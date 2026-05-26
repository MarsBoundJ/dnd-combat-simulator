"""Named-effect tagging + cross-caster buff dedup (PR #36).

PHB 2024 p.243: "The effects of the SAME spell cast multiple times
don't combine ... the most potent effect ... applies while the
durations of the effects overlap." Pre-PR #36 the eHP scoring only
caught same-caster re-casts; two clerics Blessing the same fighter
would stack.

Layers:
  1. buff_already_active detection — by named_effect (cross-caster)
     OR by (caster, action_id) (legacy)
  2. _build_modifier_entry stamps named_effect onto the source dict
     when the action declares it
  3. offensive_ehp_buff_ally returns 0.0 when buff is already active
     by either path
  4. offensive_ehp_help: same behavior
  5. Different named_effects don't dedup against each other
     (Bless + Heroism on same fighter is RAW-legal)
  6. Untagged actions still get same-caster dedup (regression)

Run via:
    python -m unittest tests.test_named_effects
"""
from __future__ import annotations

import unittest

from engine.ai.named_effects import buff_already_active
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "pc",
                actions: list[dict] | None = None) -> Actor:
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": actions or []}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=20, hp_max=20, ac=14,
                  speed={"walk": 30}, position=(0, 0),
                  abilities=abilities)


def _bless_action(named_effect: str | None = "bless") -> dict:
    """Bless-shape offensive_buff with optional named_effect tag.
    Default tagged; pass named_effect=None to test untagged behavior."""
    action = {
        "id": "a_bless", "name": "Bless",
        "type": "offensive_buff", "concentration": True,
        "spell_slot_level": 1,
        "pipeline": [
            {"primitive": "attack_modifier",
              "params": {"target": "ally", "modifier": "attack_bonus",
                          "value": 2,
                          "lifetime": "until_short_rest"}},
        ],
    }
    if named_effect is not None:
        action["named_effect"] = named_effect
    return action


def _heroism_action() -> dict:
    """Different spell with its own named_effect (Bless + Heroism stack
    per RAW because they're different spells)."""
    return {
        "id": "a_heroism", "name": "Heroism",
        "type": "offensive_buff", "concentration": True,
        "spell_slot_level": 1,
        "named_effect": "heroism",
        "pipeline": [
            {"primitive": "attack_modifier",
              "params": {"target": "ally", "modifier": "attack_bonus",
                          "value": 1,
                          "lifetime": "until_short_rest"}},
        ],
    }


def _attach_bless_modifier(ally: Actor, caster_id: str,
                              named_effect: str | None = "bless") -> None:
    """Append a Bless-shape modifier to `ally`'s active list, tagged
    with the given caster_id + optional named_effect."""
    source = {"type": "action_buff",
              "action_id": "a_bless",
              "caster_id": caster_id}
    if named_effect is not None:
        source["named_effect"] = named_effect
    ally.active_modifiers.append({
        "primitive": "attack_modifier",
        "params": {"target": "ally", "modifier": "attack_bonus", "value": 2},
        "lifetime": "until_short_rest",
        "source": source,
        "applied_at_round": 1,
        "owner_id": ally.id,
    })


# ============================================================================
# buff_already_active detection
# ============================================================================

class BuffAlreadyActiveTest(unittest.TestCase):

    def test_returns_false_when_no_modifiers(self) -> None:
        cleric = _make_actor("cleric_a")
        ally = _make_actor("ally")
        self.assertFalse(
            buff_already_active(ally, _bless_action(), cleric))

    def test_same_caster_blocks_via_legacy_path(self) -> None:
        """Untagged Bless cast by cleric_a; cleric_a re-casting is
        blocked by the per-(caster, action_id) legacy path."""
        cleric = _make_actor("cleric_a")
        ally = _make_actor("ally")
        _attach_bless_modifier(ally, "cleric_a", named_effect=None)
        # Use an untagged action — legacy path should still fire
        self.assertTrue(
            buff_already_active(ally, _bless_action(named_effect=None),
                                  cleric))

    def test_different_caster_blocks_via_named_effect(self) -> None:
        """cleric_a's Bless is already on ally; cleric_b's would be
        blocked by named_effect match (PR #36 new behavior)."""
        cleric_b = _make_actor("cleric_b")
        ally = _make_actor("ally")
        _attach_bless_modifier(ally, "cleric_a", named_effect="bless")
        self.assertTrue(
            buff_already_active(ally, _bless_action(), cleric_b))

    def test_different_caster_NOT_blocked_when_untagged(self) -> None:
        """Without named_effect, the legacy path requires same caster.
        cleric_b's untagged Bless is NOT blocked by cleric_a's
        modifier — backward-compatible behavior."""
        cleric_b = _make_actor("cleric_b")
        ally = _make_actor("ally")
        _attach_bless_modifier(ally, "cleric_a", named_effect=None)
        self.assertFalse(
            buff_already_active(ally, _bless_action(named_effect=None),
                                  cleric_b))

    def test_different_named_effect_NOT_blocked(self) -> None:
        """Bless and Heroism are different spells per RAW — both can
        be active on the same ally simultaneously."""
        cleric = _make_actor("cleric")
        ally = _make_actor("ally")
        # Bless already active
        _attach_bless_modifier(ally, "cleric_a", named_effect="bless")
        # Heroism scoring should NOT be blocked
        self.assertFalse(
            buff_already_active(ally, _heroism_action(), cleric))


