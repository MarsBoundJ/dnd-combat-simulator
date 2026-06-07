"""Monster-side breath re-aiming / chase (the offensive counterpart to the PC
de-cluster). After PR #217 gave ranged PCs the ability to step out of a breath
cone, a dial-1 dragon that never relocates made the smart-PC-vs-naive-monster
matchup lopsided. `best_aoe_attack_position` (positioning) + the runner hook
`_maybe_reposition_for_aoe` let an ABOVE-baseline enemy move its breath apex to
catch more PCs; the dial-1 'WoTC floor' boss stays deliberately naive.

Run via:
    python -m unittest tests.test_monster_breath_chase
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

from engine import primitives as pm
from engine.ai.positioning import best_aoe_attack_position, max_aoe_coverage
from engine.core.optimization_dial import set_dial
from engine.core.runner import EncounterRunner, AOE_CHASE_MIN_DIAL
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
_BITE = {"id": "a_bite", "type": "weapon_attack", "reach_ft": 10}


def _mk(actor_id, side, pos, actions=None, hp=60, speed=40):
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
    st.content_registry = _registry()
    return st


# Two PCs clustered 75 ft east of a dragon at the origin — beyond the 60-ft
# cone from the origin, so the breath catches NOBODY from where it stands, but
# a short step east brings both into a single cone (the "chase").
def _dragon_and_two_distant_pcs():
    dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
    p1 = _mk("p1", "pc", (15, 0), actions=[_BOLT])
    p2 = _mk("p2", "pc", (15, 1), actions=[_BOLT])
    return dragon, [p1, p2]


class BestAoEPositionTest(unittest.TestCase):
    def test_relocates_to_catch_more_enemies(self):
        dragon, pcs = _dragon_and_two_distant_pcs()
        st = _state([dragon, *pcs])
        # No coverage from the current square...
        self.assertIsNone(max_aoe_coverage(_breath(), dragon, st, apex=(0, 0)))
        dest = best_aoe_attack_position(dragon, st)
        self.assertIsNotNone(dest)
        self.assertNotEqual(dest, tuple(dragon.position))
        # ...positive coverage from the chosen square.
        cov = max_aoe_coverage(_breath(), dragon, st, apex=dest)
        self.assertIsNotNone(cov)
        self.assertGreater(cov["ehp"], 0)

    def test_breath_unavailable_no_move(self):
        dragon, pcs = _dragon_and_two_distant_pcs()
        st = _state([dragon, *pcs])
        dragon.recharge_spent.add("a_fire_breath")   # spent → unavailable
        self.assertIsNone(best_aoe_attack_position(dragon, st))

    def test_single_enemy_no_move(self):
        dragon, pcs = _dragon_and_two_distant_pcs()
        st = _state([dragon, pcs[0]])                 # only one PC
        self.assertIsNone(best_aoe_attack_position(dragon, st))

    def test_no_aoe_action_no_move(self):
        biter = _mk("biter", "enemy", (0, 0), actions=[_BITE], hp=200)
        p1 = _mk("p1", "pc", (15, 0), actions=[_BOLT])
        p2 = _mk("p2", "pc", (15, 1), actions=[_BOLT])
        st = _state([biter, p1, p2])
        self.assertIsNone(best_aoe_attack_position(biter, st))


class RunnerHookTest(unittest.TestCase):
    def _runner_and_state(self, actors, *, enemy_dial):
        enc = Encounter(id="t", actors=actors)
        pm.set_rng(random.Random(1))
        runner = EncounterRunner.new(enc, seed=1, content_registry=_registry())
        pm.set_rng(runner.rng)
        st = CombatState(encounter=enc)
        st.turn_order = [a.id for a in actors]
        st.content_registry = _registry()
        set_dial(st, "enemy", enemy_dial)
        return runner, st

    def test_chases_at_high_dial(self):
        dragon, pcs = _dragon_and_two_distant_pcs()
        runner, st = self._runner_and_state([dragon, *pcs],
                                            enemy_dial=AOE_CHASE_MIN_DIAL)
        moved = runner._maybe_reposition_for_aoe(dragon, st)
        self.assertTrue(moved)
        self.assertTrue(dragon.moved_this_turn)
        self.assertTrue(any(e.get("event") == "moved"
                            and e.get("reason") == "aoe_reposition"
                            and e.get("actor") == "dragon"
                            for e in st.event_log))
        # The new square actually lets the breath land.
        cov = max_aoe_coverage(_breath(), dragon, st, apex=dragon.position)
        self.assertIsNotNone(cov)

    def test_naive_at_low_dial(self):
        # Dial below the chase threshold → the WoTC-floor boss stays put even
        # though a better breath square exists.
        dragon, pcs = _dragon_and_two_distant_pcs()
        runner, st = self._runner_and_state([dragon, *pcs],
                                            enemy_dial=AOE_CHASE_MIN_DIAL - 1)
        # A better breath square DOES exist (the optimizer isn't dial-gated)...
        self.assertIsNotNone(best_aoe_attack_position(dragon, st))
        # ...but the runner hook's dial gate suppresses the chase.
        self.assertFalse(runner._maybe_reposition_for_aoe(dragon, st))
        self.assertFalse(dragon.moved_this_turn)

    def test_pc_side_excluded(self):
        # The hook is the MONSTER mirror — a PC runs _maybe_aoe_decluster.
        pc = _mk("pc", "pc", (0, 0), actions=[_breath()], hp=60)
        e1 = _mk("e1", "enemy", (15, 0), actions=[_BOLT])
        e2 = _mk("e2", "enemy", (15, 1), actions=[_BOLT])
        runner, st = self._runner_and_state([pc, e1, e2], enemy_dial=5)
        self.assertFalse(runner._maybe_reposition_for_aoe(pc, st))

    def test_already_moved_skips(self):
        dragon, pcs = _dragon_and_two_distant_pcs()
        runner, st = self._runner_and_state([dragon, *pcs], enemy_dial=5)
        dragon.moved_this_turn = True
        self.assertFalse(runner._maybe_reposition_for_aoe(dragon, st))


class FlierReachTest(unittest.TestCase):
    """A flier relocates its breath apex using FLY speed, not walk — so an
    Adult Dragon (walk 40, fly 80) can flank a formation a ground-bound step
    couldn't reach."""

    def test_reachable_squares_uses_fly(self):
        from engine.ai.positioning import reachable_squares
        from engine.core.geometry import distance_ft
        flier = _mk("flier", "enemy", (0, 0), actions=[_BITE], hp=200)
        flier.speed = {"walk": 40, "fly": 80}
        walker = _mk("walker", "enemy", (0, 0), actions=[_BITE], hp=200)
        walker.speed = {"walk": 40}
        st = _state([flier])
        st2 = _state([walker])
        fly_reach = max(distance_ft((0, 0), s)
                        for s in reachable_squares(flier, st))
        walk_reach = max(distance_ft((0, 0), s)
                         for s in reachable_squares(walker, st2))
        self.assertEqual(walk_reach, 40)
        self.assertEqual(fly_reach, 80)

    def test_fly_reaches_covering_apex_walk_cannot(self):
        from engine.core.geometry import distance_ft
        # Two PCs 120 ft east — beyond any 60-ft cone thrown from within walk
        # range (40 ft), but a fly-80 move lets the dragon close to a covering
        # apex.
        flier = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        flier.speed = {"walk": 40, "fly": 80}
        p1 = _mk("p1", "pc", (24, 0), actions=[_BOLT])
        p2 = _mk("p2", "pc", (24, 2), actions=[_BOLT])
        st = _state([flier, p1, p2])
        dest = best_aoe_attack_position(flier, st)
        self.assertIsNotNone(dest)
        self.assertGreater(distance_ft((0, 0), dest), 40)   # only fly reaches it
        cov = max_aoe_coverage(_breath(), flier, st, apex=dest)
        self.assertIsNotNone(cov)
        self.assertGreater(cov["ehp"], 0)

        # A walk-only dragon in the same spot can't reach any covering apex.
        walker = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        walker.speed = {"walk": 40}
        st2 = _state([walker,
                      _mk("p1", "pc", (24, 0), actions=[_BOLT]),
                      _mk("p2", "pc", (24, 2), actions=[_BOLT])])
        self.assertIsNone(best_aoe_attack_position(walker, st2))


if __name__ == "__main__":
    unittest.main()
