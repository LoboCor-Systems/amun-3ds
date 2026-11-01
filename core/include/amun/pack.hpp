#pragma once

#include "amun/memory.hpp"
#include "amun/types.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace amun {

inline constexpr std::uint16_t kPackMajorVersion = 1;
inline constexpr std::uint16_t kPackMinorVersion = 1;

struct BuildDefinition {
    std::string id;
    std::string region;
    std::string applicationVersion;
    std::string updateVersion;
    std::string codeFingerprint;
    bool compatible{false};
};

struct ResolverDefinition {
    ResolverKind kind{ResolverKind::Absolute};
    Address address{0};
    std::int32_t moduleOffset{0};
    std::vector<std::int32_t> pointerOffsets;
    // Optional mask for each dereference (the final offset is not dereferenced).
    std::vector<std::uint32_t> pointerXorMasks;
    bool refresh{false};
    PatternSpec pattern;
};

struct SymbolDefinition {
    std::string name;
    ValueType type{ValueType::U8};
    PollClass pollClass{PollClass::Normal};
    ResolverDefinition resolver;
    std::vector<std::uint8_t> derivedBytecode;
    std::uint8_t bitIndex{0};
    std::uint16_t valueSize{0};
};

struct AchievementDefinition {
    std::string id;
    std::string title;
    std::string description;
    std::string author;
    std::string category;
    std::string tags;
    std::string icon;
    std::vector<std::string> prerequisites;
    std::uint8_t prerequisiteMinCount{0};  // 0 = all prerequisites required
    std::uint16_t points{0};
    bool secret{false};
    bool missable{false};
    std::uint32_t progressTarget{0};
    std::uint16_t maxStack{0};
    std::uint16_t stateSlots{0};
    std::uint32_t instructionBudget{0};
    std::vector<std::uint8_t> bytecode;
};

enum class AssetKind : std::uint8_t { Icon = 1, Sound = 2 };
enum class AssetFormat : std::uint8_t { Rgb565 = 1, Rgba5551 = 2, PcmU8 = 3 };
enum class AssetCompression : std::uint8_t { None = 0, ByteRle = 1 };

struct AssetDefinition {
    std::string name;
    AssetKind kind{AssetKind::Icon};
    AssetFormat format{AssetFormat::Rgb565};
    AssetCompression compression{AssetCompression::None};
    std::uint16_t width{0};
    std::uint16_t height{0};
    std::uint32_t decodedSize{0};
    std::vector<std::uint8_t> encodedData;
};

struct AchievementPack {
    std::uint64_t titleId{0};
    std::string gameName;
    std::string profileVersion;
    std::string profileLicense;
    std::string provenance;
    std::array<std::uint8_t, 16> profileHash{};
    std::vector<BuildDefinition> builds;
    std::vector<SymbolDefinition> symbols;
    std::vector<AchievementDefinition> achievements;
    std::vector<AssetDefinition> assets;
};

enum class PackError : std::uint8_t {
    None = 0,
    TooSmall,
    TooLarge,
    BadMagic,
    UnsupportedVersion,
    SizeMismatch,
    ChecksumMismatch,
    BadSectionDirectory,
    MissingSection,
    InvalidString,
    InvalidRecord,
    LimitExceeded,
    InvalidBytecode,
};

struct PackParseResult {
    PackError error{PackError::None};
    std::string detail;
    explicit operator bool() const noexcept { return error == PackError::None; }
};

class PackParser {
public:
    explicit PackParser(RuntimeLimits limits = {});
    PackParseResult parse(const std::uint8_t *bytes, std::size_t size, AchievementPack &out) const;
    PackParseResult parseFile(const std::string &path, AchievementPack &out) const;

private:
    RuntimeLimits limits_;
};

BuildMatch matchBuild(const AchievementPack &pack, const GameIdentity &identity,
                      std::size_t *matchedIndex = nullptr) noexcept;

bool decodeAsset(const AssetDefinition &asset, std::vector<std::uint8_t> &out,
                 std::uint32_t maximumDecodedBytes = 32U * 1024U) noexcept;

} // namespace amun
