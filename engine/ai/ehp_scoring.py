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


# ============================================================================
# Offensive buff for allies (Bless shape)
# ============================================================================

# Per ehp-action-framework.md §"Offensive Buff" reference values:
# - Bless (+1d4 mean +2.5 to hit) ≈ +12.5% hit chance
# - Advantage ≈ +20-25% hit chance at baseline
# These are averaged over the middle range of attack rolls; at extreme
# hit/miss probabilities the deltas shrink. v1 uses these as constants.
HIT_PROB_PER_FLAT_BONUS = 0.05      # each +1 attack bonus ≈ +5% hit chance
DELTA_HIT_FROM_ADVANTAGE = 0.225    # framework's stated reference value


def extract_offensive_buff_effect(action: dict) -> dict:
    """Inspect an offensive_buff action's pipeline to detect what kind
    of attack-side boost it grants the ally target. Returns a dict
    with one of these populated:

      {attack_bonus: int}              — flat +N to attack rolls (Bless,
                                         Guidance-shape if it applied to
                                         attacks)
      {ally_advantage: True}           — advantage on the ally's attacks
                                         (Faerie Fire from the
                                         beneficiary side; True Strike)

    Returns empty dict if no recognized buff effect is in the pipeline.

    Only inspects `attack_modifier` primitive steps whose `target` is
    `ally` or `current_target` (i.e., the buff goes to the ally, not
    the caster).
    """
    out: dict = {}
    for step in (action.get("pipeline") or []):
        if step.get("primitive") != "attack_modifier":
            continue
        params = step.get("params") or {}
        # Only count modifiers targeting the ally
        if params.get("target") not in ("ally", "current_target"):
            continue
        modifier = params.get("modifier", "")
        if modifier in ("attack_bonus", "flat"):
            out["attack_bonus"] = int(params.get("value", 0))
        elif modifier in ("advantage", "advantage_for_self"):
            out["ally_advantage"] = True
    return out


def offensive_ehp_buff_ally(actor: Actor, target_ally: Actor, action: dict,
                              state: CombatState) -> float:
    """Offensive eHP from buffing an ally's attacks (Bless-shape).

      eHP = ally_DPR × Δhit × EXPECTED_BUFF_ROUNDS

    Where:
      - ally_DPR comes from `estimate_dpr` (same observable-proxy
        discipline used everywhere)
      - Δhit ≈ attack_bonus × 0.05 (flat bonus) or 0.225 (advantage)
      - EXPECTED_BUFF_ROUNDS = 2.5 (per framework, shared constant
        with defensive_buff scoring)

    Returns 0.0 if:
      - target is not an ally (defensive guard)
      - target is dead
      - action grants no recognized offensive buff
      - target has no combat actions to estimate DPR from
    """
    # Lazy import — defensive_ehp imports from this file for save math,
    # so we keep the constant + DPR helper consumption deferred.
    from engine.ai.defensive_ehp import (
        EXPECTED_BUFF_ROUNDS, estimate_dpr,
    )

    if target_ally is None or not target_ally.is_alive():
        return 0.0
    if target_ally.side != actor.side:
        return 0.0   # never offensively buff an enemy

    # Don't re-cast the same buff every round on the same target. The
    # modifier-entry source tag (set by _build_modifier_entry) lets us
    # detect "this target already has my buff from this action."
    action_id = action.get("id")
    for mod in target_ally.active_modifiers:
        if mod.get("primitive") != "attack_modifier":
            continue
        src = mod.get("source") or {}
        if (src.get("action_id") == action_id
                and src.get("caster_id") == actor.id):
            return 0.0   # already active — re-cast would be wasted

    buff = extract_offensive_buff_effect(action)
    if not buff:
        return 0.0

    delta_hit = 0.0
    if "attack_bonus" in buff:
        delta_hit += buff["attack_bonus"] * HIT_PROB_PER_FLAT_BONUS
    if buff.get("ally_advantage"):
        delta_hit += DELTA_HIT_FROM_ADVANTAGE
    delta_hit = min(0.95, max(0.0, delta_hit))
    if delta_hit <= 0:
        return 0.0

    ally_dpr = estimate_dpr(target_ally)
    if ally_dpr <= 0:
        return 0.0

    return ally_dpr * delta_hit * EXPECTED_BUFF_ROUNDS


