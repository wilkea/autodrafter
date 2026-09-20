"""Sesiunea de draft: starea partidei, adversarul algoritmic, cronometrele."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from autodrafter.game import SCHEDULE, Action, DraftState, Side
from autodrafter.heroes import load_catalog
from autodrafter.model import DraftModel, sigmoid
from autodrafter.search import ALGORITHMS

ACTION_SECONDS = 30.0      # timp de bază per acțiune, ca în Captain's Mode
RESERVE_SECONDS = 130.0    # rezerva fiecărei echipe


@dataclass
class TeamClock:
    reserve: float = RESERVE_SECONDS
    action_left: float = ACTION_SECONDS

    def start_action(self) -> None:
        self.action_left = ACTION_SECONDS

    def consume(self, seconds: float) -> None:
        """Se consumă întâi timpul de bază, apoi rezerva — ca în joc."""
        if seconds <= self.action_left:
            self.action_left -= seconds
            return
        self.reserve = max(0.0, self.reserve - (seconds - self.action_left))
        self.action_left = 0.0


@dataclass
class Session:
    id: str
    model: DraftModel
    human: Side
    algorithm: str = "mcts"
    options: dict = field(default_factory=dict)
    state: DraftState = None            # type: ignore[assignment]
    log: list[dict] = field(default_factory=list)
    clocks: dict[str, TeamClock] = field(default_factory=dict)
    _turn_started: float = field(default_factory=time.monotonic)

    def __post_init__(self):
        n = len(load_catalog())
        if self.state is None:
            self.state = DraftState(n_heroes=n)
        if not self.clocks:
            self.clocks = {Side.FP.value: TeamClock(), Side.FB.value: TeamClock()}

    # ---------- interogări ----------

    @property
    def bot(self) -> Side:
        return self.human.other

    @property
    def is_bot_turn(self) -> bool:
        t = self.state.current
        return t is not None and t.side is self.bot

    def win_probability(self, side: Side) -> float:
        ours, theirs = self.state.picks(side), self.state.picks(side.other)
        return float(sigmoid(self.model.score(ours, theirs)))

    def searcher(self, algorithm: str | None = None):
        cls = ALGORITHMS[algorithm or self.algorithm]
        return cls(self.model, **self.options)

    def suggest(self, algorithm: str | None = None, top_k: int = 6):
        if self.state.is_terminal:
            return None
        s = self.searcher(algorithm)
        s.opts["top_k"] = top_k
        return s.search(self.state)

    # ---------- acțiuni ----------

    def act(self, hero: int, by: str = "human") -> dict:
        turn = self.state.current
        if turn is None:
            raise ValueError("draftul s-a încheiat")

        elapsed = time.monotonic() - self._turn_started
        self.clocks[turn.side.value].consume(elapsed)

        self.state = self.state.apply(hero)
        self._turn_started = time.monotonic()
        self.clocks[turn.side.value].start_action()

        cat = load_catalog()
        entry = {
            "turn": turn.index, "side": turn.side.value, "action": turn.action.value,
            "phase": turn.phase, "hero": hero, "hero_name": cat.by_idx[hero].name,
            "by": by, "seconds": round(elapsed, 1),
        }
        self.log.append(entry)
        return entry

    def bot_move(self) -> dict | None:
        """Adversarul algoritmic acționează o singură dată."""
        if self.state.is_terminal or not self.is_bot_turn:
            return None
        result = self.searcher().search(self.state)
        entry = self.act(result.best, by=f"bot:{self.algorithm}")
        entry["elapsed_ms"] = round(result.elapsed_ms, 1)
        entry["nodes"] = result.nodes
        entry["evals"] = result.evals
        entry["value"] = round(result.top[0].value, 4)
        return entry

    def run_bot_turns(self, limit: int = 24) -> list[dict]:
        """Rulează toate turele consecutive ale botului (fazele îi pot da două la rând)."""
        moves = []
        while self.is_bot_turn and not self.state.is_terminal and len(moves) < limit:
            m = self.bot_move()
            if m is None:
                break
            moves.append(m)
        return moves

    # ---------- serializare ----------

    def to_json(self) -> dict:
        cat = load_catalog()
        st = self.state
        t = st.current
        now = time.monotonic() - self._turn_started
        clocks = {}
        for side, c in self.clocks.items():
            live = (t is not None and t.side.value == side)
            clocks[side] = {
                "reserve": round(max(0.0, c.reserve - max(0.0, now - c.action_left)) if live else c.reserve, 1),
                "action_left": round(max(0.0, c.action_left - now) if live else c.action_left, 1),
            }
        return {
            "session": self.id,
            "human": self.human.value,
            "bot": self.bot.value,
            "algorithm": self.algorithm,
            "turn": st.turn,
            "total_turns": len(SCHEDULE),
            "terminal": st.is_terminal,
            "current": None if t is None else {
                "index": t.index, "side": t.side.value,
                "action": t.action.value, "phase": t.phase,
                "is_human": t.side is self.human,
            },
            "schedule": [
                {"index": x.index, "side": x.side.value,
                 "action": x.action.value, "phase": x.phase}
                for x in SCHEDULE
            ],
            "picks": {
                Side.FP.value: [cat.by_idx[h].idx for h in st.picks_fp],
                Side.FB.value: [cat.by_idx[h].idx for h in st.picks_fb],
            },
            "banned": sorted(int(h) for h in st.banned),
            "win_probability": {
                Side.FP.value: round(self.win_probability(Side.FP), 4),
                Side.FB.value: round(self.win_probability(Side.FB), 4),
            },
            "clocks": clocks,
            "log": self.log,
            "model": self.model.meta,
        }


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def create(self, model: DraftModel, human: Side, algorithm: str,
               options: dict) -> Session:
        sid = uuid.uuid4().hex[:12]
        s = Session(id=sid, model=model, human=human,
                    algorithm=algorithm, options=options)
        self._sessions[sid] = s
        # prototip: păstrăm doar ultimele sesiuni, ca să nu crească memoria
        if len(self._sessions) > 32:
            for old in list(self._sessions)[:-32]:
                self._sessions.pop(old, None)
        return s

    def get(self, sid: str) -> Session:
        s = self._sessions.get(sid)
        if s is None:
            raise KeyError(sid)
        return s
