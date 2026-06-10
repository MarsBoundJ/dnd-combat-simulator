# spell-content-roadmap.md — D&D Combat Simulator

Planning doc for expanding the sim's spell coverage. Created 2026-05-30
(Phil + Claude). Sourcing/authoring posture lives in `data-sources.md`;
follow it for every spell added.

## THE MASTER LIST (added 2026-06-10 — start here)

**`docs/spell-master-list.csv`** is now the single spell inventory:
every spell in PHB 2024 ∪ SRD 5.2.1, one row each, plus the two
already-built out-of-scope extras (Sickening Radiance, Synaptic Static —
XGE). `tests/test_spell_master_list.py` enforces it: a new spell YAML
cannot land without its master-list row being updated, and no row can
claim a file that doesn't exist. Nothing falls between the cracks.

Columns:
- **name** — PHB 2024 canonical name.
- **srd_name** — set only where SRD 5.2.1 stripped the proper name
  (17 spells: Evard's Black Tentacles → Black Tentacles, Leomund's
  Tiny Hut → Tiny Hut, Bigby's Hand → Arcane Hand, Mordenkainen's
  Sword → Arcane Sword, Nystul's Magic Aura → Arcanist's Magic Aura,
  etc.). **Every overlap spell is an SRD spell** — the CC-BY text is
  usable verbatim under the generic name; only the proper name itself
  is the PHB-flavored part.
- **source** — `srd_5.2.1` (339 spells; CC-BY, text may be ingested
  verbatim from `docs/srd/SRD_CC_v5.2.1.pdf`) or `phb_2024` (51
  spells; mechanics-only, own-words re-expression per
  `data-sources.md` — same posture as the PHB subclasses).
- **tier** — build priority (Phil's Phase-2 scheme): **S** combat
  staples (30), **A** class-defining: attack cantrips, smites,
  signature spells (40), **B** subclass always-prepared lists (~80),
  **C** remaining combat spells (~150), **D** utility/non-combat —
  defer indefinitely (~90). Draft-assigned by Claude 2026-06-10;
  adjust freely, the test doesn't care about tier.
- **status** — `todo` / `stub` (file exists, spec-only or partial) /
  `built` (file + tests, usable in the sim). Fidelity deferrals of
  built spells stay documented in the YAML header comments, as today.
- **files** — `;`-separated content files implementing the spell.

State at creation: **128 built / 264 todo**. S-tier gaps (the
highest-leverage five): **Misty Step, Dispel Magic, Haste, Dimension
Door, Greater Invisibility.**

### Verification flags (Phil)
- SRD side is authoritative: all 339 rows (name/level/school) were
  machine-extracted from the SRD 5.2.1 PDF in `docs/srd/` (CC-BY, so
  extraction is clean). The PHB-only rows are from Claude's knowledge:
  339 + 51 = **390 vs the 391 figure for PHB 2024** — one spell is
  unaccounted for, and PHB-only level/school values are unverified.
  **Diff the master list against Phil's Google-Doc spell list** (paste
  the names/level/school into a session) to find the missing row and
  confirm the 51.

### Corrections to the rest of this doc (SRD 5.2.1 verified 2026-06-10)
The "verify SRD 5.2.1 coverage" quick-win has now been run. It moves
several spells this doc treats as non-SRD INTO the free pile:
- **True Strike, Wall of Stone, Conjure Woodland Beings, Nystul's
  Magic Aura** (as "Arcanist's Magic Aura") are all in SRD 5.2.1 —
  they were also missing from the two priority CSVs in `docs/srd/`,
  which the master list supersedes as inventory.
- **Branding Smite no longer exists in 2024** — it's **Shining Smite**,
  which is SRD. **Feeblemind** is now **Befuddlement** — SRD, already
  built. The "True Strike decision" is resolved: 2024 attack-cantrip
  redesign, SRD text.
- The true PHB-only (non-SRD) set is **51 spells** (8 already built),
  not the 38/34 counted below.

## What Phil actually directed (2026-05-30)

- **Add the 38 PHB non-SRD spells** he listed (PHB owned → clean
  provenance). 4 already built → 34 remain.
- **Verify the SRD spells are in the sim** (he has the SRD spell CSV in
  `Downloads/srd and phb data/`).
- **Start the build now with the smite batch** (Blinding + Wrathful
  Smite) — i.e. begin non-SRD immediately, archetype-easiest first.

That is the whole directive. He did NOT order any "SRD-complete-before-
non-SRD" sequencing — an earlier draft of this doc invented that and
wrongly attributed it to him; corrected here.

## Claude's proposed engineering approach (a plan to confirm, NOT a Phil directive)

1. **Easiest → hardest.** Bank archetype-reuse spells first; tackle the
   ones needing new engine systems later.
2. **Leverage archetypes for efficiency** — most spells are recolors of
   existing primitives (smite_rider, persistent_aura, save_attack,
   weapon_damage_bonus, temp_hp_grant, heal builders, aoe_attack,
   forced_save, hard_control). Adding one of those = "spec + a few
   lines + a test."
