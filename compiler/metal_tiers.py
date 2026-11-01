"""AMUN platform metal tiers: achievement ``points`` -> display metal.

This is presentation chrome shared by every game. Nothing here is stored in a
pack, profile, or ledger; the tier is always derived from ``points`` when an
achievement is shown. See ``docs/metal-tiers.md``.

Retuning hooks
--------------
* ``BANDS``   - lower bound (inclusive) of each tier. Change cut-offs here only.
* ``PALETTE`` - highlight / mid / shadow / ink RGB per tier. The trophy art
  (``scripts/make_metal_tiers.py``), Studio swatches, and the plugin toast colours
  all read this table (the C++ copy in ``core/include/amun/metal_tier.hpp`` is
  checked against it by ``tests/python/test_metal_tiers.py``; Hub keeps a
  dependency-free copy of ``BANDS`` in ``hub/metal_tiers.py``, also checked).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable, Mapping

MAX_POINTS = 10000

RGB = tuple[int, int, int]


class MetalTier(IntEnum):
    NONE = 0
    COPPER = 1
    BRONZE = 2
    SILVER = 3
    ELECTRUM = 4
    GOLD = 5
    PLATINUM = 6
    RHODIUM = 7

    @property
    def label(self) -> str:
        return "" if self is MetalTier.NONE else self.name.capitalize()

    @property
    def slug(self) -> str:
        return "" if self is MetalTier.NONE else self.name.lower()


# (tier, first point value of the band). Bands are contiguous up to MAX_POINTS.
BANDS: tuple[tuple[MetalTier, int], ...] = (
    (MetalTier.COPPER, 1),
    (MetalTier.BRONZE, 5),
    (MetalTier.SILVER, 10),
    (MetalTier.ELECTRUM, 15),
    (MetalTier.GOLD, 25),
    (MetalTier.PLATINUM, 50),
    (MetalTier.RHODIUM, 100),
)


@dataclass(frozen=True)
class MetalColors:
    highlight: RGB  # specular / toast text
    mid: RGB        # body colour / UI swatch
    shadow: RGB     # dark side of the gradient
    ink: RGB        # deep tone for toast background (text = highlight)

    def hex(self, which: str = "mid") -> str:
        r, g, b = getattr(self, which)
        return f"#{r:02X}{g:02X}{b:02X}"


# Hue families are kept apart on purpose so neighbours never look alike at 16 px:
# copper = red-orange, bronze = olive-brown, silver = neutral grey,
# electrum = pale green-gold, gold = saturated yellow-gold,
# platinum = cool ice blue, rhodium = bright chrome with a violet depth.
PALETTE: Mapping[MetalTier, MetalColors] = {
    MetalTier.COPPER: MetalColors((255, 186, 150), (214, 106, 60), (118, 44, 20), (72, 24, 10)),
    MetalTier.BRONZE: MetalColors((236, 196, 128), (168, 118, 56), (92, 60, 24), (56, 36, 14)),
    MetalTier.SILVER: MetalColors((246, 246, 246), (178, 180, 184), (90, 92, 96), (48, 49, 52)),
    MetalTier.ELECTRUM: MetalColors((248, 246, 184), (196, 192, 104), (110, 108, 40), (60, 60, 20)),
    MetalTier.GOLD: MetalColors((255, 234, 136), (240, 180, 40), (156, 96, 6), (84, 52, 0)),
    MetalTier.PLATINUM: MetalColors((236, 248, 255), (150, 192, 236), (44, 84, 140), (18, 40, 76)),
    MetalTier.RHODIUM: MetalColors((255, 255, 255), (222, 212, 248), (66, 40, 122), (34, 18, 68)),
}


def metal_tier(points: object) -> MetalTier:
    """Return the tier for an achievement's points (non-ints / <=0 -> NONE)."""
    if isinstance(points, bool) or not isinstance(points, int) or points <= 0:
        return MetalTier.NONE
    tier = MetalTier.NONE
    for candidate, lower in BANDS:
        if points >= lower:
            tier = candidate
    return tier


def metal_label(points: object) -> str:
    return metal_tier(points).label


def points_label(points: object) -> str:
    """``"10 (Silver)"``, or just the number for unranked/odd values."""
    tier = metal_tier(points)
    return f"{points} ({tier.label})" if tier is not MetalTier.NONE else f"{points}"


def band_range(tier: MetalTier) -> tuple[int, int]:
    if tier is MetalTier.NONE:
        return (0, 0)
    for index, (candidate, lower) in enumerate(BANDS):
        if candidate is tier:
            upper = BANDS[index + 1][1] - 1 if index + 1 < len(BANDS) else MAX_POINTS
            return (lower, upper)
    raise ValueError(tier)


def tier_counts(points: Iterable[object]) -> dict[MetalTier, int]:
    counts = {tier: 0 for tier in MetalTier}
    for value in points:
        counts[metal_tier(value)] += 1
    return counts


def format_tier_counts(counts: Mapping[MetalTier, int]) -> str:
    """``"Bronze 6, Silver 20, Gold 4"`` - ranked tiers with a non-zero count."""
    return ", ".join(
        f"{tier.label} {counts[tier]}" for tier in MetalTier if tier is not MetalTier.NONE and counts.get(tier)
    )
