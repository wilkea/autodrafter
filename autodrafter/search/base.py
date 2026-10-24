"""Interfața comună a algoritmilor de căutare.

Toți algoritmii consumă exact aceeași funcție de evaluare, astfel încât
diferențele măsurate între ei să fie atribuibile exclusiv strategiei de
căutare (doc 06 §6.3). Orice algoritm nou trebuie să implementeze `search`.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

from autodrafter.game import Action, DraftState, Side
from autodrafter.model import DraftModel, sigmoid


@dataclass
class Suggestion:
    hero: int
    value: float          # P(echipa la rând câștigă), după acțiune
    detail: str = ""


@dataclass
class SearchResult:
    best: int
    top: list[Suggestion]
    nodes: int = 0
    evals: int = 0
    elapsed_ms: float = 0.0
    stats: dict = field(default_factory=dict)


class Searcher(ABC):
    name = "base"

    def __init__(self, model: DraftModel, **kwargs):
        self.model = model
        self.opts = kwargs
        self.nodes = 0
        self.evals = 0

    # ---------- utilitare comune ----------

    def perspective(self, state: DraftState, side: Side) -> tuple[tuple, tuple]:
        """Componențele (ale noastre, ale lor) din punctul de vedere al lui `side`."""
        return state.picks(side), state.picks(side.other)

    def leaf_value(self, state: DraftState, side: Side) -> float:
        """Probabilitatea ca `side` să câștige, în starea dată."""
        self.evals += 1
        ours, theirs = self.perspective(state, side)
        return float(sigmoid(self.model.score(ours, theirs)))

    def candidate_gains(self, state: DraftState, side: Side) -> tuple[np.ndarray, np.ndarray]:
        """Câștigul marginal al fiecărei mutări legale, pentru `side`.

        La un ban, valoarea unui erou este cât i-ar folosi ADVERSARULUI:
        interzicem ce ne-ar face cel mai mult rău, nu ce ne-ar ajuta pe noi.
        """
        legal = np.asarray(state.legal_moves(), dtype=np.intp)
        turn = state.current
        assert turn is not None
        if turn.action is Action.PICK:
            ours, theirs = self.perspective(state, side)
        else:
            ours, theirs = self.perspective(state, side.other)
        self.evals += len(legal)
        return legal, self.model.gain_vectorised(ours, theirs, legal)

    def timed(self, fn):
        t0 = time.perf_counter()
        self.nodes = self.evals = 0
        result = fn()
        result.elapsed_ms = (time.perf_counter() - t0) * 1000.0
        result.nodes = self.nodes
        result.evals = self.evals
        return result

    @abstractmethod
    def search(self, state: DraftState) -> SearchResult:
        ...
