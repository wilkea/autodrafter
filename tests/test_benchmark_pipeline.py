"""Fluxul băncii de testare — parsare, reluare, limita de cereri, evaluare și raport —
pe date sintetice. Nicio cerere reală: rețeaua e înlocuită cu o sesiune falsă."""
import json

import numpy as np
import pytest

from autodrafter.heroes import load_catalog
from autodrafter.model import DraftModel
from benchmark import evaluate as E
from benchmark import fetch_matches as F
from benchmark import report as R


# ---------------------------------------------------------------- descărcare

def raw_row(match_id, radiant=(1, 2, 3, 4, 5), dire=(6, 7, 8, 9, 10), win=True, **extra):
    row = {"match_id": match_id, "match_seq_num": 1, "radiant_win": win, "start_time": 1_700_000_000 + match_id,
           "duration": 0, "lobby_type": 7, "game_mode": 22, "avg_rank_tier": 61, "num_rank_tier": 8,
           "cluster": 1, "radiant_team": list(radiant), "dire_team": list(dire)}
    row.update(extra)
    return row


def test_parse_match_keeps_the_needed_fields():
    m = F.parse_match(raw_row(42, win=False))
    assert m == {"match_id": 42, "start_time": 1_700_000_042, "radiant_win": False,
                 "avg_rank_tier": 61, "lobby_type": 7, "game_mode": 22,
                 "radiant": [1, 2, 3, 4, 5], "dire": [6, 7, 8, 9, 10]}


@pytest.mark.parametrize("bad", [
    raw_row(1, radiant=(0, 0, 0, 0, 0), dire=(0, 0, 0, 0, 0)),     # meci încă în desfășurare
    raw_row(2, radiant=(1,), dire=(2,)),                            # 1v1
    raw_row(3, radiant=(1, 2, 3, 4, 4)),                            # erou dublat
    raw_row(4, win=None),                                           # fără rezultat
    {"match_id": 5},                                                # câmpuri lipsă
    raw_row(6, radiant="1,2,3,4,5", dire="6,7,8,9,10"),             # schema veche, cu șiruri
])
def test_parse_match_rejects_unusable_rows(bad):
    assert F.parse_match(bad) is None


def test_load_matches_skips_corrupt_lines_and_duplicates(tmp_path):
    good = F.parse_match(raw_row(10))
    (tmp_path / "matches_00001.jsonl").write_text(
        json.dumps(good) + "\n" + '{"match_id": 11, "start_ti' + "\n", encoding="utf-8")
    (tmp_path / "matches_00002.jsonl").write_text(json.dumps(good) + "\n", encoding="utf-8")
    assert [m["match_id"] for m in F.load_matches(tmp_path)] == [10]


class FakeResp:
    def __init__(self, status=200, rows=None, headers=None):
        self.status_code, self._rows, self.headers, self.text = status, rows or [], headers or {}, ""

    def json(self):
        return self._rows


class FakeSession:
    """publicMatches simulat: pagini descrescătoare de câte 100, cu heroii variați."""
    def __init__(self, top=100_000, valid_every=1):
        self.calls, self.top, self.valid_every = [], top, valid_every

    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params or {}))
        start = (params or {}).get("less_than_match_id", self.top + 1) - 1
        rows = []
        for mid in range(start, start - 100, -1):
            rows.append(raw_row(mid) if mid % self.valid_every == 0
                        else raw_row(mid, radiant=(0, 0, 0, 0, 0), dire=(0, 0, 0, 0, 0)))
        return FakeResp(200, rows, {"x-rate-limit-remaining-day": "2000"})


def test_fetch_stops_at_the_target_and_writes_batches(tmp_path):
    total = F.fetch(2350, tmp_path, pause=0, session=FakeSession(), sleep=lambda s: None)
    assert total == 2350 == len(F.load_matches(tmp_path))
    sizes = [sum(1 for _ in open(p, encoding="utf-8")) for p in sorted(tmp_path.glob("matches_*.jsonl"))]
    assert sizes == [1000, 1000, 350]                               # loturi de 1000, ultimul parțial


