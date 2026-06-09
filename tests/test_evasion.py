"""Evasion substrate tests (Rogue/Monk L7 Evasion + Dance L14 Leading Evasion).

On a DEX save-for-half effect (on_fail full + on_success half), a creature
with Evasion takes 0 on success and half on fail. Leading Evasion also shares
the benefit with creatures making the same save within 5 ft. No benefit while
Incapacitated. Non-DEX saves and save-or-nothing effects are unaffected.
"""
from __future__ import annotations

import random
import statistics
import unittest

import engine.primitives as primitives_module
from engine.core.evasion import has_evasion, select_evasion_subs
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter


def _ab(dex_save=2):
    d = {k: {"score": 14, "save": 2}
         for k in ("str", "dex", "con", "int", "wis", "cha")}
    d["dex"] = {"score": 14, "save": dex_save}
    return d


def _actor(aid, feats=(), side="pc", pos=(0, 0), hp=60, dex_save=2):
    ab = _ab(dex_save)
    return Actor(id=aid, name=aid,
                 template={"id": f"t_{aid}", "name": aid, "abilities": ab,
                           "cr": {"proficiency_bonus": 3}, "actions": [],
                           "features_known": list(feats)},
                 side=side, hp_current=hp, hp_max=hp, ac=15,
                 position=pos, speed={"walk": 30}, abilities=ab)


def _fireball(dc):
    return {"ability": "dexterity", "dc": dc, "affected": "current_target",
            "on_fail": [{"primitive": "damage",
                         "params": {"dice": "8d6", "type": "fire"}}],
            "on_success": [{"primitive": "damage",
                            "params": {"dice": "8d6", "type": "fire",
                                       "multiplier": 0.5}}]}


def _cast(target, params, actors, seed):
    st = CombatState(encounter=Encounter(id="e", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.current_attack = {"actor": actors[0], "target": target}
    primitives_module.set_rng(random.Random(seed))
    hp0 = target.hp_current
    primitives_module._forced_save(params, st, EventBus())
    return hp0 - target.hp_current, st


def _avg_damage(feats, dc, *, extra=None, seeds=200, dex_save=2):
    dmgs = []
    caster = _actor("caster", side="enemy")
    for seed in range(seeds):
        t = _actor("t", feats, dex_save=dex_save)
        actors = [caster, t] + ([_actor(*extra)] if extra else [])
        # rebuild with extra ally if provided
        if extra:
            ally = actors[2]
            ally.position = (1, 0)   # within 5 ft of t at (0,0)
        d, _ = _cast(t, _fireball(dc), actors, seed)
        dmgs.append(d)
    return statistics.mean(dmgs)


class HasEvasionTest(unittest.TestCase):

    def test_evasion_feature(self):
        self.assertTrue(has_evasion(_actor("r", ["f_evasion"])))

    def test_leading_evasion_feature(self):
        self.assertTrue(has_evasion(_actor("b", ["f_leading_evasion"])))

    def test_no_feature(self):
        self.assertFalse(has_evasion(_actor("x", [])))

    def test_incapacitated_negates(self):
        a = _actor("r", ["f_evasion"])
        a.applied_conditions.append({"condition_id": "co_incapacitated"})
        self.assertFalse(has_evasion(a))

    def test_leading_evasion_sharing_within_5ft(self):
        protege = _actor("p", [], pos=(0, 0))
        bard = _actor("bard", ["f_leading_evasion"], pos=(1, 0))   # 5 ft
        st = CombatState(encounter=Encounter(id="e", actors=[protege, bard]))
        self.assertTrue(has_evasion(protege, st))

    def test_no_sharing_beyond_5ft(self):
        protege = _actor("p", [], pos=(0, 0))
        bard = _actor("bard", ["f_leading_evasion"], pos=(3, 0))   # 15 ft
        st = CombatState(encounter=Encounter(id="e", actors=[protege, bard]))
        self.assertFalse(has_evasion(protege, st))


class SelectSubsTest(unittest.TestCase):

    def test_non_dex_save_no_evasion(self):
        t = _actor("r", ["f_evasion"])
        self.assertIsNone(select_evasion_subs(
            t, "constitution", "fail", _fireball(10), None))

    def test_save_or_nothing_no_evasion(self):
        # on_success has no damage → not a "half damage" effect.
        t = _actor("r", ["f_evasion"])
        params = {"ability": "dexterity",
                  "on_fail": [{"primitive": "damage",
                               "params": {"dice": "8d6", "type": "fire"}}],
                  "on_success": []}
        self.assertIsNone(select_evasion_subs(
            t, "dexterity", "fail", params, None))

    def test_success_scales_to_zero(self):
        t = _actor("r", ["f_evasion"])
        subs = select_evasion_subs(t, "dexterity", "success",
                                    _fireball(10), None)
        self.assertEqual(subs[0]["params"]["multiplier"], 0.0)

    def test_fail_scales_to_half(self):
        t = _actor("r", ["f_evasion"])
        subs = select_evasion_subs(t, "dexterity", "fail",
                                    _fireball(10), None)
        self.assertEqual(subs[0]["params"]["multiplier"], 0.5)


class DamageOutcomeTest(unittest.TestCase):

    def test_evasion_fail_is_half_of_no_evasion_fail(self):
        no_ev = _avg_damage([], dc=99)            # always fail, full
        ev = _avg_damage(["f_evasion"], dc=99)    # always fail, half
        self.assertAlmostEqual(ev, no_ev / 2, delta=2.0)

    def test_evasion_success_is_zero(self):
        ev = _avg_damage(["f_evasion"], dc=1)     # always succeed → 0
        self.assertEqual(ev, 0.0)

    def test_no_evasion_success_is_half(self):
        no_ev = _avg_damage([], dc=1)             # always succeed → half
        self.assertGreater(no_ev, 0.0)

    def test_leading_evasion_works_like_evasion(self):
        lead = _avg_damage(["f_leading_evasion"], dc=99)
        ev = _avg_damage(["f_evasion"], dc=99)
        self.assertAlmostEqual(lead, ev, delta=2.5)


class IncapacitatedDamageTest(unittest.TestCase):

    def test_incapacitated_takes_full_on_fail(self):
        caster = _actor("caster", side="enemy")
        normal = _actor("n", ["f_evasion"])
        incap = _actor("i", ["f_evasion"])
        incap.applied_conditions.append({"condition_id": "co_incapacitated"})
        dn, _ = _cast(normal, _fireball(99), [caster, normal], 5)
        di, _ = _cast(incap, _fireball(99), [caster, incap], 5)
        # Same seed: incapacitated takes full, evasive takes half.
        self.assertGreater(di, dn)


if __name__ == "__main__":
    unittest.main()
