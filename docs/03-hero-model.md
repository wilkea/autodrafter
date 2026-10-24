# 3. Turning heroes into numbers (the evaluation function)

This is the chapter you said you have no idea how to do. The answer has three layers.
Build them in this order; each one is independently useful and independently testable.

**The governing principle: you never invent the numbers, and you never invent the
weights.** You define *what is measured* and *how it is measured*; the values come from
game files or telemetry, and the weights come from fitting against real match outcomes.
Anything you hand-author is a bug waiting to happen at the next patch.

---

## 3.1 Layer A — Relational / statistical (winrate, counter, synergy)

The layer you already described. Three things will make it correct rather than naive.

### (a) Work in log-odds, not winrate

Winrates don't add; log-odds do. Define `ℓ(p) = ln(p / (1−p))`. Then a lineup score is a
sum of terms and the final probability is `σ(score)` — clean, and it is exactly what a
logistic regression fits.

### (b) Measure *deviation from the additive baseline*, not raw pair winrate

Raw "A+B win 56% together" mostly tells you that A is a strong hero. The actual synergy
is the interaction term:

```
syn(a,b)   = ℓ(wr(a,b same team))   − ℓ(wr(a)) − ℓ(wr(b)) + ℓ(wr_base)
counter(a,b) = ℓ(wr(a vs b))        − ℓ(wr(a)) + ℓ(wr(b)) − ℓ(wr_base)
```

This is the single most common mistake in hobby draft tools and it is worth a paragraph
in the report. `counter` is antisymmetric: `counter(a,b) = −counter(b,a)`.

### (c) Shrink toward zero — the sparsity problem

126 heroes ⇒ 15,876 ordered counter cells and 7,875 synergy cells. Inside a single patch
window you may have only tens of games per cell, so raw cell estimates are mostly noise.
Use **empirical-Bayes / James–Stein shrinkage**:

```
ŝyn(a,b) = syn_raw(a,b) · n_ab / (n_ab + k)
```

with `k` chosen by cross-validation (typically 50–500 games). Equivalently, a
Beta-Binomial posterior mean, or report Wilson intervals. Either way: **a pair with 8
games must contribute ≈ 0 to the score, not ±15%.** Also stratify by skill bracket —
hero winrates differ wildly between Herald and Immortal, and pro CM is a different
distribution again.

### (d) The better version: fit it jointly instead of computing cells

Rather than computing cells independently, fit one model on `N` matches:

```
ℓ(P[Radiant wins]) = μ + Σ_{h ∈ R} β_h − Σ_{h ∈ D} β_h  (+ interaction terms)
```

This is **ridge-regularised logistic regression on ±1 hero indicators** — mathematically
the same technique as *adjusted plus-minus (RAPM)* in basketball analytics, which solves
the identical problem of isolating one participant's contribution from lineup-level
outcomes. Good citation, and it controls for "who else was in the game" automatically.

Pairwise interactions add ~16k parameters and will overfit. The fix is **low-rank**:
model the interaction as an inner product of learned hero vectors,

```
interaction(a,b) = ⟨v_a, v_b⟩ ,  v_h ∈ R^k ,  k ≈ 8–16
```

i.e. a **factorisation machine**. Parameters drop from 16k to ~2k, sparsity is handled by
sharing structure across heroes, and — importantly for you — **`v_h` is an automatically
learned "hero DNA" vector**, which is a data-driven version of the hand-authored tags in
Layer B. A cheap alternative with the same flavour: build the empirical matchup matrix
and take a **truncated SVD / NMF** to rank `k`. Easy to implement, easy to explain, and
the resulting components are often interpretable (they tend to separate along
push/teamfight/carry axes — inspect and report this, it makes a great figure).

**Layer A alone will already give you a working draft bot.** Ship it first.

---

## 3.2 Layer B — Semantic / capability vectors (the "5 carries vs 5 supports" intuition)

Layer A can tell you *that* a lineup is bad. It cannot tell you *why*, it fails on newly
released or reworked heroes (no data), and it must be relearned from scratch every patch.
Layer B fixes all three, at some cost in raw accuracy.

### The key modelling insight

The feeling you described — "no way we win this" — is almost never about hero strength.
It is about **coverage** and **resource contention** at the *team* level. So the hero
vector should describe *capabilities and demands*, and the team score should be
**non-linear** in those (hinge penalties), because that is where the intuition lives.

### Proposed dimension schema (~20 axes, grouped)

| group | axes |
|---|---|
| Damage | physical share, magical share, pure share, burst vs sustained DPS |
| Control | hard-disable seconds available at lvl 6/12/18; AoE vs single-target; silence/mute; break; anti-BKB |
| Fight | teamfight AoE potential, initiation, counter-initiation / save / dispel, sustain & healing |
| Map | mobility/escape, global presence, split-push, push/siege, high-ground defence |
| Clear | illusion & summon clear, own summon pressure |
| Economy | **farm dependency (gold priority)**, item dependency vs level dependency, lane requirement |
| Time | power at t = 10/20/30/40 min, snowball coefficient |
| Frailty | effective HP / survivability index |
| Vision | detection requirement, vision provision |

Keep it around 15–25 axes. Fewer than 10 and you lose the intuition; more than 30 and you
cannot populate them reliably.

### How to populate them **objectively** — three sources, in strict order of preference

