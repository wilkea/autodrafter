"""Metricile băncii de testare, verificate pe cazuri cu răspuns cunoscut.
Fără rețea și fără model: doar aritmetică."""
import math

import numpy as np
import pytest

from benchmark import metrics as M


def test_log_loss_known_value():
    y, p = [1, 0], [0.8, 0.3]
    assert M.log_loss(y, p) == pytest.approx(-(math.log(0.8) + math.log(0.7)) / 2)


def test_log_loss_of_a_coin_is_ln2_whatever_the_outcomes():
    y = [1, 0, 0, 1, 1, 1, 0]
    assert M.log_loss(y, [0.5] * 7) == pytest.approx(math.log(2))


def test_log_loss_stays_finite_for_certain_predictions():
    wrong = M.log_loss([1, 0], [0.0, 1.0])          # complet greșit, dar fără inf
    assert math.isfinite(wrong) and wrong > 20
    assert M.log_loss([1, 0], [1.0, 0.0]) == pytest.approx(0.0, abs=1e-9)


def test_brier_known_values():
    assert M.brier([1, 0], [0.8, 0.3]) == pytest.approx((0.2**2 + 0.3**2) / 2)
    assert M.brier([1, 0], [1.0, 0.0]) == 0.0
    assert M.brier([1, 0], [0.0, 1.0]) == 1.0
    assert M.brier([1, 0, 1], [0.5] * 3) == 0.25


def test_auc_classic_example():
    # exemplul standard: 3 din cele 4 perechi (câștigător, pierzător) sunt ordonate corect
    assert M.auc([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8]) == pytest.approx(0.75)


def test_auc_extremes_and_ties():
    assert M.auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert M.auc([0, 0, 1, 1], [0.8, 0.9, 0.1, 0.2]) == 0.0
    assert M.auc([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5]) == 0.5      # predicție constantă
    assert math.isnan(M.auc([1, 1, 1], [0.1, 0.5, 0.9]))          # o singură clasă


def test_auc_matches_pairwise_definition():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 200)
    p = np.round(rng.random(200), 1)                              # multe egalități
    pos, neg = p[y == 1], p[y == 0]
    brute = np.mean([(a > b) + 0.5 * (a == b) for a in pos for b in neg])
    assert M.auc(y, p) == pytest.approx(brute)


def test_accuracy_gives_half_credit_to_a_tie():
    assert M.accuracy([1, 0], [0.7, 0.2]) == 1.0
    assert M.accuracy([1, 0], [0.2, 0.7]) == 0.0
    assert M.accuracy([1, 0, 1, 1], [0.5] * 4) == 0.5             # moneda: 50%, nu rata unei părți


def test_calibration_table_bins_hold_equal_counts():
    y = np.array([0] * 50 + [1] * 50)
    p = np.concatenate([np.full(50, 0.3), np.full(50, 0.6)])
    t = M.calibration_table(y, p, bins=2)
    assert [r["n"] for r in t] == [50, 50]
    assert t[0]["mean_pred"] == pytest.approx(0.3) and t[0]["actual"] == 0.0
    assert t[1]["mean_pred"] == pytest.approx(0.6) and t[1]["actual"] == 1.0


def test_calibration_table_has_ten_rows_covering_every_match():
    rng = np.random.default_rng(2)
    p = 0.4 + 0.2 * rng.random(1234)
    t = M.calibration_table(rng.integers(0, 2, 1234), p)
    assert len(t) == 10 and sum(r["n"] for r in t) == 1234
    assert all(t[i]["mean_pred"] <= t[i + 1]["mean_pred"] for i in range(9))


def _logistic_sample(scale: float, shift: float, n: int = 40000):
    """Rezultate generate din adevărul σ(x); modelul raportează σ(scale·x + shift)."""
    rng = np.random.default_rng(3)
    x = rng.normal(0, 1, n)
    y = (rng.random(n) < 1 / (1 + np.exp(-x))).astype(float)
    return y, 1 / (1 + np.exp(-(scale * x + shift)))


def test_calibration_fit_recovers_a_well_calibrated_model():
    y, p = _logistic_sample(1.0, 0.0)
    f = M.calibration_fit(y, p)
    assert f["slope"] == pytest.approx(1.0, abs=0.06)
    assert f["intercept"] == pytest.approx(0.0, abs=0.05)


def test_calibration_fit_detects_overconfidence():
    """Un model care își dublează scorul e prea încrezut: panta recuperată ≈ 0.5."""
    y, p = _logistic_sample(2.0, 0.0)
    assert M.calibration_fit(y, p)["slope"] == pytest.approx(0.5, abs=0.05)


def test_calibration_fit_detects_a_constant_bias():
    y, p = _logistic_sample(1.0, -0.3)                            # model părtinit cu −0.3
    assert M.calibration_fit(y, p)["intercept"] == pytest.approx(0.3, abs=0.05)


def test_calibration_fit_on_constant_predictions_is_undefined():
    assert math.isnan(M.calibration_fit([1, 0, 1, 0], [0.5] * 4)["slope"])


def test_recalibration_never_hurts_log_loss():
    y, p = _logistic_sample(2.0, 0.2, n=5000)
    assert M.calibration_fit(y, p)["logloss_recalibrated"] <= M.log_loss(y, p) + 1e-9


def test_paired_delta_sign_and_zero():
    y, good = _logistic_sample(1.0, 0.0, n=4000)
    coin = np.full_like(good, 0.5)
    better = M.paired_delta(M.loss_logloss(y, good), M.loss_logloss(y, coin))
    assert better["mean"] < 0 and better["hi"] < 0                # net mai bun decât moneda
    same = M.paired_delta(M.loss_logloss(y, good), M.loss_logloss(y, good))
    assert same["mean"] == 0.0 and same["lo"] == 0.0 and same["hi"] == 0.0


def test_bootstrap_is_reproducible_and_brackets_the_estimate():
    y, p = _logistic_sample(1.0, 0.0, n=2000)
    a = M.bootstrap_ci(M.auc, y, p, B=100, seed=7)
    assert a == M.bootstrap_ci(M.auc, y, p, B=100, seed=7)
    assert a[0] < M.auc(y, p) < a[1]


def test_summarize_reports_the_four_required_metrics():
    s = M.summarize([1, 0, 1, 0], [0.9, 0.2, 0.6, 0.4])
    assert set(s) == {"n", "logloss", "brier", "auc", "accuracy"}
    assert s["n"] == 4 and s["auc"] == 1.0 and s["accuracy"] == 1.0
