"""Primitive library — engine handlers for every primitive declared
in the schema. Implementations live here for the skeleton; if the library
grows large, split into engine/primitives/<category>/<name>.py.

For the skeleton:
  - 5 primitives implemented enough to run a Goblin vs Fighter encounter:
      attack_roll, damage, apply_condition, heal, granted_action
  - All others are STUBS that raise NotImplementedError with a clear
    message. Implementing more primitives = unlocking more content.

Each primitive declares:
  - name: stable identifier (referenced from YAML content)
  - apply(params, state, event_bus): execute the effect

The engine's PrimitiveRegistry holds them; `pipeline.execute()` looks
them up by name and dispatches.
"""
from __future__ import annotations

import re
import random as _random_module
from typing import Callable, Any
from dataclasses import dataclass

from engine.core.state import CombatState, Actor, ability_modifier
from engine.core.events import EventBus


# ============================================================================
# Base + Registry
# ============================================================================

@dataclass
class Primitive:
    """A primitive: a named effect handler.

    Each handler signature: (params: dict, state: CombatState, bus: EventBus) -> Any
    """
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
                f"Primitive {name!r} is stubbed. "
                f"Implementation deferred — see engine/primitives.py."
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
    """Roll a dice expression like '1d6' or '8d6'. Returns the total."""
    m = _DICE_PATTERN.fullmatch(expr.strip())
    if not m:
        raise ValueError(f"Invalid dice expression: {expr!r}")
    count, sides = int(m.group(1)), int(m.group(2))
    return sum(rng.randint(1, sides) for _ in range(count))


def _max_dice_expr(expr: str) -> int:
    """Max possible value of a dice expression — used for crit damage."""
    m = _DICE_PATTERN.fullmatch(expr.strip())
    if not m:
        raise ValueError(f"Invalid dice expression: {expr!r}")
    count, sides = int(m.group(1)), int(m.group(2))
    return count * sides


# ============================================================================
# IMPLEMENTED PRIMITIVES (the 5 critical for skeleton smoke test)
# ============================================================================

def _attack_roll(params: dict, state: CombatState, bus: EventBus) -> dict:
    """Roll d20 + bonus vs target AC. Sets state.current_attack['state']."""
    actor: Actor = state.current_attack["actor"]
    target: Actor = state.current_attack["target"]
    bonus = params.get("bonus", 0)
    rng = _get_rng(state, bus)

    # Get advantage / disadvantage from state (set by modifiers; default normal)
    has_adv = state.current_attack.get("had_advantage", False)
    has_dis = state.current_attack.get("had_disadvantage", False)
    if has_adv and has_dis:
        has_adv = has_dis = False  # cancel out per rules

    if has_adv:
        d20 = max(rng.randint(1, 20), rng.randint(1, 20))
    elif has_dis:
        d20 = min(rng.randint(1, 20), rng.randint(1, 20))
    else:
        d20 = rng.randint(1, 20)

    total = d20 + bonus
    is_crit = (d20 >= 20)        # Improved Critical etc. would lower this threshold
    is_hit = is_crit or (total >= target.ac)
    attack_state = "crit" if is_crit else ("hit" if is_hit else "miss")

    state.current_attack["state"] = attack_state
    state.current_attack["d20"] = d20
    state.current_attack["total"] = total
    bus.emit("attack_roll", {"actor": actor, "target": target,
                              "d20": d20, "total": total, "vs_ac": target.ac})
    bus.emit("attack_resolved", {"actor": actor, "target": target,
                                  "state": attack_state, "d20": d20})
    state.event_log.append({"event": "attack_roll", "actor": actor.id,
                            "target": target.id, "d20": d20, "total": total,
                            "vs_ac": target.ac, "result": attack_state})
    return {"state": attack_state, "d20": d20, "total": total}


def _damage(params: dict, state: CombatState, bus: EventBus) -> dict:
    """Roll damage dice + modifier, apply to target HP."""
    target: Actor = state.current_attack["target"]
    actor: Actor = state.current_attack["actor"]
    dice = params.get("dice")
    modifier = params.get("modifier", 0)
    dmg_type = params.get("type", "untyped")
    rng = _get_rng(state, bus)

    is_crit = state.current_attack.get("state") == "crit"

    if dice:
        rolled = _roll_dice_expr(dice, rng)
        if is_crit:
            # 5e crit: roll damage dice twice (add an extra roll)
            rolled += _roll_dice_expr(dice, rng)
    else:
        rolled = 0

    total = rolled + modifier

    # Apply resistance / vulnerability / immunity (simplified for skeleton)
    if dmg_type in (target.template.get("damage_immunities") or []):
        total = 0
    elif dmg_type in (target.template.get("damage_resistances") or []):
        total = total // 2
    elif dmg_type in (target.template.get("damage_vulnerabilities") or []):
        total = total * 2

    total = max(0, total)
    target.hp_current = max(0, target.hp_current - total)

    bus.emit("damage_dealt", {"actor": actor, "target": target,
                                "amount": total, "type": dmg_type})
    state.event_log.append({"event": "damage_dealt", "actor": actor.id,
                            "target": target.id, "amount": total, "type": dmg_type,
                            "target_hp_remaining": target.hp_current})

    if target.hp_current == 0:
        target.is_dead = True
        bus.emit("creature_dropped", {"creature": target})
        state.event_log.append({"event": "creature_dropped", "creature": target.id})
    elif target.is_bloodied():
        bus.emit("creature_bloodied", {"creature": target})

    return {"amount": total, "target_hp": target.hp_current}


