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
  - Early-deadly-fight override: `encounter_danger` collapses the
    conserve-early penalty when the current fight turns acutely dangerous
    (applied in `candidate_slot_cost`)

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

# --- Deadly-fight danger override (PR: early-deadly-fight override) ---------
# The nova-late slot-cost penalty assumes the party can AFFORD to conserve
# for future fights. When the CURRENT fight turns acutely dangerous, that
# assumption breaks — a slot saved for a future encounter is worthless if a
# PC dies now — so a danger signal collapses the conserve-early penalty,
# letting casters nova EARLY in the day when survival demands it (vs only on
# the last fight). At the climax the penalty is already 0 (rem=0), so the
# override is a no-op there by construction — it only bites mid-day.
#
# Aggregate party-depletion ramp: no danger at/above HIGH, full danger
# at/below LOW (linear between).
DANGER_PARTY_HP_HIGH = 0.50
DANGER_PARTY_HP_LOW = 0.15
# Acute single-ally peril: an ally at/below this fraction of its OWN max HP
# is in danger of dropping; its peril ramps to full as it nears 0.
DANGER_ALLY_CRITICAL_FRAC = 0.25


# ============================================================================
# Cost formula
# ============================================================================

def slot_cost_ehp(slot_level: int, slots_remaining: int,
                    encounters_remaining: int) -> float:
    """Opportunity cost (in eHP) of spending a slot of `slot_level`.

    Per ehp-action-framework.md (NOVA-LATE pacing):

        scarcity      = 1 / max(1, slots_remaining)
        day_pressure  = encounters_remaining / 6.0   (clamped to [0, 1])
        cost = slot_level × 3.0 × scarcity × day_pressure

    `encounters_remaining` = fights still to come AFTER this one.

    Behavior (conserve early, NOVA on the last fight — matches the
    framework doc's worked example "a slot in encounter 6-of-6 is worth
    LESS than in encounter 1-of-6"):
      - More encounters remaining → HIGHER cost (those future fights still
        need slots, so spending now is more costly).
      - LAST fight (encounters_remaining = 0) → cost 0 → nova freely
        (nothing left to conserve for).
      - More slots remaining → lower cost (each individual slot is less
        precious).
      - Higher level slot → higher cost.

    NOTE (2026-06-03): this fixes a prior inversion — the formula was
    `(1 - day_pressure)`, which made the LAST fight the MOST expensive
    (hoard late / spend early), contradicting the doc's own prose +
    docstring intent. The *deadly*-fight override (collapse the cost so the
    caster novas even early in the day) is implemented as `encounter_danger`
    and applied in `candidate_slot_cost` — this pure formula stays
    danger-free so its reference values remain stable.

    slots_remaining is the count BEFORE consumption — pass the pre-cast
    count.
    """
    if slot_level <= 0:
        return 0.0   # cantrips / free actions
    scarcity = 1.0 / max(1, slots_remaining)
    day_pressure = min(1.0, max(0.0, encounters_remaining / ENCOUNTER_DAY_DIVISOR))
    return slot_level * SLOT_COST_BASE_MULTIPLIER * scarcity * day_pressure


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


def lowest_available_slot_at_or_above(actor: Actor,
                                          base_level: int) -> int | None:
    """Return the lowest slot level >= base_level where the actor has
    at least one slot available, or None if no eligible slot exists.

    Used by upcastable spells (PR #77): when a spell declares
    `upcast_scaling` and only higher slots are available, the
    executor picks the lowest one to minimize slot opportunity cost
    (matches the v1 Divine Smite heuristic from PR #73).

    Caps at 9 (no slot levels above 9 in 5e). Returns None when
    base_level <= 0 (cantrips have no slot to pick) OR when the
    actor has no slots at any qualifying level.
    """
    if base_level <= 0:
        return None
    for level in range(base_level, 10):
        if int(actor.spell_slots.get(level, 0)) > 0:
            return level
    return None


def is_upcastable(action: dict) -> bool:
    """True iff the action declares an `upcast_scaling` block.
    PR #77 introduces this field — actions with it allow casting at
    a higher slot level than the base for additional effect.
    """
    return bool(action.get("upcast_scaling"))


def has_slot_for_action(actor: Actor, action: dict) -> bool:
    """Generalized slot-availability check for the candidate filter
    (PR #77). Handles both:
      - Non-spell / cantrip actions (always available)
      - Exact-level spell actions (need slot at exact level)
      - Upcastable spell actions (need slot at base level OR HIGHER)

    Cleaner than calling `has_slot(actor, required_slot_level(a))`
    directly because it routes upcastable actions through the
    at-or-above check.
    """
    base_level = required_slot_level(action)
    if base_level <= 0:
        return True   # cantrip / not a spell
    if is_upcastable(action):
        return lowest_available_slot_at_or_above(actor, base_level) is not None
    return has_slot(actor, base_level)


