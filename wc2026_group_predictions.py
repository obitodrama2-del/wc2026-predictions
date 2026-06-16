"""
⚽ WC 2026 - Parashikime për të gjitha ndeshjet e fazës së grupeve
Merr automatikisht ndeshjet nga football-data.org dhe bën parashikimin Poisson
"""

import requests
import math
import time
import json
import os
from itertools import product
from collections import defaultdict

CACHE_FILE = os.path.join(os.path.dirname(__file__), "wc2026_cache.json")
REQUEST_DELAY = 6.5   # sekonda midis kërkesave (free tier: max 10/min)

# ─── STATS BAZË PËR TË GJITHA SKUADRAT WC 2026 ───────────────
# Bazuar në: FIFA ranking + forma e fundit ndërkombëtare (2023-2025)
# scored_avg, conceded_avg, points_per_game
TEAM_STATS_BASE = {
    # scored_avg, conceded_avg, points_per_game
    # ── ELITE ───────────────────────────────────────────────────
    "argentina":            (3.2, 0.5, 2.5),
    "spain":                (2.8, 0.4, 2.4),
    "france":               (2.6, 0.6, 2.4),
    "brazil":               (2.8, 0.6, 2.3),
    "england":              (2.3, 0.6, 2.3),
    "portugal":             (2.6, 0.7, 2.3),
    "germany":              (2.5, 0.7, 2.1),
    "netherlands":          (2.2, 0.8, 2.1),
    "belgium":              (2.0, 0.8, 2.0),
    # ── SHUMË TË FORTË ──────────────────────────────────────────
    "colombia":             (2.0, 0.9, 2.0),
    "norway":               (2.0, 1.0, 1.9),
    "mexico":               (1.8, 1.0, 1.9),
    "austria":              (1.8, 0.9, 1.9),
    "uruguay":              (1.8, 0.9, 1.9),
    "switzerland":          (1.7, 0.9, 1.9),
    "united states":        (1.7, 0.9, 1.8),
    "usa":                  (1.7, 0.9, 1.8),
    "japan":                (1.8, 1.0, 1.8),
    # ── TË FORTË ────────────────────────────────────────────────
    "korea republic":       (1.6, 1.0, 1.7),
    "south korea":          (1.6, 1.0, 1.7),
    "morocco":              (1.5, 0.8, 1.8),
    "senegal":              (1.5, 0.9, 1.7),
    "croatia":              (1.5, 1.0, 1.7),
    "turkey":               (1.6, 1.1, 1.7),
    "czech republic":       (1.5, 1.1, 1.7),
    "czechia":              (1.5, 1.1, 1.7),
    "sweden":               (1.5, 1.1, 1.6),
    "ecuador":              (1.5, 1.1, 1.7),
    "canada":               (1.4, 1.0, 1.6),
    "ivory coast":          (1.5, 1.1, 1.6),
    "côte d'ivoire":        (1.5, 1.1, 1.6),
    "scotland":             (1.4, 1.2, 1.5),
    "algeria":              (1.4, 1.0, 1.6),
    "egypt":                (1.3, 1.0, 1.5),
    # ── MESATARË ────────────────────────────────────────────────
    "iran":                 (1.3, 1.0, 1.5),
    "ghana":                (1.3, 1.2, 1.4),
    "australia":            (1.3, 1.2, 1.5),
    "paraguay":             (1.3, 1.2, 1.4),
    "bosnia & herzegovina": (1.3, 1.2, 1.5),
    "bosnia-herzegovina":   (1.3, 1.2, 1.5),
    "tunisia":              (1.2, 1.2, 1.4),
    "dr congo":             (1.1, 1.3, 1.3),
    "congo dr":             (1.1, 1.3, 1.3),
    "cape verde":           (1.1, 1.3, 1.3),
    "cape verde islands":   (1.1, 1.3, 1.3),
    "uzbekistan":           (1.0, 1.4, 1.2),
    # ── TË DOBËT ────────────────────────────────────────────────
    "saudi arabia":         (1.0, 1.4, 1.1),
    "south africa":         (1.0, 1.5, 1.1),
    "jordan":               (0.9, 1.5, 1.0),
    "iraq":                 (0.9, 1.5, 1.0),
    "new zealand":          (0.8, 1.6, 0.9),
    "panama":               (0.8, 1.6, 0.9),
    # ── SHUMË TË DOBËT ──────────────────────────────────────────
    "qatar":                (0.7, 1.9, 0.8),
    "haiti":                (0.6, 2.1, 0.6),
    "curaçao":              (0.7, 2.0, 0.7),
    "curacao":              (0.7, 2.0, 0.7),
}

