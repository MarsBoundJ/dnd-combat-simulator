"""Action Economy dial — per-slot stochastic between optimal-vs-default.

Per `docs/foundations/pillars-reconciliation.md` §5.4: modulates whether the
actor uses all turn slots (Action / Bonus Action / Reaction) and how
optimally within each slot.

**Five presets** with per-slot percentage knobs. Per the spec table:

  | Preset        | Main % | Signature bonus % | Tactical bonus % | OA reaction % | Sophisticated reaction % |
  |---------------|--------|-------------------|------------------|---------------|--------------------------|
  | Optimal       | 100    | 100               | 100              | 100           | 100                      |
  | Skilled       | 90     | 95                | 85               | 100           | 80                       |
  | Average       | 85     | 95                | 60               | 95            | 40                       |
  | Casual        | 75     | 90                | 30               | 85            | 10                       |
  | Reactive_only | 65     | 80                | 0                | 80            | 0                        |

**"Miss" semantics** — when the Main slot rolls suboptimal, the actor falls
back to its DEFAULT action (first weapon_attack in the action list), keeping
the targeting dial's chosen target. Mirrors real-table behavior: a player
who doesn't spot the combo defaults to "I attack."

**PC `play_context: solo`** — shifts the preset down one tier (Optimal →
Skilled, Skilled → Average, etc.). Captures the no-table-reminders effect.

**v1 scope:**
  - Main slot optimality roll wired (replaces step 7 no-op in pipeline.py)
  - Bonus action slot infrastructure (runner now attempts a bonus turn)
  - Default action lookup (first weapon_attack)
  - Signature vs tactical split for bonus actions
  - PC `play_context: solo` tier shift

**Deferred:**
  - Reactions entirely — need opportunity-attack trigger plumbing
    (which needs movement / positions). The `is_reactive_trigger` tag is
    parsed and reaction rates stored in the preset table, but no reaction
    candidates are generated yet.
  - Combo recognition column from the spec (qualitative; not actionable v1).
  - `additional_action` primitive (Action Surge) — separate primitive.
  - Sanity hint warnings (`ability_economy_mismatch`).
"""
from __future__ import annotations

import random
from typing import Iterable

from engine.core.state import Actor


ACTION_ECONOMY_PRESETS = (
    "optimal",
    "skilled",
    "average",
    "casual",
    "reactive_only",
)


# Preset-to-percentage table. Each row is a dict the runner / pipeline
# look up to resolve the per-slot rolls. Values are probabilities in [0, 1].
_PRESET_PERCENTAGES: dict[str, dict[str, float]] = {
    "optimal": {
        "main_optimality":         1.00,
        "signature_bonus":         1.00,
        "tactical_bonus":          1.00,
        "oa_reaction":             1.00,
        "sophisticated_reaction":  1.00,
    },
    "skilled": {
        "main_optimality":         0.90,
        "signature_bonus":         0.95,
        "tactical_bonus":          0.85,
        "oa_reaction":             1.00,
        "sophisticated_reaction":  0.80,
    },
    "average": {
        "main_optimality":         0.85,
        "signature_bonus":         0.95,
        "tactical_bonus":          0.60,
        "oa_reaction":             0.95,
        "sophisticated_reaction":  0.40,
    },
    "casual": {
        "main_optimality":         0.75,
        "signature_bonus":         0.90,
        "tactical_bonus":          0.30,
        "oa_reaction":             0.85,
        "sophisticated_reaction":  0.10,
    },
    "reactive_only": {
        "main_optimality":         0.65,
        "signature_bonus":         0.80,
        "tactical_bonus":          0.00,
        "oa_reaction":             0.80,
        "sophisticated_reaction":  0.00,
    },
}


# Tier-shift order for `play_context: solo` PCs. Per §5.4 the preset
# shifts down ONE tier — a solo Casual player drops to Reactive_only.
_TIER_DOWN: dict[str, str] = {
    "optimal":       "skilled",
    "skilled":       "average",
    "average":       "casual",
    "casual":        "reactive_only",
    "reactive_only": "reactive_only",   # floor
}


def resolve_action_economy_preset(actor: Actor) -> str:
    """Resolve the actor's action_economy preset with archetype defaults +
    play_context shift.

    Order:
      1. Explicit `behavior_profile.presets.action_economy`
      2. Archetype default (via behavior_profile resolution chain)
      3. Hard-coded fallback ('average')
    Then: if `behavior_profile.play_context == 'solo'`, shift down one tier.
    """
    # Lazy import to avoid circular ai/__init__ ordering
    from engine.ai.behavior_profile import resolve_action_economy_preset as _resolve

    preset = _resolve(actor)
    if preset not in _PRESET_PERCENTAGES:
        preset = "average"

    bp = (actor.template.get("behavior_profile") or {})
    if bp.get("play_context") == "solo":
        preset = _TIER_DOWN.get(preset, preset)
    return preset


