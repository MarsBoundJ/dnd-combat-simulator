"""Positioning v1 tests — distance / movement / reachability / range.

Layers:
  1. Pure geometry — distance_ft (Chebyshev × 5), move_toward, required_movement_ft
  2. Targeting — closest_enemy actually uses grid distance
  3. When-clause evaluation — attacker_within_ft(N) checks real distance
  4. Reachability filter in generate_candidates (melee vs ranged)
  5. attack_roll out-of-range guard (auto-miss with telemetry)
  6. Runner integration — engaging creature moves toward target; ranged
     creature shoots from distance without moving; both-out-of-range
     creature passes turn after movement

Run via:
    python -m unittest tests.test_positioning
"""
from __future__ import annotations

import random
import unittest

from engine.core.geometry import (
    distance_ft, is_within_ft, move_toward, required_movement_ft,
    SQUARE_SIZE_FT,
)
from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Test helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "enemy",
                hp: int = 30, ac: int = 15,
                position: tuple[int, int] = (0, 0),
                speed: int = 30,
                actions: list[dict] | None = None,
                abilities: dict | None = None,
                template_extras: dict | None = None) -> Actor:
    abilities = abilities or {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 14, "save": 2},
        "con": {"score": 12, "save": 1},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 12, "save": 1},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": actions or []}
    if template_extras:
        template.update(template_extras)
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac,
                  speed={"walk": speed}, position=position,
                  abilities=abilities)


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    return state


def _melee_attack(action_id: str = "a_sword", reach: int = 5,
                   bonus: int = 5, dice: str = "1d8",
                   modifier: int = 3) -> dict:
    return {
        "id": action_id, "name": action_id, "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": bonus, "reach_ft": reach}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": modifier,
                          "type": "slashing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


def _ranged_attack(action_id: str = "a_bow", range_ft: int = 80,
                    bonus: int = 5, dice: str = "1d8",
                    modifier: int = 3) -> dict:
    return {
        "id": action_id, "name": action_id, "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "ranged", "bonus": bonus,
                          "range_ft": range_ft}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": modifier,
                          "type": "piercing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


# ============================================================================
# Pure geometry
# ============================================================================

class DistanceTest(unittest.TestCase):

    def test_same_position_zero(self) -> None:
        a = _make_actor("a", position=(3, 3))
        b = _make_actor("b", position=(3, 3))
        self.assertEqual(distance_ft(a, b), 0)

    def test_cardinal_1_square_is_5ft(self) -> None:
        a = _make_actor("a", position=(0, 0))
        b = _make_actor("b", position=(1, 0))
        self.assertEqual(distance_ft(a, b), 5)

    def test_diagonal_counts_as_5ft_per_2024_rules(self) -> None:
        """Per 2024 PHB: diagonals count as 5 ft, NOT alternating 5/10."""
        a = _make_actor("a", position=(0, 0))
        b = _make_actor("b", position=(1, 1))
        self.assertEqual(distance_ft(a, b), 5,
                          "Diagonal of 1 should be 5 ft (Chebyshev)")

    def test_3_4_distance_is_chebyshev_4(self) -> None:
        a = _make_actor("a", position=(0, 0))
        b = _make_actor("b", position=(3, 4))
        # max(3, 4) = 4 squares = 20 ft
        self.assertEqual(distance_ft(a, b), 20)

    def test_distance_is_symmetric(self) -> None:
        a = _make_actor("a", position=(2, 5))
        b = _make_actor("b", position=(8, 1))
        self.assertEqual(distance_ft(a, b), distance_ft(b, a))

    def test_distance_accepts_raw_tuples(self) -> None:
        self.assertEqual(distance_ft((0, 0), (3, 0)), 15)
        a = _make_actor("a", position=(0, 0))
        self.assertEqual(distance_ft(a, (5, 0)), 25)


class IsWithinFtTest(unittest.TestCase):

    def test_at_reach_inclusive(self) -> None:
        a = _make_actor("a", position=(0, 0))
        b = _make_actor("b", position=(1, 0))   # 5 ft away
        self.assertTrue(is_within_ft(a, b, 5))

    def test_beyond_reach(self) -> None:
        a = _make_actor("a", position=(0, 0))
        b = _make_actor("b", position=(2, 0))   # 10 ft away
        self.assertFalse(is_within_ft(a, b, 5))


