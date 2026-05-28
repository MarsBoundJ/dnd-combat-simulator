"""Hex tests (PR #90) — first target-specific weapon damage rider.

RAW (Warlock 1st-level, PHB 2024):
  BA cast, 90 ft, concentration up to 1 hour. Curse one creature.
  Whenever you hit the cursed creature with an attack, deal +1d6
  necrotic. Target has disadvantage on ability checks with one
  ability chosen at cast time. If target drops, BA on a subsequent
  turn rebinds to a new creature.

v1 ships the per-hit damage rider gated to the cursed target via
the new target_is(<id>) when-clause atom on weapon_damage_bonus.
Ability-check disadvantage + rebind are deferred.

Layers:
  1. target_is(<id>) when-clause atom matches in-flight target
  2. target_is(<id>) when-clause misses non-cursed target
  3. _hex_curse primitive registers modifier with substituted when
  4. _damage applies hex bonus ONLY against cursed target
  5. _damage does NOT apply hex bonus against other enemies
  6. Concentration end scrubs the hex modifier
  7. f_hex YAML loads with correct shape
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import modifiers as _modifiers
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import _hex_curse, _damage


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0), hp=30, ac=14,
                  cha_score=16, actions=None):
    abilities = {
        "str": {"score": 10, "save": 0},
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


def _eldritch_blast(action_id="a_eldritch_blast"):
    return {
        "id": action_id, "type": "weapon_attack", "slot": "action",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "ranged", "ability": "cha",
                          "bonus": 5, "range_ft": 120}},
            {"primitive": "damage",
              "params": {"dice": "1d10", "modifier": 0,
                          "type": "force"}},
        ],
    }


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Layer 1+2: target_is when-clause atom
# ============================================================================

class TargetIsWhenAtomTest(unittest.TestCase):

    def test_matches_in_flight_target(self) -> None:
        warlock = _make_actor("warlock")
        goblin = _make_actor("goblin", side="enemy")
        state = _make_state([warlock, goblin])
        state.current_attack = {"actor": warlock, "target": goblin}
        # Direct call to the when-eval helper
        self.assertTrue(_modifiers._eval_weapon_damage_when(
            "target_is(goblin)", {"kind": "melee"}, state))

    def test_misses_different_target(self) -> None:
        warlock = _make_actor("warlock")
        goblin = _make_actor("goblin", side="enemy")
        orc = _make_actor("orc", side="enemy")
        state = _make_state([warlock, goblin, orc])
        # Current attack is on orc; modifier is gated to goblin
        state.current_attack = {"actor": warlock, "target": orc}
        self.assertFalse(_modifiers._eval_weapon_damage_when(
            "target_is(goblin)", {"kind": "melee"}, state))

    def test_no_target_returns_false(self) -> None:
        # Defensive: if no current_target, gate fails (safer than
        # silently letting bonus fire on every attack)
        warlock = _make_actor("warlock")
        state = _make_state([warlock])
        state.current_attack = {}
        self.assertFalse(_modifiers._eval_weapon_damage_when(
            "target_is(goblin)", {"kind": "melee"}, state))


# ============================================================================
# Layer 3: _hex_curse primitive
# ============================================================================

class HexCursePrimitiveTest(unittest.TestCase):

    def test_registers_modifier_with_substituted_target(self) -> None:
        warlock = _make_actor("warlock")
        goblin = _make_actor("goblin", side="enemy")
        state = _make_state([warlock, goblin])
        state.current_attack = {
            "actor": warlock, "target": goblin,
            "action": {"id": "a_hex"},
        }
        _hex_curse({"value": 3}, state, EventBus())
        mods = [m for m in warlock.active_modifiers
                  if m.get("primitive") == "weapon_damage_bonus"]
        self.assertEqual(len(mods), 1)
        # The when-clause should have the goblin's id substituted in
        self.assertEqual(mods[0]["params"]["when"], "target_is(goblin)")
        self.assertEqual(mods[0]["params"]["value"], 3)

    def test_logs_event(self) -> None:
        warlock = _make_actor("warlock")
        goblin = _make_actor("goblin", side="enemy")
        state = _make_state([warlock, goblin])
        state.current_attack = {
            "actor": warlock, "target": goblin,
            "action": {"id": "a_hex"},
        }
        _hex_curse({"value": 3}, state, EventBus())
        events = [e for e in state.event_log
                    if e.get("event") == "hex_curse_applied"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["target"], "goblin")

    def test_missing_target_raises(self) -> None:
        warlock = _make_actor("warlock")
        state = _make_state([warlock])
        state.current_attack = {"actor": warlock, "target": None,
                                  "action": {"id": "a_hex"}}
        with self.assertRaises(ValueError):
            _hex_curse({}, state, EventBus())


# ============================================================================
# Layer 4+5: _damage integration — target-specific firing
# ============================================================================

class DamageIntegrationTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_bonus_applies_against_cursed_target(self) -> None:
        warlock = _make_actor("warlock", actions=[_eldritch_blast()])
        goblin = _make_actor("goblin", side="enemy", hp=100, ac=10)
        state = _make_state([warlock, goblin])
        # Cast Hex on goblin
        state.current_attack = {"actor": warlock, "target": goblin,
                                  "action": {"id": "a_hex"}}
        _hex_curse({"value": 3}, state, EventBus())
        # Now attack the goblin
        weapon = warlock.template["actions"][0]
        state.current_attack = {
            "actor": warlock, "target": goblin,
            "action": weapon, "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        hp_before = goblin.hp_current
        _damage({"dice": "1d10", "modifier": 0,
                   "type": "force"}, state, EventBus())
        damage_dealt = hp_before - goblin.hp_current
        # 1d10 (1-10) + 3 hex bonus = 4-13
        self.assertGreaterEqual(damage_dealt, 4)

    def test_bonus_does_not_apply_against_other_targets(self) -> None:
        warlock = _make_actor("warlock", actions=[_eldritch_blast()])
        goblin = _make_actor("goblin", side="enemy", hp=100, ac=10)
        orc = _make_actor("orc", side="enemy", position=(2, 0),
                            hp=100, ac=10)
        state = _make_state([warlock, goblin, orc])
        # Cast Hex on goblin
        state.current_attack = {"actor": warlock, "target": goblin,
                                  "action": {"id": "a_hex"}}
        _hex_curse({"value": 3}, state, EventBus())
        # Attack the ORC (not cursed)
        weapon = warlock.template["actions"][0]
        state.current_attack = {
            "actor": warlock, "target": orc,
            "action": weapon, "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        hp_before = orc.hp_current
        _damage({"dice": "1d10", "modifier": 0,
                   "type": "force"}, state, EventBus())
        damage_dealt = hp_before - orc.hp_current
        # 1d10 only (1-10); no +3 bonus because orc isn't cursed
        self.assertLessEqual(damage_dealt, 10)


# ============================================================================
# Layer 6: concentration end scrubs the curse
# ============================================================================

class ConcentrationEndScrubTest(unittest.TestCase):

    def test_concentration_end_removes_hex_modifier(self) -> None:
        from engine.core.concentration import (
            apply_concentration, end_concentration)
        warlock = _make_actor("warlock")
        goblin = _make_actor("goblin", side="enemy")
        state = _make_state([warlock, goblin])
        # Apply concentration to a synthetic hex action
        apply_concentration(warlock, {
            "id": "a_hex", "concentration": True,
        }, state)
        # Apply the curse
        state.current_attack = {
            "actor": warlock, "target": goblin,
            "action": {"id": "a_hex"},
        }
        _hex_curse({"value": 3}, state, EventBus())
        self.assertEqual(len([m for m in warlock.active_modifiers
                                if m.get("primitive") == "weapon_damage_bonus"]),
                            1)
        # End concentration — the hex modifier should be scrubbed
        # via the existing source-matching scrub (caster_id + action_id)
        end_concentration(warlock, state, reason="test")
        remaining = [m for m in warlock.active_modifiers
                       if m.get("primitive") == "weapon_damage_bonus"]
        self.assertEqual(len(remaining), 0)


# ============================================================================
# Layer 7: f_hex YAML loads
# ============================================================================

class YamlLoadTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_f_hex_loads(self) -> None:
        feature = self.registry.get("feature", "f_hex")
        self.assertEqual(feature["granted_by"]["class"], "c_warlock")
        self.assertEqual(feature["granted_by"]["level"], 1)
        tmpl = feature["action_template"]
        self.assertEqual(tmpl["type"], "offensive_buff")
        self.assertEqual(tmpl["spell_slot_level"], 1)
        self.assertEqual(tmpl["slot"], "bonus_action")
        self.assertTrue(tmpl["concentration"])
        self.assertEqual(tmpl["named_effect"], "hex")
        self.assertEqual(tmpl["pipeline"][0]["primitive"], "hex_curse")


if __name__ == "__main__":
    unittest.main()
