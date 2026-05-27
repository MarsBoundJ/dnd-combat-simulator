"""Light levels + Darkvision tests (PR #50).

Layers:
  1. Zone detection helpers (is_in_dim_light_zone, is_in_dark_zone)
  2. can_actor_see extension:
     - Dim light alone does NOT block sight (RAW: lightly obscured)
     - Dark zone + no darkvision → blocked
     - Dark zone + darkvision within range → visible
     - Dark zone + darkvision beyond range → blocked
     - Both-in-dark same-zone resolves identically (one helper path)
     - Observer-in-dark, target-not-in-dark: also gated on darkvision
     - Precedence: blinded > invisible > heavy obscurement > dark zone
  3. cli._build_actor loads darkvision_range_ft:
     - From explicit actor_spec field (override)
     - From template senses.special.darkvision (monster default)
     - Defaults to 0 when neither present

Run via:
    python -m unittest tests.test_light_darkvision
"""
from __future__ import annotations

import unittest

from engine.core.state import Actor, CombatState, Encounter
from engine.core.vision import (
    can_actor_see, is_in_dim_light_zone, is_in_dark_zone,
    is_in_obscured_zone,
)


# ============================================================================
# Helpers (mirrors test_vision.py shape)
# ============================================================================

def _make_actor(actor_id, side="pc", position=(0, 0),
                  applied_conditions=None, darkvision_range_ft=0) -> Actor:
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                 "abilities": abilities,
                 "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                 "actions": []}
    actor = Actor(id=actor_id, name=actor_id, template=template, side=side,
                   hp_current=20, hp_max=20, ac=14,
                   speed={"walk": 30}, position=position,
                   abilities=abilities,
                   darkvision_range_ft=darkvision_range_ft)
    if applied_conditions:
        actor.applied_conditions = list(applied_conditions)
    return actor


def _state_with(actors, environment=None):
    enc = Encounter(id="t", actors=actors, environment=environment or {})
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Zone-detection helpers
# ============================================================================

class DimLightZoneDetectionTest(unittest.TestCase):

    def test_no_zones_returns_false(self) -> None:
        state = _state_with([_make_actor("a")])
        self.assertFalse(is_in_dim_light_zone((5, 5), state))

    def test_position_inside_zone(self) -> None:
        env = {"dim_light_zones": [{"x_min": 0, "x_max": 5,
                                       "y_min": 0, "y_max": 5}]}
        state = _state_with([_make_actor("a")], environment=env)
        self.assertTrue(is_in_dim_light_zone((3, 3), state))
        self.assertTrue(is_in_dim_light_zone((0, 0), state))
        self.assertTrue(is_in_dim_light_zone((5, 5), state))    # inclusive

    def test_position_outside_zone(self) -> None:
        env = {"dim_light_zones": [{"x_min": 0, "x_max": 5,
                                       "y_min": 0, "y_max": 5}]}
        state = _state_with([_make_actor("a")], environment=env)
        self.assertFalse(is_in_dim_light_zone((6, 3), state))
        self.assertFalse(is_in_dim_light_zone((3, 6), state))

    def test_none_position(self) -> None:
        env = {"dim_light_zones": [{"x_min": 0, "x_max": 5,
                                       "y_min": 0, "y_max": 5}]}
        state = _state_with([_make_actor("a")], environment=env)
        self.assertFalse(is_in_dim_light_zone(None, state))


class DarkZoneDetectionTest(unittest.TestCase):

    def test_no_zones_returns_false(self) -> None:
        state = _state_with([_make_actor("a")])
        self.assertFalse(is_in_dark_zone((5, 5), state))

    def test_position_inside_zone(self) -> None:
        env = {"dark_zones": [{"x_min": 10, "x_max": 15,
                                  "y_min": 10, "y_max": 15}]}
        state = _state_with([_make_actor("a")], environment=env)
        self.assertTrue(is_in_dark_zone((12, 12), state))

    def test_position_outside_zone(self) -> None:
        env = {"dark_zones": [{"x_min": 10, "x_max": 15,
                                  "y_min": 10, "y_max": 15}]}
        state = _state_with([_make_actor("a")], environment=env)
        self.assertFalse(is_in_dark_zone((5, 5), state))

    def test_multiple_zones(self) -> None:
        env = {"dark_zones": [
            {"x_min": 0, "x_max": 5, "y_min": 0, "y_max": 5},
            {"x_min": 20, "x_max": 25, "y_min": 20, "y_max": 25},
        ]}
        state = _state_with([_make_actor("a")], environment=env)
        self.assertTrue(is_in_dark_zone((3, 3), state))
        self.assertTrue(is_in_dark_zone((22, 22), state))
        self.assertFalse(is_in_dark_zone((10, 10), state))


# ============================================================================
# can_actor_see: dim light does NOT block (RAW lightly obscured)
# ============================================================================

