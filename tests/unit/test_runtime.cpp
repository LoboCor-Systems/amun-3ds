#include "test.hpp"
#include "test_support.hpp"

#include "amun/runtime.hpp"

#include <string>
#include <vector>

using namespace amun;
using namespace amun::test;

namespace {
class CapturingSink final : public EventSink {
public:
    void onUnlock(const UnlockNotification &value) noexcept override { unlocks.push_back(value); }
    void onProgress(const std::string &, std::uint32_t, std::uint32_t) noexcept override { ++progress; }
    void onWarning(const std::string &, const std::string &message) noexcept override { warnings.push_back(message); }
    std::vector<UnlockNotification> unlocks;
    std::vector<std::string> warnings;
    unsigned progress{0};
};

class CountingReader final : public MemoryReader {
public:
    ReadResult read(Address, void *, std::size_t) noexcept override { ++reads; return {ReadStatus::Unmapped, 0}; }
    bool isRangeReadable(Address, std::size_t) const noexcept override { return false; }
    unsigned reads{0};
};

class ObservedMemoryReader final : public MemoryReader {
public:
    ReadResult read(Address address, void *destination, std::size_t size) noexcept override {
        ++reads;
        return memory.read(address, destination, size);
    }
    bool isRangeReadable(Address address, std::size_t size) const noexcept override {
        ++queries;
        return memory.isRangeReadable(address, size);
    }
    SyntheticMemoryReader memory;
    unsigned reads{0};
    mutable unsigned queries{0};
};

class FailingAfterSessionLedger final : public Ledger {
public:
    bool isUnlocked(const std::string &) const noexcept override { return false; }
    std::uint32_t progress(const std::string &) const noexcept override { return 0U; }
    LedgerStatus append(LedgerEvent event) override {
        ++appends;
        if (event.type == LedgerEventType::SessionStarted) return LedgerStatus::Ok;
        return LedgerStatus::IoError;
    }

    unsigned appends{0};
};

std::vector<std::uint8_t> maximumInstructionProgram() {
    std::vector<std::uint8_t> code;
    constant(code, 1);
    for (std::uint32_t i = 0; i < 2046U; ++i) op(code, Op::Not);
    op(code, Op::End);
    return code;
}
}

TEST("complete runtime slice persists before toast and never duplicates after restart") {
    std::vector<std::uint8_t> code;
    load(code, Op::LoadPrevious, 0); constant(code, 0); op(code, Op::Gt);
    load(code, Op::LoadCurrent, 0); constant(code, 0); op(code, Op::Eq);
    op(code, Op::All); code.push_back(2); op(code, Op::End);
    AchievementPack pack = basicPack(code);
    SyntheticMemoryReader memory;
    EXPECT(memory.map(0x08001000U, 16));
    EXPECT(memory.writeLittleEndian<std::uint16_t>(0x08001000U, 100));
    MemoryLedger ledger;
    ManualClock clock; clock.setWallClock(1'700'000'000'000ULL);
    CapturingSink events;
    Runtime runtime;
    EXPECT(runtime.loadPack(pack));
    EXPECT_EQ(runtime.startSession(basicIdentity(), memory, ledger, clock, events), RuntimeStatus::Running);
    runtime.tick();
    EXPECT(events.unlocks.empty());
    EXPECT(memory.writeLittleEndian<std::uint16_t>(0x08001000U, 0));
    clock.advance(100);
    runtime.tick();
    EXPECT_EQ(events.unlocks.size(), 1U);
    EXPECT(ledger.isUnlocked("first_boss"));
    runtime.endSession();

    CapturingSink secondEvents;
    Runtime restarted;
    EXPECT(restarted.loadPack(pack));
    clock.advance(1);
    EXPECT_EQ(restarted.startSession(basicIdentity(), memory, ledger, clock, secondEvents), RuntimeStatus::Running);
    clock.advance(100);
    restarted.tick();
    EXPECT(secondEvents.unlocks.empty());
}

