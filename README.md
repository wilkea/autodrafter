# autodrafter

Proiect universitar: **optimizarea fazei de draft în Dota 2 (Captain's Mode)**,
formalizată ca joc secvențial de sumă nulă cu informație perfectă și abordată
prin mai mulți algoritmi de aproximare, a căror calitate este măsurată față de
o instanță rezolvabilă exact.

## Stare

Prototip funcțional: Captain's Mode complet (24 de acțiuni), jucător împotriva
algoritmului, cu alegerea părții (First Pick / First Ban) și trei algoritmi
comutabili. Modelul de evaluare rulează implicit pe date placeholder; datele
reale se obțin cu scriptul de colectare OpenDota.

## Rulare

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn autodrafter.server:app --reload      # http://127.0.0.1:8000
pytest tests -q                              # 20 de teste
```

Date reale (se rulează local): `python -m autodrafter.etl.fetch_opendota --bracket high`

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
