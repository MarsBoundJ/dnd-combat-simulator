"""Primitive library — engine handlers for every primitive declared
in the schema.

Phase 1 v1 (after primitives-v1 PR):
  - 13 primitives implemented end-to-end:
      attack_roll, damage, apply_condition, heal, granted_action,   (skeleton v0)
      attack_modifier, save_modifier, d20_test_modifier,             (Q5 unified — keystone)
      crit_modifier, crit_threshold_modifier,
      forced_save, recurring_save, multiattack
  - ~30 primitives still stubbed (raise NotImplementedError on invocation).

Conditions now actually affect gameplay: apply_condition instantiates the
condition's effect primitives onto the target's `active_modifiers` registry,
and attack/save resolution consults the registry via engine/core/modifiers.py.
"""
from __future__ import annotations

import re
import random as _random_module
from typing import Callable, Any
from dataclasses import dataclass

from engine.core.state import CombatState, Actor, ability_modifier
from engine.core.events import EventBus
from engine.core import modifiers as _modifiers
from engine.core import legendary_resistance as _legendary_resistance


# ============================================================================
# Base + Registry
# ============================================================================

@dataclass
class Primitive:
    name: str
    handler: Callable[[dict, CombatState, EventBus], Any]
    implemented: bool = True


class PrimitiveRegistry:
    def __init__(self) -> None:
        self._registry: dict[str, Primitive] = {}

    def register(self, primitive: Primitive) -> None:
        self._registry[primitive.name] = primitive

    def invoke(self, name: str, params: dict, state: CombatState,
               event_bus: EventBus) -> Any:
        if name not in self._registry:
            raise KeyError(f"Unknown primitive: {name!r}. "
                           f"Register it in engine.primitives or stub it.")
        prim = self._registry[name]
        if not prim.implemented:
            raise NotImplementedError(
                f"Primitive {name!r} is stubbed. Implementation deferred."
            )
        return prim.handler(params, state, event_bus)

    @classmethod
    def with_defaults(cls) -> "PrimitiveRegistry":
        reg = cls()
        for prim in _all_primitives():
            reg.register(prim)
        return reg


# ============================================================================
# Dice
# ============================================================================

_DICE_PATTERN = re.compile(r"(\d+)d(\d+)")


def _roll_dice_expr(expr: str, rng: _random_module.Random) -> int:
    m = _DICE_PATTERN.fullmatch(expr.strip())
    if not m:
        raise ValueError(f"Invalid dice expression: {expr!r}")
    count, sides = int(m.group(1)), int(m.group(2))
    return sum(rng.randint(1, sides) for _ in range(count))


def _roll_dice_expr_with_floor(expr: str, floor: int,
                                  rng: _random_module.Random) -> int:
    """Like _roll_dice_expr but clamps each individual die roll to
    `max(roll, floor)`. Used by Great Weapon Fighting (PR #49): a
    GWF user wielding a two-handed melee weapon treats any 1 or 2 on
    a damage die as a 3 (RAW 2024). floor=3 implements that exactly.

    floor=0 / floor=1 → no clamping happens (every roll is already
    ≥ 1). Caller passes 0 to opt out cleanly.
    """
    if floor <= 1:
        return _roll_dice_expr(expr, rng)
    m = _DICE_PATTERN.fullmatch(expr.strip())
    if not m:
        raise ValueError(f"Invalid dice expression: {expr!r}")
    count, sides = int(m.group(1)), int(m.group(2))
    return sum(max(rng.randint(1, sides), floor) for _ in range(count))


def _roll_dice_empowered(expr: str, floor: int, reroll_n: int,
                           rng: _random_module.Random) -> int:
    """Roll `expr` individually, then reroll the lowest `reroll_n` dice
    keeping the new results (Metamagic Empowered Spell). floor clamps
    each die as in _roll_dice_expr_with_floor. Falls back to the floor
    roller for non-NdM expressions or reroll_n <= 0."""
    if reroll_n <= 0:
        return _roll_dice_expr_with_floor(expr, floor, rng)
    m = _DICE_PATTERN.fullmatch(expr.strip())
    if not m:
        return _roll_dice_expr_with_floor(expr, floor, rng)
    count, sides = int(m.group(1)), int(m.group(2))
    fl = floor if floor > 1 else 1
    rolls = [max(rng.randint(1, sides), fl) for _ in range(count)]
    # Reroll the lowest reroll_n dice (RAW: "you must use the new rolls").
    lowest = sorted(range(count), key=lambda i: rolls[i])[:min(reroll_n, count)]
    for i in lowest:
        rolls[i] = max(rng.randint(1, sides), fl)
    return sum(rolls)


# ============================================================================
# IMPLEMENTED — Attack pipeline (v0 + v1 modifier consultation)
# ============================================================================

def _cover_ac_bonus(cover: str) -> int:
    """Cover → AC bonus mapping (PR #48 + PR #76). RAW 2024:
      - half cover: +2 AC + DEX save
      - three-quarters cover: +5 AC + DEX save
      - total cover: can't be targeted directly (handled separately
        in `_attack_roll` via an early auto-miss; returns 0 here
        because total cover is NOT an AC bonus — it's a target-cancel)
    """
    if cover == "half":
        return 2
    if cover == "three_quarters":
        return 5
    return 0


def _is_total_cover(target: Actor) -> bool:
    """True iff target has 'total' cover. RAW PHB 2024: a target with
    total cover can't be the target of a direct attack or a spell
    (though AoE effects that include them can still apply). Used by
    _attack_roll to early-auto-miss and by the candidate generator
    to filter such targets from weapon_attack / multiattack /
    hard_control candidate lists."""
    return getattr(target, "cover", "none") == "total"


def _attack_roll(params: dict, state: CombatState, bus: EventBus) -> dict:
    """Roll d20 + bonus vs target AC. Now consults active_modifiers
    AND the action's reach / range — out-of-range attacks auto-miss.
    """
    from engine.core.geometry import distance_ft, attack_range_ft

    actor: Actor = state.current_attack["actor"]
    target: Actor = state.current_attack["target"]
    bonus = params.get("bonus", 0)
    rng = _get_rng(state, bus)

    # Out-of-range guard. Defends against multiattack execution paths
    # where a sub-attack might be invoked beyond its reach (e.g., a
    # Scimitar swing against a target 30 ft away when the multiattack
    # was gated on the Shortbow's range). Auto-miss with telemetry.
    reach = attack_range_ft(params)
    if distance_ft(actor, target) > reach:
        state.current_attack["state"] = "miss"
        state.event_log.append({
            "event": "attack_roll", "actor": actor.id,
            "target": target.id, "result": "miss",
            "reason": "out_of_range",
            "distance_ft": distance_ft(actor, target),
            "reach_ft": reach,
        })
        return {"state": "miss", "reason": "out_of_range"}

    # PR #76: Total cover auto-miss. RAW PHB 2024: a target with
    # total cover "can't be the target of an attack or a spell."
    # Single-target attacks against such a target auto-miss without
    # rolling. AoE effects that happen to cover the target's square
    # still apply (handled at the AoE level via position-based
    # actors_in_radius / cone / line — not gated by cover).
    # The candidate generator filters total-cover enemies from
    # single-target candidate lists too, so AI doesn't pick them in
    # the first place; this guard catches the multiattack-subattack
    # path and any direct primitive callers.
    if _is_total_cover(target):
        state.current_attack["state"] = "miss"
        state.event_log.append({
            "event": "attack_roll", "actor": actor.id,
            "target": target.id, "result": "miss",
            "reason": "total_cover",
        })
        return {"state": "miss", "reason": "total_cover"}

    # Barrier line-of-effect guard. A wall that breaks line of effect
    # between attacker and target (e.g. Wall of Force) makes a direct
    # attack — ranged OR melee across the barrier — impossible: auto-miss
    # without rolling. Gated on the encounter having walls so a wall-free
    # fight skips this entirely. AoE is handled separately at the
    # area-membership layer (_resolve_save_targets), not here.
    _walls = getattr(state, "walls", None)
    if _walls:
        from engine.core.geometry import line_of_effect_blocked
        if line_of_effect_blocked(actor, target, _walls):
            state.current_attack["state"] = "miss"
            state.event_log.append({
                "event": "attack_roll", "actor": actor.id,
                "target": target.id, "result": "miss",
                "reason": "no_line_of_effect",
            })
            return {"state": "miss", "reason": "no_line_of_effect"}

    # PR #45: reactions fire here. Protection Fighting Style imposes
    # disadvantage on attacks against an adjacent ally. The reaction
    # applies its modifier to the target BEFORE we query
    # attack_modifiers below, so the disadvantage is folded in.
    from engine.core.reactions import resolve_reaction_triggers
    resolve_reaction_triggers("attack_targeting_resolved",
                                {"actor": actor, "target": target,
                                  "reach_ft": reach},
                                state, bus)

    # Query unified modifier registry for attack adjustments + crit changes
    attack_mods = _modifiers.query_attack_modifiers(actor, target, state)
    crit_mods = _modifiers.query_crit_modifiers(actor, target, state)
    # PR #48: cover AC bonus (+2 half, +5 three_quarters). v1 is per-
    # actor and symmetric; future terrain-based per-(attacker, target)
    # cover will replace this lookup.
    cover_ac_bonus = _cover_ac_bonus(target.cover)
    effective_ac = target.ac + attack_mods.ac_modifier + cover_ac_bonus
    effective_bonus = bonus + attack_mods.attack_bonus_modifier
    adv_state = attack_mods.net_advantage()

    if adv_state == "advantage":
        d20 = max(rng.randint(1, 20), rng.randint(1, 20))
    elif adv_state == "disadvantage":
        d20 = min(rng.randint(1, 20), rng.randint(1, 20))
    else:
        d20 = rng.randint(1, 20)

    # PR #75: Halfling Lucky reroll on natural 1 of the d20 that
    # "counts" (the chosen die after advantage/disadvantage
    # resolution). RAW PHB 2024: "you can reroll the die and must
    # use the new roll." No-op if attacker doesn't have Lucky.
    from engine.core.racial_traits import lucky_d20
    d20, _rerolled = lucky_d20(rng, d20, actor)

    total = d20 + effective_bonus
    is_crit = (d20 >= crit_mods.crit_threshold)
    pre_reaction_hit = is_crit or (total >= effective_ac)

    # PR #45: Shield-shape reactions fire here. Their condition gets
    # the current `total` and `current_ac`; on fire, they can apply
    # an ac_modifier (e.g., +5 from Shield) that takes effect
    # immediately for this attack's hit/miss check.
    resolve_reaction_triggers("attack_roll_pending",
                                {"actor": actor, "target": target,
                                  "d20": d20, "total": total,
                                  "current_ac": effective_ac,
                                  "was_going_to_hit": pre_reaction_hit},
                                state, bus)
    # Re-query attack_modifiers — Shield may have bumped the AC.
    # Cover bonus stays the same (cover is a static actor property
    # in v1, not modifiable mid-attack).
    post_attack_mods = _modifiers.query_attack_modifiers(actor, target, state)
    effective_ac = target.ac + post_attack_mods.ac_modifier + cover_ac_bonus
    # Bardic Inspiration self-add: an attacker holding a granted die may
    # spend it post-roll to try to turn a miss into a hit (RAW: add the
    # die after seeing the result). Uses the FINAL effective_ac so it
    # accounts for any Shield / Cutting Words AC bump applied by the
    # attack_roll_pending reactions above. No-op if the attacker holds
    # no die or the die can't close the gap.
    from engine.core import bardic_inspiration as _bardic
    total = _bardic.maybe_add_to_attack(
        actor, total, effective_ac, is_crit, state, rng)
    # Combat Inspiration Defense (Valor Bard): target may spend their tagged
    # BI die to raise their AC against this attack (may turn hit into miss).
    from engine.core.college_of_valor import maybe_defend_with_combat_inspiration
    effective_ac = maybe_defend_with_combat_inspiration(
        target, total, effective_ac, is_crit, state, rng)
    is_hit = is_crit or (total >= effective_ac)
    # Metamagic Seeking Spell: if a spell attack misses, reroll the d20
    # once and use the new roll (set on the action by the metamagic
    # transform). Consumed so a multi-step action doesn't reroll twice.
    _mm_action = (state.current_attack or {}).get("action") or {}
    if (not is_hit and _mm_action.get("metamagic_seeking")):
        _mm_action["metamagic_seeking"] = False
        new_d20 = rng.randint(1, 20)
        if new_d20 > d20:
            d20 = new_d20
            total = d20 + effective_bonus
        is_crit = (d20 >= crit_mods.crit_threshold)
        is_hit = is_crit or (total >= effective_ac)
        state.event_log.append({
            "event": "metamagic_seeking_reroll", "actor": actor.id,
            "new_d20": new_d20, "total": total, "hit": is_hit})
    # Forced crit (e.g., Paralyzed target within 5ft): only fires if hit
    if is_hit and crit_mods.force_crit_if_hit:
        is_crit = True
    attack_state = "crit" if is_crit else ("hit" if is_hit else "miss")

    # Unbreakable Majesty (Glamour L14): the first attack to hit the Bard
    # each turn forces the attacker's CHA save vs the Bard's spell DC, or the
    # attack misses instead. No-op unless the majestic presence is active.
    if attack_state in ("hit", "crit"):
        from engine.core.college_of_glamour import majesty_negates_hit
        if majesty_negates_hit(target, actor, state, rng):
            attack_state = "miss"
            is_hit = False
            is_crit = False

    state.current_attack["state"] = attack_state
    state.current_attack["d20"] = d20
    state.current_attack["total"] = total
    state.current_attack["had_advantage"] = (adv_state == "advantage")
    state.current_attack["had_disadvantage"] = (adv_state == "disadvantage")

    bus.emit("attack_roll", {"actor": actor, "target": target,
                              "d20": d20, "total": total, "vs_ac": effective_ac,
                              "advantage_state": adv_state})
    bus.emit("attack_resolved", {"actor": actor, "target": target,
                                  "state": attack_state, "d20": d20})
    state.event_log.append({"event": "attack_roll", "actor": actor.id,
                            "target": target.id, "d20": d20, "total": total,
                            "vs_ac": effective_ac, "result": attack_state,
                            "advantage_state": adv_state,
                            "crit_threshold": crit_mods.crit_threshold})

    # Lifetime expiry after this attack:
    #   - per_single_attack: both attacker & target (consumed by either-side
    #     participation in one attack)
    #   - per_owner_attack: ONLY the attacker side (Help-shape buffs that
    #     must survive incoming attacks on the owner and only consume
    #     when the owner themselves makes an attack)
    _modifiers.expire_modifiers(actor, {"attack_complete", "owner_made_attack"})
    _modifiers.expire_modifiers(target, {"attack_complete"})

    # PR #71: Rage bookkeeping. The "attacked a hostile creature" flag
    # is set on any swing against an opposing-side target (RAW: "attack"
    # — not "hit on attack"). This must run regardless of attack_state
    # because misses against hostiles still satisfy the rule.
    from engine.core import rage as _rage
    _rage.mark_attacked_hostile(actor, target)

    # PR #54: Weapon Mastery dispatch. Fires AFTER lifetime expiry so
    # newly-registered Vex/Sap modifiers (with per_owner_attack
    # lifetime, which consumes on owner_made_attack) survive THIS
    # attack and only consume on the NEXT swing — exactly RAW. The
    # dispatch is a no-op when the weapon has no mastery or the
    # actor doesn't know it.
    from engine.core.weapon_masteries import apply_mastery_effects
    apply_mastery_effects(params.get("mastery"), actor, target,
                             attack_state, state, bus)

    # PR #48: Hide ends when the actor attacks. RAW: attacking,
    # casting a verbal spell, or making noise breaks Hide. v1 handles
    # the attack case here; the cast-verbal case is deferred.
    # Scrub co_invisible whose source_action_id is "a_hide" (the
    # marker set by _execute_hide). Other sources of Invisible
    # (the spell, etc.) survive.
    actor.applied_conditions = [
        c for c in actor.applied_conditions
        if not (c.get("condition_id") == "co_invisible"
                and c.get("source_action_id") == "a_hide")
    ]

    return {"state": attack_state, "d20": d20, "total": total}


