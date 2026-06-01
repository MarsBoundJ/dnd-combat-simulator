"""Swallow / Engulf — restrain-and-internalize (Behir, Purple Worm,
Remorhaz, Gelatinous Cube).

RAW (SRD 5.2.1, Behir): "Swallow. Dexterity Saving Throw: DC 18, one Large
or smaller creature Grappled by the behir. Failure: the behir swallows the
target, which is no longer Grappled. While swallowed, a creature has the
Blinded and Restrained conditions, has Total Cover against attacks and
other effects outside the behir, and takes 21 (6d6) Acid damage at the
start of each of the behir's turns."

Modeling (v1 — the load-bearing combat effects):
  - The Swallow action's pipeline is a DEX `forced_save`; its `on_fail`
    applies Blinded + Restrained (via apply_condition, sourced to the
    swallower so release can remove them) then runs the `swallow_apply`
    primitive, which sets Total Cover and records the swallow on the
    target (`swallowed_by`, `swallow_damage`). The swallowed creature is
    co-located with the swallower (it's inside) so it can still attack the
    swallower from within while outside attackers are blocked by Total
    Cover.
  - Ongoing damage: at the SWALLOWER's turn start the runner calls `tick`,
    dealing `swallow_damage` to the creature it has swallowed.
  - Release: the swallower's death frees the swallowed creature
    (primitives._damage death site → `release`). `release` removes the two
    conditions (by source), clears Total Cover, and clears the tracking
    fields.

v1 deferrals (documented):
  - Regurgitate counterplay (Behir: 30+ damage in a turn from the
    swallowed creature → CON save or expel + Prone) — needs per-turn
    damage-from-inside tracking + an end-of-turn save. Until then the
    swallowed creature is freed by killing the swallower.
  - Engulf-on-movement entry (Gelatinous Cube enters spaces as it moves)
    and multi-capacity (cube holds 4 Medium) — v1 models the single-target
    save-then-internalize shape; the cube can use the same swallow_apply
    on a DEX save.
  - The "grappled first" precondition (Behir) is not enforced — the
    Swallow action targets the current enemy; positioning/grapple gating
    is a candidate-layer refinement.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState

_SWALLOW_CONDITIONS = ("co_blinded", "co_restrained")


def is_swallowed(actor: Actor) -> bool:
    return actor.swallowed_by is not None


def find_swallowed(swallower: Actor, state: CombatState) -> Actor | None:
    """The creature `swallower` currently has swallowed, if any (one at a
    time in v1)."""
    for a in state.encounter.actors:
        if a.swallowed_by == swallower.id:
            return a
    return None


def apply(swallower: Actor, target: Actor, params: dict,
          state: CombatState) -> None:
    """Mark `target` swallowed by `swallower`: Total Cover + tracking +
    ongoing-damage spec. (Blinded/Restrained are applied by the preceding
    apply_condition steps in the Swallow action's on_fail.) The target is
    pulled to the swallower's space (it's inside)."""
    target.cover = "total"
    target.swallowed_by = swallower.id
    target.swallow_damage = {
        "dice": params.get("acid_dice", "6d6"),
        "type": params.get("acid_type", "acid"),
    }
    # Optional regurgitate spec: if the swallower takes `threshold`+ damage
    # from this victim in one turn it must save or expel it. Omitted →
    # no regurgitate counterplay (victim freed only by killing the
    # swallower).
    if params.get("regurgitate_threshold"):
        target.swallow_regurgitate = {
            "threshold": int(params["regurgitate_threshold"]),
            "dc": int(params.get("regurgitate_dc", 14)),
            "save": params.get("regurgitate_save", "constitution"),
        }
    swallower.swallow_damage_taken_this_turn = 0
    target.position = swallower.position   # inside the swallower
    state.event_log.append({
        "event": "swallowed", "swallower": swallower.id,
        "target": target.id, "damage": target.swallow_damage,
    })


def release(swallowed: Actor, state: CombatState, *, reason: str) -> None:
    """Free a swallowed creature: drop Blinded + Restrained (sourced to the
    swallower), clear Total Cover, and clear the tracking fields. No-op if
    the creature isn't swallowed."""
    if swallowed.swallowed_by is None:
        return
    from engine.primitives import remove_condition
    source = swallowed.swallowed_by
    for cond in _SWALLOW_CONDITIONS:
        remove_condition(swallowed, cond, source)
    swallowed.cover = "none"
    swallowed.swallowed_by = None
    swallowed.swallow_damage = None
    swallowed.swallow_regurgitate = None
    state.event_log.append({
        "event": "swallow_released", "creature": swallowed.id,
        "reason": reason,
    })


