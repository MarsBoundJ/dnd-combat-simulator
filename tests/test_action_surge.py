"""Action Surge v1 tests — Fighter class feature, 1/short rest extra action.

Layers:
  1. Actor state: moved_this_turn / action_surge_used_this_turn fields
     default False; reset_turn clears both. Resources persist across turns.
  2. Activation gates: no charges, no living enemies, no in-reach attack
     candidate — all skip activation
  3. Charge accounting: activation decrements
     resources["action_surge_uses_remaining"]
  4. Single-turn cap: even with 2 charges, AS only fires once per turn
  5. Re-run: when AS is activated, the main slot runs twice
  6. Movement gate: AS does NOT grant a second _move_to_engage
  7. Integration: L2 fighter deals roughly 2x damage in round 1 via AS

Run via:
    python -m unittest tests.test_action_surge
"""
from __future__ import annotations

import random
import unittest

from engine.core.state import Actor, Encounter, CombatState
from engine.core.runner import EncounterRunner


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "pc", hp: int = 30,
                ac: int = 14, position: tuple[int, int] = (0, 0),
                speed: int = 30, actions: list[dict] | None = None,
                resources: dict | None = None,
                initiative_modifier: int = 0,
                initiative_score: int | None = None) -> Actor:
    abilities = {
        "str": {"score": 16, "save": 5},
        "dex": {"score": 12, "save": 1},
        "con": {"score": 14, "save": 2},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 12, "save": 1},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "combat": {
                    "armor_class": ac,
                    "hit_points": {"average": hp, "dice": "5d10",
                                     "con_contribution": 10},
                    "speed": {"walk": speed},
                    "initiative": {
                        "modifier": initiative_modifier,
                        "score": (initiative_score if initiative_score is not None
                                  else initiative_modifier + 10),
                    },
                },
                "actions": actions or []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac,
                  speed={"walk": speed}, position=position,
                  abilities=abilities,
                  resources=resources or {})


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _greatsword() -> dict:
    return {
        "id": "a_greatsword", "name": "Greatsword", "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": 6, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": "2d6", "modifier": 4, "type": "slashing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


# ============================================================================
# Actor state + reset_turn
# ============================================================================

class ActorActionSurgeStateTest(unittest.TestCase):

    def test_default_flags(self) -> None:
        a = _make_actor("a")
        self.assertFalse(a.moved_this_turn)
        self.assertFalse(a.action_surge_used_this_turn)

    def test_reset_turn_clears_both_flags(self) -> None:
        a = _make_actor("a")
        a.moved_this_turn = True
        a.action_surge_used_this_turn = True
        a.reset_turn()
        self.assertFalse(a.moved_this_turn)
        self.assertFalse(a.action_surge_used_this_turn)

    def test_reset_turn_does_NOT_clear_action_surge_charges(self) -> None:
        """Action Surge charges are per-short-rest, not per-turn —
        reset_turn must leave resources alone."""
        a = _make_actor("a", resources={"action_surge_uses_remaining": 1})
        a.reset_turn()
        self.assertEqual(a.resources.get("action_surge_uses_remaining"), 1)


# ============================================================================
# Activation gates
# ============================================================================

class ActionSurgeActivationGatesTest(unittest.TestCase):

    def _runner_with(self, actor: Actor, enemy: Actor) -> tuple[EncounterRunner, CombatState]:
        enc = Encounter(id="t", actors=[actor, enemy])
        state = CombatState(encounter=enc)
        state.turn_order = [actor.id, enemy.id]
        state.round = 1
        runner = EncounterRunner.new(enc, seed=1)
        return runner, state

    def test_no_activation_without_charges(self) -> None:
        fighter = _make_actor("fighter", side="pc",
                                actions=[_greatsword()],
                                resources={})    # no AS resource
        enemy = _make_actor("ogre", side="enemy", position=(0, 1),
                              actions=[_greatsword()])
        runner, state = self._runner_with(fighter, enemy)
        runner._maybe_activate_action_surge(fighter, state)
        self.assertFalse(fighter.action_surge_used_this_turn)

    def test_no_activation_with_zero_charges(self) -> None:
        fighter = _make_actor("fighter", side="pc",
                                actions=[_greatsword()],
                                resources={"action_surge_uses_remaining": 0})
        enemy = _make_actor("ogre", side="enemy", position=(0, 1),
                              actions=[_greatsword()])
        runner, state = self._runner_with(fighter, enemy)
        runner._maybe_activate_action_surge(fighter, state)
        self.assertFalse(fighter.action_surge_used_this_turn)

    def test_no_activation_without_living_enemies(self) -> None:
        fighter = _make_actor("fighter", side="pc",
                                actions=[_greatsword()],
                                resources={"action_surge_uses_remaining": 1})
        dead_enemy = _make_actor("ogre", side="enemy", position=(0, 1),
                                    actions=[_greatsword()])
        dead_enemy.hp_current = 0
        runner, state = self._runner_with(fighter, dead_enemy)
        runner._maybe_activate_action_surge(fighter, state)
        self.assertFalse(fighter.action_surge_used_this_turn)
        # And charges shouldn't have been spent
        self.assertEqual(fighter.resources["action_surge_uses_remaining"], 1)

    def test_no_activation_without_in_reach_attack(self) -> None:
        """Fighter is far from the enemy and would need to move. AS
        activation should wait — the v1 heuristic only fires when at
        least one weapon_attack candidate is already in reach."""
        fighter = _make_actor("fighter", side="pc",
                                actions=[_greatsword()],
                                resources={"action_surge_uses_remaining": 1})
        enemy = _make_actor("ogre", side="enemy", position=(10, 10),
                              actions=[_greatsword()])
        runner, state = self._runner_with(fighter, enemy)
        runner._maybe_activate_action_surge(fighter, state)
        self.assertFalse(fighter.action_surge_used_this_turn)
        self.assertEqual(fighter.resources["action_surge_uses_remaining"], 1)

    def test_activation_when_all_gates_pass(self) -> None:
        fighter = _make_actor("fighter", side="pc",
                                actions=[_greatsword()],
                                resources={"action_surge_uses_remaining": 1})
        enemy = _make_actor("ogre", side="enemy", position=(0, 1),
                              actions=[_greatsword()])
        runner, state = self._runner_with(fighter, enemy)
        runner._maybe_activate_action_surge(fighter, state)
        self.assertTrue(fighter.action_surge_used_this_turn)
        self.assertEqual(fighter.resources["action_surge_uses_remaining"], 0)
        # Log entry
        as_events = [e for e in state.event_log
                      if e.get("event") == "action_surge_activated"]
        self.assertEqual(len(as_events), 1)
        self.assertEqual(as_events[0]["actor"], "fighter")
        self.assertEqual(as_events[0]["charges_remaining"], 0)


# ============================================================================
# Single-turn cap (L17 fighter has 2 charges but can only AS once per turn)
# ============================================================================

class ActionSurgeSingleTurnCapTest(unittest.TestCase):

    def test_second_activation_in_same_turn_is_skipped(self) -> None:
        fighter = _make_actor("fighter", side="pc",
                                actions=[_greatsword()],
                                resources={"action_surge_uses_remaining": 2})
        enemy = _make_actor("ogre", side="enemy", position=(0, 1),
                              actions=[_greatsword()])
        enc = Encounter(id="t", actors=[fighter, enemy])
        state = CombatState(encounter=enc)
        state.turn_order = [fighter.id, enemy.id]
        state.round = 1
        runner = EncounterRunner.new(enc, seed=1)

        runner._maybe_activate_action_surge(fighter, state)
        runner._maybe_activate_action_surge(fighter, state)   # second call
        self.assertTrue(fighter.action_surge_used_this_turn)
        # Only one charge consumed
        self.assertEqual(fighter.resources["action_surge_uses_remaining"], 1)
        # Only one log entry
        as_events = [e for e in state.event_log
                      if e.get("event") == "action_surge_activated"]
        self.assertEqual(len(as_events), 1)


# ============================================================================
# Movement gate
# ============================================================================

class ActionSurgeMovementGateTest(unittest.TestCase):

    def test_move_to_engage_respects_moved_this_turn(self) -> None:
        """Once an actor has moved this turn, _move_to_engage is a no-op.
        This is what prevents Action Surge from granting a second move."""
        fighter = _make_actor("fighter", side="pc",
                                actions=[_greatsword()], position=(0, 0))
        enemy = _make_actor("ogre", side="enemy", position=(5, 5),
                              actions=[_greatsword()])
        enc = Encounter(id="t", actors=[fighter, enemy])
        state = CombatState(encounter=enc)
        state.turn_order = [fighter.id, enemy.id]
        state.round = 1
        runner = EncounterRunner.new(enc, seed=1)

        # First call: actually moves
        runner._move_to_engage(fighter, state)
        first_pos = fighter.position
        self.assertTrue(fighter.moved_this_turn)
        self.assertNotEqual(first_pos, (0, 0))

        # Second call (simulates an AS second pass): should NOT move
        runner._move_to_engage(fighter, state)
        self.assertEqual(fighter.position, first_pos)


# ============================================================================
# Integration: full turn with Action Surge → two attacks in one turn
# ============================================================================

class ActionSurgeIntegrationTest(unittest.TestCase):

    def test_fighter_with_action_surge_attacks_twice_in_one_turn(self) -> None:
        """L2 fighter (1 charge) vs tough ogre. Fighter goes first.
        Verify the event log shows two attack_roll events from the
        fighter in round 1, and the action_surge_activated event."""
        fighter = _make_actor(
            "fighter", side="pc", hp=30, position=(0, 0),
            actions=[_greatsword()],
            resources={"action_surge_uses_remaining": 1},
            initiative_modifier=30,    # force first
        )
        ogre = _make_actor(
            "ogre", side="enemy", hp=100, ac=18, position=(0, 1),
            actions=[_greatsword()],
            initiative_modifier=0,
        )
        enc = Encounter(id="action_surge_test", actors=[fighter, ogre])
        runner = EncounterRunner.new(enc, seed=1)
        state = runner.run(seed=1)

        # AS log entry present in round 1
        as_events = [e for e in state.event_log
                      if e.get("event") == "action_surge_activated"
                      and e.get("actor") == "fighter"]
        self.assertEqual(len(as_events), 1,
                          "Expected exactly one action_surge_activated event")

        # Count fighter's attack rolls within round 1 (before any
        # subsequent turn boundary). Find the first ogre turn_start as
        # the boundary.
        round1_events = []
        for e in state.event_log:
            if (e.get("event") == "turn_start"
                    and e.get("actor") == "ogre"
                    and e.get("round") == 1):
                break
            round1_events.append(e)
        fighter_attacks_r1 = [e for e in round1_events
                               if e.get("event") == "attack_roll"
                               and e.get("actor") == "fighter"]
        self.assertEqual(len(fighter_attacks_r1), 2,
                          f"Expected 2 fighter attacks in round 1 "
                          f"(action + Action Surge), got {len(fighter_attacks_r1)}")

    def test_fighter_without_action_surge_attacks_once(self) -> None:
        """Control: same fighter without resources → one attack/turn."""
        fighter = _make_actor(
            "fighter", side="pc", hp=30, position=(0, 0),
            actions=[_greatsword()],
            resources={},     # no Action Surge
            initiative_modifier=30,
        )
        ogre = _make_actor(
            "ogre", side="enemy", hp=100, ac=18, position=(0, 1),
            actions=[_greatsword()],
            initiative_modifier=0,
        )
        enc = Encounter(id="action_surge_control", actors=[fighter, ogre])
        runner = EncounterRunner.new(enc, seed=1)
        state = runner.run(seed=1)

        as_events = [e for e in state.event_log
                      if e.get("event") == "action_surge_activated"]
        self.assertEqual(len(as_events), 0)

        round1_events = []
        for e in state.event_log:
            if (e.get("event") == "turn_start"
                    and e.get("actor") == "ogre"
                    and e.get("round") == 1):
                break
            round1_events.append(e)
        fighter_attacks_r1 = [e for e in round1_events
                               if e.get("event") == "attack_roll"
                               and e.get("actor") == "fighter"]
        self.assertEqual(len(fighter_attacks_r1), 1)

    def test_fighter_does_not_double_move_with_action_surge(self) -> None:
        """Fighter starts in melee (so AS activates). After the first
        attack the only enemy dies; AS re-runs the main slot. The
        re-run path could in principle call _move_to_engage if there
        were another enemy at distance. Without the moved_this_turn
        gate, the fighter would move twice. With the gate, only one
        `moved` event per turn."""
        fighter = _make_actor(
            "fighter", side="pc", hp=30, position=(0, 0),
            actions=[_greatsword()],
            resources={"action_surge_uses_remaining": 1},
            initiative_modifier=30,
        )
        # Adjacent weak enemy (one-shot) + distant beefy enemy
        weak = _make_actor("weak", side="enemy", hp=1, ac=8,
                            position=(0, 1), actions=[_greatsword()],
                            initiative_modifier=0)
        far = _make_actor("far", side="enemy", hp=80, ac=18,
                            position=(20, 20), actions=[_greatsword()],
                            initiative_modifier=0)
        enc = Encounter(id="as_no_double_move", actors=[fighter, weak, far])
        runner = EncounterRunner.new(enc, seed=1)
        state = runner.run(seed=1)

        # Find round-1 fighter `moved` events
        round1_events = []
        for e in state.event_log:
            if (e.get("event") == "turn_start"
                    and e.get("round") == 2):
                break
            round1_events.append(e)
        fighter_moves_r1 = [e for e in round1_events
                             if e.get("event") == "moved"
                             and e.get("actor") == "fighter"]
        self.assertLessEqual(len(fighter_moves_r1), 1,
                              "Fighter must not move twice in one turn "
                              "even when Action Surge fires")


if __name__ == "__main__":
    unittest.main()
