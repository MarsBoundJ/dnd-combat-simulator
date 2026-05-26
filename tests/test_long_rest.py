"""apply_long_rest tests (PR #40).

Layers:
  1. Universal: HP restored to hp_max for any actor
  2. Universal: all spell slots restored to spell_slots_max
  3. Universal: concentration ends with reason='long_rest', source
     modifiers scrubbed from allies
  4. Universal: until_long_rest modifiers expire
  5. Per-class: Fighter Action Surge + Second Wind both fully
     refreshed (cap at L2/L17 for AS, level-table max for SW)
  6. Per-class: Wizard Arcane Recovery → 1
  7. Non-PC actor: universal effects only, no per-class refresh
  8. End-to-end via cli._build_actor for a L5 wizard

Run via:
    python -m unittest tests.test_long_rest
"""
from __future__ import annotations

import unittest

from engine.core.rest import apply_long_rest
from engine.core.state import Actor, Encounter, CombatState


# ============================================================================
# Helpers
# ============================================================================

def _make_actor(actor_id: str, class_id: str | None = None,
                level: int = 1, hp: int = 20, hp_current: int | None = None,
                spell_slots: dict | None = None,
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
                  hp_current=hp_current if hp_current is not None else hp,
                  hp_max=hp, ac=14,
                  speed={"walk": 30}, position=(0, 0),
                  abilities=abilities,
                  spell_slots=dict(spell_slots or {}),
                  spell_slots_max=dict(spell_slots_max or {}),
                  resources=dict(resources or {}))


def _state_with(actors: list[Actor]) -> CombatState:
    state = CombatState(encounter=Encounter(id="t", actors=actors))
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


# ============================================================================
# Universal: HP restoration
# ============================================================================

class HPRestorationTest(unittest.TestCase):

    def test_wounded_actor_restored_to_hp_max(self) -> None:
        a = _make_actor("a", hp=20, hp_current=5)
        state = _state_with([a])
        summary = apply_long_rest(a, state)
        self.assertEqual(a.hp_current, 20)
        self.assertEqual(summary["hp_restored"], 15)

    def test_full_hp_actor_no_restoration_in_summary(self) -> None:
        a = _make_actor("a", hp=20)
        state = _state_with([a])
        summary = apply_long_rest(a, state)
        self.assertNotIn("hp_restored", summary)


# ============================================================================
# Universal: spell slot restoration
# ============================================================================

class SpellSlotRestorationTest(unittest.TestCase):

    def test_all_slots_restored_to_max(self) -> None:
        a = _make_actor("a",
                         spell_slots={1: 0, 2: 1, 3: 0},
                         spell_slots_max={1: 4, 2: 3, 3: 2})
        state = _state_with([a])
        summary = apply_long_rest(a, state)
        self.assertEqual(a.spell_slots[1], 4)
        self.assertEqual(a.spell_slots[2], 3)
        self.assertEqual(a.spell_slots[3], 2)
        self.assertEqual(summary["slots_restored"],
                          {1: 4, 2: 2, 3: 2})

    def test_no_expended_slots_no_restoration_in_summary(self) -> None:
        a = _make_actor("a",
                         spell_slots={1: 4, 2: 3},
                         spell_slots_max={1: 4, 2: 3})
        state = _state_with([a])
        summary = apply_long_rest(a, state)
        self.assertNotIn("slots_restored", summary)


# ============================================================================
# Universal: concentration ends
# ============================================================================

class ConcentrationEndsTest(unittest.TestCase):

    def test_concentration_ends_on_long_rest(self) -> None:
        from engine.core.concentration import apply_concentration
        caster = _make_actor("caster")
        ally = _make_actor("ally")
        state = _state_with([caster, ally])
        apply_concentration(
            caster, {"id": "a_bless", "type": "offensive_buff"}, state)
        # Sanity: concentration started
        self.assertIsNotNone(caster.concentration_on)
        summary = apply_long_rest(caster, state)
        self.assertIsNone(caster.concentration_on)
        self.assertTrue(summary["concentration_ended"])
        # Event log shows the end
        ended = [e for e in state.event_log
                  if e.get("event") == "concentration_ended"
                  and e.get("caster") == "caster"]
        self.assertEqual(len(ended), 1)
        self.assertEqual(ended[0]["reason"], "long_rest")

    def test_no_concentration_no_end_event(self) -> None:
        a = _make_actor("a")
        state = _state_with([a])
        summary = apply_long_rest(a, state)
        self.assertNotIn("concentration_ended", summary)


