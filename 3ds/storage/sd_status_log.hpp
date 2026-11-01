#pragma once

#include <CTRPluginFramework.hpp>

#include <cstddef>
#include <string>

namespace amun::threeds {

// A small diagnostic buffer for the platform bootstrap. Achievement durability
// belongs to the ledger adapter; this class only proves absolute-path SD access and
// provides a concrete flush target for loader lifecycle events.
class SdStatusLog {
public:
    bool initialize() noexcept;
    void appendLine(const char *line) noexcept;
    bool flush() noexcept;
    void close() noexcept;
    bool isReady() const noexcept { return ready_; }

private:
    bool flushLocked() noexcept;

    static constexpr std::size_t kMaximumBufferedBytes = 4096U;
    CTRPluginFramework::File file_;
    CTRPluginFramework::Mutex mutex_;
    std::string pending_;
    bool ready_{false};
};

} // namespace amun::threeds
