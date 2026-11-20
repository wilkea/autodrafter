# -*- coding: utf-8 -*-
"""Experiment controlat al căutării: greedy vs alfa-beta vs MCTS pe ACEEAȘI funcție de evaluare.

    python -m experiments.search_benchmark selftest
    python -m experiments.search_benchmark e1          # instanța redusă, rezolvată exact
    python -m experiments.search_benchmark e2          # instanța completă: cost și stabilitate
    python -m experiments.search_benchmark tournament  # self-play pe deschideri aleatoare

Nu modifică nimic din `autodrafter/`: folosește `ALGORITHMS`, `DraftState` și `DraftModel`
exact cum le folosește aplicația. Rezultatele: `experiments/results/<experiment>-<timp>.json`.

METRICI FIXATE ÎNAINTE DE RULARE
--------------------------------
E1 — instanța redusă (12 eroi, 10 acțiuni: 2 ban-uri + 3 pick-uri pe echipă, tipar CM).
  V*(s) = valoarea minimax exactă (P(FP câștigă) cu joc optim de ambele părți), calculată
  prin inducție înapoi cu memoizare, de un solver scris separat (pe măști de biți), deci
  independent de codul căutării.
  Pentru o mutare a aleasă în starea s de partea X:
    regret(a)      = V*(s) − V*(s ⊕ a)        dacă X = FP (maximizează)
                   = V*(s ⊕ a) − V*(s)        dacă X = FB (minimizează)
                   în puncte procentuale (×100); 0 = mutare optimă.
    optim          = regret ≤ 1e-9 (rata de mutări optime).
    regret relativ = regret / (cea mai bună − cea mai proastă mutare), în [0, 1].
  Bază de comparație: mutarea aleatoare (media regretului peste toate mutările legale).
  Cost: timp (ms), noduri, apeluri ale evaluatorului (contorul `evals` din `Searcher`).

E2 — instanța completă (127 eroi, 24 acțiuni). NU există adevăr de referință:
  se măsoară doar costul (timp, noduri, evaluări, adâncime atinsă, EBF, TT) și
  stabilitatea MCTS (în câte semințe se alege aceeași mutare), plus acordul între algoritmi.

Turneu — fiecare pereche ordonată (A ca FP, B ca FB) pe aceleași deschideri aleatoare
  (primele două ban-uri), cu configurațiile din interfață. Rezultatul unui draft este
  P(FP câștigă) a componenței finale DUPĂ ACELAȘI EVALUATOR pe care îl optimizează
  algoritmii — o măsură circulară, raportată ca atare, nu ca rată reală de victorie.
  Scorul așteptat al lui A contra lui B pe o deschidere: (P_A,FP + (1 − P_B,FP)) / 2.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

import autodrafter.game as game
from autodrafter.game import Action, DraftState, Side, Turn
from autodrafter.model import DraftModel, default_model_path, sigmoid
from autodrafter.etl.placeholder import build_placeholder
from autodrafter.search import ALGORITHMS
from autodrafter.search.alphabeta import AlphaBetaSearcher, _OutOfTime

RESULTS = Path(__file__).resolve().parent / "results"
INF = float("inf")

# Programul redus: 2 ban-uri + 3 pick-uri pe echipă, același tipar ca fazele CM.
REDUCED = [
    (Side.FP, Action.BAN), (Side.FB, Action.BAN),
    (Side.FP, Action.PICK), (Side.FB, Action.PICK), (Side.FB, Action.PICK), (Side.FP, Action.PICK),
    (Side.FP, Action.BAN), (Side.FB, Action.BAN),
    (Side.FP, Action.PICK), (Side.FB, Action.PICK),
]
POOL = 12


# ---------------------------------------------------------------- instanța redusă

@contextmanager
def schedule(spec: list[tuple[Side, Action]]):
    """Înlocuiește temporar ordinea CM din `game`. `DraftState` citește `SCHEDULE` și
    `N_TURNS` la fiecare apel, deci căutarea rulează neschimbată pe programul redus."""
    old = game.SCHEDULE, game.N_TURNS
    game.SCHEDULE = [Turn(i, side, action, 1) for i, (side, action) in enumerate(spec)]
    game.N_TURNS = len(spec)
    try:
        yield
    finally:
        game.SCHEDULE, game.N_TURNS = old


def submodel(model: DraftModel, pool: list[int]) -> DraftModel:
    idx = np.asarray(pool, dtype=np.intp)
    return DraftModel(beta=model.beta[idx].copy(),
                      counter=model.counter[np.ix_(idx, idx)].copy(),
                      synergy=model.synergy[np.ix_(idx, idx)].copy(),
                      meta={"source": "submodel", "pool": [int(h) for h in pool]})


class ExactSolver:
    """Minimax exact pe măști de biți, cu memoizare. Scris independent de `search/`,
    ca să poată servi drept referință pentru toți algoritmii."""

    def __init__(self, model: DraftModel, spec: list[tuple[Side, Action]]):
        self.n = model.n
        self.beta = model.beta.tolist()
        self.cnt = model.counter.tolist()
        self.syn = model.synergy.tolist()
        self.spec = spec
        self.T = len(spec)
        self.memo: dict[int, float] = {}

    def leaf(self, fp: list[int], fb: list[int]) -> float:
        b, c, y = self.beta, self.cnt, self.syn
        s = sum(b[a] for a in fp) - sum(b[x] for x in fb)
        s += sum(y[fp[i]][fp[j]] for i in range(len(fp)) for j in range(i + 1, len(fp)))
        s -= sum(y[fb[i]][fb[j]] for i in range(len(fb)) for j in range(i + 1, len(fb)))
        s += sum(c[a][x] for a in fp for x in fb)
        return 1.0 / (1.0 + math.exp(-s))

    def value(self, t: int, fp: int, fb: int, ban: int) -> float:
        if t == self.T:
            n = self.n
            return self.leaf([h for h in range(n) if fp >> h & 1],
                             [h for h in range(n) if fb >> h & 1])
        key = fp | fb << self.n | ban << (2 * self.n)
        v = self.memo.get(key)
        if v is not None:
            return v
        side, action = self.spec[t]
        used = fp | fb | ban
        best = -INF if side is Side.FP else INF
        for h in range(self.n):
            bit = 1 << h
            if used & bit:
                continue
            if action is Action.BAN:
                w = self.value(t + 1, fp, fb, ban | bit)
            elif side is Side.FP:
                w = self.value(t + 1, fp | bit, fb, ban)
            else:
                w = self.value(t + 1, fp, fb | bit, ban)
            best = max(best, w) if side is Side.FP else min(best, w)
        self.memo[key] = best
        return best

    def of(self, s: DraftState) -> float:
        m = lambda hs: sum(1 << h for h in hs)
        return self.value(s.turn, m(s.picks_fp), m(s.picks_fb), m(s.banned))

    def children(self, s: DraftState) -> dict[int, float]:
        return {h: self.of(s.apply(h)) for h in s.legal_moves()}


class AlphaBetaBoundedTT(AlphaBetaSearcher):
    """Alfa-beta cu tabela de transpoziții CORECTĂ: o valoare obținută după o retezare
    este doar o limită (inferioară la MAX, superioară la MIN) și se memorează cu un
    indicator EXACT / LOWER / UPPER. Restul algoritmului e identic cu `AlphaBetaSearcher`;
    varianta există doar în experiment, ca să se poată măsura efectul defectului."""
    name = "alphabeta-tt-corect"

    def _ab(self, state, depth, alpha, beta):
        self.nodes += 1
        if self.nodes % 256 == 0 and time.perf_counter() > self._deadline:
            raise _OutOfTime
        if state.is_terminal or depth <= 0:
            return self.leaf_value(state, Side.FP)

        key = (state.key(), depth)
        alpha0, beta0 = alpha, beta
        cached = self.tt.get(key)
        if cached is not None:
            flag, val = cached
            if flag == "exact":
                self.tt_hits += 1
                return val
            if flag == "lower":
                alpha = max(alpha, val)
            else:
                beta = min(beta, val)
            if alpha >= beta:
                self.tt_hits += 1
                return val

        maximising = state.current.side is Side.FP
        best = -INF if maximising else INF
        for hero in self._candidates(state, self.k):
            v = self._ab(state.apply(hero), depth - 1, alpha, beta)
            if maximising:
                best = max(best, v)
                alpha = max(alpha, best)
            else:
                best = min(best, v)
                beta = min(beta, best)
            if beta <= alpha:
                break

        flag = "upper" if best <= alpha0 else "lower" if best >= beta0 else "exact"
        self.tt[key] = (flag, best)
        return best


class AlphaBetaNoTT(AlphaBetaSearcher):
    """Alfa-beta fără tabelă de transpoziții: referința pentru „cât de mult contează TT"."""
    name = "alphabeta-fara-tt"

    def _ab(self, state, depth, alpha, beta):
        self.nodes += 1
        if state.is_terminal or depth <= 0:
            return self.leaf_value(state, Side.FP)
        maximising = state.current.side is Side.FP
        best = -INF if maximising else INF
        for hero in self._candidates(state, self.k):
            v = self._ab(state.apply(hero), depth - 1, alpha, beta)
            if maximising:
                best = max(best, v)
                alpha = max(alpha, best)
            else:
                best = min(best, v)
                beta = min(beta, best)
            if beta <= alpha:
                break
        return best