def _damage(params: dict, state: CombatState, bus: EventBus) -> dict:
    target: Actor = state.current_attack["target"]
    actor: Actor = state.current_attack["actor"]
    dice = params.get("dice")
    modifier = params.get("modifier", 0)
    dmg_type = params.get("type", "untyped")
    # Final multiplier applied after resistance/vuln/immunity. Default 1.0.
    # 0.5 = half-damage-on-save (AoE on_success steps), 2.0 = doubled.
    multiplier = float(params.get("multiplier", 1.0))
    rng = _get_rng(state, bus)

    is_crit = state.current_attack.get("state") == "crit"
    # PR #49: damage_die_floor (Great Weapon Fighting): each rolled
    # die is clamped to max(roll, floor). floor=3 implements GWF
    # 2024's "treat any 1 or 2 as a 3" exactly.
    floor = int(params.get("damage_die_floor", 0))

    # Metamagic Empowered Spell: reroll the lowest N damage dice (N =
    # caster CHA mod), set on the damage step's params by the metamagic
    # transform. 0 → normal roll.
    empowered_n = int(params.get("empowered_reroll", 0) or 0)
    if dice:
        rolled = _roll_dice_empowered(dice, floor, empowered_n, rng)
        if is_crit:
            rolled += _roll_dice_empowered(dice, floor, empowered_n, rng)
    else:
        rolled = 0

    # PR #77: upcast scaling. If the in-flight action declares
    # `upcast_scaling` AND state.current_attack.chosen_slot_level
    # > the action's base spell_slot_level, roll the per-level
    # extra dice. RAW upcast pattern: "+Xd[Y] per slot level above
    # base." Schema:
    #   upcast_scaling:
    #     extra_dice_per_level: "1d6"   # the per-level scaling
    #     damage_type: "fire"             # which damage step to scale
    #                                       # (matches `params.type`)
    # When `damage_type` matches the current damage step's `type`,
    # the extra dice fire on THIS step. Spells with one damage type
    # need just one upcast_scaling block; multi-damage-type spells
    # would declare multiple entries (none in v1 — deferred to
    # extension shape if needed).
    upcast_extra = _resolve_upcast_extra_dice(state, dmg_type, rng, is_crit,
                                                  floor)
    rolled += upcast_extra

    # PR #71: Rage damage bonus on STR-mod melee weapon attacks.
    # Added BEFORE resistance/vuln/immunity so BPS resistance against
    # a raging attacker halves the full pre-resistance value (RAW: the
    # rage bonus is part of the damage roll, then resistance applies).
    # Attack params travel via the pipeline's attack_roll step — the
    # `kind` and `ability` keys live on the action's attack_roll step,
    # not directly on the damage step. We read them off the cached
    # state.current_attack.action.pipeline (set by the pipeline at
    # execution time). Safe to read-or-default to ranged/None gate.
    from engine.core import rage as _rage
    attack_params = _extract_attack_params(state)
    if _rage.is_raging(actor):
        if _rage.applies_rage_damage_bonus(actor, attack_params):
            total = rolled + modifier + actor.rage_damage_bonus
        else:
            total = rolled + modifier
    else:
        total = rolled + modifier

    # PR #88: weapon_damage_bonus riders (Divine Favor, future
    # Hex/Hunter's Mark). Only applies to weapon attacks — gated on
    # attack_params.kind being melee or ranged. Adds AFTER rage bonus
    # but BEFORE resistance, so Divine-Favor-buffed damage gets
    # halved by BPS resistance the same way the weapon die does
    # (RAW: the +1d4 radiant is part of the attack's damage).
    is_weapon_attack = (attack_params or {}).get("kind") in ("melee",
                                                                "ranged")
    if is_weapon_attack:
        weapon_bonus = _modifiers.query_weapon_damage_bonus(
            actor, attack_params, state)
        if weapon_bonus:
            total += weapon_bonus

    # PR #72: Sneak Attack rider. Fires on hit/crit only (this
    # branch only runs when the `when: combat.attack_state == hit`
    # filter passes, which is enforced by the pipeline before
    # _damage is invoked — but we double-check here for direct-call
    # callers like tests). Adds 0 if the actor doesn't qualify
    # (non-Rogue, already-used-this-turn, non-finesse-non-ranged,
    # or trigger condition not met).
    from engine.core import sneak_attack as _sa
    sa_state = state.current_attack.get("state")
    if sa_state in ("hit", "crit"):
        sa_damage = _sa.try_apply_sneak_attack(
            actor, target, state, attack_params, rng,
            is_crit=(sa_state == "crit"))
        total += sa_damage
        # PR #73: Divine Smite rider. Same gating as SA (hit/crit on
        # melee weapon). The smite heuristic decides whether to
        # actually spend a slot via pace-aware gating (crit always
        # smites; kill-steal always smites; Fiend/Undead bias;
        # otherwise compare expected damage to slot opportunity
        # cost). Folded into the same damage instance so HP-tracking
        # sees one consolidated hit (RAW 2024: smite damage is part
        # of the attack's hit).
        from engine.core import divine_smite as _ds
        ds_damage = _ds.try_apply_divine_smite(
            actor, target, state, attack_params, rng,
            is_crit=(sa_state == "crit"),
            base_attack_damage=total)
        total += ds_damage
        # Frenzy rider (Path of the Berserker, Barbarian L3). Once-per-
        # turn extra Nd6 (N = rage damage bonus) on the first STR-based
        # hit when Reckless Attack is used while raging. Same fold-into-
        # the-hit treatment as Sneak Attack — adds 0 when the actor
        # doesn't qualify (non-Berserker, not raging, no Reckless this
        # turn, already frenzied this turn, or a non-STR/ranged attack).
        from engine.core import frenzy as _fr
        total += _fr.try_apply_frenzy(
            actor, target, state, attack_params, rng,
            is_crit=(sa_state == "crit"))
        # Divine Fury rider (Path of the Zealot, Barbarian L3). Once-per-
        # turn extra 1d6 + half level on the first weapon/Unarmed hit
        # while raging (no Reckless / STR gate). Folds into the hit like
        # Frenzy; adds 0 when the actor doesn't qualify.
        from engine.core import divine_fury as _df
        total += _df.try_apply_divine_fury(
            actor, target, state, attack_params, rng,
            is_crit=(sa_state == "crit"))
        # PR #89: Searing Smite rider. Fires on the caster's next
        # melee weapon hit when armed. Adds 1d6 fire damage (+1d6
        # per upcast slot level above 1st, doubled on crit) AND
        # fires a CON save on the target — on fail, target gets
        # co_ignited (recurring_damage 1d6 fire per turn). The
        # marker clears after firing (one-shot per cast;
        # concentration continues for the burn). Melee only per
        # RAW: "next time you hit a creature with a Melee weapon."
        if is_weapon_attack and (attack_params or {}).get(
                "kind", "melee") == "melee":
            from engine.core import searing_smite as _ss
            ss_damage = _ss.try_apply_searing_smite_followup(
                actor, target, state, attack_params, rng,
                is_crit=(sa_state == "crit"))
            total += ss_damage
        # PR #110: Ensnaring Strike rider (Ranger). Fires on the
        # caster's next weapon hit when armed — ANY weapon (melee OR
        # ranged), unlike Searing Smite. Adds NO direct damage; fires
        # a STR save on the target and on fail applies co_ensnared
        # (Restrained + 1d6 piercing/turn). One-shot marker clears
        # after firing; concentration continues for the ensnare.
        if is_weapon_attack:
            from engine.core import ensnaring_strike as _es
            _es.try_apply_ensnaring_strike_followup(
                actor, target, state, attack_params, rng,
                is_crit=(sa_state == "crit"))
        # Blinding Smite rider (Paladin, 3rd-level). Melee-only;
        # 3d8 radiant bonus (+1d8/upcast), Blinded auto-applied on hit.
        if is_weapon_attack and (attack_params or {}).get(
                "kind", "melee") == "melee":
            from engine.core import blinding_smite as _bs
            bs_damage = _bs.try_apply_blinding_smite_followup(
                actor, target, state, attack_params, rng,
                is_crit=(sa_state == "crit"))
            total += bs_damage
        # Wrathful Smite rider (Paladin, 1st-level). Melee-only;
        # 1d6 necrotic bonus (+1d6/upcast), WIS save -> co_frightened
        # (+ end-of-turn re-save; non-concentration per PHB 2024).
        if is_weapon_attack and (attack_params or {}).get(
                "kind", "melee") == "melee":
            from engine.core import wrathful_smite as _ws
            ws_damage = _ws.try_apply_wrathful_smite_followup(
                actor, target, state, attack_params, rng,
                is_crit=(sa_state == "crit"))
            total += ws_damage
        # Thunderous Smite rider (Paladin, 1st-level). Melee-only;
        # 2d6 thunder bonus (+1d6/upcast), STR save -> 10-ft push
        # + co_prone.
        if is_weapon_attack and (attack_params or {}).get(
                "kind", "melee") == "melee":
            from engine.core import thunderous_smite as _ts
            ts_damage = _ts.try_apply_thunderous_smite_followup(
                actor, target, state, attack_params, rng,
                is_crit=(sa_state == "crit"))
            total += ts_damage
        # Hail of Thorns rider (Ranger, 1st-level). RANGED-only; thorn
        # burst around the struck target — target + creatures within
        # 5 ft make a DEX save, Nd10 piercing / half (separate
        # save-based damage, never folded into the attack total).
        if is_weapon_attack and (attack_params or {}).get(
                "kind", "melee") == "ranged":
            from engine.core import hail_of_thorns as _ht
            _ht.try_apply_hail_of_thorns_followup(
                actor, target, state, attack_params, rng,
                is_crit=(sa_state == "crit"))
        # Monk on-hit strike riders (Stunning Strike + Open Hand Topple).
        # Melee-only, once per turn each; no bonus damage (control only).
        if is_weapon_attack and (attack_params or {}).get(
                "kind", "melee") == "melee":
            from engine.core import monk_strikes as _monk
            _monk.try_apply_stunning_strike(
                actor, target, state, attack_params, rng)
            _monk.try_apply_open_hand(
                actor, target, state, attack_params, rng)
            # Ram (Wild Heart L14, Power of the Wilds): melee hit while
            # raging with Ram active knocks a Large-or-smaller target Prone
            # (no save). Idempotent on already-prone targets.
            from engine.core import wild_heart as _wh
            _wh.try_apply_ram(actor, target, state, attack_params)
            # Battering Roots (World Tree L10): on-turn hit with a Heavy/
            # Versatile melee weapon applies Topple (CON save → Prone).
            from engine.core import world_tree as _wt
            _wt.try_apply_battering_roots(actor, target, state, attack_params)
        # Combat Inspiration Offense (Valor Bard): if the attacker holds a
        # Combat-Inspiration-tagged BI die, spend it for bonus damage.
        from engine.core.college_of_valor import (
            maybe_add_combat_inspiration_to_damage)
        total += maybe_add_combat_inspiration_to_damage(
            actor, True, state, rng)

    # Resistance / vulnerability / immunity (template-level)
    template = target.template or {}
    if dmg_type in (template.get("damage_immunities") or []):
        total = 0
    elif dmg_type in (template.get("damage_resistances") or []):
        total = total // 2
    elif dmg_type in (template.get("damage_vulnerabilities") or []):
        total = total * 2

    # PR #71: Rage BPS resistance on the TARGET side. RAW: a raging
    # creature has resistance to bludgeoning, piercing, and slashing
    # damage. Layered AFTER template-level resistances — if the target
    # already had template-side BPS resistance, this would double-halve
    # per RAW "resistances don't stack," so we skip the rage halving
    # when the template already halved.
    if _rage.applies_rage_bps_resistance(target, dmg_type):
        already_resisted = dmg_type in (template.get("damage_resistances") or [])
        if not already_resisted:
            total = total // 2

    # Rage of the Gods (Zealot L14): Necrotic, Psychic, Radiant resistance
    # while the divine form is active. Checked after template-level
    # resistances (same "don't double-halve" discipline as rage BPS).
    from engine.core.rage_of_the_gods import applies_resistance as _rotg_resist
    if _rotg_resist(target, dmg_type):
        already_resisted = (dmg_type in (template.get("damage_resistances") or [])
                             or _rage.applies_rage_bps_resistance(target, dmg_type))
        if not already_resisted:
            total = total // 2

    # Rage of the Wilds — Bear aspect (Wild Heart L3): Resistance to every
    # damage type except Force / Necrotic / Psychic / Radiant. Broader than
    # the base Rage B/P/S resistance, so skip if the type was already
    # halved by the template OR base Rage BPS (RAW: resistances don't stack).
    from engine.core.wild_heart import applies_bear_resistance as _bear_resist
    if _bear_resist(target, dmg_type):
        already_resisted = (dmg_type in (template.get("damage_resistances") or [])
                             or _rage.applies_rage_bps_resistance(target, dmg_type))
        if not already_resisted:
            total = total // 2

    # Apply multiplier (after resistance per 5e ordering: resistance halves
    # the post-multiplier? Or multiplier-then-resistance? Per RAW saves halve
    # the rolled total before resistance. For v1 we apply resistance first
    # then multiplier — close enough for eHP scoring).
    if multiplier != 1.0:
        total = int(total * multiplier)

    total = max(0, total)

    # PR #96: Armor of Agathys reflective cold damage. Snapshot
    # whether AoA fires BEFORE damage applies (RAW: thorns fire if
    # the bearer has temp HP at the moment of the hit, even if the
    # hit drops temp HP to 0). Three gates:
    #   1. Target has an active armor_of_agathys_active marker
    #   2. Target currently has temp HP > 0 (the "while you have
    #      these hit points" clause)
    #   3. Attack is melee (RAW: "melee attack")
    #   4. Recursion guard: this isn't itself a thorn reflection
    # Stored in a local; applied AFTER the target's damage resolves
    # so the cold damage to attacker doesn't clobber state mid-flight.
    agathys_marker = None
    agathys_cold_damage = 0
    if (total > 0 and target.temp_hp > 0
            and (attack_params or {}).get("kind") == "melee"
            and actor.is_alive()
            and actor.id != target.id
            and not state.current_attack.get("is_agathys_reflection")):
        for mod in target.active_modifiers:
            if mod.get("primitive") == "armor_of_agathys_active":
                agathys_marker = mod
                agathys_cold_damage = int(
                    (mod.get("params") or {}).get("cold_damage", 5))
                break

    # PR #94: temp HP absorbs damage before regular HP. RAW PHB 2024
    # p.244: "When you take damage, the damage is subtracted from
    # the temporary Hit Points first." If damage exceeds temp HP,
    # the overflow hits regular HP. Both telemetry and downstream
    # checks (concentration save, creature_dropped, rage damage
    # tracker) see the FULL damage amount — temp HP is a defensive
    # buffer, not a damage reduction.
    # Form system: when transformed, hp_current IS the active form's pool;
    # `_form_overflow` records damage beyond it so a carry_overflow policy
    # (Polymorph) can pass excess to the restored true HP on revert.
    _hp_before = target.hp_current
    _dmg_to_hp = 0
    if total > 0 and target.temp_hp > 0:
        absorbed = min(total, target.temp_hp)
        target.temp_hp -= absorbed
        overflow = total - absorbed
        if overflow > 0:
            _dmg_to_hp = overflow
            target.hp_current = max(0, target.hp_current - overflow)
        state.event_log.append({
            "event": "temp_hp_absorbed",
            "target": target.id,
            "absorbed": absorbed,
            "overflow_to_hp": overflow,
            "temp_hp_remaining": target.temp_hp,
        })
    else:
        _dmg_to_hp = total
        target.hp_current = max(0, target.hp_current - total)
    _form_overflow = max(0, _dmg_to_hp - _hp_before)

    # PR #96: fire AoA reflective cold damage to the attacker now
    # that the target's damage has resolved. The reflection runs
    # _damage recursively with `is_agathys_reflection: True` set so
    # the attacker's own AoA (if any) doesn't infinite-loop. After
    # the reflection, if the target's temp HP is now 0, clear the
    # marker — RAW: the spell ends when temp HP is depleted.
    if agathys_marker is not None and agathys_cold_damage > 0:
        saved_attack = state.current_attack
        state.current_attack = {
            "actor": target, "target": actor,
            "action": {"id": "a_armor_of_agathys_thorns"},
            "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
            "is_agathys_reflection": True,
        }
        try:
            state.event_log.append({
                "event": "armor_of_agathys_reflected",
                "bearer": target.id,
                "attacker": actor.id,
                "cold_damage": agathys_cold_damage,
            })
            _damage({
                "dice": "", "modifier": agathys_cold_damage,
                "type": "cold",
            }, state, bus)
        finally:
            state.current_attack = saved_attack
        # Clear the AoA marker if temp HP is now depleted from this
        # hit (RAW: "while you have these hit points" — when they're
        # gone, the spell ends).
        if target.temp_hp <= 0:
            try:
                target.active_modifiers.remove(agathys_marker)
                state.event_log.append({
                    "event": "armor_of_agathys_ended",
                    "bearer": target.id,
                    "reason": "temp_hp_depleted",
                })
            except ValueError:
                pass   # already removed by another path; safe no-op

    # PR #71: track damage taken while raging — feeds the end-of-turn
    # "no attack + no damage" auto-end check. Damage > 0 satisfies the
    # "took damage this turn" branch of the rule.
    _rage.mark_damaged_while_raging(target, total)

    # Regeneration: a suppressing damage type (Troll: acid/fire) switches
    # the trait off for the creature's next turn. No-op for non-regenerators.
    if total > 0:
        from engine.core import regeneration as _regeneration
        _regeneration.note_damage(target, dmg_type)
        # Swallow regurgitate: accumulate damage a swallowed creature deals
        # to its swallower this turn (feeds the end-of-turn check).
        from engine.core import swallow as _swallow_mod
        _swallow_mod.note_damage_to_swallower(actor, target, total)

    bus.emit("damage_dealt", {"actor": actor, "target": target,
                                "amount": total, "type": dmg_type})
    state.event_log.append({"event": "damage_dealt", "actor": actor.id,
                            "target": target.id, "amount": total, "type": dmg_type,
                            "target_hp_remaining": target.hp_current})

    # Break-on-damage control (RAW): any damage ends a break_on_damage
    # condition FOR THE DAMAGED CREATURE (Hypnotic Pattern's charm, Sleep).
    # The spell continues for OTHER affected creatures — we only scrub this
    # target's application, not the caster's concentration. So damaging a
    # hypnotized enemy wakes it; leaving it alone keeps it locked (the
    # peel-one-at-a-time tactic).
    if total > 0 and target.applied_conditions:
        _broken = [a for a in target.applied_conditions
                   if a.get("break_on_damage")]
        for a in _broken:
            remove_condition(target, a["condition_id"], a.get("source_id"))
            state.event_log.append({
                "event": "condition_ended_by_damage",
                "target": target.id, "condition": a["condition_id"]})

    # Concentration check on damage taken (5e RAW: DC = max(10,
    # ceil(damage/2))). Lives in primitives.py so all damage paths get
    # the check uniformly — AoE on_fail / on_success, weapon attack
    # damage, OA damage, sub-attack damage in multiattack, etc.
    if total > 0 and target.concentration_on is not None:
        from engine.core.concentration import attempt_concentration_save
        attempt_concentration_save(target, total, state, rng)

    if target.hp_current == 0:
        # Revivification (Zealot L14 Rage of the Gods): a raging Zealot
        # within 30 ft may use a reaction + Rage use to save the target
        # before death processing. Fires BEFORE forms/death/dying so HP
        # can be restored in time.
        from engine.core.reactions import resolve_reaction_triggers as _rtrig
        _rtrig("creature_would_drop_to_zero", {
            "target": target,
            "target_id": target.id,
        }, state, bus)

    if target.hp_current == 0:
        # Form system: a transformed creature dropping to 0 in its form
        # REVERTS instead of dying (Wild Shape: back to the druid;
        # Polymorph: back to true form with overflow carried). revert_form
        # restores true-form HP and only marks death if the overflow
        # itself zeroes the true form.
        from engine.core import forms
        from engine.core import regeneration as _regeneration
        if forms.is_transformed(target):
            forms.revert_form(target, state, reason="hp_zero",
                                overflow=_form_overflow)
        elif _regeneration.revives_from_zero(target):
            # Troll rule: 0 HP is NOT death. The creature is downed and
            # regenerates back at its next turn start — unless it took
            # acid/fire (regen_suppressed), in which case the turn-start
            # resolution kills it. Leave is_dead False here.
            state.event_log.append({
                "event": "downed_pending_regeneration", "actor": target.id,
            })
        else:
            from engine.core import death_saves as _ds
            # Massive damage (RAW): leftover after dropping to 0 >= HP max =
            # instant death, even for a death-save creature.
            _massive = _ds.is_massive_damage(_form_overflow, target.hp_max)
            _is_crit = bool((state.current_attack or {}).get("is_crit"))
            if _ds.uses_death_saves(target) and not _massive:
                # PCs fall UNCONSCIOUS and roll death saves instead of dying.
                if target.is_dying:
                    # Already down — another hit is an auto death-save failure
                    # (two on a crit); may finish them off.
                    _ds.damage_while_dying(target, state, is_crit=_is_crit)
                else:
                    _ds.enter_dying(target, state)
            else:
                target.is_dead = True
                # Death ends any concentration the deceased was maintaining
                if target.concentration_on is not None:
                    from engine.core.concentration import end_concentration
                    end_concentration(target, state, reason="caster_died")
                # A dying swallower frees whatever it had swallowed.
                from engine.core import swallow as _swallow
                _swallow.release_victims_of(target, state,
                                              reason="swallower_died")
        bus.emit("creature_dropped", {"creature": target})
        state.event_log.append({"event": "creature_dropped", "creature": target.id})
    elif target.is_bloodied():
        bus.emit("creature_bloodied", {"creature": target})

    # PR #45: damage_taken reaction trigger. Hellish Rebuke hooks
    # here — fires only if target is still alive (RAW: HR requires
    # the rebuker to be able to see the attacker and respond, which
    # the dead can't do). Skip if the damage source is the target
    # itself (avoid feedback loop on self-damage primitives).
    if total > 0 and target.is_alive() and actor.id != target.id:
        from engine.core.reactions import resolve_reaction_triggers
        resolve_reaction_triggers("damage_taken", {
            "target_id": target.id,
            "target": target,
            "attacker": actor,
            "attacker_id": actor.id,
            "amount": total,
            "type": dmg_type,
        }, state, bus)

    # PR #93: Ready Action `ally_takes_damage` trigger. Fires AFTER
    # damage applies + reaction-event resolution so the heal/buff
    # readier sees the current HP. Allies of the damaged creature
    # whose readied trigger matches react (typically Healing Word,
    # Cure Wounds, Shield via Ready). Fires even if the damaged
    # creature dropped to 0 HP — Healing Word picking up a downed
    # ally is the most dramatic version of this pattern.
    # Skipped when total <= 0 (no actual damage = no trigger).
    if total > 0:
        from engine.core import ready_action as _ra
        # primitives=None → try_fire uses _invoke_subprimitive's
        # module-level handler table (same dispatch path as
        # forced_save's on_fail / on_success). allow_dead_target=True
        # so a Cleric's Ready Healing Word fires on an ally who
        # just dropped to 0 HP.
        _ra.on_ally_takes_damage(target, total, state, bus)

    return {"amount": total, "target_hp": target.hp_current}


def _apply_condition(params: dict, state: CombatState, bus: EventBus) -> None:
    """Apply a condition + instantiate its effect primitives onto active_modifiers."""
    target: Actor = state.current_attack.get("target") or state.current_actor()
    actor: Actor = state.current_attack.get("actor") or state.current_actor()
    condition_id = params.get("condition_id") or params.get("condition")
    if not condition_id:
        raise ValueError("apply_condition requires condition_id or condition")

    # Mindless Rage (Path of the Berserker, Barbarian L6): immunity to
    # the Charmed and Frightened conditions while Rage is active. The
    # condition simply doesn't land (RAW: "You have Immunity to the
    # Charmed and Frightened conditions while your Rage is active").
    if condition_id in ("co_charmed", "co_frightened") and target is not None:
        from engine.core import rage as _rage
        features = (target.template or {}).get("features_known") or []
        if "f_mindless_rage" in features and _rage.is_raging(target):
            state.event_log.append({
                "event": "condition_immune",
                "target": target.id,
                "condition": condition_id,
                "reason": "mindless_rage",
            })
            return

    application = {
        "condition_id": condition_id,
        "source_id": actor.id if actor else None,
        "applied_at_round": state.round,
        "duration": params.get("duration"),
        # RAW: some control effects (Hypnotic Pattern's charm, Sleep, etc.)
        # END FOR AN AFFECTED CREATURE if it takes any damage. Tagged per
        # application (a property of the spell, NOT the condition — Hold
        # Monster's paralysis is co_incapacitated too but does NOT break).
        "break_on_damage": bool(params.get("break_on_damage")),
    }
    target.applied_conditions.append(application)
    state.event_log.append({"event": "condition_applied",
                            "target": target.id, "condition": condition_id,
                            "source": actor.id if actor else None})

    # Instantiate the condition's effect primitives onto target.active_modifiers.
    # This is also where inherited conditions get appended to applied_conditions
    # (e.g., applying Stunned also adds Incapacitated). The incapacitation
    # check below runs AFTER this so it sees the full transitive condition set.
    _instantiate_condition_effects(target, application, state)

    # RAW (PHB 2024 p.243): if a creature becomes Incapacitated while
    # concentrating, their concentration ends. Stunned / Paralyzed /
    # Unconscious / Petrified inherit Incapacitated and thus also break
    # concentration; raw Incapacitated breaks it directly. Frightened /
    # Charmed / Poisoned / etc. do NOT.
    from engine.core.concentration import check_incapacitation_breaks_concentration
    check_incapacitation_breaks_concentration(target, state)


