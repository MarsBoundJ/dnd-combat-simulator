"""Tests for the narrative combat-log renderer (WS-F0, engine/narrative.py).

Two layers:
  1. Synthetic event streams — hand-built lists of the REAL event_log dict
     shapes (verified against the live taxonomy) let us assert exact line
     shapes for a hit, a crit, a miss, merged damage, an HP update, a save,
     a condition, a drop, named AoE casts, and round boundaries.
  2. A real end-to-end sim — drive an EncounterRunner to termination and
     render its actual event_log, proving the formatter consumes a genuine
     stream and emits round-prefixed, HP-bearing lines.
"""
from __future__ import annotations

import random
import unittest

from engine.narrative import (render_narrative, format_run, _action_name,
                              _condition_name, _coords)
from engine.core.runner import EncounterRunner
from engine.core.state import Actor, CombatState, Encounter


# ---------------------------------------------------------------------------
# Roster doubles
# ---------------------------------------------------------------------------

class _FakeActor:
    """Minimal actor-like object for roster enrichment (name/class/hp_max)."""
    def __init__(self, name, hp_max=None, class_id=None, creature_type=None):
        self.name = name
        self.hp_max = hp_max
        self.template = {}
        if class_id:
            self.template["derived_from_pc_schema"] = {"class": class_id}
        if creature_type:
            self.template["creature_type"] = creature_type


# ---------------------------------------------------------------------------
# 1. Synthetic-stream line-shape tests
# ---------------------------------------------------------------------------

class HelperTest(unittest.TestCase):
    def test_action_name_de_snakes_and_strips_prefix(self):
        self.assertEqual(_action_name("a_fire_bolt"), "Fire Bolt")
        self.assertEqual(_action_name("f_fireball"), "Fireball")
        self.assertEqual(_action_name("la_pounce"), "Pounce")

    def test_condition_name_strips_co_prefix(self):
        self.assertEqual(_condition_name("co_frightened"), "frightened")
        self.assertEqual(_condition_name("co_prone"), "prone")

    def test_coords(self):
        self.assertEqual(_coords([12, 8]), "(12,8)")
        self.assertEqual(_coords((3, 4)), "(3,4)")
        self.assertEqual(_coords(None), "(?)")


