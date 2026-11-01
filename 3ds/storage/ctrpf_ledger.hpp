#pragma once

#include "amun/3ds/ledger_snapshot.hpp"
#include "amun/ledger.hpp"

#include <CTRPluginFramework.hpp>

#include <cstdint>
#include <string>

namespace amun::threeds {

// JournalLedger's on-disk AMLG/AMLE format implemented on CTRPF's SD archive.
// This avoids pulling std::filesystem into a 3GX while remaining byte-compatible
// with the host ledger and its torn-tail recovery model.
class CtrpfLedger final : public Ledger {
public:
    explicit CtrpfLedger(std::string absolutePath,
                         std::uint32_t maxRecordBytes = 16U * 1024U,
                         std::uint32_t maxFileBytes = 512U * 1024U);

    LedgerLoadResult load() noexcept;
    bool isUnlocked(const std::string &achievementId) const noexcept override;
    std::uint32_t progress(const std::string &achievementId) const noexcept override;
    LedgerStatus append(LedgerEvent event) override;
    LedgerStatus compact();

    bool flush() noexcept;
    bool hadTruncatedTail() const noexcept { return recoveredTail_; }
    const std::string &path() const noexcept { return path_; }

private:
    bool recoverAtomicTransaction() noexcept;
    bool replaceWithTemporary(const std::string &temporary,
                              const std::string &backup) noexcept;
    bool rewriteValidPrefix(const std::uint8_t *bytes, std::size_t count) noexcept;
    LedgerStatus compactLocked();

    std::string path_;
    std::uint32_t maxRecordBytes_;
    std::uint32_t maxFileBytes_;
    bool loaded_{false};
    bool recoveredTail_{false};
    std::uint64_t validBytes_{0};
    std::uint64_t nextSequence_{1};
    std::size_t records_{0};
    LedgerSnapshotState state_;
    mutable CTRPluginFramework::Mutex mutex_;
};

std::string ledgerPathForTitle(std::uint64_t titleId);

} // namespace amun::threeds
