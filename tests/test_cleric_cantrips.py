"""Cleric save-for-damage cantrips — Sacred Flame + Toll the Dead (PR #115).

First single-target `save_attack` actions in the engine: no attack
roll, the target saves vs the caster's spell save DC or takes Nd8
damage (N scales with character level). Built by pc_schema like
Eldritch Blast; run via _execute_single; scored by
offensive_ehp_save_attack.

Layers:
  1. _cantrip_dice_count scales 1/2/3/4 at L1/5/11/17
  2. builders produce a save_attack with the right save/type/dice
  3. c_cleric L1 lists both cantrips; pc_schema attaches both actions
  4. Nd8 scales on a built Cleric (L1 → 1d8, L5 → 2d8, L11 → 3d8)
  5. extract_damage_components reads on_fail damage (the PR #115 fix)
  6. scoring: offensive_ehp_save_attack > 0; higher vs a low-save foe;
     0 vs a dead target
  7. candidate generation emits one save_attack per in-range enemy
  8. end-to-end: cast → failed save → radiant damage applied
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.ai.ehp_scoring import (
    offensive_ehp_save_attack, score_candidate,
)
from engine.core import pipeline
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import (
    build_pc_template, _cantrip_dice_count,
    _build_sacred_flame_action, _build_toll_the_dead_action,
)
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


def _foe(foe_id="foe", *, hp=30, ac=13, dex_save=0, wis_save=0,
           position=(1, 0)):
    abilities = {a: {"score": 10, "save": 0}
                   for a in ("str", "dex", "con", "int", "wis", "cha")}
    abilities["dex"] = {"score": 10, "save": dex_save}
    abilities["wis"] = {"score": 10, "save": wis_save}
    return Actor(id=foe_id, name=foe_id,
                   template={"id": "t", "name": foe_id,
                               "abilities": abilities,
                               "cr": {"proficiency_bonus": 2},
                               "actions": []},
                   side="enemy", hp_current=hp, hp_max=hp, ac=ac,
                   speed={"walk": 30}, position=position,
                   abilities=abilities)


def _cleric_actor(level=1, wis=16):
    template = _build_cleric(level, wis)
    return Actor(id="cleric", name="cleric", template=template, side="pc",
                   hp_current=24, hp_max=24, ac=16, position=(0, 0),
                   abilities=template["abilities"],
                   spell_slots=dict(template.get("spell_slots") or {})), template


# ============================================================================
# Layers 1+2: helpers + builders
# ============================================================================

class BuilderTest(unittest.TestCase):

    def test_dice_count_scaling(self) -> None:
        self.assertEqual(_cantrip_dice_count(1), 1)
        self.assertEqual(_cantrip_dice_count(4), 1)
        self.assertEqual(_cantrip_dice_count(5), 2)
        self.assertEqual(_cantrip_dice_count(11), 3)
        self.assertEqual(_cantrip_dice_count(17), 4)

    def test_sacred_flame_shape(self) -> None:
        a = _build_sacred_flame_action(1)
        self.assertEqual(a["type"], "save_attack")
        self.assertEqual(a["save_ability"], "dexterity")
        self.assertEqual(a["spell_slot_level"], 0)
        self.assertEqual(a["range_ft"], 60)
        on_fail = a["pipeline"][0]["params"]["on_fail"]
        self.assertEqual(on_fail[0]["params"]["dice"], "1d8")
        self.assertEqual(on_fail[0]["params"]["type"], "radiant")

    def test_toll_the_dead_shape(self) -> None:
        a = _build_toll_the_dead_action(5)
        self.assertEqual(a["save_ability"], "wisdom")
        on_fail = a["pipeline"][0]["params"]["on_fail"]
        self.assertEqual(on_fail[0]["params"]["dice"], "2d8")   # L5 → 2 dice
        self.assertEqual(on_fail[0]["params"]["type"], "necrotic")


# ============================================================================
# Layers 3+4: class wiring + scaling on built Cleric
# ============================================================================

class WiringTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_l1_lists_both_cantrips(self) -> None:
        l1 = next(r for r in self.registry.get("class", "c_cleric")
                    ["level_table"] if r["level"] == 1)
        self.assertIn("f_sacred_flame", l1["features"])
        self.assertIn("f_toll_the_dead", l1["features"])

    def test_both_actions_attached(self) -> None:
        ids = {a.get("id") for a in _build_cleric(1)["actions"]}
        self.assertIn("a_sacred_flame", ids)
        self.assertIn("a_toll_the_dead", ids)

    def _sacred(self, template):
        return next(a for a in template["actions"]
                      if a.get("id") == "a_sacred_flame")

    def _dice(self, action):
        return action["pipeline"][0]["params"]["on_fail"][0]["params"]["dice"]

    def test_scales_with_level(self) -> None:
        self.assertEqual(self._dice(self._sacred(_build_cleric(1))), "1d8")
        self.assertEqual(self._dice(self._sacred(_build_cleric(5))), "2d8")
        self.assertEqual(self._dice(self._sacred(_build_cleric(11))), "3d8")


# ============================================================================
# Layer 5: scorer reads on_fail damage → higher-level cantrip scores more
# ============================================================================

class LevelScalingScoreTest(unittest.TestCase):

    def test_more_dice_scores_higher(self) -> None:
        # Vs a high-HP, weak-save foe (no overkill cap), a 2d8 (L5)
        # Sacred Flame must out-score a 1d8 (L1) one — proving the
        # scorer reads the on_fail damage and the dice scale.
        cleric, _ = _cleric_actor(1, wis=16)
        foe = _foe(hp=200, dex_save=-5)
        state = _state([cleric, foe])
        s_l1 = offensive_ehp_save_attack(
            cleric, foe, _build_sacred_flame_action(1), state)
        s_l5 = offensive_ehp_save_attack(
            cleric, foe, _build_sacred_flame_action(5), state)
        self.assertGreater(s_l1, 0.0)
        self.assertGreater(s_l5, s_l1)


# ============================================================================
# Layer 6: scoring
# ============================================================================

class ScoringTest(unittest.TestCase):

    def test_positive(self) -> None:
        cleric, _ = _cleric_actor(1, wis=16)
        foe = _foe(hp=30, dex_save=0)
        state = _state([cleric, foe])
        a = _build_sacred_flame_action(1)
        self.assertGreater(
            offensive_ehp_save_attack(cleric, foe, a, state), 0.0)

    def test_higher_vs_weak_save(self) -> None:
        cleric, _ = _cleric_actor(1, wis=16)
        weak = _foe("weak", dex_save=-2, position=(1, 0))
        tough = _foe("tough", dex_save=8, position=(2, 0))
        state = _state([cleric, weak, tough])
        a = _build_sacred_flame_action(1)
        self.assertGreater(
            offensive_ehp_save_attack(cleric, weak, a, state),
            offensive_ehp_save_attack(cleric, tough, a, state))

    def test_zero_vs_dead(self) -> None:
        cleric, _ = _cleric_actor(1)
        foe = _foe(hp=0)
        foe.hp_current = 0
        state = _state([cleric, foe])
        self.assertEqual(
            offensive_ehp_save_attack(cleric, foe,
                                        _build_sacred_flame_action(1), state),
            0.0)


# ============================================================================
# Layer 7+8: candidate generation + end-to-end
# ============================================================================

class IntegrationTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_candidate_emitted_per_enemy(self) -> None:
        cleric, _ = _cleric_actor(1, wis=16)
        foe = _foe(position=(1, 0))
        state = _state([cleric, foe])
        cands = pipeline.generate_candidates(cleric, state)
        sf = [c for c in cands
                if c.get("action", {}).get("id") == "a_sacred_flame"]
        self.assertEqual(len(sf), 1)
        self.assertEqual(sf[0]["kind"], "save_attack")

    def test_end_to_end_failed_save_deals_damage(self) -> None:
        cleric, template = _cleric_actor(5, wis=18)   # high DC, 2d8
        foe = _foe(hp=40, dex_save=-5)                # near-certain fail
        state = _state([cleric, foe])
        state.content_registry = _registry()
        sf = next(a for a in template["actions"]
                    if a.get("id") == "a_sacred_flame")
        chosen = {"kind": "save_attack", "action": sf,
                    "target": foe, "actor": cleric}
        hp_before = foe.hp_current
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        self.assertLess(foe.hp_current, hp_before)   # took radiant damage

    def test_score_candidate_routes_save_attack(self) -> None:
        cleric, template = _cleric_actor(1, wis=16)
        foe = _foe(hp=30, dex_save=0)
        state = _state([cleric, foe])
        sf = next(a for a in template["actions"]
                    if a.get("id") == "a_sacred_flame")
        score = score_candidate(
            {"kind": "save_attack", "action": sf,
              "target": foe, "actor": cleric}, state)
        self.assertGreater(score, 0.0)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


if __name__ == "__main__":
    unittest.main()
