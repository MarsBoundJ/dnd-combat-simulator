# Engine Capabilities — Checkpoint

**Last updated:** 2026-05-25
**Engine state:** Phase 1, post-PR #12 (RP Constraints merged).
**Test surface:** 178 tests across 7 modules; 6 CLI fixtures.

This document captures what the simulator can actually do today — in
observable behavioral terms, not module inventories. The companion
`pillars-reconciliation.md` defines the *intended* design; this document
describes what's *wired up*.

A reader should be able to answer two questions from this doc alone:
*"What can the AI demonstrate right now?"* and *"What's the next thing
I'd see if I tried X?"*

**Status headline:** as of PR #12, the **entire 8-step decision pipeline
is live**, all **4 dials** have v1 implementations, and RP Constraints
provide identity / personality / story behavioral filters. Remaining
work is breadth (more primitives, positions, content) and depth (defer-
tagged behaviors within each system), not new architecture.

---

## 1. What the AI Can Demonstrate Today

These behaviors are verifiable by running the CLI on the bundled
fixtures or by reading the integration tests. They are not "designed
for"; they fall out of the math.

### Targeting (5 dial presets, all live)

| Preset | Behavior demonstrable in a test? |
|---|---|
| `closest_enemy` | ✅ Picks first enemy in turn order (positions deferred). |
| `weakest_target` | ✅ Picks lowest current HP. Goblins (cowardly_skirmisher) attack the 5-HP fighter before the 28-HP one in `two_pc_encounter.yaml`. |
| `most_dangerous` | ✅ Picks the highest threat-score enemy (CR × 10 + max_attack_bonus × 2 + spellcaster signal +5). |
| `caster_first` | ✅ Prefers any visible spellcaster; falls back to `most_dangerous`. |
| `optimal_ehp` | ⚠️ Degrades to `caster_first` for v1 — joint (target × ability) eHP optimization deferred until defensive scoring covers more action types. |

**Universal finish-off rule:** INT ≥ 4 creatures deviate from their
preset when an enemy is below 15% HP. Mindless creatures (INT 1-3) do
not.

### Ability selection (5 dial presets)

| Preset | Status |
|---|---|
| `mindless` | ✅ Always uses the first action. |
| `instinctive` | ✅ Prefers `is_signature: true` flagged actions. |
| `default` | ✅ Multiattack > weapon_attack > first listed. |
| `tactical` | ✅ Picks the highest-EV action against the chosen target via offensive-eHP scoring. Longsword beats dagger when hit chances are equal; high-bonus weapon beats low-bonus when damage is close. |
| `optimal` | ⚠️ Aliases to `tactical` for v1. Joint (target × ability) optimization across defensive options deferred. |

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
  use eHP scoring; usage gated by `signature_bonus_pct` (for
  `is_signature: true`) vs `tactical_bonus_pct` (default).
- **`play_context: solo`** PC modifier shifts preset down one tier.
- **Reactions** — `is_reactive_trigger` tag + OA / sophisticated
  preset percentages are wired in the table but no reaction candidates
  are generated yet (deferred until positions land).

### Retreat (5 dial presets — DMG p48 algorithm)

Operates **above** all other dials — a retreat trigger overrides the
turn's action pipeline. Per `pillars-reconciliation.md` §5.1:

| Preset | Bloodied % | Ally-disparity | Frightened-alone | In-combat DC |
|---|---|---|---|---|
| FtD | (algorithm disabled — never flees) ||||
| Resolute | 35% | >75% | No | 8 |
| Default | 50% | >50% | Yes | 10 |
| Cowardly | 60% | 1 ally falls | Yes | 13 |
| Pacifist | 50% | >50% | Yes (parley first — deferred) | 10 |

**Algorithm:** mindless override (INT ≤ 2 OR archetype
`mindless_aggressor` → never flees) → trigger evaluation → compound
logic (Resolute requires Bloodied AND another trigger) → WIS save vs
`in_combat_dc` → fail = flee.

