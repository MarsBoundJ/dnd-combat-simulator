"""Legendary Actions — extra actions a legendary creature takes between
other creatures' turns.

RAW (SRD 5.2.1): a legendary creature has a pool of Legendary Action uses
(typically 3). "Immediately after another creature's turn ends, the
[creature] can expend a use to take one of the following actions." Spent
uses are regained at the start of the creature's turn. One option is taken
per trigger; an option may cost more than one use.

Stat-block shape (monster schema `legendary_actions`):

    legendary_actions:
      uses_per_round: 3
      options:
        - id: a_la_tail_attack
          name: Tail Attack
          type: weapon_attack
          # cost: 1   (optional; default 1)
          pipeline: [...]
        - id: a_la_wing
          name: Wing Attack
          type: aoe_attack
          cost: 2
          area: {...}
          pipeline: [...]

Modeling:
  - The use pool lives on the actor as the resource
    `legendary_actions_remaining` (seeded by cli._build_actor from
    `uses_per_round`, reset to `uses_per_round` at the creature's own
    turn start by the runner).
  - After each creature's turn ends, the runner
    (_resolve_legendary_actions) gives every OTHER eligible legendary
    creature a window to spend ONE use (RAW "a use" per trigger).
  - Selection reuses the normal decision machinery: the legendary
    `options` are temporarily exposed as the actor's slot-'action'
    actions and run through generate_candidates → score → select →
    execute, so range / cover / recharge filtering and eHP scoring all
    apply for free. Options costing more than the remaining budget are
    withheld.

v1 scope / deferrals:
  - One option per window (the RAW singular "a use" reading). The pool
    still spreads across the round because every other creature's
    turn-end is a fresh window.
  - Movement-only options (no target) tend to score 0 and are skipped —
    v1 favors offensive legendary actions. A positional "reposition then
    attack" option is deferred with the movement system.
  - Lair Actions (initiative-20 environmental effects) are a separate
    mechanic, not modeled here.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState

RESOURCE_KEY = "legendary_actions_remaining"
_COOLDOWN_KEY = "la_used_this_round"


def configured(template: dict) -> dict | None:
    """Return the `legendary_actions` block if the template has usable
    options, else None."""
    block = (template or {}).get("legendary_actions") or None
    if not block:
        return None
    if not block.get("options"):
        return None
    return block


def uses_per_round(template: dict) -> int:
    block = configured(template) or {}
    return int(block.get("uses_per_round", 0) or 0)


def option_cost(option: dict) -> int:
    """Use cost of a legendary option (default 1)."""
    return max(1, int(option.get("cost", 1) or 1))


def remaining(actor: Actor) -> int:
    return int(actor.resources.get(RESOURCE_KEY, 0))


def reset_budget(actor: Actor, state: CombatState) -> None:
    """Regain all Legendary Action uses — called at the creature's own
    turn start. No-op for non-legendary creatures."""
    block = configured(actor.template)
    if block is None:
        return
    full = int(block.get("uses_per_round", 0) or 0)
    if full <= 0:
        return
    before = actor.resources.get(RESOURCE_KEY)
    actor.resources[RESOURCE_KEY] = full
    actor.resources[_COOLDOWN_KEY] = set()
    if before != full:
        state.event_log.append({
            "event": "legendary_actions_reset",
            "actor": actor.id, "uses": full,
        })


def is_eligible(actor: Actor) -> bool:
    """A creature can take a legendary action only if it's alive, not
    fled, has uses left, and isn't Incapacitated (RAW: a creature can't
    take legendary actions while Incapacitated)."""
    if not actor.is_alive() or getattr(actor, "is_fled", False):
        return False
    if remaining(actor) <= 0:
        return False
    if configured(actor.template) is None:
        return False
    if any(c.get("condition_id") == "co_incapacitated"
            for c in actor.applied_conditions):
        return False
    return True


def affordable_options(actor: Actor) -> list[dict]:
    """The legendary options the actor can currently pay for, each tagged
    `slot: 'action'` so generate_candidates will enumerate it.

    Options with `once_per_round: true` that were already used this
    round (tracked in the actor's `la_used_this_round` set) are
    excluded — RAW "can't take this action again until the start of
    its next turn."
    """
    block = configured(actor.template)
    if block is None:
        return []
    budget = remaining(actor)
    cooldowns = actor.resources.get(_COOLDOWN_KEY) or set()
    out = []
    for opt in block.get("options") or []:
        if option_cost(opt) > budget:
            continue
        if opt.get("once_per_round") and opt.get("id") in cooldowns:
            continue
        out.append(dict(opt, slot="action"))
    return out


def consume(actor: Actor, option: dict, state: CombatState) -> None:
    """Spend an option's cost from the actor's Legendary Action pool.
    If the option has `once_per_round`, mark it on cooldown."""
    cost = option_cost(option)
    actor.resources[RESOURCE_KEY] = max(0, remaining(actor) - cost)
    if option.get("once_per_round"):
        cooldowns = actor.resources.get(_COOLDOWN_KEY)
        if cooldowns is None:
            cooldowns = set()
            actor.resources[_COOLDOWN_KEY] = cooldowns
        cooldowns.add(option.get("id"))
    state.event_log.append({
        "event": "legendary_action_used",
        "actor": actor.id,
        "option": option.get("id"),
        "cost": cost,
        "remaining": actor.resources[RESOURCE_KEY],
    })
