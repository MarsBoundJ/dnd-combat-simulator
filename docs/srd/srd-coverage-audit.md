# SRD 5.2.1 Coverage Audit — PC Building Blocks

**Workstream:** WS-A0 (`docs/stages-1-3-plan.md` §4, §5). **Status:** v1 (2026-06-14).
**Gates:** all of WS-A content fan-out (A2/A3/A4/A5/A8) and the import/rename
layers (WS-I) key off the SRD-vs-owned-book boundary established here.

## Purpose & method

This is the authoritative line between **content we can build now** (it is in
the Creative-Commons SRD 5.2.1, so we re-express mechanics freely) and content
that needs **owned-book source supply from Phil** before it can be modeled
(PHB-2024 / DMG-2024 deltas). Per `docs/data-sources.md` and plan §3.4/§3.8, the
`source` enum already tags every entity; this audit tells the later cycles
exactly which names fall on each side so no one hand-builds something that is
free, and no one assumes something is free when it isn't.

**Source of truth:** the in-repo `docs/srd/SRD_CC_v5.2.1.pdf` (364 pp.), text-
extracted with `pdftotext` (both `-layout` and raw reading-order modes) and
enumerated section by section. **SRD lists below are verified against the PDF.**

**Delta lists** (PHB-2024 / DMG-2024 "exists in the book, not in the SRD") are
**names only** — we do not have those books' text in-repo (only the SRD PDF is
present). They are compiled from the published 2024 books' tables of contents as
a *shopping list* and are marked **⚠ verify against Phil's copy** before any
build cycle consumes them. Names are facts (not copyrightable); no rules text is
reproduced.

**One caveat, called out honestly:** the **Magic Items A–Z** enumeration was
machine-extracted from a reflowed two-column PDF. The category lists below are
complete to the best of the extraction + targeted verification, but the magic-
item section (only) carries a residual risk of a small number of wrap-induced
omissions; it is flagged for a one-pass human verification (§7) before A8 fan-out.
Every other SRD list here was cross-checked and is exhaustive.

---

## 1. Backgrounds

The SRD ships **4** of the PHB-2024's **16** backgrounds. Each SRD background is
complete: three ability scores, an Origin feat, two skill proficiencies, one
tool proficiency, and an equipment-or-50 GP package.

### 1A. In SRD 5.2.1 (free to build now)

| Background | Ability Scores | Origin Feat | Skills | Tool |
|---|---|---|---|---|
| Acolyte | Int, Wis, Cha | Magic Initiate (Cleric) | Insight, Religion | Calligrapher's Supplies |
| Criminal | Dex, Con, Int | Alert | Sleight of Hand, Stealth | Thieves' Tools |
| Sage | Con, Int, Wis | Magic Initiate (Wizard) | Arcana, History | Calligrapher's Supplies |
| Soldier | Str, Dex, Con | Savage Attacker | Athletics, Intimidation | Gaming Set (choice) |

### 1B. PHB-2024 delta (⚠ verify against Phil's copy)

Names only — 12 backgrounds in the 2024 PHB not in the SRD:

| Background | Background | Background |
|---|---|---|
| Artisan | Guide | Noble |
| Charlatan | Hermit | Sailor |
| Entertainer | Merchant | Scribe |
| Farmer | (Guard) | Wayfarer |

> The 2024 PHB background list is: Acolyte, Artisan, Charlatan, Criminal,
> Entertainer, Farmer, Guard, Guide, Hermit, Merchant, Noble, Sage, Sailor,
> Scribe, Soldier, Wayfarer. SRD = {Acolyte, Criminal, Sage, Soldier}; delta =
> the other 12.

### 1C. DMG-2024 delta
None — backgrounds are a PHB entity class.

---

## 2. Species

The SRD ships **9** of the PHB-2024's **10** species, each with its level-1
traits and sub-option table (lineage / ancestry / legacy).

### 2A. In SRD 5.2.1 (free to build now)

