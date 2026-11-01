#include "test.hpp"
#include "test_support.hpp"

#include "amun/crc32.hpp"
#include "amun/pack.hpp"

#include <string>
#include <utility>
#include <vector>

using namespace amun;
using namespace amun::test;

namespace {

void rawU16(std::vector<std::uint8_t> &out, std::uint16_t value) {
    out.push_back(static_cast<std::uint8_t>(value));
    out.push_back(static_cast<std::uint8_t>(value >> 8U));
}

void rawU32(std::vector<std::uint8_t> &out, std::uint32_t value) {
    for (unsigned i = 0; i < 4U; ++i)
        out.push_back(static_cast<std::uint8_t>(value >> (i * 8U)));
}

void rawU64(std::vector<std::uint8_t> &out, std::uint64_t value) {
    for (unsigned i = 0; i < 8U; ++i)
        out.push_back(static_cast<std::uint8_t>(value >> (i * 8U)));
}

struct RawSection {
    std::uint32_t type;
    std::vector<std::uint8_t> data;
    std::uint32_t count;
};

std::vector<std::uint8_t> minimalSerializedPack(std::uint32_t achievementCount = 1U,
                                                std::uint16_t stateSlots = 0U,
                                                const std::string &prerequisites = {},
                                                std::uint32_t assetCount = 0U) {
    std::vector<std::uint8_t> strings{0};
    std::uint32_t stringCount = 1;
    const auto addString = [&](const std::string &value) {
        const auto offset = static_cast<std::uint32_t>(strings.size());
        strings.insert(strings.end(), value.begin(), value.end());
        strings.push_back(0);
        ++stringCount;
        return offset;
    };
    const std::uint32_t game = addString("Game");
    const std::uint32_t version = addString("1");
    const std::uint32_t license = addString("MIT");
    const std::uint32_t provenance = addString("test");
    const std::uint32_t buildId = addString("build");
    const std::uint32_t region = addString("EUR");
    const std::uint32_t application = addString("1.0");
    const std::uint32_t update = addString("0");
    const std::uint32_t fingerprint = addString("fingerprint");
    const std::uint32_t achievementId = addString("achievement");
    const std::uint32_t title = addString("Title");
    const std::uint32_t description = addString("Description");
    const std::uint32_t prerequisiteOffset = prerequisites.empty() ? 0U : addString(prerequisites);
    const std::uint32_t assetName = assetCount == 0U ? 0U : addString("asset");

    std::vector<std::uint8_t> manifest;
    rawU64(manifest, 0x000400000ABCDEF0ULL);
    rawU32(manifest, game);
    rawU32(manifest, version);
    rawU32(manifest, license);
    rawU32(manifest, provenance);
    rawU32(manifest, 0);

    std::vector<std::uint8_t> builds;
    for (const std::uint32_t offset : {buildId, region, application, update, fingerprint})
        rawU32(builds, offset);
    builds.insert(builds.end(), {0, 0, 0, 0});

    std::vector<std::uint8_t> bytecode;
    constant(bytecode, 0);
    op(bytecode, Op::End);

    std::vector<std::uint8_t> achievements;
    for (std::uint32_t i = 0; i < achievementCount; ++i) {
        for (const std::uint32_t offset : {achievementId, title, description, 0U, 0U, 0U, 0U,
                                           prerequisiteOffset})
            rawU32(achievements, offset);
        rawU16(achievements, 5);
        achievements.insert(achievements.end(), {0, 0});
        rawU32(achievements, 0);
        rawU32(achievements, 0);
        rawU32(achievements, static_cast<std::uint32_t>(bytecode.size()));
        rawU16(achievements, 1);
        rawU16(achievements, stateSlots);
        rawU32(achievements, 2);
    }

    std::vector<RawSection> sections{
        {1, std::move(manifest), 1},
        {2, std::move(builds), 1},
        {3, {}, 0},
        {4, std::move(achievements), achievementCount},
        {5, {}, 0},
        {6, std::move(bytecode), 1},
        {7, std::move(strings), stringCount},
    };
    if (assetCount != 0U) {
        std::vector<std::uint8_t> assets;
        for (std::uint32_t i = 0; i < assetCount; ++i) {
            rawU32(assets, assetName);
            assets.insert(assets.end(), {1, 1, 0, 0});
            rawU16(assets, 1);
            rawU16(assets, 1);
            rawU32(assets, 0);
            rawU32(assets, 2);
            rawU32(assets, 2);
        }
        sections.push_back({8, std::move(assets), assetCount});
        sections.push_back({9, {0x12, 0x34}, assetCount});
    }

    const auto sectionCount = static_cast<std::uint16_t>(sections.size());
    const auto headerSize = static_cast<std::uint16_t>(40U + sections.size() * 16U);
    std::vector<std::uint8_t> payload;
    for (const RawSection &section : sections)
        payload.insert(payload.end(), section.data.begin(), section.data.end());
    const std::uint32_t totalSize = static_cast<std::uint32_t>(headerSize + payload.size());

    std::vector<std::uint8_t> out{'A', 'M', 'U', 'N'};
    rawU16(out, 1);
    rawU16(out, 0);
    rawU32(out, totalSize);
    rawU32(out, crc32(payload.data(), payload.size()));
    rawU32(out, assetCount == 0U ? 0U : 1U);
    rawU16(out, sectionCount);
    rawU16(out, headerSize);
    out.insert(out.end(), 16U, 0);
    std::uint32_t cursor = headerSize;
    for (const RawSection &section : sections) {
        rawU32(out, section.type);
        rawU32(out, cursor);
        rawU32(out, static_cast<std::uint32_t>(section.data.size()));
        rawU32(out, section.count);
        cursor += static_cast<std::uint32_t>(section.data.size());
    }
    out.insert(out.end(), payload.begin(), payload.end());
    return out;
}

} // namespace

