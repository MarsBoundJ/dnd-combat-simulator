"""Healing Word tests (PR #118).

The bonus-action ranged companion to Cure Wounds (PR #116) — the
emergency "pick an ally up from across the field" heal. Same heal-action
shape; differs in slot (bonus_action) and range (60 ft). 2d4 + WIS mod
(RAW 2024).

Layers:
  1. f_healing_word loads; c_cleric L1 lists it
  2. pc_schema builds a_healing_word (bonus_action, 60 ft, 2d4 + mod)
  3. heal amount tracks WIS (16 → +3, 10 → +0)
  4. candidate generation enumerates it on the bonus-action slot
  5. scoring: positive on wounded, 0 on full HP
  6. end-to-end: cast heals a wounded ally (clamped to max)
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.ai.defensive_ehp import defensive_ehp_healing
from engine.core import pipeline
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template, _build_healing_word_action
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


def _build_cleric(level=1, wis=16):
    return build_pc_template({
        "id": f"cleric{level}", "class": "c_cleric", "level": level,
        "ability_scores": {"str": 10, "dex": 12, "con": 14,
                              "int": 10, "wis": wis, "cha": 12},
        "weapons": [{"id": "mace", "name": "Mace", "damage_dice": "1d6",
                       "damage_type": "bludgeoning", "attack_ability": "str"}],
    }, _registry())


def _ally(ally_id="ally", *, hp=8, hp_max=30, position=(5, 0)):
    return Actor(id=ally_id, name=ally_id,
                   template={"id": "t", "name": ally_id, "abilities": {},
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="pc", hp_current=hp, hp_max=hp_max, ac=15,
                   speed={"walk": 30}, position=position, abilities={})


def _cleric_actor(level=1, wis=16):
    template = _build_cleric(level, wis)
    actor = Actor(id="cleric", name="cleric", template=template, side="pc",
                    hp_current=24, hp_max=24, ac=16, position=(0, 0),
                    abilities=template["abilities"],
                    spell_slots=dict(template.get("spell_slots") or {}))
    return actor, template


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


# ============================================================================
# Layers 1+2+3: content, wiring, builder
# ============================================================================

class WiringTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_f_healing_word_loads(self) -> None:
        feat = self.registry.get("feature", "f_healing_word")
        self.assertEqual(feat["granted_by"]["class"], "c_cleric")
        self.assertEqual(feat["spell"]["level"], 1)

    def test_l1_lists_healing_word(self) -> None:
        l1 = next(r for r in self.registry.get("class", "c_cleric")
                    ["level_table"] if r["level"] == 1)
        self.assertIn("f_healing_word", l1["features"])

    def test_action_built(self) -> None:
        ids = {a.get("id") for a in _build_cleric(1)["actions"]}
        self.assertIn("a_healing_word", ids)

    def test_shape_and_amount(self) -> None:
        a = _build_healing_word_action(1, {"wis": {"score": 16}}, "c_cleric")
        self.assertEqual(a["type"], "heal")
        self.assertEqual(a["slot"], "bonus_action")
        self.assertEqual(a["range_ft"], 60)
        heal = a["pipeline"][0]["params"]
        self.assertEqual(heal["dice"], "2d4")
        self.assertEqual(heal["modifier"], 3)            # WIS 16 → +3
        a0 = _build_healing_word_action(1, {"wis": {"score": 10}}, "c_cleric")
        self.assertEqual(a0["pipeline"][0]["params"]["modifier"], 0)


# ============================================================================
# Layer 4: candidate generation (bonus-action slot)
# ============================================================================

class CandidateTest(unittest.TestCase):

    def test_heal_candidate_on_bonus_slot(self) -> None:
        cleric, _ = _cleric_actor(1, wis=16)
        ally = _ally(hp=5, position=(5, 0))
        enemy = Actor(id="e", name="e",
                        template={"id": "t", "name": "e", "abilities": {},
                                    "actions": []},
                        side="enemy", hp_current=20, hp_max=20, ac=13,
                        speed={"walk": 30}, position=(8, 0), abilities={})
        state = _state([cleric, ally, enemy])
        cands = pipeline.generate_candidates(cleric, state,
                                                slot="bonus_action")
        hw = [c for c in cands
                if c.get("action", {}).get("id") == "a_healing_word"]
        targets = {c["target"].id for c in hw}
        self.assertIn("ally", targets)
        self.assertIn("cleric", targets)


# ============================================================================
# Layer 5: scoring
# ============================================================================

class ScoringTest(unittest.TestCase):

    def test_positive_on_wounded(self) -> None:
        cleric, template = _cleric_actor(1, wis=16)
        wounded = _ally(hp=4, hp_max=40)
        state = _state([cleric, wounded])
        hw = next(a for a in template["actions"]
                    if a.get("id") == "a_healing_word")
        self.assertGreater(
            defensive_ehp_healing(cleric, wounded, hw, state), 0.0)

    def test_zero_on_full_hp(self) -> None:
        cleric, template = _cleric_actor(1, wis=16)
        healthy = _ally(hp=40, hp_max=40)
        state = _state([cleric, healthy])
        hw = next(a for a in template["actions"]
                    if a.get("id") == "a_healing_word")
        self.assertEqual(
            defensive_ehp_healing(cleric, healthy, hw, state), 0.0)


# ============================================================================
# Layer 6: end-to-end
# ============================================================================

class EndToEndTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_cast_heals_wounded_ally(self) -> None:
        cleric, template = _cleric_actor(1, wis=16)
        wounded = _ally(hp=4, hp_max=40)
        state = _state([cleric, wounded])
        state.content_registry = _registry()
        hw = next(a for a in template["actions"]
                    if a.get("id") == "a_healing_word")
        chosen = {"kind": "heal", "action": hw,
                    "target": wounded, "actor": cleric}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        # 2d4 + 3 = 5..11 onto 4 HP (max 40, no clamp)
        self.assertGreaterEqual(wounded.hp_current, 4 + 5)
        self.assertLessEqual(wounded.hp_current, 40)


if __name__ == "__main__":
    unittest.main()
