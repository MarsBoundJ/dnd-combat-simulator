"""RP Constraints v1 tests — Hard Filters / Forced Choices / Weighted Preferences.

Five layers:
  1. Library + active-constraint resolution (read template, severity / priority
     overrides, unknown-id skip, hard_filter severity locked at 1.0)
  2. Hard Filters (Tier 1) — intersection semantics, empty result legal,
     pacifist_strict removes damage candidates
  3. Forced Choices (Tier 2) — score boost on qualifying candidates;
     priority resolution when multiple trigger; untriggered = no-op
  4. Weighted Preferences (Tier 3) — additive cumulative; negative severity
     for penalties; resource_hoarder penalizes spell-using actions
  5. Behavioral integration — pacifist PC Passes turn; heal_priority
     forces healing even when attack scores higher otherwise

Run via:
    python -m unittest tests.test_rp_constraints
"""
from __future__ import annotations

import random
import unittest

from engine.ai import (
    CANONICAL_CONSTRAINTS, get_active_constraints,
    apply_rp_hard_filters, apply_forced_choice_boosts,
    apply_weighted_preferences, apply_rp_score_modifications,
    score_candidates_v1,
)
from engine.core.pipeline import generate_candidates
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Test helpers
# ============================================================================

def _make_actor(actor_id: str, side: str = "pc", hp: int = 50,
                hp_current: int | None = None,
                ac: int = 15, abilities: dict | None = None,
                actions: list[dict] | None = None,
                rp_constraints: list[dict] | None = None,
                archetype: str | None = None,
                template_extras: dict | None = None) -> Actor:
    abilities = abilities or {
        "str": {"score": 10, "save": 0},
        "dex": {"score": 14, "save": 2},
        "con": {"score": 12, "save": 1},
        "int": {"score": 10, "save": 0},
        "wis": {"score": 14, "save": 2},
        "cha": {"score": 10, "save": 0},
    }
    template = {"id": f"tpl_{actor_id}", "name": actor_id,
                "abilities": abilities,
                "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                "actions": actions or []}
    bp: dict = {}
    if archetype:
        bp["archetype"] = archetype
    if rp_constraints is not None:
        bp["rp_constraints"] = rp_constraints
    if bp:
        template["behavior_profile"] = bp
    if template_extras:
        template.update(template_extras)
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                  hp_current=hp if hp_current is None else hp_current,
                  hp_max=hp, ac=ac, abilities=abilities)


