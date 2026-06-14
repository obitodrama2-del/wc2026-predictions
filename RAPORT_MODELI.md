# Raport: Si funksionon llogaritja e parashikimeve — WC 2026

Ky shënim përshkruan hap-pas-hapi si sistemi kthen dy ekipe në probabilitete `1 / X / 2`,
një rezultat të mundshëm, dhe një sugjerim basti. Në fund ka një listë të prioritizuar
me çfarë mund të përmirësohet dhe pse.

---

## 1. Pamja e përgjithshme — rrjedha e të dhënave

Çdo parashikim kalon nga gjashtë faza:

```
TË DHËNAT  →  LAMBDA (λ)  →  MODIFIKATORËT WC  →  DIXON-COLES  →  EV/KELLY  →  TELEGRAM
   ▲             ▲                ▲                   ▲              ▲            ▲
 forma e     fuqia e        host / lodhje /      probabilitete   value bets   formatim
 ekipit      sulmit/        rotacion             1/X/2 + skor    + stake       + normalizim
 (xG/gola)   mbrojtjes                            
```

`λ` (lambda) është numri mesatar i golave që pritet të shënojë një ekip në atë ndeshje.
I gjithë modeli mbështetet te ky numër: nëse `λ` është i gabuar, gjithçka pas tij është e gabuar.

---

## 2. Hapi 1 — Të dhënat (nga vijnë numrat)

Sistemi ka tre burime, me përparësi nga lart-poshtë:

1. **API-Sports live (xG)** — `dynamic_data.py`. Merr 5–10 ndeshjet e fundit të ekipit
   dhe nxjerr "Expected Goals". Kjo është më e saktja sepse xG është më pak e zhurmshme
   se golat e thjeshtë.
2. **API-Sports live (gola)** — nëse plani nuk jep xG, përdor golat realë të të njëjtave ndeshje.
3. **Tabela statike `TEAM_STATS_BASE`** — `wc2026_group_predictions.py`. Çdo ekip ka tre vlera:
   `(gola_shënuar_mesatar, gola_pësuar_mesatar, pikë_për_ndeshje)`. Përdoret kur s'ka të dhëna live
   (p.sh. pa çelës API, ose para fillimit të turneut).

### Time decay (rënia kohore)
Kur përdoren të dhëna live, ndeshjet e vjetra peshojnë më pak se të rejat:

```
W(t) = e^(−α · t)        t = ditë nga ndeshja
α    = ln(2) / half_life
```

`half_life = 180 ditë` (parazgjedhje) do të thotë: një ndeshje 6 muaj e vjetër vlen
gjysmën e një ndeshjeje të sotme. Lambda përfundimtare është mesatarja e peshuar:

```
λ_sulm  = Σ(xG_shënuar_i · W_i) / Σ(W_i)
λ_mbrojtje = Σ(xG_pësuar_i · W_i) / Σ(W_i)
```

---

## 3. Hapi 2 — Ndërtimi i lambda-ve të ndeshjes

Kjo është pjesa më e ndjeshme. Për një ndeshje vendës (h) vs mysafir (a):

```
λ_h = sqrt(sulm_h × mbrojtje_a)      ← mesatare gjeometrike
λ_a = sqrt(sulm_a × mbrojtje_h)
```

Logjika: sa shënon vendësi varet nga sulmi i tij DHE mbrojtja e kundërshtarit.

### Peshimi me Elo (ndreqja e fundit)
Vetëm formula e mësipërme **e injoronte fuqinë relative** të ekipeve — kështu mbrojtjet
elite (0.4–0.6 gola/ndeshje) i shtypnin të gjitha lambdat te ~1.1 dhe favoriti mund të dilte
underdog. Tani rishpërndajmë epërsinë sipas renditjes Elo, duke mbajtur totalin e golave konstant:

```
p_elo  = 1 / (1 + 10^(−(Elo_h − Elo_a)/400))     # probabiliteti i vendësit sipas Elo
p_pois = λ_h / (λ_h + λ_a)                         # ç'thotë modeli aktual
p_mix  = (1 − w)·p_pois + w·p_elo                  # w = ELO_BLEND_WEIGHT = 0.6
λ_h    = p_mix · (λ_h + λ_a)
λ_a    = (1 − p_mix) · (λ_h + λ_a)
```

`w = 0.6` do të thotë: 60% fuqia Elo, 40% forma/golat e tabelës. E rregullueshme me
variablin `ELO_BLEND_WEIGHT`.

---

## 4. Hapi 3 — Modifikatorët specifikë të WC 2026

Mbi lambdat aplikohen tre rregullime (`prediction_engine_v2.py`):

- **Host advantage:** +8% λ për SHBA / Meksikë / Kanada kur luajnë në qytetet e tyre pritëse.
- **Lodhja nga udhëtimi:** −5% λ (−7% për fluturime ndërkontinentale > 4500 km) kur ekipi
  udhëton ≥ 3000 km mes ndeshjeve.
- **Rotacioni (Matchday 3):** −12% λ kur ekipi tashmë ka 6 pikë (i kualifikuar) dhe pritet
  të pushojë titullarët.

---

## 5. Hapi 4 — Modeli Dixon-Coles

Poisson-i bazë i trajton golat e dy ekipeve si plotësisht të pavarur, çka **nënvlerëson**
barazimet me pak gola (0-0, 1-1) dhe fitoret e ngushta (1-0, 0-1). Dixon-Coles shton një
faktor korrigjimi τ vetëm për këto katër rezultate:

```
P(x,y) = Poisson(x|λ) · Poisson(y|μ) · τ(x,y,λ,μ,ρ)

τ = 1 − λμρ   nëse (0,0)
    1 + μρ    nëse (1,0)
    1 + λρ    nëse (0,1)
    1 − ρ     nëse (1,1)
    1         ndryshe
```

