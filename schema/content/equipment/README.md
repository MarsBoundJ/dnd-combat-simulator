# equipment/

Content directory for weapons, armor, shields, tools, consumables, magic items,
ammunition, and miscellaneous gear. Schema:
`schema/definitions/equipment.schema.json`.

Empty as of PR #84 — schema scaffolded ahead of content. Weapons and armor are
currently inlined directly in `pc_spec.weapons` / `pc_spec.armor` blocks
(unchanged); future content-loader-managed equipment files will plug into the
same shape via `eq_*.yaml` entries here.

Convention: filenames mirror equipment ids (`eq_longsword.yaml`,
`eq_chain_mail.yaml`, `eq_potion_of_healing.yaml`, etc.). Category-specific
fields apply based on `category` (weapon / armor / shield / tool / consumable
/ magic_item / ammunition / spellcasting_focus / mount_or_vehicle /
trade_good / misc).
