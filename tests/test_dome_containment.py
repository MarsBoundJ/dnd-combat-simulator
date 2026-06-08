"""Microwave Stage B: Wall of Force dome — containment valuation + casting.

The floating dome (Stage A) is a save-less positional lockdown. Stage B values
it: trapping a kiter denies its mobility (it can't flee / reposition its breath)
and pins it for the party's focus-fire, so a greedy caster reaches for it vs a
flier. No save-or-lose math (the dome has no save), no LR discount.

Run via:
    python -m unittest tests.test_dome_containment
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.ai.defensive_ehp import (
    defensive_ehp_containment, defensive_ehp_hard_control, _action_traps_in_dome,
)
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


_DOME_ACTION = {
    "id": "a_wall_of_force_dome", "type": "hard_control",
    "pipeline": [{"primitive": "place_barrier",
                  "params": {"shape": "sphere", "gap": True, "move": True}}],
}


def _ab():
    return {k: {"score": 16, "save": 4} for k in
            ("str", "dex", "con", "int", "wis", "cha")}


def _mk(actor_id, side, speed, hp=200):
    # a creature with a real attack so estimate_dpr > 0
    fist = {"id": "a_fist", "type": "weapon_attack",
            "pipeline": [{"primitive": "attack_roll",
                          "params": {"kind": "melee", "bonus": 8, "reach_ft": 10}},
                         {"primitive": "damage",
                          "params": {"dice": "2d10", "modifier": 6,
                                     "type": "bludgeoning", "average": 17}}]}
    return Actor(id=actor_id, name=actor_id,
                 template={"id": f"t_{actor_id}", "abilities": _ab(),
                           "actions": [fist], "cr": {"proficiency_bonus": 4}},
                 side=side, hp_current=hp, hp_max=hp, ac=18,
                 speed=speed, position=(0, 0), abilities=_ab())


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.content_registry = _registry()
    return st


class DetectionTest(unittest.TestCase):
    def test_detects_dome_action(self):
        self.assertTrue(_action_traps_in_dome(_DOME_ACTION))

    def test_non_dome_action_not_detected(self):
        flat = {"pipeline": [{"primitive": "place_barrier",
                              "params": {"length_ft": 30}}]}
        self.assertFalse(_action_traps_in_dome(flat))
        self.assertFalse(_action_traps_in_dome({"pipeline": []}))


class ContainmentValuationTest(unittest.TestCase):
    def test_flier_scores_higher_than_grounded(self):
        caster = _mk("wiz", "pc", {"walk": 30})
        flier = _mk("dragon", "enemy", {"walk": 40, "fly": 80})
        grounded = _mk("giant", "enemy", {"walk": 40})
        st = _state([caster, flier, grounded])
        v_flier = defensive_ehp_containment(caster, flier, _DOME_ACTION, st)
        v_ground = defensive_ehp_containment(caster, grounded, _DOME_ACTION, st)
        self.assertGreater(v_flier, 0.0)
        self.assertGreater(v_flier, v_ground)     # mobility reliance differs

    def test_zero_for_ally_or_dead(self):
        caster = _mk("wiz", "pc", {"walk": 30})
        ally = _mk("fighter", "pc", {"walk": 30})
        st = _state([caster, ally])
        self.assertEqual(
            defensive_ehp_containment(caster, ally, _DOME_ACTION, st), 0.0)

    def test_hard_control_routes_dome_to_containment(self):
        # The save-based path returns 0 for a save-less dome; the router sends
        # it to containment, which is > 0 vs a flier.
        caster = _mk("wiz", "pc", {"walk": 30})
        flier = _mk("dragon", "enemy", {"walk": 40, "fly": 80})
        st = _state([caster, flier])
        self.assertGreater(
            defensive_ehp_hard_control(caster, flier, _DOME_ACTION, st), 0.0)


class ContentTest(unittest.TestCase):
    def test_wizard_has_dome_action(self):
        from sims.adventuring_day import _build_party
        wiz = next(a for a in _build_party(_registry())
                   if a.id == "Wizard_Evoker")
        self.assertTrue(any(a.get("id") == "a_wall_of_force_dome"
                            for a in (wiz.template.get("actions") or [])))


if __name__ == "__main__":
    unittest.main()
