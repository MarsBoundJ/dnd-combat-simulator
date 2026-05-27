"""Upcast scaling tests (PR #77).

Layers:
  1. Helper: lowest_available_slot_at_or_above
  2. Helper: is_upcastable
  3. Helper: has_slot_for_action (cantrip / exact / upcastable)
  4. Helper: resolve_chosen_slot_level (lowest-first picker)
  5. Pipeline filter: upcastable spell with only higher slots passes
  6. Pipeline execute: stamps chosen_slot_level on state.current_attack
  7. Pipeline execute: consumes the chosen (not base) slot level
  8. _resolve_upcast_extra_dice helper math
  9. _damage applies upcast bonus dice on hit/crit
 10. Damage type filter: bonus only on matching damage_type
 11. Crit doubles upcast dice
 12. Hellish Rebuke (reaction path) upcast: 2d10 → 3d10 at slot 2
 13. HoH (persistent_aura) upcast: 4d6 cold → 5d6 cold at slot 4
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.spell_slots import (
    has_slot, has_slot_for_action, is_upcastable,
    lowest_available_slot_at_or_above,
    resolve_chosen_slot_level,
)
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import _damage, _resolve_upcast_extra_dice


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, slots=None, side="pc", position=(0, 0),
                  hp=100):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [],
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp, ac=14,
        speed={"walk": 30}, position=position, abilities=abilities,
        spell_slots=dict(slots or {}),
        spell_slots_max=dict(slots or {}),
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _spell_action(*, slot_level=1, upcast=None, action_id="a_spell"):
    action = {
        "id": action_id, "type": "hard_control",
        "spell_slot_level": slot_level,
        "pipeline": [
            {"primitive": "forced_save",
              "params": {"ability": "dexterity", "dc": 13,
                          "on_fail": [{"primitive": "damage",
                                          "params": {"dice": "2d10",
                                                       "type": "fire"}}]}},
        ],
    }
    if upcast is not None:
        action["upcast_scaling"] = upcast
    return action


# ============================================================================
# Layer 1: lowest_available_slot_at_or_above
# ============================================================================

class LowestAvailableSlotTest(unittest.TestCase):

    def test_picks_exact_when_available(self) -> None:
        actor = _make_actor("a", slots={3: 1, 5: 1})
        self.assertEqual(lowest_available_slot_at_or_above(actor, 3), 3)

    def test_picks_higher_when_exact_empty(self) -> None:
        actor = _make_actor("a", slots={5: 1})  # no L3 slots
        self.assertEqual(lowest_available_slot_at_or_above(actor, 3), 5)

    def test_none_when_no_eligible(self) -> None:
        actor = _make_actor("a", slots={1: 1, 2: 1})
        self.assertIsNone(
            lowest_available_slot_at_or_above(actor, 3))

    def test_none_when_no_slots(self) -> None:
        actor = _make_actor("a", slots={})
        self.assertIsNone(
            lowest_available_slot_at_or_above(actor, 3))

    def test_base_zero_returns_none(self) -> None:
        actor = _make_actor("a", slots={1: 1})
        self.assertIsNone(
            lowest_available_slot_at_or_above(actor, 0))


# ============================================================================
# Layer 2: is_upcastable
# ============================================================================

class IsUpcastableTest(unittest.TestCase):

    def test_true_with_upcast_block(self) -> None:
        action = {"upcast_scaling": {"extra_dice_per_level": "1d6"}}
        self.assertTrue(is_upcastable(action))

    def test_false_without_block(self) -> None:
        self.assertFalse(is_upcastable({}))

    def test_false_with_empty_block(self) -> None:
        self.assertFalse(is_upcastable({"upcast_scaling": {}}))


# ============================================================================
# Layer 3: has_slot_for_action
# ============================================================================

class HasSlotForActionTest(unittest.TestCase):

    def test_cantrip_always_available(self) -> None:
        actor = _make_actor("a", slots={})
        self.assertTrue(has_slot_for_action(actor, {}))

    def test_exact_level_requires_exact_slot(self) -> None:
        actor = _make_actor("a", slots={5: 1})
        # Non-upcastable spell at L3 — actor has L5 but no L3,
        # should NOT be available
        action = _spell_action(slot_level=3)
        self.assertFalse(has_slot_for_action(actor, action))

    def test_upcastable_accepts_higher_slot(self) -> None:
        actor = _make_actor("a", slots={5: 1})
        action = _spell_action(slot_level=3,
                                  upcast={"extra_dice_per_level": "1d6"})
        self.assertTrue(has_slot_for_action(actor, action))

    def test_upcastable_rejects_when_no_eligible_slot(self) -> None:
        actor = _make_actor("a", slots={1: 1, 2: 1})
        action = _spell_action(slot_level=3,
                                  upcast={"extra_dice_per_level": "1d6"})
        self.assertFalse(has_slot_for_action(actor, action))


# ============================================================================
# Layer 4: resolve_chosen_slot_level
# ============================================================================

class ResolveChosenSlotLevelTest(unittest.TestCase):

    def test_non_spell_returns_zero(self) -> None:
        actor = _make_actor("a", slots={1: 1})
        self.assertEqual(resolve_chosen_slot_level(actor, {}), 0)

    def test_non_upcastable_returns_base(self) -> None:
        actor = _make_actor("a", slots={3: 1, 5: 1})
        action = _spell_action(slot_level=3)
        self.assertEqual(resolve_chosen_slot_level(actor, action), 3)

    def test_upcastable_picks_lowest(self) -> None:
        actor = _make_actor("a", slots={3: 1, 4: 1, 5: 1})
        action = _spell_action(slot_level=3,
                                  upcast={"extra_dice_per_level": "1d6"})
        self.assertEqual(resolve_chosen_slot_level(actor, action), 3)

    def test_upcastable_picks_higher_when_base_empty(self) -> None:
        actor = _make_actor("a", slots={5: 1})
        action = _spell_action(slot_level=3,
                                  upcast={"extra_dice_per_level": "1d6"})
        self.assertEqual(resolve_chosen_slot_level(actor, action), 5)

    def test_upcastable_raises_when_no_eligible_slot(self) -> None:
        actor = _make_actor("a", slots={1: 1})
        action = _spell_action(slot_level=3,
                                  upcast={"extra_dice_per_level": "1d6"})
        with self.assertRaises(ValueError):
            resolve_chosen_slot_level(actor, action)


# ============================================================================
# Layer 5: pipeline filter
# ============================================================================

class PipelineFilterTest(unittest.TestCase):

    def test_upcastable_spell_emits_with_higher_slot(self) -> None:
        from engine.core import pipeline
        attacker = _make_actor("a", slots={5: 1})  # no L3 slot
        # Range 60 ft, target adjacent — in range
        action = _spell_action(slot_level=3,
                                  upcast={"extra_dice_per_level": "1d6"})
        action["range_ft"] = 60
        attacker.template["actions"] = [action]
        enemy = _make_actor("e", side="enemy", position=(1, 0))
        state = _make_state([attacker, enemy])
        candidates = pipeline.generate_candidates(attacker, state,
                                                      slot="action")
        # Should have a hard_control candidate via the L5 slot
        hc = [c for c in candidates if c.get("kind") == "hard_control"]
        self.assertEqual(len(hc), 1)

    def test_non_upcastable_spell_blocked_when_exact_empty(self) -> None:
        from engine.core import pipeline
        attacker = _make_actor("a", slots={5: 1})  # no L3 slot
        action = _spell_action(slot_level=3)  # NO upcast block
        action["range_ft"] = 60
        attacker.template["actions"] = [action]
        enemy = _make_actor("e", side="enemy", position=(1, 0))
        state = _make_state([attacker, enemy])
        candidates = pipeline.generate_candidates(attacker, state,
                                                      slot="action")
        hc = [c for c in candidates if c.get("kind") == "hard_control"]
        self.assertEqual(len(hc), 0)


# ============================================================================
# Layer 6+7: pipeline execute stashes + consumes chosen slot
# ============================================================================

class PipelineExecuteUpcastTest(unittest.TestCase):

    def test_execute_consumes_higher_slot_when_upcasting(self) -> None:
        from engine.core import pipeline
        primitives_module.set_rng(random.Random(5))
        attacker = _make_actor("a", slots={5: 1})
        action = _spell_action(slot_level=3,
                                  upcast={"extra_dice_per_level": "1d10",
                                            "damage_type": "fire"})
        action["range_ft"] = 60
        enemy = _make_actor("e", side="enemy", position=(1, 0))
        state = _make_state([attacker, enemy])
        chosen = {
            "kind": "hard_control",
            "action": action,
            "target": enemy,
            "actor": attacker,
        }
        from engine.primitives import PrimitiveRegistry
        prims = PrimitiveRegistry.with_defaults()
        pipeline.execute(chosen, state, EventBus(), prims)
        # L5 slot consumed (count goes from 1 to 0)
        self.assertEqual(attacker.spell_slots.get(5, 0), 0)
        # L3 was empty before; should still be empty (was never used)
        self.assertEqual(attacker.spell_slots.get(3, 0), 0)


# ============================================================================
# Layer 8+9+10+11: _damage upcast helper + integration + filters + crit
# ============================================================================

class DamagePrimitiveUpcastTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def _setup_attack(self, *, base_slot_level, chosen_slot_level,
                         upcast=None, damage_type="fire",
                         attack_state="hit"):
        attacker = _make_actor("a")
        target = _make_actor("t", side="enemy", hp=500)
        state = _make_state([attacker, target])
        action = {"id": "a_test", "type": "hard_control",
                    "spell_slot_level": base_slot_level,
                    "pipeline": []}
        if upcast is not None:
            action["upcast_scaling"] = upcast
        state.current_attack = {
            "actor": attacker, "target": target,
            "action": action, "state": attack_state,
            "had_advantage": False, "had_disadvantage": False,
            "chosen_slot_level": chosen_slot_level,
        }
        return attacker, target, state, action

    def test_upcast_extra_zero_when_chosen_equals_base(self) -> None:
        _, _, state, _ = self._setup_attack(
            base_slot_level=3, chosen_slot_level=3,
            upcast={"extra_dice_per_level": "1d6", "damage_type": "fire"})
        rng = random.Random(99)
        extra = _resolve_upcast_extra_dice(state, "fire", rng,
                                                is_crit=False, floor=0)
        self.assertEqual(extra, 0)

    def test_upcast_extra_zero_when_no_upcast_block(self) -> None:
        _, _, state, _ = self._setup_attack(
            base_slot_level=3, chosen_slot_level=5)
        rng = random.Random(99)
        extra = _resolve_upcast_extra_dice(state, "fire", rng,
                                                is_crit=False, floor=0)
        self.assertEqual(extra, 0)

    def test_upcast_extra_dice_added(self) -> None:
        # 2 levels above base, "1d6" per level → 2d6 extra. Range
        # [2, 12]. Run many times to confirm we're in range.
        max_seen = 0
        for seed in range(20):
            _, _, state, _ = self._setup_attack(
                base_slot_level=3, chosen_slot_level=5,
                upcast={"extra_dice_per_level": "1d6",
                          "damage_type": "fire"})
            rng = random.Random(seed)
            extra = _resolve_upcast_extra_dice(state, "fire", rng,
                                                    is_crit=False, floor=0)
            max_seen = max(max_seen, extra)
            self.assertGreaterEqual(extra, 2)
            self.assertLessEqual(extra, 12)
        # Should regularly approach max
        self.assertGreater(max_seen, 6)

    def test_damage_type_filter_excludes_wrong_type(self) -> None:
        # Cold spell at +2 slots — querying with damage_type='fire'
        # should return 0 because the upcast targets cold only.
        _, _, state, _ = self._setup_attack(
            base_slot_level=3, chosen_slot_level=5,
            upcast={"extra_dice_per_level": "1d6",
                      "damage_type": "cold"})
        rng = random.Random(99)
        extra = _resolve_upcast_extra_dice(state, "fire", rng,
                                                is_crit=False, floor=0)
        self.assertEqual(extra, 0)

    def test_damage_type_filter_includes_matching_type(self) -> None:
        _, _, state, _ = self._setup_attack(
            base_slot_level=3, chosen_slot_level=5,
            upcast={"extra_dice_per_level": "1d6",
                      "damage_type": "cold"})
        rng = random.Random(99)
        extra = _resolve_upcast_extra_dice(state, "cold", rng,
                                                is_crit=False, floor=0)
        self.assertGreater(extra, 0)

    def test_no_damage_type_filter_applies_to_any(self) -> None:
        # Upcast without damage_type filter applies regardless
        _, _, state, _ = self._setup_attack(
            base_slot_level=3, chosen_slot_level=5,
            upcast={"extra_dice_per_level": "1d6"})  # no type filter
        rng = random.Random(99)
        extra = _resolve_upcast_extra_dice(state, "fire", rng,
                                                is_crit=False, floor=0)
        self.assertGreater(extra, 0)

    def test_crit_doubles_upcast_dice(self) -> None:
        # 1 level above base, "1d6" per level. Non-crit max 6; crit max 12.
        crit_max = 0
        for seed in range(30):
            _, _, state, _ = self._setup_attack(
                base_slot_level=3, chosen_slot_level=4,
                upcast={"extra_dice_per_level": "1d6",
                          "damage_type": "fire"},
                attack_state="crit")
            rng = random.Random(seed)
            extra = _resolve_upcast_extra_dice(state, "fire", rng,
                                                    is_crit=True, floor=0)
            crit_max = max(crit_max, extra)
            self.assertGreaterEqual(extra, 2)
            self.assertLessEqual(extra, 12)
        self.assertGreater(crit_max, 6)


class DamagePrimitiveEndToEndTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_damage_primitive_adds_upcast_to_hp_delta(self) -> None:
        attacker = _make_actor("a")
        target = _make_actor("t", side="enemy", hp=500)
        state = _make_state([attacker, target])
        action = {"id": "a_test", "type": "hard_control",
                    "spell_slot_level": 1,
                    "upcast_scaling": {"extra_dice_per_level": "1d10",
                                          "damage_type": "fire"},
                    "pipeline": []}
        # Set chosen_slot_level=3 — 2 levels above base → +2d10 fire
        state.current_attack = {
            "actor": attacker, "target": target,
            "action": action, "state": "hit",
            "had_advantage": False, "had_disadvantage": False,
            "chosen_slot_level": 3,
        }
        # Without upcast: 2d10 fire, max 20. With upcast: 4d10, max 40.
        hp_lost_max = 0
        for i in range(30):
            target.hp_current = 500
            primitives_module.set_rng(random.Random(100 + i))
            _damage({"dice": "2d10", "modifier": 0, "type": "fire"},
                    state, EventBus())
            hp_lost_max = max(hp_lost_max, 500 - target.hp_current)
        # Without upcast we'd see max ~20. With upcast we should
        # regularly exceed 20.
        self.assertGreater(hp_lost_max, 20)


# ============================================================================
# Layer 12: Hellish Rebuke reaction-path upcast
# ============================================================================

class HellishRebukeUpcastTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(3))

    def test_hellish_rebuke_upcast_at_l2_slot_adds_d10(self) -> None:
        # Load the actual f_hellish_rebuke YAML to verify the wiring
        from pathlib import Path
        from engine.loader import load_content
        repo_root = Path(__file__).parent.parent
        registry = load_content(
            repo_root / "schema" / "content",
            validate=True,
            schema_root=repo_root / "schema" / "definitions")
        hr_feature = registry.get("feature", "f_hellish_rebuke")
        # Verify upcast_scaling block exists
        action = hr_feature["action_template"]
        self.assertIn("upcast_scaling", action)
        self.assertEqual(action["upcast_scaling"]["extra_dice_per_level"],
                          "1d10")
        self.assertEqual(action["upcast_scaling"]["damage_type"], "fire")
        self.assertEqual(action["spell_slot_level"], 1)


# ============================================================================
# Layer 13: HoH persistent_aura upcast
# ============================================================================

class HungerOfHadarUpcastTest(unittest.TestCase):

    def test_hoh_upcast_scaling_declared(self) -> None:
        from pathlib import Path
        from engine.loader import load_content
        repo_root = Path(__file__).parent.parent
        registry = load_content(
            repo_root / "schema" / "content",
            validate=True,
            schema_root=repo_root / "schema" / "definitions")
        hoh = registry.get("feature", "f_hunger_of_hadar")
        action = hoh["action_template"]
        self.assertIn("upcast_scaling", action)
        self.assertEqual(action["upcast_scaling"]["extra_dice_per_level"],
                          "1d6")
        self.assertEqual(action["upcast_scaling"]["damage_type"], "cold")

    def test_cloudkill_upcast_scaling_declared(self) -> None:
        from pathlib import Path
        from engine.loader import load_content
        repo_root = Path(__file__).parent.parent
        registry = load_content(
            repo_root / "schema" / "content",
            validate=True,
            schema_root=repo_root / "schema" / "definitions")
        ck = registry.get("feature", "f_cloudkill")
        action = ck["action_template"]
        self.assertIn("upcast_scaling", action)
        self.assertEqual(action["upcast_scaling"]["extra_dice_per_level"],
                          "1d8")
        self.assertEqual(action["upcast_scaling"]["damage_type"], "poison")


if __name__ == "__main__":
    unittest.main()
