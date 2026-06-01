# Parallel Build Guide — SRD Spell & Monster Content

This guide is for a **second Claude instance** (browser lane) building SRD
content in parallel with the desktop lane. Read this BEFORE building anything.

## Your job

Build SRD spells (and later monsters) as **content that rides existing engine
primitives**. You are composing YAML + thin Python adapters from parts that
already work. You are NOT building new engine systems.

## Source of truth

- **SRD PDF:** `docs/srd/SRD_CC_v5.2.1.pdf` — read the ACTUAL spell text
  for every spell you build. Do NOT rely on training data. The SRD 5.2.1 is
  the PHB 2024 free content; several spells changed from 2014.
- **Sourcing rules:** `docs/data-sources.md` — follow exactly.
- **Spell priority list:** `docs/srd/srd_combat_spells_priority.csv` — work
  from priority 5 down to priority 2. Skip utility spells (separate file).

## Files you OWN (create freely)

- `schema/content/features/f_<spell_name>.yaml` — spell feature definitions
- `schema/content/conditions/co_<condition>.yaml` — new conditions (if needed)
- `schema/content/monsters/` — monster templates (future)
- `tests/test_<spell_name>.py` — per-spell test suites

## Files you must NOT touch

These are owned by the desktop lane to avoid merge conflicts:

- `engine/primitives.py` — all primitive implementations
- `engine/core/runner.py` — turn execution loop
- `engine/core/pipeline.py` — action pipeline
- `engine/core/smite_rider.py` — smite core
- `engine/core/divine_smite.py` — divine smite
- `engine/core/sneak_attack.py` — sneak attack
- `engine/ai/` — all AI scoring
- `schema/content/classes/` — class YAML files (desktop wires new spells)
- Any existing test file you didn't create

**If a spell needs a new primitive or engine change, DON'T build it.**
Instead, add it to `docs/srd/NEEDS_ENGINE_WORK.md` with: spell name,
what it needs, and why existing primitives can't handle it. Desktop lane
will build the primitive, then you build the spell.

## Branching

- Work on branches named `feat/srd-spells-batch-N` (N = 1, 2, 3, ...).
- Each batch = ~5-10 spells that share an archetype.
- Push the branch; do NOT merge to main. Desktop lane merges sequentially.
- Run `python -m pytest -q` and confirm zero regressions before pushing.

## Available primitive archetypes (what you can compose from)

### Attack spells (ranged/melee spell attacks)
```yaml
pipeline:
  - primitive: attack_roll
    params: { kind: ranged, bonus: 5, range_ft: 120 }
  - primitive: damage
    params: { dice: "3d10", modifier: 0, type: fire }
```
Examples: Guiding Bolt, Inflict Wounds, Scorching Ray, Chromatic Orb.

### AoE save-burst spells (forced save + damage)
```yaml
pipeline:
  - primitive: persistent_aura   # OR forced_save for instantaneous
    params:
      shape: sphere
      radius_ft: 20
      range_ft: 150
      trigger_event: target_turn_start_in_area  # persistent
      affected: enemies_only  # or all_creatures_in_area
      save_ability: dexterity
      dc_source: caster_spell_save_dc
      on_fail:
        - primitive: damage
          params: { dice: "8d6", type: fire }
      on_success:
        - primitive: damage
          params: { dice: "8d6", type: fire, half_on_success: true }
```
Examples: Fireball, Lightning Bolt, Cone of Cold, Shatter.

For **instantaneous** AoE (Fireball), use `forced_save` with
`affected: all_creatures_in_area` + `area:` block on the action_template.
For **persistent** AoE (Cloudkill, Stinking Cloud), use `persistent_aura`.

### Save-or-condition spells (forced save + apply condition)
```yaml
pipeline:
  - primitive: forced_save
    params:
      ability: wisdom
      dc_source: caster_spell_save_dc
      affected: all_creatures_in_area
      on_fail:
        - primitive: apply_condition
          params: { condition_id: co_paralyzed, duration: until_spell_ends }
        - primitive: recurring_save
          params:
            ability: wisdom
            dc_source: caster_spell_save_dc
            trigger_event: target_turn_end
            on_success: end_spell_on_target
            condition_id: co_paralyzed
      on_success: []
```
Examples: Hold Person, Hold Monster, Banishment, Fear.