from config import FOOTBALL_API_KEY as API_KEY  # type: ignore
BASE_URL = "https://api.football-data.org/v4"
HEADERS  = {"X-Auth-Token": API_KEY}
WC_CODE  = "WC"


# ─── API ──────────────────────────────────────────────────────

_last_request_time = 0.0

def api_get(endpoint: str, params: dict = {}) -> dict | None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)
    try:
        r = requests.get(f"{BASE_URL}{endpoint}", headers=HEADERS,
                         params=params, timeout=15, verify=True)
        _last_request_time = time.time()
    except requests.exceptions.SSLError:
        # SSL gabim — provo pa verifikim (fallback)
        try:
            r = requests.get(f"{BASE_URL}{endpoint}", headers=HEADERS,
                             params=params, timeout=15, verify=False)
            _last_request_time = time.time()
        except Exception:
            return None
    except (requests.exceptions.ConnectionError,
            requests.exceptions.Timeout):
        return None

    if r.status_code == 429:
        print(f"  ⏳ Rate limit, pres 15s...")
        time.sleep(15)
        try:
            r = requests.get(f"{BASE_URL}{endpoint}", headers=HEADERS,
                             params=params, timeout=15, verify=False)
            _last_request_time = time.time()
        except Exception:
            return None
    if r.status_code != 200:
        print(f"  ⚠ {endpoint} → {r.status_code}")
        return None
    return r.json()


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def get_group_stage_matches() -> list[dict]:
    """Merr të gjitha ndeshjet e fazës së grupeve (SCHEDULED + FINISHED)."""
    data = api_get(f"/competitions/{WC_CODE}/matches", {"stage": "GROUP_STAGE"})
    if not data:
        return []
    return data.get("matches", [])


def get_wc_finished_matches() -> list[dict]:
    """Merr të gjitha ndeshjet e WC të përfunduara — për statistika."""
    data = api_get(f"/competitions/{WC_CODE}/matches", {"status": "FINISHED"})
    if not data:
        return []
    return data.get("matches", [])


def get_team_recent_matches(team_id: int, cache: dict, limit: int = 10) -> list[dict]:
    """Merr ndeshjet e fundit të skuadrës — nga cache nëse ekziston."""
    key = f"team_{team_id}_matches"
    if key in cache:
        return cache[key]
    data = api_get(f"/teams/{team_id}/matches", {"status": "FINISHED", "limit": limit})
    if not data:
        return []
    matches = data.get("matches", [])
    cache[key] = matches
    return matches


# ─── STATISTIKAT PER SKUADER ──────────────────────────────────

def build_team_stats(finished_matches: list[dict]) -> dict[int, dict]:
    """
    Nga ndeshjet e përfunduara ndërton statistikat për çdo skuadër:
    goals_scored, goals_conceded, played
    """
    stats = defaultdict(lambda: {"scored": 0, "conceded": 0, "played": 0,
                                  "wins": 0, "draws": 0, "losses": 0})
    for m in finished_matches:
        hs = m["score"]["fullTime"]["home"]
        as_ = m["score"]["fullTime"]["away"]
        if hs is None or as_ is None:
            continue

        hid = m["homeTeam"]["id"]
        aid = m["awayTeam"]["id"]

        stats[hid]["scored"]   += hs
        stats[hid]["conceded"] += as_
        stats[hid]["played"]   += 1
        stats[aid]["scored"]   += as_
        stats[aid]["conceded"] += hs
        stats[aid]["played"]   += 1

        if hs > as_:
            stats[hid]["wins"]   += 1; stats[aid]["losses"] += 1
        elif hs == as_:
            stats[hid]["draws"]  += 1; stats[aid]["draws"]  += 1
        else:
            stats[hid]["losses"] += 1; stats[aid]["wins"]   += 1

    # Mesataret
    result = {}
    for tid, s in stats.items():
        n = s["played"] if s["played"] > 0 else 1
        pts = s["wins"] * 3 + s["draws"]
        result[tid] = {
            "goals_scored_avg":   round(s["scored"]   / n, 2),
            "goals_conceded_avg": round(s["conceded"] / n, 2),
            "points_per_game":    round(pts / n, 2),
            "played":             s["played"],
            "form":               f"{s['wins']}F {s['draws']}B {s['losses']}H",
        }
    return result


