"""WS-F1 — engine.metrics.compute_metrics.

Synthetic event streams assert each metric bucket precisely and each
outcome-taxonomy branch; two real EncounterRunner sims cross-validate the
outcome classifier against the engine's own termination verdict and confirm
the buckets populate from a live fight.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.metrics import (
    compute_metrics, roster_from_actors, difficulty_band,
    VICTORY, TPK, FLED_ENEMY_ALIVE, STALEMATE, MUTUAL_DESTRUCTION, UNKNOWN,
)
from engine.core.runner import EncounterRunner
from engine.core.state import Actor, Encounter
from engine.loader import load_content

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"

_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _roster(*entries):
    """entries: (id, side, hp_max[, name])."""
    out = {}
    for e in entries:
        aid, side, hp = e[0], e[1], e[2]
        name = e[3] if len(e) > 3 else aid
        out[aid] = {"side": side, "hp_max": hp, "name": name}
    return out


# ════════════════════════════════════ buckets ════════════════════════════════

class BucketTest(unittest.TestCase):
    """Each WS-F1 bucket, isolated, from a hand-built stream."""

    def setUp(self):
        self.roster = _roster(("pc", "pc", 40, "Hero"), ("foe", "enemy", 30))

    def test_damage_dealt_and_taken_cross_side(self):
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "damage_dealt", "actor": "pc", "target": "foe",
             "amount": 12, "type": "fire", "target_hp_remaining": 18},
            {"event": "damage_dealt", "actor": "foe", "target": "pc",
             "amount": 7, "type": "slashing", "target_hp_remaining": 33},
        ]
        m = compute_metrics(events, roster=self.roster)
        self.assertEqual(m["per_actor"]["pc"]["damage_dealt"], 12)
        self.assertEqual(m["per_actor"]["pc"]["damage_taken"], 7)
        self.assertEqual(m["per_actor"]["foe"]["damage_taken"], 12)
        self.assertEqual(m["per_side"]["pc"]["damage_dealt"], 12)
        self.assertEqual(m["per_side"]["enemy"]["damage_dealt"], 7)

    def test_friendly_fire_not_counted_as_dealt(self):
        # PC AoE clips an ally: damage_taken registers, damage_dealt does not.
        roster = _roster(("pc", "pc", 40), ("ally", "pc", 25), ("foe", "enemy", 30))
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "damage_dealt", "actor": "pc", "target": "ally",
             "amount": 9, "type": "fire", "target_hp_remaining": 16},
        ]
        m = compute_metrics(events, roster=roster)
        self.assertEqual(m["per_actor"]["pc"]["damage_dealt"], 0)
        self.assertEqual(m["per_actor"]["ally"]["damage_taken"], 9)

    def test_hit_crit_automiss_and_hit_pct(self):
        events = [
            {"event": "attack_roll", "actor": "pc", "target": "foe", "d20": 18, "result": "hit"},
            {"event": "attack_roll", "actor": "pc", "target": "foe", "d20": 20, "result": "crit"},
            {"event": "attack_roll", "actor": "pc", "target": "foe", "d20": 4, "result": "miss"},
            # auto-miss: out of range, never rolled a d20
            {"event": "attack_roll", "actor": "pc", "target": "foe",
             "result": "miss", "reason": "out_of_range"},
        ]
        r = compute_metrics(events, roster=self.roster)["per_actor"]["pc"]
        self.assertEqual(r["attacks"], 3)
        self.assertEqual(r["hits"], 2)
        self.assertEqual(r["crits"], 1)
        self.assertEqual(r["auto_misses"], 1)
        self.assertEqual(r["hit_pct"], round(100 * 2 / 3, 1))

    def test_spell_slots_by_level(self):
        events = [
            {"event": "spell_slot_consumed", "actor": "pc", "slot_level": 3, "remaining": 1},
            {"event": "spell_slot_consumed", "actor": "pc", "slot_level": 1, "remaining": 2},
            {"event": "spell_slot_consumed", "actor": "pc", "slot_level": 1, "remaining": 1},
        ]
        r = compute_metrics(events, roster=self.roster)["per_actor"]["pc"]
        self.assertEqual(r["spell_slots_spent"], {3: 1, 1: 2})
        self.assertEqual(r["spell_slots_total"], 3)

    def test_healing_done_and_received(self):
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "healed", "target": "pc", "amount": 8, "hp_current": 40},
        ]
        m = compute_metrics(events, roster=self.roster)
        self.assertEqual(m["per_actor"]["pc"]["healing_received"], 8)
        # `healed` carries only the target → credited to the turn's actor.
        self.assertEqual(m["per_actor"]["pc"]["healing_done"], 8)

    def test_control_rounds_denied(self):
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            # hard control (1.0) on the foe
            {"event": "condition_applied", "source": "pc", "target": "foe",
             "condition": "co_stunned"},
            # control on own side is NOT credited
            {"event": "condition_applied", "source": "pc", "target": "pc",
             "condition": "co_stunned"},
            # non-control condition contributes nothing
            {"event": "condition_applied", "source": "pc", "target": "foe",
             "condition": "co_poisoned"},
        ]
        r = compute_metrics(events, roster=self.roster)["per_actor"]["pc"]
        self.assertEqual(r["control_applications"], 1)
        self.assertEqual(r["control_rounds_denied"], 1.0)

    def test_movement_stats(self):
        events = [
            {"event": "moved", "actor": "pc", "ft": 15, "reason": "engage"},
            {"event": "moved", "actor": "pc", "ft": 10, "reason": "kite"},
        ]
        r = compute_metrics(events, roster=self.roster)["per_actor"]["pc"]
        self.assertEqual(r["feet_moved"], 25)
        self.assertEqual(r["moves"], 2)

    def test_rounds_from_turn_starts(self):
        events = [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "turn_start", "actor": "foe", "round": 1},
            {"event": "turn_start", "actor": "pc", "round": 2},
            {"event": "turn_start", "actor": "foe", "round": 3},
        ]
        self.assertEqual(compute_metrics(events, roster=self.roster)["rounds"], 3)

    def test_non_participant_still_listed(self):
        m = compute_metrics([], roster=self.roster)
        self.assertIn("pc", m["per_actor"])
        self.assertIn("foe", m["per_actor"])
        self.assertEqual(m["per_actor"]["pc"]["attacks"], 0)


# ═══════════════════════════════ HP reconstruction ═══════════════════════════

class HpReconstructionTest(unittest.TestCase):

    def test_final_hp_tracks_last_authoritative_value(self):
        roster = _roster(("pc", "pc", 40), ("foe", "enemy", 30))
        events = [
            {"event": "damage_dealt", "actor": "foe", "target": "pc",
             "amount": 10, "type": "x", "target_hp_remaining": 30},
            {"event": "damage_dealt", "actor": "foe", "target": "pc",
             "amount": 25, "type": "x", "target_hp_remaining": 5},
            {"event": "healed", "target": "pc", "amount": 12, "hp_current": 17},
        ]
        m = compute_metrics(events, roster=roster)
        self.assertEqual(m["per_actor"]["pc"]["final_hp"], 17)
        self.assertTrue(m["per_actor"]["pc"]["alive"])

    def test_untouched_actor_defaults_to_hp_max(self):
        roster = _roster(("pc", "pc", 40), ("foe", "enemy", 30))
        m = compute_metrics([], roster=roster)
        self.assertEqual(m["per_actor"]["pc"]["final_hp"], 40)

    def test_drop_then_revive(self):
        roster = _roster(("pc", "pc", 40), ("foe", "enemy", 30))
        events = [
            {"event": "creature_dropped", "creature": "pc"},
            {"event": "revived", "actor": "pc", "hp": 9, "reason": "healed"},
        ]
        m = compute_metrics(events, roster=roster)
        self.assertEqual(m["per_actor"]["pc"]["final_hp"], 9)
        self.assertTrue(m["per_actor"]["pc"]["alive"])


# ═══════════════════════════ outcome taxonomy (synthetic) ════════════════════

class OutcomeTaxonomyTest(unittest.TestCase):

    def _stream_kill(self, killer, victim):
        return [{"event": "damage_dealt", "actor": killer, "target": victim,
                 "amount": 999, "type": "x", "target_hp_remaining": 0},
                {"event": "creature_dropped", "creature": victim}]

    def test_victory(self):
        roster = _roster(("pc", "pc", 40), ("foe", "enemy", 30))
        m = compute_metrics(self._stream_kill("pc", "foe"), roster=roster)
        self.assertEqual(m["outcome"]["result"], VICTORY)
        self.assertEqual(m["outcome"]["winning_side"], "pc")
        # closeness = surviving (pc) side HP fraction; pc untouched → 1.0
        self.assertEqual(m["outcome"]["closeness"]["surviving_side"], "pc")
        self.assertEqual(m["outcome"]["closeness"]["hp_fraction"], 1.0)

    def test_tpk(self):
        roster = _roster(("pc", "pc", 40), ("foe", "enemy", 30))
        m = compute_metrics(self._stream_kill("foe", "pc"), roster=roster)
        self.assertEqual(m["outcome"]["result"], TPK)
        self.assertEqual(m["outcome"]["winning_side"], "enemy")

    def test_fled_enemy_alive(self):
        roster = _roster(("pc", "pc", 40), ("foe", "enemy", 30))
        events = [
            {"event": "damage_dealt", "actor": "foe", "target": "pc",
             "amount": 10, "type": "x", "target_hp_remaining": 30},
            {"event": "fled", "actor": "pc"},
        ]
        m = compute_metrics(events, roster=roster)
        self.assertEqual(m["outcome"]["result"], FLED_ENEMY_ALIVE)
        self.assertEqual(m["outcome"]["winning_side"], "enemy")

    def test_stalemate_both_sides_alive(self):
        roster = _roster(("pc", "pc", 40), ("foe", "enemy", 30))
        events = [{"event": "turn_start", "actor": "pc", "round": 50}]  # both full HP
        m = compute_metrics(events, roster=roster)
        self.assertEqual(m["outcome"]["result"], STALEMATE)
        self.assertIsNone(m["outcome"]["winning_side"])

    def test_mutual_destruction(self):
        roster = _roster(("pc", "pc", 40), ("foe", "enemy", 30))
        events = (self._stream_kill("foe", "pc") + self._stream_kill("pc", "foe"))
        m = compute_metrics(events, roster=roster)
        self.assertEqual(m["outcome"]["result"], MUTUAL_DESTRUCTION)

    def test_closeness_reflects_attrition(self):
        # Pyrrhic victory: pc wins but is badly hurt.
        roster = _roster(("pc", "pc", 100), ("foe", "enemy", 30))
        events = [
            {"event": "damage_dealt", "actor": "foe", "target": "pc",
             "amount": 90, "type": "x", "target_hp_remaining": 10},
            {"event": "damage_dealt", "actor": "pc", "target": "foe",
             "amount": 999, "type": "x", "target_hp_remaining": 0},
            {"event": "creature_dropped", "creature": "foe"},
        ]
        m = compute_metrics(events, roster=roster)
        self.assertEqual(m["outcome"]["result"], VICTORY)
        self.assertEqual(m["outcome"]["closeness"]["hp_fraction"], 0.1)

    def test_no_roster_degrades_to_unknown(self):
        events = [{"event": "damage_dealt", "actor": "pc", "target": "foe",
                   "amount": 5, "type": "x", "target_hp_remaining": 0}]
        m = compute_metrics(events)  # no roster
        self.assertEqual(m["outcome"]["result"], UNKNOWN)
        self.assertEqual(m["per_side"], {})
        # per-actor counters still computed (gross damage)
        self.assertEqual(m["per_actor"]["pc"]["damage_dealt"], 5)


# ═══════════════════════════ real EncounterRunner sims ═══════════════════════

class RealSimTest(unittest.TestCase):
    """Drive a real fight; cross-validate the outcome classifier against the
    engine's own termination verdict and confirm buckets populate."""

    MELEE = "m_aarakocra"      # has a melee a_talons attack + walk speed
    ATTACK_ID = "a_talons"

    def _actor(self, aid, side, hp, ac, pos):
        m = _registry().get("monster", self.MELEE)
        return Actor(id=aid, name=aid, template=m, side=side,
                     hp_current=hp, hp_max=hp, ac=ac,
                     speed={"walk": m["combat"]["speed"].get("walk", 30)},
                     position=pos, abilities=m["abilities"])

    def _run(self, pc_hp, pc_ac, foe_hp, foe_ac):
        """Run a lopsided 1v1 to a decisive end; return (state, roster).
        Loops seeds so the test never hinges on a single RNG draw."""
        for seed in range(25):
            pc = self._actor("hero", "pc", pc_hp, pc_ac, (0, 0))
            foe = self._actor("villain", "enemy", foe_hp, foe_ac, (1, 0))
            enc = Encounter(id="t", actors=[pc, foe])
            runner = EncounterRunner.new(enc, seed=seed, content_registry=_registry())
            state = runner.run(seed=seed)
            roster = roster_from_actors(state.encounter.actors)
            yield state, roster
            if state.terminated:
                return

    def test_victory_sim_matches_engine_verdict(self):
        # Tanky hero vs a 1-HP, AC-1 foe → reliable PC victory.
        for state, roster in self._run(pc_hp=500, pc_ac=18, foe_hp=1, foe_ac=1):
            if state.termination_reason == "side_pc_victory":
                break
        else:
            self.skipTest("no decisive PC victory in 25 seeds")
        m = compute_metrics(state.event_log, roster=roster)
        self.assertEqual(m["outcome"]["result"], VICTORY)
        self.assertEqual(m["outcome"]["winning_side"], "pc")
        # buckets populated from the live fight
        self.assertGreater(m["per_actor"]["hero"]["damage_dealt"], 0)
        self.assertGreater(m["per_actor"]["hero"]["attacks"], 0)
        self.assertTrue(m["per_actor"]["hero"]["alive"])
        self.assertTrue(m["per_actor"]["villain"]["downed"])
        # hero barely scratched → high closeness + Trivial difficulty
        self.assertGreater(m["outcome"]["closeness"]["hp_fraction"], 0.9)
        self.assertEqual(difficulty_band(m), "Trivial")

    def test_tpk_sim_matches_engine_verdict(self):
        # Fragile hero (1 HP, AC 1) vs a 500-HP foe → reliable party wipe.
        for state, roster in self._run(pc_hp=1, pc_ac=1, foe_hp=500, foe_ac=18):
            if state.termination_reason == "side_enemy_victory":
                break
        else:
            self.skipTest("no decisive enemy victory in 25 seeds")
        m = compute_metrics(state.event_log, roster=roster)
        self.assertEqual(m["outcome"]["result"], TPK)
        self.assertEqual(m["outcome"]["winning_side"], "enemy")
        self.assertFalse(m["per_actor"]["hero"]["alive"])
        self.assertGreater(m["per_actor"]["villain"]["damage_dealt"], 0)

    def test_metrics_run_on_serialized_stream_only(self):
        # F1 must work off the event list alone (no CombatState) — that's the
        # archive contract. Use a plain dict roster, not roster_from_actors.
        for state, _ in self._run(pc_hp=500, pc_ac=18, foe_hp=1, foe_ac=1):
            if state.terminated:
                break
        plain_roster = {
            "hero": {"side": "pc", "hp_max": 500, "name": "hero"},
            "villain": {"side": "enemy", "hp_max": 1, "name": "villain"},
        }
        m = compute_metrics(list(state.event_log), roster=plain_roster)
        self.assertIn(m["outcome"]["result"], (VICTORY, TPK, STALEMATE,
                                               MUTUAL_DESTRUCTION))
        self.assertEqual(set(m["per_actor"]), {"hero", "villain"})


if __name__ == "__main__":
    unittest.main()
