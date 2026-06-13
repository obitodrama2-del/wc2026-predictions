"""
╔══════════════════════════════════════════════════════════════════════╗
║          WC 2026 — PREDICTION ENGINE v2.0                          ║
║          Dixon-Coles + Time Decay + Elo + Kelly Criterion          ║
╚══════════════════════════════════════════════════════════════════════╝

MATHEMATICAL FOUNDATIONS
─────────────────────────
① TIME DECAY
   Standard Poisson uses raw averages — old matches count equally as
   recent ones. We fix this with exponential decay:

       W(t) = e^(−α × t)

   where t = days since match, α = decay rate (typically 0.005–0.02).
   α = 0.005 → a match 365 days ago keeps 16% weight
   α = 0.01  → same match keeps 2.6% weight  (recommended)

   Weighted Lambda:
       λ = Σ(goals_i × W(t_i)) / Σ(W(t_i))

② ELO RATINGS
   Elo difference predicts win probability via logistic function:
       P(win) = 1 / (1 + 10^(−ΔElo / 400))
   We use this to scale the base lambda when live form data is missing.

③ DIXON-COLES MODEL
   Standard Poisson underestimates low-scoring outcomes (0-0, 1-0, 0-1,
   1-1) because goals are not perfectly independent — a team that scores
   early changes their strategy. Dixon-Coles adds a correction factor τ:

       τ(x, y, λ, μ, ρ) applied only when x+y ≤ 1:
           if x=0, y=0: (1 − λμρ)
           if x=1, y=0: (1 + μρ)
           if x=0, y=1: (1 + λρ)
           if x=1, y=1: (1 − ρ)
       ρ ≈ −0.13 (estimated from historical WC data, slightly negative)

   Full probability of exact score (x, y):
       P(x,y) = Poisson(x|λ) × Poisson(y|μ) × τ(x,y,λ,μ,ρ)

④ KELLY CRITERION
   Optimal fraction of bankroll to stake:
       f* = (p × b − q) / b
   where: p = model probability, q = 1−p, b = decimal_odd − 1
   Fractional Kelly (f_k = 0.25) reduces variance significantly.
"""

import math
import datetime
from dataclasses import dataclass, field
from typing import Optional


# ══════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════

@dataclass
class MatchRecord:
    """A single historical match result for time-decay calculation."""
    date: datetime.date        # match date
    goals_scored: float        # goals scored by the team
    goals_conceded: float      # goals conceded by the team
    is_home: bool = True


@dataclass
class TeamProfile:
    """Full profile for a team entering the model."""
    name: str
    elo_rating: float = 1500.0
    match_history: list[MatchRecord] = field(default_factory=list)
    # WC 2026 context
    is_host: bool = False
    host_cities: list[str] = field(default_factory=list)   # e.g. ["Miami", "Houston"]
    group_points: int = 0
    matchday: int = 1
    last_match_city: Optional[str] = None   # for travel fatigue


# ══════════════════════════════════════════════════════════════════════
# MODULE 1 — TIME DECAY + ELO RATINGS
# ══════════════════════════════════════════════════════════════════════

# Current FIFA/WC Elo ratings (approximate, June 2026)
ELO_RATINGS: dict[str, float] = {
    "argentina":     2082,
    "france":        2005,
    "england":       1990,
    "brazil":        1978,
    "spain":         1970,
    "portugal":      1965,
    "netherlands":   1955,
    "germany":       1950,
    "belgium":       1930,
    "colombia":      1895,
    "united states": 1880,
    "mexico":        1875,
    "uruguay":       1870,
    "japan":         1865,
    "morocco":       1860,
    "croatia":       1855,
    "senegal":       1845,
    "switzerland":   1840,
    "norway":        1835,
    "austria":       1830,
    "turkey":        1820,
    "korea republic":1815,
    "ecuador":       1800,
    "canada":        1795,
    "egypt":         1780,
    "ghana":         1765,
    "ivory coast":   1760,
    "iran":          1755,
    "australia":     1750,
    "algeria":       1745,
    "saudi arabia":  1700,
    "south africa":  1690,
    "jordan":        1660,
    "iraq":          1655,
    "panama":        1640,
    "new zealand":   1620,
    "uzbekistan":    1615,
    "dr congo":      1610,
    "cape verde":    1605,
    "qatar":         1580,
    "haiti":         1520,
    "curacao":       1510,
}


