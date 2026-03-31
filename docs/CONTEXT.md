# CONTEXT.md — D&D Combat Simulator

**Paste this file at the start of every AI session on this project.**  
Last updated: 2026-03-30

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

## Current Project Status

| Document | Status |
|---|---|
| `finished-book-summary.md` | ✅ Complete — full live-site audit March 2026 |
| `ammann-behavior-framework.md` | ✅ Complete |
| `ehp-action-framework.md` | ✅ Complete |
| `environment-system.md` | ✅ Complete |
| `pillars-reconciliation.md` | 🟡 Next priority — all inputs now available |
| `engine-design.md` | ✅ Complete |
| `data-sources.md` | ✅ Complete |
| `combat-state-model.md` | 🔴 Not started |
| `conditions-and-edge-cases.md` | 🔴 Not started |
| `foundry-integration.md` | 🔴 Not started |
| `ai-decision-layer.md` | 🔴 Not started |
| Any engine code | 🔴 Not started — `pillars-reconciliation.md` must come first |

**Current phase:** Source of Truth documentation. `pillars-reconciliation.md`
is the last doc blocking Phase 1 engine code.

---

## Key Architectural Decisions Made

1. **Docs-as-code** — all documentation lives in `/docs` in the repo.

2. **Headless engine** — Python engine has no UI dependency. Foundry module is
   a bridge only. ~300–500 lines of JavaScript.

3. **XP formula** — exponential approximation (`1.077^(eAB-4 + eAC-12)`) is
   the engine's internal truth. 2024 rules use no encounter multiplier.

4. **Variability modes** — EV (expected value) mode for AI decisions; Sampled
   mode for Monte Carlo. Never mixed in the same encounter run.

5. **Condition policy** — conditions resolved through eHP/eDPR adjustments.
   Targeting decisions governed by Ammann pillar.

6. **eHP Action Framework** — unified evaluation function for all action types.
   Every action scores as: offensive_ehp + defensive_ehp − opportunity_cost,
   weighted by behavioral coefficients.

7. **Environment system** — `EnvironmentTemplate` is the stable interface.
   Engine always receives a template object regardless of source (named registry,
   custom DM sliders, Foundry scene data, or AI map analysis). Infinitely
   extensible without touching engine code.

8. **Phase 1 scope** — single encounter simulation + outcome report +
   environment templates. Web app, hosted infrastructure, and AI map analysis
   are later phases.

9. **Data sources** — Open5e API for Phase 1 development/testing. Foundry
   runtime data for Phase 2. No copyrighted WotC content in the repo.

10. **AI decision layer** — MCTS vs rules-based not yet decided. See
    `ai-decision-layer.md`.

---

## Build Phases

| Phase | Scope |
|---|---|
| **Phase 1** | Python engine (headless) + Open5e data + environment templates + single encounter simulation + outcome report |
| **Phase 2** | Foundry module (thin bridge) + live Foundry world data + automated combat with manual override |
| **Phase 3** | Multi-encounter day + dynamic difficulty adjustment + class/subclass Monte Carlo scoring |
| **Phase 4** | Web app + user accounts + AI map analysis + extended 3p/homebrew content |

---

## Open Questions (Unresolved)

- [ ] MCTS vs rules-based vs hybrid for monster AI decisions?
- [ ] Data source for monster stat blocks — Open5e only, or D&D Beyond API?
- [ ] Foundry VTT version to pin against?
- [ ] Does the simulator target 2014 rules, 2024 rules, or both?
- [ ] Legendary Actions / Lair Actions in initiative order?
- [ ] Ambush/surprise round — how does `ambush_potential` translate to
      initiative mechanics?
- [ ] Portal usage by AI — how does INT gate portal awareness?
- [ ] Underwater combat rules — attack disadvantage, weapon/spell restrictions
- [ ] Passive environmental damage — start of turn, end of turn, or on entry?
- [ ] Bystander constraint (tavern brawl) — how does engine model self-restriction
      of AoE near innocents?

---

## Related Project

**Arcane Analytics** (`dnd-trends-index`) — separate GCP-based Google Trends
intelligence platform. Shares the D&D domain but is an entirely separate
codebase. Do not mix concerns between the two repos.

---

## Antigravity Protocol

- Checkpoint protocol: require complete raw output after each command.
- Never batch instructions — one command at a time.
- Verify writes with BigQuery MCP reads — do not accept fabricated confirmations.
- Known failure modes: truncated output, unsolicited extra commands, fabricated
  success reports.
