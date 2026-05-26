# SESSIONS.md — D&D Combat Simulator

Running log of key decisions, findings, and open items across AI sessions.  
Add a new entry at the top for each session that produces a non-obvious decision.

---

## Session: 2026-05-26 — Pace-aware Action Surge (PR #42)

**Participants:** Phil, Claude

**Work done:**
- The first pace-aware AI behavior. Pre-#42, a L2 Fighter dumped
  Action Surge on every encounter's first turn because the
  activation gate only checked "have charges + have an in-reach
  target + at least one enemy alive." With the session runner
  shipped in #41, that dump-and-pray behavior left the fighter
  empty-handed for the boss.
- New `engine/core/feature_pacing.py`:
  - `feature_use_cost_ehp(charges_remaining, encounters_remaining,
    base_cost)` — generic opportunity-cost formula:
    `cost = base_cost × scarcity × urgency_factor`. Scarcity =
    1/charges (fewer charges = each is more precious).
    Urgency_factor = encounters_remaining/3 (more future fights =
    higher cost = save).
  - `action_surge_cost_ehp` wrapper with `ACTION_SURGE_BASE_COST = 6.0`
    (calibrated against a typical L2-5 fighter greatsword swing at
    AC 14: ~7 eHP per attack).
  - **Different shape from `spell_slots.slot_cost_ehp`** (which uses
    `(1 - urgency)` and has questionable last-encounter behavior).
    Documented in module docstring that the two formulas may
    converge long-term.
- `runner._maybe_activate_action_surge` now:
  - Scores the best in-reach `weapon_attack` / `multiattack`
    candidate via `score_candidate`
  - Computes AS cost from the formula
  - Activates only if `gain > cost`
  - Logs `gain_eHP` / `cost_eHP` on the activation event for
    telemetry
- `runner.run()` gained an `encounters_remaining_today: int = 3`
  parameter. Single-encounter sims default to mid-day (3); session
  runners pass per-encounter values.
- `session.run_session` now computes
  `encounters_remaining = len(spec.encounters) - i` per encounter
  so the fighter sees urgency decrease across the day:
  - Encounter 1 of 6: encounters_remaining=6, cost=12, AS rarely
    fires (gain typically ~7)
  - Encounter 6 of 6: encounters_remaining=1, cost=2, AS fires
    freely
- 11 new tests in `tests/test_feature_pacing.py`: formula edges
  (zero charges, last-encounter, mid-day, start-of-day, multi-
  charge scarcity), AS-specific cost using the base constant,
  pace-aware runner activation (does NOT fire with many encounters
  left, DOES fire on last encounter), event-log telemetry
  contents, L17 with 2 charges is more eager, session-level
  6-encounter day proves AS does NOT fire in encounter 1 but DOES
  fire in some later encounter.
- Updated one existing AS test
  (`test_fighter_with_action_surge_attacks_twice_in_one_turn`) to
  pass `encounters_remaining_today=1` — it's testing the AS
  *mechanism* (the existing test scenario was specifically meant
  to demonstrate AS firing; the pacing gate added the requirement
  that it be the right time to fire).
- Test count: 560 → 571. All green, stable across full-suite
  re-runs.

