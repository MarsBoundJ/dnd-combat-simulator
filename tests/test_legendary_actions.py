"""Legendary Actions — extra actions between other creatures' turns
(engine.core.legendary_actions + runner interleave hook).

Layers:
  1. module helpers: configured / uses_per_round / option_cost / remaining
  2. reset_budget refills at turn start; is_eligible gates on alive /
     incapacitated / budget
  3. affordable_options withholds options the budget can't pay for
  4. runner._resolve_legendary_actions: an eligible legendary creature
     spends ONE use after another creature's turn — not after its own,
     not while incapacitated, not with an empty pool
  5. end-to-end: legendary_action_used events fire during a real run
"""
from __future__ import annotations

import random
import unittest

import engine.primitives as primitives_module
from engine.core import legendary_actions as la
from engine.core.runner import EncounterRunner
from engine.core.state import Actor, CombatState, Encounter


def _abil():
    return {k: {"score": 14, "save": 1}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _claw_option(opt_id="a_la_claw", cost=1):
    opt = {"id": opt_id, "name": "Claw", "type": "weapon_attack",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "melee", "bonus": 8, "reach_ft": 10}},
                {"primitive": "damage",
                  "params": {"dice": "2d6", "modifier": 4,
                              "type": "slashing", "average": 11},
                  "when": {"event": "damage_roll",
                            "condition": "combat.attack_state == hit"}},
            ]}
    if cost != 1:
        opt["cost"] = cost
    return opt


def _dragon_template(uses=3, options=None):
    return {"id": "m_test_dragon", "name": "Test Dragon",
            "abilities": _abil(), "size": "huge", "creature_type": "dragon",
            "cr": {"proficiency_bonus": 4},
            "actions": [
                {"id": "a_bite", "name": "Bite", "type": "weapon_attack",
                  "pipeline": [
                      {"primitive": "attack_roll",
                        "params": {"kind": "melee", "bonus": 8, "reach_ft": 10}},
                      {"primitive": "damage",
                        "params": {"dice": "2d10", "modifier": 4,
                                    "type": "piercing", "average": 15},
                        "when": {"event": "damage_roll",
                                  "condition": "combat.attack_state == hit"}},
                  ]}],
            "legendary_actions": {
                "uses_per_round": uses,
                "options": options if options is not None else [_claw_option()],
            }}


def _dragon(uses=3, options=None, *, hp=400, pos=(0, 0), seed_pool=True):
    tpl = _dragon_template(uses, options)
    res = {la.RESOURCE_KEY: uses} if seed_pool else {}
    return Actor(id="dragon", name="dragon", template=tpl, side="enemy",
                  hp_current=hp, hp_max=hp, ac=16, speed={"walk": 40},
                  position=pos, abilities=_abil(), size="huge",
                  creature_type="dragon", resources=res)


def _pc(actor_id="hero", *, hp=40, pos=(1, 0)):
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                  template={"id": f"t_{actor_id}", "name": actor_id,
                             "abilities": ab, "actions": [],
                             "cr": {"proficiency_bonus": 2}},
                  side="pc", hp_current=hp, hp_max=hp, ac=12,
                  speed={"walk": 30}, position=pos, abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


def _runner(actors):
    return EncounterRunner.new(Encounter(id="t", actors=actors), seed=1)


# ---------------------------------------------------------------------------
# Layer 1-3: module helpers
# ---------------------------------------------------------------------------

class ModuleTest(unittest.TestCase):

    def test_configured_requires_options(self):
        self.assertIsNotNone(la.configured(_dragon_template()))
        self.assertIsNone(la.configured({"legendary_actions":
                                          {"uses_per_round": 3}}))
        self.assertIsNone(la.configured({}))

    def test_uses_per_round_and_cost(self):
        self.assertEqual(la.uses_per_round(_dragon_template(uses=3)), 3)
        self.assertEqual(la.option_cost({"id": "x"}), 1)
        self.assertEqual(la.option_cost({"id": "x", "cost": 2}), 2)

    def test_reset_budget_refills(self):
        d = _dragon(uses=3, seed_pool=False)
        st = _state([d])
        la.reset_budget(d, st)
        self.assertEqual(la.remaining(d), 3)

    def test_reset_budget_noop_for_non_legendary(self):
        pc = _pc()
        st = _state([pc])
        la.reset_budget(pc, st)
        self.assertNotIn(la.RESOURCE_KEY, pc.resources)

    def test_affordable_options_respects_budget(self):
        d = _dragon(uses=1, options=[_claw_option("cheap", 1),
                                       _claw_option("pricey", 2)])
        # Pool seeded to 1 → only the cost-1 option is affordable.
        self.assertEqual(la.remaining(d), 1)
        ids = {o["id"] for o in la.affordable_options(d)}
        self.assertEqual(ids, {"cheap"})

    def test_is_eligible_gates(self):
        d = _dragon(uses=3)
        self.assertTrue(la.is_eligible(d))
        # No budget
        d.resources[la.RESOURCE_KEY] = 0
        self.assertFalse(la.is_eligible(d))
        # Incapacitated
        d.resources[la.RESOURCE_KEY] = 3
        d.applied_conditions.append({"condition_id": "co_incapacitated"})
        self.assertFalse(la.is_eligible(d))


