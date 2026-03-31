# Ammann Behavior Framework

**Source:** Keith Ammann — *The Monsters Know What They're Doing* (blog and book series)  
**Blog:** https://www.themonstersknow.com  
**Books:** TMKWTD (2019), MOAR! (2022), Live to Tell the Tale (2020), How to Defend Your Lair (2022)  
**Status:** ✅ Draft complete — 2026-03-30  
**Location in engine:** `engine/ai/decision.py`, `engine/ai/targeting.py`

---

## Purpose

Where `finished-book-summary.md` answers **"how much is this action worth mathematically?"**,  
this document answers **"which action would this creature actually choose, and why?"**

Ammann's method: read the lore, analyze the stat block, deduce the mindset, then find the
optimal behavior *within that mindset*. Monsters are not cold calculators — they are
creatures with instincts, fears, intelligence levels, and social structures that constrain
and shape their decisions. The engine must respect those constraints or combat will feel
like a math problem rather than a living encounter.

---

## Ammann's Core Methodology

### Step 1 — Read the Lore First
Before looking at stats, determine what the creature *is*:
- What does it want? (food, territory, treasure, worship, chaos)
- What does it fear? (death, fire, sunlight, its master)
- How intelligent is it? (INT score as a proxy)
- Is it social? (does it coordinate with allies or act alone)
- Is it predatory, defensive, or opportunistic?

### Step 2 — Analyze the Stat Block for Capability
What *can* the creature do?
- Which attacks deal the most damage?
- Which features give it unusual advantages (flight, invisibility, multiattack)?
- What are its saving throw strengths and weaknesses?
- What is its movement speed and type?

### Step 3 — Derive Behavior from Mindset + Capability
The creature will pursue its goal using its best available tools, constrained by its
nature. A goblin *could* stand and fight to the death — but a goblin *wouldn't*,
because goblins are cowardly opportunists who value self-preservation over honor.

### Step 4 — Encode as Priority-Ordered Decision Rules
The output is a ranked list of conditions and actions: "If X, do Y. If Y is not
available, do Z."

---

## The Behavioral Profile

Every creature in the engine has a behavioral profile with the following fields:

```python
@dataclass
class BehaviorProfile:
    # Identity
    creature_type: str           # "beast", "humanoid", "undead", "fiend", etc.
    intelligence: int            # INT score — drives decision complexity
    social_structure: str        # "solitary", "pack", "hierarchical", "swarm"

    # Combat disposition
    aggression_coefficient: float        # 0.5 (cautious) to 1.5 (reckless)
    self_preservation_coefficient: float # 0.0 (mindless) to 2.0 (cowardly)
    morale_threshold: float              # HP% at which creature considers fleeing

    # Targeting preferences
    target_priority: str         # "nearest", "weakest", "most_dangerous", "spellcaster"
    focus_fire: bool             # Does creature coordinate focus-fire with allies?

    # Tactical tendencies
    uses_cover: bool
    uses_flanking: bool
    kites_if_ranged: bool        # Stays at range if it has ranged attacks
    retreats_to_heal: bool
    wakes_allies: bool           # Will spend action to wake incapacitated ally

    # Special flags
    fears: list[str]             # ["fire", "sunlight", "turning"] — triggers retreat
    enrage_threshold: float      # HP% at which creature becomes reckless (0 = never)
```

---

## Intelligence as Decision Complexity

INT score is the single most important behavioral modifier. It determines how many
moves ahead the creature can "think" and how tactically sophisticated its decisions are.

| INT Score | Category | Decision Complexity |
|---|---|---|
| 1–3 | Animal / Mindless | Pure instinct — no tactics, no retreating, no coordination |
| 4–6 | Low | Basic survival — will flee when hurt, won't coordinate |
| 7–9 | Below Average | Simple tactics — uses best attack, may retreat if losing |
| 10–12 | Average | Moderate tactics — targets weak PCs, uses abilities correctly |
| 13–15 | High | Good tactics — coordinates with allies, reads battlefield |
| 16–18 | Very High | Advanced tactics — exploits positioning, conserves resources |
| 19+ | Exceptional | Near-optimal play within behavioral constraints |