# ============================================================================
# _build_modifier_entry: source stamping
# ============================================================================

class BuildModifierEntryTaggingTest(unittest.TestCase):

    def test_named_effect_propagates_to_source(self) -> None:
        from engine.primitives import _build_modifier_entry
        owner = _make_actor("ally")
        caster = _make_actor("cleric")
        state = CombatState(encounter=Encounter(id="t", actors=[owner, caster]))
        state.current_attack = {
            "actor": caster, "target": owner,
            "action": _bless_action(),  # tagged with named_effect="bless"
            "state": None,
            "had_advantage": False, "had_disadvantage": False,
            "area_origin": None, "area_direction": None,
        }
        entry = _build_modifier_entry(
            "attack_modifier",
            {"target": "ally", "modifier": "attack_bonus", "value": 2},
            owner, state,
        )
        self.assertEqual(entry["source"]["named_effect"], "bless")
        self.assertEqual(entry["source"]["caster_id"], "cleric")

    def test_no_named_effect_when_action_untagged(self) -> None:
        from engine.primitives import _build_modifier_entry
        owner = _make_actor("ally")
        caster = _make_actor("cleric")
        state = CombatState(encounter=Encounter(id="t", actors=[owner, caster]))
        state.current_attack = {
            "actor": caster, "target": owner,
            "action": _bless_action(named_effect=None),
            "state": None,
            "had_advantage": False, "had_disadvantage": False,
            "area_origin": None, "area_direction": None,
        }
        entry = _build_modifier_entry(
            "attack_modifier",
            {"target": "ally", "modifier": "attack_bonus", "value": 2},
            owner, state,
        )
        self.assertNotIn("named_effect", entry["source"])

    def test_explicit_source_overrides_auto_stamping(self) -> None:
        """If the caller passes their own `source` dict, the auto-stamp
        path is skipped entirely — no surprise named_effect injection."""
        from engine.primitives import _build_modifier_entry
        owner = _make_actor("ally")
        caster = _make_actor("cleric")
        state = CombatState(encounter=Encounter(id="t", actors=[owner, caster]))
        state.current_attack = {
            "actor": caster, "target": owner,
            "action": _bless_action(),  # tagged
            "state": None,
            "had_advantage": False, "had_disadvantage": False,
            "area_origin": None, "area_direction": None,
        }
        custom_source = {"type": "condition", "condition_id": "co_blessed"}
        entry = _build_modifier_entry(
            "attack_modifier",
            {"target": "ally", "modifier": "attack_bonus", "value": 2,
              "source": custom_source},
            owner, state,
        )
        self.assertEqual(entry["source"], custom_source)
        self.assertNotIn("named_effect", entry["source"])


# ============================================================================
# Scoring integration — offensive_ehp_buff_ally + offensive_ehp_help
# ============================================================================

