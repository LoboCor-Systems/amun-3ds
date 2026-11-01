#include "amun/3ds/title_gate.hpp"

#include <cstdio>

namespace amun::threeds {

namespace {

constexpr std::uint32_t kNativeApplicationTitleHigh = 0x00040000U;

} // namespace

TitleGateResult evaluateTitleGate(std::uint64_t titleId, const PackProbe &probe) noexcept {
    TitleGateResult result;
    result.titleId = titleId;
    if (titleId == 0U) return result;

    const std::uint32_t high = static_cast<std::uint32_t>(titleId >> 32U);
    if (high != kNativeApplicationTitleHigh) {
        result.decision = TitleGateDecision::UnsupportedTitleClass;
        return result;
    }

    const int written = std::snprintf(result.packPath.data(), result.packPath.size(),
                                      "/amun/packs/%016llX/%s",
                                      static_cast<unsigned long long>(titleId), kPackFileName);
    if (written < 0 || static_cast<std::size_t>(written) >= result.packPath.size()) {
        result.decision = TitleGateDecision::InvalidTitle;
        result.packPath.fill('\0');
        return result;
    }

    result.decision = probe.exists(result.packPath.data())
        ? TitleGateDecision::Observe
        : TitleGateDecision::PackMissing;
    return result;
}

const char *titleGateDecisionName(TitleGateDecision decision) noexcept {
    switch (decision) {
    case TitleGateDecision::Observe:
        return "observe";
    case TitleGateDecision::InvalidTitle:
        return "invalid-title";
    case TitleGateDecision::UnsupportedTitleClass:
        return "unsupported-title-class";
    case TitleGateDecision::PackMissing:
        return "pack-missing";
    }
    return "unknown";
}

} // namespace amun::threeds
