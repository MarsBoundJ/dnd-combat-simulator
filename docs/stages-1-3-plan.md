# Stages 1–3 Plan v2 — Complete PCs → Customization & Environments → Public Sim

**Status:** v2 (2026-06-14) — supersedes the 2026-06-11 DRAFT. Incorporates the
AI-Cadre external red-team (Perplexity / ChatGPT / Gemini, 2026-06-14; resolved
in §9) and Phil's three calls: Foundry two-mode model (§3.9), public-monster
renaming (§3.8), and subclass-currency policy (§3.4 / WS-I).
**Companions:** `docs/stages-1-3-redteam-brief.md` (the review brief, on branch
`claude/vigilant-cray-p9qsz1`), `docs/phase-3-plan.md` (complete),
`docs/stocktake-2026-06-02.md`, `sims/FINDINGS.md`, `docs/sim-modes.md`,
`docs/data-sources.md`, `docs/architecture/browser-deployment.md`,
`docs/positioning-model.md`.
**Out of scope:** Stage 4 (AI DM) — but Stage-4 data stubs are captured as we go
(§3.10).

> **What changed from v1.** The bones held; the red-team confirmed the plan's
> own open questions (the review brief had already flagged most of them as
> stress-test items) and turned them into committed changes. Seven structural
> adopts (§9): two-layer PCSpec; archive/manifest pulled into Wave 1; multiclass
> spell-provenance made first-class; Metamagic as candidate-generation not
> post-hoc decoration; the decision-layer gate widened from DPR to a benchmark
> matrix; a two-tier (community vs verified) telemetry corpus; and a named
> content-resolution subsystem (WS-I) that now carries imports, the
> monster-renaming layer, and subclass currency. Plus a narrative event-log
> renderer (WS-F0), a Stage-2.5 browser-prototype gate, and an earlier legal
> checkpoint.

---

## 1. Where we actually are (baseline inventory, verified)

| Area | State |
|---|---|
| Engine | Full 8-step decision pipeline, 4 dials, RP constraints, positioning v1 (defense-weighted), walls + line-of-effect + zones + vision, all 3 AoE shapes + cube, concentration, spell slots, reactions (OA/Shield/Counterspell), death saves, short/long rests, multi-encounter session runner, ~3,260 tests |
| Event stream | 20+ typed, JSON-serializable events already emitted per run (the substrate WS-F0/F3/G3 all build on) |
| Classes | All 12 PHB-2024 classes; spell lists wired (Phase 3A–C complete); slot tables live |
| Subclasses | 13 built; expansion is fan-out, not novel design |
| Spells | 168 built / 391 tracked; 221 todo |
| Monsters | 261 built; **ingestion PAUSED**; 76/261 carry habitat/treasure Stage-4 stubs; every entity carries a `source` enum (`srd_5.2.1`/`phb_2024`/`mm_2024`/`user_authored`/`homebrew`) — the hook the public bundle and rename layer key off |
| Species | 4 SRD (`races/r_*.yaml`) |
| PC spec | `pc:` compact spec (class/level/abilities/armor/weapons/style/masteries/subclass/race/skills/expertise/metamagic/invocations) |
| Foundry | One-way export serializer (`engine/core/foundry_export.py`); **the sim stays authoritative, the documents are rendering hints**; codebase already distinguishes *sim mode* (engine drives) and *observation mode* (external driver feeds events). No module, no import yet |
| Sims/logging | Event log → `sims/*.py` Monte Carlo → stdout/JSON. **No persistence/DB, no narrative renderer** |
| Deployment | Pure-Python (PyYAML + jsonschema) → Pyodide-compatible; no web UI, no server, no Pyodide build yet |

**Missing (the gap this plan closes):** backgrounds, feats, equipment, magic
items & potions, creation/level-up rules, spell *selection*, multiclassing
(scaffolded only; Warlock pact slots recover on long rest as a v1 simplification),
builder UI, import, environments-as-data, hazards/traps/cover/terrain, any
DB/archive, narrative log, web UI, Foundry module, and the PC decision-layer
calibration (nova pacing inverted; positioning defense-only; no LR sequencing;
Metamagic/Overchannel never selected).

---

## 2. Stage definitions and exit gates

