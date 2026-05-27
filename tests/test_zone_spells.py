"""Hunger of Hadar + Cloudkill zone-spell tests (PR #68).

Layers:
  1. _CREATES_ZONE_TO_ENV_KEY mapping completeness
  2. _persistent_aura with creates_zone="heavy_obscurement"
     appends a sphere zone to heavily_obscured_zones
  3. _persistent_aura with creates_zone="magical_dark" still
     appends to magical_dark_zones (regression)
  4. Unknown creates_zone value raises with the known-list
  5. end_concentration scrubs heavy_obscurement zones alongside
     magical_dark zones
  6. Vision: Cloudkill's heavy_obscurement zone blocks LOS
     (truesight can't pierce fog; blindsight can)
  7. Vision: Hunger of Hadar's magical_dark zone blocks ordinary
     darkvision (truesight pierces; blindsight pierces)
  8. Feature YAML files load + match expected shape
"""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from engine.core.concentration import end_concentration
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.core.vision import (
    can_actor_see, is_in_magical_dark_zone, is_in_obscured_zone,
)
from engine.primitives import _CREATES_ZONE_TO_ENV_KEY, _persistent_aura


FEATURES_DIR = Path(__file__).resolve().parent.parent \
    / "schema" / "content" / "features"


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


def _action_for(zone_type: str, action_id: str):
    """Build a minimal persistent_aura action that creates `zone_type`."""
    return {
        "id": action_id, "name": action_id,
        "type": "persistent_aura",
        "spell_slot_level": 3, "concentration": True,
        "named_effect": action_id,
        "pipeline": [
            {"primitive": "persistent_aura",
              "params": {
                  "shape": "sphere", "radius_ft": 20,
                  "anchor": "point",
                  "ability": "none",
                  "on_fail": [], "on_success": [],
                  "creates_zone": zone_type,
              }},
        ],
    }


def _cast_aura(caster, action, origin, state):
    """Simulate casting a persistent_aura action (sets state.current_attack
    and invokes the primitive)."""
    caster.concentration_on = {"action_id": action["id"],
                                  "caster_id": caster.id,
                                  "applied_at_round": 1}
    state.current_attack = {
        "actor": caster, "target": caster, "action": action,
        "area_origin": origin,
    }
    params = action["pipeline"][0]["params"]
    _persistent_aura(params, state, EventBus())


# ============================================================================
# Layer 1: mapping completeness
# ============================================================================

class CreatesZoneMappingTest(unittest.TestCase):

    def test_magical_dark_present(self) -> None:
        self.assertIn("magical_dark", _CREATES_ZONE_TO_ENV_KEY)
        self.assertEqual(_CREATES_ZONE_TO_ENV_KEY["magical_dark"],
                            "magical_dark_zones")

    def test_heavy_obscurement_present(self) -> None:
        self.assertIn("heavy_obscurement", _CREATES_ZONE_TO_ENV_KEY)
        self.assertEqual(_CREATES_ZONE_TO_ENV_KEY["heavy_obscurement"],
                            "heavily_obscured_zones")


# ============================================================================
# Layer 2: heavy_obscurement zone creation
# ============================================================================

class CreateHeavyObscurementTest(unittest.TestCase):

    def test_appends_sphere_to_heavily_obscured_zones(self) -> None:
        caster = _make_actor("wiz")
        state = _state_with([caster])
        action = _action_for("heavy_obscurement", "a_cloudkill")
        _cast_aura(caster, action, (5, 5), state)
        zones = state.encounter.environment.get("heavily_obscured_zones") or []
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]["shape"], "sphere")
        self.assertEqual(zones[0]["center"], [5, 5])
        self.assertEqual(zones[0]["radius_ft"], 20)
        self.assertEqual(zones[0]["caster_id"], "wiz")
        self.assertEqual(zones[0]["action_id"], "a_cloudkill")


# ============================================================================
# Layer 3: magical_dark regression
# ============================================================================

