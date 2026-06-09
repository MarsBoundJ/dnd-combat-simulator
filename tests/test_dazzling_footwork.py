"""Dazzling Footwork tests (College of Dance, Bard L3).

While unarmored + no Shield:
  - Unarmored Defense: AC = 10 + DEX + CHA.
  - Bardic Damage: a DEX Unarmed Strike dealing (Bardic die + DEX) Bludgeoning
    (a_dance_unarmed_strike).
  - Agile Strikes: granting Bardic Inspiration fires one Unarmed Strike at the
    lowest-HP enemy within 5 ft.
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import college_of_dance as CD
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template

_REPO = Path(__file__).resolve().parent.parent
_REG = None


def _reg():
    global _REG
    if _REG is None:
        _REG = load_content(_REPO / "schema" / "content", validate=True,
                            schema_root=_REPO / "schema")
    return _REG


def _tmpl(level=3, dex=16, cha=18, shield=False, armor=None):
    spec = {"id": "b", "class": "c_bard", "level": level,
            "subclass": "sc_college_of_dance",
            "ability_scores": {"str": 8, "dex": dex, "con": 12,
                               "int": 10, "wis": 12, "cha": cha}}
    if shield:
        spec["shield"] = True
    if armor:
        spec["armor"] = armor
    return build_pc_template(spec, _reg())


def _ab(dex_save=3):
    d = {k: {"score": 10, "save": 0}
         for k in ("str", "dex", "con", "int", "wis", "cha")}
    d["dex"] = {"score": 16, "save": dex_save}
    return d


def _bard(level=3):
    t = _tmpl(level)
    b = Actor(id="b", name="b", template=t, side="pc",
              hp_current=25, hp_max=25, ac=t["combat"]["armor_class"],
              position=(0, 0), speed={"walk": 30}, abilities=_ab())
    b.resources = {"bardic_inspiration_uses_remaining": 3,
                   "bardic_inspiration_uses_max": 3}
    return b


def _foe(pos=(1, 0), hp=20, ac=10):
    ab = _ab()
    return Actor(id="foe", name="foe",
                 template={"id": "tf", "name": "foe", "abilities": ab,
                           "cr": {"proficiency_bonus": 2}, "actions": []},
                 side="enemy", hp_current=hp, hp_max=hp, ac=ac,
                 position=pos, speed={"walk": 30}, abilities=ab)


class UnarmoredDefenseTest(unittest.TestCase):

    def test_ac_is_ten_plus_dex_plus_cha(self):
        # DEX 16 (+3) + CHA 18 (+4) → 17
        self.assertEqual(_tmpl(dex=16, cha=18)["combat"]["armor_class"], 17)

    def test_shield_disables_unarmored_defense(self):
        self.assertNotEqual(_tmpl(shield=True)["combat"]["armor_class"], 17)

    def test_armor_disables_unarmored_defense(self):
        ac = _tmpl(armor={"base_ac": 14, "max_dex_bonus": 2})[
            "combat"]["armor_class"]
        self.assertNotEqual(ac, 17)


class BardicDamageActionTest(unittest.TestCase):

    def _unarmed(self, level):
        for a in _tmpl(level)["actions"]:
            if a.get("id") == "a_dance_unarmed_strike":
                return a
        return None

    def test_action_exists(self):
        self.assertIsNotNone(self._unarmed(3))

    def test_dex_based_attack(self):
        a = self._unarmed(3)
        ar = [s for s in a["pipeline"]
              if s["primitive"] == "attack_roll"][0]["params"]
        # DEX +3 + PB +2 = 5
        self.assertEqual(ar.get("bonus"), 5)

    def test_damage_die_scales_with_bardic_die(self):
        for level, die in ((3, "1d6"), (5, "1d8"), (10, "1d10"), (15, "1d12")):
            a = self._unarmed(level)
            dm = [s for s in a["pipeline"]
                  if s["primitive"] == "damage"][0]["params"]
            self.assertEqual(dm.get("dice"), die, f"L{level}")
            self.assertEqual(dm.get("type"), "bludgeoning")


class AgileStrikesTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(0))

    def test_bi_grant_fires_unarmed_strike(self):
        b = _bard()
        ally = Actor(id="ally", name="ally",
                     template={"id": "ta", "name": "ally", "abilities": _ab(),
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                     side="pc", hp_current=20, hp_max=30, ac=12,
                     position=(0, 0), speed={"walk": 30}, abilities=_ab())
        foe = _foe(pos=(1, 0))   # adjacent
        st = CombatState(encounter=Encounter(id="e", actors=[b, ally, foe]))
        st.turn_order = ["b", "ally", "foe"]
        st.round = 1
        st.current_attack = {"actor": b, "target": ally}
        primitives_module._grant_bardic_inspiration({}, st, EventBus())
        self.assertIn("agile_strike", [e.get("event") for e in st.event_log])
        self.assertLess(foe.hp_current, 20)   # struck

    def test_no_strike_when_no_enemy_in_reach(self):
        b = _bard()
        foe = _foe(pos=(5, 0))   # 25 ft — out of 5 ft reach
        st = CombatState(encounter=Encounter(id="e", actors=[b, foe]))
        st.turn_order = ["b", "foe"]
        st.round = 1
        CD.try_agile_strike(b, st, EventBus())
        self.assertEqual(foe.hp_current, 20)

    def test_no_strike_without_feature(self):
        # A non-Dance Bard granting BI doesn't punch.
        spec = {"id": "lore", "class": "c_bard", "level": 3,
                "subclass": "sc_college_of_lore",
                "ability_scores": {"str": 8, "dex": 16, "con": 12,
                                   "int": 10, "wis": 12, "cha": 18}}
        t = build_pc_template(spec, _reg())
        b = Actor(id="lore", name="lore", template=t, side="pc",
                  hp_current=25, hp_max=25, ac=13, position=(0, 0),
                  speed={"walk": 30}, abilities=_ab())
        foe = _foe(pos=(1, 0))
        st = CombatState(encounter=Encounter(id="e", actors=[b, foe]))
        st.turn_order = ["lore", "foe"]
        st.round = 1
        CD.try_agile_strike(b, st, EventBus())
        self.assertEqual(foe.hp_current, 20)

    def test_targets_lowest_hp_enemy(self):
        b = _bard()
        weak = _foe(pos=(1, 0), hp=5)
        weak.id = "weak"
        strong = _foe(pos=(1, 0), hp=40)
        strong.id = "strong"
        st = CombatState(encounter=Encounter(id="e", actors=[b, weak, strong]))
        st.turn_order = ["b", "weak", "strong"]
        st.round = 1
        primitives_module.set_rng(random.Random(0))
        CD.try_agile_strike(b, st, EventBus())
        strike = [e for e in st.event_log if e.get("event") == "agile_strike"][0]
        self.assertEqual(strike["target"], "weak")


if __name__ == "__main__":
    unittest.main()
