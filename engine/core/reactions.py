"""Reactions — opportunity attacks triggered by movement.

Per `pillars-reconciliation.md` §5.4: reactions are one of two cognitive-
load tiers within the Action Economy dial. Opportunity Attacks are the
"OA-type reactions" — instinctive, low-decision-overhead. Even mindless
creatures take them ("they moved, I swing"). The AE dial's `oa_reaction`
percentage (80-100% across all 5 presets) gates whether the reaction
actually fires.

**v1 scope:**
  - Trigger: a creature `A` moved out of creature `B`'s melee reach
    (`B`'s reach was satisfied at `A`'s pre-move position but not at
    its post-move position).
  - One OA per reactor per round (uses `actor.actions_used_this_turn["reaction"]`).
  - Decision: roll vs `oa_reaction` percentage from reactor's resolved AE preset.
  - Execution: single melee weapon attack from reactor → mover. Resolves
    against mover's pre-move position (mover is "leaving" reach, not
    "left"). Marks reaction used.
  - Mover can drop from OA damage; subsequent action pipeline checks
    `is_alive()` and skips cleanly.

**Deferred (documented):**
  - Multi-square path checking — only pre/post positions compared.
    "Pass-through" OAs (mover enters then leaves reach in a single
    move) are missed. Most common case (leaving an established melee)
    works correctly.
  - Sentinel / Polearm Master feats (extra OA triggers)
  - Disengage action grants no-OA-from-leaving (needs Disengage primitive)
  - Sophisticated OA action selection — uses first available melee
  - OA from forced movement (push / pull / teleport) — only normal walk
  - OA against ranged attacks made in melee — different trigger
  - OA-aware path planning (mover doesn't try to avoid them)
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState
from engine.core.geometry import distance_ft


# ============================================================================
# OA candidate detection
# ============================================================================

def find_oa_triggers(mover: Actor, pre_position: tuple[int, int],
                      state: CombatState) -> list[tuple[Actor, dict]]:
    """Find reactors who can OA the mover.

    Trigger condition: reactor's melee reach covered mover's pre-position
    AND does NOT cover mover's post-position (mover left their reach).

    Returns list of (reactor, melee_attack_action) tuples for each
    reactor that has a usable melee attack and an available reaction.
    Order matches actor list ordering for determinism.
    """
    # Lazy import to avoid circular (pipeline imports state, reactions
    # uses pipeline helpers)
    from engine.core.pipeline import _action_reach_ft

    # Disengage: per RAW the disengaging creature's speed doesn't provoke
    # OAs for the rest of their turn. Short-circuit before iterating
    # potential reactors. Log a single suppression event for telemetry.
    if mover.disengaging:
        state.event_log.append({
            "event": "disengage_suppressed_oa",
            "mover": mover.id,
        })
        return []

    triggers: list[tuple[Actor, dict]] = []
    for reactor in state.encounter.actors:
        if reactor.id == mover.id:
            continue
        if reactor.side == mover.side:
            continue
        if not reactor.is_alive():
            continue
        if reactor.actions_used_this_turn.get("reaction"):
            continue

        # Find this reactor's best melee weapon attack action.
        oa_action = _find_oa_attack(reactor, pre_position)
        if oa_action is None:
            continue

        reach = _action_reach_ft(oa_action)
        was_in_reach = distance_ft(reactor.position, pre_position) <= reach
        still_in_reach = distance_ft(reactor.position, mover.position) <= reach
        if was_in_reach and not still_in_reach:
            triggers.append((reactor, oa_action))
    return triggers


def _find_oa_attack(reactor: Actor,
                     mover_pre_position: tuple[int, int]) -> dict | None:
    """Return the reactor's first melee weapon attack whose reach covers
    the mover's pre-position. None if no such attack exists.

    v1: uses the FIRST matching melee attack (deterministic). Future:
    pick highest-damage melee. Ranged attacks don't OA in 5e RAW
    (Crossbow Expert is a separate feat — deferred).
    """
    from engine.core.pipeline import _action_reach_ft

    actions = (reactor.template.get("actions") or [])
    for action in actions:
        if action.get("type") != "weapon_attack":
            continue
        # Only count actions with a melee `reach_ft` parameter (not
        # `range_ft` ranged attacks). Distinguish by reading the
        # attack_roll step's params directly.
        if not _is_melee_attack(action):
            continue
        reach = _action_reach_ft(action)
        if distance_ft(reactor.position, mover_pre_position) <= reach:
            return action
    return None


def _is_melee_attack(action: dict) -> bool:
    """True if the action's attack_roll step has `reach_ft` (melee) and
    NOT `range_ft` (ranged). Defensive: also accepts top-level
    action.kind=='melee' as a marker."""
    for step in (action.get("pipeline") or []):
        if step.get("primitive") != "attack_roll":
            continue
        params = step.get("params") or {}
        if "range_ft" in params:
            return False
        if "reach_ft" in params:
            return True
        # Fallback heuristic on the kind param
        kind = params.get("kind", "").lower()
        if kind == "melee":
            return True
        if kind == "ranged":
            return False
    return False


# ============================================================================
# OA resolution
# ============================================================================

def resolve_opportunity_attacks(mover: Actor,
                                  pre_position: tuple[int, int],
                                  state: CombatState,
                                  event_bus, primitives,
                                  rng: random.Random) -> int:
    """Run all triggered OAs against the mover. Returns count fired.

    For each triggered reactor:
      1. Roll vs `oa_reaction` percentage from their AE preset.
      2. If passing: temporarily snap mover back to pre_position
         (so the attack_roll out-of-range guard sees the in-reach
         distance), execute the OA attack pipeline, mark the reactor's
         reaction slot used.
      3. If the OA drops the mover, stop iterating (no further OAs
         on a dead target).
    """
    triggers = find_oa_triggers(mover, pre_position, state)
    if not triggers:
        return 0

    # Lazy import to avoid the AI module pulling in at engine.core load.
    from engine.ai.action_economy import resolve_percentages

    fired = 0
    actual_post_position = mover.position
    # Temporarily snap mover back to pre_position so attack_roll's
    # distance check sees the trigger-time distance (in reach).
    mover.position = pre_position
    try:
        for reactor, oa_action in triggers:
            if reactor.actions_used_this_turn.get("reaction"):
                continue
            pcts = resolve_percentages(reactor)
            if rng.random() >= pcts.get("oa_reaction", 0.95):
                # Reaction declined this trigger — log so it's debuggable
                state.event_log.append({
                    "event": "opportunity_attack_declined",
                    "reactor": reactor.id,
                    "mover": mover.id,
                    "ae_threshold": pcts.get("oa_reaction", 0.95),
                })
                continue

            _log_oa_triggered(state, reactor, mover, oa_action)
            _execute_oa(reactor, mover, oa_action, state, event_bus, primitives)
            reactor.actions_used_this_turn["reaction"] = True
            fired += 1

            # Stop if the OA killed the mover — no more reactions land
            if not mover.is_alive():
                break
    finally:
        # Restore mover's post-move position (unless they died, in which
        # case position doesn't matter for further play).
        if mover.is_alive():
            mover.position = actual_post_position

    return fired


def _log_oa_triggered(state: CombatState, reactor: Actor, mover: Actor,
                       action: dict) -> None:
    state.event_log.append({
        "event": "opportunity_attack_triggered",
        "reactor": reactor.id,
        "mover": mover.id,
        "action": action.get("id"),
    })


def _execute_oa(reactor: Actor, mover: Actor, action: dict,
                 state: CombatState, event_bus, primitives) -> None:
    """Run the OA attack pipeline. Mirrors pipeline._execute_single but
    inline to avoid clobbering action-slot tracking (reactions use the
    reaction slot, not the main action slot — pipeline.execute marks the
    action's `slot` field, which would be 'action' for a weapon attack).
    """
    # Save + override current_attack scratch
    saved_attack = state.current_attack
    state.current_attack = {
        "actor": reactor, "target": mover, "action": action,
        "state": None, "had_advantage": False, "had_disadvantage": False,
        "is_opportunity_attack": True,
    }
    try:
        for step in (action.get("pipeline") or []):
            primitive_name = step["primitive"]
            params = step.get("params", {})
            when = step.get("when")
            if when:
                cond = when.get("condition", "")
                if cond and not _evaluate_simple_condition(cond, state):
                    continue
            primitives.invoke(primitive_name, params, state, event_bus)
    finally:
        state.current_attack = saved_attack


def _evaluate_simple_condition(cond: str, state: CombatState) -> bool:
    """Mirror of pipeline._evaluate_simple_condition for the on-hit
    damage gating. Duplicated to keep this module decoupled from pipeline
    internals; same vocabulary handled."""
    if "combat.attack_state == hit" in cond:
        return state.current_attack.get("state") in ("hit", "crit")
    if "combat.attack_had_advantage" in cond:
        return state.current_attack.get("had_advantage", False)
    return True


# ============================================================================
# Generic reaction trigger system (PR #45)
# ============================================================================
#
# Beyond opportunity attacks, reactions like Shield / Protection /
# Hellish Rebuke fire on specific events (attack roll pending, ally
# attacked, self damaged). The infrastructure below is general:
#
#   1. Actor template actions tagged `trigger: <event_name>` are
#      reactions (not main-slot candidates). pipeline.generate_candidates
#      filters them out.
#   2. At specific points in the attack / damage primitives, we call
#      `resolve_reaction_triggers(event_type, event_data, state, ...)`.
#   3. That scans every living actor for declared reactions matching
#      the event_type whose condition is satisfied; for each eligible
#      reactor, calls `try_use_reaction` which checks the reaction
#      slot is available, runs the reaction's pipeline, and consumes
#      the slot.
#
# Conditions are a small fixed vocabulary mapped to Python predicates
# (see _reaction_condition_satisfied). Adding new conditions = adding
# a new case there.
#
# v1: "Always use the reaction if eligible" — no AI scoring (pacing-
# aware reaction use is a follow-up). Spell-slot consumption for
# reactions that cast spells happens via try_use_reaction (checks +
# decrements via the existing spell_slots helpers).


def is_reaction_action(action: dict) -> bool:
    """True if `action` is a reaction (declared with `trigger: <event>`).
    Used by pipeline.generate_candidates to filter reactions out of the
    main / bonus candidate pool — reactions fire from event triggers,
    not from turn-initiated decisions."""
    return bool(action.get("trigger"))


def resolve_reaction_triggers(event_type: str, event_data: dict,
                                 state: CombatState, bus) -> int:
    """Scan actors for reactions matching `event_type` whose conditions
    are satisfied; fire each eligible reaction. Returns the count of
    reactions that fired.

    `event_data` is a dict of context the condition predicates can
    consult — typically includes `actor` (attacker), `target` (defender)
    for attack events, or `attacker_id` / `amount` for damage events.

    Sub-primitives in reaction pipelines are invoked via
    `primitives._invoke_subprimitive` (uses the module-level handler
    registry — same approach as forced_save's on_fail / on_success).
    """
    fired = 0
    for reactor in list(state.encounter.actors):
        if not reactor.is_alive():
            continue
        if reactor.actions_used_this_turn.get("reaction"):
            continue
        for action in (reactor.template.get("actions") or []):
            if action.get("trigger") != event_type:
                continue
            if not _reaction_condition_satisfied(
                    action.get("condition"), reactor, event_data, state):
                continue
            # Defer cost / availability checks to try_use_reaction
            if try_use_reaction(reactor, action, event_data, state, bus):
                fired += 1
                # Per RAW, one reaction per round — stop checking this
                # reactor's other reactions; move to next actor
                break
    return fired


def try_use_reaction(reactor: Actor, action: dict, event_data: dict,
                        state: CombatState, bus) -> bool:
    """Attempt to fire a reaction. Returns True if it fired (slot
    consumed + pipeline executed), False if it was skipped (slot
    unavailable, missing resources, etc.).

    Side effects when firing:
      - Decrement `actor.actions_used_this_turn['reaction']`
      - Consume spell slot (if the action declares `spell_slot_level`)
      - Consume feature use (if the action declares `feature_use`)
      - Run the reaction's pipeline with state.current_attack set up
        for the reaction context (reactor as actor; the attacker /
        target swapped appropriately per event type)
    """
    # Spell-slot gate
    from engine.core.spell_slots import (
        required_slot_level, has_slot, consume_slot,
        has_slot_for_action, resolve_chosen_slot_level,
    )
    slot_level = required_slot_level(action)
    # PR #77: gate via has_slot_for_action so upcastable reactions
    # (e.g., Hellish Rebuke with `upcast_scaling`) can fire from any
    # slot level at or above their base. The actual slot level
    # consumed is resolved below via resolve_chosen_slot_level.
    if slot_level > 0 and not has_slot_for_action(reactor, action):
        return False
    # Feature-use gate
    from engine.core.feature_uses import (
        required_feature_use, has_use, consume_use,
    )
    feature_key = required_feature_use(action)
    if feature_key is not None and not has_use(reactor, feature_key):
        return False

    # PR #56: pace-aware reaction gate. After resource availability
    # checks but BEFORE pipeline execution, weigh slot cost (in eHP)
    # vs reaction value (in eHP). Skip if cost > value, preserving
    # the slot for higher-value use later in the day.
    #
    # Bypassed when:
    #   - slot_level == 0 (no slot to weigh; OA-shape reactions)
    #   - action.signature_reaction == True (override flag for
    #     reactions that should always fire when eligible)
    # Unknown reactions (no value estimator) get value=inf, so the
    # gate passes — forward-compat for reactions added before their
    # estimators land.
    if slot_level > 0 and not action.get("signature_reaction"):
        from engine.core.feature_pacing import reaction_cost_ehp
        from engine.ai.reaction_scoring import estimate_reaction_value_ehp
        slots_remaining = int(reactor.spell_slots.get(slot_level, 0))
        encounters_remaining = int(
            getattr(state, "encounters_remaining_today", 3))
        cost = reaction_cost_ehp(slot_level, slots_remaining,
                                    encounters_remaining)
        value = estimate_reaction_value_ehp(action, event_data,
                                                reactor, state)
        if cost > value:
            state.event_log.append({
                "event": "reaction_skipped_pace",
                "actor": reactor.id,
                "action": action.get("id"),
                "slot_level": slot_level,
                "slots_remaining": slots_remaining,
                "encounters_remaining": encounters_remaining,
                "cost_ehp": round(cost, 2),
                "value_ehp": (round(value, 2)
                                if value != float("inf") else "inf"),
            })
            return False

    # Set up state.current_attack for the reaction's pipeline. The
    # reaction's "current_attack" semantics depend on the event type:
    #   - attack_targeting_resolved / attack_roll_pending: reactor is
    #     the spell-caster (actor); the original attacker remains in
    #     event_data; current_attack.target is the original defender
    #     (so attack_modifier with target='ally' resolves to them).
    #   - damage_taken: reactor was the damaged one (= reactor); we
    #     want forced_save to target the ATTACKER, so set target =
    #     event_data['attacker'].
    saved_attack = state.current_attack
    if event_data.get("_reaction_target_is_attacker"):
        new_target = event_data.get("attacker")
    else:
        new_target = event_data.get("target") or reactor
    # PR #77: resolve the chosen slot level for upcast scaling.
    # Reactions that declare upcast_scaling AND have slots at
    # higher levels get the bonus dice on their damage steps.
    chosen_slot_level = (resolve_chosen_slot_level(reactor, action)
                          if slot_level > 0 else 0)
    state.current_attack = {
        "actor": reactor,
        "target": new_target,
        "action": action,
        "state": None,
        "had_advantage": False,
        "had_disadvantage": False,
        "area_origin": None,
        "area_direction": None,
        "is_reaction": True,
        "reaction_event_data": event_data,
        "chosen_slot_level": chosen_slot_level,
    }
    try:
        # Use the module-level handler registry via _invoke_subprimitive
        # (same dispatch as forced_save's on_fail / on_success). Keeps
        # this module free of a primitives-registry dependency.
        from engine.primitives import _invoke_subprimitive
        for step in (action.get("pipeline") or []):
            _invoke_subprimitive(step, state, bus)
    finally:
        state.current_attack = saved_attack

    # Mark reaction used + consume resources
    reactor.actions_used_this_turn["reaction"] = True
    # PR #77: consume the chosen slot level (base for non-upcastable
    # reactions; possibly higher for upcastable ones like Hellish
    # Rebuke when only higher slots are available, or when slot
    # picker prefers upcast).
    if chosen_slot_level > 0:
        consume_slot(reactor, chosen_slot_level, state,
                       action_id=action.get("id"))
    if feature_key is not None:
        consume_use(reactor, feature_key, state, action_id=action.get("id"))
    state.event_log.append({
        "event": "reaction_fired",
        "reactor": reactor.id,
        "action": action.get("id"),
        "trigger": action.get("trigger"),
    })
    return True


def _reaction_condition_satisfied(cond: str | None, reactor: Actor,
                                     event_data: dict,
                                     state: CombatState) -> bool:
    """Evaluate a reaction's condition predicate. v1 vocabulary:

      - None / '' / 'always': fires unconditionally
      - 'shield_would_help': event.target == reactor AND event.total
        would hit (>= current_ac) AND event.total < current_ac + 5
        (Shield's RAW: only useful if it actually turns a hit into a
        miss; +5 AC otherwise unused)
      - 'attack_against_ally_within_5_ft': event.target on reactor's
        side, distance(reactor, target) <= 5 ft, reactor != target
        (Protection Fighting Style)
      - 'damage_taken_by_self_from_attacker': event.target_id ==
        reactor.id AND event.attacker is alive (Hellish Rebuke)

    Adding new conditions = adding a new case here. Keeps the
    vocabulary small and explicit; no expression evaluator needed.
    """
    if not cond or cond == "always":
        return True
    if cond == "shield_would_help":
        target = event_data.get("target")
        if target is None or target.id != reactor.id:
            return False
        total = int(event_data.get("total", 0))
        current_ac = int(event_data.get("current_ac", 0))
        # Shield bumps AC by 5. Useful only if total would hit current_ac
        # but would miss current_ac + 5.
        return total >= current_ac and total < current_ac + 5
    if cond == "attack_against_ally_within_5_ft":
        target = event_data.get("target")
        if target is None or target.id == reactor.id:
            return False
        if target.side != reactor.side:
            return False
        if distance_ft(reactor.position, target.position) > 5:
            return False
        # PR #47: Protection RAW: "When a creature you can see attacks
        # a target other than you..." — gate on visibility of the
        # attacker.
        from engine.core.vision import can_actor_see
        attacker = event_data.get("actor")
        if attacker is not None and not can_actor_see(
                reactor, attacker, state):
            return False
        return True
    if cond == "damage_taken_by_self_from_attacker":
        if event_data.get("target_id") != reactor.id:
            return False
        attacker = event_data.get("attacker")
        if attacker is None or not attacker.is_alive():
            return False
        # PR #47: Hellish Rebuke RAW: "the creature that damaged you
        # ... you can see" — gate on visibility. (RAW also has 60-ft
        # range; deferred since we don't have a clean place to put the
        # range check on the reactor side of damage events without
        # threading more event_data through.)
        from engine.core.vision import can_actor_see
        if not can_actor_see(reactor, attacker, state):
            return False
        # Mark for try_use_reaction: forced_save's affected='current_target'
        # should be the attacker for retaliation reactions.
        event_data["_reaction_target_is_attacker"] = True
        return True
    if cond == "enemy_casting_spell_within_60_ft":
        # Counterspell trigger (PR #46): an enemy is casting a spell.
        # Conditions:
        #   - caster is on opposing side (don't counter your own spells
        #     or allies' spells)
        #   - reactor is not the caster (you can't counterspell yourself)
        #   - caster is within 60 ft (RAW range)
        #   - reactor can see the caster (PR #47: RAW "you see")
        caster = event_data.get("caster")
        if caster is None or caster.id == reactor.id:
            return False
        if caster.side == reactor.side:
            return False
        if distance_ft(reactor.position, caster.position) > 60:
            return False
        from engine.core.vision import can_actor_see
        if not can_actor_see(reactor, caster, state):
            return False
        return True
    return False
