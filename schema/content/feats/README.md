# feats/

Content directory for PHB 2024 feats. Schema: `schema/definitions/feat.schema.json`.

Empty as of PR #84 — schema scaffolded ahead of content. Add `ft_*.yaml` files
following the feat schema. The loader (`engine/loader.py`) picks them up
automatically and validates against the schema on load.

Convention: filenames mirror feat ids (`ft_great_weapon_master.yaml`,
`ft_sentinel.yaml`, etc.). Categories: `origin` / `general` / `fighting_style` /
`epic_boon` per PHB 2024.
