"""Weapon Mastery tests (PR #54).

Layers:
  1. validate_mastery + validate_mastery_list
  2. actor_knows_mastery helper
  3. pc_schema: weapon_masteries baked onto template + derived_from
  4. _build_weapon_action bakes the mastery sub-dict into attack_roll
     params when weapon.mastery is set
  5. _attack_roll dispatches to apply_mastery_effects post-resolution
  6. Per-property semantics:
     - Vex: registers advantage_for_self on actor (per_owner_attack)
     - Sap: registers disadvantage_for_self on target (per_owner_attack)
     - Topple: forces CON save; prone applied on fail; no prone on save
     - Graze: deals ability_mod damage on miss; no damage on hit;
       respects resistance / immunity / vulnerability
  7. Dispatch is a no-op when:
     - mastery_params is None / empty
     - actor doesn't know the mastery
     - attack_state doesn't match (Vex/Sap/Topple miss; Graze hit)

Run via:
    python -m unittest tests.test_weapon_mastery
"""
from __future__ import annotations

import random
import unittest
from unittest.mock import MagicMock

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.core.weapon_masteries import (
    KNOWN_MASTERIES, DEFERRED_MASTERIES,
    actor_knows_mastery, apply_mastery_effects,
    validate_mastery, validate_mastery_list,
)
from engine.pc_schema import build_pc_template, _build_weapon_action


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id="a", *, side="pc", position=(0, 0),
                  abilities=None, weapon_masteries=None,
                  applied_conditions=None, hp=30) -> Actor:
    abilities = abilities or {k: {"score": 10, "save": 0}
                                 for k in ("str", "dex", "con",
                                            "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                 "abilities": abilities,
                 "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                 "actions": []}
    actor = Actor(id=actor_id, name=actor_id, template=template, side=side,
                   hp_current=hp, hp_max=hp, ac=14,
                   speed={"walk": 30}, position=position,
                   abilities=abilities,
                   weapon_masteries=list(weapon_masteries or []))
    if applied_conditions:
        actor.applied_conditions = list(applied_conditions)
    return actor


def _state_with(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


class _MockRegistry:
    def __init__(self, classes):
        self._classes = classes
    def get(self, etype, eid):
        if etype != "class":
            raise KeyError(etype)
        if eid not in self._classes:
            raise KeyError(eid)
        return self._classes[eid]


def _fighter_class_def():
    return {
        "id": "c_fighter", "name": "Fighter",
        "core_traits": {"hit_die": "d10",
                         "save_proficiencies": ["strength", "constitution"]},
        "level_table": [
            {"level": 1, "proficiency_bonus": 2,
              "features": ["f_weapon_mastery"],
              "class_resources": {"weapon_mastery_count": 3}},
        ],
    }


def _registry():
    return _MockRegistry({"c_fighter": _fighter_class_def()})


def _base_pc_spec(weapon_masteries=None, weapons=None):
    spec = {
        "class": "c_fighter", "level": 1,
        "ability_scores": {"str": 16, "dex": 14, "con": 14,
                            "int": 10, "wis": 10, "cha": 10},
        "weapons": weapons if weapons is not None else [{
            "id": "a_longsword", "name": "Longsword",
            "attack_ability": "str", "damage_dice": "1d8",
            "damage_type": "slashing", "reach_ft": 5,
        }],
    }
    if weapon_masteries is not None:
        spec["weapon_masteries"] = weapon_masteries
    return spec


# ============================================================================
# Layer 1: validators
# ============================================================================

class ValidatorTest(unittest.TestCase):

    def test_known_v1_set(self) -> None:
        self.assertEqual(KNOWN_MASTERIES,
                            # PR #57: nick promoted from DEFERRED to KNOWN
                            frozenset({"vex", "sap", "topple", "graze",
                                         "nick"}))

    def test_validate_passes(self) -> None:
        for m in KNOWN_MASTERIES:
            self.assertEqual(validate_mastery(m), m)

    def test_validate_normalizes_case(self) -> None:
        self.assertEqual(validate_mastery("VEX"), "vex")
        self.assertEqual(validate_mastery("Topple"), "topple")

    def test_deferred_raises_with_clear_message(self) -> None:
        for m in DEFERRED_MASTERIES:
            with self.assertRaises(ValueError) as ctx:
                validate_mastery(m)
            self.assertIn("deferred", str(ctx.exception).lower())

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            validate_mastery("not_a_mastery")

    def test_list_dedupes_preserving_order(self) -> None:
        result = validate_mastery_list(["vex", "sap", "vex", "topple"])
        self.assertEqual(result, ["vex", "sap", "topple"])

    def test_list_empty_returns_empty(self) -> None:
        self.assertEqual(validate_mastery_list(None), [])
        self.assertEqual(validate_mastery_list([]), [])

    def test_list_non_list_raises(self) -> None:
        with self.assertRaises(ValueError):
            validate_mastery_list("vex")    # str, not list


# ============================================================================
# Layer 2: actor_knows_mastery
# ============================================================================

class KnowsMasteryTest(unittest.TestCase):

    def test_in_list(self) -> None:
        actor = _make_actor(weapon_masteries=["vex", "topple"])
        self.assertTrue(actor_knows_mastery(actor, "vex"))

    def test_not_in_list(self) -> None:
        actor = _make_actor(weapon_masteries=["vex"])
        self.assertFalse(actor_knows_mastery(actor, "topple"))

    def test_empty_list_returns_false(self) -> None:
        actor = _make_actor(weapon_masteries=[])
        self.assertFalse(actor_knows_mastery(actor, "vex"))

    def test_empty_id_returns_false(self) -> None:
        actor = _make_actor(weapon_masteries=["vex"])
        self.assertFalse(actor_knows_mastery(actor, ""))


# ============================================================================
# Layer 3: pc_schema integration
# ============================================================================

class PCSchemaWeaponMasteryTest(unittest.TestCase):

    def test_unknown_mastery_raises(self) -> None:
        spec = _base_pc_spec(weapon_masteries=["not_a_mastery"])
        with self.assertRaises(ValueError):
            build_pc_template(spec, _registry())

    def test_deferred_mastery_raises(self) -> None:
        spec = _base_pc_spec(weapon_masteries=["cleave"])
        with self.assertRaises(ValueError):
            build_pc_template(spec, _registry())

    def test_masteries_baked_on_template(self) -> None:
        spec = _base_pc_spec(weapon_masteries=["vex", "topple"])
        template = build_pc_template(spec, _registry())
        self.assertEqual(template["weapon_masteries"], ["vex", "topple"])

    def test_masteries_in_derived_from(self) -> None:
        spec = _base_pc_spec(weapon_masteries=["vex"])
        template = build_pc_template(spec, _registry())
        self.assertEqual(
            template["derived_from_pc_schema"]["weapon_masteries"],
            ["vex"])

    def test_empty_when_not_specified(self) -> None:
        spec = _base_pc_spec()
        template = build_pc_template(spec, _registry())
        self.assertEqual(template["weapon_masteries"], [])


# ============================================================================
# Layer 4: _build_weapon_action bakes mastery into attack_roll params
# ============================================================================

class BuildWeaponActionMasteryTest(unittest.TestCase):

    def test_no_mastery_omits_key(self) -> None:
        weapon = {"id": "a_lsword", "name": "Longsword",
                    "attack_ability": "str", "damage_dice": "1d8",
                    "damage_type": "slashing", "reach_ft": 5}
        action = _build_weapon_action(
            weapon,
            ability_scores={"str": {"score": 16}, "dex": {"score": 14}},
            proficiency_bonus=2)
        attack_params = action["pipeline"][0]["params"]
        self.assertNotIn("mastery", attack_params)

    def test_mastery_baked_with_full_subdict(self) -> None:
        weapon = {"id": "a_lsword", "name": "Longsword",
                    "attack_ability": "str", "damage_dice": "1d8",
                    "damage_type": "slashing", "reach_ft": 5,
                    "mastery": "topple"}
        action = _build_weapon_action(
            weapon,
            ability_scores={"str": {"score": 16}, "dex": {"score": 14}},
            proficiency_bonus=3)
        mastery = action["pipeline"][0]["params"]["mastery"]
        self.assertEqual(mastery["id"], "topple")
        self.assertEqual(mastery["ability_mod"], 3)       # str 16 → +3
        self.assertEqual(mastery["damage_type"], "slashing")
        self.assertEqual(mastery["save_dc"], 14)           # 8 + 3 + 3

    def test_unknown_mastery_on_weapon_raises(self) -> None:
        weapon = {"id": "a_x", "name": "Bad Weapon",
                    "attack_ability": "str", "damage_dice": "1d6",
                    "damage_type": "slashing", "reach_ft": 5,
                    "mastery": "not_a_mastery"}
        with self.assertRaises(ValueError):
            _build_weapon_action(
                weapon,
                ability_scores={"str": {"score": 16}, "dex": {"score": 14}},
                proficiency_bonus=2)


# ============================================================================
# Layer 5/6: per-property semantics
# ============================================================================

class VexTest(unittest.TestCase):

    def test_hit_registers_advantage_modifier(self) -> None:
        actor = _make_actor("rogue", weapon_masteries=["vex"])
        target = _make_actor("ogre", side="enemy")
        state = _state_with([actor, target])
        apply_mastery_effects({"id": "vex", "ability_mod": 3,
                                  "damage_type": "slashing", "save_dc": 13},
                                 actor, target, "hit", state)
        vex_mods = [m for m in actor.active_modifiers
                       if (m.get("source") or {}).get("id") == "vex"]
        self.assertEqual(len(vex_mods), 1)
        self.assertEqual(vex_mods[0]["params"]["modifier"],
                            "advantage_for_self")
        self.assertEqual(vex_mods[0]["lifetime"], "per_owner_attack")

    def test_miss_does_NOT_register(self) -> None:
        actor = _make_actor("rogue", weapon_masteries=["vex"])
        target = _make_actor("ogre", side="enemy")
        state = _state_with([actor, target])
        apply_mastery_effects({"id": "vex", "ability_mod": 3,
                                  "damage_type": "slashing", "save_dc": 13},
                                 actor, target, "miss", state)
        self.assertEqual(len(actor.active_modifiers), 0)

    def test_actor_without_vex_no_op(self) -> None:
        actor = _make_actor("rogue", weapon_masteries=["sap"])   # not vex
        target = _make_actor("ogre", side="enemy")
        state = _state_with([actor, target])
        apply_mastery_effects({"id": "vex", "ability_mod": 3,
                                  "damage_type": "slashing", "save_dc": 13},
                                 actor, target, "hit", state)
        self.assertEqual(len(actor.active_modifiers), 0)

    def test_crit_also_triggers(self) -> None:
        actor = _make_actor("rogue", weapon_masteries=["vex"])
        target = _make_actor("ogre", side="enemy")
        state = _state_with([actor, target])
        apply_mastery_effects({"id": "vex", "ability_mod": 3,
                                  "damage_type": "slashing", "save_dc": 13},
                                 actor, target, "crit", state)
        vex_mods = [m for m in actor.active_modifiers
                       if (m.get("source") or {}).get("id") == "vex"]
        self.assertEqual(len(vex_mods), 1)


class SapTest(unittest.TestCase):

    def test_hit_registers_disadvantage_on_target(self) -> None:
        actor = _make_actor("rogue", weapon_masteries=["sap"])
        target = _make_actor("ogre", side="enemy")
        state = _state_with([actor, target])
        apply_mastery_effects({"id": "sap", "ability_mod": 3,
                                  "damage_type": "slashing", "save_dc": 13},
                                 actor, target, "hit", state)
        sap_mods = [m for m in target.active_modifiers
                       if (m.get("source") or {}).get("id") == "sap"]
        self.assertEqual(len(sap_mods), 1)
        self.assertEqual(sap_mods[0]["params"]["modifier"],
                            "disadvantage_for_self")
        self.assertEqual(sap_mods[0]["owner_id"], target.id)

    def test_miss_does_NOT_register(self) -> None:
        actor = _make_actor("rogue", weapon_masteries=["sap"])
        target = _make_actor("ogre", side="enemy")
        state = _state_with([actor, target])
        apply_mastery_effects({"id": "sap", "ability_mod": 3,
                                  "damage_type": "slashing", "save_dc": 13},
                                 actor, target, "miss", state)
        self.assertEqual(len(target.active_modifiers), 0)


class ToppleTest(unittest.TestCase):

    def setUp(self) -> None:
        # Deterministic RNG for save rolls
        primitives_module.set_rng(random.Random(1))

    def test_failed_save_applies_prone(self) -> None:
        actor = _make_actor("fighter", weapon_masteries=["topple"])
        # Target with -3 CON save (con 4) → almost certain failure vs DC 14
        target = _make_actor("dummy", side="enemy",
                                abilities={"str": {"score": 10, "save": 0},
                                            "dex": {"score": 10, "save": 0},
                                            "con": {"score": 4, "save": -3},
                                            "int": {"score": 10, "save": 0},
                                            "wis": {"score": 10, "save": 0},
                                            "cha": {"score": 10, "save": 0}})
        state = _state_with([actor, target])
        # Seed produces low d20 — let me just force a low roll via mock
        primitives_module.set_rng(random.Random(1))    # seed 1 → d20=5
        apply_mastery_effects({"id": "topple", "ability_mod": 3,
                                  "damage_type": "slashing", "save_dc": 25},
                                 # DC 25 essentially guarantees fail
                                 actor, target, "hit", state)
        prone_conds = [c for c in target.applied_conditions
                          if c.get("condition_id") == "co_prone"]
        self.assertEqual(len(prone_conds), 1)

    def test_passed_save_no_prone(self) -> None:
        actor = _make_actor("fighter", weapon_masteries=["topple"])
        target = _make_actor("strongman", side="enemy",
                                abilities={"str": {"score": 10, "save": 0},
                                            "dex": {"score": 10, "save": 0},
                                            "con": {"score": 20, "save": 10},
                                            "int": {"score": 10, "save": 0},
                                            "wis": {"score": 10, "save": 0},
                                            "cha": {"score": 10, "save": 0}})
        state = _state_with([actor, target])
        # DC 1 = trivially passed
        apply_mastery_effects({"id": "topple", "ability_mod": 3,
                                  "damage_type": "slashing", "save_dc": 1},
                                 actor, target, "hit", state)
        prone_conds = [c for c in target.applied_conditions
                          if c.get("condition_id") == "co_prone"]
        self.assertEqual(len(prone_conds), 0)

    def test_miss_does_NOT_force_save(self) -> None:
        actor = _make_actor("fighter", weapon_masteries=["topple"])
        target = _make_actor("dummy", side="enemy")
        state = _state_with([actor, target])
        apply_mastery_effects({"id": "topple", "ability_mod": 3,
                                  "damage_type": "slashing", "save_dc": 25},
                                 actor, target, "miss", state)
        # No save event in log
        save_events = [e for e in state.event_log
                          if e.get("event") == "weapon_mastery_save"]
        self.assertEqual(len(save_events), 0)


class GrazeTest(unittest.TestCase):

    def test_miss_deals_ability_mod_damage(self) -> None:
        actor = _make_actor("fighter", weapon_masteries=["graze"])
        target = _make_actor("dummy", side="enemy", hp=30)
        state = _state_with([actor, target])
        apply_mastery_effects({"id": "graze", "ability_mod": 3,
                                  "damage_type": "slashing", "save_dc": 13},
                                 actor, target, "miss", state)
        # 30 - 3 = 27
        self.assertEqual(target.hp_current, 27)

    def test_hit_does_NOT_deal_graze_damage(self) -> None:
        actor = _make_actor("fighter", weapon_masteries=["graze"])
        target = _make_actor("dummy", side="enemy", hp=30)
        state = _state_with([actor, target])
        apply_mastery_effects({"id": "graze", "ability_mod": 3,
                                  "damage_type": "slashing", "save_dc": 13},
                                 actor, target, "hit", state)
        self.assertEqual(target.hp_current, 30)

    def test_zero_ability_mod_no_damage(self) -> None:
        actor = _make_actor("fighter", weapon_masteries=["graze"])
        target = _make_actor("dummy", side="enemy", hp=30)
        state = _state_with([actor, target])
        apply_mastery_effects({"id": "graze", "ability_mod": 0,
                                  "damage_type": "slashing", "save_dc": 13},
                                 actor, target, "miss", state)
        self.assertEqual(target.hp_current, 30)

    def test_resistance_halves_graze(self) -> None:
        actor = _make_actor("fighter", weapon_masteries=["graze"])
        target = _make_actor("dummy", side="enemy", hp=30)
        target.template["damage_resistances"] = ["slashing"]
        state = _state_with([actor, target])
        apply_mastery_effects({"id": "graze", "ability_mod": 4,
                                  "damage_type": "slashing", "save_dc": 13},
                                 actor, target, "miss", state)
        # 4 // 2 = 2 → 30 - 2 = 28
        self.assertEqual(target.hp_current, 28)

    def test_immunity_zeros_graze(self) -> None:
        actor = _make_actor("fighter", weapon_masteries=["graze"])
        target = _make_actor("dummy", side="enemy", hp=30)
        target.template["damage_immunities"] = ["slashing"]
        state = _state_with([actor, target])
        apply_mastery_effects({"id": "graze", "ability_mod": 4,
                                  "damage_type": "slashing", "save_dc": 13},
                                 actor, target, "miss", state)
        self.assertEqual(target.hp_current, 30)


# ============================================================================
# Layer 7: dispatch no-ops
# ============================================================================

class DispatchNoOpTest(unittest.TestCase):

    def test_none_mastery_params_no_op(self) -> None:
        actor = _make_actor("a", weapon_masteries=["vex"])
        target = _make_actor("t", side="enemy")
        state = _state_with([actor, target])
        apply_mastery_effects(None, actor, target, "hit", state)
        self.assertEqual(len(actor.active_modifiers), 0)
        self.assertEqual(len(target.active_modifiers), 0)

    def test_empty_mastery_params_no_op(self) -> None:
        actor = _make_actor("a", weapon_masteries=["vex"])
        target = _make_actor("t", side="enemy")
        state = _state_with([actor, target])
        apply_mastery_effects({}, actor, target, "hit", state)
        self.assertEqual(len(actor.active_modifiers), 0)


if __name__ == "__main__":
    unittest.main()
