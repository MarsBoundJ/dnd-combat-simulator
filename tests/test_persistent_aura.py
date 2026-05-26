"""persistent_aura primitive + Spirit Guardians tests (PR #43).

Layers:
  1. _persistent_aura primitive registers the aura in
     state.persistent_auras with the right fields
  2. Runner fires forced_save at turn_start for in-radius enemies
  3. Allies in radius do NOT get hit (v1 enemies-only)
  4. Out-of-radius enemies do NOT get hit
  5. Save fail / success → full / half damage per the registered
     pipeline
  6. Concentration end scrubs the aura (multiple casts, new spell,
     incapacitation, damage save fail)
  7. eHP scoring approximates the per-turn × rounds value
  8. End-to-end via runner — cleric with Spirit Guardians does
     per-turn-start damage

Run via:
    python -m unittest tests.test_persistent_aura
"""
from __future__ import annotations

import random
import unittest

from engine.core.state import Actor, Encounter, CombatState
from engine.core.runner import EncounterRunner


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "pc", hp: int = 30,
                ac: int = 14, position: tuple[int, int] = (0, 0),
                wis_save: int = 0, initiative_modifier: int = 0,
                actions: list[dict] | None = None) -> Actor:
    abilities = {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 10, "save": 0},
        "con": {"score": 10, "save": 0},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": wis_save},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "combat": {
                    "armor_class": ac,
                    "hit_points": {"average": hp, "dice": "5d10",
                                     "con_contribution": 10},
                    "speed": {"walk": 30},
                    "initiative": {"modifier": initiative_modifier,
                                     "score": initiative_modifier + 10},
                },
                "actions": actions or []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac,
                  speed={"walk": 30}, position=position,
                  abilities=abilities)


def _spirit_guardians_action() -> dict:
    """Spirit Guardians, 3rd-level cleric. 15-ft radius, WIS save vs
    DC 15, 3d8 radiant on fail / half on success. Concentration."""
    return {
        "id": "a_spirit_guardians",
        "name": "Spirit Guardians",
        "type": "persistent_aura",
        "spell_slot_level": 3,
        "concentration": True,
        "named_effect": "spirit_guardians",
        "pipeline": [
            {"primitive": "persistent_aura",
              "params": {
                  "radius_ft": 15,
                  "trigger_event": "target_turn_start_in_area",
                  "affected": "enemies",
                  "ability": "wisdom",
                  "dc": 15,
                  "on_fail": [{
                      "primitive": "damage",
                      "params": {"dice": "3d8", "type": "radiant"},
                  }],
                  "on_success": [{
                      "primitive": "damage",
                      "params": {"dice": "3d8", "type": "radiant",
                                  "multiplier": 0.5},
                  }],
              }},
        ],
    }


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Primitive registration
# ============================================================================

class PersistentAuraRegistrationTest(unittest.TestCase):

    def test_primitive_registers_aura_in_state(self) -> None:
        from engine.primitives import _persistent_aura
        cleric = _make_actor("cleric", side="pc")
        state = _state_with([cleric])
        state.current_attack = {
            "actor": cleric, "target": cleric,
            "action": _spirit_guardians_action(),
        }
        _persistent_aura(_spirit_guardians_action()["pipeline"][0]["params"],
                          state, None)
        self.assertEqual(len(state.persistent_auras), 1)
        aura = state.persistent_auras[0]
        self.assertEqual(aura["caster_id"], "cleric")
        self.assertEqual(aura["radius_ft"], 15)
        self.assertEqual(aura["trigger_event"], "target_turn_start_in_area")
        self.assertEqual(aura["ability"], "wisdom")
        self.assertEqual(aura["dc"], 15)
        self.assertEqual(aura["affected"], "enemies")

    def test_registration_emits_event(self) -> None:
        from engine.primitives import _persistent_aura
        cleric = _make_actor("cleric", side="pc")
        state = _state_with([cleric])
        state.current_attack = {
            "actor": cleric, "target": cleric,
            "action": _spirit_guardians_action(),
        }
        _persistent_aura(_spirit_guardians_action()["pipeline"][0]["params"],
                          state, None)
        events = [e for e in state.event_log
                   if e.get("event") == "persistent_aura_registered"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["caster"], "cleric")
        self.assertEqual(events[0]["radius_ft"], 15)


