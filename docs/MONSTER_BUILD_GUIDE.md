# Monster Build Guide (browser lane)

How to build SRD monsters as content. Monsters are the **opposition** the
sim measures PCs against — a real bestiary is what makes the simulator
usable. Read this before building.

## Why monsters are a clean lane

Monsters declare their actions **directly in the stat block** (`actions:`
with inline `pipeline:` steps) — they do **NOT** touch `pc_schema.py` or
any engine file. You work purely in `schema/content/monsters/` + tests.
Template of record: `schema/content/monsters/m_goblin_warrior.yaml`.

## Source & provenance

- Read each stat block from `docs/srd/SRD_CC_v5.2.1.pdf`. SRD 5.2.1 is
  CC-BY and machine-ingestable from the open doc (see `docs/data-sources.md`).
- Re-express mechanics in structured YAML; `source: srd_5.2.1`. Never
  paste flavor/prose text.

## Work order

From the monsters priority CSV (`docs/srd/srd_monsters_priority.csv`),
build highest-rating first. NOTE: high-rating monsters skew complex
(dragons/liches → recharge/legendary/spellcasting). Within each rating,
**build the stat-block-composable ones first and defer the rest** — don't
stall the batch on one legendary dragon.

---

## TRIAGE — build now vs defer (mechanical, not judgment)

### Step 1 — defer-trigger keyword scan (do this FIRST)
Scan the stat block text. If ANY of these phrases appears, the monster (or
that ability) is **DEFERRED** — record it in
`docs/srd/MONSTERS_NEED_ENGINE_WORK.md` under the named bucket. Do not
build a partial/fake version.

| Keyword in stat block | Bucket |
|---|---|
| `Recharge` (5–6 / 6 / after a rest) | Recharge abilities |
| `Legendary Action`, `Legendary Resistance` | Legendary Actions & Resistance |
| `Lair Action`, `Regional Effect` | Lair Actions & Regional Effects |
| `Spellcasting`, `Innate Spellcasting` | Monster Spellcasting |
| `Regeneration`, "regains … at the start of its turn" | Regeneration / recurring self-heal |
| `summon`, `conjure`, calls/creates allies | Summon / call adds |
| `Death Burst`, "When it dies", split-on-hit | On-death / triggered effects |
| `Change Shape`, `Shapechanger` | Form change |
| `Swallow`, `Engulf` | Engulf / swallow |
| "each creature within N feet" aura, `Frightful Presence` | Aura traits |
| `Magic Resistance`, "from nonmagical attacks" | Conditional immunities/resistances |

### Step 2 — GREEN checklist (build only if ALL true)
A monster is **BUILDABLE NOW** when:
1. **No defer-trigger keyword** fired in Step 1.
2. **All offense** is one of: weapon attacks (`attack_roll` + hit-gated
   `damage`), a `multiattack` of those, or a `forced_save` attack whose
   on-fail applies an **already-existing condition**
   (`co_frightened`, `co_prone`, `co_poisoned`, `co_grappled`,
   `co_restrained`, `co_stunned`, `co_blinded`, `co_paralyzed`,
   `co_charmed`, `co_incapacitated`, `co_prone`, …).
3. **Traits** are either declarative fields (damage resistances /
   vulnerabilities / immunities, condition immunities, senses,
   languages, skills) OR map to an existing modifier/condition.
4. **No spellcasting.**

If all four hold → build it. If any fails → defer the monster (or, when
only one ability is blocked and the rest is a complete monster, build the
monster WITHOUT that ability and log the missing ability in the queue —
note this in the monster file's header comment).

### Allowed approximation (build, don't defer)
- **Non-walk movement** (fly/swim/burrow): use `walk` speed as the
  positional stand-in; note the real mode in the file header. Don't defer
  flyers over movement alone.

---

## Authoring

Copy the shape of `m_goblin_warrior.yaml`: `id` (`m_<snake_name>`), `name`,
`source`, `size`, `creature_type`, `alignment`, `combat` (AC / HP
{average, dice, con_contribution} / speed / initiative), `abilities`
(score + save each), `skills`, damage `resistances`/`vulnerabilities`/
`immunities`, `condition_immunities`, `senses`, `languages`, `cr`
{value, xp, proficiency_bonus}, `traits`, `actions`, optional
`bonus_actions` / `reactions`, and a `behavior_profile`. Validate against
`schema/definitions/monster.schema.json`.

## Locked files / rules

- Touch ONLY `schema/content/monsters/`, your own tests, and the two
  monster docs. Do NOT edit engine files, `pc_schema.py`, classes,
  subclasses, spell content, or tests you didn't write.
- Reuse existing conditions; do NOT invent new `co_*` for monsters
  (if a monster needs a brand-new condition, that's a defer).
- Commit per ~5 monsters; run `pytest -q` (zero regressions) before each
  commit; push your branch, don't merge.

## Per-batch report format

End each batch with two tables:
- **Built:** monster · CR · rating
- **Deferred:** monster · CR · rating · bucket (and confirm each was
  appended to `MONSTERS_NEED_ENGINE_WORK.md`)
