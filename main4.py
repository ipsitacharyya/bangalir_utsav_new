import base64
import os
import json
from datetime import datetime, date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from ai_backend import get_ai_chat_recommendation, PLAYLISTS
from services.persistence import (
    get_pushpanjali_count,
    increment_pushpanjali,
    publish_location,
    get_locations,
    get_latest_location_event,
    submit_song_request,
    PersistenceError,
    supabase_enabled,
)

st.set_page_config(
    page_title="বাঙালির উৎসব, বাঙালির গান",
    page_icon="🔔",
    layout="wide",
    initial_sidebar_state="collapsed",
)

RADIO_STATIONS = {
    "AIR FM Rainbow Kolkata": "https://airhlspush.pc.cdn.bitgravity.com/httppush/hlspbaudio004/hlspbaudio00464kbps.m3u8",
    "Radio Mirchi 98.3 FM": "https://eu8.fastcast4u.com/proxy/clyedupq/stream",
}

CURATED_PLAYLISTS = {
    name: (data.get("title_bn", name), data.get("playlist_id", ""))
    for name, data in PLAYLISTS.items()
}

PUJO_TV_PLAYLISTS = {
    "Pujo Parikrama": ("পুজো পরিক্রমা · Pujo Parikrama", "PLfTjRpsb1rY8"),
    "Pujo Documentaries": ("পুজো তথ্যচিত্র · Pujo Documentaries", "PLecb9cZC82BA"),
    "Pujo Vlogs": ("পুজো ভ্লগ · Pujo Vlogs", "PLJqqjUoAyYQc"),
    "Pujo Food Vlogs": ("পুজোর খাবার · Pujo Food Vlogs", "PLE5h4EdnvhlE"),
    "Bhasan": ("বিসর্জন · Bhasan", "PLfVh5eUbKEO8"),
}

SOUNDS = [
    ("🥁", "ঢাক", "DHAK", "ঢাকের তালে পুজোর প্যান্ডালের প্রাণবন্ত আবহ।", "dhak.mp3"),
    ("🪘", "কাঁসর", "KANSAR", "কাঁসরের ধাতব অনুরণন ও আরতির আবহ।", "kansar.mp3"),
    ("🔔", "ঘণ্টা", "BELL", "পুজোর ঘণ্টাধ্বনি ও আরতির পবিত্র পরিবেশ।", "bell.mp3"),
    ("🕉️", "মন্ত্র", "CHANTING", "মন্ত্রোচ্চারণের শান্ত ও ধ্যানমগ্ন আবহ।", "chanting.mp3"),
    ("✨", "আতশবাজি", "FIREWORKS", "উৎসবের রাতের আতশবাজির উচ্ছ্বাস।", "fireworks.mp3"),
    ("🗣️", "হুল্লোড়", "CROWD", "প্যান্ডালের ভিড়, আড্ডা ও উৎসবের সম্মিলিত শব্দ।", "crowd.mp3"),
]

# -----------------------------------------------------------------------------
# Asset helpers
# -----------------------------------------------------------------------------
def b64(path):
    try:
        return base64.b64encode((BASE_DIR / path).read_bytes()).decode() if not Path(path).is_absolute() else base64.b64encode(Path(path).read_bytes()).decode()
    except Exception:
        return ""

def img_uri(path):
    p = Path(path)
    if not p.is_absolute():
        p = BASE_DIR / p
    if not p.exists():
        return ""
    ext = p.suffix.lower()
    mime = "image/png" if ext == ".png" else "image/jpeg" if ext in {".jpg", ".jpeg"} else "image/webp"
    return f"data:{mime};base64,{b64(p)}"

def first_existing(*paths):
    for p in paths:
        candidate = Path(p)
        if not candidate.is_absolute():
            candidate = BASE_DIR / candidate
        if candidate.exists():
            return str(candidate)
    return str(paths[0]) if paths else ""

def img_uri_candidates(*paths):
    """Return the first usable image URI, including case-insensitive filename matching."""
    for raw in paths:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = BASE_DIR / candidate
        if candidate.exists() and candidate.is_file():
            uri = img_uri(candidate)
            if uri:
                return uri
        parent = candidate.parent
        wanted = candidate.name.lower()
        if parent.exists():
            for item in parent.iterdir():
                if item.is_file() and item.name.lower() == wanted:
                    uri = img_uri(item)
                    if uri:
                        return uri
    return ""

ASSET = {
    "hero": img_uri_candidates("assets/hero_durga_puja.PNG", "assets/hero_durga_puja.png", "assets/bg_durga.jpg"),
    "featured": img_uri("assets/puja_song_featured.PNG"),
    "agomoni": img_uri("assets/playlist_agomoni.PNG"),
    "classics": img_uri("assets/playlist_bengali_classics.PNG"),
    "dhak": img_uri("assets/playlist_dhak_beats.PNG"),
    "indie": img_uri("assets/playlist_pujo_indie.PNG"),
    "tv": img_uri("assets/pujo_tv.PNG"),
    "radio": img_uri("assets/pujo_radio.PNG"),
    "sound": img_uri("assets/pujo_sound.PNG"),
    "community": img_uri("assets/community_puja.PNG"),
    "footer_left": img_uri("assets/footer_diya.PNG"),
    "footer_right": img_uri("assets/footer_dhak.PNG"),
    "push_bell": img_uri_candidates("assets/bell_icon.PNG", "assets/bell_icon.png"),
}

# -----------------------------------------------------------------------------
# Session state
# -----------------------------------------------------------------------------
if "active_section" not in st.session_state:
    st.session_state.active_section = "Puja Songs"
if "active_playlist" not in st.session_state:
    st.session_state.active_playlist = next(iter(CURATED_PLAYLISTS))
if "active_tv_playlist" not in st.session_state:
    st.session_state.active_tv_playlist = next(iter(PUJO_TV_PLAYLISTS))
if "ai_result" not in st.session_state:
    st.session_state.ai_result = None
if "expanded_sound" not in st.session_state:
    st.session_state.expanded_sound = None
if "popup_message" not in st.session_state:
    st.session_state.popup_message = None
if "popup_kind" not in st.session_state:
    st.session_state.popup_kind = "flower"
if "last_location_event_id" not in st.session_state:
    st.session_state.last_location_event_id = None
if "scroll_target" not in st.session_state:
    st.session_state.scroll_target = None
if "last_section_q" not in st.session_state:
    st.session_state.last_section_q = None
if "pushpanjali_count" not in st.session_state:
    try:
        st.session_state.pushpanjali_count = get_pushpanjali_count()
        st.session_state.persistence_error = None
    except PersistenceError as exc:
        st.session_state.pushpanjali_count = 0
        st.session_state.persistence_error = str(exc)

# Query links are same-tab navigation only. They also set the exact player scroll target.
section_q = st.query_params.get("section")
if section_q in {"songs", "sounds", "radio", "tv"}:
    mapping = {"songs": "Puja Songs", "sounds": "Puja Sound", "radio": "Live Radio", "tv": "Pujo TV"}
    st.session_state.active_section = mapping[section_q]
    if section_q != st.session_state.last_section_q:
        st.session_state.scroll_target = {
            "songs": "songs-player",
            "sounds": "sounds-player",
            "radio": "radio-player",
            "tv": "tv-player",
        }[section_q]
        st.session_state.last_section_q = section_q

panel_q = st.query_params.get("panel")
st.session_state.active_panel = panel_q if panel_q in {"gallery", "analytics"} else None

# -----------------------------------------------------------------------------
# Visual system — warm ivory / deep Durga red / antique gold
# -----------------------------------------------------------------------------
ALPANA_URI = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180' viewBox='0 0 180 180'%3E%3Cg fill='none' stroke='%23b37a3d' stroke-width='2' opacity='.72'%3E%3Cpath d='M8 48 Q28 20 58 8 Q36 36 8 58 M8 90 Q35 62 68 62 Q42 88 8 98 M8 132 Q34 106 64 110 Q42 134 8 144'/%3E%3Cpath d='M172 48 Q152 20 122 8 Q144 36 172 58 M172 90 Q145 62 112 62 Q138 88 172 98 M172 132 Q146 106 116 110 Q138 134 172 144'/%3E%3Ccircle cx='20' cy='24' r='6'/%3E%3Ccircle cx='160' cy='24' r='6'/%3E%3Ccircle cx='20' cy='156' r='6'/%3E%3Ccircle cx='160' cy='156' r='6'/%3E%3Cpath d='M78 8 Q90 20 102 8 M78 172 Q90 160 102 172'/%3E%3C/g%3E%3Cg fill='%23b37a3d' opacity='.55'%3E%3Ccircle cx='46' cy='24' r='3'/%3E%3Ccircle cx='134' cy='24' r='3'/%3E%3Ccircle cx='46' cy='156' r='3'/%3E%3Ccircle cx='134' cy='156' r='3'/%3E%3C/g%3E%3C/svg%3E"