TEST("a ledger failure is latched for the session instead of retrying every frame") {
    AchievementPack pack = basicPack(equalityProgram(0, 0));
    SyntheticMemoryReader memory;
    EXPECT(memory.map(0x08001000U, 8));
    FailingAfterSessionLedger ledger;
    ManualClock clock;
    CapturingSink events;
    Runtime runtime;
    EXPECT(runtime.loadPack(std::move(pack)));
    EXPECT_EQ(runtime.startSession(basicIdentity(), memory, ledger, clock, events),
              RuntimeStatus::Running);

    runtime.tick();
    EXPECT_EQ(ledger.appends, 2U);
    EXPECT_EQ(events.warnings.size(), 1U);
    EXPECT(events.unlocks.empty());

    clock.advance(100);
    runtime.tick();
    EXPECT_EQ(ledger.appends, 2U);
    EXPECT_EQ(events.warnings.size(), 1U);
    EXPECT(events.unlocks.empty());

    runtime.endSession();
    EXPECT_EQ(ledger.appends, 2U);
    EXPECT_EQ(runtime.status(), RuntimeStatus::Ended);
}

TEST("unknown build performs no memory reads") {
    AchievementPack pack = basicPack();
    CountingReader memory;
    MemoryLedger ledger;
    ManualClock clock;
    NullEventSink events;
    Runtime runtime;
    EXPECT(runtime.loadPack(std::move(pack)));
    GameIdentity identity = basicIdentity();
    identity.codeFingerprint = "unknown";
    EXPECT_EQ(runtime.startSession(identity, memory, ledger, clock, events), RuntimeStatus::ExactBuildRequired);
    EXPECT_EQ(memory.reads, 0U);
}

TEST("read plan samples a shared symbol once for multiple achievements") {
    AchievementPack pack = basicPack(equalityProgram(0, 99));
    AchievementDefinition second = pack.achievements.front();
    second.id = "second";
    second.title = "Second";
    pack.achievements.push_back(second);
    SyntheticMemoryReader memory;
    EXPECT(memory.map(0x08001000U, 8));
    EXPECT(memory.writeLittleEndian<std::uint16_t>(0x08001000U, 1));
    MemoryLedger ledger;
    ManualClock clock;
    NullEventSink events;
    Runtime runtime;
    EXPECT(runtime.loadPack(std::move(pack)));
    EXPECT_EQ(runtime.startSession(basicIdentity(), memory, ledger, clock, events), RuntimeStatus::Running);
    const TickMetrics metrics = runtime.tick();
    EXPECT_EQ(metrics.reads, 1U);
    EXPECT_EQ(metrics.achievementsEvaluated, 2U);
}

TEST("a delayed heap resolves at the slow cadence and primes coin history before unlocking") {
    std::vector<std::uint8_t> code;
    load(code, Op::Increased, 0); op(code, Op::End);
    AchievementPack pack = basicPack(code);
    pack.symbols[0].pollClass = PollClass::Slow;
    ObservedMemoryReader memory;
    MemoryLedger ledger;
    ManualClock clock;
    CapturingSink events;
    Runtime runtime;
    EXPECT(runtime.loadPack(std::move(pack)));
    EXPECT_EQ(runtime.startSession(basicIdentity(), memory, ledger, clock, events), RuntimeStatus::Running);
    EXPECT_EQ(memory.queries, 1U);
    for (unsigned tick = 0; tick < 100U; ++tick) {
        EXPECT_EQ(runtime.tick().reads, 0U);
        EXPECT(!runtime.achievementStates()[0].disabled);
        clock.advance(10);
    }
    EXPECT_EQ(memory.queries, 1U);
    EXPECT_EQ(events.warnings.size(), 1U);
    EXPECT(memory.memory.map(0x08001000U, 16));
    EXPECT(memory.memory.writeLittleEndian<std::uint16_t>(0x08001000U, 30));
    EXPECT_EQ(runtime.tick().reads, 1U);
    EXPECT(runtime.symbolSnapshots()[0].valid);
    EXPECT_EQ(runtime.symbolSnapshots()[0].initial.integer, 30);
    EXPECT(!runtime.symbolSnapshots()[0].hasPrevious);
    EXPECT(events.unlocks.empty());
    EXPECT(memory.memory.writeLittleEndian<std::uint16_t>(0x08001000U, 31));
    clock.advance(999);
    EXPECT_EQ(runtime.tick().reads, 0U);
    EXPECT(events.unlocks.empty());
    clock.advance(1);
    EXPECT_EQ(runtime.tick().reads, 1U);
    EXPECT_EQ(events.unlocks.size(), 1U);
    EXPECT(ledger.isUnlocked("first_boss"));
    EXPECT_EQ(events.warnings.size(), 2U);
}

