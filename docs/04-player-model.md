# 4. Player / roster modelling

You identified two tiers, and you were right that they need different treatment:

- **Tier 1 — public accounts** (any Dotabuff-style profile): lots of matches, low signal
  per match, fully automatable. This is where you should build and validate.
- **Tier 2 — pro rosters**: few matches, but roles are fixed and known, and qualitative
  scouting knowledge exists. Here you lean on priors and playstyle, not per-hero winrates.

---

## 4.1 Hero proficiency — the statistics, done properly

The naive version ("player X has 62% on Invoker over 21 games") is noise. 21 games has a
±21pp confidence interval. Use **partial pooling / a hierarchical model**:

```
ℓ(P[win]) = μ + α_p + β_h + γ_{p,h}
```

- `α_p` — player's own strength (how good they are in general),
- `β_h` — the hero's global strength (from doc 03),
- `γ_{p,h}` — the **player-specific hero effect**, heavily regularised.

With few games `γ → 0` and you gracefully fall back to `α_p + β_h` — which is exactly
the behaviour you want. This is a mixed-effects / regularised-regression formulation and
it is defensible in a report in a way that raw winrates are not.

**Signature hero** = a `γ_{p,h}` that is significantly positive (report the interval, not
the point estimate). **Weak hero** = significantly negative. If nothing is significant,
the honest answer is "this player has no measurable signature", and saying that is better
than inventing one.

### Sparsity for player-vs-hero ("heroes he loses against")

`γ` for *opposing* heroes is far sparser — a player may have 3 games against a given
enemy hero. Two ways out:
- shrink much harder (larger `k`), accepting most cells are ≈0; or
- **factorise**: `effect = ⟨u_p, w_h⟩` with a low-dimensional player vector `u_p` and
  hero vector `w_h`. This borrows strength across heroes — "he struggles against
  high-mobility gankers" emerges as a direction, rather than needing per-hero data.

### Recency — meta and form both drift

Weight every match by exponential decay:

```
w(match) = 0.5 ^ (Δdays / H) ,   H ≈ 14–30 days
```

Report `H` as a tuned hyperparameter (fit by held-out log-loss — a nice small experiment).

**Separate two different things that both matter, which most tools conflate:**

- **Comfort** = recency-weighted *games played* (familiarity/confidence). A hero played
  40 times this month is draftable even at 50% winrate.
- **Performance** = the `γ` above.

They are different features and both belong in the score.

---

## 4.2 Playstyle vectors — objectivising the "scout notes"

This is the direct analogue of doc 03's Layer B, applied to players. Each axis is a
**percentile within the same position and skill tier** — percentiles are the trick that
makes these comparable across patches, roles and brackets.

| trait | proxy |
|---|---|
| aggression | kills + deaths per minute; share of team's pre-15-min fights |
| farm efficiency | GPM / last-hits percentile, conditioned on role and duration |
| risk appetite | deaths in enemy territory; warding depth |
| map movement | lane presence %, rotations per 10 min |
| objective focus | tower/Roshan damage share |
| teamfight participation | % of team fights attended |
| **versatility** | entropy of the hero-pool distribution |
| **pool size** | number of heroes covering 90% of recent games |
| tempo | average net-worth curve shape vs role baseline |

Two payoffs:

1. **Cold start for a player-hero pair with zero games.** Score the *fit* between the
   hero's requirement vector (doc 03) and the player's style vector — cosine similarity,
   or better, learn the mapping. Now you can recommend a hero they've never played.
2. It converts pro-scouting intuition into something falsifiable. If you claim "this
   player is a greedy farmer", pre-register the proxy, then check the number.

---

## 4.3 Fusing it back into the evaluator

A hero's value to *your team* is:

```
fit(p, h) = base_hero_value(h)              # doc 03
          + λ₁ · γ_{p,h}                    # measured proficiency (shrunk)
          + λ₂ · comfort(p, h)              # recency-weighted familiarity
          + λ₃ · style_match(p, h)          # cold-start / fit term
          + λ₄ · α_p                        # player's overall level
```

and the **lineup** value maximises over assignments of the 5 heroes to the 5 players:

```
maximise Σ_i fit(player_i, hero_{σ(i)})  over perfect matchings σ
```

→ **Hungarian algorithm, O(k³)**, exact. Add position constraints (pos 1–5) as forbidden
edges (cost −∞) if a player never plays a position. This is the algorithmic component
that makes the roster model more than a feature-engineering exercise.

`λ` are fitted, not chosen — same discipline as everywhere else.

---

## 4.4 Data-access warning (important, put it in the proposal)

**Dotabuff has no public API and scraping it is against its terms of service.** Do not
build the project on it. Use instead:

- **OpenDota** — documented REST API, open source, `/players/{id}/heroes` gives
  per-player-per-hero win/loss counts directly; `/explorer` runs raw SQL; full database
  dumps are published for bulk work.
- **STRATZ** — GraphQL API, richer per-player and league data, has a free tier.
- **Valve Web API** — official, match details and league data.

Also note the *privacy/consent* angle for a university project: public match data is
fine, but say explicitly that you use only publicly-exposed profiles and aggregate stats,
and that you do not store personal identifiers beyond the numeric account ID. Ethics
sections are cheap marks.

---

## 4.5 Realistic scope advice

The player model roughly doubles the project. Suggested boundary:

- **In scope:** `α_p`, shrunk `γ_{p,h}`, comfort with recency decay, Hungarian assignment.
  Demonstrated on 5 public accounts.
- **Stretch:** playstyle vectors and the cold-start fit term.
- **Out of scope (say so):** modelling in-game skill expression, communication, or
  team chemistry. You cannot observe them, so don't pretend to.
