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
    """Cover → AC bonus mapping (PR #48). RAW 2024:
      - half cover: +2 AC + DEX save
      - three-quarters cover: +5 AC + DEX save
      - total cover: can't be targeted (deferred — needs attack-cancel)
    """
    if cover == "half":
        return 2
    if cover == "three_quarters":
        return 5
    return 0


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

    # PR #54: Weapon Mastery dispatch. Fires AFTER lifetime expiry so
    # newly-registered Vex/Sap modifiers (with per_owner_attack
    # lifetime, which consumes on owner_made_attack) survive THIS
    # attack and only consume on the NEXT swing — exactly RAW. The
    # dispatch is a no-op when the weapon has no mastery or the
    # actor doesn't know it.
    from engine.core.weapon_masteries import apply_mastery_effects
    apply_mastery_effects(params.get("mastery"), actor, target,
                             attack_state, state)

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

    total = rolled + modifier

    # Resistance / vulnerability / immunity (template-level)
    template = target.template or {}
    if dmg_type in (template.get("damage_immunities") or []):
        total = 0
    elif dmg_type in (template.get("damage_resistances") or []):
        total = total // 2
    elif dmg_type in (template.get("damage_vulnerabilities") or []):
        total = total * 2

    # Apply multiplier (after resistance per 5e ordering: resistance halves
    # the post-multiplier? Or multiplier-then-resistance? Per RAW saves halve
    # the rolled total before resistance. For v1 we apply resistance first
    # then multiplier — close enough for eHP scoring).
    if multiplier != 1.0:
        total = int(total * multiplier)

    total = max(0, total)
    target.hp_current = max(0, target.hp_current - total)

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
        entry = {
            "primitive": effect.get("primitive"),
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
    }
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
        "forced_save": _forced_save,
        "recurring_save": _recurring_save,
        "slot_recovery_partial": _slot_recovery_partial,
        "persistent_aura": _persistent_aura,
        "counterspell_resolve": _counterspell_resolve,
        "multiattack": _multiattack,
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
