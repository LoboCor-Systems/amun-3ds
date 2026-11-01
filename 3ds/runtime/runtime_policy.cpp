#include "amun/3ds/runtime_policy.hpp"

namespace amun::threeds {

RuntimeLimits old2dsPackLimits() noexcept {
    RuntimeLimits limits;
    limits.maxPackBytes = 512U * 1024U;
    limits.maxBuilds = 16U;
    limits.maxAchievements = 300U;
    limits.maxSymbols = 512U;
    limits.maxStrings = 4096U;
    limits.maxStringBytes = 512U;
    limits.maxReferencedStringBytes = 256U * 1024U;
    limits.maxPrerequisitesPerAchievement = 32U; // MK7 ghost milestones depend on all 32 per-track ledger entries
    limits.maxPointerDepth = 16U; // raised for MK7 race.* chains (depth 10); matches types.hpp default
    limits.maxSignatureBytes = 128U;
    limits.maxPatternScanBytes = 2U * 1024U * 1024U;
    limits.maxTotalPatternScanBytes = 8U * 1024U * 1024U;
    limits.maxAssets = 64U;
    limits.maxAssetStoredBytes = 64U * 1024U;
    limits.maxAssetDecodedBytes = 64U * 1024U;
    limits.maxTotalAssetDecodedBytes = 256U * 1024U;
    limits.maxBytecodeBytes = 128U * 1024U;
    limits.maxVmStack = 64U;
    limits.maxVmStateSlots = 128U;
    limits.maxTotalVmStateSlots = 4096U;
    limits.maxInstructionsPerAchievement = 1024U;
    limits.maxConditionNesting = 32U;
    return limits;
}

RuntimeConfig old2dsRuntimeConfig() noexcept {
    RuntimeConfig config;
    config.performanceMode = PerformanceMode::Balanced;
    config.integrityMode = IntegrityMode::LiveUnverified;
    config.cheatStatus = CheatStatus::Unknown;
    config.maxTickMicroseconds = 3500U;
    // MK7's 26 race.* symbols are "normal" class and walk pointer chains up to 10 hops deep;
    // at the default 100 ms they dominate the ~2,000 reads/s a full set costs. 250 ms keeps race
    // events responsive while cutting those reads by more than half (measured on the host).
    config.normalIntervalMs = 250U;
    return config;
}

Milliseconds nextTickDelayMs(std::uint64_t lastTickMicroseconds) noexcept {
    // elapsed * divisor, in whole milliseconds (rounded up so a slow tick never rounds to zero).
    const std::uint64_t scaled = (lastTickMicroseconds * kTickDutyDivisor + 999U) / 1000U;
    const std::uint64_t delay = scaled < kMinTickIntervalMs ? kMinTickIntervalMs : scaled;
    return static_cast<Milliseconds>(delay > kMaxTickIntervalMs ? kMaxTickIntervalMs : delay);
}

} // namespace amun::threeds
