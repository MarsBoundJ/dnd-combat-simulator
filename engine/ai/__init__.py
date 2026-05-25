"""AI decision layer — replaces the skeleton's 'attack nearest enemy'
with archetype-driven targeting and ability selection.

Implements the 5-step Ammann + eHP hybrid decision pattern from
docs/foundations/pillars-reconciliation.md §7, behind the
score_candidates() socket that's been waiting in pipeline.py.

v1 scope (this module):
  - Targeting dial — all 5 presets implemented
    (closest_enemy / weakest_target / most_dangerous / caster_first / optimal_ehp)
  - Ability selection — simple priority order (multiattack > weapon_attack)
  - Behavior profile resolution — read from actor.template (no 3-level
    inheritance yet; faction profiles + instance overrides deferred)

Deferred to follow-on PRs:
  - Full Ammann + eHP scoring with behavioral coefficients
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
]
