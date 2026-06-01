"""Magic Missile tests — SRD spell batch 1.

The guaranteed-hit force-damage spell: no attack roll, no save. Rides
the bare `damage` primitive. v1 focus-fires three 1d4+1 darts on one
target as a single 3d4+3 force step (+1d4 per slot above 1st).

Layers:
  1. f_magic_missile loads with the right shape
  2. end-to-end: damage lands with NO attack roll and NO save event
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
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
    return dict(_registry().get("feature", "f_magic_missile")["action_template"])


def _wizard():
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id="wiz", name="wiz",
                   template={"id": "t", "name": "wiz", "abilities": abilities,
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="pc", hp_current=12, hp_max=12, ac=12,
                   position=(0, 0), speed={"walk": 30}, abilities=abilities,
                   spell_slots={1: 2})


def _enemy(hp=40):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id="orc", name="orc",
                   template={"id": "t", "name": "orc", "abilities": abilities,
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="enemy", hp_current=hp, hp_max=hp, ac=16,   # high AC
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
        feat = _registry().get("feature", "f_magic_missile")
        self.assertEqual(feat["spell"]["level"], 1)
        self.assertEqual(feat["source"], "srd_5.2.1")

    def test_pipeline_is_pure_damage(self):
        a = _action()
        self.assertEqual(len(a["pipeline"]), 1)
        dmg = a["pipeline"][0]
        self.assertEqual(dmg["primitive"], "damage")
        self.assertEqual(dmg["params"]["dice"], "3d4")
        self.assertEqual(dmg["params"]["modifier"], 3)
        self.assertEqual(dmg["params"]["type"], "force")
        self.assertEqual(a["upcast_scaling"]["extra_dice_per_level"], "1d4")


class EndToEndTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(7))

    def test_auto_hits_with_no_roll_or_save(self):
        wiz, orc = _wizard(), _enemy(hp=40)
        state = _state([wiz, orc])
        chosen = {"kind": "auto_attack", "action": _action(),
                    "target": orc, "actor": wiz}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        # Damage in the 3d4+3 = 6..15 band landed despite the orc's AC 16
        dealt = 40 - orc.hp_current
        self.assertGreaterEqual(dealt, 6)
        self.assertLessEqual(dealt, 15)
        # No attack roll and no save were involved (auto-hit, no save)
        self.assertFalse([e for e in state.event_log
                           if e.get("event") == "attack_roll"])
        self.assertFalse([e for e in state.event_log
                           if e.get("event") == "forced_save"])

    def test_slot_consumed(self):
        wiz, orc = _wizard(), _enemy()
        state = _state([wiz, orc])
        chosen = {"kind": "auto_attack", "action": _action(),
                    "target": orc, "actor": wiz}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        self.assertEqual(wiz.spell_slots.get(1), 1)     # 2 → 1


if __name__ == "__main__":
    unittest.main()
