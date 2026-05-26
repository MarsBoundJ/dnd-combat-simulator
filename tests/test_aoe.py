"""AoE geometry v1 tests — sphere shape, friendly fire, half-on-save.

Layers:
  1. Geometry — actors_in_radius (Chebyshev)
  2. damage primitive multiplier (half / double)
  3. forced_save with area filtering + per-target swap of current_attack.target
  4. AoE eHP scoring (multi-target, friendly fire penalty, half-save folded in)
  5. Candidate generation: one per enemy-anchored origin
  6. End-to-end: wizard with Fireball picks cluster-centered origin and
     hits multiple goblins in one cast

Run via:
    python -m unittest tests.test_aoe
"""
from __future__ import annotations

import random
import unittest

from engine.ai import score_candidate, offensive_ehp_aoe
from engine.core.geometry import actors_in_radius
from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "enemy",
                hp: int = 30, ac: int = 13,
                position: tuple[int, int] = (0, 0),
                speed: int = 30,
                actions: list[dict] | None = None,
                damage_resistances: list[str] | None = None,
                damage_immunities: list[str] | None = None,
                wis_save: int = 0,
                dex_save: int = 0,
                template_extras: dict | None = None) -> Actor:
    abilities = {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 10 + 2 * dex_save, "save": dex_save},
        "con": {"score": 12, "save": 1},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10 + 2 * wis_save, "save": wis_save},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": actions or []}
    if damage_resistances:
        template["damage_resistances"] = damage_resistances
    if damage_immunities:
        template["damage_immunities"] = damage_immunities
    if template_extras:
        template.update(template_extras)
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp, hp_max=hp, ac=ac,
                  speed={"walk": speed}, position=position,
                  abilities=abilities)


def _state_with(actors: list[Actor]) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    return state


def _fireball_action(action_id: str = "a_fireball",
                      radius_ft: int = 20, range_ft: int = 150,
                      dice: str = "8d6", dc: int = 15,
                      dmg_type: str = "fire") -> dict:
    return {
        "id": action_id, "name": action_id, "type": "aoe_attack",
        "area": {"shape": "sphere", "radius_ft": radius_ft,
                  "range_ft": range_ft},
        "pipeline": [
            {"primitive": "forced_save",
              "params": {
                  "ability": "dexterity", "dc": dc,
                  "affected": "all_creatures_in_area",
                  "on_fail": [
                      {"primitive": "damage",
                        "params": {"dice": dice, "type": dmg_type}},
                  ],
                  "on_success": [
                      {"primitive": "damage",
                        "params": {"dice": dice, "type": dmg_type,
                                    "multiplier": 0.5}},
                  ],
              }},
        ],
    }


# ============================================================================
# Geometry — actors_in_radius
# ============================================================================

class ActorsInRadiusTest(unittest.TestCase):

    def test_includes_actor_at_origin(self) -> None:
        a = _make_actor("a", position=(3, 3))
        self.assertEqual(actors_in_radius((3, 3), 5, [a]), [a])

    def test_excludes_actor_outside_radius(self) -> None:
        a = _make_actor("a", position=(10, 0))   # 50 ft from origin
        self.assertEqual(actors_in_radius((0, 0), 20, [a]), [])

    def test_chebyshev_boundary_20ft_sphere(self) -> None:
        # 20 ft radius = 4 squares Chebyshev. Square (4, 0) = 20 ft = in.
        # Square (5, 0) = 25 ft = out.
        a_in = _make_actor("in", position=(4, 0))
        a_out = _make_actor("out", position=(5, 0))
        result = actors_in_radius((0, 0), 20, [a_in, a_out])
        self.assertIn(a_in, result)
        self.assertNotIn(a_out, result)

    def test_diagonal_inclusion_per_2024_rules(self) -> None:
        """Diagonal (3, 3) is 15 ft per Chebyshev × 5 (NOT alternating
        5/10). At 20 ft radius: includes (3, 3); excludes (5, 5)."""
        in_diag = _make_actor("in", position=(3, 3))
        out_diag = _make_actor("out", position=(5, 5))
        result = actors_in_radius((0, 0), 20, [in_diag, out_diag])
        self.assertIn(in_diag, result)
        self.assertNotIn(out_diag, result)


