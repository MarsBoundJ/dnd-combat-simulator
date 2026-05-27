"""Defensive eHP scoring — heal / buff / control sides of the eHP framework.

Per `docs/foundations/ehp-action-framework.md`:

  Total Action Value = Offensive eHP + Defensive eHP − Opportunity Cost

`ehp_scoring.py` covers offensive eHP (expected damage × hit prob).
This module covers the three defensive families landed in v1:

  1. Direct healing  — Defensive eHP = healing × desperation_multiplier
  2. Defensive buff  — Defensive eHP = ally_DPR_taken × Δmiss × rounds
  3. Hard control    — Defensive eHP = enemy_DPR × fail_prob × rounds

**v1 scope:**
  - Single-target only; AoE multi-target enumeration deferred
  - Flat 2.5-round time horizon for buffs/control (per framework constant)
  - No concentration-break discounting
  - DPR estimation uses observable proxies on creature templates (same
    discipline as `targeting._threat_score` — no mental-stat introspection)
  - Soft control / movement denial deferred (needs positions)
  - Offensive buff (Bless for allies) deferred (needs cross-actor attack
    mod lookup at score-time; math symmetric to defensive buff)

**Deferred (documented elsewhere):**
  - Debuff on enemy saves (rarer; lands with offensive-buff PR)
  - Spell slot opportunity cost (no slot tracking on actors yet)
  - Future-rounds discounting (flat constant for now)
  - self_preservation_coefficient scaling on defensive eHP
"""
from __future__ import annotations

from typing import Iterable

from engine.core.modifiers import query_save_modifiers
from engine.core.state import Actor, CombatState, ability_modifier
from engine.ai.ehp_scoring import (
    dice_mean, extract_damage_components,
)


# ============================================================================
# Framework constants (per ehp-action-framework.md)
# ============================================================================

# Expected encounter / buff / control duration in rounds. The Finished Book's
# 2.5-round benchmark — what to use when an effect's "real" duration is
# capped only by encounter length or concentration risk.
EXPECTED_BUFF_ROUNDS = 2.5
EXPECTED_CONTROL_ROUNDS = 2.5

# Desperation multiplier: per the framework, healing a target at 10% HP is
# worth more than healing one at 80% HP. Formula: 1.0 + max(0, 0.5 - hp_frac).
# At full HP → 1.0. At half → 1.0. At 0% → 1.5.
DESPERATION_FULL_HP_VALUE = 1.0
DESPERATION_CRITICAL_HP_VALUE = 1.5


# ============================================================================
# Healing eHP
# ============================================================================

def desperation_multiplier(target_hp_fraction: float) -> float:
    """Scales healing value upward for low-HP targets.

    At hp_fraction ≥ 0.5: 1.0 (no urgency boost).
    At hp_fraction = 0.0: 1.5 (max urgency).
    Linear in between.

    Per ehp-action-framework.md §"Direct Healing".
    """
    return 1.0 + max(0.0, 0.5 - target_hp_fraction)


def expected_healing(action: dict, caster: Actor) -> float:
    """Mean healing delivered by a heal action's pipeline.

    Sums all `heal` steps in the pipeline:
      - `dice` (e.g., "1d8") → mean
      - `fixed` → flat amount
      - `modifier_source` (e.g., "actor.con_mod") → ability modifier

    Returns 0.0 if no heal steps in the pipeline.
    """
    total = 0.0
    for step in action.get("pipeline") or []:
        if step.get("primitive") != "heal":
            continue
        params = step.get("params") or {}
        total += dice_mean(params.get("dice"))
        total += float(params.get("fixed", 0))
        mod_source = params.get("modifier_source")
        if mod_source:
            total += _resolve_caster_modifier(mod_source, caster)
    return total


def defensive_ehp_healing(actor: Actor, target_ally: Actor, action: dict,
                           state: CombatState) -> float:
    """Defensive eHP from healing an ally.

    eHP = expected_healing × desperation_multiplier, capped at the ally's
    missing HP (you can't restore more than was lost — overkill cap on
    the upside).

    Returns 0.0 if the target is at full HP, dead, or not actually an ally.
    """
    if target_ally is None or not target_ally.is_alive():
        return 0.0
    if target_ally.hp_current >= target_ally.hp_max:
        return 0.0
    missing = float(target_ally.hp_max - target_ally.hp_current)
    if missing <= 0:
        return 0.0

    hp_frac = target_ally.hp_current / target_ally.hp_max if target_ally.hp_max else 0.0
    raw = expected_healing(action, actor) * desperation_multiplier(hp_frac)
    return min(raw, missing)


