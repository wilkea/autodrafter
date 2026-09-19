# autodrafter

Planning and research for a university algorithms project: **optimal hero drafting in
Dota 2 Captain's Mode**, framed as a finite two-player zero-sum perfect-information
game, and attacked with several approximation algorithms whose quality is measured
against an exactly solvable reduced instance.

**Status: planning / research only. No implementation yet.**

## The one-paragraph pitch

The Captain's Mode draft is a 24-ply game with a branching factor of ~110, giving on the
order of 10^30 reachable positions — exact backward induction is impossible. The project
therefore compares **greedy**, **alpha–beta with beam search**, and **Monte Carlo Tree
Search** on an identical evaluation function, measures the quality/compute trade-off, and
obtains *true* optimality gaps by solving a reduced-hero-pool variant exactly. The
evaluation function is built in three separable, independently ablatable layers:
statistical (winrate / counter / synergy), semantic (hero capability vectors derived from
game files and telemetry), and player-specific (per-player hero proficiency, fused via
the Hungarian algorithm).

## Documents

| # | document | contents |
|---|---|---|
| 01 | [Problem](docs/01-problem.md) | game-theoretic formalisation, state space, complexity bounds, search/eval decomposition |
| 02 | [Algorithms](docs/02-algorithms.md) | greedy, alpha–beta + beam + TT, MCTS/UCT, the exactly-solvable ground-truth instance, complexity table |
| 03 | [Hero model](docs/03-hero-model.md) | **how to turn heroes into numbers objectively**: log-odds, shrinkage, factorisation, capability vectors from game files + telemetry, patch scalability |
| 04 | [Player model](docs/04-player-model.md) | hierarchical per-player hero proficiency, recency decay, playstyle vectors, Hungarian assignment, data-access warnings |
| 05 | [Items](docs/05-items.md) | budgeted max-coverage, submodularity, greedy's (1−1/e) guarantee vs exact DP |
| 06 | [Data & evaluation](docs/06-data-and-evaluation.md) | data sources, chronological splits, metrics, ablations, threats to validity |
| 07 | [Prior art](docs/07-prior-art.md) | the existing MOBA-drafting literature and structurally identical problems elsewhere |
| 08 | [Roadmap](docs/08-roadmap.md) | scope cuts, risks, 12-week timeline, repo layout, questions for the supervisor |

## Reading order if you only have ten minutes

`docs/01` §1.3–1.5 → `docs/02` §2.4 → `docs/03` §3.2 → `docs/08` §8.1.
