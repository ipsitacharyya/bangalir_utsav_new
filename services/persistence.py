import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
import streamlit as st

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

LOCAL = Path("data/site_state.json")
DEFAULT_COUNT = 14290
STATE_ID = 1
RPC_INCREMENT = "increment_pushpanjali"


class PersistenceError(RuntimeError):
    """Raised when Supabase is configured but a database operation fails."""


def _load_project_secret_file():
    """Load the project's example secrets file as a local/server fallback.

    Streamlit only auto-loads .streamlit/secrets.toml. The project was
    previously using .streamlit/secrets.toml.example, so those values were
    invisible to st.secrets and the app incorrectly selected local storage.
    This fallback keeps the existing deployment layout working.
    """
    if tomllib is None:
        return {}
    path = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
    if not path.exists():
        return {}
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def secret(key, default=""):
    # 1) Streamlit's real secrets.toml / Streamlit Cloud Secrets
    try:
        value = st.secrets.get(key, None)
        if value not in (None, ""):
            return value
    except Exception:
        pass

    # 2) Environment variables (useful for servers/containers)
    value = os.environ.get(key)
    if value not in (None, ""):
        return value

    # 3) Backward-compatible project fallback requested for this deployment
    value = _load_project_secret_file().get(key)
    if value not in (None, ""):
        return value

    return default


def get_base_url():
    url = str(secret("SUPABASE_URL", "")).strip()
    if url.endswith("/rest/v1/"):
        url = url[:-9]
    elif url.endswith("/rest/v1"):
        url = url[:-8]
    return url.rstrip("/")


def supabase_enabled():
    return bool(get_base_url() and secret("SUPABASE_KEY"))


def headers(prefer=None):
    key = str(secret("SUPABASE_KEY", "")).strip()
    result = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        result["Prefer"] = prefer
    return result


def _request(method, path, **kwargs):
    url = f"{get_base_url()}{path}"
    kwargs.setdefault("headers", headers())
    kwargs.setdefault("timeout", 10)
    try:
        response = requests.request(method, url, **kwargs)
    except requests.RequestException as exc:
        raise PersistenceError(f"Could not reach Supabase: {exc}") from exc

    if not 200 <= response.status_code < 300:
        detail = response.text.strip().replace("\n", " ")[:500]
        raise PersistenceError(
            f"Supabase returned HTTP {response.status_code}: {detail or 'no response body'}"
        )
    return response


def local():
    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    if not LOCAL.exists():
        LOCAL.write_text(
            json.dumps({"pushpanjali_count": DEFAULT_COUNT, "locations": []}),
            encoding="utf-8",
        )
    try:
        return json.loads(LOCAL.read_text(encoding="utf-8"))
    except Exception:
        return {"pushpanjali_count": DEFAULT_COUNT, "locations": []}


def persistence_mode():
    return "Supabase" if supabase_enabled() else "Local fallback"


def get_pushpanjali_count() -> int:
    if not supabase_enabled():
        return int(local().get("pushpanjali_count", DEFAULT_COUNT))

    response = _request(
        "GET",
        f"/rest/v1/puja_state?id=eq.{STATE_ID}&select=pushpanjali_count",
    )
    rows = response.json()
    if not rows:
        raise PersistenceError(
            "Supabase table 'puja_state' has no row with id=1. Run database/migration.sql."
        )
    try:
        return int(rows[0]["pushpanjali_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PersistenceError("Invalid pushpanjali_count in Supabase.") from exc


def increment_pushpanjali() -> int:
    if not supabase_enabled():
        data = local()
        data["pushpanjali_count"] = int(data.get("pushpanjali_count", DEFAULT_COUNT)) + 1
        LOCAL.write_text(json.dumps(data), encoding="utf-8")
        return data["pushpanjali_count"]

    # Atomic database-side increment. This avoids lost updates when multiple
    # visitors click the bell at the same time.
    response = _request(
        "POST",
        f"/rest/v1/rpc/{RPC_INCREMENT}",
        headers=headers("return=representation"),
        json={},
    )
    # PostgREST can return a scalar for a SQL function whose return type is
    # bigint. Depending on the PostgREST/Supabase version and Prefer header,
    # the same RPC may also be represented as a one-row array or an object.
    # Accept all of those valid response shapes.
    try:
        payload = response.json()
    except ValueError as exc:
        detail = response.text.strip()[:300]
        raise PersistenceError(
            f"Supabase increment returned invalid JSON: {detail or 'empty response'}"
        ) from exc

    value = None
    if isinstance(payload, (int, float, str)) and not isinstance(payload, bool):
        value = payload
    elif isinstance(payload, list) and payload:
        value = payload[0]
        if isinstance(value, dict):
            value = value.get("pushpanjali_count", value.get("increment_pushpanjali"))
    elif isinstance(payload, dict):
        value = payload.get("pushpanjali_count", payload.get("increment_pushpanjali"))

    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise PersistenceError(
                f"Supabase increment returned a non-numeric count: {value!r}"
            ) from exc

    raise PersistenceError(
        f"Supabase increment returned an unexpected response: {payload!r}"
    )


def publish_location(location: str):
    location = str(location).strip()
    if not location:
        return

    if not supabase_enabled():
        data = local()
        data.setdefault("locations", []).append(
            {"location": location, "created_at": datetime.now(timezone.utc).isoformat()}
        )
        data["locations"] = data["locations"][-30:]
        LOCAL.write_text(json.dumps(data), encoding="utf-8")
        return

    _request(
        "POST",
        "/rest/v1/live_locations",
        headers=headers("return=minimal"),
        json={"location": location},
    )


def get_locations(limit=30):
    limit = max(1, min(int(limit), 100))
    if not supabase_enabled():
        return [x.get("location", "") for x in local().get("locations", [])[-limit:]]

    response = _request(
        "GET",
        f"/rest/v1/live_locations?select=location&order=created_at.desc&limit={limit}",
    )
    return [x["location"] for x in response.json() if x.get("location")]


def get_latest_location_event():
    """Return the newest broadcast event with its timestamp for live clients."""
    if not supabase_enabled():
        items = local().get("locations", [])
        if not items:
            return None
        item = items[-1]
        return {
            "location": item.get("location", ""),
            "created_at": item.get("created_at", ""),
        }

    response = _request(
        "GET",
        "/rest/v1/live_locations?select=location,created_at&order=created_at.desc&limit=1",
    )
    rows = response.json()
    if not rows:
        return None
    row = rows[0]
    return {"location": row.get("location", ""), "created_at": row.get("created_at", "")}


def submit_song_request(title, artist, url, location):
    webhook = secret("SONG_REQUEST_WEBHOOK")
    if not webhook:
        return False, "Configure SONG_REQUEST_WEBHOOK in Streamlit Secrets first."
    try:
        r = requests.post(
            webhook,
            json={
                "song_title": title,
                "artist": artist,
                "youtube_url": url,
                "location": location,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            timeout=10,
        )
        return (
            (True, "Request sent — thank you! 🌺")
            if 200 <= r.status_code < 300
            else (False, "Request service returned an error.")
        )
    except requests.RequestException:
        return False, "Could not reach the request service."
