#include "amun/3ds/clock.hpp"

#include <3ds.h>

namespace amun::threeds {

Milliseconds ThreeDSClock::monotonicMs() const noexcept {
    const std::uint64_t ticks = svcGetSystemTick();
    const std::uint64_t wholeSeconds = ticks / SYSCLOCK_ARM11;
    const std::uint64_t remainder = ticks % SYSCLOCK_ARM11;
    return wholeSeconds * 1000U + (remainder * 1000U) / SYSCLOCK_ARM11;
}

std::uint64_t ThreeDSClock::wallClockUnixMs() const noexcept {
    // libctru's osGetTime() epoch is 1900-01-01; ledger timestamps use Unix time.
    constexpr std::uint64_t kUnixEpochOffsetMs = 2'208'988'800'000ULL;
    const std::uint64_t consoleMs = osGetTime();
    return consoleMs >= kUnixEpochOffsetMs ? consoleMs - kUnixEpochOffsetMs : 0U;
}

} // namespace amun::threeds
