"""Monster spellcasting — let a monster action *cast* an existing spell.

RAW (SRD 5.2.1): a monster's "Spellcasting" action lists spells it can cast
"At Will" and "1/Day Each" (the 2024 stat-block format — per-day uses
rather than a PC slot table). Each such spell produces the same effect as
the spell itself, using the monster's spell save DC.

Rather than re-author every spell's pipeline inside every caster (which
duplicates complex effects like Spirit Guardians and invites drift), a
monster action references a built spell feature by id:

    spellcasting:
      ability: intelligence
      save_dc: 15            # explicit stat-block DC (optional override)
    actions:
      - id: a_cast_fire_bolt
        name: Fire Bolt
        casts: f_fire_bolt          # At Will — no gate
      - id: a_cast_fireball
        name: Fireball
        casts: f_fireball
        recharge: "daily:1"         # 1/Day — rides the recharge gate

`expand_registry` runs once after content load: each `casts` action is
replaced by a full action built from the referenced feature's
`action_template` — its `type`, `area`, `pipeline`, `concentration`,
`named_effect`, `range_ft` — so the existing candidate/scoring/execute
paths handle it unchanged. The casting monster is the source, so any
`dc_source: caster_spell_save_dc` in the borrowed pipeline resolves to the
MONSTER's DC.

Expansion rules:
  - DROP `spell_slot_level` and `upcast_scaling`: monsters don't spend PC
    spell slots (so the slot-availability candidate filter won't gate the
    action) and don't upcast — they cast at the listed level.
  - KEEP the monster action's own id / name (the stat-block label).
  - APPLY the monster action's gate: `recharge` (e.g. "daily:1" for
    1/Day, which the recharge system treats as "spent for the encounter")
    or `feature_use`. Omit both for an At-Will spell.
  - STAMP `spellcasting_ability` (and an optional `spell_save_dc`
    override) onto the monster template from its `spellcasting` block so
    _caster_spell_save_dc computes/forces the right DC.

v1 scope / deferrals:
  - "N/Day Each" for N > 1 isn't a count yet — `daily:1` (the common case)
    gates one cast per encounter; N>1 is a documented follow-up.
  - A missing/typo'd `casts` target raises at load (fail fast) — a caster
    can only reference spells that are actually built.
"""
from __future__ import annotations

# Fields copied from a spell feature's action_template into the expanded
# monster action. Deliberately excludes spell_slot_level + upcast_scaling.
_COPIED_FIELDS = (
    "type", "area", "pipeline", "concentration", "named_effect",
    "range_ft", "max_targets", "save_ability",
)


def _ability_mod(score) -> int:
    return (int(score) - 10) // 2


def spell_attack_bonus(template: dict) -> int:
    """The monster's spell attack bonus: an explicit
    `spellcasting.attack_bonus` (the 2024 stat block lists "Spell Attack
    +X") if present, else spellcasting-ability modifier + proficiency
    bonus."""
    sc = template.get("spellcasting") or {}
    if sc.get("attack_bonus") is not None:
        return int(sc["attack_bonus"])
    ability = sc.get("ability", "charisma")
    score = ((template.get("abilities") or {}).get(ability[:3]) or {}).get(
        "score", 10)
    pb = int((template.get("cr") or {}).get("proficiency_bonus", 2))
    return _ability_mod(score) + pb


def _build_from_pc_builder(monster_action: dict, feature: dict,
                             attack_bonus: int) -> dict | None:
    """Build a runnable action from a feature's `pc_builder` block (a
    spell-ATTACK marker that has no action_template — Scorching Ray /
    Guiding Bolt / attack cantrips). Returns the pipeline body, or None if
    the pc_builder kind isn't a buildable spell-attack shape.

    The attack roll uses the MONSTER's spell attack bonus (the PC builder
    bakes the PC's mod+PB; here we bake the monster's). spell_slot_level /
    upcast are intentionally dropped — monster casts ride at-will / daily
    gates, not PC slots."""
    pb = (feature or {}).get("pc_builder") or {}
    kind = pb.get("kind")
    params = pb.get("params") or {}
    range_ft = int(params.get("range_ft", 120))
    dmg_type = params.get("damage_type", "force")

    if kind == "spell_attack":
        dice = params.get("damage_dice", "1d6")
        rays = max(1, int(params.get("ray_count", 1)))
    elif kind == "attack_cantrip":
        # Monster cantrips deal a fixed amount; the PC builder scales dice
        # by caster level, which a monster lacks — v1 uses a single die.
        dice = f"1d{int(params.get('die', 8))}"
        rays = 1
    else:
        return None   # not a spell-attack shape we can build

    pipeline: list[dict] = []
    for _ in range(rays):
        pipeline.append({"primitive": "attack_roll",
                          "params": {"kind": "ranged", "bonus": attack_bonus,
                                      "range_ft": range_ft}})
        pipeline.append({"primitive": "damage",
                          "params": {"dice": dice, "modifier": 0,
                                      "type": dmg_type},
                          "when": {"event": "damage_roll",
                                    "condition": "combat.attack_state == hit"}})
    return {"type": "weapon_attack", "range_ft": range_ft, "pipeline": pipeline}


