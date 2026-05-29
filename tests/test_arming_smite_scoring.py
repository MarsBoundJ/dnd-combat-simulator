"""Arming-smite AI scoring tests (PR #111).

Searing Smite (PR #89) and Ensnaring Strike (PR #110) are self-buffs
that arm a one-shot rider firing on the caster's next weapon hit. Their
pipelines use bespoke arm primitives (no attack/save_modifier), so the
generic extract_buff_effect path returned 0 — the AI never cast them.
This wires scorers so both are valued by the caster's next-hit
probability × the rider's payoff.

Layers:
  1. _self_next_hit_prob returns the best weapon's p_hit (0 if none)
  2. _caster_spell_dc is ability-aware (WIS Ranger / CHA Paladin)
  3. _score_searing_smite > 0 with an enemy + weapon; 0 otherwise
  4. _score_ensnaring_strike > 0 with an enemy + weapon; 0 otherwise
  5. both = 0 with no enemies / no weapon
  6. defensive_ehp_defensive_buff dispatches both to nonzero
  7. score_candidate routes both to nonzero (real built spells)
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.ai.defensive_ehp import (
    _self_next_hit_prob, _caster_spell_dc,
    _score_searing_smite, _score_ensnaring_strike,
    defensive_ehp_defensive_buff,
)
from engine.ai.ehp_scoring import score_candidate
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"

_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True,
                                   schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _abilities(**overrides):
    base = {a: {"score": 12, "save": 1}
              for a in ("str", "dex", "con", "int", "wis", "cha")}
    for k, v in overrides.items():
        base[k] = v
    return base


def _weapon(bonus=6):
    return {"id": "a_sword", "type": "weapon_attack",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "melee", "bonus": bonus,
                              "reach_ft": 5}},
                {"primitive": "damage",
                  "params": {"dice": "1d8", "modifier": 3,
                              "type": "slashing"}},
            ]}


def _actor(actor_id, *, side="pc", position=(0, 0), actions=None,
             abilities=None, template_extra=None):
    template = {"id": "t", "name": actor_id,
                "abilities": abilities or _abilities(),
                "cr": {"proficiency_bonus": 2},
                "actions": actions if actions is not None else [_weapon()]}
    if template_extra:
        template.update(template_extra)
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                   hp_current=40, hp_max=40, ac=15,
                   speed={"walk": 30}, position=position,
                   abilities=abilities or _abilities())


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


# ============================================================================
# Layer 1+2: helpers
# ============================================================================

class HelperTest(unittest.TestCase):

    def test_next_hit_prob_positive(self) -> None:
        self.assertGreater(_self_next_hit_prob(_actor("a")), 0.0)

    def test_next_hit_prob_zero_without_weapon(self) -> None:
        self.assertEqual(_self_next_hit_prob(_actor("a", actions=[])), 0.0)

    def test_caster_dc_uses_wisdom(self) -> None:
        # WIS 18 (+4), PB 2 → 14
        ranger = _actor("r", abilities=_abilities(wis={"score": 18}),
                          template_extra={"spellcasting_ability": "wisdom"})
        self.assertEqual(_caster_spell_dc(ranger), 14)

    def test_caster_dc_falls_back_to_charisma(self) -> None:
        # CHA 16 (+3), PB 2 → 13
        pal = _actor("p", abilities=_abilities(cha={"score": 16}),
                       template_extra={"spellcasting_ability": "charisma"})
        self.assertEqual(_caster_spell_dc(pal), 13)


# ============================================================================
# Layer 3+4+5: scorers
# ============================================================================

class ScorerTest(unittest.TestCase):

    def test_searing_positive(self) -> None:
        caster = _actor("paladin",
                          template_extra={"spellcasting_ability": "charisma"})
        foe = _actor("foe", side="enemy", position=(1, 0))
        st = _state([caster, foe])
        self.assertGreater(_score_searing_smite(caster, st), 0.0)

    def test_ensnaring_positive(self) -> None:
        caster = _actor("ranger",
                          template_extra={"spellcasting_ability": "wisdom"})
        foe = _actor("foe", side="enemy", position=(1, 0))
        st = _state([caster, foe])
        self.assertGreater(_score_ensnaring_strike(caster, st), 0.0)

    def test_zero_without_enemies(self) -> None:
        caster = _actor("paladin")
        ally = _actor("ally", position=(1, 0))   # same side
        st = _state([caster, ally])
        self.assertEqual(_score_searing_smite(caster, st), 0.0)
        self.assertEqual(_score_ensnaring_strike(caster, st), 0.0)

    def test_zero_without_weapon(self) -> None:
        caster = _actor("caster", actions=[])     # no weapon to land
        foe = _actor("foe", side="enemy", position=(1, 0))
        st = _state([caster, foe])
        self.assertEqual(_score_searing_smite(caster, st), 0.0)
        self.assertEqual(_score_ensnaring_strike(caster, st), 0.0)


# ============================================================================
# Layer 6+7: dispatch through the public scorers (real built spells)
# ============================================================================

class DispatchTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def _build_paladin(self):
        return build_pc_template({
            "id": "pal2", "class": "c_paladin", "level": 2,
            "ability_scores": {"str": 16, "dex": 12, "con": 14,
                                  "int": 10, "wis": 12, "cha": 16},
            "weapons": [{"id": "longsword", "name": "Longsword",
                          "damage_dice": "1d8", "damage_type": "slashing",
                          "attack_ability": "str"}],
        }, self.registry)

    def _build_ranger(self):
        return build_pc_template({
            "id": "r2", "class": "c_ranger", "level": 2,
            "ability_scores": {"str": 12, "dex": 16, "con": 14,
                                  "int": 10, "wis": 16, "cha": 8},
            "weapons": [{"id": "longbow", "name": "Longbow",
                          "damage_dice": "1d8", "damage_type": "piercing",
                          "attack_ability": "dex"}],
        }, self.registry)

    def _goblin(self):
        return Actor(id="goblin", name="goblin",
                       template={"id": "t", "name": "g",
                                   "abilities": _abilities(),
                                   "cr": {"proficiency_bonus": 2},
                                   "actions": [_weapon(4)]},
                       side="enemy", hp_current=30, hp_max=30, ac=13,
                       speed={"walk": 30}, position=(1, 0),
                       abilities=_abilities())

    def test_searing_smite_dispatches(self) -> None:
        template = self._build_paladin()
        paladin = Actor(id="pal", name="pal", template=template, side="pc",
                          hp_current=40, hp_max=40, ac=18, position=(0, 0),
                          abilities=template["abilities"])
        st = _state([paladin, self._goblin()])
        ss = next(a for a in template["actions"]
                    if a.get("id") == "a_searing_smite")
        self.assertGreater(
            defensive_ehp_defensive_buff(paladin, paladin, ss, st), 0.0)
        self.assertGreater(
            score_candidate({"kind": "defensive_buff", "action": ss,
                               "actor": paladin, "target": paladin}, st),
            0.0)

    def test_ensnaring_strike_dispatches(self) -> None:
        template = self._build_ranger()
        ranger = Actor(id="rng", name="rng", template=template, side="pc",
                         hp_current=40, hp_max=40, ac=15, position=(0, 0),
                         abilities=template["abilities"])
        st = _state([ranger, self._goblin()])
        es = next(a for a in template["actions"]
                    if a.get("id") == "a_ensnaring_strike")
        self.assertGreater(
            defensive_ehp_defensive_buff(ranger, ranger, es, st), 0.0)
        self.assertGreater(
            score_candidate({"kind": "defensive_buff", "action": es,
                               "actor": ranger, "target": ranger}, st),
            0.0)


if __name__ == "__main__":
    unittest.main()