TEST("pack parser rejects short, bad-magic, and inconsistent data") {
    PackParser parser;
    AchievementPack pack;
    const std::uint8_t shortData[] = {'A', 'M', 'U', 'N'};
    EXPECT_EQ(parser.parse(shortData, sizeof(shortData), pack).error, PackError::TooSmall);
    std::uint8_t header[40]{};
    header[0] = 'B'; header[1] = 'A'; header[2] = 'D'; header[3] = '!';
    EXPECT_EQ(parser.parse(header, sizeof(header), pack).error, PackError::BadMagic);
}

TEST("build matching requires title and exact executable fingerprint") {
    const AchievementPack pack = basicPack();
    GameIdentity identity = basicIdentity();
    EXPECT_EQ(matchBuild(pack, identity), BuildMatch::ExactSupportedBuild);
    identity.codeFingerprint = "other";
    EXPECT_EQ(matchBuild(pack, identity), BuildMatch::UnknownBuild);
    identity.titleId = 5;
    EXPECT_EQ(matchBuild(pack, identity), BuildMatch::UnsupportedBuild);
}

TEST("bounded asset decoder supports raw and byte RLE without expansion overflow") {
    AssetDefinition raw;
    raw.decodedSize = 4;
    raw.encodedData = {1, 2, 3, 4};
    std::vector<std::uint8_t> decoded;
    EXPECT(decodeAsset(raw, decoded));
    EXPECT_EQ(decoded[2], 3U);
    AssetDefinition compressed;
    compressed.compression = AssetCompression::ByteRle;
    compressed.decodedSize = 5;
    compressed.encodedData = {3, 7, 2, 9};
    EXPECT(decodeAsset(compressed, decoded));
    EXPECT_EQ(decoded.size(), 5U);
    EXPECT_EQ(decoded[3], 9U);
    compressed.encodedData = {6, 1};
    EXPECT(!decodeAsset(compressed, decoded));
}

TEST("serialized pack parser charges aliased bytecode and asset references") {
    AchievementPack pack;
    {
        const std::vector<std::uint8_t> bytes = minimalSerializedPack(2U);
        RuntimeLimits limits;
        limits.maxBytecodeBytes = 10U;
        const PackParseResult parsed = PackParser(limits).parse(bytes.data(), bytes.size(), pack);
        EXPECT_EQ(parsed.error, PackError::LimitExceeded);
    }
    {
        const std::vector<std::uint8_t> bytes = minimalSerializedPack(1U, 0U, {}, 2U);
        RuntimeLimits limits;
        limits.maxAssetStoredBytes = 2U;
        const PackParseResult parsed = PackParser(limits).parse(bytes.data(), bytes.size(), pack);
        EXPECT_EQ(parsed.error, PackError::LimitExceeded);
    }
}

TEST("serialized pack parser enforces referenced strings prerequisites and aggregate state") {
    AchievementPack pack;
    {
        const std::vector<std::uint8_t> bytes = minimalSerializedPack();
        RuntimeLimits limits;
        limits.maxReferencedStringBytes = 4U;
        EXPECT_EQ(PackParser(limits).parse(bytes.data(), bytes.size(), pack).error,
                  PackError::LimitExceeded);
    }
    {
        const std::vector<std::uint8_t> bytes = minimalSerializedPack(1U, 0U, "a,b");
        RuntimeLimits limits;
        limits.maxPrerequisitesPerAchievement = 1U;
        EXPECT_EQ(PackParser(limits).parse(bytes.data(), bytes.size(), pack).error,
                  PackError::LimitExceeded);
    }
    {
        const std::vector<std::uint8_t> bytes = minimalSerializedPack(2U, 1U);
        RuntimeLimits limits;
        limits.maxTotalVmStateSlots = 1U;
        EXPECT_EQ(PackParser(limits).parse(bytes.data(), bytes.size(), pack).error,
                  PackError::LimitExceeded);
    }
}
