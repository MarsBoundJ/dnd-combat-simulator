# Data Sources

**Status:** 🟡 Policy defined — implementation pending  
**Last updated:** 2026-03-30

---

## The Legal Boundary (Read This First)

Wizards of the Coast's content — monster stat blocks, spell descriptions, class features, magic item properties — is **copyrighted material**. This includes everything in the Player's Handbook, Dungeon Master's Guide, Monster Manual, and all other official sourcebooks for D&D 5e/5.5e.

**This repository will never contain:**
- Monster stat blocks copied from official WotC sources
- Spell text or descriptions from official sourcebooks
- Class feature text or subclass content
- Magic item properties or descriptions
- Any other copyrighted game content

This is not a technicality. It applies even if:
- The repo is for personal use
- The content is for a non-commercial project
- The content is "just for testing"
- The content is already widely available online

Violating this would expose the project to a DMCA takedown and potentially Phil personally. **When in doubt, don't commit it.**

---

## What Is Legally Safe

**The Systems Reference Document (SRD 5.1 and 5.2)**  
WotC releases a subset of D&D content under a Creative Commons license. This content — roughly 400 monsters, core spells, base classes — can be used freely. It is incomplete but legally unambiguous.  
SRD 5.1: https://dnd.wizards.com/resources/systems-reference-document  
SRD 5.2 (2024 rules): https://www.dndbeyond.com/srd

**Stat block structure and mechanical values**  
The *structure* of a stat block (AC, HP, attack bonus, damage dice, saving throws) is not copyrightable — only the specific creative expression (flavor text, lore, names in some cases) is protected. The engine can legally operate on mechanical values extracted by the user from their own licensed books.

**User-owned content**  
If the user owns a licensed copy of the Monster Manual and imports it into Foundry VTT via a licensed module, the engine can operate on that data at runtime. The data lives in the user's Foundry installation, not in this repo.

---

## Architecture Decision: The Data Layer

### Primary Approach — Foundry as the Data Runtime

Since Foundry VTT is the front end, it is also the data layer. The user's Foundry installation contains their licensed content (imported via D&D Beyond integration, purchased Foundry modules, or manual entry). The engine receives stat block data from Foundry at runtime and operates on it.

**What this means in practice:**
- The engine defines a schema (what fields it needs)
- Foundry provides the values that populate that schema
- Nothing is stored in this repo except the schema itself
- The user's content license is their own responsibility

This is the same model used by every serious Foundry module and is the legally correct approach for a public repository.

### Development/Testing Fallback — Open5e API

While building and testing the engine before a full Foundry integration exists, the simulator uses the Open5e API as its data source.

**Open5e:** https://open5e.com / https://api.open5e.com  
- Free, open REST API
- Covers full SRD content plus significant community-contributed 5e material
- No authentication required
- Well-maintained and actively developed
- Not completist, but sufficient for engine development and testing

```python
# Example: fetch a monster from Open5e
import requests

def get_monster(slug: str) -> dict:
    """
    Fetch monster data from Open5e API.
    slug examples: 'goblin', 'adult-red-dragon', 'beholder'
    """
    response = requests.get(f"https://api.open5e.com/v1/monsters/{slug}/")
    response.raise_for_status()
    return response.json()
```

### High-Profile 3rd Party and Homebrew Content

For the simulator's ambition to cover high-profile 3p publishers (Kobold Press, MCDM, Darrington Press) and homebrew:

- **3p content:** Same rule applies — cannot be stored in the repo. If the publisher has released content under OGL or CC, it can be referenced. Otherwise, user must supply it via Foundry.
- **MCDM content (e.g., Illrigger):** MCDM releases PDFs and Foundry modules. Users who own those modules can import the data into their Foundry world. The engine operates on whatever Foundry provides.
- **Homebrew:** User-created content in Foundry is fair game — it's the user's own work.
- **UA (Unearthed Arcana):** WotC releases UA under a free playtest license but it is still copyrighted. Same rule — engine can operate on it if the user supplies it, but it cannot be stored in the repo.

---

## Data Schema (What the Engine Needs)

The engine does not care about flavor text, lore, or descriptions. It only needs mechanical values. This schema defines the interface contract between Foundry and the engine.

