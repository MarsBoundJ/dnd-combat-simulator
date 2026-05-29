"""c_cleric tests (PR #114).

First WIS full-caster. Shipped to ACTIVATE dormant shared divine
spells — Bless + Shield of Faith (built for Paladin, PR #82) and Aid
(forward-compat, PR #97) — all genuine Cleric spells wired via the
PR #82 auto-attach pass (keys off features_known + action_template,
not granted_by).

Layers:
  1. c_cleric loads + declares a WIS spellcasting block
  2. L1 lists Bless + Shield of Faith + first slots
  3. pc_schema stamps spellcasting_ability = wisdom
  4. full-caster slots stamped (L1 {1:2}, L5 {1:4,2:3,3:2})
  5. a_bless + a_shield_of_faith auto-attach at L1
  6. a_aid auto-attaches at L3 (when 2nd-level slots arrive), not L1
  7. activation: a built Cleric's Bless scores positive on an ally
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.ai.ehp_scoring import offensive_ehp_buff_ally
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template


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


def _build_cleric(level=1, wis=16):
    pc_spec = {
        "id": f"cleric{level}", "class": "c_cleric", "level": level,
        "ability_scores": {"str": 10, "dex": 12, "con": 14,
                              "int": 10, "wis": wis, "cha": 12},
        "weapons": [{"id": "mace", "name": "Mace", "damage_dice": "1d6",
                       "damage_type": "bludgeoning", "attack_ability": "str"}],
    }
    return build_pc_template(pc_spec, _registry())


# ============================================================================
# Layers 1+2: class wiring
# ============================================================================

class ClassWiringTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_cleric_has_wis_spellcasting_block(self) -> None:
        cleric = self.registry.get("class", "c_cleric")
        sc = cleric.get("spellcasting")
        self.assertIsNotNone(sc)
        self.assertTrue(sc["enabled"])
        self.assertEqual(sc["ability"], "wisdom")

    def test_l1_lists_bless_and_shield_of_faith(self) -> None:
        cleric = self.registry.get("class", "c_cleric")
        l1 = next(r for r in cleric["level_table"] if r["level"] == 1)
        self.assertIn("f_bless", l1["features"])
        self.assertIn("f_shield_of_faith", l1["features"])
        self.assertEqual(l1["class_resources"]["spell_slots"], {1: 2})


# ============================================================================
# Layers 3+4: pc_schema stamps
# ============================================================================

class PcSchemaStampTest(unittest.TestCase):

    def test_spellcasting_ability_wisdom(self) -> None:
        self.assertEqual(_build_cleric(1).get("spellcasting_ability"),
                            "wisdom")

    def test_full_caster_slots_l1(self) -> None:
        self.assertEqual(_build_cleric(1).get("spell_slots"), {1: 2})

    def test_full_caster_slots_l5(self) -> None:
        self.assertEqual(_build_cleric(5).get("spell_slots"),
                            {1: 4, 2: 3, 3: 2})


# ============================================================================
# Layers 5+6: auto-attach
# ============================================================================

class AutoAttachTest(unittest.TestCase):

    def test_l1_has_bless_and_shield(self) -> None:
        ids = {a.get("id") for a in _build_cleric(1)["actions"]}
        self.assertIn("a_bless", ids)
        self.assertIn("a_shield_of_faith", ids)

    def test_aid_not_at_l1(self) -> None:
        ids = {a.get("id") for a in _build_cleric(1)["actions"]}
        self.assertNotIn("a_aid", ids)

    def test_aid_attaches_at_l3(self) -> None:
        ids = {a.get("id") for a in _build_cleric(3)["actions"]}
        self.assertIn("a_aid", ids)


# ============================================================================
# Layer 7: activation — Bless scores on an ally
# ============================================================================

class ActivationTest(unittest.TestCase):

    def test_cleric_bless_scores_positive(self) -> None:
        template = _build_cleric(1, wis=16)
        cleric = Actor(id="cleric", name="cleric", template=template,
                         side="pc", hp_current=24, hp_max=24, ac=16,
                         position=(0, 0), abilities=template["abilities"])
        ally = Actor(id="ally", name="ally",
                       template={"id": "t", "name": "ally",
                                   "abilities": {},
                                   "cr": {"proficiency_bonus": 2},
                                   "actions": [{"id": "a_sword",
                                       "type": "weapon_attack",
                                       "pipeline": [
                                           {"primitive": "attack_roll",
                                             "params": {"kind": "melee",
                                                          "bonus": 5}},
                                           {"primitive": "damage",
                                             "params": {"dice": "1d8",
                                                          "modifier": 3}}]}]},
                       side="pc", hp_current=30, hp_max=30, ac=16,
                       position=(1, 0), abilities={})
        enemy = Actor(id="enemy", name="enemy",
                        template={"id": "t", "name": "e", "abilities": {},
                                    "actions": []},
                        side="enemy", hp_current=30, hp_max=30, ac=14,
                        position=(2, 0), abilities={})
        enc = Encounter(id="t", actors=[cleric, ally, enemy])
        state = CombatState(encounter=enc)
        state.turn_order = ["cleric", "ally", "enemy"]
        state.round = 1
        bless = next(a for a in template["actions"]
                       if a.get("id") == "a_bless")
        self.assertGreater(
            offensive_ehp_buff_ally(cleric, ally, bless, state), 0.0)


if __name__ == "__main__":
    unittest.main()
