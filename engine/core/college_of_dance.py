"""College of Dance — Bard subclass (PHB 2024).

A nimble, melee-capable Bard that fights unarmored and weaves Unarmed Strikes
into its support. This module wires the combat-relevant features:

  - Dazzling Footwork (L3): while unarmored + no Shield —
      * Unarmored Defense: AC = 10 + DEX + CHA (build-time, pc_schema).
      * Bardic Damage: Unarmed Strikes use DEX and deal (Bardic Inspiration
        die + DEX) Bludgeoning — modeled as the a_dance_unarmed_strike action
        (built in pc_schema).
      * Agile Strikes: expending a Bardic Inspiration use lets you make one
        Unarmed Strike as part of that action/BA/Reaction — fired here as a
        rider on the Bardic Inspiration grant.
  - Inspiring Movement (L6), Tandem Footwork (L6), Leading Evasion (L14):
    see their own blocks / wiring.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState


def has_dazzling_footwork(actor: Actor) -> bool:
    """True if the actor has Dazzling Footwork (College of Dance L3+)."""
    features = (actor.template or {}).get("features_known") or []
    return "f_dazzling_footwork" in features


def _dance_unarmed_action(actor: Actor) -> dict | None:
    for a in (actor.template.get("actions") or []):
        if a.get("id") == "a_dance_unarmed_strike":
            return a
    return None


def fire_dance_unarmed_strike(actor: Actor, target: Actor,
                                state: CombatState, bus) -> bool:
    """Run one Dance Unarmed Strike (attack_roll + hit-gated damage) from
    `actor` against `target`, routed through the normal pipeline. Returns
    True if the swing was made. Mirrors reactions.execute_retaliation_strike."""
    action = _dance_unarmed_action(actor)
    if action is None or target is None or not target.is_alive():
        return False
    from engine.primitives import _invoke_subprimitive
    from engine.core.reactions import _evaluate_simple_condition
    saved_attack = state.current_attack
    state.current_attack = {
        "actor": actor, "target": target, "action": action,
        "state": None, "had_advantage": False, "had_disadvantage": False,
    }
    try:
        for step in (action.get("pipeline") or []):
            name = step.get("primitive")
            if name not in ("attack_roll", "damage"):
                continue
            when = step.get("when")
            if when:
                c = when.get("condition", "")
                if c and not _evaluate_simple_condition(c, state):
                    continue
            _invoke_subprimitive(step, state, bus)
    finally:
        state.current_attack = saved_attack
    return True


def apply_tandem_footwork(actors: list, rng, state: CombatState) -> None:
    """Tandem Footwork (College of Dance L6): each Dance Bard with the feature
    and an available Bardic Inspiration use (and not Incapacitated) expends
    one use at initiative, rolls its Bardic die, and adds the result to its
    own and each ally-within-30-ft's initiative.

    v1 heuristic: always spend a use when available (going first is worth a
    die, and Font of Inspiration refreshes BI on a short rest). Incapacitated
    is not yet tracked at initiative time, so that clause is a no-op guard."""
    from engine.core.bardic_inspiration import die_max
    from engine.core.geometry import distance_ft
    for bard in list(actors):
        if "f_tandem_footwork" not in (bard.template.get("features_known") or []):
            continue
        if not bard.is_alive():
            continue
        if int(bard.resources.get("bardic_inspiration_uses_remaining", 0)) <= 0:
            continue
        bard.resources["bardic_inspiration_uses_remaining"] -= 1
        die = str((bard.template or {}).get("bardic_die", "d6"))
        roll = rng.randint(1, die_max(die))
        beneficiaries = []
        for a in actors:
            if a.side != bard.side or not a.is_alive():
                continue
            if a.id != bard.id and distance_ft(bard.position, a.position) > 30:
                continue
            a.initiative += roll
            beneficiaries.append(a.id)
        state.event_log.append({
            "event": "tandem_footwork",
            "actor": bard.id,
            "die": die,
            "roll": roll,
            "beneficiaries": beneficiaries,
        })


def has_inspiring_movement(actor: Actor) -> bool:
    """True if the actor has Inspiring Movement (College of Dance L6+)."""
    features = (actor.template or {}).get("features_known") or []
    return "f_inspiring_movement" in features


def inspiring_movement_eligible(reactor: Actor, mover: Actor,
                                  state: CombatState) -> bool:
    """True if `reactor` (a Dance Bard) can use Inspiring Movement: it has the
    feature, the mover whose turn just ended is a living enemy it can see
    within 5 ft, and the reactor isn't that mover. (BI + reaction availability
    are checked by the reaction's feature_use / slot gates.)"""
    if not has_inspiring_movement(reactor):
        return False
    if mover is None or not mover.is_alive() or mover.id == reactor.id:
        return False
    if mover.side == reactor.side:
        return False
    from engine.core.geometry import distance_ft
    if distance_ft(reactor.position, mover.position) > 5:
        return False
    from engine.core.vision import can_actor_see
    if not can_actor_see(reactor, mover, state):
        return False
    return True


