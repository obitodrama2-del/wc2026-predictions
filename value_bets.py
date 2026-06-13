"""
⚽ Value Bet Finder — WC 2026
Tërheq koeficientet nga Bet365 (The Odds API) dhe i krahason
me probabilitetet e modelit Poisson për të gjetur Value Bets.
"""

import requests
import pandas as pd
import difflib
from datetime import datetime, timezone

# ─── KONFIGURIMI ──────────────────────────────────────────────
from config import ODDS_API_KEY  # type: ignore   # https://the-odds-api.com
SPORT_KEY     = "soccer_fifa_world_cup"
BOOKMAKER     = "tipico_de"   # Tipico
ODDS_FORMAT   = "decimal"
REGIONS       = "eu"
MARKET        = "h2h"

# ─── FJALORI I EMRAVE ─────────────────────────────────────────
# Model → The Odds API  (shto çdo ndryshim emri që gjen)
NAME_MAP: dict[str, str] = {
    "korea republic":     "south korea",
    "republic of korea":  "south korea",
    "usa":                "united states",
    "united states":      "united states",
    "ir iran":            "iran",
    "côte d'ivoire":      "ivory coast",
    "cote d'ivoire":      "ivory coast",
    "congo dr":           "dr congo",
    "democratic republic of congo": "dr congo",
    "bosnia-herzegovina": "bosnia & herzegovina",
    "bosnia-h.":          "bosnia & herzegovina",
    "czechia":            "czech republic",
    "cape verde":         "cape verde islands",
}


# ══════════════════════════════════════════════════════════════
# 1. TËRHEQJA E KOEFICIENTEVE NGA THE ODDS API
# ══════════════════════════════════════════════════════════════

def _api_request(params: dict) -> requests.Response:
    """Dërgon kërkesë dhe trajton gabimet e zakonshme."""
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/odds"
    try:
        r = requests.get(url, params=params, timeout=15)
    except requests.exceptions.ConnectionError:
        raise RuntimeError("❌ Nuk ka lidhje interneti.")
    except requests.exceptions.Timeout:
        raise RuntimeError("❌ Kërkesa doli jashtë kohe (timeout).")
    if r.status_code == 401:
        raise RuntimeError("❌ Çelës API i pavlefshëm (401).")
    if r.status_code == 429:
        raise RuntimeError("❌ Kreditet e API-së mbaruan (429).")
    if r.status_code != 200:
        raise RuntimeError(f"❌ Gabim API: {r.status_code} — {r.text[:300]}")
    return r


def detect_available_bookmakers() -> list[str]:
    """Kontrollo cilët bookmaker kanë koeficiente për WC 2026 (të gjitha rajonet)."""
    found = set()
    for region in ["eu", "uk", "us", "au"]:
        try:
            r = _api_request({
                "apiKey": ODDS_API_KEY, "regions": region,
                "markets": MARKET, "oddsFormat": ODDS_FORMAT,
            })
            for match in r.json():
                for bm in match.get("bookmakers", []):
                    found.add(bm["key"])
            if found:
                break   # mjafton rajoni i parë me të dhëna
        except RuntimeError:
            pass
    return sorted(found)


