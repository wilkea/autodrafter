"""Metrici pentru un predictor probabilistic binar.

Funcții pure, fără rețea și fără model, ca să poată fi verificate pe cazuri cu
răspuns cunoscut (tests/test_benchmark_metrics.py). Convenția: `y` = 1 dacă a
câștigat Radiant, `p` = P(Radiant câștigă).
"""
from __future__ import annotations

from typing import Callable

import numpy as np

# o predicție de exact 0 sau 1 nu trebuie să producă log(0) = -inf
EPS = 1e-12


def _p(p) -> np.ndarray:
    return np.clip(np.asarray(p, dtype=float), EPS, 1.0 - EPS)


def loss_logloss(y, p) -> np.ndarray:
    """Log-loss pe fiecare meci (media lor este `log_loss`)."""
    y, p = np.asarray(y, dtype=float), _p(p)
    return -(y * np.log(p) + (1.0 - y) * np.log(1.0 - p))


def loss_brier(y, p) -> np.ndarray:
    return (np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2


def log_loss(y, p) -> float:
    return float(loss_logloss(y, p).mean())


def brier(y, p) -> float:
    return float(loss_brier(y, p).mean())


def _average_ranks(x: np.ndarray) -> np.ndarray:
    """Ranguri 1-based, cu media rangurilor pentru valori egale."""
    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    cuts = np.flatnonzero(np.diff(xs)) + 1
    starts = np.concatenate(([0], cuts))
    ends = np.concatenate((cuts, [len(x)]))
    avg = (starts + ends + 1) / 2.0
    ranks = np.empty(len(x))
    ranks[order] = np.repeat(avg, ends - starts)
    return ranks


def auc(y, p) -> float:
    """Aria de sub curba ROC = P(un câștigător primește scor mai mare decât un
    pierzător), prin statistica Mann-Whitney; egalitățile contează 1/2."""
    y = np.asarray(y).astype(bool)
    p = np.asarray(p, dtype=float)
    n1 = int(y.sum())
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = _average_ranks(p)
    return float((r[y].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def accuracy(y, p) -> float:
    """Acuratețea la pragul 0.5. O predicție de exact 0.5 nu alege nicio
    echipă, deci primește credit 1/2 (așa că baza „constant 0.5" dă ≈ 50%,
    nu rata de victorie a unei părți)."""
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    hit = np.where(p > 0.5, y, np.where(p < 0.5, 1.0 - y, 0.5))
    return float(hit.mean())


def calibration_table(y, p, bins: int = 10, z: float = 1.96) -> list[dict]:
    """Tabel de calibrare pe `bins` intervale cu ACELAȘI număr de meciuri.

    Intervalele de lățime egală ar fi inutile aici: un model regularizat dă
    predicții strânse în jurul lui 50%, deci 8 din 10 intervale ar rămâne goale.
    Fiecare rând: predicția medie, rata reală de câștig și eroarea ei (±z·σ).
    """
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    order = np.argsort(p, kind="mergesort")
    rows = []
    for idx in np.array_split(order, bins):
        if len(idx) == 0:
            continue
        actual = float(y[idx].mean())
        rows.append({
            "lo": float(p[idx].min()), "hi": float(p[idx].max()),
            "mean_pred": float(p[idx].mean()), "actual": actual, "n": int(len(idx)),
            "ci": float(z * np.sqrt(actual * (1 - actual) / len(idx))),
        })
    return rows


def calibration_fit(y, p, iters: int = 60) -> dict:
    """Regresie logistică y ~ σ(a + b·logit(p)), prin metoda Newton.

    b < 1 înseamnă predicții prea încrezute (scorul ar trebui înmulțit cu b);
    a ≠ 0 înseamnă o părtinire constantă, de pildă avantajul Radiant pe care
    modelul nu îl are. Întoarce și log-loss-ul după această recalibrare pe două
    parametri — cât se poate câștiga dintr-o simplă reglare a scării.
    """
    y = np.asarray(y, dtype=float)
    x = np.log(_p(p) / (1.0 - _p(p)))
    nan = {"intercept": float("nan"), "slope": float("nan"),
           "logloss_recalibrated": float("nan")}
    if len(y) < 3 or float(x.std()) < 1e-9:
        return nan
    X = np.column_stack([np.ones_like(x), x])

    def nll(w):                                   # log-verosimilitate negativă (convexă)
        z = np.clip(X @ w, -30, 30)
        return float(np.sum(np.logaddexp(0.0, z) - y * z))

    # Newton amortizat: pasul întreg poate depăși minimul și diverge când panta
    # adevărată e departe de punctul de pornire (ex. un model anti-corelat).
    w = np.zeros(2)
    for _ in range(iters):
        mu = 1.0 / (1.0 + np.exp(-np.clip(X @ w, -30, 30)))
        grad = X.T @ (y - mu)
        hess = (X * (mu * (1.0 - mu))[:, None]).T @ X + 1e-9 * np.eye(2)
        step = np.linalg.solve(hess, grad)
        f0, t = nll(w), 1.0
        while nll(w + t * step) > f0 + 1e-12 and t > 1e-8:
            t *= 0.5
        w = w + t * step
        if float(np.max(np.abs(t * step))) < 1e-9:
            break
    fitted = 1.0 / (1.0 + np.exp(-np.clip(X @ w, -30, 30)))
    return {"intercept": float(w[0]), "slope": float(w[1]),
            "logloss_recalibrated": log_loss(y, fitted)}


def bootstrap_ci_multi(stat: Callable[[np.ndarray, np.ndarray], tuple], y, p,
                       B: int = 300, seed: int = 0,
                       alpha: float = 0.05) -> list[tuple[float, float]]:
    """Intervale percentilă 1-alpha pentru mai multe statistici odată (`stat`
    întoarce un tuplu), prin re-eșantionare cu revenire. Sămânța fixă face
    raportul reproductibil."""
    y, p = np.asarray(y), np.asarray(p)
    rng = np.random.default_rng(seed)
    n = len(y)
    draws = []
    for _ in range(B):
        i = rng.integers(0, n, n)
        draws.append(stat(y[i], p[i]))
    arr = np.asarray(draws, dtype=float)                       # (B, k)
    out = []
    for j in range(arr.shape[1]):
        col = arr[~np.isnan(arr[:, j]), j]
        if len(col) == 0:
            out.append((float("nan"), float("nan")))
            continue
        lo, hi = np.percentile(col, [100 * alpha / 2, 100 * (1 - alpha / 2)])
        out.append((float(lo), float(hi)))
    return out


def bootstrap_ci(stat: Callable[[np.ndarray, np.ndarray], float], y, p,
                 B: int = 300, seed: int = 0, alpha: float = 0.05) -> tuple[float, float]:
    """Interval percentilă pentru o singură statistică."""
    return bootstrap_ci_multi(lambda yy, pp: (stat(yy, pp),), y, p, B, seed, alpha)[0]


def paired_delta(loss_a: np.ndarray, loss_b: np.ndarray, z: float = 1.96) -> dict:
    """Diferența medie a pierderilor pe aceleași meciuri (a − b) cu interval de
    încredere. Negativ = a e mai bun. Perechile elimină zgomotul dintre meciuri,
    deci intervalul e mult mai strâns decât la două medii comparate separat."""
    d = np.asarray(loss_a, dtype=float) - np.asarray(loss_b, dtype=float)
    n = len(d)
    mean = float(d.mean())
    se = float(d.std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
    return {"mean": mean, "lo": mean - z * se, "hi": mean + z * se}


def summarize(y, p) -> dict:
    """Cele patru metrici obligatorii pentru un set de predicții."""
    return {"n": int(len(y)), "logloss": log_loss(y, p), "brier": brier(y, p),
            "auc": auc(y, p), "accuracy": accuracy(y, p)}
