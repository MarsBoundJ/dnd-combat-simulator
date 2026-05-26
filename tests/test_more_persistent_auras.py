"""Persistent_aura expansion tests (PR #44).

Covers the new infrastructure added on top of PR #43:
  1. `anchor: point` — origin captured at cast, doesn't move
  2. `affected: all_creatures` — friendly fire mode (used by Moonbeam,
     Cloud of Daggers, future Sickening Radiance)
  3. `ability: 'none'` / no-save path — used by Cloud of Daggers
  4. Cube area shape — `actors_in_cube` helper + runner integration
  5. Moonbeam end-to-end (point-anchored, all_creatures, CON save)
  6. Cloud of Daggers end-to-end (point-anchored, all_creatures,
     no-save, cube shape)

Run via:
    python -m unittest tests.test_more_persistent_auras
"""
from __future__ import annotations

import random
import unittest

from engine.core.state import Actor, Encounter, CombatState
from engine.core.runner import EncounterRunner
from engine.core.geometry import actors_in_cube


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "pc", hp: int = 30,
                ac: int = 14, position: tuple[int, int] = (0, 0),
                con_save: int = 0, initiative_modifier: int = 0,
                actions: list[dict] | None = None) -> Actor:
    abilities = {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 10, "save": 0},
        "con": {"score": 10, "save": con_save},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "combat": {
                    "armor_class": ac,
                    "hit_points": {"average": hp, "dice": "5d10",
                                     "con_contribution": 10},
                    "speed": {"walk": 30},
                    "initiative": {"modifier": initiative_modifier,
                                     "score": initiative_modifier + 10},
                },
                "actions": actions or []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac,
                  speed={"walk": 30}, position=position,
                  abilities=abilities)


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _moonbeam_action() -> dict:
    """Moonbeam — Druid 2nd-level. Point-anchored, all_creatures
    (friendly fire), CON save vs DC 15, 2d10 radiant on fail / half
    on success. Concentration."""
    return {
        "id": "a_moonbeam", "name": "Moonbeam",
        "type": "persistent_aura",
        "spell_slot_level": 2,
        "concentration": True,
        "named_effect": "moonbeam",
        "area": {"shape": "sphere", "radius_ft": 5, "range_ft": 120},
        "pipeline": [
            {"primitive": "persistent_aura",
              "params": {
                  "shape": "sphere",
                  "radius_ft": 5,
                  "anchor": "point",
                  "trigger_event": "target_turn_start_in_area",
                  "affected": "all_creatures",
                  "ability": "constitution",
                  "dc": 15,
                  "on_fail": [{
                      "primitive": "damage",
                      "params": {"dice": "2d10", "type": "radiant"},
                  }],
                  "on_success": [{
                      "primitive": "damage",
                      "params": {"dice": "2d10", "type": "radiant",
                                  "multiplier": 0.5},
                  }],
              }},
        ],
    }


def _cloud_of_daggers_action() -> dict:
    """Cloud of Daggers — Wizard 2nd-level. Point-anchored, cube
    shape (5-ft), all_creatures, NO SAVE, 4d4 slashing. Concentration."""
    return {
        "id": "a_cloud_of_daggers", "name": "Cloud of Daggers",
        "type": "persistent_aura",
        "spell_slot_level": 2,
        "concentration": True,
        "named_effect": "cloud_of_daggers",
        "area": {"shape": "cube", "size_ft": 5, "range_ft": 60},
        "pipeline": [
            {"primitive": "persistent_aura",
              "params": {
                  "shape": "cube",
                  "size_ft": 5,
                  "anchor": "point",
                  "trigger_event": "target_turn_start_in_area",
                  "affected": "all_creatures",
                  "ability": "none",   # no-save path
                  "on_fail": [{
                      "primitive": "damage",
                      "params": {"dice": "4d4", "type": "slashing"},
                  }],
              }},
        ],
    }


