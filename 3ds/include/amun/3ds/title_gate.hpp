#pragma once

#include "amun/3ds/paths.hpp"

#include <array>
#include <cstdint>

namespace amun::threeds {

class PackProbe {
public:
    virtual ~PackProbe() = default;
    virtual bool exists(const char *absolutePath) const noexcept = 0;
};

enum class TitleGateDecision : std::uint8_t {
    Observe = 0,
    InvalidTitle,
    UnsupportedTitleClass,
    PackMissing,
};

struct TitleGateResult {
    TitleGateDecision decision{TitleGateDecision::InvalidTitle};
    std::uint64_t titleId{0};
    std::array<char, kPlatformPathCapacity> packPath{};

    bool canObserve() const noexcept { return decision == TitleGateDecision::Observe; }
};

// AMUN v1 accepts only native CTR application/game titles (00040000 high word).
// It then gates on a pack path containing the complete 64-bit Title ID.
TitleGateResult evaluateTitleGate(std::uint64_t titleId, const PackProbe &probe) noexcept;
const char *titleGateDecisionName(TitleGateDecision decision) noexcept;

} // namespace amun::threeds
