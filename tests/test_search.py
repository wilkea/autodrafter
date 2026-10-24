import pytest

from autodrafter.etl.placeholder import build_placeholder
from autodrafter.game import N_TURNS, DraftState
from autodrafter.search import ALGORITHMS

N = 127
FAST = {"greedy": {}, "alphabeta": {"depth": 2, "k": 6}, "mcts": {"iterations": 60, "seed": 7}}


@pytest.mark.parametrize("name", sorted(ALGORITHMS))
def test_returns_a_legal_move(name):
    m = build_placeholder(N)
    s = DraftState(n_heroes=N).apply(0).apply(1).apply(2)
    r = ALGORITHMS[name](m, **FAST[name]).search(s)
    assert r.best in s.legal_moves()
    assert r.top and all(x.hero in s.legal_moves() for x in r.top)
    assert all(0.0 <= x.value <= 1.0 for x in r.top)


@pytest.mark.parametrize("name", sorted(ALGORITHMS))
def test_completes_a_full_draft(name):
    m = build_placeholder(N)
    s = DraftState(n_heroes=N)
    for _ in range(N_TURNS):
        s = s.apply(ALGORITHMS[name](m, **FAST[name]).search(s).best)
    assert s.is_terminal
    assert len(s.picks_fp) == 5 and len(s.picks_fb) == 5 and len(s.banned) == 14
    # un erou nu poate apărea de două ori în draft
    used = list(s.picks_fp) + list(s.picks_fb) + list(s.banned)
    assert len(used) == len(set(used)) == N_TURNS


def test_greedy_picks_the_highest_marginal_gain():
    """Proprietatea care defineşte algoritmul greedy: la un PICK alege exact
    maximul câştigului imediat, fără a anticipa răspunsul adversarului."""
    m = build_placeholder(N)
    s = DraftState(n_heroes=N)
    while s.current.action.value != "pick":
        s = s.apply(s.legal_moves()[0])
    r = ALGORITHMS["greedy"](m).search(s)
    side = s.current.side
    gains = {h: m.score(s.picks(side) + (h,), s.picks(side.other))
             for h in s.legal_moves()}
    assert r.best == max(gains, key=gains.get)


# ---------------------------------------------------------------- adâncire iterativă

def test_iterative_deepening_respects_the_budget():
    m = build_placeholder(N)
    s = DraftState(n_heroes=N)
    for i in range(9):
        s = s.apply(s.legal_moves()[i * 3])
    for budget in (50, 200):
        r = ALGORITHMS["alphabeta"](m, time_budget_ms=budget, k=10).search(s)
        assert r.elapsed_ms < budget * 1.6 + 60, f"buget {budget} depășit: {r.elapsed_ms}"
        assert r.best in s.legal_moves()


def test_deeper_budget_never_searches_shallower():
    """Un buget mai mare nu poate duce la o adâncime mai mică."""
    m = build_placeholder(N)
    s = DraftState(n_heroes=N)
    depths = [ALGORITHMS["alphabeta"](m, time_budget_ms=b, k=8).search(s).stats["depth"]
              for b in (20, 100, 400)]
    assert depths == sorted(depths), depths


def test_ban_phase_needs_depth_to_see_a_pick():
    """Ordinea CM începe cu 7 ban-uri: sub adâncimea 8 toate frunzele sunt
    componențe goale, deci scorul e exact 0.5 și căutarea n-are niciun semnal."""
    m = build_placeholder(N)
    s = DraftState(n_heroes=N)
    shallow = ALGORITHMS["alphabeta"](m, depth=6, k=10).search(s)
    deep = ALGORITHMS["alphabeta"](m, depth=8, k=10).search(s)
    assert shallow.top[0].value == 0.5
    assert deep.top[0].value != 0.5


def test_fixed_depth_still_works():
    """Fără time_budget_ms, comportamentul vechi rămâne neschimbat."""
    m = build_placeholder(N)
    s = DraftState(n_heroes=N).apply(0).apply(1)
    r = ALGORITHMS["alphabeta"](m, depth=4, k=8).search(s)
    assert r.stats["depth"] == 4 and r.best in s.legal_moves()
