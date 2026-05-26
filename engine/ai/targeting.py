"""Targeting dial — 5 presets per pillars-reconciliation.md §5.3.

Each preset is a pure function: given an actor and a list of valid
enemies, return the preferred target (or None if no valid targets).

Universal modifiers (per §5.3):
  - Finish-off rule — for INT ≥ 4, deviate to attack near-death target
    (HP_remaining < 15%) if reachable. Applied across all presets except
    mindless.
  - Focus-fire flag — if archetype has focus_fire=True AND last_target
    is still valid, prefer continuing on them.

v1 simplifications:
  - No reachability filter (positions are (0,0)); all enemies considered reachable.
  - Focus-fire flag tracking deferred (no last_target on Actor yet).
  - "Most dangerous" threat heuristic uses observable proxies: highest
    CR, highest visible attack bonus, plus visible spellcaster signal.
  - "Optimal eHP" degrades to caster_first behavior — full eHP joint
    optimization is deferred until eHP scoring lands.
"""
from __future__ import annotations

from typing import Callable

from engine.core.state import Actor, CombatState


TARGETING_PRESETS = (
    "closest_enemy",
    "weakest_target",
    "most_dangerous",
    "caster_first",
    "optimal_ehp",
)


# Near-death threshold for the universal finish-off rule (HP_remaining %)
FINISH_OFF_THRESHOLD = 0.15

# INT cutoff for the finish-off rule — mindless creatures (INT 1-3) don't
# have the awareness; INT 4+ do.
FINISH_OFF_INT_CUTOFF = 4


def pick_target(actor: Actor, enemies: list[Actor], state: CombatState,
                 preset: str) -> Actor | None:
    """Pick the actor's preferred target given a targeting-dial preset.

    Returns None if no valid enemies are alive.
    """
    living = [e for e in enemies if e.is_alive()]
    if not living:
        return None

    # Universal finish-off rule (per §5.3) — applies across all non-mindless presets
    if preset != "closest_enemy" or _actor_int(actor) >= FINISH_OFF_INT_CUTOFF:
        near_death = [e for e in living
                       if e.hp_max > 0 and (e.hp_current / e.hp_max) < FINISH_OFF_THRESHOLD]
        if near_death and _actor_int(actor) >= FINISH_OFF_INT_CUTOFF:
            # Pick the most-finished-off (closest to dead)
            return min(near_death, key=lambda e: e.hp_current)

    handler = _PRESET_HANDLERS.get(preset)
    if handler is None:
        # Unknown preset — fall back to closest
        return _closest_enemy(actor, living, state)
    return handler(actor, living, state)


# ============================================================================
# Preset implementations
# ============================================================================

def _closest_enemy(actor: Actor, enemies: list[Actor],
                    state: CombatState) -> Actor:
    """Pick the nearest living enemy by grid distance.

    Ties broken by turn-order index (earlier-in-init wins) for
    determinism — important since same-distance ties are common in
    open-battlefield fixtures where multiple enemies share a side.
    """
    from engine.core.geometry import distance_ft
    turn_idx = {aid: i for i, aid in enumerate(state.turn_order or [])}
    return min(enemies,
                key=lambda e: (distance_ft(actor, e),
                                turn_idx.get(e.id, 999)))


def _weakest_target(actor: Actor, enemies: list[Actor],
                     state: CombatState) -> Actor:
    """Pick the enemy with the lowest current HP. 'Bullies the wounded.'"""
    return min(enemies, key=lambda e: e.hp_current)


def _most_dangerous(actor: Actor, enemies: list[Actor],
                     state: CombatState) -> Actor:
    """Pick the enemy with the highest perceived threat.

    Threat heuristic (observable proxies — actor doesn't 'cheat' with full
    stat-block introspection):
      - Highest CR (a rough strength signal)
      - Highest attack bonus on any of its actions
      - Apparent spellcasting (any spellcasting action or trait)
    """
    return max(enemies, key=lambda e: _threat_score(e))


def _caster_first(actor: Actor, enemies: list[Actor],
                   state: CombatState) -> Actor:
    """Pick the most threatening spellcaster; fall back to most_dangerous."""
    spellcasters = [e for e in enemies if _is_spellcaster(e)]
    if spellcasters:
        # Among spellcasters, prefer the most threatening one
        return max(spellcasters, key=lambda e: _threat_score(e))
    # No spellcasters visible — fall back to most_dangerous
    return _most_dangerous(actor, enemies, state)


def _optimal_ehp(actor: Actor, enemies: list[Actor],
                  state: CombatState) -> Actor:
    """Joint (target × ability) eHP optimization.

    **v1 fallback:** without the full eHP scoring framework, this
    degrades to caster_first behavior. Real implementation lands when
    eHP scoring + behavioral coefficients are wired into score_candidates.
    Documented limitation.
    """
    return _caster_first(actor, enemies, state)


_PRESET_HANDLERS: dict[str, Callable[..., Actor]] = {
    "closest_enemy": _closest_enemy,
    "weakest_target": _weakest_target,
    "most_dangerous": _most_dangerous,
    "caster_first": _caster_first,
    "optimal_ehp": _optimal_ehp,
}


# ============================================================================
# Helpers
# ============================================================================

def _actor_int(actor: Actor) -> int:
    """Return the actor's Intelligence score (default 10)."""
    return actor.abilities.get("int", {}).get("score", 10)


def _threat_score(enemy: Actor) -> float:
    """Heuristic threat score from observable signals on the enemy's template.

    Components:
      - CR value (×10 weight)
      - Max attack bonus across actions (×2)
      - +5 bonus if it has any spellcasting indicator
    """
    template = enemy.template or {}
    cr = (template.get("cr") or {}).get("value", 0)
    score = cr * 10
    actions = template.get("actions") or []
    max_attack_bonus = 0
    for action in actions:
        for step in action.get("pipeline") or []:
            if step.get("primitive") == "attack_roll":
                bonus = (step.get("params") or {}).get("bonus", 0)
                max_attack_bonus = max(max_attack_bonus, bonus)
    score += max_attack_bonus * 2
    if _is_spellcaster(enemy):
        score += 5
    return score


def _is_spellcaster(enemy: Actor) -> bool:
    """Detect spellcaster status from observable signals on the template.

    Observable proxies (a creature doesn't 'cheat' by reading mental stats):
      - Has a spellcasting action / trait
      - Template declares a spellcasting block (e.g., from c_wizard class)
      - Has any action with type=spellcasting
    """
    template = enemy.template or {}
    if template.get("spellcasting"):
        return True
    actions = template.get("actions") or []
    for action in actions:
        if action.get("type") in ("spellcasting", "cast_spell"):
            return True
        # Also check the action name as a fallback heuristic
        name = (action.get("name") or "").lower()
        if "spellcasting" in name or "cast " in name:
            return True
    traits = template.get("traits") or []
    for trait in traits:
        name = (trait.get("name") or "").lower()
        if "spellcasting" in name:
            return True
    return False