SEARCHERS = {**ALGORITHMS, "alphabeta-tt-corect": AlphaBetaBoundedTT,
             "alphabeta-fara-tt": AlphaBetaNoTT}


def random_prefix(n: int, t: int, rng: random.Random) -> DraftState:
    """O stare aleatoare la tura t: mutări legale uniforme de la începutul draftului."""
    s = DraftState(n_heroes=n)
    for _ in range(t):
        s = s.apply(rng.choice(s.legal_moves()))
    return s


def e1_configs(quick: bool, variant: str = "main") -> list[tuple[str, str, dict, int]]:
    """(etichetă, algoritm, opțiuni, semințe). Adâncimea „full" = toate turele rămase.

    `mcts-c`: sensibilitatea MCTS la constanta de explorare. Valorile P(FP) diferă între
    mutări cu câteva sutimi, iar c = 1,4 presupune diferențe de ordinul unității."""
    if variant == "mcts-c":
        return [(f"mcts c={c} {it} it", "mcts", {"iterations": it, "c": c}, 3)
                for c in (0.05, 0.2, 0.5, 1.4) for it in (200, 800, 3200)]
    cfg = [("greedy", "greedy", {}, 1)]
    for impl in ("alphabeta", "alphabeta-tt-corect"):
        for k in (3, 5, 12):
            for d in (2, 4, "full"):
                cfg.append((f"{impl} K={k} d={d}", impl, {"k": k, "depth": d}, 1))
    for it in ((50, 200, 800) if quick else (50, 200, 800, 3200)):
        cfg.append((f"mcts {it} it", "mcts", {"iterations": it}, 3 if quick else 5))
    return cfg