def default_stats(team_name: str = "") -> dict:
    """Stats bazë — merr nga tabela TEAM_STATS_BASE nëse ekziston."""
    key = team_name.strip().lower()
    if key in TEAM_STATS_BASE:
        s, c, p = TEAM_STATS_BASE[key]
    else:
        s, c, p = 1.2, 1.2, 1.0   # fallback i fundit
    return {
        "goals_scored_avg":   s,
        "goals_conceded_avg": c,
        "points_per_game":    p,
        "played":             0,
        "form":               "FIFA-rank",
        "source":             "fifa_base",
    }


# Sa "ndeshje fiktive" peshon priori (tabela) kundër të dhënave live.
# Me 1 ndeshje reale dhe PRIOR=4 → 20% live, 80% tabelë (mbron nga zhurma).
PRIOR_MATCHES = float(os.environ.get("PRIOR_MATCHES", "4"))


def blended_stats(team_name: str, live: dict) -> dict:
    """
    Përzien statistikat live (nga ndeshjet e luajtura) me priorin e tabelës,
    me peshë sipas numrit të ndeshjeve: w = n / (n + PRIOR_MATCHES).
    Pak ndeshje → dominon tabela; shumë ndeshje → dominon forma reale.
    Kjo shmang që 1 ndeshje e vetme (zhurmë) të përmbysë favoritin.
    """
    base = default_stats(team_name)
    n = int(live.get("played", 0) or 0)
    if n <= 0:
        return base
    w = n / (n + PRIOR_MATCHES)
    return {
        "goals_scored_avg":   w * live["goals_scored_avg"]   + (1 - w) * base["goals_scored_avg"],
        "goals_conceded_avg": w * live["goals_conceded_avg"] + (1 - w) * base["goals_conceded_avg"],
        "points_per_game":    live.get("points_per_game", base["points_per_game"]),
        "played":             n,
        "form":               live.get("form", base["form"]),
        "source":             f"blend({n}m+{live.get('source','goals')})",
    }


# ══════════════════════════════════════════════════════════════
# PËRMIRËSIMI #1 — xG si burimi kryesor i λ
# ══════════════════════════════════════════════════════════════
# xG/xGA janë statistikisht shumë më të qëndrueshme se golat e papërpunuar
# (një 5-0 ose 0-4 s'përfaqëson gjithmonë performancën). Kur API jep xG,
# e përdorim atë si burim të λ-së; përndryshe biem te golat live, e në fund te tabela.
USE_XG_LAMBDA = os.environ.get("USE_XG_LAMBDA", "1") not in ("0", "false", "False", "")


def _xg_live_stats(team_name: str, opponent_name: str, is_home: bool) -> Optional[dict]:
    """
    Përpiqet të marrë xGF/xGA të peshuara në kohë nga shtresa dinamike (API-Sports).
    Kthen një dict {goals_scored_avg=xGF, goals_conceded_avg=xGA, played, source}
    VETËM nëse xG është vërtet i disponueshëm; ndryshe None (→ fallback te golat/tabela).

    Import i vonuar: dynamic_data importon nga ky modul (shmang import-in cirkular).
    Pa çelës API, get_dynamic_stats short-circuit-on pa kosto rrjeti dhe kthen
    xg_available=False → ky funksion kthen None → sjellja e vjetër ruhet (backward compatible).
    """
    if not USE_XG_LAMBDA:
        return None
    try:
        from dynamic_data import get_dynamic_stats   # type: ignore
        s = get_dynamic_stats(team_name, opponent_name, is_home)
    except Exception:
        return None
    if s.get("xg_available") and int(s.get("played", 0) or 0) >= 1:
        return {
            "goals_scored_avg":   s["goals_scored_avg"],    # xGF
            "goals_conceded_avg": s["goals_conceded_avg"],  # xGA
            "played":             int(s["played"]),
            "source":             "xG",
        }
    return None


