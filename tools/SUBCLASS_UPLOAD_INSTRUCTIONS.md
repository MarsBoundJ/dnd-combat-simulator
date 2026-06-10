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

## Already Done (skip these entirely)

All 4 Barbarian subclasses and all 4 Bard subclasses are complete:

| Class     | Subclass                    |
|-----------|-----------------------------|
| Barbarian | Path of the Berserker       |
| Barbarian | Path of the Zealot          |
| Barbarian | Path of the World Tree      |
| Barbarian | Path of Wild Heart          |
| Bard      | College of Lore             |
| Bard      | College of Dance            |
| Bard      | College of Glamour          |
| Bard      | College of Valor            |

Plus these individual subclasses from other classes:

| Class    | Subclass                    |
|----------|-----------------------------|
| Druid    | Circle of the Land          |
| Fighter  | Champion                    |
| Monk     | Warrior of the Open Hand    |
| Sorcerer | Draconic Sorcery            |
| Wizard   | Evoker                      |

## Subclass Feature Levels (2024 PHB)

Subclass features vary by class. The number of features at level 3 varies
by subclass — some get 1, others get 2 or 3 plus a spell list. Later levels
always get exactly 1 feature each.

### Cleric — subclass features at levels 3, 6, 17

Level 3 grants **2 features + a Domain Spell list** (3 feature files total).
Example: Life Domain gets Disciple of Life, Life Domain Spells, Preserve Life.

| Level | Feature count | Notes                              |
|-------|---------------|-------------------------------------|
| 3     | 2-3 + spells  | Two features plus Domain Spell list |
| 6     | 1             |                                     |
| 17    | 1             |                                     |

### Druid — subclass features at levels 3, 6, 10, 14

Level 3 grants **1 feature + Subclass Spells**.
Example: Circle of the Moon gets Circle Forms + Circle of the Moon Spells.

| Level | Feature count | Notes                         |
|-------|---------------|-------------------------------|
| 3     | 1 + spells    | One feature plus spell list   |
| 6     | 1             |                               |
| 10    | 1             |                               |
| 14    | 1             |                               |

### Fighter — subclass features at levels 3, 7, 10, 15, 18

Level 3 grants **2 features**.

| Level | Feature count | Notes        |
|-------|---------------|--------------|
| 3     | 2             | Two features |
| 7     | 1             |              |
| 10    | 1             |              |
| 15    | 1             |              |
| 18    | 1             |              |

### Monk — subclass features at levels 3, 6, 11, 17

Level 3 feature count varies: Open Hand gets 1, Shadow gets 1, Elements
gets 2, Mercy gets 3.

| Level | Feature count | Notes                          |
|-------|---------------|--------------------------------|
| 3     | 1-3           | Varies by subclass (see above) |
| 6     | 1             |                                |
| 11    | 1             |                                |
| 17    | 1             |                                |

### Paladin — subclass features at levels 3, 7, 15, 20

Level 3 feature count varies: Devotion gets 2, Glory gets 3, Ancients
gets 2, Vengeance gets 2. All include Oath Spells.

| Level | Feature count  | Notes                               |
|-------|----------------|-------------------------------------|
| 3     | 2-3 + spells   | Varies by subclass; includes spells |
| 7     | 1              |                                     |
| 15    | 1              |                                     |
| 20    | 1              |                                     |

### Ranger — subclass features at levels 3, 7, 11, 15

Level 3 feature count varies: Beast Master gets 1, Fey Wanderer gets 3,
Gloom Stalker gets 3, Hunter gets 2.

| Level | Feature count | Notes                          |
|-------|---------------|--------------------------------|
| 3     | 1-3           | Varies by subclass (see above) |
| 7     | 1             |                                |
| 11    | 1             |                                |
| 15    | 1             |                                |

### Rogue — subclass features at levels 3, 9, 13, 17

Level 3 grants **2 features**.

| Level | Feature count | Notes        |
|-------|---------------|--------------|
| 3     | 2             | Two features |
| 9     | 1             |              |
| 13    | 1             |              |
| 17    | 1             |              |

### Sorcerer — subclass features at levels 3, 6, 14, 18

Level 3 grants **2 features**.

| Level | Feature count | Notes        |
|-------|---------------|--------------|
| 3     | 2             | Two features |
| 6     | 1             |              |
| 14    | 1             |              |
| 18    | 1             |              |

### Warlock — subclass features at levels 3, 6, 10, 14

Level 3 grants **2 features** (Great Old One gets 3).
Level 10: Great Old One gets 2 features; others get 1.

| Level | Feature count | Notes                               |
|-------|---------------|-------------------------------------|
| 3     | 2-3           | GOO gets 3; others get 2            |
| 6     | 1             |                                     |
| 10    | 1-2           | GOO gets 2; others get 1            |
| 14    | 1             |                                     |

### Wizard — subclass features at levels 3, 6, 10, 14

Level 3 grants **2 features**.

| Level | Feature count | Notes        |
|-------|---------------|--------------|
| 3     | 2             | Two features |
| 6     | 1             |              |
| 10    | 1             |              |
| 14    | 1             |              |

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

**Domain/Subclass Spell lists** are a feature too. Create a feature file
with type `passive` for each spell list (e.g., `f_life_domain_spells`).

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
- Spell list features: `f_<subclass>_spells` — e.g., `f_life_domain_spells`
- Use snake_case everywhere
- Match D&D Beyond feature names (lowercase, underscored)

## What NOT to Do

- Don't modify class files (`c_*.yaml`)
- Don't modify existing subclass/feature files
- Don't add engine code — just YAML declarations
- Don't invent features not in the 2024 PHB
- Don't skip levels — every subclass level needs at least one feature
- Don't assume every subclass gets the same number of L3 features — check D&D Beyond
