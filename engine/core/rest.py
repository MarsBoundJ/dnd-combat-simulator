"""Rest cycle hooks (PR #37).

The engine simulates single encounters; there's no in-runner rest
cycle today. This module exposes the entry points that future multi-
encounter sim work will call between encounters, AND lets tests
invoke rest-cycle behavior directly (Arcane Recovery, Second Wind
short-rest partial refresh, etc.) without spinning up a fake runner.

**v1 scope (PR #37):**
  - `apply_short_rest(actor, state)` — entry point. Dispatches to
    per-class handlers based on `actor.template.derived_from_pc_schema.class`.
  - Wizard handler: Arcane Recovery. Restores expended spell slots
    via `slot_recovery_partial` primitive (budget = ceil(level/2),
    cap = 5th level). Decrements
    `actor.resources["arcane_recovery_uses_remaining"]`.
  - Fighter handler: Second Wind short-rest partial refresh.
    Restores +1 use of Second Wind (up to the level-table maximum)
    per RAW. Doesn't refresh Action Surge (that's also 1/short
    rest per RAW but only counted as a uses_remaining → we restore
    Action Surge too with +1 cap at the level-table max).
  - Non-PC-derived actors (inline templates) → no-op. Robust.

**Deferred:**
  - Long rest (`apply_long_rest`) — same shape, broader restorations
    (spell slots fully restored, all per-rest feature uses refilled).
  - Data-driven per-feature dispatch — currently hard-coded per
    class. When more classes land we'll walk
    `class_def.level_table` for `f_*` features whose YAML defs
    declare a `usage.rest_recovery.short_rest` or `long_rest` hook.
  - Runner integration (multi-encounter session simulation calling
    apply_short_rest between encounters).
"""
from __future__ import annotations

import math

from engine.core.state import Actor, CombatState


def apply_short_rest(actor: Actor, state: CombatState) -> dict:
    """Run all short-rest effects for `actor`. Returns a dict
    summarizing what fired, for logging / test inspection.

    The dict shape:
      {
        "arcane_recovery": {"restored": [{"level": L, "count": N}, ...]}
          # absent if not applicable
        "second_wind_refresh": {"added": N, "new_total": M}
          # absent if not applicable
        "action_surge_refresh": {"added": N, "new_total": M}
          # absent if not applicable
      }

    Logs a `short_rest_applied` event with the summary.
    """
    derived = actor.template.get("derived_from_pc_schema") or {}
    cls = derived.get("class")
    level = int(derived.get("level", 1))
    summary: dict = {}
    if cls == "c_wizard":
        result = _apply_arcane_recovery(actor, level, state)
        if result is not None:
            summary["arcane_recovery"] = result
    if cls == "c_fighter":
        sw = _apply_second_wind_short_rest_refresh(actor, level, state)
        if sw is not None:
            summary["second_wind_refresh"] = sw
        # RAW (PHB 2024): Action Surge is also 1/short rest at L2-16,
        # 2/short rest at L17+. Short rest fully refreshes it.
        asg = _apply_action_surge_short_rest_refresh(actor, level, state)
        if asg is not None:
            summary["action_surge_refresh"] = asg
    state.event_log.append({
        "event": "short_rest_applied",
        "actor": actor.id,
        "summary": summary,
    })
    return summary


# ============================================================================
# Wizard: Arcane Recovery
# ============================================================================

def _apply_arcane_recovery(actor: Actor, level: int,
                              state: CombatState) -> dict | None:
    """Once per long rest, on completing a short rest, the wizard
    recovers expended slots up to ceil(level/2) combined levels.
    Slots restored must be ≤ 5th level."""
    uses = int(actor.resources.get("arcane_recovery_uses_remaining", 0))
    if uses <= 0:
        return None
    # Pre-decrement the use even if no slots are actually expended —
    # RAW: the activation consumes the use either way (player chooses
    # to use AR; if they don't, they don't have to invoke it). For
    # our purposes, only call this helper when the wizard would use
    # it, which we infer from "uses available AND at least one slot
    # is expended."
    if not _has_expended_slots(actor):
        return None
    actor.resources["arcane_recovery_uses_remaining"] = uses - 1
    state.event_log.append({
        "event": "feature_use_consumed",
        "actor": actor.id,
        "resource": "arcane_recovery_uses_remaining",
        "remaining": actor.resources["arcane_recovery_uses_remaining"],
        "action": "arcane_recovery",
    })
    # Fire the slot_recovery_partial primitive directly. Setting
    # current_attack.actor lets the primitive resolve the target.
    from engine.primitives import _slot_recovery_partial
    saved_attack = state.current_attack
    state.current_attack = {"actor": actor}
    try:
        result = _slot_recovery_partial({
            "max_combined_level": math.ceil(level / 2),
            "max_slot_level": 5,
        }, state, None)
    finally:
        state.current_attack = saved_attack
    return result


def _has_expended_slots(actor: Actor) -> bool:
    """True if the actor has any spell slot level where the current
    count is below the max."""
    for lvl, max_at in actor.spell_slots_max.items():
        if int(actor.spell_slots.get(lvl, 0)) < int(max_at):
            return True
    return False


# ============================================================================
# Fighter: Second Wind + Action Surge short-rest refresh
# ============================================================================

def _apply_second_wind_short_rest_refresh(actor: Actor, level: int,
                                              state: CombatState) -> dict | None:
    """Per RAW: Second Wind restores +1 use on a short rest, up to
    the level-table maximum. The max scales with fighter level
    (2/3/4 across L1/L4/L10 per c_fighter level_table).
    """
    cur = int(actor.resources.get("second_wind_uses_remaining", 0))
    max_uses = _fighter_second_wind_max_at_level(level)
    if max_uses == 0:
        return None
    if cur >= max_uses:
        return None
    actor.resources["second_wind_uses_remaining"] = cur + 1
    return {"added": 1,
             "new_total": actor.resources["second_wind_uses_remaining"]}


def _apply_action_surge_short_rest_refresh(actor: Actor, level: int,
                                                state: CombatState) -> dict | None:
    """Per RAW: Action Surge refreshes fully on a short rest. The max
    is 1 at L2-16, 2 at L17+."""
    if level < 2:
        return None
    max_uses = 2 if level >= 17 else 1
    cur = int(actor.resources.get("action_surge_uses_remaining", 0))
    if cur >= max_uses:
        return None
    actor.resources["action_surge_uses_remaining"] = max_uses
    return {"added": max_uses - cur,
             "new_total": max_uses}


def _fighter_second_wind_max_at_level(level: int) -> int:
    """Per c_fighter.level_table: second_wind_uses scales 2/3/4 across
    L1/L4/L10. Mirrors the data here for the rest cycle so we don't
    need to load the class def. If the schema changes, update here too.
    """
    if level >= 10:
        return 4
    if level >= 4:
        return 3
    if level >= 1:
        return 2
    return 0
