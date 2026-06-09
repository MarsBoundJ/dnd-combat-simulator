"""Path of the Wild Heart — Rage of the Wilds (Barbarian L3) and the
combat-relevant rage choices (PHB 2024 / SRD-adjacent).

Rage of the Wilds (L3): whenever you activate your Rage, you choose one of
three animal aspects. The choice is combat-relevant for all three:

  - Bear:  Resistance to every damage type EXCEPT Force, Necrotic, Psychic,
           and Radiant (a much broader resistance than the base Rage B/P/S).
  - Eagle: You can take the Disengage and Dash actions as part of the Rage
           Bonus Action, and as a Bonus Action on each later turn of the
           Rage. Mobility / action economy.
  - Wolf:  While raging, your allies have Advantage on attack rolls against
           any enemy within 5 ft of you. A positional team-buff aura.

Engine modeling: the choice is a build-time pick stamped on the template as
`wild_heart_rage_choice` (default "bear"), activated on rage entry (the same
`enter_rage` hook used by Rage of the Gods). The active choice lives on
`actor.wild_heart_active_choice` while raging and is cleared on rage end.

  - Bear:  applies_bear_resistance() consulted in primitives._damage.
  - Eagle: rage-entry grant sets disengaging + dashed_this_turn; the
           per-later-turn Bonus Action is a thin follow-on (documented).
  - Wolf:  wolf_advantage_applies() consulted in modifiers.query_attack_
           modifiers as an identity-state check (mirrors Reckless Attack).

Non-combat Wild Heart features (Animal Speaker L3, Aspect of the Wilds L6,
Nature Speaker L10) are deferred to Stage 4 (AI DM) — see
docs/deferred-noncombat-features.md.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState

RAGE_CHOICES = ("bear", "eagle", "wolf")

# Bear resists every type EXCEPT these four (RAW PHB 2024).
_BEAR_NON_RESISTED = frozenset({"force", "necrotic", "psychic", "radiant"})

POWER_CHOICES = ("falcon", "lion", "ram")


def has_rage_of_the_wilds(actor: Actor) -> bool:
    """True if the actor has Rage of the Wilds (Wild Heart L3+)."""
    features = (actor.template or {}).get("features_known") or []
    return "f_rage_of_the_wilds" in features


def rage_choice(actor: Actor) -> str:
    """The actor's configured Rage of the Wilds animal (default 'bear').

    Build-time pick stamped on the template as `wild_heart_rage_choice`.
    Falls back to Bear (the strongest, most universal combat pick) for an
    unset or unrecognized value."""
    choice = (actor.template or {}).get("wild_heart_rage_choice", "bear")
    return choice if choice in RAGE_CHOICES else "bear"


def activate_rage_of_the_wilds(actor: Actor, state: CombatState) -> None:
    """Activate the chosen animal aspect on rage entry. Called from
    rage.enter_rage AFTER the actor is already raging. No-op without the
    feature."""
    if not has_rage_of_the_wilds(actor):
        return
    choice = rage_choice(actor)
    actor.wild_heart_active_choice = choice

    # Eagle's rage-entry grant: Dash + Disengage fold into the Rage Bonus
    # Action. Mark the actor disengaging (no OAs provoked this turn) and
    # dashed (doubled movement this turn). The per-later-turn Bonus Action
    # to repeat this is a documented follow-on.
    if choice == "eagle":
        actor.disengaging = True
        actor.dashed_this_turn = True

    state.event_log.append({
        "event": "rage_of_the_wilds_activated",
        "actor": actor.id,
        "choice": choice,
    })


def deactivate_rage_of_the_wilds(actor: Actor, state: CombatState) -> None:
    """Clear the active animal aspect when Rage ends. Idempotent."""
    if getattr(actor, "wild_heart_active_choice", None) is None:
        return
    prior = actor.wild_heart_active_choice
    actor.wild_heart_active_choice = None
    state.event_log.append({
        "event": "rage_of_the_wilds_deactivated",
        "actor": actor.id,
        "choice": prior,
    })


def applies_bear_resistance(target: Actor, damage_type: str) -> bool:
    """True if the Bear aspect grants resistance to this damage type:
    active Bear aspect AND the type is not one of the four exceptions
    (Force / Necrotic / Psychic / Radiant)."""
    return (getattr(target, "wild_heart_active_choice", None) == "bear"
            and damage_type not in _BEAR_NON_RESISTED)


def wolf_advantage_applies(attacker: Actor, target: Actor,
                            state: CombatState) -> bool:
    """True if the Wolf aspect grants `attacker` Advantage against `target`:
    some ally of the attacker is a raging Wolf barbarian, and `target`
    (an enemy of that barbarian) is within 5 ft of them.

    RAW: "your allies have Advantage on attack rolls against any enemy
    within 5 ft of you" — the Wolf themselves are NOT included ("your
    allies"). Mirrors the Reckless Attack identity-state read."""
    from engine.core.geometry import distance_ft
    for wolf in state.encounter.actors:
        if getattr(wolf, "wild_heart_active_choice", None) != "wolf":
            continue
        if not wolf.is_alive():
            continue
        if wolf.side != attacker.side:
            continue
        if wolf.id == attacker.id:
            continue   # "your allies" excludes the Wolf themselves
        if target.side == wolf.side:
            continue   # target must be an enemy of the Wolf
        if distance_ft(wolf.position, target.position) <= 5:
            return True
    return False


