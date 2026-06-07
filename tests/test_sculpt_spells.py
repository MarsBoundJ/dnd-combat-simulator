"""Sculpt Spells (Evoker) — end-to-end (#1).

RAW: when an Evoker casts an evocation spell affecting multiple creatures, it
chooses up to (1 + spell level) of them to auto-succeed their save AND take
ZERO damage. The optimal use: shield your own swarmed martials, then drop a
fireball that clears the enemies cleanly.

This covers both halves:
  - Execution: `_forced_save` protects up to (1+level) caster-allies in an
    evocation AoE (auto-succeed, no damage), via _sculpt_protected_count.
  - Scoring: `offensive_ehp_aoe` stops subtracting those allies as friendly
    fire, so an evoker's fireball-through-its-own-martials scores higher.

Run via:
    python -m unittest tests.test_sculpt_spells
"""
from __future__ import annotations

import random
import unittest

from engine.core.state import Actor, Encounter, CombatState
from engine.core.events import EventBus
import engine.primitives as pm
from engine.primitives import _forced_save, _sculpt_protected_count
from engine.ai.ehp_scoring import offensive_ehp_aoe, offensive_ehp_persistent_aura


def _abil():
    return {k: {"score": 12, "save": 1}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _actor(actor_id, side, hp=30, pos=(0, 0), features=None, actions=None):
    tmpl = {"id": f"tpl_{actor_id}", "name": actor_id, "abilities": _abil(),
            "cr": {"proficiency_bonus": 3}, "actions": actions or [],
            "features_known": features or []}
    return Actor(id=actor_id, name=actor_id, template=tmpl, side=side,
                 hp_current=hp, hp_max=hp, ac=14, position=pos, abilities=_abil())


# A fireball-shaped evocation AoE: sphere, DEX save, fire damage.
def _fireball(slot_level=3, school="evocation"):
    return {"id": "a_fireball", "name": "Fireball", "type": "aoe_attack",
            "spell_slot_level": slot_level, "school": school,
            "area": {"shape": "sphere", "radius_ft": 20},
            "pipeline": [{"primitive": "forced_save",
                          "params": {"ability": "dexterity", "dc": 99,
                                     "affected": "all_creatures_in_area",
                                     "on_fail": [{"primitive": "damage",
                                                  "params": {"dice": "8d6",
                                                             "type": "fire"}}],
                                     "on_success": [{"primitive": "damage",
                                                     "params": {"dice": "8d6",
                                                                "type": "fire",
                                                                "multiplier": 0.5}}]}}]}


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


SCULPT = ["f_sculpt_spells"]


class SculptCountTest(unittest.TestCase):

    def _ctx(self, caster, action):
        st = _state([caster])
        st.current_attack = {"actor": caster, "action": action}
        return st

    def test_evoker_evocation_protects_one_plus_level(self):
        evoker = _actor("ev", "pc", features=SCULPT)
        st = self._ctx(evoker, _fireball(slot_level=3))
        self.assertEqual(_sculpt_protected_count(st), 4)   # 1 + 3
        st = self._ctx(evoker, _fireball(slot_level=5))
        self.assertEqual(_sculpt_protected_count(st), 6)

    def test_non_evoker_zero(self):
        plain = _actor("w", "pc", features=[])
        st = self._ctx(plain, _fireball(slot_level=3))
        self.assertEqual(_sculpt_protected_count(st), 0)

    def test_non_evocation_zero(self):
        evoker = _actor("ev", "pc", features=SCULPT)
        st = self._ctx(evoker, _fireball(slot_level=3, school="conjuration"))
        self.assertEqual(_sculpt_protected_count(st), 0)


class SculptExecutionTest(unittest.TestCase):
    """The evoker's fireball spares its allies in the blast, hits the enemies."""

    def _run(self, caster_features):
        evoker = _actor("ev", "pc", hp=40, pos=(0, 0),
                        features=caster_features)
        ally = _actor("ally", "pc", hp=40, pos=(1, 0))
        e1 = _actor("e1", "enemy", hp=40, pos=(1, 0))
        e2 = _actor("e2", "enemy", hp=40, pos=(0, 1))
        st = _state([evoker, ally, e1, e2])
        action = _fireball(slot_level=3)
        st.current_attack = {"actor": evoker, "target": e1, "action": action,
                             "area_origin": (0, 0)}
        pm.set_rng(random.Random(1))
        _forced_save(action["pipeline"][0]["params"], st, EventBus())
        return evoker, ally, e1, e2, st

    def test_sculpt_ally_takes_zero_enemies_burn(self):
        evoker, ally, e1, e2, st = self._run(SCULPT)
        self.assertEqual(ally.hp_current, ally.hp_max,
                         "Sculpted ally must take ZERO damage")
        self.assertLess(e1.hp_current, e1.hp_max, "enemy should burn")
        self.assertLess(e2.hp_current, e2.hp_max, "enemy should burn")
        # The evoker (a caster-ally, also in the blast) is protected too.
        self.assertEqual(evoker.hp_current, evoker.hp_max)
        sculpt_events = [x for x in st.event_log
                         if x.get("sculpt_spells")]
        self.assertTrue(sculpt_events)

    def test_without_sculpt_ally_burns(self):
        evoker, ally, e1, e2, st = self._run([])   # no Sculpt Spells
        self.assertLess(ally.hp_current, ally.hp_max,
                        "without Sculpt Spells the ally takes friendly fire")


class SculptScoringTest(unittest.TestCase):
    """offensive_ehp_aoe stops subtracting sculpt-protected allies."""

    def _setup(self, caster_features):
        evoker = _actor("ev", "pc", hp=40, pos=(0, 0), features=caster_features)
        ally = _actor("ally", "pc", hp=40, pos=(0, 0))
        e1 = _actor("e1", "enemy", hp=40, pos=(0, 0))
        e2 = _actor("e2", "enemy", hp=40, pos=(0, 0))
        st = _state([evoker, ally, e1, e2])
        st.content_registry = None
        return evoker, st, _fireball(slot_level=3)

    def test_evoker_scores_higher_than_plain_caster(self):
        ev, st_ev, action = self._setup(SCULPT)
        plain, st_pl, action2 = self._setup([])
        score_ev = offensive_ehp_aoe(ev, (0, 0), action, st_ev)
        score_plain = offensive_ehp_aoe(plain, (0, 0), action2, st_pl)
        # Same blast, but the evoker doesn't pay the ally's friendly fire.
        self.assertGreater(score_ev, score_plain)


def _aura(affected="all_creatures", school="conjuration", slot_level=5):
    """A Cloudkill-shaped damaging persistent aura (sphere, CON save)."""
    return {"id": "a_cloudkill", "name": "Cloudkill", "type": "persistent_aura",
            "spell_slot_level": slot_level, "school": school,
            "pipeline": [{"primitive": "persistent_aura",
                          "params": {"shape": "sphere", "radius_ft": 20,
                                     "anchor": "point", "affected": affected,
                                     "ability": "constitution", "dc": 16,
                                     "on_fail": [{"primitive": "damage",
                                                  "params": {"dice": "5d8",
                                                             "type": "poison"}}]}}]}


class AuraFriendlyFireTest(unittest.TestCase):
    """A damaging `affected: all_creatures` aura (Cloudkill) must pay for the
    allies it gasses; an `affected: enemies` aura (Spirit Guardians) must not;
    an evoker's EVOCATION aura sculpts allies out."""

    def _setup(self):
        caster = _actor("ev", "pc", hp=40, pos=(0, 0))
        ally = _actor("ally", "pc", hp=40, pos=(0, 0))
        e1 = _actor("e1", "enemy", hp=60, pos=(0, 0))
        e2 = _actor("e2", "enemy", hp=60, pos=(0, 0))
        return caster, ally, e1, e2

    def test_all_creatures_aura_subtracts_ally_friendly_fire(self):
        caster, ally, e1, e2 = self._setup()
        st_no = _state([caster, e1, e2])           # no ally in blast
        st_ff = _state([caster, ally, e1, e2])     # ally in blast
        action = _aura(affected="all_creatures")
        score_no = offensive_ehp_persistent_aura(caster, action, st_no, (0, 0))
        score_ff = offensive_ehp_persistent_aura(caster, action, st_ff, (0, 0))
        self.assertLess(score_ff, score_no,
                        "ally in an all_creatures zone should cost friendly fire")

    def test_enemies_only_aura_no_friendly_fire(self):
        caster, ally, e1, e2 = self._setup()
        st_no = _state([caster, e1, e2])
        st_ally = _state([caster, ally, e1, e2])
        action = _aura(affected="enemies")
        self.assertAlmostEqual(
            offensive_ehp_persistent_aura(caster, action, st_no, (0, 0)),
            offensive_ehp_persistent_aura(caster, action, st_ally, (0, 0)),
            msg="Spirit-Guardians-style enemies-only aura hits no allies")

    def test_evoker_evocation_aura_sculpts_ally_out(self):
        ev = _actor("ev", "pc", hp=40, pos=(0, 0), features=SCULPT)
        ally = _actor("ally", "pc", hp=40, pos=(0, 0))
        e1 = _actor("e1", "enemy", hp=60, pos=(0, 0))
        plain = _actor("pl", "pc", hp=40, pos=(0, 0))   # no Sculpt
        ally2 = _actor("ally2", "pc", hp=40, pos=(0, 0))
        e2 = _actor("e2", "enemy", hp=60, pos=(0, 0))
        action = _aura(affected="all_creatures", school="evocation")
        st_ev = _state([ev, ally, e1])
        st_pl = _state([plain, ally2, e2])
        # The evoker sculpts the ally out → no friendly-fire penalty → higher.
        self.assertGreater(
            offensive_ehp_persistent_aura(ev, action, st_ev, (0, 0)),
            offensive_ehp_persistent_aura(plain, action, st_pl, (0, 0)))


if __name__ == "__main__":
    unittest.main()
