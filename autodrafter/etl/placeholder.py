"""Model placeholder, determinist — structură realistă, numere inventate.

Nu are valoare predictivă. Există pentru ca interfața și algoritmii să poată
fi dezvoltați și testați înainte de colectarea datelor reale. Ordinele de
mărime imită datele reale: β în ±0.25 (≈ ±6 puncte procentuale de winrate),
interacțiunile perechi mai mici decât efectele individuale.
"""
from __future__ import annotations

import numpy as np

from autodrafter.model import DraftModel

SEED = 20260920


def build_placeholder(n: int, seed: int = SEED) -> DraftModel:
    rng = np.random.default_rng(seed)

    beta = rng.normal(0.0, 0.12, size=n)

    # Vectori latenți: interacțiunile sunt produse scalare de rang redus,
    # la fel ca în factorizarea din doc 03 §3.1d. Astfel matricele au
    # structură (eroi similari se comportă similar), nu zgomot pur.
    k = 6
    u = rng.normal(0, 1, size=(n, k))
    v = rng.normal(0, 1, size=(n, k))

    counter = (u @ v.T) * 0.02
    counter = (counter - counter.T) / 2.0          # antisimetrie: cnt(a,b) = −cnt(b,a)
    np.fill_diagonal(counter, 0.0)

    synergy = (u @ u.T) * 0.015
    synergy = (synergy + synergy.T) / 2.0          # simetrie
    np.fill_diagonal(synergy, 0.0)

    return DraftModel(beta=beta, counter=counter, synergy=synergy,
                      meta={"source": "placeholder", "seed": seed, "n": n,
                            "warning": "numere inventate — fără valoare predictivă"})
