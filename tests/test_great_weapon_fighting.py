"""Great Weapon Fighting tests (PR #49).

Layers:
  1. _roll_dice_expr_with_floor primitive helper:
     - floor=0 / floor=1 behaves identically to plain _roll_dice_expr
     - floor=3 clamps 1s and 2s to 3
     - Floor never lowers a high roll
  2. _damage primitive routes through the floor when
     `damage_die_floor` is in params
     - Without the floor, low rolls pass through
     - With the floor, low rolls are clamped per-die
     - Crit doubles dice AND applies floor to both rolls
     - Modifier still adds on top (floor is dice-only, RAW)
  3. pc_schema._build_weapon_action gate:
     - GWF + 2H melee → damage_die_floor=3 baked into damage params
     - GWF + 1H melee → no floor
     - GWF + ranged → no floor
     - Non-GWF + 2H melee → no floor
  4. Validation:
     - great_weapon_fighting accepted by _validate_fighting_style

Run via:
    python -m unittest tests.test_great_weapon_fighting
"""
from __future__ import annotations

import random
import unittest
from unittest.mock import MagicMock

from engine.core.state import Actor, CombatState, Encounter
from engine.core.events import EventBus
from engine.pc_schema import (
    build_pc_template, _validate_fighting_style, _KNOWN_FIGHTING_STYLES,
)
from engine.primitives import (
    _roll_dice_expr, _roll_dice_expr_with_floor, _damage,
)
import engine.primitives as _P


# ============================================================================
# Mock registry (mirrors test_fighting_style)
# ============================================================================

class _MockRegistry:
    def __init__(self, classes):
        self._classes = classes
    def get(self, etype, eid):
        if etype != "class":
            raise KeyError(etype)
        if eid not in self._classes:
            raise KeyError(eid)
        return self._classes[eid]


def _fighter_class_def() -> dict:
    return {
        "id": "c_fighter", "name": "Fighter",
        "core_traits": {"hit_die": "d10",
                         "save_proficiencies": ["strength", "constitution"]},
        "level_table": [
            {"level": 1, "proficiency_bonus": 2,
              "features": ["f_fighting_style", "f_second_wind"],
              "class_resources": {"second_wind_uses": 2}},
        ],
    }


def _registry():
    return _MockRegistry({"c_fighter": _fighter_class_def()})


def _base_spec(fighting_style: str | None = None,
                  weapons: list[dict] | None = None) -> dict:
    spec = {
        "class": "c_fighter", "level": 1,
        "ability_scores": {"str": 16, "dex": 14, "con": 14,
                            "int": 10, "wis": 10, "cha": 10},
        "weapons": weapons if weapons is not None else [{
            "id": "a_greatsword", "name": "Greatsword",
            "attack_ability": "str", "damage_dice": "2d6",
            "damage_type": "slashing", "reach_ft": 5,
            "two_handed": True,
        }],
    }
    if fighting_style is not None:
        spec["fighting_style"] = fighting_style
    return spec


# ============================================================================
# Layer 1: _roll_dice_expr_with_floor helper
# ============================================================================

class RollDiceWithFloorTest(unittest.TestCase):

    def test_floor_zero_matches_plain_roll(self) -> None:
        # With seed parity, floor=0 and plain _roll_dice_expr produce
        # identical sequences (no clamping branch taken).
        rng_a = random.Random(42)
        rng_b = random.Random(42)
        for _ in range(50):
            a = _roll_dice_expr("2d6", rng_a)
            b = _roll_dice_expr_with_floor("2d6", 0, rng_b)
            self.assertEqual(a, b)

    def test_floor_one_matches_plain_roll(self) -> None:
        # floor=1 is also a no-op since every d-X roll is already ≥ 1.
        rng_a = random.Random(7)
        rng_b = random.Random(7)
        for _ in range(50):
            a = _roll_dice_expr("3d8", rng_a)
            b = _roll_dice_expr_with_floor("3d8", 1, rng_b)
            self.assertEqual(a, b)

    def test_floor_three_clamps_ones_and_twos(self) -> None:
        # Force a sequence of 1s and 2s via a mock RNG.
        rng = MagicMock()
        rng.randint.side_effect = [1, 2, 1, 2, 1, 2]
        # 6d6 with floor=3 → each clamped to 3 → 18
        total = _roll_dice_expr_with_floor("6d6", 3, rng)
        self.assertEqual(total, 18)

    def test_floor_does_not_lower_high_rolls(self) -> None:
        rng = MagicMock()
        rng.randint.side_effect = [6, 6, 5, 4]
        total = _roll_dice_expr_with_floor("4d6", 3, rng)
        # No clamp applied — all rolls ≥ floor.
        self.assertEqual(total, 21)

    def test_floor_mixed(self) -> None:
        rng = MagicMock()
        # 1 → 3, 6 → 6, 2 → 3, 4 → 4
        rng.randint.side_effect = [1, 6, 2, 4]
        total = _roll_dice_expr_with_floor("4d6", 3, rng)
        self.assertEqual(total, 3 + 6 + 3 + 4)


# ============================================================================
# Layer 2: _damage primitive routes through the floor
# ============================================================================

def _make_actor(actor_id: str) -> Actor:
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                 "abilities": abilities,
                 "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                 "actions": []}
    return Actor(id=actor_id, name=actor_id, template=template, side="pc",
                  hp_current=100, hp_max=100, ac=14,
                  speed={"walk": 30}, position=(0, 0),
                  abilities=abilities)


