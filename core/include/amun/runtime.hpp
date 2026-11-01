#pragma once

#include "amun/ledger.hpp"
#include "amun/memory.hpp"
#include "amun/pack.hpp"
#include "amun/types.hpp"
#include "amun/vm.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace amun {

class Clock {
public:
    virtual ~Clock() = default;
    virtual Milliseconds monotonicMs() const noexcept = 0;
    virtual std::uint64_t wallClockUnixMs() const noexcept = 0;
};

class ManualClock final : public Clock {
public:
    Milliseconds monotonicMs() const noexcept override { return monotonic_; }
    std::uint64_t wallClockUnixMs() const noexcept override { return wall_; }
    void setMonotonic(Milliseconds value) noexcept { monotonic_ = value; }
    void setWallClock(std::uint64_t value) noexcept { wall_ = value; }
    void advance(Milliseconds delta) noexcept { monotonic_ += delta; wall_ += delta; }

private:
    Milliseconds monotonic_{0};
    std::uint64_t wall_{0};
};

struct UnlockNotification {
    std::string achievementId;
    std::string title;
    std::string description;
    std::uint16_t points{0};
    bool secret{false};
    std::uint64_t wallClockUnixMs{0};
};

class EventSink {
public:
    virtual ~EventSink() = default;
    virtual void onUnlock(const UnlockNotification &notification) noexcept = 0;
    virtual void onProgress(const std::string &achievementId, std::uint32_t current,
                            std::uint32_t target) noexcept = 0;
    virtual void onWarning(const std::string &subsystem, const std::string &message) noexcept = 0;
};

class NullEventSink final : public EventSink {
public:
    void onUnlock(const UnlockNotification &) noexcept override {}
    void onProgress(const std::string &, std::uint32_t, std::uint32_t) noexcept override {}
    void onWarning(const std::string &, const std::string &) noexcept override {}
};

struct RuntimeConfig {
    PerformanceMode performanceMode{PerformanceMode::Balanced};
    IntegrityMode integrityMode{IntegrityMode::LiveUnverified};
    CheatStatus cheatStatus{CheatStatus::Unknown};
    std::uint32_t fastIntervalMs{17};
    std::uint32_t normalIntervalMs{100};
    std::uint32_t slowIntervalMs{1000};
    std::uint32_t progressWriteIntervalMs{2000};
    std::uint32_t maxConsecutiveReadFailures{8};
    // Cheap resolvers only; pointer depth is independently bounded by RuntimeLimits.
    std::uint32_t maxSymbolResolutionsPerTick{8};
    std::uint32_t maxInstructionsPerTick{100000};
    std::uint32_t maxTickMicroseconds{4000};
};

enum class RuntimeStatus : std::uint8_t {
    Idle = 0,
    Ready,
    Running,
    ExactBuildRequired,
    UnsupportedGame,
    SymbolResolutionFailed,
    LedgerFailure,
    PackInvalid,
    ProfileDisabled,
    Ended,
};

struct AchievementRuntimeState {
    VmState vm;
    bool unlocked{false};
    bool disabled{false};
    std::uint32_t progress{0};
    std::uint32_t persistedProgress{0};
    Milliseconds lastProgressWrite{0};
    std::string disableReason;
};

class Runtime {
public:
    explicit Runtime(RuntimeConfig config = {});

    bool loadPack(AchievementPack pack, std::string *error = nullptr);
    RuntimeStatus startSession(const GameIdentity &identity, MemoryReader &memory,
                               Ledger &ledger, Clock &clock, EventSink &events);
    TickMetrics tick();
    void endSession();

    RuntimeStatus status() const noexcept { return status_; }
    BuildMatch buildMatch() const noexcept { return buildMatch_; }
    const AchievementPack &pack() const noexcept { return pack_; }
    const std::vector<SymbolSnapshot> &symbolSnapshots() const noexcept { return snapshots_; }
    const std::vector<AchievementRuntimeState> &achievementStates() const noexcept { return achievementStates_; }
    const std::string &sessionId() const noexcept { return sessionId_; }
    std::size_t estimatedMemoryBytes() const noexcept;
    RuntimeSummary summary() const noexcept;

private:
    struct ResolvedSymbol {
        Address address{0};
        Milliseconds lastRead{0};
        std::uint32_t consecutiveFailures{0};
        std::uint16_t derivedStack{0};
        std::uint32_t derivedInstructions{0};
        bool resolved{false};
        bool attempted{false};
        bool sampled{false};
        bool disabled{false};
    };

    bool resolveSymbols();
    bool resolveSymbol(std::size_t index, TickMetrics *metrics = nullptr);
    void retryUnresolvedSymbols(TickMetrics &metrics, Milliseconds now);
    bool sampleSymbol(std::size_t index, TickMetrics &metrics, Milliseconds now);
    bool pollDue(const SymbolDefinition &symbol, const ResolvedSymbol &resolved,
                 Milliseconds now) const noexcept;
    bool prerequisitesMet(const AchievementDefinition &achievement) const noexcept;
    LedgerStatus appendEvent(LedgerEventType type, const std::string &achievementId,
                             std::uint32_t progress, const std::string &detail = {});
    std::string makeEventId(LedgerEventType type, const std::string &achievementId,
                            Milliseconds now) const;

    RuntimeConfig config_;
    RuntimeStatus status_{RuntimeStatus::Idle};
    BuildMatch buildMatch_{BuildMatch::UnsupportedBuild};
    AchievementPack pack_;
    GameIdentity identity_;
    std::size_t buildIndex_{0};
    std::string sessionId_;
    std::vector<ResolvedSymbol> resolved_;
    std::size_t nextResolutionIndex_{0};
    std::vector<SymbolSnapshot> snapshots_;
    std::vector<AchievementRuntimeState> achievementStates_;
    bool ledgerWritable_{false};
    MemoryReader *memory_{nullptr};
    Ledger *ledger_{nullptr};
    Clock *clock_{nullptr};
    EventSink *events_{nullptr};
};

} // namespace amun