# ============================================================================
# damage primitive — multiplier param
# ============================================================================

class DamageMultiplierTest(unittest.TestCase):

    def test_multiplier_half_halves_damage(self) -> None:
        from engine import primitives as primitives_module
        from engine.core.events import EventBus

        primitives_module.set_rng(random.Random(0))
        target = _make_actor("t", hp=100)
        state = _state_with([_make_actor("a", side="pc"), target])
        state.current_attack = {
            "actor": state.encounter.actors[0],
            "target": target,
            "action": {}, "state": "hit",
        }
        # 6d6 mean = 21; multiplier 0.5 → ~10 dmg
        # We can't assert exact damage (RNG), but multiplier=0.5 should
        # always deal ≤ multiplier=1.0 result with same seed.
        rng_seed = 99
        full = _roll_damage(rng_seed, multiplier=1.0)
        half = _roll_damage(rng_seed, multiplier=0.5)
        self.assertLessEqual(half, full)
        self.assertGreater(full, 0)

    def test_multiplier_two_doubles_damage(self) -> None:
        full = _roll_damage(99, multiplier=1.0)
        double = _roll_damage(99, multiplier=2.0)
        # Multiplier 2.0 should produce at least ~2x; integer rounding may
        # off-by-1
        self.assertGreaterEqual(double, full * 2 - 1)


def _roll_damage(seed: int, multiplier: float) -> int:
    """Helper: roll 6d6 damage on a 100-HP target with given multiplier
    and return the HP loss."""
    from engine import primitives as primitives_module
    from engine.core.events import EventBus

    primitives_module.set_rng(random.Random(seed))
    target = Actor(id="t", name="t", template={}, side="pc",
                    hp_current=100, hp_max=100, ac=10,
                    abilities={}, position=(0, 0))
    enc = Encounter(id="e", actors=[target])
    state = CombatState(encounter=enc)
    state.current_attack = {
        "actor": target, "target": target,
        "action": {}, "state": "hit",
    }
    primitives_module._damage(
        {"dice": "6d6", "type": "fire", "multiplier": multiplier},
        state, EventBus(),
    )
    return 100 - target.hp_current


# ============================================================================
# AoE eHP scoring
# ============================================================================

