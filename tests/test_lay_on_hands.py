"""Lay on Hands tests (PR #83).

Layers:
  1. f_lay_on_hands YAML loads + c_paladin L1 wires it
  2. pc_schema derives lay_on_hands_pool_remaining = 5 × level
  3. Pool max stamped for long rest restore
  4. _lay_on_hands primitive: heals min(damage, pool); drains pool
  5. _lay_on_hands primitive: no-op when pool empty
  6. _lay_on_hands primitive: no-op when target at full HP
  7. _lay_on_hands primitive: never overheals beyond hp_max
  8. apply_long_rest restores Paladin pool to max
  9. AI scoring: returns value based on min(missing, pool) ×
     desperation_multiplier
 10. AI scoring: returns 0 when pool empty
 11. AI scoring: returns 0 when target at full HP
 12. pc_schema auto-attaches a_lay_on_hands action template at L1
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.ai.defensive_ehp import defensive_ehp_healing
from engine.core.events import EventBus
from engine.core.rest import apply_long_rest
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.primitives import _lay_on_hands


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


# ============================================================================
# Helpers
# ============================================================================

def _make_paladin(actor_id="paly", *, level=5, position=(0, 0),
                     pool_remaining=None):
    if pool_remaining is None:
        pool_remaining = 5 * level
    abilities = {
        "str": {"score": 16, "save": 3},
        "dex": {"score": 12, "save": 1},
        "con": {"score": 14, "save": 2},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 12, "save": 1},
        "cha": {"score": 16, "save": 3},
    }
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [],
        "levels": {"paladin": level},
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side="pc",
        hp_current=40, hp_max=40, ac=18,
        speed={"walk": 30}, position=position, abilities=abilities,
        resources={"lay_on_hands_pool_remaining": pool_remaining,
                     "lay_on_hands_pool_max": 5 * level},
    )


def _make_ally(actor_id="ally", *, position=(1, 0), hp=20, hp_max=40):
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [
            {"id": "a_sword", "type": "weapon_attack",
              "pipeline": [
                  {"primitive": "attack_roll",
                    "params": {"kind": "melee", "bonus": 5,
                                 "reach_ft": 5}},
                  {"primitive": "damage",
                    "params": {"dice": "1d8", "modifier": 3,
                                 "type": "slashing"}},
              ]},
        ],
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side="pc",
        hp_current=hp, hp_max=hp_max, ac=14,
        speed={"walk": 30}, position=position, abilities=abilities,
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _loh_action():
    return {
        "id": "a_lay_on_hands", "type": "heal",
        "slot": "bonus_action",
        "pipeline": [
            {"primitive": "lay_on_hands",
              "params": {"target": "ally"}},
        ],
    }


# ============================================================================
# Layer 1+12: YAML + class wiring + pc_schema integration
# ============================================================================

class FeatureLoadingTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_f_lay_on_hands_loads(self) -> None:
        feature = self.registry.get("feature", "f_lay_on_hands")
        action = feature["action_template"]
        self.assertEqual(action["id"], "a_lay_on_hands")
        self.assertEqual(action["type"], "heal")
        self.assertEqual(action["slot"], "bonus_action")
        self.assertEqual(action["pipeline"][0]["primitive"],
                          "lay_on_hands")

    def test_c_paladin_l1_lists_lay_on_hands(self) -> None:
        paly = self.registry.get("class", "c_paladin")
        l1_row = next(r for r in paly["level_table"]
                          if r["level"] == 1)
        self.assertIn("f_lay_on_hands", l1_row["features"])


class PcSchemaIntegrationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def _build(self, level):
        from engine.pc_schema import build_pc_template, derive_pc_resources
        pc_spec = {
            "class": "c_paladin", "level": level,
            "ability_scores": {"str": 16, "dex": 12, "con": 14,
                                 "int": 10, "wis": 12, "cha": 16},
            "weapons": [{"id": "longsword", "name": "Longsword",
                          "damage_dice": "1d8",
                          "damage_type": "slashing",
                          "attack_ability": "str"}],
        }
        template = build_pc_template(pc_spec, self.registry)
        resources = derive_pc_resources(pc_spec, self.registry)
        return template, resources

    def test_l1_pool_is_5(self) -> None:
        _, resources = self._build(level=1)
        self.assertEqual(resources["lay_on_hands_pool_remaining"], 5)
        self.assertEqual(resources["lay_on_hands_pool_max"], 5)

    def test_l5_pool_is_25(self) -> None:
        _, resources = self._build(level=5)
        self.assertEqual(resources["lay_on_hands_pool_remaining"], 25)
        self.assertEqual(resources["lay_on_hands_pool_max"], 25)

    def test_l11_pool_is_55(self) -> None:
        _, resources = self._build(level=11)
        self.assertEqual(resources["lay_on_hands_pool_remaining"], 55)

    def test_a_lay_on_hands_action_attached_at_l1(self) -> None:
        template, _ = self._build(level=1)
        ids = {a.get("id") for a in template["actions"]}
        self.assertIn("a_lay_on_hands", ids)


# ============================================================================
# Layer 4-7: _lay_on_hands primitive
# ============================================================================

class LayOnHandsPrimitiveTest(unittest.TestCase):

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(1))

    def test_heals_min_of_damage_and_pool(self) -> None:
        # Paladin L5: pool 25. Ally missing 20 HP. Heals 20, pool → 5.
        paly = _make_paladin(level=5)
        ally = _make_ally(hp=20, hp_max=40)
        state = _make_state([paly, ally])
        state.current_attack = {"actor": paly, "target": ally,
                                  "action": _loh_action(), "state": None}
        _lay_on_hands({}, state, EventBus())
        self.assertEqual(ally.hp_current, 40)
        self.assertEqual(paly.resources["lay_on_hands_pool_remaining"],
                          5)

    def test_pool_capped_when_damage_exceeds_pool(self) -> None:
        # Paladin L1: pool 5. Ally missing 30 HP. Heals 5, pool → 0.
        paly = _make_paladin(level=1)
        ally = _make_ally(hp=10, hp_max=40)
        state = _make_state([paly, ally])
        state.current_attack = {"actor": paly, "target": ally,
                                  "action": _loh_action(), "state": None}
        _lay_on_hands({}, state, EventBus())
        self.assertEqual(ally.hp_current, 15)
        self.assertEqual(paly.resources["lay_on_hands_pool_remaining"],
                          0)

    def test_noop_when_pool_empty(self) -> None:
        paly = _make_paladin(level=5, pool_remaining=0)
        ally = _make_ally(hp=10, hp_max=40)
        state = _make_state([paly, ally])
        state.current_attack = {"actor": paly, "target": ally,
                                  "action": _loh_action(), "state": None}
        _lay_on_hands({}, state, EventBus())
        # No heal, no log event for lay_on_hands
        self.assertEqual(ally.hp_current, 10)
        events = [e for e in state.event_log
                    if e.get("event") == "lay_on_hands"]
        self.assertEqual(len(events), 0)

    def test_noop_when_target_at_full_hp(self) -> None:
        paly = _make_paladin(level=5)
        ally = _make_ally(hp=40, hp_max=40)
        state = _make_state([paly, ally])
        state.current_attack = {"actor": paly, "target": ally,
                                  "action": _loh_action(), "state": None}
        _lay_on_hands({}, state, EventBus())
        self.assertEqual(paly.resources["lay_on_hands_pool_remaining"],
                          25)
        events = [e for e in state.event_log
                    if e.get("event") == "lay_on_hands"]
        self.assertEqual(len(events), 0)

    def test_never_overheals_past_hp_max(self) -> None:
        # Pool large, ally missing 5 HP → heal exactly 5, pool drains 5.
        paly = _make_paladin(level=10)   # pool 50
        ally = _make_ally(hp=35, hp_max=40)
        state = _make_state([paly, ally])
        state.current_attack = {"actor": paly, "target": ally,
                                  "action": _loh_action(), "state": None}
        _lay_on_hands({}, state, EventBus())
        self.assertEqual(ally.hp_current, 40)
        self.assertEqual(paly.resources["lay_on_hands_pool_remaining"],
                          45)

    def test_logs_event(self) -> None:
        paly = _make_paladin(level=5)
        ally = _make_ally(hp=20, hp_max=40)
        state = _make_state([paly, ally])
        state.current_attack = {"actor": paly, "target": ally,
                                  "action": _loh_action(), "state": None}
        _lay_on_hands({}, state, EventBus())
        events = [e for e in state.event_log
                    if e.get("event") == "lay_on_hands"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["amount"], 20)
        self.assertEqual(events[0]["pool_remaining"], 5)


# ============================================================================
# Layer 8: long rest refresh
# ============================================================================

class LongRestRefreshTest(unittest.TestCase):

    def test_paladin_pool_refreshes_on_long_rest(self) -> None:
        paly = _make_paladin(level=5, pool_remaining=3)
        paly.template["derived_from_pc_schema"] = {
            "class": "c_paladin", "level": 5}
        state = _make_state([paly])
        summary = apply_long_rest(paly, state)
        self.assertEqual(
            paly.resources["lay_on_hands_pool_remaining"], 25)
        self.assertIn("lay_on_hands_pool_refresh", summary)

    def test_non_paladin_skips_refresh(self) -> None:
        # Fighter actor (no pool resources) shouldn't get the
        # refresh summary entry.
        from engine.core.state import Actor
        abilities = {k: {"score": 10, "save": 0}
                      for k in ("str", "dex", "con", "int", "wis", "cha")}
        fighter = Actor(
            id="f", name="f", template={
                "id": "f", "abilities": abilities,
                "cr": {"proficiency_bonus": 2}, "actions": [],
                "derived_from_pc_schema": {
                    "class": "c_fighter", "level": 5},
            },
            side="pc", hp_current=40, hp_max=40, ac=18,
            speed={"walk": 30}, abilities=abilities,
        )
        state = _make_state([fighter])
        summary = apply_long_rest(fighter, state)
        self.assertNotIn("lay_on_hands_pool_refresh", summary)


# ============================================================================
# Layer 9-11: AI scoring
# ============================================================================

class ScoringTest(unittest.TestCase):

    def test_scores_pool_capped_amount(self) -> None:
        # L1 Paladin (pool 5) heals ally at hp=20/40 → amount = 5
        # × desperation_multiplier(0.5) = 5 × 1.0 = 5
        paly = _make_paladin(level=1, pool_remaining=5)
        ally = _make_ally(hp=20, hp_max=40)
        state = _make_state([paly, ally])
        score = defensive_ehp_healing(paly, ally, _loh_action(), state)
        # Should be exactly 5 (pool-capped, desperation multiplier 1.0
        # at exactly 50% HP).
        self.assertEqual(score, 5.0)

    def test_scores_missing_capped_amount(self) -> None:
        # L5 Paladin (pool 25) heals ally at hp=35/40 → amount =
        # min(5, 25) = 5. Desperation multiplier at 35/40 = 0.875
        # is 1.0 (above 0.5).
        paly = _make_paladin(level=5, pool_remaining=25)
        ally = _make_ally(hp=35, hp_max=40)
        state = _make_state([paly, ally])
        score = defensive_ehp_healing(paly, ally, _loh_action(), state)
        self.assertEqual(score, 5.0)

    def test_desperation_multiplier_boosts_low_hp(self) -> None:
        # Ally at hp=4/40 (10%) → desperation multiplier = 1.4
        # L1 pool 5, missing 36, amount = min(36, 5) = 5
        # score = 5 × 1.4 = 7.0
        paly = _make_paladin(level=1, pool_remaining=5)
        ally = _make_ally(hp=4, hp_max=40)
        state = _make_state([paly, ally])
        score = defensive_ehp_healing(paly, ally, _loh_action(), state)
        # 1.0 + (0.5 - 0.1) = 1.4
        self.assertAlmostEqual(score, 7.0, places=2)

    def test_zero_when_pool_empty(self) -> None:
        paly = _make_paladin(level=5, pool_remaining=0)
        ally = _make_ally(hp=10, hp_max=40)
        state = _make_state([paly, ally])
        score = defensive_ehp_healing(paly, ally, _loh_action(), state)
        self.assertEqual(score, 0.0)

    def test_zero_when_target_at_full_hp(self) -> None:
        paly = _make_paladin(level=5)
        ally = _make_ally(hp=40, hp_max=40)
        state = _make_state([paly, ally])
        score = defensive_ehp_healing(paly, ally, _loh_action(), state)
        self.assertEqual(score, 0.0)


if __name__ == "__main__":
    unittest.main()
