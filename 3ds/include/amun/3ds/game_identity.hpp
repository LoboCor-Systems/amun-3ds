#pragma once

#include "amun/types.hpp"

#include <cstdint>
#include <string>

namespace amun::threeds {

class ThreeDSMemoryReader;

struct IdentityResult {
    bool ok{false};
    GameIdentity identity;
    std::string detail;
};

// Fingerprints the complete live .text mapping once, subject to a hard size cap.
// The v1 string intentionally names this as a live-text fingerprint because the
// pinned CTRPF bootstrap has already installed its framework hooks at this point.
IdentityResult buildGameIdentity(std::uint64_t titleId, ThreeDSMemoryReader &memory) noexcept;

} // namespace amun::threeds
