"""Druid class + Wild Shape (form-core) + Circle of the Land (Land's Aid).

Layers:
  1. c_druid loads: WIS full-caster chassis, Wild Shape at L2, subclass L3
  2. Resource: wild_shape_uses scales 2 → 3 (L6) → 4 (L17)
  3. Actions: f_wild_shape / f_wild_shape_revert / (subclass) f_lands_aid
     auto-attach their action_templates onto the built PC
  4. wild_shape_transform primitive rides engine.core.forms: a built Druid
     Actor transforms into a real bestiary Beast (m_wolf) — physical stats
     replaced, mental kept, HP = form pool; wild_shape_revert reverts
  5. Land's Aid is an aoe_attack gated on the Wild Shape resource
     (feature_use: wild_shape_uses_remaining), not a spell slot
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core import forms
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template, derive_pc_resources
from engine.primitives import _wild_shape_transform, _wild_shape_revert

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


def _druid_spec(level=2, subclass=None, wis=16):
    spec = {"id": "druid", "class": "c_druid", "level": level,
            "ability_scores": {"str": 10, "dex": 14, "con": 14,
                                 "int": 10, "wis": wis, "cha": 10},
            "weapons": []}
    if subclass and level >= 3:
        spec["subclass"] = subclass
    return spec


def _abil(s, d, c, i, w, ch):
    return {"str": {"score": s, "save": 0}, "dex": {"score": d, "save": 0},
            "con": {"score": c, "save": 0}, "int": {"score": i, "save": 0},
            "wis": {"score": w, "save": 0}, "cha": {"score": ch, "save": 0}}


def _druid_actor(hp=15, ac=14):
    ab = _abil(10, 14, 14, 10, 16, 10)
    return Actor(id="druid", name="druid",
                  template={"id": "pc_druid", "name": "Druid",
                             "abilities": ab, "actions": [],
                             "cr": {"proficiency_bonus": 2}},
                  side="pc", hp_current=hp, hp_max=hp, ac=ac,
                  speed={"walk": 30}, position=(0, 0), abilities=ab,
                  size="medium", creature_type="humanoid")


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


# ============================================================================
# Layer 1: chassis
# ============================================================================

class ChassisTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = _registry()

    def test_druid_is_wis_full_caster(self):
        c = self.registry.get("class", "c_druid")
        self.assertEqual(c["spellcasting"]["ability"], "wisdom")
        self.assertEqual(c["spellcasting"]["slots_progression"], "full_caster")
        self.assertEqual(c["core_traits"]["hit_die"], "d8")
        self.assertEqual(c["subclass_grant_level"], 3)
        self.assertEqual(len(c["level_table"]), 20)

    def test_spellcasting_ability_stamped_wis(self):
        t = build_pc_template(_druid_spec(level=1), self.registry)
        self.assertEqual(t.get("spellcasting_ability"), "wisdom")

    def test_l2_druid_has_wild_shape_actions(self):
        t = build_pc_template(_druid_spec(level=2), self.registry)
        feats = set(t.get("features_known", []))
        self.assertIn("f_wild_shape", feats)
        self.assertIn("f_wild_shape_revert", feats)
        action_ids = {a.get("id") for a in t.get("actions", [])}
        self.assertIn("a_wild_shape", action_ids)
        self.assertIn("a_wild_shape_revert", action_ids)

    def test_l1_druid_has_no_wild_shape(self):
        t = build_pc_template(_druid_spec(level=1), self.registry)
        self.assertNotIn("f_wild_shape", set(t.get("features_known", [])))


# ============================================================================
# Layer 2: Wild Shape resource scaling
# ============================================================================

class ResourceTest(unittest.TestCase):

    def test_uses_scale_with_level(self):
        cases = {2: 2, 5: 2, 6: 3, 16: 3, 17: 4, 20: 4}
        for lvl, uses in cases.items():
            res = derive_pc_resources(_druid_spec(level=lvl), _registry())
            self.assertEqual(res.get("wild_shape_uses_remaining"), uses,
                              f"level {lvl}")
            self.assertEqual(res.get("wild_shape_uses_max"), uses,
                              f"level {lvl} max")

    def test_l1_druid_has_no_wild_shape_resource(self):
        res = derive_pc_resources(_druid_spec(level=1), _registry())
        self.assertNotIn("wild_shape_uses_remaining", res)


# ============================================================================
# Layer 3: wild_shape_transform / revert primitives ride the form core
# ============================================================================

class WildShapeTransformTest(unittest.TestCase):

    def test_transform_into_wolf_replaces_physical_keeps_mental(self):
        d = _druid_actor(hp=15, ac=14)
        st = _state([d])
        st.current_attack = {"actor": d}
        _wild_shape_transform({"form": "m_wolf"}, st, EventBus())
        self.assertTrue(forms.is_transformed(d))
        self.assertEqual(forms.active_form_id(d), "m_wolf")
        # Physical replaced with the wolf's stat block
        self.assertEqual(d.abilities["str"]["score"], 14)   # wolf STR
        self.assertEqual(d.ac, 12)                           # wolf AC
        self.assertEqual(d.hp_current, 11)                   # wolf HP pool
        self.assertEqual(d.hp_max, 11)
        self.assertEqual(d.size, "medium")
        self.assertEqual(d.creature_type, "beast")
        self.assertEqual(d.speed["walk"], 40)
        # Mental KEPT (Wild Shape policy)
        self.assertEqual(d.abilities["wis"]["score"], 16)   # druid WIS
        self.assertEqual(d.abilities["int"]["score"], 10)

    def test_transform_defaults_to_wolf(self):
        d = _druid_actor()
        st = _state([d])
        st.current_attack = {"actor": d}
        _wild_shape_transform({}, st, EventBus())   # no form param → default
        self.assertEqual(forms.active_form_id(d), "m_wolf")

    def test_revert_restores_true_form(self):
        d = _druid_actor(hp=15, ac=14)
        st = _state([d])
        st.current_attack = {"actor": d}
        _wild_shape_transform({"form": "m_wolf"}, st, EventBus())
        _wild_shape_revert({}, st, EventBus())
        self.assertFalse(forms.is_transformed(d))
        self.assertEqual(d.abilities["str"]["score"], 10)   # druid STR back
        self.assertEqual(d.ac, 14)
        self.assertEqual(d.creature_type, "humanoid")
        self.assertEqual(d.hp_current, 15)

    def test_revert_when_not_transformed_is_noop(self):
        d = _druid_actor()
        st = _state([d])
        st.current_attack = {"actor": d}
        _wild_shape_revert({}, st, EventBus())   # not transformed
        self.assertFalse(forms.is_transformed(d))


# ============================================================================
# Layer 4: Circle of the Land — Land's Aid
# ============================================================================

class CircleOfTheLandTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = _registry()

    def test_subclass_grants_lands_aid_at_l3(self):
        t = build_pc_template(
            _druid_spec(level=3, subclass="sc_circle_of_the_land"),
            self.registry)
        action_ids = {a.get("id") for a in t.get("actions", [])}
        self.assertIn("a_lands_aid", action_ids)

    def test_lands_aid_spends_wild_shape_not_a_slot(self):
        t = build_pc_template(
            _druid_spec(level=3, subclass="sc_circle_of_the_land"),
            self.registry)
        lands_aid = next(a for a in t["actions"] if a.get("id") == "a_lands_aid")
        self.assertEqual(lands_aid.get("feature_use"),
                          "wild_shape_uses_remaining")
        self.assertEqual(lands_aid.get("type"), "aoe_attack")
        # No spell slot is consumed (it rides the Wild Shape resource).
        self.assertNotIn("spell_slot_level", lands_aid)

    def test_l2_druid_has_no_lands_aid(self):
        t = build_pc_template(_druid_spec(level=2), self.registry)
        action_ids = {a.get("id") for a in t.get("actions", [])}
        self.assertNotIn("a_lands_aid", action_ids)


if __name__ == "__main__":
    unittest.main()
