#include "amun/pack.hpp"

#include "amun/crc32.hpp"
#include "amun/vm.hpp"

#include <algorithm>
#include <cstring>
#include <fstream>
#include <limits>
#include <utility>

namespace amun {

namespace {

constexpr std::size_t kFixedHeaderSize = 40U;
constexpr std::size_t kSectionEntrySize = 16U;
constexpr std::size_t kManifestRecordSize = 28U;
constexpr std::size_t kBuildRecordSize = 24U;
constexpr std::size_t kSymbolRecordSize = 32U;
constexpr std::size_t kAchievementRecordSize = 56U;
constexpr std::size_t kAssetRecordSize = 24U;
constexpr std::uint16_t kMaximumSections = 16;

enum class SectionType : std::uint32_t {
    Manifest = 1,
    Builds = 2,
    Symbols = 3,
    Achievements = 4,
    Resolvers = 5,
    Bytecode = 6,
    Strings = 7,
    Assets = 8,
    AssetData = 9,
};

struct Section {
    SectionType type{};
    std::uint32_t offset{0};
    std::uint32_t size{0};
    std::uint32_t count{0};
};

bool readU8(const std::uint8_t *data, std::size_t size, std::size_t offset,
            std::uint8_t &out) noexcept {
    if (offset >= size) return false;
    out = data[offset];
    return true;
}

bool readU16(const std::uint8_t *data, std::size_t size, std::size_t offset,
             std::uint16_t &out) noexcept {
    if (offset > size || size - offset < 2U) return false;
    out = static_cast<std::uint16_t>(data[offset]) |
          static_cast<std::uint16_t>(static_cast<std::uint16_t>(data[offset + 1U]) << 8U);
    return true;
}

bool readU32(const std::uint8_t *data, std::size_t size, std::size_t offset,
             std::uint32_t &out) noexcept {
    if (offset > size || size - offset < 4U) return false;
    out = static_cast<std::uint32_t>(data[offset]) |
          (static_cast<std::uint32_t>(data[offset + 1U]) << 8U) |
          (static_cast<std::uint32_t>(data[offset + 2U]) << 16U) |
          (static_cast<std::uint32_t>(data[offset + 3U]) << 24U);
    return true;
}

bool readI32(const std::uint8_t *data, std::size_t size, std::size_t offset,
             std::int32_t &out) noexcept {
    std::uint32_t raw = 0;
    if (!readU32(data, size, offset, raw)) return false;
    std::memcpy(&out, &raw, sizeof(out));
    return true;
}

bool readU64(const std::uint8_t *data, std::size_t size, std::size_t offset,
             std::uint64_t &out) noexcept {
    if (offset > size || size - offset < 8U) return false;
    out = 0;
    for (unsigned i = 0; i < 8U; ++i) {
        out |= static_cast<std::uint64_t>(data[offset + i]) << (i * 8U);
    }
    return true;
}

const Section *findSection(const std::vector<Section> &sections, SectionType type) noexcept {
    const auto it = std::find_if(sections.begin(), sections.end(),
                                 [type](const Section &section) { return section.type == type; });
    return it == sections.end() ? nullptr : &*it;
}

bool sectionSlice(const Section &section, std::uint32_t relativeOffset, std::uint32_t length,
                  const std::uint8_t *&out, const std::uint8_t *file) noexcept {
    const std::uint64_t end = static_cast<std::uint64_t>(relativeOffset) + length;
    if (end > section.size) return false;
    out = file + section.offset + relativeOffset;
    return true;
}

bool getString(const std::uint8_t *file, const Section &strings, std::uint32_t offset,
               std::uint16_t maxBytes, std::string &out) {
    if (offset >= strings.size) return false;
    const char *start = reinterpret_cast<const char *>(file + strings.offset + offset);
    const std::size_t remaining = strings.size - offset;
    const void *terminator = std::memchr(start, '\0', std::min<std::size_t>(remaining, maxBytes + 1U));
    if (terminator == nullptr) return false;
    const auto *end = static_cast<const char *>(terminator);
    out.assign(start, static_cast<std::size_t>(end - start));
    return true;
}

std::vector<std::string> splitPrerequisites(const std::string &joined) {
    std::vector<std::string> result;
    std::size_t begin = 0;
    while (begin < joined.size()) {
        const std::size_t end = joined.find(',', begin);
        const std::size_t length = (end == std::string::npos ? joined.size() : end) - begin;
        if (length != 0) result.push_back(joined.substr(begin, length));
        if (end == std::string::npos) break;
        begin = end + 1U;
    }
    return result;
}

PackParseResult error(PackError code, std::string detail) {
    return {code, std::move(detail)};
}

} // namespace

PackParser::PackParser(RuntimeLimits limits) : limits_(limits) {}

PackParseResult PackParser::parseFile(const std::string &path, AchievementPack &out) const {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream) return error(PackError::TooSmall, "could not open pack");
    const std::streamoff rawSize = stream.tellg();
    if (rawSize < 0 || static_cast<std::uint64_t>(rawSize) > limits_.maxPackBytes)
        return error(PackError::TooLarge, "pack exceeds configured size limit");
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(rawSize));
    const auto readSize = static_cast<std::streamsize>(rawSize);
    stream.seekg(0, std::ios::beg);
    if (!bytes.empty() && !stream.read(reinterpret_cast<char *>(bytes.data()), readSize))
        return error(PackError::SizeMismatch, "could not read entire pack");
    return parse(bytes.data(), bytes.size(), out);
}