TEST("delayed module and pointer resolvers recover and account for pointer reads") {
    for (ResolverKind kind : {ResolverKind::ModuleRelative, ResolverKind::PointerChain}) {
        AchievementPack pack = basicPack(equalityProgram(0, 42));
        pack.symbols[0].resolver.kind = kind;
        pack.symbols[0].resolver.moduleOffset = 0x07F01000;
        pack.symbols[0].resolver.pointerOffsets = {0, 0};
        ObservedMemoryReader memory;
        MemoryLedger ledger;
        ManualClock clock;
        CapturingSink events;
        Runtime runtime;
        EXPECT(runtime.loadPack(std::move(pack)));
        EXPECT_EQ(runtime.startSession(basicIdentity(), memory, ledger, clock, events), RuntimeStatus::Running);
        runtime.tick();
        EXPECT(!runtime.achievementStates()[0].disabled);
        EXPECT(memory.memory.map(0x08001000U, 16));
        if (kind == ResolverKind::PointerChain) {
            EXPECT(memory.memory.map(0x08002000U, 16));
            EXPECT(memory.memory.writeLittleEndian<std::uint32_t>(0x08001000U, 0x08002000U));
            EXPECT(memory.memory.writeLittleEndian<std::uint16_t>(0x08002000U, 42));
        } else {
            EXPECT(memory.memory.writeLittleEndian<std::uint16_t>(0x08001000U, 42));
        }
        clock.advance(100);
        const TickMetrics tick = runtime.tick();
        EXPECT_EQ(tick.reads, kind == ResolverKind::PointerChain ? 2U : 1U);
        EXPECT_EQ(tick.bytesRead, kind == ResolverKind::PointerChain ? 6U : 2U);
        EXPECT_EQ(tick.reads, memory.reads);
        EXPECT_EQ(events.unlocks.size(), 1U);
    }
}

TEST("resolution retry budget is fair to later symbols and excludes pattern scans") {
    AchievementPack pack = basicPack(equalityProgram(0, 99));
    for (unsigned index = 1; index < 4U; ++index) {
        SymbolDefinition symbol = pack.symbols[0];
        symbol.name = "late." + std::to_string(index);
        symbol.resolver.address += index * 0x1000U;
        pack.symbols.push_back(symbol);
    }
    SymbolDefinition pattern = pack.symbols[0];
    pattern.name = "pattern";
    pattern.resolver.kind = ResolverKind::Pattern;
    pattern.resolver.pattern = {0x09000000U, 16, {42}, {0xFF}, 0};
    pack.symbols.push_back(pattern);
    ObservedMemoryReader memory;
    MemoryLedger ledger;
    ManualClock clock;
    CapturingSink events;
    RuntimeConfig config;
    config.maxSymbolResolutionsPerTick = 1;
    Runtime runtime(config);
    EXPECT(runtime.loadPack(std::move(pack)));
    EXPECT_EQ(runtime.startSession(basicIdentity(), memory, ledger, clock, events), RuntimeStatus::Running);
    EXPECT(memory.memory.map(0x08002000U, 16));
    EXPECT(memory.memory.map(0x08003000U, 16));
    EXPECT(memory.memory.map(0x08004000U, 16));
    EXPECT(memory.memory.map(0x09000000U, 16, 42));
    clock.advance(100);
    for (unsigned index = 0; index < 4U; ++index) {
        const unsigned queries = memory.queries;
        const TickMetrics tick = runtime.tick();
        EXPECT_EQ(memory.queries - queries, 1U);
        EXPECT_EQ(tick.reads, index == 0 ? 0U : 1U);
        EXPECT_EQ(runtime.symbolSnapshots()[index].valid, index != 0);
    }
    const unsigned queries = memory.queries;
    EXPECT_EQ(runtime.tick().reads, 0U);
    EXPECT_EQ(memory.queries, queries);
    EXPECT(!runtime.symbolSnapshots()[4].valid);
    EXPECT(!runtime.symbolSnapshots()[0].valid);
}