def offensive_ehp_help(actor: Actor, target_ally: Actor, action: dict,
                         state: CombatState) -> float:
    """eHP from the Help action — advantage on one attack by an adjacent ally.

      eHP = ally_per_attack_damage × Δhit_advantage

    Where:
      - ally_per_attack_damage is the ally's best single-attack expected
        damage at AC 15 (NOT scaled by multiattack count — Help boosts
        one attack roll, not the whole multiattack chain).
      - Δhit_advantage = 0.225 (framework constant, same as offensive
        buff with `ally_advantage`).

    Notes:
      - No EXPECTED_BUFF_ROUNDS multiplier here. Help's lifetime is
        explicitly per_single_attack — it buys one attack's worth of
        advantage, period. Bless gets ×2.5 because it's concentration
        over multiple rounds and many attacks; Help does not.
      - Per RAW the helped ally's attack must target a creature within
        5 ft of the helper. v1 doesn't filter the ally's eventual
        target by that constraint (we'd need a "who will the ally
        actually swing at" projection); we accept the small overscoring
        in exchange for a simple, robust v1.

    Returns 0.0 if:
      - target is not an ally / is dead / is self
      - ally has no weapon-attack actions to score against
      - Help is already active on the ally from this caster (don't
        stack)
    """
    if target_ally is None or not target_ally.is_alive():
        return 0.0
    if target_ally.side != actor.side:
        return 0.0
    if target_ally.id == actor.id:
        return 0.0   # can't Help yourself per RAW

    # Don't re-cast Help if a previous Help from this caster is still
    # waiting on the ally to make an attack. Same source-tag check as
    # offensive_ehp_buff_ally.
    action_id = action.get("id")
    for mod in target_ally.active_modifiers:
        if mod.get("primitive") != "attack_modifier":
            continue
        src = mod.get("source") or {}
        if (src.get("action_id") == action_id
                and src.get("caster_id") == actor.id):
            return 0.0

    from engine.ai.defensive_ehp import estimate_per_attack_damage
    per_attack = estimate_per_attack_damage(target_ally)
    if per_attack <= 0:
        return 0.0
    return per_attack * DELTA_HIT_FROM_ADVANTAGE


