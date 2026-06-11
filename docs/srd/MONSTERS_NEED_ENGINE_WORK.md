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
- **Ancient Red Dragon, Young Red Dragon** (CR 10–24, rating 5) — Breath
  Weapon (Recharge 5–6) is buildable. (The five **Adult** chromatics are
  now BUILT — see the Legendary section.)
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
  **Ankheg** (CR 2, Acid Spray); **Ettercap** (CR 2, Web); **Ancient
  Silver/White Dragon** (Legendary). (**Adult Brass/Bronze/Copper** are
  BUILT — batch M8.)
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
- **✅ BUILT (batch M7): Adult Black / Blue / Green / Red / White Dragon**
  (CR 13–17) — the first consumers of both Legendary systems: Multiattack
  of Rend (+ chromatic elemental rider), Recharge 5–6 breath (DEX-save
  line for Black/Blue, DEX-save cone for Red, CON-save cone for
  Green/White), `legendary_resistance: { uses: 3 }`, and
  `legendary_actions` (Pounce/Tail Swipe Rend, plus the save-based
  options: Black Cloud of Insects, Green Noxious Miasma, White Freezing
  Burst). Per-dragon DEFERS noted in each file: innate **Spellcasting**
  (and the "replace one attack with Spellcasting" Multiattack option),
  the Spellcasting-based legendary actions (Black/White **Frightful
  Presence** → Aura/Reaction bucket; Blue Cloaked Flight / Sonic Boom;
  Green Mind Invasion; Red Commanding Presence / Fiery Rays), and the
  no-engine-hook save riders (Concentration disadvantage, −2 AC, Speed-0).
- **Ancient Red Dragon** (CR 24, rating 5) — now buildable (LR + LA +
  Recharge breath all supported); watch for Frightful Presence
  (Aura/Reaction bucket) and Spellcasting.
- **Lich** (CR 21, rating 5), **Vampire** (CR 15, rating 5), **Balor**
  (CR 19, rating 5), **Pit Fiend** (CR 20, rating 5), **Kraken** (CR 23,
  rating 5), **Tarrasque** (CR 30, rating 5) — Legendary no longer
  blocks, but each still defers on OTHER systems (Spellcasting / auras /
  on-hit drains / Swallow). Triage per creature.
- **✅ BUILT (batch M8): Adult Brass / Bronze / Copper / Gold / Silver
  Dragon** (CR 13–17) — the first content to combine all four monster
  systems: Multiattack of Rend (+ metallic elemental rider), Recharge 5–6
  primary breath (DEX-save line for Brass/Bronze/Copper, DEX/CON-save cone
  for Gold/Silver), an at-will SECONDARY breath where it composes (Brass
  Sleep → co_incapacitated; Bronze Repulsion → push + co_prone; Copper
  Slowing → co_slowed; Silver Paralyzing → co_incapacitated),
  `legendary_resistance { uses: 3 }`, `legendary_actions` (Pounce Rend +
  a save option: Brass Scorching Sands, Bronze Thunderclap, Copper
  Giggling Magic, Gold Banish, Silver Cold Gale), and SAVE/AoE spell
  casts via `casts:` (Copper Mind Spike at-will; Gold Flame Strike 1/Day;
  Silver Hold Monster at-will + Ice Storm 1/Day). **M8 touch-up (after
  spellcasting v2):** the Spellcasting-based legendary actions are now
  WIRED IN as expanded `casts` LA options — Brass **Blazing Light**
  (Scorching Ray), Bronze/Gold **Guiding Light** (Guiding Bolt), Copper
  **Mind Jolt** (Mind Spike, daily:1), Silver **Chill** (Hold Monster,
  daily:1); the spell-ATTACK casts (Scorching Ray, Guiding Bolt) build
  from their pc_builder. Per-dragon DEFERS still noted in each file (see
  also the Monster Spellcasting + Lair sections below): Gold **Weakening
  Breath** (STR-disadvantage/damage-penalty debuff → no primitive);
  **Ice Knife** (Silver, unbuilt spell); the at-will main-action versions
  of the spell-ATTACK casts (represented only as the LA above for
  Brass/Bronze/Gold — the top-level at-will cast is a possible follow-up);
  and the no-engine-hook save riders (sleep/paralysis escalation,
  Speed-halved, D20-Test penalty, demiplane teleport).
