# Stages 1–3 Plan — Red-Team Brief

> **Historical artifact.** The v1 snapshot sent to the AI Cadre for review.
> The current plan is `docs/stages-1-3-plan.md` (v2); its §9 resolves these
> findings. Kept for provenance — do not edit as if it were the live plan.

*Self-contained snapshot for external review (2026-06-11). Planning stage —
NOT yet implemented. Goal of this review: **soundness + completeness check
of the plan.** Poke holes, find sequencing errors, surface blind spots,
missing workstreams, and wrong architectural bets. We are NOT seeking new
feature ideas — we want to know where this plan fails, lies to itself, or
underestimates. Our own known deferrals are listed in §10 so you can look
**past** them and find what we haven't seen.*

***Output format requested:** numbered findings; each with (a) severity —
BLOCKER / MAJOR / MINOR, (b) which plan section it hits, (c) the failure
scenario in one or two sentences, (d) a suggested fix or test. Rank your
top 5 at the end. Challenge premises, not just details — "this whole
workstream is mis-ordered" is a valid finding.*

---

## 1. What this project is

A locally-run **D&D 5e (2024 rules) combat simulator**: a headless,
pure-Python, deterministic-seeded engine that runs full tactical combats
(initiative, movement on a 2D grid, attacks, spells, concentration,
conditions, reactions, legendary monsters, death saves, short/long rests,
multi-encounter "adventuring days"). Monsters and PCs are played by an AI
decision layer: every candidate action is scored in **eHP** (effective hit
points — expected HP-equivalent value: damage dealt, damage prevented,
enemy actions denied) and shaped by behavioral dials (targeting, ability
selection, action economy, retreat) plus an optimization scale (1 = noob,
5 = optimal). Two product purposes: (1) DMs test whether an encounter
will kill their party; (2) statistically rigorous power/optimization
scoring of character builds via Monte Carlo batches.

Current maturity (verified inventory, not aspiration): ~3,260 tests; all
12 PHB-2024 classes with wired spell lists; 13 subclasses; 168 of 391
spells built; 261 monsters; walls/line-of-effect/vision/zones; a one-way
Foundry-VTT geometry exporter; event-logged runs. **Missing:** backgrounds,
species beyond 4, feats, equipment library, magic items, multiclassing,
character builder UI, any import path, environment templates as data,
hazards/traps, cover derivation, any database/persistence, any web UI,
any Foundry module. Content is authored as schema-validated YAML via
**functional reimplementation** (mechanics only, never source prose);
non-SRD mechanics are modeled from books the owner physically owns.

## 2. The directive being planned

The owner (Phil) directed: pause monster ingestion; complete the **player
character** side — backgrounds, species, feats, equipment, **magic items
and potions** (SRD + PHB + DMG, owned), character-creation rules, full
**multiclassing** with special attention to **Warlock Pact Magic**; build
a **D&D-Beyond-style character creation UI**; an **import path** for
existing characters; **environments** (hazards, traps, cover, corridors,
room sizes, indoor/outdoor) building toward **Foundry VTT** integration
(map import, then watching sims play out graphically); **archive every
simulation event** in a database for statistical analysis; then go
**public** with compute running **on the user's machine** (not cloud) and
consented telemetry growing a central dataset. Stage 4 (an AI DM) is out
of scope, but non-combat data encountered along the way (monster
habitat/treasure, lore, ritual/social features) is captured as **inert
data-layer stubs** for Stage 4 rather than dropped.

## 3. Stage structure proposed by the plan

- **Stage 1 — Complete the PC (CLI-driven):** all PC building blocks +
  creation rules + spell selection + multiclassing (dual slot pools) +
  PC decision-layer fixes. *Exit gate:* any legal 2024 PC L1–20 declared
  in the new spec simulates credibly; golden-build benchmarks pass.
- **Stage 2 — Customization & environments (private):** builder UI,
  importers, room/environment system + generator, Foundry scene import +
  read-only replay module, local SQLite archive with per-run metrics.
  *Exit gate:* build/import a PC in the UI, pick a room, run a Monte
  Carlo batch, watch the replay in Foundry, query the archive.
- **Stage 3 — Public (MVP):** same UI + engine compiled to WebAssembly
  (Pyodide) running fully client-side; SRD-only public content bundle;
  consent-gated telemetry to a small serverless ingest + managed
  Postgres. *Exit gate:* a stranger builds/imports a PC, runs sims in
  the browser, optionally contributes run records.

