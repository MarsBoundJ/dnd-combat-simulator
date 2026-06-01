# Agent Identity & Lifecycle — architecture spec

Status: **design (pre-implementation)**. The blueprint for *what agents
exist in an encounter, what each one currently is, and how they enter
and leave* — powering Wild Shape, the Polymorph family, illusions/
disguise, decoy/echo mechanics, and summoning. Build the system first;
the Druid's Wild Shape is the first consumer, but the same substrate
serves the rest.

## The four concepts

An agent (PC / monster / NPC) has a **true identity**, but what it
currently *is*, *looks like*, and *whether it's even a standalone
creature* can all differ. Four distinct concepts — keep them separate
and any combination is expressible:

1. **Mechanical form** (Axis 1) — which stat block's numbers are live:
   Wild Shape, Polymorph, True Polymorph, Shapechange, lycanthrope
   forms, a dragon's Change Shape. AC / HP / attacks / abilities / speed
   / size / traits change.
2. **Perceived appearance** (Axis 2) — what observers believe it is,
   with the *same* stats: Disguise Self, Seeming, doppelganger "looking
   like the noble." No combat math changes until someone acts on the
   false belief.
3. **Proxy / decoy entities** (Concept 3) — controller-linked secondary
   entities ranging from a non-targetable illusory marker to a
   targetable avatar the controller acts through: Mirror Image, Trickery
   Cleric's Invoke Duplicity, Echo Knight's echo.
4. **Summoned / spawned agents** (Concept 4) — independent new creatures
   brought into the encounter mid-combat: conjure/summon spells, monster
   "call adds" abilities, DM reinforcements.

### The unifying substrate
Concepts 1, 3, and 4 all rest on one shared capability the engine lacks
today: **instantiate an Actor from a template/form and give it a
lifecycle inside a live encounter** (enter → act → leave). Form *becomes*
a template in place; a proxy is a controller-linked instantiation with
special targetability + action-origin; a summon is an independent
instantiation added to initiative. The two engine prerequisites they
share:
- **Actor instantiation from a template** mid-combat (not just at
  encounter setup).
- **Dynamic encounter membership** — the runner must add/remove actors
  from `turn_order` mid-combat and re-resolve initiative. Today
  `turn_order` is fixed at start; this is the single biggest new runner
  capability the whole family needs.

Concept 2 (appearance) is the odd one out — it changes *belief*, not the
roster or the stats — and is modeled independently (below).

(Original "agent lifecycle, forward-looking" note, now promoted to
Concept 4:) creatures appearing/leaving reuse the same "instantiate an
agent from a base_form" path;
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

## Concept 3 — Proxy / decoy entities

Controller-linked secondary entities. They span a spectrum from a
non-targetable buff-marker to a targetable avatar the controller acts
through. Model one lightweight entity with flags rather than three
bespoke mechanics:

```
ProxyEntity = {
  controller_id,
  position,
  targetable: bool,        # can an attack/effect target it?
  occupies_space: bool,    # does it block / count for flanking-ish?
  hp: int | None,          # None = intangible (Invoke Duplicity); 1 = Echo
  condition_immune: bool,
  act_from: bool,          # may the controller's attacks/spells originate
                           #   from this position?
  ends_on: [incapacitated, dismissed, duration_end, hp_zero, controller_*],
}
```

Mapped:
| Mechanic | targetable | hp | act_from | extra |
|---|---|---|---|---|
| **Invoke Duplicity** (Trickery Cleric) | no (intangible) | — | cast-from | Distract = advantage vs creatures near it; L6 teleport-swap; L17 ally-advantage + heal-on-end |
| **Echo Knight echo** (non-SRD) | yes (AC 14+PB, 1 HP, cond-immune) | 1 | attack + OA from | teleport-swap; Shadow Martyr intercept; Legion of One = two echoes |
| **Mirror Image** | (special — see below) | — | — | not a positioned entity; an interception pool |