def _instantiate_condition_effects(target: Actor, application: dict,
                                    state: CombatState) -> None:
    """Look up the condition definition and add its effects as active modifiers."""
    registry = state.content_registry
    if registry is None:
        return  # no registry available; condition is a marker only
    try:
        cond_def = registry.get("condition", application["condition_id"])
    except KeyError:
        return  # condition not in registry; marker only

    for effect in cond_def.get("effects") or []:
        prim = effect.get("primitive")
        # PR #89: recurring_damage effects need to register an entry
        # in state.recurring_damage, NOT in active_modifiers (it's
        # not a modifier — it's a per-turn callback). Invoke the
        # primitive directly with the current_attack context already
        # set up by _apply_condition's caller.
        if prim == "recurring_damage":
            params = dict(effect.get("params") or {})
            params.setdefault("condition_id",
                                application["condition_id"])
            _recurring_damage(params, state, _NoOpBus())
            continue
        if prim == "recurring_save":
            params = dict(effect.get("params") or {})
            params.setdefault("condition_id",
                                application["condition_id"])
            _recurring_save(params, state, _NoOpBus())
            continue
        entry = {
            "primitive": prim,
            "params": effect.get("params") or {},
            "lifetime": "until_condition_ends",
            "source": {
                "type": "condition",
                "condition_id": application["condition_id"],
                "source_creature_id": application["source_id"],
            },
            "applied_at_round": state.round,
            "owner_id": target.id,
        }
        target.active_modifiers.append(entry)

    # Subordinate conditions (inheritance) — apply transitively
    for inherited_id in cond_def.get("inherits_conditions") or []:
        try:
            inherited_def = registry.get("condition", inherited_id)
        except KeyError:
            continue
        # Record inherited application (so the engine knows to expire it too)
        sub_application = {
            "condition_id": inherited_id,
            "source_id": application["source_id"],
            "applied_at_round": state.round,
            "duration": application.get("duration"),
            "parent_condition": application["condition_id"],
            "break_on_damage": application.get("break_on_damage", False),
        }
        target.applied_conditions.append(sub_application)
        for effect in inherited_def.get("effects") or []:
            entry = {
                "primitive": effect.get("primitive"),
                "params": effect.get("params") or {},
                "lifetime": "until_condition_ends",
                "source": {
                    "type": "condition",
                    "condition_id": inherited_id,
                    "source_creature_id": application["source_id"],
                    "parent_condition": application["condition_id"],
                },
                "applied_at_round": state.round,
                "owner_id": target.id,
            }
            target.active_modifiers.append(entry)


def remove_condition(target: Actor, condition_id: str,
                     source_creature_id: str | None = None) -> int:
    """Remove a condition + its active modifiers from target.

    Public helper used by recurring_save and other end-condition triggers.
    Returns count of removed modifiers.
    """
    # Remove the condition application(s)
    target.applied_conditions = [
        a for a in target.applied_conditions
        if not (a.get("condition_id") == condition_id
                and (source_creature_id is None
                     or a.get("source_id") == source_creature_id))
    ]
    # Also remove subordinate applications whose parent_condition matches
    target.applied_conditions = [
        a for a in target.applied_conditions
        if a.get("parent_condition") != condition_id
    ]
    # Remove all active modifiers from this condition
    removed = _modifiers.remove_modifiers_from_source(
        target, "condition", condition_id, source_creature_id
    )
    # Remove subordinate-condition modifiers too
    target.active_modifiers = [
        m for m in target.active_modifiers
        if (m.get("source") or {}).get("parent_condition") != condition_id
    ]
    return removed


def _heal(params: dict, state: CombatState, bus: EventBus) -> dict:
    """Heal a target.

    Target resolution (in order):
      - params.target == 'self'  → current actor heals self (legacy shape)
      - params.target == 'ally'  → uses state.current_attack.target (the
        candidate generator sets this to the ally being healed)
      - params.target missing    → defaults to current_attack.target if a
        heal candidate is being executed, else self
    """
    actor: Actor = state.current_actor()
    target_spec = params.get("target")
    if target_spec == "self":
        target = actor
    elif target_spec in ("ally", "current_target"):
        target = state.current_attack.get("target") or actor
    elif target_spec is None:
        target = state.current_attack.get("target") or actor
    else:
        raise ValueError(f"Unsupported heal target: {target_spec!r}")
    if target is None:
        raise ValueError("heal could not resolve a target")
    rng = _get_rng(state, bus)

    dice = params.get("dice")
    fixed = params.get("fixed", 0)
    modifier_source = params.get("modifier_source")

    amount = fixed
    if dice:
        amount += _roll_dice_expr(dice, rng)
    if modifier_source:
        # modifier_source like 'actor.wis_mod' refers to the CASTER, not
        # the heal target — Cure Wounds is "+ your spellcasting ability mod".
        amount += _resolve_modifier(modifier_source, actor)
    # PR #118: flat `modifier` key — the pre-resolved ability mod baked
    # in at PC-build time (Cure Wounds / Healing Word builders compute
    # the caster's WIS mod and pass it as `modifier`). Was dropped
    # silently, so those heals lost their + ability mod (latent since
    # PR #116 — Cure Wounds healed dice-only).
    amount += int(params.get("modifier", 0))

    # Death-save revival (Stage 2): ANY positive healing on a dying creature
    # brings it back to consciousness at that many HP and clears the death-save
    # tally (RAW). A 0-point heal does NOT revive.
    from engine.core import death_saves as _ds
    if getattr(target, "is_dying", False) and not target.is_dead and amount > 0:
        _ds.revive(target, amount, state, reason="healed")
    else:
        target.hp_current = min(target.hp_max, target.hp_current + amount)
    state.event_log.append({"event": "healed", "target": target.id,
                            "amount": amount, "hp_current": target.hp_current})
    return {"amount": amount, "hp_current": target.hp_current}


def _granted_action(params: dict, state: CombatState, bus: EventBus) -> None:
    actor: Actor = state.current_actor()
    kind = params.get("kind") or params.get("granted_action")
    state.event_log.append({"event": "granted_action",
                            "actor": actor.id, "kind": kind})


# ============================================================================
# IMPLEMENTED — Q5 unified modifier primitives
# ============================================================================
#
# These primitives REGISTER modifiers onto an actor's active_modifiers list.
# They are invoked at apply-time (e.g., when a condition is applied, when a
# feature grants a passive modifier, when Shield is cast as a reaction).
# The engine consults the registry at attack_roll / save / d20-test time via
# engine.core.modifiers.

def _attack_modifier(params: dict, state: CombatState, bus: EventBus) -> None:
    """Register an attack_modifier on the current target/actor."""
    owner = _resolve_modifier_owner(params, state)
    entry = _build_modifier_entry("attack_modifier", params, owner, state)
    owner.active_modifiers.append(entry)


def _save_modifier(params: dict, state: CombatState, bus: EventBus) -> None:
    owner = _resolve_modifier_owner(params, state)
    entry = _build_modifier_entry("save_modifier", params, owner, state)
    owner.active_modifiers.append(entry)


def _d20_test_modifier(params: dict, state: CombatState, bus: EventBus) -> None:
    owner = _resolve_modifier_owner(params, state)
    entry = _build_modifier_entry("d20_test_modifier", params, owner, state)
    owner.active_modifiers.append(entry)


def _crit_modifier(params: dict, state: CombatState, bus: EventBus) -> None:
    owner = _resolve_modifier_owner(params, state)
    entry = _build_modifier_entry("crit_modifier", params, owner, state)
    owner.active_modifiers.append(entry)


def _crit_threshold_modifier(params: dict, state: CombatState, bus: EventBus) -> None:
    owner = _resolve_modifier_owner(params, state)
    entry = _build_modifier_entry("crit_threshold_modifier", params, owner, state)
    owner.active_modifiers.append(entry)


def _weapon_damage_bonus(params: dict, state: CombatState,
                            bus: EventBus) -> None:
    """Register a weapon_damage_bonus on the current target/actor
    (PR #88).

    Used by Divine Favor (+1d4 radiant on weapon hits, modeled as
    flat +2 average). Future consumers: Hex / Hunter's Mark / Searing
    Smite / Holy Weapon.

    Params (mirror attack_modifier's modifier-entry shape):
      - target: 'self' | 'ally' | 'current_target' (default 'self')
      - value: int — flat damage to add on each qualifying weapon hit
      - when: optional gate string (melee_attack | ranged_attack |
        weapon_attack); empty → fires on every weapon attack
      - lifetime: until_short_rest / until_concentration_ends / etc.
      - source: caster_id / action_id / named_effect for concentration
        scrub
    """
    owner = _resolve_modifier_owner(params, state)
    entry = _build_modifier_entry("weapon_damage_bonus", params, owner,
                                       state)
    owner.active_modifiers.append(entry)


def _resolve_modifier_owner(params: dict, state: CombatState) -> Actor:
    """Determine which actor a modifier attaches to.

    Targets supported:
      - 'self' (default) — caster (e.g., self-Bless, Shield reaction)
      - 'ally' / 'current_target' — the candidate's target (used by
        offensive_buff actions where the ally being buffed is set as
        state.current_attack.target by the candidate generator)
    For modifiers from conditions, the owner is the condition's target
    — handled by _instantiate_condition_effects, NOT by this function.
    """
    target = params.get("target", "self")
    if target == "self":
        # During a REACTION (Shield, etc.) the self-modifier owner is the
        # REACTOR — state.current_attack["actor"], set by the reaction system —
        # NOT whoever's turn it is. current_actor() would (a) attach a reactive
        # self-buff to the turn-holder rather than the reactor, and (b) raise
        # IndexError when the reaction fires during a legendary action (resolved
        # between turns, current_turn_idx out of range — the brass-dragon
        # crash). current_attack["actor"] is the actor performing the current
        # action in both turn and reaction contexts, so prefer it for reactions.
        ca = state.current_attack or {}
        if ca.get("is_reaction") and ca.get("actor") is not None:
            return ca["actor"]
        actor = state.current_actor()
        if actor is None and ca:
            actor = ca.get("actor")
        if actor is None:
            raise ValueError("No owner resolvable for modifier")
        return actor
    if target in ("ally", "current_target"):
        owner = state.current_attack.get("target") if state.current_attack \
            else None
        if owner is None:
            raise ValueError(
                f"target={target!r} requires state.current_attack.target "
                "to be set (typically by the candidate generator)"
            )
        return owner
    raise ValueError(f"Unsupported modifier target: {target!r}")


def _build_modifier_entry(primitive_name: str, params: dict, owner: Actor,
                           state: CombatState) -> dict:
    # If caller didn't explicitly specify a source, infer one from the
    # currently-executing action + caster. This lets eHP scoring detect
    # "this target already has my buff" and skip redundant re-casts
    # (Bless every round was the canary that drove this).
    source = params.get("source")
    if not source:
        action = (state.current_attack or {}).get("action") or {}
        caster = (state.current_attack or {}).get("actor")
        source = {
            "type": "action_buff",
            "action_id": action.get("id"),
            "caster_id": caster.id if caster else None,
        }
        # PR #36: if the action declares a `named_effect` (RAW spell
        # identity — e.g., "bless", "heroism"), stamp it on the source
        # so cross-caster dedup can fire. Two Blesses on the same
        # target shouldn't stack per PHB 2024 p.243.
        named_effect = action.get("named_effect")
        if named_effect:
            source["named_effect"] = named_effect
    return {
        "primitive": primitive_name,
        "params": dict(params),  # copy, don't share
        "lifetime": params.get("lifetime", "until_short_rest"),  # default conservative
        "source": source,
        "applied_at_round": state.round,
        "owner_id": owner.id,
    }


# ============================================================================
# IMPLEMENTED — Spell mechanics (forced_save, recurring_save)
# ============================================================================

def _sculpt_protected_count(state: CombatState) -> int:
    """Sculpt Spells (Evoker, f_sculpt_spells): when the caster casts an
    EVOCATION spell that affects multiple creatures, it auto-protects up to
    (1 + spell level) chosen creatures — they auto-succeed AND take ZERO damage
    (even on a half-damage save). Mechanically identical to Careful Spell, so
    the save loop reuses the same auto-protect path.

    Returns 0 when there's no caster, the action isn't tagged
    `school: evocation`, or the caster lacks Sculpt Spells. The protected
    count is spent on the caster's ALLIES in target order (the optimal use:
    shield your own party from your fireball)."""
    ca = state.current_attack or {}
    caster = ca.get("actor")
    action = ca.get("action") or {}
    if caster is None or action.get("school") != "evocation":
        return 0
    features = (caster.template or {}).get("features_known") or []
    if "f_sculpt_spells" not in features:
        return 0
    level = int(ca.get("chosen_slot_level")
                or action.get("spell_slot_level", 0) or 0)
    return 1 + level


def _forced_save(params: dict, state: CombatState, bus: EventBus) -> dict:
    """Force the current target (or specified affected set) to make a save.

    Params:
      ability: 'strength' | 'dexterity' | 'constitution' | ...
      dc: int OR dc_source: 'caster_spell_save_dc' OR 'fixed:N'
      affected: 'current_target' (default) | 'all_creatures_in_area' (skeleton: just current_target)
      on_fail: list of effect_primitives to invoke
      on_success: list of effect_primitives to invoke (often empty / 'half')

    Sets state.current_save with outcome for chained primitives to consume.
    """
    ability = params.get("ability", "dexterity")
    dc = _resolve_dc(params, state)
    rng = _get_rng(state, bus)

    # PR #75: stash save-source context BEFORE per-target loop so
    # query_save_modifiers can apply racial trait advantages (Brave /
    # Fey Ancestry / Dwarven Resilience). The context is the same for
    # every target this call hits (the on_fail block is shared), so a
    # single set + cleared-at-end pattern is correct.
    from engine.core.racial_traits import build_save_context
    saved_save_context = state.current_save_context
    state.current_save_context = build_save_context(params)

    # Metamagic honors (set by engine.core.metamagic transforms):
    #   - careful_allies: N caster-allies auto-succeed + take no damage
    #     (Careful Spell). Exhausted in target order.
    #   - heightened: the first rolling target makes its save at
    #     disadvantage (Heightened Spell — RAW "one target").
    careful_allies = int(params.get("careful_allies", 0) or 0)
    careful_used = 0
    # Sculpt Spells (Evoker) — auto-protect (1 + spell level) caster-allies
    # from this evocation AoE, identical effect to Careful Spell.
    sculpt_protected = _sculpt_protected_count(state)
    sculpt_used = 0
    heightened = bool(params.get("heightened"))
    heightened_applied = False
    mm_caster = (state.current_attack or {}).get("actor")

    targets = _resolve_save_targets(params, state)
    rolls = []
    for target in targets:
        # Careful Spell: a chosen caster-ally automatically succeeds and
        # takes no damage (skip rolling + skip on_success/on_fail).
        if (careful_allies and mm_caster is not None
                and target.side == mm_caster.side
                and careful_used < careful_allies):
            careful_used += 1
            rolls.append({"target_id": target.id, "outcome": "success",
                           "d20": None, "total": None, "dc": dc,
                           "ability": ability, "careful": True})
            state.current_save = {"target": target, "outcome": "success",
                                   "ability": ability, "dc": dc}
            state.event_log.append({
                "event": "forced_save", "target": target.id,
                "ability": ability, "dc": dc, "d20": None, "total": None,
                "outcome": "success", "metamagic_careful": True})
            continue
        # Sculpt Spells (Evoker): a chosen caster-ally auto-succeeds and takes
        # NO damage from this evocation AoE (same shape as Careful Spell). This
        # is what lets the evoker drop a fireball through its own swarmed
        # martials to clear the enemies cleanly. The CASTER is NOT an eligible
        # sculpt target (whether it may choose itself is a contested RAW point;
        # we take the conservative reading), so if it stands in its own blast
        # it takes the damage like anyone else.
        if (sculpt_protected and mm_caster is not None
                and target.side == mm_caster.side
                and target.id != mm_caster.id
                and sculpt_used < sculpt_protected):
            sculpt_used += 1
            rolls.append({"target_id": target.id, "outcome": "success",
                           "d20": None, "total": None, "dc": dc,
                           "ability": ability, "sculpt": True})
            state.current_save = {"target": target, "outcome": "success",
                                   "ability": ability, "dc": dc}
            state.event_log.append({
                "event": "forced_save", "target": target.id,
                "ability": ability, "dc": dc, "d20": None, "total": None,
                "outcome": "success", "sculpt_spells": True})
            continue
        # Query save modifiers
        save_mods = _modifiers.query_save_modifiers(target, ability, state)
        override = save_mods.net_outcome_override()

        if override == "auto_fail":
            outcome = "fail"
            d20 = None
            total = None
        elif override == "auto_succeed":
            outcome = "success"
            d20 = None
            total = None
        else:
            save_bonus = target.abilities.get(_short_ability(ability), {}).get("save", 0)
            adv_state = save_mods.net_advantage()
            # Heightened Spell: force disadvantage on the first rolling
            # target (overrides any pre-existing advantage state).
            if heightened and not heightened_applied:
                adv_state = "disadvantage"
                heightened_applied = True
            if adv_state == "advantage":
                d20 = max(rng.randint(1, 20), rng.randint(1, 20))
            elif adv_state == "disadvantage":
                d20 = min(rng.randint(1, 20), rng.randint(1, 20))
            else:
                d20 = rng.randint(1, 20)
            # PR #75: Halfling Lucky reroll on natural 1 of the d20
            # that counts (post-adv/disadv resolution).
            from engine.core.racial_traits import lucky_d20
            d20, _rerolled = lucky_d20(rng, d20, target)
            # PR #48: cover gives a bonus to DEX saves too (+2 half,
            # +5 three_quarters). Only applies to DEX saves per RAW.
            cover_save_bonus = 0
            if ability == "dexterity":
                cover_save_bonus = _cover_ac_bonus(target.cover)
            total = (d20 + save_bonus
                      + save_mods.save_bonus_modifier
                      + cover_save_bonus)
            outcome = "success" if total >= dc else "fail"

        # Bardic Inspiration: a creature holding a BI die may add it to a
        # failed save to turn it into a success — the same held-resource
        # self-add modeled on attack rolls. Only on a real roll (auto_fail
        # overrides have total None). Fires before the reroll features +
        # Legendary Resistance (cheapest self-resource first).
        if outcome == "fail" and total is not None:
            from engine.core.bardic_inspiration import maybe_add_to_save
            bi_total = maybe_add_to_save(target, total, dc, state, rng)
            if bi_total != total:
                total = bi_total
                outcome = "success" if total >= dc else "fail"

        # Fanatical Focus (Zealot L6): once per Rage, reroll a failed save
        # with +rage_damage_bonus. Fires before Legendary Resistance so the
        # Zealot gets their reroll first (then LR may still flip it back).
        if outcome == "fail":
            from engine.core.fanatical_focus import try_fanatical_focus_reroll
            ff_d20, ff_total, ff_outcome = try_fanatical_focus_reroll(
                target, ability, dc, rng, state)
            if ff_d20 is not None:
                d20, total, outcome = ff_d20, ff_total, ff_outcome
        # Countercharm (Bard L7): if the save would apply Charmed/Frightened
        # and the creature (or an ally within 30 ft) is a Bard with a
        # Reaction, reroll with Advantage. Also before Legendary Resistance.
        if outcome == "fail":
            from engine.core.countercharm import try_countercharm_reroll
            cc_d20, cc_total, cc_outcome = try_countercharm_reroll(
                target, ability, dc, params, rng, state)
            if cc_d20 is not None:
                d20, total, outcome = cc_d20, cc_total, cc_outcome

        # Legendary Resistance: a legendary creature that just failed a
        # save may spend a per-day charge to succeed instead. Applies to
        # every fail path above (rolled OR auto_fail override). The natural
        # d20/total stay on the log line; maybe_use emits its own
        # legendary_resistance_used event so the swap is traceable.
        if outcome == "fail" and _legendary_resistance.maybe_use(
                target, state, ability=ability, dc=dc):
            outcome = "success"

        rolls.append({"target_id": target.id, "outcome": outcome,
                       "d20": d20, "total": total, "dc": dc,
                       "ability": ability})
        state.current_save = {"target": target, "outcome": outcome,
                              "ability": ability, "dc": dc}
        state.event_log.append({"event": "forced_save", "target": target.id,
                                "ability": ability, "dc": dc,
                                "d20": d20, "total": total, "outcome": outcome})

        # Swap state.current_attack.target to THIS iteration's target so
        # sub-primitives (damage, apply_condition) deal with the right
        # creature. Critical for AoE where the original .target is just
        # an "anchor"; each affected creature needs its own damage roll.
        saved_attack_target = state.current_attack.get("target")
        state.current_attack["target"] = target
        try:
            # Invoke on_fail or on_success sub-primitives (if specified inline)
            # Evasion (Rogue/Monk L7, Dance Leading Evasion L14): on a DEX
            # save-for-half effect, a creature with Evasion takes 0 on success
            # and half on fail. select_evasion_subs returns the damage-scaled
            # sub list when it applies; otherwise we use the normal branch.
            from engine.core.evasion import select_evasion_subs
            ev_subs = select_evasion_subs(target, ability, outcome, params,
                                            state)
            if ev_subs is not None:
                state.event_log.append({
                    "event": "evasion", "target": target.id,
                    "outcome": outcome})
                for sub in ev_subs:
                    _invoke_subprimitive(sub, state, bus)
            elif outcome == "fail":
                for sub in params.get("on_fail") or []:
                    _invoke_subprimitive(sub, state, bus)
            else:
                for sub in params.get("on_success") or []:
                    _invoke_subprimitive(sub, state, bus)
        finally:
            state.current_attack["target"] = saved_attack_target
    # PR #75: restore prior save context now that this forced_save
    # call is done. Restored rather than cleared so nested save calls
    # (rare; not currently used by any spell but defensive) leave the
    # outer context intact.
    state.current_save_context = saved_save_context
    return {"rolls": rolls}


