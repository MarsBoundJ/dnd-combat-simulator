"""Monster passive-trait mechanics — Displacement, Avoidance, Bloodied Fury,
Fear of Fire — plus the compound (AND/OR) damage-guard evaluator and the
crit-damage regression it fixes.

These exercise the engine wiring added for the MM-2024 CR-3 batch:
  - t_displacement  → attacks against the creature have Disadvantage
  - t_avoidance     → Evasion for ANY save ability (0 / half)
  - t_bloodied_fury → +1 Multiattack swing while Bloodied
  - t_fear_of_fire  → self-Disadvantage after taking fire damage
  - _evaluate_simple_condition AND/OR support + hit-includes-crit
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import modifiers, pipeline
from engine.core.events import EventBus
from engine.core.evasion import select_avoidance_subs
from engine.core.monster_traits import is_bloodied, has_trait
from engine.core.pipeline import _evaluate_simple_condition
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
        _REGISTRY = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _monster(mid):
    return _registry().get("monster", mid)


def _actor_from(mid, *, position=(0, 0), hp=None):
    m = _monster(mid)
    full = m["combat"]["hit_points"]["average"]
    cur = full if hp is None else hp
    return Actor(id=mid, name=m["name"], template=m, side="enemy",
                 hp_current=cur, hp_max=full, ac=m["combat"]["armor_class"],
                 speed={"walk": m["combat"]["speed"].get("walk", 30)},
                 position=position, abilities=m["abilities"])


def _dummy(eid="pc", *, ac=5, hp=200, position=(1, 0), **saves):
    ab = {k: {"score": 10, "save": 0} for k in ("str", "dex", "con", "int", "wis", "cha")}
    for k, v in saves.items():
        ab[k] = {"score": 10, "save": v}
    return Actor(id=eid, name=eid,
                 template={"id": "t", "name": eid, "abilities": ab,
                           "cr": {"proficiency_bonus": 2}, "actions": [], "size": "medium"},
                 side="pc", hp_current=hp, hp_max=hp, ac=ac, position=position,
                 speed={"walk": 30}, abilities=ab)


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


def _action(mid, action_id):
    return next(a for a in _monster(mid)["actions"] if a["id"] == action_id)


def _run(actor, action, target, st, *, kind="weapon_attack"):
    chosen = {"kind": kind, "action": action, "target": target, "actor": actor}
    pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
    return st


class DisplacementTest(unittest.TestCase):
    """t_displacement → attacks against the Displacer Beast have Disadvantage."""

    def test_attacks_against_displacer_beast_have_disadvantage(self):
        beast = _actor_from("m_displacer_beast")
        pc = _dummy()
        st = _state([pc, beast])
        res = modifiers.query_attack_modifiers(pc, beast, st)
        self.assertTrue(res.has_disadvantage)
        self.assertEqual(res.net_advantage(), "disadvantage")

    def test_displacement_suppressed_while_incapacitated(self):
        beast = _actor_from("m_displacer_beast")
        beast.applied_conditions.append({"condition_id": "co_incapacitated"})
        pc = _dummy()
        st = _state([pc, beast])
        res = modifiers.query_attack_modifiers(pc, beast, st)
        self.assertFalse(res.has_disadvantage)

    def test_normal_creature_grants_no_disadvantage(self):
        yeti = _actor_from("m_yeti")  # no displacement
        pc = _dummy()
        st = _state([pc, yeti])
        res = modifiers.query_attack_modifiers(pc, yeti, st)
        self.assertFalse(res.has_disadvantage)


class AvoidanceTest(unittest.TestCase):
    """t_avoidance → Evasion for ANY save ability (0 on success, half on fail)."""

    def _half_save_params(self, ability):
        return {
            "ability": ability, "dc": 15,
            "on_fail": [{"primitive": "damage",
                          "params": {"dice": "6d6", "type": "fire", "average": 21}}],
            "on_success": [{"primitive": "damage",
                             "params": {"dice": "6d6", "type": "fire",
                                        "average": 21, "multiplier": 0.5}}],
        }

    def test_avoidance_zero_on_success_any_ability(self):
        beast = _actor_from("m_displacer_beast")
        # CON save (not DEX) — base Evasion would NOT apply; Avoidance does.
        subs = select_avoidance_subs(beast, "constitution", "success",
                                       self._half_save_params("constitution"), None)
        self.assertIsNotNone(subs)
        self.assertEqual(subs[0]["params"]["multiplier"], 0.0)

    def test_avoidance_half_on_fail_any_ability(self):
        beast = _actor_from("m_displacer_beast")
        subs = select_avoidance_subs(beast, "wisdom", "fail",
                                       self._half_save_params("wisdom"), None)
        self.assertIsNotNone(subs)
        self.assertEqual(subs[0]["params"]["multiplier"], 0.5)

    def test_avoidance_absent_on_normal_creature(self):
        yeti = _actor_from("m_yeti")
        subs = select_avoidance_subs(yeti, "constitution", "success",
                                       self._half_save_params("constitution"), None)
        self.assertIsNone(subs)

    def test_avoidance_not_applied_to_non_half_effect(self):
        beast = _actor_from("m_displacer_beast")
        params = {"ability": "constitution", "dc": 15,
                  "on_fail": [{"primitive": "apply_condition",
                                "params": {"condition_id": "co_prone"}}],
                  "on_success": []}
        self.assertIsNone(
            select_avoidance_subs(beast, "constitution", "fail", params, None))


class BloodiedFuryTest(unittest.TestCase):
    """t_bloodied_fury → +1 Multiattack swing while Bloodied."""

    def setUp(self):
        primitives_module.set_rng(random.Random(7))

    def test_is_bloodied_threshold(self):
        a = _dummy(hp=200)
        a.hp_max = 200
        a.hp_current = 100
        self.assertTrue(is_bloodied(a))      # exactly half → bloodied
        a.hp_current = 101
        self.assertFalse(is_bloodied(a))
        a.hp_current = 0
        self.assertFalse(is_bloodied(a))     # dead is not bloodied

    def test_full_health_swings_twice(self):
        q = _actor_from("m_quaggoth_thonot")  # full HP
        pc = _dummy(ac=1)
        st = _state([q, pc])
        _run(q, _action("m_quaggoth_thonot", "a_multiattack"), pc, st,
             kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 2)

    def test_bloodied_swings_three_times(self):
        q = _actor_from("m_quaggoth_thonot", hp=10)  # ≤ half of 67 → bloodied
        self.assertTrue(is_bloodied(q))
        pc = _dummy(ac=1)
        st = _state([q, pc])
        _run(q, _action("m_quaggoth_thonot", "a_multiattack"), pc, st,
             kind="multiattack")
        self.assertEqual(
            len([e for e in st.event_log if e.get("event") == "attack_roll"]), 3)
        self.assertTrue(any(e.get("event") == "bloodied_fury"
                            for e in st.event_log))


class FearOfFireTest(unittest.TestCase):
    """t_fear_of_fire → self-Disadvantage after taking fire damage."""

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def _deal(self, attacker, target, st, dmg_type):
        st.current_attack = {"actor": attacker, "target": target,
                              "action": {"id": "a_x"}, "state": "hit",
                              "had_advantage": False, "had_disadvantage": False}
        primitives_module._damage({"dice": "", "modifier": 10, "type": dmg_type},
                                  st, EventBus())

    def test_fire_damage_imposes_self_disadvantage(self):
        yeti = _actor_from("m_yeti")
        pc = _dummy()
        st = _state([yeti, pc])
        self._deal(pc, yeti, st, "fire")
        # Yeti now attacks at Disadvantage.
        res = modifiers.query_attack_modifiers(yeti, pc, st)
        self.assertTrue(res.has_disadvantage)

    def test_non_fire_damage_does_not_trigger(self):
        yeti = _actor_from("m_yeti")
        pc = _dummy()
        st = _state([yeti, pc])
        self._deal(pc, yeti, st, "cold")
        res = modifiers.query_attack_modifiers(yeti, pc, st)
        self.assertFalse(res.has_disadvantage)

    def test_fear_of_fire_not_stacked(self):
        yeti = _actor_from("m_yeti")
        pc = _dummy()
        st = _state([yeti, pc])
        self._deal(pc, yeti, st, "fire")
        self._deal(pc, yeti, st, "fire")
        fof = [m for m in yeti.active_modifiers
               if (m.get("source") or {}).get("id") == "t_fear_of_fire"]
        self.assertEqual(len(fof), 1)

    def test_fear_of_fire_clears_at_turn_end(self):
        yeti = _actor_from("m_yeti")
        pc = _dummy()
        st = _state([yeti, pc])
        self._deal(pc, yeti, st, "fire")
        modifiers.expire_modifiers(yeti, {"turn_end"})
        res = modifiers.query_attack_modifiers(yeti, pc, st)
        self.assertFalse(res.has_disadvantage)

    def test_fear_of_fire_survives_turn_start(self):
        yeti = _actor_from("m_yeti")
        pc = _dummy()
        st = _state([yeti, pc])
        self._deal(pc, yeti, st, "fire")
        # turn-start expiry must NOT clear it (it lasts through the turn).
        modifiers.expire_modifiers(yeti, {"turn_start"})
        res = modifiers.query_attack_modifiers(yeti, pc, st)
        self.assertTrue(res.has_disadvantage)


class CompoundConditionTest(unittest.TestCase):
    """_evaluate_simple_condition: AND/OR support + hit-includes-crit."""

    def _st(self, *, state="hit", adv=False, disadv=False):
        st = CombatState(encounter=Encounter(id="t", actors=[]))
        st.current_attack = {"state": state, "had_advantage": adv,
                              "had_disadvantage": disadv}
        return st

    def test_and_requires_both(self):
        cond = "combat.attack_state == hit AND combat.attack_had_advantage"
        self.assertTrue(_evaluate_simple_condition(cond, self._st(adv=True)))
        self.assertFalse(_evaluate_simple_condition(cond, self._st(adv=False)))
        self.assertFalse(
            _evaluate_simple_condition(cond, self._st(state="miss", adv=True)))

    def test_or_requires_either(self):
        cond = "combat.attack_had_advantage OR combat.attack_had_disadvantage"
        self.assertTrue(_evaluate_simple_condition(cond, self._st(adv=True)))
        self.assertTrue(_evaluate_simple_condition(cond, self._st(disadv=True)))
        self.assertFalse(_evaluate_simple_condition(cond, self._st()))

    def test_hit_atom_matches_crit(self):
        self.assertTrue(
            _evaluate_simple_condition("combat.attack_state == hit",
                                        self._st(state="crit")))

    def test_crit_atom_is_specific(self):
        self.assertTrue(
            _evaluate_simple_condition("combat.attack_state == crit",
                                        self._st(state="crit")))
        self.assertFalse(
            _evaluate_simple_condition("combat.attack_state == crit",
                                        self._st(state="hit")))


class ScoutCaptainAdvantageBonusTest(unittest.TestCase):
    """Scout Captain deals +3d6 only when the attack roll had Advantage —
    the concrete consumer of the AND-condition guard."""

    def setUp(self):
        primitives_module.set_rng(random.Random(5))

    def _grant_attacker_advantage(self, target):
        target.active_modifiers.append({
            "primitive": "attack_modifier",
            "params": {"when": "target_is_self",
                        "modifier": "advantage_for_attacker"},
            "lifetime": "until_long_rest",
            "source": {"type": "test"},
            "owner_id": target.id,
        })

    def _shortsword(self, *, advantage):
        scout = _actor_from("m_scout_captain")
        pc = _dummy(ac=1, hp=200)
        if advantage:
            self._grant_attacker_advantage(pc)
        st = _state([scout, pc])
        _run(scout, _action("m_scout_captain", "a_shortsword"), pc, st)
        return st

    def test_no_bonus_without_advantage(self):
        # The +3d6 is a SEPARATE damage step; without Advantage only the base
        # damage step fires → exactly one damage_dealt event. (Counting events
        # is crit-robust — a crit doubles the base but adds no extra event.)
        st = self._shortsword(advantage=False)
        self.assertFalse(st.current_attack.get("had_advantage"))
        dmg_events = [e for e in st.event_log if e.get("event") == "damage_dealt"]
        self.assertEqual(len(dmg_events), 1)

    def test_bonus_applies_with_advantage(self):
        st = self._shortsword(advantage=True)
        self.assertTrue(st.current_attack.get("had_advantage"))
        # base 1d6+3 step + the +3d6 advantage step → two damage_dealt events.
        dmg_events = [e for e in st.event_log if e.get("event") == "damage_dealt"]
        self.assertEqual(len(dmg_events), 2)


class CritDamageRegressionTest(unittest.TestCase):
    """A crit must deal (doubled) damage through the normal pipeline guard.

    Before the hit-includes-crit fix, a damage step gated on
    `combat.attack_state == hit` was skipped on a crit (state == "crit"),
    so crits dealt zero weapon damage.
    """

    def test_crit_deals_damage_through_pipeline(self):
        action = {"id": "a_hit", "type": "weapon_attack", "pipeline": [
            {"primitive": "attack_roll",
             "params": {"kind": "melee", "bonus": 50, "reach_ft": 5}},
            {"primitive": "damage",
             "params": {"dice": "1d6", "modifier": 3, "type": "slashing"},
             "when": {"event": "damage_roll",
                      "condition": "combat.attack_state == hit"}},
        ]}
        ab = {k: {"score": 10, "save": 0}
              for k in ("str", "dex", "con", "int", "wis", "cha")}
        atk = Actor(id="atk", name="atk",
                    template={"id": "atk", "name": "atk", "size": "medium",
                              "abilities": ab, "cr": {"proficiency_bonus": 2},
                              "actions": []},
                    side="enemy", hp_current=10, hp_max=10, ac=10,
                    speed={"walk": 30}, position=(0, 0), abilities=ab)
        seen_crit = False
        for seed in range(60):
            primitives_module.set_rng(random.Random(seed))
            pc = _dummy(ac=1)
            st = _state([atk, pc])
            _run(atk, action, pc, st)
            if st.current_attack.get("state") == "crit":
                seen_crit = True
                self.assertLess(pc.hp_current, 200,
                                "crit dealt zero damage through pipeline")
        self.assertTrue(seen_crit, "no crit sampled — test inconclusive")


class TempHpFromDamageTest(unittest.TestCase):
    """Lizardfolk Sovereign Bite → Temp HP (to self) equal to the damage dealt
    (temp_hp_grant target: self, amount_source: last_damage_dealt)."""

    def setUp(self):
        primitives_module.set_rng(random.Random(4))

    def test_bite_grants_self_temp_hp_equal_to_damage(self):
        for seed in range(30):
            primitives_module.set_rng(random.Random(seed))
            liz = _actor_from("m_lizardfolk_sovereign")
            pc = _dummy(ac=1, hp=500)
            st = _state([liz, pc])
            _run(liz, _action("m_lizardfolk_sovereign", "a_bite"), pc, st)
            dmg = [e for e in st.event_log if e.get("event") == "damage_dealt"]
            if dmg:
                dealt = dmg[-1]["amount"]
                self.assertEqual(liz.temp_hp, dealt)
                self.assertGreater(liz.temp_hp, 0)
                return
        self.fail("no bite hit in 30 seeds")

    def test_no_temp_hp_on_miss(self):
        liz = _actor_from("m_lizardfolk_sovereign")
        pc = _dummy(ac=99, hp=500)   # unhittable
        st = _state([liz, pc])
        _run(liz, _action("m_lizardfolk_sovereign", "a_bite"), pc, st)
        self.assertEqual(liz.temp_hp, 0)

    def test_temp_hp_takes_greater_not_sum(self):
        # Two bites: temp HP uses max-semantics (RAW: doesn't stack).
        liz = _actor_from("m_lizardfolk_sovereign")
        pc = _dummy(ac=1, hp=500)
        st = _state([liz, pc])
        primitives_module.set_rng(random.Random(11))
        _run(liz, _action("m_lizardfolk_sovereign", "a_bite"), pc, st)
        first = liz.temp_hp
        _run(liz, _action("m_lizardfolk_sovereign", "a_bite"), pc, st)
        # After the second bite, temp HP is the GREATER of the two grants,
        # never their sum.
        dmg = [e["amount"] for e in st.event_log
               if e.get("event") == "damage_dealt"]
        self.assertEqual(liz.temp_hp, max(dmg))
        self.assertLess(liz.temp_hp, sum(dmg))


class TargetSizeConditionTest(unittest.TestCase):
    """Lizardfolk Sovereign Earthen Maul → Prone only vs Medium-or-smaller
    targets (when: combat.target_size <= medium)."""

    def setUp(self):
        primitives_module.set_rng(random.Random(5))

    def _maul(self, target_size):
        for seed in range(40):
            primitives_module.set_rng(random.Random(seed))
            liz = _actor_from("m_lizardfolk_sovereign")
            pc = _dummy(ac=1, hp=500)
            pc.size = target_size
            st = _state([liz, pc])
            _run(liz, _action("m_lizardfolk_sovereign", "a_earthen_maul"),
                 pc, st)
            if any(e.get("event") == "damage_dealt" for e in st.event_log):
                return pc, st
        self.fail("no maul hit in 40 seeds")

    def test_medium_target_knocked_prone(self):
        pc, _ = self._maul("medium")
        self.assertIn("co_prone",
                      [c["condition_id"] for c in pc.applied_conditions])

    def test_small_target_knocked_prone(self):
        pc, _ = self._maul("small")
        self.assertIn("co_prone",
                      [c["condition_id"] for c in pc.applied_conditions])

    def test_large_target_not_knocked_prone(self):
        pc, _ = self._maul("large")
        self.assertNotIn("co_prone",
                         [c["condition_id"] for c in pc.applied_conditions])

    def test_huge_target_not_knocked_prone(self):
        pc, _ = self._maul("huge")
        self.assertNotIn("co_prone",
                         [c["condition_id"] for c in pc.applied_conditions])

    # Direct atom evaluation (deterministic).
    def _st_with_target_size(self, size):
        st = CombatState(encounter=Encounter(id="t", actors=[]))
        tgt = _dummy()
        tgt.size = size
        st.current_attack = {"state": "hit", "target": tgt}
        return st

    def test_atom_medium_le_medium(self):
        self.assertTrue(_evaluate_simple_condition(
            "combat.target_size <= medium", self._st_with_target_size("medium")))

    def test_atom_large_not_le_medium(self):
        self.assertFalse(_evaluate_simple_condition(
            "combat.target_size <= medium", self._st_with_target_size("large")))

    def test_atom_tiny_le_medium(self):
        self.assertTrue(_evaluate_simple_condition(
            "combat.target_size <= medium", self._st_with_target_size("tiny")))


class BloodiedConditionalDamageTest(unittest.TestCase):
    """Swarm of Dretches Rend → 3d6+2 at full strength, 3d4+2 while Bloodied
    (combat.attacker_not_bloodied / combat.attacker_bloodied guards)."""

    def setUp(self):
        primitives_module.set_rng(random.Random(7))

    def test_healthy_swarm_uses_full_dice(self):
        # Full-strength Rend is 3d6+2 (non-crit max 20). A NON-CRIT hit above
        # 14 can only come from the 3d6 step (3d4+2 non-crit caps at 14),
        # proving the full-damage branch fires while not Bloodied.
        saw_above_14 = False
        for seed in range(80):
            primitives_module.set_rng(random.Random(seed))
            swarm = _actor_from("m_swarm_of_dretches")  # full HP, not bloodied
            self.assertFalse(is_bloodied(swarm))
            pc = _dummy(ac=1, hp=2000)
            st = _state([swarm, pc])
            _run(swarm, _action("m_swarm_of_dretches", "a_rend"), pc, st)
            dmg = [e for e in st.event_log if e.get("event") == "damage_dealt"]
            if dmg:
                # exactly ONE damage step fires per Rend (never both branches)
                self.assertEqual(len(dmg), 1)
                if (st.current_attack.get("state") == "hit"
                        and dmg[0]["amount"] > 14):
                    saw_above_14 = True
        self.assertTrue(saw_above_14,
                        "full-strength Rend never exceeded the bloodied cap")

    def test_bloodied_swarm_uses_reduced_dice(self):
        # Reduced Rend is 3d4+2: non-crit max 14, crit (dice doubled → 6d4+2)
        # max 26. While Bloodied no NON-CRIT hit may exceed 14.
        for seed in range(80):
            primitives_module.set_rng(random.Random(seed))
            swarm = _actor_from("m_swarm_of_dretches", hp=10)  # ≤ half of 45
            self.assertTrue(is_bloodied(swarm))
            pc = _dummy(ac=1, hp=2000)
            st = _state([swarm, pc])
            _run(swarm, _action("m_swarm_of_dretches", "a_rend"), pc, st)
            dmg = [e for e in st.event_log if e.get("event") == "damage_dealt"]
            if dmg:
                self.assertEqual(len(dmg), 1)
                cap = 26 if st.current_attack.get("state") == "crit" else 14
                self.assertLessEqual(dmg[0]["amount"], cap)

    # Direct atom evaluation (deterministic).
    def _st_with_attacker(self, actor):
        st = CombatState(encounter=Encounter(id="t", actors=[]))
        st.current_attack = {"state": "hit", "actor": actor}
        return st

    def test_atom_attacker_bloodied(self):
        swarm = _actor_from("m_swarm_of_dretches", hp=10)
        st = self._st_with_attacker(swarm)
        self.assertTrue(_evaluate_simple_condition(
            "combat.attacker_bloodied", st))
        self.assertFalse(_evaluate_simple_condition(
            "combat.attacker_not_bloodied", st))

    def test_atom_attacker_not_bloodied(self):
        swarm = _actor_from("m_swarm_of_dretches")  # full HP
        st = self._st_with_attacker(swarm)
        self.assertFalse(_evaluate_simple_condition(
            "combat.attacker_bloodied", st))
        self.assertTrue(_evaluate_simple_condition(
            "combat.attacker_not_bloodied", st))


class ShadowBreathRechargeTest(unittest.TestCase):
    """Juvenile Shadow Dragon Shadow Breath → Recharge 5–6 aoe_attack (cone).
    Exercises the existing recharge gate + AoE cone targeting."""

    def setUp(self):
        primitives_module.set_rng(random.Random(9))

    def _breath(self, dragon, target, st):
        from engine.core.geometry import unit_direction
        action = _action("m_juvenile_shadow_dragon", "a_shadow_breath")
        chosen = {"kind": "aoe_attack", "action": action, "target": target,
                  "actor": dragon, "origin_point": dragon.position,
                  "direction": unit_direction(dragon.position, target.position)}
        pipeline.execute(chosen, st, EventBus(),
                         PrimitiveRegistry.with_defaults())
        return st

    def test_breath_is_aoe_with_recharge(self):
        action = _action("m_juvenile_shadow_dragon", "a_shadow_breath")
        self.assertEqual(action["type"], "aoe_attack")
        self.assertEqual(action["recharge"], "5-6")
        self.assertEqual(action["area"]["shape"], "cone")

    def test_breath_marks_spent_after_use(self):
        dragon = _actor_from("m_juvenile_shadow_dragon", position=(0, 0))
        pc = _dummy(ac=5, hp=200, position=(1, 0))
        st = _state([dragon, pc])
        self._breath(dragon, pc, st)
        # After use it is spent until a turn-start recharge roll succeeds.
        from engine.core import recharge
        action = _action("m_juvenile_shadow_dragon", "a_shadow_breath")
        self.assertIn("a_shadow_breath", dragon.recharge_spent)
        self.assertFalse(recharge.is_available(dragon, action))

    def test_breath_recharges_on_high_roll(self):
        from engine.core import recharge
        dragon = _actor_from("m_juvenile_shadow_dragon")
        dragon.recharge_spent.add("a_shadow_breath")
        st = _state([dragon])

        class _R:   # forces a 6 → within 5-6 → recharges
            def randint(self, a, b):
                return 6
        recharge.roll_recharges_at_turn_start(dragon, st, _R())
        self.assertNotIn("a_shadow_breath", dragon.recharge_spent)

    def test_breath_stays_spent_on_low_roll(self):
        from engine.core import recharge
        dragon = _actor_from("m_juvenile_shadow_dragon")
        dragon.recharge_spent.add("a_shadow_breath")
        st = _state([dragon])

        class _R:   # forces a 4 → outside 5-6 → stays spent
            def randint(self, a, b):
                return 4
        recharge.roll_recharges_at_turn_start(dragon, st, _R())
        self.assertIn("a_shadow_breath", dragon.recharge_spent)

    def test_breath_deals_necrotic_in_cone(self):
        dragon = _actor_from("m_juvenile_shadow_dragon", position=(0, 0))
        pc = _dummy(ac=5, hp=200, position=(1, 0))
        st = _state([dragon, pc])
        self._breath(dragon, pc, st)
        dmg = [e for e in st.event_log if e.get("event") == "damage_dealt"]
        self.assertTrue(dmg)
        self.assertTrue(all(e["type"] == "necrotic" for e in dmg))


if __name__ == "__main__":
    unittest.main()
