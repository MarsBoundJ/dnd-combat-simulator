"""Ability selection dial — pick which action the actor uses on its turn.

Preset behaviors:

| Preset       | Behavior                                                     |
|--------------|--------------------------------------------------------------|
| mindless     | Use the first action; never adapt.                           |
| instinctive  | Prefer a signature action if flagged; else first.            |
| default      | Prefer multiattack > weapon_attack > anything else.          |
| tactical     | Pick the highest-eHP action against the chosen target.       |
| optimal      | Same as tactical for v1 (joint (target × ability) optimization|
|              | deferred until full eHP layer covers defensive/control eHP). |

The `tactical` preset now consults `engine.ai.ehp_scoring.best_action_against`
to evaluate every action's expected HP delivered vs the chosen target and
pick the winner. This makes Tactical creatures actually exploit conditions:
if the target is Blinded (attacker advantage), the action with the largest
single-hit damage roll wins; against a Restrained target, similar logic.

`optimal` will eventually be different (full eHP joint optimization across
both target and action together, including defensive options). For v1 it
shares the tactical implementation — documented limitation.
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
    """Pick the highest-eHP action against the chosen target.

    Delegates to ehp_scoring.best_action_against, which evaluates each
    action via the offensive-eHP formula (hit_prob × damage_mean) including
    active_modifier effects (advantage from Blinded, etc.). With no target
    we fall back to the default priority.
    """
    # Lazy import — ehp_scoring imports modifiers which is heavyweight to
    # load at package-init; keep this hot path light when not used.
    from engine.ai.ehp_scoring import best_action_against

    if target is None:
        return _pick_default(actor, actions, target, state)
    best = best_action_against(actor, target, state, actions)
    return best if best is not None else _pick_default(actor, actions,
                                                        target, state)


def _pick_optimal(actor: Actor, actions: list[dict], target: Actor | None,
                   state: CombatState) -> dict:
    """v1: same as tactical. Full joint (target × ability) optimization
    deferred until the eHP layer includes defensive / control / healing
    eHP formulas — at that point optimal can compare 'attack target A with
    longsword' vs 'cast Hold Person on target B' on a single eHP scale.
    """
    return _pick_tactical(actor, actions, target, state)


_PRESET_HANDLERS: dict[str, Callable[..., dict]] = {
    "mindless": _pick_mindless,
    "instinctive": _pick_instinctive,
    "default": _pick_default,
    "tactical": _pick_tactical,
    "optimal": _pick_optimal,
}
