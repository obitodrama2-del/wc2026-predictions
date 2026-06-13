"""
⚽ Football Match Predictor - World Cup 2026
Merr të dhëna nga football-data.org dhe parashikon rezultatin
duke përdorur formën e 5 ndeshjeve të fundit + algoritmin Poisson
"""

import requests
import math
from itertools import product

# ─── KONFIGURIMI ──────────────────────────────────────────────
API_KEY  = "e84716bdd3524721b8d744d8d921ebad"
BASE_URL = "https://api.football-data.org/v4"
HEADERS  = {"X-Auth-Token": API_KEY}
WC_CODE  = "WC"   # kompeticion - FIFA World Cup


# ─── MARRJA E SKUADRAVE NGA WC ────────────────────────────────

def get_wc_teams() -> dict[str, dict]:
    """
    Kthehet dict:  emri_lowercase -> {id, name}
    p.sh. "brazil" -> {"id": 764, "name": "Brazil"}
    """
    url = f"{BASE_URL}/competitions/{WC_CODE}/teams"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        print(f"  ⚠ Gabim duke marrë skuadrat WC: {r.status_code} {r.text[:200]}")
        return {}

    teams = r.json().get("teams", [])
    result = {}
    for t in teams:
        result[t["name"].lower()] = {"id": t["id"], "name": t["name"]}
        # Shto edhe forma të shkurtra p.sh. "usa" -> "United States"
        if t.get("shortName"):
            result[t["shortName"].lower()] = {"id": t["id"], "name": t["name"]}
        if t.get("tla"):
            result[t["tla"].lower()] = {"id": t["id"], "name": t["name"]}
    return result


def find_team(query: str, wc_teams: dict) -> tuple[int | None, str]:
    """Gjen skuadrën nga query (pjesë e emrit)."""
    q = query.lower().strip()

    # Kërkim i drejtpërdrejtë
    if q in wc_teams:
        t = wc_teams[q]
        return t["id"], t["name"]

    # Kërkim i pjesshëm
    matches = [(name, t) for name, t in wc_teams.items() if q in name]
    if matches:
        # Kthe skuadrën me emrin më të shkurtër (më specifike)
        matches.sort(key=lambda x: len(x[0]))
        t = matches[0][1]
        return t["id"], t["name"]

    return None, f"Skuadra '{query}' nuk u gjet në WC 2026."


# ─── NDESHJET NGA KOMPETICION ─────────────────────────────────

def get_team_wc_matches(team_id: int, team_name: str, n: int = 5) -> list[dict]:
    """
    Merr ndeshjet e përfunduara të skuadrës nga WC 2026.
    Nëse ka < n ndeshje WC, plotëson me ndeshje të tjera ndërkombëtare.
    """
    # 1. Ndeshjet e WC 2026
    url = f"{BASE_URL}/competitions/{WC_CODE}/matches"
    params = {"status": "FINISHED"}
    r = requests.get(url, headers=HEADERS, params=params)

    wc_matches = []
    if r.status_code == 200:
        all_matches = r.json().get("matches", [])
        for m in all_matches:
            if m["homeTeam"]["id"] == team_id or m["awayTeam"]["id"] == team_id:
                wc_matches.append(m)
        wc_matches.sort(key=lambda x: x["utcDate"], reverse=True)

    parsed = _parse_matches(wc_matches[:n], team_id)

    # 2. Nëse ka pak ndeshje WC, shto ndeshje të tjera të skuadrës
    if len(parsed) < n:
        need = n - len(parsed)
        url2 = f"{BASE_URL}/teams/{team_id}/matches"
        params2 = {"status": "FINISHED", "limit": need + 5}
        r2 = requests.get(url2, headers=HEADERS, params=params2)
        if r2.status_code == 200:
            extra = r2.json().get("matches", [])
            extra.sort(key=lambda x: x["utcDate"], reverse=True)
            extra_parsed = _parse_matches(extra, team_id)
            # Shto vetëm ato që nuk janë tashmë
            existing_dates = {p["date"] + p["home"] for p in parsed}
            for ep in extra_parsed:
                key = ep["date"] + ep["home"]
                if key not in existing_dates:
                    parsed.append(ep)
                if len(parsed) >= n:
                    break

    return parsed[:n]