| Species | Sub-options in SRD |
|---|---|
| Dragonborn | Draconic Ancestry (Black, Blue, Brass, Bronze, Copper, Gold, Green, Red, Silver, White — damage type per dragon) |
| Dwarf | — (Darkvision, Dwarven Resilience, Dwarven Toughness, Stonecunning) |
| Elf | Elven Lineage (Drow, High Elf, Wood Elf) |
| Gnome | Gnomish Lineage (Forest Gnome, Rock Gnome) |
| Goliath | Giant Ancestry (Cloud's Jaunt, Fire's Burn, Frost's Chill, Hill's Tumble, Stone's Endurance, Storm's Thunder) |
| Halfling | — (Brave, Halfling Nimbleness, Luck, Naturally Stealthy) |
| Human | — (Resourceful, Skillful, Versatile) |
| Orc | — (Adrenaline Rush, Darkvision 120, Relentless Endurance) |
| Tiefling | Fiendish Legacy (Abyssal, Chthonic, Infernal) |

> Repo note: species live under `schema/content/races/` (alias "species" per
> plan A3). 4 are already built (`r_*.yaml`); the remaining 5 SRD species + the
> sub-option tables are free fan-out.

### 2B. PHB-2024 delta (⚠ verify against Phil's copy)

| Species |
|---|
| Aasimar |

> 2024 PHB species: Aasimar, Dragonborn, Dwarf, Elf, Gnome, Goliath, Halfling,
> Human, Orc, Tiefling. SRD omits only **Aasimar**.

### 2C. DMG-2024 delta
None — species are a PHB entity class. (Additional species — Eladrin, Centaur,
Goblin, etc. — live in *other* WotC books, out of scope for this audit.)

---

## 3. Feats

The SRD ships **17** feats across the four categories. The 2024 PHB carries
roughly **75**, so the feat delta is the single largest PC-build gap.

### 3A. In SRD 5.2.1 (free to build now)

| Category | Feats (SRD) | Count |
|---|---|---|
| Origin | Alert · Magic Initiate (Cleric/Druid/Wizard choice) · Savage Attacker · Skilled | 4 |
| General | Ability Score Improvement · Grappler | 2 |
| Fighting Style | Archery · Defense · Great Weapon Fighting · Two-Weapon Fighting | 4 |
| Epic Boon | Boon of Combat Prowess · Boon of Dimensional Travel · Boon of Fate · Boon of Irresistible Offense · Boon of Spell Recall · Boon of the Night Spirit · Boon of Truesight | 7 |

> **Engine note for A4:** of these, the engine-real ones that escalate to Opus
> are Great Weapon Fighting (already modeled — `damage_die_floor`), Archery
> (+2 ranged attack), Defense (+1 AC), Two-Weapon Fighting (BA damage mod), and
> Grappler (advantage vs grappled). Alert/Skilled/Savage Attacker/Magic Initiate
> and most Epic Boons are mostly modifier-registry or out-of-combat.

### 3B. PHB-2024 delta (⚠ verify against Phil's copy — names only)

**Origin feats (delta):** Crafter, Healer, Lucky, Musician, Tavern Brawler, Tough.

**Fighting Style feats (delta):** Blind Fighting, Dueling, Interception,
Protection, Thrown Weapon Fighting, Unarmed Fighting.

**General feats (delta — high-combat-impact ones in bold):** Actor, Athlete,
Charger, Chef, **Crossbow Expert**, **Crusher**, Defensive Duelist, **Dual
Wielder**, Durable, **Elemental Adept**, **Fey Touched**, **Great Weapon
Master**, Heavily Armored, **Heavy Armor Master**, Inspiring Leader, Keen Mind,
Lightly Armored, **Mage Slayer**, Martial Weapon Training, Medium Armor Master,
**Mobile**, Moderately Armored, **Mounted Combatant**, Observant, **Piercer**,
Poisoner, **Polearm Master**, **Resilient**, Ritual Caster, **Sentinel**,
**Shadow Touched**, **Sharpshooter**, **Shield Master**, Skill Expert,
**Slasher**, Speedy, **Spell Sniper**, Telekinetic, Telepathic, **War Caster**,
Weapon Master.

**Epic Boon feats (delta):** Boon of Energy Resistance, Boon of Fortitude, Boon
of Recovery, Boon of Skill, Boon of Speed, Boon of the Night Spirit *(check —
may be SRD)*, Boon of Spell Recall *(SRD)*, plus any others in the PHB Epic Boon
chapter.

