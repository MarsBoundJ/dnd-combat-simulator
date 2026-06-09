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
