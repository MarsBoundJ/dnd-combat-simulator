"""Searing Smite — Paladin 1st-level smite spell (PR #89).

As of PR #112 this is a **thin adapter** over engine.core.smite_rider,
which holds the shared "arm a one-shot rider on the next weapon hit"
logic. This module owns Searing Smite's SmiteRiderSpec and re-exports
the original public functions (unchanged signatures) so existing
callers — the `searing_smite_arm` primitive, the `_damage` hook, and
the test suite — keep working.

RAW (SRD 5.2.1 / PHB 2024):
  Bonus Action, V, Self, 1 minute (NOT Concentration). As you hit
  the target, it takes an extra 1d6 Fire damage. At the start of
  each of its turns until the spell ends, the target takes 1d6 Fire
  damage and then makes a CON save — on success the spell ends.
  Higher Levels: ALL damage increases by 1d6 per slot above 1st.

Spec specifics: melee-only; 1d6 fire bonus damage on hit (scales
with upcast); NO initial save — co_ignited applies automatically
on hit; per-turn burn also scales with upcast (burn_scales_with_upcast).

Deferred: typed bonus damage modeling (added as untyped to the
existing damage step — shared gap with Divine Favor's +1d4 radiant).
"""
from __future__ import annotations

import random

from engine.core import smite_rider
from engine.core.smite_rider import SmiteRiderSpec
from engine.core.state import Actor, CombatState

# Marker modifier primitive name (kept module-level for back-compat;
# tests and any external reference still resolve it here).
SEARING_SMITE_ARMED_PRIMITIVE = "searing_smite_armed"

SEARING_SMITE_SPEC = SmiteRiderSpec(
    key="searing_smite",
    marker_primitive=SEARING_SMITE_ARMED_PRIMITIVE,
    named_effect="searing_smite",
    default_action_id="a_searing_smite",
    save_ability="constitution",        # end-of-turn save (via co_ignited)
    on_fail_condition="co_ignited",
    melee_only=True,
    bonus_damage_die=6,                 # 1d6 fire on the empowering hit
    bonus_scales_with_upcast=True,
    has_initial_save=False,             # 2024: co_ignited auto-applies on hit
    burn_scales_with_upcast=True,       # "All the damage increases"
)


def register_armed(caster: Actor, slot_level: int, spell_save_dc: int,
                     action_id: str, state: CombatState) -> None:
    """Register the one-shot armed marker on the caster (delegates to
    smite_rider; signature preserved from PR #89)."""
    smite_rider.register_armed(
        caster, SEARING_SMITE_SPEC, spell_save_dc=spell_save_dc,
        action_id=action_id, state=state, slot_level=slot_level)


def find_armed_entry(caster: Actor) -> dict | None:
    return smite_rider.find_armed_entry(caster, SEARING_SMITE_SPEC)


def clear_armed(caster: Actor) -> None:
    smite_rider.clear_armed(caster, SEARING_SMITE_SPEC)


def try_apply_searing_smite_followup(
        attacker: Actor, target: Actor, state: CombatState,
        attack_params: dict | None, rng: random.Random,
        is_crit: bool) -> int:
    """Fire Searing Smite's rider on a qualifying melee hit: 1d6 fire
    (+1d6/upcast, doubled on crit), CON save → co_ignited. Returns the
    bonus damage to add to the attack total."""
    return smite_rider.try_apply_followup(
        attacker, target, state, attack_params, rng, is_crit,
        SEARING_SMITE_SPEC)


# Back-compat alias: some call sites / tests imported the no-op bus
# from this module.
_NoOpBus = smite_rider._NoOpBus