class MoveTowardTest(unittest.TestCase):

    def test_move_toward_in_straight_line(self) -> None:
        mover = _make_actor("m", position=(0, 0))
        target = _make_actor("t", position=(10, 0))   # 50 ft away
        moved = move_toward(mover, target, max_ft=30)
        # 30 ft / 5 ft per square = 6 squares cardinal
        self.assertEqual(mover.position, (6, 0))
        self.assertEqual(moved, 30)

    def test_move_toward_diagonal(self) -> None:
        mover = _make_actor("m", position=(0, 0))
        target = _make_actor("t", position=(5, 5))   # 25 ft (Chebyshev)
        moved = move_toward(mover, target, max_ft=15)
        # 3 diagonal squares: (1,1), (2,2), (3,3)
        self.assertEqual(mover.position, (3, 3))
        self.assertEqual(moved, 15)

    def test_move_stops_on_target_square(self) -> None:
        """Should not push past the target."""
        mover = _make_actor("m", position=(0, 0))
        target = _make_actor("t", position=(2, 0))   # 10 ft
        moved = move_toward(mover, target, max_ft=100)
        self.assertEqual(mover.position, (2, 0))
        self.assertEqual(moved, 10)

    def test_no_movement_if_less_than_one_square(self) -> None:
        mover = _make_actor("m", position=(0, 0))
        target = _make_actor("t", position=(5, 0))
        moved = move_toward(mover, target, max_ft=4)
        self.assertEqual(mover.position, (0, 0))
        self.assertEqual(moved, 0)

    def test_already_at_target_no_movement(self) -> None:
        mover = _make_actor("m", position=(3, 3))
        target = _make_actor("t", position=(3, 3))
        moved = move_toward(mover, target, max_ft=30)
        self.assertEqual(moved, 0)


class RequiredMovementTest(unittest.TestCase):

    def test_already_in_reach_zero(self) -> None:
        a = _make_actor("a", position=(0, 0))
        b = _make_actor("b", position=(1, 0))   # 5 ft
        self.assertEqual(required_movement_ft(a, b, reach_ft=5), 0)

    def test_one_square_outside_reach(self) -> None:
        a = _make_actor("a", position=(0, 0))
        b = _make_actor("b", position=(2, 0))   # 10 ft
        # Need to close 5 ft to be at reach 5
        self.assertEqual(required_movement_ft(a, b, reach_ft=5), 5)

    def test_far_distance(self) -> None:
        a = _make_actor("a", position=(0, 0))
        b = _make_actor("b", position=(10, 0))   # 50 ft
        # Need to close 45 ft to be at reach 5
        self.assertEqual(required_movement_ft(a, b, reach_ft=5), 45)


# ============================================================================
# Targeting — closest_enemy by distance
# ============================================================================

class ClosestEnemyByDistanceTest(unittest.TestCase):

    def test_picks_closest_by_grid_distance_not_turn_order(self) -> None:
        from engine.ai import pick_target
        attacker = _make_actor("att", side="pc", position=(0, 0))
        # e1 listed first (in turn order) but FAR (50 ft)
        e1 = _make_actor("e1", side="enemy", position=(10, 0))
        # e2 listed second but CLOSE (10 ft)
        e2 = _make_actor("e2", side="enemy", position=(2, 0))
        state = _state_with([attacker, e1, e2])
        chosen = pick_target(attacker, [e1, e2], state, "closest_enemy")
        self.assertEqual(chosen.id, "e2",
                          "closest_enemy should pick by grid distance, "
                          "not turn order")

    def test_ties_broken_by_turn_order(self) -> None:
        from engine.ai import pick_target
        attacker = _make_actor("att", side="pc", position=(0, 0))
        # Both 10 ft away (one north, one east) → tie → first in turn wins
        e1 = _make_actor("e1", side="enemy", position=(2, 0))
        e2 = _make_actor("e2", side="enemy", position=(0, 2))
        state = _state_with([attacker, e1, e2])
        chosen = pick_target(attacker, [e1, e2], state, "closest_enemy")
        self.assertEqual(chosen.id, "e1")


# ============================================================================
# Reachability filter in generate_candidates
# ============================================================================

