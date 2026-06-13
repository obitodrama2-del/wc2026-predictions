"""
Lexon çelësat API VETËM nga variablat e mjedisit (GitHub Secrets lokalisht ose
në CI). Asnjë çelës nuk kodohet më në kod — kjo shmang ekspozimin në git.

Lokalisht, vendosi në mjedis para se ta nisësh, p.sh.:
    export TELEGRAM_BOT_TOKEN=...   export APISPORTS_KEY=...
ose përdor një skedar .env (i shtuar te .gitignore).
"""
import os

# ── Football-data.org ──────────────────────────────────────────
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")

# ── The Odds API (Tipico) ──────────────────────────────────────
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")

# ── API-Sports DIREKT (xG + historiku dinamik) ───────────────
# Platforma zyrtare: https://v3.football.api-sports.io
# Autentikimi bëhet VETËM me header `x-apisports-key`.
# Regjistrohu falas: https://dashboard.api-football.com/register
APISPORTS_KEY = os.environ.get("APISPORTS_KEY", "")

# ── DEPRECATED (nuk përdoren më nga dynamic_data.py) ──────────
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
SPORTMONKS_KEY = os.environ.get("SPORTMONKS_KEY", "")

# ── Telegram ───────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