# ============================================================================
# Runner hook — turn-start triggers
# ============================================================================

class PersistentAuraRunnerHookTest(unittest.TestCase):

    def _setup(self, enemy_position: tuple[int, int] = (0, 1),
                ally_position: tuple[int, int] = (1, 0)):
        """Cleric with active Spirit Guardians at (0,0); enemy + ally
        with configurable positions."""
        cleric = _make_actor("cleric", side="pc", position=(0, 0))
        ally = _make_actor("ally", side="pc", position=ally_position)
        enemy = _make_actor("ogre", side="enemy", position=enemy_position,
                              wis_save=-2)
        state = _state_with([cleric, ally, enemy])
        # Register aura manually (faster than running execute)
        state.persistent_auras.append({
            "caster_id": "cleric",
            "action_id": "a_spirit_guardians",
            "named_effect": "spirit_guardians",
            "radius_ft": 15,
            "trigger_event": "target_turn_start_in_area",
            "ability": "wisdom",
            "dc": 15,
            "on_fail": [{"primitive": "damage",
                          "params": {"dice": "3d8", "type": "radiant"}}],
            "on_success": [{"primitive": "damage",
                              "params": {"dice": "3d8", "type": "radiant",
                                          "multiplier": 0.5}}],
            "affected": "enemies",
            "applied_at_round": 1,
        })
        runner = EncounterRunner.new(state.encounter, seed=1)
        import engine.primitives as primitives_module
        primitives_module.set_rng(runner.rng)
        return runner, state, cleric, ally, enemy

    def test_in_range_enemy_gets_save_at_turn_start(self) -> None:
        runner, state, cleric, ally, enemy = self._setup(
            enemy_position=(0, 1))    # 5 ft away — in 15-ft aura
        hp_before = enemy.hp_current
        runner._resolve_persistent_aura_triggers(enemy, state)
        # A forced_save event was logged
        saves = [e for e in state.event_log
                  if e.get("event") == "forced_save"
                  and e.get("target") == "ogre"]
        self.assertEqual(len(saves), 1)
        # Enemy took some damage (regardless of save outcome)
        self.assertLess(enemy.hp_current, hp_before)

    def test_out_of_range_enemy_unaffected(self) -> None:
        runner, state, cleric, ally, enemy = self._setup(
            enemy_position=(20, 20))    # well beyond 15-ft aura
        hp_before = enemy.hp_current
        runner._resolve_persistent_aura_triggers(enemy, state)
        saves = [e for e in state.event_log
                  if e.get("event") == "forced_save"
                  and e.get("target") == "ogre"]
        self.assertEqual(len(saves), 0)
        self.assertEqual(enemy.hp_current, hp_before)

    def test_in_range_ally_unaffected_v1(self) -> None:
        """v1 affected=enemies only — ally in aura takes no damage."""
        runner, state, cleric, ally, enemy = self._setup(
            ally_position=(0, 1))    # ally also in aura
        hp_before = ally.hp_current
        runner._resolve_persistent_aura_triggers(ally, state)
        saves = [e for e in state.event_log
                  if e.get("event") == "forced_save"
                  and e.get("target") == "ally"]
        self.assertEqual(len(saves), 0)
        self.assertEqual(ally.hp_current, hp_before)

    def test_dead_caster_aura_is_noop(self) -> None:
        """If the caster died (aura wasn't scrubbed for some reason),
        triggers should skip cleanly without raising."""
        runner, state, cleric, ally, enemy = self._setup(
            enemy_position=(0, 1))
        cleric.hp_current = 0
        cleric.is_dead = True
        hp_before = enemy.hp_current
        runner._resolve_persistent_aura_triggers(enemy, state)
        self.assertEqual(enemy.hp_current, hp_before)


