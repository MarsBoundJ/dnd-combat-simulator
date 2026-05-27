"""Engine state — dataclasses for actor, encounter, combat state.

Design commitment: every state object is **plain Python data**
(dataclasses, dicts, lists, primitives). No Python-object-specific
state, no closures, no callbacks-as-state. This guarantees:

  1. Full JSON serialization (Foundry bridge can ship state over the
     wire as JSON).
  2. Deterministic replay (snapshot/restore for testing).
  3. Observation mode (external driver can hold state and pass it back).

See docs/architecture/schema-design.md §3 and the eventual Foundry
integration in CONTEXT.md Phase 2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ============================================================================
# Actor — a single creature in the encounter (PC or monster)
# ============================================================================

@dataclass
class Actor:
    """One creature in the encounter.

    Mutable during combat: HP, position, applied_conditions, resources, etc.
    The static template (stat block) is in `template`; runtime state is
    in the rest of the fields.
    """
    id: str                                     # instance id, e.g. "goblin_1"
    name: str                                   # display name
    template: dict                              # the loaded YAML template (monster or PC)
    side: str                                   # "pc" | "enemy" | "neutral"

    # Combat stats
    hp_current: int = 0
    hp_max: int = 0
    ac: int = 10
    speed: dict = field(default_factory=lambda: {"walk": 30})
    position: tuple[int, int] = (0, 0)          # grid coords; (0,0) until movement matters

    # Ability scores + modifiers
    abilities: dict = field(default_factory=dict)   # {"str": {"score": 16, "save": 5}, ...}

    # Runtime state
    applied_conditions: list = field(default_factory=list)   # list of {condition_id, source, ...}
    active_modifiers: list = field(default_factory=list)     # registry of active modifiers
    resources: dict = field(default_factory=dict)            # {"second_wind_uses_remaining": 2, ...}
    actions_used_this_turn: dict = field(default_factory=lambda: {
        "action": False, "bonus_action": False, "reaction": False,
    })
    initiative: int = 0
    is_dead: bool = False
    is_fled: bool = False

    # Concentration tracking — at most ONE concentration spell active.
    # None when not concentrating; otherwise:
    #   {action_id: str, caster_id: str, applied_at_round: int}
    # Modifiers tied to this concentration are tagged via their
    # source.action_id + source.caster_id, so end_concentration can scan
    # all actors and remove them.
    concentration_on: dict | None = None

    # Spell slots remaining at each level — {1: 3, 2: 2, 3: 1, ...}
    # Empty dict = not a spellcaster (no actions require slots).
    # Decremented at execution time via engine.core.spell_slots.consume_slot.
    spell_slots: dict = field(default_factory=dict)

    # Maximum slots per level — populated alongside spell_slots at build
    # time (defaults to a copy of the initial spell_slots). Used by
    # restoration mechanics like Arcane Recovery (PR #37) to cap
    # how many slots can be recovered. Long-rest restoration would
    # also reference this. Empty dict = no max tracked = no
    # restoration possible.
    spell_slots_max: dict = field(default_factory=dict)

    # Set to True while a Disengage-tagged turn is in flight. Cleared by
    # reset_turn() at start of next turn. While True, movement from this
    # actor does NOT trigger opportunity attacks (per RAW Disengage:
    # "Your speed doesn't provoke opportunity attacks for the rest of
    # your turn"). See engine.core.reactions.find_oa_triggers.
    disengaging: bool = False

    # Set to True when this actor has consumed their per-turn movement
    # (via _move_to_engage). Cleared by reset_turn(). The runner checks
    # this when Action Surge re-runs the main slot — RAW gives one move
    # per turn, not one per action, so the Action Surge second action
    # cannot trigger another _move_to_engage.
    moved_this_turn: bool = False

    # Set to True when this actor activated Action Surge this turn. The
    # runner re-runs the main slot once after the regular action +
    # bonus action complete. Cleared by reset_turn(). Resource charge
    # (`resources["action_surge_uses_remaining"]`) is decremented at
    # activation time, NOT here — that's per-short-rest, not per-turn.
    action_surge_used_this_turn: bool = False

    # Cover state (PR #48): one of 'none' | 'half' | 'three_quarters'.
    # Drives the AC + DEX-save bonus applied during attack resolution
    # (+2 for half, +5 for three_quarters). v1 is per-actor and
    # symmetric (everyone attacking sees the same cover bonus); future
    # work models per-(attacker, target) cover based on terrain
    # geometry. Total cover (auto-miss) is also deferred — needs an
    # attack-cancellation path.
    cover: str = "none"

    # Darkvision range in feet (PR #50). 0 = no darkvision (normal sight
    # only — can't see anything in a dark zone). Typical RAW values:
    # most races/monsters with darkvision have 60 ft; some (deep-dwellers,
    # drow, true-monsters) have 120 ft. Per RAW: in darkness, darkvision
    # treats darkness within range as dim light. v1 models that as
    # "still visible" — the dim-light Perception disadvantage is
    # deferred to a perception-check PR.
    # Loaded from monster template's `senses.special.darkvision` (numeric
    # feet) or from a fixture-level `darkvision_range_ft` override.
    # NOTE: ordinary darkvision does NOT pierce magical_dark_zones —
    # only Truesight (or future Devil's Sight) does.
    darkvision_range_ft: int = 0

    # Truesight range in feet (PR #52). 0 = no truesight (most actors).
    # Per RAW: truesight sees in nonmagical AND magical darkness, sees
    # invisible creatures and objects, automatically detects visual
    # illusions and succeeds on saves against them, and perceives the
    # original form of a shapechanger. v1 models the first two only —
    # illusions + shapechangers aren't in the engine yet. Truesight
    # does NOT bypass heavy obscurement (fog) per RAW — fog is
    # physical, not magical.
    # Loaded from template senses.special.truesight or actor_spec override.
    truesight_range_ft: int = 0

    # Blindsight range in feet (PR #52). 0 = no blindsight (most
    # actors). Per RAW: a creature with blindsight can perceive its
    # surroundings without relying on sight, within a specific
    # radius. Bypasses Invisible, darkness (magical + nonmagical),
    # heavy obscurement (fog) — the lot. Blindsight wins over every
    # other vision check within range; this is the dominant override
    # in can_actor_see.
    # Loaded from template senses.special.blindsight or actor_spec override.
    blindsight_range_ft: int = 0

    # Passive Perception (PR #51). Used by vision.can_actor_see to
    # auto-spot a Hide-source-Invisible target whose recorded
    # stealth_total falls at or below the observer's passive Perception.
    # Loaded from monster template `senses.passive_perception` (already
    # declared on SRD monsters) or from a PC template's computed value
    # (10 + WIS_mod + PB if Perception-proficient). Defaults to 10 as a
    # last-resort fallback (raw average human with neutral WIS).
    passive_perception: int = 10

    # Weapon mastery properties this actor "knows" (PR #54). When the
    # actor wields a weapon whose intrinsic `mastery` matches an entry
    # here, the property fires after attack resolution. Loaded from
    # the template's `weapon_masteries` list (PC schema bakes it from
    # the pc_spec `weapon_masteries:` field) or an actor_spec override.
    # v1 ships four properties: vex / sap / topple / graze. See
    # engine.core.weapon_masteries.KNOWN_MASTERIES.
    weapon_masteries: list = field(default_factory=list)

    def is_alive(self) -> bool:
        return self.hp_current > 0 and not self.is_dead and not self.is_fled

    def is_bloodied(self) -> bool:
        return self.hp_current <= (self.hp_max // 2)

    def reset_turn(self) -> None:
        self.actions_used_this_turn = {
            "action": False, "bonus_action": False, "reaction": False,
        }
        # Disengage's OA-suppression lasts until end of the actor's turn.
        # We clear at the next turn's start (== this actor's reset_turn);
        # the prior turn's flag is moot since OAs only fire during movement.
        self.disengaging = False
        # Per-turn movement / Action Surge flags. Resources (per-short-
        # rest charges) are NOT cleared here — those live longer than
        # one turn and only reset on short / long rest.
        self.moved_this_turn = False
        self.action_surge_used_this_turn = False
        # Per-turn dedup set for slot=free actions (PR #57). Nick-
        # generated off-hand attacks fire here, once per turn.
        # Reset attribute-style since the field isn't a dataclass
        # member (avoids forcing a schema change for a runner-only
        # bookkeeping detail).
        if hasattr(self, "_free_actions_fired_this_turn"):
            self._free_actions_fired_this_turn.clear()
        # PR #58: per-turn Cleave dedup. Cleared each turn so the
        # actor can Cleave once per turn even across multi-attack /
        # Action Surge re-runs.
        if hasattr(self, "_cleave_fired_this_turn"):
            self._cleave_fired_this_turn = False


# ============================================================================
# Encounter — the full battle scenario
# ============================================================================

@dataclass
class Encounter:
    """One encounter scenario: a list of actors + environment."""
    id: str
    actors: list[Actor]
    environment: dict = field(default_factory=dict)       # template name, terrain, etc.
    initial_distances: dict = field(default_factory=dict)  # {(id1, id2): ft}; optional


# ============================================================================
# CombatState — runtime state during an encounter
# ============================================================================

@dataclass
class CombatState:
    """Mutable per-encounter combat state."""
    encounter: Encounter
    round: int = 0
    turn_order: list = field(default_factory=list)   # actor ids in initiative order
    current_turn_idx: int = 0
    event_log: list = field(default_factory=list)
    terminated: bool = False
    termination_reason: str = ""

    # Per-current-attack scratch space (cleared between attacks)
    current_attack: dict = field(default_factory=dict)

    # Per-current-save scratch space (used by forced_save / save_modifier)
    current_save: dict = field(default_factory=dict)

    # Content registry — lookup for condition definitions, spells, etc.
    # Set by the runner via EncounterRunner.attach_content_registry().
    # Optional: if None, condition application stores markers only (no effects fire).
    content_registry: object | None = None

    # Recurring-save callbacks registered against actor turn-end events.
    # Entries: { target_id, condition_id, source_id, ability, dc, on_success, trigger_event }
    # Resolved by runner at the appropriate turn boundary.
    recurring_saves: list = field(default_factory=list)

    # Persistent auras (PR #43): self-anchored area effects that
    # trigger forced saves on creatures who satisfy the trigger
    # condition (v1: at their turn-start while in the area). Spirit
    # Guardians is the canonical first consumer. Entry shape:
    #   { caster_id, action_id, named_effect, radius_ft,
    #     trigger_event, ability, dc, on_fail, on_success, affected,
    #     applied_at_round }
    # Resolved by runner via _resolve_persistent_aura_triggers; cleaned
    # up by engine.core.concentration.end_concentration when the caster
    # drops concentration.
    persistent_auras: list = field(default_factory=list)

    # Used by the spell-slot opportunity-cost formula (see
    # engine/core/spell_slots.py). Default 3 = mid-adventuring-day baseline
    # per the framework's 6-encounter day. Higher = early-day (slots are
    # "cheap" to spend); lower = late-day (preserve remaining slots).
    encounters_remaining_today: int = 3

    def current_actor(self) -> Actor | None:
        if not self.turn_order:
            return None
        return self._actor_by_id(self.turn_order[self.current_turn_idx])

    def _actor_by_id(self, actor_id: str) -> Actor | None:
        for a in self.encounter.actors:
            if a.id == actor_id:
                return a
        return None

    def living_actors_by_side(self) -> dict[str, list[Actor]]:
        sides: dict[str, list[Actor]] = {}
        for a in self.encounter.actors:
            if a.is_alive():
                sides.setdefault(a.side, []).append(a)
        return sides

    def advance_turn(self) -> None:
        if not self.turn_order:
            return
        self.current_turn_idx = (self.current_turn_idx + 1) % len(self.turn_order)
        if self.current_turn_idx == 0:
            self.round += 1


# ============================================================================
# Helper: ability modifier from score
# ============================================================================

def ability_modifier(score: int) -> int:
    """Standard D&D ability modifier: floor((score - 10) / 2)."""
    return (score - 10) // 2
