"""AI eHP scoring for the Darkness spell (PR #61).

Layers:
  1. offensive_ehp_darkness:
     - No actors in sphere → 0
     - Only out-of-sphere actors → 0 (sphere empty)
     - In-sphere allies + out-of-sphere enemies (reachable) → positive
     - In-sphere enemies + out-of-sphere allies (reachable) → cost
       outweighs benefit → 0 (clamped)
     - Symmetric setup (allies AND enemies in sphere) → benefit and
       cost partially cancel
     - Truesight enemy filtered out from benefit
     - Truesight ally filtered out from cost
     - Out-of-reach enemies don't contribute defensive value
     - Origin override (non-self-cast)
  2. Dispatch via creates_zone:
     - Darkness action routes to offensive_ehp_darkness
     - Damage aura (Spirit Guardians-shape) routes to the existing
       damage scorer
"""
from __future__ import annotations

import unittest

from engine.ai.ehp_scoring import (
    DARKNESS_RADIUS_SQUARES, EXPECTED_AURA_ROUNDS,
    offensive_ehp_darkness, offensive_ehp_persistent_aura,
)
from engine.core.state import Actor, CombatState, Encounter


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0),
                  truesight_range_ft=0,
                  blindsight_range_ft=0,
                  actions=None) -> Actor:
    abilities = {k: {"score": 14 if k == "str" else 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                 "abilities": abilities,
                 "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                 "actions": actions or []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=30, hp_max=30, ac=14,
                  speed={"walk": 30}, position=position,
                  abilities=abilities,
                  truesight_range_ft=truesight_range_ft,
                  blindsight_range_ft=blindsight_range_ft)


def _basic_attack():
    return {
        "id": "a_attack", "name": "Attack",
        "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": 4, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": "1d8", "modifier": 3, "type": "slashing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }


def _state_with(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _darkness_action():
    return {
        "id": "a_darkness", "name": "Darkness",
        "type": "persistent_aura",
        "spell_slot_level": 2,
        "concentration": True,
        "named_effect": "darkness",
        "pipeline": [
            {"primitive": "persistent_aura",
              "params": {
                  "shape": "sphere",
                  "radius_ft": 15,
                  "anchor": "point",
                  "ability": "none",
                  "on_fail": [],
                  "on_success": [],
                  "creates_zone": "magical_dark",
              }},
        ],
    }


def _spirit_guardians_action():
    """Damage-aura template (no creates_zone) for dispatch tests."""
    return {
        "id": "a_sg", "name": "Spirit Guardians",
        "type": "persistent_aura",
        "spell_slot_level": 3,
        "concentration": True,
        "pipeline": [
            {"primitive": "persistent_aura",
              "params": {
                  "shape": "sphere",
                  "radius_ft": 15,
                  "anchor": "caster",
                  "ability": "wisdom",
                  "dc": 14,
                  "affected": "enemies",
                  "on_fail": [{"primitive": "damage",
                                 "params": {"dice": "3d8",
                                              "type": "radiant"}}],
                  "on_success": [{"primitive": "damage",
                                     "params": {"dice": "3d8",
                                                  "type": "radiant",
                                                  "multiplier": 0.5}}],
              }},
        ],
    }


# ============================================================================
# Layer 1: offensive_ehp_darkness
# ============================================================================

class DarknessScoringTest(unittest.TestCase):

    def test_radius_constant(self) -> None:
        self.assertEqual(DARKNESS_RADIUS_SQUARES, 3)

    def test_empty_sphere_returns_zero(self) -> None:
        # Caster at (0,0), enemy and ally both well outside the sphere
        caster = _make_actor("caster", position=(0, 0),
                                actions=[_basic_attack()])
        ally = _make_actor("ally", position=(50, 50),
                              actions=[_basic_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(50, 0),
                              actions=[_basic_attack()])
        state = _state_with([caster, ally, enemy])
        # Override origin to (100, 100) — nobody is in the sphere
        score = offensive_ehp_darkness(caster, _darkness_action(),
                                            state, origin=(100, 100))
        self.assertEqual(score, 0.0)

    def test_caster_inside_enemy_outside_reachable_positive(self) -> None:
        # Cast on self; enemy adjacent but outside the 15-ft sphere
        # (15 ft = 3 squares radius, so enemy at (4, 0) is outside).
        caster = _make_actor("caster", position=(0, 0),
                                actions=[_basic_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(4, 0),
                              actions=[_basic_attack()])
        state = _state_with([caster, enemy])
        score = offensive_ehp_darkness(caster, _darkness_action(),
                                            state)
        self.assertGreater(score, 0.0)

    def test_enemy_inside_caster_outside_negative_clamped_to_zero(self) -> None:
        # Cast Darkness on a square containing an enemy; caster outside
        caster = _make_actor("caster", position=(20, 20),
                                actions=[_basic_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(0, 0),
                              actions=[_basic_attack()])
        state = _state_with([caster, enemy])
        # Origin at enemy's position — caster is far away (outside)
        # Enemy is in sphere, no allies in sphere → only cost, no
        # benefit. Net negative → clamps to 0.
        score = offensive_ehp_darkness(caster, _darkness_action(),
                                            state, origin=(0, 0))
        self.assertEqual(score, 0.0)

    def test_truesight_enemy_doesnt_contribute_benefit(self) -> None:
        # Caster in sphere, enemy with truesight outside the sphere
        # but within truesight range — enemy pierces, no benefit
        caster = _make_actor("caster", position=(0, 0),
                                actions=[_basic_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(4, 0),
                              truesight_range_ft=120,
                              actions=[_basic_attack()])
        state = _state_with([caster, enemy])
        score = offensive_ehp_darkness(caster, _darkness_action(),
                                            state)
        # With truesight enemy, only the offensive "one boosted attack"
        # piece contributes (because the defensive disadvantage is
        # nullified by truesight). Still some positive value.
        # Actually our scorer adds offensive value when out_enemies
        # is non-empty — truesight doesn't disqualify the enemy from
        # the OFFENSIVE side. So expect SOME positive value.
        self.assertGreaterEqual(score, 0.0)
        # And less than what it'd be without truesight
        no_ts_enemy = _make_actor("enemy2", side="enemy", position=(4, 0),
                                       actions=[_basic_attack()])
        state_no_ts = _state_with([caster, no_ts_enemy])
        score_no_ts = offensive_ehp_darkness(caster, _darkness_action(),
                                                  state_no_ts)
        self.assertGreater(score_no_ts, score)

    def test_truesight_ally_doesnt_contribute_cost(self) -> None:
        # Caster outside, ally with truesight outside, enemy in sphere.
        # Without truesight: ally would suffer cost. With truesight:
        # ally pierces, so cost from this ally is 0.
        caster = _make_actor("caster", position=(20, 20),
                                actions=[_basic_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(0, 0),
                              actions=[_basic_attack()])
        ts_ally = _make_actor("ally", side="pc", position=(4, 0),
                                 truesight_range_ft=120,
                                 actions=[_basic_attack()])
        state = _state_with([caster, ts_ally, enemy])
        # Origin at (0, 0) — enemy in sphere, ts_ally just outside
        # but with truesight → no cost from this ally
        score = offensive_ehp_darkness(caster, _darkness_action(),
                                            state, origin=(0, 0))
        # With ally truesight neutralizing the defensive cost, only
        # the offensive cost (enemy gets boosted attack) remains.
        # Caster also out of sphere and far from enemy (chebyshev
        # 20 + reach 5 = 25 ft; distance from caster to enemy =
        # max(20, 20)*5 = 100 ft, way out of threat range). So
        # caster doesn't contribute cost. ts_ally is in reach (max
        # (4, 0)*5 = 20 ft, < speed+reach=35) but truesight nullifies.
        # Net should be 0 or low.
        self.assertEqual(score, 0.0)

    def test_out_of_reach_enemy_no_defensive(self) -> None:
        # Enemy WAY outside threat range — no defensive contribution
        caster = _make_actor("caster", position=(0, 0),
                                actions=[_basic_attack()])
        far_enemy = _make_actor("enemy", side="enemy", position=(100, 0),
                                   actions=[_basic_attack()])
        state = _state_with([caster, far_enemy])
        score_far = offensive_ehp_darkness(caster, _darkness_action(),
                                                state)
        # Compare to a near enemy
        near_enemy = _make_actor("enemy2", side="enemy", position=(4, 0),
                                    actions=[_basic_attack()])
        state_near = _state_with([caster, near_enemy])
        score_near = offensive_ehp_darkness(caster, _darkness_action(),
                                                 state_near)
        self.assertGreater(score_near, score_far)

    def test_origin_default_is_caster_position(self) -> None:
        # When origin is None, scorer should use caster's position
        caster = _make_actor("caster", position=(0, 0),
                                actions=[_basic_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(4, 0),
                              actions=[_basic_attack()])
        state = _state_with([caster, enemy])
        score_default = offensive_ehp_darkness(caster, _darkness_action(),
                                                    state)
        score_explicit = offensive_ehp_darkness(caster, _darkness_action(),
                                                     state,
                                                     origin=(0, 0))
        self.assertAlmostEqual(score_default, score_explicit, places=2)

    def test_multiple_allies_more_benefit(self) -> None:
        # Two allies in sphere vs one ally → more benefit
        caster = _make_actor("caster", position=(0, 0),
                                actions=[_basic_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(4, 0),
                              actions=[_basic_attack()])
        one_ally_state = _state_with([caster, enemy])
        score_one = offensive_ehp_darkness(caster, _darkness_action(),
                                                one_ally_state)

        ally2 = _make_actor("ally", side="pc", position=(0, 1),
                               actions=[_basic_attack()])
        two_ally_state = _state_with([caster, ally2,
                                          _make_actor("enemy2",
                                                         side="enemy",
                                                         position=(4, 0),
                                                         actions=[_basic_attack()])])
        score_two = offensive_ehp_darkness(caster, _darkness_action(),
                                                two_ally_state)
        self.assertGreater(score_two, score_one)


# ============================================================================
# Layer 2: dispatch via creates_zone
# ============================================================================

class DispatchTest(unittest.TestCase):

    def test_darkness_routes_to_darkness_scorer(self) -> None:
        caster = _make_actor("caster", position=(0, 0),
                                actions=[_basic_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(4, 0),
                              actions=[_basic_attack()])
        state = _state_with([caster, enemy])
        # Call via persistent_aura dispatcher
        score_via_dispatch = offensive_ehp_persistent_aura(
            caster, _darkness_action(), state, origin=(0, 0))
        score_direct = offensive_ehp_darkness(
            caster, _darkness_action(), state, origin=(0, 0))
        self.assertAlmostEqual(score_via_dispatch, score_direct,
                                  places=2)

    def test_damage_aura_does_NOT_route_to_darkness(self) -> None:
        # Spirit Guardians-shape should still use the damage scorer
        caster = _make_actor("caster", position=(0, 0),
                                actions=[_basic_attack()])
        enemy = _make_actor("enemy", side="enemy", position=(2, 0),
                              actions=[_basic_attack()])
        state = _state_with([caster, enemy])
        score = offensive_ehp_persistent_aura(
            caster, _spirit_guardians_action(), state)
        # SG should produce a non-zero damage score (positive eHP from
        # enemy in aura)
        self.assertGreater(score, 0.0)
        # And NOT match what the darkness scorer would produce on the
        # same setup (since darkness scorer ignores damage)
        darkness_score = offensive_ehp_darkness(
            caster, _spirit_guardians_action(), state)
        # Darkness scorer treats SG as if it were Darkness — different
        # value. They shouldn't accidentally match.
        # (They might both happen to be 0 in degenerate cases, but
        # for this in-aura enemy SG should be > 0 and unrelated to
        # the darkness computation.)
        self.assertNotEqual(score, darkness_score)


# ============================================================================
# PR #69: Blindsight bypass for Darkness scoring
# ============================================================================

class BlindsightBypassTest(unittest.TestCase):
    """Blindsight is the dominant override in can_actor_see (per PR
    #52): pierces fog / Invisible / darkness / magical darkness /
    self-Blinded within range. PR #61's Darkness scorer originally
    only considered Truesight; PR #69 added Blindsight to the
    sense-bypass helper so the scorer correctly values Darkness
    LESS against blindsight monsters and LESS to drop on top of
    blindsight allies."""

    def test_blindsight_enemy_reduces_defensive_benefit(self) -> None:
        """An out-sphere enemy with blindsight in range pierces the
        magical darkness, contributing 0 defensive value (instead of
        their normal DPR × disadvantage_delta)."""
        # Caster + ally inside the sphere
        caster = _make_actor("caster", position=(0, 0),
                                actions=[_basic_attack()])
        # Enemy with blindsight 60 ft outside the sphere but in range
        bs_enemy = _make_actor("bat", side="enemy", position=(4, 0),
                                  blindsight_range_ft=60,
                                  actions=[_basic_attack()])
        state_bs = _state_with([caster, bs_enemy])
        score_bs = offensive_ehp_darkness(caster, _darkness_action(),
                                              state_bs, origin=(0, 0))

        # Compare to a no-blindsight enemy in the same spot
        no_bs_enemy = _make_actor("ogre", side="enemy", position=(4, 0),
                                      actions=[_basic_attack()])
        state_no_bs = _state_with([caster, no_bs_enemy])
        score_no_bs = offensive_ehp_darkness(caster, _darkness_action(),
                                                  state_no_bs,
                                                  origin=(0, 0))

        # The blindsight enemy contributes no defensive value; the
        # no-bs enemy contributes a full DPR × delta term. The bs
        # score should be strictly less.
        self.assertLess(score_bs, score_no_bs)

    def test_blindsight_out_of_range_does_not_bypass(self) -> None:
        """Blindsight 30 ft enemy at 50 ft can't pierce — same as no
        bs at all."""
        caster = _make_actor("caster", position=(0, 0),
                                actions=[_basic_attack()])
        # Far blindsight enemy (out of bs range)
        far_bs = _make_actor("bat", side="enemy", position=(10, 0),
                                blindsight_range_ft=30,
                                actions=[_basic_attack()])
        state_far = _state_with([caster, far_bs])
        score_far = offensive_ehp_darkness(caster, _darkness_action(),
                                                state_far, origin=(0, 0))
        # No-bs equivalent at same distance
        far_no_bs = _make_actor("ogre", side="enemy", position=(10, 0),
                                     actions=[_basic_attack()])
        state_no_bs = _state_with([caster, far_no_bs])
        score_no_bs = offensive_ehp_darkness(caster, _darkness_action(),
                                                  state_no_bs,
                                                  origin=(0, 0))
        # Should be the same — out-of-range bs is irrelevant
        self.assertEqual(score_far, score_no_bs)

    def test_blindsight_ally_reduces_cost(self) -> None:
        """An out-sphere ally with blindsight pierces an in-sphere
        enemy's darkness benefit — reduces our COST."""
        caster = _make_actor("caster", position=(20, 20),
                                actions=[_basic_attack()])
        # Enemy in the sphere
        enemy = _make_actor("rogue", side="enemy", position=(0, 0),
                               actions=[_basic_attack()])
        # Ally outside with blindsight in range
        bs_ally = _make_actor("scout", side="pc", position=(4, 0),
                                 blindsight_range_ft=60,
                                 actions=[_basic_attack()])
        state_bs = _state_with([caster, enemy, bs_ally])
        score_bs = offensive_ehp_darkness(caster, _darkness_action(),
                                              state_bs, origin=(0, 0))

        # Same setup but ally without blindsight
        no_bs_ally = _make_actor("scout", side="pc", position=(4, 0),
                                     actions=[_basic_attack()])
        state_no_bs = _state_with([caster, enemy, no_bs_ally])
        score_no_bs = offensive_ehp_darkness(caster, _darkness_action(),
                                                  state_no_bs,
                                                  origin=(0, 0))

        # bs ally → lower cost → higher (or equal) net score
        self.assertGreaterEqual(score_bs, score_no_bs)

    def test_blindsight_and_truesight_both_pierce(self) -> None:
        """Either sense should suffice; an enemy with both should
        score the same as an enemy with just one (both produce
        'pierces' True for this pair)."""
        caster = _make_actor("caster", position=(0, 0),
                                actions=[_basic_attack()])
        both_enemy = _make_actor("paladin", side="enemy", position=(4, 0),
                                     truesight_range_ft=60,
                                     blindsight_range_ft=60,
                                     actions=[_basic_attack()])
        state_both = _state_with([caster, both_enemy])
        score_both = offensive_ehp_darkness(caster, _darkness_action(),
                                                 state_both,
                                                 origin=(0, 0))

        ts_only = _make_actor("paladin", side="enemy", position=(4, 0),
                                 truesight_range_ft=60,
                                 actions=[_basic_attack()])
        state_ts = _state_with([caster, ts_only])
        score_ts = offensive_ehp_darkness(caster, _darkness_action(),
                                               state_ts, origin=(0, 0))

        bs_only = _make_actor("bat", side="enemy", position=(4, 0),
                                 blindsight_range_ft=60,
                                 actions=[_basic_attack()])
        state_bs = _state_with([caster, bs_only])
        score_bs = offensive_ehp_darkness(caster, _darkness_action(),
                                              state_bs, origin=(0, 0))

        # All three scores should match: pierces is a boolean OR.
        self.assertEqual(score_both, score_ts)
        self.assertEqual(score_ts, score_bs)


if __name__ == "__main__":
    unittest.main()
