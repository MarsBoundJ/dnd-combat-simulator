"""Truesight + Blindsight + Magical darkness tests (PR #52).

Layers:
  1. Zone detection: is_in_magical_dark_zone
  2. cli._build_actor loads truesight_range_ft + blindsight_range_ft
     from template senses.special.* and from actor_spec overrides
  3. Blindsight (dominant override):
     - Bypasses Invisible
     - Bypasses heavy obscurement (fog)
     - Bypasses ordinary darkness without darkvision
     - Bypasses magical darkness without truesight
     - Bypasses self-blinded (the blinded condition on the observer)
     - Out-of-range falls back to ordinary precedence
  4. Truesight:
     - Bypasses spell-source Invisible (which passive Perception can't)
     - Bypasses Hide-source Invisible too (redundant with passive,
       but cheaper than rolling — exercises the new branch)
     - Bypasses magical darkness within range
     - Bypasses ordinary darkness within range (substitutes for
       darkvision when actor lacks both)
     - Does NOT bypass heavy obscurement (fog still blocks)
     - Out-of-range: no bypass
  5. Magical darkness:
     - Blocks ordinary darkvision (even at full range)
     - Truesight in range pierces
     - Blindsight in range pierces (handled at top of can_actor_see)
     - Combined zones: regular dark zone + magical dark zone both blocked
       without sufficient sense

Run via:
    python -m unittest tests.test_truesight_blindsight
"""
from __future__ import annotations

import unittest

from engine.core.state import Actor, CombatState, Encounter
from engine.core.vision import (
    can_actor_see, is_in_magical_dark_zone,
)


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0),
                  applied_conditions=None,
                  darkvision_range_ft=0,
                  truesight_range_ft=0,
                  blindsight_range_ft=0,
                  passive_perception=10) -> Actor:
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
                   darkvision_range_ft=darkvision_range_ft,
                   truesight_range_ft=truesight_range_ft,
                   blindsight_range_ft=blindsight_range_ft,
                   passive_perception=passive_perception)
    if applied_conditions:
        actor.applied_conditions = list(applied_conditions)
    return actor


def _state_with(actors, environment=None):
    enc = Encounter(id="t", actors=actors, environment=environment or {})
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _invisible(source="spell"):
    """Build an Invisible condition. source='spell' (default) is
    NOT passive-perception-bypassable; source='a_hide' IS.
    """
    cond = {"condition_id": "co_invisible"}
    if source == "a_hide":
        cond["source_action_id"] = "a_hide"
        cond["stealth_total"] = 25    # high — only truesight should pierce
    else:
        cond["source_action_id"] = "a_invisibility_spell"
    return cond


def _blinded():
    return {"condition_id": "co_blinded"}


# ============================================================================
# Layer 1: magical-darkness zone helper
# ============================================================================

class MagicalDarkZoneDetectionTest(unittest.TestCase):

    def test_no_zones_returns_false(self) -> None:
        state = _state_with([_make_actor("a")])
        self.assertFalse(is_in_magical_dark_zone((5, 5), state))

    def test_position_inside_zone(self) -> None:
        env = {"magical_dark_zones": [{"x_min": 0, "x_max": 3,
                                          "y_min": 0, "y_max": 3}]}
        state = _state_with([_make_actor("a")], environment=env)
        self.assertTrue(is_in_magical_dark_zone((1, 1), state))

    def test_position_outside_zone(self) -> None:
        env = {"magical_dark_zones": [{"x_min": 0, "x_max": 3,
                                          "y_min": 0, "y_max": 3}]}
        state = _state_with([_make_actor("a")], environment=env)
        self.assertFalse(is_in_magical_dark_zone((10, 0), state))


# ============================================================================
# Layer 2: cli._build_actor loading
# ============================================================================