def resolve_match_stats(team_name: str, opponent_name: str, is_home: bool,
                        goals_stats: Optional[dict]) -> dict:
    """
    Zgjedh burimin më të mirë të statistikave për një ekip dhe e përzien me priorin:
        1) xG live (nëse ekziston)      — preferohet (më pak variancë)
        2) gola live (football-data)    — fallback
        3) tabela TEAM_STATS_BASE       — fallback final
    Përzierja Bayesiane (blended_stats) zbatohet njësoj për (1) dhe (2).
    """
    live = _xg_live_stats(team_name, opponent_name, is_home)
    if live is None:
        live = goals_stats          # gola live nga ndeshjet e WC (ose None)
    if not live or int(live.get("played", 0) or 0) <= 0:
        return default_stats(team_name)
    return blended_stats(team_name, live)


# ─── MODELI DIXON-COLES (v2) ──────────────────────────────────
# Importo motorin e ri — zëvendëson Poisson bazë
from prediction_engine_v2 import (          # type: ignore
    dixon_coles_predict,
    apply_all_wc_modifiers,
    TeamProfile,
    ELO_RATINGS,
)

# Skuadrat pritëse dhe qytetet e tyre (për host advantage)
HOST_PROFILES: dict[str, TeamProfile] = {
    "united states": TeamProfile("united states", is_host=True,
        host_cities=["New York","Los Angeles","Dallas","San Francisco",
                     "Seattle","Boston","Kansas City","Atlanta","Houston","Miami"]),
    "usa":           TeamProfile("usa", is_host=True,
        host_cities=["New York","Los Angeles","Dallas","San Francisco",
                     "Seattle","Boston","Kansas City","Atlanta","Houston","Miami"]),
    "mexico":        TeamProfile("mexico", is_host=True,
        host_cities=["Mexico City","Guadalajara","Monterrey"]),
    "canada":        TeamProfile("canada", is_host=True,
        host_cities=["Toronto","Vancouver"]),
}


# ── Parametrat e kalibrimit të lambda-ve ──────────────────────
# Pesha e Elo-s në përzierje (0=vetëm tabela, 1=vetëm Elo).
#   ELO_BLEND_WEIGHT  → kur s'ka të dhëna live (tabela statike).
#   ELO_WEIGHT_LIVE   → kur ka formë reale (≥ MIN_LIVE ndeshje) → besohet më shumë forma.
ELO_BLEND_WEIGHT = float(os.environ.get("ELO_BLEND_WEIGHT", "0.50"))
ELO_WEIGHT_LIVE  = float(os.environ.get("ELO_WEIGHT_LIVE",  "0.30"))
MIN_LIVE_MATCHES = int(os.environ.get("MIN_LIVE_MATCHES", "5"))

# Mesatarja e golave për ekip (bazë e modelit shumëzues).
MU_GOALS = float(os.environ.get("MU_GOALS", "1.35"))
# Tkurrja drejt mesatares (0=të gjithë mesatarë, 1=pa tkurrje → shpërthen).
STRENGTH_SHRINK = float(os.environ.get("STRENGTH_SHRINK", "0.50"))
# Kufijtë e λ-së për qëndrueshmëri (shmang skore absurde).
LAMBDA_MIN, LAMBDA_MAX = 0.25, 3.30

# Mesataret e ligës, të nxjerra një herë nga tabela (auto-kalibrim).
_LEAGUE_ATTACK  = sum(v[0] for v in TEAM_STATS_BASE.values()) / max(1, len(TEAM_STATS_BASE))
_LEAGUE_DEFENSE = sum(v[1] for v in TEAM_STATS_BASE.values()) / max(1, len(TEAM_STATS_BASE))


def _strength(value: float, league_avg: float) -> float:
    """Forcë relative e tkurrur drejt 1.0: 1 + shrink·(value/avg − 1)."""
    if league_avg <= 0:
        return 1.0
    return 1.0 + STRENGTH_SHRINK * (value / league_avg - 1.0)


