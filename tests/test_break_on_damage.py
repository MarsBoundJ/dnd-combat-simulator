"""Break-on-damage control (RAW): a condition flagged break_on_damage ends
for an affected creature when it takes any damage (Hypnotic Pattern's charm,
Sleep). Non-break control (Hold Monster's paralysis) is unaffected, and the
caster's concentration / OTHER affected creatures are untouched.

Run via:
    python -m unittest tests.test_break_on_damage
"""
from __future__ import annotations

import random
import unittest

from engine.core.events import EventBus
from engine.core.state import Actor, Encounter, CombatState
import engine.primitives as primitives_module
from engine.primitives import _apply_condition, _damage


def _actor(actor_id, side="enemy", hp=60):
    ab = {k: {"score": 12, "save": 1} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                 template={"id": f"t_{actor_id}", "abilities": ab,
                           "cr": {"proficiency_bonus": 2}, "actions": []},
                 side=side, hp_current=hp, hp_max=hp, ac=12,
                 position=(0, 0), abilities=ab)


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = None     # marker-only conditions (no effect lookup)
    return st


def _has(actor, cond):
    return any(a.get("condition_id") == cond for a in actor.applied_conditions)


def _apply(caster, target, state, cond, break_on_damage):
    state.current_attack = {"actor": caster, "target": target}
    _apply_condition({"condition_id": cond,
                      "break_on_damage": break_on_damage}, state, EventBus())


def _hit(attacker, target, state, amount=8):
    primitives_module.set_rng(random.Random(0))
    state.current_attack = {"actor": attacker, "target": target,
                            "action": {}, "state": "hit"}
    _damage({"dice": "", "modifier": amount, "type": "fire"}, state, EventBus())


class BreakOnDamageTest(unittest.TestCase):

    def test_break_on_damage_ends_on_hit(self):
        caster = _actor("wiz", side="pc")
        foe = _actor("foe")
        st = _state([caster, foe])
        _apply(caster, foe, st, "co_incapacitated", break_on_damage=True)
        self.assertTrue(_has(foe, "co_incapacitated"))
        st.event_log.clear()
        _hit(_actor("atk", side="pc"), foe, st)
        self.assertFalse(_has(foe, "co_incapacitated"))   # woke up
        self.assertTrue(any(e["event"] == "condition_ended_by_damage"
                            for e in st.event_log))

    def test_non_break_control_survives_damage(self):
        caster = _actor("wiz", side="pc")
        foe = _actor("foe")
        st = _state([caster, foe])
        _apply(caster, foe, st, "co_paralyzed", break_on_damage=False)
        self.assertTrue(_has(foe, "co_paralyzed"))
        _hit(_actor("atk", side="pc"), foe, st)
        self.assertTrue(_has(foe, "co_paralyzed"))        # Hold Monster holds

    def test_zero_damage_does_not_break(self):
        caster = _actor("wiz", side="pc")
        foe = _actor("foe")
        st = _state([caster, foe])
        _apply(caster, foe, st, "co_incapacitated", break_on_damage=True)
        _hit(_actor("atk", side="pc"), foe, st, amount=0)
        self.assertTrue(_has(foe, "co_incapacitated"))    # 0 damage = no break

    def test_damaging_one_leaves_others_locked(self):
        # Two creatures hypnotized by the same cast; damage one — the OTHER
        # stays locked (peel one at a time).
        caster = _actor("wiz", side="pc")
        a = _actor("a")
        b = _actor("b")
        st = _state([caster, a, b])
        _apply(caster, a, st, "co_incapacitated", break_on_damage=True)
        _apply(caster, b, st, "co_incapacitated", break_on_damage=True)
        _hit(_actor("atk", side="pc"), a, st)
        self.assertFalse(_has(a, "co_incapacitated"))     # damaged -> woke
        self.assertTrue(_has(b, "co_incapacitated"))      # untouched -> locked


if __name__ == "__main__":
    unittest.main()