# ============================================================================
# Universal: until_long_rest modifiers expire
# ============================================================================

class UntilLongRestExpiryTest(unittest.TestCase):

    def test_until_long_rest_modifiers_expire(self) -> None:
        a = _make_actor("a")
        a.active_modifiers.append({
            "primitive": "attack_modifier",
            "params": {"target": "self", "modifier": "attack_bonus",
                        "value": 2},
            "lifetime": "until_long_rest",
            "source": {"type": "action_buff",
                        "action_id": "a_bless", "caster_id": "self"},
            "applied_at_round": 1,
            "owner_id": "a",
        })
        state = _state_with([a])
        summary = apply_long_rest(a, state)
        self.assertEqual(a.active_modifiers, [])
        self.assertEqual(summary["modifiers_expired"], 1)

    def test_other_lifetime_modifiers_persist(self) -> None:
        """A modifier with `until_short_rest` lifetime should NOT
        expire on long rest — different trigger event. (RAW: short-
        rest-only effects... actually do go away on long rest too,
        but the lifetime mapping doesn't model that yet. Test pins
        current behavior; revisit when we wire short-rest events
        into the long-rest trigger.)"""
        a = _make_actor("a")
        a.active_modifiers.append({
            "primitive": "attack_modifier",
            "params": {"target": "self", "modifier": "attack_bonus",
                        "value": 1},
            "lifetime": "until_short_rest",
            "source": {"type": "action_buff",
                        "action_id": "a_x", "caster_id": "self"},
            "applied_at_round": 1,
            "owner_id": "a",
        })
        state = _state_with([a])
        apply_long_rest(a, state)
        self.assertEqual(len(a.active_modifiers), 1)


# ============================================================================
# Per-class: Fighter refresh
# ============================================================================

class FighterLongRestRefreshTest(unittest.TestCase):

    def test_action_surge_refresh_to_one_at_L2(self) -> None:
        fighter = _make_actor(
            "fighter", class_id="c_fighter", level=2,
            resources={"action_surge_uses_remaining": 0},
        )
        state = _state_with([fighter])
        summary = apply_long_rest(fighter, state)
        self.assertEqual(
            fighter.resources["action_surge_uses_remaining"], 1)
        self.assertEqual(summary["action_surge_refresh"]["new_total"], 1)

    def test_action_surge_refresh_to_two_at_L17(self) -> None:
        fighter = _make_actor(
            "fighter", class_id="c_fighter", level=17,
            resources={"action_surge_uses_remaining": 0},
        )
        state = _state_with([fighter])
        apply_long_rest(fighter, state)
        self.assertEqual(
            fighter.resources["action_surge_uses_remaining"], 2)

    def test_action_surge_no_refresh_below_L2(self) -> None:
        fighter = _make_actor("fighter", class_id="c_fighter", level=1)
        state = _state_with([fighter])
        summary = apply_long_rest(fighter, state)
        self.assertNotIn("action_surge_refresh", summary)

    def test_second_wind_refresh_to_level_table_max(self) -> None:
        fighter = _make_actor(
            "fighter", class_id="c_fighter", level=10,
            resources={"second_wind_uses_remaining": 1},
        )
        state = _state_with([fighter])
        summary = apply_long_rest(fighter, state)
        self.assertEqual(
            fighter.resources["second_wind_uses_remaining"], 4)
        self.assertEqual(summary["second_wind_refresh"]["new_total"], 4)

    def test_already_at_max_no_refresh_in_summary(self) -> None:
        fighter = _make_actor(
            "fighter", class_id="c_fighter", level=2,
            resources={"action_surge_uses_remaining": 1,
                        "second_wind_uses_remaining": 2},
        )
        state = _state_with([fighter])
        summary = apply_long_rest(fighter, state)
        self.assertNotIn("action_surge_refresh", summary)
        self.assertNotIn("second_wind_refresh", summary)


