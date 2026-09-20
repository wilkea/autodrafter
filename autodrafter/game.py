"""Motorul de joc: starea draftului, ordinea acțiunilor, mutări legale.

Acest modul NU conține nicio logică de evaluare a eroilor. Separarea dintre
căutare și evaluare (doc 01 §1.5) depinde de menținerea acestei granițe.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


class Side(str, Enum):
    """Rolul echipei stabilit la coin toss, nu culoarea hărții."""
    FP = "FP"   # first pick
    FB = "FB"   # first ban

    @property
    def other(self) -> "Side":
        return Side.FB if self is Side.FP else Side.FP


class Action(str, Enum):
    PICK = "pick"
    BAN = "ban"


@dataclass(frozen=True)
class Turn:
    index: int
    side: Side
    action: Action
    phase: int


# Ordinea Captain's Mode: 14 ban-uri (7/echipă) + 10 pick-uri (5/echipă) = 24 acțiuni.
# ATENȚIE: alternanța exactă în interiorul fazelor se modifică între patch-uri.
# Verificați secvența față de patch-ul curent înainte de a raporta rezultate.
_SCHEDULE: list[tuple[int, Action, list[Side]]] = [
    (1, Action.BAN,  [Side.FB, Side.FP, Side.FB, Side.FP]),
    (1, Action.PICK, [Side.FP, Side.FB, Side.FB, Side.FP]),
    (2, Action.BAN,  [Side.FB, Side.FP, Side.FB, Side.FP, Side.FB, Side.FP]),
    (2, Action.PICK, [Side.FB, Side.FP, Side.FP, Side.FB]),
    (3, Action.BAN,  [Side.FP, Side.FB, Side.FP, Side.FB]),
    (3, Action.PICK, [Side.FP, Side.FB]),
]


def build_schedule() -> list[Turn]:
    turns: list[Turn] = []
    for phase, action, sides in _SCHEDULE:
        for side in sides:
            turns.append(Turn(len(turns), side, action, phase))
    return turns


SCHEDULE: list[Turn] = build_schedule()
N_TURNS = len(SCHEDULE)

PICKS_PER_SIDE = sum(1 for t in SCHEDULE if t.action is Action.PICK and t.side is Side.FP)
BANS_PER_SIDE = sum(1 for t in SCHEDULE if t.action is Action.BAN and t.side is Side.FP)


@dataclass(frozen=True)
class DraftState:
    """Stare imuabilă. `picks` păstrează ordinea; `banned` nu contează ca ordine."""
    n_heroes: int
    turn: int = 0
    picks_fp: tuple[int, ...] = ()
    picks_fb: tuple[int, ...] = ()
    banned: frozenset[int] = field(default_factory=frozenset)

    @property
    def is_terminal(self) -> bool:
        return self.turn >= N_TURNS

    @property
    def current(self) -> Turn | None:
        return None if self.is_terminal else SCHEDULE[self.turn]

    @property
    def used(self) -> frozenset[int]:
        return self.banned | frozenset(self.picks_fp) | frozenset(self.picks_fb)

    def legal_moves(self) -> list[int]:
        used = self.used
        return [h for h in range(self.n_heroes) if h not in used]

    def picks(self, side: Side) -> tuple[int, ...]:
        return self.picks_fp if side is Side.FP else self.picks_fb

    def apply(self, hero: int) -> "DraftState":
        if self.is_terminal:
            raise ValueError("draftul s-a încheiat")
        if hero in self.used:
            raise ValueError(f"eroul {hero} este deja folosit")
        if not 0 <= hero < self.n_heroes:
            raise ValueError(f"indice de erou invalid: {hero}")
        t = self.current
        assert t is not None
        if t.action is Action.BAN:
            return replace(self, turn=self.turn + 1, banned=self.banned | {hero})
        if t.side is Side.FP:
            return replace(self, turn=self.turn + 1, picks_fp=self.picks_fp + (hero,))
        return replace(self, turn=self.turn + 1, picks_fb=self.picks_fb + (hero,))

    def key(self) -> tuple:
        """Cheie canonică pentru tabela de transpoziții: ordinea pick-urilor
        în interiorul unei faze nu schimbă componența, deci o ignorăm."""
        return (self.turn, frozenset(self.picks_fp), frozenset(self.picks_fb), self.banned)
