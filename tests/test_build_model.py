"""Construcția modelului din meciuri brute (etl/build_model.py), pe date sintetice.
Fără rețea și fără catalogul real: 20 de eroi inventați, adevărul cunoscut."""
from types import SimpleNamespace

import numpy as np
import pytest

from autodrafter.etl import build_model as B
from autodrafter.model import DraftModel
from autodrafter.etl.placeholder import build_placeholder

NH = 20


def synth(N=40000, seed=0, side=0.2, counter_sd=0.15, synergy_sd=0.15, beta_sd=0.3):
    """Meciuri trase dintr-un model cunoscut: β, counter și synergy centrate, avantaj Radiant."""
    rng = np.random.default_rng(seed)
    beta = rng.normal(0, beta_sd, NH)
    c = rng.normal(0, counter_sd, (NH, NH))
    c = B.center_antisymmetric((c - c.T) / 2)
    s = rng.normal(0, synergy_sd, (NH, NH))
    s = B.center_symmetric((s + s.T) / 2)
    perm = np.argsort(rng.random((N, NH)), axis=1)[:, :10]         # 10 eroi distincți per meci
    R, D = perm[:, :5], perm[:, 5:]
    score = B.score_matches(beta, c, s, R, D) + side
    y = (rng.random(N) < B.sigmoid(score)).astype(float)
    arrays = {"R": R, "D": D, "y": y, "t": np.arange(N, dtype=np.int64) * 10,
              "mid": np.arange(N, dtype=np.int64) + 1000, "unknown_hero": 0}
    return arrays, beta, c, s


def corr(a, b):
    return float(np.corrcoef(a.ravel(), b.ravel())[0, 1])


# ---------------------------------------------------------------- centrare

def _hero_level_matrix(rng, kind):
    """Matrice cu o componentă puternică de nivel de erou + puțină interacțiune."""
    level = rng.normal(0, 1.0, NH)
    noise = rng.normal(0, 0.2, (NH, NH))
    if kind == "anti":
        m = (noise - noise.T) / 2 - 1.5 * (level[:, None] - level[None, :])
    else:
        m = (noise + noise.T) / 2 + 1.5 * (level[:, None] + level[None, :])
    np.fill_diagonal(m, 0.0)
    return m


def test_centering_an_antisymmetric_matrix_zeroes_rows_and_columns():
    m = _hero_level_matrix(np.random.default_rng(1), "anti")
    assert np.abs(m.sum(axis=1)).max() > 1                          # înainte: nivel de erou mare
    c = B.center_antisymmetric(m)
    assert np.abs(c.sum(axis=1)).max() < 1e-10                      # mediile pe rânduri ≈ 0
    assert np.abs(c.sum(axis=0)).max() < 1e-10                      # și pe coloane
    assert np.allclose(c, -c.T) and np.allclose(np.diag(c), 0)      # rămâne antisimetrică


def test_centering_a_symmetric_matrix_zeroes_rows_and_columns():
    m = _hero_level_matrix(np.random.default_rng(2), "sym")
    assert np.abs(m.sum(axis=1)).max() > 1
    s = B.center_symmetric(m)
    assert np.abs(s.sum(axis=1)).max() < 1e-10 and np.abs(s.sum(axis=0)).max() < 1e-10
    assert np.allclose(s, s.T) and np.allclose(np.diag(s), 0)       # rămâne simetrică


def test_centering_removes_a_pure_hero_level_term_entirely_and_is_idempotent():
    beta = np.random.default_rng(3).normal(0, 1, NH)
    pure = -1.5 * (beta[:, None] - beta[None, :])                   # exact defectul vechiului counter
    assert np.allclose(B.center_antisymmetric(pure), 0, atol=1e-10)
    m = B.center_antisymmetric(_hero_level_matrix(np.random.default_rng(4), "anti"))
    assert np.allclose(B.center_antisymmetric(m), m)                # a centra din nou nu schimbă nimic


# ---------------------------------------------------------------- verificarea de corelație

def test_check_stops_a_counter_that_carries_a_hero_level_term():
    """Reproduce anomalia care a ascuns defectul: sumele pe rânduri ale counter
    corelează puternic (negativ) cu β."""
    beta = np.random.default_rng(5).normal(0, 0.3, NH)
    buggy = -1.5 * (beta[:, None] - beta[None, :])
    with pytest.raises(B.HeroLevelLeak) as exc:
        B.check_no_hero_level("counter", buggy, beta)
    msg = str(exc.value)
    assert "1.00" in msg and "negativ" in msg                       # valoarea, afișată
    assert "NIVEL DE EROU" in msg and "−0.67" in msg                # și ce înseamnă
    assert B.check_no_hero_level("counter", B.center_antisymmetric(buggy), beta) == 0.0   # centrat: trece


