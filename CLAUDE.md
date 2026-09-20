# autodrafter

Proiect universitar la algoritmi: optimizarea fazei de draft în Dota 2
(Captain's Mode), formalizată ca joc secvențial de sumă nulă cu informație
perfectă, cu ~10³⁰ stări accesibile.

Contribuția evaluată este **compararea controlată a algoritmilor de căutare**
(greedy, alfa-beta, MCTS) și măsurarea abaterii lor față de optimul exact pe o
instanță redusă — nu predicția rezultatului meciului. Planificarea completă e
în `docs/01`…`docs/10`; starea curentă, cifrele și deciziile deschise: `docs/11-stare-si-decizii.md`.

## Comenzi

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn autodrafter.server:app --reload      # http://127.0.0.1:8000
pytest tests -q                              # 102 de teste

# modelul: meciuri brute -> data/model.npz (se rulează local, durează ore la 250k)
python -m autodrafter.etl.fetch_publicmatches --count 250000 --min-rank 50
python -m autodrafter.etl.build_model

# banc de testare al funcției de evaluare (vezi benchmark/README.md)
python -m benchmark.evaluate && python -m benchmark.report
```

`etl/fetch_opendota.py` (β din `heroStats`, counter din `/matchups`) e ÎNVECHIT: are un defect
măsurat, descris în docstring-ul lui. Rămâne în repo ca istorie metodologică.

Fără `data/model.npz`, aplicația pornește pe un model placeholder — numere
inventate, cu structură realistă. Interfața avertizează explicit.

## Invarianta care nu se încalcă

**Căutarea nu știe nimic despre calitatea eroilor. Modelul nu știe nimic
despre ordinea acțiunilor.**

- `game.py` — stare, ordinea CM, mutări legale. Zero evaluare.
- `model.py` — β, counter, synergy, `score()`. Zero logică de joc.
- `search/` — greedy, alfa-beta, MCTS. Consumă toate **aceeași** funcție de
  evaluare.

Dacă logica de evaluare ajunge în `game.py`, diferențele măsurate între
algoritmi nu mai sunt atribuibile căutării, iar comparația — care este tot
proiectul — devine invalidă.

Orice îmbogățire a modelului (abilități, sinergii, jucători) se face în
`model.py`, fără să se atingă `search/`.

## Convenții

- Comentariile din cod și `docs/` sunt în română.
- Numerele despre eroi nu se scriu niciodată în cod — stau în `data/`,
  generate de `etl/`, versionate pe patch.
- Ponderile modelului se estimează prin regresie pe meciuri reale, nu se aleg
  de mână.
- **Toate componentele modelului (β, counter, synergy, avantajul de partidă) vin din ACELEAȘI
  meciuri brute.** Amestecarea surselor a produs un model mai rău decât o monedă
  (counter calculat față de un β din altă sursă). `counter` și `synergy` se centrează
  obligatoriu (fără nivel de erou), iar `build_model.py` se oprește dacă
  |corr(sumele pe rânduri, β)| ≥ 0.15.
- Împărțirea train/test e CRONOLOGICĂ (80/20 după `start_time`), niciodată aleatoare;
  `benchmark/` exclude orice meci anterior hold-out-ului din meta modelului.
- `DraftModel.side_advantage` NU se adună în `score()`: o constantă nu schimbă niciun argmax
  de draft. Se folosește doar la predicția meciurilor reale (în `benchmark/`).
- Fișierele de date mari nu intră în repo; se descarcă prin `etl/` și stau în
  `.gitignore`.
- Ordinea fazelor din `game.py` (`_SCHEDULE`) trebuie verificată față de
  patch-ul curent înainte de a raporta rezultate.

## Documentație de bibliotecă

Pentru FastAPI, numpy, pytest și altele folosește **Context7**, configurat în
`.mcp.json` la rădăcina proiectului.
