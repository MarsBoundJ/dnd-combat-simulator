"""Concentration→summon lifecycle (Lever B Stage 2a).

A concentration summon spell (Bigby's Hand, Animate Objects) creates allied
combatants that exist ONLY while the caster concentrates. When concentration
ends — broken by damage, dropped voluntarily, incapacitation — the summons
must vanish from the encounter roster AND the turn order.

This is the engine foundation under the RAW-faithful full-summon: the
`_summon` primitive stamps each creature with `summon_concentration =
{caster_id, action_id}` when the executing action is a concentration spell,
and `end_concentration` scrubs exactly those creatures (mirroring the
walls / persistent_auras scrub).

Run via:
    python -m unittest tests.test_summon_concentration
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core import summoning
from engine.core.concentration import apply_concentration, end_concentration
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import _summon

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


def _caster(actor_id="wiz", pos=(0, 0)):
    return Actor(id=actor_id, name=actor_id,
                  template={"id": "pc", "name": actor_id, "abilities": _abil(),
                             "actions": [], "cr": {"proficiency_bonus": 5}},
                  side="pc", hp_current=60, hp_max=60, ac=15,
                  speed={"walk": 30}, position=pos, abilities=_abil())


def _foe(actor_id="foe", pos=(6, 0)):
    return Actor(id=actor_id, name=actor_id,
                  template={"id": "pc", "name": actor_id, "abilities": _abil(),
                             "actions": [], "cr": {"proficiency_bonus": 3}},
                  side="enemy", hp_current=80, hp_max=80, ac=15,
                  speed={"walk": 30}, position=pos, abilities=_abil())


def _state(actors):
    enc = Encounter(id="t", actors=list(actors))
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


# A concentration spell that summons (the Bigby's Hand / Animate Objects shape).
_CONC_SUMMON = {"id": "a_test_summon_conc", "concentration": True}
# A non-concentration / permanent summon for the negative case.
_PERM_SUMMON = {"id": "a_test_summon_perm", "concentration": False}


class SummonConcentrationLifecycleTest(unittest.TestCase):

    def _summon_via(self, caster, action, st, count=2):
        """Drive the _summon primitive as if `action` were being cast."""
        st.current_attack = {"actor": caster, "action": action}
        _summon({"monster": "m_specter", "count": count}, st, EventBus())

    def test_concentration_summon_is_stamped(self):
        c, f = _caster(), _foe()
        st = _state([c, f])
        apply_concentration(c, _CONC_SUMMON, st)
        self._summon_via(c, _CONC_SUMMON, st, count=2)
        sums = [a for a in st.encounter.actors if a.summoned_by == "wiz"]
        self.assertEqual(len(sums), 2)
        for s in sums:
            self.assertEqual(s.summon_concentration,
                             {"caster_id": "wiz", "action_id": "a_test_summon_conc"})
            self.assertIn(s.id, st.turn_order)

    def test_end_concentration_dismisses_summons(self):
        c, f = _caster(), _foe()
        st = _state([c, f])
        apply_concentration(c, _CONC_SUMMON, st)
        self._summon_via(c, _CONC_SUMMON, st, count=2)
        sum_ids = [a.id for a in st.encounter.actors if a.summoned_by == "wiz"]
        self.assertEqual(len(sum_ids), 2)

        removed = end_concentration(c, st, reason="dropped")
        # Both summons gone from roster AND turn order.
        self.assertGreaterEqual(removed, 2)
        roster_ids = {a.id for a in st.encounter.actors}
        for sid in sum_ids:
            self.assertNotIn(sid, roster_ids)
            self.assertNotIn(sid, st.turn_order)
        # Caster + foe untouched.
        self.assertIn("wiz", roster_ids)
        self.assertIn("foe", roster_ids)

    def test_permanent_summon_survives_other_concentration_ending(self):
        """A non-concentration summon is NOT scrubbed when an unrelated
        concentration ends."""
        c, f = _caster(), _foe()
        st = _state([c, f])
        # Permanent summon (no concentration stamp).
        self._summon_via(c, _PERM_SUMMON, st, count=1)
        perm_ids = [a.id for a in st.encounter.actors if a.summoned_by == "wiz"]
        self.assertEqual(len(perm_ids), 1)
        for s in st.encounter.actors:
            if s.summoned_by == "wiz":
                self.assertIsNone(s.summon_concentration)

        # Now concentrate on something else and end it — the permanent
        # summon must remain.
        apply_concentration(c, _CONC_SUMMON, st)
        end_concentration(c, st, reason="dropped")
        roster_ids = {a.id for a in st.encounter.actors}
        for pid in perm_ids:
            self.assertIn(pid, roster_ids)
            self.assertIn(pid, st.turn_order)

    def test_only_matching_casters_summons_dismissed(self):
        """Two casters each with concentration summons; ending one caster's
        concentration leaves the other's summons alive."""
        c1 = _caster("wiz1", pos=(0, 0))
        c2 = _caster("wiz2", pos=(2, 0))
        f = _foe()
        st = _state([c1, c2, f])
        apply_concentration(c1, _CONC_SUMMON, st)
        apply_concentration(c2, _CONC_SUMMON, st)
        self._summon_via(c1, _CONC_SUMMON, st, count=1)
        self._summon_via(c2, _CONC_SUMMON, st, count=1)
        c1_sums = [a.id for a in st.encounter.actors if a.summoned_by == "wiz1"]
        c2_sums = [a.id for a in st.encounter.actors if a.summoned_by == "wiz2"]

        end_concentration(c1, st, reason="dropped")
        roster_ids = {a.id for a in st.encounter.actors}
        for sid in c1_sums:
            self.assertNotIn(sid, roster_ids)      # wiz1's summon gone
        for sid in c2_sums:
            self.assertIn(sid, roster_ids)         # wiz2's summon alive


if __name__ == "__main__":
    unittest.main()
