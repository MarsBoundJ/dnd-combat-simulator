"""Recharge ability system — engine.core.recharge + pipeline/runner wiring.

Layers:
  1. parse_die_range: "5-6"/"6-6" → (lo,hi); rest/daily/malformed → None
  2. is_available: ungated always True; gated False once spent
  3. mark_spent: adds the action id; no-op without recharge/id
  4. roll_recharges_at_turn_start: restores on an in-range d6, keeps spent
     out of range, and never restores a rest/daily ability mid-combat
  5. Candidate filter: a spent recharge ability drops out of the pool and
     returns once recharged (via generate_candidates)
"""
from __future__ import annotations

import unittest

from pathlib import Path

from engine.core import recharge
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


def _actor_from(mid, *, side="enemy", pos=(0, 0)):
    m = _registry().get("monster", mid)
    hp = m["combat"]["hit_points"]["average"]
    return Actor(id=mid, name=m["name"], template=m, side=side,
                  hp_current=max(hp, 1), hp_max=max(hp, 1),
                  ac=m["combat"]["armor_class"],
                  speed={"walk": m["combat"]["speed"].get("walk", 30)},
                  position=pos, abilities=m["abilities"],
                  size=m.get("size", "medium"),
                  creature_type=m.get("creature_type", "beast"))


class _FakeRng:
    """Deterministic d6: randint(...) always returns `value`."""
    def __init__(self, value):
        self.value = value

    def randint(self, lo, hi):
        return self.value


