"""apply_short_rest tests (PR #37).

Layers:
  1. Wizard with Arcane Recovery: short rest restores slots, decrements
     arcane_recovery_uses_remaining
  2. Subsequent short rest with no AR uses left → no slot restoration
  3. Wizard at full slots → no-op (don't spend AR for nothing)
  4. Fighter: short rest refreshes Second Wind by +1 (capped at max)
  5. Fighter: short rest fully refreshes Action Surge (L2 = 1, L17 = 2)
  6. Non-PC actor (inline template) → no-op
  7. End-to-end via PC schema: L5 Wizard via pc: spec, burn slots,
     short rest, verify AR fires through the auto-wired counter
  8. short_rest_applied event fires with the summary

Run via:
    python -m unittest tests.test_short_rest
"""
from __future__ import annotations

import unittest

from engine.core.rest import apply_short_rest
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str, class_id: str | None = None,
                level: int = 1, spell_slots: dict | None = None,
                spell_slots_max: dict | None = None,
                resources: dict | None = None) -> Actor:
    abilities = {k: {"score": 10, "save": 0}
                  for k in ("str", "dex", "con", "int", "wis", "cha")}
    template: dict = {"id": f"tpl_{actor_id}", "name": actor_id,
                       "abilities": abilities,
                       "cr": {"value": 0, "xp": 0, "proficiency_bonus": 2},
                       "actions": []}
    if class_id is not None:
        template["derived_from_pc_schema"] = {"class": class_id, "level": level}
    return Actor(id=actor_id, name=actor_id, template=template, side="pc",
                  hp_current=20, hp_max=20, ac=14,
                  speed={"walk": 30}, position=(0, 0),
                  abilities=abilities,
                  spell_slots=dict(spell_slots or {}),
                  spell_slots_max=dict(spell_slots_max or {}),
                  resources=dict(resources or {}))


def _state_with(actor: Actor) -> CombatState:
    state = CombatState(encounter=Encounter(id="t", actors=[actor]))
    state.turn_order = [actor.id]
    state.round = 1
    return state


# ============================================================================
# Wizard Arcane Recovery
# ============================================================================

class WizardArcaneRecoveryTest(unittest.TestCase):

    def test_short_rest_restores_slots(self) -> None:
        """L5 wizard with all slots expended, 1 AR use. Short rest
        restores one L3 slot (ceil(5/2) = 3 budget)."""
        wizard = _make_actor(
            "wizard", class_id="c_wizard", level=5,
            spell_slots={1: 0, 2: 0, 3: 0},
            spell_slots_max={1: 4, 2: 3, 3: 2},
            resources={"arcane_recovery_uses_remaining": 1},
        )
        state = _state_with(wizard)
        summary = apply_short_rest(wizard, state)
        self.assertIn("arcane_recovery", summary)
        self.assertEqual(summary["arcane_recovery"]["restored"],
                          [{"level": 3, "count": 1}])
        self.assertEqual(wizard.spell_slots[3], 1)
        self.assertEqual(wizard.resources["arcane_recovery_uses_remaining"],
                          0)

    def test_second_short_rest_no_recovery(self) -> None:
        """After AR's 1/long-rest use is spent, a second short rest
        doesn't restore anything."""
        wizard = _make_actor(
            "wizard", class_id="c_wizard", level=5,
            spell_slots={3: 0}, spell_slots_max={3: 2},
            resources={"arcane_recovery_uses_remaining": 0},
        )
        state = _state_with(wizard)
        summary = apply_short_rest(wizard, state)
        self.assertNotIn("arcane_recovery", summary)
        self.assertEqual(wizard.spell_slots[3], 0)

    def test_no_recovery_when_no_slots_expended(self) -> None:
        """RAW: AR only triggers when the wizard chooses to use it.
        If no slots are expended, using it would waste the charge —
        we skip activation."""
        wizard = _make_actor(
            "wizard", class_id="c_wizard", level=5,
            spell_slots={3: 2}, spell_slots_max={3: 2},
            resources={"arcane_recovery_uses_remaining": 1},
        )
        state = _state_with(wizard)
        summary = apply_short_rest(wizard, state)
        self.assertNotIn("arcane_recovery", summary)
        # Charge preserved for a future rest
        self.assertEqual(wizard.resources["arcane_recovery_uses_remaining"],
                          1)

    def test_L1_wizard_budget_is_one(self) -> None:
        """L1 wizard: ceil(1/2) = 1 budget → one L1 slot restored."""
        wizard = _make_actor(
            "wizard", class_id="c_wizard", level=1,
            spell_slots={1: 0}, spell_slots_max={1: 2},
            resources={"arcane_recovery_uses_remaining": 1},
        )
        state = _state_with(wizard)
        apply_short_rest(wizard, state)
        self.assertEqual(wizard.spell_slots[1], 1)

    def test_logs_feature_use_consumed(self) -> None:
        wizard = _make_actor(
            "wizard", class_id="c_wizard", level=5,
            spell_slots={3: 0}, spell_slots_max={3: 2},
            resources={"arcane_recovery_uses_remaining": 1},
        )
        state = _state_with(wizard)
        apply_short_rest(wizard, state)
        events = [e for e in state.event_log
                   if e.get("event") == "feature_use_consumed"
                   and e.get("resource") == "arcane_recovery_uses_remaining"]
        self.assertEqual(len(events), 1)


