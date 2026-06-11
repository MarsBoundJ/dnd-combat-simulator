"""Draconic Sorcery — Elemental Affinity damage rider (Sorcerer subclass).

RAW (SRD 5.2.1, Draconic Sorcery L6 Elemental Affinity): "When you cast
a spell that deals damage of the type associated with your draconic
ancestry, you can add your Charisma modifier to one damage roll of that
spell." (The matching-type Resistance half is baked into the actor's
damage_resistances at PC-build time; see pc_schema.)

Modeling: a passive, strictly-beneficial rider applied directly in
_damage (like the Rage / weapon-damage-bonus riders) — there is no
decision to make, so it fires automatically whenever it applies. The
"one damage roll" clause is honored by a once-per-cast dedup flag on
state.current_attack, so a multi-target or save-for-half spell adds the
bonus a single time (to the first matching-type damage roll of the
cast), not once per target.

The actor carries the feature data on template["elemental_affinity"] =
{"element": <type>, "cha_mod": <int>}, stamped by pc_schema when
f_elemental_affinity is in features_known.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState

_CAST_FLAG = "elemental_affinity_applied"


def elemental_affinity_bonus(actor: Actor, damage_type: str,
                              state: CombatState) -> int:
    """Return the CHA-mod bonus to add to this damage roll, or 0.

    Adds the bonus exactly once per cast (dedup via state.current_attack)
    and only when the damage type matches the sorcerer's draconic element.
    Returns 0 for actors without the feature, mismatched types, an
    already-applied cast, or a non-positive modifier."""
    ea = (actor.template or {}).get("elemental_affinity")
    if not ea:
        return 0
    if str(damage_type).lower() != str(ea.get("element", "")).lower():
        return 0
    current = state.current_attack or {}
    if current.get(_CAST_FLAG):
        return 0
    bonus = int(ea.get("cha_mod", 0))
    if bonus <= 0:
        return 0
    current[_CAST_FLAG] = True
    state.event_log.append({
        "event": "elemental_affinity_bonus",
        "actor": actor.id,
        "element": ea.get("element"),
        "bonus": bonus,
    })
    return bonus
