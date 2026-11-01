#pragma once

#include "amun/metal_tier.hpp"

namespace amun::threeds {

// Unlock badge: draws the tier's trophy (docs/metal-tiers.md) in the top-right corner of the
// top screen for as long as the unlock toast is on screen. Presentation only; it reads no game
// memory and touches no ledger or pack data. Unranked (0-point) unlocks show no badge.

// Registers the per-frame draw callback with CTRPF's OSD. Call once, after the observer is
// running, so an inert (no-pack) plugin never draws anything.
void installTrophyOverlay() noexcept;

// Starts (or restarts) the badge for `tier`. MetalTier::None is ignored. Safe to call from the
// plugin thread while the OSD thread draws: the two words it publishes are independent atomics.
void showTrophyOverlay(MetalTier tier) noexcept;

} // namespace amun::threeds