def resolve_chosen_slot_level(actor: Actor, action: dict) -> int:
    """Decide which spell slot level to consume when casting this
    action (PR #77). For non-upcastable actions, returns the action's
    base level. For upcastable actions, returns the lowest available
    slot at or above the base.

    The "lowest available" heuristic mirrors the Divine Smite v1
    pattern from PR #73 — higher slot dice rarely outweigh saving
    the slot for a different spell. A follow-up PR can extend the
    AI to choose higher slots when burst damage value justifies it.

    Returns 0 for non-spell actions (no slot to consume). Raises
    ValueError if the action requires a slot but none is available
    (the candidate filter should prevent this).
    """
    base_level = required_slot_level(action)
    if base_level <= 0:
        return 0
    if not is_upcastable(action):
        return base_level
    chosen = lowest_available_slot_at_or_above(actor, base_level)
    if chosen is None:
        raise ValueError(
            f"resolve_chosen_slot_level: action "
            f"{action.get('id')!r} has base level {base_level} "
            f"but actor {actor.id!r} has no eligible slots — "
            f"candidate filter should have caught this"
        )
    return chosen


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

def encounter_danger(actor: Actor, state: CombatState) -> float:
    """Danger of the CURRENT encounter to `actor`'s side, in [0.0, 1.0].

    0.0 = safe (conserve slots normally for future fights); 1.0 = deadly
    (nova NOW — a conserved slot is worthless if the party dies here).
    Used by `candidate_slot_cost` to collapse the nova-late conserve-early
    penalty mid-day (the early-deadly-fight override).

    Only meaningful while living enemies remain — returns 0.0 if the fight
    is already won (no living enemies) or `actor` has no living allies.

    Two signals, combined by max() (worst-case governs):
      - AGGREGATE party depletion: total ally HP fraction ramps from 0
        danger at DANGER_PARTY_HP_HIGH (50%) to full danger at
        DANGER_PARTY_HP_LOW (15%).
      - ACUTE single-ally peril: any ally at/below DANGER_ALLY_CRITICAL_FRAC
        (25%) of its OWN max HP contributes peril ramping to 1.0 as it
        nears 0 HP. A near-dead Wizard makes the fight "deadly" even if the
        party's aggregate HP still looks healthy.

    This is REACTIVE (HP-based) by design: the party novas once a fight
    REVEALS itself as deadly, not pre-emptively on turn 1 at full HP (when
    conserving is still correct). A predictive enemy-threat-ratio term
    (incoming DPR vs party eHP) is a deferred v2 enhancement.
    """
    by_side = state.living_actors_by_side()
    allies = by_side.get(actor.side, [])
    enemies = [a for side, lst in by_side.items() if side != actor.side
               for a in lst]
    if not allies or not enemies:
        return 0.0

    # Aggregate party depletion.
    hp_cur = sum(max(0, a.hp_current) for a in allies)
    hp_max = sum(a.hp_max for a in allies) or 1
    frac = hp_cur / hp_max
    span = DANGER_PARTY_HP_HIGH - DANGER_PARTY_HP_LOW
    aggregate = min(1.0, max(0.0, (DANGER_PARTY_HP_HIGH - frac) / span))

    # Acute single-ally peril.
    acute = 0.0
    for a in allies:
        a_frac = max(0, a.hp_current) / (a.hp_max or 1)
        if a_frac <= DANGER_ALLY_CRITICAL_FRAC:
            peril = (DANGER_ALLY_CRITICAL_FRAC - a_frac) / DANGER_ALLY_CRITICAL_FRAC
            acute = max(acute, min(1.0, peril))

    return max(aggregate, acute)


def candidate_slot_cost(actor: Actor, action: dict,
                          state: CombatState) -> float:
    """eHP cost of casting this action given the actor's current state.

    Returns 0.0 for non-spell actions and cantrips. Otherwise computes the
    nova-late base cost via `slot_cost_ehp` (using the actor's current
    slots_remaining at the required level and state.encounters_remaining_today),
    then applies the early-deadly-fight override: the cost is scaled by
    `(1 - encounter_danger)`, so an acutely dangerous fight collapses the
    conserve-early penalty toward 0 and the caster novas now.

    At the climax (encounters_remaining = 0) the base is already 0, so the
    override is a no-op there — it only bites on a deadly fight EARLIER in
    the day, which is exactly where conserving for "future fights" is a
    false economy.
    """
    level = required_slot_level(action)
    if level <= 0:
        return 0.0
    base = slot_cost_ehp(
        slot_level=level,
        slots_remaining=remaining_slots(actor, level),
        encounters_remaining=state.encounters_remaining_today,
    )
    danger = encounter_danger(actor, state)
    return base * (1.0 - danger)
