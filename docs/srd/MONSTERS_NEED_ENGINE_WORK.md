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
breath weapons.

**✅ SYSTEM BUILT (engine.core.recharge).** A `recharge` action field
("5-6", "6-6", or rest/daily forms) is gated end-to-end: spent on use,
rolled at the owner's turn-start, filtered from the candidate pool while
unavailable. The following partial-defers are now COMPLETE: **Giant
Spider** Web (5–6, save-or-Restrained), **Minotaur of Baphomet** Gore
(5–6, base hit; charge rider deferred), **Giant Ape** Boulder Toss (6,
DEX-save AoE + Prone — the breath-weapon-shape proof), and **Ape** Rock
(6, ranged throw).

Remaining recharge defers are blocked by *other* systems (mostly
Legendary / Spellcasting), not by recharge itself:
- **Wolf** (CR 1/4) — the *Winter* Wolf variant's Cold Breath (5–6) is a
  NEW monster (not the built plain Wolf); recharge-ready, awaits a
  monster batch.
- **Adult Black / Blue / Green / Red Dragon, Ancient Red Dragon, Young
  Red Dragon** (CR 10–24, rating 5) — Breath Weapon (Recharge 5–6) is now
  buildable, but these stay deferred on Legendary Actions/Resistance.
- **✅ BUILT (batch M6): all ten Dragon Wyrmlings** — Black/Blue/Green/
  Red/White (chromatic) + Brass/Bronze/Copper/Gold/Silver (metallic),
  each with Rend (+ chromatic elemental rider) and a Recharge 5–6 breath
  (DEX-save line/cone, or CON-save cone for poison/cold). Metallic
  secondary breaths built too where they map to existing primitives
  (Brass Sleep / Silver Paralyzing → Incapacitated; Copper Slowing →
  co_slowed; Bronze Repulsion → push + Prone). See the Gold note below
  for the one omitted secondary breath.
- Still recharge-ready but blocked on OTHER systems: **Young** dragons
  (CR 6–9, breath ready — most also fine but check per color); **Gorgon**
  (CR 5, Petrifying Breath → petrify escalation); **Half-Dragon** (CR 5);
  **Ankheg** (CR 2, Acid Spray); **Ettercap** (CR 2, Web); **Adult
  Brass/Bronze/Copper Dragon, Ancient Silver/White Dragon** (Legendary).
## Legendary Actions & Legendary Resistance
**✅ BOTH SYSTEMS BUILT.**
- **Legendary Resistance** (engine.core.legendary_resistance): stat-block
  `legendary_resistance: { uses: N }` → a failed save can be spent to
  succeed. Hooked into `_forced_save`.
- **Legendary Actions** (engine.core.legendary_actions): stat-block
  `legendary_actions: { uses_per_round: N, options: [...] }` → the runner
  spends one use per "another creature's turn ended" window (pool refills
  at the creature's own turn start); options run through the normal
  score/select/execute path.

These were the last blockers for the adult+ dragons and the legendary
solos. Each is now BUILDABLE by a monster batch (read the per-creature
breath / attacks / LA options / LR count from the SRD). Remaining
per-creature riders may still defer to OTHER buckets (Frightful Presence →
Aura/Reaction; Spellcasting on casters; Change Shape; Swallow) — triage
per monster.
- **Adult Black / Blue / Green / Red Dragon, Ancient Red Dragon** (CR
  14–24, rating 5) — now buildable (LR + LA + Recharge breath all
  supported); watch for Frightful Presence (Aura/Reaction bucket).
- **Lich** (CR 21, rating 5), **Vampire** (CR 15, rating 5), **Balor**
  (CR 19, rating 5), **Pit Fiend** (CR 20, rating 5), **Kraken** (CR 23,
  rating 5), **Tarrasque** (CR 30, rating 5) — Legendary no longer
  blocks, but each still defers on OTHER systems (Spellcasting / auras /
  on-hit drains / Swallow). Triage per creature.
- rating 4: **Adult Gold/Silver/White Dragon, Ancient Black/Blue/Gold/
  Green Dragon** — now buildable (Legendary + Recharge breath all
  supported). **Aboleth** (CR 10),
  **Deva/Planetar/Solar** (CR 10/16/21), **Marilith** (CR 16),
  **Mummy Lord** (CR 15), **Purple Worm** (CR 15, also Swallow),
  **Dragon Turtle** (CR 17). Full defer.
- Spellcasting/innate (no legendary) — also full-defer: **Erinyes**
  (CR 12), **Cloud Giant** (CR 9), **Storm Giant** (CR 13), **Efreeti /
  Djinni** (CR 11), **Oni** (CR 7, also Regeneration), **Night Hag**
  (CR 5), **Unicorn** (CR 5), **Treant** (CR 9).

- rating 2 full defers: **Ancient Brass / Bronze / Copper Dragon**
  (CR 20–22) — Legendary Actions/Resistance + Recharge breath.
## Lair Actions & Regional Effects
Initiative-20 lair actions / area regional effects — no lair-timing system.

## Monster Spellcasting
**✅ SYSTEM BUILT (engine.core.monster_spellcasting).** A monster action
casts a built spell by reference: `casts: <feature_id>` (+ optional
`recharge: "daily:1"` for 1/Day; omit for At-Will). A top-level
`spellcasting: { ability, save_dc }` drives the DC. The loader expands
each `casts` action into the referenced spell's full effect (type / area /
pipeline), with the monster as caster, dropping the PC spell-slot level.

Remaining blocker is now CONTENT, not engine: a caster is buildable once
**every spell it casts is built**. Built & ready to reference today:
Bless, Fireball, Healing Word, Mass Healing Word, Spirit Guardians (plus
the rest of the spell library). A caster needing an unbuilt spell defers
on THAT spell (build it first, or omit + note).
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
- **Giant Owl** (CR 1/4, rating 2) — innate Spellcasting. Full defer.
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
- **Death Dog** (CR 1, rating 2) — Bite disease (CON save → HP-max
  decay). **Built without the disease** (Bite damage core).
- **Lemure** (CR 0, rating 2) — Hellish Restoration (non-combat revive in
  the Nine Hells). **Built** with it recorded as a declarative trait.
- rating 2 full defers: **Dust Mephit** (CR 1/2), **Magmin** (CR 1/2) —
  Death Burst (explode on death) + breath.
- **Gold Dragon Wyrmling** (CR 3) — Weakening Breath (STR save: Disadvantage on
  STR-based D20 Tests + a -1d4 damage-roll penalty). **Built without this
  secondary breath** (a damage-roll/ability-check debuff has no primitive);
  its Fire Breath + Rend are the core.

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
- **Octopus** (CR 0, rating 1) — Ink Cloud (1/Day) reaction (escape:
  release ink + swim away). **Built without this reaction** (Tentacles
  is the core). No full monster defers at rating 1 — the trivial-critter
  tail is entirely GREEN.

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
