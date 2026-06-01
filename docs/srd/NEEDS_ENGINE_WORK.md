# Spells That Need Engine Work

Spells from the priority list that the browser lane CANNOT build because
they need new engine primitives or systems. Desktop lane builds the system
first, then the spell rides it.

## Summon / Animate system
- **Animate Objects** (L5, P5) — animate N objects as creatures under caster control
- **Conjure Animals** (L3, P5) — summon creatures that act on caster's turn
- **Conjure Elemental** (L5, P4)
- **Conjure Fey** (L6, P3)
- **Conjure Minor Elementals** (L4, P4)
- **Conjure Celestial** (L7, P3)
- **Summon Dragon** (L5, P4)
- **Create Undead** (L6, P3)
- **Animate Dead** (L3, P4)

## Teleport / Positional system
- **Misty Step** (L2, P5) — bonus-action teleport 30 ft
- **Dimension Door** (L4, P5) — 500-ft teleport
- **Teleport** (L7, P3)

## Form-replacement system (Polymorph family)
- **Polymorph** (L4, P5) — replace target's stat block entirely
- **True Polymorph** (L9, P5)
- **Shapechange** (L9, P5)

## Wall / Terrain system
- **Wall of Fire** (L4, P5) — line/ring wall, damage on pass-through or end-turn near
- **Wall of Force** (L5, P5) — impassable barrier
- **Prismatic Wall** (L9, P5) — multi-layered wall with per-layer effects
- **Forcecage** (L7, P5) — enclosed barrier

## Movement-through-zone damage + Grapple drag
- **Spike Growth** (L2, P5) — damage per 5 ft moved through the area. The
  tactical value is the "cheese grater" combo: a grappler drags an enemy
  through the zone on their turn, triggering damage per 5 ft. Needs:
  forced-movement-through-zone damage triggers, grapple mechanics, and
  party-coordinated movement (martial drags on their turn, Druid's spell
  fires). All three are new engine systems.

## Action-economy grant
- **Haste** (L3, P5) — grants an extra action per turn + speed/AC buffs.
  Needs action-economy expansion (the runner currently has fixed 2-slot turns).

## Flight / Movement mode
- **Fly** (L3, P5) — grants flight speed. Needs vertical positioning or
  at minimum a "can't be melee'd from ground" state.

## Complex multi-buff
- **Greater Invisibility** (L4, P5) — invisible + can still attack.
  co_invisible exists but the attack-breaks-invisibility interaction for
  Greater (it doesn't break) vs regular Invisibility (it does) needs work.
- **Foresight** (L9, P5) — advantage on all attack rolls, ability checks,
  saving throws + attackers have disadvantage. Doable with modifiers but
  touches many interaction points.

## Meta / Special
- **Wish** (L9, P5) — can duplicate any 8th-level-or-lower spell + freeform
- **Mass Suggestion** (L6, P5) — multi-target charm control (12 creatures)
- **Meteor Swarm** (L9, P5) — four simultaneous 40-ft-radius AoE points
- **Gate** (L9, P4) — planar portal + summon
- **Time Stop** (L9, P4) — grants 1d4+1 extra turns
