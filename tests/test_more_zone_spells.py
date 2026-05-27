"""Tests for the four additional zone-creating spells (PR #79).

Spells covered:
  - Fog Cloud (heavy_obscurement, zone-only)
  - Stinking Cloud (CON save → co_incapacitated)
  - Web (DEX save → co_restrained, cube shape)
  - Silence (creates silence_zone, suppresses Verbal spellcasting
    for actors inside)

Layers:
  1. Feature YAMLs load correctly
  2. Silence: pipeline filter blocks spell candidates for actors
     inside silence_zone
  3. Silence: spells unblocked for actors OUTSIDE the zone
  4. Silence: cantrips (slot_level=0) unaffected by filter
  5. Silence: weapon attacks unaffected by filter
  6. Silence: zone scrubbed when concentration drops
  7. Silence: _actor_in_silence_zone predicate edge cases
  8. Fog Cloud: registers heavy_obscurement zone, no damage
  9. Stinking Cloud: forced_save with co_incapacitated on_fail
 10. Web: cube shape, forced_save with co_restrained on_fail
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0),
                  spell_slots=None, hp=30, ac=14, str_score=14):
    abilities = {k: {"score": str_score if k == "str" else 10,
                       "save": 2 if k == "str" else 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [],
    }
    actor = Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp, ac=ac,
        speed={"walk": 30}, position=position, abilities=abilities,
        spell_slots=dict(spell_slots or {}),
        spell_slots_max=dict(spell_slots or {}),
    )
    return actor


def _make_state(actors, *, env=None):
    enc = Encounter(id="t", actors=actors,
                      environment=dict(env or {}))
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Layer 1: feature YAMLs load
# ============================================================================

class FeatureLoadingTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_fog_cloud_loads(self) -> None:
        spell = self.registry.get("feature", "f_fog_cloud")
        action = spell["action_template"]
        self.assertEqual(action["spell_slot_level"], 1)
        self.assertEqual(action["concentration"], True)
        aura_params = action["pipeline"][0]["params"]
        self.assertEqual(aura_params["creates_zone"], "heavy_obscurement")
        self.assertEqual(aura_params["radius_ft"], 20)
        # Zone-only — no on_fail damage
        self.assertEqual(aura_params["on_fail"], [])
        self.assertEqual(aura_params["on_success"], [])

    def test_stinking_cloud_loads(self) -> None:
        spell = self.registry.get("feature", "f_stinking_cloud")
        action = spell["action_template"]
        self.assertEqual(action["spell_slot_level"], 3)
        aura_params = action["pipeline"][0]["params"]
        self.assertEqual(aura_params["ability"], "constitution")
        on_fail = aura_params["on_fail"]
        self.assertEqual(len(on_fail), 1)
        self.assertEqual(on_fail[0]["primitive"], "apply_condition")
        self.assertEqual(on_fail[0]["params"]["condition_id"],
                          "co_incapacitated")

    def test_web_loads(self) -> None:
        spell = self.registry.get("feature", "f_web")
        action = spell["action_template"]
        self.assertEqual(action["spell_slot_level"], 2)
        aura_params = action["pipeline"][0]["params"]
        self.assertEqual(aura_params["shape"], "cube")
        self.assertEqual(aura_params["size_ft"], 20)
        self.assertEqual(aura_params["ability"], "dexterity")
        on_fail = aura_params["on_fail"]
        self.assertEqual(on_fail[0]["params"]["condition_id"],
                          "co_restrained")

    def test_silence_loads(self) -> None:
        spell = self.registry.get("feature", "f_silence")
        action = spell["action_template"]
        self.assertEqual(action["spell_slot_level"], 2)
        aura_params = action["pipeline"][0]["params"]
        self.assertEqual(aura_params["creates_zone"], "silence")
        self.assertEqual(aura_params["radius_ft"], 20)


# ============================================================================
# Layer 2+3+4+5+7: Silence pipeline filter + predicate
# ============================================================================

class SilenceFilterTest(unittest.TestCase):

    def test_actor_in_silence_zone_predicate(self) -> None:
        from engine.core.pipeline import _actor_in_silence_zone
        actor = _make_actor("a", position=(0, 0))
        # No zones
        state = _make_state([actor])
        self.assertFalse(_actor_in_silence_zone(actor, state))
        # Add a silence_zone covering (0, 0)
        env = {"silence_zones": [{"shape": "sphere",
                                    "center": [0, 0],
                                    "radius_ft": 20}]}
        state = _make_state([actor], env=env)
        self.assertTrue(_actor_in_silence_zone(actor, state))
        # Actor outside the zone (60 ft away = 12 squares away)
        actor.position = (12, 0)
        self.assertFalse(_actor_in_silence_zone(actor, state))

    def test_silence_filters_spells_for_inside_actor(self) -> None:
        # Caster inside silence zone has a 3rd-level spell action;
        # should NOT appear in candidate list.
        caster = _make_actor("caster", position=(0, 0),
                                spell_slots={3: 2})
        # Give the caster a fireball-shape spell (any spell will do)
        fireball = {
            "id": "a_fireball", "type": "aoe_attack",
            "spell_slot_level": 3,
            "area": {"shape": "sphere", "radius_ft": 20,
                       "range_ft": 150},
            "pipeline": [
                {"primitive": "forced_save",
                  "params": {"ability": "dexterity", "dc": 15}},
            ],
        }
        caster.template["actions"] = [fireball]
        enemy = _make_actor("e", side="enemy", position=(5, 0))
        env = {"silence_zones": [{"shape": "sphere",
                                    "center": [0, 0],
                                    "radius_ft": 20}]}
        state = _make_state([caster, enemy], env=env)
        candidates = pipeline.generate_candidates(caster, state,
                                                      slot="action")
        # No spell candidate emitted — Fireball filtered
        spell_candidates = [c for c in candidates
                              if c.get("action", {}).get("id") == "a_fireball"]
        self.assertEqual(len(spell_candidates), 0)

    def test_silence_does_not_filter_outside_actor(self) -> None:
        caster = _make_actor("caster", position=(20, 0),  # outside
                                spell_slots={3: 2})
        fireball = {
            "id": "a_fireball", "type": "aoe_attack",
            "spell_slot_level": 3,
            "area": {"shape": "sphere", "radius_ft": 20,
                       "range_ft": 150},
            "pipeline": [
                {"primitive": "forced_save",
                  "params": {"ability": "dexterity", "dc": 15}},
            ],
        }
        caster.template["actions"] = [fireball]
        enemy = _make_actor("e", side="enemy", position=(25, 0))
        env = {"silence_zones": [{"shape": "sphere",
                                    "center": [0, 0],
                                    "radius_ft": 20}]}
        state = _make_state([caster, enemy], env=env)
        candidates = pipeline.generate_candidates(caster, state,
                                                      slot="action")
        spell_candidates = [c for c in candidates
                              if c.get("action", {}).get("id") == "a_fireball"]
        # Caster outside silence_zone → spell available
        self.assertEqual(len(spell_candidates), 1)

    def test_silence_does_not_filter_cantrips(self) -> None:
        # spell_slot_level: 0 should NOT be filtered
        caster = _make_actor("caster", position=(0, 0),
                                spell_slots={})  # no slots, but cantrip
        cantrip = {
            "id": "a_firebolt", "type": "weapon_attack",
            "spell_slot_level": 0,
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "ranged", "bonus": 5,
                              "range_ft": 60}},
            ],
        }
        caster.template["actions"] = [cantrip]
        enemy = _make_actor("e", side="enemy", position=(5, 0))
        env = {"silence_zones": [{"shape": "sphere",
                                    "center": [0, 0],
                                    "radius_ft": 20}]}
        state = _make_state([caster, enemy], env=env)
        candidates = pipeline.generate_candidates(caster, state,
                                                      slot="action")
        cantrip_candidates = [c for c in candidates
                                 if c.get("action", {}).get("id") == "a_firebolt"]
        self.assertEqual(len(cantrip_candidates), 1)

    def test_silence_does_not_filter_weapon_attacks(self) -> None:
        attacker = _make_actor("a", position=(0, 0))
        weapon = {
            "id": "a_sword", "type": "weapon_attack",
            # No spell_slot_level field — non-spell
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "melee", "bonus": 5,
                              "reach_ft": 5}},
            ],
        }
        attacker.template["actions"] = [weapon]
        enemy = _make_actor("e", side="enemy", position=(1, 0))
        env = {"silence_zones": [{"shape": "sphere",
                                    "center": [0, 0],
                                    "radius_ft": 20}]}
        state = _make_state([attacker, enemy], env=env)
        candidates = pipeline.generate_candidates(attacker, state,
                                                      slot="action")
        weapon_candidates = [c for c in candidates
                                if c.get("kind") == "weapon_attack"]
        self.assertEqual(len(weapon_candidates), 1)


# ============================================================================
# Layer 6: silence zone scrubbed on concentration drop
# ============================================================================

class SilenceConcentrationScrubTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_silence_zone_removed_when_concentration_drops(self) -> None:
        from engine.primitives import _persistent_aura
        from engine.core.concentration import end_concentration
        caster = _make_actor("caster", position=(0, 0))
        state = _make_state([caster])
        # Synthesize a Silence cast directly
        state.current_attack = {
            "actor": caster,
            "action": {"id": "a_silence", "concentration": True,
                          "named_effect": "silence"},
            "area_origin": (0, 0),
        }
        caster.concentration_on = {"action_id": "a_silence",
                                       "caster_id": caster.id,
                                       "applied_at_round": 1}
        _persistent_aura({
            "shape": "sphere", "radius_ft": 20, "anchor": "point",
            "trigger_event": "target_turn_start_in_area",
            "affected": "all_creatures",
            "ability": "none", "on_fail": [], "on_success": [],
            "creates_zone": "silence",
        }, state, EventBus())
        # Zone exists
        env = state.encounter.environment or {}
        self.assertEqual(len(env.get("silence_zones") or []), 1)
        # Drop concentration → zone scrubbed
        end_concentration(caster, state, reason="test")
        env = state.encounter.environment or {}
        self.assertEqual(len(env.get("silence_zones") or []), 0)


# ============================================================================
# Layer 8: Fog Cloud zone creation
# ============================================================================

class FogCloudZoneTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_fog_cloud_creates_heavy_obscurement_zone(self) -> None:
        from engine.primitives import _persistent_aura
        caster = _make_actor("caster", position=(0, 0))
        state = _make_state([caster])
        state.current_attack = {
            "actor": caster,
            "action": {"id": "a_fog_cloud", "concentration": True,
                          "named_effect": "fog_cloud"},
            "area_origin": (0, 0),
        }
        _persistent_aura({
            "shape": "sphere", "radius_ft": 20, "anchor": "point",
            "trigger_event": "target_turn_start_in_area",
            "affected": "all_creatures",
            "ability": "none", "on_fail": [], "on_success": [],
            "creates_zone": "heavy_obscurement",
        }, state, EventBus())
        env = state.encounter.environment or {}
        zones = env.get("heavily_obscured_zones") or []
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]["radius_ft"], 20)


# ============================================================================
# Layer 9: Stinking Cloud incapacitation on fail
# ============================================================================

class StinkingCloudIncapacitationTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_stinking_cloud_applies_incapacitated_on_fail(self) -> None:
        # Run the aura's forced_save with a guaranteed-fail target
        # (DC 99). Verify co_incapacitated applied.
        from engine.primitives import _forced_save
        target = _make_actor("t", side="enemy", position=(0, 0))
        caster = _make_actor("caster")
        state = _make_state([target, caster])
        state.current_attack = {
            "actor": caster, "target": target,
            "action": {"id": "a_stinking_cloud", "concentration": True,
                          "named_effect": "stinking_cloud"},
        }
        _forced_save({
            "ability": "constitution", "dc": 99,
            "affected": "current_target",
            "on_fail": [
                {"primitive": "apply_condition",
                  "params": {"condition_id": "co_incapacitated",
                              "duration": "until_actor_next_turn_start"}},
            ],
            "on_success": [],
        }, state, EventBus())
        applied = [c["condition_id"] for c in target.applied_conditions]
        self.assertIn("co_incapacitated", applied)


# ============================================================================
# Layer 10: Web restrains on fail
# ============================================================================

class WebRestrainedTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_web_applies_restrained_on_fail(self) -> None:
        from engine.primitives import _forced_save
        target = _make_actor("t", side="enemy", position=(0, 0))
        caster = _make_actor("caster")
        state = _make_state([target, caster])
        state.current_attack = {
            "actor": caster, "target": target,
            "action": {"id": "a_web", "concentration": True,
                          "named_effect": "web"},
        }
        _forced_save({
            "ability": "dexterity", "dc": 99,
            "affected": "current_target",
            "on_fail": [
                {"primitive": "apply_condition",
                  "params": {"condition_id": "co_restrained",
                              "duration": "until_actor_next_turn_start"}},
            ],
            "on_success": [],
        }, state, EventBus())
        applied = [c["condition_id"] for c in target.applied_conditions]
        self.assertIn("co_restrained", applied)


if __name__ == "__main__":
    unittest.main()
