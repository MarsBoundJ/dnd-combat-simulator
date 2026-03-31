# Environment System

**Status:** 🟡 Specification complete — implementation pending  
**Last updated:** 2026-03-30  
**Location in engine:** `engine/environment/templates.py`, `engine/environment/hazards.py`

---

## Core Design Principle

The `EnvironmentTemplate` is the stable interface between the world and the engine.
The engine always receives a template object and works with it. It never cares how
that template was created. This means the system is infinitely extensible without
touching engine code.

```
Source (any of these)          →    EnvironmentTemplate    →    Engine
─────────────────────────────       ───────────────────         ──────
Named template from registry   →           object          →   Combat math
DM custom sliders in UI        →           object          →   AI decisions
Foundry scene wall/tile data   →           object          →   Behavior profiles
AI analysis of uploaded map    →           object          →   Outcome report
```

---

## The EnvironmentTemplate Object

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class HazardZone:
    name: str
    damage_per_round: float          # Expected damage for creatures in zone
    damage_type: str                 # "fire", "bludgeoning", "acid", etc.
    save_dc: Optional[float]         # DC to avoid/halve damage (None = automatic)
    save_ability: Optional[str]      # "DEX", "CON", etc.
    area_fraction: float             # Fraction of battlefield covered (0.0–1.0)
    push_into_possible: bool         # Can creatures be pushed into this zone?

@dataclass
class PortalPair:
    name: str
    entry_position: str              # "north_wall", "center", etc. (descriptive)
    exit_position: str
    bidirectional: bool = True       # Can be used in both directions?
    requires_action: bool = False    # Does using it cost an action?

@dataclass
class EnvironmentTemplate:
    name: str
    description: str

    # Cover and concealment
    cover_availability: float        # 0.0 = open field, 1.0 = dense cover
                                     # Translates to average miss chance bonus

    # Battlefield geometry
    choke_point: bool                # Restricts multi-target AoE efficiency
    choke_width: int                 # Creatures abreast in choke (default 2)
    multi_level: bool                # Has high ground / elevation differences
    high_ground_available: bool      # Ranged attackers can gain advantage
    size_category: str               # "tiny", "small", "medium", "large", "huge"
                                     # Affects AoE target count estimates

    # Movement
    movement_modifier: float         # 1.0 = normal, 0.5 = difficult terrain throughout
    difficult_terrain_fraction: float # Fraction of battlefield with difficult terrain

    # Hazards
    hazard_zones: list[HazardZone] = field(default_factory=list)

    # Ambush / surprise
    ambush_potential: float          # 0.0–1.0 chance of surprise round for either side
    concealment_for_defenders: bool  # Defenders start hidden (ambush setup)

    # Portals / special movement
    portal_pairs: list[PortalPair] = field(default_factory=list)

    # Environmental damage (passive — affects all creatures)
    passive_damage_per_round: float = 0.0
    passive_damage_type: str = ""

    # Tactical notes (human-readable, for outcome report)
    tactical_notes: str = ""

    # Source metadata
    source: str = "registry"         # "registry", "custom", "foundry", "ai_analysis"
```

---

## Named Template Registry

Pre-defined templates covering common encounter environments. DMs can use these
directly or as starting points for custom templates.

```python
from engine.environment.hazards import LAVA_PIT, CLIFF_EDGE, CHASM, SPIKE_PIT

