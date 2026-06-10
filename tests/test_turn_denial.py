"""Turn-denial substrate tests.

A creature with an incapacitating condition (Incapacitated / Stunned /
Paralyzed / Unconscious / Petrified — incl. Command's Halt, Hold Person's
paralysis, dragon/ghoul effects) takes no action, Bonus Action, or movement
on its turn: the turn is skipped. "Lose one turn" conditions (duration:
until_actor_next_turn_start) then expire at the end of the denied turn, so the
creature recovers the turn after.
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.runner import EncounterRunner
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import _apply_condition

_REPO = Path(__file__).resolve().parent.parent
_REG = None


def _reg():
    global _REG
    if _REG is None:
        _REG = load_content(_REPO / "schema" / "content", validate=True,
                            schema_root=_REPO / "schema")
    return _REG


def _ab():
    return {k: {"score": 12, "save": 1}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _attacker(aid, side, pos, target_ac_bonus=4):
    return Actor(id=aid, name=aid,
                 template={"id": f"t_{aid}", "name": aid, "abilities": _ab(),
                           "cr": {"proficiency_bonus": 2},
                           "actions": [{"id": f"a_{aid}", "name": "Hit",
                                        "type": "weapon_attack",
                                        "pipeline": [
                                            {"primitive": "attack_roll",
                                             "params": {"bonus": 6,
                                                        "reach_ft": 5}},
                                            {"primitive": "damage",
                                             "params": {"dice": "1d8",
                                                        "modifier": 3,
                                                        "type": "slashing"},
                                             "when": {"event": "damage_roll",
                                                      "condition": "combat.attack_state == hit"}}]}]},
                 side=side, hp_current=50, hp_max=50, ac=10,
                 position=pos, speed={"walk": 30}, abilities=_ab())


def _scenario():
    pc = _attacker("pc", "pc", (0, 0))
    pc.ac = 18
    pc.hp_current = pc.hp_max = 200
    foe = _attacker("foe", "enemy", (1, 0))
    enc = Encounter(id="e", actors=[pc, foe])
    run = EncounterRunner.new(enc, seed=5)
    st = CombatState(encounter=enc)
    st.round = 1
    st.content_registry = _reg()
    st.turn_order = ["pc", "foe"]
    return pc, foe, enc, run, st


class TurnDenialTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(5))

    def _incapacitate(self, foe, st, duration="until_actor_next_turn_start",
                        condition="co_incapacitated"):
        st.current_attack = {"actor": st.encounter.actors[0], "target": foe}
        _apply_condition({"condition_id": condition, "duration": duration},
                          st, EventBus())

    def test_incapacitated_skips_turn(self):
        pc, foe, enc, run, st = _scenario()
        self._incapacitate(foe, st)
        pc_hp = pc.hp_current
        run.tick(st)   # pc
        run.tick(st)   # foe — skipped
        self.assertTrue(any(e.get("event") == "turn_skipped_incapacitated"
                            for e in st.event_log))
        self.assertEqual(pc.hp_current, pc_hp)   # foe did nothing

    def test_one_turn_condition_expires_after_denied_turn(self):
        pc, foe, enc, run, st = _scenario()
        self._incapacitate(foe, st)
        run.tick(st)   # pc
        run.tick(st)   # foe — skipped + expire
        self.assertFalse(any(c.get("condition_id") == "co_incapacitated"
                             for c in foe.applied_conditions))

    def test_recovers_the_turn_after(self):
        pc, foe, enc, run, st = _scenario()
        self._incapacitate(foe, st)
        run.tick(st)   # pc
        run.tick(st)   # foe — skipped
        hp_after_skip = pc.hp_current
        run.tick(st)   # pc
        run.tick(st)   # foe — now free, attacks
        self.assertLess(pc.hp_current, hp_after_skip)

    def test_stunned_also_skips(self):
        pc, foe, enc, run, st = _scenario()
        self._incapacitate(foe, st, condition="co_stunned")
        pc_hp = pc.hp_current
        run.tick(st)
        run.tick(st)
        self.assertTrue(any(e.get("event") == "turn_skipped_incapacitated"
                            for e in st.event_log))
        self.assertEqual(pc.hp_current, pc_hp)

    def test_uncontrolled_creature_acts(self):
        # Sanity: with no incapacitation, the foe attacks normally.
        pc, foe, enc, run, st = _scenario()
        pc_hp = pc.hp_current
        run.tick(st)   # pc
        run.tick(st)   # foe — acts
        self.assertFalse(any(e.get("event") == "turn_skipped_incapacitated"
                             for e in st.event_log))


if __name__ == "__main__":
    unittest.main()