def test_check_passes_below_the_limit_and_fires_at_it():
    beta = np.random.default_rng(6).normal(0, 1, NH)
    # la n=20 o matrice aleatoare poate corela ±0.2 din întâmplare: alegem determinist una sub prag
    for seed in range(100):
        rng = np.random.default_rng(seed)
        unrelated = rng.normal(0, 1, (NH, NH))
        unrelated = (unrelated - unrelated.T) / 2
        small = B.hero_level_corr(unrelated, beta)[0]
        if 0.02 < abs(small) < 0.10:
            break
    else:
        pytest.fail("nu s-a găsit o matrice cu corelație mică")
    assert abs(small) < B.MAX_LEAK
    assert B.check_no_hero_level("counter", unrelated, beta) == pytest.approx(small)
    with pytest.raises(B.HeroLevelLeak):
        B.check_no_hero_level("counter", unrelated, beta, limit=abs(small) * 0.5)


def test_zero_row_sums_are_reported_as_degenerate_not_as_a_random_correlation():
    beta = np.random.default_rng(7).normal(0, 1, NH)
    centred = B.center_antisymmetric(_hero_level_matrix(np.random.default_rng(8), "anti"))
    corr_, degenerate = B.hero_level_corr(centred, beta)
    assert degenerate and corr_ == 0.0


def test_pipeline_check_fires_if_centering_is_ever_removed(monkeypatch):
    """Garda funcționează în construcție: fără centrare, cu un β subestimat (C foarte mic)
    counter-ul absoarbe nivelul eroilor și construcția se oprește."""
    a, *_ = synth(N=20000)
    monkeypatch.setattr(B, "center_antisymmetric", lambda c: c)
    with pytest.raises(B.HeroLevelLeak, match="counter"):
        B.build_from_arrays(a, NH, C=0.0005, k_counter=1.0, k_synergy=B.OFF, log=lambda *_: None)


# ---------------------------------------------------------------- estimare

def test_pair_statistics_have_the_required_symmetries():
    a, *_ = synth(N=5000)
    rng = np.random.default_rng(9)
    r, w = rng.normal(0, 0.5, 5000), rng.random(5000) * 0.25
    st = B.pair_stats(a["R"], a["D"], r, w, NH)
    assert np.allclose(st["c_num"], -st["c_num"].T)                 # counter: antisimetric
    assert np.allclose(st["c_den"], st["c_den"].T) and np.allclose(st["c_n"], st["c_n"].T)
    assert np.allclose(st["s_num"], st["s_num"].T)                  # synergy: simetric
    counter, synergy = B.shrunk_terms(st, 100.0, 100.0)
    assert np.allclose(counter, -counter.T) and np.allclose(synergy, synergy.T)


def test_built_model_has_antisymmetric_counter_and_symmetric_synergy_without_hero_level():
    a, *_ = synth()
    m = B.build_from_arrays(a, NH, min_rank=50, C=0.5, k_counter=100.0, k_synergy=100.0, log=lambda *_: None)
    assert np.allclose(m.counter, -m.counter.T) and np.allclose(m.synergy, m.synergy.T)
    assert np.allclose(np.diag(m.counter), 0) and np.allclose(np.diag(m.synergy), 0)
    for mat in (m.counter, m.synergy):                              # mediile pe rânduri și coloane ≈ 0
        assert np.abs(mat.sum(axis=0)).max() < 1e-9 and np.abs(mat.sum(axis=1)).max() < 1e-9
    assert abs(m.meta["counter_beta_corr"]) < B.MAX_LEAK


def test_regression_recovers_beta_and_the_side_advantage_together():
    a, beta, *_ = synth(counter_sd=0.0, synergy_sd=0.0, side=0.25)
    m = B.build_from_arrays(a, NH, C=0.5, k_counter=B.OFF, k_synergy=B.OFF, log=lambda *_: None)
    assert corr(m.beta, beta) > 0.95
    assert m.side_advantage == pytest.approx(0.25, abs=0.06)        # interceptul ESTE avantajul de partidă
    assert m.meta["side_advantage"] == pytest.approx(m.side_advantage, abs=1e-4)


def test_pair_terms_are_estimated_from_the_same_matches():
    a, _, c_true, s_true = synth(N=60000)
    m = B.build_from_arrays(a, NH, C=0.5, k_counter=100.0, k_synergy=100.0, log=lambda *_: None)
    assert corr(m.counter, c_true) > 0.7                            # aceleași sensuri ca adevărul
    assert corr(m.synergy, s_true) > 0.7


def test_pair_terms_stay_off_when_there_are_no_pair_effects():
    """Fără interacțiuni reale, validarea nu are de ce să le țină: modelul nu e mai rău decât β singur."""
    a, *_ = synth(N=12000, counter_sd=0.0, synergy_sd=0.0)
    m = B.build_from_arrays(a, NH, log=lambda *_: None)
    assert m.meta["val_logloss"] <= m.meta["val_logloss_beta_only"] + 1e-12
    assert m.meta["regularization_chosen_by"] == "validare cronologică internă"


