"""Creation/level-up validation tests (WS-A6, engine/creation.py).

Exercises the §3.1 status triad and the SRD creation rules: point-buy cost
edge cases, standard-array enforcement, the ability cap, subclass-at-3, HP
modes, prepared-spell counts, multiclass prerequisites (delegated to
engine.core.multiclass), and — crucially — that the three legs are independent:
content gaps don't fail rules_valid, and a legal+resolved build can still be
engine_supported: false.

Run via:
    python -m unittest tests.test_creation_rules
"""
from __future__ import annotations

import unittest

from engine.creation import (
    validate_creation, ValidationResult, Check,
    POINT_BUY_COSTS, POINT_BUY_BUDGET, STANDARD_ARRAY, ABILITY_CAP_AT_CREATION,
)


# A plain {type: {id: entity}} mapping doubles for a ContentRegistry.
def _registry() -> dict:
    return {
        "class": {
            "c_fighter": {"id": "c_fighter", "name": "Fighter",
                          "source": "srd_5.2.1",
                          "level_table": [{"level": 1}, {"level": 2},
                                          {"level": 3}, {"level": 4}]},
            "c_wizard": {"id": "c_wizard", "name": "Wizard",
                         "source": "srd_5.2.1",
                         "level_table": [
                             {"level": 1, "spellcasting":
                              {"cantrips_known": 3, "prepared_spells": 4}},
                             {"level": 2, "spellcasting":
                              {"cantrips_known": 3, "prepared_spells": 5}}]},
        },
        "subclass": {
            "sc_champion": {"id": "sc_champion", "name": "Champion",
                            "source": "srd_5.2.1"},
            "sc_unmodeled": {"id": "sc_unmodeled", "name": "Unwired Order",
                             "source": "phb_2024", "not_modeled": True},
        },
        "race": {"r_human": {"id": "r_human", "name": "Human",
                             "source": "srd_5.2.1"}},
        "background": {
            "bg_soldier": {"id": "bg_soldier", "name": "Soldier",
                           "source": "srd_5.2.1", "feat": "ft_savage_attacker",
                           "skill_proficiencies": ["athletics", "intimidation"],
                           "ability_scores": {"choices":
                                              ["strength", "constitution", "charisma"]}},
        },
        "feat": {
            "ft_savage_attacker": {"id": "ft_savage_attacker", "name": "Savage Attacker",
                                   "source": "srd_5.2.1", "category": "origin"},
            "ft_grappler": {"id": "ft_grappler", "name": "Grappler",
                            "source": "phb_2024", "category": "general",
                            "prerequisites": {
                                "ability_scores": [{"ability": "strength", "min": 13}]}},
        },
    }


# A legal, fully-resolved, fully-supported single-class baseline.
def _valid_spec(**overrides) -> dict:
    spec = {
        "class": "c_fighter", "level": 2,
        "ability_method": "standard_array",
        "ability_scores": {"str": 15, "dex": 14, "con": 13,
                           "int": 12, "wis": 10, "cha": 8},
    }
    spec.update(overrides)
    return spec


class BaselineTest(unittest.TestCase):
    def test_clean_build_passes_all_three(self):
        r = validate_creation(_valid_spec(), _registry())
        self.assertTrue(r.rules_valid.ok, r.rules_valid.reasons)
        self.assertTrue(r.content_resolved.ok, r.content_resolved.reasons)
        self.assertTrue(r.engine_supported.ok, r.engine_supported.reasons)
        self.assertTrue(r.ok)
        self.assertEqual(r.status,
                         {"rules_valid": True, "content_resolved": True,
                          "engine_supported": True})

    def test_result_is_serializable_triad(self):
        d = validate_creation(_valid_spec(), _registry()).to_dict()
        self.assertEqual(set(d["status"]),
                         {"rules_valid", "content_resolved", "engine_supported"})
        self.assertIn("reasons", d["rules_valid"])


class PointBuyTest(unittest.TestCase):
    def test_cost_table_values(self):
        # The SRD costs — note 14 costs 7 and 15 costs 9 (not linear).
        self.assertEqual(POINT_BUY_COSTS,
                         {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9})
        self.assertEqual(POINT_BUY_BUDGET, 27)

    def _pb(self, scores):
        return validate_creation(
            _valid_spec(ability_method="point_buy", ability_scores=scores),
            _registry())

    def test_exactly_27_is_valid(self):
        # 15,15,13,10,10,8 -> 9+9+5+2+2+0 = 27
        r = self._pb({"str": 15, "dex": 15, "con": 13,
                      "int": 10, "wis": 10, "cha": 8})
        self.assertTrue(r.rules_valid.ok, r.rules_valid.reasons)

    def test_one_point_over_budget_fails(self):
        # 15,15,14,11,8,8 -> 9+9+7+3+0+0 = 28
        r = self._pb({"str": 15, "dex": 15, "con": 14,
                      "int": 11, "wis": 8, "cha": 8})
        self.assertFalse(r.rules_valid.ok)
        self.assertTrue(any("budget" in x for x in r.rules_valid.reasons))

    def test_score_above_15_rejected(self):
        r = self._pb({"str": 16, "dex": 14, "con": 13,
                      "int": 12, "wis": 10, "cha": 8})
        self.assertFalse(r.rules_valid.ok)
        self.assertTrue(any("buyable range" in x for x in r.rules_valid.reasons))

    def test_under_budget_is_allowed(self):
        # 8s everywhere -> 0 points. Legal (you needn't spend all 27).
        r = self._pb({"str": 8, "dex": 8, "con": 8,
                      "int": 8, "wis": 8, "cha": 8})
        self.assertTrue(r.rules_valid.ok, r.rules_valid.reasons)


