"""Legendary Resistance — spend a per-day charge to turn a failed save
into a success (engine.core.legendary_resistance + _forced_save hook).

Layers:
  1. maybe_use: spends a charge + returns True when available; False at 0
  2. _forced_save: a legendary creature's failed save flips to success and
     a charge is spent; the on_fail effect does NOT land
  3. charges deplete — once spent out, saves fail normally
  4. non-legendary creatures are unaffected
  5. cli._build_actor seeds the charge from a stat block's
     `legendary_resistance: { uses: N }`
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import legendary_resistance as lr
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import _forced_save

# DC no unmodified d20 + a +0 save can ever reach → the roll always fails,
# so every test exercises the "failed save" branch deterministically.
_UNBEATABLE_DC = 99


def _abil():
    return {k: {"score": 10, "save": 0}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _actor(actor_id, *, side, resources=None, pos=(0, 0)):
    ab = _abil()
    return Actor(id=actor_id, name=actor_id,
                  template={"id": f"t_{actor_id}", "name": actor_id,
                             "abilities": ab, "actions": [],
                             "cr": {"proficiency_bonus": 2}},
                  side=side, hp_current=200, hp_max=200, ac=18,
                  speed={"walk": 40}, position=pos, abilities=ab,
                  size="huge", creature_type="dragon",
                  resources=dict(resources or {}))


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


def _force_save_on(target, state):
    """Force `target` to make a DEX save it cannot pass; on a fail it would
    gain co_prone. Returns the resulting outcome string."""
    attacker = _actor("caster", side="pc")
    state.current_attack = {"actor": attacker, "target": target,
                             "state": None, "had_advantage": False,
                             "had_disadvantage": False}
    _forced_save({
        "ability": "dexterity", "dc": _UNBEATABLE_DC,
        "affected": "current_target",
        "on_fail": [{"primitive": "apply_condition",
                      "params": {"condition_id": "co_prone",
                                  "duration": "until_removed"}}],
        "on_success": [],
    }, state, EventBus())
    return state.current_save["outcome"]


def _is_prone(actor):
    return any(c.get("condition_id") == "co_prone"
                for c in actor.applied_conditions)


class MaybeUseTest(unittest.TestCase):

    def test_spends_charge_when_available(self):
        a = _actor("dragon", side="enemy",
                    resources={"legendary_resistance_remaining": 3})
        st = _state([a])
        self.assertTrue(lr.maybe_use(a, st))
        self.assertEqual(a.resources["legendary_resistance_remaining"], 2)

    def test_returns_false_with_no_charges(self):
        a = _actor("dragon", side="enemy",
                    resources={"legendary_resistance_remaining": 0})
        st = _state([a])
        self.assertFalse(lr.maybe_use(a, st))

    def test_returns_false_when_resource_absent(self):
        a = _actor("ogre", side="enemy")   # no LR resource
        st = _state([a])
        self.assertFalse(lr.maybe_use(a, st))

    def test_logs_event(self):
        a = _actor("dragon", side="enemy",
                    resources={"legendary_resistance_remaining": 1})
        st = _state([a])
        lr.maybe_use(a, st, ability="dexterity", dc=20)
        ev = [e for e in st.event_log
              if e["event"] == "legendary_resistance_used"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["remaining"], 0)


class ForcedSaveHookTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_failed_save_flips_to_success_and_spends_charge(self):
        dragon = _actor("dragon", side="enemy",
                          resources={"legendary_resistance_remaining": 3})
        st = _state([dragon])
        outcome = _force_save_on(dragon, st)
        self.assertEqual(outcome, "success")        # LR rescued the save
        self.assertFalse(_is_prone(dragon))          # on_fail did NOT run
        self.assertEqual(
            dragon.resources["legendary_resistance_remaining"], 2)

    def test_charges_deplete_then_save_fails_normally(self):
        dragon = _actor("dragon", side="enemy",
                          resources={"legendary_resistance_remaining": 1})
        st = _state([dragon])
        # First save: rescued.
        self.assertEqual(_force_save_on(dragon, st), "success")
        self.assertEqual(
            dragon.resources["legendary_resistance_remaining"], 0)
        # Second save: no charge → fails for real, on_fail lands.
        self.assertEqual(_force_save_on(dragon, st), "fail")
        self.assertTrue(_is_prone(dragon))

    def test_non_legendary_creature_fails_normally(self):
        ogre = _actor("ogre", side="enemy")   # no LR resource
        st = _state([ogre])
        self.assertEqual(_force_save_on(ogre, st), "fail")
        self.assertTrue(_is_prone(ogre))


class ActorBuildSeedTest(unittest.TestCase):

    def test_build_actor_seeds_lr_from_stat_block(self):
        from engine.cli import _build_actor
        spec = {"template": {
            "id": "m_test_dragon", "name": "Test Dragon",
            "size": "huge", "creature_type": "dragon",
            "legendary_resistance": {"uses": 3},
            "combat": {"armor_class": 19,
                        "hit_points": {"average": 200},
                        "speed": {"walk": 40}},
            "abilities": _abil(), "actions": []}}
        actor = _build_actor(spec, registry=None)
        self.assertEqual(
            actor.resources.get("legendary_resistance_remaining"), 3)

    def test_explicit_resources_override_stat_block(self):
        from engine.cli import _build_actor
        spec = {"resources": {"legendary_resistance_remaining": 0},
                "template": {
                    "id": "m_test_dragon", "name": "Test Dragon",
                    "size": "huge", "creature_type": "dragon",
                    "legendary_resistance": {"uses": 3},
                    "combat": {"armor_class": 19,
                                "hit_points": {"average": 200},
                                "speed": {"walk": 40}},
                    "abilities": _abil(), "actions": []}}
        actor = _build_actor(spec, registry=None)
        self.assertEqual(
            actor.resources.get("legendary_resistance_remaining"), 0)


if __name__ == "__main__":
    unittest.main()
