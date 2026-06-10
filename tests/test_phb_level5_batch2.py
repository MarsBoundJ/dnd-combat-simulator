"""PHB-2024-only level-5 batch (part 2) — Swift Quiver, Yolande's Regal
Presence.

Engine pieces exercised:
  - swift_quiver_arm: stamps swift_quiver_active concentration-scrubbed
    marker; BA double-attack deferred (documented undervalue);
  - yolandes_regal_presence: persistent_aura with anchor:caster, sphere
    radius 10, enemies_in_area WIS save → 4d6 psychic + co_prone +
    forced_movement 10 ft on fail; half psychic on success.
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.concentration import end_concentration
from engine.core.events import EventBus
from engine.core.runner import EncounterRunner
from engine.primitives import PrimitiveRegistry

from tests._srd_helpers import (
    action_template, ally, caster, enemy, registry, state,
)


class TestRegistryLoads(unittest.TestCase):
    def test_features_present(self):
        reg = registry()
        for fid in ("f_swift_quiver", "f_yolandes_regal_presence"):
            self.assertIsNotNone(reg.get("feature", fid), fid)


class TestSwiftQuiver(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(7))

    def _cast(self):
        t = action_template("f_swift_quiver")
        rgr = caster(cid="rgr", ability="wisdom", position=(0, 0), slots={5: 1})
        foe = enemy(eid="foe", position=(5, 0), hp=40)
        st = state([rgr, foe])
        chosen = {"kind": "defensive_buff", "action": t, "target": rgr,
                   "actor": rgr}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        return st, rgr

    def test_marker_stamped(self):
        st, rgr = self._cast()
        markers = [m for m in rgr.active_modifiers
                   if m.get("primitive") == "swift_quiver_active"]
        self.assertEqual(len(markers), 1)

    def test_event_logged(self):
        st, rgr = self._cast()
        ev = next((e for e in st.event_log
                   if e["event"] == "swift_quiver_armed"), None)
        self.assertIsNotNone(ev)
        self.assertEqual(ev["caster"], "rgr")

    def test_concentration_scrubs_marker(self):
        st, rgr = self._cast()
        end_concentration(rgr, st, reason="test")
        markers = [m for m in rgr.active_modifiers
                   if m.get("primitive") == "swift_quiver_active"]
        self.assertEqual(markers, [])


class TestYolandesRegalPresence(unittest.TestCase):
    def setUp(self):
        primitives_module.set_rng(random.Random(13))

    def _cast(self, foe_wis_save=0):
        t = action_template("f_yolandes_regal_presence")
        wiz = caster(cid="wiz", ability="charisma", position=(0, 0), slots={5: 1})
        foe = enemy(eid="foe", position=(1, 0), hp=80, wis=foe_wis_save)
        buddy = ally(aid="buddy", position=(1, 0), hp=30, hp_max=30)
        far = enemy(eid="far", position=(20, 0), hp=40)
        st = state([wiz, foe, buddy, far])
        chosen = {"kind": "aoe_attack", "action": t, "target": foe,
                   "origin_point": (0, 0), "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        return st, wiz, foe, buddy, far

    def test_zone_registers(self):
        st, wiz, foe, buddy, far = self._cast()
        self.assertEqual(len(st.persistent_auras), 1)
        a = st.persistent_auras[0]
        self.assertEqual(a["anchor"], "caster")
        self.assertEqual(a["caster_id"], "wiz")

    def test_fail_deals_damage_and_prone(self):
        # WIS save -20 always fails — fire the turn-start trigger manually
        st, wiz, foe, buddy, far = self._cast(foe_wis_save=-20)
        runner = EncounterRunner.new(st.encounter, seed=99)
        runner._resolve_persistent_aura_triggers(foe, st)
        # 4d6 min 4 damage
        self.assertLessEqual(foe.hp_current, 80 - 4)
        cond_ids = [c["condition_id"] for c in foe.applied_conditions]
        self.assertIn("co_prone", cond_ids)

    def test_allies_and_out_of_range_spared(self):
        st, wiz, foe, buddy, far = self._cast()
        self.assertEqual(buddy.hp_current, 30)    # ally — spared
        self.assertEqual(far.hp_current, 40)      # 100 ft — out of range

    def test_concentration_scrubs_aura(self):
        st, wiz, foe, buddy, far = self._cast()
        self.assertEqual(len(st.persistent_auras), 1)
        end_concentration(wiz, st, reason="test")
        self.assertEqual(st.persistent_auras, [])


if __name__ == "__main__":
    unittest.main()
