"""Branches of the Tree tests (Path of the World Tree, Barbarian L6).

A reaction when a creature starts its turn within 30 ft of a raging World
Tree barbarian: STR save (DC 8 + STR + PB) or be teleported adjacent to the
barbarian and have its Speed reduced to 0 for the turn.

Layers:
  1. Eligibility (feature + raging + enemy + within 30 ft + visible).
  2. execute_branches_pull: fail → teleport adjacent + Speed 0; success → no
     change.
  3. restore_branches_speed (next turn).
  4. Reaction dispatch (fires vs eligible mover; skips ally / out-of-range /
     non-raging).
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import rage as R
from engine.core import world_tree as WT
from engine.core.events import EventBus
from engine.core.reactions import resolve_reaction_triggers
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template

_REPO = Path(__file__).resolve().parent.parent


def _registry():
    return load_content(_REPO / "schema" / "content", validate=True,
                        schema_root=_REPO / "schema")


def _ab(str_save=0):
    d = {k: {"score": 10, "save": 0}
         for k in ("str", "dex", "con", "int", "wis", "cha")}
    d["str"] = {"score": 10, "save": str_save}
    return d


def _barb(level=6, pos=(0, 0)):
    spec = {"id": "z", "class": "c_barbarian", "level": level,
            "subclass": "sc_path_of_the_world_tree",
            "ability_scores": {"str": 18, "dex": 14, "con": 16,
                               "int": 8, "wis": 10, "cha": 8},
            "weapons": [{"id": "a_greataxe", "name": "Greataxe",
                         "damage_dice": "1d12", "damage_type": "slashing",
                         "attack_ability": "str", "reach_ft": 5,
                         "heavy": True}]}
    tmpl = build_pc_template(spec, _registry())
    ab = {k: {"score": 16, "save": 1}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id="z", name="z", template=tmpl, side="pc",
                 hp_current=70, hp_max=70, ac=16, position=pos,
                 speed={"walk": 40}, abilities=ab)


def _enemy(aid="foe", pos=(5, 0), str_save=0, side="enemy"):
    ab = _ab(str_save)
    return Actor(id=aid, name=aid,
                 template={"id": f"t_{aid}", "name": aid, "abilities": ab,
                           "cr": {"proficiency_bonus": 2}, "actions": []},
                 side=side, hp_current=40, hp_max=40, ac=14,
                 position=pos, speed={"walk": 30}, abilities=ab)


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class EligibilityTest(unittest.TestCase):

    def test_eligible_raging_enemy_in_range(self):
        b = _barb()
        foe = _enemy(pos=(5, 0))
        st = _state([b, foe])
        R.enter_rage(b, st)
        self.assertTrue(WT.branches_eligible_reactor(b, foe, st))

    def test_not_eligible_without_rage(self):
        b = _barb()
        foe = _enemy(pos=(5, 0))
        st = _state([b, foe])
        self.assertFalse(WT.branches_eligible_reactor(b, foe, st))

    def test_not_eligible_out_of_range(self):
        b = _barb()
        foe = _enemy(pos=(7, 0))   # 35 ft
        st = _state([b, foe])
        R.enter_rage(b, st)
        self.assertFalse(WT.branches_eligible_reactor(b, foe, st))

    def test_not_eligible_against_ally(self):
        b = _barb()
        ally = _enemy("ally", pos=(2, 0), side="pc")
        st = _state([b, ally])
        R.enter_rage(b, st)
        self.assertFalse(WT.branches_eligible_reactor(b, ally, st))


class ExecuteTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(5))

    def test_fail_teleports_adjacent_and_zeros_speed(self):
        b = _barb(pos=(0, 0))
        foe = _enemy(pos=(5, 0), str_save=-100)   # always fails
        st = _state([b, foe])
        R.enter_rage(b, st)
        WT.execute_branches_pull(b, foe, st)
        from engine.core.geometry import distance_ft
        self.assertLessEqual(distance_ft(b.position, foe.position), 5)
        self.assertEqual(foe.speed.get("walk"), 0)

    def test_success_no_change(self):
        b = _barb(pos=(0, 0))
        foe = _enemy(pos=(5, 0), str_save=100)   # always saves
        st = _state([b, foe])
        R.enter_rage(b, st)
        WT.execute_branches_pull(b, foe, st)
        self.assertEqual(foe.position, (5, 0))
        self.assertEqual(foe.speed.get("walk"), 30)

    def test_restore_speed(self):
        b = _barb(pos=(0, 0))
        foe = _enemy(pos=(5, 0), str_save=-100)
        st = _state([b, foe])
        R.enter_rage(b, st)
        WT.execute_branches_pull(b, foe, st)
        self.assertEqual(foe.speed.get("walk"), 0)
        WT.restore_branches_speed(foe, st)
        self.assertEqual(foe.speed.get("walk"), 30)

    def test_save_event_logged(self):
        b = _barb()
        foe = _enemy(pos=(5, 0), str_save=-100)
        st = _state([b, foe])
        R.enter_rage(b, st)
        WT.execute_branches_pull(b, foe, st)
        events = [e.get("event") for e in st.event_log]
        self.assertIn("branches_of_the_tree_save", events)
        self.assertIn("branches_of_the_tree_pull", events)


class ReactionDispatchTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(5))

    def test_reaction_on_template(self):
        b = _barb()
        self.assertTrue(any(a.get("id") == "a_branches_of_the_tree"
                            for a in b.template["actions"]))

    def test_fires_against_eligible_mover(self):
        b = _barb(pos=(0, 0))
        foe = _enemy(pos=(5, 0), str_save=-100)
        st = _state([b, foe])
        R.enter_rage(b, st)
        fired = resolve_reaction_triggers(
            "creature_turn_start", {"mover": foe, "target": foe},
            st, EventBus())
        self.assertEqual(fired, 1)
        self.assertEqual(foe.speed.get("walk"), 0)

    def test_no_fire_on_ally_turn_start(self):
        b = _barb(pos=(0, 0))
        ally = _enemy("ally", pos=(2, 0), side="pc")
        st = _state([b, ally])
        R.enter_rage(b, st)
        fired = resolve_reaction_triggers(
            "creature_turn_start", {"mover": ally, "target": ally},
            st, EventBus())
        self.assertEqual(fired, 0)

    def test_no_fire_when_not_raging(self):
        b = _barb(pos=(0, 0))
        foe = _enemy(pos=(5, 0), str_save=-100)
        st = _state([b, foe])
        fired = resolve_reaction_triggers(
            "creature_turn_start", {"mover": foe, "target": foe},
            st, EventBus())
        self.assertEqual(fired, 0)

    def test_reaction_consumed(self):
        b = _barb(pos=(0, 0))
        foe = _enemy(pos=(5, 0), str_save=-100)
        st = _state([b, foe])
        R.enter_rage(b, st)
        resolve_reaction_triggers(
            "creature_turn_start", {"mover": foe, "target": foe},
            st, EventBus())
        self.assertTrue(b.actions_used_this_turn["reaction"])


if __name__ == "__main__":
    unittest.main()