def _move_away(mover: Actor, threat_pos: tuple, max_ft: int) -> None:
    """Reposition `mover` directly away from `threat_pos` by up to `max_ft`
    (a clean reposition — no Opportunity Attacks, per RAW)."""
    from engine.core.geometry import unit_direction, SQUARE_SIZE_FT
    dx, dy = unit_direction(threat_pos, mover.position)   # threat → mover = away
    if (dx, dy) == (0, 0):
        dx, dy = 1, 0
    squares = max(0, int(max_ft) // SQUARE_SIZE_FT)
    if squares <= 0:
        return
    x, y = mover.position
    mover.position = (x + dx * squares, y + dy * squares)


def _nearest_enemy(actor: Actor, state: CombatState):
    from engine.core.geometry import distance_ft
    enemies = [e for e in state.encounter.actors
                if e.side != actor.side and e.is_alive()]
    if not enemies:
        return None
    return min(enemies, key=lambda e: distance_ft(actor.position, e.position))


def execute_inspiring_movement(reactor: Actor, mover: Actor,
                                 state: CombatState, bus) -> None:
    """Inspiring Movement: the Dance Bard moves up to half its Speed away from
    the triggering enemy (no OA), then one ally within 30 ft moves up to half
    its Speed away from its nearest enemy using its Reaction (no OA). The
    Bardic Inspiration use + the Bard's Reaction are consumed by the reaction
    gate. Agile Strikes (if the Bard has it) fires one Unarmed Strike at the
    adjacent triggering enemy as part of this Reaction (RAW: expending BI as
    part of a Reaction)."""
    from engine.core.geometry import distance_ft
    # Agile Strikes rider — expending BI as part of a Reaction.
    try_agile_strike_at(reactor, mover, state, bus)

    half = int((reactor.speed or {}).get("walk", 30)) // 2
    before = reactor.position
    _move_away(reactor, mover.position, half)

    # One ally within 30 ft (with a Reaction) repositions away from its
    # nearest enemy — pick the most threatened (closest to an enemy).
    ally = None
    candidates = [a for a in state.encounter.actors
                   if a.side == reactor.side and a.is_alive()
                   and a.id != reactor.id
                   and not a.actions_used_this_turn.get("reaction")
                   and distance_ft(reactor.position, a.position) <= 30]
    ally_before = None
    if candidates:
        def _threat(a):
            e = _nearest_enemy(a, state)
            return distance_ft(a.position, e.position) if e else 9999
        ally = min(candidates, key=_threat)
        enemy = _nearest_enemy(ally, state)
        if enemy is not None:
            ally_before = ally.position
            ally.actions_used_this_turn["reaction"] = True
            _move_away(ally, enemy.position,
                        int((ally.speed or {}).get("walk", 30)) // 2)

    state.event_log.append({
        "event": "inspiring_movement",
        "reactor": reactor.id,
        "trigger_enemy": mover.id,
        "moved_from": before, "moved_to": reactor.position,
        "ally": ally.id if ally else None,
        "ally_moved_from": ally_before,
        "ally_moved_to": ally.position if ally and ally_before else None,
    })


def try_agile_strike_at(actor: Actor, target: Actor, state: CombatState,
                          bus) -> None:
    """Agile Strikes against a SPECIFIC target (used by Inspiring Movement's
    Reaction). Fires one Dance Unarmed Strike if the actor has Dazzling
    Footwork and the target is within 5 ft."""
    if not has_dazzling_footwork(actor):
        return
    if _dance_unarmed_action(actor) is None:
        return
    from engine.core.geometry import distance_ft
    if target is None or not target.is_alive():
        return
    if distance_ft(actor.position, target.position) > 5:
        return
    state.event_log.append({
        "event": "agile_strike", "actor": actor.id, "target": target.id})
    fire_dance_unarmed_strike(actor, target, state, bus)


def try_agile_strike(actor: Actor, state: CombatState, bus) -> None:
    """Agile Strikes (Dazzling Footwork): when a Dance Bard expends a Bardic
    Inspiration use, make one Unarmed Strike as part of that action. Fired as
    a rider on the Bardic Inspiration grant — targets the lowest-HP enemy
    within the Dance Unarmed Strike's reach (5 ft). No-op without the feature
    / no enemy in reach."""
    if not has_dazzling_footwork(actor) or _dance_unarmed_action(actor) is None:
        return
    from engine.core.geometry import distance_ft
    enemies = [e for e in state.encounter.actors
                if e.side != actor.side and e.is_alive()
                and distance_ft(actor.position, e.position) <= 5]
    if not enemies:
        return
    try_agile_strike_at(actor, min(enemies, key=lambda e: e.hp_current),
                         state, bus)
