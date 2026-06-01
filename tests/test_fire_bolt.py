"""Fire Bolt tests — SRD spell batch 1.

The arcane ranged-spell-attack cantrip. Like Eldritch Blast, it is a
MARKER feature built at PC-build time by pc_schema._build_fire_bolt_action
(attack bonus = INT mod + PB; damage Nd10 fire scaling with character
level). Single beam — the cantrip upgrade scales the die count, not the
attack count.

Layers:
  1. f_fire_bolt loads with the right shape (cantrip, Wizard, passive)
  2. the builder produces a_fire_bolt with the right bonus + Nd10 scaling
  3. end-to-end: the attack+damage pipeline fires against an enemy
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
from engine.pc_schema import _build_fire_bolt_action
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


def _abilities(int_score=16):
    return {
        "str": {"score": 10, "save": 0}, "dex": {"score": 14, "save": 0},
        "con": {"score": 12, "save": 0}, "int": {"score": int_score, "save": 0},
        "wis": {"score": 10, "save": 0}, "cha": {"score": 10, "save": 0},
    }


def _wizard_actor(int_score=16):
    template = {"id": "tpl_wiz", "name": "wiz", "abilities": _abilities(int_score),
                "cr": {"proficiency_bonus": 2}, "actions": [],
                "spellcasting_ability": "intelligence"}
    return Actor(id="wiz", name="wiz", template=template, side="pc",
                   hp_current=12, hp_max=12, ac=12, position=(0, 0),
                   speed={"walk": 30}, abilities=_abilities(int_score))


def _enemy(ac=5, hp=30, position=(1, 0)):
    return Actor(id="goblin", name="goblin",
                   template={"id": "t", "name": "goblin", "abilities": {},
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="enemy", hp_current=hp, hp_max=hp, ac=ac,
                   speed={"walk": 30}, position=position, abilities={})


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


# ----------------------------------------------------------------------
# Layer 1: content
# ----------------------------------------------------------------------

class WiringTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = _registry()

    def test_f_fire_bolt_loads(self):
        feat = self.registry.get("feature", "f_fire_bolt")
        self.assertEqual(feat["granted_by"]["class"], "c_wizard")
        self.assertEqual(feat["spell"]["level"], 0)        # cantrip
        self.assertEqual(feat["source"], "srd_5.2.1")
        self.assertEqual(feat["type"], "passive")          # marker feature


# ----------------------------------------------------------------------
# Layer 2: builder
# ----------------------------------------------------------------------

class BuilderTest(unittest.TestCase):

    def test_attack_bonus_tracks_int_and_pb(self):
        # INT 16 → +3, PB 2 → attack bonus +5
        a = _build_fire_bolt_action(1, _abilities(16), 2, "c_wizard")
        atk = a["pipeline"][0]
        self.assertEqual(atk["primitive"], "attack_roll")
        self.assertEqual(atk["params"]["bonus"], 5)
        self.assertEqual(atk["params"]["kind"], "ranged")
        self.assertEqual(atk["params"]["range_ft"], 120)

    def test_damage_is_fire_and_no_modifier(self):
        a = _build_fire_bolt_action(1, _abilities(16), 2, "c_wizard")
        dmg = a["pipeline"][1]["params"]
        self.assertEqual(dmg["type"], "fire")
        self.assertEqual(dmg["modifier"], 0)
        self.assertEqual(dmg["dice"], "1d10")
        self.assertEqual(a["spell_slot_level"], 0)         # no slot

    def test_die_count_scales_with_character_level(self):
        for lvl, n in [(1, 1), (5, 2), (11, 3), (17, 4)]:
            a = _build_fire_bolt_action(lvl, _abilities(16), 2, "c_wizard")
            self.assertEqual(a["pipeline"][1]["params"]["dice"], f"{n}d10")

    def test_no_multiattack_wrapper(self):
        # Unlike Eldritch Blast, Fire Bolt is always a single attack.
        a = _build_fire_bolt_action(17, _abilities(16), 2, "c_wizard")
        self.assertEqual(a["type"], "weapon_attack")
        self.assertNotIn("count", a)


# ----------------------------------------------------------------------
# Layer 3: end-to-end
# ----------------------------------------------------------------------

class EndToEndTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_fire_bolt_hits_and_damages(self):
        wiz = _wizard_actor(16)
        goblin = _enemy(ac=5, hp=30)        # low AC so the +5 attack lands
        state = _state([wiz, goblin])
        state.content_registry = _registry()
        action = _build_fire_bolt_action(1, _abilities(16), 2, "c_wizard")
        chosen = {"kind": "weapon_attack", "action": action,
                    "target": goblin, "actor": wiz}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        atk_events = [e for e in state.event_log
                       if e.get("event") == "attack_roll"
                       and e.get("target") == "goblin"]
        self.assertEqual(len(atk_events), 1)
        # With seed 1 + a +5 bonus vs AC 5 this hits and deals 1d10 fire
        self.assertLess(goblin.hp_current, 30)


if __name__ == "__main__":
    unittest.main()
