# 2. Algorithms

You need 2–3 algorithms that solve *the same* problem and can be compared fairly.
Recommended set, in increasing sophistication. All three consume the identical
evaluator `V`, so any difference in results is attributable to the search alone.

---

## 2.1 Baseline — Greedy / myopic best response

At each turn, score every legal hero by the immediate change in evaluation of the
partial lineup, take the argmax.

```
best = argmax_{h ∈ A(s)}  Ṽ(P_side ∪ {h}, P_enemy)
```

- **Cost:** `O(|A(s)|)` evaluator calls per turn, `O(n·d)` for the whole draft. Trivial.
- **Why it's wrong:** it is blind to the *sequence*. Two concrete failure modes to
  demonstrate in the report:
  - **Contested hero:** hero X is great for both sides. Greedy first-pick takes its own
    best hero and loses X; a searching agent takes X (or bans it) because it knows the
    enemy picks next.
  - **Last-pick advantage:** the side picking last should keep its lineup flexible and
    counter-pick; greedy commits early.
- **Value to the project:** it is the honest baseline, it is what the 2013 Stanford
  recommender did, and beating it in self-play is your first real result.

A useful variant worth including as "greedy+": **greedy with one-ply opponent lookahead**
(pick the hero maximising `V` after the opponent's greedy reply). Cheap, and it closes
part of the gap — good data point for the quality/cost curve.

---

## 2.2 Minimax with alpha–beta pruning, depth limit, and candidate beaming

Standard adversarial search over the draft tree, cut off at depth `d'` with a heuristic
evaluation of the partial state.

```
αβ(s, α, β, depth):
    if depth == 0 or terminal(s): return eval(s)
    for h in candidates(s, K):          # ordered, truncated
        v = αβ(s ⊕ h, α, β, depth-1)
        ... standard α/β update, cutoff when β ≤ α
```

**The critical implementation detail is `candidates(s, K)`.** With `b ≈ 110`, even depth
4 is `110^4 ≈ 1.5 × 10^8` nodes. So you restrict to the top `K` heroes by the greedy
heuristic (a *beam*), typically `K = 8..20`. This makes the algorithm **inadmissible**
(it can prune the optimal move) — say so honestly; it becomes a tunable
quality-vs-compute knob and that is exactly what you want to plot.

- **Complexity:** `O(K^{d'})` naive, `O(K^{d'/2})` with perfect move ordering — and you
  *have* good move ordering for free from the greedy score, so measure the **effective
  branching factor** `EBF = (nodes)^{1/d'}` empirically and show it sits near `√K`. That
  measurement is a genuinely nice experimental result.
- **Extras worth implementing:** transposition table keyed by the canonical
  `(frozenset(B), frozenset(P_R), frozenset(P_D), t)` — transpositions are *extremely*
  common here since pick order within a phase doesn't matter, so the TT hit rate will be
  high and it is easy to report. Iterative deepening gives you anytime behaviour.
- **Weakness to discuss:** the draft has 24 plies; depth 4–6 is myopic about the endgame,
  and the evaluator on *partial* lineups is much less reliable than on complete ones.

---

## 2.3 Monte Carlo Tree Search (UCT)

The method used by the published state of the art for this exact problem.

```
loop until budget exhausted:
    SELECT   descend the tree by UCB1:  argmax  Q(s,a) + c·sqrt(ln N(s) / N(s,a))
    EXPAND   add one child
    ROLLOUT  complete the draft with a cheap policy to a terminal lineup
    BACKUP   propagate V(terminal) up the path, negating for the opposing side
```

- **Why it fits:** it reaches *terminal* states, where your evaluator is trained and
  trustworthy — it never has to guess the value of a half-finished lineup. It handles
  the huge branching factor by sampling, it is **anytime** (stop whenever), and its
  quality grows smoothly with iterations, giving you a beautiful quality-vs-budget plot.
- **Rollout policy choices** (an experiment in itself): uniform random, greedy,
  ε-greedy, or sample from the empirical pick distribution of real pro drafts. Smarter
  rollouts converge faster per iteration but cost more per iteration — plot both axes.
- **Tuning:** exploration constant `c` (start at `√2` for payoffs in [0,1]), progressive
  widening if you want to limit the effective branching, RAVE/AMAF is a natural fit here
  because "hero X was picked somewhere in this subtree" is a strong signal regardless of
  when it was picked. RAVE is a good stretch goal.
- **Reported result to aim for:** the RecSys'18 work found UCT with ≥400 iterations beat
  every non-UCT strategy; you should be able to reproduce that shape.

---

## 2.4 The ground-truth trick — make one instance exactly solvable

This is the highest-value idea in the whole plan, and it is what turns "I built a bot"
into "I measured approximation quality".

Restrict to a **reduced hero pool** (`n' = 10–14 heroes`) and a **shortened schedule**
(e.g. 2 bans + 3 picks per side, 10 plies). Then exact backward induction is feasible:

```
states ≈ 3^{n'}   (each hero is: available / taken-by-R / taken-by-D / banned → 4^{n'} upper bound)
n'=12 → ~1.7×10^7 states with memoisation — computable in seconds
```

Now you have the **true minimax value**, and you can report, for each algorithm:

- **optimality gap** = `val*(root) − val(move chosen)`, averaged over random start states;
- **exact-move agreement rate** (% of positions where the algorithm picks an optimal move);
- how the gap shrinks with `K`, `d'`, MCTS iterations.

Do this on synthetic *and* on real (top-12 meta heroes) pools. Almost no student project
has a ground-truth baseline; this one gets it essentially for free.

---

## 2.5 Optional third/fourth algorithm, if you want more breadth

| algorithm | where it fits | why include it |
|---|---|---|
| **Hungarian algorithm** `O(k³)` | hero → player/role assignment inside the evaluator | exact, polynomial, textbook; contrasts with the heuristic outer search |
| **Greedy submodular maximisation** `(1 − 1/e)` | item-build selection (see doc 05) | gives the project one *provable approximation guarantee* |
| **0/1 & multi-dimensional knapsack DP** | exact item build under gold budget | pseudo-polynomial; compare greedy's empirical ratio against the 0.63 bound |
| **Beam search / DP over subsets** | draft on the reduced pool | bridges greedy and exact; nice intermediate point |

**Recommendation:** ship greedy + αβ + MCTS as the three compared draft algorithms, and
include Hungarian as a required component. Add the item module only if time allows —
but note it is the only place in the project where you can state a *theorem*.

---

## 2.6 Complexity summary table (draft this early, fill in measured numbers later)

| algorithm | time / turn | space | optimal? | anytime? | measured gap |
|---|---|---|---|---|---|
| Greedy | `O(n)` evals | `O(1)` | no | n/a | |
| Greedy + 1-ply | `O(n²)` | `O(1)` | no | n/a | |
| αβ, beam `K`, depth `d'` | `O(K^{d'/2})`–`O(K^{d'})` | `O(K·d')` + TT | optimal within `(K, d')` only | via iterative deepening | |
| MCTS/UCT, `m` iters | `O(m · d)` | `O(m)` | asymptotically, in the limit | yes | |
| Exact backward induction | `O(4^{n'})` | `O(4^{n'})` | **yes** | no | 0 by definition |
