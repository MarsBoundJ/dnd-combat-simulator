"""Armor of Agathys tests (PR #96).

RAW (Warlock/Wizard 1st-level, PHB 2024):
  Action cast, self, 1-hour, NOT concentration. 5 temp HP. If a
  creature hits you with a melee attack while you have these temp
  HP, the attacker takes 5 cold damage. Both scale +5/upcast level.

v1 ships:
  - Reuses PR #94's Actor.temp_hp + _temp_hp_grant (extended with
    amount_per_slot_above_base for upcast)
  - New _armor_of_agathys_arm primitive that registers the reflective
    marker modifier
  - _damage extension that fires reflective cold damage on melee
    hits while target has temp HP + active marker
  - Marker auto-cleared when temp HP drops to 0 from a hit
  - Recursion guard via is_agathys_reflection flag

Layers:
  1. armor_of_agathys_arm registers marker on caster
  2. arm replaces prior marker on re-cast
  3. temp_hp_grant upcast scaling (amount_per_slot_above_base)
  4. Reflective cold fires on melee hit while temp_hp > 0
  5. Reflective cold does NOT fire on ranged attack
  6. Reflective cold does NOT fire when temp_hp == 0
  7. Marker cleared when temp_hp depletes from hit
  8. Marker persists across hits while temp_hp > 0
  9. Recursion guard: attacker's own AoA doesn't infinite-loop
 10. Upcast: cold damage scales per slot level
 11. f_armor_of_agathys YAML loads with correct shape
 12. Scoring: AoA scored as defensive + offensive components
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
    _armor_of_agathys_arm, _temp_hp_grant, _damage,
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
# Layer 1+2: arm primitive
# ============================================================================

class ArmPrimitiveTest(unittest.TestCase):

    def test_arm_registers_marker_with_cold_damage(self) -> None:
        warlock = _make_actor("warlock")
        state = _make_state([warlock])
        state.current_attack = {
            "actor": warlock, "target": warlock,
            "action": {"id": "a_armor_of_agathys"},
        }
        _armor_of_agathys_arm({"cold_damage": 5}, state, EventBus())
        markers = [m for m in warlock.active_modifiers
                     if m.get("primitive") == "armor_of_agathys_active"]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["params"]["cold_damage"], 5)
        # Event logged
        events = [e for e in state.event_log
                    if e.get("event") == "armor_of_agathys_armed"]
        self.assertEqual(len(events), 1)

    def test_arm_replaces_existing_marker(self) -> None:
        # Re-cast: new amounts replace old (RAW behavior)
        warlock = _make_actor("warlock")
        state = _make_state([warlock])
        state.current_attack = {
            "actor": warlock, "target": warlock,
            "action": {"id": "a_armor_of_agathys"},
        }
        _armor_of_agathys_arm({"cold_damage": 5}, state, EventBus())
        _armor_of_agathys_arm({"cold_damage": 10}, state, EventBus())
        markers = [m for m in warlock.active_modifiers
                     if m.get("primitive") == "armor_of_agathys_active"]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["params"]["cold_damage"], 10)


# ============================================================================
# Layer 3: temp_hp_grant upcast scaling
# ============================================================================

class TempHpUpcastTest(unittest.TestCase):

    def test_amount_per_slot_above_base_scales(self) -> None:
        # Cast at slot 3 with base 1 + 5 per upcast = 5 + 2*5 = 15
        warlock = _make_actor("warlock")
        target = _make_actor("target", side="pc")
        state = _make_state([warlock, target])
        state.current_attack = {
            "actor": warlock, "target": target,
            "action": {"id": "a_aoa", "spell_slot_level": 1},
            "chosen_slot_level": 3,
        }
        _temp_hp_grant({
            "amount": 5,
            "amount_per_slot_above_base": 5,
        }, state, EventBus())
        self.assertEqual(target.temp_hp, 15)

    def test_no_upcast_when_at_base_level(self) -> None:
        warlock = _make_actor("warlock")
        target = _make_actor("target", side="pc")
        state = _make_state([warlock, target])
        state.current_attack = {
            "actor": warlock, "target": target,
            "action": {"id": "a_aoa", "spell_slot_level": 1},
            "chosen_slot_level": 1,
        }
        _temp_hp_grant({
            "amount": 5,
            "amount_per_slot_above_base": 5,
        }, state, EventBus())
        self.assertEqual(target.temp_hp, 5)


# ============================================================================
# Layer 4+5+6+7+8: reflective cold damage in _damage
# ============================================================================

class ReflectiveColdTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def _arm_with_temp_hp(self, target, *, temp_hp=5, cold=5):
        target.temp_hp = temp_hp
        target.active_modifiers.append({
            "primitive": "armor_of_agathys_active",
            "params": {"cold_damage": cold},
            "lifetime": "until_short_rest",
            "source": {"named_effect": "armor_of_agathys",
                          "caster_id": target.id,
                          "action_id": "a_armor_of_agathys"},
            "owner_id": target.id,
        })

    def test_cold_fires_on_melee_hit(self) -> None:
        warlock = _make_actor("warlock", side="pc")
        attacker = _make_actor("attacker", side="enemy", hp=30)
        self._arm_with_temp_hp(warlock, temp_hp=5, cold=5)
        state = _make_state([warlock, attacker])
        # Attacker hits warlock for 3 (absorbed by temp HP)
        state.current_attack = {
            "actor": attacker, "target": warlock,
            "action": {"id": "a_melee",
                          "pipeline": [
                              {"primitive": "attack_roll",
                                "params": {"kind": "melee", "ability": "str"}},
                              {"primitive": "damage", "params": {}},
                          ]},
            "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        attacker_hp_before = attacker.hp_current
        _damage({"dice": "", "modifier": 3,
                   "type": "slashing"}, state, EventBus())
        # Warlock's temp HP absorbed 3 → temp HP = 2
        self.assertEqual(warlock.temp_hp, 2)
        # Attacker took 5 cold from reflection
        self.assertEqual(attacker.hp_current, attacker_hp_before - 5)
        # Marker still present (temp HP not depleted)
        markers = [m for m in warlock.active_modifiers
                     if m.get("primitive") == "armor_of_agathys_active"]
        self.assertEqual(len(markers), 1)

    def test_cold_does_not_fire_on_ranged_attack(self) -> None:
        warlock = _make_actor("warlock", side="pc")
        attacker = _make_actor("attacker", side="enemy", hp=30)
        self._arm_with_temp_hp(warlock)
        state = _make_state([warlock, attacker])
        state.current_attack = {
            "actor": attacker, "target": warlock,
            "action": {"id": "a_bow",
                          "pipeline": [
                              {"primitive": "attack_roll",
                                "params": {"kind": "ranged",
                                              "ability": "dex"}},
                              {"primitive": "damage", "params": {}},
                          ]},
            "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        attacker_hp_before = attacker.hp_current
        _damage({"dice": "", "modifier": 3,
                   "type": "piercing"}, state, EventBus())
        # Attacker took no cold (RAW: melee only)
        self.assertEqual(attacker.hp_current, attacker_hp_before)

    def test_cold_does_not_fire_when_no_temp_hp(self) -> None:
        # Marker present but temp_hp = 0 → "while you have these
        # hit points" gate fails
        warlock = _make_actor("warlock", side="pc")
        attacker = _make_actor("attacker", side="enemy", hp=30)
        # Marker present but no temp HP (e.g., already depleted)
        warlock.active_modifiers.append({
            "primitive": "armor_of_agathys_active",
            "params": {"cold_damage": 5},
            "lifetime": "until_short_rest",
            "source": {"named_effect": "armor_of_agathys",
                          "caster_id": warlock.id},
            "owner_id": warlock.id,
        })
        state = _make_state([warlock, attacker])
        state.current_attack = {
            "actor": attacker, "target": warlock,
            "action": {"id": "a_melee",
                          "pipeline": [
                              {"primitive": "attack_roll",
                                "params": {"kind": "melee", "ability": "str"}},
                              {"primitive": "damage", "params": {}},
                          ]},
            "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        attacker_hp_before = attacker.hp_current
        _damage({"dice": "", "modifier": 3,
                   "type": "slashing"}, state, EventBus())
        self.assertEqual(attacker.hp_current, attacker_hp_before)

    def test_marker_cleared_when_temp_hp_depletes_from_hit(self) -> None:
        # Hit deals MORE damage than temp HP — temp HP goes to 0,
        # overflow hits HP, marker is cleared
        warlock = _make_actor("warlock", side="pc", hp=20)
        attacker = _make_actor("attacker", side="enemy", hp=30)
        self._arm_with_temp_hp(warlock, temp_hp=5, cold=5)
        state = _make_state([warlock, attacker])
        state.current_attack = {
            "actor": attacker, "target": warlock,
            "action": {"id": "a_melee",
                          "pipeline": [
                              {"primitive": "attack_roll",
                                "params": {"kind": "melee", "ability": "str"}},
                              {"primitive": "damage", "params": {}},
                          ]},
            "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        _damage({"dice": "", "modifier": 8,
                   "type": "slashing"}, state, EventBus())
        # Temp HP depleted (5), overflow 3 hit HP (20→17)
        self.assertEqual(warlock.temp_hp, 0)
        self.assertEqual(warlock.hp_current, 17)
        # Cold reflection still fired (RAW: thorns fire if temp HP
        # was > 0 at moment of hit, even if depleted by it)
        self.assertEqual(attacker.hp_current, 30 - 5)
        # Marker cleared (RAW: spell ends when temp HP depleted)
        markers = [m for m in warlock.active_modifiers
                     if m.get("primitive") == "armor_of_agathys_active"]
        self.assertEqual(len(markers), 0)
        # End event logged
        end_events = [e for e in state.event_log
                        if e.get("event") == "armor_of_agathys_ended"]
        self.assertEqual(len(end_events), 1)

    def test_marker_persists_across_partial_hits(self) -> None:
        # Two hits each within the temp HP buffer — marker stays
        warlock = _make_actor("warlock", side="pc")
        attacker = _make_actor("attacker", side="enemy", hp=100)
        self._arm_with_temp_hp(warlock, temp_hp=10, cold=5)
        state = _make_state([warlock, attacker])
        for _ in range(2):
            state.current_attack = {
                "actor": attacker, "target": warlock,
                "action": {"id": "a_melee",
                              "pipeline": [
                                  {"primitive": "attack_roll",
                                    "params": {"kind": "melee",
                                                  "ability": "str"}},
                                  {"primitive": "damage", "params": {}},
                              ]},
                "state": "hit",
                "had_advantage": False, "had_disadvantage": False,
            }
            _damage({"dice": "", "modifier": 3,
                       "type": "slashing"}, state, EventBus())
        # Two hits × 3 damage = 6 absorbed; temp HP = 4
        self.assertEqual(warlock.temp_hp, 4)
        # Two reflections × 5 cold each = 10 damage to attacker
        self.assertEqual(attacker.hp_current, 100 - 10)
        # Marker still active
        markers = [m for m in warlock.active_modifiers
                     if m.get("primitive") == "armor_of_agathys_active"]
        self.assertEqual(len(markers), 1)


# ============================================================================
# Layer 9: recursion guard
# ============================================================================

class RecursionGuardTest(unittest.TestCase):
    """Two actors both have AoA active. When one hits the other in
    melee, only ONE reflection fires (the bearer of the hit's target).
    The attacker's own AoA does NOT fire from the cold-damage
    reflection — `is_agathys_reflection` guards against this."""

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_no_infinite_loop_when_both_have_aoa(self) -> None:
        warlock_a = _make_actor("a", side="pc")
        warlock_b = _make_actor("b", side="enemy", hp=30)
        # Both have AoA active with 5 temp HP each
        for w in (warlock_a, warlock_b):
            w.temp_hp = 5
            w.active_modifiers.append({
                "primitive": "armor_of_agathys_active",
                "params": {"cold_damage": 5},
                "lifetime": "until_short_rest",
                "source": {"named_effect": "armor_of_agathys",
                              "caster_id": w.id},
                "owner_id": w.id,
            })
        state = _make_state([warlock_a, warlock_b])
        # A hits B in melee for 3 damage
        state.current_attack = {
            "actor": warlock_a, "target": warlock_b,
            "action": {"id": "a_melee",
                          "pipeline": [
                              {"primitive": "attack_roll",
                                "params": {"kind": "melee", "ability": "str"}},
                              {"primitive": "damage", "params": {}},
                          ]},
            "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        _damage({"dice": "", "modifier": 3,
                   "type": "slashing"}, state, EventBus())
        # B's temp HP absorbed 3 → 2 remaining
        self.assertEqual(warlock_b.temp_hp, 2)
        # B's AoA fired 5 cold at A. A's temp HP absorbed 5 → 0
        self.assertEqual(warlock_a.temp_hp, 0)
        # A's AoA did NOT fire back at B (recursion guard) — B's HP
        # only took the initial 3 to temp HP, no extra cold from A
        # Cold reflections counted: should be exactly 1
        reflections = [e for e in state.event_log
                         if e.get("event")
                            == "armor_of_agathys_reflected"]
        self.assertEqual(len(reflections), 1)


# ============================================================================
# Layer 10: upcast scaling end-to-end
# ============================================================================

class UpcastE2eTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_cast_at_slot_3_scales_temp_hp_and_cold(self) -> None:
        warlock = _make_actor("warlock", side="pc")
        attacker = _make_actor("attacker", side="enemy", hp=50)
        # Simulate the cast at slot 3: pipeline runs temp_hp_grant
        # + armor_of_agathys_arm with chosen_slot_level=3
        state = _make_state([warlock, attacker])
        state.current_attack = {
            "actor": warlock, "target": warlock,
            "action": {"id": "a_armor_of_agathys",
                          "spell_slot_level": 1},
            "chosen_slot_level": 3,
        }
        _temp_hp_grant({"amount": 5,
                          "amount_per_slot_above_base": 5},
                         state, EventBus())
        _armor_of_agathys_arm({"cold_damage": 5,
                                  "cold_damage_per_slot_above_base": 5},
                                 state, EventBus())
        # 5 + 2*5 = 15 temp HP, 5 + 2*5 = 15 cold
        self.assertEqual(warlock.temp_hp, 15)
        marker = next(m for m in warlock.active_modifiers
                          if m.get("primitive") == "armor_of_agathys_active")
        self.assertEqual(marker["params"]["cold_damage"], 15)
        # Hit with 5 melee damage → temp_hp 15→10, attacker takes 15 cold
        state.current_attack = {
            "actor": attacker, "target": warlock,
            "action": {"id": "a_melee",
                          "pipeline": [
                              {"primitive": "attack_roll",
                                "params": {"kind": "melee", "ability": "str"}},
                              {"primitive": "damage", "params": {}},
                          ]},
            "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        _damage({"dice": "", "modifier": 5,
                   "type": "slashing"}, state, EventBus())
        self.assertEqual(warlock.temp_hp, 10)
        self.assertEqual(attacker.hp_current, 50 - 15)


# ============================================================================
# Layer 11: YAML loads
# ============================================================================

class YamlTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_f_armor_of_agathys_loads(self) -> None:
        feature = self.registry.get("feature", "f_armor_of_agathys")
        self.assertEqual(feature["granted_by"]["class"], "c_warlock")
        self.assertEqual(feature["granted_by"]["level"], 1)
        tmpl = feature["action_template"]
        self.assertEqual(tmpl["type"], "defensive_buff")
        self.assertEqual(tmpl["spell_slot_level"], 1)
        self.assertEqual(tmpl["slot"], "action")
        # AoA is NOT concentration per RAW
        self.assertNotIn("concentration", tmpl)
        self.assertEqual(tmpl["named_effect"], "armor_of_agathys")
        # Pipeline has temp_hp_grant + armor_of_agathys_arm
        prims = [s["primitive"] for s in tmpl["pipeline"]]
        self.assertIn("temp_hp_grant", prims)
        self.assertIn("armor_of_agathys_arm", prims)


# ============================================================================
# Layer 12: scoring
# ============================================================================

class ScoringTest(unittest.TestCase):

    def _aoa_action(self):
        return {
            "id": "a_armor_of_agathys", "type": "defensive_buff",
            "named_effect": "armor_of_agathys",
            "spell_slot_level": 1,
            "pipeline": [
                {"primitive": "temp_hp_grant",
                  "params": {"amount": 5,
                              "amount_per_slot_above_base": 5}},
                {"primitive": "armor_of_agathys_arm",
                  "params": {"cold_damage": 5,
                              "cold_damage_per_slot_above_base": 5}},
            ],
        }

    def test_aoa_scores_positive(self) -> None:
        from engine.ai.defensive_ehp import defensive_ehp_defensive_buff
        warlock = _make_actor("warlock")
        state = _make_state([warlock])
        score = defensive_ehp_defensive_buff(
            warlock, warlock, self._aoa_action(), state)
        # 5 temp HP × 1.0 + 5 cold × 1.5 = 5 + 7.5 = 12.5
        self.assertGreater(score, 10.0)

    def test_aoa_zero_when_already_active(self) -> None:
        from engine.ai.defensive_ehp import defensive_ehp_defensive_buff
        warlock = _make_actor("warlock")
        warlock.active_modifiers.append({
            "primitive": "armor_of_agathys_active",
            "params": {"cold_damage": 5},
        })
        state = _make_state([warlock])
        score = defensive_ehp_defensive_buff(
            warlock, warlock, self._aoa_action(), state)
        self.assertEqual(score, 0.0)


if __name__ == "__main__":
    unittest.main()
