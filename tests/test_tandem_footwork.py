"""Tandem Footwork tests (College of Dance, Bard L6).

At initiative, a Dance Bard may expend a Bardic Inspiration use, roll its
Bardic die, and add the result to its own + each ally-within-30-ft's
initiative.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core.state import Actor, CombatState, Encounter
from engine.core.runner import EncounterRunner
from engine.loader import load_content
from engine.pc_schema import build_pc_template, derive_pc_resources

_REPO = Path(__file__).resolve().parent.parent
_REG = None


def _reg():
    global _REG
    if _REG is None:
        _REG = load_content(_REPO / "schema" / "content", validate=True,
                            schema_root=_REPO / "schema")
    return _REG


def _dance(level, aid="bard", pos=(0, 0)):
    spec = {"id": aid, "class": "c_bard", "level": level,
            "subclass": "sc_college_of_dance",
            "ability_scores": {"str": 8, "dex": 16, "con": 12,
                               "int": 10, "wis": 12, "cha": 18}}
    tmpl = build_pc_template(spec, _reg())
    res = derive_pc_resources(spec, _reg())
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["dex"] = {"score": 16, "save": 3}
    a = Actor(id=aid, name=aid, template=tmpl, side="pc",
              hp_current=30, hp_max=30, ac=15, position=pos,
              speed={"walk": 30}, abilities=ab)
    a.resources = dict(res)
    return a


def _ally(pos=(3, 0)):
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id="ally", name="ally",
                 template={"id": "ta", "name": "ally", "abilities": ab,
                           "cr": {"proficiency_bonus": 2}, "actions": [],
                           "features_known": [],
                           "combat": {"initiative": {"modifier": 0}}},
                 side="pc", hp_current=30, hp_max=30, ac=12,
                 position=pos, speed={"walk": 30}, abilities=ab)


def _roll(actors, seed=3):
    enc = Encounter(id="e", actors=actors)
    st = CombatState(encounter=enc)
    st.round = 1
    EncounterRunner.new(enc, seed=seed).roll_initiative(st)
    return st


class TandemFootworkTest(unittest.TestCase):

    def test_fires_and_spends_bi(self):
        b = _dance(6)
        before = b.resources["bardic_inspiration_uses_remaining"]
        st = _roll([b])
        tf = [e for e in st.event_log if e.get("event") == "tandem_footwork"]
        self.assertTrue(tf)
        self.assertEqual(before - b.resources["bardic_inspiration_uses_remaining"], 1)

    def test_buffs_self_and_nearby_ally(self):
        b = _dance(6)
        ally = _ally(pos=(3, 0))   # 15 ft
        st = _roll([b, ally])
        tf = [e for e in st.event_log if e.get("event") == "tandem_footwork"][0]
        self.assertIn("bard", tf["beneficiaries"])
        self.assertIn("ally", tf["beneficiaries"])

    def test_does_not_buff_far_ally(self):
        b = _dance(6)
        far = _ally(pos=(8, 0))   # 40 ft > 30
        st = _roll([b, far])
        tf = [e for e in st.event_log if e.get("event") == "tandem_footwork"][0]
        self.assertNotIn("ally", tf["beneficiaries"])

    def test_not_at_l3(self):
        b = _dance(3)
        st = _roll([b])
        self.assertFalse(any(e.get("event") == "tandem_footwork"
                             for e in st.event_log))

    def test_noop_without_bi(self):
        b = _dance(6)
        b.resources["bardic_inspiration_uses_remaining"] = 0
        st = _roll([b])
        self.assertFalse(any(e.get("event") == "tandem_footwork"
                             for e in st.event_log))

    def test_bardic_die_scales(self):
        # L10 Dance Bard rolls d10 (1-10), so the roll can exceed 8.
        rolls = []
        for seed in range(30):
            b = _dance(10)
            st = _roll([b], seed=seed)
            tf = [e for e in st.event_log
                  if e.get("event") == "tandem_footwork"]
            if tf:
                rolls.append(tf[0]["roll"])
        self.assertEqual(max(rolls), 10)   # d10 reached


if __name__ == "__main__":
    unittest.main()
