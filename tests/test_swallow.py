"""Swallow / Engulf — restrain-and-internalize (engine.core.swallow).

Layers:
  1. a failed DEX save (Swallow on_fail) swallows the target: Blinded +
     Restrained (sourced to the swallower), Total Cover, tracked, pulled
     into the swallower's space
  2. a successful save → not swallowed
  3. ongoing acid at the swallower's turn start (tick)
  4. release frees the conditions / cover / tracking
  5. the swallower's death frees its victim (via _damage death site)
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import swallow
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import _forced_save, _damage, PrimitiveRegistry


def _abil(dex=10):
    a = {k: {"score": 12, "save": 1}
         for k in ("str", "dex", "con", "int", "wis", "cha")}
    a["dex"] = {"score": dex, "save": (dex - 10) // 2}
    return a


def _behir(hp=90, pos=(0, 0)):
    ab = {k: {"score": 16, "save": 3} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id="behir", name="behir",
                  template={"id": "m_behir", "name": "Behir", "abilities": ab,
                             "actions": [], "cr": {"proficiency_bonus": 4}},
                  side="enemy", hp_current=hp, hp_max=hp, ac=17,
                  speed={"walk": 40}, position=pos, abilities=ab,
                  size="huge", creature_type="monstrosity")


def _hero(hp=45, pos=(1, 0), dex=10):
    ab = _abil(dex)
    return Actor(id="hero", name="hero",
                  template={"id": "pc", "name": "hero", "abilities": ab,
                             "actions": [], "cr": {"proficiency_bonus": 2}},
                  side="pc", hp_current=hp, hp_max=hp, ac=14,
                  speed={"walk": 30}, position=pos, abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


# A Behir-shaped Swallow on_fail block: Blinded + Restrained + swallow_apply.
_ON_FAIL = [
    {"primitive": "apply_condition",
      "params": {"condition_id": "co_blinded", "duration": "until_removed"}},
    {"primitive": "apply_condition",
      "params": {"condition_id": "co_restrained", "duration": "until_removed"}},
    {"primitive": "swallow_apply",
      "params": {"acid_dice": "6d6", "acid_type": "acid"}},
]


def _attempt_swallow(behir, hero, state, *, dc):
    state.current_attack = {"actor": behir, "target": hero, "state": None,
                             "had_advantage": False, "had_disadvantage": False}
    _forced_save({"ability": "dexterity", "dc": dc,
                   "affected": "current_target",
                   "on_fail": _ON_FAIL, "on_success": []},
                  state, EventBus())


def _has_cond(actor, cond, source):
    return any(c.get("condition_id") == cond and c.get("source_id") == source
                for c in actor.applied_conditions)


class ApplyTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_failed_save_swallows(self):
        b, h = _behir(), _hero(pos=(3, 0))
        st = _state([b, h])
        _attempt_swallow(b, h, st, dc=99)        # unbeatable → fail
        self.assertEqual(h.swallowed_by, "behir")
        self.assertEqual(h.cover, "total")
        self.assertEqual(h.swallow_damage["dice"], "6d6")
        self.assertTrue(_has_cond(h, "co_blinded", "behir"))
        self.assertTrue(_has_cond(h, "co_restrained", "behir"))
        self.assertEqual(h.position, b.position)   # pulled inside
        self.assertTrue(swallow.is_swallowed(h))

    def test_successful_save_not_swallowed(self):
        b, h = _behir(), _hero(dex=20)
        st = _state([b, h])
        _attempt_swallow(b, h, st, dc=1)          # auto-succeed
        self.assertIsNone(h.swallowed_by)
        self.assertEqual(h.cover, "none")


class TickTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_acid_at_swallower_turn_start(self):
        b, h = _behir(), _hero(hp=45)
        st = _state([b, h])
        _attempt_swallow(b, h, st, dc=99)
        prims = PrimitiveRegistry.with_defaults()
        swallow.tick(b, st, prims, EventBus())
        self.assertLess(h.hp_current, 45)         # took acid
        self.assertGreater(h.hp_current, 0)

    def test_tick_noop_without_victim(self):
        b = _behir()
        st = _state([b])
        prims = PrimitiveRegistry.with_defaults()
        swallow.tick(b, st, prims, EventBus())     # no victim → no error
        ticks = [e for e in st.event_log if e["event"] == "swallow_acid_tick"]
        self.assertEqual(ticks, [])


class ReleaseTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_release_frees_conditions_and_cover(self):
        b, h = _behir(), _hero()
        st = _state([b, h])
        _attempt_swallow(b, h, st, dc=99)
        swallow.release(h, st, reason="test")
        self.assertIsNone(h.swallowed_by)
        self.assertEqual(h.cover, "none")
        self.assertFalse(_has_cond(h, "co_blinded", "behir"))
        self.assertFalse(_has_cond(h, "co_restrained", "behir"))

    def test_swallower_death_frees_victim(self):
        b, h = _behir(hp=12), _hero()
        st = _state([b, h])
        _attempt_swallow(b, h, st, dc=99)
        self.assertTrue(swallow.is_swallowed(h))
        # Kill the behir → its victim is freed at the death site.
        atk = _hero("striker"); atk.id = "striker"
        st.current_attack = {"actor": atk, "target": b, "state": "hit",
                              "action": {"id": "a"}, "had_advantage": False,
                              "had_disadvantage": False}
        _damage({"dice": "", "modifier": 50, "type": "slashing"},
                st, EventBus())
        self.assertTrue(b.is_dead)
        self.assertIsNone(h.swallowed_by)          # freed
        self.assertEqual(h.cover, "none")


if __name__ == "__main__":
    unittest.main()
