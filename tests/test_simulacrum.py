"""Microwave Stage D: Simulacrum — a second independent caster.

The Simulacrum unlocks the full microwave combo: the original Wizard holds
the Wall of Force dome (concentration #1) while the Simulacrum holds the
damaging zone — Cloudkill or Sickening Radiance (concentration #2). A
single caster can't do both (one concentration slot).

Tests verify:
  1. build_simulacrum produces a half-HP clone with the same spells.
  2. Two casters can hold independent concentrations.
  3. is_trapped_in_dome prevents redundant re-doming (frees the sim
     for zone duty).
  4. A zone scores HIGHER on a dome-trapped target (can't escape →
     longer effective duration → the microwave synergy signal).

Run via:
    python -m unittest tests.test_simulacrum
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core.concentration import apply_concentration
from engine.core.geometry import Sphere, WALL_BLOCK_NORMAL, WALL_BLOCK_NONE
from engine.core.simulacrum import (
    SIMULACRUM_HP_FRACTION, SIMULACRUM_ID_SUFFIX,
    build_simulacrum, is_simulacrum,
)
from engine.core.state import Actor, CombatState, Encounter
from engine.ai.defensive_ehp import (
    defensive_ehp_containment, is_trapped_in_dome,
)
from engine.loader import load_content

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _party():
    from sims.adventuring_day import _build_party
    return _build_party(_registry())


def _dragon():
    from sims.adventuring_day import _build_monsters
    return _build_monsters(_registry(), [("m_adult_red_dragon", 1)])[0]


def _ab():
    return {k: {"score": 16, "save": 4} for k in
            ("str", "dex", "con", "int", "wis", "cha")}


_DOME_ACTION = {
    "id": "a_wall_of_force_dome", "type": "hard_control",
    "pipeline": [{"primitive": "place_barrier",
                  "params": {"shape": "sphere", "gap": True, "move": True}}],
}

_CLOUDKILL_STUB = {
    "id": "a_cloudkill", "concentration": True,
}

_SR_STUB = {
    "id": "a_sickening_radiance", "concentration": True,
}


def _dome_at(center, radius=2.0):
    return Sphere(center=(float(center[0]), float(center[1])),
                  radius=radius,
                  move=WALL_BLOCK_NORMAL,
                  sight=WALL_BLOCK_NONE,
                  sound=WALL_BLOCK_NONE,
                  light=WALL_BLOCK_NONE)


# ============================================================================
# Simulacrum building
# ============================================================================

class BuildTest(unittest.TestCase):
    def test_half_hp(self):
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        sim = build_simulacrum(wiz)
        expected = max(1, int(wiz.hp_max * SIMULACRUM_HP_FRACTION))
        self.assertEqual(sim.hp_max, expected)
        self.assertEqual(sim.hp_current, sim.hp_max)

    def test_id_suffix(self):
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        sim = build_simulacrum(wiz)
        self.assertEqual(sim.id, f"Wizard_Evoker{SIMULACRUM_ID_SUFFIX}")

    def test_is_simulacrum_flag(self):
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        sim = build_simulacrum(wiz)
        self.assertTrue(is_simulacrum(sim))
        self.assertFalse(is_simulacrum(wiz))

    def test_same_actions(self):
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        sim = build_simulacrum(wiz)
        orig_ids = {a["id"] for a in (wiz.template.get("actions") or [])}
        sim_ids = {a["id"] for a in (sim.template.get("actions") or [])}
        self.assertEqual(orig_ids, sim_ids)

    def test_independent_state(self):
        """Mutating the simulacrum's HP doesn't touch the original."""
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        sim = build_simulacrum(wiz)
        sim.hp_current = 1
        self.assertGreater(wiz.hp_current, 1)

    def test_fresh_concentration(self):
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        wiz.concentration_on = {"action_id": "a_cloudkill", "caster_id": wiz.id}
        sim = build_simulacrum(wiz)
        self.assertIsNone(sim.concentration_on)


# ============================================================================
# Dual concentration (the whole point of Stage D)
# ============================================================================

class DualConcentrationTest(unittest.TestCase):
    def _setup(self):
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        sim = build_simulacrum(wiz)
        dragon = _dragon()
        dragon.position = (5, 0)
        wiz.position = (0, 0)
        sim.position = (0, 5)
        actors = [a for a in party if a.id != wiz.id] + [wiz, sim, dragon]
        enc = Encounter(id="t", actors=actors)
        st = CombatState(encounter=enc)
        st.turn_order = [a.id for a in enc.actors]
        st.content_registry = _registry()
        return st, wiz, sim, dragon

    def test_independent_concentrations(self):
        """Original holds dome, simulacrum holds zone — both active."""
        st, wiz, sim, _d = self._setup()
        apply_concentration(wiz, _DOME_ACTION, st)
        apply_concentration(sim, _CLOUDKILL_STUB, st)
        self.assertIsNotNone(wiz.concentration_on)
        self.assertIsNotNone(sim.concentration_on)
        self.assertEqual(wiz.concentration_on["action_id"],
                         "a_wall_of_force_dome")
        self.assertEqual(sim.concentration_on["action_id"],
                         "a_cloudkill")

    def test_new_concentration_on_sim_drops_only_sims(self):
        """Casting a new conc spell on the sim doesn't touch the original."""
        st, wiz, sim, _d = self._setup()
        apply_concentration(wiz, _DOME_ACTION, st)
        apply_concentration(sim, _CLOUDKILL_STUB, st)
        apply_concentration(sim, _SR_STUB, st)
        self.assertEqual(wiz.concentration_on["action_id"],
                         "a_wall_of_force_dome")
        self.assertEqual(sim.concentration_on["action_id"],
                         "a_sickening_radiance")


