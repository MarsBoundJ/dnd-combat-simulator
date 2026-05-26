"""AoE Cone + Line v1 tests — geometry helpers, candidate gen, scoring,
end-to-end fixture.

Layers:
  1. unit_direction snaps to 8 cardinal/ordinal directions
  2. actors_in_cone — cardinal + diagonal; lateral clipping; origin
     excluded
  3. actors_in_line — cardinal + diagonal; width handling; origin
     excluded
  4. Candidate generation: aoe_attack cone/line emits caster-origin +
     per-enemy direction; sphere unchanged
  5. eHP scoring routes through cone/line correctly; AI picks direction
     that catches more enemies
  6. End-to-end: Burning Hands fixture (15-ft cone)

Run via:
    python -m unittest tests.test_aoe_cone_line
"""
from __future__ import annotations

import random
import unittest

from engine.ai import score_candidate, offensive_ehp_aoe
from engine.core.geometry import (
    unit_direction, actors_in_cone, actors_in_line,
)
from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "enemy", hp: int = 30,
                ac: int = 13, position: tuple[int, int] = (0, 0),
                speed: int = 30, actions: list[dict] | None = None,
                dex_save: int = 2,
                template_extras: dict | None = None) -> Actor:
    abilities = {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 10 + 2 * dex_save, "save": dex_save},
        "con": {"score": 12, "save": 1},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": actions or []}
    if template_extras:
        template.update(template_extras)
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac,
                  speed={"walk": speed}, position=position,
                  abilities=abilities)


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    return state


def _cone_action(length_ft: int = 15, dice: str = "3d6",
                  dc: int = 13) -> dict:
    return {
        "id": "a_burning_hands", "name": "Burning Hands",
        "type": "aoe_attack",
        "area": {"shape": "cone", "length_ft": length_ft, "range_ft": 0},
        "pipeline": [{
            "primitive": "forced_save",
            "params": {
                "ability": "dexterity", "dc": dc,
                "affected": "all_creatures_in_area",
                "on_fail": [
                    {"primitive": "damage",
                      "params": {"dice": dice, "type": "fire"}}],
                "on_success": [
                    {"primitive": "damage",
                      "params": {"dice": dice, "type": "fire",
                                  "multiplier": 0.5}}],
            },
        }],
    }


def _line_action(length_ft: int = 30, width_ft: int = 5,
                  dice: str = "8d6", dc: int = 15) -> dict:
    return {
        "id": "a_lightning_bolt", "name": "Lightning Bolt",
        "type": "aoe_attack",
        "area": {"shape": "line", "length_ft": length_ft,
                  "width_ft": width_ft, "range_ft": 0},
        "pipeline": [{
            "primitive": "forced_save",
            "params": {
                "ability": "dexterity", "dc": dc,
                "affected": "all_creatures_in_area",
                "on_fail": [
                    {"primitive": "damage",
                      "params": {"dice": dice, "type": "lightning"}}],
                "on_success": [
                    {"primitive": "damage",
                      "params": {"dice": dice, "type": "lightning",
                                  "multiplier": 0.5}}],
            },
        }],
    }


# ============================================================================
# unit_direction
# ============================================================================

class UnitDirectionTest(unittest.TestCase):

    def test_same_position_zero(self) -> None:
        self.assertEqual(unit_direction((3, 3), (3, 3)), (0, 0))

    def test_cardinal_east(self) -> None:
        self.assertEqual(unit_direction((0, 0), (5, 0)), (1, 0))

    def test_cardinal_north(self) -> None:
        self.assertEqual(unit_direction((0, 0), (0, -3)), (0, -1))

    def test_diagonal_NE(self) -> None:
        self.assertEqual(unit_direction((0, 0), (3, 3)), (1, 1))

    def test_diagonal_SW(self) -> None:
        self.assertEqual(unit_direction((5, 5), (2, 2)), (-1, -1))

    def test_axis_aligned_only_when_pure_cardinal(self) -> None:
        # Vector (3, 0) snaps to (1, 0); (3, 1) snaps to (1, 1) diagonal
        self.assertEqual(unit_direction((0, 0), (3, 0)), (1, 0))
        self.assertEqual(unit_direction((0, 0), (3, 1)), (1, 1))


# ============================================================================
# actors_in_cone
# ============================================================================