ENVIRONMENT_TEMPLATES: dict[str, EnvironmentTemplate] = {

    # ── Open Terrain ──────────────────────────────────────────────────────────

    "open_field": EnvironmentTemplate(
        name="Open Field",
        description="Flat, featureless terrain with minimal cover.",
        cover_availability=0.05,
        choke_point=False, choke_width=10,
        multi_level=False, high_ground_available=False,
        size_category="huge",
        movement_modifier=1.0, difficult_terrain_fraction=0.0,
        ambush_potential=0.1, concealment_for_defenders=False,
        tactical_notes="AoE spells are highly effective. No cover bonus for either side.",
    ),

    "road_ambush": EnvironmentTemplate(
        name="Road Ambush",
        description="A road through light forest. Defenders hidden in tree line.",
        cover_availability=0.5,
        choke_point=True, choke_width=4,
        multi_level=False, high_ground_available=False,
        size_category="medium",
        movement_modifier=1.0, difficult_terrain_fraction=0.1,
        ambush_potential=0.75, concealment_for_defenders=True,
        tactical_notes="Defenders likely get surprise round. Road is choke point.",
    ),

    # ── Dungeon Environments ───────────────────────────────────────────────────

    "dungeon_corridor": EnvironmentTemplate(
        name="Dungeon Corridor",
        description="A narrow stone corridor. Single-file movement only.",
        cover_availability=0.2,
        choke_point=True, choke_width=2,
        multi_level=False, high_ground_available=False,
        size_category="small",
        movement_modifier=1.0, difficult_terrain_fraction=0.0,
        ambush_potential=0.3, concealment_for_defenders=False,
        tactical_notes=(
            "AoE heavily penalized — choke width 2 limits multi-target spells. "
            "Ranged PCs at back of marching order have poor lines of effect."
        ),
    ),

    "dungeon_chamber": EnvironmentTemplate(
        name="Dungeon Chamber",
        description="A medium-sized stone room with pillars for cover.",
        cover_availability=0.35,
        choke_point=False, choke_width=6,
        multi_level=False, high_ground_available=False,
        size_category="medium",
        movement_modifier=1.0, difficult_terrain_fraction=0.0,
        ambush_potential=0.2, concealment_for_defenders=False,
        tactical_notes="Pillars provide cover for ranged combatants on both sides.",
    ),

    "throne_room": EnvironmentTemplate(
        name="Throne Room",
        description="Large ornate hall. Raised dais at far end provides high ground.",
        cover_availability=0.15,
        choke_point=False, choke_width=8,
        multi_level=True, high_ground_available=True,
        size_category="large",
        movement_modifier=1.0, difficult_terrain_fraction=0.0,
        ambush_potential=0.15, concealment_for_defenders=False,
        tactical_notes=(
            "Boss on dais has high ground advantage on ranged attacks. "
            "PCs must spend movement to climb dais."
        ),
    ),

    # ── Wilderness ────────────────────────────────────────────────────────────

    "forest_clearing": EnvironmentTemplate(
        name="Forest Clearing",
        description="A clearing in dense forest. Tree line provides cover at edges.",
        cover_availability=0.55,
        choke_point=False, choke_width=6,
        multi_level=False, high_ground_available=False,
        size_category="medium",
        movement_modifier=0.85, difficult_terrain_fraction=0.2,
        ambush_potential=0.5, concealment_for_defenders=True,
        tactical_notes=(
            "Creatures at tree line have half cover. "
            "Difficult terrain at edges reduces kiting effectiveness."
        ),
    ),

    "mountain_pass": EnvironmentTemplate(
        name="Mountain Pass",
        description="Narrow high-altitude pass with rocky outcroppings.",
        cover_availability=0.4,
        choke_point=True, choke_width=3,
        multi_level=True, high_ground_available=True,
        size_category="medium",
        movement_modifier=0.7, difficult_terrain_fraction=0.4,
        hazard_zones=[CLIFF_EDGE],
        ambush_potential=0.4, concealment_for_defenders=True,
        tactical_notes=(
            "High ground on rocky outcroppings. Cliff edge — push effects lethal. "
            "Difficult terrain severely limits mobility."
        ),
    ),

    "swamp": EnvironmentTemplate(
        name="Swamp",
        description="Dense wetland with thick mud and shallow water throughout.",
        cover_availability=0.45,
        choke_point=False, choke_width=5,
        multi_level=False, high_ground_available=False,
        size_category="large",
        movement_modifier=0.5, difficult_terrain_fraction=0.8,
        ambush_potential=0.45, concealment_for_defenders=True,
        passive_damage_per_round=0.0,
        tactical_notes=(
            "Difficult terrain everywhere. Movement-denial spells (Web, Plant Growth) "
            "stack badly here — may reduce enemy DPR to near zero."
        ),
    ),

    # ── Hazardous Environments ────────────────────────────────────────────────

    "volcanic_cavern": EnvironmentTemplate(
        name="Volcanic Cavern",
        description="Cave system with active lava flows and toxic gases.",
        cover_availability=0.3,
        choke_point=False, choke_width=5,
        multi_level=True, high_ground_available=True,
        size_category="large",
        movement_modifier=0.8, difficult_terrain_fraction=0.3,
        hazard_zones=[LAVA_PIT],
        ambush_potential=0.2, concealment_for_defenders=False,
        passive_damage_per_round=2.0,
        passive_damage_type="fire",
        tactical_notes=(
            "Lava pits — push effects potentially lethal. "
            "Passive fire damage affects all creatures each round. "
            "Fire-resistant enemies gain major advantage here."
        ),
    ),

    "cliff_bridge": EnvironmentTemplate(
        name="Cliff Bridge",
        description="Narrow stone bridge over a deep chasm.",
        cover_availability=0.05,
        choke_point=True, choke_width=2,
        multi_level=False, high_ground_available=False,
        size_category="small",
        movement_modifier=0.75, difficult_terrain_fraction=0.0,
        hazard_zones=[CHASM],
        ambush_potential=0.2, concealment_for_defenders=False,
        tactical_notes=(
            "Extreme choke point — single file only. "
            "Push/grapple effects are potentially lethal (falling damage). "
            "AoE nearly useless. Melee dominates."
        ),
    ),

    "spike_pit_chamber": EnvironmentTemplate(
        name="Spike Pit Chamber",
        description="A trapped room with concealed spike pits in the floor.",
        cover_availability=0.2,
        choke_point=False, choke_width=5,
        multi_level=False, high_ground_available=False,
        size_category="medium",
        movement_modifier=0.9, difficult_terrain_fraction=0.0,
        hazard_zones=[SPIKE_PIT],
        ambush_potential=0.35, concealment_for_defenders=False,
        tactical_notes=(
            "Spike pits hidden until triggered (Perception DC). "
            "Push/shove effects may send creatures into pits. "
            "Defenders know pit locations — offensive positioning advantage."
        ),
    ),

    # ── Special / Unusual ────────────────────────────────────────────────────

    "arcane_portal_chamber": EnvironmentTemplate(
        name="Arcane Portal Chamber",
        description="A mystical chamber with active teleportation portals.",
        cover_availability=0.2,
        choke_point=False, choke_width=6,
        multi_level=False, high_ground_available=False,
        size_category="large",
        movement_modifier=1.0, difficult_terrain_fraction=0.0,
        portal_pairs=[
            PortalPair("North-South Portal", "north_wall", "south_wall", bidirectional=True),
            PortalPair("East-West Portal",   "east_wall",  "west_wall",  bidirectional=True),
        ],
        ambush_potential=0.15, concealment_for_defenders=False,
        tactical_notes=(
            "Portals allow instant repositioning. High-INT creatures will exploit portals "
            "to escape encirclement or reposition for AoE. "
            "Engine must track portal awareness by INT score."
        ),
    ),

    "tavern_brawl": EnvironmentTemplate(
        name="Tavern Brawl",
        description="Cramped interior with tables, chairs, and a bar for improvised cover.",
        cover_availability=0.5,
        choke_point=False, choke_width=4,
        multi_level=False, high_ground_available=False,
        size_category="small",
        movement_modifier=0.8, difficult_terrain_fraction=0.3,
        ambush_potential=0.1, concealment_for_defenders=False,
        tactical_notes=(
            "Improvised weapons available. Difficult terrain from overturned furniture. "
            "AoE spells risk hitting bystanders — behavioral constraint on casters."
        ),
    ),

    "underwater": EnvironmentTemplate(
        name="Underwater",
        description="Fully submerged combat in open water or a flooded chamber.",
        cover_availability=0.1,
        choke_point=False, choke_width=8,
        multi_level=True, high_ground_available=False,
        size_category="large",
        movement_modifier=0.5, difficult_terrain_fraction=1.0,
        ambush_potential=0.3, concealment_for_defenders=False,
        passive_damage_per_round=0.0,
        tactical_notes=(
            "Creatures without swim speed have disadvantage on attacks. "
            "Many ranged weapons unusable. Fire spells don't work. "
            "Full 3D movement — flying creatures have no advantage. "
            "Breath weapons / most AoE shapes behave differently."
        ),
    ),

    "haunted_graveyard": EnvironmentTemplate(
        name="Haunted Graveyard",
        description="Open graveyard at night. Tombstones for cover, open graves as hazards.",
        cover_availability=0.35,
        choke_point=False, choke_width=6,
        multi_level=False, high_ground_available=False,
        size_category="large",
        movement_modifier=0.9, difficult_terrain_fraction=0.15,
        hazard_zones=[SPIKE_PIT],  # Reusing spike pit as open grave (fall damage)
        ambush_potential=0.6, concealment_for_defenders=True,
        tactical_notes=(
            "Undead enemies likely have darkvision — PCs may be at disadvantage at night. "
            "Open graves as hazards (fall into grave = 1d6 bludgeoning + prone). "
            "Concealment for ambushing undead rising from graves."
        ),
    ),
}
```

---

## Standard Hazard Definitions

```python
# engine/environment/hazards.py

