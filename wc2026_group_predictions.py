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


def predict(stats_h: dict, stats_a: dict,
            home_name: str = "", away_name: str = "",
            venue_city: str = "", matchday: int = 1,
            group_pts_h: int = 0, group_pts_a: int = 0,
            max_goals: int = 7) -> dict:
    """
    Parashikim me Dixon-Coles + WC 2026 modifiers.
    Prapavijë e plotë: lam gjeometrik → korrektim DC → host/lodhje/rotacion.
    """
    # Lambda gjeometrik bazë
    lam_h = math.sqrt(stats_h["goals_scored_avg"] * stats_a["goals_conceded_avg"])
    lam_a = math.sqrt(stats_a["goals_scored_avg"] * stats_h["goals_conceded_avg"])

    # Ndërto profiler për modifierët WC
    h_key = home_name.strip().lower()
    a_key = away_name.strip().lower()

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
                sh = team_stats.get(hid, default_stats(hfull))
                sa = team_stats.get(aid, default_stats(afull))
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
        sh = team_stats.get(hid, default_stats(hname))
        sa = team_stats.get(aid, default_stats(aname))
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

    print("📡 Duke ndërtuar statistikat...")
    team_stats = build_team_stats(finished_matches)
    team_names = {}
    for m in group_matches:
        for side in ("homeTeam", "awayTeam"):
            tid = m[side]["id"]
            team_names[tid] = m[side].get("shortName") or m[side]["name"]

    teams_with_data = len([t for t in team_names if t in team_stats and team_stats[t]["played"] > 0])
    print(f"  ✓ Statistika WC disponibël për {teams_with_data}/{len(team_names)} skuadra")

    # Plotëso me historikun e ndeshjeve të fundit për skuadrat pa të dhëna WC
    missing = [tid for tid in team_names if tid not in team_stats or team_stats[tid]["played"] == 0]
    if missing:
        cache = load_cache()
    print(f"  📡 Duke marrë historikun për {len(missing)} skuadra pa të dhëna WC...")
    cached_count = sum(1 for tid in missing if f"team_{tid}_matches" in cache)
    if cached_count:
        print(f"  💾 {cached_count} skuadra nga cache lokale (të shpejta)")
    for i, tid in enumerate(missing):
            recent = get_team_recent_matches(tid, cache, limit=10)
            if recent:
                fake_finished = [m for m in recent
                                 if m["score"]["fullTime"]["home"] is not None]
                if fake_finished:
                    extra = build_team_stats(fake_finished)
                    if tid in extra:
                        team_stats[tid] = extra[tid]
                        team_stats[tid]["source"] = "historik"
            if (i + 1) % 8 == 0:
                print(f"    {i+1}/{len(missing)}...")
    save_cache(cache)
    print(f"  💾 Cache u ruajt — herën tjetër do jetë i shpejtë")

    now_with_data = len([t for t in team_names if t in team_stats and team_stats[t]["played"] > 0])
    print(f"  ✓ Statistika totale: {now_with_data}/{len(team_names)} skuadra")

    print("\n  LEGJENDË:  📊 = të dhëna WC  |  📈 = historik i fundit  |  🔮 = pa të dhëna")
    print("             H% = fitore home  B% = barazim  A% = fitore away")

    print_group_predictions(group_matches, team_stats, team_names)

    print(f"\n{'─'*70}")
    print("  ✅ Parashikimet u gjeneruan.")
    print("  ⚠ Parashikimet janë probabilistike, jo të sigurta.")
    print(f"{'─'*70}\n")


if __name__ == "__main__":
    main()