def _parse_matches(matches_raw: list, team_id: int) -> list[dict]:
    """Konverton ndeshjet raw në format standard."""
    result = []
    for m in matches_raw:
        hs = m["score"]["fullTime"]["home"]
        as_ = m["score"]["fullTime"]["away"]
        if hs is None or as_ is None:
            continue
        side = "home" if m["homeTeam"]["id"] == team_id else "away"
        result.append({
            "date":       m["utcDate"][:10],
            "home":       m["homeTeam"]["name"],
            "away":       m["awayTeam"]["name"],
            "home_score": hs,
            "away_score": as_,
            "team_side":  side,
            "competition": m.get("competition", {}).get("name", ""),
        })
    return result


# ─── STATISTIKAT ──────────────────────────────────────────────

def compute_stats(matches: list[dict]) -> dict:
    if not matches:
        return {}

    scored, conceded, points, form = [], [], [], []
    for m in matches:
        if m["team_side"] == "home":
            s, c = m["home_score"], m["away_score"]
        else:
            s, c = m["away_score"], m["home_score"]

        scored.append(s)
        conceded.append(c)

        if s > c:
            points.append(3); form.append("W")
        elif s == c:
            points.append(1); form.append("D")
        else:
            points.append(0); form.append("L")

    return {
        "goals_scored_avg":   round(sum(scored)  / len(scored),  2),
        "goals_conceded_avg": round(sum(conceded) / len(conceded), 2),
        "points_per_game":    round(sum(points)   / len(points),  2),
        "form":               " → ".join(form),
        "matches_count":      len(matches),
    }


# ─── ALGORITMI POISSON ────────────────────────────────────────

def poisson_prob(lam: float, k: int) -> float:
    return (math.exp(-lam) * lam**k) / math.factorial(k)


def predict_match(stats_home: dict, stats_away: dict, max_goals: int = 6) -> dict:
    lam_h = (stats_home["goals_scored_avg"] + stats_away["goals_conceded_avg"]) / 2
    lam_a = (stats_away["goals_scored_avg"] + stats_home["goals_conceded_avg"]) / 2

    p_home_win = p_draw = p_away_win = 0.0
    best_prob  = 0.0
    best_score = (0, 0)

    for g_h, g_a in product(range(max_goals + 1), repeat=2):
        p = poisson_prob(lam_h, g_h) * poisson_prob(lam_a, g_a)
        if g_h > g_a:   p_home_win += p
        elif g_h == g_a: p_draw    += p
        else:            p_away_win += p
        if p > best_prob:
            best_prob  = p
            best_score = (g_h, g_a)

    # Bonus forma
    bonus = (stats_home["points_per_game"] - stats_away["points_per_game"]) * 0.05
    p_home_win = min(max(p_home_win + bonus, 0), 1)
    p_away_win = min(max(p_away_win - bonus, 0), 1)

    total = p_home_win + p_draw + p_away_win
    return {
        "lambda_home":             round(lam_h, 2),
        "lambda_away":             round(lam_a, 2),
        "prob_home_win":           round(p_home_win / total * 100, 1),
        "prob_draw":               round(p_draw     / total * 100, 1),
        "prob_away_win":           round(p_away_win / total * 100, 1),
        "most_likely_score":       f"{best_score[0]} - {best_score[1]}",
        "most_likely_score_prob":  round(best_prob * 100, 1),
    }


# ─── PREZANTIMI ───────────────────────────────────────────────

def print_match_history(team_name: str, matches: list[dict]):
    print(f"\n  📋 Ndeshjet e fundit të {team_name}:")
    for m in matches:
        comp = f"[{m['competition']}]" if m.get("competition") else ""
        print(f"    {m['date']}  {m['home']} {m['home_score']}-{m['away_score']} {m['away']}  {comp}")


