#pragma once

#include "amun/runtime.hpp"

namespace amun::threeds {

class ThreeDSClock final : public Clock {
public:
    Milliseconds monotonicMs() const noexcept override;
    std::uint64_t wallClockUnixMs() const noexcept override;
};

} // namespace amun::threeds
