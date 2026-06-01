"""Regeneration — turn-start self-heal, acid/fire suppression, Troll rule.

Layers:
  1. resolve_turn_start heals `amount` (capped at hp_max)
  2. acid/fire damage suppresses regen for one turn, then it resumes
  3. plain flavor ("if it has >=1 HP") does not heal from 0
  4. Troll rule: 0 HP is downed (not dead); revives at turn start...
  5. ...unless suppressed by acid/fire, in which case it dies
  6. _damage leaves a Troll-rule regenerator downed (not is_dead) at 0
  7. a downed troll keeps its side in the fight (no premature termination)
  8. non-regenerators are unaffected
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import regeneration as regen
from engine.core.events import EventBus
from engine.core.runner import EncounterRunner
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import _damage


def _abil():
    return {k: {"score": 14, "save": 2}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _regen_template(amount=15, suppressed_by=("acid", "fire"),
                      revives_from_zero=True):
    block = {"amount": amount}
    if suppressed_by is not None:
        block["suppressed_by"] = list(suppressed_by)
    block["revives_from_zero"] = revives_from_zero
    return {"id": "m_troll", "name": "Troll", "abilities": _abil(),
            "actions": [], "cr": {"proficiency_bonus": 2},
            "regeneration": block}


def _troll(hp=84, *, amount=15, suppressed_by=("acid", "fire"),
            revives=True):
    tpl = _regen_template(amount, suppressed_by, revives)
    return Actor(id="troll", name="troll", template=tpl, side="enemy",
                  hp_current=hp, hp_max=84, ac=15, speed={"walk": 30},
                  position=(0, 0), abilities=_abil(),
                  size="large", creature_type="giant")


def _plain(actor_id="pc", *, side="pc", hp=40, pos=(1, 0)):
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                  template={"id": "t", "name": actor_id, "abilities": ab,
                             "actions": [], "cr": {"proficiency_bonus": 2}},
                  side=side, hp_current=hp, hp_max=hp, ac=12,
                  speed={"walk": 30}, position=pos, abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


class HealTest(unittest.TestCase):

    def test_heals_amount_capped_at_max(self):
        t = _troll(hp=60, amount=15)
        st = _state([t])
        regen.resolve_turn_start(t, st)
        self.assertEqual(t.hp_current, 75)
        # Near max → capped, not overhealed.
        t.hp_current = 80
        regen.resolve_turn_start(t, st)
        self.assertEqual(t.hp_current, 84)

    def test_no_heal_at_full(self):
        t = _troll(hp=84)
        st = _state([t])
        regen.resolve_turn_start(t, st)
        self.assertEqual(t.hp_current, 84)

    def test_non_regenerator_is_noop(self):
        pc = _plain()
        st = _state([pc])
        pc.hp_current = 10
        regen.resolve_turn_start(pc, st)
        self.assertEqual(pc.hp_current, 10)


class SuppressionTest(unittest.TestCase):

    def test_acid_fire_suppresses_one_turn_then_resumes(self):
        t = _troll(hp=50)
        st = _state([t])
        regen.note_damage(t, "fire")
        self.assertTrue(t.regen_suppressed)
        regen.resolve_turn_start(t, st)          # suppressed this turn
        self.assertEqual(t.hp_current, 50)        # no heal
        self.assertFalse(t.regen_suppressed)      # flag cleared
        regen.resolve_turn_start(t, st)          # next turn resumes
        self.assertEqual(t.hp_current, 65)

    def test_non_suppressing_type_does_not_suppress(self):
        t = _troll(hp=50)
        regen.note_damage(t, "slashing")
        self.assertFalse(t.regen_suppressed)


class PlainFlavorTest(unittest.TestCase):

    def test_plain_does_not_heal_from_zero(self):
        # "if it has at least 1 HP" — revives_from_zero False.
        g = _troll(hp=0, revives=False)
        st = _state([g])
        regen.resolve_turn_start(g, st)
        self.assertEqual(g.hp_current, 0)         # stays down


class TrollRuleTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def _hit(self, target, amount, dmg_type, state):
        atk = _plain("atk", side="pc")
        state.current_attack = {"actor": atk, "target": target,
                                 "state": "hit", "action": {"id": "a"},
                                 "had_advantage": False,
                                 "had_disadvantage": False}
        _damage({"dice": "", "modifier": amount, "type": dmg_type},
                state, EventBus())

    def test_damage_to_zero_leaves_troll_downed_not_dead(self):
        t = _troll(hp=20)
        st = _state([t, _plain()])
        self._hit(t, 20, "slashing", st)
        self.assertEqual(t.hp_current, 0)
        self.assertFalse(t.is_dead)               # downed, not dead
        self.assertTrue(regen.is_pending(t))

    def test_downed_troll_revives_at_turn_start(self):
        t = _troll(hp=20)
        st = _state([t, _plain()])
        self._hit(t, 20, "slashing", st)          # to 0, downed
        regen.resolve_turn_start(t, st)
        self.assertFalse(t.is_dead)
        self.assertEqual(t.hp_current, 15)        # revived from 0
        self.assertFalse(regen.is_pending(t))

    def test_downed_troll_burned_dies(self):
        t = _troll(hp=20)
        st = _state([t, _plain()])
        self._hit(t, 20, "fire", st)              # lethal fire → suppressed
        self.assertFalse(t.is_dead)               # still downed this instant
        regen.resolve_turn_start(t, st)           # starts turn at 0, no regen
        self.assertTrue(t.is_dead)                # dies
        self.assertEqual(t.hp_current, 0)

    def test_fire_before_drop_still_kills_on_zero_turn(self):
        # Fire that doesn't drop it, then slashing to 0 → still suppressed.
        t = _troll(hp=30)
        st = _state([t, _plain()])
        self._hit(t, 5, "fire", st)               # suppress next turn
        self._hit(t, 25, "slashing", st)          # to 0, downed
        regen.resolve_turn_start(t, st)
        self.assertTrue(t.is_dead)


class TerminationTest(unittest.TestCase):

    def test_downed_troll_keeps_encounter_alive(self):
        t = _troll(hp=0)            # downed solo enemy
        t.hp_current = 0
        hero = _plain("hero", side="pc")
        runner = EncounterRunner.new(
            Encounter(id="e", actors=[t, hero]), seed=1)
        st = _state([t, hero])
        self.assertTrue(regen.is_pending(t))
        # Despite the only enemy being at 0 HP, the fight isn't over —
        # the troll may revive next turn.
        self.assertFalse(runner.check_termination(st))

    def test_dead_troll_ends_encounter(self):
        t = _troll(hp=0)
        t.is_dead = True            # truly dead (burned)
        hero = _plain("hero", side="pc")
        runner = EncounterRunner.new(
            Encounter(id="e", actors=[t, hero]), seed=1)
        st = _state([t, hero])
        self.assertTrue(runner.check_termination(st))


if __name__ == "__main__":
    unittest.main()