> The exact PHB general-feat roster and prerequisites **must be read from Phil's
> PHB** before A4 builds them — this list is a planning shopping list, not a
> verified enumeration. The four bolded families (GWM, Sharpshooter, Polearm
> Master, Sentinel, War Caster) are the named Opus-escalation feats in plan A4.

### 3C. DMG-2024 delta
None — feats are a PHB entity class.

---

## 4. Equipment

**The SRD equipment chapter is effectively complete** — the SRD 5.2.1 weapon,
armor, tool, and adventuring-gear tables are the same tables printed in the 2024
PHB. There is **no meaningful PHB equipment delta** for weapons/armor; the only
owned-book follow-ups are flavor/edge items, noted in 4E.

### 4A. Weapons — In SRD 5.2.1 (full table: 38 weapons)

Each carries: category, damage+type, properties, **mastery property**, weight,
cost. Mastery properties present (8): **Cleave, Graze, Nick, Push, Sap, Slow,
Topple, Vex**.

| Simple Melee (10) | Simple Ranged (4) | Martial Melee (18) | Martial Ranged (6) |
|---|---|---|---|
| Club | Dart | Battleaxe | Blowgun |
| Dagger | Light Crossbow | Flail | Hand Crossbow |
| Greatclub | Shortbow | Glaive | Heavy Crossbow |
| Handaxe | Sling | Greataxe | Longbow |
| Javelin | | Greatsword | Musket |
| Light Hammer | | Halberd | Pistol |
| Mace | | Lance | |
| Quarterstaff | | Longsword | |
| Sickle | | Maul | |
| Spear | | Morningstar | |
| | | Pike | |
| | | Rapier | |
| | | Scimitar | |
| | | Shortsword | |
| | | Trident | |
| | | Warhammer | |
| | | War Pick | |
| | | Whip | |

> Weapon properties present: Ammunition, Finesse, Heavy, Light, Loading, Range,
> Reach, Thrown, Two-Handed, Versatile. (Firearms — Musket/Pistol — are in the
> SRD as the higher-cost ranged options.)

### 4B. Armor — In SRD 5.2.1 (full table: 13 entries)

| Light (3) | Medium (5) | Heavy (4) | Shield |
|---|---|---|---|
| Padded Armor | Hide Armor | Ring Mail | Shield (+2 AC) |
| Leather Armor | Chain Shirt | Chain Mail | |
| Studded Leather Armor | Scale Mail | Splint Armor | |
| | Breastplate | Plate Armor | |
| | Half Plate Armor | | |

### 4C. Tools — In SRD 5.2.1

**Artisan's Tools (17):** Alchemist's Supplies, Brewer's Supplies, Calligrapher's
Supplies, Carpenter's Tools, Cartographer's Tools, Cobbler's Tools, Cook's
Utensils, Glassblower's Tools, Jeweler's Tools, Leatherworker's Tools, Mason's
Tools, Painter's Supplies, Potter's Tools, Smith's Tools, Tinker's Tools,
Weaver's Tools, Woodcarver's Tools.

**Other Tools (8):** Disguise Kit, Forgery Kit, Gaming Set (Dice / Dragonchess /
Playing Cards / Three-Dragon Ante), Herbalism Kit, Musical Instrument (Bagpipes,
Drum, Dulcimer, Flute, Horn, Lute, Lyre, Pan Flute, Shawm, Viol), Navigator's
Tools, Poisoner's Kit, Thieves' Tools.

### 4D. Adventuring Gear — In SRD 5.2.1 (full alphabetical table present)

The complete Adventuring Gear table is in the SRD. **Combat-relevant / engine-
relevant** items (the ones A2/A8 actually wire): Acid, Alchemist's Fire,
Antitoxin, Ball Bearings, Caltrops, Healer's Kit, Holy Water, Hunting Trap, Net,
Oil, Potion of Healing, Spell Scroll (Cantrip), Spell Scroll (Level 1).

**Spellcasting focuses:** Arcane Focus (Crystal, Orb, Rod, Staff, Wand), Druidic
Focus, Holy Symbol; Component Pouch.

