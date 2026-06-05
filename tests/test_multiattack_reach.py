"""Multiattack picks an IN-REACH target per sub-attack (grind fix #77).

`_execute_multiattack` was a skeleton firing every sub-attack at `enemies[0]`
(first by actor order) with no reach check — so a multiattacker dumped its
whole multiattack at an out-of-range enemy while a reachable one stood adjacent
(ledger: Fighter 27/28 attacks out-of-range). Now each sub-attack targets the
preferred (chosen) enemy if reachable, else the nearest reachable enemy.

Reach comes from the SUB-ACTION's declared `reach_ft` (5 default, 10 for a
glaive / Polearm Master / Bugbear's long limbs, or whatever a monster stat
block lists for its size) — so variable reach is honored, not hardcoded to 5.

Run via:
    python -m unittest tests.test_multiattack_reach
"""
from __future__ import annotations

import random
import unittest

from engine.core.pipeline import _execute_multiattack
from engine.core.events import EventBus
from engine.core.state import Actor, Encounter, CombatState
from engine.primitives import PrimitiveRegistry
import engine.primitives as primitives_module


def _melee(reach_ft):
    """A reliable-hit melee sub-action (bonus +12) with the given reach."""
    return {"id": f"a_melee{reach_ft}", "type": "weapon_attack",
            "reach_ft": reach_ft,
            "pipeline": [
                {"primitive": "attack_roll",
                 "params": {"kind": "melee", "bonus": 12, "reach_ft": reach_ft}},
                {"primitive": "damage",
                 "params": {"dice": "1d8", "modifier": 3, "type": "slashing"},
                 "when": {"condition": "combat.attack_state == hit"}}]}


def _multi(sub_id, count=2):
    return {"id": "a_multi", "type": "multiattack", "count": count,
            "sub_actions": [sub_id]}


def _actor(actor_id, side, pos, sub_actions, hp=60):
    ab = {k: {"score": 14, "save": 2} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                 template={"id": f"t_{actor_id}", "abilities": ab,
                           "cr": {"proficiency_bonus": 3},
                           "actions": sub_actions},
                 side=side, hp_current=hp, hp_max=hp, ac=10,   # AC 10 -> +12 hits
                 position=pos, abilities=ab)


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


def _attacked_targets(state):
    """Set of targets that actually received a rolled attack (real d20)."""
    return {e["target"] for e in state.event_log
            if e.get("event") == "attack_roll" and "d20" in e}


def _run(attacker, action, state, preferred=None):
    primitives_module.set_rng(random.Random(0))
    _execute_multiattack(attacker, action, state, EventBus(),
                         PrimitiveRegistry.with_defaults(), preferred=preferred)


class MultiattackReachTest(unittest.TestCase):

    def test_targets_in_reach_enemy_not_first_in_order(self):
        sub = _melee(5)
        atk = _actor("atk", "pc", (0, 0), [sub, _multi("a_melee5")])
        far = _actor("far", "enemy", (3, 0), [], hp=80)   # 15 ft, FIRST, high HP
        near = _actor("near", "enemy", (1, 0), [], hp=40)  # 5 ft, in reach
        st = _state([atk, far, near])
        _run(atk, _multi("a_melee5", count=2), st)
        hit = _attacked_targets(st)
        self.assertIn("near", hit)        # reachable enemy attacked
        self.assertNotIn("far", hit)      # NOT the out-of-range first-in-order

    def test_prefers_chosen_target_when_reachable(self):
        sub = _melee(5)
        atk = _actor("atk", "pc", (0, 0), [sub, _multi("a_melee5")])
        a = _actor("a", "enemy", (1, 0), [], hp=40)   # both in reach (5 ft)
        b = _actor("b", "enemy", (1, 1), [], hp=40)
        st = _state([atk, a, b])
        _run(atk, _multi("a_melee5", count=2), st, preferred=b)
        self.assertEqual(_attacked_targets(st), {"b"})  # stuck to preferred

    def test_falls_off_preferred_when_out_of_reach(self):
        sub = _melee(5)
        atk = _actor("atk", "pc", (0, 0), [sub, _multi("a_melee5")])
        reachable = _actor("reachable", "enemy", (1, 0), [], hp=40)
        pref_far = _actor("pref_far", "enemy", (4, 0), [], hp=40)  # 20 ft
        st = _state([atk, reachable, pref_far])
        _run(atk, _multi("a_melee5", count=2), st, preferred=pref_far)
        # preferred is out of reach -> retarget the reachable one
        self.assertIn("reachable", _attacked_targets(st))
        self.assertNotIn("pref_far", _attacked_targets(st))

    def test_honors_longer_reach_weapon(self):
        # A 10-ft reach sub-action (glaive / Polearm Master / Bugbear) hits an
        # enemy at 10 ft that a 5-ft weapon could not.
        sub = _melee(10)
        atk = _actor("atk", "pc", (0, 0), [sub, _multi("a_melee10")])
        at10 = _actor("at10", "enemy", (2, 0), [], hp=40)   # 10 ft away
        st = _state([atk, at10])
        _run(atk, _multi("a_melee10", count=1), st)
        self.assertIn("at10", _attacked_targets(st))

    def test_five_foot_weapon_cannot_reach_ten_feet(self):
        # Same geometry, 5-ft reach -> the 10-ft enemy is NOT a rolled attack
        # (auto-miss / out of range), confirming reach is honored not ignored.
        sub = _melee(5)
        atk = _actor("atk", "pc", (0, 0), [sub, _multi("a_melee5")])
        at10 = _actor("at10", "enemy", (2, 0), [], hp=40)
        st = _state([atk, at10])
        _run(atk, _multi("a_melee5", count=1), st)
        self.assertNotIn("at10", _attacked_targets(st))   # no real roll landed


if __name__ == "__main__":
    unittest.main()
