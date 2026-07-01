"""
╔══════════════════════════════════════════════════════════════════════╗
║   DYNAMIC DATA LAYER — WC 2026  (v3, direct API-Sports integration)    ║
║   API-Sports DIRECT  +  xG  +  Exponential Half-Life Time Decay        ║
╚══════════════════════════════════════════════════════════════════════╝

CILA ËSHTË NDRYSHIMI NDAJ VERSIONIT TË VJETËR
─────────────────────────────────────────────
  • Lidhet DIREKT me  https://v3.football.api-sports.io
  • Autentikim VETËM me header  `x-apisports-key`  (PA RapidAPI, PA Sportmonks)
  • Cache në SQLite (jo JSON) → i qëndrueshëm, atomik, me TTL
  • Token-bucket rate limiter (minutë + kuotë ditore e persistuar në SQLite)
  • Rënie kohore EKSPONENCIALE me HALF-LIFE të konfigurueshme

ZINXHIRI I FALLBACK-ut (automatik):
    1. API-Sports → xG  + time decay   (saktësia më e mirë)
    2. API-Sports → gola + time decay  (kur xG s'është i disponueshëm)
    3. Elo-adjusted + TEAM_STATS_BASE   (pa të dhëna live / pa çelës)

ARKITEKTURA:
    ┌──────────────────────────────────────────────────────────────┐
    │  DynamicDataProvider.get_team_lambda(team, opponent)          │
    │       ↓                                                       │
    │  1. RateLimiter.acquire()      (token-bucket: /min + /ditë)   │
    │  2. SQLiteCache.get/set        (TTL, p.sh. 6h)                │
    │  3. APISportsClient._get()     (header x-apisports-key)       │
    │  4. extract xG (ose gola si fallback)                         │
    │  5. apliko  W(t) = e^(−α·t),  α = ln(2)/half_life             │
    │  6. llogarit λ_attack, λ_defense të peshuara në kohë          │
    └──────────────────────────────────────────────────────────────┘

INTEGRIMI (drop-in në wc2026_group_predictions.py):
    from dynamic_data import get_dynamic_stats
    sh = get_dynamic_stats(hname, aname, is_home=True)
    sa = get_dynamic_stats(aname, hname, is_home=False)
"""

from __future__ import annotations

import os
import json
import math
import time
import sqlite3
import datetime
import threading
from dataclasses import dataclass
from typing import Optional, Any

import requests

# ── Modulet ekzistuese ────────────────────────────────────────
from config import APISPORTS_KEY                       # type: ignore
from prediction_engine_v2 import (                      # type: ignore
    MatchRecord,
    time_decay_weight,
    ELO_RATINGS,
)
from wc2026_group_predictions import TEAM_STATS_BASE     # type: ignore


# ══════════════════════════════════════════════════════════════
# KONFIGURIM
# ══════════════════════════════════════════════════════════════

# Endpoint-i DIREKT i API-Sports (jo RapidAPI).
API_BASE_URL = "https://v3.football.api-sports.io"

# Çelësi merret nga config (që nga ana e vet e lexon nga env / GitHub Secrets).
# Lejohet override i drejtpërdrejtë nga mjedisi për fleksibilitet.
API_KEY = os.environ.get("APISPORTS_KEY", APISPORTS_KEY)

# Skedari i bazës SQLite (cache + njehsorë kuote).
DB_FILE = os.environ.get(
    "APISPORTS_DB_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "dynamic_data.sqlite"),
)

# Sa orë qëndron i freskët një rezultat në cache.
CACHE_TTL_HOURS = float(os.environ.get("APISPORTS_CACHE_TTL_HOURS", "6"))

# ── Limitet e rate-it (default-et e planit FALAS, plotësisht të mbishkruajtshme) ──
#   Plani falas i API-Sports: 100 kërkesa/ditë, ~10 kërkesa/minutë.
RATE_PER_MINUTE = int(os.environ.get("APISPORTS_RATE_PER_MIN", "10"))
RATE_PER_DAY    = int(os.environ.get("APISPORTS_RATE_PER_DAY", "100"))

