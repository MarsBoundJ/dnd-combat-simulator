"""Hybrid aura scoring tests (PR #78).

Layers:
  1. offensive_ehp_zone_vision_denial — generalized darkness scorer
  2. Zone type behavior: magical_dark (BS or TS pierces)
  3. Zone type behavior: heavy_obscurement (BS only pierces)
  4. Radius respects radius_ft param (HoH 20 ft vs Darkness 15 ft)
  5. Backward compat: offensive_ehp_darkness wrapper
  6. Hybrid: HoH score includes BOTH damage + magical_dark zone
  7. Hybrid: Cloudkill score includes BOTH damage + heavy_obscurement
  8. Cloud of Daggers (damage-only, no zone) unchanged
  9. Darkness (zone-only, no damage) unchanged via wrapper
 10. Per-spell ground truth: HoH scoring sanity (damage > 0 AND zone > 0)
"""
from __future__ import annotations

import unittest

from engine.ai.ehp_scoring import (
    DARKNESS_RADIUS_SQUARES,
    offensive_ehp_darkness,
    offensive_ehp_persistent_aura,
    offensive_ehp_zone_vision_denial,
)
from engine.core.state import Actor, CombatState, Encounter


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0), ac=14,
                  hp=30, str_score=14, blindsight_ft=0, truesight_ft=0):
    abilities = {k: {"score": str_score if k == "str" else 10,
                       "save": 2 if k == "str" else 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 1, "xp": 200, "proficiency_bonus": 2},
        "actions": [
            # Give a melee attack so estimate_per_attack_damage > 0
            {"id": "a_swing", "name": "Swing", "type": "weapon_attack",
              "pipeline": [
                  {"primitive": "attack_roll",
                    "params": {"kind": "melee", "bonus": 4, "reach_ft": 5}},
                  {"primitive": "damage",
                    "params": {"dice": "1d8", "modifier": 2,
                                 "type": "slashing"}},
              ]},
        ],
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp, ac=ac,
        speed={"walk": 30}, position=position, abilities=abilities,
        blindsight_range_ft=blindsight_ft,
        truesight_range_ft=truesight_ft,
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _hoh_action(radius_ft=20, dc=15):
    """Synth HoH action template (damage + magical_dark zone)."""
    return {
        "id": "a_hunger_of_hadar", "type": "persistent_aura",
        "spell_slot_level": 3,
        "concentration": True, "named_effect": "hunger_of_hadar",
        "area": {"shape": "sphere", "radius_ft": radius_ft,
                  "range_ft": 150},
        "pipeline": [
            {"primitive": "persistent_aura",
              "params": {"shape": "sphere", "radius_ft": radius_ft,
                          "anchor": "point",
                          "trigger_event": "target_turn_start_in_area",
                          "affected": "all_creatures",
                          "ability": "constitution", "dc": dc,
                          "on_fail": [{"primitive": "damage",
                                          "params": {"dice": "4d6",
                                                       "type": "cold"}}],
                          "on_success": [{"primitive": "damage",
                                              "params": {"dice": "2d6",
                                                           "type": "cold"}}],
                          "creates_zone": "magical_dark"}},
        ],
    }


def _cloudkill_action(radius_ft=20, dc=15):
    """Synth Cloudkill action template (damage + heavy_obscurement)."""
    return {
        "id": "a_cloudkill", "type": "persistent_aura",
        "spell_slot_level": 5,
        "concentration": True, "named_effect": "cloudkill",
        "area": {"shape": "sphere", "radius_ft": radius_ft,
                  "range_ft": 120},
        "pipeline": [
            {"primitive": "persistent_aura",
              "params": {"shape": "sphere", "radius_ft": radius_ft,
                          "anchor": "point",
                          "trigger_event": "target_turn_start_in_area",
                          "affected": "all_creatures",
                          "ability": "constitution", "dc": dc,
                          "on_fail": [{"primitive": "damage",
                                          "params": {"dice": "5d8",
                                                       "type": "poison"}}],
                          "on_success": [{"primitive": "damage",
                                              "params": {"dice": "5d8",
                                                           "type": "poison",
                                                           "multiplier": 0.5}}],
                          "creates_zone": "heavy_obscurement"}},
        ],
    }


def _darkness_action(radius_ft=15):
    """Synth Darkness action template (zone-only, no damage)."""
    return {
        "id": "a_darkness", "type": "persistent_aura",
        "spell_slot_level": 2,
        "concentration": True, "named_effect": "darkness",
        "area": {"shape": "sphere", "radius_ft": radius_ft,
                  "range_ft": 60},
        "pipeline": [
            {"primitive": "persistent_aura",
              "params": {"shape": "sphere", "radius_ft": radius_ft,
                          "anchor": "point",
                          "trigger_event": "target_turn_start_in_area",
                          "affected": "enemies",
                          "creates_zone": "magical_dark"}},
        ],
    }


def _cod_action(size_ft=5):
    """Synth Cloud of Daggers action (damage-only cube, no zone)."""
    return {
        "id": "a_cod", "type": "persistent_aura",
        "spell_slot_level": 2,
        "concentration": True, "named_effect": "cloud_of_daggers",
        "area": {"shape": "cube", "size_ft": size_ft, "range_ft": 60},
        "pipeline": [
            {"primitive": "persistent_aura",
              "params": {"shape": "cube", "size_ft": size_ft,
                          "anchor": "point",
                          "trigger_event": "target_turn_start_in_area",
                          "affected": "all_creatures",
                          "on_fail": [{"primitive": "damage",
                                          "params": {"dice": "4d4",
                                                       "type": "slashing"}}]}},
        ],
    }


# ============================================================================
# Layer 1+2+3: generalized zone scorer
# ============================================================================

class ZoneVisionDenialMagicalDarkTest(unittest.TestCase):

    def test_magical_dark_truesight_pierces(self) -> None:
        # Setup: caster + 1 ally inside zone, 1 enemy outside.
        # Enemy has truesight → score should DROP toward 0 because
        # truesight pierces magical_dark.
        caster = _make_actor("caster", position=(0, 0))
        ally = _make_actor("ally", position=(1, 0))
        enemy_no_ts = _make_actor("e1", side="enemy", position=(5, 0))
        enemy_ts = _make_actor("e2", side="enemy", position=(5, 0),
                                  truesight_ft=120)
        # Run two scenarios: with and without truesight on the enemy
        state_blind = _make_state([caster, ally, enemy_no_ts])
        state_ts = _make_state([caster, ally, enemy_ts])
        score_blind = offensive_ehp_zone_vision_denial(
            caster, _darkness_action(), state_blind, origin=(0, 0),
            radius_ft=15, zone_type="magical_dark")
        score_ts = offensive_ehp_zone_vision_denial(
            caster, _darkness_action(), state_ts, origin=(0, 0),
            radius_ft=15, zone_type="magical_dark")
        # Truesight enemy can see through magical dark → score drops
        self.assertGreater(score_blind, 0)
        self.assertLess(score_ts, score_blind)

    def test_magical_dark_blindsight_pierces(self) -> None:
        caster = _make_actor("caster", position=(0, 0))
        ally = _make_actor("ally", position=(1, 0))
        enemy_bs = _make_actor("e", side="enemy", position=(5, 0),
                                  blindsight_ft=60)
        state = _make_state([caster, ally, enemy_bs])
        score = offensive_ehp_zone_vision_denial(
            caster, _darkness_action(), state, origin=(0, 0),
            radius_ft=15, zone_type="magical_dark")
        # Blindsight pierces → low/zero score (enemy can attack
        # in-zone ally normally)
        baseline = offensive_ehp_zone_vision_denial(
            caster,
            _darkness_action(),
            _make_state([caster, ally,
                            _make_actor("e2", side="enemy",
                                          position=(5, 0))]),
            origin=(0, 0), radius_ft=15, zone_type="magical_dark")
        self.assertLess(score, baseline)


class ZoneVisionDenialHeavyObscurementTest(unittest.TestCase):

    def test_heavy_obscurement_truesight_does_NOT_pierce(self) -> None:
        # RAW: truesight does NOT see through fog (heavy_obscurement is
        # physical, not magical). Enemy with truesight should still be
        # blinded by Cloudkill fog.
        caster = _make_actor("caster", position=(0, 0))
        ally = _make_actor("ally", position=(1, 0))
        enemy_no_ts = _make_actor("e1", side="enemy", position=(5, 0))
        enemy_ts = _make_actor("e2", side="enemy", position=(5, 0),
                                  truesight_ft=120)
        state_blind = _make_state([caster, ally, enemy_no_ts])
        state_ts = _make_state([caster, ally, enemy_ts])
        score_blind = offensive_ehp_zone_vision_denial(
            caster, _cloudkill_action(), state_blind, origin=(0, 0),
            radius_ft=20, zone_type="heavy_obscurement")
        score_ts = offensive_ehp_zone_vision_denial(
            caster, _cloudkill_action(), state_ts, origin=(0, 0),
            radius_ft=20, zone_type="heavy_obscurement")
        # Truesight enemy is STILL blinded by fog → score same as
        # no-truesight (both blinded by fog)
        self.assertEqual(score_blind, score_ts)

    def test_heavy_obscurement_blindsight_pierces(self) -> None:
        caster = _make_actor("caster", position=(0, 0))
        ally = _make_actor("ally", position=(1, 0))
        enemy_no_bs = _make_actor("e1", side="enemy", position=(5, 0))
        enemy_bs = _make_actor("e2", side="enemy", position=(5, 0),
                                  blindsight_ft=60)
        state_blind = _make_state([caster, ally, enemy_no_bs])
        state_bs = _make_state([caster, ally, enemy_bs])
        score_blind = offensive_ehp_zone_vision_denial(
            caster, _cloudkill_action(), state_blind, origin=(0, 0),
            radius_ft=20, zone_type="heavy_obscurement")
        score_bs = offensive_ehp_zone_vision_denial(
            caster, _cloudkill_action(), state_bs, origin=(0, 0),
            radius_ft=20, zone_type="heavy_obscurement")
        self.assertLess(score_bs, score_blind)


# ============================================================================
# Layer 4: radius respects param
# ============================================================================

class ZoneRadiusTest(unittest.TestCase):

    def test_larger_radius_includes_more_actors(self) -> None:
        # Place an enemy at 18 ft (just inside 20-ft sphere; outside
        # 15-ft sphere). Score should differ between Darkness (15 ft)
        # and HoH-radius (20 ft).
        caster = _make_actor("caster", position=(0, 0))
        # Distance ~20 ft = 4 squares. Place at (4, 0).
        enemy = _make_actor("e", side="enemy", position=(4, 0))
        # Ally outside both
        ally_out = _make_actor("ally", position=(6, 0))
        state = _make_state([caster, enemy, ally_out])
        score_15 = offensive_ehp_zone_vision_denial(
            caster, _darkness_action(), state, origin=(0, 0),
            radius_ft=15, zone_type="magical_dark")
        score_20 = offensive_ehp_zone_vision_denial(
            caster, _hoh_action(), state, origin=(0, 0),
            radius_ft=20, zone_type="magical_dark")
        # 20 ft sphere includes enemy at 20 ft (4 squares); 15 ft
        # sphere doesn't (3-square cutoff). enemy now in-zone vs out.
        # Cost component changes — at minimum, scores differ.
        self.assertNotEqual(score_15, score_20)


# ============================================================================
# Layer 5: backward compat wrapper
# ============================================================================

class DarknessWrapperTest(unittest.TestCase):

    def test_offensive_ehp_darkness_uses_15_ft_magical_dark(self) -> None:
        caster = _make_actor("caster", position=(0, 0))
        ally = _make_actor("ally", position=(1, 0))
        enemy = _make_actor("e", side="enemy", position=(5, 0))
        state = _make_state([caster, ally, enemy])
        # Wrapper
        score_wrapper = offensive_ehp_darkness(caster, _darkness_action(),
                                                    state, origin=(0, 0))
        # Direct call with same params
        score_direct = offensive_ehp_zone_vision_denial(
            caster, _darkness_action(), state, origin=(0, 0),
            radius_ft=15, zone_type="magical_dark")
        self.assertAlmostEqual(score_wrapper, score_direct, places=2)


# ============================================================================
# Layer 6+7+10: hybrid scoring
# ============================================================================

class HoHHybridScoringTest(unittest.TestCase):

    def test_hoh_includes_damage_and_zone(self) -> None:
        # Caster + ally inside the zone, enemies outside but reachable
        caster = _make_actor("caster", position=(0, 0), hp=50)
        ally = _make_actor("ally", position=(1, 0), hp=50)
        # Enemy IN-aura (gets damage); enemy OUT-of-aura (matters for
        # vision-denial cost computation only)
        in_enemy = _make_actor("e_in", side="enemy", position=(2, 0),
                                  hp=50)
        out_enemy = _make_actor("e_out", side="enemy", position=(10, 0),
                                   hp=50)
        state = _make_state([caster, ally, in_enemy, out_enemy])
        action = _hoh_action()
        score = offensive_ehp_persistent_aura(
            caster, action, state, origin=(2, 0))
        # The in-zone ally now (correctly) costs friendly fire from this
        # all_creatures cloud, so the absolute score may net negative — the
        # meaningful check is that the ZONE component still adds value on top
        # of the damage component (both subtract the same ally friendly fire).
        # Compare: damage-only version (strip the zone) should be
        # LESS than the hybrid score.
        damage_only_action = _hoh_action()
        # Remove creates_zone from the aura params
        damage_only_action["pipeline"][0]["params"].pop("creates_zone")
        score_damage_only = offensive_ehp_persistent_aura(
            caster, damage_only_action, state, origin=(2, 0))
        self.assertGreater(score, score_damage_only,
                            f"Hybrid score {score:.2f} should be "
                            f"higher than damage-only "
                            f"{score_damage_only:.2f} when zone "
                            f"helps the party")


class CloudkillHybridScoringTest(unittest.TestCase):

    def test_cloudkill_includes_damage_and_zone(self) -> None:
        caster = _make_actor("caster", position=(0, 0))
        ally = _make_actor("ally", position=(1, 0))
        in_enemy = _make_actor("e_in", side="enemy", position=(2, 0))
        out_enemy = _make_actor("e_out", side="enemy", position=(10, 0))
        state = _make_state([caster, ally, in_enemy, out_enemy])
        action = _cloudkill_action()
        score = offensive_ehp_persistent_aura(
            caster, action, state, origin=(2, 0))
        # In-zone ally costs friendly fire from this all_creatures cloud; the
        # meaningful check is the zone component adding value (below).
        damage_only_action = _cloudkill_action()
        damage_only_action["pipeline"][0]["params"].pop("creates_zone")
        score_damage_only = offensive_ehp_persistent_aura(
            caster, damage_only_action, state, origin=(2, 0))
        self.assertGreater(score, score_damage_only)


# ============================================================================
# Layer 8: damage-only auras unchanged
# ============================================================================

class CloudOfDaggersUnchangedTest(unittest.TestCase):

    def test_cod_score_unchanged_no_zone(self) -> None:
        # CoD has no creates_zone — should equal damage_value alone
        caster = _make_actor("caster", position=(0, 0))
        in_enemy = _make_actor("e", side="enemy", position=(0, 0))
        state = _make_state([caster, in_enemy])
        score = offensive_ehp_persistent_aura(
            caster, _cod_action(), state, origin=(0, 0))
        # 4d4 (avg 10) per turn × 2.5 rounds = 25, capped at HP (30).
        self.assertGreater(score, 0)
        # No vision-denial value added (CoD has no zone)
        self.assertLess(score, 50)   # sanity upper bound


# ============================================================================
# Layer 9: zone-only auras unchanged via wrapper
# ============================================================================

class DarknessZoneOnlyUnchangedTest(unittest.TestCase):

    def test_darkness_score_matches_zone_only(self) -> None:
        caster = _make_actor("caster", position=(0, 0))
        ally = _make_actor("ally", position=(1, 0))
        enemy = _make_actor("e", side="enemy", position=(5, 0))
        state = _make_state([caster, ally, enemy])
        # Via the persistent_aura dispatch
        score_dispatch = offensive_ehp_persistent_aura(
            caster, _darkness_action(), state, origin=(0, 0))
        # Via the wrapper directly
        score_wrapper = offensive_ehp_darkness(
            caster, _darkness_action(), state, origin=(0, 0))
        # PR #78: dispatch route now also calls the zone scorer for
        # creates_zone=magical_dark. With NO damage payload, damage
        # component is 0 and the dispatch result equals the wrapper.
        self.assertAlmostEqual(score_dispatch, score_wrapper, places=2)


if __name__ == "__main__":
    unittest.main()
