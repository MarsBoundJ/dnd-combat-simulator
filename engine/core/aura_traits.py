"""Aura traits — always-on monster emanations (Ghast Stench, etc.).

RAW (SRD 5.2.1, Ghast): "Stench. Constitution Saving Throw: DC 10, any
creature that starts its turn in a 5-foot Emanation originating from the
ghast. Failure: the target has the Poisoned condition until the start of
its next turn. Success: the target is immune to this ghast's Stench for
24 hours."

Unlike a spell aura (Spirit Guardians — created by a cast action), an aura
TRAIT is always on. This module registers each such trait as a
caster-anchored `persistent_aura` entry at combat start, so the existing
runner resolution (_resolve_persistent_aura_triggers) fires it at every
creature's turn start for free — the aura moves with the monster
(anchor='caster' reads its live position).

Stat-block shape (monster `auras`):

    auras:
      - id: t_stench
        name: Stench
        range_ft: 5
        save: { ability: constitution, dc: 10 }
        affected: enemies          # default 'enemies'
        immune_on_success: true    # 24h immunity → rest of the encounter
        on_fail:
          - primitive: apply_condition
            params: { condition_id: co_poisoned,
                      duration: until_actor_next_turn_start }

`immune_on_success` is honored in the resolver: a creature that succeeds is
recorded on the aura entry and skipped on later turns (the per-encounter
stand-in for "immune for 24 hours").

v1 scope: save-based debuff auras (Stench). No-save damage auras (e.g. a
Fire Elemental's Fire Aura) also work via this shape (omit `save`,
`on_fail` deals damage). Concentration *action* auras with a one-time
entry save (Harpy Luring Song) are NOT trait auras — they ride the
persistent_aura cast action instead.
"""
from __future__ import annotations

from engine.core.state import CombatState


def _entry_from_trait(actor, trait: dict, state: CombatState) -> dict:
    save = trait.get("save") or {}
    ability = save.get("ability")
    return {
        "caster_id": actor.id,
        "action_id": trait.get("id", "aura_trait"),
        "named_effect": trait.get("id"),
        "shape": "sphere",
        "radius_ft": int(trait.get("range_ft", 0)),
        "size_ft": 0,
        "anchor": "caster",        # moves with the monster
        "origin": None,
        "trigger_event": "target_turn_start_in_area",
        "ability": ability,        # None → no-save (always applies on_fail)
        "dc": int(save.get("dc", 0)) if ability else 0,
        "on_fail": trait.get("on_fail") or [],
        "on_success": trait.get("on_success") or [],
        "affected": trait.get("affected", "enemies"),
        "immune_on_success": bool(trait.get("immune_on_success", False)),
        "is_trait_aura": True,
        "applied_at_round": state.round,
        "chosen_slot_level": 0,
        "spell_slot_level": 0,
    }


def register(state: CombatState) -> int:
    """Register every actor's always-on aura traits as caster-anchored
    persistent_auras. Idempotent per (caster, aura id): re-registration
    skips auras already present. Returns the number registered."""
    existing = {(a.get("caster_id"), a.get("action_id"))
                for a in state.persistent_auras if a.get("is_trait_aura")}
    count = 0
    for actor in state.encounter.actors:
        for trait in (actor.template.get("auras") or []):
            key = (actor.id, trait.get("id", "aura_trait"))
            if key in existing:
                continue
            state.persistent_auras.append(_entry_from_trait(actor, trait, state))
            existing.add(key)
            count += 1
            state.event_log.append({
                "event": "aura_trait_registered",
                "caster": actor.id, "aura": trait.get("id"),
            })
    return count
