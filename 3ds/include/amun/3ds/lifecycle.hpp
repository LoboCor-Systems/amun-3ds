#pragma once

#include <atomic>
#include <cstdint>

namespace amun::threeds {

enum class LifecycleEvent : std::uint8_t {
    Exit = 0,
    SleepEnter,
    SleepExit,
    HomeEnter,
    HomeExit,
    SwapEnter,
    SwapExit,
};

using LifecycleHook = void (*)(void *context) noexcept;
using FlushHook = bool (*)(void *context) noexcept;

struct LifecycleHooks {
    void *context{nullptr};
    LifecycleHook pause{nullptr};
    LifecycleHook resume{nullptr};
    LifecycleHook stop{nullptr};
    FlushHook flush{nullptr};
};

class LifecycleCoordinator {
public:
    explicit LifecycleCoordinator(LifecycleHooks hooks = {}) noexcept : hooks_(hooks) {}

    void handle(LifecycleEvent event) noexcept;
    bool isPaused() const noexcept;
    bool isStopping() const noexcept { return stopping_.load(std::memory_order_acquire); }
    std::uint32_t flushFailures() const noexcept {
        return flushFailures_.load(std::memory_order_relaxed);
    }

private:
    static std::uint32_t suspensionBit(LifecycleEvent event) noexcept;
    void enterSuspension(std::uint32_t bit) noexcept;
    void leaveSuspension(std::uint32_t bit) noexcept;
    void flush() noexcept;

    LifecycleHooks hooks_;
    std::atomic<std::uint32_t> suspensionMask_{0U};
    std::atomic<std::uint32_t> flushFailures_{0U};
    std::atomic<bool> stopping_{false};
};

} // namespace amun::threeds