Default preset is the live baseline for any actor without an explicit
retreat dial. PCs included.

### RP Constraints (3 types — Tier 1/2/3 architecture)

| Type | Tier | Mechanism | Example shipped |
|---|---|---|---|
| Hard Filter | 1 | Set-intersection removal of candidates; empty → Pass-turn fallback | `pacifist_strict` |
| Forced Choice | 2 | Highest-priority triggered constraint applies score boost (others suppressed) | `heal_priority` (prio 80), `signature_first` (prio 50) |
| Weighted Preference | 3 | All matching constraints applied additively in single pass | `resource_hoarder` (-30% on spell candidates) |

Schema: `behavior_profile.rp_constraints: [{id, severity?, priority?}]`
on actor template. Hard Filter severity locked at 1.0 even if user
overrides (per §6.3 binary-only semantics).

**v1 ships 4 of 12 canonical constraints** (one+ per type, to prove
the framework end-to-end). The remaining 8 are recipes in the same
shape; ship when fixture demand arises.

### Conditions actually affect AI choices

The Q5 unified modifier registry feeds advantage / disadvantage / AC
swings into both *execution* (attack rolls, saves) and *scoring*
(hit_probability). The net effect:

- A **Blinded** target scores higher than an equivalent non-Blinded
  target, because attackers have advantage → higher hit probability →
  higher expected damage → higher offensive eHP. **No special-cased
  "prefer Blinded" code exists** — it falls out of the math.
- The same path will work for Restrained, Frightened (against the
  source), Prone, etc. as soon as those modifiers attach in fixtures.

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

This scales the raw eHP score before tie-break preferences are added.

### Defensive eHP — heal / buff / control

The cleric in `cleric_heals_ally_encounter.yaml` is the headline demo:

- 2 goblins attacking, dying fighter at 1/28 HP, cleric with mace +
  Cure Wounds at full HP.
- **Cleric's first action is `healed → fighter_dying +10 HP`,** not a
  mace attack. The math: heal eHP ≈ `(2d8 + wis_mod) × desperation`
  ≈ `12 × 1.46 ≈ 17.5 eHP` (capped at 27 missing HP); mace eHP ≈
  hit_prob × dmg ≈ 0.5 × 4.5 ≈ 2.3 eHP. Heal wins by ~7×.
- Fighter then makes a comeback and kills both goblins (then panics
  and flees when its partner dies, per Cowardly's "1 ally falls"
  retreat trigger).

The framework also scores:

- **Defensive buff** (AC bonus or disadvantage-for-attacker on an
  ally): `worst_enemy_DPR × Δmiss × 2.5 rounds`.
- **Hard control** (save-or-lose conditions: Paralyzed, Stunned,
  Petrified, Unconscious, Incapacitated): `enemy_DPR × p_fail × 2.5
  rounds × 1.0 denial`. Partial-denial conditions (Restrained,
  Blinded, Frightened, Grappled, Prone) score 0.2–0.5 denial.

A unit test verifies the AI picks Hold Person over a weak attack when
the target is a high-DPR low-WIS bruiser.

---

## 2. Decision Pipeline — Step-by-Step Status

The 8-step pipeline from `pillars-reconciliation.md` §7 lives in
`engine/core/pipeline.py`. Status per step:

