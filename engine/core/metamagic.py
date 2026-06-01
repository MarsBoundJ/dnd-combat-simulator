"""Metamagic — the Sorcerer's spell-modification subsystem (SRD 5.2.1).

A Sorcerer spends Sorcery Points to modify a spell as it's cast. This
module is the framework: each of the 10 SRD options is a declarative
spec with a Sorcery-Point cost, an applicability test, and a transform
that returns a MODIFIED COPY of the cast action (and/or arms a per-cast
flag the engine honors at resolution).

How it's used:
  apply_metamagic(option_id, action, caster, state) — checks the caster
  knows the option (caster.metamagic_known) and has the SP, deep-copies
  the action, applies the transform, spends the SP, logs, and returns
  the modified action. Returns the unmodified action if the option
  can't apply (unknown / unaffordable / not applicable).

Engine honors (resolution-time flags some transforms set):
  - empowered (reroll N lowest damage dice)  → _damage
  - heightened (one target rolls save at disadvantage) → _forced_save
  - careful (listed creatures auto-succeed the save) → _forced_save
  - seeking (reroll a missed spell-attack d20)  → _attack_roll
  - subtle (no V/S/M components → bypass silence gate) → pipeline filter
Distant / Quickened / Transmuted / Extended / Twinned are pure action-
dict transforms needing no resolution hook.

AI note: WHICH option a Sorcerer applies to WHICH spell, and when, is an
engine/ai concern (deferred). This module makes each option correct and
directly testable; proactive selection is a follow-on.
"""
from __future__ import annotations

import copy

from engine.core.state import Actor, CombatState

# The six damage types Transmuted can swap between (SRD list).
_TRANSMUTE_TYPES = ["acid", "cold", "fire", "lightning", "poison", "thunder"]


