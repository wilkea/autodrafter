"""Colectorul de meciuri brute (etl/fetch_publicmatches.py): filtrare, reluare, căderi.
Rețeaua e înlocuită cu o sesiune falsă; nu se face nicio cerere reală."""
import pytest
import requests

from autodrafter.etl import fetch_publicmatches as F


def ranked(mid) -> bool:
    return mid % 5 == 0                          # 20% din meciuri sunt ranked


def tier(mid) -> int:
    return 40 + (mid % 7) * 5                    # 40, 45, …, 70


def kept(mid, min_rank=50) -> bool:
    return ranked(mid) and tier(mid) >= min_rank


class Resp:
    def __init__(self, status=200, rows=None, headers=None):
        self.status_code, self._rows, self.headers, self.text = status, rows or [], headers or {}, ""

    def json(self):
        return self._rows


def raw_row(mid):
    return {"match_id": mid, "radiant_win": mid % 2 == 0, "start_time": 1_700_000_000 + mid,
            "lobby_type": 7 if ranked(mid) else 0, "game_mode": 22, "avg_rank_tier": tier(mid),
            "radiant_team": [1, 2, 3, 4, 5], "dire_team": [6, 7, 8, 9, 10]}


class FakeSession:
    """publicMatches simulat: pagini descrescătoare de câte 100, id-uri consecutive."""
    def __init__(self, top=1_000_000, quota=2000):
        self.calls, self.top, self.quota = [], top, quota

    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params or {}))
        start = (params or {}).get("less_than_match_id", self.top + 1) - 1
        self.quota -= 1
        return Resp(200, [raw_row(m) for m in range(start, start - 100, -1)],
                    {"x-rate-limit-remaining-day": str(self.quota)})


def scanned_ids(state, top=1_000_000):
    """Toate id-urile scanate: de la `top` în jos până la cursor inclusiv."""
    return range(top, state["cursor"] - 1, -1)


def stored(tmp_path):
    return sorted(m["match_id"] for m in F.load_matches(tmp_path))


def run(tmp_path, count, session=None, **kw):
    return F.fetch(count, tmp_path, min_rank=kw.pop("min_rank", 50), pause=0,
                   session=session or FakeSession(), sleep=lambda s: None, **kw)


def test_wanted_keeps_only_ranked_at_or_above_the_minimum_rank():
    base = {"lobby_type": 7, "avg_rank_tier": 55}
    assert F.wanted(base, 50) and F.wanted(base, None)
    assert not F.wanted(dict(base, lobby_type=0), 50)               # Turbo/normal: aruncat
    assert not F.wanted(dict(base, avg_rank_tier=49), 50)           # sub tranșa cerută
    assert not F.wanted(dict(base, avg_rank_tier=None), 50)         # fără rang: nu știm
    assert F.wanted(dict(base, avg_rank_tier=20), None)             # fără --min-rank: orice rang ranked


def test_count_is_matches_scanned_and_only_wanted_ones_are_stored(tmp_path):
    state = run(tmp_path, 500)
    assert state["scanned"] == 500                                  # 5 pagini × 100
    expected = [m for m in scanned_ids(state) if kept(m)]
    assert stored(tmp_path) == sorted(expected)
    assert state["kept"] == len(expected) and 0 < len(expected) < 500
    assert state["min_rank"] == 50
    assert all(m["lobby_type"] == 7 and m["avg_rank_tier"] >= 50 for m in F.load_matches(tmp_path))


def test_resume_continues_from_the_scan_cursor_not_from_the_lowest_stored_match(tmp_path):
    first = run(tmp_path, 300)
    lowest_kept = min(stored(tmp_path))
    assert first["cursor"] < lowest_kept                            # sunt meciuri scanate mai vechi decât cel mai vechi păstrat
    second = FakeSession()
    state = run(tmp_path, 700, session=second)
    assert second.calls[0]["less_than_match_id"] == first["cursor"]  # nu re-scanează ce a aruncat deja
    assert state["scanned"] == 700
    expected = [m for m in scanned_ids(state) if kept(m)]
    assert stored(tmp_path) == sorted(expected)                     # fără goluri și fără duplicate


def test_nothing_to_do_when_the_target_is_already_reached(tmp_path):
    run(tmp_path, 300)
    idle = FakeSession()
    run(tmp_path, 300, session=idle)
    assert idle.calls == []


