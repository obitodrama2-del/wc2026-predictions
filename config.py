"""
Lexon çelësat API nga variablat e mjedisit (GitHub Secrets)
ose nga vlerat e vendosura direkt në skedar (lokalisht).
"""
import os

# ── Football-data.org ──────────────────────────────────────────
FOOTBALL_API_KEY = os.environ.get(
    "FOOTBALL_DATA_API_KEY",
    "e84716bdd3524721b8d744d8d921ebad"   # fallback lokal
)

# ── The Odds API (Tipico) ──────────────────────────────────────
ODDS_API_KEY = os.environ.get(
    "ODDS_API_KEY",
    "ee3d568bc28741429ddadad1105bb1fe"   # fallback lokal
)

# ── Telegram ───────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8756758704:AAGmXiPMZLjbROU53AUGyIyff6Al7VaMsw4"   # fallback lokal
)

TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID",
    "1596210476"   # fallback lokal
)
