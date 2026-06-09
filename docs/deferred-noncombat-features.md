# Deferred Non-Combat Features → Stage 4 (AI DM)

**Purpose:** The combat simulator only models mechanics that move a sim
signal (DPR, eHP, control, action economy, positioning). Features whose
entire effect is *exploration*, *social*, *ritual utility*, or *narrative*
have **no observable combat effect** and are deliberately shipped as
**markers** (data-layer YAML present, no engine wiring) until the project
reaches the **AI DM stage (Phase 4 — web app + AI DM)**, when a full
ruleset (including non-combat pillars) becomes worth modeling.

**Policy (Phil, 2026-06-09):** When wiring a subclass/class, *full-wire the
combat-relevant choices* and *record every non-combat feature here* as a
Stage-4 marker. Do not delete the marker YAML — it carries the RAW text and
`granted_by` metadata so the AI-DM lane can pick it up without re-research.

When a feature is later wired, move it from "Deferred" to "Wired" below with
the PR / session reference.

---

## Deferred (markers only — wire in Stage 4 / AI DM)

### Barbarian — Path of the Wild Heart
- **f_animal_speaker (L3)** — ritual-cast *Beast Sense* + *Speak with
  Animals*. Pure utility/exploration; no combat signal. Needs the ritual-
  casting + non-combat-spell system (shared with Nature Speaker).
- **f_aspect_of_the_wilds (L6)** — Owl (Darkvision 60 / +60) / Panther
  (Climb Speed = Speed) / Salmon (Swim Speed = Speed). Exploration movement
  + senses. *Owl's darkvision* has a faint combat edge (vision system) but
  the climb/swim speeds are exploration-only; deferred as a unit until the
  exploration-movement + light/vision-economy layer lands.
- **f_nature_speaker (L10)** — ritual-cast *Commune with Nature*. Pure
  exploration/information. No combat signal. Shares the ritual-casting
  system with Animal Speaker.

---

## Wired (combat-relevant — for cross-reference)

### Barbarian — Path of the Wild Heart
- **f_rage_of_the_wilds (L3)** — Bear / Eagle / Wolf rage choices. WIRED
  (combat-relevant: resistance / mobility / team-advantage aura).
- **f_power_of_the_wilds (L14)** — Falcon / Lion / Ram rage choices. WIRED
  (combat-relevant: fly-while-unarmored / enemy-disadvantage aura / on-hit
  Prone on Large-or-smaller). RAW confirmed by Phil 2026-06-09.

---

## Cross-cutting systems Stage 4 will need (gathered as we go)
- **Ritual casting of non-combat spells** (Beast Sense, Speak with Animals,
  Commune with Nature, Detect Magic, etc.) — a "cast outside initiative, no
  slot" path with narrative resolution rather than mechanical effect.
- **Exploration movement modes** (Climb / Swim / Burrow speeds) as
  first-class, beyond the combat-grid Fly already modeled.
- **Senses / light economy** beyond combat vision (passive exploration
  perception, navigation).
