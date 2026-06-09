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


def try_agile_strike(actor: Actor, state: CombatState, bus) -> None:
    """Agile Strikes (Dazzling Footwork): when a Dance Bard expends a Bardic
    Inspiration use, make one Unarmed Strike as part of that action. Fired as
    a rider on the Bardic Inspiration grant — targets the lowest-HP enemy
    within the Dance Unarmed Strike's reach (5 ft). No-op without the feature
    / no enemy in reach."""
    if not has_dazzling_footwork(actor):
        return
    action = _dance_unarmed_action(actor)
    if action is None:
        return
    reach = 5
    from engine.core.geometry import distance_ft
    enemies = [e for e in state.encounter.actors
                if e.side != actor.side and e.is_alive()
                and distance_ft(actor.position, e.position) <= reach]
    if not enemies:
        return
    target = min(enemies, key=lambda e: e.hp_current)
    state.event_log.append({
        "event": "agile_strike",
        "actor": actor.id,
        "target": target.id,
    })
    fire_dance_unarmed_strike(actor, target, state, bus)
