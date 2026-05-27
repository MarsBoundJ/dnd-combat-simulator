"""Weapon Mastery properties (PR #54).

5e 2024 PHB introduces Weapon Mastery as a class feature. Each
character with the feature "knows" a number of mastery properties
(scales by class level). When they wield a weapon whose intrinsic
mastery property is one they know, the property fires.

v1 ships all eight properties:

  - **Vex** — On a hit, you have advantage on your next attack roll
    against this target before the end of your next turn.
  - **Sap** — On a hit, the target has disadvantage on its next
    attack roll before the end of its next turn.
  - **Topple** — On a hit, the target makes a CON save (DC 8 +
    ability mod + proficiency bonus). On fail, target is knocked
    Prone.
  - **Graze** — On a MISS with this weapon, deal ability-modifier
    damage of the weapon's damage type. (Heavy-melee-only per RAW;
    v1 does not enforce the Heavy gate — we trust the weapon spec.)
  - **Nick** (PR #57) — When you make the extra attack of the Light
    property as part of the Attack action, you can make that extra
    attack as part of the same action (instead of as a Bonus
    Action). Effect lives at template-build time
    (pc_schema._build_weapon_action sets slot='free' on the off-hand
    when Nick is active for the actor); no attack-resolution
    effect, so the apply_mastery_effects dispatch skips Nick via
    the if-elif chain.
  - **Cleave** (PR #58) — On a hit with a melee Heavy weapon, can
    make one extra melee attack with the same weapon against a
    different creature within 5 ft of the original target AND
    within the attacker's reach. Once per turn (gated via
    `actor._cleave_fired_this_turn` attribute, cleared by
    `reset_turn`). v1 doesn't enforce the Heavy gate — trusts
    the weapon spec.
  - **Push** (PR #58) — On a hit, push the target up to 10 ft
    (2 squares) straight away from the attacker. v1 doesn't gate
    on target size (RAW: Large or smaller); a `size` field on
    Actor + the gate are tracked as a future refinement.
    Forced-movement helper lives in `engine.core.geometry.push_creature`.
  - **Slow** (PR #58) — On a hit AND damage dealt, reduce target's
    walking speed by 10 ft until the start of the attacker's next
    turn. RAW: "doesn't exceed 10 ft if hit multiple times" —
    v1 enforces this by no-op-ing if the target already has a
    Slow modifier (any source). Implemented via direct
    `target.speed["walk"]` mutation + a `_slow_data` runtime
    record. Expiry is handled by the runner at the slow-applier's
    turn_start (`_expire_slow_from_source(actor_id, state)`).

**Wiring conventions:**
  - Weapon specs declare `mastery: <id>` (intrinsic to the weapon).
  - Actor.weapon_masteries lists which properties the actor *knows*
    (gated by class feature).
  - `pc_schema._build_weapon_action` bakes a `mastery` sub-dict into
    the `attack_roll` params with `{id, ability_mod, damage_type,
    save_dc}` — everything the dispatch helper needs at runtime
    without re-reading the actor template.
  - `primitives._attack_roll` calls `apply_mastery_effects(...)` after
    the attack state is final (hit / crit / miss). The helper checks
    whether the actor knows the mastery and dispatches to the
    per-property function.

**Deferred refinements (post-v1 tightenings, not new masteries):**
  - Heavy-weapon gate on Cleave + Graze (RAW restricts these to
    Heavy melee weapons; v1 trusts the weapon spec).
  - Size gate on Push (RAW: Large or smaller targets). Needs an
    `Actor.size` field that doesn't exist yet.
  - Forced-movement collision handling (Push currently moves the
    target whether or not the destination is occupied; v1 trusts
    open-battlefield environments).
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState


class _NullEventBus:
    """No-op stub for sub-primitive bus.emit calls when no real bus
    is available (e.g., direct test invocation). Mirrors EventBus's
    emit(name, payload) signature.
    """
    def emit(self, name: str, payload: dict) -> None:
        pass


# Known mastery property ids. Validated against this set when reading
# weapon specs and pc-schema declarations.
KNOWN_MASTERIES: frozenset[str] = frozenset({
    "vex", "sap", "topple", "graze",
    "nick",      # PR #57 — slot-level effect (free off-hand attack)
    "cleave",    # PR #58 — on-hit sub-attack
    "push",      # PR #58 — on-hit forced movement
    "slow",      # PR #58 — on-hit speed reduction
})


# Future masteries (declared deferred so we can list them in errors
# without making them "unknown"). Empty after PR #58 ships all eight
# v1 properties; kept as a frozenset so future RAW additions can
# slot in cleanly without changing the validator branching.
DEFERRED_MASTERIES: frozenset[str] = frozenset()


def validate_mastery(name: str) -> str:
    """Return the lowercase id if known; raise ValueError otherwise.
    Surfaces deferred masteries with a clearer message so authors know
    *why* their valid-looking choice doesn't work yet.
    """
    n = str(name).strip().lower()
    if n in KNOWN_MASTERIES:
        return n
    if n in DEFERRED_MASTERIES:
        raise ValueError(
            f"Weapon mastery {name!r} is recognized but not yet "
            f"implemented (deferred to a future PR). Known v1 "
            f"masteries: {sorted(KNOWN_MASTERIES)}."
        )
    raise ValueError(
        f"Unknown weapon mastery {name!r}. Known: "
        f"{sorted(KNOWN_MASTERIES)}."
    )


def validate_mastery_list(value) -> list[str]:
    """Validate + normalize a list of mastery ids (PC spec field).
    Empty / None returns []. Deduplicates while preserving order.
    """
    if value is None or value == "":
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError(
            f"weapon_masteries must be a list, got {type(value).__name__}"
        )
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        n = validate_mastery(str(raw))
        if n not in seen:
            out.append(n)
            seen.add(n)
    return out


def actor_knows_mastery(actor: Actor, mastery_id: str) -> bool:
    """True if `actor` has `mastery_id` in their declared weapon_masteries
    list. Handles the None / empty cases cleanly.
    """
    if not mastery_id:
        return False
    masteries = getattr(actor, "weapon_masteries", None) or []
    return mastery_id in masteries


# ============================================================================
# Per-property implementations
# ============================================================================

def _mastery_vex(actor: Actor, target: Actor, state: CombatState) -> None:
    """Vex: actor has advantage on next attack roll against THIS target,
    before the end of actor's next turn.

    Implementation: register an advantage_for_self attack_modifier on
    the actor with an `applies_to` matcher tied to target.id, and
    lifetime `until_actor_next_turn_end`. The `per_owner_attack`
    lifetime would expire it after any swing; we want it to expire
    only after a swing against THIS target OR the turn ends.

    v1 simplification: use `per_owner_attack` lifetime. This means
    Vex expires after the actor's NEXT attack regardless of target.
    Slightly less accurate than RAW (RAW: only expires if next attack
    is against the same target), but practically equivalent for AI
    that single-targets sequentially. Tracked as a future
    target-specific-lifetime refinement.
    """
    entry = {
        "primitive": "attack_modifier",
        "params": {
            "when": "attacker_is_self",
            "modifier": "advantage_for_self",
        },
        "lifetime": "per_owner_attack",
        "source": {
            "type": "weapon_mastery",
            "id": "vex",
            "source_creature_id": actor.id,
            "target_creature_id": target.id,
        },
        "applied_at_round": state.round,
        "owner_id": actor.id,
    }
    actor.active_modifiers.append(entry)
    state.event_log.append({
        "event": "weapon_mastery_applied",
        "mastery": "vex",
        "actor": actor.id,
        "target": target.id,
    })


def _mastery_sap(actor: Actor, target: Actor, state: CombatState) -> None:
    """Sap: target has disadvantage on its next attack roll before the
    end of target's next turn.

    Implementation: register a disadvantage_for_self attack_modifier
    on the target with `when: attacker_is_self` so it fires only
    when the target is the attacker. Lifetime `per_owner_attack`
    (consumed after target's next swing).
    """
    entry = {
        "primitive": "attack_modifier",
        "params": {
            "when": "attacker_is_self",
            "modifier": "disadvantage_for_self",
        },
        "lifetime": "per_owner_attack",
        "source": {
            "type": "weapon_mastery",
            "id": "sap",
            "source_creature_id": actor.id,
        },
        "applied_at_round": state.round,
        "owner_id": target.id,
    }
    target.active_modifiers.append(entry)
    state.event_log.append({
        "event": "weapon_mastery_applied",
        "mastery": "sap",
        "actor": actor.id,
        "target": target.id,
    })


def _mastery_topple(actor: Actor, target: Actor, state: CombatState,
                       params: dict) -> None:
    """Topple: target makes CON save vs DC (8 + ability_mod + PB).
    On fail, target falls Prone.

    params must include `save_dc` (computed at build time by
    `pc_schema._build_weapon_action`).
    """
    import engine.primitives as primitives_module
    rng = primitives_module._rng
    dc = int(params.get("save_dc", 13))
    save_mod = int((target.abilities.get("con") or {}).get("save", 0))
    d20 = rng.randint(1, 20)
    save_total = d20 + save_mod
    saved = save_total >= dc

    state.event_log.append({
        "event": "weapon_mastery_save",
        "mastery": "topple",
        "actor": actor.id,
        "target": target.id,
        "save_ability": "con",
        "d20": d20,
        "save_mod": save_mod,
        "total": save_total,
        "dc": dc,
        "outcome": "saved" if saved else "failed",
    })

    if saved:
        return

    # Apply Prone via the standard apply_condition flow (so the
    # condition's modifiers wire up correctly).
    application = {
        "condition_id": "co_prone",
        "source_id": actor.id,
        "applied_at_round": state.round,
        "duration": None,
    }
    target.applied_conditions.append(application)
    state.event_log.append({
        "event": "condition_applied",
        "target": target.id,
        "condition": "co_prone",
        "source": actor.id,
        "via": "weapon_mastery_topple",
    })
    # Instantiate the condition's modifier effects so they actually
    # apply at attack-roll time.
    from engine.primitives import _instantiate_condition_effects
    _instantiate_condition_effects(target, application, state)


def _mastery_cleave(actor: Actor, target: Actor, state: CombatState,
                       params: dict, bus=None) -> None:
    """Cleave: on hit with a melee Heavy weapon, make one extra melee
    attack with the same weapon against a different creature within
    5 ft of the original target AND within the attacker's reach.
    Once per turn.

    Implementation:
      - Per-turn gate via `actor._cleave_fired_this_turn` attribute
        (cleared by `reset_turn`)
      - Find candidate: a living enemy that is (a) within 5 ft of
        the original target, (b) within actor's reach for the
        triggering weapon, (c) not the original target
      - Fire a sub-attack via the existing attack pipeline against
        the second target. The attack uses the same weapon's
        attack/damage params (cleaner than re-resolving the entire
        weapon action — we mimic the multiattack sub-action pattern).

    v1 doesn't enforce the Heavy gate (trusts the weapon spec). If
    no candidate is found, logs cleave_no_target and returns cleanly.
    """
    # Per-turn dedup
    if getattr(actor, "_cleave_fired_this_turn", False):
        state.event_log.append({
            "event": "weapon_mastery_skipped",
            "mastery": "cleave",
            "actor": actor.id,
            "reason": "already_fired_this_turn",
        })
        return

    # Find candidate: enemy within 5 ft of the original target AND
    # within the attacker's reach. The "5 ft between primary and
    # second target" is a fixed RAW distance (does not scale with
    # the attacker's reach). The attacker-reach constraint reads
    # from the mastery params (PR #66: passed through from the
    # weapon spec at build time). Reach weapons (glaive / halberd
    # / pike at 10 ft) can Cleave to a second target up to 10 ft
    # from the attacker, even if it's > 5 ft from the primary's
    # actual hex (as long as the second target IS within 5 ft of
    # primary).
    from engine.core.geometry import distance_ft
    reach_ft = int(params.get("reach_ft", 5))
    candidates = [
        a for a in state.encounter.actors
        if a.id != target.id
        and a.id != actor.id
        and a.side != actor.side
        and a.is_alive()
        and distance_ft(target.position, a.position) <= 5
        and distance_ft(actor.position, a.position) <= reach_ft
    ]
    if not candidates:
        state.event_log.append({
            "event": "weapon_mastery_skipped",
            "mastery": "cleave",
            "actor": actor.id,
            "reason": "no_second_target",
        })
        return

    second_target = candidates[0]    # deterministic: first in actor order
    actor._cleave_fired_this_turn = True
    state.event_log.append({
        "event": "weapon_mastery_applied",
        "mastery": "cleave",
        "actor": actor.id,
        "primary_target": target.id,
        "second_target": second_target.id,
    })

    # Fire a sub-attack against the second target using the same
    # weapon's attack/damage params. We mimic the multiattack sub-
    # action pattern: swap state.current_attack target, invoke an
    # attack_roll + damage step, restore.
    #
    # Build minimal sub-pipeline from the mastery params (which carry
    # the weapon's ability_mod + damage_type + save_dc). We need the
    # weapon's dice + attack bonus — currently not in mastery params.
    # v1 simplification: synthesize a basic attack using the actor's
    # known attack_bonus and a heuristic damage estimate.
    #
    # Actually cleaner: scan the actor's template.actions for the
    # weapon action that was just fired and re-use its pipeline.
    # We don't currently track WHICH action fired, but we can find
    # the highest-DPR melee weapon attack as a proxy.
    weapon_action = _find_attacker_weapon_for_cleave(actor)
    if weapon_action is None:
        state.event_log.append({
            "event": "weapon_mastery_skipped",
            "mastery": "cleave",
            "actor": actor.id,
            "reason": "no_weapon_action_found",
        })
        return

    saved_target = state.current_attack["target"]
    saved_state = state.current_attack.get("state")
    try:
        state.current_attack["target"] = second_target
        # Reset attack state so the sub-attack is rolled fresh
        state.current_attack["state"] = None
        from engine.primitives import _invoke_subprimitive
        # bus may be None when called directly from a test; fall back
        # to a no-op stub so attack_roll's bus.emit doesn't crash.
        effective_bus = bus if bus is not None else _NullEventBus()
        for step in (weapon_action.get("pipeline") or []):
            _invoke_subprimitive(step, state, effective_bus)
    finally:
        state.current_attack["target"] = saved_target
        state.current_attack["state"] = saved_state


def _find_attacker_weapon_for_cleave(actor: Actor) -> dict | None:
    """Find the actor's highest-DPR melee weapon_attack action whose
    weapon spec declares mastery=cleave. Used to source the sub-
    attack pipeline for Cleave.

    Returns the action dict, or None if no qualifying weapon action
    exists (rare — would mean the mastery params said cleave but no
    weapon claims it).
    """
    best = None
    best_score = -1.0
    for action in (actor.template.get("actions") or []):
        if action.get("type") != "weapon_attack":
            continue
        # Check attack_roll step for the mastery
        attack_step = next(
            (s for s in (action.get("pipeline") or [])
              if s.get("primitive") == "attack_roll"), None)
        if attack_step is None:
            continue
        params = attack_step.get("params") or {}
        mastery_info = params.get("mastery") or {}
        if mastery_info.get("id") != "cleave":
            continue
        # Compute rough DPR proxy: ability_mod + dice avg
        damage_step = next(
            (s for s in (action.get("pipeline") or [])
              if s.get("primitive") == "damage"), None)
        if damage_step is None:
            continue
        score = float(damage_step.get("params", {}).get("modifier", 0))
        if score > best_score:
            best = action
            best_score = score
    return best


def _mastery_push(actor: Actor, target: Actor, state: CombatState,
                     params: dict) -> None:
    """Push: on hit, push target up to 10 ft straight away from actor.

    Uses `geometry.push_creature` which snaps to the 8-direction
    unit vector and moves the target in 5-ft steps.

    PR #65: enforces the RAW size gate — Push only affects Large or
    smaller creatures. Huge / Gargantuan targets are immune; a
    `weapon_mastery_skipped` event is logged with reason=size_immune.

    v1 still doesn't check for collisions with other actors at the
    push destination — open-battlefield assumption.
    """
    from engine.core.geometry import push_creature
    from engine.core.sizes import PUSH_SIZES, normalize_size
    target_size = normalize_size(getattr(target, "size", None))
    if target_size not in PUSH_SIZES:
        state.event_log.append({
            "event": "weapon_mastery_skipped",
            "mastery": "push",
            "actor": actor.id,
            "target": target.id,
            "reason": "size_immune",
            "target_size": target_size,
        })
        return
    pre_pos = target.position
    pushed_ft = push_creature(actor, target, 10)
    state.event_log.append({
        "event": "weapon_mastery_applied",
        "mastery": "push",
        "actor": actor.id,
        "target": target.id,
        "pushed_ft": pushed_ft,
        "from": list(pre_pos),
        "to": list(target.position),
    })


def _mastery_slow(actor: Actor, target: Actor, state: CombatState,
                     params: dict) -> None:
    """Slow: on hit AND damage dealt, reduce target's walking speed
    by 10 ft until the start of actor's next turn.

    RAW: "If the creature is hit by this property more than once,
    the Speed reduction doesn't exceed 10 feet." v1 enforces this
    by no-op-ing when the target already has any Slow record (any
    source). New applications don't refresh duration in v1 — a
    future tightening could refresh.

    Implementation:
      - Direct mutation of `target.speed["walk"]` (subtract 10,
        capped at 0)
      - Stash `_slow_data: {source_id, original_speed,
        applied_at_round}` on the target
      - Runner's turn_start handler scans all actors for _slow_data
        whose source_id matches the acting actor; restores speed
        and clears the record (see runner.py
        `_expire_slow_from_source`)
    """
    # No-op if target already slowed (RAW: doesn't stack beyond 10 ft).
    if hasattr(target, "_slow_data") and target._slow_data is not None:
        state.event_log.append({
            "event": "weapon_mastery_skipped",
            "mastery": "slow",
            "actor": actor.id,
            "target": target.id,
            "reason": "already_slowed",
        })
        return

    current_speed = int((target.speed or {}).get("walk", 30))
    new_speed = max(0, current_speed - 10)
    actual_reduction = current_speed - new_speed
    target.speed["walk"] = new_speed
    target._slow_data = {
        "source_id": actor.id,
        "original_speed": current_speed,
        "applied_at_round": state.round,
    }
    state.event_log.append({
        "event": "weapon_mastery_applied",
        "mastery": "slow",
        "actor": actor.id,
        "target": target.id,
        "reduction_ft": actual_reduction,
        "new_speed": new_speed,
    })


def expire_slow_from_source(source_actor_id: str,
                                state: CombatState) -> int:
    """Restore speed for any actor slowed BY `source_actor_id`.

    Called from the runner's turn_start handler when the acting
    actor (`source_actor_id`) starts a new turn — any creature
    they slowed last turn gets their speed back.

    Returns the number of actors restored.
    """
    restored = 0
    for actor in state.encounter.actors:
        slow_data = getattr(actor, "_slow_data", None)
        if not slow_data:
            continue
        if slow_data.get("source_id") != source_actor_id:
            continue
        original = int(slow_data.get("original_speed", 30))
        actor.speed["walk"] = original
        actor._slow_data = None
        state.event_log.append({
            "event": "weapon_mastery_expired",
            "mastery": "slow",
            "actor": actor.id,
            "source_id": source_actor_id,
            "restored_speed": original,
        })
        restored += 1
    return restored


def _mastery_graze(actor: Actor, target: Actor, state: CombatState,
                      params: dict) -> None:
    """Graze: on a MISS, deal ability_mod damage of the weapon's
    damage type. No save, no attack roll — just flat ability_mod
    damage.

    params must include `ability_mod` + `damage_type` (baked by
    `pc_schema._build_weapon_action`).
    """
    ability_mod = int(params.get("ability_mod", 0))
    if ability_mod <= 0:
        # RAW: 0 or negative ability mod → no damage. Skip cleanly.
        state.event_log.append({
            "event": "weapon_mastery_applied",
            "mastery": "graze",
            "actor": actor.id,
            "target": target.id,
            "amount": 0,
            "reason": "ability_mod_non_positive",
        })
        return
    damage_type = str(params.get("damage_type", "untyped"))
    # Resistance / vulnerability / immunity (mirror _damage primitive)
    total = ability_mod
    template = target.template or {}
    if damage_type in (template.get("damage_immunities") or []):
        total = 0
    elif damage_type in (template.get("damage_resistances") or []):
        total = total // 2
    elif damage_type in (template.get("damage_vulnerabilities") or []):
        total = total * 2
    total = max(0, total)

    target.hp_current = max(0, target.hp_current - total)
    state.event_log.append({
        "event": "weapon_mastery_applied",
        "mastery": "graze",
        "actor": actor.id,
        "target": target.id,
        "amount": total,
        "type": damage_type,
        "target_hp_remaining": target.hp_current,
    })
    if target.hp_current == 0:
        target.is_dead = True
        state.event_log.append({"event": "creature_dropped",
                                  "creature": target.id})


# ============================================================================
# Dispatch
# ============================================================================

def apply_mastery_effects(mastery_params: dict | None,
                             actor: Actor, target: Actor,
                             attack_state: str,
                             state: CombatState,
                             bus=None) -> None:
    """Dispatch weapon mastery effects after attack resolution.

    No-op if:
      - mastery_params is None / empty
      - actor doesn't know the mastery id
      - the mastery has no effect for the given attack_state (e.g.,
        Vex/Sap/Topple are hit-only; Graze is miss-only)

    `mastery_params` shape (baked by pc_schema._build_weapon_action):
      {
        "id": "vex" | "sap" | "topple" | "graze",
        "ability_mod": int,
        "damage_type": str,
        "save_dc": int (Topple only — others tolerate missing),
      }

    Called from primitives._attack_roll after the attack_state is
    final but BEFORE the damage primitive runs (so Topple-induced
    Prone affects subsequent same-pipeline reactions, and Graze
    damage on miss is logged before the no-damage branch).
    """
    if not mastery_params:
        return
    mastery_id = mastery_params.get("id")
    if not mastery_id or not actor_knows_mastery(actor, mastery_id):
        return

    # Hit-only masteries
    if attack_state in ("hit", "crit"):
        if mastery_id == "vex":
            _mastery_vex(actor, target, state)
        elif mastery_id == "sap":
            _mastery_sap(actor, target, state)
        elif mastery_id == "topple":
            _mastery_topple(actor, target, state, mastery_params)
        elif mastery_id == "push":
            _mastery_push(actor, target, state, mastery_params)
        elif mastery_id == "slow":
            _mastery_slow(actor, target, state, mastery_params)
        elif mastery_id == "cleave":
            # Cleave fires AFTER damage in v1 — but apply_mastery_effects
            # is called BEFORE damage in the attack pipeline. The
            # ordering still works because Cleave's sub-attack is a
            # separate attack_roll + damage that doesn't depend on the
            # original attack's damage step having fired. The primary
            # target may not have taken damage yet when the second
            # attack rolls; that's fine (Cleave RAW doesn't require
            # the primary attack to deal damage, just to hit).
            _mastery_cleave(actor, target, state, mastery_params, bus)
    # Miss-only masteries
    elif attack_state == "miss":
        if mastery_id == "graze":
            _mastery_graze(actor, target, state, mastery_params)
