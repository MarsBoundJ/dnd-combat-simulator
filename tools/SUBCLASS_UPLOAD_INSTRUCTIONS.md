# Subclass Bulk Upload — Instructions for Browser Claude

## What You're Doing

Creating YAML files for D&D 2024 PHB subclasses in a combat simulator repo.
Each subclass needs: one `sc_*.yaml` file + one `f_*.yaml` file per feature.

## Repo Layout

```
schema/content/
  classes/c_fighter.yaml        # class definitions (DO NOT MODIFY)
  subclasses/sc_champion.yaml   # subclass files (YOU CREATE THESE)
  features/f_improved_critical.yaml  # feature files (YOU CREATE THESE)
```

Templates are in `tools/subclass_template.yaml` and `tools/feature_template.yaml`.

## Already Done (8 subclasses — skip these)

| Class     | Subclass                    |
|-----------|-----------------------------|
| Barbarian | Path of the Berserker       |
| Barbarian | Path of the Zealot          |
| Bard      | College of Lore             |
| Druid     | Circle of the Land          |
| Fighter   | Champion                    |
| Monk      | Warrior of the Open Hand    |
| Sorcerer  | Draconic Sorcery            |
| Wizard    | Evoker                      |

## Subclass Feature Levels (2024 PHB)

Every subclass MUST have features at exactly these levels:

| Class     | Levels             |
|-----------|--------------------|
| Barbarian | 3, 6, 10, 14      |
| Bard      | 3, 6, 14          |
| Cleric    | 3, 6, 10, 14, 17  |
| Druid     | 3, 6, 10, 14      |
| Fighter   | 3, 7, 10, 15, 18  |
| Monk      | 3, 6, 11, 17      |
| Paladin   | 3, 7, 15, 20      |
| Ranger    | 3, 7, 11, 15      |
| Rogue     | 3, 9, 13, 17      |
| Sorcerer  | 3, 6, 14, 18      |
| Warlock   | 3, 6, 10, 14      |
| Wizard    | 3, 6, 10, 14      |

## The Loop — For Each Subclass

### Step 1: Create `sc_<name>.yaml`

File: `schema/content/subclasses/sc_<snake_case_name>.yaml`

```yaml
# sc_battle_master — Battle Master (Fighter subclass)
# Source: PHB 2024

id: sc_battle_master
name: Battle Master
source: phb_2024
parent_class: c_fighter

archetype_tags:
  behavior_archetype: cunning_tactician
  role: martial_striker           # INTERNAL-EVAL-ONLY per vocabulary firewall
  flavor_tags: [tactical, commanding, precise]

features_by_level:
  - level: 3
    feature_ids: [f_combat_superiority, f_student_of_war]
  - level: 7
    feature_ids: [f_know_your_enemy]
  - level: 10
    feature_ids: [f_improved_combat_superiority]
  - level: 15
    feature_ids: [f_relentless]
  - level: 18
    feature_ids: [f_ultimate_combat_superiority]
```

### Step 2: Create `f_<name>.yaml` for each feature

File: `schema/content/features/f_<snake_case_name>.yaml`

```yaml
# f_combat_superiority — Combat Superiority (Battle Master L3)
# Source: PHB 2024

id: f_combat_superiority
name: Combat Superiority
source: phb_2024
granted_by:
  subclass: sc_battle_master
  level: 3
type: active
```

**Feature type rules:**
- `passive` — always-on buffs (HP boost, AC calc, resistance, damage rider)
- `active` — costs action/BA/reaction, has `action_template` with pipeline
- `triggered` — fires on event automatically (e.g., damage_taken reaction)
- `triggered_choice` — fires on event, actor decides
- `compound` — bundles sub-features (rare)

**For v1, keep features minimal.** Most features just need `id`, `name`,
`source`, `granted_by`, and `type`. Add `effect_primitives` or
`action_template` only for features with obvious mechanical mappings.
Features that need engine code to implement can have `effect_primitives: []`.

### Step 3: Validate

After each class's subclasses are done:

```bash
python tools/validate_subclass.py --class c_fighter
```

After all are done:

```bash
python tools/validate_subclass.py --summary
python tools/validate_subclass.py --all
```

The validator checks:
- All required fields present
- parent_class exists
- Feature files exist for every feature_id
- Feature granted_by.subclass and granted_by.level match
- All 2024 PHB subclass levels covered
- No unexpected levels
- archetype_tags valid

## Archetype Vocabulary

**behavior_archetype** (how AI plays it):
- `berserker_fanatic` — all-in aggression, charge the biggest threat
- `apex_predator` — calculated burst, picks off weak targets
- `cunning_tactician` — control/support, debuffs, positioning
- `primal_guardian` — zone defense, protects allies
- `pack_alpha` — buff allies, lead charges
- `opportunistic_skirmisher` — hit-and-run, exploit openings
- `cautious_defender` — turtle, react, outlast

**role** (internal eval label):
- `striker` / `martial_striker` / `arcane_striker` — damage dealer
- `blaster` — AoE damage
- `controller` — conditions, denial, crowd control
- `healer` — HP restoration
- `tank` — absorb damage, hold position
- `support` — buffs, enablement
- `skirmisher` — mobile damage

## Naming Conventions

- Subclass IDs: `sc_<name>` — e.g., `sc_oath_of_devotion`, `sc_thief`
- Feature IDs: `f_<name>` — e.g., `f_divine_smite`, `f_cunning_action`
- Use snake_case everywhere
- Match D&D Beyond feature names (lowercase, underscored)

## What NOT to Do

- Don't modify class files (`c_*.yaml`)
- Don't modify existing subclass/feature files
- Don't add engine code — just YAML declarations
- Don't invent features not in the 2024 PHB
- Don't skip levels — every subclass level needs at least one feature
