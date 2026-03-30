# Engine Design

**Status:** 🟡 Architecture defined — implementation pending  
**Last updated:** 2026-03-30

---

## Core Principle

The Python engine and the Foundry VTT module are two separate, independently testable pieces that communicate through a simple message protocol. **The engine never touches the UI. The Foundry module never touches the math.**

```
┌─────────────────────────┐         ┌─────────────────────────┐
│     Python Engine       │         │     Foundry Module      │
│     (The Brain)         │  ←────→ │     (The Hands)         │
│                         │         │                         │
│  - Combat math          │         │  - Move tokens          │
│  - eHP / eDPR / XP      │         │  - Roll dice in UI      │
│  - AI decisions         │         │  - Update HP bars       │
│  - State tracking       │         │  - Trigger animations   │
│  - Monte Carlo          │         │  - Read actor sheets    │
└─────────────────────────┘         └─────────────────────────┘
```

If it is a calculation → it belongs in the Python engine.  
If it is a UI action → it belongs in the Foundry module.  
This rule prevents bloat and keeps both components testable in isolation.

---

## Build Phases

### Phase 1 — Python Engine (Headless)
Build and validate the math engine with no Foundry dependency.  
Data source: Open5e API (see `docs/domain/data-sources.md`).  
The engine must be fully testable via pytest and Monte Carlo simulation before Phase 2 begins.

### Phase 2 — Foundry Module (Thin Bridge)
Build the Foundry module as a minimal bridge — no logic, just message passing.  
Scope: ~300–500 lines of JavaScript.  
The module sends combat state to the engine and executes the engine's instructions.

