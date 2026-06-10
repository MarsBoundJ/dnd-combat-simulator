"""College of Valor (Bard subclass, PHB 2024).

Combat Inspiration (L3)
-----------------------
The Valor Bard's BI die is tagged `combat_inspiration: True` in its
modifier params at grant time (see _grant_bardic_inspiration in
primitives.py). Two hooks in the attack pipeline consume the tag:

  Defense — maybe_defend_with_combat_inspiration, called from _attack_roll
  in primitives.py immediately after the regular BI maybe_add_to_attack
  call. If the attack would hit and the die's max roll could push AC above
  the total, the die is spent and effective_ac increases.  The caller re-
  evaluates is_hit against the new effective_ac.

  Offense — maybe_add_combat_inspiration_to_damage, called from _damage in
  primitives.py in the on-hit rider section (alongside Sneak Attack, Divine
  Smite, etc.). Spends the die on the first hit; adds the roll to `total`.

v1 always uses the die optimally and does not consume the Reaction slot
(automatic-optimal-play model, matching how Sneak Attack fires).

Extra Attack (L6)
-----------------
Handled by the shared f_extra_attack marker: pc_schema._extra_attack_count()
builds the multiattack action when the feature is in features_known and
class_id == "c_bard".

Battle Magic (L14)
------------------
pipeline.execute() sets actor.actions_used_this_turn["battle_magic_triggered"]
after any completed spell action. pc_schema builds an a_battle_magic_attack
bonus-action weapon attack tagged requires_battle_magic: True.
pipeline.generate_candidates() gates it on the flag.
"""
from __future__ import annotations

import random

from engine.core.state import Actor, CombatState


def has_combat_inspiration(actor: Actor) -> bool:
    return "f_combat_inspiration" in (
        actor.template.get("features_known") or [])


def has_battle_magic(actor: Actor) -> bool:
    return "f_battle_magic" in (
        actor.template.get("features_known") or [])


def maybe_defend_with_combat_inspiration(
        target: Actor, total: int, effective_ac: int,
        is_crit: bool, state: CombatState,
        rng: random.Random) -> int:
    """Spend a Combat Inspiration die (if held) to raise the target's AC
    against an incoming hit.

    Returns the (possibly increased) effective_ac.

    No-ops when:
      - attack is a critical hit (crits ignore AC per RAW)
      - attack already misses (die would be wasted)
      - target holds no BI die with combat_inspiration tag
      - the die can't close the gap even at its maximum roll
    """
    from engine.core.bardic_inspiration import (
        find_inspiration_die, clear_inspiration_die, die_max)
    if is_crit or total < effective_ac:
        return effective_ac
    marker = find_inspiration_die(target)
    if marker is None:
        return effective_ac
    if not (marker.get("params") or {}).get("combat_inspiration"):
        return effective_ac
    die = (marker.get("params") or {}).get("die", "d6")
    if total >= effective_ac + die_max(die):
        return effective_ac  # can't help even at max roll — keep die
    roll = rng.randint(1, die_max(die))
    new_ac = effective_ac + roll
    clear_inspiration_die(target)
    state.event_log.append({
        "event": "combat_inspiration_defense",
        "reactor": target.id,
        "die": die,
        "roll": roll,
        "old_ac": effective_ac,
        "new_ac": new_ac,
        "total": total,
        "result": "miss" if total < new_ac else "hit",
    })
    return new_ac


def maybe_add_combat_inspiration_to_damage(
        actor: Actor, hit: bool, state: CombatState,
        rng: random.Random) -> int:
    """Spend a Combat Inspiration die (if held) and add the roll to damage
    after the attacker confirms a hit.

    Returns the damage bonus (0 if not spent).
    """
    from engine.core.bardic_inspiration import (
        find_inspiration_die, clear_inspiration_die, die_max)
    if not hit:
        return 0
    marker = find_inspiration_die(actor)
    if marker is None:
        return 0
    if not (marker.get("params") or {}).get("combat_inspiration"):
        return 0
    die = (marker.get("params") or {}).get("die", "d6")
    roll = rng.randint(1, die_max(die))
    clear_inspiration_die(actor)
    state.event_log.append({
        "event": "combat_inspiration_offense",
        "actor": actor.id,
        "die": die,
        "roll": roll,
    })
    return roll
