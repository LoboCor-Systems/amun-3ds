#include "amun/3ds/lifecycle.hpp"
#include "amun/3ds/ledger_snapshot.hpp"
#include "amun/3ds/menu_policy.hpp"
#include "amun/3ds/memory_reader.hpp"
#include "amun/3ds/network_policy.hpp"
#include "amun/3ds/runtime_policy.hpp"
#include "amun/3ds/title_gate.hpp"

#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

namespace {

using amun::Address;
using amun::ReadStatus;
using amun::threeds::BoundedMemoryReader;
using amun::threeds::LifecycleCoordinator;
using amun::threeds::LifecycleEvent;
using amun::threeds::LifecycleHooks;
using amun::threeds::LedgerSnapshotState;
using amun::threeds::MemoryRegion;
using amun::threeds::PackProbe;
using amun::threeds::TitleGateDecision;

int failures = 0;

void expect(bool condition, const char *message) {
    if (condition) return;
    ++failures;
    std::cerr << "FAIL: " << message << '\n';
}

class FakeReader final : public BoundedMemoryReader {
public:
    struct Mapping {
        Address base;
        std::vector<std::uint8_t> bytes;
        bool readable;
    };

    void map(Address base, std::initializer_list<std::uint8_t> bytes, bool readable = true) {
        mappings_.push_back({base, bytes, readable});
    }

    void exclude(Address base, std::uint32_t size) {
        exclusions_.push_back({base, size, false});
    }

    std::size_t copies() const noexcept { return copies_; }
    std::size_t largestCopy() const noexcept { return largestCopy_; }

protected:
    bool queryRegion(Address address, MemoryRegion &region) const noexcept override {
        for (const Mapping &mapping : mappings_) {
            const std::uint64_t end = static_cast<std::uint64_t>(mapping.base) + mapping.bytes.size();
            if (address >= mapping.base && address < end) {
                region = {mapping.base, static_cast<std::uint32_t>(mapping.bytes.size()),
                          mapping.readable};
                for (const MemoryRegion &excluded : exclusions_) {
                    if (!amun::threeds::excludeMemoryRange(address, excluded.base,
                                                          excluded.size, region))
                        return false;
                }
                return true;
            }
        }
        return false;
    }

