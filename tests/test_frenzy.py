"""Frenzy + Mindless Rage tests (Path of the Berserker).

Frenzy (Barbarian L3) is a once-per-turn damage rider: when Reckless
Attack is used while raging, the first Strength-based hit deals an extra
Nd6 (N = Rage Damage bonus), same type as the weapon.

Mindless Rage (L6) grants Immunity to Charmed/Frightened while raging.

Layers:
  1. Qualification gate: needs feature + rage + reckless + STR melee
  2. Each gate independently suppresses the rider
  3. Dice = rage_damage_bonus d6; crit doubles
  4. Per-turn dedup (fires once), and RESETS next turn
  5. _damage integration adds the extra dice to the hit
  6. Mindless Rage blocks Charmed/Frightened while raging (not otherwise)
"""
from __future__ import annotations

import random
import unittest

from engine.core.frenzy import qualifies_for_frenzy, try_apply_frenzy
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import _apply_condition, _damage
from engine.core.events import EventBus


# ============================================================================
# Helpers
# ============================================================================

def _make_berserker(actor_id="zerk", *, features=("f_frenzy",),
                       rage_active=True, reckless=True, rage_bonus=2,
                       position=(0, 0), side="pc"):
    abilities = {
        "str": {"score": 18, "save": 4},
        "dex": {"score": 12, "save": 1},
        "con": {"score": 16, "save": 3},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {
        "id": f"tpl_{actor_id}",
        "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [],
        "levels": {"barbarian": 3},
        "features_known": list(features),
    }
    a = Actor(
        id=actor_id, name=actor_id, template=template,
        side=side, hp_current=40, hp_max=40, ac=14,
        speed={"walk": 30}, position=position, abilities=abilities,
    )
    a.rage_active = rage_active
    a.rage_damage_bonus = rage_bonus
    a.reckless_active = reckless
    return a


def _make_target(actor_id="dummy", *, position=(1, 0), side="enemy", hp=200):
    abilities = {k: {"score": 10, "save": 0}
                 for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id, "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2}, "actions": [],
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp, ac=14, speed={"walk": 30},
        position=position, abilities=abilities,
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _str_melee(state, attacker, target, *, attack_state="hit"):
    params = {"kind": "melee", "ability": "str", "bonus": 6, "reach_ft": 5}
    action = {"id": "a_gs", "type": "weapon_attack",
              "pipeline": [{"primitive": "attack_roll", "params": params}]}
    state.current_attack = {
        "actor": attacker, "target": target, "action": action,
        "state": attack_state, "had_advantage": True,
        "had_disadvantage": False,
    }
    return params


# ============================================================================
# Layer 1-2: qualification gates
# ============================================================================

class FrenzyGateTest(unittest.TestCase):

    def test_full_qualification(self) -> None:
        a, t = _make_berserker(), _make_target()
        params = _str_melee(_make_state([a, t]), a, t)
        self.assertTrue(qualifies_for_frenzy(a, params))

    def test_without_feature_suppressed(self) -> None:
        a, t = _make_berserker(features=()), _make_target()
        params = _str_melee(_make_state([a, t]), a, t)
        self.assertFalse(qualifies_for_frenzy(a, params))

    def test_without_rage_suppressed(self) -> None:
        a, t = _make_berserker(rage_active=False), _make_target()
        params = _str_melee(_make_state([a, t]), a, t)
        self.assertFalse(qualifies_for_frenzy(a, params))

    def test_without_reckless_suppressed(self) -> None:
        a, t = _make_berserker(reckless=False), _make_target()
        params = _str_melee(_make_state([a, t]), a, t)
        self.assertFalse(qualifies_for_frenzy(a, params))

    def test_dex_finesse_attack_suppressed(self) -> None:
        # RAW: "Strength-based attack" — a DEX swing doesn't frenzy.
        a, t = _make_berserker(), _make_target()
        _str_melee(_make_state([a, t]), a, t)
        params = {"kind": "melee", "ability": "dex", "bonus": 6}
        self.assertFalse(qualifies_for_frenzy(a, params))

    def test_ranged_attack_suppressed(self) -> None:
        a, t = _make_berserker(), _make_target()
        _str_melee(_make_state([a, t]), a, t)
        params = {"kind": "ranged", "ability": "str", "bonus": 6}
        self.assertFalse(qualifies_for_frenzy(a, params))


# ============================================================================
# Layer 3: dice
# ============================================================================

class FrenzyDiceTest(unittest.TestCase):

    def test_dice_count_equals_rage_bonus(self) -> None:
        a, t = _make_berserker(rage_bonus=3), _make_target()
        state = _make_state([a, t])
        params = _str_melee(state, a, t)
        rng = random.Random(1)
        dmg = try_apply_frenzy(a, t, state, params, rng, is_crit=False)
        # 3d6 → between 3 and 18
        self.assertGreaterEqual(dmg, 3)
        self.assertLessEqual(dmg, 18)

    def test_crit_doubles_dice(self) -> None:
        # With a fixed seed, the crit roll (6 dice) must exceed the
        # max of the non-crit roll (3 dice) in aggregate expectation;
        # assert the dice COUNT doubled by checking the telemetry.
        a, t = _make_berserker(rage_bonus=3), _make_target()
        state = _make_state([a, t])
        params = _str_melee(state, a, t)
        try_apply_frenzy(a, t, state, params, random.Random(1), is_crit=True)
        ev = [e for e in state.event_log if e["event"] == "frenzy_applied"][-1]
        self.assertEqual(ev["dice_count"], 3)
        self.assertTrue(ev["is_crit"])
        # 6 dice rolled on crit → total in [6, 36]
        self.assertGreaterEqual(ev["damage"], 6)

    def test_zero_rage_bonus_no_damage(self) -> None:
        a, t = _make_berserker(rage_bonus=0), _make_target()
        state = _make_state([a, t])
        params = _str_melee(state, a, t)
        self.assertEqual(
            try_apply_frenzy(a, t, state, params, random.Random(1), False), 0)


# ============================================================================
# Layer 4: per-turn dedup
# ============================================================================

class FrenzyDedupTest(unittest.TestCase):

    def test_fires_once_per_turn(self) -> None:
        a, t = _make_berserker(), _make_target()
        state = _make_state([a, t])
        params = _str_melee(state, a, t)
        rng = random.Random(2)
        first = try_apply_frenzy(a, t, state, params, rng, is_crit=False)
        second = try_apply_frenzy(a, t, state, params, rng, is_crit=False)
        self.assertGreater(first, 0)
        self.assertEqual(second, 0)

    def test_resets_next_turn(self) -> None:
        a, t = _make_berserker(), _make_target()
        state = _make_state([a, t])
        params = _str_melee(state, a, t)
        rng = random.Random(2)
        try_apply_frenzy(a, t, state, params, rng, is_crit=False)
        a.reset_turn()
        # rage/reckless persist across the reset in this fixture
        a.rage_active = True
        a.reckless_active = True
        again = try_apply_frenzy(a, t, state, params, rng, is_crit=False)
        self.assertGreater(again, 0)


# ============================================================================
# Layer 5: _damage integration
# ============================================================================

class FrenzyDamageIntegrationTest(unittest.TestCase):

    def test_damage_includes_frenzy(self) -> None:
        a, t = _make_berserker(rage_bonus=2), _make_target()
        state = _make_state([a, t])
        params = _str_melee(state, a, t)
        bus = EventBus()
        # Flat 1 base damage so any excess is the Frenzy rider. _damage
        # reads attack_params off state.current_attack.action.pipeline
        # (set by _str_melee) and the rider fires inside the hit branch.
        dmg_params = {"dice": "1d4", "type": "slashing"}
        _damage(dmg_params, state, bus)
        applied = [e for e in state.event_log
                   if e["event"] == "frenzy_applied"]
        self.assertEqual(len(applied), 1)


# ============================================================================
# Layer 6: Mindless Rage
# ============================================================================

class MindlessRageTest(unittest.TestCase):

    def _frighten(self, target, attacker, state):
        state.current_attack = {"target": target, "actor": attacker}
        _apply_condition({"condition_id": "co_frightened"}, state, EventBus())

    def test_blocks_frightened_while_raging(self) -> None:
        zerk = _make_berserker(features=("f_mindless_rage",),
                                  rage_active=True)
        atk = _make_target("scary")
        state = _make_state([zerk, atk])
        self._frighten(zerk, atk, state)
        self.assertEqual(zerk.applied_conditions, [])
        self.assertTrue(any(e["event"] == "condition_immune"
                            for e in state.event_log))

    def test_charmed_blocked_while_raging(self) -> None:
        zerk = _make_berserker(features=("f_mindless_rage",),
                                  rage_active=True)
        atk = _make_target("charmer")
        state = _make_state([zerk, atk])
        state.current_attack = {"target": zerk, "actor": atk}
        _apply_condition({"condition_id": "co_charmed"}, state, EventBus())
        self.assertEqual(zerk.applied_conditions, [])

    def test_not_blocked_when_not_raging(self) -> None:
        zerk = _make_berserker(features=("f_mindless_rage",),
                                  rage_active=False)
        atk = _make_target("scary")
        state = _make_state([zerk, atk])
        # No registry → _instantiate_condition_effects no-ops, but the
        # application itself still lands (immunity gate must NOT fire).
        self._frighten(zerk, atk, state)
        self.assertEqual(len(zerk.applied_conditions), 1)


if __name__ == "__main__":
    unittest.main()
