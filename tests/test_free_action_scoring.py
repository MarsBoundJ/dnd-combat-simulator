"""Free-action scoring tests (PR #70).

Layers:
  1. free_action_fired event now carries a `score` field
  2. min_score_to_fire gate: skip with reason=below_min_score
     when score < threshold
  3. min_score_to_fire default 0 → always-fire preserved (v1
     Nick behavior unchanged)
  4. min_score_to_fire with positive threshold can skip
  5. Score reflects actual eHP (weapon attack vs target)
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core.runner import EncounterRunner
from engine.core.state import Actor, CombatState, Encounter


# ============================================================================
# Helpers (mirrors test_nick_mastery FreePhaseTest)
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0),
                  free_actions=None, normal_actions=None) -> Actor:
    abilities = {k: {"score": 14 if k == "str" else 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    actions = list(normal_actions or [])
    actions.extend(list(free_actions or []))
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                 "abilities": abilities,
                 "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                 "actions": actions}
    return Actor(id=actor_id, name=actor_id, template=template,
                  side=side,
                  hp_current=30, hp_max=30, ac=14,
                  speed={"walk": 30}, position=position,
                  abilities=abilities)


def _state_with(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _free_attack(action_id="a_offhand_nick",
                    min_score_to_fire=None,
                    bonus=4, dice="1d6", modifier=3):
    action = {
        "id": action_id, "name": action_id,
        "type": "weapon_attack", "slot": "free",
        "nick_active": True,
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": bonus,
                          "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": modifier,
                          "type": "piercing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }
    if min_score_to_fire is not None:
        action["min_score_to_fire"] = min_score_to_fire
    return action


# ============================================================================
# Layer 1: free_action_fired carries score
# ============================================================================

class FreeActionScoreLoggingTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_fired_event_has_score(self) -> None:
        actor = _make_actor("rogue", free_actions=[_free_attack()])
        enemy = _make_actor("dummy", side="enemy", position=(1, 0))
        state = _state_with([actor, enemy])
        runner = EncounterRunner.new(state.encounter, seed=1)
        runner._run_free_phase(actor, state)
        fire_events = [e for e in state.event_log
                          if e.get("event") == "free_action_fired"]
        self.assertEqual(len(fire_events), 1)
        self.assertIn("score", fire_events[0])
        self.assertIsInstance(fire_events[0]["score"], (int, float))

    def test_score_positive_for_reachable_enemy(self) -> None:
        # Weapon: 1d6 + 3 = 6.5 avg. Hit prob vs AC 14 with +4
        # bonus is moderate. eHP > 0 expected.
        actor = _make_actor("rogue", free_actions=[_free_attack()])
        enemy = _make_actor("dummy", side="enemy", position=(1, 0))
        state = _state_with([actor, enemy])
        runner = EncounterRunner.new(state.encounter, seed=1)
        runner._run_free_phase(actor, state)
        fire_events = [e for e in state.event_log
                          if e.get("event") == "free_action_fired"]
        self.assertGreater(fire_events[0]["score"], 0)


# ============================================================================
# Layer 2: min_score_to_fire gate
# ============================================================================

class MinScoreToFireGateTest(unittest.TestCase):

    def test_high_threshold_skips_with_event(self) -> None:
        # min_score 100 — far above what a 1d6+3 attack scores
        action = _free_attack(min_score_to_fire=100)
        actor = _make_actor("rogue", free_actions=[action])
        enemy = _make_actor("dummy", side="enemy", position=(1, 0))
        state = _state_with([actor, enemy])
        runner = EncounterRunner.new(state.encounter, seed=1)
        runner._run_free_phase(actor, state)
        skip_events = [e for e in state.event_log
                          if e.get("event") == "free_action_skipped"
                          and e.get("reason") == "below_min_score"]
        self.assertEqual(len(skip_events), 1)
        self.assertEqual(skip_events[0]["min_score"], 100.0)
        self.assertLess(skip_events[0]["score"], 100.0)

    def test_low_threshold_fires(self) -> None:
        # min_score 0.5 — easily passable for a 1d6+3 attack
        action = _free_attack(min_score_to_fire=0.5)
        actor = _make_actor("rogue", free_actions=[action])
        enemy = _make_actor("dummy", side="enemy", position=(1, 0))
        state = _state_with([actor, enemy])
        runner = EncounterRunner.new(state.encounter, seed=1)
        runner._run_free_phase(actor, state)
        fire_events = [e for e in state.event_log
                          if e.get("event") == "free_action_fired"]
        self.assertEqual(len(fire_events), 1)


# ============================================================================
# Layer 3: default behavior unchanged (Nick v1 always-fire)
# ============================================================================

class DefaultAlwaysFireTest(unittest.TestCase):

    def test_no_min_score_fires_normally(self) -> None:
        # No min_score_to_fire on the action → default 0 → fires
        action = _free_attack()    # no threshold
        actor = _make_actor("rogue", free_actions=[action])
        enemy = _make_actor("dummy", side="enemy", position=(1, 0))
        state = _state_with([actor, enemy])
        runner = EncounterRunner.new(state.encounter, seed=1)
        runner._run_free_phase(actor, state)
        fire_events = [e for e in state.event_log
                          if e.get("event") == "free_action_fired"]
        self.assertEqual(len(fire_events), 1)

    def test_explicit_zero_threshold_fires(self) -> None:
        action = _free_attack(min_score_to_fire=0.0)
        actor = _make_actor("rogue", free_actions=[action])
        enemy = _make_actor("dummy", side="enemy", position=(1, 0))
        state = _state_with([actor, enemy])
        runner = EncounterRunner.new(state.encounter, seed=1)
        runner._run_free_phase(actor, state)
        fire_events = [e for e in state.event_log
                          if e.get("event") == "free_action_fired"]
        self.assertEqual(len(fire_events), 1)


if __name__ == "__main__":
    unittest.main()
