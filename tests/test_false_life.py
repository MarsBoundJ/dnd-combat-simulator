"""False Life tests (PR #99) — one-shot self temp HP grant.

RAW (1st-level Necromancy, PHB/SRD): Action, Self, NOT concentration.
Gain 1d4+4 temp HP (v1: flat 6) for the duration. +5/upcast.

The simplest temp-HP spell — pure reuse of PR #94 temp_hp infra +
PR #96 upcast. This PR adds:
  - temp_hp_grant(target:self) / hp_max_grant(target:self) detection
    in is_self_targeted_defensive_buff (one candidate, not per-ally)
  - armor_of_agathys_arm self-detection (side cleanup — AoA now also
    emits as self-only)
  - _score_temp_hp_oneshot (flat-amount scorer), split from the
    Heroism recurring scorer

Layers:
  1. f_false_life YAML loads (self, NOT concentration)
  2. Self-targeted detection → one candidate emitted
  3. temp_hp_grant applies flat 6 to caster
  4. Upcast scales (+5/level)
  5. Scorer = amount × absorption fraction (one-shot path, NOT Heroism)
  6. Scorer dedups when caster already has >= the grant in temp HP
  7. AoA still emits as self-only (regression guard for the shared
     is_self_targeted change)
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.basic_actions import is_self_targeted_defensive_buff
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import _temp_hp_grant, PrimitiveRegistry


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


def _make_actor(actor_id, *, side="pc", position=(0, 0), hp=30, ac=14,
                  actions=None):
    abilities = {a: {"score": 12, "save": 1}
                  for a in ("str", "dex", "con", "int", "wis", "cha")}
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": list(actions or []),
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp, ac=ac,
        speed={"walk": 30}, position=position, abilities=abilities,
    )


def _false_life_action():
    return {
        "id": "a_false_life", "name": "False Life",
        "type": "defensive_buff", "spell_slot_level": 1,
        "slot": "action", "named_effect": "false_life", "range_ft": 0,
        "pipeline": [
            {"primitive": "temp_hp_grant",
              "params": {"target": "self", "amount": 6,
                          "amount_per_slot_above_base": 5}},
        ],
    }


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Layer 1: YAML
# ============================================================================

class YamlTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_f_false_life_loads(self) -> None:
        feature = self.registry.get("feature", "f_false_life")
        tmpl = feature["action_template"]
        self.assertEqual(tmpl["type"], "defensive_buff")
        self.assertEqual(tmpl["spell_slot_level"], 1)
        self.assertEqual(tmpl["slot"], "action")
        self.assertNotIn("concentration", tmpl)   # NOT concentration
        self.assertEqual(tmpl["named_effect"], "false_life")
        step = tmpl["pipeline"][0]
        self.assertEqual(step["primitive"], "temp_hp_grant")
        self.assertEqual(step["params"]["target"], "self")


# ============================================================================
# Layer 2: self-targeted detection / emission
# ============================================================================

class SelfTargetedTest(unittest.TestCase):

    def test_recognized_as_self_targeted(self) -> None:
        self.assertTrue(
            is_self_targeted_defensive_buff(_false_life_action()))

    def test_emits_one_candidate(self) -> None:
        caster = _make_actor("wiz", side="pc", position=(0, 0),
                                actions=[_false_life_action()])
        caster.spell_slots = {1: 2}
        a1 = _make_actor("a1", side="pc", position=(1, 0))
        a2 = _make_actor("a2", side="pc", position=(1, 0))
        state = _make_state([caster, a1, a2])
        candidates = pipeline.generate_candidates(caster, state,
                                                      slot="action")
        fl = [c for c in candidates
                if c.get("action", {}).get("id") == "a_false_life"]
        # Exactly one (self), not one-per-ally
        self.assertEqual(len(fl), 1)
        self.assertEqual(fl[0]["target"], caster)


# ============================================================================
# Layer 3+4: grant application
# ============================================================================

class GrantTest(unittest.TestCase):

    def test_grants_flat_temp_hp(self) -> None:
        caster = _make_actor("wiz")
        state = _make_state([caster])
        state.current_attack = {
            "actor": caster, "target": caster,
            "action": {"id": "a_false_life", "named_effect": "false_life"},
        }
        _temp_hp_grant({"target": "self", "amount": 6}, state, EventBus())
        self.assertEqual(caster.temp_hp, 6)

    def test_upcast_scales(self) -> None:
        caster = _make_actor("wiz")
        state = _make_state([caster])
        state.current_attack = {
            "actor": caster, "target": caster,
            "action": {"id": "a_false_life", "spell_slot_level": 1},
            "chosen_slot_level": 3,
        }
        _temp_hp_grant({"target": "self", "amount": 6,
                          "amount_per_slot_above_base": 5},
                         state, EventBus())
        # 6 + 2*5 = 16
        self.assertEqual(caster.temp_hp, 16)


# ============================================================================
# Layer 5+6: scoring
# ============================================================================

class ScoringTest(unittest.TestCase):

    def test_oneshot_scorer_value(self) -> None:
        from engine.ai.defensive_ehp import (
            defensive_ehp_defensive_buff, TEMP_HP_ABSORPTION_FRACTION)
        caster = _make_actor("wiz")
        state = _make_state([caster])
        score = defensive_ehp_defensive_buff(
            caster, caster, _false_life_action(), state)
        self.assertAlmostEqual(
            score, 6 * TEMP_HP_ABSORPTION_FRACTION, places=4)

    def test_dedup_when_already_has_temp_hp(self) -> None:
        from engine.ai.defensive_ehp import defensive_ehp_defensive_buff
        caster = _make_actor("wiz")
        caster.temp_hp = 10   # already higher than the 6 grant
        state = _make_state([caster])
        score = defensive_ehp_defensive_buff(
            caster, caster, _false_life_action(), state)
        self.assertEqual(score, 0.0)

    def test_oneshot_not_routed_to_heroism_scorer(self) -> None:
        # False Life has no recurring_temp_hp, so it must NOT use the
        # Heroism per-turn caster-mod formula. A 0-CHA-mod caster
        # would score 0 under Heroism but should score > 0 here.
        from engine.ai.defensive_ehp import defensive_ehp_defensive_buff
        caster = _make_actor("wiz")
        # caster has CHA 12 → +1 mod; Heroism path would give
        # 1 * 0.6 * rounds; one-shot path gives 6 * 0.6 = 3.6.
        state = _make_state([caster])
        score = defensive_ehp_defensive_buff(
            caster, caster, _false_life_action(), state)
        # One-shot value is 6 * fraction, distinctly larger than the
        # +1-mod Heroism per-tick of 0.6 * EXPECTED_BUFF_ROUNDS.
        self.assertGreater(score, 3.0)


# ============================================================================
# Layer 7: AoA still self-only (regression guard)
# ============================================================================

class AoaSelfOnlyRegressionTest(unittest.TestCase):

    def test_armor_of_agathys_recognized_self_targeted(self) -> None:
        aoa = {
            "id": "a_armor_of_agathys", "type": "defensive_buff",
            "pipeline": [
                {"primitive": "temp_hp_grant",
                  "params": {"target": "self", "amount": 5}},
                {"primitive": "armor_of_agathys_arm",
                  "params": {"cold_damage": 5}},
            ],
        }
        self.assertTrue(is_self_targeted_defensive_buff(aoa))


if __name__ == "__main__":
    unittest.main()
