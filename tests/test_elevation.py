"""Altitude model — Stage 1: the elevation foundation (pure plumbing).

`Actor.elevation` (feet, Foundry-aligned) feeds a Chebyshev-3D `distance_ft`,
so melee reach + ranged range become altitude-aware: a flier 30 ft up and one
square over is out of a 5-ft greatsword but inside a 120-ft Fire Bolt. At
elevation 0 (the default for everyone) distance is byte-identical to the old
2-D metric, so no current behavior changes — this stage only lays the rails.

Run via:
    python -m unittest tests.test_elevation
"""
from __future__ import annotations

import unittest

from engine.core.geometry import distance_ft, is_within_ft, _as_elevation
from engine.core.foundry_export import token_to_document
from engine.core.state import Actor


def _mk(pos=(0, 0), elev=0, actor_id="a"):
    a = Actor(id=actor_id, name=actor_id, template={}, side="pc",
              hp_current=1, hp_max=1, ac=10, position=pos)
    a.elevation = elev
    return a


class ElevationFieldTest(unittest.TestCase):
    def test_actor_defaults_to_grounded(self):
        self.assertEqual(_mk().elevation, 0)
        # a freshly-built Actor is grounded by default
        self.assertEqual(Actor(id="z", name="z", template={}, side="pc").elevation, 0)

    def test_as_elevation_helper(self):
        self.assertEqual(_as_elevation(_mk(elev=30)), 30)
        self.assertEqual(_as_elevation((4, 7)), 0)        # bare tuple → ground


class Chebyshev3DDistanceTest(unittest.TestCase):
    def test_grounded_distance_unchanged(self):
        # Equal elevation → identical to the old 2-D Chebyshev metric.
        self.assertEqual(distance_ft(_mk((0, 0)), _mk((3, 4))), 20)
        self.assertEqual(distance_ft((0, 0), (3, 4)), 20)   # tuples stay 2-D

    def test_pure_vertical(self):
        self.assertEqual(distance_ft(_mk((0, 0), 0), _mk((0, 0), 30)), 30)

    def test_vertical_dominates_when_taller(self):
        # 1 square over (5 ft) + 30 ft up → max(1, 0, 6) squares = 30 ft.
        self.assertEqual(distance_ft(_mk((0, 0), 0), _mk((1, 0), 30)), 30)

    def test_horizontal_dominates_when_wider(self):
        # 10 squares over (50 ft) + 10 ft up → max(10, 0, 2) = 50 ft.
        self.assertEqual(distance_ft(_mk((0, 0), 0), _mk((10, 0), 10)), 50)

    def test_symmetric(self):
        a, b = _mk((2, 1), 0), _mk((2, 1), 25)
        self.assertEqual(distance_ft(a, b), distance_ft(b, a))


class ReachGatingTest(unittest.TestCase):
    def test_melee_cannot_reach_airborne(self):
        ground = _mk((0, 0), 0)
        aloft = _mk((1, 0), 30)            # adjacent on the ground, 30 ft up
        self.assertFalse(is_within_ft(ground, aloft, 5))   # 5-ft greatsword
        self.assertFalse(is_within_ft(ground, aloft, 10))  # even 10-ft reach

    def test_ranged_still_reaches_airborne(self):
        ground = _mk((0, 0), 0)
        aloft = _mk((1, 0), 30)
        self.assertTrue(is_within_ft(ground, aloft, 120))  # Fire Bolt
        self.assertTrue(is_within_ft(ground, aloft, 60))

    def test_grounded_melee_unaffected(self):
        a, b = _mk((0, 0), 0), _mk((1, 0), 0)
        self.assertTrue(is_within_ft(a, b, 5))             # both grounded


class FoundryTokenExportTest(unittest.TestCase):
    def test_token_doc_carries_elevation_in_feet(self):
        doc = token_to_document(_mk((2, 3), 30, actor_id="dragon"))
        self.assertEqual(doc["elevation"], 30)             # feet, Foundry-native
        self.assertEqual(doc["x"], 2 * 100)                # grid → pixels
        self.assertEqual(doc["y"], 3 * 100)
        self.assertEqual(doc["flags"]["trusight"]["actor_id"], "dragon")

    def test_grounded_token_elevation_zero(self):
        self.assertEqual(token_to_document(_mk((0, 0), 0))["elevation"], 0)


if __name__ == "__main__":
    unittest.main()
