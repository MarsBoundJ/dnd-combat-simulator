# D&D Combat Simulator

A high-fidelity D&D 5e combat simulator built on two intellectual pillars:

- **The Finished Book** — physics-based mathematical framework by Tom Dunn (tomedunn.github.io/the-finished-book)
- **The Monsters Know What They're Doing** — behavioral monster decision-making framework by Keith Ammann

Foundry VTT serves as the front end. A headless Python engine handles all math, AI decision logic, and simulation. A Foundry module bridges the two.

## Architecture Overview

```
/docs           Source of Truth documentation
/engine         Headless Python math + AI engine
/foundry        Foundry VTT module (JavaScript)
/tests          Monte Carlo simulation tests
```

## Documentation

All architectural decisions, mathematical foundations, and design policies live in `/docs`. Start there before reading any code.

| Document | Purpose |
|---|---|
| `docs/CONTEXT.md` | Project state — read this at the start of every session |
| `docs/SESSIONS.md` | Running log of key decisions across sessions |
| `docs/foundations/finished-book-summary.md` | Mathematical engine (Pillar 1) |
| `docs/foundations/ammann-behavior-framework.md` | Behavioral decision logic (Pillar 2) |
| `docs/foundations/pillars-reconciliation.md` | Policy for resolving conflicts between pillars |
| `docs/domain/combat-state-model.md` | What a combat turn looks like as data |
| `docs/domain/conditions-and-edge-cases.md` | Concentration, reactions, legendary actions |
| `docs/domain/data-sources.md` | SRD, monster stat blocks, spell index |
| `docs/architecture/engine-design.md` | Headless Python engine spec |
| `docs/architecture/foundry-integration.md` | Hook map, API surface, version pins |
| `docs/architecture/ai-decision-layer.md` | Decision algorithm policy |

## Tech Stack

| Layer | Technology |
|---|---|
| Front End | Foundry VTT (Electron/Node.js) |
| Engine | Python 3.11+ |
| Bridge | Foundry Module (JavaScript/ES Modules) |
| Math | NumPy, SciPy |
| AI Decision Layer | TBD — MCTS vs rules-based (see `ai-decision-layer.md`) |
| Testing | pytest + Monte Carlo simulation |

## AI Workflow

This project uses a multi-AI architecture:
- **Claude** — architect, reviewer, Source of Truth oversight
- **Antigravity** — DevContainer/Docker execution agent
- **Gemini / Perplexity** — parallel research and validation

All non-obvious decisions made during AI sessions are logged in `docs/SESSIONS.md`.

## Status

🟡 Pre-development — Source of Truth documentation in progress.

See `docs/CONTEXT.md` for current state.