class SyntheticStreamTest(unittest.TestCase):

    def _two_round_stream(self):
        return [
            {"event": "turn_start", "actor": "pc", "round": 1},
            {"event": "moved", "actor": "pc", "from": [0, 0], "to": [12, 8],
             "ft": 20},
            {"event": "attack_roll", "actor": "pc", "target": "orc",
             "d20": 18, "total": 24, "vs_ac": 13, "result": "hit",
             "advantage_state": "none", "crit_threshold": 20},
            {"event": "damage_dealt", "actor": "pc", "target": "orc",
             "amount": 11, "type": "fire", "target_hp_remaining": 23},
            {"event": "turn_end", "actor": "pc", "hp_remaining": 30},
            {"event": "turn_start", "actor": "orc", "round": 1},
            {"event": "attack_roll", "actor": "orc", "target": "pc",
             "d20": 7, "total": 11, "vs_ac": 16, "result": "miss",
             "advantage_state": "none", "crit_threshold": 20},
            {"event": "turn_end", "actor": "orc", "hp_remaining": 23},
            {"event": "turn_start", "actor": "pc", "round": 2},
            {"event": "aoe_origin_placed", "actor": "pc", "action": "a_fireball",
             "origin": [10, 10]},
            {"event": "forced_save", "target": "orc", "ability": "dexterity",
             "dc": 15, "d20": 4, "total": 9, "outcome": "fail"},
            {"event": "damage_dealt", "actor": "pc", "target": "orc",
             "amount": 14, "type": "fire", "target_hp_remaining": 9},
            {"event": "condition_applied", "target": "orc",
             "condition": "co_prone", "source": "pc"},
            {"event": "creature_dropped", "creature": "orc"},
            {"event": "turn_end", "actor": "orc", "hp_remaining": 0},
        ]

    def test_round_boundaries_present(self):
        lines = render_narrative(self._two_round_stream())
        self.assertTrue(any(l.startswith("Round 1 — ") for l in lines))
        self.assertTrue(any(l.startswith("Round 2 — ") for l in lines))

    def test_one_line_per_acting_turn(self):
        lines = render_narrative(self._two_round_stream())
        # pc (r1), orc (r1), pc (r2) each acted → 3 lines.
        self.assertEqual(len(lines), 3)

    def test_hit_merges_damage_and_movement(self):
        lines = render_narrative(self._two_round_stream())
        pc_r1 = next(l for l in lines if l.startswith("Round 1 — pc"))
        self.assertIn("moves to (12,8)", pc_r1)
        self.assertIn("hits orc (roll 18) for 11 fire", pc_r1)
        # HP update clause (no roster → current-HP-only)
        self.assertIn("orc 23 HP", pc_r1)

    def test_miss_line(self):
        lines = render_narrative(self._two_round_stream())
        orc_r1 = next(l for l in lines if l.startswith("Round 1 — orc"))
        self.assertIn("misses pc (roll 7)", orc_r1)

    def test_no_duplicate_damage_after_merged_attack(self):
        # The damage merged into the hit clause must not ALSO appear as a
        # standalone "takes 11 fire" clause.
        lines = render_narrative(self._two_round_stream())
        pc_r1 = next(l for l in lines if l.startswith("Round 1 — pc"))
        self.assertNotIn("takes 11", pc_r1)

    def test_aoe_save_condition_and_drop(self):
        lines = render_narrative(self._two_round_stream())
        pc_r2 = next(l for l in lines if l.startswith("Round 2 — pc"))
        self.assertIn("casts Fireball at (10,10)", pc_r2)
        self.assertIn("DEX save vs DC 15: fails (roll 9)", pc_r2)
        self.assertIn("orc takes 14 fire", pc_r2)
        self.assertIn("orc is prone", pc_r2)
        self.assertIn("orc drops!", pc_r2)

    def test_crit_and_autorange_miss(self):
        stream = [
            {"event": "turn_start", "actor": "a", "round": 1},
            {"event": "attack_roll", "actor": "a", "target": "b", "d20": 20,
             "total": 27, "result": "crit", "vs_ac": 15},
            {"event": "damage_dealt", "actor": "a", "target": "b",
             "amount": 22, "type": "slashing", "target_hp_remaining": 0},
            {"event": "attack_roll", "actor": "a", "target": "b",
             "result": "miss", "reason": "out_of_range"},
            {"event": "turn_end", "actor": "a"},
        ]
        line = render_narrative(stream)[0]
        self.assertIn("crits b (roll 20) for 22 slashing", line)
        self.assertIn("misses b (out of range)", line)

    def test_show_unhandled_surfaces_unknown_events(self):
        stream = [
            {"event": "turn_start", "actor": "a", "round": 1},
            {"event": "weapon_mastery_applied", "actor": "a"},
            {"event": "turn_end", "actor": "a"},
        ]
        # default: bookkeeping event dropped → no clause → no line
        self.assertEqual(render_narrative(stream), [])
        # opt-in: surfaced as a raw clause
        verbose = render_narrative(stream, show_unhandled=True)
        self.assertTrue(any("(weapon_mastery_applied)" in l for l in verbose))


class RosterEnrichmentTest(unittest.TestCase):

    def _stream(self):
        return [
            {"event": "turn_start", "actor": "pc1", "round": 2},
            {"event": "moved", "actor": "pc1", "to": [12, 8]},
            {"event": "attack_roll", "actor": "pc1", "target": "orc1",
             "d20": 18, "total": 22, "result": "hit", "vs_ac": 13},
            {"event": "damage_dealt", "actor": "pc1", "target": "orc1",
             "amount": 11, "type": "fire", "target_hp_remaining": 23},
            {"event": "turn_end", "actor": "pc1"},
        ]

    def test_label_strings(self):
        actors = {"pc1": "Aria", "orc1": "Orc"}
        line = render_narrative(self._stream(), actors=actors)[0]
        self.assertTrue(line.startswith("Round 2 — Aria: "))
        self.assertIn("hits Orc (roll 18) for 11 fire", line)

    def test_actor_objects_give_class_and_hp_fraction(self):
        actors = {
            "pc1": _FakeActor("Aria", hp_max=30, class_id="c_wizard"),
            "orc1": _FakeActor("Orc", hp_max=34, creature_type="humanoid"),
        }
        line = render_narrative(self._stream(), actors=actors)[0]
        # "Aria (Wizard)" label + monster's creature-type tag + the full
        # "23/34 HP (68%)" fraction (hp_max came from the roster object).
        self.assertIn("Round 2 — Aria (Wizard): ", line)
        self.assertIn("Orc (Humanoid)", line)
        self.assertIn("23/34 HP (68%)", line)

    def test_unknown_id_falls_back_to_raw_id(self):
        # roster missing 'orc1' → its id is shown verbatim, line still renders
        actors = {"pc1": "Aria"}
        line = render_narrative(self._stream(), actors=actors)[0]
        self.assertIn("hits orc1 (roll 18)", line)


