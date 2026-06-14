"""
📲 Telegram Notifier — WC 2026
Dërgon parashikimet e ndeshjeve në Telegram.
"""

import requests

# ─── KONFIGURIMI ──────────────────────────────────────────────
from config import TELEGRAM_BOT_TOKEN as BOT_TOKEN, TELEGRAM_CHAT_ID as CHAT_ID  # type: ignore
TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ─── NORMALIZIM PROBABILITETI (mbrojtje nga shkalla e gabuar) ──
def prob_frac(p) -> float:
    """
    Kthen ÇDO probabilitet në fraksion [0,1], pavarësisht shkallës hyrëse.
        0.7569  → 0.7569   (fraksion)
        75.69   → 0.7569   (përqindje)
        7569    → 0.7569   (përqindje e shumëzuar gabimisht me 100)
    Kjo e bën të pamundur shfaqjen e ">100%" edhe nëse një burim e fryn vlerën.
    """
    p = float(p or 0.0)
    if p < 0:
        return 0.0
    while p > 1.0:
        p /= 100.0
    return min(p, 1.0)


def prob_pct(p) -> float:
    """Probabilitet i normalizuar si përqindje 0–100."""
    return prob_frac(p) * 100.0


# ─── DËRGIMI I MESAZHIT ───────────────────────────────────────