| Step | Status |
|---|---|
| 0. Resolve effective profile | 🟡 Reads `actor.template.behavior_profile`; archetype defaults via `_ARCHETYPE_DEFAULTS` table. Faction profiles, instance overrides, form transitions, runtime overrides (Frightened/Dominate/Confusion) all deferred. |
| 1. Retreat trigger check | ✅ DMG p48 algorithm via `engine/ai/retreat.py`; 5 presets; mindless override; WIS save; flees telemetry. |
| 2. Generate candidates | ✅ Enumerates `(weapon_attack × enemy)`, `(multiattack)`, `(heal × ally)`, `(defensive_buff × ally)`, `(hard_control × enemy)`. Slot-aware: separate calls for main vs bonus action slots. |
| 3. Apply RP Hard Filters | ✅ Tier 1 set-intersection via `engine/ai/rp_constraints.py`. Empty set logs `passed_turn` event (guaranteed-legal fallback per §6.4). |
| 4. Apply RP Forced Choices | ✅ Pass-through at the pipeline level; the actual score-boost work happens at scoring time per §6.3 score-weight semantics. |
| 5. Score each candidate | ✅ Real offensive + defensive eHP per type, scaled by aggression coefficient, with small tie-break bonuses for dial-preferred picks, then Tier 2 forced-choice boost + Tier 3 weighted preferences applied additively. Single coherent scoring pass per the Utility AI shape. |
| 6. Select max-scoring candidate | ✅ Stable max (first-listed wins ties). |
| 7. Apply Action Economy per slot | ✅ Main-slot optimality roll (downgrade to default attack on miss); bonus slot gated by `signature_bonus_pct` vs `tactical_bonus_pct`. Reactions deferred until positions land. |
| 8. Execute | ✅ Dispatches single actions through their primitive pipeline; multiattack loops per `count` × `sub_actions`. |

---

## 3. eHP Framework — Coverage Map

Per `docs/foundations/ehp-action-framework.md`:

```
Total Action Value = Offensive eHP + Defensive eHP − Opportunity Cost
```

| Component | Status | Module |
|---|---|---|
| Direct damage (offensive) | ✅ `expected_damage × hit_prob`, overkill-capped, crit-fold-in, resistance/vuln/immunity | `engine/ai/ehp_scoring.py` |
| Multiattack (offensive) | ✅ Sums sub-attacks with running overkill cap | `engine/ai/ehp_scoring.py` |
| Direct healing (defensive) | ✅ With desperation multiplier; missing-HP cap | `engine/ai/defensive_ehp.py` |
| Defensive buff (defensive) | ✅ AC bonus + disadvantage-for-attacker shapes | `engine/ai/defensive_ehp.py` |
| Hard control / action denial | ✅ `forced_save → apply_condition` shape recognized | `engine/ai/defensive_ehp.py` |
| Offensive buff (for allies, e.g., Bless) | 🔴 Deferred — math symmetric to defensive buff; needs cross-actor `attack_modifier` lookup at score-time |
| Soft control / movement denial | 🔴 Deferred — needs positions |
| Debuff on enemy saves | 🔴 Deferred |
| Opportunity cost — spell slots | 🔴 Deferred — needs slot tracking on actors |
| Opportunity cost — action economy alternatives | 🔴 Deferred |
| Future-rounds discounting | 🔴 Deferred — flat 2.5-round constant for buffs/control |
| AoE multi-target optimization | 🔴 Deferred — single-target only |
| Concentration management | 🔴 Deferred |
| Behavioral coefficients | 🟡 Only `aggression_coefficient` wired; `self_preservation_coefficient`, `pack_tactics_bonus`, `morale_threshold` deferred |

---

## 4. Primitives — Coverage

13 implemented (executable end-to-end through the runner); ~30 stubbed
(raise `NotImplementedError` if invoked).

**Implemented:**
attack_roll · damage · apply_condition · heal · granted_action ·
attack_modifier · save_modifier · d20_test_modifier · crit_modifier ·
crit_threshold_modifier · forced_save · recurring_save · multiattack

**Stubbed (most-likely-next-needed):** Dodge (would replace the
Pass-turn RP fallback), speed_modifier, damage_modifier,
additional_action (Action Surge), persistent_aura + triggered_save
(Spirit Guardians), slot_recovery_partial (Arcane Recovery),
spellcasting_enable, spell_grant.

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

Goblin Warrior (archetype `cowardly_skirmisher` → targeting preset
`weakest_target`) faces a wounded fighter (5 HP) and a healthy fighter
(28 HP). First attack roll in the event log targets `fighter_wounded`,
not `fighter_healthy`. After the wounded fighter dies, the healthy
fighter (Default retreat preset → 50% ally-disparity trigger) fails
the WIS save and flees.

