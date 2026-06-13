# WC 2026 Prediction Engine — Upgrade Notes (v2 → v3)

This documents the 4-part upgrade: dynamic data + time decay, Dixon-Coles,
WC 2026 modifiers, and Kelly staking. Code lives in two modules that drop into
the existing pipeline:

- `dynamic_data.py` — direct API-Sports layer, half-life decay, SQLite cache, rate limiter
- `prediction_engine_v2.py` — Dixon-Coles, WC modifiers, Kelly, master `predict_match_v2()`

---

## 1. Mathematical implementation (the two core ideas)

### Time Decay (exponential half-life)

Raw historical averages treat a match from 3 years ago the same as last week's.
We weight each past match by an exponential decay so recent form dominates:

    W(t) = e^(−α · t)        t = days since the match

Instead of picking `α` blindly, we parameterise it by a **half-life** — the
number of days after which a match is worth half as much:

    α = ln(2) / half_life

A 180-day half-life (the default) means a match 6 months old carries exactly
50% weight, 12 months ≈ 25%, etc. The time-decayed expected-goals metric
(Lambda) for a team is the weighted mean of its xG (or goals as fallback):

    λ_attack  = Σ(xG_scored_i   · W(t_i)) / Σ(W(t_i))
    λ_defense = Σ(xG_conceded_i · W(t_i)) / Σ(W(t_i))

xG is preferred over goals because it is far less noisy over a 5–10 match
sample. If live data is unavailable (no key / quota spent), the layer falls
back to static base stats adjusted by the **Elo** win probability:

    P_elo(win) = 1 / (1 + 10^(−ΔElo/400))

### Dixon-Coles correction

A plain bivariate Poisson assumes the two teams' goals are independent. In
reality, low-scoring outcomes are correlated — there are more 0-0 and 1-1
draws, and fewer 1-0 / 0-1 results, than independence predicts (teams shut up
shop at 0-0, chase the game when 1-0 down, etc.). Dixon-Coles multiplies the
joint probability by a correction factor τ that only touches the four
low-score cells (x + y ≤ 1):

    P(x, y) = Poisson(x | λ) · Poisson(y | μ) · τ(x, y, λ, μ, ρ)

    τ = 1 − λ·μ·ρ   if (x, y) = (0, 0)
        1 + μ·ρ     if (x, y) = (1, 0)
        1 + λ·ρ     if (x, y) = (0, 1)
        1 − ρ       if (x, y) = (1, 1)
        1           otherwise

With ρ ≈ −0.13 (typical for international football) this **raises** P(0-0) and
P(1-1) and **lowers** P(1-0) and P(0-1). The full score matrix is renormalised
so all cells sum to 1, then collapsed into 1 / X / 2 probabilities.

---

## 2. The four components

**(1) Dynamic data & decay — `dynamic_data.py`**
Connects directly to `https://v3.football.api-sports.io` using only the
`x-apisports-key` header (no RapidAPI, no Sportmonks). `GET /fixtures` pulls
the last 5–10 matches; `GET /fixtures/statistics` pulls Expected Goals. A
SQLite cache (TTL) and a two-tier token-bucket rate limiter (per-minute +
persisted daily quota, free-tier defaults 10/min and 100/day, fully
overridable) keep usage inside the free plan. `DynamicDataProvider` returns a
half-life-decayed λ per team, with automatic Elo + static fallback.

**(2) Dixon-Coles — `prediction_engine_v2.py`**
`dixon_coles_tau`, `dixon_coles_score_matrix`, `dixon_coles_predict`.

**(3) WC 2026 modifiers — `prediction_engine_v2.py`**
- Host advantage: +8% λ for USA / Mexico / Canada when playing in a host city.
- Travel fatigue: −5% λ (−7% for transcontinental > 4500 km) when a team
  travels ≥ 3000 km between matchdays.
- Matchday-3 rotation: −12% λ when a team already has 6 points (qualified).

**(4) Kelly staking — `prediction_engine_v2.py`**
    f* = (p·b − q) / b      b = decimal_odd − 1,  q = 1 − p
Negative f* ⇒ no bet. Output uses **Fractional (Quarter) Kelly** (0.25) and a
20% hard cap for strict bankroll management.

---

## 3. Mocked comparison — Basic Poisson vs adjusted Dixon-Coles

Hypothetical: **Mexico vs Poland**, λ_Mexico = 1.95, λ_Poland = 1.30, odds 2.10 / 3.30 / 3.60.

| Metric            | Basic Poisson | Dixon-Coles |
|-------------------|--------------:|------------:|
| P(Mexico wins)    |        52.41% |      51.26% |
| P(Draw)           |        22.10% |      24.58% |
| P(Poland wins)    |        25.50% |      24.17% |
| Most likely score |           1-1 |         1-1 |

Low-score cells — where Dixon-Coles changes things:

| Score | Basic Poisson | Dixon-Coles |       Δ |
|-------|--------------:|------------:|--------:|
| 0-0   |         3.88% |       5.16% | **+1.28%** |
| 1-0   |         7.56% |       6.29% | **−1.27%** |
| 0-1   |         5.04% |       3.77% | **−1.27%** |
| 1-1   |         9.83% |      11.12% | **+1.29%** |
| 2-0   |         7.37% |       7.38% |  +0.01% |

The draw probability rises (22.1% → 24.6%) precisely because the model now
expects more 0-0 / 1-1 results — the flaw Dixon-Coles was designed to fix.

Betting view (Quarter Kelly, €100 bankroll):

| Market   | Old EV  | New EV  | Kelly stake |
|----------|--------:|--------:|------------:|
| 1 Mexico | +10.06% |  +7.65% |       €1.74 |
| X Draw   | −27.09% | −18.89% |      no bet |
| 2 Poland |  −8.21% | −12.99% |      no bet |

Host advantage (Mexico in Guadalajara, +8% λ): P(Mexico) 51.26% → 54.67%.

---

## 4. Integration

Lambdas now flow from the dynamic layer when you ask for it — the master
function gained two parameters:

```python
from prediction_engine_v2 import predict_match_v2, TeamProfile

home = TeamProfile("Mexico", elo_rating=1875, is_host=True, host_cities=["Guadalajara"])
away = TeamProfile("Poland", elo_rating=1760)

# Live xG + 180-day half-life decay (falls back to Elo if no key/quota):
result = predict_match_v2(
    home, away, venue_city="Guadalajara", matchday=1,
    odd_1=2.10, odd_x=3.30, odd_2=3.60,
    use_dynamic=True, half_life_days=180,
)
print(result["data_source"], result["prob_h"], result["best_bet"])
```

Or use the drop-in stats helper inside `wc2026_group_predictions.py`:

```python
from dynamic_data import get_dynamic_stats
sh = get_dynamic_stats(hname, aname, is_home=True)
sa = get_dynamic_stats(aname, hname, is_home=False)
```

### Configuration (env vars / GitHub Secrets)

| Variable                 | Default | Purpose                              |
|--------------------------|--------:|--------------------------------------|
| `APISPORTS_KEY`          |    (—)  | API-Sports key (`x-apisports-key`)   |
| `DECAY_HALF_LIFE_DAYS`   |    180  | Decay half-life in days              |
| `APISPORTS_RATE_PER_MIN` |     10  | Token-bucket refill (requests/min)   |
| `APISPORTS_RATE_PER_DAY` |    100  | Daily quota (persisted in SQLite)    |
| `APISPORTS_CACHE_TTL_HOURS` |    6 | Cache freshness window               |
| `APISPORTS_DB_FILE`      | module dir | SQLite cache location             |

Get a free key at https://dashboard.api-football.com/register.