# ============================================================================
# Redundant re-doming prevention
# ============================================================================

class RedundantDomeTest(unittest.TestCase):
    def test_trapped_target_not_re_domed(self):
        """Once a target is trapped, defensive_ehp_containment returns 0 for a
        second dome (so the second caster picks the zone instead)."""
        fist = {"id": "a_fist", "type": "weapon_attack",
                "pipeline": [{"primitive": "attack_roll",
                              "params": {"kind": "melee", "bonus": 8,
                                         "reach_ft": 10}},
                             {"primitive": "damage",
                              "params": {"dice": "2d10", "modifier": 6,
                                         "type": "bludgeoning", "average": 17}}]}
        caster = Actor(id="wiz", name="wiz",
                       template={"id": "t_wiz", "abilities": _ab(),
                                 "actions": [fist],
                                 "cr": {"proficiency_bonus": 4}},
                       side="pc", hp_current=80, hp_max=80, ac=15,
                       speed={"walk": 30}, position=(0, 0), abilities=_ab())
        dragon = Actor(id="dragon", name="dragon",
                       template={"id": "t_dragon", "abilities": _ab(),
                                 "actions": [fist],
                                 "cr": {"proficiency_bonus": 6}},
                       side="enemy", hp_current=200, hp_max=200, ac=19,
                       speed={"walk": 40, "fly": 80},
                       position=(5, 0), abilities=_ab())
        st = CombatState(encounter=Encounter(id="t", actors=[caster, dragon]))
        st.content_registry = _registry()

        score_before = defensive_ehp_containment(
            caster, dragon, _DOME_ACTION, st)
        self.assertGreater(score_before, 0.0)

        st.walls = [_dome_at(dragon.position)]
        score_after = defensive_ehp_containment(
            caster, dragon, _DOME_ACTION, st)
        self.assertEqual(score_after, 0.0)

    def test_is_trapped_in_dome_util(self):
        dragon = Actor(id="dragon", name="dragon",
                       template={"id": "t_d", "abilities": _ab()},
                       side="enemy", hp_current=200, hp_max=200, ac=19,
                       speed={"walk": 40}, position=(5, 0), abilities=_ab())
        st = CombatState(encounter=Encounter(id="t", actors=[dragon]))
        self.assertFalse(is_trapped_in_dome(dragon, st))
        st.walls = [_dome_at((5, 0))]
        self.assertTrue(is_trapped_in_dome(dragon, st))


# ============================================================================
# Zone-scores-higher-when-trapped (the microwave synergy signal)
# ============================================================================

class ZoneTrappedBoostTest(unittest.TestCase):
    """A zone on a dome-trapped target is worth more (the target can't walk
    out), so the AI routes the Simulacrum toward zone-casting, not another dome.
    """

    def _setup(self):
        from engine.ai.ehp_scoring import score_candidate
        party = _party()
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        sim = build_simulacrum(wiz)
        dragon = _dragon()
        # Dragon isolated at origin; party far away to avoid friendly fire.
        dragon.position = (0, 0)
        wiz.position = (200, 0)
        sim.position = (200, 10)
        for a in party:
            if a.id != wiz.id:
                a.position = (200, 20)
        actors = [a for a in party if a.id != wiz.id] + [wiz, sim, dragon]
        enc = Encounter(id="t", actors=actors)
        st = CombatState(encounter=enc)
        st.content_registry = _registry()
        return wiz, sim, dragon, st, score_candidate

    def test_cloudkill_scores_higher_when_trapped(self):
        wiz, sim, dragon, st, score = self._setup()
        ck = next(a for a in (sim.template.get("actions") or [])
                  if a.get("id") == "a_cloudkill")
        cand = {"kind": "persistent_aura", "action": ck,
                "target": dragon, "actor": sim,
                "origin_point": dragon.position}

        score_free = score(cand, st)
        st.walls = [_dome_at(dragon.position)]
        score_trapped = score(cand, st)

        self.assertGreater(score_free, 0.0)
        self.assertGreater(score_trapped, score_free)

    def test_sickening_radiance_scores_higher_when_trapped(self):
        wiz, sim, dragon, st, score = self._setup()
        sr = next(a for a in (sim.template.get("actions") or [])
                  if a.get("id") == "a_sickening_radiance")
        cand = {"kind": "persistent_aura", "action": sr,
                "target": dragon, "actor": sim,
                "origin_point": dragon.position}

        score_free = score(cand, st)
        st.walls = [_dome_at(dragon.position)]
        score_trapped = score(cand, st)

        self.assertGreater(score_free, 0.0)
        self.assertGreater(score_trapped, score_free)


if __name__ == "__main__":
    unittest.main()