def _abil():
    return {k: {"score": 10, "save": 0}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _breath_action(recharge_spec="5-6"):
    # A breath-weapon-shaped save_attack carrying a recharge gate.
    return {"id": "a_breath", "name": "Fire Breath", "type": "save_attack",
            "recharge": recharge_spec, "range_ft": 30,
            "pipeline": []}


def _bite_action():
    return {"id": "a_bite", "name": "Bite", "type": "weapon_attack",
            "pipeline": [{"primitive": "attack_roll",
                            "params": {"kind": "melee", "bonus": 4,
                                        "reach_ft": 5}}]}


def _monster(recharge_spec="5-6", pos=(0, 0)):
    ab = _abil()
    return Actor(id="drake", name="drake",
                  template={"id": "m_drake", "name": "Drake", "abilities": ab,
                             "actions": [_breath_action(recharge_spec),
                                          _bite_action()],
                             "cr": {"proficiency_bonus": 2}},
                  side="enemy", hp_current=30, hp_max=30, ac=13,
                  speed={"walk": 30}, position=pos, abilities=ab,
                  size="medium", creature_type="dragon")


def _target(pos=(1, 0)):   # adjacent (1 grid square = 5 ft) → in Bite reach
    ab = _abil()
    return Actor(id="hero", name="hero",
                  template={"id": "pc", "name": "Hero", "abilities": ab,
                             "actions": [], "cr": {"proficiency_bonus": 2}},
                  side="pc", hp_current=25, hp_max=25, ac=14,
                  speed={"walk": 30}, position=pos, abilities=ab,
                  size="medium", creature_type="humanoid")


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


# ---------------------------------------------------------------------------
# Layer 1: parse
# ---------------------------------------------------------------------------

class ParseTest(unittest.TestCase):

    def test_die_ranges(self):
        self.assertEqual(recharge.parse_die_range("5-6"), (5, 6))
        self.assertEqual(recharge.parse_die_range("6-6"), (6, 6))
        self.assertEqual(recharge.parse_die_range("1-6"), (1, 6))

    def test_reversed_range_normalized(self):
        self.assertEqual(recharge.parse_die_range("6-5"), (5, 6))

    def test_non_die_specs_are_none(self):
        for spec in ("short_rest", "long_rest", "daily:3", "", None,
                      "garbage", "7-8"):
            self.assertIsNone(recharge.parse_die_range(spec), spec)


# ---------------------------------------------------------------------------
# Layer 2 + 3: availability + mark_spent
# ---------------------------------------------------------------------------

class AvailabilityTest(unittest.TestCase):

    def test_ungated_action_always_available(self):
        m = _monster()
        self.assertTrue(recharge.is_available(m, _bite_action()))

    def test_recharge_action_available_until_spent(self):
        m = _monster()
        breath = _breath_action()
        self.assertTrue(recharge.is_available(m, breath))
        recharge.mark_spent(m, breath, _state([m]))
        self.assertFalse(recharge.is_available(m, breath))
        self.assertIn("a_breath", m.recharge_spent)

    def test_mark_spent_noop_for_ungated(self):
        m = _monster()
        recharge.mark_spent(m, _bite_action(), _state([m]))
        self.assertEqual(m.recharge_spent, set())


# ---------------------------------------------------------------------------
# Layer 4: turn-start roll
# ---------------------------------------------------------------------------

class TurnStartRollTest(unittest.TestCase):

    def test_in_range_roll_recharges(self):
        m = _monster("5-6")
        st = _state([m])
        m.recharge_spent.add("a_breath")
        recharge.roll_recharges_at_turn_start(m, st, _FakeRng(5))
        self.assertNotIn("a_breath", m.recharge_spent)

    def test_out_of_range_roll_stays_spent(self):
        m = _monster("5-6")
        st = _state([m])
        m.recharge_spent.add("a_breath")
        recharge.roll_recharges_at_turn_start(m, st, _FakeRng(4))
        self.assertIn("a_breath", m.recharge_spent)

    def test_recharge_6_only_on_a_6(self):
        for roll, expected_spent in ((5, True), (6, False)):
            m = _monster("6-6")
            m.recharge_spent.add("a_breath")
            recharge.roll_recharges_at_turn_start(m, _state([m]),
                                                    _FakeRng(roll))
            self.assertEqual("a_breath" in m.recharge_spent, expected_spent,
                              f"roll {roll}")

    def test_rest_based_never_recharges_midcombat(self):
        m = _monster("short_rest")
        m.recharge_spent.add("a_breath")
        # Even a "6" can't recharge a rest-gated ability in an encounter.
        recharge.roll_recharges_at_turn_start(m, _state([m]), _FakeRng(6))
        self.assertIn("a_breath", m.recharge_spent)

    def test_roll_logs_event(self):
        m = _monster("5-6")
        st = _state([m])
        m.recharge_spent.add("a_breath")
        recharge.roll_recharges_at_turn_start(m, st, _FakeRng(6))
        rolls = [e for e in st.event_log if e["event"] == "recharge_roll"]
        self.assertEqual(len(rolls), 1)
        self.assertEqual(rolls[0]["roll"], 6)
        self.assertTrue(rolls[0]["recharged"])


# ---------------------------------------------------------------------------
# Layer 5: candidate filter integration
# ---------------------------------------------------------------------------

class CandidateFilterTest(unittest.TestCase):

    def _breath_in_candidates(self, monster, state):
        cands = generate_candidates(monster, state, slot="action")
        return any(c["action"].get("id") == "a_breath" for c in cands)

    def test_breath_present_when_available(self):
        m = _monster("5-6")
        st = _state([m, _target()])
        self.assertTrue(self._breath_in_candidates(m, st))

    def test_breath_filtered_when_spent(self):
        m = _monster("5-6")
        st = _state([m, _target()])
        m.recharge_spent.add("a_breath")
        self.assertFalse(self._breath_in_candidates(m, st))
        # The non-recharge Bite is still a candidate.
        cands = generate_candidates(m, st, slot="action")
        self.assertTrue(any(c["action"].get("id") == "a_bite"
                              for c in cands))

    def test_breath_returns_after_recharge(self):
        m = _monster("5-6")
        st = _state([m, _target()])
        m.recharge_spent.add("a_breath")
        self.assertFalse(self._breath_in_candidates(m, st))
        recharge.roll_recharges_at_turn_start(m, st, _FakeRng(6))
        self.assertTrue(self._breath_in_candidates(m, st))


# ---------------------------------------------------------------------------
# Layer 6: real loaded monsters carry working recharge gates
# ---------------------------------------------------------------------------

class RealMonsterTest(unittest.TestCase):
    """The four partial-defers completed alongside the recharge system."""

    def _has(self, actor, state, action_id):
        cands = generate_candidates(actor, state, slot="action")
        return any(c["action"].get("id") == action_id for c in cands)

    def test_giant_ape_boulder_toss_gated_end_to_end(self):
        # The breath-weapon-shape proof: aoe_attack + Recharge 6.
        ape = _actor_from("m_giant_ape", pos=(0, 0))
        hero = _actor_from("m_wolf", side="pc", pos=(2, 0))  # any enemy
        st = _state([ape, hero])
        self.assertTrue(self._has(ape, st, "a_boulder_toss"))
        recharge.mark_spent(ape, {"id": "a_boulder_toss", "recharge": "6-6"}, st)
        self.assertFalse(self._has(ape, st, "a_boulder_toss"))
        # A 6 recharges it; a 5 would not.
        recharge.roll_recharges_at_turn_start(ape, st, _FakeRng(6))
        self.assertTrue(self._has(ape, st, "a_boulder_toss"))

    def test_giant_spider_web_is_recharge_gated(self):
        spider = _registry().get("monster", "m_giant_spider")
        web = next(a for a in spider["actions"] if a["id"] == "a_web")
        self.assertEqual(web["recharge"], "5-6")
        self.assertEqual(web["type"], "hard_control")

    def test_recharge_specs_parse_for_all_four(self):
        cases = [("m_giant_spider", "a_web", (5, 6)),
                  ("m_minotaur_of_baphomet", "a_gore", (5, 6)),
                  ("m_ape", "a_rock", (6, 6)),
                  ("m_giant_ape", "a_boulder_toss", (6, 6))]
        for mid, aid, expected in cases:
            m = _registry().get("monster", mid)
            act = next(a for a in m["actions"] if a["id"] == aid)
            self.assertEqual(recharge.parse_die_range(act["recharge"]),
                              expected, f"{mid}/{aid}")


if __name__ == "__main__":
    unittest.main()
