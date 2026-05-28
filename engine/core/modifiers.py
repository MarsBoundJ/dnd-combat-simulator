"""Active-modifier evaluation — the Q5 unified modifier system runtime.

Each actor has an `active_modifiers` registry (a list of modifier entries).
At attack-roll / save / damage / d20-test time, the engine queries the
registry, filters to entries whose `when` clause matches, and aggregates
their effects.

Per Q5 unification (schema-design.md §4):
  - One `attack_modifier` primitive handles modifiers from conditions
    (Blinded, Paralyzed, Restrained), spells (Shield, Bless), features,
    magic items, etc.
  - The DIFFERENCE between sources is the `lifetime` parameter, not the
    math. The engine maintains the active-modifier registry uniformly.

Modifier entry shape:
  {
    "primitive": "attack_modifier",
    "params": { "when": "target_is_self", "modifier": "advantage_for_attacker" },
    "lifetime": "until_condition_ends" | "per_single_attack" | ...,
    "source": { "type": "condition", "id": "co_blinded",
                "source_creature_id": "<id>" | None },
    "applied_at_round": N,
    "owner_id": "<actor_id>",   # which actor this modifier is attached to
  }

The `when` clause is a small boolean expression — see _eval_when().
This is skeleton-grade; a real engine has a proper expression evaluator.
"""
from __future__ import annotations

from typing import Any

from engine.core.state import Actor, CombatState


# ============================================================================
# Aggregated query results
# ============================================================================

class AttackModifierResult:
    """Aggregated attack-modifier state for a single attack."""

    def __init__(self) -> None:
        self.has_advantage: bool = False
        self.has_disadvantage: bool = False
        self.ac_modifier: int = 0
        self.attack_bonus_modifier: int = 0
        # Sources that contributed (for event logging / debugging)
        self.sources: list[dict] = []

    def net_advantage(self) -> str:
        """D&D 5e: advantage and disadvantage cancel out, even if multiple sources."""
        if self.has_advantage and self.has_disadvantage:
            return "normal"
        if self.has_advantage:
            return "advantage"
        if self.has_disadvantage:
            return "disadvantage"
        return "normal"


class SaveModifierResult:
    """Aggregated save-modifier state for a single save."""

    def __init__(self) -> None:
        self.has_advantage: bool = False
        self.has_disadvantage: bool = False
        self.auto_fail: bool = False
        self.auto_succeed: bool = False
        self.save_bonus_modifier: int = 0
        self.sources: list[dict] = []

    def net_outcome_override(self) -> str | None:
        """Returns 'auto_fail' / 'auto_succeed' / None.

        Auto-fail trumps auto-succeed (rare conflict; D&D doesn't specify
        but auto-fail is the safer assumption for the player).
        """
        if self.auto_fail:
            return "auto_fail"
        if self.auto_succeed:
            return "auto_succeed"
        return None

    def net_advantage(self) -> str:
        if self.has_advantage and self.has_disadvantage:
            return "normal"
        if self.has_advantage:
            return "advantage"
        if self.has_disadvantage:
            return "disadvantage"
        return "normal"


class CritModifierResult:
    """Aggregated crit-modifier state for a single attack."""

    def __init__(self) -> None:
        self.crit_threshold: int = 20                 # default: nat 20 only
        self.force_crit_if_hit: bool = False          # Paralyzed within 5ft etc.
        self.sources: list[dict] = []


class D20TestModifierResult:
    """Aggregated d20-test-modifier state (initiative / ability checks / etc.)."""

    def __init__(self) -> None:
        self.has_advantage: bool = False
        self.has_disadvantage: bool = False
        self.flat_modifier: int = 0                   # e.g., Exhaustion -2 × level
        self.sources: list[dict] = []

    def net_advantage(self) -> str:
        if self.has_advantage and self.has_disadvantage:
            return "normal"
        if self.has_advantage:
            return "advantage"
        if self.has_disadvantage:
            return "disadvantage"
        return "normal"


# ============================================================================
# Modifier queries
# ============================================================================

