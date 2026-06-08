"""Summon Celestial (Avenger) — a flying, ranged, expendable summon.

The counterplay to a kiting boss the flying Fighter couldn't be: its 600-ft
Radiant Bow reaches the airborne dragon from the ground (fly 40 is moot), it
risks no PC, and it frees the Cleric from a dead melee role. Verified +13 pts
vs the Adult Red at both-dial-5 (160 seeds).

Run via:
    python -m unittest tests.test_summon_celestial
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.ai.ehp_scoring import offensive_ehp_summon
from engine.core.concentration import apply_concentration, end_concentration
from engine.core.pipeline import _action_reach_ft
from engine.core.state import Actor, Encounter, CombatState
from engine.loader import load_content
from engine.primitives import PrimitiveRegistry

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _cleric():
    from sims.adventuring_day import _build_party
    return next(a for a in _build_party(_registry()) if a.id == "Cleric")


def _foe(pos=(2, 0), hp=200):
    ab = {k: {"score": 14, "save": 2} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id="dragon", name="dragon",
                 template={"id": "m_adult_red_dragon", "abilities": ab,
                           "actions": [], "cr": {"proficiency_bonus": 6}},
                 side="enemy", hp_current=hp, hp_max=hp, ac=19,
                 speed={"walk": 40, "fly": 80}, position=pos, abilities=ab)


class ContentTest(unittest.TestCase):
    def test_cleric_has_summon_celestial(self):
        actions = _cleric().template.get("actions") or []
        self.assertTrue(any(a.get("id") == "a_summon_celestial"
                            for a in actions))

    def test_avenger_stat_block(self):
        av = _registry().get("monster", "m_celestial_spirit_avenger")
        combat = av["combat"]
        self.assertEqual(combat["armor_class"], 16)          # 11 + 5
        self.assertEqual(combat["hit_points"]["average"], 40)
        self.assertEqual(combat["speed"].get("fly"), 40)
        bow = next(a for a in av["actions"] if a["id"] == "a_radiant_bow")
        self.assertEqual(_action_reach_ft(bow), 600)         # long ranged
        mult = next(a for a in av["actions"] if a["type"] == "multiattack")
        self.assertEqual(mult["count"], 2)                   # floor(5/2)


class ValuationTest(unittest.TestCase):
    def test_summon_scores_positive(self):
        cleric = _cleric()
        cleric.position = (0, 0)
        foe = _foe(pos=(2, 0))
        st = CombatState(encounter=Encounter(id="t", actors=[cleric, foe]))
        st.content_registry = _registry()
        action = next(a for a in cleric.template["actions"]
                      if a["id"] == "a_summon_celestial")
        # A long-ranged summon has no travel penalty → positive eHP value.
        self.assertGreater(offensive_ehp_summon(cleric, action, st), 0.0)


class ConcentrationLifecycleTest(unittest.TestCase):
    def test_summon_then_dismiss_on_concentration_end(self):
        cleric = _cleric()
        cleric.position = (0, 0)
        foe = _foe()
        enc = Encounter(id="t", actors=[cleric, foe])
        st = CombatState(encounter=enc)
        st.turn_order = [a.id for a in enc.actors]
        st.content_registry = _registry()
        action = next(a for a in cleric.template["actions"]
                      if a["id"] == "a_summon_celestial")
        st.current_attack = {"actor": cleric, "target": cleric, "action": action}
        apply_concentration(cleric, action, st)
        PrimitiveRegistry.with_defaults().invoke(
            "summon", {"monster": "m_celestial_spirit_avenger", "count": 1,
                       "max_total": 1,
                       "attack_bonus_from": "caster_spell_attack"},
            st, None)
        avengers = [a for a in enc.actors
                    if a.template.get("id") == "m_celestial_spirit_avenger"]
        self.assertEqual(len(avengers), 1)                   # summoned
        end_concentration(cleric, st, reason="test")
        remaining = [a for a in enc.actors
                     if a.template.get("id") == "m_celestial_spirit_avenger"]
        self.assertEqual(remaining, [])                      # dismissed


if __name__ == "__main__":
    unittest.main()
