"""Recharge ability tracking + candidate gate.

Monster abilities that, once used, are unavailable until they "recharge"
on a die roll at the start of the creature's turn — the dragon's Breath
Weapon ("Recharge 5–6"), the Giant Ape's Boulder Toss ("Recharge 6"),
the Giant Spider's Web, etc. RAW (SRD 5.2.1): "When the ability is used,
it can't be used again until the creature rolls the recharge number(s) on
a d6 at the start of its turn, or until the creature finishes a Short or
Long Rest" depending on the ability.

**Schema:** an action declares its limit via a `recharge` field whose
string matches the monster schema's pattern:

    - id: a_breath_weapon
      name: Fire Breath
      type: aoe_attack            # a recharge ability is an ordinary
      recharge: "5-6"             # action type + this gate
      pipeline: [...]

Accepted forms:
  - "X-Y"        → rolls a d6 at turn start; recharges on a roll in [X, Y]
                   (Recharge 6 is written "6-6"; Recharge 5–6 is "5-6").
  - "short_rest" / "long_rest" / "daily:N"
                 → does NOT recharge mid-encounter (no rest cycle in
                   combat yet — same deferral as feature_uses). The
                   ability fires once, then stays spent for the fight.

**How it composes with the rest of the pipeline:**
  - Candidate filter: an action is dropped from the pool while spent
    (engine.core.pipeline, alongside the spell-slot / feature-use gates).
  - Consumption: mark_spent at execution time (pipeline post-exec block),
    parallel to consume_slot / consume_use.
  - Turn-start roll: the runner calls roll_recharges_at_turn_start for the
    creature whose turn is beginning, AFTER turn_start is emitted.

Recharge is deliberately NOT modeled as a feature_use charge count: it's a
boolean availability that flips off on use and rolls to flip back on, not
a depleting pool with an opportunity-cost score. See feature_uses.py for
why the two are separate modules.
"""
from __future__ import annotations

import re

from engine.core.state import Actor, CombatState

# "X-Y" with each digit in 1..6 (matches the monster schema's pattern).
_DIE_RANGE_RE = re.compile(r"^([1-6])-([1-6])$")


def recharge_spec(action: dict) -> str | None:
    """Return the action's raw `recharge` string, or None if ungated."""
    spec = action.get("recharge")
    if not spec:
        return None
    return str(spec)


def parse_die_range(spec: str | None) -> tuple[int, int] | None:
    """Parse a die-based recharge spec ("5-6", "6-6") into (lo, hi).

    Returns None for rest-based / daily specs (short_rest, long_rest,
    daily:N) and for malformed/empty specs — those never recharge via the
    turn-start d6 roll.
    """
    if not spec:
        return None
    m = _DIE_RANGE_RE.match(str(spec))
    if not m:
        return None
    lo, hi = int(m.group(1)), int(m.group(2))
    if lo > hi:
        lo, hi = hi, lo
    return (lo, hi)


def is_available(actor: Actor, action: dict) -> bool:
    """True if a recharge-gated action may be used this turn.

    Non-recharge actions (no `recharge` field) are always available.
    A recharge action is available unless its id sits in the actor's
    `recharge_spent` set.
    """
    if not action.get("recharge"):
        return True
    return action.get("id") not in actor.recharge_spent


def mark_spent(actor: Actor, action: dict, state: CombatState) -> None:
    """Mark a recharge ability as used → unavailable until it recharges.

    No-op for actions without a `recharge` field or without an id. Logs a
    `recharge_spent` event.
    """
    if not action.get("recharge"):
        return
    action_id = action.get("id")
    if not action_id:
        return
    actor.recharge_spent.add(action_id)
    state.event_log.append({
        "event": "recharge_spent",
        "actor": actor.id,
        "action": action_id,
        "recharge": str(action.get("recharge")),
    })


def roll_recharges_at_turn_start(actor: Actor, state: CombatState,
                                   rng) -> None:
    """At the start of `actor`'s turn, roll a d6 for each of its spent
    die-based recharge abilities; an ability whose roll lands in its
    recharge range becomes available again.

    Rest-based / daily abilities are skipped (they don't recharge in an
    encounter). `rng` is the shared combat RNG (random.Random-like).
    """
    if not actor.recharge_spent:
        return
    for action in (actor.template.get("actions") or []):
        action_id = action.get("id")
        if not action_id or action_id not in actor.recharge_spent:
            continue
        rng_range = parse_die_range(action.get("recharge"))
        if rng_range is None:
            continue   # rest/daily — no turn-start recharge
        lo, hi = rng_range
        roll = rng.randint(1, 6)
        recharged = lo <= roll <= hi
        state.event_log.append({
            "event": "recharge_roll",
            "actor": actor.id,
            "action": action_id,
            "recharge": action.get("recharge"),
            "roll": roll,
            "recharged": recharged,
        })
        if recharged:
            actor.recharge_spent.discard(action_id)