# Half-life e parazgjedhur për rënien kohore (në ditë).
#   180 ditë → një ndeshje 6-muajshe peshon gjysmën e një të sotmeje.
DEFAULT_HALF_LIFE_DAYS = float(os.environ.get("DECAY_HALF_LIFE_DAYS", "180"))


def half_life_to_alpha(half_life_days: float) -> float:
    """
    Kthen half-life (në ditë) → koeficientin e rënies α për  W(t)=e^(−α·t).

        W(half_life) = 0.5   ⇒   e^(−α·half_life) = 0.5   ⇒   α = ln(2)/half_life

    Shembuj:
        half_life =  90 ditë → α ≈ 0.0077
        half_life = 180 ditë → α ≈ 0.0039   ← default
        half_life = 365 ditë → α ≈ 0.0019
    """
    half_life_days = max(float(half_life_days), 1.0)
    return math.log(2.0) / half_life_days


DEFAULT_ALPHA = half_life_to_alpha(DEFAULT_HALF_LIFE_DAYS)


# ══════════════════════════════════════════════════════════════
# MODULI 1 — CACHE NË SQLITE  (+ njehsor kuote ditore i persistuar)
# ══════════════════════════════════════════════════════════════

class SQLiteCache:
    """
    Cache i thjeshtë çelës→vlerë në SQLite me TTL.

    Tabela `cache`     → ruan përgjigjet JSON me kohën e ruajtjes.
    Tabela `quota`     → ruan numrin e kërkesave për ditë (kuota ditore mbijeton
                         rinisjet e programit — kritike për planin falas 100/ditë).

    SQLite zgjidhet sepse:
      • shkrime atomike (s'ka skedar JSON gjysmë të shkruar nëse procesi vritet),
      • i sigurt për akses nga disa procese (GitHub Actions paralel),
      • mbështet pyetje TTL pa lexuar gjithë skedarin.
    """

    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._lock = threading.Lock()
        try:
            self._init_db()
        except sqlite3.OperationalError:
            # File-system i montuar s'e lejon SQLite (p.sh. sandbox).
            # Biem te një vendndodhje e shkruajtshme e përkohshme.
            import tempfile
            self.db_path = os.path.join(tempfile.gettempdir(), "wc26_dynamic_data.sqlite")
            self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        try:
            # WAL jep akses më të mirë paralel, por disa file-system
            # të montuara (rrjet/9p) s'e mbështesin — provohet best-effort.
            conn.execute("PRAGMA journal_mode=WAL;")
        except sqlite3.OperationalError:
            pass
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key       TEXT PRIMARY KEY,
                    payload   TEXT NOT NULL,
                    cached_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quota (
                    day   TEXT PRIMARY KEY,
                    count INTEGER NOT NULL
                )
            """)

    # ── Cache çelës→vlerë me TTL ──────────────────────────────
    def get(self, key: str, ttl_hours: float = CACHE_TTL_HOURS) -> Optional[Any]:
        """Kthen vlerën e ruajtur nëse është ende e freskët, përndryshe None."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload, cached_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        payload, cached_at = row
        age_hours = (time.time() - cached_at) / 3600.0
        if age_hours > ttl_hours:
            return None
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return None

    def set(self, key: str, value: Any) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, payload, cached_at) VALUES (?,?,?)",
                (key, json.dumps(value, ensure_ascii=False), time.time()),
            )

    # ── Njehsor kuote ditore (i persistuar) ───────────────────
    @staticmethod
    def _today_key() -> str:
        # UTC: API-Sports e reseton kuotën në mesnatë UTC.
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    def get_today_count(self) -> int:
        day = self._today_key()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT count FROM quota WHERE day = ?", (day,)
            ).fetchone()
        return int(row[0]) if row else 0

    def incr_today_count(self, n: int = 1) -> int:
        """Rrit numrin e kërkesave të sotme dhe kthen vlerën e re."""
        day = self._today_key()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO quota (day, count) VALUES (?, ?) "
                "ON CONFLICT(day) DO UPDATE SET count = count + ?",
                (day, n, n),
            )
            row = conn.execute(
                "SELECT count FROM quota WHERE day = ?", (day,)
            ).fetchone()
        return int(row[0]) if row else n