def fetch_bet365_odds() -> list[dict]:
    """
    Tërheq koeficientet për WC 2026.
    Provon Bet365 në të gjitha rajonet; nëse nuk gjen, tregon alternativat.
    """
    base_params = {
        "apiKey":     ODDS_API_KEY,
        "markets":    MARKET,
        "oddsFormat": ODDS_FORMAT,
        "bookmakers": BOOKMAKER,
    }

    # Provo variantet e Bet365 dhe të gjitha rajonet
    bet365_keys = [BOOKMAKER]
    for region in ["eu", "uk", "us", "au"]:
        r = _api_request({**base_params, "regions": region})
        remaining = r.headers.get("x-requests-remaining", "?")
        used      = r.headers.get("x-requests-used", "?")
        data = r.json()

        # Gjej çfarë Bet365 variantesh janë aktive
        active_bm_keys = {
            bm["key"]
            for match in data
            for bm in match.get("bookmakers", [])
        }
        matched = [k for k in bet365_keys if k in active_bm_keys]
        if matched:
            active_key = matched[0]
            print(f"  ✓ Bookmaker gjetur: '{active_key}' në rajonin '{region}'")
            print(f"  ✓ API: {len(data)} ndeshje  |  Kredite: {used} përdorur, {remaining} mbetur")
            # Filtro vetëm atë bookmaker
            for match in data:
                match["bookmakers"] = [b for b in match.get("bookmakers", [])
                                       if b["key"] == active_key]
            return [m for m in data if m["bookmakers"]]

    # Bet365 nuk ka koeficiente — gjej alternativat
    print("  ⚠ Bet365 nuk ka koeficiente aktive për WC 2026 ende.")
    print("  🔍 Duke kontrolluar bookmaker-ët e disponibëlt...")
    available = detect_available_bookmakers()
    if available:
        print(f"\n  📋 Bookmaker-ët me koeficiente aktive:")
        for bm in available:
            print(f"     • {bm}")
        print(f"\n  💡 Ndrysho  BOOKMAKER = \"{available[0]}\"  në krye të skedarit")
        print(f"     ose prit derisa Bet365 të hapë linjat për WC 2026.\n")
    else:
        print("  ❌ Asnjë bookmaker nuk ka koeficiente WC 2026 ende.")
    return []


# ══════════════════════════════════════════════════════════════
# 2. STRUKTURIMI NË DATAFRAME
# ══════════════════════════════════════════════════════════════

def odds_to_dataframe(raw_matches: list[dict]) -> pd.DataFrame:
    """
    Ekstrakton nga JSON-i i The Odds API:
    home_team, away_team, commence_time, odd_1, odd_x, odd_2
    """
    rows = []
    for match in raw_matches:
        home = match.get("home_team", "")
        away = match.get("away_team", "")
        dt_str = match.get("commence_time", "")
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            date_local = dt.astimezone().strftime("%Y-%m-%d %H:%M")
        except Exception:
            date_local = dt_str

        # Gjej bookmaker-in Bet365
        odd_1 = odd_x = odd_2 = None
        for bm in match.get("bookmakers", []):
            if bm["key"] != BOOKMAKER:
                continue
            for market in bm.get("markets", []):
                if market["key"] != "h2h":
                    continue
                outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                # h2h: home win, draw, away win
                odd_1 = outcomes.get(home)
                odd_2 = outcomes.get(away)
                # Barazimi quhet "Draw" në Odds API
                odd_x = outcomes.get("Draw")
                break
            break

        if odd_1 and odd_x and odd_2:
            rows.append({
                "home_team":   home,
                "away_team":   away,
                "match_date":  date_local,
                "odd_1":       odd_1,
                "odd_x":       odd_x,
                "odd_2":       odd_2,
            })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("match_date").reset_index(drop=True)
    return df


# ══════════════════════════════════════════════════════════════
# 3. PËRPUTHJA E EMRAVE
# ══════════════════════════════════════════════════════════════

def normalize(name: str) -> str:
    """Normalizon emrin: lowercase + trim + fjalori mapimi."""
    n = name.strip().lower()
    return NAME_MAP.get(n, n)


def fuzzy_match(name: str, candidates: list[str], cutoff: float = 0.72) -> str | None:
    """Gjen emrin më të ngjashëm me difflib nëse mapimi i drejtpërdrejtë dështon."""
    norm = normalize(name)
    norm_candidates = {normalize(c): c for c in candidates}

    # Provë e drejtpërdrejtë
    if norm in norm_candidates:
        return norm_candidates[norm]

    # Fuzzy search
    matches = difflib.get_close_matches(norm, norm_candidates.keys(),
                                         n=1, cutoff=cutoff)
    if matches:
        return norm_candidates[matches[0]]
    return None