def _state_with(actors: list[Actor], round_num: int = 1) -> CombatState:
    enc = Encounter(id="t_enc", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = round_num
    return state


def _weapon_attack(action_id: str, bonus: int = 5, dice: str = "1d8",
                    modifier: int = 0, is_sig: bool = False) -> dict:
    action = {
        "id": action_id, "name": action_id, "type": "weapon_attack",
        "pipeline": [
            {"primitive": "attack_roll",
              "params": {"kind": "melee", "bonus": bonus, "reach_ft": 5}},
            {"primitive": "damage",
              "params": {"dice": dice, "modifier": modifier, "type": "slashing"},
              "when": {"event": "damage_roll",
                        "condition": "combat.attack_state == hit"}},
        ],
    }
    if is_sig:
        action["is_signature"] = True
    return action


def _heal_action(action_id: str = "a_cure", dice: str = "2d8") -> dict:
    return {
        "id": action_id, "name": action_id, "type": "heal",
        "pipeline": [{"primitive": "heal",
                      "params": {"target": "ally", "dice": dice,
                                  "modifier_source": "actor.wis_mod"}}],
    }


def _spell_attack(action_id: str = "a_hold") -> dict:
    """A spell-shape action — has a forced_save primitive (the proxy
    resource_hoarder uses to detect 'this uses a spell slot')."""
    return {
        "id": action_id, "name": action_id, "type": "hard_control",
        "pipeline": [{
            "primitive": "forced_save",
            "params": {"ability": "wisdom", "dc": 13,
                        "on_fail": [{"primitive": "apply_condition",
                                      "params": {"condition_id": "co_paralyzed"}}]},
        }],
    }


# ============================================================================
# Library + active-constraint resolution
# ============================================================================

class LibraryAndResolutionTest(unittest.TestCase):

    def test_canonical_library_has_four_v1_constraints(self) -> None:
        # v1 ships 4 of the 12 canonical constraints (one+ of each type)
        for cid in ("pacifist_strict", "heal_priority",
                     "signature_first", "resource_hoarder"):
            self.assertIn(cid, CANONICAL_CONSTRAINTS,
                           f"Missing v1 canonical constraint {cid}")

    def test_no_rp_constraints_returns_empty_active(self) -> None:
        actor = _make_actor("a")
        self.assertEqual(get_active_constraints(actor), [])

    def test_unknown_constraint_id_silently_skipped(self) -> None:
        actor = _make_actor("a", rp_constraints=[{"id": "not_a_real_constraint"}])
        self.assertEqual(get_active_constraints(actor), [])

    def test_default_severity_pulled_from_library(self) -> None:
        actor = _make_actor("a", rp_constraints=[{"id": "heal_priority"}])
        actives = get_active_constraints(actor)
        self.assertEqual(len(actives), 1)
        self.assertAlmostEqual(actives[0].severity, 0.70)
        self.assertEqual(actives[0].priority, 80)

    def test_per_actor_severity_override(self) -> None:
        actor = _make_actor("a", rp_constraints=[
            {"id": "heal_priority", "severity": 0.5, "priority": 99},
        ])
        active = get_active_constraints(actor)[0]
        self.assertAlmostEqual(active.severity, 0.5)
        self.assertEqual(active.priority, 99)

    def test_hard_filter_severity_locked_at_1pt0(self) -> None:
        """Per §6.3, Hard Filter severity is locked at 100% binary; user
        attempts to override are ignored."""
        actor = _make_actor("a", rp_constraints=[
            {"id": "pacifist_strict", "severity": 0.5},   # tries to lower
        ])
        self.assertEqual(get_active_constraints(actor)[0].severity, 1.0)


# ============================================================================
# Tier 1 — Hard Filters
# ============================================================================

class HardFilterTest(unittest.TestCase):

    def test_pacifist_filters_out_damage_actions(self) -> None:
        attack = _weapon_attack("a_sword")
        heal = _heal_action("a_cure")
        pacifist = _make_actor("p", side="pc",
                                 actions=[attack, heal],
                                 rp_constraints=[{"id": "pacifist_strict"}])
        ally = _make_actor("ally", side="pc", hp=30, hp_current=15)
        enemy = _make_actor("e", side="enemy")
        state = _state_with([pacifist, ally, enemy])

        # Generate all candidates first (attack vs enemy + heal vs allies)
        candidates = generate_candidates(pacifist, state)
        self.assertTrue(any(c["kind"] == "weapon_attack" for c in candidates),
                         "Setup: attack candidates should exist before filtering")

        filtered = apply_rp_hard_filters(candidates, pacifist, state)
        # All weapon_attack candidates removed; heal candidates remain
        self.assertTrue(all(c["kind"] != "weapon_attack" for c in filtered),
                         "Pacifist should have all damage candidates removed")
        self.assertTrue(any(c["kind"] == "heal" for c in filtered),
                         "Heal candidates should remain")

    def test_no_constraints_passthrough(self) -> None:
        attack = _weapon_attack("a_sword")
        actor = _make_actor("a", side="pc", actions=[attack])
        enemy = _make_actor("e", side="enemy")
        state = _state_with([actor, enemy])
        candidates = generate_candidates(actor, state)
        filtered = apply_rp_hard_filters(candidates, actor, state)
        self.assertEqual(len(filtered), len(candidates))

    def test_filter_can_empty_set(self) -> None:
        """A pacifist with ONLY attack actions has zero survivors."""
        attack = _weapon_attack("a_sword")
        pacifist = _make_actor("p", side="pc",
                                 actions=[attack],
                                 rp_constraints=[{"id": "pacifist_strict"}])
        enemy = _make_actor("e", side="enemy")
        state = _state_with([pacifist, enemy])
        candidates = generate_candidates(pacifist, state)
        filtered = apply_rp_hard_filters(candidates, pacifist, state)
        self.assertEqual(filtered, [],
                          "Pacifist with only attacks should have empty set")

    def test_multiattack_with_damage_subaction_filtered(self) -> None:
        """A multiattack whose sub-actions deal damage should also be
        filtered by pacifist_strict."""
        attack = _weapon_attack("a_sword")
        multi = {"id": "a_multi", "type": "multiattack",
                  "count": 2, "sub_actions": ["a_sword"]}
        pacifist = _make_actor("p", side="pc",
                                 actions=[attack, multi],
                                 rp_constraints=[{"id": "pacifist_strict"}])
        enemy = _make_actor("e", side="enemy")
        state = _state_with([pacifist, enemy])
        candidates = generate_candidates(pacifist, state)
        filtered = apply_rp_hard_filters(candidates, pacifist, state)
        self.assertEqual(filtered, [],
                          "Both single-attack and multiattack should be filtered")


# ============================================================================
# Tier 2 — Forced Choices
# ============================================================================

class ForcedChoiceTest(unittest.TestCase):

    def test_heal_priority_boosts_qualifying_heal_when_ally_wounded(self) -> None:
        heal = _heal_action("a_cure")
        attack = _weapon_attack("a_mace", dice="1d6", modifier=1)
        cleric = _make_actor("c", side="pc",
                              actions=[attack, heal],
                              rp_constraints=[{"id": "heal_priority"}])
        ally = _make_actor("ally", side="pc", hp=30, hp_current=10)  # 33% < 50%
        enemy = _make_actor("e", side="enemy", hp=30, ac=15)
        state = _state_with([cleric, ally, enemy])

        # Score with NO constraint applied (baseline)
        baseline_cleric = _make_actor("baseline", side="pc",
                                         actions=[attack, heal])
        baseline_state = _state_with([baseline_cleric, ally, enemy])
        baseline_scored = score_candidates_v1(
            generate_candidates(baseline_cleric, baseline_state),
            baseline_cleric, baseline_state,
        )

        # Score with heal_priority active
        scored = score_candidates_v1(
            generate_candidates(cleric, state), cleric, state,
        )

        # Find best heal candidate score in each list
        def _best_heal_score(scored_list):
            heals = [s for s, c in scored_list if c["kind"] == "heal"]
            return max(heals) if heals else 0.0

        baseline_best_heal = _best_heal_score(baseline_scored)
        boosted_best_heal = _best_heal_score(scored)
        self.assertGreater(boosted_best_heal, baseline_best_heal,
                            "heal_priority should boost heal candidate scores "
                            f"(baseline {baseline_best_heal}, "
                            f"boosted {boosted_best_heal})")

    def test_heal_priority_no_boost_when_no_wounded_ally(self) -> None:
        """If all allies are above 50% HP, the trigger does not fire."""
        heal = _heal_action("a_cure")
        cleric = _make_actor("c", side="pc", actions=[heal],
                              rp_constraints=[{"id": "heal_priority"}])
        healthy_ally = _make_actor("ally", side="pc", hp=30, hp_current=30)
        state = _state_with([cleric, healthy_ally])

        scored = [(5.0, {"kind": "heal", "actor": cleric,
                          "target": healthy_ally,
                          "action": heal})]
        boosted = apply_forced_choice_boosts(scored, cleric, state)
        # No change — trigger did not fire
        self.assertEqual(boosted[0][0], 5.0)

    def test_signature_first_only_fires_round_one(self) -> None:
        sig = _weapon_attack("a_sig", is_sig=True)
        plain = _weapon_attack("a_plain")
        actor = _make_actor("a", side="pc",
                              actions=[sig, plain],
                              rp_constraints=[{"id": "signature_first"}])
        enemy = _make_actor("e", side="enemy")

        # Round 1: signature gets boost
        state_r1 = _state_with([actor, enemy], round_num=1)
        scored_r1 = [
            (10.0, {"kind": "weapon_attack", "actor": actor,
                     "action": sig, "target": enemy}),
            (10.0, {"kind": "weapon_attack", "actor": actor,
                     "action": plain, "target": enemy}),
        ]
        boosted_r1 = apply_forced_choice_boosts(scored_r1, actor, state_r1)
        self.assertGreater(boosted_r1[0][0], 10.0,
                            "Signature should be boosted in round 1")
        self.assertEqual(boosted_r1[1][0], 10.0,
                          "Non-signature unchanged in round 1")

        # Round 3: no boost — trigger doesn't fire
        state_r3 = _state_with([actor, enemy], round_num=3)
        scored_r3 = [
            (10.0, {"kind": "weapon_attack", "actor": actor,
                     "action": sig, "target": enemy}),
            (10.0, {"kind": "weapon_attack", "actor": actor,
                     "action": plain, "target": enemy}),
        ]
        boosted_r3 = apply_forced_choice_boosts(scored_r3, actor, state_r3)
        self.assertEqual(boosted_r3[0][0], 10.0,
                          "Signature should NOT be boosted past round 1")

    def test_priority_resolution_when_multiple_trigger(self) -> None:
        """When two forced_choice constraints both trigger, only the
        highest-priority one's boost applies."""
        sig = _weapon_attack("a_sig", is_sig=True)
        heal = _heal_action("a_cure")
        actor = _make_actor("a", side="pc",
                              actions=[sig, heal],
                              rp_constraints=[
                                  {"id": "heal_priority"},      # priority 80
                                  {"id": "signature_first"},    # priority 50
                              ])
        wounded_ally = _make_actor("ally", side="pc", hp=30, hp_current=5)
        state = _state_with([actor, wounded_ally], round_num=1)
        # Both triggers fire (wounded ally + round 1)
        # heal_priority (priority 80) should win

        scored = [
            (10.0, {"kind": "heal", "actor": actor,
                     "action": heal, "target": wounded_ally}),
            (10.0, {"kind": "weapon_attack", "actor": actor,
                     "action": sig, "target": wounded_ally}),
        ]
        boosted = apply_forced_choice_boosts(scored, actor, state)
        # The heal candidate should be boosted (heal_priority's qualifier);
        # the sig attack should NOT be boosted (signature_first suppressed)
        self.assertGreater(boosted[0][0], 10.0, "Heal should win priority")
        self.assertEqual(boosted[1][0], 10.0,
                          "Lower-priority signature_first suppressed")


# ============================================================================
# Tier 3 — Weighted Preferences (cumulative additive)
# ============================================================================

class WeightedPreferenceTest(unittest.TestCase):

    def test_resource_hoarder_penalizes_spell_actions(self) -> None:
        attack = _weapon_attack("a_sword")
        spell = _spell_attack("a_hold")
        actor = _make_actor("a", side="pc",
                              actions=[attack, spell],
                              rp_constraints=[{"id": "resource_hoarder"}])
        enemy = _make_actor("e", side="enemy")
        state = _state_with([actor, enemy])

        # Baseline scores
        baseline = [
            (10.0, {"kind": "weapon_attack", "actor": actor,
                     "action": attack, "target": enemy}),
            (10.0, {"kind": "hard_control", "actor": actor,
                     "action": spell, "target": enemy}),
        ]
        modified = apply_weighted_preferences(baseline, actor, state)
        # Sword unchanged; spell penalized -30% → 7.0
        self.assertAlmostEqual(modified[0][0], 10.0,
                                msg="Weapon attack should be unchanged")
        self.assertAlmostEqual(modified[1][0], 7.0,
                                msg="Spell should be -30% penalty")

    def test_no_constraint_passthrough(self) -> None:
        actor = _make_actor("a", side="pc")
        state = _state_with([actor])
        scored = [(5.0, {"kind": "weapon_attack"})]
        self.assertEqual(apply_weighted_preferences(scored, actor, state),
                          scored)


# ============================================================================
# Chained: apply_rp_score_modifications applies Tier 2 then Tier 3
# ============================================================================

class ChainedModificationTest(unittest.TestCase):

    def test_chain_applies_both_tiers(self) -> None:
        """A creature with both a forced_choice AND a weighted_preference
        should see both modifications applied."""
        heal = _heal_action("a_cure")
        spell_attack = _spell_attack("a_hold")
        actor = _make_actor("a", side="pc",
                              actions=[heal, spell_attack],
                              rp_constraints=[
                                  {"id": "heal_priority"},
                                  {"id": "resource_hoarder"},
                              ])
        wounded = _make_actor("ally", side="pc", hp=30, hp_current=5)
        enemy = _make_actor("e", side="enemy")
        state = _state_with([actor, wounded, enemy])

        scored = [
            (10.0, {"kind": "heal", "actor": actor,
                     "action": heal, "target": wounded}),
            (10.0, {"kind": "hard_control", "actor": actor,
                     "action": spell_attack, "target": enemy}),
        ]
        modified = apply_rp_score_modifications(scored, actor, state)
        # heal boosted by 0.70 → 17.0; spell penalized -30% → 7.0
        self.assertAlmostEqual(modified[0][0], 17.0)
        self.assertAlmostEqual(modified[1][0], 7.0)


# ============================================================================
# Behavioral integration — pacifist Pass-turns instead of attacking
# ============================================================================

class PacifistDodgesFallbackTest(unittest.TestCase):

    def test_pacifist_defends_via_dodge_never_attacks(self) -> None:
        """A pacifist with no non-damaging actions should never attack
        — pacifist_strict filters all weapon_attack candidates. With
        PR #29 (built-in basic actions), the built-in Dodge candidate
        survives the filter (no `damage` primitive), so the pacifist
        Dodges via the normal candidate path instead of triggering
        the PR #28 `dodge_fallback` safety net.

        Enemy attacks against the pacifist should show
        `advantage_state: disadvantage` (Dodge modifier active).
        """
        import random as _random
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner

        attack = _weapon_attack("a_sword", dice="1d8", modifier=3)
        pacifist = _make_actor("pacifist", side="pc", hp=30, ac=15,
                                 actions=[attack],
                                 rp_constraints=[{"id": "pacifist_strict"}],
                                 template_extras={"combat": {
                                     "initiative": {"modifier": 5, "score": 18},
                                 }})
        enemy = _make_actor("enemy", side="enemy", hp=20, ac=15,
                             actions=[attack])
        encounter = Encounter(id="pacifist_test", actors=[pacifist, enemy])

        primitives_module.set_rng(_random.Random(1))
        runner = EncounterRunner.new(encounter, seed=1)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # Pacifist should NEVER attack — constraint enforced
        pacifist_attacks = [e for e in state.event_log
                             if e.get("event") == "attack_roll"
                             and e.get("actor") == "pacifist"]
        self.assertEqual(len(pacifist_attacks), 0,
                          "Pacifist should NEVER have attacked")

        # Enemy attacks should show disadvantage (Dodge active)
        enemy_attacks = [e for e in state.event_log
                          if e.get("event") == "attack_roll"
                          and e.get("actor") == "enemy"
                          and e.get("target") == "pacifist"]
        self.assertGreater(len(enemy_attacks), 0,
                            "Enemy should have attacked at least once")
        disad = [a for a in enemy_attacks
                  if a.get("advantage_state") == "disadvantage"]
        self.assertGreater(len(disad), 0,
                            "Built-in Dodge should impose disadvantage on "
                            "enemy attacks against the pacifist")

    def test_monster_pacifist_also_dodges_via_built_in(self) -> None:
        """Per RAW every creature has Dodge available — including
        monsters. With PR #29 built-in basic actions, a monster-side
        pacifist behaves like a PC pacifist: never attacks (constraint
        enforced), defends via built-in Dodge.

        The PR #28 PC/monster `dodge_fallback` vs `passed_turn` split
        only fires when even built-in Dodge is somehow filtered (rare;
        no canonical constraint does this in v1). With built-ins in the
        candidate pool, both sides reach Dodge through normal selection.
        """
        import random as _random
        from engine import primitives as primitives_module
        from engine.core.runner import EncounterRunner

        attack = _weapon_attack("a_sword", dice="1d8", modifier=3)
        monster_pacifist = _make_actor(
            "monster_pacifist", side="enemy", hp=30, ac=15,
            actions=[attack],
            rp_constraints=[{"id": "pacifist_strict"}],
            template_extras={"combat": {
                "initiative": {"modifier": 5, "score": 18},
            }},
        )
        pc_attacker = _make_actor("pc_enemy", side="pc", hp=20, ac=15,
                                     actions=[attack])
        encounter = Encounter(id="monster_pacifist_test",
                                actors=[monster_pacifist, pc_attacker])

        primitives_module.set_rng(_random.Random(1))
        runner = EncounterRunner.new(encounter, seed=1)
        primitives_module.set_rng(runner.rng)
        state = runner.run(seed=1)

        # Monster pacifist never attacks
        monster_attacks = [e for e in state.event_log
                            if e.get("event") == "attack_roll"
                            and e.get("actor") == "monster_pacifist"]
        self.assertEqual(len(monster_attacks), 0,
                          "Monster pacifist should NEVER have attacked")

        # PC's attacks against the monster show disadvantage
        pc_attacks = [e for e in state.event_log
                       if e.get("event") == "attack_roll"
                       and e.get("actor") == "pc_enemy"
                       and e.get("target") == "monster_pacifist"]
        self.assertGreater(len(pc_attacks), 0)
        disad = [a for a in pc_attacks
                  if a.get("advantage_state") == "disadvantage"]
        self.assertGreater(len(disad), 0,
                            "Built-in Dodge should give monster pacifist "
                            "disadvantage on incoming attacks too (RAW: every "
                            "creature has Dodge available)")


# ============================================================================
# Behavioral integration — heal_priority forces healing over attacking
# ============================================================================

class HealPriorityForcesHealTest(unittest.TestCase):

    def test_heal_priority_overrides_attack_preference(self) -> None:
        """A cleric whose attack scores higher than her heal at baseline
        should still choose to heal when heal_priority is active and an
        ally is below 50% HP."""
        # High-damage attack (would normally beat heal eHP)
        strong_attack = _weapon_attack("a_smite", bonus=8, dice="3d8", modifier=5)
        heal = _heal_action("a_cure", dice="1d4")   # small heal
        cleric_no_rp = _make_actor("c_baseline", side="pc",
                                      actions=[strong_attack, heal])
        # Use severity 3.0 so the boost is unambiguously strong enough
        # to override the strong attack's combined eHP + preset
        # preference bonuses (the attack candidate gets +3 from
        # target+action matching the closest-enemy preset). This test
        # proves the MECHANISM works at sufficient severity.
        cleric_with_rp = _make_actor("c_with_rp", side="pc",
                                        actions=[strong_attack, heal],
                                        rp_constraints=[{"id": "heal_priority",
                                                          "severity": 3.0}])
        ally = _make_actor("ally", side="pc", hp=30, hp_current=10)  # 33%
        enemy = _make_actor("e", side="enemy", ac=15, hp=40)

        # Baseline: which action would the cleric prefer without heal_priority?
        baseline_state = _state_with([cleric_no_rp, ally, enemy])
        baseline_cands = generate_candidates(cleric_no_rp, baseline_state)
        baseline_scored = score_candidates_v1(baseline_cands, cleric_no_rp,
                                                  baseline_state)
        baseline_best = max(baseline_scored, key=lambda x: x[0])[1]

        # With heal_priority: should switch to heal
        rp_state = _state_with([cleric_with_rp, ally, enemy])
        rp_cands = generate_candidates(cleric_with_rp, rp_state)
        rp_scored = score_candidates_v1(rp_cands, cleric_with_rp, rp_state)
        rp_best = max(rp_scored, key=lambda x: x[0])[1]

        # The constraint should change the choice (or at least keep heal best
        # if it already was — but our setup ensures attack would win baseline)
        if baseline_best["kind"] == "weapon_attack":
            self.assertEqual(rp_best["kind"], "heal",
                              "heal_priority should override attack preference "
                              "when an ally is wounded")
        else:
            # If baseline already picks heal, this test isn't proving anything
            # — bail with a meaningful message.
            self.skipTest("Baseline already preferred heal; can't prove "
                           "constraint changed behavior")


if __name__ == "__main__":
    unittest.main()
