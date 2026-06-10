"""Save-DC Shapley attribution (engine/core/attribution.py save lane).

Extends the attack-roll attribution to save-gated damage: the CASTER keeps
the save's baseline expected value (their DC vs the target's own save bonus);
every temporary save modifier (an ally's Restrained imposing DEX-save
disadvantage, a flat save debuff, an auto-fail rider) is a contributor
credited with its exact Shapley share; realized damage splits proportionally
so credited amounts sum exactly to what happened.

Layers:
  1. Save probability math (no nat-1/nat-20 faces — mirrors _forced_save)
  2. expected_save_value (negate vs save-for-half, auto-fail/succeed, flats)
  3. Shapley on the save value function (hand-computed disadvantage case,
     symmetry of redundant disadvantage sources)
  4. Realized scaling via attribute_save_damage_event
  5. Engine integration: _forced_save damage events carry shapley_save_v1
     payloads crediting the save-debuffer; plain saves carry nothing;
     the context never leaks past the forced_save call
  6. Ledger: save-attribution shares route to enablement_ehp

Run via:
    python -m unittest tests.test_save_attribution
"""
from __future__ import annotations

import unittest

from engine.core.attribution import (
    attribute_save_damage_event, build_save_attribution_context,
    expected_save_value, group_contributions, save_success_probability,
    shapley_shares,
)
from engine.core.combat_metrics import build_contribution_ledger
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.primitives import _forced_save, _save_success_damage_ratio


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id, *, side="pc", position=(0, 0), hp=50, ac=10,
                dex_save=5):
    abilities = {
        "str": {"score": 16, "save": 3},
        "dex": {"score": 12, "save": dex_save},
        "con": {"score": 14, "save": 2},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 10, "save": 0},
        "cha": {"score": 10, "save": 0},
    }
    template = {
        "id": f"tpl_{actor_id}", "name": actor_id,
        "abilities": abilities,
        "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
        "actions": [],
    }
    return Actor(
        id=actor_id, name=actor_id, template=template, side=side,
        hp_current=hp, hp_max=hp, ac=ac,
        speed={"walk": 30}, position=position, abilities=abilities,
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


def _save_dis(source):
    return {"kind": "save_disadvantage", "value": 0, "source": source}


def _save_flat(value, source):
    return {"kind": "save_bonus", "value": value, "source": source}


_WEB_SRC = {"type": "condition", "condition_id": "co_restrained",
            "source_creature_id": "wizard"}
_BANE_SRC = {"type": "action_buff", "action_id": "a_bane",
             "caster_id": "bard", "named_effect": "bane"}

# Half-on-success damage shape (the dragon-breath / fireball runtime params).
_HALF_PARAMS = {
    "on_fail": [{"primitive": "damage",
                 "params": {"dice": "8d6", "modifier": 0, "type": "fire"}}],
    "on_success": [{"primitive": "damage",
                    "params": {"dice": "8d6", "modifier": 0, "type": "fire",
                               "multiplier": 0.5}}],
}


# ============================================================================
# Layer 1: save probability math
# ============================================================================

class SaveProbabilityTest(unittest.TestCase):
    def test_normal(self):
        # need 11+ on the d20 → 10 of 20 faces
        self.assertAlmostEqual(save_success_probability(11), 0.5)

    def test_advantage(self):
        self.assertAlmostEqual(save_success_probability(11, "advantage"), 0.75)

    def test_disadvantage(self):
        self.assertAlmostEqual(
            save_success_probability(11, "disadvantage"), 0.25)

    def test_no_nat_20_auto_success(self):
        # Saves have no auto-success face: an impossible DC is impossible.
        self.assertAlmostEqual(save_success_probability(25), 0.0)

    def test_no_nat_1_auto_fail(self):
        # And no auto-fail face: a trivial DC always succeeds.
        self.assertAlmostEqual(save_success_probability(1), 1.0)
        self.assertAlmostEqual(save_success_probability(-3), 1.0)


class ExpectedSaveValueTest(unittest.TestCase):
    def test_negate_spell(self):
        # DC 15 vs +5 save → needed 10, p_succ = .55 → expected = p_fail = .45
        self.assertAlmostEqual(expected_save_value(15, 5, []), 0.45)

    def test_save_for_half(self):
        # .45 + .55 × .5 = .725
        self.assertAlmostEqual(
            expected_save_value(15, 5, [], success_ratio=0.5), 0.725)

    def test_disadvantage_raises_value(self):
        # p_succ = .55² = .3025 → value = .6975 + .3025 × .5 = .84875
        self.assertAlmostEqual(
            expected_save_value(15, 5, [_save_dis(_WEB_SRC)],
                                success_ratio=0.5), 0.84875)

    def test_flat_save_bonus_lowers_value(self):
        # +2 to the target's save lowers expected damage.
        base = expected_save_value(15, 5, [])
        buffed = expected_save_value(15, 5, [_save_flat(2, _BANE_SRC)])
        self.assertLess(buffed, base)

    def test_auto_fail(self):
        self.assertAlmostEqual(
            expected_save_value(
                15, 5, [{"kind": "save_auto_fail", "value": 0,
                         "source": _WEB_SRC}], success_ratio=0.5), 1.0)

    def test_auto_succeed(self):
        self.assertAlmostEqual(
            expected_save_value(
                15, 5, [{"kind": "save_auto_succeed", "value": 0,
                         "source": _BANE_SRC}], success_ratio=0.5), 0.5)

    def test_auto_fail_trumps_auto_succeed(self):
        # Mirrors SaveModifierResult.net_outcome_override.
        effects = [
            {"kind": "save_auto_fail", "value": 0, "source": _WEB_SRC},
            {"kind": "save_auto_succeed", "value": 0, "source": _BANE_SRC},
        ]
        self.assertAlmostEqual(expected_save_value(15, 5, effects), 1.0)


# ============================================================================
# Layers 2+3: Shapley properties + realized scaling on the save lane
# ============================================================================

class SaveShapleyTest(unittest.TestCase):
    def _value_fn(self, success_ratio=0.5):
        def value_fn(effects):
            return expected_save_value(15, 5, effects,
                                       success_ratio=success_ratio)
        return value_fn

    def test_hand_computed_disadvantage_share(self):
        """Baseline .725; with the wizard's disadvantage .84875 —
        the whole .12375 surplus is the wizard's."""
        contributors, _ = group_contributions([_save_dis(_WEB_SRC)])
        baseline, phis = shapley_shares(contributors, self._value_fn())
        self.assertAlmostEqual(baseline, 0.725)
        self.assertAlmostEqual(phis[0], 0.12375)

    def test_redundant_disadvantage_split_equally(self):
        """Two creatures each imposing save disadvantage: 5e doesn't stack
        disadvantage, so the surplus exists once — Shapley symmetry splits
        it equally between the two redundant sources."""
        src_b = {"type": "condition", "condition_id": "co_poisoned_save",
                 "source_creature_id": "druid"}
        contributors, _ = group_contributions(
            [_save_dis(_WEB_SRC), _save_dis(src_b)])
        baseline, phis = shapley_shares(contributors, self._value_fn())
        self.assertAlmostEqual(phis[0], phis[1])
        self.assertAlmostEqual(baseline + sum(phis), 0.84875)

    def test_efficiency(self):
        contributors, _ = group_contributions(
            [_save_dis(_WEB_SRC), _save_flat(-3, _BANE_SRC)])
        value_fn = self._value_fn()
        baseline, phis = shapley_shares(contributors, value_fn)
        full = value_fn([e for c in contributors for e in c["effects"]])
        self.assertAlmostEqual(baseline + sum(phis), full)

    def test_realized_scaling_matches_proportions(self):
        ctx = build_save_attribution_context(
            [_save_dis(_WEB_SRC)], dc=15, save_bonus=5,
            success_ratio=0.5, caster_id="sorcerer")
        # 84.875 realized → baseline 72.5, wizard 12.375 (the .725/.12375
        # decomposition scaled by 100).
        attr = attribute_save_damage_event(ctx, 84.875)
        self.assertEqual(attr["model"], "shapley_save_v1")
        self.assertAlmostEqual(attr["baseline"], 72.5)
        self.assertAlmostEqual(attr["shares"][0]["amount"], 12.375)
        self.assertEqual(attr["shares"][0]["source_id"], "wizard")

    def test_shares_sum_to_realized_amount(self):
        ctx = build_save_attribution_context(
            [_save_dis(_WEB_SRC), _save_flat(-3, _BANE_SRC)],
            dc=15, save_bonus=5, success_ratio=0.5, caster_id="sorcerer")
        attr = attribute_save_damage_event(ctx, 23.0)
        total = attr["baseline"] + sum(s["amount"] for s in attr["shares"])
        self.assertAlmostEqual(total, 23.0)

    def test_no_contributors_no_context(self):
        ctx = build_save_attribution_context(
            [], dc=15, save_bonus=5, success_ratio=0.5, caster_id="sorcerer")
        self.assertIsNone(ctx)

    def test_target_own_save_buff_negative_share_for_offense(self):
        """A save buff sourced by the TARGET's side (e.g., Bless on saves)
        produces a NEGATIVE share — the offense ledger ignores it (defensive
        attribution is the v2 lane), but the math must stay closed."""
        ally_src = {"type": "action_buff", "action_id": "a_bless",
                    "caster_id": "enemy_priest"}
        ctx = build_save_attribution_context(
            [_save_flat(4, ally_src)], dc=15, save_bonus=5,
            success_ratio=0.5, caster_id="sorcerer")
        attr = attribute_save_damage_event(ctx, 10.0)
        self.assertLess(attr["shares"][0]["amount"], 0)
        total = attr["baseline"] + sum(s["amount"] for s in attr["shares"])
        self.assertAlmostEqual(total, 10.0)


class SuccessRatioTest(unittest.TestCase):
    def test_half_on_success(self):
        self.assertAlmostEqual(_save_success_damage_ratio(_HALF_PARAMS), 0.5)

    def test_negate_on_success(self):
        params = {"on_fail": _HALF_PARAMS["on_fail"], "on_success": []}
        self.assertAlmostEqual(_save_success_damage_ratio(params), 0.0)

    def test_no_damage_at_all(self):
        # Pure-control save (Hold Person shape): ratio 0, harmless.
        params = {"on_fail": [{"primitive": "apply_condition",
                               "params": {"condition_id": "co_paralyzed"}}],
                  "on_success": []}
        self.assertAlmostEqual(_save_success_damage_ratio(params), 0.0)


# ============================================================================
# Layer 4: engine integration — _forced_save damage carries attribution
# ============================================================================

def _restrained_save_modifier(owner_id):
    """The co_restrained DEX-save-disadvantage effect shape, sourced by the
    wizard (who cast the Web)."""
    return {
        "primitive": "save_modifier",
        "params": {"when": "save_ability == dexterity",
                   "modifier": "disadvantage"},
        "lifetime": "until_condition_ends",
        "source": dict(_WEB_SRC),
        "applied_at_round": 1,
        "owner_id": owner_id,
    }


class EngineIntegrationTest(unittest.TestCase):
    def _cast_save_spell(self, caster, target, state, params=None):
        state.current_attack = {
            "actor": caster, "target": target,
            "action": {"id": "a_test_save_spell"},
            "state": None,
        }
        bus = EventBus()
        p = {"ability": "dexterity", "dc": 15, "affected": "current_target"}
        p.update(params or _HALF_PARAMS)
        return _forced_save(p, state, bus)

    def test_debuffed_save_damage_carries_attribution(self):
        sorcerer = _make_actor("sorcerer")
        wizard = _make_actor("wizard", position=(2, 0))
        dragon = _make_actor("dragon", side="enemy", position=(0, 3), hp=2000)
        state = _make_state([sorcerer, wizard, dragon])
        dragon.active_modifiers.append(_restrained_save_modifier("dragon"))
        # Half-on-success means EVERY cast deals damage; one cast suffices.
        self._cast_save_spell(sorcerer, dragon, state)
        dmg_events = [e for e in state.event_log
                      if e.get("event") == "damage_dealt"]
        self.assertTrue(dmg_events)
        attr = dmg_events[-1].get("attribution")
        self.assertIsNotNone(attr)
        self.assertEqual(attr["model"], "shapley_save_v1")
        by_id = {s["source_id"]: s for s in attr["shares"]}
        self.assertIn("wizard", by_id)
        self.assertGreater(by_id["wizard"]["amount"], 0)
        self.assertIn("co_restrained", by_id["wizard"]["labels"])
        total = attr["baseline"] + sum(s["amount"] for s in attr["shares"])
        self.assertAlmostEqual(total, dmg_events[-1]["amount"], places=5)

    def test_plain_save_carries_no_attribution(self):
        sorcerer = _make_actor("sorcerer")
        dragon = _make_actor("dragon", side="enemy", position=(0, 3), hp=2000)
        state = _make_state([sorcerer, dragon])
        self._cast_save_spell(sorcerer, dragon, state)
        dmg_events = [e for e in state.event_log
                      if e.get("event") == "damage_dealt"]
        self.assertTrue(dmg_events)
        self.assertNotIn("attribution", dmg_events[-1])

    def test_wrong_ability_modifier_does_not_contribute(self):
        """A DEX-save disadvantage modifier doesn't touch a CON save."""
        sorcerer = _make_actor("sorcerer")
        dragon = _make_actor("dragon", side="enemy", position=(0, 3), hp=2000)
        state = _make_state([sorcerer, dragon])
        dragon.active_modifiers.append(_restrained_save_modifier("dragon"))
        self._cast_save_spell(sorcerer, dragon, state, params={
            "ability": "constitution", "dc": 15,
            "affected": "current_target", **_HALF_PARAMS})
        dmg_events = [e for e in state.event_log
                      if e.get("event") == "damage_dealt"]
        self.assertTrue(dmg_events)
        self.assertNotIn("attribution", dmg_events[-1])

    def test_context_does_not_leak_after_forced_save(self):
        sorcerer = _make_actor("sorcerer")
        wizard = _make_actor("wizard", position=(2, 0))
        dragon = _make_actor("dragon", side="enemy", position=(0, 3), hp=2000)
        state = _make_state([sorcerer, wizard, dragon])
        dragon.active_modifiers.append(_restrained_save_modifier("dragon"))
        self._cast_save_spell(sorcerer, dragon, state)
        self.assertNotIn("save_attribution_ctx", state.current_attack)


# ============================================================================
# Layer 6: ledger routing — save shares become enablement eHP
# ============================================================================

class LedgerRoutingTest(unittest.TestCase):
    def test_save_enablement_routed_to_debuffer(self):
        sorcerer = _make_actor("sorcerer")
        wizard = _make_actor("wizard", position=(2, 0))
        dragon = _make_actor("dragon", side="enemy", position=(0, 3), hp=2000)
        state = _make_state([sorcerer, wizard, dragon])
        dragon.active_modifiers.append(_restrained_save_modifier("dragon"))
        state.current_attack = {
            "actor": sorcerer, "target": dragon,
            "action": {"id": "a_test_save_spell"}, "state": None,
        }
        state.event_log.append(
            {"event": "turn_start", "round": 1, "actor": "sorcerer"})
        _forced_save({"ability": "dexterity", "dc": 15,
                      "affected": "current_target", **_HALF_PARAMS},
                     state, EventBus())
        led = build_contribution_ledger(state)
        pa = led["per_actor"]
        self.assertGreater(pa["wizard"]["enablement_ehp"], 0)
        self.assertAlmostEqual(pa["sorcerer"]["enabled_by_others"],
                               pa["wizard"]["enablement_ehp"])
        # Closed ledger: side's attributed offense == side's realized damage.
        pc_dealt = sum(r["damage_dealt"] for r in pa.values()
                       if r["side"] == "pc")
        pc_attr = sum(r["attributed_offense"] for r in pa.values()
                      if r["side"] == "pc")
        self.assertAlmostEqual(pc_dealt, pc_attr)


if __name__ == "__main__":
    unittest.main()
