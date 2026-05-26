"""Spell slot tracking + opportunity cost formula.

Per `docs/foundations/ehp-action-framework.md` §"Opportunity Cost":

    spell_slot_ehp_value(slot_level, slots_remaining, encounters_remaining):
        scarcity = 1.0 / max(1, slots_remaining)
        urgency  = encounters_remaining / 6.0   # 6-encounter day baseline
        return slot_level * 3.0 * scarcity * (1.0 - urgency)

The cost is subtracted from a candidate's raw eHP score, so the AI
weighs "this Fireball does 75 eHP but burns my last 3rd-level slot
for 9 eHP cost = net 66" against alternatives.

**v1 scope:**
  - Per-actor slot tracking (Actor.spell_slots {level: remaining})
  - `has_slot` / `consume_slot` helpers
  - `slot_cost_ehp` formula matching the framework reference values
  - Filter at candidate generation: skip if required slot unavailable
  - Subtract cost at scoring: in decision_layer.score_candidates_v1
  - Consume at execution: in pipeline._execute_single

**Deferred:**
  - Upcasting (cast 1st-level Bless with a 3rd-level slot for amplified
    effect) — needs `upcast: scaling` rules from spell templates
  - Pact Magic (warlock short-rest slot restoration)
  - Spell points variant
  - Long rest restoration mid-simulation
  - Per-class spell preparation lists
  - Cantrips with formal level 0 — v1 treats anything WITHOUT a
    `spell_slot_level` field as "free" (no slot consumption, no cost)
  - Per-actor encounters_remaining_today override (currently
    CombatState-level only)
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState


# 5e standard adventuring day = 6-8 medium encounters. The framework's
# default uses 6 as the divisor. Matches PHB DMG guidance.
ENCOUNTER_DAY_DIVISOR = 6.0

# Per-slot-level base cost multiplier. A 3rd-level slot at full scarcity
# (only 1 left) on the last encounter (urgency 0) costs 3 × 3 × 1 × 1 = 9
# eHP, matching the framework's "Fireball cost ≈ 9.0 eHP" example.
SLOT_COST_BASE_MULTIPLIER = 3.0


# ============================================================================
# Cost formula
# ============================================================================

def slot_cost_ehp(slot_level: int, slots_remaining: int,
                    encounters_remaining: int) -> float:
    """Opportunity cost (in eHP) of spending a slot of `slot_level`.

    Per ehp-action-framework.md:

        scarcity = 1 / max(1, slots_remaining)
        urgency  = encounters_remaining / 6.0   (clamped to [0, 1])
        cost = slot_level × 3.0 × scarcity × (1 - urgency)

    Behavior:
      - More slots remaining → lower cost (each individual slot is less
        precious).
      - More encounters remaining → lower cost (you can replenish later;
        spend freely early in the day).
      - Higher level slot → higher cost (your last 5th-level slot is
        worth more than your last 1st).

    slots_remaining is the count BEFORE consumption — pass the
    pre-cast count.
    """
    if slot_level <= 0:
        return 0.0   # cantrips / free actions
    scarcity = 1.0 / max(1, slots_remaining)
    urgency = min(1.0, max(0.0, encounters_remaining / ENCOUNTER_DAY_DIVISOR))
    return slot_level * SLOT_COST_BASE_MULTIPLIER * scarcity * (1.0 - urgency)


# ============================================================================
# Slot availability
# ============================================================================

def required_slot_level(action: dict) -> int:
    """Return the slot level this action consumes (0 = free / not a spell)."""
    return int(action.get("spell_slot_level", 0))


def has_slot(actor: Actor, slot_level: int) -> bool:
    """True if the actor has at least one available slot at this level.
    Level 0 (cantrip / not a spell) is always available."""
    if slot_level <= 0:
        return True
    return actor.spell_slots.get(slot_level, 0) > 0


def remaining_slots(actor: Actor, slot_level: int) -> int:
    """Count of slots available at this level (0 if none / not tracked)."""
    if slot_level <= 0:
        return 0
    return int(actor.spell_slots.get(slot_level, 0))


def consume_slot(actor: Actor, slot_level: int, state: CombatState,
                  action_id: str | None = None) -> None:
    """Decrement the actor's slot count at the given level. No-op for
    level 0 (cantrips). Logs `spell_slot_consumed` event.

    Raises ValueError if no slot available — this is a contract
    violation; the candidate filter should have prevented selection.
    """
    if slot_level <= 0:
        return
    available = actor.spell_slots.get(slot_level, 0)
    if available <= 0:
        raise ValueError(
            f"consume_slot called on {actor.id!r} with no level-{slot_level} "
            f"slot available (candidate filter should have caught this)"
        )
    actor.spell_slots[slot_level] = available - 1
    state.event_log.append({
        "event": "spell_slot_consumed",
        "actor": actor.id,
        "slot_level": slot_level,
        "remaining": actor.spell_slots[slot_level],
        "action": action_id,
    })


# ============================================================================
# Public eHP cost helper — used by decision_layer.score_candidates_v1
# ============================================================================

def candidate_slot_cost(actor: Actor, action: dict,
                          state: CombatState) -> float:
    """eHP cost of casting this action given the actor's current state.

    Returns 0.0 for non-spell actions and cantrips. Otherwise computes
    cost via `slot_cost_ehp` using the actor's current slots_remaining
    at the required level and state.encounters_remaining_today.
    """
    level = required_slot_level(action)
    if level <= 0:
        return 0.0
    return slot_cost_ehp(
        slot_level=level,
        slots_remaining=remaining_slots(actor, level),
        encounters_remaining=state.encounters_remaining_today,
    )