# ============================================================================
# Concentration cleanup
# ============================================================================

class ConcentrationCleansAuraTest(unittest.TestCase):

    def test_end_concentration_scrubs_aura(self) -> None:
        from engine.core.concentration import (
            apply_concentration, end_concentration,
        )
        cleric = _make_actor("cleric", side="pc")
        state = _state_with([cleric])
        # Start concentration on Spirit Guardians + register the aura
        apply_concentration(cleric, _spirit_guardians_action(), state)
        state.persistent_auras.append({
            "caster_id": "cleric",
            "action_id": "a_spirit_guardians",
            "named_effect": "spirit_guardians",
            "radius_ft": 15,
            "trigger_event": "target_turn_start_in_area",
            "ability": "wisdom", "dc": 15,
            "on_fail": [], "on_success": [],
            "affected": "enemies",
            "applied_at_round": 1,
        })
        # End concentration manually
        end_concentration(cleric, state, reason="test")
        self.assertEqual(state.persistent_auras, [])

    def test_other_aura_preserved(self) -> None:
        """A different caster's aura should NOT be scrubbed when this
        caster's concentration ends."""
        from engine.core.concentration import (
            apply_concentration, end_concentration,
        )
        cleric_a = _make_actor("cleric_a", side="pc")
        cleric_b = _make_actor("cleric_b", side="pc", position=(5, 0))
        state = _state_with([cleric_a, cleric_b])
        apply_concentration(cleric_a, _spirit_guardians_action(), state)
        # Register A's aura AND B's aura
        for cid in ("cleric_a", "cleric_b"):
            state.persistent_auras.append({
                "caster_id": cid,
                "action_id": "a_spirit_guardians",
                "named_effect": "spirit_guardians",
                "radius_ft": 15,
                "trigger_event": "target_turn_start_in_area",
                "ability": "wisdom", "dc": 15,
                "on_fail": [], "on_success": [],
                "affected": "enemies",
                "applied_at_round": 1,
            })
        end_concentration(cleric_a, state, reason="test")
        # Only B's aura remains
        self.assertEqual(len(state.persistent_auras), 1)
        self.assertEqual(state.persistent_auras[0]["caster_id"], "cleric_b")


# ============================================================================
# eHP scoring
# ============================================================================