def _slot_recovery_partial(params: dict, state: CombatState,
                              bus: EventBus) -> dict:
    """Restore expended spell slots up to a combined-level budget.

    The canonical use is Wizard's Arcane Recovery: total slot levels
    restored ≤ ceil(wizard_level / 2), capped at 5th-level slots
    individually.

    Resolution target: `state.current_attack.actor` if set (caller put
    the actor whose slots are being restored there), else
    `state.current_actor()`. The restoration walks slot levels from
    `max_slot_level` down to 1, restoring one slot at a time at each
    level while:
      - the actor has expended slots at that level
        (`spell_slots[level] < spell_slots_max[level]`), AND
      - the level fits in the remaining budget

    Greedy high-first: restores higher-level slots first because they
    carry more value (a 5th-level slot beats five 1st-level slots in
    practice). This matches the typical wizard's Arcane Recovery play.

    Params:
      max_combined_level: int — total slot levels available to restore
      max_slot_level: int — cap on individual slot level (default 9)

    No-op if the actor has no `spell_slots_max` (non-caster or fixture
    that didn't declare the post-rest ceiling). No-op if the actor has
    no expended slots.

    Returns {"restored": [{"level": L, "count": N}, ...]} for logging.
    Also appends a `slot_recovery_partial` event to state.event_log.
    """
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("slot_recovery_partial requires a current actor")
    budget = int(params.get("max_combined_level", 0))
    max_level = int(params.get("max_slot_level", 9))
    restored_by_level: dict[int, int] = {}
    if not actor.spell_slots_max:
        return {"restored": []}
    # Walk highest-first within budget
    level = max_level
    while level >= 1 and budget > 0:
        if level > budget:
            level -= 1
            continue
        max_at = int(actor.spell_slots_max.get(level, 0))
        cur = int(actor.spell_slots.get(level, 0))
        if cur < max_at:
            actor.spell_slots[level] = cur + 1
            budget -= level
            restored_by_level[level] = restored_by_level.get(level, 0) + 1
            continue       # try same level again — could have multiple slots expended
        level -= 1
    restored_list = [{"level": L, "count": N}
                      for L, N in sorted(restored_by_level.items(),
                                          reverse=True)]
    state.event_log.append({
        "event": "slot_recovery_partial",
        "actor": actor.id,
        "restored": restored_list,
        "budget_remaining": budget,
    })
    return {"restored": restored_list}


class _NoOpBus:
    """Minimal event bus stand-in for sub-primitive invocations from
    inside other primitives. _recurring_damage's _NoOpBus mirror at
    the apply_condition call site; defining it here once keeps the
    pattern uniform."""

    def emit(self, *args, **kwargs) -> None:
        return None


def _temp_hp_grant(params: dict, state: CombatState,
                      bus: EventBus) -> None:
    """Grant temporary hit points to the current target (PR #94,
    upcast extended in PR #96).

    RAW PHB 2024 p.244: temp HP doesn't stack — gaining temp HP
    while you already have some keeps the GREATER value. We use
    max-semantics: `target.temp_hp = max(target.temp_hp, amount)`.

    Params:
      - target: 'self' | 'ally' | 'current_target' (default
        'current_target' — caller sets state.current_attack.target)
      - amount (int, optional): flat temp HP to grant (base value)
      - amount_source (str, optional): one of
        'caster_spellcasting_modifier' | 'caster_cha_mod' |
        'caster_wis_mod' — computed at invoke time from the caster.
        Mutually exclusive with `amount` (amount wins if both set).
      - amount_per_slot_above_base (int, optional, PR #96): per-
        upcast-level bonus. When set + spell cast at slot N above
        base level B, adds `(N - B) × this_value` to the grant.
        Reads cast level from state.current_attack.chosen_slot_level
        (set by pipeline.execute for upcasted casts). Used by
        Armor of Agathys (+5 temp HP per upcast level).

    Logs `temp_hp_granted` with target / amount / final_temp_hp.
    """
    target = state.current_attack.get("target") or state.current_actor()
    if target is None:
        raise ValueError("temp_hp_grant requires a current target")
    if "amount" in params:
        amount = int(params["amount"])
    else:
        amount = _resolve_temp_hp_amount(
            params.get("amount_source", "caster_spellcasting_modifier"),
            state)
    # PR #96: upcast scaling. Apply per-level bonus when the cast
    # slot exceeds the action's base spell_slot_level.
    per_slot_bonus = int(params.get("amount_per_slot_above_base", 0))
    if per_slot_bonus > 0:
        chosen_level = int(state.current_attack.get(
            "chosen_slot_level") or 0)
        action = state.current_attack.get("action") or {}
        base_level = int(action.get("spell_slot_level", 1))
        if chosen_level > base_level:
            amount += (chosen_level - base_level) * per_slot_bonus
    if amount <= 0:
        return
    prior = target.temp_hp
    target.temp_hp = max(target.temp_hp, amount)
    state.event_log.append({
        "event": "temp_hp_granted",
        "target": target.id,
        "amount": amount,
        "prior_temp_hp": prior,
        "final_temp_hp": target.temp_hp,
    })


def _resolve_temp_hp_amount(source: str, state: CombatState) -> int:
    """Compute a temp HP amount from a source token. Used by
    _temp_hp_grant and _recurring_temp_hp when `amount_source` is
    declared instead of a literal `amount`. Returns max(1, value) so
    a 0-mod caster still grants 1 temp HP (RAW: grants are positive)."""
    caster = (state.current_attack or {}).get("actor") or \
              state.current_actor()
    if caster is None:
        return 0
    abilities = caster.abilities or {}
    if source in ("caster_spellcasting_modifier",
                    "caster_cha_mod"):
        # Default to CHA (Paladin / Bard / Sorcerer / Warlock)
        score = (abilities.get("cha") or {}).get("score", 10)
    elif source == "caster_wis_mod":
        score = (abilities.get("wis") or {}).get("score", 10)
    elif source == "caster_int_mod":
        score = (abilities.get("int") or {}).get("score", 10)
    else:
        return 0
    mod = (score - 10) // 2
    return max(1, mod)


def _hp_max_grant(params: dict, state: CombatState,
                     bus: EventBus) -> None:
    """Raise the current target's maximum AND current HP (PR #97).

    Distinct from temp HP (a separate absorbing buffer). RAW spells
    like Aid raise both current and max HP for the duration:
      "Each target's hit point maximum and current hit points
       increase by 5 for the duration."

    Params:
      - target: 'self' | 'ally' | 'current_target' (default
        current_attack.target)
      - amount (int): base HP increase
      - amount_per_slot_above_base (int, optional): per-upcast-level
        bonus (reads chosen_slot_level vs action.spell_slot_level)

    Dedup: keyed by the action's named_effect — if the target already
    has an active bonus from the same named effect (e.g., Aid re-cast
    on an ally who's still under a prior Aid), the grant is skipped
    (RAW: same-named effects don't stack). The bonus ledger entry on
    `target.hp_max_bonuses` lets `remove_hp_max_bonus` cleanly undo
    the change when the spell ends.

    Logs `hp_max_granted`.
    """
    target = state.current_attack.get("target") or state.current_actor()
    caster = (state.current_attack or {}).get("actor") or \
              state.current_actor()
    if target is None:
        raise ValueError("hp_max_grant requires a current target")
    amount = int(params.get("amount", 0))
    per_slot_bonus = int(params.get("amount_per_slot_above_base", 0))
    if per_slot_bonus > 0:
        chosen_level = int(state.current_attack.get(
            "chosen_slot_level") or 0)
        action = state.current_attack.get("action") or {}
        base_level = int(action.get("spell_slot_level", 1))
        if chosen_level > base_level:
            amount += (chosen_level - base_level) * per_slot_bonus
    if amount <= 0:
        return
    action = (state.current_attack or {}).get("action") or {}
    named_effect = action.get("named_effect")
    action_id = action.get("id")
    # Dedup by named_effect (same spell doesn't stack on a target).
    if named_effect:
        for entry in target.hp_max_bonuses:
            if entry.get("named_effect") == named_effect:
                return   # already has this effect; no stacking
    target.hp_max += amount
    target.hp_current += amount
    target.hp_max_bonuses.append({
        "amount": amount,
        "source_id": caster.id if caster else None,
        "source_action_id": action_id,
        "named_effect": named_effect,
    })
    state.event_log.append({
        "event": "hp_max_granted",
        "target": target.id,
        "amount": amount,
        "new_hp_max": target.hp_max,
        "new_hp_current": target.hp_current,
    })


def remove_hp_max_bonus(target: Actor, *, source_id: str | None = None,
                           source_action_id: str | None = None,
                           named_effect: str | None = None) -> int:
    """Remove matching max-HP bonuses from `target` and lower hp_max
    accordingly (PR #97). Caps hp_current at the reduced hp_max per
    RAW ("if this lowers your maximum below your current HP, your
    current HP drops to match").

    Matches entries where the provided keys equal the entry's fields
    (None keys are wildcards — at least one key must be provided).
    Returns the total HP amount removed (sum of matched bonuses).

    Used by long-rest cleanup (apply_long_rest) and a future timed-
    duration system when an Aid-style spell expires.
    """
    if not target.hp_max_bonuses:
        return 0
    removed_total = 0
    kept: list = []
    for entry in target.hp_max_bonuses:
        match = True
        if source_id is not None and entry.get("source_id") != source_id:
            match = False
        if (source_action_id is not None
                and entry.get("source_action_id") != source_action_id):
            match = False
        if (named_effect is not None
                and entry.get("named_effect") != named_effect):
            match = False
        if match:
            removed_total += int(entry.get("amount", 0))
        else:
            kept.append(entry)
    if removed_total > 0:
        target.hp_max_bonuses = kept
        target.hp_max = max(1, target.hp_max - removed_total)
        # Cap current HP at the reduced maximum (RAW).
        if target.hp_current > target.hp_max:
            target.hp_current = target.hp_max
    return removed_total


def _grant_speed(params: dict, state: CombatState, bus: EventBus) -> None:
    """Grant the current target a movement speed (Fly's fly 60) for the
    duration. Records a `active_speed_grants` ledger entry so
    concentration.end_concentration can cleanly revert it.

    Params:
      - target: 'self' | 'ally' | 'current_target' (default current target)
      - speed_type (str): 'fly' (default), 'walk', 'swim', ...
      - amount (int): the speed in ft (default 60)

    Sets target.speed[speed_type] = max(amount, existing) so a creature with a
    faster innate speed keeps it; stores the PRIOR value (None = key absent) for
    revert. Dedup by the action's named_effect (re-casting Fly on the same ally
    doesn't stack). Logs `speed_granted`."""
    target = state.current_attack.get("target") or state.current_actor()
    caster = (state.current_attack or {}).get("actor") or state.current_actor()
    if target is None:
        raise ValueError("grant_speed requires a current target")
    speed_type = params.get("speed_type", "fly")
    amount = int(params.get("amount", 60))
    action = (state.current_attack or {}).get("action") or {}
    named_effect = action.get("named_effect")
    action_id = action.get("id")
    if named_effect:
        for g in target.active_speed_grants:
            if g.get("named_effect") == named_effect:
                return   # already has this effect; no stacking
    if target.speed is None:
        target.speed = {}
    prior = target.speed.get(speed_type)
    if amount <= int(prior or 0):
        return   # innate speed already as fast or faster; nothing to grant
    target.speed[speed_type] = amount
    target.active_speed_grants.append({
        "speed_type": speed_type,
        "amount": amount,
        "prior": prior,
        "source_caster_id": caster.id if caster else None,
        "source_action_id": action_id,
        "named_effect": named_effect,
    })
    state.event_log.append({
        "event": "speed_granted",
        "target": target.id,
        "speed_type": speed_type,
        "amount": amount,
        "source": caster.id if caster else None,
    })


def _recurring_temp_hp(params: dict, state: CombatState,
                          bus: EventBus) -> None:
    """Register a per-turn temp HP grant on the current target
    (PR #94). The dual of recurring_damage — used by Heroism and
    future per-turn grant spells (Aid-shape effects with duration).

    Each tick fires at the target's turn-start (resolved by
    runner._resolve_recurring_temp_hp). Re-grants the amount each
    time; max-semantics on Actor.temp_hp means the temp HP doesn't
    accumulate (RAW: replace if greater).

    Params:
      - amount (int) OR amount_source (str): see _temp_hp_grant
      - trigger_event (str, default 'target_turn_start')

    Source ids stamped from state.current_attack so end_concentration
    can match-and-scrub when the spell drops.
    """
    target = state.current_attack.get("target") or state.current_actor()
    actor = state.current_attack.get("actor") or state.current_actor()
    action = state.current_attack.get("action") or {}
    if "amount" in params:
        amount = int(params["amount"])
    else:
        amount = _resolve_temp_hp_amount(
            params.get("amount_source", "caster_spellcasting_modifier"),
            state)
    if amount <= 0:
        return
    entry = {
        "target_id": target.id,
        "source_id": actor.id if actor else None,
        "source_action_id": action.get("id"),
        "amount": amount,
        "trigger_event": params.get("trigger_event", "target_turn_start"),
        "applied_at_round": state.round,
    }
    state.recurring_temp_hp.append(entry)


def _recurring_damage(params: dict, state: CombatState,
                         bus: EventBus) -> None:
    """Register a per-turn damage tick on the current target (PR #89).

    Used by ongoing-damage conditions like co_ignited (Searing Smite
    burn). Each tick fires at the affected creature's turn-start
    (resolved by runner._resolve_recurring_damage).

    Params:
      - dice (str): damage dice (e.g., "1d6")
      - type (str): damage type (e.g., "fire")
      - trigger_event (str, default 'target_turn_start'): when the
        tick fires. v1 only supports 'target_turn_start'.
      - condition_id (str, optional): the host condition id; lets
        condition-removal scrub the tick (when the condition ends
        via a save-to-end action or other mechanism).

    Source ids (target_id / source_id / source_action_id) come from
    `state.current_attack` so concentration-end cleanup in
    end_concentration can match-and-scrub.
    """
    target = state.current_attack.get("target") or state.current_actor()
    actor = state.current_attack.get("actor") or state.current_actor()
    action = state.current_attack.get("action") or {}
    entry = {
        "target_id": target.id,
        "source_id": actor.id if actor else None,
        "source_action_id": action.get("id"),
        "dice": params.get("dice", "1d6"),
        "damage_type": params.get("type", "untyped"),
        "trigger_event": params.get("trigger_event", "target_turn_start"),
        "condition_id": params.get("condition_id"),
        "applied_at_round": state.round,
    }
    state.recurring_damage.append(entry)


def _recurring_save(params: dict, state: CombatState, bus: EventBus) -> None:
    """Register a recurring save check on a target at a named event.

    Engine resolves these at the appropriate turn boundary (see runner.py).

    AoE usage (PR #35): when placed in a `forced_save` step's `on_fail`
    block, the registration fires once per failed creature because
    `forced_save`'s per-target loop swaps `state.current_attack.target`
    to the current iteration's creature before invoking sub-primitives.
    Result: each held creature gets its own end-of-turn save entry with
    the correct target_id.
    """
    target = state.current_attack.get("target") or state.current_actor()
    actor = state.current_attack.get("actor") or state.current_actor()
    entry = {
        "target_id": target.id,
        "source_id": actor.id if actor else None,
        "ability": params.get("ability", "wisdom"),
        "dc": _resolve_dc(params, state),
        "trigger_event": params.get("trigger_event", "target_turn_end"),
        "on_success": params.get("on_success", "end_spell_on_target"),
        "condition_id": params.get("condition_id"),  # what to end if save succeeds
        "applied_at_round": state.round,
    }
    state.recurring_saves.append(entry)


# ============================================================================
# IMPLEMENTED — persistent_aura (Spirit Guardians, PR #43)
# ============================================================================

# PR #60 + PR #68: map `creates_zone` values to the encounter
# environment list key they append to. Future zone-creating spells
# (Fog Cloud, Stinking Cloud, Silence, Web, etc.) extend this dict.
_CREATES_ZONE_TO_ENV_KEY: dict[str, str] = {
    "magical_dark": "magical_dark_zones",
    "heavy_obscurement": "heavily_obscured_zones",
    # PR #79: Silence creates a silence_zone that suppresses
    # Verbal-component spellcasting for actors fully inside the
    # sphere. The pipeline filter reads `silence_zones` to gate
    # spell candidates; no vision impact.
    "silence": "silence_zones",
}