# ============================================================================
# DPR estimation — observable proxies on a creature template
# ============================================================================

def estimate_dpr(creature: Actor) -> float:
    """Estimate damage-per-round from a creature's actions.

    Skeleton: takes the most-damaging attack action's expected damage,
    times multiattack count if the creature has a multiattack.

    Returns 0.0 for creatures with no usable attack actions (pure
    casters, controllers). Real DPR estimation against specific targets
    is post-MVP — this is the "generic threat magnitude" stand-in used
    when scoring defensive actions where we don't yet know who the
    enemy will swing at.
    """
    actions = (creature.template or {}).get("actions") or []
    if not actions:
        return 0.0

    # Find the highest-damage single attack action's mean damage on hit
    by_id = {a.get("id"): a for a in actions}
    best_single = 0.0
    for action in actions:
        if action.get("type") != "weapon_attack":
            continue
        single = _approximate_damage_on_hit(action)
        if single > best_single:
            best_single = single

    # Approximate hit-probability against a default AC15 with creature's bonus
    best_with_hit = 0.0
    for action in actions:
        if action.get("type") != "weapon_attack":
            continue
        bonus = _attack_bonus(action) or 0
        # vs AC 15: need (15 - bonus); clamp
        needed = 15 - bonus
        if needed <= 2:
            p_hit = 19 / 20
        elif needed > 20:
            p_hit = 1 / 20
        else:
            p_hit = (21 - needed) / 20
        single_value = _approximate_damage_on_hit(action) * p_hit
        if single_value > best_with_hit:
            best_with_hit = single_value

    # Multiattack: multiply the single-attack value by count
    multi_count = 1
    for action in actions:
        if action.get("type") == "multiattack":
            multi_count = max(multi_count, int(action.get("count", 1)))

    return best_with_hit * multi_count


def _attack_bonus(action: dict) -> int | None:
    for step in action.get("pipeline") or []:
        if step.get("primitive") == "attack_roll":
            return int((step.get("params") or {}).get("bonus", 0))
    return None


def _approximate_damage_on_hit(action: dict) -> float:
    """Mean damage on hit, ignoring crit fold-in (close enough for DPR estimate)."""
    total = 0.0
    for c in extract_damage_components(action):
        total += dice_mean(c["dice"]) + c["modifier"]
    return total


def estimate_per_attack_damage(creature: Actor) -> float:
    """Expected damage from a SINGLE attack roll vs default AC 15.

    Used by Help-shape scoring where the buff applies to one attack
    only, not a full round's worth of attacks. Multiattack does NOT
    multiply here (unlike `estimate_dpr`): Help grants advantage on
    "the next attack roll the target makes", which is one swing of
    the multiattack chain — not all of them.

    Mirrors the AC 15 hit-prob proxy used by `estimate_dpr` so the
    two scoring paths stay calibrated to the same baseline.
    Returns 0.0 for creatures with no usable attack actions.
    """
    actions = (creature.template or {}).get("actions") or []
    if not actions:
        return 0.0
    best_with_hit = 0.0
    for action in actions:
        if action.get("type") != "weapon_attack":
            continue
        bonus = _attack_bonus(action) or 0
        needed = 15 - bonus
        if needed <= 2:
            p_hit = 19 / 20
        elif needed > 20:
            p_hit = 1 / 20
        else:
            p_hit = (21 - needed) / 20
        single_value = _approximate_damage_on_hit(action) * p_hit
        if single_value > best_with_hit:
            best_with_hit = single_value
    return best_with_hit


# ============================================================================
# Defensive buff eHP (AC bonus / disadvantage on attackers)
# ============================================================================

