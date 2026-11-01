#include "ctrpf_ledger.hpp"

#include "amun/3ds/paths.hpp"
#include "amun/crc32.hpp"

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <limits>
#include <utility>
#include <vector>

namespace amun::threeds {

namespace {

constexpr std::array<std::uint8_t, 8> kLedgerHeader{{'A', 'M', 'L', 'G', 1U, 0U, 0U, 0U}};
constexpr char kRecordMagic[4] = {'A', 'M', 'L', 'E'};
constexpr std::size_t kRecordHeaderSize = 24U;
constexpr std::size_t kFixedPayloadSize = 32U;
constexpr std::size_t kStringCount = 6U;
constexpr std::size_t kMaximumRecords = 4096U;
constexpr std::size_t kPeriodicRecordThreshold = (kMaximumRecords * 3U) / 4U;
constexpr std::size_t kMinimumDiscardableRecords = 64U;

class MutexGuard {
public:
    explicit MutexGuard(CTRPluginFramework::Mutex &mutex) noexcept : mutex_(mutex) { mutex_.Lock(); }
    ~MutexGuard() { mutex_.Unlock(); }
    MutexGuard(const MutexGuard &) = delete;
    MutexGuard &operator=(const MutexGuard &) = delete;
private:
    CTRPluginFramework::Mutex &mutex_;
};

void putU16(std::vector<std::uint8_t> &out, std::uint16_t value) {
    out.push_back(static_cast<std::uint8_t>(value));
    out.push_back(static_cast<std::uint8_t>(value >> 8U));
}

void putU32(std::vector<std::uint8_t> &out, std::uint32_t value) {
    for (unsigned i = 0; i < 4U; ++i) out.push_back(static_cast<std::uint8_t>(value >> (i * 8U)));
}

void putU64(std::vector<std::uint8_t> &out, std::uint64_t value) {
    for (unsigned i = 0; i < 8U; ++i) out.push_back(static_cast<std::uint8_t>(value >> (i * 8U)));
}

bool getU16(const std::uint8_t *data, std::size_t size, std::size_t at,
            std::uint16_t &out) noexcept {
    if (at > size || size - at < 2U) return false;
    out = static_cast<std::uint16_t>(data[at]) |
          static_cast<std::uint16_t>(static_cast<std::uint16_t>(data[at + 1U]) << 8U);
    return true;
}

bool getU32(const std::uint8_t *data, std::size_t size, std::size_t at,
            std::uint32_t &out) noexcept {
    if (at > size || size - at < 4U) return false;
    out = static_cast<std::uint32_t>(data[at]) |
          (static_cast<std::uint32_t>(data[at + 1U]) << 8U) |
          (static_cast<std::uint32_t>(data[at + 2U]) << 16U) |
          (static_cast<std::uint32_t>(data[at + 3U]) << 24U);
    return true;
}

bool getU64(const std::uint8_t *data, std::size_t size, std::size_t at,
            std::uint64_t &out) noexcept {
    if (at > size || size - at < 8U) return false;
    out = 0U;
    for (unsigned i = 0; i < 8U; ++i)
        out |= static_cast<std::uint64_t>(data[at + i]) << (i * 8U);
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
    std::uint16_t length = 0U;
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
    const std::string *strings[kStringCount] = {
        &event.eventId, &event.achievementId, &event.gameBuildId,
        &event.runtimeVersion, &event.sessionId, &event.detail};
    for (const std::string *value : strings) {
        if (!putString(payload, *value)) return false;
    }
    return payload.size() <= maxBytes;
}

bool encodeRecordHeader(const LedgerEvent &event, const std::vector<std::uint8_t> &payload,
                        std::vector<std::uint8_t> &header) {
    const std::uint8_t rawType = static_cast<std::uint8_t>(event.type);
    if (rawType < static_cast<std::uint8_t>(LedgerEventType::SessionStarted) ||
        rawType > static_cast<std::uint8_t>(LedgerEventType::SyncAcknowledged) ||
        event.sequence == 0U || event.sequence == std::numeric_limits<std::uint64_t>::max() ||
        payload.size() > std::numeric_limits<std::uint32_t>::max()) return false;
    header.clear();
    header.reserve(kRecordHeaderSize);
    header.insert(header.end(), std::begin(kRecordMagic), std::end(kRecordMagic));
    header.push_back(1U);
    header.push_back(rawType);
    putU16(header, 0U);
    putU32(header, static_cast<std::uint32_t>(payload.size()));
    putU32(header, crc32(payload.data(), payload.size()));
    putU64(header, event.sequence);
    return header.size() == kRecordHeaderSize;
}

bool decodePayload(const std::uint8_t *payload, std::size_t size, LedgerEvent &event) {
    if (size < kFixedPayloadSize || !getU64(payload, size, 0U, event.wallClockUnixMs) ||
        !getU32(payload, size, 12U, event.progress) ||
        payload[8U] > static_cast<std::uint8_t>(IntegrityMode::SaveScan)) return false;
    event.integrity = static_cast<IntegrityMode>(payload[8U]);
    std::memcpy(event.profileHash.data(), payload + 16U, event.profileHash.size());
    std::size_t cursor = kFixedPayloadSize;
    std::string *strings[kStringCount] = {
        &event.eventId, &event.achievementId, &event.gameBuildId,
        &event.runtimeVersion, &event.sessionId, &event.detail};
    for (std::string *value : strings) {
        if (!getString(payload, size, cursor, *value)) return false;
    }
    return cursor == size && !event.eventId.empty();
}

bool writeExact(CTRPluginFramework::File &file, const void *data, std::size_t size) noexcept {
    if (size > std::numeric_limits<std::uint32_t>::max()) return false;
    const std::uint64_t before = file.Tell();
    return file.Write(data, static_cast<std::uint32_t>(size)) == CTRPluginFramework::File::SUCCESS &&
           file.Tell() == before + size;
}

} // namespace

std::string ledgerPathForTitle(std::uint64_t titleId) {
    char path[kPlatformPathCapacity]{};
    std::snprintf(path, sizeof(path), "%s/%016llX.amunledger", kLedgerDirectory,
                  static_cast<unsigned long long>(titleId));
    return path;
}

CtrpfLedger::CtrpfLedger(std::string absolutePath, std::uint32_t maxRecordBytes,
                         std::uint32_t maxFileBytes)
    : path_(std::move(absolutePath)), maxRecordBytes_(maxRecordBytes),
      maxFileBytes_(maxFileBytes) {}

LedgerLoadResult CtrpfLedger::load() noexcept {
    MutexGuard guard(mutex_);
    state_.reset();
    loaded_ = false;
    recoveredTail_ = false;
    validBytes_ = 0U;
    nextSequence_ = 1U;
    records_ = 0U;

    if (path_.empty() || path_[0] != '/')
        return {LedgerStatus::IoError, 0U, false, 0U, "ledger path is not absolute"};
    if (!recoverAtomicTransaction())
        return {LedgerStatus::IoError, 0U, false, 0U,
                "could not roll back an interrupted ledger transaction"};
    if (CTRPluginFramework::File::Exists(path_) != 1) {
        loaded_ = true;
        return {LedgerStatus::Ok, 0U, false, 0U, {}};
    }

    CTRPluginFramework::File file;
    if (CTRPluginFramework::File::Open(file, path_, CTRPluginFramework::File::READ) !=
        CTRPluginFramework::File::SUCCESS)
        return {LedgerStatus::IoError, 0U, false, 0U, "could not open ledger"};
    const std::uint64_t rawSize = file.GetSize();
    if (rawSize < kLedgerHeader.size())
        return {LedgerStatus::InvalidHeader, 0U, false, 0U, "truncated ledger header"};
    if (rawSize > maxFileBytes_ || rawSize > std::numeric_limits<std::uint32_t>::max())
        return {LedgerStatus::LimitExceeded, 0U, false, 0U, "ledger exceeds file bound"};

    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(rawSize));
    if (file.Read(bytes.data(), static_cast<std::uint32_t>(bytes.size())) !=
            CTRPluginFramework::File::SUCCESS || file.Tell() != rawSize)
        return {LedgerStatus::IoError, 0U, false, 0U, "short or failed ledger read"};
    (void)file.Close();
    if (!std::equal(kLedgerHeader.begin(), kLedgerHeader.end(), bytes.begin()))
        return {LedgerStatus::InvalidHeader, 0U, false, 0U, "invalid ledger magic or version"};

