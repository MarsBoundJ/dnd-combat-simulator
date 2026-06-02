"""Aura traits — always-on monster emanations (Ghast Stench).

Layers:
  1. register builds a caster-anchored persistent_aura from the trait
  2. a creature starting its turn in range fails the save -> condition
  3. out of range -> nothing
  4. immune_on_success: a creature that succeeds is immune thereafter
     (skipped even when it would now fail)
  5. the aura moves with the monster (caster-anchored reads live position)
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import aura_traits
from engine.core.runner import EncounterRunner
from engine.core.state import Actor, CombatState, Encounter


def _abil():
    return {k: {"score": 10, "save": 0}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _ghast(dc=10, pos=(0, 0), immune=True):
    ab = _abil()
    return Actor(id="ghast", name="ghast",
                  template={"id": "m_ghast", "name": "Ghast", "abilities": ab,
                             "actions": [], "cr": {"proficiency_bonus": 2},
                             "auras": [{
                                 "id": "t_stench", "name": "Stench",
                                 "range_ft": 5,
                                 "save": {"ability": "constitution", "dc": dc},
                                 "affected": "enemies",
                                 "immune_on_success": immune,
                                 "on_fail": [{"primitive": "apply_condition",
                                     "params": {"condition_id": "co_poisoned",
                                                 "duration": "until_actor_next_turn_start"}}],
                             }]},
                  side="enemy", hp_current=30, hp_max=30, ac=12,
                  speed={"walk": 30}, position=pos, abilities=ab)


def _hero(pos=(1, 0)):
    ab = _abil()
    return Actor(id="hero", name="hero",
                  template={"id": "pc", "name": "hero", "abilities": ab,
                             "actions": [], "cr": {"proficiency_bonus": 2}},
                  side="pc", hp_current=30, hp_max=30, ac=12,
                  speed={"walk": 30}, position=pos, abilities=ab)


def _setup(ghast, hero):
    enc = Encounter(id="t", actors=[ghast, hero])
    st = CombatState(encounter=enc)
    st.turn_order = [ghast.id, hero.id]
    st.round = 1
    runner = EncounterRunner.new(enc, seed=1)
    aura_traits.register(st)
    primitives_module.set_rng(random.Random(1))
    return st, runner


def _poisoned(actor):
    return any(c.get("condition_id") == "co_poisoned"
                for c in actor.applied_conditions)


class RegisterTest(unittest.TestCase):

    def test_register_builds_caster_anchored_aura(self):
        g, h = _ghast(), _hero()
        st, _ = _setup(g, h)
        self.assertEqual(len(st.persistent_auras), 1)
        a = st.persistent_auras[0]
        self.assertEqual(a["anchor"], "caster")
        self.assertEqual(a["radius_ft"], 5)
        self.assertTrue(a["is_trait_aura"])


class TriggerTest(unittest.TestCase):

    def test_in_range_failed_save_poisons(self):
        g, h = _ghast(dc=99), _hero(pos=(1, 0))   # 5 ft, can't pass
        st, runner = _setup(g, h)
        runner._resolve_persistent_aura_triggers(h, st)
        self.assertTrue(_poisoned(h))

    def test_out_of_range_nothing(self):
        g, h = _ghast(dc=99), _hero(pos=(3, 0))   # 15 ft, outside 5
        st, runner = _setup(g, h)
        runner._resolve_persistent_aura_triggers(h, st)
        self.assertFalse(_poisoned(h))

    def test_ally_unaffected(self):
        g = _ghast(dc=99)
        ally = _hero(pos=(1, 0)); ally.id = "minion"; ally.side = "enemy"
        st, runner = _setup(g, ally)
        runner._resolve_persistent_aura_triggers(ally, st)
        self.assertFalse(_poisoned(ally))          # same side as ghast


class ImmunityTest(unittest.TestCase):

    def test_success_grants_encounter_immunity(self):
        g, h = _ghast(dc=1), _hero(pos=(1, 0))     # auto-succeed first
        st, runner = _setup(g, h)
        runner._resolve_persistent_aura_triggers(h, st)
        self.assertFalse(_poisoned(h))
        self.assertIn("hero", st.persistent_auras[0].get("_immune_ids", set()))
        # Now make the aura unbeatable — immunity must still skip it.
        st.persistent_auras[0]["dc"] = 99
        runner._resolve_persistent_aura_triggers(h, st)
        self.assertFalse(_poisoned(h))             # immune → skipped


class MovementTest(unittest.TestCase):

    def test_aura_follows_the_monster(self):
        g, h = _ghast(dc=99, pos=(0, 0)), _hero(pos=(3, 0))   # 15 ft: safe
        st, runner = _setup(g, h)
        runner._resolve_persistent_aura_triggers(h, st)
        self.assertFalse(_poisoned(h))
        # Ghast moves adjacent → hero is now in the emanation.
        g.position = (2, 0)                        # 5 ft from hero
        runner._resolve_persistent_aura_triggers(h, st)
        self.assertTrue(_poisoned(h))


if __name__ == "__main__":
    unittest.main()
