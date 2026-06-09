"""Built-in basic actions — Dodge and Disengage implicit on every actor.

Per RAW: every creature has the basic combat actions (Dodge, Disengage,
Help, Hide, Ready, Use an Object, Search) available regardless of their
stat block. Most templates don't declare them explicitly because the
AI usually prefers attacking; built-ins ensure they're in the candidate
pool for the rare cases where they're the right choice.

This module ships Dodge + Disengage + Help — the three basic actions
whose mechanics map cleanly onto existing engine primitives. **Hide is
deferred until a terrain / cover / line-of-sight layer exists** — Hide
RAW requires heavy obscurement or total cover to break LOS from
observers, and `geometry.py` is bare positions with no occlusion. See
`docs/engine-capabilities.md` §7.

**Usage:** `generate_candidates` calls `built_in_actions_for(actor, slot)`
and appends the result to the actor's per-slot action list before the
existing per-action loop. Built-ins are skipped if the actor's template
already declares an action of that type — avoids duplicate candidates
when a fixture explicitly opts into the action.

**Scope:**
  - Dodge + Disengage + Help on the main slot for all actors (PC + monster)
  - Skips if the actor has an explicit declaration of that type
  - No bonus-slot built-ins (Dodge/Disengage/Help are full Actions per RAW)

**Deferred:**
  - Hide as a built-in action (PR #48 shipped Hide as a declarable
    action type — actors with `type: hide` in their template can
    take it. Making it implicitly available to everyone is a small
    follow-up; current behavior matches RAW since only actors
    explicitly trained in stealth typically declare it.)
  - Ready / Use an Object / Search
  - Dodge ineligibility (Incapacitated / speed=0 prevents Dodge)
  - Built-in actions for bonus slot (e.g., off-hand attack for two-weapon)
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState


# Built-in Dodge: matches an explicit Dodge declaration from PR #26.
# `defensive_buff` type with target: self attack-modifier (disadvantage
# for attackers) + DEX save advantage. Lifetime expires at owner's next
# turn-start via the existing modifier-expiry system.
BUILT_IN_DODGE = {
    "id": "_builtin_dodge",
    "name": "Dodge (built-in)",
    "type": "defensive_buff",
    "defensive_buff_rounds": 1,    # Dodge lasts 1 round per RAW
    "pipeline": [
        {"primitive": "attack_modifier",
          "params": {"target": "self",
                      "modifier": "disadvantage_for_attacker",
                      "lifetime": "until_actor_next_turn_start"}},
        {"primitive": "save_modifier",
          "params": {"target": "self",
                      "modifier": "advantage",
                      "when": "save_ability == dexterity",
                      "lifetime": "until_actor_next_turn_start"}},
    ],
}


# Built-in Disengage: matches an explicit Disengage declaration from PR #26.
# Sets actor.disengaging = True for the rest of the turn (cleared by
# next reset_turn). find_oa_triggers short-circuits to [] when the
# mover is disengaging.
BUILT_IN_DISENGAGE = {
    "id": "_builtin_disengage",
    "name": "Disengage (built-in)",
    "type": "disengage",
    "pipeline": [],
}


# Built-in Search (PR #55): RAW 2024 Search action. Roll a Wisdom
# (Perception) check vs a hider's Stealth total. On success, the hider
# is revealed — `_execute_search` in pipeline.py scrubs their Hide-
# source co_invisible. v1 reveal model is "spotted means spotted"
# (one mutation; the Invisible scrub applies for all observers); per-
# observer `spotted_by:` tracking deferred.
#
# This is the first non-damage information action. AI scoring would
# need a real eHP value (probability_of_reveal * DPR_unlocked); v1
# uses gated emission instead — Search is only emitted when there's
# at least one Hide-source-hidden enemy nearby whose stealth_total
# beats the observer's passive Perception (otherwise the auto-spot
# from PR #51 would have already revealed them).
BUILT_IN_SEARCH = {
    "id": "_builtin_search",
    "name": "Search (built-in)",
    "type": "search",
    "pipeline": [],    # _execute_search in pipeline.py handles dispatch
}


# Built-in Help: matches an explicit Help declaration. Grants the helped
# ally advantage on their next attack roll (lifetime `per_single_attack`,
# expires after one attack). The candidate generator gates on helper
# being adjacent to at least one enemy and the chosen ally being within
# 5 ft of the helper (RAW Help requires both).
BUILT_IN_HELP = {
    "id": "_builtin_help",
    "name": "Help (built-in)",
    "type": "help",
    # PR #92: named_effect stamp lets cross-caster dedup detect a
    # prior Help on the ally + lets the source-caster-turn-start
    # scrub identify Help modifiers when the helper's turn comes
    # back around.
    "named_effect": "help",
    "pipeline": [
        # `advantage_for_self` = the owner of this modifier has advantage
        # on their OWN attack rolls. The target=ally resolution attaches
        # the modifier to the ally, so when the ally next attacks, the
        # query iterates their modifiers (as attacker) and lights up
        # advantage. The `when: attacker_is_self` gate is REQUIRED so
        # the modifier doesn't also light up when the ally is being
        # ATTACKED (a bare `advantage_for_self` fires regardless of
        # which side of the attack the owner is on — same pattern as
        # the Invisible condition in co_invisible.yaml). Plain
        # `advantage` is not recognized for attack rolls; use the
        # _for_self / _for_attacker pair.
        # PR #92: composite lifetime — expires EITHER when the ally
        # swings (per_owner_attack, consumed-on-use) OR when the
        # helper's next turn starts (until_source_caster_next_turn,
        # RAW timing window). Closes the gap where the previous
        # per_owner_attack-only lifetime let Help advantage persist
        # across multiple helper turns if the ally never swung.
        {"primitive": "attack_modifier",
          "params": {"target": "ally",
                      "when": "attacker_is_self",
                      "modifier": "advantage_for_self",
                      "lifetime": ["per_owner_attack",
                                    "until_source_caster_next_turn"]}},
    ],
}


# ============================================================================
# Public API
# ============================================================================

def built_in_actions_for(actor: Actor, slot: str,
                           state: CombatState | None = None) -> list[dict]:
    """Return basic actions implicitly available to `actor` at `slot`.

    Filters out built-ins whose action type is already declared on the
    actor's template (no duplicate candidates).

    THREAT GATE: built-in Dodge and Disengage are only generated if
    `actor` is within the threat range of at least one enemy this turn.
    Without this gate, actors with no in-range attack options would
    Dodge in place instead of closing on distant enemies (the AI would
    pick the only available candidate even if it scores 0 eHP).

    The gate is bypassed when `state` is None (legacy callers); pass
    state from the candidate generator so the gate fires.

    Bonus slot: returns []. Dodge and Disengage are full Actions per RAW.
    """
    if slot != "action":
        return []
    template_actions = (actor.template.get("actions") or [])
    out: list[dict] = []

    # Dodge / Disengage / Help: gated by threat range + move-to-engage.
    # These are reactive defensive / cooperative actions; pointless if
    # no enemy can hit you, and they shouldn't preempt the runner's
    # move-to-engage path when the actor needs to close distance.
    if state is None or (
        actor_in_any_enemy_threat_range(actor, state)
        and not _actor_should_move_instead(actor, state)
    ):
        if not _has_explicit_dodge(template_actions):
            out.append(BUILT_IN_DODGE)
        if not _has_explicit_disengage(template_actions):
            out.append(BUILT_IN_DISENGAGE)
        # Help: only inject if at least one ally is adjacent.
        if state is not None and not _has_explicit_help(template_actions):
            if _has_adjacent_ally(actor, state):
                out.append(BUILT_IN_HELP)

    # PR #55: Search — INFORMATION action, not gated by threat range.
    # The actor may be far from the hidden enemy but want to peer
    # around / search the area. Skipping it on the threat / move gates
    # would prevent the AI from Searching during the close-distance
    # turns where it's most useful. The internal
    # `_has_unspotted_hidden_enemy` gate is what filters to "Search has
    # something to find" — that's the only filter Search needs.
    if state is not None and not _has_explicit_search(template_actions):
        if _has_unspotted_hidden_enemy(actor, state):
            out.append(BUILT_IN_SEARCH)
    return out


# ============================================================================
# Threat detection — gates built-in availability
# ============================================================================

def actor_in_any_enemy_threat_range(actor: Actor,
                                       state: CombatState) -> bool:
    """True if any living enemy could attack `actor` this turn (within
    that enemy's walk_speed + max attack reach).

    Used to gate built-in Dodge / Disengage generation: dodging is
    pointless if no enemy can hit you this round, and the AI would
    waste a turn dodging in place when it should be closing distance.

    Ranged enemies count (their `range_ft` contributes to max reach).
    """
    from engine.core.geometry import distance_ft
    for enemy in state.encounter.actors:
        if enemy.id == actor.id or enemy.side == actor.side:
            continue
        if not enemy.is_alive():
            continue
        speed = int((enemy.speed or {}).get("walk", 30))
        max_reach = _max_attack_reach(enemy)
        if max_reach <= 0:
            continue   # No attacks at all → not a threat
        if distance_ft(enemy.position, actor.position) <= speed + max_reach:
            return True
    return False


def _actor_should_move_instead(actor: Actor, state: CombatState) -> bool:
    """True if the actor has movement available AND no enemy is within
    its attack reach.

    Used by `built_in_actions_for` to suppress built-in Dodge/Disengage
    when the actor needs to close on distant enemies. Otherwise built-in
    Dodge would always be a candidate, preventing the runner's
    move-to-engage path from triggering.
    """
    from engine.core.geometry import distance_ft
    speed = int((actor.speed or {}).get("walk", 30))
    if speed <= 0:
        return False   # Can't move; might as well Dodge if threatened
    max_reach = _max_attack_reach(actor)
    if max_reach == 0:
        return False   # No attacks at all (rare); built-ins are still useful
    for enemy in state.encounter.actors:
        if enemy.id == actor.id or enemy.side == actor.side:
            continue
        if not enemy.is_alive():
            continue
        if distance_ft(actor.position, enemy.position) <= max_reach:
            return False   # Has an in-reach enemy; attack normally
    return True   # No enemies in own reach AND can move — should close


def _max_attack_reach(actor: Actor) -> int:
    """Return the longest reach/range across actor's weapon_attack
    actions. 0 if no attacks (rare; pure controllers, dead creatures).
    """
    reaches: list[int] = []
    for action in (actor.template.get("actions") or []):
        if action.get("type") != "weapon_attack":
            continue
        for step in (action.get("pipeline") or []):
            if step.get("primitive") != "attack_roll":
                continue
            params = step.get("params") or {}
            if "range_ft" in params:
                reaches.append(int(params["range_ft"]))
            elif "reach_ft" in params:
                reaches.append(int(params["reach_ft"]))
    return max(reaches) if reaches else 0


# ============================================================================
# Detection helpers
# ============================================================================

def _has_explicit_dodge(actions: list[dict]) -> bool:
    """Heuristic: action with type=defensive_buff and a pipeline step
    that applies `disadvantage_for_attacker` to `target: self`.
    Captures Dodge whether declared with the canonical id or a custom one.
    """
    for action in actions:
        if action.get("type") != "defensive_buff":
            continue
        for step in (action.get("pipeline") or []):
            if step.get("primitive") != "attack_modifier":
                continue
            params = step.get("params") or {}
            if (params.get("target") == "self"
                    and params.get("modifier") == "disadvantage_for_attacker"):
                return True
    return False


def _has_explicit_disengage(actions: list[dict]) -> bool:
    """Any action with type=disengage counts as an explicit Disengage."""
    return any(a.get("type") == "disengage" for a in actions)


def _has_explicit_help(actions: list[dict]) -> bool:
    """Any action with type=help counts as an explicit Help."""
    return any(a.get("type") == "help" for a in actions)


def _has_explicit_search(actions: list[dict]) -> bool:
    """Any action with type=search counts as an explicit Search."""
    return any(a.get("type") == "search" for a in actions)


def _has_unspotted_hidden_enemy(actor: Actor, state: CombatState) -> bool:
    """True if at least one living enemy currently has a Hide-source
    co_invisible condition whose recorded stealth_total exceeds the
    actor's passive Perception (PR #55).

    Coarse gate for the built-in Search emission. If no such enemy
    exists, Search has nothing to do — PR #51's auto-spot already
    reveals any hider whose stealth_total <= observer.passive_perception.
    Skipping emission keeps the candidate pool clean.

    Sight range is not currently enforced; any hider in the encounter
    is considered. Future tightening: gate on observer's reasonable
    sight range (no senses model that yet; the existing vision
    pipeline assumes any-to-any unless blocked by a vision gate).
    """
    pp = int(getattr(actor, "passive_perception", 10) or 10)
    for enemy in state.encounter.actors:
        if enemy.id == actor.id or enemy.side == actor.side:
            continue
        if not enemy.is_alive():
            continue
        for cond in (enemy.applied_conditions or []):
            if cond.get("condition_id") != "co_invisible":
                continue
            if cond.get("source_action_id") != "a_hide":
                continue
            stealth_total = int(cond.get("stealth_total", 0))
            if stealth_total > pp:
                return True
    return False


def _has_adjacent_ally(actor: Actor, state: CombatState) -> bool:
    """True if at least one living ally (excluding self) is within 5 ft.

    Coarse gate for built-in Help. The candidate generator does the
    precise per-ally adjacency check + adjacent-enemy requirement; this
    only filters out the obvious "no allies anywhere near" case so we
    don't bloat the candidate pool with a Help action that will produce
    zero candidates downstream.
    """
    from engine.core.geometry import distance_ft
    for ally in state.encounter.actors:
        if ally.id == actor.id or ally.side != actor.side:
            continue
        if not ally.is_alive():
            continue
        if distance_ft(actor.position, ally.position) <= 5:
            return True
    return False


# ============================================================================
# Self-target detection (used by pipeline candidate gen to dedup self-buffs)
# ============================================================================

def is_self_targeted_heal(action: dict) -> bool:
    """True if the action is a heal whose primary heal step targets
    `self`. Used by `generate_candidates` to emit a single self-
    candidate instead of per-ally enumeration — Second Wind heals
    the caster only, so we shouldn't emit N redundant candidates in
    an N-ally party that all execute the same self-heal.
    """
    if action.get("type") != "heal":
        return False
    for step in (action.get("pipeline") or []):
        # `heal` (Second Wind) and `warrior_of_the_gods` (Zealot
        # dice-pool self-heal) both carry the self marker on their step.
        if step.get("primitive") not in ("heal", "warrior_of_the_gods"):
            continue
        params = step.get("params") or {}
        if params.get("target") == "self":
            return True
    return False


def is_self_targeted_defensive_buff(action: dict) -> bool:
    """True if the action is a defensive_buff whose primary modifier
    targets `self` rather than `ally`. Used by `generate_candidates` to
    emit a single self-candidate instead of per-ally enumeration —
    self-Dodge shouldn't generate N candidates for an N-ally party.
    """
    if action.get("type") != "defensive_buff":
        return False
    for step in (action.get("pipeline") or []):
        prim = step.get("primitive")
        # PR #71: Rage's rage_start primitive is inherently self-
        # targeted — the actor enters Rage on themselves. No params
        # branch needed; rage_start has no target param.
        if prim == "rage_start":
            return True
        # PR #74: Dash (used by Cunning Action) is also self-
        # targeted — affects only the actor's own movement budget.
        if prim == "dash":
            return True
        # Wild Heart Eagle Bound — self-targeted Dash + Disengage grant.
        if prim == "eagle_bound":
            return True
        # World Tree Travel along the Tree — self-targeted teleport.
        if prim == "travel_teleport":
            return True
        # Glamour Mantle of Inspiration — fans Temp HP out to chosen allies
        # internally, so it emits ONE candidate (not one-per-ally).
        if prim == "mantle_of_inspiration":
            return True
        # Glamour Unbreakable Majesty — self-targeted presence activation.
        if prim == "unbreakable_majesty_activate":
            return True
        # PR #80: Steady Aim — self-targeted advantage on next
        # attack + speed 0. Same self-targeted pattern.
        if prim == "steady_aim":
            return True
        # PR #96: Armor of Agathys arms the caster (self-buff). Its
        # pipeline pairs temp_hp_grant(self) + armor_of_agathys_arm;
        # the marker primitive is the unambiguous self signal.
        if prim == "armor_of_agathys_arm":
            return True
        # PR #99: one-shot self temp HP (False Life) + self temp HP
        # grants generally. A temp_hp_grant / hp_max_grant step with
        # target: self marks the whole action self-targeted so it
        # emits ONE candidate, not one-per-ally.
        if prim in ("temp_hp_grant", "hp_max_grant"):
            params = step.get("params") or {}
            if params.get("target") == "self":
                return True
            continue
        if prim not in ("attack_modifier", "save_modifier"):
            continue
        params = step.get("params") or {}
        if params.get("target") == "self":
            return True
    return False
