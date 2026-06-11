# monster-ingest-roadmap.md — D&D Combat Simulator

Planning + tracking doc for completing the bestiary. Mirrors the spell
effort (`spell-content-roadmap.md`): cross-reference an owned source list
against the SRD, ingest all SRD content, then ingest the non-SRD list in
manageable CR-tier chunks. Sourcing posture: `docs/data-sources.md`;
build mechanics: `docs/MONSTER_BUILD_GUIDE.md`; engine-blocked abilities:
`docs/srd/MONSTERS_NEED_ENGINE_WORK.md`.

Created 2026-06-10 (Phil + Claude).

## What Phil directed (2026-06-10)

1. **Cross-reference a PHB monster list against the SRD** (like spells) →
   produce the list of PHB monsters NOT in the SRD. *(Pending Phil's PHB
   list — see "PHB cross-reference" below. SRD master list is staged here
   for the diff.)*
2. **Ingest ALL SRD monsters into the sim** (we own the SRD outright —
   `docs/srd/SRD_CC_v5.2.1.pdf`, CC-BY).
3. **Tier the PHB (non-SRD) monsters by CR** so Phil can send stat blocks
   in chunks: Tier 1 = CR 0–4, Tier 2 = CR 5–10, Tier 3 = CR 11–15,
   Tier 4 = CR 16–20 (Tier 5 = CR 21+ for the epic tail).

## Method (mirrors the spell lane)

- The **SRD is owned** → I build those directly from the PDF, no input
  needed. Per the build guide, GREEN (stat-block-composable) monsters get
  built now; abilities that need an unbuilt engine system are deferred to
  `MONSTERS_NEED_ENGINE_WORK.md` (most systems — recharge, legendary,
  spellcasting, regeneration, summon, swallow, auras, shape-shift — are
  now BUILT, so the buildable set is large).
- The **PHB is NOT owned** → for any PHB-only monster I need Phil to send
  the stat block. The cross-reference produces that "needed" list; the CR
  tiers below are the chunking so he can send a tier at a time.

## State (2026-06-10)