def test_fetch_resumes_backwards_instead_of_starting_over(tmp_path):
    F.fetch(1000, tmp_path, pause=0, session=FakeSession(), sleep=lambda s: None)
    lowest = min(m["match_id"] for m in F.load_matches(tmp_path))
    second = FakeSession()
    total = F.fetch(1500, tmp_path, pause=0, session=second, sleep=lambda s: None)
    assert total == 1500
    assert second.calls[0]["less_than_match_id"] == lowest          # continuă de unde a rămas
    ids = [m["match_id"] for m in F.load_matches(tmp_path)]
    assert len(ids) == len(set(ids)) == 1500                        # fără duplicate


def test_fetch_does_nothing_when_the_target_is_already_met(tmp_path):
    F.fetch(1000, tmp_path, pause=0, session=FakeSession(), sleep=lambda s: None)
    idle = FakeSession()
    assert F.fetch(1000, tmp_path, pause=0, session=idle, sleep=lambda s: None) == 1000
    assert idle.calls == []


def test_fetch_skips_unusable_matches_but_still_reaches_the_count(tmp_path):
    total = F.fetch(300, tmp_path, pause=0, session=FakeSession(valid_every=2), sleep=lambda s: None)
    assert total == 300 and all(len(m["radiant"]) == 5 for m in F.load_matches(tmp_path))


def test_fetch_passes_min_rank_and_cursor_to_the_api(tmp_path):
    s = FakeSession()
    F.fetch(150, tmp_path, min_rank=60, pause=0, session=s, sleep=lambda s_: None)
    assert s.calls[0] == {"min_rank": 60}
    assert s.calls[1]["min_rank"] == 60 and "less_than_match_id" in s.calls[1]


class Scripted:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return self.responses.pop(0)


def test_get_waits_retry_after_on_429_then_succeeds():
    sleeps = []
    s = Scripted(FakeResp(429, headers={"Retry-After": "7", "x-rate-limit-remaining-day": "1500"}),
                 FakeResp(200, [raw_row(1)], {"x-rate-limit-remaining-day": "1499"}))
    rows, remaining = F._get(s, {}, sleep=sleeps.append)
    assert len(rows) == 1 and remaining == 1499
    assert sleeps == [7.0]                                          # a respectat Retry-After


def test_get_stops_instead_of_waiting_when_the_daily_quota_is_gone():
    s = Scripted(FakeResp(429, headers={"x-rate-limit-remaining-day": "0"}))
    with pytest.raises(F.RateLimitExhausted):
        F._get(s, {}, sleep=lambda x: None)


def test_get_gives_a_readable_error_after_repeated_failures():
    s = Scripted(*[FakeResp(500) for _ in range(3)])
    with pytest.raises(RuntimeError, match="cerere eșuată"):
        F._get(s, {}, tries=3, sleep=lambda x: None)


# ---------------------------------------------------------------- evaluare + raport

@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def make_model(catalog, seed=0):
    rng = np.random.default_rng(seed)
    m = DraftModel.zeros(len(catalog))
    m.beta[:] = rng.normal(0, 0.5, len(catalog))                    # scoruri bine răspândite
    m.meta = {"source": "test", "bracket": "high", "matches": 123, "k_beta": 2000.0,
              "k_counter": 300.0, "fetched": "2026-01-01 00:00", "synergy": "zero"}
    return m


def synthetic_matches(catalog, model, n=1500, invert=False, seed=1):
    """Rezultate trase din propriile probabilități ale modelului (calibrat), sau
    din inversul lor (un model anti-corelat cu realitatea)."""
    rng = np.random.default_rng(seed)
    ids = [h.hero_id for h in catalog]
    out = []
    for i in range(n):
        picks = rng.choice(ids, 10, replace=False).tolist()
        rad = tuple(catalog.by_id[h].idx for h in picks[:5])
        dire = tuple(catalog.by_id[h].idx for h in picks[5:])
        p = model.win_probability(rad, dire)
        p = 1 - p if invert else p
        out.append({"match_id": 1000 + i, "start_time": 1_700_000_000 + i * 60,
                    "radiant_win": bool(rng.random() < p),
                    "avg_rank_tier": int(rng.choice([31, 45, 52, 61, 72])),
                    "lobby_type": 7 if i % 5 else 0, "game_mode": 22 if i % 5 else 23,
                    "radiant": picks[:5], "dire": picks[5:]})
    return out


