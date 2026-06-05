"""Synaptic Static (Lever B) — the repeatable NON-concentration AoE casters
spam each round while concentrating on a recurring effect.

Verifies: built onto the Wizard + Bard 5th-level lists; correct shape (INT
save, 8d6 psychic, half on success, NOT concentration); and — the load-bearing
Lever-B property — a CONCENTRATING caster can still cast it (the
concentration-candidate filter doesn't suppress it, because it's not a
concentration spell).

Run via:
    python -m unittest tests.test_synaptic_static
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.cli import _build_actor
from engine.core.concentration import apply_concentration
from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, Encounter, CombatState
from engine.loader import load_content
from engine.pc_schema import build_pc_template

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _actions(cls, level):
    spec = {"class": cls, "level": level,
            "ability_scores": {"str": 8, "dex": 12, "con": 14,
                                "int": 18, "wis": 12, "cha": 16}}
    return {a.get("id"): a for a in build_pc_template(spec, _registry())
            .get("actions", [])}


class SynapticStaticContentTest(unittest.TestCase):

    def test_on_wizard_and_bard_at_l13(self):
        self.assertIn("a_synaptic_static", _actions("c_wizard", 13))
        self.assertIn("a_synaptic_static", _actions("c_bard", 13))

    def test_gated_to_char_level_9(self):
        self.assertNotIn("a_synaptic_static", _actions("c_wizard", 8))
        self.assertIn("a_synaptic_static", _actions("c_wizard", 9))

    def test_shape_is_non_concentration_int_psychic_aoe(self):
        ss = _actions("c_wizard", 13)["a_synaptic_static"]
        self.assertEqual(ss["type"], "aoe_attack")
        self.assertEqual(ss["spell_slot_level"], 5)
        self.assertFalse(ss.get("concentration"))          # NOT concentration
        self.assertEqual(ss["area"]["shape"], "sphere")
        fs = ss["pipeline"][0]
        self.assertEqual(fs["params"]["ability"], "intelligence")
        on_fail = fs["params"]["on_fail"][0]["params"]
        self.assertEqual(on_fail["type"], "psychic")
        self.assertEqual(on_fail["dice"], "8d6")


class SynapticStaticConcurrentTest(unittest.TestCase):
    """The Lever-B point: a concentrating caster can STILL cast Synaptic Static
    (non-conc), while a concentration spell would be suppressed."""

    def _wizard(self):
        spec = {"instance_id": "wiz", "side": "pc",
                "pc": {"class": "c_wizard", "level": 13,
                       "ability_scores": {"str": 8, "dex": 12, "con": 14,
                                          "int": 18, "wis": 12, "cha": 10}}}
        return _build_actor(spec, _registry())

    def test_concentrating_caster_can_still_cast_synaptic_static(self):
        wiz = self._wizard()
        foe = _build_actor({"instance_id": "foe", "side": "enemy",
                            "position": [4, 0],
                            "template_ref": {"entity_type": "monster",
                                             "id": "m_fire_giant"}}, _registry())
        st = CombatState(encounter=Encounter(id="t", actors=[wiz, foe]))
        st.turn_order = [wiz.id, foe.id]
        st.round = 1
        # Concentrate on a control spell.
        apply_concentration(
            wiz, {"id": "a_hold_monster", "concentration": True}, st)
        ids = {c["action"].get("id") for c in generate_candidates(wiz, st)
               if c.get("action")}
        # Non-conc nuke survives the concentration filter; conc spells don't.
        self.assertIn("a_synaptic_static", ids)
        self.assertNotIn("a_hold_monster", ids)
        self.assertNotIn("a_hypnotic_pattern", ids)


if __name__ == "__main__":
    unittest.main()
