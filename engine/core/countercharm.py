"""Countercharm — Bard L7 (SRD CC v5.2.1 / PHB 2024).

RAW: "If you or a creature within 30 feet of you fails a saving throw against
an effect that applies the Charmed or Frightened condition, you can take a
Reaction to cause the save to be rerolled, and the new roll has Advantage."

Engine modeling: an inline save-reroll hook (the same shape as the Barbarian
Zealot's Fanatical Focus). After a creature fails a forced save whose on_fail
would apply Charmed or Frightened, a Bard with Countercharm — the failing
creature itself OR an ally within 30 ft — may spend its Reaction to reroll
the save with Advantage. The hook lives in primitives._forced_save and fires
before Legendary Resistance (so a monster could still LR the rerolled fail).
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState

_CHARM_FRIGHT = frozenset({"co_charmed", "co_frightened"})

_SHORT = {"strength": "str", "dexterity": "dex", "constitution": "con",
          "intelligence": "int", "wisdom": "wis", "charisma": "cha"}


def has_countercharm(actor: Actor) -> bool:
    """True if the actor has Countercharm (Bard L7+)."""
    features = (actor.template or {}).get("features_known") or []
    return "f_countercharm" in features


def _save_applies_charm_or_fright(params: dict) -> bool:
    """True if the forced save's on_fail would apply Charmed or Frightened."""
    for sub in params.get("on_fail") or []:
        if sub.get("primitive") == "apply_condition":
            cid = (sub.get("params") or {}).get("condition_id")
            if cid in _CHARM_FRIGHT:
                return True
    return False


def _find_reactor(target: Actor, state: CombatState) -> Actor | None:
    """Find a Bard who can Countercharm for `target`: the target itself, or
    an ally within 30 ft, with Countercharm and a Reaction available."""
    from engine.core.geometry import distance_ft
    for a in state.encounter.actors:
        if not has_countercharm(a) or not a.is_alive():
            continue
        if a.actions_used_this_turn.get("reaction"):
            continue
        if a.id == target.id:
            return a
        # "a creature within 30 feet" — restricted to allies for the sim
        # (you wouldn't free an enemy from a charm/fright your side applied).
        if a.side == target.side and distance_ft(a.position, target.position) <= 30:
            return a
    return None


def try_countercharm_reroll(target: Actor, ability: str, dc: int,
                              params: dict, rng: random.Random,
                              state: CombatState) -> tuple:
    """If `target` just failed a charm/fright save and an eligible Bard can
    Countercharm, spend that Bard's Reaction and reroll the save with
    Advantage. Returns (new_d20, new_total, new_outcome) or (None, None, None)."""
    if not _save_applies_charm_or_fright(params):
        return None, None, None
    reactor = _find_reactor(target, state)
    if reactor is None:
        return None, None, None

    reactor.actions_used_this_turn["reaction"] = True
    short = _SHORT.get(ability, ability[:3])
    save_bonus = int((target.abilities.get(short) or {}).get("save", 0))
    d20 = max(rng.randint(1, 20), rng.randint(1, 20))   # Advantage
    total = d20 + save_bonus
    outcome = "success" if total >= dc else "fail"

    state.event_log.append({
        "event": "countercharm",
        "reactor": reactor.id,
        "target": target.id,
        "ability": ability,
        "dc": dc,
        "d20": d20,
        "save_bonus": save_bonus,
        "total": total,
        "outcome": outcome,
    })
    return d20, total, outcome
