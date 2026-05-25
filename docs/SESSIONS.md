# SESSIONS.md — D&D Combat Simulator

Running log of key decisions, findings, and open items across AI sessions.  
Add a new entry at the top for each session that produces a non-obvious decision.

---

## Session: 2026-05-25 — Schema design v1 committed

**Participants:** Phil, Claude

**Work done:**
- Sampled SRD CC v5.2.1 across content types: Fighter class + Champion subclass (p47-49), monster stat block format (p254-257), Goblin Warrior (p290), three spells with distinct patterns (Fireball p131, Hold Person p141, Spirit Guardians p164-165), Wizard class + Evoker subclass (p77-82), and all 15 conditions from the Rules Glossary (p177-191).
- Iteratively designed schemas dial-by-dial: class, subclass, feature, monster, spell, condition. Each iteration: read SRD example → draft schema → react/refine → confirm/lock.
- Identified the **unified ability pattern** (Q5 from conditions design): a weapon attack, spell, class feature, monster action, magic item activation are all instances of one schema with different casting semantics. Same primitive library, same execution pipeline.
- Locked the **attack pipeline event vocabulary** (11 events: attack_declared → attack_complete) and the **spell pipeline events** (spell_cast, spell_resolve, spell_end, area triggers, target turn end).
- Locked the **modifier-with-lifetime pattern** — one `attack_modifier` primitive handles Blinded, Shield, Bless, etc. by varying the lifetime parameter, not by having separate primitives per source.
- Locked the **conditions architecture**: definition vs application; absolute vs source_referencing scope; subordinate condition inheritance with reference counting; Petrified `state_transition` as a sui generis primitive; 15 SRD conditions verified directly from PDF including the leveled Exhaustion model.
- Locked the **spellcasting class block**: ability + save_dc_formula + attack_mod_formula + focus_types + preparation_model enum (prepared_from_known_list / spells_known_fixed / prepared_from_class_list / pact_magic) + slots_progression (full / half / third / pact, engine-canonical tables) + ritual_casting style.
- Wrote `docs/architecture/schema-design.md` as the binding architectural commitment for content schema. Companion to pillars-reconciliation.md (which governs the AI behavior layer).
- Created `/schema/` directory structure: definitions/ (6 JSON Schemas + common shared sub-schemas), content/ (sample YAML per type), worksheets/ (gitignored — clean-room audit trail).
- Authored v1 sample content: c_fighter, c_wizard, sc_champion, sc_evoker, 9 features, m_goblin_warrior, sp_fireball, sp_hold_person, sp_spirit_guardians, all 15 conditions.
- gitignore updated to exclude `schema/worksheets/*` (clean-room audit trail kept private).

**Key decisions:**
- **YAML authoring + JSON Schema validation.** Content in YAML for readability/comments; JSON Schema in /schema/definitions/ for tooling.
- **Schema has no rules-text fields by construction.** Clean-room legal enforcement is structural — there is nowhere in the shipped schema to put copied WotC prose.
- **Spell lists are auto-derived views.** Each spell carries `classes:`; the Wizard spell list is a query, not a separate file. No duplication, no drift.
- **Slot progressions are engine-canonical.** Four standard tables (full / half / third / pact) live as engine constants; classes reference by name. Eliminates 12-class duplication.
- **`source:` field on every entry.** srd_5.2.1 / phb_2024 / user_authored / homebrew. Documentation tag with no licensing implication.
- **File naming convention:** type-prefixed snake_case (c_*, sc_*, f_*, m_*, sp_*, co_*).
- **Primitive library lives in `/schema/primitives/`** but the Python handler implementations are deferred to engine skeleton work. The schema commits today specify what primitives exist; the engine PR implements them.

**Open items carried forward:**
- [ ] Engine skeleton: event bus, handler interface, contract enforcement, reaction-cascade termination guard, primitive library implementation (Python).
- [ ] Schema validation tooling: YAML loader + JSON Schema validator for content files.
- [ ] Content expansion: ~11 remaining classes, ~23 remaining subclasses, ~300 monsters, ~300 spells, equipment / weapons with Mastery (2024 rules), magic items, backgrounds, species, feats. Each is parallel iterative work, no architectural new design.
- [ ] Half caster (Paladin), pact magic (Warlock), prepared_from_class_list (Cleric, Druid) sampling to validate the spellcasting block against all four preparation models.
- [ ] Equipment schema sampling — weapons with Mastery properties (2024 rules), armor with stealth disadvantage, etc.

---

## Session: 2026-05-25 — `pillars-reconciliation.md` drafted + cadre red-team amendments