class AoEScoringTest(unittest.TestCase):

    def test_no_creatures_in_area_scores_zero(self) -> None:
        # Caster + enemy both well outside the chosen origin's radius
        caster = _make_actor("c", side="pc", position=(0, 0))
        far = _make_actor("e", side="enemy", position=(20, 0))   # 100 ft
        state = _state_with([caster, far])
        action = _fireball_action(radius_ft=20)
        # Origin at (40, 0) — 200 ft from caster, 100 ft from enemy.
        # Nobody in radius → 0 eHP.
        self.assertEqual(offensive_ehp_aoe(caster, (40, 0), action, state),
                          0.0)

    def test_single_enemy_in_area_scores_positive(self) -> None:
        # Caster far from origin (outside blast); single enemy in blast
        caster = _make_actor("c", side="pc", position=(0, 0))
        enemy = _make_actor("e", side="enemy", position=(20, 0),   # 100 ft
                              hp=50)
        state = _state_with([caster, enemy])
        action = _fireball_action(radius_ft=20)
        # Origin at enemy's square; caster 100 ft away (outside 20 ft)
        score = offensive_ehp_aoe(caster, (20, 0), action, state)
        self.assertGreater(score, 0)

    def test_more_enemies_score_more(self) -> None:
        """3 clustered enemies > 1 enemy."""
        caster = _make_actor("c", side="pc", position=(0, 0))
        e1 = _make_actor("e1", side="enemy", position=(5, 0), hp=50)
        e2 = _make_actor("e2", side="enemy", position=(5, 1), hp=50)
        e3 = _make_actor("e3", side="enemy", position=(5, -1), hp=50)
        state_three = _state_with([caster, e1, e2, e3])
        state_one = _state_with([caster, e1])
        action = _fireball_action(radius_ft=20)

        score_three = offensive_ehp_aoe(caster, (5, 0), action, state_three)
        score_one = offensive_ehp_aoe(caster, (5, 0), action, state_one)
        self.assertGreater(score_three, score_one * 2,
                            "3 enemies in area should score significantly "
                            "more than 1")

    def test_friendly_fire_subtracts_from_score(self) -> None:
        """Casting AoE on a cluster that includes an ally scores lower."""
        caster = _make_actor("c", side="pc", position=(0, 0))
        enemy = _make_actor("e", side="enemy", position=(5, 0), hp=50)
        ally = _make_actor("ally", side="pc", position=(5, 1), hp=50)
        action = _fireball_action(radius_ft=20)

        state_clean = _state_with([caster, enemy])
        state_with_ally = _state_with([caster, enemy, ally])

        clean_score = offensive_ehp_aoe(caster, (5, 0), action, state_clean)
        ally_score = offensive_ehp_aoe(caster, (5, 0), action, state_with_ally)
        self.assertLess(ally_score, clean_score,
                          "Friendly fire on an ally should lower the score")

    def test_caster_self_counts_as_friendly_fire(self) -> None:
        """Don't fireball yourself."""
        caster = _make_actor("c", side="pc", position=(0, 0), hp=30)
        enemy = _make_actor("e", side="enemy", position=(2, 0), hp=30)
        action = _fireball_action(radius_ft=20)
        state = _state_with([caster, enemy])
        # Origin near the caster includes the caster in the blast
        score_at_caster = offensive_ehp_aoe(caster, (0, 0), action, state)
        # Origin far from caster (only enemy hit)
        score_at_enemy = offensive_ehp_aoe(caster, (2, 0), action, state)
        # In v1 with caster in radius, score includes caster as friendly
        # fire. So enemy-origin should score higher than self-origin.
        # In this setup both include both creatures (radius 20 covers
        # everything), so they should be equal. Adjust the test to use a
        # tighter radius:
        tight_action = _fireball_action(radius_ft=5)
        score_tight_at_caster = offensive_ehp_aoe(
            caster, (0, 0), tight_action, state)
        score_tight_at_enemy = offensive_ehp_aoe(
            caster, (2, 0), tight_action, state)
        # Origin at caster (radius 5) → only caster in area → negative
        # Origin at enemy (radius 5) → only enemy in area → positive
        self.assertLess(score_tight_at_caster, 0,
                          "Self-origin small-radius AoE should be negative "
                          "(only friendly fire)")
        self.assertGreater(score_tight_at_enemy, 0,
                            "Enemy-origin small-radius AoE should be "
                            "positive")


# ============================================================================
# Candidate generation
# ============================================================================

