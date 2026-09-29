import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
PLAYLIST_FILE = BASE_DIR / "data" / "playlists.json"
LOG_FILE = BASE_DIR / "recommendation_log.xlsx"


def secret(key, default=""):
    try:
        value = st.secrets.get(key, default)
    except Exception:
        value = os.environ.get(key, default)
    return value if value is not None else default


def load_playlists():
    try:
        return json.loads(PLAYLIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


PLAYLISTS = load_playlists()

# The DJ works as a recommender over the user's own curated playlists.
# It does not generate or download music; it interprets the request and routes
# the listener to an appropriate YouTube playlist.
PLAYLIST_PROFILES = {
    "Rabindra Sangeet": {"energy": 2, "warmth": 5, "dance": 1, "nostalgia": 5, "festive": 3, "tags": {"calm", "reflective", "poetic", "rabindra", "nostalgic"}},
    "Bangla Nostalgia": {"energy": 2, "warmth": 5, "dance": 2, "nostalgia": 5, "festive": 3, "tags": {"nostalgia", "memory", "adda", "classic", "old", "romantic"}},
    "Bangla Dance Number": {"energy": 5, "warmth": 4, "dance": 5, "nostalgia": 2, "festive": 5, "tags": {"dance", "party", "energetic", "pandal", "celebration", "fun"}},
    "Bangla Rock": {"energy": 5, "warmth": 3, "dance": 3, "nostalgia": 3, "festive": 4, "tags": {"rock", "guitar", "band", "energetic", "loud", "pandal"}},
    "Pujor Gaan": {"energy": 4, "warmth": 5, "dance": 3, "nostalgia": 4, "festive": 5, "tags": {"puja", "durga", "festive", "dhak", "pandal", "sharodiya"}},
    "Mahalaya": {"energy": 2, "warmth": 5, "dance": 1, "nostalgia": 5, "festive": 5, "tags": {"mahalaya", "agamani", "dawn", "morning", "chanting", "devotional", "shubho"}},
}

KEYWORD_HINTS = {
    "rock": {"energy": 5, "tags": {"rock", "guitar", "band"}},
    "guitar": {"energy": 5, "tags": {"rock", "guitar"}},
    "energetic": {"energy": 5, "dance": 4, "tags": {"energetic"}},
    "energy": {"energy": 5},
    "dance": {"dance": 5, "energy": 5, "tags": {"dance"}},
    "party": {"dance": 5, "energy": 5, "tags": {"party"}},
    "pandal": {"festive": 5, "energy": 4, "tags": {"pandal"}},
    "puja": {"festive": 5, "tags": {"puja", "festive"}},
    "durga": {"festive": 5, "tags": {"durga"}},
    "mahalaya": {"festive": 5, "nostalgia": 5, "tags": {"mahalaya", "agamani"}},
    "agamani": {"festive": 5, "nostalgia": 5, "tags": {"agamani"}},
    "morning": {"energy": 2, "warmth": 5, "tags": {"morning", "dawn"}},
    "ভোর": {"energy": 2, "warmth": 5, "tags": {"morning", "dawn"}},
    "সকাল": {"energy": 2, "warmth": 5, "tags": {"morning", "dawn"}},
    "nostalgia": {"nostalgia": 5, "tags": {"nostalgia", "memory"}},
    "নস্টালজিয়া": {"nostalgia": 5, "tags": {"nostalgia", "memory"}},
    "old": {"nostalgia": 5, "tags": {"old", "classic"}},
    "adda": {"warmth": 5, "nostalgia": 4, "tags": {"adda"}},
    "শান্ত": {"energy": 1, "warmth": 5, "tags": {"calm", "reflective"}},
    "calm": {"energy": 1, "warmth": 5, "tags": {"calm", "reflective"}},
    "devotional": {"energy": 2, "festive": 5, "tags": {"devotional", "chanting"}},
    "মন্ত্র": {"energy": 1, "festive": 5, "tags": {"chanting", "devotional"}},
}


def _fallback_analysis(prompt):
    text = prompt.lower()
    dims = {"energy": 3, "warmth": 3, "dance": 2, "nostalgia": 2, "festive": 3}
    tags = set()
    hits = 0
    for word, hint in KEYWORD_HINTS.items():
        if word in text:
            hits += 1
            for key in dims:
                if key in hint:
                    dims[key] = max(dims[key], hint[key])
            tags.update(hint.get("tags", set()))
    return dims, tags, hits


def _rank_playlists(dims, tags):
    ranked = []
    for name, profile in PLAYLIST_PROFILES.items():
        if name not in PLAYLISTS:
            continue
        score = 0.0
        for dim in ("energy", "warmth", "dance", "nostalgia", "festive"):
            score += max(0, 5 - abs(dims[dim] - profile[dim]))
        score += 3.0 * len(tags.intersection(profile["tags"]))
        ranked.append((score, name))
    ranked.sort(reverse=True)
    return ranked


def _gemini_analysis(prompt):
    key = secret("GEMINI_API_KEY")
    if not key:
        return None

    playlist_names = list(PLAYLISTS)
    instruction = (
        "You are the AI DJ for Bangalir Utsav, a Bengali Durga Puja nostalgia site. "
        "Choose only from these curated playlists: " + ", ".join(playlist_names) + ". "
        "Interpret the user's request using five dimensions from 1-5: energy, warmth, dance, nostalgia, festive. "
        "Return JSON only with keys primary_playlist, secondary_playlist, energy, warmth, dance, nostalgia, festive, commentary. "
        "primary_playlist and secondary_playlist must be exact playlist names from the supplied list. "
        "Keep commentary under 180 characters. User request: " + prompt
    )
    payload = {
        "contents": [{"parts": [{"text": instruction}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "primary_playlist": {"type": "STRING", "enum": playlist_names},
                    "secondary_playlist": {"type": "STRING", "enum": playlist_names},
                    "energy": {"type": "INTEGER", "minimum": 1, "maximum": 5},
                    "warmth": {"type": "INTEGER", "minimum": 1, "maximum": 5},
                    "dance": {"type": "INTEGER", "minimum": 1, "maximum": 5},
                    "nostalgia": {"type": "INTEGER", "minimum": 1, "maximum": 5},
                    "festive": {"type": "INTEGER", "minimum": 1, "maximum": 5},
                    "commentary": {"type": "STRING"},
                },
                "required": ["primary_playlist", "secondary_playlist", "energy", "warmth", "dance", "nostalgia", "festive", "commentary"],
            },
        },
    }
    try:
        response = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
            params={"key": key}, json=payload, timeout=15,
        )
        response.raise_for_status()
        raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(raw)
    except Exception:
        return None


