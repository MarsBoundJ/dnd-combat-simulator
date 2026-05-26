# Engine Capabilities — Checkpoint

**Last updated:** 2026-05-25
**Engine state:** Phase 1, post-PR #17 (AoE Geometry merged).
**Test surface:** 238 tests across 9 modules; 9 CLI fixtures.

This document captures what the simulator can actually do today — in
observable behavioral terms, not module inventories. The companion
`pillars-reconciliation.md` defines the *intended* design; this
document describes what's *wired up*.

A reader should be able to answer two questions from this doc alone:
*"What can the AI demonstrate right now?"* and *"What's the next thing
I'd see if I tried X?"*

**Status headline:** as of PR #17 the engine has the **entire 8-step
decision pipeline live**, **all 4 dials** with v1 implementations, **RP
Constraints** as identity overlay, **positioning + movement +
reachability**, **opportunity attacks** as the first reaction type, and
**multi-target AoE** with friendly-fire scoring. Remaining work is
content breadth, additional primitives, and depth-within-system, not
new architecture.

---

## 1. What the AI Can Demonstrate Today

These behaviors are verifiable by running the CLI on the bundled
fixtures or by reading the integration tests. They are not "designed
for"; they fall out of the math.

### Targeting (5 dial presets, all live)

| Preset | Behavior demonstrable in a test? |
|---|---|
| `closest_enemy` | ✅ **Picks by real grid distance** (was: turn-order fallback before positioning); ties broken by turn order |
| `weakest_target` | ✅ Picks lowest current HP. Goblins (cowardly_skirmisher) attack the 5-HP fighter before the 28-HP one in `two_pc_encounter.yaml`. |
| `most_dangerous` | ✅ Picks the highest threat-score enemy (CR × 10 + max_attack_bonus × 2 + spellcaster signal +5). |
| `caster_first` | ✅ Prefers any visible spellcaster; falls back to `most_dangerous`. |
| `optimal_ehp` | ⚠️ Degrades to `caster_first` for v1 — joint (target × ability) eHP optimization deferred. |

**Universal finish-off rule:** INT ≥ 4 creatures deviate from their
preset when an enemy is below 15% HP. Mindless creatures (INT 1-3) do
not.

### Ability selection (5 dial presets)

| Preset | Status |
|---|---|
| `mindless` | ✅ Always uses the first action. |
| `instinctive` | ✅ Prefers `is_signature: true` flagged actions. |
| `default` | ✅ Multiattack > weapon_attack > first listed. |
| `tactical` | ✅ Picks the highest-EV action against the chosen target via offensive-eHP scoring. |
| `optimal` | ⚠️ Aliases to `tactical` for v1. |

### Action Economy (5 dial presets — all live)

Per-slot stochastic resolution within each turn:

| Preset | Main % | Sig Bonus % | Tac Bonus % | OA Rxn % | Sophist Rxn % |
|---|---|---|---|---|---|
| Optimal | 100 | 100 | 100 | 100 | 100 |
| Skilled | 90 | 95 | 85 | 100 | 80 |
| Average | 85 | 95 | 60 | 95 | 40 |
| Casual | 75 | 90 | 30 | 85 | 10 |
| Reactive_only | 65 | 80 | 0 | 80 | 0 |

- **Main slot "miss"** — at `(1 - main_optimality)` rate, the chosen
  candidate is downgraded to the actor's **default action** (first
  `weapon_attack`), preserving target. Logs `action_downgraded`.
- **Bonus slot** — runner runs Main → Bonus per turn. Bonus candidates
  use eHP scoring; usage gated by `signature_bonus_pct` vs
  `tactical_bonus_pct`.
- **OA reactions — LIVE as of PR #16** (see §"Opportunity Attacks" below).
  No longer a wired-but-dormant percentage.
- **Sophisticated reactions** — still wired-but-dormant; trigger
  plumbing deferred.
- **`play_context: solo`** PC modifier shifts preset down one tier.

### Retreat (5 dial presets — DMG p48 algorithm)

Operates **above** all other dials. Per `pillars-reconciliation.md` §5.1:

