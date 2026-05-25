# CONTEXT.md — D&D Combat Simulator

**Paste this file at the start of every AI session on this project.**  
Last updated: 2026-05-25

---

## What This Project Is

A locally-run D&D 5e combat simulation engine that DMs use to test and tune
encounters, score class/subclass power, and run statistically rigorous
multi-encounter days — with Foundry VTT as the interactive front end for
visualizing and manually adjusting combat.

This is a solo project by Phil (GitHub: MarsBoundJ). The AI collaborator team
is Claude (architect/reviewer), Antigravity (execution agent), and
Gemini/Perplexity (research/validation).

---

## Two Intellectual Pillars

All engine logic must trace back to one or both of these pillars. Conflicts
between them are resolved by `docs/foundations/pillars-reconciliation.md`.

**Pillar 1 — The Finished Book**  
Physics-based mathematical framework by Tom Dunn.  
Source: https://tomedunn.github.io/the-finished-book  
Encoded in: `docs/foundations/finished-book-summary.md` ✅ Complete

**Pillar 2 — The Monsters Know What They're Doing**  
Behavioral monster decision-making framework by Keith Ammann.  
Source: https://www.themonstersknow.com  
Encoded in: `docs/foundations/ammann-behavior-framework.md` ✅ Complete

**Unifying Framework — eHP Action Framework**  
Every action (damage, healing, buff, debuff, control, movement denial) is
quantified as Offensive eHP + Defensive eHP − Opportunity Cost. This is the
AI's evaluation function.  
Encoded in: `docs/foundations/ehp-action-framework.md` ✅ Complete

---

## Primary Use Cases

1. **DM Encounter Lab** — Test and tune encounters before running them at the
   table. Single encounter simulation with outcome report. Multi-encounter days
   with dynamic difficulty adjustment.

2. **Class/Subclass Power Scoring** — Run Monte Carlo simulations to produce
   statistically rigorous Positive/Negative eHP power numbers for classes,
   subclasses, and homebrew designs. Scientific tier list generation.

---

## Cross-Project Architecture

This sim is one half of a two-project architecture. The other half is
**Trusight** (the `dnd-trends-index` repo) — a separate intelligence /
measurement platform. The two have **opposite epistemic stances** toward the
same source material: the sim *enumerates-then-selects* (collapses to one
ruling per run); Trusight *measures-never-selects* (records distributions of
how the community rules).

Load-bearing architectural decisions governing the cross-project
relationship — firewall layers, validation-oracle rules, §config engine
conditions, legal posture, monetization architecture — live in an internal
**architecture spine** document (project memory:
`project_rules_substrate_architecture.md`). The engineering rules below are
extracted from that spine for in-context use during sim development; the
spine itself owns strategic context.

---

## Firewall Rules

Four firewall layers govern what crosses between Trusight and this sim:

1. **Epistemic** — Trusight records distributions-with-sentiment; the sim
   collapses to one ruling per run. A Trusight-flavored rules dataset is
   poison in the sim engine.
2. **Data** — No raw dataset crosses, ever, in either direction. Only
   summary signals (and even those are gated by the Validation-Oracle Rules
   below — summary signals alone are necessary but radically insufficient).
3. **Legal** — Game mechanics are not copyrightable (17 USC §102(b); *Baker
   v. Selden*). The sim implements all subclasses (SRD + non-SRD) via
   **clean-room functional reimplementation** in our own data model — no
   transcribed WotC prose. *"SRD/Open5e only"* is a **sourcing rule**
   governing ready-made-text ingestion, NOT a cap on which subclasses the
   sim may model. Real names kept internally with a private real-name↔id map.
4. **Vocabulary** — 4e-derived terms (Arcane/Divine/Primal source axis;
   Striker/Defender/Controller/Leader roles; optimizer jargon like
   "Striker/Brute") are internal-evaluation-only. Translate before any
   external-facing surface.

**Monetization architecture (Stage 3+):** Hybrid model. The sim ships SRD
content bundled (CC-BY, free to redistribute with attribution); non-SRD
content arrives via user-supplied port (typed in via a schema-validated
form, or imported from where the user already licensed it — DDB / Roll20
export). The sim **never** ships non-SRD content. Monetization is on the
engine/analysis, not on content distribution. We do NOT pursue a
DDB/Roll20-style licensed-reseller model (would require a WotC license).

---

## §Config Locked Design Conditions

The combinatorial-config viability of bounded-parameter rulings is
conditional on all 5 of these (cadre-confirmed; no engine code lands
without them):

