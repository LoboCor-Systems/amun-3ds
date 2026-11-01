#include "test.hpp"

#include "amun/memory.hpp"
#include "amun/trace.hpp"

#include <array>
#include <limits>
#include <cstring>
#include <filesystem>
#include <fstream>

using namespace amun;

TEST("synthetic memory rejects invalid spans and preserves little endian bytes") {
    SyntheticMemoryReader memory;
    EXPECT(memory.map(0x1000, 16));
    EXPECT(!memory.map(0x1008, 16));
    EXPECT(memory.writeLittleEndian<std::uint32_t>(0x1004, 0x78563412U));
    std::array<std::uint8_t, 4> bytes{};
    EXPECT(memory.read(0x1004, bytes.data(), bytes.size()));
    EXPECT_EQ(bytes[0], 0x12U);
    EXPECT_EQ(bytes[3], 0x78U);
    EXPECT(!memory.read(0x0FFF, bytes.data(), bytes.size()));
    EXPECT(memory.setReadable(0x1000, false));
    EXPECT(!memory.read(0x1004, bytes.data(), bytes.size()));
}

TEST("all required scalar types decode explicitly as little endian") {
    Scalar value;
    const std::uint8_t u16[] = {0x34, 0x12};
    EXPECT(decodeScalarLittleEndian(ValueType::U16, u16, sizeof(u16), value));
    EXPECT_EQ(value.integer, 0x1234);
    const std::uint8_t s16[] = {0xFE, 0xFF};
    EXPECT(decodeScalarLittleEndian(ValueType::S16, s16, sizeof(s16), value));
    EXPECT_EQ(value.integer, -2);
    const std::uint8_t u32[] = {0x78, 0x56, 0x34, 0x12};
    EXPECT(decodeScalarLittleEndian(ValueType::U32, u32, sizeof(u32), value));
    EXPECT_EQ(value.integer, 0x12345678);
    const std::uint8_t f32[] = {0x00, 0x00, 0xC0, 0x3F};
    EXPECT(decodeScalarLittleEndian(ValueType::F32, f32, sizeof(f32), value));
    EXPECT(value.floating == 1.5F);
    EXPECT_EQ(scalarWidth(ValueType::U8), 1U);
    EXPECT_EQ(scalarWidth(ValueType::S32), 4U);
    const std::uint8_t sequence[] = {0x41, 0x4D, 0x55, 0x4E};
    EXPECT(decodeScalarLittleEndian(ValueType::Bytes, sequence, sizeof(sequence), value));
    EXPECT_EQ(value.kind, Scalar::Kind::Bytes);
    EXPECT_EQ(value.byteCount, 4U);
}

TEST("non-finite game floats are rejected before VM numeric conversion") {
    Scalar value;
    const std::uint8_t positiveInfinity[] = {0x00, 0x00, 0x80, 0x7F};
    const std::uint8_t quietNan[] = {0x00, 0x00, 0xC0, 0x7F};
    EXPECT(!decodeScalarLittleEndian(ValueType::F32, positiveInfinity,
                                     sizeof(positiveInfinity), value));
    EXPECT(!decodeScalarLittleEndian(ValueType::F32, quietNan, sizeof(quietNan), value));
    EXPECT_EQ(Scalar::fromFloat(std::numeric_limits<float>::infinity()).asInteger(), 0);
}

TEST("pattern scan handles wildcards, absence, and ambiguity") {
    SyntheticMemoryReader memory;
    EXPECT(memory.map(0x2000, 64));
    const std::uint8_t first[] = {0x12, 0x34, 0x99, 0x78};
    EXPECT(memory.write(0x2005, first, sizeof(first)));
    PatternSpec pattern{0x2000, 64, {0x12, 0x34, 0x00, 0x78}, {1, 1, 0, 1}, 2};
    PatternResult result = scanPattern(memory, pattern, 8);
    EXPECT_EQ(result.status, PatternStatus::Found);
    EXPECT_EQ(result.address, 0x2007U);
    EXPECT(memory.write(0x2020, first, sizeof(first)));
    result = scanPattern(memory, pattern, 8);
    EXPECT_EQ(result.status, PatternStatus::Ambiguous);
    pattern.bytes[0] = 0xFF;
    result = scanPattern(memory, pattern, 8);
    EXPECT_EQ(result.status, PatternStatus::NotFound);
}

TEST("recording and replay readers preserve bounded reads") {
    SyntheticMemoryReader source;
    EXPECT(source.map(0x3000, 8));
    const std::uint8_t data[] = {1, 2, 3, 4};
    EXPECT(source.write(0x3002, data, sizeof(data)));
    RecordingMemoryReader recorder(source);
    recorder.beginFrame(50);
    std::uint8_t read[4]{};
    EXPECT(recorder.read(0x3002, read, sizeof(read)));
    std::vector<TraceFrame> frames{recorder.endFrame()};
    ReplayMemoryReader replay(std::move(frames));
    std::memset(read, 0, sizeof(read));
    EXPECT(replay.read(0x3002, read, sizeof(read)));
    EXPECT_EQ(read[2], 3U);
    EXPECT(!replay.read(0x3000, read, sizeof(read)));
}

TEST("trace files round-trip and reject corrupted frame payloads") {
    TraceData trace;
    trace.titleId = 0x000400000ABCDEF0ULL;
    trace.buildId = "synthetic";
    trace.frames.push_back({123, {{0x08000000U, {1, 2, 3, 4}}}});
    const auto path = std::filesystem::temp_directory_path() / "amun-trace-test.amuntrace";
    std::string error;
    EXPECT(writeTraceFile(path.string(), trace, error));
    TraceData loaded;
    EXPECT(readTraceFile(path.string(), loaded, error));
    EXPECT_EQ(loaded.frames.size(), 1U);
    EXPECT_EQ(loaded.frames[0].reads[0].bytes[3], 4U);
    {
        std::fstream stream(path, std::ios::binary | std::ios::in | std::ios::out);
        stream.seekp(-1, std::ios::end);
        char value = 0;
        stream.write(&value, 1);
    }
    EXPECT(!readTraceFile(path.string(), loaded, error));
    EXPECT(error.find("checksum") != std::string::npos);
    std::error_code ignored;
    std::filesystem::remove(path, ignored);
}
