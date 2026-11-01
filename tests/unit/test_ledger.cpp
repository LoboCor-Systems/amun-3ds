#include "test.hpp"

#include "amun/ledger.hpp"

#include <filesystem>
#include <fstream>

using namespace amun;

namespace {
std::filesystem::path ledgerPath(const char *name) {
    return std::filesystem::temp_directory_path() / (std::string("amun-") + name + ".ledger");
}
LedgerEvent unlock(std::string eventId, std::string achievementId) {
    LedgerEvent event;
    event.type = LedgerEventType::AchievementUnlocked;
    event.eventId = std::move(eventId);
    event.achievementId = std::move(achievementId);
    event.gameBuildId = "synthetic";
    event.sessionId = "session";
    event.runtimeVersion = "test";
    return event;
}
}

TEST("memory ledger suppresses duplicate events and duplicate unlocks") {
    MemoryLedger ledger;
    EXPECT_EQ(ledger.append(unlock("event-1", "a")), LedgerStatus::Ok);
    EXPECT_EQ(ledger.append(unlock("event-1", "a")), LedgerStatus::Duplicate);
    EXPECT_EQ(ledger.append(unlock("event-2", "a")), LedgerStatus::Duplicate);
    EXPECT(ledger.isUnlocked("a"));
    EXPECT_EQ(ledger.events().size(), 1U);
}

TEST("journal survives reload and recovers a truncated tail before append") {
    const auto path = ledgerPath("recovery");
    std::error_code ignored;
    std::filesystem::remove(path, ignored);
    JournalLedger ledger(path.string());
    EXPECT(ledger.load());
    EXPECT_EQ(ledger.append(unlock("event-1", "a")), LedgerStatus::Ok);
    {
        std::ofstream corrupt(path, std::ios::binary | std::ios::app);
        corrupt.write("AMLE\1", 5);
    }
    JournalLedger recovered(path.string());
    const LedgerLoadResult result = recovered.load();
    EXPECT(result);
    EXPECT(result.truncatedTail);
    EXPECT(recovered.isUnlocked("a"));
    EXPECT_EQ(recovered.append(unlock("event-2", "b")), LedgerStatus::Ok);
    JournalLedger finalLedger(path.string());
    EXPECT(finalLedger.load());
    EXPECT(finalLedger.isUnlocked("a"));
    EXPECT(finalLedger.isUnlocked("b"));
    std::filesystem::remove(path, ignored);
}

TEST("ledger compaction retains unlocks and latest progress") {
    const auto path = ledgerPath("compact");
    std::error_code ignored;
    std::filesystem::remove(path, ignored);
    std::filesystem::remove(path.string() + ".bak", ignored);
    JournalLedger ledger(path.string());
    EXPECT(ledger.load());
    LedgerEvent progress;
    progress.type = LedgerEventType::ProgressCheckpoint;
    progress.achievementId = "collector";
    progress.sessionId = "s";
    progress.runtimeVersion = "test";
    progress.eventId = "p1";
    progress.progress = 10;
    EXPECT_EQ(ledger.append(progress), LedgerStatus::Ok);
    progress.eventId = "p2"; progress.progress = 25;
    EXPECT_EQ(ledger.append(progress), LedgerStatus::Ok);
    EXPECT_EQ(ledger.append(unlock("u1", "boss")), LedgerStatus::Ok);
    EXPECT_EQ(ledger.compact(), LedgerStatus::Ok);
    EXPECT(ledger.isUnlocked("boss"));
    EXPECT_EQ(ledger.progress("collector"), 25U);
    EXPECT_EQ(ledger.events().size(), 2U);
    std::filesystem::remove(path, ignored);
    std::filesystem::remove(path.string() + ".bak", ignored);
}

