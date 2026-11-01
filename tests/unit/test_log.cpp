#include "test.hpp"

#include "amun/log.hpp"

#include <string>

using namespace amun;

namespace {
class StringSink final : public LogSink {
public:
    bool write(const char *data, std::size_t size) noexcept override {
        output.append(data, size);
        ++writes;
        return true;
    }
    bool flush() noexcept override { return true; }
    std::string output;
    unsigned writes{0};
};
}

TEST("buffered logger filters, bounds, and writes one batch") {
    StringSink sink;
    BufferedLogger logger(sink, LogLevel::Info, 128);
    logger.log(LogLevel::Debug, "runtime", "hidden");
    logger.log(LogLevel::Info, "runtime", "started", 10);
    logger.log(LogLevel::Warn, "memory", std::string(200, 'x'), 11);
    EXPECT(logger.droppedMessages() > 0U);
    EXPECT(logger.flush());
    EXPECT_EQ(sink.writes, 1U);
    EXPECT(sink.output.find("hidden") == std::string::npos);
    EXPECT(sink.output.find("started") != std::string::npos);
    EXPECT_EQ(logger.pendingBytes(), 0U);
}
