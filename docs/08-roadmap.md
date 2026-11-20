# 8. Scope, risks and roadmap

## 8.1 Recommended scope

Your idea is currently ~3 projects stacked (draft search, hero modelling, player
modelling, item builds). Cut it like this:

**Core (must ship — this alone is a complete project):**
- C1. Draft game formalisation + complexity analysis.
- C2. Statistical evaluator (Layer A: ridge logistic regression + low-rank interactions).
- C3. Three search algorithms: greedy, alpha–beta with beam + TT, MCTS/UCT.
- C4. Exactly solvable reduced instance → true optimality gaps.
- C5. Self-play tournament + quality-vs-compute curves.

**Extensions, in priority order (take as many as time allows, and say in the proposal
that they are optional):**
- E1. Semantic/capability layer + composition penalties (doc 03 Layer B), with the
      cold-start and patch-transfer experiments. *Highest value of the extensions —
      it is the part of your original idea that no one else has published well.*
- E2. Player/roster model + Hungarian assignment (doc 04).
- E3. Item builds as budgeted max-coverage, greedy vs DP (doc 05). *Take this one if
      your supervisor wants more formal theory — it's the only provable guarantee.*
- E4. Best-of-N series drafting (hero used once per series) — genuinely novel-ish.

**Explicitly out of scope (write this down):** in-game play, execution skill, team
chemistry, live patch prediction, real-time integration with the game client.

## 8.2 Risks and mitigations

| risk | mitigation |
|---|---|
| Data collection eats the semester | Use OpenDota bulk dumps, not per-match API calls. Cache to Parquet on day one. Budget 1 week, cap it hard. |
| Evaluator is weak → everything downstream looks bad | Decoupled design: the search comparison is valid *regardless* of evaluator quality, and the exact-instance ground truth doesn't need real data at all. Say this in the proposal. |
| Hand-authored hero tags become an endless subjective slog | Sources 1 and 2 in doc 03 (game files + telemetry) are automated. Cap manual labels at ≤3 axes. |
| Scope creep from items + players | They are E-tier. Cut line is pre-declared. |
| "Is this an algorithms project or an ML project?" | Lead with the game-tree formalisation, complexity bounds, and optimality gaps. The ML is a *component* of the evaluator, not the thesis. |
| Dotabuff ToS / data ethics | Use OpenDota/STRATZ only; add a short data-ethics paragraph. |

## 8.3 Suggested timeline (~12 weeks; compress proportionally)

| week | deliverable |
|---|---|
| 1 | Proposal, formalisation, complexity analysis (doc 01). Data source decided. |
| 2 | Data pipeline: bulk match dump → local store. Hero constants parsed. |
| 3 | Layer A evaluator; log-loss/Brier/calibration on a held-out chronological split. |
| 4 | Greedy agent end-to-end. **First full system working — de-risked.** |
| 5 | Reduced-pool exact solver + the game-tree infrastructure (state, legal moves, TT). |
| 6 | Alpha–beta with beam and move ordering; EBF and TT-hit measurements. |
| 7 | MCTS/UCT; rollout-policy experiments; anytime curves. |
| 8 | Self-play tournament + optimality gaps. **Core complete.** |
| 9–10 | E1 semantic layer + composition features; ablations; patch-transfer test. |
| 11 | E2 player model + Hungarian (or E3 items, if you prefer the theory). |
| 12 | Write-up, figures, threats to validity, defence prep. |

Ship the core by week 8 even if it is ugly. Every extension after that is upside; nothing
after week 8 is load-bearing.

## 8.4 Suggested repository layout

```
autodrafter/
  docs/                  # this planning material, then the report
  schema/features.yaml   # capability-dimension definitions (doc 03)
  etl/                   # data collection + feature construction
  data/patches/<patch>/  # generated values, never hand-edited
  labels/                # the few manual labels, versioned, with annotator IDs
  drafter/
    game.py              # state, legal moves, turn schedule, terminal test
    eval/                # layer_a.py, layer_b.py, player.py, assignment.py
    search/              # greedy.py, alphabeta.py, mcts.py, exact.py
  experiments/           # one script per experiment, writes results/<name>/<ts>.json
  results/
  tests/
```

Keeping `game.py` free of any evaluation logic is what lets you swap searches and
evaluators independently — the whole methodology depends on that boundary holding.

## 8.5 Three questions to settle with your supervisor before week 2

1. **Is an ML-fitted evaluation function acceptable inside an algorithms project?**
   (Pitch: yes, because the algorithmic contribution is the search + the measured
   approximation quality, and the evaluator is deliberately held constant across the
   comparison.)
2. **Is reproducing an existing published approach (MCTS drafting) acceptable, with the
   contribution being the controlled comparison + optimality gaps + layered evaluator?**
   (This is the honest positioning from doc 07 §7.3.)
3. **How many algorithms do they actually want compared — 2, 3, or "3 plus components"?**
   That determines whether Hungarian and the item module are required or optional.
