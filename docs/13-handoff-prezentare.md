# 13. Handoff — context pentru sesiunea locală (prezentare 20.11.2026)

Acest document transferă contextul unei sesiuni de lucru din cloud către o
sesiune locală, care are acces la discurile PC-ului (PDF-ul de prezentare e pe
`F:\tg desk\AutoDrafter_Prezentare_7min.pdf`, inaccesibil din container).

Toate cifrele de aici sunt recalculate din datele comise în repo
(`experiments/results/`, `benchmark/results/`, metadatele din `data/model.npz`)
la 20.11.2026. Nu sunt din memorie.

---

## 13.1 Sarcina imediată

1. Citește `F:\tg desk\AutoDrafter_Prezentare_7min.pdf`.
2. Convertește-l în markdown, cu structura pe slide-uri păstrată.
3. **Sincronizează fiecare cifră** din el cu §13.4–§13.6 de mai jos și
   raportează explicit: ce se confirmă, ce e depășit, ce lipsește.

Două erori de verificat prioritar, fiindcă au apărut în materiale anterioare:

- **numărul de componențe finale este 2,42 × 10³⁴**, nu 10³⁰ (greșeală de patru
  ordine de mărime, prezentă încă în `CLAUDE.md` și `docs/01-problem.md`);
- **datele acoperă o singură zi**, nu „ultimele 2 luni”.

---

## 13.2 Încadrarea proiectului (formularea convenită)

Contribuția evaluată **nu** este predicția rezultatului meciului și **nu** este
un model complet al mecanicii jocului — ultimul a fost declarat nerealizabil și
scos din scop în mod deliberat.

Funcția de evaluare devine **variabilă experimentală**, iar întrebarea de
cercetare este: **cum depinde clasamentul algoritmilor de structura
evaluatorului.**

Formularea care susține prezentarea: pe instanța redusă adâncimea plătește
masiv; pe instanța completă, cu același evaluator aditiv, aproape deloc. Cauza
nu e o deficiență de implementare, ci faptul că **un evaluator aditiv nu
conține tactică, deci adâncimea nu are ce descoperi**: câștigul marginal al
unui erou nu depinde de ordinea în care e luat. De aici predicția testabilă: un
evaluator neliniar (cu poziții, cu concurență pentru resurse) ar inversa
concluzia.

## 13.3 Invarianta care justifică întregul proiect

`game.py` — stare, ordinea CM, mutări legale. Zero evaluare.
`model.py` — β, counter, synergy, `score()`. Zero logică de joc.
`search/` — toți algoritmii consumă **aceeași** funcție de evaluare.

Dacă evaluarea ajunge în logica de joc, diferențele măsurate între algoritmi nu
mai sunt atribuibile căutării, iar comparația — care este tot proiectul —
devine invalidă.

---

## 13.4 Modelul: ce avem, din ce

Totul din `data/model.npz` (216 KB, versionat ca excepție deliberată).

| | |
|---|---|
| sursă | OpenDota `publicmatches`, ranked, `avg_rank_tier >= 50` |
| antrenare | 128.965 meciuri, 20.09.2026 04:33 → 14:28 UTC |
| hold-out cronologic | 32.244 meciuri, 14:28 → 16:47 UTC |
| regularizare | `l2_C` 0,02 · `k_counter` 1000 · `k_synergy` 3000 |
| AUC | **0,607** [0,602, 0,613] |
| pantă de calibrare | **1,02** [0,96, 1,07]; intercept +0,017 [−0,007, 0,040] |
| avantaj de partidă | +0,1221 log-odds (Radiant 53,0%); **nu** intră în `score()` |
| verificare centrare | corr(sume pe rânduri, β) = 0,0 pentru counter și synergy (înainte: 0,4856 și 0,7923) |

Structura: un vector de 127 + două matrici 127×127 = **32.385 de numere**.
`S = Σβ(noi) − Σβ(ei) + Σsyn(noi) − Σsyn(ei) + Σcnt(noi × ei)`, `P = σ(S)`.

Pe componente, AUC: β 0,593 · counter 0,558 · sinergie 0,523 · complet 0,607.

**Din D2PT nu s-au tras niciodată date.** Singura apariție în repo este
`docs/12-roadmap-model.md:13`: două cifre citite manual de pe site, pentru un
singur draft, folosite ca diagnostic. Nu există scraper și nu există dataset.
Dacă se întreabă de unde vin datele, răspunsul este OpenDota.