def extract_buff_effect(action: dict) -> dict:
    """Inspect a buff action's pipeline to detect what kind of protection
    it grants. Returns a dict with one of these populated:

      {ac_bonus: int}              — flat AC buff
      {attacker_disadvantage: True}  — attackers have disadvantage
      {save_advantage: True}       — target has advantage on saves
      {save_bonus: int}            — flat bonus to saves

    Returns empty dict if no recognized buff effect is in the pipeline.

    Looks at apply_condition steps (the condition's effects), and direct
    attack_modifier / save_modifier steps in the pipeline.
    """
    out: dict = {}
    for step in action.get("pipeline") or []:
        prim = step.get("primitive")
        params = step.get("params") or {}
        if prim == "attack_modifier":
            modifier = params.get("modifier", "")
            if modifier == "ac_modifier":
                out["ac_bonus"] = int(params.get("value", 0))
            elif modifier == "disadvantage_for_attacker":
                out["attacker_disadvantage"] = True
        elif prim == "save_modifier":
            modifier = params.get("modifier", "")
            if modifier == "advantage":
                out["save_advantage"] = True
            elif modifier == "flat":
                out["save_bonus"] = int(params.get("value", 0))
    return out


def _delta_miss_from_ac(ac_bonus: int) -> float:
    """Mean Δmiss_prob from N AC bonus, roughly 5%/AC (per framework's
    Shield of Faith reference: +2 AC ≈ +10% miss chance)."""
    return min(0.95, max(0.0, ac_bonus * 0.05))


# Per framework: disadvantage on enemy attacks ≈ −20% hit chance
DELTA_MISS_FROM_DISADVANTAGE = 0.20


def defensive_ehp_defensive_buff(actor: Actor, target_ally: Actor,
                                   action: dict, state: CombatState) -> float:
    """Defensive eHP from buffing an ally's AC or imposing disadvantage on
    attackers.

      eHP = ally_dpr_taken_per_round × Δmiss × buff_rounds

    Ally damage-taken-per-round is approximated by the strongest enemy's
    DPR estimate (worst-case attacker on the ally). If no enemies are
    visible, falls back to 0 — buffing in a vacuum has no value.

    The action can override the framework's default 2.5-round buff
    duration via `defensive_buff_rounds`. Dodge uses this (lasts only
    1 round); Shield-of-Faith-shape buffs use the default.
    """
    if target_ally is None or not target_ally.is_alive():
        return 0.0

    # PR #71: Rage scoring path. Rage isn't a +AC / disadvantage buff —
    # it's an identity-state toggle that grants BPS resistance + a
    # melee damage bonus. The standard buff-shape scorer would return
    # 0 because `extract_buff_effect` doesn't find an
    # attack/save_modifier in the pipeline. Detect Rage by its
    # signature primitive and score it separately so the AI actually
    # picks it.
    if _pipeline_has_primitive(action, "rage_start"):
        return _score_rage_entry(actor, state)

    buff = extract_buff_effect(action)
    if not buff:
        return 0.0

    delta_miss = 0.0
    if "ac_bonus" in buff:
        delta_miss += _delta_miss_from_ac(buff["ac_bonus"])
    if buff.get("attacker_disadvantage"):
        delta_miss += DELTA_MISS_FROM_DISADVANTAGE
    delta_miss = min(0.95, delta_miss)
    if delta_miss <= 0:
        return 0.0

    enemies = [a for a in state.encounter.actors
                if a.side != target_ally.side and a.is_alive()]
    if not enemies:
        return 0.0
    worst_dpr = max((estimate_dpr(e) for e in enemies), default=0.0)

    buff_rounds = float(action.get("defensive_buff_rounds",
                                       EXPECTED_BUFF_ROUNDS))
    return worst_dpr * delta_miss * buff_rounds


# ============================================================================
# Rage scoring helpers (PR #71)
# ============================================================================

def _pipeline_has_primitive(action: dict, primitive_name: str) -> bool:
    """True iff the action's pipeline contains a step with this
    primitive name. Used by the Rage scorer to detect rage_start
    cheaply without importing rage state machinery."""
    for step in (action.get("pipeline") or []):
        if step.get("primitive") == primitive_name:
            return True
    return False


