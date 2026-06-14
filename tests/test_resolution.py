"""Content-resolution core tests (WS-I1, engine/resolution.py).

Covers the five behaviours the resolver promises: an exact hit (by id and
by name), an alias hit (curated, beats fuzzy name matching), an ambiguous
result (>1 entity shares a name), an unmapped result carrying a structured
review reason, and case/whitespace normalization. Plus provenance
(``source``) passthrough and the alias-target-not-loaded edge.

Run via:
    python -m unittest tests.test_resolution
"""
from __future__ import annotations

import unittest

from engine.resolution import (
    MatchClass, Resolution, AliasTable, ContentResolver, resolve,
    normalize_ref, REVIEW_REASONS,
)


# A plain {type: {id: entity}} mapping doubles for a ContentRegistry —
# the resolver accepts either (read-only count()/all() or Mapping).
def _registry() -> dict:
    return {
        "monster": {
            "m_orc": {"id": "m_orc", "name": "Orc", "source": "srd_5.2.1"},
            "m_goblin": {"id": "m_goblin", "name": "Goblin", "source": "srd_5.2.1"},
            # Two distinct ids sharing a display name -> ambiguous.
            "m_giant_spider": {"id": "m_giant_spider", "name": "Giant Spider",
                               "source": "srd_5.2.1"},
            "m_giant_spider_variant": {"id": "m_giant_spider_variant",
                                       "name": "Giant Spider",
                                       "source": "mm_2024"},
        },
        "spell": {
            "sp_fire_bolt": {"id": "sp_fire_bolt", "name": "Fire Bolt",
                             "source": "srd_5.2.1"},
        },
    }


class NormalizationTest(unittest.TestCase):
    def test_case_whitespace_separators(self):
        for raw in ("Fire Bolt", "fire bolt", "  FIRE   BOLT  ",
                    "fire_bolt", "FIRE-BOLT"):
            self.assertEqual(normalize_ref(raw), "fire bolt")

    def test_punctuation_dropped(self):
        self.assertEqual(normalize_ref("Beholder's"), "beholders")
        self.assertEqual(normalize_ref("Mordenkainen's Sword."), "mordenkainens sword")

    def test_empty_like(self):
        self.assertEqual(normalize_ref("   "), "")
        self.assertEqual(normalize_ref(""), "")


class ExactHitTest(unittest.TestCase):
    def test_exact_by_canonical_id(self):
        r = resolve("m_orc", "monster", _registry())
        self.assertEqual(r.match_class, MatchClass.EXACT)
        self.assertEqual(r.resolved_id, "m_orc")
        self.assertTrue(r.resolved)
        self.assertTrue(r.in_registry)

    def test_exact_by_name(self):
        r = resolve("Orc", "monster", _registry())
        self.assertEqual(r.match_class, MatchClass.EXACT)
        self.assertEqual(r.resolved_id, "m_orc")
        self.assertTrue(r.resolved)

    def test_exact_by_name_case_insensitive(self):
        r = resolve("  fire   bolt ", "spell", _registry())
        self.assertEqual(r.match_class, MatchClass.EXACT)
        self.assertEqual(r.resolved_id, "sp_fire_bolt")

    def test_exact_by_id_in_different_case(self):
        # An id passed with different case/separators still resolves exact.
        r = resolve("M_ORC", "monster", _registry())
        self.assertEqual(r.match_class, MatchClass.EXACT)
        self.assertEqual(r.resolved_id, "m_orc")

    def test_provenance_passthrough(self):
        r = resolve("Orc", "monster", _registry())
        self.assertEqual(r.source, "srd_5.2.1")