# ============================================================================
# Per-class: Wizard Arcane Recovery refresh
# ============================================================================

class WizardLongRestRefreshTest(unittest.TestCase):

    def test_arcane_recovery_refreshes_to_one(self) -> None:
        wizard = _make_actor(
            "wizard", class_id="c_wizard", level=5,
            resources={"arcane_recovery_uses_remaining": 0},
        )
        state = _state_with([wizard])
        summary = apply_long_rest(wizard, state)
        self.assertEqual(
            wizard.resources["arcane_recovery_uses_remaining"], 1)
        self.assertEqual(summary["arcane_recovery_refresh"]["new_total"], 1)

    def test_already_one_no_refresh_in_summary(self) -> None:
        wizard = _make_actor(
            "wizard", class_id="c_wizard", level=5,
            resources={"arcane_recovery_uses_remaining": 1},
        )
        state = _state_with([wizard])
        summary = apply_long_rest(wizard, state)
        self.assertNotIn("arcane_recovery_refresh", summary)


# ============================================================================
# Non-PC actor
# ============================================================================

class NonPCActorTest(unittest.TestCase):

    def test_non_pc_gets_universal_effects_only(self) -> None:
        """Inline-template ogre: HP and slots restore, no per-class
        refresh (no derived_from_pc_schema tag)."""
        ogre = _make_actor("ogre", hp=30, hp_current=10,
                            spell_slots={1: 0}, spell_slots_max={1: 1})
        state = _state_with([ogre])
        summary = apply_long_rest(ogre, state)
        # Universal effects fired
        self.assertEqual(ogre.hp_current, 30)
        self.assertEqual(ogre.spell_slots[1], 1)
        # No per-class refresh keys
        self.assertNotIn("action_surge_refresh", summary)
        self.assertNotIn("second_wind_refresh", summary)
        self.assertNotIn("arcane_recovery_refresh", summary)


# ============================================================================
# End-to-end via cli._build_actor
# ============================================================================

class WizardEndToEndTest(unittest.TestCase):

    def test_pc_schema_wizard_full_long_rest(self) -> None:
        """A wizard built via the pc: schema burns slots + AR + HP
        across an encounter, then a long rest restores everything."""
        from engine.cli import _build_actor
        from engine.loader import load_content
        from pathlib import Path

        here = Path(__file__).resolve()
        repo = here.parent.parent
        registry = load_content(repo / "schema" / "content", validate=False)

        wizard_spec = {
            "instance_id": "wizard",
            "side": "pc",
            "spell_slots": {1: 1, 2: 0, 3: 0},     # mostly expended
            "spell_slots_max": {1: 4, 2: 3, 3: 2},
            "hp_current": 8,                          # wounded
            "pc": {
                "class": "c_wizard", "level": 5,
                "ability_scores": {"str": 8, "dex": 14, "con": 14,
                                     "int": 18, "wis": 12, "cha": 10},
                "weapons": [{"id": "a_dagger", "name": "Dagger",
                              "attack_ability": "dex",
                              "damage_dice": "1d4",
                              "damage_type": "piercing"}],
            },
            "resources": {
                "arcane_recovery_uses_remaining": 0,    # already spent
            },
        }
        wizard = _build_actor(wizard_spec, registry)
        state = _state_with([wizard])
        summary = apply_long_rest(wizard, state)
        # HP, slots, AR all restored
        self.assertEqual(wizard.hp_current, wizard.hp_max)
        self.assertEqual(wizard.spell_slots[1], 4)
        self.assertEqual(wizard.spell_slots[2], 3)
        self.assertEqual(wizard.spell_slots[3], 2)
        self.assertEqual(
            wizard.resources["arcane_recovery_uses_remaining"], 1)
        # Summary signals all three categories
        self.assertGreater(summary["hp_restored"], 0)
        self.assertIn("slots_restored", summary)
        self.assertIn("arcane_recovery_refresh", summary)


if __name__ == "__main__":
    unittest.main()
