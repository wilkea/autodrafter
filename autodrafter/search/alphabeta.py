"""Minimax cu retezare alfa-beta, restrângere la K candidați și tabelă de
transpoziții (doc 02 §2.2).

Valoarea este întotdeauna exprimată ca P(FP câștigă): FP maximizează, FB
minimizează. Ban-urile nu necesită tratare specială — sunt mutări care scot
un erou din mulțimea disponibilă fără a-l adăuga vreunei echipe.

Restrângerea la primii K candidați face algoritmul NEADMISIBIL (poate reteza
mutarea optimă). Este un compromis deliberat: cu b ≈ 110, chiar adâncimea 4
ar însemna ~1.5·10⁸ noduri.
"""
from __future__ import annotations

import numpy as np

from autodrafter.game import Action, DraftState, Side
from autodrafter.search.base import SearchResult, Searcher, Suggestion

INF = float("inf")


class AlphaBetaSearcher(Searcher):
    name = "alphabeta"

    def search(self, state: DraftState) -> SearchResult:
        return self.timed(lambda: self._search(state))

    def _search(self, state: DraftState) -> SearchResult:
        turn = state.current
        if turn is None:
            raise ValueError("draftul s-a încheiat")

        depth = int(self.opts.get("depth", 4))
        self.k = int(self.opts.get("k", 10))
        self.tt: dict[tuple, tuple[int, float]] = {}
        self.tt_hits = 0

        maximising = turn.side is Side.FP
        scored: list[tuple[int, float]] = []
        alpha, beta = -INF, INF

        for hero in self._candidates(state, self.k):
            v = self._ab(state.apply(hero), depth - 1, alpha, beta)
            scored.append((hero, v))
            if maximising:
                alpha = max(alpha, v)
            else:
                beta = min(beta, v)

        scored.sort(key=lambda kv: kv[1], reverse=maximising)
        top = [
            Suggestion(hero=h,
                       value=v if maximising else 1.0 - v,
                       detail=f"P(FP) = {v:.3f}")
            for h, v in scored[: self.opts.get("top_k", 8)]
        ]
        return SearchResult(
            best=top[0].hero, top=top,
            stats={"depth": depth, "k": self.k, "tt_hits": self.tt_hits,
                   "tt_size": len(self.tt),
                   "ebf": round(self.nodes ** (1.0 / max(depth, 1)), 2)},
        )

    def _candidates(self, state: DraftState, k: int) -> list[int]:
        """Ordonarea mutărilor pe baza euristicii greedy. Ordonarea bună este
        ceea ce apropie alfa-beta de O(b^(d/2)), deci nu este opțională."""
        turn = state.current
        assert turn is not None
        legal, gains = self.candidate_gains(state, turn.side)
        order = np.argsort(-gains)[:k]
        return [int(legal[i]) for i in order]

    def _ab(self, state: DraftState, depth: int, alpha: float, beta: float) -> float:
        self.nodes += 1

        if state.is_terminal or depth <= 0:
            return self.leaf_value(state, Side.FP)

        key = (state.key(), depth)
        cached = self.tt.get(key)
        if cached is not None:
            self.tt_hits += 1
            return cached[1]

        turn = state.current
        assert turn is not None
        maximising = turn.side is Side.FP
        best = -INF if maximising else INF

        for hero in self._candidates(state, self.k):
            v = self._ab(state.apply(hero), depth - 1, alpha, beta)
            if maximising:
                best = max(best, v)
                alpha = max(alpha, best)
            else:
                best = min(best, v)
                beta = min(beta, best)
            if beta <= alpha:
                break   # retezare

        self.tt[key] = (depth, best)
        return best