- rating 4: **Ancient Black/Blue/Gold/Green Dragon** — now buildable
  (Legendary + Recharge breath all supported). (**Adult White** is BUILT —
  batch M7; **Adult Gold/Silver** BUILT — batch M8.) **Aboleth** (CR 10),
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

**✅ Both M8-surfaced `casts`-expansion gaps are now FIXED (spellcasting
v2).**
- **Spell-ATTACK casts now build.** `monster_spellcasting` builds a runnable
  ranged-attack pipeline from a `pc_builder: kind: spell_attack` /
  `attack_cantrip` feature (no action_template needed), using the
  monster's spell attack bonus (`spellcasting.attack_bonus`, else ability
  mod + PB). A `casts` to a feature with NEITHER an action_template NOR a
  buildable pc_builder now RAISES at load (fail-fast — no more silent
  non-runnable actions). The M8 defers are now buildable: **Scorching
  Ray** (Adult Brass), **Guiding Bolt** (Adult Bronze/Gold).
- **`casts` now expands in `legendary_actions.options`** (and
  `bonus_actions`), so spellcasting-based legendary actions work: Brass
  **Blazing Light**, Bronze/Gold **Guiding Light**, Copper **Mind Jolt**,
  Silver **Chill** — all WIRED IN as LA options (batch M8 touch-up).
- **✅ BUILT (batch M9): Mage / Priest / Archmage** — the first pure
  spellcaster NPCs, each modeled as its weapon/Arcane-Burst attack + a
  Spellcasting action whose buildable damage/control spells are `casts:`
  actions, gated daily:1 for per-day spells. Built casts: **Priest** (CR 2,
  WIS DC 13) — Spirit Guardians (1/Day) + Divine Aid → Bless (bonus action);
  **Mage** (CR **6** per the 2024 SRD, not CR 9; INT DC 14) — Fireball
  (2/Day) + Cone of Cold (1/Day); **Archmage** (CR 12, INT DC 17, Magic
  Resistance trait) — Lightning Bolt (2/Day) + Cone of Cold (1/Day).
  Per-caster DEFERS (noted in each file): at-will utility cantrips (Light,
  Thaumaturgy, Detect Magic/Thoughts, Mage Hand, Prestidigitation, Disguise
  Self, Invisibility) and **Mage Armor** (already in AC); the unbuilt/heal
  Divine Aid options **Healing Word / Dispel Magic / Lesser Restoration**;
  utility 1/Day **Fly / Mind Blank / Scrying / Teleport**; bonus-action
  **Misty Step** (f_misty_step not built); and the **Protective Magic**
  reaction (Counterspell / Shield) — no monster reactive-cast path yet.
  RAW 2/Day casts (Fireball, Lightning Bolt) are gated daily:1 (one cast
  per encounter — the second daily use is a v1 under-representation).
- **Druid** (CR 2, rating 4), **Green Hag** (CR 3, rating 4) —
  Spellcasting / Innate Spellcasting. Full defer.
- **Lich** (CR 21, rating 5) — Spellcasting (also Legendary). Full defer.
- **Cultist Fanatic** (CR 2, rating 5), **Drider** (CR 6, rating 5),
  **Medusa** (CR 6, rating 5) — Spellcasting (Medusa also Petrifying Gaze).

- rating 3 full defers: **Guardian Naga / Spirit Naga** (CR 10 / 8),
  **Sphinx of Lore / Valor / Wonder** (CR 11 / 17 / 10), **Couatl**
  (CR 4), **Lamia** (CR 4), **Sea Hag / Green Hag** innate (CR 2 / 3),
  **Satyr** (innate), **Salamander**-tier innate casters.
- **Giant Owl** (CR 1/4, rating 2) — innate Spellcasting. Full defer.
- **Multiattack + cast composite** (batch M10, also the M8 dragons'
  "replace one attack with Spellcasting"): 2024 stat blocks routinely
  fold a cast into Multiattack — **Aarakocra Aeromancer** (CR 4, MM 2024)
  "two Wind Staff attacks AND can cast Gust of Wind"; **Bullywug Bog
  Sage** (CR 4, MM 2024) "can replace any attack with Ray of Sickness";
  **Bone Naga** (CR 4, MM 2024) "can replace any attack with Serpentine
  Gaze" (modeled as round-robin, not a choice). Both casters are BUILT
  with the cast as a separate top-level action (action-economy
  under-representation). Likely fix: allow `sub_actions` to reference a
  `casts`-expanded action id — `_execute_multiattack` already looks
  sub-actions up by id in the expanded template, so this may only need
  verification + a test (Opus call: it composes the multiattack loop
  with the spellcasting expansion, two systems with no joint coverage).
