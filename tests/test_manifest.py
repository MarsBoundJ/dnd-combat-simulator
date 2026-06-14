"""Run-manifest tests (WS-F2, engine/manifest.py).

Covers the three properties the manifest exists to guarantee:

  1. **Complete** — every reproducibility input is present (engine SHA,
     content hash, rule bundle, seed, run params, and a full
     encounter-spec snapshot), including the forward-compat keys.
  2. **Deterministic** — identical inputs produce an identical manifest
     (and an identical ``manifest_id``); no wall-clock contamination.
  3. **Sensitive to what matters** — a content change changes the content
     hash (and the manifest id); a seed/dial/spec change changes the id.

Run via:
    python -m unittest tests.test_manifest
"""
from __future__ import annotations

import json
import unittest

from engine.manifest import (
    MANIFEST_VERSION, build_manifest, content_hash, manifest_id,
)
from engine.core.state import Actor, Encounter


# ---------------------------------------------------------------------------
# Lightweight content doubles (no disk / loader dependency)
# ---------------------------------------------------------------------------

class _FakeRegistry:
    """Mimics ContentRegistry's public count()/all() surface."""
    def __init__(self, content: dict):
        self._content = content

    def count(self) -> dict:
        return {etype: len(items) for etype, items in self._content.items()}

    def all(self, etype: str) -> dict:
        return dict(self._content.get(etype, {}))


def _sample_content() -> dict:
    return {
        "monster": {
            "m_goblin": {"id": "m_goblin", "name": "Goblin", "hp": 7},
            "m_orc": {"id": "m_orc", "name": "Orc", "hp": 15},
        },
        "spell": {
            "sp_fireball": {"id": "sp_fireball", "level": 3},
        },
    }


def _sample_encounter_spec() -> dict:
    return {
        "id": "enc_demo",
        "actors": [
            {"instance_id": "aria", "position": [0, 0],
             "pc": {"class": "c_wizard", "level": 5,
                    "ability_scores": {"int": 16}}},
            {"instance_id": "orc1", "template_ref": "m_orc", "position": [5, 0]},
        ],
        "environment": {"template": "open_field"},
    }


# A SHA is injected in most tests so they don't depend on a git checkout.
_SHA = "0123456789abcdef0123456789abcdef01234567"


def _manifest(**overrides):
    kwargs = dict(
        seed=42,
        content_registry=_FakeRegistry(_sample_content()),
        encounter_spec=_sample_encounter_spec(),
        optimization_dials={"pc": 3, "enemy": 1},
        encounters_remaining_today=2,
        engine_sha=_SHA,
    )
    kwargs.update(overrides)
    return build_manifest(**kwargs)


# ---------------------------------------------------------------------------
# 1. Completeness
# ---------------------------------------------------------------------------

class ManifestCompletenessTest(unittest.TestCase):

    def test_version_and_top_level_keys(self):
        m = _manifest()
        self.assertEqual(m["manifest_version"], MANIFEST_VERSION)
        for key in ("engine", "content", "rules", "run_params",
                    "encounter", "room_spec"):
            self.assertIn(key, m)

    def test_engine_section(self):
        m = _manifest()
        self.assertEqual(m["engine"]["git_sha"], _SHA)
        self.assertIn("git_dirty", m["engine"])

    def test_content_section(self):
        m = _manifest()
        self.assertTrue(m["content"]["hash"].startswith("sha256:"))
        self.assertEqual(m["content"]["counts"],
                         {"monster": 2, "spell": 1})

    def test_run_params_capture_seed_and_dials(self):
        m = _manifest()
        rp = m["run_params"]
        self.assertEqual(rp["seed"], 42)
        self.assertEqual(rp["optimization_dials"], {"pc": 3, "enemy": 1})
        self.assertEqual(rp["encounters_remaining_today"], 2)
        self.assertIn("behavior_profiles", rp)        # forward-compat key

    def test_forward_compat_fields_present_and_default_none(self):
        m = _manifest()
        self.assertIsNone(m["rules"]["rule_bundle"])
        self.assertIsNone(m["room_spec"])
        self.assertIsNone(m["run_params"]["behavior_profiles"])

    def test_forward_compat_fields_captured_when_supplied(self):
        m = _manifest(
            rule_bundle="Strict",
            room_spec={"width": 30, "height": 30, "walls": []},
            behavior_profiles={"pc": "aggressive"},
        )
        self.assertEqual(m["rules"]["rule_bundle"], "Strict")
        self.assertEqual(m["room_spec"]["width"], 30)
        self.assertEqual(m["run_params"]["behavior_profiles"], {"pc": "aggressive"})

    def test_declarative_spec_snapshot_is_faithful(self):
        m = _manifest()
        enc = m["encounter"]
        self.assertEqual(enc["snapshot_source"], "declarative_spec")
        self.assertEqual(enc["id"], "enc_demo")
        # The PCSpec `pc:` block survives verbatim.
        aria = enc["spec"]["actors"][0]
        self.assertEqual(aria["pc"]["class"], "c_wizard")
        self.assertEqual(aria["pc"]["level"], 5)

    def test_snapshot_is_a_copy_not_a_reference(self):
        spec = _sample_encounter_spec()
        m = build_manifest(seed=1, encounter_spec=spec, engine_sha=_SHA)
        spec["actors"][0]["pc"]["level"] = 99
        # Mutating the source spec after the fact must not alter the manifest.
        self.assertEqual(m["encounter"]["spec"]["actors"][0]["pc"]["level"], 5)

    def test_manifest_is_json_serializable(self):
        m = _manifest()
        # Round-trips through JSON unchanged (no tuples / non-JSON scalars).
        self.assertEqual(json.loads(json.dumps(m)), m)


