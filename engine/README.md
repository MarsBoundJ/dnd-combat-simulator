# Engine

Headless Python D&D 5e combat simulator. Phase 1 skeleton.

## Install

```bash
pip install -e .                   # installs PyYAML + jsonschema
pip install -e ".[dev]"            # adds pytest for testing
```

## CLI usage

```bash
# Validate all content loads + lite-validates against schemas:
python -m engine validate

# Run an encounter from a YAML spec:
python -m engine encounter tests/fixtures/smoke_encounter.yaml --seed 42

# Quiet (no event log):
python -m engine encounter tests/fixtures/smoke_encounter.yaml --seed 42 --quiet

# JSON output (for downstream pipelines):
python -m engine encounter tests/fixtures/smoke_encounter.yaml --seed 42 --json
```

## Smoke test

```bash
python -m unittest tests.test_smoke -v
```

Runs four checks: content loads, encounter terminates, Fighter wins majority of 20 random seeds, JSON report is valid.

## Module layout

```
engine/
├── __init__.py             # public API
├── __main__.py             # python -m engine entry
├── cli.py                  # CLI arg parsing + commands
├── loader.py               # YAML loader + JSON Schema (lite) validator
├── primitives.py           # primitive registry (5 implemented; ~40 stubbed)
├── reports.py              # EncounterReport (JSON + human-readable)
└── core/
    ├── state.py            # Actor, Encounter, CombatState dataclasses
    ├── events.py           # EventBus + canonical event vocabulary
    ├── pipeline.py         # 8-step decision pipeline (skeleton AI)
    └── runner.py           # EncounterRunner — drives encounters to termination
```

## What's implemented

**5 primitives implemented end-to-end:**
- `attack_roll` — d20 + bonus vs AC, with advantage/disadvantage support
- `damage` — dice + modifier, crit doubling, resistance/vulnerability/immunity
- `apply_condition` — adds entry to actor's `applied_conditions` array
- `heal` — dice + modifier source, capped at HP max
- `granted_action` — records granted action in event log (engine ignores effect for now)

**~40 primitives stubbed.** They raise `NotImplementedError` with a clear message if invoked. Adding more = unlocking more content.

## Stage 1 (current) → Stage 2/3 (future)

- **Now:** library-first Python engine + CLI for internal research grading. Fully serializable state; event-emitting API; schema as lingua franca. All architectural commitments needed for the future Foundry bridge are in place.
- **Phase 2:** Foundry VTT thin-bridge module (~300–500 lines JS). Bridge subscribes to engine events for display updates; translates Foundry actors → engine state at the bridge layer. Engine itself unchanged.
- **Phase 3:** Public-facing standalone tool (community service). Monte Carlo loop + statistical reporting. Engine API unchanged; new consumers.

The engine's two operating modes — **sim mode** (engine drives decisions) and **observation mode** (external driver feeds events; engine records) — are enabled by the EventBus design from day one. Foundry integration in Phase 2 just uses observation mode plus the schema as a translation target.

## What's NOT implemented yet

| | |
|---|---|
| Full AI decision layer | Skeleton uses "attack nearest enemy with first available attack." Real implementation is the 5-step Ammann+eHP hybrid per `docs/foundations/pillars-reconciliation.md` §7. |
| ~40 primitives | Stubbed with clear `NotImplementedError`. Add implementations as content requires. |
| Movement / positioning / line of sight | Skeleton uses (0,0) coords for everyone. Real engine needs grid math. |
| Area-of-effect geometry | Sphere / cube / cone / line / emanation / cylinder math. |
| Concentration mechanics | Engine should auto-trigger CON saves on damage when caster has concentration. |
| Condition effects in decisions | Schema models them; engine doesn't yet consult them. |
| Monte Carlo loop | One encounter at a time for now. Phase 3 work. |
| BehaviorProfile dial resolution | Schema models them; engine doesn't yet consult them. |
| Spellcasting infrastructure | Spell slots tracking, prepared spells, ritual rules — all stubbed. |

Each gap is a tractable incremental piece of work, not a redesign. The architecture is the deliverable; primitives + AI + math are content that fills it in.
