"""eHP scoring — the offensive-eHP layer of the Ammann + eHP hybrid AI.

Per `docs/foundations/ehp-action-framework.md` and
`docs/foundations/pillars-reconciliation.md` §7 step 5, every action's value
is expressed in expected-HP-removed units so the AI can compare disparate
options (longsword vs spell vs heal vs control) on a single scale.

  Total Action Value = Offensive eHP + Defensive eHP − Opportunity Cost

**v1 scope (this module):**
  - Offensive eHP only: expected damage × hit probability, summed across
    sub-attacks for multiattack candidates.
  - Hit probability accounts for active_modifiers via the unified
    modifier-query layer (Blinded target → attacker has advantage → higher
    hit_prob → higher eHP delivered → AI organically prefers Blinded targets).
  - aggression_coefficient from archetype scales the final eHP score.
  - No spell slot opportunity cost (no casters in current fixtures).
  - No defensive eHP, no future-rounds discounting, no AoE optimization.

**Deferred:** the rest of the eHP framework (heal/buff/control/debuff
formulas, opportunity cost, behavioral coefficients beyond aggression,
positioning eHP) per ehp-action-framework.md Known Gaps table.

The functions here are pure: given a candidate dict and a CombatState,
return a float eHP score. The decision_layer module consumes them.
"""
from __future__ import annotations

import re
from typing import Iterable

from engine.core.modifiers import (
    query_attack_modifiers,
    query_crit_modifiers,
)
from engine.core.state import Actor, CombatState


# ============================================================================
# Aggression coefficient — Ammann behavioral weight (§ ehp-action-framework.md)
# ============================================================================

# Per-archetype aggression coefficients. Values in [0.5, 1.5] per the
# framework table. v1 keeps these conservative — they scale raw eHP, not
# the decision shape, so small differences here are deliberate.
_AGGRESSION_BY_ARCHETYPE: dict[str, float] = {
    "mindless_aggressor": 1.3,     # all gas, no brakes
    "berserker_fanatic":  1.5,     # most aggressive
    "apex_predator":      1.1,     # disciplined but assertive
    "pack_hunter":        1.1,
    "territorial_beast":  1.0,
    "cowardly_skirmisher": 0.8,    # under-commits
}
_DEFAULT_AGGRESSION = 1.0


def aggression_coefficient(actor: Actor) -> float:
    """Return the actor's aggression coefficient (default 1.0 if no archetype)."""
    bp = (actor.template.get("behavior_profile") or {})
    archetype = bp.get("archetype")
    if archetype and archetype in _AGGRESSION_BY_ARCHETYPE:
        return _AGGRESSION_BY_ARCHETYPE[archetype]
    return _DEFAULT_AGGRESSION


# ============================================================================
# Dice expression mean (e.g., "2d6" → 7.0, "1d8+3" → 7.5)
# ============================================================================

_DICE_PATTERN = re.compile(r"\s*(\d+)\s*d\s*(\d+)\s*$", re.IGNORECASE)


def dice_mean(expr: str | None) -> float:
    """Mean roll of a dice expression like '2d6' (modifier handled separately).

    Returns 0.0 for empty/None. Raises ValueError on malformed strings.
    """
    if not expr:
        return 0.0
    m = _DICE_PATTERN.fullmatch(expr.strip())
    if not m:
        raise ValueError(f"Invalid dice expression: {expr!r}")
    count, sides = int(m.group(1)), int(m.group(2))
    # Mean of NdS = N * (S + 1) / 2
    return count * (sides + 1) / 2.0


# ============================================================================
# Hit probability (d20 + bonus vs AC, with advantage / disadvantage)
# ============================================================================

def hit_probability(attack_bonus: int, target_ac: int,
                     advantage_state: str = "normal",
                     crit_threshold: int = 20) -> float:
    """Probability of hitting (including crits) on a single attack roll.

    Args:
      attack_bonus: total to-hit modifier (proficiency + ability + magic).
      target_ac: defender's AC.
      advantage_state: "normal" | "advantage" | "disadvantage".
      crit_threshold: d20 face at-or-above which a roll auto-crits (default 20).

    Returns:
      Probability in [0.0, 1.0]. Natural 1 always misses (per 5e rules);
      natural 20+ always hits (and is a crit by default).
    """
    # The d20 face required to hit (clamped to [2, 20] — nat 1 always miss,
    # nat 20 always hit even if math says it shouldn't).
    needed = target_ac - attack_bonus
    if needed <= 2:
        single_hit_prob = 19 / 20.0   # only nat 1 misses
    elif needed > 20:
        single_hit_prob = 1 / 20.0    # only nat 20 hits
    else:
        # Faces that hit: needed..20 inclusive = (21 - needed) faces
        single_hit_prob = (21 - needed) / 20.0

    if advantage_state == "advantage":
        # P(hit with adv) = 1 - (1 - p)^2
        return 1.0 - (1.0 - single_hit_prob) ** 2
    if advantage_state == "disadvantage":
        # P(hit with dis) = p^2
        return single_hit_prob ** 2
    return single_hit_prob


