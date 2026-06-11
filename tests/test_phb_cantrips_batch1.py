"""PHB-2024-only cantrip batch 1 — Blade Ward, Mind Sliver, Thorn Whip,
Thunderclap, Word of Radiance (+ the Friends non-combat stub).

Covers the two new engine pieces shipped with this batch:
  - the aoe_save_cantrip pc_builder kind (self-emanation save cantrips,
    caster excluded per the 2024 Emanation rule);
  - the forced_save `affected: enemies_in_area` option ("each creature
    of your choice" — Word of Radiance spares allies, Thunderclap
    doesn't).
"""
from __future__ import annotations

import unittest

from engine.core import pipeline
from engine.core.events import EventBus
from engine.pc_schema import (
    _build_aoe_save_cantrip_action,
    _build_attack_cantrip_action,
    _build_save_cantrip_action,
    _dispatch_pc_builder,
)
from engine.primitives import PrimitiveRegistry, _resolve_save_targets

from tests._srd_helpers import (
    action_template, ally, caster, enemy, registry, state,
)


def _abil(**kw):
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    for k, v in kw.items():
        ab[k] = {"score": v, "save": 0}
    return ab


def _thunderclap(level=1):
    return _build_aoe_save_cantrip_action(
        "a_thunderclap", "Thunderclap", level,
        save_ability="constitution", damage_type="thunder", die=6,
        emanation_ft=5, affected="all_creatures_in_area")


def _word_of_radiance(level=1):
    return _build_aoe_save_cantrip_action(
        "a_word_of_radiance", "Word of Radiance", level,
        save_ability="constitution", damage_type="radiant", die=6,
        emanation_ft=5, affected="enemies_in_area")


def _aoe_state(action, *, with_ally=False):
    """Caster at (0,0), enemy adjacent at (1,0); optional ally at (0,1).
    current_attack primed as the AoE execution path does."""
    c = caster(position=(0, 0))
    foe = enemy(position=(1, 0), con=-20)   # always fails the CON save
    actors = [c, foe]
    if with_ally:
        actors.append(ally(position=(0, 1), hp=20, hp_max=20))
    st = state(actors)
    st.current_attack = {"actor": c, "action": action,
                          "area_origin": tuple(c.position)}
    st.turn_order = [a.id for a in actors]
    return st, c, foe


class TestRegistryLoads(unittest.TestCase):
    """All six batch files load + validate."""

    def test_features_present(self):
        reg = registry()
        for fid in ("f_blade_ward", "f_friends", "f_mind_sliver",
                     "f_thorn_whip", "f_thunderclap", "f_word_of_radiance"):
            self.assertIsNotNone(reg.get("feature", fid), fid)

    def test_friends_is_inert_stub(self):
        f = registry().get("feature", "f_friends")
        self.assertNotIn("action_template", f)
        self.assertNotIn("pc_builder", f)


class TestMindSliver(unittest.TestCase):
    def test_pc_builder_dispatch(self):
        f = registry().get("feature", "f_mind_sliver")
        a = _dispatch_pc_builder(f, 1, _abil(cha=16), 2, "c_sorcerer")
        self.assertEqual(a["id"], "a_mind_sliver")
        self.assertEqual(a["type"], "save_attack")
        self.assertEqual(a["save_ability"], "intelligence")
        self.assertEqual(a["spell_slot_level"], 0)

    def test_dice_scale_with_character_level(self):
        for lvl, n in ((1, 1), (5, 2), (11, 3), (17, 4)):
            a = _build_save_cantrip_action(
                "a_mind_sliver", "Mind Sliver", lvl,
                save_ability="intelligence", damage_type="psychic",
                die=6, range_ft=60)
            dmg = a["pipeline"][0]["params"]["on_fail"][0]["params"]
            self.assertEqual(dmg["dice"], f"{n}d6")
            self.assertEqual(dmg["type"], "psychic")


class TestThornWhip(unittest.TestCase):
    def test_melee_spell_attack_at_30ft(self):
        a = _build_attack_cantrip_action(
            "a_thorn_whip", "Thorn Whip", 5, _abil(wis=16), 3, "c_druid",
            damage_type="piercing", die=6, range_ft=30,
            attack_kind="melee")
        atk = a["pipeline"][0]["params"]
        self.assertEqual(atk["kind"], "melee")
        self.assertEqual(atk["reach_ft"], 30)
        self.assertEqual(atk["bonus"], 3 + 3)   # WIS mod + PB
        dmg = a["pipeline"][1]["params"]
        self.assertEqual(dmg["dice"], "2d6")    # character level 5

    def test_pc_builder_dispatch(self):
        f = registry().get("feature", "f_thorn_whip")
        a = _dispatch_pc_builder(f, 1, _abil(wis=16), 2, "c_druid")
        self.assertEqual(a["id"], "a_thorn_whip")
        self.assertEqual(a["pipeline"][0]["params"]["kind"], "melee")