def offensive_ehp_aoe(actor: Actor, origin: tuple[int, int], action: dict,
                        state: CombatState,
                        direction: tuple[int, int] | None = None) -> float:
    """Expected HP delivered by an AoE save-or-half action.

    Geometry depends on action.area.shape:
      - sphere: origin = center; `direction` ignored
      - cone:  origin = apex; `direction` = unit vector (required)
      - line:  origin = start; `direction` = unit vector (required)

    For each living creature in the area:
      - p_fail × full_damage  (creature failed save → full dmg)
      - p_save × half_damage  (creature saved → half dmg, if multiplier
        configured on the on_success damage step)
    Each contribution is capped at that creature's remaining HP.

    Friendly fire: allies in the area subtract from the score (1.0
    weight in v1; `self_preservation_coefficient` modulation deferred).
    Caster themselves count as an ally — don't fireball yourself.

    Returns 0.0 if no creatures in area, action shape malformed, or
    a non-sphere shape is missing its direction.
    """
    # Lazy import to avoid circular (defensive_ehp imports from this file)
    from engine.ai.defensive_ehp import save_fail_probability
    from engine.core.geometry import (
        actors_in_radius, actors_in_cone, actors_in_line,
    )

    area = action.get("area") or {}
    shape = (area.get("shape") or "sphere").lower()
    living = [a for a in state.encounter.actors if a.is_alive()]
    affected: list = []

    if shape == "sphere":
        radius_ft = area.get("radius_ft")
        if radius_ft is None:
            return 0.0
        affected = actors_in_radius(tuple(origin), int(radius_ft), living)
    elif shape == "cone":
        length_ft = area.get("length_ft")
        if length_ft is None or direction is None:
            return 0.0
        affected = actors_in_cone(tuple(origin), tuple(direction),
                                     int(length_ft), living)
    elif shape == "line":
        length_ft = area.get("length_ft")
        width_ft = area.get("width_ft", 5)
        if length_ft is None or direction is None:
            return 0.0
        affected = actors_in_line(tuple(origin), tuple(direction),
                                     int(length_ft), int(width_ft),
                                     living)
    else:
        return 0.0

    if not affected:
        return 0.0

    # Resolve save params from the embedded forced_save step
    save_info = _extract_aoe_save_info(action, actor)
    if save_info is None:
        return 0.0
    ability, dc = save_info

    # Damage on fail / on success (full / half by multiplier)
    fail_damage_by_step = _aoe_damage_per_step(action, on="fail")
    succ_damage_by_step = _aoe_damage_per_step(action, on="success")
    # AoE applied conditions (Hypnotic Pattern → Incapacitated, Web →
    # Restrained, etc.). Scored as control eHP per affected target —
    # the AoE generalization of defensive_ehp_hard_control.
    fail_control_components = _aoe_control_components(action, on="fail")
    succ_control_components = _aoe_control_components(action, on="success")

    total = 0.0
    for target in affected:
        # Damage contribution
        full_dmg = _aoe_target_damage(target, fail_damage_by_step)
        half_dmg = _aoe_target_damage(target, succ_damage_by_step)
        p_fail = save_fail_probability(target, ability, dc, state)
        p_save = 1.0 - p_fail
        expected_dmg = (p_fail * full_dmg) + (p_save * half_dmg)
        # Overkill cap per target
        capped_dmg = min(expected_dmg, float(max(0, target.hp_current)))

        # Control contribution
        full_ctrl = _aoe_target_control_ehp(
            target, fail_control_components)
        succ_ctrl = _aoe_target_control_ehp(
            target, succ_control_components)
        expected_ctrl = (p_fail * full_ctrl) + (p_save * succ_ctrl)

        target_total = capped_dmg + expected_ctrl
        # Allies subtract (friendly fire applies to control too)
        if target.side == actor.side:
            total -= target_total
        else:
            total += target_total
    return total


def _extract_aoe_save_info(action: dict, caster: Actor) -> tuple[str, int] | None:
    """Pull (ability, dc) from the action's forced_save step, or None
    if the action isn't a save-based AoE."""
    # Lazy import for DC resolution
    from engine.ai.defensive_ehp import _resolve_dc_for_action

    for step in (action.get("pipeline") or []):
        if step.get("primitive") != "forced_save":
            continue
        params = step.get("params") or {}
        ability = params.get("ability", "dexterity")
        dc = _resolve_dc_for_action(
            {"save_dc_fixed": params.get("dc"),
              "save_dc_source": params.get("dc_source")},
            caster,
        )
        return (ability, dc)
    return None


def _aoe_damage_per_step(action: dict, on: str) -> list[dict]:
    """Extract the damage components from the forced_save's on_fail or
    on_success sub-primitives.

    Returns a list of damage-component dicts shaped like
    extract_damage_components output: {dice, modifier, type, multiplier}.
    """
    key = f"on_{on}"
    components: list[dict] = []
    for step in (action.get("pipeline") or []):
        if step.get("primitive") != "forced_save":
            continue
        for sub in ((step.get("params") or {}).get(key) or []):
            if sub.get("primitive") != "damage":
                continue
            p = sub.get("params") or {}
            components.append({
                "dice": p.get("dice"),
                "modifier": int(p.get("modifier", 0)),
                "type": p.get("type", "untyped"),
                "multiplier": float(p.get("multiplier", 1.0)),
            })
    return components


