# Engine Capabilities — Checkpoint

**Last updated:** 2026-05-26
**Engine state:** Phase 1, post-PR #26 (Dodge + Disengage merged).
**Test surface:** 375 tests across 15 modules; 14 CLI fixtures.

This document captures what the simulator can actually do today — in
observable behavioral terms, not module inventories. The companion
`pillars-reconciliation.md` defines the *intended* design; this
document describes what's *wired up*.

A reader should be able to answer two questions from this doc alone:
*"What can the AI demonstrate right now?"* and *"What's the next thing
I'd see if I tried X?"*

**Status headline:** as of PR #26 the engine has the **entire 8-step
decision pipeline live**, **all 4 dials** with v1 implementations,
**RP Constraints** as identity overlay, **positioning + movement +
reachability**, **opportunity attacks** with Disengage suppression,
**all three RAW AoE shapes** (sphere + cone + line) scoring both
damage AND control on the same per-target pipeline, **offensive +
defensive ally buffs** (Bless), **concentration** with damage-triggered
CON saves, **spell slot opportunity cost**, **Dodge / Disengage**
defensive actions, and the **compact PC schema** for fixture authoring.
The framework doc's canonical Fireball-vs-Hypnotic-Pattern worked
example is now a deterministic CLI demo. Remaining work is content
breadth, additional primitives, and depth-within-system, not new
architecture.

---

## 1. What the AI Can Demonstrate Today

These behaviors are verifiable by running the CLI on the bundled
fixtures or by reading the integration tests. They are not "designed
for"; they fall out of the math.

### Targeting (5 dial presets)

| Preset | Behavior demonstrable in a test? |
|---|---|
| `closest_enemy` | ✅ Picks by real grid distance (ties → turn order) |
| `weakest_target` | ✅ Picks lowest current HP |
| `most_dangerous` | ✅ Picks highest threat-score enemy (CR × 10 + max_attack_bonus × 2 + spellcaster signal +5) |
| `caster_first` | ✅ Prefers any visible spellcaster; falls back to `most_dangerous` |
| `optimal_ehp` | ⚠️ Degrades to `caster_first` for v1 — joint (target × ability) optimization deferred |

**Universal finish-off rule:** INT ≥ 4 creatures deviate from their
preset when an enemy is below 15% HP.

### Ability selection (5 dial presets)

| Preset | Status |
|---|---|
| `mindless` | ✅ Always uses the first action |
| `instinctive` | ✅ Prefers `is_signature: true` flagged actions |
| `default` | ✅ Multiattack > weapon_attack > first listed |
| `tactical` | ✅ Picks the highest-EV action against the chosen target via offensive-eHP scoring |
| `optimal` | ⚠️ Aliases to `tactical` for v1 |

### Action Economy (5 dial presets — all live)

| Preset | Main % | Sig Bonus % | Tac Bonus % | OA Rxn % | Sophist Rxn % |
|---|---|---|---|---|---|
| Optimal | 100 | 100 | 100 | 100 | 100 |
| Skilled | 90 | 95 | 85 | 100 | 80 |
| Average | 85 | 95 | 60 | 95 | 40 |
| Casual | 75 | 90 | 30 | 85 | 10 |
| Reactive_only | 65 | 80 | 0 | 80 | 0 |

