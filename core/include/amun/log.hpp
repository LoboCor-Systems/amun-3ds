#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <string>

namespace amun {

enum class LogLevel : std::uint8_t { Error = 0, Warn, Info, Debug, Trace };

class LogSink {
public:
    virtual ~LogSink() = default;
    virtual bool write(const char *data, std::size_t size) noexcept = 0;
    virtual bool flush() noexcept = 0;
};

class FileLogSink final : public LogSink {
public:
    explicit FileLogSink(std::string path) : path_(std::move(path)) {}
    bool write(const char *data, std::size_t size) noexcept override;
    bool flush() noexcept override;

private:
    std::string path_;
};

class BufferedLogger {
public:
    BufferedLogger(LogSink &sink, LogLevel threshold = LogLevel::Info,
                   std::size_t maximumBufferedBytes = 16U * 1024U);

    void log(LogLevel level, const std::string &subsystem, const std::string &message,
             std::uint64_t monotonicMs = 0);
    bool flush() noexcept;
    std::size_t pendingBytes() const noexcept { return pendingBytes_; }
    std::uint32_t droppedMessages() const noexcept { return droppedMessages_; }
    void setThreshold(LogLevel threshold) noexcept { threshold_ = threshold; }

private:
    LogSink &sink_;
    LogLevel threshold_;
    std::size_t maximumBufferedBytes_;
    std::size_t pendingBytes_{0};
    std::uint32_t droppedMessages_{0};
    std::deque<std::string> pending_;
};

const char *logLevelName(LogLevel level) noexcept;

} // namespace amun

