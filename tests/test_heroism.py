"""Heroism tests (PR #94) — tests the dual of recurring_damage.

RAW (Bard/Paladin 1st-level, PHB 2024):
  BA cast, touch, concentration up to 1 minute. Target is Immune to
  the Frightened condition AND gains temp HP equal to your
  spellcasting ability modifier at the start of each of its turns.

v1 ships:
  - Actor.temp_hp field + _damage absorbs temp_hp first
  - _temp_hp_grant primitive with max-semantics (no stacking)
  - _recurring_temp_hp primitive + runner hook at turn_start
  - end_concentration scrubs recurring_temp_hp entries
  - apply_long_rest clears temp_hp
  - f_heroism wired into c_paladin L2

Layers:
  1. Actor.temp_hp default + temp_hp_grant primitive
  2. temp_hp_grant max-semantics (no stacking)
  3. _damage absorbs temp_hp before hp_current
  4. _damage overflow hits hp_current after temp_hp depletes
  5. _recurring_temp_hp registers entry
  6. Runner _resolve_recurring_temp_hp fires at turn_start
  7. Concentration end scrubs recurring temp HP entries
  8. apply_long_rest clears temp_hp
  9. f_heroism YAML loads + correct shape
 10. PC schema: Paladin L2 has f_heroism + action auto-attached
 11. Scoring: heroism scored via temp HP value formula
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import (
    _temp_hp_grant, _recurring_temp_hp, _damage,
)


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0), hp=30, ac=14,
                  cha_score=16, actions=None):
    abilities = {
        "str": {"score": 14, "save": 2},
        "dex": {"score": 12, "save": 1},
        "con": {"score": 14, "save": 2},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": cha_score, "save": 3},
    }
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


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Layer 1+2: temp_hp field + temp_hp_grant
# ============================================================================

class TempHpGrantTest(unittest.TestCase):

    def test_actor_temp_hp_default_zero(self) -> None:
        a = _make_actor("a1")
        self.assertEqual(a.temp_hp, 0)

    def test_grant_sets_temp_hp(self) -> None:
        caster = _make_actor("caster")
        target = _make_actor("target", side="pc")
        state = _make_state([caster, target])
        state.current_attack = {"actor": caster, "target": target,
                                  "action": {"id": "a_heroism"}}
        _temp_hp_grant({"amount": 5}, state, EventBus())
        self.assertEqual(target.temp_hp, 5)

    def test_grant_max_semantics_replaces_when_greater(self) -> None:
        target = _make_actor("target")
        target.temp_hp = 3
        caster = _make_actor("caster")
        state = _make_state([caster, target])
        state.current_attack = {"actor": caster, "target": target,
                                  "action": {"id": "a_heroism"}}
        _temp_hp_grant({"amount": 7}, state, EventBus())
        self.assertEqual(target.temp_hp, 7)

    def test_grant_max_semantics_keeps_when_lower(self) -> None:
        # RAW: gaining temp HP while you have some doesn't stack;
        # keeps the GREATER value (here: keep the 7)
        target = _make_actor("target")
        target.temp_hp = 7
        caster = _make_actor("caster")
        state = _make_state([caster, target])
        state.current_attack = {"actor": caster, "target": target,
                                  "action": {"id": "a_heroism"}}
        _temp_hp_grant({"amount": 3}, state, EventBus())
        self.assertEqual(target.temp_hp, 7)

    def test_grant_with_amount_source_reads_caster_mod(self) -> None:
        # Caster CHA 16 → mod +3
        caster = _make_actor("caster", cha_score=16)
        target = _make_actor("target", side="pc")
        state = _make_state([caster, target])
        state.current_attack = {"actor": caster, "target": target,
                                  "action": {"id": "a_heroism"}}
        _temp_hp_grant({"amount_source": "caster_spellcasting_modifier"},
                         state, EventBus())
        self.assertEqual(target.temp_hp, 3)


# ============================================================================
# Layer 3+4: _damage absorbs temp_hp before hp_current
# ============================================================================

class DamageAbsorbsTempHpTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_damage_absorbed_by_temp_hp(self) -> None:
        # Target has 5 temp HP. Takes 3 damage — all absorbed by
        # temp HP. hp_current unchanged.
        caster = _make_actor("caster", side="enemy")
        target = _make_actor("target", side="pc", hp=30)
        target.temp_hp = 5
        state = _make_state([caster, target])
        state.current_attack = {
            "actor": caster, "target": target,
            "action": {"id": "a_attack"}, "state": "hit",
        }
        _damage({"dice": "", "modifier": 3,
                   "type": "slashing"}, state, EventBus())
        self.assertEqual(target.temp_hp, 2)
        self.assertEqual(target.hp_current, 30)

    def test_damage_overflow_hits_hp(self) -> None:
        # Target has 5 temp HP, 30 HP. Takes 8 damage — 5 absorbed by
        # temp HP (depleted to 0), 3 overflow hits hp_current → 27.
        caster = _make_actor("caster", side="enemy")
        target = _make_actor("target", side="pc", hp=30)
        target.temp_hp = 5
        state = _make_state([caster, target])
        state.current_attack = {
            "actor": caster, "target": target,
            "action": {"id": "a_attack"}, "state": "hit",
        }
        _damage({"dice": "", "modifier": 8,
                   "type": "slashing"}, state, EventBus())
        self.assertEqual(target.temp_hp, 0)
        self.assertEqual(target.hp_current, 27)

    def test_damage_without_temp_hp_hits_directly(self) -> None:
        caster = _make_actor("caster", side="enemy")
        target = _make_actor("target", side="pc", hp=30)
        # temp_hp = 0 by default
        state = _make_state([caster, target])
        state.current_attack = {
            "actor": caster, "target": target,
            "action": {"id": "a_attack"}, "state": "hit",
        }
        _damage({"dice": "", "modifier": 5,
                   "type": "slashing"}, state, EventBus())
        self.assertEqual(target.hp_current, 25)


# ============================================================================
# Layer 5+6: recurring_temp_hp + runner
# ============================================================================

class RecurringTempHpTest(unittest.TestCase):

    def test_recurring_primitive_registers_entry(self) -> None:
        caster = _make_actor("caster", cha_score=16)
        target = _make_actor("target", side="pc")
        state = _make_state([caster, target])
        state.current_attack = {
            "actor": caster, "target": target,
            "action": {"id": "a_heroism"},
        }
        _recurring_temp_hp({
            "amount_source": "caster_spellcasting_modifier",
            "trigger_event": "target_turn_start",
        }, state, EventBus())
        self.assertEqual(len(state.recurring_temp_hp), 1)
        entry = state.recurring_temp_hp[0]
        self.assertEqual(entry["target_id"], "target")
        self.assertEqual(entry["amount"], 3)

    def test_runner_fires_tick_at_turn_start(self) -> None:
        from engine.core.runner import EncounterRunner
        caster = _make_actor("caster", cha_score=16)
        target = _make_actor("target", side="pc", hp=20)
        target.temp_hp = 0
        state = _make_state([caster, target])
        # Register a tick manually
        state.recurring_temp_hp.append({
            "target_id": "target", "source_id": "caster",
            "source_action_id": "a_heroism",
            "amount": 3,
            "trigger_event": "target_turn_start",
        })
        runner = EncounterRunner.new(state.encounter, seed=42)
        runner._resolve_recurring_temp_hp(target, state)
        self.assertEqual(target.temp_hp, 3)
        events = [e for e in state.event_log
                    if e.get("event") == "recurring_temp_hp_tick"]
        self.assertEqual(len(events), 1)

    def test_runner_tick_uses_max_semantics(self) -> None:
        # If target already has higher temp_hp (from another source),
        # the tick doesn't reduce it.
        from engine.core.runner import EncounterRunner
        caster = _make_actor("caster", cha_score=16)
        target = _make_actor("target", side="pc", hp=20)
        target.temp_hp = 10  # higher than the tick amount
        state = _make_state([caster, target])
        state.recurring_temp_hp.append({
            "target_id": "target", "source_id": "caster",
            "source_action_id": "a_heroism",
            "amount": 3,
            "trigger_event": "target_turn_start",
        })
        runner = EncounterRunner.new(state.encounter, seed=42)
        runner._resolve_recurring_temp_hp(target, state)
        # Stays at 10 (max-semantics keeps the higher)
        self.assertEqual(target.temp_hp, 10)


# ============================================================================
# Layer 7: concentration scrub
# ============================================================================

class ConcentrationScrubTest(unittest.TestCase):

    def test_concentration_end_scrubs_recurring_temp_hp(self) -> None:
        from engine.core.concentration import (
            apply_concentration, end_concentration)
        caster = _make_actor("caster")
        target = _make_actor("target", side="pc")
        state = _make_state([caster, target])
        apply_concentration(caster, {
            "id": "a_heroism", "concentration": True,
        }, state)
        state.recurring_temp_hp.append({
            "target_id": "target", "source_id": "caster",
            "source_action_id": "a_heroism",
            "amount": 3,
            "trigger_event": "target_turn_start",
        })
        end_concentration(caster, state, reason="test")
        self.assertEqual(len(state.recurring_temp_hp), 0)


# ============================================================================
# Layer 8: long rest clears temp_hp
# ============================================================================

class LongRestClearsTempHpTest(unittest.TestCase):

    def test_long_rest_clears_temp_hp(self) -> None:
        from engine.core.rest import apply_long_rest
        a = _make_actor("a", hp=30)
        a.hp_current = 25
        a.temp_hp = 8
        state = _make_state([a])
        summary = apply_long_rest(a, state)
        self.assertEqual(a.temp_hp, 0)
        self.assertEqual(summary.get("temp_hp_cleared"), 8)


# ============================================================================
# Layer 9+10: YAML + PC schema integration
# ============================================================================

class YamlAndSchemaTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_f_heroism_loads(self) -> None:
        feature = self.registry.get("feature", "f_heroism")
        self.assertEqual(feature["granted_by"]["class"], "c_paladin")
        self.assertEqual(feature["granted_by"]["level"], 2)
        tmpl = feature["action_template"]
        self.assertEqual(tmpl["type"], "defensive_buff")
        self.assertEqual(tmpl["spell_slot_level"], 1)
        self.assertEqual(tmpl["slot"], "bonus_action")
        self.assertTrue(tmpl["concentration"])
        self.assertEqual(tmpl["named_effect"], "heroism")
        # Pipeline has both primitives
        prims = [s["primitive"] for s in tmpl["pipeline"]]
        self.assertIn("temp_hp_grant", prims)
        self.assertIn("recurring_temp_hp", prims)

    def test_paladin_l2_has_heroism(self) -> None:
        from engine.pc_schema import build_pc_template
        pc_spec = {
            "id": "pal2", "class": "c_paladin", "level": 2,
            "ability_scores": {"str": 16, "dex": 10, "con": 14,
                                  "int": 8, "wis": 12, "cha": 16},
            "weapons": [],
        }
        template = build_pc_template(pc_spec, self.registry)
        self.assertIn("f_heroism",
                        template.get("features_known", []))
        action_ids = {a.get("id") for a in template.get("actions", [])}
        self.assertIn("a_heroism", action_ids)


# ============================================================================
# Layer 11: scoring
# ============================================================================

class ScoringTest(unittest.TestCase):

    def _heroism_action(self):
        return {
            "id": "a_heroism", "type": "defensive_buff",
            "named_effect": "heroism",
            "pipeline": [
                {"primitive": "temp_hp_grant",
                  "params": {"amount_source": "caster_spellcasting_modifier"}},
                {"primitive": "recurring_temp_hp",
                  "params": {"amount_source": "caster_spellcasting_modifier",
                              "trigger_event": "target_turn_start"}},
            ],
        }

    def test_heroism_scores_positive(self) -> None:
        from engine.ai.defensive_ehp import defensive_ehp_defensive_buff
        caster = _make_actor("caster", cha_score=16)  # +3 mod
        target = _make_actor("fighter", side="pc")
        state = _make_state([caster, target])
        score = defensive_ehp_defensive_buff(
            caster, target, self._heroism_action(), state)
        self.assertGreater(score, 0.0)

    def test_heroism_scales_with_caster_mod(self) -> None:
        from engine.ai.defensive_ehp import defensive_ehp_defensive_buff
        # Higher CHA → higher temp HP grant → higher score
        weak_caster = _make_actor("weak", cha_score=12)  # +1 mod
        strong_caster = _make_actor("strong", cha_score=20)  # +5 mod
        target_a = _make_actor("ally_a", side="pc")
        target_b = _make_actor("ally_b", side="pc")
        state_a = _make_state([weak_caster, target_a])
        state_b = _make_state([strong_caster, target_b])
        score_low = defensive_ehp_defensive_buff(
            weak_caster, target_a, self._heroism_action(), state_a)
        score_high = defensive_ehp_defensive_buff(
            strong_caster, target_b, self._heroism_action(), state_b)
        self.assertGreater(score_high, score_low)

    def test_heroism_zero_for_negative_mod_caster(self) -> None:
        from engine.ai.defensive_ehp import defensive_ehp_defensive_buff
        caster = _make_actor("caster", cha_score=8)  # -1 mod
        target = _make_actor("ally", side="pc")
        state = _make_state([caster, target])
        score = defensive_ehp_defensive_buff(
            caster, target, self._heroism_action(), state)
        self.assertEqual(score, 0.0)

    def test_heroism_zero_for_enemy_target(self) -> None:
        from engine.ai.defensive_ehp import defensive_ehp_defensive_buff
        caster = _make_actor("caster", cha_score=16)
        enemy = _make_actor("enemy", side="enemy")
        state = _make_state([caster, enemy])
        score = defensive_ehp_defensive_buff(
            caster, enemy, self._heroism_action(), state)
        self.assertEqual(score, 0.0)


if __name__ == "__main__":
    unittest.main()
