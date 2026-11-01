#include "amun/3ds/ledger_snapshot.hpp"

#include <utility>

namespace amun::threeds {

namespace {

bool isLater(const LedgerEvent &candidate, const LedgerEvent &known) noexcept {
    if (candidate.sequence != known.sequence) return candidate.sequence > known.sequence;
    return candidate.eventId > known.eventId;
}

bool snapshotOrder(const LedgerEvent &left, const LedgerEvent &right) noexcept {
    if (left.sequence != right.sequence) return left.sequence < right.sequence;
    if (left.type != right.type)
        return static_cast<std::uint8_t>(left.type) < static_cast<std::uint8_t>(right.type);
    if (left.achievementId != right.achievementId)
        return left.achievementId < right.achievementId;
    return left.eventId < right.eventId;
}

void sortSnapshot(std::vector<LedgerEvent> &events) {
    // Accepted console packs cap this at 300 state records. A small insertion sort
    // avoids devkitARM's noisy legacy-ABI std::sort instantiations and is deterministic.
    for (std::size_t i = 1U; i < events.size(); ++i) {
        LedgerEvent value = std::move(events[i]);
        std::size_t cursor = i;
        while (cursor != 0U && snapshotOrder(value, events[cursor - 1U])) {
            events[cursor] = std::move(events[cursor - 1U]);
            --cursor;
        }
        events[cursor] = std::move(value);
    }
}

} // namespace

void LedgerSnapshotState::reset() noexcept {
    eventIds_.clear();
    unlockEvents_.clear();
    progressEvents_.clear();
}

bool LedgerSnapshotState::hasEvent(const std::string &eventId) const noexcept {
    return eventIds_.find(eventId) != eventIds_.end();
}

bool LedgerSnapshotState::isUnlocked(const std::string &achievementId) const noexcept {
    return unlockEvents_.find(achievementId) != unlockEvents_.end();
}

std::uint32_t LedgerSnapshotState::progress(const std::string &achievementId) const noexcept {
    const auto found = progressEvents_.find(achievementId);
    return found == progressEvents_.end() ? 0U : found->second.progress;
}

LedgerStatus LedgerSnapshotState::apply(const LedgerEvent &event, bool rejectDuplicates) {
    if (event.eventId.empty()) return LedgerStatus::InvalidRecord;
    if (hasEvent(event.eventId))
        return rejectDuplicates ? LedgerStatus::Duplicate : LedgerStatus::Ok;
    if (rejectDuplicates && event.type == LedgerEventType::AchievementUnlocked &&
        isUnlocked(event.achievementId)) return LedgerStatus::Duplicate;

    eventIds_.insert(event.eventId);
    if (event.type == LedgerEventType::AchievementUnlocked && !event.achievementId.empty()) {
        auto found = unlockEvents_.find(event.achievementId);
        if (found == unlockEvents_.end()) {
            unlockEvents_.emplace(event.achievementId, event);
        } else if (isLater(event, found->second)) {
            found->second = event;
        }
    } else if (event.type == LedgerEventType::ProgressCheckpoint &&
               !event.achievementId.empty()) {
        auto found = progressEvents_.find(event.achievementId);
        if (found == progressEvents_.end()) {
            progressEvents_.emplace(event.achievementId, event);
        } else if (event.progress > found->second.progress ||
                   (event.progress == found->second.progress && isLater(event, found->second))) {
            // Runtime progress is monotonic. Keeping the maximum also preserves state
            // if a hand-edited or older journal contains a later decreasing record.
            found->second = event;
        }
    }
    return LedgerStatus::Ok;
}

std::size_t LedgerSnapshotState::snapshotRecordCount() const noexcept {
    std::size_t count = unlockEvents_.size();
    for (const auto &entry : progressEvents_) {
        if (!isUnlocked(entry.first)) ++count;
    }
    return count;
}

std::vector<LedgerEvent> LedgerSnapshotState::snapshot() const {
    std::vector<LedgerEvent> retained;
    retained.reserve(snapshotRecordCount());
    for (const auto &entry : unlockEvents_) retained.push_back(entry.second);
    for (const auto &entry : progressEvents_) {
        if (!isUnlocked(entry.first)) retained.push_back(entry.second);
    }
    sortSnapshot(retained);
    std::uint64_t sequence = 1U;
    for (LedgerEvent &event : retained) event.sequence = sequence++;
    return retained;
}

} // namespace amun::threeds