    bool copyOut(Address source, void *destination, std::size_t size) const noexcept override {
        for (const Mapping &mapping : mappings_) {
            const std::uint64_t end = static_cast<std::uint64_t>(mapping.base) + mapping.bytes.size();
            const std::uint64_t copyEnd = static_cast<std::uint64_t>(source) + size;
            if (source >= mapping.base && copyEnd <= end) {
                const std::size_t offset = static_cast<std::size_t>(source - mapping.base);
                std::memcpy(destination, mapping.bytes.data() + offset, size);
                ++copies_;
                if (size > largestCopy_) largestCopy_ = size;
                return true;
            }
        }
        return false;
    }

private:
    std::vector<Mapping> mappings_;
    std::vector<MemoryRegion> exclusions_;
    mutable std::size_t copies_{0U};
    mutable std::size_t largestCopy_{0U};
};

class ExactProbe final : public PackProbe {
public:
    explicit ExactProbe(std::string expected) : expected_(std::move(expected)) {}
    bool exists(const char *absolutePath) const noexcept override {
        return absolutePath != nullptr && expected_ == absolutePath;
    }

private:
    std::string expected_;
};

struct HookRecorder {
    int pauses{0};
    int resumes{0};
    int stops{0};
    int flushes{0};
    bool flushResult{true};
};

void recordPause(void *context) noexcept { ++static_cast<HookRecorder *>(context)->pauses; }
void recordResume(void *context) noexcept { ++static_cast<HookRecorder *>(context)->resumes; }
void recordStop(void *context) noexcept { ++static_cast<HookRecorder *>(context)->stops; }
bool recordFlush(void *context) noexcept {
    HookRecorder &recorder = *static_cast<HookRecorder *>(context);
    ++recorder.flushes;
    return recorder.flushResult;
}

void testBoundedReader() {
    FakeReader reader;
    reader.map(0x1000U, {1U, 2U, 3U, 4U});
    reader.map(0x1004U, {5U, 6U, 7U, 8U});

    std::array<std::uint8_t, 6> output{};
    const auto read = reader.read(0x1002U, output.data(), output.size());
    expect(read.status == ReadStatus::Ok && read.bytesRead == output.size(),
           "a read may span adjacent readable mappings");
    expect(output == std::array<std::uint8_t, 6>{3U, 4U, 5U, 6U, 7U, 8U},
           "the bounded reader preserves byte order");
    expect(reader.copies() == 2U && reader.largestCopy() == 4U,
           "each memcpy is capped at its queried mapping boundary");

    FakeReader partialReader;
    partialReader.map(0x2000U, {9U, 8U});
    partialReader.map(0x2002U, {7U, 6U}, false);
    std::array<std::uint8_t, 4> partial{};
    const auto failed = partialReader.read(0x2000U, partial.data(), partial.size());
    expect(failed.status == ReadStatus::Partial && failed.bytesRead == 2U,
           "an unreadable next mapping returns a bounded partial result");
    expect(!partialReader.isRangeReadable(0x2000U, partial.size()),
           "range probing rejects any unreadable member mapping");

    std::uint8_t byte = 0U;
    const auto overflow = reader.read(0xFFFFFFFEU, &byte, 4U);
    expect(overflow.status == ReadStatus::InvalidRange && overflow.bytesRead == 0U,
           "32-bit address overflow is rejected before querying");
    expect(reader.read(0x1000U, nullptr, 1U).status == ReadStatus::InvalidRange,
           "a null output buffer is rejected");
}

void testMemoryExclusions() {
    using amun::threeds::excludeMemoryRange;

    // Model a broad process mapping containing both a game save field and a
    // plugin heap allocation: overlap alone must not deny the unrelated field.
    MemoryRegion linearHeap{0x14000000U, 0x0383D000U, true};
    expect(excludeMemoryRange(0x1413C540U, 0x17200000U, 0x00600000U, linearHeap) &&
               linearHeap.readable && linearHeap.base == 0x14000000U &&
               linearHeap.size == 0x03200000U,
           "game memory remains readable before an excluded plugin allocation");

    FakeReader reader;
    reader.map(0x1000U, {0U, 1U, 2U, 3U, 4U, 5U, 6U, 7U,
                         8U, 9U, 10U, 11U, 12U, 13U, 14U, 15U});
    reader.exclude(0x1004U, 4U);
    reader.exclude(0x100CU, 2U);
    std::array<std::uint8_t, 4> bytes{};
    auto result = reader.read(0x1000U, bytes.data(), bytes.size());
    expect(result.status == ReadStatus::Ok &&
               bytes == std::array<std::uint8_t, 4>{0U, 1U, 2U, 3U},
           "an allowed read ending exactly at an exclusion succeeds");
    result = reader.read(0x1008U, bytes.data(), bytes.size());
    expect(result.status == ReadStatus::Ok &&
               bytes == std::array<std::uint8_t, 4>{8U, 9U, 10U, 11U},
           "allowed memory between two exclusions remains readable");
    expect(reader.isRangeReadable(0x100EU, 2U),
           "memory following an exclusion remains readable");
    const std::size_t copiesBeforeDenied = reader.copies();
    result = reader.read(0x1004U, bytes.data(), bytes.size());
    expect(result.status == ReadStatus::Unmapped && result.bytesRead == 0U &&
               reader.copies() == copiesBeforeDenied,
           "a read starting in plugin memory never copies bytes");
    expect(!reader.isRangeReadable(0x1003U, 2U) &&
               !reader.isRangeReadable(0x100BU, 4U),
           "range checks reject reads crossing either exclusion");
    bytes.fill(0xFFU);
    result = reader.read(0x1002U, bytes.data(), bytes.size());
    expect(result.status == ReadStatus::Partial && result.bytesRead == 2U &&
               bytes == std::array<std::uint8_t, 4>{2U, 3U, 0xFFU, 0xFFU},
           "a crossing read stops at the first excluded byte");

    MemoryRegion unreadable{0x2000U, 16U, false};
    expect(excludeMemoryRange(0x2000U, 0x2008U, 4U, unreadable) && !unreadable.readable,
           "exclusion clipping cannot enable an unreadable mapping");
    MemoryRegion emptyExclusion{0x2000U, 16U, true};
    expect(excludeMemoryRange(0x2000U, 0x2008U, 0U, emptyExclusion) &&
               emptyExclusion.readable && emptyExclusion.size == 16U,
           "zero-sized plugin allocations do not exclude an unrelated mapping");
    MemoryRegion invalidExclusion{0x2000U, 16U, true};
    expect(!excludeMemoryRange(0x2000U, 0xFFFFFFF0U, 32U, invalidExclusion) &&
               !invalidExclusion.readable,
           "overflowing plugin metadata fails closed");
    MemoryRegion invalidRegion{0xFFFFFFF0U, 32U, true};
    expect(!excludeMemoryRange(0xFFFFFFF0U, 0x2000U, 4U, invalidRegion) &&
               !invalidRegion.readable,
           "overflowing queried mappings fail closed");
    MemoryRegion topOfAddressSpace{0xFFFFFFF0U, 16U, true};
    expect(excludeMemoryRange(0xFFFFFFF8U, 0xFFFFFFF0U, 8U, topOfAddressSpace) &&
               topOfAddressSpace.readable && topOfAddressSpace.base == 0xFFFFFFF8U &&
               topOfAddressSpace.size == 8U,
           "exclusion arithmetic permits the final readable bytes in address space");
}

void testFullTitleGate() {
    constexpr std::uint64_t title = 0x000400001234ABCDULL;
    ExactProbe present("/amun/packs/000400001234ABCD/game.amunpack");
    const auto accepted = amun::threeds::evaluateTitleGate(title, present);
    expect(accepted.decision == TitleGateDecision::Observe,
           "a native application with an exact full-title pack is accepted");

    ExactProbe lowWordCollision("/amun/packs/000400101234ABCD/game.amunpack");
    const auto rejectedSystemTitle =
        amun::threeds::evaluateTitleGate(0x000400101234ABCDULL, lowWordCollision);
    expect(rejectedSystemTitle.decision == TitleGateDecision::UnsupportedTitleClass,
           "matching low title words cannot admit a system application");

    ExactProbe absent("/amun/packs/000400001234ABCE/game.amunpack");
    const auto missing = amun::threeds::evaluateTitleGate(title, absent);
    expect(missing.decision == TitleGateDecision::PackMissing,
           "an absent exact full-title pack keeps the plugin inert");
}

void testOld2dsPolicy() {
    const amun::RuntimeLimits limits = amun::threeds::old2dsPackLimits();
    expect(limits.maxPackBytes == 512U * 1024U,
           "Old2DS rejects packs larger than its explicit half-megabyte budget");
    expect(limits.maxReferencedStringBytes <= 256U * 1024U &&
               limits.maxStringBytes <= 512U,
           "Old2DS bounds both individual and aggregate referenced strings");
    expect(limits.maxPatternScanBytes <= 2U * 1024U * 1024U &&
               limits.maxTotalPatternScanBytes <= 8U * 1024U * 1024U,
           "Old2DS bounds individual and aggregate signature scanning");
    expect(limits.maxVmStateSlots <= 128U && limits.maxTotalVmStateSlots <= 4096U,
           "Old2DS bounds per-achievement and aggregate VM state");
    expect(limits.maxAssetStoredBytes <= 64U * 1024U &&
               limits.maxTotalAssetDecodedBytes <= 256U * 1024U,
           "Old2DS bounds stored and decoded UI assets");
    expect(limits.maxPrerequisitesPerAchievement >= 32U,
           "Old2DS accepts the 32-prerequisite MK7 ghost milestones");

    using amun::threeds::nextTickDelayMs;
    expect(nextTickDelayMs(0U) == amun::threeds::kMinTickIntervalMs &&
               nextTickDelayMs(2000U) == amun::threeds::kMinTickIntervalMs,
           "fast ticks run at the minimum observer cadence, not every frame");
    expect(nextTickDelayMs(10000U) == 200U,
           "a 10 ms tick backs off to ~5% duty (200 ms gap)");
    expect(nextTickDelayMs(~0ULL / 64U) == amun::threeds::kMaxTickIntervalMs,
           "back-off is capped so unlocks are still noticed within a second");

    const amun::RuntimeConfig runtime = amun::threeds::old2dsRuntimeConfig();
    expect(runtime.performanceMode == amun::PerformanceMode::Balanced,
           "Old2DS defaults to balanced polling");
    expect(runtime.normalIntervalMs >= 250U,
           "Old2DS polls normal-class symbols no faster than 4 Hz");
    expect(runtime.maxTickMicroseconds == 3500U,
           "Old2DS has an explicit per-tick time budget");
}

void testMenuPolicy() {
    expect(amun::threeds::kInformationRowsSelectable,
           "information rows remain reachable with the D-pad");
    expect(amun::threeds::kCloseMenuWithB,
           "B closes the CTRPF overlay from the root menu");
}

void testLifecycle() {
    HookRecorder recorder;
    LifecycleHooks hooks{&recorder, recordPause, recordResume, recordStop, recordFlush};
    LifecycleCoordinator lifecycle(hooks);

    lifecycle.handle(LifecycleEvent::HomeEnter);
    lifecycle.handle(LifecycleEvent::SwapEnter);
    expect(lifecycle.isPaused() && recorder.pauses == 1 && recorder.flushes == 2,
           "nested HOME/SWAP entry pauses once and flushes at both boundaries");

    lifecycle.handle(LifecycleEvent::SwapExit);
    expect(lifecycle.isPaused() && recorder.resumes == 0,
           "leaving one nested suspension does not resume work early");
    lifecycle.handle(LifecycleEvent::HomeExit);
    expect(!lifecycle.isPaused() && recorder.resumes == 1,
           "work resumes after the final suspension reason clears");

    recorder.flushResult = false;
    lifecycle.handle(LifecycleEvent::Exit);
    lifecycle.handle(LifecycleEvent::Exit);
    expect(lifecycle.isStopping() && recorder.stops == 1,
           "the stop hook is idempotent");
    expect(lifecycle.flushFailures() == 2U,
           "flush failures remain observable across duplicate exit delivery");
}

amun::LedgerEvent ledgerEvent(amun::LedgerEventType type, std::uint64_t sequence,
                              std::string eventId, std::string achievementId,
                              std::uint32_t progress = 0U) {
    amun::LedgerEvent event;
    event.type = type;
    event.sequence = sequence;
    event.eventId = std::move(eventId);
    event.achievementId = std::move(achievementId);
    event.progress = progress;
    event.gameBuildId = "test-build";
    event.runtimeVersion = "test-runtime";
    event.sessionId = "test-session";
    return event;
}

void testLedgerSnapshot() {
    LedgerSnapshotState state;
    expect(state.apply(ledgerEvent(amun::LedgerEventType::SessionStarted, 1U,
                                   "session", ""), false) == amun::LedgerStatus::Ok,
           "snapshot state accepts journal-only session history");
    expect(state.apply(ledgerEvent(amun::LedgerEventType::ProgressCheckpoint, 2U,
                                   "p-old", "collector", 10U), false) ==
               amun::LedgerStatus::Ok,
           "snapshot state accepts progress");
    expect(state.apply(ledgerEvent(amun::LedgerEventType::ProgressCheckpoint, 4U,
                                   "p-new", "collector", 25U), false) ==
               amun::LedgerStatus::Ok,
           "snapshot state accepts a newer progress checkpoint");
    expect(state.apply(ledgerEvent(amun::LedgerEventType::AchievementUnlocked, 3U,
                                   "unlock", "boss"), false) == amun::LedgerStatus::Ok,
           "snapshot state accepts an unlock");
    expect(state.apply(ledgerEvent(amun::LedgerEventType::SessionEnded, 5U,
                                   "session-end", ""), false) == amun::LedgerStatus::Ok,
           "snapshot state accepts journal-only session end history");

    const auto retained = state.snapshot();
    expect(retained.size() == 2U, "compaction drops session history but retains state");
    expect(retained.size() == 2U && retained[0].type == amun::LedgerEventType::AchievementUnlocked &&
               retained[0].achievementId == "boss" && retained[0].sequence == 1U,
           "snapshot ordering follows original sequence and resequences deterministically");
    expect(retained.size() == 2U && retained[1].type == amun::LedgerEventType::ProgressCheckpoint &&
               retained[1].achievementId == "collector" && retained[1].progress == 25U &&
               retained[1].sequence == 2U,
           "snapshot retains the latest effective progress checkpoint");
    expect(state.apply(ledgerEvent(amun::LedgerEventType::AchievementUnlocked, 6U,
                                   "unlock-again", "boss"), true) ==
               amun::LedgerStatus::Duplicate,
           "a compacted unlock remains duplicate-protected");

    LedgerSnapshotState unlockedAfterProgress;
    (void)unlockedAfterProgress.apply(
        ledgerEvent(amun::LedgerEventType::ProgressCheckpoint, 1U, "pre", "secret", 9U), false);
    (void)unlockedAfterProgress.apply(
        ledgerEvent(amun::LedgerEventType::AchievementUnlocked, 2U, "done", "secret"), false);
    const auto unlockedSnapshot = unlockedAfterProgress.snapshot();
    expect(unlockedSnapshot.size() == 1U &&
               unlockedSnapshot[0].type == amun::LedgerEventType::AchievementUnlocked,
           "an unlock snapshot supersedes obsolete progress for the same achievement");
}

} // namespace

int main() {
    static_assert(!amun::threeds::kNetworkingCompiledIn,
                  "the conservative bootstrap must not compile networking");
    testBoundedReader();
    testMemoryExclusions();
    testFullTitleGate();
    testOld2dsPolicy();
    testMenuPolicy();
    testLifecycle();
    testLedgerSnapshot();
    if (failures != 0) {
        std::cerr << failures << " platform test(s) failed\n";
        return 1;
    }
    std::cout << "AMUN portable 3DS boundary tests passed\n";
    return 0;
}