def query_attack_modifiers(
    attacker: Actor, target: Actor, state: CombatState
) -> AttackModifierResult:
    """Aggregate all attack_modifier entries on attacker + target that match."""
    result = AttackModifierResult()
    for owner, mod in _iter_relevant_modifiers([attacker, target], "attack_modifier"):
        params = mod.get("params") or {}
        when = params.get("when", "")
        if not _eval_when(when, owner=owner, attacker=attacker,
                          target=target, state=state):
            continue
        modifier_type = params.get("modifier", "")
        _apply_attack_modifier(result, modifier_type, params, mod)
    # PR #85: Reckless Attack — identity-state checks read off the
    # actor (mirrors the rage STR-saves pattern in query_save_modifiers).
    # Two arms:
    #   1. Attacker is reckless + this is a STR-melee swing → advantage
    #      on the outgoing attack. Reads the in-flight attack params
    #      from state.current_attack.action.pipeline (set when the
    #      pipeline executes the action's attack_roll step).
    #   2. Target's "grants advantage" window is open → advantage on
    #      every attack rolled against them. No attack-shape filter
    #      (RAW: "Attack rolls against you have advantage" — period).
    from engine.core import reckless_attack as _ra
    if attacker.reckless_active:
        attack_params = _extract_inflight_attack_params(state)
        if _ra.applies_self_advantage(attacker, attack_params):
            result.has_advantage = True
            result.sources.append({
                "type": "reckless_attack",
                "source_creature_id": attacker.id,
                "arm": "self_advantage",
            })
    if _ra.applies_attacker_advantage_against(target):
        result.has_advantage = True
        result.sources.append({
            "type": "reckless_attack",
            "source_creature_id": target.id,
            "arm": "grants_advantage_to_attacker",
        })
    return result


def _extract_inflight_attack_params(state: CombatState) -> dict:
    """Pull the in-flight attack's attack_roll params from
    `state.current_attack.action.pipeline`. Returns {} if there isn't
    an action recorded (e.g., direct primitive-test callers).

    Local copy of engine.primitives._extract_attack_params to avoid a
    circular import (primitives.py imports modifiers.py at module load
    time). Logic is identical and stays in lockstep with that helper.
    """
    if not state.current_attack:
        return {}
    explicit = state.current_attack.get("attack_roll_params")
    if explicit is not None:
        return dict(explicit)
    action = state.current_attack.get("action") or {}
    for step in (action.get("pipeline") or []):
        if step.get("primitive") == "attack_roll":
            return dict(step.get("params") or {})
    return {}


def query_save_modifiers(
    target: Actor, save_ability: str, state: CombatState
) -> SaveModifierResult:
    """Aggregate save_modifier entries on target that match the save ability."""
    result = SaveModifierResult()
    for owner, mod in _iter_relevant_modifiers([target], "save_modifier"):
        params = mod.get("params") or {}
        when = params.get("when", "")
        if not _eval_save_when(when, save_ability, owner, target, state):
            continue
        outcome = params.get("outcome", "")
        modifier = params.get("modifier", "")
        if outcome == "auto_fail":
            result.auto_fail = True
        elif outcome == "auto_succeed":
            result.auto_succeed = True
        elif modifier == "advantage":
            result.has_advantage = True
        elif modifier == "disadvantage":
            result.has_disadvantage = True
        elif modifier == "flat":
            result.save_bonus_modifier += params.get("value", 0)
        result.sources.append(mod.get("source") or {})
    # PR #71: Rage gives advantage on STR saves (RAW PHB 2024). Read
    # directly off Actor.rage_active rather than registering a
    # modifier at rage entry — keeps rage as an identity-state check
    # rather than a registry-managed buff with lifetime concerns.
    if getattr(target, "rage_active", False) \
            and save_ability in ("strength", "str"):
        result.has_advantage = True
        result.sources.append({"type": "rage", "source_creature_id": target.id})
    # PR #75: racial trait save advantages (Halfling Brave, Elf Fey
    # Ancestry, Dwarf Dwarven Resilience). Reads
    # state.current_save_context (set by _forced_save and recurring
    # save resolution before this query fires) to detect "this save
    # would apply condition X on failure"; if X matches the trait's
    # triggering condition AND target has the trait, grant advantage.
    from engine.core.racial_traits import racial_save_advantage_for
    racial_trait = racial_save_advantage_for(target, state)
    if racial_trait is not None:
        result.has_advantage = True
        result.sources.append({
            "type": "racial_trait",
            "trait": racial_trait,
            "source_creature_id": target.id,
        })
    return result


