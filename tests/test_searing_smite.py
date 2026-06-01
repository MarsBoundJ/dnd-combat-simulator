"""Searing Smite tests (PR #89).

RAW (PHB 2024, 1st-level Paladin spell):
  BA cast, concentration up to 1 minute. Next melee weapon hit deals
  +1d6 fire (+1d6 per upcast level) AND target makes CON save or is
  Ignited (1d6 fire per turn until concentration ends).

Layers:
  1. recurring_damage primitive registers entry in state.recurring_damage
  2. runner._resolve_recurring_damage fires at turn-start + deals damage
  3. concentration-end scrubs recurring_damage entries
  4. searing_smite.register_armed / find_armed_entry / clear_armed
  5. try_apply_searing_smite_followup gating: only melee, only when armed
  6. try_apply_searing_smite_followup applies damage + condition on fail
  7. _damage hooks Searing Smite on melee weapon hits
  8. co_ignited condition: applies recurring_damage on instantiation
  9. f_searing_smite YAML loads with correct shape
 10. PC schema: Paladin L2 has f_searing_smite + emits a_searing_smite
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import searing_smite as ss
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import (
    _recurring_damage, _searing_smite_arm, _damage,
    PrimitiveRegistry,
)


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0), hp=30, ac=14,
                  cha_score=16, levels=None, actions=None):
    abilities = {
        "str": {"score": 16, "save": 3},
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
        "levels": dict(levels or {"paladin": 2}),
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp, ac=ac,
        speed={"walk": 30}, position=position, abilities=abilities,
    )


def _melee_weapon(action_id="a_longsword"):
    return {
        "id": action_id, "type": "weapon_attack", "slot": "action",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "ability": "str",
                          "bonus": 5, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": "1d8", "modifier": 3,
                          "type": "slashing"}},
        ],
    }


def _make_state(actors, with_registry=True):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    if with_registry:
        state.content_registry = load_content(
            CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
    return state


# ============================================================================
# Layer 1: recurring_damage primitive
# ============================================================================

class RecurringDamagePrimitiveTest(unittest.TestCase):

    def test_primitive_registers_entry(self) -> None:
        paladin = _make_actor("paladin")
        target = _make_actor("dummy", side="enemy")
        state = _make_state([paladin, target], with_registry=False)
        state.current_attack = {"actor": paladin, "target": target,
                                  "action": {"id": "a_searing_smite"}}
        _recurring_damage({
            "dice": "1d6", "type": "fire",
            "trigger_event": "target_turn_start",
            "condition_id": "co_ignited",
        }, state, EventBus())
        self.assertEqual(len(state.recurring_damage), 1)
        entry = state.recurring_damage[0]
        self.assertEqual(entry["target_id"], "dummy")
        self.assertEqual(entry["source_id"], "paladin")
        self.assertEqual(entry["dice"], "1d6")
        self.assertEqual(entry["damage_type"], "fire")


# ============================================================================
# Layer 2+3: runner integration + concentration scrub
# ============================================================================

class RecurringDamageRunnerIntegrationTest(unittest.TestCase):

    def test_tick_fires_at_turn_start(self) -> None:
        from engine.core.runner import EncounterRunner
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=30)
        # Register a tick manually
        state = _make_state([paladin, target], with_registry=False)
        state.recurring_damage.append({
            "target_id": "goblin", "source_id": "paladin",
            "source_action_id": "a_searing_smite",
            "dice": "1d6", "damage_type": "fire",
            "trigger_event": "target_turn_start",
            "applied_at_round": 1,
        })
        runner = EncounterRunner.new(state.encounter, seed=42)
        # Fire the resolver directly
        runner._resolve_recurring_damage(target, state)
        # Goblin should have taken damage
        self.assertLess(target.hp_current, 30)
        events = [e for e in state.event_log
                    if e.get("event") == "recurring_damage_tick"]
        self.assertEqual(len(events), 1)

    def test_concentration_end_scrubs_recurring_damage(self) -> None:
        from engine.core.concentration import (
            apply_concentration, end_concentration)
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy")
        state = _make_state([paladin, target], with_registry=False)
        # Set up concentration + recurring_damage entry tied to it
        apply_concentration(paladin, {
            "id": "a_searing_smite", "concentration": True,
        }, state)
        state.recurring_damage.append({
            "target_id": "goblin", "source_id": "paladin",
            "source_action_id": "a_searing_smite",
            "dice": "1d6", "damage_type": "fire",
            "trigger_event": "target_turn_start",
        })
        self.assertEqual(len(state.recurring_damage), 1)
        end_concentration(paladin, state, reason="test")
        # Entry should be scrubbed
        self.assertEqual(len(state.recurring_damage), 0)


# ============================================================================
# Layer 4: register_armed / find / clear
# ============================================================================

class ArmedMarkerTest(unittest.TestCase):

    def test_register_armed_creates_modifier(self) -> None:
        paladin = _make_actor("paladin")
        state = _make_state([paladin], with_registry=False)
        ss.register_armed(paladin, slot_level=1, spell_save_dc=13,
                            action_id="a_searing_smite", state=state)
        entry = ss.find_armed_entry(paladin)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["params"]["slot_level"], 1)
        self.assertEqual(entry["params"]["dc"], 13)

    def test_clear_armed_removes_marker(self) -> None:
        paladin = _make_actor("paladin")
        state = _make_state([paladin], with_registry=False)
        ss.register_armed(paladin, slot_level=1, spell_save_dc=13,
                            action_id="a_searing_smite", state=state)
        ss.clear_armed(paladin)
        self.assertIsNone(ss.find_armed_entry(paladin))


# ============================================================================
# Layer 5+6: try_apply_searing_smite_followup
# ============================================================================

class FollowupApplicationTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_no_armed_no_damage(self) -> None:
        # Unarmed caster — no bonus damage, no condition.
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=30)
        state = _make_state([paladin, target])
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longsword"}, "state": "hit",
        }
        rng = random.Random(1)
        damage = ss.try_apply_searing_smite_followup(
            paladin, target, state, {"kind": "melee"}, rng, is_crit=False)
        self.assertEqual(damage, 0)

    def test_ranged_attack_does_not_trigger(self) -> None:
        # Armed but firing a ranged attack — RAW says melee only.
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=30)
        state = _make_state([paladin, target])
        ss.register_armed(paladin, slot_level=1, spell_save_dc=13,
                            action_id="a_searing_smite", state=state)
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longbow"}, "state": "hit",
        }
        rng = random.Random(1)
        damage = ss.try_apply_searing_smite_followup(
            paladin, target, state, {"kind": "ranged"}, rng, is_crit=False)
        self.assertEqual(damage, 0)
        # Marker should still be there (one-shot only consumes on
        # qualifying hit)
        self.assertIsNotNone(ss.find_armed_entry(paladin))

    def test_melee_hit_armed_adds_damage_and_clears_marker(self) -> None:
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=30, ac=10)
        state = _make_state([paladin, target])
        ss.register_armed(paladin, slot_level=1, spell_save_dc=5,
                            action_id="a_searing_smite", state=state)
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longsword"}, "state": "hit",
        }
        rng = random.Random(1)
        damage = ss.try_apply_searing_smite_followup(
            paladin, target, state, {"kind": "melee"}, rng, is_crit=False)
        # 1d6 → 1-6 range
        self.assertGreaterEqual(damage, 1)
        self.assertLessEqual(damage, 6)
        # Marker cleared
        self.assertIsNone(ss.find_armed_entry(paladin))

    def test_upcast_scales_damage(self) -> None:
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=100, ac=10)
        state = _make_state([paladin, target])
        # Cast at 3rd level: 1d6 base + 2d6 upcast = 3d6 (3-18 range)
        ss.register_armed(paladin, slot_level=3, spell_save_dc=5,
                            action_id="a_searing_smite", state=state)
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longsword"}, "state": "hit",
        }
        rng = random.Random(1)
        damage = ss.try_apply_searing_smite_followup(
            paladin, target, state, {"kind": "melee"}, rng, is_crit=False)
        self.assertGreaterEqual(damage, 3)
        self.assertLessEqual(damage, 18)

    def test_crit_doubles_dice(self) -> None:
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=100, ac=10)
        state = _make_state([paladin, target])
        ss.register_armed(paladin, slot_level=1, spell_save_dc=5,
                            action_id="a_searing_smite", state=state)
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longsword"}, "state": "crit",
        }
        rng = random.Random(1)
        damage = ss.try_apply_searing_smite_followup(
            paladin, target, state, {"kind": "melee"}, rng, is_crit=True)
        # 2d6 → 2-12 range
        self.assertGreaterEqual(damage, 2)
        self.assertLessEqual(damage, 12)

    def test_ignited_auto_applies_with_recurring_damage(self) -> None:
        # 2024: no initial save — co_ignited auto-applies on hit.
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=100, ac=10)
        state = _make_state([paladin, target])
        ss.register_armed(paladin, slot_level=1, spell_save_dc=13,
                            action_id="a_searing_smite", state=state)
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longsword"}, "state": "hit",
        }
        rng = random.Random(1)
        ss.try_apply_searing_smite_followup(
            paladin, target, state, {"kind": "melee"}, rng, is_crit=False)
        ignited = [c for c in target.applied_conditions
                     if c.get("condition_id") == "co_ignited"]
        self.assertEqual(len(ignited), 1)
        ticks = [t for t in state.recurring_damage
                   if t.get("target_id") == "goblin"
                   and t.get("damage_type") == "fire"]
        self.assertEqual(len(ticks), 1)
        saves = [s for s in state.recurring_saves
                   if s.get("target_id") == "goblin"
                   and s.get("condition_id") == "co_ignited"]
        self.assertEqual(len(saves), 1)


# ============================================================================
# Layer 7: _damage integration (end-to-end)
# ============================================================================

class DamageIntegrationTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_searing_smite_fires_via_damage_primitive(self) -> None:
        # Run a real _damage call on a melee weapon hit; verify the
        # damage rider added extra damage.
        paladin = _make_actor("paladin", actions=[_melee_weapon()])
        target = _make_actor("goblin", side="enemy", hp=100, ac=10)
        state = _make_state([paladin, target])
        ss.register_armed(paladin, slot_level=1, spell_save_dc=5,
                            action_id="a_searing_smite", state=state)
        weapon = paladin.template["actions"][0]
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": weapon, "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        hp_before = target.hp_current
        _damage({"dice": "1d8", "modifier": 3,
                   "type": "slashing"}, state, EventBus())
        damage_dealt = hp_before - target.hp_current
        # 1d8 (1-8) + 3 mod + 1d6 (1-6) Searing Smite = 5-17
        self.assertGreaterEqual(damage_dealt, 5)
        # Marker cleared
        self.assertIsNone(ss.find_armed_entry(paladin))


# ============================================================================
# Layer 9: YAML loads + 10: PC schema
# ============================================================================

class YamlAndSchemaTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_f_searing_smite_loads(self) -> None:
        feature = self.registry.get("feature", "f_searing_smite")
        self.assertEqual(feature["granted_by"]["class"], "c_paladin")
        self.assertEqual(feature["granted_by"]["level"], 2)
        tmpl = feature["action_template"]
        self.assertEqual(tmpl["spell_slot_level"], 1)
        self.assertEqual(tmpl["slot"], "bonus_action")
        self.assertNotIn("concentration", tmpl)
        # Pipeline = searing_smite_arm primitive
        self.assertEqual(tmpl["pipeline"][0]["primitive"],
                            "searing_smite_arm")

    def test_co_ignited_loads(self) -> None:
        cond = self.registry.get("condition", "co_ignited")
        self.assertEqual(cond["scope"], "source_referencing")
        effects = cond["effects"]
        self.assertTrue(any(e["primitive"] == "recurring_damage"
                              for e in effects))
        self.assertTrue(any(e["primitive"] == "recurring_save"
                              for e in effects))

    def test_paladin_l2_has_searing_smite(self) -> None:
        from engine.pc_schema import build_pc_template
        pc_spec = {
            "id": "pal2", "class": "c_paladin", "level": 2,
            "ability_scores": {"str": 16, "dex": 10, "con": 14,
                                  "int": 8, "wis": 12, "cha": 16},
            "weapons": [],
        }
        template = build_pc_template(pc_spec, self.registry)
        self.assertIn("f_searing_smite",
                        template.get("features_known", []))
        action_ids = {a.get("id") for a in template.get("actions", [])}
        self.assertIn("a_searing_smite", action_ids)


# ============================================================================
# Layer 11: save-to-end at turn start
# ============================================================================

class SaveToEndTest(unittest.TestCase):

    def test_successful_save_ends_ignited_and_scrubs_entries(self) -> None:
        from engine.core.runner import EncounterRunner
        paladin = _make_actor("paladin")
        # CON 30 → save +10; caster DC = 8+3+2 = 13; roll 3+ passes
        target = _make_actor("goblin", side="enemy", hp=100, ac=10)
        target.abilities["con"] = {"score": 30, "save": 10}
        state = _make_state([paladin, target])
        ss.register_armed(paladin, slot_level=1, spell_save_dc=13,
                            action_id="a_searing_smite", state=state)
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longsword"}, "state": "hit",
        }
        ss.try_apply_searing_smite_followup(
            paladin, target, state, {"kind": "melee"},
            random.Random(1), is_crit=False)
        # co_ignited applied + recurring entries registered
        self.assertTrue(any(c.get("condition_id") == "co_ignited"
                              for c in target.applied_conditions))
        self.assertTrue(any(rd.get("condition_id") == "co_ignited"
                              for rd in state.recurring_damage))
        self.assertTrue(any(rs.get("condition_id") == "co_ignited"
                              for rs in state.recurring_saves))
        # Resolve turn-start: damage tick fires, then save (DC 1 → auto-pass)
        runner = EncounterRunner.new(state.encounter, seed=42)
        runner._resolve_recurring_damage(target, state)
        runner._resolve_recurring_saves(
            target, state, trigger_event="target_turn_start")
        # Save succeeded → co_ignited removed, entries scrubbed
        self.assertFalse(any(c.get("condition_id") == "co_ignited"
                               for c in target.applied_conditions))
        self.assertFalse(any(rd.get("condition_id") == "co_ignited"
                               for rd in state.recurring_damage))
        self.assertFalse(any(rs.get("condition_id") == "co_ignited"
                               for rs in state.recurring_saves))

    def test_failed_save_keeps_ignited(self) -> None:
        from engine.core.runner import EncounterRunner
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=100, ac=10)
        state = _make_state([paladin, target])
        ss.register_armed(paladin, slot_level=1, spell_save_dc=30,
                            action_id="a_searing_smite", state=state)
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longsword"}, "state": "hit",
        }
        ss.try_apply_searing_smite_followup(
            paladin, target, state, {"kind": "melee"},
            random.Random(1), is_crit=False)
        runner = EncounterRunner.new(state.encounter, seed=42)
        runner._resolve_recurring_damage(target, state)
        runner._resolve_recurring_saves(
            target, state, trigger_event="target_turn_start")
        # Save failed → co_ignited still active
        self.assertTrue(any(c.get("condition_id") == "co_ignited"
                              for c in target.applied_conditions))
        self.assertTrue(any(rd.get("condition_id") == "co_ignited"
                              for rd in state.recurring_damage))


# ============================================================================
# Layer 12: upcast burn scaling
# ============================================================================

class UpcastBurnTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_upcast_slot_3_scales_burn_dice(self) -> None:
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=100, ac=10)
        state = _make_state([paladin, target])
        ss.register_armed(paladin, slot_level=3, spell_save_dc=30,
                            action_id="a_searing_smite", state=state)
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longsword"}, "state": "hit",
        }
        ss.try_apply_searing_smite_followup(
            paladin, target, state, {"kind": "melee"},
            random.Random(1), is_crit=False)
        ticks = [t for t in state.recurring_damage
                   if t.get("condition_id") == "co_ignited"]
        self.assertEqual(len(ticks), 1)
        self.assertEqual(ticks[0]["dice"], "3d6")


if __name__ == "__main__":
    unittest.main()
