"""Monster passive-trait substrate — shared helpers for MM-style traits.

A handful of 2024 Monster Manual traits are mechanical rather than narrative
and need engine wiring. They share a common shape: a passive entry in the
monster's `traits:` list (id + name + type: trait_passive) whose effect is
consulted at the relevant resolution point. This module centralises the
trait-presence / state checks so each consumer (modifiers, evasion, the
multiattack executor, the damage primitive) reads off one source of truth.

Wired traits:
  - t_displacement  (Displacer Beast): attacks against the creature have
    Disadvantage unless it is Incapacitated. Consulted in
    modifiers.query_attack_modifiers (the disadvantage twin of the Wolf/Lion
    auras — an identity-state read off the target template).
  - t_avoidance     (Displacer Beast): Evasion for ANY saving throw, not just
    DEX (success → 0 damage, fail → half). Consulted via evasion.py's
    select_avoidance_subs in primitives._forced_save.
  - t_bloodied_fury (Quaggoth Thonot): while Bloodied (HP ≤ half max) the
    creature makes one extra attack as part of its Multiattack. Consulted in
    pipeline._execute_multiattack.
  - t_fear_of_fire  (Yeti): if the creature takes fire damage, it has
    Disadvantage on attack rolls until the end of its next turn. Consulted in
    primitives._damage (registers a self-disadvantage modifier on fire damage).
"""
from __future__ import annotations

from engine.core.state import Actor


def has_trait(actor: Actor, trait_id: str) -> bool:
    """True if `actor`'s template declares a passive trait with id `trait_id`."""
    for t in ((actor.template or {}).get("traits") or []):
        if t.get("id") == trait_id:
            return True
    return False


def is_incapacitated(actor: Actor) -> bool:
    """True if `actor` currently has the Incapacitated condition."""
    return any(c.get("condition_id") == "co_incapacitated"
               for c in actor.applied_conditions)


def is_bloodied(actor: Actor) -> bool:
    """True if `actor` is Bloodied: alive and at or below half its max HP
    (RAW 2024: "a creature is Bloodied while it has half its Hit Points or
    fewer")."""
    if actor.hp_current <= 0 or actor.hp_max <= 0:
        return False
    return actor.hp_current * 2 <= actor.hp_max


def imposes_attack_disadvantage(target: Actor) -> bool:
    """True if attacks against `target` should have Disadvantage due to the
    Displacement trait: the target has t_displacement and is not
    Incapacitated (RAW: Displacement is suppressed while Incapacitated)."""
    return has_trait(target, "t_displacement") and not is_incapacitated(target)