```python
def decision_depth(intelligence: int) -> int:
    """
    Returns how many actions ahead the creature plans.
    Low INT = reactive (depth 0-1). High INT = proactive (depth 2-3).
    """
    if intelligence <= 3:  return 0   # Pure instinct
    if intelligence <= 6:  return 1   # One move ahead
    if intelligence <= 12: return 1   # Reactive
    if intelligence <= 16: return 2   # Plans one round ahead
    return 3                          # Plans two rounds ahead
```

---

## Behavioral Archetypes

These are the generalizable archetypes derived from Ammann's per-monster analyses.
Each creature maps to one primary archetype and optionally one secondary.

### Archetype 1: Mindless Aggressor
**Examples:** Zombie, Skeleton, Animated Object  
**Profile:** INT 1–6, SPC = 0.0, morale_threshold = 0.0  
**Behavior:** Moves toward nearest enemy and attacks. No tactics. No retreat. No coordination. Will attack a downed PC if it's closer than a standing one.

```python
MINDLESS_AGGRESSOR = BehaviorProfile(
    aggression_coefficient=1.0,
    self_preservation_coefficient=0.0,
    morale_threshold=0.0,
    target_priority="nearest",
    focus_fire=False,
    uses_cover=False,
    uses_flanking=False,
    kites_if_ranged=False,
    retreats_to_heal=False,
    wakes_allies=False,
    fears=[],
    enrage_threshold=0.0,
)
```

### Archetype 2: Cowardly Skirmisher
**Examples:** Goblin, Kobold, Stirge  
**Profile:** INT 8–10, SPC = 1.5–2.0, morale_threshold = 0.35–0.50  
**Behavior:** Strikes opportunistically, disengages when threatened. Pack Tactics when
outnumbering, flees when outnumbered. Will not fight to the death. Goblins specifically:
use Nimble Escape to Hide after attacking, target isolated or wounded PCs, scatter
when leader falls.

```python
COWARDLY_SKIRMISHER = BehaviorProfile(
    aggression_coefficient=0.7,
    self_preservation_coefficient=1.8,
    morale_threshold=0.40,
    target_priority="weakest",
    focus_fire=False,
    uses_cover=True,
    uses_flanking=True,
    kites_if_ranged=True,
    retreats_to_heal=False,
    wakes_allies=False,
    fears=["fire", "turning"],
    enrage_threshold=0.0,
)
```

### Archetype 3: Pack Hunter
**Examples:** Wolf, Gnoll, Hobgoblin, Bandit  
**Profile:** INT 6–12, SPC = 1.0, social_structure = "pack"  
**Behavior:** Coordinates with allies. Focus-fires the same target. Uses flanking.
Protects the alpha/leader. May retreat if pack is heavily depleted but not if evenly
matched. Hobgoblins specifically: use martial advantage, protect formation, follow
orders from highest-INT member.

```python
PACK_HUNTER = BehaviorProfile(
    aggression_coefficient=1.0,
    self_preservation_coefficient=1.0,
    morale_threshold=0.25,
    target_priority="most_dangerous",  # threat assessment
    focus_fire=True,
    uses_cover=False,
    uses_flanking=True,
    kites_if_ranged=False,
    retreats_to_heal=False,
    wakes_allies=True,
    fears=[],
    enrage_threshold=0.0,
)
```

### Archetype 4: Apex Predator
**Examples:** Adult Dragon, Beholder, Mind Flayer, Vampire  
**Profile:** INT 16+, SPC = 1.0–1.3, uses full tactical toolkit  
**Behavior:** Maximizes positioning advantage. Exploits flight/range to nullify melee
threats. Uses breath weapons/special abilities at optimal moments. Targets spellcasters
and healers first. Respects legendary resistance as a finite resource — won't burn it
on low-stakes saves. May parley if reduced below morale threshold.

```python
APEX_PREDATOR = BehaviorProfile(
    aggression_coefficient=1.2,
    self_preservation_coefficient=1.2,
    morale_threshold=0.20,
    target_priority="spellcaster",
    focus_fire=True,
    uses_cover=True,
    uses_flanking=True,
    kites_if_ranged=True,
    retreats_to_heal=True,
    wakes_allies=True,
    fears=[],
    enrage_threshold=0.15,  # becomes reckless near death
)
```

