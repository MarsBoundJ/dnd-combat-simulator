"""Wall of Force — SPHERE form (microwave arc, Stage A).

A closed Sphere barrier (center + radius) lives in the same `state.walls` list
as flat Walls; `segment_blocked` dispatches on type. It traps a creature inside
(can't move or attack across the surface — effective speed 0), is total cover
both ways, yet leaves a wholly-inside segment clear — so a damaging zone sharing
the center hits the trapped creature it can't escape ("the microwave"). Built
on a point-in-circle transition, so it's leak-proof (no diagonal corner-cuts).

Run via:
    python -m unittest tests.test_wall_of_force_sphere
"""
from __future__ import annotations

import unittest

from engine.core.geometry import (
    Sphere, segment_blocked, line_of_effect_blocked, move_toward,
    WALL_BLOCK_NORMAL,
)
from engine.core.foundry_export import walls_to_documents
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import PrimitiveRegistry


def _mk(pos, actor_id="x", side="pc"):
    return Actor(id=actor_id, name=actor_id, template={}, side=side,
                 hp_current=10, hp_max=10, ac=10, position=pos)


def _sphere(center=(10.0, 10.0), radius=2.0, gap=False):
    return Sphere(center=center, radius=radius, move=WALL_BLOCK_NORMAL,
                  gap=gap, flags={"caster_id": "w", "action_id": "a_wof"})


class ContainmentTest(unittest.TestCase):
    def setUp(self):
        self.walls = [_sphere()]

    def test_inside_to_outside_move_blocked(self):
        self.assertTrue(segment_blocked((10, 10), (14, 10), self.walls, "move"))

    def test_inside_to_inside_move_clear(self):
        self.assertFalse(segment_blocked((10, 10), (11, 10), self.walls, "move"))

    def test_external_segment_through_sphere_blocked(self):
        # An outside→outside line that passes through the disk is blocked.
        self.assertTrue(segment_blocked((4, 10), (16, 10), self.walls, "move"))

    def test_external_segment_clear_of_sphere(self):
        self.assertFalse(segment_blocked((20, 20), (25, 25), self.walls, "move"))

    def test_trapped_creature_cannot_flee(self):
        trapped = _mk((10, 10))
        move_toward(trapped, (25, 10), 120, stop_at_ft=5, blockers=self.walls)
        # never escapes the radius-2 boundary
        self.assertTrue(_sphere().contains(
            (float(trapped.position[0]), float(trapped.position[1]))))


class LineOfEffectTest(unittest.TestCase):
    def setUp(self):
        self.walls = [_sphere()]

    def test_trapped_cannot_be_targeted_from_outside(self):
        self.assertTrue(line_of_effect_blocked((10, 10), (20, 10), self.walls))

    def test_zone_inside_still_reaches_trapped(self):
        # zone origin at the center, trapped creature one square over → both
        # inside → clear LoE → the microwave damages the trapped creature.
        self.assertFalse(line_of_effect_blocked((10, 10), (11, 11), self.walls))


class PlaceBarrierSphereTest(unittest.TestCase):
    def _cast_sphere(self, caster, target, radius_ft=10):
        st = CombatState(encounter=Encounter(id="t", actors=[caster, target]))
        st.current_attack = {"actor": caster, "target": target,
                             "action": {"id": "a_wall_of_force"}}
        PrimitiveRegistry.with_defaults().invoke(
            "place_barrier",
            {"shape": "sphere", "radius_ft": radius_ft, "move": True},
            st, None)
        return st

    def test_places_sphere_centered_on_target(self):
        caster = _mk((0, 0), "wiz")
        target = _mk((8, 3), "dragon", side="enemy")
        st = self._cast_sphere(caster, target)
        spheres = [w for w in st.walls if isinstance(w, Sphere)]
        self.assertEqual(len(spheres), 1)
        self.assertEqual(spheres[0].center, (8.0, 3.0))     # on the target
        self.assertEqual(spheres[0].radius, 2.0)            # 10 ft / 5
        self.assertEqual(spheres[0].flags["caster_id"], "wiz")

    def test_concentration_scrub_removes_sphere(self):
        from engine.core.concentration import apply_concentration, end_concentration
        caster = _mk((0, 0), "wiz")
        target = _mk((8, 3), "dragon", side="enemy")
        st = self._cast_sphere(caster, target)
        apply_concentration(caster, {"id": "a_wall_of_force",
                                     "concentration": True}, st)
        # stamp the sphere's action_id to match the concentration
        st.walls[0].flags["action_id"] = "a_wall_of_force"
        end_concentration(caster, st, reason="test")
        self.assertEqual([w for w in st.walls if isinstance(w, Sphere)], [])


class FloatingDomeTest(unittest.TestCase):
    """gap=True: blocks MOVEMENT (trapped) but is line-of-effect TRANSPARENT —
    the floor gap lets a zone seep in / attacks pass, so the microwave can be
    cast in either order (trap first, drop the zone in after)."""

    def setUp(self):
        self.dome = [_sphere(gap=True)]
        self.sealed = [_sphere(gap=False)]

    def test_dome_blocks_movement_like_sealed(self):
        # Movement is still trapped — gap is too small for a creature.
        self.assertTrue(segment_blocked((10, 10), (14, 10), self.dome, "move"))

    def test_dome_is_loe_transparent(self):
        # Sealed sphere = total cover; floating dome = LoE passes (the gap).
        self.assertTrue(line_of_effect_blocked((10, 10), (20, 10), self.sealed))
        self.assertFalse(line_of_effect_blocked((10, 10), (20, 10), self.dome))

    def test_trapped_can_be_targeted_and_zoned_from_outside(self):
        # An outside caster's line to the trapped creature is clear → it can be
        # shot, AND a damaging zone can be placed inside it afterward.
        self.assertFalse(line_of_effect_blocked((20, 10), (10, 10), self.dome))

    def test_place_barrier_gap_flag(self):
        caster = _mk((0, 0), "wiz")
        target = _mk((8, 3), "dragon", side="enemy")
        st = CombatState(encounter=Encounter(id="t", actors=[caster, target]))
        st.current_attack = {"actor": caster, "target": target,
                             "action": {"id": "a_wall_of_force"}}
        PrimitiveRegistry.with_defaults().invoke(
            "place_barrier",
            {"shape": "sphere", "radius_ft": 10, "gap": True}, st, None)
        dome = next(w for w in st.walls if isinstance(w, Sphere))
        self.assertTrue(dome.gap)
        self.assertFalse(dome.blocks_loe())     # transparent
        self.assertTrue(dome.blocks("move"))    # but traps movement


class FoundryExportTest(unittest.TestCase):
    def test_sphere_exports_as_segment_ring(self):
        docs = walls_to_documents([_sphere(center=(10.0, 10.0), radius=2.0)])
        self.assertEqual(len(docs), 16)                     # default ring
        self.assertTrue(all(d["move"] == WALL_BLOCK_NORMAL for d in docs))
        self.assertTrue(all(len(d["c"]) == 4 for d in docs))


if __name__ == "__main__":
    unittest.main()