# ══════════════════════════════════════════════════════════════
# MODULI 2 — TOKEN-BUCKET RATE LIMITER
# ══════════════════════════════════════════════════════════════

class RateLimiter:
    """
    Limiter me dy nivele:

      1) Bucket për-minutë (token-bucket klasik, në kujtesë):
         kapaciteti = `per_minute`, mbushet me `per_minute/60` token/sekondë.
         Kjo shtrin kërkesat në mënyrë të barabartë (s'i lëshon në grumbull).

      2) Kuota ditore (e persistuar në SQLite):
         lejon maksimumi `per_day` kërkesa në ditën UTC. Mbijeton rinisjet.

    `acquire()` bllokon derisa të lirohet një token për-minutë; nëse kuota
    ditore është shteruar, kthen False (s'pret deri nesër).

    Të gjitha vlerat janë default-et e planit FALAS por plotësisht të
    mbishkruajtshme nga konstruktori ose nga variablat e mjedisit.
    """

    def __init__(self,
                 cache: SQLiteCache,
                 per_minute: int = RATE_PER_MINUTE,
                 per_day: int = RATE_PER_DAY):
        self.cache = cache
        self.per_minute = max(1, int(per_minute))
        self.per_day = max(1, int(per_day))

        # Gjendja e token-bucket-it për-minutë.
        self.capacity = float(self.per_minute)
        self.tokens = float(self.per_minute)
        self.refill_rate = self.per_minute / 60.0  # token/sekondë
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self._last_refill = now

    def remaining_today(self) -> int:
        return max(0, self.per_day - self.cache.get_today_count())

    def acquire(self, block: bool = True, max_wait: float = 30.0) -> bool:
        """
        Përpiqet të marrë një token.

        Returns:
            True  → leje e dhënë (kërkesa mund të dërgohet), kuota u rrit me 1.
            False → kuota ditore u shter, ose s'u lirua token brenda `max_wait`.
        """
        # 1) Kontroll i kuotës ditore (e fortë — s'pres deri nesër).
        if self.remaining_today() <= 0:
            print(f"  [RateLimiter] Kuota ditore u shter "
                  f"({self.per_day}/ditë). Prit reset-in në mesnatë UTC.")
            return False

        # 2) Token-bucket për-minutë.
        deadline = time.monotonic() + max_wait
        while True:
            with self._lock:
                self._refill()
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    self.cache.incr_today_count(1)
                    return True
                needed = (1.0 - self.tokens) / self.refill_rate
            if not block:
                return False
            if time.monotonic() + needed > deadline:
                print(f"  [RateLimiter] Time-out duke pritur token "
                      f"({self.per_minute}/min).")
                return False
            time.sleep(min(needed, deadline - time.monotonic()))


# ══════════════════════════════════════════════════════════════
# MODULI 3 — API-SPORTS CLIENT (DIREKT, header x-apisports-key)
# ══════════════════════════════════════════════════════════════