## 4. Keystone architectural bets (challenge these)

1. **PCSpec v2 as lingua franca.** One schema-validated, versioned PC
   spec consumed/emitted by builder UI, importers, CLI fixtures, archive
   records, Foundry bridge. Multiclass shape: ordered `classes:` list
   (first = first-taken class for saves/armor/L1 hit die). Includes
   ability-generation method, feats, background, species, equipment
   refs, magic items + attunement (cap 3), chosen cantrips/prepared
   spells, HP-mode.
2. **RoomSpec as the environment contract.** Walls, light/obscurement
   zones, hazard zones, traps, difficult terrain, cover objects, spawn
   regions, dimensions. Generators emit it; a Foundry scene importer
   emits it; the engine consumes it. 15 pre-specced environment
   templates become presets.
3. **Import = translation into OUR content registry, never ingestion of
   theirs.** Importers map build *facts* to our IDs; unmapped references
   become explicit fix-up items in the builder (and a demand signal).
   Supported v1 paths: manual entry; **D&D Beyond character-sheet PDF
   upload** (AcroForm field extraction — form fields, not OCR); **Foundry
   dnd5e actor JSON** (user's own export). Explicitly NOT v1: scraping
   DDB shared links or its unofficial character-JSON endpoint (terms-of-
   service posture; parked as a counsel question).
4. **Decision layer as a release gate.** Known pilot defects (from real
   sim post-mortems): the spell-slot opportunity-cost formula is
   *inverted* (a cantrip can outscore Disintegrate in the last fight of
   the day); positioning utility is defense-only (casters hang back and
   plink); no Legendary-Resistance-aware sequencing; Metamagic/maximize
   effects are implemented but never *selected*. Plan: fix these, then
   gate optimization claims on benchmarks — 39 independently published
   build-DPR baselines re-derived through the sim, plus a pure-control
   wizard benchmark.
5. **Archive-first reproducibility.** Every run stamped with a manifest:
   engine git SHA, content-bundle hash, rule bundle, seed, full spec
   snapshot → bit-identical re-runs; aggregation only within
   manifest-compatible cohorts. Local SQLite first; the public ingest
   stores manifest + per-actor aggregate metrics (damage dealt/taken,
   hit %, slots spent by level, healing, control-rounds-denied, outcome
   taxonomy + closeness), not full event streams.
6. **Public compute client-side (Pyodide/WASM)**; the only server is a
   consent-gated ingest endpoint. Submission trust: schema + manifest
   validation, plausibility bounds, rate limits, version pinning, and
   **sampled server-side seed-replay verification** (recompute a random
   subset; determinism makes forgery detectable).
7. **SRD-only public bundle.** The public product bundles SRD content
   only; non-SRD content (PHB/DMG/MM mechanics modeled from owned books)
   never ships in the public bundle — users port their own via import/
   builder entry stored client-side. Whether the public builder may even
   *display* non-SRD names (e.g. as selectable options) is flagged as a
   counsel question, not assumed.
8. **Stage-4 stub discipline.** Non-combat data (monster habitat/
   treasure, background lore, ritual/social features) is captured as
   schema-validated inert fields at authoring time. No engine wiring.

## 5. Workstreams and ordering (compressed)

A. **PC data:** SRD-coverage audit first (know what's free before
   hand-building); schemas for background/feat/equipment/magic-item;
   equipment library; species; feats (origin → general → fighting-style
   → epic boons; mechanically real ones like Great Weapon Master,
   Sentinel, War Caster are engine work); backgrounds (2024: they carry
   the +2/+1 ability bonuses and an origin feat); creation + level-up
   rules as a single validation module the UI and importers both call;
   spell *selection* (prepared/known subsets — today a PC gets every
   spell its class has wired, which breaks both realism and import
   fidelity); magic items & potions (modifier-riding +X items, charged
   items, spell-granting items, potions as a new consumable-inventory
   shape).
B. **Multiclassing:** rules from the book; ordered-classes spec;
   derivation merge (PB by character level, HP across hit dice, feature
   union, per-class resources); multiclass slot table for the shared
   pool; **Pact Magic as a separate slot pool with short-rest recovery**
   (currently simplified to long-rest); **either-pool casting interop**
   (a Sorlock burns pact slots on Sorcerer spells and converts slots ↔
   sorcery points); Mystic Arcanum as per-rest uses, never slots;
   feature-interaction matrix (Extra Attack non-stacking etc.); an
   oracle suite of hand-verified canonical builds (Paladin 2/Warlock X;
   Fighter 2/Wizard X; Sorcerer X/Warlock 2 stress case).
C. **Decision layer:** nova-pacing recalibration (framework-level fix +
   owner sign-off); offensive positioning term; LR-aware sequencing; a
   pre-cast "decoration" chooser (Metamagic/Overchannel/smites); then
   the benchmark gate.
D. **Environments:** RoomSpec; hazard zones + triggered traps; **cover
   derived from geometry** (unblocks Hide, which is deliberately absent
   until cover exists); difficult terrain; parameterized room generator
   with the 15 presets; Foundry scene-JSON import; encounter-opening
   placement policies (parties currently spawn clustered, which one AoE
   punishes).
E. **Builder UI + import:** static SPA, no server, schema-driven; wizard
   flow Class → Origin → Abilities → Equipment → Spells → Review;
   localStorage PC library; the three import paths; an import-fidelity
   harness comparing derived AC/HP/attack/DC against the sheet's printed
   values. v1 imports **2024-rules characters only** — 2014 sheets are
   detected and rejected with a clear message, never silently converted.
F. **Archive:** metric buckets; manifest; SQLite writer wired into CLI +
   batch harness; canned analysis queries; (Stage 3) the ingest service.
G. **Foundry ladder:** buy + pin version → scene import (file-based, no
   API risk) → **read-only replay module** (plays back an event log as
   token movement/HP bars — the "watch it" trust mechanism) → live
   WebSocket observation bridge → full in-VTT UX. Tokens: placeholders
   now; art licensing checked later.
H. **Public:** Pyodide build (engine is already pure-Python/sync/
   no-C-deps by long-standing invariant; browser ≈3–5× slower than
   CPython — Monte Carlo sizing guidance published, heavy studies stay
   local); 2D canvas replay viewer; SRD-only bundle compiler; consent UX;
   counsel checkpoint **before** launch (public + donations is the
   pre-agreed trigger); rate limiting/ops.

Waves: A+B+C (Stage 1) → D+E+F-local+G1-3 (Stage 2) → H+F-ingest (Stage
3), with the SRD audit as the very first task and benchmarks as the
Stage-1 exit gate.

## 6. Model-lane economics (context for feasibility findings)

Execution is split across AI tiers: an architect model (planning/review),
**Opus** (all new schemas, primitives, engine systems, anything touching
the scoring framework, first worked example of each content pattern),
**Sonnet** (high-volume content fan-out against established patterns,
instrumentation, mapping tables, backfills). Protocol rules already in
force: the cheaper lane never decides "new primitive vs reuse" forks and
never touches scoring; full test suite green before every push. Findings
about where this division will mis-execute (e.g., a task that *looks*
like fan-out but hides design decisions) are in scope.

## 7. Legal/sourcing posture (context for legal findings)

Mechanics are treated as uncopyrightable systems (17 USC §102(b)); all
content is functional reimplementation in original words, structured
data only; non-SRD modeled only from books the owner possesses; **no
machine extraction from D&D Beyond or wikis** (ToS line, independent of
copyright); SRD 5.2.1 is CC-BY and freely ingestable; public repo today
already contains non-SRD *mechanical* YAML (interpreted as fine because
mechanics-not-expression — flagged for counsel confirmation at the
public gate); real WotC names kept as internal join keys, nominative use
in analysis assumed legitimate, but *builder display* of non-SRD names
is an open counsel question.

## 8. Data/measurement governance (context for dataset findings)

The sim is one of two sibling projects; the other (Trusight) measures
community reception. Standing rules that bind this plan: no raw dataset
ever crosses between them (summaries only); community prevalence never
silently changes engine defaults (the engine stays RAW-anchored; common
table rulings are an explicit user-selectable bundle); eHP outputs are
disclosed distributions-with-conditions, never pass/fail verdicts; no
automated content-generate→test loop, ever. The public dataset inherits
known biases: self-selected users, weird encounters, optimization levels
all over the dial — the plan's answer is manifest-keyed cohort analysis
rather than naive pooling.

## 9. Performance & scale assumptions (challenge with numbers)

Single encounter ≈ 17 ms CPython / ~50–85 ms browser-WASM; 1,000-run
Monte Carlo ≈ 1–2 min in-browser in a Web Worker; 10k+ runs stay on the
owner's machine. Ingest volume at MVP: tiny (manifest + aggregates ≈ a
few KB/run). SQLite locally; managed Postgres centrally; static hosting
for everything else. No accounts at MVP; consent is per-submission or
per-session.

