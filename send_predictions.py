"""
⚽ WC 2026 — Dërgo Parashikimet në Telegram
Ekzekuto këtë skript për të marrë menjëherë të gjitha parashikimet në Telegram.
"""

import sys
import os
from datetime import datetime, timezone

# ── Importo modulet tona ───────────────────────────────────────
from wc2026_group_predictions import (
    get_group_stage_matches,
    get_wc_finished_matches,
    build_team_stats,
    build_model_dataframe,
    load_cache,
    get_team_recent_matches,
    default_stats,
    predict,
    TEAM_STATS_BASE,
)
from value_bets import (
    fetch_bet365_odds,
    odds_to_dataframe,
    merge_with_model,
    calculate_value,
)
from telegram_notify import (
    send_message,
    test_connection,
    format_all_matches_list,
    format_best_combo,
    format_value_only_message,
)


# ─── NDËRTIMI I STATS ─────────────────────────────────────────

def build_full_stats() -> tuple:
    print("📡 Duke marrë ndeshjet WC...")
    group_matches    = get_group_stage_matches()
    finished_matches = get_wc_finished_matches()
    if not group_matches:
        print("✗ Nuk u morën ndeshjet.")
        sys.exit(1)

    finished  = sum(1 for m in group_matches if m["status"] == "FINISHED")
    print(f"  ✓ {len(group_matches)} ndeshje: {finished} luajtur, "
          f"{len(group_matches)-finished} planifikuar")

    team_stats = build_team_stats(finished_matches)
    team_names = {}
    for m in group_matches:
        for side in ("homeTeam", "awayTeam"):
            tid = m[side].get("id")
            if tid is None:                 # ekip TBD (eliminatore ende pa u vendosur)
                continue
            team_names[tid] = m[side].get("name")

    # Historiku nga cache (nëse ekziston)
    missing = [tid for tid in team_names
               if tid not in team_stats or team_stats[tid]["played"] == 0]
    if missing:
        cache = load_cache()
        cached = sum(1 for tid in missing if f"team_{tid}_matches" in cache)
        if cached:
            print(f"  💾 {cached} skuadra nga cache")
        for tid in missing:
            try:
                recent = get_team_recent_matches(tid, cache, limit=10)
                if recent:
                    fin = [m for m in recent if m["score"]["fullTime"]["home"] is not None]
                    if fin:
                        extra = build_team_stats(fin)
                        if tid in extra:
                            team_stats[tid] = extra[tid]
                            team_stats[tid]["source"] = "historik"
            except Exception:
                pass

    return group_matches, team_stats, finished_matches


# ─── PËRGATIT TË DHËNAT PËR TELEGRAM ─────────────────────────

def prepare_matches_data(group_matches: list, team_stats: dict,
                          df_final) -> list[dict]:
    """
    Bashkon df_final (value_bets) me oraret nga group_matches.
    Kthen listë me dict të gatshme për formatim Telegram.
    """
    import pandas as pd

    # Map: (home_norm, away_norm) → utcDate
    schedule_map = {}
    for m in group_matches:
        hname = m["homeTeam"].get("name")
        aname = m["awayTeam"].get("name")
        if not hname or not aname:      # anashkalo ndeshjet TBD (ekipe null)
            continue
        schedule_map[(hname.lower(), aname.lower())] = m["utcDate"]

    results = []
    for _, row in df_final.iterrows():
        home = str(row.get("home_team_odds", row.get("home_team", "")))
        away = str(row.get("away_team_odds", row.get("away_team", "")))

        # Gjej kohën
        utc_str = schedule_map.get((home.lower(), away.lower()), "")
        if utc_str:
            try:
                dt_utc = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                dt_local = dt_utc.astimezone()
                date_str = dt_local.strftime("%d/%m/%Y")
                time_str = dt_local.strftime("%H:%M")
            except Exception:
                date_str = row.get("match_date", "")[:10]
                time_str = row.get("match_date", "")[-5:] if len(str(row.get("match_date",""))) > 10 else "?"
        else:
            md = str(row.get("match_date", ""))
            date_str = md[:10]
            time_str = md[11:16] if len(md) > 10 else "?"

        # Probabilitetet (korrigjim nëse janë fraksione)
        ph = float(row.get("prob_home_win", 0))
        px = float(row.get("prob_draw", 0))
        pa = float(row.get("prob_away_win", 0))
        if ph < 1.5:   # janë 0-1, kthejini në %
            ph *= 100; px *= 100; pa *= 100

        # EV i PRANUESHËM (eev_*) — përjashton longshot-et (kuota shumë të larta /
        # prob shumë të vogla). Bie mbrapsht te ev_* nëse kolonat e reja mungojnë.
        ev1 = float(row.get("eev_1", row.get("ev_1", -99)))
        evx = float(row.get("eev_x", row.get("ev_x", -99)))
        ev2 = float(row.get("eev_2", row.get("ev_2", -99)))

        best_ev = max(ev1, evx, ev2)
        prob_map = {"1": (ph, float(row.get("odd_1", 0))),
                    "X": (px, float(row.get("odd_x", 0))),
                    "2": (pa, float(row.get("odd_2", 0)))}
        if best_ev >= 0.04:
            # Ka vlerë të pranueshme → zgjidh atë.
            best_out = "1" if best_ev == ev1 else "X" if best_ev == evx else "2"
        else:
            # Pa vlerë → trego favoritin e modelit (prob më e lartë), jo longshot.
            best_out = max(prob_map, key=lambda k: prob_map[k][0])
        best_prob, best_odd = prob_map[best_out]

        # Kelly stake për outcomen më të mirë
        kelly_map = {"1": float(row.get("kelly_1", 0)),
                     "X": float(row.get("kelly_x", 0)),
                     "2": float(row.get("kelly_2", 0))}
        best_kelly = kelly_map.get(best_out, 0.0)

        results.append({
            "date":           date_str,
            "time":           time_str,
            "home_team":      home,
            "away_team":      away,
            "prob_home_win":  ph,
            "prob_draw":      px,
            "prob_away_win":  pa,
            "odd_1":          float(row.get("odd_1", 0)),
            "odd_x":          float(row.get("odd_x", 0)),
            "odd_2":          float(row.get("odd_2", 0)),
            "best_outcome":   best_out,
            "best_prob":      best_prob,
            "best_odd":       best_odd,
            "ev":             best_ev,
            "kelly_stake":    best_kelly,
            "is_value":       row.get("value_bet", "") == "✅ YES",
        })

    # Sorto sipas datës/orës
    results.sort(key=lambda x: (x["date"], x["time"]))
    return results


