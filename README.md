# autodrafter

Proiect universitar: **optimizarea fazei de draft în Dota 2 (Captain's Mode)**,
formalizată ca joc secvențial de sumă nulă cu informație perfectă și abordată
prin mai mulți algoritmi de aproximare, a căror calitate este măsurată față de
o instanță rezolvabilă exact.

## Stare

Prototip funcțional: Captain's Mode complet (24 de acțiuni, ordinea asimetrică 7.34+), jucător
împotriva algoritmului, cu alegerea părții (First Pick / Second Pick) și trei algoritmi
comutabili (greedy, alfa-beta, MCTS), plus un mod „draft instant" în care doi algoritmi joacă
ambele părți și rezultatul apare la final.

Modelul de evaluare se construiește din meciuri brute OpenDota (`etl/fetch_publicmatches.py` +
`etl/build_model.py`), cu împărțire cronologică 80/20. Pe 32.244 de meciuri nevăzute la
antrenare are AUC 0,607 și bate ambele baze de comparație; fără `data/model.npz` aplicația
pornește pe un model placeholder (numere inventate) și interfața avertizează. Cifrele, limitele și
deciziile deschise sunt în [`docs/11-stare-si-decizii.md`](docs/11-stare-si-decizii.md);
banca de testare e descrisă în [`benchmark/README.md`](benchmark/README.md).

## Rulare

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn autodrafter.server:app --reload      # http://127.0.0.1:8000
pytest tests -q                              # 102 de teste
```

Date reale (se rulează local, durează ore): `python -m autodrafter.etl.fetch_publicmatches --count 250000 --min-rank 50`
apoi `python -m autodrafter.etl.build_model`. Cât de bun e modelul: `benchmark/README.md`.

## Ideea în două fraze

Draftul are ~10³⁰ stări accesibile, deci căutarea exhaustivă este imposibilă și
problema devine „care algoritm de aproximare se apropie cel mai mult, la ce
cost". Căutarea este separată strict de evaluare, astfel încât algoritmii să
poată fi comparați pe aceeași funcție de evaluare — condiția care face
comparația validă.

## Documentație

| # | document | conținut |
|---|---|---|
| 01 | [Problema](docs/01-problem.md) | formalizare, spațiul stărilor, complexitate, separarea căutare/evaluare |
| 02 | [Algoritmi](docs/02-algorithms.md) | greedy, alfa-beta, MCTS, instanța rezolvabilă exact |
| 03 | [Modelul eroilor](docs/03-hero-model.md) | log-odds, regularizare, factorizare, vectori de capabilități |
| 04 | [Modelul jucătorilor](docs/04-player-model.md) | competență per erou, recență, stil de joc, algoritmul ungar |
| 05 | [Obiecte](docs/05-items.md) | acoperire maximă bugetată, garanția (1−1/e) |
| 06 | [Date și evaluare](docs/06-data-and-evaluation.md) | surse, împărțire cronologică, metrici, limite |
| 07 | [Lucrări similare](docs/07-prior-art.md) | literatura existentă și probleme analoage |
| 08 | [Plan](docs/08-roadmap.md) | scop, riscuri, calendar 12 săptămâni |
| 09 | [Parserul](docs/09-parser.md) | corectitudinea extragerii din fișierele jocului |
| 10 | [Prototipul](docs/10-prototip.md) | arhitectură, rulare, măsurători, limitări |