def time_decay_weight(match_date: datetime.date,
                      reference_date: Optional[datetime.date] = None,
                      alpha: float = 0.01) -> float:
    """
    Calculates exponential time-decay weight for a historical match.

    W(t) = e^(−α × t)

    Args:
        match_date:      Date of the historical match.
        reference_date:  Date to measure from (defaults to today).
        alpha:           Decay rate. Higher = forget old matches faster.
                         0.005 = slow decay (1yr → 16% weight)
                         0.010 = medium decay (1yr → 2.6% weight) ← recommended
                         0.020 = fast decay  (1yr → 0.07% weight)

    Returns:
        Weight in range (0, 1].
    """
    if reference_date is None:
        reference_date = datetime.date.today()
    t = (reference_date - match_date).days
    return math.exp(-alpha * max(t, 0))


def calculate_time_decayed_lambda(match_history: list[MatchRecord],
                                  alpha: float = 0.01,
                                  reference_date: Optional[datetime.date] = None,
                                  min_matches: int = 3) -> Optional[tuple[float, float]]:
    """
    Calculates time-decayed attack (λ_scored) and defense (λ_conceded)
    from a team's recent match history.

    Returns (lambda_scored, lambda_conceded) or None if insufficient data.
    """
    if not match_history or len(match_history) < min_matches:
        return None

    if reference_date is None:
        reference_date = datetime.date.today()

    total_weight = 0.0
    weighted_scored = 0.0
    weighted_conceded = 0.0

    for match in match_history:
        w = time_decay_weight(match.date, reference_date, alpha)
        weighted_scored    += match.goals_scored   * w
        weighted_conceded  += match.goals_conceded * w
        total_weight       += w

    if total_weight < 1e-9:
        return None

    lambda_scored    = weighted_scored   / total_weight
    lambda_conceded  = weighted_conceded / total_weight
    return lambda_scored, lambda_conceded


def elo_lambda_adjustment(elo_home: float,
                          elo_away: float,
                          base_lambda_home: float,
                          base_lambda_away: float) -> tuple[float, float]:
    """
    Adjusts base lambdas using Elo rating difference.

    The Elo-predicted win probability scales the lambdas up/down:
        P_elo(home wins) = 1 / (1 + 10^(−ΔElo/400))

    If the model's implied home win probability is lower than Elo predicts,
    we shift lambda toward what the ratings suggest.

    Returns adjusted (lambda_home, lambda_away).
    """
    delta_elo = elo_home - elo_away

    # Elo win probability for home team
    p_elo_home = 1.0 / (1.0 + 10.0 ** (-delta_elo / 400.0))

    # Poisson-implied home win probability (approximation)
    ratio = base_lambda_home / (base_lambda_home + base_lambda_away + 1e-9)
    p_poisson_home = ratio  # simplified proxy

    # Blend factor: weight Elo at 30%, Poisson at 70%
    blend = 0.30
    p_blended_home = blend * p_elo_home + (1 - blend) * p_poisson_home

    # Scale lambdas to reflect blended probability
    scale_home = p_blended_home / (p_poisson_home + 1e-9)
    scale_away = (1 - p_blended_home) / ((1 - p_poisson_home) + 1e-9)

    adj_lambda_home = base_lambda_home * max(0.5, min(scale_home, 2.0))
    adj_lambda_away = base_lambda_away * max(0.5, min(scale_away, 2.0))

    return adj_lambda_home, adj_lambda_away


