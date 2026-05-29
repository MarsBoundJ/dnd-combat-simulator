"""Repelling Blast invocation tests (PR #106).

The classic control Eldritch Invocation: when an Eldritch Blast beam
hits, push the target up to 10 ft straight away from the Warlock.
Second invocation in the system bootstrapped by Agonizing Blast
(PR #103); also introduces the generic `forced_movement` pipeline
primitive (a push wrapper over geometry.push_creature).

Layers:
  1. f_repelling_blast loads
  2. Invocation selection: pc_spec.invocations merges into
     features_known
  3. EB beam gains a forced_movement step (gated on hit) when known
  4. Without the invocation, no forced_movement step
  5. Multiattack beams ALL inherit the push (rides the single beam)
  6. Name marked "Repelling"; composes with Agonizing
  7. Validation: Repelling Blast requires Eldritch Blast prereq
  8. forced_movement primitive: pushes away + size gate
  9. End-to-end: a hit pushes the target 10 ft; a miss does not
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


def _push_step(beam):
    return next((s for s in beam["pipeline"]
                   if s.get("primitive") == "forced_movement"), None)


# ============================================================================
# Layer 1+2: load + selection
# ============================================================================

class SelectionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_f_repelling_blast_loads(self) -> None:
        feature = self.registry.get("feature", "f_repelling_blast")
        self.assertEqual(feature["granted_by"]["class"], "c_warlock")

    def test_invocation_merged_into_features_known(self) -> None:
        template = _build_warlock(self.registry, 1,
                                     invocations=["f_repelling_blast"])
        self.assertIn("f_repelling_blast",
                        template.get("features_known", []))


# ============================================================================
# Layer 3+4+5: forced_movement step on beams
# ============================================================================

class PushStepTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_repelling_adds_push_step(self) -> None:
        template = _build_warlock(self.registry, 1,
                                     invocations=["f_repelling_blast"])
        step = _push_step(_beam(template))
        self.assertIsNotNone(step)
        self.assertEqual(step["params"]["distance_ft"], 10)
        # Gated on hit
        self.assertIn("attack_state == hit",
                        step["when"]["condition"])

    def test_without_invocation_no_push_step(self) -> None:
        template = _build_warlock(self.registry, 1)
        self.assertIsNone(_push_step(_beam(template)))

    def test_multiattack_beams_inherit_push(self) -> None:
        # L5 Warlock: the multiattack references the single beam, which
        # carries the push — so all beams push.
        template = _build_warlock(self.registry, 5,
                                     invocations=["f_repelling_blast"])
        self.assertIsNotNone(_push_step(_beam(template)))
        multi = next(a for a in template["actions"]
                       if a.get("id") == "a_eldritch_blast_beams")
        self.assertEqual(multi["sub_actions"],
                            ["a_eldritch_blast"] * 2)


# ============================================================================
# Layer 6: naming + composition with Agonizing Blast
# ============================================================================

class NamingTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_repelling_name_marked(self) -> None:
        template = _build_warlock(self.registry, 1,
                                     invocations=["f_repelling_blast"])
        self.assertIn("Repelling", _beam(template)["name"])

    def test_composes_with_agonizing(self) -> None:
        # Both invocations: name lists both, damage gets CHA mod AND
        # the push step is present.
        template = _build_warlock(
            self.registry, 1, cha=16,
            invocations=["f_agonizing_blast", "f_repelling_blast"])
        beam = _beam(template)
        self.assertIn("Agonizing", beam["name"])
        self.assertIn("Repelling", beam["name"])
        self.assertEqual(beam["pipeline"][1]["params"]["modifier"], 3)
        self.assertIsNotNone(_push_step(beam))


# ============================================================================
# Layer 7: validation
# ============================================================================

class ValidationTest(unittest.TestCase):

    def test_repelling_requires_eldritch_blast(self) -> None:
        from engine.pc_schema import _validate_invocations
        with self.assertRaises(ValueError):
            _validate_invocations(["f_repelling_blast"],
                                    features_known=set(),  # no EB
                                    class_id="c_warlock", level=1)

    def test_repelling_validates_with_eldritch_blast(self) -> None:
        from engine.pc_schema import _validate_invocations
        result = _validate_invocations(
            ["f_repelling_blast"],
            features_known={"f_eldritch_blast"},
            class_id="c_warlock", level=1)
        self.assertEqual(result, ["f_repelling_blast"])


# ============================================================================
# Layer 8: forced_movement primitive
# ============================================================================

class ForcedMovementPrimitiveTest(unittest.TestCase):

    def _actor(self, aid, pos, *, size=None):
        return Actor(id=aid, name=aid,
                       template={"id": "t", "name": aid,
                                   "abilities": {}, "actions": []},
                       side="pc" if aid == "wl" else "enemy",
                       hp_current=20, hp_max=20, ac=10, position=pos,
                       abilities={}, size=size)

    def _state(self, actor, target):
        enc = Encounter(id="t", actors=[actor, target])
        state = CombatState(encounter=enc)
        state.turn_order = [actor.id, target.id]
        state.round = 1
        state.current_attack = {"actor": actor, "target": target}
        return state

    def test_pushes_target_away(self) -> None:
        wl = self._actor("wl", (0, 0))
        foe = self._actor("foe", (2, 0))      # 10 ft east
        state = self._state(wl, foe)
        primitives_module._forced_movement(
            {"distance_ft": 10}, state, EventBus())
        # Pushed 10 ft (2 squares) further east → (4, 0)
        self.assertEqual(foe.position, (4, 0))

    def test_huge_target_immune(self) -> None:
        wl = self._actor("wl", (0, 0))
        dragon = self._actor("foe", (2, 0), size="huge")
        state = self._state(wl, dragon)
        primitives_module._forced_movement(
            {"distance_ft": 10}, state, EventBus())
        self.assertEqual(dragon.position, (2, 0))   # unmoved
        self.assertTrue(any(
            e.get("event") == "forced_movement_skipped"
            and e.get("reason") == "size_immune"
            for e in state.event_log))


# ============================================================================
# Layer 9: end-to-end
# ============================================================================

class EndToEndTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def setUp(self) -> None:
        primitives_module.set_rng(random.Random(7))

    def _run(self, target_ac):
        from engine.core import pipeline
        template = _build_warlock(self.registry, 1, cha=16,
                                     invocations=["f_repelling_blast"])
        wl = Actor(id="wl", name="wl", template=template, side="pc",
                     hp_current=20, hp_max=20, ac=12, position=(0, 0),
                     abilities=template["abilities"])
        goblin = Actor(id="goblin", name="goblin",
                         template={"id": "t", "name": "g",
                                     "abilities": {}, "actions": []},
                         side="enemy", hp_current=50, hp_max=50,
                         ac=target_ac, position=(2, 0), abilities={})
        enc = Encounter(id="t", actors=[wl, goblin])
        state = CombatState(encounter=enc)
        state.turn_order = ["wl", "goblin"]
        state.round = 1
        beam = _beam(template)
        chosen = {"kind": "weapon_attack", "action": beam,
                    "target": goblin, "actor": wl}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        return goblin

    def test_hit_pushes_target(self) -> None:
        # AC 1 → guaranteed hit → pushed 10 ft east from (2,0) to (4,0)
        goblin = self._run(target_ac=1)
        self.assertEqual(goblin.position, (4, 0))

    def test_miss_does_not_push(self) -> None:
        # AC 99 → guaranteed miss → no push (gated on hit)
        goblin = self._run(target_ac=99)
        self.assertEqual(goblin.position, (2, 0))


if __name__ == "__main__":
    unittest.main()
