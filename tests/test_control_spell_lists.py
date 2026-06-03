"""Control-spell class-list wiring (caster-lane content batch).

Motivating bug: a Lore Bard wasted a fight casting Hold Person
(Humanoid-only) at a dragon, because the Bard's spell list granted
Hold Person but not the any-creature lockdowns. These tests assert that
the dragon-applicable control spells are now on the right class lists
(Bard / Sorcerer per the SRD) and that the any-creature lockdown
(Hold Monster) actually paralyzes a non-Humanoid (dragon) target.

Runnability of each spell's pipeline is already covered by its own test
(test_hold_monster / test_hypnotic_pattern / test_web); this file pins
the wiring + the cross-type fix.
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core import pipeline
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template
from engine.primitives import PrimitiveRegistry

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True, schema_root=SCHEMA_ROOT)
    return _REGISTRY


def _pc(cls, level):
    spec = {"class": cls, "level": level,
            "ability_scores": {"str": 10, "dex": 12, "con": 12,
                                 "int": 12, "wis": 12, "cha": 16}}
    return build_pc_template(spec, _registry())


def _action_ids(template):
    return {a.get("id") for a in template.get("actions", [])}


def _action(template, action_id):
    return next(a for a in template["actions"] if a["id"] == action_id)


class ControlSpellWiringTest(unittest.TestCase):

    def test_bard_gets_any_creature_control(self):
        # The fix: a Bard now learns Hold Monster (L9) and Hypnotic Pattern
        # (L5), not only the Humanoid-only Hold Person.
        bard = _pc("c_bard", 9)
        ids = _action_ids(bard)
        self.assertIn("a_hold_monster", ids)
        self.assertIn("a_hypnotic_pattern", ids)
        self.assertIn("a_hold_person", ids)        # still present

    def test_bard_hypnotic_pattern_available_at_5(self):
        self.assertIn("a_hypnotic_pattern", _action_ids(_pc("c_bard", 5)))
        # but Hold Monster (L5 spell) not until character L9
        self.assertNotIn("a_hold_monster", _action_ids(_pc("c_bard", 5)))

    def test_sorcerer_gets_web_and_holds(self):
        sorc = _pc("c_sorcerer", 9)
        ids = _action_ids(sorc)
        self.assertIn("a_web", ids)                 # L3 spell, Sorc list
        self.assertIn("a_hypnotic_pattern", ids)
        self.assertIn("a_hold_monster", ids)

    def test_web_not_on_bard_list(self):
        # Web is Sorcerer/Wizard only (not Bard) — must NOT leak onto Bard.
        self.assertNotIn("a_web", _action_ids(_pc("c_bard", 20)))


class HoldMonsterCrossTypeTest(unittest.TestCase):
    """The any-creature lockdown must work on a non-Humanoid (dragon)."""

    def setUp(self):
        primitives_module.set_rng(random.Random(3))

    def _dragon(self):
        m = _registry().get("monster", "m_adult_red_dragon")
        hp = m["combat"]["hit_points"]["average"]
        # Force the WIS save to fail: a deeply negative save modifier.
        ab = dict(m["abilities"])
        ab["wis"] = {"score": 1, "save": -20}
        return Actor(id="drag", name=m["name"], template=m, side="enemy",
                       hp_current=hp, hp_max=hp, ac=m["combat"]["armor_class"],
                       speed={"walk": 40}, position=(2, 0), abilities=ab)

    def test_hold_monster_paralyzes_a_dragon(self):
        bard = _pc("c_bard", 9)
        caster = Actor(id="bard", name="Bard", template=bard, side="pc",
                         hp_current=60, hp_max=60, ac=bard["combat"]["armor_class"],
                         speed={"walk": 30}, position=(0, 0), abilities=bard["abilities"],
                         spell_slots={5: 1})
        dragon = self._dragon()
        enc = Encounter(id="t", actors=[caster, dragon])
        st = CombatState(encounter=enc)
        st.turn_order = ["bard", "drag"]
        st.round = 1
        st.content_registry = _registry()
        chosen = {"kind": "hard_control", "action": _action(bard, "a_hold_monster"),
                    "target": dragon, "actor": caster}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        self.assertIn("co_paralyzed", [c["condition_id"] for c in dragon.applied_conditions])


if __name__ == "__main__":
    unittest.main()
