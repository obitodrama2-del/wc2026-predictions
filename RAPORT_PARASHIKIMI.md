# Raport i detajuar — Si funksionon parashikimi (WC 2026)

Ky shënim përshkruan, hap-pas-hapi, si sistemi kthen dy ekipe në një parashikim
`1 / X / 2`, një rezultat të mundshëm dhe (opsionalisht) një bast me vlerë. Pasqyron
modelin aktual pas të gjitha përmirësimeve. Në fund ka një shembull të plotë numerik,
parametrat e konfigurueshëm dhe kufizimet.

---

## 1. Pamja e përgjithshme

Çdo parashikim kalon nëpër këtë zinxhir:

```
TË DHËNAT          →  λ (gola të pritur)      →  RREGULLIME         →  DIXON-COLES   →  VENDIMI
─────────────         ────────────────────       ──────────────        ───────────      ─────────
tabela + forma        forcë e tkurrur (shrink)    peshim Elo            prob 1/X/2       favoriti
reale, e përzier      × mesatare lige             modifikatorë WC       + skori          + value bet
(Bayes)                                           clamp                                  (anti-longshot)
```

Gjithçka varet nga **λ (lambda)** — numri i golave që pritet të shënojë secili ekip.
Nëse λ është i saktë, gjithçka pas tij është e saktë.

---

## 2. Hapi 1 — Të dhënat (me përzierje Bayesiane)

Sistemi merr statistikat nga dy burime dhe i kombinon:

- **Forma reale e WC 2026** — nga ndeshjet e luajtura të turneut (mesatarja e golave të
  shënuara/pësuara për ekip).
- **Tabela bazë `TEAM_STATS_BASE`** — vlerësim paraprak (prior) i fuqisë së çdo kombëtareje:
  `(gola_shënuar, gola_pësuar, pikë/ndeshje)`.

Në fillim të turneut, forma reale ka shumë pak ndeshje (1–2) dhe është e pabesueshme —
një rezultat i vetëm mund ta përmbysë gabimisht favoritin. Prandaj i përziejmë me peshë
sipas numrit të ndeshjeve (regresion drejt priorit / shrinkage Bayesian):

```
w = n / (n + PRIOR_MATCHES)            n = ndeshje reale,  PRIOR_MATCHES = 4
stat = w · stat_live + (1 − w) · stat_tabelë
```

- n = 1 ndeshje → w = 0.20 → **80% tabelë, 20% formë reale** (mbron nga zhurma).
- n = 4 → w = 0.50 → gjysmë-gjysmë.
- n = 10 → w = 0.71 → dominon forma reale e turneut.

Kjo do të thotë: parashikimet janë të qëndrueshme në fillim dhe bëhen gjithnjë e më të
mprehta ndërsa luhen ndeshje.

---

## 3. Hapi 2 — Forca e ekipit dhe λ bazë

Vlerat e tabelës nuk janë në një bazë të përbashkët, ndaj i kthejmë në **forcë relative**
ndaj mesatares së ligës (e nxjerrë automatikisht nga tabela), të **tkurrur** drejt 1.0 që
mospërputhjet ekstreme të mos shpërthejnë në λ joreale (p.sh. 5 gola):

```
forcë = 1 + STRENGTH_SHRINK · (vlera / mesatarja_ligës − 1)      STRENGTH_SHRINK = 0.5
```

Pastaj λ ndërtohet me modelin shumëzues standard:

```
λ_vendës  = sulm_vendës  × mbrojtje_mysafir × MU
λ_mysafir = sulm_mysafir × mbrojtje_vendës  × MU                 MU = 1.35 (gola mesatarë/ekip)
```

Logjika: sa shënon një ekip varet nga sulmi i tij DHE dobësia mbrojtëse e kundërshtarit.

---

## 4. Hapi 3 — Peshim me Elo + clamp

