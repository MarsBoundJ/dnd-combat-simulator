# Boss Sim — Run 3 (positioning stack live) — Tier-3 vs Adult Red Dragon

*Seed 42; reproducible via `sims/run_boss_sim.py`. 2026-06-03. Spread starting formation + full positioning stack (max_aoe_coverage + PC de-cluster). Compare runs 1-2 (`report.md`, `report_run2_post_casters.md`).*

**Outcome:** side_enemy_victory in 13 rounds. First to act: **Adult_Red_Dragon**. PCs caught by the round-1 breath: **2** (runs 1-2 caught all 4). Party damage dealt: **247**.

## Final state
| Combatant | Side | HP | Status |
|---|---|---|---|
| Fighter_Champion | pc | 0/126 | dead |
| Cleric | pc | 112/112 | fled |
| Wizard_Evoker | pc | 0/85 | dead |
| Bard_Lore | pc | 0/99 | dead |
| Adult_Red_Dragon | enemy | 9/256 | alive |

## Derived stats
| Combatant | Dmg dealt | Attacks | Hits | Healing | Dmg taken |
|---|--:|--:|--:|--:|--:|
| Fighter_Champion | 173 | 17 | 17 | 118 | 244 |
| Cleric | 0 | 1 | 0 | 0 | 0 |
| Wizard_Evoker | 74 | 1 | 0 | 46 | 138 |
| Bard_Lore | 0 | 0 | 0 | 0 | 111 |
| Adult_Red_Dragon | 493 | 16 | 6 | 0 | 247 |

## Round-by-round

### Round 1

**Adult_Red_Dragon's turn**
- save: Fighter_Champion dexterity DC 21 -> fail (rolled 6)
- Adult_Red_Dragon -> Fighter_Champion: 53 fire (68 HP left)
- save: Wizard_Evoker dexterity DC 21 -> fail (rolled 9)
- Adult_Red_Dragon -> Wizard_Evoker: 64 fire (16 HP left)

**Bard_Lore's turn**
- save: Adult_Red_Dragon wisdom DC 18 -> success (rolled 21)

**Wizard_Evoker's turn**
- save: Adult_Red_Dragon wisdom DC 18 -> success (rolled 18)

**Fighter_Champion's turn**
- heal: Fighter_Champion +18 (-> 86)

**Cleric's turn**
- heal: Wizard_Evoker +12 (-> 28)

### Round 2

**Adult_Red_Dragon's turn**
- save: Fighter_Champion dexterity DC 21 -> fail (rolled 13)
- Adult_Red_Dragon -> Fighter_Champion: 51 fire (35 HP left)
- save: Wizard_Evoker dexterity DC 21 -> success (rolled 22)
- Adult_Red_Dragon -> Wizard_Evoker: 26 fire (2 HP left)

**Bard_Lore's turn**
- save: Adult_Red_Dragon wisdom DC 18 -> success (rolled 19)

**Wizard_Evoker's turn**
- save: Adult_Red_Dragon wisdom DC 18 -> success (rolled 19)

**Fighter_Champion's turn**
- heal: Fighter_Champion +17 (-> 52)

**Cleric's turn**
- heal: Wizard_Evoker +12 (-> 14)
- heal: Wizard_Evoker +9 (-> 23)

### Round 3

**Adult_Red_Dragon's turn**
- moved Adult_Red_Dragon [0, 0]->[8, 5]

**Bard_Lore's turn**
- save: Adult_Red_Dragon wisdom DC 18 -> success (rolled 13)
- heal: Wizard_Evoker +13 (-> 36)

**Wizard_Evoker's turn**
- save: Adult_Red_Dragon charisma DC 18 -> success (rolled 15)

**Fighter_Champion's turn**
- moved Fighter_Champion [10, 0]->[8, 4]
- attack: Fighter_Champion -> Adult_Red_Dragon hit (28)
- Fighter_Champion -> Adult_Red_Dragon: 13 slashing (243 HP left)
- heal: Fighter_Champion +19 (-> 71)
- attack: Adult_Red_Dragon -> Fighter_Champion miss (16)

