"""Target-effectiveness gate — the AI must not pick a spell against a
target it can't affect (e.g. Hold Person → Humanoid only; a dragon can
never be held).

From the first-sim diagnosis: a Lore Bard wasted three rounds + all its
2nd-level slots casting Hold Person at the Adult Red Dragon.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core.pipeline import generate_candidates, _target_creature_type_ok
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content


def _abil():
    return {k: {"score": 12, "save": 1}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _actor(actor_id, side, ctype, pos=(0, 0)):
    return Actor(id=actor_id, name=actor_id,
                  template={"id": f"t_{actor_id}", "abilities": _abil(),
                             "actions": [], "cr": {"proficiency_bonus": 2}},
                  side=side, hp_current=40, hp_max=40, ac=14,
                  speed={"walk": 30}, position=pos, abilities=_abil(),
                  creature_type=ctype)


def _hold_person_action():
    return {"id": "a_hold_person", "name": "Hold Person",
            "type": "hard_control", "range_ft": 60,
            "target_creature_types": ["humanoid"],
            "pipeline": [{"primitive": "forced_save",
                           "params": {"ability": "wisdom", "dc": 15,
                                       "affected": "current_target",
                                       "on_fail": [], "on_success": []}}]}


class HelperTest(unittest.TestCase):

    def test_no_restriction_allows_any(self):
        c = {"action": {"id": "x"}, "target": _actor("d", "enemy", "dragon")}
        self.assertTrue(_target_creature_type_ok(c))

    def test_restriction_blocks_out_of_type(self):
        c = {"action": _hold_person_action(),
              "target": _actor("d", "enemy", "dragon")}
        self.assertFalse(_target_creature_type_ok(c))

    def test_restriction_allows_in_type(self):
        c = {"action": _hold_person_action(),
              "target": _actor("g", "enemy", "humanoid")}
        self.assertTrue(_target_creature_type_ok(c))

    def test_no_target_is_ok(self):
        c = {"action": _hold_person_action(), "target": None}
        self.assertTrue(_target_creature_type_ok(c))


class CandidateGenTest(unittest.TestCase):

    def _state(self, caster, target):
        enc = Encounter(id="t", actors=[caster, target])
        st = CombatState(encounter=enc)
        st.turn_order = [caster.id, target.id]
        st.round = 1
        return st

    def _offers_hold_person(self, caster, target):
        st = self._state(caster, target)
        cands = generate_candidates(caster, st, slot="action")
        return any(c["action"].get("id") == "a_hold_person" for c in cands)

    def _caster(self, pos=(1, 0)):
        a = _actor("bard", "pc", "humanoid", pos=pos)
        a.template["actions"] = [_hold_person_action()]
        return a

    def test_hold_person_filtered_vs_dragon(self):
        self.assertFalse(
            self._offers_hold_person(self._caster(), _actor("drg", "enemy", "dragon")))

    def test_hold_person_offered_vs_humanoid(self):
        self.assertTrue(
            self._offers_hold_person(self._caster(), _actor("cultist", "enemy", "humanoid")))


class ContentTest(unittest.TestCase):

    def test_hold_person_feature_is_humanoid_restricted(self):
        reg = load_content(Path(__file__).parent.parent / "schema" / "content",
                            validate=True,
                            schema_root=Path(__file__).parent.parent / "schema" / "definitions")
        hp = reg.get("feature", "f_hold_person")
        self.assertEqual(
            hp["action_template"].get("target_creature_types"), ["humanoid"])
        # Hold Monster (any creature) must NOT carry the restriction.
        hm = reg.get("feature", "f_hold_monster")
        self.assertIsNone(
            hm["action_template"].get("target_creature_types"))


if __name__ == "__main__":
    unittest.main()
