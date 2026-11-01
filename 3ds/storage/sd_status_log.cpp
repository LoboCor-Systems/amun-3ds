#include "sd_status_log.hpp"

#include "amun/3ds/paths.hpp"

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <limits>

namespace amun::threeds {

namespace {

class MutexGuard {
public:
    explicit MutexGuard(CTRPluginFramework::Mutex &mutex) noexcept : mutex_(mutex) {
        mutex_.Lock();
    }
    ~MutexGuard() { mutex_.Unlock(); }

    MutexGuard(const MutexGuard &) = delete;
    MutexGuard &operator=(const MutexGuard &) = delete;

private:
    CTRPluginFramework::Mutex &mutex_;
};

bool ensureDirectory(const char *absolutePath) noexcept {
    using CTRPluginFramework::Directory;
    const int exists = Directory::IsExists(absolutePath);
    return exists == 1 || (exists == 0 && Directory::Create(absolutePath) == Directory::SUCCESS);
}

} // namespace

bool SdStatusLog::initialize() noexcept {
    MutexGuard guard(mutex_);
    if (ready_) return true;
    if (!ensureDirectory(kRootDirectory) || !ensureDirectory(kPackDirectory) ||
        !ensureDirectory(kLedgerDirectory) || !ensureDirectory(kLogDirectory) ||
        !ensureDirectory(kConfigDirectory)) {
        return false;
    }

    const int mode = CTRPluginFramework::File::WRITE |
                     CTRPluginFramework::File::CREATE |
                     CTRPluginFramework::File::APPEND;
    ready_ = CTRPluginFramework::File::Open(file_, kStatusLogPath, mode) ==
             CTRPluginFramework::File::SUCCESS;
    return ready_;
}

void SdStatusLog::appendLine(const char *line) noexcept {
    if (line == nullptr) return;
    MutexGuard guard(mutex_);
    if (!ready_) return;

    const std::size_t length = std::strlen(line);
    if (!pending_.empty() && pending_.size() + length + 1U > kMaximumBufferedBytes) {
        (void)flushLocked();
    }
    const std::size_t available = pending_.size() < kMaximumBufferedBytes
        ? kMaximumBufferedBytes - pending_.size()
        : 0U;
    if (available <= 1U) return;

    const std::size_t copied = std::min(length, available - 1U);
    pending_.append(line, copied);
    pending_.push_back('\n');
}

bool SdStatusLog::flushLocked() noexcept {
    if (!ready_) return false;
    if (!pending_.empty()) {
        if (pending_.size() > std::numeric_limits<std::uint32_t>::max()) return false;
        if (file_.Write(pending_.data(), static_cast<std::uint32_t>(pending_.size())) !=
            CTRPluginFramework::File::SUCCESS) {
            return false;
        }
        pending_.clear();
    }
    return file_.Flush() == CTRPluginFramework::File::SUCCESS;
}

bool SdStatusLog::flush() noexcept {
    MutexGuard guard(mutex_);
    return flushLocked();
}

void SdStatusLog::close() noexcept {
    MutexGuard guard(mutex_);
    if (!ready_) return;
    (void)flushLocked();
    (void)file_.Close();
    ready_ = false;
}

} // namespace amun::threeds
