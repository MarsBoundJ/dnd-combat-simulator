"""Darkness spell as persistent_aura tests (PR #60).

Layers:
  1. Sphere zone detection in vision.py:
     - Sphere shape recognized alongside legacy rect
     - Chebyshev distance vs radius_squares
     - Backward compat: rect zones still work
  2. _persistent_aura creates_zone param:
     - creates_zone='magical_dark' + anchor='point' + origin:
       appends sphere entry to environment.magical_dark_zones
     - Zone carries caster_id + action_id for cleanup matching
     - creates_zone with anchor!='point' raises
     - creates_zone='magical_dark' with no origin raises
     - Unknown creates_zone value raises
     - No creates_zone (default): no zone created
  3. end_concentration cleanup:
     - Darkness zone matching dropped aura is removed
     - Statically-declared zones (no caster_id stamp) preserved
     - Multiple Darkness from different casters coexist; ending
       one only removes its zone
  4. End-to-end vision:
     - can_actor_see returns False for actor in Darkness zone (no
       darkvision)
     - Truesight pierces the Darkness zone
     - Ordinary darkvision does NOT pierce
"""
from __future__ import annotations

import unittest

from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.core.vision import (
    can_actor_see, is_in_magical_dark_zone, _position_in_any_zone,
)


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id="a", *, side="pc", position=(0, 0),
                  darkvision_range_ft=0, truesight_range_ft=0,
                  blindsight_range_ft=0) -> Actor:
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                 "abilities": abilities,
                 "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                 "actions": []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=20, hp_max=20, ac=14,
                  speed={"walk": 30}, position=position,
                  abilities=abilities,
                  darkvision_range_ft=darkvision_range_ft,
                  truesight_range_ft=truesight_range_ft,
                  blindsight_range_ft=blindsight_range_ft)


def _state_with(actors, environment=None):
    enc = Encounter(id="t", actors=actors, environment=environment or {})
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    state.persistent_auras = []
    return state


def _darkness_action():
    return {
        "id": "a_darkness", "name": "Darkness",
        "type": "persistent_aura",
        "spell_slot_level": 2,
        "concentration": True,
        "named_effect": "darkness",
        "pipeline": [
            {"primitive": "persistent_aura",
              "params": {
                  "shape": "sphere",
                  "radius_ft": 15,
                  "anchor": "point",
                  "trigger_event": "target_turn_start_in_area",
                  "affected": "all_creatures",
                  "ability": "none",
                  "on_fail": [],
                  "on_success": [],
                  "creates_zone": "magical_dark",
              }},
        ],
    }


# ============================================================================
# Layer 1: sphere zone detection
# ============================================================================

class SphereZoneDetectionTest(unittest.TestCase):

    def test_sphere_zone_center(self) -> None:
        zones = [{"shape": "sphere", "center": [5, 5], "radius_ft": 15}]
        self.assertTrue(_position_in_any_zone((5, 5), zones))

    def test_sphere_zone_within_radius(self) -> None:
        # 15 ft = 3 squares. Chebyshev distance ≤ 3 → inside.
        zones = [{"shape": "sphere", "center": [5, 5], "radius_ft": 15}]
        self.assertTrue(_position_in_any_zone((8, 5), zones))    # 3 east
        self.assertTrue(_position_in_any_zone((8, 8), zones))    # diagonal 3
        self.assertTrue(_position_in_any_zone((2, 2), zones))    # 3 NW

    def test_sphere_zone_just_outside(self) -> None:
        zones = [{"shape": "sphere", "center": [5, 5], "radius_ft": 15}]
        self.assertFalse(_position_in_any_zone((9, 5), zones))   # 4 east

    def test_rect_zone_backward_compat(self) -> None:
        zones = [{"x_min": 0, "x_max": 5, "y_min": 0, "y_max": 5}]
        self.assertTrue(_position_in_any_zone((3, 3), zones))
        self.assertFalse(_position_in_any_zone((6, 3), zones))

    def test_mixed_rect_and_sphere(self) -> None:
        zones = [
            {"x_min": 0, "x_max": 2, "y_min": 0, "y_max": 2},
            {"shape": "sphere", "center": [10, 10], "radius_ft": 10},
        ]
        self.assertTrue(_position_in_any_zone((1, 1), zones))   # in rect
        self.assertTrue(_position_in_any_zone((11, 10), zones))  # in sphere
        self.assertFalse(_position_in_any_zone((5, 5), zones))   # neither

    def test_is_in_magical_dark_zone_with_sphere(self) -> None:
        env = {"magical_dark_zones": [
            {"shape": "sphere", "center": [0, 0], "radius_ft": 15},
        ]}
        state = _state_with([_make_actor("a")], environment=env)
        self.assertTrue(is_in_magical_dark_zone((2, 2), state))
        self.assertFalse(is_in_magical_dark_zone((10, 10), state))


