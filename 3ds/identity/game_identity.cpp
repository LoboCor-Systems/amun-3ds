#include "amun/3ds/game_identity.hpp"

#include "amun/3ds/memory_reader.hpp"
#include "amun/crc32.hpp"

#include <3ds.h>
#include <CTRPluginFramework.hpp>

#include <algorithm>
#include <array>
#include <cstdio>

namespace amun::threeds {

namespace {

constexpr Address kTextBase = 0x00100000U;
constexpr std::uint32_t kMaximumTextBytes = 32U * 1024U * 1024U;

const char *regionName(std::uint8_t region) noexcept {
    switch (region) {
    case CFG_REGION_JPN: return "JPN";
    case CFG_REGION_USA: return "USA";
    case CFG_REGION_EUR: return "EUR";
    case CFG_REGION_AUS: return "AUS";
    case CFG_REGION_CHN: return "CHN";
    case CFG_REGION_KOR: return "KOR";
    case CFG_REGION_TWN: return "TWN";
    default: return nullptr;
    }
}

} // namespace

IdentityResult buildGameIdentity(std::uint64_t titleId, ThreeDSMemoryReader &memory) noexcept {
    IdentityResult result;
    result.identity.titleId = titleId;
    result.identity.moduleBase = kTextBase;

    std::uint8_t region = 0;
    const Result cfgInitialized = cfguInit();
    const Result regionResult = R_SUCCEEDED(cfgInitialized)
        ? CFGU_SecureInfoGetRegion(&region)
        : cfgInitialized;
    if (R_SUCCEEDED(cfgInitialized)) cfguExit();
    if (R_FAILED(regionResult) || regionName(region) == nullptr) {
        result.detail = "CFGU did not return a recognized region";
        return result;
    }
    result.identity.region = regionName(region);

    const std::uint16_t installedVersion = CTRPluginFramework::Process::GetVersion();
    result.identity.applicationVersion = std::to_string(installedVersion);
    // Process::GetVersion() is the effective installed title version (including an
    // update when one is present). CTRPF does not expose separate base/update
    // versions, so updateVersion stays empty and packs must do the same.
    result.identity.updateVersion.clear();

    const std::uint32_t textSize = CTRPluginFramework::Process::GetTextSize();
    if (textSize == 0U || textSize > kMaximumTextBytes) {
        result.detail = "live .text size is outside the 1..32 MiB fingerprint bound";
        return result;
    }

    std::array<std::uint8_t, 4096> chunk{};
    std::uint32_t checksum = 0U;
    std::uint32_t offset = 0U;
    while (offset < textSize) {
        const std::size_t count = static_cast<std::size_t>(
            std::min<std::uint32_t>(static_cast<std::uint32_t>(chunk.size()), textSize - offset));
        const ReadResult read = memory.read(kTextBase + offset, chunk.data(), count);
        if (!read || read.bytesRead != count) {
            result.detail = "safe reader could not cover the complete live .text mapping";
            return result;
        }
        checksum = crc32(chunk.data(), count, checksum);
        offset += static_cast<std::uint32_t>(count);
    }

    char fingerprint[64]{};
    std::snprintf(fingerprint, sizeof(fingerprint), "live-text-crc32-v1:%08lX:%08lX",
                  static_cast<unsigned long>(textSize), static_cast<unsigned long>(checksum));
    result.identity.codeFingerprint = fingerprint;
    result.ok = true;
    return result;
}

} // namespace amun::threeds
