"""AI decision layer — replaces the skeleton's 'attack nearest enemy'
with archetype-driven targeting, ability selection, and eHP scoring.

Implements the 5-step Ammann + eHP hybrid decision pattern from
docs/foundations/pillars-reconciliation.md §7, behind the
score_candidates() socket that's been waiting in pipeline.py.

v1+eHP+defensive scope (this module):
  - Targeting dial — all 5 presets implemented
  - Ability selection — mindless/instinctive/default + eHP-driven
    tactical/optimal (picks highest-EV action against chosen target)
  - Behavior profile resolution — reads from actor.template (no 3-level
    inheritance yet; faction profiles + instance overrides deferred)
  - Offensive eHP scoring — expected_damage × hit_probability per
    candidate, including advantage from active_modifiers (AI exploits
    Blinded / Restrained / Prone targets organically)
  - Defensive eHP scoring — healing (desperation-weighted), defensive
    buff (AC / disadvantage-for-attackers), hard control (save-or-lose
    action denial)
  - Candidate generator now emits heal/buff candidates per ally and
    hard_control candidates per enemy
  - Aggression coefficient — per-archetype multiplier on raw eHP

Deferred to follow-on PRs:
  - Soft control / movement denial (needs positions)
  - Offensive buff for allies (Bless) — math symmetric to defensive buff
  - Debuff on enemy saves
  - Spell slot opportunity cost
  - Future-rounds discounting + AoE multi-target optimization
  - self_preservation_coefficient / pack_tactics_bonus
  - Action Economy dial (signature_bonus / tactical_bonus / reaction tiering)
  - Retreat dial (DMG p48 algorithm + the 3 modes)
  - RP Constraints (Hard Filter / Forced Choice / Weighted Preference)
  - Faction profile + instance override layers
  - Runtime override layer (Frightened / Dominate Person / Confusion)
"""

from engine.ai.decision_layer import score_candidates_v1, select_action_v1
from engine.ai.targeting import pick_target, TARGETING_PRESETS
from engine.ai.ability_selection import pick_action, ABILITY_SELECTION_PRESETS
from engine.ai.behavior_profile import (
    resolve_targeting_preset,
    resolve_ability_selection_preset,
    resolve_archetype,
)
from engine.ai.ehp_scoring import (
    score_candidate,
    best_action_against,
    aggression_coefficient,
    hit_probability,
    expected_damage_on_hit,
)
from engine.ai.defensive_ehp import (
    desperation_multiplier,
    expected_healing,
    estimate_dpr,
    save_fail_probability,
    defensive_ehp_healing,
    defensive_ehp_defensive_buff,
    defensive_ehp_hard_control,
)

__all__ = [
    "score_candidates_v1",
    "select_action_v1",
    "pick_target",
    "TARGETING_PRESETS",
    "pick_action",
    "ABILITY_SELECTION_PRESETS",
    "resolve_targeting_preset",
    "resolve_ability_selection_preset",
    "resolve_archetype",
    "score_candidate",
    "best_action_against",
    "aggression_coefficient",
    "hit_probability",
    "expected_damage_on_hit",
    "desperation_multiplier",
    "expected_healing",
    "estimate_dpr",
    "save_fail_probability",
    "defensive_ehp_healing",
    "defensive_ehp_defensive_buff",
    "defensive_ehp_hard_control",
]
