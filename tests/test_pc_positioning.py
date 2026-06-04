"""PC positioning utility (Phase 1c-i) — AoE-exposure + enablement +
best_position. Pure functions (not yet wired into the runner). Driven by
the real Adult Red Dragon cone breath.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.ai.positioning import (
    aoe_exposure_ehp,
    best_position,
    can_act_from,
    largest_enemy_aoe_radius,
)
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _breath():
    mon = _registry().get("monster", "m_adult_red_dragon")
    return next(a for a in mon["actions"]
                if (a.get("area") or {}).get("shape") == "cone")


_BITE = {"id": "a_bite", "type": "weapon_attack", "reach_ft": 10}
_BOLT = {"id": "a_bolt", "type": "weapon_attack", "range_ft": 120}


def _mk(actor_id, side, pos, actions=None, hp=60, speed=30):
    ab = {k: {"score": 12, "save": 1} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                 template={"id": f"t_{actor_id}", "abilities": ab,
                           "actions": actions or [],
                           "cr": {"proficiency_bonus": 3}},
                 side=side, hp_current=hp, hp_max=hp, ac=14,
                 speed={"walk": speed}, position=pos, abilities=ab)


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    return st


class ExposureTest(unittest.TestCase):
    def test_actor_in_cone_has_positive_exposure(self):
        dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        actor = _mk("pc", "pc", (5, 0), actions=[_BOLT])
        st = _state([dragon, actor])
        self.assertGreater(aoe_exposure_ehp(actor, (5, 0), st), 0)

    def test_stepping_out_of_cone_lowers_exposure(self):
        # Dragon east-facing best cone catches the eastern line; a square
        # well off that axis should expose the actor far less.
        dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        actor = _mk("pc", "pc", (5, 0), actions=[_BOLT])
        ally = _mk("ally", "pc", (6, 0), actions=[_BOLT])
        st = _state([dragon, actor, ally])
        in_line = aoe_exposure_ehp(actor, (5, 0), st)
        off_axis = aoe_exposure_ehp(actor, (5, 8), st)
        self.assertGreater(in_line, off_axis)


class EnablementTest(unittest.TestCase):
    def test_in_range_with_los_can_act(self):
        dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        actor = _mk("pc", "pc", (5, 0), actions=[_BOLT])
        st = _state([dragon, actor])
        self.assertTrue(can_act_from(actor, (5, 8), st))   # 120-ft bolt

    def test_out_of_range_cannot_act(self):
        dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        actor = _mk("pc", "pc", (5, 0), actions=[_BITE])    # 10-ft reach only
        st = _state([dragon, actor])
        self.assertFalse(can_act_from(actor, (30, 30), st))  # far from dragon


class BestPositionTest(unittest.TestCase):
    def test_declusters_out_of_the_breath(self):
        dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        actor = _mk("pc", "pc", (5, 0), actions=[_BOLT])
        ally = _mk("ally", "pc", (6, 0), actions=[_BOLT])
        st = _state([dragon, actor, ally])
        dest = best_position(actor, st)
        self.assertIsNotNone(dest)
        # Strictly lower exposure than staying put, and still able to act.
        self.assertLess(aoe_exposure_ehp(actor, dest, st),
                        aoe_exposure_ehp(actor, (5, 0), st))
        self.assertTrue(can_act_from(actor, dest, st))

    def test_no_aoe_enemy_no_reposition(self):
        # Enemy has only a melee bite -> no AoE threat -> gate returns None.
        melee = _mk("melee", "enemy", (0, 0), actions=[_BITE], hp=100)
        actor = _mk("pc", "pc", (5, 0), actions=[_BOLT])
        ally = _mk("ally", "pc", (6, 0), actions=[_BOLT])
        st = _state([melee, actor, ally])
        self.assertEqual(largest_enemy_aoe_radius(actor, st), 0)
        self.assertIsNone(best_position(actor, st))

    def test_solo_pc_no_reposition(self):
        # No allies -> party-coupled gate returns None (v1).
        dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        actor = _mk("pc", "pc", (5, 0), actions=[_BOLT])
        st = _state([dragon, actor])
        self.assertIsNone(best_position(actor, st))


if __name__ == "__main__":
    unittest.main()