def _persistent_aura(params: dict, state: CombatState, bus: EventBus) -> None:
    """Register a persistent self-anchored or point-anchored area effect.

    The aura triggers forced saves (or no-save damage) on creatures who
    satisfy `trigger_event` (v1: `target_turn_start_in_area` — fires at
    each affected creature's turn-start while they're within the area).
    The runner resolves triggers via
    `_resolve_persistent_aura_triggers`.

    Params:
      shape: 'sphere' (default) | 'cube'
      radius_ft: int — radius for sphere shapes (centered on the
        aura's anchor)
      size_ft: int — cube side length for cube shapes (centered on
        anchor; see `actors_in_cube` for the half-extent convention)
      anchor: 'caster' (default) — aura moves with caster (Spirit
              Guardians). The runner reads the live caster.position at
              each trigger.
              | 'point' — aura placed at cast time, doesn't move
              (Moonbeam, Cloud of Daggers, Sickening Radiance). The
              origin comes from `state.current_attack.area_origin`
              (set by the candidate generator for point-anchored).
      trigger_event: str — when the trigger fires (v1 only supports
        'target_turn_start_in_area')
      ability: str — save ability ('wisdom', etc.). Pass 'none' or
        omit to skip the save and apply on_fail damage directly
        (Cloud of Daggers, Sleet Storm-class spells).
      dc: int — save DC (ignored if ability == 'none' or absent)
      on_fail: list[dict] — sub-primitives invoked on failed save
        (also fires unconditionally when there's no save)
      on_success: list[dict] — sub-primitives invoked on successful
        save (typically a half-damage variant). Ignored if no save.
      affected: 'enemies' (default) | 'all_creatures' — RAW exclusion
        for spells like Spirit Guardians is modeled via 'enemies';
        spells with true friendly fire (Cloud of Daggers, Sickening
        Radiance) use 'all_creatures'.

    Tagged with the caster's concentration source so end_concentration
    can scrub the aura when concentration drops.
    """
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("persistent_aura requires a current actor")
    action = (state.current_attack or {}).get("action") or {}
    anchor = params.get("anchor", "caster")
    # Point-anchored auras read origin from state.current_attack —
    # candidate generator sets area_origin on the chosen candidate.
    if anchor == "point":
        origin = (state.current_attack or {}).get("area_origin")
        if origin is None:
            # Fallback: caster position. Test fixtures may call the
            # primitive directly without setting area_origin.
            origin = tuple(actor.position)
        else:
            origin = tuple(origin)
    else:
        # Caster-anchored auras don't record a fixed origin; the runner
        # reads caster.position live at each trigger.
        origin = None
    # `ability='none'` (or omitted entirely) means no save — on_fail
    # damage is applied unconditionally. Normalize to None for the
    # entry so the runner can branch cleanly.
    ability = params.get("ability")
    if ability == "none":
        ability = None
    entry = {
        "caster_id": actor.id,
        "action_id": action.get("id"),
        "named_effect": action.get("named_effect"),
        "shape": params.get("shape", "sphere"),
        "radius_ft": int(params.get("radius_ft", 0)),
        "size_ft": int(params.get("size_ft", 0)),
        "anchor": anchor,
        "origin": origin,         # None for caster-anchored
        "trigger_event": params.get("trigger_event",
                                       "target_turn_start_in_area"),
        "ability": ability,       # None means no-save
        "dc": _resolve_dc(params, state) if ability else 0,
        "on_fail": params.get("on_fail") or [],
        "on_success": params.get("on_success") or [],
        "affected": params.get("affected", "enemies"),
        "applied_at_round": state.round,
        # PR #77: capture the chosen_slot_level + the action's full
        # upcast_scaling block at registration time so the runner's
        # trigger path can stamp them onto state.current_attack when
        # firing per-turn damage. Lets HoH / Cloudkill / future
        # persistent_aura damage upcast correctly. The full action
        # is also tucked away so _resolve_upcast_extra_dice has the
        # spell_slot_level + upcast_scaling fields it needs.
        "chosen_slot_level": int((state.current_attack or {})
                                       .get("chosen_slot_level", 0)),
        "spell_slot_level": int(action.get("spell_slot_level", 0)),
        "upcast_scaling": dict(action.get("upcast_scaling") or {}) or None,
    }
    # Charge-limited auras (Cordon of Arrows: 4 planted arrows, each
    # destroyed after one shot; +2 per slot above base). `charges`
    # sets remaining_triggers; the runner decrements per firing and
    # removes the aura at 0. Absent → unlimited (normal auras).
    if params.get("charges") is not None:
        charges = int(params["charges"])
        per_slot = int(params.get("charges_per_slot_above_base", 0))
        if per_slot:
            base = int(action.get("spell_slot_level", 0))
            chosen = entry["chosen_slot_level"] or base
            charges += per_slot * max(0, chosen - base)
        entry["remaining_triggers"] = charges
    # PR #60 + PR #68: `creates_zone` param — persistent_auras that
    # ALSO declare an environment zone. The zone is stamped with
    # caster_id + action_id so concentration end can scrub it
    # alongside the aura. Supported zone types:
    #   - "magical_dark" (PR #60) — Darkness spell. Appends to
    #     state.encounter.environment.magical_dark_zones.
    #   - "heavy_obscurement" (PR #68) — Cloudkill / Fog Cloud /
    #     other fog-shaped spells. Appends to heavily_obscured_zones.
    # Both use sphere shape via the same `radius_ft` field. Future
    # zone types (e.g., difficult_terrain) extend
    # _CREATES_ZONE_TO_ENV_KEY.
    creates_zone = params.get("creates_zone")
    if creates_zone is not None:
        env_key = _CREATES_ZONE_TO_ENV_KEY.get(creates_zone)
        if env_key is None:
            raise ValueError(
                f"creates_zone={creates_zone!r} not recognized. "
                f"Known: {sorted(_CREATES_ZONE_TO_ENV_KEY)}."
            )
        if anchor != "point" or origin is None:
            raise ValueError(
                f"creates_zone={creates_zone!r} requires "
                f"anchor=point and a resolved origin. Caster-"
                f"anchored zone spells deferred."
            )
        # Ensure environment dict + zone list exist
        if state.encounter is not None:
            env = state.encounter.environment or {}
            zones = list(env.get(env_key) or [])
            zones.append({
                "shape": "sphere",
                "center": list(origin),
                "radius_ft": int(params.get("radius_ft", 15)),
                "caster_id": actor.id,
                "action_id": action.get("id"),
            })
            env[env_key] = zones
            state.encounter.environment = env
            entry["creates_zone"] = creates_zone

    state.persistent_auras.append(entry)
    state.event_log.append({
        "event": "persistent_aura_registered",
        "caster": actor.id,
        "action": action.get("id"),
        "shape": entry["shape"],
        "radius_ft": entry["radius_ft"],
        "size_ft": entry["size_ft"],
        "anchor": entry["anchor"],
        "origin": list(origin) if origin is not None else None,
        "trigger_event": entry["trigger_event"],
        "creates_zone": entry.get("creates_zone"),
    })


# ============================================================================
# IMPLEMENTED — counterspell_resolve (PR #46)
# ============================================================================

def _counterspell_resolve(params: dict, state: CombatState,
                              bus: EventBus) -> dict:
    """Resolve a Counterspell attempt (SRD 5.2.1 / PHB 2024).

    The TARGET CASTER makes a Constitution saving throw against the
    counterspeller's spell save DC. On a failed save, the spell
    dissipates (state.cast_cancelled = True; pipeline.execute skips
    the pipeline and refunds the slot). On a successful save, the
    spell goes through.

    No level comparison, no auto-success, no caster ability check —
    the 2024 version simplified to a flat CON save.

    Returns {"outcome": "countered" | "resisted"}.
    """
    rng = _get_rng(state, bus)
    counterspeller = state.current_attack.get("actor")
    if counterspeller is None:
        raise ValueError("counterspell_resolve needs a current actor")
    event_data = state.current_attack.get("reaction_event_data") or {}
    target_caster = event_data.get("caster")
    target_action = event_data.get("action") or {}
    target_level = int(event_data.get("spell_slot_level", 0))

    dc = _caster_spell_save_dc(counterspeller)

    con_score = ((target_caster.abilities.get("con") or {}).get("score", 10)
                   if target_caster else 10)
    con_save_bonus = ((target_caster.abilities.get("con") or {}).get("save", 0)
                        if target_caster else 0)
    d20 = rng.randint(1, 20)
    from engine.core.racial_traits import lucky_d20
    if target_caster:
        d20, _rerolled = lucky_d20(rng, d20, target_caster)
    total = d20 + con_save_bonus
    save_failed = total < dc

    if save_failed:
        state.cast_cancelled = True

    state.event_log.append({
        "event": "counterspell_resolved",
        "counterspeller": counterspeller.id,
        "target_caster": target_caster.id if target_caster else None,
        "target_spell": target_action.get("id"),
        "target_level": target_level,
        "outcome": "countered" if save_failed else "resisted",
        "d20": d20,
        "con_save_bonus": con_save_bonus,
        "total": total,
        "dc": dc,
    })
    return {"outcome": "countered" if save_failed else "resisted"}


# ============================================================================
# IMPLEMENTED — multiattack (handled in pipeline.execute via type check)
# ============================================================================
#
# The multiattack primitive itself is a marker; the actual N-attack loop is
# implemented in engine/core/pipeline.py:execute(). When an action has
# type=multiattack, execute() reads count + sub_actions and loops the pipeline.

def _multiattack(params: dict, state: CombatState, bus: EventBus) -> None:
    """Marker primitive — actual multi-attack loop is in pipeline.execute."""
    # Nothing to do here; pipeline.execute reads action.type to detect this.
    pass


# ============================================================================
# STUB PRIMITIVES — raise NotImplementedError when invoked
# ============================================================================

_STUB_PRIMITIVES = [
    # Modifiers not yet implemented
    "speed_modifier", "damage_modifier", "ability_check_modifier",
    "death_save_threshold_modifier",
    # Spell pipeline (besides forced_save / recurring_save)
    "triggered_save",
    # Condition effects
    "sense_restriction", "movement_restriction", "action_restriction",
    "damage_resistance_grant", "condition_immunity_grant",
    "state_transition", "concentration_break", "visibility_state",
    "awareness_state", "state_flag",
    # Action / turn
    "additional_action", "at_will_spell_grant",
    "free_cast_per_rest",
    # Spellcasting infrastructure
    "spellcasting_enable", "cantrips_known_grant", "spell_grant",
    "proficiency_grant", "ability_score_increase",
    "free_spell_to_known_list",
    # Special
    "target_swap", "ignite_objects", "damage_max", "self_damage_rider",
    "advantage_on", "on_event_effect", "designate_protected",
    "attack_state_modifier",
]


def _stub_handler(name: str):
    def handler(params: dict, state: CombatState, bus: EventBus) -> None:
        raise NotImplementedError(
            f"Primitive {name!r} is stubbed. Implementation deferred."
        )
    return handler


# ============================================================================
# Helpers
# ============================================================================

def _get_rng(state: CombatState, bus: EventBus) -> _random_module.Random:
    return _rng


def _resolve_upcast_extra_dice(state: CombatState, damage_type: str,
                                  rng: _random_module.Random,
                                  is_crit: bool, floor: int) -> int:
    """Compute the upcast bonus dice for the in-flight damage step
    (PR #77). Returns 0 when:
      - No current_attack (direct primitive call without context)
      - chosen_slot_level == 0 (non-spell action)
      - Action has no `upcast_scaling` block
      - chosen_slot_level <= base spell_slot_level (no upcast)
      - The upcast_scaling's damage_type filter doesn't match the
        current damage step's type (multi-type spells can scale
        only specific damage types per RAW)

    Otherwise rolls `extra_dice_per_level × (chosen - base)` dice,
    doubled on crit (matches the base-dice doubling pattern).
    """
    if not state.current_attack:
        return 0
    chosen_slot = int(state.current_attack.get("chosen_slot_level", 0))
    if chosen_slot <= 0:
        return 0
    action = state.current_attack.get("action") or {}
    upcast = action.get("upcast_scaling")
    if not upcast:
        return 0
    base_level = int(action.get("spell_slot_level", 0))
    if chosen_slot <= base_level:
        return 0
    extra_dice_expr = upcast.get("extra_dice_per_level")
    if not extra_dice_expr:
        return 0
    # Optional damage-type filter — only scale matching type. For
    # spells that scale a single damage type (Hellish Rebuke fire,
    # HoH cold, Cloudkill poison), this gates the upcast bonus to
    # the correct damage step. If absent, applies to all damage
    # steps in the action.
    scale_type = upcast.get("damage_type")
    if scale_type and scale_type != damage_type:
        return 0
    levels_above = chosen_slot - base_level
    total = 0
    # Roll extra_dice_per_level × levels_above. e.g. "1d6" × 2
    # levels above = 2d6 extra.
    for _ in range(levels_above):
        total += _roll_dice_expr_with_floor(extra_dice_expr, floor, rng)
        if is_crit:
            total += _roll_dice_expr_with_floor(extra_dice_expr, floor, rng)
    return total


def _extract_attack_params(state: CombatState) -> dict:
    """Pull the live attack_roll params for the in-flight attack (PR #71).
    Used by the Rage damage-bonus check in `_damage`, which needs to
    know whether the swing was melee/ranged and STR/DEX.

    Reads `state.current_attack.action.pipeline` and finds the first
    `attack_roll` step. Returns its params dict, or {} if no attack
    pipeline is detected (e.g., damage from a no-attack source like
    Cloud of Daggers — Rage never applies there anyway).

    `state.current_attack.attack_roll_params` may also be set
    explicitly by future test seams; that wins if present.
    """
    if not state.current_attack:
        return {}
    explicit = state.current_attack.get("attack_roll_params")
    if explicit is not None:
        return dict(explicit)
    action = state.current_attack.get("action") or {}
    for step in (action.get("pipeline") or []):
        if step.get("primitive") == "attack_roll":
            return dict(step.get("params") or {})
    return {}


def _dash(params: dict, state: CombatState, bus: EventBus) -> None:
    """Generic Dash primitive (PR #74).

    Sets `actor.dashed_this_turn = True`, which both:
      - Doubles the actor's walk speed for any subsequent
        `_move_to_engage` call this turn (RAW: Dash grants extra
        movement equal to your Speed)
      - Clears `actor.moved_this_turn` so a second move attempt can
        fire (the runner re-attempts movement after BA if the actor
        Dashed and there's still an out-of-reach enemy)

    Invoked by:
      - The Cunning Action Dash variant (Rogue L2+ bonus action,
        PR #74)
      - Future generic Dash action available to all actors as a
        main-slot option (deferred — out of scope for PR #74)
    """
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("dash requires a current actor")
    actor.dashed_this_turn = True
    # Clear moved_this_turn so the runner's post-BA second-move pass
    # can fire (without this, the existing moved_this_turn=True guard
    # in _move_to_engage would short-circuit the retry).
    actor.moved_this_turn = False
    state.event_log.append({
        "event": "dash_taken",
        "actor": actor.id,
        "doubled_speed_ft": int((actor.speed or {}).get("walk", 30)) * 2,
    })


def _lay_on_hands(params: dict, state: CombatState, bus: EventBus) -> None:
    """Lay on Hands primitive (PR #83, Paladin L1+).

    RAW PHB 2024: Paladin has a healing pool of 5 × paladin_level
    HP. As a Bonus Action, touch a creature and restore HP up to
    the remaining pool. v1 only models the heal half (deferred:
    "spend 5 pool to neutralize Poisoned condition").

    The amount healed is computed at primitive-invoke time as:
        min(target_missing_hp, actor_pool_remaining)
    This auto-rights the amount: never overheals, never wastes
    pool below what the target needs. Pool drains by the actual
    amount healed.

    Reads pool from `actor.resources["lay_on_hands_pool_remaining"]`.
    No-op (returns 0 heal, no pool drain, no event) when:
      - Pool is empty / missing
      - Target is at full HP / dead / not a valid heal target
    """
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("lay_on_hands requires a current actor")
    target = (state.current_attack or {}).get("target") or actor
    if not target.is_alive():
        return
    pool = int(actor.resources.get("lay_on_hands_pool_remaining", 0))
    if pool <= 0:
        return
    missing = max(0, int(target.hp_max) - int(target.hp_current))
    if missing <= 0:
        return
    amount = min(missing, pool)
    target.hp_current = min(target.hp_max,
                                int(target.hp_current) + amount)
    actor.resources["lay_on_hands_pool_remaining"] = pool - amount
    state.event_log.append({
        "event": "lay_on_hands",
        "actor": actor.id,
        "target": target.id,
        "amount": amount,
        "pool_remaining": pool - amount,
    })


def _warrior_of_the_gods(params: dict, state: CombatState,
                            bus: EventBus) -> None:
    """Warrior of the Gods (Path of the Zealot, Barbarian L3+).

    RAW: a pool of d12s (4/5/6/7 at L3/6/12/17). As a Bonus Action,
    expend dice from the pool, roll them, and regain HP equal to the
    total. Self-only ("heal yourself"). Pool refreshes on a Long Rest.

    v1 spend policy: heal the actor by spending the FEWEST dice that, at
    the d12 average (6.5), cover the actor's missing HP — at least one
    die, never more than the pool. Mirrors Lay on Hands' "never waste"
    property while honoring the dice-roll variance.

    No-op when the pool is empty or the actor is at full HP / dead.
    """
    import math
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None or not actor.is_alive():
        return
    dice = int(actor.resources.get("warrior_of_the_gods_dice_remaining", 0))
    if dice <= 0:
        return
    missing = max(0, int(actor.hp_max) - int(actor.hp_current))
    if missing <= 0:
        return
    need = max(1, math.ceil(missing / 6.5))
    spend = min(dice, need)
    rng = _get_rng(state, bus)
    healed = sum(rng.randint(1, 12) for _ in range(spend))
    actor.hp_current = min(int(actor.hp_max),
                              int(actor.hp_current) + healed)
    actor.resources["warrior_of_the_gods_dice_remaining"] = dice - spend
    state.event_log.append({
        "event": "warrior_of_the_gods",
        "actor": actor.id,
        "dice_spent": spend,
        "amount": healed,
        "dice_remaining": dice - spend,
    })


def _zealous_presence(params: dict, state: CombatState,
                        bus: EventBus) -> None:
    """Zealous Presence (Path of the Zealot, Barbarian L10+).

    RAW: "As a Bonus Action, unleash a battle cry infused with divine
    energy. Up to ten other creatures of your choice within 60 feet gain
    Advantage on attack rolls and saving throws until the start of your
    next turn. Once you use this feature, you can't use it again until you
    finish a Long Rest unless you expend a use of your Rage (no action
    required) to restore it."

    v1: fans out advantage on attacks (attack_modifier, attacker_is_self)
    and saves (save_modifier, advantage) to up to 10 allies within 60 ft.
    Modifiers use `until_source_caster_next_turn` lifetime — scrubbed by
    modifiers.scrub_source_caster_turn_start_modifiers at the Zealot's
    next turn-start (already called by the runner at every turn-start).

    Resource consumption is handled by the `feature_use` gate at the
    pipeline level (the action declares `feature_use:
    zealous_presence_uses_remaining` + `rage_refund: true`), so this
    primitive does NOT decrement the pool — it only applies the buff. The
    candidate gate guarantees a charge (or an affordable Rage refund) is
    available before this runs.
    """
    from engine.core.geometry import distance_ft
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        return

    source = {
        "type": "action_buff",
        "action_id": "a_zealous_presence",
        "caster_id": actor.id,
    }
    allies_buffed = []
    count = 0
    for candidate in state.encounter.actors:
        if count >= 10:
            break
        if candidate.id == actor.id:
            continue
        if candidate.side != actor.side:
            continue
        if not candidate.is_alive():
            continue
        if distance_ft(actor.position, candidate.position) > 60:
            continue
        # Attack advantage: fires when THIS ally is the attacker
        candidate.active_modifiers.append({
            "primitive": "attack_modifier",
            "params": {"when": "attacker_is_self", "modifier": "advantage_for_self"},
            "lifetime": "until_source_caster_next_turn",
            "source": source,
            "applied_at_round": state.round,
            "owner_id": candidate.id,
        })
        # Save advantage: fires when THIS ally makes any save
        candidate.active_modifiers.append({
            "primitive": "save_modifier",
            "params": {"modifier": "advantage"},
            "lifetime": "until_source_caster_next_turn",
            "source": source,
            "applied_at_round": state.round,
            "owner_id": candidate.id,
        })
        allies_buffed.append(candidate.id)
        count += 1

    state.event_log.append({
        "event": "zealous_presence",
        "actor": actor.id,
        "allies_buffed": allies_buffed,
    })


def _mantle_of_inspiration(params: dict, state: CombatState,
                             bus: EventBus) -> None:
    """Mantle of Inspiration (College of Glamour L3). The Bardic Inspiration
    use is consumed by the action's feature_use gate; this rolls the Bardic
    die and grants up to CHA-mod allies within 60 ft Temp HP = 2× the roll."""
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        return
    from engine.core.college_of_glamour import resolve_mantle_of_inspiration
    resolve_mantle_of_inspiration(actor, state, _get_rng(state, bus))


def _mantle_of_majesty_activate(params: dict, state: CombatState,
                                  bus: EventBus) -> None:
    """Mantle of Majesty (Glamour L6) activation BA: assume the unearthly
    appearance + cast Command free. The use is consumed by the feature_use
    gate."""
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        return
    from engine.core.college_of_glamour import activate_mantle_of_majesty
    activate_mantle_of_majesty(actor, state, bus)


def _mantle_of_majesty_command(params: dict, state: CombatState,
                                 bus: EventBus) -> None:
    """Mantle of Majesty sustained BA: while the appearance is active, cast
    Command free each turn."""
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        return
    from engine.core.college_of_glamour import cast_mantle_command
    cast_mantle_command(actor, state, bus)


