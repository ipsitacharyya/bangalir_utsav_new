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
LOCATION_RPC = "record_location"


class PersistenceError(RuntimeError):
    """Raised when Supabase is configured but a database operation fails."""


def _load_project_secret_file():
    """Load the project's example secrets file as a local/server fallback.

    Streamlit only auto-loads .streamlit/secrets.production.toml. The project was
    previously using .streamlit/secrets.production.toml.example, so those values were
    invisible to st.secrets and the app incorrectly selected local storage.
    This fallback keeps the existing deployment layout working.
    """
    if tomllib is None:
        return {}
    path = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.production.toml"
    if not path.exists():
        return {}
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def secret(key, default=""):
    # 1) Streamlit's real secrets.production.toml / Streamlit Cloud Secrets
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
            json.dumps({"pushpanjali_count": DEFAULT_COUNT, "location_stats": {}}),
            encoding="utf-8",
        )
    try:
        data = json.loads(LOCAL.read_text(encoding="utf-8"))
    except Exception:
        return {"pushpanjali_count": DEFAULT_COUNT, "location_stats": {}}

    # One-time local migration from the previous append-only location list.
    if "location_stats" not in data and data.get("locations"):
        stats = {}
        for item in data.get("locations", []):
            location = " ".join(str(item.get("location", "")).strip().split())
            if not location:
                continue
            key = _location_key(location)
            row = stats.setdefault(
                key,
                {
                    "location": location,
                    "counter": 0,
                    "first_seen": item.get("created_at", ""),
                    "last_seen": item.get("created_at", ""),
                },
            )
            row["counter"] += 1
            created_at = item.get("created_at", "")
            if created_at:
                if not row.get("first_seen") or created_at < row["first_seen"]:
                    row["first_seen"] = created_at
                if created_at > row.get("last_seen", ""):
                    row["last_seen"] = created_at
        data["location_stats"] = stats
        data.pop("locations", None)
        LOCAL.write_text(json.dumps(data), encoding="utf-8")

    data.setdefault("location_stats", {})
    return data


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


def _location_key(location: str) -> str:
    """Create a stable, human-readable aggregation key without storing coordinates."""
    return " ".join(str(location).strip().casefold().split())


def publish_location(location: str):
    """Atomically increment an aggregated location counter and return the updated row."""
    location = " ".join(str(location).strip().split())
    if not location:
        return None

    now = datetime.now(timezone.utc).isoformat()

    if not supabase_enabled():
        data = local()
        stats = data.setdefault("location_stats", {})
        key = _location_key(location)
        item = stats.get(key)
        if item is None:
            item = {
                "location": location,
                "counter": 0,
                "first_seen": now,
            }
        item["counter"] = int(item.get("counter", 0)) + 1
        item["last_seen"] = now
        stats[key] = item
        # Keep the fallback compact: one row per normalized location.
        data.pop("locations", None)
        LOCAL.write_text(json.dumps(data), encoding="utf-8")
        return dict(item)

    response = _request(
        "POST",
        f"/rest/v1/rpc/{LOCATION_RPC}",
        headers=headers("return=representation"),
        json={"p_location": location},
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise PersistenceError("Location RPC returned invalid JSON.") from exc

    # Depending on the Supabase/PostgREST response configuration, a
    # successful record_location() RPC may return the updated row, a one-row
    # array, or a scalar counter. The database write has already succeeded in
    # all of these cases. Accept the scalar form as a successful submission
    # instead of showing a false error to the visitor.
    if isinstance(payload, list):
        row = payload[0] if payload else None
        if isinstance(row, dict):
            return row
        if isinstance(row, (int, float)) and not isinstance(row, bool):
            return {
                "location": location,
                "counter": int(row),
                "last_seen": now,
            }
    elif isinstance(payload, dict):
        return payload
    elif isinstance(payload, (int, float)) and not isinstance(payload, bool):
        return {
            "location": location,
            "counter": int(payload),
            "last_seen": now,
        }

    # A successful RPC can also return an empty body. Since the HTTP status
    # check above already confirmed success, treat it as a successful
    # submission rather than raising a misleading error popup.
    if payload is None:
        return {
            "location": location,
            "counter": 1,
            "last_seen": now,
        }

    raise PersistenceError(
        f"Location RPC returned an unexpected response: {payload!r}"
    )


def get_location_stats(limit=50):
    """Return aggregate location rows, newest activity first."""
    limit = max(1, min(int(limit), 200))
    if not supabase_enabled():
        rows = list(local().get("location_stats", {}).values())
        rows.sort(key=lambda x: x.get("last_seen", ""), reverse=True)
        return rows[:limit]

    response = _request(
        "GET",
        f"/rest/v1/location_stats?select=location,counter,first_seen,last_seen"
        f"&order=last_seen.desc&limit={limit}",
    )
    return response.json()


def get_location_participant_count() -> int:
    """Total submissions to date = sum of all aggregated location counters."""
    if not supabase_enabled():
        return sum(
            int(row.get("counter", 0))
            for row in local().get("location_stats", {}).values()
        )

    response = _request(
        "GET",
        "/rest/v1/location_stats?select=counter",
    )
    return sum(int(row.get("counter", 0)) for row in response.json())


def get_unique_location_count() -> int:
    """Number of distinct normalized locations represented in the aggregate table."""
    if not supabase_enabled():
        return len(local().get("location_stats", {}))

    response = _request(
        "GET",
        "/rest/v1/location_stats?select=location",
    )
    return len(response.json())


def get_latest_location_event():
    """Return the newest aggregate update so active clients can show a short popup."""
    if not supabase_enabled():
        rows = get_location_stats(1)
        if not rows:
            return None
        row = rows[0]
        return {
            "location": row.get("location", ""),
            "counter": int(row.get("counter", 0)),
            "last_seen": row.get("last_seen", ""),
        }

    response = _request(
        "GET",
        "/rest/v1/location_stats?"
        "select=location,counter,last_seen"
        "&order=last_seen.desc&limit=1",
    )
    rows = response.json()
    if not rows:
        return None
    row = rows[0]
    return {
        "location": row.get("location", ""),
        "counter": int(row.get("counter", 0)),
        "last_seen": row.get("last_seen", ""),
    }


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