| Preset | Bloodied % | Ally-disparity | Frightened-alone | In-combat DC |
|---|---|---|---|---|
| FtD | (algorithm disabled — never flees) ||||
| Resolute | 35% | >75% | No | 8 |
| Default | 50% | >50% | Yes | 10 |
| Cowardly | 60% | 1 ally falls | Yes | 13 |
| Pacifist | 50% | >50% | Yes (parley first — deferred) | 10 |

Mindless override (INT ≤ 2 OR archetype `mindless_aggressor` → never
flees) + compound logic (Resolute requires Bloodied AND another
trigger) + WIS save → fail = flee.

Default preset is the live baseline for any actor without an explicit
retreat dial. PCs included.

### RP Constraints (3 types — Tier 1/2/3 architecture)

| Type | Tier | Mechanism | Example shipped |
|---|---|---|---|
| Hard Filter | 1 | Set-intersection removal of candidates; empty → Pass-turn fallback | `pacifist_strict` |
| Forced Choice | 2 | Highest-priority triggered constraint applies score boost (others suppressed) | `heal_priority` (prio 80), `signature_first` (prio 50) |
| Weighted Preference | 3 | All matching constraints applied additively in single pass | `resource_hoarder` (-30% on spell candidates) |

Schema: `behavior_profile.rp_constraints: [{id, severity?, priority?}]`
on actor template. Hard Filter severity locked at 1.0 per §6.3.

**v1 ships 4 of 12 canonical constraints** (one+ per type). The
remaining 8 are recipes in the same shape; ship when fixture demand
arises.

### Positioning, movement, reachability (PR #15)

Real 2D grid + reachability filtering. The biggest structural unblock
in the engine's history.

- **Positions are real** — `Actor.position` is `(x, y)` in 5-ft squares
  per the CLI loader's `position: [x, y]` field on actor_spec.
- **Distance** uses Chebyshev × 5 (5e 2024 "diagonals = 5 ft" rule —
  simpler than the alternating 5/10 rule).
- **Movement** — runner's `_move_to_engage` greedily closes on the
  dial-preferred target up to walk speed, **stopping at max reach** so
  creatures land adjacent rather than stacked on the target's square.
- **Reachability filter** in `generate_candidates`:
  - Melee → action's `reach_ft` (default 5)
  - Ranged → action's `range_ft`
  - Heal/buff allies → generous range for v1 (touch-range deferred)
- **Out-of-range guard** in `attack_roll` — defensive auto-miss
  (with telemetry) for any attack invoked beyond its reach.
- **`attacker_within_ft(N)` / `attacker_not_within_ft(N)` when-clauses**
  now actually evaluate against real positions (were defaulting
  TRUE/FALSE before positioning landed).

### Opportunity attacks (PR #16)

The first reaction type wired. The AE dial's `oa_reaction` percentages
(80-100% across presets) now actually fire.

- **Trigger**: reactor's melee reach covered the mover's pre-move
  position AND does NOT cover the mover's post-move position (mover
  left their reach).
- **Decision**: roll vs `oa_reaction` percentage from reactor's AE
  preset. Optimal/Skilled = 100%; Reactive_only = 80%. Even mindless
  creatures OA — "they moved, I swing."
- **Execution**: single melee weapon attack from reactor → mover.
  Mover's position is temporarily restored to pre-move for the OA
  attack roll (so reach math sees the in-reach distance), then
  restored to post-move.
- **One per reactor per round** — uses `actions_used_this_turn["reaction"]`.
- **Mover may drop mid-engagement** — runner checks `is_alive()`
  after movement and skips cleanly.

### AoE attacks (PR #17)

The first multi-target eHP scoring. Wizards can now Fireball clusters.

- **Sphere shape** (v1). Cone + Line deferred. Per 2024 PHB:
  Chebyshev radius — a 20-ft sphere covers all squares within 4
  squares cardinal/diagonal.
- **Candidate generation** — for `aoe_attack` actions, one candidate
  per living enemy whose position is within `area.range_ft` of the
  caster, with `origin_point = enemy.position`. Naturally tries
  clusters (placing on enemy A hits A + neighbors).