# ---------------------------------------------------------------------------
# Layer 4: runner interleave hook (direct, deterministic)
# ---------------------------------------------------------------------------

class ResolveTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def test_spends_one_use_after_another_creatures_turn(self):
        d = _dragon(uses=3)
        hero = _pc()
        r = _runner([d, hero])
        st = _state([d, hero])
        # Simulate: the hero's turn just ended → dragon gets a window.
        r._resolve_legendary_actions(hero, st)
        self.assertEqual(la.remaining(d), 2)        # one use spent
        used = [e for e in st.event_log
                if e["event"] == "legendary_action_used"]
        self.assertEqual(len(used), 1)
        self.assertEqual(used[0]["option"], "a_la_claw")

    def test_no_legendary_action_after_own_turn(self):
        d = _dragon(uses=3)
        hero = _pc()
        r = _runner([d, hero])
        st = _state([d, hero])
        r._resolve_legendary_actions(d, st)         # dragon's OWN turn ended
        self.assertEqual(la.remaining(d), 3)        # nothing spent
        self.assertFalse([e for e in st.event_log
                            if e["event"] == "legendary_action_used"])

    def test_no_action_when_pool_empty(self):
        d = _dragon(uses=3)
        d.resources[la.RESOURCE_KEY] = 0
        hero = _pc()
        r = _runner([d, hero])
        st = _state([d, hero])
        r._resolve_legendary_actions(hero, st)
        self.assertFalse([e for e in st.event_log
                            if e["event"] == "legendary_action_used"])

    def test_no_action_while_incapacitated(self):
        d = _dragon(uses=3)
        d.applied_conditions.append({"condition_id": "co_incapacitated"})
        hero = _pc()
        r = _runner([d, hero])
        st = _state([d, hero])
        r._resolve_legendary_actions(hero, st)
        self.assertEqual(la.remaining(d), 3)
        self.assertFalse([e for e in st.event_log
                            if e["event"] == "legendary_action_used"])

    def test_cost_2_option_spends_two(self):
        d = _dragon(uses=3, options=[_claw_option("a_la_wing", cost=2)])
        hero = _pc()
        r = _runner([d, hero])
        st = _state([d, hero])
        r._resolve_legendary_actions(hero, st)
        self.assertEqual(la.remaining(d), 1)        # 3 - 2
        used = [e for e in st.event_log
                if e["event"] == "legendary_action_used"]
        self.assertEqual(used[0]["cost"], 2)


# ---------------------------------------------------------------------------
# Layer 5: end-to-end through a real run
# ---------------------------------------------------------------------------

class EndToEndTest(unittest.TestCase):

    def test_legendary_actions_fire_during_run(self):
        # A durable dragon vs two squishier PCs: the encounter runs several
        # turns (so windows open) and ends when the dragon wins.
        d = _dragon(uses=3, hp=600)
        h1 = _pc("hero1", hp=45, pos=(1, 0))
        h2 = _pc("hero2", hp=45, pos=(0, 1))
        runner = EncounterRunner.new(
            Encounter(id="e2e", actors=[d, h1, h2]), seed=3)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=3)

        used = [e for e in state.event_log
                if e["event"] == "legendary_action_used"]
        self.assertTrue(used, "dragon should take legendary actions")
        # Budget refills each round → it should reset at least once.
        resets = [e for e in state.event_log
                  if e["event"] == "legendary_actions_reset"]
        self.assertTrue(resets)
        # Never more than uses_per_round spent between two resets.
        self.assertTrue(all(e["remaining"] >= 0 for e in used))


if __name__ == "__main__":
    unittest.main()
