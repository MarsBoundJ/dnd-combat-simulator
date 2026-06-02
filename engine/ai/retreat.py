"""Retreat dial — when an actor considers leaving the fight.

Per `docs/foundations/pillars-reconciliation.md` §5.1: operates *above* all
other dials — a triggered retreat overrides every other decision for the
actor's turn. Implements the DMG p48 algorithm in the recommended
`dmg_ammann` mode (Rules + Behavior + eHP).

**Five presets** (per-creature parameter bundles, per the §5.1 table):

  | Preset    | Bloodied % | Ally-disparity % | Frightened-alone | In-combat DC |
  |-----------|------------|------------------|------------------|--------------|
  | FtD       | (algorithm disabled — never flees)                                  |
  | Resolute  |   35%      |   >75%           | No                |     8        |
  | Default   |   50%      |   >50%           | Yes               |    10        |
  | Cowardly  |   60%      |    1 ally falls  | Yes               |    13        |
  | Pacifist  |   50%      |   >50%           | Yes (parley first)|    10        |

**Algorithm per turn (dmg_ammann mode):**

  1. Mindless override: INT ≤ 2 OR archetype `mindless_aggressor` → FtD
     (never flees), regardless of preset
  2. If preset is FtD → never flees
  3. Evaluate triggers:
       - bloodied_triggered  ← HP_remaining / HP_max ≤ bloodied_pct
       - ally_disparity_triggered ← fraction of side fallen ≥ ally_disparity_pct
       - frightened_triggered ← has co_frightened in applied_conditions
  4. Apply compound logic per preset:
       - Resolute: must be bloodied AND (frightened OR ally_disparity)
       - Others:  any single trigger fires the roll
  5. If triggered → roll d20 + WIS save vs `in_combat_dc`
       - Fail → return retreat dict (actor flees this turn)
       - Pass → return None (actor stays, may re-trigger next turn)

**v1 scope:**
  - In-combat per-turn check only (pre-combat check deferred)
  - DMG p48 + Ammann archetype short-circuit (FtD for mindless)
  - Compound triggers + WIS save roll
  - Event log entries: retreat_triggered, retreat_save, fled

**Deferred:**
  - Parley action (needs language tracking + parley action + RP-Constraint
    tie-in) — Pacifist preset flees for v1, no parley attempt
  - Strict RAW mode + Behavior Engine mode — only dmg_ammann active
  - Pre-combat retreat check (whether monster engages at all)
  - SPC modulation of save DC (waiting on behavioral coefficients PR)
  - Flight-blocked / no-exit → FtD fallback (needs positioning)
  - Surrendered-creature non-targetable behavioral system
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from engine.core.state import Actor, CombatState


RETREAT_PRESETS = (
    "ftd",
    "resolute",
    "default",
    "cowardly",
    "pacifist",
)


# Per-preset parameter bundle. FtD has no parameters — the algorithm
# short-circuits before consulting any threshold.
@dataclass(frozen=True)
class RetreatBundle:
    bloodied_pct: float           # HP_remaining/HP_max threshold
    ally_disparity_pct: float     # fraction of side fallen (dead/fled)
    frightened_alone_sufficient: bool
    in_combat_dc: int


_PRESET_BUNDLES: dict[str, RetreatBundle | None] = {
    "ftd":      None,   # algorithm disabled
    "resolute": RetreatBundle(bloodied_pct=0.35, ally_disparity_pct=0.75,
                                frightened_alone_sufficient=False, in_combat_dc=8),
    "default":  RetreatBundle(bloodied_pct=0.50, ally_disparity_pct=0.50,
                                frightened_alone_sufficient=True, in_combat_dc=10),
    "cowardly": RetreatBundle(bloodied_pct=0.60, ally_disparity_pct=0.001,
                                frightened_alone_sufficient=True, in_combat_dc=13),
    "pacifist": RetreatBundle(bloodied_pct=0.50, ally_disparity_pct=0.50,
                                frightened_alone_sufficient=True, in_combat_dc=10),
}


# INT threshold below which the algorithm short-circuits to FtD per spec
# "minimal undead/construct/INT≤2 → FtD override".
MINDLESS_INT_CUTOFF = 2

# Archetypes that always FtD regardless of declared preset.
_ALWAYS_FTD_ARCHETYPES = {"mindless_aggressor"}


# ============================================================================
# Public API
# ============================================================================

def get_bundle(preset: str) -> RetreatBundle | None:
    """Return the preset's parameter bundle, or None for FtD/unknown."""
    return _PRESET_BUNDLES.get(preset)


