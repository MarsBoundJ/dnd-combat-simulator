"""Concentration-aware candidate filter (grind diagnosis #70).

While an actor is ALREADY concentrating, `generate_candidates` suppresses
every concentration-spell candidate — you can hold only one concentration
effect, so casting another either re-applies the same effect (waste) or drops
a working one (churn). The grind trace showed casters thrashing control spells
every turn, contributing no damage and losing a Moderate fight; this filter
forces them to keep concentration and fall through to damage.

Run via:
    python -m unittest tests.test_concentration_candidate_filter
"""
from __future__ import annotations

import unittest

from engine.core.concentration import apply_concentration
from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, Encounter, CombatState


def _actor(actor_id, side="pc", pos=(0, 0), actions=None):
    ab = {k: {"score": 14, "save": 2} for k in
          ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id=actor_id, name=actor_id,
                 template={"id": f"t_{actor_id}", "abilities": ab,
                           "actions": actions or [],
                           "cr": {"proficiency_bonus": 3}},
                 side=side, hp_current=40, hp_max=40, ac=14,
                 position=pos, abilities=ab,
                 spell_slots={1: 4, 2: 3, 3: 3})


# A concentration control spell and a non-concentration damage cantrip.
_HYPNOTIC = {"id": "a_hypnotic_pattern", "name": "Hypnotic Pattern",
             "type": "hard_control", "slot": "action",
             "concentration": True, "spell_slot_level": 3,
             "range_ft": 120,
             "pipeline": [{"primitive": "forced_save",
                           "params": {"ability": "wisdom", "dc": 15,
                                      "on_fail": []}}]}
_HOLD = {"id": "a_hold_monster", "name": "Hold Monster", "type": "hard_control",
         "slot": "action", "concentration": True, "spell_slot_level": 3,
         "range_ft": 90,
         "pipeline": [{"primitive": "forced_save",
                       "params": {"ability": "wisdom", "dc": 15,
                                  "on_fail": []}}]}
_FIRE_BOLT = {"id": "a_fire_bolt", "name": "Fire Bolt", "type": "weapon_attack",
              "slot": "action", "spell_slot_level": 0, "range_ft": 120,
              "pipeline": [{"primitive": "attack_roll",
                            "params": {"kind": "ranged", "bonus": 7,
                                       "range_ft": 120}},
                           {"primitive": "damage",
                            "params": {"dice": "2d10", "modifier": 0,
                                       "type": "fire"},
                            "when": {"condition":
                                     "combat.attack_state == hit"}}]}


def _state(actors):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


def _candidate_action_ids(actor, state):
    return {c["action"].get("id")
            for c in generate_candidates(actor, state, slot="action")
            if c.get("action")}


class ConcentrationCandidateFilterTest(unittest.TestCase):

    def test_not_concentrating_allows_concentration_spells(self):
        caster = _actor("c", actions=[_HYPNOTIC, _HOLD, _FIRE_BOLT])
        foe = _actor("foe", side="enemy", pos=(5, 0))
        ids = _candidate_action_ids(caster, _state([caster, foe]))
        # First cast: concentration spells available.
        self.assertIn("a_hypnotic_pattern", ids)
        self.assertIn("a_hold_monster", ids)
        self.assertIn("a_fire_bolt", ids)

    def test_concentrating_suppresses_all_concentration_spells(self):
        caster = _actor("c", actions=[_HYPNOTIC, _HOLD, _FIRE_BOLT])
        foe = _actor("foe", side="enemy", pos=(5, 0))
        state = _state([caster, foe])
        apply_concentration(caster, _HYPNOTIC, state)
        ids = _candidate_action_ids(caster, state)
        # Re-cast of the SAME spell suppressed (narrow case)...
        self.assertNotIn("a_hypnotic_pattern", ids)
        # ...and switching to a DIFFERENT concentration spell suppressed
        # (the churn case that was the dominant grind bug).
        self.assertNotIn("a_hold_monster", ids)
        # Non-concentration damage still available -> caster falls through to
        # damage instead of thrashing control.
        self.assertIn("a_fire_bolt", ids)

    def test_non_concentration_actions_unaffected(self):
        # A caster concentrating still keeps every non-concentration option.
        caster = _actor("c", actions=[_HYPNOTIC, _FIRE_BOLT])
        foe = _actor("foe", side="enemy", pos=(5, 0))
        state = _state([caster, foe])
        apply_concentration(caster, _HYPNOTIC, state)
        ids = _candidate_action_ids(caster, state)
        self.assertEqual(ids, {"a_fire_bolt"})


if __name__ == "__main__":
    unittest.main()