**Ammunition:** Arrows, Bolts, Firearm Bullets, Sling Bullets, Needles.

**Equipment packs (7):** Burglar's, Diplomat's, Dungeoneer's, Entertainer's,
Explorer's, Priest's, Scholar's.

**Mounts (SRD):** Camel, Draft Horse, Elephant, Mastiff, Mule, Pony, Riding
Horse, Warhorse (+ tack: Saddle, etc.). **Vehicles (SRD):** Carriage, Cart,
Chariot, Sled, Wagon (land); Galley, Keelboat, Longship, Rowboat, Sailing Ship,
Warship (water). **Lifestyle Expenses** table present.

### 4E. PHB-2024 / DMG-2024 equipment delta

- **PHB-2024:** none of consequence — the weapon/armor/gear tables match the SRD.
  (Any divergence is flavor text, which we never copy.) **No build action.**
- **DMG-2024:** equipment proper is a PHB class; the DMG adds only *magic* gear,
  covered in §5. **No mundane-equipment delta.**

---

## 5. Magic Items & Potions

The SRD ships a large magic-item subset (~**200 entries**) across all nine
categories. The DMG-2024 superset is much larger; the delta is the bulk of the
DMG Magic Items chapter.

> **Methodology flag (magic items only):** lists below were machine-extracted
> from the reflowed PDF and spot-verified. Treat §5A as ~complete with a residual
> wrap-omission risk; **§7 schedules the one-pass human verification** before A8
> fan-out. Categories present in the SRD: Armor, Potion, Ring, Rod, Scroll,
> Staff, Wand, Weapon, Wondrous Item. Rarities: Common → Legendary (+ Artifact).
> Attunement rule present (cap 3, validated in PCSpec).

### 5A. In SRD 5.2.1 (free to build now)

**Magic Armor (~19):** Adamantine Armor · Animated Shield · Armor (+1/+2/+3) ·
Armor of Invulnerability · Armor of Resistance · Armor of Vulnerability ·
Arrow-Catching Shield · Demon Armor · Dragon Scale Mail · Dwarven Plate · Elven
Chain · Glamoured Studded Leather · Mithral Armor · Plate Armor of Etherealness ·
Sentinel Shield · Shield (+1/+2/+3) · Shield of Missile Attraction · Shield of
the Cavalier · Spellguard Shield.

**Magic Weapons (~29):** Ammunition (+1/+2/+3) · Ammunition of Slaying ·
Berserker Axe · Dagger of Venom · Defender · Dragon Slayer · Dwarven Thrower ·
Energy Bow · Flame Tongue · Giant Slayer · Hammer of Thunderbolts · Holy Avenger ·
Javelin of Lightning · Mace of Disruption · Mace of Smiting · Mace of Terror ·
Nine Lives Stealer · Oathbow · Quarterstaff of the Acrobat · Scimitar of Speed ·
Sun Blade · Sword of Life Stealing · Sword of Sharpness · Thunderous Greatclub ·
Trident of Fish Command · Vicious Weapon · Vorpal Sword · Weapon (+1/+2/+3) ·
Weapon of Warning.

**Rings (~23):** Animal Influence · Djinni Summoning · Elemental Command ·
Evasion · Feather Falling · Free Action · Invisibility · Jumping · Mind
Shielding · Protection · Regeneration · Resistance · Shooting Stars · Spell
Storing · Spell Turning · Swimming · Telekinesis · the Ram · Three Wishes ·
Warmth · Water Walking · X-ray Vision.

**Rods (7):** Immovable Rod · Rod of Absorption · Rod of Alertness · Rod of
Lordly Might · Rod of Resurrection · Rod of Rulership · Rod of Security.

**Staffs (12):** Staff of Charming · Staff of Fire · Staff of Frost · Staff of
Healing · Staff of Power · Staff of Striking · Staff of Swarming Insects · Staff
of the Magi · Staff of the Python · Staff of the Woodlands · Staff of Thunder and
Lightning · Staff of Withering.

