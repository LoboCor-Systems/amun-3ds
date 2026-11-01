"""Dependency-free copy of the AMUN metal-tier bands for the standalone Hub.

Hub ships without the compiler package, so it keeps this tiny table. The
canonical table is ``compiler/metal_tiers.py``; ``tests/python/test_metal_tiers.py``
fails if the two drift apart. See ``docs/metal-tiers.md``.
"""

from __future__ import annotations

# (name, first point value of the band); 0 points = unranked.
BANDS: tuple[tuple[str, int], ...] = (
    ("Copper", 1),
    ("Bronze", 5),
    ("Silver", 10),
    ("Electrum", 15),
    ("Gold", 25),
    ("Platinum", 50),
    ("Rhodium", 100),
)


def metal_name(points: object) -> str | None:
    """Metal name for ``points``, or ``None`` when unranked or not an integer."""
    if isinstance(points, bool) or not isinstance(points, int) or points <= 0:
        return None
    name = None
    for candidate, lower in BANDS:
        if points >= lower:
            name = candidate
    return name
