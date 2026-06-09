"""Inspiring Movement tests (College of Dance, Bard L6).

A reaction when an enemy ends its turn within 5 ft: spend a Bardic Inspiration
use, move the Bard up to half Speed away (no OA), and move one nearby ally up
to half Speed away using its Reaction. Agile Strikes also fires (the Bard
punches the adjacent enemy as part of the Reaction).
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import college_of_dance as CD
from engine.core.events import EventBus
from engine.core.geometry import distance_ft
from engine.core.reactions import resolve_reaction_triggers
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template

_REPO = Path(__file__).resolve().parent.parent
_REG = None


def _reg():
    global _REG
    if _REG is None:
        _REG = load_content(_REPO / "schema" / "content", validate=True,
                            schema_root=_REPO / "schema")
    return _REG


def _ab():
    d = {k: {"score": 10, "save": 0}
         for k in ("str", "dex", "con", "int", "wis", "cha")}
    d["dex"] = {"score": 16, "save": 3}
    return d


def _bard(level=6, pos=(2, 0)):
    t = build_pc_template({"id": "b", "class": "c_bard", "level": level,
                           "subclass": "sc_college_of_dance",
                           "ability_scores": {"str": 8, "dex": 16, "con": 12,
                                              "int": 10, "wis": 12,
                                              "cha": 18}}, _reg())
    b = Actor(id="b", name="b", template=t, side="pc", hp_current=30,
              hp_max=30, ac=15, position=pos, speed={"walk": 30},
              abilities=_ab())
    b.resources = {"bardic_inspiration_uses_remaining": 3,
                   "bardic_inspiration_uses_max": 3}
    return b


def _plain(aid, side="pc", pos=(3, 0), hp=30):
    ab = _ab()
    return Actor(id=aid, name=aid,
                 template={"id": f"t_{aid}", "name": aid, "abilities": ab,
                           "cr": {"proficiency_bonus": 2}, "actions": []},
                 side=side, hp_current=hp, hp_max=hp, ac=12,
                 position=pos, speed={"walk": 30}, abilities=ab)


def _state(actors):
    st = CombatState(encounter=Encounter(id="e", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _reg()
    return st


class EligibilityTest(unittest.TestCase):

    def test_eligible_enemy_within_5ft(self):
        b = _bard(pos=(2, 0))
        foe = _plain("foe", side="enemy", pos=(2, 0))
        st = _state([b, foe])
        self.assertTrue(CD.inspiring_movement_eligible(b, foe, st))

    def test_not_eligible_far_enemy(self):
        b = _bard(pos=(2, 0))
        foe = _plain("foe", side="enemy", pos=(8, 0))   # 30 ft
        st = _state([b, foe])
        self.assertFalse(CD.inspiring_movement_eligible(b, foe, st))

    def test_not_eligible_ally(self):
        b = _bard(pos=(2, 0))
        ally = _plain("ally", side="pc", pos=(2, 0))
        st = _state([b, ally])
        self.assertFalse(CD.inspiring_movement_eligible(b, ally, st))

    def test_not_eligible_at_l3(self):
        b = _bard(level=3, pos=(2, 0))
        foe = _plain("foe", side="enemy", pos=(2, 0))
        st = _state([b, foe])
        self.assertFalse(CD.inspiring_movement_eligible(b, foe, st))


class ReactionTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def _fire(self, actors, mover):
        st = _state(actors)
        return resolve_reaction_triggers(
            "creature_turn_end", {"mover": mover, "target": mover},
            st, EventBus()), st

    def test_reaction_on_template(self):
        self.assertTrue(any(a.get("id") == "a_inspiring_movement"
                            for a in _bard().template["actions"]))

    def test_bard_moves_away_and_spends_bi(self):
        b = _bard(pos=(2, 0))
        foe = _plain("foe", side="enemy", pos=(2, 0))
        d0 = distance_ft(b.position, foe.position)
        fired, st = self._fire([b, foe], foe)
        self.assertEqual(fired, 1)
        self.assertGreater(distance_ft(b.position, foe.position), d0)
        self.assertEqual(b.resources["bardic_inspiration_uses_remaining"], 2)
        self.assertTrue(b.actions_used_this_turn["reaction"])

    def test_ally_repositions_and_uses_reaction(self):
        b = _bard(pos=(2, 0))
        ally = _plain("ally", side="pc", pos=(3, 0))
        foe = _plain("foe", side="enemy", pos=(2, 0))
        ally0 = ally.position
        fired, st = self._fire([b, ally, foe], foe)
        self.assertNotEqual(ally.position, ally0)
        self.assertTrue(ally.actions_used_this_turn["reaction"])

    def test_no_reaction_far_enemy(self):
        b = _bard(pos=(2, 0))
        foe = _plain("foe", side="enemy", pos=(8, 0))
        fired, st = self._fire([b, foe], foe)
        self.assertEqual(fired, 0)

    def test_no_reaction_without_bi(self):
        b = _bard(pos=(2, 0))
        b.resources["bardic_inspiration_uses_remaining"] = 0
        foe = _plain("foe", side="enemy", pos=(2, 0))
        fired, st = self._fire([b, foe], foe)
        self.assertEqual(fired, 0)

    def test_agile_strike_hits_adjacent_enemy(self):
        # Dance Bard punches the adjacent triggering enemy as part of the
        # reaction (Agile Strikes on BI expenditure).
        b = _bard(pos=(2, 0))
        foe = _plain("foe", side="enemy", pos=(2, 0), hp=30)
        fired, st = self._fire([b, foe], foe)
        self.assertIn("agile_strike", [e.get("event") for e in st.event_log])


if __name__ == "__main__":
    unittest.main()