def run_search(name: str, model: DraftModel, opts: dict, state: DraftState):
    opts = dict(opts)
    if opts.get("depth") == "full":
        opts["depth"] = game.N_TURNS - state.turn
    return SEARCHERS[name](model, **opts).search(state)


def e1_pool(args: tuple) -> list[dict]:
    """Un pool de 12 eroi: solver exact o dată, apoi toate configurațiile pe toate stările."""
    source, pool_id, pool, states_per_pool, quick, seed, variant = args
    base = DraftModel.load(default_model_path()) if source == "real" else build_placeholder(127)
    model = submodel(base, pool)
    rows = []
    with schedule(REDUCED):
        solver = ExactSolver(model, REDUCED)
        t0 = time.perf_counter()
        root_value = solver.of(DraftState(n_heroes=POOL))
        exact_ms = (time.perf_counter() - t0) * 1000
        rng = random.Random(seed)
        turns = list(range(game.N_TURNS))
        picked = turns if states_per_pool >= len(turns) else sorted(rng.sample(turns, states_per_pool))
        for t in picked:
            s = random_prefix(POOL, t, rng)
            side = s.current.side
            vals = solver.children(s)
            vstar = solver.of(s)
            sign = 1.0 if side is Side.FP else -1.0
            regrets = {h: sign * (vstar - v) * 100 for h, v in vals.items()}
            spread = max(regrets.values())
            common = {"source": source, "pool": pool_id, "turn": t, "side": side.value,
                      "action": s.current.action.value, "n_legal": len(vals),
                      "v_star": vstar, "spread_pp": spread,
                      "random_regret_pp": float(np.mean(list(regrets.values())))}
            for label, algo, opts, seeds in e1_configs(quick, variant):
                for sd in range(seeds):
                    o = dict(opts)
                    if algo == "mcts":
                        o["seed"] = 1000 * pool_id + 10 * t + sd
                    r = run_search(algo, model, o, s)
                    reg = regrets[r.best]
                    rows.append({**common, "config": label, "algo": algo, "seed": sd,
                                 "best": r.best, "regret_pp": reg,
                                 "rel_regret": reg / spread if spread > 1e-12 else 0.0,
                                 "optimal": reg <= 1e-7,
                                 "ms": r.elapsed_ms, "nodes": r.nodes, "evals": r.evals,
                                 "depth": r.stats.get("depth"), "tt_hits": r.stats.get("tt_hits")})
        rows.append({"source": source, "pool": pool_id, "config": "_exact",
                     "root_value": root_value, "exact_ms": exact_ms,
                     "exact_states": len(solver.memo)})
    return rows


