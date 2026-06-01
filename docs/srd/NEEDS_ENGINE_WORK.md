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

## End-an-ongoing-effect system
- **Dispel Magic** (L3, P5) — ends one ongoing spell/effect on a target:
  auto-success when the effect's spell level ≤ the slot used (or ≤ 3rd),
  else an ability check (DC 10 + the effect's spell level). Needs: a
  primitive that enumerates a target's active spell effects (named_effect
  modifiers, persistent auras, applied conditions, recurring saves) tagged
  with their originating spell level, then selectively tears one down
  (the inverse of apply/cast). The engine tracks effects by
  source.action_id + caster_id but has no "what spell level produced
  this, and end exactly this one" lookup, and no ability-check-to-dispel
  resolver. Counterspell (built) intercepts a cast in flight; Dispel
  removes an effect already in play — a different operation.

## Revive-from-dead system
- **Revivify** (L3, P5) — a creature that died within the last minute
  returns with 1 HP. Needs: (a) a death-timestamp / "died this combat,
  within N rounds" record on the Actor (today there is only the boolean
  `is_dead`, no time-of-death), (b) a `revive` primitive that clears
  `is_dead` and sets HP to a fixed value, and (c) runner support for a
  revived actor re-entering the turn order. The `heal` primitive clamps
  to hp_max but does not clear `is_dead`, so a healed corpse stays dead
  (`is_alive()` checks `not is_dead`). Combat sims also rarely model the
  "dead ≤ 1 minute" window — needs a small death-bookkeeping system.

## Persistent controllable attacker (pseudo-summon)
- **Spiritual Weapon** (L2, P5) — a Bonus-Action cast spawns a floating
  spectral weapon that makes one melee spell attack immediately, and on
  each later turn the caster spends a Bonus Action to move it up to 20 ft
  and repeat the attack (1d8 + spellcasting mod Force, +1d8/slot above 2;
  Concentration in 2024). Needs: a per-duration "controllable construct"
  that (1) occupies a position the caster repositions, (2) grants a
  recurring Bonus-Action spell-attack action available ONLY while the
  spell is active, and (3) ends with Concentration. The engine has no
  summon/companion entity and no "spell grants a recurring action for its
  duration" mechanism — persistent_aura does turn-boundary saves/damage,
  not a caster-initiated attack roll. This is the lightweight front end
  of the same Summon/Animate system the conjure spells need.

## Scoring / candidate archetypes (content built, AI selection pending)
- **Magic Missile** (L1, P5) — BUILT as content (f_magic_missile rides
  the bare `damage` primitive; loads + executes + slot-consumes
  correctly). But it is an auto-hit, no-save, no-roll damage spell, and
  every offensive scorer assumes a roll: offensive_ehp_aoe returns 0
  without a forced_save step, and the attack/save scorers key off an
  attack_roll / save_ability. Needs a desktop-lane `auto_hit` damage
  archetype in the candidate generator + an eHP scorer (expected damage =
  mean dice, capped at target HP) so the AI will select it. Until then
  Magic Missile is correct under direct execution but not auto-cast.

## Meta / Special
- **Wish** (L9, P5) — can duplicate any 8th-level-or-lower spell + freeform
- **Mass Suggestion** (L6, P5) — multi-target charm control (12 creatures)
- **Meteor Swarm** (L9, P5) — four simultaneous 40-ft-radius AoE points
- **Gate** (L9, P4) — planar portal + summon
- **Time Stop** (L9, P4) — grants 1d4+1 extra turns
