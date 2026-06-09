"""Altitude model — Stage 2: flier altitude + aerial kiting.

A dial-gated flier hovers out of grounded-melee reach when it has working
airborne offense (breath/ranged) and there are melee enemies to deny; otherwise
it grounds (swoops). Built on Stage 1's Chebyshev-3D distance, so hovering
auto-disables melee in both directions.

Run via:
    python -m unittest tests.test_altitude_kiting
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

from engine import primitives as pm
from engine.ai.altitude import (
    choose_flier_elevation, safe_hover_elevation, best_airborne_offense_ehp,
    has_fly, KITE_MIN_DIAL,
)
from engine.core.optimization_dial import set_dial
from engine.core.runner import EncounterRunner
from engine.core.state import Actor, Encounter, CombatState
from engine.loader import load_content

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _ab():
    return {k: {"score": 12, "save": 1}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


_GREATSWORD = {"id": "a_gs", "type": "weapon_attack",
               "pipeline": [{"primitive": "attack_roll",
                             "params": {"kind": "melee", "reach_ft": 5}}]}


def _mk(actor_id, side, pos, speed, actions=None, elev=0):
    a = Actor(id=actor_id, name=actor_id,
              template={"id": f"t_{actor_id}", "abilities": _ab(),
                        "actions": actions or [],
                        "cr": {"proficiency_bonus": 4}},
              side=side, hp_current=80, hp_max=80, ac=15,
              speed=speed, position=pos, abilities=_ab())
    a.elevation = elev
    return a


def _state(actors, *, enemy_dial=5):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.content_registry = _registry()
    set_dial(st, "enemy", enemy_dial)
    set_dial(st, "pc", 5)
    return st


class HoverElevationTest(unittest.TestCase):
    def test_clears_tallest_grounded_melee_reach(self):
        flier = _mk("f", "enemy", (0, 0), {"walk": 40, "fly": 80})
        melee5 = _mk("m", "pc", (1, 0), {"walk": 30}, [_GREATSWORD])
        st = _state([flier, melee5])
        # max grounded reach 5 → hover 10 (strictly clears 5 in Chebyshev-3D)
        self.assertEqual(safe_hover_elevation(flier, st), 10)

    def test_zero_when_no_grounded_melee(self):
        flier = _mk("f", "enemy", (0, 0), {"walk": 40, "fly": 80})
        # only a flying enemy → nothing grounded to deny
        other = _mk("g", "pc", (1, 0), {"walk": 30, "fly": 60}, [_GREATSWORD])
        st = _state([flier, other])
        self.assertEqual(safe_hover_elevation(flier, st), 0)


def _reg_dragon_and_party():
    """A real Adult Red Dragon (breath scores real eHP) + the standard party,
    placed adjacent so the breath catches grounded PCs."""
    from sims.adventuring_day import _build_party, _build_monsters
    party = _build_party(_registry())
    dragon = _build_monsters(_registry(), [("m_adult_red_dragon", 1)])[0]
    dragon.position = (1, 0)
    return dragon, party


class AirborneOffenseTest(unittest.TestCase):
    def test_breath_scores_from_hover(self):
        dragon, party = _reg_dragon_and_party()
        st = _state([dragon, *party])
        self.assertGreater(best_airborne_offense_ehp(dragon, 10, st), 0)

    def test_melee_only_scores_zero_from_hover(self):
        biter = _mk("b", "enemy", (0, 0), {"walk": 40, "fly": 80}, [_GREATSWORD])
        p1 = _mk("p1", "pc", (1, 0), {"walk": 30}, [_GREATSWORD])
        st = _state([biter, p1])
        # 5-ft reach can't touch a grounded foe from 10 ft up
        self.assertEqual(best_airborne_offense_ehp(biter, 10, st), 0.0)


class ChooseElevationTest(unittest.TestCase):
    def _enc(self, monster, **kw):
        from sims.adventuring_day import _build_party, _build_monsters
        party = _build_party(_registry())
        mons = _build_monsters(_registry(), [(monster, 1)])
        return _state(party + mons, **kw), mons[0]

    def test_dragon_with_breath_kites(self):
        st, d = self._enc("m_adult_red_dragon")
        self.assertGreater(choose_flier_elevation(d, st), 0)

    def test_dragon_kites_when_breath_spent_but_has_ranged_spells(self):
        # 2024 stat block: at-will Scorching Ray keeps dragon airborne
        st, d = self._enc("m_adult_red_dragon")
        d.recharge_spent.add("a_fire_breath")
        self.assertGreater(choose_flier_elevation(d, st), 0)

    def test_wyvern_grounds(self):
        st, w = self._enc("m_wyvern")
        self.assertEqual(choose_flier_elevation(w, st), 0)

    def test_naive_dial_grounds(self):
        st, d = self._enc("m_adult_red_dragon", enemy_dial=KITE_MIN_DIAL - 1)
        self.assertEqual(choose_flier_elevation(d, st), 0)

    def test_non_flier_grounds(self):
        from sims.adventuring_day import _build_monsters
        giant = _build_monsters(_registry(), [("m_fire_giant", 1)])[0]
        st = _state([giant,
                     _mk("p1", "pc", (1, 0), {"walk": 30}, [_GREATSWORD])])
        self.assertFalse(has_fly(giant))
        self.assertEqual(choose_flier_elevation(giant, st), 0)


class RunnerHookTest(unittest.TestCase):
    def _runner_state(self, actors, **kw):
        enc = Encounter(id="t", actors=actors)
        pm.set_rng(random.Random(1))
        runner = EncounterRunner.new(enc, seed=1, content_registry=_registry())
        pm.set_rng(runner.rng)
        st = CombatState(encounter=enc)
        st.turn_order = [a.id for a in actors]
        st.content_registry = _registry()
        set_dial(st, "enemy", kw.get("enemy_dial", 5))
        set_dial(st, "pc", 5)
        return runner, st

    def test_hook_lifts_kiter_and_logs(self):
        dragon, party = _reg_dragon_and_party()
        runner, st = self._runner_state([dragon, *party])
        self.assertTrue(runner._maybe_choose_elevation(dragon, st))
        self.assertGreater(dragon.elevation, 0)
        self.assertTrue(any(e.get("event") == "elevation_changed"
                            and e.get("reason") == "kite" for e in st.event_log))

    def test_hook_noop_for_grounded_nonflier(self):
        giant = _mk("g", "enemy", (0, 0), {"walk": 30}, [_GREATSWORD])
        p1 = _mk("p1", "pc", (1, 0), {"walk": 30}, [_GREATSWORD])
        runner, st = self._runner_state([giant, p1])
        self.assertFalse(runner._maybe_choose_elevation(giant, st))
        self.assertEqual(giant.elevation, 0)


if __name__ == "__main__":
    unittest.main()
