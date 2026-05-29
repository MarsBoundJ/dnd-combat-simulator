"""Self weapon-damage buff scoring — "buff before burst" (PR #109).

Divine Favor is a self-targeted weapon_damage_bonus buff (+N on every
weapon hit). `extract_buff_effect` only recognizes AC / save /
disadvantage shapes, so before this PR Divine Favor scored 0.0 and the
AI never cast it. The new `_score_self_weapon_damage_buff` values it by
the caster's OWN expected hits across the buff's lifetime — the
buff-before-burst payoff.

Layers:
  1. _extract_self_weapon_damage_bonus reads the self +N (0 otherwise)
  2. _expected_hits_per_round scales with multiattack count
  3. _score_self_weapon_damage_buff > 0 for a self weapon-damage buff
  4. = 0 with no enemies / no weapon attacks
  5. multiattacker values it more (more hits to ride the bonus)
  6. defensive_ehp_defensive_buff dispatches Divine Favor to nonzero
  7. score_candidate routes a Divine Favor defensive_buff to nonzero
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.ai.defensive_ehp import (
    _extract_self_weapon_damage_bonus, _expected_hits_per_round,
    _score_self_weapon_damage_buff, defensive_ehp_defensive_buff,
)
from engine.ai.ehp_scoring import score_candidate
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


def _registry():
    return load_content(CONTENT_ROOT, validate=True,
                          schema_root=SCHEMA_ROOT)


def _weapon(action_id="a_sword", bonus=5):
    return {"id": action_id, "type": "weapon_attack",
            "pipeline": [
                {"primitive": "attack_roll",
                  "params": {"kind": "melee", "bonus": bonus,
                              "reach_ft": 5}},
                {"primitive": "damage",
                  "params": {"dice": "1d8", "modifier": 3,
                              "type": "slashing"}},
            ]}


def _multiattack(count=2):
    return {"id": "a_extra_attack", "type": "multiattack",
            "count": count, "sub_actions": ["a_sword"] * count}


def _divine_favor_action():
    return {"id": "a_divine_favor", "type": "defensive_buff",
            "slot": "bonus_action", "concentration": True,
            "pipeline": [
                {"primitive": "weapon_damage_bonus",
                  "params": {"target": "self", "value": 2,
                              "when": "weapon_attack",
                              "lifetime": "until_short_rest"}},
            ]}


def _actor(actor_id, *, side="pc", position=(0, 0), actions=None,
             speed=30):
    template = {"id": "t", "name": actor_id, "abilities": {},
                "cr": {"proficiency_bonus": 2},
                "actions": actions if actions is not None else [_weapon()]}
    return Actor(id=actor_id, name=actor_id, template=template, side=side,
                   hp_current=40, hp_max=40, ac=16,
                   speed={"walk": speed}, position=position, abilities={})


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

    def test_extract_self_bonus(self) -> None:
        self.assertEqual(
            _extract_self_weapon_damage_bonus(_divine_favor_action()), 2)

    def test_extract_zero_for_non_self(self) -> None:
        ac_buff = {"pipeline": [
            {"primitive": "attack_modifier",
              "params": {"target": "self", "modifier": "ac_modifier",
                          "value": 2}}]}
        self.assertEqual(_extract_self_weapon_damage_bonus(ac_buff), 0)

    def test_hits_scale_with_multiattack(self) -> None:
        single = _actor("single", actions=[_weapon()])
        multi = _actor("multi", actions=[_weapon(), _multiattack(2)])
        self.assertGreater(_expected_hits_per_round(multi),
                             _expected_hits_per_round(single))


# ============================================================================
# Layer 3+4+5: scorer
# ============================================================================

class ScorerTest(unittest.TestCase):

    def test_positive_with_enemy_and_weapon(self) -> None:
        paladin = _actor("paladin")
        foe = _actor("foe", side="enemy", position=(1, 0))
        st = _state([paladin, foe])
        score = _score_self_weapon_damage_buff(
            paladin, _divine_favor_action(), st)
        self.assertGreater(score, 0.0)

    def test_zero_without_enemies(self) -> None:
        paladin = _actor("paladin")
        ally = _actor("ally", position=(1, 0))   # same side
        st = _state([paladin, ally])
        self.assertEqual(
            _score_self_weapon_damage_buff(
                paladin, _divine_favor_action(), st), 0.0)

    def test_zero_without_weapon_attacks(self) -> None:
        caster = _actor("caster", actions=[])     # no weapons
        foe = _actor("foe", side="enemy", position=(1, 0))
        st = _state([caster, foe])
        self.assertEqual(
            _score_self_weapon_damage_buff(
                caster, _divine_favor_action(), st), 0.0)

    def test_multiattacker_values_it_more(self) -> None:
        single = _actor("single", actions=[_weapon()])
        multi = _actor("multi", actions=[_weapon(), _multiattack(2)])
        foe_a = _actor("foe_a", side="enemy", position=(1, 0))
        foe_b = _actor("foe_b", side="enemy", position=(1, 0))
        st_s = _state([single, foe_a])
        st_m = _state([multi, foe_b])
        df = _divine_favor_action()
        self.assertGreater(
            _score_self_weapon_damage_buff(multi, df, st_m),
            _score_self_weapon_damage_buff(single, df, st_s))


# ============================================================================
# Layer 6+7: dispatch through the public scorers (real Divine Favor)
# ============================================================================

class DispatchTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def _build_paladin(self, level=2):
        pc_spec = {
            "id": f"pal{level}", "class": "c_paladin", "level": level,
            "ability_scores": {"str": 16, "dex": 12, "con": 14,
                                  "int": 10, "wis": 12, "cha": 16},
            "weapons": [{"id": "longsword", "name": "Longsword",
                          "damage_dice": "1d8", "damage_type": "slashing",
                          "attack_ability": "str"}],
        }
        return build_pc_template(pc_spec, self.registry)

    def test_defensive_buff_scorer_picks_up_divine_favor(self) -> None:
        template = self._build_paladin(2)
        paladin = Actor(id="pal", name="pal", template=template, side="pc",
                          hp_current=40, hp_max=40, ac=18, position=(0, 0),
                          abilities=template["abilities"])
        goblin = Actor(id="goblin", name="goblin",
                         template={"id": "t", "name": "g", "abilities": {},
                                     "actions": [_weapon("a_scim", 4)]},
                         side="enemy", hp_current=30, hp_max=30, ac=13,
                         speed={"walk": 30}, position=(1, 0), abilities={})
        st = _state([paladin, goblin])
        df = next(a for a in template["actions"]
                    if a.get("id") == "a_divine_favor")
        # Self-targeted: target_ally == the paladin
        score = defensive_ehp_defensive_buff(paladin, paladin, df, st)
        self.assertGreater(score, 0.0)

    def test_score_candidate_routes_divine_favor(self) -> None:
        template = self._build_paladin(2)
        paladin = Actor(id="pal", name="pal", template=template, side="pc",
                          hp_current=40, hp_max=40, ac=18, position=(0, 0),
                          abilities=template["abilities"])
        goblin = Actor(id="goblin", name="goblin",
                         template={"id": "t", "name": "g", "abilities": {},
                                     "actions": [_weapon("a_scim", 4)]},
                         side="enemy", hp_current=30, hp_max=30, ac=13,
                         speed={"walk": 30}, position=(1, 0), abilities={})
        st = _state([paladin, goblin])
        df = next(a for a in template["actions"]
                    if a.get("id") == "a_divine_favor")
        score = score_candidate(
            {"kind": "defensive_buff", "action": df,
              "actor": paladin, "target": paladin}, st)
        self.assertGreater(score, 0.0)


if __name__ == "__main__":
    unittest.main()
