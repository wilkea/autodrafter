import numpy as np

from autodrafter.etl.placeholder import build_placeholder

N = 127


def test_matrix_symmetries():
    m = build_placeholder(N)
    assert np.allclose(m.counter, -m.counter.T)       # contracararea e antisimetrică
    assert np.allclose(m.synergy, m.synergy.T)        # sinergia e simetrică
    assert np.allclose(np.diag(m.counter), 0)
    assert np.allclose(np.diag(m.synergy), 0)


def test_empty_draft_is_even():
    m = build_placeholder(N)
    assert m.win_probability((), ()) == 0.5


def test_score_is_zero_sum():
    m = build_placeholder(N)
    a, b = (1, 2, 3, 4, 5), (6, 7, 8, 9, 10)
    assert m.score(a, b) == -m.score(b, a)
    assert abs(m.win_probability(a, b) + m.win_probability(b, a) - 1.0) < 1e-12


def test_vectorised_gain_matches_incremental_score():
    """gain_vectorised este o optimizare; trebuie să dea exact același
    rezultat ca recalcularea scorului pentru fiecare candidat."""
    m = build_placeholder(N)
    ours, theirs = (1, 2), (6, 7)
    cand = np.array([11, 12, 13, 40, 99])
    fast = m.gain_vectorised(ours, theirs, cand)
    for i, h in enumerate(cand):
        slow = m.score(ours + (int(h),), theirs) - m.score(ours, theirs)
        assert abs(float(fast[i]) - slow) < 1e-9


def test_determinism():
    assert np.array_equal(build_placeholder(N).beta, build_placeholder(N).beta)