def print_prediction(home_name: str, away_name: str,
                     stats_h: dict, stats_a: dict, pred: dict):
    sep = "=" * 58
    print(f"\n{sep}")
    print(f"  ⚽  {home_name}  vs  {away_name}")
    print(sep)

    print(f"\n  FORMA ({stats_h['matches_count']} ndeshje):")
    print(f"    {home_name:<28} {stats_h['form']}")
    print(f"    {away_name:<28} {stats_a['form']}")

    print(f"\n  STATISTIKA MESATARE:")
    print(f"    {'Skuadra':<28} {'Gola shen.':>10}  {'Gola pes.':>9}  {'Pikë/nd.':>8}")
    print(f"    {home_name:<28} {stats_h['goals_scored_avg']:>10}  "
          f"{stats_h['goals_conceded_avg']:>9}  {stats_h['points_per_game']:>8}")
    print(f"    {away_name:<28} {stats_a['goals_scored_avg']:>10}  "
          f"{stats_a['goals_conceded_avg']:>9}  {stats_a['points_per_game']:>8}")

    print(f"\n  PARASHIKIMI (Poisson):")
    print(f"    Gola të pritura: {home_name} ≈ {pred['lambda_home']}  |  "
          f"{away_name} ≈ {pred['lambda_away']}")
    print(f"\n    Rezultati më i mundshëm: {pred['most_likely_score']}  "
          f"({pred['most_likely_score_prob']}%)")
    print(f"\n    Fitore {home_name:<24} {pred['prob_home_win']:>5}%")
    print(f"    Barazim                           {pred['prob_draw']:>5}%")
    print(f"    Fitore {away_name:<24} {pred['prob_away_win']:>5}%")

    max_p = max(pred["prob_home_win"], pred["prob_draw"], pred["prob_away_win"])
    if max_p == pred["prob_home_win"]:
        verdict = f"🏆 Favorit: {home_name}"
    elif max_p == pred["prob_away_win"]:
        verdict = f"🏆 Favorit: {away_name}"
    else:
        verdict = "🤝 Barazim i mundshëm"

    print(f"\n  {verdict}")
    print(sep)


# ─── MAIN ─────────────────────────────────────────────────────

def main():
    print("⚽ BOTI I PARASHIKIMIT - BOTËRORI 2026")
    print("─" * 40)

    print("\n📡 Duke ngarkuar skuadrat e WC 2026...")
    wc_teams = get_wc_teams()
    if not wc_teams:
        print("✗ Nuk u morën skuadrat. Kontrollo çelësin API.")
        return

    print(f"  ✓ {len(set(t['id'] for t in wc_teams.values()))} skuadra të ngarkuara.\n")

    home_input = input("Skuadra HOME: ").strip()
    away_input = input("Skuadra AWAY: ").strip()

    home_id, home_name = find_team(home_input, wc_teams)
    if not home_id:
        print(f"  ✗ {home_name}"); return
    print(f"  ✓ {home_name}")

    away_id, away_name = find_team(away_input, wc_teams)
    if not away_id:
        print(f"  ✗ {away_name}"); return
    print(f"  ✓ {away_name}")

    print(f"\n📡 Duke marrë ndeshjet...")
    home_matches = get_team_wc_matches(home_id, home_name, n=5)
    away_matches = get_team_wc_matches(away_id, away_name, n=5)

    if not home_matches or not away_matches:
        print("  ✗ Nuk ka të dhëna të mjaftueshme."); return

    print_match_history(home_name, home_matches)
    print_match_history(away_name, away_matches)

    stats_h = compute_stats(home_matches)
    stats_a = compute_stats(away_matches)
    pred    = predict_match(stats_h, stats_a)

    print_prediction(home_name, away_name, stats_h, stats_a, pred)


if __name__ == "__main__":
    main()