PackParseResult PackParser::parse(const std::uint8_t *bytes, std::size_t size,
                                  AchievementPack &out) const {
    out = {};
    if (bytes == nullptr || size < kFixedHeaderSize) return error(PackError::TooSmall, "truncated header");
    if (size > limits_.maxPackBytes) return error(PackError::TooLarge, "pack exceeds configured size limit");
    if (std::memcmp(bytes, "AMUN", 4U) != 0) return error(PackError::BadMagic, "expected AMUN magic");

    std::uint16_t major = 0, minor = 0, sectionCount = 0, headerSize = 0;
    std::uint32_t declaredSize = 0, expectedCrc = 0, flags = 0;
    if (!readU16(bytes, size, 4, major) || !readU16(bytes, size, 6, minor) ||
        !readU32(bytes, size, 8, declaredSize) || !readU32(bytes, size, 12, expectedCrc) ||
        !readU32(bytes, size, 16, flags) || !readU16(bytes, size, 20, sectionCount) ||
        !readU16(bytes, size, 22, headerSize))
        return error(PackError::TooSmall, "truncated fixed header");
    (void)flags;
    if (major != kPackMajorVersion || minor > kPackMinorVersion)
        return error(PackError::UnsupportedVersion, "unsupported pack format version");
    if (declaredSize != size) return error(PackError::SizeMismatch, "declared size differs from file size");
    if (sectionCount == 0 || sectionCount > kMaximumSections ||
        headerSize != kFixedHeaderSize + static_cast<std::size_t>(sectionCount) * kSectionEntrySize ||
        headerSize > size)
        return error(PackError::BadSectionDirectory, "invalid section directory size");
    if (crc32(bytes + headerSize, size - headerSize) != expectedCrc)
        return error(PackError::ChecksumMismatch, "payload CRC-32 mismatch");
    std::memcpy(out.profileHash.data(), bytes + 24U, out.profileHash.size());

    std::vector<Section> sections;
    sections.reserve(sectionCount);
    for (std::uint16_t i = 0; i < sectionCount; ++i) {
        const std::size_t at = kFixedHeaderSize + static_cast<std::size_t>(i) * kSectionEntrySize;
        std::uint32_t rawType = 0;
        Section section;
        if (!readU32(bytes, size, at, rawType) || !readU32(bytes, size, at + 4U, section.offset) ||
            !readU32(bytes, size, at + 8U, section.size) || !readU32(bytes, size, at + 12U, section.count))
            return error(PackError::BadSectionDirectory, "truncated section entry");
        section.type = static_cast<SectionType>(rawType);
        const std::uint64_t end = static_cast<std::uint64_t>(section.offset) + section.size;
        if (section.offset < headerSize || end > size)
            return error(PackError::BadSectionDirectory, "section outside payload");
        if (findSection(sections, section.type) != nullptr)
            return error(PackError::BadSectionDirectory, "duplicate section type");
        sections.push_back(section);
    }
    std::vector<std::pair<std::uint64_t, std::uint64_t>> ranges;
    for (const Section &section : sections) {
        if (section.size != 0) ranges.emplace_back(section.offset,
            static_cast<std::uint64_t>(section.offset) + section.size);
    }
    std::sort(ranges.begin(), ranges.end());
    for (std::size_t i = 1; i < ranges.size(); ++i) {
        if (ranges[i].first < ranges[i - 1U].second)
            return error(PackError::BadSectionDirectory, "overlapping sections");
    }

    const Section *manifest = findSection(sections, SectionType::Manifest);
    const Section *builds = findSection(sections, SectionType::Builds);
    const Section *symbols = findSection(sections, SectionType::Symbols);
    const Section *achievements = findSection(sections, SectionType::Achievements);
    const Section *resolvers = findSection(sections, SectionType::Resolvers);
    const Section *bytecode = findSection(sections, SectionType::Bytecode);
    const Section *strings = findSection(sections, SectionType::Strings);
    const Section *assets = findSection(sections, SectionType::Assets);
    const Section *assetData = findSection(sections, SectionType::AssetData);
    if (!manifest || !builds || !symbols || !achievements || !resolvers || !bytecode || !strings)
        return error(PackError::MissingSection, "one or more required sections are absent");
    if (manifest->count != 1 || manifest->size != kManifestRecordSize ||
        builds->size != static_cast<std::uint64_t>(builds->count) * kBuildRecordSize ||
        symbols->size != static_cast<std::uint64_t>(symbols->count) * kSymbolRecordSize ||
        achievements->size != static_cast<std::uint64_t>(achievements->count) * kAchievementRecordSize)
        return error(PackError::InvalidRecord, "section count does not match record bytes");
    if (builds->count == 0 || builds->count > limits_.maxBuilds ||
        symbols->count > limits_.maxSymbols || achievements->count == 0 ||
        achievements->count > limits_.maxAchievements ||
        bytecode->size > limits_.maxBytecodeBytes)
        return error(PackError::LimitExceeded, "pack object limit exceeded");
    if (strings->size == 0 || bytes[strings->offset] != 0)
        return error(PackError::InvalidString, "string table must begin with NUL");
    const auto actualStringCount = static_cast<std::uint64_t>(std::count(
        bytes + strings->offset, bytes + strings->offset + strings->size, std::uint8_t{0}));
    if (strings->count > limits_.maxStrings || actualStringCount != strings->count)
        return error(PackError::LimitExceeded, "string table count exceeds limit or does not match data");
    if ((assets == nullptr) != (assetData == nullptr))
        return error(PackError::MissingSection, "asset records and data must appear together");
    if (assets != nullptr && (assets->count > limits_.maxAssets ||
        assets->size != static_cast<std::uint64_t>(assets->count) * kAssetRecordSize ||
        assetData->size > limits_.maxAssetStoredBytes))
        return error(PackError::LimitExceeded, "asset section limit exceeded");

    std::uint64_t referencedStringBytes = 0;
    bool referencedStringLimitExceeded = false;
    const auto readString = [&](std::uint32_t offset, std::string &value) {
        if (!getString(bytes, *strings, offset, limits_.maxStringBytes, value)) return false;
        referencedStringBytes += value.size() + 1U;
        if (referencedStringBytes > limits_.maxReferencedStringBytes) {
            referencedStringLimitExceeded = true;
            return false;
        }
        return true;
    };
    const auto stringError = [&](const char *detail) {
        return referencedStringLimitExceeded
            ? error(PackError::LimitExceeded, "referenced string bytes exceed configured limit")
            : error(PackError::InvalidString, detail);
    };

    std::uint32_t nameOffset = 0, versionOffset = 0, licenseOffset = 0, provenanceOffset = 0;
    if (!readU64(bytes, size, manifest->offset, out.titleId) ||
        !readU32(bytes, size, manifest->offset + 8U, nameOffset) ||
        !readU32(bytes, size, manifest->offset + 12U, versionOffset) ||
        !readU32(bytes, size, manifest->offset + 16U, licenseOffset) ||
        !readU32(bytes, size, manifest->offset + 20U, provenanceOffset) ||
        !readString(nameOffset, out.gameName) || !readString(versionOffset, out.profileVersion) ||
        !readString(licenseOffset, out.profileLicense) || !readString(provenanceOffset, out.provenance))
        return stringError("invalid manifest string reference");

    out.builds.reserve(builds->count);
    for (std::uint32_t i = 0; i < builds->count; ++i) {
        const std::size_t at = builds->offset + static_cast<std::size_t>(i) * kBuildRecordSize;
        std::uint32_t offsets[5]{};
        std::uint8_t buildFlags = 0;
        for (std::size_t field = 0; field < 5U; ++field) {
            if (!readU32(bytes, size, at + field * 4U, offsets[field]))
                return error(PackError::InvalidRecord, "truncated build record");
        }
        if (!readU8(bytes, size, at + 20U, buildFlags))
            return error(PackError::InvalidRecord, "truncated build flags");
        BuildDefinition build;
        if (!readString(offsets[0], build.id) || !readString(offsets[1], build.region) ||
            !readString(offsets[2], build.applicationVersion) || !readString(offsets[3], build.updateVersion) ||
            !readString(offsets[4], build.codeFingerprint))
            return stringError("invalid build string reference");
        build.compatible = (buildFlags & 1U) != 0;
        out.builds.push_back(std::move(build));
    }

    std::uint64_t referencedBytecodeBytes = 0;
    std::uint64_t totalPatternScanBytes = 0;
    out.symbols.reserve(symbols->count);
    for (std::uint32_t i = 0; i < symbols->count; ++i) {
        const std::size_t at = symbols->offset + static_cast<std::size_t>(i) * kSymbolRecordSize;
        std::uint32_t symbolName = 0, address = 0, resolverOffset = 0, derivedOffset = 0;
        std::uint16_t resolverSize = 0, derivedSize = 0, valueSize = 0;
        std::int32_t moduleOffset = 0;
        std::uint8_t valueType = 0, pollClass = 0, resolverKind = 0, symbolFlags = 0;
        std::uint8_t pointerDepth = 0, bitIndex = 0;
        if (!readU32(bytes, size, at, symbolName) || !readU8(bytes, size, at + 4U, valueType) ||
            !readU8(bytes, size, at + 5U, pollClass) || !readU8(bytes, size, at + 6U, resolverKind) ||
            !readU8(bytes, size, at + 7U, symbolFlags) || !readU32(bytes, size, at + 8U, address) ||
            !readI32(bytes, size, at + 12U, moduleOffset) || !readU32(bytes, size, at + 16U, resolverOffset) ||
            !readU16(bytes, size, at + 20U, resolverSize) || !readU8(bytes, size, at + 22U, pointerDepth) ||
            !readU8(bytes, size, at + 23U, bitIndex) || !readU32(bytes, size, at + 24U, derivedOffset) ||
            !readU16(bytes, size, at + 28U, derivedSize) || !readU16(bytes, size, at + 30U, valueSize))
            return error(PackError::InvalidRecord, "truncated symbol record");
        if ((symbolFlags & ~3U) != 0 ||
            (symbolFlags != 0 && resolverKind != static_cast<std::uint8_t>(ResolverKind::PointerChain)) ||
            (minor == 0 && (symbolFlags != 0 || pointerDepth > 8)))
            return error(PackError::InvalidRecord, "invalid or unversioned pointer resolver flags");
        if (valueType > static_cast<std::uint8_t>(ValueType::FixedString) ||
            pollClass > static_cast<std::uint8_t>(PollClass::Static) ||
            resolverKind > static_cast<std::uint8_t>(ResolverKind::Derived) ||
            pointerDepth > limits_.maxPointerDepth || bitIndex > 7)
            return error(PackError::InvalidRecord, "invalid symbol enum or limit");
        SymbolDefinition symbol;
        if (!readString(symbolName, symbol.name)) return stringError("invalid symbol name");
        if (symbol.name.empty()) return error(PackError::InvalidString, "empty symbol name");
        symbol.type = static_cast<ValueType>(valueType);
        symbol.pollClass = static_cast<PollClass>(pollClass);
        symbol.resolver.kind = static_cast<ResolverKind>(resolverKind);
        symbol.resolver.address = address;
        symbol.resolver.moduleOffset = moduleOffset;
        symbol.resolver.refresh = (symbolFlags & 2U) != 0;
        symbol.bitIndex = bitIndex;
        symbol.valueSize = valueSize;
        const bool fixedBytes = symbol.type == ValueType::Bytes || symbol.type == ValueType::FixedString;
        if ((fixedBytes && (valueSize == 0 || valueSize > 16U)) || (!fixedBytes && valueSize != 0))
            return error(PackError::InvalidRecord, "invalid fixed value size");

        const std::uint8_t *resolverData = nullptr;
        if (!sectionSlice(*resolvers, resolverOffset, resolverSize, resolverData, bytes))
            return error(PackError::InvalidRecord, "resolver slice outside section");
        if (symbol.resolver.kind == ResolverKind::PointerChain) {
            const unsigned expectedSize = pointerDepth * 4U +
                ((symbolFlags & 1U) != 0 && pointerDepth > 0 ? (pointerDepth - 1U) * 4U : 0U);
            if (pointerDepth == 0 || resolverSize != expectedSize)
                return error(PackError::InvalidRecord, "invalid pointer resolver size");
            for (std::uint8_t depth = 0; depth < pointerDepth; ++depth) {
                std::int32_t offset = 0;
                if (!readI32(resolverData, resolverSize, depth * 4U, offset))
                    return error(PackError::InvalidRecord, "truncated pointer offset");
                symbol.resolver.pointerOffsets.push_back(offset);
            }
            if ((symbolFlags & 1U) != 0) {
                for (std::uint8_t depth = 0; depth + 1U < pointerDepth; ++depth) {
                    std::uint32_t mask = 0;
                    if (!readU32(resolverData, resolverSize, (pointerDepth + depth) * 4U, mask))
                        return error(PackError::InvalidRecord, "truncated pointer XOR mask");
                    symbol.resolver.pointerXorMasks.push_back(mask);
                }
            }
        } else if (symbol.resolver.kind == ResolverKind::Pattern) {
            std::uint16_t patternLength = 0;
            if (resolverSize < 16U || !readU32(resolverData, resolverSize, 0, symbol.resolver.pattern.scanStart) ||
                !readU32(resolverData, resolverSize, 4, symbol.resolver.pattern.scanSize) ||
                !readI32(resolverData, resolverSize, 8, symbol.resolver.pattern.resultOffset) ||
                !readU16(resolverData, resolverSize, 12, patternLength) || patternLength == 0 ||
                patternLength > limits_.maxSignatureBytes || resolverSize != 16U + patternLength * 2U ||
                symbol.resolver.pattern.scanSize < patternLength ||
                symbol.resolver.pattern.scanSize > limits_.maxPatternScanBytes ||
                static_cast<std::uint64_t>(symbol.resolver.pattern.scanStart) +
                    symbol.resolver.pattern.scanSize > std::numeric_limits<Address>::max())
                return error(PackError::InvalidRecord, "invalid pattern resolver");
            totalPatternScanBytes += symbol.resolver.pattern.scanSize;
            if (totalPatternScanBytes > limits_.maxTotalPatternScanBytes)
                return error(PackError::LimitExceeded, "aggregate pattern scan bytes exceed limit");
            symbol.resolver.pattern.bytes.assign(resolverData + 16U, resolverData + 16U + patternLength);
            symbol.resolver.pattern.mask.assign(resolverData + 16U + patternLength,
                                                resolverData + 16U + patternLength * 2U);
        } else if (resolverSize != 0) {
            return error(PackError::InvalidRecord, "unexpected resolver payload");
        }
        const std::uint8_t *derivedData = nullptr;
        if (!sectionSlice(*bytecode, derivedOffset, derivedSize, derivedData, bytes))
            return error(PackError::InvalidRecord, "derived bytecode outside section");
        if ((symbol.resolver.kind == ResolverKind::Derived && derivedSize == 0) ||
            (symbol.resolver.kind != ResolverKind::Derived && derivedSize != 0))
            return error(PackError::InvalidRecord, "derived bytecode does not match resolver kind");
        referencedBytecodeBytes += derivedSize;
        if (referencedBytecodeBytes > limits_.maxBytecodeBytes)
            return error(PackError::LimitExceeded, "referenced bytecode bytes exceed limit");
        if (derivedSize != 0) {
            const VmVerifyResult verified = verifyBytecode(derivedData, derivedSize, symbols->count, limits_);
            if (!verified.valid || verified.stateSlots != 0)
                return error(PackError::InvalidBytecode,
                             verified.error.empty() ? "derived bytecode must be stateless" : verified.error);
        }
        symbol.derivedBytecode.assign(derivedData, derivedData + derivedSize);
        out.symbols.push_back(std::move(symbol));
    }

    std::uint64_t totalVmStateSlots = 0;
    out.achievements.reserve(achievements->count);
    for (std::uint32_t i = 0; i < achievements->count; ++i) {
        const std::size_t at = achievements->offset + static_cast<std::size_t>(i) * kAchievementRecordSize;
        std::uint32_t offsets[8]{};
        for (std::size_t field = 0; field < 8U; ++field) {
            if (!readU32(bytes, size, at + field * 4U, offsets[field]))
                return error(PackError::InvalidRecord, "truncated achievement strings");
        }
        AchievementDefinition achievement;
        std::uint8_t metadataFlags = 0, reserved = 0;
        std::uint32_t codeOffset = 0, codeSize = 0;
        if (!readU16(bytes, size, at + 32U, achievement.points) ||
            !readU8(bytes, size, at + 34U, metadataFlags) || !readU8(bytes, size, at + 35U, reserved) ||
            !readU32(bytes, size, at + 36U, achievement.progressTarget) ||
            !readU32(bytes, size, at + 40U, codeOffset) || !readU32(bytes, size, at + 44U, codeSize) ||
            !readU16(bytes, size, at + 48U, achievement.maxStack) ||
            !readU16(bytes, size, at + 50U, achievement.stateSlots) ||
            !readU32(bytes, size, at + 52U, achievement.instructionBudget))
            return error(PackError::InvalidRecord, "truncated achievement record");
        achievement.prerequisiteMinCount = reserved;
        std::string prereq;
        std::string *fields[8] = {&achievement.id, &achievement.title, &achievement.description,
                                  &achievement.author, &achievement.category, &achievement.tags,
                                  &achievement.icon, &prereq};
        for (std::size_t field = 0; field < 8U; ++field) {
            if (!readString(offsets[field], *fields[field]))
                return stringError("invalid achievement string reference");
        }
        achievement.prerequisites = splitPrerequisites(prereq);
        if (achievement.prerequisites.size() > limits_.maxPrerequisitesPerAchievement)
            return error(PackError::LimitExceeded, "achievement prerequisite count exceeds limit");
        if (achievement.prerequisiteMinCount != 0 &&
            achievement.prerequisiteMinCount > achievement.prerequisites.size())
            return error(PackError::InvalidRecord, "achievement prerequisiteMinCount exceeds prerequisite list");
        achievement.secret = (metadataFlags & 1U) != 0;
        achievement.missable = (metadataFlags & 2U) != 0;
        if (achievement.id.empty() || achievement.points > 10000U || achievement.instructionBudget == 0 ||
            achievement.instructionBudget > limits_.maxInstructionsPerAchievement ||
            achievement.maxStack == 0 || achievement.maxStack > limits_.maxVmStack ||
            achievement.stateSlots > limits_.maxVmStateSlots)
            return error(PackError::InvalidRecord, "invalid achievement limits");
        totalVmStateSlots += achievement.stateSlots;
        if (totalVmStateSlots > limits_.maxTotalVmStateSlots)
            return error(PackError::LimitExceeded, "aggregate VM state slots exceed limit");
        const std::uint8_t *program = nullptr;
        if (!sectionSlice(*bytecode, codeOffset, codeSize, program, bytes))
            return error(PackError::InvalidRecord, "achievement bytecode outside section");
        referencedBytecodeBytes += codeSize;
        if (referencedBytecodeBytes > limits_.maxBytecodeBytes)
            return error(PackError::LimitExceeded, "referenced bytecode bytes exceed limit");
        const VmVerifyResult verified = verifyBytecode(program, codeSize, symbols->count, limits_);
        if (!verified.valid || achievement.maxStack < verified.maximumStack ||
            achievement.stateSlots < verified.stateSlots || achievement.instructionBudget < verified.instructions)
            return error(PackError::InvalidBytecode, verified.error.empty() ? "declared VM limits too small" : verified.error);
        achievement.bytecode.assign(program, program + codeSize);
        out.achievements.push_back(std::move(achievement));
    }
    if (assets != nullptr) {
        out.assets.reserve(assets->count);
        std::uint64_t totalDecoded = 0;
        std::uint64_t totalStoredReferences = 0;
        for (std::uint32_t i = 0; i < assets->count; ++i) {
            const std::size_t at = assets->offset + static_cast<std::size_t>(i) * kAssetRecordSize;
            std::uint32_t name = 0, dataOffset = 0, storedSize = 0, decodedSize = 0;
            std::uint16_t width = 0, height = 0;
            std::uint8_t kind = 0, format = 0, compression = 0;
            if (!readU32(bytes, size, at, name) || !readU8(bytes, size, at + 4U, kind) ||
                !readU8(bytes, size, at + 5U, format) || !readU8(bytes, size, at + 6U, compression) ||
                !readU16(bytes, size, at + 8U, width) || !readU16(bytes, size, at + 10U, height) ||
                !readU32(bytes, size, at + 12U, dataOffset) ||
                !readU32(bytes, size, at + 16U, storedSize) ||
                !readU32(bytes, size, at + 20U, decodedSize))
                return error(PackError::InvalidRecord, "truncated asset record");
            if (kind < static_cast<std::uint8_t>(AssetKind::Icon) ||
                kind > static_cast<std::uint8_t>(AssetKind::Sound) ||
                format < static_cast<std::uint8_t>(AssetFormat::Rgb565) ||
                format > static_cast<std::uint8_t>(AssetFormat::PcmU8) ||
                compression > static_cast<std::uint8_t>(AssetCompression::ByteRle) ||
                storedSize == 0 || decodedSize == 0 || decodedSize > limits_.maxAssetDecodedBytes)
                return error(PackError::InvalidRecord, "invalid asset enum or size");
            const std::uint8_t *encoded = nullptr;
            if (!sectionSlice(*assetData, dataOffset, storedSize, encoded, bytes))
                return error(PackError::InvalidRecord, "asset bytes outside data section");
            totalStoredReferences += storedSize;
            if (totalStoredReferences > limits_.maxAssetStoredBytes)
                return error(PackError::LimitExceeded, "referenced stored asset bytes exceed limit");
            AssetDefinition asset;
            if (!readString(name, asset.name) || asset.name.empty()) return stringError("invalid asset name");
            asset.kind = static_cast<AssetKind>(kind);
            asset.format = static_cast<AssetFormat>(format);
            asset.compression = static_cast<AssetCompression>(compression);
            asset.width = width;
            asset.height = height;
            asset.decodedSize = decodedSize;
            asset.encodedData.assign(encoded, encoded + storedSize);
            if (asset.kind == AssetKind::Icon) {
                if (width == 0 || height == 0 || width > 64 || height > 64 ||
                    (asset.format != AssetFormat::Rgb565 && asset.format != AssetFormat::Rgba5551) ||
                    decodedSize != static_cast<std::uint32_t>(width) * height * 2U)
                    return error(PackError::InvalidRecord, "invalid icon dimensions or format");
            } else if (width != 0 || height != 0 || asset.format != AssetFormat::PcmU8) {
                return error(PackError::InvalidRecord, "invalid sound asset metadata");
            }
            if (asset.compression == AssetCompression::None && storedSize != decodedSize)
                return error(PackError::InvalidRecord, "uncompressed asset size mismatch");
            std::vector<std::uint8_t> decoded;
            if (!decodeAsset(asset, decoded, limits_.maxAssetDecodedBytes))
                return error(PackError::InvalidRecord, "malformed compressed asset");
            totalDecoded += decodedSize;
            if (totalDecoded > limits_.maxTotalAssetDecodedBytes)
                return error(PackError::LimitExceeded, "total decoded asset limit exceeded");
            out.assets.push_back(std::move(asset));
        }
    }
    return {};
}