**Cleric's turn**
- attack: Adult_Red_Dragon -> Fighter_Champion hit (22)
- Adult_Red_Dragon -> Fighter_Champion: 14 slashing (57 HP left)
- Adult_Red_Dragon -> Fighter_Champion: 7 fire (50 HP left)

### Round 4

**Adult_Red_Dragon's turn**
- attack: Adult_Red_Dragon -> Fighter_Champion miss (17)
- attack: Adult_Red_Dragon -> Fighter_Champion hit (21)
- Adult_Red_Dragon -> Fighter_Champion: 18 slashing (32 HP left)
- Adult_Red_Dragon -> Fighter_Champion: 5 fire (27 HP left)
- attack: Adult_Red_Dragon -> Fighter_Champion hit (30)
- Adult_Red_Dragon -> Fighter_Champion: 15 slashing (12 HP left)
- Adult_Red_Dragon -> Fighter_Champion: 6 fire (6 HP left)

**Bard_Lore's turn**
- save: Adult_Red_Dragon wisdom DC 18 -> success (rolled 16)
- attack: Adult_Red_Dragon -> Fighter_Champion miss (19)

**Wizard_Evoker's turn**
- save: Adult_Red_Dragon charisma DC 18 -> fail (rolled 14)

**Fighter_Champion's turn**
- attack: Fighter_Champion -> Adult_Red_Dragon hit (28)
- Fighter_Champion -> Adult_Red_Dragon: 13 slashing (230 HP left)
- heal: Fighter_Champion +23 (-> 29)
- attack: Fighter_Champion -> Adult_Red_Dragon hit (24)
- Fighter_Champion -> Adult_Red_Dragon: 14 slashing (216 HP left)
- attack: Fighter_Champion -> Adult_Red_Dragon hit (22)
- Fighter_Champion -> Adult_Red_Dragon: 9 slashing (207 HP left)
- attack: Fighter_Champion -> Adult_Red_Dragon hit (27)
- Fighter_Champion -> Adult_Red_Dragon: 10 slashing (197 HP left)

**Cleric's turn**

### Round 5

**Adult_Red_Dragon's turn**
- attack: Adult_Red_Dragon -> Fighter_Champion miss (16)
- attack: Adult_Red_Dragon -> Fighter_Champion miss (18)
- attack: Adult_Red_Dragon -> Fighter_Champion miss (19)

**Bard_Lore's turn**
- heal: Fighter_Champion +15 (-> 44)
- heal: Fighter_Champion +10 (-> 54)

**Wizard_Evoker's turn**
- save: Adult_Red_Dragon charisma DC 18 -> success (rolled 19)

**Fighter_Champion's turn**
- attack: Fighter_Champion -> Adult_Red_Dragon crit (30)
- attack: Fighter_Champion -> Adult_Red_Dragon hit (25)
- Fighter_Champion -> Adult_Red_Dragon: 13 slashing (184 HP left)
- attack: Fighter_Champion -> Adult_Red_Dragon hit (28)
- Fighter_Champion -> Adult_Red_Dragon: 12 slashing (172 HP left)

**Cleric's turn**

### Round 6

**Adult_Red_Dragon's turn**
- attack: Adult_Red_Dragon -> Fighter_Champion miss (18)
- attack: Adult_Red_Dragon -> Fighter_Champion hit (32)
- Adult_Red_Dragon -> Fighter_Champion: 13 slashing (41 HP left)
- Adult_Red_Dragon -> Fighter_Champion: 4 fire (42 HP left)
- attack: Adult_Red_Dragon -> Fighter_Champion miss (24)

**Bard_Lore's turn**
- heal: Fighter_Champion +16 (-> 58)
- attack: Adult_Red_Dragon -> Fighter_Champion miss (15)

**Wizard_Evoker's turn**
- save: Adult_Red_Dragon wisdom DC 18 -> fail (rolled 16)

**Fighter_Champion's turn**
- attack: Fighter_Champion -> Adult_Red_Dragon hit (27)
- Fighter_Champion -> Adult_Red_Dragon: 11 slashing (161 HP left)
- attack: Fighter_Champion -> Adult_Red_Dragon hit (27)
- Fighter_Champion -> Adult_Red_Dragon: 12 slashing (149 HP left)
- attack: Fighter_Champion -> Adult_Red_Dragon hit (22)
- Fighter_Champion -> Adult_Red_Dragon: 12 slashing (137 HP left)