# ============================================================================
# Geometry: actors_in_cube
# ============================================================================

class ActorsInCubeTest(unittest.TestCase):

    def test_5_ft_cube_only_origin_square(self) -> None:
        """A 5-ft cube has half-extent of 0 squares — only the
        origin square is in the cube."""
        a_at_origin = _make_actor("a", position=(2, 2))
        a_adjacent = _make_actor("b", position=(3, 2))
        result = actors_in_cube((2, 2), 5, [a_at_origin, a_adjacent])
        self.assertEqual([a.id for a in result], ["a"])

    def test_10_ft_cube_is_3x3(self) -> None:
        """A 10-ft cube has half-extent of 1 square — 3x3 centered."""
        actors = []
        for x in range(-2, 3):
            for y in range(-2, 3):
                actors.append(_make_actor(f"{x}_{y}", position=(x, y)))
        result = actors_in_cube((0, 0), 10, actors)
        # 3x3 = 9 actors, all within max(|x|, |y|) <= 1
        self.assertEqual(len(result), 9)

    def test_20_ft_cube_is_5x5(self) -> None:
        actors = []
        for x in range(-3, 4):
            for y in range(-3, 4):
                actors.append(_make_actor(f"{x}_{y}", position=(x, y)))
        result = actors_in_cube((0, 0), 20, actors)
        self.assertEqual(len(result), 25)


# ============================================================================
# Point anchor — origin captured at cast, doesn't move
# ============================================================================

class PointAnchorTest(unittest.TestCase):

    def test_primitive_records_origin_from_area_origin(self) -> None:
        """When the candidate generator sets area_origin, the
        primitive copies it to the aura entry's origin field."""
        from engine.primitives import _persistent_aura
        caster = _make_actor("caster", position=(0, 0))
        state = _state_with([caster])
        state.current_attack = {
            "actor": caster, "target": caster,
            "action": _moonbeam_action(),
            "area_origin": (5, 5),
        }
        _persistent_aura(_moonbeam_action()["pipeline"][0]["params"],
                          state, None)
        self.assertEqual(len(state.persistent_auras), 1)
        aura = state.persistent_auras[0]
        self.assertEqual(aura["anchor"], "point")
        self.assertEqual(aura["origin"], (5, 5))

    def test_primitive_falls_back_to_caster_pos_when_no_origin(self) -> None:
        """If no area_origin in state, point-anchored falls back to
        caster.position (defensive — for direct primitive invocation
        in tests)."""
        from engine.primitives import _persistent_aura
        caster = _make_actor("caster", position=(3, 4))
        state = _state_with([caster])
        state.current_attack = {
            "actor": caster, "target": caster,
            "action": _moonbeam_action(),
        }
        _persistent_aura(_moonbeam_action()["pipeline"][0]["params"],
                          state, None)
        self.assertEqual(state.persistent_auras[0]["origin"], (3, 4))

    def test_caster_anchor_records_no_origin(self) -> None:
        """For anchor='caster' (default for SG), origin is None — the
        runner reads caster.position live at each trigger."""
        from engine.primitives import _persistent_aura
        caster = _make_actor("caster", position=(3, 4))
        state = _state_with([caster])
        # SG-shape action
        sg = {
            "id": "a_sg", "name": "Spirit Guardians",
            "type": "persistent_aura",
            "pipeline": [{
                "primitive": "persistent_aura",
                "params": {
                    "radius_ft": 15,
                    "anchor": "caster",
                    "trigger_event": "target_turn_start_in_area",
                    "ability": "wisdom", "dc": 15,
                    "on_fail": [], "on_success": [],
                    "affected": "enemies",
                },
            }],
        }
        state.current_attack = {
            "actor": caster, "target": caster, "action": sg,
        }
        _persistent_aura(sg["pipeline"][0]["params"], state, None)
        aura = state.persistent_auras[0]
        self.assertEqual(aura["anchor"], "caster")
        self.assertIsNone(aura["origin"])

    def test_point_aura_stays_at_origin_even_if_caster_moves(self) -> None:
        """Runner hook reads aura.origin (not caster.position) for
        point-anchored auras."""
        caster = _make_actor("caster", side="pc", position=(0, 0))
        enemy = _make_actor("enemy", side="enemy", position=(5, 5),
                              con_save=-5)
        state = _state_with([caster, enemy])
        # Point-anchored aura at (5, 5)
        state.persistent_auras.append({
            "caster_id": "caster", "action_id": "a_moonbeam",
            "named_effect": "moonbeam",
            "shape": "sphere", "radius_ft": 5,
            "size_ft": 0,
            "anchor": "point", "origin": (5, 5),
            "trigger_event": "target_turn_start_in_area",
            "ability": "constitution", "dc": 15,
            "on_fail": [{"primitive": "damage",
                          "params": {"dice": "2d10", "type": "radiant"}}],
            "on_success": [],
            "affected": "all_creatures",
            "applied_at_round": 1,
        })
        # Move caster way off — aura should still trigger on the
        # enemy who's at the (now-old) origin
        caster.position = (50, 50)
        runner = EncounterRunner.new(state.encounter, seed=1)
        import engine.primitives as primitives_module
        primitives_module.set_rng(runner.rng)
        hp_before = enemy.hp_current
        runner._resolve_persistent_aura_triggers(enemy, state)
        self.assertLess(enemy.hp_current, hp_before)