**Reusable mechanics Concept 3 needs:**
- **Action-origin override** — the controller's attack/spell originates
  from the proxy's space (Echo attacks, Invoke Duplicity casting).
- **Teleport-swap** — controller ↔ proxy position swap (rides the
  teleport/positional system already in the queue).
- **Positional advantage aura** — advantage vs creatures adjacent to the
  proxy (Invoke Duplicity Distract); rides a persistent_aura-shaped
  positional effect.

### Mirror Image is the special case — an interception pool, not an entity
Mirror Image is NOT a positioned entity. It's a **depleting miss-chance
counter** on the caster: while N images remain, an attack that would hit
rolls d6/image and on any 3+ is absorbed (hit → miss) and one image is
destroyed; ends at 0 images. It rides the **existing
`attack_roll_pending` hook** (where Shield bumps AC and the Bard's
Cutting Words fire) — a `mirror_image_remaining` counter + a check that
converts hit→miss and decrements. The Blinded/Blindsight/Truesight
clause is an attacker-sense bypass (senses already on the Actor). This
makes Mirror Image **cheap and buildable without the rest of Concept 3.**

### Cross-cutting: attack redirection / interception
A recurring pattern across mechanics: *an incoming attack may be absorbed
or rerouted.* One `attack_roll_pending`-style hook serves all of them:
- **Mirror Image** — probabilistic self-absorb (above).
- **Goblin Boss "Redirect Attack"** (queued) — swap places with an ally,
  who becomes the target.
- **Echo "Shadow Martyr"** — reaction, reroute an attack to the echo.
- **Sanctuary** (queued) — attacker must save or pick a new target.
Build the redirection hook once; these become thin configs over it.

## Concept 4 — Summoned / spawned agents

Summoning is a first-class part of the game (PC conjure/summon spells,
monster "call adds," DM reinforcements) and the original spec
under-specified it. A summon is an **independent new agent (or several)
instantiated mid-combat**, allied to (and often commanded by) the
summoner, that takes turns, can be targeted/killed, and leaves when the
spell ends.

What it needs (most of it is the unifying substrate above):
- **Instantiation from a template** — spawn Actor(s) from a monster/beast
  template at positions near the summoner. (Same instantiation Wild Shape
  uses to *become* a template; here it creates *separate* agents.)
- **Dynamic encounter membership** — add the spawn(s) to
  `encounter.actors` + `turn_order` and resolve their initiative
  mid-combat; remove on death/dismissal/spell-end. (The shared runner
  gap.)