def query_crit_modifiers(
    attacker: Actor, target: Actor, state: CombatState
) -> CritModifierResult:
    """Aggregate crit_modifier + crit_threshold_modifier entries."""
    result = CritModifierResult()
    # crit_threshold_modifier (lowers crit range; e.g., Improved Critical: 19+)
    for owner, mod in _iter_relevant_modifiers([attacker], "crit_threshold_modifier"):
        params = mod.get("params") or {}
        new_threshold = params.get("new_threshold")
        if new_threshold and new_threshold < result.crit_threshold:
            result.crit_threshold = new_threshold
            result.sources.append(mod.get("source") or {})
    # crit_modifier (auto-crit, e.g., Paralyzed within 5ft)
    for owner, mod in _iter_relevant_modifiers([target], "crit_modifier"):
        params = mod.get("params") or {}
        when = params.get("when", "")
        if not _eval_when(when, owner=owner, attacker=attacker,
                          target=target, state=state):
            continue
        outcome = params.get("outcome", "")
        if outcome == "auto_crit":
            result.force_crit_if_hit = True
            result.sources.append(mod.get("source") or {})
    return result


def query_d20_test_modifiers(
    actor: Actor, applies_to_key: str, state: CombatState
) -> D20TestModifierResult:
    """Aggregate d20_test_modifier entries that apply to a given test type.

    applies_to_key examples: 'initiative_roll', 'all_d20_tests', 'ability_checks',
    'attack_rolls', 'death_saving_throws'.
    """
    result = D20TestModifierResult()
    for owner, mod in _iter_relevant_modifiers([actor], "d20_test_modifier"):
        params = mod.get("params") or {}
        applies_to = params.get("applies_to")
        if not _applies_to_matches(applies_to, applies_to_key):
            continue
        modifier = params.get("modifier", "")
        if modifier == "advantage":
            result.has_advantage = True
        elif modifier == "disadvantage":
            result.has_disadvantage = True
        else:
            # Flat modifier (Exhaustion: "-2 * actor.exhaustion_level")
            value = _resolve_numeric_expr(modifier, actor)
            if value is not None:
                result.flat_modifier += value
        result.sources.append(mod.get("source") or {})
    # PR #71: Rage gives advantage on Strength ability checks (PHB
    # 2024). Specific to STR — DEX/CON/INT/WIS/CHA checks unaffected.
    # Recognized applies_to keys for STR checks:
    #   - 'strength_check' (explicit)
    #   - 'ability_checks' (umbrella; STR check is a subset)
    if getattr(actor, "rage_active", False) \
            and applies_to_key in ("strength_check", "str_check"):
        result.has_advantage = True
        result.sources.append({"type": "rage", "source_creature_id": actor.id})
    return result


# ============================================================================
# Modifier lifetime management
# ============================================================================

def expire_modifiers(actor: Actor, lifetime_events: set[str]) -> int:
    """Remove modifiers whose lifetime matches any of the trigger events.

    Trigger events: 'turn_start' (clears until_actor_next_turn_start),
    'attack_complete' (clears per_single_attack — both sides of an
    attack), 'owner_made_attack' (clears per_owner_attack — only the
    attacker side), etc.

    Returns count of removed modifiers.
    """
    before = len(actor.active_modifiers)
    actor.active_modifiers = [
        m for m in actor.active_modifiers
        if not _lifetime_matches(m.get("lifetime"), lifetime_events)
    ]
    return before - len(actor.active_modifiers)


