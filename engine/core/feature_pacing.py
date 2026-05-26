"""Pace-aware feature-use cost formulas (PR #42).

The runner's existing Action Surge activation check (PR #31) fires
whenever charges > 0 and an in-reach attack candidate exists. With
the session runner now real (PR #41), that's the wrong call — a L2
fighter in encounter 1 of 6 burns their AS on a softball target and
has nothing left for the boss. This module adds an opportunity-cost
formula the runner consults before activating.

**Formula intent:**

  cost = base_cost × scarcity × urgency_factor

  - scarcity = 1 / charges_remaining
    (One charge left = each charge is more precious; multiple charges
    = each is less precious.)
  - urgency_factor = encounters_remaining_today / encounters_baseline
    (More future encounters = higher cost = save for later; last
    encounter of the day = low cost = spend freely.)
  - base_cost = the rough eHP value of the feature use (tunable; AS
    is roughly worth one extra attack's expected damage = 6-8 eHP for
    a typical L2 fighter; we use 6 as a slightly-permissive default).

This differs from `spell_slots.slot_cost_ehp` deliberately: that
formula's `(1 - urgency)` shape models "spell slots replenish on
long rest so spend early when you have time to recover." That logic
is questionable for the last-encounter case (you SHOULD spend your
last slot on the boss) but it's pinned by existing tests; rather
than change slot semantics here, we use a SAVE-FOR-LATER shape for
feature uses where the pacing intuition is cleaner. Long-term, both
formulas may converge.

**v1 scope:**
  - `action_surge_cost_ehp` — concrete cost for Action Surge.
  - Generic `feature_use_cost_ehp` exposed for future per-rest
    features that adopt the same shape (Bardic Inspiration, Lay on
    Hands, etc. when those classes land).

**Deferred:**
  - Pace-aware Second Wind (multi-use; less impactful than AS)
  - Per-actor "boss alarm" / Difficulty-aware activation (recognize
    a high-CR enemy as worth spending on regardless of pace)
  - Calibration against the Treantmonk damage rankings (the v1 base
    costs are eyeballed from L2-5 fighter damage ranges)
"""
from __future__ import annotations


# Encounters per adventuring day baseline. Matches the framework's
# 6-8 medium encounter assumption used in spell_slots.py.
ENCOUNTERS_BASELINE = 3.0   # urgency_factor = 1.0 when at this many remaining

# Default cost-eHP value for one Action Surge use. ~6 eHP roughly
# matches one greatsword attack's expected damage at AC 14 with +6 to
# hit. Tunable.
ACTION_SURGE_BASE_COST = 6.0


def feature_use_cost_ehp(charges_remaining: int,
                           encounters_remaining: int,
                           base_cost: float = 6.0,
                           encounters_baseline: float = ENCOUNTERS_BASELINE
                           ) -> float:
    """Opportunity cost (in eHP) of spending one charge of a per-rest
    feature use, given how many charges remain and how many encounters
    are left in the day.

    Behavior:
      - 1 charge left, last encounter: low cost — spend freely
      - 1 charge left, many encounters left: high cost — save
      - Multiple charges left: lower per-charge cost (less precious)

    Returns 0.0 if `charges_remaining <= 0` (cost of spending nothing
    is nothing; caller should already have gated on availability).
    """
    if charges_remaining <= 0:
        return 0.0
    scarcity = 1.0 / max(1, charges_remaining)
    urgency_factor = max(0.0, encounters_remaining / encounters_baseline)
    return base_cost * scarcity * urgency_factor


def action_surge_cost_ehp(charges_remaining: int,
                             encounters_remaining: int) -> float:
    """Action Surge specifically. Uses the generic formula with the
    AS_BASE_COST constant."""
    return feature_use_cost_ehp(
        charges_remaining=charges_remaining,
        encounters_remaining=encounters_remaining,
        base_cost=ACTION_SURGE_BASE_COST,
    )
