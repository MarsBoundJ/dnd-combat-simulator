"""Wall of Force (Phase C) — the place_barrier primitive + f_wall_of_force
spell riding the positional-barrier system.

Proves: the spell loads + wires to place_barrier; the primitive drops a
move-blocking / sight-transparent wall between caster and target; the wall
breaks line of effect (attacks across it auto-miss); and the caster's
concentration owns it (end_concentration scrubs it, by flags).
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core.concentration import apply_concentration, end_concentration
from engine.core.events import EventBus
from engine.core.geometry import line_of_effect_blocked, segment_blocked
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import _attack_roll, _place_barrier, set_rng

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _actor(actor_id: str, side: str, position: tuple[int, int]) -> Actor:
    ab = {k: {"score": 12, "save": 1} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                 template={"id": f"t_{actor_id}", "abilities": ab,
                           "actions": [], "cr": {"proficiency_bonus": 3}},
                 side=side, hp_current=60, hp_max=60, ac=14,
                 speed={"walk": 30}, position=position, abilities=ab)


def _state(actors: list[Actor]) -> CombatState:
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.current_turn_idx = 0
    return st


def _cast_wall(caster, target, state, *, action_id="a_wall_of_force",
               params=None):
    state.current_attack = {"actor": caster, "target": target,
                            "action": {"id": action_id,
                                       "concentration": True},
                            "state": None}
    _place_barrier(params or {"length_ft": 30}, state, EventBus())


class SpellLoadsTest(unittest.TestCase):
    def test_feature_loads_and_wires_place_barrier(self):
        f = _registry().get("feature", "f_wall_of_force")
        at = f["action_template"]
        self.assertEqual(at["type"], "hard_control")
        self.assertTrue(at["concentration"])
        prims = [s["primitive"] for s in at["pipeline"]]
        self.assertIn("place_barrier", prims)

    def test_place_barrier_registered(self):
        self.assertIn("place_barrier", primitives_module._PRIMITIVE_HANDLERS)


class PlacementTest(unittest.TestCase):
    def test_wall_placed_between_caster_and_target(self):
        c = _actor("wiz", "pc", (0, 0))
        t = _actor("boss", "enemy", (8, 0))
        st = _state([c, t])
        _cast_wall(c, t, st)
        self.assertEqual(len(st.walls), 1)
        w = st.walls[0]
        # Half a square in front of the target, perpendicular (vertical).
        self.assertEqual(w.c[0], 7.5)
        self.assertEqual(w.c[2], 7.5)
        self.assertEqual(w.flags["effect"], "wall_of_force")
        self.assertEqual(w.flags["caster_id"], "wiz")
        self.assertEqual(w.flags["action_id"], "a_wall_of_force")

    def test_wall_blocks_move_but_not_sight(self):
        c = _actor("wiz", "pc", (0, 0))
        t = _actor("boss", "enemy", (8, 0))
        st = _state([c, t])
        _cast_wall(c, t, st)
        w = st.walls[0]
        self.assertTrue(w.blocks("move"))
        self.assertFalse(w.blocks("sight"))
        # Breaks line of effect (move channel) but is sight-transparent.
        self.assertTrue(line_of_effect_blocked(c, t, st.walls))
        self.assertFalse(segment_blocked(c, t, st.walls, "sight"))

    def test_stacked_caster_target_falls_back(self):
        c = _actor("wiz", "pc", (3, 3))
        t = _actor("boss", "enemy", (3, 3))
        st = _state([c, t])
        _cast_wall(c, t, st)   # must not crash
        self.assertEqual(len(st.walls), 1)


class LineOfEffectTest(unittest.TestCase):
    def setUp(self):
        set_rng(random.Random(1))

    def test_attack_across_wall_auto_misses(self):
        c = _actor("wiz", "pc", (0, 0))
        t = _actor("boss", "enemy", (8, 0))
        st = _state([c, t])
        _cast_wall(c, t, st)
        # An enemy ranged attack back across the wall at the wizard.
        st.current_attack = {"actor": t, "target": c,
                             "action": {"id": "a_claw"}, "state": None,
                             "had_advantage": False, "had_disadvantage": False}
        res = _attack_roll({"kind": "ranged", "bonus": 8, "range_ft": 80},
                           st, EventBus())
        self.assertEqual(res["state"], "miss")
        self.assertEqual(res["reason"], "no_line_of_effect")


class ConcentrationTeardownTest(unittest.TestCase):
    def test_end_concentration_scrubs_the_wall(self):
        c = _actor("wiz", "pc", (0, 0))
        t = _actor("boss", "enemy", (8, 0))
        st = _state([c, t])
        apply_concentration(c, {"id": "a_wall_of_force",
                                "concentration": True}, st)
        _cast_wall(c, t, st)
        self.assertEqual(len(st.walls), 1)
        end_concentration(c, st, reason="test")
        self.assertEqual(len(st.walls), 0)

    def test_unrelated_concentration_end_keeps_wall(self):
        # Wall stamped with a different action_id than the concentration
        # being dropped -> it survives.
        c = _actor("wiz", "pc", (0, 0))
        t = _actor("boss", "enemy", (8, 0))
        st = _state([c, t])
        apply_concentration(c, {"id": "a_other_spell",
                                "concentration": True}, st)
        _cast_wall(c, t, st, action_id="a_wall_of_force")
        end_concentration(c, st, reason="test")
        self.assertEqual(len(st.walls), 1)


if __name__ == "__main__":
    unittest.main()