LAVA_PIT = HazardZone(
    name="Lava Pit",
    damage_per_round=55.0,           # 10d10 average — instantly lethal for most creatures
    damage_type="fire",
    save_dc=None,                    # No save — automatic damage if in zone
    save_ability=None,
    area_fraction=0.15,
    push_into_possible=True,
)

CLIFF_EDGE = HazardZone(
    name="Cliff Edge",
    damage_per_round=0.0,            # No passive damage
    damage_type="bludgeoning",
    save_dc=None,
    save_ability=None,
    area_fraction=0.10,
    push_into_possible=True,         # Push = falling damage (1d6 per 10ft)
)

CHASM = HazardZone(
    name="Chasm",
    damage_per_round=0.0,
    damage_type="bludgeoning",
    save_dc=None,
    save_ability=None,
    area_fraction=0.20,
    push_into_possible=True,         # Fall = likely lethal
)

SPIKE_PIT = HazardZone(
    name="Spike Pit",
    damage_per_round=11.0,           # 2d10 average fall + spike damage
    damage_type="piercing",
    save_dc=15.0,
    save_ability="DEX",
    area_fraction=0.10,
    push_into_possible=True,
)

ACID_POOL = HazardZone(
    name="Acid Pool",
    damage_per_round=22.0,           # 4d10 average
    damage_type="acid",
    save_dc=13.0,
    save_ability="DEX",
    area_fraction=0.10,
    push_into_possible=True,
)

