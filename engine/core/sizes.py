"""Creature sizes (PR #65).

5e 2024 PHB defines six creature sizes. v1 carries the size as a
runtime field on `Actor.size` (loaded from monster template's
top-level `size:` or PC schema's eventual race wiring); a few
mechanics gate on size:

  - **Push** (Weapon Mastery, PR #58) — only affects Large or
    smaller creatures
  - **Grapple** (deferred) — gates on size relative to attacker
  - **Carrying capacity** (deferred) — scales by size
  - **Squeezing through tight spaces** (deferred) — Small or
    smaller can fit through Tiny spaces

KNOWN_SIZES preserves the canonical 5e ordering (smallest →
largest) so range comparisons via `index` are well-defined.

Comparisons via `size_at_or_below(a, b)` answer "is a no larger
than b" — used by Push to filter affected targets.
"""
from __future__ import annotations


# Canonical 5e sizes, smallest → largest. Lowercase to match the
# convention monster templates already use (`size: small`).
SIZE_TINY = "tiny"
SIZE_SMALL = "small"
SIZE_MEDIUM = "medium"
SIZE_LARGE = "large"
SIZE_HUGE = "huge"
SIZE_GARGANTUAN = "gargantuan"

KNOWN_SIZES: tuple[str, ...] = (
    SIZE_TINY, SIZE_SMALL, SIZE_MEDIUM,
    SIZE_LARGE, SIZE_HUGE, SIZE_GARGANTUAN,
)
_SIZE_INDEX = {s: i for i, s in enumerate(KNOWN_SIZES)}


# Sizes that Push (Weapon Mastery) can affect — RAW: "Large or
# smaller." Huge + Gargantuan immune.
PUSH_SIZES: frozenset[str] = frozenset({
    SIZE_TINY, SIZE_SMALL, SIZE_MEDIUM, SIZE_LARGE,
})


def normalize_size(value) -> str:
    """Return lowercase canonical size string. Treats None / empty as
    'medium' (the engine default for actors with no explicit size).
    Raises ValueError on unknown size names.
    """
    if value is None or value == "":
        return SIZE_MEDIUM
    n = str(value).strip().lower()
    if n not in _SIZE_INDEX:
        raise ValueError(
            f"Unknown creature size {value!r}. Known: {list(KNOWN_SIZES)}."
        )
    return n


def size_at_or_below(actor_size, threshold) -> bool:
    """True if `actor_size` is no larger than `threshold`.

    Both inputs are normalized first. Used by Push to gate on
    "Large or smaller" — `size_at_or_below(target.size, "large")`.
    """
    a = normalize_size(actor_size)
    t = normalize_size(threshold)
    return _SIZE_INDEX[a] <= _SIZE_INDEX[t]