### Monster Schema

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class AttackAction:
    name: str
    attack_bonus: float          # AB for attack rolls, or None if save-based
    save_dc: Optional[float]     # DC if save-based, else None
    save_ability: Optional[str]  # "DEX", "CON", etc.
    damage_dice_mean: float      # Expected damage on hit/fail
    damage_dice_variance: float  # Variance of damage roll
    is_legendary: bool = False
    is_multiattack: bool = False
    targets: int = 1             # Number of targets (for AoE)

@dataclass
class MonsterStatBlock:
    name: str
    cr: float
    hp: float
    hp_variance: float
    ac: float
    speed: int                   # ft per round
    
    # Saving throw bonuses (use calc_sb_from_ac() if not provided)
    str_save: float
    dex_save: float
    con_save: float
    int_save: float
    wis_save: float
    cha_save: float
    
    # Offense
    attack_bonus: float          # Primary AB (weighted eAB calculated by engine)
    attacks: list[AttackAction] = field(default_factory=list)
    
    # Special properties
    is_legendary: bool = False
    legendary_actions: int = 0
    legendary_resistances: int = 0
    has_lair_actions: bool = False
    
    # Conditions and immunities
    damage_immunities: list[str] = field(default_factory=list)
    damage_resistances: list[str] = field(default_factory=list)
    condition_immunities: list[str] = field(default_factory=list)
    
    # Initiative
    initiative_modifier: float = 0.0
```

### Player Character Schema

```python
@dataclass
class PCStatBlock:
    name: str
    level: int
    character_class: str
    subclass: Optional[str]
    
    hp: float
    hp_max: float
    ac: float
    
    # Offense
    attack_bonus: float          # Primary AB or spell attack bonus
    save_dc: Optional[float]     # Spell save DC if applicable
    dpr_hit: float               # Expected DPR assuming all attacks hit (single target)
    
    # Saving throws
    str_save: float
    dex_save: float
    con_save: float
    int_save: float
    wis_save: float
    cha_save: float
    
    # Resources
    spell_slots: dict[int, int] = field(default_factory=dict)  # {level: remaining}
    hit_dice_remaining: int = 0
    
    # Magic item adjustments (see finished-book-summary.md Section X)
    magic_item_ab_bonus: float = 0.0
    magic_item_ac_bonus: float = 0.0
    magic_item_damage_bonus: float = 0.0
    
    # Initiative
    initiative_modifier: float = 0.0
```

### Spell Schema

```python
@dataclass
class SpellData:
    name: str
    level: int                   # 0 = cantrip
    school: str
    casting_time: str            # "action", "bonus_action", "reaction"
    
    # Mechanical effect type
    is_attack_roll: bool
    is_saving_throw: bool
    save_ability: Optional[str]
    
    # Damage
    damage_dice_mean: float
    damage_dice_variance: float
    damage_type: str
    
    # Targeting
    targets: int                 # 1 = single target; >1 = AoE
    aoe_type: Optional[str]      # "cone", "sphere", "line", "cylinder"
    
    # Concentration
    requires_concentration: bool
    duration_rounds: Optional[int]
    
    # Half damage on save
    half_damage_on_save: bool = False
```

---

## Implementation Phases

| Phase | Data Source | Purpose |
|---|---|---|
| **Phase 1 — Engine dev** | Open5e API | Build and validate math engine against SRD monsters |
| **Phase 2 — Foundry bridge** | Foundry runtime data | Wire engine to live Foundry world data |
| **Phase 3 — Extended coverage** | User-supplied via Foundry modules | 3p, homebrew, UA content via user's own licenses |

---

## What Never Goes in This Repo

To be explicit, a standing list of what must never be committed:

| Content Type | Reason |
|---|---|
| Monster stat blocks from WotC books | Copyright |
| Spell descriptions or text | Copyright |
| Class/subclass feature text | Copyright |
| Magic item descriptions | Copyright |
| UA playtest content | Copyright (even though free to use) |
| 3p publisher content | Copyright (unless explicitly CC/OGL licensed) |
| Any JSON/CSV dump of the above | Same copyright, different format |

**The test:** if you didn't write it yourself or it isn't explicitly CC/OGL licensed, it doesn't go in the repo.

---

## References

- SRD 5.1 Creative Commons license: https://dnd.wizards.com/resources/systems-reference-document
- Open5e project: https://open5e.com
- Foundry VTT dnd5e system: https://github.com/foundryvtt/dnd5e
- D&D Beyond Foundry importer (community): https://github.com/MrPrimate/ddb-importer
