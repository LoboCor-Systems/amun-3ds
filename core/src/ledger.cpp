#include "amun/ledger.hpp"

#include "amun/crc32.hpp"

#include <algorithm>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>

namespace amun {

namespace {

constexpr char kLedgerMagic[4] = {'A', 'M', 'L', 'G'};
constexpr char kRecordMagic[4] = {'A', 'M', 'L', 'E'};
constexpr std::size_t kLedgerHeaderSize = 8U;
constexpr std::size_t kRecordHeaderSize = 24U;
constexpr std::uint8_t kLedgerMajor = 1;
constexpr std::uint8_t kLedgerMinor = 0;
constexpr std::size_t kFixedPayloadSize = 8U + 1U + 3U + 4U + 16U;
constexpr std::size_t kStringCount = 6U;

void putU16(std::vector<std::uint8_t> &out, std::uint16_t value) {
    out.push_back(static_cast<std::uint8_t>(value & 0xFFU));
    out.push_back(static_cast<std::uint8_t>((value >> 8U) & 0xFFU));
}

void putU32(std::vector<std::uint8_t> &out, std::uint32_t value) {
    for (unsigned i = 0; i < 4U; ++i) out.push_back(static_cast<std::uint8_t>(value >> (i * 8U)));
}

void putU64(std::vector<std::uint8_t> &out, std::uint64_t value) {
    for (unsigned i = 0; i < 8U; ++i) out.push_back(static_cast<std::uint8_t>(value >> (i * 8U)));
}

bool getU16(const std::uint8_t *data, std::size_t size, std::size_t at, std::uint16_t &out) noexcept {
    if (at > size || size - at < 2U) return false;
    out = static_cast<std::uint16_t>(data[at]) |
          static_cast<std::uint16_t>(static_cast<std::uint16_t>(data[at + 1U]) << 8U);
    return true;
}

bool getU32(const std::uint8_t *data, std::size_t size, std::size_t at, std::uint32_t &out) noexcept {
    if (at > size || size - at < 4U) return false;
    out = static_cast<std::uint32_t>(data[at]) |
          (static_cast<std::uint32_t>(data[at + 1U]) << 8U) |
          (static_cast<std::uint32_t>(data[at + 2U]) << 16U) |
          (static_cast<std::uint32_t>(data[at + 3U]) << 24U);
    return true;
}

bool getU64(const std::uint8_t *data, std::size_t size, std::size_t at, std::uint64_t &out) noexcept {
    if (at > size || size - at < 8U) return false;
    out = 0;
    for (unsigned i = 0; i < 8U; ++i) out |= static_cast<std::uint64_t>(data[at + i]) << (i * 8U);
    return true;
}

bool putString(std::vector<std::uint8_t> &out, const std::string &value) {
    if (value.size() > std::numeric_limits<std::uint16_t>::max()) return false;
    putU16(out, static_cast<std::uint16_t>(value.size()));
    out.insert(out.end(), value.begin(), value.end());
    return true;
}

bool getString(const std::uint8_t *data, std::size_t size, std::size_t &cursor,
               std::string &out) {
    std::uint16_t length = 0;
    if (!getU16(data, size, cursor, length)) return false;
    cursor += 2U;
    if (cursor > size || size - cursor < length) return false;
    out.assign(reinterpret_cast<const char *>(data + cursor), length);
    cursor += length;
    return true;
}

bool encodePayload(const LedgerEvent &event, std::uint32_t maxBytes,
                   std::vector<std::uint8_t> &payload) {
    payload.clear();
    payload.reserve(256U);
    putU64(payload, event.wallClockUnixMs);
    payload.push_back(static_cast<std::uint8_t>(event.integrity));
    payload.insert(payload.end(), 3U, 0U);
    putU32(payload, event.progress);
    payload.insert(payload.end(), event.profileHash.begin(), event.profileHash.end());
    const std::string *strings[kStringCount] = {&event.eventId, &event.achievementId,
                                                &event.gameBuildId, &event.runtimeVersion,
                                                &event.sessionId, &event.detail};
    for (const std::string *value : strings) {
        if (!putString(payload, *value)) return false;
    }
    return payload.size() <= maxBytes;
}

bool decodePayload(const std::uint8_t *payload, std::size_t size, LedgerEvent &event) {
    if (size < kFixedPayloadSize || !getU64(payload, size, 0, event.wallClockUnixMs) ||
        !getU32(payload, size, 12, event.progress)) return false;
    if (payload[8] > static_cast<std::uint8_t>(IntegrityMode::SaveScan)) return false;
    event.integrity = static_cast<IntegrityMode>(payload[8]);
    std::memcpy(event.profileHash.data(), payload + 16U, event.profileHash.size());
    std::size_t cursor = kFixedPayloadSize;
    std::string *strings[kStringCount] = {&event.eventId, &event.achievementId,
                                          &event.gameBuildId, &event.runtimeVersion,
                                          &event.sessionId, &event.detail};
    for (std::string *value : strings) {
        if (!getString(payload, size, cursor, *value)) return false;
    }
    return cursor == size && !event.eventId.empty();
}

void updateState(const LedgerEvent &event, std::unordered_set<std::string> &unlocked,
                 std::unordered_map<std::string, std::uint32_t> &progress) {
    if (event.type == LedgerEventType::AchievementUnlocked && !event.achievementId.empty()) {
        unlocked.insert(event.achievementId);
    } else if (event.type == LedgerEventType::ProgressCheckpoint && !event.achievementId.empty()) {
        auto &known = progress[event.achievementId];
        known = std::max(known, event.progress);
    }
}

} // namespace

bool MemoryLedger::isUnlocked(const std::string &achievementId) const noexcept {
    return unlocked_.find(achievementId) != unlocked_.end();
}

std::uint32_t MemoryLedger::progress(const std::string &achievementId) const noexcept {
    const auto it = progress_.find(achievementId);
    return it == progress_.end() ? 0U : it->second;
}

LedgerStatus MemoryLedger::append(LedgerEvent event) {
    if (event.eventId.empty()) return LedgerStatus::InvalidRecord;
    if (eventIds_.find(event.eventId) != eventIds_.end()) return LedgerStatus::Duplicate;
    if (event.type == LedgerEventType::AchievementUnlocked && isUnlocked(event.achievementId))
        return LedgerStatus::Duplicate;
    if (event.sequence == 0) event.sequence = events_.size() + 1U;
    eventIds_.insert(event.eventId);
    updateState(event, unlocked_, progress_);
    events_.push_back(std::move(event));
    return LedgerStatus::Ok;
}

JournalLedger::JournalLedger(std::string path, std::uint32_t maxRecordBytes)
    : path_(std::move(path)), maxRecordBytes_(maxRecordBytes) {}

LedgerLoadResult JournalLedger::load() {
    events_.clear();
    eventIds_.clear();
    unlocked_.clear();
    progress_.clear();
    truncatedTail_ = false;
    validBytes_ = 0;
    nextSequence_ = 1;
    loaded_ = false;

    std::ifstream stream(path_, std::ios::binary | std::ios::ate);
    if (!stream) {
        loaded_ = true; // a missing ledger is a valid empty ledger
        return {LedgerStatus::Ok, 0, false, 0, {}};
    }
    const std::streamoff rawSize = stream.tellg();
    if (rawSize < static_cast<std::streamoff>(kLedgerHeaderSize))
        return {LedgerStatus::InvalidHeader, 0, false, 0, "truncated ledger header"};
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(rawSize));
    stream.seekg(0, std::ios::beg);
    if (!stream.read(reinterpret_cast<char *>(bytes.data()), rawSize))
        return {LedgerStatus::IoError, 0, false, 0, "could not read ledger"};
    if (std::memcmp(bytes.data(), kLedgerMagic, 4U) != 0 || bytes[4] != kLedgerMajor ||
        bytes[5] > kLedgerMinor)
        return {LedgerStatus::InvalidHeader, 0, false, 0, "invalid ledger magic or version"};

