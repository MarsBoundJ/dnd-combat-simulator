"""c_warlock class tests (PR #100).

Ships the Warlock primarily to ACTIVATE two spells shipped forward-
compat against a not-yet-existing class:
  - f_hex (PR #90)
  - f_armor_of_agathys (PR #96)

v1 scope (Phil's call): Pact Magic slot COUNTS + LEVELS correct, but
slots recover on LONG rest (short-rest recovery deferred). Minimal
class — no Eldritch Blast / invocations / boons / subclasses.

Layers:
  1. c_warlock loads + validates
  2. f_pact_magic marker loads
  3. PC build: L1 Warlock has 1 first-level slot + Pact Magic feature
  4. Pact Magic slot progression at key levels (all-same-level,
     concentrated counts)
  5. f_hex + f_armor_of_agathys in a L1 Warlock's features_known
  6. Both spell actions auto-attached (a_hex + a_armor_of_agathys)
  7. End-to-end: L1 Warlock can cast Hex (slot consumed, curse applied)
  8. End-to-end: L1 Warlock can cast Armor of Agathys (temp HP + marker)
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
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


def _build_warlock(registry, level):
    pc_spec = {
        "id": f"wl{level}", "class": "c_warlock", "level": level,
        "ability_scores": {"str": 8, "dex": 14, "con": 14,
                              "int": 10, "wis": 12, "cha": 16},
        "weapons": [],
    }
    return build_pc_template(pc_spec, registry)


# ============================================================================
# Layers 1+2: content loads
# ============================================================================

class ContentLoadTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_c_warlock_loads(self) -> None:
        cls = self.registry.get("class", "c_warlock")
        self.assertEqual(cls["name"], "Warlock")
        self.assertEqual(cls["core_traits"]["hit_die"], "d8")
        self.assertEqual(cls["spellcasting"]["ability"], "charisma")
        self.assertEqual(cls["spellcasting"]["slots_progression"],
                            "pact_magic")

    def test_f_pact_magic_loads(self) -> None:
        feature = self.registry.get("feature", "f_pact_magic")
        self.assertEqual(feature["granted_by"]["class"], "c_warlock")
        self.assertEqual(feature["type"], "passive")


# ============================================================================
# Layers 3+4: slot progression
# ============================================================================

class SlotProgressionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_l1_one_first_level_slot(self) -> None:
        template = _build_warlock(self.registry, 1)
        self.assertEqual(template["spell_slots"], {1: 1})

    def test_l2_two_first_level_slots(self) -> None:
        template = _build_warlock(self.registry, 2)
        self.assertEqual(template["spell_slots"], {1: 2})

    def test_l3_slots_move_to_second_level(self) -> None:
        # Pact Magic: at L3 the two slots are BOTH 2nd-level
        template = _build_warlock(self.registry, 3)
        self.assertEqual(template["spell_slots"], {2: 2})

    def test_l5_two_third_level_slots(self) -> None:
        template = _build_warlock(self.registry, 5)
        self.assertEqual(template["spell_slots"], {3: 2})

    def test_l11_three_fifth_level_slots(self) -> None:
        template = _build_warlock(self.registry, 11)
        self.assertEqual(template["spell_slots"], {5: 3})


# ============================================================================
# Layers 5+6: dormant spells activate
# ============================================================================

class SpellActivationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_l1_warlock_knows_hex_and_agathys(self) -> None:
        template = _build_warlock(self.registry, 1)
        features = template.get("features_known", [])
        self.assertIn("f_pact_magic", features)
        self.assertIn("f_hex", features)
        self.assertIn("f_armor_of_agathys", features)

    def test_l1_warlock_has_both_spell_actions(self) -> None:
        template = _build_warlock(self.registry, 1)
        action_ids = {a.get("id") for a in template.get("actions", [])}
        self.assertIn("a_hex", action_ids)
        self.assertIn("a_armor_of_agathys", action_ids)


# ============================================================================
# Layers 7+8: end-to-end casting
# ============================================================================

class EndToEndCastingTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def _warlock_actor(self, level=1):
        template = _build_warlock(self.registry, level)
        return Actor(
            id="warlock", name="warlock", template=template, side="pc",
            hp_current=20, hp_max=20, ac=12,
            speed={"walk": 30}, position=(0, 0),
            abilities=template["abilities"],
            spell_slots=dict(template.get("spell_slots") or {}),
            spell_slots_max=dict(template.get("spell_slots") or {}),
        )

    def _make_state(self, actors):
        enc = Encounter(id="t", actors=actors)
        state = CombatState(encounter=enc)
        state.turn_order = [a.id for a in actors]
        state.round = 1
        state.content_registry = self.registry
        return state

    def test_warlock_casts_hex(self) -> None:
        from engine.core import pipeline
        warlock = self._warlock_actor()
        goblin = Actor(id="goblin", name="goblin", template={
            "id": "t", "name": "goblin", "abilities": {},
            "actions": []}, side="enemy",
            hp_current=20, hp_max=20, ac=12, position=(1, 0),
            abilities={})
        state = self._make_state([warlock, goblin])
        hex_action = next(a for a in warlock.template["actions"]
                            if a.get("id") == "a_hex")
        chosen = {"kind": "offensive_buff", "action": hex_action,
                    "target": goblin, "actor": warlock}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        # Slot consumed (1 → 0)
        self.assertEqual(warlock.spell_slots.get(1, 0), 0)
        # Hex curse modifier registered on the warlock
        hex_mods = [m for m in warlock.active_modifiers
                      if (m.get("source") or {}).get("named_effect") == "hex"]
        self.assertEqual(len(hex_mods), 1)

    def test_warlock_casts_armor_of_agathys(self) -> None:
        from engine.core import pipeline
        warlock = self._warlock_actor()
        state = self._make_state([warlock])
        aoa = next(a for a in warlock.template["actions"]
                     if a.get("id") == "a_armor_of_agathys")
        chosen = {"kind": "defensive_buff", "action": aoa,
                    "target": warlock, "targets": None, "actor": warlock}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        self.assertEqual(warlock.spell_slots.get(1, 0), 0)
        # Temp HP granted + AoA marker active
        self.assertEqual(warlock.temp_hp, 5)
        markers = [m for m in warlock.active_modifiers
                     if m.get("primitive") == "armor_of_agathys_active"]
        self.assertEqual(len(markers), 1)


if __name__ == "__main__":
    unittest.main()