class StandardArrayTest(unittest.TestCase):
    def _sa(self, scores):
        return validate_creation(
            _valid_spec(ability_method="standard_array", ability_scores=scores),
            _registry())

    def test_exact_array_valid(self):
        r = self._sa({"str": 15, "dex": 14, "con": 13,
                      "int": 12, "wis": 10, "cha": 8})
        self.assertTrue(r.rules_valid.ok, r.rules_valid.reasons)
        self.assertEqual(sorted(STANDARD_ARRAY, reverse=True),
                         [15, 14, 13, 12, 10, 8])

    def test_duplicate_value_rejected(self):
        r = self._sa({"str": 15, "dex": 15, "con": 13,
                      "int": 12, "wis": 10, "cha": 8})
        self.assertFalse(r.rules_valid.ok)
        self.assertTrue(any("standard array" in x for x in r.rules_valid.reasons))

    def test_off_array_value_rejected(self):
        r = self._sa({"str": 16, "dex": 14, "con": 13,
                      "int": 12, "wis": 11, "cha": 8})
        self.assertFalse(r.rules_valid.ok)


class AbilityCapTest(unittest.TestCase):
    def test_origin_bonus_within_cap_ok(self):
        # base 14 str + origin +2 -> 16, fine.
        spec = _valid_spec(
            ability_method="point_buy",
            base_ability_scores={"str": 14, "dex": 13, "con": 13,
                                 "int": 10, "wis": 10, "cha": 12},
            ability_scores={"str": 14, "dex": 13, "con": 13,
                            "int": 10, "wis": 10, "cha": 12},
            background="bg_soldier",
            origin_ability_bonuses={"str": 2, "con": 1})
        r = validate_creation(spec, _registry())
        self.assertTrue(r.rules_valid.ok, r.rules_valid.reasons)

    def test_manual_score_over_20_rejected(self):
        spec = _valid_spec(ability_method="manual",
                           ability_scores={"str": 21, "dex": 14, "con": 13,
                                           "int": 12, "wis": 10, "cha": 8})
        r = validate_creation(spec, _registry())
        self.assertFalse(r.rules_valid.ok)
        self.assertTrue(any(str(ABILITY_CAP_AT_CREATION) in x
                            for x in r.rules_valid.reasons))

    def test_origin_bonus_pattern_enforced(self):
        # +2/+2 is neither +2/+1 nor +1/+1/+1.
        spec = _valid_spec(background="bg_soldier",
                           origin_ability_bonuses={"str": 2, "con": 2})
        r = validate_creation(spec, _registry())
        self.assertFalse(r.rules_valid.ok)
        self.assertTrue(any("background increase" in x
                            for x in r.rules_valid.reasons))

    def test_origin_bonus_must_target_background_abilities(self):
        # bg_soldier raises STR/CON/CHA; raising DEX is illegal.
        spec = _valid_spec(background="bg_soldier",
                           origin_ability_bonuses={"dex": 2, "str": 1})
        r = validate_creation(spec, _registry())
        self.assertFalse(r.rules_valid.ok)


class SubclassTimingTest(unittest.TestCase):
    def test_subclass_before_level_3_rejected(self):
        spec = _valid_spec(level=2, subclass="sc_champion")
        r = validate_creation(spec, _registry())
        self.assertFalse(r.rules_valid.ok)
        self.assertTrue(any("subclass" in x for x in r.rules_valid.reasons))

    def test_level_3_requires_subclass(self):
        spec = _valid_spec(level=3)              # no subclass
        r = validate_creation(spec, _registry())
        self.assertFalse(r.rules_valid.ok)
        self.assertTrue(any("requires a subclass" in x
                            for x in r.rules_valid.reasons))

    def test_subclass_at_level_3_ok(self):
        spec = _valid_spec(level=3, subclass="sc_champion")
        r = validate_creation(spec, _registry())
        self.assertTrue(r.rules_valid.ok, r.rules_valid.reasons)


class EngineSupportTest(unittest.TestCase):
    def test_legal_resolved_but_unmodeled_subclass(self):
        # The canonical §3.1 case: rules_valid + content_resolved true,
        # engine_supported FALSE (subclass present but not wired).
        spec = _valid_spec(level=3, subclass="sc_unmodeled")
        r = validate_creation(spec, _registry())
        self.assertTrue(r.rules_valid.ok, r.rules_valid.reasons)
        self.assertTrue(r.content_resolved.ok, r.content_resolved.reasons)
        self.assertFalse(r.engine_supported.ok)
        self.assertTrue(any("sc_unmodeled" in x
                            for x in r.engine_supported.reasons))
        self.assertEqual(r.status["engine_supported"], False)


