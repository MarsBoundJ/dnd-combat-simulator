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
