"""Phase 1c-ii — best_position wired into the runner's _move_to_engage.

A clustered ranged PC facing the dragon's breath repositions to a safer,
still-actionable square (reason='aoe_spacing'); a far melee PC who can't
yet act falls through to the greedy close-in.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.ai.positioning import aoe_exposure_ehp, can_act_from
from engine.core.geometry import distance_ft
from engine.core.runner import EncounterRunner
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


_BOLT = {"id": "a_bolt", "type": "weapon_attack", "range_ft": 120}
_GREATSWORD = {"id": "a_gs", "type": "weapon_attack", "reach_ft": 5}


def _mk(actor_id, side, pos, actions=None, hp=60, speed=30):
    ab = {k: {"score": 12, "save": 1} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                 template={"id": f"t_{actor_id}", "abilities": ab,
                           "actions": actions or [],
                           "cr": {"proficiency_bonus": 3}},
                 side=side, hp_current=hp, hp_max=hp, ac=14,
                 speed={"walk": speed}, position=pos, abilities=ab)


def _runner_and_state(actors):
    enc = Encounter(id="t", actors=actors)
    runner = EncounterRunner.new(enc, seed=1, content_registry=_registry())
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.current_turn_idx = 0
    st.content_registry = _registry()
    return runner, st


class DeclutterRunnerTest(unittest.TestCase):
    def test_clustered_ranged_pc_repositions(self):
        dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        pc = _mk("pc", "pc", (5, 0), actions=[_BOLT])
        ally = _mk("ally", "pc", (6, 0), actions=[_BOLT])
        runner, st = _runner_and_state([dragon, pc, ally])
        before = aoe_exposure_ehp(pc, (5, 0), st)
        runner._move_to_engage(pc, st)
        self.assertTrue(pc.moved_this_turn)
        self.assertNotEqual(pc.position, (5, 0))
        self.assertTrue(can_act_from(pc, pc.position, st))
        self.assertLess(aoe_exposure_ehp(pc, pc.position, st), before)
        self.assertTrue(any(e.get("event") == "moved"
                            and e.get("reason") == "aoe_spacing"
                            for e in st.event_log))

    def test_far_melee_pc_falls_through_to_greedy(self):
        # Greatsword reach 5; dragon 25 ft away -> can't act from current
        # square -> best_position returns None -> greedy close-in fires.
        dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        pc = _mk("pc", "pc", (5, 0), actions=[_GREATSWORD])
        ally = _mk("ally", "pc", (6, 0), actions=[_GREATSWORD])
        runner, st = _runner_and_state([dragon, pc, ally])
        before = distance_ft(pc.position, dragon.position)
        runner._move_to_engage(pc, st)
        self.assertTrue(pc.moved_this_turn)
        self.assertLess(distance_ft(pc.position, dragon.position), before)
        # The move was a greedy engage, not an aoe_spacing reposition.
        spacing = [e for e in st.event_log
                   if e.get("event") == "moved"
                   and e.get("reason") == "aoe_spacing"]
        self.assertEqual(spacing, [])


if __name__ == "__main__":
    unittest.main()