    std::size_t cursor = kLedgerHeaderSize;
    validBytes_ = kLedgerHeaderSize;
    while (cursor < bytes.size()) {
        if (bytes.size() - cursor < kRecordHeaderSize) {
            truncatedTail_ = true;
            break;
        }
        if (std::memcmp(bytes.data() + cursor, kRecordMagic, 4U) != 0 || bytes[cursor + 4U] != 1U) {
            truncatedTail_ = true;
            break;
        }
        const std::uint8_t rawType = bytes[cursor + 5U];
        std::uint32_t payloadSize = 0, expectedCrc = 0;
        std::uint64_t sequence = 0;
        if (rawType < static_cast<std::uint8_t>(LedgerEventType::SessionStarted) ||
            rawType > static_cast<std::uint8_t>(LedgerEventType::SyncAcknowledged) ||
            !getU32(bytes.data(), bytes.size(), cursor + 8U, payloadSize) ||
            !getU32(bytes.data(), bytes.size(), cursor + 12U, expectedCrc) ||
            !getU64(bytes.data(), bytes.size(), cursor + 16U, sequence) ||
            payloadSize > maxRecordBytes_ || bytes.size() - cursor - kRecordHeaderSize < payloadSize) {
            truncatedTail_ = true;
            break;
        }
        const std::uint8_t *payload = bytes.data() + cursor + kRecordHeaderSize;
        if (crc32(payload, payloadSize) != expectedCrc) {
            truncatedTail_ = true;
            break;
        }
        LedgerEvent event;
        event.type = static_cast<LedgerEventType>(rawType);
        event.sequence = sequence;
        if (!decodePayload(payload, payloadSize, event)) {
            truncatedTail_ = true;
            break;
        }
        const LedgerStatus applied = apply(event, false);
        if (applied != LedgerStatus::Ok && applied != LedgerStatus::Duplicate)
            return {applied, events_.size(), truncatedTail_, validBytes_, "invalid ledger event"};
        nextSequence_ = std::max(nextSequence_, sequence + 1U);
        cursor += kRecordHeaderSize + payloadSize;
        validBytes_ = cursor;
    }
    loaded_ = true;
    return {LedgerStatus::Ok, events_.size(), truncatedTail_, validBytes_, {}};
}

