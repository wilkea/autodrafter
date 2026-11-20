# 9. Making the game-file parser correct

This document exists because "just parse the game files" hides the hardest engineering
problem in the project. Below is what the data actually looks like, what "correct" can
and cannot mean here, and the specific techniques that make it defensible in a report.

All numbers below were measured against `odota/dotaconstants` (`build/abilities.json`,
`build/hero_abilities.json`), which is the cleaned mirror of the game's own files.

---

## 9.1 First: it is two programs, not one

The word "parser" is doing too much work. Separate these, physically, into two modules:

| stage | job | can it be *verified*? |
|---|---|---|
| **A. Extractor** | read the game files, emit a faithful, flat, typed table of every ability and every field, losing nothing and interpreting nothing | **Yes.** It either matches the file or it doesn't. Aim for 100%. |
| **B. Interpreter** | turn those fields into your ~20 capability axes ("hard disable seconds at level 12") | **No — not by testing.** This is judgment, encoded as rules. It is validated statistically, not asserted. |

Almost every mistake people make here comes from writing B *inside* A — scattering
judgment calls through the extraction code, where they can't be reviewed, diffed, or
argued about. Keep A dumb and complete; keep B declarative and small.

---

## 9.2 What you are actually up against (measured, not guessed)

### Problem 1 — 75% of the file is not heroes

`abilities.json` has **3,099 entries**. Only **788** are reachable from a real hero via
`hero_abilities.json` (**127 heroes**). The rest are Roshan, neutral creeps, warlock
golems, Greevils, and abandoned event modes — `roshan_bash`, `mud_golem_hurl_boulder`,
`frostivus2018_throw_snowball`.

If you aggregate blindly you will assign Roshan's stun to somebody. **Always drive
iteration from the hero list, never from the ability list.**

### Problem 2 — the field you want does not exist

There is no `stun_duration` field. There are **18 different key names** whose header
mentions a stun, across **41 different header strings**:

```
  51  stun_duration                    (e.g. roshan_bash)
  11  duration                         (e.g. lion_impale  ← Lion's stun is called "duration")
   4  max_stun
   3  hero_stun_duration
   3  stun_delay                       ← NOT a stun duration
   3  stun_radius                      ← NOT a duration at all
   2  ministun
   2  stun_min / stun_max              ← two halves of one value (Morphling)
   2  castable_while_stunned           ← a boolean about being stunned, not applying one
   2  explosion_stun_duration
   ... plus another 8
```