def _expand_action(monster_action: dict, feature: dict,
                     attack_bonus: int) -> dict:
    """Build a full action from a `casts` reference + the spell feature.

    A feature with an `action_template` (save / AoE / buff spells) is
    copied; a spell-ATTACK marker (`pc_builder`, no action_template) is
    built via _build_from_pc_builder. A feature with NEITHER raises — a
    `casts` to an unexpandable feature is an authoring error, and failing
    fast beats silently emitting a non-runnable {id, name, casts} action
    (the bug batch M8 hit)."""
    template = (feature or {}).get("action_template")
    expanded: dict = {}
    if template:
        for key in _COPIED_FIELDS:
            if key in template:
                expanded[key] = template[key]
    else:
        built = _build_from_pc_builder(monster_action, feature, attack_bonus)
        if built is None:
            raise ValueError(
                f"casts: {monster_action.get('casts')!r} references a "
                f"feature with no action_template and no buildable "
                f"pc_builder spell-attack — cannot expand it into a "
                f"monster spell action."
            )
        expanded.update(built)
    # The monster action's own identity + gate win.
    expanded["id"] = monster_action.get("id")
    expanded["name"] = (monster_action.get("name")
                          or (template or {}).get("name"))
    # Carry the monster action's gate + option metadata (e.g. `cost` for a
    # legendary-action option, which legendary_actions.option_cost reads).
    for gate in ("recharge", "feature_use", "slot", "cost"):
        if gate in monster_action:
            expanded[gate] = monster_action[gate]
    # Record provenance so the action is traceable as a cast spell.
    expanded["casts"] = monster_action.get("casts")
    return expanded


def expand_template(template: dict, registry) -> bool:
    """Expand any `casts` actions on one monster template in place.

    Stamps `spellcasting_ability` / `spell_save_dc` from the template's
    `spellcasting` block. Returns True if anything was expanded/stamped.
    """
    changed = False

    sc = template.get("spellcasting") or {}
    if sc.get("ability") and not template.get("spellcasting_ability"):
        template["spellcasting_ability"] = sc["ability"]
        changed = True
    if sc.get("save_dc") is not None and template.get("spell_save_dc") is None:
        template["spell_save_dc"] = int(sc["save_dc"])
        changed = True

    attack_bonus = spell_attack_bonus(template)

    def _expand_list(actions):
        nonlocal changed
        out = []
        for action in actions:
            if isinstance(action, dict) and action.get("casts"):
                feature = registry.get("feature", action["casts"])
                out.append(_expand_action(action, feature, attack_bonus))
                changed = True
            else:
                out.append(action)
        return out

    # Top-level actions + bonus actions.
    for key in ("actions", "bonus_actions"):
        lst = template.get(key)
        if isinstance(lst, list):
            template[key] = _expand_list(lst)

    # Legendary action options (e.g. a dragon's "uses Spellcasting to cast
    # …" options) — casts in option position now expand too.
    la = template.get("legendary_actions")
    if isinstance(la, dict) and isinstance(la.get("options"), list):
        la["options"] = _expand_list(la["options"])

    return changed


def expand_registry(registry) -> int:
    """Expand `casts` actions across every monster in the registry. Runs
    once after content load. Returns the number of templates touched.

    Raises KeyError (via registry.get) if a `casts` action references a
    feature id that isn't built — fail fast so a caster can't ship with a
    dangling spell reference.
    """
    touched = 0
    for template in registry.all("monster").values():
        if expand_template(template, registry):
            touched += 1
    return touched