    std::size_t cursor = kLedgerHeader.size();
    validBytes_ = kLedgerHeader.size();
    bool tornTail = false;
    while (cursor < bytes.size()) {
        if (records_ >= kMaximumRecords)
            return {LedgerStatus::LimitExceeded, records_, false, validBytes_,
                    "ledger record-count bound exceeded"};
        if (bytes.size() - cursor < kRecordHeaderSize ||
            std::memcmp(bytes.data() + cursor, kRecordMagic, 4U) != 0 ||
            bytes[cursor + 4U] != 1U) {
            tornTail = true;
            break;
        }
        const std::uint8_t rawType = bytes[cursor + 5U];
        std::uint32_t payloadSize = 0U;
        std::uint32_t expectedCrc = 0U;
        std::uint64_t sequence = 0U;
        if (rawType < static_cast<std::uint8_t>(LedgerEventType::SessionStarted) ||
            rawType > static_cast<std::uint8_t>(LedgerEventType::SyncAcknowledged) ||
            !getU32(bytes.data(), bytes.size(), cursor + 8U, payloadSize) ||
            !getU32(bytes.data(), bytes.size(), cursor + 12U, expectedCrc) ||
            !getU64(bytes.data(), bytes.size(), cursor + 16U, sequence) ||
            sequence == 0U || sequence == std::numeric_limits<std::uint64_t>::max() ||
            payloadSize > maxRecordBytes_ ||
            bytes.size() - cursor - kRecordHeaderSize < payloadSize) {
            tornTail = true;
            break;
        }
        const std::uint8_t *payload = bytes.data() + cursor + kRecordHeaderSize;
        LedgerEvent event;
        event.type = static_cast<LedgerEventType>(rawType);
        event.sequence = sequence;
        if (crc32(payload, payloadSize) != expectedCrc ||
            !decodePayload(payload, payloadSize, event)) {
            tornTail = true;
            break;
        }
        const LedgerStatus applied = state_.apply(event, false);
        if (applied != LedgerStatus::Ok && applied != LedgerStatus::Duplicate)
            return {applied, records_, false, validBytes_, "invalid ledger event"};
        nextSequence_ = std::max(nextSequence_, sequence + 1U);
        ++records_;
        cursor += kRecordHeaderSize + payloadSize;
        validBytes_ = cursor;
    }