class TestEmanationTargeting(unittest.TestCase):
    """forced_save target resolution for the emanation cantrips."""

    def _targets(self, action, with_ally):
        st, c, foe = _aoe_state(action, with_ally=with_ally)
        params = action["pipeline"][0]["params"]
        return st, [t.id for t in _resolve_save_targets(params, st)]

    def test_caster_excluded_from_own_emanation(self):
        st, ids = self._targets(_thunderclap(), with_ally=False)
        self.assertEqual(ids, ["foe"])

    def test_thunderclap_hits_adjacent_ally(self):
        st, ids = self._targets(_thunderclap(), with_ally=True)
        self.assertCountEqual(ids, ["foe", "ally"])

    def test_word_of_radiance_spares_ally(self):
        st, ids = self._targets(_word_of_radiance(), with_ally=True)
        self.assertEqual(ids, ["foe"])

    def test_out_of_emanation_enemy_untouched(self):
        action = _thunderclap()
        c = caster(position=(0, 0))
        near = enemy(eid="near", position=(1, 0))
        far = enemy(eid="far", position=(4, 0))   # 20 ft away
        st = state([c, near, far])
        st.current_attack = {"actor": c, "action": action,
                              "area_origin": (0, 0)}
        ids = [t.id for t in _resolve_save_targets(
            action["pipeline"][0]["params"], st)]
        self.assertEqual(ids, ["near"])


class TestEmanationExecution(unittest.TestCase):
    def _chosen(self, action, st, c, foe):
        return {"kind": "aoe_attack", "action": action, "target": foe,
                 "origin_point": tuple(c.position), "actor": c}

    def test_failed_save_takes_thunder_damage(self):
        action = _thunderclap()
        st, c, foe = _aoe_state(action)
        hp0 = foe.hp_current
        pipeline.execute(self._chosen(action, st, c, foe), st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        self.assertLess(foe.hp_current, hp0)
        self.assertEqual(c.hp_current, c.hp_max)   # caster untouched

    def test_word_of_radiance_never_damages_ally(self):
        action = _word_of_radiance()
        st, c, foe = _aoe_state(action, with_ally=True)
        buddy = next(a for a in st.encounter.actors if a.id == "ally")
        hp0 = buddy.hp_current
        pipeline.execute(self._chosen(action, st, c, foe), st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        self.assertEqual(buddy.hp_current, hp0)
        self.assertLess(foe.hp_current, foe.hp_max)


class TestEmanationScoring(unittest.TestCase):
    """offensive_ehp_aoe drives whether the AI ever swings these."""

    def _score(self, action, with_ally):
        from engine.ai.ehp_scoring import offensive_ehp_aoe
        st, c, foe = _aoe_state(action, with_ally=with_ally)
        return offensive_ehp_aoe(c, (0, 0), action, st)

    def test_thunderclap_positive_vs_adjacent_enemy(self):
        self.assertGreater(self._score(_thunderclap(), False), 0.0)

    def test_thunderclap_pays_friendly_fire(self):
        alone = self._score(_thunderclap(), False)
        crowded = self._score(_thunderclap(), True)
        self.assertLess(crowded, alone)

    def test_word_of_radiance_ignores_ally(self):
        alone = self._score(_word_of_radiance(), False)
        crowded = self._score(_word_of_radiance(), True)
        self.assertAlmostEqual(crowded, alone)

    def test_positioner_places_emanation_on_caster(self):
        from engine.ai.positioning import max_aoe_coverage
        action = _thunderclap()
        st, c, foe = _aoe_state(action)
        best = max_aoe_coverage(action, c, st)
        self.assertIsNotNone(best)
        # range_ft 0 forbids enemy-anchored origins — only the caster's
        # own square remains for an emanation.
        self.assertEqual(tuple(best["origin"]), (0, 0))


class TestBladeWard(unittest.TestCase):
    def test_template_shape(self):
        t = action_template("f_blade_ward")
        self.assertEqual(t["type"], "defensive_buff")
        self.assertEqual(t["spell_slot_level"], 0)
        self.assertTrue(t["concentration"])
        step = t["pipeline"][0]
        self.assertEqual(step["params"]["target"], "self")
        self.assertEqual(step["params"]["modifier"], "ac_modifier")
        self.assertEqual(step["params"]["value"], 2)

    def test_execution_applies_self_ac_modifier(self):
        t = action_template("f_blade_ward")
        c = caster(position=(0, 0))
        st = state([c, enemy(position=(2, 0))])
        chosen = {"kind": "defensive_buff", "action": t, "target": c,
                   "actor": c}
        pipeline.execute(chosen, st, EventBus(),
                          PrimitiveRegistry.with_defaults())
        mods = [m for m in c.active_modifiers
                if m.get("primitive") == "attack_modifier"
                and m["params"].get("modifier") == "ac_modifier"]
        self.assertEqual(len(mods), 1)
        self.assertEqual(mods[0]["params"]["value"], 2)


if __name__ == "__main__":
    unittest.main()