def run_e1(a) -> Path:
    real = DraftModel.load(default_model_path())
    rng = np.random.default_rng(a.seed)
    tasks = []
    for source in ("real", "placeholder"):
        for i in range(a.pools):
            pool = sorted(int(h) for h in rng.choice(real.n, POOL, replace=False))
            tasks.append((source, i, pool, a.states, a.quick, a.seed + i, a.variant))
    rows: list[dict] = []
    t0 = time.perf_counter()
    if a.workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(a.workers) as ex:
            for i, part in enumerate(ex.map(e1_pool, tasks)):
                rows.extend(part)
                print(f"  pool {i + 1}/{len(tasks)} gata ({time.perf_counter() - t0:.0f} s)", flush=True)
    else:
        for i, task in enumerate(tasks):
            rows.extend(e1_pool(task))
            print(f"  pool {i + 1}/{len(tasks)} gata ({time.perf_counter() - t0:.0f} s)", flush=True)
    name = "e1" if a.variant == "main" else f"e1-{a.variant}"
    return save(name, {"args": vars(a), "schedule": [(s.value, x.value) for s, x in REDUCED],
                       "pool_size": POOL, "rows": rows})


# ---------------------------------------------------------------- instanța completă

def e2_configs(quick: bool) -> list[tuple[str, str, dict, int]]:
    cfg = [("greedy", "greedy", {}, 1)]
    for d in (2, 4, 6):
        cfg.append((f"alphabeta K=10 d={d}", "alphabeta", {"k": 10, "depth": d}, 1))
    for b in (100, 500, 2000):
        cfg.append((f"alphabeta K=10 {b} ms", "alphabeta", {"k": 10, "time_budget_ms": b}, 1))
    for it in ((100, 400, 1600) if quick else (100, 400, 1600, 6400)):
        cfg.append((f"mcts {it} it", "mcts", {"iterations": it}, 3 if quick else 5))
    return cfg