# ============================================================================
# Fighter Second Wind + Action Surge refresh
# ============================================================================

class FighterShortRestRefreshTest(unittest.TestCase):

    def test_second_wind_refresh_adds_one_use(self) -> None:
        fighter = _make_actor(
            "fighter", class_id="c_fighter", level=1,
            resources={"second_wind_uses_remaining": 0},
        )
        state = _state_with(fighter)
        summary = apply_short_rest(fighter, state)
        self.assertEqual(summary["second_wind_refresh"]["added"], 1)
        self.assertEqual(fighter.resources["second_wind_uses_remaining"], 1)

    def test_second_wind_does_not_exceed_max(self) -> None:
        """L1 max is 2 — already at 2 → no refresh."""
        fighter = _make_actor(
            "fighter", class_id="c_fighter", level=1,
            resources={"second_wind_uses_remaining": 2},
        )
        state = _state_with(fighter)
        summary = apply_short_rest(fighter, state)
        self.assertNotIn("second_wind_refresh", summary)
        self.assertEqual(fighter.resources["second_wind_uses_remaining"], 2)

    def test_second_wind_max_scales_with_level(self) -> None:
        """L10 fighter: max is 4. At 3 → refresh to 4."""
        fighter = _make_actor(
            "fighter", class_id="c_fighter", level=10,
            resources={"second_wind_uses_remaining": 3},
        )
        state = _state_with(fighter)
        apply_short_rest(fighter, state)
        self.assertEqual(fighter.resources["second_wind_uses_remaining"], 4)

    def test_action_surge_refresh_at_L2(self) -> None:
        fighter = _make_actor(
            "fighter", class_id="c_fighter", level=2,
            resources={"action_surge_uses_remaining": 0},
        )
        state = _state_with(fighter)
        summary = apply_short_rest(fighter, state)
        self.assertEqual(summary["action_surge_refresh"]["new_total"], 1)
        self.assertEqual(fighter.resources["action_surge_uses_remaining"], 1)

    def test_action_surge_refresh_at_L17_is_two(self) -> None:
        fighter = _make_actor(
            "fighter", class_id="c_fighter", level=17,
            resources={"action_surge_uses_remaining": 0},
        )
        state = _state_with(fighter)
        apply_short_rest(fighter, state)
        self.assertEqual(fighter.resources["action_surge_uses_remaining"], 2)

    def test_action_surge_no_refresh_below_L2(self) -> None:
        fighter = _make_actor("fighter", class_id="c_fighter", level=1)
        state = _state_with(fighter)
        summary = apply_short_rest(fighter, state)
        self.assertNotIn("action_surge_refresh", summary)


# ============================================================================
# Non-PC actor (inline template) — no-op
# ============================================================================

class NonPCShortRestTest(unittest.TestCase):

    def test_inline_template_actor_is_noop(self) -> None:
        """Monster / inline-template actor with no
        derived_from_pc_schema tag → apply_short_rest doesn't crash
        and doesn't modify state."""
        ogre = _make_actor("ogre")    # no class_id
        state = _state_with(ogre)
        summary = apply_short_rest(ogre, state)
        self.assertEqual(summary, {})
        # Event still logs (empty summary)
        events = [e for e in state.event_log
                   if e.get("event") == "short_rest_applied"]
        self.assertEqual(len(events), 1)


# ============================================================================
# End-to-end via pc_schema + cli._build_actor
# ============================================================================

class WizardEndToEndTest(unittest.TestCase):

    def test_pc_schema_wizard_short_rest_restores_slots(self) -> None:
        from engine.cli import _build_actor
        from engine.loader import load_content
        from pathlib import Path

        here = Path(__file__).resolve()
        repo = here.parent.parent
        registry = load_content(repo / "schema" / "content", validate=False)

        wizard_spec = {
            "instance_id": "wizard_pc",
            "side": "pc",
            # Wizard expended all their L3 slots; AR will restore one
            "spell_slots": {1: 0, 2: 0, 3: 0},
            "spell_slots_max": {1: 4, 2: 3, 3: 2},
            "pc": {
                "class": "c_wizard", "level": 5,
                "ability_scores": {"str": 8, "dex": 14, "con": 14,
                                     "int": 18, "wis": 12, "cha": 10},
                "weapons": [{"id": "a_dagger", "name": "Dagger",
                              "attack_ability": "dex",
                              "damage_dice": "1d4",
                              "damage_type": "piercing"}],
            },
        }
        wizard = _build_actor(wizard_spec, registry)
        # Arcane Recovery counter auto-wired via PR #32 + #37
        self.assertEqual(
            wizard.resources["arcane_recovery_uses_remaining"], 1)
        state = _state_with(wizard)
        apply_short_rest(wizard, state)
        # One L3 slot restored (budget = ceil(5/2) = 3, max_slot = 5)
        self.assertEqual(wizard.spell_slots[3], 1)
        # AR counter spent
        self.assertEqual(
            wizard.resources["arcane_recovery_uses_remaining"], 0)


if __name__ == "__main__":
    unittest.main()