# ---------------------------------------------------------------------------
# 2. Real end-to-end sim
# ---------------------------------------------------------------------------

def _bruiser(actor_id, *, side, position):
    abilities = {"str": {"score": 18, "save": 6}, "dex": {"score": 10, "save": 2},
                 "con": {"score": 16, "save": 5}, "int": {"score": 10, "save": 0},
                 "wis": {"score": 10, "save": 2}, "cha": {"score": 10, "save": 0}}
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id.title(),
        "abilities": abilities,
        "cr": {"value": 1, "xp": 200, "proficiency_bonus": 2},
        "creature_type": "humanoid",
        "actions": [{
            "id": "a_greatsword", "name": "Greatsword", "type": "weapon_attack",
            "slot": "action",
            "pipeline": [
                {"primitive": "attack_roll",
                 "params": {"kind": "melee", "ability": "str", "bonus": 6,
                            "reach_ft": 5}},
                {"primitive": "damage",
                 "params": {"dice": "2d6", "modifier": 4, "type": "slashing"},
                 "when": {"event": "damage_roll",
                          "condition": "combat.attack_state == hit"}},
            ],
        }],
    }
    return Actor(id=actor_id, name=actor_id.title(), template=template,
                 side=side, hp_current=40, hp_max=40, ac=12,
                 speed={"walk": 30}, position=position, abilities=abilities)


class RealSimRenderTest(unittest.TestCase):

    def test_renders_a_real_encounter_stream(self):
        hero = _bruiser("hero", side="pc", position=(0, 0))
        foe = _bruiser("foe", side="enemy", position=(1, 0))   # adjacent
        enc = Encounter(id="e", actors=[hero, foe])
        runner = EncounterRunner.new(enc, seed=7)
        state = runner.run(seed=7)

        # The stream must actually contain the structural events we render.
        names = {e.get("event") for e in state.event_log}
        self.assertIn("turn_start", names)
        self.assertIn("attack_roll", names)

        # format_run auto-pulls the roster off the CombatState.
        transcript = format_run(state)
        lines = transcript.splitlines()
        self.assertTrue(lines, "transcript should not be empty")

        # Round-prefixed, name-bearing lines (roster gives "Hero (Humanoid)").
        self.assertTrue(any(l.startswith("Round 1 — ") for l in lines))
        self.assertTrue(any("Hero" in l for l in lines))

        # At least one resolved attack (hit or miss) and one HP figure.
        joined = transcript.lower()
        self.assertTrue(("hits" in joined) or ("misses" in joined)
                        or ("crits" in joined))
        self.assertIn(" hp", joined)

        # Either the fight reached a 2nd round or someone dropped — both are
        # legitimate round-boundary evidence for a 40-HP slugfest.
        reached_r2 = any(l.startswith("Round 2 — ") for l in lines)
        someone_dropped = "drops!" in joined
        self.assertTrue(reached_r2 or someone_dropped)

    def test_render_narrative_on_raw_event_list(self):
        # format_run also accepts a bare event list (no CombatState).
        hero = _bruiser("hero", side="pc", position=(0, 0))
        foe = _bruiser("foe", side="enemy", position=(1, 0))
        enc = Encounter(id="e", actors=[hero, foe])
        state = EncounterRunner.new(enc, seed=3).run(seed=3)
        lines = render_narrative(state.event_log)   # no roster → ids
        self.assertTrue(lines)
        self.assertTrue(any(l.startswith("Round 1 — ") for l in lines))


if __name__ == "__main__":
    unittest.main()
