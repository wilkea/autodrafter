from fastapi.testclient import TestClient

from autodrafter.server import app

client = TestClient(app)


def test_meta_lists_heroes_and_algorithms():
    m = client.get("/api/meta").json()
    assert len(m["heroes"]) == 127
    assert set(m["algorithms"]) == {"greedy", "alphabeta", "mcts"}


def test_rejects_bad_input():
    assert client.post("/api/new", json={"side": "XX"}).status_code == 400
    assert client.post("/api/new", json={"side": "FP", "algorithm": "nope"}).status_code == 400
    assert client.get("/api/state/inexistent").status_code == 404


def test_full_game_through_the_api():
    g = client.post("/api/new", json={"side": "FP", "algorithm": "greedy"}).json()
    sid = g["session"]
    for _ in range(40):
        if g["terminal"]:
            break
        s = client.get(f"/api/suggest/{sid}").json()["suggestions"]
        g = client.post("/api/act", json={"session": sid, "hero": s[0]["hero"]}).json()
    assert g["terminal"] and g["turn"] == 24
    assert len(g["picks"]["FP"]) == len(g["picks"]["FB"]) == 5
    assert len(g["banned"]) == 14


def test_instant_draft_plays_both_sides_to_the_end():
    g = client.post("/api/instant", json={
        "fp": {"algorithm": "alphabeta", "options": {"depth": 2, "k": 5}},
        "fb": {"algorithm": "greedy"},
    }).json()
    assert g["mode"] == "instant" and g["human"] is None
    assert g["players"] == {"FP": "alphabeta", "FB": "greedy"}
    assert g["terminal"] and g["turn"] == 24
    assert len(g["picks"]["FP"]) == len(g["picks"]["FB"]) == 5
    assert len(g["banned"]) == 14 and len(g["log"]) == 24
    # fiecare mutare a fost făcută de algoritmul părții ei
    assert {(m["side"], m["by"]) for m in g["log"]} == {("FP", "bot:alphabeta"),
                                                      ("FB", "bot:greedy")}
    assert client.post("/api/instant", json={"fp": {"algorithm": "nope"}}).status_code == 400


def test_cannot_move_out_of_turn_or_reuse_a_hero():
    g = client.post("/api/new", json={"side": "FP", "algorithm": "greedy"}).json()
    sid = g["session"]
    assert g["current"]["is_human"]               # FP acționează prima în ordinea 7.34+
    assert client.post("/api/act", json={"session": sid, "hero": 0}).status_code == 200
    # FP are două ban-uri la rând, deci tot rândul lui; eroul 0 e deja banat
    assert client.post("/api/act", json={"session": sid, "hero": 0}).status_code == 400

    # cu FB, botul (FP) își joacă imediat cele două ban-uri de deschidere
    g = client.post("/api/new", json={"side": "FB", "algorithm": "greedy"}).json()
    assert g["current"]["is_human"] and g["turn"] == 2 and len(g["banned"]) == 2