## 10. Our KNOWN deferrals / assumptions (look PAST these)

Already on our list — find what's *beyond* them:

- 2014 rules entirely unsupported (engine is 2024-only by decision).
- Mounted combat, crafting, Bastions, downtime, non-combat pillars out
  of scope (Stage-4 stubs only).
- Single-point actors (no multi-square Large+ footprints yet); 2D grid
  (elevation is scalar, no true 3D); 8-direction AoE snapping.
- Monster ingestion paused (261 built monsters are the test bestiary;
  ~185 of them still need habitat/treasure stub backfill).
- Spell library at 168/391; remaining spells built on demand, not as a
  gate.
- Subclass coverage at 13; expansion is fan-out work, not novel design.
- Mystic Arcanum modeled as per-rest feature uses; Eldritch invocation
  list partial.
- Tokens are placeholders until late; no art pipeline.
- No user accounts, no collaboration features at MVP.
- Web replay is 2D canvas, not a VTT; Foundry is the rich renderer.
- Counsel engagement is planned at the Stage-3 gate, not before.

## 11. Specific things to stress-test

1. **Multiclass correctness surface.** Where does the ordered-classes +
   dual-slot-pool design break? Sorlock slot↔point conversion loops
   ("coffeelock" infinite-slot exploits), pact-slot smite consumers,
   Paladin/Warlock smite economy across short rests, multiclass
   spell-save-DC/ability selection, prepared-list counts when two
   prepared casters merge, Extra Attack/Unarmored Defense collisions,
   first-class proficiency asymmetries. Which oracle builds are missing
   from the suite?
