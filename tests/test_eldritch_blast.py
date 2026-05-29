"""Eldritch Blast tests (PR #102).

The iconic Warlock cantrip — first RANGED SPELL ATTACK in the engine.
Ranged spell attack, 1d10 force, beams scale with CHARACTER level
(1/2/3/4 at L1/L5/L11/L17). Cantrip (no slot). Mirrors the Fighter
Extra Attack pattern: single beam always present + multiattack
wrapper at L5+.

Layers:
  1. f_eldritch_blast loads
  2. Beam-count helper (1/2/3/4 breakpoints)
  3. L1 Warlock: single a_eldritch_blast (cantrip, ranged, 1d10 force,
     spell attack bonus = CHA + PB), NO multiattack
  4. L5 Warlock: single beam + 2-beam multiattack
  5. L11 / L17 beam counts (3 / 4)
  6. Attack bonus = CHA mod + proficiency
  7. spell_slot_level 0 → casting consumes no Pact Magic slot
  8. End-to-end: L1 EB hits + deals force damage
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import (
    build_pc_template, _eldritch_blast_beams_at_level,
)
from engine.primitives import PrimitiveRegistry


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


def _registry():
    return load_content(CONTENT_ROOT, validate=True,
                          schema_root=SCHEMA_ROOT)


def _build_warlock(registry, level, cha=16):
    pc_spec = {
        "id": f"wl{level}", "class": "c_warlock", "level": level,
        "ability_scores": {"str": 8, "dex": 14, "con": 14,
                              "int": 10, "wis": 12, "cha": cha},
        "weapons": [],
    }
    return build_pc_template(pc_spec, registry)


def _eb_actions(template):
    return [a for a in template.get("actions", [])
              if a.get("id", "").startswith("a_eldritch_blast")]


# ============================================================================
# Layer 1+2: load + beam helper
# ============================================================================

class BasicsTest(unittest.TestCase):

    def test_f_eldritch_blast_loads(self) -> None:
        registry = _registry()
        feature = registry.get("feature", "f_eldritch_blast")
        self.assertEqual(feature["granted_by"]["class"], "c_warlock")

    def test_beam_count_breakpoints(self) -> None:
        self.assertEqual(_eldritch_blast_beams_at_level(1), 1)
        self.assertEqual(_eldritch_blast_beams_at_level(4), 1)
        self.assertEqual(_eldritch_blast_beams_at_level(5), 2)
        self.assertEqual(_eldritch_blast_beams_at_level(10), 2)
        self.assertEqual(_eldritch_blast_beams_at_level(11), 3)
        self.assertEqual(_eldritch_blast_beams_at_level(16), 3)
        self.assertEqual(_eldritch_blast_beams_at_level(17), 4)
        self.assertEqual(_eldritch_blast_beams_at_level(20), 4)


# ============================================================================
# Layer 3+4+5: action generation by level
# ============================================================================

class ActionGenerationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_l1_single_beam_no_multiattack(self) -> None:
        template = _build_warlock(self.registry, 1)
        eb = _eb_actions(template)
        ids = {a["id"] for a in eb}
        self.assertIn("a_eldritch_blast", ids)
        self.assertNotIn("a_eldritch_blast_beams", ids)
        beam = next(a for a in eb if a["id"] == "a_eldritch_blast")
        self.assertEqual(beam["type"], "weapon_attack")
        self.assertEqual(beam["spell_slot_level"], 0)   # cantrip
        atk = beam["pipeline"][0]["params"]
        self.assertEqual(atk["kind"], "ranged")
        self.assertEqual(atk["range_ft"], 120)
        dmg = beam["pipeline"][1]["params"]
        self.assertEqual(dmg["dice"], "1d10")
        self.assertEqual(dmg["type"], "force")

    def test_l5_two_beam_multiattack(self) -> None:
        template = _build_warlock(self.registry, 5)
        eb = _eb_actions(template)
        ids = {a["id"] for a in eb}
        self.assertIn("a_eldritch_blast", ids)
        self.assertIn("a_eldritch_blast_beams", ids)
        multi = next(a for a in eb
                       if a["id"] == "a_eldritch_blast_beams")
        self.assertEqual(multi["type"], "multiattack")
        self.assertEqual(multi["count"], 2)
        self.assertEqual(multi["sub_actions"],
                            ["a_eldritch_blast", "a_eldritch_blast"])
        self.assertEqual(multi["spell_slot_level"], 0)

    def test_l11_three_beams(self) -> None:
        template = _build_warlock(self.registry, 11)
        multi = next(a for a in _eb_actions(template)
                       if a["id"] == "a_eldritch_blast_beams")
        self.assertEqual(multi["count"], 3)

    def test_l17_four_beams(self) -> None:
        template = _build_warlock(self.registry, 17)
        multi = next(a for a in _eb_actions(template)
                       if a["id"] == "a_eldritch_blast_beams")
        self.assertEqual(multi["count"], 4)


# ============================================================================
# Layer 6+7: attack bonus + cantrip slot
# ============================================================================

class AttackBonusTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_attack_bonus_is_cha_plus_pb(self) -> None:
        # L1 Warlock, CHA 16 (+3), PB 2 → attack bonus 5
        template = _build_warlock(self.registry, 1, cha=16)
        beam = next(a for a in _eb_actions(template)
                      if a["id"] == "a_eldritch_blast")
        self.assertEqual(beam["pipeline"][0]["params"]["bonus"], 5)

    def test_attack_bonus_scales_with_cha_and_pb(self) -> None:
        # L5 Warlock (PB 3), CHA 18 (+4) → attack bonus 7
        template = _build_warlock(self.registry, 5, cha=18)
        beam = next(a for a in _eb_actions(template)
                      if a["id"] == "a_eldritch_blast")
        self.assertEqual(beam["pipeline"][0]["params"]["bonus"], 7)

    def test_eb_is_cantrip_no_slot(self) -> None:
        template = _build_warlock(self.registry, 1)
        for a in _eb_actions(template):
            self.assertEqual(a.get("spell_slot_level"), 0)


# ============================================================================
# Layer 8: end-to-end
# ============================================================================

class EndToEndTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_eb_hits_and_deals_force_damage(self) -> None:
        from engine.core import pipeline
        template = _build_warlock(self.registry, 1)
        wl = Actor(id="wl", name="wl", template=template, side="pc",
                     hp_current=20, hp_max=20, ac=12, position=(0, 0),
                     abilities=template["abilities"],
                     spell_slots=dict(template.get("spell_slots") or {}),
                     spell_slots_max=dict(template.get("spell_slots") or {}))
        # AC 1 target so the beam always hits
        goblin = Actor(id="goblin", name="goblin",
                         template={"id": "t", "name": "g",
                                     "abilities": {}, "actions": []},
                         side="enemy", hp_current=30, hp_max=30,
                         ac=1, position=(2, 0), abilities={})
        enc = Encounter(id="t", actors=[wl, goblin])
        state = CombatState(encounter=enc)
        state.turn_order = ["wl", "goblin"]
        state.round = 1
        beam = next(a for a in wl.template["actions"]
                      if a["id"] == "a_eldritch_blast")
        chosen = {"kind": "weapon_attack", "action": beam,
                    "target": goblin, "actor": wl}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        # Goblin took 1d10 force (1-10); cantrip consumed no slot
        self.assertLess(goblin.hp_current, 30)
        self.assertEqual(wl.spell_slots, {1: 1})   # slot untouched


if __name__ == "__main__":
    unittest.main()
