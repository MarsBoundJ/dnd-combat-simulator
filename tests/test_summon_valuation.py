"""Summon-spell valuation (Lever B Stage 2b).

Stage 2a gave concentration summons a lifecycle (they vanish when the caster's
concentration ends). But the AI never CAST them — a summon action scored 0 eHP
(unknown candidate kind) and lost to every cantrip. This is the gating piece:

  - `offensive_ehp_summon` values a summon at per_creature_DPR × creatable
    count × EXPECTED_SUMMON_ROUNDS (the recurring damage stream the summoned
    creatures deal — the action-economy doubling), capped at enemy HP and
    capacity-aware.
  - `score_candidate` dispatches the `summon` kind BEFORE the enemy-target
    guard (summons target self / no one).
  - `generate_candidates` emits one summon candidate per turn, and the
    existing concentration filter suppresses it while the caster already
    concentrates.

Run via:
    python -m unittest tests.test_summon_valuation
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.ai.ehp_scoring import (
    offensive_ehp_summon, score_candidate, EXPECTED_SUMMON_ROUNDS,
)
from engine.ai.defensive_ehp import estimate_dpr
from engine.cli import _build_actor
from engine.core.concentration import apply_concentration
from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content

REPO_ROOT = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO_ROOT / "schema" / "content",
                                   validate=True,
                                   schema_root=REPO_ROOT / "schema" / "definitions")
    return _REGISTRY


def _abil():
    return {k: {"score": 12, "save": 1}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


# A synthetic summon action — the shape Bigby's Hand / Animate Objects will
# carry in 2c/2d: type=summon, a `summon` primitive step naming a monster.
def _summon_action(monster="m_specter", count=1, max_total=None,
                    concentration=False, action_id="a_test_summon"):
    params = {"monster": monster, "count": count}
    if max_total is not None:
        params["max_total"] = max_total
    return {
        "id": action_id,
        "name": "Test Summon",
        "type": "summon",
        "concentration": concentration,
        "pipeline": [{"primitive": "summon", "params": params}],
    }


def _caster(actor_id="wiz", pos=(0, 0), actions=None):
    return Actor(id=actor_id, name=actor_id,
                  template={"id": "pc", "name": actor_id, "abilities": _abil(),
                             "actions": actions or [],
                             "cr": {"proficiency_bonus": 5}},
                  side="pc", hp_current=60, hp_max=60, ac=15,
                  speed={"walk": 30}, position=pos, abilities=_abil())


def _foe(actor_id="foe", pos=(2, 0), hp=80):
    return Actor(id=actor_id, name=actor_id,
                  template={"id": "m_fire_giant", "name": actor_id,
                             "abilities": _abil(),
                             "actions": [], "cr": {"proficiency_bonus": 3}},
                  side="enemy", hp_current=hp, hp_max=hp, ac=15,
                  speed={"walk": 30}, position=pos, abilities=_abil())


def _state(actors):
    enc = Encounter(id="t", actors=list(actors))
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


class SummonValuationTest(unittest.TestCase):

    def _probe_dpr(self, monster="m_specter", pos=(0, 0)):
        probe = _build_actor(
            {"template_ref": {"entity_type": "monster", "id": monster},
             "instance_id": "__probe__", "position": list(pos)}, _registry())
        return estimate_dpr(probe)

    def test_summon_value_is_dpr_times_rounds(self):
        c, f = _caster(), _foe(hp=500)        # plenty of enemy HP, no cap
        st = _state([c, f])
        action = _summon_action(count=1)
        val = offensive_ehp_summon(c, action, st)
        expected = self._probe_dpr() * 1 * EXPECTED_SUMMON_ROUNDS
        self.assertGreater(val, 0.0)
        self.assertAlmostEqual(val, expected, places=4)

    def test_count_scales_value(self):
        c, f = _caster(), _foe(hp=5000)
        st = _state([c, f])
        one = offensive_ehp_summon(c, _summon_action(count=1), st)
        three = offensive_ehp_summon(c, _summon_action(count=3), st)
        self.assertAlmostEqual(three, one * 3, places=4)

    def test_overkill_capped_at_enemy_hp(self):
        c, f = _caster(), _foe(hp=5)          # almost-dead enemy
        st = _state([c, f])
        val = offensive_ehp_summon(c, _summon_action(count=5), st)
        self.assertLessEqual(val, 5.0 + 1e-6)

    def test_capacity_aware_zero_at_cap(self):
        c, f = _caster(), _foe(hp=500)
        st = _state([c, f])
        # Pre-summon to the cap, then a fresh summon at the same cap is 0.
        from engine.core import summoning
        summoning.summon(c, "m_specter", st, count=2, max_total=2)
        val = offensive_ehp_summon(
            c, _summon_action(count=2, max_total=2), st)
        self.assertEqual(val, 0.0)

    def test_no_registry_returns_zero(self):
        c, f = _caster(), _foe()
        st = _state([c, f])
        st.content_registry = None
        self.assertEqual(offensive_ehp_summon(c, _summon_action(), st), 0.0)

    def test_score_candidate_dispatches_summon(self):
        c, f = _caster(), _foe(hp=500)
        st = _state([c, f])
        cand = {"kind": "summon", "action": _summon_action(),
                "target": c, "actor": c}      # target=self, no enemy
        score = score_candidate(cand, st)
        self.assertGreater(score, 0.0)

    def test_generate_candidates_emits_summon(self):
        action = _summon_action(concentration=True)
        c = _caster(actions=[action])
        f = _foe()
        st = _state([c, f])
        kinds = [x for x in generate_candidates(c, st)
                 if x.get("kind") == "summon"]
        self.assertEqual(len(kinds), 1)
        self.assertIs(kinds[0]["action"], action)

    def test_concentration_filter_suppresses_summon_while_concentrating(self):
        action = _summon_action(concentration=True,
                                 action_id="a_test_summon_conc")
        c = _caster(actions=[action])
        f = _foe()
        st = _state([c, f])
        # Already concentrating on something → conc summon suppressed.
        apply_concentration(
            c, {"id": "a_other_conc", "concentration": True}, st)
        summon_cands = [x for x in generate_candidates(c, st)
                        if x.get("kind") == "summon"]
        self.assertEqual(summon_cands, [])


if __name__ == "__main__":
    unittest.main()
