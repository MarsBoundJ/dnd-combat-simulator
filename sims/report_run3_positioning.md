# Boss Sim — Run 3 (positioning stack live) — Tier-3 vs Adult Red Dragon

*Seed 42; reproducible via `sims/run_boss_sim.py`. 2026-06-03. Spread starting formation + full positioning stack (max_aoe_coverage + PC de-cluster). Compare runs 1-2 (`report.md`, `report_run2_post_casters.md`).*

**Outcome:** side_enemy_victory in 9 rounds. First to act: **Adult_Red_Dragon**. PCs caught by the round-1 breath: **2** (runs 1-2 caught all 4). Party damage dealt: **87**.

## Final state
| Combatant | Side | HP | Status |
|---|---|---|---|
| Fighter_Champion | pc | 0/121 | dead |
| Cleric | pc | 41/107 | fled |
| Wizard_Evoker | pc | 0/80 | dead |
| Bard_Lore | pc | 0/94 | dead |
| Adult_Red_Dragon | enemy | 169/256 | alive |

## Derived stats
| Combatant | Dmg dealt | Attacks | Hits | Healing | Dmg taken |
|---|--:|--:|--:|--:|--:|
| Fighter_Champion | 75 | 15 | 7 | 153 | 276 |
| Cleric | 0 | 1 | 0 | 0 | 66 |
| Wizard_Evoker | 12 | 1 | 1 | 9 | 89 |
| Bard_Lore | 0 | 0 | 0 | 0 | 94 |
| Adult_Red_Dragon | 525 | 20 | 10 | 0 | 87 |

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
- attack: Wizard_Evoker -> Adult_Red_Dragon hit (21)
- Wizard_Evoker -> Adult_Red_Dragon: 12 cold (244 HP left)

**Fighter_Champion's turn**
- heal: Fighter_Champion +19 (-> 87)

**Cleric's turn**
- heal: Wizard_Evoker +9 (-> 25)

### Round 2

**Adult_Red_Dragon's turn**
- save: Fighter_Champion dexterity DC 21 -> fail (rolled 15)
- Adult_Red_Dragon -> Fighter_Champion: 59 fire (28 HP left)
- save: Wizard_Evoker dexterity DC 21 -> success (rolled 21)
- Adult_Red_Dragon -> Wizard_Evoker: 25 fire (0 HP left)

**Bard_Lore's turn**
- save: Adult_Red_Dragon wisdom DC 18 -> success (rolled 19)

**Fighter_Champion's turn**
- heal: Fighter_Champion +17 (-> 45)

**Cleric's turn**
- heal: Fighter_Champion +12 (-> 57)

### Round 3

**Adult_Red_Dragon's turn**
- moved Adult_Red_Dragon [0, 0]->[8, 0]
- attack: Adult_Red_Dragon -> Fighter_Champion crit (34)
- attack: Adult_Red_Dragon -> Fighter_Champion miss (20)
- attack: Adult_Red_Dragon -> Fighter_Champion hit (32)
- Adult_Red_Dragon -> Fighter_Champion: 12 slashing (45 HP left)
- Adult_Red_Dragon -> Fighter_Champion: 6 fire (39 HP left)

**Bard_Lore's turn**
- save: Adult_Red_Dragon wisdom DC 18 -> success (rolled 20)
- heal: Fighter_Champion +10 (-> 49)

**Fighter_Champion's turn**
- moved Fighter_Champion [10, 0]->[9, 0]
- attack: Fighter_Champion -> Adult_Red_Dragon hit (21)
- Fighter_Champion -> Adult_Red_Dragon: 8 slashing (236 HP left)
- attack: Fighter_Champion -> Adult_Red_Dragon miss (12)
- attack: Fighter_Champion -> Adult_Red_Dragon hit (21)
- Fighter_Champion -> Adult_Red_Dragon: 12 slashing (224 HP left)
- heal: Fighter_Champion +15 (-> 64)
- attack: Adult_Red_Dragon -> Fighter_Champion miss (21)

**Cleric's turn**
- heal: Fighter_Champion +15 (-> 79)
- attack: Adult_Red_Dragon -> Fighter_Champion hit (30)
- Adult_Red_Dragon -> Fighter_Champion: 15 slashing (64 HP left)
- Adult_Red_Dragon -> Fighter_Champion: 6 fire (58 HP left)

### Round 4

**Adult_Red_Dragon's turn**
- attack: Adult_Red_Dragon -> Fighter_Champion hit (23)
- Adult_Red_Dragon -> Fighter_Champion: 12 slashing (46 HP left)
- Adult_Red_Dragon -> Fighter_Champion: 7 fire (39 HP left)
- attack: Adult_Red_Dragon -> Fighter_Champion hit (33)
- Adult_Red_Dragon -> Fighter_Champion: 15 slashing (24 HP left)
- Adult_Red_Dragon -> Fighter_Champion: 5 fire (19 HP left)
- attack: Adult_Red_Dragon -> Fighter_Champion miss (19)