    if (tornTail && !rewriteValidPrefix(bytes.data(), static_cast<std::size_t>(validBytes_)))
        return {LedgerStatus::IoError, records_, true, validBytes_,
                "valid prefix found but atomic tail recovery failed"};
    recoveredTail_ = tornTail;
    loaded_ = true;
    return {LedgerStatus::Ok, records_, tornTail, validBytes_, {}};
}

bool CtrpfLedger::recoverAtomicTransaction() noexcept {
    const std::string temporary = path_ + ".atomic.tmp";
    const std::string backup = path_ + ".atomic.bak";
    if (CTRPluginFramework::File::Exists(backup) == 1) {
        // A backup exists only between the two rename operations. Always prefer the
        // original full journal after a reboot; compaction can be retried later.
        if (CTRPluginFramework::File::Exists(path_) == 1 &&
            CTRPluginFramework::File::Remove(path_) != CTRPluginFramework::File::SUCCESS)
            return false;
        if (CTRPluginFramework::File::Rename(backup, path_) !=
            CTRPluginFramework::File::SUCCESS) return false;
    }
    if (CTRPluginFramework::File::Exists(temporary) == 1 &&
        CTRPluginFramework::File::Remove(temporary) != CTRPluginFramework::File::SUCCESS)
        return false;
    return true;
}

bool CtrpfLedger::replaceWithTemporary(const std::string &temporary,
                                       const std::string &backup) noexcept {
    if (CTRPluginFramework::File::Exists(backup) == 1 &&
        CTRPluginFramework::File::Remove(backup) != CTRPluginFramework::File::SUCCESS)
        return false;
    const bool hadOriginal = CTRPluginFramework::File::Exists(path_) == 1;
    if (hadOriginal && CTRPluginFramework::File::Rename(path_, backup) !=
                           CTRPluginFramework::File::SUCCESS) return false;
    if (CTRPluginFramework::File::Rename(temporary, path_) !=
        CTRPluginFramework::File::SUCCESS) {
        if (hadOriginal && CTRPluginFramework::File::Rename(backup, path_) !=
                               CTRPluginFramework::File::SUCCESS) {
            // Leave the backup for load()-time recovery and fail closed.
        }
        return false;
    }
    if (hadOriginal && CTRPluginFramework::File::Remove(backup) !=
                           CTRPluginFramework::File::SUCCESS) {
        // Do not permit later appends while a rollback marker exists. The next load
        // restores the original journal, so no committed unlock can be lost.
        return false;
    }
    return true;
}

