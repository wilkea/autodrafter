# 1. Problem formalisation

## 1.1 Why this is a legitimate algorithms problem

The draft in Dota 2 Captain's Mode is a **finite, deterministic, perfect-information,
two-player zero-sum sequential game**. That single sentence is what makes it gradeable
as an algorithms project rather than a data-science project: it has a well-defined
optimal solution (a minimax value), that optimum is provably unreachable by brute force,
and therefore the whole project becomes *"which approximation algorithm gets closest,
at what cost?"* — which is exactly the shape of an algorithms course deliverable.

Keep this framing in the proposal. Do **not** frame it as "predict the winner with ML";
that is a different (and much more boring) project.

## 1.2 Definitions

- `H` — set of heroes, `n = |H| ≈ 126` (patch-dependent).
- A **state** `s = (B, P_R, P_D, t)` where
  - `B ⊆ H` — banned heroes,
  - `P_R, P_D ⊆ H` — Radiant / Dire picks, `|P_R|, |P_D| ≤ 5`,
  - `t ∈ {0..23}` — turn index,
  - all three sets pairwise disjoint (a hero is used at most once).
- A **turn schedule** `τ(t) → (side, action)` with `action ∈ {pick, ban}` is **fixed and
  public** by the patch (currently 7 bans + 5 picks per side, 24 plies total). This is
  important: the game tree's shape is known in advance, no chance nodes, no hidden info.
- **Legal moves** at `s`: `A(s) = H \ (B ∪ P_R ∪ P_D)`, so `|A(s)| = n − t`.
- **Terminal state**: `t = 24`, i.e. both sides have 5 heroes.
- **Payoff**: `V(P_R, P_D) = Pr[Radiant wins]` ∈ (0,1). Zero-sum because Dire's payoff
  is `1 − V`.

## 1.3 The problem statement (put this verbatim in your proposal)

> Given a draft state `s`, the known turn schedule `τ`, and an evaluation function
> `V` over complete lineups, compute the action `a ∈ A(s)` that maximises the acting
> side's minimax value, assuming the opponent also plays to maximise their own value.

Formally, the game value is defined by backward induction:

```
val(s) = V(P_R, P_D)                                if t = 24
val(s) = max_{a ∈ A(s)} val(s ⊕ a)                  if τ(t) acts for the maximising side
val(s) = min_{a ∈ A(s)} val(s ⊕ a)                  otherwise
```

Bans are handled by the same recursion — a ban is just a move that removes a hero
from `A` without adding it to either lineup. No special case is needed, which is a
nice property worth pointing out in the write-up.

## 1.4 Why brute force is impossible (your complexity section)

Branching factor `b_t = n − t`, depth `d = 24`.

Number of leaves of the naive game tree:

```
∏_{t=0}^{23} (n − t) = n! / (n − 24)!  ≈  126 × 125 × … × 103  ≈  1.3 × 10^49
```

Collapsing order-irrelevant permutations (ban order within a phase doesn't matter,
pick order within a side doesn't change the lineup) still leaves roughly

```
C(126, 24) × (24! / (14! · 5! · 5!))  ≈  10^30 distinct reachable terminal configurations
```

and the number of distinct *final lineup pairs* alone is

```
C(126,5) × C(121,5) ≈ 2.3 × 10^8 × 1.9 × 10^8 ≈ 4 × 10^16
```

(the ~1.56 × 10^16 figure quoted in the RecSys'18 paper is the same quantity computed
slightly differently). At 1 ns per evaluation that is ~1.3 years just to score the
leaves of a *single* fully-specified subtree, ignoring the search above it.

**Conclusion for the report:** exact backward induction is infeasible; the transposition
table needed for a DP over subsets would have `2^126` entries. Hence approximation.

## 1.5 The decomposition that makes the project tractable

Split the system in two, exactly like a chess engine:

```
        SEARCH                                  EVALUATION
 which hero to take next            how good is a finished 5v5 lineup
 (greedy / αβ / MCTS)               (statistics + hero model + player model)
```

This separation is the single most useful design decision in the project because:

1. You can **swap search algorithms while holding the evaluator fixed** — that is a
   controlled experiment, and it is what your algorithm comparison chapter needs.
2. You can **swap evaluators while holding the search fixed** — that is your ablation
   study for the "hero modelling" chapters.
3. The evaluator is where all the domain knowledge and all the messy data lives, so it
   can be developed and validated independently (log-loss on held-out matches) without
   ever running a search.

## 1.6 Sub-problem: hero → player/role assignment

A lineup is not just a set of five heroes; it is five heroes *assigned to five players*
occupying positions 1–5. The value of `{Anti-Mage, Invoker, ...}` depends on who plays
what. So the evaluator internally solves:

> maximise `Σ_i fit(player_i, hero_{σ(i)})` over all perfect matchings `σ`

This is the **assignment problem** on a 5×5 bipartite graph — solved exactly by the
**Hungarian algorithm in O(k³)**. Include it deliberately: it gives the project one
component with a *proven-optimal polynomial algorithm*, in contrast to the heuristic
outer search. Supervisors like that contrast.

## 1.7 Chess is not the right comparison — say so explicitly

| | chess | Dota draft |
|---|---|---|
| depth | ~80 plies | 24 plies (shallow) |
| branching | ~35 | ~110 (huge) |
| evaluation | cheap, fairly well understood | **the hard part**, must be learned from data |
| ground truth | endgame tablebases exist | none; only noisy match outcomes |

The difficulty in chess is depth; here it is **width + an evaluation function that has
to be inferred statistically**. That single table is a good intro paragraph — it
pre-empts the "isn't this just chess?" question in the defence.