def _score_rage_entry(actor: Actor, state: CombatState) -> float:
    """Estimate eHP value of entering Rage now.

    Two value components, both estimated against the framework's
    EXPECTED_BUFF_ROUNDS (2.5 by default, conservative for Rage which
    practically lasts the whole encounter, but matches how other
    persistent buffs are valued):

      1. **Offensive:** +rage_damage_bonus on each STR melee swing.
         Estimate ~2 swings per round (multiattack-ready Barbarian)
         × bonus × rounds. The Barbarian's actual swing count scales
         with Extra Attack; v1 uses 2 as a midpoint between L1 (1
         swing) and L5+ (2 swings).

      2. **Defensive:** BPS resistance halves incoming damage from
         BPS-typed attacks. Estimated as 0.5 × worst_enemy_dpr ×
         rounds, on the assumption that most martial enemies deal BPS.

    Returns 0 if the actor is already raging (no benefit from re-
    entering) — preserves the "rage once per fight" expectation
    without needing a separate filter.
    """
    from engine.core.rage import is_raging
    if is_raging(actor):
        return 0.0

    bonus = int(getattr(actor, "rage_damage_bonus", 0))
    # If not raging, rage_damage_bonus is 0 (it's only stamped at
    # entry time). Read the level-table value instead so we score
    # against the bonus we WILL have post-entry.
    if bonus <= 0:
        from engine.core.rage import rage_damage_at_level
        levels = (actor.template or {}).get("levels") or {}
        bonus = rage_damage_at_level(int(levels.get("barbarian", 1)))

    # Offensive: +bonus on ~2 STR melee swings per round
    offensive_value = 2.0 * float(bonus) * EXPECTED_BUFF_ROUNDS

    # Defensive: halve worst enemy DPR (assumes BPS typing)
    enemies = [a for a in state.encounter.actors
                if a.side != actor.side and a.is_alive()]
    worst_dpr = max((estimate_dpr(e) for e in enemies), default=0.0)
    defensive_value = 0.5 * worst_dpr * EXPECTED_BUFF_ROUNDS

    return offensive_value + defensive_value


# ============================================================================
# Hard control eHP (action denial via save-or-lose conditions)
# ============================================================================

# Conditions that completely zero a creature's action economy.
# Per pillars-reconciliation: these are the "save-or-lose" effects whose
# value the AI should compute as full-DPR denial.
HARD_CONTROL_CONDITIONS = {
    "co_paralyzed",
    "co_stunned",
    "co_petrified",
    "co_unconscious",
    "co_incapacitated",
}

# Conditions that partially deny action economy. Lower value than full
# denial — apply a fractional multiplier.
PARTIAL_CONTROL_CONDITIONS = {
    "co_restrained": 0.5,    # can't move, attacks at disadvantage, attackers have advantage
    "co_blinded":    0.4,    # attacks at disadvantage, attackers have advantage
    "co_frightened": 0.3,    # disadvantage on attacks while source visible
    "co_grappled":   0.2,    # can't move
    "co_prone":      0.3,    # disadvantage on attacks; melee attackers have advantage
}


def extract_control_intent(action: dict) -> dict:
    """Inspect a control action's pipeline for the save + apply_condition shape.

    Returns:
      {save_ability, save_dc_source, save_dc_fixed, condition_id, denial_fraction}
      or {} if not a recognized control shape.

    Recognized shape:
      pipeline:
        - primitive: forced_save
          params:
            ability: <wisdom|...>
            dc: <int>  OR  dc_source: <str>
            on_fail:
              - primitive: apply_condition
                params: { condition_id: <co_*> }
    """
    for step in action.get("pipeline") or []:
        if step.get("primitive") != "forced_save":
            continue
        params = step.get("params") or {}
        ability = params.get("ability", "wisdom")
        dc_fixed = params.get("dc")
        dc_source = params.get("dc_source")
        on_fail = params.get("on_fail") or []
        for sub in on_fail:
            if sub.get("primitive") != "apply_condition":
                continue
            sub_params = sub.get("params") or {}
            condition_id = sub_params.get("condition_id") or sub_params.get("condition")
            if not condition_id:
                continue
            denial_fraction = _denial_fraction_for_condition(condition_id)
            if denial_fraction <= 0:
                continue
            return {
                "save_ability": ability,
                "save_dc_fixed": dc_fixed,
                "save_dc_source": dc_source,
                "condition_id": condition_id,
                "denial_fraction": denial_fraction,
            }
    return {}


def _denial_fraction_for_condition(condition_id: str) -> float:
    """How much of the creature's action economy is denied by a condition?
    1.0 = full denial (hard control); 0.0 = no denial."""
    if condition_id in HARD_CONTROL_CONDITIONS:
        return 1.0
    return PARTIAL_CONTROL_CONDITIONS.get(condition_id, 0.0)