class DimLightDoesNotBlockTest(unittest.TestCase):

    def test_target_in_dim_light_still_visible(self) -> None:
        env = {"dim_light_zones": [{"x_min": 0, "x_max": 10,
                                       "y_min": 0, "y_max": 10}]}
        obs = _make_actor("obs", position=(20, 0))
        tgt = _make_actor("tgt", position=(5, 5))     # in dim light
        state = _state_with([obs, tgt], environment=env)
        self.assertTrue(can_actor_see(obs, tgt, state))

    def test_observer_in_dim_light_still_sees(self) -> None:
        env = {"dim_light_zones": [{"x_min": 0, "x_max": 10,
                                       "y_min": 0, "y_max": 10}]}
        obs = _make_actor("obs", position=(5, 5))     # in dim light
        tgt = _make_actor("tgt", position=(20, 0))
        state = _state_with([obs, tgt], environment=env)
        self.assertTrue(can_actor_see(obs, tgt, state))


# ============================================================================
# can_actor_see: dark zone + darkvision
# ============================================================================

class DarkZoneNoDarkvisionTest(unittest.TestCase):

    def test_no_darkvision_cant_see_target_in_dark(self) -> None:
        env = {"dark_zones": [{"x_min": 0, "x_max": 5,
                                  "y_min": 0, "y_max": 5}]}
        obs = _make_actor("obs", position=(10, 0), darkvision_range_ft=0)
        tgt = _make_actor("tgt", position=(2, 2))     # in dark
        state = _state_with([obs, tgt], environment=env)
        self.assertFalse(can_actor_see(obs, tgt, state))

    def test_no_darkvision_cant_see_anything_when_self_in_dark(self) -> None:
        # Observer in dark zone, target outside it. RAW: the observer
        # is effectively blinded by their own dark surroundings.
        env = {"dark_zones": [{"x_min": 0, "x_max": 5,
                                  "y_min": 0, "y_max": 5}]}
        obs = _make_actor("obs", position=(2, 2), darkvision_range_ft=0)
        tgt = _make_actor("tgt", position=(10, 0))
        state = _state_with([obs, tgt], environment=env)
        self.assertFalse(can_actor_see(obs, tgt, state))


class DarkZoneWithDarkvisionTest(unittest.TestCase):

    def test_darkvision_within_range_sees_into_dark(self) -> None:
        env = {"dark_zones": [{"x_min": 0, "x_max": 5,
                                  "y_min": 0, "y_max": 5}]}
        # Elf observer with 60 ft darkvision at (10, 0); target in dark
        # at (2, 0). Distance = max(8, 0) = 8 squares = 40 ft ≤ 60 ft.
        obs = _make_actor("obs", position=(10, 0), darkvision_range_ft=60)
        tgt = _make_actor("tgt", position=(2, 0))
        state = _state_with([obs, tgt], environment=env)
        self.assertTrue(can_actor_see(obs, tgt, state))

    def test_darkvision_at_exact_range_boundary_sees(self) -> None:
        env = {"dark_zones": [{"x_min": 0, "x_max": 5,
                                  "y_min": 0, "y_max": 5}]}
        # Observer at (12, 0); target in dark at (0, 0).
        # Distance = max(12, 0) = 12 squares = 60 ft = exact darkvision range.
        obs = _make_actor("obs", position=(12, 0), darkvision_range_ft=60)
        tgt = _make_actor("tgt", position=(0, 0))
        state = _state_with([obs, tgt], environment=env)
        self.assertTrue(can_actor_see(obs, tgt, state))

    def test_darkvision_beyond_range_blocked(self) -> None:
        env = {"dark_zones": [{"x_min": 0, "x_max": 5,
                                  "y_min": 0, "y_max": 5}]}
        # Observer at (15, 0); target at (0, 0). Distance = 15 * 5 = 75 ft > 60.
        obs = _make_actor("obs", position=(15, 0), darkvision_range_ft=60)
        tgt = _make_actor("tgt", position=(0, 0))
        state = _state_with([obs, tgt], environment=env)
        self.assertFalse(can_actor_see(obs, tgt, state))

    def test_both_in_dark_within_darkvision_range_sees(self) -> None:
        # Observer + target both in the same dark zone, within darkvision.
        env = {"dark_zones": [{"x_min": 0, "x_max": 10,
                                  "y_min": 0, "y_max": 10}]}
        obs = _make_actor("obs", position=(0, 0), darkvision_range_ft=60)
        tgt = _make_actor("tgt", position=(5, 5))    # 25 ft away
        state = _state_with([obs, tgt], environment=env)
        self.assertTrue(can_actor_see(obs, tgt, state))

    def test_120_ft_darkvision_reaches_further(self) -> None:
        env = {"dark_zones": [{"x_min": 0, "x_max": 5,
                                  "y_min": 0, "y_max": 5}]}
        obs = _make_actor("obs", position=(20, 0), darkvision_range_ft=120)
        tgt = _make_actor("tgt", position=(0, 0))    # 100 ft away
        state = _state_with([obs, tgt], environment=env)
        self.assertTrue(can_actor_see(obs, tgt, state))


