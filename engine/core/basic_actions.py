"""Built-in basic actions — Dodge and Disengage implicit on every actor.

Per RAW: every creature has the basic combat actions (Dodge, Disengage,
Help, Hide, Ready, Use an Object, Search) available regardless of their
stat block. Most templates don't declare them explicitly because the
AI usually prefers attacking; built-ins ensure they're in the candidate
pool for the rare cases where they're the right choice.

This v1 ships Dodge + Disengage (the two action types that already exist
as primitives in the engine). Help / Hide will land as separate small PRs
once their action types are wired.

**Usage:** `generate_candidates` calls `built_in_actions_for(actor, slot)`
and appends the result to the actor's per-slot action list before the
existing per-action loop. Built-ins are skipped if the actor's template
already declares an action of that type — avoids duplicate candidates
when a fixture explicitly opts into the action.

**v1 scope:**
  - Dodge + Disengage on the main slot for all actors (PC + monster)
  - Skips if the actor has an explicit declaration of that type
  - No bonus-slot built-ins (Dodge/Disengage are full Actions per RAW)

**Deferred:**
  - Help / Hide (need their action types first)
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
    if state is not None:
        if not actor_in_any_enemy_threat_range(actor, state):
            return []
        # Skip built-ins if the actor has no in-reach attack option but
        # CAN move — otherwise they'd Dodge in place instead of closing
        # distance. This preserves the "no candidates → move to engage"
        # runner path for actors that need to engage.
        if _actor_should_move_instead(actor, state):
            return []
    template_actions = (actor.template.get("actions") or [])
    out: list[dict] = []
    if not _has_explicit_dodge(template_actions):
        out.append(BUILT_IN_DODGE)
    if not _has_explicit_disengage(template_actions):
        out.append(BUILT_IN_DISENGAGE)
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


# ============================================================================
# Self-target detection (used by pipeline candidate gen to dedup self-buffs)
# ============================================================================

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
        if prim not in ("attack_modifier", "save_modifier"):
            continue
        params = step.get("params") or {}
        if params.get("target") == "self":
            return True
    return False
