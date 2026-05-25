# Schema

Content schema for the simulator: clean-room mechanical definitions of classes, subclasses, features, monsters, spells, and conditions.

See [`docs/architecture/schema-design.md`](../docs/architecture/schema-design.md) for the full architectural commitments.

## Directory layout

```
schema/
├── definitions/        # JSON Schema files defining the entity types
│   ├── common.schema.json       # shared sub-schemas (effect_primitive, contract, etc.)
│   ├── class.schema.json
│   ├── subclass.schema.json
│   ├── feature.schema.json
│   ├── monster.schema.json
│   ├── spell.schema.json
│   └── condition.schema.json
├── primitives/         # engine handler library — DEFERRED (engine-skeleton PR)
├── content/            # YAML content files — one entity per file
│   ├── classes/        # c_*.yaml
│   ├── subclasses/     # sc_*.yaml
│   ├── features/       # f_*.yaml
│   ├── monsters/       # m_*.yaml
│   ├── spells/         # sp_*.yaml
│   └── conditions/     # co_*.yaml
└── worksheets/         # gitignored — clean-room audit trail
```

## What's in v1

Sample content validating the schemas across every entity type:

| Entity | Files |
|---|---|
| Class | `c_fighter`, `c_wizard` |
| Subclass | `sc_champion`, `sc_evoker` |
| Feature | ~10 features across Fighter / Champion / Wizard / Evoker |
| Monster | `m_goblin_warrior` |
| Spell | `sp_fireball`, `sp_hold_person`, `sp_spirit_guardians` |
| Condition | All 15 SRD conditions |

This is not exhaustive content — it is **schema validation**. Authoring the remaining ~12 classes, ~24 subclasses, ~300 monsters, ~300 spells, plus equipment, magic items, backgrounds, species, and feats is follow-on work.

## File naming

| Prefix | Type |
|---|---|
| `c_` | Class |
| `sc_` | Subclass |
| `f_` | Feature |
| `m_` | Monster |
| `sp_` | Spell |
| `co_` | Condition |

## Content authoring

See [`docs/architecture/schema-design.md`](../docs/architecture/schema-design.md) §9 (Authoring workflow). Summary:

1. **SRD content** (`source: srd_5.2.1`) is CC-BY-4.0. Author from the SRD directly.
2. **Non-SRD content** requires clean-room reimplementation: read source for understanding → own-words paraphrase in a `worksheets/` file (gitignored audit trail) → encode mechanics into YAML schema. Never transcribe prose.
3. **Validate** YAML against the JSON Schema in `definitions/` before committing.

## What the schema does NOT contain

By construction, the schema has **no rules-text fields**. There is nowhere to put copied WotC prose. Content is mechanical facts only:

- Numbers (damage dice, save DCs, ranges)
- Triggers (event subscriptions)
- References (primitive names, other entity IDs)
- Structured options (preset names, archetype tags)

Prose lives in two places:
- The SRD itself (cited via `source: srd_5.2.1`)
- The `worksheets/` clean-room logs (gitignored, private)

Neither flows into shipped artifacts.
