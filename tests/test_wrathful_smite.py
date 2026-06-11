"""Wrathful Smite tests.

RAW (PHB 2024, 1st-level Paladin spell):
  BA cast (after a melee hit), 1 minute, NOT concentration (2024).
  The hit deals +1d6 necrotic (+1d6 per slot above 1st, doubled on
  crit); target makes a WIS save or is Frightened until the spell
  ends, re-saving at the end of each of its turns.

Layers:
  1. f_wrathful_smite YAML loads with correct shape
  2. Paladin L2 lists f_wrathful_smite; pc_schema attaches the action
  3. register_armed / find_armed / clear_armed
  4. followup gating: only melee, only when armed
  5. followup applies 1d6 necrotic bonus damage + WIS save -> co_frightened
  6. upcast scales damage (+1d6 per slot above 1st)
  7. crit doubles dice
  8. ranged attack does not trigger
  9. end-to-end via _damage: armed Paladin melee hit -> frightened
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import wrathful_smite as ws
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import _wrathful_smite_arm, _damage

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


def _make_actor(actor_id, *, side="pc", position=(0, 0), hp=30, ac=14,
                  cha_score=16, wis_score=10, levels=None, actions=None):
    abilities = {
        "str": {"score": 16, "save": 3},
        "dex": {"score": 12, "save": 1},
        "con": {"score": 14, "save": 2},
        "int": {"score": 10, "save": 0},
        "wis": {"score": wis_score, "save": (wis_score - 10) // 2},
        "cha": {"score": cha_score, "save": (cha_score - 10) // 2},
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


_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True,
                                   schema_root=SCHEMA_ROOT)
    return _REGISTRY


# ============================================================================
# Layer 1+2: content + class wiring
# ============================================================================

class ContentTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_f_wrathful_smite_loads(self) -> None:
        feature = self.registry.get("feature", "f_wrathful_smite")
        self.assertEqual(feature["granted_by"]["class"], "c_paladin")
        self.assertEqual(feature["granted_by"]["level"], 2)
        tmpl = feature["action_template"]
        self.assertEqual(tmpl["spell_slot_level"], 1)
        self.assertEqual(tmpl["slot"], "bonus_action")
        # 2024: NOT concentration (end-of-turn re-save instead)
        self.assertNotIn("concentration", tmpl)
        self.assertEqual(tmpl["named_effect"], "wrathful_smite")
        self.assertEqual(tmpl["pipeline"][0]["primitive"],
                            "wrathful_smite_arm")

    def test_paladin_l2_has_wrathful_smite(self) -> None:
        from engine.pc_schema import build_pc_template
        pc_spec = {
            "id": "pal2", "class": "c_paladin", "level": 2,
            "ability_scores": {"str": 16, "dex": 10, "con": 14,
                                  "int": 8, "wis": 12, "cha": 16},
            "weapons": [],
        }
        template = build_pc_template(pc_spec, self.registry)
        self.assertIn("f_wrathful_smite",
                        template.get("features_known", []))
        action_ids = {a.get("id") for a in template.get("actions", [])}
        self.assertIn("a_wrathful_smite", action_ids)

    def test_co_frightened_loads(self) -> None:
        cond = self.registry.get("condition", "co_frightened")
        self.assertEqual(cond["scope"], "source_referencing")


# ============================================================================
# Layer 3: armed marker lifecycle
# ============================================================================

class ArmedMarkerTest(unittest.TestCase):

    def test_register_find_clear(self) -> None:
        paladin = _make_actor("paladin")
        state = _make_state([paladin], with_registry=False)
        ws.register_armed(paladin, slot_level=1, spell_save_dc=13,
                            action_id="a_wrathful_smite", state=state)
        entry = ws.find_armed_entry(paladin)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["params"]["slot_level"], 1)
        self.assertEqual(entry["params"]["dc"], 13)
        ws.clear_armed(paladin)
        self.assertIsNone(ws.find_armed_entry(paladin))

    def test_arm_primitive_uses_cha_dc(self) -> None:
        # CHA 16 (+3), PB 2 -> DC 8+3+2 = 13
        paladin = _make_actor("paladin", cha_score=16)
        paladin.template["spellcasting_ability"] = "charisma"
        target = _make_actor("foe", side="enemy")
        state = _make_state([paladin, target], with_registry=False)
        state.current_attack = {"actor": paladin, "target": target,
                                  "action": {"id": "a_wrathful_smite"},
                                  "chosen_slot_level": 1}
        _wrathful_smite_arm({}, state, EventBus())
        entry = ws.find_armed_entry(paladin)
        self.assertEqual(entry["params"]["dc"], 13)
        self.assertEqual(entry["params"]["slot_level"], 1)


# ============================================================================
# Layer 4+5: followup gating + application
# ============================================================================

class FollowupTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_no_armed_no_damage(self) -> None:
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=30)
        state = _make_state([paladin, target])
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longsword"}, "state": "hit",
        }
        damage = ws.try_apply_wrathful_smite_followup(
            paladin, target, state, {"kind": "melee"}, random.Random(1),
            is_crit=False)
        self.assertEqual(damage, 0)

    def test_ranged_attack_does_not_trigger(self) -> None:
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=30)
        state = _make_state([paladin, target])
        ws.register_armed(paladin, slot_level=1, spell_save_dc=13,
                            action_id="a_wrathful_smite", state=state)
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longbow"}, "state": "hit",
        }
        damage = ws.try_apply_wrathful_smite_followup(
            paladin, target, state, {"kind": "ranged"}, random.Random(1),
            is_crit=False)
        self.assertEqual(damage, 0)
        self.assertIsNotNone(ws.find_armed_entry(paladin))

    def test_melee_hit_deals_1d6_and_clears_marker(self) -> None:
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=100, ac=10)
        state = _make_state([paladin, target])
        ws.register_armed(paladin, slot_level=1, spell_save_dc=5,
                            action_id="a_wrathful_smite", state=state)
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longsword"}, "state": "hit",
        }
        damage = ws.try_apply_wrathful_smite_followup(
            paladin, target, state, {"kind": "melee"}, random.Random(1),
            is_crit=False)
        # 1d6 -> 1-6 range
        self.assertGreaterEqual(damage, 1)
        self.assertLessEqual(damage, 6)
        self.assertIsNone(ws.find_armed_entry(paladin))

    def test_on_fail_applies_frightened(self) -> None:
        # DC 30 -> target auto-fails WIS save -> Frightened applies.
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=100, ac=10,
                               wis_score=8)
        state = _make_state([paladin, target])
        ws.register_armed(paladin, slot_level=1, spell_save_dc=30,
                            action_id="a_wrathful_smite", state=state)
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longsword"}, "state": "hit",
        }
        ws.try_apply_wrathful_smite_followup(
            paladin, target, state, {"kind": "melee"}, random.Random(1),
            is_crit=False)
        frightened = [c for c in target.applied_conditions
                        if c.get("condition_id") == "co_frightened"]
        self.assertEqual(len(frightened), 1)

    def test_on_success_no_condition(self) -> None:
        # DC 1 -> target auto-succeeds -> no Frightened.
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=100, ac=10,
                               wis_score=18)
        state = _make_state([paladin, target])
        ws.register_armed(paladin, slot_level=1, spell_save_dc=1,
                            action_id="a_wrathful_smite", state=state)
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longsword"}, "state": "hit",
        }
        ws.try_apply_wrathful_smite_followup(
            paladin, target, state, {"kind": "melee"}, random.Random(1),
            is_crit=False)
        self.assertFalse(any(c.get("condition_id") == "co_frightened"
                               for c in target.applied_conditions))
        self.assertIsNone(ws.find_armed_entry(paladin))


# ============================================================================
# Layer 6: upcast scaling
# ============================================================================

class UpcastTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_upcast_slot_3_deals_3d6(self) -> None:
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=100, ac=10)
        state = _make_state([paladin, target])
        ws.register_armed(paladin, slot_level=3, spell_save_dc=5,
                            action_id="a_wrathful_smite", state=state)
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longsword"}, "state": "hit",
        }
        damage = ws.try_apply_wrathful_smite_followup(
            paladin, target, state, {"kind": "melee"}, random.Random(1),
            is_crit=False)
        # 3d6 -> 3-18 range
        self.assertGreaterEqual(damage, 3)
        self.assertLessEqual(damage, 18)


# ============================================================================
# Layer 7: crit doubles dice
# ============================================================================

class CritTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_crit_doubles_dice(self) -> None:
        paladin = _make_actor("paladin")
        target = _make_actor("goblin", side="enemy", hp=100, ac=10)
        state = _make_state([paladin, target])
        ws.register_armed(paladin, slot_level=1, spell_save_dc=5,
                            action_id="a_wrathful_smite", state=state)
        state.current_attack = {
            "actor": paladin, "target": target,
            "action": {"id": "a_longsword"}, "state": "crit",
        }
        damage = ws.try_apply_wrathful_smite_followup(
            paladin, target, state, {"kind": "melee"}, random.Random(1),
            is_crit=True)
        # 2d6 -> 2-12 range
        self.assertGreaterEqual(damage, 2)
        self.assertLessEqual(damage, 12)


# ============================================================================
# Layer 9: end-to-end via _damage
# ============================================================================

class EndToEndTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_damage_hook_fires_wrathful_smite(self) -> None:
        paladin = _make_actor("paladin", actions=[_melee_weapon()])
        target = _make_actor("goblin", side="enemy", hp=100, ac=10,
                               wis_score=6)
        state = _make_state([paladin, target])
        ws.register_armed(paladin, slot_level=1, spell_save_dc=30,
                            action_id="a_wrathful_smite", state=state)
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
        # 1d8 (1-8) + 3 mod + 1d6 (1-6) Wrathful Smite = 5-17
        self.assertGreaterEqual(damage_dealt, 5)
        self.assertIsNone(ws.find_armed_entry(paladin))
        # DC 30 -> Frightened applied
        self.assertTrue(any(c.get("condition_id") == "co_frightened"
                              for c in target.applied_conditions))


if __name__ == "__main__":
    unittest.main()