class ReachabilityFilterTest(unittest.TestCase):

    def test_melee_out_of_reach_filtered(self) -> None:
        attacker = _make_actor("att", side="pc", position=(0, 0),
                                 actions=[_melee_attack(reach=5)])
        far_enemy = _make_actor("far", side="enemy", position=(10, 0))
        state = _state_with([attacker, far_enemy])
        # Filter to weapon attacks (built-ins Dodge/Disengage always present)
        candidates = [c for c in generate_candidates(attacker, state)
                       if c["kind"] == "weapon_attack"]
        self.assertEqual(candidates, [],
                          "Melee attack against 50-ft enemy should generate "
                          "no weapon_attack candidates")

    def test_melee_in_reach_kept(self) -> None:
        attacker = _make_actor("att", side="pc", position=(0, 0),
                                 actions=[_melee_attack(reach=5)])
        close_enemy = _make_actor("close", side="enemy", position=(1, 0))
        state = _state_with([attacker, close_enemy])
        candidates = [c for c in generate_candidates(attacker, state)
                       if c["kind"] == "weapon_attack"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["target"].id, "close")

    def test_ranged_attack_reaches_distant_enemy(self) -> None:
        attacker = _make_actor("att", side="pc", position=(0, 0),
                                 actions=[_ranged_attack(range_ft=80)])
        # 70 ft away
        enemy = _make_actor("e", side="enemy", position=(14, 0))
        state = _state_with([attacker, enemy])
        candidates = [c for c in generate_candidates(attacker, state)
                       if c["kind"] == "weapon_attack"]
        self.assertEqual(len(candidates), 1,
                          "Ranged attack should reach the 70-ft enemy")

    def test_partial_filter_keeps_only_in_range(self) -> None:
        """Attacker with melee weapon vs two enemies — only the close
        one generates a candidate."""
        attacker = _make_actor("att", side="pc", position=(0, 0),
                                 actions=[_melee_attack(reach=5)])
        close = _make_actor("close", side="enemy", position=(1, 0))
        far = _make_actor("far", side="enemy", position=(10, 0))
        state = _state_with([attacker, close, far])
        candidates = [c for c in generate_candidates(attacker, state)
                       if c["kind"] == "weapon_attack"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["target"].id, "close")

    def test_heal_ally_no_reach_filter_in_v1(self) -> None:
        """Heal/buff on allies: v1 ignores reach (defer touch-range)."""
        heal_action = {
            "id": "a_cure", "type": "heal",
            "pipeline": [{"primitive": "heal",
                          "params": {"target": "ally", "dice": "1d8"}}],
        }
        caster = _make_actor("c", side="pc", position=(0, 0),
                              actions=[heal_action])
        far_ally = _make_actor("ally", side="pc", position=(20, 0))
        state = _state_with([caster, far_ally])
        candidates = generate_candidates(caster, state)
        heal_candidates = [c for c in candidates if c["kind"] == "heal"]
        # 2 candidates: caster self-heal + ally
        self.assertEqual(len(heal_candidates), 2)


# ============================================================================
# attack_roll out-of-range guard (multiattack execution safety net)
# ============================================================================

class AttackRollOutOfRangeTest(unittest.TestCase):

    def test_attack_roll_auto_misses_when_out_of_range(self) -> None:
        from engine import primitives as primitives_module
        from engine.core.events import EventBus

        primitives_module.set_rng(random.Random(0))
        attacker = _make_actor("a", side="pc", position=(0, 0))
        target = _make_actor("t", side="enemy", position=(10, 0))   # 50 ft
        state = _state_with([attacker, target])
        state.current_attack = {"actor": attacker, "target": target,
                                  "action": _melee_attack(reach=5),
                                  "state": None}

        result = primitives_module._attack_roll(
            {"kind": "melee", "bonus": 5, "reach_ft": 5},
            state, EventBus(),
        )
        self.assertEqual(result["state"], "miss")
        self.assertEqual(result["reason"], "out_of_range")
        # Log entry should record the reason
        log = [e for e in state.event_log
                if e.get("event") == "attack_roll"]
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["reason"], "out_of_range")


# ============================================================================
# When-clause evaluation
# ============================================================================

class WhenClauseDistanceTest(unittest.TestCase):

    def test_attacker_within_ft_evaluates_distance(self) -> None:
        from engine.core.modifiers import _eval_when

        close_attacker = _make_actor("a", position=(0, 0))
        far_attacker = _make_actor("af", position=(10, 0))   # 50 ft
        target = _make_actor("t", position=(1, 0))   # 5 ft from close_attacker
        state = _state_with([close_attacker, far_attacker, target])

        self.assertTrue(
            _eval_when("attacker_within_ft(5)", owner=target,
                        attacker=close_attacker, target=target, state=state)
        )
        self.assertFalse(
            _eval_when("attacker_within_ft(5)", owner=target,
                        attacker=far_attacker, target=target, state=state)
        )

    def test_attacker_not_within_ft_inverse(self) -> None:
        from engine.core.modifiers import _eval_when

        far_attacker = _make_actor("af", position=(10, 0))
        target = _make_actor("t", position=(0, 0))
        state = _state_with([far_attacker, target])
        # 50 ft apart — NOT within 5 ft → True
        self.assertTrue(
            _eval_when("attacker_not_within_ft(5)", owner=target,
                        attacker=far_attacker, target=target, state=state)
        )


# ============================================================================
# Runner integration — engaging movement
# ============================================================================

