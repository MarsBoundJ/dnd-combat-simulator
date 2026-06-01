# Form & Identity System — architecture spec

Status: **design (pre-implementation)**. This is the blueprint for the
agent identity layer that powers Wild Shape, the Polymorph family,
lycanthropes, illusions/disguise, and (later) the AI-DM's creature
lifecycle. Build the system first; the Druid's Wild Shape is its first
consumer.

## Motivation

Every agent (PC / monster / NPC) has a **true identity** but a **current
identity** that can differ along two orthogonal axes:

- **Axis 1 — mechanical form** (which stat block's numbers are live):
  Wild Shape, Polymorph, True Polymorph, Shapechange, lycanthrope hybrid
  forms, a dragon's Change Shape. AC / HP / attacks / abilities / speed /
  size / traits change.
- **Axis 2 — perceived appearance** (what observers believe it is, with
  the *same* stats): Disguise Self, Seeming, Mislead, a doppelganger
  "looking like the noble." No combat math changes until someone acts on
  the false belief.

Conflating the axes is the trap: a polymorphed druid that still *looks*
like a druid (no — Wild Shape changes appearance too) vs. a disguised
spy that fights with its real stats are different combinations. Model
them independently and any combination is expressible.

A third, adjacent concern (AI-DM era, not built now): **agent lifecycle**
— creatures appearing/leaving (summons, reinforcements, a spawned
ambush). It reuses the same "instantiate an agent from a base_form" path;
the model below accommodates it without committing to it.

## Key enabling fact (why this is tractable)

The `Actor` already **denormalizes** its combat stats onto live top-level
fields at construction — `ac`, `hp_current`, `hp_max`, `speed`,
`abilities`, `size`, `creature_type`, senses, `template.actions`. The
engine reads these live fields, **not** `template[...]`, almost
everywhere (only ~7 raw template-reads in the primitives/runner hot
paths). Therefore a form swap does NOT require teaching every call site
to "read the active form." It is:

> **snapshot the live fields → overwrite them per the merge policy →
> restore the snapshot on revert.**

The live Actor IS the active form. `base_form` is a saved snapshot.

## Axis 1 — mechanical form

### Actor additions
- `base_form_snapshot: dict | None` — the saved live-field snapshot taken
  when the FIRST form is pushed (None ⇒ in true form). Captures the
  fields a merge policy may overwrite (abilities, ac, speed, size,
  creature_type, template.actions, attack profile, traits, plus an HP
  record).
- `form_stack: list[FormLayer]` — active forms, innermost first. Empty ⇒
  true form. Top = current. (A stack handles the rare nest; usually ≤1.)
- `form_hp: int | None` + `form_hp_max: int | None` — the current form's
  separate HP pool (Wild Shape / Polymorph). Damage depletes this; at 0
  the form ends and excess carries to the underlying HP.

### `FormLayer`
```
FormLayer = {
  form_id,                 # the assumed creature/template id
  merge_policy,            # see below
  source: {effect, caster_id, named_effect, concentration?},
  reversion: [triggers],   # hp_zero | duration_end | concentration_end
                           # | incapacitated | voluntary
}
```

### Merge policy — where ALL the RAW fidelity lives
A declarative rule for what the assumed form replaces vs. what the base
keeps. Fields:
- `physical: replace|keep`   — STR/DEX/CON, AC, speed, size, natural attacks
- `mental: replace|keep`     — INT/WIS/CHA
- `hp: separate_pool|none`   — new temp HP pool that reverts on 0
- `keep_features: bool`      — class/monster features usable in form
- `can_cast: bool`           — may cast spells while transformed
- `saves: use_better|replace|keep`
- `skills: use_better|replace|keep`
- `keep_appearance: bool`    — does the form change Axis 2 too (usually yes)

Canonical policies:

| Effect | physical | mental | hp | keep_features | can_cast |
|---|---|---|---|---|---|
| **Wild Shape (2024)** | replace | keep | separate_pool | yes | no* |
| **Polymorph** | replace | replace | separate_pool | no | no |
| **True Polymorph** | replace | replace | separate_pool | no | no |
| **Dragon Change Shape** | replace | keep | none (same HP) | varies | yes |
| **Lycanthrope hybrid** | replace(partial) | keep | none | yes | n/a |

*2024 Wild Shape lets some subclass features/cantrips through — modeled
per-subclass later; base Wild Shape = no casting.

### Reversion
Form ends on any declared trigger. On end: pop the layer; if the stack is
now empty, restore `base_form_snapshot`. HP handling per `hp` model:
- `separate_pool`: damage hits `form_hp` first; at ≤0 the form ends and
  any **overflow** damage carries to the underlying `hp_current`
  (Polymorph RAW). Wild Shape: revert at 0, no overflow to the druid.
- `none`: shares the base HP pool (Dragon Change Shape).

### API sketch (engine/core/forms.py)
- `assume_form(actor, form_template, merge_policy, source, state)` —
  snapshot (if first layer), push layer, overwrite live fields per
  policy, set up `form_hp`.
- `revert_form(actor, state, *, reason)` — pop, restore, carry HP.
- `is_transformed(actor) -> bool`, `active_form_id(actor)`.
- Damage routing + reversion-trigger checks hook the existing `_damage`
  + turn/concentration paths (reuse end_concentration + the new
  timed-condition scrub pattern).

## Axis 2 — perceived appearance (observer-relative)

### Actor additions
- `appearance_layers: list[AppearanceLayer]` — presented identity
  overrides (innermost = base true appearance).
- `AppearanceLayer = { appearance_id/descriptor, source, see_through }`
  where `see_through` is the rule by which an observer can pierce it:
  `{ kind: investigation_contest|truesight|action_reveal|automatic,
      dc?: int }`.

### Resolver
- `perceived_as(observer, target, state) -> appearance` — returns what
  `observer` currently believes `target` is. Defaults to the target's
  true/active-form appearance; an active appearance layer overrides it
  unless the observer has pierced it.
- `pierce_check(observer, target, layer, state) -> bool` — runs the
  layer's see_through rule (Investigation vs the caster's spell DC,
  truesight auto-pierce, etc.). Pierced state is per-(observer, target)
  and persists for the encounter.