- **Built:** 149 `m_*.yaml` files.
- **SRD total (priority CSV):** 330 monsters.
- **SRD gap (to build):** ~181 monsters (a handful are
  apostrophe/encoding false-positives already built, e.g. Will-o'-Wisp).

## SRD ingestion — gap by tier

Status legend: ⬜ not built · ✅ built this effort · 🔧 deferred (bucket).
Triage is per-monster at build time (build guide §TRIAGE); a monster with
one engine-blocked rider is built WITHOUT that rider when the rest is a
complete stat block (noted in its file header).

### Tier 1 (CR 0–4) — 124 built, 94 gap
Beasts/mounts (Animals appendix, all GREEN): Bat, Cat, Deer, Eagle, Frog,
Goat, Hawk, Lizard, Owl, Rat, Raven, Scorpion, Spider, Vulture, Flying
Snake, Giant Bat, Giant Centipede, Giant Owl, Giant Rat, Mastiff, Mule,
Pony, Draft Horse, Riding Horse, Warhorse, Swarm of Insects, Swarm of
Venomous Snakes.
NPCs/humanoids: Assassin*, Cultist Fanatic*, Druid*, Guard Captain,
Hobgoblin Captain, Merfolk Skirmisher, Noble, Pirate, Priest Acolyte*,
Sahuagin Warrior, Warrior Infantry, Centaur Trooper, Gnoll Warrior.
Monsters: Animated Armor, Animated Flying Sword, Animated Rug of
Smothering, Ankheg†, Awakened Shrub, Awakened Tree, Azer Sentinel‡,
Basilisk(petrify rider), Bearded Devil‡, Black Pudding†, Blink Dog,
Chimera†, Chuul‡, Couatl*, Darkmantle, Doppelganger, Dretch, Dryad*,
Dust Mephit†, Ettercap†, Gelatinous Cube, Ghost, Gibbering Mouther,
Gray Ooze†, Green Hag*, Grick, Hell Hound, Homunculus, Ice/Magma/Steam
Mephit†, Imp, Incubus, Lamia*, Magmin†, Merrow, Nightmare, Ochre Jelly†,
Phase Spider, Pseudodragon, Quasit, Rust Monster, Satyr*, Sea Hag*,
Shrieker/Violet Fungus, Sprite, Succubus, Troll Limb, Werebeasts (Were-
boar/rat/tiger/wolf), Winter Wolf†, Worg.
  *= Spellcasting/Innate · †= Recharge/Death-Burst/split · ‡= Magic
  Resistance / nonmagical-resistance.

### Tier 2 (CR 5–10) — 11 built, 54 gap
Now-buildable via built systems: Young dragons ×10 (recharge breath),
Air/Earth/Fire/Water Elemental, Bulette, Hill/Frost/Stone Giant, Troll
(regen), Tyrannosaurus Rex, Otyugh, Roper(swallow), Shambling Mound,
Werebear, Hydra(regen; multi-head deferred). Defers: demons (Glabrezu/
Hezrou/Vrock — Magic Resistance), Aboleth/Deva (legendary+cast), casters
(Druid line, nagas, sphinx), golems (Clay/Stone — Magic Resistance),
Medusa/Gorgon (petrify), Night Hag/Oni/Unicorn/Treant (cast).

### Tier 3 (CR 11–15) — 7 built, 15 gap
Buildable: Behir/Remorhaz (swallow), Roc, Storm Giant(cast→defer rider),
Vampire (legendary; charm/drain deferred). Defers: devils (Horned/Ice —
Magic Resistance), Erinyes/Djinni/Efreeti (cast), Mummy Lord (legendary+
HP-drain), Rakshasa/Nalfeshnee (Magic Resistance), Sphinx of Lore (cast),
Purple Worm (swallow — buildable).

### Tier 4 (CR 16–20) — 4 built, 9 gap
Buildable: Ancient Brass/White Dragon, Dragon Turtle, Sphinx of Valor
(cast riders defer). Defers: Balor/Marilith/Pit Fiend (Magic Resistance),
Iron Golem (Magic Resistance), Planetar (cast).

### Tier 5 (CR 21+) — 0 built, 12 gap
Ancient dragons ×8 (legendary+recharge — buildable, heavy), Solar (cast),
Kraken/Lich (cast+legendary), Tarrasque (legendary — buildable, reflect
deferred).

## PHB cross-reference (pending Phil's PHB list)

When Phil sends the PHB monster list, diff it against the SRD master list
(the priority CSV / `name:` fields of built monsters). The set difference
(PHB − SRD) is the "needs a stat block from Phil" list. Group that result
by the CR tiers above and request stat blocks one tier at a time.

Note: the 2024 PHB itself contains few monsters; if Phil means the 2024
**Monster Manual**, the same diff applies — only the source list changes.

## Build order this effort

1. **Batch A — Animals appendix beasts** (Tier 1, all GREEN). ✅ DONE —
   28 built: Bat, Cat, Deer, Eagle, Frog, Goat, Hawk, Lizard, Owl, Rat,
   Raven, Scorpion, Spider, Vulture, Flying Snake, Giant Rat, Mule, Pony,
   Giant Bat, Giant Centipede, Giant Owl (sans utility spells), Draft
   Horse, Mastiff, Riding Horse, Warhorse, Swarm of Insects, Swarm of
   Venomous Snakes, Tyrannosaurus Rex. (Built count 149 → 177.)
2. Tier-1 GREEN NPCs + composable monsters.
3. Tier-2 now-buildable (Young dragons, elementals, giants, regen/swallow).
4. Tiers 3–5 legendary/heavy builds.
5. PHB non-SRD monsters, by tier, as Phil sends them.
</content>
