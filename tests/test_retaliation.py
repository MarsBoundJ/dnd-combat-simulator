"""Retaliation (Path of the Berserker, Barbarian L10).

A damage_taken reaction: when an adjacent enemy damages the Barbarian,
they take a Reaction to make one melee weapon attack back. Routed
through the reactor's real weapon (Rage damage / masteries apply).

Layers:
  1. Condition gating: fires only when a living enemy within 5 ft dealt
     the damage to the reactor (not allies, not far, not when reaction
     spent).
  2. Strike resolution: the attacker takes damage; the reaction slot is
     consumed.
  3. Loop safety: two adjacent creatures that both have Retaliation
     resolve to one swing each, not an infinite volley.
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.reactions import resolve_reaction_triggers
from engine.core.state import Actor, CombatState, Encounter


_RETALIATION = {
    "id": "a_retaliation", "name": "Retaliation", "type": "weapon_attack",
    "slot": "reaction", "trigger": "damage_taken",
    "condition": "damaged_by_adjacent_creature",
    "pipeline": [{"primitive": "melee_retaliation"}],
}


def _greataxe(bonus=9):
    return {
        "id": "a_greataxe", "name": "Greataxe", "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
             "params": {"kind": "melee", "ability": "str",
                          "bonus": bonus, "reach_ft": 5}},
            {"primitive": "damage",
             "params": {"dice": "1d12", "type": "slashing"},
             "when": {"condition": "combat.attack_state == hit"}},
        ],
    }


def _abil(**ov):
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    for k, v in ov.items():
        ab[k] = {"score": v, "save": 0}
    return ab


def _actor(aid, *, side, position, actions=None, ac=12, hp=80,
             str_score=20):
    ab = _abil(str=str_score)
    return Actor(
        id=aid, name=aid,
        template={"id": f"t_{aid}", "name": aid, "abilities": ab,
                    "cr": {"proficiency_bonus": 4},
                    "actions": actions or []},
        side=side, hp_current=hp, hp_max=hp, ac=ac, position=position,
        speed={"walk": 30}, abilities=ab)


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


def _damage_event(target, attacker):
    return {"target_id": target.id, "target": target,
            "attacker": attacker, "attacker_id": attacker.id,
            "amount": 10, "type": "slashing"}


class RetaliationFiresTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_adjacent_enemy_takes_a_swing_back(self):
        zerk = _actor("zerk", side="pc", position=(0, 0),
                        actions=[_greataxe(), dict(_RETALIATION)])
        foe = _actor("foe", side="enemy", position=(1, 0), ac=10, hp=60)
        st = _state([zerk, foe])
        fired = resolve_reaction_triggers(
            "damage_taken", _damage_event(zerk, foe), st, EventBus())
        self.assertEqual(fired, 1)
        self.assertLess(foe.hp_current, 60)              # took the swing
        self.assertTrue(zerk.actions_used_this_turn.get("reaction"))

    def test_far_attacker_does_not_trigger(self):
        zerk = _actor("zerk", side="pc", position=(0, 0),
                        actions=[_greataxe(), dict(_RETALIATION)])
        foe = _actor("foe", side="enemy", position=(3, 0), ac=10, hp=60)  # 15 ft
        st = _state([zerk, foe])
        fired = resolve_reaction_triggers(
            "damage_taken", _damage_event(zerk, foe), st, EventBus())
        self.assertEqual(fired, 0)
        self.assertEqual(foe.hp_current, 60)

    def test_ally_source_does_not_trigger(self):
        zerk = _actor("zerk", side="pc", position=(0, 0),
                        actions=[_greataxe(), dict(_RETALIATION)])
        friend = _actor("friend", side="pc", position=(1, 0), hp=60)
        st = _state([zerk, friend])
        fired = resolve_reaction_triggers(
            "damage_taken", _damage_event(zerk, friend), st, EventBus())
        self.assertEqual(fired, 0)

    def test_no_swing_when_reaction_spent(self):
        zerk = _actor("zerk", side="pc", position=(0, 0),
                        actions=[_greataxe(), dict(_RETALIATION)])
        zerk.actions_used_this_turn["reaction"] = True
        foe = _actor("foe", side="enemy", position=(1, 0), ac=10, hp=60)
        st = _state([zerk, foe])
        fired = resolve_reaction_triggers(
            "damage_taken", _damage_event(zerk, foe), st, EventBus())
        self.assertEqual(fired, 0)
        self.assertEqual(foe.hp_current, 60)

    def test_no_melee_weapon_no_swing(self):
        # Reactor with only the reaction action (no weapon) makes no swing.
        zerk = _actor("zerk", side="pc", position=(0, 0),
                        actions=[dict(_RETALIATION)])
        foe = _actor("foe", side="enemy", position=(1, 0), ac=10, hp=60)
        st = _state([zerk, foe])
        fired = resolve_reaction_triggers(
            "damage_taken", _damage_event(zerk, foe), st, EventBus())
        # The reaction is eligible + fires, but the strike is a no-op.
        self.assertEqual(foe.hp_current, 60)


class RetaliationLoopSafetyTest(unittest.TestCase):
    """Two adjacent creatures that both have Retaliation must resolve to
    one swing each — the nested damage_taken from the first swing must
    not recurse forever (Retaliation has no slot to self-limit)."""

    def setUp(self):
        primitives_module.set_rng(random.Random(5))

    def test_mutual_retaliation_terminates(self):
        a = _actor("a", side="pc", position=(0, 0), ac=8, hp=200,
                     actions=[_greataxe(bonus=12), dict(_RETALIATION)])
        b = _actor("b", side="enemy", position=(1, 0), ac=8, hp=200,
                     actions=[_greataxe(bonus=12), dict(_RETALIATION)])
        st = _state([a, b])
        # b damaged a → a retaliates b → b's damage_taken could retaliate
        # a → ... must terminate with both reactions spent.
        fired = resolve_reaction_triggers(
            "damage_taken", _damage_event(a, b), st, EventBus())
        self.assertGreaterEqual(fired, 1)
        self.assertTrue(a.actions_used_this_turn.get("reaction"))
        # b's counter-retaliation (from a's swing) also spent its reaction.
        self.assertTrue(b.actions_used_this_turn.get("reaction"))


if __name__ == "__main__":
    unittest.main()
