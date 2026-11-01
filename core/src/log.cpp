#include "amun/log.hpp"

#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>

namespace amun {

const char *logLevelName(LogLevel level) noexcept {
    switch (level) {
    case LogLevel::Error: return "ERROR";
    case LogLevel::Warn: return "WARN";
    case LogLevel::Info: return "INFO";
    case LogLevel::Debug: return "DEBUG";
    case LogLevel::Trace: return "TRACE";
    }
    return "UNKNOWN";
}

bool FileLogSink::write(const char *data, std::size_t size) noexcept {
    try {
        const std::filesystem::path path(path_);
        std::error_code error;
        if (!path.parent_path().empty()) std::filesystem::create_directories(path.parent_path(), error);
        if (error) return false;
        std::ofstream stream(path_, std::ios::binary | std::ios::app);
        if (!stream) return false;
        stream.write(data, static_cast<std::streamsize>(size));
        return static_cast<bool>(stream);
    } catch (...) {
        return false;
    }
}

bool FileLogSink::flush() noexcept {
    // Each bounded batch is closed after write(), so the C++ stream buffer is already flushed.
    return true;
}

BufferedLogger::BufferedLogger(LogSink &sink, LogLevel threshold,
                               std::size_t maximumBufferedBytes)
    : sink_(sink), threshold_(threshold), maximumBufferedBytes_(maximumBufferedBytes) {}

void BufferedLogger::log(LogLevel level, const std::string &subsystem,
                         const std::string &message, std::uint64_t monotonicMs) {
    if (static_cast<unsigned>(level) > static_cast<unsigned>(threshold_)) return;
    std::ostringstream formatted;
    formatted << '[' << std::setw(10) << monotonicMs << "] [" << logLevelName(level) << "] ["
              << subsystem.substr(0, 32) << "] " << message.substr(0, 1024) << '\n';
    std::string line = formatted.str();
    if (line.size() > maximumBufferedBytes_) {
        ++droppedMessages_;
        return;
    }
    while (!pending_.empty() && pendingBytes_ + line.size() > maximumBufferedBytes_) {
        pendingBytes_ -= pending_.front().size();
        pending_.pop_front();
        ++droppedMessages_;
    }
    pendingBytes_ += line.size();
    pending_.push_back(std::move(line));
}

bool BufferedLogger::flush() noexcept {
    if (pending_.empty()) return sink_.flush();
    try {
        std::string batch;
        batch.reserve(pendingBytes_);
        for (const std::string &line : pending_) batch += line;
        if (!sink_.write(batch.data(), batch.size()) || !sink_.flush()) return false;
        pending_.clear();
        pendingBytes_ = 0;
        return true;
    } catch (...) {
        return false;
    }
}

} // namespace amun