### Archetype 5: Territorial Defender
**Examples:** Owlbear, Brown Bear, Hill Giant  
**Profile:** INT 5–8, SPC = 1.0, morale_threshold = 0.30  
**Behavior:** Defends its space rather than pursuing. Attacks the closest threat.
Will retreat to its lair if losing badly. Does not coordinate. Not malicious —
just protecting territory. Will disengage if the PCs back off.

### Archetype 6: Fanatical True Believer
**Examples:** Cultist, Berserker, Gnoll Fang of Yeenoghu  
**Profile:** Any INT, SPC = 0.2–0.5, morale_threshold = 0.0  
**Behavior:** Will not retreat. Will not negotiate. Attacks relentlessly. May enrage
at low HP rather than flee. Morale check always fails (they don't break).

---

## Targeting Priority Rules

When a creature has multiple valid targets, it applies these rules in order.
Higher-INT creatures apply more rules; lower-INT creatures use only the first 1–2.

```python
def select_target(actor, valid_targets: list, state) -> Target:
    """
    Returns the selected target based on the actor's behavioral profile.
    Applied in priority order — first rule that produces a valid target wins.
    """
    profile = actor.behavior_profile

    # Rule 0: Fear override — flee from feared stimuli regardless of anything else
    if is_feared_stimulus_present(actor, state):
        return flee_action(actor, state)

    # Rule 1: Finish off near-death targets (opportunistic kill — all archetypes)
    near_death = [t for t in valid_targets if t.hp_fraction < 0.15]
    if near_death and profile.intelligence >= 4:
        return min(near_death, key=lambda t: t.hp_current)

    # Rule 2: Target priority by archetype
    if profile.target_priority == "nearest":
        return min(valid_targets, key=lambda t: distance(actor, t))

    if profile.target_priority == "weakest":
        return min(valid_targets, key=lambda t: t.hp_current)

    if profile.target_priority == "most_dangerous":
        return max(valid_targets, key=lambda t: estimate_threat(t, state))

    if profile.target_priority == "spellcaster":
        spellcasters = [t for t in valid_targets if t.is_spellcaster]
        if spellcasters:
            return min(spellcasters, key=lambda t: t.hp_current)
        # Fall back to most dangerous if no spellcasters visible
        return max(valid_targets, key=lambda t: estimate_threat(t, state))

    # Default: nearest
    return min(valid_targets, key=lambda t: distance(actor, t))
```

---

## Morale System

Creatures check morale when certain thresholds are crossed. This is Ammann's most
important contribution to realistic combat — creatures that should flee, flee.

```python
def morale_check(actor, state, trigger: str) -> str:
    """
    Returns "hold", "flee", or "surrender" based on morale state.
    trigger: "hp_threshold", "ally_died", "leader_died", "outnumbered"
    """
    profile = actor.behavior_profile

    # Mindless creatures never check morale
    if profile.self_preservation_coefficient == 0.0:
        return "hold"

    hp_fraction = actor.hp_current / actor.hp_max

    # Primary morale threshold
    if hp_fraction <= profile.morale_threshold:
        if profile.self_preservation_coefficient >= 1.5:
            return "flee"
        else:
            return "hold"  # Brave creatures fight on

    # Leader died — pack creatures may break
    if trigger == "leader_died" and profile.social_structure in ("pack", "hierarchical"):
        if profile.intelligence <= 8:
            return "flee"  # Low-INT pack scatters when leader falls

    # Heavily outnumbered
    if trigger == "outnumbered":
        enemy_count = len([c for c in state.combatants if c.side != actor.side])
        ally_count  = len([c for c in state.combatants if c.side == actor.side])
        if enemy_count > ally_count * 2 and profile.self_preservation_coefficient > 1.0:
            return "flee"

    return "hold"
```

---

## The Wake-Ally Decision

One of Ammann's key insights: intelligent creatures will spend an action to wake an
incapacitated ally if the math favors it. The engine encodes this explicitly.

```python
def should_wake_ally(actor, sleeping_ally, state) -> bool:
    """
    Returns True if waking the ally is worth spending the actor's action.
    """
    if not actor.behavior_profile.wakes_allies:
        return False
    if actor.behavior_profile.intelligence < 8:
        return False  # Not smart enough to reason about this

    # Compare: value of waking ally vs. value of attacking
    ally_dpr = sleeping_ally.effective_dpr(state)
    actor_dpr = actor.effective_dpr(state)

    # Worth it if ally DPR > actor's own attack DPR
    # (sacrificing 1 attack to restore a stronger attacker)
    return ally_dpr > actor_dpr * 1.2  # 20% threshold to make it clearly worthwhile
```

---

## Legendary Resistance Policy

Intelligent creatures with Legendary Resistance treat it as a finite resource.
They will NOT spend it on:
- Low-damage saves (less than 15% of their max HP in expected damage)
- Saves against effects that don't meaningfully change the encounter
- Saves when at full HP against non-incapacitating effects

They WILL spend it on:
- Incapacitation (Banishment, Hold Monster, Hypnotic Pattern)
- Effects that would end the encounter immediately
- Concentration-requiring effects that would last multiple rounds

```python
def spend_legendary_resistance(actor, save_effect, state) -> bool:
    """
    Returns True if the creature should spend Legendary Resistance on this save.
    Only called when the creature has already failed the save roll.
    """
    if actor.legendary_resistances_remaining <= 0:
        return False
    if actor.behavior_profile.intelligence < 10:
        return False  # Not smart enough to manage resources

    # Always spend on incapacitating effects
    if save_effect.causes_incapacitation:
        return True

    # Spend if effect lasts multiple rounds and deals significant damage
    if save_effect.duration_rounds >= 2:
        expected_damage = save_effect.damage_per_round * save_effect.duration_rounds
        if expected_damage > actor.hp_max * 0.20:
            return True

    return False
```

---

## Behavioral Profile Registry

The engine maintains a registry mapping monster types to default behavioral profiles.
This is seeded from Ammann's analyses and can be overridden per-encounter.

```python
BEHAVIOR_REGISTRY = {
    # Undead
    "zombie":           MINDLESS_AGGRESSOR,
    "skeleton":         MINDLESS_AGGRESSOR,

    # Humanoids
    "goblin":           COWARDLY_SKIRMISHER,
    "kobold":           COWARDLY_SKIRMISHER,
    "hobgoblin":        PACK_HUNTER,
    "orc":              PACK_HUNTER,
    "bandit":           PACK_HUNTER,

    # Beasts
    "wolf":             PACK_HUNTER,
    "brown_bear":       TERRITORIAL_DEFENDER,
    "owlbear":          TERRITORIAL_DEFENDER,

    # Apex
    "adult_red_dragon": APEX_PREDATOR,
    "beholder":         APEX_PREDATOR,
    "mind_flayer":      APEX_PREDATOR,

    # Fanatics
    "berserker":        FANATICAL_TRUE_BELIEVER,
    "cultist":          FANATICAL_TRUE_BELIEVER,
}

def get_behavior_profile(monster_slug: str) -> BehaviorProfile:
    """Returns behavioral profile for a monster, defaulting to PACK_HUNTER."""
    return BEHAVIOR_REGISTRY.get(monster_slug, PACK_HUNTER)
```

---

## Relationship to The Finished Book

Ammann governs **which action to choose**.  
The Finished Book governs **how much that action is worth**.

The decision pipeline is:

```
1. Ammann: enumerate candidate actions filtered by behavioral constraints
2. Finished Book (eHP framework): score each candidate action
3. Ammann: apply behavioral weights (aggression, self-preservation)
4. Select highest-scoring action
5. Ammann: morale check — override with flee/surrender if triggered
```

Conflicts between the two pillars are resolved in `pillars-reconciliation.md`.

---

## Source Notes

The behavioral profiles and archetypes in this document are derived from Ammann's
analytical methodology, not copied from his text. The specific coefficients
(aggression, self-preservation thresholds) are the simulator's own implementations
of his qualitative framework in quantitative terms.

Ammann's per-monster analyses (available on the blog at themonstersknow.com) should
be consulted when adding new monster profiles to the registry. The blog is the
authoritative source for individual monster behavior; this document encodes the
generalizable framework.

**Books in the series (for reference, not for copying):**
- *The Monsters Know What They're Doing* (2019) — Monster Manual creatures
- *MOAR! Monsters Know What They're Doing* (2022) — Volo's and Mordenkainen's creatures
- *Live to Tell the Tale* (2020) — Player character tactics
- *How to Defend Your Lair* (2022) — Villain and lair design
