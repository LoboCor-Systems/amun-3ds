#include "amun/ledger.hpp"
#include "amun/pack.hpp"
#include "amun/runtime.hpp"
#include "amun/trace.hpp"

#include <algorithm>
#include <filesystem>
#include <iostream>
#include <string>

namespace {

class ConsoleEvents final : public amun::EventSink {
public:
    void onUnlock(const amun::UnlockNotification &event) noexcept override {
        std::cout << "UNLOCK " << event.achievementId << " | " << event.title << " | +"
                  << event.points << '\n';
        ++unlocks;
    }
    void onProgress(const std::string &id, std::uint32_t current,
                    std::uint32_t target) noexcept override {
        std::cout << "PROGRESS " << id << ' ' << current << '/' << target << '\n';
    }
    void onWarning(const std::string &subsystem, const std::string &message) noexcept override {
        std::cerr << "WARN [" << subsystem << "] " << message << '\n';
    }
    std::size_t unlocks{0};
};

void usage() {
    std::cout << "AMUN host replay simulator\n\n"
              << "Usage:\n"
              << "  amun-sim --pack GAME.amunpack --trace SESSION.amuntrace [--ledger FILE]\n";
}

} // namespace

int main(int argc, char **argv) {
    std::string packPath;
    std::string tracePath;
    std::string ledgerPath = "amun-sim.ledger";
    for (int i = 1; i < argc; ++i) {
        const std::string argument(argv[i]);
        if ((argument == "--pack" || argument == "--trace" || argument == "--ledger") && i + 1 < argc) {
            const std::string value(argv[++i]);
            if (argument == "--pack") packPath = value;
            else if (argument == "--trace") tracePath = value;
            else ledgerPath = value;
        } else if (argument == "--help" || argument == "-h") {
            usage();
            return 0;
        } else {
            std::cerr << "Unknown or incomplete option: " << argument << '\n';
            usage();
            return 2;
        }
    }
    if (packPath.empty() || tracePath.empty()) {
        usage();
        return 2;
    }

    amun::AchievementPack pack;
    const amun::PackParseResult parsed = amun::PackParser{}.parseFile(packPath, pack);
    if (!parsed) {
        std::cerr << "Pack error: " << parsed.detail << '\n';
        return 1;
    }
    amun::TraceData trace;
    std::string error;
    if (!amun::readTraceFile(tracePath, trace, error)) {
        std::cerr << "Trace error: " << error << '\n';
        return 1;
    }
    if (trace.titleId != pack.titleId || trace.profileHash != pack.profileHash) {
        std::cerr << "Trace identity/profile hash does not match pack\n";
        return 1;
    }
    const auto build = std::find_if(pack.builds.begin(), pack.builds.end(), [&](const auto &candidate) {
        return candidate.id == trace.buildId;
    });
    if (build == pack.builds.end()) {
        std::cerr << "Trace build ID is absent from pack\n";
        return 1;
    }
    if (trace.frames.empty()) {
        std::cerr << "Trace contains no frames\n";
        return 1;
    }

    amun::JournalLedger ledger(ledgerPath);
    const amun::LedgerLoadResult loaded = ledger.load();
    if (!loaded) {
        std::cerr << "Ledger error: " << loaded.detail << '\n';
        return 1;
    }
    amun::ReplayMemoryReader memory(trace.frames);
    amun::ManualClock clock;
    clock.setMonotonic(memory.frameTime());
    ConsoleEvents events;
    amun::Runtime runtime;
    if (!runtime.loadPack(pack, &error)) {
        std::cerr << "Runtime rejected pack: " << error << '\n';
        return 1;
    }
    amun::GameIdentity identity{pack.titleId, build->region, build->applicationVersion,
                                build->updateVersion, build->codeFingerprint, 0x00100000U};
    const amun::RuntimeStatus started = runtime.startSession(identity, memory, ledger, clock, events);
    if (started != amun::RuntimeStatus::Running) {
        std::cerr << "Runtime could not start, status " << static_cast<unsigned>(started) << '\n';
        return 1;
    }
    std::uint64_t instructions = 0;
    std::uint64_t reads = 0;
    do {
        clock.setMonotonic(memory.frameTime());
        const amun::TickMetrics metrics = runtime.tick();
        instructions += metrics.instructionsExecuted;
        reads += metrics.reads;
    } while (memory.advance());
    runtime.endSession();
    std::cout << "Replay complete: " << trace.frames.size() << " frames, " << reads
              << " reads, " << instructions << " VM instructions, " << events.unlocks
              << " new unlocks\n";
    return 0;
}
