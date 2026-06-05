"""Concentration-protection positioning (Lever C).

A concentrating caster backs out of enemy MELEE reach to protect its spell —
`concentration_break_risk_ehp` penalizes squares an enemy can move-and-reach,
and `best_position` repositions a concentrating actor (gate relaxed) to a
safer, still-able-to-act square.

Run via:
    python -m unittest tests.test_concentration_positioning
"""
from __future__ import annotations

import unittest

from engine.ai.positioning import (
    concentration_break_risk_ehp, best_position, can_act_from,
)
from engine.core.state import Actor, CombatState, Encounter


_BOLT = {"id": "a_bolt", "type": "weapon_attack", "range_ft": 120,
         "pipeline": [{"primitive": "attack_roll",
                       "params": {"kind": "ranged", "bonus": 7,
                                  "range_ft": 120}},
                      {"primitive": "damage",
                       "params": {"dice": "2d10", "modifier": 0,
                                  "type": "force"},
                       "when": {"condition": "combat.attack_state == hit"}}]}
# A melee attacker (reach 5) so estimate_dpr > 0 and it has a melee reach.
_CLAW = {"id": "a_claw", "type": "weapon_attack",
         "pipeline": [{"primitive": "attack_roll",
                       "params": {"bonus": 7, "reach_ft": 5}},
                      {"primitive": "damage",
                       "params": {"dice": "2d6", "modifier": 4,
                                  "type": "slashing"}}]}


def _mk(aid, side, pos, actions=None, speed=30, hp=60):
    ab = {k: {"score": 12, "save": 1} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=aid, name=aid,
                 template={"id": f"t_{aid}", "abilities": ab,
                           "actions": actions or [], "cr": {"proficiency_bonus": 3}},
                 side=side, hp_current=hp, hp_max=hp, ac=14,
                 speed={"walk": speed}, position=pos, abilities=ab)


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    return st


class ConcBreakRiskTest(unittest.TestCase):
    def test_zero_when_not_concentrating(self):
        caster = _mk("c", "pc", (5, 0), [_BOLT])
        foe = _mk("foe", "enemy", (5, 0), [_CLAW])
        self.assertEqual(
            concentration_break_risk_ehp(caster, (5, 0), _state([caster, foe])),
            0.0)

    def test_positive_within_threat_radius_zero_outside(self):
        caster = _mk("c", "pc", (5, 0), [_BOLT])
        caster.concentration_on = {"action_id": "a_x", "caster_id": "c"}
        # Slow enemy (speed 5 => 1 sq) + reach 5 (1 sq) => threat radius 2 sq.
        foe = _mk("foe", "enemy", (0, 0), [_CLAW], speed=5)
        st = _state([caster, foe])
        near = concentration_break_risk_ehp(caster, (1, 0), st)   # 5 ft, within
        far = concentration_break_risk_ehp(caster, (20, 0), st)   # 100 ft, out
        self.assertGreater(near, 0.0)
        self.assertEqual(far, 0.0)


class BestPositionConcentrationTest(unittest.TestCase):
    def test_concentrating_caster_backs_out_of_melee(self):
        # Caster adjacent to a SLOW melee enemy (escapable). It's concentrating
        # and can act from anywhere (120-ft bolt), so it should move to a
        # lower-risk square out of the enemy's move+reach.
        caster = _mk("c", "pc", (1, 0), [_BOLT], speed=30)
        caster.concentration_on = {"action_id": "a_x", "caster_id": "c"}
        foe = _mk("foe", "enemy", (0, 0), [_CLAW], speed=5)   # threat radius 2 sq
        st = _state([caster, foe])
        dest = best_position(caster, st)
        self.assertIsNotNone(dest)                    # it repositions
        self.assertLess(concentration_break_risk_ehp(caster, dest, st),
                        concentration_break_risk_ehp(caster, (1, 0), st))
        self.assertTrue(can_act_from(caster, dest, st))   # still able to act

    def test_non_concentrating_no_melee_flee(self):
        # Not concentrating + no AoE threat -> best_position stays out of it
        # (returns None; the normal move logic applies).
        caster = _mk("c", "pc", (1, 0), [_BOLT], speed=30)
        foe = _mk("foe", "enemy", (0, 0), [_CLAW], speed=5)
        self.assertIsNone(best_position(caster, _state([caster, foe])))


if __name__ == "__main__":
    unittest.main()
