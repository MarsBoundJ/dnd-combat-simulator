# Boss Sim — Run 2 (post-casters) — Tier-3 party vs Adult Red Dragon

*Seed 42; reproducible via `sims/run_first_sim.py`. 2026-06-03 — RE-RUN after
the decision-layer fixes + the Wizard spell list (#162) + control spells
(Polymorph #159, Hold Monster #160, Wall of Force #165). Compare to the
first sim (`sims/report.md`, 2026-06-02), which was a 2-round flawless TPK
with casters dealing 0. See `sims/FINDINGS.md` for the run-2 diagnosis.*

**Outcome:** side_enemy_victory in 4 rounds (vs 2 in the first sim).

## Final state
| Combatant | Side | HP | Status |
|---|---|---|---|
| Fighter_Champion | pc | 0/121 | 💀 dead |
| Cleric | pc | 0/107 | 💀 dead |
| Wizard_Evoker | pc | 0/80 | 💀 dead |
| Bard_Lore | pc | 17/94 | 🏃 fled |
| Adult_Red_Dragon | enemy | 134/256 | alive |

## Derived stats (a first taste of the per-sim buckets)
| Combatant | Dmg dealt | Attacks | Hits | To-hit % | Healing | Dmg taken |
|---|--:|--:|--:|--:|--:|--:|
| Fighter_Champion | 103 | 12 | 8 | 66% | 68 | 200 |
| Cleric | 0 | 0 | 0 | — | 0 | 133 |
| Wizard_Evoker | 19 | 1 | 1 | 100% | 12 | 103 |
| Bard_Lore | 0 | 0 | 0 | — | 11 | 88 |
| Adult_Red_Dragon | 524 | 12 | 6 | 50% | 0 | 122 |

## Round-by-round

### Round 1

**Adult_Red_Dragon's turn**
- save: Fighter_Champion dexterity DC 21 → fail (rolled 6)
- Adult_Red_Dragon → Fighter_Champion: 53 fire (68 HP left)
- save: Cleric dexterity DC 21 → fail (rolled 7)
- Adult_Red_Dragon → Cleric: 64 fire (43 HP left)
- save: Wizard_Evoker dexterity DC 21 → fail (rolled 16)
- Adult_Red_Dragon → Wizard_Evoker: 50 fire (30 HP left)
- save: Bard_Lore dexterity DC 21 → fail (rolled 12)
- Adult_Red_Dragon → Bard_Lore: 56 fire (38 HP left)

**Bard_Lore's turn**
- save: Adult_Red_Dragon wisdom DC 18 → success (rolled 11)

**Wizard_Evoker's turn**
- attack: Wizard_Evoker → Adult_Red_Dragon hit (23)
- Wizard_Evoker → Adult_Red_Dragon: 19 cold (237 HP left)

**Fighter_Champion's turn**
- attack: Fighter_Champion → Adult_Red_Dragon miss (16)
- attack: Fighter_Champion → Adult_Red_Dragon hit (22)
- Fighter_Champion → Adult_Red_Dragon: 10 slashing (227 HP left)
- attack: Fighter_Champion → Adult_Red_Dragon hit (19)
- Fighter_Champion → Adult_Red_Dragon: 17 slashing (210 HP left)
- heal: Fighter_Champion +15 (→ 83)
- attack: Adult_Red_Dragon → Fighter_Champion crit (34)
- ⚔️ legendary action: la_pounce (2 left)

**Cleric's turn**
- heal: Wizard_Evoker +12 (→ 42)
- attack: Adult_Red_Dragon → Fighter_Champion miss (20)
- ⚔️ legendary action: la_pounce (1 left)

### Round 2

**Adult_Red_Dragon's turn**
- 🎲 recharge a_fire_breath: rolled 5 → recharged
- save: Fighter_Champion dexterity DC 21 → fail (rolled 17)
- Adult_Red_Dragon → Fighter_Champion: 57 fire (26 HP left)
- save: Cleric dexterity DC 21 → fail (rolled 11)
- Adult_Red_Dragon → Cleric: 69 fire (0 HP left)
- 💀 None dropped
- save: Wizard_Evoker dexterity DC 21 → fail (rolled 15)
- Adult_Red_Dragon → Wizard_Evoker: 53 fire (0 HP left)
- 💀 None dropped
- save: Bard_Lore dexterity DC 21 → success (rolled 28)
- Adult_Red_Dragon → Bard_Lore: 32 fire (6 HP left)

**Bard_Lore's turn**
- save: Adult_Red_Dragon wisdom DC 18 → success (rolled 8)
- attack: Adult_Red_Dragon → Fighter_Champion miss (23)
- ⚔️ legendary action: la_pounce (2 left)

**Fighter_Champion's turn**
- attack: Fighter_Champion → Adult_Red_Dragon miss (16)
- attack: Fighter_Champion → Adult_Red_Dragon hit (27)
- Fighter_Champion → Adult_Red_Dragon: 12 slashing (198 HP left)
- attack: Fighter_Champion → Adult_Red_Dragon hit (20)
- Fighter_Champion → Adult_Red_Dragon: 16 slashing (182 HP left)
- heal: Fighter_Champion +23 (→ 49)
- attack: Fighter_Champion → Adult_Red_Dragon miss (17)
- attack: Fighter_Champion → Adult_Red_Dragon miss (15)
- attack: Fighter_Champion → Adult_Red_Dragon hit (22)
- Fighter_Champion → Adult_Red_Dragon: 12 slashing (170 HP left)
- attack: Adult_Red_Dragon → Fighter_Champion hit (31)
- Adult_Red_Dragon → Fighter_Champion: 9 slashing (40 HP left)
- Adult_Red_Dragon → Fighter_Champion: 7 fire (33 HP left)
- ⚔️ legendary action: la_pounce (1 left)

### Round 3

**Adult_Red_Dragon's turn**
- 🎲 recharge a_fire_breath: rolled 1 → not yet
- attack: Adult_Red_Dragon → Fighter_Champion miss (15)
- attack: Adult_Red_Dragon → Fighter_Champion miss (18)
- attack: Adult_Red_Dragon → Fighter_Champion hit (26)
- Adult_Red_Dragon → Fighter_Champion: 13 slashing (20 HP left)
- Adult_Red_Dragon → Fighter_Champion: 3 fire (17 HP left)

**Bard_Lore's turn**
- heal: Bard_Lore +11 (→ 17)
- heal: Fighter_Champion +10 (→ 27)
- attack: Adult_Red_Dragon → Fighter_Champion miss (17)
- ⚔️ legendary action: la_pounce (2 left)

**Fighter_Champion's turn**
- attack: Fighter_Champion → Adult_Red_Dragon hit (28)
- Fighter_Champion → Adult_Red_Dragon: 9 slashing (161 HP left)
- attack: Fighter_Champion → Adult_Red_Dragon hit (26)
- Fighter_Champion → Adult_Red_Dragon: 12 slashing (149 HP left)
- attack: Fighter_Champion → Adult_Red_Dragon hit (19)
- Fighter_Champion → Adult_Red_Dragon: 15 slashing (134 HP left)
- heal: Fighter_Champion +20 (→ 47)
- attack: Adult_Red_Dragon → Fighter_Champion miss (21)
- ⚔️ legendary action: la_pounce (1 left)

### Round 4

**Adult_Red_Dragon's turn**
- 🎲 recharge a_fire_breath: rolled 3 → not yet
- attack: Adult_Red_Dragon → Fighter_Champion hit (21)
- Adult_Red_Dragon → Fighter_Champion: 13 slashing (34 HP left)
- Adult_Red_Dragon → Fighter_Champion: 7 fire (27 HP left)
- attack: Adult_Red_Dragon → Fighter_Champion hit (29)
- Adult_Red_Dragon → Fighter_Champion: 17 slashing (10 HP left)
- Adult_Red_Dragon → Fighter_Champion: 5 fire (5 HP left)
- attack: Adult_Red_Dragon → Fighter_Champion hit (22)
- Adult_Red_Dragon → Fighter_Champion: 12 slashing (0 HP left)
- 💀 None dropped
- Adult_Red_Dragon → Fighter_Champion: 4 fire (0 HP left)
- 💀 None dropped

**Bard_Lore's turn**
- 🏃 Bard_Lore FLED (['last_conscious_pc'])