class ContentResolutionTest(unittest.TestCase):
    def test_unbuilt_equipment_is_content_gap_not_rules_failure(self):
        spec = _valid_spec(equipment={"armor": "eq_chain_mail",
                                      "weapons": ["eq_longsword"]})
        r = validate_creation(spec, _registry())
        # Legal build; equipment just isn't authored yet.
        self.assertTrue(r.rules_valid.ok, r.rules_valid.reasons)
        self.assertFalse(r.content_resolved.ok)
        reasons = " ".join(r.content_resolved.reasons)
        self.assertIn("eq_chain_mail", reasons)
        self.assertIn("eq_longsword", reasons)

    def test_unknown_class_is_content_gap(self):
        spec = _valid_spec(**{"class": "c_artificer"})
        r = validate_creation(spec, _registry())
        self.assertFalse(r.content_resolved.ok)
        self.assertTrue(any("c_artificer" in x
                            for x in r.content_resolved.reasons))

    def test_no_registry_skips_content_and_engine(self):
        r = validate_creation(_valid_spec(), registry=None)
        self.assertTrue(r.rules_valid.ok, r.rules_valid.reasons)
        self.assertTrue(r.content_resolved.ok)   # vacuous when no registry
        self.assertTrue(r.engine_supported.ok)


class MulticlassPrereqTest(unittest.TestCase):
    def _spec(self, int_score):
        # Fighter 1 / Wizard 1; manual scores so we set prereqs directly.
        return {
            "classes": [{"class": "c_fighter", "level": 1},
                        {"class": "c_wizard", "level": 1}],
            "ability_method": "manual",
            "ability_scores": {"str": 15, "dex": 12, "con": 13,
                               "int": int_score, "wis": 10, "cha": 8},
        }

    def test_prereq_pass(self):
        # STR 15 (Fighter STR-or-DEX) and INT 14 (Wizard INT) both >= 13.
        r = validate_creation(self._spec(14), _registry())
        self.assertTrue(r.rules_valid.ok, r.rules_valid.reasons)

    def test_prereq_fail(self):
        # INT 11 fails the Wizard multiclass prerequisite.
        r = validate_creation(self._spec(11), _registry())
        self.assertFalse(r.rules_valid.ok)
        self.assertTrue(any("c_wizard" in x and "13" in x
                            for x in r.rules_valid.reasons))


class PreparedSpellCountTest(unittest.TestCase):
    def _wizard(self, prepared_n):
        return {
            "class": "c_wizard", "level": 1,
            "ability_method": "standard_array",
            "ability_scores": {"str": 8, "dex": 14, "con": 13,
                               "int": 15, "wis": 12, "cha": 10},
            "spells": {"prepared": [{"id": f"sp_{i}", "source_class": "c_wizard"}
                                    for i in range(prepared_n)]},
        }

    def test_within_limit_ok_ignoring_content(self):
        # 4 prepared == the L1 allowance; rules pass (spell ids are a content
        # gap, but that's a separate leg).
        r = validate_creation(self._wizard(4), _registry())
        self.assertTrue(r.rules_valid.ok, r.rules_valid.reasons)

    def test_over_limit_fails_rules(self):
        r = validate_creation(self._wizard(6), _registry())
        self.assertFalse(r.rules_valid.ok)
        self.assertTrue(any("prepared spells exceeds" in x
                            for x in r.rules_valid.reasons))


class HPModeTest(unittest.TestCase):
    def test_valid_modes(self):
        for mode in ("fixed", "average", "rolled"):
            r = validate_creation(_valid_spec(level_up={"hp_mode": mode}),
                                  _registry())
            self.assertTrue(r.rules_valid.ok, (mode, r.rules_valid.reasons))

    def test_unknown_mode_rejected(self):
        r = validate_creation(_valid_spec(level_up={"hp_mode": "maximized"}),
                              _registry())
        self.assertFalse(r.rules_valid.ok)


class FeatPrereqTest(unittest.TestCase):
    def test_feat_ability_prereq_met(self):
        spec = _valid_spec(feats=["ft_grappler"])   # needs STR 13; baseline has 15
        r = validate_creation(spec, _registry())
        self.assertTrue(r.rules_valid.ok, r.rules_valid.reasons)

    def test_feat_ability_prereq_unmet(self):
        spec = _valid_spec(
            ability_scores={"str": 10, "dex": 15, "con": 13,
                            "int": 12, "wis": 14, "cha": 8},
            feats=["ft_grappler"])               # STR 10 < 13
        r = validate_creation(spec, _registry())
        self.assertFalse(r.rules_valid.ok)
        self.assertTrue(any("ft_grappler" in x for x in r.rules_valid.reasons))


if __name__ == "__main__":
    unittest.main()
