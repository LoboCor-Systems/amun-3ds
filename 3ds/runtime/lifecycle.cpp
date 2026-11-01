#include "amun/3ds/lifecycle.hpp"

namespace amun::threeds {

namespace {

constexpr std::uint32_t kSleepBit = 1U << 0U;
constexpr std::uint32_t kHomeBit = 1U << 1U;
constexpr std::uint32_t kSwapBit = 1U << 2U;

} // namespace

std::uint32_t LifecycleCoordinator::suspensionBit(LifecycleEvent event) noexcept {
    switch (event) {
    case LifecycleEvent::SleepEnter:
    case LifecycleEvent::SleepExit:
        return kSleepBit;
    case LifecycleEvent::HomeEnter:
    case LifecycleEvent::HomeExit:
        return kHomeBit;
    case LifecycleEvent::SwapEnter:
    case LifecycleEvent::SwapExit:
        return kSwapBit;
    case LifecycleEvent::Exit:
        return 0U;
    }
    return 0U;
}

void LifecycleCoordinator::flush() noexcept {
    if (hooks_.flush != nullptr && !hooks_.flush(hooks_.context)) {
        flushFailures_.fetch_add(1U, std::memory_order_relaxed);
    }
}

void LifecycleCoordinator::enterSuspension(std::uint32_t bit) noexcept {
    const std::uint32_t previous = suspensionMask_.fetch_or(bit, std::memory_order_acq_rel);
    if (previous == 0U && hooks_.pause != nullptr) hooks_.pause(hooks_.context);
    flush();
}

void LifecycleCoordinator::leaveSuspension(std::uint32_t bit) noexcept {
    const std::uint32_t previous = suspensionMask_.fetch_and(~bit, std::memory_order_acq_rel);
    const std::uint32_t remaining = previous & ~bit;
    if (previous != 0U && remaining == 0U && !isStopping() && hooks_.resume != nullptr) {
        hooks_.resume(hooks_.context);
    }
}

void LifecycleCoordinator::handle(LifecycleEvent event) noexcept {
    switch (event) {
    case LifecycleEvent::SleepEnter:
    case LifecycleEvent::HomeEnter:
    case LifecycleEvent::SwapEnter:
        enterSuspension(suspensionBit(event));
        break;
    case LifecycleEvent::SleepExit:
    case LifecycleEvent::HomeExit:
    case LifecycleEvent::SwapExit:
        leaveSuspension(suspensionBit(event));
        break;
    case LifecycleEvent::Exit:
        suspensionMask_.store(kSleepBit | kHomeBit | kSwapBit, std::memory_order_release);
        if (!stopping_.exchange(true, std::memory_order_acq_rel) && hooks_.stop != nullptr) {
            hooks_.stop(hooks_.context);
        }
        flush();
        break;
    }
}

bool LifecycleCoordinator::isPaused() const noexcept {
    return isStopping() || suspensionMask_.load(std::memory_order_acquire) != 0U;
}

} // namespace amun::threeds
