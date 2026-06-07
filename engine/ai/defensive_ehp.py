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

# Danger floor: healing eHP is scaled by how much DANGER the target is in this
# round (see danger_factor). A target NO enemy can threaten this round still
# retains this fraction of the nominal heal value — anticipatory topping-off is
# worth something, but a heal on a safe ally should lose to real offense /
# control. A target whose incoming damage could drop it this round scales to
# full (1.0). This is the fix for the Cleric heal-spam on un-threatened allies
# (the day-attrition drain): HP banked on someone who won't be hit isn't
# realized eHP.
HEAL_DANGER_FLOOR = 0.25


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


def incoming_danger_to(target: Actor, state: CombatState) -> float:
    """Sum of estimated DPR from enemies who can THREATEN `target` this round.

    An enemy threatens the target if the target sits within the enemy's
    threat radius (walk speed + longest attack reach/range — `_max_attack_reach`
    already folds in ranged `range_ft`, so archers/casters threaten at distance).
    Enemies that can't reach this round contribute 0 (they're 2+ rounds away).

    Pure observable-proxy DPR (estimate_dpr), same discipline as the rest of the
    module. Used by `danger_factor` to scale heal value by real threat."""
    if state.encounter is None:
        return 0.0
    from engine.core.geometry import distance_ft
    from engine.core.basic_actions import _max_attack_reach
    total = 0.0
    for enemy in state.encounter.actors:
        if enemy.side == target.side or not enemy.is_alive():
            continue
        reach = _max_attack_reach(enemy)
        if reach <= 0:
            continue
        speed = int((enemy.speed or {}).get("walk", 30) or 30)
        if distance_ft(enemy, target) <= speed + reach:
            total += estimate_dpr(enemy)
    return total