# ============================================================================
# Layer 2: _persistent_aura creates_zone
# ============================================================================

class PersistentAuraCreatesZoneTest(unittest.TestCase):

    def _run_primitive(self, state, actor, action, params):
        """Set state.current_attack as the runner would and invoke."""
        from engine.primitives import _persistent_aura
        state.current_attack = {
            "actor": actor, "target": actor, "action": action,
            "area_origin": (5, 5),
        }
        _persistent_aura(params, state, EventBus())

    def test_creates_magical_dark_zone(self) -> None:
        actor = _make_actor("wiz")
        state = _state_with([actor])
        self._run_primitive(state, actor, _darkness_action(), {
            "shape": "sphere",
            "radius_ft": 15,
            "anchor": "point",
            "ability": "none",
            "creates_zone": "magical_dark",
        })
        env = state.encounter.environment or {}
        zones = env.get("magical_dark_zones") or []
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]["shape"], "sphere")
        self.assertEqual(zones[0]["center"], [5, 5])
        self.assertEqual(zones[0]["radius_ft"], 15)
        self.assertEqual(zones[0]["caster_id"], "wiz")
        self.assertEqual(zones[0]["action_id"], "a_darkness")

    def test_caster_anchor_raises(self) -> None:
        actor = _make_actor("wiz")
        state = _state_with([actor])
        # Caster-anchored Darkness not supported in v1
        state.current_attack = {
            "actor": actor, "target": actor,
            "action": _darkness_action(),
            "area_origin": (5, 5),
        }
        from engine.primitives import _persistent_aura
        with self.assertRaises(ValueError) as ctx:
            _persistent_aura({
                "shape": "sphere",
                "radius_ft": 15,
                "anchor": "caster",
                "ability": "none",
                "creates_zone": "magical_dark",
            }, state, EventBus())
        self.assertIn("anchor=point", str(ctx.exception))

    def test_unknown_creates_zone_raises(self) -> None:
        actor = _make_actor("wiz")
        state = _state_with([actor])
        state.current_attack = {
            "actor": actor, "target": actor,
            "action": _darkness_action(),
            "area_origin": (5, 5),
        }
        from engine.primitives import _persistent_aura
        with self.assertRaises(ValueError):
            _persistent_aura({
                "shape": "sphere",
                "radius_ft": 15,
                "anchor": "point",
                "ability": "none",
                "creates_zone": "not_a_zone_type",
            }, state, EventBus())

    def test_no_creates_zone_no_environment_change(self) -> None:
        actor = _make_actor("wiz")
        state = _state_with([actor])
        # Standard Spirit-Guardians-shape aura, no zone declared
        state.current_attack = {
            "actor": actor, "target": actor, "action": _darkness_action(),
        }
        from engine.primitives import _persistent_aura
        _persistent_aura({
            "shape": "sphere",
            "radius_ft": 15,
            "anchor": "caster",
            "ability": "none",
        }, state, EventBus())
        env = state.encounter.environment or {}
        self.assertNotIn("magical_dark_zones", env)


# ============================================================================
# Layer 3: end_concentration cleanup
# ============================================================================

