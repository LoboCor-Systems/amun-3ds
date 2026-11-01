#pragma once

#include "amun/metal_tier.hpp"
#include "amun/runtime.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>

namespace amun::threeds {

class SdStatusLog;

class ThreeDSEventSink final : public EventSink {
public:
    explicit ThreeDSEventSink(SdStatusLog *statusLog) noexcept : statusLog_(statusLog) {}

    void onUnlock(const UnlockNotification &notification) noexcept override;
    void onProgress(const std::string &achievementId, std::uint32_t current,
                    std::uint32_t target) noexcept override;
    void onWarning(const std::string &subsystem, const std::string &message) noexcept override;

    void pump(Milliseconds now) noexcept;
    std::size_t queued() const noexcept { return count_; }
    std::uint32_t dropped() const noexcept { return dropped_; }

private:
    static constexpr std::size_t kQueueCapacity = 8U;
    static constexpr std::size_t kToastTextLimit = 160U;
    std::array<std::string, kQueueCapacity> queue_{};
    std::array<MetalTier, kQueueCapacity> tiers_{};
    std::size_t head_{0U};
    std::size_t tail_{0U};
    std::size_t count_{0U};
    std::uint32_t dropped_{0U};
    static constexpr std::uint32_t kPerformanceWarningStride = 100U;
    std::uint32_t performanceWarnings_{0U};
    Milliseconds lastToast_{0U};
    SdStatusLog *statusLog_{nullptr};
};

} // namespace amun::threeds