def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Dërgon mesazh në Telegram. Kthen True nëse sukses."""
    if BOT_TOKEN.startswith("VENDOS"):
        print("  ⚠ Vendos BOT_TOKEN dhe CHAT_ID në telegram_notify.py")
        return False
    try:
        r = requests.post(
            f"{TELEGRAM_URL}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        if r.status_code == 200:
            return True
        print(f"  ⚠ Telegram gabim: {r.status_code} — {r.text[:200]}")
        return False
    except Exception as e:
        print(f"  ⚠ Telegram exception: {e}")
        return False


def test_connection() -> bool:
    """Teston lidhjen me Telegram bot."""
    try:
        r = requests.get(f"{TELEGRAM_URL}/getMe", timeout=10)
        if r.status_code == 200:
            name = r.json()["result"].get("first_name", "Bot")
            print(f"  ✓ Telegram i lidhur: @{r.json()['result'].get('username','?')} ({name})")
            return True
        print(f"  ✗ Telegram: {r.status_code} — Token i gabuar?")
        return False
    except Exception as e:
        print(f"  ✗ Telegram lidhje e dështuar: {e}")
        return False


# ─── FORMATIMI I MESAZHIT ─────────────────────────────────────

def format_prediction_message(match: dict) -> str:
    """
    Ndërton mesazhin e parashikimit për një ndeshje.

    match dict pret:
        date, time, home_team, away_team,
        prob_home_win, prob_draw, prob_away_win,
        odd_1, odd_x, odd_2,
        best_outcome, best_prob, best_odd, ev
    """
    outcome_map = {
        "1": "🏠 Fitore Vendas",
        "X": "🤝 Barazim",
        "2": "✈️ Fitore Mysafir",
    }
    outcome_label = outcome_map.get(match.get("best_outcome", ""), match.get("best_outcome", ""))

    # Emoji sipas EV
    ev = match.get("ev", 0)
    if ev >= 0.15:
        ev_emoji = "🔥🔥"
    elif ev >= 0.08:
        ev_emoji = "🔥"
    elif ev > 0:
        ev_emoji = "✅"
    else:
        ev_emoji = "⚪"

    msg = (
        f"⚽ <b>WC 2026 — PARASHIKIM</b>\n"
        f"{'─' * 28}\n"
        f"📅 <b>{match['date']}</b>  🕐 <b>{match['time']}</b>\n"
        f"🏟 <b>{match['home_team']}</b> vs <b>{match['away_team']}</b>\n"
        f"\n"
        f"📊 <b>Probabilitetet (Poisson):</b>\n"
        f"   1️⃣  {match['home_team']:<20}  <b>{match['prob_home_win']:.1f}%</b>\n"
        f"   🤝  Barazim                   <b>{match['prob_draw']:.1f}%</b>\n"
        f"   2️⃣  {match['away_team']:<20}  <b>{match['prob_away_win']:.1f}%</b>\n"
        f"\n"
        f"💰 <b>Koeficientet Tipico:</b>\n"
        f"   1={match['odd_1']}  X={match['odd_x']}  2={match['odd_2']}\n"
        f"\n"
        f"{ev_emoji} <b>Parashikimi:</b> {outcome_label}\n"
        f"   Probabilitet: <b>{prob_pct(match['best_prob']):.1f}%</b>  |  "
        f"Koeficient: <b>{match['best_odd']}</b>\n"
        f"   Expected Value: <b>{ev:+.1%}</b>\n"
        f"{'─' * 28}\n"
        f"⚠️ <i>Parashikim statistikor — jo garanci fitoreje</i>"
    )
    return msg


def format_summary_header(total: int, value_count: int) -> str:
    """Mesazh hyrës para listës së parashikimeve."""
    return (
        f"🏆 <b>WC 2026 — PARASHIKIMET E GRUPEVE</b>\n"
        f"{'─' * 28}\n"
        f"📋 {total} ndeshje  |  🔥 {value_count} Value Bets\n"
        f"📡 Koeficientet: Tipico  |  Modeli: Poisson\n"
        f"{'─' * 28}"
    )


def format_all_matches_list(matches: list[dict]) -> str:
    """
    TË GJITHA ndeshjet në një mesazh të vetëm.
    Format: Data Ora | Ndeshja → Parashikimi (Koef)
    """
    outcome_map = {"1": "1", "X": "X", "2": "2"}

    lines = [
        "⚽ <b>WC 2026 — PARASHIKIMET</b>",
        "─" * 32,
    ]

    current_date = ""
    for m in matches:
        if m["date"] != current_date:
            current_date = m["date"]
            lines.append(f"\n📅 <b>{current_date}</b>")

        o = outcome_map.get(m.get("best_outcome", ""), "?")
        lines.append(f"{m['time']}  <b>{m['home_team']} vs {m['away_team']}</b>  <b>{o}</b>")

    lines.append("\n─" * 16)
    lines.append("⚠️ <i>Jo garanci fitoreje</i>")
    return "\n".join(lines)


def format_best_combo(matches: list[dict], top_n: int = 5) -> str:
    """
    Kombinimi më i mirë: top N ndeshje sipas raportit koeficient × probabilitet.
    Koeficienti total i kombos llogaritet si prodhim.
    """
    import math

    # Filtro vetëm ato me EV > 0 dhe probabilitet të mjaftueshëm (≥20%)
    candidates = [m for m in matches if m.get("ev", 0) > 0 and prob_frac(m.get("best_prob", 0)) > 0.20]

    if not candidates:
        candidates = sorted(matches, key=lambda x: x.get("ev", -99), reverse=True)[:top_n]

    # Sorto sipas: probabilitet × koeficient (Expected Value absolut)
    candidates.sort(key=lambda x: prob_frac(x.get("best_prob", 0)) * x.get("best_odd", 1), reverse=True)
    top = candidates[:top_n]

    outcome_map = {"1": "1", "X": "X", "2": "2"}
    combo_odd = 1.0
    for m in top:
        combo_odd *= m.get("best_odd", 1)
    # Probabiliteti i kombos = prodhimi i fraksioneve (gjithmonë ≤ 100%)
    combo_prob = math.prod(prob_frac(m.get("best_prob", 0)) for m in top) * 100

    lines = [
        "🎯 <b>KOMBINIMI MË I MIRË — WC 2026</b>",
        "─" * 32,
    ]
    for i, m in enumerate(top, 1):
        o = outcome_map.get(m.get("best_outcome", ""), "?")
        kelly = m.get("kelly_stake", 0)
        kelly_str = f"  Kelly: <b>€{kelly:.2f}</b>/€100" if kelly > 0 else ""
        lines.append(
            f"{i}. <b>{m['home_team']} vs {m['away_team']}</b>  "
            f"({m['date']} {m['time']})\n"
            f"   → <b>{o}</b>  Koef: <b>{m['best_odd']}</b>  "
            f"Prob: <b>{prob_pct(m['best_prob']):.1f}%</b>{kelly_str}"
        )

    lines.append("─" * 16)
    lines.append(
        f"💰 <b>Koeficienti total:</b> <b>{combo_odd:.2f}</b>\n"
        f"📊 <b>Probabiliteti:</b> <b>{combo_prob:.2f}%</b>\n"
        f"⚠️ <i>Jo garanci fitoreje</i>"
    )
    return "\n".join(lines)


def format_value_only_message(matches: list[dict]) -> str:
    """Mesazh i kompaktuar vetëm me Value Bets (EV > 0)."""
    vb = [m for m in matches if m.get("is_value", False) or m.get("ev", 0) > 0]
    if not vb:
        return "⚪ Asnjë Value Bet u gjet me modelin aktual."

    outcome_map = {"1": "1", "X": "X", "2": "2"}
    lines = [f"🔥 <b>VALUE BETS ({len(vb)}) — WC 2026</b>", "─" * 32]

    current_date = ""
    for m in vb:
        if m["date"] != current_date:
            current_date = m["date"]
            lines.append(f"\n📅 <b>{current_date}</b>")
        o = outcome_map.get(m.get("best_outcome", ""), "?")
        ev = m.get("ev", 0)
        emoji = "🔥🔥" if ev >= 0.15 else "🔥" if ev >= 0.08 else "✅"
        lines.append(
            f"{emoji} {m['time']}  <b>{m['home_team']} vs {m['away_team']}</b>  "
            f"→ <b>{o}</b>  Koef: <b>{m['best_odd']}</b>  EV: <b>{ev:+.1%}</b>"
        )

    lines.append("\n─" * 16)
    lines.append("⚠️ <i>Jo garanci fitoreje</i>")
    return "\n".join(lines)
