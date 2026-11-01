#pragma once

#include "amun/memory.hpp"
#include "amun/types.hpp"

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace amun {

struct TraceReadSample {
    Address address{0};
    std::vector<std::uint8_t> bytes;
};

struct TraceFrame {
    Milliseconds monotonicMs{0};
    std::vector<TraceReadSample> reads;
};

struct TraceData {
    std::uint64_t titleId{0};
    std::array<std::uint8_t, 16> profileHash{};
    std::string buildId;
    std::vector<TraceFrame> frames;
};

struct TraceLimits {
    std::uint32_t maxFileBytes{16U * 1024U * 1024U};
    std::uint32_t maxFrames{1'000'000U};
    std::uint16_t maxReadsPerFrame{2048U};
    std::uint16_t maxReadBytes{4096U};
    std::uint16_t maxBuildIdBytes{256U};
};

bool writeTraceFile(const std::string &path, const TraceData &trace,
                    std::string &error, TraceLimits limits = {});
bool readTraceFile(const std::string &path, TraceData &trace,
                   std::string &error, TraceLimits limits = {});

class RecordingMemoryReader final : public MemoryReader {
public:
    explicit RecordingMemoryReader(MemoryReader &source) : source_(source) {}

    void beginFrame(Milliseconds monotonicMs);
    TraceFrame endFrame();
    ReadResult read(Address address, void *destination, std::size_t size) noexcept override;
    bool isRangeReadable(Address address, std::size_t size) const noexcept override;

private:
    MemoryReader &source_;
    TraceFrame current_;
    bool recording_{false};
};

class ReplayMemoryReader final : public MemoryReader {
public:
    explicit ReplayMemoryReader(std::vector<TraceFrame> frames = {});

    bool seek(std::size_t frameIndex) noexcept;
    bool advance() noexcept;
    std::size_t frameIndex() const noexcept { return frameIndex_; }
    Milliseconds frameTime() const noexcept;
    std::size_t frameCount() const noexcept { return frames_.size(); }

    ReadResult read(Address address, void *destination, std::size_t size) noexcept override;
    bool isRangeReadable(Address address, std::size_t size) const noexcept override;

private:
    const TraceReadSample *find(Address address, std::size_t size) const noexcept;
    std::vector<TraceFrame> frames_;
    std::size_t frameIndex_{0};
};

} // namespace amun

