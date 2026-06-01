# Monsters That Need Engine Work

Monsters the browser lane set aside because a stat-block element needs an
engine system that doesn't exist yet. Desktop lane builds the system,
then the monster (or just its blocked ability) gets built/finished.

**How to add an entry:** when BC's triage (see docs/MONSTER_BUILD_GUIDE.md)
hits a defer-trigger, append the monster under the matching bucket with:
`- **<Monster>** (CR <x>, rating <n>) — <the exact ability + why it blocks>`.
Use the bucket names below verbatim so the desktop lane can batch by system.

---

## Recharge abilities
Abilities usable again on a die roll at turn start ("Recharge 5–6",
"Recharge 6", "Recharge after a Short/Long Rest") — most dragon/beast
breath weapons. No recharge tracking exists. *(Unblocks the most
rating-5 monsters; strong candidate for the desktop systems track.)*

## Legendary Actions & Legendary Resistance
- Legendary Actions: extra actions taken between other creatures' turns.
- Legendary Resistance: "N/Day, auto-succeed a failed save."
Neither has runner support (the `legendary_actions` schema field exists
but isn't consumed).

## Lair Actions & Regional Effects
Initiative-20 lair actions / area regional effects — no lair-timing system.

## Monster Spellcasting
"Spellcasting" / "Innate Spellcasting" trait. Defer unless every listed
spell is already built AND a monster-spellcasting action path exists.

## Regeneration / recurring self-heal
"Regeneration" or "regains N Hit Points at the start of its turn." No
regen tick (recurring_damage/temp_hp exist; a self-heal regen does not).

## Summon / call adds
Monsters that summon or call other creatures into the fight.

## On-death / triggered effects
"Death Burst," "When it dies …," ooze split-on-hit, phylactery, etc.

## Form change
"Change Shape" / "Shapechanger" — the polymorph/form-replacement family.

## Engulf / swallow
"Swallow," "Engulf," restrain-and-internalize mechanics.

## Aura traits
Per-turn area effects on nearby creatures ("each creature within X feet
…", "Frightful Presence"). Some may later map to persistent_aura; defer
until confirmed.

## Conditional save/attack immunities & resistances (non-declarative)
"Magic Resistance" (advantage on saves vs spells), damage resistance
"from nonmagical attacks," etc. — needs a conditional grant the flat
damage_resistances field can't express.

---

## Notes on approximations (BUILT, not deferred)
These are built with a documented simplification rather than deferred:
- **Non-walk movement** (fly/swim/burrow): built using `walk` speed as
  the positional approximation; note the real movement mode in the
  monster file. (Deferring all flyers would gut the roster.)