## 13.5 E1 — instanța redusă, singurul experiment cu adevăr de referință

12 eroi, 10 acțiuni (2 ban-uri + 3 pick-uri pe echipă, tipar CM), rezolvată
exact prin inducție inversă: 765.019 stări, 8,2 s, solver separat pe măști de
biți, deci independent de codul căutării. Regret în puncte procentuale,
0 = mutare optimă. Rulare comisă: `--pools 30 --states 10`.

| configurație | regret pp | mutări optime | ms | evaluări |
|---|---|---|---|---|
| mutare aleatoare (bază) | 2,939 | — | — | — |
| greedy / SCM | 0,574 | 63,3% | 0,11 | 8 |
| alfa-beta K=3 d=2 | 0,489 | 67,3% | 0,36 | 32 |
| alfa-beta K=3 d=4 | 0,227 | 78,0% | 1,21 | 122 |
| alfa-beta K=12 d=4 | 0,207 | 80,8% | 7,5 | 682 |
| alfa-beta K=12 d=full | 0,021 | 96,3% | 217 | 15.413 |
| **alfa-beta K=12 d=full, TT corect** | **0,000** | **100%** | 269 | 20.134 |
| MCTS 50 it | 1,358 | 42,4% | 10,2 | 967 |
| MCTS 200 it | 0,530 | 61,6% | 37,7 | 3.263 |
| MCTS 800 it | 0,393 | 67,8% | 136 | 11.057 |
| MCTS 3200 it | 0,332 | 70,6% | 472 | 35.800 |

Atingerea optimului exact (0,000 / 100%) de către alfa-beta cu tabelă de
transpoziții corectă validează implementarea.

## 13.6 E2 și turneul — instanța completă

E2: 127 eroi, 24 acțiuni. **Nu există adevăr de referință**; se măsoară doar
cost și stabilitate.

| configurație | ms | noduri | evaluări | adâncime | EBF |
|---|---|---|---|---|---|
| greedy / SCM | 0,1 | 114 | 114 | — | — |
| alfa-beta K=10, d=2 | 0,8 | 52 | 1.184 | 2,00 | 6,79 |
| alfa-beta K=10, d=6 | 72,7 | 3.612 | 125.559 | 6,00 | 3,37 |
| alfa-beta K=10, 100 ms | 65,9 | 4.161 | 155.246 | 7,48 | 4,20 |
| alfa-beta K=10, 500 ms | 305,9 | 16.461 | 610.733 | 8,84 | 3,51 |
| alfa-beta K=10, 2000 ms | 1.139 | 56.393 | 2.038.159 | 9,48 | 3,50 |
| MCTS 400 it | 87,8 | 337 | 73.022 | — | — |
| MCTS 6400 it | 1.293 | 5.137 | 1.053.431 | — | — |

EBF 3,5–4,2 la K=10, adică ușor peste √K: retezarea funcționează, dar nu ideal.

Acordul mutării alese (50 de poziții), dovada că adâncimea nu descoperă nimic
pe instanța completă:

| | acord |
|---|---|
| greedy vs alfa-beta d=2 | 88% |
| alfa-beta d=2 vs d=6 | 70% |
| alfa-beta d=6 vs 2000 ms | 84% |
| alfa-beta d=2 vs 2000 ms | **62%** |
| greedy vs alfa-beta 2000 ms | 60% |
| greedy vs MCTS 6400 it | 38% |

Turneu self-play, 180 de drafturi, 20 de deschideri, ambele poziții:

| | scor așteptat | |
|---|---|---|
| alfa-beta vs greedy | **0,5301** ± 0,0025 | alfa-beta mai bun |
| alfa-beta vs MCTS | **0,5227** ± 0,0056 | alfa-beta mai bun |
| greedy vs MCTS | 0,5071 ± 0,0066 | practic egali |

**Limita se declară din proprie inițiativă:** scorul este P(FP câștigă) măsurat
cu *același* evaluator pe care algoritmii îl optimizează — circular prin
construcție. E1 rămâne experimentul principal; turneul doar confirmă ordinea.

---

## 13.7 Terminologie: „greedy” nu e un nume de algoritm

