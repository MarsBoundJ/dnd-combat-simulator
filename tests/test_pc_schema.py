"""PC Schema v1 tests — compact-spec → full-template derivation.

Layers:
  1. Pure-math derivations: PB by level, HP by class+level+CON, AC,
     ability mod, save bonus computation
  2. Build a full template from a compact PC spec; verify shape +
     derived values
  3. Loader integration: `_build_actor` with `pc:` key builds an Actor
     with the right HP / AC / abilities
  4. End-to-end: PC-schema fixture runs through the CLI and behaves
     correctly (Level 3 Fighter takes down a goblin)

Run via:
    python -m unittest tests.test_pc_schema
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

from engine.pc_schema import (
    build_pc_template,
    _compute_hp, _compute_ac, _lookup_pb,
    _build_abilities_with_saves,
    _build_weapon_action,
    _resolve_ability_scores,
)


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


# ============================================================================
# Helpers
# ============================================================================

def _registry():
    """Load the full content registry once per test class."""
    from engine.loader import load_content
    return load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)


def _ability_scores(str_=10, dex=10, con=10, int_=10, wis=10, cha=10):
    return _resolve_ability_scores({
        "str": str_, "dex": dex, "con": con,
        "int": int_, "wis": wis, "cha": cha,
    })


# ============================================================================
# Pure-math derivations
# ============================================================================

class ProficiencyBonusTest(unittest.TestCase):

    def setUp(self):
        self.fighter = _registry().get("class", "c_fighter")

    def test_pb_level_1(self):
        self.assertEqual(_lookup_pb(self.fighter, 1), 2)

    def test_pb_level_4(self):
        self.assertEqual(_lookup_pb(self.fighter, 4), 2)

    def test_pb_level_5(self):
        self.assertEqual(_lookup_pb(self.fighter, 5), 3)

    def test_pb_level_9(self):
        self.assertEqual(_lookup_pb(self.fighter, 9), 4)

    def test_pb_level_17(self):
        self.assertEqual(_lookup_pb(self.fighter, 17), 6)

    def test_pb_missing_level_falls_back_to_raw(self):
        # Pass an empty class def → no level_table entry → 5e RAW fallback
        self.assertEqual(_lookup_pb({}, 1), 2)
        self.assertEqual(_lookup_pb({}, 5), 3)
        self.assertEqual(_lookup_pb({}, 17), 6)


class HitPointsTest(unittest.TestCase):

    def test_level_1_d10_con_14(self):
        # L1 = max(d10) + CON_mod = 10 + 2 = 12
        self.assertEqual(_compute_hp("d10", 1, con_mod=2), 12)

    def test_level_3_d10_con_2(self):
        # L1: 10 + 2 = 12
        # L2: + (6 + 2) = +8 → 20
        # L3: + (6 + 2) = +8 → 28
        self.assertEqual(_compute_hp("d10", 3, con_mod=2), 28)

    def test_level_1_d6_con_negative_2(self):
        # L1 = max(d6) + (-2) = 6 - 2 = 4
        self.assertEqual(_compute_hp("d6", 1, con_mod=-2), 4)

    def test_hp_floor_at_1(self):
        # Pathological: negative CON keeps HP at floor of 1
        self.assertEqual(_compute_hp("d6", 1, con_mod=-100), 1)


class ACTest(unittest.TestCase):

    def test_unarmored_uses_dex_only(self):
        abilities = _ability_scores(dex=16)   # +3
        self.assertEqual(_compute_ac({}, abilities), 13)

    def test_plate_no_dex_cap(self):
        abilities = _ability_scores(dex=16)
        ac = _compute_ac({"base_ac": 18}, abilities)
        # No max_dex_bonus → full DEX mod adds → 18 + 3 = 21
        self.assertEqual(ac, 21)

    def test_chain_mail_caps_dex_at_2(self):
        abilities = _ability_scores(dex=16)   # +3 mod
        ac = _compute_ac({"base_ac": 16, "max_dex_bonus": 2}, abilities)
        # base 16 + min(3, 2) = 18
        self.assertEqual(ac, 18)

    def test_low_dex_below_cap(self):
        abilities = _ability_scores(dex=10)   # +0
        ac = _compute_ac({"base_ac": 14, "max_dex_bonus": 2}, abilities)
        # base 14 + min(0, 2) = 14
        self.assertEqual(ac, 14)


class SaveBonusesTest(unittest.TestCase):

    def test_fighter_proficient_in_str_and_con(self):
        abilities = _ability_scores(str_=16, con=14)
        save_profs = {"strength", "constitution"}
        result = _build_abilities_with_saves(abilities, save_profs,
                                                proficiency_bonus=2)
        # STR mod +3 + PB +2 = +5
        self.assertEqual(result["str"]["save"], 5)
        # CON mod +2 + PB +2 = +4
        self.assertEqual(result["con"]["save"], 4)
        # DEX not proficient: mod 0 + 0 = 0
        self.assertEqual(result["dex"]["save"], 0)
        # WIS not proficient: mod 0 + 0 = 0
        self.assertEqual(result["wis"]["save"], 0)

    def test_no_proficiencies_just_modifiers(self):
        abilities = _ability_scores(str_=14, wis=18)
        result = _build_abilities_with_saves(abilities, set(),
                                                proficiency_bonus=3)
        self.assertEqual(result["str"]["save"], 2)
        self.assertEqual(result["wis"]["save"], 4)


# ============================================================================
# Weapon action generation
# ============================================================================

class WeaponActionTest(unittest.TestCase):

    def test_str_melee_weapon(self):
        abilities = _ability_scores(str_=16)   # +3
        weapon = {
            "id": "a_sword", "name": "Longsword",
            "attack_ability": "str",
            "damage_dice": "1d8",
            "damage_type": "slashing",
            "reach_ft": 5,
        }
        action = _build_weapon_action(weapon, abilities, proficiency_bonus=2)
        self.assertEqual(action["id"], "a_sword")
        self.assertEqual(action["type"], "weapon_attack")
        attack_step = action["pipeline"][0]
        # +3 ability + 2 PB = +5 to hit
        self.assertEqual(attack_step["params"]["bonus"], 5)
        self.assertEqual(attack_step["params"]["kind"], "melee")
        self.assertEqual(attack_step["params"]["reach_ft"], 5)
        damage_step = action["pipeline"][1]
        self.assertEqual(damage_step["params"]["modifier"], 3)
        self.assertEqual(damage_step["params"]["type"], "slashing")

    def test_dex_ranged_weapon(self):
        abilities = _ability_scores(dex=16)   # +3
        weapon = {
            "id": "a_bow", "name": "Longbow",
            "attack_ability": "dex",
            "damage_dice": "1d8",
            "damage_type": "piercing",
            "range_ft": 80,
        }
        action = _build_weapon_action(weapon, abilities, proficiency_bonus=3)
        attack_step = action["pipeline"][0]
        # +3 ability + 3 PB = +6 to hit
        self.assertEqual(attack_step["params"]["bonus"], 6)
        self.assertEqual(attack_step["params"]["kind"], "ranged")
        self.assertEqual(attack_step["params"]["range_ft"], 80)
        # No reach_ft for a ranged weapon
        self.assertNotIn("reach_ft", attack_step["params"])
        damage_step = action["pipeline"][1]
        self.assertEqual(damage_step["params"]["modifier"], 3)


# ============================================================================
# End-to-end build_pc_template
# ============================================================================

class BuildPCTemplateTest(unittest.TestCase):

    def setUp(self):
        self.registry = _registry()

    def test_level_3_fighter_full_template(self):
        spec = {
            "class": "c_fighter",
            "level": 3,
            "ability_scores": {"str": 16, "dex": 12, "con": 14,
                                 "int": 10, "wis": 12, "cha": 10},
            "armor": {"base_ac": 16, "max_dex_bonus": 2},
            "weapons": [{
                "id": "a_longsword", "name": "Longsword",
                "attack_ability": "str",
                "damage_dice": "1d8",
                "damage_type": "slashing",
                "reach_ft": 5,
            }],
        }
        template = build_pc_template(spec, self.registry)

        # PB = 2 at level 3
        self.assertEqual(template["cr"]["proficiency_bonus"], 2)
        # AC = 16 base + min(DEX+1, 2) = 17
        self.assertEqual(template["combat"]["armor_class"], 17)
        # HP = 12 (L1: 10 + 2 CON) + 8 + 8 (L2, L3: 6 avg + 2 CON) = 28
        self.assertEqual(template["combat"]["hit_points"]["average"], 28)
        # STR save: +3 mod + PB 2 = +5 (Fighter proficient)
        self.assertEqual(template["abilities"]["str"]["save"], 5)
        # CON save: +2 mod + PB 2 = +4 (Fighter proficient)
        self.assertEqual(template["abilities"]["con"]["save"], 4)
        # DEX save: +1 mod, not proficient = +1
        self.assertEqual(template["abilities"]["dex"]["save"], 1)
        # WIS save: +1 mod, not proficient = +1
        self.assertEqual(template["abilities"]["wis"]["save"], 1)
        # One weapon action, longsword with +5 to hit
        self.assertEqual(len(template["actions"]), 1)
        self.assertEqual(
            template["actions"][0]["pipeline"][0]["params"]["bonus"], 5)

    def test_missing_class_raises(self):
        spec = {"level": 1}
        with self.assertRaises(ValueError):
            build_pc_template(spec, self.registry)

    def test_invalid_level_raises(self):
        spec = {"class": "c_fighter", "level": 25}
        with self.assertRaises(ValueError):
            build_pc_template(spec, self.registry)

    def test_unknown_class_raises_keyerror(self):
        spec = {"class": "c_not_a_real_class", "level": 1}
        with self.assertRaises(KeyError):
            build_pc_template(spec, self.registry)

    def test_behavior_profile_passes_through(self):
        spec = {
            "class": "c_fighter", "level": 1,
            "ability_scores": {"str": 14},
            "behavior_profile": {
                "archetype": "berserker_fanatic",
                "presets": {"retreat": "ftd"},
            },
        }
        template = build_pc_template(spec, self.registry)
        self.assertEqual(
            template["behavior_profile"]["archetype"],
            "berserker_fanatic",
        )


# ============================================================================
# Loader integration via _build_actor
# ============================================================================

class BuildActorPCSchemaTest(unittest.TestCase):

    def test_pc_actor_spec_produces_actor(self):
        from engine.cli import _build_actor

        registry = _registry()
        actor_spec = {
            "instance_id": "test_fighter",
            "name": "Test Fighter",
            "side": "pc",
            "position": [0, 0],
            "pc": {
                "class": "c_fighter",
                "level": 3,
                "ability_scores": {"str": 16, "dex": 12, "con": 14,
                                     "int": 10, "wis": 12, "cha": 10},
                "armor": {"base_ac": 16, "max_dex_bonus": 2},
                "weapons": [{
                    "id": "a_longsword", "name": "Longsword",
                    "attack_ability": "str",
                    "damage_dice": "1d8",
                    "damage_type": "slashing",
                    "reach_ft": 5,
                }],
            },
        }
        actor = _build_actor(actor_spec, registry)
        self.assertEqual(actor.id, "test_fighter")
        self.assertEqual(actor.hp_max, 28)
        self.assertEqual(actor.ac, 17)
        self.assertEqual(actor.abilities["str"]["save"], 5)
        # Template tagged for telemetry
        self.assertEqual(
            actor.template["derived_from_pc_schema"]["class"], "c_fighter")
        self.assertEqual(
            actor.template["derived_from_pc_schema"]["level"], 3)

    def test_pc_schema_coexists_with_template_ref(self):
        """A fixture can mix PC-schema PCs and template_ref monsters."""
        from engine.cli import _build_actor

        registry = _registry()
        # Monster via template_ref (existing path)
        monster_spec = {
            "instance_id": "g1", "side": "enemy",
            "template_ref": {"entity_type": "monster",
                              "id": "m_goblin_warrior"},
        }
        monster = _build_actor(monster_spec, registry)
        self.assertEqual(monster.id, "g1")

        # PC via new pc: key
        pc_spec = {
            "instance_id": "p1", "side": "pc",
            "pc": {"class": "c_fighter", "level": 1,
                    "ability_scores": {"con": 14}},
        }
        pc = _build_actor(pc_spec, registry)
        self.assertEqual(pc.id, "p1")
        self.assertEqual(pc.hp_max, 12)   # d10 + 2 CON


# ============================================================================
# End-to-end fixture loads + runs cleanly
# ============================================================================

class PCSchemaFixtureTest(unittest.TestCase):

    def test_pc_schema_fighter_fixture_runs(self):
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner
        from engine.cli import _build_encounter
        from engine.loader import load_yaml_file

        fixture = Path(__file__).parent / "fixtures" / \
            "pc_schema_fighter_encounter.yaml"
        registry = _registry()
        spec = load_yaml_file(fixture)
        encounter = _build_encounter(spec, registry)

        primitives_module.set_rng(random.Random(1))
        runner = EncounterRunner.new(encounter, seed=1,
                                       content_registry=registry)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # Encounter terminated with a winner
        self.assertTrue(state.terminated)
        # Fighter and goblin both appear in the actor list
        names = {a.id for a in encounter.actors}
        self.assertIn("fighter_pc", names)
        self.assertIn("goblin_enemy", names)
        # Fighter should have at least attempted an attack via the
        # derived longsword action
        fighter_attacks = [
            e for e in state.event_log
            if e.get("event") == "attack_roll"
            and e.get("actor") == "fighter_pc"
        ]
        self.assertGreater(len(fighter_attacks), 0)


if __name__ == "__main__":
    unittest.main()
