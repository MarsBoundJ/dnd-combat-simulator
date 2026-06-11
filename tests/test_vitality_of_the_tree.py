"""Vitality of the Tree tests (Path of the World Tree, Barbarian L3).

Rage-scoped Temporary HP:
  - Vitality Surge: on rage entry, gain Temp HP = Barbarian level.
  - Life-Giving Force: at the start of each turn while raging, grant the
    most-wounded ally within 10 ft Temp HP = sum of Nd6 (N = Rage Damage
    bonus).
  - All World-Tree Temp HP vanishes when the Rage ends.

Layers:
  1. Vitality Surge (rage entry; max-semantics; no-op without feature).
  2. Life-Giving Force (turn-start grant; beneficiary = most wounded in 10ft).
  3. Vanish on rage end (self + ally).
  4. Rage-entry scoring reflects the Vitality value.
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

from engine.core import rage as R
from engine.core import world_tree as WT
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template

_REPO = Path(__file__).resolve().parent.parent


def _registry():
    return load_content(_REPO / "schema" / "content", validate=True,
                        schema_root=_REPO / "schema")


def _ab():
    return {k: {"score": 16, "save": 1}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _barb(aid="b", *, side="pc", pos=(0, 0), level=5, feature=True,
            hp=60, hp_max=60):
    ab = _ab()
    tmpl = {"id": f"t_{aid}", "name": aid, "abilities": ab,
            "cr": {"proficiency_bonus": 3}, "actions": [],
            "features_known": ["f_vitality_of_the_tree"] if feature else [],
            "levels": {"barbarian": level}}
    return Actor(id=aid, name=aid, template=tmpl, side=side,
                 hp_current=hp, hp_max=hp_max, ac=14, position=pos,
                 speed={"walk": 30}, abilities=ab)


def _ally(aid="a", *, side="pc", pos=(1, 0), hp=15, hp_max=40):
    ab = _ab()
    return Actor(id=aid, name=aid,
                 template={"id": f"t_{aid}", "name": aid, "abilities": ab,
                           "cr": {"proficiency_bonus": 2}, "actions": []},
                 side=side, hp_current=hp, hp_max=hp_max, ac=14,
                 position=pos, speed={"walk": 30}, abilities=ab)


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


class VitalitySurgeTest(unittest.TestCase):

    def test_grants_temp_hp_equal_to_level(self):
        b = _barb(level=7)
        st = _state([b])
        R.enter_rage(b, st)
        self.assertEqual(b.temp_hp, 7)

    def test_no_surge_without_feature(self):
        b = _barb(level=7, feature=False)
        st = _state([b])
        R.enter_rage(b, st)
        self.assertEqual(b.temp_hp, 0)

    def test_max_semantics_keeps_greater(self):
        b = _barb(level=3)
        b.temp_hp = 10   # already has more from elsewhere
        st = _state([b])
        R.enter_rage(b, st)
        self.assertEqual(b.temp_hp, 10)   # level 3 doesn't lower it

    def test_logs_event(self):
        b = _barb(level=5)
        st = _state([b])
        R.enter_rage(b, st)
        self.assertIn("vitality_surge", [e.get("event") for e in st.event_log])


class LifeGivingForceTest(unittest.TestCase):

    def test_grants_ally_temp_hp(self):
        b = _barb(level=5)
        ally = _ally(pos=(1, 0))
        st = _state([b, ally])
        R.enter_rage(b, st)
        WT.resolve_life_giving_force(b, st, random.Random(1))
        self.assertGreater(ally.temp_hp, 0)

    def test_picks_most_wounded_in_range(self):
        b = _barb(level=5)
        healthy = _ally("healthy", pos=(1, 0), hp=40, hp_max=40)
        wounded = _ally("wounded", pos=(1, 0), hp=5, hp_max=40)
        st = _state([b, healthy, wounded])
        R.enter_rage(b, st)
        WT.resolve_life_giving_force(b, st, random.Random(1))
        self.assertGreater(wounded.temp_hp, 0)
        self.assertEqual(healthy.temp_hp, 0)

    def test_skips_ally_out_of_range(self):
        b = _barb(level=5)
        far = _ally("far", pos=(3, 0))   # 15 ft > 10 ft
        st = _state([b, far])
        R.enter_rage(b, st)
        WT.resolve_life_giving_force(b, st, random.Random(1))
        self.assertEqual(far.temp_hp, 0)

    def test_no_self_target(self):
        b = _barb(level=5)
        st = _state([b])   # no allies
        R.enter_rage(b, st)
        before = b.temp_hp
        WT.resolve_life_giving_force(b, st, random.Random(1))
        self.assertEqual(b.temp_hp, before)   # unchanged (only Vitality Surge)

    def test_noop_when_not_raging(self):
        b = _barb(level=5)
        ally = _ally(pos=(1, 0))
        st = _state([b, ally])
        WT.resolve_life_giving_force(b, st, random.Random(1))
        self.assertEqual(ally.temp_hp, 0)

    def test_skips_enemy(self):
        b = _barb(level=5)
        enemy = _ally("enemy", side="enemy", pos=(1, 0))
        st = _state([b, enemy])
        R.enter_rage(b, st)
        WT.resolve_life_giving_force(b, st, random.Random(1))
        self.assertEqual(enemy.temp_hp, 0)


class VanishOnRageEndTest(unittest.TestCase):

    def test_self_temp_hp_vanishes(self):
        b = _barb(level=6)
        st = _state([b])
        R.enter_rage(b, st)
        self.assertEqual(b.temp_hp, 6)
        R.end_rage(b, st, reason="manual")
        self.assertEqual(b.temp_hp, 0)

    def test_ally_temp_hp_vanishes(self):
        b = _barb(level=5)
        ally = _ally(pos=(1, 0))
        st = _state([b, ally])
        R.enter_rage(b, st)
        WT.resolve_life_giving_force(b, st, random.Random(1))
        self.assertGreater(ally.temp_hp, 0)
        R.end_rage(b, st, reason="manual")
        self.assertEqual(ally.temp_hp, 0)

    def test_logs_vanish_event(self):
        b = _barb(level=6)
        st = _state([b])
        R.enter_rage(b, st)
        R.end_rage(b, st, reason="manual")
        self.assertIn("world_tree_temp_hp_vanished",
                      [e.get("event") for e in st.event_log])


class ScoringTest(unittest.TestCase):

    def test_rage_score_higher_with_vitality(self):
        from engine.ai.defensive_ehp import _score_rage_entry
        wt = _barb("wt", level=5, feature=True)
        plain = _barb("plain", level=5, feature=False)
        enemy = _ally("enemy", side="enemy", pos=(2, 0), hp=40, hp_max=40)
        ally = _ally("ally", pos=(1, 0))
        st_wt = _state([wt, ally, enemy])
        st_plain = _state([plain, ally, enemy])
        self.assertGreater(_score_rage_entry(wt, st_wt),
                           _score_rage_entry(plain, st_plain))


class IntegrationTest(unittest.TestCase):

    def test_pc_template_has_feature(self):
        spec = {"id": "z", "class": "c_barbarian", "level": 5,
                "subclass": "sc_path_of_the_world_tree",
                "ability_scores": {"str": 18, "dex": 14, "con": 16,
                                   "int": 8, "wis": 10, "cha": 8},
                "weapons": [{"id": "ga", "name": "GA", "damage_dice": "1d12",
                             "damage_type": "slashing",
                             "attack_ability": "str", "reach_ft": 5}]}
        tmpl = build_pc_template(spec, _registry())
        self.assertIn("f_vitality_of_the_tree",
                      tmpl.get("features_known", []))


if __name__ == "__main__":
    unittest.main()