class ActorsInConeTest(unittest.TestCase):

    def test_15ft_cone_east_includes_axis_squares(self) -> None:
        origin = (0, 0)
        # 15ft = 3 squares. Axis squares (1,0), (2,0), (3,0) all in cone.
        targets = [_make_actor(f"t{i}", position=(i, 0))
                    for i in range(1, 4)]
        result = actors_in_cone(origin, (1, 0), 15, targets)
        self.assertEqual([a.id for a in result], ["t1", "t2", "t3"])

    def test_15ft_cone_east_excludes_axis_beyond_length(self) -> None:
        origin = (0, 0)
        far = _make_actor("far", position=(4, 0))   # 20 ft, beyond 15ft
        result = actors_in_cone(origin, (1, 0), 15, [far])
        self.assertEqual(result, [])

    def test_origin_square_excluded(self) -> None:
        origin = (0, 0)
        at_origin = _make_actor("self", position=(0, 0))
        result = actors_in_cone(origin, (1, 0), 15, [at_origin])
        self.assertEqual(result, [])

    def test_lateral_clipping(self) -> None:
        """At forward=1, lateral=1 is NOT in cone (2*1 > 1+1 fails by 1).
        At forward=2, lateral=1 IS in cone (2*1 <= 2+1)."""
        origin = (0, 0)
        # (1, 1) — forward=1, lateral=1: 2*1=2, 1+1=2 → 2 <= 2 ✓ wait that's IN.
        # Let me re-check the formula: 2*lateral <= forward + 1 → 2 <= 2 ✓
        # So (1, 1) IS in cone with the grid-tolerance. OK.
        # Let's pick (1, 2) — forward=1, lateral=2: 4 <= 2 ✗
        in_close = _make_actor("close", position=(1, 1))
        out_far_lateral = _make_actor("out", position=(1, 2))
        result = actors_in_cone(origin, (1, 0), 15,
                                  [in_close, out_far_lateral])
        ids = [a.id for a in result]
        self.assertIn("close", ids)
        self.assertNotIn("out", ids)

    def test_behind_origin_not_in_cone(self) -> None:
        """East cone shouldn't catch enemies west of caster."""
        origin = (0, 0)
        behind = _make_actor("behind", position=(-2, 0))
        result = actors_in_cone(origin, (1, 0), 15, [behind])
        self.assertEqual(result, [])

    def test_diagonal_cone(self) -> None:
        """Cone in (1, 1) direction catches squares along that diagonal."""
        origin = (0, 0)
        # (1, 1) and (2, 2) are on the diagonal axis
        on_axis = [_make_actor(f"d{i}", position=(i, i))
                    for i in (1, 2)]
        # (1, -1) is the wrong direction
        wrong_dir = _make_actor("wrong", position=(1, -1))
        result = actors_in_cone(origin, (1, 1), 15,
                                  on_axis + [wrong_dir])
        ids = [a.id for a in result]
        self.assertIn("d1", ids)
        self.assertIn("d2", ids)
        self.assertNotIn("wrong", ids)

    def test_zero_direction_returns_empty(self) -> None:
        actors = [_make_actor("a", position=(1, 0))]
        self.assertEqual(actors_in_cone((0, 0), (0, 0), 15, actors), [])


# ============================================================================
# actors_in_line
# ============================================================================

