"""Optimization dial (1-5) + focus-fire (its first consumer).

The dial is a per-side play-skill knob: a probability that, when a tactic is
warranted, the side applies it (Phil's mapping). Focus-fire LOCKS single-target
offense onto the lowest-HP enemy when it fires (AoE still competes). Default
dial 1 → never → unchanged behavior.

Run via:
    python -m unittest tests.test_optimization_dial
"""
from __future__ import annotations

import random
import unittest

from engine.core import optimization_dial as od
from engine.core.state import Actor, Encounter, CombatState


def _actor(actor_id, side, hp=40, actions=None):
    ab = {k: {"score": 12, "save": 1} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                 template={"id": f"t_{actor_id}", "abilities": ab,
                           "cr": {"proficiency_bonus": 2},
                           "actions": actions or []},
                 side=side, hp_current=hp, hp_max=hp, ac=12,
                 position=(0, 0), abilities=ab)


def _state(actors, dials=None):
    st = CombatState(encounter=Encounter(id="t", actors=actors),
                     optimization_dials=dict(dials or {}))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


class DialSubstrateTest(unittest.TestCase):
    def test_default_is_dial_1(self):
        a = _actor("a", "pc")
        self.assertEqual(od.dial_for(a, _state([a])), 1)

    def test_set_and_read_per_side(self):
        a = _actor("a", "pc")
        st = _state([a])
        od.set_dial(st, "pc", 4)
        self.assertEqual(od.dial_for(a, st), 4)

    def test_dial_clamped(self):
        a = _actor("a", "pc")
        self.assertEqual(od.dial_for(a, _state([a], {"pc": 9})), 5)
        self.assertEqual(od.dial_for(a, _state([a], {"pc": 0})), 1)

    def test_focus_fire_chance_mapping(self):
        self.assertEqual(od.focus_fire_chance(1), 0.0)
        self.assertAlmostEqual(od.focus_fire_chance(2), 1 / 3)
        self.assertAlmostEqual(od.focus_fire_chance(3), 2 / 3)
        self.assertEqual(od.focus_fire_chance(4), 0.875)
        self.assertEqual(od.focus_fire_chance(5), 1.0)


class FocusFireGateTest(unittest.TestCase):
    def test_warranted_needs_two_enemies(self):
        pc = _actor("pc", "pc")
        one = _actor("e1", "enemy")
        self.assertFalse(od.focus_fire_warranted(pc, _state([pc, one])))
        two = _actor("e2", "enemy")
        self.assertTrue(od.focus_fire_warranted(pc, _state([pc, one, two])))

    def test_dial1_never_dial5_always(self):
        pc = _actor("pc", "pc")
        e1, e2 = _actor("e1", "enemy"), _actor("e2", "enemy")
        rng = random.Random(0)
        st1 = _state([pc, e1, e2], {"pc": 1})
        st5 = _state([pc, e1, e2], {"pc": 5})
        self.assertFalse(od.should_focus_fire(pc, st1, rng))
        self.assertTrue(od.should_focus_fire(pc, st5, rng))

    def test_dial3_roughly_two_thirds(self):
        pc = _actor("pc", "pc")
        e1, e2 = _actor("e1", "enemy"), _actor("e2", "enemy")
        st = _state([pc, e1, e2], {"pc": 3})
        rng = random.Random(1)
        fires = sum(od.should_focus_fire(pc, st, rng) for _ in range(2000))
        self.assertTrue(0.60 < fires / 2000 < 0.74)   # ~2/3

    def test_focus_target_is_lowest_hp(self):
        pc = _actor("pc", "pc")
        hi = _actor("hi", "enemy", hp=80)
        lo = _actor("lo", "enemy", hp=12)
        target = od.focus_fire_target(pc, _state([pc, hi, lo]))
        self.assertEqual(target.id, "lo")


def _lock(enemy, break_on_damage=True):
    enemy.applied_conditions = [{"condition_id": "co_incapacitated",
                                 "break_on_damage": break_on_damage}]
    return enemy