def get_percentages(preset: str) -> dict[str, float]:
    """Return the percentage table for a preset (defensive copy)."""
    return dict(_PRESET_PERCENTAGES.get(preset, _PRESET_PERCENTAGES["average"]))


def resolve_percentages(actor: Actor) -> dict[str, float]:
    """Convenience: resolve preset for actor and return its percentages."""
    return get_percentages(resolve_action_economy_preset(actor))


# ============================================================================
# Default-action lookup ("miss" fallback for the Main slot)
# ============================================================================

def find_default_action(actor: Actor) -> dict | None:
    """Return the actor's DEFAULT action — what they fall back to on a Main-slot
    miss roll. Per spec: "Attack for Main". So: the first weapon_attack in the
    actor's action list (NOT multiattack — multiattack is the optimal choice
    that gets defaulted away from).

    Returns None if the actor has no weapon_attack actions at all (rare;
    pure casters with no weapon options).
    """
    actions = (actor.template.get("actions") or [])
    for a in actions:
        if a.get("type") == "weapon_attack":
            return a
    return None


# ============================================================================
# Slot classification helpers — read action tags
# ============================================================================

def action_slot(action: dict) -> str:
    """Return the action's slot: 'action' (default), 'bonus_action', 'reaction'.

    Backward-compatible: actions without a `slot` field are treated as
    main-action slot (matches all existing fixtures).
    """
    return action.get("slot", "action")


def is_signature(action: dict) -> bool:
    """True if the action is part of the creature's identity (Goblin Nimble
    Escape, Wolf Pack Tactics, Rogue Cunning Action). Reflexive use — higher
    baseline rate across all presets."""
    return bool(action.get("is_signature", False))


def is_reactive_trigger(action: dict) -> bool:
    """True if the action triggers instinctively (Opportunity Attack, Hellish
    Rebuke when hit, Riposte after parry). Low decision overhead.

    v1: tag is parsed for future use; no reactions are generated yet."""
    return bool(action.get("is_reactive_trigger", False))


# ============================================================================
# Main-slot "miss" resolution (the heart of step 7)
# ============================================================================

def resolve_main_slot(actor: Actor, chosen: dict | None,
                       state, rng: random.Random) -> dict | None:
    """Apply the Main-slot optimality roll.

    With probability `main_optimality`, the originally chosen candidate is
    returned unchanged. Otherwise: replace its action with the actor's
    default attack (keeping the same target), simulating the player who
    "didn't spot the combo and just attacks."

    Returns the (possibly-downgraded) candidate, or None if chosen is None.

    Pure function modulo `rng` — same seed → same outcome.
    """
    if chosen is None:
        return None
    pcts = resolve_percentages(actor)
    main_optimality = pcts.get("main_optimality", 0.85)
    if rng.random() < main_optimality:
        return chosen  # optimal hit — use the AI's top pick

    # Miss — fall back to default action, keeping the targeting dial's pick
    default = find_default_action(actor)
    if default is None or default.get("id") == chosen.get("action", {}).get("id"):
        # No fallback distinct from current → just keep chosen
        return chosen
    downgrade = {
        "kind": "weapon_attack",
        "action": default,
        "target": chosen.get("target"),
        "actor": actor,
        "downgraded_from": chosen.get("action", {}).get("id"),
    }
    # The default attack must still be a LEGAL choice for this actor. An RP
    # hard filter (e.g. pacifist_strict, which forbids weapon attacks) would
    # have removed it from the candidate pool, so the optimality miss must
    # not resurrect it — keep the originally chosen (legal) action instead.
    # (Previously masked: encounters ended before the rare miss roll fired.)
    from engine.core.pipeline import apply_hard_filters
    if not apply_hard_filters([downgrade], actor, state):
        return chosen
    return downgrade


# ============================================================================
# Bonus-slot resolution
# ============================================================================

def should_use_bonus_action(actor: Actor, bonus_action: dict,
                              rng: random.Random) -> bool:
    """Roll whether to actually use a candidate bonus action.

    Signature bonus actions (is_signature=True) roll vs `signature_bonus`.
    Tactical bonus actions (default) roll vs `tactical_bonus`.
    """
    pcts = resolve_percentages(actor)
    if is_signature(bonus_action):
        threshold = pcts.get("signature_bonus", 0.95)
    else:
        threshold = pcts.get("tactical_bonus", 0.60)
    return rng.random() < threshold
