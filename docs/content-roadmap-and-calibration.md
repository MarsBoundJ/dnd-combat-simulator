# Content Roadmap + Optimization Calibration

(Companion to `stocktake-2026-06-02.md` and `sims/FINDINGS.md`.)

## Content ceiling — "how much content is enough"
In order:
1. **Finish the SRD** — remaining SRD monsters (`docs/srd/MONSTERS_NEED_ENGINE_WORK.md`
   is the working list; most engine blockers are now built) + any other
   remaining SRD content (spells, etc.).
2. **PHB delta** — PHB content not already in the SRD (classes/subclasses/
   spells/feats the SRD omits).
3. **MM delta** — MM monsters not already in the SRD.
4. **A few spells / items from other sources** — explicitly *not a lot*.

That's the ceiling. We are NOT building a universal content database —
just enough breadth for the eHP/DPR + reception signal to be
representative, then stop widening. Content is bounded and mostly
mechanical now; the open-ended high-value work is the **AI/decision layer
+ calibration** below.

## Optimization dial + the WoTC monster-AoE baseline
The behavior model has a **1–5 optimization scale** (1 = Noob ↔ 5 =
Perfect). Calibration principle:

- **WoTC designers reportedly assume AoE monsters target only ~2 PCs** with
  a breath weapon / AoE — not the whole party. Nuking all 4 is
  *over*-optimized vs design intent.
- So **WoTC's *intended* monster behavior sits mid-scale (~2–3)**; CR /
  encounter math is tuned for under-optimized monsters.
- **Why:** safeguards against party-wipe — if a control AoE (e.g. Hypnotic
  Pattern) always hit all 4 and all failed, nobody's left to recover the
  party. Capping AoE targeting keeps encounters recoverable.

**This reframes the first sim's 2-round TPK:** errors on *both* ends of the
dial — PCs too low (Bard fled, casters idle) AND the dragon's AoE too high
(breath on all 4 ≈ optimal). Matching WoTC difficulty means running
monsters around mid-scale, not 5.

**The optimal vs WoTC-intended vs actual-table divergence is itself a
measurable axis** — and feeds the Trusight sim-vs-reception thesis.

### Open design questions (to discuss)
- Encode a **"WoTC baseline" behavior preset** (~level 2–3) as the default
  for CR-matching, distinct from the optimal (5) preset.
- Likely mechanism: **cap AoE target count by optimization level** (L2–3 →
  ~2 targets; L5 → all-in-area). Same idea may extend to focus-fire and
  save-or-suck spam.
- Per-sim metric buckets should record the optimization level used per
  side, so data separates "optimal" from "intended" runs.

## AoE targeting model (refined + locked, Jun 2)
- **Headline = the RANGE.** Run each encounter at both a WoTC-baseline
  pass and an optimal pass; output is a lethality *band*. Band width per
  monster = a metric ("how much skilled play matters"). Build **proxy-first**.
- **The dial is aim/reposition EFFORT, not a target count.** Nobody picks a
  number; they pick where to point the template, and count EMERGES from
  (effort × party spread × geometry). Model effort, count what's caught.
- **Per-level aim policy:** L1 noob → aim at nearest enemy, no reposition,
  small tunnel-vision chance of 1, may clip allies. L3 baseline → best
  static cluster, avoid allies (~2 PCs). L5 optimal → reposition for max PC
  coverage, weight PCs > expendables, factor save odds, avoid allies (all
  reachable).
- **≥2 floor is geometry + clustering, not choice.** Even a noob rarely
  catches exactly 1; when they do it's forced by the map (spread/terrain)
  or tunnel-vision.
- **Friendly-fire asymmetry** is the natural cap: PCs self-cap to avoid
  clipping allies (why a player Fireballs one straggler); a solo dragon has
  no such concern (why the first-sim dragon hit all 4); a monster with
  minions flips it.
- **Proxy = "no reposition + naive aim"; principled upgrade = "let the
  party spread tactically."** Same geometry machinery — proxy is a clean
  subset, no throwaway.
- **Calibration check:** a competent party spread vs a mobile dragon should
  emerge at ~2 PCs caught → validates both the positioning AI and the WoTC
  folklore. Lethality ≈ recharge-frequency × targets-per-breath.
