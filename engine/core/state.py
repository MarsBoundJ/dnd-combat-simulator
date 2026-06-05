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
    # Temporary hit points (PR #94). RAW PHB 2024 p.244: temp HP
    # absorbs incoming damage before regular HP. Doesn't stack —
    # gaining temp HP while you already have some keeps the
    # GREATER value (ignore if new is lower). Doesn't refresh on
    # rests; lost on long rest unless a feature says otherwise.
    # Granted by Heroism, False Life, Aid (partial), Inspiring
    # Leader, Fiendish Vigor, Tempest Cleric Wrath of the Storm,
    # etc. Read+written by:
    #   - _temp_hp_grant primitive (max-semantics replacement)
    #   - _damage primitive (absorbs damage before hp_current)
    #   - apply_long_rest (clears to 0)
    temp_hp: int = 0
    # Active max-HP bonuses (PR #97). RAW spells like Aid raise BOTH
    # current and maximum HP for the duration (distinct from temp HP,
    # which is a separate absorbing buffer). Each entry tracks a
    # source so the bonus can be cleanly removed when the spell ends
    # (capping current HP at the reduced max, per RAW). Entry shape:
    #   {amount, source_id, source_action_id, named_effect}
    # Written by _hp_max_grant primitive; removed by
    # racial_traits-style cleanup at long rest (apply_long_rest) or a
    # future timed-duration system. hp_max itself already reflects the
    # bonuses (they're added in at grant time); this list is the
    # ledger for clean removal. Reusable for Heroes' Feast,
    # False Life's max-HP variants, etc.
    hp_max_bonuses: list = field(default_factory=list)
    # Hit Dice (PCs): RAW you have `level` Hit Dice of your class hit die,
    # spent on a SHORT rest to heal (each = avg(die) + CON mod); you regain
    # half your total (round down, min 1) on a LONG rest. 0 for monsters /
    # actors that don't track them (so the rest hooks no-op for them).
    hit_dice_remaining: int = 0
    hit_dice_max: int = 0
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

    # Set to True when this actor used the Dash action (PR #74). RAW:
    # Dash grants extra movement equal to your Speed for this turn.
    # `_move_to_engage` reads this flag and doubles walk speed. The
    # runner also schedules ONE additional move attempt after the BA
    # phase if the actor Dashed via Cunning Action (this lets the
    # Rogue actually close distance with the BA-Dash rather than just
    # carrying the flag uselessly into next turn). Cleared by
    # reset_turn().
    dashed_this_turn: bool = False

    # Cover state (PR #48 + PR #76): one of
    # 'none' | 'half' | 'three_quarters' | 'total'.
    # Drives the AC + DEX-save bonus applied during attack resolution
    # (+2 for half, +5 for three_quarters; 0 for total). Total cover
    # is the auto-miss case (PR #76) — single-target attacks against
    # a total-cover target are short-circuited in _attack_roll with
    # reason='total_cover' and the candidate generator filters such
    # enemies out of single-target candidate lists entirely. AoE
    # attacks still affect total-cover targets per RAW (area effects
    # cover space, not specific creatures).
    # v1 is per-actor and symmetric (everyone attacking sees the
    # same cover bonus); future work models per-(attacker, target)
    # cover based on terrain geometry.
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

    # Creature size (PR #65). Default "medium" for actors with no
    # explicit size. Loaded from monster template's top-level `size:`
    # (SRD shape; lowercase like "small" / "large") or from an
    # actor_spec override. Consumed by Push weapon mastery (RAW: only
    # Large or smaller targets) and future grapple / squeezing /
    # carry-capacity mechanics. See engine.core.sizes for the
    # KNOWN_SIZES ordering and PUSH_SIZES filter.
    size: str = "medium"

    # Creature type (PR #88). One of the RAW 14 types: aberration /
    # beast / celestial / construct / dragon / elemental / fey /
    # fiend / giant / humanoid / monstrosity / ooze / plant /
    # undead. Default "humanoid" — covers most PCs. Loaded from
    # monster template's `creature_type` (already declared on SRD
    # monsters) or from the PC race's creature_type (set by
    # pc_schema). Read by Protection from Evil and Good's
    # `attacker_creature_type_in` when-clause to gate disadvantage
    # on incoming attacks from aberration/celestial/elemental/fey/
    # fiend/undead. Future: Hunter's Mark favored-enemy filtering,
    # Holy Weapon damage type gating, type-based spell immunities.
    creature_type: str = "humanoid"

    # --- Form / identity system (Agent Identity & Lifecycle, Phase 1) ---
    # While transformed (Wild Shape / Polymorph / Change Shape), the
    # Actor's LIVE combat fields (hp_current/max, ac, speed, abilities,
    # size, creature_type, template) hold the ACTIVE form's stats, and
    # the true-form values are saved in `base_form_snapshot`. This lets
    # every existing stat/damage/death path operate unchanged — the
    # current form IS the live Actor. See docs/architecture/
    # form-identity-system.md and engine.core.forms.
    #
    # `base_form_snapshot`: dict of saved true-form fields (taken when the
    # FIRST form is assumed; None ⇒ in true form).
    base_form_snapshot: dict | None = None
    # `form_stack`: active form layers, innermost first; [] ⇒ true form.
    # Each entry: {form_id, policy, source, reversion}. Top = current.
    form_stack: list = field(default_factory=list)

    # `recharge_spent`: action_ids of recharge-gated abilities (e.g. a
    # dragon's Breath Weapon "Recharge 5–6") that have been used and are
    # currently unavailable. An action is available unless its id is in
    # here. Populated by engine.core.recharge.mark_spent at execution and
    # cleared by roll_recharges_at_turn_start when the d6 lands in range.
    # NOT reset by reset_turn — recharge persists across turns until the
    # roll succeeds. See engine/core/recharge.py.
    recharge_spent: set = field(default_factory=set)

    # `regen_suppressed`: set True when this creature takes a damage type
    # that switches off its Regeneration (Troll: acid/fire). Consumed +
    # cleared at the creature's next turn start by engine.core.regeneration
    # (one-turn suppression). NOT reset by reset_turn — it carries from the
    # damaging hit until the next turn-start regen check.
    regen_suppressed: bool = False

    # Swallow (Behir / Purple Worm / Gelatinous Cube). On the SWALLOWED
    # creature: `swallowed_by` is the swallower's id, `swallow_damage` is
    # the ongoing-acid spec {dice, type} dealt at the swallower's turn
    # start. Cleared by engine.core.swallow.release (swallower death /
    # regurgitate). A swallowed creature also has Blinded + Restrained
    # (sourced to the swallower) and Total Cover. See engine/core/swallow.py.
    swallowed_by: str | None = None
    swallow_damage: dict | None = None
    # On the SWALLOWED creature: the regurgitate spec
    # {threshold, dc, save} — if the swallower takes `threshold`+ damage
    # from this victim in one turn it makes a `save` save vs `dc` or expels
    # it (Prone). On the SWALLOWER: `swallow_damage_taken_this_turn`
    # accumulates damage from its victim this turn (reset at the victim's
    # turn start; checked at its turn end). See engine/core/swallow.py.
    swallow_regurgitate: dict | None = None
    swallow_damage_taken_this_turn: int = 0

    # `summoned_by`: the id of the creature that summoned this one into the
    # fight (Wraith → Specter, conjure spells). None for natural
    # combatants. Used for capacity caps + provenance. See
    # engine/core/summoning.py.
    summoned_by: str | None = None

    # Racial trait ids (PR #75). Loaded from PC race spec via
    # pc_schema → cli — e.g. `["t_lucky", "t_brave"]` for a Halfling.
    # Read at runtime by query_save_modifiers (Brave / Fey Ancestry /
    # Dwarven Resilience save advantage) and by attack/save d20 sites
    # (Lucky nat-1 reroll). Empty list for monsters and PCs that
    # didn't declare a race. See engine/core/racial_traits.py for the
    # registry + integration helpers.
    racial_traits: list = field(default_factory=list)

    # Rage state (PR #71, Barbarian). Flipped on by the a_rage bonus
    # action (which consumes a `rage_uses_remaining` charge); flipped
    # off by the end-of-turn auto-end check (no attack + no damage)
    # or by incapacitation. While True:
    #   - +rage_damage_bonus on STR-mod melee weapon attacks
    #     (handled in primitives._damage)
    #   - BPS resistance (handled in primitives._damage)
    #   - Advantage on STR checks + STR saves (handled via
    #     query_save_modifiers / query_d20_test_modifiers reading
    #     rage_active directly)
    # See engine/core/rage.py for the level tables + transitions.
    rage_active: bool = False
    rage_damage_bonus: int = 0

    # Reckless Attack state (PR #85, Barbarian L2). Activated via the
    # runner's `_maybe_activate_reckless_attack` pre-action hook (RAW:
    # "When you make your first attack roll on your turn, you can
    # decide to attack recklessly" — engine collapses this to a
    # pre-action decision so the AI commits before the first swing
    # rather than mid-roll).
    #   - reckless_active: True during THIS turn after activation;
    #     drives advantage on the actor's STR-mod melee weapon attack
    #     rolls. Cleared in reset_turn() at the start of the next
    #     own turn.
    #   - reckless_grants_advantage_until_next_turn: True from
    #     activation until the start of the actor's next turn; drives
    #     advantage on any attack roll TARGETING this actor. Same
    #     reset point — the "until the start of your next turn"
    #     window matches own-turn reset exactly.
    # Both flags read directly off the Actor (like rage_active); no
    # active_modifiers registration. See engine/core/reckless_attack.py
    # for the eligibility / activation / scoring helpers.
    reckless_active: bool = False
    reckless_grants_advantage_until_next_turn: bool = False

    # Ready Action state (PR #86). Set when the actor takes Ready on
    # their main action; cleared at start of next own turn (RAW: the
    # readied reaction is discarded if not taken before the start of
    # the actor's next turn). At most ONE readied action at a time —
    # taking Ready while another is pending overwrites the prior one
    # (RAW: Ready is one action per turn; can't stack readied actions).
    # Shape when set:
    #   {
    #     "action_id": "a_longsword",     # sub-action id to fire
    #     "trigger": "enemy_enters_reach" # trigger key (KNOWN_TRIGGERS
    #     | "enemy_casts_spell",          # in engine/core/ready_action.py)
    #     "trigger_params": {...},        # trigger-specific data
    #                                       # (reach_ft for enters_reach;
    #                                       # within_ft for casts_spell)
    #     "round_readied": int,           # round when Ready was taken
    #   }
    # The reaction slot is NOT pre-consumed at Ready time; it's
    # consumed when the readied action actually fires (via
    # actions_used_this_turn["reaction"]). Discarded by reset_turn at
    # start of next own turn — counted as a wasted action when no
    # trigger fired (logged via `ready_action_discarded`).
    readied_action: dict | None = None

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
        # PR #74: Dash flag + post-BA second-move dedup flag both
        # reset each turn. The dash flag is consumed by the
        # _move_to_engage speed-doubling check; the dedup attr
        # prevents the post-BA move from re-firing across re-runs.
        self.dashed_this_turn = False
        if hasattr(self, "_dash_post_move_done"):
            self._dash_post_move_done = False
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
        # PR #71: per-turn Rage end-check flags. The actor's Rage
        # auto-ends at end-of-turn if BOTH flags are False (no
        # hostile attack made + no damage taken). Cleared each turn
        # so the next turn starts a fresh accounting window. See
        # engine/core/rage.py::check_rage_end_of_turn.
        if hasattr(self, "_rage_attacked_hostile_this_turn"):
            self._rage_attacked_hostile_this_turn = False
        if hasattr(self, "_rage_damaged_this_turn"):
            self._rage_damaged_this_turn = False
        # PR #72: per-turn Sneak Attack dedup. RAW: "once per turn"
        # (not "once per round" — SA can fire on a reaction OA mid-
        # round). The flag resets at the start of each of the
        # actor's own turns, which is when their turn-dependent
        # restrictions reset.
        if hasattr(self, "_sneak_attack_used_this_turn"):
            self._sneak_attack_used_this_turn = False
        # PR #73: per-turn Divine Smite dedup. Belt-and-suspenders
        # alongside actions_used_this_turn['bonus_action'] (the
        # primary gate). Kept separate so reaction-driven smites
        # would still be blocked even if BA were somehow reset
        # mid-turn (e.g., Action Surge logic — not currently a path
        # but defensive).
        if hasattr(self, "_divine_smite_used_this_turn"):
            self._divine_smite_used_this_turn = False
        # Monk once-per-turn on-hit riders: Stunning Strike (Focus Point,
        # CON save → Stunned) and Open Hand Technique (Flurry → Topple,
        # DEX save → Prone). Both reset at the start of the Monk's turn.
        if hasattr(self, "_stunning_strike_used_this_turn"):
            self._stunning_strike_used_this_turn = False
        if hasattr(self, "_open_hand_used_this_turn"):
            self._open_hand_used_this_turn = False
        # PR #86: Ready Action discard at start of own next turn.
        # RAW: "The reaction is discarded if you don't take it before
        # the start of your next turn." Logged for telemetry so callers
        # can see how often Ready was wasted (a high discard rate
        # indicates the AI is over-eager to Ready).
        if self.readied_action is not None:
            # Log via a sentinel attribute that the runner can read +
            # forward into state.event_log. We don't have a state ref
            # here, so the runner's tick() picks up the discard event
            # after reset_turn returns.
            self._ready_discarded_this_reset = dict(self.readied_action)
            self.readied_action = None
        else:
            self._ready_discarded_this_reset = None
        # PR #85: Reckless Attack flags reset at start of own turn.
        # RAW: "Attack rolls against you have advantage until the
        # start of your next turn" — the grants-advantage window ends
        # exactly here. The `reckless_active` flag is also a per-turn
        # state (advantage applies "during this turn"), so it resets
        # at the same boundary. The runner's pre-action hook may flip
        # both back ON later in this same turn.
        self.reckless_active = False
        self.reckless_grants_advantage_until_next_turn = False


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

    # Save-source context (PR #75): set by _forced_save and recurring
    # save resolution BEFORE calling query_save_modifiers so the query
    # can apply racial trait advantages (Halfling Brave, Elf Fey
    # Ancestry, Dwarven Resilience). Cleared after the save resolves.
    # Shape:
    #   {"applied_conditions_on_fail": ["co_frightened", ...]}
    # See engine/core/racial_traits.py::build_save_context.
    current_save_context: dict | None = None

    # Content registry — lookup for condition definitions, spells, etc.
    # Set by the runner via EncounterRunner.attach_content_registry().
    # Optional: if None, condition application stores markers only (no effects fire).
    content_registry: object | None = None

    # Recurring-save callbacks registered against actor turn-end events.
    # Entries: { target_id, condition_id, source_id, ability, dc, on_success, trigger_event }
    # Resolved by runner at the appropriate turn boundary.
    recurring_saves: list = field(default_factory=list)

    # Recurring per-turn damage ticks (PR #89). Registered by spells
    # like Searing Smite (via co_ignited's effect_primitives) and
    # future ongoing-damage spells (Heat Metal, Cloudkill-on-creature
    # variants, etc.). The runner fires these at each affected
    # creature's turn-start, deals the damage, and re-registers
    # the entry for next turn.
    # Entry shape:
    #   {
    #     "target_id": "goblin_1",
    #     "source_id": "paladin",       # caster (for concentration cleanup)
    #     "source_action_id": "a_searing_smite",
    #     "dice": "1d6",
    #     "damage_type": "fire",
    #     "trigger_event": "target_turn_start",
    #     "applied_at_round": 3,
    #   }
    # Concentration-end scrubs entries whose source_id + source_action_id
    # match the dropped spell (see engine.core.concentration.
    # end_concentration). Condition-removal scrubs entries whose
    # condition_id matches when the host condition ends (e.g., co_ignited
    # via a save-to-end action, or via spell-targeted condition removal).
    recurring_damage: list = field(default_factory=list)

    # Recurring per-turn temp HP grants (PR #94). The dual of
    # recurring_damage — registered by spells like Heroism that grant
    # temp HP at the start of each of the target's turns. Runner
    # fires entries via _resolve_recurring_temp_hp at the target's
    # turn-start. Concentration-end scrubs entries tied to the spell.
    # Entry shape:
    #   {
    #     "target_id": "fighter_1",
    #     "source_id": "paladin",       # caster (for concentration cleanup)
    #     "source_action_id": "a_heroism",
    #     "amount": 3,                  # temp HP granted per tick
    #     "trigger_event": "target_turn_start",
    #     "applied_at_round": 2,
    #   }
    recurring_temp_hp: list = field(default_factory=list)

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

    # Barriers / walls (positional-barrier system). Each entry is an
    # engine.core.geometry.Wall — a Foundry-WallDocument-shaped segment
    # with move/sight/sound/light blocking channels + a `flags` provenance
    # bag (source_action_id, caster_id). Consumed by movement
    # (move_toward / push_creature), single-target line-of-effect
    # (_attack_roll + candidate generation), and AoE occlusion
    # (_resolve_save_targets + offensive_ehp_aoe). Wall of Force is the
    # canonical consumer. An empty list (the default) means open
    # battlefield — every barrier-aware code path is gated on this being
    # non-empty, so a wall-free encounter behaves exactly as before.
    # Concentration-end scrubs walls whose flags match the dropped spell
    # (caster_id + action_id), mirroring persistent_auras.
    walls: list = field(default_factory=list)

    # Conditions that auto-expire at the SOURCE actor's next turn-start
    # (e.g., Monk Stunning Strike's Stunned — "until the start of your
    # next turn"). Each entry: {target_id, condition_id, source_id}.
    # The runner scrubs matching entries at the source's turn_start.
    timed_conditions: list = field(default_factory=list)

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