def get_lambda_for_team(team: TeamProfile,
                        opponent: TeamProfile,
                        is_home: bool,
                        alpha: float = 0.01) -> tuple[float, float]:
    """
    Master function: returns (lambda_attack, lambda_defense) for a team.
    Priority: time-decay data → Elo-adjusted static stats → raw static.
    """
    from wc2026_group_predictions import TEAM_STATS_BASE  # type: ignore

    # Try time-decay from real match data first
    decay_result = calculate_time_decayed_lambda(team.match_history, alpha)

    if decay_result:
        lam_scored, lam_conceded = decay_result
        source = "time_decay"
    else:
        # Fallback to static base stats
        key = team.name.lower()
        if key in TEAM_STATS_BASE:
            s, c, _ = TEAM_STATS_BASE[key]
        else:
            s, c = 1.2, 1.2   # absolute fallback
        lam_scored, lam_conceded = s, c
        source = "static_base"

    # Apply Elo adjustment when using static data
    if source == "static_base":
        opp_key = opponent.name.lower()
        if opp_key in TEAM_STATS_BASE:
            os_, oc, _ = TEAM_STATS_BASE[opp_key]
        else:
            os_, oc = 1.2, 1.2

        if is_home:
            lam_scored, _ = elo_lambda_adjustment(
                team.elo_rating, opponent.elo_rating, lam_scored, os_
            )
        else:
            _, lam_scored = elo_lambda_adjustment(
                opponent.elo_rating, team.elo_rating, os_, lam_scored
            )

    return lam_scored, lam_conceded


# ══════════════════════════════════════════════════════════════════════
# MODULE 2 — DIXON-COLES MODEL
# ══════════════════════════════════════════════════════════════════════

def dixon_coles_tau(x: int, y: int,
                    lam: float, mu: float,
                    rho: float) -> float:
    """
    Dixon-Coles low-score correction factor τ.

    Corrects Poisson independence assumption for outcomes where x+y ≤ 1.
    Only these 4 scorelines deviate meaningfully from independence:
        (0,0), (1,0), (0,1), (1,1)

    Args:
        x:   Goals by home team
        y:   Goals by away team
        lam: Expected goals for home team (λ)
        mu:  Expected goals for away team (μ)
        rho: Correlation parameter. Negative value (≈ −0.13) means
             real football has slightly fewer 0-0 and 1-1 draws than
             pure Poisson predicts, correcting for tactical adjustments.

    Returns:
        Multiplicative correction factor (1.0 = no correction).
    """
    if x == 0 and y == 0:
        return 1.0 - lam * mu * rho
    elif x == 1 and y == 0:
        return 1.0 + mu * rho
    elif x == 0 and y == 1:
        return 1.0 + lam * rho
    elif x == 1 and y == 1:
        return 1.0 - rho
    else:
        return 1.0   # no correction for higher scores


