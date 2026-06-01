"""Fireball tests — SRD spell batch 1.

The canonical instantaneous AoE save-burst: a 20-ft-radius sphere, DEX
save vs spell DC, 8d6 fire (half on success), +1d6 per slot above 3rd.
type `aoe_attack` with a sphere `area` block; forced_save resolves every
living creature in the sphere via `all_creatures_in_area`.

Layers:
  1. f_fireball loads with the right shape
  2. the action_template wires forced_save + half-on-success + upcast
  3. end-to-end: every creature in the sphere saves; failures take 8d6
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


def _fireball_action():
    return dict(_registry().get("feature", "f_fireball")["action_template"])


def _wizard():
    abilities = {
        "str": {"score": 10, "save": 0}, "dex": {"score": 14, "save": 0},
        "con": {"score": 12, "save": 0}, "int": {"score": 18, "save": 0},
        "wis": {"score": 10, "save": 0}, "cha": {"score": 10, "save": 0},
    }
    template = {"id": "tpl", "name": "wiz", "abilities": abilities,
                "cr": {"proficiency_bonus": 3}, "actions": [],
                "spellcasting_ability": "intelligence"}
    return Actor(id="wiz", name="wiz", template=template, side="pc",
                   hp_current=20, hp_max=20, ac=12, position=(0, 0),
                   speed={"walk": 30}, abilities=abilities,
                   spell_slots={3: 1, 4: 1})


def _enemy(eid, position, dex_save=-2, hp=60):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    abilities["dex"]["save"] = dex_save
    return Actor(id=eid, name=eid,
                   template={"id": "t", "name": eid, "abilities": abilities,
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="enemy", hp_current=hp, hp_max=hp, ac=14,
                   speed={"walk": 30}, position=position, abilities=abilities)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


# ----------------------------------------------------------------------
# Layer 1 + 2: content + wiring
# ----------------------------------------------------------------------

class WiringTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = _registry()

    def test_f_fireball_loads(self):
        feat = self.registry.get("feature", "f_fireball")
        self.assertEqual(feat["spell"]["level"], 3)
        self.assertEqual(feat["source"], "srd_5.2.1")

    def test_action_template_shape(self):
        a = _fireball_action()
        self.assertEqual(a["type"], "aoe_attack")
        self.assertEqual(a["area"]["shape"], "sphere")
        self.assertEqual(a["area"]["radius_ft"], 20)
        self.assertEqual(a["area"]["range_ft"], 150)
        self.assertFalse(a.get("concentration"))           # Fireball is instant

    def test_forced_save_is_dex_with_half_on_success(self):
        save = _fireball_action()["pipeline"][0]
        self.assertEqual(save["primitive"], "forced_save")
        self.assertEqual(save["params"]["ability"], "dexterity")
        self.assertEqual(save["params"]["affected"], "all_creatures_in_area")
        on_fail = save["params"]["on_fail"][0]["params"]
        on_succ = save["params"]["on_success"][0]["params"]
        self.assertEqual(on_fail["dice"], "8d6")
        self.assertEqual(on_fail["type"], "fire")
        self.assertEqual(on_succ["multiplier"], 0.5)       # half on success

    def test_upcast_block(self):
        a = _fireball_action()
        self.assertEqual(a["upcast_scaling"]["extra_dice_per_level"], "1d6")
        self.assertEqual(a["upcast_scaling"]["damage_type"], "fire")


# ----------------------------------------------------------------------
# Layer 3: end-to-end
# ----------------------------------------------------------------------

class EndToEndTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_all_in_sphere_save_and_failures_take_damage(self):
        wiz = _wizard()
        # Positions are grid squares (1 square = 5 ft). The 20-ft-radius
        # sphere (4 squares) is centered on (10, 0). e1 + e2 are within
        # it; `far` (40 squares = 200 ft away) is well outside.
        e1 = _enemy("e1", (10, 0), dex_save=-5)
        e2 = _enemy("e2", (12, 0), dex_save=-5)      # 2 squares = 10 ft
        far = _enemy("far", (50, 0), dex_save=-5)    # 200 ft away
        state = _state([wiz, e1, e2, far])
        chosen = {"kind": "aoe_attack", "action": _fireball_action(),
                    "target": e1, "origin_point": (10, 0), "actor": wiz}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        save_targets = {e["target"] for e in state.event_log
                         if e.get("event") == "forced_save"}
        self.assertEqual(save_targets, {"e1", "e2"})       # only in-sphere
        # Low-DEX enemies in the blast take damage
        self.assertLess(e1.hp_current, 60)
        self.assertLess(e2.hp_current, 60)
        # The far enemy never saved and never took damage
        self.assertEqual(far.hp_current, 60)

    def test_slot_consumed_on_cast(self):
        wiz = _wizard()
        e1 = _enemy("e1", (10, 0))
        state = _state([wiz, e1])
        chosen = {"kind": "aoe_attack", "action": _fireball_action(),
                    "target": e1, "origin_point": (10, 0), "actor": wiz}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        self.assertEqual(wiz.spell_slots.get(3), 0)        # 3rd-level slot spent


if __name__ == "__main__":
    unittest.main()