- **Initiative-insertion policy** — per the 2024 rules a summoned
  creature usually takes its turn immediately after the summoner (or acts
  on the summoner's turn). Model a policy field rather than hard-coding.
- **Control / AI** — the spawn is party-side, AI-driven via a behavior
  profile; "obeys your commands" → for the sim it just acts to the
  party's benefit.
- **Lifecycle / teardown** — ends on duration/Concentration end, death,
  or dismissal; removal scrubs it from the roster + turn order (reuse the
  concentration-end + timed scrub hooks).

**2024 RAW note (important for content):** several conjure spells were
redesigned and DON'T spawn individual creatures anymore:
- **Conjure Animals / Conjure Minor Elementals / Conjure Woodland Beings**
  (2024) are now **emanations / persistent auras** centered on the caster
  — they ride the *existing* `persistent_aura` system, NOT Concept 4.
- The **"Summon X"** line (Summon Beast/Fey/Undead/etc.) spawns **one**
  scaling stat block — the canonical Concept 4 case (one instantiation,
  scales with slot).
- Older multi-creature conjures + monster "call adds" (e.g. Wraith's
  Create Specter) spawn **N independent agents** — full Concept 4.
So triage matters: some "summoning" is already buildable as an aura;
true agent-spawning needs Concept 4's dynamic membership.

### Confidence assessment
The original spec was **not** confident here — it had a one-line gesture.
With Concept 4 made explicit, summoning's crux is clear and shared with
proxies: **dynamic encounter membership in the runner**. That single
capability (add/remove actors + re-resolve initiative mid-combat) is the
keystone for Concepts 3 and 4 both, and is the right first build when we
tackle this family beyond Phase 1.

## D&D effect → concept mapping

| Effect | 1 form | 2 appearance | 3 proxy | 4 summon |
|---|---|---|---|---|
| Wild Shape | ✓ replace (keep mental) | ✓ | — | — |
| Polymorph / True Polymorph | ✓ full replace | ✓ | — | — |
| Shapechange | ✓ full replace | ✓ | — | — |
| Dragon Change Shape | ✓ (keep mental, same HP) | ✓ | — | — |
| Lycanthrope hybrid | ✓ partial | ✓ | — | — |
| Disguise Self / Seeming | — | ✓ (Investigation pierces) | — | — |
| Alter Self | ✓ minor | ✓ | — | — |
| Invisibility | — | ✓ (already `co_invisible`) | — | — |
| Doppelganger Change Shape | — (keeps stats) | ✓ | — | — |
| Mirror Image | — | — | ✓ (interception pool) | — |
| Invoke Duplicity (Trickery) | — | — | ✓ intangible marker | — |
| Echo Knight echo (non-SRD) | — | — | ✓ targetable avatar | — |
| Mislead | — | ✓ | ✓ (the double) | — |
| "Summon X" spells (2024) | — | — | — | ✓ one scaling block |
| Conjure Animals etc. (2024) | — | — | — | aura (persistent_aura, not C4) |
| Monster "call adds" (Wraith) | — | — | — | ✓ N agents |

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
- **Phase 4 — unblock the form/appearance queue.** Polymorph / True
  Polymorph / Shapechange (spells) + monster Change-Shape/Shapechanger
  bucket ride Phase 1; Disguise Self / Seeming ride Phase 2.
- **Phase 5 — attack redirection/interception.** The
  `attack_roll_pending` redirection hook → **Mirror Image** (cheap; the
  earliest C3 win), Goblin Boss Redirect, Sanctuary, Echo Shadow Martyr.
  Independent of dynamic membership — can land early.
- **Phase 6 — dynamic encounter membership** (the keystone for C3 + C4):
  Actor instantiation mid-combat + add/remove from `turn_order` +
  initiative insertion + teardown. Validated with a simple test spawn.
- **Phase 7 — summoning + proxies on top of Phase 6.** "Summon X" spells
  + monster call-adds (C4); Invoke Duplicity + Echo-style avatars (C3,
  with action-origin override + teleport-swap). 2024 aura-style conjures
  ride the existing persistent_aura instead.

Note the lovely convergence: Wild Shape's beast forms ARE the monsters
BC is cataloguing, and summoned creatures spawn from those same templates
— the form system, the bestiary, and the summon system all feed each
other.

## Open questions for implementation
- Beast-form source: reference monster templates by id (a Wild Shape
  druid "becomes" `m_brown_bear`)? Yes — reuse the bestiary; CR-gates the
  allowed list by druid level.
- Where does `form_hp` live vs `hp_current`? Proposed: keep `hp_current`
  as the underlying pool, add `form_hp` as the active pool; `_damage`
  routes to `form_hp` when transformed. Confirm during Phase 1.
- Concentration: Polymorph requires it; reversion on concentration end
  reuses `end_concentration`'s scrub hook.
- Dynamic membership (Phase 6): does adding an actor mid-combat re-sort
  the whole initiative, or insert at a policy slot (e.g. right after the
  summoner)? Proposed: insert-after-summoner by default, with a per-
  effect policy override. Confirm when Phase 6 is scoped.
- Summon AI: a spawned ally uses a behavior profile like any actor;
  "obeys commands" is approximated as party-beneficial play. Master-
  controlled targeting (the summoner dictating) is an AI-DM refinement.
- Proxy targetability + AI: do enemies "waste" attacks on a targetable
  Echo (1 HP)? Yes — that's the point of the decoy; the enemy targeter
  should treat it as a valid (low-value) target. Tuning is AI-lane.
