"""AI decision layer v1 tests — Targeting dial (5 presets) + ability selection.

Tests two layers:
  1. Unit tests — pure-function tests of each targeting preset
  2. Integration tests — full encounter runs verifying behavior

Run via:
    python -m unittest tests.test_ai_v1
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

from engine import primitives as primitives_module
from engine.ai import (
    pick_target, pick_action,
    resolve_targeting_preset, resolve_ability_selection_preset,
    resolve_archetype, TARGETING_PRESETS,
)
from engine.cli import _build_encounter
from engine.core.runner import EncounterRunner
from engine.core.state import Actor, Encounter, CombatState
from engine.loader import load_content, load_yaml_file


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"
TWO_PC_FIXTURE = Path(__file__).parent / "fixtures" / "two_pc_encounter.yaml"


def _make_actor(actor_id: str, side: str = "enemy", hp: int = 20,
                ac: int = 15, abilities: dict | None = None,
                template_extras: dict | None = None) -> Actor:
    abilities = abilities or {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 14, "save": 2},
        "con": {"score": 12, "save": 1},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2}}
    if template_extras:
        template.update(template_extras)
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac, abilities=abilities)


def _state_with(actors: list[Actor]) -> CombatState:
    """Minimal state with turn_order populated."""
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    return state


# ============================================================================
# Targeting preset unit tests
# ============================================================================

class TargetingClosestEnemyTest(unittest.TestCase):

    def test_picks_first_in_turn_order(self) -> None:
        attacker = _make_actor("att", side="pc")
        e1 = _make_actor("e1", hp=10)
        e2 = _make_actor("e2", hp=10)
        e3 = _make_actor("e3", hp=10)
        state = _state_with([attacker, e1, e2, e3])

        chosen = pick_target(attacker, [e1, e2, e3], state, "closest_enemy")
        self.assertEqual(chosen.id, "e1",
                          "closest_enemy should pick first in turn order")


class TargetingWeakestTargetTest(unittest.TestCase):

    def test_picks_lowest_hp(self) -> None:
        attacker = _make_actor("att", side="pc")
        e1 = _make_actor("e1", hp=20)
        e2 = _make_actor("e2", hp=3)      # weakest
        e3 = _make_actor("e3", hp=15)
        state = _state_with([attacker, e1, e2, e3])

        chosen = pick_target(attacker, [e1, e2, e3], state, "weakest_target")
        self.assertEqual(chosen.id, "e2",
                          "weakest_target should pick the lowest-HP enemy")

    def test_handles_dead_enemies(self) -> None:
        """Dead enemies should be filtered out before picking."""
        attacker = _make_actor("att", side="pc")
        dead = _make_actor("dead", hp=0)
        dead.is_dead = True
        e2 = _make_actor("e2", hp=10)
        state = _state_with([attacker, dead, e2])

        chosen = pick_target(attacker, [dead, e2], state, "weakest_target")
        self.assertEqual(chosen.id, "e2", "Should skip dead enemies")


class TargetingMostDangerousTest(unittest.TestCase):

    def test_picks_higher_attack_bonus(self) -> None:
        attacker = _make_actor("att", side="pc")
        # Two enemies; e2 has a higher attack bonus
        weak_action = {"type": "weapon_attack",
                        "pipeline": [{"primitive": "attack_roll", "params": {"bonus": 2}}]}
        strong_action = {"type": "weapon_attack",
                          "pipeline": [{"primitive": "attack_roll", "params": {"bonus": 7}}]}
        e1 = _make_actor("e1", hp=20, template_extras={"actions": [weak_action]})
        e2 = _make_actor("e2", hp=20, template_extras={"actions": [strong_action]})
        state = _state_with([attacker, e1, e2])

        chosen = pick_target(attacker, [e1, e2], state, "most_dangerous")
        self.assertEqual(chosen.id, "e2",
                          "most_dangerous should pick higher attack bonus")

    def test_picks_higher_cr(self) -> None:
        attacker = _make_actor("att", side="pc")
        e1 = _make_actor("e1", hp=20, template_extras={
            "cr": {"value": 1, "xp": 200, "proficiency_bonus": 2}
        })
        e2 = _make_actor("e2", hp=20, template_extras={
            "cr": {"value": 5, "xp": 1800, "proficiency_bonus": 3}
        })
        state = _state_with([attacker, e1, e2])

        chosen = pick_target(attacker, [e1, e2], state, "most_dangerous")
        self.assertEqual(chosen.id, "e2", "most_dangerous should pick higher CR")


class TargetingCasterFirstTest(unittest.TestCase):

    def test_picks_spellcaster_over_martial(self) -> None:
        attacker = _make_actor("att", side="pc")
        martial = _make_actor("martial", hp=30, template_extras={
            "actions": [{"name": "Greatsword", "type": "weapon_attack",
                          "pipeline": [{"primitive": "attack_roll", "params": {"bonus": 6}}]}]
        })
        caster = _make_actor("caster", hp=20, template_extras={
            "actions": [{"name": "Spellcasting", "type": "spellcasting"}]
        })
        state = _state_with([attacker, martial, caster])

        chosen = pick_target(attacker, [martial, caster], state, "caster_first")
        self.assertEqual(chosen.id, "caster",
                          "caster_first should pick the spellcaster")

    def test_falls_back_when_no_caster(self) -> None:
        attacker = _make_actor("att", side="pc")
        m1 = _make_actor("m1", hp=20, template_extras={
            "cr": {"value": 1, "xp": 200, "proficiency_bonus": 2}
        })
        m2 = _make_actor("m2", hp=20, template_extras={
            "cr": {"value": 3, "xp": 700, "proficiency_bonus": 2}
        })
        state = _state_with([attacker, m1, m2])

        chosen = pick_target(attacker, [m1, m2], state, "caster_first")
        # No caster — falls back to most_dangerous
        self.assertEqual(chosen.id, "m2", "Without caster, fall back to most_dangerous")


class TargetingFinishOffRuleTest(unittest.TestCase):

    def test_int_4_finishes_off_near_death(self) -> None:
        """Actor with INT 4+ deviates from preset to attack near-death target."""
        smart_actor = _make_actor("smart", side="pc", abilities={
            "str": {"score": 10, "save": 0},
            "dex": {"score": 14, "save": 2},
            "con": {"score": 12, "save": 1},
            "int": {"score": 10, "save": 0},
            "wis": {"score": 10, "save": 0},
            "cha": {"score": 10, "save": 0},
        })
        healthy = _make_actor("healthy", hp=20)
        near_death = _make_actor("near_dead", hp=20)  # hp_max=20
        near_death.hp_current = 1                       # but at 1/20 = 5%
        state = _state_with([smart_actor, healthy, near_death])

        # Even with "most_dangerous" preset, finish-off rule overrides
        chosen = pick_target(smart_actor, [healthy, near_death], state, "most_dangerous")
        self.assertEqual(chosen.id, "near_dead",
                          "INT 4+ creature should finish off near-death enemy")

    def test_mindless_does_not_finish_off(self) -> None:
        """INT 1-3 creatures don't have the finish-off awareness."""
        zombie = _make_actor("zombie", side="enemy", abilities={
            "str": {"score": 13, "save": 1},
            "dex": {"score": 6, "save": -2},
            "con": {"score": 16, "save": 3},
            "int": {"score": 1, "save": -5},
            "wis": {"score": 6, "save": -2},
            "cha": {"score": 5, "save": -3},
        })
        healthy = _make_actor("healthy", side="pc", hp=20)
        near_death = _make_actor("near_dead", side="pc", hp=20)  # hp_max=20
        near_death.hp_current = 1                                    # at 1/20 = 5%
        state = _state_with([zombie, healthy, near_death])

        # With "closest_enemy" preset, finish-off rule does NOT activate
        # for INT < 4 creatures (zombies don't deviate)
        chosen = pick_target(zombie, [healthy, near_death], state, "closest_enemy")
        # Should pick by closest_enemy logic (first in turn order = healthy)
        self.assertEqual(chosen.id, "healthy",
                          "Mindless creature should not deviate to finish off")


