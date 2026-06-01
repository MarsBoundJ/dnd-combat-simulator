"""Lightning Bolt tests — SRD spell batch 2 (100-ft line, DEX save 8d6)."""
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
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO_ROOT / "schema" / "content", validate=True,
                                   schema_root=REPO_ROOT / "schema" / "definitions")
    return _REGISTRY


def _action():
    return dict(_registry().get("feature", "f_lightning_bolt")["action_template"])


def _wiz():
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["int"] = {"score": 18, "save": 0}
    return Actor(id="wiz", name="wiz",
                   template={"id": "t", "name": "wiz", "abilities": ab,
                               "cr": {"proficiency_bonus": 3}, "actions": [],
                               "spellcasting_ability": "intelligence"},
                   side="pc", hp_current=24, hp_max=24, ac=14, position=(0, 0),
                   speed={"walk": 30}, abilities=ab, spell_slots={3: 1})


def _enemy(eid, pos, dex_save=-5, hp=60):
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["dex"]["save"] = dex_save
    return Actor(id=eid, name=eid,
                   template={"id": "t", "name": eid, "abilities": ab,
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="enemy", hp_current=hp, hp_max=hp, ac=14, position=pos,
                   speed={"walk": 30}, abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class LightningBoltTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_loads(self):
        a = _action()
        self.assertEqual(a["area"]["shape"], "line")
        self.assertEqual(a["area"]["length_ft"], 100)
        self.assertEqual(a["upcast_scaling"]["extra_dice_per_level"], "1d6")

    def test_line_hits_creatures_along_direction(self):
        wiz = _wiz()
        # Two enemies along the +x axis (in the line); one off-axis
        inline1 = _enemy("inline1", (4, 0), dex_save=-10)
        inline2 = _enemy("inline2", (10, 0), dex_save=-10)
        off = _enemy("off", (4, 6), dex_save=-10)        # 30 ft off-axis
        state = _state([wiz, inline1, inline2, off])
        chosen = {"kind": "aoe_attack", "action": _action(), "target": inline1,
                    "origin_point": (0, 0), "direction": (1, 0), "actor": wiz}
        pipeline.execute(chosen, state, EventBus(), PrimitiveRegistry.with_defaults())
        save_targets = {e["target"] for e in state.event_log
                         if e.get("event") == "forced_save"}
        self.assertIn("inline1", save_targets)
        self.assertIn("inline2", save_targets)
        self.assertNotIn("off", save_targets)
        self.assertLess(inline1.hp_current, 60)


if __name__ == "__main__":
    unittest.main()