def _aoe_control_components(action: dict, on: str) -> list[dict]:
    """Extract apply_condition control entries from the forced_save's
    on_fail or on_success sub-primitives.

    Returns a list of dicts: {condition_id, denial_fraction}.
    Conditions not in HARD_CONTROL_CONDITIONS or PARTIAL_CONTROL_CONDITIONS
    are skipped (e.g., applying Bless-like buffs from a save spell is
    not "control" — it'd score 0 here).

    Used by `offensive_ehp_aoe` to score AoE spells like Hypnotic
    Pattern (Incapacitated), Web (Restrained), Color Spray (Blinded).
    """
    from engine.ai.defensive_ehp import _denial_fraction_for_condition
    key = f"on_{on}"
    components: list[dict] = []
    for step in (action.get("pipeline") or []):
        if step.get("primitive") != "forced_save":
            continue
        for sub in ((step.get("params") or {}).get(key) or []):
            if sub.get("primitive") != "apply_condition":
                continue
            p = sub.get("params") or {}
            condition_id = p.get("condition_id") or p.get("condition")
            if not condition_id:
                continue
            denial_fraction = _denial_fraction_for_condition(condition_id)
            if denial_fraction <= 0:
                continue
            components.append({
                "condition_id": condition_id,
                "denial_fraction": denial_fraction,
            })
    return components


def _aoe_target_control_ehp(target: Actor,
                              components: list[dict]) -> float:
    """Per-target control eHP from a list of components. Mirrors
    `defensive_ehp_hard_control` but per-target (the AoE caller
    multiplies by p_fail and sums across targets externally).

      ehp_per_target = target_DPR × denial_fraction × EXPECTED_CONTROL_ROUNDS

    (The p_fail factor is applied by the caller, since it's computed
    once per target from the shared save_info.)
    """
    if not components:
        return 0.0
    from engine.ai.defensive_ehp import (
        EXPECTED_CONTROL_ROUNDS, estimate_dpr,
    )
    target_dpr = estimate_dpr(target)
    if target_dpr <= 0:
        return 0.0
    total = 0.0
    for c in components:
        total += target_dpr * EXPECTED_CONTROL_ROUNDS * c["denial_fraction"]
    return total


def _aoe_target_damage(target: Actor, components: list[dict]) -> float:
    """Mean damage delivered to a single target from a set of damage
    components, applying the target's resistance/vuln/immunity AND each
    component's multiplier (e.g., on_success half-damage)."""
    template = target.template or {}
    immunities = set(template.get("damage_immunities") or [])
    resistances = set(template.get("damage_resistances") or [])
    vulnerabilities = set(template.get("damage_vulnerabilities") or [])

    total = 0.0
    for c in components:
        dice_part = dice_mean(c["dice"])
        mean_damage = dice_part + c["modifier"]
        dtype = c["type"]
        if dtype in immunities:
            mean_damage = 0.0
        elif dtype in resistances:
            mean_damage = mean_damage / 2.0
        elif dtype in vulnerabilities:
            mean_damage = mean_damage * 2.0
        mean_damage *= c["multiplier"]
        total += mean_damage
    return total


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
    if kind == "aoe_attack" or action.get("type") == "aoe_attack":
        origin = candidate.get("origin_point")
        if origin is None:
            return 0.0
        direction = candidate.get("direction")
        return offensive_ehp_aoe(actor, tuple(origin), action, state,
                                    direction=tuple(direction) if direction
                                                else None)
    if kind == "offensive_buff" or action.get("type") == "offensive_buff":
        return offensive_ehp_buff_ally(actor, target, action, state)
    if kind == "help" or action.get("type") == "help":
        return offensive_ehp_help(actor, target, action, state)
    if kind == "disengage" or action.get("type") == "disengage":
        # Disengage's real eHP depends on what move comes after (avoid
        # an OA from a specific reactor). v1 returns a small constant
        # (~0.5 eHP) so the AI considers it as a tie-breaker / last-
        # resort option but rarely beats Dodge or real attacks. Real
        # picking should happen via RP-constraint forcing or movement-
        # aware AI (deferred to a future PR).
        return 0.5

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
