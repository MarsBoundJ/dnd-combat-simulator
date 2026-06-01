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
- **Giant Spider** (CR 1, rating 5) — Web (Recharge 5–6): DEX save or
  Restrained. **Built without this ability** (Bite is the complete core).
- **Minotaur of Baphomet** (CR 3, rating 5) — Gore (Recharge 5–6): a
  charge attack with bonus damage + Prone. **Built without this ability**
  (Abyssal Glaive is the complete core).
- **Wolf** (CR 1/4, rating 5) — the *Winter* Wolf variant's Cold Breath
  (Recharge 5–6); the plain Wolf was BUILT (no recharge).
- **Adult Black / Blue / Green / Red Dragon, Ancient Red Dragon, Young
  Red Dragon** (CR 10–24, rating 5) — Breath Weapon (Recharge 5–6). Also
  blocked by Legendary Actions/Resistance (dragons) — see below.

## Legendary Actions & Legendary Resistance
- Legendary Actions: extra actions taken between other creatures' turns.
- Legendary Resistance: "N/Day, auto-succeed a failed save."
Neither has runner support (the `legendary_actions` schema field exists
but isn't consumed).
- **Adult Black / Blue / Green / Red Dragon, Ancient Red Dragon** (CR
  14–24, rating 5) — Legendary Resistance (3/Day) + Legendary Actions,
  plus Recharge breath. Full defer.
- **Lich** (CR 21, rating 5), **Vampire** (CR 15, rating 5), **Balor**
  (CR 19, rating 5), **Pit Fiend** (CR 20, rating 5), **Kraken** (CR 23,
  rating 5), **Tarrasque** (CR 30, rating 5) — Legendary Actions/
  Resistance (+ Spellcasting / auras / on-hit riders). Full defer.

## Lair Actions & Regional Effects
Initiative-20 lair actions / area regional effects — no lair-timing system.

## Monster Spellcasting
"Spellcasting" / "Innate Spellcasting" trait. Defer unless every listed
spell is already built AND a monster-spellcasting action path exists.
- **Archmage** (CR 12, rating 5) — full Wizard spell list. Full defer.
- **Lich** (CR 21, rating 5) — Spellcasting (also Legendary). Full defer.
- **Cultist Fanatic** (CR 2, rating 5), **Drider** (CR 6, rating 5),
  **Medusa** (CR 6, rating 5) — Spellcasting (Medusa also Petrifying Gaze).

## Regeneration / recurring self-heal
"Regeneration" or "regains N Hit Points at the start of its turn." No
regen tick (recurring_damage/temp_hp exist; a self-heal regen does not).
- **Troll** (CR 5, rating 5) — Regeneration 15 (stops to acid/fire).
- **Hydra** (CR 8, rating 5) — Regeneration 10 + multi-head / lose-a-head
  on-hit mechanic (also an on-hit triggered effect).

## Summon / call adds
Monsters that summon or call other creatures into the fight.

## On-death / triggered effects
"Death Burst," "When it dies …," ooze split-on-hit, phylactery, etc.
- **Zombie** (CR 1/4, rating 5) — Undead Fortitude: on dropping to 0 HP,
  a CON save (DC 5 + damage) drops it to 1 HP instead (unless Radiant /
  crit). A triggered death-prevention hook. **Built without this trait**
  (Slam is the complete core).

## Form change
"Change Shape" / "Shapechanger" — the polymorph/form-replacement family.
- **Mimic** (CR 2, rating 5) — Shape-Shift (object/creature form toggle).
  **Built without this bonus action** (Bite + Pseudopod are the core).
- **Doppelganger** (CR 3, rating 5), **Werewolf** (CR 3, rating 5) —
  Change Shape / Shapechanger. Full defer.

## Engulf / swallow
"Swallow," "Engulf," restrain-and-internalize mechanics.
- **Gelatinous Cube** (CR 2, rating 5) — Engulf (DEX save, pulled inside,
  Restrained + ongoing acid). Full defer.

## Reaction abilities
Reactions beyond the existing reaction infra (Shield-style AC, Parry,
attack redirection). No general monster-reaction declaration path yet.
- **Bandit Captain** (CR 2, rating 5) — Parry (reaction: +2 AC vs a melee
  hit). **Built without this reaction.**
- **Goblin Boss** (CR 1, rating 5) — Redirect Attack (reaction: swap
  places with an ally, who becomes the target). Needs attack-redirection.
  **Built without this reaction.**

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
