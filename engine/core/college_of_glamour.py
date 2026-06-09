"""College of Glamour — Bard subclass (PHB 2024).

A Feywild-touched Bard. This module wires the combat-relevant features:

  - Mantle of Inspiration (L3): a Bonus Action that expends a Bardic
    Inspiration use, rolls the Bardic die, and grants up to CHA-mod other
    creatures within 60 ft Temp HP equal to 2× the roll (plus an optional
    Reaction move — deferred positioning).
  - Beguiling Magic (L3): immediately after the Bard casts an Enchantment or
    Illusion spell with a slot, force a WIS save (vs spell DC) on a creature
    within 60 ft → Charmed/Frightened (1 min, repeat save end of turn). 1/long
    rest (BI-refund deferred).
  - Unbreakable Majesty (L14): while the majestic presence is active, the
    first attack to hit the Bard each turn forces the attacker's CHA save vs
    the Bard's spell DC or the attack misses instead.
"""
from __future__ import annotations

from engine.core.state import Actor, CombatState, ability_modifier


def _bard_spell_dc(actor: Actor) -> int:
    """Bard spell save DC = 8 + CHA modifier + Proficiency Bonus."""
    cha = (actor.abilities.get("cha") or {}).get("score", 10)
    pb = int((actor.template.get("cr") or {}).get("proficiency_bonus", 2))
    return 8 + ability_modifier(cha) + pb


# ============================================================================
# Mantle of Inspiration (L3)
# ============================================================================

def has_mantle_of_inspiration(actor: Actor) -> bool:
    features = (actor.template or {}).get("features_known") or []
    return "f_mantle_of_inspiration" in features


def resolve_mantle_of_inspiration(actor: Actor, state: CombatState, rng) -> None:
    """Grant up to CHA-mod (min 1) other creatures within 60 ft Temp HP equal
    to 2× a Bardic die roll. The Bardic Inspiration use is consumed by the
    action's feature_use gate; this rolls the die + distributes the Temp HP.

    v1 beneficiary policy: the allies who benefit most — those with the lowest
    current Temp HP first (Temp HP doesn't stack), then the most wounded. The
    optional "each can use its Reaction to move" clause is deferred (bounded
    positioning signal)."""
    from engine.core.bardic_inspiration import die_max
    from engine.core.geometry import distance_ft
    die = str((actor.template or {}).get("bardic_die", "d6"))
    roll = rng.randint(1, die_max(die))
    temp = 2 * roll
    cha_mod = ability_modifier((actor.abilities.get("cha") or {}).get("score", 10))
    max_targets = max(1, cha_mod)

    allies = [a for a in state.encounter.actors
                if a.id != actor.id and a.side == actor.side and a.is_alive()
                and distance_ft(actor.position, a.position) <= 60]
    allies.sort(key=lambda a: (a.temp_hp, a.hp_current / max(1, a.hp_max)))
    chosen = allies[:max_targets]

    granted = []
    for a in chosen:
        if temp > a.temp_hp:
            a.temp_hp = temp
        granted.append(a.id)
    state.event_log.append({
        "event": "mantle_of_inspiration",
        "actor": actor.id,
        "die": die, "roll": roll, "temp_hp": temp,
        "beneficiaries": granted,
    })


# ============================================================================
# Beguiling Magic (L3) — post-Enchantment/Illusion control rider
# ============================================================================

_ENCH_ILLUSION = frozenset({"enchantment", "illusion"})


def has_beguiling_magic(actor: Actor) -> bool:
    features = (actor.template or {}).get("features_known") or []
    return "f_beguiling_magic" in features


