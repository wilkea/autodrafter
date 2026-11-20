# 5. Item builds — the optional module with a provable guarantee

You correctly noted that item builds are less about drafting and more about game
planning. Keep them as a **separate, clearly bounded module**. There is one strong reason
to include them anyway: **this is the only part of the project where you can state and
prove an approximation bound.** Everything else is heuristic.

---

## 5.1 Formulation — budgeted maximum coverage

Given a completed draft:

- Compute the enemy's **threat vector** `T ∈ R^m` over threat types (physical burst,
  magical burst, disable duration, illusions/summons, silences, high mobility, sustain,
  invisibility, …). This reuses the hero capability vectors from doc 03 — no new data.
- Each item `i` has a **counter-coverage vector** `c_i ∈ R^m` and a **gold cost** `g_i`
  (BKB covers magical + disable; Blademail covers physical burst; dust/sentry covers
  invisibility; Mjollnir covers illusions; etc.). Item stats are parseable from the game
  files, same pipeline as heroes.
- Choose a set `S` of items for a hero, subject to `Σ_{i∈S} g_i ≤ G` (gold available at
  time `T`) and `|S| ≤ 6` (inventory slots), maximising

```
f(S) = Σ_k  T_k · min( 1 , Σ_{i∈S} c_{i,k} )          # saturating coverage
```

## 5.2 Why this is a good algorithms problem

- `f` is **monotone and submodular** — the `min(1, ·)` saturation gives diminishing
  returns, which is exactly submodularity (a second BKB adds nothing). This is worth a
  short proof in the report; it is a three-line argument.
- The problem is **NP-hard** (it contains max-coverage / knapsack).
- Therefore **cost-benefit greedy** (repeatedly take the item maximising marginal gain
  per gold) with the standard partial-enumeration fix achieves **`1 − 1/e ≈ 0.632`** of
  the optimum. A clean, citable theorem in an otherwise empirical project.
- And you can compute the **exact optimum** for realistic instances via
  **multi-dimensional knapsack DP** over (gold × slots), pseudo-polynomial `O(n · G · 6)`
  — gold discretised to 100-gold buckets keeps it small.

→ **The experiment:** measure greedy's *empirical* ratio against the DP optimum across
many drafts and show it lands around 0.9–1.0, far above the 0.632 worst-case bound. That
"theory vs practice" gap is a classic, well-received result.

## 5.3 Harder variant, if you want it

Purchase **order** matters (an item at 18 min is worth more than at 35 min). Model as a
time-indexed DP / resource-constrained shortest path:

```
state  = (time bucket, gold on hand, set of items owned)
value  = ∫ power(t) dt  over the game
```

The `2^n` item-subset component blows up, so restrict to a shortlist of ~15 candidate
items and prune dominated states. Note the blow-up explicitly in the report — recognising
why the clean formulation is intractable is itself worth marks.

## 5.4 Recommendation

Ship it **only after** the draft module is complete and evaluated. Frame it in the
proposal as "extension module (E1)" with a clear cut line, so dropping it costs you
nothing.