class APISportsClient:
    """
    Wrapper për API-Sports DIREKT (jo RapidAPI).

      Base URL : https://v3.football.api-sports.io
      Auth     : VETËM header  `x-apisports-key: <KEY>`
      Docs     : https://www.api-football.com/documentation-v3

    Çdo kërkesë kalon nga RateLimiter + SQLiteCache.
    """

    def __init__(self,
                 api_key: str = API_KEY,
                 cache: Optional[SQLiteCache] = None,
                 rate_limiter: Optional[RateLimiter] = None,
                 cache_ttl_hours: float = CACHE_TTL_HOURS):
        self.api_key = api_key or ""
        self.cache = cache or SQLiteCache()
        self.rate = rate_limiter or RateLimiter(self.cache)
        self.cache_ttl_hours = cache_ttl_hours
        # Bëhet True kur plani (falas) nuk lejon një veçori (p.sh. param `last`).
        # Pasi vendoset, klienti çaktivizohet për sesionin → fallback i pastër,
        # pa shpenzuar thirrje kot e pa spam gabimesh për çdo ekip.
        self.plan_limited = False

    @property
    def enabled(self) -> bool:
        """A kemi çelës të vlefshëm dhe plan që lejon thirrje live?"""
        return bool(self.api_key) and not self.plan_limited

    def _headers(self) -> dict:
        # VETËM x-apisports-key. PA `X-RapidAPI-Key`, PA `X-RapidAPI-Host`.
        return {"x-apisports-key": self.api_key}

    def _get(self, endpoint: str, params: dict) -> Optional[dict]:
        """
        GET i kontrolluar nga rate-limiter dhe me cache.

        Renditja:
            cache → (nëse mungon) rate-limiter.acquire() → HTTP GET → ruaj në cache.
        """
        if not self.enabled:
            return None

        # Çelës cache-i unik për (endpoint, params).
        cache_key = f"{endpoint}?{json.dumps(params, sort_keys=True)}"
        cached = self.cache.get(cache_key, self.cache_ttl_hours)
        if cached is not None:
            return cached

        # Merr leje nga rate-limiter përpara çdo thirrjeje reale.
        if not self.rate.acquire():
            return None

        url = f"{API_BASE_URL}/{endpoint.lstrip('/')}"
        try:
            r = requests.get(url, headers=self._headers(), params=params, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"  [API-Sports] Gabim rrjeti: {e}")
            return None

        # Trajtimi i kodeve të zakonshme të API-Sports.
        if r.status_code == 429:
            print("  [API-Sports] 429 Too Many Requests — pres 5s.")
            time.sleep(5)
            return None
        if r.status_code in (401, 403):
            print(f"  [API-Sports] {r.status_code}: çelës i pavlefshëm ose i pa-abonuar.")
            return None
        if r.status_code != 200:
            print(f"  [API-Sports] HTTP {r.status_code} në /{endpoint}")
            return None

        try:
            data = r.json()
        except ValueError:
            print("  [API-Sports] Përgjigje jo-JSON.")
            return None

        # API-Sports i kthen gabimet brenda trupit edhe me HTTP 200.
        errors = data.get("errors")
        if errors and (isinstance(errors, dict) and errors or
                       isinstance(errors, list) and errors):
            # Kufizim plani (p.sh. "Free plans do not have access to the Last
            # parameter") → çaktivizo xG-në për sesionin (fallback i pastër).
            if "plan" in str(errors).lower() or "last parameter" in str(errors).lower():
                if not self.plan_limited:
                    print("  [API-Sports] Plani nuk lejon këtë veçori (xG) → "
                          "kalohet te golat/Elo për të gjitha ndeshjet.")
                self.plan_limited = True
            else:
                print(f"  [API-Sports] Gabim API: {errors}")
            return None

        # Ruaj në cache vetëm përgjigjet e suksesshme.
        self.cache.set(cache_key, data)
        return data

    # ── Endpoint: zgjidh ID-në e ekipit nga emri ──────────────
    def search_team_id(self, team_name: str) -> Optional[int]:
        """
        /teams?search=<emri>  →  team.id
        Për kombëtaret, filtron rezultatet me `national: True`.
        """
        data = self._get("teams", {"search": team_name})
        if not data or not data.get("response"):
            return None

        # Preferon ekipin kombëtar nëse ka disa përputhje.
        national = [
            item for item in data["response"]
            if item.get("team", {}).get("national") is True
        ]
        chosen = national[0] if national else data["response"][0]
        return chosen.get("team", {}).get("id")

    # ── Endpoint: ndeshjet e fundit ───────────────────────────
    def get_recent_fixtures(self, team_id: int, last_n: int = 10) -> list[dict]:
        """
        /fixtures?team=<id>&last=<N>  →  lista e ndeshjeve të mbaruara.
        """
        data = self._get("fixtures", {"team": team_id, "last": last_n})
        if not data or not data.get("response"):
            return []
        return data["response"]

    # ── Endpoint: statistika (xG) për një ndeshje ─────────────
    def get_fixture_xg(self, fixture_id: int, team_id: int) -> Optional[float]:
        """
        /fixtures/statistics?fixture=<id>&team=<id>  →  vlera e 'expected_goals'.

        Kthen float-in e xG nëse plani e mbështet, përndryshe None.
        """
        data = self._get("fixtures/statistics",
                          {"fixture": fixture_id, "team": team_id})
        if not data or not data.get("response"):
            return None
        for block in data["response"]:
            for stat in block.get("statistics", []):
                if str(stat.get("type", "")).lower() in ("expected_goals", "expected goals"):
                    val = stat.get("value")
                    try:
                        return float(val) if val is not None else None
                    except (TypeError, ValueError):
                        return None
        return None

    # ── Konverton fikstura → MatchRecord (me xG kur ka) ───────
    def extract_match_records(self,
                              team_id: int,
                              last_n: int = 10,
                              use_xg: bool = True) -> tuple[list[MatchRecord], bool]:
        """
        Ndërton listën e MatchRecord nga fiksturat e fundit të ekipit.

        Returns:
            (records, xg_used)  ku xg_used=True nëse të paktën gjysma e
            regjistrimeve përdorën xG real (jo gola).
        """
        fixtures = self.get_recent_fixtures(team_id, last_n)
        records: list[MatchRecord] = []
        xg_count = 0

        for fx in fixtures:
            fixture = fx.get("fixture", {})
            teams = fx.get("teams", {})
            goals = fx.get("goals", {})

            # Vetëm ndeshje të mbaruara.
            status = fixture.get("status", {}).get("short")
            if status not in ("FT", "AET", "PEN"):
                continue

            # A ishte ekipi ynë vendës?
            home = teams.get("home", {})
            away = teams.get("away", {})
            if home.get("id") == team_id:
                is_home = True
                gs, gc = goals.get("home"), goals.get("away")
            elif away.get("id") == team_id:
                is_home = False
                gs, gc = goals.get("away"), goals.get("home")
            else:
                continue
            if gs is None or gc is None:
                continue

            # Data e ndeshjes.
            date_str = fixture.get("date", "")[:10]
            try:
                match_date = datetime.date.fromisoformat(date_str)
            except (ValueError, TypeError):
                continue

            scored, conceded = float(gs), float(gc)

            # Përpiqu të marrësh xG (kushton një kërkesë shtesë për ndeshje).
            if use_xg:
                fid = fixture.get("id")
                opp_id = (away.get("id") if is_home else home.get("id"))
                xg_for = self.get_fixture_xg(fid, team_id) if fid else None
                xg_against = self.get_fixture_xg(fid, opp_id) if (fid and opp_id) else None
                if xg_for is not None:
                    scored = xg_for
                    xg_count += 1
                if xg_against is not None:
                    conceded = xg_against

            records.append(MatchRecord(
                date=match_date,
                goals_scored=scored,
                goals_conceded=conceded,
                is_home=is_home,
            ))

        xg_used = bool(records) and (xg_count / len(records)) >= 0.5
        return records, xg_used


