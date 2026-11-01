#pragma once

#include <cstddef>

namespace amun::threeds {

// CTRPluginFramework mounts the SD archive at "/". Keep every AMUN-owned path
// absolute so a default.3gx never inherits CTRPF's ActionReplay working directory.
inline constexpr char kRootDirectory[] = "/amun";
inline constexpr char kPackDirectory[] = "/amun/packs";
inline constexpr char kLedgerDirectory[] = "/amun/ledger";
inline constexpr char kLogDirectory[] = "/amun/logs";
inline constexpr char kConfigDirectory[] = "/amun/config";
inline constexpr char kStatusLogPath[] = "/amun/logs/platform.log";
inline constexpr char kSelfTestFlagPath[] = "/amun/config/self-test.flag";
inline constexpr char kSelfTestScratchLedgerPath[] = "/amun/ledger/platform-self-test.tmp";
inline constexpr char kPackFileName[] = "game.amunpack";
inline constexpr std::size_t kPlatformPathCapacity = 96U;

} // namespace amun::threeds