# ============================================================================
# Precedence: heavier conditions trump lighter ones
# ============================================================================

class VisionPrecedenceTest(unittest.TestCase):

    def test_blinded_trumps_darkvision(self) -> None:
        # Even with darkvision, a blinded observer can't see anything.
        env = {"dark_zones": [{"x_min": 0, "x_max": 5,
                                  "y_min": 0, "y_max": 5}]}
        obs = _make_actor("obs", position=(10, 0), darkvision_range_ft=60,
                            applied_conditions=[{"condition_id": "co_blinded"}])
        tgt = _make_actor("tgt", position=(2, 2))
        state = _state_with([obs, tgt], environment=env)
        self.assertFalse(can_actor_see(obs, tgt, state))

    def test_invisible_target_in_dark_zone_still_blocked(self) -> None:
        env = {"dark_zones": [{"x_min": 0, "x_max": 5,
                                  "y_min": 0, "y_max": 5}]}
        obs = _make_actor("obs", position=(10, 0), darkvision_range_ft=60)
        tgt = _make_actor("tgt", position=(2, 2),
                            applied_conditions=[{"condition_id": "co_invisible"}])
        state = _state_with([obs, tgt], environment=env)
        # Invisible check fires first; darkvision wouldn't have mattered
        # anyway (Invisible bypasses ordinary sight).
        self.assertFalse(can_actor_see(obs, tgt, state))

    def test_heavy_obscurement_trumps_darkvision(self) -> None:
        # A heavy-obscurement zone (fog) blocks sight even with darkvision.
        # Darkvision sees through DARK, not through FOG / leaves / etc.
        env = {
            "heavily_obscured_zones": [
                {"x_min": 0, "x_max": 5, "y_min": 0, "y_max": 5},
            ],
        }
        obs = _make_actor("obs", position=(10, 0), darkvision_range_ft=60)
        tgt = _make_actor("tgt", position=(2, 2))
        state = _state_with([obs, tgt], environment=env)
        self.assertFalse(can_actor_see(obs, tgt, state))

    def test_self_sees_self_even_in_dark_with_no_darkvision(self) -> None:
        # The self-vision short-circuit should still fire (modifier
        # when-clauses use this).
        env = {"dark_zones": [{"x_min": 0, "x_max": 10,
                                  "y_min": 0, "y_max": 10}]}
        obs = _make_actor("obs", position=(5, 5), darkvision_range_ft=0)
        state = _state_with([obs], environment=env)
        self.assertTrue(can_actor_see(obs, obs, state))


# ============================================================================
# cli._build_actor wiring
# ============================================================================

class BuildActorDarkvisionTest(unittest.TestCase):

    def test_template_darkvision_loaded(self) -> None:
        from engine.cli import _build_actor
        template = {
            "id": "m_test", "name": "Test",
            "combat": {"armor_class": 12, "speed": {"walk": 30},
                          "hit_points": {"average": 10}},
            "abilities": {k: {"score": 10, "save": 0}
                            for k in ("str", "dex", "con",
                                       "int", "wis", "cha")},
            "senses": {"passive_perception": 10,
                         "special": {"darkvision": 60}},
        }
        actor_spec = {
            "instance_id": "g1",
            "template": template,
        }
        actor = _build_actor(actor_spec, registry=None)
        self.assertEqual(actor.darkvision_range_ft, 60)

    def test_actor_spec_override_wins(self) -> None:
        # Race-granted darkvision specified directly on the actor (since
        # race isn't modeled at the PC level yet). Overrides any
        # template default.
        from engine.cli import _build_actor
        template = {
            "id": "m_test", "name": "Test",
            "combat": {"armor_class": 12, "speed": {"walk": 30},
                          "hit_points": {"average": 10}},
            "abilities": {k: {"score": 10, "save": 0}
                            for k in ("str", "dex", "con",
                                       "int", "wis", "cha")},
            "senses": {"passive_perception": 10,
                         "special": {"darkvision": 60}},
        }
        actor_spec = {
            "instance_id": "g1",
            "template": template,
            "darkvision_range_ft": 120,    # drow override
        }
        actor = _build_actor(actor_spec, registry=None)
        self.assertEqual(actor.darkvision_range_ft, 120)

    def test_no_darkvision_default_zero(self) -> None:
        from engine.cli import _build_actor
        template = {
            "id": "m_test", "name": "Test",
            "combat": {"armor_class": 12, "speed": {"walk": 30},
                          "hit_points": {"average": 10}},
            "abilities": {k: {"score": 10, "save": 0}
                            for k in ("str", "dex", "con",
                                       "int", "wis", "cha")},
            # no senses block at all
        }
        actor_spec = {
            "instance_id": "h1",
            "template": template,
        }
        actor = _build_actor(actor_spec, registry=None)
        self.assertEqual(actor.darkvision_range_ft, 0)


if __name__ == "__main__":
    unittest.main()
