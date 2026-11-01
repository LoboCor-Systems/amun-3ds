#include "trophy_overlay.hpp"

#include "amun/3ds/trophy_art.hpp"

#include <CTRPluginFramework.hpp>
#include <3ds.h>

#include <atomic>
#include <cstdint>

namespace amun::threeds {

namespace {

using CTRPluginFramework::Color;
using CTRPluginFramework::Screen;

constexpr std::uint32_t kScale = 2U;
constexpr std::uint32_t kBadgePixels = static_cast<std::uint32_t>(kTrophyArtSize) * kScale;
constexpr std::uint32_t kTopScreenWidth = 400U;
constexpr std::uint32_t kMargin = 6U;
constexpr std::uint32_t kLeft = kTopScreenWidth - kBadgePixels - kMargin;
constexpr std::uint32_t kTop = kMargin;
// Matches the five seconds CTRPF keeps an OSD::Notify toast on screen.
constexpr std::uint32_t kShowTicks = static_cast<std::uint32_t>(SYSCLOCK_ARM11) * 5U;

// Only the low 32 bits of the system tick are kept: the signed difference stays correct for
// intervals far longer than the badge lifetime. Expiry is published before the tier so the
// draw callback never pairs a new tier with an old expiry; the callback never writes either.
std::atomic<std::uint32_t> g_expiryTick{0U};
std::atomic<std::uint8_t> g_tier{static_cast<std::uint8_t>(MetalTier::None)};

bool drawTrophyOverlay(const Screen &screen) {
    if (!screen.IsTop) return false;
    const auto tier = g_tier.load(std::memory_order_acquire);
    if (tier == static_cast<std::uint8_t>(MetalTier::None) ||
        tier > static_cast<std::uint8_t>(MetalTier::Rhodium)) return false;
    const auto now = static_cast<std::uint32_t>(svcGetSystemTick());
    if (static_cast<std::int32_t>(g_expiryTick.load(std::memory_order_acquire) - now) <= 0)
        return false;

    const std::uint32_t *art = kTrophyArt[tier - 1U];
    constexpr std::uint32_t size = static_cast<std::uint32_t>(kTrophyArtSize);
    for (std::uint32_t y = 0; y < size; ++y) {
        // Merge horizontal runs of one colour into a single rectangle to bound draw calls.
        std::uint32_t x = 0;
        while (x < size) {
            const std::uint32_t word = art[y * size + x];
            if ((word >> 24U) == 0U) { ++x; continue; }
            std::uint32_t end = x + 1U;
            while (end < size && art[y * size + end] == word) ++end;
            screen.DrawRect(kLeft + x * kScale, kTop + y * kScale, (end - x) * kScale, kScale,
                            Color(static_cast<u8>((word >> 16U) & 0xFFU),
                                  static_cast<u8>((word >> 8U) & 0xFFU),
                                  static_cast<u8>(word & 0xFFU)));
            x = end;
        }
    }
    return false;
}

} // namespace

void installTrophyOverlay() noexcept {
    CTRPluginFramework::OSD::Run(drawTrophyOverlay);
}

void showTrophyOverlay(MetalTier tier) noexcept {
    if (tier == MetalTier::None || static_cast<std::uint8_t>(tier) > static_cast<std::uint8_t>(MetalTier::Rhodium))
        return;
    g_expiryTick.store(static_cast<std::uint32_t>(svcGetSystemTick()) + kShowTicks,
                       std::memory_order_release);
    g_tier.store(static_cast<std::uint8_t>(tier), std::memory_order_release);
}

} // namespace amun::threeds
