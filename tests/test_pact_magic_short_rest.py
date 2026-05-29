"""Pact Magic short-rest slot recovery tests (PR #101).

Closes the c_warlock (PR #100) deferral: Warlock Pact Magic slots
recover on a SHORT rest (the class's signature short-rest economy),
unlike every other caster whose slots are long-rest only.

Layers:
  1. Warlock short rest restores expended pact slots to max
  2. Short rest with full slots is a no-op (summary omits the key)
  3. NON-Warlock caster's slots are NOT restored on short rest
     (regression guard — the gate must be class-specific)
  4. Restore summary reports per-level counts + logs an event
  5. End-to-end: cast Hex (expend slot) → short rest → slot back
"""
from __future__ import annotations

import unittest
from pathlib import Path

from engine.core.rest import apply_short_rest
from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content
from engine.pc_schema import build_pc_template


REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"


def _registry():
    return load_content(CONTENT_ROOT, validate=True,
                          schema_root=SCHEMA_ROOT)


def _pc_actor(registry, class_id, level, slots_override=None):
    pc_spec = {
        "id": f"{class_id}{level}", "class": class_id, "level": level,
        "ability_scores": {"str": 10, "dex": 12, "con": 14,
                              "int": 14, "wis": 12, "cha": 16},
        "weapons": [],
    }
    template = build_pc_template(pc_spec, registry)
    slots = dict(template.get("spell_slots") or {})
    return Actor(
        id=f"{class_id}{level}", name=class_id, template=template,
        side="pc", hp_current=20, hp_max=20, ac=12,
        speed={"walk": 30}, position=(0, 0),
        abilities=template["abilities"],
        spell_slots=dict(slots_override) if slots_override is not None
                      else dict(slots),
        spell_slots_max=dict(slots),
    )


def _make_state(actors):
    enc = Encounter(id="t", actors=actors)
    state = CombatState(encounter=enc)
    state.turn_order = [a.id for a in actors]
    state.round = 1
    return state


class WarlockShortRestTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_short_rest_restores_expended_pact_slots(self) -> None:
        # L2 Warlock: 2 first-level slots. Expend both, short rest,
        # both back.
        wl = _pc_actor(self.registry, "c_warlock", 2,
                         slots_override={1: 0})
        state = _make_state([wl])
        summary = apply_short_rest(wl, state)
        self.assertEqual(wl.spell_slots, {1: 2})
        self.assertEqual(summary.get("pact_magic_refresh"), {1: 2})

    def test_short_rest_partial_expend(self) -> None:
        # L2 Warlock, one slot used → one restored.
        wl = _pc_actor(self.registry, "c_warlock", 2,
                         slots_override={1: 1})
        state = _make_state([wl])
        summary = apply_short_rest(wl, state)
        self.assertEqual(wl.spell_slots, {1: 2})
        self.assertEqual(summary.get("pact_magic_refresh"), {1: 1})

    def test_short_rest_full_slots_noop(self) -> None:
        wl = _pc_actor(self.registry, "c_warlock", 2)   # full {1:2}
        state = _make_state([wl])
        summary = apply_short_rest(wl, state)
        self.assertNotIn("pact_magic_refresh", summary)

    def test_higher_level_pact_slots_restore(self) -> None:
        # L11 Warlock: 3 slots @ 5th level. Expend all, short rest.
        wl = _pc_actor(self.registry, "c_warlock", 11,
                         slots_override={5: 0})
        state = _make_state([wl])
        apply_short_rest(wl, state)
        self.assertEqual(wl.spell_slots, {5: 3})

    def test_logs_event(self) -> None:
        wl = _pc_actor(self.registry, "c_warlock", 2,
                         slots_override={1: 0})
        state = _make_state([wl])
        apply_short_rest(wl, state)
        events = [e for e in state.event_log
                    if e.get("event") == "pact_magic_slots_restored"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["restored"], {1: 2})


class NonWarlockRegressionTest(unittest.TestCase):
    """A non-Warlock caster's slots must NOT come back on short rest —
    the pact-magic refresh is class-gated."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_wizard_slots_not_restored_on_short_rest(self) -> None:
        # Wizard slots are long-rest only. Build a wizard, expend
        # slots, short rest — slots stay expended (arcane recovery is
        # separate + capped; here we force no recovery by checking the
        # raw slot dict isn't blanket-restored).
        wiz = _pc_actor(self.registry, "c_wizard", 1,
                          slots_override={1: 0})
        # Wizard may have arcane recovery; to isolate the pact-magic
        # path, assert no pact_magic_refresh key appears.
        state = _make_state([wiz])
        summary = apply_short_rest(wiz, state)
        self.assertNotIn("pact_magic_refresh", summary)

    def test_paladin_slots_not_restored_on_short_rest(self) -> None:
        pal = _pc_actor(self.registry, "c_paladin", 2,
                          slots_override={1: 0})
        state = _make_state([pal])
        summary = apply_short_rest(pal, state)
        self.assertNotIn("pact_magic_refresh", summary)
        # Paladin's 1st-level slot stays expended on short rest
        self.assertEqual(pal.spell_slots.get(1, 0), 0)


class EndToEndTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = _registry()

    def test_cast_hex_then_short_rest_restores(self) -> None:
        import random
        import engine.primitives as primitives_module
        from engine.core import pipeline
        from engine.core.events import EventBus
        from engine.primitives import PrimitiveRegistry

        primitives_module.set_rng(random.Random(7))
        wl = _pc_actor(self.registry, "c_warlock", 1)   # {1: 1}
        goblin = Actor(id="goblin", name="goblin",
                         template={"id": "t", "name": "g",
                                     "abilities": {}, "actions": []},
                         side="enemy", hp_current=20, hp_max=20,
                         ac=12, position=(1, 0), abilities={})
        state = _make_state([wl, goblin])
        state.content_registry = self.registry
        hex_action = next(a for a in wl.template["actions"]
                            if a.get("id") == "a_hex")
        chosen = {"kind": "offensive_buff", "action": hex_action,
                    "target": goblin, "actor": wl}
        pipeline.execute(chosen, state, EventBus(),
                            PrimitiveRegistry.with_defaults())
        self.assertEqual(wl.spell_slots.get(1, 0), 0)   # slot spent
        # Short rest → slot back (the whole point of Pact Magic)
        apply_short_rest(wl, state)
        self.assertEqual(wl.spell_slots.get(1, 0), 1)


if __name__ == "__main__":
    unittest.main()
