"""martial_save_dc infrastructure + Intimidating Presence (the first
consumer).

martial_save_dc resolves to 8 + governing-ability mod + Proficiency
Bonus, for martial features whose save DC isn't a spell save DC (e.g.
Barbarian Intimidating Presence, STR). Covered at both resolution sites:
  - runtime: primitives._resolve_dc (what the save rolls against)
  - scoring: defensive_ehp._resolve_dc_for_action (what the AI projects)

Intimidating Presence (Berserker L14): BA, 30-ft self Emanation, WIS
save or Frightened with a turn-end re-save, on the martial STR DC.
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry, _resolve_dc
from tests import _srd_helpers as H


def _berserker(cid="zerk", *, str_score=20, pb=5, position=(0, 0)):
    # H.caster gives a STR score + PB; the martial DC ignores the
    # spellcasting_ability stamp and reads abilities.str + PB directly.
    a = H.caster(cid=cid, ability="strength", score=str_score, pb=pb,
                   position=position)
    a.resources = {"intimidating_presence_uses_remaining": 1}
    return a


class MartialSaveDcResolutionTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_runtime_dc_str_plus_pb(self):
        # STR 20 (+5), PB 5 → DC = 8 + 5 + 5 = 18
        zerk = _berserker(str_score=20, pb=5)
        st = H.state([zerk])
        st.current_attack = {"actor": zerk, "target": zerk}
        dc = _resolve_dc(
            {"dc_source": "martial_save_dc", "dc_ability": "strength"}, st)
        self.assertEqual(dc, 18)

    def test_runtime_dc_defaults_to_strength(self):
        zerk = _berserker(str_score=16, pb=3)  # +3 STR, PB 3 → 8+3+3 = 14
        st = H.state([zerk])
        st.current_attack = {"actor": zerk, "target": zerk}
        dc = _resolve_dc({"dc_source": "martial_save_dc"}, st)
        self.assertEqual(dc, 14)

    def test_runtime_dc_other_ability(self):
        # dc_ability: constitution → uses CON. CON 18 (+4), PB 2 → 14.
        zerk = H.caster(cid="z", ability="constitution", score=18, pb=2)
        st = H.state([zerk])
        st.current_attack = {"actor": zerk, "target": zerk}
        dc = _resolve_dc(
            {"dc_source": "martial_save_dc", "dc_ability": "constitution"}, st)
        self.assertEqual(dc, 14)


class IntimidatingPresenceExecutionTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(7))

    def test_loads_as_emanation(self):
        a = H.action_template("f_intimidating_presence")
        self.assertEqual(a["area"]["shape"], "emanation")
        self.assertEqual(a["area"]["size_ft"], 30)
        fs = a["pipeline"][0]["params"]
        self.assertEqual(fs["dc_source"], "martial_save_dc")
        self.assertEqual(fs["dc_ability"], "strength")

    def test_emanation_frightens_in_range_only(self):
        zerk = _berserker(position=(0, 0))
        near = H.enemy(eid="near", position=(4, 0), wis=-10)   # 20 ft — in
        far = H.enemy(eid="far", position=(8, 0), wis=-10)     # 40 ft — out
        st = H.state([zerk, near, far])
        chosen = {"kind": "hard_control",
                    "action": H.action_template("f_intimidating_presence"),
                    "target": near, "origin_point": (0, 0),
                    "direction": (1, 0), "actor": zerk}
        pipeline.execute(chosen, st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        save_targets = {e["target"] for e in st.event_log
                         if e.get("event") == "forced_save"}
        self.assertIn("near", save_targets)
        self.assertNotIn("far", save_targets)
        # DC 18 vs WIS save -10 → near auto-fails → Frightened + re-save.
        self.assertIn("co_frightened", H.condition_ids(near))
        self.assertIn("near",
                       {e["target_id"] for e in st.recurring_saves})
        self.assertNotIn("co_frightened", H.condition_ids(far))


class MartialSaveDcScoringTest(unittest.TestCase):

    def test_control_intent_carries_dc_ability(self):
        from engine.ai.defensive_ehp import (
            extract_control_intent, _resolve_dc_for_action,
        )
        action = H.action_template("f_intimidating_presence")
        intent = extract_control_intent(action)
        self.assertEqual(intent["save_dc_source"], "martial_save_dc")
        self.assertEqual(intent["save_dc_ability"], "strength")
        self.assertEqual(intent["save_ability"], "wisdom")
        # Scoring DC matches the runtime DC: STR 20 (+5), PB 5 → 18.
        zerk = _berserker(str_score=20, pb=5)
        self.assertEqual(_resolve_dc_for_action(intent, zerk), 18)


if __name__ == "__main__":
    unittest.main()
