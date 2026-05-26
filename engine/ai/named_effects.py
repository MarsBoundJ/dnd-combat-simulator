"""Named-effect tagging for cross-caster buff dedup (PR #36).

PHB 2024 p.243 "Combining Magical Effects":

    The effects of DIFFERENT spells add together while the durations of
    those spells overlap. The effects of the SAME spell cast multiple
    times don't combine, however. Instead, the most potent effect ...
    applies while the durations of the effects overlap.

PR #20's per-(caster, action_id) dedup only catches the same caster
re-casting their own buff. Two clerics each Blessing the same fighter
would stack pre-PR #36 — wrong per RAW.

**Schema:**

Actions declare an optional `named_effect: <string>` field. Convention:
lowercase RAW spell name, e.g., `"bless"`, `"heroism"`,
`"hypnotic_pattern"`. The primitive layer (`_build_modifier_entry`)
stamps this onto each generated modifier's `source` dict.

**Dedup check (this module):**

`buff_already_active(target, action, caster)` returns True iff any
active modifier on `target` matches the action's effect — either by:
  - same `named_effect` (new path, cross-caster aware), OR
  - same `(action_id, caster_id)` pair (legacy path, for actions that
    haven't been tagged with named_effect yet)

The legacy fallback is intentional: it lets fixtures that pre-date
this PR keep working without a migration. New / important fixtures
(Bless, Heroism, etc.) should declare named_effect to get the RAW
cross-caster behavior.

**Used by:**
  - `offensive_ehp_buff_ally` (Bless-shape eHP scoring)
  - `offensive_ehp_help` (Help eHP scoring — single-attack adv)

Both return 0.0 when the buff is already active, so the AI won't pick
the same buff on a target that already has it.

**Deferred:**
  - "Most-potent-wins" replacement semantics: RAW lets a stronger
    casting (e.g., higher slot upcast) supersede a weaker one. v1
    just blocks the re-cast outright; in practice the duplicate
    case rarely matters because both casts would have identical
    effects in our current schema.
  - Defensive-buff dedup (Shield of Faith, etc.): same pattern would
    apply but isn't wired yet — defensive buffs go through a
    different scoring path.
"""
from __future__ import annotations

from engine.core.state import Actor


def buff_already_active(target: Actor, action: dict, caster: Actor,
                         primitive: str = "attack_modifier") -> bool:
    """Cross-caster-aware dedup: True if `target` already has an active
    modifier from `action` (either same spell from any caster via
    `named_effect`, or same caster's own previous cast via the legacy
    per-(caster, action_id) path).

    Filters by primitive type (default `attack_modifier` matches both
    Bless-shape buffs and Help's advantage). Pass a different primitive
    name if extending to defensive buffs, save modifiers, etc.
    """
    action_id = action.get("id")
    caster_id = caster.id
    named_effect = action.get("named_effect")
    for mod in target.active_modifiers:
        if mod.get("primitive") != primitive:
            continue
        src = mod.get("source") or {}
        # Path 1: cross-caster dedup via named_effect (RAW: same spell
        # cast by anyone doesn't stack).
        if named_effect and src.get("named_effect") == named_effect:
            return True
        # Path 2: legacy per-(caster, action_id) dedup — catches the
        # same caster's own re-cast of an untagged action.
        if (src.get("action_id") == action_id
                and src.get("caster_id") == caster_id):
            return True
    return False