ELECTRIFIED_FLOOR = HazardZone(
    name="Electrified Floor",
    damage_per_round=14.0,           # 4d6 average
    damage_type="lightning",
    save_dc=14.0,
    save_ability="DEX",
    area_fraction=0.25,
    push_into_possible=False,        # Area-wide, not push-specific
)
```

---

## How Environment Affects the Engine

### 1. AoE Efficiency (Encounter Multiplier Modifier)

Choke points reduce the number of targets an AoE can hit. This feeds directly into
the encounter multiplier calculation from `finished-book-summary.md`.

```python
def aoe_target_estimate(spell_aoe_type: str, env: EnvironmentTemplate,
                         n_enemies: int) -> float:
    """
    Estimates expected targets hit by AoE given environment constraints.
    Choke points severely limit AoE; open fields maximize it.
    """
    base_targets = min(n_enemies, estimate_base_aoe_targets(spell_aoe_type))

    if env.choke_point:
        # In a corridor, AoE hits at most choke_width creatures
        return min(base_targets, env.choke_width)

    # Open terrain: scale by cover availability (creatures spread out more with cover)
    spread_factor = 1.0 - (env.cover_availability * 0.3)
    return base_targets * spread_factor
```

### 2. Cover (Miss Chance Bonus)

```python
def cover_miss_bonus(env: EnvironmentTemplate, creature_using_cover: bool) -> float:
    """
    Returns additional miss probability from cover.
    Half cover: +2 AC (≈ +10% miss). Three-quarters: +5 AC (≈ +25% miss).
    """
    if not creature_using_cover:
        return 0.0
    if env.cover_availability >= 0.5:
        return 0.25   # Three-quarters cover available
    if env.cover_availability >= 0.2:
        return 0.10   # Half cover available
    return 0.0
```

### 3. High Ground

```python
def high_ground_attack_bonus(env: EnvironmentTemplate,
                              actor_has_high_ground: bool) -> float:
    """Advantage on ranged attacks from high ground ≈ +20% hit chance at baseline."""
    if env.high_ground_available and actor_has_high_ground:
        return 0.20
    return 0.0