bool decodeAsset(const AssetDefinition &asset, std::vector<std::uint8_t> &out,
                 std::uint32_t maximumDecodedBytes) noexcept {
    out.clear();
    if (asset.decodedSize == 0 || asset.decodedSize > maximumDecodedBytes) return false;
#if defined(__cpp_exceptions) || defined(_CPPUNWIND)
    try {
#endif
        out.reserve(asset.decodedSize);
        if (asset.compression == AssetCompression::None) {
            if (asset.encodedData.size() != asset.decodedSize) return false;
            out = asset.encodedData;
        } else if (asset.compression == AssetCompression::ByteRle) {
            if ((asset.encodedData.size() & 1U) != 0U) return false;
            for (std::size_t i = 0; i < asset.encodedData.size(); i += 2U) {
                const std::uint8_t count = asset.encodedData[i];
                if (count == 0 || out.size() + count > asset.decodedSize) return false;
                out.insert(out.end(), count, asset.encodedData[i + 1U]);
            }
        } else {
            return false;
        }
#if defined(__cpp_exceptions) || defined(_CPPUNWIND)
    } catch (...) {
        out.clear();
        return false;
    }
#endif
    return out.size() == asset.decodedSize;
}

BuildMatch matchBuild(const AchievementPack &pack, const GameIdentity &identity,
                      std::size_t *matchedIndex) noexcept {
    if (matchedIndex != nullptr) *matchedIndex = std::numeric_limits<std::size_t>::max();
    if (pack.titleId != identity.titleId) return BuildMatch::UnsupportedBuild;
    for (std::size_t i = 0; i < pack.builds.size(); ++i) {
        const BuildDefinition &build = pack.builds[i];
        const bool matches = (build.region.empty() || build.region == identity.region) &&
            (build.applicationVersion.empty() || build.applicationVersion == identity.applicationVersion) &&
            (build.updateVersion.empty() || build.updateVersion == identity.updateVersion) &&
            (!build.codeFingerprint.empty() && build.codeFingerprint == identity.codeFingerprint);
        if (matches) {
            if (matchedIndex != nullptr) *matchedIndex = i;
            return build.compatible ? BuildMatch::CompatibleSupportedBuild :
                                      BuildMatch::ExactSupportedBuild;
        }
    }
    return BuildMatch::UnknownBuild;
}

} // namespace amun