# ---------------------------------------------------------------------------
# 2. Determinism
# ---------------------------------------------------------------------------

class ManifestDeterminismTest(unittest.TestCase):

    def test_identical_inputs_identical_manifest(self):
        self.assertEqual(_manifest(), _manifest())

    def test_identical_inputs_identical_id(self):
        self.assertEqual(manifest_id(_manifest()), manifest_id(_manifest()))

    def test_content_hash_independent_of_dict_order(self):
        a = {"monster": {"m_a": {"id": "m_a"}, "m_b": {"id": "m_b"}}}
        b = {"monster": {"m_b": {"id": "m_b"}, "m_a": {"id": "m_a"}}}
        self.assertEqual(content_hash(a), content_hash(b))

    def test_registry_and_plain_mapping_hash_equal(self):
        content = _sample_content()
        self.assertEqual(content_hash(content),
                         content_hash(_FakeRegistry(content)))

    def test_detected_sha_is_stable(self):
        # Real detection (no engine_sha override): str-or-None, and stable
        # across calls within one checkout.
        m1 = build_manifest(seed=1)
        m2 = build_manifest(seed=1)
        self.assertEqual(m1["engine"]["git_sha"], m2["engine"]["git_sha"])
        sha = m1["engine"]["git_sha"]
        self.assertTrue(sha is None or isinstance(sha, str))


# ---------------------------------------------------------------------------
# 3. Sensitivity — the right changes change the hash / id
# ---------------------------------------------------------------------------

class ManifestSensitivityTest(unittest.TestCase):

    def test_content_change_changes_hash(self):
        before = content_hash(_sample_content())
        changed = _sample_content()
        changed["monster"]["m_orc"]["hp"] = 16      # edit one field
        self.assertNotEqual(before, content_hash(changed))

    def test_adding_content_changes_hash(self):
        before = content_hash(_sample_content())
        more = _sample_content()
        more["monster"]["m_kobold"] = {"id": "m_kobold", "hp": 5}
        self.assertNotEqual(before, content_hash(more))

    def test_content_change_changes_manifest_id(self):
        base = _manifest()
        changed = _sample_content()
        changed["monster"]["m_orc"]["hp"] = 16
        other = _manifest(content_registry=_FakeRegistry(changed))
        self.assertNotEqual(manifest_id(base), manifest_id(other))

    def test_seed_change_changes_id(self):
        self.assertNotEqual(manifest_id(_manifest(seed=1)),
                            manifest_id(_manifest(seed=2)))

    def test_dial_change_changes_id(self):
        self.assertNotEqual(
            manifest_id(_manifest(optimization_dials={"pc": 3})),
            manifest_id(_manifest(optimization_dials={"pc": 5})))

    def test_spec_change_changes_id(self):
        spec2 = _sample_encounter_spec()
        spec2["actors"][0]["pc"]["level"] = 6
        self.assertNotEqual(manifest_id(_manifest()),
                            manifest_id(_manifest(encounter_spec=spec2)))

    def test_sha_change_changes_id(self):
        self.assertNotEqual(manifest_id(_manifest(engine_sha="a" * 40)),
                            manifest_id(_manifest(engine_sha="b" * 40)))


# ---------------------------------------------------------------------------
# Encounter-object snapshot fallback (no declarative spec available)
# ---------------------------------------------------------------------------

class EncounterObjectSnapshotTest(unittest.TestCase):

    def _encounter(self) -> Encounter:
        template = {"id": "m_orc", "name": "Orc", "source": "srd_5.2.1",
                    "combat": {"armor_class": 13}}
        orc = Actor(id="orc_1", name="Orc", template=template, side="enemy",
                    hp_current=15, hp_max=15, ac=13, position=(5, 0))
        enc = Encounter(id="enc_obj", actors=[orc])
        enc.initial_distances = {("orc_1", "hero_1"): 25}
        return enc

    def test_snapshot_from_encounter_object(self):
        m = build_manifest(seed=7, encounter=self._encounter(), engine_sha=_SHA)
        enc = m["encounter"]
        self.assertEqual(enc["snapshot_source"], "encounter_object")
        self.assertEqual(enc["id"], "enc_obj")
        actor = enc["actors"][0]
        self.assertEqual(actor["instance_id"], "orc_1")
        self.assertEqual(actor["source"], "srd_5.2.1")
        self.assertEqual(actor["position"], [5, 0])   # tuple -> list
        # Full template embedded for lossless reproduction.
        self.assertEqual(actor["template"]["id"], "m_orc")

    def test_tuple_keyed_distances_are_json_safe(self):
        m = build_manifest(seed=7, encounter=self._encounter(), engine_sha=_SHA)
        # The (id1, id2) tuple key is flattened so the manifest is JSON-safe.
        json.dumps(m)
        dists = m["encounter"]["initial_distances"]
        self.assertEqual(dists, [{"pair": ["orc_1", "hero_1"], "ft": 25}])

    def test_spec_preferred_over_object_when_both_given(self):
        m = build_manifest(seed=7, encounter_spec=_sample_encounter_spec(),
                           encounter=self._encounter(), engine_sha=_SHA)
        self.assertEqual(m["encounter"]["snapshot_source"], "declarative_spec")


if __name__ == "__main__":
    unittest.main()
