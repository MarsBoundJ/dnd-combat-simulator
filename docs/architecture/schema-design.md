# Schema Design

**Status:** ✅ v1 — 2026-05-25  
**Authority:** binding on content authoring and on engine implementation of the AI decision layer

This document captures the architectural decisions governing how game content (classes, subclasses, features, monsters, spells, conditions, etc.) is structured in the simulator. It is the companion to `pillars-reconciliation.md` (which governs the AI behavior layer) and `engine-design.md` (which governs the engine's execution model).

See also:
- `docs/CONTEXT.md` — cross-project architecture + firewall + §Config conditions
- `docs/foundations/pillars-reconciliation.md` — BehaviorProfile + dials + RP constraints + form-transition + runtime-override architecture
- `docs/architecture/engine-design.md` — Phase 1 engine architecture
- `docs/foundations/ehp-action-framework.md` — the unified scoring function

---

## 1. Core principle — clean-room mechanical content only

The schema has **no rules-text fields by construction.** Every entity is a structured set of mechanical facts (numbers, dice, triggers, primitive references), not prose. This is the clean-room legal posture enforced at the schema layer — there is nowhere in the shipped schema to put copied or paraphrased WotC text.

Sources for clean-room authoring (per the legal posture in `CONTEXT.md`):
- **SRD CC v5.2.1** — CC-BY-4.0 content, may be quoted verbatim in shipped artifacts with attribution.
- **Non-SRD content** — clean-room reimplementation only: read source for understanding, encode mechanics, never transcribe prose. Bundling non-SRD content commercially is gated by the Hybrid monetization model (see `pillars-reconciliation.md` §1 / `CONTEXT.md` Firewall Rules).

The clean-room two-document split:
- `/schema/worksheets/` (**gitignored**) — private source-reading worksheets. The provenance + own-words paraphrase log. Audit trail.
- `/schema/content/` (committed) — the shipped mechanical definitions. Schema has no prose field.

---

## 2. The unified `ability` pattern

Every executable thing in the game — a weapon attack, a spell, a class feature, a monster action, a magic-item activation — is an **ability**. Abilities share a uniform structure:

```yaml
ability:
  id: <stable_id>
  name: <canonical_name>
  source: <attribution_source>     # srd_5.2.1 / phb_2024 / user_authored / homebrew_<id>
  ability_type: <weapon_attack | spell | class_feature | monster_action | item_activation>
  activation:
    cost:    <action | bonus_action | reaction | free | minutes:N | hours:N>
    trigger?: <event_spec>           # only for reaction-cast / triggered abilities
  resource_cost?: { type, amount }   # spell slot, class resource, charge, daily-use, recharge
  usage?:                             # per-rest / per-day / recharge limits
    uses_per: <short_rest | long_rest | day | turn | recharge:X-Y>
    count: <N>
  range?:    <distance:N | touch | self>
  target?:   { type, count, constraints, area }
  duration?: { type: instantaneous | concentration | timed, max?: ... }
  pipeline:                            # the ordered list of primitives the ability resolves through
    - primitive: <name>
      params: {...}
      when?:    <event_spec>
      contract: { reads, writes, event, scope }
  upcast?:                             # for spells cast at higher level
    scaling: [...]
```

What differs between ability types is their *casting semantics* (resource consumed, when they fire, who can use them) — not their *structural shape*. The engine has one execution pipeline that handles all ability types.

This is the **Q5 unification** locked during cadre red-team of the conditions schema: the engine has one `attack_modifier` primitive, one `damage` primitive, one `save_modifier` primitive, etc. What differs across sources (condition / spell / class feature / magic item) is the modifier's **lifetime**, not the math.

---

## 3. The effect pipeline + event vocabulary

Abilities resolve via an **event-driven pipeline.** The engine emits events in strict order; primitive handlers subscribe to specific events. This is the §Config locked condition #1 (CONTEXT.md) made concrete.

### Attack pipeline events (in firing order)

| Event | Handlers that subscribe here |
|---|---|
| `attack_declared` | Pre-attack triggers (Mage Slayer-style) |
| `attack_roll` | The d20 + modifiers roll |
| `attack_resolved` | Hit/miss/crit determined. **Shield reaction** ("when you would be hit") fires here. |
| `pre_damage_triggers` | **Sneak Attack, Divine Smite, Weapon Mastery (Topple/Cleave/Sap), Hex damage rider** |
| `damage_roll` | Damage dice rolled |
| `damage_modified` | Resistance / vulnerability / immunity applied |
| `damage_dealt` | HP reduction applied. **Hellish Rebuke** ("when you take damage") fires here. |
| `creature_bloodied` | Target crossed 50% HP threshold |
| `creature_dropped` | Target hit 0 HP |
| `on_hit_riders` | Conditions from the attack (prone from Topple, grappled from Grappler) |
| `attack_complete` | Cleanup; cleave looping back |

### Spell pipeline events (additional to attacks)

| Event | Fires when |
|---|---|
| `spell_cast` | Caster begins spell. **Counterspell** subscribes here. |
| `spell_resolve` | Spell's primary effects apply. **Cantrip-resolution modifiers** (Potent Cantrip) subscribe here. |
| `spell_end` | Duration expires or concentration drops |
| `concentration_check` | Caster takes damage; engine-automatic CON save |
| `target_enters_area` / `target_exits_area` | Movement in/out of persistent areas |
| `target_turn_start_in_area` / `target_turn_end_in_area` | Persistent area effects |
| `target_turn_end` | Generic turn-end (for recurring saves) |

### Turn-level events

| Event | Fires when |
|---|---|
| `round_start` | New combat round begins |
| `turn_start` | Actor's turn starts |
| `turn_end` | Actor's turn ends |
| `round_end` | All actors have acted |

---

## 4. The primitive library

Effects compose from a finite library of **primitives** — atomic operations the engine implements once. Content files reference primitives by name with parameters; the engine evaluates them in the pipeline order.

Primitives are organized into categories:

| Category | Examples | Notes |
|---|---|---|
| **Attack pipeline** | `attack_roll`, `damage`, `apply_condition`, `forced_save` | Each subscribes to a specific attack-pipeline event |
| **Modifiers** (unified per Q5) | `attack_modifier`, `save_modifier`, `speed_modifier`, `damage_modifier`, `ability_check_modifier`, `d20_test_modifier`, `crit_modifier` | All carry a `lifetime` parameter — what differs across sources is when the modifier expires, not the math |
| **Healing & state** | `heal`, `temp_hp_grant`, `slot_recovery_partial`, `state_transition` | |
| **Action & turn** | `granted_action`, `additional_action`, `multiattack`, `at_will_spell_grant`, `free_cast_per_rest` | |
| **Condition effects** | `sense_restriction`, `movement_restriction`, `action_restriction`, `condition_immunity_grant`, `damage_resistance_grant` | Used in condition definitions |
| **Persistent / triggered** | `persistent_aura`, `triggered_save`, `recurring_save`, `on_event_effect`, `designate_protected` | |
| **Spellcasting infrastructure** | `spell_grant`, `proficiency_grant`, `ability_score_increase`, `free_spell_to_known_list` | |
| **Special** | `target_swap`, `ignite_objects`, `damage_max`, `self_damage_rider`, `death_save_threshold_modifier` | Sui generis primitives for specific mechanics |

The library grows as content surfaces new patterns. Every primitive has a Python handler in `/schema/primitives/` (engine implementation, deferred to engine-skeleton work — currently stubs only).

### The lifetime parameter on modifier primitives

Every modifier primitive carries a `lifetime` parameter declaring when the modifier expires:

```yaml
lifetime:
  - per_single_attack             # Shield's +5 AC for ONE attack
  - until_actor_next_turn_start   # Shield's actual duration
  - until_condition_ends          # From a condition (Blinded, Paralyzed)
  - until_spell_ends              # From a non-condition spell effect
  - until_dispelled
  - timed:
      duration: { unit: round|minute|hour, value: N }
```

The engine maintains one **active modifier registry** per actor; expirations are driven by registered lifetimes; the math at resolution time is uniform.

---

## 5. Entity types

The v1 schema defines these top-level entity types. Each has a JSON Schema in `/schema/definitions/`.

| Entity | Examples | Schema file |
|---|---|---|
| **Class** | Fighter, Wizard, Cleric | `class.schema.json` |
| **Subclass** | Champion, Evoker | `subclass.schema.json` |
| **Feature** | Second Wind, Improved Critical, Potent Cantrip | `feature.schema.json` |
| **Monster** | Goblin Warrior, Adult Gold Dragon, Lich | `monster.schema.json` |
| **Spell** | Fireball, Hold Person, Spirit Guardians | `spell.schema.json` |
| **Condition** | Blinded, Charmed, Paralyzed | `condition.schema.json` |

Deferred to follow-on PRs (each requires its own sampling pass):

| Entity | Status |
|---|---|
| **Equipment** (weapons, armor, gear) | Not yet sampled. Weapons have Mastery properties (2024 rules); important. |
| **Magic Items** | Not yet sampled. Attunement, charges, sentient items. |
| **Backgrounds** | Not yet sampled. Acolyte / Criminal / Sage / Soldier in SRD. |
| **Species** | Not yet sampled. 9 species in SRD. |
| **Feats** | Not yet sampled. Origin / General / Fighting Style / Epic Boon categories. |

---

## 6. Spellcasting

Classes that cast spells declare a `spellcasting:` block. Key fields:

| Field | Purpose |
|---|---|
| `ability` | Which ability is spellcasting (INT, WIS, CHA) |
| `save_dc_formula` | `8 + actor.<ability>_mod + actor.proficiency_bonus` |
| `attack_mod_formula` | `actor.<ability>_mod + actor.proficiency_bonus` |
| `focus_types` | What counts as a Spellcasting Focus for this class |
| `preparation_model` | `prepared_from_known_list` (Wizard) / `spells_known_fixed` (Sorcerer, Bard, Ranger) / `prepared_from_class_list` (Cleric, Druid, Paladin) / `pact_magic` (Warlock) |
| `slots_progression` | `full_caster` / `half_caster` / `third_caster` / `pact_magic` — references an engine-canonical table |
| `ritual_casting` | Enabled flag + style (`standard` requires prep; `ritual_adept` is the Wizard variant) |

**Spell lists are auto-derived views**, not separate files. Each spell carries `classes:` in its own definition; the Wizard spell list is a query: `WHERE c_wizard IN spell.classes`, grouped by level. No duplication, no drift risk.

**Slot progressions are engine-canonical.** The four tables (full / half / third / pact) live as constants in the engine; classes reference by name. Reduces 12-class duplication; one source of truth.

---

## 7. Conditions — definition vs application

Conditions are first-class entities in `/schema/content/conditions/`. Each condition has:

- **Definition** (immutable rules) — what the condition does, defined once.
- **Application** (per-creature runtime state) — created when the condition is applied; carries source, duration, end_conditions.

A creature's `applied_conditions[]` array tracks active conditions. The engine consults applied_conditions at decision time, applying each condition's effects via the unified modifier primitives.

### Scope: `absolute` vs `source_referencing`

Some conditions have effects that reference their source (`source_referencing`):
- **Charmed** — "can't harm the charmer"
- **Frightened** — "can't move closer to the source of fear"
- **Grappled** — "disadvantage on attacks against any target other than the grappler"

These tracked per-source: Charmed-by-A and Charmed-by-B coexist as distinct applications.

All other conditions are `absolute` — effects don't reference source. Multiple sources of the same absolute condition collapse to one application (with reference counting on source list for ending).

### Subordinate condition inheritance

Some conditions include others (Paralyzed includes Incapacitated; Unconscious includes Incapacitated + Prone). The `inherits_conditions:` field declares this. The engine applies inherited conditions transitively with **reference counting** on sources — ending Paralyzed only ends Incapacitated if no other source maintains it.

---

## 8. The BehaviorProfile (cross-reference)

Monsters carry an inline `behavior_profile:` block per the design in `pillars-reconciliation.md` §3. It specifies:
- `archetype` (from Ammann's framework)
- Four dial presets (Retreat / Ability Selection / Targeting / Action Economy)
- Optional RP constraints

The schema is defined in `pillars-reconciliation.md`, not duplicated here. Monster files reference dial presets by name.

PCs carry the same BehaviorProfile structure but typically authored at encounter setup, not in shipped content.

---

## 9. Authoring workflow

### File naming convention

| Entity type | Prefix | Example |
|---|---|---|
| Class | `c_` | `c_fighter.yaml` |
| Subclass | `sc_` | `sc_champion.yaml` |
| Feature | `f_` | `f_second_wind.yaml` |
| Monster | `m_` | `m_goblin_warrior.yaml` |
| Spell | `sp_` | `sp_fireball.yaml` |
| Condition | `co_` | `co_paralyzed.yaml` |

### YAML authoring + JSON Schema validation

Content is authored in **YAML** (readable, comment-supporting). Files are validated against **JSON Schema** definitions in `/schema/definitions/`. Build tooling (deferred to engine-skeleton work) loads YAML, validates against schemas, and feeds the engine. Authors get fast feedback on schema violations during authoring.

### Clean-room workflow for non-SRD content

When the Hybrid model eventually ships non-SRD content (Stage 3+) or when authoring internal-grading content (Stage 1):

1. **Source capture** — record provenance: source book/UA, version/date, URL. (For SRD content, source is `srd_5.2.1`.)
2. **Clean-room read & restate** — author reads source, writes own-words paraphrase into a private worksheet in `/schema/worksheets/<name>.worksheet.md` (gitignored). This is the audit trail.
3. **Decompose** — identify mechanical effects: which events does each ability hook? What does it read / write?
4. **Encode** — fill the YAML schema: declarative primitives for standard effects; custom handlers (engine-side Python) for novel mechanics.
5. **Register** — add the entity to the appropriate `/schema/content/<type>/` directory.
6. **Validate** — schema check + load smoke test.

For SRD content, the worksheet step is light (the SRD itself is the citable source); for non-SRD it is the load-bearing legal artifact.

---

## 10. Versioning + change protocol

This document and the JSON Schema files are versioned. Changes follow the same protocol as `pillars-reconciliation.md`:

- **Minor edits** (typos, library additions, new primitives without architectural change): standard PR review.
- **Schema changes** (new field, new entity type, primitive contract change): explicit cadre red-team round before merge.
- **Foundational architectural changes** (the unified ability pattern, the event vocabulary, the condition scope model): cross-doc review with pillars-reconciliation.md.

Every change updates the `Status:` date in the header and adds a SESSIONS.md entry.