E2_TURNS = (0, 4, 7, 9, 12, 15, 18, 20, 22, 23)


def run_e2(a) -> Path:
    model = DraftModel.load(default_model_path())
    rng = random.Random(a.seed)
    rows = []
    t0 = time.perf_counter()
    for rep in range(a.states):
        for t in E2_TURNS:
            s = random_prefix(model.n, t, rng)
            for label, algo, opts, seeds in e2_configs(a.quick):
                for sd in range(seeds):
                    o = dict(opts)
                    if algo == "mcts":
                        o["seed"] = 100 * rep + t * 7 + sd
                    r = SEARCHERS[algo](model, **o).search(s)
                    rows.append({"rep": rep, "turn": t, "phase": s.current.phase,
                                 "action": s.current.action.value, "side": s.current.side.value,
                                 "config": label, "algo": algo, "seed": sd, "best": r.best,
                                 "value": r.top[0].value, "ms": r.elapsed_ms, "nodes": r.nodes,
                                 "evals": r.evals, "depth": r.stats.get("depth"),
                                 "ebf": r.stats.get("ebf"), "tt_hits": r.stats.get("tt_hits"),
                                 "tt_size": r.stats.get("tt_size")})
        print(f"  repetiția {rep + 1}/{a.states} gata ({time.perf_counter() - t0:.0f} s)", flush=True)
    return save("e2", {"args": vars(a), "turns": E2_TURNS, "rows": rows})


# ---------------------------------------------------------------- turneu

PLAYERS = {  # configurațiile din interfață (web/app.js, optsFor)
    "greedy": ("greedy", {}),
    "alphabeta": ("alphabeta", {"time_budget_ms": 500, "k": 10}),
    "mcts": ("mcts", {"iterations": 800}),
}


def play(fp: str, fb: str, opening: tuple[int, int], seed: int, model: DraftModel) -> dict:
    s = DraftState(n_heroes=model.n)
    for h in opening:
        s = s.apply(h)
    cost = {Side.FP.value: [], Side.FB.value: []}
    depths = []
    while not s.is_terminal:
        side = s.current.side
        name = fp if side is Side.FP else fb
        algo, opts = PLAYERS[name]
        o = dict(opts)
        if algo == "mcts":
            o["seed"] = seed * 100 + s.turn
        r = ALGORITHMS[algo](model, **o).search(s)
        cost[side.value].append(r.elapsed_ms)
        if algo == "alphabeta":
            depths.append(r.stats.get("depth"))
        s = s.apply(r.best)
    p = float(sigmoid(model.score(s.picks_fp, s.picks_fb)))
    return {"fp": fp, "fb": fb, "opening": list(opening), "p_fp": p,
            "picks_fp": list(s.picks_fp), "picks_fb": list(s.picks_fb),
            "banned": sorted(s.banned), "ms_fp": float(np.mean(cost["FP"])),
            "ms_fb": float(np.mean(cost["FB"])), "ab_depths": depths}


def _play_task(args):
    fp, fb, opening, seed = args
    return play(fp, fb, tuple(opening), seed, DraftModel.load(default_model_path()))


def run_tournament(a) -> Path:
    model = DraftModel.load(default_model_path())
    rng = random.Random(a.seed)
    openings = [tuple(rng.sample(range(model.n), 2)) for _ in range(a.openings)]
    tasks = [(fp, fb, op, i) for i, op in enumerate(openings)
             for fp in PLAYERS for fb in PLAYERS]
    games = []
    t0 = time.perf_counter()
    if a.workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(a.workers) as ex:
            for i, g in enumerate(ex.map(_play_task, tasks)):
                games.append(g)
                if (i + 1) % 9 == 0:
                    print(f"  {i + 1}/{len(tasks)} drafturi ({time.perf_counter() - t0:.0f} s)", flush=True)
    else:
        for i, task in enumerate(tasks):
            games.append(_play_task(task))
            if (i + 1) % 9 == 0:
                print(f"  {i + 1}/{len(tasks)} drafturi ({time.perf_counter() - t0:.0f} s)", flush=True)
    return save("tournament", {"args": vars(a), "players": PLAYERS,
                               "openings": [list(o) for o in openings], "games": games})


