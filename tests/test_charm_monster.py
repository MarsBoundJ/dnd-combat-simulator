"""Charm Monster tests — SRD spell batch 3 (L4 any-creature charm).

The shared cast path lives in test_charm_person.py; this file pins the
L4 feature's own shape.
"""
from __future__ import annotations

import unittest

from tests import _srd_helpers as H


class CharmMonsterTest(unittest.TestCase):

    def test_loads(self):
        f = H.registry().get("feature", "f_charm_monster")
        self.assertEqual(f["spell"]["level"], 4)
        self.assertEqual(f["source"], "srd_5.2.1")
        a = H.action_template("f_charm_monster")
        self.assertEqual(a["spell_slot_level"], 4)
        self.assertEqual(a["pipeline"][0]["params"]["ability"], "wisdom")


if __name__ == "__main__":
    unittest.main()
