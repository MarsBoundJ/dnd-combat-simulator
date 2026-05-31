"""Spirit Guardians tests (PR #117).

The Cleric's signature battlefield-control aura — a 3rd-level
persistent_aura (WIS save, 3d8 radiant, self-anchored, enemies only).
The content shipped forward-compat in PR #79; this PR wires it onto
c_cleric L5 (when 3rd-level slots arrive), lighting it up the same way
Ranger spellcasting lit up Hunter's Mark.

Layers:
  1. f_spirit_guardians loads (Cleric, 3rd-level, persistent_aura)
  2. c_cleric L5 lists it
  3. auto-attach: a_spirit_guardians present at L5, absent at L3
  4. scoring: offensive_ehp_persistent_aura > 0 with enemies near caster
  5. candidate generation emits the aura (bonus-action slot)
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.ai.ehp_scoring import offensive_ehp_persistent_aura
from engine.core import pipeline
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


def _build_cleric(level, wis=16):
    return build_pc_template({
        "id": f"cleric{level}", "class": "c_cleric", "level": level,
        "ability_scores": {"str": 10, "dex": 12, "con": 14,
                              "int": 10, "wis": wis, "cha": 12},
        "weapons": [{"id": "mace", "name": "Mace", "damage_dice": "1d6",
                       "damage_type": "bludgeoning", "attack_ability": "str"}],
    }, _registry())


def _enemy(enemy_id, pos, hp=30):
    return Actor(id=enemy_id, name=enemy_id,
                   template={"id": "t", "name": enemy_id, "abilities": {},
                               "cr": {"proficiency_bonus": 2}, "actions": []},
                   side="enemy", hp_current=hp, hp_max=hp, ac=13,
                   speed={"walk": 30}, position=pos, abilities={})


def _cleric_actor(level=5, wis=16):
    template = _build_cleric(level, wis)
    actor = Actor(id="cleric", name="cleric", template=template, side="pc",
                    hp_current=40, hp_max=40, ac=16, position=(0, 0),
                    abilities=template["abilities"],
                    spell_slots=dict(template.get("spell_slots") or {}))
    return actor, template


def _state(actors):
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    return st


# ============================================================================
# Layers 1+2: content + class wiring
# ============================================================================

class WiringTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_f_spirit_guardians_loads(self) -> None:
        feat = self.registry.get("feature", "f_spirit_guardians")
        self.assertEqual(feat["granted_by"]["class"], "c_cleric")
        self.assertEqual(feat["spell"]["level"], 3)
        tmpl = feat["action_template"]
        self.assertEqual(tmpl["type"], "persistent_aura")
        self.assertEqual(tmpl["slot"], "bonus_action")
        self.assertTrue(tmpl["concentration"])

    def test_l5_lists_spirit_guardians(self) -> None:
        l5 = next(r for r in self.registry.get("class", "c_cleric")
                    ["level_table"] if r["level"] == 5)
        self.assertIn("f_spirit_guardians", l5["features"])


# ============================================================================
# Layer 3: auto-attach + level gating
# ============================================================================

class AutoAttachTest(unittest.TestCase):

    def test_attached_at_l5(self) -> None:
        ids = {a.get("id") for a in _build_cleric(5)["actions"]}
        self.assertIn("a_spirit_guardians", ids)

    def test_absent_at_l3(self) -> None:
        # 3rd-level slots (hence Spirit Guardians) arrive at L5; an L3
        # Cleric doesn't know it yet.
        ids = {a.get("id") for a in _build_cleric(3)["actions"]}
        self.assertNotIn("a_spirit_guardians", ids)


# ============================================================================
# Layer 4: scoring
# ============================================================================

class ScoringTest(unittest.TestCase):

    def test_positive_with_enemies_in_radius(self) -> None:
        cleric, template = _cleric_actor(5)
        e1 = _enemy("e1", (1, 0))
        e2 = _enemy("e2", (2, 0))
        state = _state([cleric, e1, e2])
        sg = next(a for a in template["actions"]
                    if a.get("id") == "a_spirit_guardians")
        score = offensive_ehp_persistent_aura(
            cleric, sg, state, origin=cleric.position)
        self.assertGreater(score, 0.0)

    def test_zero_with_no_enemies_in_radius(self) -> None:
        cleric, template = _cleric_actor(5)
        far = _enemy("far", (50, 50))   # well outside 15 ft
        state = _state([cleric, far])
        sg = next(a for a in template["actions"]
                    if a.get("id") == "a_spirit_guardians")
        score = offensive_ehp_persistent_aura(
            cleric, sg, state, origin=cleric.position)
        self.assertEqual(score, 0.0)


# ============================================================================
# Layer 5: candidate generation (bonus-action slot)
# ============================================================================

class CandidateTest(unittest.TestCase):

    def test_aura_candidate_emitted(self) -> None:
        cleric, _ = _cleric_actor(5)
        enemy = _enemy("e", (1, 0))
        state = _state([cleric, enemy])
        cands = pipeline.generate_candidates(cleric, state,
                                                slot="bonus_action")
        sg = [c for c in cands
                if c.get("action", {}).get("id") == "a_spirit_guardians"]
        self.assertGreaterEqual(len(sg), 1)
        self.assertEqual(sg[0]["kind"], "persistent_aura")


if __name__ == "__main__":
    unittest.main()
