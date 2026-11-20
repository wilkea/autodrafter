import numpy as np
import pytest

from autodrafter.game import (BANS_PER_SIDE, N_TURNS, PICKS_PER_SIDE, SCHEDULE,
                              Action, DraftState, Side)
from autodrafter.etl.placeholder import build_placeholder
from autodrafter.search import ALGORITHMS

N = 127


def test_schedule_is_balanced():
    assert N_TURNS == 24
    for side in (Side.FP, Side.FB):
        assert sum(1 for t in SCHEDULE if t.side is side and t.action is Action.PICK) == 5
        assert sum(1 for t in SCHEDULE if t.side is side and t.action is Action.BAN) == 7
    assert PICKS_PER_SIDE == 5 and BANS_PER_SIDE == 7
    assert [t.index for t in SCHEDULE] == list(range(N_TURNS))


def test_schedule_follows_asymmetric_order():
    """Ordinea 7.34+: bans 3-2-2 (FP) vs 4-1-2 (FB), picks 1-3-1 pentru ambele."""
    def per_phase(side, action):
        return [sum(1 for t in SCHEDULE
                    if t.phase == p and t.side is side and t.action is action)
                for p in (1, 2, 3)]

    assert per_phase(Side.FP, Action.BAN) == [3, 2, 2]
    assert per_phase(Side.FB, Action.BAN) == [4, 1, 2]
    # pick-urile: 1 în prima fază, 3 în a doua, 1 în a treia — pentru ambele echipe
    for side in (Side.FP, Side.FB):
        seq = [sum(1 for t in SCHEDULE if t.side is side and t.action is Action.PICK
                   and lo <= t.index < hi)
               for lo, hi in ((7, 9), (12, 18), (22, 24))]
        assert seq == [1, 3, 1]
    assert SCHEDULE[0].side is Side.FP            # FP acționează prima


def test_state_is_immutable_and_rejects_reuse():
    s = DraftState(n_heroes=N)
    s2 = s.apply(0)
    assert s.turn == 0 and s2.turn == 1          # starea originală nu s-a modificat
    with pytest.raises(ValueError):
        s2.apply(0)                              # erou deja folosit
    with pytest.raises(ValueError):
        s2.apply(N)                              # indice invalid


def test_legal_moves_shrink_by_one_each_turn():
    s = DraftState(n_heroes=N)
    for expected in range(N, N - N_TURNS, -1):
        assert len(s.legal_moves()) == expected
        s = s.apply(s.legal_moves()[0])
    assert s.is_terminal
    with pytest.raises(ValueError):
        s.apply(s.legal_moves()[0])


def test_transposition_key_ignores_pick_order():
    a = DraftState(n_heroes=N).apply(1).apply(2).apply(3).apply(4)
    b = DraftState(n_heroes=N).apply(2).apply(1).apply(3).apply(4)
    # aceleași ban-uri în ordine diferită => aceeași stare pentru tabela de transpoziții
    assert a.key() == b.key()