def release_victims_of(swallower: Actor, state: CombatState, *,
                         reason: str) -> None:
    """Release whatever `swallower` had swallowed (called on its death)."""
    victim = find_swallowed(swallower, state)
    if victim is not None:
        release(victim, state, reason=reason)


def tick(swallower: Actor, state: CombatState, primitives, bus) -> None:
    """At the swallower's turn start, deal its ongoing acid to the creature
    it has swallowed. No-op if it hasn't swallowed anyone."""
    victim = find_swallowed(swallower, state)
    if victim is None or victim.swallow_damage is None:
        return
    spec = victim.swallow_damage
    saved_attack = state.current_attack
    state.current_attack = {
        "actor": swallower, "target": victim, "state": "hit",
        "action": {"id": "swallow_acid"},
        "had_advantage": False, "had_disadvantage": False,
    }
    try:
        primitives.invoke("damage", {
            "dice": spec.get("dice", "6d6"), "modifier": 0,
            "type": spec.get("type", "acid"),
        }, state, bus)
    finally:
        state.current_attack = saved_attack
    state.event_log.append({
        "event": "swallow_acid_tick", "swallower": swallower.id,
        "target": victim.id, "hp_remaining": victim.hp_current,
    })


def note_damage_to_swallower(attacker: Actor, target: Actor,
                               amount: int) -> None:
    """Accumulate damage a swallowed creature deals to its swallower this
    turn (feeds the regurgitate check). Called from primitives._damage."""
    if amount > 0 and attacker.swallowed_by == target.id:
        target.swallow_damage_taken_this_turn += int(amount)


def reset_turn_damage(actor: Actor, state: CombatState) -> None:
    """At the start of a swallowed creature's turn, zero its swallower's
    per-turn damage accumulator so the regurgitate threshold is measured
    over this turn only. No-op if `actor` isn't swallowed."""
    if actor.swallowed_by is None:
        return
    for a in state.encounter.actors:
        if a.id == actor.swallowed_by:
            a.swallow_damage_taken_this_turn = 0
            return


def check_regurgitate(victim: Actor, state: CombatState, primitives,
                        bus) -> None:
    """At the end of a swallowed creature's turn: if its swallower took
    `threshold`+ damage from it this turn, the swallower makes a save (via
    forced_save, so Legendary Resistance applies); on a failure it expels
    the victim, which is freed and falls Prone. The per-turn accumulator is
    reset afterward. No-op if the creature isn't swallowed or has no
    regurgitate spec."""
    spec = victim.swallow_regurgitate
    if victim.swallowed_by is None or not spec:
        return
    swallower = None
    for a in state.encounter.actors:
        if a.id == victim.swallowed_by:
            swallower = a
            break
    if swallower is None:
        return
    taken = swallower.swallow_damage_taken_this_turn
    if taken < int(spec["threshold"]):
        swallower.swallow_damage_taken_this_turn = 0
        return
    # Threshold met → the swallower saves or regurgitates.
    saved_attack = state.current_attack
    state.current_attack = {
        "actor": victim, "target": swallower, "state": None,
        "had_advantage": False, "had_disadvantage": False,
    }
    try:
        primitives.invoke("forced_save", {
            "ability": spec.get("save", "constitution"),
            "dc": int(spec["dc"]), "affected": "current_target",
            "on_fail": [], "on_success": [],
        }, state, bus)
        outcome = (state.current_save or {}).get("outcome")
    finally:
        state.current_attack = saved_attack
    swallower.swallow_damage_taken_this_turn = 0
    state.event_log.append({
        "event": "regurgitate_check", "swallower": swallower.id,
        "victim": victim.id, "damage_taken": taken, "outcome": outcome,
    })
    if outcome == "fail":
        release(victim, state, reason="regurgitated")
        # The expelled creature falls Prone.
        prone_attack = state.current_attack
        state.current_attack = {"actor": swallower, "target": victim,
                                 "had_advantage": False,
                                 "had_disadvantage": False}
        try:
            primitives.invoke("apply_condition", {
                "condition_id": "co_prone", "duration": "until_removed",
            }, state, bus)
        finally:
            state.current_attack = prone_attack
