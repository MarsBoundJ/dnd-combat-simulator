"""Monk on-hit strike riders — Stunning Strike + Open Hand Technique.

Both fire from `_damage` on the Monk's qualifying melee hit, once per
turn:

- **Stunning Strike** (Monk L5): spend 1 Focus Point; the target makes a
  CON save vs the Monk's save DC (8 + WIS + PB) or has the Stunned
  condition until the start of the Monk's next turn (registered as a
  source-timed condition so the runner auto-expires it). On a success
  RAW also halves the target's Speed + grants advantage against it —
  deferred (the stun is the load-bearing effect).

- **Open Hand Technique** (Warrior of the Open Hand L3): Topple — the
  target makes a DEX save vs the Monk's save DC or is knocked Prone.
  v1 fires once per turn on any unarmed/Monk-weapon hit; RAW gates it to
  Flurry-of-Blows attacks specifically (flurry-source detection through
  the multiattack path is deferred). Push + Addle options are deferred;
  Topple (Prone) is the modeled effect.

Eligibility is stamped on the Monk's template at PC build
(`has_stunning_strike`, `has_open_hand`). Once-per-turn dedup uses
Actor attrs reset in CombatState.reset_turn.
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState


def monk_save_dc(attacker: Actor) -> int:
    """Monk Focus save DC = 8 + WIS modifier + proficiency bonus."""
    wis = (attacker.abilities.get("wis") or {}).get("score", 10)
    pb = int((attacker.template.get("cr") or {}).get("proficiency_bonus", 2))
    return 8 + (wis - 10) // 2 + pb


def _melee_hit(attack_params: dict | None) -> bool:
    return (attack_params or {}).get("kind", "melee") == "melee"


def _fire_save(attacker: Actor, target: Actor, state: CombatState,
                 ability: str, dc: int, condition_id: str) -> bool:
    """Fire a save on the target; on fail apply `condition_id`. Returns
    True if the target FAILED (condition applied)."""
    from engine.primitives import _forced_save
    from engine.core.smite_rider import _NoOpBus
    result = _forced_save({
        "ability": ability,
        "dc": int(dc),
        "affected": "current_target",
        "on_fail": [
            {"primitive": "apply_condition",
              "params": {"condition_id": condition_id}},
        ],
        "on_success": [],
    }, state, _NoOpBus())
    rolls = result.get("rolls") or []
    return bool(rolls and rolls[0].get("outcome") == "fail")


def try_apply_stunning_strike(attacker: Actor, target: Actor,
                                state: CombatState,
                                attack_params: dict | None,
                                rng: random.Random) -> None:
    """Stunning Strike: on a qualifying melee hit, if the Monk has Focus
    Points and hasn't used it this turn, spend 1 and force a CON save or
    Stun the target until the Monk's next turn."""
    if not (attacker.template or {}).get("has_stunning_strike"):
        return
    if not _melee_hit(attack_params):
        return
    if getattr(attacker, "_stunning_strike_used_this_turn", False):
        return
    if int((attacker.resources or {}).get("focus_points_remaining", 0)) <= 0:
        return
    attacker.resources["focus_points_remaining"] -= 1
    attacker._stunning_strike_used_this_turn = True
    state.event_log.append({
        "event": "stunning_strike_attempt", "attacker": attacker.id,
        "target": target.id,
        "focus_remaining": attacker.resources["focus_points_remaining"]})
    failed = _fire_save(attacker, target, state, "constitution",
                          monk_save_dc(attacker), "co_stunned")
    if failed:
        # Stunned until the start of the Monk's next turn.
        state.timed_conditions.append({
            "target_id": target.id, "condition_id": "co_stunned",
            "source_id": attacker.id})


def try_apply_open_hand(attacker: Actor, target: Actor,
                          state: CombatState, attack_params: dict | None,
                          rng: random.Random) -> None:
    """Open Hand Technique (Topple): on a qualifying melee hit, once per
    turn, force a DEX save or knock the target Prone. No Focus cost."""
    if not (attacker.template or {}).get("has_open_hand"):
        return
    if not _melee_hit(attack_params):
        return
    if getattr(attacker, "_open_hand_used_this_turn", False):
        return
    attacker._open_hand_used_this_turn = True
    state.event_log.append({
        "event": "open_hand_technique", "attacker": attacker.id,
        "target": target.id, "effect": "topple"})
    _fire_save(attacker, target, state, "dexterity",
                monk_save_dc(attacker), "co_prone")
    # Prone persists until the target stands (no timed expiry).