def _unbreakable_majesty_activate(params: dict, state: CombatState,
                                    bus: EventBus) -> None:
    """Assume the Unbreakable Majesty presence (Glamour L14 BA). The use is
    consumed by the action's feature_use gate; this sets the active flag."""
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        return
    from engine.core.college_of_glamour import activate_unbreakable_majesty
    activate_unbreakable_majesty(actor, state)


def _eagle_bound(params: dict, state: CombatState, bus: EventBus) -> None:
    """Eagle Bound (Wild Heart L3, Rage of the Wilds — Eagle aspect).

    The per-later-turn Bonus Action: while raging with Eagle active, take
    the Dash AND Disengage actions together (RAW: "you can take a Bonus
    Action on each of your turns to take both of those actions"). Sets the
    same Dash + Disengage flags as the rage-entry grant via
    wild_heart.apply_eagle_bound. Self-targeted (no params)."""
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("eagle_bound requires a current actor")
    from engine.core.wild_heart import apply_eagle_bound
    apply_eagle_bound(actor)
    state.event_log.append({
        "event": "eagle_bound",
        "actor": actor.id,
        "doubled_speed_ft": int((actor.speed or {}).get("walk", 30)) * 2,
    })


def _travel_teleport(params: dict, state: CombatState, bus: EventBus) -> None:
    """Travel along the Tree (World Tree L14) Bonus-Action teleport: reposition
    the barbarian up to 60 ft toward the nearest enemy, landing adjacent.
    Self-targeted (no params)."""
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("travel_teleport requires a current actor")
    from engine.core.world_tree import execute_travel_teleport
    execute_travel_teleport(actor, state)


def _inspiring_movement(params: dict, state: CombatState,
                          bus: EventBus) -> None:
    """Inspiring Movement (College of Dance L6) reaction payload. The Dance
    Bard (state.current_attack.actor) repositions away from the triggering
    enemy (state.current_attack.target), and one nearby ally repositions too.
    The BI use + reaction are consumed by the reaction gate."""
    reactor = (state.current_attack or {}).get("actor")
    mover = (state.current_attack or {}).get("target")
    if reactor is None or mover is None:
        return
    from engine.core.college_of_dance import execute_inspiring_movement
    execute_inspiring_movement(reactor, mover, state, bus)


def _branches_pull(params: dict, state: CombatState, bus: EventBus) -> None:
    """Branches of the Tree (World Tree L6) reaction payload.

    Resolves the STR save and, on a failure, teleports the mover adjacent to
    the barbarian and reduces its Speed to 0 for the turn. The reactor (the
    barbarian) is state.current_attack.actor; the mover is
    state.current_attack.target (set by the reaction dispatch)."""
    reactor = (state.current_attack or {}).get("actor")
    mover = (state.current_attack or {}).get("target")
    if reactor is None or mover is None:
        return
    from engine.core.world_tree import execute_branches_pull
    execute_branches_pull(reactor, mover, state)


def _revivification_save(params: dict, state: CombatState,
                          bus: EventBus) -> None:
    """Revivification (Rage of the Gods reaction, Zealot L14+).

    Executes when the `creature_would_drop_to_zero` trigger fires and the
    reactor passes the `revivification_would_save` condition. Spends one
    Rage use and sets the target's HP to the Zealot's Barbarian level.

    state.current_attack["actor"] = the Zealot (reactor)
    state.current_attack["target"] = the creature about to drop to 0
    """
    reactor = (state.current_attack or {}).get("actor")
    target = (state.current_attack or {}).get("target")
    if reactor is None or target is None:
        return
    from engine.core.rage_of_the_gods import execute_revivification
    execute_revivification(reactor, target, state)


def _steady_aim(params: dict, state: CombatState, bus: EventBus) -> None:
    """Steady Aim primitive (PR #80, Rogue L3+).

    RAW PHB 2024: "As a Bonus Action, you can take aim at one
    creature you can see that is within range of a weapon you're
    wielding. You have Advantage on your next attack roll against
    the target. This benefit expires if you don't make the attack
    roll before the end of the current turn or if your attack misses.
    Your Speed is 0 until the end of this turn."

    Eligibility (enforced at candidate-emission time, not here):
      - Actor must NOT have moved this turn (RAW prohibits Steady
        Aim once movement is spent)
      - Actor has at least L3 Rogue (gated in pc_schema)
      - Bonus Action available (standard BA gate)

    Effects:
      - Register an attack_modifier on the actor: advantage on next
        attack. Lifetime `per_owner_attack` consumes on the
        actor's NEXT attack roll — matches RAW's "next attack."
      - Mark `actor.moved_this_turn = True` to prevent any
        subsequent _move_to_engage call (RAW: "your speed is 0
        until the end of this turn").

    v1 simplifications:
      - RAW also expires the buff "if your attack misses." Today's
        modifier system consumes on owner-made-attack regardless of
        outcome. The advantage still applies to the swing, which is
        the load-bearing behavior; spurious carry-over only matters
        for the rare path where a Rogue swings once with Steady Aim
        and immediately tries to swing again — current engine
        already gates that via actions_used_this_turn.
      - "Target one creature you can see within weapon range" gate
        deferred — the eligibility check above relies on the BA
        candidate-emission flow, which doesn't yet pre-target a
        specific enemy for Steady Aim (the advantage applies to
        whatever the next attack hits).
    """
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("steady_aim requires a current actor")

    # Speed-to-0 enforcement: mark as already-moved so the runner's
    # _move_to_engage early-returns. Even if it never tried to move,
    # this prevents subsequent attempts post-Steady-Aim. Cleared by
    # reset_turn at start of next turn.
    actor.moved_this_turn = True

    # Register the advantage attack_modifier. Same shape as Vex
    # mastery's per-owner-attack advantage rider (PR #54), so the
    # `per_owner_attack` lifetime correctly consumes on the next
    # swing rather than persisting.
    entry = {
        "primitive": "attack_modifier",
        "params": {"target": "self", "modifier": "advantage"},
        "lifetime": "per_owner_attack",
        "source": {"type": "feature",
                     "feature_id": "f_steady_aim",
                     "source_creature_id": actor.id},
        "applied_at_round": state.round,
        "owner_id": actor.id,
    }
    actor.active_modifiers.append(entry)
    state.event_log.append({
        "event": "steady_aim_taken",
        "actor": actor.id,
        "round": state.round,
    })


def _armor_of_agathys_arm(params: dict, state: CombatState,
                              bus: EventBus) -> None:
    """Register the Armor of Agathys reflective-cold marker on the
    caster (PR #96).

    Companion to the temp_hp_grant step in f_armor_of_agathys's
    pipeline. The marker is read by `_damage` when the marker-bearer
    is hit by a melee attack AND has temp HP at the moment of the
    hit — fires cold damage back at the attacker.

    Params:
      - cold_damage (int, default 5): base cold damage dealt to a
        melee attacker who hits the marker-bearer
      - cold_damage_per_slot_above_base (int, default 5): per-upcast-
        level bonus. Reads cast level from state.current_attack.
        chosen_slot_level and the action's spell_slot_level.

    The marker uses lifetime=until_short_rest as a fallback (RAW: 1-
    hour duration — engine treats as "short rest" for cleanup since
    we don't model true 1-hour timers). The marker is also auto-
    cleared by `_damage` when the AoA-bearer's temp HP drops to 0
    from a hit (RAW: the spell ends when the temp HP is depleted).
    """
    caster = (state.current_attack or {}).get("actor") or \
              state.current_actor()
    if caster is None:
        raise ValueError("armor_of_agathys_arm requires a current actor")

    cold_damage = int(params.get("cold_damage", 5))
    per_slot_bonus = int(params.get(
        "cold_damage_per_slot_above_base", 0))
    if per_slot_bonus > 0:
        chosen_level = int(state.current_attack.get(
            "chosen_slot_level") or 0)
        action = state.current_attack.get("action") or {}
        base_level = int(action.get("spell_slot_level", 1))
        if chosen_level > base_level:
            cold_damage += (chosen_level - base_level) * per_slot_bonus

    action = (state.current_attack or {}).get("action") or {}
    action_id = action.get("id", "a_armor_of_agathys")
    # Existing marker for this caster? Re-cast replaces (RAW: re-
    # casting the spell while it's active overwrites with new amounts).
    caster.active_modifiers = [
        m for m in caster.active_modifiers
        if m.get("primitive") != "armor_of_agathys_active"
    ]
    entry = {
        "primitive": "armor_of_agathys_active",
        "params": {"cold_damage": cold_damage},
        "lifetime": "until_short_rest",
        "source": {
            "type": "spell",
            "id": action_id,
            "action_id": action_id,
            "caster_id": caster.id,
            "named_effect": "armor_of_agathys",
        },
        "applied_at_round": state.round,
        "owner_id": caster.id,
    }
    caster.active_modifiers.append(entry)
    state.event_log.append({
        "event": "armor_of_agathys_armed",
        "caster": caster.id,
        "cold_damage": cold_damage,
    })


def _hex_curse(params: dict, state: CombatState,
                  bus: EventBus) -> None:
    """Hex (PR #90): place a curse on the target. Registers a
    weapon_damage_bonus modifier on the caster gated to attacks
    against this specific target via the `target_is(<id>)`
    when-clause atom (engine.core.modifiers._eval_weapon_damage_when).

    Params:
      - value (int, default 3): flat bonus damage per hit. Defaults
        to 3 (avg of 1d6 ≈ 3.5, floored to integer); per-roll d6
        modeling is deferred alongside Bless / Divine Favor.

    Reads:
      - state.current_attack.target — the cursed creature (id used
        in the when-clause substitution)
      - state.current_attack.actor — the caster (modifier owner)
      - state.current_attack.action — for action_id (source tag)

    The modifier has lifetime=until_short_rest as a fallback; real
    cleanup runs via end_concentration scrubbing modifiers tagged
    with caster_id + action_id (PR #43 existing pattern).
    """
    caster = (state.current_attack or {}).get("actor") or \
              state.current_actor()
    target = (state.current_attack or {}).get("target")
    if caster is None or target is None:
        raise ValueError("hex_curse requires a current caster + target")
    value = int(params.get("value", 3))
    action = (state.current_attack or {}).get("action") or {}
    action_id = action.get("id", "a_hex")
    # Substitute the target id into the when-clause so future attacks
    # by the caster against this specific creature will pick up the
    # bonus damage. The query reads state.current_attack.target.id
    # at attack-time and matches against this substituted id.
    when_clause = f"target_is({target.id})"
    entry = {
        "primitive": "weapon_damage_bonus",
        "params": {
            "target": "self",
            "value": value,
            "when": when_clause,
        },
        "lifetime": "until_short_rest",
        "source": {
            "type": "spell",
            "id": action_id,
            "action_id": action_id,
            "caster_id": caster.id,
            "named_effect": "hex",
            "cursed_target_id": target.id,
        },
        "applied_at_round": state.round,
        "owner_id": caster.id,
    }
    caster.active_modifiers.append(entry)
    state.event_log.append({
        "event": "hex_curse_applied",
        "caster": caster.id,
        "target": target.id,
        "value": value,
    })


def _hunters_mark_mark(params: dict, state: CombatState,
                          bus: EventBus) -> None:
    """Hunter's Mark (PR #91): mark the target as the Ranger's quarry.

    Mechanically identical to _hex_curse — registers a target-specific
    weapon_damage_bonus on the caster gated via the `target_is(<id>)`
    when-clause atom. Kept as a separate primitive (rather than aliased
    to _hex_curse) so:
      - Each spell has its own named_effect tag for cross-caster dedup
        (a Ranger and a Warlock could both ride a single target with
        Hunter's Mark + Hex stacking correctly — RAW: different
        named effects don't dedup each other)
      - Each spell's own event_log entry is distinguishable in
        telemetry / debugging
      - Future divergence (e.g., Hunter's Mark gaining favored-target
        Perception tracking) can land without touching Hex

    Params:
      - value (int, default 3): flat bonus damage per hit. Defaults
        to 3 (avg of 1d6 ≈ 3.5, floored to integer); same v1
        simplification as Bless / Divine Favor / Searing Smite / Hex.
    """
    caster = (state.current_attack or {}).get("actor") or \
              state.current_actor()
    target = (state.current_attack or {}).get("target")
    if caster is None or target is None:
        raise ValueError(
            "hunters_mark_mark requires a current caster + target")
    value = int(params.get("value", 3))
    action = (state.current_attack or {}).get("action") or {}
    action_id = action.get("id", "a_hunters_mark")
    when_clause = f"target_is({target.id})"
    entry = {
        "primitive": "weapon_damage_bonus",
        "params": {
            "target": "self",
            "value": value,
            "when": when_clause,
        },
        "lifetime": "until_short_rest",
        "source": {
            "type": "spell",
            "id": action_id,
            "action_id": action_id,
            "caster_id": caster.id,
            "named_effect": "hunters_mark",
            "marked_target_id": target.id,
        },
        "applied_at_round": state.round,
        "owner_id": caster.id,
    }
    caster.active_modifiers.append(entry)
    state.event_log.append({
        "event": "hunters_mark_applied",
        "caster": caster.id,
        "target": target.id,
        "value": value,
    })


def _forced_movement(params: dict, state: CombatState,
                        bus: EventBus) -> None:
    """Push the current attack's target straight away from the actor
    (PR #106 — Repelling Blast invocation; future generic shove / pull
    effects).

    Reads actor + target from state.current_attack (the same context
    the `damage` step reads). Pushes the target up to `distance_ft`
    feet (default 10) directly away from the actor via
    geometry.push_creature, which snaps to the 8-direction vector and
    moves in 5-ft steps.

    Params:
      - distance_ft (int, default 10): max push distance.

    RAW size gate (shared with the Push weapon mastery, PR #65): only
    Large-or-smaller creatures can be moved; Huge / Gargantuan targets
    are immune and a skipped event is logged.

    Typically gated `when: combat.attack_state == hit` in the pipeline
    so it only fires on a landed hit — but the primitive itself is
    direction-only and harmless to call on a miss (the caller decides).

    No-op (logged) if there's no current target, or actor and target
    share a square (no defined push direction).
    """
    actor = (state.current_attack or {}).get("actor") or \
              state.current_actor()
    target = (state.current_attack or {}).get("target")
    if actor is None or target is None:
        state.event_log.append({
            "event": "forced_movement_skipped",
            "reason": "no_actor_or_target",
        })
        return
    distance = int(params.get("distance_ft", 10))
    from engine.core.geometry import push_creature
    from engine.core.sizes import PUSH_SIZES, normalize_size
    target_size = normalize_size(getattr(target, "size", None))
    if target_size not in PUSH_SIZES:
        state.event_log.append({
            "event": "forced_movement_skipped",
            "actor": actor.id,
            "target": target.id,
            "reason": "size_immune",
            "target_size": target_size,
        })
        return
    pre_pos = target.position
    pushed_ft = push_creature(actor, target, distance)
    state.event_log.append({
        "event": "forced_movement_applied",
        "actor": actor.id,
        "target": target.id,
        "pushed_ft": pushed_ft,
        "from": list(pre_pos),
        "to": list(target.position),
    })


def _searing_smite_arm(params: dict, state: CombatState,
                          bus: EventBus) -> None:
    """Arm the caster with Searing Smite's one-shot rider (PR #89).

    Called from f_searing_smite's cast pipeline. Reads the cast slot
    level from state.current_attack.chosen_slot_level (set by
    pipeline.execute for upcasted casts) and the caster's spell save
    DC from the action's `spell_save_dc` param OR the caster's CHA-
    based default (8 + PB + CHA mod).

    The marker modifier is registered with `lifetime: until_short_rest`
    + source tagged with caster_id + action_id, so the existing
    concentration-end / short-rest cleanup paths scrub it correctly
    if the rider never fires.
    """
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("searing_smite_arm requires a current actor")
    # Cast slot level (default 1 = base level; upcasted casts set
    # higher in state.current_attack via pipeline.execute)
    slot_level = int((state.current_attack or {}).get(
        "chosen_slot_level") or 1)
    # Spell save DC: param override OR caster's CHA-based DC
    if "dc" in params:
        dc = int(params["dc"])
    else:
        dc = _caster_spell_save_dc(actor)
    action = (state.current_attack or {}).get("action") or {}
    action_id = action.get("id", "a_searing_smite")
    from engine.core.searing_smite import register_armed
    register_armed(actor, slot_level=slot_level, spell_save_dc=dc,
                     action_id=action_id, state=state)


def _ensnaring_strike_arm(params: dict, state: CombatState,
                             bus: EventBus) -> None:
    """Arm the caster with Ensnaring Strike's one-shot rider (PR #110).

    Called from f_ensnaring_strike's cast pipeline. Mirrors
    _searing_smite_arm but with no upcast-damage tracking (Ensnaring
    deals no direct hit damage) — only the spell save DC is cached.
    The DC is the caster's spellcasting-ability-based save DC (WIS for
    Ranger via the generalized _caster_spell_save_dc), or a `dc` param
    override.
    """
    actor = (state.current_attack or {}).get("actor") or \
        state.current_actor()
    if actor is None:
        raise ValueError("ensnaring_strike_arm requires a current actor")
    dc = int(params["dc"]) if "dc" in params else _caster_spell_save_dc(actor)
    action = (state.current_attack or {}).get("action") or {}
    action_id = action.get("id", "a_ensnaring_strike")
    from engine.core.ensnaring_strike import register_armed
    register_armed(actor, spell_save_dc=dc, action_id=action_id,
                     state=state)


def _blinding_smite_arm(params: dict, state: CombatState,
                           bus: EventBus) -> None:
    """Arm the caster with Blinding Smite's one-shot rider.

    Called from f_blinding_smite's cast pipeline. 3rd-level spell;
    reads cast slot level from state.current_attack.chosen_slot_level
    and the caster's CHA-based spell save DC. Mirrors _searing_smite_arm.
    """
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("blinding_smite_arm requires a current actor")
    slot_level = int((state.current_attack or {}).get(
        "chosen_slot_level") or 3)
    if "dc" in params:
        dc = int(params["dc"])
    else:
        dc = _caster_spell_save_dc(actor)
    action = (state.current_attack or {}).get("action") or {}
    action_id = action.get("id", "a_blinding_smite")
    from engine.core.blinding_smite import register_armed
    register_armed(actor, slot_level=slot_level, spell_save_dc=dc,
                     action_id=action_id, state=state)


def _wrathful_smite_arm(params: dict, state: CombatState,
                           bus: EventBus) -> None:
    """Arm the caster with Wrathful Smite's one-shot rider.

    Called from f_wrathful_smite's cast pipeline. 1st-level spell;
    reads cast slot level from state.current_attack.chosen_slot_level
    and the caster's CHA-based spell save DC. Mirrors _searing_smite_arm.
    """
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("wrathful_smite_arm requires a current actor")
    slot_level = int((state.current_attack or {}).get(
        "chosen_slot_level") or 1)
    if "dc" in params:
        dc = int(params["dc"])
    else:
        dc = _caster_spell_save_dc(actor)
    action = (state.current_attack or {}).get("action") or {}
    action_id = action.get("id", "a_wrathful_smite")
    from engine.core.wrathful_smite import register_armed
    register_armed(actor, slot_level=slot_level, spell_save_dc=dc,
                     action_id=action_id, state=state)


def _thunderous_smite_arm(params: dict, state: CombatState,
                             bus: EventBus) -> None:
    """Arm the caster with Thunderous Smite's one-shot rider.

    Called from f_thunderous_smite's cast pipeline. 1st-level spell;
    reads cast slot level from state.current_attack.chosen_slot_level
    and the caster's CHA-based spell save DC. Mirrors _searing_smite_arm.
    """
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("thunderous_smite_arm requires a current actor")
    slot_level = int((state.current_attack or {}).get(
        "chosen_slot_level") or 1)
    if "dc" in params:
        dc = int(params["dc"])
    else:
        dc = _caster_spell_save_dc(actor)
    action = (state.current_attack or {}).get("action") or {}
    action_id = action.get("id", "a_thunderous_smite")
    from engine.core.thunderous_smite import register_armed
    register_armed(actor, slot_level=slot_level, spell_save_dc=dc,
                     action_id=action_id, state=state)