Vetëm tabela mund të mos pajtohet me renditjen reale (p.sh. dy mbrojtje elite e bëjnë
ndeshjen "monedhë"). Prandaj rishpërndajmë epërsinë drejt fuqisë Elo, duke **mbajtur
totalin e golave konstant**:

```
p_elo  = 1 / (1 + 10^(−(Elo_vendës − Elo_mysafir)/400))     # P(vendësi) sipas Elo
p_pois = λ_vendës / (λ_vendës + λ_mysafir)                  # ç'thotë λ aktual
p_mix  = (1 − w_elo)·p_pois + w_elo·p_elo
λ_vendës  = p_mix · (λ_vendës + λ_mysafir)
λ_mysafir = (1 − p_mix) · (λ_vendës + λ_mysafir)
```

Pesha e Elo-s është **dinamike**: kur ka formë reale të mjaftueshme (≥ 5 ndeshje),
`w_elo = 0.30` (besohet më shumë forma); ndryshe `w_elo = 0.50`. Në fund, λ kufizohet
(clamp) në intervalin `[0.25, 3.30]` për qëndrueshmëri.

---

## 5. Hapi 4 — Modifikatorët specifikë të WC 2026

Mbi λ-të aplikohen tre rregullime kontekstuale:

- **Avantazhi i vendit:** +8% λ për SHBA / Meksikë / Kanada kur luajnë në qytetet e tyre pritëse.
- **Lodhja nga udhëtimi:** −5% λ (−7% për fluturime > 4500 km) kur një ekip udhëton ≥ 3000 km mes ndeshjeve.
- **Rotacioni (Matchday 3):** −12% λ kur ekipi tashmë ka 6 pikë (i kualifikuar) dhe pritet të pushojë titullarët.

---

## 6. Hapi 5 — Modeli Dixon-Coles

Poisson-i bazë i trajton golat e dy ekipeve si plotësisht të pavarur dhe **nënvlerëson**
rezultatet me pak gola (0-0, 1-0, 0-1, 1-1). Dixon-Coles shton një faktor korrigjimi τ
vetëm për këto katër rezultate:

```
P(x,y) = Poisson(x | λ) · Poisson(y | μ) · τ(x,y,λ,μ,ρ)

τ = 1 − λμρ   (0,0)      τ = 1 + μρ   (1,0)
    1 + λρ    (0,1)          1 − ρ     (1,1)        ρ = −0.13
```

Ndërtohet matrica e plotë e skorit (0–7 gola për ekip), normalizohet që shuma të jetë 1,
dhe mblidhet në probabilitetet finale:

```
P(1) = Σ ku x > y      P(X) = Σ ku x = y      P(2) = Σ ku x < y
```

---

## 7. Hapi 6 — Vendimi

**Parashikimi i shfaqur** është thjesht *favoriti i modelit* — rezultati me probabilitetin
më të lartë mes `1/X/2`. Kjo është ajo që shfaqet në Telegram (vetëm rezultati).

**Value bets** (opsionale, për bast) llogariten veçmas:

```
EV    = p · koeficient − 1                       # > 0 → fitimprurës afatgjatë
Kelly: f* = (p·b − q)/b,  b = koef − 1,  q = 1−p   # Quarter Kelly (×0.25), tavan 20%
```

Me **filtra anti-longshot** për të gjitha ndeshjet: injoron "vlerën" kur kuota > 6.0 ose
probabiliteti < 15% (te bishti vlerësimi i modelit është i pasigurt — kjo shmang baste si
"Curaçao kundër Gjermanisë").

---

## 8. Shembull i plotë numerik — Brazil vs Haiti

| Hapi | Vlera |
|------|-------|
| Mesatarja e ligës | shënuar 1.529, pësuar 1.118 |
| Tabela bazë | Brazil (2.8, 0.6) · Haiti (0.6, 2.1) |
| Forcë e tkurrur | Brazil: sulm 1.416, mbrojtje 0.768 · Haiti: sulm 0.696, mbrojtje 1.439 |
| λ bazë (× MU) | λ_Brazil = 2.751 · λ_Haiti = 0.722 |
| Elo | Brazil 1978, Haiti 1520 → p_elo = 0.933 ; p_pois = 0.792 ; p_mix = 0.863 |
| λ pas Elo + clamp | λ_Brazil = 2.996 · λ_Haiti = 0.477 |
| **Dixon-Coles** | **1 = 86.4% · X = 10.7% · 2 = 2.9%** — skori më i mundshëm **2-0** |