class AliasHitTest(unittest.TestCase):
    def _aliased(self) -> ContentResolver:
        table = AliasTable()
        table.add("monster", "m_orc", ["Greenskin", "War Orc"])
        return ContentResolver(_registry(), table)

    def test_alias_resolves_to_canonical_id(self):
        r = self._aliased().resolve("Greenskin", "monster")
        self.assertEqual(r.match_class, MatchClass.ALIASED)
        self.assertEqual(r.resolved_id, "m_orc")
        self.assertTrue(r.resolved)
        self.assertTrue(r.in_registry)
        self.assertEqual(r.source, "srd_5.2.1")

    def test_alias_is_case_insensitive(self):
        r = self._aliased().resolve("  war ORC ", "monster")
        self.assertEqual(r.match_class, MatchClass.ALIASED)
        self.assertEqual(r.resolved_id, "m_orc")

    def test_alias_beats_name_match(self):
        # Alias "Goblin" -> m_orc must win over the real m_goblin name.
        table = AliasTable()
        table.add_alias("monster", "Goblin", "m_orc")
        r = ContentResolver(_registry(), table).resolve("Goblin", "monster")
        self.assertEqual(r.match_class, MatchClass.ALIASED)
        self.assertEqual(r.resolved_id, "m_orc")

    def test_alias_table_starts_empty(self):
        self.assertEqual(len(AliasTable()), 0)

    def test_from_id_aliases_builder(self):
        table = AliasTable.from_id_aliases({
            "monster": {"m_orc": ["Eye Tyrant Test", "Orcish Brute"]},
        })
        self.assertEqual(table.get("monster", "orcish brute"), "m_orc")
        self.assertEqual(table.aliases_for("monster", "m_orc"),
                         ["eye tyrant test", "orcish brute"])

    def test_conflicting_alias_raises(self):
        table = AliasTable()
        table.add_alias("monster", "Brute", "m_orc")
        with self.assertRaises(ValueError):
            table.add_alias("monster", "brute", "m_goblin")  # remap -> error

    def test_alias_target_not_loaded(self):
        table = AliasTable()
        table.add_alias("monster", "Eye Tyrant", "m_beholder")  # not in registry
        r = ContentResolver(_registry(), table).resolve("Eye Tyrant", "monster")
        self.assertEqual(r.match_class, MatchClass.ALIASED)
        self.assertEqual(r.resolved_id, "m_beholder")
        self.assertTrue(r.resolved)            # the mapping is known...
        self.assertFalse(r.in_registry)        # ...but the content isn't loaded
        self.assertIsNone(r.source)
        self.assertEqual(r.reason, "alias_target_not_loaded")
        self.assertIn(r.reason, REVIEW_REASONS)


class AmbiguousTest(unittest.TestCase):
    def test_ambiguous_name_returns_sorted_candidates(self):
        r = resolve("Giant Spider", "monster", _registry())
        self.assertEqual(r.match_class, MatchClass.AMBIGUOUS)
        self.assertFalse(r.resolved)
        self.assertIsNone(r.resolved_id)
        self.assertEqual(r.candidates,
                         ("m_giant_spider", "m_giant_spider_variant"))
        self.assertEqual(r.reason, "ambiguous_name")
        self.assertIn(r.reason, REVIEW_REASONS)


class UnmappedTest(unittest.TestCase):
    def test_no_match_has_reason(self):
        r = resolve("Tarrasque", "monster", _registry())
        self.assertEqual(r.match_class, MatchClass.UNMAPPED)
        self.assertFalse(r.resolved)
        self.assertIsNone(r.resolved_id)
        self.assertEqual(r.reason, "no_match")
        self.assertIn(r.reason, REVIEW_REASONS)

    def test_empty_reference(self):
        r = resolve("   ", "monster", _registry())
        self.assertEqual(r.match_class, MatchClass.UNMAPPED)
        self.assertEqual(r.reason, "empty_reference")

    def test_unknown_entity_type(self):
        r = resolve("Anything", "widget", _registry())
        self.assertEqual(r.match_class, MatchClass.UNMAPPED)
        self.assertEqual(r.reason, "unknown_entity_type")


class RegistryAdapterTest(unittest.TestCase):
    """The resolver accepts a ContentRegistry-like object (count()/all())."""

    class _FakeRegistry:
        def __init__(self, content):
            self._c = content
        def count(self):
            return {k: len(v) for k, v in self._c.items()}
        def all(self, etype):
            return dict(self._c.get(etype, {}))

    def test_resolves_against_registry_object(self):
        reg = self._FakeRegistry(_registry())
        r = resolve("Orc", "monster", reg)
        self.assertEqual(r.resolved_id, "m_orc")

    def test_unknown_type_on_registry_object(self):
        reg = self._FakeRegistry(_registry())
        r = resolve("x", "feat", reg)
        self.assertEqual(r.reason, "unknown_entity_type")

    def test_bad_registry_type_raises(self):
        with self.assertRaises(TypeError):
            resolve("Orc", "monster", object())


class ResolutionShapeTest(unittest.TestCase):
    def test_result_is_frozen_dataclass(self):
        r = resolve("Orc", "monster", _registry())
        self.assertIsInstance(r, Resolution)
        with self.assertRaises(Exception):
            r.resolved_id = "x"   # frozen


if __name__ == "__main__":
    unittest.main()