### Combat-sim scope (v1)
Appearance does **not** change combat math. It feeds: target
identification, "is this a known enemy," ambush/surprise, and (AI-DM)
social/recognition. v1 builds the data + resolver + truesight/auto
piercing; the Investigation-contest + AI use of belief is wired as the
AI-DM layer consumes it.

## D&D effect → axis mapping

| Effect | Axis 1 (form) | Axis 2 (appearance) |
|---|---|---|
| Wild Shape | ✓ replace (keep mental) | ✓ (becomes the beast) |
| Polymorph / True Polymorph | ✓ full replace | ✓ |
| Shapechange | ✓ full replace | ✓ |
| Dragon Change Shape | ✓ (keep mental, same HP) | ✓ |
| Lycanthrope hybrid | ✓ partial | ✓ |
| Disguise Self / Seeming | — | ✓ illusion (Investigation pierces) |
| Mislead (projected double) | — (+ a spawned agent) | ✓ |
| Alter Self | ✓ minor (natural weapons) | ✓ |
| Invisibility | — | ✓ special-case (already `co_invisible`) |
| Doppelganger Change Shape | — (keeps stats) | ✓ |
| Summon/reinforcement (AI-DM) | agent lifecycle | — |

## Phased implementation plan

- **Phase 1 — mechanical form core.** Actor fields + `forms.py`
  (assume/revert + merge_policy + form_hp + reversion) + damage routing +
  tests. First consumers: a generic `polymorph`-style effect, validated
  directly. No content yet.
- **Phase 2 — appearance layer.** `appearance_layers` + `perceived_as` /
  `pierce_check` + truesight/auto piercing + tests. (Investigation
  contest + AI belief deferred to AI-DM.)
- **Phase 3 — Druid.** WIS full-caster chassis (immediately castable) +
  **Wild Shape** riding Phase 1 (Circle of the Land subclass; beast-form
  catalogue references built monsters as forms). Wild Shape's "assume a
  beast you've seen" → pick from the monster bestiary BC is building.
- **Phase 4 — unblock the queue.** Polymorph / True Polymorph /
  Shapechange (spells) + monster Change-Shape/Shapechanger bucket all
  ride Phase 1; Disguise Self / Seeming ride Phase 2.

Note the lovely convergence: Wild Shape's beast forms ARE the monsters
BC is cataloguing — the form system + the bestiary feed each other.

## Open questions for implementation
- Beast-form source: reference monster templates by id (a Wild Shape
  druid "becomes" `m_brown_bear`)? Yes — reuse the bestiary; CR-gates the
  allowed list by druid level.
- Where does `form_hp` live vs `hp_current`? Proposed: keep `hp_current`
  as the underlying pool, add `form_hp` as the active pool; `_damage`
  routes to `form_hp` when transformed. Confirm during Phase 1.
- Concentration: Polymorph requires it; reversion on concentration end
  reuses `end_concentration`'s scrub hook.
