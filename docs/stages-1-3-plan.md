# Stages 1–3 Plan — Complete PCs → Customization & Environments → Public Sim

**Status:** DRAFT for red-team review (companion: `docs/stages-1-3-redteam-brief.md`)
**Date:** 2026-06-11
**Input:** Phil's phase briefing (2026-06-11) — pause monster ingestion, complete
PC profiles, multiclassing, creation UI, import, environments, Foundry,
archive DB, public stage. Stage 4 (AI DM) explicitly out of scope, but
**Stage-4 data stubs are captured as we go** (see §3.8).
**Companions:** `docs/phase-3-plan.md` (complete), `docs/stocktake-2026-06-02.md`,
`sims/FINDINGS.md`, `docs/sim-modes.md`, `docs/data-sources.md`,
`docs/architecture/browser-deployment.md`, `docs/positioning-model.md`.

---

## 1. Where we actually are (baseline inventory, 2026-06-11)

What exists (verified against the repo, not the stale README):

| Area | State |
|---|---|
| Engine | Full 8-step decision pipeline, 4 dials, RP constraints, positioning v1 (defense-weighted), walls + line-of-effect + zones + vision, all 3 AoE shapes + cube, concentration, spell slots, reactions (OA/Shield/Counterspell), death saves (PCs dying/stable, monsters die at 0), short/long rests, multi-encounter session runner, ~3,260 tests |
| Classes | All 12 PHB-2024 classes; spell lists wired per class (Phase 3A–C complete); slot tables live |
| Subclasses | 13 built (all 4 Barbarian, Champion, Evoker, 3 Bard colleges +Dance, Circle of the Land, Draconic Sorcery, Open Hand) |
| Spells | 168 built / 391 tracked (`docs/spell-master-list.csv`); 221 todo |
| Monsters | 261 built (SRD majority + MM-2024 CR ≤4 batch); **ingestion now PAUSED** per briefing; 76/261 carry habitat/treasure Stage-4 stubs |
| Species | 4 SRD (`races/r_*.yaml`) — Dwarf, Elf, Halfling, Human |
| PC spec | `pc:` compact spec: class/level/abilities/armor/weapons/fighting style/off-hand/masteries/subclass/race/skills/expertise/metamagic/invocations |
| Foundry | One-way export serializer only (`engine/core/foundry_export.py`, walls/templates built Foundry-shaped by design). No module, no import |
| Sims/logging | Event log (20+ typed events, JSON-serializable), `sims/*.py` Monte Carlo scripts → stdout/JSON files. **No persistence/DB** |
| Deployment | Pure-Python (PyYAML + jsonschema only) → Pyodide-compatible; **no web UI, no server, no Pyodide build yet** |

What does **not** exist (the gap this plan closes):

| Missing | Briefing item |
|---|---|
| Backgrounds (0), feats (0), equipment library (0), magic items & potions (0) | §1 + Phil's addendum |
| Character creation rules (ability gen, origin application, starting equipment/gold, level-up) | §1 |
| Spell *selection* (prepared/known subsets — today a PC gets every wired class spell) | §1 (implied) |
| Multiclassing (scaffolded only); Warlock pact slots exist but recover on long rest (v1 simplification) | §2 |
| Builder UI, import (DDB PDF / Foundry JSON / manual) | §3, §4, §10 |
| Environment templates as *data* (spec exists; hazards/traps/difficult terrain/cover derivation unimplemented), room generator, Foundry map import | §5 |
| Foundry module (replay or live) | §6 |
| Simulation archive DB + per-run metric buckets | §7 |
| Public site, client-side compute, consented telemetry | §8 |
| PC decision-layer calibration (nova pacing inverted; positioning defense-only; LR sequencing absent) | **not in briefing — added, see §3.4** |

---

## 2. Stage definitions and exit gates

The briefing's "Stages 1–3" mapped to concrete scopes. (Older docs'
"Phase 1–4" / "Stage 1–4" vocabularies are superseded by this table for
forward planning.)

### Stage 1 — Complete the PC (engine + data; CLI-driven)
Backgrounds, species, feats, equipment, magic items & potions, creation
rules, spell selection, multiclassing (incl. Pact Magic), PCSpec v2, and
the PC decision-layer upgrades that make a custom build *play* like its
build. Workstreams A, B, C.

