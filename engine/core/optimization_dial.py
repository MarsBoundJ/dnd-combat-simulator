"""Optimization dial (1-5) — the shared "how well does this side play?" knob.

A per-SIDE dial governs how reliably the actors make the optimal mechanical
combat choice. It's the calibration substrate behind the WoTC-baseline-vs-
optimal question (Phil, 2026-06-05): a casual table doesn't focus-fire; a
tournament team / a lich (dial 5) plays perfectly — and the same dial applies
to PCs AND monsters, so a sim can report a power-level CURVE (dial-1 casual
loses an encounter, dial-4 tactical wins it).

This module is the substrate + its FIRST consumer (focus-fire). The dial is a
probability that, WHEN a tactic is warranted by the situation, the side
actually applies it:

  dial 1 → 0.0   never (today's spread/nearest behavior)
  dial 2 → ~0.33 "accidental / moment of insight"
  dial 3 → ~0.67 usually
  dial 4 → ~0.875 reliable, occasional miss from imperfect information
  dial 5 → 1.0   perfect information, always the highest-eHP choice

Default is dial 1, so existing sims/tests are unchanged until a sim opts in by
setting `state.optimization_dials[side] = N`.
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState

DEFAULT_DIAL = 1
MIN_DIAL = 1
MAX_DIAL = 5
READY_SPELL_MIN_DIAL = 4

# P(apply a warranted tactic) by dial — Phil's mapping (2026-06-05).
FOCUS_FIRE_CHANCE: dict[int, float] = {
    1: 0.0,
    2: 1.0 / 3.0,
    3: 2.0 / 3.0,
    4: 0.875,
    5: 1.0,
}


def dial_for(actor: Actor, state: CombatState) -> int:
    """The optimization dial for `actor`'s side (default DEFAULT_DIAL).
    Stored per-side on `state.optimization_dials` ({side: dial})."""
    dials = getattr(state, "optimization_dials", None) or {}
    raw = dials.get(getattr(actor, "side", None), DEFAULT_DIAL)
    return max(MIN_DIAL, min(MAX_DIAL, int(raw)))


def set_dial(state: CombatState, side: str, dial: int) -> None:
    """Set a side's optimization dial (clamped to 1-5)."""
    if getattr(state, "optimization_dials", None) is None:
        state.optimization_dials = {}
    state.optimization_dials[side] = max(MIN_DIAL, min(MAX_DIAL, int(dial)))


def focus_fire_chance(dial: int) -> float:
    return FOCUS_FIRE_CHANCE.get(max(MIN_DIAL, min(MAX_DIAL, int(dial))), 0.0)


def conservation_strength(dial: int) -> float:
    """How strongly this side RATIONS day-limited resources (spell slots) —
    the three-styles spectrum (Tabletop Builds) operationalized on the SAME
    1-5 curve as focus_fire_chance:

      dial 1 → 0.0   impact-maximizer: slots feel "free" → nova early → run
                     dry → wipe in later fights
      dial 3 → ~0.67 partial conservation (WoTC baseline)
      dial 5 → 1.0   perfect conserve + progression: full NOVA-LATE pacing,
                     ends the day with slots to spare

    Unlike focus_fire_chance (a per-decision PROBABILITY resolved by a roll),
    this is a deterministic STRENGTH that scales the slot opportunity cost in
    spell_slots.candidate_slot_cost. dial 1 collapses the conserve-early
    penalty to 0 (cast as if slots were free); dial 5 applies it in full.

    Default dial is 1, so an un-dialed (casual) party is an impact-maximizer —
    matching focus_fire's default of no-focus-fire."""
    return focus_fire_chance(dial)


def conservation_strength_for(actor: Actor, state: CombatState) -> float:
    """conservation_strength for `actor`'s side dial."""
    return conservation_strength(dial_for(actor, state))


def _living_enemies(actor: Actor, state: CombatState) -> list[Actor]:
    return [a for a in state.encounter.actors
            if a.is_alive() and getattr(a, "side", None) != actor.side]


def focus_fire_warranted(actor: Actor, state: CombatState) -> bool:
    """The SITUATION calls for focus-fire when there are ≥2 living enemies
    (a lone target is auto-focus-fired; with one enemy there's no choice to
    make). The minion-swarm case is handled downstream: focus-fire is a
    single-target preference that AoE can still out-score, so vs a swarm the
    actor AoEs instead — exactly the right call. (Tougher "comparable enemies"
    refinement is a documented follow-up.)"""
    return len(_living_enemies(actor, state)) >= 2


def should_focus_fire(actor: Actor, state: CombatState,
                      rng: random.Random | None = None) -> bool:
    """True if `actor` focus-fires THIS decision: the situation warrants it
    AND a dial-probability roll lands. Dial 1 → never; dial 5 → always.
    The roll uses the shared seeded RNG so a sim is reproducible."""
    if not focus_fire_warranted(actor, state):
        return False
    chance = focus_fire_chance(dial_for(actor, state))
    if chance <= 0.0:
        return False
    if chance >= 1.0:
        return True
    if rng is None:
        from engine.primitives import get_rng
        rng = get_rng()
    return rng.random() < chance


# A break-on-damage-locked enemy at/below this fraction of its max HP is
# "finishable" — worth waking to dispatch (it dies; the lost lock is moot).
FINISHABLE_LOCKED_FRAC = 0.25


def _is_soft_locked(enemy: Actor) -> bool:
    """True if `enemy` is held by a BREAK-ON-DAMAGE control (Hypnotic Pattern,
    Sleep) — damaging it would WAKE it. Persistent control (Hold Monster's
    paralysis) doesn't carry the flag, so it isn't 'soft' (you can hit it
    freely)."""
    return any(c.get("break_on_damage")
               for c in (getattr(enemy, "applied_conditions", None) or []))


def focus_fire_target(actor: Actor, state: CombatState,
                      candidates_targets: list[Actor] | None = None) -> Actor | None:
    """The enemy to concentrate fire on — CONTROL-AWARE (the lock → peel
    one-at-a-time tactic).

    Base pick: lowest current-HP living enemy (closest to dead → fastest to
    remove; counteracts the eHP overkill-cap that otherwise spreads damage).

    Control-aware: don't gratuitously break the party's break-on-damage locks.
    Prefer UN-locked enemies (the real, still-acting threats) plus any locked
    enemy already near death (finishable — killing it makes the lost lock
    moot). Only target a HEALTHY locked enemy when nothing else is available
    (then you peel ONE, leaving the rest locked). Restricted to
    `candidates_targets` when given (what the actor can hit this turn)."""
    pool = (candidates_targets if candidates_targets is not None
            else _living_enemies(actor, state))
    pool = [e for e in pool
            if e is not None and e.is_alive()
            and getattr(e, "side", None) != actor.side]
    if not pool:
        return None
    preferred = [e for e in pool
                 if not _is_soft_locked(e)
                 or e.hp_current <= FINISHABLE_LOCKED_FRAC * (e.hp_max or 1)]
    chosen = preferred if preferred else pool
    return min(chosen, key=lambda e: e.hp_current)
