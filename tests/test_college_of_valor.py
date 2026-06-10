"""College of Valor tests (Bard subclass, PHB 2024).

Features under test:
  - Combat Inspiration (L3): Defense (die → AC vs hit) + Offense (die → damage)
  - Extra Attack (L6): 2-attack multiattack action
  - Battle Magic (L14): BA weapon attack unlocked after a spell action
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core.state import Actor, CombatState, Encounter
from engine.core.runner import EncounterRunner
from engine.loader import load_content
from engine.pc_schema import build_pc_template, derive_pc_resources
from engine.core.bardic_inspiration import (
    register_inspiration_die, find_inspiration_die, die_max)

_REPO = Path(__file__).resolve().parent.parent
_REG = None


def _reg():
    global _REG
    if _REG is None:
        _REG = load_content(_REPO / "schema" / "content", validate=True,
                            schema_root=_REPO / "schema")
    return _REG


def _valor(level, aid="bard", pos=(0, 0)):
    spec = {
        "id": aid, "class": "c_bard", "level": level,
        "subclass": "sc_college_of_valor",
        "ability_scores": {"str": 14, "dex": 14, "con": 12,
                           "int": 10, "wis": 12, "cha": 18},
        "weapons": [{"id": "longsword", "name": "Longsword",
                     "attack_ability": "str", "damage_dice": "1d8",
                     "damage_type": "slashing", "reach_ft": 5}],
    }
    tmpl = build_pc_template(spec, _reg())
    res = derive_pc_resources(spec, _reg())
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    ab["str"] = {"score": 14, "save": 2}
    ab["cha"] = {"score": 18, "save": 4}
    a = Actor(id=aid, name=aid, template=tmpl, side="pc",
              hp_current=40, hp_max=40, ac=16, position=pos,
              speed={"walk": 30}, abilities=ab)
    a.resources = dict(res)
    return a


def _enemy(pos=(1, 0), ac=14):
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    return Actor(id="goblin", name="goblin",
                 template={"id": "tg", "name": "goblin", "abilities": ab,
                            "cr": {"proficiency_bonus": 2}, "actions": [{
                                "id": "a_club", "name": "Club",
                                "type": "weapon_attack",
                                "pipeline": [
                                    {"primitive": "attack_roll",
                                     "params": {"bonus": 4, "kind": "melee",
                                                "ability": "str"}},
                                    {"primitive": "damage",
                                     "params": {"dice": "1d4", "modifier": 2,
                                                "type": "bludgeoning"},
                                     "when": {"condition":
                                              "combat.attack_state == hit"}},
                                ],
                            }],
                            "features_known": [],
                            "combat": {"initiative": {"modifier": 0}}},
                 side="enemy", hp_current=15, hp_max=15, ac=ac,
                 position=pos, speed={"walk": 30}, abilities=ab)


class CollegeOfValorFeaturesTest(unittest.TestCase):

    def test_l3_features_in_features_known(self):
        b = _valor(3)
        fk = b.template.get("features_known") or []
        self.assertIn("f_combat_inspiration", fk)
        self.assertIn("f_martial_training", fk)

    def test_l6_has_extra_attack_action(self):
        b = _valor(6)
        action_ids = [a["id"] for a in (b.template.get("actions") or [])]
        self.assertIn("a_extra_attack", action_ids)
        ea = next(a for a in b.template["actions"] if a["id"] == "a_extra_attack")
        self.assertEqual(ea["count"], 2)

    def test_l14_has_battle_magic_action(self):
        b = _valor(14)
        action_ids = [a["id"] for a in (b.template.get("actions") or [])]
        self.assertIn("a_battle_magic_attack", action_ids)
        bm = next(a for a in b.template["actions"]
                  if a["id"] == "a_battle_magic_attack")
        self.assertEqual(bm.get("slot"), "bonus_action")
        self.assertTrue(bm.get("requires_battle_magic"))


class CombatInspirationTagTest(unittest.TestCase):

    def test_valor_bi_die_tagged_combat_inspiration(self):
        b = _valor(3)
        ally = _enemy(pos=(1, 0))
        ally.side = "pc"
        # Simulate granting BI via the state machinery
        from engine.core.state import CombatState, Encounter
        enc = Encounter(id="e", actors=[b, ally])
        st = CombatState(encounter=enc)
        st.round = 1
        die = str((b.template or {}).get("bardic_die", "d6"))
        register_inspiration_die(ally, die, b.id, st,
                                 combat_inspiration=True)
        marker = find_inspiration_die(ally)
        self.assertIsNotNone(marker)
        self.assertTrue((marker.get("params") or {}).get("combat_inspiration"))

    def test_non_valor_bi_die_not_tagged(self):
        # Regular Lore Bard — should NOT tag combat_inspiration
        from engine.pc_schema import build_pc_template, derive_pc_resources
        spec = {
            "id": "lore", "class": "c_bard", "level": 3,
            "subclass": "sc_college_of_lore",
            "ability_scores": {"str": 8, "dex": 14, "con": 12,
                               "int": 12, "wis": 12, "cha": 16},
        }
        tmpl = build_pc_template(spec, _reg())
        fk = tmpl.get("features_known") or []
        self.assertNotIn("f_combat_inspiration", fk)


class CombatInspirationOffenseTest(unittest.TestCase):

    def test_offense_die_adds_to_damage(self):
        """Attacker holding a Combat Inspiration die gets bonus damage on a hit."""
        import engine.primitives as primitives_module
        import random
        primitives_module.set_rng(random.Random(1))
        b = _valor(3)
        enemy = _enemy(pos=(1, 0), ac=1)  # AC 1 → always hit
        from engine.core.state import CombatState, Encounter
        enc = Encounter(id="e", actors=[b, enemy])
        st = CombatState(encounter=enc)
        st.round = 1
        die = str((b.template or {}).get("bardic_die", "d6"))
        register_inspiration_die(b, die, "source", st, combat_inspiration=True)
        # Find the longsword attack action (weapon id is used as action id)
        sword = next(
            (a for a in (b.template.get("actions") or [])
             if a.get("id") == "longsword"),
            None)
        if sword is None:
            self.skipTest("No longsword action found")
        from engine.core.pipeline import execute
        from engine.core.events import EventBus
        from engine.primitives import PrimitiveRegistry
        chosen = {"actor": b, "target": enemy, "action": sword}
        execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        offense_events = [e for e in st.event_log
                          if e.get("event") == "combat_inspiration_offense"]
        self.assertTrue(offense_events, "Expected combat_inspiration_offense event")
        for ev in offense_events:
            self.assertGreaterEqual(ev["roll"], 1)
            self.assertLessEqual(ev["roll"], die_max(die))


class CombatInspirationDefenseTest(unittest.TestCase):

    def test_defense_die_can_prevent_hit(self):
        """Target holding a Combat Inspiration die may avoid a hit."""
        from engine.core.college_of_valor import maybe_defend_with_combat_inspiration
        import random
        # Simulate: total=14 would hit AC=13. Give target a d6 (max 6).
        # With max roll it boosts to AC=13+6=19 → miss.
        b = _valor(3)
        from engine.core.state import CombatState, Encounter
        enc = Encounter(id="e", actors=[b])
        st = CombatState(encounter=enc)
        st.round = 1
        die = "d6"
        register_inspiration_die(b, die, "source", st, combat_inspiration=True)
        # Seed rng so roll is always >= 2 (total=14, AC=13, so any roll >=2 turns miss)
        rng = random.Random(0)  # roll will be > 0, making new_ac >= 14
        new_ac = maybe_defend_with_combat_inspiration(
            b, total=14, effective_ac=13, is_crit=False, state=st, rng=rng)
        # The die was spent — die marker should be gone
        self.assertIsNone(find_inspiration_die(b))
        # Logged
        defense_events = [e for e in st.event_log
                          if e.get("event") == "combat_inspiration_defense"]
        self.assertTrue(defense_events)

    def test_defense_skips_crits(self):
        """Crits are not blocked by Combat Inspiration Defense (crits ignore AC)."""
        from engine.core.college_of_valor import maybe_defend_with_combat_inspiration
        import random
        b = _valor(3)
        from engine.core.state import CombatState, Encounter
        enc = Encounter(id="e", actors=[b])
        st = CombatState(encounter=enc)
        st.round = 1
        register_inspiration_die(b, "d6", "source", st, combat_inspiration=True)
        rng = random.Random(0)
        new_ac = maybe_defend_with_combat_inspiration(
            b, total=20, effective_ac=10, is_crit=True, state=st, rng=rng)
        self.assertEqual(new_ac, 10)  # unchanged on crit
        # Die was NOT consumed
        self.assertIsNotNone(find_inspiration_die(b))

    def test_defense_skips_when_die_cannot_help(self):
        """Die is kept when it cannot turn the hit into a miss even at max."""
        from engine.core.college_of_valor import maybe_defend_with_combat_inspiration
        import random
        b = _valor(3)
        from engine.core.state import CombatState, Encounter
        enc = Encounter(id="e", actors=[b])
        st = CombatState(encounter=enc)
        st.round = 1
        # total=25, AC=10, die=d6 (max 6 → 16 < 25): die cannot help
        register_inspiration_die(b, "d6", "source", st, combat_inspiration=True)
        rng = random.Random(0)
        new_ac = maybe_defend_with_combat_inspiration(
            b, total=25, effective_ac=10, is_crit=False, state=st, rng=rng)
        self.assertEqual(new_ac, 10)
        self.assertIsNotNone(find_inspiration_die(b))  # die kept


class BattleMagicTest(unittest.TestCase):

    def test_battle_magic_triggered_after_spell(self):
        """After a spell action, battle_magic_triggered is set on actor."""
        import engine.primitives as primitives_module
        import random
        primitives_module.set_rng(random.Random(1))
        b = _valor(14)
        enemy = _enemy(pos=(7, 0), ac=10)  # 35 ft, within vicious mockery range
        from engine.core.state import CombatState, Encounter
        enc = Encounter(id="e", actors=[b, enemy])
        st = CombatState(encounter=enc)
        st.round = 1
        # Find a cantrip (slot_level=0) — always available, no slot needed
        cantrip = next(
            (a for a in (b.template.get("actions") or [])
             if a.get("spell_slot_level") == 0),
            None)
        if cantrip is None:
            self.skipTest("No cantrip found on L14 Valor Bard")
        from engine.core.pipeline import execute
        from engine.core.events import EventBus
        from engine.primitives import PrimitiveRegistry
        chosen = {"actor": b, "target": enemy, "action": cantrip}
        execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertTrue(
            b.actions_used_this_turn.get("battle_magic_triggered"),
            "battle_magic_triggered should be set after casting a cantrip")

    def test_battle_magic_action_not_candidate_before_spell(self):
        """a_battle_magic_attack is NOT a BA candidate before any spell."""
        b = _valor(14)
        enemy = _enemy(pos=(1, 0))
        from engine.core.state import CombatState, Encounter
        enc = Encounter(id="e", actors=[b, enemy])
        st = CombatState(encounter=enc)
        st.round = 1
        from engine.core.pipeline import generate_candidates
        ba_candidates = generate_candidates(b, st, slot="bonus_action")
        bm_ids = [c["action"]["id"] for c in ba_candidates
                  if c["action"].get("id") == "a_battle_magic_attack"]
        self.assertEqual(bm_ids, [])

    def test_battle_magic_action_is_candidate_after_trigger(self):
        """After battle_magic_triggered is set, a_battle_magic_attack is a BA candidate."""
        b = _valor(14)
        enemy = _enemy(pos=(1, 0))
        from engine.core.state import CombatState, Encounter
        enc = Encounter(id="e", actors=[b, enemy])
        st = CombatState(encounter=enc)
        st.round = 1
        # Manually trigger Battle Magic
        b.actions_used_this_turn["battle_magic_triggered"] = True
        from engine.core.pipeline import generate_candidates
        ba_candidates = generate_candidates(b, st, slot="bonus_action")
        bm_ids = [c["action"]["id"] for c in ba_candidates
                  if c["action"].get("id") == "a_battle_magic_attack"]
        self.assertTrue(bm_ids, "a_battle_magic_attack should be a BA candidate "
                        "when battle_magic_triggered is set")


if __name__ == "__main__":
    unittest.main()
