"""
╔══════════════════════════════════════════════════════════════════════╗
║   FETCH RESULTS — mbledh ndeshje TË MBARUARA nga API-Sports           ║
║   Prodhon një CSV gati për backtest.py                                ║
╚══════════════════════════════════════════════════════════════════════╝

Ripërdor APISportsClient nga dynamic_data.py (header x-apisports-key,
token-bucket rate limiter dhe cache SQLite) — pra respekton kuotën falas.

PËRDORIMI:
    # Sipas lige + sezoni (p.sh. Botërori 2022 = league 1, season 2022):
    python fetch_results.py --league 1 --season 2022

    # Sipas intervali datash (çdo ndeshje e mbaruar mes datave):
    python fetch_results.py --from 2024-06-01 --to 2024-07-31

    # Pa argumente → Botërori 2022 (shembull i sigurt me të dhëna).
    python fetch_results.py

Del: results.csv  →  pastaj:  python backtest.py results.csv

SHËNIM: kërkon APISPORTS_KEY në config.py / mjedis. Pa çelës, skripti
shpjegon si ta marrësh dhe del pa gabim.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

from dynamic_data import APISportsClient   # type: ignore

FINISHED = {"FT", "AET", "PEN"}
OUT_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.csv")


def _parse_fixtures(response: list) -> list[dict]:
    """Kthen përgjigjen e /fixtures në rreshta të pastër (vetëm ndeshje të mbaruara)."""
    rows = []
    for fx in response or []:
        fixture = fx.get("fixture", {})
        if fixture.get("status", {}).get("short") not in FINISHED:
            continue
        teams = fx.get("teams", {})
        goals = fx.get("goals", {})
        home = teams.get("home", {}).get("name")
        away = teams.get("away", {}).get("name")
        hg, ag = goals.get("home"), goals.get("away")
        if not home or not away or hg is None or ag is None:
            continue
        rows.append({
            "date":       (fixture.get("date") or "")[:10],
            "home":       home,
            "away":       away,
            "home_goals": int(hg),
            "away_goals": int(ag),
        })
    return rows


def fetch(client: APISportsClient, params: dict, max_pages: int = 10) -> list[dict]:
    """
    Merr fikstura me paginim. API-Sports kthen fushën `paging` me total faqe.
    Çdo faqe është një kërkesë (e kontrolluar nga rate-limiter-i i klientit).
    """
    all_rows: list[dict] = []
    page = 1
    while page <= max_pages:
        data = client._get("fixtures", {**params, "page": page})
        if not data:
            break
        all_rows.extend(_parse_fixtures(data.get("response", [])))
        paging = data.get("paging", {}) or {}
        total = int(paging.get("total", 1) or 1)
        if page >= total:
            break
        page += 1
    return all_rows


def write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "home", "away", "home_goals", "away_goals"])
        writer.writeheader()
        for r in sorted(rows, key=lambda x: x["date"]):
            writer.writerow(r)


def main():
    ap = argparse.ArgumentParser(description="Mbledh ndeshje të mbaruara nga API-Sports.")
    ap.add_argument("--league", type=int, help="ID e ligës (p.sh. 1 = FIFA World Cup)")
    ap.add_argument("--season", type=int, help="Viti i sezonit (p.sh. 2022)")
    ap.add_argument("--from", dest="date_from", help="Data nga (YYYY-MM-DD)")
    ap.add_argument("--to",   dest="date_to",   help="Data deri (YYYY-MM-DD)")
    ap.add_argument("--out",  default=OUT_DEFAULT, help="Skedari dalës CSV")
    args = ap.parse_args()

    client = APISportsClient()
    if not client.enabled:
        print("✗ Mungon APISPORTS_KEY.")
        print("  Merr një falas: https://dashboard.api-football.com/register")
        print("  Vendose në config.py ose: set APISPORTS_KEY=<çelësi>")
        sys.exit(1)

    # Ndërto parametrat sipas mënyrës.
    if args.date_from and args.date_to:
        params = {"from": args.date_from, "to": args.date_to, "status": "FT-AET-PEN"}
        desc = f"datat {args.date_from} → {args.date_to}"
    else:
        league = args.league or 1       # 1 = FIFA World Cup
        season = args.season or 2022    # Botërori 2022 (default i sigurt)
        params = {"league": league, "season": season}
        desc = f"liga {league}, sezoni {season}"

    print(f"📡 Duke marrë ndeshjet e mbaruara për: {desc} …")
    rows = fetch(client, params)
    if not rows:
        print("  Nuk u gjet asnjë ndeshje e mbaruar (kontrollo league/season ose kuotën).")
        sys.exit(0)

    write_csv(rows, args.out)
    print(f"  ✓ {len(rows)} ndeshje të ruajtura në: {args.out}")
    print(f"\n  Tani ekzekuto:  python backtest.py {os.path.basename(args.out)}")


if __name__ == "__main__":
    main()
