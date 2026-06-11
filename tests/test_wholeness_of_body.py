"""Wholeness of Body — Warrior of the Open Hand (Monk L6) self-heal.

Covers the pc_builder heal wiring (self-target, Martial Arts die + WIS
modifier, WIS-mod feature_use count) and the Long Rest refresh.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core.rest import apply_long_rest
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template, derive_pc_resources

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


def _open_hand_l6():
    # WIS 16 → +3: heal modifier 3, uses 3. Martial Arts die at L6 = 1d8.
    return {"id": "m", "class": "c_monk", "level": 6,
            "subclass": "sc_warrior_of_the_open_hand",
            "ability_scores": {"str": 12, "dex": 16, "con": 14,
                                "int": 8, "wis": 16, "cha": 10},
            "weapons": []}


class WholenessBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                     schema_root=SCHEMA_ROOT)

    def test_feature_and_resource_present(self):
        pc = _open_hand_l6()
        tmpl = build_pc_template(pc, self.registry)
        self.assertIn("f_wholeness_of_body", tmpl.get("features_known", []))
        res = derive_pc_resources(pc, self.registry)
        self.assertEqual(res.get("wholeness_of_body_uses_remaining"), 3)
        self.assertEqual(res.get("wholeness_of_body_uses_max"), 3)

    def test_heal_action_shape(self):
        tmpl = build_pc_template(_open_hand_l6(), self.registry)
        action = next((a for a in tmpl["actions"]
                        if a.get("id") == "a_wholeness_of_body"), None)
        self.assertIsNotNone(action)
        self.assertEqual(action["type"], "heal")
        self.assertEqual(action["slot"], "bonus_action")
        self.assertEqual(action["feature_use"],
                          "wholeness_of_body_uses_remaining")
        params = action["pipeline"][0]["params"]
        self.assertEqual(params["target"], "self")
        self.assertEqual(params["dice"], "1d8")       # Monk L6 Martial Arts die
        self.assertEqual(params["modifier"], 3)        # WIS +3

    def test_die_scales_with_monk_level(self):
        pc = _open_hand_l6()
        pc["level"] = 11                                # MA die → 1d10
        tmpl = build_pc_template(pc, self.registry)
        action = next(a for a in tmpl["actions"]
                       if a.get("id") == "a_wholeness_of_body")
        self.assertEqual(action["pipeline"][0]["params"]["dice"], "1d10")


class WholenessLongRestTest(unittest.TestCase):
    def test_uses_refresh_on_long_rest(self):
        a = Actor(id="m", name="m",
                   template={"id": "t", "name": "m",
                              "abilities": {k: {"score": 10, "save": 0}
                                             for k in ("str", "dex", "con",
                                                        "int", "wis", "cha")},
                              "cr": {"proficiency_bonus": 3}, "actions": [],
                              "derived_from_pc_schema": {"class": "c_monk",
                                                          "level": 6}},
                   side="pc", hp_current=40, hp_max=40, ac=15,
                   speed={"walk": 30}, position=(0, 0),
                   abilities={k: {"score": 10, "save": 0}
                               for k in ("str", "dex", "con", "int", "wis", "cha")},
                   resources={"wholeness_of_body_uses_remaining": 0,
                               "wholeness_of_body_uses_max": 3})
        state = CombatState(encounter=Encounter(id="t", actors=[a]))
        summary = apply_long_rest(a, state)
        self.assertEqual(a.resources["wholeness_of_body_uses_remaining"], 3)
        self.assertIn("wholeness_of_body_refresh", summary)


if __name__ == "__main__":
    unittest.main()
