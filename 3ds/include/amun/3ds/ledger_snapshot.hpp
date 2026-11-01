#pragma once

#include "amun/ledger.hpp"

#include <cstddef>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace amun::threeds {

// Platform-neutral retained state for bounded journal compaction. Session and sync
// records remain append-only history; a snapshot keeps one effective state record
// per achievement and deterministically resequences it.
class LedgerSnapshotState {
public:
    void reset() noexcept;
    bool hasEvent(const std::string &eventId) const noexcept;
    bool isUnlocked(const std::string &achievementId) const noexcept;
    std::uint32_t progress(const std::string &achievementId) const noexcept;
    LedgerStatus apply(const LedgerEvent &event, bool rejectDuplicates);

    std::size_t snapshotRecordCount() const noexcept;
    std::vector<LedgerEvent> snapshot() const;

private:
    std::unordered_set<std::string> eventIds_;
    std::unordered_map<std::string, LedgerEvent> unlockEvents_;
    std::unordered_map<std::string, LedgerEvent> progressEvents_;
};

} // namespace amun::threeds
