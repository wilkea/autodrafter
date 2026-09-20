"""Construiește modelul din meciuri brute, într-o singură trecere, dintr-o SINGURĂ sursă.

    python -m autodrafter.etl.fetch_publicmatches --count 250000 --min-rank 50
    python -m autodrafter.etl.build_model

Toate componentele vin din aceleași meciuri (data/raw_matches/), spre deosebire de
vechiul `fetch_opendota.py`, unde β venea din `heroStats` și victoriile din
`/matchups` — vezi avertismentul din acel fișier.

  a) β și avantajul de partidă ÎMPREUNĂ, prin regresie logistică L2 pe indicatori:
     +1 pentru fiecare erou din Radiant, −1 pentru fiecare din Dire. Interceptul
     este avantajul de partidă al lui Radiant (nu intră în score(); vezi model.py).
  b) counter și synergy, din ACELEAȘI meciuri, ca reziduuri după β (și după intercept):
     pentru fiecare pereche, Σ(y − p) / Σ p(1−p) — un pas de scor Fisher, adică
     deplasarea de log-odds care ar corecta predicția pe meciurile ce conțin perechea.
     Regularizate cu `shrink` după numărul de observații; antisimetrie pentru
     counter, simetrie pentru synergy.
  c) centrate: se scad mediile pe rânduri și pe coloane, ca termenii să conțină NUMAI
     interacțiuni pereche-cu-pereche, nu un nivel de erou.
  d) verificare care OPREȘTE execuția: |corr(sumele pe rânduri, β)| < 0.15.
  e) împărțire CRONOLOGICĂ: primele 80% din meciuri (după start_time) antrenează,
     ultimele 20% rămân nevăzute pentru `benchmark/`. Regularizarea (C, k) se alege
     pe o împărțire cronologică INTERNĂ a celor 80%, deci hold-out-ul nu e atins.
  f) data/model.npz cu meta completă.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import sparse
from sklearn.linear_model import LogisticRegression

from autodrafter.etl.fetch_publicmatches import RAW_DIR, load_matches, wanted
from autodrafter.heroes import load_catalog
from autodrafter.model import DraftModel, default_model_path, shrink

MAX_LEAK = 0.15                 # pragul verificării (d)
TRAIN_FRACTION = 0.8
INNER_FRACTION = 0.8            # împărțirea internă, pentru alegerea regularizării
C_GRID = (0.0025, 0.005, 0.01, 0.02, 0.05, 0.1, 0.5)
# k mare = termen practic oprit; un termen care nu ajută pe validare rămâne oprit
K_GRID = (1e12, 10000.0, 3000.0, 1000.0, 300.0, 100.0)
OFF = K_GRID[0]
_IA, _JA = np.triu_indices(5, 1)          # cele 10 perechi dintr-o echipă de 5


class HeroLevelLeak(RuntimeError):
    """Un termen pereche-cu-pereche conține un nivel de erou (vezi `check_no_hero_level`)."""


# ---------------------------------------------------------------- date

def to_arrays(matches: list[dict], by_id: dict, min_rank: int | None) -> dict:
    """Meciurile ranked utilizabile -> tablouri de indici, în ordine CRONOLOGICĂ."""
    kept, unknown = [], 0
    for m in matches:
        if not wanted(m, min_rank):
            continue
        if any(h not in by_id for h in m["radiant"] + m["dire"]):
            unknown += 1
            continue
        kept.append(m)
    kept.sort(key=lambda m: (m["start_time"], m["match_id"]))
    return {
        "R": np.array([[by_id[h].idx for h in m["radiant"]] for m in kept], dtype=np.intp),
        "D": np.array([[by_id[h].idx for h in m["dire"]] for m in kept], dtype=np.intp),
        "y": np.array([1.0 if m["radiant_win"] else 0.0 for m in kept]),
        "t": np.array([m["start_time"] for m in kept], dtype=np.int64),
        "mid": np.array([m["match_id"] for m in kept], dtype=np.int64),
        "unknown_hero": unknown,
    }


def chrono_split(t: np.ndarray, fraction: float) -> int:
    """Indicele de tăiere: meciurile [0, k) antrenează, [k, N) rămân deoparte.

    Frontiera cade între două secunde DISTINCTE (t[k-1] < t[k]); altfel un meci din
    hold-out ar putea avea același start_time cu unul din antrenare, iar `benchmark/`
    (care taie după timp) nu ar mai putea garanta că nu există scurgere."""
    n = len(t)
    k = int(n * fraction)
    while 0 < k < n and t[k - 1] == t[k]:
        k -= 1
    if not 0 < k < n:
        raise ValueError(f"nu se poate împărți cronologic {n} meciuri")
    return k


def take(a: dict, sl: slice) -> dict:
    return {k: (v[sl] if isinstance(v, np.ndarray) else v) for k, v in a.items()}


# ---------------------------------------------------------------- (a) β + avantaj

def design(R: np.ndarray, D: np.ndarray, n: int) -> sparse.csr_matrix:
    """+1 pentru fiecare erou din Radiant, −1 pentru fiecare din Dire."""
    N = len(R)
    rows = np.repeat(np.arange(N), 5)
    ones = np.ones(N * 5)
    pos = sparse.csr_matrix((ones, (rows, R.ravel())), shape=(N, n))
    neg = sparse.csr_matrix((ones, (rows, D.ravel())), shape=(N, n))
    return pos - neg


def fit_beta(R, D, y, n: int, C: float) -> tuple[np.ndarray, float]:
    """Regresie logistică L2. C mare = regularizare slabă (a priori β ~ N(0, C)).
    Interceptul nu se penalizează și ESTE avantajul de partidă al lui Radiant."""
    clf = LogisticRegression(C=C, max_iter=3000)
    clf.fit(design(R, D, n), y.astype(int))
    return clf.coef_[0].copy(), float(clf.intercept_[0])


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def log_loss(y, p) -> float:
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


# ---------------------------------------------------------------- (b) counter + synergy

def pair_stats(R, D, r, w, n: int) -> dict:
    """Sume pe perechi, într-o singură trecere prin meciuri.

    r = y − p (reziduul lui Radiant), w = p(1 − p). Counter: a în Radiant vs b în
    Dire. Synergy: perechi din aceeași echipă; Dire vede reziduul cu semn schimbat.
    """
    N = len(R)
    idx = (R[:, :, None] * n + D[:, None, :]).ravel()
    sr = np.bincount(idx, np.repeat(r, 25), n * n).reshape(n, n)
    sw = np.bincount(idx, np.repeat(w, 25), n * n).reshape(n, n)
    sc = np.bincount(idx, minlength=n * n).reshape(n, n).astype(float)
    # perspectiva lui a: meciurile în care b e în Radiant contează cu semn schimbat
    c_num, c_den, c_n = sr - sr.T, sw + sw.T, sc + sc.T

    s_num = np.zeros(n * n)
    s_den = np.zeros(n * n)
    s_n = np.zeros(n * n)
    for team, sign in ((R, 1.0), (D, -1.0)):
        a, b = team[:, _IA], team[:, _JA]
        i = (np.minimum(a, b) * n + np.maximum(a, b)).ravel()
        s_num += np.bincount(i, np.repeat(sign * r, 10), n * n)
        s_den += np.bincount(i, np.repeat(w, 10), n * n)
        s_n += np.bincount(i, minlength=n * n)
    sym = lambda v: (v.reshape(n, n) + v.reshape(n, n).T)
    return {"c_num": c_num, "c_den": c_den, "c_n": c_n,
            "s_num": sym(s_num), "s_den": sym(s_den), "s_n": sym(s_n)}


def _div(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    return np.divide(num, den, out=np.zeros_like(num), where=den > 0)


def shrunk_terms(stats: dict, k_counter: float, k_synergy: float) -> tuple[np.ndarray, np.ndarray]:
    """counter antisimetric și synergy simetric, regularizate — încă NECENTRATE."""
    counter = shrink(_div(stats["c_num"], stats["c_den"]), stats["c_n"], k_counter)
    counter = (counter - counter.T) / 2.0
    synergy = shrink(_div(stats["s_num"], stats["s_den"]), stats["s_n"], k_synergy)
    synergy = (synergy + synergy.T) / 2.0
    np.fill_diagonal(counter, 0.0)
    np.fill_diagonal(synergy, 0.0)
    return counter, synergy


# ---------------------------------------------------------------- (c) centrare

def center_antisymmetric(c: np.ndarray) -> np.ndarray:
    """Scade mediile pe rânduri și pe coloane dintr-o matrice antisimetrică.

    c'[a,b] = c[a,b] − u[a] + u[b], cu u = media pe rând · (n−1)/n. Factorul (n−1)/n
    vine din diagonala exclusă: așa fiecare sumă pe rând (peste b ≠ a) iese EXACT 0,
    iar matricea rămâne antisimetrică. Nu mai rămâne nimic la nivel de erou."""
    n = len(c)
    u = c.sum(axis=1) / (n - 1) * (n - 1) / n
    out = c - u[:, None] + u[None, :]
    np.fill_diagonal(out, 0.0)
    return out


def center_symmetric(s: np.ndarray) -> np.ndarray:
    """Același lucru pentru o matrice simetrică: s'[a,b] = s[a,b] − u[a] − u[b].

    Cu m = media pe rând și U = Σm/2, soluția cu diagonala exclusă este
    u = ((n−1)·m − U)/(n−2); sumele pe rânduri (b ≠ a) ies EXACT 0 și media
    generală dispare (o constantă adunată tuturor perechilor se anulează oricum
    între cele două echipe)."""
    n = len(s)
    m = s.sum(axis=1) / (n - 1)
    total = m.sum() / 2.0
    u = ((n - 1) * m - total) / (n - 2)
    out = s - u[:, None] - u[None, :]
    np.fill_diagonal(out, 0.0)
    return out


# ---------------------------------------------------------------- (d) verificare

def hero_level_corr(matrix: np.ndarray, beta: np.ndarray) -> tuple[float, bool]:
    """corr(sumele pe rânduri, β). Dacă sumele sunt (numeric) zero pentru toți eroii,
    componenta de nivel de erou a dispărut complet: corelația e nedefinită și se
    raportează 0.0, marcată ca degenerată."""
    sums = matrix.sum(axis=1)
    # prag ABSOLUT: coeficienții sunt în log-odds (ordin 0.01–1), deci sume sub 1e-9 sunt zero
    # numeric; un prag relativ ar lua zgomotul de 1e-17 al unei matrice deja centrate drept semnal
    if float(sums.std()) < 1e-9 or float(beta.std()) < 1e-12:
        return 0.0, True
    return float(np.corrcoef(sums, beta)[0, 1]), False


def check_no_hero_level(name: str, matrix: np.ndarray, beta: np.ndarray,
                        limit: float = MAX_LEAK) -> float:
    """Oprește execuția dacă |corr(sumele pe rânduri ale `name`, β)| ≥ limit."""
    corr, _ = hero_level_corr(matrix, beta)
    if abs(corr) >= limit:
        raise HeroLevelLeak(
            f"\nVERIFICARE EȘUATĂ: |corelația dintre sumele pe rânduri ale matricei {name} și β| "
            f"= {abs(corr):.2f} (limita {limit:.2f}; semn {'negativ' if corr < 0 else 'pozitiv'}).\n"
            f"Ce înseamnă: {name} conține o componentă de NIVEL DE EROU — un erou apare "
            f"sistematic avantajat sau dezavantajat față de toți adversarii/partenerii — în loc să "
            f"conțină doar interacțiuni pereche-cu-pereche. Un semn negativ înseamnă că "
            f"{name} anulează β; exact anomalia (−0.67) care a ascuns defectul vechiului model, "
            f"unde counter se calcula ca reziduu față de un β din ALTĂ sursă.\n"
            f"Cauze probabile: centrarea nu s-a aplicat, sau β și {name} nu provin din aceleași meciuri."
        )
    return corr


# ---------------------------------------------------------------- scor și alegerea regularizării

def score_matches(beta, counter, synergy, R, D) -> np.ndarray:
    """Scorul (log-odds pentru Radiant, FĂRĂ avantaj de partidă), vectorizat; același
    rezultat ca `DraftModel.score` aplicat meci cu meci."""
    s = beta[R].sum(axis=1) - beta[D].sum(axis=1)
    s += counter[R[:, :, None], D[:, None, :]].sum(axis=(1, 2))
    s += synergy[R[:, _IA], R[:, _JA]].sum(axis=1) - synergy[D[:, _IA], D[:, _JA]].sum(axis=1)
    return s


def residual_stats(R, D, y, n, beta, intercept) -> dict:
    p = sigmoid(beta[R].sum(axis=1) - beta[D].sum(axis=1) + intercept)
    return pair_stats(R, D, y - p, p * (1 - p), n)


def select_hyperparameters(a: dict, n: int, log=print) -> dict:
    """C, k_counter, k_synergy — alese pe o împărțire cronologică internă a
    antrenării. Hold-out-ul nu se atinge. Alegerea include „termen oprit” (k mare),
    deci un termen care nu ajută pe validare nu intră în model."""
    k = chrono_split(a["t"], INNER_FRACTION)
    tr, va = take(a, slice(0, k)), take(a, slice(k, None))

    log(f"  alegerea regularizării: {len(tr['y']):,} meciuri antrenare interne, "
        f"{len(va['y']):,} validare (mai noi)")
    best_c, best_ll = None, np.inf
    for C in C_GRID:
        beta, b = fit_beta(tr["R"], tr["D"], tr["y"], n, C)
        ll = log_loss(va["y"], sigmoid(beta[va["R"]].sum(1) - beta[va["D"]].sum(1) + b))
        log(f"    C = {C:<7} log-loss validare {ll:.5f}")
        if ll < best_ll:
            best_c, best_ll = C, ll

    beta, b = fit_beta(tr["R"], tr["D"], tr["y"], n, best_c)
    stats = residual_stats(tr["R"], tr["D"], tr["y"], n, beta, b)
    grid = {}
    for kc in K_GRID:
        for ks in K_GRID:
            counter, synergy = shrunk_terms(stats, kc, ks)
            counter, synergy = center_antisymmetric(counter), center_symmetric(synergy)
            s = score_matches(beta, counter, synergy, va["R"], va["D"]) + b
            grid[(kc, ks)] = log_loss(va["y"], sigmoid(s))
    (kc, ks), ll = min(grid.items(), key=lambda kv: kv[1])
    base = grid[(OFF, OFF)]
    log(f"    fără counter/synergy (doar β): {base:.5f}")
    log(f"    alese: C = {best_c}, k_counter = {'oprit' if kc == OFF else kc}, "
        f"k_synergy = {'oprit' if ks == OFF else ks}  →  log-loss validare {ll:.5f} "
        f"({ll - base:+.5f} față de doar β)")
    return {"C": best_c, "k_counter": kc, "k_synergy": ks,
            "val_logloss": ll, "val_logloss_beta_only": base}


# ---------------------------------------------------------------- construcția

def iso(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%d %H:%M")


def build_from_arrays(a: dict, n: int, min_rank: int | None = None,
                      train_fraction: float = TRAIN_FRACTION, C: float | None = None,
                      k_counter: float | None = None, k_synergy: float | None = None,
                      log=print) -> DraftModel:
    """Modelul din tablouri de meciuri ordonate cronologic (vezi `to_arrays`)."""
    N = len(a["y"])
    cut = chrono_split(a["t"], train_fraction)
    train, hold = take(a, slice(0, cut)), take(a, slice(cut, None))
    log(f"  {N:,} meciuri ranked: {cut:,} antrenare ({iso(train['t'][0])} → {iso(train['t'][-1])} UTC), "
        f"{N - cut:,} hold-out ({iso(hold['t'][0])} → {iso(hold['t'][-1])} UTC)")

    chosen = {}
    if C is None or k_counter is None or k_synergy is None:
        chosen = select_hyperparameters(train, n, log)
    C = C if C is not None else chosen["C"]
    k_counter = k_counter if k_counter is not None else chosen["k_counter"]
    k_synergy = k_synergy if k_synergy is not None else chosen["k_synergy"]

    # β + avantajul de partidă, apoi counter/synergy ca reziduuri după ele
    beta, side = fit_beta(train["R"], train["D"], train["y"], n, C)
    stats = residual_stats(train["R"], train["D"], train["y"], n, beta, side)
    raw_counter, raw_synergy = shrunk_terms(stats, k_counter, k_synergy)
    counter, synergy = center_antisymmetric(raw_counter), center_symmetric(raw_synergy)

    # verificarea (d) — pe matricele FINALE; corelația dinainte de centrare doar se raportează
    corr_raw_c = hero_level_corr(raw_counter, beta)[0]
    corr_raw_s = hero_level_corr(raw_synergy, beta)[0]
    corr_c = check_no_hero_level("counter", counter, beta)
    corr_s = check_no_hero_level("synergy", synergy, beta)
    log(f"  verificare nivel-de-erou: corr(sume pe rânduri, β) counter {corr_c:+.3f} "
        f"(înainte de centrare {corr_raw_c:+.3f}), synergy {corr_s:+.3f} "
        f"(înainte {corr_raw_s:+.3f}) — limita {MAX_LEAK}: OK")
    log(f"  avantaj de partidă Radiant: {side:+.4f} log-odds ({sigmoid(side):.1%} șansă la egalitate)")

    meta = {
        "source": "publicmatches",
        "bracket": (f"ranked, avg_rank_tier>={min_rank}" if min_rank else "ranked, toate rangurile"),
        "min_rank": min_rank, "n": n,
        "matches": int(cut), "matches_holdout": int(N - cut),
        "split": f"cronologic {train_fraction:.0%}/{1 - train_fraction:.0%} după start_time",
        "train_start_time": iso(train["t"][0]), "train_end_time": iso(train["t"][-1]),
        "train_end_ts": int(train["t"][-1]), "train_cut_match_id": int(train["mid"].max()),
        "holdout_start_time": iso(hold["t"][0]), "holdout_start_ts": int(hold["t"][0]),
        "holdout_end_time": iso(hold["t"][-1]),
        "l2_C": C, "k_counter": k_counter, "k_synergy": k_synergy,
        "regularization_chosen_by": ("validare cronologică internă" if chosen else "parametri impuși"),
        "counter_beta_corr": round(corr_c, 4), "counter_beta_corr_raw": round(corr_raw_c, 4),
        "synergy_beta_corr": round(corr_s, 4), "synergy_beta_corr_raw": round(corr_raw_s, 4),
        "side_advantage": round(side, 5),
        "fetched": time.strftime("%Y-%m-%d %H:%M"),
        "synergy": "estimată din aceleași meciuri, centrată",
    }
    if chosen:
        meta["val_logloss"] = round(chosen["val_logloss"], 6)
        meta["val_logloss_beta_only"] = round(chosen["val_logloss_beta_only"], 6)
    return DraftModel(beta=beta, counter=counter, synergy=synergy, meta=meta,
                      side_advantage=side)


def build(matches: list[dict], catalog, min_rank: int | None = None, **kw) -> DraftModel:
    a = to_arrays(matches, catalog.by_id, min_rank)
    if a["unknown_hero"]:
        print(f"  {a['unknown_hero']:,} meciuri sărite: eroi absenți din catalog")
    if len(a["y"]) < 200:
        raise SystemExit(f"prea puține meciuri utile ({len(a['y'])}); rulează întâi "
                         f"python -m autodrafter.etl.fetch_publicmatches")
    return build_from_arrays(a, len(catalog), min_rank, **kw)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):               # consola Windows e cp1251
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=RAW_DIR, help=f"meciurile brute (implicit {RAW_DIR})")
    ap.add_argument("--min-rank", type=int, default=None,
                    help="implicit: cel din state.json al colectării")
    ap.add_argument("--out", type=Path, default=None, help="implicit data/model.npz")
    ap.add_argument("--train-fraction", type=float, default=TRAIN_FRACTION)
    ap.add_argument("--c", type=float, default=None, help="C-ul regresiei L2 (implicit: ales prin validare)")
    ap.add_argument("--k-counter", type=float, default=None)
    ap.add_argument("--k-synergy", type=float, default=None)
    a = ap.parse_args()

    min_rank = a.min_rank
    state = a.data / "state.json"
    if min_rank is None and state.exists():
        min_rank = json.loads(state.read_text(encoding="utf-8")).get("min_rank")

    matches = load_matches(a.data)
    if not matches:
        sys.exit(f"Nu există meciuri în {a.data}. Rulează întâi:\n"
                 f"  python -m autodrafter.etl.fetch_publicmatches --count 250000 --min-rank 50")
    print(f"Meciuri brute: {len(matches):,} în {a.data} · min_rank = {min_rank}")
    try:
        model = build(matches, load_catalog(), min_rank, train_fraction=a.train_fraction,
                      C=a.c, k_counter=a.k_counter, k_synergy=a.k_synergy)
    except HeroLevelLeak as exc:
        sys.exit(str(exc))
    out = a.out or default_model_path()
    model.save(out)
    print(f"\nScris {out}\n{json.dumps(model.meta, ensure_ascii=False, indent=1)}")


if __name__ == "__main__":
    main()