- **eHP scoring** — for each living creature in radius:
  `(p_fail × full_dmg) + (p_save × half_dmg)`, capped at target HP.
  Positive for enemies, **negative for allies** (friendly fire,
  1.0 weight in v1). Caster counts as ally — **don't fireball yourself**
  is a real engine invariant.
- **Half-damage-on-save** via `damage` primitive's new `multiplier`
  parameter (0.5 = half, 2.0 = doubled).
- **Per-target swap in `_forced_save`** — iterates affected creatures,
  swaps `state.current_attack.target` per iteration so damage
  primitives hit the right creature, then restores.

### Conditions actually affect AI choices

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
| `berserker_fanatic` | 1.5 (most aggressive) |
| `mindless_aggressor` | 1.3 |
| `apex_predator` | 1.1 |
| `pack_hunter` | 1.1 |
| `territorial_beast` | 1.0 |
| `cowardly_skirmisher` | 0.8 (under-commits) |
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
| 0. Resolve effective profile | 🟡 Reads `actor.template.behavior_profile`; archetype defaults via `_ARCHETYPE_DEFAULTS` table. Faction profiles, instance overrides, form transitions, runtime overrides (Frightened/Dominate/Confusion) all deferred. |
| 1. Retreat trigger check | ✅ DMG p48 algorithm via `engine/ai/retreat.py`. |
| 2. Generate candidates | ✅ Enumerates weapon_attack / multiattack / heal / defensive_buff / hard_control / **aoe_attack** per slot. Slot-aware (`action` / `bonus_action`). Reachability-filtered. |
| 3. Apply RP Hard Filters | ✅ Tier 1 set-intersection. Empty set logs `passed_turn` event. |
| 4. Apply RP Forced Choices | ✅ Pass-through at pipeline level; score-boost work at scoring time per §6.3. |
| 5. Score each candidate | ✅ Offensive eHP (single + multi-target) + defensive eHP per type, scaled by aggression coefficient, plus Tier 2 forced-choice boost + Tier 3 weighted preferences. |
| 6. Select max-scoring candidate | ✅ Stable max. |
| 7. Apply Action Economy per slot | ✅ Main-slot optimality roll; bonus slot gating; **OA reactions** via runner during movement events. |
| 8. Execute | ✅ Dispatches single actions; multiattack loops sub-attacks; **AoE candidates propagate `origin_point` into state for forced_save area filtering**. |

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
| **AoE multi-target damage** | ✅ **NEW PR #17** — sphere shape; per-target overkill cap; half-damage-on-save folded in | `engine/ai/ehp_scoring.py` |
| **Friendly fire penalty in AoE** | ✅ **NEW PR #17** — allies in radius subtract from score; caster counts as ally | `engine/ai/ehp_scoring.py` |
| Direct healing (defensive) | ✅ | `engine/ai/defensive_ehp.py` |
| Defensive buff (defensive) | ✅ | `engine/ai/defensive_ehp.py` |
| Hard control / action denial | ✅ | `engine/ai/defensive_ehp.py` |
| Offensive buff for allies (Bless) | 🔴 Deferred — math symmetric to defensive buff; needs cross-actor `attack_modifier` lookup at score-time |
| Soft control / movement denial | 🔴 Deferred — needs movement-restriction modifier types |
| Debuff on enemy saves | 🔴 Deferred |
| **AoE Cone + Line shapes** | 🔴 Deferred — sphere only v1 |
| Opportunity cost — spell slots | 🔴 Deferred — needs slot tracking on actors |
| Opportunity cost — action economy alternatives | 🔴 Deferred |
| Future-rounds discounting | 🔴 Deferred — flat 2.5-round constant for buffs/control |
| Concentration management | 🔴 Deferred |
| Behavioral coefficients | 🟡 Only `aggression_coefficient` wired; `self_preservation_coefficient`, `pack_tactics_bonus`, `morale_threshold` deferred |

---

## 4. Primitives — Coverage

13 implemented (executable end-to-end through the runner); ~30 stubbed
(raise `NotImplementedError` if invoked).

**Implemented:**
attack_roll · damage (**now with `multiplier` param**) · apply_condition
· heal · granted_action · attack_modifier · save_modifier ·
d20_test_modifier · crit_modifier · crit_threshold_modifier · forced_save
(**now with area filtering + per-target target-swap**) · recurring_save
· multiattack

