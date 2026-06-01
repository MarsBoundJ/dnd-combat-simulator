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
- **Giant Ape** (CR 7, rating 4) — Boulder Toss (Recharge 6): a ranged
  DEX-save AoE + Prone. **Built without this ability** (Fist multiattack
  is the complete core).

- rating 3 full defers (breath / recharge): all chromatic & metallic
  **Dragon Wyrmlings** (Black/Blue/Green/White/Red/Gold/Silver/Brass/
  Bronze/Copper, CR 2–4) and **Young** dragons (CR 6–9); **Gorgon**
  (CR 5, Petrifying Breath); **Half-Dragon** (CR 5, breath); **Ankheg**
  (CR 2, Acid Spray); **Ettercap** (CR 2, Web); **Adult Brass/Bronze/
  Copper Dragon, Ancient Silver/White Dragon** (also Legendary).
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
- rating 4: **Adult Gold/Silver/White Dragon, Ancient Black/Blue/Gold/
  Green Dragon** (Legendary + Recharge breath); **Aboleth** (CR 10),
  **Deva/Planetar/Solar** (CR 10/16/21), **Marilith** (CR 16),
  **Mummy Lord** (CR 15), **Purple Worm** (CR 15, also Swallow),
  **Dragon Turtle** (CR 17). Full defer.
- Spellcasting/innate (no legendary) — also full-defer: **Erinyes**
  (CR 12), **Cloud Giant** (CR 9), **Storm Giant** (CR 13), **Efreeti /
  Djinni** (CR 11), **Oni** (CR 7, also Regeneration), **Night Hag**
  (CR 5), **Unicorn** (CR 5), **Treant** (CR 9).

## Lair Actions & Regional Effects
Initiative-20 lair actions / area regional effects — no lair-timing system.