Parashikimi i shfaqur: **1 (Brazil)**.

---

## 9. Prezantimi në Telegram

Boti dërgon dy mesazhe:

1. **Lista e plotë** — çdo ndeshje me favoritin (`1/X/2`).
2. **"PARASHIKIMET MË TË SIGURTA"** — 5 ndeshjet ku modeli është më i bindur, vetëm rezultati
   (pa probabilitet, pa koeficient).

Çdo probabilitet kalon nga një normalizues që e mban në [0,100]% (mbron nga gabime shkalle
si "7569%").

---

## 10. Vlerësimi i saktësisë

Mjeti `backtest.py` ekzekuton modelin mbi ndeshje të mbaruara dhe llogarit Accuracy, Brier
score dhe log-loss, gjithmonë kundër një baze naive (1/3 për secilin). `fetch_results.py`
mbledh rezultate reale nga API-Sports.

Në back-testin mbi **26 ndeshje reale të WC 2022**: **Accuracy 61.5%**, Brier 0.563 (vs 0.667
naive), log-loss 0.982 (vs 1.099). Modeli e mund qartë bazën — pra shton vlerë reale
parashikuese. (Rastësia = 33%; basitsit profesionistë ~52–55%.)

---

## 11. Parametrat e konfigurueshëm (env / GitHub Secrets)

| Variabël | Default | Roli |
|----------|--------:|------|
| `STRENGTH_SHRINK` | 0.50 | sa tkurren forcat drejt mesatares (më i lartë = më ekstreme) |
| `MU_GOALS` | 1.35 | gola mesatarë për ekip (baza e λ-së) |
| `ELO_BLEND_WEIGHT` | 0.50 | pesha e Elo-s kur s'ka formë reale |
| `ELO_WEIGHT_LIVE` | 0.30 | pesha e Elo-s kur ka ≥ 5 ndeshje reale |
| `MIN_LIVE_MATCHES` | 5 | pragu për të kaluar te pesha "live" e Elo-s |
| `PRIOR_MATCHES` | 4 | sa peshon tabela kundër formës live (përzierja Bayes) |
| `DECAY_HALF_LIFE_DAYS` | 180 | gjysmë-jeta e rënies kohore (shtresa dinamike xG) |
| `VALUE_MAX_ODD` | 6.0 | tavani i kuotës për value bets |
| `VALUE_MIN_PROB` | 0.15 | probabiliteti minimal për një bast |

---

## 12. Kufizimet aktuale dhe hapat e mëtejshëm

- **xG live nuk e ushqen ende modelin e botit.** Shtresa `dynamic_data.py` (xG nga API-Sports
  me rënie half-life) ekziston dhe çelësi është i konfiguruar, por rruga e prodhimit
  (`send_predictions → build_model_dataframe → predict`) përdor formën e golave + tabelën, jo xG.
  Lidhja e `get_dynamic_stats` do të ishte përmirësimi tjetër logjik.
- **ρ (Dixon-Coles) është fiks (−0.13).** Idealisht kalibrohet nga të dhënat historike.
- **Elo-t janë statike** (vlerësim i Qershorit 2026), nuk përditësohen pas ndeshjeve.
- **Vlerësimi forward** është prova përfundimtare: ndërsa luhet WC 2026, mblidh rezultatet me
  `fetch_results.py` dhe ri-xhiro `backtest.py` për saktësinë reale, pa lookahead bias.

Hapi me ndikimin më të madh tani: lidhja e xG-së live + matja me back-test forward për të
parë nëse ul Brier-in.
