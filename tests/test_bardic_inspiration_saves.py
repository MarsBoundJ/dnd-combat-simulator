"""Bardic Inspiration on saving throws.

A creature holding a Bardic Inspiration die may add it to a FAILED saving
throw to turn it into a success — the same held-resource self-add already
modeled on attack rolls, now hooked into _forced_save. The die is spent only
when it can close the gap, and conserved otherwise.
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core.bardic_inspiration import (
    register_inspiration_die, find_inspiration_die, maybe_add_to_save)
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter


def _ab(wis_save=2):
    d = {k: {"score": 10, "save": 0}
         for k in ("str", "dex", "con", "int", "wis", "cha")}
    d["wis"] = {"score": 10, "save": wis_save}
    return d


def _actor(aid="t", side="pc"):
    ab = _ab()
    return Actor(id=aid, name=aid,
                 template={"id": f"t_{aid}", "name": aid, "abilities": ab,
                           "cr": {"proficiency_bonus": 2}, "actions": []},
                 side=side, hp_current=30, hp_max=30, ac=12,
                 position=(0, 0), speed={"walk": 30}, abilities=ab)


def _fright(dc):
    return {"ability": "wisdom", "dc": dc, "affected": "current_target",
            "on_fail": [{"primitive": "apply_condition",
                         "params": {"condition_id": "co_frightened"}}],
            "on_success": []}


def _run_save(target, dc, seed, *, give_die=None):
    caster = _actor("caster", side="enemy")
    st = CombatState(encounter=Encounter(id="e", actors=[caster, target]))
    st.turn_order = ["caster", target.id]
    st.round = 1
    if give_die:
        register_inspiration_die(target, give_die, "caster", st)
    st.current_attack = {"actor": caster, "target": target}
    primitives_module.set_rng(random.Random(seed))
    primitives_module._forced_save(_fright(dc), st, EventBus())
    frightened = any(c.get("condition_id") == "co_frightened"
                     for c in target.applied_conditions)
    added = any(e.get("event") == "bardic_inspiration_added"
                for e in st.event_log)
    return frightened, added


class MaybeAddToSaveTest(unittest.TestCase):

    def test_boosts_failed_save_within_reach(self):
        # total 10, DC 13, d8 die → can reach (10+8 >= 13). Spends die.
        a = _actor()
        register_inspiration_die(a, "d8", "src",
                                  CombatState(encounter=Encounter(id="e",
                                                                  actors=[a])))
        st = CombatState(encounter=Encounter(id="e", actors=[a]))
        register_inspiration_die(a, "d8", "src", st)
        new_total = maybe_add_to_save(a, 10, 13, st, random.Random(1))
        self.assertGreaterEqual(new_total, 10)
        self.assertIsNone(find_inspiration_die(a))   # consumed

    def test_conserves_die_when_unreachable(self):
        a = _actor()
        st = CombatState(encounter=Encounter(id="e", actors=[a]))
        register_inspiration_die(a, "d8", "src", st)
        # total 5, DC 30 → even +8 can't reach; keep the die.
        new_total = maybe_add_to_save(a, 5, 30, st, random.Random(1))
        self.assertEqual(new_total, 5)
        self.assertIsNotNone(find_inspiration_die(a))

    def test_conserves_die_when_already_passing(self):
        a = _actor()
        st = CombatState(encounter=Encounter(id="e", actors=[a]))
        register_inspiration_die(a, "d8", "src", st)
        new_total = maybe_add_to_save(a, 18, 13, st, random.Random(1))
        self.assertEqual(new_total, 18)
        self.assertIsNotNone(find_inspiration_die(a))

    def test_noop_without_die(self):
        a = _actor()
        st = CombatState(encounter=Encounter(id="e", actors=[a]))
        self.assertEqual(maybe_add_to_save(a, 10, 13, st, random.Random(1)), 10)


class ForcedSaveIntegrationTest(unittest.TestCase):

    def test_die_rescues_more_saves(self):
        no_die = sum(not _run_save(_actor(), 14, s)[0] for s in range(200))
        with_die = sum(not _run_save(_actor(), 14, s, give_die="d8")[0]
                       for s in range(200))
        self.assertGreater(with_die, no_die)

    def test_die_conserved_on_unreachable_dc(self):
        a = _actor()
        _, added = _run_save(a, 40, 0, give_die="d8")
        self.assertFalse(added)
        self.assertIsNotNone(find_inspiration_die(a))

    def test_die_conserved_on_easy_dc(self):
        a = _actor()
        _, added = _run_save(a, 2, 0, give_die="d8")
        self.assertFalse(added)
        self.assertIsNotNone(find_inspiration_die(a))

    def test_logs_kind_save(self):
        # Find a seed where the die is actually spent and check the log tag.
        for seed in range(50):
            a = _actor()
            caster = _actor("caster", side="enemy")
            st = CombatState(encounter=Encounter(id="e", actors=[caster, a]))
            st.turn_order = ["caster", a.id]
            st.round = 1
            register_inspiration_die(a, "d8", "caster", st)
            st.current_attack = {"actor": caster, "target": a}
            primitives_module.set_rng(random.Random(seed))
            primitives_module._forced_save(_fright(14), st, EventBus())
            added = [e for e in st.event_log
                     if e.get("event") == "bardic_inspiration_added"]
            if added:
                self.assertEqual(added[0]["kind"], "save")
                return
        self.fail("no seed exercised the save-add path")


if __name__ == "__main__":
    unittest.main()
