# Engine Capabilities — Checkpoint

**Last updated:** 2026-05-25
**Engine state:** Phase 1, post-PR #8 (defensive eHP merged).
**Test surface:** 103 tests across 4 modules; 4 CLI fixtures.

This document captures what the simulator can actually do today — in
observable behavioral terms, not module inventories. The companion
`pillars-reconciliation.md` defines the *intended* design; this
document describes what's *wired up*.

A reader should be able to answer two questions from this doc alone:
*"What can the AI demonstrate right now?"* and *"What's the next
thing I'd see if I tried X?"*

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
- Fighter then makes a comeback and kills both goblins.

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
| 1. Retreat trigger check | 🔴 Returns None unconditionally. The Retreat dial (DMG p48 algorithm + 3 modes + 5 presets) is not implemented. |
| 2. Generate candidates | ✅ Enumerates `(weapon_attack × enemy)`, `(multiattack)`, `(heal × ally)`, `(defensive_buff × ally)`, `(hard_control × enemy)`. |
| 3. Apply RP Hard Filters | 🔴 Returns input unchanged. No filters in fixtures yet. |
| 4. Apply RP Forced Choices | 🔴 Returns input unchanged. |
| 5. Score each candidate | ✅ Real offensive + defensive eHP scoring per type, scaled by aggression coefficient, with small tie-break bonuses for dial-preferred picks. Weighted preferences + behavioral coefficients beyond aggression deferred. |
| 6. Select max-scoring candidate | ✅ Stable max (first-listed wins ties). |
| 7. Apply Action Economy per slot | 🔴 No-op — always uses the chosen action. The per-slot stochastic between optimal vs default (signature_bonus / tactical_bonus / OA reaction / sophisticated reaction tiering per §5.4) is not implemented. |
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

**Stubbed (most-likely-next-needed):** speed_modifier, damage_modifier,
additional_action (Action Surge), persistent_aura + triggered_save
(Spirit Guardians), slot_recovery_partial (Arcane Recovery),
spellcasting_enable, spell_grant.

Condition definitions for all 15 SRD conditions exist in
`schema/content/conditions/` and feed the modifier registry at
application time.

---

## 5. Worked Behavioral Examples

Each is a deterministic CLI demo (seeded) you can re-run.

### Example 1 — Goblin bullies the wounded PC

```
python -m engine.cli encounter tests/fixtures/two_pc_encounter.yaml --seed 99
```

Goblin Warrior (archetype `cowardly_skirmisher` → targeting preset
`weakest_target`) faces a wounded fighter (5 HP) and a healthy fighter
(28 HP). First attack roll in the event log targets `fighter_wounded`,
not `fighter_healthy`.

**What it proves:** archetype → dial defaults → AI exploits the
preset's intent. The skeleton's "attack nearest" behavior is gone.

### Example 2 — Cleric heals the dying ally

```
python -m engine.cli encounter tests/fixtures/cleric_heals_ally_encounter.yaml --seed 1
```

2 goblins attacking. Dying Fighter at 1/28 HP. Cleric with mace +
Cure Wounds at full HP. Cleric goes first.

