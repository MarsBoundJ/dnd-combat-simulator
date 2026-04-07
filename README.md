# D&D Combat Simulator

> High-fidelity D&D 5e encounter simulation — physics-based math engine + behaviorally authentic monster AI

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Foundry VTT](https://img.shields.io/badge/Foundry_VTT-Module-red)](https://foundryvtt.com)
[![Status](https://img.shields.io/badge/Status-Pre--Development%20%7C%20Design%20Phase-yellow)](https://github.com/MarsBoundJ/dnd-combat-simulator)

---

## What This Is

A locally-run D&D 5e combat simulator built for Dungeon Masters who want to test encounters *before* putting players through them. The engine runs headless — pure Python math and AI decision logic — with Foundry VTT as the interactive front end and a thin JavaScript module bridging the two.

The simulator is designed to answer two questions:

1. **Will this encounter kill my party?** — Mathematical encounter difficulty assessment using expected hit points (eHP) rather than the WotC CR formula, which is known to be unreliable at high levels.
2. **How will the monsters actually behave?** — Not just optimal play, but intelligent, in-character behavior. A wolf pack coordinates differently from a dragon. A low-INT zombie charges blindly; an Apex Predator retreats to heal when wounded.

---

## Intellectual Foundations

The simulator is built on two published frameworks, reconciled into a unified evaluation function:

### Pillar 1 — The Finished Book (Mathematical Framework)
*Tom Dunn — [tomedunn.github.io/the-finished-book](https://tomedunn.github.io/the-finished-book)*

A physics-based mathematical analysis of D&D 5e combat covering:

- **Expected Hit Points (eHP)**: effective survivability accounting for resistances, AC, and saving throw proficiency — a far more accurate measure of creature toughness than raw HP
- **XP calibration formula**: `1.077^(eAB − 4 + eAC − 12)` — derived from regression across the Monster Manual, captures the exponential relationship between attack bonus, AC, and combat value
- **Encounter Multiplier (EM)**: action economy effects of multiple combatants; the 2024 rules revision brings EM to 1.0 (eliminating the old multi-monster multiplier)
- **Variability modeling**: how damage distribution shape, save frequency, and crit probability affect outcome uncertainty — essential for Monte Carlo validation
- **PC power baseline**: class-by-class expected output at each tier, used for difficulty benchmarking

### Pillar 2 — The Monsters Know What They're Doing (Behavioral Framework)
*Keith Ammann — [themonstersknow.com](https://themonstersknow.com)*

A behavioral analysis of every monster in the Monster Manual, establishing how each creature would fight given its real-world (in-fiction) intelligence, drives, and instincts.

The engine distills this into six named behavioral archetypes:

| Archetype | Profile | Example Creatures |
|---|---|---|
| Mindless Aggressor | Attacks nearest target, no morale, no retreat | Zombies, skeletons |
| Cowardly Skirmisher | High self-preservation, retreats below 50% HP, hit-and-run | Kobolds, goblins |
| Pack Hunter | Coordinates with allies, flanks, focuses wounded targets | Wolves, gnolls |
| Apex Predator | Optimal targeting, uses terrain, manages resources | Dragons, mind flayers |
| Territorial Defender | Prioritizes area control over damage | Giants, elementals |
| Fanatical True Believer | No morale threshold, suicidal for objectives | Cultists, berserkers |

Each archetype maps to a `BehaviorProfile` dataclass with INT-gated decision complexity — a creature with INT 3 cannot execute multi-step tactical plans regardless of its archetype.

### The Reconciliation Problem

These two pillars create a productive tension: the Finished Book tells you the *mathematically optimal* action; Ammann tells you the *behaviorally authentic* action. A zombie does not use optimal action economy. An Apex Predator might — but only when its INT and WIS support it.

The engine resolves this via an explicit policy document (`docs/foundations/pillars-reconciliation.md`) that defines, for each class of conflict, which pillar wins and why. Behavioral authenticity is the default; mathematical optimality applies only when creature intelligence explicitly permits it.

---

## The Core Evaluation Function

Every decision the monster AI makes runs through the **eHP Action Framework** — a unified formula that scores any action in combat:

```
Action Value = Offensive eHP + Defensive eHP − Opportunity Cost
```

Where:
- **Offensive eHP** = expected HP damage dealt to enemies (adjusted for hit probability, damage type, saves)
- **Defensive eHP** = expected HP damage prevented for allies (healing, buffs, cover)
- **Opportunity Cost** = resource cost (spell slot level, action economy, concentration lock)

The formula is discounted over a 2.5-round time horizon — the statistical average encounter length — so actions with delayed payoffs are properly weighted against immediate damage.

*Example*: Hypnotic Pattern (action denial, 3rd-level slot) vs Fireball (direct damage, 3rd-level slot) against a group of 4 enemies. Hypnotic Pattern scores higher at 2.5 rounds because action denial compounds — enemies lose their turns, which has multiplicative value. Fireball scores higher only when the encounter will end in fewer than 1.5 rounds, where compounding does not materialize.

---

## Architecture

```
+----------------------------------------------------------+
|                  FOUNDRY VTT (Front End)                 |
|  Combat tracker  ·  Token automation  ·  DM controls    |
|  Electron / Node.js                                      |
+------------------------+---------------------------------+
                         | WebSocket
                         | (state -> decision payloads)
                         v
+----------------------------------------------------------+
|              FOUNDRY MODULE (JS Bridge)                  |
|  Thin translation layer: Foundry hooks -> engine API    |
|  ES Modules, no game logic                              |
+------------------------+---------------------------------+
                         | JSON payloads
                         v
+----------------------------------------------------------+
|            PYTHON ENGINE (Headless)                      |
|  combat_loop.py  ·  state.py  ·  math/  ·  ai/          |
|  data/  ·  simulation/                                   |
|  All math, all AI decisions, all Monte Carlo            |
+----------------------------------------------------------+
```

**Core design principle**: the engine never touches the UI; Foundry never touches math. The boundary is strictly enforced — all game logic lives in Python, all rendering lives in Foundry.

### Performance Targets

| Operation | Target |
|---|---|
| Single monster decision (EV scoring) | < 100ms |
| Single monster decision (MCTS) | < 500ms |
| Full encounter simulation | < 1s |
| Monte Carlo run (1,000 iterations) | < 30s |

### Data Sources and Legal Boundary

The engine never requires the user to provide copyrighted WotC content. Development proceeds in phases:

- **Phase 1**: Open5e API (SRD 5.1/5.2, CC-licensed) — all SRD monsters and spells
- **Phase 2**: User's own Foundry world data (user has licensed it; engine reads at runtime, never stores it in the repo)
- **Phase 3**: User-supplied third-party and homebrew content

No WotC copyrighted stat blocks, spell text, or sourcebook content is stored in this repository.

---

## Environment System

Combat takes place in typed environments that affect tactical calculations — AoE efficiency, movement costs, cover probability, hazard exposure. The engine ships with 15 named environment templates:

| Environment | Key Tactical Features |
|---|---|
| Open Field | No cover, full AoE efficiency, unrestricted movement |
| Dungeon Corridor | Choke points, partial cover, AoE penalty, flanking bonus |
| Forest Clearing | Partial cover (25%), difficult terrain, ambush potential |
| Rooftops | Elevation advantage, fall hazard, movement penalty |
| Underwater | Speed reduction, fire spell penalty, breath weapon disabled |
| Lava Cavern | Environmental damage zones, heat exhaustion risk |
| *(+9 more)* | Defined in `docs/domain/environment-system.md` |

Environments are data templates — adding new environments requires no code changes, only a new template entry. Custom environments can be added through the UI without modifying engine source.

---

## Build Phases

| Phase | Scope | Status |
|---|---|---|
| **1** | Python engine + Open5e data + environment templates + single encounter sim | Not started |
| **2** | Foundry module (thin bridge) + live Foundry world data | Not started |
| **3** | Multi-encounter day + dynamic difficulty + class/subclass Monte Carlo scoring | Not started |
| **4** | Web app + user accounts + AI map analysis + homebrew content support | Not started |

**Current state**: documentation-first design phase. All mathematical foundations, behavioral frameworks, data contracts, environment templates, and architecture policies are specified before a line of engine code is written.

---

## Why Documentation-First

The engine must implement a specific mathematical framework correctly. Getting the eHP formula wrong, miscalibrating the XP regression, or misapplying the behavioral archetypes produces a simulator that generates plausible-looking but *incorrect* results — which is worse than no simulator, because the DM trusts the output.

The documentation phase exists to:

1. **Audit the source material** — every article of The Finished Book and every behavioral profile in Ammann's framework is read, summarized, and encoded into the design spec before it becomes code
2. **Resolve conflicts in writing** — the reconciliation policy is explicit and reviewable, not an emergent consequence of ad-hoc implementation decisions
3. **Define test oracles before writing tests** — unit tests will verify against known Finished Book values; the spec establishes what those values should be before the code exists

This produces a system that can be validated mathematically before execution, and tested precisely because expected outputs are fully specified.

---

## Open Engineering Decisions

| Decision | Options Under Consideration | Status |
|---|---|---|
| Monster AI algorithm | MCTS vs rules-based vs hybrid | Open — depends on latency vs behavior trade-off |
| Rules target | 2014 PHB, 2024 PHB, or both | Open |
| Foundry VTT version pin | v11, v12 | Open |
| Legendary/Lair Actions | Fixed initiative slot vs triggered | Open |
| Ambush/surprise round | Per 2014 or 2024 rules | Open |
| Portal usage by AI | INT-gated or always available | Open |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Engine | Python 3.11+ |
| Math | NumPy, SciPy |
| Front End | Foundry VTT (Electron/Node.js) |
| Bridge Module | JavaScript (ES Modules) |
| Communication | WebSocket (engine to Foundry) |
| Testing | pytest + Monte Carlo simulation |
| AI Decision Layer | TBD (MCTS / rules-based / hybrid) |

---

## Documentation

All architectural decisions, mathematical foundations, and design policies live in `/docs`.

| Document | Purpose |
|---|---|
| `docs/CONTEXT.md` | Project state — start here |
| `docs/SESSIONS.md` | Running log of design decisions across sessions |
| `docs/foundations/finished-book-summary.md` | Complete Finished Book audit (mathematical framework) |
| `docs/foundations/ammann-behavior-framework.md` | Behavioral archetypes and `BehaviorProfile` spec |
| `docs/foundations/pillars-reconciliation.md` | Conflict resolution policy *(in progress)* |
| `docs/foundations/ehp-action-framework.md` | Unified action evaluation formula |
| `docs/domain/combat-state-model.md` | Combat turn as data structure *(in progress)* |
| `docs/domain/environment-system.md` | 15 environment templates and tactical effect specs |
| `docs/domain/data-sources.md` | Legal data strategy and stat block schemas |
| `docs/architecture/engine-design.md` | Python engine module structure and WebSocket protocol |
| `docs/architecture/foundry-integration.md` | Hook map, module manifest, version pins *(in progress)* |
| `docs/architecture/ai-decision-layer.md` | AI algorithm decision *(pending)* |

---

## Contact

Built by [@MarsBoundJ](https://github.com/MarsBoundJ).

For design feedback or collaboration, open an issue.
