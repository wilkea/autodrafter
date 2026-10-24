# 6. Data and evaluation methodology

The methodology chapter is usually what separates a 3 from a 5. Plan it now, not at the end.

---

## 6.1 Data sources

| source | what you get | notes |
|---|---|---|
| **OpenDota API** (`api.opendota.com`) | public matches, pro matches, per-player hero stats, `/heroes/{id}/matchups` | free, documented, open-source. `/explorer` runs raw SQL — needed for same-team synergy, which the matchups endpoint does not expose |
| **OpenDota data dumps** | bulk match data | for training sets of 10⁵–10⁶ matches; much kinder than hammering the API |
| **STRATZ** (GraphQL) | richer league / player / draft-order data, free tier | best source for *pro Captain's Mode pick-ban sequences* |
| **Valve Web API** | official match + league endpoints | `GetMatchHistory`, `GetMatchDetails` |
| **`dotaconstants`** (npm) / game files | hero, ability and item definitions per patch | the backbone of doc 03 Layer B |
| **Dotabuff** | — | **no public API, scraping violates ToS. Do not build on it.** |

Practical collection plan: one patch window, ranked, high bracket, ≥200k matches for the
statistical layer; plus all league CM matches of the last ~6 months (~5–15k) for the draft
*sequence* evaluation. Cache everything to local Parquet/SQLite; never re-hit the API in
an experiment loop.

---

## 6.2 Splitting — by time, never randomly

The meta drifts. A random split leaks the future into the past and will flatter your
numbers by several points. Split **chronologically**: train on weeks 1–4 of a patch,
validate on week 5, test on week 6+. State this explicitly; examiners look for it.

---

## 6.3 Metrics

### Evaluator quality (does `V` predict anything?)
- **Log-loss** and **Brier score** (primary — they are proper scoring rules).
- **AUC**, accuracy (secondary, more intuitive).
- **Calibration / reliability diagram** — if you say 65%, does it win 65% of the time?
  Calibration matters more than accuracy here, because the search *compares* values.
- Baselines: constant 0.5; side-winrate prior (Radiant has a real advantage — use it);
  the 2013 logistic-regression-on-hero-indicators baseline.
- **Expectation management:** draft-only prediction tops out around **60–65%** accuracy
  in public matches, and *lower* in pro matches (better players close draft gaps). If you
  see 75%+ you have a leak — usually post-game features or a random split. Write the
  expected range into the proposal so a "modest" number doesn't look like failure.

### Draft agent quality (does the search help?)
1. **Self-play tournament** — every algorithm pair, both sides, first-pick swapped,
   many seeds; report a win-rate matrix with confidence intervals. This is the cleanest
   comparison and it is what the published work does.
2. **Optimality gap on the reduced-pool exact instance** (doc 02 §2.4) — the strongest
   result available to you.
3. **Agreement with real pro drafts** — HR@1 / HR@5 against the hero actually taken at
   held-out league pick-ban turns. Caveat honestly: pros are not optimal, so disagreement
   is not automatically error. Use it as a sanity signal, not a target.
4. **Cost** — nodes expanded, evaluator calls, wall-clock, TT hit rate; and MCTS's
   **anytime curve** (value vs iterations). Quality-vs-compute plots are the core figure
   of an algorithms report.

### Ablations
`Layer A only` / `A + B` / `A + B + player model` × `greedy / αβ / MCTS`.
Also the patch-transfer test (train patch X → test patch X+1) from doc 03 §3.3.

---

## 6.4 Threats to validity (write this section — it earns marks)

- **Circularity.** The evaluator is trained on the same distribution used to judge the
  search. Self-play win rates measure "wins according to my own model", not reality.
  Mitigate with the exact-instance ground truth and pro-draft agreement.
- **Both captains assumed to share one objective function.** Real opponents have
  different models and hero pools.
- **Meta drift** within the training window.
- **Selection bias in pro data** — few matches, strong teams, heavy correlation.
- **Draft is not destiny.** Execution dominates. Your ceiling is genuinely low, and
  saying so up front is a strength, not a weakness.
- **Bans are under-modelled** — a ban's value depends on what the enemy *would* have
  picked, which your model only knows through itself.

---

## 6.5 Reproducibility hygiene

Fixed seeds; every experiment a script, not a notebook cell; results written to
`results/<experiment>/<timestamp>.json`; a `model card` per fitted model recording patch,
window, N, bracket, hyperparameters, and validation metrics. Makes the write-up assemble
itself.
