"""Shared scaffolding for SRD spell batch-2 tests.

Small builders for a registry, a spellcaster actor (with a resolvable
spell save DC), generic enemies/allies, and a CombatState — so each
per-spell test file stays focused on the spell's own behavior. Not a
test module itself (no Test* classes); imported by the per-spell files.
"""
from __future__ import annotations

from pathlib import Path

from engine.core.state import Actor, CombatState, Encounter
from engine.loader import load_content

REPO_ROOT = Path(__file__).parent.parent
CONTENT_ROOT = REPO_ROOT / "schema" / "content"
SCHEMA_ROOT = REPO_ROOT / "schema" / "definitions"

_REGISTRY = None


def registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_content(CONTENT_ROOT, validate=True,
                                   schema_root=SCHEMA_ROOT)
    return _REGISTRY


def action_template(feature_id: str) -> dict:
    """A fresh copy of a feature's action_template from the registry."""
    return dict(registry().get("feature", feature_id)["action_template"])


def _abilities(**overrides) -> dict:
    ab = {k: {"score": 10, "save": 0}
          for k in ("str", "dex", "con", "int", "wis", "cha")}
    for k, v in overrides.items():
        if isinstance(v, tuple):           # (score, save)
            ab[k] = {"score": v[0], "save": v[1]}
        else:
            ab[k] = {"score": v, "save": 0}
    return ab


def caster(*, cid="caster", ability="intelligence", score=18, pb=3,
           position=(0, 0), slots=None, hp=30) -> Actor:
    """A spellcaster whose spell save DC = 8 + pb + mod(score)."""
    abbr = ability[:3]
    ab = _abilities(**{abbr: score})
    return Actor(id=cid, name=cid,
                   template={"id": f"t_{cid}", "name": cid, "abilities": ab,
                               "cr": {"proficiency_bonus": pb}, "actions": [],
                               "spellcasting_ability": ability, "size": "medium"},
                   side="pc", hp_current=hp, hp_max=hp, ac=14, position=position,
                   speed={"walk": 30}, abilities=ab,
                   spell_slots=dict(slots or {}))


def enemy(eid="foe", *, position=(1, 0), hp=40, ac=14, size="medium",
          attack=False, **saves) -> Actor:
    """An enemy; pass e.g. wis=-5 to set the WIS save bonus to -5.
    Pass attack=True to give it a basic weapon attack (so estimate_dpr /
    control scoring sees nonzero DPR)."""
    ab = _abilities(**{k: (10, v) for k, v in saves.items()})
    actions = []
    if attack:
        actions = [{"id": "a_atk", "name": "Strike", "type": "weapon_attack",
                     "pipeline": [
                         {"primitive": "attack_roll", "params": {"bonus": 5}},
                         {"primitive": "damage",
                           "params": {"dice": "2d6", "type": "slashing"}}]}]
    return Actor(id=eid, name=eid,
                   template={"id": f"t_{eid}", "name": eid, "abilities": ab,
                               "cr": {"proficiency_bonus": 2}, "actions": actions,
                               "size": size},
                   side="enemy", hp_current=hp, hp_max=hp, ac=ac, position=position,
                   speed={"walk": 30}, abilities=ab)


def ally(aid="ally", *, position=(1, 0), hp=10, hp_max=40) -> Actor:
    return Actor(id=aid, name=aid,
                   template={"id": f"t_{aid}", "name": aid, "abilities": {},
                               "cr": {"proficiency_bonus": 2}, "actions": [],
                               "size": "medium"},
                   side="pc", hp_current=hp, hp_max=hp_max, ac=15, position=position,
                   speed={"walk": 30}, abilities={})


def state(actors) -> CombatState:
    enc = Encounter(id="t", actors=actors)
    st = CombatState(encounter=enc)
    st.turn_order = [a.id for a in actors]
    st.round = 1
    st.content_registry = registry()
    return st


def condition_ids(actor: Actor) -> list[str]:
    return [c["condition_id"] for c in actor.applied_conditions]
