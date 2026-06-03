"""Barrier wiring (Phase B) — walls actually affect the engine.

Proves the four gated integration points and that an empty wall list
(the universal default) leaves every code path behaving exactly as before:

  1. Movement — move_toward / push_creature stop AT a move-blocking wall.
  2. Single-target line-of-effect — _attack_roll auto-misses across a wall.
  3. AoE occlusion — _resolve_save_targets spares creatures behind a wall.
  4. Candidate generation — single-target candidates drop wall-blocked enemies.

A Wall of Force analogue (move-blocking, sight-transparent) is used
throughout; the gating tests re-run each scenario with walls=[] and
assert the pre-barrier outcome.
"""
from __future__ import annotations

import random
import unittest

from engine.core.events import EventBus
from engine.core.geometry import Wall, move_toward, push_creature
from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import _attack_roll, _resolve_save_targets, set_rng


def _make_actor(actor_id: str, side: str = "enemy", hp: int = 30, ac: int = 15,
                position: tuple[int, int] = (0, 0), speed: int = 30,
                actions: list[dict] | None = None) -> Actor:
    abilities = {
        "str": {"score": 10, "save": 0}, "dex": {"score": 14, "save": 2},
        "con": {"score": 12, "save": 1}, "int": {"score": 10, "save": 0},
        "wis": {"score": 12, "save": 1}, "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": actions or []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                 hp_current=hp, hp_max=hp, ac=ac, speed={"walk": speed},
                 position=position, abilities=abilities)


def _state(actors: list[Actor], walls: list[Wall] | None = None) -> CombatState:
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.current_turn_idx = 0
    if walls:
        st.walls = walls
    return st


def _ranged_attack() -> dict:
    return {"id": "a_bow", "name": "Bow", "type": "weapon_attack",
            "pipeline": [{"primitive": "attack_roll",
                          "params": {"kind": "ranged", "bonus": 5,
                                     "range_ft": 80}}]}


# A move-blocking, sight-transparent wall (Wall of Force) on the boundary
# x = X, spanning a tall vertical span.
def _wof(x: float, y0: float = -5.0, y1: float = 5.0) -> Wall:
    return Wall(c=(x, y0, x, y1))   # default move=blocking, sight=none


class MovementBlockedTest(unittest.TestCase):
    def test_move_toward_stops_at_wall(self):
        mover = _make_actor("m", position=(0, 0))
        target = _make_actor("t", position=(10, 0))
        moved = move_toward(mover, target, max_ft=30, blockers=[_wof(2.5)])
        # Greedy steps to (1,0),(2,0); the (2,0)->(3,0) step crosses x=2.5.
        self.assertEqual(mover.position, (2, 0))
        self.assertEqual(moved, 10)

    def test_move_toward_no_walls_passes_through(self):
        mover = _make_actor("m", position=(0, 0))
        target = _make_actor("t", position=(10, 0))
        moved = move_toward(mover, target, max_ft=30, blockers=[])
        self.assertEqual(mover.position, (6, 0))
        self.assertEqual(moved, 30)

    def test_push_creature_stops_at_wall(self):
        pusher = _make_actor("p", position=(0, 0))
        target = _make_actor("t", position=(1, 0))
        pushed = push_creature(pusher, target, 30, blockers=[_wof(2.5)])
        # Pushed east; (1,0)->(2,0) ok, (2,0)->(3,0) crosses x=2.5.
        self.assertEqual(target.position, (2, 0))
        self.assertEqual(pushed, 5)

    def test_push_creature_no_walls_full_distance(self):
        pusher = _make_actor("p", position=(0, 0))
        target = _make_actor("t", position=(1, 0))
        pushed = push_creature(pusher, target, 30)
        self.assertEqual(target.position, (7, 0))   # 6 squares east
        self.assertEqual(pushed, 30)


class SingleTargetLineOfEffectTest(unittest.TestCase):
    def setUp(self):
        set_rng(random.Random(1))

    def _roll(self, walls):
        attacker = _make_actor("a", side="pc", position=(0, 0))
        target = _make_actor("d", side="enemy", position=(10, 0))
        st = _state([attacker, target], walls=walls)
        st.current_attack = {"actor": attacker, "target": target,
                             "action": {"id": "a_bow"}, "state": None,
                             "had_advantage": False, "had_disadvantage": False}
        return _attack_roll({"kind": "ranged", "bonus": 5, "range_ft": 80},
                            st, EventBus())

    def test_attack_across_wall_auto_misses(self):
        res = self._roll([_wof(5.5)])
        self.assertEqual(res["state"], "miss")
        self.assertEqual(res["reason"], "no_line_of_effect")

    def test_attack_no_wall_is_not_loe_miss(self):
        # Empty walls -> the LoE guard is skipped; the attack rolls
        # normally (hit or miss, but never the no_line_of_effect reason).
        res = self._roll([])
        self.assertNotEqual(res.get("reason"), "no_line_of_effect")


class AoEOcclusionTest(unittest.TestCase):
    def _resolve(self, walls):
        caster = _make_actor("caster", side="pc", position=(50, 50))
        near = _make_actor("near", side="enemy", position=(5, 0))    # on origin
        far = _make_actor("far", side="enemy", position=(9, 0))      # 20 ft
        st = _state([caster, near, far], walls=walls)
        st.current_attack = {
            "actor": caster,
            "action": {"id": "sp_fireball",
                       "area": {"shape": "sphere", "radius_ft": 20}},
            "area_origin": (5, 0), "area_direction": None,
        }
        ids = {a.id for a in
               _resolve_save_targets({"affected": "all_creatures_in_area"}, st)}
        return ids

    def test_wall_spares_creature_behind_it(self):
        # Wall on x=7.5 between origin (5,0) and far (9,0).
        ids = self._resolve([_wof(7.5)])
        self.assertIn("near", ids)
        self.assertNotIn("far", ids)

    def test_no_wall_hits_both(self):
        ids = self._resolve([])
        self.assertIn("near", ids)
        self.assertIn("far", ids)


class CandidateGenerationFilterTest(unittest.TestCase):
    def _target_ids(self, walls):
        actor = _make_actor("pc", side="pc", position=(0, 0),
                            actions=[_ranged_attack()])
        e_near = _make_actor("e_near", side="enemy", position=(3, 0))
        e_far = _make_actor("e_far", side="enemy", position=(10, 0))
        st = _state([actor, e_near, e_far], walls=walls)
        cands = generate_candidates(actor, st)
        return {c["target"].id for c in cands
                if c.get("kind") == "weapon_attack" and c.get("target")}

    def test_wall_blocked_enemy_dropped(self):
        # Wall on x=5.5 between actor (0,0) and e_far (10,0).
        ids = self._target_ids([_wof(5.5)])
        self.assertIn("e_near", ids)
        self.assertNotIn("e_far", ids)

    def test_no_wall_both_targetable(self):
        ids = self._target_ids([])
        self.assertIn("e_near", ids)
        self.assertIn("e_far", ids)


if __name__ == "__main__":
    unittest.main()
