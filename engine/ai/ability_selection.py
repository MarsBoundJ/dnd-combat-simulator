"""Ability selection dial — pick which action the actor uses on its turn.

v1 implementation is minimal: a priority order over action types
(multiattack beats single weapon attacks; otherwise first listed).
Full Ammann + eHP scoring per pillars-reconciliation.md §5.2 is
deferred to the eHP-scoring PR.

Preset behaviors (v1):

| Preset       | Behavior                                                    |
|--------------|-------------------------------------------------------------|
| mindless     | Use the first action; never adapt.                          |
| instinctive  | Prefer a signature action if flagged; else first.           |
| default      | Prefer multiattack > weapon_attack > anything else.         |
| tactical     | Same as default for v1 (eHP-scored selection deferred).     |
| optimal      | Same as default for v1 (joint optimization deferred).       |
"""
from __future__ import annotations

from typing import Callable

from engine.core.state import Actor, CombatState


ABILITY_SELECTION_PRESETS = (
    "mindless",
    "instinctive",
    "default",
    "tactical",
    "optimal",
)


def pick_action(actor: Actor, target: Actor | None, state: CombatState,
                 preset: str) -> dict | None:
    """Pick the actor's action for this turn given an ability-selection preset.

    Returns the action dict from actor.template.actions, or None if no
    usable actions.
    """
    actions = actor.template.get("actions") or []
    if not actions:
        return None

    handler = _PRESET_HANDLERS.get(preset, _pick_default)
    return handler(actor, actions, target, state)


# ============================================================================
# Preset implementations
# ============================================================================

def _pick_mindless(actor: Actor, actions: list[dict], target: Actor | None,
                    state: CombatState) -> dict:
    """Always pick the first action — no adaptation."""
    return actions[0]


def _pick_instinctive(actor: Actor, actions: list[dict], target: Actor | None,
                       state: CombatState) -> dict:
    """Prefer a signature-flagged action; else first."""
    for a in actions:
        if a.get("is_signature"):
            return a
    return actions[0]


def _pick_default(actor: Actor, actions: list[dict], target: Actor | None,
                   state: CombatState) -> dict:
    """Priority: multiattack > weapon_attack > anything else.

    Multiattack is strictly better than a single weapon attack when both
    are available (more attacks per turn). This priority captures that
    without needing full eHP scoring.
    """
    multiattacks = [a for a in actions if a.get("type") == "multiattack"]
    if multiattacks:
        return multiattacks[0]
    weapon_attacks = [a for a in actions if a.get("type") == "weapon_attack"]
    if weapon_attacks:
        return weapon_attacks[0]
    return actions[0]


def _pick_tactical(actor: Actor, actions: list[dict], target: Actor | None,
                    state: CombatState) -> dict:
    """v1: same as default. Tactical scoring with eHP is deferred."""
    return _pick_default(actor, actions, target, state)


def _pick_optimal(actor: Actor, actions: list[dict], target: Actor | None,
                   state: CombatState) -> dict:
    """v1: same as default. Joint (target × ability) optimization deferred."""
    return _pick_default(actor, actions, target, state)


_PRESET_HANDLERS: dict[str, Callable[..., dict]] = {
    "mindless": _pick_mindless,
    "instinctive": _pick_instinctive,
    "default": _pick_default,
    "tactical": _pick_tactical,
    "optimal": _pick_optimal,
}
