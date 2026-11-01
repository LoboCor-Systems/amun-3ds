#include "amun/trace.hpp"

#include "amun/crc32.hpp"

#include <algorithm>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>

namespace amun {

namespace {

constexpr std::size_t kHeaderSize = 40U;
constexpr std::size_t kFrameHeaderSize = 24U;

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
bool getU16(const std::uint8_t *data, std::size_t size, std::size_t at, std::uint16_t &value) noexcept {
    if (at > size || size - at < 2U) return false;
    value = static_cast<std::uint16_t>(data[at]) |
            static_cast<std::uint16_t>(static_cast<std::uint16_t>(data[at + 1U]) << 8U);
    return true;
}
bool getU32(const std::uint8_t *data, std::size_t size, std::size_t at, std::uint32_t &value) noexcept {
    if (at > size || size - at < 4U) return false;
    value = static_cast<std::uint32_t>(data[at]) |
            (static_cast<std::uint32_t>(data[at + 1U]) << 8U) |
            (static_cast<std::uint32_t>(data[at + 2U]) << 16U) |
            (static_cast<std::uint32_t>(data[at + 3U]) << 24U);
    return true;
}
bool getU64(const std::uint8_t *data, std::size_t size, std::size_t at, std::uint64_t &value) noexcept {
    if (at > size || size - at < 8U) return false;
    value = 0;
    for (unsigned i = 0; i < 8U; ++i) value |= static_cast<std::uint64_t>(data[at + i]) << (i * 8U);
    return true;
}

} // namespace

bool writeTraceFile(const std::string &path, const TraceData &trace,
                    std::string &error, TraceLimits limits) {
    error.clear();
    if (trace.frames.size() > limits.maxFrames || trace.buildId.size() > limits.maxBuildIdBytes) {
        error = "trace object limit exceeded";
        return false;
    }
    std::vector<std::uint8_t> output;
    output.reserve(kHeaderSize + trace.buildId.size() + trace.frames.size() * 64U);
    output.insert(output.end(), {'A', 'M', 'T', 'R'});
    putU16(output, 1);
    putU16(output, 0);
    putU64(output, trace.titleId);
    output.insert(output.end(), trace.profileHash.begin(), trace.profileHash.end());
    putU32(output, static_cast<std::uint32_t>(trace.frames.size()));
    putU16(output, static_cast<std::uint16_t>(trace.buildId.size()));
    putU16(output, 0);
    output.insert(output.end(), trace.buildId.begin(), trace.buildId.end());

    for (const TraceFrame &frame : trace.frames) {
        if (frame.reads.size() > limits.maxReadsPerFrame) {
            error = "too many reads in trace frame";
            return false;
        }
        std::vector<std::uint8_t> payload;
        for (const TraceReadSample &sample : frame.reads) {
            if (sample.bytes.empty() || sample.bytes.size() > limits.maxReadBytes) {
                error = "invalid trace read size";
                return false;
            }
            putU32(payload, sample.address);
            putU16(payload, static_cast<std::uint16_t>(sample.bytes.size()));
            putU16(payload, 0);
            payload.insert(payload.end(), sample.bytes.begin(), sample.bytes.end());
        }
        output.insert(output.end(), {'F', 'R', 'A', 'M'});
        putU32(output, static_cast<std::uint32_t>(payload.size()));
        putU64(output, frame.monotonicMs);
        putU16(output, static_cast<std::uint16_t>(frame.reads.size()));
        putU16(output, 0);
        putU32(output, crc32(payload.data(), payload.size()));
        output.insert(output.end(), payload.begin(), payload.end());
        if (output.size() > limits.maxFileBytes) {
            error = "trace exceeds file size limit";
            return false;
        }
    }
    std::error_code filesystemError;
    const std::filesystem::path target(path);
    if (!target.parent_path().empty()) std::filesystem::create_directories(target.parent_path(), filesystemError);
    if (filesystemError) {
        error = "could not create trace directory";
        return false;
    }
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    stream.write(reinterpret_cast<const char *>(output.data()), static_cast<std::streamsize>(output.size()));
    stream.flush();
    if (!stream) {
        error = "could not write trace";
        return false;
    }
    return true;
}

bool readTraceFile(const std::string &path, TraceData &trace,
                   std::string &error, TraceLimits limits) {
    trace = {};
    error.clear();
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream) { error = "could not open trace"; return false; }
    const std::streamoff rawSize = stream.tellg();
    if (rawSize < static_cast<std::streamoff>(kHeaderSize) ||
        static_cast<std::uint64_t>(rawSize) > limits.maxFileBytes) {
        error = "trace file size is invalid";
        return false;
    }
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(rawSize));
    stream.seekg(0, std::ios::beg);
    if (!stream.read(reinterpret_cast<char *>(bytes.data()), rawSize)) {
        error = "could not read trace";
        return false;
    }
    std::uint16_t major = 0, minor = 0, buildLength = 0;
    std::uint32_t frameCount = 0;
    if (std::memcmp(bytes.data(), "AMTR", 4U) != 0 || !getU16(bytes.data(), bytes.size(), 4, major) ||
        !getU16(bytes.data(), bytes.size(), 6, minor) || major != 1 || minor > 0 ||
        !getU64(bytes.data(), bytes.size(), 8, trace.titleId) ||
        !getU32(bytes.data(), bytes.size(), 32, frameCount) ||
        !getU16(bytes.data(), bytes.size(), 36, buildLength) || frameCount > limits.maxFrames ||
        buildLength > limits.maxBuildIdBytes || bytes.size() - kHeaderSize < buildLength) {
        error = "invalid trace header";
        return false;
    }
    std::memcpy(trace.profileHash.data(), bytes.data() + 16U, trace.profileHash.size());
    trace.buildId.assign(reinterpret_cast<const char *>(bytes.data() + kHeaderSize), buildLength);
    std::size_t cursor = kHeaderSize + buildLength;
    trace.frames.reserve(frameCount);
    for (std::uint32_t frameIndex = 0; frameIndex < frameCount; ++frameIndex) {
        if (cursor > bytes.size() || bytes.size() - cursor < kFrameHeaderSize ||
            std::memcmp(bytes.data() + cursor, "FRAM", 4U) != 0) {
            error = "truncated trace frame header";
            return false;
        }
        std::uint32_t payloadSize = 0, expectedCrc = 0;
        std::uint16_t readCount = 0;
        TraceFrame frame;
        if (!getU32(bytes.data(), bytes.size(), cursor + 4U, payloadSize) ||
            !getU64(bytes.data(), bytes.size(), cursor + 8U, frame.monotonicMs) ||
            !getU16(bytes.data(), bytes.size(), cursor + 16U, readCount) ||
            !getU32(bytes.data(), bytes.size(), cursor + 20U, expectedCrc) ||
            readCount > limits.maxReadsPerFrame || bytes.size() - cursor - kFrameHeaderSize < payloadSize) {
            error = "invalid trace frame limits";
            return false;
        }
        const std::uint8_t *payload = bytes.data() + cursor + kFrameHeaderSize;
        if (crc32(payload, payloadSize) != expectedCrc) {
            error = "trace frame checksum mismatch";
            return false;
        }
        std::size_t payloadCursor = 0;
        frame.reads.reserve(readCount);
        for (std::uint16_t readIndex = 0; readIndex < readCount; ++readIndex) {
            TraceReadSample sample;
            std::uint16_t readSize = 0;
            if (!getU32(payload, payloadSize, payloadCursor, sample.address) ||
                !getU16(payload, payloadSize, payloadCursor + 4U, readSize) || readSize == 0 ||
                readSize > limits.maxReadBytes || payloadCursor + 8U > payloadSize ||
                payloadSize - payloadCursor - 8U < readSize) {
                error = "invalid trace read entry";
                return false;
            }
            sample.bytes.assign(payload + payloadCursor + 8U,
                                payload + payloadCursor + 8U + readSize);
            frame.reads.push_back(std::move(sample));
            payloadCursor += 8U + readSize;
        }
        if (payloadCursor != payloadSize) {
            error = "trace frame has trailing payload";
            return false;
        }
        trace.frames.push_back(std::move(frame));
        cursor += kFrameHeaderSize + payloadSize;
    }
    if (cursor != bytes.size()) {
        error = "trace has trailing file data";
        return false;
    }
    return true;
}