bool CtrpfLedger::rewriteValidPrefix(const std::uint8_t *bytes, std::size_t count) noexcept {
    const std::string temporary = path_ + ".atomic.tmp";
    const std::string backup = path_ + ".atomic.bak";
    if (CTRPluginFramework::File::Exists(temporary) == 1 &&
        CTRPluginFramework::File::Remove(temporary) != CTRPluginFramework::File::SUCCESS)
        return false;

    CTRPluginFramework::File output;
    const int mode = CTRPluginFramework::File::WRITE | CTRPluginFramework::File::CREATE |
                     CTRPluginFramework::File::TRUNCATE;
    if (CTRPluginFramework::File::Open(output, temporary, mode) !=
        CTRPluginFramework::File::SUCCESS) return false;
    const bool written = writeExact(output, bytes, count) &&
                         output.Flush() == CTRPluginFramework::File::SUCCESS;
    (void)output.Close();
    if (!written) {
        (void)CTRPluginFramework::File::Remove(temporary);
        return false;
    }

    if (replaceWithTemporary(temporary, backup)) return true;
    (void)CTRPluginFramework::File::Remove(temporary);
    return false;
}

bool CtrpfLedger::isUnlocked(const std::string &achievementId) const noexcept {
    MutexGuard guard(mutex_);
    return state_.isUnlocked(achievementId);
}

std::uint32_t CtrpfLedger::progress(const std::string &achievementId) const noexcept {
    MutexGuard guard(mutex_);
    return state_.progress(achievementId);
}

LedgerStatus CtrpfLedger::append(LedgerEvent event) {
    MutexGuard guard(mutex_);
    if (!loaded_) return LedgerStatus::NotLoaded;
    if (event.eventId.empty()) return LedgerStatus::InvalidRecord;
    if (state_.hasEvent(event.eventId) ||
        (event.type == LedgerEventType::AchievementUnlocked &&
         state_.isUnlocked(event.achievementId))) return LedgerStatus::Duplicate;

    std::vector<std::uint8_t> payload;
    if (!encodePayload(event, maxRecordBytes_, payload)) return LedgerStatus::LimitExceeded;
    bool exists = CTRPluginFramework::File::Exists(path_) == 1;
    if (validBytes_ != 0U && !exists) return LedgerStatus::IoError;
    bool create = validBytes_ == 0U;
    std::uint64_t appendedBytes = (create ? kLedgerHeader.size() : 0U) +
                                  kRecordHeaderSize + payload.size();
    const bool wouldExceedRecords = records_ >= kMaximumRecords;
    const bool wouldExceedBytes = validBytes_ > maxFileBytes_ ||
                                  appendedBytes > maxFileBytes_ - validBytes_;
    const std::size_t snapshotRecords = state_.snapshotRecordCount();
    const std::size_t discardableRecords =
        records_ > snapshotRecords ? records_ - snapshotRecords : 0U;
    const std::uint64_t byteThreshold =
        (static_cast<std::uint64_t>(maxFileBytes_) * 3U) / 4U;
    const bool periodicCompaction = discardableRecords >= kMinimumDiscardableRecords &&
        (records_ >= kPeriodicRecordThreshold || validBytes_ >= byteThreshold);
    if (periodicCompaction || wouldExceedRecords || wouldExceedBytes) {
        const LedgerStatus compacted = compactLocked();
        if (compacted != LedgerStatus::Ok) return compacted;
        exists = CTRPluginFramework::File::Exists(path_) == 1;
        create = validBytes_ == 0U;
        appendedBytes = (create ? kLedgerHeader.size() : 0U) +
                        kRecordHeaderSize + payload.size();
    }
    if (records_ >= kMaximumRecords || validBytes_ > maxFileBytes_ ||
        appendedBytes > maxFileBytes_ - validBytes_) return LedgerStatus::LimitExceeded;
    if (validBytes_ != 0U && !exists) return LedgerStatus::IoError;

    event.sequence = nextSequence_;
    std::vector<std::uint8_t> header;
    if (!encodeRecordHeader(event, payload, header)) return LedgerStatus::InvalidRecord;

    std::vector<std::uint8_t> record;
    record.reserve(static_cast<std::size_t>(appendedBytes));
    if (create) record.insert(record.end(), kLedgerHeader.begin(), kLedgerHeader.end());
    record.insert(record.end(), header.begin(), header.end());
    record.insert(record.end(), payload.begin(), payload.end());
    if (record.size() != appendedBytes) return LedgerStatus::InvalidRecord;

    CTRPluginFramework::File file;
    const int mode = CTRPluginFramework::File::WRITE | CTRPluginFramework::File::CREATE |
                     CTRPluginFramework::File::APPEND;
    if (CTRPluginFramework::File::Open(file, path_, mode) != CTRPluginFramework::File::SUCCESS)
        return LedgerStatus::IoError;
    // CTRPF APPEND seeks to EOF only inside Write(). Its cursor is still zero
    // immediately after Open(), so writeExact() would otherwise reject the first
    // append to every existing journal after the bytes had already been written.
    // Establish and verify the expected EOF first, then issue the complete record
    // in one write so a failure cannot strand a valid header without its payload.
    bool written = file.Seek(0, CTRPluginFramework::File::END) ==
                       CTRPluginFramework::File::SUCCESS &&
                   file.Tell() == validBytes_ &&
                   writeExact(file, record.data(), record.size()) &&
                   file.Flush() == CTRPluginFramework::File::SUCCESS;
    (void)file.Close();
    if (!written) {
        // A short/torn append is recovered on the next load. Stop this session from
        // appending behind the damaged tail, which would make later valid records
        // unreachable during replay.
        loaded_ = false;
        return LedgerStatus::IoError;
    }

    const LedgerStatus applied = state_.apply(event, true);
    if (applied != LedgerStatus::Ok) return applied;
    ++nextSequence_;
    ++records_;
    validBytes_ += appendedBytes;
    return LedgerStatus::Ok;
}

