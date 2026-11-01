#pragma once

#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <string>
#include <vector>

namespace amun {

using Address = std::uint32_t;
using Milliseconds = std::uint64_t;

enum class ValueType : std::uint8_t {
    Bit = 0,
    Bool,
    U8,
    S8,
    U16,
    S16,
    U32,
    S32,
    F32,
    Bytes,
    FixedString,
};

enum class PollClass : std::uint8_t { Fast = 0, Normal, Slow, Static };
enum class ResolverKind : std::uint8_t { Absolute = 0, ModuleRelative, PointerChain, Pattern, Derived };
enum class BuildMatch : std::uint8_t {
    ExactSupportedBuild = 0,
    CompatibleSupportedBuild,
    UnknownBuild,
    UnsupportedBuild,
};
enum class IntegrityMode : std::uint8_t { Live = 0, LiveUnverified, Developer, Imported, SaveScan };
enum class CheatStatus : std::uint8_t { Inactive = 0, Active, Unknown };
enum class PerformanceMode : std::uint8_t { Compatibility = 0, Balanced, Responsive };

struct Scalar {
    enum class Kind : std::uint8_t { Integer = 0, Floating, Bytes };

    Kind kind{Kind::Integer};
    std::int64_t integer{0};
    float floating{0.0F};
    std::array<std::uint8_t, 16> bytes{};
    std::uint8_t byteCount{0};

    static Scalar fromInteger(std::int64_t value) noexcept {
        Scalar out;
        out.integer = value;
        return out;
    }

    static Scalar fromFloat(float value) noexcept {
        Scalar out;
        out.kind = Kind::Floating;
        out.floating = value;
        return out;
    }

    static Scalar fromBytes(const std::uint8_t *value, std::size_t size) noexcept {
        Scalar out;
        out.kind = Kind::Bytes;
        out.byteCount = static_cast<std::uint8_t>(size > out.bytes.size() ? out.bytes.size() : size);
        for (std::size_t i = 0; i < out.byteCount; ++i) out.bytes[i] = value[i];
        return out;
    }

    double asDouble() const noexcept {
        return kind == Kind::Floating ? static_cast<double>(floating) :
               kind == Kind::Integer ? static_cast<double>(integer) : 0.0;
    }

    std::int64_t asInteger() const noexcept {
        if (kind == Kind::Integer) return integer;
        if (kind != Kind::Floating || !std::isfinite(floating)) return 0;
        const double value = static_cast<double>(floating);
        if (value >= static_cast<double>(std::numeric_limits<std::int64_t>::max()))
            return std::numeric_limits<std::int64_t>::max();
        if (value <= static_cast<double>(std::numeric_limits<std::int64_t>::min()))
            return std::numeric_limits<std::int64_t>::min();
        return static_cast<std::int64_t>(value);
    }
};

struct SymbolSnapshot {
    Scalar current{};
    Scalar previous{};
    Scalar initial{};
    bool valid{false};
    bool hasPrevious{false};
    bool hasInitial{false};
};

struct GameIdentity {
    std::uint64_t titleId{0};
    std::string region;
    std::string applicationVersion;
    std::string updateVersion;
    std::string codeFingerprint;
    Address moduleBase{0x00100000U};
};

struct TickMetrics {
    std::uint64_t elapsedMicroseconds{0};
    std::uint32_t reads{0};
    std::uint32_t bytesRead{0};
    std::uint32_t achievementsEvaluated{0};
    std::uint32_t instructionsExecuted{0};
    std::uint32_t failures{0};
};

struct RuntimeSummary {
    std::uint16_t achievementsUnlocked{0};
    std::uint16_t achievementsTotal{0};
    std::uint32_t pointsUnlocked{0};
    std::uint32_t pointsTotal{0};
    std::uint8_t completionPercent{0};
};

struct RuntimeLimits {
    std::uint32_t maxPackBytes{2U * 1024U * 1024U};
    std::uint16_t maxBuilds{64};
    std::uint16_t maxAchievements{500};
    std::uint16_t maxSymbols{1024};
    std::uint16_t maxStrings{8192};
    std::uint16_t maxStringBytes{1024};
    std::uint32_t maxReferencedStringBytes{2U * 1024U * 1024U};
    std::uint16_t maxPrerequisitesPerAchievement{32};
    std::uint8_t maxPointerDepth{16};
    std::uint16_t maxSignatureBytes{128};
    std::uint32_t maxPatternScanBytes{32U * 1024U * 1024U};
    std::uint32_t maxTotalPatternScanBytes{64U * 1024U * 1024U};
    std::uint16_t maxAssets{128};
    std::uint32_t maxAssetStoredBytes{256U * 1024U};
    std::uint32_t maxAssetDecodedBytes{32U * 1024U};
    std::uint32_t maxTotalAssetDecodedBytes{512U * 1024U};
    std::uint32_t maxBytecodeBytes{256U * 1024U};
    std::uint16_t maxVmStack{64};
    std::uint16_t maxVmStateSlots{256};
    std::uint32_t maxTotalVmStateSlots{4096};
    std::uint32_t maxInstructionsPerAchievement{2048};
    std::uint8_t maxConditionNesting{32};
};

} // namespace amun
