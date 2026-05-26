# SESSIONS.md — D&D Combat Simulator

Running log of key decisions, findings, and open items across AI sessions.  
Add a new entry at the top for each session that produces a non-obvious decision.

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
