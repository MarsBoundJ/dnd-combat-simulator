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


# ============================================================================
# Battering Roots (L10)
# ============================================================================
#
# "During your turn, your reach is 10 feet greater with any Melee weapon
# that has the Heavy or Versatile property... When you hit with such a weapon
# on your turn, you can activate the Push or Topple mastery property in
# addition to a different mastery property you're using with that weapon."
#
# NOT rage-gated (RAW: "During your turn"). The +10 reach is baked into
# qualifying weapon actions at build time (pc_schema), which flags them with
# `battering_roots: True` in the attack_roll params. This rider reads that
# flag and applies Topple (CON save → Prone) on a qualifying on-turn hit —
# v1 picks Topple (best control for a melee build); Push is the documented
# alternative.

def has_battering_roots(actor: Actor) -> bool:
    """True if the actor has Battering Roots (World Tree L10+)."""
    features = (actor.template or {}).get("features_known") or []
    return "f_battering_roots" in features


def _battering_roots_topple_dc(actor: Actor) -> int:
    """Topple save DC = 8 + STR modifier + Proficiency Bonus (RAW mastery DC)."""
    str_score = (actor.abilities.get("str") or {}).get("score", 10)
    pb = int((actor.template.get("cr") or {}).get("proficiency_bonus", 2))
    return 8 + (str_score - 10) // 2 + pb


def try_apply_battering_roots(actor: Actor, target: Actor,
                                state: CombatState,
                                attack_params: dict | None) -> None:
    """On a hit with a Heavy/Versatile melee weapon on the barbarian's OWN
    turn, apply the Topple mastery (CON save or Prone) even without the
    mastery. Gated on the `battering_roots` flag baked into the weapon's
    attack params. Idempotent on already-prone targets. No bonus damage."""
    if not has_battering_roots(actor):
        return
    if not (attack_params or {}).get("battering_roots"):
        return
    if (attack_params or {}).get("kind", "melee") != "melee":
        return
    # "On your turn" — not Opportunity Attacks / reactions.
    if state.current_actor() is not actor:
        return
    if any(c.get("condition_id") == "co_prone"
            for c in target.applied_conditions):
        return
    from engine.core.weapon_masteries import _mastery_topple
    _mastery_topple(actor, target, state,
                     {"save_dc": _battering_roots_topple_dc(actor)})
    state.event_log.append({
        "event": "battering_roots",
        "actor": actor.id,
        "target": target.id,
        "effect": "topple",
    })


def extend_battering_roots_reach(weapon_actions: list, weapons_list: list,
                                   features_known) -> None:
    """Bake Battering Roots' +10 ft reach into qualifying weapon actions and
    flag them with `battering_roots: True`. A qualifying weapon is a MELEE
    weapon (reach_ft, not range_ft) with the Heavy or Versatile property.

    Called from pc_schema.build_pc_template once features_known is finalized.
    No-op without the feature.

    v1 simplification: the reach is baked statically, so it also applies to
    off-turn Opportunity Attacks (RAW limits the bonus to "during your turn").
    OAs are a minor damage source; the over-reach is a documented edge."""
    if "f_battering_roots" not in features_known:
        return
    for w_spec, w_action in zip(weapons_list, weapon_actions):
        if "range_ft" in w_spec:
            continue   # ranged weapon — Battering Roots is melee-only
        if not (w_spec.get("heavy") or w_spec.get("versatile")):
            continue
        for step in (w_action.get("pipeline") or []):
            if step.get("primitive") == "attack_roll":
                params = step.setdefault("params", {})
                params["reach_ft"] = int(params.get("reach_ft", 5)) + 10
                params["battering_roots"] = True


# ============================================================================
# Branches of the Tree (L6)
# ============================================================================
#
# "Whenever a creature you can see starts its turn within 30 feet of you
# while your Rage is active, you can take a Reaction to summon spectral
# branches of the World Tree around it. The target must succeed on a Strength
# saving throw (DC 8 + STR + PB) or be teleported to an unoccupied space you
# can see within 5 feet of yourself or in the nearest unoccupied space you
# can see. After the target teleports, you can reduce its Speed to 0 until
# the end of the current turn."
#
# Wired via the generic reaction system: a `creature_turn_start` trigger
# (dispatched by the runner at each creature's turn start), the
# `branches_of_the_tree_would_pull` condition, and the `branches_pull`
# primitive (this module's execute_branches_pull). On a failed STR save the
# mover is teleported adjacent to the barbarian and its Speed drops to 0 for
# the turn — yanking an enemy into the barbarian's reach and pinning it.


