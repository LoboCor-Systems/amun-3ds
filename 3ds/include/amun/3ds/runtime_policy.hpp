#pragma once

#include "amun/runtime.hpp"
#include "amun/types.hpp"

namespace amun::threeds {

// Conservative defaults for the original Old3DS/2DS hardware class. Keep
// these limits in platform-neutral code so host tests can prevent accidental
// expansion of the console attack surface or memory budget.
RuntimeLimits old2dsPackLimits() noexcept;
RuntimeConfig old2dsRuntimeConfig() noexcept;

// Observer pacing. CTRPF calls the plugin callback every other game frame (~30 Hz), but a full
// Runtime::tick samples memory and evaluates every unlocked-pending achievement, which is far
// too much work to repeat that often on an original 2DS: a 95-entry pack made Mario Kart 7
// barely playable. Ticks therefore run at most every kMinTickIntervalMs, and the gap grows so
// the observer never uses more than ~1/kTickDutyDivisor of the time it just measured.
inline constexpr Milliseconds kMinTickIntervalMs = 100U;
inline constexpr std::uint64_t kTickDutyDivisor = 20U;
inline constexpr Milliseconds kMaxTickIntervalMs = 1000U;

// Delay before the next tick may run, given how long the last one took.
Milliseconds nextTickDelayMs(std::uint64_t lastTickMicroseconds) noexcept;

} // namespace amun::threeds
