"""Ensnaring Strike — Ranger 1st-level smite-shape spell (PR #110).

As of PR #112 this is a **thin adapter** over engine.core.smite_rider
(the shared "arm a one-shot rider on the next weapon hit" core). This
module owns Ensnaring Strike's SmiteRiderSpec and re-exports the
original public functions (unchanged signatures) so existing callers —
the `ensnaring_strike_arm` primitive, the `_damage` hook, and the test
suite — keep working.

RAW (PHB 2024):
  Bonus Action, V, Self, Concentration up to 1 minute. The next time
  you hit a creature with a weapon attack before the spell ends, the
  target must succeed on a Strength saving throw or be Restrained by
  thorny vines until the spell ends (1d6 piercing at the start of each
  of its turns). A Large+ creature has advantage on the save; a
  Restrained creature can use an action to make a STR check to break
  free. Higher Levels: damage +1d6 per slot above 1st.

Spec specifics: ANY weapon hit (melee OR ranged); NO bonus damage on
the empowering hit; STR save → co_ensnared (Restrained via inheritance
+ 1d6 piercing/turn).

**v1 deferred** (unchanged): STR-check-to-break-free as the target's
action; Large+ advantage on the initial save (forced_save doesn't
thread size-based save advantage); upcast +1d6 on the per-turn tick.
"""
from __future__ import annotations

import random

from engine.core import smite_rider
from engine.core.smite_rider import SmiteRiderSpec
from engine.core.state import Actor, CombatState

ENSNARING_STRIKE_ARMED_PRIMITIVE = "ensnaring_strike_armed"

ENSNARING_STRIKE_SPEC = SmiteRiderSpec(
    key="ensnaring_strike",
    marker_primitive=ENSNARING_STRIKE_ARMED_PRIMITIVE,
    named_effect="ensnaring_strike",
    default_action_id="a_ensnaring_strike",
    save_ability="strength",
    on_fail_condition="co_ensnared",
    melee_only=False,             # any weapon attack qualifies
    bonus_damage_die=None,        # no bonus damage on the empowering hit
    bonus_scales_with_upcast=False,
)


def register_armed(caster: Actor, spell_save_dc: int, action_id: str,
                     state: CombatState) -> None:
    """Register the one-shot armed marker on the caster (delegates to
    smite_rider; signature preserved from PR #110 — no slot_level since
    Ensnaring deals no upcast-scaling bonus damage)."""
    smite_rider.register_armed(
        caster, ENSNARING_STRIKE_SPEC, spell_save_dc=spell_save_dc,
        action_id=action_id, state=state)


def find_armed_entry(caster: Actor) -> dict | None:
    return smite_rider.find_armed_entry(caster, ENSNARING_STRIKE_SPEC)


def clear_armed(caster: Actor) -> None:
    smite_rider.clear_armed(caster, ENSNARING_STRIKE_SPEC)


def try_apply_ensnaring_strike_followup(
        attacker: Actor, target: Actor, state: CombatState,
        attack_params: dict | None, rng: random.Random,
        is_crit: bool) -> int:
    """Fire Ensnaring Strike's rider on a qualifying weapon hit (melee
    OR ranged): STR save → co_ensnared. Returns 0 (no bonus damage)."""
    return smite_rider.try_apply_followup(
        attacker, target, state, attack_params, rng, is_crit,
        ENSNARING_STRIKE_SPEC)


_NoOpBus = smite_rider._NoOpBus