# ─── MAIN ─────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  📲  WC 2026 — DËRGO PARASHIKIMET NË TELEGRAM")
    print("=" * 55)

    # 1. Testo lidhjen Telegram
    print("\n🔗 Duke testuar Telegram...")
    if not test_connection():
        print("  ✗ Kontrollo BOT_TOKEN dhe CHAT_ID në telegram_notify.py")
        sys.exit(1)

    # 2. Ndërto modelin
    group_matches, team_stats, finished_matches = build_full_stats()

    # 2b. Elo dinamik — rillogarit nga ndeshjet e mbaruara (determinist) dhe
    #     vendos si override; ruaj snapshot JSON. Pa ndeshje → mbeten Elo-t fara.
    try:
        import elo_store
        from wc2026_group_predictions import set_dynamic_elo
        elo_now = elo_store.compute_current(finished_matches)
        set_dynamic_elo(elo_now)
        elo_store.save_json(elo_now)
        print(f"  ✓ Elo dinamik u rillogarit nga {len(finished_matches)} ndeshje të mbaruara")
    except Exception as e:
        print(f"  ⚠ Elo dinamik u anashkalua ({e}); përdoren Elo-t fara")

    print("\n🔧 Duke ndërtuar DataFrame të modelit...")
    df_model = build_model_dataframe(group_matches, team_stats)
    if df_model is None or df_model.empty:
        # Asnjë ndeshje e planifikuar me ekipe të përcaktuara (p.sh. midis
        # raundeve eliminatore kur çiftet s'janë vendosur ende, ose fund turneu).
        # Dalim PASTËR (exit 0) që GitHub Action të mos shënohet si i dështuar.
        print("ℹ Nuk ka ndeshje të planifikuara për parashikim (TBD ose fund turneu).")
        try:
            send_message("ℹ️ <b>WC 2026</b>\nNuk ka ndeshje të reja për parashikim tani "
                         "(çiftet eliminatore ende s'janë përcaktuar ose turneu përfundoi).")
        except Exception:
            pass
        sys.exit(0)
    print(f"  ✓ {len(df_model)} ndeshje")

    # 3. Merr koeficientet Tipico
    print("\n📡 Duke marrë koeficientet Tipico...")
    try:
        raw = fetch_bet365_odds()
    except RuntimeError as e:
        print(e); sys.exit(1)

    df_odds   = odds_to_dataframe(raw)
    df_merged = merge_with_model(df_odds, df_model)
    df_final  = calculate_value(df_merged)
    print(f"  ✓ {len(df_final)} ndeshje të bashkuara")

    # 4. Përgatit të dhënat
    matches_data = prepare_matches_data(group_matches, team_stats, df_final)
    value_bets   = [m for m in matches_data if m["is_value"]]

    print(f"\n  📊 {len(matches_data)} parashikime  |  🔥 {len(value_bets)} Value Bets")

    # 5. Dërgo në Telegram — 3 mesazhe gjithsej
    print("\n📲 Duke dërguar në Telegram...")

    # Mesazh 1: Lista e plotë e të gjitha ndeshjeve
    all_msg = format_all_matches_list(matches_data)
    # Telegram limit: 4096 karaktere — ndaje nëse duhet
    if len(all_msg) <= 4096:
        ok = send_message(all_msg)
        print(f"  {'✓' if ok else '✗'} Mesazh 1: Lista e plotë ({len(matches_data)} ndeshje)")
    else:
        # Ndaj në dy pjesë
        half = len(matches_data) // 2
        msg1 = format_all_matches_list(matches_data[:half])
        msg2 = format_all_matches_list(matches_data[half:])
        ok1 = send_message(msg1)
        ok2 = send_message(msg2)
        print(f"  {'✓' if ok1 and ok2 else '✗'} Mesazh 1+2: Lista e plotë (2 pjesë)")

    # Mesazh 2: Kombinimi më i mirë (top 5)
    combo_msg = format_best_combo(matches_data, top_n=5)
    ok = send_message(combo_msg)
    print(f"  {'✓' if ok else '✗'} Mesazh 2: Kombinimi më i mirë")

    print(f"\n✅ Gati! Telegram mori parashikimet për {len(matches_data)} ndeshje.")

    # 6. Ruaj CSV
    out_csv = os.path.join(os.path.dirname(__file__), "value_bets_output.csv")
    df_final.to_csv(out_csv, index=False)
    print(f"💾 Ruajtur: value_bets_output.csv")


if __name__ == "__main__":
    main()