# ============================================================================
# Affected: all_creatures (friendly fire on)
# ============================================================================

class AllCreaturesAffectedTest(unittest.TestCase):

    def test_ally_in_radius_takes_damage(self) -> None:
        """affected='all_creatures' includes same-side actors."""
        caster = _make_actor("caster", side="pc", position=(0, 0))
        ally = _make_actor("ally", side="pc", position=(0, 1),
                            con_save=-5)
        state = _state_with([caster, ally])
        state.persistent_auras.append({
            "caster_id": "caster", "action_id": "a_moonbeam",
            "named_effect": "moonbeam",
            "shape": "sphere", "radius_ft": 5,
            "size_ft": 0,
            "anchor": "point", "origin": (0, 1),
            "trigger_event": "target_turn_start_in_area",
            "ability": "constitution", "dc": 15,
            "on_fail": [{"primitive": "damage",
                          "params": {"dice": "2d10", "type": "radiant"}}],
            "on_success": [{"primitive": "damage",
                              "params": {"dice": "2d10", "type": "radiant",
                                          "multiplier": 0.5}}],
            "affected": "all_creatures",   # friendly fire
            "applied_at_round": 1,
        })
        runner = EncounterRunner.new(state.encounter, seed=1)
        import engine.primitives as primitives_module
        primitives_module.set_rng(runner.rng)
        hp_before = ally.hp_current
        runner._resolve_persistent_aura_triggers(ally, state)
        self.assertLess(ally.hp_current, hp_before,
                          "Ally in all_creatures aura should take damage")


# ============================================================================
# Ability: 'none' — no-save path
# ============================================================================

