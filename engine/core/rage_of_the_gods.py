"""Rage of the Gods — Path of the Zealot, Barbarian L14 (PHB 2024 / SRD CC v5.2.1).

RAW: "When you activate your Rage, you can assume the form of a divine
warrior (1/Long Rest):
  - Flight: Fly Speed = Speed, hover.
  - Resistance: Necrotic, Psychic, and Radiant damage.
  - Revivification (Reaction): When a creature within 30 ft would drop to 0
    HP, expend one Rage use to set that creature's HP to your Barbarian level."

Engine modeling:

  - `try_activate_rage_of_the_gods`: called from `enter_rage` when the
    raging actor has `f_rage_of_the_gods` and a remaining use. Activates
    the form by:
      1. Decrementing `rage_of_the_gods_uses_remaining`.
      2. Stamping `actor.rage_of_the_gods_active = True`.
      3. Granting a Fly Speed equal to the actor's walk speed (stored as
         `actor.speed["fly"]`); the prior value (typically absent) is
         saved in `_rage_of_the_gods_prior_fly` for clean teardown.

  - `deactivate_rage_of_the_gods`: called from `end_rage`. Clears the flag
    and reverts fly speed.

  - `applies_resistance`: checked in `primitives._damage` for N/P/R
    damage types. Mirrors `applies_rage_bps_resistance` in rage.py.

  - Revivification reaction: wired via the `creature_would_drop_to_zero`
    trigger in `primitives._damage` (fires at target.hp_current == 0,
    before death processing). The condition `revivification_would_save`
    in `reactions._reaction_condition_satisfied` gates it; the
    `_revivification_save` primitive in primitives.py executes it.

  - Resource: `rage_of_the_gods_uses_remaining` / `_max` (1/long rest).
    The Rage-use refund ("unless you expend a Rage use to restore it") is
    deferred — v1 ships the basic 1/long-rest model.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState

_RESISTED_TYPES = frozenset({"necrotic", "psychic", "radiant"})


def has_rage_of_the_gods(actor: Actor) -> bool:
    """True if the actor has Rage of the Gods (Zealot L14+)."""
    features = (actor.template or {}).get("features_known") or []
    return "f_rage_of_the_gods" in features


def _barbarian_level(actor: Actor) -> int:
    levels = (actor.template or {}).get("levels") or {}
    return int(levels.get("barbarian", 0))


def try_activate_rage_of_the_gods(actor: Actor, state: CombatState) -> bool:
    """If eligible, activate the Rage of the Gods divine form.

    Called from `enter_rage` AFTER the actor is already raging (the flag
    and damage bonus are already set). Returns True if activated.
    """
    if not has_rage_of_the_gods(actor):
        return False
    uses = int(actor.resources.get("rage_of_the_gods_uses_remaining", 0))
    if uses <= 0:
        return False

    actor.resources["rage_of_the_gods_uses_remaining"] = uses - 1
    actor.rage_of_the_gods_active = True

    # Fly Speed = walk speed (hover: the form lets you stay aloft)
    walk = actor.speed.get("walk", 30)
    actor._rage_of_the_gods_prior_fly = actor.speed.get("fly")
    actor.speed["fly"] = walk

    state.event_log.append({
        "event": "rage_of_the_gods_activated",
        "actor": actor.id,
        "fly_speed": walk,
        "uses_remaining": uses - 1,
    })
    return True


def deactivate_rage_of_the_gods(actor: Actor, state: CombatState) -> None:
    """Clear the divine form when Rage ends. Idempotent."""
    if not getattr(actor, "rage_of_the_gods_active", False):
        return
    actor.rage_of_the_gods_active = False

    # Revert fly speed to whatever it was before activation
    prior_fly = getattr(actor, "_rage_of_the_gods_prior_fly", None)
    if prior_fly is None:
        actor.speed.pop("fly", None)
    else:
        actor.speed["fly"] = prior_fly

    state.event_log.append({
        "event": "rage_of_the_gods_deactivated",
        "actor": actor.id,
    })


def applies_resistance(target: Actor, damage_type: str) -> bool:
    """True if Rage of the Gods grants resistance to this damage type."""
    return (getattr(target, "rage_of_the_gods_active", False)
            and damage_type in _RESISTED_TYPES)


def revivification_eligible_reactor(reactor: Actor, target: Actor,
                                     state: CombatState) -> bool:
    """True if `reactor` can use Revivification to save `target`.

    Gates:
      - reactor has f_rage_of_the_gods and rage_of_the_gods_active
      - reactor is raging
      - reactor has rage_uses_remaining > 0
      - reactor is within 30 ft of target (skeleton: position-based)
      - target is a different creature on the same side as the reactor
    """
    if not getattr(reactor, "rage_of_the_gods_active", False):
        return False
    if not getattr(reactor, "rage_active", False):
        return False
    if int(reactor.resources.get("rage_uses_remaining", 0)) <= 0:
        return False
    if reactor.id == target.id:
        return False
    if reactor.side != target.side:
        return False
    from engine.core.geometry import distance_ft
    if distance_ft(reactor.position, target.position) > 30:
        return False
    return True


def execute_revivification(reactor: Actor, target: Actor,
                            state: CombatState) -> None:
    """Spend a Rage use and restore target's HP to the Barbarian level."""
    uses = int(reactor.resources.get("rage_uses_remaining", 0))
    reactor.resources["rage_uses_remaining"] = max(0, uses - 1)
    reactor.actions_used_this_turn["reaction"] = True

    restored_hp = max(1, _barbarian_level(reactor))
    target.hp_current = restored_hp
    if getattr(target, "is_dying", False):
        target.is_dying = False
        target.death_save_successes = 0
        target.death_save_failures = 0

    state.event_log.append({
        "event": "revivification_used",
        "reactor": reactor.id,
        "target": target.id,
        "hp_restored": restored_hp,
        "rage_uses_remaining": reactor.resources.get("rage_uses_remaining", 0),
    })