**Participants:** Phil, Claude, plus AI cadre (Gemini, ChatGPT, Perplexity) for red-team review

**Work done:**
- Dial-by-dial design conversation: Retreat, Ability Selection, Targeting, Action Economy (each ~5 named presets as parameter bundles; same shape across all four).
- Designed the three execution modes (Strict RAW / Rules + Behavior + eHP / Behavior Engine) with explicit UX treatment to defeat the gradient-bias trap (comparison strip, use-case-framed wizard, inline warning, default selection).
- Resolved open question #3 (RP Constraints as separate filter/scoring system, 3 categories, library).
- Resolved open question #4 (per-type + faction + per-instance three-level inheritance; `reason:` split from `suppress_hints:`).
- Resolved open question #5 (Sanity Hints reframe — not "validation"; honest about being hints not correctness).
- **Cadre red-team round** on the three open-question resolutions (NOT the four dials — those had been iterated heavily with Phil's DM input). Standardized adversarial prompt; three independent runs. Six 3/3 convergent CRITICAL findings:
  1. Severity-as-probability destroys Monte Carlo convergence
  2. Constraint conflict resolution underspecified (deadlocks possible)
  3. Pipeline ordering mathematically incoherent (weighted prefs post-hoc)
  4. Validation system structurally insufficient (small library + suppression bypass)
  5. `reason:` field overloaded as global mute
  6. Mode-aware validation desync
- Six amendments adopted; one additional (three-level inheritance / faction layer) adopted from a 2/3 convergent finding.
- `docs/foundations/pillars-reconciliation.md` drafted incorporating all amendments. Replaces the 2026-03-30 stub.
- **Same-day reconsideration: polymorph + runtime override layer promoted from follow-on to fully specified.** Initial categorization deferred them as "architect-for, defer-detail" but the cadre had actually flagged them as CRITICAL (Gemini explicitly; ChatGPT and Perplexity on the polymorph variant). Frequency check (Druid Wild Shape as a core class identity feature available from level 2; Polymorph/Shapechange/True Polymorph as common combat tools across levels; the runtime-override class of conditions — Frightened/Dominate/Confusion — appearing constantly in real play) confirmed these are core gameplay, not edge cases. Promoted to full specification at §4.2 (Form Transition Model with `retains_mind` flag covering the Polymorph-vs-Shapechange mental-stat distinction) and §4.3 (Runtime Overrides with four primitive override types). Per-effect implementation specs (Wild Shape HP rules, Frightened save cadence, etc.) remain follow-on — they live in spells/conditions docs, not pillars-reconciliation.

**Key decisions:**
- The pillars are not in opposition; they answer different questions at different layers. Resolution is a multi-axis dial system, not per-conflict binary policy.
- Unified actor-behavior model — monsters AND PCs share the same BehaviorProfile.
- Severity is a continuous score weight in the eHP pipeline, NOT a probability — preserves Monte Carlo determinism.
- Decision pipeline follows the Utility AI single-scoring-stage pattern (all considerations baked into one coherent scoring pass; no post-hoc patching).
- Constraint composition has explicit priority tiers (Hard Filter > Forced Choice > Weighted Preference) with guaranteed-legal fallback (Dodge for PC, Pass for monster) to prevent engine deadlock.
- Three-level inheritance: archetype → faction → instance.
- `reason:` and `suppress_hints:` are separate fields with separate semantics (documentation vs control). ESLint precedent for per-rule suppression.
- "Sanity Hints" framing (not "Validation") with explicit "absence of hint ≠ correctness" disclaimer.
- Hint rules cross-reference dial choices against actual stat-block capabilities (statblock-aware hints).
- Mode-relevance lives in hint text, not in firing-vs-not-firing logic — same configuration produces same hints across all modes.
- Cadre red-team established as a recurring discipline for substantive architectural design (this is the second productive run; May 17 validation-oracle was the first).

**Follow-on items carried forward (architecturally reserved; not MVP):**
- [ ] Runtime override layer for conditions (Frightened, Dominate Person, Confusion) — schema slot reserved in `BehaviorProfile.runtime_override`.
- [ ] Polymorph / transformation as state transition (current_form vs underlying_identity pair).
- [ ] Phase-shift constraints (Bloodied → drop pacifism; mythic phases).
- [ ] Temporal memory / stateful constraints (track "already healed this turn").
- [ ] Dynamic / post-hoc validation (observation-based hints after Monte Carlo runs).
- [ ] Alternative archetype "style" baselines (Ammann is one author's interpretation).
- [ ] Faction profile library expansion (ship initial small set; grow organically).
- [ ] Per-creature default `BehaviorProfile` assignments for the 300+ creatures Ammann covered (not yet ported into our doc; only the ~6 archetypes are encoded).
- [ ] Schema design for subclass / spell / feat / monster definitions (originally next-after-pillars; now next-after-pillars).
- [ ] 5e API → schema transform pipeline.

---

## Session: 2026-05-24 — Un-stalling + Hybrid monetization + asset inventory

**Participants:** Phil, Claude

**Work done:**
- Discovered an unrelated YT-transcript POC (in sibling `dnd-trends-index` repo) had produced 224 Treantmonk transcripts already entity-extracted (`~/yt_poc_data/treantmonk/`), including the methodology video `nLXbEFurCU4` that sourced the `pc-dpr-baselines.md` engine.
- Inventoried pre-existing content artifacts across both repos and BigQuery (work previously done via Antigravity):
  - `dnd-trends/1_raw/` — index dump from `dnd5eapi.co` (334 monsters, 319 spells, 407 features, 237 equipment, 362 magic items, 12 classes, 9 races, etc.). **Names + URLs only, not full mechanical content** — the actual stat-block/feature/spell text still has to be fetched from the API.
  - `dnd-trends/game_registry/` — Trusight-side metadata SQL (`01_schema.sql` + `02_populate.sql` + `03_verify.sql`); 48-subclass registry populated in BigQuery 2026-05-19. Deliberately facts-only by legal-firewall design (no mechanical text).
  - `dnd-trends/cloud_functions/monster_classifier/` — Trusight-side tagger.
  - This repo: **zero content files** confirmed. All current work is the 8 docs in `docs/`.
- Confirmed `pillars-reconciliation.md` (1.5KB stub) is the genuine blocker per this repo's own CONTEXT line 71 — separate from CONTEXT/SESSIONS being stale.
- CONTEXT.md / SESSIONS.md refresh (this commit) — propagates the May architecture-spine work into this repo per the spine doc's §7 propagation TODO.

**Key decisions:**
- **Hybrid monetization (Stage 3+).** Sim ships SRD content bundled (CC-BY, free to redistribute with attribution). Non-SRD content arrives via user-supplied port (typed-in via schema-validated form, or imported from where the user already licensed it — DDB/Roll20 export). Sim **never** ships non-SRD content. Rejected: DDB/Roll20-style licensed-reseller model (requires a WotC license).
- Treantmonk DPR per-level numbers re-categorized from "source data" to "validation reference data" — the 7-step methodology encoded in `pc-dpr-baselines.md` (lines 44–218) is sufficient for the sim to compute DPR for any new build. Treantmonk's 5 verified per-level tables (Fighter ×3, Zealot Barb, Berserker Barb) serve as cross-validation reference. More tables nice-to-have, not blocking.
- `dnd5eapi.co` is the canonical ingestion path for bundled SRD content. Pipeline: fetch → clean-room transform into Tier-1/Tier-2 schema → store as bundled assets in this repo.
- Project name shift in all docs: `Arcane Analytics` → `Trusight`.

**Open items carried forward:**
- [ ] Draft `pillars-reconciliation.md` — needs Phil's policy input on Math-Wins / Behavior-Wins / Weighted-Blend per conflict class (targeting, retreat, ability selection, action economy). NEXT substantive design step.
- [ ] Design schema for subclass / spell / feat / monster definitions (after pillars-reconciliation lands). Two-tier: declarative effect-primitives + custom-handler escape hatch (MtG card-scripting pattern). Each effect carries the §Config read/write/event/scope contract.
- [ ] Build 5e API → schema transform pipeline.
- [ ] Extract spellcaster DPR methodology from `nLXbEFurCU4` transcript when engine reaches spellcaster scoring (currently encoded methodology is martial single-target only).

---

## Session: 2026-05-18 — Legal posture resolved + `game_registry` built (sibling repo)

**Participants:** Phil, Claude

**Work done (cross-project, primarily in `dnd-trends-index`):**
- Resolved the legal posture for sim mechanics + public eHP reports. Settled findings:
  - **Names are NOT the control. Clean-room + sourcing are.** Anonymizing real names solves a non-problem and actively costs registry/reception join-ability. Keep real names internally; private real-name↔id map.
  - **Publishing comparative eHP reports of named subclasses is legitimate and precedented** — decade of Treantmonk / Tabletop Builds / RPGBOT doing exactly this commercially, by name, untouched by WotC. Public distribution doesn't remove the activity's legitimacy; it re-ranks the controls (trademark goes from dormant to live → nominative-fair-use posture + disclaimer required).
  - **The new risk is strategic, not legal: pitch tone.** Every public report frames as neutral measurement, never "WotC got this wrong."
- `game_registry.subclasses` BigQuery table built and populated with 48 PHB-2024 subclasses (4 per class × 12 classes; all `is_current_canonical=TRUE`; all `is_srd=FALSE` deliberately under-claiming).
- Diagnostic JOIN proven: 48/48 subclasses match `concept_library`; 0/48 match `reddit_reception_proxy` (the informative result — empirically confirms subclass-level reception tagging is genuinely net-new).
- `vocabulary_lexicon` companion table established as 4th firewall layer (vocabulary). Makes the internal-vs-deliverable vocabulary discipline checkable, not advisory.

**Key decisions:**
- Combat-sim mechanical content (full stat blocks) stays separate from Trusight metadata (facts/JOIN keys): different copyright profiles → different stores.
- `is_srd=FALSE` for all 48 PHB-2024 subclasses (conservative; SRD-5.2 coverage unverified; safest stance with WotC as the prospect).
- For-profit pivot is the explicit escalate-to-real-counsel trigger.

**Open items carried forward:**
- [ ] Propagate the May architecture-spine work into this repo's CONTEXT/SESSIONS (DONE: 2026-05-24 session).
- [ ] Sharpen the "SRD/Open5e only" wording so a future session cannot misread it as a content cap on the sim. (DONE: spine doc 2026-05-20.)

---

## Session: 2026-05-17 — Architecture spine established (Trusight ↔ combat-sim)

**Participants:** Phil, Claude

**Work done (cross-project strategic design; stored in project memory as `project_rules_substrate_architecture.md`):**
- Established the load-bearing architectural spine governing the cross-project relationship.
- Codified the **epistemic-inversion principle** (3 layers: config / execution / measurement). Sim *enumerates-then-selects*; Trusight *measures-never-selects*. The Wish boundary (non-enumerable rules) proves the principle — what breaks the sim is what maximally feeds Trusight.
- Codified the **5-component Trusight feature-intelligence decomposition** (registry / reception tags / lore-resonance / structural taxonomy / translation patterns).
- Codified the **dual-axis through-line** (every Trusight surface is dual-axis; single metric is always the trap).
- Codified the **§Config locked design conditions** (5 cadre-confirmed conditions for engine implementation — see CONTEXT § §Config Locked Design Conditions).
- Codified the **validation-oracle relationship** (§5, 5 conditions — see CONTEXT § Validation-Oracle Rules). Corrected an earlier framing that "summary-only firewall = safe"; coarse verdicts ARE an optimization gradient, so summary signals are necessary-but-radically-insufficient.
- Codified the **11 eHP limitations** with the dissolution analysis: ~7 of 11 dissolve under full turn-by-turn simulation; residual ~4 are inherent conditionality + scope. Strengthens the architecture — gives §5 condition 1 (distributions-with-conditions, never scalars) and §4 (dual-axis) their real foundation.

**Key decisions (binding on this repo):**
- **Direction B is SEVERED.** Community-prevalence → sim-default-ruling channel is forbidden. The sim stays RAW-anchored, period.
- **eHP is a disclosed input axis, never a gate.** No binary balanced/not-balanced verdicts.
- **No automated generate→test loop, ever.** Architectural prohibition.
- **Rule Bundles** (`RAW` / `Common-Table` / `Strict`) are the UX surface — never hundreds of raw toggles.
- All `pillars-reconciliation.md` work and all subsequent engine code must reference the §Config conditions.

**Open items carried forward:**
- [ ] Reconcile this repo's CONTEXT/SESSIONS frozen at 2026-03-30 + pillars-reconciliation stub (DONE for CONTEXT/SESSIONS: 2026-05-24; pillars-reconciliation still open as next step).
- [ ] Add the firewall rule + a pointer to the spine doc into this CONTEXT.md (DONE: 2026-05-24).
- [ ] Record the roadmap re-prioritization rationale (Phase 3 up, validation-oracle ROI driven) (DONE: 2026-05-24 — see CONTEXT § Build Phases).

---

## Session: 2026-04-01 — DPR data work (martial classes)

**Participants:** Phil, Claude

**Work done:**
- Produced `treantmonk-damage-rankings.md` from Treantmonk's videos 19–23: scoring formula verified (`T1×1 + T2×3 + T3×2 + T4×1`), career scores + per-tier breakdowns for all 39 builds, 2024 baseline confirmed = Warlock Base Blade Pact Greatsword (C tier all four tiers, career 196).
- Produced `pc-dpr-baselines.md` methodology section from video 1 ("How to Calculate Damage in D&D 2024"): target AC scale (~60% baseline hit chance), 7 explicit calculation steps with Python — normal attack damage, studied-attacks formula, crit-bonus separation, second-attack-without-modifier shortcut, sneak-attack probability across multiple attacks, sneak-attack crit probability, advantage math, full DPR assembly.
- Verified per-level DPR tables from screenshots for 5 builds: Fighter Base Longsword + Fighter Base Greatsword + Sword-and-Shield Fighter + Zealot Barbarian Longsword + Berserker Barbarian Longsword.
- Commits: `354ce2c`, `6ae31f7`, `74edf29`, `b416c24`, `6091187`.

**Key decisions:**
- Treantmonk's 60% baseline hit chance vs the Finished Book's 65% is **not** a pillar conflict; they serve different purposes (per-class DPR calibration vs encounter XP). Formal resolution belongs in `pillars-reconciliation.md` (when drafted).
- Conjure Minor Elementals flagged as outlier (~80 DPR upcasted; "way above everything else") — engine flag required, DM override toggle (per `conditions-and-edge-cases.md`).
- Subclass selection becomes **mandatory** for T4 encounter accuracy — Barbarian and Paladin fall to D-tier at T4 without a damage subclass.

**Open items carried forward:**
- [ ] Per-level DPR tables for the remaining 34 builds. Re-categorized 2026-05-24 from "source data" to "validation reference data" — not blocking (sim computes its own DPR from encoded methodology); useful for cross-validation when ready.
- [ ] Spellcaster DPR methodology extraction (Treantmonk videos 11, 12, 13, 14, 15, 16, 18) — needed when engine reaches spellcaster scoring.

---

## Session: 2026-03-30 — Project Initialization

**Participants:** Phil, Claude

**Work done:**
- Evaluated Gemini's initial project framing (applied research / model-driven architecture). Assessment: solid on project management framing, weak on domain-specific technical due diligence.
- Identified The Finished Book and Keith Ammann's TMKWTD as the two foundational pillars.
- Established `/docs` folder structure and docs-as-code approach in GitHub repo.
- Rejected GitHub Wiki in favor of `/docs` in-repo (rationale: disconnects from code on Wiki, no version control parity).
- Rejected Cowork as project management tool (rationale: designed for file/task automation, not multi-AI architectural workflow; adds unnecessary tool layer).
- Completed full live-site audit of The Finished Book (all articles across Theory, Classes, Monsters sections as of March 2026).
- Produced `finished-book-summary.md` — covers all 20+ articles including six gaps missed by Antigravity/Perplexity in prior draft: Encounter Multiplier (full derivation), XP Approximations (three tiers), PC-side XP and daily economy, Magic Items as encounter variables, Variability series (full statistical layer), and 2024 rules EM change.
- Created GitHub repo: https://github.com/MarsBoundJ/dnd-combat-simulator
- Repo is public. `.gitignore` uses Python template + manual additions for GCP credentials, `.env`, Foundry `.db` files, and `node_modules`.

**Key decisions:**
- Exponential XP formula (`1.077^(AC+AB-15)`) chosen as engine truth over linear and published-monster approximations.
- 2024 rules: encounter multiplier defaults to 1.0 when using published 2024 XP values.
- Conditions resolved through eHP/eDPR adjustments, not ad-hoc damage modifiers.
- EV mode vs Sampled mode must never be mixed in the same encounter run.
- No engine code written until `pillars-reconciliation.md` is complete.

**Open items carried forward:**
- [ ] Draft `ammann-behavior-framework.md` — next priority (DONE — Mar 31).
- [ ] Draft `pillars-reconciliation.md` — blocked on Ammann doc (still open as of 2026-05-24).
- [ ] Decide: MCTS vs rules-based for monster AI (still open).
- [ ] Decide: data source for monster stat blocks (DONE — Open5e API; see 2026-05-24).
- [ ] Decide: Foundry VTT version to pin (still open).
- [ ] Decide: 2014 rules, 2024 rules, or both? (DONE — 2024; see 2026-05-24.)

---

<!-- Template for future sessions:

## Session: YYYY-MM-DD — [Short title]

**Participants:** Phil, [AI collaborators]

**Work done:**
- 

**Key decisions:**
- 

**Open items carried forward:**
- [ ] 

-->