def test_predict_uses_the_radiant_perspective_and_skips_unknown_heroes(catalog):
    model = DraftModel.zeros(len(catalog))
    strong = catalog.heroes[0]
    model.beta[strong.idx] = 1.0
    others = [h.hero_id for h in catalog.heroes[1:11]]
    with_strong_radiant = {"radiant": [strong.hero_id] + others[:4], "dire": others[4:9], "radiant_win": True}
    with_strong_dire = {"radiant": others[:5], "dire": [strong.hero_id] + others[5:9], "radiant_win": False}
    unknown = {"radiant": [999_999] + others[:4], "dire": others[4:9], "radiant_win": True}
    kept, y, p, missing, skipped = E.predict(model, catalog, [with_strong_radiant, with_strong_dire, unknown])
    assert len(kept) == 2 and skipped == 1 and missing == {999_999: 1}
    assert p[0] > 0.5 > p[1]                                        # eroul puternic contează pe partea lui
    assert list(y) == [1.0, 0.0]


def test_evaluate_beats_the_baselines_when_outcomes_follow_the_model(catalog):
    model = make_model(catalog)
    res = E.evaluate(model, catalog, synthetic_matches(catalog, model), B=60)
    assert res["data"]["n_test"] == 1200 and res["data"]["excluded_by_subset"] == 300   # doar ranked
    assert res["deltas"]["vs_const_0.5"]["logloss"]["hi"] < 0
    assert res["deltas"]["vs_radiant_rate"]["logloss"]["hi"] < 0
    assert 0.8 < res["calibration"]["slope"] < 1.2                  # calibrat prin construcție
    assert R.verdict(res)[0] == "beats_both"
    assert "Recalibrarea nu aduce nimic material" in R.what_to_fix(res)      # deja calibrat
    assert {r["rank"] for r in res["by_rank"]} == {3, 4, 5, 6, 7}
    assert res["in_vs_out"] is not None and res["train_ranks"] == [6, 7, 8]


def test_evaluate_calls_an_anticorrelated_model_broken(catalog):
    model = make_model(catalog)
    res = E.evaluate(model, catalog, synthetic_matches(catalog, model, invert=True), B=60)
    code, sentence = R.verdict(res)
    assert code == "broken" and sentence.startswith("Modelul este STRICAT")
    assert res["calibration"]["slope_ci"][1] < 0                    # panta negativă, nu doar slabă


def test_evaluate_flags_an_overconfident_model(catalog):
    """Rezultate trase din adevărul σ(S/3), dar modelul raportează σ(S): supraîncrezut."""
    model = make_model(catalog)
    calm = DraftModel(model.beta / 3, model.counter, model.synergy, model.meta)
    matches = synthetic_matches(catalog, calm, n=4000)
    res = E.evaluate(model, catalog, matches, B=60)
    assert res["calibration"]["slope"] == pytest.approx(1 / 3, abs=0.12)
    assert "prea încrezute" in R.what_to_fix(res)
    assert "k_beta" in R.what_to_fix(res)


def test_components_blame_a_counter_term_that_cancels_beta(catalog):
    """Reproduce eșecul real: rezultatele depind doar de β, dar modelul are un counter
    cu componentă de erou de semn opus (counter[a,b] = −k(β_a − β_b)). β singur e bun,
    counter-ul singur e anti-predictiv, iar suma lor iese mai rău decât o monedă."""
    truth = make_model(catalog)
    b = truth.beta
    zeros = np.zeros((len(b), len(b)))
    bad = DraftModel(b.copy(), -1.5 * (b[:, None] - b[None, :]), zeros, truth.meta)
    res = E.evaluate(bad, catalog, synthetic_matches(catalog, truth, n=4000), B=60)

    rows = {r["name"]: r for r in res["components"]["rows"]}
    beta_row, cnt_row = rows["β — puterea eroilor"], rows["counter"]
    assert beta_row["auc_ci"][0] > 0.5                              # β singur are semnal
    assert cnt_row["auc_ci"][1] < 0.5                               # counter-ul e anti-predictiv
    centred = rows["β + counter centrat (diagnostic)"]
    assert centred["auc"] == pytest.approx(beta_row["auc"], abs=1e-9)   # centrarea îl elimină complet
    assert res["components"]["reproduces"]                          # descompunerea regăsește scorul modelului
    assert res["components"]["counter_vs_beta_corr"] < -0.99        # sume pe rânduri ~ −β

    assert R.verdict(res)[0] == "broken"
    text = R.what_to_fix(res)
    assert "Termenul counter strică modelul" in text and "reziduu față de β" in text
    assert "Semnal inversat" in text


