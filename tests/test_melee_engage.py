"""Regression — a melee PC out of reach must CLOSE, not freeze on a Ready.

Bug (run-3 trace): _run_slot only called _move_to_engage when the candidate
set was EMPTY. A far-from-melee Fighter still had one self-targeted Ready
candidate (Ready-when-enemy-enters-reach), so the set wasn't empty → it
Readied in place forever instead of advancing. Fix: move-to-engage fires
when no candidate TARGETS AN ENEMY, not merely when the set is empty.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.cli import _build_actor
from engine.core.geometry import distance_ft, best_move_speed_ft
from engine.core.runner import EncounterRunner
from engine.core.state import Actor, Encounter, CombatState
from engine.loader import load_content
from sims.run_boss_sim import _spread_specs, _dragon_spec

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _setup():
    actors = [_build_actor(s, _registry())
              for s in (_spread_specs() + [_dragon_spec()])]
    enc = Encounter(id="t", actors=actors)
    runner = EncounterRunner.new(enc, seed=1, content_registry=_registry())
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return runner, st, actors


class MeleeEngageTest(unittest.TestCase):
    def test_far_melee_fighter_closes_instead_of_readying(self):
        runner, st, actors = _setup()
        fighter = next(a for a in actors if a.id == "Fighter_Champion")
        dragon = next(a for a in actors if a.side == "enemy")
        # Spread-start Fighter at (10,0); dragon at (0,0) = 50 ft, well beyond
        # its greatsword reach (5) — only a Ready candidate exists.
        before = distance_ft(fighter, dragon)
        self.assertGreater(before, 5)
        runner._run_slot(fighter, st, slot="action")
        # It must have advanced toward the dragon (not frozen Readying).
        self.assertLess(distance_ft(fighter, dragon), before,
                        "melee Fighter froze on a Ready instead of closing")
        self.assertTrue(fighter.moved_this_turn)


class FlyAwareEngageTest(unittest.TestCase):
    """A flier CLOSES at its fly speed, not its (often token) walk speed."""

    @staticmethod
    def _ab():
        return {k: {"score": 12, "save": 1}
                for k in ("str", "dex", "con", "int", "wis", "cha")}

    def _mk(self, actor_id, side, pos, speed, actions=None):
        return Actor(id=actor_id, name=actor_id,
                     template={"id": f"t_{actor_id}", "abilities": self._ab(),
                               "actions": actions or [],
                               "cr": {"proficiency_bonus": 3}},
                     side=side, hp_current=60, hp_max=60, ac=14,
                     speed=speed, position=pos, abilities=self._ab())

    def test_best_move_speed_prefers_fly(self):
        flier = self._mk("f", "enemy", (0, 0), {"walk": 5, "fly": 60})
        walker = self._mk("w", "enemy", (0, 0), {"walk": 30})
        self.assertEqual(best_move_speed_ft(flier), 60)   # fly beats walk
        self.assertEqual(best_move_speed_ft(walker), 30)  # walk-only unchanged
        # swim/climb don't count toward the open-field budget
        swimmer = self._mk("s", "enemy", (0, 0), {"walk": 20, "swim": 80})
        self.assertEqual(best_move_speed_ft(swimmer), 20)

    def test_flier_closes_at_fly_speed(self):
        # Hover-primary mover (walk 5, fly 60) 100 ft from a target should
        # advance ~60 ft in one move — not the 5 ft its walk would allow.
        mover = self._mk("wraith", "enemy", (0, 0), {"walk": 5, "fly": 60},
                         actions=[{"id": "a_claw", "type": "weapon_attack",
                                   "reach_ft": 5}])
        target = self._mk("pc", "pc", (20, 0), {"walk": 30},
                          actions=[{"id": "a_bolt", "type": "weapon_attack",
                                    "range_ft": 120}])
        enc = Encounter(id="t", actors=[mover, target])
        runner = EncounterRunner.new(enc, seed=1, content_registry=_registry())
        st = CombatState(encounter=enc)
        st.turn_order = [a.id for a in (mover, target)]
        st.content_registry = _registry()
        before = mover.position
        runner._move_to_engage(mover, st)
        self.assertEqual(distance_ft(before, mover.position), 60)
        self.assertTrue(mover.moved_this_turn)


class ThreeDEngageTest(unittest.TestCase):
    """A flier closes the VERTICAL gap to engage an airborne target (the
    Fly-buffed Fighter rising to a hovering dragon). Grounded movers can't."""

    @staticmethod
    def _ab():
        return {k: {"score": 12, "save": 1}
                for k in ("str", "dex", "con", "int", "wis", "cha")}

    def _mk(self, actor_id, side, pos, speed, elev=0):
        gs = {"id": "a_gs", "type": "weapon_attack",
              "pipeline": [{"primitive": "attack_roll",
                            "params": {"kind": "melee", "reach_ft": 5}}]}
        a = Actor(id=actor_id, name=actor_id,
                  template={"id": f"t_{actor_id}", "abilities": self._ab(),
                            "actions": [gs], "cr": {"proficiency_bonus": 4}},
                  side=side, hp_current=80, hp_max=80, ac=15,
                  speed=speed, position=pos, abilities=self._ab())
        a.elevation = elev
        return a

    def _runner(self, actors):
        enc = Encounter(id="t", actors=actors)
        runner = EncounterRunner.new(enc, seed=1, content_registry=_registry())
        st = CombatState(encounter=enc)
        st.turn_order = [a.id for a in actors]
        st.content_registry = _registry()
        return runner, st

    def test_flier_ascends_to_reach_airborne_target(self):
        fighter = self._mk("F", "pc", (0, 0), {"walk": 30, "fly": 60}, elev=0)
        dragon = self._mk("D", "enemy", (2, 0), {"walk": 40, "fly": 80}, elev=10)
        runner, st = self._runner([fighter, dragon])
        self.assertGreater(distance_ft(fighter, dragon), 5)   # can't reach yet
        runner._move_to_engage(fighter, st)
        self.assertEqual(fighter.elevation, 10)               # matched altitude
        self.assertLessEqual(distance_ft(fighter, dragon), 5)  # now in reach

    def test_grounded_mover_cannot_reach_airborne(self):
        fighter = self._mk("F", "pc", (0, 0), {"walk": 30}, elev=0)  # no fly
        dragon = self._mk("D", "enemy", (1, 0), {"walk": 40, "fly": 80}, elev=10)
        runner, st = self._runner([fighter, dragon])
        runner._move_to_engage(fighter, st)
        self.assertEqual(fighter.elevation, 0)                # stays grounded
        self.assertGreater(distance_ft(fighter, dragon), 5)   # still can't reach


if __name__ == "__main__":
    unittest.main()