# ══════════════════════════════════════════════════════════════
# MODULI 4 — RËNIA KOHORE EKSPONENCIALE (HALF-LIFE)
# ══════════════════════════════════════════════════════════════

@dataclass
class DecayedLambda:
    """Rezultati i llogaritjes së λ me rënie kohore për një ekip."""
    lam_attack:     float           # xG/gola të peshuar të shënuar
    lam_defense:    float           # xG/gola të peshuar të pësuar
    matches_used:   int
    data_source:    str             # "xg_live" | "goals_live" | "elo_static"
    xg_available:   bool = False
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS
    alpha:          float = DEFAULT_ALPHA


def compute_time_decayed_lambda(records: list[MatchRecord],
                                half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
                                min_matches: int = 3,
                                xg_flag: bool = False) -> Optional[DecayedLambda]:
    """
    Llogarit λ_attack dhe λ_defense me peshim eksponencial sipas kohës.

        α      = ln(2) / half_life          (gjysma e peshës çdo `half_life` ditë)
        W(t)   = e^(−α · t),   t = ditë nga ndeshja
        λ_att  = Σ(scored_i   · W_i) / Σ(W_i)
        λ_def  = Σ(conceded_i · W_i) / Σ(W_i)

    Args:
        records:        Lista e MatchRecord.
        half_life_days: Gjysmë-jeta e peshës (default 180 ditë).
        min_matches:    Minimumi i ndeshjeve për vlerësim të besueshëm.
        xg_flag:        True nëse të dhënat janë xG real.

    Returns:
        DecayedLambda ose None nëse të dhënat s'mjaftojnë.
    """
    if not records or len(records) < min_matches:
        return None

    alpha = half_life_to_alpha(half_life_days)
    today = datetime.date.today()
    total_w = w_attack = w_defense = 0.0

    for rec in records:
        w = time_decay_weight(rec.date, today, alpha)
        w_attack  += rec.goals_scored   * w
        w_defense += rec.goals_conceded * w
        total_w   += w

    if total_w < 1e-9:
        return None

    return DecayedLambda(
        lam_attack     = round(w_attack  / total_w, 4),
        lam_defense    = round(w_defense / total_w, 4),
        matches_used   = len(records),
        data_source    = "xg_live" if xg_flag else "goals_live",
        xg_available   = xg_flag,
        half_life_days = half_life_days,
        alpha          = alpha,
    )