# ============================================================================
# Power of the Wilds (Wild Heart L14) — Falcon / Lion / Ram
# ============================================================================
#
# A SECOND, independent rage choice gained at L14 (alongside the L3 Rage of
# the Wilds aspect — a L14 Wild Heart barbarian picks one from each). The
# build-time pick is `template.wild_heart_power_choice` (default 'ram'),
# activated on rage entry and cleared on rage end, tracked on
# `actor.wild_heart_power_active`.
#
#   - Falcon: Fly Speed = walk speed WHILE WEARING NO ARMOR (RAW: "any
#             armor", stricter than Heavy-only). Reverted on rage end.
#   - Lion:   enemies within 5 ft of you have Disadvantage on attacks
#             against targets OTHER than you (or another active-Lion
#             barbarian) — the disadvantage twin of the Wolf aura.
#   - Ram:    on a melee hit, knock a Large-or-smaller target Prone (no
#             save). An on-hit control rider in primitives._damage.


def has_power_of_the_wilds(actor: Actor) -> bool:
    """True if the actor has Power of the Wilds (Wild Heart L14+)."""
    features = (actor.template or {}).get("features_known") or []
    return "f_power_of_the_wilds" in features


def power_choice(actor: Actor) -> str:
    """The actor's configured Power of the Wilds option (default 'ram').

    Build-time pick stamped on the template as `wild_heart_power_choice`."""
    choice = (actor.template or {}).get("wild_heart_power_choice", "ram")
    return choice if choice in POWER_CHOICES else "ram"


def _wears_armor(actor: Actor) -> bool:
    """True if the actor is wearing any armor (stamped by pc_schema as
    template.wears_armor). Falcon requires NO armor."""
    return bool((actor.template or {}).get("wears_armor", False))


def activate_power_of_the_wilds(actor: Actor, state: CombatState) -> None:
    """Activate the chosen Power of the Wilds option on rage entry. No-op
    without the feature."""
    if not has_power_of_the_wilds(actor):
        return
    choice = power_choice(actor)
    actor.wild_heart_power_active = choice

    # Falcon: Fly Speed = walk speed, but only while wearing no armor.
    if choice == "falcon" and not _wears_armor(actor):
        walk = actor.speed.get("walk", 30)
        actor._wild_heart_falcon_prior_fly = actor.speed.get("fly")
        actor.speed["fly"] = walk

    state.event_log.append({
        "event": "power_of_the_wilds_activated",
        "actor": actor.id,
        "choice": choice,
    })


def deactivate_power_of_the_wilds(actor: Actor, state: CombatState) -> None:
    """Clear the active Power of the Wilds option when Rage ends. Idempotent;
    reverts Falcon's fly grant."""
    prior = getattr(actor, "wild_heart_power_active", None)
    if prior is None:
        return
    actor.wild_heart_power_active = None

    if prior == "falcon":
        prior_fly = getattr(actor, "_wild_heart_falcon_prior_fly", None)
        if prior_fly is None:
            actor.speed.pop("fly", None)
        else:
            actor.speed["fly"] = prior_fly

    state.event_log.append({
        "event": "power_of_the_wilds_deactivated",
        "actor": actor.id,
        "choice": prior,
    })


def lion_disadvantage_applies(attacker: Actor, target: Actor,
                                state: CombatState) -> bool:
    """True if the Lion aura imposes Disadvantage on `attacker`'s roll
    against `target`: the attacker is an enemy within 5 ft of a raging Lion
    barbarian, and `target` is NOT that Lion (nor another active-Lion
    barbarian on the Lion's side).

    RAW: "any of your enemies within 5 feet of you have Disadvantage on
    attack rolls against targets other than you or another Barbarian who
    has this option active." Identity-state read (the disadvantage twin of
    the Wolf advantage aura)."""
    from engine.core.geometry import distance_ft
    for lion in state.encounter.actors:
        if getattr(lion, "wild_heart_power_active", None) != "lion":
            continue
        if not lion.is_alive():
            continue
        if lion.side == attacker.side:
            continue   # attacker must be an ENEMY of the Lion
        if distance_ft(lion.position, attacker.position) > 5:
            continue
        # Exempt targets: the Lion itself, or another active-Lion barbarian
        # on the Lion's side ("you or another Barbarian who has this active").
        if target.id == lion.id:
            continue
        if (getattr(target, "wild_heart_power_active", None) == "lion"
                and target.side == lion.side):
            continue
        return True
    return False


def try_apply_ram(attacker: Actor, target: Actor, state: CombatState,
                    attack_params: dict | None) -> None:
    """Ram (Power of the Wilds): on a melee hit while raging with Ram active,
    knock a Large-or-smaller target Prone (no save). Idempotent — skips a
    target that's already Prone. Called from primitives._damage on hit/crit."""
    if getattr(attacker, "wild_heart_power_active", None) != "ram":
        return
    if (attack_params or {}).get("kind", "melee") != "melee":
        return
    from engine.core.sizes import size_at_or_below
    if not size_at_or_below(getattr(target, "size", "medium"), "large"):
        return
    if any(c.get("condition_id") == "co_prone"
            for c in target.applied_conditions):
        return   # already prone — nothing to do
    from engine.primitives import _apply_condition
    from engine.core.smite_rider import _NoOpBus
    _apply_condition({"condition_id": "co_prone"}, state, _NoOpBus())
    state.event_log.append({
        "event": "power_of_the_wilds_ram",
        "attacker": attacker.id,
        "target": target.id,
        "effect": "prone",
    })
