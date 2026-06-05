"""PC downed / death-saving-throw lifecycle (Stage 1).

A death-save creature (PC) at 0 HP falls unconscious + dying instead of dying
outright; rolls death saves at turn start; 3 successes -> stable, 3 failures
-> dead, nat 20 -> revive at 1 HP; damage while dying = auto-fail(s); massive
damage = instant death. Monsters die outright.

Run via:
    python -m unittest tests.test_death_saves
"""
from __future__ import annotations

import random
import unittest

from engine.core import death_saves as ds
from engine.core.concentration import apply_concentration
from engine.core.events import EventBus
from engine.core.state import Actor, Encounter, CombatState
import engine.primitives as primitives_module


def _actor(actor_id, side="pc", hp=40, hp_max=40):
    ab = {k: {"score": 12, "save": 1} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                 template={"id": f"t_{actor_id}", "abilities": ab,
                           "cr": {"proficiency_bonus": 2}, "actions": []},
                 side=side, hp_current=hp, hp_max=hp_max, ac=12,
                 position=(0, 0), abilities=ab)


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


class GatingTest(unittest.TestCase):
    def test_pc_uses_death_saves(self):
        self.assertTrue(ds.uses_death_saves(_actor("p", side="pc")))

    def test_monster_does_not(self):
        self.assertFalse(ds.uses_death_saves(_actor("m", side="enemy")))


class EnterDyingViaDamageTest(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def _hit(self, target, state, amount):
        # Deterministic fixed damage via modifier (no dice roll).
        attacker = _actor("atk", side="enemy")
        state.current_attack = {"actor": attacker, "target": target,
                                 "action": {}, "state": "hit"}
        primitives_module._damage({"dice": "", "modifier": amount,
                                    "type": "fire"}, state, EventBus())

    def test_pc_at_zero_is_dying_not_dead(self):
        pc = _actor("pc", side="pc", hp=8, hp_max=40)
        st = _state([pc])
        self._hit(pc, st, 8)               # exact drop to 0, overflow 0
        self.assertEqual(pc.hp_current, 0)
        self.assertTrue(pc.is_dying)
        self.assertFalse(pc.is_dead)

    def test_monster_at_zero_dies_outright(self):
        mon = _actor("mon", side="enemy", hp=8, hp_max=40)
        st = _state([mon])
        self._hit(mon, st, 8)
        self.assertTrue(mon.is_dead)
        self.assertFalse(mon.is_dying)

    def test_massive_damage_is_instant_death_for_pc(self):
        # 8 HP, hp_max 40, take 48 -> overflow 40 >= 40 -> instant death.
        pc = _actor("pc", side="pc", hp=8, hp_max=40)
        st = _state([pc])
        self._hit(pc, st, 48)
        self.assertTrue(pc.is_dead)
        self.assertFalse(pc.is_dying)

    def test_entering_dying_ends_concentration(self):
        pc = _actor("pc", side="pc", hp=8, hp_max=40)
        st = _state([pc])
        apply_concentration(pc, {"id": "a_bless", "concentration": True}, st)
        self.assertIsNotNone(pc.concentration_on)
        self._hit(pc, st, 8)
        self.assertTrue(pc.is_dying)
        self.assertIsNone(pc.concentration_on)


class TurnStartSaveTest(unittest.TestCase):
    def _dying_pc(self):
        pc = _actor("pc", side="pc", hp=0, hp_max=40)
        st = _state([pc])
        ds.enter_dying(pc, st)
        return pc, st

    def test_high_roll_is_success(self):
        pc, st = self._dying_pc()
        ds.resolve_turn_start(pc, st, random.Random(0))   # first d20 >= 10
        # roll outcome is rng-dependent; assert a save was recorded
        saves = [e for e in st.event_log if e["event"] == "death_save"]
        self.assertEqual(len(saves), 1)

    def test_three_successes_stabilizes(self):
        pc, st = self._dying_pc()
        pc.death_save_successes = 2
        # Force a success: rng whose first randint(1,20) >= 10.
        class _R:  # deterministic d20 = 15
            def randint(self, a, b): return 15
        ds.resolve_turn_start(pc, st, _R())
        self.assertTrue(pc.is_stable)
        self.assertFalse(pc.is_dead)

    def test_three_failures_dies(self):
        pc, st = self._dying_pc()
        pc.death_save_failures = 2

        class _R:  # deterministic d20 = 5 (fail)
            def randint(self, a, b): return 5
        ds.resolve_turn_start(pc, st, _R())
        self.assertTrue(pc.is_dead)
        self.assertFalse(pc.is_dying)

    def test_nat20_revives_at_1hp(self):
        pc, st = self._dying_pc()

        class _R:
            def randint(self, a, b): return 20
        ds.resolve_turn_start(pc, st, _R())
        self.assertFalse(pc.is_dying)
        self.assertFalse(pc.is_dead)
        self.assertEqual(pc.hp_current, 1)

    def test_nat1_is_two_failures(self):
        pc, st = self._dying_pc()

        class _R:
            def randint(self, a, b): return 1
        ds.resolve_turn_start(pc, st, _R())
        self.assertEqual(pc.death_save_failures, 2)

    def test_stable_does_not_roll(self):
        pc, st = self._dying_pc()
        ds.stabilize(pc, st)
        st.event_log.clear()

        class _R:
            def randint(self, a, b): raise AssertionError("should not roll")
        ds.resolve_turn_start(pc, st, _R())   # no-op, no roll
        self.assertEqual([e for e in st.event_log
                          if e["event"] == "death_save"], [])


class DamageWhileDyingTest(unittest.TestCase):
    def test_one_failure_per_hit(self):
        pc = _actor("pc", side="pc", hp=0, hp_max=40)
        st = _state([pc])
        ds.enter_dying(pc, st)
        ds.damage_while_dying(pc, st, is_crit=False)
        self.assertEqual(pc.death_save_failures, 1)

    def test_crit_is_two_failures(self):
        pc = _actor("pc", side="pc", hp=0, hp_max=40)
        st = _state([pc])
        ds.enter_dying(pc, st)
        ds.damage_while_dying(pc, st, is_crit=True)
        self.assertEqual(pc.death_save_failures, 2)

    def test_third_failure_kills(self):
        pc = _actor("pc", side="pc", hp=0, hp_max=40)
        st = _state([pc])
        ds.enter_dying(pc, st)
        pc.death_save_failures = 2
        ds.damage_while_dying(pc, st, is_crit=False)
        self.assertTrue(pc.is_dead)


if __name__ == "__main__":
    unittest.main()
