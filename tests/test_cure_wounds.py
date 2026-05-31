"""Cure Wounds tests (PR #116).

The Cleric's iconic heal — the first leveled heal action (Lay on Hands
is a Paladin pool). type `heal`, built by pc_schema with 2d8 + the
caster's spellcasting-ability mod; enumerated per ally and scored by
defensive_ehp_healing.

Layers:
  1. f_cure_wounds loads; c_cleric L1 lists it
  2. pc_schema builds a_cure_wounds for a Cleric (2d8 + WIS mod)
  3. modifier tracks WIS (16 → +3, 10 → +0)
  4. candidate generation enumerates the heal per ally
  5. scoring: positive on a wounded ally, 0 on a full-HP ally
  6. end-to-end: cast heals a wounded ally (clamped to max HP)
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
from engine.pc_schema import build_pc_template, _build_cure_wounds_action
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


def _ally(ally_id="ally", *, hp=10, hp_max=30, position=(1, 0)):
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

    def test_f_cure_wounds_loads(self) -> None:
        feat = self.registry.get("feature", "f_cure_wounds")
        self.assertEqual(feat["granted_by"]["class"], "c_cleric")
        self.assertEqual(feat["spell"]["level"], 1)

    def test_l1_lists_cure_wounds(self) -> None:
        l1 = next(r for r in self.registry.get("class", "c_cleric")
                    ["level_table"] if r["level"] == 1)
        self.assertIn("f_cure_wounds", l1["features"])

    def test_action_built_for_cleric(self) -> None:
        ids = {a.get("id") for a in _build_cleric(1)["actions"]}
        self.assertIn("a_cure_wounds", ids)

    def test_heal_amount_tracks_wis(self) -> None:
        # WIS 16 → +3
        a = _build_cure_wounds_action(
            1, {"wis": {"score": 16}}, "c_cleric")
        heal = a["pipeline"][0]["params"]
        self.assertEqual(heal["dice"], "2d8")
        self.assertEqual(heal["modifier"], 3)
        self.assertEqual(a["type"], "heal")
        # WIS 10 → +0
        a0 = _build_cure_wounds_action(
            1, {"wis": {"score": 10}}, "c_cleric")
        self.assertEqual(a0["pipeline"][0]["params"]["modifier"], 0)


# ============================================================================
# Layer 4: candidate generation
# ============================================================================

class CandidateTest(unittest.TestCase):

    def test_heal_candidate_per_ally(self) -> None:
        cleric, _ = _cleric_actor(1, wis=16)
        ally = _ally(hp=5, position=(1, 0))
        enemy = Actor(id="e", name="e",
                        template={"id": "t", "name": "e", "abilities": {},
                                    "actions": []},
                        side="enemy", hp_current=20, hp_max=20, ac=13,
                        speed={"walk": 30}, position=(3, 0), abilities={})
        state = _state([cleric, ally, enemy])
        cands = pipeline.generate_candidates(cleric, state)
        cw = [c for c in cands
                if c.get("action", {}).get("id") == "a_cure_wounds"]
        # One per ally (cleric + wounded ally = 2)
        targets = {c["target"].id for c in cw}
        self.assertIn("ally", targets)
        self.assertIn("cleric", targets)


# ============================================================================
# Layer 5: scoring
# ============================================================================

class ScoringTest(unittest.TestCase):

    def test_positive_on_wounded(self) -> None:
        cleric, template = _cleric_actor(1, wis=16)
        wounded = _ally(hp=5, hp_max=40)
        state = _state([cleric, wounded])
        cw = next(a for a in template["actions"]
                    if a.get("id") == "a_cure_wounds")
        self.assertGreater(
            defensive_ehp_healing(cleric, wounded, cw, state), 0.0)

    def test_zero_on_full_hp(self) -> None:
        cleric, template = _cleric_actor(1, wis=16)
        healthy = _ally(hp=40, hp_max=40)
        state = _state([cleric, healthy])
        cw = next(a for a in template["actions"]
                    if a.get("id") == "a_cure_wounds")
        self.assertEqual(
            defensive_ehp_healing(cleric, healthy, cw, state), 0.0)

    def test_wounded_scores_higher_than_lightly_hurt(self) -> None:
        cleric, template = _cleric_actor(1, wis=16)
        dying = _ally("dying", hp=3, hp_max=40, position=(1, 0))
        scratched = _ally("scratched", hp=35, hp_max=40, position=(2, 0))
        state = _state([cleric, dying, scratched])
        cw = next(a for a in template["actions"]
                    if a.get("id") == "a_cure_wounds")
        self.assertGreater(
            defensive_ehp_healing(cleric, dying, cw, state),
            defensive_ehp_healing(cleric, scratched, cw, state))


# ============================================================================
# Layer 6: end-to-end
# ============================================================================

class EndToEndTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_cast_heals_wounded_ally(self) -> None:
        cleric, template = _cleric_actor(1, wis=16)
        wounded = _ally(hp=5, hp_max=40)
        state = _state([cleric, wounded])
        state.content_registry = _registry()
        cw = next(a for a in template["actions"]
                    if a.get("id") == "a_cure_wounds")
        chosen = {"kind": "heal", "action": cw,
                    "target": wounded, "actor": cleric}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        # 2d8 + 3 = 5..19 healing onto 5 HP (max 40, no clamp)
        self.assertGreaterEqual(wounded.hp_current, 5 + 5)
        self.assertLessEqual(wounded.hp_current, 40)

    def test_heal_clamps_to_max(self) -> None:
        cleric, template = _cleric_actor(1, wis=16)
        nearly_full = _ally(hp=39, hp_max=40)
        state = _state([cleric, nearly_full])
        state.content_registry = _registry()
        cw = next(a for a in template["actions"]
                    if a.get("id") == "a_cure_wounds")
        chosen = {"kind": "heal", "action": cw,
                    "target": nearly_full, "actor": cleric}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        self.assertEqual(nearly_full.hp_current, 40)   # clamped


if __name__ == "__main__":
    unittest.main()
