"""Legendary Resistance — spend a per-day charge to turn a failed save
into a success.

RAW (SRD 5.2.1): "Legendary Resistance (N/Day). If the creature fails a
saving throw, it can choose to succeed instead." A trait of adult+ dragons
and the legendary solo monsters (Lich, Vampire, Balor, Pit Fiend, Kraken,
Tarrasque, …).

Modeling: the charge count lives on the actor as the resource
`legendary_resistance_remaining` (seeded by cli._build_actor from the
monster stat block's `legendary_resistance: { uses: N }`). The save path
(engine.primitives._forced_save) calls `maybe_use` the moment a save comes
up "fail": if the saver is a legendary creature with a charge left, the
charge is spent and the outcome flips to "success".

**v1 policy — spend on any failed save while charges remain.** RAW it's a
DM *choice* (a smart DM hoards charges for high-impact saves). Modeling
that needs per-save impact estimation; v1 takes the simple, conservative-
for-the-monster reading: never fail a save while Legendary Resistance is
available. This slightly over-spends vs optimal play on low-impact saves;
a "save it for the dangerous saves" policy is deferred.

**v1 scope — the `_forced_save` path only.** Recurring saves
(engine.primitives._recurring_save), concentration saves, and other
bespoke save sites do NOT yet consult Legendary Resistance. The dominant
case (a PC spell / breath / effect forcing a save on the monster) goes
through `_forced_save`, so that is where the hook lives. Extending to the
other save sites is a documented follow-up.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState

RESOURCE_KEY = "legendary_resistance_remaining"


def has_charge(actor: Actor) -> bool:
    """True if the actor has a Legendary Resistance charge remaining."""
    return int(actor.resources.get(RESOURCE_KEY, 0)) > 0


def maybe_use(actor: Actor, state: CombatState, *,
                ability: str | None = None, dc: int | None = None) -> bool:
    """If `actor` has a Legendary Resistance charge, spend one and return
    True (the caller should treat the failed save as a success). Returns
    False if the actor has no charges (or the resource is absent) — the
    save stands as failed.

    Logs a `legendary_resistance_used` event with the remaining count.
    """
    remaining = int(actor.resources.get(RESOURCE_KEY, 0))
    if remaining <= 0:
        return False
    actor.resources[RESOURCE_KEY] = remaining - 1
    state.event_log.append({
        "event": "legendary_resistance_used",
        "actor": actor.id,
        "ability": ability,
        "dc": dc,
        "remaining": actor.resources[RESOURCE_KEY],
    })
    return True
