# spell-content-roadmap.md — D&D Combat Simulator

Planning doc for expanding the sim's spell coverage. Created 2026-05-30
(Phil + Claude). Sourcing/authoring posture lives in `data-sources.md`;
follow it for every spell added.

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