**Wands (13):** Wand of Binding · Wand of Enemy Detection · Wand of Fear · Wand of
Fireballs · Wand of Lightning Bolts · Wand of Magic Detection · Wand of Magic
Missiles · Wand of Paralysis · Wand of Polymorph · Wand of Secrets · Wand of the
War Mage (+1/+2/+3) · Wand of Web · Wand of Wonder.

**Potions, Oils & Elixirs (~24):** Elixir of Health · Oil of Etherealness · Oil
of Sharpness · Oil of Slipperiness · Philter of Love · Potion of Animal
Friendship · Potion of Clairvoyance · Potion of Climbing · Potion of Diminution ·
Potion of Flying · Potion of Gaseous Form · Potion of Giant Strength (Hill/Frost/
Stone/Fire/Cloud/Storm) · Potion of Growth · Potion of Healing (Healing / Greater
/ Superior / Supreme) · Potion of Heroism · Potion of Invisibility · Potion of
Invulnerability · Potion of Longevity · Potion of Mind Reading · Potion of
Poison · Potion of Resistance · Potion of Speed · Potion of Vitality · Potion of
Water Breathing.

**Scrolls:** Spell Scroll (any spell level, scaled by rarity) — also listed in
Adventuring Gear.

**Wondrous Items (~115)** — the full SRD set, including:
Amulet of Health · Amulet of Proof against Detection and Location · Amulet of the
Planes · Apparatus of the Crab · Bag of Beans · Bag of Holding · Bag of Tricks ·
Bead of Force · Belt of Dwarvenkind · Belt of Giant Strength *(verify variant
coverage)* · Boots of Elvenkind · Boots of Levitation · Boots of Speed · Boots of
Striding and Springing · Boots of the Winterlands · Bowl of Commanding Water
Elementals · Bracers of Archery · Bracers of Defense · Brazier of Commanding Fire
Elementals · Brooch of Shielding · Broom of Flying · Candle of Invocation · Cape
of the Mountebank · Carpet of Flying · Censer of Controlling Air Elementals ·
Chime of Opening · Circlet of Blasting · Cloak of Arachnida · Cloak of
Displacement · Cloak of Elvenkind · Cloak of Invisibility · Cloak of Protection ·
Cloak of the Bat · Crystal Ball (+ Mind Reading / Telepathy) · Cube of Force ·
Decanter of Endless Water · Deck of Illusions · Dimensional Shackles · Dragon
Orb · Dust of Disappearance · Dust of Dryness · Dust of Sneezing and Choking ·
Efficient Quiver · Elemental Gem · Eversmoking Bottle · Eyes of Charming · Eyes of
Minute Seeing · Eyes of the Eagle · Figurine of Wondrous Power (Bronze Griffon,
Ebony Fly, Golden Lions, Ivory Goats, Marble Elephant, Obsidian Steed, Onyx Dog,
Serpentine Owl, Silver Raven) · Folding Boat · Gauntlets of Ogre Power · Gem of
Brightness · Gem of Seeing · Gloves of Missile Snaring · Gloves of Swimming and
Climbing · Gloves of Thievery · Goggles of Night · Handy Haversack · Hat of
Disguise · Headband of Intellect · Helm of Brilliance · Helm of Comprehending
Languages · Helm of Telepathy · Helm of Teleportation · Horn of Blasting · Horn of
Valhalla · Horseshoes of a Zephyr · Instant Fortress · Ioun Stone (multiple
variants) · Iron Bands of Bilarro · Iron Flask · Lantern of Revealing · Mantle of
Spell Resistance · Manual of Bodily Health · Manual of Gainful Exercise · Manual
of Golems · Manual of Quickness of Action · Marvelous Pigments · Medallion of
Thoughts · Mirror of Life Trapping · Necklace of Adaptation · Necklace of Prayer
Beads · Pearl of Power · Periapt of Health · Periapt of Proof against Poison ·
Periapt of Wound Closure · Pipes of the Sewers · Portable Hole · Robe of Eyes ·
Robe of Scintillating Colors · Robe of Stars · Robe of Useful Items · Robe of the
Archmagi · Rope of Climbing · Rope of Entanglement · Scarab of Protection ·
Sending Stones · Slippers of Spider Climbing · Sovereign Glue · Sphere of
Annihilation · Stone of Controlling Earth Elementals · Stone of Good Luck
(Luckstone) · Talisman of Pure Good *(verify)* · Talisman of the Sphere ·
Talisman of Ultimate Evil · Tome of Clear Thought · Tome of Leadership and
Influence · Tome of Understanding · Universal Solvent · Well of Many Worlds ·
Winged Boots · Wings of Flying.

