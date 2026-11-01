#include "event_sink.hpp"

#include "sd_status_log.hpp"
#include "trophy_overlay.hpp"

#include <CTRPluginFramework.hpp>

#include <algorithm>
#include <cstdio>
#include <utility>

namespace amun::threeds {

namespace {

std::string boundedLine(const std::string &prefix, const std::string &value,
                        std::size_t maximum) {
    std::string line = prefix;
    const std::size_t available = line.size() < maximum ? maximum - line.size() : 0U;
    line.append(value, 0U, std::min(value.size(), available));
    return line;
}

} // namespace

void ThreeDSEventSink::onUnlock(const UnlockNotification &notification) noexcept {
    // Platform metal tier (docs/metal-tiers.md): derived from points, never stored.
    const MetalTier tier = metalTierFor(notification.points);
    const char *metal = metalTierName(tier);
    char prefix[80]{};
    if (metal[0] != '\0') {
        std::snprintf(prefix, sizeof(prefix), notification.secret
            ? "Secret achievement unlocked (+%u, %s): "
            : "Achievement unlocked (+%u, %s): ",
            static_cast<unsigned>(notification.points), metal);
    } else {
        std::snprintf(prefix, sizeof(prefix), notification.secret
            ? "Secret achievement unlocked (+%u): "
            : "Achievement unlocked (+%u): ", static_cast<unsigned>(notification.points));
    }
    std::string text = prefix;
    text += notification.secret ? "???" : notification.title;
    if (text.size() > kToastTextLimit) text.resize(kToastTextLimit);
    if (count_ == kQueueCapacity) {
        ++dropped_;
    } else {
        queue_[tail_] = std::move(text);
        tiers_[tail_] = tier;
        tail_ = (tail_ + 1U) % kQueueCapacity;
        ++count_;
    }
    if (statusLog_ != nullptr)
        statusLog_->appendLine(boundedLine("unlock: ", notification.achievementId, 224U).c_str());
}

void ThreeDSEventSink::onProgress(const std::string &, std::uint32_t, std::uint32_t) noexcept {
    // Progress is persisted by Runtime; it is intentionally not toasted every tick.
}

void ThreeDSEventSink::onWarning(const std::string &subsystem,
                                 const std::string &message) noexcept {
    if (statusLog_ == nullptr) return;
    // A slow tick warns on every tick, which once wrote thousands of SD log lines per session.
    // Keep the first occurrence, then one in every kPerformanceWarningStride, with a count.
    if (subsystem == "performance") {
        const std::uint32_t seen = performanceWarnings_++;
        if (seen % kPerformanceWarningStride != 0U) return;
        char suffix[48]{};
        std::snprintf(suffix, sizeof(suffix), " (occurrence %lu)", static_cast<unsigned long>(seen + 1U));
        statusLog_->appendLine(
            boundedLine("warning/performance: ", message, 224U - sizeof(suffix)).append(suffix).c_str());
        return;
    }
    statusLog_->appendLine(boundedLine("warning/" + subsystem + ": ", message, 224U).c_str());
}

void ThreeDSEventSink::pump(Milliseconds now) noexcept {
    constexpr Milliseconds kMinimumToastSpacingMs = 750U;
    if (count_ == 0U || (lastToast_ != 0U && now >= lastToast_ &&
                         now - lastToast_ < kMinimumToastSpacingMs)) return;
    // Tinted toast: tier highlight text on the tier's deep ink; unranked keeps CTRPF defaults.
    const MetalTierBand *band = metalTierBand(tiers_[head_]);
    const int queued = band == nullptr
        ? CTRPluginFramework::OSD::Notify(queue_[head_])
        : CTRPluginFramework::OSD::Notify(
              queue_[head_],
              CTRPluginFramework::Color(band->highlight.r, band->highlight.g, band->highlight.b),
              CTRPluginFramework::Color(band->ink.r, band->ink.g, band->ink.b));
    if (queued < 0) return; // CTRPF's own bounded queue is full; retain ours for retry.
    showTrophyOverlay(tiers_[head_]); // no-op for unranked (0-point) unlocks
    queue_[head_].clear();
    tiers_[head_] = MetalTier::None;
    head_ = (head_ + 1U) % kQueueCapacity;
    --count_;
    lastToast_ = now;
}

} // namespace amun::threeds