TEST("a static symbol retries slowly until its first successful sample only") {
    AchievementPack pack = basicPack(equalityProgram(0, 42));
    pack.symbols[0].pollClass = PollClass::Static;
    ObservedMemoryReader memory;
    MemoryLedger ledger;
    ManualClock clock;
    CapturingSink events;
    Runtime runtime;
    EXPECT(runtime.loadPack(std::move(pack)));
    EXPECT_EQ(runtime.startSession(basicIdentity(), memory, ledger, clock, events), RuntimeStatus::Running);
    runtime.tick();
    EXPECT(memory.memory.map(0x08001000U, 16));
    EXPECT(memory.memory.writeLittleEndian<std::uint16_t>(0x08001000U, 42));
    clock.advance(999);
    EXPECT_EQ(runtime.tick().reads, 0U);
    clock.advance(1);
    EXPECT_EQ(runtime.tick().reads, 1U);
    EXPECT_EQ(events.unlocks.size(), 1U);
    clock.advance(10000);
    EXPECT_EQ(runtime.tick().reads, 0U);
}

TEST("failed reads obey poll cadence and recovery does not bridge a missing history sample") {
    std::vector<std::uint8_t> code;
    load(code, Op::Increased, 0); op(code, Op::End);
    AchievementPack pack = basicPack(code);
    ObservedMemoryReader memory;
    EXPECT(memory.memory.map(0x08001000U, 16));
    EXPECT(memory.memory.writeLittleEndian<std::uint16_t>(0x08001000U, 30));
    MemoryLedger ledger;
    ManualClock clock;
    CapturingSink events;
    Runtime runtime;
    EXPECT(runtime.loadPack(std::move(pack)));
    EXPECT_EQ(runtime.startSession(basicIdentity(), memory, ledger, clock, events), RuntimeStatus::Running);
    runtime.tick();
    clock.advance(100);
    runtime.tick();
    EXPECT(runtime.symbolSnapshots()[0].hasPrevious);
    EXPECT(memory.memory.setReadable(0x08001000U, false));
    clock.advance(100);
    EXPECT_EQ(runtime.tick().reads, 1U);
    EXPECT(!runtime.symbolSnapshots()[0].valid);
    for (unsigned tick = 0; tick < 20U; ++tick) EXPECT_EQ(runtime.tick().reads, 0U);
    EXPECT(!runtime.achievementStates()[0].disabled);
    EXPECT(memory.memory.setReadable(0x08001000U, true));
    EXPECT(memory.memory.writeLittleEndian<std::uint16_t>(0x08001000U, 40));
    clock.advance(100);
    EXPECT_EQ(runtime.tick().reads, 1U);
    EXPECT(events.unlocks.empty());
    EXPECT(!runtime.symbolSnapshots()[0].hasPrevious);
    EXPECT(memory.memory.writeLittleEndian<std::uint16_t>(0x08001000U, 41));
    clock.advance(100);
    runtime.tick();
    EXPECT_EQ(events.unlocks.size(), 1U);
}

TEST("derived symbols can wait for a delayed dependency without becoming disabled") {
    AchievementPack pack = basicPack(equalityProgram(1, 42));
    SymbolDefinition derived;
    derived.name = "derived.value";
    derived.type = ValueType::U32;
    derived.resolver.kind = ResolverKind::Derived;
    load(derived.derivedBytecode, Op::LoadCurrent, 0);
    op(derived.derivedBytecode, Op::End);
    pack.symbols.push_back(derived);
    ObservedMemoryReader memory;
    MemoryLedger ledger;
    ManualClock clock;
    CapturingSink events;
    Runtime runtime;
    EXPECT(runtime.loadPack(std::move(pack)));
    EXPECT_EQ(runtime.startSession(basicIdentity(), memory, ledger, clock, events), RuntimeStatus::Running);
    for (unsigned tick = 0; tick < 12U; ++tick) {
        runtime.tick();
        clock.advance(100);
    }
    EXPECT_EQ(events.warnings.size(), 1U);
    EXPECT(!runtime.achievementStates()[0].disabled);
    EXPECT(memory.memory.map(0x08001000U, 16));
    EXPECT(memory.memory.writeLittleEndian<std::uint16_t>(0x08001000U, 42));
    runtime.tick();
    EXPECT(runtime.symbolSnapshots()[1].valid);
    EXPECT_EQ(events.unlocks.size(), 1U);
}