def _apply_condition(params: dict, state: CombatState, bus: EventBus) -> None:
    """Add a condition to the target's applied_conditions list."""
    target: Actor = state.current_attack.get("target") or state.current_actor()
    actor: Actor = state.current_attack.get("actor") or state.current_actor()
    condition_id = params.get("condition_id") or params.get("condition")
    if not condition_id:
        raise ValueError("apply_condition requires condition_id or condition")
    target.applied_conditions.append({
        "condition_id": condition_id,
        "source_id": actor.id if actor else None,
        "applied_at_round": state.round,
        "duration": params.get("duration"),
    })
    state.event_log.append({"event": "condition_applied",
                            "target": target.id, "condition": condition_id})


def _heal(params: dict, state: CombatState, bus: EventBus) -> dict:
    """Heal target (default: current actor) by dice + modifier_source."""
    actor: Actor = state.current_actor()
    target: Actor = actor if params.get("target") in (None, "self") else None
    if target is None:
        raise ValueError("heal target other than self not supported in skeleton")
    rng = _get_rng(state, bus)

    dice = params.get("dice")
    fixed = params.get("fixed", 0)
    modifier_source = params.get("modifier_source")

    amount = fixed
    if dice:
        amount += _roll_dice_expr(dice, rng)
    if modifier_source:
        amount += _resolve_modifier(modifier_source, target)

    target.hp_current = min(target.hp_max, target.hp_current + amount)
    state.event_log.append({"event": "healed", "target": target.id,
                            "amount": amount, "hp_current": target.hp_current})
    return {"amount": amount, "hp_current": target.hp_current}


def _granted_action(params: dict, state: CombatState, bus: EventBus) -> None:
    """Grant a free action (Disengage / Hide / Dodge / etc.) to current actor.

    Skeleton: just records the grant in the event log. Real engine would
    apply the action's effect (e.g., Disengage flag prevents OAs).
    """
    actor: Actor = state.current_actor()
    kind = params.get("kind") or params.get("granted_action")
    state.event_log.append({"event": "granted_action",
                            "actor": actor.id, "kind": kind})


# ============================================================================
# STUB PRIMITIVES — raise NotImplementedError when invoked
# ============================================================================

_STUB_PRIMITIVES = [
    # Modifiers (unified per Q5)
    "attack_modifier", "save_modifier", "speed_modifier", "damage_modifier",
    "ability_check_modifier", "d20_test_modifier", "crit_modifier",
    "crit_threshold_modifier", "death_save_threshold_modifier",
    # Spell pipeline
    "forced_save", "recurring_save", "persistent_aura", "triggered_save",
    # Condition effects
    "sense_restriction", "movement_restriction", "action_restriction",
    "damage_resistance_grant", "condition_immunity_grant",
    "state_transition", "concentration_break", "visibility_state",
    "awareness_state", "state_flag",
    # Action / turn
    "additional_action", "multiattack", "at_will_spell_grant",
    "free_cast_per_rest", "slot_recovery_partial",
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
    """Lookup the runner's RNG via the bus (set during runner setup)."""
    # The runner attaches itself to bus via a back-channel; for skeleton
    # we fall back to a module-level RNG. The runner overwrites _rng below.
    return _rng


def _resolve_modifier(source: str, actor: Actor) -> int:
    """Resolve a modifier-source string like 'actor.fighter_level' or 'actor.con_mod'.

    Skeleton: handles a tiny vocabulary. Real engine has a proper
    expression evaluator.
    """
    if source == "actor.con_mod":
        return ability_modifier(actor.abilities.get("con", {}).get("score", 10))
    if source == "actor.int_mod":
        return ability_modifier(actor.abilities.get("int", {}).get("score", 10))
    if source.startswith("actor.") and source.endswith("_level"):
        # e.g., actor.fighter_level — look in template
        cls_name = source[len("actor."):-len("_level")]
        return actor.template.get("levels", {}).get(cls_name, 1)
    raise ValueError(f"Unknown modifier source: {source!r}")


# Module-level RNG; runner overrides via set_rng() for determinism
_rng: _random_module.Random = _random_module.Random()


def set_rng(rng: _random_module.Random) -> None:
    """Allow the runner to inject a seeded RNG before running."""
    global _rng
    _rng = rng


def _all_primitives() -> list[Primitive]:
    return [
        Primitive("attack_roll", _attack_roll, implemented=True),
        Primitive("damage", _damage, implemented=True),
        Primitive("apply_condition", _apply_condition, implemented=True),
        Primitive("heal", _heal, implemented=True),
        Primitive("granted_action", _granted_action, implemented=True),
    ] + [
        Primitive(name, _stub_handler(name), implemented=False)
        for name in _STUB_PRIMITIVES
    ]
