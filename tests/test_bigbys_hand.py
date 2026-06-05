"""Bigby's Hand (Lever B Stage 2c) — the first PC concentration SUMMON.

The canonical action-economy doubling: a Wizard conjures a Large hand of
force that deals recurring 5d8 Force damage every round (the Clenched Fist),
WHILE the Wizard's own action drops Synaptic Static / a cantrip.

Verifies:
  - the spell is on the Wizard 5th-level list (character level 9+), shaped as
    a concentration `summon` action referencing m_bigbys_hand;
  - the m_bigbys_hand stat block loads and its Clenched Fist scores real DPR;
  - casting it summons the hand into the encounter, tagged to the caster's
    concentration (Stage 2a), and ending concentration dismisses it;
  - the AI values it (Stage 2b summon scorer > 0).

Run via:
    python -m unittest tests.test_bigbys_hand
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.ai.defensive_ehp import estimate_dpr
from engine.ai.ehp_scoring import offensive_ehp_summon
from engine.cli import _build_actor
from engine.core import summoning
from engine.core.concentration import apply_concentration, end_concentration
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template
from engine.primitives import _summon

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _wizard_actions(level):
    spec = {"class": "c_wizard", "level": level,
            "ability_scores": {"str": 8, "dex": 12, "con": 14,
                                "int": 18, "wis": 12, "cha": 10}}
    return {a.get("id"): a for a in build_pc_template(spec, _registry())
            .get("actions", [])}


def _build_hand():
    return _build_actor(
        {"template_ref": {"entity_type": "monster", "id": "m_bigbys_hand"},
         "instance_id": "__hand__", "position": [0, 0]}, _registry())


class BigbysHandContentTest(unittest.TestCase):

    def test_on_wizard_list_at_l13(self):
        self.assertIn("a_bigbys_hand", _wizard_actions(13))

    def test_gated_to_char_level_9(self):
        self.assertNotIn("a_bigbys_hand", _wizard_actions(8))
        self.assertIn("a_bigbys_hand", _wizard_actions(9))

    def test_shape_is_concentration_summon(self):
        bh = _wizard_actions(13)["a_bigbys_hand"]
        self.assertEqual(bh["type"], "summon")
        self.assertEqual(bh["spell_slot_level"], 5)
        self.assertTrue(bh.get("concentration"))
        step = bh["pipeline"][0]
        self.assertEqual(step["primitive"], "summon")
        self.assertEqual(step["params"]["monster"], "m_bigbys_hand")
        self.assertEqual(step["params"]["max_total"], 1)

    def test_hand_stat_block_clenched_fist(self):
        hand = _build_hand()
        self.assertEqual(hand.ac, 20)
        # Clenched Fist: 5d8 force, present + scores real DPR.
        ids = {a.get("id") for a in (hand.template.get("actions") or [])}
        self.assertIn("a_clenched_fist", ids)
        self.assertGreater(estimate_dpr(hand), 0.0)


class BigbysHandIntegrationTest(unittest.TestCase):
    """Cast → summon present + concentration-tagged → end → dismissed."""

    def _wizard(self):
        return _build_actor(
            {"instance_id": "wiz", "side": "pc",
             "pc": {"class": "c_wizard", "level": 13,
                    "ability_scores": {"str": 8, "dex": 12, "con": 14,
                                        "int": 18, "wis": 12, "cha": 10}}},
            _registry())

    def _foe(self):
        return _build_actor(
            {"instance_id": "foe", "side": "enemy", "position": [4, 0],
             "template_ref": {"entity_type": "monster",
                              "id": "m_fire_giant"}}, _registry())

    def test_cast_summons_hand_and_concentration_dismisses_it(self):
        wiz, foe = self._wizard(), self._foe()
        st = CombatState(encounter=Encounter(id="t", actors=[wiz, foe]))
        st.turn_order = [wiz.id, foe.id]
        st.round = 1
        st.content_registry = _registry()

        bh = {a.get("id"): a for a in wiz.template.get("actions", [])}[
            "a_bigbys_hand"]

        # Mimic the cast: apply concentration + run the summon primitive.
        apply_concentration(wiz, bh, st)
        st.current_attack = {"actor": wiz, "action": bh}
        _summon(bh["pipeline"][0]["params"], st, EventBus())

        hands = [a for a in st.encounter.actors
                 if a.summoned_by == "wiz"]
        self.assertEqual(len(hands), 1)
        self.assertEqual(hands[0].summon_concentration,
                         {"caster_id": "wiz", "action_id": "a_bigbys_hand"})
        self.assertIn(hands[0].id, st.turn_order)

        # Concentration ends → hand vanishes.
        end_concentration(wiz, st, reason="dropped")
        roster = {a.id for a in st.encounter.actors}
        self.assertNotIn(hands[0].id, roster)
        self.assertNotIn(hands[0].id, st.turn_order)

    def test_ai_values_the_summon(self):
        wiz, foe = self._wizard(), self._foe()
        st = CombatState(encounter=Encounter(id="t", actors=[wiz, foe]))
        st.turn_order = [wiz.id, foe.id]
        st.round = 1
        st.content_registry = _registry()
        bh = {a.get("id"): a for a in wiz.template.get("actions", [])}[
            "a_bigbys_hand"]
        self.assertGreater(offensive_ehp_summon(wiz, bh, st), 0.0)


if __name__ == "__main__":
    unittest.main()