1. **No flat switches.** Rulings = event-driven handlers / policy-objects,
   each with an explicit declared **read-set / write-set /
   event-subscription / applicability-scope** contract. (Event-bus /
   interceptor pattern, borrowed from digital-MtG engines.)
2. **Static dependency graph maintained.** Two rulings interact iff one
   writes state the other reads, OR both write the same state, OR both
   feed the same oracle output metric (eHP / hit-probability /
   action-availability) — the third "output-interaction" edge is necessary;
   pure data-flow analysis misses it.
3. **Test per connected-component**, not globally. Reserve 3–4-way (NIST:
   sometimes 4–6-way) testing for known dense hubs: **movement /
   forced-movement / reach / cover / opportunity-attacks / reactions /
   action-economy**.
4. **Reaction-cascade termination guard** (hard correctness constraint).
   D&D reactions trigger reactions (Mage Slayer → Shield → Counterspell).
   Without a reaction stack + strict "once per turn / once per trigger"
   severing, the simulator infinite-loops.
5. **UX layer separated from engine layer.** Never expose hundreds of raw
   toggles. Expose **Rule Bundles**: `RAW` / `Common-Table` / `Strict`.
   The `Common-Table` bundle is exactly where Trusight's measurement layer
   feeds back into the user-facing layer (community-prevalence informing
   what "most tables do") — but it never silently mutates the engine
   baseline; see Validation-Oracle Rules condition 3.

---

## Validation-Oracle Rules

The sim's outputs eventually feed Trusight reports (internal at Stage 1,
public at Stage 2+) as **one of two analytical inputs** alongside
community-reception measurement. The relationship is ONE socio-technical
decision surface with two analytical inputs and one human arbiter — govern
it as one thing. Strict conditions:

1. **eHP is a disclosed input axis, never a gate / filter / verdict.**
   Outputs are distributions with named conditions, never scalars. The
   interface presents eHP *as Dunn derived it* — opponent-dependent, with
   the approximation band — never context-free.
2. **No automated generate→test loop, ever.** Architectural prohibition,
   not guideline. Auto-iterating proposals against oracle verdicts =
   guaranteed Goodhart collapse (sterile, homogenized, "balanced but dead"
   content; system trained to argue against fun).
3. **Direction B is SEVERED.** Community-prevalence → sim-default-ruling
   is forbidden. The sim stays **RAW-anchored, period.** "What real tables
   do" may appear in Trusight's reporting *to humans*, and in the
   `Common-Table` UI bundle as a user-selectable preset; it must never
   silently mutate the normative engine's baseline.
4. **Singular pre-assigned human arbiter** owns every math-vs-sentiment
   conflict and records written rationale. Without this, both systems
   become political shield-weapons.
5. **eHP-as-gate is structurally misaligned with "good D&D"**, not merely
   incomplete (Twilight Cleric / "balanced but dead" / commercially-loved
   but mathematically-overtuned like Hexblade). Making eHP a binary gate
   actively *selects against* the asymmetric/thematic/utility designs that
   are commercially best.

**On the 11 eHP limitations** (Action-economy blindness, Hard-control
bypass, Burst-vs-sustain, Opponent-dependence, AC-vs-saves aggregation,
Kiting/positional, Yo-yo HP, Adventuring-day pacing, Party-synergy
invisibility, Non-combat utility, Player-skill ceiling): ~7 of 11
**dissolve** under a full turn-by-turn simulation — they were critiques of
*static / manually-computed* eHP. The residual ~4 are inherent
conditionality (#4, #8, #11 — output is conditional on a named parameter,
simulation makes the parameter explicit but cannot eliminate it) and scope
(#10 non-combat utility — a combat sim is permanently silent there; a
boundary, not a computation gap). The sim handles #10 via *imported expert
utility ratings* as a disclosed input axis, never sim-computed.

**Two technical riders:**
- Control-eHP variance is dominated by the **enemy-behavior model** (Ammann
  pillar), not dice. Reports must condition on a named enemy-behavior
  profile.