class NoSavePathTest(unittest.TestCase):

    def test_no_save_invokes_on_fail_directly(self) -> None:
        """ability='none' skips forced_save and applies on_fail damage
        unconditionally."""
        caster = _make_actor("caster", side="pc", position=(0, 0))
        enemy = _make_actor("enemy", side="enemy", position=(0, 0),
                              con_save=99)   # would auto-succeed any save
        state = _state_with([caster, enemy])
        state.persistent_auras.append({
            "caster_id": "caster", "action_id": "a_cod",
            "named_effect": "cloud_of_daggers",
            "shape": "cube", "size_ft": 5,
            "radius_ft": 0,
            "anchor": "point", "origin": (0, 0),
            "trigger_event": "target_turn_start_in_area",
            "ability": None,    # no save
            "dc": 0,
            "on_fail": [{"primitive": "damage",
                          "params": {"dice": "4d4", "type": "slashing"}}],
            "on_success": [],
            "affected": "all_creatures",
            "applied_at_round": 1,
        })
        runner = EncounterRunner.new(state.encounter, seed=1)
        import engine.primitives as primitives_module
        primitives_module.set_rng(runner.rng)
        hp_before = enemy.hp_current
        runner._resolve_persistent_aura_triggers(enemy, state)
        # Damage applied despite high CON save
        self.assertLess(enemy.hp_current, hp_before)
        # No forced_save event fired
        saves = [e for e in state.event_log
                  if e.get("event") == "forced_save"]
        self.assertEqual(len(saves), 0)
        # The no-save-trigger event fired
        triggers = [e for e in state.event_log
                     if e.get("event") == "persistent_aura_no_save_trigger"]
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "enemy")


# ============================================================================
# Cube shape in runner
# ============================================================================

class CubeShapeRunnerTest(unittest.TestCase):

    def test_cube_shape_uses_actors_in_cube(self) -> None:
        """A 5-ft cube only hits actors on the origin square; an
        adjacent (5-ft-away) enemy is NOT in the cube."""
        caster = _make_actor("caster", side="pc", position=(0, 0))
        on_origin = _make_actor("on_origin", side="enemy",
                                  position=(5, 5), con_save=0)
        adjacent = _make_actor("adjacent", side="enemy",
                                 position=(6, 5), con_save=0)
        state = _state_with([caster, on_origin, adjacent])
        state.persistent_auras.append({
            "caster_id": "caster", "action_id": "a_cod",
            "named_effect": "cloud_of_daggers",
            "shape": "cube", "size_ft": 5,
            "radius_ft": 0,
            "anchor": "point", "origin": (5, 5),
            "trigger_event": "target_turn_start_in_area",
            "ability": None, "dc": 0,
            "on_fail": [{"primitive": "damage",
                          "params": {"dice": "4d4", "type": "slashing"}}],
            "on_success": [],
            "affected": "all_creatures",
            "applied_at_round": 1,
        })
        runner = EncounterRunner.new(state.encounter, seed=1)
        import engine.primitives as primitives_module
        primitives_module.set_rng(runner.rng)
        # on_origin (at the cube center): takes damage
        hp_before = on_origin.hp_current
        runner._resolve_persistent_aura_triggers(on_origin, state)
        self.assertLess(on_origin.hp_current, hp_before)
        # adjacent (5 ft away, outside the 5-ft cube): no damage
        hp_before_adj = adjacent.hp_current
        runner._resolve_persistent_aura_triggers(adjacent, state)
        self.assertEqual(adjacent.hp_current, hp_before_adj)


# ============================================================================
# eHP scoring for new aura shapes
# ============================================================================

class AuraScoringNewShapesTest(unittest.TestCase):

    def test_point_anchored_uses_origin_for_in_area_check(self) -> None:
        """Scoring with a point-anchored aura at a non-caster position
        should evaluate enemies near the origin, not the caster."""
        from engine.ai.ehp_scoring import offensive_ehp_persistent_aura
        caster = _make_actor("caster", side="pc", position=(0, 0))
        # Enemy at (10, 10) far from caster but in the Moonbeam at (10, 10)
        enemy = _make_actor("enemy", side="enemy", position=(10, 10),
                              con_save=-5, hp=100)
        state = _state_with([caster, enemy])
        # No origin → uses caster pos → no enemies in 5-ft radius → 0
        score_no_origin = offensive_ehp_persistent_aura(
            caster, _moonbeam_action(), state)
        self.assertEqual(score_no_origin, 0.0)
        # With origin at enemy's position → enemy is in aura → positive
        score_with_origin = offensive_ehp_persistent_aura(
            caster, _moonbeam_action(), state, origin=(10, 10))
        self.assertGreater(score_with_origin, 0.0)

    def test_no_save_scoring_uses_full_damage(self) -> None:
        """Cloud of Daggers (no save) should score full 4d4 per
        turn per in-cube enemy."""
        from engine.ai.ehp_scoring import (
            offensive_ehp_persistent_aura, EXPECTED_AURA_ROUNDS, dice_mean,
        )
        caster = _make_actor("caster", side="pc", position=(0, 0))
        enemy = _make_actor("enemy", side="enemy", position=(5, 5),
                              con_save=99, hp=100)
        state = _state_with([caster, enemy])
        score = offensive_ehp_persistent_aura(
            caster, _cloud_of_daggers_action(), state, origin=(5, 5))
        expected = dice_mean("4d4") * EXPECTED_AURA_ROUNDS
        self.assertAlmostEqual(score, expected, delta=0.01)


