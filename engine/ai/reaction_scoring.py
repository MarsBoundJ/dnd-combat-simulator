"""Pace-aware reaction value estimators (PR #56).

PR #45 / PR #46 shipped reactions (Shield, Counterspell, Hellish
Rebuke) with v1 always-fire semantics: if eligible and slot
available, fire. Both PRs flagged "pace-aware reaction scoring
deferred." This module closes that residue.

The pace-aware gate in `reactions.try_use_reaction` compares:

  cost = feature_pacing.reaction_cost_ehp(slot_level, slots_remaining,
                                              encounters_remaining)
  value = estimate_reaction_value_ehp(action, event_data, reactor, state)

If cost > value, the reaction skips (logs `reaction_skipped_pace`).
Otherwise it fires as before.

**Per-reaction value heuristics:**
  - **Shield** — the condition `shield_would_help` already filters to
    "this attack would hit without us, will miss with us." Value =
    expected damage of the attacker's best weapon attack (we'd avoid
    the full damage by missing).
  - **Counterspell** — value proportional to the spell's slot level,
    using the same `REACTION_SLOT_BASE_COSTS` curve as the cost side.
    A 3rd-level Counterspell on a 3rd-level Fireball roughly trades
    value-for-value.
  - **Hellish Rebuke** — expected fire damage (2d10 with ~50% save
    rate ≈ 8.25 eHP), modulated by attacker resistance / immunity /
    vulnerability.

**Unknown reactions**: any reaction without an estimator returns
`float("inf")` so the cost check passes — preserves v1 always-fire
semantics for reactions we haven't scored yet (forward compatibility).

**Override hook**: actions tagged `signature_reaction: true` bypass
the pace gate entirely (always fire if slot is available). The
`reactions.try_use_reaction` site checks this BEFORE calling the
value estimator.
"""
from __future__ import annotations

import re

from engine.core.feature_pacing import REACTION_SLOT_BASE_COSTS
from engine.core.state import Actor, CombatState


# ============================================================================
# Damage estimation helpers
# ============================================================================

_DICE_PATTERN = re.compile(r"(\d+)d(\d+)")


def _dice_avg(expr: str) -> float:
    """Average roll of a dice expression like '2d6' → 7.0.

    Returns 0.0 on parse failure (defensive — caller should pass a
    valid weapon-spec dice string).
    """
    if not expr:
        return 0.0
    m = _DICE_PATTERN.fullmatch(expr.strip())
    if not m:
        return 0.0
    count, sides = int(m.group(1)), int(m.group(2))
    return count * (sides + 1) / 2.0


def _estimate_attack_damage(attacker: Actor) -> float:
    """Average damage of attacker's best weapon_attack action.

    Scans `attacker.template.actions` for weapon_attack entries; for
    each, sums the average roll of each `damage` primitive step's
    dice + flat modifier. Returns the maximum across actions (the
    "best" weapon — what the attacker would lead with).

    Ignores attack bonus / target AC because the caller has already
    verified the attack was going to hit. Ignores resistances
    because the caller's reactor (Shield user) is the target and
    presumably knows their own resistances; v1 doesn't factor.

    Returns 0.0 if the attacker has no weapon_attack actions.
    """
    if attacker is None or attacker.template is None:
        return 0.0
    best = 0.0
    for action in (attacker.template.get("actions") or []):
        if action.get("type") != "weapon_attack":
            continue
        total = 0.0
        for step in (action.get("pipeline") or []):
            if step.get("primitive") != "damage":
                continue
            params = step.get("params") or {}
            total += _dice_avg(str(params.get("dice", "")))
            total += float(params.get("modifier", 0))
        if total > best:
            best = total
    return best


# ============================================================================
# Per-reaction value estimators
# ============================================================================