TEST("derived symbols evaluate in a bounded topological read plan") {
    AchievementPack pack = basicPack();
    pack.symbols[0].name = "player.hp";
    pack.symbols[0].resolver.address = 0x08001000U;
    SymbolDefinition maximum = pack.symbols[0];
    maximum.name = "player.max_hp";
    maximum.resolver.address = 0x08001004U;
    pack.symbols.push_back(maximum);
    SymbolDefinition percent;
    percent.name = "player.hp_percent";
    percent.type = ValueType::U32;
    percent.pollClass = PollClass::Normal;
    percent.resolver.kind = ResolverKind::Derived;
    load(percent.derivedBytecode, Op::LoadCurrent, 0);
    constant(percent.derivedBytecode, 100);
    op(percent.derivedBytecode, Op::Multiply);
    load(percent.derivedBytecode, Op::LoadCurrent, 1);
    op(percent.derivedBytecode, Op::Divide);
    op(percent.derivedBytecode, Op::End);
    pack.symbols.push_back(percent);
    pack.achievements[0].bytecode.clear();
    load(pack.achievements[0].bytecode, Op::LoadCurrent, 2);
    constant(pack.achievements[0].bytecode, 75);
    op(pack.achievements[0].bytecode, Op::Ge);
    op(pack.achievements[0].bytecode, Op::End);
    SyntheticMemoryReader memory;
    EXPECT(memory.map(0x08001000U, 16));
    EXPECT(memory.writeLittleEndian<std::uint16_t>(0x08001000U, 3));
    EXPECT(memory.writeLittleEndian<std::uint16_t>(0x08001004U, 4));
    MemoryLedger ledger;
    ManualClock clock;
    CapturingSink events;
    Runtime runtime;
    EXPECT(runtime.loadPack(std::move(pack)));
    EXPECT_EQ(runtime.startSession(basicIdentity(), memory, ledger, clock, events), RuntimeStatus::Running);
    const TickMetrics metrics = runtime.tick();
    EXPECT_EQ(metrics.reads, 2U);
    EXPECT_EQ(runtime.symbolSnapshots()[2].current.integer, 75);
    EXPECT_EQ(events.unlocks.size(), 1U);
}

TEST("pointer chains validate each dereference and resolve the final value") {
    AchievementPack pack = basicPack(equalityProgram(0, 42));
    SymbolDefinition &symbol = pack.symbols[0];
    symbol.resolver.kind = ResolverKind::PointerChain;
    symbol.resolver.address = 0x08002000U;
    symbol.resolver.pointerOffsets = {4, 8};
    SyntheticMemoryReader memory;
    EXPECT(memory.map(0x08002000U, 16));
    EXPECT(memory.map(0x08003000U, 16));
    EXPECT(memory.writeLittleEndian<std::uint32_t>(0x08002004U, 0x08003000U));
    EXPECT(memory.writeLittleEndian<std::uint16_t>(0x08003008U, 42));
    MemoryLedger ledger;
    ManualClock clock;
    CapturingSink events;
    Runtime runtime;
    EXPECT(runtime.loadPack(std::move(pack)));
    EXPECT_EQ(runtime.startSession(basicIdentity(), memory, ledger, clock, events), RuntimeStatus::Running);
    runtime.tick();
    EXPECT_EQ(events.unlocks.size(), 1U);
}

