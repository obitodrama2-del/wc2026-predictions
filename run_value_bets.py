"""
⚽ WC 2026 — Value Bet Finder (skripti kryesor)
Bashkon parashikimet Poisson me koeficientet Tipico dhe gjen Value Bets.
"""

import sys
import os

# ── Ngarko modelin e parashikimit ──────────────────────────────
from wc2026_group_predictions import (
    get_group_stage_matches,
    get_wc_finished_matches,
    build_team_stats,
    build_model_dataframe,
    load_cache,
    get_team_recent_matches,
    default_stats,
)

# ── Ngarko modulin e value bets ────────────────────────────────
from value_bets import run as find_value_bets


def get_team_stats_full() -> tuple:
    """Ndërton statistikat e plota (WC + historik nga cache)."""
    print("📡 Duke marrë ndeshjet WC...")
    group_matches    = get_group_stage_matches()
    finished_matches = get_wc_finished_matches()

    if not group_matches:
        print("✗ Nuk u morën ndeshjet. Kontrollo API_KEY në wc2026_group_predictions.py")
        sys.exit(1)

    finished  = sum(1 for m in group_matches if m["status"] == "FINISHED")
    scheduled = len(group_matches) - finished
    print(f"  ✓ {len(group_matches)} ndeshje: {finished} luajtur, {scheduled} planifikuar")

    team_stats = build_team_stats(finished_matches)
    team_names = {}
    for m in group_matches:
        for side in ("homeTeam", "awayTeam"):
            tid = m[side]["id"]
            team_names[tid] = m[side]["name"]

    # Plotëso nga cache për skuadrat pa të dhëna WC
    missing = [tid for tid in team_names
               if tid not in team_stats or team_stats[tid]["played"] == 0]
    if missing:
        cache = load_cache()
        cached = sum(1 for tid in missing if f"team_{tid}_matches" in cache)
        print(f"  💾 {cached}/{len(missing)} skuadra nga cache lokale")
        for tid in missing:
            try:
                recent = get_team_recent_matches(tid, cache, limit=10)
            except Exception:
                recent = []
            if recent:
                finished_r = [m for m in recent
                              if m["score"]["fullTime"]["home"] is not None]
                if finished_r:
                    from wc2026_group_predictions import build_team_stats as bts
                    extra = bts(finished_r)
                    if tid in extra:
                        team_stats[tid] = extra[tid]
                        team_stats[tid]["source"] = "historik"

    with_data = sum(1 for tid in team_names
                    if tid in team_stats and team_stats[tid]["played"] > 0)
    print(f"  ✓ Statistika: {with_data}/{len(team_names)} skuadra")

    return group_matches, team_stats


def main():
    print("=" * 60)
    print("  ⚽  WC 2026 — VALUE BET FINDER")
    print("=" * 60)

    # 1. Parashikimet e modelit
    group_matches, team_stats = get_team_stats_full()

    print("\n🔧 Duke ndërtuar DataFrame të modelit Poisson...")
    df_model = build_model_dataframe(group_matches, team_stats)
    if df_model is None or df_model.empty:
        print("✗ Nuk u ndërtua DataFrame. Kontrollo të dhënat.")
        sys.exit(1)
    print(f"  ✓ {len(df_model)} ndeshje me probabilitete Poisson")

    # 2. Koeficientet + Value Bets
    print()
    df_value = find_value_bets(df_model)

    # 3. Ruaj CSV
    if df_value is not None and not df_value.empty:
        out_file = os.path.join(os.path.dirname(__file__), "value_bets_output.csv")
        df_value.to_csv(out_file, index=False)
        print(f"\n  💾 Ruajtur: value_bets_output.csv")

        # Shfaq vetëm value bets
        vb = df_value[df_value["value_bet"] == "✅ YES"]
        print(f"\n  📊 Përmbledhje: {len(vb)} Value Bet(s) nga {len(df_value)} ndeshje")


if __name__ == "__main__":
    main()
