"""Hold Person tests — SRD spell batch 1.

Single-target save-or-lose: WIS save or Paralyzed, with a turn-end
re-save to break free. Concentration.

Layers:
  1. f_hold_person loads with the right shape
  2. scoring: defensive_ehp_hard_control values the lockdown (>0)
  3. end-to-end: a failed save applies Paralyzed + registers the re-save
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.ai.defensive_ehp import defensive_ehp_hard_control
from engine.core import pipeline
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import PrimitiveRegistry


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"

_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True,
                                   schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _action():
    return dict(_registry().get("feature", "f_hold_person")["action_template"])


def _cleric(wis=18):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    abilities["wis"]["score"] = wis
    return Actor(id="cleric", name="cleric",
                   template={"id": "t", "name": "cleric", "abilities": abilities,
                               "cr": {"proficiency_bonus": 3}, "actions": [],
                               "spellcasting_ability": "wisdom"},
                   side="pc", hp_current=30, hp_max=30, ac=18,
                   position=(0, 0), speed={"walk": 30}, abilities=abilities,
                   spell_slots={2: 2})


def _enemy(wis_save=-3, hp=45, attack_bonus=5, dmg="2d6"):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    abilities["wis"]["save"] = wis_save
    return Actor(id="bandit", name="bandit",
                   template={"id": "t", "name": "bandit", "abilities": abilities,
                               "cr": {"proficiency_bonus": 2},
                               "actions": [{"id": "a_atk", "name": "Sword",
                                              "type": "weapon_attack",
                                              "pipeline": [
                                                  {"primitive": "attack_roll",
                                                    "params": {"bonus": attack_bonus}},
                                                  {"primitive": "damage",
                                                    "params": {"dice": dmg,
                                                                 "type": "slashing"}}]}]},
                   side="enemy", hp_current=hp, hp_max=hp, ac=14,
                   position=(2, 0), speed={"walk": 30}, abilities=abilities)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class WiringTest(unittest.TestCase):

    def test_loads(self):
        feat = _registry().get("feature", "f_hold_person")
        self.assertEqual(feat["spell"]["level"], 2)
        self.assertEqual(feat["source"], "srd_5.2.1")
        a = _action()
        self.assertEqual(a["type"], "hard_control")
        self.assertTrue(a["concentration"])
        save = a["pipeline"][0]["params"]
        self.assertEqual(save["ability"], "wisdom")


class ScoringTest(unittest.TestCase):

    def test_lockdown_scores_positive(self):
        cleric = _cleric()
        bandit = _enemy(wis_save=-3)
        state = _state([cleric, bandit])
        self.assertGreater(
            defensive_ehp_hard_control(cleric, bandit, _action(), state), 0.0)


class EndToEndTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(2))

    def test_failed_save_paralyzes_and_registers_resave(self):
        cleric = _cleric()
        bandit = _enemy(wis_save=-10)        # essentially guaranteed fail
        state = _state([cleric, bandit])
        chosen = {"kind": "hard_control", "action": _action(),
                    "target": bandit, "actor": cleric}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        conds = [c["condition_id"] for c in bandit.applied_conditions]
        self.assertIn("co_paralyzed", conds)
        # Paralyzed inherits Incapacitated transitively
        self.assertIn("co_incapacitated", conds)
        # A turn-end re-save was registered for the bandit
        rs = [e for e in state.recurring_saves if e["target_id"] == "bandit"]
        self.assertEqual(len(rs), 1)
        self.assertEqual(rs[0]["ability"], "wisdom")
        # Caster is now concentrating on Hold Person
        self.assertIsNotNone(cleric.concentration_on)
        self.assertEqual(cleric.concentration_on["action_id"], "a_hold_person")


if __name__ == "__main__":
    unittest.main()
