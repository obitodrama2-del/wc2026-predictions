# Si Funksionon Sistemi i Parashikimit — WC 2026

---

## 1. Burimet e të Dhënave

### football-data.org (API falas)
- Merr listën e të gjitha **48 skuadrave** të WC 2026
- Merr **ndeshjet e fazës së grupeve** (64 ndeshje)
- Për çdo skuadër, tenton të marrë **statistikat nga ndeshjet e fundit** (forma)
- **Kufizim:** Tier falas lejon vetëm ~10 kërkesa/minutë dhe nuk lejon historikun e plotë të ndeshjeve për çdo ekip

### TEAM_STATS_BASE (fallback kryesor)
Kur API nuk jep të dhëna (shumica e rasteve), sistemi përdor statistikat e vendosura manualisht bazuar në **FIFA ranking + formën e fundit 2023-2025**:

```
(goals_scored_avg, goals_conceded_avg, points_per_game)

Argentina:   (3.2, 0.5, 2.5)   ← elite
Brazil:      (2.8, 0.6, 2.3)   ← elite
Haiti:       (0.6, 2.1, 0.6)   ← shumë i dobët
Qatar:       (0.7, 1.9, 0.8)   ← shumë i dobët
```

**Problemi:** ~90% e ndeshjeve përdorin këto statistika statike, jo të dhëna reale dinamike.

---

## 2. Algoritmi i Parashikimit (Poisson)

### Hapi 1 — Llogaritja e Lambda (gola të pritshëm)

Përdorim **mesataren gjeometrike** (përmirësim i fundit):

```
λ_home = √(scored_home × conceded_away)
λ_away = √(scored_away × conceded_home)
```

**Shembull: Brazil (2.8, 0.6) vs Haiti (0.6, 2.1)**
```
λ_brazil = √(2.8 × 2.1) = √5.88 = 2.42  (gola të pritshëm për Brazil)
λ_haiti  = √(0.6 × 0.6) = √0.36 = 0.60  (gola të pritshëm për Haiti)
```

### Hapi 2 — Shpërndarja Poisson

Për çdo kombinim rezultati (0-0, 1-0, 0-1, 1-1, ... 6-6), llogaritet probabiliteti:

```
P(k gola) = (e^-λ × λ^k) / k!
```

### Hapi 3 — Grumbullimi i Probabiliteteve

```
P(fitore vendas) = shuma e P(g_h > g_a) për të gjitha kombinimet
P(barazim)       = shuma e P(g_h = g_a)
P(fitore mysafir) = shuma e P(g_h < g_a)
```

**Rezultat Brazil vs Haiti:**
```
1 (Brazil): 77.5%
X (Barazim): 15.1%
2 (Haiti):   7.4%
```

### Çfarë mungon në algoritëm:
- ❌ Avantazhi i fushës (home advantage) — në WC luan rol minimal por ekziston
- ❌ Lodhja / ndeshje të grumbulluara
- ❌ Mungesa e lojtarëve kyç (lëndime, kartonë)
- ❌ Motivimi (ekip tashmë i kualifikuar vs ekip që ka nevojë për pikë)
- ❌ Statistika dinamike (forma e fundit 3-5 ndeshje, jo mesatare sezonale)

---

## 3. Koeficientët (The Odds API → Tipico)

- Merr koeficientet live për **soccer_fifa_world_cup** nga Tipico (tipico_de)
- Konverton emrat e ekipeve me **fuzzy matching** (difflib) për të lidhur me modelin
- Merr: `odd_1` (fitore vendas), `odd_x` (barazim), `odd_2` (fitore mysafir)

---

## 4. Value Bet (EV)

```
EV_1 = (prob_home / 100) × odd_1 - 1
EV_X = (prob_draw / 100) × odd_x - 1
EV_2 = (prob_away / 100) × odd_2 - 1
```

**Shembull:**
```
Brazil fitore: prob=77.5%, odd=1.35
EV = (0.775 × 1.35) - 1 = 1.046 - 1 = +0.046 → +4.6% ✅ Value Bet
```

Zgjidhim rezultatin me **EV më të lartë** si parashikim kryesor.

**Problemi:** Nëse statistikat statike janë të gabuara, edhe EV është i gabuar.

---

## 5. Telegram

Dërgohen 2 mesazhe:
1. **Lista e plotë** — të gjitha ndeshjet me parashikimin (1/X/2)
2. **Kombinimi më i mirë** — top 5 ndeshje sipas prob × koeficient

---

## 6. Automatizimi (GitHub Actions)

```
07:00 UTC → ekzekutohet send_predictions.py → Telegram
14:00 UTC → ekzekutohet send_predictions.py → Telegram
21:00 UTC → ekzekutohet send_predictions.py → Telegram
```

Konsumon ~3 minuta GitHub Actions në ditë (270 min/muaj falas).

---

## 7. Çfarë Mund të Përmirësohet

### 🔴 Prioritet i Lartë

| Problem | Zgjidhja |
|--------|-----------|
| Statistikat janë statike (FIFA rank) | Integro API që jep formën e fundit reale (5 ndeshjet e fundit) |
| Nuk ka home advantage | Shto +5-10% për ekipin vendor |
| Nuk dallohen ndeshjet e rëndësishme | Shto peshë për motivim (grup A vs grup finales) |

### 🟡 Prioritet Mesatar

| Problem | Zgjidhja |
|--------|-----------|
| Fuzzy matching mund të gabojë emrat | Shto NAME_MAP manual për të gjitha 48 ekipet |
| Koeficientet Tipico mund të mungojnë | Shto bookmaker alternativ si fallback |
| Nuk filtrohen ndeshjet e luajtura | Shto filtër: dërgo vetëm ndeshjet e ardhshme |

### 🟢 Përmirësime Opsionale

| Idea | Efekti |
|------|--------|
| Modeli Dixon-Coles (version i avancuar i Poisson) | Probabilitete më të sakta për rezultate me shumë gola |
| Shto Over/Under 2.5 gola | Treg shtesë për value bets |
| Confidence score (0-100) | Tregon sa i sigurt është modeli për çdo parashikim |
| Backtesting me ndeshje të kaluara | Verifikon nëse modeli ka qenë fitimtar historikisht |

---

## 8. Saktësia e Pritshme

Modeli Poisson është standard në industri. Saktësia tipike:
- **1X2:** ~52-55% parashikime korrekte
- **Value Bets:** fitimtare afatgjatë nëse EV > 5% vazhdimisht
- **Kufizimi kryesor:** statistikat statike e ulin saktësinë — me të dhëna dinamike rritet në ~57-60%