def merge_with_model(df_odds: pd.DataFrame,
                     df_model: pd.DataFrame) -> pd.DataFrame:
    """
    Bashkon df_odds (koeficientet) me df_model (probabilitetet e modelit).

    df_model duhet të ketë kolonat:
        home_team, away_team, prob_home_win, prob_draw, prob_away_win

    Kthehet DataFrame i bashkuar me kolonat Value Bet.
    """
    if df_odds.empty or df_model.empty:
        return pd.DataFrame()

    # Normalizim për bashkim
    df_odds  = df_odds.copy()
    df_model = df_model.copy()

    df_odds["_home_norm"]  = df_odds["home_team"].apply(normalize)
    df_odds["_away_norm"]  = df_odds["away_team"].apply(normalize)
    df_model["_home_norm"] = df_model["home_team"].apply(normalize)
    df_model["_away_norm"] = df_model["away_team"].apply(normalize)

    # Merge i drejtpërdrejtë
    merged = pd.merge(df_odds, df_model,
                      on=["_home_norm", "_away_norm"],
                      how="inner",
                      suffixes=("_odds", "_model"))

    # Fuzzy fallback për ndeshjet pa përputhjeje
    matched_pairs = set(zip(merged["_home_norm"], merged["_away_norm"]))
    unmatched = df_odds[
        ~df_odds.apply(lambda r: (r["_home_norm"], r["_away_norm"]) in matched_pairs, axis=1)
    ]

    if not unmatched.empty:
        model_homes = df_model["_home_norm"].tolist()
        model_aways = df_model["_away_norm"].tolist()
        extra_rows = []
        for _, row in unmatched.iterrows():
            fh = fuzzy_match(row["home_team"], df_model["home_team"].tolist())
            fa = fuzzy_match(row["away_team"], df_model["away_team"].tolist())
            if fh and fa:
                model_row = df_model[
                    (df_model["home_team"] == fh) &
                    (df_model["away_team"] == fa)
                ]
                if not model_row.empty:
                    combined = {**row.to_dict(), **model_row.iloc[0].to_dict()}
                    extra_rows.append(combined)
        if extra_rows:
            merged = pd.concat([merged, pd.DataFrame(extra_rows)], ignore_index=True)

    # Pastro kolonat ndihmëse
    merged.drop(columns=[c for c in merged.columns if c.startswith("_")],
                inplace=True, errors="ignore")
    return merged


# ══════════════════════════════════════════════════════════════
# 4. LLOGARITJA E VALUE BET
# ══════════════════════════════════════════════════════════════

def calculate_value(df: pd.DataFrame) -> pd.DataFrame:
    """
    Shton kolonat:
      ev_1  = prob_home_win * odd_1 - 1
      ev_x  = prob_draw    * odd_x  - 1
      ev_2  = prob_away_win * odd_2  - 1
      value_bet = "✅ YES" nëse ndonjë EV > 0, tjetër "❌ NO"
      best_bet  = cila opsion ka EV-në më të lartë
    """
    df = df.copy()

    # Probabilitetet nga modeli (janë në %, kthejini në [0,1])
    def to_prob(col):
        vals = df[col]
        if vals.max() > 1.5:   # janë në % (0-100)
            return vals / 100
        return vals

    p1 = to_prob("prob_home_win")
    px = to_prob("prob_draw")
    p2 = to_prob("prob_away_win")

    df["ev_1"] = (p1 * df["odd_1"] - 1).round(4)
    df["ev_x"] = (px * df["odd_x"] - 1).round(4)
    df["ev_2"] = (p2 * df["odd_2"] - 1).round(4)

    df["value_bet"] = df.apply(
        lambda r: "✅ YES" if max(r["ev_1"], r["ev_x"], r["ev_2"]) > 0 else "❌ NO",
        axis=1
    )

    def best_pick(r):
        opts = {"1 (Home)": r["ev_1"], "X (Draw)": r["ev_x"], "2 (Away)": r["ev_2"]}
        best_k = max(opts, key=opts.get)
        best_v = opts[best_k]
        if best_v > 0:
            return f"{best_k}  EV={best_v:+.2%}"
        return f"{best_k}  EV={best_v:+.2%} (jo vlerë)"

    df["best_bet"] = df.apply(best_pick, axis=1)
    return df