- Main slot "miss" → downgrade to default attack; bonus slot gated
  by signature vs tactical rate; **OA reactions LIVE** (PR #16);
  sophisticated reactions still dormant
- `play_context: solo` PC modifier shifts preset down one tier

### Retreat (5 dial presets — DMG p48 algorithm)

| Preset | Bloodied % | Ally-disparity | Frightened-alone | In-combat DC |
|---|---|---|---|---|
| FtD | (algorithm disabled — never flees) ||||
| Resolute | 35% | >75% | No | 8 |
| Default | 50% | >50% | Yes | 10 |
| Cowardly | 60% | 1 ally falls | Yes | 13 |
| Pacifist | 50% | >50% | Yes (parley first — deferred) | 10 |

Mindless override (INT ≤ 2 OR archetype `mindless_aggressor` → never
flees) + compound logic (Resolute requires Bloodied AND another) +
WIS save → fail = flee.

### RP Constraints (3 types — Tier 1/2/3 architecture)

| Type | Tier | Mechanism | Example shipped |
|---|---|---|---|
| Hard Filter | 1 | Set-intersection removal; empty → Pass-turn fallback | `pacifist_strict` |
| Forced Choice | 2 | Highest-priority triggered constraint applies score boost | `heal_priority` (prio 80), `signature_first` (prio 50) |
| Weighted Preference | 3 | All matching constraints applied additively | `resource_hoarder` (-30% on spell candidates) |

Schema: `behavior_profile.rp_constraints: [{id, severity?, priority?}]`.
v1 ships 4 of 12 canonical constraints.

### Positioning, movement, reachability (PR #15)

- **2D grid positions** in `Actor.position`; CLI accepts `position: [x, y]`
- **Chebyshev × 5 distance** (5e 2024 "diagonals = 5 ft")
- **`move_toward`** with `stop_at_ft` so creatures land adjacent
- **Reachability filter** in `generate_candidates`: melee `reach_ft` /
  ranged `range_ft`; heal/buff allies generous
- **Out-of-range guard** in `attack_roll` — defensive auto-miss
- **`attacker_within_ft(N)` when-clauses** evaluate against real positions
- **Movement phase** in runner: try to act → move toward dial-preferred
  target → try again → log `passed_turn` if still unreachable

### Opportunity attacks (PR #16) + Disengage suppression (PR #26)

- **Trigger**: reactor's melee reach covered mover's pre-move position
  AND does NOT cover post-move position
- **Decision**: roll vs `oa_reaction` percentage from reactor's AE preset
- **Execution**: single melee weapon attack against the mover at
  pre-move position
- **One per reactor per round**
- **NEW (PR #26): Disengage suppression** — `Actor.disengaging = True`
  short-circuits `find_oa_triggers`, returns `[]`, logs
  `disengage_suppressed_oa`. Per RAW: "your speed doesn't provoke
  opportunity attacks for the rest of your turn."

### AoE attacks — all three RAW shapes (PRs #17, #24)

**Three shapes wired:**

| Shape | Origin | Direction | Helper |
|---|---|---|---|
| Sphere | enemy.position (or chosen point) | n/a | `actors_in_radius` |
| Cone | caster.position | unit_vector toward enemy | `actors_in_cone` |
| Line | caster.position | unit_vector toward enemy | `actors_in_line` |

- **Candidate generation** — per-enemy enumeration; sphere uses
  enemy as origin (catches "cast on cluster"); cone/line use caster
  origin + per-enemy direction (8-direction snapping)
- **eHP scoring** unified across shapes: per-target damage AND
  control sum; friendly fire subtracts for caught allies; caster
  counts as ally
- **Half-damage-on-save** via `damage` primitive's `multiplier` param
- **Per-target swap in `_forced_save`** so damage hits each affected
  creature with their own roll resolution
- **8-direction snapping** for cones/lines (cardinals + ordinals)

### AoE control — Hypnotic Pattern shape (PR #25)

- **`apply_condition` in forced_save on_fail/on_success** is now
  scored as control eHP per affected target
- **Per-target control eHP** = `target_DPR × p_fail × 2.5 rounds ×
  denial_fraction` (Hard control = 1.0; Partial = 0.2–0.5)
- **Mixed damage + control AoE** automatically sums both contributions
- **Friendly fire applies** to control too (incapacitating an ally
  subtracts from the score)

### Compact PC schema (PR #19)

Third actor_spec shape alongside `template_ref:` and `template:`.

```yaml
- instance_id: fighter_pc
  side: pc
  position: [0, 0]
  spell_slots: { 1: 3 }       # optional
  pc:
    class: c_fighter
    level: 3
    ability_scores: { str: 16, dex: 12, con: 14, int: 10, wis: 12, cha: 10 }
    armor: { base_ac: 16, max_dex_bonus: 2 }
    weapons: [...]
```

Engine derives HP / AC / PB / save bonuses / per-weapon attack actions.

### Offensive buffs for allies — Bless shape (PR #20)

- **Action type `offensive_buff`** with `target: ally` on `attack_modifier`
- **eHP scoring**: `ally_DPR × Δhit × EXPECTED_BUFF_ROUNDS (2.5)`
- **Δhit math**: +1 flat ≈ +5% hit chance; advantage ≈ +22.5%
- **Dedup**: returns 0 if target already has this exact buff from this
  caster — prevents wasted re-casts

### Dodge action (PR #26)

- **Action type `defensive_buff` self-targeted** with disadvantage-for-
  attacker + DEX-advantage modifiers (lifetime `until_actor_next_turn_start`)
- **`defensive_buff_rounds: 1` override** for accurate eHP scoring
  (Dodge lasts 1 round, not the framework's default 2.5)
- **Zero new primitives** — piggy-backs on existing modifier registry
- **AI picks Dodge** when surrounded by high-DPR enemies and only weak
  attacks are available

### Disengage action (PR #26)

- **New `type: disengage`** action — sets `Actor.disengaging = True`
- **`Actor.disengaging`** field cleared by `reset_turn()` at next
  turn-start (correct RAW: until end of your turn)
- **AI scoring** — small flat constant (~0.5 eHP); rarely beats
  attacks. Real picking needs movement-aware AI (deferred). Currently
  pickable when explicitly declared or forced by RP constraint.

### Concentration (PR #21)

- **One slot per actor** (`Actor.concentration_on`)
- **`concentration: true` flag** on actions marks them; pipeline
  auto-tracks the slot
- **New cast auto-drops old** — one concentration spell at a time
- **CON save on damage taken** — `DC = max(10, ⌈damage/2⌉)`; failure
  ends concentration. Hook lives in `_damage` so every damage path
  triggers automatically
- **Death ends concentration** — runs before `creature_dropped` event

### Spell slot opportunity cost (PR #22)

- **`Actor.spell_slots: dict[int, int]`** — per-actor slot tracking
- **`action.spell_slot_level`** declares required slot
- **Candidate filter** — spells with no available slot are excluded
- **eHP cost subtracted at scoring** per framework formula:
  `slot_level × 3.0 × scarcity × (1 - urgency)` where `scarcity =
  1/max(1, slots_remaining)`, `urgency = encounters_remaining / 6`
- **Execution consumes** the slot
- **Reference value verified**: 3rd-level slot, 1 left, end-of-day =
  9.0 eHP (matches framework's Fireball worked example exactly)

### Conditions affect AI choices

The Q5 unified modifier registry feeds advantage / disadvantage / AC
swings into both *execution* (attack rolls, saves) and *scoring*
(hit_probability). The net effect:

- A **Blinded** target scores higher than an equivalent non-Blinded
  target, because attackers have advantage → higher hit probability →
  higher expected damage → higher offensive eHP. **No special-cased
  "prefer Blinded" code exists** — it falls out of the math.

### Aggression scaling (archetype → behavioral coefficient)

| Archetype | aggression_coefficient |
|---|---|
| `berserker_fanatic` | 1.5 |
| `mindless_aggressor` | 1.3 |
| `apex_predator` | 1.1 |
| `pack_hunter` | 1.1 |
| `territorial_beast` | 1.0 |
| `cowardly_skirmisher` | 0.8 |
| (no archetype) | 1.0 default |

### Defensive eHP — heal / buff / control

| Family | Formula | Status |
|---|---|---|
| Healing | `expected_healing × desperation_multiplier`, capped at missing HP | ✅ |
| Defensive buff | `worst_enemy_DPR × Δmiss × buff_rounds` (per-action override) | ✅ |
| Hard control (save-or-lose) | `enemy_DPR × p_fail × 2.5 rounds × denial_fraction` | ✅ |

---

## 2. Decision Pipeline — Step-by-Step Status

The 8-step pipeline from `pillars-reconciliation.md` §7 lives in
`engine/core/pipeline.py`. All 8 steps wired:

| Step | Status |
|---|---|
| 0. Resolve effective profile | 🟡 Reads `actor.template.behavior_profile`; archetype defaults via `_ARCHETYPE_DEFAULTS`. Faction profiles, instance overrides, form transitions, runtime overrides all deferred. |
| 1. Retreat trigger check | ✅ DMG p48 algorithm via `engine/ai/retreat.py`. |
| 2. Generate candidates | ✅ Enumerates weapon_attack / multiattack / heal / defensive_buff / hard_control / aoe_attack (sphere/cone/line) / offensive_buff / disengage per slot. Slot-aware. Reachability-filtered. Spell-slot-availability-filtered. |
| 3. Apply RP Hard Filters | ✅ Tier 1 set-intersection. Empty set logs `passed_turn` event. |
| 4. Apply RP Forced Choices | ✅ Pass-through; score-boost at scoring time per §6.3. |
| 5. Score each candidate | ✅ Offensive + defensive eHP per type (including AoE damage AND control), minus spell-slot cost, scaled by aggression, plus Tier 2/3 RP score modifications. |
| 6. Select max-scoring candidate | ✅ Stable max. |
| 7. Apply Action Economy per slot | ✅ Main-slot optimality roll; bonus slot gating; OA reactions via runner during movement; Disengage suppresses OAs from the mover. |
| 8. Execute | ✅ Single actions / multiattack loops / AoE area filtering (sphere via origin, cone/line via origin + direction). Consumes spell slot if `spell_slot_level > 0`. Marks concentration slot if `concentration: true`. Sets `actor.disengaging = True` for `type: disengage`. |

---

## 3. eHP Framework — Coverage Map

Per `docs/foundations/ehp-action-framework.md`:

```
Total Action Value = Offensive eHP + Defensive eHP − Opportunity Cost
```

| Component | Status | Module |
|---|---|---|
| Direct damage (single-target offensive) | ✅ | `engine/ai/ehp_scoring.py` |
| Multiattack (offensive) | ✅ | `engine/ai/ehp_scoring.py` |
| AoE damage — Sphere | ✅ | `engine/ai/ehp_scoring.py` |
| **AoE damage — Cone + Line** | ✅ **NEW PR #24** | `engine/ai/ehp_scoring.py` |
| Friendly fire penalty in AoE | ✅ | `engine/ai/ehp_scoring.py` |
| **AoE control (apply_condition)** | ✅ **NEW PR #25** — per-target `DPR × p_fail × 2.5 × denial_fraction`; mixed damage+control sums | `engine/ai/ehp_scoring.py` |
| Offensive buff for allies (Bless) | ✅ | `engine/ai/ehp_scoring.py` |
| Direct healing (defensive) | ✅ | `engine/ai/defensive_ehp.py` |
| Defensive buff (defensive) | ✅ — with **per-action `defensive_buff_rounds` override** (PR #26) | `engine/ai/defensive_ehp.py` |
| Hard control / action denial (single-target) | ✅ | `engine/ai/defensive_ehp.py` |
| Opportunity cost — spell slots | ✅ | `engine/core/spell_slots.py` |
| Concentration management | ✅ | `engine/core/concentration.py` |
| **Disengage OA suppression** | ✅ **NEW PR #26** | `engine/core/reactions.py` |
| **Dodge defensive action** | ✅ **NEW PR #26** — zero new primitives | `engine/ai/defensive_ehp.py` |
| Soft control / movement denial | 🔴 Deferred — needs movement-restriction modifier types |
| Debuff on enemy saves | 🔴 Deferred |
| Opportunity cost — action economy alternatives | 🔴 Deferred |
| Future-rounds discounting | 🔴 Deferred — flat 2.5-round constant (with per-action override) |
| Behavioral coefficients | 🟡 Only `aggression_coefficient` wired; `self_preservation_coefficient`, `pack_tactics_bonus`, `morale_threshold` deferred |

---

## 4. Primitives — Coverage

13 implemented (executable end-to-end through the runner); ~30 stubbed.

**Implemented (with notable extensions noted):**
attack_roll · **damage (now with `multiplier` param)** · apply_condition
· heal · granted_action · **attack_modifier (supports `target: ally`)**
· save_modifier · d20_test_modifier · crit_modifier ·
crit_threshold_modifier · **forced_save (area filtering + per-target
target-swap)** · recurring_save · multiattack

**Action types (not primitives, but new declarable types):**
weapon_attack · multiattack · heal · defensive_buff · hard_control
· offensive_buff · aoe_attack (sphere/cone/line, damage and/or
control) · **disengage (PR #26 — sets `actor.disengaging`)**

**Stubbed (most-likely-next-needed):** Action Surge
(`additional_action`), Spirit Guardians (`persistent_aura` +
`triggered_save`), Arcane Recovery (`slot_recovery_partial`),
speed_modifier, damage_modifier, spellcasting_enable, spell_grant.
Note: Dodge no longer needs its own primitive — it's a `defensive_buff`
shape with `target: self`.

Condition definitions for all 15 SRD conditions exist in
`schema/content/conditions/` and feed the modifier registry at
application time.

---

## 5. Worked Behavioral Examples

Each is a deterministic CLI demo (seeded) you can re-run.

### Example 1 — Goblin bullies the wounded PC, then party panics

```
python -m engine.cli encounter tests/fixtures/two_pc_encounter.yaml --seed 1
```

Goblin (cowardly_skirmisher → `weakest_target`) attacks wounded
fighter (5 HP) first; after wounded dies, healthy fighter (Default
retreat → 50% ally-disparity) fails WIS save and flees.

### Example 2 — Cleric heals the dying ally

```
python -m engine.cli encounter tests/fixtures/cleric_heals_ally_encounter.yaml --seed 1
```

Cleric's first action is `healed → fighter_dying +10`. Surviving
goblin panics + flees (Cowardly "1 ally falls").

### Example 3 — Skilled goblin uses both main + bonus action slots

```
python -m engine.cli encounter tests/fixtures/nimble_goblin_encounter.yaml --seed 1
```

Round 1: scimitar (main) + signature off-hand jab (bonus) both fire.

### Example 4 — Pacifist Pass-turns instead of attacking

```
python -m engine.cli encounter tests/fixtures/pacifist_encounter.yaml --seed 1
```

`passed_turn → reason: rp_hard_filter_empty_set` every round. Zero
attack_roll events from pacifist over 7 rounds. Eventually flees
alive.

### Example 5 — Ranged-vs-melee positioning

```
python -m engine.cli encounter tests/fixtures/ranged_vs_melee_encounter.yaml --seed 1
```

Archer shoots from position; goblin closes 30 ft round 1, then 25 ft
round 2 (stops at melee adjacency, not stacked) and attacks.

### Example 6 — Opportunity attack catches goblin slipping past

```
python -m engine.cli encounter tests/fixtures/opportunity_attack_encounter.yaml --seed 1
```

Polearm Guardian (glaive reach 10) catches Goblin moving past:

```
moved: goblin from [3,0] to [1,0]
opportunity_attack_triggered: reactor=guardian, mover=goblin
attack_roll: guardian → goblin (at pre-move position)
attack_roll: goblin → healer (main action completes)
```

### Example 7 — Wizard Fireball at clustered goblins

```
python -m engine.cli encounter tests/fixtures/fireball_cluster_encounter.yaml --seed 1
```

AI picks cluster center as origin; 1 goblin dropped outright, 2 left
at 3 HP.

### Example 8 — Burning Hands cone (NEW PR #24)

```
python -m engine.cli encounter tests/fixtures/burning_hands_cone_encounter.yaml --seed 1
```

Wizard at (0,0); 3 goblins east in a line + 1 goblin north. AI picks
direction `[1, 0]` (east — catches 3 goblins) over north (1 goblin):

```
aoe_origin_placed: direction [1, 0]
forced_save: goblin_east_1 → fail → 9 dmg
forced_save: goblin_east_2 → fail → 12 dmg → DEAD
forced_save: goblin_east_3 → success → 3 dmg HALF
```

### Example 9 — Hypnotic Pattern vs Fireball (NEW PR #25)

```
python -m engine.cli encounter tests/fixtures/hypnotic_pattern_vs_fireball_encounter.yaml --seed 1
```

**The canonical eHP framework worked example.** Wizard with both
spells vs 3 beefy ogres (200 HP each, low WIS save, 4d12+5 attacks).
HP outscores Fireball because per-target control eHP (~40) beats
per-target damage eHP (~24) when targets are too tanky to drop:

```
aoe_origin_placed: wizard → Hypnotic Pattern at [10, 0]
forced_save: ogre_a → fail → Incapacitated applied
forced_save: ogre_b → success
forced_save: ogre_c → fail → Incapacitated applied
concentration_started + spell_slot_consumed (L3, remaining 1)
```

### Example 10 — Dodge under pressure (NEW PR #26)

```
python -m engine.cli encounter tests/fixtures/dodge_disengage_encounter.yaml --seed 1
```

Apprentice (weak mace + Dodge + Disengage) surrounded by 2 brawlers
(3d8+5 greatclubs). AI picks Dodge every round; brawler attacks at
`advantage_state: disadvantage`:

```
turn_start: pc_apprentice    ← picks Dodge silently
turn_start: brawler_a → attack_roll, advantage_state: disadvantage → miss
turn_start: brawler_b → attack_roll, advantage_state: disadvantage → miss
turn_start: pc_apprentice round 2 → Dodge again (previous expired)
```

PC absorbs heavy hits via misses; eventually drops to crits.

### Example 11 — PC schema fighter (compact authoring)

```
python -m engine.cli encounter tests/fixtures/pc_schema_fighter_encounter.yaml --seed 1
```

Level 3 Fighter via 15-line `pc:` spec vs goblin. Engine derives
HP=28, AC=17, PB=2, longsword +5 to hit / 1d8+3. Behaviorally
identical to the legacy inline-template smoke encounter.

### Example 12 — Bless + concentration + slot consumption

```
python -m engine.cli encounter tests/fixtures/bless_buff_encounter.yaml --seed 1
```

Cleric casts Bless on fighter; CON save on damage; concentration
drops; re-cast consumes another slot. Three systems intersect:

```
concentration_started + spell_slot_consumed (L1, remaining 2)
... fighter attacks at +8 instead of +6 (Bless visible) ...
concentration_save: dc=10, dmg=6, d20=6, FAIL
concentration_ended: reason=failed_con_save
... fighter back to +6 ...
concentration_started: round 11 (re-cast, slot consumed)
```

### Example 13 — Multiattack

```
python -m engine.cli encounter tests/fixtures/test_multiattack_encounter.yaml --seed 1
```

Monster with `multiattack: count 2` loops its sub-attack pipeline
twice per turn. PC fighter eventually flees at low HP per Default
retreat trigger.

---

## 6. Test Surface

```
$ python -m unittest discover -s tests
... 375 tests ...
OK
```

| Module | Tests | What it covers |
|---|---|---|
| `tests/test_smoke.py` | 4 | End-to-end: skeleton encounter loads, runs, terminates with a winner |
| `tests/test_primitives_v1.py` | 12 | Attack roll w/ modifiers; condition application; Q5 modifier query; multiattack loop |
| `tests/test_ai_v1.py` | 19 | All 5 targeting presets; behavior profile resolution; ability selection; finish-off rule |
| `tests/test_ehp_scoring.py` | 34 | Pure-math helpers; expected damage; overkill cap; aggression; tactical preset; Blinded target |
| `tests/test_defensive_ehp.py` | 34 | Desperation; healing; DPR estimation; defensive buff; hard control; cleric integration |
| `tests/test_action_economy.py` | 30 | Preset table; main-slot optimality; bonus-slot gating; runner integration |
| `tests/test_retreat.py` | 26 | Preset bundle; mindless override; triggers; Resolute compound; WIS save mechanics |
| `tests/test_rp_constraints.py` | 19 | Library + active-constraint resolution; hard filter; forced choice; weighted preference |
| `tests/test_positioning.py` | 29 | Geometry; closest_enemy distance; reach filter; out-of-range guard; runner movement |
| `tests/test_opportunity_attacks.py` | 16 | Trigger detection; reaction slot; AE percentage gating; runner integration |
| `tests/test_aoe.py` | 15 | actors_in_radius; damage multiplier; sphere AoE eHP; friendly fire; end-to-end Fireball |
| `tests/test_pc_schema.py` | 26 | PB / HP / AC / save bonus math; weapon action gen; loader integration; fixture run |
| `tests/test_offensive_buff.py` | 17 | extract; eHP math; ally-DPR scaling; advantage > +2 flat; dedup; runner integration |
| `tests/test_concentration.py` | 18 | Slot management; new-cast-replaces; CON save mechanics; damage hook; death hook |
| `tests/test_spell_slots.py` | 25 | Formula (framework reference); has_slot / consume_slot; filter; eHP cost subtraction |
| `tests/test_aoe_cone_line.py` | 27 | unit_direction; cone / line geometry; candidate gen direction; scoring; end-to-end |
| `tests/test_aoe_control.py` | 13 | Control component extraction; per-target control eHP; mixed damage+control AoE; HP fixture |
| `tests/test_dodge_disengage.py` | 11 | Disengaging field; Dodge modifier attachment; defensive_buff_rounds override; OA suppression; behavioral |

**Fixtures (`tests/fixtures/`):** `smoke_encounter.yaml`,
`two_pc_encounter.yaml`, `test_multiattack_encounter.yaml`,
`cleric_heals_ally_encounter.yaml`, `nimble_goblin_encounter.yaml`,
`pacifist_encounter.yaml`, `ranged_vs_melee_encounter.yaml`,
`opportunity_attack_encounter.yaml`, `fireball_cluster_encounter.yaml`,
`pc_schema_fighter_encounter.yaml`, `bless_buff_encounter.yaml`,
**`burning_hands_cone_encounter.yaml`**,
**`hypnotic_pattern_vs_fireball_encounter.yaml`**,
**`dodge_disengage_encounter.yaml`**.

---

## 7. Roadmap — Honest Gap List

The engine has the **decision shape** right (Ammann pillar dials +
eHP framework as the scoring spine + RP Constraints as the identity
overlay), the **spatial shape** right (positions, reachability,
reactions, three AoE shapes), the **resource shape** right
(concentration + spell slots), AND a growing set of **basic action
types** (Dodge / Disengage / Help-Hide as the natural family). The
framework doc's canonical Fireball-vs-Hypnotic-Pattern worked
example is now a deterministic CLI demo. Remaining work is content
breadth, additional primitives, and depth-within-system. In rough
priority order:

1. **PCs default to Dodge in RP empty-set fallback** per
   `pillars-reconciliation.md` §6.4 — small follow-on to #26. Replace
   `passed_turn` with Dodge execution when PC has it available.
2. **Built-in basic actions** — Dodge / Disengage / Help / Hide
   should be available to ALL actors implicitly per RAW. v1 requires
   explicit template declaration; built-in pool is a small follow-on.
3. **Help action** — same shape as Dodge / Disengage (new action type
   + built-in entry). Small focused PR. **Hide is deferred until a
   terrain / cover / line-of-sight layer exists** — Hide RAW requires
   heavy obscurement or total cover to break LOS from observers, and
   `geometry.py` currently models bare positions with no occlusion.
   When terrain modeling is built (its own arc — it also unlocks cover
   bonuses on ranged attacks and obscurement spells like Fog Cloud /
   Darkness), Hide can land as a natural follow-on with the same
   built-in / explicit-declaration shape as Dodge.
4. **Class features auto-wiring** — Action Surge + Second Wind
   shipped via PRs #31-33. PR #31 added the runner-level Action Surge
   activation; PR #32 added `derive_pc_resources` for the counters;
   PR #33 added the generic `feature_uses` gate + the auto-generated
   Second Wind bonus-action (heal 1d10 + fighter_level on self,
   consumes `second_wind_uses_remaining`). Remaining: Fighting Style
   passive modifiers, Extra Attack → multiattack generation, Weapon
   Mastery property tags, Wizard Arcane Recovery (pending
   `slot_recovery_partial` primitive — also feature_uses-shaped).
6. **Spirit Guardians + persistent-aura primitives** —
   `persistent_aura` + `triggered_save` (movement-triggered damage in
   an area around the caster).
7. ~~**Incapacitation ending concentration** — small follow-on to #21.
   Particularly relevant now that Hypnotic Pattern can apply
   Incapacitated.~~ **Shipped in PR #34.** Stunned / Paralyzed /
   Unconscious / Petrified / Incapacitated all end concentration via
   a hook in `_apply_condition`. Frightened / Charmed / Poisoned do
   NOT (RAW). Hypnotic Pattern's Incapacitated application now
   correctly drops the target's concentration too.
8. ~~**Named-effect tagging** for cross-caster buff dedup — small
   follow-on to #20.~~ **Shipped in PR #36.** Actions declare
   `named_effect: <string>`; modifier sources carry it; the
   `buff_already_active` helper in `engine.ai.named_effects` returns
   True for any matching named_effect on the target (cross-caster
   aware) or falls back to per-(caster, action_id) for untagged
   actions. RAW: PHB 2024 p.243 "same spell doesn't stack."
9. ~~**Wizard Arcane Recovery + slot_recovery_partial primitive**~~ —
   **Shipped in PR #37.** New `slot_recovery_partial` primitive
   restores expended slots greedily (highest-first) within a combined-
   level budget. New `engine/core/rest.py` module exposes
   `apply_short_rest(actor, state)` — per-class dispatch (Wizard fires
   Arcane Recovery; Fighter refreshes Second Wind +1 + Action Surge
   to full per RAW). `Actor.spell_slots_max` tracks the post-rest
   ceiling. `derive_pc_resources` auto-wires
   `arcane_recovery_uses_remaining: 1` for Wizard L1+. Runner stays
   single-encounter; multi-encounter session work will call
   `apply_short_rest` between encounters.
10. ~~**Fighting Style** — passive modifier infra~~ — **Shipped in
   PR #38.** `pc:` spec accepts `fighting_style: <id>` field.
   Defense (+1 AC when armored, SRD), Dueling (+2 damage on 1H
   melee, SRD), Archery (+2 attack on ranged, user_authored) all
   wired. Bonuses are baked into the generated weapon actions / AC
   computation at template build time (no runtime modifier registry
   needed for always-on passives). Weapon spec gains optional
   `two_handed: bool` for Dueling's exclusion. GWF / Protection /
   Two-Weapon Fighting / Blind Fighting deferred (each needs
   additional infra — damage re-roll, reactions, off-hand support,
   vision).
11. ~~**Extra Attack auto-generation** at L5/L11/L20~~ — **Shipped
   in PR #39.** `_build_feature_actions` detects `f_extra_attack`
   (count=2 at L5), `f_two_extra_attacks` (count=3 at L11),
   `f_three_extra_attacks` (count=4 at L20) and auto-generates a
   `type: multiattack` action referencing the first weapon repeated
   `count` times. Composes naturally with Action Surge (4 attacks
   per turn at L5 round 1: 2 from multiattack × 2 from AS) and
   Fighting Style (Dueling's +2 damage applies per swing).
12. ~~**`apply_long_rest`**~~ — **Shipped in PR #40.** Sibling to
   PR #37's short rest. Universal: HP → hp_max, all spell slots →
   spell_slots_max, end concentration (RAW: sleep ends it), expire
   `until_long_rest` modifiers. Per-class for PCs: Fighter (Action
   Surge full / Second Wind full), Wizard (Arcane Recovery → 1).
   Closes the rest-cycle arc; multi-encounter session work is the
   next obvious macro item.
13. ~~**Multi-encounter session runner**~~ — **Shipped in PR #41.**
   `engine/core/session.py` exposes `run_session(spec, seed)` and
   composes EncounterRunner + rest helpers into an "adventuring
   day" sim. `SessionSpec` declares the encounter sequence + rest
   plan + party_actor_ids. Party state (HP / slots / resources /
   modifiers) carries across encounters; concentration ends at
   each boundary; dead party members are excluded from subsequent
   encounters; fled members return. This is what makes the
   resource-management mechanics (AS / SW / AR / spell slots)
   actually matter — pre-#41 those decrement-once mechanics never
   refreshed because nothing called the rest helpers.
14. ~~**Pace-aware Action Surge**~~ — **Shipped in PR #42.** New
   `engine/core/feature_pacing.py` exposes a feature-use cost
   formula: `cost = base_cost × scarcity × urgency_factor` where
   scarcity = 1/charges, urgency_factor = encounters_remaining/3.
   `_maybe_activate_action_surge` now scores the best in-reach
   attack candidate and only activates AS if `gain > cost`.
   `runner.run()` gained an `encounters_remaining_today` parameter
   that the session runner passes per-encounter, so the fighter
   sees high urgency early in the day (12 cost at 6 encounters
   remaining) vs. low urgency late (2 cost at last encounter).
   The L2 Fighter now saves AS for the boss instead of dumping it
   on the warm-up fight. Activation event log now carries
   `gain_eHP` / `cost_eHP` for telemetry.
15. ~~**Spirit Guardians + persistent_aura primitive**~~ —
   **Shipped in PR #43.** New `persistent_aura` primitive registers
   a self-anchored area effect (moves with the caster) in
   `state.persistent_auras`. Runner hook
   `_resolve_persistent_aura_triggers` fires forced saves on each
   creature's turn-start while they're within the aura's radius.
   Concentration-tied: `end_concentration` scrubs the aura when
   concentration drops (via damage CON save fail, new concentration
   cast, caster incapacitation, etc. — composes with PRs #21, #34).
   eHP scoring sums per-turn expected damage across in-radius
   enemies × EXPECTED_AURA_ROUNDS (2.5). v1 scope: turn-start
   trigger only (no entry-on-move trigger), no speed-halving —
   both deferred. `affected: enemies` default is RAW-faithful
   for Spirit Guardians specifically.
16. ~~**More persistent_aura spells** (Moonbeam + Cloud of
   Daggers)~~ — **Shipped in PR #44.**
17. ~~**Reaction infrastructure + Shield + Protection + Hellish
   Rebuke**~~ — **Shipped in PR #45.** New trigger event vocabulary
   (`attack_targeting_resolved`, `attack_roll_pending`, `damage_taken`)
   + generic reaction system in `engine/core/reactions.py`
   (`resolve_reaction_triggers` / `try_use_reaction` / condition
   vocabulary). Actions tagged `trigger: <event>` register as
   reactions; `pipeline.generate_candidates` filters them out of
   main / bonus pools. Reactions auto-fire when events match + slot
   available (v1 always-use; pace-aware scoring deferred).
   `_attack_roll` re-queries `attack_modifiers` after
   `attack_roll_pending` so Shield's +5 AC takes effect on the
   triggering attack. Three spells shipped: `f_shield.yaml` (SRD,
   wizard 1st — retroactive AC bump), `f_fs_protection.yaml` (4th
   Fighting Style option, non-SRD — impose disadvantage on attack
   against adjacent ally), `f_hellish_rebuke.yaml` (SRD warlock 1st,
   not class-wired — fixtures attach manually; retaliation against
   damaging attacker). Counterspell explicitly deferred — needs
   cast-event hook + spell-fizzle + ability-check infra; own PR. Three pieces of new infra
   on top of PR #43:
   - **`anchor: point`** mode — area placed at a chosen point at
     cast time, doesn't move (vs. `anchor: caster` which moves
     with the caster). Origin captured from
     `state.current_attack.area_origin` (set by the candidate
     generator for point-anchored auras, same pattern as Fireball).
   - **Cube area shape** — new `actors_in_cube` geometry helper
     with center-on-origin semantics (5-ft cube = 1 square,
     10-ft = 3×3, 20-ft = 5×5).
   - **No-save path** — `ability: 'none'` in the persistent_aura
     params skips `forced_save` and invokes `on_fail`
     sub-primitives directly (always-damage). Emits the new
     `persistent_aura_no_save_trigger` event.
   Two new spell YAMLs ship in `schema/content/features/`:
   `f_moonbeam.yaml` (Druid 2nd, SRD — sphere/point/all_creatures/CON
   save) and `f_cloud_of_daggers.yaml` (Wizard 2nd, SRD — cube/
   point/all_creatures/no-save). Spiritual Weapon was deliberately
   cut from this PR — it's a summoned-creature mechanic, not a
   persistent_aura, and deserves its own design pass.
9. ~~**Per-creature recurring save** to break Hypnotic Pattern at
   end-of-turn — would mirror single-target `recurring_save` for AoE.~~
   **Shipped in PR #35.** The existing single-target `recurring_save`
   primitive worked unchanged for AoE — `forced_save`'s per-target loop
   already swapped `state.current_attack.target` per-iteration before
   invoking sub-primitives, so dropping `recurring_save` into an
   AoE's `on_fail` block registers one entry per failed creature with
   the correct target_id. Hypnotic Pattern's fixture now wires this
   step; held creatures roll WIS at end of their own turns to break free.
10. **3-level profile inheritance** + runtime override layer
    (Frightened / Dominate / Confusion) per §4.4.
11. **Behavioral coefficients beyond aggression** —
    `self_preservation_coefficient`, `pack_tactics_bonus`,
    `morale_threshold`.
12. **Pyodide / browser deployment** — Stage 2 task per
    `docs/architecture/browser-deployment.md`.

---

## 8. Source of Truth Pointers

| For this question | Read this |
|---|---|
| What dial presets exist and what do they mean? | `docs/foundations/pillars-reconciliation.md` §5 |
| What eHP formulas govern action scoring? | `docs/foundations/ehp-action-framework.md` |
| How are RP Constraints structured (3 types, severity, priority)? | `docs/foundations/pillars-reconciliation.md` §6 |
| How does the schema represent monsters / PCs / spells / conditions? | `docs/architecture/schema-design.md` |
| Why Pyodide is a viable Stage 2 deployment target | `docs/architecture/browser-deployment.md` |
| What's the rationale for a specific decision in the AI / core module? | The module docstrings in `engine/ai/*.py` and `engine/core/*.py` |
| When was X shipped, with what scope, and what was deferred? | `docs/SESSIONS.md` (chronological) + PR descriptions |
| What's the current snapshot for paste-at-session-start? | `docs/CONTEXT.md` |
