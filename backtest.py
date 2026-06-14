"""
╔══════════════════════════════════════════════════════════════════════╗
║   BACK-TEST — mat saktësinë e modelit kundër rezultateve reale        ║
╚══════════════════════════════════════════════════════════════════════╝

PSE: pa një mënyrë objektive matjeje, çdo "përmirësim" është hamendje.
Ky modul ekzekuton modelin mbi ndeshje TË MBARUARA dhe llogarit:

  • Accuracy      — sa shpesh rezultati më i mundshëm (1/X/2) doli i saktë.
  • Brier score   — gabimi mesatar kuadratik i probabiliteteve (0=perfekt, ~0.66=rastësi).
  • Log-loss      — penalizon fort sigurinë e gabuar (më i ulët = më mirë).
  • Avg P(real)   — probabiliteti mesatar që modeli i dha rezultatit që ndodhi vërtet.

Krahasohet gjithmonë me një BAZË naive (1/3, 1/3, 1/3): nëse modeli s'e mund dot
këtë bazë, ai nuk po shton vlerë.

PËRDORIMI:
    # mbi rezultatet shembull të integruara:
    python backtest.py

    # mbi skedarin tënd CSV (home,away,home_goals,away_goals):
    python backtest.py rezultatet.csv

KUFIZIM: përdor statistikat AKTUALE të ekipeve (jo "si ishin atë ditë"). Pra është
një test kalibrimi/sanity, jo një back-test i pastër kohor. Për back-test të vërtetë
historik, jepi modelit statistika të ngrira para datës së çdo ndeshjeje.
"""

from __future__ import annotations

import csv
import math
import sys
from typing import Optional

from wc2026_group_predictions import predict, default_stats, TEAM_STATS_BASE   # type: ignore

# Ekipe që s'u gjetën në TEAM_STATS_BASE (bien te vlerat default 1.2/1.2).
MISSING_TEAMS: set[str] = set()


def _check_known(*names: str) -> None:
    for nm in names:
        if nm.strip().lower() not in TEAM_STATS_BASE:
            MISSING_TEAMS.add(nm)


# ── Rezultate shembull (ilustrative — zëvendësoji me të tuat) ──
# Format: (vendës, mysafir, gola_vendës, gola_mysafir)
SAMPLE_RESULTS: list[tuple[str, str, int, int]] = [
    ("Argentina", "Haiti",      4, 0),
    ("Spain",     "Morocco",    2, 0),
    ("Brazil",    "Switzerland",1, 0),
    ("France",    "Australia",  3, 1),
    ("England",   "Senegal",    3, 0),
    ("Mexico",    "Canada",     1, 1),
    ("Portugal",  "Uruguay",    2, 1),
    ("Germany",   "Japan",      1, 2),
    ("Netherlands","Ecuador",   1, 1),
    ("Croatia",   "Morocco",    0, 0),
    ("USA",       "Iran",       1, 0),
    ("Belgium",   "Canada",     1, 0),
    ("Japan",     "Spain",      2, 1),
    ("Morocco",   "Portugal",   1, 0),
    ("Argentina", "Mexico",     2, 0),
]


# ══════════════════════════════════════════════════════════════
# NDIHMËS
# ══════════════════════════════════════════════════════════════

def model_probs(home: str, away: str) -> tuple[float, float, float]:
    """Kthen (p1, pX, p2) si fraksione [0,1] nga modeli aktual."""
    _check_known(home, away)
    sh = default_stats(home)
    sa = default_stats(away)
    p = predict(sh, sa, home_name=home, away_name=away)
    return p["prob_h"] / 100.0, p["prob_d"] / 100.0, p["prob_a"] / 100.0


def actual_outcome(hg: int, ag: int) -> str:
    """'1' (vendës), 'X' (barazim) ose '2' (mysafir)."""
    if hg > ag:
        return "1"
    if ag > hg:
        return "2"
    return "X"


def _onehot(outcome: str) -> tuple[int, int, int]:
    return (int(outcome == "1"), int(outcome == "X"), int(outcome == "2"))


# ══════════════════════════════════════════════════════════════
# METRIKAT
# ══════════════════════════════════════════════════════════════