TEST("global per-tick instruction budget disables a profile without affecting the game reader") {
    AchievementPack pack = basicPack(equalityProgram(0, 99));
    AchievementDefinition second = pack.achievements.front();
    second.id = "second";
    pack.achievements.push_back(second);
    SyntheticMemoryReader memory;
    EXPECT(memory.map(0x08001000U, 8));
    MemoryLedger ledger;
    ManualClock clock;
    CapturingSink events;
    RuntimeConfig config;
    config.maxInstructionsPerTick = 4;
    Runtime runtime(config);
    EXPECT(runtime.loadPack(std::move(pack)));
    EXPECT_EQ(runtime.startSession(basicIdentity(), memory, ledger, clock, events), RuntimeStatus::Running);
    runtime.tick();
    EXPECT_EQ(runtime.status(), RuntimeStatus::ProfileDisabled);
    EXPECT(!events.warnings.empty());
    runtime.endSession();
    EXPECT_EQ(runtime.status(), RuntimeStatus::Ended);
}

TEST("refreshing encoded pointers discard old objects and recover from absent scenes") {
    std::vector<std::uint8_t> code;
    load(code, Op::Increased, 0); op(code, Op::End);
    AchievementPack pack = basicPack(code);
    auto &resolver = pack.symbols[0].resolver;
    resolver.kind = ResolverKind::PointerChain;
    resolver.address = 0x08002000U;
    resolver.pointerOffsets = {4, 8};
    resolver.pointerXorMasks = {0x75F1B26BU};
    resolver.refresh = true;
    ObservedMemoryReader reader;
    auto &memory = reader.memory;
    EXPECT(memory.map(0x08002000U, 16));
    EXPECT(memory.map(0x08003000U, 16));
    EXPECT(memory.map(0x08004000U, 16));
    const auto pointTo = [&](Address address) {
        EXPECT(memory.writeLittleEndian<std::uint32_t>(0x08002004U, address ^ 0x75F1B26BU));
    };
    pointTo(0x08003000U);
    EXPECT(memory.writeLittleEndian<std::uint16_t>(0x08003008U, 10));
    EXPECT(memory.writeLittleEndian<std::uint16_t>(0x08004008U, 40));
    MemoryLedger ledger;
    ManualClock clock;
    CapturingSink events;
    Runtime runtime;
    EXPECT(runtime.loadPack(std::move(pack)));
    EXPECT_EQ(runtime.startSession(basicIdentity(), reader, ledger, clock, events), RuntimeStatus::Running);
    EXPECT_EQ(runtime.tick().reads, 2U);
    EXPECT_EQ(runtime.tick().reads, 0U); // normal cadence, not every frame
    pointTo(0x08004000U);
    clock.advance(100); runtime.tick();
    EXPECT(!runtime.symbolSnapshots()[0].valid);
    clock.advance(100); runtime.tick();
    EXPECT_EQ(runtime.symbolSnapshots()[0].current.integer, 40);
    EXPECT(!runtime.symbolSnapshots()[0].hasPrevious);
    EXPECT(events.unlocks.empty());
    pointTo(0);
    for (unsigned i = 0; i < 12; ++i) {
        clock.advance(100); runtime.tick();
        EXPECT(!runtime.symbolSnapshots()[0].valid);
        EXPECT(!runtime.achievementStates()[0].disabled);
    }
    pointTo(0x08003000U);
    EXPECT(memory.writeLittleEndian<std::uint16_t>(0x08003008U, 50));
    clock.advance(100); runtime.tick();
    EXPECT_EQ(runtime.symbolSnapshots()[0].initial.integer, 50);
    EXPECT(events.unlocks.empty());
    EXPECT(memory.writeLittleEndian<std::uint16_t>(0x08003008U, 51));
    clock.advance(100); runtime.tick();
    EXPECT_EQ(events.unlocks.size(), 1U);
    EXPECT(events.warnings.empty());
}

