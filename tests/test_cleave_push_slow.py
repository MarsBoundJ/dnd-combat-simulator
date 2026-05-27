"""Cleave / Push / Slow weapon mastery tests (PR #58).

Layers:
  1. Registry membership: cleave / push / slow in KNOWN_MASTERIES,
     DEFERRED_MASTERIES is empty
  2. geometry.push_creature helper
  3. Cleave per-property:
     - No second target → cleave_no_target event, no sub-attack
     - Second target in range → sub-attack fired against them
     - Once-per-turn gate (second cleave attempt skipped)
     - Reset_turn clears the per-turn gate
     - Sub-attack target must be different from primary target
     - Sub-attack target must be in attacker's reach
     - Sub-attack target must be within 5 ft of original target
     - Sub-attack target must be an enemy
  4. Push per-property:
     - Pushed 10 ft straight away from attacker
     - Diagonal direction snaps to grid
     - Zero distance when stacked on same square
     - Logs from/to positions
  5. Slow per-property:
     - Speed reduced by 10 ft on hit
     - Speed restored when source actor's turn starts (via runner)
     - No-op when target already slowed
     - Speed reduction clamped at 0
     - Logs reduction amount
  6. Dispatch:
     - Hit fires cleave / push / slow
     - Miss does NOT fire them
     - Actor doesn't know mastery → no-op
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.geometry import push_creature
from engine.core.state import Actor, CombatState, Encounter
from engine.core.weapon_masteries import (
    DEFERRED_MASTERIES, KNOWN_MASTERIES,
    apply_mastery_effects,
    expire_slow_from_source,
)


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id="a", *, side="pc", position=(0, 0),
                  hp=30, speed=30,
                  weapon_masteries=None,
                  actions=None) -> Actor:
    abilities = {k: {"score": 14 if k == "str" else 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                 "abilities": abilities,
                 "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                 "actions": actions or []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=14,
                  speed={"walk": speed}, position=position,
                  abilities=abilities,
                  weapon_masteries=list(weapon_masteries or []))


def _state_with(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _cleave_weapon_action():
    """A greatsword-shaped action with mastery=cleave baked into
    attack_roll params (matches what pc_schema would generate)."""
    return {
        "id": "a_greatsword", "name": "Greatsword",
        "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": 6, "reach_ft": 5,
                          "mastery": {
                              "id": "cleave", "ability_mod": 3,
                              "damage_type": "slashing",
                              "save_dc": 13,
                          }}},
            {"primitive": "damage",
              "params": {"dice": "2d6", "modifier": 3,
                          "type": "slashing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


# ============================================================================
# Layer 1: registry
# ============================================================================

class RegistryTest(unittest.TestCase):

    def test_cleave_in_known(self) -> None:
        self.assertIn("cleave", KNOWN_MASTERIES)

    def test_push_in_known(self) -> None:
        self.assertIn("push", KNOWN_MASTERIES)

    def test_slow_in_known(self) -> None:
        self.assertIn("slow", KNOWN_MASTERIES)

    def test_deferred_empty(self) -> None:
        self.assertEqual(DEFERRED_MASTERIES, frozenset())


# ============================================================================
# Layer 2: push_creature helper
# ============================================================================

class PushCreatureHelperTest(unittest.TestCase):

    def test_push_east(self) -> None:
        pusher = _make_actor("p", position=(0, 0))
        target = _make_actor("t", side="enemy", position=(1, 0))
        # Push direction = east (target is to the east of pusher)
        feet = push_creature(pusher, target, 10)
        self.assertEqual(feet, 10)
        self.assertEqual(target.position, (3, 0))    # +2 squares east

    def test_push_west(self) -> None:
        pusher = _make_actor("p", position=(5, 0))
        target = _make_actor("t", side="enemy", position=(3, 0))
        push_creature(pusher, target, 10)
        self.assertEqual(target.position, (1, 0))    # +2 squares west

    def test_push_diagonal(self) -> None:
        pusher = _make_actor("p", position=(0, 0))
        target = _make_actor("t", side="enemy", position=(1, 1))
        push_creature(pusher, target, 10)
        # Diagonal northeast push, 2 squares
        self.assertEqual(target.position, (3, 3))

    def test_push_stacked_no_op(self) -> None:
        # Same square → no defined direction → 0 push
        pusher = _make_actor("p", position=(3, 3))
        target = _make_actor("t", side="enemy", position=(3, 3))
        feet = push_creature(pusher, target, 10)
        self.assertEqual(feet, 0)
        self.assertEqual(target.position, (3, 3))

    def test_push_partial_distance(self) -> None:
        # 5 ft (1 square) push
        pusher = _make_actor("p", position=(0, 0))
        target = _make_actor("t", side="enemy", position=(1, 0))
        feet = push_creature(pusher, target, 5)
        self.assertEqual(feet, 5)
        self.assertEqual(target.position, (2, 0))


# ============================================================================
# Layer 3: Cleave
# ============================================================================

class CleaveTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(2))

    def test_no_second_target_in_range(self) -> None:
        attacker = _make_actor("a", weapon_masteries=["cleave"],
                                  actions=[_cleave_weapon_action()])
        primary = _make_actor("e1", side="enemy", position=(1, 0))
        # Other enemy far away from primary
        far = _make_actor("e2", side="enemy", position=(20, 20))
        state = _state_with([attacker, primary, far])
        state.current_attack = {"actor": attacker, "target": primary,
                                  "state": "hit"}
        apply_mastery_effects({"id": "cleave", "ability_mod": 3,
                                  "damage_type": "slashing",
                                  "save_dc": 13},
                                 attacker, primary, "hit", state)
        skips = [e for e in state.event_log
                    if e.get("event") == "weapon_mastery_skipped"
                    and e.get("mastery") == "cleave"]
        self.assertEqual(len(skips), 1)
        self.assertEqual(skips[0]["reason"], "no_second_target")

    def test_second_target_in_range_fires_sub_attack(self) -> None:
        attacker = _make_actor("a", weapon_masteries=["cleave"],
                                  actions=[_cleave_weapon_action()],
                                  position=(0, 0))
        primary = _make_actor("e1", side="enemy", position=(1, 0))
        second = _make_actor("e2", side="enemy", position=(1, 1))
        state = _state_with([attacker, primary, second])
        state.current_attack = {"actor": attacker, "target": primary,
                                  "state": "hit"}
        apply_mastery_effects({"id": "cleave", "ability_mod": 3,
                                  "damage_type": "slashing",
                                  "save_dc": 13},
                                 attacker, primary, "hit", state)
        applied = [e for e in state.event_log
                      if e.get("event") == "weapon_mastery_applied"
                      and e.get("mastery") == "cleave"]
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["second_target"], second.id)

    def test_once_per_turn_gate(self) -> None:
        attacker = _make_actor("a", weapon_masteries=["cleave"],
                                  actions=[_cleave_weapon_action()])
        primary = _make_actor("e1", side="enemy", position=(1, 0))
        second = _make_actor("e2", side="enemy", position=(1, 1))
        state = _state_with([attacker, primary, second])
        state.current_attack = {"actor": attacker, "target": primary,
                                  "state": "hit"}
        # First cleave fires
        apply_mastery_effects({"id": "cleave", "ability_mod": 3,
                                  "damage_type": "slashing",
                                  "save_dc": 13},
                                 attacker, primary, "hit", state)
        # Second attempt this turn → skipped
        apply_mastery_effects({"id": "cleave", "ability_mod": 3,
                                  "damage_type": "slashing",
                                  "save_dc": 13},
                                 attacker, primary, "hit", state)
        skips = [e for e in state.event_log
                    if e.get("event") == "weapon_mastery_skipped"
                    and e.get("mastery") == "cleave"
                    and e.get("reason") == "already_fired_this_turn"]
        self.assertEqual(len(skips), 1)

    def test_reset_turn_clears_cleave_gate(self) -> None:
        attacker = _make_actor("a", weapon_masteries=["cleave"])
        attacker._cleave_fired_this_turn = True
        attacker.reset_turn()
        self.assertFalse(attacker._cleave_fired_this_turn)

    def test_ally_does_not_qualify_as_second_target(self) -> None:
        attacker = _make_actor("a", weapon_masteries=["cleave"],
                                  actions=[_cleave_weapon_action()])
        primary = _make_actor("e1", side="enemy", position=(1, 0))
        ally = _make_actor("ally", side="pc", position=(1, 1))
        state = _state_with([attacker, primary, ally])
        state.current_attack = {"actor": attacker, "target": primary,
                                  "state": "hit"}
        apply_mastery_effects({"id": "cleave", "ability_mod": 3,
                                  "damage_type": "slashing",
                                  "save_dc": 13},
                                 attacker, primary, "hit", state)
        skips = [e for e in state.event_log
                    if e.get("event") == "weapon_mastery_skipped"
                    and e.get("mastery") == "cleave"]
        self.assertEqual(len(skips), 1)

    def test_actor_without_cleave_no_op(self) -> None:
        attacker = _make_actor("a", weapon_masteries=["vex"])  # not cleave
        primary = _make_actor("e1", side="enemy", position=(1, 0))
        second = _make_actor("e2", side="enemy", position=(1, 1))
        state = _state_with([attacker, primary, second])
        apply_mastery_effects({"id": "cleave", "ability_mod": 3,
                                  "damage_type": "slashing",
                                  "save_dc": 13},
                                 attacker, primary, "hit", state)
        # No events
        self.assertEqual(len(state.event_log), 0)


# ============================================================================
# Layer 4: Push
# ============================================================================

class PushTest(unittest.TestCase):

    def test_push_fires_on_hit(self) -> None:
        attacker = _make_actor("a", weapon_masteries=["push"],
                                  position=(0, 0))
        target = _make_actor("t", side="enemy", position=(1, 0))
        state = _state_with([attacker, target])
        apply_mastery_effects({"id": "push", "ability_mod": 3,
                                  "damage_type": "bludgeoning",
                                  "save_dc": 13},
                                 attacker, target, "hit", state)
        # Target moved 10 ft east
        self.assertEqual(target.position, (3, 0))
        applied = [e for e in state.event_log
                      if e.get("event") == "weapon_mastery_applied"
                      and e.get("mastery") == "push"]
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["pushed_ft"], 10)

    def test_push_does_NOT_fire_on_miss(self) -> None:
        attacker = _make_actor("a", weapon_masteries=["push"])
        target = _make_actor("t", side="enemy", position=(1, 0))
        state = _state_with([attacker, target])
        apply_mastery_effects({"id": "push", "ability_mod": 3,
                                  "damage_type": "bludgeoning",
                                  "save_dc": 13},
                                 attacker, target, "miss", state)
        self.assertEqual(target.position, (1, 0))
        self.assertEqual(len(state.event_log), 0)

    def test_push_diagonal(self) -> None:
        attacker = _make_actor("a", weapon_masteries=["push"],
                                  position=(0, 0))
        target = _make_actor("t", side="enemy", position=(1, 1))
        state = _state_with([attacker, target])
        apply_mastery_effects({"id": "push", "ability_mod": 3,
                                  "damage_type": "bludgeoning",
                                  "save_dc": 13},
                                 attacker, target, "hit", state)
        # Pushed 2 squares northeast
        self.assertEqual(target.position, (3, 3))


# ============================================================================
# Layer 5: Slow
# ============================================================================

class SlowTest(unittest.TestCase):

    def test_slow_reduces_speed(self) -> None:
        attacker = _make_actor("a", weapon_masteries=["slow"])
        target = _make_actor("t", side="enemy", speed=30)
        state = _state_with([attacker, target])
        apply_mastery_effects({"id": "slow", "ability_mod": 3,
                                  "damage_type": "slashing",
                                  "save_dc": 13},
                                 attacker, target, "hit", state)
        self.assertEqual(target.speed["walk"], 20)
        applied = [e for e in state.event_log
                      if e.get("event") == "weapon_mastery_applied"
                      and e.get("mastery") == "slow"]
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["reduction_ft"], 10)

    def test_slow_does_NOT_stack(self) -> None:
        # RAW: "doesn't exceed 10 ft if hit multiple times"
        attacker = _make_actor("a", weapon_masteries=["slow"])
        target = _make_actor("t", side="enemy", speed=30)
        state = _state_with([attacker, target])
        # First slow → speed 20
        apply_mastery_effects({"id": "slow", "ability_mod": 3,
                                  "damage_type": "slashing",
                                  "save_dc": 13},
                                 attacker, target, "hit", state)
        # Second slow → no further reduction, skip event
        apply_mastery_effects({"id": "slow", "ability_mod": 3,
                                  "damage_type": "slashing",
                                  "save_dc": 13},
                                 attacker, target, "hit", state)
        self.assertEqual(target.speed["walk"], 20)
        skips = [e for e in state.event_log
                    if e.get("event") == "weapon_mastery_skipped"
                    and e.get("mastery") == "slow"]
        self.assertEqual(len(skips), 1)

    def test_slow_clamped_at_zero(self) -> None:
        attacker = _make_actor("a", weapon_masteries=["slow"])
        target = _make_actor("t", side="enemy", speed=5)
        state = _state_with([attacker, target])
        apply_mastery_effects({"id": "slow", "ability_mod": 3,
                                  "damage_type": "slashing",
                                  "save_dc": 13},
                                 attacker, target, "hit", state)
        self.assertEqual(target.speed["walk"], 0)
        applied = [e for e in state.event_log
                      if e.get("event") == "weapon_mastery_applied"
                      and e.get("mastery") == "slow"]
        # Speed went from 5 to 0 → reduction of 5 (not 10)
        self.assertEqual(applied[0]["reduction_ft"], 5)

    def test_slow_does_NOT_fire_on_miss(self) -> None:
        attacker = _make_actor("a", weapon_masteries=["slow"])
        target = _make_actor("t", side="enemy", speed=30)
        state = _state_with([attacker, target])
        apply_mastery_effects({"id": "slow", "ability_mod": 3,
                                  "damage_type": "slashing",
                                  "save_dc": 13},
                                 attacker, target, "miss", state)
        self.assertEqual(target.speed["walk"], 30)

    def test_expire_slow_restores_speed(self) -> None:
        attacker = _make_actor("a", weapon_masteries=["slow"])
        target = _make_actor("t", side="enemy", speed=30)
        state = _state_with([attacker, target])
        apply_mastery_effects({"id": "slow", "ability_mod": 3,
                                  "damage_type": "slashing",
                                  "save_dc": 13},
                                 attacker, target, "hit", state)
        # Expire from attacker
        restored = expire_slow_from_source(attacker.id, state)
        self.assertEqual(restored, 1)
        self.assertEqual(target.speed["walk"], 30)
        self.assertIsNone(target._slow_data)

    def test_expire_slow_wrong_source_does_nothing(self) -> None:
        attacker = _make_actor("a", weapon_masteries=["slow"])
        other = _make_actor("o")
        target = _make_actor("t", side="enemy", speed=30)
        state = _state_with([attacker, other, target])
        apply_mastery_effects({"id": "slow", "ability_mod": 3,
                                  "damage_type": "slashing",
                                  "save_dc": 13},
                                 attacker, target, "hit", state)
        # Wrong source → no restoration
        restored = expire_slow_from_source(other.id, state)
        self.assertEqual(restored, 0)
        self.assertEqual(target.speed["walk"], 20)

    def test_expire_slow_multiple_targets(self) -> None:
        attacker = _make_actor("a", weapon_masteries=["slow"])
        target1 = _make_actor("t1", side="enemy", speed=30)
        target2 = _make_actor("t2", side="enemy", speed=25)
        state = _state_with([attacker, target1, target2])
        apply_mastery_effects({"id": "slow", "ability_mod": 3,
                                  "damage_type": "slashing",
                                  "save_dc": 13},
                                 attacker, target1, "hit", state)
        apply_mastery_effects({"id": "slow", "ability_mod": 3,
                                  "damage_type": "slashing",
                                  "save_dc": 13},
                                 attacker, target2, "hit", state)
        restored = expire_slow_from_source(attacker.id, state)
        self.assertEqual(restored, 2)
        self.assertEqual(target1.speed["walk"], 30)
        self.assertEqual(target2.speed["walk"], 25)


if __name__ == "__main__":
    unittest.main()