def resolve_retreat_preset(actor: Actor) -> str:
    """Resolve the actor's retreat preset via behavior_profile chain."""
    from engine.ai.behavior_profile import resolve_retreat_preset as _resolve
    preset = _resolve(actor)
    if preset not in _PRESET_BUNDLES:
        preset = "default"
    return preset


def check_retreat(actor: Actor, state: CombatState,
                   rng: random.Random | None = None) -> dict | None:
    """Run the DMG p48 algorithm (dmg_ammann mode) for this actor.

    Returns:
      - None  → no retreat; actor takes their turn normally
      - dict  → actor flees this turn; dict contains telemetry:
          {"reason": str, "triggers": [str], "preset": str,
            "dc": int, "d20": int, "total": int}

    The rng is required for the WIS save. If omitted, a fresh random is used.
    """
    if rng is None:
        rng = random.Random()

    # PC retreat model — the DEFAULT for a party PC with no explicitly
    # declared retreat preset. Per table reality: a PC in a party does NOT
    # flee on HP/bloodied — they fight until they drop, trusting the party
    # to revive them; the one realistic retreat is the LAST conscious
    # member fleeing to recover the downed rest. A SOLO PC has no revival
    # safety net (self-preservation applies). A PC with an EXPLICIT preset
    # (e.g. a fixture's ftd) opts out of this model and uses the normal
    # algorithm. See _pc_party_retreat.
    if actor.side == "pc" and not _has_explicit_retreat_preset(actor):
        party_decision = _pc_party_retreat(actor, state)
        if party_decision is not _SOLO_PC:
            return party_decision
        # else: solo PC → normal self-preservation algorithm

    # Step 1: mindless override — never flees
    if _is_mindless_for_retreat(actor):
        return None

    # Step 2: preset lookup
    preset = resolve_retreat_preset(actor)
    bundle = get_bundle(preset)
    if bundle is None:   # FtD
        return None

    # Step 3: evaluate triggers
    triggers = _evaluate_triggers(actor, state, bundle)
    if not triggers:
        return None

    # Step 4: compound logic — Resolute requires Bloodied AND another trigger
    if preset == "resolute":
        if "bloodied" not in triggers:
            return None
        other = [t for t in triggers if t != "bloodied"]
        if not other:
            return None

    # Step 5: WIS save vs in_combat_dc; failure = flee
    wis_save = (actor.abilities.get("wis") or {}).get("save", 0)
    d20 = rng.randint(1, 20)
    total = d20 + wis_save
    save_outcome = "success" if total >= bundle.in_combat_dc else "fail"

    state.event_log.append({
        "event": "retreat_triggered",
        "actor": actor.id,
        "preset": preset,
        "triggers": triggers,
    })
    state.event_log.append({
        "event": "retreat_save",
        "actor": actor.id,
        "dc": bundle.in_combat_dc,
        "d20": d20,
        "total": total,
        "outcome": save_outcome,
    })

    if save_outcome == "fail":
        return {
            "reason": "wisdom_save_failed",
            "triggers": triggers,
            "preset": preset,
            "dc": bundle.in_combat_dc,
            "d20": d20,
            "total": total,
        }
    return None


# ============================================================================
# PC retreat model
# ============================================================================

# Sentinel: a solo PC (no companions) — caller falls through to the normal
# self-preservation retreat algorithm rather than the party model.
_SOLO_PC = object()


def _has_explicit_retreat_preset(actor: Actor) -> bool:
    """True if the actor's stat block explicitly declares a retreat preset
    (behavior_profile.presets.retreat). Such actors opt out of the PC
    default model and use the normal algorithm with their chosen preset."""
    return bool(((actor.template.get("behavior_profile") or {})
                 .get("presets") or {}).get("retreat"))