def decay_weight_table(half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> None:
    """Printon një tabelë referencë të peshave për horizonte të zakonshme kohore."""
    alpha = half_life_to_alpha(half_life_days)
    print(f"\n  Tabela e Rënies Kohore (half-life={half_life_days:g} ditë, α={alpha:.5f})")
    print(f"  {'Ditë':>8}  {'Peshë':>10}  {'Muaj':>8}")
    print("  " + "─" * 32)
    for days in [7, 30, 60, 90, 180, 270, 365, 540, 730]:
        w = math.exp(-alpha * days)
        print(f"  {days:>8}  {w:>10.4f}  {days/30:>8.1f}")


# ══════════════════════════════════════════════════════════════
# MODULI 5 — FALLBACK: ELO + STATIKE
# ══════════════════════════════════════════════════════════════

def elo_adjusted_static_lambda(team_name: str,
                               opponent_name: str,
                               is_home: bool,
                               blend: float = 0.30) -> DecayedLambda:
    """
    Fallback kur s'ka të dhëna live (pa çelës ose kuotë e shteruar).
    Përdor TEAM_STATS_BASE + diferencën Elo për të rregulluar λ-të.

        P_elo(ekipi fiton) = 1 / (1 + 10^(−ΔElo/400))
    """
    t_key = team_name.strip().lower()
    o_key = opponent_name.strip().lower()

    t_scored, t_conc = (TEAM_STATS_BASE.get(t_key, (1.2, 1.2, 0))[:2])
    o_scored, o_conc = (TEAM_STATS_BASE.get(o_key, (1.2, 1.2, 0))[:2])

    lam_attack  = math.sqrt(t_scored * o_conc)
    lam_defense = math.sqrt(o_scored * t_conc)

    t_elo = ELO_RATINGS.get(t_key, 1500)
    o_elo = ELO_RATINGS.get(o_key, 1500)
    delta = (t_elo - o_elo) if is_home else (o_elo - t_elo)
    p_elo = 1.0 / (1.0 + 10.0 ** (-delta / 400.0))

    scale_attack  = 1.0 + blend * (p_elo - 0.5) * 2
    scale_defense = 1.0 - blend * (p_elo - 0.5) * 2

    return DecayedLambda(
        lam_attack   = round(max(0.3, lam_attack  * scale_attack),  4),
        lam_defense  = round(max(0.3, lam_defense * scale_defense), 4),
        matches_used = 0,
        data_source  = "elo_static",
        xg_available = False,
    )


# ══════════════════════════════════════════════════════════════
# MODULI 6 — DYNAMIC DATA PROVIDER (orkestruesi)
# ══════════════════════════════════════════════════════════════

# Normalizim emrash për pyetjet drejt API-Sports.
TEAM_NAME_API_MAP: dict[str, str] = {
    "usa":                  "USA",
    "united states":        "USA",
    "korea republic":       "South Korea",
    "south korea":          "South Korea",
    "ir iran":              "Iran",
    "côte d'ivoire":        "Ivory Coast",
    "cote d'ivoire":        "Ivory Coast",
    "congo dr":             "DR Congo",
    "dr congo":             "DR Congo",
    "democratic republic of congo": "DR Congo",
    "bosnia-herzegovina":   "Bosnia",
    "czechia":              "Czech Republic",
    "cape verde":           "Cape Verde",
    "curacao":              "Curacao",
    "curaçao":              "Curacao",
}


class DynamicDataProvider:
    """
    Orkestron marrjen e të dhënave me fallback automatik:
        API-Sports (xG) → API-Sports (gola) → Elo + Statike

    Usage:
        provider = DynamicDataProvider(half_life_days=180)
        res = provider.get_team_lambda("Brazil", "Haiti", is_home=True)
        res.lam_attack, res.lam_defense, res.data_source
    """

    def __init__(self,
                 half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
                 min_matches: int = 3,
                 last_n_matches: int = 10,
                 use_xg: bool = True,
                 client: Optional[APISportsClient] = None):
        self.half_life_days = half_life_days
        self.min_matches = min_matches
        self.last_n_matches = last_n_matches
        self.use_xg = use_xg
        self.client = client or APISportsClient()
        self._team_id_cache: dict[str, Optional[int]] = {}

    def _resolve_api_name(self, name: str) -> str:
        return TEAM_NAME_API_MAP.get(name.strip().lower(), name.strip().title())

    def _team_id(self, team_name: str) -> Optional[int]:
        key = team_name.strip().lower()
        if key in self._team_id_cache:
            return self._team_id_cache[key]
        api_name = self._resolve_api_name(team_name)
        tid = self.client.search_team_id(api_name)
        self._team_id_cache[key] = tid
        return tid

    def get_team_lambda(self,
                        team_name: str,
                        opponent_name: str,
                        is_home: bool = True) -> DecayedLambda:
        """
        Metoda kryesore: kthen DecayedLambda për ekipin kundër kundërshtarit.
        Provon secilin burim sipas radhës së fallback-ut.
        """
        if self.client.enabled:
            team_id = self._team_id(team_name)
            if team_id:
                records, xg_used = self.client.extract_match_records(
                    team_id, self.last_n_matches, self.use_xg
                )
                if records and len(records) >= self.min_matches:
                    result = compute_time_decayed_lambda(
                        records, self.half_life_days, self.min_matches, xg_used
                    )
                    if result:
                        print(f"  [{team_name}] Burimi: API-Sports "
                              f"({'xG' if xg_used else 'gola'}) — "
                              f"{len(records)} ndeshje, half-life={self.half_life_days:g}d")
                        return result

        # Fallback final: Elo + statike.
        print(f"  [{team_name}] Burimi: Elo+Statike (fallback)")
        return elo_adjusted_static_lambda(team_name, opponent_name, is_home)

    def get_match_lambdas(self,
                          home_name: str,
                          away_name: str) -> tuple[DecayedLambda, DecayedLambda]:
        """Kthen (λ_home, λ_away) për një ndeshje."""
        lam_home = self.get_team_lambda(home_name, away_name, is_home=True)
        lam_away = self.get_team_lambda(away_name, home_name, is_home=False)
        return lam_home, lam_away


# ══════════════════════════════════════════════════════════════
# NDIHMËS INTEGRIMI — drop-in për wc2026_group_predictions.py
# ══════════════════════════════════════════════════════════════

_provider: Optional[DynamicDataProvider] = None


def get_provider(half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> DynamicDataProvider:
    """Kthen një instancë globale të ri-përdorshme të provider-it."""
    global _provider
    if _provider is None:
        _provider = DynamicDataProvider(half_life_days=half_life_days)
    return _provider


def get_dynamic_stats(team_name: str,
                      opponent_name: str,
                      is_home: bool,
                      half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> dict:
    """
    Zëvendësues drop-in për default_stats() në wc2026_group_predictions.py.

    Përdorim:
        from dynamic_data import get_dynamic_stats
        sh = get_dynamic_stats(hname, aname, is_home=True)
        sa = get_dynamic_stats(aname, hname, is_home=False)
    """
    provider = get_provider(half_life_days)
    res = provider.get_team_lambda(team_name, opponent_name, is_home)
    return {
        "goals_scored_avg":   res.lam_attack,
        "goals_conceded_avg": res.lam_defense,
        "points_per_game":    1.5,            # neutral (s'përdoret nga DC)
        "played":             res.matches_used,
        "form":               res.data_source,
        "source":             res.data_source,
        "xg_available":       res.xg_available,
    }


# ══════════════════════════════════════════════════════════════
# DEMO
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 64)
    print("  DYNAMIC DATA LAYER v3 — DEMO (API-Sports direkt)")
    print("=" * 64)

    decay_weight_table(half_life_days=DEFAULT_HALF_LIFE_DAYS)

    print(f"\n  Çelësi API i konfiguruar: {'PO' if API_KEY else 'JO (përdor fallback)'}")
    print("\n  DEMO: fallback Elo+Statike (s'kërkon çelës)")
    print("  " + "─" * 56)

    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from prediction_engine_v2 import dixon_coles_predict

    test_matches = [
        ("Brazil",    "Haiti"),
        ("Argentina", "Qatar"),
        ("Mexico",    "Poland"),
        ("Germany",   "Curaçao"),
        ("USA",       "Morocco"),
        ("Spain",     "Japan"),
    ]

    for home, away in test_matches:
        lh = elo_adjusted_static_lambda(home, away, is_home=True)
        la = elo_adjusted_static_lambda(away, home, is_home=False)
        lam_h = math.sqrt(lh.lam_attack * la.lam_defense)
        lam_a = math.sqrt(la.lam_attack * lh.lam_defense)
        dc = dixon_coles_predict(lam_h, lam_a)
        print(f"  {home:<11} vs {away:<10}  "
              f"1={dc['prob_h']:>5.1f}%  X={dc['prob_d']:>5.1f}%  2={dc['prob_a']:>5.1f}%"
              f"  [{lh.data_source}]")

    print()
    print("  Për të dhëna LIVE:")
    print("  1. Merr çelës falas: https://dashboard.api-football.com/register")
    print("  2. Vendos APISPORTS_KEY në config.py ose si GitHub Secret")
    print("  3. (opsionale) DECAY_HALF_LIFE_DAYS, APISPORTS_RATE_PER_DAY etj.")
    print("=" * 64)
