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


def test_cannot_move_out_of_turn_or_reuse_a_hero():
    g = client.post("/api/new", json={"side": "FP", "algorithm": "greedy"}).json()
    sid = g["session"]
    taken = (g["banned"] or [0])[0]
    assert client.post("/api/act", json={"session": sid, "hero": taken}).status_code == 400