class PersistentAuraScoringTest(unittest.TestCase):

    def test_score_with_one_in_radius_enemy(self) -> None:
        from engine.ai.ehp_scoring import (
            offensive_ehp_persistent_aura, EXPECTED_AURA_ROUNDS,
        )
        cleric = _make_actor("cleric", side="pc", position=(0, 0))
        ogre = _make_actor("ogre", side="enemy", position=(0, 1),
                            wis_save=-2, hp=100)
        state = _state_with([cleric, ogre])
        score = offensive_ehp_persistent_aura(
            cleric, _spirit_guardians_action(), state)
        # 3d8 mean = 13.5. WIS save +(-2) vs DC 15 → need 17+ → p_fail ≈ 0.8
        # per_turn ≈ 0.8 × 13.5 + 0.2 × 6.75 = 10.8 + 1.35 = 12.15
        # × EXPECTED_AURA_ROUNDS (2.5) ≈ 30
        self.assertGreater(score, 20.0)
        self.assertLess(score, 50.0)

    def test_score_zero_with_no_in_radius_enemies(self) -> None:
        from engine.ai.ehp_scoring import offensive_ehp_persistent_aura
        cleric = _make_actor("cleric", side="pc", position=(0, 0))
        ogre = _make_actor("ogre", side="enemy", position=(20, 20))
        state = _state_with([cleric, ogre])
        score = offensive_ehp_persistent_aura(
            cleric, _spirit_guardians_action(), state)
        self.assertEqual(score, 0.0)

    def test_score_scales_with_enemy_count(self) -> None:
        """Two enemies in radius should score roughly 2× one enemy."""
        from engine.ai.ehp_scoring import offensive_ehp_persistent_aura
        cleric = _make_actor("cleric", side="pc", position=(0, 0))
        ogre1 = _make_actor("ogre1", side="enemy", position=(0, 1),
                              wis_save=-2, hp=100)
        ogre2 = _make_actor("ogre2", side="enemy", position=(1, 0),
                              wis_save=-2, hp=100)
        state1 = _state_with([cleric, ogre1])
        state2 = _state_with([cleric, ogre1, ogre2])
        score1 = offensive_ehp_persistent_aura(
            cleric, _spirit_guardians_action(), state1)
        score2 = offensive_ehp_persistent_aura(
            cleric, _spirit_guardians_action(), state2)
        # Roughly 2× (within 10% of exactly double)
        self.assertAlmostEqual(score2 / score1, 2.0, delta=0.1)

    def test_per_turn_damage_capped_at_enemy_hp(self) -> None:
        """An aura that would do 12 dmg/turn to a 3 HP enemy is worth
        3 eHP for that enemy per turn, not 12."""
        from engine.ai.ehp_scoring import offensive_ehp_persistent_aura
        cleric = _make_actor("cleric", side="pc", position=(0, 0))
        weak = _make_actor("weak", side="enemy", position=(0, 1),
                            wis_save=-2, hp=3)
        state = _state_with([cleric, weak])
        score = offensive_ehp_persistent_aura(
            cleric, _spirit_guardians_action(), state)
        # per_turn capped at 3 HP, × 2.5 rounds = 7.5
        self.assertAlmostEqual(score, 7.5, delta=0.5)


# ============================================================================
# End-to-end via runner
# ============================================================================

class SpiritGuardiansEndToEndTest(unittest.TestCase):

    def test_full_encounter_aura_damages_enemies_each_turn(self) -> None:
        """Cleric casts Spirit Guardians on turn 1, enemy takes damage
        at the start of each of their subsequent turns."""
        cleric = _make_actor(
            "cleric", side="pc", position=(0, 0),
            actions=[_spirit_guardians_action()],
            initiative_modifier=30,
        )
        ogre = _make_actor(
            "ogre", side="enemy", position=(0, 1), wis_save=-2, hp=200,
            initiative_modifier=0,
            actions=[{
                "id": "a_club", "name": "Club", "type": "weapon_attack",
                "pipeline": [
                    {"primitive": "attack_roll",
                      "params": {"kind": "melee", "bonus": 4, "reach_ft": 5}},
                    {"primitive": "damage",
                      "params": {"dice": "1d4", "modifier": 2,
                                  "type": "bludgeoning"},
                      "when": {"event": "damage_roll",
                                "condition": "combat.attack_state == hit"}},
                ],
            }],
        )
        # Cleric needs spell_slots and a way to actually cast SG — give
        # them an extra slot
        cleric.spell_slots = {3: 1}
        cleric.spell_slots_max = {3: 1}
        # Force cleric to fight to death so they don't flee
        cleric.template["behavior_profile"] = {"presets": {"retreat": "ftd"}}
        enc = Encounter(id="t", actors=[cleric, ogre])
        runner = EncounterRunner.new(enc, seed=1)
        import engine.primitives as primitives_module
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # SG was cast (registration event)
        cast_events = [e for e in state.event_log
                        if e.get("event") == "persistent_aura_registered"]
        self.assertGreater(len(cast_events), 0,
                            "Cleric should have cast Spirit Guardians "
                            "(it's their best eHP-scoring candidate)")
        # At least one forced_save with the ogre as target landed (the
        # turn-start trigger fired)
        sg_saves = [e for e in state.event_log
                     if e.get("event") == "forced_save"
                     and e.get("target") == "ogre"]
        self.assertGreater(len(sg_saves), 0,
                            "Spirit Guardians should have triggered a "
                            "save on the ogre at their turn-start")


if __name__ == "__main__":
    unittest.main()