class BuildActorSenseFieldsTest(unittest.TestCase):

    def test_template_truesight_loaded(self) -> None:
        from engine.cli import _build_actor
        template = {
            "id": "m_test", "name": "Test",
            "combat": {"armor_class": 12, "speed": {"walk": 30},
                          "hit_points": {"average": 10}},
            "abilities": {k: {"score": 10, "save": 0}
                            for k in ("str", "dex", "con",
                                       "int", "wis", "cha")},
            "senses": {"passive_perception": 10,
                         "special": {"truesight": 120}},
        }
        actor = _build_actor({"instance_id": "x", "template": template},
                                registry=None)
        self.assertEqual(actor.truesight_range_ft, 120)

    def test_template_blindsight_loaded(self) -> None:
        from engine.cli import _build_actor
        template = {
            "id": "m_test", "name": "Test",
            "combat": {"armor_class": 12, "speed": {"walk": 30},
                          "hit_points": {"average": 10}},
            "abilities": {k: {"score": 10, "save": 0}
                            for k in ("str", "dex", "con",
                                       "int", "wis", "cha")},
            "senses": {"passive_perception": 10,
                         "special": {"blindsight": 30}},
        }
        actor = _build_actor({"instance_id": "x", "template": template},
                                registry=None)
        self.assertEqual(actor.blindsight_range_ft, 30)

    def test_actor_spec_overrides_win(self) -> None:
        from engine.cli import _build_actor
        template = {
            "id": "m_test", "name": "Test",
            "combat": {"armor_class": 12, "speed": {"walk": 30},
                          "hit_points": {"average": 10}},
            "abilities": {k: {"score": 10, "save": 0}
                            for k in ("str", "dex", "con",
                                       "int", "wis", "cha")},
            "senses": {"passive_perception": 10,
                         "special": {"truesight": 60,
                                       "blindsight": 30}},
        }
        actor = _build_actor({"instance_id": "x", "template": template,
                                 "truesight_range_ft": 120,
                                 "blindsight_range_ft": 60},
                                registry=None)
        self.assertEqual(actor.truesight_range_ft, 120)
        self.assertEqual(actor.blindsight_range_ft, 60)

    def test_no_senses_defaults_zero(self) -> None:
        from engine.cli import _build_actor
        template = {
            "id": "m_test", "name": "Test",
            "combat": {"armor_class": 12, "speed": {"walk": 30},
                          "hit_points": {"average": 10}},
            "abilities": {k: {"score": 10, "save": 0}
                            for k in ("str", "dex", "con",
                                       "int", "wis", "cha")},
        }
        actor = _build_actor({"instance_id": "x", "template": template},
                                registry=None)
        self.assertEqual(actor.truesight_range_ft, 0)
        self.assertEqual(actor.blindsight_range_ft, 0)


# ============================================================================
# Layer 3: Blindsight (dominant override)
# ============================================================================

class BlindsightTest(unittest.TestCase):

    def test_blindsight_bypasses_invisible(self) -> None:
        obs = _make_actor("bat", blindsight_range_ft=60)
        tgt = _make_actor("wiz", applied_conditions=[_invisible()])
        state = _state_with([obs, tgt])
        self.assertTrue(can_actor_see(obs, tgt, state))

    def test_blindsight_bypasses_fog(self) -> None:
        env = {"heavily_obscured_zones": [{"x_min": 0, "x_max": 10,
                                              "y_min": 0, "y_max": 10}]}
        obs = _make_actor("bat", position=(20, 0), blindsight_range_ft=120)
        tgt = _make_actor("rogue", position=(5, 5))
        state = _state_with([obs, tgt], environment=env)
        # Distance = max(15, 5) = 15 squares = 75 ft ≤ 120
        self.assertTrue(can_actor_see(obs, tgt, state))

    def test_blindsight_bypasses_darkness(self) -> None:
        env = {"dark_zones": [{"x_min": 0, "x_max": 5,
                                  "y_min": 0, "y_max": 5}]}
        # Observer has NO darkvision but does have blindsight.
        obs = _make_actor("bat", position=(10, 0), blindsight_range_ft=60)
        tgt = _make_actor("rogue", position=(2, 2))
        state = _state_with([obs, tgt], environment=env)
        self.assertTrue(can_actor_see(obs, tgt, state))

    def test_blindsight_bypasses_magical_darkness(self) -> None:
        env = {"magical_dark_zones": [{"x_min": 0, "x_max": 5,
                                          "y_min": 0, "y_max": 5}]}
        obs = _make_actor("bat", position=(10, 0), blindsight_range_ft=60,
                            darkvision_range_ft=120)    # DV irrelevant; BS wins
        tgt = _make_actor("rogue", position=(2, 2))
        state = _state_with([obs, tgt], environment=env)
        self.assertTrue(can_actor_see(obs, tgt, state))

    def test_blindsight_works_while_self_blinded(self) -> None:
        # Blindsight perceives without sight, so the Blinded condition
        # on the observer shouldn't matter within range.
        obs = _make_actor("bat", blindsight_range_ft=60,
                            applied_conditions=[_blinded()])
        tgt = _make_actor("wiz")
        state = _state_with([obs, tgt])
        self.assertTrue(can_actor_see(obs, tgt, state))

    def test_blindsight_out_of_range_falls_back(self) -> None:
        # Out of blindsight range — normal precedence applies.
        # Observer has blindsight 30 ft but target is 75 ft away.
        # Also Invisible — so should be blocked.
        obs = _make_actor("bat", position=(0, 0), blindsight_range_ft=30)
        tgt = _make_actor("wiz", position=(15, 0),
                            applied_conditions=[_invisible()])
        state = _state_with([obs, tgt])
        self.assertFalse(can_actor_see(obs, tgt, state))

    def test_blindsight_at_exact_range_boundary_sees(self) -> None:
        obs = _make_actor("bat", position=(0, 0), blindsight_range_ft=30)
        # 6 squares × 5 ft = 30 ft = exact boundary
        tgt = _make_actor("wiz", position=(6, 0))
        state = _state_with([obs, tgt])
        self.assertTrue(can_actor_see(obs, tgt, state))