**What it proves:** archetype → dial defaults → AI exploits the
preset's intent. Retreat dial fires reactively when half the party
falls.

### Example 2 — Cleric heals the dying ally, surviving goblin panics

```
python -m engine.cli encounter tests/fixtures/cleric_heals_ally_encounter.yaml --seed 1
```

2 goblins attacking. Dying Fighter at 1/28 HP. Cleric with mace +
Cure Wounds at full HP. Cleric goes first.

Event log shows the cleric's first action is `healed → fighter_dying
+10`, not a mace swing. Fighter is restored and kills a goblin. The
surviving goblin (cowardly_skirmisher → Cowardly retreat preset →
"1 ally falls" trigger) panics, fails its WIS save, and flees at
full HP.

**What it proves:** the AI compares offensive vs defensive options on
a single eHP scale. Retreat dial picks up "my partner just died"
without any special pack-AI code — falls out of the disparity check.

### Example 3 — Skilled goblin uses both main + bonus action slots

```
python -m engine.cli encounter tests/fixtures/nimble_goblin_encounter.yaml --seed 1
```

Skilled-preset goblin with Scimitar (main slot) + signature Off-hand
Jab (bonus slot, `is_signature: true`). Round 1 event log shows
**two** attack_roll events from the goblin: scimitar (main) hit,
followed by off-hand jab (signature bonus). Both slots fire in one
turn.

**What it proves:** Action Economy dial runs both slots; signature
bonus actions fire at ~95% under Skilled.

### Example 4 — Pacifist Pass-turns instead of attacking

```
python -m engine.cli encounter tests/fixtures/pacifist_encounter.yaml --seed 1
```

Pacifist Monk (rp_constraint: `pacifist_strict`) vs attacking goblin.
The pacifist has only weapon attacks in her template → hard filter
empties the set every turn → `passed_turn → reason:
rp_hard_filter_empty_set` logged each round. **Zero attack_roll
events from the pacifist over 7 rounds.** Eventually her Default
retreat dial fires (Bloodied trigger), and she flees alive at 2/30
HP.

**What it proves:** RP Constraints can completely override the
optimization layer. Hard Filter Tier 1 + guaranteed-legal Pass-turn
fallback work end-to-end through the runner.

### Example 5 — Multiattack still works

```
python -m engine.cli encounter tests/fixtures/test_multiattack_encounter.yaml --seed 1
```

A monster with `multiattack: count 2` correctly loops its sub-attack
pipeline twice per turn, picking new targets if the original dies
mid-multiattack. The PC fighter (Default retreat → 50% Bloodied
trigger) flees at 8/28 HP when she takes enough damage.

---

## 6. Test Surface

```
$ python -m unittest discover -s tests
..................................................................................................
..................................................................................................
Ran 178 tests in 2.9s
OK
```

| Module | Tests | What it covers |
|---|---|---|
| `tests/test_smoke.py` | 4 | End-to-end: skeleton encounter loads, runs, terminates with a winner. |
| `tests/test_primitives_v1.py` | 12 | Attack roll w/ modifiers; condition application + effect instantiation; Q5 modifier query layer; multiattack loop. |
| `tests/test_ai_v1.py` | 19 | All 5 targeting presets; behavior profile resolution; ability selection; finish-off rule; goblin-attacks-wounded-PC integration. |
| `tests/test_ehp_scoring.py` | 34 | dice_mean, hit_probability, crit math; expected damage w/ resistance / vuln / immunity; overkill cap; aggression coefficient; tactical preset highest-EV pick; AI prefers Blinded target. |
| `tests/test_defensive_ehp.py` | 34 | Desperation multiplier; healing eHP; DPR estimation; defensive buff; hard control; candidate generation; cleric-heals-dying-ally full encounter. |
| `tests/test_action_economy.py` | 30 | Preset table correctness; main-slot optimality (Optimal never misses, Reactive_only misses often); bonus-slot gating; slot-aware candidate gen; runner integration (bonus fires + downgrade logging). |
| `tests/test_retreat.py` | 26 | Preset bundle table; mindless override; FtD invariance; bloodied / ally-disparity / frightened triggers; Resolute compound logic; WIS save (Resolute resists, Cowardly often flees); runner integration. |
| `tests/test_rp_constraints.py` | 19 | Library + active-constraint resolution; hard filter intersection + empty-set fallback; forced-choice boost + priority resolution; weighted preference (cumulative additive); pacifist Pass-turn integration; heal_priority forces healing. |

**Fixtures (`tests/fixtures/`):** `smoke_encounter.yaml`,
`two_pc_encounter.yaml`, `test_multiattack_encounter.yaml`,
`cleric_heals_ally_encounter.yaml`, `nimble_goblin_encounter.yaml`,
`pacifist_encounter.yaml`.

---

## 7. Roadmap — Honest Gap List

The engine has the **decision shape** right (Ammann pillar dials +
eHP framework as the scoring spine + RP Constraints as the identity
overlay). All 4 dials and all 8 pipeline steps are wired. Remaining
work is content breadth and depth-within-system. In rough priority
order:

1. **Positioning / movement / reachability** — biggest missing axis.
   Currently all creatures at (0,0); melee reachability defaults to
   TRUE. Unblocks: proper `closest_enemy`, opportunity attacks (which
   activates the already-wired `oa_reaction` AE percentages),
   ranged-vs-melee tradeoffs, soft control / movement denial, AoE
   geometry, several deferred RP constraints (`frontline`,
   `library_protect` proximity).
2. **PC schema** — currently using inline-monster-template hack in PC
   fixtures. A first-class PC schema with class/level/feats/equipment
   slots would clean this up substantially and let us load proper
   classed PCs.
3. **Offensive buff for allies (Bless shape)** — math symmetric to
   defensive buff. Small focused PR.
4. **Spell slot opportunity cost** — needed for proper caster eHP
   scoring. Unlocks the Fireball-vs-Hypnotic-Pattern worked example
   from `ehp-action-framework.md`.
5. **Reactions** — once positioning lands, opportunity attacks
   activate via the already-wired `oa_reaction` AE percentages.
   Sophisticated reactions (Counterspell, Shield) need full trigger
   plumbing on top.
6. **3-level profile inheritance** (archetype → faction → instance) +
   runtime override layer (Frightened / Dominate / Confusion) per
   §4.4.
7. **Concentration management** — auto CON saves on damage when caster
   has active concentration spell; AI decision of whether to break
   current concentration to cast a new spell.
8. **Behavioral coefficients beyond aggression** —
   `self_preservation_coefficient` (scales defensive eHP),
   `pack_tactics_bonus` (coordinates with allies), `morale_threshold`
   (deeper retreat dial modulation).
9. **More primitives** as content demands them — Dodge (replaces
   Pass-turn RP fallback), Action Surge (`additional_action`), Spirit
   Guardians (`persistent_aura` + `triggered_save`), Arcane Recovery
   (`slot_recovery_partial`), spellcasting infrastructure.
10. **Remaining 8 of 12 canonical RP constraints** — recipes in
    `pillars-reconciliation.md` §6.5; ship when fixture demand arises.

---

## 8. Source of Truth Pointers

| For this question | Read this |
|---|---|
| What dial presets exist and what do they mean? | `docs/foundations/pillars-reconciliation.md` §5 |
| What eHP formulas govern action scoring? | `docs/foundations/ehp-action-framework.md` |
| How are RP Constraints structured (3 types, severity, priority)? | `docs/foundations/pillars-reconciliation.md` §6 |
| How does the schema represent monsters / PCs / spells / conditions? | `docs/architecture/schema-design.md` |
| What's the rationale for a specific decision in the AI module? | The module docstrings in `engine/ai/*.py` |
| When was X shipped, with what scope, and what was deferred? | `docs/SESSIONS.md` (chronological) + PR descriptions |
| What's the current snapshot for paste-at-session-start? | `docs/CONTEXT.md` |
