"""Căutare în arbore Monte Carlo cu selecție UCT (doc 02 §2.3).

Spre deosebire de alfa-beta, MCTS ajunge la stări TERMINALE, unde funcția de
evaluare este calibrată — nu trebuie să estimeze componențe incomplete.
Este un algoritm anytime: poate fi oprit după orice număr de iterații.
"""
from __future__ import annotations

import math

import numpy as np

from autodrafter.game import Action, DraftState, Side
from autodrafter.search.base import SearchResult, Searcher, Suggestion


class Node:
    __slots__ = ("state", "parent", "hero", "children", "untried", "visits", "total")

    def __init__(self, state: DraftState, parent, hero, untried: list[int]):
        self.state = state
        self.parent = parent
        self.hero = hero
        self.children: list["Node"] = []
        self.untried = untried
        self.visits = 0
        self.total = 0.0      # sumă de valori din perspectiva FP

    @property
    def mean(self) -> float:
        return self.total / self.visits if self.visits else 0.0


class MCTSSearcher(Searcher):
    name = "mcts"

    def search(self, state: DraftState) -> SearchResult:
        return self.timed(lambda: self._search(state))

    def _search(self, state: DraftState) -> SearchResult:
        turn = state.current
        if turn is None:
            raise ValueError("draftul s-a încheiat")

        iterations = int(self.opts.get("iterations", 1500))
        self.c = float(self.opts.get("c", 1.4))
        self.width = int(self.opts.get("width", 12))
        self.rng = np.random.default_rng(self.opts.get("seed"))

        root = Node(state, None, None, self._shortlist(state))

        for _ in range(iterations):
            node = self._select(root)
            node = self._expand(node)
            value = self._rollout(node.state)
            self._backup(node, value)

        maximising = turn.side is Side.FP
        kids = sorted(root.children, key=lambda c: c.visits, reverse=True)
        top = [
            Suggestion(
                hero=int(c.hero),
                value=c.mean if maximising else 1.0 - c.mean,
                detail=f"{c.visits} vizite · P(FP) = {c.mean:.3f}",
            )
            for c in kids[: self.opts.get("top_k", 8)]
        ]
        if not top:
            raise RuntimeError("MCTS nu a extins niciun nod")
        return SearchResult(best=top[0].hero, top=top,
                            stats={"iterations": iterations, "c": self.c,
                                   "width": self.width,
                                   "root_children": len(root.children)})

    def _shortlist(self, state: DraftState) -> list[int]:
        """Lățime progresivă: chiar și MCTS are nevoie de restrângere cu b ≈ 110,
        altfel primele sute de iterații doar extind rădăcina."""
        legal, gains = self.candidate_gains(state, state.current.side)
        order = np.argsort(-gains)[: self.width]
        return [int(legal[i]) for i in order]

    def _select(self, node: Node) -> Node:
        while not node.untried and node.children and not node.state.is_terminal:
            node = self._uct(node)
        return node

    def _uct(self, node: Node) -> Node:
        logn = math.log(node.visits + 1)
        maximising = node.state.current.side is Side.FP
        best, best_v = None, -float("inf")
        for c in node.children:
            exploit = c.mean if maximising else 1.0 - c.mean
            v = exploit + self.c * math.sqrt(logn / (c.visits + 1e-9))
            if v > best_v:
                best, best_v = c, v
        return best

    def _expand(self, node: Node) -> Node:
        if node.state.is_terminal or not node.untried:
            return node
        hero = node.untried.pop(self.rng.integers(len(node.untried)))
        child_state = node.state.apply(hero)
        child = Node(child_state, node, hero,
                     [] if child_state.is_terminal else self._shortlist(child_state))
        node.children.append(child)
        self.nodes += 1
        return child

    def _rollout(self, state: DraftState) -> float:
        """Simulare ε-greedy pe un EȘANTION de candidați, până la o stare terminală.

        Evaluarea tuturor celor ~110 mutări legale la fiecare pas de simulare
        domina costul (peste 3·10⁶ evaluări la 1500 de iterații). Alegerea
        lacomă dintr-un eșantion aleator de `sample` candidați păstrează
        direcția politicii la o fracțiune din cost — un compromis standard în
        MCTS între calitatea simulării și numărul de iterații posibile.
        """
        eps = float(self.opts.get("epsilon", 0.35))
        sample = int(self.opts.get("rollout_sample", 16))
        while not state.is_terminal:
            legal = state.legal_moves()
            if self.rng.random() < eps or len(legal) <= 1:
                hero = int(legal[self.rng.integers(len(legal))])
            else:
                idx = self.rng.choice(len(legal), size=min(sample, len(legal)),
                                      replace=False)
                cand = np.asarray([legal[i] for i in idx], dtype=np.intp)
                turn = state.current
                if turn.action is Action.PICK:
                    ours, theirs = self.perspective(state, turn.side)
                else:
                    ours, theirs = self.perspective(state, turn.side.other)
                self.evals += len(cand)
                gains = self.model.gain_vectorised(ours, theirs, cand)
                hero = int(cand[int(np.argmax(gains))])
            state = state.apply(hero)
        return self.leaf_value(state, Side.FP)

    def _backup(self, node: Node | None, value: float) -> None:
        while node is not None:
            node.visits += 1
            node.total += value
            node = node.parent