### 5B. PHB-2024 delta
None — magic items are a DMG entity class. (The PHB-2024 lists item *rules*;
the item catalog is the DMG.)

### 5C. DMG-2024 delta (⚠ verify against Phil's copy — shopping list)

The DMG-2024 Magic Items chapter is a large superset of §5A. Rather than a
memory-enumerated full list (error-prone), this names the **high-demand items
known to be absent from the SRD** that import/builder users will most request
(feeds the WS-I demand queue). Treat as a starting shopping list; the full DMG
A–Z must be inventoried from Phil's copy when A8 expands past the SRD subset:

| Notable DMG-2024-only items (representative, not exhaustive) |
|---|
| Deck of Many Things · Bag of Devouring · Cap of Water Breathing · Cloak of the Manta Ray · Wand of Orcus · Sword of Wounding · Cube of Summoning *(verify)* · Eyes of the Rune Keeper · Helm of Comprehend Languages variants · Mariner's Armor · Mace of Smiting variants · Robe of the Archmage variants · Bracers of Archery variants · various +X Ioun Stones beyond SRD · Wings of Flying variants · Bowl/Brazier/Censer/Stone elemental-summoning variants · the Artifacts (e.g., beyond Sphere of Annihilation) |

> **Action:** when WS-A8 is ready to exceed the SRD subset, pull the DMG-2024
> Magic Items A–Z table of contents from Phil's copy and diff it against §5A to
> produce the exact delta. Until then, A8 builds the §5A SRD set only.

---

## 6. Character-creation & multiclassing rules

These are **rules-as-text in the SRD**, consumed by `engine/creation.py` (A6) and
the multiclass lane (WS-B). All listed below are present in the SRD 5.2.1 and free
to model.

### 6A. Character Creation rules — In SRD 5.2.1

| Rule element | SRD content |
|---|---|
| Creation steps | Step 1 Choose a Class · Step 2 Determine Origin (species + background) · Step 3 Determine Ability Scores · Step 4 Choose Alignment · Step 5 Character Details |
| Ability-score methods | **Standard Array** (15,14,13,12,10,8) · **Random Generation** (4d6 drop lowest) · **Point Buy** (27 points; Ability Score Point Costs table) |
| Ability cap at creation | 20 (after background +2/+1 or +1/+1/+1) |
| Origin order | Background grants +2/+1 (or +1/+1/+1) to its 3 listed abilities + Origin feat |
| Level advancement | Character Advancement table (XP → level, Proficiency Bonus by level) |
| Starting at higher levels | Starting Equipment at Higher Levels table (gold + magic-item allotment by tier) |
| HP per level | Fixed (average+1) or rolled — both methods present |
| Hit Points at L1 | max die + Con mod |
| Subclass timing | Per class (Champion/Thief/etc. at level 3 in 2024 classes) |
| Trinkets | d100 Trinkets table present |

### 6B. Multiclassing rules — In SRD 5.2.1 (complete)

The full multiclassing section is present (plan WS-B1/B4 source):

| Rule | SRD content |
|---|---|
| Prerequisites | Score ≥ 13 in the primary ability of **both** the current and new class |
| Experience Points | XP cost by **total character level**, not per-class |
| Hit Points & Hit Dice | New class's per-level HP; pool Hit Dice (same type pools, different types tracked separately) |
| Proficiency Bonus | By total character level |
| Proficiencies | Only the **partial** starting-proficiency set when multiclassing in |
| Class Features | Get each class's per-level features; special rules for Extra Attack, Spellcasting, Unarmored Defense |
| Armor Class | Only one AC-calc feature at a time |
| Extra Attack | Does **not** stack across classes (incl. Warlock Thirsting Blade) |
| Spellcasting — Spells Prepared | Determined per class independently |
| Spellcasting — Cantrip scaling | By total character level |
| Spellcasting — Spell Slots | **Multiclass Spellcaster table**: full casters (Bard/Cleric/Druid/Sorcerer/Wizard) full levels + Paladin/Ranger half (round up) → shared slot pool |
| **Pact Magic interop** | Warlock Pact-Magic slots can cast prepared Spellcasting spells, and Spellcasting slots can cast prepared Warlock spells (the WS-B5 centerpiece) |

