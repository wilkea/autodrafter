# 10. Prototipul — arhitectură și mod de rulare

Prototipul implementează Captain's Mode complet (24 de acțiuni), jucător
împotriva algoritmului, cu alegerea părții (First Pick / Second Pick).

## 10.1 Rulare

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn autodrafter.server:app --reload                # http://127.0.0.1:8000
```

Teste: `pytest tests -q` (20 de teste).

### Date reale

La prima pornire se folosește un **model placeholder** — numere inventate, cu
structură realistă, fără valoare predictivă. Interfața avertizează explicit.
Pentru datele reale:

```bash
python -m autodrafter.etl.fetch_publicmatches --count 250000 --min-rank 50   # meciuri brute
python -m autodrafter.etl.build_model                                        # -> data/model.npz
```

`build_model` scrie `data/model.npz`, pe care serverul îl încarcă automat la repornire.
Colectarea durează ore (≈2500 de cereri, pauză de 1,5 s, cota zilnică OpenDota); e
reluabilă. Toate componentele (β, avantajul de partidă, counter, synergy) vin din
**aceleași meciuri**, antrenate pe cele mai vechi 80% după `start_time`; ultimele 20% rămân
nevăzute pentru `benchmark/`. Opțional `--api-key` ridică limita OpenDota.

> Vechiul `fetch_opendota.py` (β din `heroStats`, counter din `/matchups`) a produs un
> model mai rău decât o monedă: counter era reziduu față de un β din altă sursă și
> anula semnalul. Defectul a fost găsit de `benchmark/`; vezi docstring-ul acelui fișier.

> `api.opendota.com` nu este accesibil din orice mediu de execuție — scriptul
> se rulează local.

## 10.2 De ce această structură

Regula centrală (doc 01 §1.5): **motorul de joc nu știe nimic despre
calitatea eroilor, iar modelul nu știe nimic despre ordinea acțiunilor.**

```
autodrafter/
  heroes.py      catalogul celor 127 de eroi, indici interni stabili 0..n-1
  game.py        stare imuabilă, ordinea CM, mutări legale — ZERO evaluare
  model.py       funcția de evaluare: β, counter, synergy + score()
  search/        greedy.py · alphabeta.py · mcts.py — consumă același model
  etl/           fetch_publicmatches.py + build_model.py (date reale) · placeholder.py
                 · fetch_opendota.py (ÎNVECHIT, păstrat ca istorie)
  session.py     partida: adversarul algoritmic, cronometrele, jurnalul
  server.py      API-ul FastAPI + servirea interfeței
web/             interfața (HTML/CSS/JS, fără pas de build)
data/            heroes.json (versionat) · model.npz (generat, neversionat)
tests/           102 de teste
benchmark/       banc de testare al funcției de evaluare (vezi benchmark/README.md)
```

Consecințe practice:

- schimbi algoritmul fără să atingi evaluarea, și invers — exact experimentul
  controlat de care are nevoie capitolul de comparație;
- `data/model.npz` se regenerează la fiecare patch, fără modificări de cod;
- aceiași algoritmi din `search/` vor alimenta și experimentele offline
  (turneul, abaterea de la optim), nu doar interfața.

## 10.3 Cele două faze, concret

| | offline (o dată per patch) | online (la fiecare tură) |
|---|---|---|
| ce rulează | `fetch_publicmatches.py` + `build_model.py` | `search/*.py` |
| intrare | ~10⁵ meciuri brute ranked | starea curentă a draftului |
| ieșire | `model.npz`: β (n), counter (n×n), synergy (n×n), avantaj de partidă | eroul recomandat |
| durată | ore (colectare) + secunde (construcție) | 0,2 ms – 0,6 s |
| de câte ori | 1 | 24 |

Măsurat pe placeholder, la o stare de mijloc de draft:

| algoritm | timp | evaluări | observații |
|---|---|---|---|
| greedy | 0,2 ms | 127 | o evaluare per erou legal |
| alfa-beta (d=4, K=10) | ~9 ms | ~4.000 | factor de ramificare efectiv ≈ 2,9 față de K=10 |
| MCTS (800 iterații) | ~480 ms | ~270.000 | anytime; calitatea crește cu iterațiile |

Factorul de ramificare efectiv de ~2,9 la K=10 confirmă empiric că retezarea
alfa-beta cu ordonare bună se apropie de O(K^(d/2)) — un rezultat direct
raportabil (doc 02 §2.2).

## 10.4 Limitări cunoscute ale prototipului

1. **Sinergia este zero** în modelul real. API-ul OpenDota expune doar meciuri
   contra unui erou (`/matchups`), nu perechi în aceeași echipă; acestea
   necesită interogări `/explorer` SQL. Termenul există deja în formulă și în
   structura de date — rămâne doar alimentat cu date.
2. **Ordinea exactă a fazelor CM** din `game.py` este cea asimetrică din 7.34
   (ban-uri 3-2-2 pentru FP și 4-1-2 pentru FB, pick-uri 1-3-1, faze de
   7/2/3/6/4/2 acțiuni), preluată de la dotapicks.com pentru că sursele
   oficiale nu au putut fi accesate. Trebuie verificată față de patch-ul curent
   înainte de a raporta rezultate. Este izolată într-o singură listă
   (`_SCHEDULE`), tocmai ca modificarea să fie trivială.
3. **Cronometrele nu sunt impuse de server** — sunt afișate în client, iar la
   expirare se confirmă automat prima recomandare. Pentru experimente
   riguroase, timpul trebuie mutat pe server.
4. **Sesiunile sunt în memorie** (ultimele 32). O repornire le pierde.
5. **Portretele eroilor** se încarcă de pe CDN-ul Steam; fără internet, grila
   rămâne funcțională, dar fără imagini.