void RecordingMemoryReader::beginFrame(Milliseconds monotonicMs) {
    current_ = {};
    current_.monotonicMs = monotonicMs;
    recording_ = true;
}

TraceFrame RecordingMemoryReader::endFrame() {
    recording_ = false;
    return std::move(current_);
}

ReadResult RecordingMemoryReader::read(Address address, void *destination, std::size_t size) noexcept {
    const ReadResult result = source_.read(address, destination, size);
    if (recording_ && result && result.bytesRead == size) {
        TraceReadSample sample;
        sample.address = address;
        const auto *bytes = static_cast<const std::uint8_t *>(destination);
        sample.bytes.assign(bytes, bytes + size);
        current_.reads.push_back(std::move(sample));
    }
    return result;
}

bool RecordingMemoryReader::isRangeReadable(Address address, std::size_t size) const noexcept {
    return source_.isRangeReadable(address, size);
}

ReplayMemoryReader::ReplayMemoryReader(std::vector<TraceFrame> frames) : frames_(std::move(frames)) {}

bool ReplayMemoryReader::seek(std::size_t frameIndex) noexcept {
    if (frameIndex >= frames_.size()) return false;
    frameIndex_ = frameIndex;
    return true;
}

bool ReplayMemoryReader::advance() noexcept {
    if (frames_.empty() || frameIndex_ + 1U >= frames_.size()) return false;
    ++frameIndex_;
    return true;
}

Milliseconds ReplayMemoryReader::frameTime() const noexcept {
    return frames_.empty() ? 0 : frames_[frameIndex_].monotonicMs;
}

const TraceReadSample *ReplayMemoryReader::find(Address address, std::size_t size) const noexcept {
    if (frames_.empty()) return nullptr;
    const std::uint64_t requestedEnd = static_cast<std::uint64_t>(address) + size;
    for (const TraceReadSample &sample : frames_[frameIndex_].reads) {
        const std::uint64_t sampleEnd = static_cast<std::uint64_t>(sample.address) + sample.bytes.size();
        if (address >= sample.address && requestedEnd <= sampleEnd) return &sample;
    }
    return nullptr;
}

ReadResult ReplayMemoryReader::read(Address address, void *destination, std::size_t size) noexcept {
    if (destination == nullptr && size != 0) return {ReadStatus::InvalidRange, 0};
    const TraceReadSample *sample = find(address, size);
    if (sample == nullptr) return {ReadStatus::Unmapped, 0};
    const std::size_t offset = static_cast<std::size_t>(address - sample->address);
    std::memcpy(destination, sample->bytes.data() + offset, size);
    return {ReadStatus::Ok, size};
}

bool ReplayMemoryReader::isRangeReadable(Address address, std::size_t size) const noexcept {
    return find(address, size) != nullptr;
}

} // namespace amun