def predict(stats_h: dict, stats_a: dict,
            home_name: str = "", away_name: str = "",
            venue_city: str = "", matchday: int = 1,
            group_pts_h: int = 0, group_pts_a: int = 0,
            max_goals: int = 7) -> dict:
    """
    Parashikim me Dixon-Coles + WC 2026 modifiers.
    Prapavijë e plotë: lam gjeometrik → korrektim DC → host/lodhje/rotacion.
    """
    # ── Lambda bazë: modeli shumëzues i kalibruar me forcë të tkurrur ──
    # λ_h = sulm_h × mbrojtje_a × MU.  Forcat tkurren drejt 1.0 që
    # mospërputhjet të mos shpërthejnë (p.sh. λ=5), por favoriti të mbetet favorit.
    att_h = _strength(stats_h["goals_scored_avg"],   _LEAGUE_ATTACK)
    def_h = _strength(stats_h["goals_conceded_avg"], _LEAGUE_DEFENSE)
    att_a = _strength(stats_a["goals_scored_avg"],   _LEAGUE_ATTACK)
    def_a = _strength(stats_a["goals_conceded_avg"], _LEAGUE_DEFENSE)
    lam_h = max(0.1, att_h * def_a * MU_GOALS)
    lam_a = max(0.1, att_a * def_h * MU_GOALS)

    h_key = home_name.strip().lower()
    a_key = away_name.strip().lower()

    # ── Peshim me Elo: zhvendos epërsinë drejt fuqisë relative ──
    # Pesha ulet automatikisht kur ka formë reale (xG/gola nga ndeshjet e fundit),
    # sepse atëherë të dhënat live janë më informuese se renditja Elo.
    played = min(int(stats_h.get("played", 0)), int(stats_a.get("played", 0)))
    elo_w = ELO_WEIGHT_LIVE if played >= MIN_LIVE_MATCHES else ELO_BLEND_WEIGHT

    elo_h = ELO_RATINGS.get(h_key, 1500)
    elo_a = ELO_RATINGS.get(a_key, 1500)
    p_elo  = 1.0 / (1.0 + 10.0 ** (-(elo_h - elo_a) / 400.0))   # P(home) sipas Elo
    p_pois = lam_h / (lam_h + lam_a) if (lam_h + lam_a) > 0 else 0.5
    p_mix  = (1.0 - elo_w) * p_pois + elo_w * p_elo
    total  = lam_h + lam_a
    lam_h  = p_mix * total
    lam_a  = (1.0 - p_mix) * total

    # Clamp për qëndrueshmëri (shmang skore absurde nga vlera ekstreme).
    lam_h = max(LAMBDA_MIN, min(lam_h, LAMBDA_MAX))
    lam_a = max(LAMBDA_MIN, min(lam_a, LAMBDA_MAX))

    # Ndërto profiler për modifierët WC

    home_profile = HOST_PROFILES.get(h_key,
                   TeamProfile(home_name,
                               elo_rating=ELO_RATINGS.get(h_key, 1500),
                               group_points=group_pts_h))
    away_profile = TeamProfile(away_name,
                               elo_rating=ELO_RATINGS.get(a_key, 1500),
                               group_points=group_pts_a)
    home_profile.group_points = group_pts_h

    # Zbato modifierët WC (host, lodhje, rotacion)
    lam_h, lam_a = apply_all_wc_modifiers(
        lam_h, lam_a, home_profile, away_profile, venue_city, matchday
    )

    # Dixon-Coles me ρ = -0.13
    dc = dixon_coles_predict(lam_h, lam_a, rho=-0.13, max_goals=max_goals)

    return {
        "score":  dc["best_score"],
        "prob_h": dc["prob_h"],
        "prob_d": dc["prob_d"],
        "prob_a": dc["prob_a"],
        "lam_h":  round(lam_h, 3),
        "lam_a":  round(lam_a, 3),
    }


# ─── PREZANTIMI ───────────────────────────────────────────────

