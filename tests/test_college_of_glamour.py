"""College of Glamour tests (Bard subclass, PHB 2024).

  - Mantle of Inspiration (L3): BA — expend BI, grant up to CHA-mod allies
    within 60 ft Temp HP = 2× the Bardic die roll.
  - Beguiling Magic (L3): after casting an Enchantment/Illusion spell with a
    slot, force a WIS save on an enemy within 60 ft → Charmed (1/long rest).
  - Unbreakable Majesty (L14): the first attack to hit the Bard each turn
    forces the attacker's CHA save vs the Bard spell DC or misses.
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import college_of_glamour as G
from engine.core.events import EventBus
from engine.core.pipeline import execute
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template, derive_pc_resources

_REPO = Path(__file__).resolve().parent.parent
_REG = None


def _reg():
    global _REG
    if _REG is None:
        _REG = load_content(_REPO / "schema" / "content", validate=True,
                            schema_root=_REPO / "schema")
    return _REG


def _ab(cha=18):
    d = {k: {"score": 10, "save": 0}
         for k in ("str", "dex", "con", "int", "wis", "cha")}
    from engine.core.state import ability_modifier
    d["cha"] = {"score": cha, "save": ability_modifier(cha)}
    return d


def _glamour(level, cha=18):
    spec = {"id": "b", "class": "c_bard", "level": level,
            "subclass": "sc_college_of_glamour",
            "ability_scores": {"str": 8, "dex": 14, "con": 12,
                               "int": 10, "wis": 12, "cha": cha}}
    tmpl = build_pc_template(spec, _reg())
    res = derive_pc_resources(spec, _reg())
    b = Actor(id="b", name="b", template=tmpl, side="pc", hp_current=30,
              hp_max=30, ac=14, position=(0, 0), speed={"walk": 30},
              abilities=_ab(cha))
    b.resources = dict(res)
    return b


def _enemy(aid="foe", pos=(2, 0), wis_save=0, cha_save=0):
    ab = _ab()
    ab["wis"] = {"score": 10, "save": wis_save}
    ab["cha"] = {"score": 10, "save": cha_save}
    return Actor(id=aid, name=aid,
                 template={"id": f"t_{aid}", "name": aid, "abilities": ab,
                           "cr": {"proficiency_bonus": 2}, "actions": []},
                 side="enemy", hp_current=40, hp_max=40, ac=12,
                 position=pos, speed={"walk": 30}, abilities=ab)


def _ally(aid, hp=20, pos=(1, 0)):
    ab = _ab()
    return Actor(id=aid, name=aid,
                 template={"id": f"t_{aid}", "name": aid, "abilities": ab,
                           "cr": {"proficiency_bonus": 2}, "actions": []},
                 side="pc", hp_current=hp, hp_max=40, ac=12,
                 position=pos, speed={"walk": 30}, abilities=ab)


class MantleOfInspirationTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def test_grants_temp_hp_to_up_to_cha_mod_allies(self):
        b = _glamour(3, cha=18)   # CHA +4 → up to 4 allies
        allies = [_ally(f"a{i}", hp=10 + i) for i in range(6)]
        st = CombatState(encounter=Encounter(id="e", actors=[b] + allies))
        st.turn_order = ["b"]
        st.round = 1
        st.current_attack = {"actor": b, "target": b}
        primitives_module._mantle_of_inspiration({}, st, EventBus())
        buffed = [a for a in allies if a.temp_hp > 0]
        self.assertEqual(len(buffed), 4)

    def test_temp_hp_is_twice_the_roll(self):
        b = _glamour(3, cha=12)   # CHA +1 → 1 ally
        ally = _ally("a")
        st = CombatState(encounter=Encounter(id="e", actors=[b, ally]))
        st.turn_order = ["b"]
        st.round = 1
        st.current_attack = {"actor": b, "target": b}
        primitives_module._mantle_of_inspiration({}, st, EventBus())
        moi = [e for e in st.event_log
               if e.get("event") == "mantle_of_inspiration"][0]
        self.assertEqual(ally.temp_hp, 2 * moi["roll"])

    def test_action_on_template(self):
        self.assertTrue(any(a.get("id") == "a_mantle_of_inspiration"
                            for a in _glamour(3).template["actions"]))


class BeguilingMagicTest(unittest.TestCase):

    def _cast_hold_person(self, b, target, others, seed):
        prims = primitives_module.PrimitiveRegistry.with_defaults()
        hp_act = [a for a in b.template["actions"]
                  if a.get("id") == "a_hold_person"][0]
        b.spell_slots = {1: 4, 2: 3}
        b.spell_slots_max = dict(b.spell_slots)
        st = CombatState(encounter=Encounter(id="e",
                                              actors=[b, target] + others))
        st.turn_order = ["b"]
        st.round = 1
        st.content_registry = _reg()
        primitives_module.set_rng(random.Random(seed))
        execute({"actor": b, "action": hp_act, "target": target}, st,
                EventBus(), prims)
        return st

    def test_school_propagated_to_action(self):
        b = _glamour(5)
        hp_act = [a for a in b.template["actions"]
                  if a.get("id") == "a_hold_person"][0]
        self.assertEqual(hp_act.get("school"), "enchantment")

    def test_fires_after_enchantment_cast_and_charms_on_fail(self):
        b = _glamour(5)
        foe = _enemy(wis_save=-100)   # always fails the WIS save
        st = self._cast_hold_person(b, foe, [], seed=1)
        self.assertTrue(any(e.get("event") == "beguiling_magic"
                            for e in st.event_log))
        self.assertTrue(any(c.get("condition_id") == "co_charmed"
                            for c in foe.applied_conditions))

    def test_spends_one_use_and_is_once_per_rest(self):
        b = _glamour(5)
        foe = _enemy(wis_save=-100)
        self._cast_hold_person(b, foe, [], seed=1)
        self.assertEqual(b.resources["beguiling_magic_uses_remaining"], 0)
        # Second cast: no further beguiling.
        foe2 = _enemy("foe2", wis_save=-100)
        st2 = self._cast_hold_person(b, foe2, [], seed=2)
        self.assertFalse(any(e.get("event") == "beguiling_magic"
                             for e in st2.event_log))

    def test_seeded(self):
        # Resource seeding present at L3.
        res = derive_pc_resources(
            {"id": "b", "class": "c_bard", "level": 3,
             "subclass": "sc_college_of_glamour",
             "ability_scores": {"str": 8, "dex": 14, "con": 12,
                                "int": 10, "wis": 12, "cha": 18}}, _reg())
        self.assertEqual(res.get("beguiling_magic_uses_remaining"), 1)


class MantleOfMajestyTest(unittest.TestCase):

    def setUp(self):
        primitives_module.set_rng(random.Random(1))

    def _state(self, b, foes):
        st = CombatState(encounter=Encounter(id="e", actors=[b] + foes))
        st.turn_order = ["b"] + [f.id for f in foes]
        st.round = 1
        st.content_registry = _reg()
        return st

    def test_command_on_bard_list(self):
        self.assertTrue(any(a.get("id") == "a_command"
                            for a in _glamour(6).template["actions"]))

    def test_actions_and_resource_present(self):
        b = _glamour(6)
        ids = [a.get("id") for a in b.template["actions"]]
        self.assertIn("a_mantle_of_majesty", ids)
        self.assertIn("a_mantle_of_majesty_command", ids)
        self.assertEqual(b.resources["mantle_of_majesty_uses_remaining"], 1)

    def test_activation_casts_command_and_sets_active(self):
        b = _glamour(6)
        foe = _enemy(wis_save=-10)
        st = self._state(b, [foe])
        st.current_attack = {"actor": b, "target": b}
        primitives_module._mantle_of_majesty_activate({}, st, EventBus())
        self.assertTrue(b.mantle_of_majesty_active)
        self.assertTrue(any(c.get("condition_id") == "co_incapacitated"
                            for c in foe.applied_conditions))

    def test_sustained_command_gated_on_active(self):
        from engine.core.pipeline import generate_candidates
        b = _glamour(6)
        foe = _enemy(wis_save=-10)
        st = self._state(b, [foe])
        before = [c for c in generate_candidates(b, st, "bonus_action")
                  if c["action"].get("id") == "a_mantle_of_majesty_command"]
        self.assertEqual(len(before), 0)
        b.mantle_of_majesty_active = True
        after = [c for c in generate_candidates(b, st, "bonus_action")
                 if c["action"].get("id") == "a_mantle_of_majesty_command"]
        self.assertEqual(len(after), 1)

    def test_charmed_target_auto_fails(self):
        b = _glamour(6)
        # High-WIS foe that would normally save, but Charmed by the Bard.
        foe = _enemy(wis_save=10)
        foe.applied_conditions.append({"condition_id": "co_charmed",
                                        "source_id": "b"})
        st = self._state(b, [foe])
        G.cast_mantle_command(b, st, EventBus())
        self.assertTrue(any(c.get("condition_id") == "co_incapacitated"
                            for c in foe.applied_conditions))

    def test_long_rest_refreshes(self):
        from engine.core.rest import apply_long_rest
        b = _glamour(6)
        b.resources["mantle_of_majesty_uses_remaining"] = 0
        apply_long_rest(b, CombatState(encounter=Encounter(id="e", actors=[b])))
        self.assertEqual(b.resources["mantle_of_majesty_uses_remaining"], 1)


class UnbreakableMajestyTest(unittest.TestCase):

    def _bard_and_foe(self, cha_save=0):
        b = _glamour(14, cha=20)
        foe = _enemy(cha_save=cha_save)
        st = CombatState(encounter=Encounter(id="e", actors=[b, foe]))
        st.turn_order = ["foe", "b"]
        st.round = 1
        return b, foe, st

    def test_action_on_template_and_seeded(self):
        b = _glamour(14)
        self.assertTrue(any(a.get("id") == "a_unbreakable_majesty"
                            for a in b.template["actions"]))
        self.assertEqual(b.resources["unbreakable_majesty_uses_remaining"], 1)

    def test_negates_first_hit_when_attacker_fails(self):
        b, foe, st = self._bard_and_foe(cha_save=-100)   # always fails
        G.activate_unbreakable_majesty(b, st)
        b._majesty_negated_this_turn = False
        self.assertTrue(G.majesty_negates_hit(b, foe, st, random.Random(1)))

    def test_no_negation_when_attacker_succeeds(self):
        b, foe, st = self._bard_and_foe(cha_save=100)   # always saves
        G.activate_unbreakable_majesty(b, st)
        b._majesty_negated_this_turn = False
        self.assertFalse(G.majesty_negates_hit(b, foe, st, random.Random(1)))

    def test_only_first_hit_per_turn(self):
        b, foe, st = self._bard_and_foe(cha_save=-100)
        G.activate_unbreakable_majesty(b, st)
        b._majesty_negated_this_turn = False
        self.assertTrue(G.majesty_negates_hit(b, foe, st, random.Random(1)))
        # Second hit same turn → not negated.
        self.assertFalse(G.majesty_negates_hit(b, foe, st, random.Random(1)))

    def test_inactive_no_negation(self):
        b, foe, st = self._bard_and_foe(cha_save=-100)
        b._majesty_negated_this_turn = False
        self.assertFalse(G.majesty_negates_hit(b, foe, st, random.Random(1)))

    def test_incapacitated_drops_presence(self):
        b, foe, st = self._bard_and_foe(cha_save=-100)
        G.activate_unbreakable_majesty(b, st)
        b.applied_conditions.append({"condition_id": "co_incapacitated"})
        b._majesty_negated_this_turn = False
        self.assertFalse(G.majesty_negates_hit(b, foe, st, random.Random(1)))
        self.assertFalse(b.unbreakable_majesty_active)

    def test_short_rest_refreshes(self):
        from engine.core.rest import apply_short_rest
        b = _glamour(14)
        b.resources["unbreakable_majesty_uses_remaining"] = 0
        st = CombatState(encounter=Encounter(id="e", actors=[b]))
        apply_short_rest(b, st)
        self.assertEqual(b.resources["unbreakable_majesty_uses_remaining"], 1)


if __name__ == "__main__":
    unittest.main()