# ---------------------------------------------------------------- verificări

def selftest() -> None:
    """Solverul exact față de un minimax naiv pe DraftState (instanță minusculă), apoi
    alfa-beta cu lățime și adâncime complete față de solver, pe instanța redusă."""
    tiny = [(Side.FP, Action.BAN), (Side.FB, Action.PICK), (Side.FP, Action.PICK),
            (Side.FP, Action.PICK), (Side.FB, Action.PICK), (Side.FB, Action.BAN)]
    real = DraftModel.load(default_model_path())
    m = submodel(real, [3, 9, 17, 25, 40, 51, 66, 80])

    def naive(s: DraftState) -> float:
        if s.is_terminal:
            return float(sigmoid(m.score(s.picks_fp, s.picks_fb)))
        vals = [naive(s.apply(h)) for h in s.legal_moves()]
        return max(vals) if s.current.side is Side.FP else min(vals)

    with schedule(tiny):
        s0 = DraftState(n_heroes=m.n)
        a, b = ExactSolver(m, tiny).of(s0), naive(s0)
        print(f"solver exact {a:.12f} · minimax naiv {b:.12f}")
        assert abs(a - b) < 1e-12
    leaf = ExactSolver(m, tiny).leaf([0, 1, 2], [3, 4])
    assert abs(leaf - float(sigmoid(m.score((0, 1, 2), (3, 4))))) < 1e-12
    print("evaluarea frunzelor coincide cu DraftModel.score")

    pool = sorted(random.Random(1).sample(range(real.n), POOL))
    m = submodel(real, pool)
    with schedule(REDUCED):
        solver = ExactSolver(m, REDUCED)
        rng = random.Random(2)
        bad = {"alphabeta": 0, "alphabeta-tt-corect": 0, "alphabeta-fara-tt": 0}
        for t in range(2, 10):
            s = random_prefix(POOL, t, rng)
            vals, vstar = solver.children(s), solver.of(s)
            for name in bad:
                r = SEARCHERS[name](m, k=POOL, depth=game.N_TURNS - t).search(s)
                if abs(vals[r.best] - vstar) > 1e-9:
                    bad[name] += 1
        print("mutări neoptime la lățime și adâncime complete (din 8 stări):", bad)


# ---------------------------------------------------------------- persistență

def save(name: str, payload: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = RESULTS / f"{name}-{stamp}.json"
    payload = {"experiment": name, "created": stamp, "python": sys.version.split()[0],
               "numpy": np.__version__, "model_meta": DraftModel.load(default_model_path()).meta,
               **payload}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    rows = payload.get("rows") or payload.get("games")
    if rows:
        keys = sorted({k for r in rows for k in r})
        with open(path.with_suffix(".csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
    print(f"scris {path}")
    return path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("experiment", choices=["selftest", "e1", "e2", "tournament"])
    ap.add_argument("--seed", type=int, default=20261023)
    ap.add_argument("--pools", type=int, default=30, help="E1: pool-uri per sursă")
    ap.add_argument("--states", type=int, default=10, help="E1: stări per pool; E2: repetiții")
    ap.add_argument("--openings", type=int, default=20, help="turneu: deschideri")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--variant", choices=["main", "mcts-c"], default="main",
                    help="E1: configurațiile principale sau sensibilitatea MCTS la c")
    a = ap.parse_args()
    {"selftest": lambda: selftest(), "e1": lambda: run_e1(a), "e2": lambda: run_e2(a),
     "tournament": lambda: run_tournament(a)}[a.experiment]()


if __name__ == "__main__":
    main()