def has_branches_of_the_tree(actor: Actor) -> bool:
    """True if the actor has Branches of the Tree (World Tree L6+)."""
    features = (actor.template or {}).get("features_known") or []
    return "f_branches_of_the_tree" in features


def _branches_save_dc(actor: Actor) -> int:
    """STR save DC = 8 + STR modifier + Proficiency Bonus (martial DC)."""
    str_score = (actor.abilities.get("str") or {}).get("score", 10)
    pb = int((actor.template.get("cr") or {}).get("proficiency_bonus", 2))
    return 8 + (str_score - 10) // 2 + pb


def branches_eligible_reactor(reactor: Actor, mover: Actor,
                                state: CombatState) -> bool:
    """True if `reactor` can use Branches of the Tree on `mover`: the reactor
    has the feature + is raging, the mover is a living enemy it can see
    within 30 ft, and the mover isn't the reactor itself."""
    if not has_branches_of_the_tree(reactor):
        return False
    if not getattr(reactor, "rage_active", False):
        return False
    if mover is None or not mover.is_alive():
        return False
    if mover.id == reactor.id:
        return False
    if mover.side == reactor.side:
        return False
    from engine.core.geometry import distance_ft
    if distance_ft(reactor.position, mover.position) > 30:
        return False
    from engine.core.vision import can_actor_see
    if not can_actor_see(reactor, mover, state):
        return False
    return True


def _occupied_positions(state: CombatState) -> set:
    return {a.position for a in state.encounter.actors if a.is_alive()}


def _unoccupied_square_near(center: tuple, occupied: set,
                              max_ring: int = 3) -> tuple | None:
    """First unoccupied square within `max_ring` squares of `center`
    (excluding center), scanning outward ring by ring (nearest first)."""
    cx, cy = center
    for ring in range(1, max_ring + 1):
        for dx in range(-ring, ring + 1):
            for dy in range(-ring, ring + 1):
                if max(abs(dx), abs(dy)) != ring:
                    continue
                sq = (cx + dx, cy + dy)
                if sq not in occupied:
                    return sq
    return None


def execute_branches_pull(reactor: Actor, mover: Actor,
                            state: CombatState) -> None:
    """Resolve Branches of the Tree: the mover makes a STR save vs the
    reactor's martial DC; on a failure it is teleported to an unoccupied
    square adjacent to the reactor and its walk Speed drops to 0 for the
    turn (restored at the mover's next turn start)."""
    import engine.primitives as primitives_module
    rng = primitives_module._rng
    dc = _branches_save_dc(reactor)
    save_mod = int((mover.abilities.get("str") or {}).get("save", 0))
    d20 = rng.randint(1, 20)
    total = d20 + save_mod
    saved = total >= dc
    state.event_log.append({
        "event": "branches_of_the_tree_save",
        "reactor": reactor.id,
        "target": mover.id,
        "d20": d20, "save_mod": save_mod, "total": total, "dc": dc,
        "outcome": "saved" if saved else "failed",
    })
    if saved:
        return

    # Teleport: unoccupied square adjacent to (nearest free space near) reactor.
    occupied = _occupied_positions(state)
    occupied.discard(mover.position)   # the mover's current square frees up
    dest = _unoccupied_square_near(reactor.position, occupied)
    if dest is not None:
        mover.position = dest

    # Speed 0 until end of the current turn (restored at the mover's next
    # turn start by restore_branches_speed).
    mover._branches_speed_data = {"original_walk": mover.speed.get("walk", 30)}
    mover.speed = dict(mover.speed)
    mover.speed["walk"] = 0

    state.event_log.append({
        "event": "branches_of_the_tree_pull",
        "reactor": reactor.id,
        "target": mover.id,
        "teleported_to": dest,
        "speed_set_to": 0,
    })


def restore_branches_speed(actor: Actor, state: CombatState) -> None:
    """Restore an actor's walk Speed that Branches reduced to 0 last turn.
    Called at the actor's turn start, before Branches may re-fire."""
    data = getattr(actor, "_branches_speed_data", None)
    if not data:
        return
    actor.speed = dict(actor.speed)
    actor.speed["walk"] = int(data.get("original_walk", 30))
    actor._branches_speed_data = None
    state.event_log.append({
        "event": "branches_of_the_tree_speed_restored",
        "actor": actor.id,
        "walk": actor.speed["walk"],
    })