def crit_probability(advantage_state: str = "normal",
                      crit_threshold: int = 20) -> float:
    """Probability the attack is a critical hit.

    crit_threshold is the lowest d20 face that crits (e.g., 20 for default,
    19 for Improved Critical, 18 for Superior Critical).
    """
    faces_that_crit = max(0, 21 - crit_threshold)   # e.g., 20→1, 19→2
    single_crit_prob = faces_that_crit / 20.0
    if advantage_state == "advantage":
        return 1.0 - (1.0 - single_crit_prob) ** 2
    if advantage_state == "disadvantage":
        return single_crit_prob ** 2
    return single_crit_prob


# ============================================================================
# Action damage extraction — walk a primitive pipeline, find attack + damage
# ============================================================================

def extract_attack_bonus(action: dict) -> int | None:
    """Return the attack_bonus from the first attack_roll step, or None
    if the action has no attack_roll (e.g., automatic-hit spells).
    """
    for step in action.get("pipeline") or []:
        if step.get("primitive") == "attack_roll":
            return int((step.get("params") or {}).get("bonus", 0))
    return None


def extract_damage_components(action: dict) -> list[dict]:
    """Return all damage steps from the action's pipeline.

    Each entry: {dice: '1d8', modifier: 3, type: 'slashing'}.
    Includes only steps gated by `combat.attack_state == hit` (or no gate);
    excludes steps gated by `attack_had_advantage` etc. (sneak-attack-style).

    Skeleton: only checks for the literal hit-gate; the on-hit gate is the
    overwhelmingly common case for weapon attacks.
    """
    components: list[dict] = []
    for step in action.get("pipeline") or []:
        if step.get("primitive") != "damage":
            continue
        when = step.get("when") or {}
        cond = when.get("condition", "") if isinstance(when, dict) else ""
        # Include steps with no condition or with the standard hit gate.
        # Skip exotic conditional damage (e.g., sneak attack only with
        # advantage) — eHP-correct treatment of those is post-MVP.
        if cond and "attack_state == hit" not in cond:
            continue
        params = step.get("params") or {}
        components.append({
            "dice": params.get("dice"),
            "modifier": int(params.get("modifier", 0)),
            "type": params.get("type", "untyped"),
        })
    return components


def expected_damage_on_hit(action: dict, target: Actor,
                            crit_prob: float = 0.0) -> float:
    """Mean damage *given* the attack hits.

    Accounts for target's damage resistance / vulnerability / immunity (the
    same template-level reductions `_damage()` applies at execution time).

    crit_prob doubles only the dice portion (modifier doesn't double under
    5e crit rules), folded into the mean as: dice * (1 + crit_prob).
    """
    template = target.template or {}
    immunities = set(template.get("damage_immunities") or [])
    resistances = set(template.get("damage_resistances") or [])
    vulnerabilities = set(template.get("damage_vulnerabilities") or [])

    total = 0.0
    for c in extract_damage_components(action):
        dice_part = dice_mean(c["dice"])
        # Crits double the dice; modifier stays single.
        mean_damage = dice_part * (1.0 + crit_prob) + c["modifier"]
        dtype = c["type"]
        if dtype in immunities:
            mean_damage = 0.0
        elif dtype in resistances:
            mean_damage = mean_damage / 2.0
        elif dtype in vulnerabilities:
            mean_damage = mean_damage * 2.0
        total += mean_damage
    return total


# ============================================================================
# Offensive eHP for a single attack and for multiattack
# ============================================================================

def offensive_ehp_single_attack(actor: Actor, target: Actor, action: dict,
                                  state: CombatState) -> float:
    """Expected HP removed by one weapon_attack action.

    eHP = hit_prob × expected_damage_on_hit, capped at target's remaining HP
    (overkill doesn't deliver more value than what's there to take).

    Consults active_modifiers on attacker + target so that advantage from
    Blinded targets, the Shield spell, etc., flows into the score.
    """
    attack_bonus = extract_attack_bonus(action)
    if attack_bonus is None:
        # Non-attack-roll action (auto-hit spell etc.) — eHP scoring of those
        # is post-MVP; treat as 0 here so we don't accidentally pick them.
        return 0.0

    # Query unified modifier registry — this is what makes the AI exploit
    # conditions: a Blinded target grants advantage, which raises hit_prob.
    attack_mods = query_attack_modifiers(actor, target, state)
    crit_mods = query_crit_modifiers(actor, target, state)
    adv_state = attack_mods.net_advantage()
    effective_ac = target.ac + attack_mods.ac_modifier
    effective_bonus = attack_bonus + attack_mods.attack_bonus_modifier

    p_hit = hit_probability(effective_bonus, effective_ac, adv_state,
                             crit_mods.crit_threshold)
    p_crit = crit_probability(adv_state, crit_mods.crit_threshold)
    # P(crit given hit) is what we want for damage scaling; clamp safely.
    p_crit_given_hit = (p_crit / p_hit) if p_hit > 0 else 0.0

    mean_dmg_on_hit = expected_damage_on_hit(action, target,
                                              crit_prob=p_crit_given_hit)
    raw_ehp = p_hit * mean_dmg_on_hit
    # Overkill cap: can't deliver more eHP than target has left to lose.
    return min(raw_ehp, float(max(0, target.hp_current)))


