# Engine Capabilities — Checkpoint

**Last updated:** 2026-05-27
**Engine state:** Phase 1, post-PR #26 (Dodge + Disengage merged).
**Test surface:** 1403 tests across 60+ modules; 14 CLI fixtures.

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
   Rebuke**~~ — **Shipped in PR #45.**
18. ~~**Counterspell + cast-event infra**~~ — **Shipped in PR #46.**
19. ~~**Vision system v1**~~ — **Shipped in PR #47.**
54. ~~**Paladin spellcasting v1: Bless + Shield of Faith**~~ —
   **Shipped in PR #82.** Paladins finally have spell candidates,
   not just slots. Two iconic 1st-level Paladin spells ship via
   the existing offensive_buff / defensive_buff scoring paths.
   - **New `f_bless.yaml`** — 1st-level offensive_buff,
     concentration, named_effect: bless. Pipeline registers an
     `attack_modifier` (target=ally, when=attacker_is_self,
     modifier=attack_bonus, value=2) AND a `save_modifier`
     (target=ally, modifier=flat, value=2). v1 uses flat +2 as
     a deterministic approximation of RAW's 1d4 (avg 2.5).
   - **New `f_shield_of_faith.yaml`** — 1st-level
     defensive_buff, Bonus Action, concentration, named_effect:
     shield_of_faith. Pipeline registers `attack_modifier`
     (target=ally, modifier=ac_modifier, value=2) — the existing
     `query_attack_modifiers` reads target-side ac_modifier
     entries to bump effective AC.
   - **`c_paladin` L2 features** extended to list `f_bless` +
     `f_shield_of_faith`. Both attach automatically when the
     Paladin has 1st-level slots.
   - **`pc_schema.build_pc_template`** extended with a generic
     "feature → action_template auto-attach" pass — any feature
     in `features_known` whose YAML declares an
     `action_template` block gets the dict copied into
     `template.actions`. Future spell-shape features just need
     a YAML; no Python builder needed. Skips when an action
     with the same id is already in the list (preserves
     hardcoded builders' precedence).
   - **AI scoring** uses the existing
     `offensive_ehp_buff_ally` (Bless's attack-bonus scoring
     from PR #36) and `defensive_ehp_defensive_buff` (Shield of
     Faith's AC-bonus scoring from PR #43) — no new scorers
     needed.
   - **Cross-caster dedup** works out of the box via PR #36's
     `named_effect` path — two Paladins can't double-Bless the
     same ally.
   - **Concentration** is wired via the existing
     `pipeline.execute` concentration handling — both spells
     correctly take up the caster's concentration slot.
   - **`when: attacker_is_self`** discriminator on Bless's
     attack_modifier prevents the +2 from spuriously buffing
     enemies attacking the blessed ally (same pattern as Vex
     mastery's directional gate from PR #54).
   - 15 new tests across 11 layers (YAML loading, class
     wiring at L2, action shape, L1-gate, candidate generation
     per-ally enumeration, scoring positive value for both
     spells, cross-caster dedup, end-to-end attack/save/AC
     modifier application).
   - Deferred:
     * **Heroism** — needs temp-HP-per-turn mechanic that
       the engine doesn't model yet
     * **Multi-target Bless** (RAW: up to 3 creatures per cast)
       — needs candidate-grouping extension; v1 emits per-ally
       and the AI picks the best one
     * **Per-roll 1d4** — v1 uses flat +2; future
       `roll_modifier` primitive could roll the d4 at
       resolution time
     * **Upcast scaling** for Bless (+1 ally per slot above
       1st) — non-dice scaling, same PR #77 schema-extension
       residue as Fog Cloud's radius scaling
     * **Spell preparation** — RAW Paladins prepare spells from
       their list; v1 auto-attaches Bless + SoF unconditionally
       to any Paladin L2+. A future Paladin spell-prep PR would
       model the prepared-spells list.
     * **Other Paladin spells** — Heroism / Searing Smite /
       Compelled Duel / Wrathful Smite / Divine Favor /
       Protection from Evil and Good etc.

53. ~~**Rogue Cunning Strike (L5+)**~~ — **Shipped in PR #81.**
   Trade 1d6 of Sneak Attack damage for one of three effects.
   Integrates into the SA path; AI heuristic picks the best
   effect or skips (full damage) when no effect beats the cost.
   - **New `engine/core/cunning_strike.py`** module: registry,
     DC formula (8 + DEX_mod + PB), qualification (L5+),
     AI heuristic, effect application.
   - **Three v1 options** (all cost 1d6 of SA dice):
     * **Poison**: CON save → Poisoned condition on fail
       (disadvantage on attacks + ability checks, ~2.5 rounds
       in scoring estimate)
     * **Trip**: DEX save → Prone on fail (Large or smaller
       size gate)
     * **Withdraw**: free Disengage + extra half-speed move
       (v1: sets actor.disengaging=True; OA suppression is
       the load-bearing value)
   - **Corrected Trip value model** (per Phil's note): Prone
     target stands at start of their next turn by spending
     half their movement, so they DON'T attack at
     disadvantage on their own turn (they stand first), and
     the Rogue who applied Trip DOESN'T benefit on their
     own next swing (target stands before they swing). Trip
     is fundamentally a **party-coordination move**: only
     allies whose initiative slot falls AFTER the attacker but
     BEFORE the target's next turn get the value. Uses
     `estimate_dpr` (multi-attack-aware) per ally so Fighters
     with Extra Attack correctly amplify the value beyond
     single-attack allies. Solo Rogues won't pick Trip — math
     correctly returns 0.
   - **`_allies_acting_before_target`** helper: walks
     `state.turn_order` from attacker's index forward,
     collecting allies until hitting the target's slot.
   - **SA integration**: `try_apply_sneak_attack` calls
     `pick_cunning_strike_effect` before rolling; reduces dice
     count by the cost; applies the effect after damage. SA
     event log includes `cunning_strike` + `cunning_strike_cost_dice`
     fields when fired.
   - **Class table**: `f_cunning_strike` added to Rogue L5.
   - **New `f_cunning_strike.yaml`** feature (passive, no
     auto-generated action — fires inside the SA path).
   - 24 new tests across 14 layers (DC formula, qualification,
     registry, AI heuristic: skip / Trip with party / Withdraw
     surrounded / solo skips Trip / L4 returns None; effect
     application: Trip→Prone, Trip size gate, Withdraw→Disengage,
     Poison→Poisoned; SA integration: dice reduced, full when
     skipped, L4 skips entirely; YAML wiring).
   - Deferred:
     * **Party coordination + initiative manipulation** as a
       broader AI topic (Ready Action, holding initiative,
       Help-action timing) — Phil flagged this as worth a
       dedicated arc; Trip's value calc is the simplest case
       of it
     * Devious Strikes (Rogue L11; adds Dazed / Knock Out /
       Obscure options with higher dice costs)
     * Improved Cunning Strikes (Rogue L14; allows two
       Cunning Strike effects on one Sneak Attack)
     * "Vial of basic poison" RAW prereq for Poison (assumed
       available in v1)
     * Withdraw's half-speed move cap (v1 uses Disengage's
       OA-suppression as the load-bearing value)

52. ~~**Rogue Steady Aim (L3 BA)**~~ — **Shipped in PR #80.**
   Pairs with PR #74's Cunning Action BA infrastructure. RAW
   PHB 2024: as a Bonus Action, gain advantage on next attack
   roll this turn; speed becomes 0 for the rest of the turn;
   requires you haven't moved this turn.
   - **New `steady_aim` primitive**: registers an
     `attack_modifier` (target=self, modifier=advantage,
     lifetime=per_owner_attack — consumes on next swing) AND
     sets `actor.moved_this_turn = True` (RAW: speed becomes 0
     for the rest of this turn). Logs `steady_aim_taken` event.
   - **Eligibility gate** wired generically: actions declare
     `requires_no_movement: true`; the pipeline candidate
     generator filters them out when
     `actor.moved_this_turn == True`. Future Stand-Still-shape
     actions reuse the same flag.
   - **Auto-generated `a_steady_aim` action** for Rogue L3+
     PCs via `_build_steady_aim_action`. Type=`defensive_buff`
     (routes through the self-targeted dedup),
     `slot: bonus_action`, `is_signature: false` (highly
     tactical — only valuable when SA conditions otherwise
     unfavorable).
   - **`is_self_targeted_defensive_buff`** extended to
     recognize `steady_aim` (same pattern as PR #71's
     rage_start, PR #74's dash).
   - **AI scoring** via new `_score_steady_aim` in
     `defensive_ehp`: returns
     `actor.expected_per_attack_damage × DELTA_HIT_FROM_ADVANTAGE`
     (~22.5% of base attack damage, the framework's standard
     advantage value). Returns 0 when no enemies.
   - **Class table**: `f_steady_aim` added to Rogue L3 row.
   - **New `f_steady_aim.yaml`** declares the feature shape.
   - 14 new tests across 12 layers (primitive registers
     advantage + sets moved + logs; modifier consumes on next
     attack; self-targeted recognition; AI scoring positive /
     zero cases; pipeline filter blocks after movement /
     emits without movement; pc_schema L1/L2/L3 gating + shape;
     feature YAML loading).
   - Deferred:
     * Sneak Attack synergy uplift in AI scoring (advantage
       guarantees SA fires; deferred uplift for Rogues without
       adjacent ally)
     * "Advantage expires on miss" pedantic RAW detail
     * Pre-targeting a specific enemy (v1 grants advantage on
       the NEXT attack regardless of which target)

51. ~~**More zone-creating spells: Fog Cloud / Stinking Cloud /
   Web / Silence**~~ — **Shipped in PR #79.** Four PHB 2024
   zone spells added, each exercising different aspects of the
   existing zone substrate.
   - **Fog Cloud** (1st-level Wizard): 20-ft sphere of
     heavy_obscurement, no damage. Zero-infrastructure — just a
     new YAML using the existing `creates_zone: heavy_obscurement`
     path from PR #68. Scored via PR #78's hybrid path
     (damage_value=0 + zone_value).
   - **Stinking Cloud** (3rd-level Wizard): 20-ft sphere, CON
     save on turn-start; on fail apply `co_incapacitated` for
     until_actor_next_turn_start. RAW "uses Action doing
     nothing" → Incapacitated already gates actions per PR #34.
     Lightly-obscured aspect deferred (engine doesn't model
     light obscurement beyond binary visibility).
   - **Web** (2nd-level Wizard): 20-ft CUBE shape with DEX save;
     on fail apply `co_restrained` for until_actor_next_turn_start
     (re-saved each turn-start). Exercises the cube-shape path
     (`actors_in_cube`). Difficult-terrain aspect deferred (no
     per-square movement cost yet); Athletics-check escape
     deferred (v1 uses the turn-start re-save as the escape
     opportunity).
   - **Silence** (2nd-level Cleric): 20-ft sphere with new
     **`silence_zone` zone type** that suppresses spellcasting
     for actors inside. New entries:
     - `_CREATES_ZONE_TO_ENV_KEY["silence"] = "silence_zones"`
     - `concentration.py::_SCRUBBABLE_ZONE_KEYS` adds
       `"silence_zones"` so concentration drop scrubs the zone
     - New `pipeline._actor_in_silence_zone(actor, state)`
       predicate (sphere geometry via Chebyshev distance)
     - New pipeline filter step after the feature-use filter:
       actors inside a silence_zone have all spell candidates
       (`spell_slot_level >= 1`) removed. Cantrips
       (spell_slot_level=0) and weapon attacks unaffected.
   - 13 new tests across 10 layers (YAML loading for all four;
     silence predicate + filter for inside/outside actors +
     cantrip-passthrough + weapon-attack-passthrough;
     concentration-drop scrubs silence_zone; Fog Cloud zone
     registration; Stinking Cloud incapacitation; Web
     Restrained).
   - **AI scoring** for silence is a known gap — silence isn't
     vision-denial (which is what PR #78 scores) but
     caster-denial. The pipeline filter prevents enemies inside
     from casting; the AI's value estimate doesn't yet credit
     silence with the suppression value. Deferred follow-up.
   - Deferred:
     * Stinking Cloud's lightly-obscured area
     * Web's difficult terrain + Athletics-check escape
     * Silence's Deafened-in-sphere + Thunder-damage immunity
       in-sphere
     * Per-spell V-component declaration (v1 treats all spells
       as Verbal for the Silence filter)
     * AI scoring uplift for Silence's caster-denial value
     * Wind dispersal for Fog Cloud
     * Upcast for Fog Cloud (RAW: +20 ft radius per slot above
       1st — non-dice scaling)

50. ~~**AI scoring for damage+zone hybrid auras**~~ — **Shipped
   in PR #78.** Closes the PR #68 residue. Auras that BOTH
   deal damage AND create a vision-denial zone (HoH = cold +
   magical_dark; Cloudkill = poison + heavy_obscurement) now
   score with BOTH components summed instead of one masking
   the other.
   - **Generalized `offensive_ehp_zone_vision_denial`** —
     parameterized version of PR #61's Darkness scorer. Takes
     explicit `radius_ft` + `zone_type` instead of hardcoding
     the 15-ft Darkness sphere. Handles both `magical_dark`
     (blindsight OR truesight pierces) and `heavy_obscurement`
     (blindsight ONLY pierces; truesight does NOT — fog is
     physical per RAW).
   - **Backward-compat `offensive_ehp_darkness` wrapper** —
     calls the generalized helper with Darkness defaults
     (radius_ft=15, zone_type='magical_dark'). Existing
     callers / tests unchanged.
   - **`offensive_ehp_persistent_aura` restructure** — no
     longer early-returns to the Darkness scorer for
     `magical_dark`. Instead always computes the damage
     component (returns 0 when the aura has no damage
     payload), then ALWAYS adds the zone component when
     `creates_zone` is in
     `_VISION_DENIAL_ZONE_TYPES` (`magical_dark` /
     `heavy_obscurement`). Sum = final score.
   - **`_VISION_DENIAL_ZONE_TYPES` constant** centralizes the
     zone-type registry; new zone types extend the set.
   - **Effect on HoH / Cloudkill scoring**: AI now prefers
     these spells when BOTH the damage AND the zone are
     valuable (party can capitalize on the zone effect AND
     enemies sit in the damage area). Previously HoH was
     routed to vision-denial-only (missed cold damage);
     Cloudkill was routed to damage-only (missed heavy
     obscurement value).
   - **Effect on Darkness scoring** — unchanged. No damage
     payload, full zone score.
   - **Effect on Cloud of Daggers scoring** — unchanged. No
     `creates_zone`, damage-only.
   - 10 new tests across 10 layers (zone scorer parameterization,
     magical_dark TS/BS pierce, heavy_obscurement TS-does-NOT
     pierce / BS pierces, radius respects param, wrapper
     parity, HoH hybrid, Cloudkill hybrid, CoD unchanged,
     Darkness unchanged).
   - Deferred:
     * AI scoring of allies who would lose vision in the
       zone (currently the cost mirrors the benefit; per-
       creature attack-frequency weighting deferred)
     * "Caster forgot to put themselves in the sphere"
       opportunity-cost subtraction

49. ~~**Upcast scaling for damage spells**~~ — **Shipped in
   PR #77.** Closes the PR #67 residue. Spells that declare an
   `upcast_scaling` block now actually cast at higher slot
   levels: the candidate filter accepts higher slots when the
   exact base level is unavailable; the executor picks the
   lowest available slot ≥ base; the damage primitive applies
   the per-level bonus dice.
   - **New helpers in `engine/core/spell_slots.py`:**
     `lowest_available_slot_at_or_above`, `is_upcastable`,
     `has_slot_for_action`, `resolve_chosen_slot_level`. All
     handle the cantrip / exact-level / upcastable cases
     uniformly so callers don't repeat the dispatch.
   - **Pipeline filter** (`generate_candidates`) now uses
     `has_slot_for_action` — upcastable spells pass when ANY
     slot ≥ base is available; non-upcastable still need exact.
   - **Pipeline `execute`** computes `chosen_slot_level` via
     `resolve_chosen_slot_level` (defaults to base, picks
     lowest available ≥ base for upcastable), stashes it on
     the `chosen` dict and `state.current_attack`, and consumes
     it (not the base level) from the slot pool. Counterspell
     also sees the chosen level via `spell_cast_initiated`.
   - **Reaction execute path** (`try_use_reaction`) mirrors the
     same: gate via `has_slot_for_action`, resolve chosen
     slot, stash on state, consume the chosen level. Hellish
     Rebuke now upcasts correctly via the reaction path.
   - **`_damage` primitive** calls new
     `_resolve_upcast_extra_dice` helper which reads
     `state.current_attack.chosen_slot_level` and
     `action.upcast_scaling`. Adds
     `extra_dice_per_level × (chosen − base)` dice; optional
     `damage_type` filter scopes bonus to matching damage
     steps (so multi-type spells don't double-count). Crit
     doubles the upcast dice same as base dice.
   - **Persistent aura path also wired**: aura registration
     captures `chosen_slot_level` + the action's
     `spell_slot_level` + `upcast_scaling` block; runner's
     `_resolve_persistent_aura_triggers` synthesizes an
     action dict with these fields when invoking on_fail /
     on_success sub-primitives. Hunger of Hadar and Cloudkill
     per-turn damage now scales correctly when cast at a
     higher slot.
   - **Existing spells wired** with `upcast_scaling`:
     * Hellish Rebuke: +1d10 fire per slot above 1st
     * Hunger of Hadar: +1d6 cold per slot above 3rd
     * Cloudkill: +1d8 poison per slot above 5th
   - **AI scoring** of upcast: currently picks LOWEST
     available slot (matches Divine Smite v1 from PR #73 —
     RAW best practice). A follow-up PR can extend AI to dump
     higher slots when burst value justifies it.
   - 31 new tests across 13 layers (helpers, filter, executor,
     damage primitive helper math, damage_type filter, crit
     doubling, end-to-end HP delta, YAML wiring on HR / HoH /
     Cloudkill).
   - Deferred:
     * AI choosing HIGHER-than-lowest slot when burst worth
       it (current = lowest-available)
     * Non-damage upcast (Magic Missile +1 dart, Hold Person
       +1 target, Bless +1 ally, etc.) — would need
       `upcast_scaling` extensions for non-dice patterns
     * Upcasting in candidate scoring (the eHP scorer doesn't
       yet factor upcast bonus damage when comparing candidates
       — the AI uses upcast when forced but doesn't actively
       prefer it)

48. ~~**Total cover auto-miss**~~ — **Shipped in PR #76.**
   Closes the PR #48 residue. Adds `'total'` as a fourth cover
   state and wires the RAW PHB 2024 behavior: "a target with
   total cover can't be the target of an attack or a spell"
   (though AoE effects that cover the area still apply).
   - **`Actor.cover`** state extended to four values: `none` /
     `half` / `three_quarters` / `total`. Total is a target-
     cancel, not an AC bump — `_cover_ac_bonus` returns 0 for
     total (matching the half/three_quarters precedent that
     it's an AC modifier function).
   - **`_attack_roll` early auto-miss** when target has total
     cover. Short-circuits before the d20 roll (no RNG
     consumed); emits `attack_roll` event with
     `result: "miss"` and `reason: "total_cover"`. Defends the
     multiattack sub-attack path and any direct primitive
     callers.
   - **Candidate generator filters** total-cover enemies from
     single-target candidate lists: `weapon_attack`,
     `multiattack`, `hard_control`. Computed as
     `targetable_enemies` once at the top of
     `generate_candidates`; per-action-type branches consume
     the filtered list.
   - **AoE attacks (`aoe_attack`) unchanged** — they enumerate
     all living enemies as anchor positions regardless of
     cover, because area effects cover space (not specific
     creatures). RAW: "AoE effects that include them" still
     hit total-cover targets. Existing
     `actors_in_radius` / `actors_in_cone` / `actors_in_line`
     are position-based and ignore cover.
   - **`_is_total_cover(target)`** helper exposed for any
     future callers (other attack-shaped primitives that need
     the same gate).
   - 17 new tests across 10 layers (`_cover_ac_bonus` returns
     0 for total, predicate, attack_roll auto-miss + event
     telemetry, RNG-not-consumed defense, other cover values
     still work, candidate generator filters for
     weapon_attack / multiattack / hard_control, AoE still
     hits total-cover targets, mixed scenario).
   - Deferred:
     * Per-(attacker, target) cover based on terrain geometry
       (current per-actor symmetric cover stays unchanged)
     * Reaction-driven cover changes mid-attack (none in v1)
     * Total cover ↔ vision blocking link (currently
       independent: total cover means "can't target"; visibility
       is a separate vision check)

47. ~~**SRD races v1 + save-source context**~~ — **Shipped in
   PR #75.** First per-race substrate. Ships the four SRD CC
   v5.2.1 species (Dwarf / Elf / Halfling / Human) with sizes,
   speeds, darkvision, racial traits, and damage resistances —
   plus the new save-source-context infrastructure that lets
   "advantage on saves vs X condition" traits actually fire
   correctly without dragging trait knowledge into the
   primitives.
   - **New `race` entity type** registered in the loader; new
     `schema/content/races/` directory with 4 species YAMLs
     (`r_dwarf`, `r_elf`, `r_halfling`, `r_human`).
   - **New `engine/core/racial_traits.py` module**: trait
     registry (`SAVE_CONDITION_TRIGGERS`), `has_racial_trait`
     predicate, `racial_save_advantage_for` resolver,
     `lucky_d20` reroll helper, save-context builders
     (`build_save_context`, `build_save_context_for_condition`).
   - **New `Actor.racial_traits: list` field** — loaded from
     `template.racial_traits` (stamped by pc_schema from the
     race YAML) by cli; supports actor_spec override for
     fixture flexibility. Empty for non-PC actors.
   - **New `state.current_save_context: dict | None`** —
     stashed by `_forced_save` BEFORE the per-target loop +
     by `_resolve_recurring_saves` before each save query.
     Restored to the prior value after to allow defensive
     nesting (no spell nests today, but the pattern is
     correct). Shape: `{"applied_conditions_on_fail": [...]}`.
   - **`query_save_modifiers` reads the context** and the
     target's `racial_traits` via `racial_save_advantage_for`;
     grants advantage when any trait's triggering condition
     matches the in-flight save's on_fail conditions. Sources
     list includes `{"type": "racial_trait", "trait": ...}`
     for telemetry.
   - **Halfling Lucky** (reroll natural 1 on d20) wired in:
     * `_attack_roll` — after advantage/disadvantage resolution
       on the chosen d20
     * `_forced_save` — same shape, on the target's chosen d20
     * `_resolve_recurring_saves` — runner-side recurring saves
   - **Halfling Brave / Elf Fey Ancestry / Dwarven Resilience
     save advantage** all resolve via the save-context path —
     advantage when the on_fail block applies
     `co_frightened` / `co_charmed` / `co_poisoned`
     respectively.
   - **Dwarf poison damage resistance** baked onto the
     template's `damage_resistances` list at PC-build time;
     handled by the existing template-side `_damage`
     resistance check.
   - **Sizes correctly stamped**: Halfling is Small (gates Push
     mastery immunity per PR #65); Dwarf / Elf / Human are
     Medium.
   - **Darkvision 60 ft** stamped on Dwarf + Elf via the
     existing `Actor.darkvision_range_ft` field (PR #50).
   - **Human Skillful** — pc_spec.extra_skill picks one
     additional skill proficiency at build time; appended to
     `skill_proficiencies` if not already present.
   - **Speed inheritance**: pc_spec.speed > race.speed > 30 ft
     default.
   - 39 new tests across 14 layers (module helpers,
     save-source context, advantage resolution,
     query_save_modifiers integration, Lucky in attack /
     save / recurring save, Brave / Fey Ancestry /
     Resilience save advantage, Dwarf poison damage
     resistance, race YAML loading, pc_schema race
     integration, invalid race rejection).
   - Deferred:
     * Lucky on ability check sites (`_execute_hide`,
       `_execute_search`, `_counterspell_resolve`,
       initiative, concentration saves) — same helper, just
       not wired at those sites yet
     * Halfling Nimbleness (move through larger creatures)
     * Elf Trance (4-hour long rest)
     * Elf Keen Senses (skill proficiency choice)
     * Dwarf Stonecunning / Toolkit Proficiency
     * Non-SRD species (Aasimar / Dragonborn / Gnome /
       Goliath / Orc / Tiefling) — would need
       `source: user_authored` tagging per project policy

46. ~~**Rogue Cunning Action v1 + generic Dash**~~ — **Shipped in
   PR #74.** Final feature in the per-class four-feature arc
   (Rage → SA → Divine Smite → Cunning Action). Adds three BA
   modes for Rogue L2+ plus the underlying generic Dash
   primitive (usable by future actors / actions).
   - **New generic `dash` primitive** sets
     `Actor.dashed_this_turn = True` AND clears
     `moved_this_turn` so the runner's post-BA second-move pass
     can fire. Emits `dash_taken` event with the doubled speed.
   - **`Actor.dashed_this_turn` field** added; cleared by
     `reset_turn`. New `_dash_post_move_done` per-turn attr
     prevents the post-BA move from looping.
   - **`_move_to_engage` doubles walk speed** when
     `dashed_this_turn` is set — RAW: Dash grants extra movement
     equal to your Speed.
   - **Runner post-BA second-move pass**: in `_run_actor_turn`
     after the Action Surge second slot, if the actor Dashed
     AND `_dash_post_move_done` is not set, call
     `_move_to_engage` once more (the BA Dash's "close the
     distance" payoff). Single-pass guarded by the dedup attr.
   - **Three Cunning Action BA variants** auto-generated by
     `pc_schema._build_cunning_action_actions` for Rogue L2+:
     - `a_cunning_action_dash` — type=`defensive_buff`,
       pipeline=`[dash]`. Recognized as self-targeted by an
       extended `is_self_targeted_defensive_buff` check.
     - `a_cunning_action_disengage` — type=`disengage`. Reuses
       PR #26's existing dispatch path.
     - `a_cunning_action_hide` — type=`hide`. Reuses PR #48's
       `_execute_hide`.
     All three are `slot: bonus_action`, `is_signature: False`.
   - **Class table**: `f_cunning_action` added to Rogue L2.
   - **New `f_cunning_action.yaml`** declares the menu shape
     (type=`active_menu`, BA cost, 3-mode dispatch).
   - **AI scoring for Dash**: new `_score_dash` in
     `defensive_ehp` returns ~0-5 eHP depending on whether the
     actor needs to close distance to an out-of-reach enemy.
     Returns 0 when all enemies are in reach (Dash is wasted)
     or no enemies exist. Pairs with the existing scoring for
     `disengage` (~0.5 eHP) and `hide` (real value from PR #59).
   - 14 new tests across 11 layers (primitive flag-setting,
     reset_turn cleanup, speed doubling in `_move_to_engage`,
     post-BA second-move pass, dedup loop prevention,
     pc_schema gating at L2/L1, self-targeted detection,
     scoring for in-reach / out-of-reach / no-enemies).
   - Deferred: generic main-slot Dash available to all actors
     (currently only the Cunning Action BA variant exists);
     Steady Aim BA (Rogue L3, advantage on next attack if no
     movement); Cunning Strike (Rogue L5, spend SA dice for
     Poison / Trip / Withdraw effects).

45. ~~**Paladin Divine Smite v1**~~ — **Shipped in PR #73.**
   Third feature in the per-class arc (Rage → SA → Divine Smite
   → Cunning Action). Passive damage rider with pace-aware AI
   slot-spend heuristic. **PHB 2024 change wired correctly:**
   Divine Smite is now a 1st-level Paladin spell with BA casting
   time (not a class feature), consuming a Paladin spell slot
   AND the bonus action.
   - **New `engine/core/divine_smite.py`**: dice math
     (2d8/3d8/4d8/5d8 at slots 1-4; caps at 4th per RAW 2024 —
     5th+ slots can hold other Paladin spells but don't amplify
     smite); Fiend/Undead detection (+1d8); qualification gate;
     AI slot-pick heuristic; application.
   - **AI heuristic (v1):**
     - Always smite on crit (extra dice double, well worth the
       slot)
     - Kill-steal: smite when projected damage drops target
     - Fiend/Undead bias when slot abundance reasonable
       (encounters_remaining_today <= 4)
     - Otherwise pace-aware via `slot_cost_ehp` from PR #22
     - Always picks LOWEST available slot (RAW best-practice;
       higher slot dice rarely beat saving the slot)
   - **`_damage` integration** — fires after SA rider on
     hit/crit melee weapon attacks. Folded into the same damage
     instance as the underlying hit (RAW 2024: smite damage is
     part of the attack's hit). Crits double smite dice same as
     SA + weapon base dice.
   - **Auto-derived Paladin spell slots** from class table —
     new `_derive_class_spell_slots` in pc_schema reads
     `class_resources.spell_slots` per level and stamps onto
     `template["spell_slots"]`. cli falls back to template
     when actor_spec doesn't declare slots (fixtures can
     still override for "wounded Paladin" scenarios).
   - **Class YAML c_paladin extended L5→L20** with the full
     half-caster slot progression (L2: 2×1st → L20: 4/3/3/3/2);
     `f_divine_smite` granted at L2 (RAW 2024 entry level).
   - **New `f_divine_smite.yaml`** — declared as `type: passive`
     with `bonus_action_and_spell_slot` resource cost (1st-4th
     slot range). No auto-generated action; fires inside the
     `_damage` pipeline.
   - **Per-turn dedup**: `_divine_smite_used_this_turn` Actor
     attr (belt-and-suspenders alongside the
     `actions_used_this_turn["bonus_action"]` gate); reset by
     `Actor.reset_turn`.
   - **Telemetry**: `divine_smite_applied` event with slot
     level, dice count, total damage, crit flag, Fiend/Undead
     flag, and trigger reason (crit / lethal / fiend_undead /
     pace_gate).
   - 31 new tests across 13 layers (dice math, creature type
     detection, qualification gates, AI heuristic — including
     crit / kill-steal / fiend bias / encounter pace,
     application + slot consumption + BA marking + dedup, crit
     doubling, damage primitive integration, pc_schema slot
     derivation).
   - Deferred: higher-slot smite when player wants the burst
     (v1 always picks lowest); smite as a separate AI-scored
     candidate; 2014-style "see hit result then decide"
     timing (v1 folds smite into the same damage instance —
     mechanically equivalent for HP tracking but loses the
     narrative beat).

44. ~~**Rogue Sneak Attack v1**~~ — **Shipped in PR #72.** Second
   feature in the per-class four-feature class-identity arc
   (Rage → SA → Divine Smite → Cunning Action). Passive damage
   rider with full RAW qualification.
   - **New `engine/core/sneak_attack.py`**: level table
     (1d6/L1-2 → 10d6/L19+; ceil(level/2) d6); qualification
     (`qualifies_for_sneak_attack`) checks weapon (Finesse OR
     Ranged), per-turn dedup (`_sneak_attack_used_this_turn`),
     and roll-state (advantage OR ally-adjacent + no-disadvantage);
     application (`try_apply_sneak_attack`) rolls dice, marks
     the flag, and emits the `sneak_attack_applied` event.
   - **Ally-adjacent check** walks the encounter for any creature
     on the target's opposing side within 5 ft of the target, not
     Incapacitated, that isn't the attacker themselves (RAW:
     "Another enemy of the target").
   - **`_damage` integration**: after the Rage damage rider and
     before resistance, calls `try_apply_sneak_attack` on
     hit/crit attacks. Crits double the dice count (RAW: extra
     dice from class features double on crit).
   - **Once per turn, not per round**: per-turn dedup flag
     resets in `Actor.reset_turn`. Fires on reaction OAs too.
   - **`finesse: true` plumbing**: weapon spec → action
     `attack_params.finesse`. Read by the SA gate; ranged
     weapons recognized via existing `kind == "ranged"` path.
   - **Class table extended** to L20 with `sneak_attack_dice`
     per level + `f_sneak_attack` granted at L1.
   - **New `f_sneak_attack.yaml`** declares the feature shape
     (passive, per-turn, scales from class table).
   - **No auto-generated action**: SA fires passively on
     qualifying hits — no candidate emission, no AI scoring
     decision. (The Rogue's choice of WHICH attack to make is
     still scored, but SA application is automatic.)
   - 19 new tests across 10 layers (level table, weapon gate,
     roll-state gate, ally-adjacent fallback,
     incapacitated-ally suppression, per-turn dedup, dedup
     reset, crit doubling, non-Rogue exclusion, damage
     primitive integration, pc_schema plumb-through).
   - Deferred: Cunning Strike (2024 PHB; trade SA dice for
     effects); Steady Aim (BA: advantage if no movement);
     AI scoring uplift for finesse weapons over off-hand
     when SA is available (rogue will still attack, just may
     pick suboptimally between competing attacks).

43. ~~**Barbarian Rage v1**~~ — **Shipped in PR #71.** First per-
   class feature in the four-feature class-identity arc (Rage /
   Sneak Attack / Divine Smite / Cunning Action). Wires all four
   core RAW effects + the long-rest cadence + the auto-end check.
   - **Bonus action `a_rage`**: auto-generated by `pc_schema` for
     Barbarian PCs. `feature_use: rage_uses_remaining`,
     `is_signature: true`, pipeline calls the new `rage_start`
     primitive which flips `Actor.rage_active` and stamps
     `Actor.rage_damage_bonus` from the level table.
   - **Damage rider on STR melee weapon attacks**: `_damage`
     reads the in-flight attack's `kind`/`ability` params (via
     new `_extract_attack_params` helper) and adds
     `rage_damage_bonus` only when the swing is melee + uses
     STR. Ranged weapons and DEX finesse swings get no bonus
     (RAW: Rage explicitly says "an attack using Strength").
   - **BPS resistance**: `_damage` halves bludgeoning /
     piercing / slashing damage on raging targets. Doesn't
     double-halve when the target's template already declares
     BPS resistance (RAW: resistances don't stack).
   - **STR check + STR save advantage**: `query_save_modifiers`
     and `query_d20_test_modifiers` inject advantage when
     `actor.rage_active` AND the ability is Strength.
   - **End-of-turn auto-end**: runner calls
     `check_rage_end_of_turn` after `_resolve_recurring_saves`.
     Ends rage with `reason: no_attack_no_damage` when both
     per-turn flags (`_rage_attacked_hostile_this_turn`,
     `_rage_damaged_this_turn`) are False. Grace clause on the
     entry turn (the BA cost everything; give them next turn).
   - **Long-rest refresh**: `apply_long_rest` for `c_barbarian`
     restores `rage_uses_remaining` to `rage_uses_max` (stamped
     by `derive_pc_resources`).
   - **AI scoring**: new `_score_rage_entry` in `defensive_ehp`
     gives Rage a level-scaled eHP value (offensive: 2 swings ×
     bonus × buff rounds; defensive: 0.5 × worst enemy DPR ×
     buff rounds). Returns 0 when already raging (no re-rage).
   - **Level tables** (RAW 2024) in `engine/core/rage.py`:
     uses 2/2/3/3/3/4/4/4/4/4/5/5/5/5/5/6/6/6/6/6;
     damage bonus +2 (L1-8) / +3 (L9-15) / +4 (L16+).
   - **Class YAML** `c_barbarian` extended to L20 with
     `rage_uses` + `rage_damage_bonus` per-level entries +
     `f_rage` granted at L1.
   - **New `f_rage.yaml`** declares the feature shape; new
     `rage_start` primitive registered in the registry.
   - **Pipeline routing**: Rage uses `type: defensive_buff` so
     it threads through the candidate generator's self-buff
     dedup path; `is_self_targeted_defensive_buff` and
     `defensive_ehp_defensive_buff` both detect the
     `rage_start` primitive and route accordingly.
   - 27 new tests across 9 layers (level tables, transitions,
     damage rider gates, BPS resistance, end-of-turn check,
     long-rest restore, STR-save advantage, pc_schema
     integration).
   - Deferred: 10-minute hard duration cap (auto-end covers
     the practical case); concentration / spellcasting
     suppression (no Barbarian in v1 has spells; multiclass
     needs the gate); short-rest one-charge recovery
     (Relentless Rage L11+ subclass-specific); Persistent
     Rage (Berserker subclass); incapacitation ends rage
     (needs hook into condition application).

42. ~~**Free-action scoring (Nick / Cleave / off-hand) v1**~~ —
   **Shipped in PR #70.** Free-slot actions (auto-fired between
   the action and bonus-action phases by `_run_free_phase`) now
   pass through the offensive-eHP scorer. Score is logged on the
   `free_action_fired` event; a new optional
   `min_score_to_fire` per-action gate skips weak free attacks
   with a `free_action_skipped` event
   (`reason: "below_min_score"`).
   - `engine/core/runner.py::_run_free_phase` now imports
     `score_candidate` and runs each chosen candidate through it
     before firing. The score is rounded to 2 decimals on the
     log event for telemetry.
   - **Default behavior preserved:** `min_score_to_fire` defaults
     to `0.0`, so v1 Nick (the only free-slot action that ships
     today) still always fires when a reachable target exists.
     This keeps PR #57's "Nick fires every turn" expectation
     intact for all existing tests.
   - **New gate semantics:** when `min_score_to_fire` is set
     above 0, a candidate whose score falls below the threshold
     is suppressed and the runner emits
     `{event: "free_action_skipped", reason: "below_min_score",
     score: <X>, min_score: <Y>}` instead of
     `free_action_fired`.
   - **Score signal:** for weapon_attack free actions the
     scorer's `offensive_ehp_weapon` path computes hit-prob ×
     expected damage × concentration multiplier, so the score
     reflects real-target eHP (factors in AC, advantage, on-hit
     riders) — not just raw damage.
   - **6 new tests** across 3 classes in
     `tests/test_free_action_scoring.py`: score field appears
     on the fire event, score is positive against a reachable
     enemy, high threshold suppresses with the correct skip
     event, low threshold passes, no-threshold (default) fires
     normally, explicit-zero threshold fires normally.
   - **Foundation for AI control:** future free-slot actions
     (Vex/Sap off-hand combos, BA Cleave hooks) can opt into
     score-gated firing by setting `min_score_to_fire` in their
     YAML. The v1 ship intentionally changes no live actor
     behavior — the gate is wired but inactive everywhere by
     default.
   - Deferred: per-target re-selection (free-phase currently
     reuses the action-phase target rather than re-picking
     against the chosen free action's profile); free-action
     scoring for non-weapon free actions (none ship yet).
41. ~~**Blindsight bypass for Darkness scoring**~~ — **Shipped in
   PR #69.** Closes the PR #61 residue. The Darkness scorer's
   sense-bypass helper now checks both Truesight AND Blindsight
   (was: Truesight only). Matches the `can_actor_see` precedence
   from PR #52 where Blindsight is the dominant override for
   magical darkness.
   - Renamed `_truesight_pierces(observer, target)` →
     `_sense_pierces(observer, target)` in
     `offensive_ehp_darkness`. Checks
     `observer.truesight_range_ft` OR
     `observer.blindsight_range_ft` against the distance.
   - Behavioral effects:
     - Out-sphere enemies with Blindsight in range → contribute
       0 defensive value (the AI scores Darkness LESS against
       blindsight monsters)
     - Out-sphere allies with Blindsight in range → contribute
       0 cost (the AI is more willing to drop Darkness on an
       enemy if a blindsight ally is positioned to still
       perceive them)
     - Either sense alone suffices; both together don't
       double-count (boolean OR)
   - 4 new tests across the bypass paths (blindsight enemy
     reduces benefit, out-of-range bs is irrelevant, blindsight
     ally reduces cost, ts+bs both pierce equivalently).
   - Module-level deferred-list note updated to remove the
     "Blindsight bypass" entry.
40. ~~**Hunger of Hadar + Cloudkill (zone-spell extensions)**~~ —
   **Shipped in PR #68.** Closes the "other zone-creating
   spells" residue from PR #60. Two SRD spells ship that
   exercise the `creates_zone` hook with a new zone type
   (`heavy_obscurement` alongside `magical_dark`).
   - `_persistent_aura` extended via a new
     `_CREATES_ZONE_TO_ENV_KEY` mapping: `"magical_dark"` →
     `magical_dark_zones`, `"heavy_obscurement"` →
     `heavily_obscured_zones`. Future zone types (e.g.,
     `difficult_terrain`) extend the dict.
   - `concentration.end_concentration` generalized to scrub ALL
     zone-type lists when a caster's aura drops (not just
     `magical_dark_zones`). Statically-declared zones (no
     caster_id stamp) still preserved.
   - **`f_hunger_of_hadar.yaml`** (Warlock 3rd): 20-ft sphere of
     magical darkness + 2d6 cold per turn (no save) + 2d6 acid
     CON save. v1 models the combined damage as 4d6 cold on
     fail / 2d6 cold on success (the dual-save mechanic deferred
     for runtime clarity).
   - **`f_cloudkill.yaml`** (Wizard 5th): 20-ft sphere of
     heavily-obscuring poison fog + 5d8 poison CON save (half
     on success). Cloud movement (RAW: 10 ft/round away from
     caster) deferred — same as Moonbeam.
   - Vision integration: Cloudkill's heavy obscurement blocks
     ordinary sight + truesight (RAW: fog is physical, not
     magical); blindsight pierces. HoH's magical darkness
     blocks ordinary darkvision; truesight pierces; blindsight
     pierces.
   - 17 new tests across the mapping, the new zone-creation
     path, magical_dark regression, unknown-type rejection,
     end_concentration scrub (both types + static preserved +
     multi-caster), Cloudkill + HoH vision integration, and
     YAML loading.
   - Deferred refinements: HoH RAW dual STR/Acid + always-Cold
     save mechanic (v1 combines as one CON-save event);
     Cloudkill wind-direction movement; upcast scaling; spell-
     created zone AI scoring (Darkness scoring from PR #61
     would extend to these but doesn't yet).
39. ~~**REACTION_SLOT_BASE_COSTS calibration**~~ — **Shipped in
   PR #67.** Closes the PR #56 residue. Per-slot-level base eHP
   costs recalibrated from eyeballed values (4/6/10/14/18/22/26/
   30/36) to RAW-spell-anchored values (10/15/28/38/50/65/75/85/
   100) cross-referenced with Treantmonk's 2024 tier-aggregated
   DPR data.
   - **Methodology:** for each slot level, identify the canonical
     best-use spells (highest damage spell + commonly-cast
     utility/control), compute expected eHP value with hit/save
     odds factored, round up slightly so utility spells aren't
     systematically underweighted.
   - **Reference spells per level** documented in the dict
     docstring (Magic Missile at L1, Fireball at L3, Disintegrate
     at L6, Wish at L9, etc.).
   - **Behavioral effects of the calibration:**
     - Shield (L1) skips weak attackers in mid-day setups (cost
       10 > attacker DPR < 10); fires on Ogre+ DPR
     - Counterspell (L3) breaks even vs L3 spells; skips lower-
       level spells; fires aggressively vs L4+ spells
     - Hellish Rebuke (L1) skips in mid-day single-slot setups
       (value 8.25 < cost 10); fires when slot abundant or last
       encounter
   - **Treantmonk context** in the docstring: the 2024 baseline
     (C-tier Warlock Blade Pact Greatsword) does ~24 DPR at T2,
     so a 3rd-level slot's 28 eHP value ≈ one good turn of T2
     baseline DPR — the right comparison.
   - Updated 3 existing tests:
     - `test_last_encounter_cost_is_low` now uses
       `REACTION_SLOT_BASE_COSTS[1]` rather than the hardcoded
       4.0
     - `test_shield_turns_hit_into_miss` and
       `test_hellish_rebuke_damages_attacker` now set
       `encounters_remaining_today=1` so pacing doesn't
       suppress the mechanics under test (they're verifying the
       reaction's effect, not its pacing — those live in
       `test_pace_aware_reactions.py`)
   - 20 new tests in `test_reaction_cost_calibration.py`: pins
     each level's calibrated value, sanity-checks monotonicity
     and ≤2× growth ratio, and verifies downstream firing-
     threshold behaviors for Shield / Counterspell / Hellish
     Rebuke across mid-day / abundant-slots / last-encounter
     scenarios.
   - Deferred refinements: per-class-spec slot-vs-attack
     tradeoff calibration (waiting on Treantmonk video-by-video
     per-class DPR curves); upcast scaling (L3 Fireball cast in
     L5 slot = 10d6 vs 8d6; would justify higher slot-spent
     value scoring); spell-level-vs-character-level scaling
     (a L11 wizard's L3 slot is worth less than a L5 wizard's).
38. ~~**Cleave reach passthrough**~~ — **Shipped in PR #66.**
   Closes the PR #58 residue. Cleave's attacker-reach constraint
   used to hardcode 5 ft; now it reads the weapon's actual reach.
   - `_build_weapon_action` bakes `reach_ft` into the mastery
     sub-dict (in addition to ability_mod / damage_type /
     save_dc). Defaults to 5 when the weapon spec omits it.
   - `_mastery_cleave` reads `params.get("reach_ft", 5)` for the
     attacker-reach check. The "within 5 ft of primary target"
     RAW distance stays invariant (does not scale with attacker
     reach).
   - Glaive / Halberd / Pike (reach 10) Cleave to a second target
     up to 10 ft from the attacker now works correctly.
   - 7 new tests across build-time baking (default 5 / explicit
     10 / omitted defaults to 5) and runtime semantics (reach 5
     misses far target; reach 10 hits same target; 5 ft
     primary-to-secondary stays invariant; missing-param falls
     back to 5).
   - Deferred refinements: line-of-sight check on second target
     (RAW doesn't require it, but a wall between primary and
     secondary should arguably block — v1 trusts open-
     battlefield); secondary-target preference ordering (v1
     picks first-in-actor-list deterministic order).
37. ~~**Actor.size + Push size gate + Cleave/Graze Heavy gate**~~
   — **Shipped in PR #65.** Closes two PR #58 residues:
   Push lacked a target-size gate, and Cleave/Graze trusted the
   weapon spec rather than enforcing the Heavy property.
   - New `engine/core/sizes.py` module with 6 canonical sizes
     (tiny / small / medium / large / huge / gargantuan),
     `KNOWN_SIZES` tuple in canonical order, `PUSH_SIZES`
     frozenset (those Push can affect — Large or smaller),
     `normalize_size(value)` helper (case-insensitive,
     None→'medium', unknown raises), and `size_at_or_below(a, b)`
     comparison.
   - New `Actor.size: str = "medium"` field. Loaded by
     `cli._build_actor` from actor_spec override → template
     top-level `size:` (monster SRD shape) → 'medium'.
     Normalized through `sizes.normalize_size` so unknown size
     names fail loudly at load time.
   - `_mastery_push` gates on target size: skips with
     `weapon_mastery_skipped` event (reason=size_immune) for
     Huge / Gargantuan targets. RAW: Push only affects Large
     or smaller.
   - `_build_weapon_action` validates Cleave and Graze masteries
     at build time:
     - Weapon must declare `heavy: true` (RAW: both masteries
       require Heavy melee)
     - Weapon must NOT have `range_ft` (Heavy MELEE specifically;
       Heavy Crossbow is heavy but ranged → rejected)
     - Other masteries (Vex/Sap/Topple/Push/Nick) unaffected
   - One existing fixture update: `weapon_mastery_showcase`'s
     greatsword now declares `heavy: true` to match RAW (was
     two_handed-only; the new gate would otherwise raise).
   - 24 new tests across the sizes module (helpers + edge
     cases), Actor.size loading (template, override, unknown,
     default), Push gate (Medium / Large pushed, Huge /
     Gargantuan immune, Tiny pushed), and Heavy gate (Cleave +
     Graze on heavy passes, non-heavy raises, ranged-heavy
     raises, other masteries unaffected).
   - Deferred refinements: per-attacker push direction-of-
     forced-movement (currently always away from attacker;
     RAW also allows "into a different direction" with consent
     of the pusher); collision handling on push destination
     (still trusts open-battlefield); Heavy gate on monster-
     template attacks (currently only PC-schema-generated
     weapons gate; monster-template weapons trust their own
     declarations).
36. ~~**Other-class Weapon Mastery wirings + cap enforcement**~~ —
   **Shipped in PR #64.** Closes the PR #54 residue that left
   Weapon Mastery wired on Fighter only. All five RAW-mastery-
   knowing classes (Fighter / Barbarian / Paladin / Ranger /
   Rogue) now have class YAMLs with the proper
   `weapon_mastery_count` progression baked into their
   `level_table`. Also enforces the class-level cap at build
   time — closes another PR #54 residue ("v1 trusts the spec").
   - New minimal class YAMLs: `c_barbarian.yaml`, `c_paladin.yaml`,
     `c_ranger.yaml`, `c_rogue.yaml`. Each carries
     `core_traits` (hit_die, save_proficiencies, weapon/armor
     profs) + a `level_table` with `weapon_mastery_count` per
     RAW progression. Other class features (Rage / Lay on Hands /
     Sneak Attack / etc.) deferred — each becomes a follow-on
     PR when its mechanic lands. Each YAML lists deferred
     features in comments so future PR authors have a checklist.
   - RAW progressions baked: Barbarian 2@L1, 3@L4; Paladin 2@L1,
     3@L11; Ranger 2@L1, 3@L9; Rogue 1@L1, 2@L9. (Fighter
     unchanged: 3@L1, 4@L4, 5@L10, 6@L16.)
   - New `pc_schema._validate_weapon_masteries_cap(masteries,
     class_def, level, class_id)` helper. Reads the highest-
     applicable `class_resources.weapon_mastery_count` from the
     class's level_table; raises if `len(masteries)` exceeds it
     with a clear message naming the class + level + cap.
     Carries forward through gap rows (Paladin L6-L10 inherit
     L5's cap of 2). Wizard / non-mastery classes → cap=0;
     declaring any masteries raises with a "pick a class that
     grants Weapon Mastery" hint.
   - Empty `weapon_masteries` list always legal (declaring zero
     masteries works for any class).
   - One existing test fixed: `test_nick_mastery.py`'s mock
     Fighter class def now declares `weapon_mastery_count: 3`
     so its tests can declare 1 mastery without tripping the
     new cap.
   - 29 new tests across class YAML loading, per-level
     progression for each of the four classes, cap validator
     (empty / at-cap / under-cap / over-cap / Wizard / carry-
     forward), and end-to-end `build_pc_template` for
     Barbarian + Rogue + Paladin + Ranger with at-cap and
     over-cap cases.
   - Deferred: full class spec content (Rage / Sneak Attack /
     Divine Smite / Favored Enemy / etc. — each its own PR);
     auto-emission of Expertise choices from the Rogue level
     table (PR #62 wired the mechanic; the class table just
     names which levels grant it).
35. ~~**Blind Fighting style**~~ — **Shipped in PR #63.** Closes
   the Fighting Style arc — all 6 styles (Defense / Dueling /
   Archery / GWF / TWF / Blind Fighting) now ship in the engine.
   RAW grants Blindsight 10 ft. Builds on PR #52's blindsight
   infrastructure — `pc_schema` bakes
   `senses.special.blindsight: 10` onto the template when the
   style is chosen, and `cli._build_actor` loads it onto
   `Actor.blindsight_range_ft` via the same monster-template
   loader. New `_build_pc_senses_block` helper centralizes
   senses-block assembly (passive_perception + any
   special-sense entries). New
   `f_fs_blind_fighting.yaml` (user_authored — not in SRD CC
   v5.2.1). Vision integration is automatic: PR #52's
   `can_actor_see` already honors blindsight as the dominant
   override (pierces Invisible / fog / darkness / magical
   darkness / self-Blinded within range). Deferred: the
   "unless it successfully hides from you" RAW exception
   (Hide-source Invisible would tighten by adding a per-sense
   bypass list); the "Total Cover" RAW exception (Total Cover
   isn't yet modeled). 13 new tests across validation,
   `_build_pc_senses_block` (no style → no special; bf → +10;
   other → no special), `build_pc_template` (template has
   blindsight; derived_from records; other style no special;
   no style no special), `cli._build_actor` (bf → 10; other →
   0), and end-to-end vision (bf pierces magical darkness
   within 10 ft).
34. ~~**Skill expertise + magic-item bonuses**~~ — **Shipped in
   PR #62.** Closes the PR #51 residue. PC schemas now accept
   `skill_expertise:` (list of skills with 2×PB) and
   `skill_bonuses:` (dict of skill → flat magic-item bonus).
   Both feed into `skill_modifier` + passive Perception.
   - `engine/core/skills.py`:
     - New `has_skill_expertise(actor, skill)` helper reading
       `template.skill_expertise`
     - New `_skill_magic_bonus(actor, skill)` helper reading
       `template.skill_bonuses` (case-insensitive match)
     - `skill_modifier` extended: if proficient + expertise →
       2×PB; magic bonus added on top regardless of proficiency;
       stacks on top of monster-listed totals
   - `pc_schema`:
     - New `_validate_skill_expertise(value, proficiencies)` —
       validates against known skills AND enforces RAW gate that
       expertise requires also being proficient. Raises with a
       clear message if the gate fails.
     - New `_validate_skill_bonuses(value)` — validates against
       known skills + int values; non-dict / non-int values
       raise.
     - `build_pc_template` accepts both fields; bakes onto
       template top-level + `derived_from_pc_schema` block.
   - `_compute_passive_perception` extended with `skill_expertise`
     and `skill_bonuses` kwargs. Proficient + expertise → 2×PB
     in passive; magic bonus added always (proficient or not).
   - 38 new tests across the helpers, `skill_modifier` integration
     (proficient with/without expertise, magic bonus stacking
     with/without proficiency, monster-listed + magic bonus),
     validators (unknown / non-list / non-dict / expertise-
     without-proficiency raises), pc_schema baking (template
     fields, derived_from, passive Perception with each
     combination), and the passive Perception helper directly.
   - Deferred: Jack of All Trades / Reliable Talent variants
     ("PB doubled if it isn't already" — v1 always doubles);
     Stealth roll re-roll on advantage (Cloak of Elvenkind RAW
     grants advantage, not flat bonus — we model it as a flat
     +5 proxy if fixture authors prefer); item-suite presets
     (a "rogue with full elvish kit" auto-loader).
33. ~~**AI eHP scoring for Darkness**~~ — **Shipped in PR #61.**
   Closes the PR #60 residue. Darkness now competes against
   damage spells in the AI's candidate selection on a real
   eHP scale instead of falling through to a 0-value score.
   - New `offensive_ehp_darkness(actor, action, state, origin)` in
     `engine/ai/ehp_scoring.py`. Classifies actors as in-sphere
     vs out-of-sphere allies / enemies via Chebyshev distance
     from origin. Computes benefit (in-sphere allies' offensive
     advantage + defensive disadvantage on out-sphere enemies)
     minus cost (mirror for in-sphere enemies + out-sphere
     allies). Scales by `EXPECTED_AURA_ROUNDS` (concentration
     duration proxy). Clamps to 0 — Darkness that nets negative
     value loses to any damage option without a sign-flip
     surprise.
   - Truesight bypass: out-sphere enemies with truesight in
     range of an in-sphere ally don't contribute defensive
     value (they pierce the darkness). Same for ally truesight
     piercing in-sphere enemies (no cost from those allies).
   - Reach gating: only in-threat-range attackers contribute to
     defensive value. Out-of-range enemies wouldn't attack
     anyway.
   - Dispatch via `creates_zone` check: existing
     `offensive_ehp_persistent_aura` inspects the aura params
     and delegates to `offensive_ehp_darkness` when
     `creates_zone == "magical_dark"`. Damage-aura path
     unchanged (Spirit Guardians, Moonbeam, etc.).
   - 11 new tests across the scorer (radius constant / empty
     sphere → 0 / caster-inside-enemy-outside positive /
     enemy-inside-only clamps to 0 / truesight enemy neutralizes
     defensive / truesight ally neutralizes cost / out-of-reach
     enemy no defensive / origin defaults to caster position /
     multiple allies more benefit) and dispatch routing
     (Darkness routes to darkness scorer / Spirit Guardians-
     shape routes to damage scorer).
   - Deferred refinements: blindsight bypass (analogous to
     truesight; v1 ignores); per-target attack-frequency
     weighting (multiattack monsters' debuff worth more);
     opportunity-cost subtraction for concentration (caster
     loses other concentration spells).
32. ~~**Darkness spell as persistent_aura**~~ — **Shipped in PR #60.**
   Closes the PR #52 residue (magical_dark_zones previously needed
   fixture-authoring; the Darkness spell now declares its zone at
   cast time, with concentration tracking for cleanup). Three
   pieces of new infra:
   - `vision._position_in_any_zone` extended to recognize sphere
     zones (`{shape: "sphere", center: [x, y], radius_ft: int}`)
     alongside the legacy axis-aligned rect shape. Chebyshev
     distance vs `radius_ft // 5` matches the grid convention.
     Backward-compatible — existing rect zones still work.
   - `_persistent_aura` primitive gains a `creates_zone` param.
     When `creates_zone="magical_dark"` AND anchor='point' AND
     origin is resolved, appends a sphere entry to
     `state.encounter.environment.magical_dark_zones` stamped
     with `caster_id` + `action_id`. Caster-anchored Darkness
     (moves with caster) deferred — RAW says point-anchored
     anyway. Unknown `creates_zone` values raise; v1 supports
     only `magical_dark`.
   - `concentration.end_concentration` extended to scrub
     environment magical_dark_zones whose caster_id + action_id
     match the dropped aura. Statically-declared zones (no
     caster_id stamp from fixtures) are preserved untouched.
   - New `f_darkness.yaml` feature file. SRD CC v5.2.1.
     `granted_by: c_wizard L3` (2nd-level spell access).
     Action template uses persistent_aura with sphere/15-ft
     radius/point anchor + the new creates_zone param.
   - Deferred: "centered on a creature you choose" variant
     (Darkness can RAW be cast on an object/creature; v1
     point-anchors only); Devil's Sight (Warlock invocation
     that pierces magical darkness without truesight — same
     PR #52 residue); AI scoring for Darkness (defensive
     vision-denial value needs its own estimator).
   - 18 new tests across sphere zone detection (center / in-
     radius / just-outside / backward-compat / mixed / via
     is_in_magical_dark_zone), _persistent_aura zone creation
     (succeeds with magical_dark / raises with caster anchor /
     raises with unknown zone type / no zone when omitted),
     concentration end (drops zone / preserves static zones /
     two casters independent), and end-to-end vision
     (no darkvision blocked / ordinary darkvision blocked /
     truesight in-range pierces / truesight out-of-range
     blocked / blindsight pierces).
31. ~~**AI eHP scoring for Hide + Search**~~ — **Shipped in PR #59.**
   Closes the residues from PR #48 (Hide had no scorer; returned 0
   by default) and PR #55 (Search relied on gated emission, no
   real eHP value). New `offensive_ehp_hide` and
   `offensive_ehp_search` in `engine/ai/ehp_scoring.py`.
   - **Hide value model:** `p_success_stealth × p_evade_perception ×
     (offensive_value + defensive_value)`. Offensive value = own
     per-attack damage × `DELTA_HIT_FROM_ADVANTAGE` (one boosted
     attack from Invisible advantage next turn). Defensive value
     = sum over in-threat-range enemies of `enemy_dpr ×
     DELTA_HIT_FROM_ADVANTAGE` (each enemy attacks at disadvantage
     while we're Invisible). Returns 0 when gate fails (no heavy
     obscurement AND no 3/4+ cover), no enemies, or all enemies
     auto-spot via passive Perception.
   - **Search value model:** `Σ_hidden_enemies(p_perception_success
     × own_per_attack_damage)`. Conservative — doesn't subtract
     lost current-turn DPR (opportunity cost captured implicitly
     by competing against weapon_attack candidates on the same
     scale). Spell-source Invisible NOT counted (only Hide-source
     per RAW). Returns 0 when no Hide-source hidden enemies exist
     or the actor has no scorable attacks.
   - `score_candidate` dispatch extended: `kind='hide'` →
     `offensive_ehp_hide`; `kind='search'` → `offensive_ehp_search`.
   - `pipeline.generate_candidates` now emits search candidates for
     explicit `type: search` actions on the actor's template
     (built-in Search continues to be emitted by
     `built_in_actions_for` with its own gated emission).
   - New helpers `_stealth_success_probability(mod)` and
     `_expected_stealth_total(mod)` exposed at module level for
     test reuse.
   - 23 new tests across the probability helper, hide scoring (gate
     fail / no enemies / all auto-spot / heavy obscurement / 3/4
     cover / higher stealth / out-of-range enemies), search
     scoring (no targets / no attacks / low-vs-high stealth_total /
     multiple enemies / spell-Invisible-ignored / mixed-Invisible-
     only-Hide), dispatch routing, and candidate emission.
   - Deferred refinements: opportunity-cost subtraction for Search
     (lost current-turn DPR), per-enemy weighted defensive value
     (each enemy's auto-spot probability, not just a coarse
     fraction), expected-stealth-total based on success-conditional
     d20 average (v1 uses a simple 11+mod proxy).
30. ~~**Cleave / Push / Slow weapon masteries**~~ — **Shipped in
   PR #58.** Closes the Weapon Mastery arc with the three
   remaining v1 properties. `DEFERRED_MASTERIES` is now empty.
   All eight properties (Vex / Sap / Topple / Graze / Nick /
   Cleave / Push / Slow) ship in the engine.
   - **Cleave** — on hit, fires one sub-attack against a
     different living enemy within 5 ft of the original target
     AND within the attacker's reach. Once-per-turn via
     `actor._cleave_fired_this_turn` attribute, cleared in
     `reset_turn`. Sub-attack uses the same weapon's pipeline
     (found via `_find_attacker_weapon_for_cleave` which scans
     for the highest-DPR melee weapon with mastery=cleave).
   - **Push** — on hit, pushes target up to 10 ft straight away
     from attacker. New `engine/core/geometry.push_creature`
     helper: snaps to 8-direction unit vector via
     `unit_direction`, moves the target in 5-ft steps. v1
     trusts the weapon spec (no size gate); collision deferred.
   - **Slow** — on hit AND damage dealt, reduces target's
     `speed["walk"]` by 10 ft (clamped at 0). Direct mutation
     + `_slow_data` runtime record on the target (source_id,
     original_speed, applied_at_round). RAW "doesn't exceed
     10 ft if hit multiple times" enforced by no-op when the
     target already has any Slow record. Expiry handled by the
     runner's turn_start sweep:
     `weapon_masteries.expire_slow_from_source(source_actor_id,
     state)` restores speed when the slow-applier's next turn
     begins.
   - `apply_mastery_effects` now threads `bus` through to
     `_mastery_cleave` for the sub-attack's `attack_roll`
     emit. Falls back to a `_NullEventBus` stub for direct
     test invocation without a bus.
   - 25 new tests across registry membership, `push_creature`
     helper (east/west/diagonal/stacked/partial), Cleave
     (no-second-target / second-target-fires / once-per-turn /
     reset_turn-clears / ally-doesn't-qualify / actor-without-
     cleave-no-op), Push (fires-on-hit / NOT-on-miss /
     diagonal), Slow (reduces-speed / doesn't-stack /
     clamped-at-zero / NOT-on-miss / expire-restores /
     expire-wrong-source-noop / expire-multiple-targets).
   - Deferred refinements (not new masteries): Heavy gate on
     Cleave + Graze, size gate on Push, forced-movement
     collision handling.
29. ~~**Nick weapon mastery + runner free-phase**~~ — **Shipped in
   PR #57.** Bridges the Weapon Mastery (PR #54) and TWF (PR #53)
   arcs by closing both residues at once. RAW 2024: with Nick,
   the off-hand attack happens as part of the Attack action
   instead of as a Bonus Action — frees the bonus slot for
   Second Wind, etc. `nick` promoted from `DEFERRED_MASTERIES`
   to `KNOWN_MASTERIES`. New `_nick_active(off_hand_spec,
   weapons, weapon_masteries)` helper in pc_schema.py: returns
   True iff the actor's `weapon_masteries` list contains "nick"
   AND at least one wielded Light melee weapon (off-hand OR any
   primary) declares `mastery: nick`. When active,
   `build_pc_template` overrides the off-hand action's slot from
   `bonus_action` to `free` and marks `nick_active: true`. New
   runner `_run_free_phase` between the action and bonus_action
   phases: auto-fires ALL `slot=free` weapon_attack actions on
   the actor (no AI scoring — RAW says it happens, so it
   happens), targeting the dial-preferred enemy via the same
   `pick_target` path as movement. Per-turn dedup set
   (`_free_actions_fired_this_turn`) prevents double-firing if
   the phase runs twice in a turn (e.g., Action Surge). Logs
   `free_action_fired` / `free_action_skipped` events with
   reason. Nick has no per-attack effect, so
   `weapon_masteries.apply_mastery_effects` correctly falls
   through (the if-elif chain doesn't list "nick"). Deferred:
   AI scoring for free actions (vs always-fire), Cleave / Push /
   Slow as the remaining deferred masteries. 20 new tests
   across known-set membership, `_nick_active` helper (true
   cases for off-hand-with-nick + primary-with-nick; false
   cases for actor-doesn't-know-nick, empty masteries, non-
   light primary, ranged primary), pc_schema integration (Nick
   active → slot=free, Nick inactive → slot=bonus_action,
   no-off-hand → no action), apply_mastery_effects no-op with
   Nick id, runner free-phase end-to-end (fires automatically,
   logs events, no slot consumption, no double-fire).
28. ~~**Pace-aware reactions (Shield / Counterspell / Hellish Rebuke)**~~
   — **Shipped in PR #56.** Closes the always-fire residue from
   PR #45 and PR #46. `engine/core/feature_pacing.py` gains
   `reaction_cost_ehp(slot_level, slots_remaining, encounters_
   remaining)` — same `scarcity × urgency × base_cost` shape as
   `feature_use_cost_ehp`, with a per-slot-level base cost table
   (`REACTION_SLOT_BASE_COSTS`, levels 1-9). New
   `engine/ai/reaction_scoring.py` module with per-reaction value
   estimators:
   - `shield_value_ehp` — estimates the attacker's best weapon DPR
     (Shield converts hit → miss, so value = avoided damage)
   - `counterspell_value_ehp` — uses the target spell's slot level
     via the same base-cost curve
   - `hellish_rebuke_value_ehp` — 2d10 fire avg with ~50% save
     rate, modulated by fire resistance / immunity / vulnerability
   `estimate_reaction_value_ehp` dispatch returns `float("inf")`
   for unknown reactions (forward-compat: always-fire for reactions
   not yet scored). `reactions.try_use_reaction` gates after
   resource availability checks but before pipeline execution: if
   `cost > value`, skip and log `reaction_skipped_pace` with
   diagnostic fields. Bypassable via `signature_reaction: true`
   on the action (always fire when eligible) or `slot_level == 0`
   (OA-shape reactions never weighed). Existing reaction tests
   still pass (cost ≤ value for all in-fixture scenarios with
   typical slot loadouts and 3 encounters remaining). 36 new
   tests across the cost formula, three value estimators, dispatch
   logic, and `try_use_reaction` gate behavior (skip-on-high-cost,
   fire-on-high-value, signature override, last-encounter cost
   drop, many-slots cost drop, skip-event diagnostics).
27. ~~**Active Search action + AI gated emission**~~ — **Shipped in
   PR #55.** First non-damage information action. New built-in
   `BUILT_IN_SEARCH` (type=search, slot=action) injected by
   `built_in_actions_for` only when at least one Hide-source-
   hidden enemy is in the encounter AND that enemy's recorded
   stealth_total exceeds the actor's passive Perception
   (otherwise PR #51's auto-spot already revealed them). Search
   bypasses the threat-range and move-to-engage gates that filter
   Dodge/Disengage/Help — it's an information action, not a
   defensive one, so the AI can Search even when it'd otherwise
   close distance. New `_execute_search` in pipeline.py: for each
   Hide-source-hidden enemy, rolls d20 + Perception modifier (via
   `skill_modifier`) vs the enemy's stealth_total. On success,
   scrubs the Hide-source `co_invisible` from the target;
   `creature_revealed` event fires. v1 reveal is global ("spotted
   means spotted" for all observers); per-observer `spotted_by:`
   tracking deferred. Spell-source Invisible is NOT affected by
   Search — only Hide-source is (RAW: spell Invisibility doesn't
   expose a Perception target). Closes the last vision-arc
   residue. Deferred: per-observer reveal tracking, real eHP
   scoring for Search (vs gated emission), explicit sight-range
   gate (currently any-encounter). 21 new tests across the gate
   helper, built-in emission (no enemies / auto-spot case / above-
   passive case / bonus slot / explicit-action override),
   `_execute_search` (no candidates, failed check, successful
   reveal, perception proficiency adds PB, spell-Invisible
   untouched, mixed-source surgical scrub, multi-enemy
   independence), and end-to-end vision verification. New
   `active_search_encounter.yaml` fixture (proficient + non-
   proficient PC hunting a hidden goblin).
26. ~~**Weapon Mastery (2024 PHB) v1**~~ — **Shipped in PR #54.**
   The biggest 2024 PHB feature; tight v1 scope. New
   `engine/core/weapon_masteries.py` module with the known set,
   validators, and per-property implementations. New
   `Actor.weapon_masteries: list` field (the properties the actor
   *knows*), loaded by `cli._build_actor` from template or
   actor_spec override. PC schema accepts
   `weapon_masteries: [vex, sap, topple, graze]` with validation;
   baked onto template top-level + `derived_from_pc_schema`.
   Weapon specs accept `mastery: <id>` (intrinsic to the weapon);
   `_build_weapon_action` bakes a self-contained
   `mastery: {id, ability_mod, damage_type, save_dc}` sub-dict
   into attack_roll params. `_attack_roll` calls
   `apply_mastery_effects` AFTER lifetime expiry so newly-
   registered Vex/Sap modifiers (per_owner_attack lifetime)
   survive THIS attack and consume on the NEXT — exactly RAW.
   Four properties shipped:
   - **Vex**: on hit, advantage on next attack (modifier on actor)
   - **Sap**: on hit, target has disadvantage on next attack
   - **Topple**: on hit, target CON save (DC 8+mod+PB) vs Prone
   - **Graze**: on miss, deal ability_mod damage (respects
     resistance / vulnerability / immunity)
   New `f_weapon_mastery.yaml` feature file. Fighter class def
   already declared `weapon_mastery_count` per level (3/4/5/6)
   and `f_weapon_mastery` feature reference; this PR fills in
   the feature file. v1 does NOT enforce the class-level
   masteries-known cap — schema trusts the spec. Deferred:
   Cleave (extra attack), Push (forced movement), Slow (speed
   reduction with duration), Nick (off-hand-as-Attack-action).
   36 new tests across validators, helpers, pc_schema
   integration, weapon_action baking, per-property semantics
   (hit/miss/save/resistance), and dispatch no-ops. New
   `weapon_mastery_showcase_encounter.yaml` with four fighters
   demonstrating each property.
25. ~~**Two-Weapon Fighting + off-hand mechanics**~~ — **Shipped
   in PR #53.** Closes the Fighting Style arc with the fifth
   style. PC schemas accept `off_hand_weapon:` (a single light
   melee weapon spec). New `_validate_off_hand_weapon` enforces
   RAW gates: off-hand must be melee + light + not two-handed,
   AND the primary `weapons:` list must contain at least one
   Light melee. `_build_weapon_action(off_hand=True)` returns an
   action with `slot: bonus_action`, id suffixed `_offhand`,
   name " (Off-Hand)". RAW default: damage modifier = 0 on the
   off-hand (or the ability mod if negative — negatives always
   apply). With `fighting_style: two_weapon_fighting`, the off-
   hand damage adds the ability modifier normally. Attack bonus
   on off-hand always includes ability mod + PB (only damage is
   reduced). Dueling explicitly does NOT apply to the off-hand
   even when TWF is taken (RAW Dueling "no other weapons"
   clause). `two_weapon_fighting` added to
   `_KNOWN_FIGHTING_STYLES`. New
   `f_fs_two_weapon_fighting.yaml` feature file (user_authored —
   non-SRD). Deferred: Nick weapon mastery (lets off-hand happen
   as part of Attack action), Dueling-vs-dual-wield main-hand
   exclusion tightening (v1 still lets a dual-wielder fighter
   get the +2 on their main-hand light weapon — RAW would deny
   it). 27 new tests across style validation, off-hand
   validation, build_weapon_action off_hand semantics,
   end-to-end build_pc_template. Showcase fixture now has all
   five fighters side-by-side (Defense / Dueling / Archery /
   GWF / TWF).
24. ~~**Truesight + Blindsight + Magical darkness**~~ — **Shipped in
   PR #52.** Closes the vision-type arc. Two new per-actor sense
   fields: `Actor.truesight_range_ft` and
   `Actor.blindsight_range_ft` (both int, default 0). Loaded from
   monster template `senses.special.truesight` / `.blindsight` or
   actor_spec overrides — same precedence pattern as darkvision.
   New environment field `magical_dark_zones` (axis-aligned rect
   list, parallel to `dark_zones` / `dim_light_zones` /
   `heavily_obscured_zones`). New helper
   `vision.is_in_magical_dark_zone`. `can_actor_see` precedence
   reorganized into seven explicit steps with new vision-type
   gates: **(1) Blindsight bypass** within range overrides
   everything (Invisible, fog, darkness, magical darkness, self-
   Blinded). **(3) Truesight** within range bypasses both Hide-
   source and spell-source Invisible. **(5) Magical darkness**
   zones block ordinary darkvision; only Truesight (or Blindsight
   from step 1) pierces. **(6) Ordinary darkness** zones: Truesight
   in range substitutes for darkvision. Heavy obscurement (fog)
   still blocks even with Truesight per RAW — only Blindsight
   bypasses fog. Deferred: Devil's Sight (Warlock invocation that
   bypasses magical darkness without truesight), illusion auto-
   detection, shapechanger original-form. 29 new tests across the
   magical-darkness helper, cli loading, blindsight bypass cases
   (including self-Blinded), truesight bypass cases (including
   spell-source Invisible + range boundary), magical-darkness
   specifics (ordinary DV blocked, truesight pierces, overlapping
   zones), and precedence interactions. New
   `vision_types_showcase_encounter.yaml` fixture with four
   observers (no-senses / DV-only / truesight / blindsight) facing
   an invisible target inside a magical-darkness zone.
23. ~~**Skill proficiencies + passive Perception + Hide auto-spot**~~ —
   **Shipped in PR #51.** Closes the Hide arc with the
   detection-side mechanic. New `engine/core/skills.py` centralizes
   the 5e 2024 skill list (18 skills), the skill→ability mapping,
   and `skill_modifier(actor, skill)` — reads `template.skills.<name>`
   directly for monsters (SRD shape) or falls back to ability + PB
   if proficient for PCs. `has_skill_proficiency(actor, skill)` works
   off either source. PC schemas now accept
   `skill_proficiencies: [stealth, perception, ...]`; the list is
   validated against the known set, normalized, and baked onto the
   template (top-level + `derived_from_pc_schema` block). Passive
   Perception auto-computed for PC templates (10 + WIS_mod + PB if
   Perception-proficient) and exposed via `senses.passive_perception`
   to match monster shape. New `Actor.passive_perception: int` field
   loaded by `cli._build_actor` from the template (or explicit
   actor_spec override). `_execute_hide` now adds Stealth proficiency
   PB via `skill_modifier(actor, "stealth")` and records the rolled
   `stealth_total` on the resulting `co_invisible` condition.
   `can_actor_see` extended: if target has Hide-source Invisible
   (`source_action_id == "a_hide"`) AND observer's `passive_perception
   >= stealth_total`, observer auto-spots them (returns True, then
   falls through to remaining gates — fog + darkness still block
   even after a successful Perception spot). Spell-source Invisible
   (Invisibility / Greater Invisibility) is NOT bypassable; only
   Hide is. Deferred: active Perception search-as-action, skill
   expertise (double PB), magic-item bonuses to Perception. 32 new
   tests across the skills module, pc_schema integration, hide
   wiring, cli loading, and vision auto-spot.
22. ~~**Dark zones + Dim light zones + Darkvision**~~ —
   **Shipped in PR #50.** Extends the vision system started in
   PR #47 with light-level zones + per-actor darkvision range. Two
   new environment fields: `encounter.environment.dim_light_zones`
   and `encounter.environment.dark_zones` — both axis-aligned-rect
   lists matching `heavily_obscured_zones` shape from PR #48. New
   `Actor.darkvision_range_ft: int` field (defaults 0 = no
   darkvision). Loaded from monster template's
   `senses.special.darkvision` (numeric feet) OR from an explicit
   `darkvision_range_ft:` actor_spec override (racial PC darkvision
   lives here until race modeling lands). New vision helpers
   `is_in_dim_light_zone` / `is_in_dark_zone`. `can_actor_see`
   extended with one new gate: if either observer or target is in
   a dark zone, observer needs darkvision AND must be within range
   (RAW: darkvision treats darkness within range as dim light).
   Dim light does NOT block sight in v1 — RAW only adds Perception
   disadvantage, which lands when active-Perception checks land.
   Precedence: blinded > invisible > heavy obscurement > dark zone
   (with darkvision check). Deferred: Truesight (bypasses Invisible
   + magical darkness), Blindsight (sees within range regardless),
   per-tile light grid (vs zones), magical darkness (a higher tier
   ordinary darkvision can't bypass), active Perception check vs
   Hide DC. 24 new tests (66 total in vision + cover + light suite).
21. ~~**Great Weapon Fighting + damage_die_floor primitive**~~ —
   **Shipped in PR #49.** Adds a fourth Fighting Style option
   (`great_weapon_fighting`, non-SRD per PHB 2024). New
   `_roll_dice_expr_with_floor` dice helper clamps individual rolls
   to `max(roll, floor)`; `_damage` primitive reads
   `damage_die_floor` from params and routes through it. Crit
   doubles dice AND applies the floor to both roll passes. The
   modifier is unaffected (RAW: floor applies only to weapon damage
   dice). `pc_schema._build_weapon_action` injects
   `damage_die_floor: 3` into the damage step's params when the
   chosen Fighting Style is `great_weapon_fighting` AND the weapon
   is melee (has `reach_ft`) AND is two-handed (`two_handed: true`).
   Ranged-two-handed weapons (heavy crossbow) and one-handed melee
   are correctly excluded. Versatile weapons wielded two-handed are
   deferred until a runtime grip-state model lands. Bonus dice from
   other sources (Sneak Attack, smite) are NOT clamped because
   they're applied through separate primitive invocations — matches
   the RAW reading of "the weapon's damage die." No re-roll
   primitive was added (none currently needed: Lucky / Halfling
   Lucky are d20 re-rolls, not damage dice). Closes the GWF arc
   raised against PR #38.
20. ~~**Cover + Heavy Obscurement zones + Hide action**~~ —
   **Shipped in PR #48.** Cover: per-actor `cover` field (`half` /
   `three_quarters` / `none`) gives +2/+5 AC + DEX-save bonus. No
   total cover (would need attack-cancellation; deferred).
   Heavy Obscurement: `encounter.environment.heavily_obscured_zones`
   declares axis-aligned rects; `can_actor_see` returns False if
   either side is in a zone. Hide action: new `type: hide` gated on
   heavy obscurement OR ≥ 3/4 cover; rolls d20 + DEX_mod vs DC 15
   (no Stealth proficiency yet); on success applies `co_invisible`
   with source-tag `a_hide` so subsequent attacks scrub it. Closes
   the Hide arc deferred since PR #29. Cover-from-creatures,
   active-Perception checks, AI scoring for Hide, hide-ends-on-cast,
   and Stealth proficiency still deferred. New
   `engine/core/vision.py` exposes `can_actor_see(observer, target,
   state)` — returns False if observer Blinded OR target Invisible,
   True otherwise. Wired into `_eval_when` so the
   `attacker_can_see(self)` / `target_can_see(self)` atoms actually
   compute (previously they were unknown atoms returning False,
   which happened to give correct behavior for the Invisible
   condition's specific clauses but not for anything else). Reaction
   conditions tightened to respect RAW "you can see" gates:
   Counterspell, Hellish Rebuke, and Protection now skip when the
   relevant creature is Invisible or the reactor is Blinded.
   Truesight / Blindsight / Darkvision / light levels / Heavily
   Obscured zones / Hide action all deferred — `can_actor_see` is
   the right place to extend when they land.
   New `spell_cast_initiated` event fires before any spell-slot
   action's pipeline runs (after slot availability check). The
   `state.cast_cancelled` flag — set by reactions like Counterspell —
   is checked by `pipeline.execute` after the event resolves; if
   True, the target spell's pipeline is skipped but the slot is
   still consumed (RAW 2024). Concentration is also skipped on
   cancel (RAW: original caster's concentration doesn't take hold
   when the spell fizzles). New `_counterspell_resolve` primitive
   handles the RAW level check (auto-cancel ≤ 3) + Intelligence
   (Spellcasting) ability check vs DC = 10 + spell_level for level
   ≥ 4. New reaction condition `enemy_casting_spell_within_60_ft`.
   `f_counterspell.yaml` (SRD, Wizard 3rd-level). Closes the
   reaction-system arc. New trigger event vocabulary
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