def try_beguiling_magic(actor: Actor, action: dict, state: CombatState,
                          bus) -> None:
    """Immediately after the Bard casts an Enchantment or Illusion spell with
    a slot, force a WIS save on the lowest-WIS-save enemy within 60 ft → on a
    failure, Charmed or Frightened (1 min, repeat save at end of turn). Once
    per Long Rest, tracked via beguiling_magic_uses_remaining.

    v1: Charmed is chosen (removes the enemy from the fight like Frightened but
    is the canonical pick); the BI-refund of the use is deferred."""
    if not has_beguiling_magic(actor):
        return
    school = str(action.get("school", "")).lower()
    if school not in _ENCH_ILLUSION:
        return
    if int(action.get("spell_slot_level", 0)) < 1:
        return   # "using a spell slot" — cantrips don't qualify
    if int(actor.resources.get("beguiling_magic_uses_remaining", 0)) <= 0:
        return
    from engine.core.geometry import distance_ft
    enemies = [e for e in state.encounter.actors
                if e.side != actor.side and e.is_alive()
                and distance_ft(actor.position, e.position) <= 60]
    if not enemies:
        return
    target = min(enemies,
                  key=lambda e: (e.abilities.get("wis") or {}).get("save", 0))
    actor.resources["beguiling_magic_uses_remaining"] = int(
        actor.resources.get("beguiling_magic_uses_remaining", 0)) - 1

    dc = _bard_spell_dc(actor)
    state.event_log.append({
        "event": "beguiling_magic", "actor": actor.id, "target": target.id,
        "school": school, "dc": dc, "condition": "co_charmed"})
    from engine.primitives import _forced_save
    saved = state.current_attack
    state.current_attack = {"actor": actor, "target": target, "state": None,
                             "had_advantage": False, "had_disadvantage": False}
    try:
        _forced_save({
            "ability": "wisdom", "dc": dc, "affected": "current_target",
            "on_fail": [
                {"primitive": "apply_condition",
                 "params": {"condition_id": "co_charmed",
                            "duration": "until_spell_ends"}},
                {"primitive": "recurring_save",
                 "params": {"ability": "wisdom", "dc": dc,
                            "trigger_event": "target_turn_end",
                            "on_success": "end_spell_on_target",
                            "condition_id": "co_charmed"}},
            ],
            "on_success": [],
        }, state, bus)
    finally:
        state.current_attack = saved


# ============================================================================
# Unbreakable Majesty (L14)
# ============================================================================

def has_unbreakable_majesty(actor: Actor) -> bool:
    features = (actor.template or {}).get("features_known") or []
    return "f_unbreakable_majesty" in features


def activate_unbreakable_majesty(actor: Actor, state: CombatState) -> None:
    """Assume the majestic presence (Bonus Action, 1/short-or-long rest). The
    use is consumed by the action's feature_use gate; this sets the active
    flag. The presence lasts the encounter (RAW: 1 minute) or until the Bard
    is Incapacitated."""
    actor.unbreakable_majesty_active = True
    state.event_log.append({
        "event": "unbreakable_majesty_assumed", "actor": actor.id})


def _is_incapacitated(actor: Actor) -> bool:
    return any(c.get("condition_id") == "co_incapacitated"
               for c in actor.applied_conditions)


def majesty_negates_hit(target: Actor, attacker: Actor, state: CombatState,
                          rng) -> bool:
    """Unbreakable Majesty: while the majestic presence is active, the FIRST
    attack to hit `target` each turn forces `attacker` to make a CHA save vs
    the Bard's spell DC — on a failure the attack misses instead. Returns True
    if the hit is negated.

    Per-turn dedup via `_majesty_negated_this_turn` (cleared in reset_turn).
    The presence ends if the Bard becomes Incapacitated (RAW)."""
    if not getattr(target, "unbreakable_majesty_active", False):
        return False
    if _is_incapacitated(target):
        target.unbreakable_majesty_active = False   # presence drops
        return False
    if getattr(target, "_majesty_negated_this_turn", False):
        return False
    target._majesty_negated_this_turn = True
    dc = _bard_spell_dc(target)
    save_mod = int((attacker.abilities.get("cha") or {}).get("save", 0))
    d20 = rng.randint(1, 20)
    total = d20 + save_mod
    negated = total < dc
    state.event_log.append({
        "event": "unbreakable_majesty",
        "bard": target.id, "attacker": attacker.id,
        "d20": d20, "save_mod": save_mod, "total": total, "dc": dc,
        "negated": negated})
    return negated