def print_group_predictions(group_matches: list[dict],
                             team_stats: dict,
                             team_names: dict):
    # Grupo sipas grupit
    groups = defaultdict(list)
    for m in group_matches:
        g = m.get("group") or m.get("stage", "?")
        groups[g].append(m)

    for group_name in sorted(groups.keys()):
        matches = groups[group_name]
        print(f"\n{'='*70}")
        print(f"  🏆  {group_name}")
        print(f"{'='*70}")
        print(f"  {'NDESHJA':<38} {'REZULTAT':>8}  {'H%':>5}  {'B%':>5}  {'A%':>5}  {'STATUS'}")
        print(f"  {'-'*67}")

        for m in sorted(matches, key=lambda x: x["utcDate"]):
            hid   = m["homeTeam"]["id"]
            aid   = m["awayTeam"]["id"]
            hname = m["homeTeam"].get("shortName") or m["homeTeam"]["name"]
            aname = m["awayTeam"].get("shortName") or m["awayTeam"]["name"]
            date  = m["utcDate"][:10]
            status = m["status"]

            if status == "FINISHED":
                hs  = m["score"]["fullTime"]["home"]
                as_ = m["score"]["fullTime"]["away"]
                result_str = f"{hs}-{as_}"
                winner = ""
                if hs > as_:    winner = f"✓ {hname}"
                elif hs < as_:  winner = f"✓ {aname}"
                else:           winner = "Barazim"
                print(f"  {date}  {hname:<15} vs {aname:<15}  {result_str:>6}  "
                      f"{'':>5}  {'':>5}  {'':>5}  {winner}")
            else:
                hfull = m["homeTeam"]["name"]
                afull = m["awayTeam"]["name"]
                sh = resolve_match_stats(hfull, afull, True,  team_stats.get(hid))
                sa = resolve_match_stats(afull, hfull, False, team_stats.get(aid))
                p  = predict(sh, sa)
                h_src = sh.get("source", "wc")
                a_src = sa.get("source", "wc")
                if h_src == "fifa_base" or a_src == "fifa_base":
                    data_note = "📋"
                elif h_src == "historik" or a_src == "historik":
                    data_note = "📈"
                else:
                    data_note = "📊"
                print(f"  {date}  {hname:<15} vs {aname:<15}  {p['score']:>6}  "
                      f"{p['prob_h']:>5}  {p['prob_d']:>5}  {p['prob_a']:>5}  {data_note}")


# ─── NDËRTIMI I DATAFRAME PËR VALUE BETS ─────────────────────

def build_model_dataframe(group_matches: list[dict],
                           team_stats: dict) -> object:
    """
    Ndërton DataFrame me probabilitetet e modelit Poisson
    për të gjitha ndeshjet e pa-luajtura — gati për value_bets.run().
    Kolonat: home_team, away_team, prob_home_win, prob_draw, prob_away_win
    """
    try:
        import pandas as pd
    except ImportError:
        print("  ⚠ pandas nuk është instaluar. Ekzekuto: pip install pandas")
        return None

    rows = []
    for m in group_matches:
        if m["status"] == "FINISHED":
            continue
        hid   = m["homeTeam"]["id"]
        aid   = m["awayTeam"]["id"]
        hname = m["homeTeam"]["name"]
        aname = m["awayTeam"]["name"]
        sh = resolve_match_stats(hname, aname, True,  team_stats.get(hid))
        sa = resolve_match_stats(aname, hname, False, team_stats.get(aid))
        # Matchday nga faza (GROUP_STAGE ndeshja 1/2/3)
        matchday = m.get("matchday", 1) or 1
        venue = (m.get("venue") or {}).get("city", "")
        p  = predict(sh, sa,
                     home_name=hname, away_name=aname,
                     venue_city=venue, matchday=matchday)
        rows.append({
            "home_team":      hname,
            "away_team":      aname,
            "prob_home_win":  p["prob_h"],
            "prob_draw":      p["prob_d"],
            "prob_away_win":  p["prob_a"],
            "lam_h":          p["lam_h"],
            "lam_a":          p["lam_a"],
        })

    df = pd.DataFrame(rows)
    return df


# ─── MAIN ─────────────────────────────────────────────────────

def main():
    print("⚽ WC 2026 — PARASHIKIMET E FAZËS SË GRUPEVE")
    print("─" * 50)

    print("\n📡 Duke marrë ndeshjet...")
    group_matches    = get_group_stage_matches()
    finished_matches = get_wc_finished_matches()

    if not group_matches:
        print("✗ Nuk u morën ndeshjet. Kontrollo çelësin API.")
        return

    total     = len(group_matches)
    finished  = sum(1 for m in group_matches if m["status"] == "FINISHED")
    scheduled = total - finished
    print(f"  OK {total} ndeshje: {finished} luajtura, {scheduled} planifikuar")

 