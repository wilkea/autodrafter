# 7. Prior art and comparable projects

You asked whether anything comparable exists. It does — this exact problem has a small
but real academic literature, which is *good news* for a university project: you can cite
a state of the art, reproduce it, and position your work against it instead of claiming
novelty you can't defend.

## 7.1 Directly on MOBA drafting

- **Chen, Nguyen, Sun et al., "The Art of Drafting: A Team-Oriented Hero Recommendation
  System for MOBA Games", RecSys 2018.** Models Dota 2 Captain's Mode as a combinatorial
  game and uses **MCTS/UCT** with a neural winrate predictor. Reports UCT with ≥400
  iterations beating every non-UCT baseline (93% vs random, 88% vs association rules).
  **This is your closest reference and it directly validates the greedy-vs-MCTS
  comparison you're planning.** arXiv:1806.10130.
- **Chen et al., "Which Heroes to Pick? Learning to Draft in MOBA Games with Neural
  Networks and Tree Search" (JueWuDraft), IEEE ToG 2021**, arXiv:2012.10171. MCTS + a
  value network, on *Honor of Kings*. Its distinctive contribution is handling the
  **best-of-N series** constraint (a hero can only be drafted once across the series) —
  which is a genuinely underexplored angle and would be a strong, *novel* extension for
  your project if you want one.
- **Lee, Hwang et al., "DraftRec: Personalized Draft Recommendation", WWW 2022**,
  arXiv:2204.12750, code at `github.com/dojeon-ai/DraftRec`. Two transformer networks —
  a *player* network for individual champion preference and a *match* network for
  interactions. **This is the published version of your player-roster idea**, and its
  released dataset includes 50k Dota 2 matches you could reuse.
- **Conley & Perry, "How Does He Saw Me? A Recommendation Engine for Picking Heroes in
  Dota 2", Stanford CS229, 2013.** Logistic regression + kNN on hero-presence features
  (~70% accuracy) and a **greedy** incremental recommender. This is precisely your
  baseline — cite it as the thing you must beat.
- **Agarwala & Pearce, "Learning Dota 2 Team Compositions", CS229 2014** — role and
  composition structure; relevant to doc 03's semantic layer.
- **Association-rule line-up recommenders** (used as a baseline in the RecSys'18 paper) —
  cheap to implement, worth having as a third baseline.

## 7.2 Structurally identical problems outside Dota

Use these when arguing that your design choices are standard practice, not invention:

- **Magic: The Gathering draft bots** (17Lands data, Cube Cobra's draftbot). Sequential
  pick under a *shared, depleting* pool, with synergy and curve/coverage constraints —
  structurally the closest non-MOBA analogue that exists, and the "pick order matters,
  the pool is contested" dynamic is identical.
- **Adjusted Plus-Minus / RAPM in basketball.** Ridge regression on lineup indicator
  variables to isolate one participant's contribution from team-level outcomes. This is
  *mathematically the same estimator* as your hero-strength model (doc 03 §3.1d) — the
  single best citation for why you fit `β_h` jointly rather than computing raw winrates.
- **Pokémon VGC / Smogon team building.** Type- and role-coverage vectors, usage-weighted
  metagame statistics, matchup matrices. The "coverage vector + unmet need" idea in
  doc 03 is completely standard there, which is a good argument that it is sound.
- **Fantasy-sports / DFS lineup optimisation.** Knapsack/ILP with correlation terms —
  the roster-fit and budget pieces.
- **Football (soccer) player valuation (VAEP, xT, expected possession value).** How the
  sports-analytics field turns qualitative scouting language into telemetry-derived
  numbers — the exact methodology you need for doc 04's playstyle vectors.
- **Combinatorial auctions / sequential resource allocation.** The general theory behind
  "the pool is shared and depleting, so taking X denies X".

## 7.3 How to position your project

Honest positioning, which is stronger than false novelty:

> The core technique (MCTS over the draft tree) is established. This project's
> contribution is (a) a **controlled comparison** of greedy, alpha–beta and MCTS under an
> identical evaluator, including an **exactly solvable reduced instance that gives true
> optimality gaps**, and (b) an evaluation function built as three separable layers —
> statistical, semantic/capability, and player-specific — whose relative value is measured
> by ablation, including **cold-start and cross-patch-transfer** tests that the existing
> literature does not report.

That is a defensible, achievable, and genuinely interesting claim.