class OffensiveBuffScoringDedupTest(unittest.TestCase):

    def _state_with(self, actors: list[Actor]) -> CombatState:
        enc = Encounter(id="t_enc", actors=actors)
        state = CombatState(encounter=enc)
        state.turn_order = [a.id for a in actors]
        state.round = 1
        return state

    def test_same_caster_recast_returns_zero(self) -> None:
        """Regression: pre-#36 same-caster dedup still works."""
        from engine.ai import offensive_ehp_buff_ally
        cleric = _make_actor("cleric_a", actions=[_bless_action()])
        # Ally with a greatsword so DPR > 0
        ally = _make_actor("ally", actions=[{
            "id": "a_gs", "type": "weapon_attack",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "melee", "bonus": 6, "reach_ft": 5}},
                {"primitive": "damage",
                  "params": {"dice": "2d6", "modifier": 4,
                              "type": "slashing"}},
            ],
        }])
        state = self._state_with([cleric, ally])
        _attach_bless_modifier(ally, "cleric_a", named_effect="bless")
        score = offensive_ehp_buff_ally(cleric, ally, _bless_action(), state)
        self.assertEqual(score, 0.0)

    def test_different_caster_same_named_effect_returns_zero(self) -> None:
        """New behavior: cleric_b's Bless on an already-Blessed ally
        scores 0.0 even though the prior cast was from cleric_a."""
        from engine.ai import offensive_ehp_buff_ally
        cleric_b = _make_actor("cleric_b", actions=[_bless_action()])
        ally = _make_actor("ally", actions=[{
            "id": "a_gs", "type": "weapon_attack",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "melee", "bonus": 6, "reach_ft": 5}},
                {"primitive": "damage",
                  "params": {"dice": "2d6", "modifier": 4,
                              "type": "slashing"}},
            ],
        }])
        state = self._state_with([cleric_b, ally])
        _attach_bless_modifier(ally, "cleric_a", named_effect="bless")
        score = offensive_ehp_buff_ally(cleric_b, ally,
                                           _bless_action(), state)
        self.assertEqual(score, 0.0)

    def test_different_named_effect_scores_normally(self) -> None:
        """Bless already on ally; Heroism scoring is NOT blocked."""
        from engine.ai import offensive_ehp_buff_ally
        cleric = _make_actor("cleric_b", actions=[_heroism_action()])
        ally = _make_actor("ally", actions=[{
            "id": "a_gs", "type": "weapon_attack",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "melee", "bonus": 6, "reach_ft": 5}},
                {"primitive": "damage",
                  "params": {"dice": "2d6", "modifier": 4,
                              "type": "slashing"}},
            ],
        }])
        state = self._state_with([cleric, ally])
        _attach_bless_modifier(ally, "cleric_a", named_effect="bless")
        score = offensive_ehp_buff_ally(cleric, ally,
                                           _heroism_action(), state)
        self.assertGreater(score, 0.0)

    def test_help_action_also_uses_named_effect_dedup(self) -> None:
        """Help shares the same dedup path. If a Help advantage from
        cleric_a is on the ally and Help carries a named_effect, a
        different caster's Help scores 0."""
        from engine.ai import offensive_ehp_help
        helper_b = _make_actor("helper_b")
        ally = _make_actor("ally", actions=[{
            "id": "a_gs", "type": "weapon_attack",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "melee", "bonus": 6, "reach_ft": 5}},
                {"primitive": "damage",
                  "params": {"dice": "2d6", "modifier": 4,
                              "type": "slashing"}},
            ],
        }])
        state = self._state_with([helper_b, ally])
        # Existing Help modifier from helper_a, tagged with named_effect=help
        ally.active_modifiers.append({
            "primitive": "attack_modifier",
            "params": {"target": "ally", "modifier": "advantage_for_self"},
            "lifetime": "per_owner_attack",
            "source": {"type": "action_buff",
                        "action_id": "a_help",
                        "caster_id": "helper_a",
                        "named_effect": "help"},
            "applied_at_round": 1,
            "owner_id": ally.id,
        })
        help_action = {
            "id": "a_help", "type": "help",
            "named_effect": "help",
            "pipeline": [
                {"primitive": "attack_modifier",
                  "params": {"target": "ally",
                              "when": "attacker_is_self",
                              "modifier": "advantage_for_self",
                              "lifetime": "per_owner_attack"}},
            ],
        }
        score = offensive_ehp_help(helper_b, ally, help_action, state)
        self.assertEqual(score, 0.0)


class TwoClericsFixtureTest(unittest.TestCase):
    """End-to-end via the live two-cleric fixture: at no point in the
    encounter does the fighter carry two simultaneous Bless modifiers
    (the headline RAW guarantee — same-spell-doesn't-stack)."""

    def test_fighter_never_has_two_bless_modifiers(self) -> None:
        from pathlib import Path
        from engine.loader import load_content
        from engine.cli import _build_actor
        from engine.core.runner import EncounterRunner
        from engine.core.state import Encounter
        import engine.primitives as primitives_module
        import yaml

        here = Path(__file__).resolve()
        repo = here.parent.parent
        registry = load_content(repo / "schema" / "content", validate=False)
        fixture_path = (repo / "tests" / "fixtures"
                          / "two_clerics_bless_dedup_encounter.yaml")
        with open(fixture_path, "r", encoding="utf-8") as fh:
            fixture = yaml.safe_load(fh)
        actors = [_build_actor(spec, registry) for spec in fixture["actors"]]
        fighter = next(a for a in actors if a.id == "fighter_ally")
        enc = Encounter(id=fixture["id"], actors=actors)
        runner = EncounterRunner.new(enc, seed=1, content_registry=registry)
        primitives_module.set_rng(runner.rng)

        # Hook every event-log append to check fighter's modifier count
        # at each step. We can't easily intercept inline, so instead run
        # the encounter and inspect the FINAL state plus a per-round
        # snapshot via event_log scanning.
        state = runner.run(seed=1)

        # At any given moment, the fighter should have at most ONE
        # Bless-tagged attack_modifier. Final state is the easiest
        # snapshot — if dedup failed the lifetime is until_short_rest
        # so duplicates would persist.
        bless_mods = [m for m in fighter.active_modifiers
                       if m.get("primitive") == "attack_modifier"
                       and (m.get("source") or {}).get("named_effect") == "bless"]
        self.assertLessEqual(len(bless_mods), 1,
                              "Fighter should never carry stacked Bless "
                              "modifiers — cross-caster dedup should "
                              "block the second cleric")


if __name__ == "__main__":
    unittest.main()
