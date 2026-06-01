"""Monk on-hit riders — Stunning Strike + Open Hand Technique (Topple)
+ Warrior of the Open Hand subclass wiring + timed-condition expiry.
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import monk_strikes as ms
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template

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


def _monk(*, wis=16, pb=3, focus=5, stun=True, open_hand=False):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    abilities["wis"] = {"score": wis, "save": 0}
    abilities["dex"] = {"score": 16, "save": 3}
    a = Actor(id="monk", name="monk",
               template={"id": "t", "abilities": abilities,
                          "cr": {"proficiency_bonus": pb},
                          "has_stunning_strike": stun,
                          "has_open_hand": open_hand},
               side="pc", hp_current=30, hp_max=30, ac=15,
               speed={"walk": 30}, position=(0, 0), abilities=abilities)
    a.resources = {"focus_points_remaining": focus, "focus_points_max": focus}
    return a


def _foe(con_save=0, dex_save=0):
    ab = {k: {"score": 10, "save": 0}
           for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["con"] = {"score": 10, "save": con_save}
    ab["dex"] = {"score": 10, "save": dex_save}
    return Actor(id="foe", name="foe",
                  template={"id": "f", "abilities": ab,
                             "cr": {"proficiency_bonus": 2}},
                  side="enemy", hp_current=40, hp_max=40, ac=12,
                  speed={"walk": 30}, position=(1, 0), abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [x.id for x in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class StunningStrikeTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_stun_on_failed_save_and_focus_spent(self):
        monk, foe = _monk(focus=5), _foe(con_save=-5)  # low CON → fail
        st = _state([monk, foe])
        st.current_attack = {"actor": monk, "target": foe,
                              "action": {"id": "a_unarmed_strike"}}
        ms.try_apply_stunning_strike(monk, foe, st, {"kind": "melee"},
                                       random.Random(1))
        self.assertTrue(any(c.get("condition_id") == "co_stunned"
                              for c in foe.applied_conditions))
        self.assertEqual(monk.resources["focus_points_remaining"], 4)
        # registered for timed expiry at the Monk's next turn
        self.assertTrue(any(e["condition_id"] == "co_stunned"
                              and e["source_id"] == "monk"
                              for e in st.timed_conditions))

    def test_no_stun_without_focus(self):
        monk, foe = _monk(focus=0), _foe(con_save=-5)
        st = _state([monk, foe])
        st.current_attack = {"actor": monk, "target": foe,
                              "action": {"id": "a_unarmed_strike"}}
        ms.try_apply_stunning_strike(monk, foe, st, {"kind": "melee"},
                                       random.Random(1))
        self.assertFalse(any(c.get("condition_id") == "co_stunned"
                               for c in foe.applied_conditions))

    def test_once_per_turn(self):
        monk, foe = _monk(focus=5), _foe(con_save=-5)
        st = _state([monk, foe])
        st.current_attack = {"actor": monk, "target": foe,
                              "action": {"id": "a_unarmed_strike"}}
        ms.try_apply_stunning_strike(monk, foe, st, {"kind": "melee"},
                                       random.Random(1))
        ms.try_apply_stunning_strike(monk, foe, st, {"kind": "melee"},
                                       random.Random(1))
        # Only one Focus Point spent (5 → 4), not two
        self.assertEqual(monk.resources["focus_points_remaining"], 4)

    def test_ranged_does_not_trigger(self):
        monk, foe = _monk(focus=5), _foe(con_save=-5)
        st = _state([monk, foe])
        st.current_attack = {"actor": monk, "target": foe,
                              "action": {"id": "x"}}
        ms.try_apply_stunning_strike(monk, foe, st, {"kind": "ranged"},
                                       random.Random(1))
        self.assertEqual(monk.resources["focus_points_remaining"], 5)


class OpenHandTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_topple_prone_on_failed_dex_save(self):
        monk = _monk(open_hand=True, stun=False)
        foe = _foe(dex_save=-5)  # low DEX → fail
        st = _state([monk, foe])
        st.current_attack = {"actor": monk, "target": foe,
                              "action": {"id": "a_unarmed_strike"}}
        ms.try_apply_open_hand(monk, foe, st, {"kind": "melee"},
                                 random.Random(1))
        self.assertTrue(any(c.get("condition_id") == "co_prone"
                              for c in foe.applied_conditions))

    def test_open_hand_once_per_turn(self):
        monk = _monk(open_hand=True, stun=False)
        foe = _foe(dex_save=-5)
        st = _state([monk, foe])
        st.current_attack = {"actor": monk, "target": foe,
                              "action": {"id": "a_unarmed_strike"}}
        ms.try_apply_open_hand(monk, foe, st, {"kind": "melee"},
                                 random.Random(1))
        self.assertTrue(getattr(monk, "_open_hand_used_this_turn", False))


class TimedExpiryTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_stun_expires_at_source_next_turn(self):
        monk, foe = _monk(focus=5), _foe(con_save=-5)
        st = _state([monk, foe])
        st.current_attack = {"actor": monk, "target": foe,
                              "action": {"id": "a_unarmed_strike"}}
        ms.try_apply_stunning_strike(monk, foe, st, {"kind": "melee"},
                                       random.Random(1))
        self.assertTrue(any(c.get("condition_id") == "co_stunned"
                              for c in foe.applied_conditions))
        # The runner scrubs source-timed conditions at the source's
        # turn_start (see EncounterRunner.tick). Exercise that path by
        # ticking with the Monk as the current actor; the stun must clear.
        from engine.core.runner import EncounterRunner
        st.turn_order = ["monk", "foe"]
        st.current_turn_index = 0  # Monk's turn starts → scrub fires
        runner = EncounterRunner.new(st.encounter, seed=1)
        runner.tick(st)
        self.assertFalse(any(c.get("condition_id") == "co_stunned"
                               for c in foe.applied_conditions))
        self.assertEqual(st.timed_conditions, [])


class SubclassWiringTest(unittest.TestCase):

    def test_open_hand_monk_l6_wired(self):
        t = build_pc_template(
            {"id": "m", "class": "c_monk", "level": 6,
              "subclass": "sc_warrior_of_the_open_hand",
              "ability_scores": {"str": 10, "dex": 16, "con": 14,
                                   "int": 8, "wis": 16, "cha": 10},
              "weapons": []}, _registry())
        feats = set(t.get("features_known", []))
        self.assertIn("f_open_hand_technique", feats)
        self.assertIn("f_wholeness_of_body", feats)
        self.assertTrue(t.get("has_open_hand"))
        self.assertTrue(t.get("has_stunning_strike"))  # L5 base feature


if __name__ == "__main__":
    unittest.main()
