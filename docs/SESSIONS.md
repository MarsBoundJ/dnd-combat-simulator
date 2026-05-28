# SESSIONS.md — D&D Combat Simulator

Running log of key decisions, findings, and open items across AI sessions.  
Add a new entry at the top for each session that produces a non-obvious decision.

---

## Session: 2026-05-28 — 8-PR engine push (PRs #85–#92)

**Participants:** Phil, Claude (Sonnet)

**Test count: ~1453 → 1544 passed + 1 skipped. Zero regressions across
the entire session.** Eight PRs landed sequentially, each merged after
explicit confirm. Two long arcs progressed in parallel — **party
coordination** (Reckless self-debuff → Ready Action → Help timing) and
**Paladin spell suite expansion** (Divine Favor / Prot from E&G →
Searing Smite → Hex → Hunter's Mark) — and a third smaller
**Rogue tactical polish** sub-arc shipped between them.

### Overview — patterns + infra that fell out

The session's real value isn't the spell list — it's the reusable
infrastructure that compounds. Future spells will land in much smaller
PRs because of what shipped here:

| Infra | Future consumers |
|---|---|
| `weapon_damage_bonus` primitive + query (PR #88) | Divine Favor, Hex, Hunter's Mark all used it |
| `target_is(<id>)` when-clause atom (PR #90) | Hex, Hunter's Mark, future target-specific riders |
| `recurring_damage` primitive + state list + runner hook (PR #89) | Heat Metal, Wall of Fire, ongoing poison |
| `attacker_creature_type_in(...)` atom (PR #88) | Prot from E&G, favored-enemy patterns |
| `Actor.creature_type` field (PR #88) | Same |
| `Actor.features_known` template stamp (PR #85) | Any future marker-feature gate |
| Pre-action runner hook pattern (PR #85, mirrors AS) | Any future free declaration |
| Composite lifetime (list-OR semantics) (PR #92) | First non-string lifetime; any future "expires on EITHER X OR Y" effect |
| `until_source_caster_next_turn` lifetime (PR #92) | Bardic Inspiration, Inspiring Word, future source-driven expirations |
| `scrub_source_caster_turn_start_modifiers` helper (PR #92) | Same |
| SA-aware Steady Aim scorer pattern (PR #87) | Template for "feature-interaction-aware" scoring uplifts |
| Searing Smite armed-marker pattern (PR #89) | Pattern for other "next-hit-only" spell riders |
| Ready Action machinery (PR #86) | Foundation for hold-initiative / ally_takes_damage / Ready-a-spell follow-ons |

---

### PR #85 — Barbarian Reckless Attack

**Work done:**
- L2 Barbarian free declaration. Pre-action runner hook
  `_maybe_activate_reckless_attack` fires before main slot, mirroring
  Action Surge's pre-action timing.
- Two boolean Actor flags (`reckless_active`,
  `reckless_grants_advantage_until_next_turn`) read directly by
  `query_attack_modifiers` — same identity-state pattern as Rage.
- AI scoring: archetype overrides (mindless_aggressor +
  berserker_fanatic always; cowardly_skirmisher never), else
  cost-benefit (expected DPR uplift vs incoming damage uplift at
  `RECKLESS_HIT_UPLIFT = 0.25`).
- Side benefit: `template.features_known` now stamped by `pc_schema` —
  opens the door for marker-style features without re-scanning class
  tables. Used by Reckless's eligibility check.
- 32 new tests. Suite: 1453 passed.

**Scope decisions:**
- No new active_modifiers entry (rejected for the Rage-style direct
  flag pattern). Cleaner for two-flag-with-coordinated-reset semantics.
- Pre-action hook vs slot-cost: Reckless is a free decision, not a BA.
  Pre-action hook matches RAW timing without consuming any slot.

**Open items:**
- Versatile-grip detection (Longsword two-handed should qualify)
- Per-enemy threat weighting in cost calc (v1 averages)

---

### PR #86 — Ready Action (party-coordination arc, first PR)

**Work done:**
- First piece of the party-coordination arc Phil flagged after PR #81
  Trip-formula correction. Two RAW triggers shipped:
  `enemy_enters_reach` (Ready a swing) + `enemy_casts_spell` (Ready
  an interrupt).
- `Actor.readied_action: dict | None` — single-slot, overwrites on
  re-ready (RAW: one Ready per turn).
- `engine/core/ready_action.py` — KNOWN_TRIGGERS / register /
  discard / try_fire + `on_movement_completed` +
  `on_spell_cast_initiated` event handlers.
- New `_ready_action` primitive flips the flag.
- Runner hooks: `_move_to_engage` fires enters_reach AFTER OAs;
  `pipeline.execute` fires casts_spell AFTER counterspell resolution
  + only if cast wasn't cancelled.
- Reaction slot consumed only when readied action fires (not at
  Ready time — RAW lets you ignore the trigger).
- AI: `_emit_ready_candidates` in pipeline gates emission to
  outranged actors only (can't close-and-attack this turn).
  `offensive_ehp_ready` scorer: expected damage ×
  `READY_TRIGGER_FIRES_PROBABILITY` (0.6 baseline).
- 20 new tests. Suite: 1473.

**Scope decisions:**
- Two triggers (vs single or full 3+spell). Phil's explicit pick via
  AskUserQuestion.
- AI emission gate caught a regression in OA tests during dev where
  overly-aggressive Ready emission diverted goblins from movement.
  Fix: emit only when actor can't close-and-attack (\walk + reach < distance).

**Open items:**
- `ally_takes_damage` trigger (Ready Cure Wounds on damaged ally)
- Ready-a-spell with concentration plumbing
- Hold-initiative / delay-turn mechanic
- Buff-before-burst sequencing
- Per-trigger probability calibration via session sims

---

### PR #87 — SA-aware Steady Aim scoring uplift

**Work done:**
- Closed PR #80 residue. Old Steady Aim scorer treated the BA as a
  generic advantage buff, missing the dominant value path: Steady
  Aim's advantage SATISFIES the Sneak Attack trigger, unlocking SA
  dice that wouldn't otherwise fire when no ally is adjacent.
- New two-component formula:
  - Base: `per_attack × DELTA_HIT_FROM_ADVANTAGE` (unchanged)
  - SA-unlock (Rogues only):
    - No adjacent ally → `expected_sa_damage × 0.7` (Steady Aim
      unlocks SA dice — pure uplift)
    - Adjacent ally present → `expected_sa_damage × 0.225` (SA
      would fire anyway; only hit-chance uplift on the dice)
- Suppressed when SA already fired this turn (RAW once-per-turn cap).
- L3 Rogue solo: ~0.34 → ~5.2 eHP (comfortably beats Cunning Action
  0.5-5 range). L11 Rogue solo: ~21 eHP. AI now commits to Steady
  Aim in the right tactical situations.
- 5 new tests on top of 14 existing. Suite: 1478.

**Scope decisions:**
- `STEADY_AIM_SA_UNLOCK_HIT_PROXY = 0.7` (conservative — typical
  Rogue +7 vs AC 15 with advantage is ~0.875; rounded down).
- Cunning Strike interaction not separately modeled — CS trades SA
  dice for effects at execution time, but the advantage delta
  applies regardless of how the dice are spent.

**Open items:** None — closes PR #80 residue cleanly.

---

### PR #88 — Divine Favor + Protection from Evil and Good

**Work done:**
- Two new 1st-level Paladin concentration spells, taking the
  Paladin's concentration menu from 2 (Bless / Shield of Faith) to
  4 viable options.
- **Divine Favor:** self-buff, BA cast, +1d4 radiant on weapon
  hits (flat +2 average per Bless pattern).
- **Protection from Evil and Good:** ally-targeted defensive buff,
  Action cast, disadvantage on incoming attacks from aberration /
  celestial / elemental / fey / fiend / undead.
- **New `weapon_damage_bonus` primitive** + `query_weapon_damage_bonus`
  helper. Integrated into `_damage` on weapon attacks only (skips
  spell damage). Reusable for future Hex / Hunter's Mark / Searing
  Smite damage riders — and was, in PRs #89-91 below.
- **New `Actor.creature_type` field** + cli loading from monster
  template or PC race.
- **New `attacker_creature_type_in(...)` when-clause atom** in
  `_eval_when` for runtime gating.
- 12 new tests. Suite: 1490.

**Scope decisions:**
- Built the weapon_damage_bonus infra here knowing it would carry
  Hex / Hunter's Mark / Searing Smite later.
- Prot from E&G's charm/frighten/possession immunity + movement
  gate explicitly deferred (each needs additional plumbing).

**Open items:**
- Per-roll d4 die (v1 flat +2, same as Bless)
- Charm/frighten/possession immunity by creature type
- Movement gate (the 5-ft "can't willingly approach" rule)

---

### PR #89 — Searing Smite + recurring damage infrastructure

**Work done:**
- Paladin smite-spell counterpart to Divine Smite (passive on-hit
  rider). BA cast, concentration, one-shot rider that empowers next
  melee hit + applies Ignited burning condition.
- **Major new infrastructure (all reusable):**
  - `state.recurring_damage` list — per-turn damage tick entries
  - `recurring_damage` primitive — registers entries
  - `runner._resolve_recurring_damage` — fires at affected creature's
    turn-start, invokes `_damage` with synthetic context
  - `_apply_condition` extension — when condition effect's primitive
    is `recurring_damage`, invoke directly instead of stashing on
    active_modifiers (not a modifier shape)
  - `end_concentration` extension — scrubs recurring_damage entries
    tied to dropped spell
- **`co_ignited` condition** — recurring_damage effect (1d6 fire,
  target_turn_start).
- **`engine/core/searing_smite.py`** — `register_armed` /
  `find_armed_entry` / `clear_armed` transitions +
  `try_apply_searing_smite_followup` fires from `_damage` on next
  melee weapon hit. Adds 1d6 fire (+1d6 per upcast level, doubled
  on crit) + CON forced_save + apply co_ignited on fail.
- 15 new tests (all passed first try). Suite: 1505.

**Scope decisions:**
- New `state.recurring_damage` list (vs piggybacking on
  recurring_save). recurring_save asks for saves; recurring_damage
  just deals damage — distinct semantics.
- Armed-marker pattern: one-shot modifier with `searing_smite_armed`
  primitive, cleared on first qualifying hit. Concentration
  continues for the burn after marker clears.

**Open items:**
- Target's action-to-save-to-end (RAW Ignited save break — currently
  only caster concentration drop ends it)
- Per-turn-burn upcast scaling (RAW: only empowering attack scales)

---

### PR #90 — Hex (target-specific damage rider)

**Work done:**
- Warlock signature 1st-level concentration spell. First spell to
  use the target-specific weapon damage rider pattern that PR #88's
  `weapon_damage_bonus` infra was built for.
- BA cast, 90 ft, +1d6 (flat +3) necrotic on hits against the
  cursed creature only.
- **`_eval_weapon_damage_when` extended with `target_is(<actor_id>)`
  atom.** Reads `state.current_attack.target.id` at attack-time and
  compares against id substituted into when-clause at cast time.
- `_hex_curse` primitive reads in-flight target's id, substitutes
  into when-clause, registers modifier on caster.
- Zero new state fields — pure consolidation of PR #88's
  `weapon_damage_bonus` + PR #43's concentration scrub + PR #36's
  `named_effect` dedup.
- **Class wiring note:** ships forward-compat with `granted_by:
  c_warlock` even though c_warlock doesn't exist yet. Schema accepts
  unknown class refs.
- 10 new tests (all passed first try). Suite: 1515.

**Scope decisions:**
- Target gate via new when-atom (vs a dedicated `hex_curse`
  modifier primitive). Cleaner; reusable for Hunter's Mark.
- Ability check disadvantage + rebind on death explicitly deferred.

**Open items:**
- Ability check disadvantage on chosen ability (needs target-
  specific d20_test_modifier with when-clause support)
- Rebind on target death (BA on subsequent turn)
- c_warlock class implementation

---

### PR #91 — Hunter's Mark (consolidation)

**Work done:**
- Ranger 1st-level concentration spell. Mechanically parallel to
  Hex — both ride PR #88's `weapon_damage_bonus` + PR #90's
  `target_is(<id>)` atom.
- New `_hunters_mark_mark` primitive (distinct from `_hex_curse`
  for named_effect tagging + event log clarity + future divergence
  like favored-target Perception tracking).
- **Notable test:** Hex + Hunter's Mark stack on same target —
  validates that cross-caster dedup uses `named_effect` as
  discriminator (not just "weapon damage bonus exists").
- Class wiring note like Hex — ships forward-compat under c_ranger
  L2 since Ranger spellcasting isn't wired yet.
- 8 new tests (all passed first try). Suite: 1523.

**Scope decisions:**
- Distinct primitive vs aliasing `_hex_curse`. Code clarity over
  DRY here — each spell's primitive is clearly attributable and
  can diverge later. ~25 lines duplication accepted.

**Open items:**
- WIS (Perception/Survival) advantage on the marked creature
  (shared deferral with Hex's ability check disadvantage)
- Rebind on target death
- Favored Enemy free-cast pool (Ranger-specific PHB 2024)

---

### PR #92 — Help-action timing (party-coordination arc, second PR)

**Work done:**
- Second PR in the party-coordination arc. Closes three gaps in
  the existing Help built-in:
  1. **RAW lifetime fix.** Help's RAW lifetime is "until the start
     of your next turn." The previous per_owner_attack-only lifetime
     let the buff persist across multiple helper turns if the ally
     never swung. **Composite lifetime** now expires on EITHER
     ally-swing OR helper's-next-turn-start.
  2. **Initiative-aware scoring.** Help wasted if ally won't act
     before helper's next turn. Scorer walks `state.turn_order`
     forward, returns 0 if ally doesn't appear before wrapping back.
  3. **Wasted-advantage detection.** Help dominated when ally
     already swings with advantage (Reckless, prior Help, Steady
     Aim, Vex proc). Returns 0.
- **New reusable infrastructure:**
  - Composite lifetime (list of lifetime kinds, OR semantics) —
    first non-string lifetime in the engine
  - `until_source_caster_next_turn` lifetime kind mapped to new
    `source_caster_turn_start` event
  - `scrub_source_caster_turn_start_modifiers` helper scans all
    actors and removes matching entries — reusable for future
    Bardic Inspiration / Inspiring Word-shape effects
  - Runner integration at `tick()` turn-start
- BUILT_IN_HELP updates: added `named_effect: "help"` + composite
  lifetime.
- 21 new tests. Suite: 1544.

**Scope decisions:**
- Composite lifetime as list (vs adding a new "OR" lifetime kind).
  More general; future "expires on N triggers" effects just list
  them.
- Source-caster scrub via separate helper (vs extending
  `expire_modifiers` to take owner-walk vs all-walk modes). Single-
  purpose helper has clearer call site.

**Open items:**
- Hold-initiative / delay-turn mechanic (next in party-coord arc)
- Buff-before-burst sequencing
- Same scrub for future source-caster-driven effects

---

### Session-level open items

**Party coordination arc (Ready was the foundation):**
- Hold-initiative / delay-turn mechanic
- Buff-before-burst sequencing
- `ally_takes_damage` Ready trigger
- Ready-a-spell with concentration plumbing

**Paladin polish (smaller now):**
- Compelled Duel (hard control via WIS save)
- Lay on Hands "cure Poisoned" branch
- Defensive-buff cross-caster dedup

**Race polish:**
- More racial traits (Elf Keen Senses, Dwarf Stonecunning, Halfling Nimbleness)
- Lucky on remaining d20 sites (Hide / Search / Counterspell / initiative / concentration)

**Spell additions:**
- Heroism (temp-HP-per-turn — would test the recurring-grant pattern at the temp-HP end of the spectrum, mirroring recurring_damage)
- Multi-target Bless (candidate-grouping extension)
- AI active-upcast preference
- Non-damage upcast (Magic Missile darts, Hold Person targets)
- AI scoring uplift for Silence
- Per-spell V-component declaration

**Other:**
- Strict JSON Schema validation with cross-file $refs
- Actual feat / equipment / background content YAMLs (empty folders)

---

## Session: 2026-05-27 — Paladin Lay on Hands (PR #83)

**Participants:** Phil, Claude

**Work done:**
- First HP-pool resource type. Paladin L1+ gets healing pool of
  5 × level HP, drains per-use, refreshes on long rest.
- New `_lay_on_hands` primitive computes heal amount at invoke
  time: `min(target_missing_hp, pool_remaining)`. Never
  overheals, never wastes pool. Self-rights the amount; pool
  drains by exactly the amount healed.
- New `f_lay_on_hands.yaml` with action_template (type=heal,
  slot=bonus_action, pipeline=[lay_on_hands primitive]).
  Picked up by PR #82's generic feature → action auto-attach
  pass — zero pc_schema changes.
- c_paladin L1 features extended; pool derivation via simple
  5 × paladin_level formula (no per-row class_resources entry).
- defensive_ehp_healing extended to recognize lay_on_hands
  primitive: amount = min(missing, pool) × desperation
  multiplier. Returns 0 when pool empty or target at full HP.
- New `_refresh_lay_on_hands_pool_to_max` in apply_long_rest
  for c_paladin.
- 19 new tests across 12 layers. Full suite: 1421 passed + 1
  skipped (was 1402 + 19 new).

**Scope decisions:**
- Pool formula derived directly in pc_schema (5 × level)
  rather than in per-row class_resources. Uniform formula
  means per-row repetition would be noise.
- Self-righting heal amount (min of missing + pool) eliminates
  per-candidate amount-stashing complexity — primitive
  computes at invoke time.
- Generic PR #82 auto-attach pass works for Lay on Hands
  without any new pc_schema code — validates the
  "feature YAML with action_template" pattern.

**Open items:**
- Spend 5 pool to neutralize Poisoned (RAW alternative use)
- Touch range gating (5-ft distance check)
- More Paladin healing / utility (Cure Wounds, Bless of the
  Wounded for Oath of Devotion, etc.)

---

## Session: 2026-05-27 — Paladin spellcasting v1: Bless + Shield of Faith (PR #82)

**Participants:** Phil, Claude

**Work done:**
- Paladin spell candidates ship for the first time. Slots were
  populated in PR #73 but no spell candidates emitted; this PR
  closes the gap with Bless + Shield of Faith.
- New `f_bless.yaml` (1st-level offensive_buff, concentration):
  registers attack_modifier (target=ally, when=attacker_is_self,
  modifier=attack_bonus, value=2) + save_modifier (flat +2).
  Uses flat +2 as deterministic approximation of RAW's 1d4
  (avg 2.5).
- New `f_shield_of_faith.yaml` (1st-level defensive_buff,
  BA, concentration): registers attack_modifier
  (target=ally, modifier=ac_modifier, value=2).
- c_paladin L2 features extended to include both spells.
- New generic "feature → action_template auto-attach" pass in
  `build_pc_template`: any feature in features_known whose
  YAML declares an action_template block gets the dict copied
  into template.actions. Future spell-shape features just need
  a YAML — no Python builder.
- AI scoring uses existing infrastructure (PR #36's
  offensive_ehp_buff_ally + PR #43's
  defensive_ehp_defensive_buff) — no new scorers needed.
- Cross-caster dedup works out of the box via named_effect.
- 15 new tests across 11 layers. Full suite: 1402 passed + 1
  skipped (was 1387 + 15 new).

**Scope decisions:**
- Bless flat +2 instead of per-roll 1d4. Engine doesn't have
  a roll_modifier primitive; flat approximation captures the
  RAW mechanical impact within ~0.5 eHP at scoring level.
- Single-target Bless candidate emission (one per ally). RAW
  allows multi-target up to 3 — same candidate-grouping
  extension as Fog Cloud upcast (PR #77 residue).
- Heroism deferred: temp-HP-per-turn mechanic not yet modeled.
- Generic feature-action auto-attach pattern lets future spell
  YAMLs ship with zero pc_schema changes — important for
  the Lay on Hands / Searing Smite / Divine Favor wave when
  that comes.

**Open items:**
- Heroism (needs temp-HP-per-turn)
- Multi-target Bless (RAW: 3 creatures per cast)
- Per-roll 1d4 via roll_modifier primitive
- Bless upcast (+1 ally per slot above 1st — non-dice scaling)
- Paladin spell preparation (auto-attaches unconditionally in v1)
- Other Paladin spells: Searing Smite, Compelled Duel, Wrathful
  Smite, Divine Favor, Protection from Evil and Good, etc.
- Defensive-buff cross-caster dedup (PR #36 only covers offensive
  buffs; Shield of Faith currently dedups via legacy per-caster
  path)

---

## Session: 2026-05-27 — Rogue Cunning Strike (PR #81)

**Participants:** Phil, Claude

**Work done:**
- RAW PHB 2024 Cunning Strike wired: Rogue L5+ trades 1d6 of SA
  damage for one of three effects (Poison/Trip/Withdraw). Picked
  by AI heuristic when effect value > 3.5 eHP cost; else full SA.
- New `engine/core/cunning_strike.py` module: registry, DC
  (8 + DEX_mod + PB), qualification, AI heuristic, effect
  application.
- `try_apply_sneak_attack` integration: AI picks effect →
  reduce SA dice by cost → roll reduced SA → apply effect.
- Effects:
  * Poison: CON save → co_poisoned on fail
  * Trip: DEX save → co_prone on fail (Large or smaller size gate)
  * Withdraw: actor.disengaging = True (v1: OA-suppression is
    the load-bearing value)
- 24 new tests across 14 layers. Full suite: 1387 passed + 1
  skipped (was 1363 + 24 new).

**Critical scoping correction (per Phil's note mid-PR):**
Initial Trip value formula was wrong — modeled "1.5 rounds of
target attacking at disadvantage + offensive value for adjacent
allies × rounds." Phil pointed out: **a Prone target stands up
at the start of their next turn by spending half their movement**,
so:
- Target's own attacks DON'T happen at disadvantage (they stand
  first)
- The Rogue who applied Trip DOESN'T benefit on their own next
  swing (target stands before the Rogue's next turn)
- **Only allies whose initiative slot falls between the
  attacker's turn and the target's next turn benefit** (each
  adjacent melee ally gets advantage on their attacks)
- Trip is fundamentally a party-coordination move

Corrected formula: `sum(ally_dpr × DELTA_HIT_FROM_ADVANTAGE)
for allies in initiative window × p_fail`. Uses
`estimate_dpr` (multi-attack-aware) per ally so Fighters with
Extra Attack correctly amplify value over single-attack allies.
Solo Rogues correctly compute 0 — won't pick Trip.

New `_allies_acting_before_target` helper walks
`state.turn_order` from attacker's index forward, collecting
allies until hitting the target's slot.

**Open items (Phil-flagged broader topic):**
- **Party coordination + initiative manipulation** as a deeper
  AI topic. Trip's value calc is the simplest case of it;
  Ready Action / holding initiative / Help-action-timing /
  buff-stacking-before-burst all share the same need: AI
  reasoning about who acts WHEN. Worth a dedicated arc.
- Devious Strikes (Rogue L11; higher-cost options)
- Improved Cunning Strikes (Rogue L14; two effects per SA)
- "Vial of basic poison" RAW prereq for Poison
- Withdraw's half-speed move cap

---

## Session: 2026-05-27 — Rogue Steady Aim (PR #80)

**Participants:** Phil, Claude

**Work done:**
- RAW PHB 2024 Steady Aim wired: BA at Rogue L3+ grants
  advantage on next attack + sets speed 0 rest of turn;
  requires you haven't moved this turn.
- New `steady_aim` primitive: registers per_owner_attack
  advantage modifier + flips `actor.moved_this_turn = True`
  (RAW "speed becomes 0" enforced by short-circuiting
  subsequent _move_to_engage calls).
- New generic `requires_no_movement: true` action flag +
  pipeline filter — actions with the flag are removed from
  the candidate set when `actor.moved_this_turn` is True.
  Future Stand-Still / Aim-shape actions reuse.
- `is_self_targeted_defensive_buff` extended to recognize
  `steady_aim` (same pattern as PR #71's rage_start, PR #74's
  dash).
- New `_score_steady_aim` AI scorer: per-attack damage ×
  DELTA_HIT_FROM_ADVANTAGE (framework's standard advantage
  value formula).
- `_build_steady_aim_action` auto-generates `a_steady_aim` in
  pc_schema for Rogue L3+; `f_steady_aim` added to c_rogue
  L3 row; new `f_steady_aim.yaml` feature.
- 14 new tests across 12 layers. Full suite: 1363 passed +
  1 skipped (was 1349 + 14 new).

**Scope decisions:**
- Eligibility gate (`requires_no_movement`) implemented
  generically so future actions with the same constraint
  (Stand Still, future Aim feats) can reuse without
  hardcoded Steady-Aim checks.
- AI scoring formula: simple per-attack × advantage delta.
  Doesn't yet credit Sneak Attack synergy uplift (advantage
  guarantees SA fires without needing ally-adjacent —
  deferred uplift for follow-up).
- "Advantage expires on miss" RAW pedantry not modeled;
  the modifier consumes on owner-made-attack regardless of
  outcome (per_owner_attack lifetime).

**Open items:**
- Sneak Attack synergy uplift in Steady Aim scoring
- Pre-targeting (RAW: pick a creature in weapon range; v1
  grants advantage on the next attack to whichever target)
- "Advantage expires on miss" pedantic RAW detail

---

## Session: 2026-05-27 — More zone-creating spells (PR #79)

**Participants:** Phil, Claude

**Work done:**
- Four PHB 2024 zone spells shipped (Phil picked all four
  via AskUserQuestion):
  * **Fog Cloud** — 20-ft sphere of heavy_obscurement, no
    damage. Zero new infrastructure; reuses PR #68's
    `creates_zone: heavy_obscurement` path.
  * **Stinking Cloud** — 20-ft sphere, CON save on
    turn-start; on fail apply `co_incapacitated` for
    until_actor_next_turn_start (RAW "use action doing
    nothing" → action gate via existing Incapacitated).
  * **Web** — 20-ft CUBE, DEX save on turn-start; on fail
    apply `co_restrained`. Exercises the cube-shape aura
    path. Re-saved each turn-start (RAW "Athletics check to
    escape" deferred — turn-start re-save is the v1 escape
    opportunity).
  * **Silence** — 20-ft sphere with NEW `silence_zone` type.
    Suppresses spell candidates for actors inside via new
    pipeline filter. Cantrips + weapon attacks pass through.
- New infrastructure:
  * `_CREATES_ZONE_TO_ENV_KEY["silence"] = "silence_zones"`
  * `concentration._SCRUBBABLE_ZONE_KEYS` adds silence_zones
  * `pipeline._actor_in_silence_zone(actor, state)` predicate
  * Pipeline candidate filter: spell candidates removed when
    actor is inside a silence_zone
- 13 new tests across 10 layers. Full suite: 1349 passed +
  1 skipped (was 1336 + 13 new).

**Scope decisions:**
- v1 simplification for Silence: filter ALL spells (any
  spell_slot_level >= 1) rather than only Verbal-component
  spells. No action declares its components today; future PR
  can add per-spell V/S/M tags and tighten the filter.
- Stinking Cloud's lightly-obscured aspect dropped for v1.
  The action-denial is the load-bearing effect; light
  obscurement is mostly perception-disadvantage flavor we
  don't model.
- Web's difficult-terrain aspect dropped for v1 (no per-
  square movement cost). The Restrained-on-save-fail is the
  load-bearing effect.
- Silence isn't routed through the vision-denial scorer
  (PR #78) — it's caster-denial, not vision-denial. AI
  scoring for the suppression value is a deferred follow-up.

**Open items:**
- AI scoring uplift for Silence (currently treated as a
  zero-value zone)
- Stinking Cloud / Web's secondary effects (light obscurement
  / difficult terrain / Athletics escape)
- Silence's Deafened in-sphere + Thunder immunity
- Per-spell V-component declaration to tighten the Silence
  filter
- Fog Cloud upcast (RAW +20 ft radius per slot above 1st —
  non-dice scaling, needs schema extension)

---

## Session: 2026-05-27 — AI scoring for damage+zone hybrid auras (PR #78)

**Participants:** Phil, Claude

**Work done:**
- Closes the PR #68 residue. Auras that BOTH deal damage AND
  create a vision-denial zone (HoH = cold + magical_dark;
  Cloudkill = poison + heavy_obscurement) now score with BOTH
  components summed; previously only one component fired.
- Generalized PR #61's `offensive_ehp_darkness` to
  `offensive_ehp_zone_vision_denial(...)` with explicit
  `radius_ft` + `zone_type` params. Sense-bypass varies by
  zone type:
  * magical_dark: blindsight OR truesight pierces
  * heavy_obscurement: blindsight ONLY (fog is physical, not
    magical — truesight doesn't help)
- Backward-compat wrapper `offensive_ehp_darkness` calls the
  generalized helper with Darkness defaults.
- Restructured `offensive_ehp_persistent_aura`:
  * No more early-return-to-darkness-scorer for magical_dark
  * Always computes damage component (returns 0 cleanly when
    no payload)
  * Always adds zone component when `creates_zone` is in
    `_VISION_DENIAL_ZONE_TYPES` registry
  * Returns damage_value + zone_value
- New `_VISION_DENIAL_ZONE_TYPES` constant centralizes the
  registry; future zone types extend it.
- 10 new tests across 10 layers. Full suite: 1336 passed + 1
  skipped (was 1326 + 10 new).

**Scope decisions:**
- Generalize-and-add rather than fork-per-spell. One helper
  handles both zone types parameterized by `zone_type`. Future
  zones (Stinking Cloud, Fog Cloud, Silence) extend the
  registry constant + reuse the helper.
- Damage + zone components SUMMED rather than max'd. Both are
  real value the AI can extract; summing matches the
  "framework's eHP composition" pattern used elsewhere.
- Truesight asymmetry (magical_dark vs heavy_obscurement)
  baked into the scorer directly. Matches `can_actor_see` RAW
  behavior from PR #52 / PR #69.

**Open items:**
- Per-creature attack-frequency weighting (multiattack monster's
  debuff is worth more than one-attack-per-turn caster's)
- "Caster forgot to put themselves in the sphere" opportunity-
  cost subtraction
- Per-spell upper-bound calibration (HoH + magical_dark may
  over-score if zone and damage value the same in-zone enemies)

---

## Session: 2026-05-27 — Upcast scaling for damage spells (PR #77)

**Participants:** Phil, Claude

**Work done:**
- Closes the PR #67 residue. Spells declaring `upcast_scaling`
  now actually cast at higher slot levels: candidate filter
  accepts higher slots when exact is unavailable; executor
  picks lowest available ≥ base; damage primitive applies
  bonus dice; persistent_aura captures + propagates the
  chosen slot through per-turn triggers.
- New helpers in `engine/core/spell_slots.py`:
  `lowest_available_slot_at_or_above`, `is_upcastable`,
  `has_slot_for_action`, `resolve_chosen_slot_level`.
- Pipeline filter via `has_slot_for_action` (cantrip /
  exact-level / upcastable, all uniformly handled).
- Pipeline `execute` resolves + stashes + consumes
  `chosen_slot_level`. Counterspell sees the chosen level via
  `spell_cast_initiated` (matches RAW: Counterspell keys off
  the actual cast level).
- Reaction `try_use_reaction` mirrors the same — Hellish
  Rebuke upcasts correctly from the reaction path.
- `_damage` calls `_resolve_upcast_extra_dice` which reads
  `chosen_slot_level` + `action.upcast_scaling`, adds
  `extra_dice_per_level × (chosen − base)` dice, with
  optional `damage_type` filter for multi-type spells. Crit
  doubles the upcast dice.
- Persistent aura registration captures `chosen_slot_level`
  + `upcast_scaling`; runner synthesizes an action dict with
  these on each per-turn trigger so the upcast helper fires.
- Three existing spells now upcast: Hellish Rebuke
  (+1d10 fire/level), Hunger of Hadar (+1d6 cold/level),
  Cloudkill (+1d8 poison/level).
- 31 new tests across 13 layers. Full suite: 1326 passed +
  1 skipped (was 1295 + 31 new).

**Scope decisions:**
- AI picks LOWEST available slot ≥ base (matches Divine Smite
  v1 from PR #73). RAW best practice — higher slot dice
  rarely beat saving the slot.
- Persistent aura path wired (rather than deferred) so HoH +
  Cloudkill actually upcast correctly. Required adding
  upcast metadata to the aura entry and synthetic-action dict
  the trigger creates.
- Damage type filter on `upcast_scaling` so multi-type spells
  (none in v1, but Hellish Rebuke half-damage-on-success and
  HoH on_fail+on_success both single-type) scale only matching
  damage steps.

**Open items:**
- AI choosing HIGHER-than-lowest slot when burst value justifies
- Non-damage upcast patterns (Magic Missile +1 dart, Hold Person
  +1 target, Bless +1 ally) — need schema extensions
- Upcast factor in candidate scoring (AI doesn't actively prefer
  upcast; it consumes it only when forced by slot scarcity)

---

## Session: 2026-05-27 — Total cover auto-miss (PR #76)

**Participants:** Phil, Claude

**Work done:**
- Closes the PR #48 residue. Adds `'total'` as a fourth cover
  state value and wires the RAW PHB 2024 behavior: "a target
  with total cover can't be the target of an attack or a spell."
- `Actor.cover` extended to four values
  (`none`/`half`/`three_quarters`/`total`). Total is a target-
  cancel (not an AC bump); `_cover_ac_bonus` returns 0 for it.
- `_attack_roll` early-auto-misses (before any d20 roll) when
  target has total cover. Emits `attack_roll` event with
  `reason: "total_cover"` and `result: "miss"`. No RNG
  consumed.
- New `_is_total_cover(target)` helper.
- `generate_candidates` computes `targetable_enemies` (filtering
  total-cover enemies) once; `weapon_attack`, `multiattack`,
  and `hard_control` branches use the filtered list.
- AoE attacks (`aoe_attack`, `persistent_aura`) unchanged —
  they enumerate ALL living enemies as anchor positions
  regardless of cover (RAW: AoE covers area, not creatures).
- 17 new tests across 10 layers. Full suite: 1295 passed + 1
  skipped (was 1278 + 17 new).

**Scope decisions:**
- Total cover stays independent of visibility (vision is a
  separate check — engine doesn't link them yet). Realistic
  total cover usually blocks LOS, but per-actor cover field
  is the simple v1 model; terrain-based LOS comes later.
- AoE NOT filtered — the position-based AoE math already
  ignores cover, which matches RAW. No new code there.
- Multiattack filtered at the primary-target pool level; sub-
  attack retargeting at execution time still hits the
  `_attack_roll` total-cover guard for defense in depth.

**Open items:**
- Per-(attacker, target) cover based on terrain geometry
  (current per-actor symmetric cover stays unchanged)
- Total cover ↔ vision blocking link (currently independent)
- Reaction-driven cover changes mid-attack

---

## Session: 2026-05-27 — SRD races v1 + save-source context (PR #75)

**Participants:** Phil, Claude

**Work done:**
- First per-race substrate. Phil narrowed scope from broader
  "10 species" proposal to SRD-only (Dwarf / Elf / Halfling /
  Human) and chose "add save-source context now" over deferring
  it — meaning racial traits like Brave / Fey Ancestry /
  Dwarven Resilience saves actually work mechanically out of
  the gate.
- New `race` entity type registered in the loader; new
  `schema/content/races/` directory with the 4 SRD species
  YAMLs.
- New `engine/core/racial_traits.py` module owns the trait
  registry + integration helpers (`has_racial_trait`,
  `racial_save_advantage_for`, `lucky_d20`, save-context
  builders).
- New `Actor.racial_traits` field; cli loads from template;
  pc_schema stamps from race YAML.
- New `state.current_save_context` — set by `_forced_save`
  before the per-target loop and by
  `_resolve_recurring_saves` before each query; restored
  after. Shape `{"applied_conditions_on_fail": [...]}`.
- `query_save_modifiers` reads the context and grants
  advantage when a target's racial trait matches an
  on_fail-applied condition.
- Halfling Lucky (reroll nat 1 on d20) wired in `_attack_roll`,
  `_forced_save`, and `_resolve_recurring_saves`.
- Dwarf poison damage resistance baked on the template.
- Human Skillful appends an extra skill proficiency at build
  time (picked via pc_spec.extra_skill).
- Sizes correctly stamped (Halfling=Small gates Push mastery
  per PR #65; others Medium).
- Speed inheritance: pc_spec.speed > race.speed > 30 ft default.
- 39 new tests across 14 layers. Full suite: 1278 passed + 1
  skipped (was 1239 + 39 new).

**Scope decisions:**
- SRD-only (Phil's narrower scope) — Dwarf / Elf / Halfling /
  Human. Non-SRD species (Aasimar / Dragonborn / Gnome /
  Goliath / Orc / Tiefling) deferred + would need
  `source: user_authored` tagging per project policy.
- "Add save-source context now" (Phil chose the bigger option
  over deferring it) — wired the infrastructure cleanly so
  the trait knowledge stays out of the primitives. Primitives
  publish "what happens on fail"; the query side decides
  which trait cares.
- Lucky wired at three sites (attack / forced_save /
  recurring save). Ability check sites (Hide, Search,
  Counterspell, initiative, concentration saves) deferred —
  the helper is ready, just not wired at those sites yet.

**Open items:**
- Lucky on ability check sites (~5 sites)
- Halfling Nimbleness (move through larger creatures)
- Elf Trance / Elf Keen Senses
- Dwarf Stonecunning / Toolkit Proficiency
- Non-SRD species (when project policy allows)
- Strict JSON Schema for `race` entity type (loader currently
  silently skips validation for race YAMLs because no schema
  file exists)

---

## Session: 2026-05-27 — Rogue Cunning Action v1 + generic Dash (PR #74)

**Participants:** Phil, Claude

**Work done:**
- Final feature in the per-class four-feature arc (Rage → SA →
  Divine Smite → Cunning Action). Closes the four-feature
  identity arc.
- Phil chose "Include Dash" scope (vs. defer-Dash or
  Dash-as-extra-movement-grant) via AskUserQuestion.
- New generic `dash` primitive sets `Actor.dashed_this_turn` and
  clears `moved_this_turn` (enabling the runner's post-BA
  second-move pass).
- New `Actor.dashed_this_turn` field; per-turn dedup attr
  `_dash_post_move_done` prevents the second-move pass from
  looping.
- `_move_to_engage` doubles walk speed when `dashed_this_turn`
  is set.
- Runner `_run_actor_turn` extended: after the Action Surge
  second slot, if Dashed AND not already-second-moved, call
  `_move_to_engage` once more. This is the BA-Dash "actually
  close the distance" payoff — without it, BA Dash mid-turn
  carries the flag uselessly into next turn.
- Three Cunning Action BA variants auto-generated for Rogue
  L2+ via `_build_cunning_action_actions` in pc_schema:
  Dash / Disengage / Hide, all `slot: bonus_action`. Disengage
  reuses PR #26's dispatch; Hide reuses PR #48's
  `_execute_hide`; Dash uses the new generic primitive.
- `is_self_targeted_defensive_buff` extended to recognize
  `dash` (same pattern as PR #71 added `rage_start`).
- New `_score_dash` in defensive_ehp: ~0-5 eHP based on
  whether the actor needs to close distance to an out-of-reach
  enemy; 0 when wasted.
- c_rogue YAML adds `f_cunning_action` at L2.
- New `f_cunning_action.yaml` feature (active_menu, BA cost).
- 14 new tests across 11 layers. Full suite: 1239 passed + 1
  skipped (was 1225 + 14 new).

**Scope decisions:**
- Phil picked "Include Dash" — wired the generic primitive
  rather than deferring or hand-rolling a movement-bonus
  shortcut. This means future actors / actions that need
  Dash semantics get it for free.
- Post-BA second-move pass solves the "BA Dash mid-turn is
  useless" problem cleanly without restructuring the turn
  loop. Mirrors the Action Surge post-BA pattern.
- All three CA modes use existing dispatch paths (dash via new
  primitive, disengage via PR #26 type-branch, hide via PR #48
  type-branch). No new pipeline machinery beyond the dash
  primitive itself.

**Open items:**
- Generic main-slot Dash available to all actors (currently
  only Rogue gets it via Cunning Action BA)
- Steady Aim (Rogue L3 BA: advantage on next attack if no
  movement)
- Cunning Strike (Rogue L5: spend SA dice for Poison / Trip /
  Withdraw effects)
- The per-class four-feature class-identity arc is now
  complete (PR #71-74). Per Phil's earlier list, remaining
  candidates: per-race PC sizes + racial features; total
  cover; upcast scaling; AI scoring for hybrid auras; more
  zone-creating spells.

---

## Session: 2026-05-27 — Paladin Divine Smite v1 (PR #73)

**Participants:** Phil, Claude

**Work done:**
- Third feature in the per-class four-feature arc (Rage → SA →
  Divine Smite → Cunning Action).
- PHB 2024 mechanic wired correctly: Divine Smite is now a
  1st-level Paladin spell with BA casting time taken
  "immediately after hitting a target with a Melee weapon
  attack" — consumes both BA AND a Paladin spell slot.
- New `engine/core/divine_smite.py` module:
  * Dice math: 2d8/3d8/4d8/5d8 at slots 1-4; caps at 4th
    (RAW 2024); +1d8 vs Fiend or Undead
  * Qualification gate: paladin level >= 2, melee weapon,
    slot available, BA not yet spent, dedup flag clear
  * AI slot-pick heuristic: always smite on crit; kill-steal
    detection; Fiend/Undead bias; pace-aware via
    `slot_cost_ehp`; always picks lowest available slot
  * Application: consumes slot, marks BA, sets dedup,
    emits `divine_smite_applied` event with trigger reason
- `_damage` integration: fires after SA rider on hit/crit
  melee attacks; folded into same damage instance.
- New `_derive_class_spell_slots` helper in pc_schema reads
  `class_resources.spell_slots` from the level table and
  stamps onto `template["spell_slots"]`. cli falls back to
  template when actor_spec doesn't declare slots.
- c_paladin YAML extended L5→L20 with full half-caster slot
  progression + `f_divine_smite` at L2 + creature_type
  awareness for the Fiend/Undead bonus check.
- New `f_divine_smite.yaml` feature (passive, no
  auto-generated action — smite fires inside _damage).
- Per-turn dedup via `_divine_smite_used_this_turn`.
- 31 new tests across 13 layers. Full suite: 1225 passed +
  1 skipped (was 1194 + 31 new).

**Scope decisions:**
- Passive rider in `_damage` rather than a separately-scored
  BA candidate — matches RAW timing (smite damage is part of
  the attack's hit) and keeps the AI decision inside the
  damage path.
- Lowest-slot-first selection — RAW best-practice; higher
  slot dice rarely beat saving the slot for non-smite spells.
- Always-smite on crit captures the "always smite" pattern
  most Paladin players play; pace-aware gating handles the
  non-crit case.

**Open items:**
- Higher-slot smite when the player wants the burst (v1
  always picks lowest)
- Smite as a separately-scored AI candidate (would let the AI
  hold off on a small attack and smite a bigger one)
- Full Paladin spellcasting (preparing + casting Bless /
  Shield of Faith / Heroism — slots are populated but no
  candidates emit yet)
- Lay on Hands, Divine Sense, Aura of Protection
- 2014-style "see hit result, then decide" timing

---

## Session: 2026-05-27 — Rogue Sneak Attack v1 (PR #72)

**Participants:** Phil, Claude

**Work done:**
- Second feature in the per-class four-feature arc (Rage → SA →
  Divine Smite → Cunning Action).
- New `engine/core/sneak_attack.py` module: level table
  (ceil(level/2) d6), qualification, application. RAW gate:
  Finesse OR Ranged weapon + (advantage OR (ally-adjacent +
  no disadvantage + ally not Incapacitated)).
- Ally-adjacent check excludes the attacker themselves (RAW:
  "Another enemy of the target") and Incapacitated allies.
- Per-turn dedup via `_sneak_attack_used_this_turn` Actor attr;
  cleared by `reset_turn`. Fires on reaction OAs (once per
  TURN, not per round).
- Crits double SA dice (RAW: extra dice from class features
  double on crit).
- `_damage` invokes the SA rider after the Rage rider but
  before resistance; emits `sneak_attack_applied` with dice
  count, total, crit flag, and trigger reason
  (`advantage` / `ally_adjacent`) for telemetry.
- `finesse: true` flag plumbed from weapon spec into
  `attack_params.finesse` via pc_schema's
  `_build_weapon_action`.
- c_rogue YAML extended L5→L20 with per-level
  `sneak_attack_dice` + `f_sneak_attack` at L1.
- New `f_sneak_attack.yaml` feature (passive, no
  auto-generated action — SA fires on hits, not on
  separate candidates).
- 19 new tests across 10 layers. Full suite: 1194 passed +
  1 skipped (was 1175 + 19 new).

**Scope decisions:**
- Passive rider in `_damage` (no separate "sneak attack"
  candidate / action) — matches RAW shape: SA is part of the
  weapon's damage roll, not a separate decision.
- AI scoring uplift for the SA-qualifying attack vs other
  candidates DEFERRED. The Rogue will still attack and SA
  will fire; the choice of WHICH attack is still scored
  without the SA-bonus weighting.

**Open items:**
- Cunning Strike (2024 PHB; trade SA dice for Poison / Trip /
  Withdraw effects) — separate PR
- Steady Aim (BA: advantage on next attack if no movement) —
  pairs naturally with Cunning Action (next PR)
- Score uplift for SA-qualifying attacks

---

## Session: 2026-05-27 — Barbarian Rage v1 (PR #71)

**Participants:** Phil, Claude

**Work done:**
- First feature in the per-class four-feature arc (Rage / Sneak
  Attack / Divine Smite / Cunning Action — Phil picked "one
  feature per PR, Rage first").
- New `engine/core/rage.py` module owns the state machine:
  level tables (RAW 2024 uses + damage bonus progression),
  `enter_rage` / `end_rage` transitions, and
  `check_rage_end_of_turn` for the auto-end check.
- Bonus-action `a_rage` auto-generated by `pc_schema` for
  Barbarian PCs at L1+. Type `defensive_buff` so it routes
  through the existing self-buff candidate dedup. Pipeline
  calls the new `rage_start` primitive.
- All four RAW effects wired:
  * +rage_damage_bonus on STR melee weapon damage (gated via
    new `_extract_attack_params` helper that reads the in-
    flight attack_roll's `kind`/`ability` params from the
    pipeline)
  * Halve incoming bludgeoning/piercing/slashing damage on
    raging targets (doesn't double-halve when template
    already declares resistance)
  * Advantage on STR saves + STR ability checks (read off
    `rage_active` in `query_save_modifiers` /
    `query_d20_test_modifiers`)
  * End-of-turn auto-end if no hostile attack made AND no
    damage taken
- Long rest restores rage_uses to max via new
  `_refresh_rage_uses_to_max` in rest.py.
- `template.levels = {short_class: level}` stamp added —
  PC-side convention for class-level resolution; rage reads
  `levels.barbarian` for damage scaling.
- Class YAML c_barbarian extended L5→L20 with per-level
  rage_uses + rage_damage_bonus.
- New AI scoring path in `_score_rage_entry` (defensive_ehp):
  2 swings × bonus × buff_rounds (offensive) + 0.5 ×
  worst_enemy_dpr × buff_rounds (defensive). Returns 0 if
  already raging.
- 27 new tests across 9 layers. Full suite: 1175 passed +
  1 skipped (was 1148 + 27 new = 1175).

**Scope decisions:**
- "One feature per PR, Rage first" — picked via AskUserQuestion
  vs all-four or two-PR splits.
- Identity-state reads (rage_active) rather than registry
  modifier registration. Simpler, no lifetime concerns.
- Entry-turn grace clause on the auto-end check (the BA
  consumed everything; give them next turn to swing).
- Damage rider added to total BEFORE template
  resistance/vuln/immunity (RAW: bonus is part of the
  damage roll, then resistance applies).

**Open items:**
- Incapacitation ends rage (needs hook into condition
  application — Stunned/Paralyzed/Unconscious cascade).
- Concentration / spellcasting suppression for multiclass
  Barbarian spellcasters.
- Short-rest one-charge recovery (Relentless Rage L11+).
- 10-minute hard duration cap (auto-end covers the
  practical case but a round counter would close the gap).

---

## Session: 2026-05-27 — Free-action scoring v1 (PR #70)

**Participants:** Phil, Claude

**Work done:**
- Wired AI scoring into the free-slot action phase. Free actions
  (auto-fired between action and bonus-action phases by
  `_run_free_phase` — today only PR #57's Nick mastery off-hand)
  now route through `score_candidate` before firing.
- Added optional `min_score_to_fire` per-action gate. When set
  above 0, candidates whose score falls below the threshold are
  suppressed with a `free_action_skipped` event (reason
  `below_min_score`); the threshold defaults to 0.0 so v1 Nick
  behavior is preserved bit-for-bit.
- `free_action_fired` event now carries a `score` field
  (rounded to 2 decimals) for telemetry.
- 6 new tests in `tests/test_free_action_scoring.py`. Full suite:
  1148 passed, 1 skipped (was 1143 + 6 new).

**Scope decisions:**
- "Score + log only (no behavior change)" — Phil picked tight
  scope. The gate is wired everywhere but inactive by default
  (no shipping action sets `min_score_to_fire`), so the change is
  observable in event logs only until future free actions opt in.
- Re-selection of target against the free-action's profile
  deferred — runner currently reuses the action-phase target.
  Future work: pick targets per-free-action when a different
  enemy would score higher.
- Scoring for non-weapon free actions deferred (none ship yet).

**Open items:**
- Next BA Cleave / Vex+Sap off-hand combos can opt into the
  gate by adding `min_score_to_fire` to their YAML.
- Per-target re-selection for free-phase candidates.

---

## Session: 2026-05-27 — Blindsight bypass for Darkness scoring (PR #69)

**Participants:** Phil, Claude

**Work done:**
- Closes the PR #61 residue. The Darkness scorer's sense-bypass
  helper previously checked Truesight only; PR #69 extends it to
  also check Blindsight, matching the `can_actor_see` precedence
  from PR #52 where Blindsight is the dominant override for
  magical darkness.
- **Helper rename + extension:**
  `_truesight_pierces(observer, target)` →
  `_sense_pierces(observer, target)` in `offensive_ehp_darkness`.
  Now checks both `truesight_range_ft` AND `blindsight_range_ft`
  against distance; returns True if EITHER reaches.
- **Both call sites updated** (benefit-side: enemy piercing ally;
  cost-side: ally piercing enemy). Single helper, two consumers.
- **Behavioral effects:**
  - Out-sphere enemies with Blindsight in range contribute 0
    defensive value (instead of full DPR × disadvantage_delta).
    The AI scores Darkness LESS against blindsight monsters.
  - Out-sphere allies with Blindsight in range contribute 0
    cost. The AI is more willing to drop Darkness on enemies
    when blindsight allies are positioned.
  - Either sense alone suffices; both together don't
    double-count (boolean OR).
- **Module-level deferred-list note updated** to remove the
  now-shipped "Blindsight bypass" entry.
- **Tests (4 new in `test_darkness_scoring.py`):**
  - blindsight enemy reduces defensive benefit (less score
    than no-bs enemy in same spot)
  - blindsight out-of-range doesn't bypass (matches no-bs)
  - blindsight ally reduces cost (score ≥ no-bs ally case)
  - truesight + blindsight + both produce equivalent scores
    (boolean OR, no double-count)
- `_make_actor` helper extended with `blindsight_range_ft` kwarg
  for the new tests.
- 1143 tests pass (+4 new, 1 skip, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- Per-target attack-frequency weighting (multiattack >
  one-attack-per-turn) — still deferred from PR #61
- Opportunity-cost subtraction for concentration (PR #56 pace-
  aware shape) — still deferred
- Generalize the sense-bypass logic for other zone types — when
  AI scoring lands for Cloudkill / HoH (PR #68 zones), the same
  `_sense_pierces` shape would apply (with Truesight removed
  for fog: Truesight pierces magical darkness but NOT physical
  obscuring matter per RAW). Refactor opportunity when those
  scorers land.

---

## Session: 2026-05-27 — Hunger of Hadar + Cloudkill (PR #68)

**Participants:** Phil, Claude

**Work done:**
- Closes the "other zone-creating spells" residue from PR #60.
  Two SRD spells ship that exercise the `creates_zone` hook with
  a NEW zone type (`heavy_obscurement`, alongside the existing
  `magical_dark`).
- **`_persistent_aura` generalization:**
  - New module-level `_CREATES_ZONE_TO_ENV_KEY` dict maps the
    creates_zone string to the environment list key:
    `"magical_dark" → magical_dark_zones`,
    `"heavy_obscurement" → heavily_obscured_zones`.
  - Body of the creates_zone branch refactored to look up the
    env_key from the dict; raises with the known list on
    unknown values. Future zone types (Stinking Cloud, Silence,
    Web, difficult_terrain) extend the dict.
- **`concentration.end_concentration` generalization:**
  - Replaces the magical_dark_zones-only scrub with a loop over
    a list of scrubbable zone keys (currently
    magical_dark_zones + heavily_obscured_zones). Each iter
    runs the same caster_id + action_id matcher.
  - Listed in concentration.py (not imported from primitives)
    to keep the engine.core → primitives import direction
    one-way. A drift hazard but lightweight; documented in a
    code comment.
- **`f_hunger_of_hadar.yaml`** (Warlock 3rd):
  - 20-ft sphere of magical darkness + per-turn damage.
  - RAW says 2d6 Cold (no save) + 2d6 Acid (STR save half) per
    turn. v1 models as a single CON save: 4d6 cold on fail,
    2d6 cold on success. The combined cold/acid damage and the
    STR-vs-CON save are approximated for runtime simplicity.
  - The "Acid save = STR" RAW detail deferred — primitive's
    `ability=constitution` is the closest existing fit for
    "this hurts you" saves.
- **`f_cloudkill.yaml`** (Wizard 5th):
  - 20-ft sphere of heavily-obscuring poison fog + per-turn
    damage.
  - RAW: 5d8 Poison CON save (half on success).
  - Cloud movement (10 ft/round away from caster) deferred —
    same shape as Moonbeam's deferred bonus-action movement.
  - Upcast scaling deferred (+1d8 per slot above 5).
- **Vision integration via existing infra:**
  - Cloudkill's `heavy_obscurement` blocks ordinary sight +
    truesight (RAW: fog is physical; only Blindsight pierces).
  - HoH's `magical_dark` blocks ordinary darkvision; Truesight
    + Blindsight pierce.
  - PR #60's sphere-shape support in `_position_in_any_zone`
    Just Works™ — no vision.py changes needed.
- **Tests (17 new in `test_zone_spells.py`):**
  - `_CREATES_ZONE_TO_ENV_KEY` mapping completeness for both
    zone types
  - `_persistent_aura` with creates_zone=heavy_obscurement
    appends a sphere zone correctly
  - magical_dark regression (existing path still works)
  - Unknown creates_zone value raises with known-list
  - `end_concentration` scrubs both types; preserves static
    zones; multi-caster independent
  - Cloudkill vision: blocked for ordinary; not pierced by
    truesight; pierced by blindsight; helper recognizes sphere
  - HoH vision: blocked for darkvision; pierced by truesight
    in range; helper recognizes sphere
  - YAML files load + match expected shape
- 1139 tests pass (+17 new, 1 skip, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- HoH RAW dual-save mechanic (STR vs Acid + always-on Cold) —
  v1 combines as one CON save event for runtime simplicity
- Cloudkill wind-direction movement
- Upcast scaling (Cloudkill: +1d8 per slot above 5)
- AI scoring for HoH / Cloudkill (PR #61's Darkness scoring
  would generalize but doesn't yet handle damage+zone hybrids)
- More zone-creating spells (Stinking Cloud, Silence, Web,
  Fog Cloud) — the hook is ready

---

## Session: 2026-05-27 — REACTION_SLOT_BASE_COSTS calibration (PR #67)

**Participants:** Phil, Claude

**Work done:**
- Closes the PR #56 residue. Per-slot-level base eHP costs were
  eyeballed at PR #56 ship (4/6/10/14/18/22/26/30/36); this PR
  recalibrates them against RAW spell damage anchored at each
  slot level + Treantmonk's tier-aggregated DPR context.
- **Mid-session sanity check:** Phil asked if the calibration
  needed the per-class Treantmonk per-level DPR curves to be
  finished (currently 5 of ~20 builds complete). Verified that
  the calibration only needs per-slot spell damage math (mostly
  RAW arithmetic) + tier-aggregated DPR for context (which IS
  complete). Per-class videos would help with future per-class
  slot-vs-attack tradeoff tuning, not this slot-level
  calibration. Proceeded with current data.
- **Calibration methodology:**
  - For each slot level, identify the canonical best-use spells
    (highest damage + commonly-cast utility/control).
  - Compute the EXPECTED VALUE in eHP (damage with hit/save
    odds factored, HP-prevented for defensive, turns-of-control
    × per-turn-DPR-denied for control).
  - Round up slightly so utility spells (which are harder to
    score) aren't systematically underweighted vs pure damage.
- **New REACTION_SLOT_BASE_COSTS values:**
  - L1: 10 (Magic Missile 10.5 / Shield blocks 10-15 / Healing
    Word ~7)
  - L2: 15 (Scorching Ray 12.6 / Hold Person 30+ over duration)
  - L3: 28 (Fireball 28+ AoE / Counterspell / Hypnotic Pattern)
  - L4: 38 (Polymorph / Ice Storm / Wall of Fire)
  - L5: 50 (Wall of Force / Animate Objects / Cone of Cold 36)
  - L6: 65 (Disintegrate 75 nuke / Chain Lightning / Heal 70)
  - L7: 75 (Finger of Death 61 / Forcecage / Plane Shift)
  - L8: 85 (Power Word Stun / Sunburst 42 AoE / Maze)
  - L9: 100 (Wish / Meteor Swarm 140 / Time Stop / PW Kill)
- **Treantmonk context** in the docstring: the 2024 baseline
  (C-tier Warlock Blade Pact Greatsword) does ~24 DPR at T2,
  so a 3rd-level slot's 28 eHP value ≈ one good turn of T2
  baseline DPR. The slot-spent should buy roughly one turn of
  best-weapon damage — that's the calibration anchor.
- **Behavioral effects of the calibration:**
  - **Shield (L1)** skips weak attackers in mid-day setups
    (cost 10 > attacker DPR < 10); fires on Ogre+ DPR.
    Previously fired against almost any attacker — now
    discriminating, which matches RAW player behavior.
  - **Counterspell (L3)** breaks even vs L3 spells (28 = 28);
    skips lower-level spells (L1 spell value 10 < cost 28);
    fires aggressively vs L4+ spells. Previously fired vs
    anything — now correctly preserves slot for big targets.
  - **Hellish Rebuke (L1)** skips in mid-day single-slot
    setups (value 8.25 < cost 10); fires when slot abundant
    (4 slots → cost 2.5) or last encounter (cost 3.3). The
    correct "save for when it matters" pattern.
- **3 existing tests updated:**
  - `test_last_encounter_cost_is_low` now uses
    `REACTION_SLOT_BASE_COSTS[1]` rather than hardcoded `4.0`
    (so future tweaks don't drift this test)
  - `test_shield_turns_hit_into_miss` sets
    `encounters_remaining_today=1` — pacing was previously
    invisible because all tests defaulted to 3 encounters
    AND the old cost was low. The mechanics test now bypasses
    pacing by using the last-encounter scenario; dedicated
    pace tests live in `test_pace_aware_reactions.py`.
  - `test_hellish_rebuke_damages_attacker` similarly sets
    `encounters_remaining_today=1`.
- **Tests (20 new in `test_reaction_cost_calibration.py`):**
  - 9 pinned-value tests (one per slot level) with rationale
    comments — future calibration changes MUST update these,
    which is the desired coupling
  - 2 sanity tests: monotonically non-decreasing + ≤2× growth
    ratio (catches a typo like L4=100 vs L4=10)
  - 9 downstream behavior tests: Shield mid-day high/low DPR
    + last-encounter; Counterspell vs L1/L3/L7; Hellish
    Rebuke mid-day / abundant slots / last encounter
- 1122 tests pass (+20 new, 1 skip, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- Per-class slot-vs-attack tradeoff calibration — waits on
  Treantmonk per-class video processing (currently 5 of ~20
  complete). When more land, per-class scoring can tune slot
  costs relative to that class's weapon DPR.
- Upcast scaling — L3 Fireball cast in L5 slot = 10d6 vs 8d6
  (40% more damage). The slot-spent should score higher when
  upcast; currently it doesn't.
- Character-level scaling — a L11 wizard's L3 slot is worth
  less than a L5 wizard's L3 slot (the L11 has more other
  options). v1 ignores character level in the slot cost.

---

## Session: 2026-05-27 — Cleave reach passthrough (PR #66)

**Participants:** Phil, Claude

**Work done:**
- Closes the PR #58 residue. Cleave's attacker-reach constraint
  used to hardcode 5 ft (a TODO comment said "Future: pass weapon
  reach via params"); reach weapons (Glaive / Halberd / Pike at
  10 ft) couldn't Cleave to a second target between 5 and 10 ft
  away from the attacker even when the second target was within
  5 ft of the primary.
- **`_build_weapon_action` extension:** bakes `reach_ft` into
  the mastery sub-dict alongside the existing `id`,
  `ability_mod`, `damage_type`, `save_dc`. Reads from
  `weapon.get("reach_ft", 5)` — defaults to 5 when the spec
  omits the field. Matches the default already used by
  attack_roll's `reach_ft` param.
- **`_mastery_cleave` extension:** reads `reach_ft = int(
  params.get("reach_ft", 5))` instead of the hardcoded 5. The
  "within 5 ft of primary target" distance stays at 5 — that's
  a fixed RAW constraint between the two targets, not the
  attacker. Comments updated to explain the two distinct
  distances.
- **Tests (7 new in `test_cleave_reach.py`):**
  - Build-time: default reach 5 baked; explicit reach 10
    baked; reach omitted defaults to 5
  - Runtime: reach 5 attacker can't reach a secondary at 10 ft
    (skip with no_second_target); reach 10 attacker hits same
    secondary; reach 10 still can't Cleave to a secondary > 5
    ft from primary (the 5-ft invariant); missing reach_ft
    param falls back to 5
- 1102 tests pass (+7 new, 1 skip, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- Line-of-sight check on second target — RAW doesn't require
  it, but a wall between primary and secondary should arguably
  block. v1 trusts open-battlefield (no LOS layer for melee
  attacks yet).
- Secondary-target preference ordering — v1 picks first-in-
  actor-list (deterministic but arbitrary). AI could prefer
  low-HP / high-DPR / specific-tactical-priority targets.
- Cleave Reach with monster weapons — monster templates trust
  their own attack_roll.reach_ft; the Cleave sub-attack would
  need the same passthrough if monsters ever get Weapon
  Mastery wired in.

---

## Session: 2026-05-27 — Actor.size + Push size gate + Heavy gate (PR #65)

**Participants:** Phil, Claude

**Work done:**
- Closes two PR #58 residues at once: Push lacked a target-size
  gate, and Cleave/Graze trusted the weapon spec rather than
  enforcing the Heavy property at build time. Both gates are
  RAW-faithful and catch issues at fixture load.
- **`engine/core/sizes.py`** (new module):
  - 6 canonical sizes tiny < small < medium < large < huge <
    gargantuan
  - `KNOWN_SIZES` tuple in canonical order (so index-based
    comparison via `size_at_or_below` is well-defined)
  - `PUSH_SIZES` frozenset (Large or smaller — what Push can
    affect per RAW)
  - `normalize_size(value)` — lowercase, None/empty → 'medium',
    unknown raises with the known-list
  - `size_at_or_below(a, b)` — normalize both then index-compare
- **`Actor.size: str = "medium"`** field. Default value matches
  the "average human" baseline; the field defaults work for all
  existing code paths that didn't set size.
- **`cli._build_actor` loading:** precedence is actor_spec
  override → template top-level `size:` → 'medium' default.
  Normalized through `sizes.normalize_size` so typos raise at
  fixture load. Existing monster YAMLs already declare
  `size: small` (goblin) → no schema migration needed.
- **`_mastery_push` size gate** (in weapon_masteries.py):
  - Reads target.size, normalizes
  - If not in PUSH_SIZES (i.e., Huge or Gargantuan): logs
    `weapon_mastery_skipped` with reason=size_immune +
    target_size; returns without moving the target
  - Otherwise proceeds with the existing push_creature call
- **`_build_weapon_action` Heavy gate** (in pc_schema.py):
  - When weapon.mastery is cleave or graze:
    - Raises if `heavy` is not True ("requires Heavy melee
      weapon (RAW 2024)" with helpful add/remove hint)
    - Raises if weapon has `range_ft` (Heavy MELEE specifically;
      Heavy Crossbow is heavy but ranged and so disqualified)
  - Other masteries unaffected — Vex/Sap/Topple/Push/Nick don't
    require Heavy
- **One existing fixture updated:** the weapon_mastery_showcase
  greatsword now declares `heavy: true` (was two_handed-only —
  the new gate would otherwise raise on Graze mastery).
- **Tests (24 new in `test_size_gates.py`):**
  - sizes module: KNOWN_SIZES count, PUSH_SIZES exclusions,
    normalize edge cases, size_at_or_below
  - Actor.size loading: default medium, explicit kept, cli loads
    from template / overrides / unknown raises / defaults when
    omitted
  - Push gate: Medium / Large pushed; Huge / Gargantuan immune
    (with skip event); Tiny pushed
  - Heavy gate: Cleave on heavy passes / on non-heavy raises;
    Graze on heavy passes / on non-heavy raises; Cleave on
    ranged-heavy raises (Heavy Crossbow); other masteries
    unaffected on light weapons
- 1095 tests pass (+24 new, 1 skip, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- Per-attacker push direction (RAW allows "in a straight line
  away from you" only; future could support arc / push-into
  variants for AI tactics)
- Collision handling on push destination — still open-
  battlefield assumption
- Heavy gate on monster-template attack actions — currently
  only PC-schema-generated weapons gate; monster templates
  trust their own declarations
- Grapple / Squeezing mechanics (size-relative checks)
- Future per-class race wiring for PC size (currently PCs
  default to medium; Halflings / Goblins / Centaurs etc. would
  override via race)

---

## Session: 2026-05-27 — Other-class Weapon Mastery wirings (PR #64)

**Participants:** Phil, Claude

**Work done:**
- Closes the PR #54 residue. Weapon Mastery was wired on Fighter
  only; the other four mastery-knowing classes (Barbarian /
  Paladin / Ranger / Rogue) had no class YAML at all. Pre-scoped
  to "minimal class YAMLs + cap enforcement" — full class specs
  (Rage / Sneak Attack / Divine Smite / etc.) deferred to
  dedicated follow-on PRs.
- **Four new class YAMLs** under
  `schema/content/classes/`:
  - `c_barbarian.yaml` — d12 HD, STR+CON saves, weapon mastery
    2@L1 → 3@L4
  - `c_paladin.yaml` — d10 HD, WIS+CHA saves, 2@L1 → 3@L11
  - `c_ranger.yaml` — d10 HD, STR+DEX saves, 2@L1 → 3@L9
  - `c_rogue.yaml` — d8 HD, DEX+INT saves, 1@L1 → 2@L9
  Each declares `core_traits` (hit_die, save_proficiencies,
  weapon/armor profs, skill choices) + a `level_table` with
  `weapon_mastery_count` per RAW progression + `f_weapon_mastery`
  at L1. Other class features listed as deferred in trailing
  comments (Rage, Lay on Hands, Sneak Attack, etc.) so future
  PR authors have a checklist.
- **`_validate_weapon_masteries_cap` helper** in pc_schema:
  - Reads the highest-applicable
    `class_resources.weapon_mastery_count` from the class's
    level_table (rows with `level <= PC.level`).
  - Raises with class + level + cap in the message when
    `len(weapon_masteries) > cap`.
  - Carries forward through gap rows (Paladin L6-L10 inherit
    L5's cap of 2 because the next mastery-count row isn't
    until L11).
  - Wizard / non-mastery classes have no
    `weapon_mastery_count` → cap=0. Declaring any masteries
    raises with a "pick a class that grants Weapon Mastery"
    hint listing the five valid classes.
  - Empty `weapon_masteries` list always legal — even for
    Wizards / non-mastery classes — because declaring zero
    masteries is a no-op (no cap to check).
- **`build_pc_template` calls the cap helper** right after
  validating + normalizing the masteries list. Build-time gate;
  errors surface at fixture load, not in the middle of an
  encounter.
- **One existing test fixed:** `test_nick_mastery.py`'s mock
  Fighter class def didn't declare `weapon_mastery_count` →
  the new cap helper raised. Updated the mock to include
  `weapon_mastery_count: 3` so the existing Nick tests that
  declare 1 mastery still pass. No production code change
  for this fix; just the test fixture.
- **Tests (29 new in `test_other_class_mastery.py`):**
  - Each class YAML loads + correct hit_die per RAW
  - `weapon_mastery_count` progression: Barbarian (2→3 at L4),
    Paladin (2→3 at L11), Ranger (2→3 at L9), Rogue (1→2 at L9)
    — multiple level samples each, including carry-forward
  - `_validate_weapon_masteries_cap` directly: empty list /
    at-cap / under-cap / over-cap / Wizard-no-grant raises /
    cap carries forward through gap rows
  - End-to-end `build_pc_template`: each class at L1 with
    at-cap passes; over-cap raises; Barbarian L4 with 3
    masteries passes; no-masteries-declared works for all
    classes
- 1071 tests pass (+29 new, 1 skip, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- Full class spec content (Rage / Reckless Attack / Lay on
  Hands / Divine Smite / Favored Enemy / Hunter's Mark /
  Sneak Attack / Cunning Action / etc.) — each becomes its
  own PR
- Auto-emission of Expertise choices from the Rogue level
  table (PR #62 wired the mechanic; the class table just
  needs to declare which levels grant Expertise + the
  player-choice infra)
- Subclass support (oaths, archetypes, paths, schools)
- Half-caster / third-caster spell progressions (Paladin /
  Ranger / Arcane Trickster / Eldritch Knight)

---

## Session: 2026-05-27 — Blind Fighting style (PR #63)

**Participants:** Phil, Claude

**Work done:**
- Closes the Fighting Style arc. All 6 styles now ship (Defense /
  Dueling / Archery / GWF / TWF / Blind Fighting). The smallest
  PR of the arc since the vision infrastructure was already in
  place from PR #52.
- **`blind_fighting` added to `_KNOWN_FIGHTING_STYLES`** with a
  comment pointing to the senses-baking mechanism.
- **New `_build_pc_senses_block` helper** in `pc_schema.py`.
  Centralizes assembly of the `senses:` dict (passive_perception
  + any `special` sense entries from class features). When
  `fighting_style == "blind_fighting"`, adds
  `special.blindsight: 10`. Future per-class senses (Devil's
  Sight, etc.) can extend the same helper without touching the
  template construction.
- **`build_pc_template`** now calls `_build_pc_senses_block`
  (passing `fighting_style`) instead of inlining the senses
  dict construction.
- **`cli._build_actor`** unchanged — PR #52 already wired
  template `senses.special.blindsight` → `Actor.blindsight_range_ft`
  loading. Blind Fighting just rides that pathway.
- **Vision integration is automatic.** PR #52's `can_actor_see`
  already honors blindsight as the dominant override (pierces
  Invisible, fog, darkness, magical darkness, self-Blinded
  within range). Blind Fighting actors with blindsight 10
  benefit from this without any vision-system changes.
- **New `f_fs_blind_fighting.yaml`** — user_authored (not in
  SRD CC v5.2.1). Documents the RAW + engine application + the
  two deferred RAW exceptions.
- **Updated existing fighting-style tests** that used
  `blind_fighting` as the "unknown style" id (after PR #53
  swapped it from `two_weapon_fighting`). New genuinely-unknown
  id: `interception` (a real RAW style not yet implemented).
- **Tests (13 new in `test_blind_fighting.py`):**
  - Validation: in known set, validate passes, normalize case
  - `_build_pc_senses_block`: no style → no special; bf → +10;
    other style → no special
  - `build_pc_template`: bf → senses has blindsight; bf
    recorded in derived_from; other style → no special; no
    style → no special
  - `cli._build_actor`: bf → Actor.blindsight_range_ft = 10;
    other style → 0
  - End-to-end vision: bf actor pierces magical darkness on a
    target inside the sphere within 10 ft
- 1042 tests pass (+13 new, 1 skip, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- "Unless it successfully hides from you" RAW exception —
  Blind Fighting RAW says blindsight can't see a creature that
  has succeeded on a Hide check against you. v1 blindsight is
  dominant; tightening would require a per-sense bypass list
  similar to truesight's
  `_PERCEPTION_BYPASSABLE_INVISIBLE_SOURCES`.
- "Total Cover" exception — Total Cover blocks blindsight per
  RAW. v1 doesn't model Total Cover (PR #48 handles half / 3/4
  cover only).
- The Fighting Style arc is now CLOSED. Future PRs in this area
  would be class-feature wirings (e.g., Paladin's variant style
  options) or new "expert" subclasses that select styles.

---

## Session: 2026-05-27 — Skill expertise + magic-item bonuses (PR #62)

**Participants:** Phil, Claude

**Work done:**
- Closes the PR #51 residue. PC schemas now accept skill expertise
  (2×PB on listed skills) and per-skill magic-item bonuses
  (flat add). Both feed `skill_modifier` and passive Perception
  uniformly.
- **`engine/core/skills.py`:**
  - `has_skill_expertise(actor, skill)` — reads
    `template.skill_expertise` (case-insensitive match)
  - `_skill_magic_bonus(actor, skill)` — reads
    `template.skill_bonuses` (dict of skill → flat int)
  - `skill_modifier` extended:
    - Proficient + no expertise → +1×PB (unchanged from PR #51)
    - Proficient + expertise → +2×PB
    - Not proficient + expertise → no PB added (RAW: expertise
      requires proficiency; validation in pc_schema enforces
      this, but the runtime helper degrades gracefully)
    - Magic bonus always added on top
    - Monster-listed totals (`template.skills.<name>`) also get
      the magic bonus added (rare but supported for completeness)
- **`pc_schema` extensions:**
  - New `_validate_skill_expertise(value, proficiencies)`:
    requires expertise entries to be in the proficiencies list.
    Raises with a clear message naming the gap. RAW gate
    enforced at build time.
  - New `_validate_skill_bonuses(value)`: dict shape with int
    values; unknown skills + non-dict + non-int all raise.
  - `build_pc_template` accepts `skill_expertise:` and
    `skill_bonuses:` fields, validates them, bakes onto template
    top-level + `derived_from_pc_schema` block.
- **`_compute_passive_perception` extended** with `skill_expertise`
  and `skill_bonuses` kwargs. Same shape as active `skill_modifier`:
  - Proficient + expertise on Perception → 2×PB in passive
  - Magic bonus on Perception → flat add (regardless of
    proficiency)
  - Old call sites still work (kwargs default to None / {})
- **Tests (38 new in `test_skill_expertise_bonuses.py`):**
  - `has_skill_expertise`: in/not-in/empty/normalized
  - `_skill_magic_bonus`: returns bonus / 0 / unrelated /
    normalized
  - `skill_modifier`: proficient (1× PB), proficient + expertise
    (2× PB), not-proficient (no PB), magic bonus with/without
    proficiency, magic + expertise, monster-listed + magic
  - `_validate_skill_expertise`: None → [], unknown raises,
    expertise-without-proficiency raises (with message),
    expertise-with-proficiency passes, normalized + deduped,
    non-list raises
  - `_validate_skill_bonuses`: None → {}, unknown raises,
    non-int raises, non-dict raises, normalized keys
  - PC schema baking: expertise + bonuses on template top-level
    + derived_from; passive Perception with expertise / with
    magic / with both; unknown skill raises at build; expertise-
    without-proficiency raises at build
  - `_compute_passive_perception` helper directly: no proficiency
    / proficiency-only / expertise / magic-only-no-proficiency
- 1029 tests pass (+38 new, 1 skip, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- Jack of All Trades / Reliable Talent variants — RAW says
  "PB doubled if it isn't already" implying some sources can
  prevent doubling. v1 always doubles when expertise set;
  refinements track sources separately when they land.
- Cloak of Elvenkind RAW grants advantage on Stealth (not flat
  bonus) — fixture authors can model as +5 proxy. A proper
  advantage-grant magic-item path would need a separate hook.
- Item-suite presets (e.g., "rogue with full elvish kit" that
  auto-loads cloak + boots + gloves bonuses) — convenience for
  fixture authors; not a mechanical change.

---

## Session: 2026-05-27 — AI eHP scoring for Darkness (PR #61)

**Participants:** Phil, Claude

**Work done:**
- Closes the PR #60 residue. Darkness is a persistent_aura with
  no damage payload, so `offensive_ehp_persistent_aura`'s damage
  formula returned ~0 — the AI would never pick Darkness. PR #61
  adds a dedicated vision-denial scorer and dispatches via the
  `creates_zone` flag on the aura params.
- **Value model:**
  - Classify all living actors as in-sphere vs out-of-sphere
    allies / enemies via Chebyshev distance from origin (matches
    the engine's grid convention).
  - **Benefit** = in-sphere allies' value, computed as:
    - Defensive: sum over out-sphere enemies who can reach the
      ally (speed + reach), filtering out enemies whose
      truesight pierces. Each contributes
      `enemy_dpr × DELTA_HIT_FROM_ADVANTAGE`.
    - Offensive: one boosted attack per round per in-sphere ally
      (when out-sphere enemies exist), worth
      `ally_dpr × DELTA_HIT_FROM_ADVANTAGE`.
  - **Cost** = mirror computation for in-sphere enemies + out-
    sphere allies.
  - Net = `(benefit - cost) × EXPECTED_AURA_ROUNDS`, clamped to
    0. Darkness that nets negative loses to any damage option;
    clamping avoids accidental sign-flip surprises.
- **Truesight bypass:** Out-sphere enemies with truesight
  covering the in-sphere ally don't contribute defensive value
  (they pierce the darkness). Out-sphere allies with truesight
  covering an in-sphere enemy don't contribute cost. This makes
  the AI correctly value Darkness less when fighting truesight-
  bearing enemies.
- **Reach gating:** Only attackers within `speed + reach` of
  the relevant target contribute. Out-of-reach actors wouldn't
  attack anyway.
- **Dispatch via `creates_zone`:**
  `offensive_ehp_persistent_aura` inspects the aura params; if
  `creates_zone == "magical_dark"`, delegates to
  `offensive_ehp_darkness`. Damage-aura path (Spirit Guardians,
  Moonbeam, etc.) unchanged. Clean fork rather than tangling
  both formulas in one function.
- **New module-level constant:** `DARKNESS_RADIUS_SQUARES = 3`
  (15-ft sphere = 3 squares radius). Currently fixed; would
  generalize when other zone-creating spells with different
  radii land.
- **Helpers (private to the function):** `_in_sphere(actor)`,
  `_truesight_pierces(observer, target)`, `_reach_threat(
  attacker, target)`. Each is a clean local closure — keeps
  the main loop readable.
- **Tests (11 new in `test_darkness_scoring.py`):**
  - `DARKNESS_RADIUS_SQUARES = 3` constant
  - Empty sphere → 0
  - Caster-inside + reachable enemy outside → positive
  - Enemy-inside-only → 0 (cost-only, clamped)
  - Truesight enemy reduces benefit
  - Truesight ally neutralizes cost
  - Out-of-reach enemy → less defensive value
  - Origin default = caster position
  - Multiple allies → more benefit
  - Dispatch: Darkness routes to darkness scorer
  - Dispatch: Spirit Guardians-shape stays on damage scorer
- 991 tests pass (+11 new, 1 skip, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- Blindsight bypass — analogous to truesight; v1 underestimates
  Darkness vs blindsight enemies slightly
- Per-target attack-frequency weighting (multiattack monsters
  contribute more than one-attack-per-turn casters)
- Opportunity-cost subtraction for concentration (caster loses
  other concentration spells; PR #56's pace-aware shape would
  apply)
- Generalize `DARKNESS_RADIUS_SQUARES` to read from aura params
  (radius_ft) when other zone-creating spells with different
  radii land

---

## Session: 2026-05-27 — Darkness spell as persistent_aura (PR #60)

**Participants:** Phil, Claude

**Work done:**
- Closes the PR #52 residue. Magical_dark_zones previously needed
  fixture-authoring; the Darkness spell now creates the zone at
  cast time and the concentration system cleans it up at
  termination. Three pieces of new infra needed integration.
- **`vision._position_in_any_zone` extension:**
  - Added sphere-shape support: `{shape: "sphere", center: [x, y],
    radius_ft: int}`. Chebyshev distance vs `radius_ft // 5`
    matches the engine's grid convention (matches `actors_in_radius`
    from geometry.py).
  - Backward-compatible with the legacy axis-aligned rect shape —
    iterating zones checks `z.get("shape") == "sphere"` first,
    falls back to the rect branch otherwise.
  - Same change benefits all zone types (heavy obscurement / dim
    light / dark / magical dark) since they share this helper.
- **`_persistent_aura` primitive — new `creates_zone` param:**
  - When `creates_zone="magical_dark"` AND `anchor="point"` AND
    origin is resolved: appends a sphere entry to
    `state.encounter.environment.magical_dark_zones`. The zone
    carries `caster_id + action_id` for matching during cleanup.
  - Caster-anchored Darkness raises (RAW: Darkness is point-
    anchored anyway; the moving-with-caster variant would need
    runtime zone-position updates and isn't needed).
  - No origin raises (caller bug — point-anchored without origin
    is undefined).
  - Unknown `creates_zone` values raise with a clear "v1 supports
    only 'magical_dark'" message. Forward-compat for future
    zone-creating spells.
- **`concentration.end_concentration` extension:**
  - After scrubbing matching active_modifiers, applied_conditions,
    and persistent_auras, ALSO scrubs environment
    `magical_dark_zones` whose `caster_id + action_id` match.
  - Statically-declared zones (fixture-authored, no caster_id
    stamp) are preserved untouched — the cleanup filter is
    explicit about matching both fields.
  - Increments the same `removed` counter for consistency with
    other cleanup paths.
- **`f_darkness.yaml`:** SRD CC v5.2.1 spell.
  `granted_by: c_wizard L3` (2nd-level spell access).
  `action_template`: persistent_aura with sphere/15-ft
  radius/point anchor, `ability: none` (no save), empty
  on_fail/on_success (no damage), `creates_zone: magical_dark`.
- **Tests (18 new in `test_darkness_spell.py`):**
  - Sphere zone detection: center, in-radius, just-outside,
    rect backward compat, mixed rect+sphere, via
    `is_in_magical_dark_zone`
  - `_persistent_aura` creates_zone: succeeds with magical_dark
    + sphere center/radius/stamping; raises on caster anchor;
    raises on unknown zone type; no-zone-when-omitted
  - `end_concentration`: drops caster's Darkness zone; preserves
    statically-declared zones; two casters independent
  - End-to-end vision: no-darkvision blocked, ordinary darkvision
    blocked, truesight out-of-range blocked, truesight in-range
    pierces, blindsight pierces
- 980 tests pass (+18 new, 1 skip, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- "Centered on a creature you choose" variant — Darkness RAW lets
  the spell anchor on an object/creature; v1 point-anchors at
  coordinates only
- Devil's Sight (Warlock invocation that bypasses magical
  darkness without truesight) — same PR #52 deferred
- AI scoring for Darkness — `offensive_ehp_persistent_aura`
  currently scores damage auras; Darkness's defensive vision-
  denial value needs its own estimator (analogous to how Hide
  scores defensively in PR #59)
- Other zone-creating spells (Hunger of Hadar, Cloudkill) — the
  `creates_zone` hook is generic enough to extend; tracked

---

## Session: 2026-05-27 — AI eHP scoring for Hide + Search (PR #59)

**Participants:** Phil, Claude

**Work done:**
- Closes two scoring residues at once: PR #48 (Hide had no scorer,
  defaulted to 0) and PR #55 (Search relied on gated emission with
  no real eHP value). Both now have first-class eHP scoring that
  competes against weapon_attack candidates on the same scale.
- **Hide value model** (`offensive_ehp_hide`):
  - Gate check: returns 0 if neither heavy obscurement nor 3/4+
    cover is satisfied (matches the `_execute_hide` runtime guard).
  - `p_success` = probability the Stealth roll (d20 + skill_mod)
    meets DC 15.
  - `p_evade_perception` = fraction of enemies whose passive
    Perception is below the expected stealth_total (those who
    can't auto-spot via PR #51's check).
  - Offensive value = own `estimate_per_attack_damage(actor)` ×
    `DELTA_HIT_FROM_ADVANTAGE` (one boosted attack from Invisible
    advantage next turn — RAW: Hide ends on attack, so we only
    score one swing).
  - Defensive value = sum over enemies in their own threat range
    (speed + reach) of `enemy_per_attack_damage ×
    DELTA_HIT_FROM_ADVANTAGE` (each enemy attacks at disadvantage
    while we're Invisible).
  - Total = `(offensive + defensive) × p_evade × p_success`.
- **Search value model** (`offensive_ehp_search`):
  - For each Hide-source-Invisible enemy, computes p_reveal =
    P(d20 + perception_mod >= stealth_total).
  - Multiplies by own per-attack damage (proxy for "value
    unlocked by being able to target them next turn").
  - Spell-source Invisible explicitly NOT counted (only Hide is
    Perception-bypassable per RAW).
  - Conservative: doesn't subtract lost current-turn DPR — that
    opportunity cost is captured implicitly by competing against
    weapon_attack on the same scale.
- **New module helpers** exposed for test reuse:
  - `_stealth_success_probability(mod)` → P(d20+mod >= 15)
  - `_expected_stealth_total(mod)` → 11 + mod (success-conditional
    d20 average proxy)
  - `HIDE_DC = 15` constant
- **`score_candidate` dispatch** extended with two new branches:
  `kind='hide'` and `kind='search'`. Each falls through to the
  new scorer.
- **`pipeline.generate_candidates`** now emits `kind='search'`
  candidates for explicit `type: search` actions on the actor's
  template (the built-in Search continues to be injected by
  `built_in_actions_for` with the same gated-emission logic from
  PR #55). The hide candidate comment updated to reflect that PR
  #59 brings real scoring.
- **Tests (23 new in `test_hide_search_scoring.py`):**
  - `_stealth_success_probability`: DC constant, mod 0 → 6/20,
    mod +5 → 11/20, mod +15 → auto-pass, negative mod → low prob,
    very-negative → 0
  - `offensive_ehp_hide`: gate-fail returns 0, no-enemies returns
    0, all-auto-spot returns 0, heavy obscurement + evading enemy
    → positive, 3/4 cover also triggers, higher stealth → higher
    score, out-of-range enemies don't contribute to defensive
  - `offensive_ehp_search`: no-hidden returns 0, no-attacks
    returns 0, low-stealth + high-perception → high score, high
    stealth → lower score, multiple enemies sum, spell-Invisible
    not counted, mixed-Invisible only Hide counted
  - `score_candidate`: kind='hide' and kind='search' route
    correctly
  - `pipeline`: explicit search action emits candidate
- 962 tests pass (+23 new, 1 skip, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- Opportunity-cost subtraction for Search (lost current-turn DPR)
- Per-enemy weighted defensive value for Hide (each enemy's
  auto-spot probability, not coarse fraction)
- Expected-stealth-total based on success-conditional d20 average
  (v1 uses 11+mod proxy)
- Per-target enemy DPR estimation including their actual
  movement-to-engage capability (v1 assumes if in range, they
  attack)

---

## Session: 2026-05-26 — Cleave / Push / Slow masteries (PR #58)

**Participants:** Phil, Claude

**Work done:**
- Closes the Weapon Mastery v1 arc by shipping the three remaining
  properties. `DEFERRED_MASTERIES` is now empty; all 8 v1 masteries
  ship (Vex / Sap / Topple / Graze from PR #54, Nick from PR #57,
  Cleave / Push / Slow here).
- Pre-scoped twice: all three at once (vs piecemeal), and "trust
  weapon spec, no size gate" for Push (avoids the larger Actor.size
  refactor).
- **`KNOWN_MASTERIES` extended** to include cleave/push/slow.
  `DEFERRED_MASTERIES` is now `frozenset()` — kept as a frozenset so
  future RAW additions can slot in without changing the validator
  branching.
- **`engine/core/geometry.push_creature(pusher, target, distance_ft)`**
  new helper: snaps to 8-direction unit vector via `unit_direction`,
  moves the target in 5-ft steps. v1 doesn't check collisions or
  map bounds — trusts the open-battlefield assumption.
- **`_mastery_cleave`** implementation:
  - Per-turn dedup via `actor._cleave_fired_this_turn` attribute
    (cleared by `reset_turn`)
  - Finds a candidate second target: living enemy ≠ primary,
    within 5 ft of primary AND within attacker's reach (v1: 5 ft
    melee assumption)
  - Sub-attack via `_invoke_subprimitive` reuses the weapon's
    own pipeline. `_find_attacker_weapon_for_cleave` scans the
    actor's template.actions for the highest-DPR weapon action
    with mastery=cleave to source the pipeline (the mastery
    params don't carry the full weapon spec, so we look it back
    up).
  - Logs `weapon_mastery_skipped` (reason: already_fired_this_turn
    OR no_second_target OR no_weapon_action_found) or
    `weapon_mastery_applied` with primary + second target ids.
- **`_mastery_push`** implementation:
  - On hit, calls `geometry.push_creature(actor, target, 10)`
  - Logs `weapon_mastery_applied` with pushed_ft + from/to
    positions
- **`_mastery_slow`** implementation:
  - No-op (with skip event) if target already has `_slow_data`
    set — RAW "doesn't exceed 10 ft if hit multiple times"
  - Direct mutation: `target.speed["walk"] = max(0, current - 10)`
  - Stashes `_slow_data: {source_id, original_speed,
    applied_at_round}` on target
  - Logs reduction amount + new speed (handles the speed-5 →
    speed-0 case correctly, logging actual reduction = 5)
- **`expire_slow_from_source(source_actor_id, state)`** public
  helper: scans all actors for `_slow_data` whose source_id
  matches; restores `original_speed` and clears the record. Returns
  count restored.
- **Runner integration**: `_run_actor_turn` calls
  `expire_slow_from_source(actor.id, state)` at turn start (right
  after `expire_modifiers`). This is the "until start of slow-
  applier's next turn" hook.
- **`reset_turn` extension**: clears `_cleave_fired_this_turn` if
  set. Attribute-style (not dataclass field) — same convention as
  PR #57's `_free_actions_fired_this_turn`.
- **`apply_mastery_effects` threading**: gained a `bus=None`
  parameter so Cleave's sub-attack can pass a real bus to
  `_invoke_subprimitive` (which needs it for `bus.emit("attack_roll")`).
  Falls back to a `_NullEventBus` stub when bus is None (direct
  test invocation). `primitives._attack_roll` updated to pass bus.
- **Tests (25 new in `test_cleave_push_slow.py`):**
  - Registry: cleave/push/slow in KNOWN; DEFERRED empty
  - `push_creature` helper: east, west, diagonal, stacked
    (no-op), partial distance
  - Cleave: no-second-target, second-target-fires-sub-attack,
    once-per-turn-gate, reset_turn-clears-gate, ally-doesn't-
    qualify, actor-without-cleave-no-op
  - Push: fires-on-hit, NOT-on-miss, diagonal
  - Slow: reduces-speed, doesn't-stack, clamped-at-zero,
    NOT-on-miss, expire-restores, expire-wrong-source-noop,
    expire-multiple-targets
- **One existing test updated**: `test_weapon_mastery.py`'s
  `test_known_v1_set` (added cleave/push/slow to expected set);
  `test_deferred_mastery_raises` skips when DEFERRED is empty
  (vacuously-passes pattern preserved for future re-additions).
- 939 tests pass (+25 new, 1 skip, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- Heavy-weapon gate on Cleave + Graze (RAW restricts these to
  Heavy melee weapons; v1 trusts the weapon spec)
- Size gate on Push (RAW: Large or smaller targets). Needs an
  `Actor.size` field that doesn't exist yet.
- Forced-movement collision handling — Push currently moves the
  target whether or not the destination is occupied
- Reach passthrough for Cleave (currently assumes 5 ft melee
  reach; weapons with reach > 5 ft should propagate that to
  the candidate-finding step)
- Per-action mastery tracking (Cleave currently identifies the
  source weapon via DPR proxy; tracking which action fired this
  attack would be more direct)

---

## Session: 2026-05-26 — Nick weapon mastery + free-phase (PR #57)

**Participants:** Phil, Claude

**Work done:**
- Closes two residues at once: the Nick mastery from PR #54
  (deferred because it needed slot-semantics integration) and
  the Nick-as-TWF-closer from PR #53 (deferred to the Weapon
  Mastery arc). Pre-scoped to the "new free slot + runner phase"
  model — invasive-pipeline-chaining and slot-skip-without-runner-
  changes both rejected as either too restructuring or too
  partial.
- **`nick` promoted from DEFERRED to KNOWN.** Module docstring
  updated to list 5 properties; DEFERRED set shrinks to
  Cleave/Push/Slow.
- **New `_nick_active(off_hand_spec, weapons, weapon_masteries)`
  helper** in pc_schema.py. Returns True iff the actor knows
  Nick AND at least one wielded Light melee weapon has
  `mastery: nick`. Fail-closed on missing data (None weapon
  list, None masteries, etc.).
- **`build_pc_template` integration:** when `_nick_active` is
  True, the off-hand action gets `slot: "free"` and a
  `nick_active: true` tag (for telemetry / debugging). When
  inactive, off-hand stays `slot: "bonus_action"` (PR #53
  default).
- **New runner `_run_free_phase` method** between action and
  bonus_action phases:
  - Scans `actor.template.actions` for entries with
    `slot == "free"` AND `type == "weapon_attack"` (v1 only —
    other free action types deferred until a non-attack free
    action exists)
  - For each, picks the dial-preferred enemy via the same
    `pick_target` path as movement
  - Fires the action via `pipeline.execute`
  - Per-turn dedup set `_free_actions_fired_this_turn`
    prevents double-firing in multi-pass turns (Action Surge
    re-runs the action phase, which could otherwise re-fire
    Nick)
  - Logs `free_action_fired` or `free_action_skipped` events
- **`reset_turn` extension** in state.py: clears the per-turn
  dedup set on each new turn. Attribute-style (vs dataclass
  field) so we don't force a schema change for runner-only
  bookkeeping.
- **`apply_mastery_effects` dispatch unchanged:** Nick has no
  per-attack effect, so the existing if-elif chain skips it
  cleanly (passes through to no-op). Pinned with a test.
- **Bug discovered during integration:** the runner uses
  `EncounterRunner` class, not `Runner`. Test imports fixed;
  no production code change needed.
- **Tests (20 new in `test_nick_mastery.py`):**
  - `nick` in KNOWN_MASTERIES, not in DEFERRED_MASTERIES
  - `_nick_active` helper: off-hand-with-nick TRUE,
    primary-with-nick TRUE, neither TRUE, actor-doesn't-know
    FALSE, empty masteries FALSE, None masteries FALSE,
    non-light primary FALSE, ranged primary FALSE
  - `build_pc_template`: Nick active → slot=free + nick_active,
    Nick inactive (no mastery known) → slot=bonus_action,
    Nick inactive (no weapon has nick) → slot=bonus_action,
    no off-hand → no off-hand action
  - `apply_mastery_effects` with id=nick: no modifiers added,
    no events logged (clean no-op)
  - Runner free-phase end-to-end: fires auto with event,
    skips when no in-reach enemy, doesn't consume action or
    bonus_action slot, silent skip when no free actions,
    no double-fire on second invocation
- **Fixture:** `nick_mastery_encounter.yaml` — L1 Fighter
  dual-wielding scimitars (both with `mastery: nick`),
  declaring `weapon_masteries: [nick, vex, topple, graze]`.
  Demonstrates the action → free → bonus_action flow per turn.
- 914 tests pass (+20, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- AI scoring for free actions (vs always-fire). Free actions
  always fire when eligible in v1 because Nick is the only
  consumer and "always fire" is RAW for Nick. When other free
  actions land (e.g., subclass features that auto-trigger),
  scoring may need to distinguish.
- Cleave / Push / Slow — remaining deferred masteries
- Class-level "masteries known" cap enforcement
- Free-phase support for non-attack action types

---

## Session: 2026-05-26 — Pace-aware reactions (PR #56)

**Participants:** Phil, Claude

**Work done:**
- Closes the always-fire-reactions residue from PR #45 (reaction
  infra) and PR #46 (Counterspell). Pre-scoped tight: reactions
  only; Hide / Search AI scoring deferred to a future PR.
- **`engine/core/feature_pacing.py` extension:**
  - New `REACTION_SLOT_BASE_COSTS` dict (levels 1-9 with eHP
    values calibrated to spell potency). Tunable per-call.
  - New `reaction_cost_ehp(slot_level, slots_remaining,
    encounters_remaining, base_cost_per_level=None)` — same
    `scarcity × urgency × base_cost` shape as
    `feature_use_cost_ehp`, slot-level-aware.
- **New `engine/ai/reaction_scoring.py` module:**
  - `_dice_avg` helper: parses dice expressions like "2d6" → 7.0
  - `_estimate_attack_damage(attacker)` — scans
    `template.actions` for weapon_attack actions and returns the
    highest expected damage (dice avg + flat modifier)
  - `shield_value_ehp` — uses `_estimate_attack_damage` because
    the Shield condition (`shield_would_help`) already guarantees
    the attack converts hit → miss; value = avoided damage.
    Returns `float("inf")` when attacker is missing (defensive)
    or has no scorable attacks (fall back to always-fire).
  - `counterspell_value_ehp` — reads `event_data.spell_slot_level`
    (with `spell_level` fallback for test-shaped event_data) and
    returns the corresponding base cost. RAW intuition: same-
    level counterspell trades value-for-value.
  - `hellish_rebuke_value_ehp` — 2d10 fire (avg 11) with ~50%
    save rate → 8.25 eHP; modulated by attacker's fire
    resistance / immunity / vulnerability. Returns inf when
    attacker is missing.
  - `estimate_reaction_value_ehp` dispatch:
    `a_shield` → `shield_value_ehp`,
    `a_counterspell` → `counterspell_value_ehp`,
    `a_hellish_rebuke` → `hellish_rebuke_value_ehp`,
    anything else → `float("inf")` (forward-compat for unscored
    reactions; preserves v1 always-fire semantics for them).
- **`reactions.try_use_reaction` pace gate** added after the
  spell-slot + feature-use availability checks but BEFORE pipeline
  execution. Compares `cost` to `value` from the module above;
  if cost > value, log `reaction_skipped_pace` (with cost/value/
  slot diagnostics) and return False. Resources NOT consumed on
  skip. Bypassed when:
  - `slot_level == 0` (no slot → no opportunity cost; OA-shape
    reactions always fire on availability)
  - `action.signature_reaction == True` (escape hatch; rarely
    used but available for hand-tuned monsters)
- **One discovered bug fixed during integration:** the initial
  `counterspell_value_ehp` read `event_data.spell_level` but the
  pipeline emits `spell_slot_level`. Added both-key fallback for
  robustness (some tests use the shorter key). Pinned with
  `test_fallback_to_spell_level_key`.
- **Test default `encounters_remaining_today = 3`** kept by design
  — matches the framework's mid-day baseline. All existing
  reaction tests pass cleanly under the new gate at default
  slot loadouts.
- **Tests (36 new in `test_pace_aware_reactions.py`):**
  - `reaction_cost_ehp` formula: zero-slot-level, zero-slots,
    scarcity scales cost up, urgency scales cost up, last-
    encounter cost drop, higher slot levels cost more, custom
    base-cost map override, slot-level-above-table clamps
  - `shield_value_ehp`: missing attacker → inf, attacker with no
    attacks → inf, DPR estimate correct, picks highest among multi
  - `counterspell_value_ehp`: spell_slot_level used, fallback to
    spell_level, default-when-missing, high-level clamp
  - `hellish_rebuke_value_ehp`: missing attacker → inf, default
    8.25, immunity zeros, resistance halves, vulnerability doubles
  - `estimate_reaction_value_ehp` dispatch: unknown reaction →
    inf, each known reaction dispatches correctly
  - `try_use_reaction` gate: cost > value skips with no slot
    consumption, value > cost fires, last-encounter lowers cost,
    `signature_reaction: true` bypasses, many slots lowers cost,
    skip event diagnostics complete
- 894 tests pass (+36, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- Calibration of `REACTION_SLOT_BASE_COSTS` against
  Treantmonk damage rankings (current values are eyeballed)
- AI scoring for Hide and Search (real eHP, not just gated
  emission) — closes residue from PRs #48 and #55
- More reaction-aware value estimators when new reactions land
  (e.g., Silvery Barbs, Resilient subclass features)
- "Boss alarm" / Difficulty-aware activation — let the AI
  recognize a high-CR enemy as worth burning reactions on even
  when pacing would normally suppress them

---

## Session: 2026-05-26 — Active Search action + AI gated emission (PR #55)

**Participants:** Phil, Claude

**Work done:**
- Closes the last vision-arc residue (Active Perception search-as-
  action). First non-damage information action in the engine.
  Pre-scoped twice up front: scrub-on-reveal (global, not per-
  observer) + gated emission (vs always-emit-with-zero-scoring).
- **New `BUILT_IN_SEARCH`** (type=search, slot=action) in
  basic_actions.py. Empty pipeline; dispatch handled in
  pipeline.execute via the new `_execute_search` branch.
- **Restructured `built_in_actions_for`:** Dodge / Disengage / Help
  remain gated by threat range + move-to-engage. Search is
  NOT — it's an information action, valuable even when the actor
  would otherwise close distance (you might Search to find what
  to close on). The internal `_has_unspotted_hidden_enemy` gate
  is the only filter Search needs: "is there a Hide-source hider
  whose stealth_total beats my passive Perception?" Otherwise
  emit nothing.
- **`_execute_search` implementation:** for each living enemy with
  a Hide-source `co_invisible`, roll d20 + Perception modifier
  (via PR #51's `skill_modifier(actor, "perception")`) vs the
  enemy's recorded `stealth_total`. On success, scrub the Hide-
  source condition from the target — uses identity (`c is
  hide_cond`) to surgically remove just that condition entry,
  leaving any spell-source Invisible intact.
- **Spell-source Invisible NOT affected by Search.** RAW: only
  Hide is bypassable by Perception. Pinned with two tests:
  spell-only enemy isn't even rolled against; mixed-source enemy
  only loses the Hide entry.
- **Reveal is global (v1 simplification).** "Spotted means
  spotted" — one mutation, all observers see. Per-observer
  `spotted_by:` tracking deferred.
- **Tests (21 new in `test_active_search.py`):**
  - `_has_unspotted_hidden_enemy` helper: no hidden / above pp /
    at-or-below pp / spell-Invisible / dead enemy / ally / multi-
    enemy
  - Built-in emission: no enemy / above-passive emits / auto-spot
    case doesn't / bonus slot empty / explicit-action suppresses
  - `_execute_search`: no targets / failed check / successful
    reveal / proficiency adds PB / no proficiency just ability /
    spell-Invisible untouched / mixed-source surgical scrub /
    multi-enemy independence
  - End-to-end via `can_actor_see`: hidden → invisible; after
    successful Search → visible
- **Fixture:** `active_search_encounter.yaml` — proficient elf
  ranger (Perception PB +2, total +4) + non-proficient human
  fighter (mod +0) hunting a hidden goblin with stealth_total 18.
  Demonstrates the proficiency-helps-Search payoff.
- 858 tests pass (+21, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- Per-observer `spotted_by:` reveal tracking (vs global scrub)
- Real eHP scoring for Search (probability_of_reveal × DPR_unlocked)
  vs gated emission
- Explicit sight-range gate on Search (currently any-encounter)
- Search non-creature targets (find object, decipher map, etc. —
  RAW Search can hunt for anything "not obvious")
- Hide-source Invisible reveal-on-noise (spellcasting verbal
  components break Hide; only attack break is currently modeled)

---

## Session: 2026-05-26 — Weapon Mastery v1 (PR #54)

**Participants:** Phil, Claude

**Work done:**
- The biggest 2024 PHB feature. Pre-scoped twice:
  - **4 properties** (Vex / Sap / Topple / Graze), not all 9. Skips
    Cleave (extra attack — needs sub-attack gen), Push (movement),
    Slow (speed reduction with duration), Nick (TWF residue).
  - **Fighter only**. Barbarian / Paladin / Ranger / Rogue wirings
    deferred to per-class PRs.
- **New `engine/core/weapon_masteries.py` module** centralizes:
  - `KNOWN_MASTERIES` frozenset (v1 set)
  - `DEFERRED_MASTERIES` frozenset (Cleave/Push/Slow/Nick — listed
    so validators can surface a clearer "deferred, not unknown"
    error when authors try them)
  - `validate_mastery` + `validate_mastery_list` + `actor_knows_mastery`
  - Per-property functions: `_mastery_vex`, `_mastery_sap`,
    `_mastery_topple`, `_mastery_graze`
  - `apply_mastery_effects` dispatch helper called from `_attack_roll`
- **`Actor.weapon_masteries: list`** field — the properties the
  actor *knows*. Distinct from a weapon's intrinsic mastery
  property (which is on the weapon spec).
- **`cli._build_actor`** loads `weapon_masteries` from actor_spec
  override → template top-level → [].
- **`pc_schema`**:
  - Accepts `pc_spec.weapon_masteries: [vex, sap, topple, graze]`
  - Validates against KNOWN_MASTERIES via `validate_mastery_list`
  - Bakes onto template top-level + `derived_from_pc_schema`
  - v1 does NOT enforce the class-level "masteries known" cap from
    level table (Fighter L1: 3, L4: 4, L10: 5, L16: 6). Tracked
    as a future tightening.
- **Weapon spec extension**: `mastery: <id>` on the weapon dict.
  `_build_weapon_action` validates the id and bakes a self-
  contained `mastery: {id, ability_mod, damage_type, save_dc}`
  sub-dict into attack_roll params. Self-contained means the
  runtime helper doesn't need to re-read the actor template;
  everything it needs is in the params dict.
- **Ordering fix in `_attack_roll`**: dispatch fires AFTER lifetime
  expiry, not before. The expiry sweep includes
  `owner_made_attack` which consumes `per_owner_attack` modifiers.
  If we registered Vex *before* expiry, it'd consume on the
  triggering swing instead of the next one. Pinned with the Vex
  test confirming `per_owner_attack` lifetime is set.
- **Per-property implementations:**
  - **Vex** — registers `advantage_for_self` attack_modifier on
    actor with `per_owner_attack` lifetime + `when:
    attacker_is_self`. RAW says "next attack against this target,"
    but v1 uses the simpler "next attack period" semantics —
    practically equivalent for sequential-target AI. Tracked as
    a future refinement.
  - **Sap** — registers `disadvantage_for_self` on TARGET (owner_id
    = target.id) with same lifetime. Fires when target attacks next.
  - **Topple** — rolls CON save (d20 + target.con_save vs DC
    8+ability_mod+PB). On fail, applies Prone via the standard
    apply_condition flow (so condition's modifiers wire up
    correctly). Save events logged.
  - **Graze** — on miss, deals `ability_mod` damage of weapon's
    damage type. Mirrors `_damage`'s resistance/vuln/immunity
    handling. 0 or negative ability_mod → no damage (RAW: Graze
    explicitly mentions "ability modifier" which is 0 at +0).
- **f_weapon_mastery.yaml** feature file. Fighter class def already
  declared `weapon_mastery_count` per level (3/4/5/6) and the
  feature reference — this PR fills in the feature definition.
- **Tests (36 new in `test_weapon_mastery.py`):**
  - Validators (known set, normalize case, deferred raises with
    clear message, unknown raises, list deduplicates/preserves
    order, empty cases, non-list raises)
  - `actor_knows_mastery` (in-list, not-in-list, empty list, empty id)
  - PC schema integration (unknown raises, deferred raises, baked on
    template, in derived_from, empty when not specified)
  - `_build_weapon_action` (no mastery omits key, mastery baked with
    full subdict including correct ability_mod / damage_type /
    save_dc, unknown mastery raises)
  - Vex (hit registers correct modifier, miss does NOT register,
    actor without vex no-op, crit also triggers)
  - Sap (hit registers on target, owner_id = target.id, miss no-op)
  - Topple (failed save applies Prone via apply_condition,
    passed save does not, miss doesn't force save)
  - Graze (miss deals ability_mod damage, hit does not, zero mod
    no damage, resistance halves, immunity zeros)
  - Dispatch no-ops (None params, empty params)
- **Fixture:** `weapon_mastery_showcase_encounter.yaml` — four L1
  Fighters each wielding a different weapon (Rapier/Mace/Maul/
  Greatsword) with each weapon's mastery active. All four know
  all four masteries (over the L1 cap of 3 — v1 doesn't enforce).
  Dummies have low CON saves for the Topple demo.
- 837 tests pass (+36, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- Cleave (extra attack on hit with Heavy melee — needs sub-attack
  generation)
- Push (forced movement primitive)
- Slow (speed reduction with duration tracking)
- Nick (off-hand attack as part of Attack action — bridges to the
  TWF residue from PR #53)
- Class-level "masteries known" cap enforcement (vs trust-the-
  spec v1)
- Per-target Vex lifetime (RAW: expires only on next attack
  against same target; v1 expires on any next attack)
- Barbarian / Paladin / Ranger / Rogue Weapon Mastery wirings

---

## Session: 2026-05-26 — Two-Weapon Fighting + off-hand mechanics (PR #53)

**Participants:** Phil, Claude

**Work done:**
- Closes the Fighting Style arc with the fifth style. Pre-scoped to
  "off-hand weapon + TWF style + light gate" — Nick weapon mastery
  (which lets the off-hand attack happen as part of Attack action,
  freeing the bonus action) deferred to the Weapon Mastery PR.
- **New `two_weapon_fighting` Fighting Style** added to
  `_KNOWN_FIGHTING_STYLES`. Updated two existing
  `test_fighting_style` tests that used `two_weapon_fighting` as
  the "unknown" id (it's now known) → swapped to `blind_fighting`.
- **PC schema accepts `off_hand_weapon:`** — a single weapon spec
  (not a list). Validated by `_validate_off_hand_weapon`:
  - off-hand must be melee (no `range_ft`)
  - off-hand must have `light: true`
  - off-hand must NOT be `two_handed: true`
  - at least one primary `weapons:` entry must also be Light melee
- **`_build_weapon_action(off_hand=True)`** returns an action with:
  - `slot: bonus_action` (so the runner routes it to the bonus pool)
  - id suffixed `_offhand` (e.g., `a_shortsword_offhand`)
  - name suffixed " (Off-Hand)"
  - damage modifier = 0 by default (RAW: no ability mod on off-hand)
  - With `fighting_style: two_weapon_fighting`: damage modifier =
    ability mod (RAW: TWF lets you add the modifier)
  - With negative ability mod: still applies (RAW: negatives always
    apply, even to off-hand)
  - Attack bonus = ability mod + PB (unchanged — only damage is
    reduced for off-hand)
- **Dueling exclusion on off-hand**: even when both Dueling and TWF
  styles are taken, Dueling's +2 does NOT apply to the off-hand
  attack. Logically Dueling and TWF are incompatible Fighting
  Style choices (you can only pick one), but the
  `_build_weapon_action(off_hand=True)` path defensively skips
  the Dueling branch via the `not off_hand` guard. Pinned with a
  specific test.
- **Documented v1 limitation: Dueling vs. dual-wield main-hand
  exclusion** is NOT enforced. Per RAW, a dual-wielder with
  Dueling shouldn't get the +2 on their main-hand light weapon
  ("no other weapons"). v1 still lets them stack — tracked as a
  future RAW-tightness PR. The bigger question is whether someone
  would ever pick Dueling+TWF together, since the styles are
  mutually exclusive in practice.
- **YAML feature file:** new
  `schema/content/features/f_fs_two_weapon_fighting.yaml`. Tagged
  `source: user_authored` because the 2024 PHB version is not in
  SRD CC v5.2.1. Slots into the Fighting Style architecture from
  PR #38.
- **Tests (27 new in `test_two_weapon_fighting.py`):**
  - Style validation (known, validate passes)
  - Off-hand validation: valid passes, must be melee, must be
    light, must not be two_handed, primary must include Light
    melee, mixed-primary passes if one qualifies, non-dict raises
  - `_build_weapon_action(off_hand=True)` semantics: slot,
    id suffix, name suffix, damage mod 0 without TWF, damage mod
    +ability with TWF, negative ability mod applies regardless,
    attack bonus includes ability+PB, Dueling doesn't apply
  - End-to-end via `build_pc_template`: no off-hand → no extra
    action; off-hand → bonus-action attack generated; without TWF
    → damage mod 0; with TWF → damage mod +3; main-hand still has
    ability mod with TWF; non-light primary rejected; 2H primary
    rejected; 2H off-hand rejected
  - Dueling vs dual-wield main-hand exclusion (documents the v1
    limitation)
- **Fixture update:** `fighting_styles_showcase_encounter.yaml`
  now has FIVE fighters (Defense / Dueling / Archery / GWF / TWF)
  vs five identical dummies. TWF fighter dual-wields shortswords
  and demonstrates the off-hand bonus-action attack flow.
- 801 tests pass (+27, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- **Nick weapon mastery** — bridges to the Weapon Mastery PR.
  Lets the off-hand attack happen as part of the Attack action,
  freeing the bonus action. Pairs with TWF (stack additively).
- **Dueling vs. dual-wield main-hand exclusion** — v1 doesn't
  enforce the RAW "no other weapons" gate at the main-hand level
  when an off_hand_weapon is also declared
- **Blind Fighting** — last user-authored Fighting Style not yet
  implemented (would add blindsight 10 ft to the actor — very
  small follow-on)
- **Off-hand for ranged weapons** — RAW lets you off-hand a Light
  ranged weapon (hand crossbow) with another Light ranged weapon.
  v1 gates off-hand to melee only.

---

## Session: 2026-05-26 — Truesight + Blindsight + Magical darkness (PR #52)

**Participants:** Phil, Claude

**Work done:**
- Closes the vision-type arc. Pre-scoped twice up front:
  - Magical darkness as a separate `magical_dark_zones` field
    (parallel to `dark_zones`), not a `magical: true` flag on
    existing dark zones. Keeps the one-helper-per-zone-type
    symmetry; cleaner precedence in `can_actor_see`.
  - Truesight bypasses Invisible + magical darkness + ordinary
    darkness. Does NOT bypass heavy obscurement — RAW says
    truesight pierces magic, not physical obscuring substances.
- **Two new Actor fields:** `truesight_range_ft` + `blindsight_range_ft`
  (both int, default 0). Loaded by `cli._build_actor` with the same
  precedence pattern as `darkvision_range_ft` (actor_spec override →
  `template.senses.special.<name>` → 0). Refactored the load logic
  into an inner `_load_sense(name)` helper so the three sense
  fields don't duplicate the dispatch.
- **New environment field `magical_dark_zones`** + helper
  `vision.is_in_magical_dark_zone`. Same axis-aligned-rect shape as
  the other zone types.
- **`can_actor_see` precedence reorganized into seven explicit
  steps** with the new vision-type gates:
  1. Self-sees-self short-circuit (unchanged)
  2. **Blindsight bypass** (within range) — dominant override.
     Pierces Invisible, fog, darkness, magical darkness, AND
     self-Blinded (per RAW: blindsight perceives without sight).
  3. Blinded observer (only fires if step 2 didn't bypass).
  4. Invisible target — **Truesight in range** bypasses both
     Hide-source and spell-source. PR #51's passive-Perception
     auto-spot still handles Hide-source for non-truesight observers.
  5. Heavy obscurement — Truesight does NOT bypass (RAW: fog is
     physical). Only Blindsight bypasses, handled at step 2.
  6. **Magical darkness zones** — only Truesight pierces. Ordinary
     darkvision does NOT (this is the whole point of the Darkness
     spell vs darkvision in 5e RAW).
  7. Ordinary darkness — Truesight OR Darkvision in range.
- **Why fog blocks truesight but darkness doesn't:** The 5e 2024
  Truesight RAW lists what it bypasses: "magical and nonmagical
  darkness," "invisible creatures and objects," "visual illusions,"
  and shapechanger original-form. Notably absent: physical
  obscuring substances. Fog, leaves, dense foliage — those are
  geometry, not deception. Pinned with a specific test.
- **Why blindsight overrides self-Blinded:** Blindsight perceives
  surroundings *without* relying on sight (echolocation /
  tremorsense / etc.). So even if your sight is suppressed, the
  blindsight sense still works. Pinned with a specific test where
  observer is blinded AND target is invisible AND in magical
  darkness — blindsight within range still returns True.
- **Tests (29 new in `test_truesight_blindsight.py`):**
  - Magical-darkness zone detection
  - `cli._build_actor` loads truesight + blindsight from template
    senses or actor_spec overrides
  - Blindsight: bypasses Invisible, fog, darkness, magical
    darkness, self-Blinded; out-of-range falls back; exact-range
    boundary works
  - Truesight: bypasses spell-source Invisible (which passive
    Perception can't), bypasses Hide-source Invisible, bypasses
    magical darkness, bypasses ordinary darkness (substitutes for
    DV), does NOT bypass fog, out-of-range falls back, exact-
    range boundary works
  - Magical darkness specifics: ordinary DV blocked, observer-in-
    magical-dark with truesight sees out, observer-in-magical-
    dark with only DV blind, overlapping regular+magical zones
    use magical's strictness
  - Precedence: blindsight beats self-Blinded AND Invisible AND
    magical darkness all at once; truesight + fog still blocked;
    no-senses + magical darkness blocked; self-sees-self short-
    circuits even with senses
- **Fixture:** `vision_types_showcase_encounter.yaml` — four
  observers (human guard / dwarf darkvision / paladin truesight /
  bat familiar blindsight) facing an invisible wizard inside a
  magical-darkness zone. Each observer's vision result on the
  invisible-wizard target is the showcase: only paladin (truesight)
  and (theoretically) bat-if-within-range can see them.
- 774 tests pass (+29, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- Devil's Sight (Warlock invocation) — bypasses magical darkness
  without truesight; needs a new flag distinct from truesight
  (probably `magical_darkness_bypass: bool` on Actor)
- Illusion auto-detection (truesight RAW part)
- Shapechanger original-form perception (truesight RAW part)
- Magical-darkness as a persistent_aura cast effect (when the
  Darkness spell lands, it should auto-declare a magical_dark_zone
  rather than fixture-authoring one)

---

## Session: 2026-05-26 — Skill proficiencies + passive Perception (PR #51)

**Participants:** Phil, Claude

**Work done:**
- Closes the Hide arc with the detection-side mechanic. Pre-scoped
  to "Stealth + passive Perception only" — active Search-as-action
  deferred (would be the first non-damage information action and
  needs its own scoring infra).
- **New `engine/core/skills.py`:** centralized 5e 2024 skill list
  (18 skills), `SKILL_TO_ABILITY` map, `normalize_skill_name` +
  `validate_skill_name`, `has_skill_proficiency`, `skill_modifier`.
  Resolution order: monster-template `skills:` dict (already-
  computed bonus, SRD shape) → ability + PB if proficient → just
  ability mod. Unknown skill name raises (no silent typo).
- **PC schema:** accepts `skill_proficiencies: [stealth, ...]`,
  validates against the known set, normalizes (lowercase + under-
  score), bakes onto template top-level + `derived_from_pc_schema`.
  Also computes `senses.passive_perception` (10 + WIS_mod + PB if
  Perception-proficient) so PC templates match the monster
  template shape.
- **`Actor.passive_perception: int`** field added. `cli._build_actor`
  loads from explicit actor_spec override → template
  `senses.passive_perception` → fallback 10.
- **`_execute_hide` extension:** swapped `dex_mod` log key →
  `stealth_mod` (which now includes proficiency PB via
  `skill_modifier`). Recorded `stealth_total` on the resulting
  `co_invisible` condition for downstream auto-spot comparison.
  Updated the one existing test that asserted the old `dex_mod`
  key — keeps the snapshot legible after rename.
- **`can_actor_see` extension:** when target has Invisible, check
  if any of its Invisible conditions are Hide-source
  (`source_action_id == "a_hide"`). For those, observer's
  `passive_perception >= stealth_total` ⇒ auto-spot. If spotted,
  fall through to the remaining gates (fog / darkness still block
  vision even after Perception spots them — the rogue might
  still be invisible *to vision* because the air is full of fog).
  Spell-source Invisible is NOT bypassable per RAW; only Hide.
- **New private helper `_PERCEPTION_BYPASSABLE_INVISIBLE_SOURCES`
  frozenset** holds the source_action_id allowlist (currently just
  `a_hide`). Future Hide-equivalents (e.g., a future "Stealth as
  Bonus Action" feature) would just add to this set.
- **Tests (32 new in `test_perception_stealth.py`):**
  - Skills module: 18-skill completeness, ability map, normalize +
    validate, monster-listed-bonus path, PC compute path, not-
    proficient path, proficiency detection from each source
  - PC schema: unknown skill raises, normalization, derived_from
    recording, default-empty, passive Perception with/without
    proficiency
  - `_execute_hide`: non-proficient uses DEX only; proficient adds
    PB; `co_invisible` carries `stealth_total`
  - `cli._build_actor`: template loading, actor_spec override
    wins, fallback to 10
  - `can_actor_see` auto-spot: passive ≥ stealth (above + equal),
    passive < stealth, spell-Invisible NOT bypassable, mixed
    sources documented (v1: auto-spot wins — concentration makes
    this rare anyway), self-sees-self, auto-spot doesn't bypass
    fog, auto-spot doesn't bypass darkness without darkvision
- **Fixture update:** `rogue_hides_in_fog_encounter.yaml` updated
  with `skill_proficiencies: [stealth]` on the rogue + explicit
  `senses.passive_perception` on both rogue (11) and ogre (8).
  Header comments updated to walk through the new RAW: stealth
  total beats ogre's PP, fog still blocks emerging vision, etc.
- 745 tests pass (+32, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- Active Perception search-as-action (`type: search`)
- Skill expertise (double PB on Stealth / Perception)
- Magic-item Perception bonuses (Cloak of Elvenkind etc.)
- "Stealth as Bonus Action" features (Rogue Cunning Action) —
  would add an action type with `source_action_id` in
  `_PERCEPTION_BYPASSABLE_INVISIBLE_SOURCES`
- Fixture revisit: mixed-Invisible (Hide + spell) gating tightness

---

## Session: 2026-05-26 — Dark zones + Dim light + Darkvision (PR #50)

**Participants:** Phil, Claude

**Work done:**
- Closes most of the vision arc started in PR #47. Pre-scoped the
  PR up-front: zone-based (matching PR #48's heavy-obscurement
  shape) + Darkvision only. Truesight + Blindsight + per-tile
  light grid all deferred to keep scope tight.
- **New `Actor.darkvision_range_ft: int` field** (default 0). RAW
  framing: most darkvision-having races/monsters are 60 ft, some
  (drow, deep-dwellers) are 120 ft. 0 = no darkvision = effectively
  Blinded in a dark zone.
- **Loading precedence** in `cli._build_actor`:
  1. Explicit `darkvision_range_ft:` on actor_spec (fixture override —
     where racial PC darkvision lives, since race modeling hasn't
     landed)
  2. Template's `senses.special.darkvision` (numeric feet — matches
     the existing `m_goblin_warrior.yaml` shape; works for all SRD
     monsters with darkvision)
  3. Defaults to 0
- **Two new environment fields:**
  - `dim_light_zones`: list of axis-aligned rects (same shape as
    heavy-obscurement zones)
  - `dark_zones`: list of axis-aligned rects, same shape
- **`vision.py` extensions:**
  - Refactored `is_in_obscured_zone` to use a shared
    `_position_in_any_zone(position, zones)` helper, since dim /
    dark / heavy-obscurement all have identical detection logic
  - New `_env_zones(state, key)` helper for pulling zone lists
    from the encounter environment
  - `is_in_dim_light_zone` + `is_in_dark_zone` public helpers
  - `can_actor_see` extended with the dark-zone + darkvision gate
    AFTER the heavy-obscurement gate (heavy obscurement still
    blocks darkvision — fog blocks sight regardless of light
    levels). New precedence order: blinded > invisible > heavy
    obscurement > dark zone (with darkvision check) > visible.
- **Dim light is declarable but does NOT block sight in v1.** RAW
  says dim light is *lightly obscured* — disadvantage on Perception
  checks that rely on sight, but vision itself works. We honor
  that exactly: the helper exists for completeness + future
  perception modeling, but `can_actor_see` does NOT return False
  on dim light alone. Avoids overstating obscurement.
- **Same-side and either-side-in-dark resolve through one code
  path.** Whether observer-in-dark or target-in-dark or both,
  the question is the same: does the observer's darkvision reach
  the target? If yes (and within range), True. If no darkvision
  at all, False. Cleaner than splitting the three cases.
- **Tests (24 new in `test_light_darkvision.py`):**
  - Dim/dark zone detection (in-zone, out-of-zone, inclusive
    boundaries, none-position, multiple zones)
  - Dim light doesn't block (target in dim, observer in dim)
  - Dark zone + no darkvision → blocked (target in dark;
    observer in dark)
  - Dark zone + darkvision: within range, exact-boundary, beyond
    range, both-in-dark within range, 120 ft reach
  - Precedence: blinded trumps darkvision, invisible-in-dark
    still blocked by Invisible (not darkness), heavy-obscurement
    trumps darkvision, self-sees-self even without darkvision
  - `cli._build_actor` wiring: template default loaded; actor_spec
    override wins; missing → 0
- **Fixture:** `dark_dungeon_encounter.yaml` — elf rogue with 60 ft
  darkvision override + human guard with no darkvision + goblin
  (with template-derived 60 ft darkvision) inside a 5×5 dark zone.
  Vision queries resolve as expected in all four directions.
- 713 tests pass (+24, no regressions).

**Future-roadmap items (recorded, not in this PR):**
- Truesight (bypasses Invisible + magical darkness)
- Blindsight (sees within range regardless of vision conditions)
- Magical darkness (Darkness spell — ordinary darkvision can't
  bypass; only Devil's Sight / Truesight)
- Per-tile light grid (vs the zone model — would need a tile system)
- Active Perception check vs Hide DC (replaces static DC 15)
- Stealth proficiency (PB addition to Hide check)
- Perception disadvantage in dim light (the *other* RAW dim-light
  effect, deferred along with active Perception)

---

## Session: 2026-05-26 — Great Weapon Fighting + damage_die_floor (PR #49)

**Participants:** Phil, Claude

**Work done:**
- Phil framed the next item as "damage re-roll + GWF." I pushed back
  honestly: per RAW 2024, GWF is a *clamp* ("treat any 1 or 2 as a
  3"), not a re-roll. The 2014 RAW was re-roll-and-keep-the-second;
  2024 swapped that to a floor. The two primitives are mechanically
  distinct — a re-roll mechanism doubles RNG draws and would need
  policy about chain-rerolls (lucky halflings re-rolling a re-rolled
  1? RAW says no, but the primitive has to encode it). A floor is a
  single-call clamp with no policy questions.
- Surveyed which other 5e mechanics would need a damage re-roll
  primitive today. Found none currently in scope:
  - **Lucky / Halfling Lucky** — d20 re-rolls, not damage dice
  - **Empowered Spell** (Sorcerer Metamagic) — would need a re-roll
    primitive, but Sorcerer isn't wired in
  - **Savage Attacker** — re-roll then take higher; not yet relevant
  Conclusion: ship `damage_die_floor` alone, defer the re-roll
  primitive until it has at least one consumer. Recorded as a
  future-roadmap item.
- **`_roll_dice_expr_with_floor` helper:** clamps each individual
  rolled die to `max(roll, floor)`. floor=0 / floor=1 is a no-op
  (every roll is already ≥ 1) so the helper is safe to plumb
  through unconditionally. floor=3 implements GWF 2024 exactly.
- **`_damage` integration:** reads `damage_die_floor` from params,
  routes both the base roll AND the crit-doubled roll through the
  floored helper. The flat `modifier` is *not* clamped (RAW: floor
  applies to "a damage die," and the modifier is not a die roll).
  Resistance / vulnerability / immunity apply after as before.
- **`pc_schema` gate:** added `great_weapon_fighting` to
  `_KNOWN_FIGHTING_STYLES`. `_build_weapon_action` injects
  `damage_die_floor: 3` into the damage step's params when
  `fighting_style == "great_weapon_fighting"` AND weapon is melee
  (`reach_ft`, not `range_ft`) AND `two_handed: true`.
- **Versatile weapons:** RAW lets versatile weapons (longsword,
  battleaxe, warhammer, etc.) get GWF when wielded two-handed. We
  defer that explicitly — it needs a runtime grip-state model since
  the same weapon swaps grip mid-encounter. The `two_handed: true`
  flag is the v1 gate. A versatile-grip PR is tracked.
- **Bonus dice from other sources:** Sneak Attack, smite, +1d6
  divine sources, etc. all run through *separate* primitive
  invocations with their own `dice` expressions. The floor lives
  per-primitive-call, so other sources are correctly *not* clamped
  by GWF — matches "the weapon's damage die" reading.
- **YAML feature file:** new
  `schema/content/features/f_fs_great_weapon_fighting.yaml`. Tagged
  `source: user_authored` because the 2024 PHB version is not in
  the SRD CC v5.2.1. Lists `granted_by: c_fighter L1 +
  f_fighting_style` to slot into the Fighting Style architecture
  from PR #38.
- **Tests (17 new):**
  - `_roll_dice_expr_with_floor` parity vs plain `_roll_dice_expr`
    at floor 0/1; clamping at floor 3 (forced 1s/2s → 3s); no-op
    on high rolls; mixed sequences
  - `_damage` primitive: low rolls pass through without floor; low
    rolls clamp with floor; crit doubles dice and floor applies to
    both passes; modifier unaffected by floor
  - `pc_schema._build_weapon_action`: GWF + 2H melee bakes in floor;
    GWF + 1H melee, GWF + ranged-2H (heavy crossbow), no-style + 2H,
    Dueling + 2H all omit the floor
  - Validation: `great_weapon_fighting` is in `_KNOWN_FIGHTING_STYLES`,
    `_validate_fighting_style` accepts it, template records the
    chosen style. Updated two existing `test_fighting_style` tests
    that asserted GWF was an unknown style.
- **Fixture:** added a fourth fighter (`fighter_gwf`) + fourth dummy
  to `fighting_styles_showcase_encounter.yaml` so the showcase
  demonstrates all four styles side-by-side.
- 689 tests pass (+17 new, 0 regressions).

**Future-roadmap items (recorded, not in this PR):**
- Damage re-roll primitive (Empowered Spell / Savage Attacker —
  defer until a consumer lands)
- Versatile-grip state model (longsword 1H vs 2H mid-encounter)
- Two-Weapon Fighting style (needs off-hand weapon mechanics —
  separate arc)

---

## Session: 2026-05-26 — Cover + Heavy Obscurement + Hide action (PR #48)

**Participants:** Phil, Claude

**Work done:**
- Closes the Hide arc that's been deferred since PR #29 (where I
  flagged Hide as blocked on terrain / cover / LOS modeling). With
  vision in place from PR #47, the remaining work was a cover model
  + obscurement zones + the Hide action itself.
- Tight v1 scope committed: per-actor cover field, environment
  obscurement zones (axis-aligned rects), Hide action with gates +
  Stealth check + auto-end on attack. Cover-from-creatures,
  Stealth proficiency, active-perception checks, AI scoring for
  Hide, total cover (auto-miss) all deferred.
- **Cover (per-actor field, symmetric):**
  - `Actor.cover: str` with values `none` / `half` / `three_quarters`
  - Loaded from fixture spec via `cli._build_actor`
  - `_cover_ac_bonus` helper maps to +0/+2/+5
  - `_attack_roll` includes the bonus in `effective_ac` (and re-
    queries cover bonus correctly after Shield reactions)
  - `_forced_save` adds the bonus to **DEX saves only** (per RAW —
    cover specifically helps DEX saves, not other ability saves)
- **Heavy obscurement zones:**
  - `encounter.environment.heavily_obscured_zones`: list of axis-
    aligned rects `{x_min, x_max, y_min, y_max}` (inclusive
    boundaries)
  - `vision.is_in_obscured_zone(position, state)` helper
  - `vision.can_actor_see` extended: returns False if EITHER observer
    or target is in a zone (RAW: heavily obscured creatures are
    effectively Blinded toward whatever's in / outside the
    obscurement). Same-zone-with-vision-types refinement deferred.
- **Hide action (new `type: hide`):**
  - `pipeline.generate_candidates` emits one Hide candidate per turn
  - `pipeline.execute` dispatches to `_execute_hide`:
    1. **Gate**: actor must be heavily obscured OR have ≥ 3/4 cover.
       If neither, logs `hide_attempted` with `outcome=failed`,
       `reason=no_cover_or_obscurement` and returns.
    2. **Stealth check**: d20 + DEX_mod vs DC 15. Stealth
       proficiency not yet modeled.
    3. **On success**: applies `co_invisible` with
       `source_action_id=a_hide` so the existing Invisible
       condition's modifiers fire (advantage on owner's attacks,
       disadvantage on attacks vs owner).
    4. Logs `hide_attempted` with full d20/mod/total/dc/outcome/gate
       + `hidden` event on success.
  - `_attack_roll` scrubs `co_invisible` whose `source_action_id ==
    "a_hide"` after the actor's attack (RAW: Hide ends on attack).
    Other-source Invisible (e.g., Greater Invisibility spell) is
    preserved.
- 22 new tests in `tests/test_cover_hide_obscurement.py`:
  - Cover field default + spec loading + AC bonus mapping
  - `_attack_roll` vs_ac includes cover bonus (half / three_quarters
    / none baseline)
  - `_forced_save` adds cover bonus to DEX saves
  - Obscurement zone detection (no zones, in / out, multiple zones)
  - `can_actor_see` respects zones (target in zone, observer in
    zone, both outside baseline)
  - Hide gates (no cover/obscurement → failed; three_quarters cover
    → eligible; heavy obscurement → eligible)
  - Stealth check math + outcome computation
  - Hide ends on attack (a_hide-source scrubbed; other-source
    preserved)
- New fixture `rogue_hides_in_fog_encounter.yaml`: rogue in 5×5 fog
  zone with Hide + shortsword vs ogre outside the fog. Seed 1 trace
  shows the full chain: `hide_attempted` with `gate:
  heavy_obscurement, d20: 5, dex_mod: 5, total: 10, dc: 15,
  outcome: failed` — Hide DC math + gate detection visible end-to-
  end.
- `basic_actions.py` docstring updated to reflect Hide now
  declarable (no longer fully deferred).
- Test count: 650 → 672. All green, stable across full-suite
  re-runs.

**Key decisions:**
- **Per-actor cover, not per-(attacker, target).** Real terrain-
  geometry cover would need LOS computation across squares; v1's
  symmetric per-actor field is the right starting shape. Fixture
  authors mark "this creature is behind a parapet" and all attacks
  get the bonus. When terrain geometry lands, this becomes a
  computed property.
- **Total cover deferred.** Would need a clean attack-cancellation
  path through `_attack_roll`. Half + three_quarters cover the
  common cases; total cover is rarer in actual combat (creatures
  behind total cover usually break LOS first via the obscurement
  side).
- **Cover bonus on DEX saves only.** RAW: cover helps DEX saves
  specifically (Fireball, Dragon Breath, etc.). Other ability
  saves aren't enhanced by cover.
- **Either-side-in-zone blocks vision** for `can_actor_see`. RAW:
  heavily obscured creatures are blinded; this catches both
  "looking in" and "looking out" cases. Same-zone-with-special-
  vision (e.g., creatures with magical darkvision who can see in
  the dark) deferred until vision types arrive.
- **Hide as a declarable action, not built-in.** Built-in Dodge /
  Disengage / Help are universal (everyone has them per RAW). Hide
  is universal RAW too but only valuable for actors with stealth
  positioning + decent DEX. v1 ships Hide for fixtures that
  explicitly declare it; making it implicitly available is a small
  follow-up.
- **`a_hide` source tag for scrubbing.** Distinguishes Hide-source
  Invisible from spell-source Invisible (Greater Invisibility,
  Invisibility) so the attack-scrub only ends the Hide-source one.
  Pinned with a specific test.
- **No AI scoring for Hide.** Fixture-driven only in v1. Adding a
  proper eHP score (own_DPR × 0.225 + enemy_DPR × 0.225 over some
  duration) is a clean follow-up; for now Hide gets picked when
  there's no better candidate (e.g., rogue out of melee reach with
  no ranged option).

**Open items carried forward:**
- **Total cover** (attack auto-miss; needs cancellation path)
- **Vision types** (truesight / blindsight / darkvision)
- **Light levels per tile** (bright / dim / dark)
- **Cover-from-creatures** (other actors on the line of sight)
- **AI scoring for Hide** (proper eHP gain calculation)
- **Stealth proficiency** (add PB to the check)
- **Hide ends on cast verbal spell** (need a verbal-tag on spells)
- **Hide ends on move-out-of-cover** (currently only attack-ends)
- **Active Perception check** vs the hide DC (currently fixed DC 15
  — DM-set; passive-Perception variant deferred)

---

## Session: 2026-05-26 — Vision system v1 (PR #47)

**Participants:** Phil, Claude

**Work done:**
- Pre-discussion locked tight scope: unified can_actor_see() query +
  tighten 3 reaction conditions. Light levels / Heavily Obscured
  zones / Hide action / vision types (truesight, blindsight,
  darkvision) all deferred.
- New `engine/core/vision.py`:
  - `can_actor_see(observer, target, state)` — single query
    function. False if observer Blinded OR target Invisible; True
    otherwise. Documents the deferred items + extension points.
  - Helpers `has_condition`, `is_invisible`, `is_blinded`.
  - Self-sees-self special case (returns True) — needed for
    self-targeted modifier when-clauses on Invisible creatures.
- `engine/core/modifiers.py` `_eval_when`: added handlers for
  `attacker_can_see(self)` and `target_can_see(self)` atoms. These
  were previously "unknown atoms" returning False, which happened
  to give correct behavior for the Invisible condition's specific
  when-clauses (`NOT attacker_can_see(self)` = `NOT False = True`).
  The new implementation actually computes the result, so behavior
  is correct for ALL cases (not just by coincidence).
- `engine/core/reactions.py` _reaction_condition_satisfied: three
  reactions tightened to respect RAW "you can see" gates:
  - `enemy_casting_spell_within_60_ft` (Counterspell): adds
    `can_actor_see(reactor, caster, state)` check
  - `damage_taken_by_self_from_attacker` (Hellish Rebuke): adds
    `can_actor_see(reactor, attacker, state)` check
  - `attack_against_ally_within_5_ft` (Protection): adds
    `can_actor_see(reactor, attacker, state)` check
- 20 new tests in `tests/test_vision.py`: condition helpers,
  can_actor_see (default true, invisible target, blinded observer,
  both, self-sees-self, None safety), _eval_when integration
  (attacker_can_see resolves correctly, regression on Invisible's
  when-clause), reaction conditions (Counterspell / HR / Protection
  all skipped against Invisible / by Blinded reactor), regression
  test that Shield (no vision gate) still works for Blinded wizards.
- Test count: 630 → 650. All green, stable across full-suite
  re-runs.

**Key decisions:**
- **Unified query function** rather than scattered checks. Other
  systems (Hide, ranged-attack cover bonuses, light-level
  interactions) will compose on `can_actor_see` rather than rolling
  their own visibility logic.
- **Self always sees self.** Needed for Invisible creatures whose
  own modifier when-clauses use `attacker_can_see(self)` — the
  Invisible wizard doesn't want their own attacks to suddenly miss
  because they "can't see themselves."
- **`state` parameter accepted but unused in v1.** Light levels
  will need it. Defining the signature now means no API break when
  v2 lands.
- **All vision types deferred.** Truesight (bypasses Invisible),
  Blindsight (sees within range regardless), Darkvision (needs
  light levels). Each is its own small extension on `can_actor_see`
  when the creatures or environment that need them land.
- **Hellish Rebuke 60-ft range gate STILL deferred** even with
  vision in place. Adding it would require threading more event_data
  through the damage path (we'd need the attacker's position at
  trigger time, but currently we only pass attacker_id). Pinned as
  open item.

**Open items carried forward:**
- [ ] Vision types (truesight, blindsight, darkvision)
- [ ] Light levels (bright / dim / dark per tile)
- [ ] Heavily Obscured zones
- [ ] **Hide action** (needs heavy obscurement / cover; this PR
  unblocks the vision side but not the cover side)
- [ ] Hellish Rebuke 60-ft range gate
- [ ] Cover (half / three-quarters / total) for ranged attacks
- [ ] Stealth checks vs passive Perception for active hiding

---

## Session: 2026-05-26 — Counterspell + cast-event infra (PR #46)

**Participants:** Phil, Claude

**Work done:**
- The natural follow-on to PR #45's reaction system. Counterspell
  needed three things the other reactions didn't: a spell-cast
  event hook, a spell-fizzle mechanism, and ability-check
  resolution. All three landed here.
- New event `spell_cast_initiated` in events.py.
- `pipeline.execute` now wraps spell-slot actions with the
  cast-event flow:
  1. Set `state.cast_cancelled = False`
  2. Fire `spell_cast_initiated` event (only for actions with
     `spell_slot_level >= 1` — cantrips and free actions skip)
  3. Reactions hooked on this event resolve; Counterspell may
     set `state.cast_cancelled = True`
  4. If cancelled: log `spell_cancelled`, skip the pipeline AND
     skip concentration application
  5. Always consume the slot (RAW 2024: original caster's slot is
     burned even on successful counter)
- New `_counterspell_resolve` primitive in primitives.py:
  - Auto-cancel for spell level ≤ 3
  - For level ≥ 4: Intelligence (Spellcasting) ability check —
    d20 + INT_mod + proficiency_bonus vs DC = 10 + spell_level
  - Sets `state.cast_cancelled` on success
  - Logs `counterspell_resolved` event with outcome + check details
- New reaction condition `enemy_casting_spell_within_60_ft` in
  reactions.py (caster on opposing side, not self, within 60 ft;
  vision check deferred until vision system).
- New `f_counterspell.yaml` (SRD, Wizard 3rd-level): trigger=
  spell_cast_initiated, condition=enemy_casting_spell_within_60_ft,
  pipeline=counterspell_resolve.
- 11 new tests in `tests/test_counterspell.py`: condition vocabulary
  (enemy in range yes / ally no / self no / out-of-range no),
  counterspell_resolve primitive (auto-cancel L1/L3, check fail L4,
  check success L4 with high roll, event log contents), pipeline
  cancel flow (skip pipeline + slot consumed + concentration not
  applied), end-to-end wizard mirror match (HP cancelled, both slots
  consumed, target's concentration not engaged), cantrip doesn't
  trigger Counterspell (no spell_cast_initiated event for actions
  without spell_slot_level).
- New fixture `counterspell_mirror_match_encounter.yaml`: Wizard A
  (PC) casts Hypnotic Pattern, Wizard B (enemy) counterspells. Seed
  1 trace shows the full chain: counterspell_resolved auto_cancel
  → spell_slot_consumed for B → reaction_fired → spell_cancelled
  → spell_slot_consumed for A. HP's forced_save / apply_condition
  pipeline NOT executed. A's concentration NOT engaged.
- Test count: 619 → 630. All green, stable across full-suite
  re-runs.

**Calibration note during dev:**
- First fixture iteration had dummies with `actions: []` so their
  DPR proxy was 0, which made HP's control eHP score 0 → wizard A
  correctly picked Magic Dart instead of HP. Gave the dummies a
  club attack so they have measurable DPR, then wizard A correctly
  picks HP and triggers the Counterspell. Working as designed
  (HP control scoring respects "does the target actually do
  anything?"); the demo fixture just needed real enemies.

**Key decisions:**
- **RAW 2024 mechanics** — auto-cancel for level ≤ 3, ability check
  for ≥ 4. Different from 2014's "Counterspell auto-counters any
  spell ≤ its cast level, ability check for higher."
- **Slot consumed on successful counter** — RAW 2024: original
  caster loses the slot even if the spell fizzles. Implemented by
  having pipeline.execute always run the consume_slot path
  regardless of cast_cancelled.
- **Concentration NOT applied on successful counter** — RAW: the
  spell never "took effect" so concentration doesn't engage. Easy
  to miss; pinned with a specific test.
- **Cantrips / free actions don't trigger** the event — gated on
  `slot_level > 0` in pipeline.execute. Pinned with a test (Fire
  Bolt-shape doesn't fire Counterspell).
- **state.cast_cancelled as a CombatState attribute** — set ad-hoc
  rather than as a declared dataclass field. Python lets us; it
  works. Could be cleaned up to a proper field, but the ad-hoc
  shape mirrors how state.current_attack already gets mutated.

**Open items carried forward:**
- [ ] Vision / line-of-sight gate for Counterspell ("you see")
- [ ] Reaction-cascade termination guard (Counterspell-of-
  Counterspell: A casts spell → B counters → A counters B's
  counter → infinite recursion in principle, but one-reaction-per-
  round limits in practice; should still pin behavior with a test)
- [ ] Pace-aware Counterspell scoring (when to save the slot vs.
  spend it — mirror PR #42's Action Surge pacing)
- [ ] Magic Missile + auto-hit spells (event still fires correctly
  but Counterspell's "you see them casting" gate would need to be
  more specific about visibility)
- [ ] Upcast Counterspell (RAW 2024: no benefit to upcasting; pure
  2014 holdover behavior would need different logic anyway)

---

## Session: 2026-05-26 — Reaction infrastructure + Shield + Protection + Hellish Rebuke (PR #45)

**Participants:** Phil, Claude

**Work done:**
- Pre-discussion locked scope: infra + 3 reactions. Counterspell
  explicitly cut — it needs cast-event hook + spell-fizzle +
  ability-check resolution (Intelligence (Spellcasting) per RAW
  2024) that are non-trivial separate pieces. Counterspell goes in
  its own follow-up PR.
- New trigger events in `engine/core/events.py`:
  - `attack_targeting_resolved` — fires after target picked, BEFORE
    d20 rolled (Protection hooks here)
  - `attack_roll_pending` — fires after d20+bonus computed, BEFORE
    hit/miss check (Shield hooks here; runner re-queries
    attack_modifiers after so the +5 AC takes effect)
  - `damage_taken` — fires after HP reduced (Hellish Rebuke hooks)
- `engine/core/reactions.py` extended with generic reaction system
  alongside the existing OA code:
  - `is_reaction_action(action)` — True if `trigger: <event>` is
    present. Used by `pipeline.generate_candidates` to filter
    reactions out of the main / bonus candidate pool.
  - `resolve_reaction_triggers(event_type, event_data, state, bus)`
    — scans living actors for declared reactions matching the event
    type whose condition is satisfied; fires each eligible reaction
    via try_use_reaction. Returns count of reactions fired.
  - `try_use_reaction(reactor, action, event_data, state, bus)`
    — gates on reaction slot + spell slot + feature use availability;
    sets up state.current_attack for the reaction's pipeline (with
    target swapped to the attacker for retaliation reactions like
    Hellish Rebuke via the `_reaction_target_is_attacker` flag); runs
    the pipeline via `_invoke_subprimitive` (same dispatch as
    forced_save sub-primitives); consumes resources; logs
    `reaction_fired` event.
  - `_reaction_condition_satisfied(cond, reactor, event_data, state)`
    — v1 vocabulary: `shield_would_help`,
    `attack_against_ally_within_5_ft`,
    `damage_taken_by_self_from_attacker`. Small fixed set;
    extensions = add a case.
- `engine/primitives.py`:
  - `_attack_roll` now emits `attack_targeting_resolved` (before
    roll) and `attack_roll_pending` (after roll). Re-queries
    `attack_modifiers` after the pending event so Shield's AC bump
    folds in for the hit/miss check.
  - `_damage` emits `damage_taken` after HP reduction (skipped on
    self-damage to avoid feedback loops).
- `engine/core/pipeline.py` `generate_candidates`: filters out
  actions with `trigger:` field (they're reactions, not turn-
  initiated candidates).
- `engine/pc_schema.py`: added "protection" to
  `_KNOWN_FIGHTING_STYLES`. Protection is a reaction (not a passive
  modifier baked at build time); the Fighting Style choice records
  the protector has it, but the reaction action itself is wired
  via fixture attachment (or future class-features auto-wiring) of
  `f_fs_protection.yaml`'s `action_template`.
- Three new feature YAMLs in `schema/content/features/`:
  - `f_shield.yaml` (SRD, Wizard 1st): trigger=attack_roll_pending,
    condition=shield_would_help, effect: ac_modifier +5
    until_actor_next_turn_start. Consumes 1st-level slot.
  - `f_fs_protection.yaml` (non-SRD): trigger=attack_targeting_resolved,
    condition=attack_against_ally_within_5_ft, effect:
    disadvantage_for_attacker on the ally per_single_attack.
  - `f_hellish_rebuke.yaml` (SRD, Warlock 1st): trigger=damage_taken,
    condition=damage_taken_by_self_from_attacker, effect:
    forced_save DEX vs spell DC for 2d10 fire (half on save).
- 21 new tests in `tests/test_reactions.py`: is_reaction_action
  detection, candidate filtering, condition vocabulary (shield
  would_help yes/no-attack-misses-anyway/no-attack-hits-anyway/
  not-self; ally within 5 ft yes/not-adjacent/enemy-target; damage
  by self yes/by-other-doesnt-fire), try_use_reaction (slot
  consumed, skipped without slot, one-per-round cap), Shield end-
  to-end (turns hit into miss, doesn't fire when attack misses
  anyway), Protection end-to-end (imposes disadvantage on adjacent
  ally / skipped when ally not adjacent), Hellish Rebuke end-to-
  end (damages attacker via forced_save).
- Test count: 598 → 619. All green, stable across full-suite
  re-runs.

**Bug fix during dev:**
- Initial Shield test failed because the test helper hardcoded
  `bonus=4` for the attack roll but the test created the attacker
  with `bonus=10`. The attack's `_attack_roll` reads its bonus
  from primitive params (passed directly), not from the action's
  pipeline. Fixed by making the helper accept `attack_bonus` and
  pass it through.

**Key decisions:**
- **Counterspell cut.** Honest scope. Counterspell needs three
  pieces of infra the other reactions don't: spell-cast event hook,
  spell-fizzle mechanism (cancel pending spell while still
  consuming caster's slot), and ability-check resolution (we have
  saves but not ability checks). Each is a separate non-trivial
  addition. Bundling would have doubled the PR size and risk.
- **Always-use reaction scoring.** v1 fires the reaction whenever
  the condition is satisfied and the slot is available. Pace-aware
  reaction selection (don't burn Shield on the first attack of a
  long day) is a clean follow-up via the same shape as PR #42's
  Action Surge pacing.
- **Conditions are a small fixed vocabulary, not an expression
  evaluator.** Three conditions cover the three reactions. Adding
  new ones = adding a case. Keeps the system explicit and avoids
  the eval-string can-of-worms.
- **`_reaction_target_is_attacker` flag** for retaliation-type
  reactions (Hellish Rebuke). The condition sets it on event_data;
  try_use_reaction reads it to swap state.current_attack.target to
  the attacker so forced_save's `affected='current_target'`
  retargets correctly.
- **Re-query attack_modifiers after attack_roll_pending event.**
  Critical for Shield to work — Shield attaches a +5 AC modifier
  during its pipeline; without the re-query, the hit/miss check
  uses the pre-Shield AC.
- **Skip damage_taken event on self-damage** (attacker == target).
  Prevents feedback loops if a creature's reaction self-damages.
- **Protection isn't auto-applied at template build time** like
  Defense/Dueling/Archery. It's a reaction action wired via the
  `action_template` field on the YAML. Fixtures attach it manually
  for v1; future class-features auto-wiring will pick it up from
  the FStyle choice.

**Open items carried forward:**
- [ ] Counterspell (own PR — cast-event hook + spell-fizzle +
  ability-check infra)
- [ ] Pace-aware reaction scoring (Shield-on-first-attack burn)
- [ ] Auto-attach reaction action_templates from FStyle choice
  (Protection — currently fixtures attach manually)
- [ ] Reaction conditions for vision / line-of-sight gates
  (Hellish Rebuke RAW requires "you can see"; Protection RAW
  requires "creature you can see")
- [ ] Reaction range gates (Hellish Rebuke RAW: within 60 ft)
- [ ] Magic Missile auto-hit trigger for Shield (separate event
  needed — MM doesn't roll attack rolls)
- [ ] Reaction-cascade termination guard (the comment in events.py
  noted this; the one-reaction-per-round limit already prevents
  the worst cases, but Mage Slayer / Counterspell-of-Counterspell
  chains would need stricter rules)

---

## Session: 2026-05-26 — More persistent_aura: Moonbeam + Cloud of Daggers (PR #44)

**Participants:** Phil, Claude

**Work done:**
- Pre-discussion confirmed scope: Moonbeam + Cloud of Daggers in
  this PR. Spiritual Weapon explicitly cut — it's a summoned-
  creature mechanic (separate stat block, bonus-action attack
  chain, 1-min non-concentration duration), not a persistent_aura.
  Will be its own PR.
- Three pieces of new infra on top of PR #43's persistent_aura:
  - **`anchor: point` mode** — area placed at a chosen point at
    cast time, doesn't move (vs. `anchor: caster`). Origin
    captured from `state.current_attack.area_origin` (set by the
    candidate generator for point-anchored auras, mirroring the
    existing Fireball-style sphere AoE pattern).
  - **Cube area shape** — new `actors_in_cube` geometry helper.
    Center-on-origin semantics: half-extent in squares =
    `size_ft // 10` (5-ft = 1 square, 10-ft = 3×3, 20-ft = 5×5).
  - **No-save path** — `ability: 'none'` in the persistent_aura
    params skips `forced_save` and invokes `on_fail`
    sub-primitives directly (always-damage). Emits the new
    `persistent_aura_no_save_trigger` event for telemetry.
- `engine/primitives.py` `_persistent_aura`: gained `anchor` /
  `shape` / `size_ft` / origin recording. `ability == 'none'`
  normalizes to `None` internally so the runner can branch cleanly.
  Registration event log expanded with `shape`, `size_ft`, `anchor`,
  `origin`.
- `engine/core/runner.py` `_resolve_persistent_aura_triggers`:
  rewritten to handle the new modes. Computes area origin based
  on anchor (caster.position vs. aura.origin). Area check uses
  `actors_in_cube` for cube shapes; sphere uses radius_ft. If
  `aura.ability is None`, invokes on_fail sub-primitives directly
  via `_invoke_subprimitive`; otherwise invokes `forced_save` as
  before.
- `engine/core/pipeline.py` candidate gen: persistent_aura branch
  now splits on anchor. `caster`-anchored emits ONE candidate
  (current SG behavior). `point`-anchored emits ONE PER LIVING
  ENEMY as candidate origin (Fireball pattern), so AI picks the
  best placement. New helpers `_persistent_aura_anchor` /
  `_persistent_aura_cast_range`.
- `engine/ai/ehp_scoring.py` `offensive_ehp_persistent_aura`:
  added `origin` parameter (defaults to None = caster.position).
  Handles shape (sphere/cube via the right geometry helper) and
  no-save path (full damage every turn when no ability). Dispatch
  in `score_candidate` passes the candidate's `origin_point` so
  point-anchored candidates score against their actual placement
  rather than the caster's position.
- New feature YAMLs in `schema/content/features/`:
  - `f_moonbeam.yaml` (Druid 2nd, SRD CC v5.2.1): sphere/point/
    all_creatures/CON save vs 2d10 radiant on fail, half on
    success. `granted_by: c_druid L3` (when Druids gain access to
    2nd-level spells).
  - `f_cloud_of_daggers.yaml` (Wizard 2nd, SRD CC v5.2.1): cube/
    point/all_creatures/no-save/4d4 slashing.
  Both document deferred items (bonus-action movement for
  Moonbeam, entry-on-move trigger for both).
- 14 new tests in `tests/test_more_persistent_auras.py`: cube
  geometry helper (5-ft = 1 square, 10-ft = 3×3, 20-ft = 5×5),
  point anchor mechanics (primitive records origin from
  area_origin / falls back to caster pos / caster anchor records
  no origin / point aura stays even if caster moves), all_creatures
  friendly fire (ally in radius takes damage), no-save path
  (invokes on_fail directly without forced_save event, emits
  no_save_trigger event), cube shape in runner (only origin square
  hit for 5-ft cube), scoring (point-anchored uses origin not
  caster pos, no-save scoring uses full damage), Moonbeam end-to-
  end via runner, Cloud of Daggers end-to-end via runner.
- New fixtures `moonbeam_encounter.yaml` (druid + 3 goblins) and
  `cloud_of_daggers_encounter.yaml` (wizard + 2 orcs — one in
  the cube, one outside).
- Test count: 584 → 598. All green, stable across full-suite
  re-runs.

**Key decisions:**
- **Spiritual Weapon cut from this PR.** It's a different mechanic
  entirely (summoned floating weapon with bonus-action attacks,
  separate stat block, 1-minute non-concentration duration). Phil
  agreed. Will be its own PR with proper design space for the
  summoned-creature pattern.
- **Cube uses center-on-origin semantics.** RAW: "centered on a
  point" — half-extent = size_ft / 2 ft. In our 5-ft grid that
  rounds to `size_ft // 10` squares (5-ft = 0 → 1×1, 10-ft = 1
  → 3×3, 20-ft = 2 → 5×5). Matches Cloud of Daggers' "5-ft cube =
  1 square" intuition.
- **`anchor: point` mirrors Fireball's per-enemy candidate gen.**
  Each living enemy becomes a possible cube/sphere origin, AI
  picks best per eHP. Same pattern as existing AoE sphere
  (PR #24).
- **No-save path emits its own event** (`persistent_aura_no_save_trigger`)
  rather than reusing `forced_save`. Telemetry stays clean — log
  inspection cleanly distinguishes save-based from no-save aura
  triggers.
- **Spell-level grant from L3** for both spells (Druids and
  Wizards access 2nd-level slots at L3). Pragmatic — multiclass
  / subclass nuances aren't modeled. `granted_by.level: 3` is
  accurate for single-class.

**Open items carried forward:**
- [ ] Spiritual Weapon (separate PR — summoned-creature mechanic)
- [ ] Sickening Radiance (XGtE non-SRD; can ship as user_authored
  alongside an Exhaustion condition impl)
- [ ] Moonbeam bonus-action move (caster moves the beam 60 ft as
  bonus action; needs a "move existing aura" mechanic)
- [ ] Entry-on-move trigger (still deferred from PR #43 — needed
  for fully RAW-correct Moonbeam / CoD / Spirit Guardians)
- [ ] Cross-aura dedup (two casters drop CoD on same square;
  RAW: don't stack damage)
- [ ] Pacing-aware concentration-spell scoring (similar to
  Action Surge pacing from PR #42 but for spells that lock the
  caster's concentration slot)

---

## Session: 2026-05-26 — Spirit Guardians + persistent_aura primitive (PR #43)

**Participants:** Phil, Claude

**Work done:**
- New primitive class: persistent, self-anchored area effects that
  move with the caster and trigger forced saves at well-defined
  events. Spirit Guardians is the canonical first consumer; the
  shape also covers Spiritual Weapon / Moonbeam / Cloud of Daggers
  / Sickening Radiance.
- Pre-discussion scoped tight: "damage on turn-start only" (skip
  RAW's enter-on-move trigger — that needs movement-event
  detection), "speed-halving deferred" (needs movement-rate
  modifier infra), "enemies-only" (skip the RAW
  caster-chooses-which-creatures clause).
- New `CombatState.persistent_auras: list[dict]` — registry of
  active auras with caster_id, action_id, named_effect, radius_ft,
  trigger_event, ability, dc, on_fail, on_success, affected.
- New `_persistent_aura` primitive in `engine/primitives.py`.
  Registered with implemented=True; removed from
  _STUBBED_PRIMITIVES. Logs `persistent_aura_registered` event on
  cast.
- Runner hook `_resolve_persistent_aura_triggers` fires at each
  actor's turn_start. For each aura where actor is within radius
  of (still-living) caster AND opposing side (v1 enemies-only),
  sets up state.current_attack context with caster as actor +
  actor as target, then invokes the existing `forced_save`
  primitive with the aura's save params + on_fail / on_success
  pipelines. Composes cleanly with existing damage / save infra.
- Defensive: if actor dies from one aura's trigger, skip remaining
  auras for that actor this turn (don't keep hitting a corpse).
- `_run_actor_turn` only fires if `actor.is_alive()` after the
  aura check — fighters who die to a turn-start aura don't try to
  take their action.
- New action type `persistent_aura` in pipeline's
  generate_candidates: one candidate per turn (self-anchored, no
  positioning choice). Candidate's `target` is the closest in-
  radius enemy for scoring context; actual aura affects all in-
  radius enemies via the registered trigger.
- New scoring helper `offensive_ehp_persistent_aura` in
  ehp_scoring.py: sum per-enemy per-turn expected damage
  (p_fail × full + p_success × half) × EXPECTED_AURA_ROUNDS (2.5).
  Per-turn damage capped at enemy's remaining HP (no over-counting
  on low-HP targets).
- `end_concentration` extended to scrub `state.persistent_auras`
  entries matching the dropped (caster_id, action_id) — so when
  the cleric loses concentration to a damage CON save (PR #21) or
  becomes Incapacitated (PR #34), the Spirit Guardians aura ends
  cleanly. Verified by test.
- 13 new tests in `tests/test_persistent_aura.py`: registration
  (state field populated, event logged), runner hook (in-range
  enemy saves + takes damage, out-of-range unaffected, ally
  unaffected, dead caster aura is noop), concentration cleanup
  (this caster's aura scrubbed but other casters' preserved),
  scoring (single enemy, no enemies, multi-enemy scales linearly,
  per-turn HP cap), end-to-end via runner (cleric casts SG vs ogre
  cluster, ogres take per-turn-start damage as documented).
- New fixture `tests/fixtures/spirit_guardians_encounter.yaml`:
  L5 cleric vs 3 clustered ogres. Seed 1 demonstrates the full
  chain — cast → registered → concentration_started → each ogre
  turn-start fires forced_save → damage_dealt for radiant. Cleric
  takes hits from ogres but their CON save preserves concentration.
- Bug found + fixed: `save_fail_probability` requires a `state`
  argument that I initially omitted in the scoring function. Caught
  by the integration test that runs the full runner.
- Test count: 571 → 584. All green, stable across full-suite
  re-runs.

**Key decisions:**
- **Turn-start trigger only (v1).** RAW Spirit Guardians fires on
  "first time entering area on a turn OR starts turn there." We
  ship (b) only — entry-on-move needs per-square movement-event
  detection that's a separate arc. Documented as deferred. Most
  Spirit Guardians value comes from the turn-start trigger anyway
  (RAW: "first time on a turn" means at most 1 hit per creature
  per turn regardless of entry vs. start).
- **Enemies-only default is RAW-faithful for Spirit Guardians**
  (corrected post-PR). RAW: "When you cast this spell, you can
  choose any number of creatures you can see to be unaffected
  by it." So Spirit Guardians specifically has NO friendly fire
  when the caster makes the rational choice to exclude all
  allies. Our `affected: enemies` default is that exclusion
  baked in. The `affected: all_creatures` mode in the schema is
  for OTHER persistent_aura spells that don't have RAW exclusion
  (Cloud of Daggers, Sickening Radiance, etc.) — those would opt
  in when they land.
- **Speed-halving deferred.** Needs a movement-rate modifier
  system we don't have. Pure damage is the headline mechanic;
  speed-halving is a tactical bonus we can layer later.
- **Reuse `forced_save` primitive verbatim.** Runner hook sets up
  state.current_attack and invokes the existing primitive. No new
  save logic; clean composition.
- **Per-turn HP cap in scoring.** An aura that does 12 dmg/turn
  to a 3 HP creature is worth 3 eHP/turn for that creature, not
  12. Prevents over-scoring vs already-bloodied targets.
- **EXPECTED_AURA_ROUNDS = 2.5** to match EXPECTED_BUFF_ROUNDS for
  framework consistency. Tunable; could be longer for
  concentration-stable casters (Cleric with War Caster) or
  shorter for damage-heavy fights (caster eats CON saves).

**Open items carried forward:**
- [ ] Entry-on-move trigger (RAW: "first time entering area on a
  turn"). Needs per-movement-step event detection.
- [ ] Speed-halving while in area (needs movement-rate modifier
  system).
- [ ] `affected: all_creatures` mode in the runner (lands when the
  first persistent_aura spell WITHOUT a RAW exclusion clause
  arrives — Cloud of Daggers, Sickening Radiance, etc.). Schema
  field exists; runner currently treats anything other than
  `enemies` as not-skipped (falls through), which is the right
  behavior for `all_creatures` — needs explicit tests.
- [ ] Cross-aura dedup (two SG casters on same area). Currently
  each aura fires independently; RAW says effects of the same
  spell don't stack so the per-turn damage should be capped at
  one cast's worth. Follow-on similar to PR #36's named_effect
  pattern for buffs.
- [ ] More persistent_aura spells: Spiritual Weapon (separate
  attack action that uses the aura's position; different
  mechanic), Moonbeam (5-ft radius, casters move per turn),
  Cloud of Daggers (5-ft cube, damage on entry-and-each-turn).

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