def poisson_pmf(k: int, lam: float) -> float:
    """Standard Poisson probability mass function."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def dixon_coles_score_matrix(lam: float,
                              mu: float,
                              rho: float = -0.13,
                              max_goals: int = 7) -> list[list[float]]:
    """
    Builds a (max_goals+1) × (max_goals+1) probability matrix where
    matrix[x][y] = P(home scores x, away scores y).

    Args:
        lam:       Expected goals for home team
        mu:        Expected goals for away team
        rho:       Dixon-Coles correlation (−0.13 recommended for WC)
        max_goals: Maximum goals per team to model

    Returns:
        2D list of probabilities (rows = home goals, cols = away goals)
    """
    matrix = []
    for x in range(max_goals + 1):
        row = []
        for y in range(max_goals + 1):
            p = (poisson_pmf(x, lam) *
                 poisson_pmf(y, mu) *
                 dixon_coles_tau(x, y, lam, mu, rho))
            row.append(p)
        matrix.append(row)

    # Normalize so probabilities sum to 1.0
    total = sum(p for row in matrix for p in row)
    if total > 0:
        matrix = [[p / total for p in row] for row in matrix]

    return matrix


def dixon_coles_predict(lam: float,
                         mu: float,
                         rho: float = -0.13,
                         max_goals: int = 7) -> dict:
    """
    Full Dixon-Coles prediction from expected goals λ and μ.

    Returns dict with:
        prob_h    : P(home win) as percentage
        prob_d    : P(draw) as percentage
        prob_a    : P(away win) as percentage
        best_score: Most likely exact score (x-y)
        matrix    : Full score probability matrix
        lam, mu   : Expected goals used
    """
    matrix = dixon_coles_score_matrix(lam, mu, rho, max_goals)

    prob_h = prob_d = prob_a = 0.0
    best_p = 0.0
    best_score = (0, 0)

    for x in range(max_goals + 1):
        for y in range(max_goals + 1):
            p = matrix[x][y]
            if x > y:
                prob_h += p
            elif x == y:
                prob_d += p
            else:
                prob_a += p
            if p > best_p:
                best_p = p
                best_score = (x, y)

    return {
        "prob_h":      round(prob_h * 100, 2),
        "prob_d":      round(prob_d * 100, 2),
        "prob_a":      round(prob_a * 100, 2),
        "best_score":  f"{best_score[0]}-{best_score[1]}",
        "lam":         round(lam, 3),
        "mu":          round(mu, 3),
        "matrix":      matrix,
    }


# ══════════════════════════════════════════════════════════════════════
# MODULE 3 — WC 2026 SPECIFIC MODIFIERS
# ══════════════════════════════════════════════════════════════════════

# Approximate distances (km) between WC 2026 host city pairs
# Used to determine if travel fatigue applies
CITY_DISTANCES_KM: dict[tuple[str, str], float] = {
    ("Vancouver",     "Miami"):         5400,
    ("Vancouver",     "Dallas"):        2600,
    ("Vancouver",     "New York"):      4000,
    ("Los Angeles",   "Boston"):        4200,
    ("Los Angeles",   "Miami"):         3750,
    ("Seattle",       "Miami"):         5300,
    ("San Francisco", "Miami"):         4350,
    ("Mexico City",   "Toronto"):       3200,
    ("Guadalajara",   "New York"):      3600,
    ("Monterrey",     "Vancouver"):     3100,
    ("Kansas City",   "Miami"):         2150,
    ("Atlanta",       "Los Angeles"):   3150,
    ("Dallas",        "Vancouver"):     2600,
    ("Houston",       "Seattle"):       3200,
}

# Distance threshold for "significant travel" (km)
FATIGUE_DISTANCE_THRESHOLD_KM = 3000


def get_travel_distance(city_from: str, city_to: str) -> float:
    """Looks up approximate travel distance between two WC host cities."""
    key = (city_from, city_to)
    reverse_key = (city_to, city_from)
    return CITY_DISTANCES_KM.get(key, CITY_DISTANCES_KM.get(reverse_key, 0.0))


def apply_host_advantage(lam_home: float,
                          home_team: TeamProfile,
                          venue_city: str,
                          boost_pct: float = 0.08) -> float:
    """
    Applies host-nation advantage boost to home lambda.

    Only USA, Mexico, Canada get the boost, and only when playing
    in their own territory (matched by city).

    Args:
        lam_home:   Base expected goals for home team
        home_team:  TeamProfile of the home team
        venue_city: City where the match is played
        boost_pct:  Lambda boost percentage (default 8%)

    Returns:
        Adjusted lambda_home.
    """
    HOST_NATIONS = {"united states", "usa", "mexico", "canada"}

    if home_team.name.lower() in HOST_NATIONS:
        if venue_city in home_team.host_cities or home_team.is_host:
            boosted = lam_home * (1.0 + boost_pct)
            return boosted

    return lam_home


def apply_travel_fatigue(lam: float,
                          team: TeamProfile,
                          venue_city: str,
                          fatigue_penalty: float = 0.05) -> float:
    """
    Deducts travel fatigue penalty when a team travels a large distance.

    Args:
        lam:             Base expected goals lambda
        team:            TeamProfile with last_match_city populated
        venue_city:      City of the upcoming match
        fatigue_penalty: Lambda reduction fraction (default 5%)

    Returns:
        Adjusted lambda.
    """
    if not team.last_match_city or team.last_match_city == venue_city:
        return lam

    distance = get_travel_distance(team.last_match_city, venue_city)

    if distance >= FATIGUE_DISTANCE_THRESHOLD_KM:
        penalty_factor = 1.0 - fatigue_penalty
        # Scale penalty with distance — very long flights hurt more
        if distance > 4500:
            penalty_factor -= 0.02   # extra -2% for transcontinental flights
        return lam * max(penalty_factor, 0.80)   # cap at -20%

    return lam


def apply_group_stage_motivation(lam: float,
                                  team: TeamProfile,
                                  matchday: int,
                                  rotation_penalty: float = 0.12) -> float:
    """
    Applies rotation penalty on Matchday 3 for already-qualified teams.

    Logic: if it's MD3 AND the team already has 6 points (max possible
    from MD1+MD2), they are assumed to rotate their squad. Their attack
    lambda is reduced by rotation_penalty (default 12%).

    Args:
        lam:               Current attack lambda
        team:              TeamProfile with group_points set
        matchday:          Current matchday (1, 2, or 3)
        rotation_penalty:  Lambda reduction fraction (default 12%)

    Returns:
        Adjusted lambda.
    """
    if matchday == 3 and team.group_points >= 6:
        return lam * (1.0 - rotation_penalty)
    return lam


def apply_all_wc_modifiers(lam_home: float,
                             lam_away: float,
                             home_team: TeamProfile,
                             away_team: TeamProfile,
                             venue_city: str,
                             matchday: int) -> tuple[float, float]:
    """
    Applies all WC 2026 modifiers in sequence:
        1. Host advantage (home team)
        2. Travel fatigue (both teams)
        3. Group stage motivation / rotation (both teams)

    Returns modified (lam_home, lam_away).
    """
    # 1. Host advantage
    lam_home = apply_host_advantage(lam_home, home_team, venue_city)

    # 2. Travel fatigue
    lam_home = apply_travel_fatigue(lam_home, home_team, venue_city)
    lam_away = apply_travel_fatigue(lam_away, away_team, venue_city)

    # 3. Rotation / motivation
    lam_home = apply_group_stage_motivation(lam_home, home_team, matchday)
    lam_away = apply_group_stage_motivation(lam_away, away_team, matchday)

    return lam_home, lam_away


# ══════════════════════════════════════════════════════════════════════
# MODULE 4 — KELLY CRITERION + BANKROLL MANAGEMENT
# ══════════════════════════════════════════════════════════════════════

@dataclass
class BettingSignal:
    """Full betting recommendation output."""
    outcome: str           # "1", "X", or "2"
    probability: float     # model probability (0–1)
    decimal_odd: float     # bookmaker decimal odd
    ev: float              # expected value
    kelly_full: float      # full Kelly fraction
    kelly_fraction: float  # fractional Kelly (recommended stake fraction)
    stake_example: float   # example stake on €100 bankroll
    is_value: bool         # True if EV > min_ev threshold


def kelly_criterion(p: float,
                    decimal_odd: float,
                    fraction: float = 0.25) -> tuple[float, float]:
    """
    Calculates optimal bet size using the Kelly Criterion.

    f* = (p × b − q) / b
    where: b = decimal_odd − 1  (net profit per unit staked)
           q = 1 − p            (probability of loss)

    Fractional Kelly: stake = f* × fraction
    Using 0.25 (Quarter Kelly) drastically reduces variance while
    retaining ~75% of the growth rate of Full Kelly.

    Args:
        p:           Model win probability (0–1)
        decimal_odd: Bookmaker decimal odd (e.g., 2.50)
        fraction:    Kelly fraction (0.25 = Quarter Kelly recommended)

    Returns:
        (full_kelly, fractional_kelly) — both as fractions of bankroll.
        Negative full Kelly = no bet (bookmaker has the edge).
    """
    b = decimal_odd - 1.0   # net odds
    q = 1.0 - p             # loss probability

    if b <= 0:
        return 0.0, 0.0

    full_kelly = (p * b - q) / b

    # Never bet if Kelly is negative (no edge)
    if full_kelly <= 0:
        return full_kelly, 0.0

    # Cap at 20% of bankroll even with high confidence
    full_kelly = min(full_kelly, 0.20)
    fractional_kelly = full_kelly * fraction

    return round(full_kelly, 4), round(fractional_kelly, 4)


def calculate_ev(p: float, decimal_odd: float) -> float:
    """Expected Value: positive = profitable bet over the long run."""
    return round(p * decimal_odd - 1.0, 4)


def evaluate_betting_opportunity(outcome: str,
                                  probability: float,
                                  decimal_odd: float,
                                  kelly_fraction: float = 0.25,
                                  min_ev: float = 0.04,
                                  min_prob: float = 0.20,
                                  bankroll: float = 100.0) -> BettingSignal:
    """
    Full evaluation of a single betting market (1, X, or 2).

    Args:
        outcome:        Market label ("1", "X", "2")
        probability:    Model probability for this outcome (0–1)
        decimal_odd:    Bookmaker decimal odd
        kelly_fraction: Fractional Kelly to use (default 0.25)
        min_ev:         Minimum EV to flag as value bet (default 4%)
        min_prob:       Skip bets with very low model probability
        bankroll:       Example bankroll for stake calculation

    Returns:
        BettingSignal with all metrics.
    """
    ev = calculate_ev(probability, decimal_odd)
    full_k, frac_k = kelly_criterion(probability, decimal_odd, kelly_fraction)
    is_value = ev >= min_ev and probability >= min_prob and frac_k > 0

    return BettingSignal(
        outcome=outcome,
        probability=round(probability, 4),
        decimal_odd=decimal_odd,
        ev=ev,
        kelly_full=full_k,
        kelly_fraction=frac_k,
        stake_example=round(bankroll * frac_k, 2),
        is_value=is_value,
    )


def find_best_value_bet(prob_h: float, prob_d: float, prob_a: float,
                         odd_1: float, odd_x: float, odd_2: float,
                         kelly_fraction: float = 0.25,
                         min_ev: float = 0.04,
                         bankroll: float = 100.0) -> Optional[BettingSignal]:
    """
    Evaluates all three markets (1/X/2) and returns the best value bet,
    or None if no value exists.
    """
    candidates = [
        evaluate_betting_opportunity("1", prob_h, odd_1, kelly_fraction, min_ev, bankroll=bankroll),
        evaluate_betting_opportunity("X", prob_d, odd_x, kelly_fraction, min_ev, bankroll=bankroll),
        evaluate_betting_opportunity("2", prob_a, odd_2, kelly_fraction, min_ev, bankroll=bankroll),
    ]

    value_bets = [s for s in candidates if s.is_value]
    if not value_bets:
        return None

    return max(value_bets, key=lambda s: s.ev)


# ══════════════════════════════════════════════════════════════════════
# MASTER PREDICTION FUNCTION
# ══════════════════════════════════════════════════════════════════════

def predict_match_v2(home_team: TeamProfile,
                      away_team: TeamProfile,
                      venue_city: str,
                      matchday: int,
                      odd_1: float,
                      odd_x: float,
                      odd_2: float,
                      rho: float = -0.13,
                      kelly_fraction: float = 0.25,
                      alpha: float = 0.01,
                      use_dynamic: bool = False,
                      half_life_days: float = 180.0) -> dict:
    """
    Full pipeline v2: Time Decay → Elo → WC Modifiers → Dixon-Coles → Kelly.

    Args:
        home_team:      TeamProfile for home side
        away_team:      TeamProfile for away side
        venue_city:     Match venue city (for host/fatigue logic)
        matchday:       1, 2, or 3 (group stage)
        odd_1/x/2:      Bookmaker decimal odds
        rho:            Dixon-Coles correlation (default −0.13)
        kelly_fraction: Fractional Kelly (default 0.25)
        alpha:          Time decay rate for the built-in static path (default 0.01)
        use_dynamic:    If True, pull live xG + half-life λ from dynamic_data
                        (API-Sports → Elo fallback). If False, use the
                        in-engine match_history / static path.
        half_life_days: Half-life (days) for the dynamic decay (default 180).

    Returns:
        Full prediction dict with probabilities, Kelly stakes, value bet.
    """
    data_source = "static_engine"

    # Step 1: Get base lambdas.
    if use_dynamic:
        # Lazy import avoids the circular dependency (dynamic_data imports
        # MatchRecord/ELO_RATINGS from this module).
        from dynamic_data import get_provider   # type: ignore
        provider = get_provider(half_life_days=half_life_days)
        dl_home, dl_away = provider.get_match_lambdas(home_team.name, away_team.name)
        lam_home = math.sqrt(dl_home.lam_attack * dl_away.lam_defense)
        lam_away = math.sqrt(dl_away.lam_attack * dl_home.lam_defense)
        data_source = dl_home.data_source
    else:
        lam_h_atk, lam_h_def = get_lambda_for_team(home_team, away_team, True, alpha)
        lam_a_atk, lam_a_def = get_lambda_for_team(away_team, home_team, False, alpha)
        # Geometric mean base lambdas (consistent with v1 improvement)
        lam_home = math.sqrt(lam_h_atk * lam_a_def)
        lam_away = math.sqrt(lam_a_atk * lam_h_def)

    # Step 2: Apply WC 2026 modifiers
    lam_home, lam_away = apply_all_wc_modifiers(
        lam_home, lam_away, home_team, away_team, venue_city, matchday
    )

    # Step 3: Dixon-Coles prediction
    result = dixon_coles_predict(lam_home, lam_away, rho)

    prob_h = result["prob_h"] / 100
    prob_d = result["prob_d"] / 100
    prob_a = result["prob_a"] / 100

    # Step 4: Kelly / Value bet
    best_bet = find_best_value_bet(
        prob_h, prob_d, prob_a, odd_1, odd_x, odd_2, kelly_fraction
    )

    return {
        "home":        home_team.name,
        "away":        away_team.name,
        "venue":       venue_city,
        "matchday":    matchday,
        "data_source": data_source,
        "lam_home":    round(lam_home, 3),
        "lam_away":    round(lam_away, 3),
        "prob_h":      result["prob_h"],
        "prob_d":      result["prob_d"],
        "prob_a":      result["prob_a"],
        "best_score":  result["best_score"],
        "odd_1":       odd_1,
        "odd_x":       odd_x,
        "odd_2":       odd_2,
        "best_bet":    best_bet,
    }


# ══════════════════════════════════════════════════════════════════════
# DEMO — OLD POISSON vs NEW DIXON-COLES (Mexico vs Poland)
# ══════════════════════════════════════════════════════════════════════

def run_comparison_demo():
    """
    Compares old basic Poisson with new Dixon-Coles for Mexico vs Poland.
    Demonstrates the effect of DC correction on low-score probabilities.
    """
    import itertools

    print("=" * 65)
    print("  DEMO: Mexico vs Poland  |  Dallas, TX  |  Matchday 1")
    print("=" * 65)

    # Shared base parameters
    lam_mexico = 1.95   # Mexico attack vs Poland defense (geometric mean)
    lam_poland  = 1.30   # Poland attack vs Mexico defense

    odd_1, odd_x, odd_2 = 2.10, 3.30, 3.60
    max_goals = 7

    # ── OLD MODEL: Basic Poisson ───────────────────────────────
    def basic_poisson_predict(lam_h, lam_a, max_g=6):
        p_hw = p_d = p_aw = 0.0
        best_p = 0.0; best_s = (0, 0)
        for x, y in itertools.product(range(max_g + 1), repeat=2):
            p = poisson_pmf(x, lam_h) * poisson_pmf(y, lam_a)
            if x > y: p_hw += p
            elif x == y: p_d += p
            else: p_aw += p
            if p > best_p: best_p = p; best_s = (x, y)
        t = p_hw + p_d + p_aw
        return p_hw/t*100, p_d/t*100, p_aw/t*100, f"{best_s[0]}-{best_s[1]}"

    old_h, old_d, old_a, old_score = basic_poisson_predict(lam_mexico, lam_poland)

    # ── NEW MODEL: Dixon-Coles ─────────────────────────────────
    dc = dixon_coles_predict(lam_mexico, lam_poland, rho=-0.13, max_goals=max_goals)

    print(f"\n  Expected Goals:  Mexico λ={lam_mexico}  |  Poland λ={lam_poland}")
    print(f"  Bookmaker Odds:  1={odd_1}  X={odd_x}  2={odd_2}\n")

    print(f"  {'Metric':<28}  {'Basic Poisson':>14}  {'Dixon-Coles':>12}")
    print("  " + "─" * 58)
    print(f"  {'P(Mexico wins)':<28}  {old_h:>13.2f}%  {dc['prob_h']:>11.2f}%")
    print(f"  {'P(Draw)':<28}  {old_d:>13.2f}%  {dc['prob_d']:>11.2f}%")
    print(f"  {'P(Poland wins)':<28}  {old_a:>13.2f}%  {dc['prob_a']:>11.2f}%")
    print(f"  {'Most likely score':<28}  {old_score:>14}  {dc['best_score']:>12}")

    # Show exact score probabilities for low-score outcomes
    matrix = dc["matrix"]
    print(f"\n  {'Score':<10}  {'Basic Poisson':>14}  {'Dixon-Coles':>12}  {'Δ':>8}")
    print("  " + "─" * 50)
    for x, y in [(0,0), (1,0), (0,1), (1,1), (2,0), (2,1), (1,2)]:
        bp = poisson_pmf(x, lam_mexico) * poisson_pmf(y, lam_poland)
        dc_p = matrix[x][y]
        delta = dc_p - bp
        tag = " ← DC corrects" if abs(delta) > 0.005 and x + y <= 1 else ""
        print(f"  {x}-{y:<8}  {bp*100:>13.2f}%  {dc_p*100:>11.2f}%  {delta*100:>+7.2f}%{tag}")

    # EV comparison
    print(f"\n  {'Market':<8}  {'Old EV':>10}  {'New EV':>10}  {'Kelly stake':>12}")
    print("  " + "─" * 45)
    probs_old = [(old_h/100, odd_1, "1 Mexico"), (old_d/100, odd_x, "X Draw"), (old_a/100, odd_2, "2 Poland")]
    probs_new = [(dc['prob_h']/100, odd_1, "1 Mexico"), (dc['prob_d']/100, odd_x, "X Draw"), (dc['prob_a']/100, odd_2, "2 Poland")]

    for (p_old, odd, label), (p_new, _, _) in zip(probs_old, probs_new):
        ev_old = calculate_ev(p_old, odd)
        ev_new = calculate_ev(p_new, odd)
        _, frac_k = kelly_criterion(p_new, odd, 0.25)
        stake = f"€{100*frac_k:.2f}" if frac_k > 0 and ev_new > 0.04 else "no bet"
        print(f"  {label:<8}  {ev_old:>+9.2%}  {ev_new:>+9.2%}  {stake:>12}")

    # Mexico host advantage demo
    print(f"\n  ── Host Advantage Demo (Mexico in Guadalajara) ──")
    lam_boosted = apply_host_advantage(
        lam_mexico,
        TeamProfile("Mexico", is_host=True,
                    host_cities=["Guadalajara", "Monterrey"]),
        "Guadalajara", boost_pct=0.08,
    )
    dc_boost = dixon_coles_predict(lam_boosted, lam_poland, rho=-0.13)
    print(f"  Mexico lambda without host boost: {lam_mexico:.3f}")
    print(f"  Mexico lambda with host boost:    {lam_boosted:.3f}  (+8%)")
    print(f"  P(Mexico wins): {dc['prob_h']:.2f}%  ->  {dc_boost['prob_h']:.2f}%")

    print(f"\n  ── Kelly Criterion Demo (Quarter Kelly on bankroll 1000) ──")
    p_mexico = dc['prob_h'] / 100
    ev = calculate_ev(p_mexico, odd_1)
    full_k, frac_k = kelly_criterion(p_mexico, odd_1, fraction=0.25)
    print(f"  P(Mexico) = {p_mexico:.2%}  |  Odd = {odd_1}  |  EV = {ev:+.2%}")
    print(f"  Full Kelly:     {full_k:.2%} of bankroll")
    print(f"  Quarter Kelly:  {frac_k:.2%} of bankroll  <- recommended")
    print("\n" + "=" * 65)


if __name__ == "__main__":
    run_comparison_demo()
