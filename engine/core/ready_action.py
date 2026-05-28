"""Ready Action — first PR in the party-coordination arc (PR #86).

RAW (PHB 2024 p.380, "Take the Ready Action"):

  *You can hold an action to occur later. Take the Ready action on your
  turn, which lets you act using your reaction before the start of your
  next turn. First, you choose what perceivable circumstance will
  trigger your reaction. Then, you choose the action you will take in
  response to that trigger, or you choose to move up to your Speed in
  response to it. ... When the trigger occurs, you can take your
  reaction right after the trigger finishes, or you can ignore the
  trigger. ... When you Ready a spell, you cast it as normal but hold
  its energy, which you release with your reaction when the trigger
  occurs.*

**v1 scope (two triggers):**
  - `enemy_enters_reach` — fires when an enemy moves into the actor's
    melee reach. The classic "Ready a swing for the goblin to step
    up." Reuses the movement-completion event from the runner's
    move-to-engage path.
  - `enemy_casts_spell` — fires when an enemy starts casting a spell
    within the actor's specified range. Combines with weapon attacks
    (Ready a Longbow shot triggered on enemy cast) or future spell
    interrupts. Hooks into the existing `spell_cast_initiated` event
    that pipeline.py emits at cast time.

**Deferred (each its own follow-on PR):**
  - `ally_takes_damage` trigger (for Ready-a-Cure-Wounds-shape patterns)
  - Ready-a-spell with concentration plumbing (RAW: "hold its energy" —
    the spell holds concentration on the held trigger, not on the
    spell's normal duration). Currently Ready is **weapon-attack-only**.
  - Ready a Move (RAW: alternative to Ready an Action)
  - Conditional/AND triggers (RAW lets you pick a perceivable
    circumstance — could be complex; v1 keeps the trigger atomic)
  - Concentration-on-Ready disrupts when damaged
  - AI sub-action choice within Ready (v1 emits one Ready candidate
    per (sub_action × trigger) combo; the scoring picks the best)

**State model.** A single `actor.readied_action` dict (None when no
readied action pending). At most ONE readied action active per actor
(RAW: Ready is one action per turn). Replaces any prior readied action.

**Reaction economy.** The reaction slot is NOT pre-consumed at Ready
time — RAW lets you ignore the trigger when it fires. The slot is
consumed only when the readied action actually executes, via the
normal `actions_used_this_turn['reaction']` flag. Side effect: a
Barbarian who Readies a swing AND has Sentinel-style OA reactions
loses access to one of them whichever fires first (correct RAW).

**Discard window.** RAW: "discarded if you don't take it before the
start of your next turn." Implemented via `Actor.reset_turn` which
clears `readied_action` to None — the runner picks up the stale
entry and logs `ready_action_discarded` for telemetry.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState


# ============================================================================
# Trigger vocabulary
# ============================================================================

# Valid trigger keys for v1. Adding a new trigger = adding a key here
# + adding the event-emission point + adding the matcher logic in
# `try_fire`. Keep this set explicit so unknown triggers fail loudly
# rather than silently never firing.
KNOWN_TRIGGERS: frozenset[str] = frozenset({
    "enemy_enters_reach",
    "enemy_casts_spell",
})


# ============================================================================
# State transitions
# ============================================================================

def register(actor: Actor, sub_action_id: str, trigger: str,
              state: CombatState,
              trigger_params: dict | None = None) -> None:
    """Set `actor.readied_action` to the given (sub_action, trigger)
    pair. Overwrites any prior readied action (RAW: Ready is one
    action per turn; readying again replaces).

    `trigger_params` carries trigger-specific data:
      - `enemy_enters_reach`: {"reach_ft": int} — the reach distance
        the actor will swing at (defaults to max melee reach across
        actor's weapon attacks).
      - `enemy_casts_spell`: {"within_ft": int} — range gate (defaults
        to 60 ft, the typical Counterspell-ish range).

    Logs `ready_action_taken` with actor / sub_action / trigger /
    round so the AI's choice is visible in the event log.
    """
    if trigger not in KNOWN_TRIGGERS:
        raise ValueError(
            f"Unknown ready trigger: {trigger!r}; "
            f"valid: {sorted(KNOWN_TRIGGERS)}"
        )
    actor.readied_action = {
        "action_id": sub_action_id,
        "trigger": trigger,
        "trigger_params": dict(trigger_params or {}),
        "round_readied": state.round,
    }
    state.event_log.append({
        "event": "ready_action_taken",
        "actor": actor.id,
        "sub_action": sub_action_id,
        "trigger": trigger,
        "round": state.round,
    })


def discard(actor: Actor, state: CombatState, reason: str) -> None:
    """Clear `actor.readied_action`. Logs `ready_action_discarded`
    with reason. Reasons:
      - 'turn_start' — RAW discard at start of next turn (no trigger
        fired)
      - 'reaction_unavailable' — fired but reaction slot already used
      - 'fired' — readied action executed successfully (logged for
        symmetry; the actual firing also emits `ready_action_fired`)
      - 'caster_incapacitated' — deferred; future
    """
    if actor.readied_action is None:
        return
    snapshot = dict(actor.readied_action)
    actor.readied_action = None
    state.event_log.append({
        "event": "ready_action_discarded",
        "actor": actor.id,
        "sub_action": snapshot.get("action_id"),
        "trigger": snapshot.get("trigger"),
        "reason": reason,
        "round": state.round,
    })


def has_readied_action(actor: Actor) -> bool:
    """True iff the actor has a pending readied action."""
    return actor.readied_action is not None


# ============================================================================
# Trigger firing
# ============================================================================

def find_actors_with_trigger(state: CombatState,
                                trigger: str) -> list[Actor]:
    """Return all living actors with a readied action whose trigger
    matches `trigger`. Returned in turn-order to make firing
    deterministic when multiple actors have the same readied trigger."""
    matching: list[Actor] = []
    order = state.turn_order or [a.id for a in state.encounter.actors]
    for actor_id in order:
        actor = state._actor_by_id(actor_id)
        if actor is None or not actor.is_alive():
            continue
        if not has_readied_action(actor):
            continue
        if actor.readied_action.get("trigger") == trigger:
            matching.append(actor)
    return matching


def try_fire(actor: Actor, target: Actor, state: CombatState,
              event_bus, primitives, *, reason: str = "trigger_matched") -> bool:
    """Fire the actor's readied action against `target`. Returns True
    if it fired (slot consumed + sub-action pipeline executed), False
    if it was skipped (reaction slot already used, sub-action no
    longer valid, etc.).

    Side effects when firing:
      - Marks `actor.actions_used_this_turn['reaction']` True (RAW:
        Ready uses your reaction when the trigger fires)
      - Clears `actor.readied_action` (via `discard(reason='fired')`)
      - Executes the sub-action pipeline with state.current_attack
        scoped to (actor → target)
      - Logs `ready_action_fired`

    Skip cases:
      - Reaction slot already used this round (Sentinel OA, Shield,
        etc. consumed it first)
      - Sub-action no longer in actor's template (defensive — caller
        validation should prevent this)
      - Target is dead / not in encounter
    """
    if actor.readied_action is None:
        return False
    if actor.actions_used_this_turn.get("reaction"):
        state.event_log.append({
            "event": "ready_action_skipped",
            "actor": actor.id,
            "reason": "reaction_already_used",
        })
        return False
    if target is None or not target.is_alive():
        return False

    action_id = actor.readied_action["action_id"]
    sub_action = _find_action(actor, action_id)
    if sub_action is None:
        state.event_log.append({
            "event": "ready_action_skipped",
            "actor": actor.id,
            "reason": "sub_action_not_found",
            "missing": action_id,
        })
        return False

    # Execute the sub-action's pipeline. Mirrors the OA execution path
    # in engine/core/reactions.py::_execute_oa — save + restore
    # current_attack so any in-flight attack context isn't clobbered
    # if Ready fires mid-other-pipeline.
    saved_attack = state.current_attack
    state.current_attack = {
        "actor": actor, "target": target, "action": sub_action,
        "state": None,
        "had_advantage": False, "had_disadvantage": False,
        "is_readied_action": True,
    }
    try:
        for step in (sub_action.get("pipeline") or []):
            primitive_name = step["primitive"]
            params = step.get("params", {})
            primitives.invoke(primitive_name, params, state, event_bus)
    finally:
        state.current_attack = saved_attack

    actor.actions_used_this_turn["reaction"] = True
    state.event_log.append({
        "event": "ready_action_fired",
        "actor": actor.id,
        "target": target.id,
        "sub_action": action_id,
        "trigger": actor.readied_action.get("trigger"),
        "reason": reason,
    })
    discard(actor, state, reason="fired")
    return True


# ============================================================================
# Trigger-event handlers (called from runner / pipeline event points)
# ============================================================================

def on_movement_completed(mover: Actor, pre_position: tuple[int, int],
                            state: CombatState, event_bus,
                            primitives) -> int:
    """Hook for `enemy_enters_reach` triggers. Called from the runner's
    move-to-engage path AFTER movement resolves and OAs settle.

    For each enemy of the mover who has a readied `enemy_enters_reach`
    trigger:
      - If mover was NOT in their reach before AND IS in their reach
        now (the trigger semantics — mover stepped INTO reach), fire.

    Returns count fired. Fires in turn-order for determinism. Stops
    firing against a given actor as soon as their readied action
    consumes (one trigger per ready).
    """
    from engine.core.geometry import distance_ft
    fired = 0
    actors_with_trigger = find_actors_with_trigger(state, "enemy_enters_reach")
    for actor in actors_with_trigger:
        # Triggers only fire from opposing-side movement
        if actor.side == mover.side:
            continue
        params = actor.readied_action.get("trigger_params") or {}
        reach = int(params.get("reach_ft", _default_reach_for(actor)))
        was_in_reach = distance_ft(actor.position, pre_position) <= reach
        is_in_reach = distance_ft(actor.position, mover.position) <= reach
        if not was_in_reach and is_in_reach:
            if try_fire(actor, mover, state, event_bus, primitives,
                          reason="enemy_entered_reach"):
                fired += 1
                # If the mover died from the readied swing, stop iterating
                if not mover.is_alive():
                    break
    return fired


def on_spell_cast_initiated(caster: Actor, state: CombatState,
                              event_bus, primitives) -> int:
    """Hook for `enemy_casts_spell` triggers. Called from pipeline.py
    right after `spell_cast_initiated` reactions resolve (so
    Counterspell takes precedence; readied actions fire AFTER the
    counterspell window if the spell wasn't cancelled).

    For each enemy of the caster who has a readied `enemy_casts_spell`
    trigger with the caster within the readied range, fire.

    Returns count fired. Each actor's readied action consumes on
    fire (one trigger per ready).
    """
    from engine.core.geometry import distance_ft
    fired = 0
    actors_with_trigger = find_actors_with_trigger(state, "enemy_casts_spell")
    for actor in actors_with_trigger:
        if actor.side == caster.side:
            continue
        params = actor.readied_action.get("trigger_params") or {}
        within = int(params.get("within_ft", 60))
        if distance_ft(actor.position, caster.position) > within:
            continue
        if try_fire(actor, caster, state, event_bus, primitives,
                      reason="enemy_cast_spell"):
            fired += 1
            if not caster.is_alive():
                break
    return fired


# ============================================================================
# Helpers
# ============================================================================

def _find_action(actor: Actor, action_id: str) -> dict | None:
    """Return the actor's action dict by id, or None if not found."""
    for action in (actor.template.get("actions") or []):
        if action.get("id") == action_id:
            return action
    return None


def _default_reach_for(actor: Actor) -> int:
    """Max melee reach across actor's weapon_attack actions, defaulting
    to 5 ft. Used when a readied enemy_enters_reach trigger doesn't
    specify reach (the AI's normal Ready emission always sets this,
    but defensive default for direct callers / tests)."""
    reaches: list[int] = []
    for action in (actor.template.get("actions") or []):
        if action.get("type") != "weapon_attack":
            continue
        for step in (action.get("pipeline") or []):
            if step.get("primitive") != "attack_roll":
                continue
            params = step.get("params") or {}
            if "reach_ft" in params and "range_ft" not in params:
                reaches.append(int(params["reach_ft"]))
    return max(reaches) if reaches else 5