**Key decisions:**
- **Two different cost formulas** for spell slots vs. feature uses.
  The slot formula (PR #22) uses `(1 - urgency)` which has the
  inverted incentive of "high cost late in the day, low cost
  early." For feature uses we went with the more intuitive `*
  urgency_factor` shape: high cost early (when more future fights
  to save for), low cost late (no future to save for). Pinned for
  long-term review; the two formulas may converge.
- **Default `ACTION_SURGE_BASE_COST = 6.0`.** Calibrated against a
  typical L2-5 fighter greatsword swing at AC 14 (~7 eHP per
  attack). Tunable. With this default, a single AS charge at
  mid-day (cost = 6) just barely loses to a standard attack
  (gain ~7) — meaning AS fires in roughly the right scenarios.
  Late-day cost drops to 2; AS fires freely.
- **AS event log carries gain/cost for telemetry.** Useful for
  inspecting AI decisions in long session logs ("why did AS not
  fire in enc 2?"). Adds two fields to the existing
  action_surge_activated event.
- **`runner.run()` parameter, not state field.** Adding
  `encounters_remaining_today` to `runner.run()` keeps the API
  surface clear: callers explicitly opt in to a non-default value.
  Setting it via state-mutation (the old workaround in tests) was
  fragile.
- **Pacing for AS only, not SW yet.** Second Wind already scales
  with desperation_multiplier (more eHP when wounded). Adding
  pace-awareness is less impactful (SW has multiple uses and
  partial-refresh on short rest). Deferred to a follow-on PR.

**Open items carried forward:**
- [ ] Pace-aware Second Wind (deferred — see above)
- [ ] Unify slot_cost_ehp and feature_use_cost_ehp formulas
  (different urgency conventions; pick one)
- [ ] Difficulty-aware activation (recognize a high-CR target as
  worth spending on regardless of pace — currently the gain
  calculation already does this implicitly via expected damage but
  could be sharper)
- [ ] Spirit Guardians / persistent_aura primitive
- [ ] Pace-aware spell-slot scoring for high-value slots (the
  existing slot formula's late-day inversion would benefit from a
  similar review)

---

## Session: 2026-05-26 — Multi-encounter session runner (PR #41)

**Participants:** Phil, Claude

**Work done:**
- The "adventuring day" macro item — composes EncounterRunner +
  the rest helpers (PRs #37, #40) into a sequence of encounters
  with rests interleaved. Resource-management mechanics (Action
  Surge, Second Wind, Arcane Recovery, spell slots) finally have
  a flow that exercises them across multiple combats.
- New `engine/core/session.py`:
  - `SessionEncounter` dataclass: one (Encounter, rest_after) pair
  - `SessionSpec` dataclass: list of SessionEncounter + the set of
    party_actor_ids that persist across encounters
  - `SessionResult` dataclass: per-encounter terminal states + rest
    summaries + final party state dict
  - `run_session(spec, seed)` — iterates encounters, swaps persisted
    party actors in at each encounter boundary, runs via
    EncounterRunner, ends concentration on party (RAW: time passes),
    applies rest if specified
- Persistence semantics:
  - HP / slots / resources / active_modifiers → carry across
  - Concentration → ends at each boundary (5+ minutes pass)
  - Dead party members → excluded from subsequent encounters
  - Fled members → return for next encounter (tactical retreat,
    not session exit)
  - Position → from new encounter spec (party doesn't carry
    spatial position between encounters)
- `tests/test_session.py` (7 tests): two-encounter party state
  carryover, short-rest refresh of Action Surge across encounters,
  long-rest HP restoration, dead member excluded from subsequent,
  fled member returns, concentration ends at boundary, end-to-end
  via cli._build_actor for a L2 Fighter + L5 Wizard 3-encounter
  adventuring day with short rest after enc1 + long rest after enc2.
- **Bug found + fixed**: the session test failed when run as part
  of the full suite but passed in isolation. Root cause:
  `engine.primitives._get_rng(state, bus)` returns the module-level
  `_rng` and ignores state/bus. When other tests had set the
  module RNG via `primitives.set_rng()` then exited, our session
  runner's per-encounter `runner.rng` wasn't being read by the
  primitive layer. Fix: `run_session` now calls
  `primitives.set_rng(runner.rng)` before each `runner.run()`, so
  encounter outcomes depend on the per-encounter seed instead of
  whichever test ran last. Existing pattern in other tests —
  generalized into session.py.
- Test count: 553 → 560. All green, and stable across full-suite
  re-runs.

**Key decisions:**
- **Concentration ends at encounter boundary.** RAW concentration
  spells have minute-scale durations (Bless / Hold Person = 1
  minute = 10 rounds); 5+ minutes pass between encounters in any
  sensible adventuring day. Don't try to model "did 5 minutes pass
  or was it 30 seconds"; just end concentration cleanly.
- **Fled members return.** Fleeing is a tactical retreat — the
  party member goes back to camp, joins the next fight when the
  party catches up. Session-ending death is the only permanent
  removal in v1.
- **Position from new encounter spec.** Party doesn't carry
  spatial position between encounters (different rooms, different
  battlefields). The encounter declaration's positions are
  authoritative.
- **Per-encounter seed derivation: `seed + i`.** Simple, deterministic,
  avoids all encounters rolling identical dice (which would happen
  if every runner used the same seed).
- **SessionRunner is a function, not a class.** Single entry point
  with clear inputs / outputs is the cleaner shape for now. A class
  would make sense if we needed to pause / resume sessions, expose
  per-encounter callbacks, etc. — none of those are v1 needs.

**Open items carried forward:**
- [ ] YAML session format — sessions are constructed in Python for
  v1. A `sessions/` schema directory with `.yaml` files referencing
  encounter files would be the natural follow-on for
  fixture-driven "adventuring day" demos.
- [ ] "Should I nova or pace?" AI awareness — party is on
  EncounterRunner autopilot which has no concept of "save Action
  Surge for encounter 3." The eHP scoring framework could be
  extended with an encounters_remaining_today weight (already
  passed to the slot cost formula but not yet used for feature
  uses).
- [ ] Resurrection / fallback for dead party members
- [ ] Damaged equipment / consumables (potions used = gone forever)
- [ ] Cross-encounter narrative state (NPC reactions, faction
  tracking)
- [ ] `_get_rng` cleanup — currently the primitives module's
  global RNG is the source of truth for all primitives. A
  state.rng / bus-attached pattern would let primitives read from
  the runner's per-encounter RNG without the `set_rng` workaround.
  Worth refactoring once 2-3 callers besides the session runner
  have to do the same dance.

---

## Session: 2026-05-26 — apply_long_rest closes the rest-cycle arc (PR #40)

**Participants:** Phil, Claude

**Work done:**
- Surgical sibling to PR #37. Adds `apply_long_rest(actor, state)`
  in `engine/core/rest.py`. Closes the rest-cycle arc; multi-
  encounter session work is now the natural next macro item.
- Universal effects (any actor):
  - HP → hp_max
  - All spell slots → spell_slots_max
  - Concentration ends with `reason='long_rest'` (RAW: sleep ends
    it) — uses the existing `end_concentration` helper which scrubs
    source-tagged modifiers from all targets.
  - Modifiers with lifetime `until_long_rest` expire via the
    existing `modifiers.expire_modifiers(actor, {"long_rest_end"})`
    trigger.
- Per-class refresh (PCs only):
  - Fighter: Action Surge to L2/L17 max (1 / 2), Second Wind to
    level-table max (2/3/4 per L1/L4/L10 thresholds)
  - Wizard: Arcane Recovery → 1
- Returns a summary dict for inspection (hp_restored, slots_restored,
  concentration_ended, modifiers_expired, per-class refresh keys).
  Logs `long_rest_applied` event.
- Long rest is NOT implemented as "apply_short_rest + extras"
  because the per-feature cadence differs (Second Wind: +1 short /
  full long; Action Surge: full either; Arcane Recovery: long only).
  Separate code paths keep the per-rest RAW behavior explicit.
- 17 new tests in `tests/test_long_rest.py`: HP restoration (wounded
  to full, full → no summary entry), spell slot restoration (partial
  to full, full → no summary entry), concentration end (with event
  log), until_long_rest modifier expiry + other-lifetime persistence,
  per-class Fighter refresh (AS at L2 / L17 / below-L2 cases, SW at
  L10 cap, already-at-max no-op), per-class Wizard refresh, non-PC
  actor (universal only), end-to-end via cli._build_actor for a L5
  wizard with all categories firing.
- Test count: 536 → 553. All green.

**Key decisions:**
- **Universal effects for everyone, per-class for PCs only.** HP /
  slots / concentration / modifier expiry apply uniformly — they're
  state-cleanup operations the engine should perform regardless of
  whether the actor is a PC or a monster. Per-class refresh is
  RAW-specific to class features which only PCs have today.
- **Separate code path from apply_short_rest, no inheritance.** RAW
  rest cadences vary per feature (some refresh on short, some only
  on long, some partial vs. full). Wrapping short_rest in long_rest
  would conflate them. Per-rest helpers are explicit.
- **Long rest covers more than 5e RAW would suggest.** The 2024
  PHB long rest restores HP / slots / class features only — it
  doesn't explicitly mention concentration. But sleeping for 8
  hours obviously ends concentration (RAW PHB p.241 says
  Incapacitated ends concentration; sleep is Unconscious which
  inherits Incapacitated). Wired explicitly so the engine doesn't
  rely on a chain of inferences.
- **`until_short_rest` modifiers don't auto-expire on long rest in
  v1.** RAW: anything that ends on short rest also ends on long
  rest. The lifetime trigger event mapping doesn't model this
  ("short_rest_end" and "long_rest_end" are separate triggers).
  Test pins current behavior; can revisit when needed.

**Open items carried forward:**
- [ ] Multi-encounter session runner — invokes apply_short_rest /
  apply_long_rest between encounters. Rest hooks both in place
  now; this is the natural next macro item.
- [ ] Exhaustion (-1 level on long rest, 2024 PHB)
- [ ] HP dice spent recovery (we don't track HP dice)
- [ ] `until_short_rest` auto-expires on long rest too (RAW)
- [ ] Generic data-driven rest dispatch (when more classes land)

---

## Session: 2026-05-26 — Extra Attack auto-generation at L5/L11/L20 (PR #39)

**Participants:** Phil, Claude

**Work done:**
- Closes a major Fighter power-gap: pre-PR #39, a L5 Fighter built
  via `pc:` schema only attacked ONCE per turn (a baseline RAW
  feature drove this — Extra Attack at L5 doubles per-action
  attacks, the canonical "your fighter feels mid-level" moment).
  Auto-generation pulls from the c_fighter level_table feature ids
  the same way PR #38 pulled Fighting Style: zero schema
  duplication, zero fixture-side action declaration.
- `engine/pc_schema.py`:
  - New `_extra_attack_count(features_known)` — returns 1/2/3/4
    based on which Extra Attack tier the fighter has gained.
    Higher tier supersedes lower (L20 fighter has all three feature
    ids in features_known via accumulation, but count = 4 wins).
  - New `_build_extra_attack_action(count, weapon_actions)` —
    constructs a `type: multiattack` action with the first weapon's
    id repeated `count` times in `sub_actions`. RAW: usually the
    same weapon all attacks; cycling is unusual.
  - `_build_feature_actions` extended to accept `weapon_actions=`
    kwarg and emit Extra Attack when `class_id == "c_fighter"` AND
    count > 1 AND weapons are present (defensive: no-op for
    weapon-less fighters).
  - `build_pc_template` separates `weapon_actions` from `actions`
    so it can pass weapons through to feature generation.
- `tests/test_extra_attack.py` (18 tests): count derivation (L1
  baseline, L5 → 2, L11 → 3, L20 → 4, higher supersedes lower),
  action shape (sub_actions populated correctly with first weapon
  repeated), gating (no emit below L5, no emit for non-Fighter, no
  emit when no weapons), build_pc_template integration (multiattack
  added at L5+ with correct count; single-attack action kept
  alongside), behavioral end-to-end (L5 Fighter does 2 attack_rolls
  per turn via the runner).
- `tests/fixtures/extra_attack_l5_fighter_encounter.yaml`: L5
  Fighter via `pc:` schema (Dueling + plate + longsword + Action
  Surge + Second Wind all auto-wired) vs ogre. Seed 1 round 1
  output is dramatic: `action_surge_activated`, 2× attack_roll
  (multiattack #1 hits twice), `healed` + `feature_use_consumed`
  for Second Wind on bonus slot, 2× attack_roll (Action Surge's
  bonus main slot, multiattack #2). Four attack rolls + a heal in
  one turn — the L5 Fighter "burst pattern" working as intended.
- Test count: 518 → 536. All green.

**Key decisions:**
- **Reference first weapon, repeated.** PCs commonly declare one
  weapon; multi-weapon fighters use the multiattack mechanic on
  weapon #1 for stability. `_execute_multiattack` cycles
  `sub_action_ids[i % len(...)]` anyway so repeated vs. cycled both
  work, but explicit repetition is clearer in the generated
  declaration.
- **No-op when no weapons.** Defensive: a Fighter with no weapon
  spec is unusual but legal; the framework shouldn't crash trying
  to build a multiattack with no sub-action ids.
- **Higher feature supersedes lower in count.** L20 Fighter
  accumulates all three feature ids (`f_extra_attack`,
  `f_two_extra_attacks`, `f_three_extra_attacks`) across levels.
  `_extra_attack_count` checks them top-down so the highest tier
  wins; we don't sum them (which would give an absurd 2+3+4=9
  attacks per turn).
- **Keep the single-attack weapon action alongside multiattack.**
  Multiattack is ADDED to the actions list, not replacing the
  single weapon_attack. The candidate generator will pick whichever
  scores higher per the eHP framework — usually multiattack at L5+,
  but the single attack remains a candidate for edge cases (e.g.,
  RP constraints, future overkill-cap considerations).

**Open items carried forward:**
- [ ] Extra Attack for other classes (Barbarian, Paladin, Ranger,
  Monk's Martial Arts) — different feature ids, same shape; can
  generalize when those classes land
- [ ] Multi-weapon fighters with deliberate sub_action variety
  (e.g., Two-Weapon Fighting using off-hand on one of the swings)
  — needs off-hand mechanics first
- [ ] L5 Fighter eHP scoring may overweight multiattack on tanky
  targets (overkill cap math is per-sub-attack but the AI doesn't
  yet think "skip the multiattack if target only has 5 HP left
  and use single-attack to save the second swing for someone
  else"); deferred to a scoring refinement PR

---

## Session: 2026-05-26 — Fighting Style v1: Defense + Dueling + Archery (PR #38)

**Participants:** Phil, Claude

**Work done:**
- Pre-discussion clarified SRD scope: SRD CC v5.2.1 includes Defense
  + Dueling only. Phil opted for "framework + 2-4 common styles"
  with non-SRD ones (Archery) tagged `source: user_authored`. GWF /
  Protection / Two-Weapon Fighting / Blind Fighting deferred (each
  needs additional infra).
- New schema files:
  - `f_fighting_style.yaml` — the L1 Fighter choice point. Lists
    accepted style ids with per-style source tags (defense + dueling
    = srd_5.2.1; archery = user_authored).
  - `f_fs_defense.yaml`, `f_fs_dueling.yaml`, `f_fs_archery.yaml` —
    per-style descriptions + `mechanic:` block (kind +
    value + requires). Documentation-grade; the runtime application
    lives in pc_schema.
- `engine/pc_schema.py`:
  - New `_KNOWN_FIGHTING_STYLES` frozenset + `_validate_fighting_style`
    accepting None/empty, normalizing case, raising ValueError for
    unknown ids (with a helpful error message listing accepted set
    + deferred status).
  - `build_pc_template` reads `pc_spec["fighting_style"]`, validates
    it, threads it to `_compute_ac` and `_build_weapon_action`.
  - `_compute_ac` adds +1 if style=defense AND armor block present
    (v1 proxy for "wearing armor"). Without armor, no bonus —
    matches RAW.
  - `_build_weapon_action` adds +2 attack if style=archery AND
    weapon is ranged. Adds +2 damage if style=dueling AND weapon is
    melee AND not `two_handed: true`. Weapon spec gains optional
    `two_handed: bool` field (default False).
  - Template's `derived_from_pc_schema` block now records the chosen
    style for inspection.
- `tests/test_fighting_style.py` (19 tests): validation (None/empty
  pass, known styles accepted, case normalized, unknown raises);
  Defense (+1 with armor, none without, Dueling-style doesn't affect
  AC); Dueling (1H melee +2 damage, 2H excluded, ranged excluded, no
  style baseline); Archery (ranged +2 attack, melee excluded, doesn't
  affect damage); template tagging; build-time rejection of unknown
  styles.
- `tests/fixtures/fighting_styles_showcase_encounter.yaml`: three
  identical L1 fighters with different styles vs three training
  dummies. Demonstrates the build-time bonus application via the
  pc: schema.
- Test count: 499 → 518. All green.

**Key decisions:**
- **Bake bonuses at build time, not runtime modifier registry.**
  Fighting Style bonuses are always-on passives that depend on
  weapon properties or armor presence — both stable for the life of
  the PC instance. Pre-computing the bonus into the generated
  weapon action's attack/damage param (or AC) is cleaner than
  registering a modifier with `when` clauses that re-resolve
  per-attack. Trade-off: doesn't support runtime weapon-swap.
- **Three styles, not all eight.** Phil chose framework + 2-4 common
  styles. Defense + Dueling are SRD; Archery is the most-picked
  Fighter style in published play so it's a high-value add even
  non-SRD. GWF / Protection / TWF / Blind Fighting all need
  infrastructure they don't have today.
- **Defense's "while wearing armor" gate is `armor:` block presence.**
  A more careful gate would distinguish armor types (light/medium/
  heavy) vs. unarmored. v1 just checks "is the armor block
  declared?" which matches the intent of declaring armor in the
  schema. Edge case: a Defense-style fighter who lists no armor
  spec selects the style legally but gets no bonus (matches RAW).
- **Dueling's "no other weapon" clause is implicit in v1.** Most
  fixtures declare one weapon; multi-weapon Dueling exclusion
  (Two-Weapon Fighting + Dueling don't combine per RAW) is deferred
  until off-hand weapon mechanics arrive.
- **Per-style YAML files are documentation-grade.** The `mechanic:`
  block in each `f_fs_*.yaml` is for human reference; the actual
  application is in pc_schema. When we have more styles + a
  data-driven engine, the YAML could become authoritative and
  pc_schema could read from it.

**Open items carried forward:**
- [ ] Great Weapon Fighting — needs damage re-roll primitive
  (reroll 1s and 2s on damage dice)
- [ ] Protection — needs reaction infrastructure (use reaction to
  impose disadvantage on attack against ally within 5 ft)
- [ ] Two-Weapon Fighting — needs off-hand weapon mechanics
  (add ability mod to off-hand damage)
- [ ] Blind Fighting — needs vision / blinded interaction
  (10-ft "vision" that ignores Heavily Obscured / Invisible)
- [ ] Champion's Additional Fighting Style (L10) — picks a second
  style; would need an extra `fighting_style_secondary:` field

---

## Session: 2026-05-26 — Arcane Recovery + slot_recovery_partial + rest-cycle hook (PR #37)

**Participants:** Phil, Claude

**Work done:**
- Pre-discussion flagged a design tension: Arcane Recovery is RAW a
  short-rest feature, but the runner is single-encounter-only. Phil
  picked the honest path — ship the infrastructure (primitive +
  rest-cycle hook + auto-wired resource), don't pretend the runner
  has rest cycles. Tests invoke directly.
- `engine/primitives.py`: new `_slot_recovery_partial` primitive.
  Greedy high-first restoration within a combined-level budget,
  capped at `max_slot_level` per slot and at
  `actor.spell_slots_max[level]` per level. Removed from
  `_STUBBED_PRIMITIVES` list; registered with implemented=True.
- `engine/core/state.py`: new `Actor.spell_slots_max` field tracks
  the post-rest ceiling (defaults to a copy of `spell_slots` at
  build time).
- `engine/cli.py`: `_build_actor` reads optional `spell_slots_max:`
  from actor_spec (default = copy of spell_slots).
- `engine/core/rest.py` (new): `apply_short_rest(actor, state)`
  entry point with per-class dispatch:
  - Wizard: `_apply_arcane_recovery` — fires
    `slot_recovery_partial` with budget = ceil(level/2), cap = 5;
    decrements `arcane_recovery_uses_remaining`. Skips if no slots
    are expended (don't waste the use).
  - Fighter: `_apply_second_wind_short_rest_refresh` (+1 use up
    to level-table max) and
    `_apply_action_surge_short_rest_refresh` (full refresh to 1 at
    L2-16, 2 at L17+).
  - Non-PC actors → no-op (still logs `short_rest_applied` with
    empty summary).
- `engine/pc_schema.py` `derive_pc_resources`: auto-wires
  `arcane_recovery_uses_remaining: 1` for Wizards with
  `f_arcane_recovery` in their features. The wizard class def
  declares this at L1.
- `tests/test_slot_recovery_partial.py` (9 tests): no-op without
  spell_slots_max, single-slot restoration, greedy high-first
  preference, max_slot_level cap, never-exceeds-max, multi-slot
  same-level restoration, budget=0 no-op, event logging, canonical
  L5 wizard arcane recovery scenario.
- `tests/test_short_rest.py` (13 tests): wizard arcane recovery
  (restores slots, decrements counter, subsequent rest no-op,
  no-recovery-when-not-needed conservation, L1 budget=1, event
  logged), fighter refresh (second wind +1, doesn't exceed max,
  scales with level, action surge L2 vs L17, no AS below L2),
  non-PC no-op, end-to-end via pc_schema + cli for a L5 wizard.
- Test count: 477 → 499. All green.

**Key decisions:**
- **Honest scope.** Acknowledged upfront that Arcane Recovery
  doesn't exercise the in-combat feature_uses gate (that was an
  imprecise framing in PR #33's docstrings). Built the rest-cycle
  hook properly instead of pretending.
- **Hard-coded per-class dispatch for v1.** Each class's rest
  effects are written as Python helpers in rest.py rather than
  walking the feature YAML defs and resolving formula strings. When
  more classes land (Barbarian Rage, Paladin Lay on Hands, Bard
  Bardic Inspiration), the v2 generic version can read
  `feature_def.usage.rest_recovery` from the registry. Hard-coding
  v1 keeps the PR small and explicit.
- **`spell_slots_max` defaults to a copy of `spell_slots`.** Most
  fixtures declare slots at "post-long-rest full loadout" values;
  fixtures starting mid-day with expended slots can override
  `spell_slots_max` explicitly. Two existing wizard fixtures don't
  need to change.
- **AR conservation: skip activation when no slots expended.** RAW:
  player CHOOSES to use AR. If wizard has full slots, using AR
  wastes the 1/long-rest charge. Test pins this conservation.
- **Action Surge full-refresh on short rest is RAW.** PR #31
  mentioned this as deferred for lack of a rest cycle; #37 wires
  it. Same for Second Wind +1.

**Open items carried forward:**
- [ ] `apply_long_rest(actor, state)` — same shape, broader
  restorations (all spell slots restored, all per-rest uses
  refilled, HP fully restored, etc.)
- [ ] Multi-encounter session runner — invokes `apply_short_rest`
  between encounters. The rest hook is in place for it.
- [ ] Generic data-driven rest dispatch (read
  `class_def.level_table` for short_rest features and resolve
  formula params instead of hard-coding per class). Worth it when
  3+ classes need it.
- [ ] Long-rest restoration on the AR counter
  (`arcane_recovery_uses_remaining` should reset to 1 on long rest).

---

## Session: 2026-05-26 — Named-effect tagging for cross-caster buff dedup (PR #36)

**Participants:** Phil, Claude

**Work done:**
- Closes the cross-caster buff stacking gap. PR #20 introduced
  per-(caster, action_id) dedup so the same wizard doesn't re-Bless
  every round, but two clerics both Blessing the same fighter would
  stack (different caster_id → dedup miss → +4 attack bonus instead
  of +2). RAW (PHB 2024 p.243): "The effects of the SAME spell cast
  multiple times don't combine."
- **Schema:** actions declare an optional `named_effect: <string>`
  (RAW spell identity — lowercase convention: `bless`, `heroism`,
  `hypnotic_pattern`). Two casts of the same spell share a
  named_effect; different spells don't.
- **Stamping:** `_build_modifier_entry` in primitives.py now copies
  `named_effect` from the executing action onto the generated
  modifier's `source` dict alongside the existing `caster_id` and
  `action_id` tags.
- **New helper module `engine/ai/named_effects.py`:**
  `buff_already_active(target, action, caster, primitive)` returns
  True if any modifier on target matches the action's effect — either
  by named_effect equality (cross-caster aware) OR by legacy
  (caster_id, action_id) tuple (untagged fallback).
- **Scoring wired:** `offensive_ehp_buff_ally` and `offensive_ehp_help`
  both replaced their inline per-(caster, action_id) checks with a
  single `buff_already_active` call. Untagged actions still get the
  legacy behavior (backward compatible — no migration required).
- **`bless_buff_encounter.yaml`:** the canonical Bless demo now
  declares `named_effect: bless` so cross-caster dedup is the
  exhibited behavior.
- **New fixture `two_clerics_bless_dedup_encounter.yaml`:** explicit
  proof — two clerics + fighter + ogre. Round 1 cleric_b casts Bless;
  cleric_a's scoring sees the Bless-tagged modifier on the fighter
  and chooses to attack with a mace instead. Without the dedup,
  cleric_a would have stacked their own Bless.
- 13 new tests in `tests/test_named_effects.py`:
  - `buff_already_active` detection (same caster legacy, different
    caster via named_effect, different named_effect doesn't dedup,
    untagged action falls back to legacy per-caster check)
  - `_build_modifier_entry` source-stamping (named_effect propagates;
    untagged action gets no named_effect on source; explicit source
    overrides the auto-stamp path)
  - Scoring integration via `offensive_ehp_buff_ally` and
    `offensive_ehp_help` (Heroism + Bless on same ally NOT deduped
    because different named_effect)
  - End-to-end fixture-driven test: fighter never carries 2+ Bless
    modifiers across the encounter
- Test count: 464 → 476. All green.

**Key decisions:**
- **Named effect is opt-in.** Untagged actions keep legacy
  per-(caster, action_id) dedup — fixtures pre-dating this PR
  continue to work. The "tag your spells with named_effect"
  recommendation is in `named_effects.py` docstring; we can migrate
  more fixtures incrementally.
- **Cross-caster check is the PRIMARY path, not a fallback.** When
  both paths could match, the named_effect check fires first. The
  per-(caster, action_id) check is kept only for untagged actions.
- **Don't auto-derive named_effect from action_id.** Tempting (every
  Bless fixture uses `id: a_bless`) but the convention isn't enforced
  — some test fixtures use scoped IDs like `a_bless_test`. Explicit
  named_effect avoids accidental cross-fixture aliasing.
- **"Most-potent-wins" deferred.** RAW lets a stronger casting
  supersede a weaker one. v1 just blocks the re-cast outright; in
  practice the duplicate case rarely matters because our current
  schema doesn't model upcasting that changes Bless's potency.

**Open items carried forward:**
- [ ] Defensive-buff dedup (Shield of Faith etc.) — same pattern
  would apply but isn't wired yet; defensive buffs go through a
  different scoring path
- [ ] Auto-end existing concentration when same caster re-casts
  the same named_effect on a DIFFERENT target — currently relies on
  the `apply_concentration` "new_cast_replaced" path which fires
  regardless of named_effect
- [ ] Most-potent-wins replacement (RAW: stronger upcast wins over
  weaker existing one)

---

## Session: 2026-05-26 — Per-creature recurring save for AoE control (PR #35)

**Participants:** Phil, Claude

**Work done:**
- Closes the Hypnotic Pattern story the same way PR #34 closed the
  concentration story. Held creatures now get a WIS save at the end
  of their own turn to break free per RAW. Before this PR, HP would
  hold creatures indefinitely until the caster lost concentration
  (or in the post-PR-#34 world, until the caster themselves became
  Incapacitated).
- **No new primitive needed.** The single-target `recurring_save`
  primitive (PR #21 era) already worked. PR #24's AoE `forced_save`
  loop swaps `state.current_attack.target` per-iteration before
  invoking on_fail / on_success sub-primitives, so dropping
  `recurring_save` into an AoE's `on_fail` block registers ONE entry
  per failed creature with the correct target_id automatically. The
  runner's `_resolve_recurring_saves` already filters by
  `entry.target_id == actor.id` at each turn_end. Three existing
  systems (PR #21 + PR #24 + the runner resolution path) compose
  for free.
- `tests/fixtures/hypnotic_pattern_vs_fireball_encounter.yaml`:
  added a `recurring_save` step to Hypnotic Pattern's `on_fail`
  block alongside the existing `apply_condition`. WIS save vs DC 15
  at `target_turn_end`, `on_success: end_spell_on_target` removes
  `co_incapacitated`.
- `engine/primitives.py`: `_recurring_save` docstring updated to
  spell out the AoE pattern (the "use this inside forced_save.on_fail
  to get per-creature registration" trick) so future spell authors
  can find it.
- 6 new tests in `tests/test_recurring_save_aoe.py`:
  - per-creature registration (one entry per failed creature)
  - passing creatures get no entry
  - runner resolution fires only the current actor's save at their
    turn_end
  - save success removes the condition from that creature only;
    other held creatures stay held
  - save failure keeps the entry for next turn
  - end-to-end via the live Hypnotic Pattern fixture
- Test count: 458 → 464. All green.

**Key decisions:**
- **Reuse the existing `recurring_save` primitive verbatim.** Tempted
  to add an AoE-aware variant; resisted because the per-target swap
  pattern in `forced_save` already does the right thing. A separate
  primitive would just duplicate logic.
- **Schema authoring lives in the fixture.** Each AoE control spell
  explicitly declares its recurring_save shape (ability / DC / when
  to roll / what to end on success). This is more verbose than auto-
  generating one but keeps every spell's RAW deviations explicit —
  Hold Person re-rolls at end of THAT creature's turn, Confusion
  re-rolls at end of THE TARGET'S turn, Sleep doesn't allow a
  recurring save at all, etc. The cost is one extra block per spell;
  the win is that schema reflects RAW directly.
- **No AoE-specific runner code.** All the heavy lifting is in the
  primitive composition. Each PR like this one that requires no new
  runner code is a sign the layering is right.

**Open items carried forward:**
- [ ] AoE control eHP scoring still uses
  `EXPECTED_CONTROL_ROUNDS = 2.5` as a flat estimate. With the per-
  creature breakout now active, the realized control duration is
  closer to ~2.5 rounds AT THE TARGET LEVEL but the spell ends
  earlier on creatures with good saves. The static estimate is
  still RAW-aligned for the framework's worked example; refining
  to per-target save-DC math is a future scoring tweak.
- [ ] The wizard self-targeting Hypnotic Pattern in the existing
  fixture is a separate AoE-targeting question — `affected:
  all_creatures_in_area` literally includes the caster. Friendly-
  fire avoidance for self-AoEs is a separate concern not in scope.

---

## Session: 2026-05-26 — Incapacitation ends concentration (PR #34)

**Participants:** Phil, Claude

**Work done:**
- Surgical hook in `_apply_condition`: when any condition that
  implies Incapacitated lands on a concentrating creature, end
  concentration with reason='incapacitated'. Closes the last
  unwired bullet in `concentration.py`'s "Deferred" docstring list
  from PR #21.
- `engine/core/concentration.py`: new module exports
  `INCAPACITATING_CONDITIONS` (frozenset of 5 condition ids:
  `co_incapacitated`, `co_stunned`, `co_paralyzed`, `co_unconscious`,
  `co_petrified`), `has_incapacitating_condition(target)`, and
  `check_incapacitation_breaks_concentration(target, state)`.
- `engine/primitives.py`: `_apply_condition` now calls
  `check_incapacitation_breaks_concentration` after
  `_instantiate_condition_effects` populates `applied_conditions`
  with all transitive (inherited) condition entries. That ordering
  matters — if we checked first, Stunned wouldn't yet show
  `co_incapacitated` in the conditions list.
- The check is conservative: explicitly lists both parent and
  inheriting conditions in the set. The inheritance logic in
  `_instantiate_condition_effects` already populates both, but
  listing the children explicitly makes the intent visible without
  requiring a registry lookup at break-time.
- 12 new tests in `tests/test_concentration_incapacitation.py`:
  - detection across all 5 incapacitating conditions
  - non-incapacitating conditions (Frightened / Charmed / Poisoned)
    do NOT trip the check
  - noop when not concentrating
  - noop when not incapacitated
  - per-condition end-concentration tests
  - integration through the real `_apply_condition` primitive
    (Paralyzed via inheritance, Frightened doesn't break)
- Documentation updates:
  - `concentration.py` module docstring: moved Incapacitation from
    "Deferred" to in-scope with the new function names referenced
  - `docs/engine-capabilities.md` §7: roadmap item flipped to
    shipped with the explanatory note
  - `docs/CONTEXT.md` unchanged (the item wasn't called out at the
    CONTEXT level; deferred list is now correct without edits)
- Test count: 446 → 458. All green.

**Key decisions:**
- **Check fires inside `_apply_condition`, not in a separate event
  handler.** The check is a hard RAW consequence of the condition
  application — they always happen together. Coupling them in the
  primitive keeps the dependency one-directional and avoids the
  event-bus subscription / ordering questions a separate handler
  would raise.
- **Explicit list of incapacitating condition ids, not registry
  walk.** Could have looked up each applied condition in the
  registry and checked its inheritance chain. But the set is small,
  fixed, and stable (5 condition ids per RAW). Explicit list is
  faster and self-documenting.
- **No primitive-level event for "incapacitation broke
  concentration."** The existing `concentration_ended` event with
  `reason='incapacitated'` is enough. Adding a separate event would
  just multiply log noise.

**Open items carried forward:**
- [ ] Concentration broken by forced movement / teleportation
  (uncommon — Banishment, Dimension Door, etc. typically don't
  break concentration anyway per RAW; the few effects that do are
  rare enough to defer)
- [ ] "Drop concentration to cast new better spell" eHP comparison
  in scoring (still relying on natural eHP competition)

---

## Session: 2026-05-26 — Second Wind v1 + feature_uses gate (PR #33)

**Participants:** Phil, Claude

**Work done:**
- Closes the chain from PR #31 (runner Action Surge) → PR #32 (auto-
  wired resources) → PR #33 (auto-wired Second Wind ACTION + the
  generic `feature_uses` gate that consumes the counter). A `pc:`
  spec with `class: c_fighter, level: 1+` now ships a wounded fighter
  who self-heals on the bonus slot without any manual setup.
- New `engine/core/feature_uses.py`: mirrors the `spell_slots.py`
  pattern. Actions declare `feature_use: <resource_key>` (a key in
  `actor.resources`); the candidate filter drops actions whose key
  is missing or ≤ 0, and execution decrements the counter and logs
  a `feature_use_consumed` event. Designed to be generic — Wizard
  Arcane Recovery, Lay on Hands, monster legendary actions, etc.
  will all hang off the same gate.
- `engine/core/pipeline.py`: added the feature_uses filter alongside
  the existing spell-slot filter in `generate_candidates`, and the
  consumption call alongside `consume_slot` in `execute`. Spell slots
  and feature uses are independent gates (an action could in
  principle consume both — no RAW spell does today).
- `engine/core/basic_actions.py`: added `is_self_targeted_heal` —
  sibling of `is_self_targeted_defensive_buff` — so a self-only heal
  emits ONE candidate instead of per-ally enumeration. Without this,
  Second Wind on a multi-ally party would emit N redundant candidates
  all targeting the caster.
- `engine/pc_schema.py`: extracted shared helpers
  `_features_known_at_level` + `_class_resources_at_level` (used by
  both `derive_pc_resources` and `build_pc_template`). New
  `_build_feature_actions` + `_build_second_wind_action`: when
  `f_second_wind` is in features_known and class is `c_fighter`,
  append the auto-generated bonus-action heal (type=heal, slot=
  bonus_action, target=self, dice=1d10, fixed=fighter_level,
  feature_use=second_wind_uses_remaining, is_signature=True).
- `is_signature: True` on the generated action is load-bearing —
  matches `f_second_wind.yaml`'s declared flag, and gates the bonus-
  slot roll against the 0.95 signature threshold instead of 0.60
  tactical. Without it, a wounded Fighter would skip Second Wind
  ~40% of the time even when it's the clear high-eHP play.
- Tests:
  - `test_feature_uses.py`: 16 tests covering all the gate primitives
    (required_feature_use, has_use, consume_use, remaining_uses) +
    pipeline candidate-filter integration + execution-consumption.
  - `test_second_wind.py`: 7 tests — action shape, level-scaled
    `fixed` modifier, feature-action generation guarded on
    f_second_wind + class=c_fighter, template integration, behavioral
    end-to-end with a wounded L2 Fighter (verifies the heal fires,
    counter decrements, `feature_use_consumed` event logs).
  - `test_pc_schema.py`: updated `test_level_3_fighter_full_template`
    to expect 2 actions (longsword + Second Wind) — was 1 (longsword
    only).
- New fixture `tests/fixtures/second_wind_encounter.yaml`: L2
  Fighter (`pc:` schema, no manual resources block) starting at 5/20
  HP vs goblin warrior. Seed 1: turn 1 fighter swings sword (Action
  Surge fires), then Second Wind on bonus slot (+7 HP, 5 → 12),
  `feature_use_consumed` event with `remaining: 1`. Goblin dies
  round 3.
- Test count: 423 → 446. All green.

**Key decisions:**
- **Feature uses as their own module, not a tag on spell_slots.**
  Different scoring (no opportunity-cost formula for features — flat
  candidate gate is right), different rest cadence (short-rest
  partial restore vs. long-rest-only spells), different schema (one
  named resource per feature vs. nine slot levels). Smaller blast
  radius for future features that want this gate.
- **Auto-generated Second Wind is_signature=True.** The bonus-slot
  resolution rolls against a tactical threshold by default (0.60)
  and a signature threshold for is_signature actions (0.95). Without
  the flag, a wounded fighter would skip Second Wind too often. The
  flag matches `f_second_wind.yaml`'s explicit declaration.
- **Self-targeted heal emits one candidate.** Same dedup pattern as
  defensive_buff/self (PR #29). Without it, an N-ally party with a
  self-targeted heal would generate N redundant candidates.
- **Inline `fixed` modifier, not modifier_source.** Fighter level
  doesn't change during an encounter, so resolving via a runtime
  expression is wasted work. Inlining at template-build time is the
  simpler choice.

**Open items carried forward:**
- [ ] Short / long rest semantics — counters never refresh in a
  multi-encounter session because no rest cycle exists in-engine.
  PR #31 documented this; same issue applies to second_wind_uses_
  remaining now. Multi-encounter sessions + rest mechanics are their
  own arc.
- [ ] Fighting Style passive modifiers — Great Weapon Fighting
  damage re-roll, Defense +1 AC, etc. Always-on, not action-gated.
- [ ] Extra Attack auto-generation (L5/L11/L20 → multiattack action
  with appropriate count)
- [ ] Weapon Mastery property tags
- [ ] Wizard Arcane Recovery (`slot_recovery_partial` primitive
  pending) — first non-Fighter consumer of the feature_uses gate

---

## Session: 2026-05-26 — Class-features auto-wiring v1 (PR #32)

**Participants:** Phil, Claude

**Work done:**
- Closes the loop on PR #31's manual fixture-level resource init.
  A `pc:` spec with `class: c_fighter, level: 2+` now auto-populates
  `action_surge_uses_remaining` (1 at L2-16, 2 at L17+) and
  `second_wind_uses_remaining` (from `class_resources` at the PC's
  level) — no manual `resources:` block needed.
- `engine/pc_schema.py`: new `derive_pc_resources(pc_spec, registry)`
  function. Walks the class's `level_table` up to the PC's level,
  accumulating feature IDs + class_resources (later levels overwrite
  lower-level values, matching RAW e.g. `second_wind_uses` going
  2 → 3 → 4 across levels). Maps `f_action_surge_one_use` → 1 charge
  and `f_action_surge_two_uses` → 2 charges (L17 supersedes L2).
- `engine/cli.py` `_build_actor`: calls `derive_pc_resources` for
  `pc:` actor_specs, merges with explicit `resources:` block (explicit
  wins). Non-PC actors are unaffected.
- New `tests/test_pc_schema_features.py` — 17 tests across L1/L2/L5/
  L16/L17/L20 AS bands + Second Wind counter scaling + edge cases
  (missing class, unknown class, broken registry, level defaults,
  level zero) + end-to-end via `_build_actor` (auto-derived resources
  visible on the Actor instance, explicit override semantics, non-PC
  actors unaffected).
- New fixture `tests/fixtures/action_surge_pc_schema_encounter.yaml`:
  L2 Fighter authored via `pc:` schema with NO `resources:` block —
  proves auto-wiring. Seed 1 shows `action_surge_activated` event +
  two `attack_roll` events on the fighter's turn.
- Test count: 406 → 423. All green.

**Key decisions:**
- **Explicit `resources:` wins on conflict.** Auto-derivation provides
  the defaults; fixture authors can still force edge cases (e.g.,
  `action_surge_uses_remaining: 0` on a L2 fighter to test the "no
  AS available" branch).
- **Don't fail on missing class.** If the class isn't in the registry
  (or the spec has no `class` field at all), `derive_pc_resources`
  returns `{}` silently. Lets exotic fixtures continue to work.
- **L17 AS upgrade as a separate feature ID.** Matches the existing
  schema convention in `c_fighter.yaml` (`f_indomitable_*` follow the
  same pattern: `_one_use`, `_two_uses`, `_three_uses` as distinct
  level-table entries). Cleaner than tracking a `uses_at_each_level`
  table inside one feature def.
- **Counter only, not action.** Second Wind's resource is now derived
  but the bonus-action heal action that CONSUMES it is NOT yet
  generated — that requires a `feature_uses`-gated action infra
  similar to spell-slot consumption. Deferred to a separate PR so
  this one stays small.

**Open items carried forward:**
- [ ] Second Wind action generation (bonus-action heal, gated by
  `second_wind_uses_remaining`) — needs feature_uses consumption infra
- [ ] Fighting Style passive modifiers (Great Weapon Fighting damage
  re-roll, Defense +1 AC, etc.) — always-on modifiers, not action-gated
- [ ] Extra Attack auto-generation (L5/L11/L20 → multiattack action
  with appropriate count)
- [ ] Weapon Mastery — Mastery property tags + per-weapon effects
- [ ] Subclass features
- [ ] Wizard Arcane Recovery (slot_recovery_partial — pending the
  primitive)

---

## Session: 2026-05-26 — Action Surge v1 (PR #31)

**Participants:** Phil, Claude

**Work done:**
- Fighter class feature: 1/short-rest extra Action per turn (2/short-
  rest at L17 but still 1/turn per RAW). Activation is a pre-action
  runner-level decision, NOT a candidate in the AI's main pool — RAW
  Action Surge GRANTS a second action; it doesn't replace one.
- `Actor.moved_this_turn` + `Actor.action_surge_used_this_turn` flags
  (both reset by `reset_turn`). `resources["action_surge_uses_remaining"]`
  is per-short-rest, NOT reset per turn — fixture-authored initial
  value at L2+ fighter setup.
- `EncounterRunner._maybe_activate_action_surge` heuristic:
  - charges > 0
  - at least one living enemy
  - at least one in-reach weapon_attack / multiattack candidate
  - not already activated this turn
- `_run_actor_turn` flow: activation check → main slot → bonus slot →
  re-run main slot once if AS fired. Main-slot re-run resets
  `actions_used_this_turn["action"]` so `apply_action_economy` treats
  it as fresh.
- `_move_to_engage` gated on `moved_this_turn` so Action Surge's
  second action can't grant a second move (RAW: one move per turn).
- `engine/cli.py` `_build_actor` now reads optional `resources:` block
  on actor spec (same pattern as `spell_slots`).
- 13 new tests in `tests/test_action_surge.py`: state defaults +
  reset_turn semantics + 5 activation-gate cases + single-turn cap
  with 2 charges + movement gate + integration (L2 fighter deals 2x
  damage in round 1) + control (no AS resource → one attack/turn) +
  no-double-move regression.
- New fixture `tests/fixtures/action_surge_encounter.yaml`: L2
  fighter with greatsword + 1 AS charge vs ogre (AC 18, 100 HP).
  Seed 1: `action_surge_activated` round 1, two `attack_roll` events
  from fighter before ogre's turn, single attack each round
  thereafter.
- Test count: 393 → 406. All green.

**Key decisions:**
- **Action Surge as runner-level activation, not a candidate.** RAW
  Action Surge doesn't cost an action — it GRANTS one. Modeling it
  as a candidate would mean the AI chooses AS *instead of* attacking,
  which is wrong. Pre-action evaluation in `_run_actor_turn` is the
  semantically correct fit.
- **In-reach-attack gate.** Without it, a L2 fighter would burn AS
  to take two `_move_to_engage` calls when they're out of range —
  pointless. With the `moved_this_turn` gate the second movement is
  suppressed anyway, but the AS charge would still be spent. Better
  to gate activation conservatively.
- **No `additional_action` primitive yet.** Action Surge's mechanic
  is purely a runner-loop concern; no pipeline / primitive needed.
  If a similar mechanic ever needs to fire from a pipeline (e.g., a
  spell that grants the target an extra action), the primitive can
  be added then.

**Open items carried forward:**
- [ ] Class features auto-wiring — when a L2+ fighter is loaded,
  auto-initialize `resources["action_surge_uses_remaining"]` from
  the class level table instead of requiring fixture authors to set
  it manually.
- [ ] Short / long rest semantics — currently no rest cycle exists
  in-encounter (the engine simulates single encounters). When multi-
  encounter sessions land, short rest needs to refresh AS charges.
- [ ] Magic-action gate — RAW 2024 Action Surge cannot be used to
  take a Magic action (cast a spell). v1 doesn't distinguish Magic
  actions; the AS second action could be any weapon_attack. Tighten
  when spell-action tagging arrives.

---

## Session: 2026-05-26 — Capabilities-doc refresh #5 (post-PR #26)

**Participants:** Phil, Claude

**Work done:**
- Fifth clean rewrite of `docs/engine-capabilities.md` to reflect the
  post-PR #26 state (3 PRs since last refresh: #24 Cone+Line AoE, #25
  Hypnotic Pattern, #26 Dodge+Disengage). Major updates:
  - Header bumped: post-PR #26, 375 tests across 15 modules, 14 fixtures
  - Status headline expanded to note all 3 RAW AoE shapes + AoE control
    + Dodge/Disengage + canonical Fireball-vs-HP worked example
  - §1 added subsections for AoE Cone+Line, AoE Control, Dodge,
    Disengage with the geometry / formula tables inline
  - §1 OA section updated to note Disengage suppression
  - §3 eHP Coverage Map: AoE Cone+Line, AoE control, Dodge,
    Disengage all flipped to ✅; Cone+Line dropped from deferred
  - §4 Primitives: added action-types section noting Dodge piggy-backs
    on defensive_buff; Disengage is a new action type
  - §5 Worked Examples: added Examples 8-10 (Burning Hands cone, HP
    vs Fireball canonical, Dodge under pressure)
  - §6 Test Surface: 324 → 375 tests; added 3 new test modules
  - §7 Roadmap: dropped Cone+Line, Hypnotic Pattern fixture, Dodge,
    Disengage; promoted PCs-default-to-Dodge, built-in basic actions,
    Help+Hide to top
- Refreshed `docs/CONTEXT.md` status table — added rows for PRs #24
  (Cone+Line), #25 (HP), #26 (Dodge+Disengage). Refreshed "Current
  phase" prose to reflect 21 PRs shipped. Refreshed "Next substantive
  steps" — PCs-default-to-Dodge at #1.
- Added 4 new entries to `docs/SESSIONS.md` (this refresh + #26 +
  #25 + #24).

**Key decisions:**
- **Status headline now notes the canonical worked example is wired**
  — the framework doc's "Hypnotic Pattern vs. Fireball" example is
  no longer aspirational; it's a deterministic CLI demo at seed 1.
- **Fifth clean rewrite** — pattern continues: every 3-4 feature PRs.

**Open items carried forward:**
- [ ] Pick next priority: PCs-default-to-Dodge, built-in basic
  actions, Help (Hide deferred — see below), Action Surge / Spirit
  Guardians, class features auto-wiring (see
  `docs/engine-capabilities.md` §7).
- [ ] **Hide is blocked on terrain modeling.** Hide RAW requires
  heavy obscurement or total cover to break LOS from observers;
  `geometry.py` is bare-positions-no-occlusion. When a cover / LOS /
  terrain layer lands (its own arc), Hide can ship with the same
  shape as Dodge. Do not bundle Hide with Help — they are not the
  same complexity class.

---

## Session: 2026-05-26 — Dodge + Disengage v1 (PR #26)

**Participants:** Phil, Claude

**Work done:**
- Two RAW defensive actions hooked into existing systems.
- **Dodge**: `defensive_buff` self-targeted action with
  `disadvantage_for_attacker` + DEX-advantage modifiers; lifetime
  `until_actor_next_turn_start`. **Zero new primitives** — piggy-backs
  on existing modifier registry + PR #20 `target: ally` work (which
  also supports `target: self`).
- **`defensive_buff_rounds: 1` action override** in
  `defensive_ehp_defensive_buff` for accurate Dodge scoring (lasts
  1 round, not the framework default 2.5).
- **Disengage**: new `type: disengage` action; execution sets
  `Actor.disengaging = True` (new field) and logs `disengage_taken`.
- **`Actor.disengaging` field** cleared by `reset_turn()` at start of
  next turn (correct RAW expiry: "until end of your turn").
- **OA suppression**: `find_oa_triggers` short-circuits to `[]` when
  `mover.disengaging` is True; logs `disengage_suppressed_oa`.
- **Disengage AI scoring**: flat 0.5 eHP constant — pickable but rarely
  beats real attacks. Real picking needs movement-aware AI (deferred).
- New `dodge_disengage_encounter.yaml`: Apprentice (weak mace + Dodge
  + Disengage) vs 2 brawlers. Seed 1: Apprentice picks Dodge each
  round; brawler attacks show `advantage_state: disadvantage`; PC
  absorbs heavy hits via misses.
- 11 new tests in `tests/test_dodge_disengage.py`. 375/375 total.

**Key decisions:**
- **Zero-new-primitive Dodge** — proved that the existing modifier
  + action-type system was rich enough to support new RAW actions
  declaratively. Future basic actions (Help, Hide) should follow the
  same pattern.
- **Disengage uses a new action type, not a primitive** — the
  mechanic is "set a flag, suppress OAs"; that's lighter than a
  full primitive in the registry. Could be revisited if more
  flag-setting actions emerge.
- **Disengage scoring is conservative** — flat 0.5 constant is
  rarely chosen by the AI, which is correct because Disengage's
  real eHP requires "what move am I about to make" planning that
  v1 doesn't have.

**Open items carried forward:**
- [ ] PCs default to Dodge in RP empty-set fallback per §6.4
- [ ] Built-in basic actions (Dodge/Disengage/Help/Hide for all actors)
- [ ] Movement-aware Disengage scoring
- [ ] Help — same shape as Dodge, separate PR
- [ ] Hide — DEFERRED until terrain / cover / LOS layer lands
  (Hide RAW needs obscurement or total cover to break LOS, which the
  engine doesn't model yet — see CONTEXT.md "Next substantive steps")
- [ ] Incapacitation ending Dodge

---

## Session: 2026-05-26 — Hypnotic Pattern + AoE Control v1 (PR #25)

**Participants:** Phil, Claude

**Work done:**
- Closes the **canonical Fireball-vs-Hypnotic-Pattern worked example**
  from `ehp-action-framework.md`. The AI now demonstrably chooses
  Hypnotic Pattern over Fireball when targets are too tanky.
- `engine/ai/ehp_scoring.py` extension — `offensive_ehp_aoe` now also
  scores `apply_condition` steps in the forced_save's on_fail /
  on_success. Without this, HP would score 0 (no damage) and never
  be cast.
- New helpers `_aoe_control_components(action, on)` (extracts
  apply_condition entries with their `denial_fraction`) and
  `_aoe_target_control_ehp(target, components)` (per-target eHP =
  `DPR × denial × EXPECTED_CONTROL_ROUNDS`).
- Main scoring loop now sums damage AND control per affected target;
  friendly fire applies to both. Mixed damage+control AoE spells
  automatically sum both contributions.
- New fixture `hypnotic_pattern_vs_fireball_encounter.yaml`: Wizard
  with both spells vs 3 beefy ogres (200 HP, 4d12+5 attacks, low
  WIS save). Seed 1: HP wins (~120 eHP vs Fireball's ~73 eHP per
  framework math).
- 13 new tests in `tests/test_aoe_control.py`. 364/364 total.

**Key decisions:**
- **Sphere as cube approximation** for HP's 30-ft cube — Chebyshev
  `actors_in_radius` already produces cube-equivalent semantics on
  a grid. Documented and acceptable for v1; distinct cube primitive
  deferred.
- **Per-target control helper factored cleanly** — same architecture
  as damage. `DPR × denial × rounds` returned per-target; caller
  multiplies by `p_fail` in the shared loop. Mixed damage+control
  spells (Witch Bolt-shape) "just work" by virtue of the structure.
- **Friendly fire applies to control too** — incapacitating an ally
  is correctly penalized.

**Open items carried forward:**
- [ ] True cube primitive (distinct from sphere)
- [ ] Per-creature recurring save to break HP at end-of-turn (single-
  target `recurring_save` works today; AoE-aware version deferred)
- [ ] HP-pool-based AoE controls (Sleep, Color Spray — different
  mechanic)
- [ ] "Damage breaks HP early" interaction (RAW: damage to a
  hypnotized creature breaks the charm)

---

## Session: 2026-05-26 — AoE Cone + Line v1 (PR #24)

**Participants:** Phil, Claude

**Work done:**
- Extends sphere AoE (PR #17) with the other two RAW 5e AoE shapes:
  cone (Burning Hands, Cone of Cold) and line (Lightning Bolt).
- `engine/core/geometry.py` — three new helpers:
  - `unit_direction(from_pos, to_pos)` — snaps a vector to 8
    cardinal/ordinal directions
  - `actors_in_cone(origin, direction, length_ft, actors)` — 5e RAW
    "length = width at far end" semantics; `2 * lateral ≤ forward + 1`
    grid-snap tolerance; origin excluded
  - `actors_in_line(origin, direction, length_ft, width_ft, actors)` —
    `lateral ≤ (width_squares - 1) // 2`; diagonal lines one square
    wide on rotated diagonal
- `engine/primitives.py:_resolve_save_targets` dispatches on
  `area.shape` (sphere/cone/line).
- `engine/core/pipeline.py:generate_candidates` for `aoe_attack`
  handles three shapes:
  - Sphere unchanged (origin = enemy.position)
  - Cone/line: origin = caster.position, direction = unit_vector
    toward enemy
  - Range gating differs: spheres gate by `range_ft` (placement
    range); cones/lines gate by `length_ft` (since origin IS caster)
- `_execute_single` propagates `area_direction` alongside
  `area_origin` into `state.current_attack`.
- `offensive_ehp_aoe` accepts optional `direction` parameter;
  dispatches on shape.
- New fixture `burning_hands_cone_encounter.yaml`: Wizard at (0,0) +
  3 east-line goblins + 1 lone north goblin. AI picks east direction
  (catches 3 goblins) over north (1 goblin). 27 new tests. 351/351
  total.

**Key decisions:**
- **8-direction snapping for v1.** 16-direction deferred.
- **Origin square excluded** from cones/lines (RAW).
- **`range_ft` semantics differ by shape** — spheres use it as
  placement range; cones/lines as length reach.
- **Direction flows through the candidate dict** — scoring at
  candidate-evaluation time can't read `state.current_attack`
  (not set up yet), so direction lives on the candidate.

**Open items carried forward:**
- [ ] 16-direction cones
- [ ] Spread origin (cone from remote point)
- [ ] Wider lines beyond width_ft
- [ ] Cone spread around obstacles (open-battlefield only v1)

---

## Session: 2026-05-26 — Capabilities-doc refresh #4 (post-PR #22)

**Participants:** Phil, Claude

**Work done:**
- Rewrote `docs/engine-capabilities.md` to reflect post-PR #22 state
  (was last refreshed after PR #17; 4 PRs of progress since: #19 PC
  Schema, #20 Offensive Buff, #21 Concentration, #22 Spell Slots).
  Major updates:
  - Header bumped: post-PR #22, 324 tests across 13 modules, 11 fixtures
  - Status headline expanded to enumerate every live capability
  - §1 added subsections for PC Schema (compact authoring), Offensive
    Buffs (Bless shape), Concentration (single-slot, CON-save-on-damage),
    Spell Slot Opportunity Cost (formula + reference value)
  - §3 eHP Coverage Map: Offensive buff for allies, Spell slot cost,
    Concentration all flipped to ✅; Cone+Line AoE stays deferred
  - §4 Primitives note extensions to `damage.multiplier`, `forced_save`
    area filtering + target swap, `attack_modifier target:ally`
  - §5 Worked Examples: added Example 8 (PC Schema fighter), 9 (Bless
    + concentration + slot consumption in one fixture), 10 (Multiattack)
  - §6 Test Surface: 238 → 324 tests; added 4 new test modules
  - §7 Roadmap: dropped PC schema, offensive buff, concentration,
    spell slots (all shipped); promoted Cone+Line AoE to #1; added
    Class features auto-wiring, Hypnotic Pattern fixture, Incapacitation
    ending concentration, Named-effect cross-caster dedup as smaller
    follow-ons
- Refreshed `docs/CONTEXT.md` status table — added rows for PRs #19
  (PC Schema), #20 (Offensive Buff), #21 (Concentration), #22 (Spell
  Slots). Refreshed "Current phase" prose to reflect 17 PRs shipped
  and the now-complete resource shape. Refreshed "Next substantive
  steps" — Cone+Line AoE at #1; PC schema / offensive buff /
  concentration / spell slots dropped from list.
- Added 5 new entries to `docs/SESSIONS.md` (this refresh + #22 +
  #21 + #20 + #19).

**Key decisions:**
- **Status headline now explicitly notes the resource shape is
  complete** — concentration + spell slot cost together mean the
  engine has the spatial axis (PR #15-#17) AND the resource axis
  (#21-#22) done. The "big architecture" framing in the headline now
  applies to both.
- **Fourth clean rewrite of engine-capabilities.md** — pattern holds:
  rewrite every 3-4 feature PRs cleanly rather than patching across
  8+ sections each time.

**Open items carried forward:**
- [ ] Pick next priority: Cone+Line AoE, more primitives, class
  features, Hypnotic Pattern fixture, or smaller follow-ons (see
  `docs/engine-capabilities.md` §7).

---

## Session: 2026-05-26 — Spell Slot Opportunity Cost v1 (PR #22)

**Participants:** Phil, Claude

**Work done:**
- Closes the **most-referenced deferred item** — five prior PRs (#7,
  #8, #17, #20, #21) had noted spell slot opportunity cost as missing
  from their eHP scoring.
- `engine/core/state.py`: `Actor.spell_slots: dict[int, int]` +
  `CombatState.encounters_remaining_today: int = 3` (urgency factor
  for cost formula).
- `engine/core/spell_slots.py` — new module:
  - `slot_cost_ehp(level, slots_remaining, encounters_remaining)`
    implements framework formula:
    `slot_level × 3.0 × scarcity × (1 - urgency)`
    where `scarcity = 1/max(1, slots_remaining)` and
    `urgency = encounters_remaining / 6`. Matches the worked example
    exactly: 3rd-level slot, 1 left, 0 encounters remaining = **9.0
    eHP** (the Fireball reference value).
  - `has_slot`, `remaining_slots`, `consume_slot` (decrements + logs
    `spell_slot_consumed`), `candidate_slot_cost` (public eHP-cost API).
- `engine/core/pipeline.py`:
  - `generate_candidates` filters out spell actions whose required
    slot is unavailable (alongside existing reach filter).
  - `_execute_single` consumes the slot when action has
    `spell_slot_level > 0`.
- `engine/ai/decision_layer.py`: `score_candidates_v1` subtracts
  `candidate_slot_cost` from raw eHP BEFORE aggression scaling.
- `engine/cli.py`: `_build_actor` accepts top-level `spell_slots`
  dict; PC schema spec surfaces it.
- `tests/fixtures/bless_buff_encounter.yaml`: cleric now has `{1: 3}`
  starting slots; Bless tagged `spell_slot_level: 1`. Visible
  behavior: cleric burns through 3 slots over a long encounter,
  then falls back to mace permanently.
- 25 new tests in `tests/test_spell_slots.py`. 324/324 total.

**Key decisions:**
- **Free actions are the default.** Anything without `spell_slot_level`
  (martial weapons, monster attacks, cantrips) incurs no cost.
- **Candidate filter is the hard gate; scoring cost is the soft nudge.**
  AI can never accidentally cast without a slot.
- **encounters_remaining_today on CombatState** is the v1 surface.
  Per-actor override (warlock pact magic) deferred.
- **Cost subtracted in eHP units** (same scale as gain) per framework
  guidance. A 1st-level Bless (~6 eHP gain) at scarcity max + mid-day
  costs ~0.75 eHP — small, doesn't prevent casting, but starts to
  matter as slots dwindle.

**Open items carried forward:**
- [ ] Upcasting (cast 1st-level spell with higher-level slot)
- [ ] Pact Magic (warlock short-rest restoration)
- [ ] Spell points variant
- [ ] Long rest mid-simulation (multi-encounter day)
- [ ] Per-class spell preparation lists
- [ ] Cantrips with formal level 0 (v1: just absent)
- [ ] Per-actor encounters_remaining_today override
- [ ] Hypnotic Pattern fixture for Fireball-vs-HP worked example

---

## Session: 2026-05-25 — Concentration v1 (PR #21)

**Participants:** Phil, Claude

**Work done:**
- Implements 5e concentration: one slot per actor, auto-drop on new
  cast, CON save on damage (DC = max(10, ⌈dmg/2⌉)), drop on death.
- `engine/core/state.py`: `Actor.concentration_on` field.
- `engine/core/concentration.py` — new module:
  - `apply_concentration(caster, action, state)` — sets slot,
    auto-drops prior, logs.
  - `end_concentration(caster, state, reason)` — scans every actor,
    removes modifiers + applied_conditions tagged with this
    concentration's source.
  - `attempt_concentration_save(target, damage_taken, state, rng)` —
    RAW DC formula; fail → end_concentration.
- `engine/core/pipeline.py:_execute_single` calls `apply_concentration`
  if action has `concentration: true`.
- `engine/primitives.py:_damage`:
  - After HP loss, if target concentrating: rolls CON save.
  - On creature_dropped: ends concentration before the event so
    listeners see a clean state.
- `bless_buff_encounter.yaml`: Bless tagged `concentration: true`.
- 18 new tests in `tests/test_concentration.py`. 299/299 total.

**Key decisions:**
- **Damage hook in `_damage`** — every damage path (weapon, AoE,
  OAs, multiattack sub-attacks) auto-triggers the save. No per-
  primitive plumbing.
- **Death cleanup runs before `creature_dropped`** — anything
  listening to that event sees a fully de-concentrated actor.
- **AI trade-off is implicit** — natural eHP competition between
  candidates handles "drop concentration for better spell" without
  explicit switching-cost logic. The PR #20 dedup prevents the most
  common pathology (re-casting the same buff).
- **Per-actor scan is O(N×M)** — fine at encounter scale; could
  index by (caster_id, action_id) later if profiling shows it's hot.

**Open items carried forward:**
- [ ] Incapacitation ending concentration (Paralyzed/Stunned/Unconscious)
- [ ] Explicit "drop concentration to switch" eHP comparison
- [ ] Concentration broken by forced movement / teleportation

---

## Session: 2026-05-25 — Offensive Buff v1 (PR #20)

**Participants:** Phil, Claude

**Work done:**
- Closes the symmetric counterpart to defensive_buff: a caster can
  now boost an ally's hit chance with attack_modifier-style spells
  (Bless-shape).
- `engine/core/pipeline.py`: new `offensive_buff` action type in
  `generate_candidates`. Enumerates per ally; skips self.
- `engine/primitives.py`:
  - `_resolve_modifier_owner` extended for `target: ally` /
    `target: current_target` — attaches modifier to
    `state.current_attack.target`.
  - `_build_modifier_entry` tags source with `{action_id, caster_id}`
    when none provided. Lets eHP scoring detect "this target already
    has my buff" and skip redundant re-casts.
- `engine/ai/ehp_scoring.py`:
  - `extract_offensive_buff_effect(action)` — reads attack_bonus or
    ally_advantage from pipeline.
  - `offensive_ehp_buff_ally(actor, target_ally, action, state)` —
    `ally_DPR × Δhit × EXPECTED_BUFF_ROUNDS` per framework.
  - Constants: `HIT_PROB_PER_FLAT_BONUS = 0.05` (each +1 ≈ +5% hit
    chance), `DELTA_HIT_FROM_ADVANTAGE = 0.225`. Bless +2 ≈ +10-12.5%
    matches framework reference.
  - **Dedup guard**: returns 0 if target already has matching buff
    from this caster.
  - `score_candidate` dispatches `kind='offensive_buff'`.
- New fixture `tests/fixtures/bless_buff_encounter.yaml`: cleric
  (Mace + Bless) + fighter (Greatsword) + bruiser. Cleric picks
  Bless on round 1, switches to mace on subsequent rounds.
- 17 new tests in `tests/test_offensive_buff.py`. 281/281 total.

**Key decisions:**
- **Behavioral discovery during integration**: original implementation
  had the cleric recasting Bless every turn, stacking modifiers
  (fighter's attack bonus climbed +2/round). Fixed by source-tagging
  + scoring dedup. **The fix flipped the demo encounter outcome from
  enemy victory → PC victory** because the cleric now correctly
  switches to attacking once Bless is up.
- **Single-target buffs for v1.** Multi-target (Bless on 3 creatures,
  Aid on multiple) deferred.
- **Dedup is per-(caster, action_id)** — different casters each apply
  their own Bless; same caster won't double-stack. Real 5e prevents
  same-spell stacking from ANY caster, but that's a separate change.
- **Δhit math uses framework reference values.** Each +1 flat ≈ +5%
  hit chance; advantage ≈ +22.5%.

**Open items carried forward:**
- [ ] Multi-target offensive buffs (Bless on 3, Aid on multiple)
- [ ] Faerie Fire (debuff on enemy granting advantage to ALL attackers)
- [ ] Bardic Inspiration (reaction buff)
- [ ] Concentration mechanics — CLOSED in PR #21
- [ ] Spell slot opportunity cost — CLOSED in PR #22
- [ ] Self-buff scoring (caster picks self-Bless vs swing-weapon)
- [ ] Named-effect tagging for cross-caster dedup

---

## Session: 2026-05-25 — PC Schema v1 (PR #19)

**Participants:** Phil, Claude

**Work done:**
- Replaces the inline-monster-template hack that PC fixtures had
  been using since the skeleton landed. New compact `pc:` actor_spec
  shape lets you declare a PC by class + level + ability scores +
  armor + weapons; engine derives HP, AC, proficiency bonus, save
  bonuses, and per-weapon attack actions automatically.
- `engine/pc_schema.py` — new module:
  - `build_pc_template(pc_spec, content_registry)` returns a full
    monster-style template dict.
  - Pure helpers: `_lookup_pb` (level_table → PB), `_compute_hp`
    (L1 max + L2+ avg per die + CON), `_compute_ac` (base_ac +
    min(DEX, max_dex)), `_build_abilities_with_saves` (mod + PB if
    class-proficient), `_build_weapon_action`.
  - Telemetry: `derived_from_pc_schema: {class, level}` tagged.
- `engine/cli.py`: `_build_actor` recognizes new `pc:` key alongside
  `template:` (inline) and `template_ref:` (lookup). Three shapes
  coexist; existing fixtures unchanged.
- New fixture `tests/fixtures/pc_schema_fighter_encounter.yaml`:
  Level 3 Fighter via compact pc: spec vs Goblin Warrior via
  template_ref. **Verified identical-behavior** to the inline-template
  smoke_encounter at same seed.
- 26 new tests in `tests/test_pc_schema.py`. 264/264 total.

**Key decisions:**
- **Opt-in, backward compatible.** All 9 existing fixtures + their
  tests unchanged. `pc:` is the new third option.
- **Leans on existing class schema content.** `c_fighter.yaml`'s
  `core_traits.hit_die` + `level_table.proficiency_bonus` +
  `core_traits.save_proficiencies` are the slim layer the derivation
  reads. Class features in `level_table` (Second Wind, Action Surge,
  Fighting Style) are referenced by id but not yet consumed.
- **No new dependencies.** Pure Python + existing deps only.
  Pyodide-invariant preserved.

**Open items carried forward:**
- [ ] Class features (Second Wind, Action Surge, Fighting Style)
- [ ] Multiclass
- [ ] Spellcasting → action generation
- [ ] Subclasses
- [ ] Starting equipment library (longsword / chain_mail lookups)
- [ ] Skill / tool proficiencies
- [ ] ASI / feats
- [ ] Race / species, background

---

## Session: 2026-05-25 — Capabilities-doc refresh after AoE (post-PR #17)

**Participants:** Phil, Claude

**Work done:**
- Rewrote `docs/engine-capabilities.md` to reflect post-PR #17 state
  (was last refreshed after PR #12; 4 PRs of progress since: #14
  Pyodide doc, #15 positioning, #16 OAs, #17 AoE). Major updates:
  - Header bumped: post-PR #17, 238 tests across 9 modules, 9 fixtures
  - Status headline expanded to include positioning, reactions, AoE
  - §1 added subsections for Positioning / Movement / Reachability,
    Opportunity Attacks, AoE attacks
  - §1 Action Economy section updated to note OAs are LIVE (not
    wired-but-dormant)
  - §3 eHP Coverage Map: AoE multi-target + friendly fire flipped to
    ✅; added "Cone + Line AoE shapes" as deferred
  - §4 Primitives note updates to `damage` (multiplier) and
    `forced_save` (area filtering + per-target target-swap)
  - §5 Worked Examples: added 3 new examples (ranged_vs_melee, OA,
    Fireball cluster)
  - §6 Test Surface: 178 → 238 tests; added 3 new test modules
  - §7 Roadmap: dropped positioning + AoE (now shipped); promoted PC
    schema to #1; added Cone+Line as #4
  - §8 Source pointers: added browser-deployment doc reference
- Refreshed `docs/CONTEXT.md` status table — added rows for PRs #15
  (Positioning), #16 (OAs), #17 (AoE). Refreshed "Current phase"
  prose to reflect 13 PRs shipped and the now-complete spatial axis.
  Refreshed "Next substantive steps" — PC schema at #1; positioning/
  AoE dropped from list.
- Added five new entries to `docs/SESSIONS.md` (this refresh + #17
  AoE + #16 OAs + #15 Positioning + a small entry for the #14
  browser-deployment doc note).

**Key decisions:**
- **Third clean rewrite of engine-capabilities.md** — patches across 8+
  sections aren't worth the diff-review burden. Same shape, fresh
  content. Pattern: rewrite the capabilities doc roughly every 3-4
  feature PRs.
- **Status headline now explicitly notes spatial axis is complete** —
  big inflection: with positioning, OAs, and AoE in, the engine's
  big-architecture work is done. Future PRs are content + depth.

**Open items carried forward:**
- [ ] Pick next priority: PC schema, offensive buff for allies, spell
  slot opportunity cost, Cone+Line AoE, or more primitives (see
  `docs/engine-capabilities.md` §7 roadmap).

---

## Session: 2026-05-25 — AoE Geometry v1 (PR #17)

**Participants:** Phil, Claude

**Work done:**
- Implemented Area-of-Effect attacks — **the first multi-target eHP
  scoring in the engine**. Every prior candidate scored against
  exactly one target; AoE candidates now score against the set of
  creatures caught in the blast.
- `engine/core/geometry.py`: new `actors_in_radius(origin, radius_ft,
  actors)` using Chebyshev (2024 PHB "diagonals = 5 ft" rule).
- `engine/primitives.py`:
  - `_damage` accepts `multiplier: float` param (default 1.0). 0.5 =
    half-damage-on-save (AoE on_success); 2.0 doubles. Applied after
    resistance/vuln/immunity.
  - `_resolve_save_targets` for `affected: all_creatures_in_area`:
    filters by `actors_in_radius` when `area_origin` + `area.radius_ft`
    are set; falls back to legacy "all enemies" for backward
    compatibility.
  - `_forced_save` swaps `state.current_attack.target` per iteration
    so damage primitives in `on_fail`/`on_success` hit the right
    creature, then restores.
- `engine/core/pipeline.py`:
  - `generate_candidates`: new `aoe_attack` action type emits one
    candidate per living enemy whose position is within the action's
    `area.range_ft`. Candidate's `origin_point` = enemy position
    (naturally tries cluster centers).
  - `_execute_single` propagates `candidate.origin_point` into
    `state.current_attack.area_origin`. Logs `aoe_origin_placed`
    event.
- `engine/ai/ehp_scoring.py`: new `offensive_ehp_aoe(actor, origin,
  action, state)` — for each living creature in radius:
  `(p_fail × full_dmg) + (p_save × half_dmg)` capped at HP. Positive
  for enemies, **negative for allies** (friendly fire, 1.0 weight in
  v1). Caster counts as ally. `score_candidate` dispatches
  `kind='aoe_attack'` to it.
- New fixture `tests/fixtures/fireball_cluster_encounter.yaml`:
  Evocation Wizard with Magic Dart + Fireball vs 3 clustered goblins.
  Seed 1 trace: AI casts Fireball at cluster center; 1 goblin dies,
  2 left at 3 HP each. 2-round PC victory.
- 15 new tests across geometry, damage multiplier, AoE scoring
  (no-creatures = 0, single enemy positive, 3-enemy cluster scores
  more, friendly fire subtracts, self-fireball negative), candidate
  generation, end-to-end.
- 238/238 tests pass.

**Key decisions:**
- **Sphere only for v1.** Cone + Line shapes deferred — they need
  direction vectors which add a complexity layer. Sphere covers
  Fireball, Shatter, Spirit Guardians, Sleep — most common AoE.
- **Per-enemy-position origin enumeration** is the v1 origin search
  strategy. Captures "cast on the cluster" naturally without
  combinatorial scan. Smarter origin search (centroid, fine-grid scan)
  deferred.
- **Friendly fire is RAW.** AoE catches everyone in radius including
  allies and the caster. eHP scoring subtracts ally damage from
  candidate's total. **Don't fireball yourself** is now a real
  engine invariant verified by test.
- **Target-swap pattern in `_forced_save`** preserves the damage
  primitive's `state.current_attack.target` invariant while iterating
  multiple targets. Restored after.
- **Backward compatible.** `_resolve_save_targets` falls back to
  legacy "all enemies" if `area_origin` not set. All 9 existing
  fixtures behave identically.

**Open items carried forward:**
- [ ] Cone + Line AoE shapes (sphere only v1).
- [ ] Spell slot opportunity cost (proper caster eHP scoring).
- [ ] Concentration mechanics (Hold Person, Spirit Guardians etc.).
- [ ] "Smart" origin candidates beyond per-enemy (centroid, fine-grid
  scan).
- [ ] Spell template integration (`cast_spell` action referencing
  a YAML spell template).
- [ ] Wall spells / persistent areas (Wall of Fire, Spike Growth).
- [ ] Cover affecting AoE saves.
- [ ] `self_preservation_coefficient` scaling on friendly fire.

---

## Session: 2026-05-25 — Opportunity Attacks v1 (PR #16)

**Participants:** Phil, Claude

**Work done:**
- Activated Opportunity Attacks — the first reaction type wired. The
  Action Economy dial's `oa_reaction` percentages (80-100% across all
  5 presets) were already in the table; this PR makes them actually
  fire.
- New module `engine/core/reactions.py`:
  - `find_oa_triggers(mover, pre_position, state)` — returns
    (reactor, melee_attack_action) pairs. Trigger condition: reactor's
    melee reach covered mover's pre-position AND does not cover
    mover's post-position (mover left their reach). Filters out: dead
    reactors, same-side, no-melee-weapon, reaction-already-used.
  - `resolve_opportunity_attacks(mover, pre_position, state, bus,
    primitives, rng)` — orchestration. Per trigger: roll vs
    `oa_reaction` AE percentage. On pass: temporarily snap mover back
    to pre_position so `attack_roll`'s out-of-range guard sees the
    in-reach distance; execute the OA attack pipeline (inline so the
    action's `slot` field doesn't trigger main-action-slot marking);
    mark reactor's reaction slot used. Stop if OA killed the mover.
- `engine/core/runner.py`: `_move_to_engage` calls
  `resolve_opportunity_attacks` after the move completes. `_run_slot`
  checks `actor.is_alive()` after movement and skips cleanly if the
  OA dropped the actor.
- New fixture `tests/fixtures/opportunity_attack_encounter.yaml`:
  Polearm Guardian (glaive reach 10) + immobile Wounded Cleric +
  Goblin Scout (weakest_target preset, can't reach guardian with own
  scimitar). Seed 1 trace shows OA firing as goblin moves to engage
  healer:
    moved: goblin from [3,0] to [1,0]
    opportunity_attack_triggered: reactor=guardian, mover=goblin
    attack_roll: guardian → goblin (the OA)
    attack_roll: goblin → healer (main action completes)
- 16 new tests across trigger detection (8 cases), orchestration
  (AE percentage gating, reaction slot tracking, position restoration,
  no-OA on no-trigger), and runner integration (real encounter fires
  OA; ranged-only attacker never OAs).
- 223/223 tests pass.

**Key decisions:**
- **Inline OA execution** (separate from `pipeline.execute`) — needed
  because `pipeline.execute` marks the action's `slot` field which
  would clobber main-action tracking. OA marks `reaction` instead.
- **Position snap during OA** — mover's position temporarily restored
  to pre-move so `attack_roll`'s out-of-range guard (added in
  positioning PR #15) sees the in-reach distance. Restored to
  post-move after (unless mover died).
- **One OA per reactor per round** via existing
  `actions_used_this_turn["reaction"]`, reset at the reactor's own
  turn-start by `actor.reset_turn()`.
- **AE gating uses already-wired percentages.** Optimal 100%, Skilled
  100%, Average 95%, Casual 85%, Reactive_only 80%. Even mindless
  creatures OA per spec "they moved, I swing."
- **Multi-square path checking deferred.** Only pre/post positions
  compared. "Pass-through" OAs (mover enters then leaves reach in one
  move) are missed. Most common case (leaving an established melee)
  works correctly.
- **Discovered during testing**: my first integration test had a
  healer moving toward the goblin and engaging in melee — which then
  meant the goblin had a reachable target and didn't need to move at
  all (no OA). Fixed by making the demo healer immobile (speed=0).
  The interaction itself is correct AI behavior — close-by reachable
  targets get attacked, distant ones get movement.

**Open items carried forward:**
- [ ] Multi-square path checking (pass-through OAs).
- [ ] Sentinel / Polearm Master feats (extra OA triggers).
- [ ] Disengage action grants no-OA-from-leaving (needs Disengage
  primitive).
- [ ] Sophisticated OA action selection (uses first available melee).
- [ ] OA from forced movement (push / pull / teleport).
- [ ] OA against ranged attacks made in melee.
- [ ] OA-aware path planning (mover avoids them).

---

## Session: 2026-05-25 — Positioning v1 (PR #15)

**Participants:** Phil, Claude

**Work done:**
- **The biggest structural unblock in the engine's history.**
  Creatures had `(x, y)` fields but they were always `(0, 0)`; melee
  reach defaulted to TRUE for everyone; ranged weapons had no range
  field; movement didn't exist. All four are now wired.
- New module `engine/core/geometry.py`:
  - `distance_ft` — Chebyshev × 5 (5e 2024 "diagonals = 5 ft" rule;
    simpler than alternating 5/10)
  - `is_within_ft`, `required_movement_ft`
  - `move_toward` with `stop_at_ft` parameter so creatures land
    adjacent (in reach), not stacked on the target's square
- Six surgical edits in existing modules:
  - `engine/cli.py` — `_build_actor` accepts optional `position: [x, y]`
    per actor_spec (defaults `(0, 0)`)
  - `engine/ai/targeting.py` — `_closest_enemy` now uses real
    distance, ties broken by turn order
  - `engine/core/modifiers.py` — `attacker_within_ft(N)` /
    `attacker_not_within_ft(N)` when-clauses actually evaluate
  - `engine/core/pipeline.py` — `generate_candidates` filters by reach
    (melee uses `reach_ft`, ranged uses `range_ft`, multiattack uses
    max sub-action reach)
  - `engine/primitives.py` — `attack_roll` guards against out-of-range
    execution (auto-miss with `reason='out_of_range'` telemetry)
  - `engine/core/runner.py` — `_run_actor_turn` has a movement phase
    via `_move_to_engage`. Two-phase main slot: try to act → move
    toward dial-preferred target up to walk speed (stops at MAX reach
    across actor's actions, so creatures land adjacent for melee not
    stacked on target) → try again → log `passed_turn` if still
    nothing reachable. Bonus slot doesn't move.
- New fixture `tests/fixtures/ranged_vs_melee_encounter.yaml`:
  Halfling Archer (Longbow, range 80) at (0,0) vs Goblin Brawler
  (Scimitar, reach 5) at (12, 0) = 60 ft. Trace:
    - Round 1: goblin moves 30 ft → still 30 ft out → passed_turn
    - Round 1: archer shoots from position (no moved event)
    - Round 2: goblin moves 25 ft (stops at melee adjacency, NOT
      stacked) → hits for 3
    - Round 3-4: melee exchange, archer wins
- 29 new tests across pure geometry, reachability filter, when-clause
  evaluation, attack_roll out-of-range guard, and runner integration.
- 207/207 tests pass.

**Key decisions:**
- **2D only.** No Z-axis / flying / climbing for v1.
- **Open battlefield assumption.** No walls / obstacles / path-finding
  for v1.
- **Chebyshev × 5 distance** per 2024 PHB. Alternating 5/10 rule
  deferred.
- **`move_toward` stops at `stop_at_ft`** — caught a real bug during
  testing where creatures were ending up in the same square as their
  target. Fixed by passing the actor's max reach so they land adjacent.
- **Two-phase movement** in `_run_actor_turn`: try to act → if no
  in-range candidates, move toward dial-preferred target → try again.
  Movement is a main-slot resource; bonus slot doesn't move.
- **`attack_roll` out-of-range guard** auto-miss with telemetry as a
  safety net for multiattack execution paths that might invoke a
  short-reach sub-action beyond its reach.
- **Existing 6 fixtures behave identically** — all positions default
  to `(0, 0)`, preserving the "everyone in melee range" assumption
  baked into pre-positioning tests and fixtures.

**Open items carried forward:**
- [ ] Opportunity attacks — movement-triggered reaction events;
  would activate the already-wired `oa_reaction` AE percentages. ←
  CLOSED in PR #16.
- [ ] Soft control / movement denial scoring (the deferred eHP family).
- [ ] `frontline` / `library_protect` RP constraints (proximity-aware).
- [ ] AoE geometry (radius / cone / line) — sphere CLOSED in PR #17;
  cone + line deferred.
- [ ] Difficult terrain (speed halving).
- [ ] Cover (half / three-quarters).
- [ ] Flanking (optional 5e rule).
- [ ] 3D / flying / climbing.
- [ ] Path-finding around obstacles.
- [ ] Visibility / line-of-sight beyond existing Blinded condition.
- [ ] Dash / Disengage / Withdraw action primitives.
- [ ] "Kiting" / stay-at-preferred-range optimization for ranged.

---

## Session: 2026-05-25 — Browser deployment option doc (PR #14)

**Participants:** Phil, Claude

**Work done:**
- Documented Pyodide / browser deployment as the **Stage 2 deployment
  target**. Came out of Phil asking whether Gemini's suggestion fit
  the plan.
- New doc `docs/architecture/browser-deployment.md` (~160 lines):
  - Why this engine is unusually Pyodide-friendly (invariants table
    aligning with existing Foundry-bridge invariants)
  - Where browser deployment fits the 4-stage plan (Stage 2
    report-companion layer, NOT a Foundry replacement)
  - Invariants to preserve: no native C deps, loader supports string
    content when built, CLI stays a thin wrapper, plain-data state,
    synchronous only
  - Performance reality check (~50-85ms per encounter; MC 1k ≈
    1-2 min in browser; MC 10k+ stays backend)
  - ~1-3 day build scope when triggered
  - Trigger conditions: first Stage 2 report ready, "no Python
    install" community ask, or outreach demo
- Added a status-table row in `docs/CONTEXT.md` pointing to the doc
  with the dependency-check reminder.
- Added a "Next substantive steps" item so it's discoverable as
  future work.

**Key decisions:**
- **Engine architecture already enables it** — Foundry-bridge
  invariants (plain-data state, library-first, no native deps) also
  unlock browser deployment as a side effect. No engine refactor
  needed; just preserve the invariants.
- **Captured as documented option, not immediate build task.**
  Pyodide build itself becomes a Stage 2 task. Until triggered, the
  doc just makes sure future PRs don't break the enabling invariants.

**Open items carried forward:**
- [ ] `engine/loader.py:load_yaml_string` sibling (when build triggered).
- [ ] Static frontend + Web Worker + GitHub Pages/Firebase setup.
- [ ] "Run in browser" links on each Stage 2 published report.

---

## Session: 2026-05-25 — Capabilities-doc refresh after RP Constraints

**Participants:** Phil, Claude

**Work done:**
- Rewrote `docs/engine-capabilities.md` to reflect the post-PR #12 state
  (was last refreshed after PR #8; 3 PRs of progress since). Key updates:
  - Engine state: post-PR #12 (all 4 dials + RP Constraints live)
  - Status headline: all 8 pipeline steps now active
  - §1 added subsections for Action Economy presets + Retreat dial
    presets + RP Constraint types
  - §2 Decision Pipeline table flipped steps 1, 3, 4, 7 from 🔴 to ✅
  - §5 Worked examples updated to reflect retreat behavior shifts;
    added Example 3 (nimble_goblin bonus slot) + Example 4 (pacifist
    Pass-turn)
  - §6 Test surface: 103 → 178 tests; added 3 new test modules
  - §7 Roadmap: dropped Action Economy / Retreat / RP Constraints
    (now shipped); positioning promoted to #1
- Refreshed `docs/CONTEXT.md` status table — added rows for PRs #10
  (Action Economy), #11 (Retreat), #12 (RP Constraints). Refreshed
  "Current phase" prose and "Next substantive steps" list.
- Added three new entries to `docs/SESSIONS.md` (RP Constraints v1,
  Retreat dial v1, Action Economy dial v1) plus this refresh entry.

**Key decisions:**
- **Rewrote engine-capabilities.md rather than patching** — 3 PRs of
  changes touched too many sections to edit cleanly. Same shape, fresh
  content.
- **CONTEXT.md keeps the one-liner-per-PR convention.** Each new PR
  gets its own row in the status table. Engine-capabilities.md handles
  depth.
- **No strategic / pitch / Trusight content.** Engine repo is public;
  docs are engineering-progress only.

**Open items carried forward:**
- [ ] Pick next priority: positioning, PC schema, offensive buff for
  allies, spell slot opportunity cost, or more primitives (see
  `docs/engine-capabilities.md` §7 roadmap).

---

## Session: 2026-05-25 — RP Constraints v1 (PR #12)

**Participants:** Phil, Claude

**Work done:**
- Implemented RP Constraints — identity / personality / story-bound
  behavior — closing the last stubbed pipeline steps. **All 8 decision-
  pipeline steps from `pillars-reconciliation.md` §7 are now live.**
- New module `engine/ai/rp_constraints.py`:
  - `ConstraintDef` (library entry) + `ActiveConstraint` (per-actor
    instance with severity / priority overrides).
  - Canonical library: 4 of 12 v1 constraints proving all 3 types —
    `pacifist_strict` (hard_filter), `heal_priority` (forced_choice),
    `signature_first` (forced_choice), `resource_hoarder`
    (weighted_preference, negative severity for penalty).
  - `apply_hard_filters` — Tier 1 set intersection per §6.4.
  - `apply_forced_choice_boosts` — Tier 2 priority-winner-only boost
    per §6.3 + §6.4 (highest priority wins; ties by registration
    order; others suppressed).
  - `apply_weighted_preferences` — Tier 3 cumulative additive per
    §6.4 single coherent scoring pass.
  - `apply_score_modifications` — chained Tier 2 then Tier 3.
- `engine/ai/decision_layer.py`: `score_candidates_v1` chains the RP
  score modifications after base eHP + preference scoring.
- `engine/core/pipeline.py`: `apply_hard_filters` delegates;
  `apply_forced_choices` stays a pass-through (work happens at scoring
  time per §6.3 score-weight semantics).
- `engine/core/runner.py`: empty-set fallback. When hard filters empty
  the candidate set, runner logs `passed_turn` event with reason
  `rp_hard_filter_empty_set` and skips execution. v1 has both PCs and
  monsters Pass turn (Dodge primitive deferred).
- New fixture `tests/fixtures/pacifist_encounter.yaml`: Strict Pacifist
  Monk vs attacking goblin. Pacifist has only attack actions →
  hard filter empties every turn → `passed_turn` logged each round.
  Outcome: pacifist flees alive at 2/30 HP (her Default retreat dial
  fires from Bloodied trigger); zero attack_roll events from pacifist
  over 7 rounds.
- 19 new tests in `tests/test_rp_constraints.py`: library + active-
  constraint resolution; Tier 1 hard filter (pacifist filters damage,
  intersection, empty result legal, multiattack subaction inspection);
  Tier 2 forced choice (heal_priority boost; trigger gating;
  signature_first round-1-only; priority resolution when multiple
  trigger); Tier 3 weighted preference (resource_hoarder -30% on
  spells); chained modifications; pacifist Pass-turn integration;
  heal_priority overriding attack preference at sev 2.0.
- 178/178 tests pass.

**Key decisions:**
- **Forced Choice severity = score boost, not narrowing.** Per §6.3
  explicit "score priority weight" semantics. The §6.4 "narrowing"
  description is informal; sufficient severity creates effective
  narrowing without filter semantics.
- **Forced Choice priority = exclusivity, not stacking.** When
  multiple forced choices trigger, only the highest-priority one's
  boost applies (others suppressed). Per §6.4 explicit "resolved by
  explicit priority: int." Matches the spec's intent that forced
  choices represent mutually exclusive personality directives.
- **Weighted Preferences additive across all matching constraints.**
  Per §6.4 Tier 3 explicit "Cumulative additive in single scoring pass."
- **Hard Filter severity locked at 1.0 even if user overrides.** Per
  §6.3 explicit "always 100% binary; the severity field is locked at
  100% by schema."
- **Empty-set fallback = Pass turn for both PCs and monsters.** Dodge
  primitive deferred; both default to Pass for v1. Matches monster
  fallback per spec; PC Dodge upgrade is a follow-on primitive PR.
- **Shipping 4 of 12 canonical constraints, not all 12.** One+ per type
  proves the framework; the remaining 8 are recipes in the same shape
  and can be added on demand without re-architecting.

**Open items carried forward:**
- [ ] 8 of 12 canonical constraints (recipes in §6.5 — same shape).
- [ ] User-authored custom predicates (post-MVP per spec).
- [ ] Dodge primitive (PCs Pass turn for v1, matching monster fallback).
- [ ] Surrendered-creature non-targetable behavioral system
  (`oath_protector` intersection).
- [ ] Positioning-dependent constraints (`frontline`, `library_protect`
  proximity).
- [ ] Parley action (Pacifist + Defensive Pacifist intersection).

---

## Session: 2026-05-25 — Retreat dial v1 (PR #11)

**Participants:** Phil, Claude

**Work done:**
- Implemented the Retreat dial — the last of the 4 dials. Step 1 of the
  decision pipeline (`check_retreat_trigger`) transitioned from no-op
  to active.
- New module `engine/ai/retreat.py`:
  - `RetreatBundle` dataclass + `_PRESET_BUNDLES` table for the 5
    presets (FtD / Resolute / Default / Cowardly / Pacifist) per spec
    §5.1 parameter columns.
  - `resolve_retreat_preset` — via behavior_profile chain.
  - `check_retreat` — the DMG p48 algorithm (dmg_ammann mode):
    mindless override → FtD short-circuit → trigger evaluation →
    Resolute compound logic → WIS save vs `in_combat_dc` → fail = flee.
  - Event log entries: `retreat_triggered`, `retreat_save`.
- `engine/core/pipeline.py`: `check_retreat_trigger` delegates to
  retreat.check_retreat. Accepts optional `rng` (passed by runner for
  reproducibility).
- `engine/core/runner.py`: `_run_actor_turn` passes `self.rng` into
  the retreat check; on flee, logs `fled` event with preset + triggers
  telemetry.
- 26 new tests in `tests/test_retreat.py`: preset bundle table
  correctness, mindless override (INT 2 zombie + mindless_aggressor
  archetype), FtD invariance, all 3 triggers (bloodied / ally-disparity
  / frightened), Resolute compound logic, WIS save mechanics (Resolute
  resists ~80%, Cowardly often flees 65%), preset resolution from
  archetype, event log shape, runner integration.
- 159/159 tests pass.

**Key decisions:**
- **Implemented `dmg_ammann` mode only for v1.** The Strict RAW and
  Behavior Engine sub-modes from §5.1 use the same machinery with
  parameter variants; defer to a future PR.
- **In-combat check only; pre-combat check deferred.** Pre-combat is
  more about encounter design than per-turn behavior; lower priority
  for v1.
- **Mindless override is INT ≤ 2 OR archetype `mindless_aggressor`.**
  Per spec "minimal undead/construct/INT≤2 → FtD override." Archetype
  short-circuit is the cleaner test (matches existing archetype tag
  on undead/oozes that don't show up via INT alone).
- **Resolute compound logic: must be Bloodied AND another trigger.**
  Per spec "Frightened-alone sufficient? No (must also be Bloodied)."
  All other presets accept any single trigger.
- **Retreat as default behavior for unscoped PCs.** Any actor without
  an explicit retreat dial gets the Default preset (50% Bloodied, 50%
  ally-disparity, Frightened-alone sufficient, DC 10). Existing
  fixtures now show this emergent behavior — PCs at low HP or after
  half their party falls roll WIS and may flee.

**Open items carried forward:**
- [ ] Parley action (needs language tracking + parley action + RP
  Constraint tie-in for Pacifist).
- [ ] Strict RAW mode + Behavior Engine mode.
- [ ] Pre-combat retreat check.
- [ ] SPC (self_preservation_coefficient) modulation of save DC.
- [ ] Flight-blocked / no-exit → FtD fallback (needs positioning).
- [ ] Surrendered-creature non-targetable behavioral system.

---

## Session: 2026-05-25 — Action Economy dial v1 (PR #10)

**Participants:** Phil, Claude

**Work done:**
- Implemented the Action Economy dial — the 4th of 4 dials. Step 7 of
  the decision pipeline (`apply_action_economy`) transitioned from
  no-op pass-through to active.
- New module `engine/ai/action_economy.py`:
  - Full 5-preset percentage table (Optimal / Skilled / Average /
    Casual / Reactive_only) × 5 knobs (main_optimality /
    signature_bonus / tactical_bonus / oa_reaction /
    sophisticated_reaction) per §5.4.
  - `resolve_action_economy_preset` — with `play_context: solo`
    tier-shift (one level down per spec).
  - `find_default_action` — first weapon_attack (skips multiattack).
  - `resolve_main_slot` — the heart of step 7: rolls vs
    main_optimality; on miss, swaps chosen action for default attack,
    keeping target. Adds `downgraded_from` marker for telemetry.
  - `should_use_bonus_action` — gates bonus slot per signature_bonus
    (is_signature=True) vs tactical_bonus (default).
  - `action_slot` / `is_signature` / `is_reactive_trigger` — tag
    readers with backward-compat defaults.
- `engine/core/pipeline.py`: `apply_action_economy` wired (accepts
  optional `rng`); `generate_candidates` is now slot-aware via a
  `slot` kwarg; `execute` marks the right slot used (main vs bonus).
- `engine/core/runner.py`: `_run_actor_turn` now runs Main slot then
  Bonus slot via `_run_slot` helper. Skips bonus if main killed the
  actor or terminated the encounter. Logs `bonus_action_skipped` +
  `action_downgraded` events for telemetry.
- New fixture `tests/fixtures/nimble_goblin_encounter.yaml`:
  Skilled-preset goblin with Scimitar (main) + Off-hand Jab signature
  bonus action. At seed 1, round 1 log shows BOTH a main scimitar
  attack AND a bonus off-hand jab from the goblin.
- 30 new tests in `tests/test_action_economy.py`: preset table
  correctness + monotonicity, resolve preset with play_context shift,
  default action lookup, slot + signature tag readers, main-slot
  optimality (Optimal never misses 20 seeds; Reactive_only misses
  often 200 trials; miss falls back to default + preserves target;
  no-distinct-default keeps chosen), bonus-slot gating (Optimal +
  signature always fires; Reactive_only + tactical never fires;
  Reactive_only + signature fires ~80%), slot-aware candidate
  generation, two runner integration tests.
- 133/133 tests pass.

**Key decisions:**
- **Reactions entirely deferred.** OAs need movement / positions;
  sophisticated reactions (Counterspell, Shield) need full reaction-
  trigger plumbing. The `is_reactive_trigger` tag + `oa_reaction` /
  `sophisticated_reaction` preset percentages are wired and ready,
  but no reaction candidates are generated yet.
- **Slot field on actions, defaulting to "action".** Backward-compat
  — existing actions without `slot` stay in the main pool. New
  `slot: "bonus_action"` opts into the bonus pool.
- **Main-slot miss = default attack, not second-best candidate.**
  Per spec "Attack for Main." Default = first `weapon_attack` in the
  action list (skips multiattack — multiattack is the optimal choice
  being downgraded away from).
- **Target preserved on miss.** The Targeting dial's pick stays;
  only the action changes. Cleaner than re-resolving targeting.
- **rng passed explicitly through pipeline.apply_action_economy.**
  Mirrors how primitives get the rng. Same seed → same downgrade
  sequence.

**Open items carried forward:**
- [ ] Reactions (OAs + sophisticated) — blocked on positioning.
- [ ] Combo recognition column from spec (qualitative).
- [ ] Sanity hint warnings (`ability_economy_mismatch`).
- [ ] `additional_action` primitive (Action Surge giving extra main slot).

---

## Session: 2026-05-25 — Engine capabilities checkpoint doc

**Participants:** Phil, Claude

**Work done:**
- Created `docs/engine-capabilities.md` — reader-facing capability
  checkpoint after 3 consecutive substantial AI PRs (#6 targeting, #7
  offensive eHP, #8 defensive eHP). Covers: what the AI can
  demonstrate today (behavioral, not module-listing); decision
  pipeline status per step; eHP framework coverage map; primitives
  coverage; worked behavioral examples (goblin bullies wounded,
  cleric heals dying ally, multiattack); test surface (103 tests
  across 4 modules); honest roadmap gap list.
- Refreshed `docs/CONTEXT.md` status table — added rows for
  Offensive eHP scoring v1 (#7) and Defensive eHP scoring v1 (#8);
  refreshed "Current phase" prose and "Next substantive steps" list.
- Updated `docs/SESSIONS.md` — added entries for the two missing
  PRs (#7 + #8) plus this checkpoint session.

**Key decisions:**
- **Engine-capabilities doc is reader-facing, not module-facing.**
  Lead with what the AI demonstrably does; module locations are
  pointer-table-only at the end. Keeps the doc useful for both Phil
  picking next priorities and future Claude sessions starting cold.
- **CONTEXT.md status table stays as the one-liner per work item;**
  the new capabilities doc handles depth. Avoids both files trying
  to be the same thing.
- **No strategic / pitch / Trusight content** in the docs. Engine
  repo is public; capabilities doc is engineering-progress only.

**Open items carried forward:**
- [ ] Pick next AI dial: Action Economy, Retreat, RP Constraints,
  positioning, or offensive buff for allies. (See
  `docs/engine-capabilities.md` §7 roadmap for ordered list.)

---

## Session: 2026-05-25 — Defensive eHP scoring v1 (PR #8)

**Participants:** Phil, Claude

**Work done:**
- Added the defensive side of the eHP framework. The AI now compares
  offensive AND defensive options on a single expected-HP scale.
- New module `engine/ai/defensive_ehp.py`:
  - `desperation_multiplier` — healing low-HP allies worth more
    (1.0 at full → 1.5 at 0 HP, linear below 50%).
  - `expected_healing` — parses heal-primitive pipelines (dice +
    fixed + modifier_source).
  - `defensive_ehp_healing` — capped at the ally's missing HP.
  - `estimate_dpr` — observable-proxy DPR estimate from a creature's
    weapon_attack actions + multiattack count. Mirrors threat_score
    discipline (no mental-stat introspection).
  - `extract_buff_effect` + `defensive_ehp_defensive_buff` — scores
    AC bonus + disadvantage-for-attacker shapes via `worst_enemy_DPR ×
    Δmiss × EXPECTED_BUFF_ROUNDS` (2.5 per framework).
  - `extract_control_intent` + `save_fail_probability` +
    `defensive_ehp_hard_control` — recognizes `forced_save →
    apply_condition` pipeline shape. Scores `enemy_DPR × p_fail ×
    EXPECTED_CONTROL_ROUNDS × denial_fraction`. HARD_CONTROL_CONDITIONS
    (paralyzed/stunned/petrified/unconscious/incapacitated) score
    full denial (1.0); PARTIAL_CONTROL_CONDITIONS (restrained/blinded/
    frightened/grappled/prone) score 0.2–0.5.
- `engine/ai/ehp_scoring.py`: `score_candidate` now dispatches by
  `action.type` to either offensive (this module) or defensive
  (defensive_ehp) scoring functions.
- `engine/core/pipeline.py`: `generate_candidates` extended to emit
  `(heal × ally)`, `(defensive_buff × ally)`, `(hard_control × enemy)`
  candidates alongside the existing `(weapon_attack × enemy)` +
  `(multiattack)` candidates.
- `engine/primitives.py`: `_heal` extended to support ally targets
  via `params.target='ally'` (uses `current_attack.target`);
  `_resolve_modifier` learns the remaining 4 ability mods
  (str/dex/wis/cha — was just con/int). Pre-existing bug fixed: heal
  `modifier_source` now resolves against the CASTER, not the heal
  target (mattered for self-heal it matched; for ally-heal it would
  have been wrong).
- `engine/cli.py`: `_build_actor` accepts optional `hp_current` per
  actor_spec so fixtures can spawn wounded allies for defensive-eHP
  demos (clamped to `[0, hp_max]`).
- New fixture `tests/fixtures/cleric_heals_ally_encounter.yaml`:
  2 goblins + dying fighter (1 HP) + cleric (mace + Cure Wounds).
  Headline behavior at seed 1: cleric's first action is `healed →
  fighter_dying +10`, NOT a mace attack. Fighter survives and
  contributes to PC victory.
- 34 new tests in `tests/test_defensive_ehp.py`: desperation math,
  healing eHP, DPR estimation, defensive buff, hard control,
  candidate generation, dispatch routing, behavioral tests
  (cleric-heals-dying-ally, AI-controls-high-DPR-enemy), and the
  full-encounter integration test.
- 103/103 tests pass total. 4/4 CLI fixtures clean.

**Key decisions:**
- **Split into separate `defensive_ehp.py` module**, not crammed
  into `ehp_scoring.py`. Clean separation makes it obvious which
  functions handle which side of the framework, and the dispatch
  point in `score_candidate` becomes the only entanglement.
- **Action types `heal` / `defensive_buff` / `hard_control` are
  the discriminator** for both candidate generation (target-side
  logic) and scoring (formula dispatch). Schema field, not pipeline
  inspection.
- **Healing capped at missing HP, not raw expected_healing.** The
  framework formula is fine for analysis but for selection we want
  the actual deliverable value. Same overkill discipline as
  offensive eHP.
- **DPR estimation uses observable proxies on templates** — same
  no-cheating discipline as `_threat_score`. Worst-attacker DPR is
  the stand-in for "expected ally damage taken next round" — a
  conservative approximation appropriate for v1.
- **Flat 2.5-round constant for buff/control duration.** Per
  framework's EXPECTED_ENCOUNTER_ROUNDS baseline. Future-rounds
  discounting + concentration-break risk modeling deferred.
- **Soft control / movement denial deferred** to the positioning
  PR. Defensible because no fixture needs it and the framework
  formula explicitly requires `denial_fraction` based on enemy
  position relative to targets.
- **Offensive buff for allies (Bless) deferred** — math symmetric
  to defensive buff, but needs cross-actor `attack_modifier` lookup
  at score-time. Smaller scope; left for a focused follow-on.

**Open items carried forward:**
- [ ] Soft control / movement denial (needs positions).
- [ ] Offensive buff for allies (Bless shape).
- [ ] Debuff on enemy saves.
- [ ] AoE multi-target optimization.
- [ ] Concentration management (auto CON saves on damage; AI choice
  of whether to break concentration to cast new spell).
- [ ] Spell slot opportunity cost (needs slot tracking on actors).
- [ ] Future-rounds discounting (flat 2.5 constant for now).
- [ ] `self_preservation_coefficient` scaling on defensive eHP.

---

## Session: 2026-05-25 — Offensive eHP scoring v1 (PR #7)

**Participants:** Phil, Claude

**Work done:**
- Replaced the `+10/+5` preset-preference scoring in
  `score_candidates_v1` with real offensive-eHP math.
- New module `engine/ai/ehp_scoring.py`:
  - `dice_mean`, `hit_probability`, `crit_probability` — pure math
    helpers; nat-1 always misses, nat-20 always hits.
  - `extract_attack_bonus` / `extract_damage_components` — pipeline
    inspection (only counts damage steps gated by no condition or
    by `attack_state == hit`; exotic conditional damage like sneak
    attack deferred).
  - `expected_damage_on_hit` — handles resistance / vulnerability /
    immunity by damage type; folds crit-given-hit probability into
    the dice portion only (modifier doesn't double under 5e rules).
  - `offensive_ehp_single_attack` — `hit_prob × dmg_on_hit`, capped
    at target HP (overkill cap on the upside).
  - `offensive_ehp_multiattack` — sums sub-attacks with a running
    overkill cap so later sub-attacks against a near-dead target
    don't inflate the score.
  - `aggression_coefficient` — per-archetype multiplier in [0.8, 1.5]
    (cowardly_skirmisher 0.8 → berserker_fanatic 1.5).
  - `score_candidate`, `best_action_against` — public API.
- `engine/ai/decision_layer.py`: `score_candidates_v1` rewired —
  score = `eHP × aggression + small preference bonuses`. The dial
  preferences become tie-breakers, not the primary signal.
- `engine/ai/ability_selection.py`: `_pick_tactical` now uses
  `best_action_against` to pick the highest-EV attack against the
  chosen target (was aliased to `default`). `_pick_optimal` aliases
  to tactical (joint optimization across defensive options deferred).
- 34 new tests in `tests/test_ehp_scoring.py`: pure-math helpers
  (dice, hit/crit prob with adv/dis edge cases), expected damage
  with resistance/vuln/immunity, eHP integration with overkill cap,
  multiattack sums, aggression scaling, tactical preset picks
  highest-EV attack, and the headline behavioral test that the AI
  scores Blinded targets higher than equivalent non-blinded
  targets without any special-cased "prefer Blinded" code.
- 69/69 tests pass total (was 35; +34 new).

**Key decisions:**
- **eHP carries the signal; preset preferences become tie-breakers.**
  `TARGET_PREFERENCE_BONUS = 2.0` and `ACTION_PREFERENCE_BONUS = 1.0`
  — small enough not to overpower real eHP differences, large enough
  to steer when eHP is close. This means archetypes stay meaningful
  even though eHP math now does the heavy lifting.
- **Overkill caps are mandatory.** A 50-damage swing at a 1-HP
  target should score 1 eHP, not 50. Multiattack uses a *running*
  cap across sub-attacks to avoid inflating the score after the
  target's hypothetical HP is "spent."
- **Crit folds into damage-on-hit, not into hit probability.** The
  math: `mean_damage_on_hit = dice × (1 + p_crit_given_hit) + modifier`.
  This is cleaner than scoring crit chance separately.
- **AI exploits conditions via the unified modifier registry, no
  special code.** Blinded target → `query_attack_modifiers` returns
  advantage → `hit_probability` uses `1 - (1-p)^2` formula → eHP
  rises → AI picks the Blinded target. Same path will work for
  Restrained / Frightened / Prone when those modifiers attach.
- **`tactical` preset works for real now;** `optimal` aliases to
  tactical for v1. Real `optimal` will compare offensive vs defensive
  options jointly (needs the defensive eHP layer — next PR).
- **No spell slot opportunity cost yet** — no casters in fixtures.
  Deferred to its own PR with proper slot tracking on actors.

**Open items carried forward:**
- [ ] Defensive eHP (heal / buff / control / debuff formulas).
- [ ] Spell slot opportunity cost.
- [ ] Future-rounds discounting + AoE multi-target optimization.
- [ ] `self_preservation_coefficient` / `pack_tactics_bonus`.
- [ ] Joint (target × ability) optimization for `optimal` preset
  (needs defensive eHP first).

---

## Session: 2026-05-26 — AI decision layer v1 (Targeting dial fully implemented)

**Participants:** Phil, Claude

**Work done:**
- Created `engine/ai/` module — the AI decision layer's home. Replaces the skeleton "attack nearest enemy" with dial-driven archetype-aware targeting via the `score_candidates()` socket that was waiting in `pipeline.py` from the skeleton PR.
- `engine/ai/targeting.py` — all 5 targeting presets per `pillars-reconciliation.md` §5.3:
  - `closest_enemy` — first in turn order (positions deferred to a future PR)
  - `weakest_target` — lowest current HP ("bullies the wounded"; cowardly skirmisher default)
  - `most_dangerous` — highest observable threat score (CR × 10 + max attack bonus × 2 + caster signal +5)
  - `caster_first` — prioritize spellcasters; falls back to most_dangerous if none visible
  - `optimal_ehp` — degrades to caster_first behavior (full eHP joint optimization deferred)
  - **Universal finish-off rule** — INT ≥ 4 creatures deviate from any preset to attack near-death targets (HP_remaining < 15%); mindless creatures (INT 1-3) don't have the awareness.
- `engine/ai/ability_selection.py` — minimal v1 implementation:
  - `default` preset prefers multiattack > weapon_attack > first listed
  - `mindless` always picks first action
  - `instinctive` prefers signature-flagged actions
  - `tactical` and `optimal` degrade to `default` (full eHP scoring deferred)
- `engine/ai/behavior_profile.py` — preset resolution with archetype defaults sourced from `pillars-reconciliation.md` §3:
  - Explicit preset on `behavior_profile.presets` wins
  - Falls back to archetype default (cowardly_skirmisher → weakest_target; apex_predator → caster_first; pack_hunter → most_dangerous; berserker_fanatic → most_dangerous; mindless_aggressor → closest_enemy)
  - Hard-coded fallback (closest_enemy) when neither is present
- `engine/ai/decision_layer.py` — public orchestration:
  - `score_candidates_v1()` — the score_candidates socket implementation. Resolves the actor's dials, asks targeting + ability_selection for their preferred picks, scores candidates matching those picks higher (+10 for preferred target, +5 for preferred action).
  - `select_action_v1()` — alternative API that picks directly via dial-driven AI (useful when generate_candidates is too restrictive).
- Wired into `engine/core/pipeline.py`:
  - `score_candidates()` now delegates to `engine.ai.decision_layer.score_candidates_v1` (lazy import to avoid circular dependency at module load).
  - `generate_candidates()` expanded to include multiattack actions (previously only weapon_attack).
- 19 new tests in `tests/test_ai_v1.py`:
  - Unit tests per targeting preset (closest_enemy, weakest_target with dead-enemy handling, most_dangerous by attack-bonus and CR, caster_first with martial fallback, finish-off rule for INT 4+ and skip for INT 1-3)
  - Behavior profile resolution (explicit preset > archetype default > fallback; multiple archetype verifications)
  - Ability selection (default prefers multiattack, mindless picks first, instinctive picks signature)
  - Integration: Goblin (cowardly_skirmisher) attacks wounded fighter (5 HP) before healthy fighter (28 HP)
- New test fixture `tests/fixtures/two_pc_encounter.yaml` — Goblin + wounded fighter + healthy fighter, with goblin acting first.
- All 35 tests pass total (4 smoke + 12 primitives_v1 + 19 ai_v1).

**Key decisions:**
- **Archetype defaults are tabulated in `behavior_profile.py`** — not embedded in content YAML. A creature can specify just an archetype string and inherit sensible dial defaults; or override individual dials explicitly. Matches pillars-reconciliation §3 / §5 design.
- **Universal finish-off rule is applied across all presets**, not as a separate preset. Per §5.3 it's a modifier "applied across all non-mindless presets". The skeleton-grade implementation gates on INT ≥ 4.
- **Threat score uses observable proxies** — no "cheating" via mental stat introspection. CR is a published creature attribute; attack bonus is visible from past actions; spellcaster status is detected from template structure (presence of spellcasting blocks / actions named "Spellcasting" / etc.).
- **`optimal_ehp` degrades to `caster_first` for v1**, not raises NotImplementedError. Graceful degradation lets content using the optimal preset still function until eHP scoring lands. Documented as a known limitation.
- **Ability Selection is minimal v1**. The multiattack > weapon_attack > first priority handles the common cases; eHP-scored ability selection (where Tactical preset picks based on expected damage × hit probability, accounting for resistance / target HP) is deferred to the eHP scoring PR.
- **`score_candidates()` delegation via lazy import** — `engine.ai.decision_layer` imports from `engine.core.state`, which is itself imported by `engine.core.pipeline`. Lazy import inside the function body avoids the circular dependency without restructuring.

**Open items carried forward:**
- [ ] Full eHP scoring + behavioral coefficients in `score_candidates_v1`. Currently scoring is +10/+5/+0 for matching preferences; real implementation weighs eHP value × weighted preferences + forced choice weights + behavioral coefficients (aggression / self-preservation from archetype).
- [ ] Action Economy dial (signature_bonus / tactical_bonus / OA / sophisticated reaction tiering per §5.4 + Phil's per-slot stochastic model).
- [ ] Retreat dial (DMG p48 algorithm + 3 modes + 5 presets per §5.1).
- [ ] RP Constraints (Hard Filter / Forced Choice / Weighted Preference per §6).
- [ ] Full 3-level profile inheritance (archetype → faction → instance) + runtime override layer (Frightened / Dominate / Confusion) per §4.4.
- [ ] Positioning / movement / reachability filters. Currently all creatures at (0,0); `closest_enemy` collapses to turn order.
- [ ] Tactical ability selection with eHP scoring (highest expected damage attack against highest-eHP-contribution target).
- [ ] AI should EXPLOIT conditions — attacking Blinded targets preferentially, avoiding attacking through disadvantage, etc. Currently conditions affect resolution but not selection. Requires the eHP scoring layer.

---

## Session: 2026-05-26 — Primitives v1 (Q5 unified modifiers + spell mechanics + multiattack)

**Participants:** Phil, Claude

**Work done:**
- Implemented the Q5 unified modifier system end-to-end. The keystone change: **conditions applied to an actor now actually affect gameplay** (Blinded gives attackers advantage; Paralyzed auto-fails STR/DEX saves; etc.).
- New module `engine/core/modifiers.py` — active-modifier registry evaluator. Queries unified `attack_modifier` / `save_modifier` / `d20_test_modifier` / `crit_modifier` / `crit_threshold_modifier` entries with `when`-clause filtering and aggregation per D&D 5e rules (advantage + disadvantage cancel; auto-fail trumps; etc.). Skeleton-grade `when`-clause evaluator (atoms: target_is_self, attacker_is_self, attack_hits, position-based defaulted to TRUE since (0,0) coords throughout).
- Modifier lifetime management uniform across sources: `per_single_attack` clears after attack; `until_actor_next_turn_start` clears at turn_start; `until_condition_ends` clears when source condition is removed via `remove_condition()`.
- `apply_condition` now instantiates the condition's effect primitives onto target's `active_modifiers` (with subordinate-condition inheritance — Paralyzed → Incapacitated; Unconscious → Incapacitated + Prone). `_instantiate_condition_effects` helper handles the transitive application.
- `remove_condition` cleans up modifiers (including subordinate-inheritance chain) by source.
- `forced_save` primitive — target makes save vs DC; resolves on_fail / on_success sub-primitive arrays. DC sources: explicit `dc:` int, `dc_source: caster_spell_save_dc` (computes 8 + INT mod + PB), `fixed:N`.
- `recurring_save` primitive — registers an entry in `state.recurring_saves`; runner resolves at the target's `turn_end` boundary. On success: `remove_condition` ends the source condition.
- `multiattack` — special-cased in `pipeline.execute()`. Actions with `type: multiattack` loop N sub-attacks (referenced by sub_action_ids), each independently picks a target.
- 12 new integration tests in `tests/test_primitives_v1.py`:
  - Blinded target gives attacker advantage
  - Blinded creature's own attacks have disadvantage
  - Paralyzed auto-fails STR save / DEX save / does NOT auto-fail WIS save
  - Paralyzed inherits Incapacitated (subordinate condition appears in applied_conditions)
  - Crit threshold modifier lowers crit range (Champion Improved Critical → 19+)
  - Multiattack runs N sub-attacks per turn (verified via attacks-per-round in event log)
  - forced_save with high DC fails and applies on_fail sub-primitive (Frightened)
  - recurring_save registers entry and is resolvable at turn_end
  - remove_condition cleans up active_modifiers (Blinded)
  - remove_condition cleans up inherited subordinate modifiers (Paralyzed → Incapacitated chain)
- Test fixture `tests/fixtures/test_multiattack_encounter.yaml` — custom Test Dual Wielder creature with type=multiattack action.
- All 16 tests pass (4 smoke + 12 v1).

**Key decisions:**
- **State carries content registry.** `CombatState` gets a `content_registry` field (optional). When `apply_condition` fires, it looks up the condition definition via registry and instantiates effects. If no registry, condition is a marker only (backward-compatible).
- **Modifier lifetime uniformity.** The Q5 architectural commitment cashed out: one `attack_modifier` primitive handles Blinded, Shield, Bless, Bardic Inspiration via the lifetime parameter. The engine queries one registry; aggregates uniformly; doesn't care what type of source added the modifier.
- **`when`-clause evaluator is skeleton-grade.** Handles a small vocabulary (target_is_self, attacker_is_self, position checks defaulted to TRUE). Real engine needs a proper expression evaluator. Documented as a known limitation.
- **`recurring_save` resolved by runner**, not by event subscribers. The runner walks `state.recurring_saves` at each actor's turn_end. Simpler than coupling primitives to engine event flow.
- **Multiattack special-cased in pipeline.execute**, not as a true primitive. The `multiattack` primitive itself is a marker; the actual loop is in `_execute_multiattack`. Pragmatic — the decision pipeline picks ONE action per turn; multiattack lets that action expand into N sub-attacks.
- **`_PRIMITIVE_HANDLERS` lookup populated at module import**, not lazily on first registry build. Allows direct primitive calls (in tests + ad-hoc invocation) to find sub-primitives without going through PrimitiveRegistry.

**Open items carried forward:**
- [ ] Real AI decision layer — replace skeleton's "attack nearest enemy" with 5-step Ammann+eHP hybrid per `pillars-reconciliation.md` §7. Conditions now affect gameplay but AI doesn't EXPLOIT advantage / avoid disadvantage. The score_candidates() socket is ready.
- [ ] Movement / positioning / line-of-sight / area-of-effect geometry. Skeleton still uses (0,0); position-based `when` clauses default to TRUE.
- [ ] Remaining ~30 stubbed primitives. Next-highest-value: `speed_modifier` (movement effects from conditions), `damage_modifier` (resistance grants beyond template-level), `additional_action` (Action Surge), `persistent_aura` + `triggered_save` (Spirit Guardians end-to-end), `slot_recovery_partial` (Arcane Recovery).
- [ ] Proper `when`-clause expression evaluator (Tier 1 dependency for richer conditions).
- [ ] Concentration mechanics — auto CON save on damage when caster has active concentration spell.
- [ ] PC schema (proper one, replacing inline-monster-template hack in smoke fixture).
- [ ] Phase 2 Foundry bridge — when stage 2 timing is right.

---

## Session: 2026-05-25 — Engine skeleton (Phase 1 v0) committed

**Participants:** Phil, Claude

**Work done:**
- Confirmed alignment on Foundry-as-eventual-front-end commitment (per CONTEXT Phase 2 + spine doc's "Foundry = host, never fork" posture). Sharpened the engineering implication: engine designed library-first so Foundry bridge later doesn't force refactor.
- Chose Path A: CLI for internal research grading first; engine library is the dependency a future Foundry JS bridge will consume.
- Built the engine skeleton package `engine/`:
  - `engine/core/state.py` — Actor, Encounter, CombatState dataclasses. Fully serializable state — Foundry bridge can ship as JSON.
  - `engine/core/events.py` — EventBus with the canonical event vocabulary (40+ events from the schema PR's pipeline definitions).
  - `engine/core/pipeline.py` — the 8-step decision pipeline from `pillars-reconciliation.md` §7. Skeleton AI ("attack nearest enemy with first available attack") with real implementation slot for the 5-step Ammann+eHP hybrid.
  - `engine/core/runner.py` — EncounterRunner: rolls initiative, ticks turns, checks termination, MAX_ROUNDS safety cap.
  - `engine/primitives.py` — PrimitiveRegistry. 5 primitives implemented (attack_roll, damage, apply_condition, heal, granted_action); ~40 stubbed with clear NotImplementedError.
  - `engine/loader.py` — YAML loader + lite JSON Schema validation.
  - `engine/reports.py` — EncounterReport (JSON + human-readable summary).
  - `engine/cli.py` — `python -m engine encounter <yaml>` + `validate` subcommand.
  - `engine/README.md` — install, usage, module layout, gaps.
- Wrote `tests/test_smoke.py` (stdlib unittest, no extra deps) — 4 tests: content loads, encounter terminates, Fighter wins majority of 20 trials, JSON report serializable. All pass.
- Wrote `tests/fixtures/smoke_encounter.yaml` — Fighter L3 (inline template; PC schema is post-MVP) vs the `m_goblin_warrior` from the schema PR.
- `pyproject.toml` for package metadata; deps: PyYAML, jsonschema. Optional dev dep: pytest.

**Key decisions:**
- **Library-first architecture.** Engine is a Python package; CLI is one consumer; Foundry bridge is a future consumer. Same public API for both.
- **Fully serializable state.** Every state object is plain dicts/dataclasses/primitives. Guarantees JSON serialization for Foundry bridge, deterministic replay for testing, observation mode for external drivers.
- **Two operating modes designed-in.** Sim mode (engine drives via decision pipeline) and observation mode (external driver calls `bus.emit()`; engine records but doesn't decide). Both enabled by EventBus design; Foundry bridge will use observation mode plus translation at the bridge layer.
- **Stub-driven scope discipline.** 5 critical primitives implemented; ~40 stubbed with `NotImplementedError`. Encounter runs that need stubbed primitives fail loudly with a clear message — incremental implementation unlocks more content.
- **Skeleton AI is trivial; pipeline shape is real.** The 8-step decision pipeline from `pillars-reconciliation.md` §7 has real function stubs (resolve_effective_profile, check_retreat_trigger, generate_candidates, apply_hard_filters, apply_forced_choices, score_candidates, select_max, apply_action_economy, execute). The real Ammann+eHP scoring layer slots into `score_candidates` without architectural change.
- **Verified end-to-end.** Smoke test: Fighter L3 (AC 18, longsword +5 / 1d8+3) vs Goblin Warrior (AC 15, scimitar +4 / 1d6+2) runs to termination across 20 seeded trials; Fighter wins majority as expected by stat-block analysis.

**Open items carried forward:**
- [ ] Implement more primitives — highest-value next: the unified modifier primitives (attack_modifier, save_modifier, speed_modifier per Q5), forced_save (unblocks save-based spells / abilities), multiattack (unblocks higher-CR monsters).
- [ ] Replace skeleton AI with full 5-step Ammann+eHP hybrid decision layer. Will add `engine/ai/decision_layer.py` + `engine/ai/behavior_profile.py` + `engine/ai/rule_bundles.py`.
- [ ] Movement / positioning / line-of-sight / area-of-effect geometry. Skeleton uses (0,0) for everyone.
- [ ] Concentration mechanics — engine auto-triggers CON saves on damage when caster has active concentration spell.
- [ ] Conditions consulted by decision layer — currently applied to actor but their effects don't yet bias decisions.
- [ ] BehaviorProfile dial resolution at runtime — schema models them; engine doesn't yet consult.
- [ ] PC schema (proper one, not inline template hack used in smoke fixture).
- [ ] Monte Carlo loop with statistical aggregation (Phase 3 work).
- [ ] Phase 2 Foundry bridge — when stage 2 timing is right.

---

## Session: 2026-05-25 — Schema design v1 committed

**Participants:** Phil, Claude

**Work done:**
- Sampled SRD CC v5.2.1 across content types: Fighter class + Champion subclass (p47-49), monster stat block format (p254-257), Goblin Warrior (p290), three spells with distinct patterns (Fireball p131, Hold Person p141, Spirit Guardians p164-165), Wizard class + Evoker subclass (p77-82), and all 15 conditions from the Rules Glossary (p177-191).
- Iteratively designed schemas dial-by-dial: class, subclass, feature, monster, spell, condition. Each iteration: read SRD example → draft schema → react/refine → confirm/lock.
- Identified the **unified ability pattern** (Q5 from conditions design): a weapon attack, spell, class feature, monster action, magic item activation are all instances of one schema with different casting semantics. Same primitive library, same execution pipeline.
- Locked the **attack pipeline event vocabulary** (11 events: attack_declared → attack_complete) and the **spell pipeline events** (spell_cast, spell_resolve, spell_end, area triggers, target turn end).
- Locked the **modifier-with-lifetime pattern** — one `attack_modifier` primitive handles Blinded, Shield, Bless, etc. by varying the lifetime parameter, not by having separate primitives per source.
- Locked the **conditions architecture**: definition vs application; absolute vs source_referencing scope; subordinate condition inheritance with reference counting; Petrified `state_transition` as a sui generis primitive; 15 SRD conditions verified directly from PDF including the leveled Exhaustion model.
- Locked the **spellcasting class block**: ability + save_dc_formula + attack_mod_formula + focus_types + preparation_model enum (prepared_from_known_list / spells_known_fixed / prepared_from_class_list / pact_magic) + slots_progression (full / half / third / pact, engine-canonical tables) + ritual_casting style.
- Wrote `docs/architecture/schema-design.md` as the binding architectural commitment for content schema. Companion to pillars-reconciliation.md (which governs the AI behavior layer).
- Created `/schema/` directory structure: definitions/ (6 JSON Schemas + common shared sub-schemas), content/ (sample YAML per type), worksheets/ (gitignored — clean-room audit trail).
- Authored v1 sample content: c_fighter, c_wizard, sc_champion, sc_evoker, 9 features, m_goblin_warrior, sp_fireball, sp_hold_person, sp_spirit_guardians, all 15 conditions.
- gitignore updated to exclude `schema/worksheets/*` (clean-room audit trail kept private).

**Key decisions:**
- **YAML authoring + JSON Schema validation.** Content in YAML for readability/comments; JSON Schema in /schema/definitions/ for tooling.
- **Schema has no rules-text fields by construction.** Clean-room legal enforcement is structural — there is nowhere in the shipped schema to put copied WotC prose.
- **Spell lists are auto-derived views.** Each spell carries `classes:`; the Wizard spell list is a query, not a separate file. No duplication, no drift.
- **Slot progressions are engine-canonical.** Four standard tables (full / half / third / pact) live as engine constants; classes reference by name. Eliminates 12-class duplication.
- **`source:` field on every entry.** srd_5.2.1 / phb_2024 / user_authored / homebrew. Documentation tag with no licensing implication.
- **File naming convention:** type-prefixed snake_case (c_*, sc_*, f_*, m_*, sp_*, co_*).
- **Primitive library lives in `/schema/primitives/`** but the Python handler implementations are deferred to engine skeleton work. The schema commits today specify what primitives exist; the engine PR implements them.

**Open items carried forward:**
- [ ] Engine skeleton: event bus, handler interface, contract enforcement, reaction-cascade termination guard, primitive library implementation (Python).
- [ ] Schema validation tooling: YAML loader + JSON Schema validator for content files.
- [ ] Content expansion: ~11 remaining classes, ~23 remaining subclasses, ~300 monsters, ~300 spells, equipment / weapons with Mastery (2024 rules), magic items, backgrounds, species, feats. Each is parallel iterative work, no architectural new design.
- [ ] Half caster (Paladin), pact magic (Warlock), prepared_from_class_list (Cleric, Druid) sampling to validate the spellcasting block against all four preparation models.
- [ ] Equipment schema sampling — weapons with Mastery properties (2024 rules), armor with stealth disadvantage, etc.

---

## Session: 2026-05-25 — `pillars-reconciliation.md` drafted + cadre red-team amendments

**Participants:** Phil, Claude, plus AI cadre (Gemini, ChatGPT, Perplexity) for red-team review

**Work done:**
- Dial-by-dial design conversation: Retreat, Ability Selection, Targeting, Action Economy (each ~5 named presets as parameter bundles; same shape across all four).
- Designed the three execution modes (Strict RAW / Rules + Behavior + eHP / Behavior Engine) with explicit UX treatment to defeat the gradient-bias trap (comparison strip, use-case-framed wizard, inline warning, default selection).
- Resolved open question #3 (RP Constraints as separate filter/scoring system, 3 categories, library).
- Resolved open question #4 (per-type + faction + per-instance three-level inheritance; `reason:` split from `suppress_hints:`).
- Resolved open question #5 (Sanity Hints reframe — not "validation"; honest about being hints not correctness).
- **Cadre red-team round** on the three open-question resolutions (NOT the four dials — those had been iterated heavily with Phil's DM input). Standardized adversarial prompt; three independent runs. Six 3/3 convergent CRITICAL findings:
  1. Severity-as-probability destroys Monte Carlo convergence
  2. Constraint conflict resolution underspecified (deadlocks possible)
  3. Pipeline ordering mathematically incoherent (weighted prefs post-hoc)
  4. Validation system structurally insufficient (small library + suppression bypass)
  5. `reason:` field overloaded as global mute
  6. Mode-aware validation desync
- Six amendments adopted; one additional (three-level inheritance / faction layer) adopted from a 2/3 convergent finding.
- `docs/foundations/pillars-reconciliation.md` drafted incorporating all amendments. Replaces the 2026-03-30 stub.
- **Same-day reconsideration: polymorph + runtime override layer promoted from follow-on to fully specified.** Initial categorization deferred them as "architect-for, defer-detail" but the cadre had actually flagged them as CRITICAL (Gemini explicitly; ChatGPT and Perplexity on the polymorph variant). Frequency check (Druid Wild Shape as a core class identity feature available from level 2; Polymorph/Shapechange/True Polymorph as common combat tools across levels; the runtime-override class of conditions — Frightened/Dominate/Confusion — appearing constantly in real play) confirmed these are core gameplay, not edge cases. Promoted to full specification at §4.2 (Form Transition Model with `retains_mind` flag covering the Polymorph-vs-Shapechange mental-stat distinction) and §4.3 (Runtime Overrides with four primitive override types). Per-effect implementation specs (Wild Shape HP rules, Frightened save cadence, etc.) remain follow-on — they live in spells/conditions docs, not pillars-reconciliation.

**Key decisions:**
- The pillars are not in opposition; they answer different questions at different layers. Resolution is a multi-axis dial system, not per-conflict binary policy.
- Unified actor-behavior model — monsters AND PCs share the same BehaviorProfile.
- Severity is a continuous score weight in the eHP pipeline, NOT a probability — preserves Monte Carlo determinism.
- Decision pipeline follows the Utility AI single-scoring-stage pattern (all considerations baked into one coherent scoring pass; no post-hoc patching).
- Constraint composition has explicit priority tiers (Hard Filter > Forced Choice > Weighted Preference) with guaranteed-legal fallback (Dodge for PC, Pass for monster) to prevent engine deadlock.
- Three-level inheritance: archetype → faction → instance.
- `reason:` and `suppress_hints:` are separate fields with separate semantics (documentation vs control). ESLint precedent for per-rule suppression.
- "Sanity Hints" framing (not "Validation") with explicit "absence of hint ≠ correctness" disclaimer.
- Hint rules cross-reference dial choices against actual stat-block capabilities (statblock-aware hints).
- Mode-relevance lives in hint text, not in firing-vs-not-firing logic — same configuration produces same hints across all modes.
- Cadre red-team established as a recurring discipline for substantive architectural design (this is the second productive run; May 17 validation-oracle was the first).

**Follow-on items carried forward (architecturally reserved; not MVP):**
- [ ] Runtime override layer for conditions (Frightened, Dominate Person, Confusion) — schema slot reserved in `BehaviorProfile.runtime_override`.
- [ ] Polymorph / transformation as state transition (current_form vs underlying_identity pair).
- [ ] Phase-shift constraints (Bloodied → drop pacifism; mythic phases).
- [ ] Temporal memory / stateful constraints (track "already healed this turn").
- [ ] Dynamic / post-hoc validation (observation-based hints after Monte Carlo runs).
- [ ] Alternative archetype "style" baselines (Ammann is one author's interpretation).
- [ ] Faction profile library expansion (ship initial small set; grow organically).
- [ ] Per-creature default `BehaviorProfile` assignments for the 300+ creatures Ammann covered (not yet ported into our doc; only the ~6 archetypes are encoded).
- [ ] Schema design for subclass / spell / feat / monster definitions (originally next-after-pillars; now next-after-pillars).
- [ ] 5e API → schema transform pipeline.

---

## Session: 2026-05-24 — Un-stalling + Hybrid monetization + asset inventory

**Participants:** Phil, Claude

**Work done:**
- Discovered an unrelated YT-transcript POC (in sibling `dnd-trends-index` repo) had produced 224 Treantmonk transcripts already entity-extracted (`~/yt_poc_data/treantmonk/`), including the methodology video `nLXbEFurCU4` that sourced the `pc-dpr-baselines.md` engine.
- Inventoried pre-existing content artifacts across both repos and BigQuery (work previously done via Antigravity):
  - `dnd-trends/1_raw/` — index dump from `dnd5eapi.co` (334 monsters, 319 spells, 407 features, 237 equipment, 362 magic items, 12 classes, 9 races, etc.). **Names + URLs only, not full mechanical content** — the actual stat-block/feature/spell text still has to be fetched from the API.
  - `dnd-trends/game_registry/` — Trusight-side metadata SQL (`01_schema.sql` + `02_populate.sql` + `03_verify.sql`); 48-subclass registry populated in BigQuery 2026-05-19. Deliberately facts-only by legal-firewall design (no mechanical text).
  - `dnd-trends/cloud_functions/monster_classifier/` — Trusight-side tagger.
  - This repo: **zero content files** confirmed. All current work is the 8 docs in `docs/`.
- Confirmed `pillars-reconciliation.md` (1.5KB stub) is the genuine blocker per this repo's own CONTEXT line 71 — separate from CONTEXT/SESSIONS being stale.
- CONTEXT.md / SESSIONS.md refresh (this commit) — propagates the May architecture-spine work into this repo per the spine doc's §7 propagation TODO.

**Key decisions:**
- **Hybrid monetization (Stage 3+).** Sim ships SRD content bundled (CC-BY, free to redistribute with attribution). Non-SRD content arrives via user-supplied port (typed-in via schema-validated form, or imported from where the user already licensed it — DDB/Roll20 export). Sim **never** ships non-SRD content. Rejected: DDB/Roll20-style licensed-reseller model (requires a WotC license).
- Treantmonk DPR per-level numbers re-categorized from "source data" to "validation reference data" — the 7-step methodology encoded in `pc-dpr-baselines.md` (lines 44–218) is sufficient for the sim to compute DPR for any new build. Treantmonk's 5 verified per-level tables (Fighter ×3, Zealot Barb, Berserker Barb) serve as cross-validation reference. More tables nice-to-have, not blocking.
- `dnd5eapi.co` is the canonical ingestion path for bundled SRD content. Pipeline: fetch → clean-room transform into Tier-1/Tier-2 schema → store as bundled assets in this repo.
- Project name shift in all docs: `Arcane Analytics` → `Trusight`.

**Open items carried forward:**
- [ ] Draft `pillars-reconciliation.md` — needs Phil's policy input on Math-Wins / Behavior-Wins / Weighted-Blend per conflict class (targeting, retreat, ability selection, action economy). NEXT substantive design step.
- [ ] Design schema for subclass / spell / feat / monster definitions (after pillars-reconciliation lands). Two-tier: declarative effect-primitives + custom-handler escape hatch (MtG card-scripting pattern). Each effect carries the §Config read/write/event/scope contract.
- [ ] Build 5e API → schema transform pipeline.
- [ ] Extract spellcaster DPR methodology from `nLXbEFurCU4` transcript when engine reaches spellcaster scoring (currently encoded methodology is martial single-target only).

---

## Session: 2026-05-18 — Legal posture resolved + `game_registry` built (sibling repo)

**Participants:** Phil, Claude

**Work done (cross-project, primarily in `dnd-trends-index`):**
- Resolved the legal posture for sim mechanics + public eHP reports. Settled findings:
  - **Names are NOT the control. Clean-room + sourcing are.** Anonymizing real names solves a non-problem and actively costs registry/reception join-ability. Keep real names internally; private real-name↔id map.
  - **Publishing comparative eHP reports of named subclasses is legitimate and precedented** — decade of Treantmonk / Tabletop Builds / RPGBOT doing exactly this commercially, by name, untouched by WotC. Public distribution doesn't remove the activity's legitimacy; it re-ranks the controls (trademark goes from dormant to live → nominative-fair-use posture + disclaimer required).
  - **The new risk is strategic, not legal: pitch tone.** Every public report frames as neutral measurement, never "WotC got this wrong."
- `game_registry.subclasses` BigQuery table built and populated with 48 PHB-2024 subclasses (4 per class × 12 classes; all `is_current_canonical=TRUE`; all `is_srd=FALSE` deliberately under-claiming).
- Diagnostic JOIN proven: 48/48 subclasses match `concept_library`; 0/48 match `reddit_reception_proxy` (the informative result — empirically confirms subclass-level reception tagging is genuinely net-new).
- `vocabulary_lexicon` companion table established as 4th firewall layer (vocabulary). Makes the internal-vs-deliverable vocabulary discipline checkable, not advisory.

**Key decisions:**
- Combat-sim mechanical content (full stat blocks) stays separate from Trusight metadata (facts/JOIN keys): different copyright profiles → different stores.
- `is_srd=FALSE` for all 48 PHB-2024 subclasses (conservative; SRD-5.2 coverage unverified; safest stance with WotC as the prospect).
- For-profit pivot is the explicit escalate-to-real-counsel trigger.

**Open items carried forward:**
- [ ] Propagate the May architecture-spine work into this repo's CONTEXT/SESSIONS (DONE: 2026-05-24 session).
- [ ] Sharpen the "SRD/Open5e only" wording so a future session cannot misread it as a content cap on the sim. (DONE: spine doc 2026-05-20.)

---

## Session: 2026-05-17 — Architecture spine established (Trusight ↔ combat-sim)

**Participants:** Phil, Claude

**Work done (cross-project strategic design; stored in project memory as `project_rules_substrate_architecture.md`):**
- Established the load-bearing architectural spine governing the cross-project relationship.
- Codified the **epistemic-inversion principle** (3 layers: config / execution / measurement). Sim *enumerates-then-selects*; Trusight *measures-never-selects*. The Wish boundary (non-enumerable rules) proves the principle — what breaks the sim is what maximally feeds Trusight.
- Codified the **5-component Trusight feature-intelligence decomposition** (registry / reception tags / lore-resonance / structural taxonomy / translation patterns).
- Codified the **dual-axis through-line** (every Trusight surface is dual-axis; single metric is always the trap).
- Codified the **§Config locked design conditions** (5 cadre-confirmed conditions for engine implementation — see CONTEXT § §Config Locked Design Conditions).
- Codified the **validation-oracle relationship** (§5, 5 conditions — see CONTEXT § Validation-Oracle Rules). Corrected an earlier framing that "summary-only firewall = safe"; coarse verdicts ARE an optimization gradient, so summary signals are necessary-but-radically-insufficient.
- Codified the **11 eHP limitations** with the dissolution analysis: ~7 of 11 dissolve under full turn-by-turn simulation; residual ~4 are inherent conditionality + scope. Strengthens the architecture — gives §5 condition 1 (distributions-with-conditions, never scalars) and §4 (dual-axis) their real foundation.

**Key decisions (binding on this repo):**
- **Direction B is SEVERED.** Community-prevalence → sim-default-ruling channel is forbidden. The sim stays RAW-anchored, period.
- **eHP is a disclosed input axis, never a gate.** No binary balanced/not-balanced verdicts.
- **No automated generate→test loop, ever.** Architectural prohibition.
- **Rule Bundles** (`RAW` / `Common-Table` / `Strict`) are the UX surface — never hundreds of raw toggles.
- All `pillars-reconciliation.md` work and all subsequent engine code must reference the §Config conditions.

**Open items carried forward:**
- [ ] Reconcile this repo's CONTEXT/SESSIONS frozen at 2026-03-30 + pillars-reconciliation stub (DONE for CONTEXT/SESSIONS: 2026-05-24; pillars-reconciliation still open as next step).
- [ ] Add the firewall rule + a pointer to the spine doc into this CONTEXT.md (DONE: 2026-05-24).
- [ ] Record the roadmap re-prioritization rationale (Phase 3 up, validation-oracle ROI driven) (DONE: 2026-05-24 — see CONTEXT § Build Phases).

---

## Session: 2026-04-01 — DPR data work (martial classes)

**Participants:** Phil, Claude

**Work done:**
- Produced `treantmonk-damage-rankings.md` from Treantmonk's videos 19–23: scoring formula verified (`T1×1 + T2×3 + T3×2 + T4×1`), career scores + per-tier breakdowns for all 39 builds, 2024 baseline confirmed = Warlock Base Blade Pact Greatsword (C tier all four tiers, career 196).
- Produced `pc-dpr-baselines.md` methodology section from video 1 ("How to Calculate Damage in D&D 2024"): target AC scale (~60% baseline hit chance), 7 explicit calculation steps with Python — normal attack damage, studied-attacks formula, crit-bonus separation, second-attack-without-modifier shortcut, sneak-attack probability across multiple attacks, sneak-attack crit probability, advantage math, full DPR assembly.
- Verified per-level DPR tables from screenshots for 5 builds: Fighter Base Longsword + Fighter Base Greatsword + Sword-and-Shield Fighter + Zealot Barbarian Longsword + Berserker Barbarian Longsword.
- Commits: `354ce2c`, `6ae31f7`, `74edf29`, `b416c24`, `6091187`.

**Key decisions:**
- Treantmonk's 60% baseline hit chance vs the Finished Book's 65% is **not** a pillar conflict; they serve different purposes (per-class DPR calibration vs encounter XP). Formal resolution belongs in `pillars-reconciliation.md` (when drafted).
- Conjure Minor Elementals flagged as outlier (~80 DPR upcasted; "way above everything else") — engine flag required, DM override toggle (per `conditions-and-edge-cases.md`).
- Subclass selection becomes **mandatory** for T4 encounter accuracy — Barbarian and Paladin fall to D-tier at T4 without a damage subclass.

**Open items carried forward:**
- [ ] Per-level DPR tables for the remaining 34 builds. Re-categorized 2026-05-24 from "source data" to "validation reference data" — not blocking (sim computes its own DPR from encoded methodology); useful for cross-validation when ready.
- [ ] Spellcaster DPR methodology extraction (Treantmonk videos 11, 12, 13, 14, 15, 16, 18) — needed when engine reaches spellcaster scoring.

---

## Session: 2026-03-30 — Project Initialization

**Participants:** Phil, Claude

**Work done:**
- Evaluated Gemini's initial project framing (applied research / model-driven architecture). Assessment: solid on project management framing, weak on domain-specific technical due diligence.
- Identified The Finished Book and Keith Ammann's TMKWTD as the two foundational pillars.
- Established `/docs` folder structure and docs-as-code approach in GitHub repo.
- Rejected GitHub Wiki in favor of `/docs` in-repo (rationale: disconnects from code on Wiki, no version control parity).
- Rejected Cowork as project management tool (rationale: designed for file/task automation, not multi-AI architectural workflow; adds unnecessary tool layer).
- Completed full live-site audit of The Finished Book (all articles across Theory, Classes, Monsters sections as of March 2026).
- Produced `finished-book-summary.md` — covers all 20+ articles including six gaps missed by Antigravity/Perplexity in prior draft: Encounter Multiplier (full derivation), XP Approximations (three tiers), PC-side XP and daily economy, Magic Items as encounter variables, Variability series (full statistical layer), and 2024 rules EM change.
- Created GitHub repo: https://github.com/MarsBoundJ/dnd-combat-simulator
- Repo is public. `.gitignore` uses Python template + manual additions for GCP credentials, `.env`, Foundry `.db` files, and `node_modules`.

**Key decisions:**
- Exponential XP formula (`1.077^(AC+AB-15)`) chosen as engine truth over linear and published-monster approximations.
- 2024 rules: encounter multiplier defaults to 1.0 when using published 2024 XP values.
- Conditions resolved through eHP/eDPR adjustments, not ad-hoc damage modifiers.
- EV mode vs Sampled mode must never be mixed in the same encounter run.
- No engine code written until `pillars-reconciliation.md` is complete.

**Open items carried forward:**
- [ ] Draft `ammann-behavior-framework.md` — next priority (DONE — Mar 31).
- [ ] Draft `pillars-reconciliation.md` — blocked on Ammann doc (still open as of 2026-05-24).
- [ ] Decide: MCTS vs rules-based for monster AI (still open).
- [ ] Decide: data source for monster stat blocks (DONE — Open5e API; see 2026-05-24).
- [ ] Decide: Foundry VTT version to pin (still open).
- [ ] Decide: 2014 rules, 2024 rules, or both? (DONE — 2024; see 2026-05-24.)

---

<!-- Template for future sessions:

## Session: YYYY-MM-DD — [Short title]

**Participants:** Phil, [AI collaborators]

**Work done:**
- 

**Key decisions:**
- 

**Open items carried forward:**
- [ ] 

-->