## Monster Spellcasting
"Spellcasting" / "Innate Spellcasting" trait. Defer unless every listed
spell is already built AND a monster-spellcasting action path exists.
- **Priest** (CR 2, rating 4) — Spellcasting (Light, Thaumaturgy, Spirit
  Guardians) + Divine Aid (Bless / Dispel Magic / Healing Word / Lesser
  Restoration). Full defer (its weapon attacks aren't the point).
- **Mage** (CR 9, rating 4), **Druid** (CR 2, rating 4), **Green Hag**
  (CR 3, rating 4) — Spellcasting / Innate Spellcasting. Full defer.
- **Archmage** (CR 12, rating 5) — full Wizard spell list. Full defer.
- **Lich** (CR 21, rating 5) — Spellcasting (also Legendary). Full defer.
- **Cultist Fanatic** (CR 2, rating 5), **Drider** (CR 6, rating 5),
  **Medusa** (CR 6, rating 5) — Spellcasting (Medusa also Petrifying Gaze).

- rating 3 full defers: **Guardian Naga / Spirit Naga** (CR 10 / 8),
  **Sphinx of Lore / Valor / Wonder** (CR 11 / 17 / 10), **Couatl**
  (CR 4), **Lamia** (CR 4), **Sea Hag / Green Hag** innate (CR 2 / 3),
  **Satyr** (innate), **Salamander**-tier innate casters.
## Regeneration / recurring self-heal
"Regeneration" or "regains N Hit Points at the start of its turn." No
regen tick (recurring_damage/temp_hp exist; a self-heal regen does not).
- **Troll** (CR 5, rating 5) — Regeneration 15 (stops to acid/fire).
- **Hydra** (CR 8, rating 5) — Regeneration 10 + multi-head / lose-a-head
  on-hit mechanic (also an on-hit triggered effect).

## Summon / call adds
Monsters that summon or call other creatures into the fight.
- **Wraith** (CR 5, rating 4) — Create Specter (raises a Specter from a
  fresh Humanoid corpse). **Built without this action** (Life Drain core).

## On-death / triggered effects
"Death Burst," "When it dies …," ooze split-on-hit, phylactery, etc.
Also the **HP-maximum-drain / ability-score-drain / curse** on-hit riders
below — all need a debuff mechanic the engine lacks (HP-max reduction,
ability-score reduction, can't-regain-HP). Each monster was **built
without the rider** (its base damage is the core):
- **Zombie** (CR 1/4, rating 5) — Undead Fortitude (drop-to-1-HP save).
- **Mummy** (CR 3, rating 4) — Rotting Fist curse (can't regain HP +
  HP-max decay).
- **Shadow** (CR 1/2, rating 4) — Draining Swipe Strength-score drain.
- **Specter** (CR 1, rating 4), **Wight** (CR 3, rating 4), **Wraith**
  (CR 5, rating 4) — Life Drain HP-maximum reduction.
- **Vampire Spawn** (CR 5, rating 4) — Bite HP-max drain + self-heal.
- **Stirge** (CR 1/8, rating 4) — attach-and-drain (2d4 necrotic each of
  its turns while attached; needs a recurring-while-attached condition).
- **Will-o'-Wisp** (CR 2, rating 4) — Consume Life (finish a 0-HP creature
  + self-heal). **Built without it** (Shock is the core).

- **Ogre Zombie** (CR 2, rating 3) — Undead Fortitude (drop-to-1-HP
  save). **Built without this trait** (Slam is the complete core).
- rating 3 full defers: **Gray Ooze** (CR 1/2) — corrode/split;
  **Magma/Ice/Steam Mephit** (CR 1/2–1/4) — Death Burst (+ breath).
## Form change
"Change Shape" / "Shapechanger" — the polymorph/form-replacement family.
- **Mimic** (CR 2, rating 5) — Shape-Shift (object/creature form toggle).
  **Built without this bonus action** (Bite + Pseudopod are the core).
- **Doppelganger** (CR 3, rating 5), **Werewolf** (CR 3, rating 5) —
  Change Shape / Shapechanger. Full defer.
- **Werebear** (CR 5, rating 4), **Wererat** (CR 2, rating 4),
  **Succubus / Incubus** (CR 4, rating 4) — Shapechanger. Full defer.

- rating 3 full defers: **Wereboar** (CR 4), **Weretiger** (CR 4) —
  Shapechanger.
## Engulf / swallow
"Swallow," "Engulf," restrain-and-internalize mechanics.
- **Gelatinous Cube** (CR 2, rating 5) — Engulf (DEX save, pulled inside,
  Restrained + ongoing acid). Full defer.
- rating 4: **Behir** (CR 11) + **Remorhaz** (CR 11) + **Roper** (CR 5)
  — Swallow; **Black Pudding / Ochre Jelly** (CR 4 / 2) — split-on-hit
  (also "On-death / triggered"). Full defer.

- **Giant Frog** (CR 1/4, rating 3), **Giant Toad** (CR 1, rating 3) —
  Bite-then-Swallow. **Built without the Swallow** (Bite + Grapple core).
- rating 3 full defers: **Behir** (CR 11), **Remorhaz** (CR 11),
  **Roper** (CR 5) — Swallow.
## Reaction abilities
Reactions beyond the existing reaction infra (Shield-style AC, Parry,
attack redirection). No general monster-reaction declaration path yet.
- **Bandit Captain** (CR 2, rating 5) — Parry (reaction: +2 AC vs a melee
  hit). **Built without this reaction.**
- **Goblin Boss** (CR 1, rating 5) — Redirect Attack (reaction: swap
  places with an ally, who becomes the target). Needs attack-redirection.
  **Built without this reaction.**
- **Knight** (CR 3, rating 4), **Gladiator** (CR 5, rating 4), **Warrior
  Veteran** (CR 3, rating 4) — Parry (+2/+3 AC vs a melee hit). **Built
  without this reaction.**

- **Pirate Captain** (CR 6, rating 3) — Parry (+3 AC vs a melee hit).
  **Built without this reaction.**
## Aura traits
Per-turn area effects on nearby creatures ("each creature within X feet
…", "Frightful Presence"). Some may later map to persistent_aura; defer
until confirmed.
- **Ghast** (CR 2, rating 4) — Stench (5-ft emanation, CON save →
  Poisoned). **Built without this trait** (Bite + Claw are the core).
- **Harpy** (CR 1, rating 4) — Luring Song (300-ft Concentration
  emanation, WIS save → Charmed + Incapacitated + forced approach).
  **Built without this trait** (Claw is the core).

## Conditional save/attack immunities & resistances (non-declarative)
"Magic Resistance" (advantage on saves vs spells), damage resistance
"from nonmagical attacks," etc. — needs a conditional grant the flat
damage_resistances field can't express. Full-defer rating-4 monsters
gated here (most also have Spellcasting/Legendary):
- **Iron / Stone Golem** (CR 16 / 10) — Magic Resistance + immune to
  nonmagical-attack damage.
- **Rakshasa** (CR 13) — Magic Resistance + limited-magic immunity.
- **Glabrezu / Hezrou / Vrock** (CR 9 / 8 / 6 demons) — Magic Resistance
  (+ innate spellcasting / summon).
- Bearded / Bone / Chain / Horned / Ice Devil — Magic Resistance +
  "from nonmagical attacks" resistance.

---

- rating 3 full defers (Magic Resistance / nonmagical-attack resistance):
  **Vrock / Hezrou / Nalfeshnee** (CR 6 / 8 / 13 demons), **Clay / Stone
  Golem** (CR 9 / 10), **Chuul** (CR 4), **Salamander** (CR 5, Fire
  aura), **Azer Sentinel** (CR 2, heated body), **Xorn** (CR 5),
  **Cloaker** (CR 8), **Barbed Devil** (CR 5).
## Notes on approximations (BUILT, not deferred)
These are built with a documented simplification rather than deferred:
- **Non-walk movement** (fly/swim/burrow): built using `walk` speed as
  the positional approximation; note the real movement mode in the
  monster file. (Deferring all flyers would gut the roster.)