class EndConcentrationDarknessTest(unittest.TestCase):

    def test_dropping_darkness_removes_its_zone(self) -> None:
        from engine.core.concentration import end_concentration
        from engine.primitives import _persistent_aura
        wiz = _make_actor("wiz")
        state = _state_with([wiz])
        # Cast Darkness
        wiz.concentration_on = {"action_id": "a_darkness",
                                  "caster_id": wiz.id,
                                  "applied_at_round": 1}
        state.current_attack = {
            "actor": wiz, "target": wiz,
            "action": _darkness_action(),
            "area_origin": (5, 5),
        }
        _persistent_aura({
            "shape": "sphere",
            "radius_ft": 15,
            "anchor": "point",
            "ability": "none",
            "creates_zone": "magical_dark",
        }, state, EventBus())
        # Zone exists
        self.assertEqual(
            len(state.encounter.environment.get("magical_dark_zones")), 1)
        # End concentration
        end_concentration(wiz, state, reason="dropped")
        # Zone gone
        zones = state.encounter.environment.get("magical_dark_zones") or []
        self.assertEqual(len(zones), 0)

    def test_static_zone_preserved_on_concentration_end(self) -> None:
        """A magical_dark_zone declared statically by a fixture (no
        caster_id stamp) survives unrelated concentration drops."""
        from engine.core.concentration import end_concentration
        wiz = _make_actor("wiz")
        state = _state_with([wiz], environment={
            "magical_dark_zones": [
                {"x_min": 0, "x_max": 3, "y_min": 0, "y_max": 3},
            ],
        })
        wiz.concentration_on = {"action_id": "a_some_other_spell",
                                  "caster_id": wiz.id,
                                  "applied_at_round": 1}
        end_concentration(wiz, state, reason="dropped")
        zones = state.encounter.environment.get("magical_dark_zones") or []
        self.assertEqual(len(zones), 1)
        # Still the static rect, not a sphere
        self.assertNotIn("shape", zones[0])

    def test_two_casters_independent_zones(self) -> None:
        from engine.core.concentration import end_concentration
        from engine.primitives import _persistent_aura
        wiz1 = _make_actor("wiz1", position=(0, 0))
        wiz2 = _make_actor("wiz2", position=(20, 20))
        state = _state_with([wiz1, wiz2])
        # Both cast Darkness at their own coordinates
        for caster, origin in [(wiz1, (0, 0)), (wiz2, (20, 20))]:
            caster.concentration_on = {"action_id": "a_darkness",
                                          "caster_id": caster.id,
                                          "applied_at_round": 1}
            state.current_attack = {
                "actor": caster, "target": caster,
                "action": _darkness_action(),
                "area_origin": origin,
            }
            _persistent_aura({
                "shape": "sphere",
                "radius_ft": 15,
                "anchor": "point",
                "ability": "none",
                "creates_zone": "magical_dark",
            }, state, EventBus())
        # Both zones exist
        zones = state.encounter.environment.get("magical_dark_zones") or []
        self.assertEqual(len(zones), 2)
        # Drop wiz1's concentration → only its zone removed
        end_concentration(wiz1, state, reason="dropped")
        zones = state.encounter.environment.get("magical_dark_zones") or []
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]["caster_id"], "wiz2")


# ============================================================================
# Layer 4: end-to-end vision
# ============================================================================

class DarknessVisionEndToEndTest(unittest.TestCase):

    def _setup_darkness(self, observer, target):
        from engine.primitives import _persistent_aura
        caster = _make_actor("wiz", position=(5, 5))
        state = _state_with([observer, target, caster])
        state.current_attack = {
            "actor": caster, "target": caster,
            "action": _darkness_action(),
            "area_origin": (5, 5),
        }
        _persistent_aura({
            "shape": "sphere",
            "radius_ft": 15,
            "anchor": "point",
            "ability": "none",
            "creates_zone": "magical_dark",
        }, state, EventBus())
        return state

    def test_no_darkvision_blocked(self) -> None:
        observer = _make_actor("guard", position=(20, 20))
        target = _make_actor("rogue", side="enemy", position=(5, 5))
        state = self._setup_darkness(observer, target)
        self.assertFalse(can_actor_see(observer, target, state))

    def test_ordinary_darkvision_blocked(self) -> None:
        observer = _make_actor("dwarf", position=(20, 20),
                                  darkvision_range_ft=120)
        target = _make_actor("rogue", side="enemy", position=(5, 5))
        state = self._setup_darkness(observer, target)
        # RAW: ordinary DV doesn't pierce magical darkness
        self.assertFalse(can_actor_see(observer, target, state))

    def test_truesight_pierces(self) -> None:
        observer = _make_actor("paladin", position=(20, 20),
                                  truesight_range_ft=60)
        target = _make_actor("rogue", side="enemy", position=(5, 5))
        state = self._setup_darkness(observer, target)
        # Within 60 ft truesight range? Distance = max(15, 15) = 15
        # squares = 75 ft. Out of range — should NOT see.
        self.assertFalse(can_actor_see(observer, target, state))

    def test_truesight_in_range_pierces(self) -> None:
        observer = _make_actor("paladin", position=(8, 5),
                                  truesight_range_ft=60)
        target = _make_actor("rogue", side="enemy", position=(5, 5))
        state = self._setup_darkness(observer, target)
        # Distance = max(3, 0) = 3 squares = 15 ft. Within truesight.
        self.assertTrue(can_actor_see(observer, target, state))

    def test_blindsight_pierces(self) -> None:
        observer = _make_actor("bat", position=(8, 5),
                                  blindsight_range_ft=30)
        target = _make_actor("rogue", side="enemy", position=(5, 5))
        state = self._setup_darkness(observer, target)
        # Distance = 15 ft, within blindsight 30 ft
        self.assertTrue(can_actor_see(observer, target, state))


if __name__ == "__main__":
    unittest.main()