Event log shows the cleric's first action is `healed → fighter_dying
+10`, not a mace swing. Fighter is restored to fighting condition and
kills both goblins.

**What it proves:** the AI compares offensive vs defensive options on
a single eHP scale. The desperation multiplier (1.5 at 0 HP) makes
healing a dying ally worth ~7× more than poking a goblin with a mace.

### Example 3 — Multiattack still works

```
python -m engine.cli encounter tests/fixtures/test_multiattack_encounter.yaml --seed 1
```

A monster with `multiattack: count 2` correctly loops its sub-attack
pipeline twice per turn, picking new targets if the original dies
mid-multiattack.

---

## 6. Test Surface

```
$ python -m unittest discover -s tests
......................................................................................................
Ran 103 tests in 3.5s
OK
```

| Module | Tests | What it covers |
|---|---|---|
| `tests/test_smoke.py` | 4 | End-to-end: skeleton encounter loads, runs, terminates with a winner. |
| `tests/test_primitives_v1.py` | 12 | Attack roll w/ modifiers; condition application + effect instantiation; Q5 modifier query layer; multiattack loop. |
| `tests/test_ai_v1.py` | 19 | All 5 targeting presets; behavior profile resolution; ability selection; finish-off rule; goblin-attacks-wounded-PC integration. |
| `tests/test_ehp_scoring.py` | 34 | dice_mean, hit_probability, crit math; expected damage w/ resistance / vuln / immunity; overkill cap; aggression coefficient; tactical preset highest-EV pick; AI prefers Blinded target. |
| `tests/test_defensive_ehp.py` | 34 | Desperation multiplier; healing eHP; DPR estimation; defensive buff; hard control; candidate generation; cleric-heals-dying-ally full encounter. |

**Fixtures (`tests/fixtures/`):** `smoke_encounter.yaml`,
`two_pc_encounter.yaml`, `test_multiattack_encounter.yaml`,
`cleric_heals_ally_encounter.yaml`.

---

## 7. Roadmap — Honest Gap List

The engine has the **decision shape** right (Ammann pillar dials +
eHP framework as the scoring spine). Several big systems are stubbed
or partially-wired. In rough priority order:

1. **Action Economy dial** — per-slot stochastic between optimal-vs-default
   (signature_bonus / tactical_bonus / OA reaction / sophisticated
   reaction tiering per §5.4). Unlocks reactive-tier reaction handling
   and the "75/40/40" archetype patterns. Self-contained to
   `engine/ai/action_economy.py` + a small extension to step 7.
2. **Retreat dial** — DMG p48 algorithm + 3 modes + 5 presets per
   §5.1. The `cowardly_skirmisher` archetype already declares
   `retreat: cowardly` but it's a no-op. Self-contained to step 1.
3. **RP Constraints** — Hard Filter / Forced Choice / Weighted
   Preference per §6. Currently steps 3 + 4 are no-ops. Unlocks
   creatures with relational constraints (won't attack a specific PC,
   must protect another creature, etc.).
4. **Offensive buff for allies (Bless shape)** — math symmetric to
   defensive buff. Needs cross-actor `attack_modifier` query at
   score-time. Small PR.
5. **Spell slot opportunity cost** — needed for proper caster eHP
   scoring. Unlocks the Fireball-vs-Hypnotic-Pattern worked example.
6. **Positioning / movement / reachability** — the biggest missing
   axis. Currently all creatures at (0,0); melee reachability defaults
   to TRUE. Unblocks proper `closest_enemy`, opportunity attacks,
   ranged-vs-melee tradeoffs, soft control, and area-of-effect
   geometry.
7. **3-level profile inheritance** (archetype → faction → instance) +
   runtime override layer (Frightened / Dominate / Confusion) per §4.4.
8. **Concentration management** — auto CON saves on damage when caster
   has active concentration spell; AI decision of whether to break
   current concentration to cast a new spell.
9. **PC schema** — currently using inline monster-template hack in PC
   fixtures. A first-class PC schema with class/level/feats/equipment
   slots would clean this up substantially.
10. **More primitives** as content demands them — see "Primitives —
    Coverage" §4 above.

---

## 8. Source of Truth Pointers

| For this question | Read this |
|---|---|
| What dial presets exist and what do they mean? | `docs/foundations/pillars-reconciliation.md` §5 |
| What eHP formulas govern action scoring? | `docs/foundations/ehp-action-framework.md` |
| How does the schema represent monsters / PCs / spells / conditions? | `docs/architecture/schema-design.md` |
| What's the rationale for a specific decision in the AI module? | The module docstrings in `engine/ai/*.py` |
| When was X shipped, with what scope, and what was deferred? | `docs/SESSIONS.md` (chronological) + PR descriptions |
| What's the current snapshot for paste-at-session-start? | `docs/CONTEXT.md` |
