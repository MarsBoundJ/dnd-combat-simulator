# data-sources.md — D&D Combat Simulator

This is the content-sourcing + authoring posture for the simulator. It
is the "methodology doc" that becomes load-bearing when any sim output
goes public (Stage 3+). Keep it accurate; a future session must not
quietly relax it. **Not legal advice** — the public / for-profit pivot
(Stage 3/4) is the explicit trigger to get real counsel.

## Goal

Model **all** of the game the sim needs to be useful — including
**non-SRD** spells, subclasses, monsters, and features — because
Trusight's comparative value (grading new UA against the content people
actually play) requires the popular non-SRD surface, much of which is
not in the SRD.

## Core legal principle

Game **mechanics/systems are not copyrightable** (17 USC §102(b);
Baker v. Selden). **Names are trademark, not copyright.** What IS
protected is **expression**: prose, flavor text, stat-block wording,
art, and the selection/arrangement of a book. Therefore:

- We may model ANY feature's mechanics, SRD or not.
- We re-express every mechanic **functionally, in our own words**,
  stored as structured data — never transcribed prose.
- "Clean room" is a slight misnomer for what we do (strict clean-room =
  two isolated teams proving independent creation, needed only for
  *copyrightable* things). We don't need that, because the mechanics
  aren't copyrightable. The accurate name is **functional
  reimplementation + provenance discipline.**

## Sourcing rules (the real hard gate — independent of copyright)

The danger is rarely "did you reimplement the mechanic" (you may); it's
**where the data came from** and **whether you reproduced expression**.

- ✅ **Own a legitimate copy of any non-SRD book you model from**
  (digital — DDB / purchased PDF — or physical; format doesn't matter).
  Provenance-of-record = that owned book.
- ✅ **SRD 5.1 / SRD 5.2.1** (CC-BY-4.0) needs no ownership and may be
  ingested from the open document directly.
- ✅ **Pure facts** (a feature exists / from Tasha's / 2020 / Wizard
  subclass) need no ownership — facts aren't copyrightable (Feist).
- ✅ **Manual reading of a convenience reference** (incl.
  dnd5e.wikidot.com) to recall/confirm a mechanic is low-stakes — it's
  fact retrieval, and the same fact is in the book you own. Read it,
  then write the mechanic in your own words.
- ❌ **Never copy-paste text** from ANY source (DDB, PDFs, wikis,
  wikidot) into content files.
- ❌ **Never machine-extract** (scrape / API-harvest / export) from
  D&D Beyond or any non-open source. Owning a DDB book licenses
  *reading*, NOT data extraction — a ToS breach independent of
  copyright. Same prohibition for an automated wikidot scrape.
- ❌ **Provenance-of-record is the owned book, never the wiki.** Using
  wikidot as a read-only memory-jogger is fine; *citing* it as the
  source in a public method doc is not. (Same fact, cleaner record —
  costs nothing since the books are owned anyway.)

Bright lines: **manual reading OK / machine extraction NOT**;
**fact-in-your-own-words OK / text transcription NOT**.

## How content is authored (the efficient + safe pipeline)

1. **Demand-rank the target list** — build the popular non-SRD content
   first (the comparison set UA gets measured against), not "all of it"
   alphabetically. Trusight reception data ranks this.
2. **Exploit archetype reuse** — most non-SRD features are recolors of
   primitives the engine already has (smite_rider, persistent_aura,
   save_attack, weapon_damage_bonus, temp_hp_grant, heal builders,
   condition inheritance, …). Adding one is usually "spec + a few lines
   + a test," not new engine work.
3. **Archetype templates (planned)** — small set of annotated YAML
   stubs (one per archetype) with allowed values as schema `enum`s
   (machine-enforced "dropdowns" via the validating loader). The form
   has no paste field for prose — the posture becomes the path of least
   resistance. Human fills ~6 mechanical fields from understanding;
   prose optional/minimal (the sim runs on mechanics; flavor is only
   for Stage-3 display, and is our words for our display, never theirs).
4. **Provenance fields** baked into each file (see below).

## Provenance metadata convention

- `source:` describes **expression origin** — for non-SRD content it is
  always `user_authored` (the YAML is our expression). `srd_5.2.1` only
  where the open document is the direct source.
- Optional `authored_from:` block (sim repo only — the copyright-
  constrained store, firewalled from the Trusight registry):
  - `sourcebook:` the owned book modeled from (a fact — clean)
  - `in_own_words: true` (the good-faith attestation)
- Real feature **names** stay internal as reception-join keys; the
  private real-name↔id map is not published. Do **not** anonymize names
  in the sim/measurement layer — renaming solves a non-problem (names
  are trademark, and naming real subclasses in analysis is nominative
  fair use) and destroys the reception-join value. (Renaming is only
  ever relevant to a Stage-4 *playable-content* product, not measurement.)

## Staged documentation ladder

- **Stage 1–2 (private, measurement — current):** light. Store
  mechanics as structured data; tag `source` honestly. No formal paper
  trail needed.
- **Stage 3 (public, PWYW/donate, Foundry-hosted):** this doc becomes
  load-bearing. Add the public-output requirements: "not affiliated
  with / endorsed by Wizards of the Coast; D&D is a WotC trademark"
  disclaimer; no WotC logos/trade dress; nominative-fair-use naming;
  functional descriptions only.
- **Stage 4 (AI-DM / playable content):** categorically higher risk
  (adventure modules are the *most* protected content). Needs its own
  content architecture + **real counsel before any build**. The rename
  strategy could legitimately resurface here (serving playable content,
  not charts about it).

## Foundry

Foundry VTT = **host, never fork.** Use it via its supported
extension/API as an execution/visualization harness with our own
modules. Never fork the proprietary codebase into a derivative VTT.

## Efficiency quick-win (do first)

**Verify SRD 5.2.1's actual coverage.** It is much broader than SRD
5.1; anything it covers is fully open AND machine-ingestable from the
open document — no owned-book step, no manual intake. We currently mark
content conservatively as non-SRD without having verified 5.2 coverage,
so we may be hand-building things that are already free.

## Deferred

- Open5e API ingestion for SRD-covered monsters/spells.
- Archetype-template + schema-enum authoring forms (Stage-3-era tool).
- `authored_from` provenance block on content files.
