# Engine Capabilities — Checkpoint

**Last updated:** 2026-05-26
**Engine state:** Phase 1, post-PR #22 (Spell Slots merged).
**Test surface:** 324 tests across 13 modules; 11 CLI fixtures.

This document captures what the simulator can actually do today — in
observable behavioral terms, not module inventories. The companion
`pillars-reconciliation.md` defines the *intended* design; this
document describes what's *wired up*.

A reader should be able to answer two questions from this doc alone:
*"What can the AI demonstrate right now?"* and *"What's the next thing
I'd see if I tried X?"*

**Status headline:** as of PR #22 the engine has the **entire 8-step
decision pipeline live**, **all 4 dials** with v1 implementations,
**RP Constraints** as identity overlay, **positioning + movement +
reachability**, **opportunity attacks** as the first reaction type,
**multi-target AoE** with friendly-fire scoring, **offensive +
defensive ally buffs**, **concentration** with damage-triggered CON
saves, **spell slot opportunity cost** in eHP scoring, and the
**compact PC schema** for fixture authoring. Remaining work is
content breadth, additional primitives, and depth-within-system, not
new architecture.

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
  by signature vs tactical rate; OA reactions LIVE (PR #16);
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
- **`move_toward`** with `stop_at_ft` so creatures land adjacent, not
  stacked on the target's square
- **Reachability filter** in `generate_candidates`: melee `reach_ft` /
  ranged `range_ft`; heal/buff allies generous
- **Out-of-range guard** in `attack_roll` — defensive auto-miss
- **`attacker_within_ft(N)` when-clauses** evaluate against real positions
- **Movement phase** in runner: try to act → move toward dial-preferred
  target → try again → log `passed_turn` if still unreachable

### Opportunity attacks (PR #16)

- **Trigger**: reactor's melee reach covered mover's pre-move position
  AND does NOT cover post-move position
- **Decision**: roll vs `oa_reaction` percentage from reactor's AE preset
- **Execution**: single melee weapon attack against the mover at
  pre-move position (position snapped/restored)
- **One per reactor per round** via `actions_used_this_turn["reaction"]`

### AoE attacks (PR #17)

- **Sphere shape** (v1); cone + line deferred
- **Candidate generation** — one per living enemy whose position is
  within `area.range_ft` of caster, with `origin_point = enemy.position`
  (catches "cast on cluster" naturally)
- **eHP scoring** — sum across radius: `(p_fail × full) + (p_save × half)`,
  capped per target. **Positive for enemies, negative for allies
  (friendly fire).** Caster counts as ally
- **Half-damage-on-save** via `damage` primitive's `multiplier` param
- **Per-target swap in `_forced_save`** so damage hits each affected
  creature with their own roll resolution

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

Engine derives HP (`L1 max + L2+ avg per die + CON`), AC, PB by level,
save bonuses (mod + PB if class-proficient), per-weapon attack actions
(`attack_bonus = ability_mod + PB`, `damage_modifier = ability_mod`).

### Offensive buffs for allies — Bless shape (PR #20)

- **Action type `offensive_buff`** with `target: ally` on the
  `attack_modifier` primitive
- **eHP scoring**: `ally_DPR × Δhit × EXPECTED_BUFF_ROUNDS (2.5)`
- **Δhit math**: +1 flat ≈ +5% hit chance; advantage ≈ +22.5% (framework
  reference values)
- **Dedup**: returns 0 if target already has this exact buff from this
  caster — prevents wasted re-casts. Source-tagged via
  `_build_modifier_entry`'s `{action_id, caster_id}`.

### Concentration (PR #21)

- **One slot per actor** (`Actor.concentration_on`)
- **`concentration: true` flag** on actions marks them as concentration
  spells; pipeline auto-tracks the slot at execution
- **New cast auto-drops old** — caster can only maintain one concentration
  spell at a time
- **CON save on damage taken** — `DC = max(10, ⌈damage/2⌉)`; failure
  ends concentration. Hook lives in `_damage` so every damage path
  triggers automatically (weapon, AoE on_fail/on_success, OAs,
  multiattack sub-attacks)
- **Death ends concentration** — runs before `creature_dropped` event so
  listeners see a clean state

### Spell slot opportunity cost (PR #22)

- **`Actor.spell_slots: dict[int, int]`** — per-actor slot tracking
- **`action.spell_slot_level`** declares required slot
- **Candidate filter** — spells with no available slot are excluded
- **eHP cost subtracted at scoring** per framework formula:
  `slot_level × 3.0 × scarcity × (1 - urgency)` where `scarcity =
  1/max(1, slots_remaining)`, `urgency = encounters_remaining / 6`
  (default `CombatState.encounters_remaining_today = 3`)
- **Execution consumes** — `_execute_single` decrements actor's slot
- **Reference value verified**: 3rd-level slot, 1 left, end-of-day =
  9.0 eHP (matches the worked example exactly)

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
| Defensive buff | `worst_enemy_DPR × Δmiss × 2.5 rounds` | ✅ |
| Hard control (save-or-lose) | `enemy_DPR × p_fail × 2.5 rounds × denial_fraction` | ✅ |

---

## 2. Decision Pipeline — Step-by-Step Status

The 8-step pipeline from `pillars-reconciliation.md` §7 lives in
`engine/core/pipeline.py`. All 8 steps wired:

| Step | Status |
|---|---|
| 0. Resolve effective profile | 🟡 Reads `actor.template.behavior_profile`; archetype defaults via `_ARCHETYPE_DEFAULTS`. Faction profiles, instance overrides, form transitions, runtime overrides all deferred. |
| 1. Retreat trigger check | ✅ DMG p48 algorithm via `engine/ai/retreat.py`. |
| 2. Generate candidates | ✅ Enumerates weapon_attack / multiattack / heal / defensive_buff / hard_control / aoe_attack / **offensive_buff** per slot. Slot-aware. Reachability-filtered. **Spell-slot-availability-filtered**. |
| 3. Apply RP Hard Filters | ✅ Tier 1 set-intersection. Empty set logs `passed_turn` event. |
| 4. Apply RP Forced Choices | ✅ Pass-through; score-boost at scoring time per §6.3. |
| 5. Score each candidate | ✅ Offensive + defensive eHP per type, **minus spell-slot cost**, scaled by aggression, plus Tier 2/3 RP score modifications. |
| 6. Select max-scoring candidate | ✅ Stable max. |
| 7. Apply Action Economy per slot | ✅ Main-slot optimality roll; bonus slot gating; OA reactions via runner during movement. |
| 8. Execute | ✅ Single actions / multiattack loops / AoE area filtering. **Consumes spell slot if `spell_slot_level > 0`**. **Marks concentration slot if `concentration: true`**. |

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
| AoE multi-target damage | ✅ (sphere only) | `engine/ai/ehp_scoring.py` |
| Friendly fire penalty in AoE | ✅ | `engine/ai/ehp_scoring.py` |
| **Offensive buff for allies (Bless)** | ✅ **NEW PR #20** — `ally_DPR × Δhit × 2.5 rounds`; dedup against same-buff re-cast | `engine/ai/ehp_scoring.py` |
| Direct healing (defensive) | ✅ | `engine/ai/defensive_ehp.py` |
| Defensive buff (defensive) | ✅ | `engine/ai/defensive_ehp.py` |
| Hard control / action denial | ✅ | `engine/ai/defensive_ehp.py` |
| **Opportunity cost — spell slots** | ✅ **NEW PR #22** — framework formula; verified against the 9.0 eHP Fireball worked example | `engine/core/spell_slots.py` |
| **Concentration management** | ✅ **NEW PR #21** — single slot per actor, auto-drop on new cast, CON save on damage, drop on death | `engine/core/concentration.py` |
| AoE Cone + Line shapes | 🔴 Deferred — sphere only v1 |
| Soft control / movement denial | 🔴 Deferred — needs movement-restriction modifier types |
| Debuff on enemy saves | 🔴 Deferred |
| Opportunity cost — action economy alternatives | 🔴 Deferred |
| Future-rounds discounting | 🔴 Deferred — flat 2.5-round constant for buffs/control |
| Behavioral coefficients | 🟡 Only `aggression_coefficient` wired; `self_preservation_coefficient`, `pack_tactics_bonus`, `morale_threshold` deferred |

---

## 4. Primitives — Coverage

13 implemented (executable end-to-end through the runner); ~30 stubbed.

**Implemented (with notable extensions noted):**
attack_roll · **damage (now with `multiplier` param)** · apply_condition
· heal · granted_action · **attack_modifier (now supports `target: ally`)**
· save_modifier · d20_test_modifier · crit_modifier ·
crit_threshold_modifier · **forced_save (area filtering + per-target
target-swap)** · recurring_save · multiattack

**Stubbed (most-likely-next-needed):** Dodge (replaces Pass-turn RP
fallback), Disengage (grants no-OA-from-leaving — interacts with PR
#16), additional_action (Action Surge), persistent_aura +
triggered_save (Spirit Guardians), speed_modifier, damage_modifier,
slot_recovery_partial (Arcane Recovery), spellcasting_enable,
spell_grant.

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

Goblin (cowardly_skirmisher → `weakest_target`) attacks the wounded
fighter (5 HP) before the healthy fighter (28 HP). After the wounded
fighter dies, the healthy fighter (Default retreat preset → 50%
ally-disparity trigger) fails the WIS save and flees.

### Example 2 — Cleric heals the dying ally

```
python -m engine.cli encounter tests/fixtures/cleric_heals_ally_encounter.yaml --seed 1
```

Cleric's first action is `healed → fighter_dying +10`, not a mace
swing. The surviving goblin then panics and flees when its partner
dies (Cowardly "1 ally falls" trigger).

### Example 3 — Skilled goblin uses both main + bonus action slots

```
python -m engine.cli encounter tests/fixtures/nimble_goblin_encounter.yaml --seed 1
```

Round 1 event log shows **two** attack_roll events from the goblin:
scimitar (main) hit, off-hand jab (signature bonus). Both slots fire
in one turn.

### Example 4 — Pacifist Pass-turns instead of attacking

```
python -m engine.cli encounter tests/fixtures/pacifist_encounter.yaml --seed 1
```

`passed_turn → reason: rp_hard_filter_empty_set` every round. **Zero
attack_roll events from the pacifist** over 7 rounds. She eventually
flees alive when her Default retreat dial triggers from Bloodied.

### Example 5 — Ranged-vs-melee positioning

```
python -m engine.cli encounter tests/fixtures/ranged_vs_melee_encounter.yaml --seed 1
```

Halfling Archer (Longbow range 80) at (0,0) vs Goblin Brawler
(Scimitar reach 5) at (12, 0) = 60 ft. Archer shoots from position
(no `moved` event). Goblin closes 30 ft on round 1 (passed_turn),
then 25 ft on round 2 (stops at melee adjacency) and attacks.

### Example 6 — Opportunity attack catches goblin slipping past

```
python -m engine.cli encounter tests/fixtures/opportunity_attack_encounter.yaml --seed 1
```

Polearm Guardian (glaive reach 10) + immobile Wounded Cleric + Goblin
Scout. Round 1 log:

```
moved: goblin from [3,0] to [1,0]
opportunity_attack_triggered: reactor=guardian, mover=goblin
attack_roll: guardian → goblin (resolved at pre-move position)
attack_roll: goblin → healer (goblin's main action completes)
```

### Example 7 — Wizard Fireball at clustered goblins

```
python -m engine.cli encounter tests/fixtures/fireball_cluster_encounter.yaml --seed 1
```

3 goblins clustered at (15, ±). Round 1 trace:

```
aoe_origin_placed: wizard at [15, 0]  ← AI picked cluster center
forced_save: goblin_a → fail → 28 dmg FULL → DEAD
forced_save: goblin_b → success → 11 dmg HALF (8d6 × 0.5)
forced_save: goblin_c → success → 11 dmg HALF
```

### Example 8 — PC schema fighter (compact authoring)

```
python -m engine.cli encounter tests/fixtures/pc_schema_fighter_encounter.yaml --seed 1
```

Level 3 Fighter via the compact `pc:` spec (15 lines) vs Goblin
Warrior via `template_ref:`. Engine derives HP=28, AC=17, PB=2,
STR/CON saves +5/+4, longsword +5 to hit / 1d8+3. **Behaviorally
identical** to the legacy inline-template `smoke_encounter.yaml`.

### Example 9 — Bless + concentration + slot consumption (NEW)

```
python -m engine.cli encounter tests/fixtures/bless_buff_encounter.yaml --seed 1
```

Cleric (Mace + Bless) + Fighter (Greatsword) + Bruiser. Cleric goes
first; Bless on fighter. Three systems intersect in the log:

```
concentration_started: cleric → a_bless, round 1
spell_slot_consumed: cleric, level 1, remaining 2, action a_bless
... fighter's attack rolls jump from +6 → +8 (Bless visible) ...
... cleric takes damage ...
concentration_save: dc=10, dmg=6, d20=6, total=7, FAIL
concentration_ended: reason=failed_con_save, removed_count=1
... fighter's attacks back to +6 (no Bless) ...
concentration_started: round 11 (re-cast — slot was available)
spell_slot_consumed: cleric, level 1, remaining 1
```

Bless re-casts continue until the 3rd slot is consumed, then the
cleric falls back to mace permanently. PR #20 + #21 + #22 all
demonstrated in one fixture.

### Example 10 — Multiattack

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
... 324 tests ...
OK
```

| Module | Tests | What it covers |
|---|---|---|
| `tests/test_smoke.py` | 4 | End-to-end: skeleton encounter loads, runs, terminates with a winner |
| `tests/test_primitives_v1.py` | 12 | Attack roll w/ modifiers; condition application; Q5 modifier query layer; multiattack loop |
| `tests/test_ai_v1.py` | 19 | All 5 targeting presets; behavior profile resolution; ability selection; finish-off rule |
| `tests/test_ehp_scoring.py` | 34 | dice_mean, hit/crit math; expected damage; overkill cap; aggression; tactical preset; AI prefers Blinded target |
| `tests/test_defensive_ehp.py` | 34 | Desperation; healing; DPR estimation; defensive buff; hard control; cleric-heals-dying-ally integration |
| `tests/test_action_economy.py` | 30 | Preset table; main-slot optimality; bonus-slot gating; runner integration |
| `tests/test_retreat.py` | 26 | Preset bundle; mindless override; FtD; all 3 triggers; Resolute compound; WIS save mechanics |
| `tests/test_rp_constraints.py` | 19 | Library + active-constraint resolution; hard filter; forced-choice + priority resolution; weighted preference |
| `tests/test_positioning.py` | 29 | Geometry; closest_enemy by distance; reach filter; out-of-range guard; when-clause evaluation; runner movement |
| `tests/test_opportunity_attacks.py` | 16 | Trigger detection; reaction slot; AE percentage gating; runner integration |
| `tests/test_aoe.py` | 15 | actors_in_radius; damage multiplier; AoE eHP (cluster, friendly fire, self-fireball); end-to-end Fireball |
| `tests/test_pc_schema.py` | 26 | PB by level; HP math; AC; save bonuses; weapon action gen; build_pc_template; loader integration; fixture run |
| `tests/test_offensive_buff.py` | 17 | extract; eHP math; ally-DPR scaling; advantage > +2 flat; dedup; runner integration |
| `tests/test_concentration.py` | 18 | Slot management; new-cast-replaces; CON save mechanics; damage hook; death hook; end-to-end via runner |
| `tests/test_spell_slots.py` | 25 | slot_cost_ehp formula (framework reference); has_slot / consume_slot; candidate filter; eHP cost subtraction; PC schema integration |

**Fixtures (`tests/fixtures/`):** `smoke_encounter.yaml`,
`two_pc_encounter.yaml`, `test_multiattack_encounter.yaml`,
`cleric_heals_ally_encounter.yaml`, `nimble_goblin_encounter.yaml`,
`pacifist_encounter.yaml`, `ranged_vs_melee_encounter.yaml`,
`opportunity_attack_encounter.yaml`, `fireball_cluster_encounter.yaml`,
`pc_schema_fighter_encounter.yaml`, `bless_buff_encounter.yaml`.

---

## 7. Roadmap — Honest Gap List

The engine has the **decision shape** right (Ammann pillar dials +
eHP framework as the scoring spine + RP Constraints as the identity
overlay), the **spatial shape** right (positions, reachability,
reactions, multi-target AoE), AND the **resource shape** right
(concentration + spell slots, with opportunity cost in eHP).
Remaining work is content breadth, additional primitives, and
depth-within-system. In rough priority order:

1. **Cone + Line AoE shapes** — natural follow-on to sphere. Covers
   Burning Hands, Cone of Cold, Lightning Bolt. Geometry helpers
   parallel to `actors_in_radius`.
2. **More primitives** — Dodge (replaces Pass-turn RP fallback),
   Disengage (grants no-OA-from-leaving, interacts with PR #16),
   Action Surge (`additional_action`), Spirit Guardians
   (`persistent_aura` + `triggered_save`), Arcane Recovery
   (`slot_recovery_partial`), spellcasting infrastructure.
3. **Class features auto-wiring** — Second Wind, Action Surge,
   Fighting Style are referenced in `c_fighter.level_table` but
   unwired. A "consume class features" pass on PC schema (#19) would
   pull them in automatically.
4. **Hypnotic Pattern fixture** — would showcase the canonical
   Fireball-vs-Hypnotic-Pattern eHP example from
   `ehp-action-framework.md`. Needs Incapacitated-applying AoE
   (forced_save → apply_condition with sphere shape). Small primitive
   composition.
5. **Incapacitation ending concentration** — small follow-on to #21.
   Hook the `apply_condition` path so Paralyzed/Stunned/Unconscious
   automatically end concentration on the affected caster.
6. **Named-effect tagging** for cross-caster buff dedup — small
   follow-on to #20. Currently dedup is per-(caster, action); two
   different casters can each apply their own Bless. Real 5e prevents
   same-named-spell stacking from any source.
7. **3-level profile inheritance** (archetype → faction → instance) +
   runtime override layer (Frightened / Dominate / Confusion) per
   §4.4.
8. **Behavioral coefficients beyond aggression** —
   `self_preservation_coefficient` (scales defensive eHP),
   `pack_tactics_bonus`, `morale_threshold` (deeper retreat dial
   modulation).
9. **Upcasting** — cast a 1st-level spell with a higher-level slot
   for amplified effect; needs the `upcast: scaling` rules from spell
   templates.
10. **Remaining 8 of 12 canonical RP constraints** — recipes in
    `pillars-reconciliation.md` §6.5; ship when fixture demand arises.
11. **Pyodide / browser deployment** — Stage 2 task per
    `docs/architecture/browser-deployment.md`. Build deferred until a
    Stage 2 report is ready to ship.

---

## 8. Source of Truth Pointers

| For this question | Read this |
|---|---|
| What dial presets exist and what do they mean? | `docs/foundations/pillars-reconciliation.md` §5 |
| What eHP formulas govern action scoring? | `docs/foundations/ehp-action-framework.md` |
| How are RP Constraints structured (3 types, severity, priority)? | `docs/foundations/pillars-reconciliation.md` §6 |
| How does the schema represent monsters / PCs / spells / conditions? | `docs/architecture/schema-design.md` |
| Why Pyodide is a viable Stage 2 deployment target, what invariants protect it | `docs/architecture/browser-deployment.md` |
| What's the rationale for a specific decision in the AI module? | The module docstrings in `engine/ai/*.py` and `engine/core/*.py` |
| When was X shipped, with what scope, and what was deferred? | `docs/SESSIONS.md` (chronological) + PR descriptions |
| What's the current snapshot for paste-at-session-start? | `docs/CONTEXT.md` |