# ============================================================================
# Behavior profile resolution
# ============================================================================

class BehaviorProfileResolutionTest(unittest.TestCase):

    def test_explicit_preset_overrides_archetype(self) -> None:
        actor = _make_actor("a", template_extras={
            "behavior_profile": {
                "archetype": "cowardly_skirmisher",
                "presets": {"targeting": "most_dangerous"},
            }
        })
        self.assertEqual(resolve_targeting_preset(actor), "most_dangerous")

    def test_archetype_default_when_no_explicit_preset(self) -> None:
        # cowardly_skirmisher → weakest_target by default
        actor = _make_actor("a", template_extras={
            "behavior_profile": {"archetype": "cowardly_skirmisher"}
        })
        self.assertEqual(resolve_targeting_preset(actor), "weakest_target")

    def test_apex_predator_targets_casters(self) -> None:
        actor = _make_actor("a", template_extras={
            "behavior_profile": {"archetype": "apex_predator"}
        })
        self.assertEqual(resolve_targeting_preset(actor), "caster_first")

    def test_pack_hunter_most_dangerous(self) -> None:
        actor = _make_actor("a", template_extras={
            "behavior_profile": {"archetype": "pack_hunter"}
        })
        self.assertEqual(resolve_targeting_preset(actor), "most_dangerous")

    def test_fallback_when_no_archetype_or_preset(self) -> None:
        actor = _make_actor("a")  # no behavior_profile
        self.assertEqual(resolve_targeting_preset(actor), "closest_enemy")

    def test_archetype_resolution(self) -> None:
        actor = _make_actor("a", template_extras={
            "behavior_profile": {"archetype": "berserker_fanatic"}
        })
        self.assertEqual(resolve_archetype(actor), "berserker_fanatic")


