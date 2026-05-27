"""Total Cover auto-miss tests (PR #76).

Layers:
  1. _cover_ac_bonus returns 0 for 'total' (not an AC bump)
  2. _is_total_cover predicate
  3. _attack_roll auto-misses target with cover='total'
  4. _attack_roll event log records reason='total_cover'
  5. Other cover values still apply AC bonuses correctly
  6. Candidate generator filters total-cover from weapon_attack
  7. Candidate generator filters total-cover from multiattack
  8. Candidate generator filters total-cover from hard_control
  9. AoE attacks (aoe_attack) STILL affect total-cover targets
 10. Mixed: some enemies total-cover, others not — only non-total ones
     in single-target candidates; AoE picks all
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core import pipeline
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import _attack_roll, _cover_ac_bonus, _is_total_cover


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0), ac=14,
                  cover="none", hp=30):
    abilities = {k: {"score": 14 if k == "str" else 10,
                       "save": 2 if k == "str" else 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [],
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp, ac=ac,
        speed={"walk": 30}, position=position,
        abilities=abilities, cover=cover,
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _attack_context(state, attacker, target, action):
    state.current_attack = {
        "actor": attacker, "target": target,
        "action": action, "state": None,
        "had_advantage": False, "had_disadvantage": False,
    }


def _weapon_action(action_id="a_sword"):
    return {
        "id": action_id, "type": "weapon_attack",
        "pipeline": [{"primitive": "attack_roll",
                        "params": {"kind": "melee", "ability": "str",
                                     "bonus": 5, "reach_ft": 5}}],
    }


# ============================================================================
# Layer 1: _cover_ac_bonus
# ============================================================================

class CoverAcBonusTest(unittest.TestCase):

    def test_total_cover_returns_zero(self) -> None:
        # Total cover is NOT an AC bonus — it's the auto-miss case
        self.assertEqual(_cover_ac_bonus("total"), 0)

    def test_half_still_two(self) -> None:
        self.assertEqual(_cover_ac_bonus("half"), 2)

    def test_three_quarters_still_five(self) -> None:
        self.assertEqual(_cover_ac_bonus("three_quarters"), 5)

    def test_none_zero(self) -> None:
        self.assertEqual(_cover_ac_bonus("none"), 0)


# ============================================================================
# Layer 2: _is_total_cover predicate
# ============================================================================

class IsTotalCoverPredicateTest(unittest.TestCase):

    def test_total_returns_true(self) -> None:
        target = _make_actor("t", cover="total")
        self.assertTrue(_is_total_cover(target))

    def test_other_values_return_false(self) -> None:
        for cover in ("none", "half", "three_quarters"):
            target = _make_actor("t", cover=cover)
            self.assertFalse(_is_total_cover(target),
                              f"cover={cover!r} should be False")


# ============================================================================
# Layer 3+4: _attack_roll auto-miss + telemetry
# ============================================================================

class TotalCoverAutoMissTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_total_cover_target_auto_misses(self) -> None:
        attacker = _make_actor("attacker")
        target = _make_actor("dummy", side="enemy", position=(1, 0),
                                cover="total")
        state = _make_state([attacker, target])
        action = _weapon_action()
        _attack_context(state, attacker, target, action)
        result = _attack_roll({"kind": "melee", "ability": "str",
                                  "bonus": 5, "reach_ft": 5},
                                state, EventBus())
        self.assertEqual(result["state"], "miss")
        self.assertEqual(result["reason"], "total_cover")
        # Verify target HP unchanged (no damage from auto-miss)
        self.assertEqual(target.hp_current, target.hp_max)

    def test_total_cover_logs_attack_roll_event_with_reason(self) -> None:
        attacker = _make_actor("attacker")
        target = _make_actor("dummy", side="enemy", position=(1, 0),
                                cover="total")
        state = _make_state([attacker, target])
        action = _weapon_action()
        _attack_context(state, attacker, target, action)
        _attack_roll({"kind": "melee", "ability": "str",
                       "bonus": 5, "reach_ft": 5},
                      state, EventBus())
        events = [e for e in state.event_log
                    if e.get("event") == "attack_roll"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["result"], "miss")
        self.assertEqual(events[0]["reason"], "total_cover")
        # Should NOT have a d20 field — no roll happened
        self.assertNotIn("d20", events[0])

    def test_no_d20_consumed_on_total_cover(self) -> None:
        # Verify the RNG is NOT advanced when total cover triggers
        # auto-miss. Compare RNG state by rolling after the call.
        attacker = _make_actor("attacker")
        target = _make_actor("dummy", side="enemy", position=(1, 0),
                                cover="total")
        state = _make_state([attacker, target])
        action = _weapon_action()
        _attack_context(state, attacker, target, action)
        # Seed deterministically + check what the next d20 would be
        primitives_module.set_rng(random.Random(42))
        _attack_roll({"kind": "melee", "ability": "str",
                       "bonus": 5, "reach_ft": 5},
                      state, EventBus())
        # After the auto-miss, RNG should be unchanged.
        first_post_call_d20 = primitives_module._rng.randint(1, 20)
        # Re-seed + roll directly for comparison
        rng_check = random.Random(42)
        expected_d20 = rng_check.randint(1, 20)
        self.assertEqual(first_post_call_d20, expected_d20)


# ============================================================================
# Layer 5: other cover values still apply normally
# ============================================================================

class CoverIntegrationStillWorksTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(99))

    def test_half_cover_does_not_auto_miss(self) -> None:
        attacker = _make_actor("attacker")
        target = _make_actor("dummy", side="enemy", position=(1, 0),
                                cover="half")
        state = _make_state([attacker, target])
        action = _weapon_action()
        _attack_context(state, attacker, target, action)
        result = _attack_roll({"kind": "melee", "ability": "str",
                                  "bonus": 5, "reach_ft": 5},
                                state, EventBus())
        # Should resolve normally (hit or miss based on roll)
        self.assertIn(result["state"], ("hit", "crit", "miss"))
        self.assertNotEqual(result.get("reason"), "total_cover")

    def test_three_quarters_does_not_auto_miss(self) -> None:
        attacker = _make_actor("attacker")
        target = _make_actor("dummy", side="enemy", position=(1, 0),
                                cover="three_quarters")
        state = _make_state([attacker, target])
        action = _weapon_action()
        _attack_context(state, attacker, target, action)
        result = _attack_roll({"kind": "melee", "ability": "str",
                                  "bonus": 5, "reach_ft": 5},
                                state, EventBus())
        self.assertIn(result["state"], ("hit", "crit", "miss"))


# ============================================================================
# Layer 6+7+8: candidate generator filters
# ============================================================================

class CandidateGeneratorFiltersTest(unittest.TestCase):

    def _attacker_with_action(self, action):
        attacker = _make_actor("attacker")
        attacker.template["actions"] = [action]
        return attacker

    def test_weapon_attack_filters_total_cover_target(self) -> None:
        attacker = self._attacker_with_action(_weapon_action())
        target = _make_actor("dummy", side="enemy", position=(1, 0),
                                cover="total")
        state = _make_state([attacker, target])
        candidates = pipeline.generate_candidates(attacker, state, slot="action")
        # No weapon_attack candidate should exist against the
        # total-cover target
        weapon_candidates = [c for c in candidates
                                if c.get("kind") == "weapon_attack"]
        self.assertEqual(len(weapon_candidates), 0)

    def test_weapon_attack_includes_partial_cover_targets(self) -> None:
        attacker = self._attacker_with_action(_weapon_action())
        target = _make_actor("dummy", side="enemy", position=(1, 0),
                                cover="three_quarters")
        state = _make_state([attacker, target])
        candidates = pipeline.generate_candidates(attacker, state, slot="action")
        weapon_candidates = [c for c in candidates
                                if c.get("kind") == "weapon_attack"]
        self.assertEqual(len(weapon_candidates), 1)

    def test_multiattack_filters_total_cover_targets(self) -> None:
        weapon = _weapon_action()
        multi = {
            "id": "a_extra", "type": "multiattack",
            "count": 2, "sub_actions": [weapon["id"]] * 2,
        }
        attacker = _make_actor("attacker")
        attacker.template["actions"] = [weapon, multi]
        target = _make_actor("dummy", side="enemy", position=(1, 0),
                                cover="total")
        state = _make_state([attacker, target])
        candidates = pipeline.generate_candidates(attacker, state, slot="action")
        multi_candidates = [c for c in candidates
                              if c.get("kind") == "multiattack"]
        # No multiattack candidate either (no in-range targetable enemy)
        self.assertEqual(len(multi_candidates), 0)

    def test_hard_control_filters_total_cover_target(self) -> None:
        hold_person = {
            "id": "a_hold", "type": "hard_control",
            "range_ft": 60,
            "spell_slot_level": 2,
            "pipeline": [
                {"primitive": "forced_save",
                  "params": {"ability": "wisdom", "dc": 13,
                              "on_fail": [{"primitive": "apply_condition",
                                            "params": {"condition_id": "co_paralyzed"}}]}},
            ],
        }
        attacker = _make_actor("attacker")
        attacker.template["actions"] = [hold_person]
        attacker.spell_slots = {2: 1}
        target = _make_actor("dummy", side="enemy", position=(10, 0),
                                cover="total")
        state = _make_state([attacker, target])
        candidates = pipeline.generate_candidates(attacker, state, slot="action")
        hc_candidates = [c for c in candidates
                          if c.get("kind") == "hard_control"]
        self.assertEqual(len(hc_candidates), 0)


# ============================================================================
# Layer 9: AoE still affects total-cover targets
# ============================================================================

class AoEStillAffectsTotalCoverTest(unittest.TestCase):

    def test_fireball_aoe_picks_total_cover_target_as_anchor(self) -> None:
        # AoE candidate generation enumerates ALL living enemies as
        # possible anchors regardless of cover. Total cover doesn't
        # exclude the target from the area.
        fireball = {
            "id": "a_fireball", "type": "aoe_attack",
            "spell_slot_level": 3,
            "area": {"shape": "sphere", "radius_ft": 20,
                       "range_ft": 150},
            "pipeline": [],
        }
        attacker = _make_actor("attacker")
        attacker.template["actions"] = [fireball]
        attacker.spell_slots = {3: 1}
        # All three enemies, one with total cover
        e1 = _make_actor("e1", side="enemy", position=(10, 0))
        e2 = _make_actor("e2", side="enemy", position=(15, 0),
                          cover="total")
        e3 = _make_actor("e3", side="enemy", position=(20, 0))
        state = _make_state([attacker, e1, e2, e3])
        candidates = pipeline.generate_candidates(attacker, state, slot="action")
        aoe_candidates = [c for c in candidates
                            if c.get("kind") == "aoe_attack"]
        # Should have 3 candidates (one anchored on each enemy
        # including the total-cover one)
        self.assertEqual(len(aoe_candidates), 3)
        # And the total-cover enemy SHOULD be among the anchors
        anchor_ids = {c.get("target").id for c in aoe_candidates}
        self.assertIn("e2", anchor_ids)


# ============================================================================
# Layer 10: mixed scenario
# ============================================================================

class MixedCoverScenarioTest(unittest.TestCase):

    def test_mixed_only_non_total_in_weapon_candidates(self) -> None:
        # All three enemies adjacent (within 5 ft reach). Total cover
        # filters out sheltered; good + partial both qualify.
        attacker = _make_actor("attacker", position=(0, 0))
        attacker.template["actions"] = [_weapon_action()]
        good = _make_actor("good", side="enemy", position=(1, 0))
        sheltered = _make_actor("sheltered", side="enemy", position=(0, 1),
                                  cover="total")
        partial = _make_actor("partial", side="enemy", position=(1, 1),
                                cover="half")
        state = _make_state([attacker, good, sheltered, partial])
        candidates = pipeline.generate_candidates(attacker, state, slot="action")
        weapon_candidates = [c for c in candidates
                                if c.get("kind") == "weapon_attack"]
        target_ids = {c["target"].id for c in weapon_candidates}
        self.assertIn("good", target_ids)
        self.assertIn("partial", target_ids)
        self.assertNotIn("sheltered", target_ids)


if __name__ == "__main__":
    unittest.main()
