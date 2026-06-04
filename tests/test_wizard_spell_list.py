"""Wizard combat spell-list wiring (caster-lane content).

Bug: c_wizard's level_table listed no spell features, so a built Wizard
PC had an empty action set and did nothing in the boss sim. PC spells
become castable actions only when their f_* feature id is listed in a
level_table row's `features:` array (same mechanism as Bard/Cleric/Druid).
These tests assert the wired Wizard ladder builds real actions and that
each spell is gated to the character level where a full caster first gains
its slot tier (tier N → char 2N-1).

Runnability of each spell's pipeline is covered by its own spell test;
this file pins the class-list wiring + slot-level gating.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.loader import load_content
from engine.pc_schema import build_pc_template

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _pc(level):
    spec = {"class": "c_wizard", "level": level,
            "ability_scores": {"str": 8, "dex": 14, "con": 12,
                                 "int": 18, "wis": 12, "cha": 10}}
    return build_pc_template(spec, _registry())


def _action_ids(template):
    return {a.get("id") for a in template.get("actions", [])}


class WizardSpellListTest(unittest.TestCase):

    def test_l13_wizard_action_set_non_empty(self):
        # The core fix: a built Wizard must have a real action set, not [].
        ids = _action_ids(_pc(13))
        self.assertGreater(len(ids), 1, "L13 Wizard has an empty/trivial action set")

    def test_l13_wizard_has_big_gun_ladder(self):
        # High-tier nova + control + defense the L13 boss sim relies on.
        ids = _action_ids(_pc(13))
        for expected in ("a_disintegrate", "a_cone_of_cold", "a_polymorph",
                          "a_hold_monster", "a_fireball", "a_finger_of_death",
                          "a_counterspell", "a_shield", "a_wall_of_force"):
            self.assertIn(expected, ids, f"L13 Wizard missing {expected}")

    def test_cantrips_and_l1_present_from_level_1(self):
        ids = _action_ids(_pc(1))
        for expected in ("a_fire_bolt", "a_ray_of_frost", "a_chill_touch",
                          "a_magic_missile", "a_shield"):
            self.assertIn(expected, ids, f"L1 Wizard missing {expected}")

    def test_spell_absent_before_its_slot_level(self):
        # Fireball is a 3rd-level slot spell → a full caster unlocks it at
        # character level 5, not before.
        self.assertNotIn("a_fireball", _action_ids(_pc(4)))
        self.assertIn("a_fireball", _action_ids(_pc(5)))

    def test_slot_tier_gating_ladder(self):
        # Each tier unlocks at char level 2N-1; spot-check the high tiers.
        cases = [
            ("a_web", 2, 3),               # L2 slot → char 3
            ("a_polymorph", 4, 7),         # L4 slot → char 7
            ("a_hold_monster", 5, 9),      # L5 slot → char 9
            ("a_wall_of_force", 5, 9),     # L5 slot → char 9
            ("a_disintegrate", 6, 11),     # L6 slot → char 11
            ("a_finger_of_death", 7, 13),  # L7 slot → char 13
        ]
        for action_id, tier, unlock in cases:
            self.assertNotIn(action_id, _action_ids(_pc(unlock - 1)),
                              f"{action_id} (tier {tier}) present before char {unlock}")
            self.assertIn(action_id, _action_ids(_pc(unlock)),
                            f"{action_id} (tier {tier}) absent at char {unlock}")


class WizardSpellSlotsTest(unittest.TestCase):
    """The run-3 finding: the Wizard had a wired spell LIST but no spell
    SLOTS (c_wizard declared no class_resources.spell_slots), so every
    leveled spell was filtered at candidate generation and the Wizard could
    only cantrip. These pin the full-caster slot progression."""

    def test_l1_wizard_has_one_first_level_pair(self):
        self.assertEqual(_pc(1)["spell_slots"], {1: 2})

    def test_l13_wizard_has_full_caster_slots(self):
        # Standard SRD full-caster table at char 13 (incl. a 6th and 7th).
        self.assertEqual(
            _pc(13)["spell_slots"],
            {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1})

    def test_slots_match_cleric_full_caster_table(self):
        # Wizard slots must equal the (already-correct) Cleric full-caster
        # table at the same level — both are full casters.
        from engine.pc_schema import build_pc_template
        for lvl in (1, 5, 9, 11, 13, 17, 20):
            wiz = _pc(lvl)["spell_slots"]
            cleric = build_pc_template(
                {"class": "c_cleric", "level": lvl,
                 "ability_scores": {"str": 10, "dex": 10, "con": 12,
                                     "int": 10, "wis": 18, "cha": 10}},
                _registry())["spell_slots"]
            self.assertEqual(wiz, cleric, f"slot mismatch vs Cleric at L{lvl}")

    def test_high_tier_slots_arrive_on_schedule(self):
        self.assertNotIn(6, _pc(10)["spell_slots"])   # 6th-level slot: char 11
        self.assertIn(6, _pc(11)["spell_slots"])
        self.assertNotIn(7, _pc(12)["spell_slots"])   # 7th-level slot: char 13
        self.assertIn(7, _pc(13)["spell_slots"])


if __name__ == "__main__":
    unittest.main()
