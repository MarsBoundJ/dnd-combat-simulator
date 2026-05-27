# backgrounds/

Content directory for PHB 2024 backgrounds. Schema:
`schema/definitions/background.schema.json`.

Empty as of PR #84 — schema scaffolded ahead of content. Add `bg_*.yaml` files
following the background schema. The loader (`engine/loader.py`) picks them
up automatically and validates against the schema on load.

Convention: filenames mirror background ids (`bg_acolyte.yaml`,
`bg_soldier.yaml`, `bg_sage.yaml`, etc.). RAW PHB 2024 backgrounds grant:
- Ability Score Increases (+2 / +1 across three abilities)
- 2 skill proficiencies
- 1 tool proficiency
- An Origin Feat (referenced by `ft_*` id)
- Starting equipment / gold choice