bool JournalLedger::isUnlocked(const std::string &achievementId) const noexcept {
    return unlocked_.find(achievementId) != unlocked_.end();
}

std::uint32_t JournalLedger::progress(const std::string &achievementId) const noexcept {
    const auto it = progress_.find(achievementId);
    return it == progress_.end() ? 0U : it->second;
}

LedgerStatus JournalLedger::apply(const LedgerEvent &event, bool rejectDuplicates) {
    if (event.eventId.empty()) return LedgerStatus::InvalidRecord;
    if (eventIds_.find(event.eventId) != eventIds_.end())
        return rejectDuplicates ? LedgerStatus::Duplicate : LedgerStatus::Ok;
    if (rejectDuplicates && event.type == LedgerEventType::AchievementUnlocked &&
        isUnlocked(event.achievementId)) return LedgerStatus::Duplicate;
    eventIds_.insert(event.eventId);
    updateState(event, unlocked_, progress_);
    events_.push_back(event);
    return LedgerStatus::Ok;
}

LedgerStatus JournalLedger::appendEncoded(const LedgerEvent &event, const std::string &targetPath,
                                          bool create) const {
    std::vector<std::uint8_t> payload;
    if (!encodePayload(event, maxRecordBytes_, payload)) return LedgerStatus::LimitExceeded;
    std::error_code filesystemError;
    const std::filesystem::path target(targetPath);
    if (!target.parent_path().empty()) std::filesystem::create_directories(target.parent_path(), filesystemError);
    if (filesystemError) return LedgerStatus::IoError;

    std::ofstream stream(targetPath, std::ios::binary | std::ios::app);
    if (!stream) return LedgerStatus::IoError;
    if (create) {
        const std::uint8_t header[kLedgerHeaderSize] = {
            static_cast<std::uint8_t>(kLedgerMagic[0]), static_cast<std::uint8_t>(kLedgerMagic[1]),
            static_cast<std::uint8_t>(kLedgerMagic[2]), static_cast<std::uint8_t>(kLedgerMagic[3]),
            kLedgerMajor, kLedgerMinor, 0, 0};
        stream.write(reinterpret_cast<const char *>(header), sizeof(header));
    }
    std::vector<std::uint8_t> header;
    header.insert(header.end(), std::begin(kRecordMagic), std::end(kRecordMagic));
    header.push_back(1U);
    header.push_back(static_cast<std::uint8_t>(event.type));
    putU16(header, 0);
    putU32(header, static_cast<std::uint32_t>(payload.size()));
    putU32(header, crc32(payload.data(), payload.size()));
    putU64(header, event.sequence);
    stream.write(reinterpret_cast<const char *>(header.data()), static_cast<std::streamsize>(header.size()));
    stream.write(reinterpret_cast<const char *>(payload.data()), static_cast<std::streamsize>(payload.size()));
    stream.flush();
    return stream ? LedgerStatus::Ok : LedgerStatus::IoError;
}