**Exit gate:** any legal 2024 PHB single- or multi-class PC L1–20 can be
declared in PCSpec v2 (with feats, background, species, equipment, magic
items, chosen spells) and simulated; golden-build validation (§WS-C5)
passes; multiclass oracle suite green.

### Stage 2 — Customization & environments (private product surfaces)
Builder UI + import + PC library; RoomSpec environments (hazards, traps,
cover, terrain, generator presets); Foundry scene import + replay module;
local simulation archive + metric buckets + analysis. Workstreams D, E,
F(local), G1–G3.

**Exit gate:** Phil can build or import a PC in the UI, pick/import a
room, run a Monte Carlo batch locally, watch a replay in Foundry, and
query the archive for the results.

### Stage 3 — Public-facing (compute on the user's machine)
Pyodide build of the engine inside the same static UI; SRD-only public
content bundle + user-port for non-SRD; consented telemetry to a central
ingest DB; counsel checkpoint. Workstreams H, F5, G4+ as follow-on.

**Exit gate (= MVP):** a stranger can open the site, build/import a 2024
PC, pick a room and monsters, run simulations entirely client-side, see
results + a 2D replay, and (with explicit consent) contribute their run
records to the central dataset.

---

## 3. Keystone architecture decisions (new in this plan)

### 3.1 PCSpec v2 is the lingua franca
One schema-validated, versioned PC spec that **every** surface emits or
consumes: builder UI, all importers, CLI fixtures, archive records, and
(later) Foundry. The UI is a thin editor over the file format (existing
decision #12); importers are translators *into* it; the archive stores
it verbatim for reproducibility. Sketch (back-compat: `class:`+`level:`
remains sugar for a single-entry `classes:` list):

```yaml
pc:
  classes:                      # first entry = first class taken (RAW: saves, heavy armor, L1 hit die)
    - { class: c_paladin, level: 2 }
    - { class: c_warlock, level: 5, subclass: sc_fiend }
  species: r_human
  background: bg_soldier
  ability_scores: { str: 16, dex: 10, con: 14, int: 8, wis: 10, cha: 16 }
  ability_method: point_buy     # point_buy | standard_array | manual (validator per method)
  feats: [ft_savage_attacker, ft_great_weapon_master]   # origin feat auto-granted by background
  equipment: { armor: eq_chain_mail, shield: true, weapons: [eq_longsword, eq_javelin] }
  magic_items: [mi_ring_of_protection, mi_potion_of_healing_greater]
  attuned: [mi_ring_of_protection]                       # cap 3, validated
  spells: { cantrips: [...], prepared: [...] }           # validated vs class lists + counts
  level_up: { hp_mode: fixed }                           # fixed | rolled(seed) | average
```

### 3.2 RoomSpec is the environment contract
Same pattern for space: one validated spec — dimensions, indoor/outdoor,
walls, light/obscurement zones, hazard zones, traps, difficult terrain,
cover objects, spawn regions. Generators emit it, the Foundry scene
importer emits it, a future UI editor edits it, the engine consumes it.
The 15 templates in `docs/domain/environment-system.md` become RoomSpec
presets (finally implementing that spec as data). Builds directly on the
existing Foundry-shaped wall/zone substrate (PRs #163–166).

### 3.3 Import maps to OUR content; it never ingests theirs
An importer translates a character's **build facts** (species X,
class/level Y, feat Z, item W — facts are not copyrightable) into PCSpec
references against our content registry. It never copies rules text. A
reference we haven't modeled becomes a structured `unmapped` entry the
user resolves in the builder — and those unmapped counts become our
content demand queue. Hard line per `docs/data-sources.md`: no scraping
or API-harvesting D&D Beyond; PDF-upload (user's own artifact) and
Foundry-actor-JSON (user's own export) are the supported machine paths.

### 3.4 The decision layer is a release gate, not a nicety
The briefing's product promise is *power/optimization testing of custom
builds*. A rankings product built on a naive pilot produces confidently
wrong tier lists — worse than nothing (README's own warning). Known
defects (run-2/3 findings): slot-pacing formula inverted (cantrip
outscores Disintegrate in the boss fight), positioning utility is
defense-only, no Legendary-Resistance-aware sequencing, Metamagic/
Overchannel never selected. WS-C closes these and gates Stage-2/3
optimization claims behind benchmark validation.

### 3.5 Archive-first instrumentation, reproducible by construction
Every archived run carries a **manifest**: engine version (git SHA),
content-bundle hash, rule bundle, seed, full encounter spec (PCSpec +
RoomSpec + dials + behavior profiles). A run is comparable only within
manifest-compatible cohorts; statistical aggregation keys on the
manifest. Local-first: SQLite (stdlib, Pyodide-compatible). Without
this, the dataset's statistical power dies at the first engine change.

### 3.6 Public compute = Pyodide client-side; one tiny ingest service
Exactly as `docs/architecture/browser-deployment.md` designed: static
site (GitHub Pages/CDN, $0), engine as WASM in a Web Worker, Monte Carlo
batches sized to browser budgets. The **only** server-side piece is a
small consent-gated ingest endpoint (serverless + managed Postgres) that
accepts run records. Phil pays for a webhook and a database, not compute.

### 3.7 Public content boundary: SRD-only bundle + user port
The public bundle compiler ships SRD content only. Non-SRD mechanical
content in this repo (MM monsters, PHB subclass/spell/feat/background
mechanics, DMG items) stays out of the public bundle; users bring their
own licensed content via import/builder entry (stored client-side).
Note an existing tension to resolve with counsel at the Stage-3 gate:
the public *repo* already contains clean-room non-SRD mechanical YAML —
the working interpretation is "never ship *expression*; public *product
bundle* stays SRD-only," and the builder's display of non-SRD *names* is
a specific counsel question (nominative-use in a builder looks more like
playable content than analysis — see §8).

### 3.8 Stage-4 stub discipline: capture, don't wire (Phil addendum)
Extend the 2026-06-09 non-combat-feature policy from features to **all
entity types**: data that only Stage 4 (AI DM) consumes is captured as
schema-validated stub fields at ingestion time — never engine-wired, never
dropped. Concretely: monster `habitat`/`treasure` (fields already exist;
76/261 populated — backfill task WS-A9, mandatory on all future monster
work), background personality/lore hooks, species non-combat traits,
ritual/social/exploration feats and spells (existing marker convention),
tool proficiencies, item flavor-facts (rarity/category). Tracked in
`docs/deferred-noncombat-features.md` as today. Rationale: re-research
is the most expensive form of deferral.

---

## 4. Workstreams

Lanes: **Architect** = planning/review/red-team synthesis (this model) ·
**Opus** = engine primitives, schema design, scoring, anything touching
`engine/ai/ehp_scoring.py` · **Sonnet** = data fan-out against
established patterns, instrumentation, presence tests (per
`docs/phase-3-plan.md` §6 protocol, which stays in force) · **Phil** =
purchases, owned-book source supply, policy calls.

### WS-A — PC building blocks (briefing §1 + magic items addendum)

| # | Step | Lane | Notes |
|---|---|---|---|
| A0 | **SRD 5.2.1 coverage audit**: enumerate exactly which backgrounds, species, feats, equipment, magic items, creation + multiclass rule text the SRD contains (the `data-sources.md` "do first" item). Output: per-entity SRD/PHB-delta/DMG-delta lists | Sonnet | Gates everything below; prevents hand-building what's free |
| A1 | **Schemas** for new entity types: `background.schema.json`, `feat.schema.json`, `equipment.schema.json` (weapon/armor/gear kinds), `magic_item.schema.json` (rarity, attunement, charges, activation, consumable flag) + Stage-4 stub fields on each | Opus | Mirror existing two-tier schema architecture |
| A2 | **Equipment library** (`equipment/eq_*.yaml`): SRD weapons (mastery props — engine support exists), armor/shields, combat-relevant gear. pc_schema accepts `eq_*` refs alongside today's inline weapon dicts | Opus seeds lookup path; Sonnet fans out | Inline form stays for fixtures |
| A3 | **Species**: remaining SRD species; PHB-2024 delta as Phil supplies (clean-room, owned book). Existing `r_*` pattern | Sonnet; Opus only for novel trait mechanics | Keep `races/` dir; alias "species" in docs |
| A4 | **Feats** (`feats/ft_*.yaml`): origin → general → fighting-style → epic boons. Many are real engine mechanics (GWM, Sentinel, PAM, Lucky, War Caster…) — same escalation protocol as spells: Sonnet builds against existing primitives, flags `NEEDS_ENGINE_WORK` forks to Opus | Mixed | ASI is a feat in 2024; `grant_asi_or_feat` rows already exist in class tables |
| A5 | **Backgrounds** (`backgrounds/bg_*.yaml`): ability +2/+1, origin feat ref, skills, tool, equipment package + Stage-4 lore stubs. Depends on A4 (origin feats) + A2 (packages) | Sonnet after Opus seeds first | 2024: backgrounds carry ability bonuses, not species |
| A6 | **Creation & level-up rules as code** (`engine/creation.py`): ability methods (point-buy 27 validator, standard array, manual), origin application order, starting equipment-or-gold, HP-per-level modes, subclass-at-3, prepared counts per level. Validation layer that PCSpec v2 runs through; encode from the PHB/SRD text, never training data | Opus | The builder UI and importers both call this one validator |
| A7 | **Spell selection model**: PCSpec `spells:` block validated against class list + `spellcasting` counts (already in class YAML); candidate generation respects the chosen subset. Default "auto-loadout" preset (= today's behavior) for quick sims | Opus (touches pc_schema + pipeline) | Closes "every wizard knows everything" |
| A8 | **Magic items & potions** (`magic_items/mi_*.yaml`): SRD set first; PHB/**DMG-2024** delta from Phil's owned books. Engine: +X weapons/armor/saves ride the existing modifier registry; charged items ride `feature_uses`; spell-granting items ride the monster `casts:` pattern; **potions = consumable actions** (new small consumable-inventory counter; 2024 drinking action economy per RAW). PCSpec `magic_items:`/`attuned:` (cap 3) | Opus seeds the 4 item archetypes + consumable counter; Sonnet fans out the catalog | sim-modes.md already anticipates scoring items on the build rubric |
| A9 | **Stage-4 stub backfill**: habitat/treasure for the ~185 monsters missing them; capture mandatory in any future monster work | Sonnet (low-priority filler) | Facts-only; quick |

Monster ingestion stays **paused** otherwise (briefing). The 261 built
monsters are the Stage-1/2 test bestiary.

### WS-B — Multiclassing (briefing §2)

| # | Step | Lane | Notes |
|---|---|---|---|
| B1 | Rules ingestion: multiclass chapter from SRD 5.2.1/PHB (A0 says which); encode prerequisites, proficiency grants, first-class rules | Opus | From the book, verbatim-checked |
| B2 | PCSpec v2 `classes:` list (order = acquisition order; first entry drives saves/L1 die/armor training) | Opus | Back-compat sugar preserved |
| B3 | Derivation merge: PB from character level; HP across hit dice; per-class features from each class's level_table at its class level; per-class resources coexist; audit existing `template.levels.<class>` gates (rage.py, rest.py, reckless_attack.py, defensive_ehp.py) | Opus | `template.levels` dict was built for this |
| B4 | **Slot math**: multiclass spellcaster table (full/half/third per RAW) for the shared pool; **Pact Magic is a separate pool** — `pact_slots` distinct from `spell_slots`, with **short-rest recovery** (closes the documented c_warlock v1 simplification — required, not optional, here) | Opus | `multiclass_slot_contribution: pact_magic` field already staged |
| B5 | **Casting interop** (the briefing's named concern): spells castable from either pool; upcast level = consumed slot's level; pact-slot consumers (smite-style invocations) target the right pool; Mystic Arcanum as `feature_uses` (1/long rest each), never slots | Opus | The Warlock-correctness centerpiece |
| B6 | Feature-interaction matrix: Extra Attack doesn't stack; armor-prof gates; Channel Divinity merging; rage-vs-concentration etc. — enumerate, test, document | Opus enumerates; Sonnet test fan-out | |
| B7 | **Oracle suite**: canonical builds with hand-verified derived stats + behavior — Paladin 2/Warlock X (pact-smite economy), Fighter 2/Wizard X (Action Surge nova), Sorcerer X/Warlock 2 (Flexible Casting ↔ pact slots as the stress case), Barbarian/caster anti-synergy | Opus authors oracle values; Sonnet scaffolds | Golden tests gate the Stage-1 exit |

### WS-C — PC decision layer + benchmarks (added; see §3.4)

| # | Step | Lane | Notes |
|---|---|---|---|
| C1 | **Nova/slot-pacing recalibration** — fix the inverted urgency formula + "last encounter" semantics (`docs/sim-modes.md`); framework-doc update + reference values; needs Phil's policy input | Opus + Phil | Highest offensive lever (run-2 #1) |
| C2 | **Offensive positioning term** — `best_position` currently defense-only; add offensive-reach eHP so casters advance to fire (run-3 finding) | Opus | |
| C3 | **LR-aware control sequencing** — drain Legendary Resistance with cheap effects before premium control | Opus | run-2 #3 |
| C4 | **Cast-decoration chooser** — the pre-cast transform hook that picks Metamagic / Overchannel / smite riders (per `docs/deferred-combat-followups.md`) | Opus | One framework, three consumers |
| C5 | **Golden-build benchmarks**: encode Treantmonk's 39 builds as PCSpec v2 fixtures; validate sim DPR against the `pc-dpr-baselines.md` methodology per tier; control-wizard benchmark (content-roadmap); re-run the boss-sim series | Sonnet encodes/runs; Opus interprets deltas; Architect reviews | **Stage-1 exit gate**; doubles as builder regression suite |

### WS-D — Environments & rooms (briefing §5)

| # | Step | Lane | Notes |
|---|---|---|---|
| D1 | **RoomSpec contract** (§3.2): schema + loader + fixture support | Opus | |
| D2 | **Hazard zones & traps**: static damaging zones (persistent_aura-shaped, not caster-anchored), triggered one-shot traps (trigger → save → effect, then spent) | Opus seeds both shapes; Sonnet hazard/trap library | environment-system.md specs these |
| D3 | **Cover derivation**: half/¾/total computed from walls + cover objects on the attack line (engine's per-actor `cover` field becomes derived); unlocks **Hide** (its documented blocker) and the positioning model's cover term | Opus (geometry × scoring) | |
| D4 | **Difficult terrain** (movement-cost regions) | Opus seed, small | |
| D5 | **Generic room generator**: parameterized presets (room W×H, corridor width, pillar/cover density, indoor/outdoor, light) emitting RoomSpec; encode the 15 environment templates as presets | Sonnet after D1 | The briefing's "generic rooms first" |
| D6 | **Foundry scene import**: scene-JSON walls/lights/templates → RoomSpec (reverse of the existing export; wall model is already Foundry-shaped) | Opus contract; Sonnet field mapping | Works from exported scene files; Phil's purchase supplies real test maps |
| D7 | **Encounter setup policies**: party entry formation + monster placement per positioning-model §7 (no more stacked spawns) | Opus | |

### WS-E — Builder UI + import (briefing §3, §4, §10)

| # | Step | Lane | Notes |
|---|---|---|---|
| E1 | **UI architecture**: static SPA (no server), schema-driven forms, runs fully client-side; this same shell later hosts the Pyodide engine (Stage 3) — one frontend codebase across stages | Opus | Stack recommendation: Svelte or React, decided at E1 |
| E2 | **Builder wizard** (DDB-modeled): Class → Origin (background, species) → Abilities → Equipment & magic items → Spells → Review; every step validates through `engine/creation.py` rules; emits PCSpec v2; dials + Rule Bundles (`RAW`/`Common-Table`/`Strict` — never raw toggles, per §Config) on a side panel | Opus first screen + pattern; Sonnet fan-out | |
| E3 | **PC library**: localStorage + YAML/JSON file import-export | Sonnet | No accounts pre-Stage-3 |
| E4 | **Importers**: (a) manual = builder; (b) **DDB character-sheet PDF upload** — AcroForm field extraction (pypdf, pure-Python/Pyodide-OK), field-map → PCSpec, unmapped→builder fix-up flow; (c) **Foundry dnd5e actor JSON** (user's own export; cleanest structure; aligns with WS-G). DDB shared-link/JSON endpoint: **not v1** — counsel question (§8) | Opus importer architecture + field-map spec; Sonnet mapping tables + fixtures | §3.3 governs |
| E5 | **Import fidelity harness**: golden sheets — derived AC/HP/attack/save/DC compared against the sheet's printed values; mismatch report = mapping bug surfaced | Sonnet | 2024-rules characters only at v1 (§7 risk 3) |

### WS-F — Logging, archive, metrics (briefing §7)

| # | Step | Lane | Notes |
|---|---|---|---|
| F1 | **Metric buckets v1** (stocktake ask): per-actor per-encounter aggregates — damage dealt/taken, hit %, slots by level, healing, control-rounds-denied, movement/exposure stats, outcome taxonomy (victory / TPK / fled-enemy-alive / stalemate) + closeness | Opus schema; Sonnet instrumentation + tests | Computed from the existing event log |
| F2 | **Run manifest** (§3.5): engine SHA + content hash + rule bundle + seed + full spec snapshot; CLI stamps it on every run | Opus | Reproducibility = re-run bit-identical |
| F3 | **Local archive**: SQLite writer (`engine/archive.py`), `--archive` on CLI + sims harness; aggregates always, full event stream optional flag | Sonnet after F2 | stdlib sqlite3; Pyodide-compatible |
| F4 | **Analysis surface**: canned queries/notebooks — tier bands, difficulty curves, dial sensitivity | Sonnet | Feeds Stage-2 reports |
| F5 | **Central ingest (Stage 3)**: serverless endpoint + managed Postgres; consent-gated; **submission trust controls** — schema + manifest validation, plausibility bounds, rate limits, version pinning, and sampled server-side seed-replay verification (cheap spot-checks, not full recompute) | Opus design; build at Stage 3 | Sim-side store; **only summaries ever cross to Trusight** (firewall rule 2) |

### WS-G — Foundry ladder (briefing §6, §9 — the ordering Phil asked for)

| # | Step | Lane | Notes |
|---|---|---|---|
| G1 | Purchase Foundry; pin version in `docs/architecture/foundry-integration.md` | Phil | Unblocks G2 test data |
| G2 | **Scene import** (= D6) — file-based, no module API risk | (WS-D) | First contact |
| G3 | **Replay module** (read-only): import a sim event log + scene; play it back — token movement, HP bars, chat cards. The "watch it play out" trust mechanism with minimal API surface | Opus | Ship before any live bridge |
| G4 | **Live bridge (observation mode)**: localhost WebSocket; Foundry drives the engine turn-by-turn (runner's observation mode was designed for an external driver) | Opus | After G3 proves the rendering map |
| G5 | Full in-Foundry UX (configure + launch sims from Foundry) | Later | Post-MVP |
| — | **Tokens (briefing §9)**: deferred per briefing — letters/discs in the web replay; Foundry's token ecosystem covers G3+; any bundled art needs a license check | — | |

Rationale for the ladder: each rung is independently useful; replay-
before-bridge isolates Foundry-API churn from engine correctness.

### WS-H — Public stage (briefing §8)

| # | Step | Lane | Notes |
|---|---|---|---|
| H1 | **Pyodide build** per `browser-deployment.md` (+ `load_yaml_string` loader sibling); Web Worker; MC batch sizing for browser budgets (Pyodide ≈3–5× CPython — publish guidance, e.g. 100–1,000 runs client-side) | Opus | Doc estimates ~1–3 days |
| H2 | **Public site** = E1 shell + run panel + results + 2D canvas replay viewer (the web stand-in for G3) + URL-shareable seeded runs | Opus pattern; Sonnet components | |
| H3 | **SRD-only bundle compiler** (§3.7): build step that strips non-SRD from the public content bundle; user-port path for non-SRD (import/builder, client-side storage) | Opus | |
| H4 | **Consent + telemetry**: explicit opt-in, plain-language scope (what's in a run record: manifest + aggregates, no PII), versioned consent text; wire to F5 | Opus + Phil wording | |
| H5 | **Counsel checkpoint** (the `data-sources.md` trigger): public + donations = engage counsel with the §8 question list | Phil | Blocks public launch, not the build |
| H6 | Abuse/ops: rate limiting, schema rejection metrics, static-host cache; status page | Sonnet | Near-zero cost posture |

---

## 5. Sequencing — three waves

**Wave 1 (now → Stage-1 gate):** A0 first (one Sonnet pass), then A1–A9
and B1–B7 as parallel lanes (content fan-out vs engine), C1–C4 on the
engine lane interleaved with B, C5 last (needs A+B complete). D1–D2
design can start anytime (Opus idle slots).

**Wave 2 (→ Stage-2 gate):** E1–E5 (needs PCSpec v2 frozen), D1–D7,
F1–F4, G1–G3. Builder UI and RoomSpec work are independent lanes; F1–F3
should land *early* in Wave 2 so every Wave-2 test run is archived.

**Wave 3 (→ Stage-3 gate / MVP):** H1–H6 + F5, then G4–G5 as follow-on.
Counsel (H5) engaged at Wave-3 start, not its end.

Dependency spine: `A0 → (A1..A9 ∥ B) → C5-gate → E ∥ D ∥ F ∥ G → H`.

---

## 6. Model-handoff protocol (extends `phase-3-plan.md` §6 — still in force)

- **Architect (this lane):** stage plans, gate reviews, red-team
  synthesis, cross-workstream consistency, framework-policy drafts for
  Phil sign-off.
- **Opus:** every new schema; every new primitive or engine system
  (multiclass merge, pact pools, consumables, hazards/traps, cover,
  importer architecture, archive manifest, Pyodide/Foundry builds); the
  first worked example of each new content pattern; **anything touching
  `engine/ai/ehp_scoring.py` or framework reference values**; batch diff
  review at checkpoints.
- **Sonnet:** A0 audit; all content fan-out against established patterns
  (equipment, feats-on-existing-primitives, backgrounds, species, magic
  items, hazard library, room presets, importer field maps, A9 backfill);
  metric instrumentation after schemas; golden-fixture encoding; presence
  tests; docs upkeep.
- **Hard rules unchanged:** Sonnet never decides the primitive-vs-module
  fork, never touches scoring, stops and flags instead of inventing.
  Full suite green before every push.

---

## 7. Gaps filled and risk register (what the briefing didn't list)

1. **PC decision layer** (→ WS-C). The whole optimization-testing promise
   rests on it; it gates Stage-1 exit.
2. **Spell selection** (→ A7). Without prepared/known subsets, "my wizard"
   is everyone's wizard and import fidelity is impossible.
3. **2014-vs-2024 import mismatch.** The engine is 2024-only; many DDB
   sheets are 2014 characters. v1 policy: import 2024 characters; detect
   2014 markers and fail with a clear message (no silent conversion).
4. **Public-data trust.** Client-computed submissions can be spoofed →
   F5's validation + sampled replay verification. Also **selection bias**:
   public users run weird fights; the dataset needs manifest-keyed cohort
   analysis, not naive pooling, before any "objective" claim.
5. **Reproducibility manifest** (→ F2). Without engine/content versioning,
   the archive is statistically dead after the first engine change.
6. **Legal checkpoint specifics** (→ H5, §3.7): non-SRD *names* in a
   public builder; PDF-import posture; users uploading non-SRD content
   we then store centrally; donations + public = the counsel trigger
   data-sources.md already names.
7. **Schema versioning policy** for PCSpec/RoomSpec/archive records —
   versioned from v1 with explicit migration rules, or imports and
   archives break silently later.
8. **Browser performance budget** (→ H1): publish MC sizing guidance;
   heavy studies stay on Phil's machine.
9. **Healer-AI vs death saves**: death saves exist engine-side; verify the
   heal scorer values dying allies correctly under the 2024 yo-yo pattern
   (C5 benchmark case).
10. **Initiative/surprise** remains an open rules question from the old
    list — fold into D7 encounter-setup work (2024: surprise =
    initiative disadvantage).
11. **Out of scope, said explicitly:** mounted combat, crafting,
    Bastions, downtime, non-combat pillars (Stage-4 stubs only, §3.8).

---

## 8. Decision queue for Phil

1. **C1 framework call:** nova-pacing policy (the "last fight = cheap
   slots" inversion) — needs your worked-example sign-off.
2. **Foundry version pin** at purchase (G1).
3. **DDB import stance:** confirm PDF-upload + Foundry-JSON only; the
   unofficial DDB JSON endpoint is parked for counsel.
4. **Public name display** of non-SRD options in the builder → counsel
   question list (H5).
5. **Telemetry granularity** for public ingest: manifest + aggregates
   only (recommended) vs optional full event streams.
6. **Ingest hosting** pick (any managed Postgres; Supabase/Neon-class
   free tier is fine at MVP scale).
7. **Consent wording** sign-off (H4).
8. **UI stack** confirmation at E1 (recommendation lands with a one-page
   comparison).
