"""Travel along the Tree tests (Path of the World Tree, Barbarian L14).

A Bonus-Action 60-ft teleport-to-engage while raging: reposition toward the
nearest enemy, landing adjacent (instant Dash that ignores terrain + OAs).

Layers:
  1. execute_travel_teleport: closes to melee within 60 ft; no-op when
     already adjacent / no enemies.
  2. Candidate gating: only available while raging (requires_rage_active).
  3. Scoring: high when an enemy is beyond walk but within teleport; low when
     walkable; zero when already in melee.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core import rage as R
from engine.core import world_tree as WT
from engine.core.geometry import distance_ft
from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template

_REPO = Path(__file__).resolve().parent.parent


def _registry():
    return load_content(_REPO / "schema" / "content", validate=True,
                        schema_root=_REPO / "schema")


def _ab():
    return {k: {"score": 16, "save": 1}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _barb(level=14, pos=(0, 0), walk=40):
    spec = {"id": "z", "class": "c_barbarian", "level": level,
            "subclass": "sc_path_of_the_world_tree",
            "ability_scores": {"str": 20, "dex": 14, "con": 18,
                               "int": 8, "wis": 10, "cha": 8},
            "weapons": [{"id": "a_greataxe", "name": "Greataxe",
                         "damage_dice": "1d12", "damage_type": "slashing",
                         "attack_ability": "str", "reach_ft": 5,
                         "heavy": True}]}
    tmpl = build_pc_template(spec, _registry())
    ab = _ab()
    return Actor(id="z", name="z", template=tmpl, side="pc",
                 hp_current=90, hp_max=90, ac=17, position=pos,
                 speed={"walk": walk}, abilities=ab)


def _enemy(pos=(10, 0)):
    ab = _ab()
    return Actor(id="foe", name="foe",
                 template={"id": "tf", "name": "foe", "abilities": ab,
                           "cr": {"proficiency_bonus": 3}, "actions": []},
                 side="enemy", hp_current=50, hp_max=50, ac=15,
                 position=pos, speed={"walk": 30}, abilities=ab)


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class TeleportTest(unittest.TestCase):

    def test_closes_to_melee_within_60ft(self):
        b = _barb(pos=(0, 0))
        foe = _enemy(pos=(10, 0))   # 50 ft
        st = _state([b, foe])
        moved = WT.execute_travel_teleport(b, st)
        self.assertTrue(moved)
        self.assertLessEqual(distance_ft(b.position, foe.position), 5)

    def test_noop_when_adjacent(self):
        b = _barb(pos=(0, 0))
        foe = _enemy(pos=(1, 0))   # already 5 ft
        st = _state([b, foe])
        self.assertFalse(WT.execute_travel_teleport(b, st))
        self.assertEqual(b.position, (0, 0))

    def test_noop_without_enemies(self):
        b = _barb(pos=(0, 0))
        st = _state([b])
        self.assertFalse(WT.execute_travel_teleport(b, st))

    def test_logs_event(self):
        b = _barb(pos=(0, 0))
        foe = _enemy(pos=(10, 0))
        st = _state([b, foe])
        WT.execute_travel_teleport(b, st)
        self.assertIn("travel_along_the_tree",
                      [e.get("event") for e in st.event_log])


class CandidateGateTest(unittest.TestCase):

    def test_on_template(self):
        b = _barb()
        self.assertTrue(any(a.get("id") == "a_travel_along_the_tree"
                            for a in b.template["actions"]))

    def _teleport_candidates(self, b, st):
        return [c for c in generate_candidates(b, st, "bonus_action")
                if c["action"].get("id") == "a_travel_along_the_tree"]

    def test_not_candidate_before_rage(self):
        b = _barb(pos=(0, 0))
        st = _state([b, _enemy(pos=(10, 0))])
        self.assertEqual(len(self._teleport_candidates(b, st)), 0)

    def test_candidate_while_raging(self):
        b = _barb(pos=(0, 0))
        st = _state([b, _enemy(pos=(10, 0))])
        R.enter_rage(b, st)
        self.assertEqual(len(self._teleport_candidates(b, st)), 1)


class ScoringTest(unittest.TestCase):

    def test_high_when_beyond_walk_within_teleport(self):
        from engine.ai.defensive_ehp import _score_travel_teleport
        b = _barb(pos=(0, 0), walk=40)
        st = _state([b, _enemy(pos=(10, 0))])   # 50 ft > walk+5, < 65
        self.assertEqual(_score_travel_teleport(b, st), 5.0)

    def test_low_when_walkable(self):
        from engine.ai.defensive_ehp import _score_travel_teleport
        b = _barb(pos=(0, 0), walk=40)
        st = _state([b, _enemy(pos=(2, 0))])   # 10 ft — walkable
        self.assertEqual(_score_travel_teleport(b, st), 1.0)

    def test_zero_when_adjacent(self):
        from engine.ai.defensive_ehp import _score_travel_teleport
        b = _barb(pos=(0, 0))
        st = _state([b, _enemy(pos=(1, 0))])
        self.assertEqual(_score_travel_teleport(b, st), 0.0)


if __name__ == "__main__":
    unittest.main()