### Phase 3 — Integration
Wire Phase 1 and Phase 2 together.  
Replace Open5e data with live Foundry world data (user's licensed content).  
Validate that engine behavior is identical whether data comes from Open5e or Foundry.

### Phase 4 — Extended Content
User supplies 3p, homebrew, and UA content via their own Foundry modules.  
Engine operates on whatever Foundry provides — no repo changes needed.

---

## Python Engine Architecture

### Module Structure

```
/engine
  __init__.py
  combat_loop.py        ← Main encounter runner
  state.py              ← CombatState dataclass and state management
  math/
    __init__.py
    effective_stats.py  ← eHP, eDPR, eAC, eAB calculations
    xp.py               ← XP engine (exponential formula)
    encounter.py        ← Encounter multiplier, difficulty, rounds
    variability.py      ← Variance, std dev, win probability distributions
    initiative.py       ← Initiative win probability
    conditions.py       ← Condition valuation multipliers
    magic_items.py      ← Magic item XP adjustments
  ai/
    __init__.py
    decision.py         ← Monster AI decision layer (MCTS or rules-based — TBD)
    targeting.py        ← Target selection logic (Ammann framework)
  data/
    __init__.py
    open5e.py           ← Open5e API client (Phase 1 data source)
    schemas.py          ← MonsterStatBlock, PCStatBlock, SpellData dataclasses
    foundry.py          ← Foundry data adapter (Phase 3)
  simulation/
    __init__.py
    monte_carlo.py      ← Monte Carlo encounter runner
    reporter.py         ← Simulation result reporting
```

### Combat Loop (Pseudocode)

```python
def run_encounter(monsters: list[MonsterStatBlock],
                  party: list[PCStatBlock],
                  mode: str = "EV") -> EncounterResult:
    """
    mode = "EV"      → Expected value (deterministic, for AI decisions)
    mode = "sampled" → Monte Carlo (probabilistic, for stress testing)
    Never mix modes in the same encounter run.
    """
    state = CombatState(monsters=monsters, party=party)
    state.roll_initiative()

    while not state.is_resolved():
        actor = state.next_actor()

        if actor.is_monster():
            decision = ai_decide(actor, state)   # Ammann + Finished Book
            state.apply(decision)
        else:
            decision = pc_optimal_action(actor, state)
            state.apply(decision)

        state.advance_turn()

    return EncounterResult.from_state(state)
```

### CombatState

The complete state vector the engine operates on each turn:

```python
@dataclass
class CombatState:
    monsters: list[MonsterStatBlock]
    party: list[PCStatBlock]
    round_number: int = 1
    initiative_order: list = field(default_factory=list)
    active_conditions: dict = field(default_factory=dict)  # {actor_id: [conditions]}
    concentration: dict = field(default_factory=dict)       # {caster_id: spell}
    legendary_actions_remaining: dict = field(default_factory=dict)
    legendary_resistances_remaining: dict = field(default_factory=dict)
    spell_slots_remaining: dict = field(default_factory=dict)
```

---

## Communication Protocol (Engine ↔ Foundry)

The Foundry module and Python engine communicate via a local WebSocket connection. Foundry sends a state payload; the engine returns a decision payload.

### State Payload (Foundry → Engine)

```json
{
  "round": 2,
  "active_actor": {
    "id": "goblin_01",
    "type": "monster",
    "cr": 0.25,
    "hp_current": 4,
    "hp_max": 7,
    "ac": 15,
    "position": {"x": 3, "y": 4}
  },
  "combatants": [...],
  "active_conditions": {...},
  "concentration": {...}
}
```

### Decision Payload (Engine → Foundry)

```json
{
  "actor_id": "goblin_01",
  "action": {
    "type": "attack",
    "target_id": "wizard_01",
    "attack_name": "Scimitar",
    "attack_bonus": 4,
    "damage_roll": "1d6+2"
  },
  "bonus_action": null,
  "movement": {"x": 3, "y": 3}
}
```

The Foundry module executes this payload — it moves the token, triggers the roll, updates HP — without knowing anything about why the engine made that decision.

---

## Performance Requirements

| Operation | Target Latency |
|---|---|
| Single monster decision (EV mode) | < 100ms |
| Single monster decision (MCTS, depth 3) | < 500ms |
| Full encounter simulation (EV mode) | < 1s |
| Monte Carlo 10,000 encounters | < 60s |

These are targets, not hard constraints at this stage. Revisit after Phase 1 benchmarking.

---

## Testing Strategy

### Unit Tests (pytest)
Each math module tested in isolation against known values from `finished-book-summary.md`.

```python
# Example: validate eHP formula
def test_ehp_at_baseline():
    # At eAC = 12 (baseline), eHP should equal HP / sqrt(0.65)
    hp = 100.0
    eac = 12.0
    result = calc_ehp(hp, eac)
    expected = hp / math.sqrt(0.65)
    assert abs(result - expected) < 0.01
```

### Monte Carlo Validation
Run 10,000 simulated encounters at each difficulty level and verify win probability matches The Finished Book's expected values:

| Difficulty | Expected Win % | Acceptable Range |
|---|---|---|
| Easy | ~95% | 90–99% |
| Medium | ~85% | 80–90% |
| Hard | ~70% | 65–75% |
| Deadly | ~50% | 40–60% |

### Regression Tests
Any time a formula is updated, re-run the full Monte Carlo suite to confirm the change doesn't shift win probabilities outside acceptable ranges.

---

## Open Decisions

- [ ] **AI decision algorithm:** MCTS vs rules-based vs hybrid — see `docs/architecture/ai-decision-layer.md`
- [ ] **Foundry version to pin:** decide before starting Phase 2
- [ ] **WebSocket vs REST:** WebSocket assumed above but not yet decided
- [ ] **Rules target:** 2014, 2024, or both? Affects XP formula and encounter multiplier behavior
- [ ] **Foundry module manifest:** module ID, compatibility range, dependencies

---

## Dependencies

```toml
# pyproject.toml (planned)
[tool.poetry.dependencies]
python = "^3.11"
numpy = "*"
scipy = "*"
requests = "*"          # Open5e API client
websockets = "*"        # Foundry communication
pytest = "*"
```
