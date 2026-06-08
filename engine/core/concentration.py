"""Concentration mechanic — one concentration spell at a time, ends
on damage CON-save failure, ends on new concentration cast, ends on
caster death.

Per D&D 5e RAW:
  - A creature can concentrate on only ONE concentration spell at a time.
  - Casting a new concentration spell ends the old one automatically.
  - When a concentrating creature takes damage, they must succeed on a
    Constitution save (DC = max(10, ceil(damage_taken / 2))) or lose
    concentration.
  - Incapacitation (Stunned, Paralyzed, Unconscious) ends concentration.
  - Death ends concentration.

**Scope (post-PR #34):**
  - Schema: `concentration: true` flag on actions; pipeline marks the
    caster's `Actor.concentration_on` slot at execution.
  - Auto-drop existing concentration when caster starts a new one.
  - CON save on damage taken (in _damage primitive).
  - End on caster death (via `creature_dropped` event).
  - End on caster becoming Incapacitated — Stunned, Paralyzed,
    Unconscious, Petrified, or raw Incapacitated. The hook lives in
    `_apply_condition`: after the condition's inherited entries have
    been added to `applied_conditions`, `check_incapacitation_breaks_
    concentration` scans for any incapacitating condition id and ends
    concentration if present (PR #34).
  - End-handling: scans all actors and removes active_modifiers +
    applied_conditions whose source.action_id + caster_id match.

**Deferred:**
  - "Drop concentration to cast new better spell" eHP comparison
    in the AI scoring layer. v1 relies on natural eHP competition
    between candidates (a higher-scoring concentration candidate wins
    the slot organically).
  - Concentration broken by forced movement / teleportation (uncommon).
  - Incapacitation breaking concentration via direct `incapacitated`
    flag set outside the condition path (none today — every
    incapacitating effect goes through a condition).
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState


# ============================================================================
# Public API
# ============================================================================

def apply_concentration(caster: Actor, action: dict,
                          state: CombatState) -> None:
    """Mark `caster` as concentrating on `action`. If they were already
    concentrating on something, that prior concentration ends first
    (modifiers + conditions removed across all actors).

    Logs `concentration_ended` (if dropping prior) and
    `concentration_started` events.
    """
    if caster.concentration_on is not None:
        end_concentration(caster, state, reason="new_cast_replaced")

    caster.concentration_on = {
        "action_id": action.get("id"),
        "caster_id": caster.id,
        "applied_at_round": state.round,
    }
    state.event_log.append({
        "event": "concentration_started",
        "caster": caster.id,
        "action": action.get("id"),
        "round": state.round,
    })


def end_concentration(caster: Actor, state: CombatState,
                        reason: str = "ended") -> int:
    """End `caster`'s active concentration. Scans every actor in the
    encounter and removes:
      - active_modifiers whose source.action_id + caster_id match
      - applied_conditions whose source caster_id matches (rare; only
        if the concentration spell applied conditions, e.g.,
        Hold Person → Paralyzed)

    Clears caster.concentration_on. Logs `concentration_ended` event
    with reason + count.

    No-op (and no event) if caster wasn't concentrating.
    Returns the count of removed (modifier + condition) entries.
    """
    if caster.concentration_on is None:
        return 0

    conc = caster.concentration_on
    action_id = conc.get("action_id")
    caster_id = conc.get("caster_id")
    removed = 0

    # Scan every actor for modifiers and conditions from this concentration
    for target in state.encounter.actors:
        # Remove active_modifiers from this concentration source
        before_mods = len(target.active_modifiers)
        target.active_modifiers = [
            m for m in target.active_modifiers
            if not _matches_concentration_source(m.get("source"),
                                                   action_id, caster_id)
        ]
        removed += before_mods - len(target.active_modifiers)

        # Remove applied_conditions from this concentration source.
        # Conditions track their source via source_id (the caster's id).
        # Also scan for action-id-stamped condition sources if present.
        before_conds = len(target.applied_conditions)
        kept_conds = []
        for c in target.applied_conditions:
            if (c.get("source_id") == caster_id
                    and c.get("source_action_id") == action_id):
                continue
            kept_conds.append(c)
        target.applied_conditions = kept_conds
        removed += before_conds - len(target.applied_conditions)

    # PR #43: scrub persistent auras owned by this caster + action_id
    # (Spirit Guardians-shape effects end with concentration).
    before_auras = len(state.persistent_auras)
    state.persistent_auras = [
        a for a in state.persistent_auras
        if not (a.get("caster_id") == caster_id
                and a.get("action_id") == action_id)
    ]
    removed += before_auras - len(state.persistent_auras)

    # Barrier walls owned by this concentration (Wall of Force ends when the
    # caster drops concentration). Provenance lives in wall.flags; mirrors
    # the persistent_auras scrub above.
    walls = getattr(state, "walls", None)
    if walls:
        before_walls = len(walls)
        state.walls = [
            w for w in walls
            if not (getattr(w, "flags", {}).get("caster_id") == caster_id
                    and getattr(w, "flags", {}).get("action_id") == action_id)
        ]
        removed += before_walls - len(state.walls)

    # PR #89: scrub recurring damage ticks owned by this concentration
    # (Searing Smite's burn ends when the Paladin drops concentration).
    before_ticks = len(state.recurring_damage)
    state.recurring_damage = [
        t for t in state.recurring_damage
        if not (t.get("source_id") == caster_id
                and t.get("source_action_id") == action_id)
    ]
    removed += before_ticks - len(state.recurring_damage)

    # PR #94: scrub recurring temp HP grants owned by this concentration
    # (Heroism's per-turn temp HP ends when the caster drops
    # concentration). The dual of recurring_damage cleanup. Note: the
    # target's CURRENT temp_hp is NOT scrubbed — RAW: existing temp
    # HP persists until depleted by damage or until long rest.
    before_grants = len(state.recurring_temp_hp)
    state.recurring_temp_hp = [
        t for t in state.recurring_temp_hp
        if not (t.get("source_id") == caster_id
                and t.get("source_action_id") == action_id)
    ]
    removed += before_grants - len(state.recurring_temp_hp)

    # PR #60 + PR #68: scrub spell-created environment zones whose
    # caster_id + action_id match the dropped aura. Iterates all
    # zone-type lists (magical_dark_zones, heavily_obscured_zones,
    # future types) — the matcher is generic. Zones declared
    # statically by fixtures lack these stamps and are preserved
    # untouched.
    if state.encounter is not None:
        env = state.encounter.environment or {}
        # Mirror primitives._CREATES_ZONE_TO_ENV_KEY's value set.
        # Listed here rather than imported to keep the engine.core
        # → engine.primitives import direction one-way.
        _SCRUBBABLE_ZONE_KEYS = (
            "magical_dark_zones",
            "heavily_obscured_zones",
            "silence_zones",        # PR #79: Silence spell zone
        )
        env_dirty = False
        for env_key in _SCRUBBABLE_ZONE_KEYS:
            zones = env.get(env_key) or []
            if not zones:
                continue
            before_zones = len(zones)
            kept = [
                z for z in zones
                if not (z.get("caster_id") == caster_id
                        and z.get("action_id") == action_id)
            ]
            if len(kept) != before_zones:
                env[env_key] = kept
                env_dirty = True
                removed += before_zones - len(kept)
        if env_dirty:
            state.encounter.environment = env

    # Form system: revert any active form sustained by THIS concentration
    # (e.g. Polymorph ends → the target returns to its true form). Scans
    # every actor for a top form layer whose source matches this spell.
    from engine.core import forms
    for target in state.encounter.actors:
        if not target.form_stack:
            continue
        src = (target.form_stack[-1].get("source") or {})
        if (src.get("caster_id") == caster_id
                and src.get("action_id") == action_id):
            forms.revert_form(target, state, reason="concentration_ended")

    # Summoning system: dismiss any creatures summoned BY this concentration
    # (Bigby's Hand, Animate Objects vanish when the caster's concentration
    # ends). Mirrors the walls/persistent_auras scrub — match summons whose
    # summon_concentration stamp == (this caster_id, this action_id), then
    # remove them from the encounter roster AND the turn order so they take
    # no further turns. Permanent summons (summon_concentration is None) are
    # left untouched.
    if state.encounter is not None:
        dismissed_ids = [
            a.id for a in state.encounter.actors
            if a.summon_concentration
            and a.summon_concentration.get("caster_id") == caster_id
            and a.summon_concentration.get("action_id") == action_id
        ]
        if dismissed_ids:
            dismissed = set(dismissed_ids)
            state.encounter.actors = [
                a for a in state.encounter.actors if a.id not in dismissed
            ]
            state.turn_order = [
                tid for tid in state.turn_order if tid not in dismissed
            ]
            removed += len(dismissed_ids)
            for sid in dismissed_ids:
                state.event_log.append({
                    "event": "summon_dismissed",
                    "summon": sid,
                    "caster": caster.id,
                    "action": action_id,
                    "reason": "concentration_ended",
                })

    # Stage 3: revert granted movement speeds (Fly's fly 60) owned by this
    # concentration. Restore each affected actor's prior value for the granted
    # speed type — delete the key if it had none. Mirrors the modifier scrub.
    for target in state.encounter.actors:
        grants = getattr(target, "active_speed_grants", None)
        if not grants:
            continue
        kept = []
        for g in grants:
            if (g.get("source_caster_id") == caster_id
                    and g.get("source_action_id") == action_id):
                stype = g.get("speed_type")
                prior = g.get("prior")
                if prior is None:
                    (target.speed or {}).pop(stype, None)
                else:
                    target.speed[stype] = prior
                removed += 1
            else:
                kept.append(g)
        target.active_speed_grants = kept

    caster.concentration_on = None
    state.event_log.append({
        "event": "concentration_ended",
        "caster": caster.id,
        "action": action_id,
        "reason": reason,
        "removed_count": removed,
    })
    return removed


# ============================================================================
# Incapacitation → end concentration (RAW: PHB 2024 p.243)
# ============================================================================

# Per RAW: "If a creature is Incapacitated, it can't concentrate."
# Stunned / Paralyzed / Unconscious / Petrified all include "the
# creature is Incapacitated" in their RAW text and thus end
# concentration. Frightened / Charmed / Poisoned / etc. do NOT.
#
# We list both the parent condition (`co_incapacitated`) AND each
# child that inherits from it, because the inheritance logic in
# `_instantiate_condition_effects` populates `applied_conditions`
# with BOTH ids — a check on the child alone would still match, but
# listing them explicitly makes the intent visible without requiring
# a registry lookup at break-time.
INCAPACITATING_CONDITIONS = frozenset({
    "co_incapacitated",
    "co_stunned",
    "co_paralyzed",
    "co_unconscious",
    "co_petrified",
})


def has_incapacitating_condition(target: Actor) -> bool:
    """True if `target` currently has any condition that makes them
    Incapacitated per RAW. Inspects the `applied_conditions` list
    (already populated transitively by `_instantiate_condition_effects`
    for inherited conditions)."""
    for c in target.applied_conditions:
        if c.get("condition_id") in INCAPACITATING_CONDITIONS:
            return True
    return False


def check_incapacitation_breaks_concentration(target: Actor,
                                                  state: CombatState) -> bool:
    """If `target` is concentrating AND now has any incapacitating
    condition, end concentration with reason='incapacitated'. Returns
    True if concentration was ended, False otherwise (not concentrating
    OR not incapacitated).

    Intended to be called immediately after a condition is applied —
    `_apply_condition` in primitives.py is the canonical caller. It's
    safe to call when target isn't concentrating (no-op).
    """
    if target.concentration_on is None:
        return False
    if not has_incapacitating_condition(target):
        return False
    end_concentration(target, state, reason="incapacitated")
    return True


def attempt_concentration_save(target: Actor, damage_taken: int,
                                  state: CombatState,
                                  rng: random.Random) -> bool:
    """Roll a CON save for `target` against DC = max(10, ⌈damage_taken/2⌉)
    per RAW. On failure, end_concentration is called.

    Returns True if concentration was maintained (no save needed OR save
    passed), False if concentration was dropped (save failed).

    No-op (returns True) if target wasn't concentrating.
    """
    if target.concentration_on is None:
        return True
    if damage_taken <= 0:
        return True   # 0 damage doesn't trigger the save

    dc = max(10, (damage_taken + 1) // 2)   # ceil(damage / 2)
    con_save = (target.abilities.get("con") or {}).get("save", 0)
    d20 = rng.randint(1, 20)
    # PR #95: Halfling Lucky applies to the CON concentration save
    # (RAW: Lucky fires on saving throws). No-op for non-Halflings.
    # Critically important for Halfling spellcasters — losing
    # concentration on a key spell to a nat-1 hits hard, and Lucky
    # is the one trait that lets them re-roll out of it.
    from engine.core.racial_traits import lucky_d20
    d20, _rerolled = lucky_d20(rng, d20, target)
    total = d20 + con_save
    outcome = "success" if total >= dc else "fail"

    state.event_log.append({
        "event": "concentration_save",
        "caster": target.id,
        "action": target.concentration_on.get("action_id"),
        "dc": dc,
        "damage_taken": damage_taken,
        "d20": d20,
        "total": total,
        "outcome": outcome,
    })

    if outcome == "fail":
        end_concentration(target, state, reason="failed_con_save")
        return False
    return True


# ============================================================================
# Helpers
# ============================================================================

def _matches_concentration_source(source: dict | None,
                                    action_id: str | None,
                                    caster_id: str | None) -> bool:
    """Does this modifier's source tag match the concentration spell?"""
    if not source:
        return False
    if source.get("caster_id") != caster_id:
        return False
    if source.get("action_id") != action_id:
        return False
    return True