def _hail_of_thorns_arm(params: dict, state: CombatState,
                           bus: EventBus) -> None:
    """Arm the caster with Hail of Thorns' one-shot ranged rider.

    Called from f_hail_of_thorns' cast pipeline. 1st-level Ranger
    spell; reads cast slot level from chosen_slot_level and the
    caster's WIS-based spell save DC. Mirrors _searing_smite_arm; the
    trigger (DEX-save thorn burst around the struck target) lives in
    engine.core.hail_of_thorns.
    """
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("hail_of_thorns_arm requires a current actor")
    slot_level = int((state.current_attack or {}).get(
        "chosen_slot_level") or 1)
    if "dc" in params:
        dc = int(params["dc"])
    else:
        dc = _caster_spell_save_dc(actor)
    action = (state.current_attack or {}).get("action") or {}
    action_id = action.get("id", "a_hail_of_thorns")
    from engine.core.hail_of_thorns import register_armed
    register_armed(actor, slot_level=slot_level, spell_save_dc=dc,
                     action_id=action_id, state=state)


def _wild_shape_transform(params: dict, state: CombatState,
                            bus: EventBus) -> None:
    """Druid Wild Shape — transform into a Beast form (form system).

    Reads the target beast template id from `params.form` (a monster id
    like 'm_wolf'; default 'm_wolf') from the content registry and calls
    forms.assume_form with the wild_shape policy. The Wild Shape use is
    consumed by the action's feature_use gate. AI form-selection (which
    of the druid's known forms, and when) is deferred to the AI lane."""
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("wild_shape_transform requires a current actor")
    form_id = params.get("form", "m_wolf")
    registry = state.content_registry
    if registry is None:
        raise ValueError("wild_shape_transform requires a content registry")
    form_template = registry.get("monster", form_id)
    from engine.core import forms
    forms.assume_form(actor, form_template, "wild_shape", {
        "effect": "wild_shape", "caster_id": actor.id,
        "action_id": "a_wild_shape",
        "reversion": ["hp_zero", "incapacitated", "voluntary"],
    }, state)


def _wild_shape_revert(params: dict, state: CombatState,
                         bus: EventBus) -> None:
    """Leave Wild Shape early (Bonus Action) — revert to true form."""
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("wild_shape_revert requires a current actor")
    from engine.core import forms
    if forms.is_transformed(actor):
        forms.revert_form(actor, state, reason="voluntary")


def _shape_shift(params: dict, state: CombatState, bus: EventBus) -> None:
    """Monster Shape-Shift (2024 'Change Shape') — rides the form core's
    stat-preserving `change_shape` policy.

    RAW: the creature's game statistics, OTHER THAN ITS SIZE, are the same
    in each form. So this changes only `size` (+ `creature_type` if the
    form declares one) and keeps HP / AC / abilities / attacks. Params:
      - form_id: a label for the assumed form (e.g. 'wolf', 'humanoid')
      - size: the form's size (e.g. 'large', 'medium')
      - creature_type: optional new creature type
    A minimal form_template is built from these (no combat block — the
    `change_shape` policy ignores it). Reverting at 0 HP lets the creature
    die in its true size rather than restoring a stale HP snapshot."""
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("shape_shift requires a current actor")
    form_id = params.get("form_id", "alternate_form")
    form_template = {"id": form_id}
    if params.get("size"):
        form_template["size"] = params["size"]
    if params.get("creature_type"):
        form_template["creature_type"] = params["creature_type"]
    from engine.core import forms
    forms.assume_form(actor, form_template, "change_shape", {
        "effect": "shape_shift", "caster_id": actor.id,
        "reversion": ["hp_zero", "voluntary"],
    }, state)


def _shape_shift_revert(params: dict, state: CombatState,
                          bus: EventBus) -> None:
    """Return to true form (Shape-Shift) — restores true size, keeps HP."""
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("shape_shift_revert requires a current actor")
    from engine.core import forms
    if forms.is_transformed(actor):
        forms.revert_form(actor, state, reason="voluntary")


def _swallow_apply(params: dict, state: CombatState, bus: EventBus) -> None:
    """Swallow the current_attack target (Behir / Purple Worm / cube).

    Runs in the `on_fail` of a Swallow action's DEX forced_save (after the
    Blinded/Restrained apply_condition steps). Sets Total Cover + records
    the swallow (swallower id + ongoing-acid spec) on the target via
    engine.core.swallow. Params: acid_dice (default '6d6'), acid_type
    (default 'acid')."""
    swallower = (state.current_attack or {}).get("actor")
    target = (state.current_attack or {}).get("target")
    if swallower is None or target is None:
        raise ValueError("swallow_apply needs a current actor + target")
    from engine.core import swallow
    swallow.apply(swallower, target, params, state)


def _summon(params: dict, state: CombatState, bus: EventBus) -> None:
    """Summon creatures into the fight (Wraith Create Specter, conjure
    spells). Params: monster (template id, required), count (default 1),
    max_total (optional capacity cap). The summoner is the current actor;
    summons join its side and the turn order. Rides engine.core.summoning."""
    summoner = (state.current_attack or {}).get("actor") or state.current_actor()
    if summoner is None:
        raise ValueError("summon requires a current actor")
    monster_id = params.get("monster")
    if not monster_id:
        raise ValueError("summon requires a `monster` template id")
    from engine.core import summoning
    # Caster-aware count / cap (Animate Objects: count = spellcasting modifier).
    new_actors = summoning.summon(
        summoner, monster_id, state,
        count=summoning.resolve_summon_count(params, summoner),
        max_total=summoning.resolve_summon_max_total(params, summoner))
    # Tie the summons to the caster's CONCENTRATION if this is a concentration
    # spell (Bigby's Hand, Animate Objects) — they vanish when it ends.
    action = (state.current_attack or {}).get("action") or {}
    if action.get("concentration") and action.get("id"):
        for a in new_actors:
            a.summon_concentration = {"caster_id": summoner.id,
                                       "action_id": action.get("id")}
    # Caster-aware attack bonus (Animate Objects / Bigby's Hand: the summoned
    # creature attacks with the CASTER's spell attack modifier, not the static
    # stat-block fallback).
    if params.get("attack_bonus_from") == "caster_spell_attack":
        summoning.apply_caster_attack_bonus(new_actors, summoner)


def _polymorph_target(params: dict, state: CombatState,
                        bus: EventBus) -> None:
    """Polymorph the current_attack target into a Beast (control spell).

    Runs in the `on_fail` of the spell's WIS forced_save (a successful save
    means no effect; Legendary Resistance can spend a charge to succeed —
    handled by _forced_save). On a failure, the target assumes the beast
    form under the `polymorph` merge policy: all stats replaced by the
    beast's, HP becomes the beast's pool, and damage beyond it carries over
    to the true form on revert (carry_overflow). The form is sustained by
    the CASTER's concentration — end_concentration reverts it — and also
    reverts when the beast form drops to 0 HP (the _damage death hook).

    Params: `form` (a Beast monster id, default 'm_giant_toad' — a low-
    threat 'neutralize' choice; the caster's tactical form pick is the AI
    lane's job, capped at the target's CR per RAW, deferred)."""
    caster = (state.current_attack or {}).get("actor")
    target = (state.current_attack or {}).get("target")
    if caster is None or target is None:
        raise ValueError("polymorph_target needs a current actor + target")
    form_id = params.get("form", "m_giant_toad")
    registry = state.content_registry
    if registry is None:
        raise ValueError("polymorph_target requires a content registry")
    form_template = registry.get("monster", form_id)
    action_id = (state.current_attack.get("action") or {}).get("id", "a_polymorph")
    from engine.core import forms
    forms.assume_form(target, form_template, "polymorph", {
        "effect": "polymorph", "caster_id": caster.id,
        "action_id": action_id,
        "reversion": ["hp_zero", "concentration_end"],
    }, state)


def _place_barrier(params: dict, state: CombatState, bus: EventBus) -> None:
    """Place a Wall of Force-style barrier between the caster and the
    current target (positional-barrier system, Phase C).

    Creates a single wall PANEL perpendicular to the caster->target axis,
    sitting one half-square in front of the target on the caster's side, so
    it cuts the target off from the caster's side of the field. The wall
    blocks movement and line of effect (ranged attacks + AoE spread can't
    cross it) while staying sight-transparent — exactly like Wall of Force.
    It rides the Phase B wiring (move_toward / _attack_roll /
    _resolve_save_targets) for free; nothing spell-specific is needed there.

    The wall is stamped with flags {effect, caster_id, action_id} so
    end_concentration scrubs it when the caster drops concentration (the
    same teardown channel as persistent_auras).

    Params:
      length_ft  total panel length, centered on the axis (default 30).
      move       block movement?  (default True)
      sight      block vision?     (default False — Wall of Force is clear)
      effect     provenance tag    (default 'wall_of_force')
    """
    caster = (state.current_attack or {}).get("actor") or state.current_actor()
    target = (state.current_attack or {}).get("target")
    if caster is None or target is None:
        raise ValueError("place_barrier needs a current actor + target")
    action_id = (state.current_attack.get("action") or {}).get(
        "id", "a_wall_of_force")

    from engine.core.geometry import (
        Wall, Sphere, unit_direction, SQUARE_SIZE_FT,
        WALL_BLOCK_NORMAL, WALL_BLOCK_NONE,
    )

    # Sphere form (the trapping "microwave" cage): a closed circle centered ON
    # the target. It can't move or attack across the surface (effective speed
    # 0) and is under total cover both ways — but a damaging zone sharing the
    # center is inside WITH it, so the trapped creature takes recurring damage
    # it can't escape or answer. radius_ft default 10 (RAW max 10-ft radius).
    if str(params.get("shape", "panel")).lower() == "sphere":
        radius = int(params.get("radius_ft", 10)) / SQUARE_SIZE_FT
        gap = bool(params.get("gap", False))
        sphere = Sphere(
            center=(float(target.position[0]), float(target.position[1])),
            radius=radius,
            move=(WALL_BLOCK_NORMAL if params.get("move", True)
                  else WALL_BLOCK_NONE),
            sight=(WALL_BLOCK_NORMAL if params.get("sight", False)
                   else WALL_BLOCK_NONE),
            gap=gap,
            flags={"effect": params.get("effect", "wall_of_force"),
                   "caster_id": caster.id, "action_id": action_id},
        )
        state.walls.append(sphere)
        state.event_log.append({
            "event": "barrier_placed", "actor": caster.id,
            "effect": sphere.flags["effect"], "shape": "sphere",
            "center": list(sphere.center), "radius": radius,
            "action_id": action_id,
        })
        return

    cx, cy = caster.position
    tx, ty = target.position
    dx, dy = unit_direction((cx, cy), (tx, ty))
    if (dx, dy) == (0, 0):
        dx, dy = (1, 0)   # caster + target stacked: fall back to east-facing
    # Center the panel a half-square in front of the target on the caster
    # side, so the caster->target center-to-center segment crosses it as a
    # clean transversal (actors are integer centers; this sits on the
    # half-integer boundary).
    wcx = tx - 0.5 * dx
    wcy = ty - 0.5 * dy
    px, py = (-dy, dx)   # perpendicular to the facing axis
    half = (int(params.get("length_ft", 30)) / SQUARE_SIZE_FT) / 2.0
    wall = Wall(
        c=(wcx - half * px, wcy - half * py,
           wcx + half * px, wcy + half * py),
        move=WALL_BLOCK_NORMAL if params.get("move", True) else WALL_BLOCK_NONE,
        sight=WALL_BLOCK_NORMAL if params.get("sight", False) else WALL_BLOCK_NONE,
        flags={"effect": params.get("effect", "wall_of_force"),
               "caster_id": caster.id, "action_id": action_id},
    )
    state.walls.append(wall)
    state.event_log.append({
        "event": "barrier_placed", "actor": caster.id,
        "effect": wall.flags["effect"], "c": list(wall.c),
        "action_id": action_id,
    })


def _grant_bardic_inspiration(params: dict, state: CombatState,
                                bus: EventBus) -> None:
    """Grant a Bardic Inspiration die to an ally (current_attack.target).

    The die size comes from the granting Bard's template.bardic_die
    (d6→d12 by level; default d6). The Bardic Inspiration use is consumed
    by the action's feature_use gate (feature_use:
    bardic_inspiration_uses_remaining) at execution time, not here — this
    primitive just registers the held-die marker on the recipient."""
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    target = (state.current_attack or {}).get("target")
    if actor is None or target is None:
        raise ValueError("grant_bardic_inspiration needs an actor + target")
    die = str((actor.template or {}).get("bardic_die", "d6"))
    from engine.core.bardic_inspiration import register_inspiration_die
    # College of Valor: tag the die so Defense + Offense hooks activate.
    combat_insp = "f_combat_inspiration" in (
        (actor.template or {}).get("features_known") or [])
    register_inspiration_die(target, die, actor.id, state,
                             combat_inspiration=combat_insp)
    # Agile Strikes (College of Dance L3): expending a Bardic Inspiration use
    # lets a Dance Bard make one Unarmed Strike as part of this Bonus Action.
    from engine.core.college_of_dance import try_agile_strike
    try_agile_strike(actor, state, bus)


def _cutting_words_resolve(params: dict, state: CombatState,
                             bus: EventBus) -> dict:
    """College of Lore Cutting Words (reaction). The Bard spends a Bardic
    Inspiration use (consumed by the reaction's feature_use gate) to roll
    their Bardic die and subtract it from an enemy's attack.

    Modeled — like Shield — as an AC bump on the defender, registered
    during the attack_roll_pending reaction so _attack_roll's
    post-reaction AC re-query can turn the hit into a miss. The bump uses
    `per_single_attack` lifetime, so it affects ONLY the triggering
    attack and is cleared at attack_complete (unlike Shield's
    until-next-turn +5).

    v1 scope: attack rolls only. RAW Cutting Words also subtracts from
    a target's ability checks and damage rolls — documented follow-ons."""
    rng = _get_rng(state, bus)
    bard = (state.current_attack or {}).get("actor")
    defender = (state.current_attack or {}).get("target")
    if bard is None or defender is None:
        return {"applied": 0}
    die = str((bard.template or {}).get("bardic_die", "d6"))
    from engine.core.bardic_inspiration import die_max
    roll = rng.randint(1, die_max(die))
    defender.active_modifiers.append({
        "primitive": "attack_modifier",
        "params": {"modifier": "ac_modifier", "value": roll},
        "lifetime": "per_single_attack",
        "source": {"type": "feature", "id": "f_cutting_words",
                     "named_effect": "cutting_words", "caster_id": bard.id},
        "applied_at_round": state.round,
        "owner_id": defender.id,
    })
    state.event_log.append({
        "event": "cutting_words_resolved", "bard": bard.id,
        "defender": defender.id, "die": die, "roll": roll,
    })
    return {"applied": roll}


def _caster_spell_save_dc(actor: Actor) -> int:
    """Compute the actor's spell save DC: 8 + proficiency_bonus +
    spellcasting_ability_modifier.

    Generalized in PR #110 to read `template.spellcasting_ability`
    (stamped by pc_schema from the class's spellcasting block — PR #104
    for Paladin/CHA, PR #107 for Ranger/WIS) so the DC uses the right
    ability per class. Falls back to CHA when unstamped, preserving the
    PR #89 Paladin behavior. The 3-letter abbreviation is just the
    first 3 chars of the full ability name (wisdom→wis, charisma→cha,
    intelligence→int, etc. — all six map correctly).

    Monster override: a stat block may declare an explicit `spell_save_dc`
    (from its `spellcasting.save_dc`, stamped at load by
    monster_spellcasting). When present it's used verbatim — the 2024
    monster format lists a fixed DC, and this avoids depending on the
    monster's ability scores reproducing it via the formula."""
    explicit = (actor.template or {}).get("spell_save_dc")
    if explicit is not None:
        return int(explicit)
    pb = int((actor.template.get("cr") or {}).get("proficiency_bonus", 2))
    ability = ((actor.template or {}).get("spellcasting_ability")
                 or "charisma")
    abbr = str(ability)[:3]
    score = (actor.abilities.get(abbr) or {}).get("score", 10)
    mod = (score - 10) // 2
    return 8 + pb + mod


def _melee_retaliation(params: dict, state: CombatState,
                         bus: EventBus) -> None:
    """Reaction primitive: make one melee weapon attack against the
    creature that damaged the reactor (Barbarian Berserker Retaliation,
    L10). try_use_reaction sets current_attack.actor = reactor and
    current_attack.target = the attacker (via the
    _reaction_target_is_attacker flag); the swing routes through the
    reactor's real weapon so Rage damage / masteries apply."""
    ctx = state.current_attack or {}
    reactor = ctx.get("actor")
    attacker = ctx.get("target")
    if reactor is None or attacker is None:
        return
    from engine.core.reactions import execute_retaliation_strike
    execute_retaliation_strike(reactor, attacker, state, bus)


def _ready_action(params: dict, state: CombatState, bus: EventBus) -> None:
    """Primitive that records a readied action on the actor (PR #86).

    Params:
      - sub_action_id (str, required): the action id to fire on trigger
      - trigger (str, required): trigger key (see KNOWN_TRIGGERS in
        engine/core/ready_action.py)
      - trigger_params (dict, optional): trigger-specific params

    The action slot is consumed by the normal pipeline.execute path
    (Ready is a full Action). The reaction slot is NOT pre-consumed
    here — it's consumed when the readied action actually fires.
    """
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("ready_action requires a current actor")
    sub_action_id = params.get("sub_action_id")
    trigger = params.get("trigger")
    if not sub_action_id or not trigger:
        raise ValueError(
            "ready_action requires sub_action_id + trigger params"
        )
    from engine.core.ready_action import register
    register(actor, sub_action_id, trigger, state,
              trigger_params=params.get("trigger_params"))


def _rage_start(params: dict, state: CombatState, bus: EventBus) -> None:
    """Primitive that flips the actor into Rage (PR #71).

    Invoked by the a_rage bonus action's pipeline. The action's
    feature_use:rage_uses_remaining gate consumes the charge at
    execution time; this primitive just flips state and stamps the
    damage bonus. See engine/core/rage.py for the level tables and
    the state-transition rules.
    """
    actor = (state.current_attack or {}).get("actor") or state.current_actor()
    if actor is None:
        raise ValueError("rage_start requires a current actor")
    from engine.core.rage import enter_rage
    enter_rage(actor, state)


def _resolve_modifier(source: str, actor: Actor) -> int:
    """Resolve a modifier-source token against an actor (used by heal,
    by some on-hit damage riders, and class-level scaling)."""
    _ABILITY_MOD_SOURCES = {
        "actor.str_mod": "str", "actor.dex_mod": "dex",
        "actor.con_mod": "con", "actor.int_mod": "int",
        "actor.wis_mod": "wis", "actor.cha_mod": "cha",
    }
    if source in _ABILITY_MOD_SOURCES:
        ability = _ABILITY_MOD_SOURCES[source]
        return ability_modifier(actor.abilities.get(ability, {}).get("score", 10))
    if source.startswith("actor.") and source.endswith("_level"):
        cls_name = source[len("actor."):-len("_level")]
        return actor.template.get("levels", {}).get(cls_name, 1)
    raise ValueError(f"Unknown modifier source: {source!r}")


def _resolve_dc(params: dict, state: CombatState) -> int:
    """Resolve a DC value from params."""
    if "dc" in params:
        return int(params["dc"])
    dc_source = params.get("dc_source", "")
    if dc_source == "caster_spell_save_dc":
        # 8 + spellcasting_mod + PB. PR #104: read the caster's actual
        # spellcasting ability (stamped by pc_schema as
        # template.spellcasting_ability — e.g. 'charisma' for Paladin/
        # Warlock, 'intelligence' for Wizard, 'wisdom' for Cleric).
        # Falls back to INT for legacy fixtures without the stamp
        # (preserves prior behavior for Hold Person-style INT casters).
        actor = state.current_attack.get("actor") or state.current_actor()
        if actor:
            ability = (actor.template.get("spellcasting_ability")
                         or "intelligence")
            short = {"strength": "str", "dexterity": "dex",
                       "constitution": "con", "intelligence": "int",
                       "wisdom": "wis", "charisma": "cha"}.get(
                           ability, "int")
            mod = ability_modifier(
                actor.abilities.get(short, {}).get("score", 10))
            pb = actor.template.get("cr", {}).get("proficiency_bonus", 2)
            return 8 + mod + pb
        return 13
    if dc_source == "martial_save_dc":
        # 8 + PB + a governing ability mod (default STR). For martial
        # features whose save DC is "8 + ability + Proficiency Bonus"
        # rather than a spell save DC — e.g. Barbarian Intimidating
        # Presence (STR). The governing ability is read from the
        # forced_save's `dc_ability` param so other martial features can
        # key off CON/DEX/etc. without a new dc_source.
        actor = state.current_attack.get("actor") or state.current_actor()
        if actor:
            ability = params.get("dc_ability", "strength")
            short = {"strength": "str", "dexterity": "dex",
                       "constitution": "con", "intelligence": "int",
                       "wisdom": "wis", "charisma": "cha"}.get(
                           str(ability), "str")
            mod = ability_modifier(
                actor.abilities.get(short, {}).get("score", 10))
            pb = actor.template.get("cr", {}).get("proficiency_bonus", 2)
            return 8 + mod + pb
        return 13
    if dc_source.startswith("fixed:"):
        return int(dc_source[len("fixed:"):])
    return 13  # default