**Stubbed (most-likely-next-needed):** Dodge (would replace Pass-turn
RP fallback), Disengage (would grant no-OA-from-leaving — interacts
with PR #16), speed_modifier, damage_modifier, additional_action
(Action Surge), persistent_aura + triggered_save (Spirit Guardians),
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

`passed_turn → reason: rp_hard_filter_empty_set` logged every round.
**Zero attack_roll events from the pacifist** over 7 rounds. She
eventually flees alive when her Default retreat dial triggers from
Bloodied.

### Example 5 — Ranged-vs-melee positioning (NEW)

```
python -m engine.cli encounter tests/fixtures/ranged_vs_melee_encounter.yaml --seed 1
```

Halfling Archer (Longbow range 80) at (0,0) vs Goblin Brawler
(Scimitar reach 5) at (12, 0) = 60 ft. Archer shoots from position
(no `moved` event — bow already in range). Goblin closes 30 ft on
round 1 (still 30 ft out → `passed_turn`), then 25 ft on round 2
(stops at melee reach 5, not stacked on archer's square) and attacks.

Proves: positions used, reach filter works, no creature-stacking,
ranged attacker doesn't move when in range.

### Example 6 — Opportunity attack catches goblin slipping past (NEW)

```
python -m engine.cli encounter tests/fixtures/opportunity_attack_encounter.yaml --seed 1
```

Polearm Guardian (glaive reach 10) + immobile Wounded Cleric + Goblin
Scout. Goblin (weakest_target → healer) starts within glaive reach
but can't reach the guardian back; tries to slip past to attack the
healer. Round 1 log:

```
moved: goblin from [3,0] to [1,0]
opportunity_attack_triggered: reactor=guardian, mover=goblin
attack_roll: guardian → goblin (the OA, resolved at pre-move position)
attack_roll: goblin → healer (goblin's main action completes)
```

OA fires during the goblin's movement — semantically interrupts the
mover before reaching destination.

### Example 7 — Wizard Fireball at clustered goblins (NEW)

```
python -m engine.cli encounter tests/fixtures/fireball_cluster_encounter.yaml --seed 1
```

Wizard with Magic Dart + Fireball vs 3 goblins clustered at
(15, 0), (15, 1), (15, -1). Round 1 trace:

```
aoe_origin_placed: wizard at [15, 0]  ← AI picked the cluster center
forced_save: goblin_a → fail → 28 dmg FULL → DEAD
forced_save: goblin_b → success → 11 dmg HALF (8d6 × 0.5)
forced_save: goblin_c → success → 11 dmg HALF
```

Single Fireball: 1 goblin dropped outright, 2 left at 3 HP. 2-round
PC victory.

### Example 8 — Multiattack still works

```
python -m engine.cli encounter tests/fixtures/test_multiattack_encounter.yaml --seed 1
```

A monster with `multiattack: count 2` loops its sub-attack pipeline
twice per turn. The PC fighter eventually flees at low HP per Default
retreat trigger.

---

## 6. Test Surface

```
$ python -m unittest discover -s tests
..............................................................................
..............................................................................
..............................................................................
.....
Ran 238 tests in 5s
OK
```

| Module | Tests | What it covers |
|---|---|---|
| `tests/test_smoke.py` | 4 | End-to-end: skeleton encounter loads, runs, terminates with a winner. |
| `tests/test_primitives_v1.py` | 12 | Attack roll w/ modifiers; condition application; Q5 modifier query layer; multiattack loop. |
| `tests/test_ai_v1.py` | 19 | All 5 targeting presets; behavior profile resolution; ability selection; finish-off rule; goblin-attacks-wounded-PC integration. |
| `tests/test_ehp_scoring.py` | 34 | dice_mean, hit_probability, crit math; expected damage; overkill cap; aggression coefficient; tactical preset highest-EV pick; AI prefers Blinded target. |
| `tests/test_defensive_ehp.py` | 34 | Desperation multiplier; healing eHP; DPR estimation; defensive buff; hard control; cleric-heals-dying-ally integration. |
| `tests/test_action_economy.py` | 30 | Preset table correctness; main-slot optimality; bonus-slot gating; slot-aware candidate gen; runner integration. |
| `tests/test_retreat.py` | 26 | Preset bundle table; mindless override; FtD invariance; all 3 triggers; Resolute compound; WIS save mechanics; runner integration. |
| `tests/test_rp_constraints.py` | 19 | Library + active-constraint resolution; hard filter intersection + empty-set fallback; forced-choice boost + priority resolution; weighted preference; behavioral integration. |
| `tests/test_positioning.py` | 29 | Distance / movement / reachability geometry; closest_enemy by distance; reach filter in candidate gen; attack_roll out-of-range guard; when-clause evaluation; runner movement integration. |
| `tests/test_opportunity_attacks.py` | 16 | Trigger detection; reaction slot tracking; AE percentage gating; runner integration (OA fires in real encounter, ranged-only attacker never OAs). |
| `tests/test_aoe.py` | 15 | actors_in_radius geometry; damage multiplier (half/double); AoE eHP (single enemy, cluster, friendly fire, self-fireball); candidate generation; end-to-end Fireball-on-cluster. |

**Fixtures (`tests/fixtures/`):** `smoke_encounter.yaml`,
`two_pc_encounter.yaml`, `test_multiattack_encounter.yaml`,
`cleric_heals_ally_encounter.yaml`, `nimble_goblin_encounter.yaml`,
`pacifist_encounter.yaml`, **`ranged_vs_melee_encounter.yaml`**,
**`opportunity_attack_encounter.yaml`**, **`fireball_cluster_encounter.yaml`**.

---

## 7. Roadmap — Honest Gap List

The engine has the **decision shape** right (Ammann pillar dials +
eHP framework as the scoring spine + RP Constraints as the identity
overlay), AND now the **spatial shape** right (positions, reachability,
reactions, multi-target AoE). Remaining work is content breadth and
depth-within-system. In rough priority order:

1. **PC schema** — currently using inline-monster-template hack in PC
   fixtures. A first-class PC schema with class/level/feats/equipment
   slots would clean this up substantially and let us load proper
   classed PCs from the existing schema.
2. **Offensive buff for allies (Bless shape)** — math symmetric to
   defensive buff. Small focused PR; needs cross-actor
   `attack_modifier` lookup at score-time.
3. **Spell slot opportunity cost** — needed for proper caster eHP
   scoring. Unlocks the Fireball-vs-Hypnotic-Pattern worked example
   from `ehp-action-framework.md`.
4. **Cone + Line AoE shapes** — natural follow-on to AoE v1. Covers
   Burning Hands, Cone of Cold, Lightning Bolt. Geometry helpers
   parallel to `actors_in_radius`.
5. **More primitives** — Dodge (replaces Pass-turn RP fallback),
   Disengage (grants no-OA-from-leaving, interacts with PR #16),
   Action Surge (`additional_action`), Spirit Guardians (`persistent_aura`
   + `triggered_save`), Arcane Recovery (`slot_recovery_partial`),
   spellcasting infrastructure.
6. **Concentration management** — auto CON saves on damage when caster
   has active concentration spell; AI decision of whether to break
   current concentration to cast new spell.
7. **3-level profile inheritance** (archetype → faction → instance) +
   runtime override layer (Frightened / Dominate / Confusion) per
   §4.4.
8. **Behavioral coefficients beyond aggression** —
   `self_preservation_coefficient` (scales defensive eHP),
   `pack_tactics_bonus` (coordinates with allies), `morale_threshold`
   (deeper retreat dial modulation).
9. **Remaining 8 of 12 canonical RP constraints** — recipes in
   `pillars-reconciliation.md` §6.5; ship when fixture demand arises.
10. **Pyodide / browser deployment** — Stage 2 task per
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
| What's the rationale for a specific decision in the AI module? | The module docstrings in `engine/ai/*.py` |
| When was X shipped, with what scope, and what was deferred? | `docs/SESSIONS.md` (chronological) + PR descriptions |
| What's the current snapshot for paste-at-session-start? | `docs/CONTEXT.md` |
