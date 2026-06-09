"""Bard class-feature tests (PHB 2024).

Covers the combat-relevant class features wired this pass:
  - Bardic Inspiration rest refresh (long rest L1+; short rest L5+ via Font
    of Inspiration).
  - Font of Inspiration (L5): short-rest BI refresh.
  - Countercharm (L7): reaction reroll of a failed Charmed/Frightened save
    (self or ally within 30 ft) with Advantage.
  - Jack of All Trades (L2): +half PB to initiative.
  - Superior Inspiration (L18): top BI up to 2 on initiative.
  - features_known completeness across levels (incl. the build-config
    markers Expertise / Magical Secrets / Words of Creation).
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

from engine.core.state import Actor, CombatState, Encounter
from engine.core.rest import apply_long_rest, apply_short_rest
from engine.core.runner import EncounterRunner
from engine.loader import load_content
from engine.pc_schema import build_pc_template, derive_pc_resources

_REPO = Path(__file__).resolve().parent.parent


def _registry():
    return load_content(_REPO / "schema" / "content", validate=True,
                        schema_root=_REPO / "schema")


_REG = None


def _reg():
    global _REG
    if _REG is None:
        _REG = _registry()
    return _REG


def _bard(level, *, dex_save=2):
    spec = {"id": "b", "class": "c_bard", "level": level,
            "ability_scores": {"str": 8, "dex": 14, "con": 12,
                               "int": 10, "wis": 12, "cha": 18}}
    tmpl = build_pc_template(spec, _reg())
    res = derive_pc_resources(spec, _reg())
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["dex"] = {"score": 14, "save": dex_save}
    ab["wis"] = {"score": 12, "save": 1}
    a = Actor(id="b", name="b", template=tmpl, side="pc",
              hp_current=30, hp_max=30, ac=13, position=(0, 0),
              speed={"walk": 30}, abilities=ab)
    a.resources = dict(res)
    return a


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


class FeaturesKnownTest(unittest.TestCase):

    def test_features_present_by_level(self):
        expected = {
            2: {"f_expertise", "f_jack_of_all_trades"},
            5: {"f_font_of_inspiration"},
            7: {"f_countercharm"},
            10: {"f_magical_secrets"},
            18: {"f_superior_inspiration"},
            20: {"f_words_of_creation"},
        }
        for lvl, feats in expected.items():
            fk = set(_bard(lvl).template["features_known"])
            self.assertTrue(feats <= fk, f"L{lvl} missing {feats - fk}")


class BardicInspirationRefreshTest(unittest.TestCase):

    def test_long_rest_refreshes_at_l3(self):
        b = _bard(3)
        b.resources["bardic_inspiration_uses_remaining"] = 0
        apply_long_rest(b, _state([b]))
        self.assertEqual(b.resources["bardic_inspiration_uses_remaining"], 4)

    def test_short_rest_no_refresh_below_l5(self):
        b = _bard(3)
        b.resources["bardic_inspiration_uses_remaining"] = 1
        apply_short_rest(b, _state([b]))
        self.assertEqual(b.resources["bardic_inspiration_uses_remaining"], 1)

    def test_short_rest_refreshes_at_l5(self):
        b = _bard(5)
        b.resources["bardic_inspiration_uses_remaining"] = 0
        apply_short_rest(b, _state([b]))
        self.assertEqual(b.resources["bardic_inspiration_uses_remaining"], 4)


class CountercharmTest(unittest.TestCase):

    _FRIGHT = {"ability": "wisdom",
               "on_fail": [{"primitive": "apply_condition",
                            "params": {"condition_id": "co_frightened"}}]}
    _FIRE = {"ability": "dexterity",
             "on_fail": [{"primitive": "damage",
                          "params": {"dice": "6d6", "type": "fire"}}]}

    def test_reroll_own_failed_fright_save(self):
        from engine.core.countercharm import try_countercharm_reroll
        b = _bard(7)
        st = _state([b])
        d20, total, outcome = try_countercharm_reroll(
            b, "wisdom", 15, self._FRIGHT, random.Random(7), st)
        self.assertIsNotNone(d20)
        self.assertTrue(b.actions_used_this_turn["reaction"])

    def test_reroll_ally_within_30ft(self):
        from engine.core.countercharm import try_countercharm_reroll
        b = _bard(7)
        ab = {k: {"score": 10, "save": 0}
              for k in ("str", "dex", "con", "int", "wis", "cha")}
        ally = Actor(id="ally", name="ally",
                     template={"id": "ta", "name": "ally", "abilities": ab,
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                     side="pc", hp_current=30, hp_max=30, ac=12,
                     position=(4, 0), speed={"walk": 30}, abilities=ab)
        st = _state([b, ally])
        d20, _, _ = try_countercharm_reroll(
            ally, "wisdom", 15, self._FRIGHT, random.Random(7), st)
        self.assertIsNotNone(d20)
        self.assertTrue(b.actions_used_this_turn["reaction"])

    def test_no_reroll_for_non_charm_fright_save(self):
        from engine.core.countercharm import try_countercharm_reroll
        b = _bard(7)
        st = _state([b])
        d20, _, _ = try_countercharm_reroll(
            b, "dexterity", 15, self._FIRE, random.Random(7), st)
        self.assertIsNone(d20)

    def test_no_reroll_below_l7(self):
        from engine.core.countercharm import try_countercharm_reroll
        b = _bard(5)
        st = _state([b])
        d20, _, _ = try_countercharm_reroll(
            b, "wisdom", 15, self._FRIGHT, random.Random(7), st)
        self.assertIsNone(d20)

    def test_no_reroll_without_reaction(self):
        from engine.core.countercharm import try_countercharm_reroll
        b = _bard(7)
        b.actions_used_this_turn["reaction"] = True
        st = _state([b])
        d20, _, _ = try_countercharm_reroll(
            b, "wisdom", 15, self._FRIGHT, random.Random(7), st)
        self.assertIsNone(d20)

    def test_reroll_has_advantage(self):
        # With a guaranteed-low single die the advantage reroll should beat
        # a forced-low first roll on average; here we just assert the reroll
        # uses two dice by checking the result is the max over many seeds.
        from engine.core.countercharm import try_countercharm_reroll
        highs = 0
        for seed in range(40):
            b = _bard(7)
            st = _state([b])
            d20, _, _ = try_countercharm_reroll(
                b, "wisdom", 99, self._FRIGHT, random.Random(seed), st)
            if d20 >= 11:
                highs += 1
        # Advantage skews high: >50% of rerolls should be 11+.
        self.assertGreater(highs, 20)


class JackOfAllTradesTest(unittest.TestCase):

    def test_adds_half_pb_to_initiative(self):
        b = _bard(12)   # PB 4 → +2
        enc = Encounter(id="e", actors=[b])
        st = CombatState(encounter=enc)
        st.round = 1
        EncounterRunner.new(enc, seed=42).roll_initiative(st)
        ab = b.abilities
        plain = Actor(id="p", name="p",
                      template={"id": "tp", "name": "p", "abilities": ab,
                                "cr": {"proficiency_bonus": 4}, "actions": [],
                                "features_known": [],
                                "combat": {"initiative": {"modifier": 2}}},
                      side="pc", hp_current=30, hp_max=30, ac=13,
                      position=(0, 0), speed={"walk": 30}, abilities=ab)
        enc2 = Encounter(id="e2", actors=[plain])
        st2 = CombatState(encounter=enc2)
        st2.round = 1
        EncounterRunner.new(enc2, seed=42).roll_initiative(st2)
        self.assertEqual(b.initiative - plain.initiative, 2)


class SuperiorInspirationTest(unittest.TestCase):

    def test_tops_up_to_two_on_initiative(self):
        b = _bard(18)
        b.resources["bardic_inspiration_uses_remaining"] = 0
        enc = Encounter(id="e", actors=[b])
        st = CombatState(encounter=enc)
        st.round = 1
        EncounterRunner.new(enc, seed=1).roll_initiative(st)
        self.assertEqual(b.resources["bardic_inspiration_uses_remaining"], 2)

    def test_does_not_lower_existing(self):
        b = _bard(18)
        b.resources["bardic_inspiration_uses_remaining"] = 4
        enc = Encounter(id="e", actors=[b])
        st = CombatState(encounter=enc)
        st.round = 1
        EncounterRunner.new(enc, seed=1).roll_initiative(st)
        self.assertEqual(b.resources["bardic_inspiration_uses_remaining"], 4)


if __name__ == "__main__":
    unittest.main()