def save_fail_probability(target: Actor, ability: str, dc: int,
                            state: CombatState) -> float:
    """Probability the target FAILS the save.

    Mirrors the math `_forced_save` does at execution time, including
    advantage/disadvantage from save_modifier entries on the target.
    Nat-1 always fails, nat-20 always succeeds.
    """
    save_mods = query_save_modifiers(target, ability, state)
    override = save_mods.net_outcome_override()
    if override == "auto_fail":
        return 1.0
    if override == "auto_succeed":
        return 0.0

    short_ability = _short_ability(ability)
    save_bonus = (target.abilities.get(short_ability) or {}).get("save", 0)
    effective_dc = dc
    needed = effective_dc - save_bonus - save_mods.save_bonus_modifier
    # Single-d20 success face count
    if needed <= 2:
        single_succeed = 19 / 20.0
    elif needed > 20:
        single_succeed = 1 / 20.0
    else:
        single_succeed = (21 - needed) / 20.0

    adv = save_mods.net_advantage()
    if adv == "advantage":
        p_success = 1.0 - (1.0 - single_succeed) ** 2
    elif adv == "disadvantage":
        p_success = single_succeed ** 2
    else:
        p_success = single_succeed

    return 1.0 - p_success


def _short_ability(name: str) -> str:
    mapping = {
        "strength": "str", "dexterity": "dex", "constitution": "con",
        "intelligence": "int", "wisdom": "wis", "charisma": "cha",
    }
    return mapping.get(name, name)


def _resolve_dc_for_action(action_intent: dict, caster: Actor) -> int:
    """Resolve the save DC the AI expects to use.

    Mirrors primitives._resolve_dc but works at scoring-time (no
    state.current_attack populated yet).
    """
    if action_intent.get("save_dc_fixed") is not None:
        return int(action_intent["save_dc_fixed"])
    dc_source = action_intent.get("save_dc_source") or ""
    if dc_source == "caster_spell_save_dc":
        int_mod = ability_modifier(
            (caster.abilities.get("int") or {}).get("score", 10)
        )
        pb = (caster.template.get("cr") or {}).get("proficiency_bonus", 2)
        return 8 + int_mod + pb
    if dc_source.startswith("fixed:"):
        try:
            return int(dc_source[len("fixed:"):])
        except ValueError:
            return 13
    return 13


def defensive_ehp_hard_control(actor: Actor, target_enemy: Actor,
                                 action: dict, state: CombatState) -> float:
    """Defensive eHP from a save-or-lose control action.

      eHP = enemy_DPR × fail_prob × expected_rounds × denial_fraction

    Returns 0.0 if the action doesn't match the control shape or the
    target is dead.
    """
    if target_enemy is None or not target_enemy.is_alive():
        return 0.0

    intent = extract_control_intent(action)
    if not intent:
        return 0.0

    dc = _resolve_dc_for_action(intent, actor)
    p_fail = save_fail_probability(target_enemy, intent["save_ability"],
                                     dc, state)
    enemy_dpr = estimate_dpr(target_enemy)
    return (enemy_dpr * p_fail * EXPECTED_CONTROL_ROUNDS
            * intent["denial_fraction"])


# ============================================================================
# Helpers
# ============================================================================

def _resolve_caster_modifier(source: str, caster: Actor) -> float:
    """Mirror primitives._resolve_modifier for ability mods.

    Conservative: returns 0.0 for unknown sources rather than raising,
    since scoring is the wrong moment to fail loud.
    """
    abilities = caster.abilities or {}
    table = {
        "actor.str_mod": "str", "actor.dex_mod": "dex",
        "actor.con_mod": "con", "actor.int_mod": "int",
        "actor.wis_mod": "wis", "actor.cha_mod": "cha",
    }
    short = table.get(source)
    if short is not None:
        return float(ability_modifier((abilities.get(short) or {}).get("score", 10)))
    # Class-level shapes like "actor.cleric_level"
    if source.startswith("actor.") and source.endswith("_level"):
        cls_name = source[len("actor."):-len("_level")]
        return float((caster.template.get("levels") or {}).get(cls_name, 1))
    return 0.0
