"""Rage tests (PR #71).

Layers:
  1. Level tables: rage_uses + rage_damage_bonus
  2. enter_rage / end_rage state transitions
  3. Damage rider: +rage_damage on STR melee, NOT on ranged/DEX
  4. BPS resistance on incoming damage
  5. End-of-turn auto-end (no attack + no damage → end)
  6. End-of-turn persistence (attacked OR damaged → continue)
  7. Long rest restores rage_uses
  8. STR save advantage while raging
  9. pc_schema: a_rage action wired + resources derived
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import rage as rage_module
from engine.core.events import EventBus
from engine.core.rage import (
    RAGE_USES_BY_LEVEL,
    RAGE_DAMAGE_BY_LEVEL,
    enter_rage, end_rage, is_raging,
    check_rage_end_of_turn,
    rage_uses_at_level, rage_damage_at_level,
)
from engine.core.rest import apply_long_rest
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import _attack_roll, _damage


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0),
                  level=1, hp=30, hp_max=30, ac=14, str_score=18,
                  dex_score=10, con_score=14):
    abilities = {
        "str": {"score": str_score, "save": 4 if str_score >= 18 else 2},
        "dex": {"score": dex_score, "save": 0},
        "con": {"score": con_score, "save": 2},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {
        "id": f"tpl_{actor_id}",
        "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [],
        "levels": {"barbarian": level},
    }
    return Actor(
        id=actor_id, name=actor_id, template=template,
        side=side,
        hp_current=hp, hp_max=hp_max, ac=ac,
        speed={"walk": 30}, position=position,
        abilities=abilities,
        resources={"rage_uses_remaining": rage_uses_at_level(level),
                    "rage_uses_max": rage_uses_at_level(level)},
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _set_attack_context(state, attacker, target, action):
    state.current_attack = {
        "actor": attacker, "target": target,
        "action": action, "state": None,
        "had_advantage": False, "had_disadvantage": False,
    }


# ============================================================================
# Layer 1: level tables
# ============================================================================

class RageLevelTablesTest(unittest.TestCase):

    def test_rage_uses_table_raw_values(self) -> None:
        # RAW 2024: 2/2/3/3/3/4/4/4/4/4/5/5/5/5/5/6/6/6/6/6
        self.assertEqual(rage_uses_at_level(1), 2)
        self.assertEqual(rage_uses_at_level(3), 3)
        self.assertEqual(rage_uses_at_level(6), 4)
        self.assertEqual(rage_uses_at_level(12), 5)
        self.assertEqual(rage_uses_at_level(17), 6)
        self.assertEqual(rage_uses_at_level(20), 6)

    def test_rage_damage_table_raw_values(self) -> None:
        # RAW: +2 (L1-8), +3 (L9-15), +4 (L16+)
        self.assertEqual(rage_damage_at_level(1), 2)
        self.assertEqual(rage_damage_at_level(8), 2)
        self.assertEqual(rage_damage_at_level(9), 3)
        self.assertEqual(rage_damage_at_level(15), 3)
        self.assertEqual(rage_damage_at_level(16), 4)
        self.assertEqual(rage_damage_at_level(20), 4)

    def test_zero_and_clamped_levels(self) -> None:
        self.assertEqual(rage_uses_at_level(0), 0)
        self.assertEqual(rage_damage_at_level(0), 0)
        # Clamps above 20 (defensive)
        self.assertEqual(rage_uses_at_level(25), 6)
        self.assertEqual(rage_damage_at_level(25), 4)


# ============================================================================
# Layer 2: enter / end transitions
# ============================================================================

class RageStateTransitionsTest(unittest.TestCase):

    def test_enter_rage_flips_state_and_stamps_bonus(self) -> None:
        actor = _make_actor("barb", level=5)
        state = _make_state([actor])
        self.assertFalse(is_raging(actor))
        enter_rage(actor, state)
        self.assertTrue(is_raging(actor))
        self.assertEqual(actor.rage_damage_bonus, 2)  # L5 → +2

    def test_enter_rage_stamps_bonus_for_higher_levels(self) -> None:
        actor = _make_actor("barb", level=9)
        state = _make_state([actor])
        enter_rage(actor, state)
        self.assertEqual(actor.rage_damage_bonus, 3)

        a16 = _make_actor("barb16", level=16)
        s16 = _make_state([a16])
        enter_rage(a16, s16)
        self.assertEqual(a16.rage_damage_bonus, 4)

    def test_enter_rage_emits_event(self) -> None:
        actor = _make_actor("barb")
        state = _make_state([actor])
        enter_rage(actor, state)
        events = [e for e in state.event_log
                    if e.get("event") == "rage_started"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["damage_bonus"], 2)

    def test_re_entering_rage_is_noop(self) -> None:
        actor = _make_actor("barb")
        state = _make_state([actor])
        enter_rage(actor, state)
        enter_rage(actor, state)        # second call no-ops
        events = [e for e in state.event_log
                    if e.get("event") == "rage_started"]
        self.assertEqual(len(events), 1)

    def test_end_rage_clears_state(self) -> None:
        actor = _make_actor("barb")
        state = _make_state([actor])
        enter_rage(actor, state)
        end_rage(actor, state, reason="test")
        self.assertFalse(is_raging(actor))
        self.assertEqual(actor.rage_damage_bonus, 0)
        ended = [e for e in state.event_log
                   if e.get("event") == "rage_ended"]
        self.assertEqual(len(ended), 1)
        self.assertEqual(ended[0]["reason"], "test")


# ============================================================================
# Layer 3: damage rider — +rage_damage on STR melee only
# ============================================================================

class RageDamageRiderTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_str_melee_gets_rage_bonus(self) -> None:
        attacker = _make_actor("barb", level=5)
        target = _make_actor("dummy", side="enemy", hp=50, hp_max=50)
        state = _make_state([attacker, target])
        enter_rage(attacker, state)
        # Setup: state.current_attack mirrors what pipeline does
        action = {"id": "a_greataxe", "type": "weapon_attack",
                    "pipeline": [
                        {"primitive": "attack_roll",
                         "params": {"kind": "melee", "ability": "str",
                                     "bonus": 7, "reach_ft": 5}},
                        {"primitive": "damage",
                         "params": {"dice": "1d12", "modifier": 4,
                                     "type": "slashing"}},
                    ]}
        _set_attack_context(state, attacker, target, action)
        state.current_attack["state"] = "hit"
        hp_before = target.hp_current
        _damage({"dice": "1d12", "modifier": 4, "type": "slashing"},
                state, EventBus())
        hp_lost = hp_before - target.hp_current
        # Damage = 1d12 + 4 (mod) + 2 (rage). Min 1+4+2 = 7, max 12+4+2 = 18
        self.assertGreaterEqual(hp_lost, 7)
        self.assertLessEqual(hp_lost, 18)

    def test_ranged_attack_no_rage_bonus(self) -> None:
        attacker = _make_actor("barb", level=5)
        target = _make_actor("dummy", side="enemy", hp=100, hp_max=100)
        state = _make_state([attacker, target])
        enter_rage(attacker, state)
        action = {"id": "a_longbow", "type": "weapon_attack",
                    "pipeline": [
                        {"primitive": "attack_roll",
                         "params": {"kind": "ranged", "ability": "dex",
                                     "bonus": 4, "range_ft": 150}},
                        {"primitive": "damage",
                         "params": {"dice": "1d8", "modifier": 0,
                                     "type": "piercing"}},
                    ]}
        _set_attack_context(state, attacker, target, action)
        state.current_attack["state"] = "hit"
        hp_before = target.hp_current
        _damage({"dice": "1d8", "modifier": 0, "type": "piercing"},
                state, EventBus())
        hp_lost = hp_before - target.hp_current
        # Ranged: 1d8 only. Max 8.
        self.assertLessEqual(hp_lost, 8)

    def test_dex_finesse_attack_no_rage_bonus(self) -> None:
        # RAW: rage damage applies only when attack uses STR
        attacker = _make_actor("barb", level=5)
        target = _make_actor("dummy", side="enemy", hp=100, hp_max=100)
        state = _make_state([attacker, target])
        enter_rage(attacker, state)
        action = {"id": "a_rapier", "type": "weapon_attack",
                    "pipeline": [
                        {"primitive": "attack_roll",
                         "params": {"kind": "melee", "ability": "dex",
                                     "bonus": 4, "reach_ft": 5}},
                        {"primitive": "damage",
                         "params": {"dice": "1d8", "modifier": 0,
                                     "type": "piercing"}},
                    ]}
        _set_attack_context(state, attacker, target, action)
        state.current_attack["state"] = "hit"
        hp_before = target.hp_current
        _damage({"dice": "1d8", "modifier": 0, "type": "piercing"},
                state, EventBus())
        hp_lost = hp_before - target.hp_current
        # DEX finesse: no rage bonus. Max 8.
        self.assertLessEqual(hp_lost, 8)

    def test_not_raging_no_bonus(self) -> None:
        attacker = _make_actor("barb", level=5)
        target = _make_actor("dummy", side="enemy", hp=100, hp_max=100)
        state = _make_state([attacker, target])
        # Don't rage
        action = {"id": "a_greataxe", "type": "weapon_attack",
                    "pipeline": [
                        {"primitive": "attack_roll",
                         "params": {"kind": "melee", "ability": "str",
                                     "bonus": 7, "reach_ft": 5}},
                        {"primitive": "damage",
                         "params": {"dice": "1d12", "modifier": 4,
                                     "type": "slashing"}},
                    ]}
        _set_attack_context(state, attacker, target, action)
        state.current_attack["state"] = "hit"
        hp_before = target.hp_current
        _damage({"dice": "1d12", "modifier": 4, "type": "slashing"},
                state, EventBus())
        hp_lost = hp_before - target.hp_current
        # Just 1d12 + 4. Max 16. (No rage bonus of 2.)
        self.assertLessEqual(hp_lost, 16)


# ============================================================================
# Layer 4: BPS resistance
# ============================================================================

class RageBPSResistanceTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def _hit_with(self, target, damage_type, dice="2d8", modifier=4):
        attacker = _make_actor("attacker", side="enemy")
        state = _make_state([target, attacker])
        action = {"id": "a_hit", "type": "weapon_attack", "pipeline": []}
        _set_attack_context(state, attacker, target, action)
        state.current_attack["state"] = "hit"
        hp_before = target.hp_current
        _damage({"dice": dice, "modifier": modifier, "type": damage_type},
                state, EventBus())
        return hp_before - target.hp_current

    def test_slashing_damage_halved_while_raging(self) -> None:
        target = _make_actor("barb", level=1)
        enter_rage(target, _make_state([target]))
        # Slashing 2d8+4 = 6-20 raw. Halved → 3-10.
        # Run multiple trials to assert the halving consistently applies.
        max_seen = 0
        for _ in range(20):
            dmg = self._hit_with(target, "slashing", dice="2d8", modifier=4)
            max_seen = max(max_seen, dmg)
            target.hp_current = target.hp_max  # reset
        self.assertLessEqual(max_seen, 10)   # 20 // 2 = 10

    def test_fire_damage_not_halved(self) -> None:
        target = _make_actor("barb", level=1)
        enter_rage(target, _make_state([target]))
        max_seen = 0
        for _ in range(20):
            dmg = self._hit_with(target, "fire", dice="2d8", modifier=4)
            max_seen = max(max_seen, dmg)
            target.hp_current = target.hp_max
        # Fire isn't BPS — should regularly exceed 10 across 20 rolls
        self.assertGreater(max_seen, 10)

    def test_no_resistance_when_not_raging(self) -> None:
        target = _make_actor("barb", level=1)
        # Don't rage
        max_seen = 0
        for _ in range(20):
            dmg = self._hit_with(target, "slashing", dice="2d8", modifier=4)
            max_seen = max(max_seen, dmg)
            target.hp_current = target.hp_max
        self.assertGreater(max_seen, 10)


# ============================================================================
# Layer 5+6: end-of-turn auto-end check
# ============================================================================

class RageEndOfTurnTest(unittest.TestCase):

    def test_no_attack_no_damage_ends_rage(self) -> None:
        actor = _make_actor("barb")
        state = _make_state([actor])
        enter_rage(actor, state)
        # Simulate a turn happening AFTER entry turn (advance round
        # so the entry-turn grace doesn't apply)
        state.round = 2
        # Neither flag set
        check_rage_end_of_turn(actor, state)
        self.assertFalse(is_raging(actor))
        events = [e for e in state.event_log
                    if e.get("event") == "rage_ended"]
        self.assertEqual(events[0]["reason"], "no_attack_no_damage")

    def test_attacked_hostile_keeps_rage(self) -> None:
        actor = _make_actor("barb")
        state = _make_state([actor])
        enter_rage(actor, state)
        state.round = 2
        actor._rage_attacked_hostile_this_turn = True
        check_rage_end_of_turn(actor, state)
        self.assertTrue(is_raging(actor))

    def test_damaged_keeps_rage(self) -> None:
        actor = _make_actor("barb")
        state = _make_state([actor])
        enter_rage(actor, state)
        state.round = 2
        actor._rage_damaged_this_turn = True
        check_rage_end_of_turn(actor, state)
        self.assertTrue(is_raging(actor))

    def test_entry_turn_grace_does_not_end(self) -> None:
        # Enter rage on round 1; checking at end of same turn must
        # NOT end rage even with no flags set (RAW grace: the entry
        # consumed the bonus action, give them next turn to swing)
        actor = _make_actor("barb")
        state = _make_state([actor])
        state.round = 1
        enter_rage(actor, state)
        check_rage_end_of_turn(actor, state)
        self.assertTrue(is_raging(actor))

    def test_check_noop_when_not_raging(self) -> None:
        actor = _make_actor("barb")
        state = _make_state([actor])
        # Don't enter rage
        check_rage_end_of_turn(actor, state)
        self.assertFalse(is_raging(actor))


# ============================================================================
# Layer 7: long rest restoration
# ============================================================================

class RageLongRestTest(unittest.TestCase):

    def test_long_rest_restores_rage_uses(self) -> None:
        actor = _make_actor("barb", level=5)
        # Spend two charges
        actor.resources["rage_uses_remaining"] = 1
        # Stamp the pc_schema-style derived block so apply_long_rest
        # routes to the c_barbarian branch
        actor.template["derived_from_pc_schema"] = {
            "class": "c_barbarian", "level": 5}
        state = _make_state([actor])
        summary = apply_long_rest(actor, state)
        self.assertEqual(actor.resources["rage_uses_remaining"], 3)
        self.assertIn("rage_uses_refresh", summary)
        self.assertEqual(summary["rage_uses_refresh"]["new_total"], 3)

    def test_long_rest_skips_when_no_rage_uses_max(self) -> None:
        # A non-Barbarian actor (no rage_uses_max) shouldn't get
        # rage_uses_refresh in the summary.
        actor = _make_actor("fighter", level=5)
        actor.resources = {}  # no rage resources at all
        actor.template["derived_from_pc_schema"] = {
            "class": "c_fighter", "level": 5}
        state = _make_state([actor])
        summary = apply_long_rest(actor, state)
        self.assertNotIn("rage_uses_refresh", summary)


# ============================================================================
# Layer 8: STR save advantage while raging
# ============================================================================

class RageStrSaveAdvantageTest(unittest.TestCase):

    def test_rage_gives_advantage_on_str_save(self) -> None:
        from engine.core.modifiers import query_save_modifiers
        actor = _make_actor("barb")
        state = _make_state([actor])
        enter_rage(actor, state)
        result = query_save_modifiers(actor, "strength", state)
        self.assertTrue(result.has_advantage)

    def test_no_advantage_on_dex_save(self) -> None:
        from engine.core.modifiers import query_save_modifiers
        actor = _make_actor("barb")
        state = _make_state([actor])
        enter_rage(actor, state)
        result = query_save_modifiers(actor, "dexterity", state)
        self.assertFalse(result.has_advantage)

    def test_no_advantage_when_not_raging(self) -> None:
        from engine.core.modifiers import query_save_modifiers
        actor = _make_actor("barb")
        state = _make_state([actor])
        result = query_save_modifiers(actor, "strength", state)
        self.assertFalse(result.has_advantage)


# ============================================================================
# Layer 9: pc_schema integration — a_rage action wired
# ============================================================================

class RagePcSchemaTest(unittest.TestCase):

    def test_l1_barbarian_gets_rage_resources_and_action(self) -> None:
        from pathlib import Path
        from engine.loader import load_content
        repo_root = Path(__file__).parent.parent
        from engine.pc_schema import build_pc_template, derive_pc_resources
        registry = load_content(repo_root / "schema" / "content",
                                  validate=True,
                                  schema_root=repo_root / "schema" / "definitions")
        pc_spec = {
            "id": "barb1",
            "class": "c_barbarian",
            "level": 1,
            "ability_scores": {"str": 18, "dex": 14, "con": 16,
                                 "int": 8, "wis": 10, "cha": 10},
            "weapons": [{"id": "greataxe", "name": "Greataxe",
                          "dice": "1d12", "mastery": "cleave",
                          "two_handed": True, "heavy": True,
                          "ability": "str", "type": "slashing"}],
            "weapon_masteries": ["cleave", "graze"],
        }
        template = build_pc_template(pc_spec, registry)
        resources = derive_pc_resources(pc_spec, registry)
        # Resources derived
        self.assertEqual(resources.get("rage_uses_remaining"), 2)
        self.assertEqual(resources.get("rage_uses_max"), 2)
        # a_rage action present + properly shaped
        rage_actions = [a for a in template["actions"]
                          if a.get("id") == "a_rage"]
        self.assertEqual(len(rage_actions), 1)
        rage = rage_actions[0]
        self.assertEqual(rage["slot"], "bonus_action")
        self.assertEqual(rage["feature_use"], "rage_uses_remaining")
        self.assertTrue(rage["is_signature"])
        # Levels stamped
        self.assertEqual(template["levels"]["barbarian"], 1)

    def test_l9_barbarian_scales_uses_and_damage(self) -> None:
        from pathlib import Path
        from engine.loader import load_content
        repo_root = Path(__file__).parent.parent
        from engine.pc_schema import derive_pc_resources
        registry = load_content(repo_root / "schema" / "content",
                                  validate=True,
                                  schema_root=repo_root / "schema" / "definitions")
        pc_spec = {
            "class": "c_barbarian", "level": 9,
            "ability_scores": {"str": 18, "dex": 14, "con": 16,
                                 "int": 8, "wis": 10, "cha": 10},
            "weapons": [{"id": "greataxe", "name": "Greataxe",
                          "dice": "1d12", "two_handed": True,
                          "heavy": True, "ability": "str",
                          "type": "slashing"}],
        }
        resources = derive_pc_resources(pc_spec, registry)
        # L9: 4 uses, +3 damage (verified via rage table, not directly
        # in resources — rage_damage_bonus stamps at entry time off
        # template.levels.barbarian which Barbarian uses)
        self.assertEqual(resources.get("rage_uses_remaining"), 4)


if __name__ == "__main__":
    unittest.main()
