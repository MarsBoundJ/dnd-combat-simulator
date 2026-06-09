"""Battering Roots tests (Path of the World Tree, Barbarian L10).

  - +10 ft reach with Heavy or Versatile MELEE weapons (during your turn;
    NOT rage-gated). Baked into qualifying weapon actions at build time.
  - On a hit with such a weapon on your turn, apply Topple (CON save → Prone)
    even without the mastery.

Layers:
  1. Reach extension (heavy + versatile qualify; non-heavy + ranged don't).
  2. Topple rider on a qualifying on-turn hit; idempotent; off-turn (OA) skip.
  3. Not rage-gated.
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import world_tree as WT
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template

_REPO = Path(__file__).resolve().parent.parent


def _registry():
    return load_content(_REPO / "schema" / "content", validate=True,
                        schema_root=_REPO / "schema")


def _ab():
    return {k: {"score": 14, "save": 0}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _wt_barb(level=10, weapons=None, feature_level=True):
    spec = {"id": "z", "class": "c_barbarian", "level": level,
            "ability_scores": {"str": 20, "dex": 14, "con": 16,
                               "int": 8, "wis": 10, "cha": 8},
            "weapons": weapons or [
                {"id": "a_greataxe", "name": "Greataxe", "damage_dice": "1d12",
                 "damage_type": "slashing", "attack_ability": "str",
                 "reach_ft": 5, "heavy": True}]}
    if feature_level:
        spec["subclass"] = "sc_path_of_the_world_tree"
    tmpl = build_pc_template(spec, _registry())
    ab = _ab()
    return Actor(id="z", name="z", template=tmpl, side="pc",
                 hp_current=80, hp_max=80, ac=16, position=(0, 0),
                 speed={"walk": 40}, abilities=ab)


def _reach_and_flag(actor, action_id):
    for a in actor.template["actions"]:
        if a.get("id") == action_id:
            for s in a["pipeline"]:
                if s["primitive"] == "attack_roll":
                    p = s["params"]
                    return p.get("reach_ft"), p.get("battering_roots")
    return None, None


def _foe(pos=(1, 0)):
    ab = _ab()
    return Actor(id="foe", name="foe",
                 template={"id": "tf", "name": "foe", "abilities": ab,
                           "cr": {"proficiency_bonus": 2}, "actions": []},
                 side="enemy", hp_current=40, hp_max=40, ac=14,
                 position=pos, speed={"walk": 30}, abilities=ab)


class ReachExtensionTest(unittest.TestCase):

    def test_heavy_weapon_reach_extended(self):
        z = _wt_barb()
        reach, flag = _reach_and_flag(z, "a_greataxe")
        self.assertEqual(reach, 15)
        self.assertTrue(flag)

    def test_versatile_weapon_reach_extended(self):
        z = _wt_barb(weapons=[
            {"id": "a_longsword", "name": "Longsword", "damage_dice": "1d8",
             "damage_type": "slashing", "attack_ability": "str",
             "reach_ft": 5, "versatile": True}])
        reach, flag = _reach_and_flag(z, "a_longsword")
        self.assertEqual(reach, 15)
        self.assertTrue(flag)

    def test_non_heavy_weapon_not_extended(self):
        z = _wt_barb(weapons=[
            {"id": "a_shortsword", "name": "Shortsword", "damage_dice": "1d6",
             "damage_type": "piercing", "attack_ability": "str",
             "reach_ft": 5}])
        reach, flag = _reach_and_flag(z, "a_shortsword")
        self.assertEqual(reach, 5)
        self.assertIsNone(flag)

    def test_no_extension_without_feature(self):
        # A plain (non-World-Tree) barbarian with a heavy weapon: no reach.
        z = _wt_barb(feature_level=False)
        reach, flag = _reach_and_flag(z, "a_greataxe")
        self.assertEqual(reach, 5)
        self.assertIsNone(flag)


class ToppleRiderTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def _hit(self, z, foe, on_turn=True):
        st = CombatState(encounter=Encounter(id="e", actors=[z, foe]))
        st.turn_order = ["z", "foe"] if on_turn else ["foe", "z"]
        st.round = 1
        st.current_attack = {"actor": z, "target": foe, "state": "hit",
                              "attack_roll_params": {"kind": "melee",
                                                      "battering_roots": True}}
        primitives_module._damage({"dice": "", "modifier": 5,
                                    "type": "slashing"}, st, EventBus())
        return st

    def test_topple_on_qualifying_on_turn_hit(self):
        z = _wt_barb()
        foe = _foe()
        self._hit(z, foe, on_turn=True)
        self.assertTrue(any(c.get("condition_id") == "co_prone"
                            for c in foe.applied_conditions))

    def test_no_topple_off_turn(self):
        z = _wt_barb()
        foe = _foe()
        self._hit(z, foe, on_turn=False)
        self.assertFalse(any(c.get("condition_id") == "co_prone"
                             for c in foe.applied_conditions))

    def test_idempotent_already_prone(self):
        z = _wt_barb()
        foe = _foe()
        foe.applied_conditions.append({"condition_id": "co_prone"})
        self._hit(z, foe, on_turn=True)
        prone = [c for c in foe.applied_conditions
                 if c.get("condition_id") == "co_prone"]
        self.assertEqual(len(prone), 1)

    def test_no_topple_without_flag(self):
        z = _wt_barb()
        foe = _foe()
        WT.try_apply_battering_roots(z, foe, CombatState(
            encounter=Encounter(id="e", actors=[z, foe])),
            {"kind": "melee"})   # no battering_roots flag
        self.assertFalse(any(c.get("condition_id") == "co_prone"
                             for c in foe.applied_conditions))

    def test_not_rage_gated(self):
        # Battering Roots works without Rage (RAW: "during your turn").
        z = _wt_barb()
        self.assertFalse(getattr(z, "rage_active", False))
        foe = _foe()
        self._hit(z, foe, on_turn=True)
        self.assertTrue(any(c.get("condition_id") == "co_prone"
                            for c in foe.applied_conditions))


if __name__ == "__main__":
    unittest.main()
