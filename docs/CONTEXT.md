# CONTEXT.md — D&D Combat Simulator

**Paste this file at the start of every AI session on this project.**  
Last updated: 2026-03-30

---

## What This Project Is

A high-fidelity D&D 5e combat simulator with Foundry VTT as the front end. A headless Python engine handles math, AI decision logic, and Monte Carlo simulation. A Foundry VTT module bridges the engine to the UI.

This is a solo project by Phil (GitHub: MarsBoundJ). The AI collaborator team is Claude (architect/reviewer), Antigravity (execution agent), and Gemini/Perplexity (research/validation).

---

## Two Intellectual Pillars

All engine logic must trace back to one or both of these pillars. Conflicts between them are resolved by `docs/foundations/pillars-reconciliation.md`.

**Pillar 1 — The Finished Book**  
Physics-based mathematical framework by Tom Dunn.  
Source: https://tomedunn.github.io/the-finished-book  
Encoded in: `docs/foundations/finished-book-summary.md`  
Covers: eHP, eDPR, XP engine, encounter multiplier, variability, initiative, conditions, magic items, daily resource economy.

**Pillar 2 — The Monsters Know What They're Doing**  
Behavioral monster decision-making framework by Keith Ammann.  
Source: https://www.themonstersknow.com  
Encoded in: `docs/foundations/ammann-behavior-framework.md` ← **NOT YET DRAFTED**  
Covers: Monster targeting logic, retreat/morale decisions, ability usage priority, encounter tactics.

---

## Current Project Status

| Area | Status |
|---|---|
| Repo created | ✅ github.com/MarsBoundJ/dnd-combat-simulator |
| `finished-book-summary.md` | ✅ Complete — full live-site audit March 2026 |
| `ammann-behavior-framework.md` | 🔴 Not started |
| `pillars-reconciliation.md` | 🔴 Not started — blocked on Ammann doc |
| `combat-state-model.md` | 🔴 Not started |
| `conditions-and-edge-cases.md` | 🔴 Not started |
| `data-sources.md` | 🔴 Not started |
| `engine-design.md` | 🔴 Not started |
| `foundry-integration.md` | 🔴 Not started |
| `ai-decision-layer.md` | 🔴 Not started |
| Any engine code | 🔴 Not started — docs must precede code |

**Current phase:** Source of Truth documentation. No algorithms written until `pillars-reconciliation.md` is complete.

---

## Key Architectural Decisions Made

1. **Docs-as-code** — all documentation lives in `/docs` in this repo, co-located with code.
2. **Headless engine** — Python engine has no UI dependency. Foundry module is a bridge only.
3. **XP formula** — exponential approximation (`1.077^(eAB-4 + eAC-12)`) is the engine's internal truth. Published monster XP (Tier 0) is imported as-is for 2014 rules; 2024 rules use no encounter multiplier.
4. **Variability modes** — engine operates in EV (expected value) mode for AI decisions and Sampled mode for Monte Carlo stress tests. Never mixed in the same encounter run.
5. **Condition policy** — conditions resolved through eHP/eDPR adjustments only, not ad-hoc damage modifiers. Targeting decisions (which condition to apply) governed by Ammann pillar.
6. **AI decision layer** — choice between MCTS and rules-based not yet made. Decision lives in `ai-decision-layer.md` and must be made before engine code is written.

---

## Open Questions (Unresolved)

- [ ] MCTS vs rules-based for monster AI decisions?
- [ ] Data source for monster stat blocks — SRD only, or D&D Beyond API?
- [ ] Foundry VTT version to pin against?
- [ ] Does the simulator target 2014 rules, 2024 rules, or both?
- [ ] How does the engine handle Legendary Actions and Lair Actions in initiative order?

---

## Related Project

**Arcane Analytics** (`dnd-trends-index`) — separate GCP-based Google Trends intelligence platform. Shares the D&D domain but is an entirely separate codebase. Do not mix concerns between the two repos.

---

## Antigravity Protocol (Execution Agent Rules)

When working with Antigravity:
- **Checkpoint protocol:** require complete raw output after each command before proceeding.
- **Never batch instructions** — one command at a time.
- **Verify with BigQuery MCP reads** — do not accept Antigravity's confirmation of writes at face value.
- **Gen2 Cloud Function deployments** — must be done from Cloud Shell using owner credentials, not via Antigravity. (Arcane Analytics rule — carry forward here if GCP is ever added to this project.)
- **Known Antigravity failure modes:** truncated output, unsolicited extra commands, fabricated success reports.