def test_components_of_a_healthy_model_raise_no_accusation(catalog):
    model = make_model(catalog)
    res = E.evaluate(model, catalog, synthetic_matches(catalog, model), B=40)
    assert res["components"]["reproduces"]
    assert "Termenul counter strică" not in R.what_to_fix(res)


def test_evaluate_refuses_a_tiny_test_set(catalog):
    model = make_model(catalog)
    with pytest.raises(ValueError, match="prea puține"):
        E.evaluate(model, catalog, synthetic_matches(catalog, model, n=20))


def test_chronological_window_filters_by_time(catalog):
    model = make_model(catalog)
    matches = synthetic_matches(catalog, model, n=600)
    cut = matches[300]["start_time"]
    res = E.evaluate(model, catalog, matches, subset="all", since=cut, B=30)
    assert res["data"]["in_window"] == 300


def test_report_states_the_verdict_first_and_always_carries_the_overlap_warning(catalog):
    model = make_model(catalog)
    for invert in (False, True):
        res = E.evaluate(model, catalog, synthetic_matches(catalog, model, invert=invert), B=40)
        res["_name"] = "test.json"
        text = R.build_report(res)
        body = text.split("\n\n")
        assert body[2].startswith("**Verdict.**")                   # verdictul, imediat sub titlu
        assert "SUPRAPUNE" in text and "OPTIMISTE" in text          # avertismentul cerut
        assert "fereastră anterioară" in text.replace("**", "")
        assert "## Ce e de reparat" in text and "## Calibrare" in text


def test_report_warns_when_the_test_window_is_only_hours_wide(catalog):
    model = make_model(catalog)
    narrow = E.evaluate(model, catalog, synthetic_matches(catalog, model, n=400), B=30)   # ~6 ore
    wide = E.evaluate(model, catalog, synthetic_matches(catalog, model, n=2500), B=30)    # ~42 ore
    assert "Fereastră îngustă" in R.build_report(narrow)
    assert "Fereastră îngustă" not in R.build_report(wide)


def test_report_compares_with_the_previous_run(catalog):
    model = make_model(catalog)
    old = E.evaluate(model, catalog, synthetic_matches(catalog, model), B=30)
    worse = E.evaluate(model, catalog, synthetic_matches(catalog, model, invert=True), B=30)
    worse["_name"] = "new.json"
    text = R.build_report(worse, old, "old.json")
    assert "Comparație cu rularea anterioară (`old.json`)" in text
    assert "mai rău" in text
    assert "amestecă efectul" not in text                           # aceleași meciuri: seturi identice
    assert "Nu există o rulare anterioară" in R.build_report(old)


def test_find_results_picks_the_latest_and_the_one_before(tmp_path):
    for name in ("20260101-000000", "20260102-000000", "20260103-000000"):
        (tmp_path / f"{name}.json").write_text("{}", encoding="utf-8")
    cur, prev = R.find_results(tmp_path, None)
    assert (cur.stem, prev.stem) == ("20260103-000000", "20260102-000000")
    cur, prev = R.find_results(tmp_path, tmp_path / "20260101-000000.json")
    assert prev is None


# ---------------------------------------------------------------- modelul din meciuri brute

def test_predict_adds_the_side_advantage_only_at_prediction_time(catalog):
    model = DraftModel.zeros(len(catalog))
    model.side_advantage = 0.4
    match = {"radiant": [h.hero_id for h in catalog.heroes[:5]], "dire": [h.hero_id for h in catalog.heroes[5:10]],
             "radiant_win": True}
    _, _, p, _, _ = E.predict(model, catalog, [match])
    assert p[0] == pytest.approx(1 / (1 + np.exp(-0.4)))            # scor 0 + avantaj => σ(0.4)
    assert model.score((0, 1, 2, 3, 4), (5, 6, 7, 8, 9)) == 0.0    # iar score() rămâne neschimbat