### Stage 1 — Complete the PC (engine + data; CLI-driven)
Backgrounds, species, feats, equipment, magic items & potions, creation rules,
spell selection, multiclassing (incl. Pact Magic), PCSpec v2 (two-layer), the PC
decision-layer upgrades, **and the archive/manifest substrate** (moved here from
Stage 2 — §9 adopt #2). Workstreams A, B, C, WS-F0–F3, WS-I (scaffold).

**Exit gate:** any legal 2024 single- or multi-class PC L1–20 can be declared in
PCSpec v2 and simulated; the multiclass oracle suite is green; golden-build
benchmarks (WS-C5) pass **as a matrix** (per-family, §3.5). Every benchmark run
emits a manifest and is archived + replayable (narrative log readable). The
Stage-1 optimization claim is **explicitly scoped to open-room / no-cover
encounters with declared spawn placement**, recorded in the manifest, until the
environment layer (WS-D) lands.

### Stage 2 — Customization & environments (private product surfaces)
Builder UI + import + PC library; RoomSpec environments; Foundry scene import +
**replay** (Mode 1 visualization); the rest of the local archive + analysis.
Workstreams D, E, F(local), G1–G3, WS-I (full).

**Exit gate:** Phil can build or import a PC in the UI, pick/import a room, run a
Monte Carlo batch locally, **watch the round-by-round playout in Foundry (and
read the narrative log)**, and query the archive.

### Stage 2.5 — Browser-feasibility gate (NEW; precedes any Stage-3 commitment)
A real Pyodide prototype that *measures* — not estimates — cold start, memory,
100/1,000-run batch times, replay responsiveness, import latency, and bundle
size on a low-memory phone and a midrange laptop, plus a **cross-runtime
determinism pass** (same seeds in CPython vs headless Pyodide, diff the event
logs). Stage 3 is contingent on these numbers (§9 adopt; P#4, P#15).

### Stage 3 — Public-facing (compute on the user's machine)
Pyodide build inside the static UI; SRD bundle **+ PI-safe renamed non-SRD layer**
(§3.8); consent-gated telemetry into a **two-tier corpus** (§3.6); counsel
checkpoint. Workstreams H, F5, plus the Mode-2 Foundry track (WS-G4) as
follow-on.

**Exit gate (= MVP):** a stranger opens the site, builds/imports a 2024 PC, picks
a room and monsters, runs sims entirely client-side, sees results + a narrative
log + a 2D replay, and (with explicit consent) contributes manifest-keyed run
records to the **community** corpus.

---

## 3. Keystone architecture decisions

### 3.1 PCSpec v2 is the lingua franca — in **two layers**
*(§9 adopt #1; P#2/#19, C#3, G#8 — 3-of-3 convergence.)* One versioned spec
family every surface emits or consumes, split so importers never have to
fabricate completeness:

- **`PCDraft` / `ImportCandidate`** — provenance-bearing, may hold unresolved
  references, fix-up items, and rule-version detection. What the builder edits
  mid-flow and what every importer first produces.
- **`ResolvedPCSpec`** — simulation-ready, fully validated. The only thing the
  engine, the archive, and the benchmark fixtures accept.

Every build carries an explicit **status triad** (a build can satisfy one and
fail another, and the UI must say which):
`rules_valid` (legal 2024 character) · `content_resolved` (every reference maps
to a known entity) · `engine_supported` (every referenced mechanic is modeled).

```yaml
pc:
  spec_version: 2
  status: { rules_valid: true, content_resolved: true, engine_supported: false }  # e.g. legal build, unmodeled subclass
  rule_version: "2024"                 # importer-detected; 2014 → reject with message (§7.3)
  classes:                             # order = acquisition; first entry drives saves/L1 die/armor training
    - { class: c_paladin, level: 2 }
    - { class: c_warlock, level: 5, subclass: sc_fiend }
  species: r_human
  background: bg_soldier
  ability_scores: { str: 16, dex: 10, con: 14, int: 8, wis: 10, cha: 16 }
  ability_method: point_buy
  feats: [ft_savage_attacker, ft_great_weapon_master]
  equipment: { armor: eq_chain_mail, shield: true, weapons: [eq_longsword, eq_javelin] }
  magic_items: [mi_ring_of_protection, mi_potion_of_healing_greater]
  attuned: [mi_ring_of_protection]     # cap 3, validated
  spells:                              # validated vs class lists + counts; provenance per spell (§WS-B)
    prepared: [{ id: sp_hex, source_class: c_warlock }, ...]
  level_up: { hp_mode: fixed }
  provenance: { imported_from: ddb_pdf, sheet_hash: "…" }   # draft-layer only
  unmapped: [ { kind: feat, raw: "Some 2025-book feat", reason: not_modeled } ]  # draft-layer; feeds WS-I demand queue
```

Back-compat: `class:`+`level:` remains sugar for a single-entry `classes:` list.
Round-trip (import → draft → resolved → export) is a tested invariant (§WS-E).

### 3.2 RoomSpec is the environment contract — geometry vs tactics, split
*(P#17, G#7.)* One validated spec for space, but layered so a Foundry import can
populate raw geometry first and tactical semantics get derived/reviewed
separately:

- **`RoomGeometry`** — dimensions, walls, light/obscurement zones, elevation,
  spawn regions. Import-friendly; what a Foundry scene maps onto directly.
- **`TacticalAnnotations`** — cover (derived from geometry), hazard zones, traps,
  difficult terrain, spawn-placement policy. Derived or reviewed, not assumed.

The coordinate model must **not hard-assume 1×1 footprints** even though Large+
multi-square actors are deferred — leave the origin+bounds shape open so it isn't
a later refactor. The 15 templates in `docs/domain/environment-system.md` become
presets.

### 3.3 Import maps to OUR content; it never ingests theirs
An importer translates **build facts** (species X, class/level Y, feat Z, item W
— facts aren't copyrightable) into PCSpec references against our registry. It
never copies rules text. Unresolved references become structured `unmapped`
entries (→ WS-I demand queue), never silent coercions. Hard line per
`docs/data-sources.md`: no scraping/API-harvesting D&D Beyond; PDF-upload (user's
own artifact) and Foundry-actor-JSON (user's own export) are the supported
machine paths.

**PDF import is explicitly low-trust** *(§9; P#10, C#4, G#6).* AcroForm field
extraction is fragile across sheet variants. Every PDF import carries field-level
confidence and **must** pass a mandatory fidelity diff (derived AC/HP/attack/save/
DC + inventory/spell anomalies vs the sheet's printed values) before it can become
a `ResolvedPCSpec`. A "mostly works" parser that looks authoritative is the
failure mode.

### 3.4 Content resolution & provenance is a first-class subsystem *(NEW — keystone; WS-I)*
*(§9 adopt #7; P#11.)* Not ad-hoc UI fix-ups — a named subsystem with: canonical
internal IDs, **aliases** (incl. the public rename map, §3.8), source/provenance
tags (the existing `source` enum), ambiguity classes, and human-review reasons.
Four problems converge here, so they share one mechanism:

1. **Import resolution** — raw sheet strings → our IDs; ambiguous/unknown → review.
2. **Public monster renaming** (§3.8) — internal id → PI-safe public display name.
3. **Subclass (and content) currency** — *demand-driven, not a treadmill.*
   Unmodeled subclasses/feats/items uploaded by users become a **prioritized
   backlog ranked by real demand**; the most-requested gap surfaces first and is
   then modeled as ordinary content fan-out. A subscription (Phil) helps as
   *source supply* (authoritative text to clean-room from) — it changes nothing
   legally about what we ship and does not remove per-item modeling work. **PHB
   subclasses are the current scope.** An unmodeled reference **fails loud**
   (`engine_supported: false`, "not yet supported"), never silently degrades.
4. **Homebrew / non-comparable cohorts** — anything `user_authored`/`homebrew`
   is tagged so analytics never pool it with first-party content (C#14).

### 3.5 The decision layer is a release gate — and the gate is a **matrix**
*(§9 adopts #4,#5; P#6/#7, C#2.)* The product promise is power/optimization
testing; a naive pilot produces confidently-wrong tier lists (worse than nothing).
Two corrections to v1:

- **Candidate generation, not post-hoc decoration.** Metamagic / Overchannel /
  smite riders change the *action graph* (target count, action economy, save
  pressure), so they must be generated as distinct `(action × modifier)`
  candidates that get scored — not chosen by decorating an already-ranked spell.
  Decorating-after-ranking optimizes against the wrong search surface.
- **The benchmark gate is a family matrix, not just DPR.** DPR validates local
  action choice only. Required families, each independently blocking the
  optimization claim: day-level resource pacing; closing/kiting; concentration
  protection; Legendary-Resistance sequencing; mixed-role party coordination;
  the healer-vs-death-saves yo-yo case. The **Stage-1 claim is scoped to
  open-room/no-cover** (recorded in the manifest) until WS-D lands; spawn
  placement (WS-D7) is pulled early so positioning/AoE benchmarks aren't run
  against clustered spawns.

### 3.6 Archive-first, reproducible by construction — and **actually first**
*(§9 adopt #2; P#1, C#6 — fixes a v1 self-contradiction: v1 declared
"archive-first" but scheduled the archive in Wave 2, after the Stage-1 benchmark
gate that depends on it.)*

- **The typed event stream is the single source for everything** — narrative log
  (WS-F0), 2D web replay, Foundry replay (WS-G3), and the archive — so no two
  renderers can disagree about what happened.
- Every run carries a **manifest**: engine git SHA, content-bundle hash, rule
  bundle, seed, full encounter spec (Resolved PCSpec + RoomSpec + dials +
  behavior profiles). Aggregation keys on manifest-compatible cohorts only.
- **Local-first SQLite (stdlib, Pyodide-compatible). Manifest stamping + a
  minimal archive land in Wave 1** so every benchmark/oracle/tuning run is
  reproducible from the moment it could count toward Stage-1 sign-off.
- **Two-tier corpus** *(§9 adopt #6; P#5, C#5, G#5):* a **community** tier
  (untrusted, observational) and a **verified** tier (server-recomputed). Only
  the verified tier may back any public/"objective" claim. Designed into the
  schema now; the verified-recompute service builds at Stage 3.
- **Cross-runtime determinism is a proven property, not an assumption** — a
  CPython-vs-Pyodide event-log diff test (the Stage-2.5 gate). *(Calibration: low
  risk — Pyodide is CPython-on-WASM with the same RNG and IEEE-754 doubles — but
  the test is cheap and converts an assumption into a guarantee. §9.)*

### 3.7 Public compute = client-side Pyodide; one tiny ingest service
Static site ($0 host), engine as WASM in a Web Worker, Monte Carlo sized to
browser budgets (per `browser-deployment.md`). The only server-side piece is a
small consent-gated ingest endpoint (serverless + managed Postgres). Ingest
carries **DoS bounds** *(G#5):* reject manifests exceeding combatant/round/
size limits; run any server-side replay sandboxed with a hard CPU timeout.

### 3.8 Public content boundary: SRD bundle **+ PI-safe renamed non-SRD layer**
*(Phil's call; replaces v1's strict SRD-only posture. §9.)* The most popular
monsters live in the MM, not the SRD, so the public product ships them under
**Product-Identity-safe renamed display names** (e.g. Beholder → "Eye Tyrant",
Displacer Beast → "Phase Panther"), implemented as an alias layer in WS-I keyed
off the existing `source` tag. Rationale and guardrails:

- **Mechanics/stat blocks aren't copyrightable**; our YAML is already clean-room
  (no flavor prose). Renaming addresses the protected/trademarked *name*.
- **Hard constraints:** never ship WotC flavor/description text; the rename map
  is ours; the public bundle ships the renamed display layer over id-keyed
  mechanics.
- **Telemetry redaction boundary** *(P#12, G#2):* public ingest accepts only
  SRD-safe opaque IDs from our namespace. Non-SRD references never round-trip
  into public storage or UI as proprietary names.
- **This is the #1 counsel item and it moves earlier** (§3.9-legal, §8). Shipping
  a renamed-but-mechanically-identical popular monster in a public, possibly
  monetized product is a bigger step than SRD-only and wants a yes/no *before*
  the bundle compiler is built around it. *Not legal advice — flag for counsel.*

### 3.9 Foundry & visualization: two modes, sequenced *(Phil's call)*
The engine is **authoritative in both modes**; Foundry renders.

- **Mode 1 — Autonomous (MVP, all stages).** Set parameters, run N seeded times;
  the engine plays the whole fight; the playout is *visualized, not controlled*.
  Visualization renderers all consume the one event stream (§3.6): **narrative
  text log** (WS-F0, available from the CLI today), **2D web canvas** (WS-H2),
  and **Foundry replay** (WS-G3). *Replay-from-saved-log vs live-streaming is an
  MVP non-decision* — the user can't intervene either way — so we adopt
  **replay-from-the-event-log** (simpler, deterministic, shareable, reuses the
  archive). This is the de-black-boxing Phil wants: read the transcript, watch
  the tokens, both rendering the same authoritative record.
- **Mode 2 — Interactive (post-MVP, WS-G4).** Players move their own PCs and pick
  actions on their turn; the DM overrides monster positions/actions; the engine
  adjudicates the rest. This is the genuine added complexity (the codebase's
  *observation mode* is its seed) and Foundry is built for it — built *after*
  replay proves the rendering contract.

**Pin both Foundry core and the dnd5e system version** *(P#16)*, with fixture
scenes/actors checked in as a compatibility-regression matrix.

### 3.10 Stage-4 stub discipline: capture, don't wire
Extend the non-combat-feature policy to all entity types: data only Stage 4
consumes is captured as schema-validated stub fields, never engine-wired, never
dropped (habitat/treasure, background lore, species non-combat traits, ritual/
social/exploration feats & spells, tool profs, item flavor-facts). **Refinement
*(P#24):*** only stub fields with a clear source-of-truth and likely future
identity; for genuinely speculative data use a namespaced extension blob with no
implied semantics, so stubs don't become schema debt. Tracked in
`docs/deferred-noncombat-features.md`.

---

## 4. Workstreams

Lanes: **Architect** = planning/review/red-team synthesis (this model) · **Opus**
= engine primitives, schemas, scoring, anything touching `engine/ai/
ehp_scoring.py` · **Sonnet** = data fan-out against established patterns,
instrumentation, presence tests · **Phil** = purchases, owned-book source supply,
policy/counsel calls. *(See §6 on how lanes map to execution now that all
implementation routes through Opus browser instances.)*

### WS-A — PC building blocks

| # | Step | Lane | Notes |
|---|---|---|---|
| A0 | **SRD 5.2.1 coverage audit** — exactly which backgrounds/species/feats/equipment/magic-items/creation+multiclass rules the SRD contains | Sonnet | Gates everything below |
| A1 | **Schemas** for background/feat/equipment/magic_item (+ Stage-4 stub fields, `source`, alias hooks) | Opus | Mirror the two-tier schema architecture |
| A2 | **Equipment library** (`eq_*.yaml`): SRD weapons (mastery props), armor/shields, combat gear | Opus seeds; Sonnet fans out | Inline weapon form stays for fixtures |
| A3 | **Species**: remaining SRD; PHB-2024 delta as Phil supplies | Sonnet; Opus for novel traits | Keep `races/`, alias "species" |
| A4 | **Feats** (`ft_*.yaml`): origin→general→fighting-style→epic boons; engine-real ones (GWM, Sentinel, PAM, War Caster) escalate to Opus | Mixed | ASI-as-feat; `grant_asi_or_feat` rows exist |
| A5 | **Backgrounds** (`bg_*.yaml`): +2/+1, origin-feat ref, skills, tool, equipment package + lore stubs | Sonnet after Opus seed | Depends on A4 + A2 |
| A6 | **Creation & level-up rules as code** (`engine/creation.py`): ability methods + validators, origin order, equipment-or-gold, HP modes, subclass-at-3, prepared counts. **Separates `rules_valid` from `engine_supported` (§3.1).** | Opus | One validator; UI + importers both call it |
| A7 | **Spell selection model**: PCSpec `spells:` validated vs class list + counts; candidate gen respects the subset; default auto-loadout preset. **Spell-selection completeness gate** *(P#8):* no oracle/benchmark build may depend on a legal spell happening to be unbuilt | Opus | Closes "every wizard knows everything" |
| A8 | **Magic items & potions** (`mi_*.yaml`): treat as a **primitive family with its own interaction matrix** *(P#20, C#12)* — attunement, activation timing, override behavior, item-granted-casting provenance, potions as consumable action-economy. +X via modifier registry; charges via `feature_uses`; spell-granting via `casts:`. **Interaction matrix + primitive-closure check precede fan-out** | Opus seeds archetypes + matrix; Sonnet fans out | sim-modes.md scores items on the build rubric |
| A9 | **Stage-4 stub backfill**: habitat/treasure for ~185 monsters | Sonnet (filler) | Facts-only |

Monster ingestion stays **paused**; the 261 built monsters are the Stage-1/2 test
bestiary.

### WS-B — Multiclassing (spell provenance is first-class)

| # | Step | Lane | Notes |
|---|---|---|---|
| B1 | Rules ingestion: multiclass chapter (SRD/PHB), prerequisites, prof grants, first-class rules | Opus | Book-verbatim-checked |
| B2 | PCSpec v2 `classes:` list (order = acquisition; first entry drives saves/L1 die/armor) | Opus | Back-compat sugar preserved |
| B3 | Derivation merge: PB by character level; HP across hit dice; per-class features; per-class resources coexist; audit `template.levels.<class>` gates | Opus | `template.levels` dict was built for this |
| B4 | **Slot math**: multiclass spellcaster table (full/half/third per RAW) for the shared pool; **Pact Magic is a separate pool with short-rest recovery** (closes the c_warlock v1 long-rest simplification). **Half-caster (Pal/Ran) multiclass rounding verified against the 2024 table via oracle test** — do not trust memory *(G#1 garbled its math; the test is the point)* | Opus | `multiclass_slot_contribution: pact_magic` staged |
| B5 | **Casting interop**: spells castable from either pool; upcast = consumed slot level; pact-slot consumers target the right pool; Mystic Arcanum as `feature_uses`. **Each known/prepared spell carries source class, casting ability, eligible slot pool(s), recharge regime** *(§9 adopt #3; P#3)* | Opus | The Warlock-correctness centerpiece |
| B6 | Feature-interaction matrix: Extra Attack non-stacking; armor gates; Channel Divinity merge; rage-vs-concentration | Opus enumerates; Sonnet tests | |
| B7 | **Oracle suite** (Stage-1 gate): Paladin 2/Warlock X (pact-smite economy), Fighter 2/Wizard X (Action Surge nova), **Sorcerer X/Warlock 2 with a slot-cap invariant + degenerate-loop guard** (the "coffeelock" stress case — see §9 calibration), Barbarian/caster anti-synergy. Rest cadence stays **exogenous** (scenario-driven, never AI-elected) | Opus authors values; Sonnet scaffolds | Golden tests gate Stage-1 |

### WS-C — PC decision layer + benchmarks

| # | Step | Lane | Notes |
|---|---|---|---|
| C1 | **Nova/slot-pacing recalibration** — fix the inverted urgency formula + "last encounter" semantics | Opus + Phil | Highest offensive lever; needs Phil's policy sign-off |
| C2 | **Offensive positioning term** — add offensive-reach eHP so casters advance to fire | Opus | |
| C3 | **LR-aware control sequencing** — drain Legendary Resistance with cheap effects first | Opus | |
| C4 | **Cast-candidate generation** — `(action × modifier)` candidates for Metamagic/Overchannel/smite, scored as distinct entries (§3.5), **not** post-hoc decoration | Opus | One framework, three consumers |
| C5 | **Golden-build benchmark *matrix*** (Stage-1 exit, §3.5): Treantmonk's 39 builds as PCSpec v2 fixtures + control wizard + the family suite (pacing/kiting/concentration/LR/party/healer-yo-yo); re-run the boss series. Open-room/no-cover scope recorded in manifest | Sonnet encodes/runs; Opus interprets; Architect reviews | Doubles as builder regression suite |

### WS-D — Environments & rooms

| # | Step | Lane | Notes |
|---|---|---|---|
| D1 | **RoomGeometry + TacticalAnnotations** contracts (§3.2): schemas + loader + fixtures | Opus | |
| D2 | **Hazard zones & traps**: static damaging zones; triggered one-shot traps | Opus seeds shapes; Sonnet library | |
| D3 | **Cover derivation**: half/¾/total from geometry — as **discrete rules with a visual test harness** *(C#8)*, not free-form geometry; unlocks Hide + the positioning cover term | Opus | |
| D4 | **Difficult terrain** (movement-cost regions) | Opus seed | |
| D5 | **Room generator**: parameterized presets emitting RoomGeometry; encode the 15 templates; **track the environment distribution in the manifest** *(C#13)* | Sonnet after D1 | |
| D6 | **Foundry scene import** → RoomGeometry (reverse of export) | Opus contract; Sonnet mapping | |
| D7 | **Encounter-opening placement policies** — party formation + monster placement presets. **Pulled early (Wave 1) and recorded in the manifest** *(P#23)* so benchmarks never silently use clustered spawns | Opus | |

### WS-E — Builder UI + import

| # | Step | Lane | Notes |
|---|---|---|---|
| E1 | **UI architecture**: static SPA, client-side, later hosts the Pyodide engine. Stack decided here (Svelte or React) | Opus | One frontend across stages |
| E2 | **Builder wizard**: Class → Origin → Abilities → Equipment & items → Spells → Review; validates via `engine/creation.py`; emits PCSpec v2; Rule Bundles (`RAW`/`Common-Table`/`Strict`) on a side panel. **Prototype the "repair imported character" path before freezing the UI/spec contract** *(P#22)* — repair, not greenfield, is the real shape | Opus first screen; Sonnet fan-out | |
| E3 | **PC library**: localStorage + YAML/JSON import-export | Sonnet | No accounts pre-Stage-3 |
| E4 | **Importers**: (a) manual = builder; (b) **DDB PDF** (low-trust, §3.3); (c) **Foundry dnd5e actor JSON**. DDB JSON endpoint NOT v1 (counsel) | Opus architecture + field-map; Sonnet tables + fixtures | §3.3 governs |
| E5 | **Import fidelity harness** + **draft↔resolved round-trip tests** (§3.1): derived AC/HP/attack/save/DC vs printed; mismatch = mapping bug surfaced; 2024-rules only at v1 | Sonnet | |

### WS-F — Logging, archive, metrics *(F0–F3 in Wave 1)*

| # | Step | Lane | Notes |
|---|---|---|---|
| **F0** | **Narrative event-log renderer** *(NEW)* — typed event stream → human-readable round-by-round transcript ("PC A moves to (x,y); attacks, misses (7); hits (18) for 11; orc 70% HP"). Pure formatter, CLI-first, Foundry-independent | Sonnet | Cheapest de-black-boxing; shared by CLI/web/Foundry |
| F1 | **Metric buckets v1**: per-actor per-encounter aggregates + outcome taxonomy + closeness | Opus schema; Sonnet instrumentation | From the event log |
| F2 | **Run manifest** (§3.6): SHA + content hash + rule bundle + seed + full spec snapshot | Opus | Reproducibility |
| F3 | **Local archive**: SQLite writer (`engine/archive.py`), `--archive` flag; aggregates always, event stream optional | Sonnet after F2 | stdlib sqlite3; Pyodide-OK |
| F4 | **Analysis surface**: canned queries/notebooks — tier bands, difficulty curves, dial sensitivity. **Validate each statistical product against the public schema before freezing it** *(P#14)* | Sonnet | |
| F5 | **Central ingest (Stage 3)**: serverless + Postgres; consent-gated; **two-tier corpus** (§3.6) + DoS bounds + sampled server recompute for the *verified* tier; only summaries cross to Trusight | Opus design; build at Stage 3 | |

### WS-G — Foundry ladder (two modes, §3.9)

| # | Step | Lane | Notes |
|---|---|---|---|
| G1 | Purchase Foundry; **pin core + dnd5e system version**; fixture scenes/actors as a regression matrix | Phil + Opus | Unblocks test data |
| G2 | **Scene import** (= D6) — file-based, no module-API risk | (WS-D) | First contact |
| G3 | **Replay module (Mode 1 visualization, MVP)**: render the event log as token movement / attacks / HP bars + chat cards. The "watch it play out" trust mechanism | Opus | Ship before any interactive mode |
| G4 | **Interactive mode (Mode 2, post-MVP)**: players control their PCs on their turn; DM overrides monsters; engine adjudicates the rest (localhost bridge; observation-mode seed) | Opus | After G3 proves the rendering map |
| G5 | Full in-Foundry UX (configure + launch sims from Foundry) | Later | Post-MVP |
| — | **Tokens**: placeholders/discs in web replay; Foundry's ecosystem covers G3+; bundled art needs a license check | — | |

### WS-H — Public stage

| # | Step | Lane | Notes |
|---|---|---|---|
| H1 | **Pyodide build** (+ `load_yaml_string` loader); Web Worker; MC batch sizing. **Gated by the Stage-2.5 measurements (§2), not estimates** | Opus | |
| H2 | **Public site** = E1 shell + run panel + results + **2D canvas replay** + narrative log + URL-shareable seeded runs | Opus pattern; Sonnet components | |
| H3 | **Bundle compiler** (§3.8): SRD content **+ PI-safe renamed non-SRD layer**; telemetry redaction (SRD-safe opaque IDs only); user-port for anything else | Opus | |
| H4 | **Consent + telemetry**: explicit opt-in, plain-language scope (manifest + aggregates, no PII), versioned consent text; wire to F5's community tier | Opus + Phil wording | |
| H5 | **Counsel checkpoint** — **moved earlier**: a narrow pre-architecture review of the renaming-distribution, import, public-bundle, and telemetry-retention boundaries *before* those schemas freeze (P#13, C#17, G#2), not only at launch | Phil | Blocks the risky schema freezes |
| H6 | Abuse/ops: rate limiting, schema-rejection metrics, static-host cache, status page | Sonnet | |

### WS-I — Content resolution & provenance *(NEW; §3.4)*

| # | Step | Lane | Notes |
|---|---|---|---|
| I1 | **Resolution core**: canonical IDs, alias table, `source`/provenance, ambiguity classes, review reasons | Opus | The subsystem imports + bundle + currency share |
| I2 | **Unmapped demand queue**: unresolved imports → prioritized backlog ranked by demand | Sonnet after I1 | Drives the content roadmap |
| I3 | **Public rename map** (§3.8): internal id → PI-safe display name for non-SRD; counsel-gated for distribution | Sonnet content; Phil/counsel gate | Keyed off `source` |
| I4 | **Cohort tagging**: `user_authored`/`homebrew` flagged non-comparable for analytics | Sonnet | C#14 |

---

## 5. Sequencing — three waves + the 2.5 gate

**Wave 1 (→ Stage-1 gate):** A0 first, then A1–A9 ∥ B1–B7 as parallel lanes;
C1–C4 interleaved on the engine lane; **WS-F0–F3 land early** (narrative log +
manifest + minimal archive) so every benchmark run is reproducible from day one;
**D7 spawn presets pulled in**; WS-I (I1 scaffold) starts early because imports
and renaming both need it; C5 last (needs A+B + the archive). D1–D2 design can
start in Opus idle slots.

**Wave 2 (→ Stage-2 gate):** E1–E5 (needs PCSpec v2 frozen), D1–D7, F4, G1–G3,
WS-I full. Builder and RoomSpec are independent lanes.

**Stage 2.5 (browser-feasibility gate):** the Pyodide prototype + cross-runtime
determinism pass (§2). **Go/no-go before any Wave-3 commitment.**

**Wave 3 (→ Stage-3 gate / MVP):** H1–H6 + F5, then G4–G5 follow-on. Counsel
(H5) engaged at the *start* of the risky-schema work, not its end.

Dependency spine:
`A0 → (A1..A9 ∥ B) + F0..F3 + I1 + D7 → C5-gate → E ∥ D ∥ F4 ∥ G1..G3 → [Stage-2.5 gate] → H ∥ G4`.

---

## 6. Model-handoff protocol (extends `phase-3-plan.md` §6 — still in force)

- **Architect:** stage plans, gate reviews, red-team synthesis, cross-workstream
  consistency, framework-policy drafts for Phil sign-off, **batch-diff review at
  every checkpoint**.
- **Opus:** every new schema/primitive/engine system (multiclass merge + spell
  provenance, pact pools, consumables, hazards/traps/cover, importer
  architecture, archive manifest, resolution core, Pyodide/Foundry builds); the
  first worked example of each new content pattern; **anything touching
  `ehp_scoring.py` or framework reference values**.
- **Sonnet:** A0; content fan-out against established patterns; instrumentation;
  golden-fixture encoding; presence tests; docs upkeep.
- **Primitive-closure governance** *(NEW; P#18):* before any content family fans
  out, an explicit **primitive-closure checklist** must be signed off, and ~10%
  of fan-out output is sample-reviewed for unexpected new semantics. If more than
  a small threshold needs architect/Opus intervention, the workstream was
  misclassified — stop and re-scope.
- **Execution note (the "no cheap lane right now" reality):** all implementation
  currently routes through **Opus** browser instances. The Opus/Sonnet split
  therefore denotes **review intensity and risk**, not a model assignment — the
  loud-failure safety net (full suite green before push) still applies, and the
  **hard rule is unchanged: the primitive-vs-module fork and any scoring change
  stop for architect review; "looks like it needs something new" is the
  escalation trigger.**

---

## 7. Gaps filled and risk register

1. **PC decision layer** (→ WS-C) — gates Stage-1; now a benchmark matrix (§3.5).
2. **Spell selection + completeness gate** (→ A7) — no oracle may pass on
   accidentally-absent spells (P#8).
3. **2014-vs-2024 import mismatch** — v1 policy: import 2024; detect 2014 markers
   and fail with a clear message; subclass-at-3 enforced (G#10).
4. **Public-data trust** (→ F5, §3.6) — two-tier corpus + sampled recompute + DoS
   bounds; selection bias handled by manifest-keyed cohorts, not naive pooling.
5. **Reproducibility manifest + cross-runtime determinism** (→ F2, Stage-2.5).
6. **Legal checkpoint specifics** (→ H5, §3.8) — renaming distribution is now the
   top counsel item and the checkpoint moves earlier.
7. **Schema versioning** for PCSpec/RoomSpec/archive — versioned from v1 with
   explicit migration rules (P#7-schema).
8. **Browser performance budget** (→ Stage 2.5) — measured per device class: cold
   start, content parse, first-sim latency, throughput, replay FPS (P#4, P#21).
9. **Healer-AI vs death saves** — a named benchmark family (C5).
10. **Initiative/surprise** — folded into D7 (2024: surprise = initiative
    disadvantage).
11. **Multi-tile actors** — deferred, but the coordinate model stays
    footprint-agnostic so it isn't a later refactor (G#7).
12. **Out of scope, explicitly:** mounted combat, crafting, Bastions, downtime,
    non-combat pillars (Stage-4 stubs only).

---

## 8. Decision queue for Phil (reordered by urgency)

1. **Monster-renaming distribution → counsel (NEW #1).** Confirm the PI-safe
   renamed-non-SRD public bundle strategy (§3.8) and engage counsel *before* the
   bundle compiler + telemetry-redaction schemas freeze (H5 moved earlier).
2. **C1 nova-pacing framework sign-off** (the "last fight = cheap slots"
   inversion) — needs your worked-example approval.
3. **Foundry pin** at purchase — core **and** dnd5e system version (G1).
4. **DDB import stance** — confirm PDF + Foundry-JSON only; DDB JSON endpoint
   parked for counsel.
5. **Telemetry granularity + verified-corpus policy** — manifest + aggregates
   into community tier; server-recompute for the verified tier that backs public
   claims (recommended).
6. **Ingest hosting** — any managed Postgres (Supabase/Neon-class free tier).
7. **Consent wording** sign-off (H4).
8. **UI stack** confirmation at E1.
9. **Stage-2.5 gate acceptance criteria** — the device-class numbers that make
   Stage 3 a go.

---

## 9. Red-team resolution (AI Cadre, 2026-06-14)

Three independent reviews (Perplexity = P, ChatGPT = C, Gemini = G) of the
`stages-1-3-redteam-brief.md`. Convergence (≥2 reviewers, no coordination) is the
signal.

**Calibration before the table:**
- **Discount the citations.** P's links nearly all point to one unrelated DDB
  cantrip-multiclass forum thread (and a Facebook group); they don't support the
  findings. Judge the reasoning, ignore the links.
- **Coffeelock is bounded, not a BLOCKER.** Verified in-repo: rests are applied
  by the session harness (`apply_short_rest`/`apply_long_rest`), not AI-elected
  (`feature_uses.py`: "no rest cycle in-encounter yet"), and pact slots currently
  recover on long rest. The AI cannot farm short rests. Residual risk is real but
  narrow → a slot-cap invariant + one Sorlock oracle + exogenous rest cadence
  (WS-B7). Downgraded G#4/C#1 BLOCKER → bounded.
- **Determinism panic is over-stated.** Pyodide *is* CPython-on-WASM (same RNG,
  same IEEE-754 doubles); divergence is unlikely. Kept as a cheap Stage-2.5 test
  that converts the assumption into a guarantee, not a redesign.
- **G#1's half-caster math is internally garbled** (its worked example doesn't
  compute). The *action* — an oracle test verifying 2024 multiclass rounding
  against the actual table — is correct and adopted (WS-B4). Do not propagate its
  numbers.

| Theme | Reviewers | Calibrated severity | Disposition → lands in |
|---|---|---|---|
| Two-layer PCSpec (draft/candidate vs resolved) + status triad | P2/P19, C3, G8 | BLOCKER | **Adopt** → §3.1, WS-E5 |
| Archive/manifest pulled into Wave 1 (fix self-contradiction) | P1, C6 | BLOCKER | **Adopt** → §3.6, WS-F2/F3, §5 |
| Multiclass spell provenance first-class + Sorlock/half-caster oracles | P3, G1/G4, C1 | BLOCKER (calibrated) | **Adopt** → WS-B5/B7 |
| Metamagic = candidate generation, not decoration | P7 | MAJOR | **Adopt** → §3.5, WS-C4 |
| Decision gate = benchmark matrix, not just DPR; scope claim open-room | P6, C2 | MAJOR | **Adopt** → §3.5, WS-C5, D7 |
| Two-tier telemetry corpus + DoS bounds | P5, C5, G5 | BLOCKER | **Adopt** → §3.6/3.7, WS-F5 |
| Content-resolution subsystem (alias/provenance/ambiguity) | P11 | MAJOR | **Adopt** → §3.4, WS-I |
| PDF import low-trust + mandatory fidelity diff | P10, C4, G6 | MAJOR | **Adopt** → §3.3, WS-E5 |
| Cross-runtime determinism test + browser-feasibility gate | P4/P15, C9/C10, G3 | MAJOR (calibrated low-prob) | **Adopt as gate** → Stage 2.5 |
| Legal checkpoint moved earlier | P13, C17, G2 | MAJOR | **Adopt** → WS-H5, §8 |
| Magic items = primitive family + interaction matrix | P20, C12 | MAJOR | **Adopt** → A8 |
| Spell-selection completeness gate | P8 | MAJOR | **Adopt** → A7 |
| Primitive-closure checklist + fan-out sampling | P18 | MAJOR | **Adopt** → §6 |
| RoomGeometry / TacticalAnnotations split; cover as discrete rules | P17, C8 | MAJOR | **Adopt** → §3.2, D1/D3 |
| Spawn-placement presets early + in manifest | P23, C13 | MINOR | **Adopt** → D7 (Wave 1) |
| "Repair imported character" path prototyped before UI freeze | P22 | MAJOR | **Adopt** → E2 |
| Telemetry redaction (SRD-safe opaque IDs only) | P12, G2 | MAJOR | **Adopt** → §3.8, H3 |
| Foundry: pin dnd5e system + compatibility matrix | P16 | MAJOR | **Adopt** → G1 |
| Multi-tile footprint-agnostic coordinates | G7 | MAJOR | **Adopt (cheap)** → §3.2, §7.11 |
| Stub only with clear source-of-truth; else extension blob | P24 | MINOR | **Adopt** → §3.10 |
| Coffeelock infinite-loop | G4, C1 | (claimed BLOCKER) | **Down-rank → bounded** (calibration above) |
| Determinism = "redesign with fixed-point/custom RNG" | G3, C10 | (claimed MAJOR) | **Partial**: test yes, fixed-point no (over-engineered for CPython-on-WASM) |
| No-accounts longitudinal telemetry weakness | P25 | MINOR | **Accept**: narrow MVP dataset claims; client install-IDs later |
| "Owns the books is legally irrelevant" | P26 | MINOR | **Note only**: ownership is for clean-room *source supply*, not a distribution right — language already says so |

Down-ranked/deferred without action beyond a note: property-based interaction
testing at scale (C15 — adopt opportunistically), opt-in selection bias framing
(C18/P25 — covered by cohort analysis), long-tail spell fidelity registry (C19 —
the existing NEEDS_ENGINE_WORK convention already serves this).