# ============================================================================
# Layer 4: Truesight
# ============================================================================

class TruesightTest(unittest.TestCase):

    def test_truesight_bypasses_spell_invisible(self) -> None:
        obs = _make_actor("paladin", truesight_range_ft=60)
        tgt = _make_actor("wiz", applied_conditions=[_invisible()])
        state = _state_with([obs, tgt])
        self.assertTrue(can_actor_see(obs, tgt, state))

    def test_truesight_bypasses_hide_invisible_too(self) -> None:
        # Hide-source Invisible with stealth_total 25 — passive
        # Perception can't reach. But truesight ignores it.
        obs = _make_actor("paladin", truesight_range_ft=60,
                             passive_perception=10)
        tgt = _make_actor("rogue",
                             applied_conditions=[_invisible(source="a_hide")])
        state = _state_with([obs, tgt])
        self.assertTrue(can_actor_see(obs, tgt, state))

    def test_truesight_bypasses_magical_darkness(self) -> None:
        env = {"magical_dark_zones": [{"x_min": 0, "x_max": 5,
                                          "y_min": 0, "y_max": 5}]}
        obs = _make_actor("paladin", position=(10, 0), truesight_range_ft=60)
        tgt = _make_actor("rogue", position=(2, 2))
        state = _state_with([obs, tgt], environment=env)
        self.assertTrue(can_actor_see(obs, tgt, state))

    def test_truesight_bypasses_ordinary_darkness(self) -> None:
        # No darkvision, only truesight. Should still see in regular dark.
        env = {"dark_zones": [{"x_min": 0, "x_max": 5,
                                  "y_min": 0, "y_max": 5}]}
        obs = _make_actor("paladin", position=(10, 0), truesight_range_ft=60)
        tgt = _make_actor("rogue", position=(2, 2))
        state = _state_with([obs, tgt], environment=env)
        self.assertTrue(can_actor_see(obs, tgt, state))

    def test_truesight_does_NOT_bypass_fog(self) -> None:
        # Truesight sees through DARK and INVISIBILITY, not through
        # physical obscuring substances like fog or leaves.
        env = {"heavily_obscured_zones": [{"x_min": 0, "x_max": 5,
                                              "y_min": 0, "y_max": 5}]}
        obs = _make_actor("paladin", position=(10, 0), truesight_range_ft=60)
        tgt = _make_actor("rogue", position=(2, 2))
        state = _state_with([obs, tgt], environment=env)
        self.assertFalse(can_actor_see(obs, tgt, state))

    def test_truesight_out_of_range_does_not_bypass(self) -> None:
        # Truesight 30 ft, target 75 ft away in magical darkness.
        env = {"magical_dark_zones": [{"x_min": 0, "x_max": 5,
                                          "y_min": 0, "y_max": 5}]}
        obs = _make_actor("paladin", position=(15, 0), truesight_range_ft=30)
        tgt = _make_actor("rogue", position=(0, 0))
        state = _state_with([obs, tgt], environment=env)
        self.assertFalse(can_actor_see(obs, tgt, state))

    def test_truesight_at_exact_range_boundary_sees_invisible(self) -> None:
        obs = _make_actor("paladin", position=(0, 0), truesight_range_ft=60)
        tgt = _make_actor("wiz", position=(12, 0),    # exactly 60 ft
                             applied_conditions=[_invisible()])
        state = _state_with([obs, tgt])
        self.assertTrue(can_actor_see(obs, tgt, state))


# ============================================================================
# Layer 5: Magical darkness specifics
# ============================================================================