def test_components_still_reproduce_the_predictions_with_a_side_advantage(catalog):
    model = make_model(catalog)
    model.side_advantage = 0.3
    res = E.evaluate(model, catalog, synthetic_matches(catalog, model), B=30)
    assert res["components"]["reproduces"] and res["model"]["side_advantage"] == 0.3


def test_train_ranks_from_min_rank_or_from_the_old_bracket():
    assert E.train_ranks({"min_rank": 50}) == {5, 6, 7, 8}
    assert E.train_ranks({"bracket": "high"}) == {6, 7, 8}          # modelul vechi, din heroStats
    assert E.train_ranks({"bracket": "ranked, toate rangurile", "min_rank": None}) == set()


def test_holdout_guard_excludes_matches_that_may_have_been_in_training(catalog):
    """Meciurile anterioare hold-out-ului se exclud, oricât de convenabil ar fi să le testăm."""
    model = make_model(catalog)
    matches = synthetic_matches(catalog, model, n=1500)
    cut = matches[500]["start_time"]
    model.meta = dict(model.meta, holdout_start_ts=cut)
    res = E.evaluate(model, catalog, matches, B=30)
    assert res["data"]["holdout_guard"] == {"holdout_start_ts": cut, "excluded_before_holdout": 500, "own": True}
    assert res["data"]["in_window"] == 1000                        # doar meciurile de la tăiere încolo
    other = make_model(catalog, seed=0)                            # alt model, fără hold-out propriu…
    same = E.evaluate(other, catalog, matches, B=30, holdout_ts=cut)   # …dar testat pe hold-out-ul primului
    assert same["data"]["in_window"] == 1000
    assert same["data"]["holdout_guard"]["own"] is False               # hold-out împrumutat, nu al lui
    borrowed = R.build_report(dict(same, _name="x"))
    assert "OPTIMISTE" in borrowed and "Împărțire cronologică respectată" not in borrowed   # NU pretinde ce nu e adevărat


def test_overlap_warning_is_replaced_by_the_chronological_statement_when_the_guard_applies(catalog):
    model = make_model(catalog)
    matches = synthetic_matches(catalog, model, n=1500)
    plain = E.evaluate(model, catalog, matches, B=30)
    model.meta = dict(model.meta, holdout_start_ts=matches[300]["start_time"], train_end_time="2026-01-01 00:00",
                      source="publicmatches", matches=999, matches_holdout=100, l2_C=0.01,
                      k_counter=100, k_synergy=100, regularization_chosen_by="test", counter_beta_corr=0.0,
                      counter_beta_corr_raw=0.9, synergy_beta_corr=0.0, synergy_beta_corr_raw=0.9,
                      train_start_time="2026-01-01 00:00", holdout_start_time="2026-01-02 00:00",
                      train_cut_match_id=5)
    guarded = E.evaluate(model, catalog, matches, B=30)
    assert "SUPRAPUNE" in R.overlap_note(plain) and "OPTIMISTE" in R.overlap_note(plain)
    note = R.overlap_note(guarded)
    assert "Împărțire cronologică respectată" in note and "SUPRAPUNE" not in note
    text = R.build_report(guarded)
    assert "meciuri brute OpenDota" in text and "Avantaj de partidă estimat" in text
    assert "Antrenarea (`etl/build_model.py`)" in text


def test_advice_points_at_the_knobs_of_the_model_that_was_actually_tested(catalog):
    """Un model din meciuri brute se reglează în build_model.py; cel vechi în fetch_opendota.py."""
    assert "build_model.py" in R.reg_knobs({"source": "publicmatches"})
    assert "fetch_opendota.py" in R.reg_knobs({"source": "opendota"})
    assert "l2_C = 0.01" in R.reg_now({"source": "publicmatches", "l2_C": 0.01, "k_counter": 1, "k_synergy": 2})
