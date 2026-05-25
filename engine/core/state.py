"""Engine state — dataclasses for actor, encounter, combat state.

Design commitment: every state object is **plain Python data**
(dataclasses, dicts, lists, primitives). No Python-object-specific
state, no closures, no callbacks-as-state. This guarantees:

  1. Full JSON serialization (Foundry bridge can ship state over the
     wire as JSON).
  2. Deterministic replay (snapshot/restore for testing).
  3. Observation mode (external driver can hold state and pass it back).

See docs/architecture/schema-design.md §3 and the eventual Foundry
integration in CONTEXT.md Phase 2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ============================================================================
# Actor — a single creature in the encounter (PC or monster)
# ============================================================================

@dataclass
class Actor:
    """One creature in the encounter.

    Mutable during combat: HP, position, applied_conditions, resources, etc.
    The static template (stat block) is in `template`; runtime state is
    in the rest of the fields.
    """
    id: str                                     # instance id, e.g. "goblin_1"
    name: str                                   # display name
    template: dict                              # the loaded YAML template (monster or PC)
    side: str                                   # "pc" | "enemy" | "neutral"

    # Combat stats
    hp_current: int = 0
    hp_max: int = 0
    ac: int = 10
    speed: dict = field(default_factory=lambda: {"walk": 30})
    position: tuple[int, int] = (0, 0)          # grid coords; (0,0) until movement matters

    # Ability scores + modifiers
    abilities: dict = field(default_factory=dict)   # {"str": {"score": 16, "save": 5}, ...}

    # Runtime state
    applied_conditions: list = field(default_factory=list)   # list of {condition_id, source, ...}
    active_modifiers: list = field(default_factory=list)     # registry of active modifiers
    resources: dict = field(default_factory=dict)            # {"second_wind_uses_remaining": 2, ...}
    actions_used_this_turn: dict = field(default_factory=lambda: {
        "action": False, "bonus_action": False, "reaction": False,
    })
    initiative: int = 0
    is_dead: bool = False
    is_fled: bool = False

    def is_alive(self) -> bool:
        return self.hp_current > 0 and not self.is_dead and not self.is_fled

    def is_bloodied(self) -> bool:
        return self.hp_current <= (self.hp_max // 2)

    def reset_turn(self) -> None:
        self.actions_used_this_turn = {
            "action": False, "bonus_action": False, "reaction": False,
        }


# ============================================================================
# Encounter — the full battle scenario
# ============================================================================

@dataclass
class Encounter:
    """One encounter scenario: a list of actors + environment."""
    id: str
    actors: list[Actor]
    environment: dict = field(default_factory=dict)       # template name, terrain, etc.
    initial_distances: dict = field(default_factory=dict)  # {(id1, id2): ft}; optional


# ============================================================================
# CombatState — runtime state during an encounter
# ============================================================================

@dataclass
class CombatState:
    """Mutable per-encounter combat state."""
    encounter: Encounter
    round: int = 0
    turn_order: list = field(default_factory=list)   # actor ids in initiative order
    current_turn_idx: int = 0
    event_log: list = field(default_factory=list)
    terminated: bool = False
    termination_reason: str = ""

    # Per-current-attack scratch space (cleared between attacks)
    current_attack: dict = field(default_factory=dict)

    # Per-current-save scratch space (used by forced_save / save_modifier)
    current_save: dict = field(default_factory=dict)

    # Content registry — lookup for condition definitions, spells, etc.
    # Set by the runner via EncounterRunner.attach_content_registry().
    # Optional: if None, condition application stores markers only (no effects fire).
    content_registry: object | None = None

    # Recurring-save callbacks registered against actor turn-end events.
    # Entries: { target_id, condition_id, source_id, ability, dc, on_success, trigger_event }
    # Resolved by runner at the appropriate turn boundary.
    recurring_saves: list = field(default_factory=list)

    def current_actor(self) -> Actor | None:
        if not self.turn_order:
            return None
        return self._actor_by_id(self.turn_order[self.current_turn_idx])

    def _actor_by_id(self, actor_id: str) -> Actor | None:
        for a in self.encounter.actors:
            if a.id == actor_id:
                return a
        return None

    def living_actors_by_side(self) -> dict[str, list[Actor]]:
        sides: dict[str, list[Actor]] = {}
        for a in self.encounter.actors:
            if a.is_alive():
                sides.setdefault(a.side, []).append(a)
        return sides

    def advance_turn(self) -> None:
        if not self.turn_order:
            return
        self.current_turn_idx = (self.current_turn_idx + 1) % len(self.turn_order)
        if self.current_turn_idx == 0:
            self.round += 1


# ============================================================================
# Helper: ability modifier from score
# ============================================================================

def ability_modifier(score: int) -> int:
    """Standard D&D ability modifier: floor((score - 10) / 2)."""
    return (score - 10) // 2
