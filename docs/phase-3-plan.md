# Phase 3 — Wiring Features Against the Spell Library

**Status:** COMPLETE (2026-06-11) — 3A/3B/3C executed; decision-layer
follow-ups parked in `docs/deferred-combat-followups.md` (§7)
**Prereq met:** `docs/spell-master-list.csv` now carries a DDB-authoritative
`classes` column (base-class availability) for all 392 spells.
**Branch:** `claude/practical-lovelace-u9bety`

---

## 1. What Phase 3 actually is

Phases 1–2 built the *spell library*: ~150 spell features (`f_*.yaml`) with
working engine mechanics, each verified in isolation. But a spell existing in
the registry does **not** mean any class can cast it in a simulated fight. A
spell only becomes a candidate action when its feature id appears in a class's
`level_table` (or a subclass's `features_by_level`) at or below the PC's level
— because `build_pc_template` collects `features_known` from those tables and
the **auto-attach** loop (`engine/pc_schema.py:325`) turns every known feature
that carries an `action_template` or `pc_builder` block into a usable action.

> **Key fact the whole phase rests on:** wiring is keyed off `features_known`,
> NOT `granted_by`. The single-valued `granted_by` field on each feature is
> doc-only. To give the Cleric *Spirit Guardians*, you add `f_spirit_guardians`
> to the Cleric's L5 row — you do **not** touch the feature file. This is why a
> spell can be shared by many classes without any change to the spell YAML.

So Phase 3 = go class-by-class and **populate the spell lists for real**, now
that the library is deep enough and the `classes` column tells us exactly which
class may take which spell.

It splits into three distinct sub-tasks, in dependency order:

- **3A — Base-class spell-list wiring** (the bulk; mechanical fan-out)
- **3B — Subclass always-prepared spell lists** (domain / oath / circle / patron)
- **3C — Subclass combat-feature wiring** (wire combat, stub exploration/social)

---

## 2. The data model (read before touching anything)

### Class file (`schema/content/classes/c_*.yaml`)
- `level_table[].features` — list of feature ids granted at that level. Today
  these hold **only built spells** that someone wired by hand. This is the list
  we extend in 3A.
- `class_resources.spell_slots` — the slot table per level. **This is the gate:
  a spell of tier-N is only castable from the level where the `N:` slot first
  appears.** (Cleric gets `3:` slots at L5 → Spirit Guardians is wired at L5,
  not L3.)
- `spellcasting.preparation_model: prepared_from_class_list` — descriptive
  today; there is **no** runtime spell-selection engine. The `level_table`
  features list *is* the de-facto known/prepared list.

### Subclass file (`schema/content/subclasses/sc_*.yaml`)
- `features_by_level[].feature_ids` — same shape, loaded by `_subclass_features`
  (`engine/pc_schema.py:1112`). This is where 3B and 3C land.
- Several subclasses already note their always-prepared spell lists **in header
  comments as deferred** (e.g. `sc_circle_of_the_land` Circle Spells,
  `sc_draconic_sorcery` Draconic Spells). Those comments are the 3B to-do list.

### The source of truth
- `docs/spell-master-list.csv` `classes` column = which base classes may take
  each spell (semicolon-separated, e.g. `bard;cleric;druid`).
- Subclass/domain/oath grants are **not** in the CSV — DDB lists them
  separately ("Forge Domain", "Oath of Glory"). For 3B, those come from the
  per-feature YAML "Available for" comments and pasted DDB data.

### Test guards already protecting us
- `tests/test_spell_master_list.py` — CSV well-formed, classes valid, files
  exist & are referenced.
- Per-class feature-presence tests (e.g. `tests/test_spirit_guardians.py`
  asserts `a_spirit_guardians` present at L5, absent at L3).
- The full suite (~3100 tests) — a mis-wired action that produces a malformed
  pipeline fails loudly at template-build or scoring time.

---

## 3. Sub-task 3A — Base-class spell-list wiring

**Goal:** for each of the 8 caster classes, every **built, combat-relevant**
spell the class may take (per the `classes` column) appears in its `level_table`
at the correct slot-gated level.

### Procedure (per class, repeatable)
1. From the CSV, filter rows where `status == built` AND `class` ∈ `classes`
   AND the spell is combat-relevant (exclude `tier: D` utility unless it has a
   combat action_template — when in doubt, check whether the feature YAML has an
   `action_template`/`pc_builder`; no block → skip, it can't produce an action).
2. For each spell, compute its **wire level** = the class's character level
   where the spell's `spell.level` slot tier first appears in
   `class_resources.spell_slots`. (Full casters: L1/3/5/7/9/11/13/15/17 for
   tiers 1–9. Half casters Paladin/Ranger: L2/5/9/13/17 for tiers 1–5.)
3. Add the feature id to that `level_table` row's `features` list. Keep rows
   alphabetically ordered within a level for reviewability.
4. **Do not** add a spell already present. **Do not** add a spell whose
   primary `granted_by` is a *different* class unless the `classes` column
   confirms this class — the column is authoritative, the comment is not.

### Worked example (already in the repo — copy this shape)
`c_cleric.yaml` L5 row wires `f_spirit_guardians`; L9 wires `f_summon_celestial`.
Both sit at the level their slot tier unlocks. That is exactly the pattern; 3A
is doing this for every remaining built spell across all 8 classes.

### Scope discipline
- Combat-relevant only. A `tier: D` ritual with no `action_template` (e.g.
  *Detect Magic*) produces no action and must NOT be wired — it just inflates
  `features_known` noise.
- This sub-task touches **only** `c_*.yaml` files. No engine code, no feature
  YAML, no new tests beyond optional presence-spot-checks.

### Difficulty: **LOW — Sonnet-perfect.**
Pure pattern fan-out against a deterministic rule (slot-tier → level). The slot
tables are right there in each file; mistakes (wrong level, duplicate, wrong
class) are mechanical and caught by re-running the suite + a presence check.

---

## 4. Sub-task 3B — Subclass always-prepared spell lists

**Goal:** wire the domain/oath/circle/patron always-prepared spells that each
built subclass grants, for the **built** spells on those lists.

### Procedure (per subclass)
1. Read the subclass header comment — it already enumerates the always-prepared
   list and flags which spells aren't built yet.
2. For each spell on the list that is **built**, add its feature id to the
   `features_by_level` row at the subclass-grant level (these lists grant at
   fixed levels, e.g. Cleric domain spells at L3/5/7/9).
3. Spells on the list that are **not yet built** → leave a `# deferred (not
   built): <spell>` comment so the gap is visible. Do not build them here;
   that's a library task, not a wiring task.

### Difficulty: **LOW–MEDIUM — mostly Sonnet, flag the ambiguous.**
Mechanical when the always-prepared list is unambiguous. Escalate to Opus only
when: the subclass introduces a *choice* (Circle of the Land's land-type
sub-list needs a selection field that doesn't exist yet) or a grant interacts
with a feature mechanic (always-prepared + free-cast like Natural Recovery).
Those are design calls — see §6.

---

## 5. Sub-task 3C — Subclass combat-feature wiring

**Goal:** the 13 existing subclasses (and any new ones) have their **combat**
features wired for real; exploration/social features are stubbed with a clear
"deliberately unmodeled" note (the established convention — see `f_friends`,
`f_feign_death`).

### Procedure (per subclass feature)
1. Classify: does this feature change a **combat** outcome (damage, defense,
   action economy, conditions, positioning)? If yes → wire. If it's
   exploration/social/ritual → stub with `status: stub` + non-combat note.
2. For combat features, the wiring path depends on shape:
   - **Rider on attacks** (smite-like) → reuse `smite_rider` /
     `SmiteRiderSpec` if the trigger fits its generic save path; custom module
     only if it doesn't (the Banishing Smite precedent). **This fork is an Opus
     call** — see §6.
   - **Data-driven action** (attack/save/heal/aoe) → `pc_builder` block, no
     engine code.
   - **Aura / zone** → `persistent_aura` primitive.
   - **Passive modifier** → `active_modifiers` entry via an existing primitive.
3. Every wired combat feature gets a focused test (presence + one
   behavior assertion), mirroring `tests/test_phb_level5_batch2.py`.

### Difficulty: **MIXED.**
- Wiring a feature that fits an existing primitive/pattern → **Sonnet.**
- Deciding *whether* a feature needs a new primitive or a custom rider module,
  and anything touching `engine/ai/ehp_scoring.py` → **Opus** (§6).

---

## 6. Model-handoff protocol (the cost-management point)

The test suite is the safety net. Where coverage is dense, Sonnet runs
near-autonomously because mistakes fail loudly. Where a wrong-but-plausible
choice slips past tests, Opus stays in the loop.

### Opus does (don't delegate)
1. **This plan** (done) and any revision to the wiring rules.
2. **The first instance of each new pattern category** — one worked example +
   its test, which Sonnet then mirrors N times.
3. **The "new primitive vs. custom module vs. existing spec" fork.** This is
   the single highest-risk decision: a wrong call here silently produces
   plausible-but-incorrect damage/behavior that passes tests and corrupts
   simulation results three batches later. (Precedent: Banishing Smite needed a
   custom rider because `SmiteRiderSpec`'s save path fires unconditionally but
   the banish is HP-conditional. That call was non-obvious.)
4. **Anything touching `engine/ai/ehp_scoring.py`** — new scoring heuristics
   have thin test coverage and corrupt results silently rather than failing.
5. **Checkpoint diff review** at the end of each class/subclass batch
   (review is far cheaper than authoring).

### Sonnet does (delegate freely)
1. **All of 3A** — base-class spell-list fan-out (deterministic rule).
2. **3B** where the always-prepared list is unambiguous and all-built.
3. **3C** where the feature fits an existing primitive/pattern Opus already
   established — mirror the worked example, write the focused test, run the
   suite.
4. Master-list `status`/`classes` upkeep, CSV hygiene, presence-test scaffolds.

### Hard handoff rule
Sonnet **never** decides #3 (the primitive/module fork) or touches #4 (scoring).
If a 3C feature can't be expressed with an already-established pattern, Sonnet
stops and flags it for Opus rather than inventing a primitive. "Looks like it
needs something new" is the escalation trigger.

### Suggested cadence
- Opus: write plan (done) → seed first worked example per new pattern → review
  batch diffs at checkpoints.
- Sonnet: execute 3A in full, then 3B, then the Sonnet-eligible slice of 3C,
  committing per class with the suite green.

---

## 7. Execution order & checklist

Ordered so novel-pattern (Opus) work front-loads and unblocks the fan-out.

- [x] **3A** Base-class spell lists — one commit per class, suite green each:
  - [x] Cleric  [x] Druid  [x] Bard  [x] Wizard  [x] Sorcerer
  - [x] Warlock [x] Paladin [x] Ranger
- [x] **3B** Subclass always-prepared spells (built spells only), per subclass.
- [x] **3C** Subclass combat features:
  - [x] Opus: seed one worked example per new wiring shape encountered
        (Overchannel maximize-dice + module, Elemental Affinity damage
        rider, Wholeness of Body heal-builder extension — `860ec4c`).
  - [x] Sonnet: mirror for the rest; stub exploration/social.
- [x] Per batch: run full suite, update master-list status, commit + push.

### Follow-ups parked for the PC decision layer

Combat features whose mechanics shipped in 3C but whose *selection*
decision (or remaining infra) is deferred are tracked in
**`docs/deferred-combat-followups.md`** — currently Overchannel (Evoker;
mechanics wired, AI when-to-use deferred alongside Metamagic option
selection) and Peerless Skill (Lore Bard; deliberate stub, implementation
path documented). Revisit when working on the PC decision layer /
`ehp_scoring` heuristics.

### Invariants (every commit)
1. Full suite green before push.
2. A spell is wired at the level its slot tier unlocks — never earlier.
3. `classes` column is authoritative for base-class eligibility.
4. Combat-relevant only; exploration/social → `stub` + non-combat note.
5. New combat feature → focused test (presence + one behavior assertion).
6. No spell wired to a class the `classes` column doesn't list.
