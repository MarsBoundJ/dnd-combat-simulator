"""PHB-2024-only level 6–8 batch — Arcane Gate (6th, stub), Summon Fiend
(6th), Tasha's Bubbling Cauldron (6th, stub), Power Word Fortify (7th),
Telepathy (8th, stub).

Engine pieces exercised:
  - summon primitive: m_fiendish_spirit_devil loaded and summoned;
  - temp_hp_grant: 120 temp HP granted to caster by Power Word Fortify;
  - stub spells: registry loads only (no pipeline effect asserted).
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry

from tests._srd_helpers import (
    action_template, caster, enemy, registry, state,
)


class TestRegistryLoads(unittest.TestCase):
    def test_features_present(self):
        reg = registry()
        for fid in (
            "f_arcane_gate",
            "f_summon_fiend",
            "f_tashas_bubbling_cauldron",
            "f_power_word_fortify",
            "f_telepathy",
        ):
            self.assertIsNotNone(reg.get("feature", fid), fid)

    def test_fiendish_spirit_devil_monster_present(self):
        self.assertIsNotNone(
            registry().get("monster", "m_fiendish_spirit_devil"))


class TestArcaneGate(unittest.TestCase):
    def test_stub_executes_without_error(self):
        t = action_template("f_arcane_gate")
        wiz = caster(cid="wiz", ability="intelligence", position=(0, 0),
                      slots={6: 1})
        foe = enemy(eid="foe", position=(5, 0), hp=40)
        st = state([wiz, foe])
        chosen = {"kind": "defensive_buff", "action": t, "target": wiz,
                   "actor": wiz}
        # Should not raise even with empty pipeline
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())


class TestSummonFiend(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(42))

    def test_fiend_spawns_in_encounter(self):
        t = action_template("f_summon_fiend")
        wiz = caster(cid="wiz", ability="intelligence", position=(0, 0),
                      slots={6: 1})
        foe = enemy(eid="foe", position=(10, 0), hp=60)
        st = state([wiz, foe])
        chosen = {"kind": "summon", "action": t, "target": foe,
                   "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        summoned_ids = [a.id for a in st.encounter.actors
                        if "fiendish_spirit_devil" in a.id]
        self.assertEqual(len(summoned_ids), 1)

    def test_fiend_statblock(self):
        m = registry().get("monster", "m_fiendish_spirit_devil")
        self.assertEqual(m["combat"]["armor_class"], 18)
        self.assertEqual(m["combat"]["speed"]["fly"], 60)
        self.assertIn("fire", m["damage_resistances"])
        self.assertIn("poison", m["damage_immunities"])


class TestTashasBubbling(unittest.TestCase):
    def test_stub_executes_without_error(self):
        t = action_template("f_tashas_bubbling_cauldron")
        wiz = caster(cid="wiz", ability="intelligence", position=(0, 0),
                      slots={6: 1})
        foe = enemy(eid="foe", position=(5, 0), hp=40)
        st = state([wiz, foe])
        chosen = {"kind": "defensive_buff", "action": t, "target": wiz,
                   "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())


class TestPowerWordFortify(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(7))

    def test_grants_120_temp_hp_to_caster(self):
        t = action_template("f_power_word_fortify")
        clr = caster(cid="clr", ability="wisdom", position=(0, 0),
                      slots={7: 1}, hp=50)
        foe = enemy(eid="foe", position=(5, 0), hp=40)
        st = state([clr, foe])
        chosen = {"kind": "defensive_buff", "action": t, "target": clr,
                   "actor": clr}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertEqual(clr.temp_hp, 120)

    def test_event_logged(self):
        t = action_template("f_power_word_fortify")
        clr = caster(cid="clr", ability="wisdom", position=(0, 0),
                      slots={7: 1}, hp=50)
        foe = enemy(eid="foe", position=(5, 0), hp=40)
        st = state([clr, foe])
        chosen = {"kind": "defensive_buff", "action": t, "target": clr,
                   "actor": clr}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        ev = next((e for e in st.event_log if e["event"] == "temp_hp_granted"), None)
        self.assertIsNotNone(ev)
        self.assertEqual(ev["amount"], 120)


class TestTelepathy(unittest.TestCase):
    def test_stub_executes_without_error(self):
        t = action_template("f_telepathy")
        wiz = caster(cid="wiz", ability="intelligence", position=(0, 0),
                      slots={8: 1})
        foe = enemy(eid="foe", position=(5, 0), hp=40)
        st = state([wiz, foe])
        chosen = {"kind": "defensive_buff", "action": t, "target": wiz,
                   "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())


if __name__ == "__main__":
    unittest.main()
