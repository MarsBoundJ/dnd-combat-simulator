"""Elemental Affinity — Draconic Sorcery L6 +CHA damage rider.

Covers the draconic_sorcery.elemental_affinity_bonus helper (type match,
once-per-cast dedup, feature/threshold guards), its integration through
the `damage` primitive, and the PC-build wiring (template stamp).
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import draconic_sorcery as drac
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template
from engine.primitives import _damage

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


def _abilities():
    return {k: {"score": 10, "save": 0}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _sorc(element="fire", cha_mod=4, hp=60):
    tmpl = {"id": "t", "name": "sorc", "abilities": _abilities(),
            "cr": {"proficiency_bonus": 3},
            "features_known": ["f_elemental_affinity"],
            "elemental_affinity": {"element": element, "cha_mod": cha_mod}}
    return Actor(id="sorc", name="sorc", template=tmpl, side="pc",
                  hp_current=hp, hp_max=hp, ac=12, speed={"walk": 30},
                  position=(0, 0), abilities=_abilities())


def _foe(hp=400):
    return Actor(id="foe", name="foe", template={"abilities": {}},
                  side="enemy", hp_current=hp, hp_max=hp, ac=10,
                  speed={"walk": 30}, position=(1, 0), abilities=_abilities())


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [x.id for x in actors]
    st.round = 1
    return st


class HelperTest(unittest.TestCase):
    def test_matching_type_adds_cha_mod_once_per_cast(self):
        sorc, foe = _sorc(), _foe()
        st = _state([sorc, foe])
        st.current_attack = {"actor": sorc, "target": foe, "action": {"id": "x"}}
        self.assertEqual(drac.elemental_affinity_bonus(sorc, "fire", st), 4)
        # Once per cast: a second matching damage roll in the same cast adds 0.
        self.assertEqual(drac.elemental_affinity_bonus(sorc, "fire", st), 0)

    def test_mismatched_type_adds_zero(self):
        sorc, foe = _sorc(element="fire"), _foe()
        st = _state([sorc, foe])
        st.current_attack = {"actor": sorc, "target": foe, "action": {"id": "x"}}
        self.assertEqual(drac.elemental_affinity_bonus(sorc, "cold", st), 0)

    def test_no_feature_adds_zero(self):
        plain = Actor(id="p", name="p",
                       template={"id": "t", "abilities": _abilities()},
                       side="pc", hp_current=10, hp_max=10, ac=10,
                       abilities=_abilities())
        foe = _foe()
        st = _state([plain, foe])
        st.current_attack = {"actor": plain, "target": foe, "action": {"id": "x"}}
        self.assertEqual(drac.elemental_affinity_bonus(plain, "fire", st), 0)


class DamageIntegrationTest(unittest.TestCase):
    def _roll(self, element_on_spell):
        primitives_module.set_rng(random.Random(5))
        sorc, foe = _sorc(element="fire", cha_mod=4), _foe()
        st = _state([sorc, foe])
        st.current_attack = {"actor": sorc, "target": foe,
                              "action": {"id": "a_fireball"}, "state": "hit"}
        hp = foe.hp_current
        _damage({"dice": "8d6", "type": element_on_spell}, st, EventBus())
        return hp - foe.hp_current

    def test_fire_spell_beats_cold_spell_by_cha_mod(self):
        # Same seed → identical dice; the only delta is the +4 fire rider.
        cold = self._roll("cold")
        fire = self._roll("fire")
        self.assertEqual(fire - cold, 4)


class PCBuildWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                     schema_root=SCHEMA_ROOT)

    def test_draconic_sorcerer_l6_stamps_elemental_affinity(self):
        pc = {"id": "s", "class": "c_sorcerer", "level": 6,
              "subclass": "sc_draconic_sorcery", "draconic_element": "fire",
              "ability_scores": {"str": 8, "dex": 14, "con": 14,
                                  "int": 10, "wis": 10, "cha": 18},
              "weapons": []}
        tmpl = build_pc_template(pc, self.registry)
        ea = tmpl.get("elemental_affinity")
        self.assertIsNotNone(ea)
        self.assertEqual(ea["element"], "fire")
        self.assertEqual(ea["cha_mod"], 4)         # CHA 18 → +4
        self.assertIn("fire", tmpl.get("damage_resistances", []))


if __name__ == "__main__":
    unittest.main()
