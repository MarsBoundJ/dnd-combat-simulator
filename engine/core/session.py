"""Multi-encounter session runner (PR #41).

Composes `EncounterRunner` (single-encounter execution) and the rest
helpers (`engine.core.rest.apply_short_rest` / `apply_long_rest`) into
an "adventuring day" sim — a sequence of encounters with rests
interleaved. This is what makes the resource-management mechanics
shipped in PRs #31, #33, #37, #40 actually matter: a fighter who burns
Action Surge in encounter 1 has to wait for a short rest to use it
again; a wizard who casts all their slots in encounter 1 either uses
Arcane Recovery on the next short rest or sleeps through a long rest.

**v1 scope:**
  - `SessionSpec` declares: list of (Encounter, rest_after) pairs +
    the set of party actor ids that persist across encounters.
  - `run_session(spec, seed)` iterates encounters:
      1. Build the live encounter, swapping any persisted party actor
         in place of the encounter's declaration (carrying forward
         HP / slots / resources / active_modifiers).
      2. Run via EncounterRunner.
      3. End concentration on party members (5+ minutes pass between
         encounters; RAW concentration spells expire).
      4. If `rest_after` is "short" or "long", apply that rest to
         each living party member.
  - Returns a `SessionResult` with per-encounter terminal state +
    rest summaries + the final party state dict.

**Persistence semantics:**
  - HP, spell slots, feature resources, modifiers → persist across
    encounters until rested
  - Concentration → ends at each encounter boundary (time passes)
  - Dead party members → stay dead, excluded from subsequent encounters
  - Fled party members → return for the next encounter (fleeing is a
    tactical retreat, not a session-ending event)
  - Position → taken from the new encounter spec (party doesn't carry
    spatial position between encounters)

**Deferred:**
  - YAML session format (sessions are constructed in Python for v1)
  - "Should I nova or pace?" AI awareness — party is on EncounterRunner
    autopilot which has no concept of "save resources for encounter 3"
  - Time-based concentration expiry mid-encounter
  - Resurrection / fallback for dead party members
  - Damaged equipment / consumables (potions used = gone forever)
  - Cross-encounter narrative state (NPC reactions, faction tracking)
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Literal

from engine.core.state import Actor, Encounter, CombatState
from engine.core.runner import EncounterRunner


RestType = Literal["short", "long", "none"]


@dataclass
class SessionEncounter:
    """One encounter slot in a session — the Encounter definition +
    the rest to take after (or "none" for the last one).

    `encounter` is the Encounter as declared (with the party actors
    listed for spatial / fixture purposes); `run_session` swaps in
    the PERSISTED versions of party actors at run time.
    """
    encounter: Encounter
    rest_after: RestType = "none"


@dataclass
class SessionSpec:
    """The full session declaration."""
    encounters: list[SessionEncounter]
    # Actor ids that persist across encounters (HP, slots, resources
    # carry over). Other actor ids in any encounter's actor list are
    # treated as ephemeral (fresh enemies per encounter).
    party_actor_ids: set[str] = field(default_factory=set)


@dataclass
class SessionResult:
    """What the session produced — one entry per encounter that ran."""
    encounter_results: list[dict] = field(default_factory=list)
    # Final state of each party actor (Actor objects, post all rests
    # and encounter persistence). Keyed by actor id.
    party_final: dict[str, Actor] = field(default_factory=dict)


def run_session(spec: SessionSpec, seed: int | None = None) -> SessionResult:
    """Run all encounters in `spec` sequentially with rests applied
    between as specified. Returns a SessionResult summarizing what
    happened.

    Each encounter result is a dict:
      {
        "encounter_id": str,
        "state": CombatState,
        "termination_reason": str,
        "rest_after": RestType,
        "rest_summaries": dict[str, dict]  # per-party-actor rest summary
      }

    Seeding: if `seed` is provided, each encounter uses a deterministic
    derived seed (seed + encounter_index) so the session as a whole is
    reproducible without all encounters rolling identical dice.
    """
    party: dict[str, Actor] = {}
    results: list[dict] = []

    for i, sess_enc in enumerate(spec.encounters):
        # 1. Build the live encounter, swapping in persisted party
        # actors where they appear in the encounter's actor list.
        actors = _hydrate_actors(sess_enc.encounter, party,
                                    spec.party_actor_ids)
        if not actors:
            # No actors left — TPK happened earlier and no enemies
            # declared standalone. Skip cleanly.
            results.append({
                "encounter_id": sess_enc.encounter.id,
                "state": None,
                "termination_reason": "no_actors_remaining",
                "rest_after": sess_enc.rest_after,
                "rest_summaries": {},
            })
            continue
        live_enc = Encounter(
            id=sess_enc.encounter.id,
            actors=actors,
            environment=sess_enc.encounter.environment,
            initial_distances=sess_enc.encounter.initial_distances,
        )

        # 2. Run the encounter
        enc_seed = seed + i if seed is not None else None
        runner = EncounterRunner.new(live_enc, seed=enc_seed)
        # Sync the primitives module's global RNG with the runner's
        # per-encounter RNG. _get_rng in primitives.py reads from the
        # module-level _rng (not state/bus), so without this call,
        # encounter outcomes would depend on whichever test ran last.
        import engine.primitives as _primitives_module
        _primitives_module.set_rng(runner.rng)
        # Pace-aware AI (PR #42): pass the number of encounters STILL
        # AHEAD of (and including) this one so the urgency factor
        # decreases across the day. Encounter 1 of 3 → encounters_
        # remaining_today=3; encounter 3 of 3 → 1.
        encounters_remaining = len(spec.encounters) - i
        state = runner.run(seed=enc_seed,
                            encounters_remaining_today=encounters_remaining)

        # 3. End concentration on surviving party members (time passes)
        _end_party_concentration(actors, spec.party_actor_ids, state)

        # 4. Apply rest if specified
        rest_summaries = _apply_rest_to_party(
            actors, spec.party_actor_ids, sess_enc.rest_after, state)

        # 5. Update the persistent party map (so dead-and-gone party
        # members are tracked correctly for subsequent encounters)
        for a in actors:
            if a.id in spec.party_actor_ids:
                party[a.id] = a

        results.append({
            "encounter_id": sess_enc.encounter.id,
            "state": state,
            "termination_reason": state.termination_reason,
            "rest_after": sess_enc.rest_after,
            "rest_summaries": rest_summaries,
        })

    return SessionResult(encounter_results=results, party_final=party)


# ============================================================================
# Helpers
# ============================================================================

def _hydrate_actors(encounter: Encounter,
                       party: dict[str, Actor],
                       party_actor_ids: set[str]) -> list[Actor]:
    """Replace each party-member-in-the-encounter with the persisted
    version (if one exists from a prior encounter), preserving HP /
    slots / resources / modifiers. Non-party actors are used as-is.

    Dead party members (from a prior encounter) are EXCLUDED — they
    don't appear in this encounter. Fled party members are reset to
    `is_fled = False` and DO appear (tactical retreat, not session
    exit).
    """
    actors: list[Actor] = []
    for a in encounter.actors:
        if a.id in party_actor_ids and a.id in party:
            persisted = party[a.id]
            # Drop dead party members from subsequent encounters
            if persisted.is_dead or persisted.hp_current <= 0:
                continue
            # Fled members come back; reset per-encounter state
            persisted.is_fled = False
            persisted.reset_turn()
            # Position comes from the new encounter spec — party
            # doesn't carry spatial position between encounters
            persisted.position = a.position
            actors.append(persisted)
        else:
            actors.append(a)
    return actors


def _end_party_concentration(actors: list[Actor],
                                party_actor_ids: set[str],
                                state: CombatState) -> None:
    """End any active concentration on party members at the encounter
    boundary. RAW concentration spells have minute-scale durations
    (Bless = 1 minute; Hold Person = 1 minute; etc.); 5+ minutes pass
    between encounters in any sensible adventuring day, so anything
    still active would have expired."""
    from engine.core.concentration import end_concentration
    for a in actors:
        if a.id in party_actor_ids and a.concentration_on is not None:
            end_concentration(a, state, reason="encounter_ended")


def _apply_rest_to_party(actors: list[Actor],
                            party_actor_ids: set[str],
                            rest_type: RestType,
                            state: CombatState) -> dict[str, dict]:
    """Apply short / long rest to each living party member. Returns
    {actor_id: rest_summary_dict} for inspection."""
    if rest_type == "none":
        return {}
    summaries: dict[str, dict] = {}
    if rest_type == "short":
        from engine.core.rest import apply_short_rest as _rest
    elif rest_type == "long":
        from engine.core.rest import apply_long_rest as _rest
    else:
        raise ValueError(f"Unknown rest_type {rest_type!r}")
    for a in actors:
        if a.id not in party_actor_ids:
            continue
        if not a.is_alive():
            continue   # dead / fled don't rest
        summaries[a.id] = _rest(a, state)
    return summaries