def danger_factor(target: Actor, state: CombatState) -> float:
    """Scale healing value by how much DANGER `target` is in this round.

    Returns a factor in [HEAL_DANGER_FLOOR, 1.0]:
      - 1.0 when the incoming DPR this round is ≥ the target's current HP
        (it could be dropped this round — heal is fully realized).
      - HEAL_DANGER_FLOOR when no enemy can threaten the target this round
        (heal is banked, not realized — anticipatory value only).
      - Linear in the incoming-DPR / current-HP ratio between.

    A DYING ally is always at maximum danger (1.0): it's on a 3-strike clock to
    PERMANENT death regardless of enemy positions, so reviving is never
    discounted by board state."""
    if getattr(target, "is_dying", False) and not target.is_dead:
        return 1.0
    incoming = incoming_danger_to(target, state)
    if incoming <= 0:
        return HEAL_DANGER_FLOOR
    current_hp = max(1.0, float(target.hp_current))
    ratio = min(1.0, incoming / current_hp)
    return HEAL_DANGER_FLOOR + (1.0 - HEAL_DANGER_FLOOR) * ratio


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
        # PR #118: flat `modifier` key (pre-resolved ability mod baked
        # in at build time — Cure Wounds / Healing Word). Mirror the
        # _heal primitive so scoring matches executed healing.
        total += float(params.get("modifier", 0))
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

    Returns 0.0 if the target is at full HP, truly dead, or not an ally.

    A DYING (downed, 0-HP, unconscious) ally is a valid REVIVAL target even
    though is_alive() is False — any healing brings it back into the fight
    (Stage 2). It scores at maximum desperation (hp_frac 0), so the AI weights
    picking a downed ally up heavily; the missing-HP cap is the full HP max.
    """
    if target_ally is None:
        return 0.0
    _dying = getattr(target_ally, "is_dying", False) and not target_ally.is_dead
    if not _dying:
        if not target_ally.is_alive():
            return 0.0   # truly dead / fled — can't heal
        if target_ally.hp_current >= target_ally.hp_max:
            return 0.0   # full HP — no value
    missing = float(target_ally.hp_max - target_ally.hp_current)
    if missing <= 0:
        return 0.0

    hp_frac = target_ally.hp_current / target_ally.hp_max if target_ally.hp_max else 0.0

    # Revival priority (Stage 3): reviving a DYING ally is worth far more than
    # the HP restored — it returns a whole COMBATANT who is otherwise
    # contributing nothing AND is on a 3-strike clock to PERMANENT death. Add
    # one round of the revived ally's estimated DPR as a "back in the fight"
    # bonus on top of the healing value, so the AI prefers reviving (and
    # prefers reviving the bigger damage dealer) over chip damage or topping
    # off a healthy ally. Bounded (one round) so it can't dominate unboundedly.
    revival_bonus = estimate_dpr(target_ally) if _dying else 0.0

    # Danger scaling: HP restored on an ally NO enemy can threaten this round
    # isn't realized eHP (the Cleric heal-spam bug). Scale the healing
    # component by how much danger the target is actually in. A dying ally is
    # max danger (1.0) so revival is never discounted; the revival_bonus is
    # added AFTER scaling for the same reason.
    danger = danger_factor(target_ally, state)

    # PR #83: Lay on Hands special path. The heal amount isn't
    # baked into the action (it's `min(missing, pool)` at runtime),
    # so `expected_healing` returns 0. Compute the actual amount
    # from the actor's pool + target's missing HP, then apply the
    # same desperation multiplier + missing cap.
    for step in action.get("pipeline") or []:
        if step.get("primitive") == "lay_on_hands":
            pool = int(actor.resources.get(
                "lay_on_hands_pool_remaining", 0))
            if pool <= 0:
                return 0.0
            amount = min(missing, float(pool))
            return (amount * desperation_multiplier(hp_frac) * danger
                    + revival_bonus)

    raw = expected_healing(action, actor) * desperation_multiplier(hp_frac)
    return min(raw, missing) * danger + revival_bonus


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


def _expected_hits_per_round(creature: Actor) -> float:
    """Expected NUMBER of landed weapon hits per round (not damage).

    Used by the self weapon-damage buff scorer (Divine Favor): a flat
    +N-per-hit rider is worth N for each hit the caster lands, so the
    value scales with hit count, not damage magnitude. Mirrors the
    AC 15 hit-prob proxy + multiattack-count logic used by
    `estimate_dpr` so the two paths stay calibrated.

    Picks the p_hit of the highest-damage weapon attack (the one the
    caster will actually swing) and multiplies by the multiattack
    count. Returns 0.0 for creatures with no weapon attacks.
    """
    actions = (creature.template or {}).get("actions") or []
    if not actions:
        return 0.0
    best_value = 0.0
    p_hit_of_best = 0.0
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
        value = _approximate_damage_on_hit(action) * p_hit
        if value > best_value:
            best_value = value
            p_hit_of_best = p_hit
    if p_hit_of_best <= 0:
        return 0.0
    multi_count = 1
    for action in actions:
        if action.get("type") == "multiattack":
            multi_count = max(multi_count, int(action.get("count", 1)))
    return p_hit_of_best * multi_count


def _extract_self_weapon_damage_bonus(action: dict) -> int:
    """Flat +N weapon-damage bonus a buff grants its SELF target
    (Divine Favor shape). Returns 0 if no self-targeting
    weapon_damage_bonus step is present.

    Only counts `target: self` steps so target-specific enemy riders
    (Hex / Hunter's Mark, which mark an enemy) never route here."""
    total = 0
    for step in (action.get("pipeline") or []):
        if step.get("primitive") != "weapon_damage_bonus":
            continue
        params = step.get("params") or {}
        if params.get("target") != "self":
            continue
        total += int(params.get("value", 0))
    return total


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

    # PR #74: Dash (Cunning Action) is a movement-buff; the standard
    # buff-shape scorer would return 0. Score it based on whether
    # closing distance has value (i.e., there's a target out of reach
    # the actor could attack next turn if they move closer this turn).
    if _pipeline_has_primitive(action, "dash"):
        return _score_dash(actor, state)

    # PR #80: Steady Aim (Rogue L3 BA) — advantage on next attack.
    # Standard buff scorer wouldn't pick it up (no
    # attack/save_modifier in the pipeline; uses a custom primitive).
    # Score = DELTA_HIT_FROM_ADVANTAGE × actor's expected per-attack
    # damage. Rogues with Sneak Attack benefit additionally because
    # advantage guarantees SA fires (if no ally adjacent), but
    # v1 keeps the formula simple.
    if _pipeline_has_primitive(action, "steady_aim"):
        return _score_steady_aim(actor, state)

    # PR #96: Armor of Agathys — self temp HP + reflective cold
    # damage on melee attackers. Dispatched BEFORE the generic temp-HP
    # branch since AoA's pipeline includes BOTH temp_hp_grant AND
    # armor_of_agathys_arm; the latter is the discriminating shape.
    if _pipeline_has_primitive(action, "armor_of_agathys_arm"):
        return _score_armor_of_agathys(actor, target_ally, action, state)

    # PR #97: Aid — raises max HP + current HP. The eHP value is the
    # full grant amount (it's a direct HP buffer that persists the
    # whole encounter and beyond). Scored per-target; the
    # multi-target sum happens in score_candidate.
    if _pipeline_has_primitive(action, "hp_max_grant"):
        return _score_hp_max_grant(actor, target_ally, action, state)

    # PR #94: Heroism — RECURRING per-turn temp HP grant. The
    # recurring_temp_hp primitive is the discriminator (one-shot
    # temp_hp_grant spells like False Life fall through to the
    # one-shot scorer below).
    if _pipeline_has_primitive(action, "recurring_temp_hp"):
        return _score_heroism(actor, target_ally, action, state)

    # PR #111: arming-smite family — self-buffs that arm a one-shot
    # rider firing on the caster's NEXT weapon hit. Their pipelines use
    # bespoke arm primitives (no attack/save_modifier), so the generic
    # extract_buff_effect path returned 0 and the AI never cast them.
    # Scored against the caster's next-hit probability × the rider's
    # payoff (Searing = bonus fire + ignite DoT; Ensnaring = restrain
    # control + pierce DoT).
    if _pipeline_has_primitive(action, "searing_smite_arm"):
        return _score_searing_smite(actor, state)
    if _pipeline_has_primitive(action, "ensnaring_strike_arm"):
        return _score_ensnaring_strike(actor, state)

    # PR #109: self weapon-damage buff (Divine Favor shape) — a flat
    # +N on the caster's OWN weapon hits. extract_buff_effect doesn't
    # recognize weapon_damage_bonus, so without this branch the buff
    # scored 0 and the AI never cast it. This is the "buff-before-
    # burst" insight: the value is the extra damage the caster lands
    # across its own attacks over the buff's lifetime. Dispatched on a
    # self-targeting weapon_damage_bonus step.
    if _extract_self_weapon_damage_bonus(action) > 0:
        return _score_self_weapon_damage_buff(actor, action, state)

    # PR #99: one-shot temp HP grant (False Life-shape). Flat-amount
    # temp HP, no recurring tick. Value = amount × absorption
    # fraction (the fraction of the buffer that lands before it would
    # otherwise expire). Routed here only when there's no
    # recurring_temp_hp step.
    if _pipeline_has_primitive(action, "temp_hp_grant"):
        return _score_temp_hp_oneshot(actor, target_ally, action, state)

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


def _score_self_weapon_damage_buff(actor: Actor, action: dict,
                                      state: CombatState) -> float:
    """eHP value of a self weapon-damage buff (Divine Favor, PR #109).

      eHP = bonus × expected_hits_per_round × buff_rounds

    The "buff-before-burst" payoff: a flat +N on every weapon hit is
    worth N for each hit the caster lands, summed over its own attacks
    across the buff's lifetime. A multiattacking caster (Extra Attack)
    therefore values it more — more hits to ride the bonus. Because
    Divine Favor is a Bonus Action, casting it doesn't cost the Attack
    action, so the burst lands the same turn; the runner already
    sequences BA-buff + Action-attack, so the scorer just needs to
    credit the extra damage.

    Returns 0.0 when:
      - there's no self weapon_damage_bonus step (guarded by caller)
      - the caster has no weapon attacks (no hits to buff)
      - there are no living enemies (buffing in a vacuum is worthless)

    `buff_rounds` defaults to EXPECTED_BUFF_ROUNDS; an action may
    override via `offensive_buff_rounds`.
    """
    bonus = _extract_self_weapon_damage_bonus(action)
    if bonus <= 0:
        return 0.0
    enemies = [a for a in state.encounter.actors
                 if a.side != actor.side and a.is_alive()]
    if not enemies:
        return 0.0
    hits_per_round = _expected_hits_per_round(actor)
    if hits_per_round <= 0:
        return 0.0
    buff_rounds = float(action.get("offensive_buff_rounds",
                                       EXPECTED_BUFF_ROUNDS))
    return float(bonus) * hits_per_round * buff_rounds


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


def _score_dash(actor: Actor, state: CombatState) -> float:
    """Estimate eHP value of taking the Dash action (PR #74).

    Dash has value when the actor needs to close distance to reach
    an enemy. Value scales with:
      - How far the nearest enemy is beyond the actor's reach (more
        gap = more Dash value)
      - Actor's typical DPR (closing one round earlier means one
        more swing landed)

    Returns a small positive value (~2-5 eHP) when there's an
    out-of-reach enemy; near-zero when all enemies are already in
    reach (Dash is wasted in that case). The bonus-action
    `tactical_bonus` gate will still roll for whether to fire — at
    low score it usually won't, which is correct (don't burn the BA
    on a wasted Dash).
    """
    from engine.core.geometry import distance_ft
    enemies = [a for a in state.encounter.actors
                if a.side != actor.side and a.is_alive()]
    if not enemies:
        return 0.0
    # Use the actor's walk speed as the rough "reach into the future"
    # value — Dash doubles that, so closing speed_ft worth of gap
    # is the value.
    speed = int((actor.speed or {}).get("walk", 30))
    # Find nearest enemy distance
    nearest_ft = min(distance_ft(actor.position, e.position)
                       for e in enemies)
    # Reach of the actor's most-reachy attack (default 5 melee).
    # Crude: assume 5 ft melee reach if no actions; future PR could
    # consult action reach properly.
    reach_ft = 5
    for a in (actor.template.get("actions") or []):
        if a.get("type") in ("weapon_attack", "multiattack"):
            for step in (a.get("pipeline") or []):
                if step.get("primitive") == "attack_roll":
                    p = step.get("params") or {}
                    candidate_reach = int(p.get("range_ft",
                                                    p.get("reach_ft", 5)))
                    reach_ft = max(reach_ft, candidate_reach)
    gap_ft = max(0, nearest_ft - reach_ft)
    if gap_ft <= 0:
        # All enemies in reach — Dash is wasted
        return 0.0
    # Value: if the gap is bigger than one move (speed_ft), Dash
    # may close it in one turn (vs. two). Value scales with how
    # much closer we get. Cap at ~5 eHP.
    closed_ft = min(gap_ft, speed)  # Dash gives extra `speed` ft of movement
    if speed <= 0:
        return 0.0
    return min(5.0, 5.0 * (closed_ft / speed))


# Probability proxy for a Rogue's next attack hitting WITH advantage,
# used by the Steady-Aim SA-unlock uplift (PR #87). Calibration:
# typical L3+ Rogue is +7 to hit vs default AC 15 → p_hit = 0.65 normally,
# ~0.875 with advantage (0.65 + DELTA_HIT_FROM_ADVANTAGE × ~1). Round to
# a clean 0.7 — slightly conservative so the scorer doesn't overweight
# the SA-unlock arm in marginal cases. A per-target hit-chance calc is
# possible but adds complexity for diminishing return; the constant
# proxy is calibrated to the framework's other "expected per-swing"
# estimators (Help-shape, Vex mastery).
STEADY_AIM_SA_UNLOCK_HIT_PROXY: float = 0.7


# Empirical fraction of granted temp HP that gets absorbed each
# round it persists (PR #94). Calibrated for typical melee-ally
# scenarios where the buffed target is being attacked roughly
# every round. Back-line targets (Wizards out of melee reach) would
# absorb less; the constant is a mid-case proxy. Future calibration
# could vary by buffed-target archetype, but a single constant
# matches the framework's approach for other per-round buff values
# (Bless's flat-+2 averages over hits / misses similarly).
TEMP_HP_ABSORPTION_FRACTION: float = 0.6


# Expected number of melee hits the Agathys bearer absorbs over the
# spell's effective duration. The temp HP usually depletes in 1-2
# enemy melee hits at low levels (5 temp HP at base, typical L1-3
# attacks deal ~4-8 damage). Per RAW, each hit while temp HP > 0
# fires the cold reflection — so the expected reflections roughly
# matches "hits until temp HP depletes." For the v1 calibration we
# use 1.5 as a midpoint between "absorbed in one hit" (5+ damage
# attack) and "absorbed in two hits" (3-damage attacks).
ARMOR_OF_AGATHYS_EXPECTED_REFLECTIONS: float = 1.5


def _score_hp_max_grant(actor: Actor, target_ally: Actor,
                            action: dict,
                            state: CombatState) -> float:
    """Estimate eHP value of an Aid-style max-HP grant on one ally
    (PR #97).

    Value = grant_amount (the max+current HP raise is wholesale eHP —
    it directly increases the ally's effective hit points and persists
    the whole encounter; unlike a damage rider or advantage buff, none
    of it is probabilistic). The current-HP raise also un-bloodies /
    pulls a downed-adjacent ally further from 0, but v1 keeps the
    estimate at the flat grant amount for simplicity.

    Per-target function — score_candidate sums this across the
    multi-target group. Returns 0 if the target already has an Aid
    bonus active (dedup; the hp_max_grant primitive also no-ops on
    re-application, so a re-cast would be wasted).
    """
    if target_ally is None or not target_ally.is_alive():
        return 0.0
    if target_ally.side != actor.side:
        return 0.0
    named_effect = action.get("named_effect")
    if named_effect:
        for entry in target_ally.hp_max_bonuses:
            if entry.get("named_effect") == named_effect:
                return 0.0   # already has Aid; no value in re-applying
    grant = 0
    for step in (action.get("pipeline") or []):
        if step.get("primitive") == "hp_max_grant":
            grant = int((step.get("params") or {}).get("amount", 0))
            break
    return float(grant)


def _score_armor_of_agathys(actor: Actor, target_ally: Actor,
                                 action: dict,
                                 state: CombatState) -> float:
    """Estimate eHP value of casting Armor of Agathys on self (PR #96).

    Two components both summed:
      - **Defensive (temp HP buffer):** `temp_hp_amount × 1.0` — temp
        HP directly absorbs an equal amount of incoming damage,
        wholesale-eHP. Per RAW it persists past combat (until short
        rest) so 100% of the grant counts in worst case.
      - **Offensive (reflective cold damage):**
        `cold_damage_per_reflection × expected_reflections` — each
        reflected cold hit costs the attacker that many HP, which
        the framework treats as DPR equivalent for the bearer.

    AoA is self-targeted; this function is called with
    `target_ally == actor`. Returns 0 if the AoA marker is already
    active (the arm primitive replaces but the scorer dedups to
    avoid the AI re-casting on the same turn).
    """
    if target_ally is None or not target_ally.is_alive():
        return 0.0
    if target_ally.id != actor.id:
        # AoA RAW is self-only. Non-self target candidates shouldn't
        # be emitted, but if one slips through, score 0.
        return 0.0
    # Dedup: don't re-cast if marker is already active
    for mod in target_ally.active_modifiers:
        if mod.get("primitive") == "armor_of_agathys_active":
            return 0.0
    # Extract base values from the pipeline
    base_temp_hp = 5
    base_cold = 5
    for step in (action.get("pipeline") or []):
        params = step.get("params") or {}
        if step.get("primitive") == "temp_hp_grant":
            base_temp_hp = int(params.get("amount", base_temp_hp))
        elif step.get("primitive") == "armor_of_agathys_arm":
            base_cold = int(params.get("cold_damage", base_cold))
    # Defensive component — temp HP directly absorbs damage
    defensive_value = float(base_temp_hp)
    # Offensive component — cold reflections against expected
    # melee attackers (only fires if AoA bearer is actually in
    # melee range of enemies, but for self-cast scoring we assume
    # they're in the fight)
    offensive_value = base_cold * ARMOR_OF_AGATHYS_EXPECTED_REFLECTIONS
    return defensive_value + offensive_value


def _score_temp_hp_oneshot(actor: Actor, target_ally: Actor,
                              action: dict,
                              state: CombatState) -> float:
    """Estimate eHP value of a one-shot temp HP grant (PR #99,
    False Life-shape).

    Value = grant_amount × TEMP_HP_ABSORPTION_FRACTION. Temp HP is a
    direct damage buffer; the absorption fraction discounts for the
    portion that may go unused if the buff expires before being
    spent. (For a self-cast pre-fight buff the whole amount usually
    lands, but the same conservative fraction used for Heroism keeps
    the two temp-HP scorers calibrated to one shared assumption.)

    Reads the flat `amount` from the temp_hp_grant step. Returns 0
    when the target already has a matching named_effect (dedup; the
    primitive also no-ops via max-semantics, so a re-cast that
    wouldn't raise temp HP is wasted) — but only when the existing
    temp HP is >= this grant (a bigger pending grant is still worth
    casting). v1 keeps it simple: dedup purely on named_effect
    presence among active modifiers is not tracked for temp HP (it's
    a scalar, not a modifier list), so we skip the dedup branch and
    rely on the AI not re-casting a self-buff it just cast.
    """
    if target_ally is None or not target_ally.is_alive():
        return 0.0
    if target_ally.side != actor.side:
        return 0.0
    grant = 0
    for step in (action.get("pipeline") or []):
        if step.get("primitive") == "temp_hp_grant":
            grant = int((step.get("params") or {}).get("amount", 0))
            break
    if grant <= 0:
        return 0.0
    # Don't re-cast if the target already has temp HP >= this grant
    # (max-semantics means the grant would do nothing).
    if target_ally.temp_hp >= grant:
        return 0.0
    return grant * TEMP_HP_ABSORPTION_FRACTION


def _score_heroism(actor: Actor, target_ally: Actor, action: dict,
                     state: CombatState) -> float:
    """Estimate eHP value of casting Heroism (PR #94).

    Heroism grants `caster_spellcasting_modifier` temp HP at the
    start of each of the target's turns for the spell's duration.
    Per-tick value = grant × TEMP_HP_ABSORPTION_FRACTION (fraction
    of temp HP that actually absorbs damage before the next tick
    refills it via max-semantics).

    Total value = per_tick × EXPECTED_BUFF_ROUNDS.

    The grant amount is computed from the caster's CHA modifier
    (default spellcasting ability for Paladin / Bard / Sorcerer /
    Warlock — the four classes that learn Heroism). Returns 0 when
    the caster has a negative or zero modifier (rare; PCs typically
    have +2 or better in their casting stat by L2).
    """
    if target_ally is None or not target_ally.is_alive():
        return 0.0
    if target_ally.side != actor.side:
        return 0.0
    # Don't re-cast on a target who already has heroism active (PR
    # #36 named_effect dedup catches identical re-casts, but check
    # explicitly here too).
    from engine.ai.named_effects import buff_already_active
    if buff_already_active(target_ally, action, actor):
        return 0.0
    # Estimate caster's spellcasting modifier (default CHA for the
    # four Heroism-learning classes; Bards/Paladins/Sorcerers/Warlocks
    # all use CHA). Wizard-style INT casters could learn Heroism via
    # multiclass eventually; v1 reads CHA.
    cha_score = (actor.abilities.get("cha") or {}).get("score", 10)
    cha_mod = (cha_score - 10) // 2
    if cha_mod <= 0:
        return 0.0
    per_tick_value = cha_mod * TEMP_HP_ABSORPTION_FRACTION
    return per_tick_value * EXPECTED_BUFF_ROUNDS


def _score_steady_aim(actor: Actor, state: CombatState) -> float:
    """Estimate eHP value of taking Steady Aim (PR #80, scoring uplift
    in PR #87).

    Two components:

      **Base component** — Steady Aim grants advantage on next attack.
      Value = expected per-attack damage × DELTA_HIT_FROM_ADVANTAGE
      (matches the standard advantage-value formula used in Help / Vex
      mastery scoring).

      **SA-unlock component (PR #87)** — for Rogues, advantage from
      Steady Aim satisfies the Sneak Attack trigger by itself. When the
      Rogue would NOT otherwise have SA (no adjacent ally; SA not yet
      used this turn), Steady Aim unlocks the SA dice and the
      `expected_sa_damage × P(hit_with_advantage)` is pure uplift on
      top of the base advantage value. When SA would already fire
      (an ally is adjacent to the best target), Steady Aim still
      raises the hit chance on the SA dice — smaller uplift
      (sa_damage × DELTA_HIT_FROM_ADVANTAGE).

    Returns 0 when:
      - No living enemies (no target to swing at)
      - Actor's per-attack damage estimate is 0 (no weapons)

    The SA-unlock uplift is the difference between "SA dice are about
    to roll" vs "they aren't" — a much larger swing than the base
    advantage value. For a L3 Rogue (2d6 SA = 7 avg) with no adjacent
    ally, taking Steady Aim is worth roughly 7 × 0.7 ≈ 4.9 eHP of SA
    uplift on top of ~1-2 eHP of base advantage value, comfortably
    beating Cunning Action Dash/Hide/Disengage (0.5-5 eHP) and the
    BA-slot threshold for tactical activation.

    Cunning Strike (PR #81) interaction: CS trades SA dice for an
    effect at execution time. v1 scorer doesn't try to anticipate
    whether the Rogue will spend dice on CS — the advantage delta
    applies regardless of how those dice are spent, so it's a wash.
    """
    from engine.ai.ehp_scoring import DELTA_HIT_FROM_ADVANTAGE
    from engine.core.sneak_attack import (
        sneak_attack_dice_at_level, _rogue_level,
        _has_ally_adjacent_to_target,
    )
    enemies = [a for a in state.encounter.actors
                if a.side != actor.side and a.is_alive()]
    if not enemies:
        return 0.0
    per_attack = estimate_per_attack_damage(actor)
    if per_attack <= 0:
        return 0.0

    base_value = per_attack * DELTA_HIT_FROM_ADVANTAGE

    # Non-Rogues only get the base advantage value (no SA dice to unlock).
    rogue_level = _rogue_level(actor)
    if rogue_level <= 0:
        return base_value

    # SA can only fire once per turn. If it already fired this turn,
    # Steady Aim provides no SA-unlock value (the rest of this turn's
    # attacks can't SA again).
    if getattr(actor, "_sneak_attack_used_this_turn", False):
        return base_value

    sa_dice = sneak_attack_dice_at_level(rogue_level)
    if sa_dice <= 0:
        return base_value
    sa_avg = sa_dice * 3.5    # average of N d6

    # Pick the best plausible SA target. v1 uses the closest enemy
    # within max attack reach as a proxy — same heuristic the runner's
    # targeting layer applies. If we can't pick one, fall back to base.
    best_target = _pick_best_steady_aim_target(actor, enemies)
    if best_target is None:
        return base_value

    # If an ally is already adjacent to the best target, SA would fire
    # WITHOUT Steady Aim — so Steady Aim only adds the hit-chance uplift
    # on the SA dice (small bump). Otherwise, Steady Aim unlocks the
    # full SA dice firing — much bigger bump.
    if _has_ally_adjacent_to_target(actor, best_target, state):
        sa_uplift = sa_avg * DELTA_HIT_FROM_ADVANTAGE
    else:
        sa_uplift = sa_avg * STEADY_AIM_SA_UNLOCK_HIT_PROXY

    return base_value + sa_uplift


def _pick_best_steady_aim_target(actor: Actor,
                                    enemies: list) -> Actor | None:
    """Pick the closest in-reach enemy as the proxy SA target.

    Walks the actor's weapon_attack actions, finds the max reach, and
    returns the closest living enemy within that distance. None if no
    in-reach enemy exists — Steady Aim still has base value via raising
    the next-attack hit chance (which the caller scores), but the
    SA-unlock branch can't pick a specific target.
    """
    from engine.core.geometry import distance_ft
    actions = (actor.template or {}).get("actions") or []
    reaches: list[int] = []
    for action in actions:
        if action.get("type") != "weapon_attack":
            continue
        for step in (action.get("pipeline") or []):
            if step.get("primitive") != "attack_roll":
                continue
            params = step.get("params") or {}
            if "range_ft" in params:
                reaches.append(int(params["range_ft"]))
            elif "reach_ft" in params:
                reaches.append(int(params["reach_ft"]))
    max_reach = max(reaches) if reaches else 5
    in_reach = [e for e in enemies
                  if distance_ft(actor.position, e.position) <= max_reach]
    if not in_reach:
        return None
    in_reach.sort(key=lambda e: distance_ft(actor.position, e.position))
    return in_reach[0]


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
    # PR #104: Compelled Duel — disadvantage on the target's attacks
    # against anyone other than the caster. In a multi-enemy fight the
    # marked creature usually wants to hit someone other than the
    # Paladin, so the disadvantage applies to most of its attacks —
    # valued like Frightened's disadvantage-on-attacks (0.3). Lower
    # than Frightened-vs-everyone since attacks ON the Paladin
    # themselves are unaffected (the duel "works as intended" there).
    "co_compelled_duel": 0.25,
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

    PR #113: the `caster_spell_save_dc` branch is now ability-aware —
    it delegates to `_caster_spell_dc`, which reads
    template.spellcasting_ability (CHA Paladin / WIS Ranger·Cleric,
    INT fallback). Previously it hardcoded INT, silently
    under-/over-estimating the save DC for every non-INT caster — the
    scoring-side twin of the execution-side bug fixed in PR #104/#110.
    This makes hard-control scoring (Compelled Duel etc.) use the same
    DC the rider will actually roll.
    """
    if action_intent.get("save_dc_fixed") is not None:
        return int(action_intent["save_dc_fixed"])
    dc_source = action_intent.get("save_dc_source") or ""
    if dc_source == "caster_spell_save_dc":
        return _caster_spell_dc(caster)
    if dc_source.startswith("fixed:"):
        try:
            return int(dc_source[len("fixed:"):])
        except ValueError:
            return 13
    return 13


def lr_control_factor(target: Actor) -> float:
    """Scoring discount for a save-or-lose control vs a Legendary Resistance
    target.

    LR (engine v1 policy) spends a charge to turn ANY failed save into a
    success while charges remain, so a control's lockdown won't LAND while
    the target has LR — casting it only DRAINS one charge. We model the
    per-cast value as `1 / (lr_remaining + 1)`: ~0 while LRs are stacked,
    rising to full (1.0) as they deplete. This (a) stops the AI from wasting
    premium control at full value into LR — the observed boss-sim bug — and
    (b) gives a monotone drain-then-land incentive without a multi-turn
    planner. Returns 1.0 when the target has no LR.

    NOTE: optimal sequencing (drain with the CHEAPEST save-forcer, save the
    premium control for lr=0) is superagent-level and deferred — and since
    LR is spent greedily on any save, PC *damage* save-spells also drain it,
    so LRs deplete fast in practice. See engine.core.legendary_resistance.
    """
    from engine.core.legendary_resistance import RESOURCE_KEY
    lr = int((getattr(target, "resources", {}) or {}).get(RESOURCE_KEY, 0))
    return 1.0 / (lr + 1) if lr > 0 else 1.0


def defensive_ehp_hard_control(actor: Actor, target_enemy: Actor,
                                 action: dict, state: CombatState) -> float:
    """Defensive eHP from a save-or-lose control action.

      eHP = enemy_DPR × fail_prob × expected_rounds × denial_fraction
            × lr_control_factor   (LR discount — see below)

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
            * intent["denial_fraction"] * lr_control_factor(target_enemy))