**Source 1 — parse the game's own data files (best; fully objective, fully patch-scalable).**
Dota 2 ships machine-readable hero/ability definitions (`npc_heroes`, `npc_abilities`,
mirrored by the `dotaconstants` npm package and the public Web API). From these you can
*compute*, not guess:

- base stats, attribute gain, movement speed, armour, BAT → survivability, EHP;
- ability `damage_type`, `AbilityUnitTargetTeam/Type`, `AbilityBehavior` flags;
- `ability_special` fields: stun/root/hex durations, radii, cooldowns, mana costs → so
  "hard-disable seconds at level 12" is literally a sum over parsed fields;
- cast range, radius → AoE vs single-target classification;
- talents and their per-level values.

**When a patch drops, you re-run the parser.** That is your answer to "easy to manage
across patches": the schema is stable, the values are regenerated.

**Source 2 — derive from match telemetry (objective, patch-current, no opinions).**
Most of your remaining adjectives have an obvious measurable proxy. Define the operational
definition *before* you look at the number:

| intuitive trait | measurable proxy |
|---|---|
| farm dependency / greed | mean net-worth share within own team; GPM percentile; lane role distribution |
| item vs level dependency | slope of winrate on net-worth advantage vs on XPM advantage |
| **late-game hero** | regress `ℓ(winrate)` on game duration → the slope *is* the power-curve tilt |
| teamfight contribution | hero-damage share of team total |
| pushing | tower-damage share, avg. time of first tower |
| sustain | healing done per minute |
| snowball | correlation of win with a lead at 10 min |
| fragility | deaths per minute conditioned on role |

The duration-regression trick deserves emphasis: **"early game hero" vs "late game hero"
becomes a single fitted coefficient**, not an opinion. Same for "snowbally".

**Source 3 — human labels, only for axes with no proxy** (e.g. "requires team
coordination"). If you must: ≥3 annotators, ordinal 0–3 scale, publish
inter-annotator agreement (Krippendorff's α), store in a versioned CSV, and treat the
labels as a **prior that data can override**. Say in the report how many axes ended up in
this bucket — a small number is a strength.

### Team-level composition features — where the intuition actually lives

Aggregate hero vectors into team features. The *linear* ones (sums/means) are weak; the
**non-linear** ones are the interesting contribution:

```
unmet_need[k]        = max(0, required_k − Σ_h cover_k(h))        # hinge: why 5 supports lose
farm_oversubscription = max(0, Σ_h farm_demand(h) − 1.0)          # hinge: why 5 carries lose
damage_imbalance      = 1 − entropy(physical, magical, pure)      # one-dimensional damage = one item counters you
curve_mismatch        = Σ_t w(t) · (our_power(t) − their_power(t)) # who wins the tempo war
control_vs_frailty    = their_disable_seconds × our_fragility
clear_deficit         = max(0, their_summon_pressure − our_clear)
```

These are the encodable form of "oh sh*t, we can't win this".

### Then: **do not choose the weights — fit them**

Feed team features into a logistic regression / GBM trained on real match outcomes.
The coefficient on `farm_oversubscription` tells you empirically how much a greedy draft
costs. A patch = **refit**, not rewrite. If a feature turns out to have no predictive
power, that is a finding you report, not a failure.

---

## 3.3 Layer C — the honest expectation

Say this up front in the report, because your examiner will ask:

> The learned relational model (Layer A) will almost certainly **out-predict** the
> hand-designed semantic model (Layer B) on raw log-loss, given enough matches.

Layer B earns its place on three other axes, and you should measure all three:

1. **Interpretability** — it explains *why* a draft is bad ("you have 3.2 units of farm
   demand and 4 seconds of lockdown against a hero with 2600 EHP").
2. **Cold start** — it scores a brand-new or reworked hero with zero matches played.
   Test this explicitly: hold out a hero entirely, see which layer degrades less.
3. **Patch transfer** — train on patch X, test on patch X+1. Layer A decays; Layer B
   should decay slower. **This experiment is a publishable-quality result for a student
   project** and directly answers your "adaptable to patches" requirement.

The strongest final model is the **hybrid**: Layer A embeddings + Layer B composition
features concatenated. Ablate all three configurations.

---

## 3.4 Engineering for patch scalability (your "easy to manage" requirement)

```
schema/features.yaml          # dimension definitions + how each is computed + its source
etl/parse_gamefiles.py        # Source 1  → data/patches/<patch>/hero_static.json
etl/build_telemetry.py        # Source 2  → data/patches/<patch>/hero_derived.json
labels/manual.csv             # Source 3, versioned, with annotator IDs
models/<patch>/weights.json   # fitted weights + model card
```

Rules:
- **No hero number is ever written in source code.** Code contains the schema and the
  fitting procedure; data contains the values.
- Every artefact is stamped with `(patch, match window, N matches, bracket)`.
- A **model card** per fitted model records validation log-loss/Brier/AUC so you can see
  a patch degrade the old model, which is itself a nice figure.
- A new patch is a pipeline run, ideally under an hour of wall-clock, zero code changes.

---

## 3.5 Concrete first-week scope

1. Pull one patch of high-bracket ranked matches (~200k).
2. Fit `β_h` by ridge logistic regression on ±1 indicators. Sanity-check against published
   winrates.
3. Add rank-8 factorised interactions. Measure log-loss vs. the additive model.
4. That is a working evaluator. Plug it into greedy. You now have an end-to-end system
   in week one, and everything after is improvement rather than risk.
