#include "test.hpp"

#include "amun/metal_tier.hpp"

#include <string>

using namespace amun;

TEST("metal tiers follow the documented point bands") {
    EXPECT(metalTierFor(0U) == MetalTier::None);
    const struct { std::uint32_t low; std::uint32_t high; MetalTier tier; } bands[] = {
        {1U, 4U, MetalTier::Copper},     {5U, 9U, MetalTier::Bronze},
        {10U, 14U, MetalTier::Silver},   {15U, 24U, MetalTier::Electrum},
        {25U, 49U, MetalTier::Gold},     {50U, 99U, MetalTier::Platinum},
        {100U, 10000U, MetalTier::Rhodium},
    };
    for (const auto &band : bands) {
        EXPECT(metalTierFor(band.low) == band.tier);
        EXPECT(metalTierFor(band.high) == band.tier);
        EXPECT(metalTierFor(band.low - 1U) != band.tier);
    }
    EXPECT(metalTierFor(65535U) == MetalTier::Rhodium);
}

TEST("metal tier names and bands are stable") {
    EXPECT_EQ(std::string(metalTierName(MetalTier::None)), std::string());
    EXPECT_EQ(std::string(metalTierName(MetalTier::Silver)), std::string("Silver"));
    EXPECT_EQ(std::string(metalTierName(MetalTier::Rhodium)), std::string("Rhodium"));
    EXPECT(metalTierBand(MetalTier::None) == nullptr);
    for (std::size_t i = 0; i < kMetalTierBands.size(); ++i) {
        EXPECT_EQ(static_cast<std::size_t>(kMetalTierBands[i].tier), i + 1U);
        if (i != 0U) EXPECT(kMetalTierBands[i].minPoints > kMetalTierBands[i - 1U].minPoints);
    }
}

TEST("metal tier tally counts unlocked and total per tier") {
    MetalTierTally tally;
    tally.add(0U, true);
    tally.add(10U, true);
    tally.add(12U, false);
    tally.add(25U, false);
    EXPECT_EQ(tally.total[static_cast<std::size_t>(MetalTier::None)], 1U);
    EXPECT_EQ(tally.total[static_cast<std::size_t>(MetalTier::Silver)], 2U);
    EXPECT_EQ(tally.unlocked[static_cast<std::size_t>(MetalTier::Silver)], 1U);
    EXPECT_EQ(tally.unlocked[static_cast<std::size_t>(MetalTier::Gold)], 0U);
    EXPECT_EQ(tally.total[static_cast<std::size_t>(MetalTier::Gold)], 1U);
}
