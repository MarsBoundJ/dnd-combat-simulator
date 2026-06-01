"""Form system — mechanical form replacement (Agent Identity & Lifecycle,
Phase 1).

Wild Shape, Polymorph, True Polymorph, a dragon's Change Shape, and
lycanthrope forms all swap which stat block is "live" on an Actor. The
implementation rests on the fact that the engine reads the Actor's
denormalized live fields (hp_current/max, ac, speed, abilities, size,
creature_type, template), not the raw base template — so a form swap is:

    snapshot the live fields → overwrite them per a merge policy →
    restore the snapshot on revert.

The active form's HP IS hp_current/hp_max while transformed (base HP is
saved in the snapshot), so every existing damage / temp-HP /
concentration path works unchanged. The only engine hook the rest of the
codebase needs is in _damage: at 0 HP, if transformed, REVERT instead of
die (see primitives._damage).

Merge policy = where RAW fidelity lives (what the form replaces vs. what
the base keeps). See docs/architecture/form-identity-system.md.

Phase-1 scope: the core swap + Wild Shape / Polymorph policies, validated
directly. Content (Druid Wild Shape = Phase 3; Polymorph spell = Phase 4)
rides this later. `keep_features` / `can_cast` are recorded on the policy
for those phases but not yet enforced (a transformed actor's template is
swapped wholesale in Phase 1).
"""
from __future__ import annotations

import copy

from engine.core.state import Actor, CombatState

# Merge policies: what the assumed form replaces vs. what the base keeps.
#   physical: replace → form's STR/DEX/CON, AC, speed, size, attacks
#   mental:   keep → base INT/WIS/CHA survive (Wild Shape); replace → form's
#   carry_overflow: on revert at 0 HP, does excess damage carry to the
#     restored base HP? (Polymorph: yes; Wild Shape: no)
#   keep_features / can_cast: recorded for Phase 3+ (not enforced yet)
MERGE_POLICIES: dict[str, dict] = {
    "wild_shape": {
        "physical": "replace", "mental": "keep",
        "carry_overflow": False, "keep_features": True, "can_cast": False,
    },
    "polymorph": {
        "physical": "replace", "mental": "replace",
        "carry_overflow": True, "keep_features": False, "can_cast": False,
    },
    "change_shape": {   # dragon/doppelganger style: keep mental, same HP
        "physical": "replace", "mental": "keep",
        "carry_overflow": False, "keep_features": True, "can_cast": True,
    },
}

# Fields snapshotted from the live Actor when the first form is assumed.
_SNAPSHOT_FIELDS = ("hp_current", "hp_max", "ac", "size", "creature_type")


def is_transformed(actor: Actor) -> bool:
    return bool(actor.form_stack)


def active_form_id(actor: Actor) -> str | None:
    return actor.form_stack[-1]["form_id"] if actor.form_stack else None


def _snapshot(actor: Actor) -> dict:
    snap = {f: getattr(actor, f) for f in _SNAPSHOT_FIELDS}
    snap["speed"] = dict(actor.speed)
    snap["abilities"] = copy.deepcopy(actor.abilities)
    snap["template"] = actor.template   # ref is fine; we restore the ref
    return snap


def _apply_form(actor: Actor, form_template: dict, policy: dict) -> None:
    combat = form_template.get("combat") or {}
    # HP: the form's average HP becomes the live pool (true HP is in snap).
    form_hp = int((combat.get("hit_points") or {}).get("average", actor.hp_max))
    actor.hp_current = form_hp
    actor.hp_max = form_hp
    actor.ac = int(combat.get("armor_class", actor.ac))
    if combat.get("speed"):
        actor.speed = dict(combat["speed"])
    if form_template.get("size"):
        actor.size = form_template["size"]
    if form_template.get("creature_type"):
        actor.creature_type = form_template["creature_type"]
    # Abilities: physical from the form; mental kept or replaced per policy.
    form_abils = form_template.get("abilities") or {}
    base_abils = actor.abilities
    if policy["mental"] == "keep":
        merged = {}
        for k in ("str", "dex", "con"):
            merged[k] = dict(form_abils.get(k, base_abils.get(k, {})))
        for k in ("int", "wis", "cha"):
            merged[k] = dict(base_abils.get(k, form_abils.get(k, {})))
        actor.abilities = merged
    else:
        actor.abilities = copy.deepcopy(form_abils)
    # Swap the live template (actions / traits / resistances / senses).
    # Phase 3 will layer keep_features back on for Wild Shape; for now the
    # form's stat block is adopted wholesale.
    actor.template = form_template


def assume_form(actor: Actor, form_template: dict, policy_name: str,
                  source: dict, state: CombatState) -> None:
    """Transform `actor` into `form_template` under the named merge policy.
    Snapshots the true form on the first layer; overwrites live fields;
    pushes a form layer."""
    policy = MERGE_POLICIES.get(policy_name)
    if policy is None:
        raise ValueError(f"unknown merge policy: {policy_name!r}")
    if not actor.form_stack:
        actor.base_form_snapshot = _snapshot(actor)
    _apply_form(actor, form_template, policy)
    actor.form_stack.append({
        "form_id": form_template.get("id", "unknown_form"),
        "policy": policy_name,
        "source": source,
        "reversion": source.get("reversion", ["hp_zero"]),
    })
    state.event_log.append({
        "event": "form_assumed", "actor": actor.id,
        "form_id": form_template.get("id"), "policy": policy_name,
        "form_hp": actor.hp_current,
    })


def revert_form(actor: Actor, state: CombatState, *, reason: str,
                  overflow: int = 0) -> None:
    """Pop the top form layer. If the actor is back to its true form,
    restore the snapshot. `overflow` is damage beyond the form's HP pool;
    for carry_overflow policies (Polymorph) it subtracts from the
    restored true HP, which can drop the creature to 0 (then it dies)."""
    if not actor.form_stack:
        return
    layer = actor.form_stack.pop()
    policy = MERGE_POLICIES.get(layer["policy"], {})
    if actor.form_stack:
        # Nested form: revert to the layer beneath. (Rare; re-derive from
        # the now-top layer's template is out of Phase-1 scope — log it.)
        state.event_log.append({
            "event": "form_reverted_nested", "actor": actor.id,
            "to_form_id": active_form_id(actor), "reason": reason,
        })
        return
    snap = actor.base_form_snapshot or {}
    for f in _SNAPSHOT_FIELDS:
        if f in snap and f not in ("hp_current",):
            setattr(actor, f, snap[f])
    if "speed" in snap:
        actor.speed = dict(snap["speed"])
    if "abilities" in snap:
        actor.abilities = copy.deepcopy(snap["abilities"])
    if "template" in snap:
        actor.template = snap["template"]
    base_hp = int(snap.get("hp_current", actor.hp_current))
    if policy.get("carry_overflow") and overflow > 0:
        actor.hp_current = max(0, base_hp - overflow)
    else:
        actor.hp_current = base_hp
    actor.base_form_snapshot = None
    state.event_log.append({
        "event": "form_reverted", "actor": actor.id,
        "reason": reason, "restored_hp": actor.hp_current,
        "overflow": overflow,
    })
    if actor.hp_current == 0:
        actor.is_dead = True
        if actor.concentration_on is not None:
            from engine.core.concentration import end_concentration
            end_concentration(actor, state, reason="form_revert_death")