class RunnerMovementTest(unittest.TestCase):

    def test_melee_attacker_moves_to_engage_then_attacks(self) -> None:
        """A melee creature 40 ft from its target should move to engage
        and end up adjacent (within 5 ft melee reach), not stacked on
        the target's square. Initiative-independent check."""
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner
        from engine.core.geometry import distance_ft

        sword = _melee_attack(reach=5, bonus=5, dice="1d6", modifier=2)
        warrior = _make_actor("warrior", side="enemy", hp=30,
                                position=(8, 0),   # 40 ft from target
                                speed=30,
                                actions=[sword],
                                template_extras={"combat": {
                                    "initiative": {"modifier": 0, "score": 12},
                                }})
        # Dummy is immobile (speed 0) AND has no attack actions, so the
        # warrior doesn't see dummy as an in-range threat and doesn't
        # generate a built-in Dodge candidate — warrior's only option is
        # to move and engage. Without these properties, dummy would close
        # on warrior or warrior would Dodge in place.
        dummy = _make_actor("dummy", side="pc", hp=200, ac=10,
                              position=(0, 0), speed=0,
                              actions=[])
        encounter = Encounter(id="movement_test", actors=[warrior, dummy])

        primitives_module.set_rng(random.Random(1))
        runner = EncounterRunner.new(encounter, seed=1)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # Both creatures should close to engage, and at least one
        # eventually lands in reach to attack.
        warrior_moves = [e for e in state.event_log
                          if e.get("event") == "moved"
                          and e.get("actor") == "warrior"]
        warrior_attacks = [e for e in state.event_log
                            if e.get("event") == "attack_roll"
                            and e.get("actor") == "warrior"]
        self.assertGreater(len(warrior_moves), 0,
                            "Warrior at 40 ft should have moved to engage")
        self.assertGreater(len(warrior_attacks), 0,
                            "Warrior should have attacked once engaged")
        # No move should land warrior on a target's square (no overlapping
        # creatures) — distance_after should be ≥ stop_at (5 ft melee).
        for m in warrior_moves:
            self.assertGreaterEqual(m["distance_after"], 5,
                                      f"Warrior moved into target's square: {m}")

    def test_ranged_attacker_does_not_move_when_in_range(self) -> None:
        """A ranged attacker with target in range should attack from
        position without moving."""
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner

        bow = _ranged_attack(range_ft=80, bonus=10, dice="1d6", modifier=3)
        archer = _make_actor("archer", side="enemy", hp=30, ac=15,
                               position=(14, 0),   # 70 ft from dummy
                               actions=[bow],
                               template_extras={"combat": {
                                   "initiative": {"modifier": 3, "score": 18},
                               }})
        # Make dummy unable to attack back (no actions) so the encounter
        # stalls and we can examine archer's first round purely
        dummy = _make_actor("dummy", side="pc", hp=400, ac=10,
                              position=(0, 0), actions=[],
                              template_extras={"combat": {
                                  "initiative": {"modifier": 0, "score": 1},
                              }})
        encounter = Encounter(id="ranged_test", actors=[archer, dummy])

        primitives_module.set_rng(random.Random(1))
        runner = EncounterRunner.new(encounter, seed=1)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # Archer should have made attack_rolls without any moved events
        archer_moves = [e for e in state.event_log
                         if e.get("event") == "moved"
                         and e.get("actor") == "archer"]
        archer_attacks = [e for e in state.event_log
                           if e.get("event") == "attack_roll"
                           and e.get("actor") == "archer"]
        self.assertEqual(len(archer_moves), 0,
                          "Archer with target in range should not move")
        self.assertGreater(len(archer_attacks), 0,
                            "Archer should have attacked from range")

    def test_unreachable_target_after_movement_passes_turn(self) -> None:
        """An actor whose target is too far to reach even with full
        movement should pass its turn with reason
        'out_of_range_after_movement'."""
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner

        sword = _melee_attack(reach=5)
        # Very slow attacker, very far target
        slow = _make_actor("slow", side="enemy", hp=20,
                             position=(100, 0),   # 500 ft away
                             speed=10,            # only 10 ft/turn
                             actions=[sword],
                             template_extras={"combat": {
                                 "initiative": {"modifier": 0, "score": 5},
                             }})
        # Dummy on the other end
        dummy = _make_actor("dummy", side="pc", hp=20, ac=20,
                              position=(0, 0), actions=[],
                              template_extras={"combat": {
                                  "initiative": {"modifier": 0, "score": 1},
                              }})
        encounter = Encounter(id="too_far_test", actors=[slow, dummy])

        primitives_module.set_rng(random.Random(1))
        runner = EncounterRunner.new(encounter, seed=1)
        primitives_module.set_rng(runner.rng)
        # MAX_ROUNDS is 50; this should hit the cap with slow walking
        # toward dummy but never reaching attack range
        state = runner.run(seed=1)

        # Each turn should log a passed_turn event from slow
        passed = [e for e in state.event_log
                   if e.get("event") == "passed_turn"
                   and e.get("actor") == "slow"
                   and e.get("reason") == "out_of_range_after_movement"]
        self.assertGreater(len(passed), 5,
                            "Slow actor 500 ft away should pass turn most "
                            "rounds while closing")


if __name__ == "__main__":
    unittest.main()