def _log_recommendation(row):
    try:
        if LOG_FILE.exists():
            old = pd.read_excel(LOG_FILE)
            pd.concat([old, pd.DataFrame([row])], ignore_index=True).to_excel(LOG_FILE, index=False)
        else:
            pd.DataFrame([row]).to_excel(LOG_FILE, index=False)
    except Exception:
        fallback = LOG_FILE.with_suffix(".csv")
        try:
            old = pd.read_csv(fallback) if fallback.exists() else pd.DataFrame()
            pd.concat([old, pd.DataFrame([row])], ignore_index=True).to_csv(fallback, index=False)
        except Exception:
            pass


def get_ai_chat_recommendation(prompt):
    prompt = (prompt or "").strip()
    if not prompt:
        return {"category": "Pujor Gaan", "playlist_name": "Pujor Gaan", "response": "একটি পুজোর গান বেছে নেওয়া হয়েছে।", "playlist_id": PLAYLISTS.get("Pujor Gaan", {}).get("playlist_id", "")}

    dims, tags, hits = _fallback_analysis(prompt)
    ranked = _rank_playlists(dims, tags)
    fallback_primary = ranked[0][1] if ranked else "Pujor Gaan"
    fallback_secondary = ranked[1][1] if len(ranked) > 1 else fallback_primary

    ai = _gemini_analysis(prompt)
    if ai and ai.get("primary_playlist") in PLAYLISTS:
        primary = ai["primary_playlist"]
        secondary = ai.get("secondary_playlist") if ai.get("secondary_playlist") in PLAYLISTS else fallback_secondary
        dims = {k: int(ai.get(k, dims[k])) for k in ("energy", "warmth", "dance", "nostalgia", "festive")}
        commentary = ai.get("commentary") or f"তোমার vibe-এর জন্য {PLAYLISTS[primary]['title_bn']} বেছে নেওয়া হয়েছে।"
        source = "gemini"
    else:
        primary, secondary = fallback_primary, fallback_secondary
        commentary = f"তোমার vibe-এর সঙ্গে {PLAYLISTS[primary]['title_bn']} সবচেয়ে ভালোভাবে মেলে।"
        source = "local-fallback"

    playlist_id = PLAYLISTS[primary]["playlist_id"]
    result = {
        "category": primary,
        "playlist_name": primary,
        "playlist_id": playlist_id,
        "secondary_playlist": secondary,
        "energy": dims["energy"],
        "warmth": dims["warmth"],
        "dance": dims["dance"],
        "nostalgia": dims["nostalgia"],
        "festive": dims["festive"],
        "response": commentary,
        "source": source,
        "matched_keywords": sorted(tags),
    }

    _log_recommendation({
        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "User_Prompt": prompt,
        "AI_Analysis": commentary,
        "Primary_Playlist": primary,
        "Secondary_Playlist": secondary,
        "Playlist_ID": playlist_id,
        "Energy": dims["energy"],
        "Warmth": dims["warmth"],
        "Dance": dims["dance"],
        "Nostalgia": dims["nostalgia"],
        "Festive": dims["festive"],
        "Source": source,
    })
    return result