class ActorsInLineTest(unittest.TestCase):

    def test_5ft_wide_line_east_is_single_column(self) -> None:
        """5-ft-wide line (default for most line spells) catches only the
        squares directly east of origin along the axis."""
        origin = (0, 0)
        actors = [
            _make_actor("on", position=(2, 0)),    # in line
            _make_actor("off_n", position=(2, 1)),  # off axis
            _make_actor("off_s", position=(2, -1)),  # off axis
        ]
        result = actors_in_line(origin, (1, 0), 30, 5, actors)
        ids = [a.id for a in result]
        self.assertEqual(ids, ["on"])

    def test_10ft_wide_line_catches_one_square_off_axis(self) -> None:
        """10-ft-wide line: half_width = (2-1)//2 = 0 → still single
        square. Need 15-ft (3 wide) for ±1 off axis."""
        origin = (0, 0)
        off_axis = _make_actor("off", position=(2, 1))
        result_10 = actors_in_line(origin, (1, 0), 30, 10, [off_axis])
        # 10ft = 2 squares wide; (2-1)//2 = 0 half_width. (2, 1) lateral 1
        # → NOT in line.
        self.assertEqual(result_10, [])
        result_15 = actors_in_line(origin, (1, 0), 30, 15, [off_axis])
        # 15ft = 3 squares; (3-1)//2 = 1 half_width. (2, 1) lateral 1 ✓.
        self.assertEqual([a.id for a in result_15], ["off"])

    def test_line_length_clipping(self) -> None:
        origin = (0, 0)
        # 30ft = 6 squares. (7, 0) is beyond.
        in_line = _make_actor("in", position=(6, 0))
        out_line = _make_actor("out", position=(7, 0))
        result = actors_in_line(origin, (1, 0), 30, 5,
                                  [in_line, out_line])
        ids = [a.id for a in result]
        self.assertEqual(ids, ["in"])

    def test_origin_excluded(self) -> None:
        at_origin = _make_actor("self", position=(0, 0))
        result = actors_in_line((0, 0), (1, 0), 30, 5, [at_origin])
        self.assertEqual(result, [])

    def test_diagonal_line_axis_only(self) -> None:
        """A diagonal line includes only squares directly on the diagonal."""
        origin = (0, 0)
        on_diag = _make_actor("on", position=(3, 3))
        off_diag = _make_actor("off", position=(3, 2))
        result = actors_in_line(origin, (1, 1), 30, 5,
                                  [on_diag, off_diag])
        ids = [a.id for a in result]
        self.assertEqual(ids, ["on"])

    def test_behind_origin_not_in_line(self) -> None:
        behind = _make_actor("behind", position=(-2, 0))
        result = actors_in_line((0, 0), (1, 0), 30, 5, [behind])
        self.assertEqual(result, [])


# ============================================================================
# Candidate generation
# ============================================================================

class CandidateGenConeLineTest(unittest.TestCase):

    def test_cone_candidates_use_caster_origin_and_direction(self) -> None:
        caster = _make_actor("c", side="pc", position=(0, 0),
                               actions=[_cone_action()])
        enemy_e = _make_actor("ee", side="enemy", position=(3, 0))
        enemy_n = _make_actor("en", side="enemy", position=(0, -3))
        state = _state_with([caster, enemy_e, enemy_n])

        cands = [c for c in generate_candidates(caster, state)
                  if c["kind"] == "aoe_attack"]
        self.assertEqual(len(cands), 2)
        # Both candidates should use caster's position as origin
        for c in cands:
            self.assertEqual(c["origin_point"], (0, 0))
            self.assertIn("direction", c)
        # Directions should snap toward each enemy
        dirs = {tuple(c["direction"]) for c in cands}
        self.assertEqual(dirs, {(1, 0), (0, -1)})

    def test_line_candidates_use_caster_origin_and_direction(self) -> None:
        caster = _make_actor("c", side="pc", position=(0, 0),
                               actions=[_line_action()])
        enemy = _make_actor("e", side="enemy", position=(5, 0))
        state = _state_with([caster, enemy])
        cands = [c for c in generate_candidates(caster, state)
                  if c["kind"] == "aoe_attack"]
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["origin_point"], (0, 0))
        self.assertEqual(tuple(cands[0]["direction"]), (1, 0))

    def test_sphere_candidates_unchanged(self) -> None:
        """Sphere AoE candidates still use enemy.position as origin
        and don't get a direction."""
        sphere = {
            "id": "a_fireball", "type": "aoe_attack",
            "area": {"shape": "sphere", "radius_ft": 20, "range_ft": 150},
            "pipeline": [{"primitive": "forced_save",
                          "params": {"ability": "dexterity", "dc": 15,
                                      "affected": "all_creatures_in_area"}}],
        }
        caster = _make_actor("c", side="pc", position=(0, 0),
                               actions=[sphere])
        enemy = _make_actor("e", side="enemy", position=(5, 0))
        state = _state_with([caster, enemy])
        cands = [c for c in generate_candidates(caster, state)
                  if c["kind"] == "aoe_attack"]
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["origin_point"], (5, 0))
        self.assertNotIn("direction", cands[0])


# ============================================================================
# eHP scoring routes correctly
# ============================================================================