def _damage_call(params, *, is_crit=False, rng=None):
    """Build a minimal state for _damage() and invoke it. Returns the
    target actor (with hp_current mutated by the call).
    """
    attacker = _make_actor("atk")
    target = _make_actor("tgt")
    enc = Encounter(id="t", actors=[attacker, target])
    state = CombatState(encounter=enc)
    state.current_attack = {
        "actor": attacker, "target": target,
        "state": "crit" if is_crit else "hit",
    }
    bus = EventBus()

    saved = _P._rng
    if rng is not None:
        _P.set_rng(rng)
    try:
        _damage(params, state, bus)
    finally:
        _P.set_rng(saved)
    return target


class DamagePrimitiveFloorTest(unittest.TestCase):

    def test_no_floor_passes_through_low_rolls(self) -> None:
        # Mock RNG returning 1s — without floor, total should reflect that.
        rng = MagicMock()
        rng.randint.side_effect = [1, 1]    # 2d6 → 2
        target = _damage_call(
            {"dice": "2d6", "modifier": 3, "type": "slashing"},
            rng=rng)
        # 2 (dice) + 3 (mod) = 5 damage off 100 HP → 95
        self.assertEqual(target.hp_current, 95)

    def test_floor_three_clamps_low_dice_rolls(self) -> None:
        rng = MagicMock()
        rng.randint.side_effect = [1, 2]    # 2d6 floored = 6
        target = _damage_call(
            {"dice": "2d6", "modifier": 3, "type": "slashing",
              "damage_die_floor": 3},
            rng=rng)
        # 6 (floored dice) + 3 (mod) = 9 damage off 100 → 91
        self.assertEqual(target.hp_current, 91)

    def test_crit_doubles_dice_and_applies_floor_to_both(self) -> None:
        rng = MagicMock()
        # First roll: 1, 2 → 3+3 = 6. Crit second roll: 1, 1 → 3+3 = 6.
        rng.randint.side_effect = [1, 2, 1, 1]
        target = _damage_call(
            {"dice": "2d6", "modifier": 3, "type": "slashing",
              "damage_die_floor": 3},
            is_crit=True,
            rng=rng)
        # 6 + 6 + 3 (mod, not doubled) = 15 damage → 85
        self.assertEqual(target.hp_current, 85)

    def test_modifier_unaffected_by_floor(self) -> None:
        # The +modifier is a flat add, never clamped (it's not a die roll).
        rng = MagicMock()
        rng.randint.side_effect = [6, 6]
        target = _damage_call(
            {"dice": "2d6", "modifier": 0, "type": "slashing",
              "damage_die_floor": 3},
            rng=rng)
        # 12 + 0 = 12 damage. Floor irrelevant because all rolls > 3.
        self.assertEqual(target.hp_current, 88)


# ============================================================================
# Layer 3: pc_schema gates damage_die_floor onto qualifying weapons only
# ============================================================================

class PCSchemaGWFGateTest(unittest.TestCase):

    def test_gwf_plus_two_handed_melee_bakes_floor(self) -> None:
        spec = _base_spec(fighting_style="great_weapon_fighting")
        template = build_pc_template(spec, _registry())
        damage_step = template["actions"][0]["pipeline"][1]
        self.assertEqual(damage_step["params"].get("damage_die_floor"), 3)

    def test_gwf_plus_one_handed_melee_no_floor(self) -> None:
        spec = _base_spec(fighting_style="great_weapon_fighting",
                           weapons=[{
                               "id": "a_longsword", "name": "Longsword",
                               "attack_ability": "str",
                               "damage_dice": "1d8",
                               "damage_type": "slashing",
                               "reach_ft": 5,
                               # no two_handed flag → 1H
                           }])
        template = build_pc_template(spec, _registry())
        damage_step = template["actions"][0]["pipeline"][1]
        self.assertNotIn("damage_die_floor", damage_step["params"])

    def test_gwf_plus_ranged_no_floor(self) -> None:
        # Crossbow with two_handed=True is RANGED — RAW excludes ranged
        # from GWF entirely. Our gate is "melee + 2H" so the ranged
        # branch trumps two_handed.
        spec = _base_spec(fighting_style="great_weapon_fighting",
                           weapons=[{
                               "id": "a_heavy_crossbow",
                               "name": "Heavy Crossbow",
                               "attack_ability": "dex",
                               "damage_dice": "1d10",
                               "damage_type": "piercing",
                               "range_ft": 100,
                               "two_handed": True,
                           }])
        template = build_pc_template(spec, _registry())
        damage_step = template["actions"][0]["pipeline"][1]
        self.assertNotIn("damage_die_floor", damage_step["params"])

    def test_no_style_plus_two_handed_melee_no_floor(self) -> None:
        spec = _base_spec()    # no fighting_style
        template = build_pc_template(spec, _registry())
        damage_step = template["actions"][0]["pipeline"][1]
        self.assertNotIn("damage_die_floor", damage_step["params"])

    def test_dueling_plus_two_handed_no_floor(self) -> None:
        # Different style: confirm we only floor on GWF, not all styles.
        spec = _base_spec(fighting_style="dueling")
        template = build_pc_template(spec, _registry())
        damage_step = template["actions"][0]["pipeline"][1]
        self.assertNotIn("damage_die_floor", damage_step["params"])


# ============================================================================
# Layer 4: validation
# ============================================================================

class ValidateGWFTest(unittest.TestCase):

    def test_gwf_is_known(self) -> None:
        self.assertIn("great_weapon_fighting", _KNOWN_FIGHTING_STYLES)

    def test_gwf_validate_passes(self) -> None:
        self.assertEqual(
            _validate_fighting_style("great_weapon_fighting"),
            "great_weapon_fighting")

    def test_gwf_recorded_on_template(self) -> None:
        spec = _base_spec(fighting_style="great_weapon_fighting")
        template = build_pc_template(spec, _registry())
        self.assertEqual(
            template["derived_from_pc_schema"]["fighting_style"],
            "great_weapon_fighting")


if __name__ == "__main__":
    unittest.main()
