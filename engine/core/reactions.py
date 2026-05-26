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