> **Verified for WS-B4:** the SRD prints the Multiclass Spellcaster table and the
> half-caster "round up" rule explicitly (plan §9 flagged G#1's garbled math —
> the SRD text is the authority, oracle-test it).

### 6C. PHB-2024 / DMG-2024 delta
Creation & multiclassing rules in the SRD match the 2024 PHB. **No rules delta**
expected; if A6/B1 hit an edge the SRD omits, escalate as a NEEDS_ENGINE_WORK
item rather than assuming PHB text.

---

## 7. Owned-book input needed from Phil (consolidated shopping list)

Everything below requires **Phil's owned 2024 books as clean-room source supply**
before the corresponding build cycle can model it. Names are facts; we still need
the book text to model mechanics (plan §3.4 — ownership is source supply, not a
distribution right).

### From the **2024 Player's Handbook**

1. **Backgrounds (12):** Artisan, Charlatan, Entertainer, Farmer, Guard, Guide,
   Hermit, Merchant, Noble, Sailor, Scribe, Wayfarer.
2. **Species (1):** Aasimar.
3. **Feats (~58):**
   - *Origin (6):* Crafter, Healer, Lucky, Musician, Tavern Brawler, Tough.
   - *Fighting Style (6):* Blind Fighting, Dueling, Interception, Protection,
     Thrown Weapon Fighting, Unarmed Fighting.
   - *General (~40):* full list in §3B — priority engine feats: Great Weapon
     Master, Sharpshooter, Polearm Master, Sentinel, War Caster, Crossbow Expert,
     Shield Master, Mobile, Dual Wielder, Mage Slayer, Elemental Adept, Fey
     Touched, Shadow Touched, Resilient, the Crusher/Piercer/Slasher trio.
   - *Epic Boons:* the PHB Epic Boon chapter beyond the SRD 7 (Energy Resistance,
     Fortitude, Recovery, Skill, Speed, …).
4. **Verification pass:** confirm the exact PHB general-feat roster +
   prerequisites (§3B is a planning list, not yet book-verified).

### From the **2024 Dungeon Master's Guide**

5. **Magic Items:** the full DMG-2024 Magic Items A–Z **table of contents**, to
   diff against the SRD set in §5A and produce the exact delta. High-demand
   known-absent items to prioritize: Deck of Many Things, Bag of Devouring, Cap
   of Water Breathing, Wand of Orcus, Mariner's Armor, Sword of Wounding, the
   extended Ioun Stone set, plus the Artifacts chapter. (See §5C.)

### Internal verification (no book needed)

6. **Magic-items SRD list (§5A):** one human pass over the SRD Magic Items A–Z
   (pp. 209–253) to close any residual PDF-wrap omissions before A8 fan-out.
   Every other SRD list in this audit is exhaustively verified.

---

## Appendix — counts at a glance

| Entity class | SRD 5.2.1 | PHB-2024 delta | DMG-2024 delta |
|---|---|---|---|
| Backgrounds | 4 | 12 | — |
| Species | 9 | 1 (Aasimar) | — |
| Feats | 17 | ~58 | — |
| Weapons | 38 | 0 (same tables) | — |
| Armor | 13 | 0 (same tables) | — |
| Tools | 25 (17 artisan + 8 other) | 0 | — |
| Adventuring gear | full table + 7 packs | 0 | — |
| Magic items & potions | ~200 | — | large (full DMG superset) |
| Creation rules | complete | 0 | — |
| Multiclassing rules | complete | 0 | — |

**Bottom line:** weapons, armor, tools, gear, creation rules, and multiclassing
rules are **100% buildable now** from the SRD. Backgrounds, species, and feats
are partly buildable now (SRD subset) with a clear PHB shopping list. Magic items
are largely buildable now (SRD ~200) with the DMG superset as the deferred delta.