# ============================================================================
# End-to-end via runner
# ============================================================================

class MoonbeamEndToEndTest(unittest.TestCase):

    def test_moonbeam_damages_enemy_at_anchor(self) -> None:
        druid = _make_actor("druid", side="pc", position=(0, 0),
                              actions=[_moonbeam_action()],
                              initiative_modifier=30)
        druid.spell_slots = {2: 1}
        druid.spell_slots_max = {2: 1}
        druid.template["behavior_profile"] = {"presets": {"retreat": "ftd"}}
        enemy = _make_actor("enemy", side="enemy", position=(5, 0),
                              hp=80, con_save=-5,
                              initiative_modifier=0)
        enc = Encounter(id="t", actors=[druid, enemy])
        runner = EncounterRunner.new(enc, seed=1)
        import engine.primitives as primitives_module
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # Moonbeam was cast (registration event)
        casts = [e for e in state.event_log
                  if e.get("event") == "persistent_aura_registered"
                  and e.get("action") == "a_moonbeam"]
        self.assertGreater(len(casts), 0)
        # Aura is point-anchored
        self.assertEqual(casts[0]["anchor"], "point")
        # forced_save event fired on enemy at their turn-start
        saves = [e for e in state.event_log
                  if e.get("event") == "forced_save"
                  and e.get("target") == "enemy"]
        self.assertGreater(len(saves), 0)


class CloudOfDaggersEndToEndTest(unittest.TestCase):

    def test_cod_damages_enemy_with_no_save_event(self) -> None:
        wizard = _make_actor("wizard", side="pc", position=(0, 0),
                                actions=[_cloud_of_daggers_action()],
                                initiative_modifier=30)
        wizard.spell_slots = {2: 1}
        wizard.spell_slots_max = {2: 1}
        wizard.template["behavior_profile"] = {"presets": {"retreat": "ftd"}}
        enemy = _make_actor("enemy", side="enemy", position=(5, 0),
                              hp=80, con_save=99,    # would auto-save any
                              initiative_modifier=0)
        enc = Encounter(id="t", actors=[wizard, enemy])
        runner = EncounterRunner.new(enc, seed=1)
        import engine.primitives as primitives_module
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # CoD was cast
        casts = [e for e in state.event_log
                  if e.get("event") == "persistent_aura_registered"
                  and e.get("action") == "a_cloud_of_daggers"]
        self.assertGreater(len(casts), 0)
        # Cube shape recorded
        self.assertEqual(casts[0]["shape"], "cube")
        # NO forced_save event on enemy from this aura — but damage
        # was applied via the no-save path
        no_save_triggers = [e for e in state.event_log
                             if e.get("event")
                             == "persistent_aura_no_save_trigger"
                             and e.get("target") == "enemy"]
        self.assertGreater(len(no_save_triggers), 0,
                            "Cloud of Daggers should fire the no-save "
                            "trigger event on the enemy")


if __name__ == "__main__":
    unittest.main()
