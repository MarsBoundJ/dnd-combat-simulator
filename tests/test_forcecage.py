"""Forcecage — 7th-level Evocation, Concentration (2024 PHB).

Two forms:
  - BOX (10 ft on a side, sealed): blocks movement AND line-of-effect. Total
    isolation — nothing in, nothing out. Pure denial.
  - CAGE (20 ft on a side, bars): blocks movement but is LoE-transparent. The
    microwave container: trap + zone damage. Functionally identical to Wall of
    Force dome but with no dispel vulnerability and a higher slot cost.

Both forms are concentration, so they compete with the caster's other conc.
effects. The microwave combo (Forcecage + zone) requires two concentration
slots (Simulacrum).

Run via:
    python -m unittest tests.test_forcecage
"""
from __future__ import annotations

import unittest

from engine.core.geometry import (
    Sphere, segment_blocked, line_of_effect_blocked, move_toward,
    WALL_BLOCK_NORMAL, WALL_BLOCK_NONE,
)
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import PrimitiveRegistry


def _mk(pos, actor_id="x", side="pc"):
    abilities = {k: {"score": 10, "save": 0} for k in
                 ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                 template={"id": f"tpl_{actor_id}", "abilities": abilities,
                           "cr": {"proficiency_bonus": 2}, "actions": []},
                 side=side, hp_current=200, hp_max=200, ac=18,
                 position=pos, abilities=abilities)


def _cast_forcecage(caster, target, form="cage"):
    """Invoke the place_barrier primitive with Forcecage params."""
    st = CombatState(encounter=Encounter(id="t", actors=[caster, target]))
    action_id = f"a_forcecage_{form}"
    st.current_attack = {"actor": caster, "target": target,
                         "action": {"id": action_id}}
    if form == "box":
        PrimitiveRegistry.with_defaults().invoke(
            "place_barrier",
            {"shape": "sphere", "radius_ft": 5, "gap": False,
             "move": True, "sight": True, "effect": "forcecage_box"},
            st, None)
    else:
        PrimitiveRegistry.with_defaults().invoke(
            "place_barrier",
            {"shape": "sphere", "radius_ft": 10, "gap": True,
             "move": True, "sight": False, "effect": "forcecage_cage"},
            st, None)
    return st


class ForcecageBoxTest(unittest.TestCase):
    """BOX form: sealed, blocks movement AND line-of-effect."""

    def setUp(self):
        self.caster = _mk((0, 0), "wizard")
        self.target = _mk((10, 5), "dragon", side="enemy")
        self.st = _cast_forcecage(self.caster, self.target, form="box")
        self.spheres = [w for w in self.st.walls if isinstance(w, Sphere)]

    def test_sphere_placed_on_target(self):
        self.assertEqual(len(self.spheres), 1)
        self.assertEqual(self.spheres[0].center, (10.0, 5.0))

    def test_box_radius_is_1_square(self):
        # 5 ft / 5 ft per square = 1.0 radius
        self.assertEqual(self.spheres[0].radius, 1.0)

    def test_box_blocks_movement(self):
        self.assertTrue(
            segment_blocked((10, 5), (14, 5), self.st.walls, "move"))

    def test_box_blocks_line_of_effect(self):
        # Sealed box: LoE blocked across the boundary
        self.assertTrue(
            line_of_effect_blocked((10, 5), (20, 5), self.st.walls))

    def test_box_blocks_attacks_from_outside(self):
        self.assertTrue(
            line_of_effect_blocked((0, 0), (10, 5), self.st.walls))

    def test_trapped_creature_cannot_flee(self):
        trapped = _mk((10, 5), "trapped")
        move_toward(trapped, (25, 5), 120, stop_at_ft=5,
                    blockers=self.st.walls)
        s = self.spheres[0]
        self.assertTrue(
            s.contains((float(trapped.position[0]),
                        float(trapped.position[1]))))

    def test_event_logged(self):
        events = [e for e in self.st.event_log
                  if e.get("event") == "barrier_placed"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["effect"], "forcecage_box")
        self.assertEqual(events[0]["shape"], "sphere")
        self.assertEqual(events[0]["actor"], "wizard")


