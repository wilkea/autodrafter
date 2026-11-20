# benchmark — cât de bun e raterul

Compară predicțiile modelului din `data/model.npz` cu rezultatul unor meciuri reale
și arată unde greșește. Nu modifică nimic din `autodrafter/`.

```bash
python -m autodrafter.etl.fetch_publicmatches --count 250000 --min-rank 50   # meciurile brute
python -m autodrafter.etl.build_model                                        # -> data/model.npz
python -m benchmark.evaluate                      # metrici + baze -> results/<timp>.json
python -m benchmark.report                        # raport -> results/<timp>.md
pytest tests -q
```

- Un model construit de `build_model.py` are în meta un **hold-out cronologic** (ultimele
  20% din meciuri). `evaluate` citește implicit `data/raw_matches/` și **exclude orice meci mai
  vechi decât începutul hold-out-ului**: ar fi putut fi în antrenare. Modelul vechi (din
  `heroStats`) nu are hold-out și se testă pe `benchmark/data/` (`benchmark.fetch_matches`).
- `evaluate --model M --holdout-of N` testează modelul `M` pe hold-out-ul modelului `N`:
  comparație pe **aceleași meciuri**, cum trebuie ca „înainte/după” să însemne ceva.
- `evaluate` testează doar meciurile **ranked** (`--subset all` pentru toate); `--since` /
  `--until` (YYYY-MM-DD) taie o fereastră de timp.
- Avantajul de partidă al modelului (`side_advantage`) se adaugă la predicție aici, nu în `score()`.
- `report` compară automat cu rezultatul anterior din `results/`. Rapoartele `.md` se
  versionează; fișierele `.json` nu. Verdictul e prima frază; modelul trebuie să bată **și**
  predicția constantă 0.5, **și** baza „avantajul Radiant”, altfel raportul spune că nu are valoare.

**Limită:** meciurile vin din aceeași zi (`publicMatches` întoarce mereu cele mai recente),
deci un rezultat de aici nu spune ce se întâmplă în alte zile sau patch-uri.
