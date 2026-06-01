"""Magic Weapon tests — SRD spell batch 3 (self weapon +1 attack/damage)."""
from __future__ import annotations

import unittest

from engine.core import modifiers, pipeline
from engine.core.events import EventBus
from engine.primitives import PrimitiveRegistry
from tests import _srd_helpers as H


class MagicWeaponTest(unittest.TestCase):

    def test_loads(self):
        a = H.action_template("f_magic_weapon")
        self.assertEqual(a["slot"], "bonus_action")
        self.assertTrue(a["concentration"])
        prims = {s["primitive"] for s in a["pipeline"]}
        self.assertEqual(prims, {"attack_modifier", "weapon_damage_bonus"})

    def test_cast_grants_attack_and_damage_bonus(self):
        wiz = H.caster(cid="wiz", ability="intelligence", slots={2: 1})
        foe = H.enemy(eid="foe")
        st = H.state([wiz, foe])
        chosen = {"kind": "defensive_buff", "action": H.action_template("f_magic_weapon"),
                    "target": wiz, "actor": wiz}
        pipeline.execute(chosen, st, EventBus(), PrimitiveRegistry.with_defaults())
        # +1 to the caster's own attack rolls
        am = modifiers.query_attack_modifiers(wiz, foe, st)
        self.assertEqual(am.attack_bonus_modifier, 1)
        # +1 weapon damage rider registered
        wdb = modifiers.query_weapon_damage_bonus(wiz, {"kind": "melee"}, st)
        self.assertEqual(wdb, 1)
        self.assertEqual(wiz.concentration_on["action_id"], "a_magic_weapon")


if __name__ == "__main__":
    unittest.main()
