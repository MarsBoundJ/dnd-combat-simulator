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
    from engine.core.geometry import distance_ft

    actor: Actor = state.current_attack["actor"]
    target: Actor = state.current_attack["target"]
    bonus = params.get("bonus", 0)
    rng = _get_rng(state, bus)

    # Out-of-range guard. Defends against multiattack execution paths
    # where a sub-attack might be invoked beyond its reach (e.g., a
    # Scimitar swing against a target 30 ft away when the multiattack
    # was gated on the Shortbow's range). Auto-miss with telemetry.
    reach = int(params.get("range_ft", params.get("reach_ft", 5)))
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
    is_hit = is_crit or (total >= effective_ac)
    # Forced crit (e.g., Paralyzed target within 5ft): only fires if hit
    if is_hit and crit_mods.force_crit_if_hit:
        is_crit = True
    attack_state = "crit" if is_crit else ("hit" if is_hit else "miss")

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

    if dice:
        rolled = _roll_dice_expr_with_floor(dice, floor, rng)
        if is_crit:
            rolled += _roll_dice_expr_with_floor(dice, floor, rng)
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

    # Apply multiplier (after resistance per 5e ordering: resistance halves
    # the post-multiplier? Or multiplier-then-resistance? Per RAW saves halve
    # the rolled total before resistance. For v1 we apply resistance first
    # then multiplier — close enough for eHP scoring).
    if multiplier != 1.0:
        total = int(total * multiplier)

    total = max(0, total)
    target.hp_current = max(0, target.hp_current - total)

    # PR #71: track damage taken while raging — feeds the end-of-turn
    # "no attack + no damage" auto-end check. Damage > 0 satisfies the
    # "took damage this turn" branch of the rule.
    _rage.mark_damaged_while_raging(target, total)

    bus.emit("damage_dealt", {"actor": actor, "target": target,
                                "amount": total, "type": dmg_type})
    state.event_log.append({"event": "damage_dealt", "actor": actor.id,
                            "target": target.id, "amount": total, "type": dmg_type,
                            "target_hp_remaining": target.hp_current})

    # Concentration check on damage taken (5e RAW: DC = max(10,
    # ceil(damage/2))). Lives in primitives.py so all damage paths get
    # the check uniformly — AoE on_fail / on_success, weapon attack
    # damage, OA damage, sub-attack damage in multiattack, etc.
    if total > 0 and target.concentration_on is not None:
        from engine.core.concentration import attempt_concentration_save
        attempt_concentration_save(target, total, state, rng)

    if target.hp_current == 0:
        target.is_dead = True
        # Death ends any concentration the deceased was maintaining
        if target.concentration_on is not None:
            from engine.core.concentration import end_concentration
            end_concentration(target, state, reason="caster_died")
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

    return {"amount": total, "target_hp": target.hp_current}