class MagicalDarkRegressionTest(unittest.TestCase):

    def test_magical_dark_still_works(self) -> None:
        caster = _make_actor("wiz")
        state = _state_with([caster])
        action = _action_for("magical_dark", "a_darkness")
        _cast_aura(caster, action, (5, 5), state)
        zones = state.encounter.environment.get("magical_dark_zones") or []
        self.assertEqual(len(zones), 1)


# ============================================================================
# Layer 4: unknown zone type
# ============================================================================

class UnknownZoneTypeTest(unittest.TestCase):

    def test_unknown_creates_zone_raises(self) -> None:
        caster = _make_actor("wiz")
        state = _state_with([caster])
        action = _action_for("not_a_zone_type", "a_bad")
        with self.assertRaises(ValueError) as ctx:
            _cast_aura(caster, action, (5, 5), state)
        self.assertIn("not recognized", str(ctx.exception).lower())


# ============================================================================
# Layer 5: end_concentration scrubs both types
# ============================================================================

class EndConcentrationScrubTest(unittest.TestCase):

    def test_drops_heavy_obscurement_zone(self) -> None:
        caster = _make_actor("wiz")
        state = _state_with([caster])
        action = _action_for("heavy_obscurement", "a_cloudkill")
        _cast_aura(caster, action, (5, 5), state)
        self.assertEqual(
            len(state.encounter.environment.get("heavily_obscured_zones")), 1)
        end_concentration(caster, state, reason="dropped")
        zones = state.encounter.environment.get("heavily_obscured_zones") or []
        self.assertEqual(len(zones), 0)

    def test_static_obscurement_zones_preserved(self) -> None:
        """Statically-declared heavy obscurement (e.g., fog from
        fixture) survives unrelated concentration drops."""
        caster = _make_actor("wiz")
        state = _state_with([caster], environment={
            "heavily_obscured_zones": [
                {"x_min": 0, "x_max": 3, "y_min": 0, "y_max": 3},
            ],
        })
        caster.concentration_on = {"action_id": "a_some_spell",
                                      "caster_id": caster.id,
                                      "applied_at_round": 1}
        end_concentration(caster, state, reason="dropped")
        zones = state.encounter.environment.get("heavily_obscured_zones") or []
        self.assertEqual(len(zones), 1)

    def test_two_casters_independent_zones(self) -> None:
        """Two Cloudkills from different casters; ending one only
        removes its own zone."""
        wiz1 = _make_actor("wiz1", position=(0, 0))
        wiz2 = _make_actor("wiz2", position=(20, 20))
        state = _state_with([wiz1, wiz2])
        action1 = _action_for("heavy_obscurement", "a_cloudkill")
        action2 = _action_for("heavy_obscurement", "a_cloudkill")
        _cast_aura(wiz1, action1, (0, 0), state)
        _cast_aura(wiz2, action2, (20, 20), state)
        zones = state.encounter.environment.get("heavily_obscured_zones") or []
        self.assertEqual(len(zones), 2)
        # Drop wiz1's concentration → only its zone removed
        end_concentration(wiz1, state, reason="dropped")
        zones = state.encounter.environment.get("heavily_obscured_zones") or []
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]["caster_id"], "wiz2")


# ============================================================================
# Layer 6: Cloudkill vision integration
# ============================================================================