Me `ρ = −0.13`, modeli ngre P(0-0) dhe P(1-1) dhe ul P(1-0)/P(0-1) — pikërisht ku
Poisson-i gabon. Ndërtohet një matricë 8×8 me probabilitetin e çdo rezultati, normalizohet
që shuma të jetë 1, dhe mblidhet në:

```
P(1) = Σ rezultatet ku x > y      P(X) = Σ ku x = y      P(2) = Σ ku x < y
```

---

## 6. Hapi 5 — Bastet me vlerë (EV + Kelly)

Për çdo treg krahasohet probabiliteti i modelit me koeficientin e basitsit:

```
EV = p · koeficient − 1            # > 0 → fitimprurës afatgjatë
Kelly:  f* = (p·b − q) / b         b = koeficient − 1,  q = 1 − p
stake = f* × 0.25                  # Quarter Kelly, me tavan 20%
```

Një ndeshje shënohet "value bet" nëse `EV ≥ 4%` dhe probabiliteti ≥ një prag minimal.

---

## 7. Hapi 6 — Prezantimi në Telegram

`telegram_notify.py` formaton listën, kombinimin më të mirë dhe value bets. Pas ndreqjes
së fundit, çdo probabilitet kalon nga `prob_frac()` që e normalizon në [0,1] pavarësisht
shkallës — kështu nuk shfaqen më vlera si "7569%" dhe probabiliteti i kombos është gjithmonë ≤100%.

---

## 8. Dobësitë aktuale dhe çfarë mund të përmirësohet

Renditur sipas ndikimit në saktësi (nga më i larti).

### Prioritet i lartë

**8.1 — Tabela statike `TEAM_STATS_BASE` është e pakalibruar.**
Vlerat si "Argentina 3.2 gola/ndeshje" janë të fryra dhe jo në një bazë të përbashkët
("kundër kundërshtarit mesatar"). Modeli mbahet vetëm sepse mbrojtjet e ulëta i kompensojnë.
*Përmirësim:* normalizo me një mesatare lige (μ ≈ 1.35 gola), pra `sulm = gola_shënuar/μ`,
`mbrojtje = gola_pësuar/μ`, dhe `λ_h = sulm_h × mbrojtje_a × μ`. Kjo është modeli standard
i pranuar dhe i bën numrat të krahasueshëm.

**8.2 — Të dhënat live nuk peshohen ndryshe nga statike.**
Kur ka formë reale (xG nga ndeshjet e fundit), Elo duhet të peshojë më pak; kur s'ka, më shumë.
Aktualisht `ELO_BLEND_WEIGHT` është fiks 0.6 për të dyja.
*Përmirësim:* ulë peshën e Elo-s automatikisht kur ka ≥5 ndeshje reale (p.sh. 0.35), rrite kur s'ka (0.7).

**8.3 — Avantazhi i fushës mungon për ndeshjet neutrale.**
Vetëm host-et marrin bonus. Por edhe në botëror, ekipi i "shtëpisë" në një ndeshje (apo me më
shumë tifozë) ka avantazh të vogël (~+0.2–0.3 gola). Mungon plotësisht.
*Përmirësim:* shto një avantazh bazë vendësi në λ_h, i kalibrueshëm.

### Prioritet i mesëm

**8.4 — `ρ` (Dixon-Coles) është i palëvizshëm (−0.13).**
Vlera ideale e ρ ndryshon sipas turneut/ligës dhe duhet vlerësuar nga të dhënat historike,
jo e fiksuar. *Përmirësim:* kalibroje ρ nga rezultatet reale (maksimizim i gjasave).

**8.5 — Elo-t janë të koduara dhe statike.**
`ELO_RATINGS` janë vlera afërsie të Qershorit 2026 dhe nuk përditësohen pas ndeshjeve.
*Përmirësim:* përditëso Elo-t pas çdo ndeshjeje (formula klasike Elo me K-factor), ose merri
nga një burim live.

**8.6 — Value bets ndjekin verbërisht EV-në.**
Modeli sugjeron baste te longshot-et kur s'pajtohet me basitsin, edhe pse aty gabimi i modelit
është më i madh. *Përmirësim:* shto një tavan koeficienti (p.sh. injoro EV te koef > 6–8) dhe
kërko një prag probabiliteti minimal më të lartë.

### Prioritet i ulët / cilësi

**8.7 — Pa kalibrim/validim historik.** S'ka asnjë test që mat sa mirë parashikon modeli
(p.sh. Brier score, log-loss) kundër rezultateve reale. Pa këtë, çdo "përmirësim" është hamendje.
*Përmirësim:* back-test mbi ndeshje të kaluara dhe ndiq metrikat me kalimin e kohës.

**8.8 — Emrat e ekipeve normalizohen pjesërisht.** Shtuam aliase, por çdo emër i ri nga API
që s'përputhet bie te 1500 (Elo) ose (1.2, 1.2) (statike) pa paralajmërim.
*Përmirësim:* logo një paralajmërim kur një ekip bie te vlerat default.

---

## 9. Përmbledhje — ku të fokusohesh i pari

Nëse do një hap të vetëm me ndikimin më të madh: **8.1 (kalibrimi i tabelës me mesatare lige)**
bashkë me **8.2 (peshë dinamike Elo)**. Këto dy e bëjnë λ-në — themelin e gjithçkaje — shumë më
realiste. Pas tyre, **8.7 (back-test)** të jep një mënyrë objektive për të matur çdo ndryshim
të ardhshëm, në vend që të gjykosh "me sy".