**Cleric's turn**

### Round 7

**Adult_Red_Dragon's turn**
- save: Fighter_Champion dexterity DC 21 -> fail (rolled 19)
- Adult_Red_Dragon -> Fighter_Champion: 44 fire (14 HP left)

**Bard_Lore's turn**

**Wizard_Evoker's turn**
- attack: Wizard_Evoker -> Adult_Red_Dragon miss (out_of_range)

**Fighter_Champion's turn**
- attack: Fighter_Champion -> Adult_Red_Dragon hit (28)
- Fighter_Champion -> Adult_Red_Dragon: 13 slashing (124 HP left)
- attack: Fighter_Champion -> Adult_Red_Dragon hit (28)
- Fighter_Champion -> Adult_Red_Dragon: 10 slashing (114 HP left)
- attack: Fighter_Champion -> Adult_Red_Dragon crit (30)

**Cleric's turn**

### Round 8

**Adult_Red_Dragon's turn**
- save: Bard_Lore dexterity DC 21 -> success (rolled 22)
- Adult_Red_Dragon -> Bard_Lore: 33 fire (66 HP left)

**Bard_Lore's turn**
- save: Adult_Red_Dragon wisdom DC 18 -> success (rolled 18)

**Wizard_Evoker's turn**
- save: Adult_Red_Dragon dexterity DC 18 -> fail (rolled None)
- Wizard_Evoker -> Adult_Red_Dragon: 74 force (40 HP left)

**Fighter_Champion's turn**
- attack: Fighter_Champion -> Adult_Red_Dragon hit (20)
- Fighter_Champion -> Adult_Red_Dragon: 9 slashing (31 HP left)
- attack: Fighter_Champion -> Adult_Red_Dragon hit (27)
- Fighter_Champion -> Adult_Red_Dragon: 10 slashing (21 HP left)
- attack: Fighter_Champion -> Adult_Red_Dragon hit (26)
- Fighter_Champion -> Adult_Red_Dragon: 12 slashing (9 HP left)

**Cleric's turn**

### Round 9

**Adult_Red_Dragon's turn**
- save: Bard_Lore dexterity DC 21 -> success (rolled 27)
- Adult_Red_Dragon -> Bard_Lore: 30 fire (36 HP left)

**Bard_Lore's turn**
- attack: Adult_Red_Dragon -> Fighter_Champion miss (16)

**Wizard_Evoker's turn**
- save: Adult_Red_Dragon wisdom DC 18 -> success (rolled 20)
- attack: Adult_Red_Dragon -> Fighter_Champion hit (25)
- Adult_Red_Dragon -> Fighter_Champion: 10 slashing (4 HP left)
- Adult_Red_Dragon -> Fighter_Champion: 4 fire (0 HP left)

**Cleric's turn**
- attack: Cleric -> Cleric miss (13)

### Round 10

**Adult_Red_Dragon's turn**
- save: Wizard_Evoker dexterity DC 21 -> fail (rolled 20)
- Adult_Red_Dragon -> Wizard_Evoker: 48 fire (0 HP left)

**Bard_Lore's turn**
- save: Bard_Lore wisdom DC 18 -> fail (rolled 14)
- save: Adult_Red_Dragon wisdom DC 18 -> success (rolled 23)

**Cleric's turn**

### Round 11

**Adult_Red_Dragon's turn**
- save: Bard_Lore dexterity DC 21 -> success (rolled 24)
- Adult_Red_Dragon -> Bard_Lore: 32 fire (4 HP left)

**Bard_Lore's turn**
- save: Adult_Red_Dragon wisdom DC 18 -> fail (rolled 14)

**Cleric's turn**

### Round 12

**Adult_Red_Dragon's turn**
- moved Adult_Red_Dragon [8, 5]->[9, 6]
- attack: Adult_Red_Dragon -> Bard_Lore hit (24)
- Adult_Red_Dragon -> Bard_Lore: 12 slashing (0 HP left)
- Adult_Red_Dragon -> Bard_Lore: 4 fire (0 HP left)

**Cleric's turn**
- Cleric FLED (['last_conscious_pc'])