st.markdown(
f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@500;600;700&family=Noto+Serif+Bengali:wght@500;600;700&family=Special+Elite&display=swap');

:root {{
    --ivory:#f8f0df; --ivory2:#fffaf0; --paper:#f4ead5;
    --red:#741522; --red2:#5b0d19; --red3:#8d1828;
    --gold:#b47a34; --gold2:#d4a45c; --ink:#4b171b; --muted:#795f57;
}}

.stApp {{
    background:
        radial-gradient(circle at 50% 0%, rgba(181,123,52,.12), transparent 28%),
        linear-gradient(180deg,#f8f0df 0%,#f5ecda 46%,#efe3cc 100%);
    color:var(--ink);
}}
.stApp::after {{
    content:"";position:fixed;inset:0;pointer-events:none;z-index:9999;opacity:.075;mix-blend-mode:multiply;
    background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
    animation:grain .18s steps(2) infinite;
}}
@keyframes grain {{50%{{transform:translate(1%,-1%)}}}}
#MainMenu,header{{visibility:hidden}}
.block-container{{max-width:1440px;padding:0 12px 0;margin:0 auto}}

/* top header */
.topbar{{width:100%;min-height:66px;background:linear-gradient(180deg,#741522,#5d0f19);border-bottom:1px solid rgba(222,177,98,.75);display:flex;align-items:center;padding:0 22px;box-shadow:0 5px 20px rgba(76,17,25,.18);position:relative;z-index:20}}
.brand,.brand:visited{{font:700 1.15rem 'Noto Serif Bengali',serif;color:#fff8e9!important;white-space:nowrap;text-decoration:none!important}}
.brand-mark{{font-size:1.35rem;margin-right:8px}}
.topnav{{margin-left:auto;display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.topnav a{{color:#fff !important;text-decoration:none !important;font:600 .82rem 'Noto Serif Bengali',serif;padding:9px 13px;border-radius:999px;border:1px solid transparent;transition:.18s}}
.topnav a:hover,.topnav a.active{{color:#fff !important;border-color:rgba(239,201,132,.55);background:rgba(255,255,255,.09)}}

/* hero */
.hero-banner{{position:relative;width:100%;min-height:455px;border-radius:0 0 20px 20px;overflow:hidden;background-position:center;background-size:cover;background-repeat:no-repeat;background-color:#5b0d19;display:grid;grid-template-columns:minmax(0,1.45fr) minmax(270px,.55fr);align-items:center;padding:54px clamp(24px,6vw,82px) 0;box-shadow:0 14px 35px rgba(73,25,27,.2)}}
.hero-bg{{display:none}}
.hero-banner:after{{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(52,6,14,.93) 0%,rgba(73,10,17,.76) 38%,rgba(55,7,14,.20) 70%,rgba(55,7,14,.38) 100%);z-index:1}}
.hero-copy,.hero-count{{position:relative;z-index:2}}
.hero-kicker{{font:600 .68rem 'Cinzel',serif;letter-spacing:3px;color:#e8c17b;text-transform:uppercase;margin-bottom:10px}}
.hero-title{{font:700 clamp(2.7rem,6vw,5.8rem)/1.02 'Noto Serif Bengali',serif;color:#fff8e9;max-width:760px;text-shadow:0 5px 24px rgba(0,0,0,.4)}}
.hero-sub{{font:500 clamp(.95rem,1.5vw,1.15rem)/1.7 'Noto Serif Bengali',serif;color:#f5ddc2;max-width:700px;margin:18px 0 24px}}
.hero-actions{{display:flex;gap:12px;flex-wrap:wrap}}
.hero-btn{{display:inline-block;padding:12px 22px;border-radius:999px;border:1px solid #efc77f;text-decoration:none;color:#fff8e9!important;background:rgba(116,21,34,.82);font:600 .84rem 'Noto Serif Bengali',serif}}
.hero-btn.primary{{background:#f1c56f;color:#5e101a!important;border-color:#f1c56f}}
.hero-count{{justify-self:end;align-self:end;width:min(100%,310px);padding:26px 20px;text-align:center;border:1px solid rgba(239,199,127,.8);border-radius:20px;background:linear-gradient(145deg,rgba(83,12,22,.82),rgba(55,7,14,.72));box-shadow:inset 0 0 0 1px rgba(255,235,185,.08),0 15px 30px rgba(45,6,12,.24);margin-bottom:-1px}}
.hero-count .small{{font:600 .72rem 'Cinzel',serif;letter-spacing:2px;color:#e9c47d}}
.hero-count .main{{font:700 clamp(3rem,6vw,5rem)/1 'Noto Serif Bengali',serif;color:#fff8e9;margin:10px 0 4px}}
.hero-count .date{{font:500 .8rem 'Noto Serif Bengali',serif;color:#f2d7bb}}

/* pushpanjali */
.puja-wrap{{padding:18px 8px 8px;text-align:center;background:rgba(255,250,240,.58);border-bottom:1px solid rgba(180,122,52,.25)}}
.puja-counter{{display:flex;justify-content:center;gap:7px;align-items:center;font:500 .88rem 'Noto Serif Bengali',serif;color:#6b302d}}
.puja-counter strong{{font-size:1.15rem;color:var(--red)}}
[class*="st-key-push_bell_container"]{{width:100%!important;display:flex!important;justify-content:center!important;align-items:center!important;margin:2px auto!important}}
[class*="st-key-push_bell_container"] [data-testid="stButton"]{{width:48px!important;margin:auto!important}}
[class*="st-key-push_bell_container"] [data-testid="stButton"]>button{{width:48px!important;height:48px!important;padding:0!important;border:0!important;background-color:transparent!important;background-image:url("{ASSET['push_bell']}")!important;background-repeat:no-repeat!important;background-position:center!important;background-size:36px 36px!important;box-shadow:none!important;font-size:0!important;color:transparent!important;text-indent:-9999px!important}}
[class*="st-key-push_bell_container"] [data-testid="stButton"]>button:hover{{transform:scale(1.12);background:transparent!important}}
[class*="st-key-v2_loc"]{{margin-top:14px!important}}
.push-text{{font:500 .72rem 'Cinzel',serif;letter-spacing:1.4px;color:#86645b}}

/* four navigation tabs */
.section-nav{{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid rgba(180,122,52,.45);border-radius:999px;overflow:hidden;background:rgba(255,250,240,.78);margin:20px 0 18px;box-shadow:0 6px 18px rgba(75,26,29,.08)}}
.section-nav a{{display:flex;justify-content:center;align-items:center;min-height:48px;color:var(--ink)!important;text-decoration:none;font:600 .85rem 'Noto Serif Bengali',serif;border-right:1px solid rgba(180,122,52,.25)}}
.section-nav a:last-child{{border-right:0}}
.section-nav a.active{{background:var(--red);color:#fff7e8!important}}
.section-nav a:hover{{background:rgba(116,21,34,.09)}}

/* section surfaces */
.page-section{{position:relative;background:rgba(255,250,240,.72);border:1px solid rgba(180,122,52,.45);border-radius:20px;padding:24px;margin:0 0 18px;box-shadow:0 8px 24px rgba(73,25,27,.08);overflow:hidden}}
.page-section:before,.page-section:after{{content:"";position:absolute;width:150px;height:150px;background-image:url("{ALPANA_URI}");background-size:contain;background-repeat:no-repeat;pointer-events:none;opacity:.72}}
.page-section:before{{top:0;left:0}}
.page-section:after{{right:0;bottom:0;transform:rotate(180deg)}}
.loc-card{{margin-bottom:10px!important}}
.section-head{{display:flex;justify-content:space-between;gap:14px;align-items:flex-end;margin-bottom:16px;position:relative;z-index:1}}
.kicker{{font:600 .67rem 'Cinzel',serif;letter-spacing:2.2px;color:#a56532;text-transform:uppercase}}
.section-title{{font:700 clamp(1.45rem,2.5vw,2.1rem) 'Noto Serif Bengali',serif;color:var(--ink);margin-top:2px}}
.section-desc{{font:500 .84rem/1.65 'Noto Serif Bengali',serif;color:var(--muted);max-width:850px}}
.ornament-rule{{height:10px;margin:10px 0 18px;background:linear-gradient(90deg,transparent,rgba(180,122,52,.65),transparent);position:relative}}
.ornament-rule:after{{content:"✦  ❈  ✦";position:absolute;left:50%;top:-7px;transform:translateX(-50%);padding:0 12px;background:#f8f0df;color:#9d6631;font-size:12px;letter-spacing:6px}}

/* featured song / AI DJ */
.feature-grid{{display:grid;grid-template-columns:1.2fr .8fr;gap:18px}}
.feature-song{{display:grid;grid-template-columns:175px minmax(0,1fr);gap:18px;align-items:center}}
.feature-img{{width:100%;aspect-ratio:1;object-fit:cover;border-radius:14px;border:1px solid rgba(180,122,52,.55);box-shadow:0 8px 20px rgba(75,25,29,.16)}}
.feature-title{{font:700 1.8rem 'Noto Serif Bengali',serif;color:var(--ink)}}
.ai-box{{height:100%;background:linear-gradient(145deg,rgba(116,21,34,.08),rgba(255,255,255,.18));border:1px solid rgba(180,122,52,.45);border-radius:16px;padding:22px;position:relative;overflow:hidden}}
.ai-box:after{{content:"♫";position:absolute;right:18px;top:12px;color:#8d1828;font-size:3.5rem;opacity:.18}}

/* playlist image strip */
.playlist-strip{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-top:16px}}
.playlist-tile{{background:#fffaf0;border:1px solid rgba(180,122,52,.38);border-radius:14px;overflow:hidden;box-shadow:0 6px 14px rgba(73,25,27,.07)}}
.playlist-tile img{{width:100%;aspect-ratio:1;object-fit:cover;display:block}}
.playlist-tile .pname{{padding:9px 8px 10px;text-align:center;font:600 .76rem 'Noto Serif Bengali',serif;color:var(--ink);line-height:1.35}}

/* form controls */
div[data-testid="stTextInput"] div[data-baseweb="input"],div[data-testid="stTextArea"] div[data-baseweb="textarea"],div[data-baseweb="input"],div[data-baseweb="textarea"]{{background:rgba(255,250,240,.82)!important;border:1px solid rgba(180,122,52,.42)!important;box-shadow:none!important;border-radius:10px!important}}
div[data-testid="stTextInput"] input,div[data-testid="stTextArea"] textarea,input,textarea{{background:transparent!important;color:#4b171b!important;border:none!important;box-shadow:none!important;font-family:'Noto Serif Bengali',serif!important}}
div[data-baseweb="select"]>div{{background:linear-gradient(180deg,#741522,#5d0f19)!important;border:1px solid #d4a45c!important;border-radius:10px!important;color:#fff!important}}
div[data-baseweb="select"]>div,div[data-baseweb="select"]>div *{{color:#fff!important;-webkit-text-fill-color:#fff!important}}
div[data-baseweb="select"] [data-testid="stMarkdownContainer"],div[data-baseweb="select"] span,div[data-baseweb="select"] input{{color:#fff!important;-webkit-text-fill-color:#fff!important}}
ul[data-baseweb="menu"]{{background:#5d0f19!important;border:1px solid #d4a45c!important}}
ul[data-baseweb="menu"] li{{color:#fff!important;background:#5d0f19!important}}
ul[data-baseweb="menu"] li:hover,ul[data-baseweb="menu"] li[aria-selected="true"]{{color:#fff!important;background:#741522!important}}
[data-baseweb="popover"] [role="option"],[data-baseweb="popover"] [role="option"] *,div[data-baseweb="select"] input,div[data-baseweb="select"] [role="combobox"],div[data-baseweb="select"] [role="combobox"] *{{color:#fff!important;-webkit-text-fill-color:#fff!important;caret-color:#fff!important}}

div[data-testid="stButton"]>button{{border-radius:999px!important;min-height:42px!important;border:1px solid #b47a34!important;background:var(--red)!important;color:#fff7e8!important;font-family:'Noto Serif Bengali',serif!important;box-shadow:0 6px 14px rgba(116,21,34,.16)!important}}
div[data-testid="stButton"]>button:hover{{background:#8d1828!important;border-color:#d4a45c!important}}

/* four equal feature cards */
.feature-cards{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}}
.feature-card{{min-height:345px;background:linear-gradient(180deg,#741522 0%,#5e101b 100%);border:1px solid #d2a158;border-radius:17px;padding:16px;display:flex;flex-direction:column;box-shadow:0 10px 25px rgba(76,17,25,.17);position:relative;overflow:hidden}}
.feature-card:before{{content:"";position:absolute;inset:7px;border:1px solid rgba(234,198,126,.35);border-radius:12px;background-image:url("{ALPANA_URI}");background-size:170px;background-position:top left;background-repeat:no-repeat;pointer-events:none}}
.feature-card>*{{position:relative;z-index:1}}
.feature-card .icon{{font-size:1.8rem;text-align:center;margin-top:3px}}
.feature-card h3{{font:700 1.25rem 'Noto Serif Bengali',serif;color:#fff6e6;text-align:center;margin:6px 0 3px}}
.feature-card p{{font:500 .74rem/1.55 'Noto Serif Bengali',serif;color:#f1d9c0;text-align:center;margin:0 0 10px}}
.feature-card img{{width:100%;height:125px;object-fit:cover;border:1px solid rgba(236,193,112,.45);border-radius:10px;margin-top:auto}}
.feature-card .card-btn{{margin:12px auto 0;background:#f0c36d;color:#5d1018;border-radius:999px;padding:8px 18px;font:600 .74rem 'Noto Serif Bengali',serif;text-decoration:none}}
.countdown-card{{justify-content:center;text-align:center}}
.countdown-card .big{{font:700 3.2rem/1 'Noto Serif Bengali',serif;color:#fff7e9;margin:8px 0}}
.countdown-card .gold{{color:#e5bd77;font:600 .7rem 'Cinzel',serif;letter-spacing:1.8px}}

/* community */
.community{{display:grid;grid-template-columns:1.15fr .85fr;gap:20px;align-items:center}}
.community img{{width:100%;height:220px;object-fit:cover;border-radius:14px;border:1px solid rgba(180,122,52,.42)}}
.avatar-row{{display:flex;align-items:center;gap:7px;margin-top:12px}}
.avatar{{width:38px;height:38px;border-radius:50%;background:linear-gradient(145deg,#8d1828,#5d1019);border:2px solid #e0b56f;color:#fff;text-align:center;padding-top:8px;font:700 .7rem Georgia,serif}}
.live-pill{{margin-left:auto;border:1px solid #a5b78f;background:#f4f8ee;color:#55733f;border-radius:999px;padding:7px 13px;font:600 .7rem 'Cinzel',serif}}

/* player area */
.player-shell{{background:linear-gradient(180deg,#7b1524,#5e101b);border:1px solid #d0a058;border-radius:20px;padding:10px;box-shadow:0 12px 28px rgba(76,17,25,.18);position:relative}}
.player-shell .player-inner{{background:#f8f0df;border-radius:15px;padding:18px;position:relative;overflow:hidden}}
.player-shell .player-inner:before{{content:"";position:absolute;inset:8px;background-image:url("{ALPANA_URI}");background-size:170px;background-repeat:no-repeat;opacity:.34;pointer-events:none}}
.player-shell .player-inner>*{{position:relative;z-index:1}}

/* client-side player tabs: only the selected player is visible, with no Streamlit rerun */
[class*="st-key-client_player_songs"],[class*="st-key-client_player_tv"],[class*="st-key-client_player_radio"],[class*="st-key-client_player_sounds"]{{display:none}}
.client-player-visible{{display:block!important}}
.playlist-display{{position:relative;background:#f8f0df;border:7px solid #741522;border-radius:18px;min-height:52px;margin:8px 0 10px;padding:10px 18px;display:flex;align-items:center;justify-content:center;text-align:center;box-shadow:0 8px 20px rgba(76,17,25,.12);overflow:hidden}}
.playlist-display:before{{content:"";position:absolute;inset:5px;background-image:url("{ALPANA_URI}");background-size:150px;background-repeat:no-repeat;background-position:left center;opacity:.28;pointer-events:none}}
.playlist-display .playlist-display-text{{position:relative;z-index:1;font:600 .72rem 'Cinzel',serif;letter-spacing:1.6px;color:#8d1828;text-transform:uppercase}}

/* sounds */
.sound-shell{{background:linear-gradient(180deg,#741522,#5b0d18);border:1px solid #d0a058;border-radius:20px;padding:18px;box-shadow:0 12px 28px rgba(76,17,25,.18);position:relative;overflow:hidden}}
.sound-shell:before{{content:"";position:absolute;inset:8px;border:1px solid rgba(238,200,129,.35);border-radius:14px;background-image:url("{ALPANA_URI}");background-size:220px;background-repeat:no-repeat;opacity:.7;pointer-events:none}}
.sound-shell>*{{position:relative;z-index:1}}
.sound-shell .section-title,.sound-shell .section-desc,.sound-shell .kicker{{color:#fff7e8}}
.sound-shell .kicker{{color:#e6bb72}}

/* footer symmetry */
.footer{{clear:both;position:relative;width:100vw;margin-left:calc(50% - 50vw);margin-top:26px;min-height:300px;overflow:hidden;background:linear-gradient(180deg,#6d101c,#4e0a14);border-top:1px solid #d6a35a;display:flex;align-items:center;justify-content:center;padding:52px 24px 38px;box-shadow:0 -12px 35px rgba(74,18,26,.18)}}
.footer:before{{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(78,10,20,.1),rgba(78,10,20,.92) 48%,rgba(78,10,20,.1));z-index:1;pointer-events:none}}
.footer-side{{position:absolute;top:0;bottom:0;width:43%;z-index:0;overflow:hidden}}
.footer-side.left{{left:0;mask-image:linear-gradient(to right,black 0%,black 45%,transparent 100%);-webkit-mask-image:linear-gradient(to right,black 0%,black 45%,transparent 100%)}}
.footer-side.right{{right:0;mask-image:linear-gradient(to left,black 0%,black 45%,transparent 100%);-webkit-mask-image:linear-gradient(to left,black 0%,black 45%,transparent 100%)}}
.footer-side img{{width:100%;height:100%;object-fit:cover;object-position:center;opacity:.52;filter:saturate(.88) sepia(.1)}}
.footer-content{{position:relative;z-index:2;width:min(760px,90%);text-align:center;color:#fff5e4;background:linear-gradient(90deg,transparent,rgba(83,10,20,.82) 14%,rgba(83,10,20,.9) 50%,rgba(83,10,20,.82) 86%,transparent);padding:12px 22px}}
.footer-content h2{{font:700 2rem 'Noto Serif Bengali',serif;margin:0 0 4px;color:#fff2d6}}
.footer-content .sub{{font:500 .78rem 'Noto Serif Bengali',serif;color:#efd5b4}}
.footer-links{{display:flex;justify-content:center;gap:20px;flex-wrap:wrap;margin:20px 0 12px}}
.footer-link{{color:#fff!important;text-decoration:none;font:600 .76rem 'Noto Serif Bengali',serif}}
.footer-link:hover{{color:#f4c978!important;text-decoration:underline}}
.footer-email{{color:#ffd17d;font:600 .78rem Arial,sans-serif;text-transform:none;margin-bottom:7px}}
.footer-meta{{color:#d9b8ad;font:500 .63rem 'Cinzel',serif;letter-spacing:1.2px;line-height:1.8}}

.footer-panel{{margin-top:18px}}

@media(max-width:1000px){{.topbar{{padding:0 12px}}.topnav a{{font-size:.75rem;padding:8px 9px}}.hero-banner{{grid-template-columns:1fr;min-height:520px}}.hero-count{{justify-self:start;margin-top:18px;width:260px}}.feature-cards{{grid-template-columns:repeat(2,minmax(0,1fr))}}.playlist-strip{{grid-template-columns:repeat(3,minmax(0,1fr))}}.community{{grid-template-columns:1fr}}}}
@media(max-width:680px){{.topbar{{min-height:58px;align-items:flex-start;padding-top:9px;padding-bottom:9px}}.brand{{font-size:.95rem}}.topnav{{justify-content:flex-end}}.topnav a{{font-size:.68rem;padding:7px 6px}}.hero-banner{{padding:34px 20px 0;min-height:550px}}.hero-title{{font-size:2.55rem}}.hero-count{{width:100%;max-width:290px}}.section-nav{{border-radius:15px;grid-template-columns:repeat(2,1fr)}}.section-nav a{{border-bottom:1px solid rgba(180,122,52,.25)}}.page-section{{padding:16px;border-radius:16px}}.feature-grid{{grid-template-columns:1fr}}.feature-song{{grid-template-columns:110px 1fr}}.playlist-strip{{grid-template-columns:repeat(2,minmax(0,1fr))}}.feature-cards{{grid-template-columns:1fr 1fr;gap:10px}}.feature-card{{min-height:320px;padding:12px}}.community img{{height:170px}}.footer{{min-height:260px;padding:35px 12px 24px}}.footer-side{{width:58%}}.footer-content{{width:96%}}}}
@media(max-width:430px){{.topnav a{{font-size:.62rem;padding:6px 4px}}.brand-mark{{display:none}}.hero-title{{font-size:2.25rem}}.hero-sub{{font-size:.86rem}}.feature-cards{{grid-template-columns:1fr}}.playlist-strip{{grid-template-columns:1fr 1fr}}.playlist-tile .pname{{font-size:.7rem}}}}
</style>""",
unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Live popup
# -----------------------------------------------------------------------------
def _render_global_popup():
    if st.session_state.get("popup_message"):
        kind = st.session_state.get("popup_kind")
        icon = "🌸" if kind == "flower" else "📍" if kind == "location" else "⚠️"
        st.markdown(
            f'<div class="global-puja-popup"><span class="flower">{icon}</span><div class="popup-title">{st.session_state.popup_message}</div><div class="popup-sub">BANGALIR UTSAV · LIVE PUJA MOMENT</div></div>',
            unsafe_allow_html=True,
        )
        st.session_state.popup_message = None

if hasattr(st, "fragment"):
    @st.fragment(run_every="3s")
    def _live_location_watcher():
        try:
            event = get_latest_location_event()
            if event:
                event_id = f"{event.get('created_at','')}|{event.get('location','')}"
                if st.session_state.last_location_event_id is None:
                    st.session_state.last_location_event_id = event_id
                elif event_id != st.session_state.last_location_event_id:
                    st.session_state.last_location_event_id = event_id
                    st.session_state.popup_message = f"📍 {event.get('location','')}"
                    st.session_state.popup_kind = "location"
                    _render_global_popup()
        except PersistenceError:
            pass
    _live_location_watcher()

# -----------------------------------------------------------------------------
# Header / hero / countdown
# -----------------------------------------------------------------------------
def days_to_mahalaya():
    today = date.today()
    target = date(2026, 10, 10)
    return max(0, (target - today).days)

countdown_days = days_to_mahalaya()
active_map = {"Puja Songs":"songs", "Puja Sound":"sounds", "Live Radio":"radio", "Pujo TV":"tv"}

st.markdown(
    f"""<div class="topbar">
        <a class="brand" target="_self" rel="nofollow" href="?section=songs#songs-player"><span class="brand-mark">🌺</span>বাঙালির উৎসব</a>
        <nav class="topnav">
            <a class="{'active' if st.session_state.active_section=='Puja Songs' else ''}" target="_self" rel="nofollow" href="?section=songs#songs-player">হোম</a>
            <a class="{'active' if st.session_state.active_section=='Puja Songs' else ''}" target="_self" rel="nofollow" href="?section=songs#songs-player">পুজোর গান</a>
            <a class="{'active' if st.session_state.active_section=='Pujo TV' else ''}" target="_self" rel="nofollow" href="?section=tv#tv-player">পুজো TV</a>
            <a class="{'active' if st.session_state.active_section=='Live Radio' else ''}" target="_self" rel="nofollow" href="?section=radio#radio-player">লাইভ রেডিও</a>
            <a class="{'active' if st.session_state.active_section=='Puja Sound' else ''}" target="_self" rel="nofollow" href="?section=sounds#sounds-player">পুজোর সাউন্ড</a>
            <a href="?panel=gallery#gallery">কমিউনিটি</a>
        </nav>
    </div>""",
    unsafe_allow_html=True,
)

hero_style = f'background-image:url("{ASSET["hero"]}")' if ASSET["hero"] else ''
st.markdown(
    f"""<section class="hero-banner" style="{hero_style}">
        <div class="hero-copy">
            <div class="hero-kicker">THE SOUL OF BENGAL · PUJA EXPERIENCE</div>
            <div class="hero-title">বাঙালির উৎসব,<br>বাঙালির গান</div>
            <div class="hero-sub">পুজোর আনন্দ, গান, আড্ডা আর আমাদের সবার — একটা ঠিকানা। কলকাতা থেকে পৃথিবীর যেকোনো প্রান্তে, পুজোর আবহ থাকুক আপনার সঙ্গেই।</div>
            <div class="hero-actions">
                <a class="hero-btn primary" target="_self" rel="nofollow" href="?section=songs#songs-player">♫ পুজোর গান শুনুন →</a>
                <a class="hero-btn" target="_self" rel="nofollow" href="?section=radio#radio-player">▣ পুজো রেডিও</a>
            </div>
        </div>
        <div class="hero-count">
            <div class="small">মহালয়া পর্যন্ত</div>
            <div class="main">আর {countdown_days} দিন</div>
            <div class="date">১০ অক্টোবর ২০২৬ · মহালয়া</div>
        </div>
    </section>""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""<div class="puja-wrap">
        <div class="puja-counter">🪔 এই মুহূর্তে পুষ্পাঞ্জলি নিবেদন করেছেন <strong>{st.session_state.pushpanjali_count}</strong> জন</div>
    </div>""",
    unsafe_allow_html=True,
)
with st.container(key="push_bell_container"):
    if st.button(" ", key="pushpanjali_btn", help="Offer Pushpanjali"):
        try:
            st.session_state.pushpanjali_count = increment_pushpanjali()
            st.session_state.persistence_error = None
            st.session_state.popup_message = "পুষ্পাঞ্জলি নিবেদন সম্পন্ন · শুভ শারদীয়া!"
            st.session_state.popup_kind = "flower"
        except PersistenceError as exc:
            st.session_state.persistence_error = str(exc)
            st.session_state.popup_message = "পুষ্পাঞ্জলি সংরক্ষণ করা যায়নি"
            st.session_state.popup_kind = "error"
_render_global_popup()
st.markdown('<div class="puja-wrap" style="padding-top:0"><div class="push-text">পুষ্পাঞ্জলি প্রদান করুন এবং পবিত্র ঘণ্টা বাজান</div></div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Main four-button navigation — same tab, exact player scroll target
# -----------------------------------------------------------------------------
nav_html = f"""<div class="section-nav" id="player-nav">
<a class="{'active' if st.session_state.active_section=='Puja Songs' else ''}" href="?section=songs#songs-player" data-player-section="songs">🎵 পুজোর গান</a>
<a class="{'active' if st.session_state.active_section=='Pujo TV' else ''}" href="?section=tv#tv-player" data-player-section="tv">📺 পুজো TV</a>
<a class="{'active' if st.session_state.active_section=='Live Radio' else ''}" href="?section=radio#radio-player" data-player-section="radio">📻 লাইভ রেডিও</a>
<a class="{'active' if st.session_state.active_section=='Puja Sound' else ''}" href="?section=sounds#sounds-player" data-player-section="sounds">🔊 পুজোর সাউন্ড</a>
</div>"""
st.markdown(nav_html, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Featured content — compact, proportionate, no large white gaps
# -----------------------------------------------------------------------------
featured_uri = ASSET["featured"]
st.markdown(
    f"""<section class="page-section">
        <div class="section-head"><div><div class="kicker">Featured</div><div class="section-title">পুজোর গান</div><div class="section-desc">শারদীয়ার সেরা গানগুলি নিয়ে আমাদের বিশেষ সংগ্রহ — আগমনী, রবীন্দ্রসঙ্গীত, ধাক আর পুজোর মুড।</div></div></div>
        <div class="ornament-rule"></div>
        <div class="feature-grid">
            <div class="feature-song">
                <img class="feature-img" src="{featured_uri}" alt="Puja song featured" />
                <div>
                    <div class="kicker">CURATED BENGALI COLLECTION</div>
                    <div class="feature-title">শারদীয়ার সেরা গানগুলি</div>
                    <div class="section-desc">আগমনী থেকে বাংলা রক — পুজোর প্রতিটি মুহূর্তের জন্য আলাদা vibe।</div>
                </div>
            </div>
            <div class="ai-box">
                <div class="kicker">AI DJ</div>
                <div class="section-title">নিজের মতো পুজোর গান</div>
                <div class="section-desc">মুড বলুন — AI DJ আপনার vibe-এর সঙ্গে মেলে এমন curated পুজোর playlist খুঁজে দেবে।</div>
            </div>
        </div>
    </section>""",
    unsafe_allow_html=True,
)

# AI input is kept outside the decorative HTML so it remains fully functional.
ai_col1, ai_col2 = st.columns([4, 1])
with ai_col1:
    ai_prompt = st.text_input("AI DJ prompt", placeholder="যেমন: ধুনুচি নাচের গান, বনসাই মুড...", label_visibility="collapsed", key="v2_ai_prompt")
with ai_col2:
    if st.button("✦ AI DJ-কে বলুন", key="ai_btn_v2", use_container_width=True):
        if ai_prompt.strip():
            st.session_state.ai_result = get_ai_chat_recommendation(ai_prompt)
        else:
            st.warning("মুডটি লিখুন।")
if st.session_state.ai_result:
    r = st.session_state.ai_result
    st.markdown(f'<div class="page-section" style="padding:12px 18px;margin-top:10px"><div class="section-desc">✦ {r.get("response","")}</div><div class="kicker">AI ROUTE · {r.get("playlist_name",r.get("category","Bengali Music"))}</div></div>', unsafe_allow_html=True)

# Playlist art — all requested images are actually rendered.
playlist_art = {
    "Rabindra Sangeet": (ASSET["classics"], "রবীন্দ্রসঙ্গীত"),
    "Bangla Nostalgia": (ASSET["classics"], "বাংলা নস্টালজিয়া"),
    "Bangla Dance Number": (ASSET["dhak"], "নাচের বাংলা গান"),
    "Bangla Rock": (ASSET["indie"], "বাংলা রক"),
    "Pujor Gaan": (ASSET["featured"], "পুজোর গান"),
    "Mahalaya": (ASSET["agomoni"], "মহালয়া · আগমনী"),
}
playlist_tiles = []
for name in CURATED_PLAYLISTS:
    uri, label_bn = playlist_art.get(name, (ASSET["featured"], name))
    playlist_tiles.append(f'<div class="playlist-tile"><img src="{uri}" alt="{label_bn}"><div class="pname">{label_bn}</div></div>')
st.markdown('<div class="playlist-strip">' + ''.join(playlist_tiles) + '</div>', unsafe_allow_html=True)

# Location + song request in one balanced row.
loc_col, req_col = st.columns([1.2, .8])
with loc_col:
    st.markdown(
        f"""<section class="page-section loc-card" style="height:100%;margin-bottom:0;padding-bottom:20px"><div class="kicker">Live Puja Map</div><div class="section-title">📍 লাইভ পুজো ম্যাপ</div><div class="section-desc">আপনার এলাকার পুজো কোথায়, কীভাবে পৌঁছবেন — জেনে নিন এক ক্লিকে।</div></section>""",
        unsafe_allow_html=True,
    )
    loc = st.text_input("Location", placeholder="আপনার এলাকা / পিন কোড লিখুন", label_visibility="collapsed", key="v2_loc")
    if st.button("🗺️ আমার পুজোর লোকেশন শেয়ার করুন →", key="v2_loc_btn", use_container_width=True):
        if loc.strip():
            try:
                publish_location(loc.strip())
                latest = get_latest_location_event()
                if latest:
                    st.session_state.last_location_event_id = f"{latest.get('created_at','')}|{latest.get('location','')}"
                st.session_state.popup_message = f"📍 {loc.strip()}"
                st.session_state.popup_kind = "location"
            except PersistenceError as exc:
                st.session_state.persistence_error = str(exc)
                st.session_state.popup_message = f"Location could not be broadcast: {exc}"
                st.session_state.popup_kind = "error"
            _render_global_popup()
    try:
        live_locations = get_locations(30)
    except PersistenceError:
        live_locations = []
    if live_locations:
        st.markdown(f'<div class="section-desc" style="margin-top:8px"><b>LIVE:</b> {" · ".join(live_locations[:10])}</div>', unsafe_allow_html=True)
with req_col:
    st.markdown('<section class="page-section" style="height:100%;margin-bottom:0"><div class="kicker">Community Requests</div><div class="section-title">🎶 গান রিকোয়েস্ট</div><div class="section-desc">আপনার প্রিয় গানটি আমাদের জানান, পুজোর আড্ডায় সেটি পৌঁছে যাবে।</div></section>', unsafe_allow_html=True)
    rt = st.text_input("Song title", placeholder="গানের নাম / শিল্পীর নাম", key="v2_rt")
    ra = st.text_input("Artist / Band", placeholder="শিল্পী / ব্যান্ড", key="v2_ra")
    ru = st.text_input("YouTube URL", placeholder="YouTube লিঙ্ক (ঐচ্ছিক)", key="v2_ru")
    rl = st.text_input("Pandal / Location", placeholder="পুজো ম্যাপ / এলাকা (ঐচ্ছিক)", key="v2_rl")
    if st.button("➤ গান রিকোয়েস্ট পাঠান", key="v2_song_req", use_container_width=True):
        if rt.strip():
            ok, msg = submit_song_request(rt, ra, ru, rl)
            (st.success if ok else st.warning)(msg)
        else:
            st.warning("অন্তত গানের নামটি লিখুন।")

# -----------------------------------------------------------------------------
# Equal four-card row — including the second Mahalaya countdown
# -----------------------------------------------------------------------------
countdown_card = f"""<div class="feature-card countdown-card"><div class="icon">✦</div><div class="gold">মহালয়া পর্ব</div><div class="section-desc" style="color:#f0d5b9;text-align:center">মহালয়া আসতে বাকি</div><div class="big">আর {countdown_days} দিন</div><div class="gold">১০ অক্টোবর ২০২৬ · মহালয়া</div><div style="margin-top:18px;color:#f4dcbf;font:500 .78rem 'Noto Serif Bengali',serif">শুভ মহালয়া</div></div>"""
card_specs = [
    ("📺", "পুজো TV", "লাইভ পুজো, সাংস্কৃতিক অনুষ্ঠান, রেডিও ভিজ্যুয়াল ও বিশেষ অনুষ্ঠান।", ASSET["tv"], "?section=tv#tv-player"),
    ("📻", "লাইভ রেডিও", "সারা দিন পুজোর গান, আড্ডা, বিশেষ অনুষ্ঠান আর বাংলা রেডিও।", ASSET["radio"], "?section=radio#radio-player"),
    ("🔊", "পুজোর সাউন্ড", "ঢাক, কাঁসর, ঘণ্টা, মন্ত্র, আতশবাজি — পুজোর আবহ এক জায়গায়।", ASSET["sound"], "?section=sounds#sounds-player"),
]
card_html = []
for icon, title, desc, uri, href in card_specs:
    card_html.append(f'<div class="feature-card"><div class="icon">{icon}</div><h3>{title}</h3><p>{desc}</p><img src="{uri}" alt="{title}"><a class="card-btn" target="_self" rel="nofollow" href="{href}">এখন দেখুন →</a></div>')
st.markdown('<section class="page-section"><div class="section-head"><div><div class="kicker">Explore</div><div class="section-title">পুজোর চারটি সুর</div></div></div><div class="feature-cards">' + ''.join(card_html) + countdown_card + '</div></section>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Community strip using the supplied community_puja image
# -----------------------------------------------------------------------------
st.markdown(
    f"""<section class="page-section"><div class="community"><div><div class="kicker">Community</div><div class="section-title">আমাদের কমিউনিটি</div><div class="section-desc">আজ যারা পুজোর গান শুনছেন, রেডিও চালাচ্ছেন বা লোকেশন শেয়ার করছেন — সবাই মিলে তৈরি হোক একটাই ডিজিটাল পুজো আড্ডা।</div><div class="avatar-row"><span class="avatar">BU</span><span class="avatar">PU</span><span class="avatar">DG</span><span class="avatar">AA</span><span class="avatar">+</span><span class="live-pill">● এখন লাইভ</span></div></div><img src="{ASSET["community"]}" alt="Bengali Puja community" /></div></section>""",
    unsafe_allow_html=True,
)

def deck(playlist_id: str, title: str, component_key: str = "main_deck"):
    if not playlist_id:
        st.error("This playlist is not configured.")
        return

    playlist_json = json.dumps(str(playlist_id))
    title_json = json.dumps(str(title))
    html = r'''<!doctype html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><style>
*{box-sizing:border-box}html,body{margin:0;padding:0;background:transparent;color:#eee;font-family:Arial,sans-serif}body{overflow-x:hidden;overflow-y:auto}
.vinyl{position:absolute;top:10px;right:10px;width:62px;height:62px;border-radius:50%;background:radial-gradient(circle at 50% 50%,#d6a15a 0 9%,#2b1710 10% 13%,#050505 14% 100%);border:2px solid #9a663b;box-shadow:0 5px 12px rgba(0,0,0,.7),inset 0 0 0 1px rgba(255,220,170,.18);z-index:20;transform-origin:50% 50%}.vinyl:before{content:"";position:absolute;inset:7px;border-radius:50%;border:1px solid rgba(255,255,255,.12);box-shadow:inset 0 0 0 4px rgba(255,255,255,.025),inset 0 0 0 10px rgba(255,255,255,.018)}.vinyl:after{content:"";position:absolute;left:50%;top:50%;width:5px;height:5px;border-radius:50%;background:#d9b06c;transform:translate(-50%,-50%);box-shadow:0 0 4px #000}.vinyl.playing{animation:vinylSpin 5.5s linear infinite}@keyframes vinylSpin{to{transform:rotate(360deg)}}.vinyl-title{position:absolute;inset:19px 8px 18px;display:flex;align-items:center;justify-content:center;text-align:center;color:#f2d19b;font:700 6px Georgia,serif;letter-spacing:.35px;text-transform:uppercase;overflow:hidden;pointer-events:none;z-index:2}.vinyl-label{position:absolute;top:7px;left:0;right:0;text-align:center;color:#8e6a44;font:6px Georgia,serif;letter-spacing:1px;z-index:2}
.console{width:100%;max-width:1120px;margin:0 auto;padding:18px 18px 20px;border-radius:8px;background:linear-gradient(90deg,rgba(255,255,255,.035),transparent 10%,transparent 90%,rgba(0,0,0,.16)),linear-gradient(180deg,#6b3e24 0,#3c2115 9%,#24140e 14%,#160e0b 100%);border:2px solid #9a663b;box-shadow:0 20px 45px rgba(0,0,0,.72),inset 0 1px rgba(255,230,190,.24),inset 0 -2px 0 rgba(0,0,0,.75);position:relative}.console:before{content:"";position:absolute;inset:5px;border:1px solid rgba(232,183,113,.28);border-radius:5px;pointer-events:none}.grain{position:absolute;inset:0;pointer-events:none;opacity:.12;background:repeating-linear-gradient(88deg,rgba(255,220,170,.12) 0 1px,transparent 1px 5px);mix-blend-mode:screen}
.header{position:relative;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:0 4px 13px;color:#c5a17e;font:600 9px Georgia,serif;letter-spacing:1.8px;text-transform:uppercase}.brand{color:#f0c77d;font-size:10px}.model{color:#9e8066}
.stereo{position:relative;display:grid;grid-template-columns:190px minmax(0,1fr) 190px;gap:14px;align-items:stretch}.speaker{min-height:360px;border:2px solid #765036;border-radius:4px;padding:13px;background:linear-gradient(145deg,#2d1a12,#130c09);box-shadow:inset 0 0 18px rgba(0,0,0,.95),inset 0 1px rgba(255,235,205,.08),0 8px 18px rgba(0,0,0,.48);position:relative;overflow:hidden}.speaker:before{content:"";position:absolute;inset:10px;border:1px solid #63432d;background:radial-gradient(circle at 50% 22%,#090807 0 10%,#2c2119 10.5% 11%,#090807 11.5% 20%,transparent 20.5%),radial-gradient(circle at 50% 22%,transparent 0 20%,#4a3524 20.5% 21%,#0b0907 21.5% 36%,transparent 36.5%),radial-gradient(circle at 50% 72%,#090807 0 18%,#31251d 18.5% 19.5%,#080706 20% 31%,transparent 31.5%),repeating-linear-gradient(0deg,#0b0908 0 4px,#2e2118 5px 6px);box-shadow:inset 0 0 30px #000}.speaker:after{content:"BANGALIR UTSAV";position:absolute;left:24px;right:24px;bottom:22px;padding:6px 4px;text-align:center;border-top:1px solid #7c5838;border-bottom:1px solid #5b3d28;color:#caa36c;font:600 8px Georgia,serif;letter-spacing:1.5px;background:rgba(13,8,6,.72)}
.center{min-width:0;border:2px solid #69472e;border-radius:4px;padding:12px;background:linear-gradient(180deg,#1b110c,#0b0907 22%,#15100d 100%);box-shadow:inset 0 0 30px rgba(0,0,0,.9),0 8px 18px rgba(0,0,0,.42)}.faceplate{border:1px solid #5e432e;background:linear-gradient(#0d0b09,#18110c);padding:9px;border-radius:3px;box-shadow:inset 0 0 16px #000}.display-row{display:grid;grid-template-columns:72px minmax(0,1fr) 72px;gap:10px;align-items:center}.meter{height:42px;border:1px solid #5a422b;background:#080706;position:relative;overflow:hidden;box-shadow:inset 0 0 10px #000}.meter .ticks{position:absolute;inset:6px 6px 8px;background:repeating-linear-gradient(90deg,#7b5c39 0 1px,transparent 1px 9px);opacity:.5}.meter .needle{position:absolute;width:42%;height:2px;left:7%;bottom:17%;background:#df9c51;transform-origin:100% 50%;transform:rotate(-23deg);box-shadow:0 0 7px #df9c51}.playing .meter .needle{animation:needle .55s ease-in-out infinite alternate}@keyframes needle{from{transform:rotate(-25deg)}to{transform:rotate(13deg)}}
.screen{min-width:0;height:78px;border:1px solid #604126;background:radial-gradient(circle at 50% 40%,#4a2a12,#120b07 65%);box-shadow:inset 0 0 22px #000;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:8px;overflow:hidden}.screen-title{width:100%;text-align:center;color:#f0bd69;font:600 clamp(12px,2vw,18px) 'Noto Serif Bengali',Georgia,serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:0 0 8px rgba(231,161,70,.25)}.screen-sub{color:#b9864b;font:8px monospace;letter-spacing:1.2px;margin-top:5px}.screen-time{color:#8d673f;font:8px monospace;margin-top:3px}
.tuning{margin-top:10px;border:1px solid #513b27;background:#0a0806;height:56px;position:relative;overflow:hidden}.freq{position:absolute;left:5%;right:5%;top:7px;display:flex;justify-content:space-between;color:#8e6a44;font:8px monospace}.scale{position:absolute;left:5%;right:5%;bottom:12px;height:18px;border-bottom:1px solid #7b5a39;background:repeating-linear-gradient(90deg,transparent 0 4.6%,#765638 4.8% 5%,transparent 5.2% 10%)}.tuning-needle{position:absolute;top:9px;bottom:8px;left:53%;width:2px;background:#e3a354;box-shadow:0 0 9px #e3a354}
.album{margin-top:10px;position:relative;aspect-ratio:16/8.8;border:1px solid #5a422c;background:#030303;overflow:hidden;box-shadow:inset 0 0 20px #000}.yt{position:absolute;inset:0;width:100%;height:100%;z-index:2}.yt iframe{width:100% !important;height:100% !important;border:0 !important;display:block}.album-caption{position:absolute;left:10px;right:10px;bottom:9px;color:#f1d19b;font:600 9px Georgia,serif;letter-spacing:1px;text-shadow:0 1px 3px #000;z-index:4;pointer-events:none;background:linear-gradient(transparent,rgba(0,0,0,.72));padding-top:24px}
.transport{margin-top:11px;padding:9px 7px;border-top:1px solid #65462e;border-bottom:1px solid #3b291d;display:flex;justify-content:center;align-items:center;gap:6px;flex-wrap:wrap;background:linear-gradient(#1a100b,#0c0907)}.physical{position:relative;height:38px;min-width:42px;padding:0 9px;border-radius:3px;border:1px solid #7b5a3b;background:linear-gradient(180deg,#6b5540 0,#30251b 44%,#110e0b 100%);color:#e5cba5;font:700 8px Georgia,serif;letter-spacing:.4px;box-shadow:0 2px 0 #080706,0 4px 7px rgba(0,0,0,.65),inset 0 1px rgba(255,255,255,.2);cursor:pointer;text-shadow:0 1px #000;transition:transform .08s,box-shadow .08s,filter .12s}.physical:before{content:"";position:absolute;left:7px;right:7px;top:4px;height:2px;background:rgba(255,239,210,.18);border-radius:3px}.physical:hover{filter:brightness(1.18)}.physical:active,.physical.pressed{transform:translateY(2px);box-shadow:0 0 0 #080706,0 2px 4px rgba(0,0,0,.55),inset 0 1px rgba(0,0,0,.3)}.physical.play{min-width:58px;background:linear-gradient(180deg,#a56a34,#5d2d17 48%,#2b160c);border-color:#a97b4a;color:#ffe8bd}.physical.stop{background:linear-gradient(180deg,#71453a,#2c1714)}
.knob-bank{display:grid;grid-template-columns:repeat(2,54px);gap:8px 14px;justify-content:center;margin-top:10px}.knob-wrap{text-align:center}.knob{width:50px;height:50px;border-radius:50%;margin:auto;background:radial-gradient(circle at 32% 28%,#d9c6a6 0,#9e8663 18%,#4d3b29 48%,#17110c 66%,#090706 68%);border:2px solid #9a7047;box-shadow:0 4px 9px #000,inset 0 1px 3px rgba(255,255,255,.22);position:relative;cursor:pointer}.knob:after{content:"";position:absolute;left:50%;top:5px;width:2px;height:15px;background:#24170e;transform:translateX(-50%);box-shadow:0 0 1px #000}.knob-label{margin-top:3px;color:#9f7a51;font:7px Georgia,serif;letter-spacing:1px}
.lower{margin-top:10px;display:grid;grid-template-columns:1fr auto 1fr;gap:10px;align-items:center}.brand-plate{text-align:left;color:#c8a275;font:600 9px Georgia,serif;letter-spacing:1.5px}.status{text-align:center;min-height:14px;color:#b89a79;font:8px monospace;letter-spacing:.8px}.power{text-align:right;color:#d5aa69;font:700 8px monospace;letter-spacing:1px}.lamp{display:inline-block;width:7px;height:7px;border-radius:50%;background:#54281a;border:1px solid #8d4d31;vertical-align:middle;margin-right:5px}.playing .lamp{background:#e08b45;box-shadow:0 0 10px rgba(224,139,69,.7)}
@media(max-width:820px){.console{padding:12px}.stereo{grid-template-columns:1fr}.speaker{min-height:100px;height:100px}.speaker:before{inset:7px;background:repeating-linear-gradient(0deg,#0b0908 0 3px,#2e2118 4px 5px)}.speaker:after{bottom:8px;left:22%;right:22%;padding:3px;font-size:6px}.center{order:2}.speaker.left{order:1}.speaker.right{order:3}.display-row{grid-template-columns:58px minmax(0,1fr) 58px}.meter{height:36px}.album{aspect-ratio:16/7}.transport{gap:5px}.physical{height:36px;min-width:38px;padding:0 7px;font-size:7px}.physical.play{min-width:54px}.knob-bank{grid-template-columns:repeat(4,50px);gap:8px;margin-bottom:2px}.lower{grid-template-columns:1fr;gap:5px;text-align:center}.brand-plate,.power{text-align:center}}
@media(max-width:430px){.header{flex-direction:column;align-items:flex-start;gap:4px}.console{padding:9px}.speaker{min-height:74px;height:74px}.center{padding:8px}.display-row{grid-template-columns:48px minmax(0,1fr) 48px;gap:6px}.meter{height:32px}.screen{height:66px}.screen-title{font-size:12px}.tuning{height:48px}.album{aspect-ratio:16/6.8}.transport{gap:4px;padding:7px 3px}.physical{height:34px;min-width:34px;padding:0 5px;font-size:6.5px}.physical.play{min-width:49px}.knob-bank{grid-template-columns:repeat(4,44px);gap:5px}.knob{width:42px;height:42px}.knob:after{height:12px}}
</style></head><body>
<div class="console" id="console"><div class="grain"></div><div class="vinyl" id="vinyl"><div class="vinyl-label">PUJA</div><div class="vinyl-title" id="vinylTitle">__TITLE__</div></div><div class="header"><span>● <span class="brand">BANGALIR UTSAV</span> · VINTAGE HI-FI CONSOLE</span><span class="model">MODEL 76 · WOODGRAIN STEREO</span></div><div class="stereo"><div class="speaker left"></div><div class="center"><div class="faceplate"><div class="display-row"><div class="meter"><div class="ticks"></div><div class="needle"></div></div><div class="screen"><div class="screen-title" id="title">__TITLE__</div><div class="screen-sub" id="sub">PLAYLIST · READY</div><div class="screen-time"><span id="current">00:00</span> / <span id="duration">--:--</span></div></div><div class="meter"><div class="ticks"></div><div class="needle"></div></div></div><div class="tuning"><div class="freq"><span>FM 88</span><span>92</span><span>96</span><span>100</span><span>104</span><span>108</span></div><div class="scale"></div><div class="tuning-needle"></div></div><div class="album"><div class="yt" id="yt-host"></div><div class="album-caption">DURGAPUJA · BENGALI MUSIC</div></div><div class="transport"><button class="physical" id="prev">⏮ REV</button><button class="physical" id="rewind">◀◀ 10</button><button class="physical play" id="play">▶ PLAY</button><button class="physical stop" id="stop">■ STOP</button><button class="physical" id="forward">10 ▶▶</button><button class="physical" id="next">FWD ⏭</button><button class="physical" id="mute">MUTE</button></div><div class="knob-bank"><div class="knob-wrap"><div class="knob" id="volDown"></div><div class="knob-label">VOL −</div></div><div class="knob-wrap"><div class="knob" id="volUp"></div><div class="knob-label">VOL +</div></div><div class="knob-wrap"><div class="knob" id="prevTrack"></div><div class="knob-label">TRACK ◀</div></div><div class="knob-wrap"><div class="knob" id="nextTrack"></div><div class="knob-label">TRACK ▶</div></div></div></div><div class="lower"><div class="brand-plate">ANALOGUE AUDIO · STEREO RECEIVER</div><div class="status" id="status">READY · PRESS PLAY</div><div class="power"><span class="lamp"></span><span id="powerText">STANDBY</span></div></div></div><div class="speaker right"></div></div></div>
<script>
const PLAYLIST_ID=__PLAYLIST__;let player=null,ready=false,apiReady=false;const $=id=>document.getElementById(id);const fmt=s=>{s=Math.max(0,Math.floor(s||0));return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')};function status(t){$('status').textContent=t}function sync(){if(!player||!ready)return;try{const d=player.getDuration()||0,c=player.getCurrentTime()||0,idx=player.getPlaylistIndex();$('current').textContent=fmt(c);$('duration').textContent=fmt(d);$('sub').textContent='PLAYLIST · TRACK '+(idx>=0?idx+1:'—')}catch(e){}}function playing(on){$('console').classList.toggle('playing',on);$('vinyl').classList.toggle('playing',on);$('powerText').textContent=on?'PLAYING':'STANDBY';$('play').textContent=on?'❚❚ PAUSE':'▶ PLAY';if(player){try{const d=player.getVideoData();if(d&&d.title)$('vinylTitle').textContent=d.title}catch(e){}}}function press(id){const b=$(id);if(!b)return;b.classList.add('pressed');setTimeout(()=>b.classList.remove('pressed'),130)}function onYTReady(){if(apiReady)return;apiReady=true;player=new YT.Player('yt-player',{height:'100%',width:'100%',playerVars:{controls:0,rel:0,playsinline:1,fs:0,modestbranding:1,iv_load_policy:3},events:{onReady:()=>{ready=true;player.cuePlaylist({listType:'playlist',list:PLAYLIST_ID,index:0});status('READY · FIRST TRACK QUEUED')},onStateChange:e=>{if(e.data===YT.PlayerState.PLAYING){playing(true);status('PLAYING · TRACK '+(player.getPlaylistIndex()+1))}else if(e.data===YT.PlayerState.PAUSED){playing(false);status('PAUSED · TRACK '+(player.getPlaylistIndex()+1))}else if(e.data===YT.PlayerState.ENDED){playing(false);status('TRACK COMPLETE')}sync()}}})}function boot(){const host=$('yt-host');if(host&&!$('yt-player')){const d=document.createElement('div');d.id='yt-player';host.appendChild(d)}if(window.YT&&window.YT.Player)onYTReady();else{window.onYouTubeIframeAPIReady=onYTReady;const tag=document.createElement('script');tag.src='https://www.youtube.com/iframe_api';document.head.appendChild(tag)}}$('play').onclick=()=>{press('play');if(player)player.getPlayerState()===1?player.pauseVideo():player.playVideo()};$('stop').onclick=()=>{press('stop');if(player){player.pauseVideo();player.seekTo(0,true);status('STOPPED · 00:00');playing(false)}};$('rewind').onclick=()=>{press('rewind');if(player)player.seekTo(Math.max(0,player.getCurrentTime()-10),true)};$('forward').onclick=()=>{press('forward');if(player)player.seekTo(Math.max(0,player.getCurrentTime()+10),true)};$('prev').onclick=()=>{press('prev');if(player)player.previousVideo()};$('next').onclick=()=>{press('next');if(player)player.nextVideo()};$('prevTrack').onclick=()=>{press('prevTrack');if(player)player.previousVideo()};$('nextTrack').onclick=()=>{press('nextTrack');if(player)player.nextVideo()};$('volDown').onclick=()=>{press('volDown');if(player)player.setVolume(Math.max(0,player.getVolume()-10))};$('volUp').onclick=()=>{press('volUp');if(player)player.setVolume(Math.min(100,player.getVolume()+10))};$('mute').onclick=()=>{press('mute');if(player){const wasMuted=player.isMuted();wasMuted?player.unMute():player.mute();status(wasMuted?'SOUND ON':'MUTED')}};setInterval(sync,500);boot();
</script></body></html>'''
    html=html.replace('__PLAYLIST__',playlist_json).replace('__TITLE__',title_json)
    components.html(html, height=760, scrolling=False)


def radio_deck(stations: dict):
    stations_json=json.dumps(stations)
    html=r"""<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><script src="https://cdn.jsdelivr.net/npm/hls.js@1.6.2/dist/hls.min.js"></script><style>
*{box-sizing:border-box}html,body{margin:0;background:transparent}body{font-family:Arial,sans-serif;color:#fff}.radio-vinyl{position:absolute;top:9px;right:78px;width:52px;height:52px;border-radius:50%;background:radial-gradient(circle at 50% 50%,#d6a15a 0 10%,#2b1710 11% 14%,#050505 15% 100%);border:2px solid #9a663b;box-shadow:0 4px 10px rgba(0,0,0,.65),inset 0 0 0 1px rgba(255,220,170,.18);z-index:15;transform-origin:50% 50%}.radio-vinyl:before{content:"";position:absolute;inset:6px;border-radius:50%;border:1px solid rgba(255,255,255,.12);box-shadow:inset 0 0 0 8px rgba(255,255,255,.018)}.radio-vinyl:after{content:"";position:absolute;left:50%;top:50%;width:5px;height:5px;border-radius:50%;background:#d9b06c;transform:translate(-50%,-50%)}.radio-vinyl.playing{animation:radioVinylSpin 5.5s linear infinite}@keyframes radioVinylSpin{to{transform:rotate(360deg)}}.radio-vinyl-title{position:absolute;inset:16px 6px 15px;display:flex;align-items:center;justify-content:center;text-align:center;color:#f2d19b;font:700 5px Georgia,serif;letter-spacing:.25px;text-transform:uppercase;overflow:hidden}.radio-vinyl-label{position:absolute;top:5px;left:0;right:0;text-align:center;color:#8e6a44;font:5px Georgia,serif;letter-spacing:.8px}.radio{position:relative;width:100%;max-width:1080px;margin:auto;padding:15px;border-radius:14px;background:linear-gradient(145deg,#3b2119,#17100d 40%,#090807);border:1px solid #a27a49;box-shadow:0 22px 55px rgba(0,0,0,.65),inset 0 1px rgba(255,240,205,.14);position:relative;overflow:hidden}.radio:before{content:"";position:absolute;inset:0;opacity:.13;background:repeating-linear-gradient(90deg,rgba(255,220,170,.08) 0 1px,transparent 1px 6px);pointer-events:none}.top{position:relative;display:flex;justify-content:space-between;color:#aa967f;font:600 10px Georgia,serif;letter-spacing:1.2px;padding-bottom:10px}.brand{color:#e0b46f}.radio-main{position:relative;display:grid;grid-template-columns:150px 1fr 145px;gap:12px;align-items:stretch}.speaker{min-height:205px;border:1px solid #72583a;border-radius:7px;background:repeating-linear-gradient(0deg,#0b0907 0 5px,#3a2a1c 6px 7px);box-shadow:inset 0 0 28px #000}.speaker-label{margin:82px 12px 0;padding:6px;text-align:center;border:1px solid #8b6b42;color:#c9a76d;font:600 9px Georgia,serif;letter-spacing:1px;background:#1b120c}.tuner{background:linear-gradient(#090807,#15100c);border:1px solid #5b452e;border-radius:7px;padding:12px;box-shadow:inset 0 0 28px #000}.channel{display:flex;justify-content:space-between;gap:8px;color:#f0c988;font:600 clamp(15px,2.4vw,21px) 'Noto Serif Bengali',Georgia,serif}.station{color:#a08c75;font:10px Arial,sans-serif;margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.dial{margin-top:17px;height:54px;border:1px solid #59442e;border-radius:5px;background:linear-gradient(#17100b,#0a0806);position:relative;overflow:hidden}.ticks{position:absolute;left:5%;right:5%;bottom:14px;height:22px;border-bottom:1px solid #9c713e;background:repeating-linear-gradient(90deg,transparent 0 7%,#8c6539 7.2% 7.5%,transparent 7.7% 10%)}.needle{position:absolute;top:6px;bottom:9px;width:2px;left:50%;background:#e9ae5d;box-shadow:0 0 9px #e9ae5d}.freq{position:absolute;left:6%;right:6%;top:6px;display:flex;justify-content:space-between;color:#9c794e;font:9px monospace}.radio-controls{display:flex;gap:6px;flex-wrap:wrap;align-items:center;justify-content:center;margin-top:12px}.key{height:31px;min-width:40px;padding:0 8px;border-radius:5px;border:1px solid #7f6544;background:linear-gradient(#4b4034,#17130f);color:#ddc39b;font:600 8px Georgia,serif;cursor:pointer}.key.play{min-width:57px;background:linear-gradient(#b87531,#5a2a13);color:#fff0d0}.station-select{width:100%;margin-top:11px;padding:9px;border-radius:5px;border:1px solid #765a39;background:#120d09;color:#e3c590;font:10px Georgia,serif}.knob{width:58px;height:58px;margin:auto;border-radius:50%;background:radial-gradient(circle at 35% 30%,#d7c09c,#8d704b 32%,#3a2a1b 59%,#0d0b08 63%);border:2px solid #9e784b;box-shadow:0 4px 12px #000;position:relative}.knob:after{content:"";position:absolute;width:2px;height:16px;background:#251a10;left:50%;top:5px;transform:translateX(-50%)}.label{text-align:center;color:#98754d;font:8px Georgia,serif;letter-spacing:1px;margin-top:3px}.vu-line{height:4px;margin-top:13px;background:#2e2015;border-radius:9px;overflow:hidden}.vu-line i{display:block;width:35%;height:100%;background:linear-gradient(90deg,#8d5125,#e7ad5a);animation:level .9s ease-in-out infinite alternate}.status{text-align:center;color:#a99580;font:9px monospace;letter-spacing:.8px;min-height:14px;margin-top:8px}@keyframes level{from{width:22%}to{width:74%}}.onair{display:inline-block;color:#f2a15b;border:1px solid #774122;padding:2px 6px;border-radius:3px;font:600 8px monospace;letter-spacing:1px;margin-left:5px}.playing .onair{box-shadow:0 0 10px rgba(240,110,40,.4)}
@media(max-width:700px){.radio{padding:9px;border-radius:10px}.top{font-size:8px}.radio-main{grid-template-columns:1fr}.speaker{display:none}.tuner{padding:10px}.dial{margin-top:11px;height:48px}.knob{width:46px;height:46px}.radio-controls{gap:4px}.key{min-width:34px;height:30px;font-size:8px;padding:0 6px}}@media(max-width:390px){.top{flex-direction:column;gap:3px}.radio{padding:8px}.key{min-width:32px}}
</style></head><body><div class="radio" id="radio"><div class="radio-vinyl" id="radioVinyl"><div class="radio-vinyl-label">RADIO</div><div class="radio-vinyl-title" id="radioVinylTitle">PUJA RADIO</div></div><div class="top"><span>● <span class="brand">BANGALIR UTSAV</span> · LIVE RADIO</span><span>VINTAGE BROADCAST RECEIVER</span></div><div class="radio-main"><div class="speaker"><div class="speaker-label">BENGAL RADIO</div></div><div class="tuner"><div class="channel" id="channel">বাংলা রেডিও <span class="onair" id="onair">OFF AIR</span></div><div class="station" id="station">Select a station below</div><div class="dial"><div class="freq"><span>88</span><span>92</span><span>96</span><span>100</span><span>104</span><span>108</span></div><div class="ticks"></div><div class="needle"></div></div><select id="stationSelect" class="station-select"></select><div class="radio-controls"><button class="key" id="prev">◀ PREV</button><button class="key play" id="play">PLAY</button><button class="key" id="stop">STOP</button><button class="key" id="next">NEXT ▶</button><button class="key" id="mute">MUTE</button></div><div class="vu-line"><i></i></div><div class="status" id="status">READY · SELECT A CHANNEL</div></div><div><div class="knob"></div><div class="label">VOLUME</div><div style="height:18px"></div><div class="knob" style="width:45px;height:45px"></div><div class="label">TUNE</div></div></div><audio id="audio" preload="none" crossorigin="anonymous"></audio></div><script>
const STATIONS=__STATIONS__;const sel=document.getElementById('stationSelect'),audio=document.getElementById('audio'),radio=document.getElementById('radio'),statusEl=document.getElementById('status'),onair=document.getElementById('onair'),playBtn=document.getElementById('play');let names=Object.keys(STATIONS),hls=null;names.forEach(n=>{const o=document.createElement('option');o.value=n;o.textContent=n;sel.appendChild(o)});function current(){return sel.value}function cleanup(){if(hls){hls.destroy();hls=null}audio.pause();audio.removeAttribute('src');audio.load()}function load(){cleanup();const n=current(),src=STATIONS[n];document.getElementById('station').textContent=n;statusEl.textContent='READY · '+n;onair.textContent='OFF AIR';playBtn.textContent='PLAY';if(!src)return;if(src.includes('.m3u8')){if(audio.canPlayType('application/vnd.apple.mpegurl')){audio.src=src}else if(window.Hls&&Hls.isSupported()){hls=new Hls({enableWorker:true,lowLatencyMode:true});hls.loadSource(src);hls.attachMedia(audio);hls.on(Hls.Events.ERROR,(e,d)=>{if(d.fatal)statusEl.textContent='STREAM ERROR · HLS SOURCE UNAVAILABLE'})}else{statusEl.textContent='HLS NOT SUPPORTED IN THIS BROWSER'}}else{audio.src=src}}async function play(){try{if(!audio.src&&!hls)load();await audio.play();radio.classList.add('playing');document.getElementById('radioVinyl').classList.add('playing');document.getElementById('radioVinylTitle').textContent=current();onair.textContent='ON AIR';statusEl.textContent='PLAYING · '+current();playBtn.textContent='PAUSE'}catch(e){statusEl.textContent='STREAM UNAVAILABLE · CHECK THE LIVE SOURCE'}}function pause(){audio.pause();radio.classList.remove('playing');document.getElementById('radioVinyl').classList.remove('playing');onair.textContent='OFF AIR';statusEl.textContent='PAUSED · '+current();playBtn.textContent='PLAY'}sel.onchange=()=>load();playBtn.onclick=()=>audio.paused?play():pause();document.getElementById('stop').onclick=()=>{audio.pause();audio.currentTime=0;pause()};document.getElementById('mute').onclick=()=>{audio.muted=!audio.muted;document.getElementById('mute').textContent=audio.muted?'UNMUTE':'MUTE'};document.getElementById('prev').onclick=()=>{sel.selectedIndex=(sel.selectedIndex-1+names.length)%names.length;load()};document.getElementById('next').onclick=()=>{sel.selectedIndex=(sel.selectedIndex+1)%names.length;load()};audio.addEventListener('playing',()=>{radio.classList.add('playing');document.getElementById('radioVinyl').classList.add('playing');document.getElementById('radioVinylTitle').textContent=current();onair.textContent='ON AIR';playBtn.textContent='PAUSE'});audio.addEventListener('pause',()=>{if(!audio.ended)pause()});audio.addEventListener('error',()=>{radio.classList.remove('playing');document.getElementById('radioVinyl').classList.remove('playing');onair.textContent='OFF AIR';statusEl.textContent='STREAM ERROR · TRY ANOTHER CHANNEL';playBtn.textContent='PLAY'});load();
</script></body></html>"""
    html=html.replace('__STATIONS__',stations_json)
    components.html(html, height=430, scrolling=False)


def pujo_tv_deck(playlist_id: str, title: str, component_key: str = "pujo_tv_deck"):
    if not playlist_id:
        st.error("This playlist is not configured.")
        return
    playlist_json=json.dumps(str(playlist_id)); title_json=json.dumps(str(title))
    html=r"""<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><style>
*{box-sizing:border-box}html,body{margin:0;padding:0;background:transparent;color:#eee;font-family:Arial,sans-serif}body{overflow-x:hidden}.tv{width:100%;max-width:1080px;margin:0 auto;padding:18px 20px 22px;border-radius:20px;background:linear-gradient(145deg,#70472d 0,#3b2418 12%,#24150f 55%,#120c09 100%);border:2px solid #a87543;box-shadow:0 24px 60px rgba(0,0,0,.75),inset 0 1px rgba(255,238,200,.2);position:relative}.tv:before{content:"";position:absolute;inset:6px;border:1px solid rgba(244,194,120,.3);border-radius:15px;pointer-events:none}.tv-head{position:relative;display:flex;justify-content:space-between;gap:12px;color:#caa477;font:600 10px Georgia,serif;letter-spacing:1.7px;text-transform:uppercase;padding:0 4px 12px}.tv-brand{color:#f2c77c}.tv-body{position:relative;display:grid;grid-template-columns:minmax(0,1fr) 190px;gap:16px;align-items:stretch}.crt{min-width:0;padding:15px;border:2px solid #5e3d27;border-radius:18px;background:linear-gradient(145deg,#1a110c,#090706);box-shadow:inset 0 0 32px #000,0 8px 18px rgba(0,0,0,.5)}.screen-frame{position:relative;background:#020202;border:10px solid #2e2119;border-radius:26px;box-shadow:inset 0 0 24px #000,0 0 0 2px #765137;overflow:hidden;aspect-ratio:16/9}.screen-frame:after{content:"";position:absolute;inset:0;border-radius:18px;pointer-events:none;background:radial-gradient(ellipse at center,transparent 55%,rgba(0,0,0,.42) 100%),repeating-linear-gradient(0deg,rgba(255,255,255,.025) 0 1px,transparent 1px 3px);z-index:4}.yt{position:absolute;inset:0;width:100%;height:100%;z-index:2}.yt iframe{width:100%;height:100%;border:0}.side{border:2px solid #60412c;border-radius:13px;background:linear-gradient(180deg,#2a1b13,#120c09);padding:14px;box-shadow:inset 0 0 22px #000;display:flex;flex-direction:column;justify-content:space-between}.speaker-grille{height:115px;border:1px solid #755337;border-radius:8px;background:repeating-linear-gradient(0deg,#0b0907 0 4px,#493523 5px 6px);box-shadow:inset 0 0 20px #000}.dial{margin-top:13px;height:52px;border:1px solid #795536;border-radius:6px;background:#0b0806;position:relative;overflow:hidden}.dial-scale{position:absolute;left:8%;right:8%;top:11px;display:flex;justify-content:space-between;color:#a68154;font:8px monospace}.dial-line{position:absolute;left:8%;right:8%;bottom:11px;height:1px;background:#87603a}.dial-needle{position:absolute;left:51%;top:8px;bottom:7px;width:2px;background:#e4aa5b;box-shadow:0 0 8px #e4aa5b}.knobs{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:13px}.knob{width:54px;height:54px;margin:auto;border-radius:50%;background:radial-gradient(circle at 34% 28%,#d5bd92,#8a6b45 33%,#3a2919 60%,#0b0907 64%);border:2px solid #a27b4c;box-shadow:0 5px 12px #000;position:relative}.knob:after{content:"";position:absolute;width:2px;height:16px;left:50%;top:5px;transform:translateX(-50%);background:#24180f}.knob-label{text-align:center;color:#a7865c;font:8px Georgia,serif;letter-spacing:1px;margin-top:4px}.controls{margin-top:13px;display:flex;flex-wrap:wrap;justify-content:center;gap:6px;padding-top:11px;border-top:1px solid #4e3625}.key{height:34px;min-width:48px;padding:0 9px;border-radius:5px;border:1px solid #866445;background:linear-gradient(#554535,#1b130e);color:#e6cda5;font:600 8px Georgia,serif;cursor:pointer;box-shadow:inset 0 1px rgba(255,255,255,.08),0 3px 6px #000}.key:active{transform:translateY(2px);box-shadow:inset 0 2px 5px #000}.key.play{background:linear-gradient(#b56b2e,#5b2a12);color:#fff1d2}.timeline{margin-top:11px;height:8px;border-radius:8px;background:#2d1e15;border:1px solid #5d412a;overflow:hidden}.timeline input{width:100%;height:100%;margin:0;padding:0;accent-color:#e1a253;cursor:pointer}.meta{display:flex;justify-content:space-between;gap:8px;color:#9c7a54;font:8px monospace;margin-top:5px}.status{text-align:center;color:#b6956e;font:9px monospace;letter-spacing:.8px;margin-top:7px;min-height:13px}.now{margin-top:7px;color:#e7bd7b;text-align:center;font:600 10px Georgia,serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.playing .crt{box-shadow:inset 0 0 32px #000,0 0 20px rgba(224,157,73,.13),0 8px 18px rgba(0,0,0,.5)}
@media(max-width:760px){.tv{padding:12px;border-radius:14px}.tv-head{font-size:8px}.tv-body{grid-template-columns:1fr}.side{display:grid;grid-template-columns:1fr 1fr;gap:10px}.speaker-grille{height:70px}.dial{margin-top:0}.knobs{margin-top:0}.controls{grid-column:1/-1;margin-top:0}.timeline{grid-column:1/-1}.meta,.status,.now{grid-column:1/-1}.key{min-width:42px;height:33px;padding:0 7px}}@media(max-width:430px){.tv-head{flex-direction:column;gap:4px}.crt{padding:8px}.screen-frame{border-width:7px;border-radius:19px}.side{grid-template-columns:1fr}.speaker-grille{height:62px}.controls{gap:4px}.key{min-width:40px;font-size:7px}}
</style></head><body><div class="tv" id="tv"><div class="tv-head"><span>● <span class="tv-brand">BANGALIR UTSAV</span> · PUJO TV</span><span>VINTAGE TELEVISION RECEIVER</span></div><div class="tv-body"><div class="crt"><div class="screen-frame"><div class="yt" id="yt-host"></div></div><div class="now" id="now">__TITLE__</div><div class="controls"><button class="key" id="prev">◀ CH−</button><button class="key" id="rewind">◀◀ 10</button><button class="key play" id="play">▶ PLAY</button><button class="key" id="stop">■ STOP</button><button class="key" id="forward">10 ▶▶</button><button class="key" id="next">CH+ ▶</button><button class="key" id="mute">MUTE</button></div><div class="timeline"><input id="progress" type="range" min="0" max="1000" value="0" step="1" aria-label="Video progress"></div><div class="meta"><span id="elapsed">00:00</span><span id="duration">00:00</span></div><div class="status" id="status">READY · SELECTED PLAYLIST · PRESS PLAY</div></div><div class="side"><div><div class="speaker-grille"></div><div class="dial"><div class="dial-scale"><span>2</span><span>4</span><span>6</span><span>8</span><span>10</span><span>12</span></div><div class="dial-line"></div><div class="dial-needle"></div></div></div><div class="knobs"><div><div class="knob"></div><div class="knob-label">VOLUME</div></div><div><div class="knob"></div><div class="knob-label">TUNE</div></div></div></div></div></div><script>
const PLAYLIST_ID=__PLAYLIST__,TITLE=__TITLE__;let player=null,ready=false;const $=id=>document.getElementById(id),progress=$("progress");function fmt(sec){sec=Math.max(0,Math.floor(sec||0));return String(Math.floor(sec/60)).padStart(2,"0")+":"+String(sec%60).padStart(2,"0")}function setStatus(x){$("status").textContent=x}function setPlaying(v){$("tv").classList.toggle("playing",v);$("play").textContent=v?"❚❚ PAUSE":"▶ PLAY"}function onReady(){if(ready)return;ready=true;player=new YT.Player("yt-player",{width:"100%",height:"100%",playerVars:{playsinline:1,rel:0,modestbranding:1,controls:1},events:{onReady:()=>{player.cuePlaylist({listType:"playlist",list:PLAYLIST_ID,index:0});setStatus("READY · PRESS PLAY");sync()},onStateChange:e=>{if(e.data===1){setPlaying(true);setStatus("PLAYING · "+TITLE)}else if(e.data===2){setPlaying(false);setStatus("PAUSED · "+TITLE)}else if(e.data===0){setPlaying(false);setStatus("TRACK COMPLETE")}}}})}function boot(){const host=$("yt-host");if(host&&!$("yt-player")){const d=document.createElement("div");d.id="yt-player";host.appendChild(d)}if(window.YT&&window.YT.Player)onReady();else{window.onYouTubeIframeAPIReady=onReady;const tag=document.createElement("script");tag.src="https://www.youtube.com/iframe_api";document.head.appendChild(tag)}}function sync(){if(!player||!ready)return;const cur=player.getCurrentTime()||0,dur=player.getDuration()||0;progress.value=dur?Math.round(cur/dur*1000):0;$("elapsed").textContent=fmt(cur);$("duration").textContent=fmt(dur);const idx=player.getPlaylistIndex();if(idx!=null&&idx>=0)$("now").textContent=TITLE+" · TRACK "+(idx+1)}$("play").onclick=()=>{if(!player)return;if(player.getPlayerState()===1)player.pauseVideo();else player.playVideo()};$("stop").onclick=()=>{if(player){player.pauseVideo();player.seekTo(0,true);setPlaying(false);setStatus("STOPPED · 00:00")}};$("rewind").onclick=()=>{if(player)player.seekTo(Math.max(0,(player.getCurrentTime()||0)-10),true)};$("forward").onclick=()=>{if(player)player.seekTo(Math.min(player.getDuration()||0,(player.getCurrentTime()||0)+10),true)};$("prev").onclick=()=>{if(player)player.previousVideo()};$("next").onclick=()=>{if(player)player.nextVideo()};$("mute").onclick=()=>{if(player){const m=player.isMuted();m?player.unMute():player.mute();setStatus(m?"SOUND ON":"MUTED")}};progress.addEventListener("input",()=>{if(player){const dur=player.getDuration()||0;player.seekTo(dur*(Number(progress.value)/1000),true)}});setInterval(sync,500);boot();
</script></body></html>"""
    html=html.replace('__PLAYLIST__',playlist_json).replace('__TITLE__',title_json)
    components.html(html, height=690, scrolling=False)



# -----------------------------------------------------------------------------
# Player sections — rendered once and switched entirely in the browser.
# This avoids a Streamlit rerun, page reload, or new tab when changing sections.
# -----------------------------------------------------------------------------
with st.container(key="client_player_songs"):
    st.markdown('<div id="songs-player" style="scroll-margin-top:22px"></div>', unsafe_allow_html=True)
    st.markdown('<section class="page-section player-section"><div class="section-head"><div><div class="kicker">Retro Music Player</div><div class="section-title">পুজোর গান · Retro Music Player</div><div class="section-desc">একটি vintage hi-fi console-এর মতো করে নির্বাচিত YouTube playlist শুনুন।</div></div></div>', unsafe_allow_html=True)
    names = list(CURATED_PLAYLISTS)
    if st.session_state.active_playlist not in names:
        st.session_state.active_playlist = names[0]
    selected = st.selectbox("Curated playlist", names, index=names.index(st.session_state.active_playlist), label_visibility="collapsed", key="v4_playlist_select")
    st.session_state.active_playlist = selected
    st.markdown(f'<div class="playlist-display"><div class="playlist-display-text">{CURATED_PLAYLISTS[selected][0]}</div></div>', unsafe_allow_html=True)
    deck(CURATED_PLAYLISTS[selected][1], CURATED_PLAYLISTS[selected][0], component_key="v4_curated_deck")
    st.markdown('</section>', unsafe_allow_html=True)

with st.container(key="client_player_tv"):
    st.markdown('<div id="tv-player" style="scroll-margin-top:22px"></div>', unsafe_allow_html=True)
    st.markdown('<section class="page-section"><div class="section-head"><div><div class="kicker">Vintage Television</div><div class="section-title">পুজো TV · Retro Television</div><div class="section-desc">পুজোর পরিক্রমা, তথ্যচিত্র, ভ্লগ, খাবারের গল্প এবং বিসর্জন — সব vintage television-এ।</div></div></div>', unsafe_allow_html=True)
    names = list(PUJO_TV_PLAYLISTS)
    if st.session_state.active_tv_playlist not in names:
        st.session_state.active_tv_playlist = names[0]
    selected = st.selectbox("Pujo TV playlist", names, index=names.index(st.session_state.active_tv_playlist), label_visibility="collapsed", key="v4_tv_select")
    st.session_state.active_tv_playlist = selected
    st.markdown(f'<div class="playlist-display"><div class="playlist-display-text">{PUJO_TV_PLAYLISTS[selected][0]}</div></div>', unsafe_allow_html=True)
    pujo_tv_deck(PUJO_TV_PLAYLISTS[selected][1], PUJO_TV_PLAYLISTS[selected][0], component_key="v4_tv_deck")
    st.markdown('</section>', unsafe_allow_html=True)

with st.container(key="client_player_radio"):
    st.markdown('<div id="radio-player" style="scroll-margin-top:22px"></div>', unsafe_allow_html=True)
    st.markdown('<section class="page-section"><div class="section-head"><div><div class="kicker">Live Broadcast</div><div class="section-title">লাইভ রেডিও · Vintage Radio</div><div class="section-desc">স্টেশন বেছে নিন, play চাপুন এবং vintage radio receiver-এ বাংলা পুজোর সুর শুনুন।</div></div></div>', unsafe_allow_html=True)
    radio_deck(RADIO_STATIONS)
    st.markdown('</section>', unsafe_allow_html=True)

with st.container(key="client_player_sounds"):
    st.markdown('<div id="sounds-player" style="scroll-margin-top:22px"></div>', unsafe_allow_html=True)
    # Browser mixer from the previous working version. It remains file-driven and works with an empty sounds folder.
    import html as _html
    tracks=[]
    for icon,bn,en,desc,filename in SOUNDS:
        candidates=[BASE_DIR / "assets/sounds"/filename,BASE_DIR / "assets/sounds"/filename.replace('.mp3','.wav'),BASE_DIR / "assets/sounds"/filename.replace('.mp3','.ogg')
        ]
        src=""
        for c in candidates:
            if c.exists():
                mime='audio/mpeg' if c.suffix.lower()=='.mp3' else 'audio/wav' if c.suffix.lower()=='.wav' else 'audio/ogg'
                src=f'data:{mime};base64,{b64(c)}'
                break
        tracks.append({"icon":icon,"name":bn,"label":en,"desc":desc,"src":src,"available":bool(src)})
    mixer_json=json.dumps(tracks)
    mixer_html="""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>
    *{box-sizing:border-box}body{margin:0;background:transparent;color:#fff7e8;font-family:Georgia,serif}.mixer{background:linear-gradient(180deg,#741522,#5b0d18);border:1px solid #d0a058;border-radius:16px;padding:16px;position:relative;overflow:hidden}.mixer:before{content:"";position:absolute;inset:7px;border:1px solid rgba(238,200,129,.3);border-radius:12px;background:radial-gradient(circle at 15% 15%,rgba(255,220,170,.1),transparent 20%),radial-gradient(circle at 85% 85%,rgba(255,220,170,.08),transparent 22%);pointer-events:none}.top{position:relative;display:flex;justify-content:space-between;gap:10px;align-items:center;padding:4px 4px 12px;border-bottom:1px solid rgba(231,188,109,.35)}.title{font-size:18px;font-weight:700}.sub{font-size:11px;color:#e6bf82;letter-spacing:1px}.master{display:flex;gap:10px;align-items:center;font-size:11px}.master input{width:120px}.grid{position:relative;display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px}.channel{background:linear-gradient(145deg,#7b1928,#55101a);border:1px solid rgba(224,178,96,.52);border-radius:12px;padding:12px;min-height:190px;box-shadow:inset 0 0 22px rgba(0,0,0,.16)}.head{display:flex;align-items:center;gap:8px}.icon{font-size:25px}.name{font-size:15px;font-weight:700}.label{font-size:9px;letter-spacing:1.5px;color:#e6bf82}.led{margin-left:auto;width:8px;height:8px;border-radius:50%;background:#4c1b22;border:1px solid #b8793c}.led.on{background:#f0b35f;box-shadow:0 0 10px #f0b35f}.desc{font-size:10px;color:#f0d5bb;line-height:1.45;margin:8px 0 9px;min-height:29px}.controls{display:flex;gap:6px}.btn{flex:1;height:30px;border-radius:6px;border:1px solid #b9854a;background:linear-gradient(#8c2b35,#531019);color:#fff0d2;font-size:9px;cursor:pointer}.btn:disabled{opacity:.45;cursor:not-allowed}.meter{height:5px;background:#3e1018;border:1px solid #8a4b35;border-radius:5px;margin:10px 0 7px;overflow:hidden}.meter span{display:block;height:100%;width:12%;background:#e3ad61;transition:width .12s}.vol{display:flex;gap:7px;align-items:center;font-size:9px;color:#e4c28e}.vol input{flex:1}.loop{font-size:9px;color:#e4c28e;margin-top:5px;display:block}.status{position:relative;margin-top:10px;border-top:1px solid rgba(231,188,109,.25);padding-top:9px;text-align:center;font-size:10px;color:#e4c28e}.stop{height:34px;padding:0 14px;border-radius:999px;border:1px solid #d5a25b;background:#f0c36d;color:#5d1018;font-weight:700;cursor:pointer}@media(max-width:760px){.grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:470px){.grid{grid-template-columns:1fr}.master{flex-wrap:wrap}}
    </style></head><body><div class="mixer"><div class="top"><div><div class="title">পুজোর সাউন্ড · Sound Mixer</div><div class="sub">MIX YOUR OWN PUJA ATMOSPHERE</div></div><div class="master">MASTER <input id="master" type="range" min="0" max="1" step="0.01" value="0.72"><button id="stop-all" class="stop">STOP ALL</button></div></div><div id="grid" class="grid"></div><div id="status" class="status">READY · ADD LICENSED FILES TO assets/sounds/ TO ENABLE A CHANNEL</div></div><script>
    const tracks=__TRACKS__,grid=document.getElementById('grid'),master=document.getElementById('master'),status=document.getElementById('status'),audios=[];tracks.forEach(t=>{const c=document.createElement('div');c.className='channel';c.innerHTML=`<div class="head"><span class="icon">${t.icon}</span><div><div class="name">${t.name}</div><div class="label">${t.label}</div></div><span class="led"></span></div><div class="desc">${t.desc}</div><div class="controls"><button class="btn play" ${t.available?'':'disabled'}>${t.available?'▶ PLAY':'OFF'}</button><button class="btn mute" ${t.available?'':'disabled'}>MUTE</button></div><div class="meter"><span></span></div><div class="vol"><span>VOL</span><input class="slider" type="range" min="0" max="1" step="0.01" value="0.72" ${t.available?'':'disabled'}></div><label class="loop"><input type="checkbox" class="loopbox" ${t.available?'checked':'disabled'}> LOOP</label>`;grid.appendChild(c);const a=new Audio();a.loop=true;a.preload='auto';a.src=t.src||'';a.volume=.72;audios.push(a);const play=c.querySelector('.play'),mute=c.querySelector('.mute'),slider=c.querySelector('.slider'),loop=c.querySelector('.loopbox'),led=c.querySelector('.led'),meter=c.querySelector('.meter span');play.onclick=async()=>{if(!t.available)return;if(a.paused){try{await a.play();play.textContent='❚❚';led.classList.add('on');status.textContent=t.label+' · PLAYING'}catch(e){status.textContent='BROWSER BLOCKED AUDIO · TAP PLAY AGAIN'}}else{a.pause();play.textContent='▶';led.classList.remove('on')}};mute.onclick=()=>{a.muted=!a.muted;mute.textContent=a.muted?'UNMUTE':'MUTE'};slider.oninput=()=>a.volume=Number(slider.value)*Number(master.value);loop.onchange=()=>a.loop=loop.checked;setInterval(()=>meter.style.width=a.paused?'12%':(18+Math.random()*78)+'%',180)});master.oninput=()=>audios.forEach((a,i)=>{const s=grid.children[i]?.querySelector('.slider');if(s)a.volume=Number(s.value)*Number(master.value)});document.getElementById('stop-all').onclick=()=>{audios.forEach((a,i)=>{a.pause();a.currentTime=0;const c=grid.children[i];if(c){const t=tracks[i];c.querySelector('.play').textContent=t.available?'▶':'OFF';c.querySelector('.led').classList.remove('on')}});status.textContent='ALL CHANNELS STOPPED'};
    </script></body></html>""".replace('__TRACKS__',mixer_json)
    st.markdown('<section class="page-section sound-shell"><div class="kicker">Puja Ambience · Sound Library</div><div class="section-title">পুজোর সাউন্ড</div><div class="section-desc">আপনার sound library-এর ফাইলগুলি <code>assets/sounds/</code>-এ যোগ করলে প্রতিটি channel সক্রিয় হবে।</div>', unsafe_allow_html=True)
    components.html(mixer_html, height=690, scrolling=False)
    st.markdown('</section>', unsafe_allow_html=True)
# Client-side section switcher. It changes only visibility and URL state; no reload and no new tab.
st.html("""<script>
(() => {
  const map = {songs:'client_player_songs', tv:'client_player_tv', radio:'client_player_radio', sounds:'client_player_sounds'};
  const nav = document.getElementById('player-nav');
  const readSection = () => {
    const q = new URLSearchParams(window.location.search).get('section');
    if (q && map[q]) return q;
    const h = (window.location.hash || '').replace('#','');
    if (h === 'songs-player') return 'songs';
    if (h === 'tv-player') return 'tv';
    if (h === 'radio-player') return 'radio';
    if (h === 'sounds-player') return 'sounds';
    return 'songs';
  };
  const show = (section, updateUrl=true, scroll=true) => {
    Object.entries(map).forEach(([key, containerKey]) => {
      const el = document.querySelector('[class*="st-key-' + containerKey + '"]');
      if (el) el.classList.toggle('client-player-visible', key === section);
    });
    if (nav) nav.querySelectorAll('[data-player-section]').forEach(a => a.classList.toggle('active', a.dataset.playerSection === section));
    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set('section', section);
      url.hash = '#' + section + '-player';
      window.history.replaceState({}, '', url.pathname + '?' + url.searchParams.toString() + url.hash);
    }
    if (scroll) {
      const anchor = document.getElementById(section + '-player');
      if (anchor) setTimeout(() => anchor.scrollIntoView({behavior:'smooth', block:'start'}), 30);
    }
  };
  const bind = () => {
    const links = document.querySelectorAll('a[href^="?section="]');
    links.forEach(a => {
      if (a.dataset.bound === '1') return;
      const href = a.getAttribute('href') || '';
      const match = href.match(/[?&]section=(songs|tv|radio|sounds)/);
      if (!match) return;
      a.dataset.bound = '1';
      a.dataset.playerSection = match[1];
      a.target = '_self';
      a.addEventListener('click', event => {
        event.preventDefault();
        show(match[1], true, true);
      });
    });
    show(readSection(), false, false);
  };
  bind();
  setTimeout(bind, 250);
  setTimeout(bind, 900);
  window.addEventListener('popstate', () => show(readSection(), false, true));
})();
</script>""", unsafe_allow_javascript=True)

# -----------------------------------------------------------------------------
# Footer + optional panels
# -----------------------------------------------------------------------------
st.markdown(
    f"""<footer class="footer">
        <div class="footer-side left"><img src="{ASSET["footer_left"]}" alt="Diya footer decoration"></div>
        <div class="footer-side right"><img src="{ASSET["footer_right"]}" alt="Dhaak footer decoration"></div>
        <div class="footer-content">
            <div class="kicker" style="color:#e7be76">SHARODIYA SUBHECHHA</div>
            <h2>শারদীয় শুভেচ্ছা</h2>
            <div class="sub">সবার জীবনে আসুক শান্তি, আনন্দ আর সমৃদ্ধি।</div>
            <div class="footer-links">
                <a class="footer-link" target="_self" rel="nofollow" href="?section=songs#songs-player">🎵 পুজোর গান</a>
                <a class="footer-link" target="_self" rel="nofollow" href="?section=tv#tv-player">📺 পুজো TV</a>
                <a class="footer-link" target="_self" rel="nofollow" href="?section=radio#radio-player">📻 লাইভ রেডিও</a>
                <a class="footer-link" target="_self" rel="nofollow" href="?section=sounds#sounds-player">🔊 পুজোর সাউন্ড</a>
                <a class="footer-link" target="_self" rel="nofollow" href="?panel=gallery#gallery">📸 পুজো গ্যালারি</a>
                <a class="footer-link" target="_self" rel="nofollow" href="?panel=analytics#analytics">📊 অ্যানালিটিক্স</a>
            </div>
            <div class="footer-email">datascientistipsitacharyya@gmail.com</div>
            <div class="footer-meta">BUILT WITH LOVE · BANGALIR UTSAV · FESTIVALS OF THE BENGALI, FOR THE BENGALI, BY THE BENGALI</div>
        </div>
    </footer>""",
    unsafe_allow_html=True,
)

if st.session_state.get("active_panel") == "gallery":
    st.markdown('<div id="gallery"></div>', unsafe_allow_html=True)
    st.markdown('<section class="page-section footer-panel"><div class="kicker">Puja Gallery</div><div class="section-title">পুজো গ্যালারি</div><div class="section-desc">আপনার Puja celebration photos এখানে যোগ করতে পারেন।</div></section>', unsafe_allow_html=True)
    gallery_dir=BASE_DIR / "assets/gallery"
    imgs=[p for p in gallery_dir.glob("*") if p.suffix.lower() in {".jpg",".jpeg",".png",".webp"}] if gallery_dir.exists() else []
    if imgs:
        st.image([str(p) for p in imgs],use_container_width=True)
    else:
        st.info("Add your Puja celebration photos to assets/gallery/ to view them here.")

elif st.session_state.get("active_panel") == "analytics":
    st.markdown('<div id="analytics"></div>', unsafe_allow_html=True)
    st.markdown('<section class="page-section footer-panel"><div class="kicker">Admin Analytics</div><div class="section-title">অ্যানালিটিক্স · Admin</div><div class="section-desc">Private interaction analytics for the site administrator.</div></section>', unsafe_allow_html=True)
    pw=st.text_input("Admin Password",type="password",key="admin_pw")
    if pw and pw==st.secrets.get("ADMIN_PASSWORD","BangalirPujoBangalirThakbe"):
        log_file=BASE_DIR / "recommendation_log.xlsx"
        if log_file.exists(): st.dataframe(pd.read_excel(log_file),use_container_width=True)
        elif (BASE_DIR / "recommendation_log.csv").exists(): st.dataframe(pd.read_csv(BASE_DIR / "recommendation_log.csv"),use_container_width=True)
        else: st.info("No interaction logs recorded yet.")
