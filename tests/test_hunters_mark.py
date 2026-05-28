"""Hunter's Mark tests (PR #91).

RAW (Ranger 1st-level, PHB 2024):
  BA cast, 90 ft, concentration up to 1 hour. Mark one creature.
  Whenever you hit it with a weapon attack, deal +1d6 damage.
  Advantage on WIS (Perception/Survival) checks to find it. Rebind
  on death.

v1 ships the per-hit damage rider gated to the marked target via
PR #90's target_is(<id>) when-clause atom. Mechanically parallel to
Hex (which the tests mirror); kept distinct for named_effect tagging
+ event log clarity + future divergence (Perception tracking).

Layers:
  1. _hunters_mark_mark registers modifier with substituted target
  2. _hunters_mark_mark logs hunters_mark_applied event
  3. _hunters_mark_mark raises on missing target
  4. _damage applies bonus against marked target
  5. _damage does NOT apply bonus against other enemies
  6. Concentration end scrubs the mark
  7. Hex + Hunter's Mark stack correctly on same target (different
     named_effects don't dedup each other)
  8. f_hunters_mark YAML loads with correct shape
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
    _hunters_mark_mark, _hex_curse, _damage,
)


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0), hp=30, ac=14,
                  wis_score=14, actions=None):
    abilities = {
        "str": {"score": 12, "save": 1},
        "dex": {"score": 16, "save": 3},
        "con": {"score": 14, "save": 2},
        "int": {"score": 10, "save": 0},
        "wis": {"score": wis_score, "save": 2},
        "cha": {"score": 10, "save": 0},
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


def _longbow(action_id="a_longbow"):
    return {
        "id": action_id, "type": "weapon_attack", "slot": "action",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "ranged", "ability": "dex",
                          "bonus": 5, "range_ft": 150}},
            {"primitive": "damage",
              "params": {"dice": "1d8", "modifier": 3,
                          "type": "piercing"}},
        ],
    }


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Layer 1+2+3: _hunters_mark_mark primitive
# ============================================================================

class HuntersMarkPrimitiveTest(unittest.TestCase):

    def test_registers_modifier_with_substituted_target(self) -> None:
        ranger = _make_actor("ranger")
        deer = _make_actor("deer", side="enemy")
        state = _make_state([ranger, deer])
        state.current_attack = {
            "actor": ranger, "target": deer,
            "action": {"id": "a_hunters_mark"},
        }
        _hunters_mark_mark({"value": 3}, state, EventBus())
        mods = [m for m in ranger.active_modifiers
                  if m.get("primitive") == "weapon_damage_bonus"]
        self.assertEqual(len(mods), 1)
        self.assertEqual(mods[0]["params"]["when"], "target_is(deer)")
        self.assertEqual(mods[0]["params"]["value"], 3)
        # Named effect is hunters_mark (not hex)
        self.assertEqual(mods[0]["source"]["named_effect"],
                            "hunters_mark")

    def test_logs_event(self) -> None:
        ranger = _make_actor("ranger")
        deer = _make_actor("deer", side="enemy")
        state = _make_state([ranger, deer])
        state.current_attack = {
            "actor": ranger, "target": deer,
            "action": {"id": "a_hunters_mark"},
        }
        _hunters_mark_mark({"value": 3}, state, EventBus())
        events = [e for e in state.event_log
                    if e.get("event") == "hunters_mark_applied"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["target"], "deer")

    def test_missing_target_raises(self) -> None:
        ranger = _make_actor("ranger")
        state = _make_state([ranger])
        state.current_attack = {"actor": ranger, "target": None,
                                  "action": {"id": "a_hunters_mark"}}
        with self.assertRaises(ValueError):
            _hunters_mark_mark({}, state, EventBus())


# ============================================================================
# Layer 4+5: _damage integration — target-specific firing
# ============================================================================

class DamageIntegrationTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_bonus_applies_against_marked_target(self) -> None:
        ranger = _make_actor("ranger", actions=[_longbow()])
        deer = _make_actor("deer", side="enemy", hp=100, ac=10)
        state = _make_state([ranger, deer])
        state.current_attack = {"actor": ranger, "target": deer,
                                  "action": {"id": "a_hunters_mark"}}
        _hunters_mark_mark({"value": 3}, state, EventBus())
        weapon = ranger.template["actions"][0]
        state.current_attack = {
            "actor": ranger, "target": deer,
            "action": weapon, "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        hp_before = deer.hp_current
        _damage({"dice": "1d8", "modifier": 3,
                   "type": "piercing"}, state, EventBus())
        damage_dealt = hp_before - deer.hp_current
        # 1d8 (1-8) + 3 mod + 3 hunter's mark = 7-14
        self.assertGreaterEqual(damage_dealt, 7)

    def test_bonus_does_not_apply_against_other_targets(self) -> None:
        ranger = _make_actor("ranger", actions=[_longbow()])
        deer = _make_actor("deer", side="enemy", hp=100, ac=10)
        wolf = _make_actor("wolf", side="enemy", position=(2, 0),
                              hp=100, ac=10)
        state = _make_state([ranger, deer, wolf])
        # Mark the deer
        state.current_attack = {"actor": ranger, "target": deer,
                                  "action": {"id": "a_hunters_mark"}}
        _hunters_mark_mark({"value": 3}, state, EventBus())
        # Attack the wolf (not marked)
        weapon = ranger.template["actions"][0]
        state.current_attack = {
            "actor": ranger, "target": wolf,
            "action": weapon, "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        hp_before = wolf.hp_current
        _damage({"dice": "1d8", "modifier": 3,
                   "type": "piercing"}, state, EventBus())
        damage_dealt = hp_before - wolf.hp_current
        # 1d8 (1-8) + 3 mod only — no Hunter's Mark bonus
        self.assertLessEqual(damage_dealt, 11)


# ============================================================================
# Layer 6: concentration end scrubs the mark
# ============================================================================

class ConcentrationEndScrubTest(unittest.TestCase):

    def test_concentration_end_removes_hunters_mark_modifier(self) -> None:
        from engine.core.concentration import (
            apply_concentration, end_concentration)
        ranger = _make_actor("ranger")
        deer = _make_actor("deer", side="enemy")
        state = _make_state([ranger, deer])
        apply_concentration(ranger, {
            "id": "a_hunters_mark", "concentration": True,
        }, state)
        state.current_attack = {
            "actor": ranger, "target": deer,
            "action": {"id": "a_hunters_mark"},
        }
        _hunters_mark_mark({"value": 3}, state, EventBus())
        self.assertEqual(len([m for m in ranger.active_modifiers
                                if m.get("primitive") == "weapon_damage_bonus"]),
                            1)
        end_concentration(ranger, state, reason="test")
        remaining = [m for m in ranger.active_modifiers
                       if m.get("primitive") == "weapon_damage_bonus"]
        self.assertEqual(len(remaining), 0)


# ============================================================================
# Layer 7: Hex + Hunter's Mark stack (different named_effects)
# ============================================================================

class HexAndHuntersMarkStackTest(unittest.TestCase):
    """Two different damage riders from different spells should both
    apply to the same target since they have different named_effects.
    This validates the cross-caster dedup uses named_effect (not just
    "weapon damage bonus exists") as the discriminator."""

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_both_riders_apply_to_same_target(self) -> None:
        # Single-actor scenario: same caster has both Hex AND
        # Hunter's Mark on the same target. (Unrealistic per RAW
        # — can't concentrate on two spells — but tests that the
        # modifier system itself doesn't dedup them.)
        caster = _make_actor("caster", actions=[_longbow()])
        target = _make_actor("target", side="enemy", hp=100, ac=10)
        state = _make_state([caster, target])
        # Apply Hex
        state.current_attack = {
            "actor": caster, "target": target,
            "action": {"id": "a_hex"},
        }
        _hex_curse({"value": 3}, state, EventBus())
        # Apply Hunter's Mark
        state.current_attack = {
            "actor": caster, "target": target,
            "action": {"id": "a_hunters_mark"},
        }
        _hunters_mark_mark({"value": 3}, state, EventBus())
        # Both modifiers should be present
        mods = [m for m in caster.active_modifiers
                  if m.get("primitive") == "weapon_damage_bonus"]
        self.assertEqual(len(mods), 2)
        # Attack and verify both bonuses applied
        weapon = caster.template["actions"][0]
        state.current_attack = {
            "actor": caster, "target": target,
            "action": weapon, "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
        }
        hp_before = target.hp_current
        _damage({"dice": "1d8", "modifier": 3,
                   "type": "piercing"}, state, EventBus())
        damage_dealt = hp_before - target.hp_current
        # 1d8 (1-8) + 3 mod + 3 hex + 3 hunter's mark = 10-17
        self.assertGreaterEqual(damage_dealt, 10)


# ============================================================================
# Layer 8: f_hunters_mark YAML loads
# ============================================================================

class YamlLoadTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_f_hunters_mark_loads(self) -> None:
        feature = self.registry.get("feature", "f_hunters_mark")
        self.assertEqual(feature["granted_by"]["class"], "c_ranger")
        self.assertEqual(feature["granted_by"]["level"], 2)
        tmpl = feature["action_template"]
        self.assertEqual(tmpl["type"], "offensive_buff")
        self.assertEqual(tmpl["spell_slot_level"], 1)
        self.assertEqual(tmpl["slot"], "bonus_action")
        self.assertTrue(tmpl["concentration"])
        self.assertEqual(tmpl["named_effect"], "hunters_mark")
        self.assertEqual(tmpl["pipeline"][0]["primitive"],
                            "hunters_mark_mark")


if __name__ == "__main__":
    unittest.main()
