"""Scoring-side spell-save-DC fix (PR #113).

`_resolve_dc_for_action` (the scoring-time DC resolver used by
hard-control scoring) hardcoded INT for `caster_spell_save_dc`,
silently mis-estimating the DC for every non-INT caster — the
scoring-side twin of the execution-side bug fixed in PR #104/#110. It
now delegates to the ability-aware `_caster_spell_dc`.

Layers:
  1. caster_spell_save_dc → CHA for a charisma-stamped caster
  2. caster_spell_save_dc → WIS for a wisdom-stamped caster
  3. caster_spell_save_dc → INT fallback when unstamped
  4. save_dc_fixed and fixed:N branches unchanged
  5. regression: CHA Paladin hard-control scoring uses the CHA DC
     (higher than the old INT-based DC for a low-INT Paladin)
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.ai.defensive_ehp import (
    _resolve_dc_for_action, defensive_ehp_hard_control,
)
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


def _abilities(**overrides):
    base = {a: {"score": 10, "save": 0}
              for a in ("str", "dex", "con", "int", "wis", "cha")}
    base.update(overrides)
    return base


def _caster(*, abilities, pb=2, spellcasting_ability=None):
    template = {"id": "t", "name": "c", "abilities": abilities,
                "cr": {"proficiency_bonus": pb}, "actions": []}
    if spellcasting_ability:
        template["spellcasting_ability"] = spellcasting_ability
    return Actor(id="c", name="c", template=template, side="pc",
                   hp_current=30, hp_max=30, ac=14, speed={"walk": 30},
                   position=(0, 0), abilities=abilities)


_SPELL_DC_INTENT = {"save_dc_source": "caster_spell_save_dc"}


# ============================================================================
# Layers 1-3: ability-aware caster_spell_save_dc
# ============================================================================

class CasterSpellSaveDcTest(unittest.TestCase):

    def test_charisma_caster(self) -> None:
        # CHA 18 (+4), PB 3 → 8+4+3 = 15. (INT 8 would give 8-1+3=10.)
        c = _caster(abilities=_abilities(cha={"score": 18}, int={"score": 8}),
                      pb=3, spellcasting_ability="charisma")
        self.assertEqual(_resolve_dc_for_action(_SPELL_DC_INTENT, c), 15)

    def test_wisdom_caster(self) -> None:
        # WIS 16 (+3), PB 2 → 13.
        c = _caster(abilities=_abilities(wis={"score": 16}),
                      pb=2, spellcasting_ability="wisdom")
        self.assertEqual(_resolve_dc_for_action(_SPELL_DC_INTENT, c), 13)

    def test_int_fallback_when_unstamped(self) -> None:
        # No spellcasting_ability → CHA fallback in _caster_spell_dc.
        # CHA 10 (+0), PB 2 → 10. (Confirms the helper's documented
        # CHA fallback, matching primitives._caster_spell_save_dc.)
        c = _caster(abilities=_abilities(), pb=2)
        self.assertEqual(_resolve_dc_for_action(_SPELL_DC_INTENT, c), 10)


# ============================================================================
# Layer 4: other DC branches unchanged
# ============================================================================

class OtherDcBranchesTest(unittest.TestCase):

    def test_fixed_value(self) -> None:
        c = _caster(abilities=_abilities())
        self.assertEqual(
            _resolve_dc_for_action({"save_dc_fixed": 17}, c), 17)

    def test_fixed_prefix_source(self) -> None:
        c = _caster(abilities=_abilities())
        self.assertEqual(
            _resolve_dc_for_action({"save_dc_source": "fixed:14"}, c), 14)

    def test_unknown_source_default(self) -> None:
        c = _caster(abilities=_abilities())
        self.assertEqual(
            _resolve_dc_for_action({"save_dc_source": "???"}, c), 13)


# ============================================================================
# Layer 5: regression — CHA Paladin hard-control scoring uses CHA DC
# ============================================================================

class HardControlRegressionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_content(CONTENT_ROOT, validate=True,
                                       schema_root=SCHEMA_ROOT)

    def test_compelled_duel_scores_with_cha_dc(self) -> None:
        # L2 Paladin: CHA 16 (+3) high, INT 8 (-1) low. Compelled Duel
        # is a WIS-save hard-control. The CHA-based DC (8+3+2=13) makes
        # the goblin more likely to fail than the old INT-based DC
        # (8-1+2=9) would — so the score must be positive and reflect
        # the higher fail prob.
        template = build_pc_template({
            "id": "pal2", "class": "c_paladin", "level": 2,
            "ability_scores": {"str": 16, "dex": 10, "con": 14,
                                  "int": 8, "wis": 10, "cha": 16},
            "weapons": [],
        }, self.registry)
        paladin = Actor(id="pal", name="pal", template=template, side="pc",
                          hp_current=40, hp_max=40, ac=18, position=(0, 0),
                          abilities=template["abilities"])
        goblin = Actor(
            id="goblin", name="goblin",
            template={"id": "t", "name": "g",
                        "abilities": {"wis": {"score": 8, "save": -1}},
                        "cr": {"proficiency_bonus": 2},
                        "actions": [{"id": "a", "type": "weapon_attack",
                                       "pipeline": [
                                           {"primitive": "attack_roll",
                                             "params": {"kind": "melee",
                                                          "bonus": 4}},
                                           {"primitive": "damage",
                                             "params": {"dice": "1d6",
                                                          "modifier": 2}}]}]},
            side="enemy", hp_current=20, hp_max=20, ac=13,
            speed={"walk": 30}, position=(1, 0),
            abilities={"wis": {"score": 8, "save": -1}})
        enc = Encounter(id="t", actors=[paladin, goblin])
        state = CombatState(encounter=enc)
        state.turn_order = ["pal", "goblin"]
        state.round = 1
        cd = next(a for a in template["actions"]
                    if a.get("id") == "a_compelled_duel")
        score = defensive_ehp_hard_control(paladin, goblin, cd, state)
        self.assertGreater(score, 0.0)


if __name__ == "__main__":
    unittest.main()