class MagicalDarknessTest(unittest.TestCase):

    def test_ordinary_darkvision_does_NOT_pierce_magical_darkness(self) -> None:
        env = {"magical_dark_zones": [{"x_min": 0, "x_max": 5,
                                          "y_min": 0, "y_max": 5}]}
        # Observer has darkvision 60 ft — enough range, but RAW says
        # ordinary darkvision can't see through MAGICAL darkness.
        obs = _make_actor("dwarf", position=(10, 0), darkvision_range_ft=60)
        tgt = _make_actor("rogue", position=(2, 2))
        state = _state_with([obs, tgt], environment=env)
        self.assertFalse(can_actor_see(obs, tgt, state))

    def test_observer_in_magical_darkness_with_truesight_sees_out(self) -> None:
        env = {"magical_dark_zones": [{"x_min": 0, "x_max": 5,
                                          "y_min": 0, "y_max": 5}]}
        obs = _make_actor("paladin", position=(2, 2), truesight_range_ft=60)
        tgt = _make_actor("ogre", position=(10, 0))
        state = _state_with([obs, tgt], environment=env)
        self.assertTrue(can_actor_see(obs, tgt, state))

    def test_observer_in_magical_darkness_with_only_darkvision_blind(self) -> None:
        env = {"magical_dark_zones": [{"x_min": 0, "x_max": 5,
                                          "y_min": 0, "y_max": 5}]}
        obs = _make_actor("dwarf", position=(2, 2), darkvision_range_ft=60)
        tgt = _make_actor("ogre", position=(10, 0))
        state = _state_with([obs, tgt], environment=env)
        self.assertFalse(can_actor_see(obs, tgt, state))

    def test_overlapping_regular_and_magical_dark_zones(self) -> None:
        # Both zone types declared. Magical-dark check is stricter, so
        # any actor in BOTH should be treated as in magical dark.
        env = {
            "dark_zones": [{"x_min": 0, "x_max": 10,
                              "y_min": 0, "y_max": 10}],
            "magical_dark_zones": [{"x_min": 2, "x_max": 5,
                                       "y_min": 2, "y_max": 5}],
        }
        # Observer at (15, 0) has darkvision 60 ft. Target at (3, 3) is
        # in BOTH zones. Magical darkness should block ordinary DV.
        obs = _make_actor("dwarf", position=(15, 0), darkvision_range_ft=60)
        tgt = _make_actor("rogue", position=(3, 3))
        state = _state_with([obs, tgt], environment=env)
        self.assertFalse(can_actor_see(obs, tgt, state))


# ============================================================================
# Layer 6: precedence / interactions
# ============================================================================

class VisionPrecedenceTest(unittest.TestCase):

    def test_blindsight_beats_self_blinded_AND_invisible_target(self) -> None:
        # Stress test: observer is blinded, target is invisible AND in
        # magical darkness. Blindsight in range should still return True.
        env = {"magical_dark_zones": [{"x_min": 0, "x_max": 5,
                                          "y_min": 0, "y_max": 5}]}
        obs = _make_actor("bat", position=(5, 5), blindsight_range_ft=60,
                            applied_conditions=[_blinded()])
        tgt = _make_actor("wiz", position=(2, 2),
                            applied_conditions=[_invisible()])
        state = _state_with([obs, tgt], environment=env)
        self.assertTrue(can_actor_see(obs, tgt, state))

    def test_truesight_AND_fog_still_blocked(self) -> None:
        # Truesight in range but target in fog → still blocked.
        # Pinned to ensure step-4 (heavy obscurement) fires before
        # step-5/6 darkness gates would even check truesight.
        env = {"heavily_obscured_zones": [{"x_min": 0, "x_max": 5,
                                              "y_min": 0, "y_max": 5}]}
        obs = _make_actor("paladin", position=(10, 0), truesight_range_ft=120)
        tgt = _make_actor("rogue", position=(2, 2),
                            applied_conditions=[_invisible()])
        state = _state_with([obs, tgt], environment=env)
        # Truesight bypasses Invisible, but fog still blocks.
        self.assertFalse(can_actor_see(obs, tgt, state))

    def test_no_senses_in_magical_dark_blocked(self) -> None:
        env = {"magical_dark_zones": [{"x_min": 0, "x_max": 5,
                                          "y_min": 0, "y_max": 5}]}
        obs = _make_actor("commoner", position=(10, 0))    # no senses
        tgt = _make_actor("rogue", position=(2, 2))
        state = _state_with([obs, tgt], environment=env)
        self.assertFalse(can_actor_see(obs, tgt, state))

    def test_self_sees_self_short_circuits_even_with_senses(self) -> None:
        # Defensive: the self short-circuit must fire before any sense
        # check (else a Blinded actor with no blindsight couldn't
        # self-target their own modifier when-clauses).
        obs = _make_actor("rogue",
                             applied_conditions=[_blinded()])
        state = _state_with([obs])
        self.assertTrue(can_actor_see(obs, obs, state))


if __name__ == "__main__":
    unittest.main()