**Bard_Lore's turn**
- save: Adult_Red_Dragon wisdom DC 18 -> success (rolled 24)
- attack: Adult_Red_Dragon -> Fighter_Champion hit (30)
- Adult_Red_Dragon -> Fighter_Champion: 10 slashing (9 HP left)
- Adult_Red_Dragon -> Fighter_Champion: 2 fire (7 HP left)

**Fighter_Champion's turn**
- attack: Fighter_Champion -> Adult_Red_Dragon miss (15)
- attack: Fighter_Champion -> Adult_Red_Dragon miss (16)
- attack: Fighter_Champion -> Adult_Red_Dragon hit (24)
- Fighter_Champion -> Adult_Red_Dragon: 11 slashing (213 HP left)
- heal: Fighter_Champion +20 (-> 27)
- attack: Fighter_Champion -> Adult_Red_Dragon hit (23)
- Fighter_Champion -> Adult_Red_Dragon: 14 slashing (199 HP left)
- attack: Fighter_Champion -> Adult_Red_Dragon hit (27)
- Fighter_Champion -> Adult_Red_Dragon: 13 slashing (186 HP left)
- attack: Fighter_Champion -> Adult_Red_Dragon miss (11)
- attack: Adult_Red_Dragon -> Fighter_Champion miss (18)

**Cleric's turn**
- attack: Cleric -> Adult_Red_Dragon miss (out_of_range)
- attack: Adult_Red_Dragon -> Fighter_Champion hit (32)
- Adult_Red_Dragon -> Fighter_Champion: 13 slashing (14 HP left)
- Adult_Red_Dragon -> Fighter_Champion: 4 fire (10 HP left)

### Round 5

**Adult_Red_Dragon's turn**
- save: Cleric dexterity DC 21 -> fail (rolled 10)
- Adult_Red_Dragon -> Cleric: 66 fire (41 HP left)

**Bard_Lore's turn**
- heal: Fighter_Champion +14 (-> 24)
- attack: Adult_Red_Dragon -> Fighter_Champion hit (32)
- Adult_Red_Dragon -> Fighter_Champion: 17 slashing (7 HP left)
- Adult_Red_Dragon -> Fighter_Champion: 4 fire (3 HP left)

**Fighter_Champion's turn**
- attack: Fighter_Champion -> Adult_Red_Dragon hit (26)
- Fighter_Champion -> Adult_Red_Dragon: 7 slashing (179 HP left)
- attack: Fighter_Champion -> Adult_Red_Dragon hit (22)
- Fighter_Champion -> Adult_Red_Dragon: 10 slashing (169 HP left)
- attack: Fighter_Champion -> Adult_Red_Dragon miss (12)
- attack: Adult_Red_Dragon -> Fighter_Champion miss (22)

**Cleric's turn**
- save: Adult_Red_Dragon dexterity DC 18 -> success (rolled 9)
- attack: Adult_Red_Dragon -> Fighter_Champion miss (17)

### Round 6

**Adult_Red_Dragon's turn**
- save: Bard_Lore dexterity DC 21 -> success (rolled 24)
- Adult_Red_Dragon -> Bard_Lore: 32 fire (62 HP left)

**Bard_Lore's turn**
- heal: Fighter_Champion +18 (-> 21)
- heal: Fighter_Champion +13 (-> 34)
- attack: Adult_Red_Dragon -> Fighter_Champion miss (18)

**Fighter_Champion's turn**
- attack: Fighter_Champion -> Adult_Red_Dragon miss (18)
- attack: Fighter_Champion -> Adult_Red_Dragon miss (18)
- attack: Fighter_Champion -> Adult_Red_Dragon miss (13)
- attack: Adult_Red_Dragon -> Fighter_Champion hit (25)
- Adult_Red_Dragon -> Fighter_Champion: 18 slashing (16 HP left)
- Adult_Red_Dragon -> Fighter_Champion: 4 fire (12 HP left)

**Cleric's turn**
- save: Adult_Red_Dragon dexterity DC 18 -> success (rolled 7)
- attack: Adult_Red_Dragon -> Fighter_Champion miss (17)

### Round 7

**Adult_Red_Dragon's turn**
- attack: Adult_Red_Dragon -> Fighter_Champion miss (16)
- attack: Adult_Red_Dragon -> Fighter_Champion hit (22)
- Adult_Red_Dragon -> Fighter_Champion: 10 slashing (2 HP left)
- Adult_Red_Dragon -> Fighter_Champion: 4 fire (0 HP left)
- attack: Adult_Red_Dragon -> Cleric miss (out_of_range)

**Bard_Lore's turn**
- save: Adult_Red_Dragon wisdom DC 18 -> success (rolled 10)

**Cleric's turn**
- save: Adult_Red_Dragon dexterity DC 18 -> success (rolled 23)

### Round 8

**Adult_Red_Dragon's turn**
- save: Bard_Lore dexterity DC 21 -> fail (rolled 16)
- Adult_Red_Dragon -> Bard_Lore: 62 fire (0 HP left)

**Cleric's turn**
- Cleric FLED (['last_conscious_pc'])