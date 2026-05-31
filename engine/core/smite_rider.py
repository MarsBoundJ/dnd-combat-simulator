"""smite_rider — shared core for "arm a one-shot rider on the next
weapon hit" spells (PR #112).

Searing Smite (PR #89) and Ensnaring Strike (PR #110) shipped as two
near-identical modules: each had its own register_armed / find /
clear / try_apply_followup that differed only in a handful of
parameters (marker name, save ability, on-fail condition, melee-only
vs any-weapon, whether the empowering hit deals bonus damage). This
module collapses that duplicated LOGIC into one parameterized
implementation driven by a `SmiteRiderSpec`.

The per-spell modules (engine.core.searing_smite, engine.core.
ensnaring_strike) are now thin adapters: they own a SPEC and re-export
the same public function names/signatures they always had, so all
existing callers (the arm primitives, the _damage hooks, the test
suites) keep working unchanged. Adding a new smite is now: define a
SmiteRiderSpec + a one-line arm primitive + a _damage hook line.

**Shared mechanic (two-phase):**
  1. Arm — register a marker modifier on the caster (lifetime until
     short rest, source tagged with caster_id + action_id +
     named_effect for concentration scrub).
  2. Trigger — on the caster's next qualifying weapon hit
     (try_apply_followup, called from _damage): optionally roll bonus
     damage on the empowering hit, fire a save on the target, on fail
     apply the spell's condition, clear the marker (one-shot).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from engine.core.state import Actor, CombatState


@dataclass(frozen=True)
class SmiteRiderSpec:
    """Declarative description of an arming-smite rider.

    - key: short id used in event-log names ("searing_smite_armed",
      "<key>_triggered").
    - marker_primitive: the active_modifier primitive name that tags an
      armed caster (kept distinct per spell so a caster could in
      principle be armed with two, and clear only removes the match).
    - named_effect: cross-caster dedup tag on the marker source.
    - default_action_id: fallback spell-action id for the save context.
    - save_ability: full ability name for the on-hit save ("strength").
    - on_fail_condition: condition applied to the target on a failed
      save ("co_ignited" / "co_ensnared").
    - melee_only: True → only melee hits trigger (Searing); False →
      any weapon hit (Ensnaring).
    - bonus_damage_die: die size for bonus damage on the empowering hit
      (6 → 1d6), or None for no bonus damage.
    - bonus_scales_with_upcast: True → +1 die per slot level above 1st.
    - has_initial_save: True → forced save on hit (Searing/Wrathful);
      False → condition applied automatically on hit (Blinding).
    """
    key: str
    marker_primitive: str
    named_effect: str
    default_action_id: str
    save_ability: str
    on_fail_condition: str
    melee_only: bool
    bonus_damage_die: int | None
    bonus_scales_with_upcast: bool
    has_initial_save: bool = True


def register_armed(caster: Actor, spec: SmiteRiderSpec, *,
                     spell_save_dc: int, action_id: str,
                     state: CombatState, slot_level: int = 1) -> None:
    """Register the one-shot armed marker on the caster (lifetime until
    short rest; source tagged for concentration / short-rest scrub)."""
    entry = {
        "primitive": spec.marker_primitive,
        "params": {"dc": int(spell_save_dc),
                     "slot_level": int(slot_level)},
        "lifetime": "until_short_rest",
        "source": {
            "type": "spell",
            "id": action_id,
            "action_id": action_id,
            "caster_id": caster.id,
            "named_effect": spec.named_effect,
        },
        "applied_at_round": state.round,
        "owner_id": caster.id,
    }
    caster.active_modifiers.append(entry)
    state.event_log.append({
        "event": f"{spec.key}_armed",
        "caster": caster.id,
        "dc": int(spell_save_dc),
        "slot_level": int(slot_level),
    })


def find_armed_entry(caster: Actor, spec: SmiteRiderSpec) -> dict | None:
    """Return the caster's active marker for this spec, or None."""
    for mod in caster.active_modifiers:
        if mod.get("primitive") == spec.marker_primitive:
            return mod
    return None


def clear_armed(caster: Actor, spec: SmiteRiderSpec) -> None:
    """Remove this spec's marker after the rider fires (one-shot;
    concentration continues for any ongoing effect)."""
    caster.active_modifiers = [
        m for m in caster.active_modifiers
        if m.get("primitive") != spec.marker_primitive
    ]


def try_apply_followup(attacker: Actor, target: Actor, state: CombatState,
                         attack_params: dict | None, rng: random.Random,
                         is_crit: bool, spec: SmiteRiderSpec) -> int:
    """If the attacker is armed for `spec` AND this is a qualifying
    weapon hit, fire the rider: roll any bonus damage, fire the save,
    on fail apply the condition, clear the marker. Returns the bonus
    damage to add to the attack's total (0 for no-bonus-damage specs
    or when not armed / non-qualifying)."""
    armed = find_armed_entry(attacker, spec)
    if armed is None:
        return 0
    kind = (attack_params or {}).get("kind", "melee")
    if spec.melee_only:
        if kind != "melee":
            return 0
    elif kind not in ("melee", "ranged"):
        return 0

    armed_params = armed.get("params") or {}
    dc = int(armed_params.get("dc", 10))
    slot_level = int(armed_params.get("slot_level", 1))

    bonus_damage = 0
    if spec.bonus_damage_die:
        dice_count = 1
        if spec.bonus_scales_with_upcast:
            dice_count += max(0, slot_level - 1)
        rolls = dice_count * (2 if is_crit else 1)
        bonus_damage = sum(rng.randint(1, spec.bonus_damage_die)
                             for _ in range(rolls))

    state.event_log.append({
        "event": f"{spec.key}_triggered",
        "attacker": attacker.id, "target": target.id,
        "dc": dc, "slot_level": slot_level,
        "bonus_damage": bonus_damage, "is_crit": is_crit,
    })

    # Stamp the spell's action id onto current_attack so the condition's
    # recurring_damage entry records source_action_id for
    # end_concentration scrub.
    saved_action = state.current_attack.get("action")
    spell_action_id = (armed.get("source") or {}).get(
        "action_id", spec.default_action_id)
    state.current_attack["action"] = {
        "id": spell_action_id,
        "spell_slot_level": slot_level,
    }
    try:
        if spec.has_initial_save:
            from engine.primitives import _forced_save
            _forced_save({
                "ability": spec.save_ability,
                "dc": dc,
                "affected": "current_target",
                "on_fail": [
                    {"primitive": "apply_condition",
                      "params": {"condition_id": spec.on_fail_condition,
                                  "duration": "until_spell_ends"}},
                ],
                "on_success": [],
            }, state, _NoOpBus())
        else:
            from engine.primitives import _apply_condition
            _apply_condition({
                "condition_id": spec.on_fail_condition,
                "duration": "until_spell_ends",
            }, state, _NoOpBus())
    finally:
        state.current_attack["action"] = saved_action

    clear_armed(attacker, spec)
    return bonus_damage


class _NoOpBus:
    """Minimal event-bus stand-in for the forced_save invocation from
    within try_apply_followup (the save path emits no events required
    for correctness here)."""

    def emit(self, *args, **kwargs) -> None:
        return None
