"""Minimax cu retezare alfa-beta, restrângere la K candidați și tabelă de
transpoziții (doc 02 §2.2).

Valoarea este întotdeauna exprimată ca P(FP câștigă): FP maximizează, FB
minimizează. Ban-urile nu necesită tratare specială — sunt mutări care scot
un erou din mulțimea disponibilă fără a-l adăuga vreunei echipe.

Restrângerea la primii K candidați face algoritmul NEADMISIBIL (poate reteza
mutarea optimă). Este un compromis deliberat: cu b ≈ 110, chiar adâncimea 4
ar însemna ~1.5·10⁸ noduri.

ADÂNCIRE ITERATIVĂ. O adâncime fixă este nepotrivită aici, fiindcă ordinea
Captain's Mode începe cu șapte ban-uri consecutive: până la acțiunea 7 nicio
componență nu se schimbă, deci o căutare mai puțin adâncă de 8 niveluri vede
numai frunze identice (0.5) și degenerează în greedy. În schimb, în faza de
pick-uri nodurile sunt scumpe și aceeași adâncime devine prohibitivă.

Cu `time_budget_ms`, căutarea reia la adâncimi 2, 4, 6, … până la epuizarea
bugetului și păstrează ultimul rezultat COMPLET. Se adaptează singură: adânc
acolo unde retezarea taie mult, superficial unde nu. Algoritmul devine astfel
și de tip anytime, deci comparabil cu MCTS pe aceeași axă timp/calitate.
"""
from __future__ import annotations

import time

import numpy as np

from autodrafter.game import Action, DraftState, Side
from autodrafter.search.base import SearchResult, Searcher, Suggestion

INF = float("inf")


class _OutOfTime(Exception):
    """Bugetul de timp a expirat în mijlocul unei adâncimi."""


class AlphaBetaSearcher(Searcher):
    name = "alphabeta"

    def search(self, state: DraftState) -> SearchResult:
        return self.timed(lambda: self._search(state))

    def _search(self, state: DraftState) -> SearchResult:
        turn = state.current
        if turn is None:
            raise ValueError("draftul s-a încheiat")

        self.k = int(self.opts.get("k", 10))
        self.tt: dict[tuple, tuple[int, float]] = {}
        self.tt_hits = 0

        budget_ms = self.opts.get("time_budget_ms")
        if budget_ms is None:
            depths = [int(self.opts.get("depth", 4))]
            self._deadline = INF
        else:
            max_depth = int(self.opts.get("max_depth", 12))
            depths = list(range(2, max_depth + 1, 2))
            self._deadline = time.perf_counter() + float(budget_ms) / 1000.0

        scored: list[tuple[int, float]] = []
        reached = 0
        started = time.perf_counter()
        for depth in depths:
            # O adâncime nouă costă, de regulă, mai mult decât toate cele
            # anterioare la un loc. Dacă s-a consumat deja jumătate din buget,
            # pornirea ei ar irosi restul pe un rezultat care va fi aruncat.
            if self._deadline < INF and depth > depths[0]:
                elapsed = time.perf_counter() - started
                if elapsed > (self._deadline - started) * 0.5:
                    break
            try:
                scored = self._root(state, depth, scored)
            except _OutOfTime:
                break          # adâncimea curentă e incompletă: o aruncăm
            reached = depth

        if not scored:          # bugetul n-a ajuns nici pentru prima adâncime
            scored = [(h, 0.5) for h in self._candidates(state, self.k)]
            reached = 0

        maximising = turn.side is Side.FP
        top = [
            Suggestion(hero=h,
                       value=v if maximising else 1.0 - v,
                       detail=f"P(FP) = {v:.3f}")
            for h, v in scored[: self.opts.get("top_k", 8)]
        ]
        depth = reached
        return SearchResult(
            best=top[0].hero, top=top,
            stats={"depth": depth, "k": self.k, "tt_hits": self.tt_hits,
                   "tt_size": len(self.tt),
                   "ebf": round(self.nodes ** (1.0 / max(depth, 1)), 2)},
        )

    def _root(self, state: DraftState, depth: int,
              previous: list[tuple[int, float]]) -> list[tuple[int, float]]:
        """O iterație completă. Mutările cele mai bune din iterația anterioară
        se încearcă primele — ordonarea bună este ceea ce apropie alfa-beta de
        O(K^(d/2)), iar adâncirea iterativă o oferă gratuit."""
        turn = state.current
        assert turn is not None
        maximising = turn.side is Side.FP

        order = [h for h, _ in previous]
        for h in self._candidates(state, self.k):
            if h not in order:
                order.append(h)

        scored: list[tuple[int, float]] = []
        alpha, beta = -INF, INF
        for hero in order:
            v = self._ab(state.apply(hero), depth - 1, alpha, beta)
            scored.append((hero, v))
            if maximising:
                alpha = max(alpha, v)
            else:
                beta = min(beta, v)

        scored.sort(key=lambda kv: kv[1], reverse=maximising)
        return scored

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
        # Verificarea ceasului la fiecare 256 de noduri: fără ea, o singură
        # adâncime poate depăși bugetul cu ordine de mărime.
        if self.nodes % 256 == 0 and time.perf_counter() > self._deadline:
            raise _OutOfTime

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
