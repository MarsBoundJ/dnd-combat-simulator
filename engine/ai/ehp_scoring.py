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

    # Don't re-cast the same buff every round on the same target.
    # Cross-caster aware via `named_effect` (PR #36): two clerics
    # Blessing the same ally is wasted on the second cast per RAW.
    # Falls back to per-(caster, action_id) for actions without a
    # named_effect tag.
    from engine.ai.named_effects import buff_already_active
    if buff_already_active(target_ally, action, actor):
        return 0.0

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
        explicitly per_owner_attack OR until_source_caster_next_turn
        (PR #92) — it buys one attack's worth of advantage and the
        window closes at the helper's next turn either way.
      - Per RAW the helped ally's attack must target a creature within
        5 ft of the helper. v1 doesn't filter the ally's eventual
        target by that constraint (we'd need a "who will the ally
        actually swing at" projection); we accept the small overscoring
        in exchange for a simple, robust v1.

    Returns 0.0 if:
      - target is not an ally / is dead / is self
      - ally has no weapon-attack actions to score against
      - Help is already active on the ally from this caster
      - **PR #92 timing gate**: ally won't act before helper's next
        turn (advantage would expire unused at helper's turn-start)
      - **PR #92 wasted-advantage gate**: ally would already have
        advantage on their next attack from another source (Reckless,
        a prior Help, Steady Aim, etc.). Help would buy nothing.
    """
    if target_ally is None or not target_ally.is_alive():
        return 0.0
    if target_ally.side != actor.side:
        return 0.0
    if target_ally.id == actor.id:
        return 0.0   # can't Help yourself per RAW

    # Don't re-cast Help if a previous Help from this caster (or any
    # caster sharing the same `named_effect` tag) is still waiting on
    # the ally to make an attack. Same check as offensive_ehp_buff_ally.
    from engine.ai.named_effects import buff_already_active
    if buff_already_active(target_ally, action, actor):
        return 0.0

    # PR #92 timing gate: Help's advantage expires at the helper's
    # next turn-start (RAW). If the ally won't have a turn between
    # NOW and the helper's next turn, Help is wasted — score 0.
    if not _ally_acts_before_caster_next_turn(actor, target_ally, state):
        return 0.0

    # PR #92 wasted-advantage gate: if the ally would already swing
    # with advantage on their next attack from another source, Help
    # adds nothing. Detected sources:
    #   - Reckless Attack active (Barbarian L2+)
    #   - An existing advantage-granting attack_modifier on the ally
    #     (prior Help, Steady Aim, Vex mastery proc, etc.)
    if _ally_has_pending_advantage_source(target_ally):
        return 0.0

    from engine.ai.defensive_ehp import estimate_per_attack_damage
    per_attack = estimate_per_attack_damage(target_ally)
    if per_attack <= 0:
        return 0.0
    return per_attack * DELTA_HIT_FROM_ADVANTAGE


def _ally_acts_before_caster_next_turn(caster: Actor, ally: Actor,
                                          state: CombatState) -> bool:
    """True iff `ally` has a turn in initiative order between NOW
    (just after `caster`'s current turn) and `caster`'s NEXT turn.

    Walks state.turn_order starting one step past caster's current
    index, stopping when we wrap back to caster. If we encounter
    ally.id before wrapping back, ally acts in the Help window.

    Defensive defaults:
      - Empty turn_order or caster not in it: return True (don't
        over-prune Help — this is the conservative fallback for
        legacy fixtures that bypass roll_initiative)
      - ally not in turn_order: return False (can't act)
    """
    order = state.turn_order or []
    if not order or caster.id not in order:
        return True
    if ally.id not in order:
        return False
    caster_idx = order.index(caster.id)
    # Walk forward from one past caster, wrapping; if we see ally
    # before we cycle back to caster, ally acts in the window.
    n = len(order)
    for i in range(1, n + 1):
        pos = (caster_idx + i) % n
        if order[pos] == caster.id:
            return False
        if order[pos] == ally.id:
            return True
    return False


def _ally_has_pending_advantage_source(ally: Actor) -> bool:
    """True iff `ally` would attack with advantage on their next
    attack from a source other than the Help being scored. Detects:

      - Reckless Attack active (Barbarian)
      - Active attack_modifier on the ally granting advantage_for_self
        (prior Help, Steady Aim, Vex mastery proc, Faerie Fire on
        target — anything that sets up advantage for the ally's
        next swing)

    Used by the wasted-advantage gate in offensive_ehp_help — Help
    is dominated when the ally already has advantage queued.
    """
    if getattr(ally, "reckless_active", False):
        return True
    for mod in ally.active_modifiers:
        if mod.get("primitive") != "attack_modifier":
            continue
        params = mod.get("params") or {}
        modifier_type = params.get("modifier", "")
        # advantage_for_self = the owner has advantage on their own
        # attacks (Help-shape buff). Catches the existing-Help and
        # Steady-Aim cases without needing to enumerate sources.
        if modifier_type == "advantage_for_self":
            return True
        # advantage_for_attacker on the ally = whoever attacks the
        # ally gets advantage — NOT relevant for the ally's
        # outgoing attacks; skip.
    return False


# ============================================================================
# Hide / Search scoring (PR #59)
# ============================================================================
#
# Hide and Search were emitted as candidates in PR #48 / PR #55 with no
# real eHP scoring — Hide had no scorer at all (returned 0 by default),
# and Search relied on gated emission ("don't emit if there's nothing
# to find") rather than a value-cost weighing. This module closes both
# residues.
#
# Hide value model:
#   eHP = p_success_stealth × p_evade_perception ×
#           (offensive_value + defensive_value)
#   where:
#     - p_success_stealth = probability the Stealth roll meets DC 15
#     - p_evade_perception = fraction of enemies whose passive
#       Perception falls below the expected stealth_total (those who
#       can't auto-spot)
#     - offensive_value = own per-attack damage × DELTA_HIT_FROM_ADVANTAGE
#       (one boosted attack from Invisible advantage next turn)
#     - defensive_value = sum over in-threat-range enemies of
#       enemy_per_attack_damage × DELTA_HIT_FROM_ADVANTAGE (each enemy
#       attacks at disadvantage while we're Invisible)
#
# Search value model:
#   eHP = sum_over_hidden_enemies(p_perception_success × own_per_attack_damage)
#   The own DPR is a proxy for "value unlocked by being able to target
#   this enemy next turn." Conservative — doesn't multiply by sustained
#   turns or factor in the lost current-turn DPR (Search consumes the
#   action this turn). v1 approximation: the AI weighs Search against
#   weapon_attack on the same scale.
#
# Both formulas use existing constants:
#   - DELTA_HIT_FROM_ADVANTAGE for advantage/disadvantage value
#   - estimate_per_attack_damage from defensive_ehp for DPR estimates
#
# Gate behavior — Hide returns 0 when neither gate (heavy obscurement
# OR ≥ 3/4 cover) is satisfied, matching the runtime guard in
# `pipeline._execute_hide`.

HIDE_DC = 15    # RAW 2024 fixed DC


def _stealth_success_probability(stealth_mod: int) -> float:
    """P(d20 + stealth_mod >= 15). Returns value in [0.0, 1.0]."""
    # Need d20 >= 15 - stealth_mod. p = (21 - (15 - mod)) / 20 = (6 + mod) / 20
    # Clamp to [0, 1].
    successes = 21 - (HIDE_DC - stealth_mod)
    return max(0.0, min(20.0, successes)) / 20.0


def _expected_stealth_total(stealth_mod: int) -> int:
    """Expected `stealth_total` on a successful Hide roll.

    Among rolls that meet DC 15, the average d20 is roughly (need_value
    + 20) / 2. With stealth_mod added, the typical recorded
    stealth_total is approximately:
      avg_d20_on_success + stealth_mod
    where avg_d20_on_success ≈ (max(1, 15 - mod) + 20) / 2.

    We use this to compare against enemy passive Perception when
    estimating p_evade_perception. v1 uses a simple proxy: 11 + mod
    (≈ d20 average among success outcomes for mid-range mods).
    """
    return 11 + int(stealth_mod)


def offensive_ehp_hide(actor: Actor, action: dict,
                          state: CombatState) -> float:
    """eHP scoring for the Hide action (PR #59).

    Returns 0 when:
      - Actor not heavily obscured AND has < 3/4 cover (gate fails)
      - No living enemies (nothing to gain from Hiding)
      - All enemies would auto-spot via passive Perception (no value)

    Otherwise: `p_success_stealth × p_evade_perception ×
    (offensive_value + defensive_value)`. The offensive value is the
    one-attack-with-advantage we'd get next turn; the defensive value
    is the sum of disadvantage-applied enemy attack damage over those
    in threat range this round.
    """
    from engine.core.vision import is_in_obscured_zone
    from engine.core.skills import skill_modifier
    from engine.core.geometry import distance_ft
    from engine.core.basic_actions import _max_attack_reach
    from engine.ai.defensive_ehp import estimate_per_attack_damage

    # Gate: heavy obscurement OR 3/4+ cover. Matches _execute_hide.
    heavily_obscured = is_in_obscured_zone(actor.position, state)
    has_cover = actor.cover in ("three_quarters", "total")
    if not (heavily_obscured or has_cover):
        return 0.0

    stealth_mod = skill_modifier(actor, "stealth")
    p_success = _stealth_success_probability(stealth_mod)
    if p_success <= 0.0:
        return 0.0

    enemies = [a for a in state.encounter.actors
                if a.side != actor.side and a.is_alive()]
    if not enemies:
        return 0.0

    # Per-enemy auto-spot evasion: enemy's passive Perception must be
    # BELOW our expected stealth_total to NOT auto-spot us.
    expected_total = _expected_stealth_total(stealth_mod)
    evading_enemies = [
        e for e in enemies
        if int(getattr(e, "passive_perception", 10) or 10) < expected_total
    ]
    if not evading_enemies:
        return 0.0
    p_evade = len(evading_enemies) / len(enemies)

    # Offensive value: one boosted attack from Invisible advantage on
    # our next turn. estimate_per_attack_damage already uses the AC-15
    # hit_prob proxy; we scale by the advantage delta.
    own_per_attack = estimate_per_attack_damage(actor)
    offensive_value = own_per_attack * DELTA_HIT_FROM_ADVANTAGE

    # Defensive value: each in-threat-range enemy attacks at
    # disadvantage while we're Invisible. Sum their per-attack damage
    # × the disadvantage delta. (Disadvantage hurts the attacker by
    # the same magnitude advantage helps — symmetric.)
    defensive_value = 0.0
    for enemy in evading_enemies:
        enemy_speed = int((enemy.speed or {}).get("walk", 30))
        enemy_reach = _max_attack_reach(enemy)
        if enemy_reach <= 0:
            continue   # no attacks to debuff
        if distance_ft(enemy, actor) > enemy_speed + enemy_reach:
            continue   # enemy can't reach us this round anyway
        enemy_dpr = estimate_per_attack_damage(enemy)
        defensive_value += enemy_dpr * DELTA_HIT_FROM_ADVANTAGE

    total = (offensive_value + defensive_value) * p_evade * p_success
    return float(total)


# Probability that a readied trigger actually fires before the actor's
# next turn. Calibrated conservatively — Ready is a defensive interrupt
# that costs a full Action; if it doesn't fire, the actor loses a
# turn's worth of DPR. The trigger-fires probability decays linearly
# from 0.85 (very-close enemy clearly closing) to 0.4 (enemy at edge
# of plausibility). Empirical calibration via session sims is future
# work; v1 uses a flat 0.6 baseline that matches "the AI takes Ready
# in roughly the right situations" from manual smoke tests.
READY_TRIGGER_FIRES_PROBABILITY: float = 0.6


def offensive_ehp_ready(actor: Actor, action: dict,
                          state: CombatState) -> float:
    """eHP scoring for a Ready Action candidate (PR #86).

    Score = expected_damage_of_sub_action × READY_TRIGGER_FIRES_PROBABILITY

    The sub-action is the weapon attack the actor will fire when the
    trigger matches. We estimate its damage against the most-likely
    trigger-time target (the median enemy in HP, as a proxy — the
    actual target is determined at trigger time, not now).

    Returns 0.0 when:
      - No `_ready_sub_action` is stashed on the synthetic action
        (defensive — candidate generator always sets this)
      - No living enemies exist
      - The sub-action has no scorable damage path

    Note: candidate generator already gates emission on
    "no in-reach enemy for any weapon", so this score doesn't need to
    suppress itself when an immediate attack is available — those
    candidates simply aren't emitted.
    """
    sub_action = action.get("_ready_sub_action")
    if not sub_action:
        return 0.0
    enemies = [a for a in state.encounter.actors
                if a.side != actor.side and a.is_alive()]
    if not enemies:
        return 0.0
    # Pick the median-HP enemy as the proxy target. Lower-HP enemies
    # would be the "kill steal" target if Ready fires; median splits
    # the difference between expected-damage and likelihood-of-firing.
    enemies_sorted = sorted(enemies, key=lambda e: e.hp_current)
    proxy_target = enemies_sorted[len(enemies_sorted) // 2]
    base_score = offensive_ehp_single_attack(
        actor, proxy_target, sub_action, state)
    return base_score * READY_TRIGGER_FIRES_PROBABILITY


def offensive_ehp_search(actor: Actor, action: dict,
                            state: CombatState) -> float:
    """eHP scoring for the Search action (PR #59).

    Sums the per-hidden-enemy reveal value: for each enemy with a
    Hide-source `co_invisible` condition, compute the probability
    our Perception check beats their recorded stealth_total, then
    multiply by our own per-attack damage (proxy for "DPR unlocked
    by being able to target them next turn").

    Returns 0 when there are no Hide-source-hidden enemies OR the
    actor has no scorable weapon attacks (nothing to do once
    revealed).

    Note: Search consumes the actor's main Action this turn. The
    score doesn't subtract the lost current-turn DPR — that
    opportunity cost is captured implicitly by being compared
    against weapon_attack candidates on the same eHP scale.
    """
    from engine.core.skills import skill_modifier
    from engine.ai.defensive_ehp import estimate_per_attack_damage

    perception_mod = skill_modifier(actor, "perception")
    own_per_attack = estimate_per_attack_damage(actor)
    if own_per_attack <= 0:
        return 0.0

    total = 0.0
    for enemy in state.encounter.actors:
        if enemy.side == actor.side or not enemy.is_alive():
            continue
        for cond in (enemy.applied_conditions or []):
            if cond.get("condition_id") != "co_invisible":
                continue
            if cond.get("source_action_id") != "a_hide":
                continue
            stealth_total = int(cond.get("stealth_total", 0))
            # P(d20 + perception_mod >= stealth_total). Same shape as
            # _stealth_success_probability but DC = stealth_total.
            successes = 21 - (stealth_total - perception_mod)
            p_reveal = max(0.0, min(20.0, successes)) / 20.0
            total += own_per_attack * p_reveal
    return float(total)


EXPECTED_AURA_ROUNDS = 2.5     # matches EXPECTED_BUFF_ROUNDS for consistency


# ============================================================================
# Darkness vision-denial scoring (PR #61)
# ============================================================================
#
# Darkness (PR #60) is a persistent_aura that DOESN'T deal damage —
# it declares a magical_dark_zone that blocks vision into / out of
# the sphere. The Darkness-shape scoring has nothing in common with
# the damage-aura scoring (Spirit Guardians, Moonbeam, etc.), so we
# fork to a dedicated function.
#
# Value model (per RAW vision rules):
#   - In-sphere allies attacking out-sphere enemies → advantage
#     (Invisible attacker, target can't see them)
#   - Out-sphere enemies attacking in-sphere allies → disadvantage
#     (target Invisible, attacker can't see them)
#   - Within-sphere attacks (both inside or both outside) → no
#     net change (mutual unseen advantages cancel for inside-inside;
#     outside-outside sees normally)
#   - Enemies inside the sphere get the SAME benefits against PCs
#     outside — that's a cost. Net = ally benefit − enemy benefit.
#
# Truesight bypass: an enemy with truesight in range of an in-sphere
# ally pierces the darkness — that pair doesn't contribute to
# benefit. Same for ally-truesight piercing in-sphere enemies (cost).
#
# Duration multiplier: EXPECTED_AURA_ROUNDS (2.5, matching Spirit
# Guardians-shape). Concentration spell, typical encounter shape.
#
# Deferred refinements (post-PR #69):
#   - Per-target attack-frequency weighting (a multiattack monster's
#     debuff is worth more than a one-attack-per-turn caster's)
#   - "Caster forgot to put themselves in the sphere" detection
#     (could subtract concentration opportunity cost)

DARKNESS_RADIUS_SQUARES = 3       # 15-ft sphere = 3 squares radius
                                    # (RAW Darkness spell radius). Kept
                                    # for the wrapper below; HoH /
                                    # Cloudkill / future zone spells
                                    # pass their own radius.

# PR #78: zone types that drive vision-denial scoring. Each value
# determines which special senses pierce the zone:
#   - "magical_dark": blindsight OR truesight pierces (Darkness,
#     Hunger of Hadar — RAW magical darkness)
#   - "heavy_obscurement": blindsight ONLY pierces; truesight does
#     NOT (Cloudkill, future Fog Cloud / Stinking Cloud — RAW
#     non-magical heavy obscurement aka fog)
_VISION_DENIAL_ZONE_TYPES = frozenset({"magical_dark", "heavy_obscurement"})


def offensive_ehp_zone_vision_denial(actor: Actor, action: dict,
                                          state: CombatState,
                                          origin: tuple[int, int] | None,
                                          *, radius_ft: int,
                                          zone_type: str) -> float:
    """eHP value of dropping a vision-denial zone (PR #78,
    generalizes PR #61's offensive_ehp_darkness to handle both
    magical darkness AND heavy obscurement / fog).

    Classifies all living actors as in-sphere vs out-of-sphere via
    Chebyshev distance from origin (matches the engine's grid
    convention). Computes:
      benefit = sum over (in-sphere ally × out-sphere enemy who can
                reach them, no piercing sense) of enemy_DPR ×
                DELTA_HIT_FROM_ADVANTAGE
              + sum over in-sphere allies of ally_DPR ×
                DELTA_HIT_FROM_ADVANTAGE when reachable out-sphere
                enemies exist (ally swings with advantage)
      cost   = mirror with sides swapped (in-sphere enemies + out-
                sphere allies)
      net    = (benefit - cost) × EXPECTED_AURA_ROUNDS

    Returns max(0.0, net). Negative values clamp to 0 so the AI
    never PREFERS dropping a vision-denial zone that hurts the
    party more than the enemy.

    `origin` defaults to actor.position when None (caster drops the
    zone on themselves, common Darkness pattern).

    Sense-bypass rules by `zone_type`:
      - "magical_dark": blindsight OR truesight pierces. RAW:
        truesight sees through magical darkness; blindsight bypasses
        every vision-blocking effect within range.
      - "heavy_obscurement": ONLY blindsight pierces. RAW: fog /
        cloud / smoke is physical, not magical — truesight doesn't
        see through it, but blindsight (which perceives without
        sight) still works.
    """
    from engine.ai.defensive_ehp import estimate_per_attack_damage
    from engine.core.basic_actions import _max_attack_reach
    from engine.core.geometry import distance_ft

    if origin is None:
        origin = tuple(actor.position)
    ox, oy = int(origin[0]), int(origin[1])
    # Convert radius_ft → grid squares (5 ft per square, integer
    # truncation matches the existing DARKNESS_RADIUS_SQUARES
    # convention). For HoH/Cloudkill (20 ft) → 4 squares; Darkness
    # (15 ft) → 3 squares.
    radius_squares = max(0, int(radius_ft) // 5)

    def _in_sphere(actor_obj: Actor) -> bool:
        ax, ay = actor_obj.position
        return max(abs(ax - ox), abs(ay - oy)) <= radius_squares

    in_allies: list[Actor] = []
    out_allies: list[Actor] = []
    in_enemies: list[Actor] = []
    out_enemies: list[Actor] = []
    for a in state.encounter.actors:
        if not a.is_alive():
            continue
        in_zone = _in_sphere(a)
        if a.side == actor.side:
            (in_allies if in_zone else out_allies).append(a)
        else:
            (in_enemies if in_zone else out_enemies).append(a)

    # Sense-bypass: which special senses pierce this zone type?
    truesight_pierces = (zone_type == "magical_dark")

    def _sense_pierces(observer: Actor, target: Actor) -> bool:
        d = distance_ft(observer, target)
        if truesight_pierces:
            ts_range = int(getattr(observer, "truesight_range_ft", 0) or 0)
            if ts_range > 0 and d <= ts_range:
                return True
        bs_range = int(getattr(observer, "blindsight_range_ft", 0) or 0)
        if bs_range > 0 and d <= bs_range:
            return True
        return False

    def _reach_threat(attacker: Actor, target: Actor) -> bool:
        """Can attacker reach target this round (speed + max reach)?"""
        reach = _max_attack_reach(attacker)
        if reach <= 0:
            return False
        speed = int((attacker.speed or {}).get("walk", 30))
        return distance_ft(attacker, target) <= speed + reach

    # Benefit: in-sphere allies vs out-sphere enemies
    benefit = 0.0
    for ally in in_allies:
        # Defensive: each enemy who'd attack this ally suffers disadvantage
        for enemy in out_enemies:
            if _sense_pierces(enemy, ally):
                continue
            if not _reach_threat(enemy, ally):
                continue
            enemy_dpr = estimate_per_attack_damage(enemy)
            benefit += enemy_dpr * DELTA_HIT_FROM_ADVANTAGE
        # Offensive: one boosted attack per round if any out-sphere
        # enemy exists (ally swings with advantage)
        if out_enemies:
            ally_dpr = estimate_per_attack_damage(ally)
            benefit += ally_dpr * DELTA_HIT_FROM_ADVANTAGE

    # Cost: in-sphere enemies vs out-sphere allies (mirror)
    cost = 0.0
    for enemy in in_enemies:
        for ally in out_allies:
            if _sense_pierces(ally, enemy):
                continue
            if not _reach_threat(ally, enemy):
                continue
            ally_dpr = estimate_per_attack_damage(ally)
            cost += ally_dpr * DELTA_HIT_FROM_ADVANTAGE
        if out_allies:
            enemy_dpr = estimate_per_attack_damage(enemy)
            cost += enemy_dpr * DELTA_HIT_FROM_ADVANTAGE

    net = (benefit - cost) * EXPECTED_AURA_ROUNDS
    return max(0.0, net)


def offensive_ehp_darkness(actor: Actor, action: dict,
                              state: CombatState,
                              origin: tuple[int, int] | None = None
                              ) -> float:
    """Backward-compatible wrapper (PR #61 → PR #78 generalization).
    Routes to `offensive_ehp_zone_vision_denial` with Darkness-spell
    defaults: radius_ft=15, zone_type='magical_dark'. Existing
    callers and tests that target the Darkness spell don't need to
    change; new hybrid auras (HoH / Cloudkill) should call the
    generalized function with their own radius + zone_type.
    """
    return offensive_ehp_zone_vision_denial(
        actor, action, state, origin,
        radius_ft=15, zone_type="magical_dark",
    )


def offensive_ehp_persistent_aura(actor: Actor, action: dict,
                                       state: CombatState,
                                       origin: tuple[int, int] | None = None
                                       ) -> float:
    """eHP scoring for persistent_aura spells (PR #43 + PR #44).

    Sums per-turn expected damage across enemies currently in the
    aura's area, multiplied by `EXPECTED_AURA_ROUNDS` to approximate
    full-duration value.

    Shapes:
      - sphere: `radius_ft` from origin (default behavior)
      - cube: `size_ft` cube centered on origin

    Anchors:
      - caster (default): origin = actor.position (live)
      - point: origin from `origin` argument (candidate's
        `origin_point`); falls back to actor.position if not provided

    Save vs no-save:
      - With `ability`: per-turn = p_fail × full + p_success × half
      - Without `ability` (Cloud of Daggers-shape): per-turn = full
        (always applies)

    Per-turn damage capped at each enemy's remaining HP. Returns 0.0
    if no enemies in area or no damage payload.
    """
    from engine.ai.defensive_ehp import save_fail_probability
    from engine.core.geometry import distance_ft, actors_in_cube

    # Extract aura params from the first persistent_aura step
    aura_params = None
    for step in (action.get("pipeline") or []):
        if step.get("primitive") == "persistent_aura":
            aura_params = step.get("params") or {}
            break
    if aura_params is None:
        return 0.0

    # PR #78: hybrid aura scoring. Auras may contribute via BOTH a
    # damage payload AND a vision-denial zone (HoH = cold damage +
    # magical_dark; Cloudkill = poison damage + heavy_obscurement).
    # Compute both components below and SUM them at the end. PR #61
    # added Darkness-only routing here; PR #78 lifts that fork so
    # zone-only spells (Darkness — no damage payload) still get
    # zone value (damage component = 0), and hybrids get both.

    shape = aura_params.get("shape", "sphere")
    anchor = aura_params.get("anchor", "caster")
    ability = aura_params.get("ability")
    if ability == "none":
        ability = None
    dc = int(aura_params.get("dc", 0))

    # Determine the area's origin for "in-area enemies" check
    if anchor == "point" and origin is not None:
        area_origin = tuple(origin)
    else:
        area_origin = tuple(actor.position)

    # Sum the on_fail / on_success damage steps
    def _sum_damage(steps: list[dict]) -> float:
        total = 0.0
        for s in steps or []:
            if s.get("primitive") != "damage":
                continue
            p = s.get("params") or {}
            dice = p.get("dice")
            if dice:
                mult = float(p.get("multiplier", 1.0))
                total += dice_mean(dice) * mult
        return total

    full_dmg = _sum_damage(aura_params.get("on_fail") or [])
    half_dmg = _sum_damage(aura_params.get("on_success") or [])

    # PR #78: damage-component computation. Returns 0 when the aura
    # has no damage payload (Darkness) OR no enemies in area OR a
    # malformed shape. The zone-component computation below ALWAYS
    # runs regardless — that's the load-bearing fix for hybrid
    # damage+zone auras (HoH / Cloudkill) and zone-only auras
    # (Darkness).
    damage_value = 0.0
    if full_dmg > 0 or half_dmg > 0:
        living_enemies = [e for e in state.encounter.actors
                           if e.side != actor.side and e.is_alive()]
        enemies_in_aura: list[Actor] = []
        if shape == "cube":
            size_ft = int(aura_params.get("size_ft", 0))
            if size_ft > 0:
                enemies_in_aura = actors_in_cube(area_origin, size_ft,
                                                    living_enemies)
        else:
            radius = int(aura_params.get("radius_ft", 0))
            if radius > 0:
                enemies_in_aura = [
                    e for e in living_enemies
                    if distance_ft(e.position, area_origin) <= radius]

        total_per_turn = 0.0
        for e in enemies_in_aura:
            if ability is None:
                # No-save: full damage every turn (Cloud of Daggers shape)
                per_turn = full_dmg
            else:
                p_fail = save_fail_probability(e, ability, dc, state)
                per_turn = p_fail * full_dmg + (1.0 - p_fail) * half_dmg
            # Cap per-turn at enemy remaining HP
            per_turn = min(per_turn, float(max(0, e.hp_current)))
            total_per_turn += per_turn
        damage_value = total_per_turn * EXPECTED_AURA_ROUNDS

    # PR #78: hybrid zone-component score. If the aura also creates
    # a vision-denial zone (magical_dark or heavy_obscurement),
    # add the zone's eHP value to the damage value. Zero contribution
    # when creates_zone is absent or set to an unsupported type.
    # The zone scorer reads radius from the aura params directly so
    # HoH/Cloudkill (20 ft) and Darkness (15 ft) all work uniformly.
    zone_value = 0.0
    creates_zone = aura_params.get("creates_zone")
    if creates_zone in _VISION_DENIAL_ZONE_TYPES:
        aura_radius_ft = int(aura_params.get("radius_ft", 0))
        if aura_radius_ft > 0:
            zone_value = offensive_ehp_zone_vision_denial(
                actor, action, state, area_origin,
                radius_ft=aura_radius_ft,
                zone_type=creates_zone,
            )

    return damage_value + zone_value


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
    if kind == "persistent_aura" or action.get("type") == "persistent_aura":
        origin = candidate.get("origin_point")
        return offensive_ehp_persistent_aura(
            actor, action, state,
            origin=tuple(origin) if origin is not None else None,
        )
    if kind == "disengage" or action.get("type") == "disengage":
        # Disengage's real eHP depends on what move comes after (avoid
        # an OA from a specific reactor). v1 returns a small constant
        # (~0.5 eHP) so the AI considers it as a tie-breaker / last-
        # resort option but rarely beats Dodge or real attacks. Real
        # picking should happen via RP-constraint forcing or movement-
        # aware AI (deferred to a future PR).
        return 0.5
    # PR #59: Hide / Search real eHP scoring (closes PRs #48 + #55
    # residues where these were fixture-only / gated-emission).
    if kind == "hide" or action.get("type") == "hide":
        return offensive_ehp_hide(actor, action, state)
    if kind == "search" or action.get("type") == "search":
        return offensive_ehp_search(actor, action, state)
    # PR #86: Ready Action — score the held sub-action against the
    # best plausible trigger-time target, discounted for trigger
    # uncertainty. Only emitted by the candidate generator when no
    # in-reach enemy exists for any weapon (Ready is dominated when
    # an immediate attack is available).
    if kind == "ready" or action.get("type") == "ready":
        return offensive_ehp_ready(actor, action, state)

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