LedgerStatus CtrpfLedger::compactLocked() {
    if (!loaded_) return LedgerStatus::NotLoaded;
    std::vector<LedgerEvent> retained = state_.snapshot();
    if (retained.size() > kMaximumRecords) return LedgerStatus::LimitExceeded;

    const std::string temporary = path_ + ".atomic.tmp";
    const std::string backup = path_ + ".atomic.bak";
    if (CTRPluginFramework::File::Exists(temporary) == 1 &&
        CTRPluginFramework::File::Remove(temporary) != CTRPluginFramework::File::SUCCESS)
        return LedgerStatus::IoError;

    CTRPluginFramework::File output;
    const int mode = CTRPluginFramework::File::WRITE | CTRPluginFramework::File::CREATE |
                     CTRPluginFramework::File::TRUNCATE;
    if (CTRPluginFramework::File::Open(output, temporary, mode) !=
        CTRPluginFramework::File::SUCCESS) return LedgerStatus::IoError;

    std::uint64_t compactedBytes = kLedgerHeader.size();
    LedgerStatus failure = LedgerStatus::Ok;
    if (compactedBytes > maxFileBytes_) {
        failure = LedgerStatus::LimitExceeded;
    } else if (!writeExact(output, kLedgerHeader.data(), kLedgerHeader.size())) {
        failure = LedgerStatus::IoError;
    }
    std::vector<std::uint8_t> payload;
    std::vector<std::uint8_t> header;
    for (const LedgerEvent &event : retained) {
        if (failure != LedgerStatus::Ok) break;
        if (!encodePayload(event, maxRecordBytes_, payload)) {
            failure = LedgerStatus::LimitExceeded;
            break;
        }
        if (!encodeRecordHeader(event, payload, header)) {
            failure = LedgerStatus::InvalidRecord;
            break;
        }
        const std::uint64_t recordBytes = header.size() + payload.size();
        if (compactedBytes > maxFileBytes_ || recordBytes > maxFileBytes_ - compactedBytes) {
            failure = LedgerStatus::LimitExceeded;
            break;
        }
        if (!writeExact(output, header.data(), header.size()) ||
            !writeExact(output, payload.data(), payload.size())) {
            failure = LedgerStatus::IoError;
            break;
        }
        compactedBytes += recordBytes;
    }
    if (failure == LedgerStatus::Ok &&
        output.Flush() != CTRPluginFramework::File::SUCCESS) failure = LedgerStatus::IoError;
    (void)output.Close();
    if (failure != LedgerStatus::Ok) {
        (void)CTRPluginFramework::File::Remove(temporary);
        return failure;
    }
    if (!replaceWithTemporary(temporary, backup)) {
        loaded_ = false;
        (void)CTRPluginFramework::File::Remove(temporary);
        return LedgerStatus::IoError;
    }

    state_.reset();
    for (const LedgerEvent &event : retained) {
        if (state_.apply(event, false) != LedgerStatus::Ok) {
            loaded_ = false;
            return LedgerStatus::InvalidRecord;
        }
    }
    records_ = retained.size();
    validBytes_ = compactedBytes;
    nextSequence_ = static_cast<std::uint64_t>(records_) + 1U;
    recoveredTail_ = false;
    return LedgerStatus::Ok;
}

LedgerStatus CtrpfLedger::compact() {
    MutexGuard guard(mutex_);
    return compactLocked();
}

bool CtrpfLedger::flush() noexcept {
    MutexGuard guard(mutex_);
    // append() flushes and closes each record before publishing it in memory.
    return true;
}

} // namespace amun::threeds