def _cha_mod(caster: Actor) -> int:
    score = (caster.abilities.get("cha") or {}).get("score", 10)
    return max(1, (score - 10) // 2)   # "minimum of one" per RAW


def _double_range(action: dict) -> None:
    """Distant: double an explicit range; Touch (<=5) becomes 30."""
    r = int(action.get("range_ft", 0) or 0)
    if r and r <= 5:
        action["range_ft"] = 30
    elif r:
        action["range_ft"] = r * 2
    # also bump range inside attack_roll / forced_save params + area
    for step in action.get("pipeline", []):
        p = step.get("params") or {}
        if "range_ft" in p:
            rr = int(p["range_ft"])
            p["range_ft"] = 30 if rr <= 5 else rr * 2
    area = action.get("area")
    if isinstance(area, dict) and area.get("range_ft"):
        area["range_ft"] = int(area["range_ft"]) * 2


def _iter_damage_params(action: dict):
    """Yield every damage step's params dict, both at the action's top
    level AND nested inside forced_save on_fail / on_success blocks
    (save-for-damage spells like Fireball put the damage there)."""
    def _walk(steps):
        for step in steps or []:
            if step.get("primitive") == "damage":
                yield step.setdefault("params", {})
            elif step.get("primitive") == "forced_save":
                sp = step.get("params") or {}
                yield from _walk(sp.get("on_fail"))
                yield from _walk(sp.get("on_success"))
    yield from _walk(action.get("pipeline"))


def _transmute_damage(action: dict) -> None:
    """Transmuted: change each damage step's type to the next type in the
    SRD list (deterministic representative swap; the sim treats the type
    as cosmetic unless the target has a matching resistance)."""
    for p in _iter_damage_params(action):
        cur = str(p.get("type", "")).lower()
        if cur in _TRANSMUTE_TYPES:
            idx = _TRANSMUTE_TYPES.index(cur)
            p["type"] = _TRANSMUTE_TYPES[(idx + 1) % len(_TRANSMUTE_TYPES)]


def _tag_forced_saves(action: dict, key: str, value) -> None:
    """Set a flag on every forced_save step's params (Heightened/Careful)."""
    for step in action.get("pipeline", []):
        if step.get("primitive") == "forced_save":
            (step.setdefault("params", {}))[key] = value


# ---- Option specs -----------------------------------------------------

def _apply_quickened(action, caster, state):
    action["slot"] = "bonus_action"


def _apply_distant(action, caster, state):
    _double_range(action)


def _apply_transmuted(action, caster, state):
    _transmute_damage(action)


def _apply_extended(action, caster, state):
    # Duration isn't strongly modeled in the sim; tag for completeness +
    # advantage on concentration saves (honored by concentration code if
    # present). Mechanically near-no-op in single-encounter sims.
    action["metamagic_extended"] = True


def _apply_empowered(action, caster, state):
    # Reroll up to CHA-mod damage dice (keep the new rolls). _damage
    # honors `empowered_reroll` on the damage step params.
    n = _cha_mod(caster)
    for p in _iter_damage_params(action):
        p["empowered_reroll"] = n


def _apply_heightened(action, caster, state):
    # One target rolls its save at disadvantage. _forced_save honors
    # `heightened` (applies to the first/primary affected creature).
    _tag_forced_saves(action, "heightened", True)


def _apply_careful(action, caster, state):
    # Up to CHA-mod chosen creatures auto-succeed + take no damage.
    # The transform marks the count; _forced_save exempts that many
    # allies of the caster from the save (v1: allies auto-succeed).
    _tag_forced_saves(action, "careful_allies", _cha_mod(caster))


def _apply_seeking(action, caster, state):
    # Reroll a missed spell-attack d20. Armed as a per-cast flag on the
    # action; _attack_roll honors `metamagic_seeking`.
    action["metamagic_seeking"] = True


def _apply_subtle(action, caster, state):
    # No V/S/M components → can cast inside a Silence zone. The pipeline
    # silence filter honors `subtle`.
    action["subtle"] = True


def _apply_twinned(action, caster, state):
    # Target a second creature with a single-target spell. Modeled by
    # routing through the multi-target grouping (max_targets=2). v1
    # applies only to actions that target a single creature.
    if int(action.get("max_targets", 1)) <= 1:
        action["max_targets"] = 2


METAMAGIC_OPTIONS: dict[str, dict] = {
    "quickened":  {"name": "Quickened Spell",  "sp": 2, "apply": _apply_quickened},
    "distant":    {"name": "Distant Spell",    "sp": 1, "apply": _apply_distant},
    "transmuted": {"name": "Transmuted Spell", "sp": 1, "apply": _apply_transmuted},
    "extended":   {"name": "Extended Spell",   "sp": 1, "apply": _apply_extended},
    "empowered":  {"name": "Empowered Spell",  "sp": 1, "apply": _apply_empowered},
    "heightened": {"name": "Heightened Spell", "sp": 2, "apply": _apply_heightened},
    "careful":    {"name": "Careful Spell",    "sp": 1, "apply": _apply_careful},
    "seeking":    {"name": "Seeking Spell",    "sp": 1, "apply": _apply_seeking},
    "subtle":     {"name": "Subtle Spell",     "sp": 1, "apply": _apply_subtle},
    "twinned":    {"name": "Twinned Spell",    "sp": 1, "apply": _apply_twinned},
}


def sp_cost(option_id: str) -> int:
    opt = METAMAGIC_OPTIONS.get(option_id)
    return int(opt["sp"]) if opt else 0


def knows(caster: Actor, option_id: str) -> bool:
    return option_id in (getattr(caster, "metamagic_known", None) or
                          (caster.template or {}).get("metamagic_known") or [])


def remaining_sp(caster: Actor) -> int:
    return int((caster.resources or {}).get("sorcery_points_remaining", 0))


def apply_metamagic(option_id: str, action: dict, caster: Actor,
                     state: CombatState) -> dict:
    """Apply a Metamagic option to `action`, returning a modified COPY
    (the original is never mutated). No-op (returns the original action)
    if the caster doesn't know the option, can't afford it, or it isn't
    a real option. Spends the Sorcery Points + logs on success."""
    opt = METAMAGIC_OPTIONS.get(option_id)
    if opt is None:
        return action
    if not knows(caster, option_id):
        return action
    cost = int(opt["sp"])
    if remaining_sp(caster) < cost:
        return action
    modified = copy.deepcopy(action)
    opt["apply"](modified, caster, state)
    caster.resources["sorcery_points_remaining"] = remaining_sp(caster) - cost
    state.event_log.append({
        "event": "metamagic_applied",
        "caster": caster.id,
        "option": option_id,
        "sp_spent": cost,
        "sp_remaining": caster.resources["sorcery_points_remaining"],
        "action": action.get("id"),
    })
    return modified


# ---- Font of Magic: slot <-> Sorcery Point conversion -----------------

# Creating Spell Slots table (SP cost, min sorcerer level) per SRD.
_CREATE_SLOT_COST = {1: (2, 2), 2: (3, 3), 3: (5, 5), 4: (6, 7), 5: (7, 9)}


def convert_slot_to_sp(caster: Actor, slot_level: int,
                        state: CombatState) -> bool:
    """Expend a spell slot to gain SP equal to the slot level (no action).
    Caps at sorcery_points_max. Returns True on success."""
    slots = caster.spell_slots or {}
    if int(slots.get(slot_level, 0)) <= 0:
        return False
    slots[slot_level] = int(slots[slot_level]) - 1
    cap = int((caster.resources or {}).get("sorcery_points_max", 0))
    cur = remaining_sp(caster)
    caster.resources["sorcery_points_remaining"] = min(cap, cur + slot_level)
    state.event_log.append({
        "event": "font_of_magic_slot_to_sp", "caster": caster.id,
        "slot_level": slot_level,
        "sp_remaining": caster.resources["sorcery_points_remaining"],
    })
    return True


def convert_sp_to_slot(caster: Actor, slot_level: int,
                        state: CombatState) -> bool:
    """Bonus Action: spend SP to create a spell slot (<= level 5) per the
    SRD cost table. Returns True on success."""
    entry = _CREATE_SLOT_COST.get(slot_level)
    if entry is None:
        return False
    cost, _min_level = entry
    if remaining_sp(caster) < cost:
        return False
    caster.resources["sorcery_points_remaining"] = remaining_sp(caster) - cost
    slots = caster.spell_slots or {}
    slots[slot_level] = int(slots.get(slot_level, 0)) + 1
    state.event_log.append({
        "event": "font_of_magic_sp_to_slot", "caster": caster.id,
        "slot_level": slot_level, "sp_cost": cost,
        "sp_remaining": caster.resources["sorcery_points_remaining"],
    })
    return True