- Control payoff is **convex / threshold-shaped**. Closed-form EV
  understates it systematically; **Sampled / Monte-Carlo mode is MANDATORY**
  for control (the canonical case behind the "never mix EV and Sampled
  modes" rule).

---

## Current Project Status

| Document | Status |
|---|---|
| `finished-book-summary.md` | ✅ Complete |
| `ammann-behavior-framework.md` | ✅ Complete |
| `ehp-action-framework.md` | ✅ Complete |
| `environment-system.md` | ✅ Complete |
| `engine-design.md` | ✅ Complete |
| `data-sources.md` | ✅ Complete |
| `pc-dpr-baselines.md` | ✅ Methodology complete (7-step DPR engine encoded). Per-build per-level tables verified for 5/39 builds (Fighter ×3, Zealot Barb, Berserker Barb) — remaining 34 are re-categorized as *validation reference* data (not source); the sim computes its own DPR from the encoded methodology. |
| `treantmonk-damage-rankings.md` | ✅ Complete — career scores + per-tier breakdowns for all 39 builds |
| `pillars-reconciliation.md` | ✅ Complete (2026-05-25) — unified BehaviorProfile resolution; 3 modes; 4 dials with preset bundles; RP Constraints; 3-level inheritance; Sanity Hints. Cadre-red-team-hardened. |
| `docs/architecture/schema-design.md` | ✅ Complete (2026-05-25) — content schema architecture: unified ability pattern, event vocabulary, primitive library, conditions as first-class entities, spellcasting block, clean-room two-document split. |
| `/schema/` (definitions + content) | ✅ v1 — JSON Schemas for 6 entity types + sample content (Fighter, Wizard, Champion, Evoker, 10 features, Goblin Warrior, 3 spells, all 15 conditions). |
| `combat-state-model.md` | 🔴 Not started |
| `conditions-and-edge-cases.md` | 🔴 Not started |
| `foundry-integration.md` | 🔴 Not started |
| `ai-decision-layer.md` | 🔴 Not started |
| Engine skeleton | ✅ Phase 1 v0 (2026-05-25) — library-first Python; `engine/` package; CLI (`python -m engine`); smoke test (Fighter vs Goblin) passes; JSON report output. |
| Primitives v1 | ✅ (2026-05-26) — 13 primitives now implemented (was 5). Q5 unified modifier system live in `engine/core/modifiers.py`; conditions actually affect gameplay (Blinded gives attackers advantage; Paralyzed auto-fails STR/DEX saves; etc.). `forced_save` + `recurring_save` for spells; `multiattack` for higher-CR monsters. See `engine/README.md`. |
| AI decision layer v1 | ✅ (2026-05-26) — Targeting dial fully implemented (`engine/ai/`): all 5 presets (`closest_enemy`, `weakest_target`, `most_dangerous`, `caster_first`, `optimal_ehp` graceful fallback), behavior_profile resolution with archetype defaults, universal finish-off rule. Goblins now bully wounded PCs; pack hunters target the dangerous fighter; apex predators target casters. Wired into `pipeline.score_candidates()`. |
| Offensive eHP scoring v1 | ✅ (2026-05-25) — `engine/ai/ehp_scoring.py`. Replaces +10/+5 preset preferences with `expected_damage × hit_probability × aggression_coefficient`, with preset preferences as small tie-break bonuses. AI now exploits conditions organically (Blinded target → advantage → higher hit_prob → higher score, no special-cased logic). `tactical` ability preset works for real — picks highest-EV action against the chosen target. Overkill capped at target HP; per-archetype aggression in [0.8, 1.5]. PR #7. |
| Defensive eHP scoring v1 | ✅ (2026-05-25) — `engine/ai/defensive_ehp.py`. Adds healing (desperation-weighted, missing-HP-capped), defensive buff (AC bonus + disadvantage-for-attacker via `worst_enemy_DPR × Δmiss × 2.5 rounds`), and hard control (`forced_save → apply_condition` recognized; `enemy_DPR × p_fail × 2.5 rounds × denial_fraction`; hard conditions score 1.0, partial conditions 0.2–0.5). Candidate generator extended to emit heal/buff candidates per ally + control candidates per enemy. New cleric-heals-dying-ally fixture proves end-to-end: cleric's first action is `healed → fighter_dying +10` (NOT a mace attack). 103 tests pass (4 smoke + 12 primitives_v1 + 19 ai_v1 + 34 ehp_scoring + 34 defensive_ehp). PR #8. |
| Engine capabilities checkpoint | ✅ (2026-05-25) — `docs/engine-capabilities.md`. Reader-facing summary of what the engine can demonstrate today (decision pipeline status per step, eHP framework coverage map, behavioral worked examples, test surface, honest roadmap gap list). |

**Current phase:** Engine skeleton (Phase 1 v0) landed 2026-05-25, followed by
4 substantial PRs on the same day: primitives v1 (#5), targeting dial v1 (#6),
offensive eHP v1 (#7), defensive eHP v1 (#8). The AI now drives a real
5-step Ammann + eHP hybrid decision per `pillars-reconciliation.md` §7 —
both offensive (attack/multiattack) and defensive (heal/buff/control)
candidates score on a single eHP scale, and the cleric-heals-dying-ally
fixture demonstrates the AI choosing Cure Wounds over a mace attack
end-to-end. 13 primitives implemented; ~30 stubbed.

**See `docs/engine-capabilities.md` for the full reader-facing capability
checkpoint** — behavioral worked examples, decision-pipeline status per
step, eHP framework coverage map, and the honest roadmap gap list.

**Next substantive steps** (parallel, prioritize per use case):
1. **Action Economy dial** — per-slot stochastic between optimal-vs-default
   (signature_bonus / tactical_bonus / OA reaction / sophisticated reaction
   tiering per §5.4). Self-contained PR on `engine/ai/action_economy.py`.
2. **Retreat dial** — DMG p48 algorithm + 3 modes + 5 presets per §5.1.
   The `cowardly_skirmisher` archetype already declares `retreat: cowardly`
   but it's a no-op until this lands.
3. **RP Constraints** — Hard Filter / Forced Choice / Weighted Preference
   per §6. Currently `apply_hard_filters` and `apply_forced_choices` are
   stubs.
4. **Positioning / movement / reachability** — biggest missing axis;
   unblocks `closest_enemy`, OAs, ranged-vs-melee, soft control.
5. **Phase 2 Foundry bridge** — when Stage 2 timing is right. Thin JS module that
   uses the engine in observation mode + the schema as translation target.
6. **Content expansion** — remaining ~11 classes / ~23 subclasses / ~300 monsters /
   ~300 spells / equipment / magic items / backgrounds / species / feats. Parallel
   iterative work; schemas are stable.

---

## Known Assets

External and sibling-repo resources the sim will consume; documented here
so future sessions don't re-discover them.

- **`dnd5eapi.co`** — CC-BY SRD content (334 monsters, 319 spells, 407
  features, 237 equipment, 362 magic items, 12 classes, 9 races, 38 traits,
  15 conditions, etc.). The ingestion path for bundled SRD content under
  the Hybrid monetization model.
- **`dnd-trends/1_raw/`** (sibling repo) — Existing inventory of every SRD
  entity (names + URLs to the 5e API). Tells the sim exactly what to fetch
  during the ingestion pipeline build.
- **`dnd-trends-index.game_registry.subclasses`** (BigQuery, sibling
  project) — 48-row registry of all PHB-2024 subclasses with `lineage_id`,
  aliases, `lifecycle_status`, `is_srd`. The JOIN target for sim outputs
  feeding Trusight reports (Stage 1+).
- **YT transcripts** — 224 Treantmonk videos (June 2024 → May 2026)
  transcribed + entity-extracted on local disk
  (`~/yt_poc_data/treantmonk/`). Includes "How to Calculate Damage in D&D
  2024" (video id `nLXbEFurCU4`) — the verbal source for the DPR
  methodology encoded in `pc-dpr-baselines.md`. Likely also contains
  spellcaster-DPR methodology not yet extracted.

---

## Key Architectural Decisions Made

1. **Docs-as-code** — all documentation lives in `/docs` in the repo.

2. **Headless engine** — Python engine has no UI dependency. Foundry module
   is a bridge only. ~300–500 lines of JavaScript.

3. **XP formula** — exponential approximation (`1.077^(eAB-4 + eAC-12)`)
   is the engine's internal truth. 2024 rules use no encounter multiplier.

4. **Variability modes** — EV (expected value) mode for AI decisions;
   Sampled mode for Monte Carlo. Never mixed in the same encounter run.

5. **Condition policy** — conditions resolved through eHP/eDPR adjustments.
   Targeting decisions governed by Ammann pillar.

6. **eHP Action Framework** — unified evaluation function for all action
   types. Every action scores as: offensive_ehp + defensive_ehp −
   opportunity_cost, weighted by behavioral coefficients.

7. **Environment system** — `EnvironmentTemplate` is the stable interface.
   Engine always receives a template object regardless of source (named
   registry, custom DM sliders, Foundry scene data, or AI map analysis).
   Infinitely extensible without touching engine code.

8. **Phase 1 scope** — single encounter simulation + outcome report +
   environment templates. Web app, hosted infrastructure, and AI map
   analysis are later phases.

9. **Data sources** — Open5e / 5e API for Phase 1 development/testing.
   Foundry runtime data for Phase 2. **No copyrighted WotC content in the
   repo** — clean-room reimplementation for non-SRD; CC-BY-attributed SRD
   text where it's bundled.

10. **AI decision layer** — MCTS vs rules-based not yet decided. See
    `ai-decision-layer.md` (not yet drafted).

11. **Hybrid monetization (Stage 3+).** Ship bundled SRD content; non-SRD
    via user-supplied port. Monetization on the engine/analysis, not
    content distribution. (See Firewall Rules above for legal substrate;
    see Cross-Project Architecture for full posture in the spine doc.)

12. **Clean-room reimplementation, file-first.** Subclass / spell / monster
    definitions are versioned, schema-validated files in the repo. A form
    UI is a thin editor over the file format, added later. Two-document
    split: private source-reading worksheet (provenance + own-words
    paraphrase = the clean-room audit trail) vs the shipped mechanical
    definition (schema has no rules-text field by construction — clean-room
    enforcement is structural, not advisory).

13. **Two-tier content schema.** Tier 1 — declarative effect-primitives
    (`extra_attack`, `stat_modifier`, `resource_pool`, etc.) parameterized
    by a small vocabulary; covers ~80% of features. Tier 2 — custom
    handler module for genuinely novel mechanics. Pattern borrowed from
    MtG card-scripting engines (Forge / XMage). Each effect carries an
    explicit read/write/event/scope contract (§Config condition 1).

---

## Build Phases

| Phase | Scope |
|---|---|
| **Phase 1** | Python engine (headless) + Open5e data + environment templates + single encounter simulation + outcome report |
| **Phase 2** | Foundry module (thin bridge) + live Foundry world data + automated combat with manual override |
| **Phase 3** | Multi-encounter day + dynamic difficulty adjustment + class/subclass Monte Carlo scoring |
| **Phase 4** | Web app + user accounts + AI map analysis + extended 3p/homebrew content |

**Re-prioritization note (May 2026):** The architecture-spine's
validation-oracle ROI elevates Phase 3 (Monte Carlo class/subclass scoring)
higher than its original ordering implied — Phase 3 produces the eHP power
curves that the Hybrid published-reports stage consumes. Phase 1 still
gates everything; the change is the rationale for Phase 3 being a
near-term commercial driver, not an "eventually" item.

---

## Open Questions (Unresolved)

- [ ] MCTS vs rules-based vs hybrid for monster AI decisions (see
      `ai-decision-layer.md` when drafted)
- [ ] Foundry VTT version to pin against
- [ ] Legendary Actions / Lair Actions in initiative order
- [ ] Ambush/surprise round — how does `ambush_potential` translate to
      initiative mechanics?
- [ ] Portal usage by AI — how does INT gate portal awareness?
- [ ] Underwater combat rules — attack disadvantage, weapon/spell
      restrictions
- [ ] Passive environmental damage — start of turn, end of turn, or on
      entry?
- [ ] Bystander constraint (tavern brawl) — engine model of AoE
      self-restriction near innocents
- [ ] Spellcaster DPR methodology — `pc-dpr-baselines.md` currently encodes
      martial single-target attack. Treantmonk *does* cover spell builds
      (Sorcerer Blast, EB Warlock, Bard Spells, Druid Spells, etc.); the
      methodology video transcript (`nLXbEFurCU4`) likely contains
      spell-DPR coverage. Extract when engine reaches spellcaster scoring.
- [ ] Schema design for subclass / spell / feat / monster definitions —
      drafted after `pillars-reconciliation.md` lands.
- [ ] 5e API → schema transform pipeline — fetch from `dnd5eapi.co`,
      clean-room transform, store as bundled SRD assets in this repo.

**Resolved since 2026-03-30:**
- ~~Data source for monster stat blocks?~~ → Open5e / 5e API for Phase 1
  (per `data-sources.md`).
- ~~2014 vs 2024 vs both?~~ → 2024 (per all April DPR work and the
  registry's `is_current_canonical` posture).
- ~~Conditions handling?~~ → eHP / eDPR adjustments (decided Mar 30,
  encoded in `ehp-action-framework.md`).
- Monetization architecture → Hybrid (see Decision #11).

---

## Related Project

**Trusight** (the `dnd-trends-index` repo) — intelligence / measurement
platform. Shares the D&D domain but is an entirely separate codebase,
separate GCP project, separate legal profile. The four firewall layers
above govern what crosses. The sim never holds Trusight intelligence data;
Trusight never holds sim engine code.

(Project formerly named "Arcane Analytics"; rebranded to "Trusight" May
2026.)

---

## Antigravity Protocol

- Checkpoint protocol: require complete raw output after each command.
- Never batch instructions — one command at a time.
- Verify writes with BigQuery MCP reads — do not accept fabricated
  confirmations.
- Known failure modes: truncated output, unsolicited extra commands,
  fabricated success reports.