```

### 4. Hazard Valuation (Push Effects)

```python
def push_into_hazard_value(target, hazard: HazardZone) -> float:
    """
    Returns eHP value of successfully pushing a target into a hazard zone.
    Used by the AI to evaluate Shove, Thunderwave, etc.
    """
    if not hazard.push_into_possible:
        return 0.0

    # For instant-kill hazards (lava, deep chasm), value = target's remaining eHP
    if hazard.damage_per_round >= target.hp_current:
        return target.hp_current  # Effectively removes creature from combat

    # For damage hazards, value = expected damage
    if hazard.save_dc:
        fail_prob = calc_fail_probability(hazard.save_dc,
                                          getattr(target, f"{hazard.save_ability.lower()}_save"))
        return hazard.damage_per_round * fail_prob
    return hazard.damage_per_round
```

### 5. Movement Denial Stacking

```python
def effective_movement_denial(env: EnvironmentTemplate,
                               spell_denial: float) -> float:
    """
    Movement denial from spells and difficult terrain stack multiplicatively.
    A Web spell (50% denial) in a swamp (50% movement modifier) = ~75% denial.
    """
    env_denial = 1.0 - env.movement_modifier
    combined = 1.0 - ((1.0 - env_denial) * (1.0 - spell_denial))
    return min(1.0, combined)
```

---

## Custom Template Construction

DMs can build custom templates via the UI without touching code. The UI writes
directly to an `EnvironmentTemplate` object with the same structure.

```python
def build_custom_template(
    name: str,
    cover: float = 0.2,
    choke_point: bool = False,
    choke_width: int = 6,
    high_ground: bool = False,
    movement_mod: float = 1.0,
    difficult_terrain: float = 0.0,
    ambush: float = 0.1,
    hazards: list[HazardZone] = None,
    portals: list[PortalPair] = None,
    tactical_notes: str = "",
) -> EnvironmentTemplate:
    return EnvironmentTemplate(
        name=name,
        description="Custom template",
        cover_availability=cover,
        choke_point=choke_point, choke_width=choke_width,
        multi_level=high_ground, high_ground_available=high_ground,
        size_category="medium",
        movement_modifier=movement_mod,
        difficult_terrain_fraction=difficult_terrain,
        hazard_zones=hazards or [],
        ambush_potential=ambush,
        concealment_for_defenders=False,
        portal_pairs=portals or [],
        tactical_notes=tactical_notes,
        source="custom",
    )
```

---

## Foundry Scene Adapter (Phase 2)

When the Foundry bridge exists, scene data is converted into an `EnvironmentTemplate`.
The engine receives the same object type regardless of source.

```python
def template_from_foundry_scene(scene_data: dict) -> EnvironmentTemplate:
    """
    Converts Foundry VTT scene JSON into an EnvironmentTemplate.
    Reads: walls (for choke detection), terrain tiles, lighting, elevation flags.
    Phase 2 implementation — stub only.
    """
    raise NotImplementedError("Foundry scene adapter — Phase 2")
```

---

## AI Map Analysis Adapter (Phase 4)

```python
def template_from_map_image(image_path: str) -> EnvironmentTemplate:
    """
    Uses computer vision to extract tactical features from a map image.
    Identifies: cover objects, choke points, hazard areas, elevation changes.
    Phase 4 implementation — stub only.
    """
    raise NotImplementedError("AI map analysis — Phase 4")
```

---

## Adding New Templates

To add a new named template to the registry:

1. Define any new `HazardZone` objects needed in `engine/environment/hazards.py`
2. Add the `EnvironmentTemplate` to `ENVIRONMENT_TEMPLATES` in `engine/environment/templates.py`
3. Add a test in `tests/test_environment.py` validating the template's property values
4. Document any non-obvious tactical interactions in the `tactical_notes` field

No other files need to change. The engine picks up new templates automatically.

---

## Open Decisions

- [ ] Ambush/surprise round mechanics — how does `ambush_potential` translate to
      initiative advantage in the engine? (Related to initiative system in
      `finished-book-summary.md` Section VIII)
- [ ] Portal usage by AI — how does creature INT gate portal awareness?
- [ ] Underwater combat rules — attack disadvantage, weapon restrictions, spell
      modifications. Needs its own section in `conditions-and-edge-cases.md`
- [ ] Passive environmental damage — applied at start of turn, end of turn, or
      on entry? Needs policy decision.
- [ ] Bystander constraint — how does the engine model the tavern brawl case where
      casters self-restrict AoE to avoid hitting innocents?