def _pc_party_retreat(actor: Actor, state: CombatState):
    """Retreat decision for a PC *that has companions*.

    - Returns `_SOLO_PC` if the PC has no other party members → the caller
      should use the normal algorithm (a solo PC has no revival safety net,
      so it self-preserves like anyone else).
    - Returns None if at least one companion is still up → fight until you
      drop, trusting the party to revive you (no HP/bloodied/morale flee).
    - Returns a retreat dict if this is the LAST conscious member (all
      companions down) → flee to escape and recover/raise them.

    v1 simplification: the last survivor always flees; a "heroic last stand
    when the fight is clearly winnable" refinement is deferred.
    """
    party = [a for a in state.encounter.actors
             if a.side == "pc" and a.id != actor.id]
    if not party:
        return _SOLO_PC                   # no companions → normal algorithm
    if any(a.is_alive() for a in party):
        return None                       # someone's still up — fight on
    # Every other party member is down → flee to recover them.
    state.event_log.append({
        "event": "retreat_triggered", "actor": actor.id,
        "preset": "pc_last_standing", "triggers": ["last_conscious_pc"],
    })
    return {
        "reason": "last_conscious_pc", "triggers": ["last_conscious_pc"],
        "preset": "pc_last_standing", "dc": None, "d20": None, "total": None,
    }


# ============================================================================
# Internal helpers — trigger evaluation
# ============================================================================

def _is_mindless_for_retreat(actor: Actor) -> bool:
    """Mindless override: never flees."""
    # Archetype check
    bp = (actor.template.get("behavior_profile") or {})
    if bp.get("archetype") in _ALWAYS_FTD_ARCHETYPES:
        return True
    # INT check
    int_score = (actor.abilities.get("int") or {}).get("score", 10)
    if int_score <= MINDLESS_INT_CUTOFF:
        return True
    return False


def _evaluate_triggers(actor: Actor, state: CombatState,
                        bundle: RetreatBundle) -> list[str]:
    """Return list of trigger names that have fired this turn.

    Possible entries: 'bloodied', 'ally_disparity', 'frightened'.
    Frightened-alone is recorded only if the preset accepts it as a trigger
    (per `frightened_alone_sufficient`); otherwise Frightened is recorded
    only as a compound contributor (handled in check_retreat via the
    Resolute branch).
    """
    triggers: list[str] = []

    # Bloodied trigger
    if actor.hp_max > 0:
        hp_frac = actor.hp_current / actor.hp_max
        if hp_frac <= bundle.bloodied_pct:
            triggers.append("bloodied")

    # Ally-disparity trigger
    fallen_frac = _ally_disparity_fraction(actor, state)
    if fallen_frac >= bundle.ally_disparity_pct:
        triggers.append("ally_disparity")

    # Frightened trigger — only counts as a standalone trigger when the
    # preset allows it. For Resolute (frightened_alone_sufficient=False),
    # Frightened still appears in triggers IF it co-occurs with Bloodied
    # or ally_disparity (the compound rule). We always record it, and the
    # check_retreat compound logic handles the Resolute case.
    if _has_frightened(actor):
        if bundle.frightened_alone_sufficient or triggers:
            triggers.append("frightened")
    return triggers


def _ally_disparity_fraction(actor: Actor, state: CombatState) -> float:
    """Fraction of same-side actors that are dead or fled (excluding self).

    Returns 0.0 if there are no other allies (a lone actor has no
    disparity signal). A side with 4 members where 2 are down returns 0.5.
    """
    same_side = [a for a in state.encounter.actors if a.side == actor.side]
    others = [a for a in same_side if a.id != actor.id]
    if not others:
        return 0.0
    fallen = sum(1 for a in others if not a.is_alive())
    return fallen / len(others)


def _has_frightened(actor: Actor) -> bool:
    """True if the actor currently has the Frightened condition applied."""
    for c in actor.applied_conditions:
        if c.get("condition_id") == "co_frightened":
            return True
    return False
