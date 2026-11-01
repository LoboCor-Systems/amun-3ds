#include "amun/pack.hpp"
#include "amun/runtime.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <vector>

namespace {

void emitU16(std::vector<std::uint8_t> &code, std::uint16_t value) {
    code.push_back(static_cast<std::uint8_t>(value));
    code.push_back(static_cast<std::uint8_t>(value >> 8U));
}
void emitI64(std::vector<std::uint8_t> &code, std::int64_t value) {
    std::uint64_t raw = 0;
    std::memcpy(&raw, &value, sizeof(raw));
    for (unsigned i = 0; i < 8U; ++i) code.push_back(static_cast<std::uint8_t>(raw >> (i * 8U)));
}

amun::AchievementPack makePack(std::size_t achievementCount) {
    amun::AchievementPack pack;
    pack.titleId = 0x000400000ABCDEF0ULL;
    pack.gameName = "benchmark";
    pack.profileVersion = "1";
    pack.builds.push_back({"bench", "EUR", "1", "0", "bench-fingerprint", false});
    amun::SymbolDefinition symbol;
    symbol.name = "counter";
    symbol.type = amun::ValueType::U32;
    symbol.pollClass = amun::PollClass::Fast;
    symbol.resolver.kind = amun::ResolverKind::Absolute;
    symbol.resolver.address = 0x08000000U;
    pack.symbols.push_back(symbol);
    for (std::size_t i = 0; i < achievementCount; ++i) {
        amun::AchievementDefinition achievement;
        achievement.id = "achievement-" + std::to_string(i);
        achievement.title = achievement.id;
        achievement.maxStack = 2;
        achievement.instructionBudget = 8;
        achievement.bytecode.push_back(static_cast<std::uint8_t>(amun::Op::LoadCurrent));
        emitU16(achievement.bytecode, 0);
        achievement.bytecode.push_back(static_cast<std::uint8_t>(amun::Op::ConstI64));
        emitI64(achievement.bytecode, static_cast<std::int64_t>(i + 1U));
        achievement.bytecode.push_back(static_cast<std::uint8_t>(amun::Op::Eq));
        achievement.bytecode.push_back(static_cast<std::uint8_t>(amun::Op::End));
        pack.achievements.push_back(std::move(achievement));
    }
    return pack;
}

} // namespace

int main() {
    constexpr std::size_t iterations = 2000;
    std::cout << "achievements,iterations,load_us,start_us,estimated_bytes,mean_us,p95_us,max_us,mean_reads,mean_instructions\n";
    for (const std::size_t count : {10U, 50U, 100U, 250U, 500U}) {
        amun::SyntheticMemoryReader memory;
        memory.map(0x08000000U, 16);
        memory.writeLittleEndian<std::uint32_t>(0x08000000U, 0);
        amun::MemoryLedger ledger;
        amun::ManualClock clock;
        amun::NullEventSink events;
        amun::Runtime runtime;
        const auto loadStarted = std::chrono::steady_clock::now();
        runtime.loadPack(makePack(count));
        const auto loadEnded = std::chrono::steady_clock::now();
        const amun::GameIdentity identity{0x000400000ABCDEF0ULL, "EUR", "1", "0",
                                          "bench-fingerprint", 0x00100000U};
        const auto startStarted = std::chrono::steady_clock::now();
        if (runtime.startSession(identity, memory, ledger, clock, events) != amun::RuntimeStatus::Running) {
            std::cerr << "benchmark session failed\n";
            return 1;
        }
        const auto startEnded = std::chrono::steady_clock::now();
        std::vector<std::uint64_t> timings;
        timings.reserve(iterations);
        std::uint64_t reads = 0;
        std::uint64_t instructions = 0;
        for (std::size_t i = 0; i < iterations; ++i) {
            clock.advance(17);
            const amun::TickMetrics metrics = runtime.tick();
            timings.push_back(metrics.elapsedMicroseconds);
            reads += metrics.reads;
            instructions += metrics.instructionsExecuted;
        }
        std::sort(timings.begin(), timings.end());
        const double mean = static_cast<double>(std::accumulate(timings.begin(), timings.end(), 0ULL)) /
                            static_cast<double>(timings.size());
        const auto p95 = timings[static_cast<std::size_t>(timings.size() * 0.95)];
        const auto loadUs = std::chrono::duration_cast<std::chrono::microseconds>(loadEnded - loadStarted).count();
        const auto startUs = std::chrono::duration_cast<std::chrono::microseconds>(startEnded - startStarted).count();
        std::cout << count << ',' << iterations << ',' << loadUs << ',' << startUs << ','
                  << runtime.estimatedMemoryBytes() << ',' << std::fixed << std::setprecision(3) << mean
                  << ',' << p95 << ',' << timings.back() << ','
                  << static_cast<double>(reads) / iterations << ','
                  << static_cast<double>(instructions) / iterations << '\n';
    }
    return 0;
}
