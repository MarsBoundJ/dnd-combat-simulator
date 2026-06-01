"""Mage Armor tests — SRD spell batch 1.

Self/ally defensive buff. RAW sets base AC to 13 + DEX, which for an
unarmored caster (base 10 + DEX) is a flat +3 — modeled as an
ac_modifier of +3 lasting the adventuring day (not Concentration).

Layers:
  1. f_mage_armor loads with the right shape
  2. end-to-end: casting registers a +3 ac_modifier that raises the
     caster's effective AC
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core import pipeline
from engine.core.events import EventBus
from engine.core import modifiers
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import PrimitiveRegistry


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"

_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True,
                                   schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _action():
    return dict(_registry().get("feature", "f_mage_armor")["action_template"])


def _wizard(ac=12):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id="wiz", name="wiz",
                   template={"id": "t", "name": "wiz", "abilities": abilities,
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="pc", hp_current=12, hp_max=12, ac=ac,
                   position=(0, 0), speed={"walk": 30}, abilities=abilities,
                   spell_slots={1: 2})


def _attacker():
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id="foe", name="foe",
                   template={"id": "t", "name": "foe", "abilities": abilities,
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="enemy", hp_current=20, hp_max=20, ac=12,
                   position=(1, 0), speed={"walk": 30}, abilities=abilities)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class WiringTest(unittest.TestCase):

    def test_loads(self):
        feat = _registry().get("feature", "f_mage_armor")
        self.assertEqual(feat["spell"]["level"], 1)
        self.assertEqual(feat["source"], "srd_5.2.1")

    def test_not_concentration(self):
        a = _action()
        self.assertFalse(a.get("concentration"))
        self.assertEqual(a["type"], "defensive_buff")
        step = a["pipeline"][0]["params"]
        self.assertEqual(step["modifier"], "ac_modifier")
        self.assertEqual(step["value"], 3)
        self.assertEqual(step["target"], "self")


class EndToEndTest(unittest.TestCase):

    def test_cast_grants_plus_3_ac(self):
        wiz = _wizard(ac=12)
        foe = _attacker()
        state = _state([wiz, foe])
        chosen = {"kind": "defensive_buff", "action": _action(),
                    "target": wiz, "actor": wiz}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        # A +3 ac_modifier is now on the caster
        ac_mods = [m for m in wiz.active_modifiers
                    if m.get("params", {}).get("modifier") == "ac_modifier"]
        self.assertEqual(len(ac_mods), 1)
        self.assertEqual(ac_mods[0]["params"]["value"], 3)
        # The modifier query sees the +3 when an attacker computes AC
        attack_mods = modifiers.query_attack_modifiers(foe, wiz, state)
        self.assertEqual(attack_mods.ac_modifier, 3)


if __name__ == "__main__":
    unittest.main()
