"""Simulacrum — a duplicate caster (microwave arc, Stage D).

RAW (PHB 2024, Simulacrum, 7th-level): a 12-HOUR cast that shapes snow into an
illusory duplicate of a creature you can see. The duplicate is a creature,
partly real: it has the original's game statistics EXCEPT its HP maximum is
HALF the original's, and it can't regain spell slots (it keeps the slots it had
when created but never recovers them). It's friendly to you and your companions,
acts on its own turn, and obeys your commands.

Because the cast time is 12 hours, a Simulacrum is ALWAYS pre-cast before an
encounter — so in combat it is simply a second creature already on the field.
We model it exactly that way: `build_simulacrum(original)` clones the caster
into a half-HP duplicate that joins the party roster. It then takes its own
turn (own initiative) and — crucially for the "microwave" — holds its OWN
concentration, independent of the original. The real Wizard can hold the Wall
of Force dome (concentration #1) while the Simulacrum holds Cloudkill / Sickening
Radiance (concentration #2): the full trap-and-cook combo that a single
concentration slot can't build.

v1 scope: the duplicate is a faithful stat copy at half HP with its own fresh
spell-slot set for the encounter (within one combat slots don't regenerate
anyway, so "can't regain slots" is moot at the encounter scale). Snow/cold-
climate flavor and the 12-hour ritual are out of scope — we model the combat
object, not the ritual.
"""
from __future__ import annotations

import copy

from engine.core.state import Actor

SIMULACRUM_HP_FRACTION = 0.5
SIMULACRUM_ID_SUFFIX = "_simulacrum"


def is_simulacrum(actor: Actor) -> bool:
    """True if `actor` is a Simulacrum duplicate."""
    return bool((getattr(actor, "template", None) or {}).get("is_simulacrum"))


def build_simulacrum(original: Actor) -> Actor:
    """Build a Simulacrum duplicate of `original`: a half-HP clone that shares
    its stats, actions, and a fresh copy of its spell slots, with its own
    runtime state (fresh concentration, cleared per-turn flags). Joins the party
    roster as a second independent caster.

    The clone is a deep copy (the engine guarantees plain-data state, so this is
    safe + fully independent). Its `template.is_simulacrum` flag marks it."""
    sim = copy.deepcopy(original)
    sim.id = f"{original.id}{SIMULACRUM_ID_SUFFIX}"
    sim.name = f"{original.name} (Simulacrum)"

    # Half the original's maximum HP (RAW); start at full of that reduced max.
    sim.hp_max = max(1, int(original.hp_max * SIMULACRUM_HP_FRACTION))
    sim.hp_current = sim.hp_max

    # Fresh runtime state — its own concentration + turn flags, not the
    # original's mid-fight state (build_simulacrum is called at roster time).
    sim.concentration_on = None
    sim.moved_this_turn = False
    sim.action_surge_used_this_turn = False
    sim.dashed_this_turn = False
    sim.is_dead = False
    sim.is_dying = False
    sim.is_stable = False
    sim.death_save_successes = 0
    sim.death_save_failures = 0
    sim.applied_conditions = []
    sim.active_modifiers = []
    sim.active_speed_grants = []

    # Mark the clone (template was deep-copied with the actor).
    sim.template["is_simulacrum"] = True
    return sim