def remove_modifiers_from_source(actor: Actor, source_type: str,
                                  source_id: str,
                                  source_creature_id: str | None = None) -> int:
    """Remove modifiers added by a specific source (e.g., when a condition ends).

    Returns count of removed modifiers.
    """
    before = len(actor.active_modifiers)
    actor.active_modifiers = [
        m for m in actor.active_modifiers
        if not _source_matches(m.get("source"), source_type, source_id,
                                source_creature_id)
    ]
    return before - len(actor.active_modifiers)


# ============================================================================
# Internal helpers
# ============================================================================

def _iter_relevant_modifiers(actors: list[Actor], primitive_name: str):
    """Yield (owner, modifier_entry) for each modifier of the given primitive."""
    for actor in actors:
        for mod in actor.active_modifiers:
            if mod.get("primitive") == primitive_name:
                yield actor, mod


def _apply_attack_modifier(result: AttackModifierResult, modifier_type: str,
                            params: dict, mod: dict) -> None:
    """Mutate result to include this modifier's effect."""
    if modifier_type == "advantage_for_attacker":
        result.has_advantage = True
    elif modifier_type == "disadvantage_for_attacker":
        result.has_disadvantage = True
    elif modifier_type == "advantage_for_self":
        result.has_advantage = True
    elif modifier_type == "disadvantage_for_self":
        result.has_disadvantage = True
    elif modifier_type == "ac_modifier":
        result.ac_modifier += params.get("value", 0)
    elif modifier_type == "attack_bonus":
        result.attack_bonus_modifier += params.get("value", 0)
    result.sources.append(mod.get("source") or {})


def _lifetime_matches(lifetime: Any, trigger_events: set[str]) -> bool:
    """Does this lifetime expire on any of the given trigger events?"""
    if not lifetime:
        return False
    if isinstance(lifetime, str):
        lookup = {
            "per_single_attack": {"attack_complete"},
            # per_owner_attack: consume only when the owner of the
            # modifier was the ATTACKER (not when they were targeted).
            # Used by Help-shape buffs — modifier attached to the helped
            # ally, must persist if the ally is attacked, then consume
            # when the ally next swings.
            "per_owner_attack": {"owner_made_attack"},
            "until_actor_next_turn_start": {"turn_start"},
            "until_short_rest": {"short_rest_end"},
            "until_long_rest": {"long_rest_end"},
            # 'until_condition_ends' / 'until_spell_ends' / 'until_dispelled' —
            # handled via remove_modifiers_from_source, not by trigger events.
        }
        return bool(lookup.get(lifetime, set()) & trigger_events)
    return False


def _source_matches(source: dict | None, source_type: str, source_id: str,
                     source_creature_id: str | None) -> bool:
    """Does this modifier's source match the removal target?"""
    if not source:
        return False
    if source.get("type") != source_type:
        return False
    if source.get("id") != source_id and source.get("condition_id") != source_id:
        return False
    if source_creature_id is not None:
        if source.get("source_creature_id") != source_creature_id:
            return False
    return True


def _applies_to_matches(applies_to: Any, key: str) -> bool:
    """Does the applies_to spec from a d20_test_modifier match the test key?"""
    if applies_to is None:
        return True
    if isinstance(applies_to, str):
        if applies_to == key:
            return True
        if applies_to == "all_d20_tests":
            return True
        return False
    if isinstance(applies_to, list):
        return key in applies_to or "all_d20_tests" in applies_to
    return False


def _resolve_numeric_expr(expr: str, actor: Actor) -> int | None:
    """Resolve a tiny vocabulary of numeric expressions.

    Skeleton-grade; supports e.g., '-2 * actor.exhaustion_level',
    '5 * actor.exhaustion_level', plain ints.
    """
    expr = expr.strip()
    try:
        return int(expr)
    except (ValueError, TypeError):
        pass
    # Pattern: '<int> * actor.<field>'
    if "*" in expr and "actor." in expr:
        try:
            lhs, rhs = expr.split("*", 1)
            multiplier = int(lhs.strip())
            field = rhs.strip()[len("actor."):]
            value = actor.resources.get(field, 0)
            return multiplier * value
        except (ValueError, KeyError):
            return None
    return None


# ============================================================================
# When-clause expression evaluator
# ============================================================================

