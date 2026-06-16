"""
╔══════════════════════════════════════════════════════════════════════╗
║   ELO DINAMIK — përditëson Elo-n pas çdo ndeshjeje (WC 2026)          ║
╚══════════════════════════════════════════════════════════════════════╝

PËRMIRËSIMI #2. Elo-t e ekipeve nuk janë më statike: pas çdo ndeshjeje
fituesi fiton pikë, humbësi humbet, barazimi rregullon të dy — me formulën
standarde Elo.

FORMULA:
    E_vendës = 1 / (1 + 10^((R_mysafir − R_vendës)/400))     # rezultati i pritur
    S        = 1 (fitore), 0.5 (barazim), 0 (humbje)          # rezultati real
    R_ri     = R + K · (S − E)                                # përditësimi
  (opsionale) shumëzues sipas diferencës së golave (stil World Football Elo).

PERSISTENCA NË CI (GitHub Actions ka filesystem efemerale):
    Burimi i së vërtetës është RI-LLOGARITJA: çdo xhirim nis nga fara
    statike (ELO_RATINGS) dhe ri-luan TË GJITHA ndeshjet e mbaruara në rend
    kronologjik → Elo aktuale. Determinist, pa nevojë për commit-back.
    Ruajmë gjithashtu një snapshot JSON për inspektim / përdorim lokal.
"""

from __future__ import annotations

import os
import json
import math
from typing import Optional

from prediction_engine_v2 import ELO_RATINGS   # type: ignore  # fara fillestare

# ── Parametra të konfigurueshëm ───────────────────────────────
ELO_K = float(os.environ.get("ELO_K", "30"))               # K-factor (30 = standard ndërkombëtar)
# Shumëzues sipas diferencës së golave: 0 = i çaktivizuar (Elo klasik),
# >0 → fitoret e mëdha lëvizin Elo-n më shumë (si World Football Elo).
ELO_GD_MULTIPLIER = float(os.environ.get("ELO_GD_MULTIPLIER", "0"))
ELO_JSON_FILE = os.environ.get(
    "ELO_JSON_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "elo_ratings.json"),
)
DEFAULT_ELO = 1500.0


def _key(name: str) -> str:
    return (name or "").strip().lower()


def seed_ratings() -> dict[str, float]:
    """Kthen një kopje të Elo-ve fillestare (fara)."""
    return {k: float(v) for k, v in ELO_RATINGS.items()}


def get_elo(ratings: dict, name: str) -> float:
    """Elo aktual i një ekipi (me fallback te fara dhe te 1500)."""
    k = _key(name)
    if k in ratings:
        return ratings[k]
    return float(ELO_RATINGS.get(k, DEFAULT_ELO))


def expected_score(r_home: float, r_away: float) -> float:
    """Probabiliteti i pritur (Elo) që vendësi të mos humbasë — rezultati i pritur."""
    return 1.0 / (1.0 + 10.0 ** ((r_away - r_home) / 400.0))


def _gd_factor(goal_diff: int) -> float:
    """Shumëzues i butë sipas diferencës së golave (kur ELO_GD_MULTIPLIER > 0)."""
    if ELO_GD_MULTIPLIER <= 0:
        return 1.0
    return 1.0 + ELO_GD_MULTIPLIER * math.log1p(abs(goal_diff))


def update_one(ratings: dict, home: str, away: str,
               home_goals: int, away_goals: int, k: float = ELO_K) -> None:
    """
    Përditëson Elo-n e dy ekipeve pas një ndeshjeje (modifikon `ratings` në vend).
    """
    hk, ak = _key(home), _key(away)
    rh = get_elo(ratings, home)
    ra = get_elo(ratings, away)

    e_home = expected_score(rh, ra)
    if home_goals > away_goals:
        s_home = 1.0
    elif home_goals == away_goals:
        s_home = 0.5
    else:
        s_home = 0.0

    k_eff = k * _gd_factor(home_goals - away_goals)
    delta = k_eff * (s_home - e_home)

    ratings[hk] = rh + delta
    ratings[ak] = ra - delta   # loja me shumë zero: ç'fiton njëri, humb tjetri


def _match_date(m: dict) -> str:
    """Datë për renditje kronologjike (formate të ndryshme API)."""
    return (m.get("utcDate") or m.get("date") or
            (m.get("fixture", {}) or {}).get("date") or "")


def _match_teams_goals(m: dict):
    """Nxjerr (home, away, hg, ag) nga formate të ndryshme; None nëse s'vlen."""
    # Format football-data
    try:
        home = m["homeTeam"]["name"]; away = m["awayTeam"]["name"]
        ft = m.get("score", {}).get("fullTime", {})
        hg, ag = ft.get("home"), ft.get("away")
        if hg is not None and ag is not None:
            return home, away, int(hg), int(ag)
    except (KeyError, TypeError):
        pass
    # Format API-Sports
    try:
        home = m["teams"]["home"]["name"]; away = m["teams"]["away"]["name"]
        g = m.get("goals", {})
        hg, ag = g.get("home"), g.get("away")
        if hg is not None and ag is not None:
            return home, away, int(hg), int(ag)
    except (KeyError, TypeError):
        pass
    return None


def compute_current(finished_matches: list[dict], k: float = ELO_K) -> dict[str, float]:
    """
    Burimi i së vërtetës: nis nga fara dhe ri-luan të gjitha ndeshjet e mbaruara
    në rend kronologjik. Kthen Elo-t aktuale. Deterministe — pa varësi nga disku.
    """
    ratings = seed_ratings()
    rows = []
    for m in finished_matches or []:
        tg = _match_teams_goals(m)
        if tg:
            rows.append((_match_date(m), tg))
    rows.sort(key=lambda r: r[0])   # kronologjik
    for _, (home, away, hg, ag) in rows:
        update_one(ratings, home, away, hg, ag, k)
    return ratings


def save_json(ratings: dict, path: str = ELO_JSON_FILE) -> None:
    """Ruaj një snapshot JSON (për inspektim / përdorim lokal)."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({k: round(v, 2) for k, v in sorted(ratings.items())},
                      f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_json(path: str = ELO_JSON_FILE) -> Optional[dict]:
    """Lexo snapshot-in JSON nëse ekziston (përndryshe None)."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return {k: float(v) for k, v in json.load(f).items()}
    except (OSError, json.JSONDecodeError, ValueError):
        return None


if __name__ == "__main__":
    # Demo: ri-luaj disa ndeshje dhe shfaq ndryshimet.
    demo = [
        {"utcDate": "2026-06-12", "homeTeam": {"name": "Argentina"},
         "awayTeam": {"name": "Saudi Arabia"}, "score": {"fullTime": {"home": 1, "away": 2}}},
        {"utcDate": "2026-06-13", "homeTeam": {"name": "Brazil"},
         "awayTeam": {"name": "Haiti"}, "score": {"fullTime": {"home": 4, "away": 0}}},
    ]
    r = compute_current(demo)
    print(f"K={ELO_K}  GD_mult={ELO_GD_MULTIPLIER}")
    for t in ("argentina", "saudi arabia", "brazil", "haiti"):
        print(f"  {t:<14} {ELO_RATINGS.get(t, 1500):>6.0f} → {r.get(t, 1500):>7.1f}")
