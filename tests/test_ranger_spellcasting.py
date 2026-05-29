"""Ranger spellcasting v1 tests (PR #107).

Wires the Ranger as a WIS half-caster, which activates the
forward-compat Hunter's Mark feature (f_hunters_mark, PR #91). Mirrors
the Paladin spellcasting wiring (PR #82): a spellcasting block + a
per-level half-caster spell_slots table read by pc_schema, plus
f_hunters_mark added to the L2 feature list so the auto-attach pass
generates the a_hunters_mark action.

Layers:
  1. c_ranger declares a WIS spellcasting block
  2. c_ranger L2 row lists f_hunters_mark + first spell slots
  3. pc_schema stamps spellcasting_ability = wisdom on L2+ Rangers
  4. pc_schema stamps half-caster spell_slots (L2 → {1:2}, L5 → {1:4,2:2})
  5. pc_schema auto-attaches a_hunters_mark for L2+ Rangers
  6. Ranger L1 has NO slots and NO Hunter's Mark (L2-start convention)
  7. End-to-end: a built Ranger casts Hunter's Mark → marks the target
     (registers the target-specific weapon_damage_bonus rider)
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
from engine.pc_schema import build_pc_template
from engine.primitives import PrimitiveRegistry


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


def _registry():
    return load_content(CONTENT_ROOT, validate=True,
                          schema_root=SCHEMA_ROOT)


def _build_ranger(registry, level=2, wis=16):
    pc_spec = {
        "id": f"ranger{level}", "class": "c_ranger", "level": level,
        "ability_scores": {"str": 12, "dex": 16, "con": 14,
                              "int": 10, "wis": wis, "cha": 8},
        "weapons": [{"id": "longbow", "name": "Longbow",
                       "damage_dice": "1d8", "damage_type": "piercing",
                       "attack_ability": "dex"}],
    }
    return build_pc_template(pc_spec, registry)


# ============================================================================
# Layer 1+2: class wiring
# ============================================================================

class ClassWiringTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_ranger_has_wis_spellcasting_block(self) -> None:
        ranger = self.registry.get("class", "c_ranger")
        sc = ranger.get("spellcasting")
        self.assertIsNotNone(sc)
        self.assertTrue(sc["enabled"])
        self.assertEqual(sc["ability"], "wisdom")

    def test_l2_row_lists_hunters_mark_and_slots(self) -> None:
        ranger = self.registry.get("class", "c_ranger")
        l2 = next(r for r in ranger["level_table"] if r["level"] == 2)
        self.assertIn("f_hunters_mark", l2["features"])
        self.assertEqual(l2["class_resources"]["spell_slots"], {1: 2})


# ============================================================================
# Layer 3+4+5: pc_schema stamps + auto-attach
# ============================================================================

class PcSchemaTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_spellcasting_ability_stamped_wisdom(self) -> None:
        template = _build_ranger(self.registry, level=2)
        self.assertEqual(template.get("spellcasting_ability"), "wisdom")

    def test_spell_slots_stamped_l2(self) -> None:
        template = _build_ranger(self.registry, level=2)
        self.assertEqual(template.get("spell_slots"), {1: 2})

    def test_spell_slots_stamped_l5(self) -> None:
        template = _build_ranger(self.registry, level=5)
        self.assertEqual(template.get("spell_slots"), {1: 4, 2: 2})

    def test_hunters_mark_action_attached_l2(self) -> None:
        template = _build_ranger(self.registry, level=2)
        ids = {a.get("id") for a in template["actions"]}
        self.assertIn("a_hunters_mark", ids)

    def test_hunters_mark_known_l2(self) -> None:
        template = _build_ranger(self.registry, level=2)
        self.assertIn("f_hunters_mark",
                        template.get("features_known", []))


# ============================================================================
# Layer 6: L1 Ranger has no spellcasting yet (L2-start convention)
# ============================================================================

class Level1NoCastingTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_l1_has_no_slots(self) -> None:
        template = _build_ranger(self.registry, level=1)
        self.assertEqual(template.get("spell_slots") or {}, {})

    def test_l1_has_no_hunters_mark_action(self) -> None:
        template = _build_ranger(self.registry, level=1)
        ids = {a.get("id") for a in template["actions"]}
        self.assertNotIn("a_hunters_mark", ids)


# ============================================================================
# Layer 7: end-to-end cast
# ============================================================================

class EndToEndTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_ranger_casts_hunters_mark_marks_target(self) -> None:
        template = _build_ranger(self.registry, level=5, wis=16)
        ranger = Actor(id="ranger", name="ranger", template=template,
                         side="pc", hp_current=40, hp_max=40, ac=15,
                         position=(0, 0), abilities=template["abilities"],
                         spell_slots=dict(template.get("spell_slots") or {}),
                         spell_slots_max=dict(template.get("spell_slots") or {}))
        deer = Actor(id="deer", name="deer",
                       template={"id": "t", "name": "deer",
                                   "abilities": {}, "actions": []},
                       side="enemy", hp_current=50, hp_max=50, ac=12,
                       position=(2, 0), abilities={})
        enc = Encounter(id="t", actors=[ranger, deer])
        state = CombatState(encounter=enc)
        state.turn_order = ["ranger", "deer"]
        state.round = 1
        state.content_registry = self.registry
        hm = next(a for a in template["actions"]
                    if a.get("id") == "a_hunters_mark")
        chosen = {"kind": "offensive_buff", "action": hm,
                    "target": deer, "actor": ranger}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        # The mark registers a target-specific weapon_damage_bonus on
        # the ranger gated to the deer.
        mods = [m for m in ranger.active_modifiers
                  if m.get("primitive") == "weapon_damage_bonus"]
        self.assertEqual(len(mods), 1)
        self.assertEqual(mods[0]["params"]["when"], "target_is(deer)")
        self.assertEqual(mods[0]["source"]["named_effect"],
                            "hunters_mark")


if __name__ == "__main__":
    unittest.main()