TEST("refreshing pointer relocation breaks partial achievement state") {
    std::vector<std::uint8_t> code;
    load(code, Op::LoadCurrent, 0); constant(code, 10); op(code, Op::Eq);
    op(code, Op::Latch); code.push_back(0); code.push_back(0);
    load(code, Op::LoadCurrent, 0); constant(code, 42); op(code, Op::Eq);
    op(code, Op::All); code.push_back(2); op(code, Op::End);
    auto pack = basicPack(code);
    auto &resolver = pack.symbols[0].resolver;
    resolver.kind = ResolverKind::PointerChain;
    resolver.address = 0x08002000U;
    resolver.pointerOffsets = {0, 0};
    resolver.refresh = true;
    SyntheticMemoryReader memory;
    EXPECT(memory.map(0x08002000U, 0x30));
    EXPECT(memory.writeLittleEndian<std::uint32_t>(0x08002000U, 0x08002010U));
    EXPECT(memory.writeLittleEndian<std::uint16_t>(0x08002010U, 10));
    EXPECT(memory.writeLittleEndian<std::uint16_t>(0x08002020U, 42));
    MemoryLedger ledger;
    ManualClock clock;
    CapturingSink events;
    Runtime runtime;
    EXPECT(runtime.loadPack(std::move(pack)));
    EXPECT_EQ(runtime.startSession(basicIdentity(), memory, ledger, clock, events), RuntimeStatus::Running);
    runtime.tick();
    EXPECT(memory.writeLittleEndian<std::uint32_t>(0x08002000U, 0x08002020U));
    clock.advance(100); runtime.tick();
    clock.advance(100); runtime.tick();
    EXPECT(events.unlocks.empty());
    EXPECT(memory.writeLittleEndian<std::uint16_t>(0x08002020U, 10));
    clock.advance(100); runtime.tick();
    EXPECT(memory.writeLittleEndian<std::uint16_t>(0x08002020U, 42));
    clock.advance(100); runtime.tick();
    EXPECT_EQ(events.unlocks.size(), 1U);
}

TEST("summary uses achievement count for completion and points independently") {
    AchievementPack pack = basicPack(equalityProgram(0, 0));
    AchievementDefinition second = pack.achievements.front();
    second.id = "secret";
    second.title = "Hidden";
    second.secret = true;
    second.points = 90;
    second.bytecode = equalityProgram(0, 999);
    pack.achievements.push_back(second);
    SyntheticMemoryReader memory;
    EXPECT(memory.map(0x08001000U, 8));
    MemoryLedger ledger;
    ManualClock clock;
    NullEventSink events;
    Runtime runtime;
    EXPECT(runtime.loadPack(std::move(pack)));
    EXPECT_EQ(runtime.startSession(basicIdentity(), memory, ledger, clock, events), RuntimeStatus::Running);
    runtime.tick();
    const RuntimeSummary summary = runtime.summary();
    EXPECT_EQ(summary.achievementsUnlocked, 1U);
    EXPECT_EQ(summary.achievementsTotal, 2U);
    EXPECT_EQ(summary.pointsUnlocked, 10U);
    EXPECT_EQ(summary.pointsTotal, 100U);
    EXPECT_EQ(summary.completionPercent, 50U);
}

TEST("programmatic packs enforce per-object and aggregate VM resource limits") {
    {
        AchievementPack pack = basicPack();
        pack.builds.resize(65U, pack.builds.front());
        Runtime runtime;
        std::string detail;
        EXPECT(!runtime.loadPack(std::move(pack), &detail));
        EXPECT_EQ(runtime.status(), RuntimeStatus::PackInvalid);
        EXPECT(!detail.empty());
    }
    {
        AchievementPack pack = basicPack();
        pack.achievements.front().stateSlots = 257U;
        Runtime runtime;
        EXPECT(!runtime.loadPack(std::move(pack)));
    }
    {
        AchievementPack pack = basicPack();
        AchievementDefinition prototype = pack.achievements.front();
        prototype.bytecode = equalityProgram(0, 0);
        prototype.maxStack = 1;
        prototype.stateSlots = 256;
        prototype.instructionBudget = 4;
        pack.achievements.clear();
        for (std::uint32_t i = 0; i < 17U; ++i) {
            AchievementDefinition achievement = prototype;
            achievement.id = "state_" + std::to_string(i);
            pack.achievements.push_back(std::move(achievement));
        }
        Runtime runtime;
        EXPECT(!runtime.loadPack(std::move(pack)));
    }
    {
        AchievementPack pack = basicPack();
        AchievementDefinition prototype = pack.achievements.front();
        prototype.bytecode = maximumInstructionProgram();
        prototype.maxStack = 1;
        prototype.stateSlots = 0;
        prototype.instructionBudget = 2048;
        pack.achievements.clear();
        for (std::uint32_t i = 0; i < 128U; ++i) {
            AchievementDefinition achievement = prototype;
            achievement.id = "code_" + std::to_string(i);
            pack.achievements.push_back(std::move(achievement));
        }
        Runtime runtime;
        EXPECT(!runtime.loadPack(std::move(pack)));
    }
}

