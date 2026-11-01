#pragma once

#include "amun/types.hpp"

#include <array>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace amun {

enum class LedgerEventType : std::uint8_t {
    SessionStarted = 1,
    AchievementUnlocked = 2,
    ProgressCheckpoint = 3,
    SessionEnded = 4,
    SyncAcknowledged = 5,
};

struct LedgerEvent {
    LedgerEventType type{LedgerEventType::SessionStarted};
    std::uint64_t sequence{0};
    std::uint64_t wallClockUnixMs{0};
    IntegrityMode integrity{IntegrityMode::LiveUnverified};
    std::uint32_t progress{0};
    std::array<std::uint8_t, 16> profileHash{};
    std::string eventId;
    std::string achievementId;
    std::string gameBuildId;
    std::string runtimeVersion;
    std::string sessionId;
    std::string detail;
};

enum class LedgerStatus : std::uint8_t {
    Ok = 0,
    Duplicate,
    NotLoaded,
    IoError,
    InvalidHeader,
    InvalidRecord,
    LimitExceeded,
};

struct LedgerLoadResult {
    LedgerStatus status{LedgerStatus::Ok};
    std::size_t records{0};
    bool truncatedTail{false};
    std::uint64_t validBytes{0};
    std::string detail;
    explicit operator bool() const noexcept { return status == LedgerStatus::Ok; }
};

class Ledger {
public:
    virtual ~Ledger() = default;
    virtual bool isUnlocked(const std::string &achievementId) const noexcept = 0;
    virtual std::uint32_t progress(const std::string &achievementId) const noexcept = 0;
    virtual LedgerStatus append(LedgerEvent event) = 0;
};

class MemoryLedger final : public Ledger {
public:
    bool isUnlocked(const std::string &achievementId) const noexcept override;
    std::uint32_t progress(const std::string &achievementId) const noexcept override;
    LedgerStatus append(LedgerEvent event) override;
    const std::vector<LedgerEvent> &events() const noexcept { return events_; }

private:
    std::vector<LedgerEvent> events_;
    std::unordered_set<std::string> eventIds_;
    std::unordered_set<std::string> unlocked_;
    std::unordered_map<std::string, std::uint32_t> progress_;
};

class JournalLedger final : public Ledger {
public:
    explicit JournalLedger(std::string path, std::uint32_t maxRecordBytes = 16U * 1024U);

    LedgerLoadResult load();
    bool isUnlocked(const std::string &achievementId) const noexcept override;
    std::uint32_t progress(const std::string &achievementId) const noexcept override;
    LedgerStatus append(LedgerEvent event) override;
    LedgerStatus compact();

    const std::vector<LedgerEvent> &events() const noexcept { return events_; }
    const std::string &path() const noexcept { return path_; }
    bool hadTruncatedTail() const noexcept { return truncatedTail_; }

private:
    LedgerStatus apply(const LedgerEvent &event, bool rejectDuplicates);
    LedgerStatus appendEncoded(const LedgerEvent &event, const std::string &targetPath,
                               bool create) const;

    std::string path_;
    std::uint32_t maxRecordBytes_;
    bool loaded_{false};
    bool truncatedTail_{false};
    std::uint64_t validBytes_{0};
    std::uint64_t nextSequence_{1};
    std::vector<LedgerEvent> events_;
    std::unordered_set<std::string> eventIds_;
    std::unordered_set<std::string> unlocked_;
    std::unordered_map<std::string, std::uint32_t> progress_;
};

} // namespace amun