LedgerStatus JournalLedger::append(LedgerEvent event) {
    if (!loaded_) return LedgerStatus::NotLoaded;
    if (event.eventId.empty()) return LedgerStatus::InvalidRecord;
    if (eventIds_.find(event.eventId) != eventIds_.end() ||
        (event.type == LedgerEventType::AchievementUnlocked && isUnlocked(event.achievementId)))
        return LedgerStatus::Duplicate;
    std::error_code errorCode;
    bool create = !std::filesystem::exists(path_, errorCode) || validBytes_ == 0;
    if (errorCode) return LedgerStatus::IoError;
    if (truncatedTail_ && !create) {
        std::filesystem::resize_file(path_, validBytes_, errorCode);
        if (errorCode) return LedgerStatus::IoError;
        truncatedTail_ = false;
    }
    event.sequence = nextSequence_;
    const LedgerStatus written = appendEncoded(event, path_, create);
    if (written != LedgerStatus::Ok) return written;
    ++nextSequence_;
    validBytes_ += (create ? kLedgerHeaderSize : 0U) + kRecordHeaderSize;
    std::vector<std::uint8_t> payload;
    encodePayload(event, maxRecordBytes_, payload);
    validBytes_ += payload.size();
    return apply(event, true);
}

LedgerStatus JournalLedger::compact() {
    if (!loaded_) return LedgerStatus::NotLoaded;
    const std::string temporary = path_ + ".compact.tmp";
    std::error_code errorCode;
    std::filesystem::remove(temporary, errorCode);
    errorCode.clear();

    std::vector<LedgerEvent> retained;
    retained.reserve(unlocked_.size() + progress_.size());
    for (const LedgerEvent &event : events_) {
        if (event.type == LedgerEventType::AchievementUnlocked) retained.push_back(event);
    }
    for (const auto &entry : progress_) {
        if (unlocked_.find(entry.first) != unlocked_.end()) continue;
        auto it = std::find_if(events_.rbegin(), events_.rend(), [&](const LedgerEvent &event) {
            return event.type == LedgerEventType::ProgressCheckpoint && event.achievementId == entry.first;
        });
        if (it != events_.rend()) retained.push_back(*it);
    }
    std::sort(retained.begin(), retained.end(),
              [](const LedgerEvent &a, const LedgerEvent &b) { return a.sequence < b.sequence; });
    bool create = true;
    std::uint64_t sequence = 1;
    for (LedgerEvent &event : retained) {
        event.sequence = sequence++;
        const LedgerStatus status = appendEncoded(event, temporary, create);
        if (status != LedgerStatus::Ok) {
            std::filesystem::remove(temporary, errorCode);
            return status;
        }
        create = false;
    }
    if (retained.empty()) {
        std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
        const std::uint8_t header[kLedgerHeaderSize] = {
            static_cast<std::uint8_t>(kLedgerMagic[0]), static_cast<std::uint8_t>(kLedgerMagic[1]),
            static_cast<std::uint8_t>(kLedgerMagic[2]), static_cast<std::uint8_t>(kLedgerMagic[3]),
            kLedgerMajor, kLedgerMinor, 0, 0};
        stream.write(reinterpret_cast<const char *>(header), sizeof(header));
        stream.flush();
        if (!stream) return LedgerStatus::IoError;
    }
    std::filesystem::path backup(path_ + ".bak");
    std::filesystem::remove(backup, errorCode);
    errorCode.clear();
    if (std::filesystem::exists(path_)) {
        std::filesystem::rename(path_, backup, errorCode);
        if (errorCode) return LedgerStatus::IoError;
    }
    std::filesystem::rename(temporary, path_, errorCode);
    if (errorCode) {
        std::error_code rollback;
        if (std::filesystem::exists(backup)) std::filesystem::rename(backup, path_, rollback);
        return LedgerStatus::IoError;
    }
    return load().status;
}

} // namespace amun