class ControlAwareTargetTest(unittest.TestCase):
    """Control-aware focus-fire: don't gratuitously break break-on-damage locks
    (lock -> peel one at a time)."""

    def test_prefers_unlocked_over_lower_hp_locked(self):
        pc = _actor("pc", "pc")
        locked = _lock(_actor("locked", "enemy", hp=20))   # lower HP, but LOCKED
        unlocked = _actor("unlocked", "enemy", hp=60)
        target = od.focus_fire_target(pc, _state([pc, locked, unlocked]))
        self.assertEqual(target.id, "unlocked")   # don't wake the lock

    def test_near_death_locked_is_finishable(self):
        pc = _actor("pc", "pc", hp=40)
        # Locked giant at 10% HP -> worth dispatching (lock loss is moot).
        nearly = _lock(_actor("nearly", "enemy", hp=4))
        nearly.hp_max = 40
        unlocked = _actor("unlocked", "enemy", hp=60)
        target = od.focus_fire_target(pc, _state([pc, nearly, unlocked]))
        self.assertEqual(target.id, "nearly")    # finish the near-dead lock

    def test_all_healthy_locked_peels_one(self):
        pc = _actor("pc", "pc")
        a = _lock(_actor("a", "enemy", hp=50))
        b = _lock(_actor("b", "enemy", hp=30))
        target = od.focus_fire_target(pc, _state([pc, a, b]))
        self.assertEqual(target.id, "b")         # only locked left -> peel lowest

    def test_persistent_control_is_not_soft_locked(self):
        # Hold Monster (no break_on_damage flag) -> hit it freely (lowest HP).
        pc = _actor("pc", "pc")
        held = _lock(_actor("held", "enemy", hp=15), break_on_damage=False)
        other = _actor("other", "enemy", hp=60)
        target = od.focus_fire_target(pc, _state([pc, held, other]))
        self.assertEqual(target.id, "held")


class FocusFireDecisionTest(unittest.TestCase):
    """Integration: at dial 5 the decision layer locks single-target offense
    onto the lowest-HP enemy and drops the spread options."""

    def _weapon(self):
        return {"id": "a_sword", "type": "weapon_attack", "reach_ft": 5,
                "pipeline": [{"primitive": "attack_roll",
                              "params": {"bonus": 7, "reach_ft": 5}},
                             {"primitive": "damage",
                              "params": {"dice": "1d8", "modifier": 3,
                                         "type": "slashing"},
                              "when": {"condition":
                                       "combat.attack_state == hit"}}]}

    def _candidates(self, actor, enemies):
        w = actor.template["actions"][0]
        return [{"kind": "weapon_attack", "action": w, "target": e,
                 "actor": actor} for e in enemies]

    def test_dial5_locks_onto_lowest_hp(self):
        from engine.ai.decision_layer import score_candidates_v1
        atk = _actor("atk", "pc", actions=[self._weapon()])
        hi = _actor("hi", "enemy", hp=80)
        lo = _actor("lo", "enemy", hp=10)
        hi.position = (1, 0); lo.position = (1, 0)   # both in melee reach
        st = _state([atk, hi, lo], {"pc": 5})
        scored = score_candidates_v1(self._candidates(atk, [hi, lo]), atk, st)
        targets = {c["target"].id for _, c in scored}
        self.assertEqual(targets, {"lo"})   # spread option (hi) dropped

    def test_dial1_keeps_both_targets(self):
        from engine.ai.decision_layer import score_candidates_v1
        atk = _actor("atk", "pc", actions=[self._weapon()])
        hi = _actor("hi", "enemy", hp=80)
        lo = _actor("lo", "enemy", hp=10)
        hi.position = (1, 0); lo.position = (1, 0)
        st = _state([atk, hi, lo], {"pc": 1})   # casual: no focus-fire
        scored = score_candidates_v1(self._candidates(atk, [hi, lo]), atk, st)
        targets = {c["target"].id for _, c in scored}
        self.assertEqual(targets, {"hi", "lo"})   # both kept (no lock)


if __name__ == "__main__":
    unittest.main()