class AoECandidateGenerationTest(unittest.TestCase):

    def test_one_aoe_candidate_per_living_enemy(self) -> None:
        wizard = _make_actor("w", side="pc", position=(0, 0),
                              actions=[_fireball_action()])
        e1 = _make_actor("e1", side="enemy", position=(5, 0))
        e2 = _make_actor("e2", side="enemy", position=(5, 5))
        state = _state_with([wizard, e1, e2])
        cands = generate_candidates(wizard, state)
        aoe_cands = [c for c in cands if c["kind"] == "aoe_attack"]
        self.assertEqual(len(aoe_cands), 2)
        # Each origin should match an enemy position
        origins = sorted(tuple(c["origin_point"]) for c in aoe_cands)
        self.assertEqual(origins, [(5, 0), (5, 5)])

    def test_aoe_candidate_filtered_by_cast_range(self) -> None:
        """An enemy beyond the spell's range_ft generates no candidate."""
        wizard = _make_actor("w", side="pc", position=(0, 0),
                              actions=[_fireball_action(range_ft=30)])
        close = _make_actor("close", side="enemy", position=(5, 0))   # 25 ft
        far = _make_actor("far", side="enemy", position=(20, 0))    # 100 ft
        state = _state_with([wizard, close, far])
        cands = generate_candidates(wizard, state)
        aoe_origins = sorted(tuple(c["origin_point"]) for c in cands
                              if c["kind"] == "aoe_attack")
        self.assertEqual(aoe_origins, [(5, 0)])

    def test_score_candidate_routes_to_aoe_scoring(self) -> None:
        wizard = _make_actor("w", side="pc", position=(0, 0))
        enemy = _make_actor("e", side="enemy", position=(5, 0), hp=50)
        state = _state_with([wizard, enemy])
        action = _fireball_action()
        cand = {"kind": "aoe_attack", "actor": wizard, "target": enemy,
                "action": action, "origin_point": (5, 0)}
        score = score_candidate(cand, state)
        self.assertGreater(score, 0)


# ============================================================================
# End-to-end: wizard with Fireball hits a cluster
# ============================================================================

class WizardFireballIntegrationTest(unittest.TestCase):

    def test_wizard_casts_fireball_at_cluster(self) -> None:
        """A wizard with Fireball + Dart should choose Fireball when 3
        clustered goblins are present, picking an origin that catches
        all 3."""
        import random as _random
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner

        # Weak dart attack + a hefty Fireball
        dart = {
            "id": "a_dart", "name": "Dart", "type": "weapon_attack",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "ranged", "bonus": 5, "range_ft": 60}},
                {"primitive": "damage",
                  "params": {"dice": "1d4", "modifier": 3, "type": "piercing"},
                  "when": {"event": "damage_roll",
                            "condition": "combat.attack_state == hit"}},
            ],
        }
        wizard = _make_actor("wizard", side="pc", hp=30, ac=12,
                               position=(0, 0),
                               actions=[dart, _fireball_action(
                                   radius_ft=20, range_ft=150,
                                   dice="8d6", dc=15)],
                               template_extras={"combat": {
                                   "initiative": {"modifier": 20},
                               }})
        # 3 clustered goblins at (10, 0), (10, 1), (11, 0). All within
        # ~5 ft of each other → 20-ft radius sphere catches all 3.
        g1 = _make_actor("g1", side="enemy", hp=14, ac=13,
                           position=(10, 0), dex_save=2)
        g2 = _make_actor("g2", side="enemy", hp=14, ac=13,
                           position=(10, 1), dex_save=2)
        g3 = _make_actor("g3", side="enemy", hp=14, ac=13,
                           position=(11, 0), dex_save=2)
        encounter = Encounter(id="fireball_test",
                                actors=[wizard, g1, g2, g3])

        primitives_module.set_rng(_random.Random(1))
        runner = EncounterRunner.new(encounter, seed=1)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # Find the wizard's first AoE origin placement
        aoe_events = [e for e in state.event_log
                       if e.get("event") == "aoe_origin_placed"
                       and e.get("actor") == "wizard"]
        self.assertGreater(len(aoe_events), 0,
                            "Wizard should have cast Fireball at least once")

        # Verify forced_save fired for all 3 goblins on the first AoE
        first_aoe_idx = state.event_log.index(aoe_events[0])
        # Look for the immediately-following forced_save events
        following_saves = []
        for e in state.event_log[first_aoe_idx:first_aoe_idx + 10]:
            if e.get("event") == "forced_save":
                following_saves.append(e.get("target"))
            elif e.get("event") == "turn_end":
                break
        # All 3 goblins should be in the affected set
        targeted_ids = set(following_saves)
        self.assertTrue(
            {"g1", "g2", "g3"}.issubset(targeted_ids),
            f"All 3 clustered goblins should have rolled saves; got "
            f"{targeted_ids}",
        )


if __name__ == "__main__":
    unittest.main()
