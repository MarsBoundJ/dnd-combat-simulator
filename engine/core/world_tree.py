"""Path of the World Tree — Barbarian subclass (PHB 2024 p.52-53).

A support/control/reach Barbarian path themed on Yggdrasil, the cosmic World
Tree. This module wires the combat-relevant features:

  - Vitality of the Tree (L3): rage-scoped Temporary HP.
      * Vitality Surge: on rage entry, gain Temp HP = Barbarian level.
      * Life-Giving Force: at the start of each of your turns while raging,
        grant an ally within 10 ft Temp HP = sum of Nd6 (N = Rage Damage
        bonus). All World-Tree Temp HP vanishes when the Rage ends.

  - Branches of the Tree (L6): reaction control (see this module's L6 block).
  - Battering Roots (L10): +10 ft reach with Heavy/Versatile melee + a
    Push/Topple rider (see L10 block).
  - Travel along the Tree (L14): teleport mobility (see L14 block).

Vitality is activated on the shared `enter_rage` hook (like Rage of the
Gods / Rage of the Wilds); Life-Giving Force fires from the runner's
turn-start; the rage-scoped Temp HP is cleared on `end_rage`.
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState


def _barbarian_level(actor: Actor) -> int:
    levels = (actor.template or {}).get("levels") or {}
    return int(levels.get("barbarian", 0))


# ============================================================================
# Vitality of the Tree (L3)
# ============================================================================

def has_vitality_of_the_tree(actor: Actor) -> bool:
    """True if the actor has Vitality of the Tree (World Tree L3+)."""
    features = (actor.template or {}).get("features_known") or []
    return "f_vitality_of_the_tree" in features


def _grant_temp_hp(creature: Actor, amount: int) -> int:
    """Grant Temp HP with RAW max-semantics (no stacking — keep the greater).
    Marks the recipient so World-Tree Temp HP can be cleared on rage end.
    Returns the creature's resulting Temp HP."""
    if amount > creature.temp_hp:
        creature.temp_hp = amount
    creature._world_tree_temp_hp = True
    return creature.temp_hp


def apply_vitality_surge(actor: Actor, state: CombatState) -> None:
    """Vitality Surge: on rage entry, the barbarian gains Temp HP equal to
    their Barbarian level (max-semantics). No-op without the feature."""
    if not has_vitality_of_the_tree(actor):
        return
    amount = _barbarian_level(actor)
    if amount <= 0:
        return
    _grant_temp_hp(actor, amount)
    state.event_log.append({
        "event": "vitality_surge",
        "actor": actor.id,
        "temp_hp": amount,
        "final_temp_hp": actor.temp_hp,
    })


def resolve_life_giving_force(actor: Actor, state: CombatState,
                                rng: random.Random) -> None:
    """Life-Giving Force: at the start of the barbarian's turn while raging,
    grant an ally within 10 ft Temp HP = sum of Nd6 (N = Rage Damage bonus).

    v1 beneficiary policy: the most-wounded living ally (lowest HP fraction)
    within 10 ft — Temp HP is most valuable on whoever is likeliest to take
    the next hit. No-op without the feature / not raging / no rage bonus /
    no ally in range."""
    if not has_vitality_of_the_tree(actor):
        return
    if not getattr(actor, "rage_active", False):
        return
    n = int(getattr(actor, "rage_damage_bonus", 0))
    if n <= 0:
        return
    from engine.core.geometry import distance_ft
    in_range = [a for a in state.encounter.actors
                if a.id != actor.id and a.side == actor.side and a.is_alive()
                and distance_ft(actor.position, a.position) <= 10]
    if not in_range:
        return
    beneficiary = min(in_range,
                       key=lambda a: a.hp_current / max(1, a.hp_max))
    rolled = sum(rng.randint(1, 6) for _ in range(n))
    _grant_temp_hp(beneficiary, rolled)
    state.event_log.append({
        "event": "life_giving_force",
        "actor": actor.id,
        "target": beneficiary.id,
        "dice": n,
        "temp_hp": rolled,
        "final_temp_hp": beneficiary.temp_hp,
    })


def clear_world_tree_temp_hp(actor: Actor, state: CombatState) -> None:
    """On rage end, World-Tree Temp HP vanishes (RAW: "If any of these
    Temporary Hit Points remain when your Rage ends, they vanish"). Clears
    the marker + Temp HP on the barbarian AND every creature it buffed.

    v1 simplification: with multiple World Tree barbarians raging at once,
    one ending its Rage clears all World-Tree Temp HP (the marker isn't
    per-source). Rare; documented."""
    if not has_vitality_of_the_tree(actor):
        return
    for a in state.encounter.actors:
        if getattr(a, "_world_tree_temp_hp", False):
            if a.temp_hp > 0:
                state.event_log.append({
                    "event": "world_tree_temp_hp_vanished",
                    "creature": a.id,
                    "lost": a.temp_hp,
                })
            a.temp_hp = 0
            a._world_tree_temp_hp = False