Greedy este o *metodă* de proiectare, nu un algoritm. În propunerea de proiect
obiectivul a fost redenumit **SCM**, cu descrierea: „alege la fiecare etapă
acțiunea cu cel mai bun câștig imediat, fără anticiparea adversarului”.
Confirmat de utilizator ca fiind corect — SCM este exact varianta lacomă.

În cod denumirea veche a rămas: `autodrafter/search/greedy.py`
(`class GreedySearcher`, `name = "greedy"`) și cheile `greedy` din
`web/app.js` (`ALGO_LABEL`, `ALGO_TAG`) și `web/index.html` (un buton și două
`<option>`). Redenumirea locală a utilizatorului nu era încă pushată la
20.11.2026. De aliniat dacă se dorește coerență.

## 13.8 Limite de declarat explicit

- datele acoperă **o singură zi** (~10 h antrenare + 2,3 h test): `publicMatches`
  întoarce mereu cele mai recente meciuri, iar banca nu expune încă
  `less_than_match_id`;
- modelul **nu are noțiunea de poziție**: un draft generat primește 63% de la
  model și 30,7% de la D2PT; aceiași 10 eroi cu poziții reatribuite trec de la
  69/31 la 53/47 — **16 puncte doar din atribuirea rolurilor**;
- aditivitatea nu poate reprezenta concurența pentru resurse (farm-ul e o
  proprietate a întregii mulțimi și e supra-aditivă);
- draftul explică 40–50% din rezultatul meciului; restul e execuție;
- algoritmul ungar și CFR sunt direcții planificate, **nu** implementate.

## 13.9 Comenzi

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
pytest tests -q                              # 106 teste
uvicorn autodrafter.server:app --reload      # http://127.0.0.1:8000

python -m experiments.search_benchmark e1 --pools 120 --states 20 --workers 4
python -m experiments.search_benchmark e2 --states 15
python -m experiments.search_benchmark tournament --openings 100 --workers 1
```

**`--workers` falsifică turneul și E2.** În `PLAYERS` alfa-beta rulează cu
`time_budget_ms: 500`, deci adâncimea atinsă depinde de ceas: cu mai multe
procese pe aceleași nuclee ajunge mai puțin adânc și rezultatul se schimbă. De
aceea rulările comise au `workers: 1`. E1 este imun, fiindcă acolo adâncimile
sunt fixe (`d=2`, `d=4`, `d=full`); semințele sunt per-task, deci E1 e
reproductibil indiferent de paralelism.

**Nu reconstrui `data/model.npz`.** `build_model.py` ar produce alte ponderi,
iar raportul de benchmark comis (AUC 0,607, pantă 1,02) nu ar mai corespunde
modelului. Experimentele de căutare folosesc modelul ca pe o constantă, exact
cum trebuie.

## 13.10 Starea verificată la 20.11.2026

Branch `claude/dota-draft-algorithm-plan-fqv8x8`, commit `394b355`, nimic
nepushat. **106 teste trec.** Serverul pornește, `/api/meta` întoarce catalogul
real de 127 de eroi — nu placeholder-ul.

## 13.11 Întrebările probabile și răspunsurile

1. *De unde știi că algoritmul e bun, nu doar modelul?* — E1, regret față de
   optimul exact; modelul e constant între algoritmi (§13.3).
2. *De ce nu MCTS?* — Măsurat: 472 ms pentru 0,332 pp, față de 1,21 ms pentru
   0,227 pp. Pe un evaluator aditiv rollout-urile nu adaugă informație.
3. *AUC 0,607 nu e mic?* — Draftul explică 40–50% din rezultat, iar panta de
   calibrare 1,02 arată că încrederea modelului e reală.
4. *La ce folosește inducția inversă dacă nu scalează?* — Instrument de măsură,
   nu de producție: fără ea „alfa-beta e mai bun” ar fi o impresie, cu ea este
   0,000 față de 0,574 pp.

## 13.12 Rămas deschis

- corectarea 10³⁰ → 2,42 × 10³⁴ în `CLAUDE.md` și `docs/01-problem.md`;
- butoane de ieșire din draft / revenire în menu (TODO al utilizatorului);
- poziția și algoritmul ungar în `model.py` (pasul real următor, blochează CFR);
- CFR pe instanța redusă (direcție).
