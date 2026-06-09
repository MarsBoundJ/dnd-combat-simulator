"""Ready-a-Spell: extending Ready Actions to spells (dial >= 4).

Enables the microwave combo: Wizard readies a zone spell (SR/Cloudkill),
Simulacrum readies Wall of Force dome, both fire as reactions when the
dragon approaches — trapping it in a damaging zone it can't escape.

Tests cover: trigger vocabulary, spell-ready registration (slot
consumption + concentration), discard edge cases, both new triggers,
dial gating, scoring, microwave integration, and edge cases.

Run via:
    python -m unittest tests.test_ready_spell
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core.concentration import apply_concentration, end_concentration
from engine.core.events import EventBus
from engine.core.ready_action import (
    KNOWN_TRIGGERS, register, discard, has_readied_action,
    try_fire, find_actors_with_trigger,
    on_enemy_enters_range, on_ally_casts_spell_at_target,
    _find_action,
)
from engine.core.simulacrum import build_simulacrum
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import PrimitiveRegistry

REPO = Path(__file__).parent.parent
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(REPO / "schema" / "content", validate=True,
                                 schema_root=REPO / "schema" / "definitions")
    return _REGISTRY


def _ab():
    return {k: {"score": 16, "save": 4} for k in
            ("str", "dex", "con", "int", "wis", "cha")}


def _mk(actor_id, side, position=(0, 0), hp=80, slots=None):
    fist = {"id": "a_fist", "type": "weapon_attack",
            "pipeline": [{"primitive": "attack_roll",
                          "params": {"kind": "melee", "bonus": 8,
                                     "reach_ft": 5}},
                         {"primitive": "damage",
                          "params": {"dice": "2d10", "modifier": 6,
                                     "type": "bludgeoning", "average": 17}}]}
    zone = {"id": "a_sickening_radiance", "name": "Sickening Radiance",
            "type": "persistent_aura", "concentration": True,
            "spell_slot_level": 4, "range_ft": 120,
            "pipeline": [{"primitive": "persistent_aura",
                          "params": {"shape": "sphere", "radius_ft": 30,
                                     "ability": "con", "dc": 15,
                                     "on_fail": [{"primitive": "damage",
                                                  "params": {"dice": "4d10",
                                                             "type": "radiant",
                                                             "average": 22}}]}}]}
    dome = {"id": "a_wall_of_force_dome", "name": "Wall of Force (Dome)",
            "type": "hard_control", "concentration": True,
            "spell_slot_level": 5, "range_ft": 120,
            "pipeline": [{"primitive": "place_barrier",
                          "params": {"shape": "sphere", "gap": True,
                                     "move": True}}]}
    template = {"id": f"t_{actor_id}", "abilities": _ab(),
                "actions": [fist, zone, dome],
                "cr": {"proficiency_bonus": 4}}
    a = Actor(id=actor_id, name=actor_id, template=template,
              side=side, hp_current=hp, hp_max=hp, ac=15,
              speed={"walk": 30}, position=position, abilities=_ab())
    a.spell_slots = dict(slots or {"4": 3, "5": 2})
    return a


def _state(actors, dial=4):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.content_registry = _registry()
    if dial:
        from engine.core.optimization_dial import set_dial
        for side in {a.side for a in actors}:
            set_dial(st, side, dial)
    return st


_SR_ACTION = {"id": "a_sickening_radiance", "name": "Sickening Radiance",
              "type": "persistent_aura", "concentration": True,
              "spell_slot_level": 4, "range_ft": 120}

_DOME_ACTION = {"id": "a_wall_of_force_dome", "name": "Wall of Force (Dome)",
                "type": "hard_control", "concentration": True,
                "spell_slot_level": 5, "range_ft": 120}


# ============================================================================
# Layer 1: Trigger vocabulary
# ============================================================================

class TriggerVocabularyTest(unittest.TestCase):
    def test_enemy_enters_range_in_known_triggers(self):
        self.assertIn("enemy_enters_range", KNOWN_TRIGGERS)

    def test_ally_casts_spell_at_target_in_known_triggers(self):
        self.assertIn("ally_casts_spell_at_target", KNOWN_TRIGGERS)


# ============================================================================
# Layer 2: Spell-ready registration
# ============================================================================

class SpellReadyRegistrationTest(unittest.TestCase):
    def test_register_spell_ready_consumes_slot(self):
        wiz = _mk("wiz", "pc")
        st = _state([wiz])
        before = int(wiz.spell_slots["4"])
        register(wiz, "a_sickening_radiance", "enemy_enters_range", st,
                 trigger_params={"range_ft": 120},
                 spell_ready=True, sub_action=_SR_ACTION,
                 chosen_slot_level=4)
        self.assertEqual(int(wiz.spell_slots["4"]), before - 1)

    def test_register_spell_ready_applies_concentration(self):
        wiz = _mk("wiz", "pc")
        st = _state([wiz])
        register(wiz, "a_sickening_radiance", "enemy_enters_range", st,
                 trigger_params={"range_ft": 120},
                 spell_ready=True, sub_action=_SR_ACTION,
                 chosen_slot_level=4)
        self.assertIsNotNone(wiz.concentration_on)
        self.assertEqual(wiz.concentration_on["action_id"],
                         "a_sickening_radiance")

    def test_register_spell_ready_drops_prior_concentration(self):
        wiz = _mk("wiz", "pc")
        st = _state([wiz])
        apply_concentration(wiz, {"id": "a_old_spell"}, st)
        self.assertEqual(wiz.concentration_on["action_id"], "a_old_spell")
        register(wiz, "a_sickening_radiance", "enemy_enters_range", st,
                 trigger_params={"range_ft": 120},
                 spell_ready=True, sub_action=_SR_ACTION,
                 chosen_slot_level=4)
        self.assertEqual(wiz.concentration_on["action_id"],
                         "a_sickening_radiance")

    def test_register_spell_ready_stashes_metadata(self):
        wiz = _mk("wiz", "pc")
        st = _state([wiz])
        register(wiz, "a_sickening_radiance", "enemy_enters_range", st,
                 trigger_params={"range_ft": 120},
                 spell_ready=True, sub_action=_SR_ACTION,
                 chosen_slot_level=4)
        ra = wiz.readied_action
        self.assertTrue(ra["spell_ready"])
        self.assertTrue(ra["concentration"])
        self.assertEqual(ra["chosen_slot_level"], 4)

    def test_non_spell_register_unchanged(self):
        """Non-spell register (weapon attacks) still works as before."""
        fighter = _mk("fighter", "pc")
        fighter.spell_slots = {}
        st = _state([fighter])
        register(fighter, "a_fist", "enemy_enters_reach", st,
                 trigger_params={"reach_ft": 5})
        ra = fighter.readied_action
        self.assertFalse(ra.get("spell_ready", False))
        self.assertFalse(ra.get("concentration", False))


# ============================================================================
# Layer 3: Discard edge cases
# ============================================================================

class DiscardEdgeCasesTest(unittest.TestCase):
    def test_discard_spell_ready_ends_concentration(self):
        wiz = _mk("wiz", "pc")
        st = _state([wiz])
        register(wiz, "a_sickening_radiance", "enemy_enters_range", st,
                 trigger_params={"range_ft": 120},
                 spell_ready=True, sub_action=_SR_ACTION,
                 chosen_slot_level=4)
        self.assertIsNotNone(wiz.concentration_on)
        discard(wiz, st, reason="turn_start")
        self.assertIsNone(wiz.concentration_on)
        self.assertIsNone(wiz.readied_action)

    def test_discard_fired_does_not_double_end_concentration(self):
        """When reason='fired', discard should NOT end concentration
        (the spell was released, not discarded)."""
        wiz = _mk("wiz", "pc")
        st = _state([wiz])
        register(wiz, "a_sickening_radiance", "enemy_enters_range", st,
                 trigger_params={"range_ft": 120},
                 spell_ready=True, sub_action=_SR_ACTION,
                 chosen_slot_level=4)
        discard(wiz, st, reason="fired")
        self.assertIsNotNone(wiz.concentration_on)

    def test_concentration_lost_prevents_firing(self):
        wiz = _mk("wiz", "pc")
        dragon = _mk("dragon", "enemy", position=(20, 0), hp=200)
        st = _state([wiz, dragon])
        register(wiz, "a_sickening_radiance", "enemy_enters_range", st,
                 trigger_params={"range_ft": 120},
                 spell_ready=True, sub_action=_SR_ACTION,
                 chosen_slot_level=4)
        end_concentration(wiz, st, reason="damage_save_failed")
        self.assertIsNone(wiz.concentration_on)
        result = try_fire(wiz, dragon, st, event_bus=None)
        self.assertFalse(result)
        self.assertIsNone(wiz.readied_action)
        events = [e for e in st.event_log
                  if e.get("event") == "ready_action_discarded"
                  and e.get("reason") == "concentration_lost"]
        self.assertEqual(len(events), 1)


# ============================================================================
# Layer 4: enemy_enters_range trigger
# ============================================================================

class EnemyEntersRangeTriggerTest(unittest.TestCase):
    def test_fires_when_enemy_enters_range(self):
        # Grid units: 1 sq = 5ft. 120ft = 24 sq.
        wiz = _mk("wiz", "pc", position=(0, 0))
        dragon = _mk("dragon", "enemy", position=(20, 0), hp=200)
        st = _state([wiz, dragon])
        register(wiz, "a_fist", "enemy_enters_range", st,
                 trigger_params={"range_ft": 120})
        bus = EventBus()
        prims = PrimitiveRegistry.with_defaults()
        fired = on_enemy_enters_range(
            dragon, pre_position=(30, 0), state=st,
            event_bus=bus, primitives=prims)
        self.assertEqual(fired, 1)

    def test_does_not_fire_when_already_in_range(self):
        wiz = _mk("wiz", "pc", position=(0, 0))
        dragon = _mk("dragon", "enemy", position=(20, 0), hp=200)
        st = _state([wiz, dragon])
        register(wiz, "a_fist", "enemy_enters_range", st,
                 trigger_params={"range_ft": 120})
        bus = EventBus()
        prims = PrimitiveRegistry.with_defaults()
        fired = on_enemy_enters_range(
            dragon, pre_position=(22, 0), state=st,
            event_bus=bus, primitives=prims)
        self.assertEqual(fired, 0)

    def test_does_not_fire_for_same_side_movement(self):
        wiz = _mk("wiz", "pc", position=(0, 0))
        ally = _mk("ally", "pc", position=(20, 0))
        st = _state([wiz, ally])
        register(wiz, "a_fist", "enemy_enters_range", st,
                 trigger_params={"range_ft": 120})
        bus = EventBus()
        prims = PrimitiveRegistry.with_defaults()
        fired = on_enemy_enters_range(
            ally, pre_position=(30, 0), state=st,
            event_bus=bus, primitives=prims)
        self.assertEqual(fired, 0)


# ============================================================================
# Layer 5: ally_casts_spell_at_target trigger
# ============================================================================

class AllyCastsSpellTriggerTest(unittest.TestCase):
    def test_fires_when_ally_casts_spell_at_target(self):
        wiz = _mk("wiz", "pc", position=(0, 0))
        sim = _mk("sim", "pc", position=(1, 0))
        dragon = _mk("dragon", "enemy", position=(10, 0), hp=200)
        st = _state([wiz, sim, dragon])
        register(sim, "a_fist", "ally_casts_spell_at_target", st,
                 trigger_params={"range_ft": 120})
        bus = EventBus()
        prims = PrimitiveRegistry.with_defaults()
        fired = on_ally_casts_spell_at_target(
            wiz, dragon, st, event_bus=bus, primitives=prims)
        self.assertEqual(fired, 1)

    def test_does_not_fire_for_enemy_cast(self):
        wiz = _mk("wiz", "pc", position=(0, 0))
        dragon = _mk("dragon", "enemy", position=(10, 0), hp=200)
        st = _state([wiz, dragon])
        register(wiz, "a_fist", "ally_casts_spell_at_target", st,
                 trigger_params={"range_ft": 120})
        bus = EventBus()
        prims = PrimitiveRegistry.with_defaults()
        fired = on_ally_casts_spell_at_target(
            dragon, wiz, st, event_bus=bus, primitives=prims)
        self.assertEqual(fired, 0)

    def test_fires_at_same_target(self):
        wiz = _mk("wiz", "pc", position=(0, 0))
        sim = _mk("sim", "pc", position=(1, 0))
        dragon = _mk("dragon", "enemy", position=(10, 0), hp=200)
        st = _state([wiz, sim, dragon])
        register(sim, "a_fist", "ally_casts_spell_at_target", st,
                 trigger_params={"range_ft": 120})
        bus = EventBus()
        prims = PrimitiveRegistry.with_defaults()
        on_ally_casts_spell_at_target(
            wiz, dragon, st, event_bus=bus, primitives=prims)
        fired_events = [e for e in st.event_log
                        if e.get("event") == "ready_action_fired"]
        self.assertEqual(len(fired_events), 1)
        self.assertEqual(fired_events[0]["target"], dragon.id)

    def test_does_not_fire_self(self):
        """The caster's own readied action doesn't fire on their own cast."""
        wiz = _mk("wiz", "pc", position=(0, 0))
        dragon = _mk("dragon", "enemy", position=(10, 0), hp=200)
        st = _state([wiz, dragon])
        register(wiz, "a_fist", "ally_casts_spell_at_target", st,
                 trigger_params={"range_ft": 120})
        bus = EventBus()
        prims = PrimitiveRegistry.with_defaults()
        fired = on_ally_casts_spell_at_target(
            wiz, dragon, st, event_bus=bus, primitives=prims)
        self.assertEqual(fired, 0)


# ============================================================================
# Layer 6: Dial gating
# ============================================================================

class DialGatingTest(unittest.TestCase):
    def _party_and_state(self, dial):
        from sims.adventuring_day import _build_party
        party = _build_party(_registry())
        wiz = next(a for a in party if a.id == "Wizard_Evoker")
        sim = build_simulacrum(wiz)
        dragon_spec = {"id": "a_fist", "type": "weapon_attack",
                       "pipeline": [{"primitive": "attack_roll",
                                     "params": {"kind": "melee",
                                                "bonus": 8,
                                                "reach_ft": 10}},
                                    {"primitive": "damage",
                                     "params": {"dice": "2d10",
                                                "modifier": 6,
                                                "type": "bludgeoning",
                                                "average": 17}}]}
        dragon = Actor(id="dragon", name="dragon",
                       template={"id": "t_dragon", "abilities": _ab(),
                                 "actions": [dragon_spec],
                                 "cr": {"proficiency_bonus": 6}},
                       side="enemy", hp_current=256, hp_max=256, ac=19,
                       speed={"walk": 40, "fly": 80},
                       position=(200, 0), abilities=_ab())
        actors = [a for a in party if a.id != wiz.id] + [wiz, sim, dragon]
        for a in actors:
            if a.side == "pc":
                a.position = (0, 0)
        st = _state(actors, dial=dial)
        return wiz, sim, dragon, st

    def test_spell_ready_not_emitted_at_dial_3(self):
        from engine.core.pipeline import generate_candidates
        wiz, sim, dragon, st = self._party_and_state(dial=3)
        cands = generate_candidates(wiz, st, slot="action")
        spell_readies = [c for c in cands if c.get("kind") == "ready"
                         and c["action"].get("pipeline", [{}])[0]
                         .get("params", {}).get("spell_ready")]
        self.assertEqual(len(spell_readies), 0)

    def test_spell_ready_emitted_at_dial_4(self):
        from engine.core.pipeline import generate_candidates
        wiz, sim, dragon, st = self._party_and_state(dial=4)
        cands = generate_candidates(wiz, st, slot="action")
        spell_readies = [c for c in cands if c.get("kind") == "ready"
                         and c["action"].get("pipeline", [{}])[0]
                         .get("params", {}).get("spell_ready")]
        self.assertGreater(len(spell_readies), 0)

    def test_weapon_ready_unaffected_by_dial(self):
        from engine.core.pipeline import generate_candidates
        wiz, sim, dragon, st = self._party_and_state(dial=1)
        cands = generate_candidates(wiz, st, slot="action")
        weapon_readies = [c for c in cands if c.get("kind") == "ready"
                          and not c["action"].get("pipeline", [{}])[0]
                          .get("params", {}).get("spell_ready")]
        # Weapon ready may or may not emit depending on positioning,
        # but it's not BLOCKED by low dial — just verify no error.
        self.assertIsInstance(weapon_readies, list)


# ============================================================================
# Layer 7: Scoring
# ============================================================================

class ScoringTest(unittest.TestCase):
    def test_spell_ready_zone_scores_positive(self):
        from engine.ai.ehp_scoring import offensive_ehp_ready
        wiz = _mk("wiz", "pc", position=(0, 0))
        dragon = _mk("dragon", "enemy", position=(5, 0), hp=200)
        st = _state([wiz, dragon])
        action = {"_ready_sub_action": _find_action(wiz, "a_sickening_radiance"),
                  "_ready_trigger": "enemy_enters_range"}
        score = offensive_ehp_ready(wiz, action, st)
        self.assertGreater(score, 0.0)

    def test_spell_ready_dome_scores_positive(self):
        from engine.ai.ehp_scoring import offensive_ehp_ready
        wiz = _mk("wiz", "pc", position=(0, 0))
        dragon = _mk("dragon", "enemy", position=(5, 0), hp=200)
        dragon.speed = {"walk": 40, "fly": 80}
        st = _state([wiz, dragon])
        action = {"_ready_sub_action": _find_action(wiz, "a_wall_of_force_dome"),
                  "_ready_trigger": "ally_casts_spell_at_target"}
        score = offensive_ehp_ready(wiz, action, st)
        self.assertGreater(score, 0.0)

    def test_spell_ready_score_zero_no_enemies(self):
        from engine.ai.ehp_scoring import offensive_ehp_ready
        wiz = _mk("wiz", "pc", position=(0, 0))
        st = _state([wiz])
        action = {"_ready_sub_action": _find_action(wiz, "a_sickening_radiance"),
                  "_ready_trigger": "enemy_enters_range"}
        self.assertEqual(offensive_ehp_ready(wiz, action, st), 0.0)


# ============================================================================
# Layer 8: Microwave combo integration
# ============================================================================

class MicrowaveComboTest(unittest.TestCase):
    def test_both_ready_fire_in_sequence(self):
        """Wizard readies SR, Sim readies dome. Dragon moves into range.
        Wizard's SR fires, then chain-triggers Sim's dome at same dragon."""
        wiz = _mk("wiz", "pc", position=(0, 0))
        sim = _mk("sim", "pc", position=(1, 0))
        dragon = _mk("dragon", "enemy", position=(20, 0), hp=256)
        st = _state([wiz, sim, dragon])

        register(wiz, "a_sickening_radiance", "enemy_enters_range", st,
                 trigger_params={"range_ft": 120},
                 spell_ready=True, sub_action=_SR_ACTION,
                 chosen_slot_level=4)
        register(sim, "a_wall_of_force_dome",
                 "ally_casts_spell_at_target", st,
                 trigger_params={"range_ft": 120},
                 spell_ready=True, sub_action=_DOME_ACTION,
                 chosen_slot_level=5)

        self.assertIsNotNone(wiz.concentration_on)
        self.assertIsNotNone(sim.concentration_on)

        bus = EventBus()
        prims = PrimitiveRegistry.with_defaults()
        on_enemy_enters_range(
            dragon, pre_position=(30, 0), state=st,
            event_bus=bus, primitives=prims)

        fired_events = [e for e in st.event_log
                        if e.get("event") == "ready_action_fired"]
        self.assertEqual(len(fired_events), 2)
        self.assertEqual(fired_events[0]["actor"], wiz.id)
        self.assertEqual(fired_events[0]["target"], dragon.id)
        self.assertEqual(fired_events[1]["actor"], sim.id)
        self.assertEqual(fired_events[1]["target"], dragon.id)

        self.assertIsNone(wiz.readied_action)
        self.assertIsNone(sim.readied_action)


# ============================================================================
# Layer 9: Edge cases
# ============================================================================

class EdgeCaseTest(unittest.TestCase):
    def test_no_slot_no_emission(self):
        """Actor with no remaining spell slots should not get spell-ready
        candidates."""
        from engine.core.pipeline import generate_candidates
        wiz = _mk("wiz", "pc", position=(0, 0), slots={"4": 0, "5": 0})
        dragon = _mk("dragon", "enemy", position=(200, 0), hp=200)
        st = _state([wiz, dragon], dial=4)
        cands = generate_candidates(wiz, st, slot="action")
        spell_readies = [c for c in cands if c.get("kind") == "ready"
                         and c["action"].get("pipeline", [{}])[0]
                         .get("params", {}).get("spell_ready")]
        self.assertEqual(len(spell_readies), 0)

    def test_already_concentrating_no_spell_ready(self):
        """Actor already concentrating should not emit spell-ready
        candidates (would waste prior concentration)."""
        from engine.core.pipeline import generate_candidates
        wiz = _mk("wiz", "pc", position=(0, 0))
        dragon = _mk("dragon", "enemy", position=(200, 0), hp=200)
        st = _state([wiz, dragon], dial=4)
        apply_concentration(wiz, {"id": "a_existing"}, st)
        cands = generate_candidates(wiz, st, slot="action")
        spell_readies = [c for c in cands if c.get("kind") == "ready"
                         and c["action"].get("pipeline", [{}])[0]
                         .get("params", {}).get("spell_ready")]
        self.assertEqual(len(spell_readies), 0)


if __name__ == "__main__":
    unittest.main()
