"""Shared smite-rider core tests (PR #112).

Searing Smite (#89) and Ensnaring Strike (#110) collapsed their
duplicated arm/find/clear/followup logic into engine.core.smite_rider,
driven by a SmiteRiderSpec. The per-spell modules are now thin
adapters (their own test suites still pass — behavior preserved). This
suite tests the generic core directly + proves a brand-new spec runs
through the same path with no new logic (the payoff of the refactor).

Layers:
  1. register_armed / find_armed_entry / clear_armed are spec-scoped
  2. two specs coexist on one caster; clear removes only the match
  3. melee_only spec rejects a ranged hit; any-weapon spec accepts it
  4. bonus_damage_die rolls (scales with upcast); None → 0
  5. on fail → applies the spec's condition; success → none; clears
  6. the two shipped specs carry the right parameters
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import smite_rider
from engine.core.smite_rider import SmiteRiderSpec
from engine.core.searing_smite import SEARING_SMITE_SPEC
from engine.core.ensnaring_strike import ENSNARING_STRIKE_SPEC
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"

_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True,
                                   schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _abilities(str_score=14):
    return {a: {"score": (str_score if a == "str" else 12),
                  "save": ((str_score if a == "str" else 12) - 10) // 2}
              for a in ("str", "dex", "con", "int", "wis", "cha")}


def _actor(actor_id, *, side="pc", hp=40, ac=14, str_score=14):
    template = {"id": "t", "name": actor_id, "abilities": _abilities(str_score),
                "cr": {"proficiency_bonus": 2}, "actions": []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                   hp_current=hp, hp_max=hp, ac=ac, speed={"walk": 30},
                   position=(0, 0), abilities=_abilities(str_score))


def _state(actors, registry=None):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    if registry is not None:
        st.content_registry = registry
    return st


# A synthetic spec to prove the core is content-agnostic — reuses
# co_ensnared as a convenient existing condition.
_TEST_SPEC = SmiteRiderSpec(
    key="test_smite", marker_primitive="test_smite_armed",
    named_effect="test_smite", default_action_id="a_test_smite",
    save_ability="dexterity", on_fail_condition="co_ensnared",
    melee_only=False, bonus_damage_die=8, bonus_scales_with_upcast=True,
)


# ============================================================================
# Layers 1+2: marker lifecycle, spec-scoped
# ============================================================================

class MarkerLifecycleTest(unittest.TestCase):

    def test_register_find_clear_scoped(self) -> None:
        caster = _actor("c")
        state = _state([caster])
        smite_rider.register_armed(caster, SEARING_SMITE_SPEC,
                                     spell_save_dc=13, action_id="a",
                                     state=state, slot_level=1)
        self.assertIsNotNone(
            smite_rider.find_armed_entry(caster, SEARING_SMITE_SPEC))
        smite_rider.clear_armed(caster, SEARING_SMITE_SPEC)
        self.assertIsNone(
            smite_rider.find_armed_entry(caster, SEARING_SMITE_SPEC))

    def test_two_specs_coexist_clear_only_match(self) -> None:
        caster = _actor("c")
        state = _state([caster])
        smite_rider.register_armed(caster, SEARING_SMITE_SPEC,
                                     spell_save_dc=13, action_id="a",
                                     state=state)
        smite_rider.register_armed(caster, ENSNARING_STRIKE_SPEC,
                                     spell_save_dc=13, action_id="b",
                                     state=state)
        smite_rider.clear_armed(caster, SEARING_SMITE_SPEC)
        # Searing gone, Ensnaring still armed
        self.assertIsNone(
            smite_rider.find_armed_entry(caster, SEARING_SMITE_SPEC))
        self.assertIsNotNone(
            smite_rider.find_armed_entry(caster, ENSNARING_STRIKE_SPEC))


# ============================================================================
# Layers 3+4: weapon-kind gate + bonus damage
# ============================================================================

class FollowupMechanicsTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_melee_only_rejects_ranged(self) -> None:
        caster = _actor("c")
        foe = _actor("foe", side="enemy", str_score=6)
        state = _state([caster, foe], registry=_registry())
        smite_rider.register_armed(caster, SEARING_SMITE_SPEC,
                                     spell_save_dc=25, action_id="a",
                                     state=state)
        state.current_attack = {"actor": caster, "target": foe,
                                  "action": {"id": "a"}, "state": "hit"}
        out = smite_rider.try_apply_followup(
            caster, foe, state, {"kind": "ranged"}, random.Random(1),
            False, SEARING_SMITE_SPEC)
        self.assertEqual(out, 0)
        # Still armed (didn't consume on a non-qualifying swing)
        self.assertIsNotNone(
            smite_rider.find_armed_entry(caster, SEARING_SMITE_SPEC))

    def test_any_weapon_accepts_ranged(self) -> None:
        caster = _actor("c")
        foe = _actor("foe", side="enemy", str_score=6)
        state = _state([caster, foe], registry=_registry())
        smite_rider.register_armed(caster, ENSNARING_STRIKE_SPEC,
                                     spell_save_dc=25, action_id="a",
                                     state=state)
        state.current_attack = {"actor": caster, "target": foe,
                                  "action": {"id": "a"}, "state": "hit"}
        smite_rider.try_apply_followup(
            caster, foe, state, {"kind": "ranged"}, random.Random(1),
            False, ENSNARING_STRIKE_SPEC)
        self.assertTrue(any(c.get("condition_id") == "co_ensnared"
                              for c in foe.applied_conditions))

    def test_bonus_damage_die_rolls_and_scales(self) -> None:
        caster = _actor("c")
        foe = _actor("foe", side="enemy", hp=200, ac=10, str_score=16)
        state = _state([caster, foe], registry=_registry())
        # Upcast to slot 3 → 1 + 2 = 3 dice of d8 (3-24)
        smite_rider.register_armed(caster, _TEST_SPEC, spell_save_dc=1,
                                     action_id="a", state=state, slot_level=3)
        state.current_attack = {"actor": caster, "target": foe,
                                  "action": {"id": "a"}, "state": "hit"}
        dmg = smite_rider.try_apply_followup(
            caster, foe, state, {"kind": "melee"}, random.Random(1),
            False, _TEST_SPEC)
        self.assertGreaterEqual(dmg, 3)
        self.assertLessEqual(dmg, 24)

    def test_no_bonus_die_returns_zero(self) -> None:
        caster = _actor("c")
        foe = _actor("foe", side="enemy", str_score=6)
        state = _state([caster, foe], registry=_registry())
        smite_rider.register_armed(caster, ENSNARING_STRIKE_SPEC,
                                     spell_save_dc=25, action_id="a",
                                     state=state)
        state.current_attack = {"actor": caster, "target": foe,
                                  "action": {"id": "a"}, "state": "hit"}
        dmg = smite_rider.try_apply_followup(
            caster, foe, state, {"kind": "melee"}, random.Random(1),
            False, ENSNARING_STRIKE_SPEC)
        self.assertEqual(dmg, 0)


# ============================================================================
# Layer 5: save outcome + marker consume
# ============================================================================

class SaveOutcomeTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_fail_applies_condition_and_clears(self) -> None:
        caster = _actor("c")
        foe = _actor("foe", side="enemy", str_score=6)
        state = _state([caster, foe], registry=_registry())
        smite_rider.register_armed(caster, _TEST_SPEC, spell_save_dc=25,
                                     action_id="a", state=state)
        state.current_attack = {"actor": caster, "target": foe,
                                  "action": {"id": "a"}, "state": "hit"}
        smite_rider.try_apply_followup(
            caster, foe, state, {"kind": "melee"}, random.Random(1),
            False, _TEST_SPEC)
        self.assertTrue(any(c.get("condition_id") == "co_ensnared"
                              for c in foe.applied_conditions))
        self.assertIsNone(
            smite_rider.find_armed_entry(caster, _TEST_SPEC))

    def test_success_no_condition_still_clears(self) -> None:
        caster = _actor("c")
        foe = _actor("foe", side="enemy", str_score=18)
        state = _state([caster, foe], registry=_registry())
        smite_rider.register_armed(caster, _TEST_SPEC, spell_save_dc=1,
                                     action_id="a", state=state)
        state.current_attack = {"actor": caster, "target": foe,
                                  "action": {"id": "a"}, "state": "hit"}
        smite_rider.try_apply_followup(
            caster, foe, state, {"kind": "melee"}, random.Random(1),
            False, _TEST_SPEC)
        self.assertFalse(any(c.get("condition_id") == "co_ensnared"
                               for c in foe.applied_conditions))
        self.assertIsNone(
            smite_rider.find_armed_entry(caster, _TEST_SPEC))


# ============================================================================
# Layer 6: shipped specs carry the right parameters
# ============================================================================

class SpecParametersTest(unittest.TestCase):

    def test_searing_spec(self) -> None:
        s = SEARING_SMITE_SPEC
        self.assertEqual(s.save_ability, "constitution")
        self.assertEqual(s.on_fail_condition, "co_ignited")
        self.assertTrue(s.melee_only)
        self.assertEqual(s.bonus_damage_die, 6)
        self.assertTrue(s.bonus_scales_with_upcast)

    def test_ensnaring_spec(self) -> None:
        s = ENSNARING_STRIKE_SPEC
        self.assertEqual(s.save_ability, "strength")
        self.assertEqual(s.on_fail_condition, "co_ensnared")
        self.assertFalse(s.melee_only)
        self.assertIsNone(s.bonus_damage_die)


if __name__ == "__main__":
    unittest.main()
