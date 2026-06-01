"""Guiding Bolt tests — SRD spell batch 2.

Ranged-spell-attack leveled spell (4d6 radiant on hit, +1d6/slot). Like
Fire Bolt, a MARKER feature built by pc_schema with the spell attack
bonus baked at PC-build time.
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
from engine.pc_schema import _build_leveled_spell_attack_action
from engine.primitives import PrimitiveRegistry

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _abil(wis=16):
    return {k: {"score": 10, "save": 0} for k in
            ("str", "dex", "con", "int", "wis", "cha")} | {"wis": {"score": wis, "save": 0}}


def _action(level_pb=3, wis=16):
    return _build_leveled_spell_attack_action(
        "a_guiding_bolt", "Guiding Bolt", slot_level=1, range_ft=120,
        ability_scores=_abil(wis), proficiency_bonus=level_pb, class_id="c_cleric",
        damage_dice="4d6", damage_type="radiant", upcast_dice="1d6")


def _cleric():
    return Actor(id="cle", name="cle",
                   template={"id": "t", "name": "cle", "abilities": _abil(),
                               "cr": {"proficiency_bonus": 3}, "actions": [],
                               "spellcasting_ability": "wisdom"},
                   side="pc", hp_current=24, hp_max=24, ac=16, position=(0, 0),
                   speed={"walk": 30}, abilities=_abil(), spell_slots={1: 2})


def _enemy(ac=5, hp=40):
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id="undead", name="undead",
                   template={"id": "t", "name": "undead", "abilities": ab,
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="enemy", hp_current=hp, hp_max=hp, ac=ac, position=(1, 0),
                   speed={"walk": 30}, abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class GuidingBoltTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_loads(self):
        f = _registry().get("feature", "f_guiding_bolt")
        self.assertEqual(f["spell"]["level"], 1)
        self.assertEqual(f["source"], "srd_5.2.1")

    def test_builder_bonus_and_damage(self):
        a = _action()
        self.assertEqual(a["pipeline"][0]["params"]["bonus"], 3 + 3)  # WIS+3, PB 3
        self.assertEqual(a["pipeline"][1]["params"]["dice"], "4d6")
        self.assertEqual(a["pipeline"][1]["params"]["type"], "radiant")
        self.assertEqual(a["upcast_scaling"]["extra_dice_per_level"], "1d6")

    def test_hits_and_damages(self):
        cle, undead = _cleric(), _enemy(ac=5)
        state = _state([cle, undead])
        chosen = {"kind": "weapon_attack", "action": _action(),
                    "target": undead, "actor": cle}
        pipeline.execute(chosen, state, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertLess(undead.hp_current, 40)
        self.assertEqual(cle.spell_slots.get(1), 1)


if __name__ == "__main__":
    unittest.main()