# ============================================================================
# Arming-smite scoring (PR #111) — Searing Smite / Ensnaring Strike
# ============================================================================

# Mean of 1d6 (the empowering-attack bonus + the per-turn DoT on both
# spells). v1 scores the base cast; upcast bonus dice aren't modeled at
# selection time (the rider rolls them at execution).
_SMITE_D6_MEAN = 3.5


def _self_next_hit_prob(actor: Actor) -> float:
    """Probability the caster LANDS its next weapon attack (AC 15
    proxy, same baseline as estimate_dpr). Arming smites fire on the
    next hit, so this gates their whole value. Returns the p_hit of the
    caster's highest-damage weapon attack; 0.0 if it has none."""
    actions = (actor.template or {}).get("actions") or []
    best_value = 0.0
    p_hit_of_best = 0.0
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
        value = _approximate_damage_on_hit(action) * p_hit
        if value > best_value:
            best_value = value
            p_hit_of_best = p_hit
    return p_hit_of_best


def _caster_spell_dc(actor: Actor) -> int:
    """Scoring-time spell save DC: 8 + PB + spellcasting-ability mod.
    Ability-aware (reads template.spellcasting_ability; CHA fallback),
    matching the generalized primitives._caster_spell_save_dc (PR #110)
    so the AI scores against the same DC the rider will roll."""
    pb = int((actor.template.get("cr") or {}).get("proficiency_bonus", 2))
    ability = ((actor.template or {}).get("spellcasting_ability")
                 or "charisma")
    short = _short_ability(ability)
    score = (actor.abilities.get(short) or {}).get("score", 10)
    return 8 + pb + ability_modifier(score)


