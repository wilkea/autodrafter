"""Funcția de evaluare — „modelul matematic pentru erou".

Modelul minim (doc 03 §3.1) lucrează în log-odds, pentru ca efectele să se adune:

    S = Σ β_h (ai noștri) − Σ β_h (ai lor)
      + Σ syn(a,b) (perechile noastre) − Σ syn(a,b) (perechile lor)
      + Σ cnt(a,b) pentru a ∈ ai noștri, b ∈ ai lor

    P(câștigăm) = σ(S) = 1 / (1 + e^(−S))

Întregul model se reduce la trei structuri: un vector β (n) și două matrice
n×n. Evaluarea este apelată de mii de ori într-o singură căutare, deci se
bazează exclusiv pe operații numpy asupra unor tablouri ținute în memorie.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def logit(p: float | np.ndarray) -> float | np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(x: float | np.ndarray) -> float | np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def shrink(raw: np.ndarray, n_obs: np.ndarray, k: float) -> np.ndarray:
    """Regularizare empirical-Bayes către 0: o pereche cu puține meciuri nu
    trebuie să contribuie. k se alege prin validare încrucișată."""
    return raw * (n_obs / (n_obs + k))


@dataclass
class DraftModel:
    """β: putere per erou. counter[a, b]: avantajul lui a împotriva lui b
    (antisimetric). synergy[a, b]: câștigul lui a și b în aceeași echipă."""

    beta: np.ndarray            # (n,)
    counter: np.ndarray         # (n, n)
    synergy: np.ndarray         # (n, n)
    meta: dict

    @property
    def n(self) -> int:
        return int(self.beta.shape[0])

    def score(self, ours: tuple[int, ...], theirs: tuple[int, ...]) -> float:
        """Scorul în log-odds. Funcționează și pe componențe incomplete,
        fiindcă toate sumele sunt peste eroii prezenți efectiv."""
        s = 0.0
        if ours:
            a = np.fromiter(ours, dtype=np.intp, count=len(ours))
            s += float(self.beta[a].sum())
            if len(ours) > 1:
                s += float(np.triu(self.synergy[np.ix_(a, a)], 1).sum())
        if theirs:
            b = np.fromiter(theirs, dtype=np.intp, count=len(theirs))
            s -= float(self.beta[b].sum())
            if len(theirs) > 1:
                s -= float(np.triu(self.synergy[np.ix_(b, b)], 1).sum())
        if ours and theirs:
            s += float(self.counter[np.ix_(a, b)].sum())
        return s

    def win_probability(self, ours: tuple[int, ...], theirs: tuple[int, ...]) -> float:
        return float(sigmoid(self.score(ours, theirs)))

    def gain_vectorised(self, ours: tuple[int, ...], theirs: tuple[int, ...],
                        candidates: np.ndarray) -> np.ndarray:
        """Câștigul marginal, pentru toți candidații simultan.

        Evaluarea naivă ar reapela score() o dată per candidat. Fiindcă scorul
        este aditiv, câștigul adăugării lui h se reduce la:
            β_h + Σ_{a ∈ ai noștri} syn(h, a) + Σ_{b ∈ ai lor} cnt(h, b)
        ceea ce transformă O(n) apeluri în două produse matrice-vector.
        """
        g = self.beta[candidates].copy()
        if ours:
            a = np.fromiter(ours, dtype=np.intp, count=len(ours))
            g += self.synergy[np.ix_(candidates, a)].sum(axis=1)
        if theirs:
            b = np.fromiter(theirs, dtype=np.intp, count=len(theirs))
            g += self.counter[np.ix_(candidates, b)].sum(axis=1)
        return g

    # ---------- persistență ----------

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, beta=self.beta, counter=self.counter,
                            synergy=self.synergy, meta=json.dumps(self.meta))

    @classmethod
    def load(cls, path: Path) -> "DraftModel":
        z = np.load(path, allow_pickle=False)
        return cls(beta=z["beta"], counter=z["counter"], synergy=z["synergy"],
                   meta=json.loads(str(z["meta"])))

    @classmethod
    def zeros(cls, n: int) -> "DraftModel":
        return cls(np.zeros(n), np.zeros((n, n)), np.zeros((n, n)),
                   {"source": "zeros"})


def default_model_path() -> Path:
    return DATA_DIR / "model.npz"


def load_or_placeholder(n: int) -> DraftModel:
    """Încarcă modelul real dacă există, altfel generează unul placeholder.

    Permite rularea întregii aplicații înainte de colectarea datelor —
    algoritmii și interfața nu depind de proveniența numerelor.
    """
    path = default_model_path()
    if path.exists():
        m = DraftModel.load(path)
        if m.n == n:
            return m
    from autodrafter.etl.placeholder import build_placeholder
    return build_placeholder(n)
