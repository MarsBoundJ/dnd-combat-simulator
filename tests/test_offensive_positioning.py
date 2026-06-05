"""Offensive positioning term — `offensive_reach_ehp` + utility-maximizing
`best_position`. Previously best_position only MINIMIZED AoE exposure
(defense-only); it now maximizes delivered-offense − exposure, so a PC won't
retreat to a safe square that guts its own output, and will step to a square
whose cone catches more enemies.

Driven by the real Adult Red Dragon cone breath (a known-scoreable AoE) used
both as the enemy threat and, in the offense tests, as the actor's own cone.

Run via:
    python -m unittest tests.test_offensive_positioning
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.ai.positioning import (
    offensive_reach_ehp, position_utility, best_position,
    aoe_exposure_ehp, can_act_from, reachable_squares,
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


# A real, scoreable ranged attack (attack_roll + damage) so the offense term
# returns positive eHP — distance never enters the single-attack scorer.
_BOLT = {"id": "a_bolt", "type": "weapon_attack", "range_ft": 120,
         "pipeline": [
             {"primitive": "attack_roll",
              "params": {"kind": "ranged", "bonus": 7, "range_ft": 120}},
             {"primitive": "damage",
              "params": {"dice": "2d10", "modifier": 4, "type": "force"},
              "when": {"condition": "combat.attack_state == hit"}}]}
_BITE = {"id": "a_bite", "type": "weapon_attack", "reach_ft": 10}


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


# ============================================================================
# offensive_reach_ehp — the offense term itself
# ============================================================================

class OffensiveReachTest(unittest.TestCase):

    def test_single_target_offense_is_position_invariant(self):
        # A 120-ft bolt deals the same eHP from any in-range square (the
        # scorer reads hit prob + damage, not distance) — this invariance is
        # exactly why adding the term preserves the de-cluster behavior.
        dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        actor = _mk("pc", "pc", (5, 0), actions=[_BOLT])
        st = _state([dragon, actor])
        a = offensive_reach_ehp(actor, (5, 0), st)
        b = offensive_reach_ehp(actor, (5, 8), st)
        self.assertGreater(a, 0.0)
        self.assertAlmostEqual(a, b)

    def test_out_of_range_offense_is_zero(self):
        dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        actor = _mk("pc", "pc", (5, 0), actions=[_BITE])   # 10-ft reach
        st = _state([dragon, actor])
        self.assertEqual(offensive_reach_ehp(actor, (40, 40), st), 0.0)

    def test_no_enemies_zero_offense(self):
        actor = _mk("pc", "pc", (5, 0), actions=[_BOLT])
        ally = _mk("ally", "pc", (6, 0), actions=[_BOLT])
        st = _state([actor, ally])
        self.assertEqual(offensive_reach_ehp(actor, (5, 0), st), 0.0)

    def test_lone_enemy_aoe_is_skipped(self):
        # Perf guard: with a single enemy an AoE reduces to single-target
        # value, so the costly 8-direction scan is skipped. An actor whose
        # ONLY action is a cone therefore reports 0 offense vs a lone enemy.
        dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        coner = _mk("coner", "pc", (5, 0), actions=[_breath()])
        st = _state([dragon, coner])
        self.assertEqual(offensive_reach_ehp(coner, (5, 0), st), 0.0)

    def test_multi_enemy_cone_offense_is_apex_dependent(self):
        # With 2+ enemies the cone scan runs: an apex within reach of the
        # cluster delivers positive eHP; an apex far away catches nothing.
        g1 = _mk("g1", "enemy", (10, 0), hp=40)
        g2 = _mk("g2", "enemy", (10, 3), hp=40)
        coner = _mk("coner", "pc", (5, 1), actions=[_breath()], speed=60)
        st = _state([g1, g2, coner])
        near = offensive_reach_ehp(coner, (4, 1), st)
        far = offensive_reach_ehp(coner, (-40, -40), st)
        self.assertGreater(near, 0.0)
        self.assertEqual(far, 0.0)


# ============================================================================
# position_utility — offense minus exposure
# ============================================================================

class PositionUtilityTest(unittest.TestCase):

    def test_utility_is_offense_minus_exposure(self):
        dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        actor = _mk("pc", "pc", (5, 0), actions=[_BOLT])
        st = _state([dragon, actor])
        for sq in ((5, 0), (5, 6), (8, 2)):
            self.assertAlmostEqual(
                position_utility(actor, sq, st),
                offensive_reach_ehp(actor, sq, st)
                - aoe_exposure_ehp(actor, sq, st))


# ============================================================================
# best_position — now offense-aware
# ============================================================================

class BestPositionOffenseTest(unittest.TestCase):

    def test_decluster_preserved_for_single_target(self):
        # Regression guard: a pure single-target attacker still de-clusters to
        # strictly lower exposure (offense is position-invariant, so utility
        # max == exposure min).
        dragon = _mk("dragon", "enemy", (0, 0), actions=[_breath()], hp=256)
        actor = _mk("pc", "pc", (5, 0), actions=[_BOLT])
        ally = _mk("ally", "pc", (6, 0), actions=[_BOLT])
        st = _state([dragon, actor, ally])
        dest = best_position(actor, st)
        self.assertIsNotNone(dest)
        self.assertLess(aoe_exposure_ehp(actor, dest, st),
                        aoe_exposure_ehp(actor, (5, 0), st))

    def test_maximizes_offense_when_exposure_is_uniform(self):
        # The decisive isolation: park the AoE-threat enemy FAR away so its
        # breath can't reach any candidate square -> exposure ~0 everywhere ->
        # best_position is driven purely by the offense term. It must land on
        # a max-offense square (catch both goblins in the cone), proving the
        # term changes the decision (old min-exposure logic was offense-blind).
        far_dragon = _mk("dragon", "enemy", (100, 100),
                         actions=[_breath()], hp=256)        # gate + no reach
        g1 = _mk("g1", "enemy", (10, 0), hp=40)
        g2 = _mk("g2", "enemy", (10, 3), hp=40)
        coner = _mk("coner", "pc", (0, 12), actions=[_breath()], speed=60)
        ally = _mk("ally", "pc", (0, 14), actions=[_BOLT])   # party gate
        st = _state([far_dragon, g1, g2, coner, ally])

        # Exposure is ~0 at every reachable square (dragon too far to reach).
        cands = [c for c in reachable_squares(coner, st)
                 if can_act_from(coner, c, st)]
        self.assertTrue(cands)
        self.assertTrue(all(aoe_exposure_ehp(coner, c, st) < 1e-6
                            for c in cands))

        dest = best_position(coner, st)
        chosen = dest if dest is not None else tuple(coner.position)
        max_off = max(offensive_reach_ehp(coner, c, st) for c in cands)
        self.assertGreater(max_off, 0.0)
        # The chosen square achieves the maximum deliverable offense.
        self.assertAlmostEqual(
            offensive_reach_ehp(coner, chosen, st), max_off)


if __name__ == "__main__":
    unittest.main()