2. **Creation-rules validator completeness.** What legal-but-weird 2024
   builds would our validator wrongly reject (or wrongly accept)?
   Custom-background rules, ability-score edge cases, feat
   prerequisites, attunement edge cases, equipment-or-gold
   interactions?
3. **Import fidelity failure modes.** AcroForm PDFs: which DDB sheet
   variants (homebrew content, 2014 sheets, multiclass formatting,
   renamed items) silently mis-map? Is "reject 2014 with a message"
   detectable reliably? Foundry actor JSON: schema drift across dnd5e
   system versions?
4. **Decision-layer gate sufficiency.** Is "re-derive 39 published DPR
   baselines + a control-wizard benchmark" actually sufficient evidence
   to publish optimization claims? What benchmark would falsify the
   pilot's competence that this set misses (e.g., resource pacing across
   a day, party synergy, kiting)?
5. **Public-data trust.** Can sampled seed-replay verification be
   defeated (e.g., valid replay, fabricated metrics elsewhere; replay
   cost amplification attacks; version-pinning gaps)? Is the
   manifest-cohort answer to selection bias sound, or does the dataset
   stay unusable for the claims we want?
6. **Legal blind spots.** The SRD-only-bundle + user-port + counsel-at-
   gate posture: what's the riskiest thing we're not flagging? (Builder
   displaying non-SRD names; central storage of user-submitted non-SRD
   mechanics inside run manifests; PDF parsing of DDB exports; donation
   framing.)
7. **Archive schema sufficiency.** Will manifest + per-actor aggregates
   support the statistical products promised (tier lists, difficulty
   bands, dial sensitivity), or do specific analyses require event-level
   data we're choosing not to collect publicly? Schema-versioning and
   migration risks?
8. **Stage ordering.** Is replay-before-live-bridge right for Foundry?
   Is the builder UI correctly placed *after* PCSpec freeze? Should the
   archive land in Wave 1 instead of Wave 2 (every benchmark run is
   currently un-archived)? Is anything on the critical path hiding in
   Wave 3?
9. **PCSpec v2 design.** Will the single-spec-everywhere bet hold under
   homebrew content, partial imports, and version migration — or do we
   need explicit "draft/incomplete" states the schema currently lacks?
10. **Pyodide reality check.** Memory ceilings on phones, cold-start
    bundle size with 600+ content YAMLs, Web Worker + SQLite-in-browser
    interactions, determinism across CPython/WASM (float/RNG identical?)
    — what breaks the "client-side compute" promise first?
11. **Scope traps.** Which workstream most likely balloons (builder UI
    polish? feat engine work? Foundry API churn?) and what's the
    cheapest descope that preserves each stage's exit gate?
12. **What's missing entirely.** A workstream, gate, or failure mode the
    plan never names.
