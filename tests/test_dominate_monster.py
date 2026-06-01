"""Dominate Monster tests — SRD spell batch 2 (L8 any-creature charm).

The shared cast path lives in test_dominate_person.py; this file pins
the L8 feature's own shape.
"""
from __future__ import annotations

import unittest

from tests import _srd_helpers as H


class DominateMonsterTest(unittest.TestCase):

    def test_loads(self):
        f = H.registry().get("feature", "f_dominate_monster")
        self.assertEqual(f["spell"]["level"], 8)
        self.assertEqual(f["source"], "srd_5.2.1")
        a = H.action_template("f_dominate_monster")
        self.assertEqual(a["spell_slot_level"], 8)
        self.assertTrue(a["concentration"])
        self.assertEqual(a["pipeline"][0]["params"]["ability"], "wisdom")


if __name__ == "__main__":
    unittest.main()