### Healing spells
```yaml
pipeline:
  - primitive: heal
    params: { dice: "2d8", modifier_source: spellcasting_mod }
```
Examples: Cure Wounds (already built), Mass Cure Wounds, Mass Healing Word.

### Self-buff spells (weapon damage bonus)
```yaml
pipeline:
  - primitive: weapon_damage_bonus
    params: { target: self, value: 2, when: weapon_attack,
              lifetime: until_short_rest }
```
Examples: Divine Favor (already built), Magic Weapon, Elemental Weapon.

### Temp HP spells
```yaml
pipeline:
  - primitive: temp_hp_grant
    params: { target: self, amount: 9, amount_per_slot_above_base: 5 }
```
Examples: False Life (already built), Armor of Agathys (already built).

### HP max boost spells
```yaml
pipeline:
  - primitive: hp_max_grant
    params: { target: self, amount: 5, amount_per_slot_above_base: 5 }
```
Examples: Aid (already built).

## YAML template (copy-paste starter)

```yaml
# f_<spell_name> — <Spell Name> (<level>-level <School>, SRD CC v5.2.1)
#
# RAW summary (SRD 5.2.1): <paste the RAW text summary here>
#
# Engine modeling: <describe the primitive pipeline>
#
# source: srd_5.2.1

id: f_<spell_name>
name: <Spell Name>
source: srd_5.2.1
granted_by:
  class: <class_id>
  level: <class_level_that_gains_access>
type: active
spell:
  class: <class_id>
  level: <spell_level>

description: |
  <One-line mechanical description>

action_template:
  id: a_<spell_name>
  name: <Spell Name>
  type: <aoe_attack|weapon_attack|defensive_buff|hard_control|heal>
  spell_slot_level: <level>
  slot: <action|bonus_action|reaction>
  concentration: true  # only if the spell is Concentration
  named_effect: <spell_name>
  range_ft: <range>
  # For AoE spells:
  area:
    shape: <sphere|cube|cone|line>
    radius_ft: <radius>
    range_ft: <range>
  pipeline:
    - primitive: <primitive_name>
      params: { ... }
```

## Test template (copy-paste starter)

Follow the layered test pattern from existing spells. At minimum:
1. YAML loads with correct shape
2. Primitive pipeline fires correctly
3. End-to-end via runner or pipeline.execute

See `tests/test_searing_smite.py` or `tests/test_ensnaring_strike.py`
for the full pattern.

## Conditions

If a spell applies a condition that already exists in
`schema/content/conditions/`, just reference it by id. Existing conditions:

- `co_blinded`, `co_charmed`, `co_deafened`, `co_frightened`
- `co_grappled`, `co_incapacitated`, `co_invisible`
- `co_paralyzed`, `co_petrified`, `co_poisoned`, `co_prone`
- `co_restrained`, `co_stunned`, `co_unconscious`
- `co_ignited` (Searing Smite burn), `co_ensnared` (Ensnaring Strike)

If you need a NEW condition, create `schema/content/conditions/co_<name>.yaml`
following the existing patterns. Conditions with `recurring_damage` or
`recurring_save` effects get special handling in `_instantiate_condition_effects`.

## Class wiring (you DON'T do this)

You create the feature YAML with `granted_by: { class: ..., level: ... }`
but you do NOT edit the class YAML files to wire the spell in. Desktop lane
handles that when merging your branch — they add `f_<spell>` to the class's
level_table features list.

## Provenance

Every feature YAML must have `source: srd_5.2.1`. Read the spell from the
PDF, write the mechanic in your own words. Never copy-paste text from the PDF
into YAML descriptions.

## Commit cadence

Commit after every 2-3 spells (a logical batch). Message format:
```
feat: <Spell1> + <Spell2> + <Spell3> — SRD spell batch N

<one-line per spell describing the archetype used>

Suite: XXXX passed, X skipped, zero regressions.
```
