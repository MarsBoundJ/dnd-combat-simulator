"""Overchannel — Evoker (Wizard subclass) L14 damage maximizer.

RAW (SRD 5.2.1): "When you cast a Wizard spell of level 1 through 5 that
deals damage, you can deal maximum damage with that spell on the turn
you cast it. The first time you do so, you suffer no adverse effect. If
you use this feature again before you finish a Long Rest, you take 2d12
Necrotic damage per level of the spell immediately after you cast it.
This damage ignores Resistance and Immunity. Each time you use this
feature again before you finish a Long Rest, the Necrotic damage per
spell level increases by 1d12."

Like the Metamagic module, this makes the mechanic correct and directly
testable; the proactive AI decision of WHICH spell to overchannel (and
whether to pay the escalating self-damage for a reuse) is a follow-on
engine/ai concern — the free first use is strictly beneficial, the
reuses are not, and weighing the reuse cost belongs with the scoring
heuristics. `apply_overchannel` deep-copies the action, stamps
`maximize_dice` on every damage step (honored by _damage), debits the
per-rest usage counter, and — on a reuse — applies the escalating
necrotic self-damage.

v1 limitation: maximize covers the spell's base + crit damage dice; the
per-slot-level upcast extra dice (_resolve_upcast_extra_dice) are not
maximized. The base dice dominate the total and the common Overchannel
target is a fixed-level damage spell, so this is a documented edge.
"""
from __future__ import annotations

import copy

from engine.core.metamagic import _iter_damage_params
from engine.core.state import Actor, CombatState

_USES_KEY = "overchannel_uses_this_rest"


def has_overchannel(actor: Actor) -> bool:
    """True if the actor has the Overchannel feature (Evoker L14+)."""
    return "f_overchannel" in ((actor.template or {}).get("features_known") or [])


def _spell_level(action: dict) -> int:
    return int(action.get("spell_slot_level", 0) or 0)


def is_eligible(action: dict) -> bool:
    """True if `action` is a Wizard spell of level 1-5 that deals damage
    (has at least one damage step)."""
    if not (1 <= _spell_level(action) <= 5):
        return False
    return any(True for _ in _iter_damage_params(action))


def apply_overchannel(action: dict, caster: Actor, state: CombatState,
                       rng) -> dict:
    """Maximize `action`'s damage dice; on a reuse before a Long Rest,
    deal the escalating necrotic self-damage. Returns a MODIFIED COPY of
    the action (the original is left untouched, mirroring apply_metamagic).
    Returns the action unchanged if it isn't Overchannel-eligible."""
    if not is_eligible(action):
        return action
    modified = copy.deepcopy(action)
    for p in _iter_damage_params(modified):
        p["maximize_dice"] = True

    prior_uses = int(caster.resources.get(_USES_KEY, 0))
    level = _spell_level(action)
    self_damage = 0
    if prior_uses >= 1:
        # Nth use (N = prior_uses + 1, N >= 2): N d12 per spell level,
        # ignoring Resistance and Immunity (applied straight to HP).
        dice_count = (prior_uses + 1) * level
        self_damage = sum(rng.randint(1, 12) for _ in range(dice_count))
        caster.hp_current = max(0, caster.hp_current - self_damage)
    caster.resources[_USES_KEY] = prior_uses + 1

    state.event_log.append({
        "event": "overchannel_used",
        "actor": caster.id,
        "spell": action.get("id"),
        "spell_level": level,
        "use_number": prior_uses + 1,
        "self_damage": self_damage,
    })
    return modified