# ══════════════════════════════════════════════════════════════
# 5. PRINTIMI I REZULTATEVE
# ══════════════════════════════════════════════════════════════

def print_value_bets(df: pd.DataFrame):
    value_only = df[df["value_bet"] == "✅ YES"]
    print(f"\n{'='*70}")
    print(f"  💰  VALUE BETS — WC 2026  ({len(value_only)} nga {len(df)} ndeshje)")
    print(f"{'='*70}")

    if value_only.empty:
        print("  Nuk u gjetën Value Bets me modelin aktual.")
        return

    for _, r in value_only.iterrows():
        print(f"\n  ⚽ {r.get('home_team_odds', r.get('home_team',''))}  vs  "
              f"{r.get('away_team_odds', r.get('away_team',''))}")
        print(f"     📅 {r.get('match_date','')}")
        print(f"     Koef Bet365:  1={r['odd_1']}  X={r['odd_x']}  2={r['odd_2']}")
        ph = r.get("prob_home_win", 0)
        px = r.get("prob_draw", 0)
        pa = r.get("prob_away_win", 0)
        if ph > 1: ph /= 100; px /= 100; pa /= 100
        print(f"     Prob. model:  1={ph:.1%}  X={px:.1%}  2={pa:.1%}")
        print(f"     EV:           1={r['ev_1']:+.2%}  X={r['ev_x']:+.2%}  2={r['ev_2']:+.2%}")
        print(f"     🎯 {r['best_bet']}")

    print(f"\n{'─'*70}")
    print("  ⚠ Value Bets janë bazuar në modelin Poisson — jo garanci fitoreje.")
    print(f"{'─'*70}\n")


def print_all_odds(df: pd.DataFrame):
    """Printo tabelën e plotë (për debug)."""
    cols = ["home_team", "away_team", "match_date",
            "odd_1", "odd_x", "odd_2",
            "prob_home_win", "prob_draw", "prob_away_win",
            "ev_1", "ev_x", "ev_2", "value_bet", "best_bet"]
    cols_exist = [c for c in cols if c in df.columns]
    print(df[cols_exist].to_string(index=False))


# ══════════════════════════════════════════════════════════════
# MAIN — si ta integrosh me modelin ekzistues
# ══════════════════════════════════════════════════════════════

def run(df_model: pd.DataFrame) -> pd.DataFrame:
    """
    Funksioni kryesor — thirre me DataFrame-in e modelit tënd.

    df_model duhet të ketë kolonat:
        home_team, away_team, prob_home_win, prob_draw, prob_away_win

    Kthehet DataFrame me Value Bets.
    """
    print("📡 Duke tërhequr koeficientet nga Bet365 (The Odds API)...")
    try:
        raw = fetch_bet365_odds()
    except RuntimeError as e:
        print(e)
        return pd.DataFrame()

    print("🔧 Duke strukturuar të dhënat...")
    df_odds = odds_to_dataframe(raw)
    if df_odds.empty:
        print("  ⚠ Nuk u gjetën koeficiente Bet365 për WC 2026.")
        return pd.DataFrame()
    print(f"  ✓ {len(df_odds)} ndeshje me koeficiente Bet365")

    print("🔗 Duke bashkuar me modelin...")
    df_merged = merge_with_model(df_odds, df_model)
    if df_merged.empty:
        print("  ⚠ Asnjë përputhje emrash mes API-së dhe modelit.")
        print("  💡 Shto emrat e mungueshëm te NAME_MAP në krye të skedarit.")
        return pd.DataFrame()
    print(f"  ✓ {len(df_merged)} ndeshje të përputhura")

    print("💰 Duke llogaritur Value Bets...")
    df_final = calculate_value(df_merged)

    print_value_bets(df_final)
    return df_final


