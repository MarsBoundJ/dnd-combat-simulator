"""D&D 5e combat simulator — Phase 1 engine skeleton.

Library-first headless Python. CLI wrapper in `engine.cli`. A future
Foundry VTT bridge (Phase 2 per docs/CONTEXT.md) consumes the same
public API.

Architectural commitments — see `docs/architecture/schema-design.md`
and `docs/foundations/pillars-reconciliation.md`:

  - Engine state is fully serializable (plain dicts / dataclasses).
  - Event-emitting API: primitive handlers subscribe to engine events.
  - Schema as lingua franca: YAML content → validated → engine state.
  - Two operating modes: sim (engine drives decisions) + observation
    (external driver feeds events; engine records).

This is a SKELETON — most primitives are stubbed. Implementations
land incrementally per content surface area.
"""

from engine.core.runner import EncounterRunner, run_encounter
from engine.core.state import Actor, Encounter, CombatState
from engine.core.events import EventBus
from engine.reports import EncounterReport

__version__ = "0.1.0"
__all__ = [
    "EncounterRunner",
    "run_encounter",
    "Actor",
    "Encounter",
    "CombatState",
    "EventBus",
    "EncounterReport",
]
