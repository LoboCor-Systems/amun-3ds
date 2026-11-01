#pragma once

#include "amun/pack.hpp"

#include <cstddef>
#include <cstdint>
#include <string>

namespace amun::threeds {

struct PackLoadResult {
    bool ok{false};
    AchievementPack pack;
    std::size_t bytes{0};
    std::string detail;
};

PackLoadResult loadPackFromSd(const char *absolutePath,
                              RuntimeLimits limits = {}) noexcept;

} // namespace amun::threeds