# ── Shembull: si ta thirrësh nga wc2026_group_predictions.py ──
#
# from value_bets import run as find_value_bets
#
# # df_model duhet të ketë: home_team, away_team, prob_home_win, prob_draw, prob_away_win
# df_value = find_value_bets(df_model)
# df_value.to_csv("value_bets_output.csv", index=False)   # ruaj si CSV
#
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # DEMO: testo me të dhëna fikse pa model të vërtetë
    if ODDS_API_KEY == "VENDOS_CELESIN_TEND_KETU":
        print("\n⚠  Merr çelësin API falas nga: https://the-odds-api.com")
        print("   Pastaj zëvendëso ODDS_API_KEY në krye të skedarit.\n")

        # Demo me DataFrame fiktiv
        df_demo_model = pd.DataFrame([
            {"home_team": "Brazil",        "away_team": "Morocco",
             "prob_home_win": 55.0, "prob_draw": 25.0, "prob_away_win": 20.0},
            {"home_team": "France",        "away_team": "Senegal",
             "prob_home_win": 58.0, "prob_draw": 22.0, "prob_away_win": 20.0},
            {"home_team": "Argentina",     "away_team": "Algeria",
             "prob_home_win": 60.0, "prob_draw": 22.0, "prob_away_win": 18.0},
            {"home_team": "Germany",       "away_team": "Ivory Coast",
             "prob_home_win": 52.0, "prob_draw": 26.0, "prob_away_win": 22.0},
        ])

        df_demo_odds = pd.DataFrame([
            {"home_team": "Brazil",    "away_team": "Morocco",
             "match_date": "2026-06-13 17:00", "odd_1": 1.70, "odd_x": 3.60, "odd_2": 5.00},
            {"home_team": "France",    "away_team": "Senegal",
             "match_date": "2026-06-16 20:00", "odd_1": 1.65, "odd_x": 3.80, "odd_2": 5.50},
            {"home_team": "Argentina", "away_team": "Algeria",
             "match_date": "2026-06-17 23:00", "odd_1": 1.55, "odd_x": 4.00, "odd_2": 6.50},
            {"home_team": "Germany",   "away_team": "Ivory Coast",
             "match_date": "2026-06-14 23:00", "odd_1": 1.80, "odd_x": 3.50, "odd_2": 4.80},
        ])

        print("── DEMO MODE (koeficiente & probabilitete fikse) ─────────────\n")
        df_merged = merge_with_model(df_demo_odds, df_demo_model)
        df_final  = calculate_value(df_merged)
        print_value_bets(df_final)
        print_all_odds(df_final)
    else:
        # Çelësi është vendosur — thirr API-në dhe shfaq koeficientet + value bets
        print("📡 Duke tërhequr koeficientet nga Bet365 (The Odds API)...")
        try:
            raw = fetch_bet365_odds()
        except RuntimeError as e:
            print(e)
            exit(1)

        df_odds = odds_to_dataframe(raw)
        if df_odds.empty:
            print("  ⚠ Nuk u gjetën koeficiente Bet365 për WC 2026.")
            print("  💡 Verifikoni sport key: soccer_fifa_world_cup")
            exit(0)

        print(f"\n{'='*65}")
        print(f"  📋  KOEFICIENTET BET365 — WC 2026  ({len(df_odds)} ndeshje)")
        print(f"{'='*65}")
        print(df_odds.to_string(index=False))

        print("\n💡 Për Value Bets, importo dhe thirr run(df_model) me DataFrame-in e modelit.")
        print("   Shembull:  from value_bets import run; df_value = run(df_model)")