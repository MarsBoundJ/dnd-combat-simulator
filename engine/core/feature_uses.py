"""Feature-use tracking + candidate gate (PR #33).

Generic "this action consumes a limited-use resource on the actor"
infrastructure, mirroring the spell-slot gate in `spell_slots.py`. The
canonical first consumer is Second Wind (Fighter, L1+), gated by
`second_wind_uses_remaining`. Future consumers include Wizard Arcane
Recovery, monster legendary actions, Lay on Hands, etc.

**Schema:** an action declares its resource via a `feature_use` field:

    - id: a_second_wind
      name: Second Wind
      type: heal
      slot: bonus_action
      feature_use: second_wind_uses_remaining  # key into actor.resources
      pipeline: [...]

The action is filtered out of the candidate pool when the actor's
`resources[feature_use]` is missing or <= 0, and the same key is
decremented at execution time.

**Why a separate module, not a tag on spell_slots:**
  - Spell slots are per-level (level 1-9); features are per-named-
    resource (one key per feature).
  - Spell slots have an opportunity-cost formula tied to encounters-
    remaining; feature uses are flat (RAW: if you have a charge, use
    it). The scoring penalty for being on your last Second Wind is
    already baked into the candidate filter — there are no more
    candidates once it's spent.
  - Rest cadence differs (long-rest-only spell slots vs. short-rest-
    one-use + long-rest-all-back for Second Wind).

**v1 scope:**
  - Per-actor resource tracking via the existing `actor.resources`
    dict (single key → integer count remaining).
  - `required_feature_use` / `has_use` / `consume_use` helpers.
  - Pipeline-level candidate filter (alongside `has_slot`).
  - Pipeline-level consumption at execution (alongside `consume_slot`).

**Deferred:**
  - Rest restoration logic (no rest cycle in-encounter yet — PR #31
    documented this as a deferred item for the same reason)
  - Multi-resource actions (an action that consumes both a spell slot
    AND a feature use — none exist in 5e RAW that we model)
  - Per-encounter recharge (e.g., Dragon's Breath Weapon recharge on
    5-6) — separate mechanic, not feature-use shaped
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState


def required_feature_use(action: dict) -> str | None:
    """Return the resource key this action consumes, or None if the
    action is not feature-use gated."""
    key = action.get("feature_use")
    if not key:
        return None
    return str(key)


def has_use(actor: Actor, resource_key: str | None) -> bool:
    """True if the actor has at least one charge remaining. None means
    'not gated' which is always available."""
    if resource_key is None:
        return True
    return int(actor.resources.get(resource_key, 0)) > 0


def remaining_uses(actor: Actor, resource_key: str) -> int:
    return int(actor.resources.get(resource_key, 0))


def consume_use(actor: Actor, resource_key: str, state: CombatState,
                  action_id: str | None = None) -> None:
    """Decrement the actor's charge for this resource. Logs a
    `feature_use_consumed` event. Raises ValueError if no charges
    remain — the candidate filter should have prevented this."""
    available = int(actor.resources.get(resource_key, 0))
    if available <= 0:
        raise ValueError(
            f"consume_use called on {actor.id!r} for {resource_key!r} "
            f"with no charges remaining (candidate filter should have "
            f"caught this)"
        )
    actor.resources[resource_key] = available - 1
    state.event_log.append({
        "event": "feature_use_consumed",
        "actor": actor.id,
        "resource": resource_key,
        "remaining": actor.resources[resource_key],
        "action": action_id,
    })


# ============================================================================
# Rage-use refund (Zealot Zealous Presence, Berserker Intimidating Presence)
# ============================================================================
#
# RAW for both features: "Once you use this feature, you can't use it again
# until you finish a Long Rest unless you expend a use of your Rage (no
# action required) to restore your use of it."
#
# Modeling: an action declares `rage_refund: true` alongside its
# `feature_use:` key. When the feature pool is empty, the actor may expend
# one Rage use (rage_uses_remaining) to restore the pool to its max and use
# the feature again — at no action-economy cost ("no action required").
#
# v1 conservative gate: the refund is only offered while the actor keeps at
# least `_RAGE_REFUND_RESERVE` Rage uses in reserve, so the AI never burns
# its LAST Rage charge on a feature refund (which would strand the Barbarian
# unable to actually Rage). The Rage-use opportunity cost beyond that is not
# yet modeled in scoring — a documented follow-on.

# Keep at least this many Rage uses unspent when refunding.
_RAGE_REFUND_RESERVE = 1


def is_rage_refundable(action: dict) -> bool:
    """True if `action` declares it can be restored by spending a Rage use."""
    return bool(action.get("rage_refund"))


def can_rage_refund(actor: Actor, action: dict) -> bool:
    """True if `action` is Rage-refundable AND the actor has a spare Rage
    use to spend on the refund (keeping `_RAGE_REFUND_RESERVE` in reserve)."""
    if not is_rage_refundable(action):
        return False
    return (int(actor.resources.get("rage_uses_remaining", 0))
            > _RAGE_REFUND_RESERVE)


def is_action_available(actor: Actor, action: dict) -> bool:
    """Candidate-gate check: True if the action has a feature charge OR it's
    Rage-refundable and the actor can pay the Rage cost. Replaces the bare
    `has_use(actor, required_feature_use(action))` check so the refund path
    is surfaced as an available candidate."""
    key = required_feature_use(action)
    if has_use(actor, key):
        return True
    return can_rage_refund(actor, action)


def consume_use_or_rage_refund(actor: Actor, action: dict,
                                  state: CombatState) -> None:
    """Execution-time consumption for feature-use-gated actions. If the
    pool is empty but the action is Rage-refundable and affordable, first
    expend a Rage use to restore the pool to max, then consume one charge.
    No-op for actions without a `feature_use` key."""
    key = required_feature_use(action)
    if key is None:
        return
    if int(actor.resources.get(key, 0)) <= 0 and can_rage_refund(actor, action):
        _apply_rage_refund(actor, key, state, action.get("id"))
    consume_use(actor, key, state, action_id=action.get("id"))


def _apply_rage_refund(actor: Actor, resource_key: str,
                          state: CombatState,
                          action_id: str | None) -> None:
    """Spend one Rage use to restore `resource_key` to its level-table max
    (read from the sibling `*_max` key, defaulting to 1). Logs a
    `rage_use_refund` event."""
    rage = int(actor.resources.get("rage_uses_remaining", 0))
    actor.resources["rage_uses_remaining"] = max(0, rage - 1)
    max_key = resource_key.replace("_remaining", "_max")
    max_uses = int(actor.resources.get(max_key, 1))
    actor.resources[resource_key] = max_uses
    state.event_log.append({
        "event": "rage_use_refund",
        "actor": actor.id,
        "resource": resource_key,
        "restored_to": max_uses,
        "rage_uses_remaining": actor.resources["rage_uses_remaining"],
        "action": action_id,
    })
