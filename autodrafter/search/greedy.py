"""Algoritmul greedy — soluția de referință (doc 02 §2.1).

Alege mutarea cu cel mai bun câștig imediat, fără a anticipa răspunsul
adversarului. Complexitate: O(n) evaluări per tură.

Limitarea se vede cel mai clar la eroii disputați: dacă un erou este bun
pentru ambele echipe, greedy își ia propriul optim local și îl pierde.
"""
from __future__ import annotations

import numpy as np

from autodrafter.game import DraftState
from autodrafter.model import sigmoid
from autodrafter.search.base import SearchResult, Searcher, Suggestion


class GreedySearcher(Searcher):
    name = "greedy"

    def search(self, state: DraftState) -> SearchResult:
        return self.timed(lambda: self._search(state))

    def _search(self, state: DraftState) -> SearchResult:
        turn = state.current
        if turn is None:
            raise ValueError("draftul s-a încheiat")
        side = turn.side
        legal, gains = self.candidate_gains(state, side)
        self.nodes = len(legal)

        order = np.argsort(-gains)[: self.opts.get("top_k", 8)]
        ours, theirs = self.perspective(state, side)
        base = self.model.score(ours, theirs)

        top = [
            Suggestion(
                hero=int(legal[i]),
                value=float(sigmoid(base + gains[i])),
                detail=f"câștig marginal {gains[i]:+.3f}",
            )
            for i in order
        ]
        return SearchResult(best=top[0].hero, top=top)
