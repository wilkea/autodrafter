"""Serverul FastAPI: API pentru draft + servirea interfeței web.

    uvicorn autodrafter.server:app --reload
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from autodrafter.game import Side
from autodrafter.heroes import load_catalog
from autodrafter.model import load_or_placeholder
from autodrafter.search import ALGORITHMS
from autodrafter.session import SessionStore

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="autodrafter", version="0.1.0")
store = SessionStore()
_catalog = load_catalog()
_model = load_or_placeholder(len(_catalog))


class NewGame(BaseModel):
    side: str = Field("FP", description="FP = first pick, FB = first ban")
    algorithm: str = "mcts"
    options: dict = Field(default_factory=dict)


class Move(BaseModel):
    session: str
    hero: int


def _session(sid: str):
    try:
        return store.get(sid)
    except KeyError:
        raise HTTPException(404, "sesiune inexistentă sau expirată")


@app.get("/api/meta")
def meta():
    return {
        "heroes": _catalog.to_json(),
        "algorithms": sorted(ALGORITHMS),
        "model": _model.meta,
        "placeholder": _model.meta.get("source") == "placeholder",
    }


@app.post("/api/new")
def new_game(body: NewGame):
    if body.side not in (Side.FP.value, Side.FB.value):
        raise HTTPException(400, "partea trebuie să fie FP sau FB")
    if body.algorithm not in ALGORITHMS:
        raise HTTPException(400, f"algoritm necunoscut: {body.algorithm}")
    s = store.create(_model, Side(body.side), body.algorithm, body.options)
    moves = s.run_bot_turns()     # dacă botul începe, se mișcă imediat
    return {**s.to_json(), "bot_moves": moves}


@app.get("/api/state/{sid}")
def state(sid: str):
    return _session(sid).to_json()


@app.get("/api/suggest/{sid}")
def suggest(sid: str, algorithm: str | None = None, top_k: int = 6):
    s = _session(sid)
    if algorithm and algorithm not in ALGORITHMS:
        raise HTTPException(400, f"algoritm necunoscut: {algorithm}")
    r = s.suggest(algorithm, top_k)
    if r is None:
        return {"suggestions": []}
    return {
        "algorithm": algorithm or s.algorithm,
        "elapsed_ms": round(r.elapsed_ms, 1),
        "nodes": r.nodes,
        "evals": r.evals,
        "stats": r.stats,
        "suggestions": [
            {"hero": x.hero, "name": _catalog.by_idx[x.hero].name,
             "value": round(x.value, 4), "detail": x.detail}
            for x in r.top
        ],
    }


@app.post("/api/act")
def act(body: Move):
    s = _session(body.session)
    cur = s.state.current
    if cur is None:
        raise HTTPException(400, "draftul s-a încheiat")
    if cur.side is not s.human:
        raise HTTPException(409, "nu este rândul tău")
    if not 0 <= body.hero < len(_catalog) or body.hero in s.state.used:
        raise HTTPException(400, "erou indisponibil")
    entry = s.act(body.hero, by="human")
    moves = s.run_bot_turns()
    return {**s.to_json(), "your_move": entry, "bot_moves": moves}


# interfața web
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")
