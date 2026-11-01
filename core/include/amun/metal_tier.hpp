#pragma once

// AMUN platform metal tiers: achievement points -> display metal.
//
// Presentation only: nothing is stored in packs, profiles, or the ledger. The
// canonical table (bands + palette) is compiler/metal_tiers.py;
// tests/python/test_metal_tiers.py checks that this copy matches it.
// To retune, edit both tables (cut-offs in kMetalTierBands, colours in the
// MetalTierColors rows) and run the tests. See docs/metal-tiers.md.

#include <array>
#include <cstddef>
#include <cstdint>

namespace amun {

enum class MetalTier : std::uint8_t {
    None = 0,
    Copper,
    Bronze,
    Silver,
    Electrum,
    Gold,
    Platinum,
    Rhodium,
};

inline constexpr std::size_t kMetalTierCount = 8U; // including None

struct MetalRgb {
    std::uint8_t r{0};
    std::uint8_t g{0};
    std::uint8_t b{0};
};

struct MetalTierBand {
    MetalTier tier;
    std::uint16_t minPoints;  // inclusive lower bound; upper bound = next band - 1
    const char *name;
    MetalRgb highlight;       // specular / toast text
    MetalRgb mid;             // body colour / swatch
    MetalRgb shadow;
    MetalRgb ink;             // toast background
};

// clang-format off
inline constexpr std::array<MetalTierBand, 7> kMetalTierBands{{
    {MetalTier::Copper,     1U, "Copper",   {255, 186, 150}, {214, 106,  60}, {118,  44,  20}, { 72,  24,  10}},
    {MetalTier::Bronze,     5U, "Bronze",   {236, 196, 128}, {168, 118,  56}, { 92,  60,  24}, { 56,  36,  14}},
    {MetalTier::Silver,    10U, "Silver",   {246, 246, 246}, {178, 180, 184}, { 90,  92,  96}, { 48,  49,  52}},
    {MetalTier::Electrum,  15U, "Electrum", {248, 246, 184}, {196, 192, 104}, {110, 108,  40}, { 60,  60,  20}},
    {MetalTier::Gold,      25U, "Gold",     {255, 234, 136}, {240, 180,  40}, {156,  96,   6}, { 84,  52,   0}},
    {MetalTier::Platinum,  50U, "Platinum", {236, 248, 255}, {150, 192, 236}, { 44,  84, 140}, { 18,  40,  76}},
    {MetalTier::Rhodium,  100U, "Rhodium",  {255, 255, 255}, {222, 212, 248}, { 66,  40, 122}, { 34,  18,  68}},
}};
// clang-format on

constexpr MetalTier metalTierFor(std::uint32_t points) noexcept {
    MetalTier tier = MetalTier::None;
    for (const MetalTierBand &band : kMetalTierBands)
        if (points >= band.minPoints) tier = band.tier;
    return tier;
}

constexpr const MetalTierBand *metalTierBand(MetalTier tier) noexcept {
    const auto index = static_cast<std::size_t>(tier);
    return index == 0U || index > kMetalTierBands.size() ? nullptr : &kMetalTierBands[index - 1U];
}

// "" for MetalTier::None, so callers can test name[0].
constexpr const char *metalTierName(MetalTier tier) noexcept {
    const MetalTierBand *band = metalTierBand(tier);
    return band == nullptr ? "" : band->name;
}

struct MetalTierTally {
    std::array<std::uint16_t, kMetalTierCount> unlocked{};
    std::array<std::uint16_t, kMetalTierCount> total{};

    void add(std::uint32_t points, bool isUnlocked) noexcept {
        const auto index = static_cast<std::size_t>(metalTierFor(points));
        if (total[index] != UINT16_MAX) ++total[index];
        if (isUnlocked && unlocked[index] != UINT16_MAX) ++unlocked[index];
    }
};

static_assert(metalTierFor(0U) == MetalTier::None);
static_assert(metalTierFor(4U) == MetalTier::Copper);
static_assert(metalTierFor(5U) == MetalTier::Bronze);
static_assert(metalTierFor(10U) == MetalTier::Silver);
static_assert(metalTierFor(25U) == MetalTier::Gold);
static_assert(metalTierFor(10000U) == MetalTier::Rhodium);

} // namespace amun