# ---------------------------------------------------------------- cronologie

def test_split_boundary_falls_between_distinct_seconds():
    t = np.array([1, 2, 3, 4, 5, 5, 5, 6, 7, 8])
    k = B.chrono_split(t, 0.6)
    assert t[k - 1] < t[k] and k == 4                               # a mutat frontiera înapoi peste egalități
    with pytest.raises(ValueError):
        B.chrono_split(np.array([5, 5, 5, 5]), 0.5)


def test_training_is_strictly_older_than_the_holdout_and_meta_says_so():
    a, *_ = synth(N=10000)
    m = B.build_from_arrays(a, NH, C=0.5, k_counter=B.OFF, k_synergy=B.OFF, log=lambda *_: None)
    meta = m.meta
    assert meta["matches"] == 8000 and meta["matches_holdout"] == 2000        # 80% / 20%
    assert meta["train_end_ts"] < meta["holdout_start_ts"]                    # antrenare strict mai veche
    assert meta["train_cut_match_id"] == int(a["mid"][:8000].max())
    assert meta["source"] == "publicmatches" and meta["min_rank"] is None
    for key in ("train_start_time", "train_end_time", "holdout_start_time", "l2_C", "k_counter",
                "k_synergy", "counter_beta_corr", "counter_beta_corr_raw", "side_advantage", "fetched"):
        assert key in meta


def test_holdout_labels_never_influence_the_model():
    """Cea mai tare garanție: dacă răsturnăm rezultatele din hold-out, modelul (inclusiv
    regularizarea aleasă prin validare) rămâne IDENTIC bit cu bit."""
    a, *_ = synth(N=6000)
    b = dict(a, y=a["y"].copy())
    b["y"][4800:] = 1.0 - b["y"][4800:]
    m1 = B.build_from_arrays(a, NH, log=lambda *_: None)
    m2 = B.build_from_arrays(b, NH, log=lambda *_: None)
    assert np.array_equal(m1.beta, m2.beta) and np.array_equal(m1.counter, m2.counter)
    assert np.array_equal(m1.synergy, m2.synergy) and m1.side_advantage == m2.side_advantage
    assert (m1.meta["l2_C"], m1.meta["k_counter"], m1.meta["k_synergy"]) == \
           (m2.meta["l2_C"], m2.meta["k_counter"], m2.meta["k_synergy"])


def test_to_arrays_filters_and_orders_chronologically():
    by_id = {h: SimpleNamespace(idx=h - 1) for h in range(1, 21)}

    def match(mid, t, lobby=7, tier=61, heroes=tuple(range(1, 11))):
        return {"match_id": mid, "start_time": t, "radiant_win": True, "avg_rank_tier": tier,
                "lobby_type": lobby, "game_mode": 22, "radiant": list(heroes[:5]), "dire": list(heroes[5:])}
    ms = [match(3, 300), match(1, 100), match(2, 200, lobby=0), match(4, 400, tier=40),
          match(5, 500, heroes=(99, 2, 3, 4, 5, 6, 7, 8, 9, 10)), match(6, 250)]
    a = B.to_arrays(ms, by_id, min_rank=50)
    assert list(a["mid"]) == [1, 6, 3]                              # ranked, ≥50, cunoscuți, în ordinea timpului
    assert a["unknown_hero"] == 1 and a["R"].shape == (3, 5)


# ---------------------------------------------------------------- modelul (model.py)

def test_side_advantage_is_never_added_to_the_score():
    """Constanta nu schimbă niciun argmax de draft; dacă cineva o adună în score(), acest test pică."""
    m = build_placeholder(127)
    ours, theirs = (1, 2, 3, 4, 5), (6, 7, 8, 9, 10)
    before, prob = m.score(ours, theirs), m.win_probability(ours, theirs)
    m.side_advantage = 0.7
    assert m.score(ours, theirs) == before and m.win_probability(ours, theirs) == prob
    cand = np.array([11, 12, 13])
    assert np.array_equal(m.gain_vectorised(ours, theirs, cand),
                          build_placeholder(127).gain_vectorised(ours, theirs, cand))


def test_model_file_roundtrip_and_old_files_without_the_field(tmp_path):
    m = DraftModel.zeros(6)
    m.side_advantage = 0.13
    path = tmp_path / "m.npz"
    m.save(path)
    assert DraftModel.load(path).side_advantage == pytest.approx(0.13)
    np.savez_compressed(path, beta=m.beta, counter=m.counter, synergy=m.synergy, meta="{}")   # format vechi
    assert DraftModel.load(path).side_advantage == 0.0