def _apply_condition(params: dict, state: CombatState, bus: EventBus) -> None:
    """Apply a condition + instantiate its effect primitives onto active_modifiers."""
    target: Actor = state.current_attack.get("target") or state.current_actor()
    actor: Actor = state.current_attack.get("actor") or state.current_actor()
    condition_id = params.get("condition_id") or params.get("condition")
    if not condition_id:
        raise ValueError("apply_condition requires condition_id or condition")

    application = {
        "condition_id": condition_id,
        "source_id": actor.id if actor else None,
        "applied_at_round": state.round,
        "duration": params.get("duration"),
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
            # Pass the host condition's id through so the entry can
            # be scrubbed later via condition-removal cleanup.
            params.setdefault("condition_id",
                                application["condition_id"])
            _recurring_damage(params, state, _NoOpBus())
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
        actor = state.current_actor()
        if actor is None and state.current_attack:
            actor = state.current_attack.get("actor")
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

    targets = _resolve_save_targets(params, state)
    rolls = []
    for target in targets:
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
            if outcome == "fail":
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
    """Resolve a Counterspell attempt. Reads the triggering spell info
    from state.current_attack.reaction_event_data; performs RAW 2024
    Counterspell mechanics:

      - If target spell is level ≤ 3: auto-cancel (no check needed).
      - If level ≥ 4: counterspeller rolls Intelligence (Spellcasting)
        ability check vs DC = 10 + target spell's level.
        Spellcasting ability is the caster's INT (Counterspell is on
        the wizard list; v1 hard-codes INT for the check). Modifier =
        INT_mod + proficiency_bonus (every spellcaster is automatically
        proficient with their spellcasting ability for casting purposes).
        On success: cancel. On fail: spell goes through.

    Side effects on cancel:
      - Sets state.cast_cancelled = True (pipeline.execute checks this
        flag after the spell_cast_initiated event resolves; if True,
        skips the target spell's pipeline but still consumes its slot).
      - Logs counterspell_resolved event with outcome + check details.

    Returns {"outcome": "auto_cancel" | "check_success" | "check_fail"}.
    """
    rng = _get_rng(state, bus)
    counterspeller = state.current_attack.get("actor")
    if counterspeller is None:
        raise ValueError("counterspell_resolve needs a current actor")
    event_data = state.current_attack.get("reaction_event_data") or {}
    target_caster = event_data.get("caster")
    target_action = event_data.get("action") or {}
    target_level = int(event_data.get("spell_slot_level", 0))

    if target_level <= 3:
        state.cast_cancelled = True
        state.event_log.append({
            "event": "counterspell_resolved",
            "counterspeller": counterspeller.id,
            "target_caster": target_caster.id if target_caster else None,
            "target_spell": target_action.get("id"),
            "target_level": target_level,
            "outcome": "auto_cancel",
        })
        return {"outcome": "auto_cancel"}

    # Level ≥ 4: ability check
    int_score = (counterspeller.abilities.get("int") or {}).get("score", 10)
    int_mod = ability_modifier(int_score)
    pb = int((counterspeller.template.get("cr") or {})
                .get("proficiency_bonus", 2))
    dc = 10 + target_level
    d20 = rng.randint(1, 20)
    total = d20 + int_mod + pb
    success = total >= dc
    if success:
        state.cast_cancelled = True
    state.event_log.append({
        "event": "counterspell_resolved",
        "counterspeller": counterspeller.id,
        "target_caster": target_caster.id if target_caster else None,
        "target_spell": target_action.get("id"),
        "target_level": target_level,
        "outcome": "check_success" if success else "check_fail",
        "d20": d20,
        "int_mod": int_mod,
        "proficiency_bonus": pb,
        "total": total,
        "dc": dc,
    })
    return {"outcome": "check_success" if success else "check_fail"}


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


def _caster_spell_save_dc(actor: Actor) -> int:
    """Compute the actor's spell save DC: 8 + proficiency_bonus +
    spellcasting_ability_modifier. v1 reads CHA for Paladin (the only
    spell-DC consumer in PR #89); future generalization will read
    actor.template.spellcasting.ability or a per-class default."""
    pb = int((actor.template.get("cr") or {}).get("proficiency_bonus", 2))
    cha_score = (actor.abilities.get("cha") or {}).get("score", 10)
    cha_mod = (cha_score - 10) // 2
    return 8 + pb + cha_mod


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
        # Skeleton: use current_attack.actor's spellcasting DC
        # Fallback to a reasonable default (DC 13) if no caster info available
        actor = state.current_attack.get("actor") or state.current_actor()
        if actor:
            # Try to compute: 8 + spellcasting_mod + PB
            int_mod = ability_modifier(actor.abilities.get("int", {}).get("score", 10))
            pb = actor.template.get("cr", {}).get("proficiency_bonus", 2)
            return 8 + int_mod + pb
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
    if affected == "all_creatures_in_area":
        # AoE-aware path: dispatch on area.shape using state.current_attack's
        # area_origin (sphere) or area_origin + area_direction (cone, line).
        # Living creatures only; includes allies (friendly fire is RAW).
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

        if origin is not None:
            if shape == "sphere":
                radius_ft = area.get("radius_ft")
                if radius_ft is not None:
                    from engine.core.geometry import actors_in_radius
                    return actors_in_radius(tuple(origin), int(radius_ft),
                                              living)
            elif shape == "cone":
                length_ft = area.get("length_ft")
                if length_ft is not None and direction is not None:
                    from engine.core.geometry import actors_in_cone
                    return actors_in_cone(tuple(origin), tuple(direction),
                                            int(length_ft), living)
            elif shape == "line":
                length_ft = area.get("length_ft")
                width_ft = area.get("width_ft", 5)
                if length_ft is not None and direction is not None:
                    from engine.core.geometry import actors_in_line
                    return actors_in_line(tuple(origin), tuple(direction),
                                            int(length_ft), int(width_ft),
                                            living)
        # Legacy fallback: all living enemies
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
        "ready_action": _ready_action,
        "recurring_damage": _recurring_damage,
        "searing_smite_arm": _searing_smite_arm,
        "hex_curse": _hex_curse,
        "hunters_mark_mark": _hunters_mark_mark,
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
        # PR #86 — Ready Action (records a readied sub-action + trigger
        # onto the actor; fires when the trigger matches before the
        # actor's next turn).
        Primitive("ready_action", _ready_action, implemented=True),
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
        # PR #90 — Hex curse primitive. Registers a target-specific
        # weapon_damage_bonus modifier on the caster gated via
        # target_is(<cursed_id>) when-clause atom.
        Primitive("hex_curse", _hex_curse, implemented=True),
        # PR #91 — Hunter's Mark. Mechanically parallel to hex_curse
        # (same target-specific damage rider machinery); kept distinct
        # for named_effect tagging + event log clarity + future
        # divergence (favored-target Perception tracking).
        Primitive("hunters_mark_mark", _hunters_mark_mark, implemented=True),
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