def shield_value_ehp(action: dict, event_data: dict,
                        reactor: Actor, state: CombatState) -> float:
    """Estimate eHP value of casting Shield as a reaction.

    The Shield condition (`shield_would_help`) already filters to
    "attack would hit without +5 AC, will miss with it." So Shield
    is guaranteed to convert this attack from hit → miss. Value =
    the expected damage we'd take from that attack.

    When the attacker is missing from event_data (defensive — happens
    in stripped-down test event_data shapes), returns `float("inf")`.
    Matches the unknown-reaction policy: when we can't estimate, fall
    back to "always fire" (the conservative gate, not a blocking one).
    """
    attacker = event_data.get("actor") or event_data.get("attacker")
    if attacker is None:
        return float("inf")
    estimated = _estimate_attack_damage(attacker)
    if estimated <= 0.0:
        # Attacker exists but has no scorable weapon attacks (e.g., a
        # template without an actions list). Fall back to "always fire."
        return float("inf")
    return estimated


def counterspell_value_ehp(action: dict, event_data: dict,
                              reactor: Actor, state: CombatState) -> float:
    """Estimate eHP value of Counterspell.

    Uses the slot-level → eHP curve from `REACTION_SLOT_BASE_COSTS`
    as the proxy for "what would this spell have done if cast?"
    A 3rd-level Counterspell countering a 3rd-level Fireball thus
    breaks roughly even (which is RAW: same-level Counterspell
    auto-counters, value-for-value).

    For higher-level enemy spells, value scales up — Counterspell
    becomes worth burning even a precious slot to prevent the
    8th-level Power Word Stun.
    """
    # event_data carries the target spell's slot level under
    # `spell_slot_level` (set in pipeline.execute's
    # spell_cast_initiated emit). Some test event_data shapes use
    # `spell_level` — accept either for robustness.
    spell_level = int(
        event_data.get("spell_slot_level")
        or event_data.get("spell_level")
        or 1
    )
    # Use the base cost at the SPELL's level as the value (not the
    # counterspell's slot level, which is on the cost side).
    base = REACTION_SLOT_BASE_COSTS.get(spell_level)
    if base is None:
        # Spell level above our table — clamp to the max known level.
        base = REACTION_SLOT_BASE_COSTS[max(REACTION_SLOT_BASE_COSTS)]
    return float(base)


def hellish_rebuke_value_ehp(action: dict, event_data: dict,
                                reactor: Actor, state: CombatState) -> float:
    """Estimate eHP value of Hellish Rebuke.

    RAW: 2d10 fire (avg 11) DEX save vs spell DC; half on success.
    Assuming a roughly average save rate (~50%), expected damage
    = 11 × 0.5 + 5.5 × 0.5 ≈ 8.25 eHP.

    Modulated by attacker template's fire resistance / immunity /
    vulnerability.
    """
    attacker = event_data.get("attacker")
    if attacker is None:
        # Missing context (defensive) — fall back to always-fire policy.
        return float("inf")
    expected = 11.0 * 0.5 + 5.5 * 0.5    # ≈ 8.25
    template = attacker.template or {}
    if "fire" in (template.get("damage_immunities") or []):
        return 0.0
    if "fire" in (template.get("damage_resistances") or []):
        expected /= 2.0
    if "fire" in (template.get("damage_vulnerabilities") or []):
        expected *= 2.0
    return expected


# ============================================================================
# Dispatch
# ============================================================================

# Reaction id → value estimator. Add new reactions here as they land.
# Reactions NOT in this table return float("inf") from the public
# `estimate_reaction_value_ehp` — preserves v1 always-fire semantics
# for unscored reactions (forward compatibility).
_REACTION_VALUE_ESTIMATORS = {
    "a_shield": shield_value_ehp,
    "a_counterspell": counterspell_value_ehp,
    "a_hellish_rebuke": hellish_rebuke_value_ehp,
}


def estimate_reaction_value_ehp(action: dict, event_data: dict,
                                    reactor: Actor,
                                    state: CombatState) -> float:
    """Public dispatch — return the eHP value of firing `action` as a
    reaction given the triggering event_data.

    Unknown reaction id → `float("inf")` (forward compatibility for
    reactions not yet scored).
    """
    action_id = action.get("id")
    estimator = _REACTION_VALUE_ESTIMATORS.get(action_id)
    if estimator is None:
        return float("inf")
    return estimator(action, event_data, reactor, state)