def test_api_gets_min_rank_and_cursor(tmp_path):
    s = FakeSession()
    run(tmp_path, 200, session=s)
    assert s.calls[0] == {"min_rank": 50}
    assert s.calls[1]["min_rank"] == 50 and s.calls[1]["less_than_match_id"] == 1_000_000 - 99


class Flaky(FakeSession):
    """Cade după `ok` cereri (rețea)."""
    def __init__(self, ok):
        super().__init__()
        self.ok = ok

    def get(self, url, params=None, timeout=None):
        if len(self.calls) >= self.ok:
            raise requests.ConnectionError("cădere")
        return super().get(url, params, timeout)


def test_a_crash_between_batches_leaves_no_gap(tmp_path, monkeypatch):
    """Lotul se scrie împreună cu cursorul; ce nu a apucat să fie salvat se re-scanează."""
    monkeypatch.setattr(F, "BATCH", 20)
    with pytest.raises(RuntimeError, match="cerere eșuată"):
        run(tmp_path, 3000, session=Flaky(ok=13))
    state = run(tmp_path, 3000)                                     # reluare cu rețea sănătoasă
    assert state["scanned"] >= 3000 or state["cursor"] is not None
    expected = [m for m in scanned_ids(state) if kept(m)]
    assert stored(tmp_path) == sorted(expected)                     # exact ce trebuia, o singură dată


def test_daily_quota_exhaustion_stops_cleanly_and_saves_progress(tmp_path):
    s = FakeSession(quota=8)                                        # după 5 cereri mai rămân 3 => oprire
    with pytest.raises(F.RateLimitExhausted):
        run(tmp_path, 100_000, session=s)
    state = F.load_state(tmp_path, F.load_matches(tmp_path))
    assert state["scanned"] == 500 and state["cursor"] == 1_000_000 - 499
    assert stored(tmp_path) == sorted(m for m in scanned_ids(state) if kept(m))
    resumed = FakeSession(quota=1000)
    run(tmp_path, 800, session=resumed)                             # a doua zi: continuă
    assert resumed.calls[0]["less_than_match_id"] == state["cursor"]


def test_429_waits_retry_after_and_zero_quota_is_terminal():
    sleeps = []

    class Scripted:
        def __init__(self, *r):
            self.r = list(r)

        def get(self, *a, **k):
            return self.r.pop(0)

    rows, left = F._get(Scripted(Resp(429, headers={"Retry-After": "7", "x-rate-limit-remaining-day": "900"}),
                                 Resp(200, [raw_row(1)], {"x-rate-limit-remaining-day": "899"})),
                        {}, sleep=sleeps.append)
    assert sleeps == [7.0] and left == 899 and len(rows) == 1
    with pytest.raises(F.RateLimitExhausted):
        F._get(Scripted(Resp(429, headers={"x-rate-limit-remaining-day": "0"})), {}, sleep=lambda s: None)


def test_parse_match_rejects_what_the_real_api_sends_for_unfinished_games():
    assert F.parse_match(raw_row(10))["radiant"] == [1, 2, 3, 4, 5]
    in_progress = dict(raw_row(10), radiant_team=[0] * 5, dire_team=[0] * 5)
    one_v_one = dict(raw_row(10), radiant_team=[1], dire_team=[2])
    assert F.parse_match(in_progress) is None and F.parse_match(one_v_one) is None


def test_a_transient_permission_error_on_replace_is_retried(tmp_path, monkeypatch):
    """Pe Windows un cititor poate ține state.json deschis o clipă; colectarea nu trebuie să pice."""
    from pathlib import Path
    real, failures = Path.replace, {"left": 2}

    def flaky(self, target):
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError("fișier deschis de alt proces")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    F.save_state(tmp_path, {"cursor": 5, "scanned": 100, "kept": 40, "min_rank": 50})
    assert F.load_state(tmp_path, [])["cursor"] == 5 and failures["left"] == 0
    failures["left"] = 99                                              # cădere permanentă: eroarea iese la vedere
    with pytest.raises(PermissionError):
        F.save_state(tmp_path, {"cursor": 6, "scanned": 1, "kept": 1, "min_rank": 50})