TEST("programmatic packs bound referenced metadata and prerequisite fanout") {
    {
        AchievementPack pack = basicPack();
        pack.gameName.assign(1025U, 'x');
        Runtime runtime;
        EXPECT(!runtime.loadPack(std::move(pack)));
    }
    {
        AchievementPack pack = basicPack();
        pack.achievements.front().prerequisites.assign(33U, "first_boss");
        Runtime runtime;
        EXPECT(!runtime.loadPack(std::move(pack)));
    }
    {
        AchievementPack pack = basicPack();
        const std::string longText(1024U, 'x');
        AchievementDefinition prototype = pack.achievements.front();
        prototype.title = longText;
        prototype.description = longText;
        prototype.author = longText;
        prototype.category = longText;
        prototype.tags = longText;
        prototype.icon.clear();
        pack.achievements.clear();
        for (std::uint32_t i = 0; i < 500U; ++i) {
            AchievementDefinition achievement = prototype;
            achievement.id = "metadata_" + std::to_string(i);
            pack.achievements.push_back(std::move(achievement));
        }
        Runtime runtime;
        EXPECT(!runtime.loadPack(std::move(pack)));
    }
    {
        AchievementPack pack = basicPack();
        pack.achievements.front().prerequisites = {"missing"};
        Runtime runtime;
        EXPECT(!runtime.loadPack(std::move(pack)));
    }
}

TEST("programmatic packs bound pattern scans and stored asset expansion") {
    {
        AchievementPack pack = basicPack();
        SymbolDefinition &symbol = pack.symbols.front();
        symbol.resolver.kind = ResolverKind::Pattern;
        symbol.resolver.pattern.scanStart = 0x00100000U;
        symbol.resolver.pattern.scanSize = 32U * 1024U * 1024U + 1U;
        symbol.resolver.pattern.bytes = {0xAA};
        symbol.resolver.pattern.mask = {0xFF};
        Runtime runtime;
        EXPECT(!runtime.loadPack(std::move(pack)));
    }
    {
        AchievementPack pack = basicPack();
        SymbolDefinition prototype = pack.symbols.front();
        prototype.resolver.kind = ResolverKind::Pattern;
        prototype.resolver.pattern.scanStart = 0x00100000U;
        prototype.resolver.pattern.scanSize = 24U * 1024U * 1024U;
        prototype.resolver.pattern.bytes = {0xAA};
        prototype.resolver.pattern.mask = {0xFF};
        pack.symbols.clear();
        for (std::uint32_t i = 0; i < 3U; ++i) {
            SymbolDefinition symbol = prototype;
            symbol.name = "pattern_" + std::to_string(i);
            pack.symbols.push_back(std::move(symbol));
        }
        Runtime runtime;
        EXPECT(!runtime.loadPack(std::move(pack)));
    }
    {
        AchievementPack pack = basicPack();
        AssetDefinition prototype;
        prototype.kind = AssetKind::Sound;
        prototype.format = AssetFormat::PcmU8;
        prototype.compression = AssetCompression::None;
        prototype.decodedSize = 2049U;
        prototype.encodedData.assign(prototype.decodedSize, 0x80U);
        for (std::uint32_t i = 0; i < 128U; ++i) {
            AssetDefinition asset = prototype;
            asset.name = "sound_" + std::to_string(i);
            pack.assets.push_back(std::move(asset));
        }
        Runtime runtime;
        EXPECT(!runtime.loadPack(std::move(pack)));
    }
}

TEST("programmatic packs reject duplicate identities and missing icons") {
    {
        AchievementPack pack = basicPack();
        AchievementDefinition duplicate = pack.achievements.front();
        pack.achievements.push_back(std::move(duplicate));
        Runtime runtime;
        EXPECT(!runtime.loadPack(std::move(pack)));
    }
    {
        AchievementPack pack = basicPack();
        pack.achievements.front().icon = "missing.icon";
        Runtime runtime;
        EXPECT(!runtime.loadPack(std::move(pack)));
    }
}