def evaluate(matches: list[tuple[str, str, int, int]]) -> dict:
    """
    Ekzekuton modelin mbi ndeshjet dhe kthen metrikat, krahasuar me bazën naive.
    """
    n = 0
    hits = 0
    brier_sum = 0.0
    logloss_sum = 0.0
    p_actual_sum = 0.0

    # Bazë naive: probabilitete uniforme.
    base_p = (1 / 3, 1 / 3, 1 / 3)
    base_brier = 0.0
    base_logloss = 0.0

    eps = 1e-12
    detail = []

    for home, away, hg, ag in matches:
        probs = model_probs(home, away)
        outcome = actual_outcome(hg, ag)
        y = _onehot(outcome)

        # Accuracy: a parashikoi modeli rezultatin më të mundshëm saktë?
        pred_idx = max(range(3), key=lambda i: probs[i])
        actual_idx = y.index(1)
        hit = (pred_idx == actual_idx)
        hits += int(hit)

        # Brier multiklas: Σ (p_k − y_k)^2
        brier = sum((probs[k] - y[k]) ** 2 for k in range(3))
        brier_sum += brier
        base_brier += sum((base_p[k] - y[k]) ** 2 for k in range(3))

        # Log-loss: −log(p i rezultatit real)
        p_real = max(probs[actual_idx], eps)
        logloss_sum += -math.log(p_real)
        base_logloss += -math.log(max(base_p[actual_idx], eps))
        p_actual_sum += probs[actual_idx]

        n += 1
        detail.append({
            "match": f"{home} {hg}-{ag} {away}",
            "p": tuple(round(x * 100, 1) for x in probs),
            "actual": outcome,
            "hit": hit,
        })

    if n == 0:
        return {"n": 0}

    return {
        "n": n,
        "accuracy":      hits / n,
        "brier":         brier_sum / n,
        "logloss":       logloss_sum / n,
        "avg_p_actual":  p_actual_sum / n,
        "base_brier":    base_brier / n,
        "base_logloss":  base_logloss / n,
        "detail":        detail,
    }


def load_csv(path: str) -> list[tuple[str, str, int, int]]:
    """
    Lexon CSV me kolona: home, away, home_goals, away_goals.
    Emrat e kolonave janë fleksibël (home_team/homeTeam etj.).
    """
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r = {k.lower().strip(): v for k, v in row.items()}
            home = r.get("home") or r.get("home_team") or r.get("hometeam")
            away = r.get("away") or r.get("away_team") or r.get("awayteam")
            hg = r.get("home_goals") or r.get("hg") or r.get("home_score")
            ag = r.get("away_goals") or r.get("ag") or r.get("away_score")
            if home and away and hg not in (None, "") and ag not in (None, ""):
                out.append((home, away, int(float(hg)), int(float(ag))))
    return out


# ══════════════════════════════════════════════════════════════
# RAPORTI
# ══════════════════════════════════════════════════════════════

def print_report(res: dict, show_detail: bool = True) -> None:
    if res.get("n", 0) == 0:
        print("Nuk u gjetën ndeshje për back-test.")
        return

    if show_detail:
        print(f"\n  {'Ndeshja':<34} {'1':>6} {'X':>6} {'2':>6}  {'Real':>5} {'OK':>3}")
        print("  " + "─" * 64)
        for d in res["detail"]:
            p1, px, p2 = d["p"]
            print(f"  {d['match']:<34} {p1:>5.1f}% {px:>5.1f}% {p2:>5.1f}%  "
                  f"{d['actual']:>5} {'✓' if d['hit'] else '·':>3}")

    print("\n" + "=" * 50)
    print("  REZULTATI I BACK-TEST-it  (n = %d ndeshje)" % res["n"])
    print("=" * 50)
    print(f"  Accuracy (1/X/2 saktë):   {res['accuracy']*100:>6.1f}%")
    print(f"  Brier score:              {res['brier']:>6.3f}   (bazë naive {res['base_brier']:.3f})")
    print(f"  Log-loss:                 {res['logloss']:>6.3f}   (bazë naive {res['base_logloss']:.3f})")
    print(f"  P mesatare te rezultati real: {res['avg_p_actual']*100:>5.1f}%")
    print("-" * 50)
    better_b = res["brier"]   < res["base_brier"]
    better_l = res["logloss"] < res["base_logloss"]
    if better_b and better_l:
        print("  ✓ Modeli e mund bazën naive (po shton vlerë).")
    elif better_b or better_l:
        print("  ~ Modeli e mund pjesërisht bazën naive.")
    else:
        print("  ✗ Modeli NUK e mund bazën naive — duhet rishikim.")
    print("=" * 50)

    if MISSING_TEAMS:
        print(f"\n  ⚠ {len(MISSING_TEAMS)} ekipe s'u gjetën në TEAM_STATS_BASE")
        print("    (përdorën vlera default 1.2/1.2 → parashikim i dobët për to):")
        for nm in sorted(MISSING_TEAMS):
            print(f"      • {nm}")
        print("    Shto këto në TEAM_STATS_BASE për rezultate më të sakta.")


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
        print(f"Duke lexuar rezultatet nga: {path}")
        matches = load_csv(path)
    else:
        print("Duke përdorur rezultatet SHEMBULL (jep një CSV për të tuat).")
        matches = SAMPLE_RESULTS

    res = evaluate(matches)
    print_report(res)


if __name__ == "__main__":
    main()
