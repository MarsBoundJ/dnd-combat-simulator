"""Divine Fury tests (Path of the Zealot, Barbarian L3).

A once-per-turn damage rider: while raging, the first weapon/Unarmed hit
each turn deals an extra 1d6 + floor(level/2) Necrotic/Radiant. Unlike
Frenzy it needs no Reckless Attack and isn't limited to Strength attacks.

Layers:
  1. Qualification: needs feature + rage + a weapon/Unarmed hit
  2. Broader than Frenzy: fires on DEX/finesse and ranged hits too
  3. Damage = 1d6 + floor(level/2); crit doubles the die, not the bonus
  4. Per-turn dedup (fires once), resets next turn
  5. _damage integration
"""
from __future__ import annotations

import random
import unittest

from engine.core.divine_fury import (
    qualifies_for_divine_fury, try_apply_divine_fury,
)
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import _damage
from engine.core.events import EventBus


def _make_zealot(actor_id="zealot", *, features=("f_divine_fury",),
                   rage_active=True, level=10, position=(0, 0), side="pc"):
    abilities = {
        "str": {"score": 18, "save": 4}, "dex": {"score": 16, "save": 3},
        "con": {"score": 16, "save": 3}, "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": 0}, "cha": {"score": 10, "save": 0},
    }
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id, "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 4}, "actions": [],
        "levels": {"barbarian": level},
        "features_known": list(features),
    }
    a = Actor(id=actor_id, name=actor_id, template=template, side=side,
                hp_current=60, hp_max=60, ac=14, speed={"walk": 30},
                position=position, abilities=abilities)
    a.rage_active = rage_active
    return a


def _make_target(actor_id="dummy", *, position=(1, 0), side="enemy", hp=200):
    abilities = {k: {"score": 10, "save": 0}
                 for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                  "abilities": abilities,
                  "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                  "actions": []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                   hp_current=hp, hp_max=hp, ac=14, speed={"walk": 30},
                   position=position, abilities=abilities)


def _make_state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


def _attack(state, attacker, target, *, kind="melee", ability="str",
              attack_state="hit"):
    params = {"kind": kind, "ability": ability, "bonus": 7}
    if kind == "melee":
        params["reach_ft"] = 5
    else:
        params["range_ft"] = 80
    action = {"id": "a_w", "type": "weapon_attack",
                "pipeline": [{"primitive": "attack_roll", "params": params}]}
    state.current_attack = {"actor": attacker, "target": target,
                              "action": action, "state": attack_state,
                              "had_advantage": False, "had_disadvantage": False}
    return params


class DivineFuryGateTest(unittest.TestCase):

    def test_full_qualification(self):
        a, t = _make_zealot(), _make_target()
        params = _attack(_make_state([a, t]), a, t)
        self.assertTrue(qualifies_for_divine_fury(a, params))

    def test_without_feature_suppressed(self):
        a, t = _make_zealot(features=()), _make_target()
        params = _attack(_make_state([a, t]), a, t)
        self.assertFalse(qualifies_for_divine_fury(a, params))

    def test_without_rage_suppressed(self):
        a, t = _make_zealot(rage_active=False), _make_target()
        params = _attack(_make_state([a, t]), a, t)
        self.assertFalse(qualifies_for_divine_fury(a, params))

    def test_dex_finesse_qualifies(self):
        # Broader than Frenzy: a DEX swing still gets Divine Fury.
        a, t = _make_zealot(), _make_target()
        _attack(_make_state([a, t]), a, t)
        params = {"kind": "melee", "ability": "dex", "bonus": 7}
        self.assertTrue(qualifies_for_divine_fury(a, params))

    def test_ranged_qualifies(self):
        # "a weapon" includes ranged weapons.
        a, t = _make_zealot(), _make_target()
        _attack(_make_state([a, t]), a, t)
        params = {"kind": "ranged", "ability": "dex", "bonus": 7}
        self.assertTrue(qualifies_for_divine_fury(a, params))


class DivineFuryDamageTest(unittest.TestCase):

    def test_damage_die_plus_half_level(self):
        # L10 → flat bonus floor(10/2) = 5; 1d6 → [1..6]; total [6..11].
        a, t = _make_zealot(level=10), _make_target()
        st = _make_state([a, t])
        params = _attack(st, a, t)
        dmg = try_apply_divine_fury(a, t, st, params, random.Random(1), False)
        self.assertGreaterEqual(dmg, 6)
        self.assertLessEqual(dmg, 11)

    def test_flat_bonus_scales_with_level(self):
        # L7 → floor(7/2) = 3.
        a, t = _make_zealot(level=7), _make_target()
        st = _make_state([a, t])
        params = _attack(st, a, t)
        try_apply_divine_fury(a, t, st, params, random.Random(1), False)
        ev = [e for e in st.event_log
              if e["event"] == "divine_fury_applied"][-1]
        self.assertEqual(ev["flat_bonus"], 3)

    def test_crit_doubles_die_not_bonus(self):
        a, t = _make_zealot(level=10), _make_target()
        st = _make_state([a, t])
        params = _attack(st, a, t)
        try_apply_divine_fury(a, t, st, params, random.Random(1), is_crit=True)
        ev = [e for e in st.event_log
              if e["event"] == "divine_fury_applied"][-1]
        self.assertEqual(ev["flat_bonus"], 5)        # bonus NOT doubled
        self.assertGreaterEqual(ev["die"], 2)        # 2d6 rolled
        self.assertLessEqual(ev["die"], 12)


class DivineFuryDedupTest(unittest.TestCase):

    def test_fires_once_per_turn(self):
        a, t = _make_zealot(), _make_target()
        st = _make_state([a, t])
        params = _attack(st, a, t)
        rng = random.Random(2)
        first = try_apply_divine_fury(a, t, st, params, rng, False)
        second = try_apply_divine_fury(a, t, st, params, rng, False)
        self.assertGreater(first, 0)
        self.assertEqual(second, 0)

    def test_resets_next_turn(self):
        a, t = _make_zealot(), _make_target()
        st = _make_state([a, t])
        params = _attack(st, a, t)
        rng = random.Random(2)
        try_apply_divine_fury(a, t, st, params, rng, False)
        a.reset_turn()
        a.rage_active = True
        self.assertGreater(
            try_apply_divine_fury(a, t, st, params, rng, False), 0)


class DivineFuryDamageIntegrationTest(unittest.TestCase):

    def test_damage_includes_divine_fury(self):
        a, t = _make_zealot(), _make_target()
        st = _make_state([a, t])
        _attack(st, a, t)
        _damage({"dice": "1d4", "type": "slashing"}, st, EventBus())
        applied = [e for e in st.event_log
                   if e["event"] == "divine_fury_applied"]
        self.assertEqual(len(applied), 1)


if __name__ == "__main__":
    unittest.main()