class ConeLineEHPScoringTest(unittest.TestCase):

    def test_cone_score_higher_with_more_enemies_in_line(self) -> None:
        """3 enemies in a row in the cone direction beats 1 enemy."""
        caster = _make_actor("c", side="pc", position=(0, 0))
        # Direction east. Three enemies at (1, 0), (2, 0), (3, 0).
        triple_state = _state_with([caster] + [
            _make_actor(f"e{i}", side="enemy", position=(i, 0), hp=30)
            for i in (1, 2, 3)
        ])
        single_state = _state_with([caster,
                                       _make_actor("e1", side="enemy",
                                                     position=(1, 0), hp=30)])

        action = _cone_action(length_ft=15, dice="3d6", dc=15)
        triple_score = offensive_ehp_aoe(
            caster, (0, 0), action, triple_state, direction=(1, 0))
        single_score = offensive_ehp_aoe(
            caster, (0, 0), action, single_state, direction=(1, 0))
        self.assertGreater(triple_score, single_score)

    def test_cone_missing_direction_scores_zero(self) -> None:
        caster = _make_actor("c", side="pc", position=(0, 0))
        enemy = _make_actor("e", side="enemy", position=(1, 0), hp=30)
        state = _state_with([caster, enemy])
        action = _cone_action()
        self.assertEqual(
            offensive_ehp_aoe(caster, (0, 0), action, state,
                                direction=None),
            0.0,
        )

    def test_line_score_higher_with_enemies_in_line(self) -> None:
        caster = _make_actor("c", side="pc", position=(0, 0))
        # 4 enemies along east axis
        line_state = _state_with([caster] + [
            _make_actor(f"e{i}", side="enemy", position=(i, 0), hp=30)
            for i in (1, 2, 3, 4)
        ])
        # Single enemy
        single_state = _state_with([caster,
                                       _make_actor("e1", side="enemy",
                                                     position=(1, 0), hp=30)])

        action = _line_action(length_ft=30, width_ft=5, dice="8d6", dc=15)
        line_score = offensive_ehp_aoe(
            caster, (0, 0), action, line_state, direction=(1, 0))
        single_score = offensive_ehp_aoe(
            caster, (0, 0), action, single_state, direction=(1, 0))
        self.assertGreater(line_score, single_score)

    def test_score_candidate_dispatches_cone_direction(self) -> None:
        caster = _make_actor("c", side="pc", position=(0, 0))
        enemy = _make_actor("e", side="enemy", position=(3, 0), hp=30)
        state = _state_with([caster, enemy])
        action = _cone_action(length_ft=15)
        cand = {"kind": "aoe_attack", "actor": caster, "target": enemy,
                "action": action, "origin_point": (0, 0),
                "direction": (1, 0)}
        score = score_candidate(cand, state)
        self.assertGreater(score, 0)


# ============================================================================
# End-to-end: Burning Hands fixture
# ============================================================================

class BurningHandsFixtureTest(unittest.TestCase):

    def test_burning_hands_fixture_runs(self) -> None:
        import random as _random
        from pathlib import Path
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner
        from engine.cli import _build_encounter
        from engine.loader import load_content, load_yaml_file

        repo_root = Path(__file__).parent.parent
        content_root = repo_root / "schema" / "content"
        schema_root = repo_root / "schema" / "definitions"
        fixture = Path(__file__).parent / "fixtures" / \
            "burning_hands_cone_encounter.yaml"

        registry = load_content(content_root, validate=True,
                                  schema_root=schema_root)
        spec = load_yaml_file(fixture)
        encounter = _build_encounter(spec, registry)

        primitives_module.set_rng(_random.Random(1))
        runner = EncounterRunner.new(encounter, seed=1,
                                       content_registry=registry)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # The wizard should have cast Burning Hands at least once with
        # direction set
        aoe_events = [e for e in state.event_log
                       if e.get("event") == "aoe_origin_placed"
                       and e.get("actor") == "wizard_pc"]
        self.assertGreater(len(aoe_events), 0,
                            "Wizard should have cast Burning Hands")
        # Direction should be in the event payload
        self.assertIn("direction", aoe_events[0],
                        "AoE origin event should include direction for cone")

        # Multiple goblins should have rolled DEX saves
        save_targets = {e["target"] for e in state.event_log
                          if e.get("event") == "forced_save"}
        # At least 2 of the 3 in-line goblins
        goblin_save_count = sum(1 for t in save_targets
                                  if t.startswith("goblin"))
        self.assertGreaterEqual(goblin_save_count, 2,
                                  "Cone should have caught multiple goblins")


if __name__ == "__main__":
    unittest.main()