def _eval_when(expr: str, *, owner: Actor, attacker: Actor, target: Actor,
                state: CombatState) -> bool:
    """Evaluate a when-clause boolean expression.

    Supported atoms:
      - target_is_self           — owner.id == target.id
      - attacker_is_self         — owner.id == attacker.id
      - attacker_within_ft(N)    — distance(attacker, target) <= N
      - attacker_not_within_ft(N) — distance(attacker, target) > N
      - attack_hits              — current attack state is hit or crit
      - attack_target_is_not(<expr>) — target is not the referenced source

    Operators: AND, OR, NOT, parentheses (basic; not fully nested).

    Skeleton-grade: position-based checks default to TRUE since the
    skeleton uses (0,0) for everyone. Real engine needs grid math.
    """
    if not expr:
        return True
    return _eval_expr(expr.strip(), owner, attacker, target, state)


def _eval_save_when(expr: str, save_ability: str, owner: Actor, target: Actor,
                     state: CombatState) -> bool:
    """Evaluate a when-clause for a save context."""
    if not expr:
        return True
    expr = expr.strip()
    # Specific atoms for saves
    # 'save_ability IN [strength, dexterity]' or 'save_ability == X'
    if "save_ability IN [" in expr:
        list_part = expr.split("save_ability IN [", 1)[1].rstrip("]").rstrip(")")
        items = [s.strip().rstrip(",") for s in list_part.split(",")]
        return save_ability in items
    if "save_ability ==" in expr:
        target_ability = expr.split("save_ability ==", 1)[1].strip()
        return save_ability == target_ability
    # Fallback: try general evaluator with target as both attacker and target
    return _eval_expr(expr, owner, target, target, state)


def _eval_expr(expr: str, owner: Actor, attacker: Actor, target: Actor,
                state: CombatState) -> bool:
    expr = expr.strip()
    # Parentheses (single level; skeleton)
    if expr.startswith("(") and expr.endswith(")"):
        return _eval_expr(expr[1:-1].strip(), owner, attacker, target, state)
    # AND / OR / NOT (left-associative; skeleton)
    if " AND " in expr:
        left, right = expr.split(" AND ", 1)
        return _eval_expr(left, owner, attacker, target, state) and \
               _eval_expr(right, owner, attacker, target, state)
    if " OR " in expr:
        left, right = expr.split(" OR ", 1)
        return _eval_expr(left, owner, attacker, target, state) or \
               _eval_expr(right, owner, attacker, target, state)
    if expr.startswith("NOT "):
        return not _eval_expr(expr[4:], owner, attacker, target, state)
    # Atoms
    if expr == "target_is_self":
        return target.id == owner.id
    if expr == "attacker_is_self":
        return attacker.id == owner.id
    if expr == "attack_hits":
        return state.current_attack.get("state") in ("hit", "crit")
    if expr.startswith("attacker_within_ft("):
        # Parse the N parameter and check actual grid distance.
        from engine.core.geometry import distance_ft
        try:
            n = int(expr[len("attacker_within_ft("):-1].strip())
        except ValueError:
            return True  # malformed → conservative default
        return distance_ft(attacker, target) <= n
    if expr.startswith("attacker_not_within_ft("):
        from engine.core.geometry import distance_ft
        try:
            n = int(expr[len("attacker_not_within_ft("):-1].strip())
        except ValueError:
            return False
        return distance_ft(attacker, target) > n
    if expr.startswith("attack_target_is_not("):
        # Used by Grappled: target other than the grappler
        # Skeleton: True if there's any target at all
        return True
    # PR #47: vision predicates. attacker_can_see(self) and
    # target_can_see(self) — "self" refers to the modifier owner.
    # Used by co_invisible's when-clauses and (future) other
    # visibility-gated modifiers.
    if expr == "attacker_can_see(self)":
        from engine.core.vision import can_actor_see
        return can_actor_see(attacker, owner, state)
    if expr == "target_can_see(self)":
        from engine.core.vision import can_actor_see
        return can_actor_see(target, owner, state)
    # Unknown atom — log + default to False (conservative)
    return False
