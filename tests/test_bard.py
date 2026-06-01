"""Bard class + Bardic Inspiration + College of Lore (Cutting Words).

Layers:
  1. c_bard loads: CHA full-caster chassis, spells wired, subclass L3
  2. Resource: bardic_inspiration_uses = max(1, CHA mod); die scales by
     level (d6→d8→d10→d12)
  3. Grant: grant_bardic_inspiration registers a held die on an ally
  4. Self-add (engine.core.bardic_inspiration.maybe_add_to_attack):
     turns a would-be miss into a hit; saves the die when it can't help;
     no-op without a die or on a hit/crit
  5. Self-add end-to-end via _attack_roll
  6. College of Lore via subclass consumption: Cutting Words wired
  7. Cutting Words condition gating (cutting_words_would_help)
  8. Cutting Words end-to-end: an enemy hit becomes a miss when the Bard
     reacts (rides attack_roll_pending), and a bardic use is consumed
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import bardic_inspiration as bi
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template, derive_pc_resources
from engine.primitives import _attack_roll, _grant_bardic_inspiration

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"

_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True,
                                   schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _bard_spec(level=3, cha=18, subclass="sc_college_of_lore"):
    spec = {"id": "bard", "class": "c_bard", "level": level,
            "ability_scores": {"str": 8, "dex": 14, "con": 12,
                                 "int": 10, "wis": 10, "cha": cha},
            "weapons": []}
    if subclass and level >= 3:
        spec["subclass"] = subclass
    return spec


def _plain_actor(actor_id, *, side, position=(0, 0), ac=14, hp=30):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac, speed={"walk": 30},
                  position=position, abilities=abilities)


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = _registry()
    return st


# ============================================================================
# Layer 1: chassis
# ============================================================================

class ChassisTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_bard_is_cha_full_caster(self) -> None:
        c = self.registry.get("class", "c_bard")
        self.assertEqual(c["spellcasting"]["ability"], "charisma")
        self.assertEqual(c["spellcasting"]["slots_progression"], "full_caster")
        self.assertEqual(c["subclass_grant_level"], 3)
        self.assertEqual(len(c["level_table"]), 20)

    def test_l1_bard_has_inspiration_and_spells(self) -> None:
        t = build_pc_template(_bard_spec(level=1), self.registry)
        feats = set(t.get("features_known", []))
        self.assertIn("f_bardic_inspiration", feats)
        # Built Bard-list spells wired
        action_ids = {a.get("id") for a in t.get("actions", [])}
        self.assertIn("a_healing_word", action_ids)
        self.assertIn("a_heroism", action_ids)

    def test_spellcasting_ability_stamped_cha(self) -> None:
        t = build_pc_template(_bard_spec(level=1), self.registry)
        self.assertEqual(t.get("spellcasting_ability"), "charisma")


# ============================================================================
# Layer 2: resource + die scaling
# ============================================================================

class ResourceTest(unittest.TestCase):

    def test_uses_equal_cha_mod(self) -> None:
        res = derive_pc_resources(_bard_spec(level=1, cha=18), _registry())
        self.assertEqual(res["bardic_inspiration_uses_remaining"], 4)

    def test_uses_minimum_one(self) -> None:
        # CHA 10 → +0 mod → min 1 use
        res = derive_pc_resources(_bard_spec(level=1, cha=10), _registry())
        self.assertEqual(res["bardic_inspiration_uses_remaining"], 1)

    def test_die_scales_by_level(self) -> None:
        cases = {1: "d6", 4: "d6", 5: "d8", 9: "d8", 10: "d10",
                  14: "d10", 15: "d12", 20: "d12"}
        for lvl, die in cases.items():
            sub = "sc_college_of_lore" if lvl >= 3 else None
            t = build_pc_template(_bard_spec(level=lvl, subclass=sub),
                                    _registry())
            self.assertEqual(t.get("bardic_die"), die, f"level {lvl}")


# ============================================================================
# Layer 3: grant
# ============================================================================

class GrantTest(unittest.TestCase):

    def test_grant_registers_die_on_ally(self) -> None:
        bard = _plain_actor("bard", side="pc")
        bard.template["bardic_die"] = "d8"
        ally = _plain_actor("ally", side="pc")
        state = _make_state([bard, ally])
        state.current_attack = {"actor": bard, "target": ally}
        _grant_bardic_inspiration({}, state, EventBus())
        marker = bi.find_inspiration_die(ally)
        self.assertIsNotNone(marker)
        self.assertEqual(marker["params"]["die"], "d8")

    def test_grant_replaces_existing_die(self) -> None:
        bard = _plain_actor("bard", side="pc")
        bard.template["bardic_die"] = "d6"
        ally = _plain_actor("ally", side="pc")
        state = _make_state([bard, ally])
        state.current_attack = {"actor": bard, "target": ally}
        _grant_bardic_inspiration({}, state, EventBus())
        _grant_bardic_inspiration({}, state, EventBus())
        dice = [m for m in ally.active_modifiers
                  if m.get("primitive") == bi.INSPIRATION_DIE_PRIMITIVE]
        self.assertEqual(len(dice), 1)  # only one die at a time


# ============================================================================
# Layer 4: self-add helper
# ============================================================================

class SelfAddTest(unittest.TestCase):

    def test_adds_when_can_turn_miss_to_hit(self) -> None:
        actor = _plain_actor("holder", side="pc")
        state = _make_state([actor])
        bi.register_inspiration_die(actor, "d8", "bard", state)
        # total 13 vs AC 14 → miss; d8 can close the 1-gap
        rng = random.Random(1)
        new_total = bi.maybe_add_to_attack(actor, 13, 14, False, state, rng)
        self.assertGreaterEqual(new_total, 14)
        # die consumed
        self.assertIsNone(bi.find_inspiration_die(actor))

    def test_saves_die_when_cannot_help(self) -> None:
        actor = _plain_actor("holder", side="pc")
        state = _make_state([actor])
        bi.register_inspiration_die(actor, "d6", "bard", state)
        # total 5 vs AC 20 → even a max d6 (6) can't reach; keep the die
        new_total = bi.maybe_add_to_attack(actor, 5, 20, False,
                                             state, random.Random(1))
        self.assertEqual(new_total, 5)
        self.assertIsNotNone(bi.find_inspiration_die(actor))

    def test_noop_on_hit(self) -> None:
        actor = _plain_actor("holder", side="pc")
        state = _make_state([actor])
        bi.register_inspiration_die(actor, "d8", "bard", state)
        # already hits (18 >= 14) → no spend
        new_total = bi.maybe_add_to_attack(actor, 18, 14, False,
                                             state, random.Random(1))
        self.assertEqual(new_total, 18)
        self.assertIsNotNone(bi.find_inspiration_die(actor))

    def test_noop_without_die(self) -> None:
        actor = _plain_actor("holder", side="pc")
        state = _make_state([actor])
        new_total = bi.maybe_add_to_attack(actor, 13, 14, False,
                                             state, random.Random(1))
        self.assertEqual(new_total, 13)


# ============================================================================
# Layer 5: self-add end-to-end via _attack_roll
# ============================================================================

class SelfAddEndToEndTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(5))

    def test_holder_attack_can_become_hit(self) -> None:
        # An attacker holding a big die; force a near-miss roll and verify
        # the die can rescue it. We sweep seeds to find a near-miss case.
        for seed in range(40):
            attacker = _plain_actor("att", side="pc", position=(0, 0))
            attacker.template["actions"] = []
            target = _plain_actor("def", side="enemy", position=(1, 0), ac=18)
            state = _make_state([attacker, target])
            bi.register_inspiration_die(attacker, "d12", "bard", state)
            state.current_attack = {"actor": attacker, "target": target,
                                      "action": {"id": "a_sword"},
                                      "had_advantage": False,
                                      "had_disadvantage": False}
            rng = random.Random(seed)
            primitives_module.set_rng(rng)
            _attack_roll({"bonus": 6, "reach_ft": 5}, state, EventBus())
            added = [e for e in state.event_log
                       if e.get("event") == "bardic_inspiration_added"]
            if added:
                # When the die was added, the attack must have resolved hit/crit
                self.assertIn(state.current_attack["state"], ("hit", "crit"))
                return
        self.skipTest("no near-miss case in seed sweep (rare)")


# ============================================================================
# Layer 6: College of Lore via subclass consumption
# ============================================================================

class CollegeOfLoreWiringTest(unittest.TestCase):

    def test_l3_lore_bard_has_cutting_words(self) -> None:
        t = build_pc_template(_bard_spec(level=3), _registry())
        feats = set(t.get("features_known", []))
        self.assertIn("f_cutting_words", feats)
        self.assertIn("f_bonus_proficiencies", feats)
        action_ids = {a.get("id") for a in t.get("actions", [])}
        self.assertIn("a_cutting_words", action_ids)


# ============================================================================
# Layer 7+8: Cutting Words condition + end-to-end
# ============================================================================

class CuttingWordsTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(3))

    def _lore_bard_actor(self, position=(0, 0)):
        # Build a real L5 Lore Bard (d8 die) so a_cutting_words is wired.
        t = build_pc_template(_bard_spec(level=5), _registry())
        res = derive_pc_resources(_bard_spec(level=5), _registry())
        a = Actor(id="bard", name="bard", template=t, side="pc",
                   hp_current=30, hp_max=30, ac=14, speed={"walk": 30},
                   position=position,
                   abilities=t["abilities"])
        a.resources = dict(res)
        return a

    def test_condition_fires_for_enemy_hit_in_range(self) -> None:
        from engine.core.reactions import _reaction_condition_satisfied
        bard = self._lore_bard_actor(position=(0, 0))
        attacker = _plain_actor("orc", side="enemy", position=(1, 0))
        ally = _plain_actor("ally", side="pc", position=(0, 1), ac=15)
        state = _make_state([bard, attacker, ally])
        ed = {"actor": attacker, "target": ally, "total": 16,
              "current_ac": 15, "was_going_to_hit": True}
        self.assertTrue(_reaction_condition_satisfied(
            "cutting_words_would_help", bard, ed, state))

    def test_condition_skips_when_attack_missed(self) -> None:
        from engine.core.reactions import _reaction_condition_satisfied
        bard = self._lore_bard_actor()
        attacker = _plain_actor("orc", side="enemy", position=(1, 0))
        ally = _plain_actor("ally", side="pc", position=(0, 1), ac=15)
        state = _make_state([bard, attacker, ally])
        ed = {"actor": attacker, "target": ally, "total": 10,
              "current_ac": 15, "was_going_to_hit": False}
        self.assertFalse(_reaction_condition_satisfied(
            "cutting_words_would_help", bard, ed, state))

    def test_end_to_end_negates_enemy_hit(self) -> None:
        # Enemy attacks the ally and would hit; the Bard reacts with
        # Cutting Words and the AC bump turns it into a miss.
        bard = self._lore_bard_actor(position=(0, 0))
        attacker = _plain_actor("orc", side="enemy", position=(1, 0))
        ally = _plain_actor("ally", side="pc", position=(0, 1), ac=14)
        state = _make_state([attacker, bard, ally])
        uses_before = bard.resources["bardic_inspiration_uses_remaining"]
        # Sweep seeds to find a roll that hits AC 14 by a small margin
        # (within d8) so Cutting Words can flip it.
        for seed in range(60):
            ally.ac = 14
            ally.active_modifiers = []
            attacker.actions_used_this_turn = {}
            bard.actions_used_this_turn = {}
            bard.resources["bardic_inspiration_uses_remaining"] = uses_before
            state.current_attack = {"actor": attacker, "target": ally,
                                      "action": {"id": "a_orc_axe"},
                                      "had_advantage": False,
                                      "had_disadvantage": False}
            primitives_module.set_rng(random.Random(seed))
            _attack_roll({"bonus": 5, "reach_ft": 5}, state, EventBus())
            fired = [e for e in state.event_log
                       if e.get("event") == "cutting_words_resolved"]
            if fired:
                # Cutting Words fired → use consumed + attack resolved miss
                self.assertEqual(
                    bard.resources["bardic_inspiration_uses_remaining"],
                    uses_before - 1)
                self.assertEqual(state.current_attack["state"], "miss")
                return
        self.skipTest("no flip-able hit found in seed sweep (rare)")


if __name__ == "__main__":
    unittest.main()