## Regeneration / recurring self-heal
**✅ SYSTEM BUILT (engine.core.regeneration).** Stat-block
`regeneration: { amount: N, suppressed_by: [acid, fire],
revives_from_zero: true }`. Heals N at the creature's turn start; a
suppressing damage type switches it off for the next turn;
`revives_from_zero` models the Troll rule (0 HP is downed-not-dead — the
creature revives at its turn start unless it took acid/fire, and the
encounter doesn't end while it's down). Plain "if it has ≥1 HP" regen =
`revives_from_zero: false`.
- **Troll** (CR 5) — now buildable: Multiattack of Rend +
  `regeneration: { amount: 15, suppressed_by: [acid, fire],
  revives_from_zero: true }`.
- **Hydra** (CR 8) — Regeneration 10 maps to this trait, but the Hydra
  still defers on its multi-head / lose-a-head-on-hit / grow-heads
  mechanic (dynamic action count + on-hit trigger) — its own follow-up.

## Summon / call adds
Monsters that summon or call other creatures into the fight.
**✅ SYSTEM BUILT (engine.core.summoning).** The `summon` primitive
(params `monster`, `count`, optional `max_total`) spawns creatures
mid-encounter: each is built from its stat block (via cli._build_actor),
joins the summoner's side, is tagged `summoned_by`, added to
`encounter.actors`, and inserted into `turn_order` right after the
summoner — a full combatant from that moment (targetable, takes its turn).
A `max_total` cap limits concurrent summons (Wraith: 7).
- **Wraith** (CR 5) — Create Specter now buildable: a `summon` action with
  `{ monster: m_specter, max_total: 7 }` (m_specter is built). v1 DEFERS
  the corpse precondition (a Humanoid that died within 1 min, within
  10 ft) — battlefield-corpse tracking is a follow-up; v1 summons
  unconditionally.

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
- **Gold Dragon Wyrmling** (CR 3) and **Adult Gold Dragon** (CR 17, batch
  M8) — Weakening Breath (STR save: Disadvantage on STR-based D20 Tests +
  a -1d4/-1d6 damage-roll penalty). **Built without this secondary
  breath** (a damage-roll/ability-check debuff has no primitive); the Fire
  Breath + Rend (+ the Adult's legendary kit) are the core.

## HP-threshold instant-drop (power-word shape)
A save/effect that checks the target's CURRENT HP against a threshold
and drops it to 0 outright when at-or-under (otherwise a normal damage
fallback). No primitive exists — needs something like
`hp_threshold_drop { threshold: N, otherwise: [damage steps] }` inside a
forced_save `on_fail`. Same shape as the Power Word Kill / Power Word
Stun spell family, so building it serves the spell library too.
**Opus-owned: new primitive.**
- **Banshee** (CR 4, MM 2024, batch M10) — Deathly Wail (1/Day):
  CON save DC 13, 30-ft emanation; on a fail a target at ≤25 HP drops
  to 0, else takes 3d6 Psychic. **Built with the 3d6 Psychic fail-damage
  only** (the wail under-represents its execute potential). Also
  unmodeled: the sunlight precondition and Construct/Undead + hearing
  exclusions (no creature-type/sense filters on AoE saves).

## Per-encounter save-immunity on targeted saves
"Success: the target is immune to this creature's X for 24 hours." The
aura-trait resolver already supports exactly this (`immune_on_success`
in engine.core.aura_traits / runner), but targeted `forced_save` actions
have no equivalent — a passed save grants nothing, so the monster can
re-attempt every round (overstates the ability). Fix shape: an
`immune_on_success: true` param on forced_save that stamps a
per-(source, action) immunity set the save resolver checks.
**Opus-owned: touches the forced_save hot path.**
- **Banshee** (CR 4, MM 2024, batch M10) — Horrify (part of its
  Multiattack): WIS DC 13 → Frightened; success → 24h immunity.
  **Built without the immunity.**

## Form change
2024 SRD trait name is **"Shape-Shift"** (not "Change Shape").
**✅ SYSTEM BUILT (shape_shift primitive + change_shape form policy).**
RAW: "its game statistics, OTHER THAN ITS SIZE, are the same in each
form" — so Shape-Shift is combat-light: it changes only `size`
(+ creature_type if declared) and keeps HP/AC/abilities/attacks. A monster
action runs `primitive: shape_shift {form_id, size, creature_type?}`
(revert via `shape_shift_revert`); a creature dropped to 0 HP while shifted
dies in its true size (no HP-snapshot resurrection).

The Shape-Shift trait itself is no longer a blocker. These monsters can
now build their Shape-Shift toggle — but most still defer on their OTHER
combat abilities, which are the real point:
- **Mimic** (CR 2) — Shape-Shift now buildable; Adhesive is the remaining
  flavor (Bite + Pseudopod core already built).
- **Doppelganger** (CR 3) — Shape-Shift buildable; defers on Read
  Thoughts / surprise-burst riders.
- **Werewolf** (CR 3), **Werebear** (CR 5), **Wererat** (CR 2),
  **Wereboar** (CR 4), **Weretiger** (CR 4) — Shape-Shift buildable
  (size-only per 2024 RAW; attacks are NOT form-gated); the lycanthropy
  curse-on-bite is non-combat and stays declarative.
- **Succubus / Incubus** (CR 4) — Shape-Shift buildable; the real
  blockers are Charm / Draining Kiss / Etherealness (own buckets).
## Engulf / swallow
"Swallow," "Engulf," restrain-and-internalize mechanics.
**✅ SYSTEM BUILT (engine.core.swallow).** A Swallow action is a DEX
`forced_save` whose `on_fail` applies Blinded + Restrained then the
`swallow_apply` primitive: the target gets Total Cover, is pulled into the
swallower's space, and is tagged with an ongoing-acid spec. The runner
deals that acid at the swallower's turn start; the swallower's death frees
the victim. **Swallow is now buildable** for Behir / Remorhaz / Purple
Worm / Giant Frog/Toad (and Gelatinous Cube's Engulf uses the same
save→swallow_apply shape).
- **✅ Regurgitate counterplay built (v2).** A Swallow action's
  `swallow_apply` can carry `regurgitate_threshold` / `regurgitate_dc` /
  `regurgitate_save`: damage the victim deals to the swallower is tracked
  per turn, and at the victim's turn end a threshold breach makes the
  swallower save (via forced_save, so Legendary Resistance applies) or
  expel the victim (freed + Prone). Behir: threshold 30, CON DC 14.
- Still DEFERRED: **Engulf-on-move** entry + **multi-capacity** (cube
  holds 4 Medium); the **grapple-first** precondition (Behir).
- Still deferred on OTHER systems: **Black Pudding / Ochre Jelly**
  (CR 4 / 2) — split-on-hit (On-death / triggered bucket); **Roper**
  (CR 5) — also Reel/Grapple-line mechanics.
- **Giant Frog** (CR 1/4), **Giant Toad** (CR 1) — Swallow now buildable
  (currently built with Bite + Grapple core; add the Swallow action).
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
- **Aarakocra Aeromancer** (CR 4, MM 2024, batch M10) — Feather Fall
  (1/Day) reactive cast. **Built without it**: falling isn't modeled in
  the sim, AND there's no monster reactive-cast path (same gap as the
  Mage/Archmage Protective Magic above).

## Aura traits
**✅ SYSTEM BUILT (engine.core.aura_traits).** Always-on emanations: a
monster `auras: [{id, range_ft, save:{ability,dc}, on_fail, affected,
immune_on_success}]` is registered at combat start as a caster-anchored
`persistent_aura` (moves with the monster), and the existing turn-start
resolver fires it. `immune_on_success` grants per-encounter immunity
(the "immune for 24h" stand-in).
- **Ghast** (CR 2) — Stench now buildable: `auras: [{ range_ft: 5,
  save: {constitution, 10}, immune_on_success: true, on_fail:
  [apply_condition co_poisoned] }]` (Bite + Claw core already built).
- **Frightful Presence** (dragons) — NOT a trait aura in 2024 RAW; it's a
  legendary action that **casts Fear**. Already buildable today via
  `casts: f_fear` in `legendary_actions.options` (f_fear is built;
  Spellcasting v2 expands it). No engine work — a dragon LA touch-up.
- **Harpy** (CR 1) — Luring Song is a Concentration *action* aura (WIS →
  Charmed + Incapacitated + forced approach), not an always-on trait;
  rides the persistent_aura cast action. The Charmed-forced-approach
  movement rider is the remaining gap.

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
