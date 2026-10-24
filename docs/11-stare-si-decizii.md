# 11. Stare și decizii deschise

_Instantaneu la 2026-09-20. Cifrele vin din `benchmark/results/*.md` și din `meta`-ul
`data/model.npz`; nu le rescrie de mână, regenerează-le cu comenzile din `CLAUDE.md`._

## 11.1 Ce există

| componentă | stare |
|---|---|
| Motor Captain's Mode (`game.py`) | 24 de acțiuni, ordinea asimetrică 7.34+ (ban 3-2-2 / 4-1-2, pick 1-3-1). **Sursa ordinii e neoficială** (dotapicks.com), vezi 11.3 |
| Algoritmi (`search/`) | greedy, alfa-beta, MCTS; toți consumă aceeași funcție de evaluare |
| Interfață web + „draft instant" | jucător vs algoritm, sau doi algoritmi joacă ambele părți; modal „Vezi draftul" |
| Model (`model.py`, `etl/`) | β + avantaj de partidă + counter + synergy, toate din **aceleași meciuri brute** |
| Banc de testare (`benchmark/`) | metrici pe meciuri nevăzute, baze de comparație, raport în română, comparație între rulări |
| Teste | 102 (`pytest tests -q`) |

## 11.2 Rezultate măsurate

**Modelul vechi** (β din `heroStats`, counter din `/matchups`) era mai rău decât o monedă.
Cauza (`etl/fetch_opendota.py`, avertisment în docstring): counter era reziduu față de un β din
ALTĂ sursă, deci conținea un nivel de erou de semn opus lui β și îl anula.

Același hold-out cronologic de 32.244 de meciuri ranked (14:28 → 16:47 UTC), niciunul văzut la antrenare:

| | model vechi | model nou | constant 0.5 | avantaj Radiant |
|---|---|---|---|---|
| log-loss | 0,7173 | **0,6728** | 0,6931 | 0,6909 |
| AUC | 0,483 [0,477; 0,490] | **0,607 [0,602; 0,613]** | 0,500 | 0,500 |
| panta de calibrare | −0,14 | **1,02 [0,96; 1,07]** | | |

Pe componente (AUC, model nou): β 0,593 · counter 0,558 · synergy 0,523 · complet 0,607. Counter-ul
singur era 0,441 (anti-predictiv) în modelul vechi. Modelul nou bate ambele baze cu interval de
încredere care exclude 0. Rapoartele: `benchmark/results/20260920-212217.md` (vechi) și
`20260920-212246.md` (nou, cu comparația automată între ele).

**Date:** ~227.500 de meciuri scanate, 161.209 ranked cu `avg_rank_tier ≥ 50`, pe 12,2 ore
(04:33 → 16:47 UTC). Antrenare: primele 80% (128.965), hold-out: ultimele 20% (32.244), cu frontiera
între secunde distincte. Regularizarea (`l2_C` = 0,02, `k_counter` = 1000, `k_synergy` = 3000) s-a ales
pe o împărțire cronologică internă a antrenării; hold-out-ul nu a influențat nicio alegere (un test
verifică bit cu bit). Avantajul de partidă estimat: +0,122 log-odds (Radiant 53,0%; observat 53,3%).

Rata de păstrare la colectare a crescut de la 14% (cele mai noi pagini) la ~71% pe măsură ce
colectarea mergea în trecut: estimarea „40% ranked" din cerere nu s-a confirmat nici într-un sens,
nici în celălalt, deci `--count` se raportează în meciuri **scanate**.

## 11.3 Limite cunoscute

1. **O singură zi.** Antrenarea (10 ore) și testul (2,3 ore) sunt din aceeași zi; nu există nicio
   dovadă despre generalizarea peste zile sau patch-uri. `publicMatches` dă mereu cele mai noi
   meciuri; alte perioade cer un `less_than_match_id` ales manual, pe care colectorul nu îl expune.
2. **Ordinea de draft e neverificată oficial.** Liquipedia (403), Fandom (402) și dota2.com (JS) nu
   au putut fi citite; secvența vine de la dotapicks.com și se potrivește cu rezumatul din 7.34.
3. **Verificarea nivel-de-erou trece prin construcție.** După centrare, sumele pe rânduri sunt zero,
   deci corelația cu β e 0,000; testele arată că verificarea se declanșează dacă centrarea dispare.
   Valoarea informativă e cea dinainte de centrare (+0,49 counter, +0,79 synergy): regularizarea L2
   lasă nivelul eroilor în reziduuri, iar centrarea îl scoate (nu îl adaugă înapoi în β).
4. **Evaluatorul e validat doar ca predictor al meciului din 10 eroi**, nu pe drafturi parțiale și
   nu ca ghid pentru căutare. Contribuția proiectului rămâne compararea algoritmilor de căutare
   (`CLAUDE.md`); experimentele acelea (turneu, abaterea de la optim) nu au fost rulate cu modelul nou.
5. **Doar ranked ≥ Legend.** Modelul nu a fost testat pe rânduri mai joase sau pe alte moduri.
6. **Colectorul s-a oprit la 91%** dintr-o cursă pe Windows la scrierea atomică a `state.json`
   (reparat: reîncercări, cu test). Datele sunt intacte; `state.json` rămâne cu un lot în urmă, ceea
   ce e sigur (la reluare se rescanează câteva pagini, dedupe după `match_id`).
7. **Cod duplicat:** `parse_match`, `_get` și încărcătorul de loturi există și în `benchmark/fetch_matches.py`,
   și în `etl/fetch_publicmatches.py`.
8. **Nume înșelător:** `Side.FB` înseamnă acum „second pick" (numele vine din ordinea veche, în care
   banea prima); interfața spune „Second Pick".

## 11.4 Decizii deschise

- **Cât de larg colectăm?** Pentru mai multe zile trebuie un cursor `less_than_match_id` ales pe
  zile; cota gratuită e ~2500–3000 de cereri/zi (o colectare de 250k ≈ toată cota).
- **Merită counter/synergy complexitatea lor?** Complet 0,607 vs β singur 0,593 (ΔAUC ≈ +0,014,
  ΔLL ≈ −0,005). E câștig real și semnificativ, dar mic; de cântărit față de costul de mentenanță.
- **Ce facem cu nivelul de erou scos din counter/synergy?** Adăugat înapoi în β ar desface
  regularizarea aleasă prin validare; alternativa e o regularizare pe grupuri. Netestat.
- **Extensii din planul inițial** (`docs/08`): stratul semantic/abilități (E1), model de jucători (E2),
  iteme (E3). Niciuna nu a început.
- **Experimentele de căutare cu modelul nou:** turneul între algoritmi și abaterea de la optimul
  exact pe instanța redusă (C4, C5 din `docs/08`) sunt următorul pas al contribuției evaluate.
- **Curățenie:** unificarea codului duplicat (11.3 pct. 7), redenumirea `Side.FB`, verificarea ordinii
  CM pe o sursă oficială.

## 11.5 Reproducere

```bash
python -m autodrafter.etl.fetch_publicmatches --count 250000 --min-rank 50   # ore; reluabil
python -m autodrafter.etl.build_model                                        # secunde
python -m benchmark.evaluate && python -m benchmark.report
pytest tests -q
```