class ForcecageCageTest(unittest.TestCase):
    """CAGE form: bars — blocks movement but LoE-transparent (the microwave)."""

    def setUp(self):
        self.caster = _mk((0, 0), "wizard")
        self.target = _mk((10, 5), "dragon", side="enemy")
        self.st = _cast_forcecage(self.caster, self.target, form="cage")
        self.spheres = [w for w in self.st.walls if isinstance(w, Sphere)]

    def test_sphere_placed_on_target(self):
        self.assertEqual(len(self.spheres), 1)
        self.assertEqual(self.spheres[0].center, (10.0, 5.0))

    def test_cage_radius_is_2_squares(self):
        # 10 ft / 5 ft per square = 2.0 radius
        self.assertEqual(self.spheres[0].radius, 2.0)

    def test_cage_blocks_movement(self):
        self.assertTrue(
            segment_blocked((10, 5), (14, 5), self.st.walls, "move"))

    def test_cage_allows_line_of_effect(self):
        # gap=True → LoE-transparent (bars). Attacks/spells pass through.
        self.assertFalse(
            line_of_effect_blocked((10, 5), (20, 5), self.st.walls))

    def test_zone_inside_reaches_trapped(self):
        # Both points inside → clear LoE → the microwave damages the trapped
        self.assertFalse(
            line_of_effect_blocked((10, 5), (11, 5), self.st.walls))

    def test_outside_can_target_inside(self):
        # Cage bars don't block LoE from outside
        self.assertFalse(
            line_of_effect_blocked((0, 0), (10, 5), self.st.walls))


class ConcentrationTest(unittest.TestCase):
    """Forcecage IS concentration (2024 rules): dropping it ends the cage."""

    def test_concentration_scrub_removes_cage(self):
        from engine.core.concentration import (
            apply_concentration, end_concentration,
        )
        caster = _mk((0, 0), "wizard")
        target = _mk((10, 5), "dragon", side="enemy")
        st = _cast_forcecage(caster, target, form="cage")
        self.assertEqual(len([w for w in st.walls if isinstance(w, Sphere)]), 1)
        apply_concentration(caster, {"id": "a_forcecage_cage",
                                     "concentration": True}, st)
        end_concentration(caster, st, reason="cast_new_spell")
        self.assertEqual([w for w in st.walls if isinstance(w, Sphere)], [])

    def test_concentration_scrub_removes_box(self):
        from engine.core.concentration import (
            apply_concentration, end_concentration,
        )
        caster = _mk((0, 0), "wizard")
        target = _mk((10, 5), "dragon", side="enemy")
        st = _cast_forcecage(caster, target, form="box")
        self.assertEqual(len([w for w in st.walls if isinstance(w, Sphere)]), 1)
        apply_concentration(caster, {"id": "a_forcecage_box",
                                     "concentration": True}, st)
        end_concentration(caster, st, reason="damage")
        self.assertEqual([w for w in st.walls if isinstance(w, Sphere)], [])


class ContainmentScoringTest(unittest.TestCase):
    """AI containment scorer (is_trapped_in_dome) recognizes Forcecage spheres."""

    def test_is_trapped_in_dome_recognizes_forcecage(self):
        from engine.ai.defensive_ehp import is_trapped_in_dome
        caster = _mk((0, 0), "wizard")
        target = _mk((10, 5), "dragon", side="enemy")
        st = _cast_forcecage(caster, target, form="cage")
        self.assertTrue(is_trapped_in_dome(target, st))

    def test_not_trapped_before_cast(self):
        from engine.ai.defensive_ehp import is_trapped_in_dome
        target = _mk((10, 5), "dragon", side="enemy")
        st = CombatState(encounter=Encounter(id="t", actors=[target]))
        self.assertFalse(is_trapped_in_dome(target, st))

    def test_no_redundant_cage_on_already_trapped(self):
        from engine.ai.defensive_ehp import defensive_ehp_containment
        caster = _mk((0, 0), "wizard")
        target = _mk((10, 5), "dragon", side="enemy")
        st = _cast_forcecage(caster, target, form="cage")
        # Second cage attempt → 0 eHP (already trapped)
        action = {"id": "a_forcecage_cage", "pipeline": [
            {"primitive": "place_barrier",
             "params": {"shape": "sphere", "radius_ft": 10}}]}
        self.assertEqual(
            defensive_ehp_containment(caster, target, action, st), 0.0)


if __name__ == "__main__":
    unittest.main()
