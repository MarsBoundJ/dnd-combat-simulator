# First Sim — Tier-3 party vs Adult Red Dragon

*Seed 42; reproducible via `sims/run_first_sim.py`. June 2 2026 — the project's first end-to-end encounter.*

**Outcome:** side_enemy_victory in 2 rounds.

## Final state
| Combatant | Side | HP | Status |
|---|---|---|---|
| Fighter_Champion | pc | 0/121 | 💀 dead |
| Cleric | pc | 0/107 | 💀 dead |
| Wizard_Evoker | pc | 0/80 | 💀 dead |
| Bard_Lore | pc | 38/94 | 🏃 fled |
| Adult_Red_Dragon | enemy | 234/256 | alive |

## Derived stats (a first taste of the per-sim buckets)
| Combatant | Dmg dealt | Attacks | Hits | To-hit % | Healing | Dmg taken |
|---|--:|--:|--:|--:|--:|--:|
| Fighter_Champion | 22 | 3 | 2 | 66% | 19 | 146 |
| Cleric | 0 | 0 | 0 | — | 0 | 130 |
| Wizard_Evoker | 0 | 0 | 0 | — | 12 | 114 |
| Bard_Lore | 0 | 0 | 0 | — | 0 | 56 |
| Adult_Red_Dragon | 446 | 3 | 2 | 66% | 0 | 22 |

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
- 🏃 Bard_Lore FLED (['bloodied'])

**Wizard_Evoker's turn**
- attack: Adult_Red_Dragon → Fighter_Champion miss (out_of_range)
- ⚔️ legendary action: la_pounce (2 left)

**Fighter_Champion's turn**
- attack: Fighter_Champion → Adult_Red_Dragon miss (14)
- attack: Fighter_Champion → Adult_Red_Dragon hit (23)
- Fighter_Champion → Adult_Red_Dragon: 12 slashing (244 HP left)
- attack: Fighter_Champion → Adult_Red_Dragon hit (22)
- Fighter_Champion → Adult_Red_Dragon: 10 slashing (234 HP left)
- heal: Fighter_Champion +19 (→ 87)
- attack: Adult_Red_Dragon → Fighter_Champion hit (21)
- Adult_Red_Dragon → Fighter_Champion: 13 slashing (74 HP left)
- Adult_Red_Dragon → Fighter_Champion: 3 fire (71 HP left)
- ⚔️ legendary action: la_pounce (1 left)

**Cleric's turn**
- heal: Wizard_Evoker +12 (→ 42)
- attack: Adult_Red_Dragon → Fighter_Champion hit (29)
- Adult_Red_Dragon → Fighter_Champion: 15 slashing (56 HP left)
- Adult_Red_Dragon → Fighter_Champion: 5 fire (51 HP left)
- ⚔️ legendary action: la_pounce (0 left)

### Round 2

**Adult_Red_Dragon's turn**
- 🎲 recharge a_fire_breath: rolled 5 → recharged
- save: Fighter_Champion dexterity DC 21 → fail (rolled 13)
- Adult_Red_Dragon → Fighter_Champion: 57 fire (0 HP left)
- 💀 None dropped
- save: Cleric dexterity DC 21 → fail (rolled 5)
- Adult_Red_Dragon → Cleric: 66 fire (0 HP left)
- 💀 None dropped
- save: Wizard_Evoker dexterity DC 21 → fail (rolled 5)
- Adult_Red_Dragon → Wizard_Evoker: 64 fire (0 HP left)
- 💀 None dropped