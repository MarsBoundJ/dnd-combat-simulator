"""Zealous Presence tests (Path of the Zealot, Barbarian L10).

A Bonus-Action that grants Advantage on attack rolls and saving throws to
up to 10 allies within 60 ft until the start of the Zealot's next turn.
1/long rest (resource_uses_remaining/max).

Layers:
  1. Resource seeding at L10 (PC schema).
  2. Primitive: buffs allies within 60 ft, skips self, decrements use.
  3. Modifiers are correctly typed (attack_modifier + save_modifier).
  4. Long-rest refresh restores the use.
  5. No-op when pool empty.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import derive_pc_resources
import engine.primitives as primitives_module

_REPO = Path(__file__).resolve().parent.parent


def _registry():
    return load_content(_REPO / "schema" / "content", validate=True,
                        schema_root=_REPO / "schema")


def _ab():
    return {k: {"score": 10, "save": 0}
            for k in ("str", "dex", "con", "int", "wis", "cha")}


def _actor(aid, side="pc", pos=(0, 0), alive=True):
    ab = _ab()
    a = Actor(id=aid, name=aid,
              template={"id": f"t_{aid}", "name": aid, "abilities": ab,
                        "cr": {"proficiency_bonus": 2}, "actions": [],
                        "features_known": []},
              side=side, hp_current=50 if alive else 0, hp_max=100,
              ac=12, position=pos, speed={"walk": 30}, abilities=ab)
    return a


def _zealot(pos=(0, 0)):
    ab = _ab()
    a = Actor(id="z", name="z",
              template={"id": "t_z", "name": "z", "abilities": ab,
                        "cr": {"proficiency_bonus": 2}, "actions": [],
                        "features_known": ["f_zealous_presence"]},
              side="pc", hp_current=50, hp_max=100, ac=12,
              position=pos, speed={"walk": 30}, abilities=ab)
    a.resources = {"zealous_presence_uses_remaining": 1,
                   "zealous_presence_uses_max": 1}
    return a


def _state(actors, zealot):
    st = CombatState(encounter=Encounter(id="t", actors=actors))
    st.turn_order = [x.id for x in actors]
    st.round = 1
    st.content_registry = _registry()
    st.current_attack = {"actor": zealot, "target": zealot}
    return st


def _run_zealous_presence(zealot, allies):
    actors = [zealot] + allies
    st = _state(actors, zealot)
    from engine.primitives import _zealous_presence
    from engine.core.events import EventBus
    _zealous_presence({}, st, EventBus())
    return st


class ResourceSeedingTest(unittest.TestCase):

    def test_resource_seeded_at_l10(self):
        spec = {
            "id": "z", "class": "c_barbarian", "level": 10,
            "subclass": "sc_path_of_the_zealot",
            "ability_scores": {"str": 18, "dex": 14, "con": 16,
                               "int": 8, "wis": 10, "cha": 8},
            "weapons": [{"id": "ga", "name": "GA", "damage_dice": "1d12",
                         "damage_type": "slashing", "attack_ability": "str",
                         "reach_ft": 5}],
        }
        r = derive_pc_resources(spec, _registry())
        self.assertEqual(r.get("zealous_presence_uses_remaining"), 1)
        self.assertEqual(r.get("zealous_presence_uses_max"), 1)

    def test_no_resource_below_l10(self):
        spec = {
            "id": "z", "class": "c_barbarian", "level": 6,
            "subclass": "sc_path_of_the_zealot",
            "ability_scores": {"str": 18, "dex": 14, "con": 16,
                               "int": 8, "wis": 10, "cha": 8},
            "weapons": [{"id": "ga", "name": "GA", "damage_dice": "1d12",
                         "damage_type": "slashing", "attack_ability": "str",
                         "reach_ft": 5}],
        }
        r = derive_pc_resources(spec, _registry())
        self.assertIsNone(r.get("zealous_presence_uses_remaining"))


class PrimitiveTest(unittest.TestCase):

    # Positions are grid squares (×5 ft). (6,0) = 30 ft, (12,0) = 60 ft,
    # (13,0) = 65 ft. All existing tests use (0,0) grid squares.

    def test_buffs_ally_within_range(self):
        z = _zealot()
        ally = _actor("a1", side="pc", pos=(6, 0))  # 30 ft
        _run_zealous_presence(z, [ally])
        prim_names = [m.get("primitive") for m in ally.active_modifiers]
        self.assertIn("attack_modifier", prim_names)
        self.assertIn("save_modifier", prim_names)

    def test_skips_self(self):
        z = _zealot()
        _run_zealous_presence(z, [])
        self.assertEqual(z.active_modifiers, [])

    def test_skips_enemies(self):
        z = _zealot()
        enemy = _actor("e1", side="enemy", pos=(2, 0))  # 10 ft
        _run_zealous_presence(z, [enemy])
        self.assertEqual(enemy.active_modifiers, [])

    def test_skips_ally_beyond_60ft(self):
        z = _zealot()
        far_ally = _actor("a2", side="pc", pos=(13, 0))  # 65 ft — out of range
        _run_zealous_presence(z, [far_ally])
        self.assertEqual(far_ally.active_modifiers, [])

    def test_primitive_does_not_decrement(self):
        # Resource consumption is the feature_use gate's job now, not the
        # primitive's — the primitive only applies the buff.
        z = _zealot()
        ally = _actor("a1", side="pc", pos=(2, 0))  # 10 ft
        _run_zealous_presence(z, [ally])
        self.assertEqual(z.resources["zealous_presence_uses_remaining"], 1)

    def test_caps_at_ten_allies(self):
        z = _zealot()
        # All at 5 ft (grid square 1)
        allies = [_actor(f"a{i}", side="pc", pos=(1, 0)) for i in range(15)]
        _run_zealous_presence(z, allies)
        buffed = [a for a in allies if a.active_modifiers]
        self.assertEqual(len(buffed), 10)

    def test_modifier_lifetime_is_source_caster_next_turn(self):
        z = _zealot()
        ally = _actor("a1", side="pc", pos=(2, 0))  # 10 ft
        _run_zealous_presence(z, [ally])
        lifetimes = {m.get("lifetime") for m in ally.active_modifiers}
        self.assertEqual(lifetimes, {"until_source_caster_next_turn"})

    def test_modifier_caster_id_set(self):
        z = _zealot()
        ally = _actor("a1", side="pc", pos=(2, 0))  # 10 ft
        _run_zealous_presence(z, [ally])
        for m in ally.active_modifiers:
            self.assertEqual((m.get("source") or {}).get("caster_id"), "z")

    def test_event_logged(self):
        z = _zealot()
        ally = _actor("a1", side="pc", pos=(2, 0))  # 10 ft
        actors = [z, ally]
        st = _state(actors, z)
        from engine.primitives import _zealous_presence
        _zealous_presence({}, st, EventBus())
        events = [e.get("event") for e in st.event_log]
        self.assertIn("zealous_presence", events)


class LongRestRefreshTest(unittest.TestCase):

    def test_long_rest_restores_use(self):
        from engine.core.rest import _refresh_generic_uses_to_max
        z = _zealot()
        z.resources["zealous_presence_uses_remaining"] = 0
        result = _refresh_generic_uses_to_max(
            z, "zealous_presence_uses_remaining", "zealous_presence_uses_max")
        self.assertEqual(result, {"new_total": 1})
        self.assertEqual(z.resources["zealous_presence_uses_remaining"], 1)

    def test_noop_for_non_zealot(self):
        from engine.core.rest import _refresh_generic_uses_to_max
        p = _actor("p")
        result = _refresh_generic_uses_to_max(
            p, "zealous_presence_uses_remaining", "zealous_presence_uses_max")
        self.assertIsNone(result)


class RageRefundTest(unittest.TestCase):
    """Generic Rage-use refund (shared with Intimidating Presence).

    RAW: "...unless you expend a use of your Rage (no action required) to
    restore your use of it." Modeled via `rage_refund: true` on the action;
    the feature_use gate spends a Rage use to restore the pool when empty,
    keeping one Rage in reserve.
    """

    def _action(self):
        return {
            "id": "a_zealous_presence",
            "feature_use": "zealous_presence_uses_remaining",
            "rage_refund": True,
        }

    def test_available_with_charge(self):
        from engine.core.feature_uses import is_action_available
        z = _zealot()
        z.resources["zealous_presence_uses_remaining"] = 1
        self.assertTrue(is_action_available(z, self._action()))

    def test_available_when_empty_if_rage_refundable(self):
        from engine.core.feature_uses import is_action_available
        z = _zealot()
        z.resources["zealous_presence_uses_remaining"] = 0
        z.resources["rage_uses_remaining"] = 3
        self.assertTrue(is_action_available(z, self._action()))

    def test_unavailable_when_empty_and_low_rage(self):
        # Only one Rage use left — kept in reserve, no refund offered.
        from engine.core.feature_uses import is_action_available
        z = _zealot()
        z.resources["zealous_presence_uses_remaining"] = 0
        z.resources["rage_uses_remaining"] = 1
        self.assertFalse(is_action_available(z, self._action()))

    def test_unavailable_when_empty_and_no_rage(self):
        from engine.core.feature_uses import is_action_available
        z = _zealot()
        z.resources["zealous_presence_uses_remaining"] = 0
        z.resources["rage_uses_remaining"] = 0
        self.assertFalse(is_action_available(z, self._action()))

    def test_non_refundable_action_not_available_when_empty(self):
        from engine.core.feature_uses import is_action_available
        z = _zealot()
        z.resources["zealous_presence_uses_remaining"] = 0
        z.resources["rage_uses_remaining"] = 3
        action = {"id": "a_zealous_presence",
                  "feature_use": "zealous_presence_uses_remaining"}
        self.assertFalse(is_action_available(z, action))

    def test_consume_normal_path_no_refund(self):
        from engine.core.feature_uses import consume_use_or_rage_refund
        z = _zealot()
        z.resources["zealous_presence_uses_remaining"] = 1
        z.resources["rage_uses_remaining"] = 3
        st = _state([z], z)
        consume_use_or_rage_refund(z, self._action(), st)
        self.assertEqual(z.resources["zealous_presence_uses_remaining"], 0)
        self.assertEqual(z.resources["rage_uses_remaining"], 3)  # untouched

    def test_consume_refund_path_spends_rage(self):
        from engine.core.feature_uses import consume_use_or_rage_refund
        z = _zealot()
        z.resources["zealous_presence_uses_remaining"] = 0
        z.resources["rage_uses_remaining"] = 3
        st = _state([z], z)
        consume_use_or_rage_refund(z, self._action(), st)
        # Restored to max (1) then consumed → 0; one Rage use spent.
        self.assertEqual(z.resources["zealous_presence_uses_remaining"], 0)
        self.assertEqual(z.resources["rage_uses_remaining"], 2)

    def test_refund_logs_event(self):
        from engine.core.feature_uses import consume_use_or_rage_refund
        z = _zealot()
        z.resources["zealous_presence_uses_remaining"] = 0
        z.resources["rage_uses_remaining"] = 3
        st = _state([z], z)
        consume_use_or_rage_refund(z, self._action(), st)
        events = [e.get("event") for e in st.event_log]
        self.assertIn("rage_use_refund", events)


if __name__ == "__main__":
    unittest.main()