3. **Some spells need engine enhancements** — new primitives/systems
   (summons, walls/terrain, teleport/positional, action-economy grants,
   sustained-channel spells, ally-buff auras, damage-resistance
   modeling). Build the system once, then the spells that ride it.
4. **Harder spells need clever testing** — positional/multi-turn/
   conditional spells may need new test scaffolding (seeded multi-round
   scenarios). Design the test approach with the engine enhancement.
5. **SRD-vs-non-SRD ordering is OPEN** — Phil chose to start non-SRD
   now. Whether/when to interleave SRD-gap-filling is his call, not
   assumed.

## Reality check (state as of 2026-05-30, post-PR #118)

The sim is an **engine with a curated ~30-spell content set**, NOT a
complete spell database — most SRD spells are also not yet built (we
build on demand). So "verify SRD spells are in the sim" will mostly
return "not yet implemented"; that produces an SRD gap list, it doesn't
confirm broad coverage. Built so far (the `f_*` spell/cantrip files):
Bless, Shield of Faith, Aid, Divine Favor, Prot from Evil & Good,
Searing Smite, Ensnaring Strike, Hex, Hunter's Mark, Heroism, False
Life, Armor of Agathys, Compelled Duel, Eldritch Blast (+Agonizing/
Repelling), Sacred Flame, Toll the Dead, Cure Wounds, Healing Word,
Spirit Guardians, Counterspell, Shield, Hellish Rebuke, Darkness,
Moonbeam, Cloud of Daggers, Cloudkill, Fog Cloud, Hunger of Hadar,
Silence, Stinking Cloud, Web.

## Active work: the 34 non-SRD PHB spells (started 2026-05-30)

38-spell target, **4 already built** (Armor of Agathys, Cloud of
Daggers, Compelled Duel, Hunger of Hadar) → **34 remain.** Building
archetype-easiest first; smite batch is PR #1. Triage:

- **A. Smite riders** (ride smite_rider, PR #112).
  - *Clean now (existing conditions):* **Blinding Smite** (CON →
    co_blinded), **Wrathful Smite** (WIS → co_frightened). ← PR #1
  - *Need small spec extensions:* Branding (no-save bonus dmg vs a
    type), Thunderous (prone + push), Staggering (new debuff condition),
    Banishing (banish + HP-gate).
- **B. AoE save-burst** (aoe_attack): Arms of Hadar, Conjure Barrage,
  Conjure Volley, Destructive Wave.
- **C. Self weapon-buff** (Divine Favor shape): Elemental Weapon; Blade
  Ward (needs BPS-resistance modeling).
- **D. Attack + forced-movement**: Thorn Whip (pull), Hail of Thorns,
  Lightning Arrow.
- **E. Ally/utility auras** (Spirit Guardians shape, NEW ally-side
  sub-shapes): Aura of Vitality (heal-over-time), Aura of Purity
  (save-buff), Circle of Power, Crusader's Mantle (offensive ally aura).
- **F. Hard control**: Feeblemind, Crown of Madness (forced attack),
  Grasping Vine (pull), Witch Bolt (sustained channel).
- **G. Defer — need new systems**: Arcane Gate (teleport), Wall of
  Stone (walls/terrain), Conjure Woodland Beings (summons), Swift
  Quiver (action-economy), Cordon of Arrows (traps). **Non-combat
  (likely never sim-modeled):** Beast Sense, Feign Death, Friends,
  Nystul's Magic Aura, Telepathy. **Decide:** True Strike (2014
  advantage-buff vs 2024 attack-cantrip redesign).

## Engine enhancements likely needed (build-once, then ride)

- Ally-affecting auras: heal-over-time (Aura of Vitality), save-buff
  (Circle of Power / Aura of Purity), offensive ally aura (Crusader's
  Mantle). Spirit Guardians proved enemies-only damage auras; these are
  the ally-side sub-shapes.
- Smite-spec extensions: optional/no-save smites (Branding), rider +
  forced-movement (Thunderous), HP-gated rider (Banishing), new
  conditions (Staggering).
- Forced-movement *pull* (Thorn Whip / Grasping Vine) — we have push;
  pull is the inverse.
- Sustained-channel spells (Witch Bolt) — multi-turn repeating
  same-target damage.
- Bigger systems (later / maybe never for a combat sim): summons,
  walls/terrain, teleport/positional, action-economy grants.

## Optional efficiency check (Phil's call, not a gate)

**Verify SRD 5.2.1 coverage** (the quick-win from data-sources.md): 5.2
is broader than 5.1; anything it covers is fully open + machine-
ingestable, and a few "non-SRD"-tagged items may already be free —
which could shorten the manual-build list. Independent of the non-SRD
work Phil started; run if/when useful.

## Testing approach for harder spells

Positional / multi-turn / conditional spells need scenario-style tests
(seeded multi-round fixtures), not just single-call unit tests. Design
the harness alongside the engine enhancement that needs it.