class CloudkillVisionTest(unittest.TestCase):

    def _setup_cloudkill(self, observer, target, origin=(5, 5)):
        caster = _make_actor("wiz", position=origin)
        state = _state_with([observer, target, caster])
        action = _action_for("heavy_obscurement", "a_cloudkill")
        _cast_aura(caster, action, origin, state)
        return state

    def test_ordinary_vision_blocked_by_cloudkill(self) -> None:
        observer = _make_actor("guard", position=(20, 20))
        target = _make_actor("rogue", side="enemy", position=(5, 5))
        state = self._setup_cloudkill(observer, target)
        self.assertFalse(can_actor_see(observer, target, state))

    def test_truesight_does_NOT_pierce_cloudkill(self) -> None:
        """Truesight sees through magical darkness + Invisible per
        RAW, but NOT through physical fog/obscurement."""
        observer = _make_actor("paladin", position=(8, 5),
                                  truesight_range_ft=120)
        target = _make_actor("rogue", side="enemy", position=(5, 5))
        state = self._setup_cloudkill(observer, target)
        self.assertFalse(can_actor_see(observer, target, state))

    def test_blindsight_pierces_cloudkill(self) -> None:
        """Blindsight perceives surroundings without sight; pierces
        fog within range."""
        observer = _make_actor("bat", position=(8, 5),
                                  blindsight_range_ft=30)
        target = _make_actor("rogue", side="enemy", position=(5, 5))
        state = self._setup_cloudkill(observer, target)
        self.assertTrue(can_actor_see(observer, target, state))

    def test_is_in_obscured_zone_recognizes_sphere(self) -> None:
        caster = _make_actor("wiz")
        state = _state_with([caster])
        action = _action_for("heavy_obscurement", "a_cloudkill")
        _cast_aura(caster, action, (0, 0), state)
        # Position (3, 0) is 15 ft from origin = within 20-ft sphere
        self.assertTrue(is_in_obscured_zone((3, 0), state))
        # Position (10, 10) is way outside
        self.assertFalse(is_in_obscured_zone((10, 10), state))


# ============================================================================
# Layer 7: Hunger of Hadar vision integration
# ============================================================================

class HungerOfHadarVisionTest(unittest.TestCase):

    def _setup_hoh(self, observer, target, origin=(5, 5)):
        caster = _make_actor("warlock", position=origin)
        state = _state_with([observer, target, caster])
        action = _action_for("magical_dark", "a_hunger_of_hadar")
        _cast_aura(caster, action, origin, state)
        return state

    def test_ordinary_darkvision_blocked_by_hoh(self) -> None:
        observer = _make_actor("dwarf", position=(15, 5),
                                  darkvision_range_ft=120)
        target = _make_actor("rogue", side="enemy", position=(5, 5))
        state = self._setup_hoh(observer, target)
        # Ordinary darkvision can't pierce magical darkness
        self.assertFalse(can_actor_see(observer, target, state))

    def test_truesight_pierces_hoh_in_range(self) -> None:
        observer = _make_actor("paladin", position=(8, 5),
                                  truesight_range_ft=60)
        target = _make_actor("rogue", side="enemy", position=(5, 5))
        state = self._setup_hoh(observer, target)
        # Distance = 15 ft, within truesight 60
        self.assertTrue(can_actor_see(observer, target, state))

    def test_is_in_magical_dark_zone_recognizes_sphere(self) -> None:
        caster = _make_actor("warlock")
        state = _state_with([caster])
        action = _action_for("magical_dark", "a_hunger_of_hadar")
        _cast_aura(caster, action, (0, 0), state)
        # Position (4, 0) is 20 ft from origin = within 20-ft sphere
        self.assertTrue(is_in_magical_dark_zone((4, 0), state))


# ============================================================================
# Layer 8: feature YAML files load + match expected shape
# ============================================================================

class FeatureYAMLLoadingTest(unittest.TestCase):

    def _load(self, file_id):
        path = FEATURES_DIR / f"{file_id}.yaml"
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    def test_hunger_of_hadar_loads(self) -> None:
        f = self._load("f_hunger_of_hadar")
        self.assertEqual(f["id"], "f_hunger_of_hadar")
        self.assertEqual(f["spell"]["level"], 3)
        params = f["action_template"]["pipeline"][0]["params"]
        self.assertEqual(params["creates_zone"], "magical_dark")
        self.assertEqual(params["radius_ft"], 20)

    def test_cloudkill_loads(self) -> None:
        f = self._load("f_cloudkill")
        self.assertEqual(f["id"], "f_cloudkill")
        self.assertEqual(f["spell"]["level"], 5)
        params = f["action_template"]["pipeline"][0]["params"]
        self.assertEqual(params["creates_zone"], "heavy_obscurement")
        self.assertEqual(params["radius_ft"], 20)


if __name__ == "__main__":
    unittest.main()