So: **matching on the key name fails** (Lion's key is `duration`). **Matching on the
header fails too** (`STUN RADIUS:`, `CASTABLE WHILE STUNNED:`). Neither a regex nor a
substring search is correct, and any approach that "mostly works" here will be silently
wrong for exactly the heroes you care most about.

Here is the real entry for Lion's Earth Spike:

```json
{ "key": "duration", "header": "STUN DURATION:", "value": ["1.3","1.6","1.9","2.2"] }
```

Note also: **values are per-level arrays**, sometimes plain strings, sometimes arrays of
strings-that-are-numbers. Type handling is not optional.

### Problem 3 — the schema is irregular

`hero_abilities[hero].abilities` is a list of strings — except for Monkey King, where one
element is itself a *list* (`['monkey_king_untransform','monkey_king_transfiguration']`).
Exactly one hero out of 127 breaks the type. A naive loop either crashes or, worse,
silently skips it.

There will be a handful more of these. Assume irregularity; never assume a uniform schema.

### Problem 4 — some heroes are genuinely not parseable this way

Invoker has **16** ability entries, including two placeholders (`invoker_empty1`,
`invoker_empty2`) and three reagents that do nothing on their own. "Invoker's stun
seconds at level 12" is not a well-posed question — it depends on what he invoked.

The same applies to Rubick (steals), Morphling (stat morph + Replicate), Lone Druid
(bear), Arc Warden (clone), Meepo (clones), Monkey King (forms), Terrorblade
(metamorphosis), Aghanim's/shard-conditional abilities, and talents that change kind
rather than magnitude.

**That is roughly 12–16 heroes. You do not have to solve them. You have to *know* which
ones they are.** See §9.5.

---

## 9.3 So what does "correct" even mean here?

There is no ground truth for "Lion has 3.4 units of teamfight control". Chasing absolute
correctness is a trap that will eat your semester. Decompose it into three properties,
two of which are fully achievable:

### (a) Faithfulness — Stage A only. *Achievable: aim for 100%.*
Does the extracted table match the source file? Round-trippable, testable, done.

### (b) Consistency — the one that actually matters. *Achievable.*
Is the **same rule applied to every hero**? This is more important than accuracy, and
understanding why will save you a lot of anxiety:

> Your axis feeds a regression that fits a weight for it. A *systematically* biased axis
> is harmless — if you undercount every hero's disable by 30%, the fitted weight simply
> comes out ~1.43× larger and the model is identical. What destroys the model is
> **inconsistency**: counting Lion's stun because its header said `STUN DURATION:` while
> missing Sven's because his key was named something else. That is not noise; it is a
> per-hero error that the model cannot absorb, and it will look exactly like "Sven is
> bad at fighting".

So stop asking "is 3.4 the right number for Lion?" and start asking "would Sven be
measured the same way?" That is a question you can actually answer.

### (c) Stability — across reruns and across patches. *Achievable.*
Same input ⇒ same output. And a patch should produce a *small, explainable* diff. See §9.6.

Semantic correctness ("does this axis measure what I claim?") is the fourth property, and
it is not established by the parser at all — it is established statistically, in §9.4.

---

## 9.4 The six techniques

### 1. A declarative mapping file, not code

Stage B lives in `schema/features.yaml`, not in Python:

```yaml
hard_disable_seconds:
  description: >
    Seconds of guaranteed, non-dispellable loss of control applied to a single
    enemy hero by one cast, at the ability's level at hero level 12.
  unit: seconds
  sources:
    - match: {header: "STUN DURATION:"}
    - match: {header: "HERO STUN DURATION:"}
    - match: {key: "hex_duration"}
    - match: {key: "stun_max", ability: "morphling_adaptive_strike_agi"}
  exclude:
    - {header: "STUN RADIUS:"}
    - {header: "STUN DELAY:"}
    - {header: "CASTABLE WHILE STUNNED:"}
  notes: "Roots counted at 0.6 weight (unit can still act); see ADR-003."
```

Why this matters: your examiner's question "why does Lion count but Sven doesn't?" now
has an answer that lives in a **reviewable, diffable, citable file**, rather than in line
340 of a script. It also makes the judgment calls *visible to you*, which is how you catch
them.

Write the `description` **before** you write the rule. If you cannot write one sentence
defining the axis precisely, the axis is not ready, and no parser will save it.

### 2. Allowlist + a fail-loud unmapped report ← *the single most important technique*

Never regex-guess. Maintain an explicit allowlist of what counts. Then, every
`(ability, key, header)` triple the parser encounters that is **not** in the allowlist
and **not** in an explicit "known irrelevant" list gets written to
`build/unmapped.csv`, sorted by how often it appears.

This converts an unanswerable question into a measurable one:

```
coverage   = % of hero abilities with ≥1 mapped field
unmapped   = the ranked TODO list, longest-first
```

You work down `unmapped.csv` until the remaining entries are genuinely irrelevant. And on
a new patch, **new keys appear in that report instead of being silently ignored** —
which is precisely the failure mode that makes hand-built game data rot.

This is also your answer in the defence to "how do you know your parser is complete?"
You show the coverage number and the unmapped tail. That is a real answer.

### 3. Golden tests on heroes you know cold

Pick 15–20 heroes spanning the space (Lion, Sven, Crystal Maiden, Anti-Mage, Axe, Zeus,
Pudge, Tidehunter, Drow, Treant). Hand-write the expected values from the wiki. Assert.

```python
def test_lion_disable():
    assert 1.8 <= axes["lion"]["hard_disable_seconds"] <= 4.2
```

Use **ranges, not exact values**, so a balance patch doesn't break your test suite every
two weeks — you want the test to catch *structural* breakage, not numeric drift.

This is cheap (an afternoon) and catches the large majority of real bugs.

### 4. Invariants / property tests over all 127

Structural checks that must hold for every hero, run on every build:

```
every hero has ≥ 1 mapped ability
0 ≤ hard_disable_seconds ≤ 12
physical_share + magical_share + pure_share == 1  (±1e-6)
no NaN, no None, no negative durations
no axis is identical for all 127 heroes      # ← catches a silently-dead axis
no axis is non-zero for fewer than 3 heroes  # ← catches an over-narrow rule
```

Those last two are the ones that catch the embarrassing bugs: an axis that quietly
extracts nothing looks fine in every unit test and just contributes zero to the model.

### 5. Correlate against telemetry ← *this is how you validate the interpretation*

Unit tests cannot tell you whether your axis measures what you claim. Statistics can.

For each capability axis, pick an **independent** behavioural proxy from match data and
compute the rank (Spearman) correlation across all 127 heroes:

| axis (from game files) | independent proxy (from telemetry) | expect |
|---|---|---|
| push/siege score | tower-damage share | strong + |
| sustain/healing | healing per minute | strong + |
| teamfight AoE | hero-damage share in 5-man fights | + |
| hard disable seconds | stuns-applied duration per match (if available) | strong + |
| farm dependency | net-worth share within own team | strong + |
| fragility | deaths per minute, conditioned on role | + |

If your "pusher" axis does not correlate with tower damage across 127 heroes, **your
parser is wrong**, and you found out without needing any ground truth at all. If it
correlates at ρ ≈ 0.7, you have real evidence your derived axis means what you say.

**Put that table of correlations in your report.** It is the single most convincing piece
of evidence that your hero numbers are objective rather than invented, and it is exactly
the "how do I make this objective and realistic to the game" question you started with,
answered empirically.

### 6. Separate "predicts nothing" from "is broken"

If an axis has no weight in the final regression, there are two possible causes —
it genuinely doesn't matter, or your parser botched it. You cannot tell them apart from
the regression alone. Technique 5 is what distinguishes them: an axis that correlates
with its telemetry proxy but carries no regression weight is a *finding*; an axis that
correlates with nothing is a *bug*.

---

## 9.5 The pathological heroes: flag, don't solve

Add a per-hero, per-axis `confidence` field. Three tiers:

- **parsed** — derived by rule, normal case (~110 heroes)
- **manual** — hand-entered in `labels/manual.csv`, with an annotator and a date
- **unknown** — no reliable value

Then: the model can down-weight low-confidence entries, the count of each tier is a
reportable quality metric, and — importantly — nobody can accuse you of hiding the
problem, because it is a column in your output.

Budget: ~12–16 heroes end up `manual`. That is a few hours of work, versus weeks trying
to make the rules handle Invoker. **Do not generalise your parser to fit the hard 12%;
you will damage the easy 88% doing it.**

Keep an `ADR` (one short markdown file per decision) for the calls you make: "roots count
at 0.6 of a stun because the unit retains attack and item usage — ADR-003". Ten of these
turn your methodology chapter into an editing job.

---

## 9.6 Patch workflow — the diff is the test

When a patch lands, you do not re-verify 127 heroes. You diff:

```
make parse PATCH=7.40
git diff data/patches/7.39d/... data/patches/7.40/...
```

Then check three things:

1. **Does the diff match the patch notes?** Notes say "Earth Spike stun 1.6→1.8"; your
   diff should show Lion's disable axis moving and little else. If unrelated heroes moved,
   you have a bug — most likely a renamed key.
2. **Is `unmapped.csv` longer?** New keys mean new content your rules don't see yet.
3. **Did coverage drop?** A renamed field silently zeroes an axis; coverage catches it.

This makes a patch a ~1-hour supervised task rather than a rebuild, which is what you
meant by "easy to manage". Keep every patch's output committed so the diffs exist.

---

## 9.7 Recommended first step (one day, before committing to any of this)

Do **one** axis end to end — `hard_disable_seconds`:

1. Extract all 788 hero abilities, faithfully, with types. *(Stage A)*
2. Write the allowlist for that one axis; emit `unmapped.csv`. *(Stage B)*
3. Golden-test 15 heroes by hand.
4. Correlate the resulting 127 numbers against a telemetry proxy.
5. Eyeball the top and bottom 20 heroes by the axis. Does the ranking look like Dota?

That last check is worth as much as the other four. If the top of your disable ranking
isn't recognisable, no amount of statistics will fix it downstream.

If step 4 gives a decent correlation, the whole capability-layer approach is validated and
you can mass-produce the remaining axes with confidence. If it doesn't, you have lost one
day instead of six weeks — and you still have the statistical layer (doc 03 §3.1), which
needs no parser at all.

---

## 9.8 Measured reality check — and a correction to §9.4

The prototype in §9.7 was actually run against live `dotaconstants` data. It failed, in a
way that changes the recommended design. Recording it here because the failure is more
instructive than the plan was.

### What the file contains

789 hero abilities. Top-level fields and their coverage:

| field | present on | values |
|---|---|---|
| `attrib` | 789 | per-level numbers — 6,068 rows total |
| `behavior` | 787 | No Target 216, Unit Target 211, Point Target 186, Passive 184, AOE 117, Channeled 28 |
| `cd` / `mc` | 590 / 550 | cooldown, mana cost |
| `bkbpierce` | 521 | Yes 160 / No 354 |
| `dispellable` | 455 | Yes 219 / No 183 / Strong Dispels Only 53 |
| `dmg_type` | 422 | Magical 301 / Physical 80 / Pure 31 |
| `target_team` | 299 | Enemy 210 / Friendly 64 / Both 19 |
| `target_type` | 296 | Hero 276 / Basic 207 / Building 12 / Tree 6 |
| `is_innate` | 126 | innate abilities |

### The long tail is fatal to name-matching

```
6,068 attrib rows → 2,892 distinct key names, 2,381 of which appear exactly ONCE
top  25 headers → 36% of rows | top 100 → 46% | top 400 → 59%
```

### The prototype result

Header-matching every `*STUN*` header, summing per hero:

```
heroes with a stun found: 52 of 127
TOP:  alchemist 6.45 · mirana 5.00 · magnataur 4.25 · beastmaster 4.00
ZERO: axe, bane, crystal_maiden, faceless_void, legion_commander,
      naga_siren, elder_titan, pudge, disruptor, lich, ...
```

Wrong on sight — Axe, Bane, Faceless Void, Legion Commander and Naga Siren at zero
control; Alchemist top only because `stun_min` and `stun_max` are two halves of one
number and both got summed.

### Why — the semantics are simply not in the file

```
Berserker's Call    DURATION: [2.1, 2.4, 2.7, 3]   bkbpierce=Yes  dispellable=No
Frostbite           DURATION: [1.5, 2, 2.5, 3]     bkbpierce=No   dispellable=Yes
Fiend's Grip        DURATION: [4.75, 5.25, 5.75]   bkbpierce=Yes  dispellable=Strong Only
Chronosphere        DURATION: [3.75, 4.25, 4.75]   bkbpierce=Yes  dispellable=No
Duel                DURATION: [4, 4.5, 5]          bkbpierce=Yes  dispellable=No
Song of the Siren   DURATION: 7                    bkbpierce=No   dispellable=No
Hex                 DURATION: [2, 2.4, 2.8, 3.2]   bkbpierce=No   dispellable=Strong Only
```

Every real disable is labelled only `DURATION:` — the same generic header (276 rows) used
for buff, slow, vision and illusion durations. **The durations are present and clean; the
meaning is absent.** Whether a `DURATION` is a loss of control exists only in the
description text and in the reader's head.

So §9.4's header-allowlist works for damage type and cooldowns, but **not** for anything
about control. Revised approach:

### The corrected principle: the file owns the numbers, you own the categories

Hand-author ~150 rows, once, mapping ability → control class and naming which field holds
the length:

```yaml
axe_berserkers_call:        {class: taunt,  source: "DURATION"}
crystal_maiden_frostbite:   {class: root,   source: "DURATION"}
faceless_void_chronosphere: {class: stasis, source: "DURATION"}
lion_impale:                {class: stun,   source: "STUN DURATION"}
lion_voodoo:                {class: hex,    source: "DURATION"}
```

You are **not** recording "Lion has 2.2 seconds". You are recording *"Earth Spike is a
stun and its length lives in STUN DURATION"*. The parser reads the current value from the
current patch.

This keeps every property that motivated the game-file approach:

- **Patch-scalable** — patches change numbers (auto), not categories (stable). A reworked
  hero is a few rows to review, and `unmapped.csv` flags which.
- **Objective where it counts** — you never invent magnitudes, only classifications any
  player would agree with, in a reviewable file. Weights remain fitted, not chosen.
- **Consistent** (§9.3b) — one explicit, visible rule per hero.
- **Bounded** — ~500 hero-ability pairs, ~150 involving control. An evening, not a
  research problem.

### What stays fully automatic (no curation)

`dmg_type` (the physical/magical/pure split, 422 abilities), `bkbpierce`, `dispellable`,
`behavior` (passive / channeled / AoE), `target_team` (enemy = disable, friendly = save),
cooldowns, mana costs, `is_innate`.

Worth noting: `bkbpierce=Yes` **and** `dispellable=No` co-occur on Berserker's Call,
Chronosphere and Duel. That pair is machine-readable and is a strong signal of heavy
unavoidable control. **Build the automatic flag-based proxy first, then the 150-row
curated table, and report which predicts better** — that comparison is a small, clean,
self-contained experiment and belongs in the report either way.
