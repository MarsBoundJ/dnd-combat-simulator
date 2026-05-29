"""Agonizing Blast invocation tests (PR #103).

The Warlock's most-taken Eldritch Invocation: adds CHA mod to each
Eldritch Blast beam's damage. Bootstraps a minimal invocations
system — player-chosen Warlock features declared via pc_spec
`invocations: [...]`, validated + merged into features_known.

Layers:
  1. f_agonizing_blast loads
  2. Invocation selection: pc_spec.invocations merges into
     features_known
  3. EB beam damage_mod = CHA mod when Agonizing Blast known
  4. Without the invocation, EB beam damage_mod = 0
  5. Multiattack beams ALL inherit the bonus (rides the single beam)
  6. Validation: non-Warlock can't take invocations
  7. Validation: unknown invocation id raises
  8. Validation: Agonizing Blast requires Eldritch Blast prereq
  9. End-to-end: Agonizing EB hits for 1d10 + CHA force
"""
from __future__ import annotations

import random
import unittest
from pathlib import Path

import engine.primitives as primitives_module
from engine.core.events import EventBus
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template
from engine.primitives import PrimitiveRegistry


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


def _registry():
    return load_content(CONTENT_ROOT, validate=True,
                          schema_root=SCHEMA_ROOT)


def _build_warlock(registry, level=1, cha=16, invocations=None,
                     class_id="c_warlock"):
    pc_spec = {
        "id": f"wl{level}", "class": class_id, "level": level,
        "ability_scores": {"str": 8, "dex": 14, "con": 14,
                              "int": 10, "wis": 12, "cha": cha},
        "weapons": [],
    }
    if invocations is not None:
        pc_spec["invocations"] = invocations
    return build_pc_template(pc_spec, registry)


def _beam(template):
    return next(a for a in template.get("actions", [])
                  if a.get("id") == "a_eldritch_blast")


# ============================================================================
# Layer 1+2: load + selection
# ============================================================================

class SelectionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_f_agonizing_blast_loads(self) -> None:
        feature = self.registry.get("feature", "f_agonizing_blast")
        self.assertEqual(feature["granted_by"]["class"], "c_warlock")

    def test_invocation_merged_into_features_known(self) -> None:
        template = _build_warlock(self.registry, 1,
                                     invocations=["f_agonizing_blast"])
        self.assertIn("f_agonizing_blast",
                        template.get("features_known", []))

    def test_no_invocations_by_default(self) -> None:
        template = _build_warlock(self.registry, 1)
        self.assertNotIn("f_agonizing_blast",
                            template.get("features_known", []))


# ============================================================================
# Layer 3+4+5: damage bonus on beams
# ============================================================================

class DamageBonusTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_agonizing_adds_cha_to_beam_damage(self) -> None:
        # CHA 16 → +3
        template = _build_warlock(self.registry, 1, cha=16,
                                     invocations=["f_agonizing_blast"])
        beam = _beam(template)
        dmg = beam["pipeline"][1]["params"]
        self.assertEqual(dmg["modifier"], 3)
        self.assertEqual(dmg["dice"], "1d10")
        self.assertEqual(dmg["type"], "force")

    def test_without_invocation_no_bonus(self) -> None:
        template = _build_warlock(self.registry, 1, cha=16)
        beam = _beam(template)
        self.assertEqual(beam["pipeline"][1]["params"]["modifier"], 0)

    def test_multiattack_beams_inherit_bonus(self) -> None:
        # L5 Warlock w/ Agonizing: the multiattack references the
        # single beam, which carries the +CHA — so all beams benefit.
        template = _build_warlock(self.registry, 5, cha=18,
                                     invocations=["f_agonizing_blast"])
        beam = _beam(template)
        self.assertEqual(beam["pipeline"][1]["params"]["modifier"], 4)
        multi = next(a for a in template["actions"]
                       if a.get("id") == "a_eldritch_blast_beams")
        self.assertEqual(multi["sub_actions"],
                            ["a_eldritch_blast"] * 2)

    def test_agonizing_name_marked(self) -> None:
        template = _build_warlock(self.registry, 1,
                                     invocations=["f_agonizing_blast"])
        self.assertIn("Agonizing", _beam(template)["name"])


# ============================================================================
# Layer 6+7+8: validation
# ============================================================================

class ValidationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_non_warlock_cannot_take_invocations(self) -> None:
        with self.assertRaises(ValueError):
            _build_warlock(self.registry, 5, class_id="c_fighter",
                             invocations=["f_agonizing_blast"])

    def test_unknown_invocation_raises(self) -> None:
        with self.assertRaises(ValueError):
            _build_warlock(self.registry, 1,
                             invocations=["f_not_a_real_invocation"])

    def test_agonizing_requires_eldritch_blast(self) -> None:
        # _validate_invocations checks f_eldritch_blast in
        # features_known. A Warlock always knows EB at L1 (it's in the
        # class table), so to test the prereq failure we validate the
        # helper directly with an EB-less feature set.
        from engine.pc_schema import _validate_invocations
        with self.assertRaises(ValueError):
            _validate_invocations(["f_agonizing_blast"],
                                    features_known=set(),  # no EB
                                    class_id="c_warlock", level=1)

    def test_duplicate_invocations_deduped(self) -> None:
        from engine.pc_schema import _validate_invocations
        result = _validate_invocations(
            ["f_agonizing_blast", "f_agonizing_blast"],
            features_known={"f_eldritch_blast"},
            class_id="c_warlock", level=1)
        self.assertEqual(result, ["f_agonizing_blast"])


# ============================================================================
# Layer 9: end-to-end
# ============================================================================

class EndToEndTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def test_agonizing_eb_deals_extra_damage(self) -> None:
        from engine.core import pipeline
        template = _build_warlock(self.registry, 1, cha=16,
                                     invocations=["f_agonizing_blast"])
        wl = Actor(id="wl", name="wl", template=template, side="pc",
                     hp_current=20, hp_max=20, ac=12, position=(0, 0),
                     abilities=template["abilities"])
        goblin = Actor(id="goblin", name="goblin",
                         template={"id": "t", "name": "g",
                                     "abilities": {}, "actions": []},
                         side="enemy", hp_current=50, hp_max=50,
                         ac=1, position=(2, 0), abilities={})
        enc = Encounter(id="t", actors=[wl, goblin])
        state = CombatState(encounter=enc)
        state.turn_order = ["wl", "goblin"]
        state.round = 1
        beam = _beam(template)
        chosen = {"kind": "weapon_attack", "action": beam,
                    "target": goblin, "actor": wl}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        dmg = 50 - goblin.hp_current
        # 1d10 (1-10) + 3 CHA = 4-13, so at least 4
        self.assertGreaterEqual(dmg, 4)


if __name__ == "__main__":
    unittest.main()