def offensive_ehp_multiattack(actor: Actor, target: Actor, action: dict,
                                state: CombatState) -> float:
    """Sum of offensive eHP across the multiattack's sub-attacks.

    v1 simplification: all sub-attacks aimed at the same target (matching
    the skeleton's _execute_multiattack behavior). The overkill cap is
    applied to the running total, not per-attack — once the target's HP is
    "spent", further attacks don't add eHP.
    """
    count = int(action.get("count", 1))
    sub_action_ids: list[str] = action.get("sub_actions") or []
    if not sub_action_ids:
        return 0.0

    template_actions = actor.template.get("actions") or []
    by_id = {a.get("id"): a for a in template_actions}

    target_hp = float(max(0, target.hp_current))
    total = 0.0
    for i in range(count):
        sub_id = sub_action_ids[i % len(sub_action_ids)]
        sub_action = by_id.get(sub_id)
        if sub_action is None:
            continue
        per_attack = offensive_ehp_single_attack(actor, target, sub_action, state)
        # Apply running overkill cap so later sub-attacks against a
        # near-dead target don't inflate the multiattack score.
        remaining = max(0.0, target_hp - total)
        total += min(per_attack, remaining)
        if total >= target_hp:
            break
    return total


# ============================================================================
# Public scoring entry point — score one candidate
# ============================================================================

def score_candidate(candidate: dict, state: CombatState) -> float:
    """Return the raw eHP score for a single candidate (offensive OR defensive).

    Recognized candidate kinds:
      - 'weapon_attack' / 'multiattack' — offensive_ehp (this module)
      - 'heal' / 'defensive_buff' / 'hard_control' — defensive_ehp (sibling
        module). Dispatched on action.type so the candidate generator can
        emit defensive candidates whose target is an ally.

    Unknown kinds return 0.0 (will lose to anything that scores).

    Note: caller (decision_layer.score_candidates_v1) applies aggression
    coefficient + preset preference bonuses on top of this raw score.
    """
    actor: Actor = candidate.get("actor")
    target: Actor = candidate.get("target")
    action: dict = candidate.get("action") or {}
    kind = candidate.get("kind")
    if not actor or not target or not action:
        return 0.0
    if not target.is_alive():
        return 0.0

    # Offensive (this module)
    if kind == "multiattack" or action.get("type") == "multiattack":
        return offensive_ehp_multiattack(actor, target, action, state)
    if kind == "weapon_attack" or action.get("type") == "weapon_attack":
        return offensive_ehp_single_attack(actor, target, action, state)

    # Defensive — lazy-import to keep modules cleanly separable
    action_type = action.get("type")
    if action_type in ("heal", "defensive_buff", "hard_control") \
            or kind in ("heal", "defensive_buff", "hard_control"):
        from engine.ai import defensive_ehp as _def
        effective_type = action_type or kind
        if effective_type == "heal":
            return _def.defensive_ehp_healing(actor, target, action, state)
        if effective_type == "defensive_buff":
            return _def.defensive_ehp_defensive_buff(actor, target, action, state)
        if effective_type == "hard_control":
            return _def.defensive_ehp_hard_control(actor, target, action, state)
    return 0.0


def best_action_against(actor: Actor, target: Actor, state: CombatState,
                         actions: Iterable[dict]) -> dict | None:
    """Pick the highest-eHP action from `actions` against the given target.

    Used by `ability_selection._pick_tactical / _pick_optimal` to choose
    the best attack option for an already-chosen target. Ties are broken
    by first-listed (max() is stable on first occurrence).
    """
    actions = list(actions)
    if not actions:
        return None
    if target is None:
        # No target to score against → fall back to first action.
        return actions[0]

    best: tuple[float, dict] | None = None
    for action in actions:
        kind = action.get("type")
        if kind == "multiattack":
            score = offensive_ehp_multiattack(actor, target, action, state)
        elif kind == "weapon_attack":
            score = offensive_ehp_single_attack(actor, target, action, state)
        else:
            score = 0.0
        if best is None or score > best[0]:
            best = (score, action)
    return best[1] if best else None