# ============================================================================
# Ability selection
# ============================================================================

class AbilitySelectionTest(unittest.TestCase):

    def test_default_prefers_multiattack(self) -> None:
        actor = _make_actor("a", template_extras={
            "actions": [
                {"id": "a_attack", "type": "weapon_attack",
                 "pipeline": [{"primitive": "attack_roll", "params": {"bonus": 3}}]},
                {"id": "a_multi", "type": "multiattack", "count": 2,
                 "sub_actions": ["a_attack", "a_attack"]},
            ]
        })
        chosen = pick_action(actor, None, _state_with([actor]), "default")
        self.assertEqual(chosen["id"], "a_multi",
                          "Default preset should prefer multiattack")

    def test_mindless_picks_first(self) -> None:
        actor = _make_actor("a", template_extras={
            "actions": [
                {"id": "a_first", "type": "weapon_attack"},
                {"id": "a_multi", "type": "multiattack", "count": 2},
            ]
        })
        chosen = pick_action(actor, None, _state_with([actor]), "mindless")
        self.assertEqual(chosen["id"], "a_first", "Mindless picks the first action")

    def test_instinctive_prefers_signature(self) -> None:
        actor = _make_actor("a", template_extras={
            "actions": [
                {"id": "a_basic", "type": "weapon_attack"},
                {"id": "a_signature", "type": "weapon_attack", "is_signature": True},
            ]
        })
        chosen = pick_action(actor, None, _state_with([actor]), "instinctive")
        self.assertEqual(chosen["id"], "a_signature",
                          "Instinctive picks signature action")


# ============================================================================
# Integration test: weakest_target — Goblin attacks wounded PC first
# ============================================================================

class IntegrationWeakestTargetTest(unittest.TestCase):

    def test_goblin_attacks_wounded_fighter_first(self) -> None:
        """The m_goblin_warrior has archetype=cowardly_skirmisher,
        which defaults to weakest_target. In the two-PC encounter,
        the goblin should attack the wounded fighter (5 HP) before
        the healthy fighter (28 HP).
        """
        registry = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
        spec = load_yaml_file(TWO_PC_FIXTURE)
        encounter = _build_encounter(spec, registry)

        primitives_module.set_rng(random.Random(99))
        runner = EncounterRunner.new(encounter, seed=99, content_registry=registry)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=99)

        # Find the goblin's FIRST attack roll in the event log
        goblin_attacks = [e for e in state.event_log
                          if e.get("event") == "attack_roll"
                          and e.get("actor") == "goblin_1"]
        self.assertTrue(goblin_attacks,
                        "Goblin should have made at least one attack")
        first_target = goblin_attacks[0]["target"]
        self.assertEqual(first_target, "fighter_wounded",
                          f"Goblin (cowardly_skirmisher → weakest_target) should "
                          f"attack the wounded fighter first; attacked {first_target}")


if __name__ == "__main__":
    unittest.main()
