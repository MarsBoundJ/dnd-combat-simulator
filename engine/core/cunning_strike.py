"""Cunning Strike — Rogue L5+ (PR #81).

RAW PHB 2024 (Rogue L5): "When you deal Sneak Attack damage, you can
add one of the following effects, paying its cost in Sneak Attack
dice. Reduce your Sneak Attack damage by the number of dice you
spend. For example, if you would normally deal 3d6 Sneak Attack
damage and spend 1d6 on Trip, you deal 2d6 Sneak Attack damage and
trigger Trip."

v1 options (all cost 1d6 at L5; higher tiers ship Devious Strikes
at L11 / Improved Cunning Strikes at L14 — deferred):
  - Poison: target makes a CON save vs the Cunning Strike DC; on
    fail, the target has the Poisoned condition (1 minute, save at
    end of each turn — v1 applies for until_actor_next_turn_start
    with a recurring save shape)
  - Trip: target Large or smaller makes a DEX save; on fail, Prone
  - Withdraw: you move up to half your speed without provoking
    opportunity attacks (v1: sets actor.disengaging = True; the
    extra-half-speed-move portion is approximated by allowing a
    post-BA second-move pass via PR #74's dash flag, capped at
    half speed)

DC formula: 8 + DEX_mod + proficiency_bonus (matches the Rogue's
class DC convention introduced in PHB 2024).

Architecture:
  - `try_apply_sneak_attack` in sneak_attack.py calls
    `pick_cunning_strike_effect` to decide whether to spend a die
    on an effect. If returned, the SA dice count is reduced by the
    cost BEFORE rolling, and the effect is applied AFTER the
    damage step via `apply_cunning_strike_effect`.
  - AI heuristic: each option has an estimated value; pick the
    highest value if it exceeds the cost (3.5 avg damage per d6).
    Returns None if no effect beats the cost.

v1 simplifications:
  - "Vial of basic poison" RAW prereq dropped (Rogue always has
    access to Poison v1)
  - Withdraw's "move up to half your speed" doesn't strictly half-
    cap; the post-BA dash retry path uses full speed. RAW: the
    suppression of OAs is the main mechanical value.
  - Higher-tier effects (Devious Strikes, Improved Cunning Strikes)
    deferred — only Poison / Trip / Withdraw ship in v1
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState, ability_modifier
from engine.core.sizes import size_at_or_below


# ============================================================================
# Constants
# ============================================================================

# RAW PHB 2024 Cunning Strike comes online at Rogue L5.
MIN_ROGUE_LEVEL = 5

# Avg damage per d6 (used for the AI cost comparison: an effect
# must beat ~3.5 eHP to be worth spending a die on).
D6_AVERAGE = 3.5

# Per-option metadata: cost in SA dice + flags.
CUNNING_STRIKE_OPTIONS: dict[str, dict] = {
    "poison": {
        "name": "Poison",
        "cost_dice": 1,
        "save_ability": "constitution",
        "applies_condition": "co_poisoned",
        "size_gate": None,        # no size restriction
    },
    "trip": {
        "name": "Trip",
        "cost_dice": 1,
        "save_ability": "dexterity",
        "applies_condition": "co_prone",
        # RAW: "Large or smaller" — sets the upper-bound size
        "size_gate": "large",
    },
    "withdraw": {
        "name": "Withdraw",
        "cost_dice": 1,
        "save_ability": None,    # no save — self-buff effect
        "applies_condition": None,
        "size_gate": None,
    },
}


# ============================================================================
# DC + qualification
# ============================================================================

def cunning_strike_dc(actor: Actor) -> int:
    """RAW PHB 2024 Rogue class DC: 8 + DEX_mod + PB.

    Reads DEX from actor.abilities and PB from the cr block (PCs
    have PB stamped under cr.proficiency_bonus by pc_schema)."""
    dex_score = (actor.abilities.get("dex") or {}).get("score", 10)
    dex_mod = ability_modifier(dex_score)
    pb = int((actor.template.get("cr") or {})
                .get("proficiency_bonus", 2))
    return 8 + dex_mod + pb


def qualifies_for_cunning_strike(actor: Actor) -> bool:
    """True iff the actor has at least L5 Rogue. Mirrors the
    `_rogue_level` check in sneak_attack.py."""
    levels = (actor.template or {}).get("levels") or {}
    return int(levels.get("rogue", 0)) >= MIN_ROGUE_LEVEL


# ============================================================================
# AI heuristic — pick the best effect (or None for full damage)
# ============================================================================

def pick_cunning_strike_effect(attacker: Actor, target: Actor,
                                   state: CombatState) -> str | None:
    """Decide whether to trade SA dice for a Cunning Strike effect.

    Returns the effect id (string key in CUNNING_STRIKE_OPTIONS) to
    apply, or None to skip the trade (preserve full SA damage).

    Value estimation per option:
      - Poison: enemy_DPR × 0.225 (disadvantage proxy) × ~2.5
        rounds × p_fail. Skipped vs Constructs / Undead (poison-
        immune templates skip naturally because their save would
        also fail to apply the condition meaningfully — but v1
        doesn't check immunity here; the existing template-side
        damage_immunities apply at condition-application time.)
      - Trip: enemy_DPR × 0.225 × ~1 round × p_fail. Lower duration
        because RAW: Prone creature can use half movement to stand
        up next turn. Size-gated (Large or smaller).
      - Withdraw: ~5 eHP if attacker is adjacent to ≥2 enemies
        (escape value), else 0.

    Picks the highest-value option that exceeds D6_AVERAGE (3.5).
    Returns None when no option beats the cost.
    """
    if not qualifies_for_cunning_strike(attacker):
        return None
    best_effect: str | None = None
    best_value = D6_AVERAGE   # must beat 3.5 to be worth the cost

    # ---- Poison ----
    poison_value = _estimate_poison_value(attacker, target, state)
    if poison_value > best_value:
        best_effect = "poison"
        best_value = poison_value

    # ---- Trip ----
    trip_value = _estimate_trip_value(attacker, target, state)
    if trip_value > best_value:
        best_effect = "trip"
        best_value = trip_value

    # ---- Withdraw ----
    withdraw_value = _estimate_withdraw_value(attacker, state)
    if withdraw_value > best_value:
        best_effect = "withdraw"
        best_value = withdraw_value

    return best_effect


def _estimate_poison_value(attacker: Actor, target: Actor,
                              state: CombatState) -> float:
    """eHP value of applying Poisoned via Cunning Strike.

    Poisoned imposes Disadvantage on attack rolls and ability checks
    for 1 minute (re-save each turn). Approximate as:
        target_dpr × DELTA_HIT_FROM_ADVANTAGE × 2.5 rounds × p_fail
    """
    from engine.ai.ehp_scoring import DELTA_HIT_FROM_ADVANTAGE
    from engine.ai.defensive_ehp import estimate_per_attack_damage, save_fail_probability
    target_dpr = estimate_per_attack_damage(target)
    if target_dpr <= 0:
        return 0.0
    dc = cunning_strike_dc(attacker)
    p_fail = save_fail_probability(target, "constitution", dc, state)
    return target_dpr * DELTA_HIT_FROM_ADVANTAGE * 2.5 * p_fail


def _estimate_trip_value(attacker: Actor, target: Actor,
                            state: CombatState) -> float:
    """eHP value of applying Prone via Trip.

    **Corrected RAW model (per Phil's note):** A Prone target stands
    up at the start of their next turn by spending half their
    movement. They then act normally — NO disadvantage on their own
    attacks (they stand before they swing). The Rogue who applied
    Trip ALSO doesn't benefit on their next swing — their next turn
    comes AFTER the target's stand-up.

    Trip is therefore fundamentally a **party-coordination move**:
    only allies whose initiative slot falls AFTER the attacker but
    BEFORE the target's next turn get the value (one attack at
    advantage against the still-prone target, since they're adjacent
    melee). Ranged allies get DISADVANTAGE against prone per RAW
    and are excluded.

    Approximation:
        sum (over allies_acting_before_target who are adjacent melee)
        of ally_DPR × DELTA_HIT_FROM_ADVANTAGE × p_fail

    Returns 0 if:
      - Target larger than Large (size gate)
      - No allies act in the (attacker, target) initiative window
      - All eligible allies are out of melee reach (5 ft)

    Implication: solo Rogue trips have value 0 — Trip is only worth
    spending an SA die when the party composition + initiative
    order let multiple melee allies capitalize.

    Future: party initiative coordination (Ready Action, Help,
    holding initiative) is a deeper AI topic — see deferred
    roadmap.
    """
    from engine.ai.ehp_scoring import DELTA_HIT_FROM_ADVANTAGE
    from engine.ai.defensive_ehp import estimate_dpr, save_fail_probability
    from engine.core.geometry import distance_ft
    # Size gate (RAW: Large or smaller)
    if not size_at_or_below(target.size, "large"):
        return 0.0
    dc = cunning_strike_dc(attacker)
    p_fail = save_fail_probability(target, "dexterity", dc, state)
    if p_fail <= 0:
        return 0.0

    # Identify allies whose next attack happens BEFORE the target's
    # next turn (i.e., in the initiative window between now and
    # when target stands up). Each adjacent melee ally's FULL TURN
    # of attacks benefits from advantage against the prone target
    # — so we use `estimate_dpr` (which accounts for multiattack)
    # rather than single-attack damage. A Fighter L5 with two
    # swings per turn gets ~2× the value of a single-attack ally.
    eligible_allies = _allies_acting_before_target(attacker, target,
                                                       state)
    offensive_value = 0.0
    for ally in eligible_allies:
        if distance_ft(ally, target) > 5:
            continue   # ranged path: RAW disadvantage vs prone, skip
        ally_dpr = estimate_dpr(ally)
        offensive_value += ally_dpr * DELTA_HIT_FROM_ADVANTAGE
    return offensive_value * p_fail


def _allies_acting_before_target(attacker: Actor, target: Actor,
                                       state: CombatState) -> list[Actor]:
    """Return allies whose initiative slot falls in the window
    (attacker_idx, target_idx) — they get to act between the
    Trip-cast NOW and the target standing up on their turn.

    Walks `state.turn_order` from attacker's current position
    forward; collects allies until we hit the target's id (or wrap
    back to attacker). Includes the attacker only if their turn
    cycles around BEFORE target (which never happens within one
    round — the attacker's NEXT turn is after target's).

    Returns empty list when:
      - turn_order is empty (test fixtures without initiative)
      - target acts immediately after attacker (no window)
      - target's id isn't in turn_order
    """
    turn_order = state.turn_order or []
    if not turn_order or target.id not in turn_order:
        return []
    if attacker.id not in turn_order:
        return []
    attacker_idx = turn_order.index(attacker.id)
    target_idx = turn_order.index(target.id)
    # Build walk order: attacker_idx + 1, +2, ... wrapping until we
    # hit target_idx (exclusive)
    n = len(turn_order)
    eligible: list[Actor] = []
    i = (attacker_idx + 1) % n
    while i != target_idx:
        actor_id = turn_order[i]
        actor = state._actor_by_id(actor_id)
        if actor is not None and actor.is_alive() \
                and actor.side == attacker.side:
            eligible.append(actor)
        i = (i + 1) % n
        # Safety: if turn_order is malformed and we'd loop forever,
        # the wrap-back to attacker_idx would catch it. But the
        # explicit i != target_idx guard plus the for-bounded
        # walk via modulo prevents infinite loops.
        if i == attacker_idx:
            break
    return eligible


def _estimate_withdraw_value(attacker: Actor,
                                  state: CombatState) -> float:
    """eHP value of Withdraw: free Disengage + extra half-speed move.

    Value comes from: avoiding OA damage when leaving melee. Most
    valuable when attacker is adjacent to multiple enemies (each
    enemy that would have hit on OA contributes its expected
    damage).
    """
    from engine.ai.defensive_ehp import estimate_per_attack_damage
    from engine.core.geometry import distance_ft
    adjacent_enemy_dpr = 0.0
    adjacent_enemies = 0
    for enemy in state.encounter.actors:
        if enemy.side == attacker.side:
            continue
        if not enemy.is_alive():
            continue
        if distance_ft(enemy, attacker) > 5:
            continue
        adjacent_enemies += 1
        adjacent_enemy_dpr += estimate_per_attack_damage(enemy)
    if adjacent_enemies == 0:
        return 0.0
    # Each adjacent enemy might OA on our move. Withdraw suppresses
    # all of them; value = sum of their OA damage. v1 estimates as
    # one swing per enemy at full hit chance — slight over-estimate
    # but matches the "biggest OA threat scenarios are the most
    # valuable" intuition.
    return adjacent_enemy_dpr


# ============================================================================
# Effect application
# ============================================================================

def apply_cunning_strike_effect(effect_id: str, attacker: Actor,
                                    target: Actor,
                                    state: CombatState,
                                    rng: random.Random) -> dict:
    """Apply the chosen Cunning Strike effect after SA damage rolls.

    Returns a result dict describing what happened (for logging /
    test inspection). Always logs a `cunning_strike_applied` event
    with the effect, outcome, and DC.
    """
    if effect_id not in CUNNING_STRIKE_OPTIONS:
        raise ValueError(f"Unknown cunning strike effect: {effect_id!r}")
    option = CUNNING_STRIKE_OPTIONS[effect_id]
    dc = cunning_strike_dc(attacker)
    result: dict = {"effect": effect_id, "dc": dc}

    if effect_id == "withdraw":
        # Self-buff: suppress OAs for the rest of this turn. Mirrors
        # the Disengage action's behavior (PR #26).
        attacker.disengaging = True
        result["outcome"] = "applied"
        result["target"] = attacker.id
    else:
        # Save-based effect (Poison / Trip): force the save and
        # apply the condition on failure.
        ability = option["save_ability"]
        condition_id = option["applies_condition"]
        # Size gate for Trip (Large or smaller); if target is too
        # big the effect simply fails to land. RAW: Trip "Large or
        # smaller" target; bigger targets are immune.
        if option.get("size_gate") \
                and not size_at_or_below(target.size, option["size_gate"]):
            result["outcome"] = "no_effect_size_immune"
        else:
            # Roll the save inline (don't reuse _forced_save — we
            # want to keep the SA + Cunning Strike chain self-
            # contained without restructuring state.current_attack
            # mid-flow)
            from engine.core import modifiers as _modifiers
            save_mods = _modifiers.query_save_modifiers(target, ability, state)
            override = save_mods.net_outcome_override()
            if override == "auto_fail":
                outcome = "fail"
                d20 = None
            elif override == "auto_succeed":
                outcome = "success"
                d20 = None
            else:
                short_ab = _short_ability(ability)
                save_bonus = (target.abilities.get(short_ab) or {})\
                    .get("save", 0)
                adv = save_mods.net_advantage()
                if adv == "advantage":
                    d20 = max(rng.randint(1, 20), rng.randint(1, 20))
                elif adv == "disadvantage":
                    d20 = min(rng.randint(1, 20), rng.randint(1, 20))
                else:
                    d20 = rng.randint(1, 20)
                total = d20 + save_bonus + save_mods.save_bonus_modifier
                outcome = "success" if total >= dc else "fail"
            result["outcome"] = outcome
            result["target"] = target.id
            result["d20"] = d20
            if outcome == "fail" and condition_id:
                # Apply the condition directly. Use the engine's
                # apply_condition path for full condition-effect
                # instantiation (modifier registration etc.).
                from engine.primitives import _apply_condition
                saved_target = state.current_attack.get("target")
                state.current_attack["target"] = target
                try:
                    _apply_condition({
                        "condition_id": condition_id,
                        "duration": "until_actor_next_turn_start",
                    }, state, None)
                finally:
                    state.current_attack["target"] = saved_target
                result["condition_applied"] = condition_id
    state.event_log.append({
        "event": "cunning_strike_applied",
        "attacker": attacker.id,
        **result,
    })
    return result


def _short_ability(name: str) -> str:
    return {"strength": "str", "dexterity": "dex", "constitution": "con",
            "intelligence": "int", "wisdom": "wis", "charisma": "cha"}.get(
                name, name)
