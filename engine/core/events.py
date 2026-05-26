"""Event bus — primitives subscribe; engine dispatches.

The event vocabulary is fixed (see docs/architecture/schema-design.md §3).
Engine and content reference event names as strings; the bus dispatches
to subscribed handlers in registration order.

For the skeleton: simple synchronous dispatch. No reactions are
implemented yet, so the reaction-cascade termination guard (§Config
condition #4) is NOT YET enforced — when reactions land, this is where
it goes: handlers that consume actor reactions must decrement
per-actor reaction availability before emitting follow-on events, so
Mage Slayer → Shield → Counterspell cascades cannot infinite-loop.
"""
from __future__ import annotations

from typing import Callable, Any


# Canonical event names — must match schema/definitions/common.schema.json#event_name
EVENT_NAMES = frozenset({
    # Attack pipeline
    "attack_declared", "attack_roll", "attack_resolved",
    "pre_damage_triggers", "damage_roll", "damage_modified", "damage_dealt",
    "creature_bloodied", "creature_dropped", "on_hit_riders", "attack_complete",
    # Reaction triggers (PR #45):
    #   attack_targeting_resolved — fires after target is picked but
    #     BEFORE the d20 is rolled. Protection Fighting Style hooks here.
    #   attack_roll_pending — fires after d20+bonus is computed but
    #     BEFORE the hit/miss check. Shield hooks here (retroactive AC
    #     bump). Engine re-queries attack_modifiers after this event.
    #   damage_taken — fires after HP is reduced. Hellish Rebuke hooks
    #     here (retaliation against the damaging attacker).
    "attack_targeting_resolved", "attack_roll_pending", "damage_taken",
    # PR #46: spell-cast event for Counterspell
    #   spell_cast_initiated — fires BEFORE a spell's pipeline runs
    #     (after slot availability check but before any effect lands).
    #     Counterspell hooks here. Reaction handlers can set
    #     state.current_attack.cast_cancelled = True to fizzle the
    #     spell; pipeline.execute checks the flag and skips the
    #     pipeline but still consumes the slot (RAW 2024).
    "spell_cast_initiated",
    # Spell pipeline
    "spell_cast", "spell_resolve", "spell_end", "concentration_check",
    "target_enters_area", "target_exits_area",
    "target_turn_start_in_area", "target_turn_end_in_area",
    "target_turn_end", "target_movement_or_turn_end",
    # Turn / round level
    "round_start", "turn_start", "turn_end", "round_end",
    "actor_turn_bonus_action", "actor_turn_start", "actor_bonus_action",
    "attack_roll_resolved", "creature_makes_attack_roll_against_actor",
    "continuous",
    # Rest events
    "short_rest_end", "long_rest_end",
})


class EventBus:
    """Simple synchronous event dispatcher.

    Future Foundry bridge subscribes here for display updates.
    Observation mode: external driver calls `emit()` directly with
    events from Foundry; engine records and runs handlers but doesn't
    drive decisions.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[dict], Any]]] = {
            name: [] for name in EVENT_NAMES
        }
        self._global_subscribers: list[Callable[[str, dict], Any]] = []

    def subscribe(self, event_name: str, handler: Callable[[dict], Any]) -> None:
        if event_name not in EVENT_NAMES:
            raise ValueError(f"Unknown event: {event_name!r}. "
                             f"See engine.core.events.EVENT_NAMES.")
        self._subscribers[event_name].append(handler)

    def subscribe_all(self, handler: Callable[[str, dict], Any]) -> None:
        """Subscribe to every event (useful for logging / observation mode)."""
        self._global_subscribers.append(handler)

    def emit(self, event_name: str, payload: dict) -> list[Any]:
        """Dispatch the event. Returns results from each handler (most return None)."""
        if event_name not in EVENT_NAMES:
            raise ValueError(f"Unknown event: {event_name!r}")
        results: list[Any] = []
        for h in self._subscribers[event_name]:
            results.append(h(payload))
        for h in self._global_subscribers:
            h(event_name, payload)
        return results

    def clear(self) -> None:
        """Reset all subscriptions (between encounters)."""
        for name in EVENT_NAMES:
            self._subscribers[name] = []
        self._global_subscribers = []