def _representative_enemy(actor: Actor, state: CombatState):
    """The highest-DPR living enemy — the one the caster most wants to
    burn / lock down, and the proxy target the arming smite is scored
    against (the real target is whoever the caster hits next)."""
    enemies = [a for a in state.encounter.actors
                 if a.side != actor.side and a.is_alive()]
    if not enemies:
        return None
    return max(enemies, key=estimate_dpr)


def _score_searing_smite(actor: Actor, state: CombatState) -> float:
    """eHP of arming Searing Smite (PR #111).

      eHP = p_hit × (bonus_fire + p_fail_CON × burn_per_turn × rounds)

    The +1d6 fire lands on the empowering hit regardless of the save;
    the ignite DoT (1d6/turn) only if the target fails its CON save.
    Scored against the highest-DPR enemy as the plausible next target.
    """
    enemy = _representative_enemy(actor, state)
    if enemy is None:
        return 0.0
    p_hit = _self_next_hit_prob(actor)
    if p_hit <= 0:
        return 0.0
    p_fail = save_fail_probability(enemy, "constitution",
                                     _caster_spell_dc(actor), state)
    burn = p_fail * _SMITE_D6_MEAN * EXPECTED_BUFF_ROUNDS
    return p_hit * (_SMITE_D6_MEAN + burn)


def _score_ensnaring_strike(actor: Actor, state: CombatState) -> float:
    """eHP of arming Ensnaring Strike (PR #111).

      eHP = p_hit × p_fail_STR
            × (enemy_DPR × restrain_denial × rounds + pierce × rounds)

    No bonus damage on the hit; on a failed STR save the target is
    Restrained (control denial, reusing PARTIAL_CONTROL_CONDITIONS'
    co_restrained fraction) and takes 1d6 piercing per turn. Scored
    against the highest-DPR enemy (most worth locking down).
    """
    enemy = _representative_enemy(actor, state)
    if enemy is None:
        return 0.0
    p_hit = _self_next_hit_prob(actor)
    if p_hit <= 0:
        return 0.0
    p_fail = save_fail_probability(enemy, "strength",
                                     _caster_spell_dc(actor), state)
    denial = PARTIAL_CONTROL_CONDITIONS.get("co_restrained", 0.5)
    control = estimate_dpr(enemy) * denial * EXPECTED_CONTROL_ROUNDS
    dot = _SMITE_D6_MEAN * EXPECTED_BUFF_ROUNDS
    return p_hit * p_fail * (control + dot)


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
