"""Weapon Mastery properties (PR #54).

5e 2024 PHB introduces Weapon Mastery as a class feature. Each
character with the feature "knows" a number of mastery properties
(scales by class level). When they wield a weapon whose intrinsic
mastery property is one they know, the property fires.

v1 ships five properties (the rest are deferred — see module-end notes):

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

**Deferred v1:**
  - Cleave (extra attack on hit with Heavy melee) — needs sub-attack
    generation
  - Push (push target 10 ft on hit) — needs forced-movement primitive
  - Slow (reduce target speed by 10 ft) — needs speed-reduction infra
    with duration tracking
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState


# Known mastery property ids. Validated against this set when reading
# weapon specs and pc-schema declarations.
KNOWN_MASTERIES: frozenset[str] = frozenset({
    "vex", "sap", "topple", "graze",
    "nick",    # PR #57: lets off-hand attack happen as part of the
                # Attack action instead of as a bonus action. Effect
                # is at template-build time (off-hand action gets
                # slot='free' instead of 'bonus_action'); no per-
                # attack effect, so the apply_mastery_effects dispatch
                # skips Nick cleanly via the if-elif chain.
})


# Future masteries (declared deferred so we can list them in errors
# without making them "unknown"). Kept separate so adding them later
# is just a frozenset union, not a code change here.
DEFERRED_MASTERIES: frozenset[str] = frozenset({
    "cleave", "push", "slow",
})


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
                             state: CombatState) -> None:
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
    # Miss-only masteries
    elif attack_state == "miss":
        if mastery_id == "graze":
            _mastery_graze(actor, target, state, mastery_params)