def _resolve_save_targets(params: dict, state: CombatState) -> list[Actor]:
    """Resolve the targets that must save."""
    affected = params.get("affected", "current_target")
    if affected == "current_target":
        target = state.current_attack.get("target") or state.current_actor()
        return [target] if target else []
    if affected in ("all_creatures_in_area", "enemies_in_area"):
        # AoE-aware path: dispatch on area.shape using state.current_attack's
        # area_origin (sphere) or area_origin + area_direction (cone, line).
        # Living creatures only. 'all_creatures_in_area' includes allies
        # (friendly fire is RAW); 'enemies_in_area' filters to the caster's
        # enemies — the "each creature of your choice" spells (Word of
        # Radiance), where the caster always chooses only foes.
        # Legacy fallback (no area declared) returns all living enemies.
        actor = state.current_actor() or state.current_attack.get("actor")
        if actor is None:
            return []
        action = state.current_attack.get("action") or {}
        area = action.get("area") or {}
        shape = (area.get("shape") or "sphere").lower()
        origin = state.current_attack.get("area_origin")
        direction = state.current_attack.get("area_direction")
        living = [a for a in state.encounter.actors if a.is_alive()]

        members: list[Actor] | None = None
        if origin is not None:
            if shape == "sphere":
                radius_ft = area.get("radius_ft")
                if radius_ft is not None:
                    from engine.core.geometry import actors_in_radius
                    members = actors_in_radius(tuple(origin), int(radius_ft),
                                                 living)
            elif shape == "emanation":
                # A self-centered Emanation is a sphere of `size_ft`
                # radius originating from the actor (origin == caster's
                # position). Used by Barbarian Intimidating Presence and
                # the emanation cantrips (Thunderclap, Word of Radiance).
                # 2024 Emanation rule: the originator is NOT included in
                # its own area.
                size_ft = area.get("size_ft")
                if size_ft is not None:
                    from engine.core.geometry import actors_in_radius
                    members = [m for m in actors_in_radius(
                                   tuple(origin), int(size_ft), living)
                               if m.id != actor.id]
            elif shape == "cone":
                length_ft = area.get("length_ft")
                if length_ft is not None and direction is not None:
                    from engine.core.geometry import actors_in_cone
                    members = actors_in_cone(tuple(origin), tuple(direction),
                                               int(length_ft), living)
            elif shape == "line":
                length_ft = area.get("length_ft")
                width_ft = area.get("width_ft", 5)
                if length_ft is not None and direction is not None:
                    from engine.core.geometry import actors_in_line
                    members = actors_in_line(tuple(origin), tuple(direction),
                                               int(length_ft), int(width_ft),
                                               living)
        if members is not None:
            # Barrier occlusion: a creature whose line of effect from the
            # blast origin is broken by a wall (Wall of Force) is spared.
            # Gated — no walls leaves membership identical.
            _walls = getattr(state, "walls", None)
            if _walls:
                from engine.core.geometry import clear_line_of_effect
                members = clear_line_of_effect(tuple(origin), members, _walls)
            if affected == "enemies_in_area":
                members = [m for m in members if m.side != actor.side]
            return members
        # Legacy fallback: all living enemies (already enemies-only,
        # so it serves both affected modes)
        return [a for a in state.encounter.actors
                if a.side != actor.side and a.is_alive()]
    return []


def _short_ability(name: str) -> str:
    """Convert 'strength' / 'dexterity' / etc. to short keys."""
    mapping = {
        "strength": "str", "dexterity": "dex", "constitution": "con",
        "intelligence": "int", "wisdom": "wis", "charisma": "cha",
    }
    return mapping.get(name, name)


def _invoke_subprimitive(sub: dict, state: CombatState, bus: EventBus) -> Any:
    """Invoke a nested primitive call (e.g., on_fail inside forced_save)."""
    primitive_name = sub.get("primitive")
    if not primitive_name:
        return None
    # Look up via the module's registry — there's only one in the runner
    handler = _PRIMITIVE_HANDLERS.get(primitive_name)
    if handler is None:
        raise KeyError(f"Subprimitive lookup failed: {primitive_name!r}")
    return handler(sub.get("params") or {}, state, bus)


# Module-level RNG
_rng: _random_module.Random = _random_module.Random()


def set_rng(rng: _random_module.Random) -> None:
    global _rng
    _rng = rng


def get_rng() -> _random_module.Random:
    """The shared seeded RNG (set per-sim via set_rng). Lets decision-layer
    code that isn't handed an rng (e.g. the optimization-dial focus-fire roll)
    draw reproducibly from the same stream as every other combat roll."""
    return _rng


# ============================================================================
# Registry assembly + handler lookup table for subprimitives
# ============================================================================

_PRIMITIVE_HANDLERS: dict[str, Callable] = {}


def _populate_handler_table() -> None:
    """Populate the subprimitive lookup table eagerly at module load.

    Subprimitives (e.g., the on_fail array inside a forced_save call)
    are dispatched via this table rather than through the PrimitiveRegistry,
    so direct primitive calls (in tests + ad hoc) work even before a
    registry exists.
    """
    global _PRIMITIVE_HANDLERS
    _PRIMITIVE_HANDLERS = {
        "attack_roll": _attack_roll,
        "damage": _damage,
        "apply_condition": _apply_condition,
        "heal": _heal,
        "granted_action": _granted_action,
        "attack_modifier": _attack_modifier,
        "save_modifier": _save_modifier,
        "d20_test_modifier": _d20_test_modifier,
        "crit_modifier": _crit_modifier,
        "crit_threshold_modifier": _crit_threshold_modifier,
        "weapon_damage_bonus": _weapon_damage_bonus,
        "forced_save": _forced_save,
        "recurring_save": _recurring_save,
        "slot_recovery_partial": _slot_recovery_partial,
        "persistent_aura": _persistent_aura,
        "counterspell_resolve": _counterspell_resolve,
        "multiattack": _multiattack,
        "rage_start": _rage_start,
        "dash": _dash,
        "steady_aim": _steady_aim,
        "lay_on_hands": _lay_on_hands,
        "warrior_of_the_gods": _warrior_of_the_gods,
        "zealous_presence": _zealous_presence,
        "eagle_bound": _eagle_bound,
        "mantle_of_inspiration": _mantle_of_inspiration,
        "mantle_of_majesty_activate": _mantle_of_majesty_activate,
        "mantle_of_majesty_command": _mantle_of_majesty_command,
        "unbreakable_majesty_activate": _unbreakable_majesty_activate,
        "inspiring_movement": _inspiring_movement,
        "branches_pull": _branches_pull,
        "travel_teleport": _travel_teleport,
        "revivification_save": _revivification_save,
        "ready_action": _ready_action,
        "melee_retaliation": _melee_retaliation,
        "recurring_damage": _recurring_damage,
        "searing_smite_arm": _searing_smite_arm,
        "ensnaring_strike_arm": _ensnaring_strike_arm,
        "thunderous_smite_arm": _thunderous_smite_arm,
        "hail_of_thorns_arm": _hail_of_thorns_arm,
        "hex_curse": _hex_curse,
        "hunters_mark_mark": _hunters_mark_mark,
        "forced_movement": _forced_movement,
        "temp_hp_grant": _temp_hp_grant,
        "recurring_temp_hp": _recurring_temp_hp,
        "armor_of_agathys_arm": _armor_of_agathys_arm,
        "hp_max_grant": _hp_max_grant,
        "grant_speed": _grant_speed,
        "grant_bardic_inspiration": _grant_bardic_inspiration,
        "cutting_words_resolve": _cutting_words_resolve,
        "wild_shape_transform": _wild_shape_transform,
        "wild_shape_revert": _wild_shape_revert,
        "shape_shift": _shape_shift,
        "shape_shift_revert": _shape_shift_revert,
        "polymorph_target": _polymorph_target,
        "swallow_apply": _swallow_apply,
        "summon": _summon,
        "place_barrier": _place_barrier,
    }


def _all_primitives() -> list[Primitive]:
    implemented = [
        # v0 (skeleton)
        Primitive("attack_roll", _attack_roll, implemented=True),
        Primitive("damage", _damage, implemented=True),
        Primitive("apply_condition", _apply_condition, implemented=True),
        Primitive("heal", _heal, implemented=True),
        Primitive("granted_action", _granted_action, implemented=True),
        # v1 — Q5 unified modifiers
        Primitive("attack_modifier", _attack_modifier, implemented=True),
        Primitive("save_modifier", _save_modifier, implemented=True),
        Primitive("d20_test_modifier", _d20_test_modifier, implemented=True),
        Primitive("crit_modifier", _crit_modifier, implemented=True),
        Primitive("crit_threshold_modifier", _crit_threshold_modifier, implemented=True),
        # PR #88 — Weapon damage rider (Divine Favor; future Hex /
        # Hunter's Mark / Searing Smite). Registers an active_modifier
        # entry on the owner; read by _damage via
        # modifiers.query_weapon_damage_bonus.
        Primitive("weapon_damage_bonus", _weapon_damage_bonus, implemented=True),
        # v1 — Spell mechanics
        Primitive("forced_save", _forced_save, implemented=True),
        Primitive("recurring_save", _recurring_save, implemented=True),
        # PR #37 — slot restoration (Arcane Recovery, future Sorcerer
        # Flexible Casting / Warlock Pact Magic)
        Primitive("slot_recovery_partial", _slot_recovery_partial, implemented=True),
        # PR #43 — persistent self-anchored area effects (Spirit
        # Guardians, future Spiritual Weapon / Moonbeam / Cloud of
        # Daggers shape)
        Primitive("persistent_aura", _persistent_aura, implemented=True),
        # PR #46 — Counterspell resolution
        Primitive("counterspell_resolve", _counterspell_resolve,
                    implemented=True),
        # v1 — Monster mechanics
        Primitive("multiattack", _multiattack, implemented=True),
        # PR #71 — Barbarian Rage entry
        Primitive("rage_start", _rage_start, implemented=True),
        # PR #74 — generic Dash (used by Cunning Action; future:
        # generic main-slot Dash for all actors)
        Primitive("dash", _dash, implemented=True),
        # PR #80 — Rogue L3 Steady Aim (BA: advantage on next
        # attack + speed 0 rest of turn)
        Primitive("steady_aim", _steady_aim, implemented=True),
        # PR #83 — Paladin Lay on Hands (BA touch heal from pool)
        Primitive("lay_on_hands", _lay_on_hands, implemented=True),
        # Warrior of the Gods (Zealot L3) — BA self-heal from a d12 dice
        # pool. Must stay in sync with _populate_handler_table.
        Primitive("warrior_of_the_gods", _warrior_of_the_gods,
                    implemented=True),
        # Zealous Presence (Zealot L10) — BA that grants Advantage on
        # attacks + saves to up to 10 allies within 60 ft until the
        # Zealot's next turn. Must stay in sync with _populate_handler_table.
        Primitive("zealous_presence", _zealous_presence, implemented=True),
        # Eagle Bound (Wild Heart L3, Eagle aspect) — per-later-turn Bonus
        # Action: Dash + Disengage together while raging with Eagle active.
        Primitive("eagle_bound", _eagle_bound, implemented=True),
        # Mantle of Inspiration (Glamour L3) — BA: expend BI, grant up to
        # CHA-mod allies within 60 ft Temp HP = 2× the Bardic die roll.
        Primitive("mantle_of_inspiration", _mantle_of_inspiration,
                    implemented=True),
        # Mantle of Majesty (Glamour L6) — BA: cast Command free (activate
        # 1/long rest; sustained free Command each turn while active).
        Primitive("mantle_of_majesty_activate", _mantle_of_majesty_activate,
                    implemented=True),
        Primitive("mantle_of_majesty_command", _mantle_of_majesty_command,
                    implemented=True),
        # Unbreakable Majesty (Glamour L14) — BA: assume the majestic
        # presence (first hit each turn forces a CHA save or misses).
        Primitive("unbreakable_majesty_activate",
                    _unbreakable_majesty_activate, implemented=True),
        # Inspiring Movement (College of Dance L6) — reaction at an enemy's
        # turn end within 5 ft: reposition the Bard + an ally (no OAs).
        Primitive("inspiring_movement", _inspiring_movement, implemented=True),
        # Branches of the Tree (World Tree L6) — reaction at a creature's
        # turn start: STR save or teleport-pull adjacent + Speed 0.
        Primitive("branches_pull", _branches_pull, implemented=True),
        # Travel along the Tree (World Tree L14) — BA 60-ft teleport-to-engage
        # while raging.
        Primitive("travel_teleport", _travel_teleport, implemented=True),
        # Revivification (Zealot L14, Rage of the Gods reaction) — spends a
        # Rage use to restore a would-be-downed ally to Barbarian level HP.
        Primitive("revivification_save", _revivification_save,
                    implemented=True),
        # PR #86 — Ready Action (records a readied sub-action + trigger
        # onto the actor; fires when the trigger matches before the
        # actor's next turn).
        Primitive("ready_action", _ready_action, implemented=True),
        # Retaliation (Barbarian Berserker L10) — reaction primitive that
        # makes one melee weapon swing at the creature that damaged the
        # reactor. Must stay in sync with _populate_handler_table.
        Primitive("melee_retaliation", _melee_retaliation, implemented=True),
        # PR #89 — Recurring per-turn damage tick (Searing Smite burn,
        # future Heat Metal). Registers an entry in state.recurring_
        # damage; runner._resolve_recurring_damage fires at each
        # affected creature's turn-start.
        Primitive("recurring_damage", _recurring_damage, implemented=True),
        # PR #89 — Searing Smite arming primitive. Registers a one-
        # shot marker modifier on the caster; _damage fires the
        # rider on the caster's next melee weapon hit via
        # engine.core.searing_smite.try_apply_searing_smite_followup.
        Primitive("searing_smite_arm", _searing_smite_arm, implemented=True),
        # PR #110 — Ensnaring Strike arming primitive (Ranger). Twin of
        # searing_smite_arm: registers a one-shot marker on the caster;
        # _damage fires the rider on the caster's next weapon hit via
        # engine.core.ensnaring_strike.try_apply_ensnaring_strike_followup
        # (STR save → on fail co_ensnared). No bonus damage.
        Primitive("ensnaring_strike_arm", _ensnaring_strike_arm,
                    implemented=True),
        # Blinding Smite arming primitive (Paladin, 3rd-level). Same
        # pattern as searing_smite_arm: registers a one-shot marker;
        # _damage fires the rider (3d8 radiant + CON save -> Blinded).
        Primitive("blinding_smite_arm", _blinding_smite_arm,
                    implemented=True),
        # Wrathful Smite arming primitive (Paladin, 1st-level). Same
        # pattern: registers a one-shot marker; _damage fires the
        # rider (1d6 psychic + WIS save -> Frightened).
        Primitive("wrathful_smite_arm", _wrathful_smite_arm,
                    implemented=True),
        # Thunderous Smite arming primitive (Paladin, 1st-level).
        # Rider: 2d6 thunder bonus, STR save -> 10-ft push + Prone.
        Primitive("thunderous_smite_arm", _thunderous_smite_arm,
                    implemented=True),
        # Hail of Thorns arming primitive (Ranger, 1st-level). RANGED
        # rider: DEX-save thorn burst (Nd10 / half) around the struck
        # target — trigger lives in engine.core.hail_of_thorns.
        Primitive("hail_of_thorns_arm", _hail_of_thorns_arm,
                    implemented=True),
        # Bardic Inspiration — grant a held die to an ally. The holder's
        # post-roll self-add lives in engine.core.bardic_inspiration
        # (hooked in _attack_roll), not a primitive.
        # Druid Wild Shape — transform into a Beast form (rides
        # engine.core.forms). Revert leaves the form early.
        Primitive("wild_shape_transform", _wild_shape_transform,
                    implemented=True),
        Primitive("wild_shape_revert", _wild_shape_revert,
                    implemented=True),
        # Monster Shape-Shift (2024 Change Shape) — stat-preserving form
        # change (size only) via the change_shape policy.
        Primitive("shape_shift", _shape_shift, implemented=True),
        Primitive("shape_shift_revert", _shape_shift_revert,
                    implemented=True),
        # Polymorph (control) — forced WIS save → transform the TARGET into
        # a Beast under the polymorph policy (carry_overflow, concentration-
        # and death-revert). See engine.core.forms.
        Primitive("polymorph_target", _polymorph_target, implemented=True),
        # Swallow / Engulf — internalize the target (Total Cover +
        # ongoing acid) via engine.core.swallow.
        Primitive("swallow_apply", _swallow_apply, implemented=True),
        # Summon creatures into the fight (Wraith Create Specter, conjure)
        # via engine.core.summoning — dynamic encounter membership.
        Primitive("summon", _summon, implemented=True),
        # Place a Wall of Force-style barrier (positional-barrier system):
        # appends a geometry.Wall to state.walls; rides the movement / LoE /
        # AoE wiring; concentration-end scrubs it by flags.
        Primitive("place_barrier", _place_barrier, implemented=True),
        Primitive("grant_bardic_inspiration", _grant_bardic_inspiration,
                    implemented=True),
        # College of Lore Cutting Words — reaction that rolls the Bard's
        # die and bumps the defender's AC (per_single_attack) to negate
        # an enemy hit. Rides the attack_roll_pending reaction hook.
        Primitive("cutting_words_resolve", _cutting_words_resolve,
                    implemented=True),
        # PR #90 — Hex curse primitive. Registers a target-specific
        # weapon_damage_bonus modifier on the caster gated via
        # target_is(<cursed_id>) when-clause atom.
        Primitive("hex_curse", _hex_curse, implemented=True),
        # PR #91 — Hunter's Mark. Mechanically parallel to hex_curse
        # (same target-specific damage rider machinery); kept distinct
        # for named_effect tagging + event log clarity + future
        # divergence (favored-target Perception tracking).
        Primitive("hunters_mark_mark", _hunters_mark_mark, implemented=True),
        # PR #106 — Forced movement (Repelling Blast invocation; future
        # generic shove / pull). Pushes current target away from the
        # actor via geometry.push_creature; RAW size gate (Large-or-
        # smaller). Typically gated `when: combat.attack_state == hit`.
        Primitive("forced_movement", _forced_movement, implemented=True),
        # PR #94 — Temp HP grant + per-turn recurring grant. Dual of
        # recurring_damage; used by Heroism and future Aid-shape
        # spells. Max-semantics replacement on Actor.temp_hp.
        Primitive("temp_hp_grant", _temp_hp_grant, implemented=True),
        Primitive("recurring_temp_hp", _recurring_temp_hp, implemented=True),
        # PR #96 — Armor of Agathys arming primitive. Registers a
        # marker modifier on the caster that drives reflective cold
        # damage to melee attackers (read by _damage via the
        # `armor_of_agathys_active` primitive name).
        Primitive("armor_of_agathys_arm", _armor_of_agathys_arm,
                    implemented=True),
        # PR #97 — Max-HP grant (Aid). Raises target's hp_max +
        # hp_current; ledgered on Actor.hp_max_bonuses for clean
        # removal at long rest. Distinct from temp HP.
        Primitive("hp_max_grant", _hp_max_grant, implemented=True),
        # Stage 3 — grant a movement speed (Fly's fly 60). Ledgered on
        # Actor.active_speed_grants; reverted when concentration ends.
        Primitive("grant_speed", _grant_speed, implemented=True),
    ]
    # Populate handler lookup table for subprimitive invocations
    global _PRIMITIVE_HANDLERS
    _PRIMITIVE_HANDLERS = {p.name: p.handler for p in implemented}
    stubs = [
        Primitive(name, _stub_handler(name), implemented=False)
        for name in _STUB_PRIMITIVES
    ]
    return implemented + stubs


# Populate the subprimitive lookup table at module import time.
_populate_handler_table()
