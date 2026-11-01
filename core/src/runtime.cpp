#include "amun/runtime.hpp"

#include "amun/crc32.hpp"
#include "amun/version.hpp"

#include <algorithm>
#include <chrono>
#include <cstring>
#include <iomanip>
#include <limits>
#include <sstream>
#include <string_view>
#include <unordered_set>

namespace amun {

namespace {

bool addAddress(Address base, std::int32_t offset, Address &out) noexcept {
    const std::int64_t value = static_cast<std::int64_t>(base) + offset;
    if (value < 0 || value > std::numeric_limits<Address>::max()) return false;
    out = static_cast<Address>(value);
    return true;
}

std::string hex64(std::uint64_t value) {
    std::ostringstream stream;
    stream << std::hex << std::setfill('0') << std::setw(16) << value;
    return stream.str();
}

bool symbolUnavailable(const std::string &error) noexcept {
    return error == "unavailable symbol" || error == "unavailable history symbol" ||
           error == "unavailable delta symbol";
}

} // namespace

Runtime::Runtime(RuntimeConfig config) : config_(config) {
    if (config_.integrityMode == IntegrityMode::Live && config_.cheatStatus != CheatStatus::Inactive)
        config_.integrityMode = IntegrityMode::LiveUnverified;
    if (config_.performanceMode == PerformanceMode::Compatibility) {
        config_.fastIntervalMs = std::max<std::uint32_t>(config_.fastIntervalMs, 33U);
        config_.normalIntervalMs = std::max<std::uint32_t>(config_.normalIntervalMs, 150U);
        config_.slowIntervalMs = std::max<std::uint32_t>(config_.slowIntervalMs, 1000U);
    } else if (config_.performanceMode == PerformanceMode::Responsive) {
        config_.fastIntervalMs = std::min<std::uint32_t>(config_.fastIntervalMs, 16U);
        config_.normalIntervalMs = std::min<std::uint32_t>(config_.normalIntervalMs, 67U);
    }
}

bool Runtime::loadPack(AchievementPack pack, std::string *error) {
    const auto reject = [&](std::string detail) {
        if (error != nullptr) *error = std::move(detail);
        status_ = RuntimeStatus::PackInvalid;
        return false;
    };
    if (status_ == RuntimeStatus::Running || pack.titleId == 0 || pack.builds.empty() ||
        pack.achievements.empty()) {
        return reject("pack is incomplete or a session is active");
    }
    RuntimeLimits limits;
    if (pack.builds.size() > limits.maxBuilds || pack.symbols.size() > limits.maxSymbols ||
        pack.achievements.size() > limits.maxAchievements || pack.assets.size() > limits.maxAssets) {
        return reject("pack object count exceeds runtime limits");
    }

    std::uint64_t referencedStringBytes = 0;
    std::unordered_set<std::string_view> distinctStrings;
    distinctStrings.reserve(limits.maxStrings);
    const auto trackString = [&](const std::string &value) {
        if (value.size() > limits.maxStringBytes) return false;
        referencedStringBytes += value.size() + 1U;
        if (referencedStringBytes > limits.maxReferencedStringBytes) return false;
        distinctStrings.emplace(value);
        return distinctStrings.size() <= limits.maxStrings;
    };
    if (!trackString(pack.gameName) || !trackString(pack.profileVersion) ||
        !trackString(pack.profileLicense) || !trackString(pack.provenance)) {
        return reject("manifest strings exceed runtime limits");
    }
    std::unordered_set<std::string_view> buildIds;
    buildIds.reserve(pack.builds.size());
    for (const BuildDefinition &build : pack.builds) {
        if (build.id.empty() || build.codeFingerprint.empty() || !buildIds.emplace(build.id).second ||
            !trackString(build.id) || !trackString(build.region) ||
            !trackString(build.applicationVersion) || !trackString(build.updateVersion) ||
            !trackString(build.codeFingerprint)) {
            return reject("build identity or strings exceed runtime limits");
        }
    }

    std::uint64_t referencedBytecodeBytes = 0;
    std::uint64_t totalPatternScanBytes = 0;
    std::unordered_set<std::string_view> symbolNames;
    symbolNames.reserve(pack.symbols.size());
    for (const SymbolDefinition &symbol : pack.symbols) {
        if (symbol.name.empty() || !symbolNames.emplace(symbol.name).second ||
            !trackString(symbol.name) ||
            static_cast<std::uint8_t>(symbol.type) > static_cast<std::uint8_t>(ValueType::FixedString) ||
            static_cast<std::uint8_t>(symbol.pollClass) > static_cast<std::uint8_t>(PollClass::Static) ||
            static_cast<std::uint8_t>(symbol.resolver.kind) > static_cast<std::uint8_t>(ResolverKind::Derived) ||
            symbol.bitIndex > 7U || symbol.resolver.pointerOffsets.size() > limits.maxPointerDepth) {
            return reject("symbol metadata exceeds runtime limits");
        }
        const bool fixedBytes = symbol.type == ValueType::Bytes || symbol.type == ValueType::FixedString;
        if ((fixedBytes && (symbol.valueSize == 0 || symbol.valueSize > 16U)) ||
            (!fixedBytes && symbol.valueSize != 0)) {
            return reject(symbol.name + ": invalid fixed value size");
        }
        if (symbol.resolver.kind == ResolverKind::PointerChain &&
            symbol.resolver.pointerOffsets.empty()) {
            return reject(symbol.name + ": pointer chain is empty");
        }
        if ((!symbol.resolver.pointerXorMasks.empty() &&
             symbol.resolver.pointerXorMasks.size() + 1U != symbol.resolver.pointerOffsets.size()) ||
            ((symbol.resolver.refresh || !symbol.resolver.pointerXorMasks.empty()) &&
             symbol.resolver.kind != ResolverKind::PointerChain)) {
            return reject(symbol.name + ": invalid pointer chain options");
        }
        if (symbol.resolver.kind == ResolverKind::Pattern) {
            const PatternSpec &pattern = symbol.resolver.pattern;
            if (pattern.bytes.empty() || pattern.bytes.size() > limits.maxSignatureBytes ||
                pattern.bytes.size() != pattern.mask.size() || pattern.scanSize < pattern.bytes.size() ||
                pattern.scanSize > limits.maxPatternScanBytes ||
                static_cast<std::uint64_t>(pattern.scanStart) + pattern.scanSize >
                    std::numeric_limits<Address>::max()) {
                return reject(symbol.name + ": pattern exceeds runtime limits");
            }
            totalPatternScanBytes += pattern.scanSize;
            if (totalPatternScanBytes > limits.maxTotalPatternScanBytes)
                return reject("aggregate pattern scan bytes exceed runtime limit");
        }
        const bool derived = symbol.resolver.kind == ResolverKind::Derived;
        if (derived != !symbol.derivedBytecode.empty())
            return reject(symbol.name + ": derived bytecode does not match resolver kind");
        referencedBytecodeBytes += symbol.derivedBytecode.size();
        if (referencedBytecodeBytes > limits.maxBytecodeBytes)
            return reject("referenced bytecode bytes exceed runtime limit");
        if (derived) {
            const VmVerifyResult verified = verifyBytecode(symbol.derivedBytecode.data(),
                                                           symbol.derivedBytecode.size(),
                                                           pack.symbols.size(), limits);
            if (!verified.valid || verified.stateSlots != 0)
                return reject(symbol.name + ": invalid or stateful derived bytecode");
        }
    }

    std::uint64_t totalVmStateSlots = 0;
    std::unordered_set<std::string_view> achievementIds;
    achievementIds.reserve(pack.achievements.size());
    for (const AchievementDefinition &achievement : pack.achievements) {
        if (achievement.id.empty() || !achievementIds.emplace(achievement.id).second ||
            achievement.points > 10000U ||
            achievement.maxStack == 0 || achievement.maxStack > limits.maxVmStack ||
            achievement.stateSlots > limits.maxVmStateSlots || achievement.instructionBudget == 0 ||
            achievement.instructionBudget > limits.maxInstructionsPerAchievement ||
            achievement.prerequisites.size() > limits.maxPrerequisitesPerAchievement ||
            !trackString(achievement.id) || !trackString(achievement.title) ||
            !trackString(achievement.description) || !trackString(achievement.author) ||
            !trackString(achievement.category) || !trackString(achievement.tags) ||
            !trackString(achievement.icon)) {
            return reject(achievement.id + ": metadata exceeds runtime limits");
        }
        for (const std::string &prerequisite : achievement.prerequisites) {
            if (prerequisite.empty() || !trackString(prerequisite))
                return reject(achievement.id + ": prerequisites exceed runtime limits");
        }
        totalVmStateSlots += achievement.stateSlots;
        if (totalVmStateSlots > limits.maxTotalVmStateSlots)
            return reject("aggregate VM state slots exceed runtime limit");
        referencedBytecodeBytes += achievement.bytecode.size();
        if (referencedBytecodeBytes > limits.maxBytecodeBytes)
            return reject("referenced bytecode bytes exceed runtime limit");
        const VmVerifyResult verified = verifyBytecode(achievement.bytecode.data(),
                                                       achievement.bytecode.size(),
                                                       pack.symbols.size(), limits);
        if (!verified.valid || achievement.maxStack < verified.maximumStack ||
            achievement.stateSlots < verified.stateSlots ||
            achievement.instructionBudget < verified.instructions) {
            return reject(achievement.id + ": " +
                (verified.error.empty() ? "declared VM limits are too small" : verified.error));
        }
    }
    for (const AchievementDefinition &achievement : pack.achievements) {
        for (const std::string &prerequisite : achievement.prerequisites) {
            if (prerequisite == achievement.id || achievementIds.find(prerequisite) == achievementIds.end())
                return reject(achievement.id + ": unknown or self prerequisite");
        }
    }

    std::uint64_t totalStoredAssetBytes = 0;
    std::uint64_t totalDecodedAssetBytes = 0;
    std::unordered_set<std::string_view> assetNames;
    std::unordered_set<std::string_view> iconNames;
    assetNames.reserve(pack.assets.size());
    iconNames.reserve(pack.assets.size());
    for (const AssetDefinition &asset : pack.assets) {
        totalStoredAssetBytes += asset.encodedData.size();
        totalDecodedAssetBytes += asset.decodedSize;
        if (asset.name.empty() || !assetNames.emplace(asset.name).second ||
            !trackString(asset.name) || asset.encodedData.empty() ||
            totalStoredAssetBytes > limits.maxAssetStoredBytes || asset.decodedSize == 0 ||
            asset.decodedSize > limits.maxAssetDecodedBytes ||
            totalDecodedAssetBytes > limits.maxTotalAssetDecodedBytes ||
            static_cast<std::uint8_t>(asset.kind) < static_cast<std::uint8_t>(AssetKind::Icon) ||
            static_cast<std::uint8_t>(asset.kind) > static_cast<std::uint8_t>(AssetKind::Sound) ||
            static_cast<std::uint8_t>(asset.format) < static_cast<std::uint8_t>(AssetFormat::Rgb565) ||
            static_cast<std::uint8_t>(asset.format) > static_cast<std::uint8_t>(AssetFormat::PcmU8) ||
            static_cast<std::uint8_t>(asset.compression) > static_cast<std::uint8_t>(AssetCompression::ByteRle)) {
            return reject(asset.name + ": asset exceeds runtime limits");
        }
        if (asset.kind == AssetKind::Icon) {
            if (asset.width == 0 || asset.height == 0 || asset.width > 64U || asset.height > 64U ||
                (asset.format != AssetFormat::Rgb565 && asset.format != AssetFormat::Rgba5551) ||
                asset.decodedSize != static_cast<std::uint32_t>(asset.width) * asset.height * 2U) {
                return reject(asset.name + ": invalid icon metadata");
            }
            iconNames.emplace(asset.name);
        } else if (asset.width != 0 || asset.height != 0 || asset.format != AssetFormat::PcmU8) {
            return reject(asset.name + ": invalid sound metadata");
        }
        std::vector<std::uint8_t> decoded;
        if (!decodeAsset(asset, decoded, limits.maxAssetDecodedBytes))
            return reject(asset.name + ": malformed asset encoding");
    }
    for (const AchievementDefinition &achievement : pack.achievements) {
        if (!achievement.icon.empty() && iconNames.find(achievement.icon) == iconNames.end())
            return reject(achievement.id + ": referenced icon is absent or not an icon");
    }
    pack_ = std::move(pack);
    status_ = RuntimeStatus::Ready;
    return true;
}

RuntimeStatus Runtime::startSession(const GameIdentity &identity, MemoryReader &memory,
                                    Ledger &ledger, Clock &clock, EventSink &events) {
    if (status_ != RuntimeStatus::Ready && status_ != RuntimeStatus::Ended) return status_;
    identity_ = identity;
    buildMatch_ = matchBuild(pack_, identity_, &buildIndex_);
    if (buildMatch_ == BuildMatch::UnsupportedBuild) {
        status_ = RuntimeStatus::UnsupportedGame;
        return status_;
    }
    if (buildMatch_ == BuildMatch::UnknownBuild) {
        status_ = RuntimeStatus::ExactBuildRequired;
        return status_;
    }
    memory_ = &memory;
    ledger_ = &ledger;
    clock_ = &clock;
    events_ = &events;
    sessionId_ = hex64(identity.titleId) + "-" + hex64(clock.wallClockUnixMs()) + "-" +
                 hex64(clock.monotonicMs());

    resolved_.assign(pack_.symbols.size(), {});
    nextResolutionIndex_ = 0;
    snapshots_.assign(pack_.symbols.size(), {});
    achievementStates_.assign(pack_.achievements.size(), {});
    for (std::size_t i = 0; i < pack_.achievements.size(); ++i) {
        AchievementRuntimeState &state = achievementStates_[i];
        const AchievementDefinition &achievement = pack_.achievements[i];
        state.vm.slots.assign(achievement.stateSlots, {});
        state.unlocked = ledger.isUnlocked(achievement.id);
        state.progress = ledger.progress(achievement.id);
        state.persistedProgress = state.progress;
    }
    ledgerWritable_ = true;
    resolveSymbols();
    status_ = RuntimeStatus::Running;
    const char *cheatDetail = config_.cheatStatus == CheatStatus::Inactive ? "cheat_status=inactive" :
                              config_.cheatStatus == CheatStatus::Active ? "cheat_status=active" :
                                                                          "cheat_status=unknown";
    const LedgerStatus sessionStored = appendEvent(LedgerEventType::SessionStarted, {}, 0, cheatDetail);
    if (sessionStored != LedgerStatus::Ok && sessionStored != LedgerStatus::Duplicate) {
        status_ = RuntimeStatus::LedgerFailure;
        return status_;
    }
    return status_;
}

bool Runtime::resolveSymbols() {
    bool allRequired = true;
    for (std::size_t i = 0; i < pack_.symbols.size(); ++i) {
        if (!resolveSymbol(i)) {
            allRequired = false;
            resolved_[i].attempted = true;
            resolved_[i].lastRead = clock_->monotonicMs();
            if (events_ != nullptr) events_->onWarning("memory", "failed to resolve symbol " + pack_.symbols[i].name);
        }
    }
    return allRequired;
}

bool Runtime::resolveSymbol(std::size_t index, TickMetrics *metrics) {
    const SymbolDefinition &symbol = pack_.symbols[index];
    ResolvedSymbol &resolved = resolved_[index];
    Address address = 0;
    switch (symbol.resolver.kind) {
    case ResolverKind::Absolute:
        address = symbol.resolver.address;
        break;
    case ResolverKind::ModuleRelative:
        if (!addAddress(identity_.moduleBase, symbol.resolver.moduleOffset, address)) return false;
        break;
    case ResolverKind::PointerChain: {
        address = symbol.resolver.address;
        if (address == 0 && !addAddress(identity_.moduleBase, symbol.resolver.moduleOffset, address)) return false;
        if (symbol.resolver.pointerOffsets.empty()) return false;
        for (std::size_t depth = 0; depth < symbol.resolver.pointerOffsets.size(); ++depth) {
            if (!addAddress(address, symbol.resolver.pointerOffsets[depth], address)) return false;
            if (depth + 1U < symbol.resolver.pointerOffsets.size()) {
                std::uint8_t bytes[4]{};
                if (!memory_->isRangeReadable(address, sizeof(bytes))) return false;
                const ReadResult read = memory_->read(address, bytes, sizeof(bytes));
                if (metrics != nullptr) {
                    ++metrics->reads;
                    metrics->bytesRead += static_cast<std::uint32_t>(read.bytesRead);
                }
                if (!read || read.bytesRead != sizeof(bytes)) return false;
                address = static_cast<Address>(bytes[0]) |
                          (static_cast<Address>(bytes[1]) << 8U) |
                          (static_cast<Address>(bytes[2]) << 16U) |
                          (static_cast<Address>(bytes[3]) << 24U);
                if (!symbol.resolver.pointerXorMasks.empty())
                    address ^= symbol.resolver.pointerXorMasks[depth];
                if (address == 0) return false;
            }
        }
        break;
    }
    case ResolverKind::Pattern: {
        const PatternResult found = scanPattern(*memory_, symbol.resolver.pattern);
        if (found.status != PatternStatus::Found) return false;
        address = found.address;
        break;
    }
    case ResolverKind::Derived:
        if (symbol.derivedBytecode.empty()) return false;
        {
            const VmVerifyResult verified = verifyBytecode(symbol.derivedBytecode.data(),
                                                           symbol.derivedBytecode.size(),
                                                           pack_.symbols.size());
            if (!verified.valid || verified.stateSlots != 0) return false;
            resolved.derivedStack = std::max<std::uint16_t>(verified.maximumStack, 1);
            resolved.derivedInstructions = verified.instructions;
        }
        resolved.resolved = true;
        return true;
    }
    const std::size_t width = scalarWidth(symbol.type) != 0 ? scalarWidth(symbol.type) : symbol.valueSize;
    if (width == 0 || !memory_->isRangeReadable(address, width)) return false;
    resolved.address = address;
    resolved.resolved = true;
    return true;
}

void Runtime::retryUnresolvedSymbols(TickMetrics &metrics, Milliseconds now) {
    std::uint32_t attempts = 0;
    for (std::size_t visited = 0; visited < resolved_.size() &&
         attempts < config_.maxSymbolResolutionsPerTick; ++visited) {
        const std::size_t index = nextResolutionIndex_;
        nextResolutionIndex_ = (nextResolutionIndex_ + 1U) % resolved_.size();
        ResolvedSymbol &resolved = resolved_[index];
        const SymbolDefinition &symbol = pack_.symbols[index];
        // Pattern scans stay startup-only. Retrying one can scan megabytes on the
        // game thread. Cheap resolvers are bounded, throttled, and visited fairly.
        if (resolved.resolved || resolved.disabled ||
            (symbol.resolver.kind != ResolverKind::Absolute &&
             symbol.resolver.kind != ResolverKind::ModuleRelative &&
             symbol.resolver.kind != ResolverKind::PointerChain) ||
            !pollDue(symbol, resolved, now)) continue;
        ++attempts;
        resolved.attempted = true;
        resolved.lastRead = now;
        if (!resolveSymbol(index, &metrics)) {
            ++metrics.failures;
            continue;
        }
        // Let this tick establish the first real sample; never invent a zero
        // baseline while the game's heap or pointer chain is unavailable.
        resolved.attempted = false;
        events_->onWarning("memory", "resolved previously unavailable symbol " + symbol.name);
    }
}

bool Runtime::pollDue(const SymbolDefinition &symbol, const ResolvedSymbol &resolved,
                      Milliseconds now) const noexcept {
    if (!resolved.attempted) return true;
    if (symbol.pollClass == PollClass::Static && resolved.sampled && !symbol.resolver.refresh) return false;
    std::uint32_t interval = config_.normalIntervalMs;
    if (symbol.pollClass == PollClass::Fast) interval = config_.fastIntervalMs;
    else if (symbol.pollClass == PollClass::Slow || symbol.pollClass == PollClass::Static)
        interval = config_.slowIntervalMs;
    return now < resolved.lastRead || now - resolved.lastRead >= interval;
}

bool Runtime::sampleSymbol(std::size_t index, TickMetrics &metrics, Milliseconds now) {
    ResolvedSymbol &resolved = resolved_[index];
    const SymbolDefinition &symbol = pack_.symbols[index];
    if (!resolved.resolved || resolved.disabled || !pollDue(symbol, resolved, now)) return resolved.sampled;
    // Failed attempts obey the same cadence as successful samples.
    resolved.attempted = true;
    resolved.lastRead = now;
    if (symbol.resolver.refresh) {
        const Address previousAddress = resolved.address;
        if (!resolveSymbol(index, &metrics)) {
            // Scene-owned allocations legitimately disappear. No stale reads,
            // invented history, permanent disable, or repeated warning flood.
            snapshots_[index] = {};
            resolved.sampled = false;
            return false;
        }
        if (previousAddress != resolved.address && resolved.sampled) {
            // Expose an invalid tick so dependent state machines cannot join
            // observations from two different objects into one achievement.
            snapshots_[index] = {};
            resolved.sampled = false;
            return false;
        }
    }
    if (symbol.resolver.kind == ResolverKind::Derived) {
        VmState expressionState;
        const VmEvalResult evaluated = evaluateBytecode(symbol.derivedBytecode.data(),
                                                        symbol.derivedBytecode.size(), snapshots_, now,
                                                        expressionState, resolved.derivedInstructions,
                                                        resolved.derivedStack);
        if (!evaluated.valid) {
            snapshots_[index].valid = false;
            if (symbolUnavailable(evaluated.error)) return false;
            ++metrics.failures;
            ++resolved.consecutiveFailures;
            if (resolved.consecutiveFailures >= config_.maxConsecutiveReadFailures) {
                resolved.disabled = true;
                events_->onWarning("derived", "disabled repeatedly failing symbol " + symbol.name);
            }
            return false;
        }
        resolved.consecutiveFailures = 0;
        resolved.lastRead = now;
        resolved.sampled = true;
        SymbolSnapshot &snapshot = snapshots_[index];
        if (snapshot.valid) {
            snapshot.previous = snapshot.current;
            snapshot.hasPrevious = true;
        } else {
            if (!snapshot.hasInitial) snapshot.initial = evaluated.value;
            snapshot.previous = evaluated.value;
            snapshot.hasInitial = true;
            snapshot.hasPrevious = false;
        }
        snapshot.current = evaluated.value;
        snapshot.valid = true;
        return true;
    }
    const std::size_t width = scalarWidth(symbol.type) != 0 ? scalarWidth(symbol.type) : symbol.valueSize;
    std::uint8_t bytes[16]{};
    ++metrics.reads;
    const ReadResult read = memory_->read(resolved.address, bytes, width);
    metrics.bytesRead += static_cast<std::uint32_t>(read.bytesRead);
    Scalar value;
    if (!read || read.bytesRead != width || !decodeScalarLittleEndian(symbol.type, bytes, width, value)) {
        ++metrics.failures;
        ++resolved.consecutiveFailures;
        if (symbol.resolver.refresh) snapshots_[index] = {};
        else snapshots_[index].valid = false;
        if (resolved.consecutiveFailures >= config_.maxConsecutiveReadFailures && !symbol.resolver.refresh) {
            resolved.disabled = true;
            events_->onWarning("memory", "disabled repeatedly failing symbol " + symbol.name);
        }
        return false;
    }
    if (symbol.type == ValueType::Bit) {
        value = Scalar::fromInteger((bytes[0] & (1U << symbol.bitIndex)) != 0U ? 1 : 0);
    }
    resolved.consecutiveFailures = 0;
    resolved.lastRead = now;
    resolved.sampled = true;
    SymbolSnapshot &snapshot = snapshots_[index];
    if (snapshot.valid) {
        snapshot.previous = snapshot.current;
        snapshot.hasPrevious = true;
    } else {
        if (!snapshot.hasInitial) snapshot.initial = value;
        snapshot.previous = value;
        snapshot.hasInitial = true;
        snapshot.hasPrevious = false;
    }
    snapshot.current = value;
    snapshot.valid = true;
    return true;
}

bool Runtime::prerequisitesMet(const AchievementDefinition &achievement) const noexcept {
    if (achievement.prerequisites.empty()) return true;
    const std::size_t requiredCount =
        achievement.prerequisiteMinCount == 0
            ? achievement.prerequisites.size()
            : static_cast<std::size_t>(achievement.prerequisiteMinCount);
    std::size_t met = 0;
    for (const std::string &required : achievement.prerequisites) {
        if (ledger_->isUnlocked(required)) {
            ++met;
            if (met >= requiredCount) return true;
        }
    }
    return met >= requiredCount;
}

std::string Runtime::makeEventId(LedgerEventType type, const std::string &achievementId,
                                 Milliseconds now) const {
    std::string material = sessionId_ + ':' + std::to_string(static_cast<unsigned>(type)) + ':' +
                           achievementId + ':' + std::to_string(now);
    std::uint8_t uuid[16]{};
    for (unsigned part = 0; part < 4U; ++part) {
        const std::uint32_t hash = crc32(material.data(), material.size(), 0x9E3779B9U * (part + 1U));
        for (unsigned byte = 0; byte < 4U; ++byte)
            uuid[part * 4U + byte] = static_cast<std::uint8_t>(hash >> (byte * 8U));
    }
    uuid[6] = static_cast<std::uint8_t>((uuid[6] & 0x0FU) | 0x50U);
    uuid[8] = static_cast<std::uint8_t>((uuid[8] & 0x3FU) | 0x80U);
    std::ostringstream stream;
    stream << std::hex << std::setfill('0');
    for (unsigned i = 0; i < 16U; ++i) {
        stream << std::setw(2) << static_cast<unsigned>(uuid[i]);
        if (i == 3 || i == 5 || i == 7 || i == 9) stream << '-';
    }
    return stream.str();
}

LedgerStatus Runtime::appendEvent(LedgerEventType type, const std::string &achievementId,
                                  std::uint32_t progress, const std::string &detail) {
    if (!ledgerWritable_) return LedgerStatus::NotLoaded;
    const Milliseconds now = clock_->monotonicMs();
    LedgerEvent event;
    event.type = type;
    event.wallClockUnixMs = clock_->wallClockUnixMs();
    event.integrity = config_.integrityMode;
    event.progress = progress;
    event.profileHash = pack_.profileHash;
    event.eventId = makeEventId(type, achievementId, now);
    event.achievementId = achievementId;
    event.gameBuildId = buildIndex_ < pack_.builds.size() ? pack_.builds[buildIndex_].id : std::string{};
    event.runtimeVersion = kRuntimeVersion;
    event.sessionId = sessionId_;
    event.detail = detail;
    const LedgerStatus stored = ledger_->append(std::move(event));
    // Durability failures are session-fatal. Retrying the same unlock every frame can
    // extend a torn tail, flood diagnostics, and delay an in-process loader shutdown.
    // A fresh session reloads/recovers the ledger and resets this latch.
    if (stored != LedgerStatus::Ok && stored != LedgerStatus::Duplicate)
        ledgerWritable_ = false;
    return stored;
}

TickMetrics Runtime::tick() {
    TickMetrics metrics;
    if (status_ != RuntimeStatus::Running) return metrics;
    const auto started = std::chrono::steady_clock::now();
    const Milliseconds now = clock_->monotonicMs();
    retryUnresolvedSymbols(metrics, now);
    for (std::size_t i = 0; i < pack_.symbols.size(); ++i) sampleSymbol(i, metrics, now);

    for (std::size_t i = 0; i < pack_.achievements.size(); ++i) {
        AchievementRuntimeState &state = achievementStates_[i];
        const AchievementDefinition &achievement = pack_.achievements[i];
        if (state.unlocked || state.disabled || !prerequisitesMet(achievement)) continue;
        if (metrics.instructionsExecuted > config_.maxInstructionsPerTick ||
            achievement.instructionBudget > config_.maxInstructionsPerTick - metrics.instructionsExecuted) {
            for (AchievementRuntimeState &affected : achievementStates_) {
                if (!affected.unlocked) {
                    affected.disabled = true;
                    affected.disableReason = "runtime instruction budget exceeded";
                }
            }
            status_ = RuntimeStatus::ProfileDisabled;
            events_->onWarning("vm", "profile disabled: runtime instruction budget exceeded");
            break;
        }
        ++metrics.achievementsEvaluated;
        VmEvalResult evaluation = evaluateBytecode(achievement.bytecode.data(), achievement.bytecode.size(),
                                                   snapshots_, now, state.vm,
                                                   achievement.instructionBudget, achievement.maxStack);
        metrics.instructionsExecuted += evaluation.instructions;
        if (!evaluation.valid) {
            if (symbolUnavailable(evaluation.error)) {
                // A missing game allocation is not invalid bytecode. Discard
                // partial counters/timers so an unavailable interval cannot
                // count toward an unlock, then wait for a valid sample.
                state.vm.reset();
                continue;
            }
            ++metrics.failures;
            if (evaluation.error.find("instruction budget") != std::string::npos) {
                for (AchievementRuntimeState &affected : achievementStates_) {
                    if (!affected.unlocked) {
                        affected.disabled = true;
                        affected.disableReason = evaluation.error;
                    }
                }
                status_ = RuntimeStatus::ProfileDisabled;
            } else {
                state.disabled = true;
                state.disableReason = evaluation.error;
            }
            events_->onWarning("vm", achievement.id + ": " + evaluation.error);
            if (status_ == RuntimeStatus::ProfileDisabled) break;
            continue;
        }
        if (achievement.progressTarget != 0 && evaluation.progress != state.progress) {
            state.progress = evaluation.progress;
            events_->onProgress(achievement.id, state.progress, achievement.progressTarget);
            const std::uint32_t meaningfulDelta = std::max<std::uint32_t>(
                1U, achievement.progressTarget / 100U);
            const bool meaningful = state.progress >= state.persistedProgress + meaningfulDelta ||
                                    state.progress >= achievement.progressTarget;
            const bool writeDue = now < state.lastProgressWrite ||
                                  now - state.lastProgressWrite >= config_.progressWriteIntervalMs ||
                                  state.progress >= achievement.progressTarget;
            if (meaningful && writeDue && ledgerWritable_) {
                const LedgerStatus stored = appendEvent(LedgerEventType::ProgressCheckpoint,
                                                        achievement.id, state.progress);
                if (stored == LedgerStatus::Ok || stored == LedgerStatus::Duplicate) {
                    state.persistedProgress = state.progress;
                    state.lastProgressWrite = now;
                } else {
                    events_->onWarning("ledger", "could not persist progress for " + achievement.id);
                }
            }
        }
        if (!evaluation.condition || !ledgerWritable_) continue;
        const LedgerStatus stored = appendEvent(LedgerEventType::AchievementUnlocked,
                                                achievement.id, state.progress);
        if (stored == LedgerStatus::Ok) {
            state.unlocked = true;
            events_->onUnlock({achievement.id, achievement.title, achievement.description,
                               achievement.points, achievement.secret, clock_->wallClockUnixMs()});
        } else if (stored == LedgerStatus::Duplicate) {
            state.unlocked = true;
        } else {
            ++metrics.failures;
            events_->onWarning("ledger", "unlock was detected but not durably stored: " + achievement.id);
        }
    }
    const auto ended = std::chrono::steady_clock::now();
    metrics.elapsedMicroseconds = static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::microseconds>(ended - started).count());
    if (metrics.elapsedMicroseconds > config_.maxTickMicroseconds) {
        events_->onWarning("performance", "tick exceeded configured host-side budget");
    }
    return metrics;
}

void Runtime::endSession() {
    if (status_ != RuntimeStatus::Running && status_ != RuntimeStatus::ProfileDisabled) return;
    if (ledgerWritable_) {
        const LedgerStatus stored = appendEvent(LedgerEventType::SessionEnded, {}, 0);
        if (stored != LedgerStatus::Ok && stored != LedgerStatus::Duplicate)
            events_->onWarning("ledger", "could not store session end");
    }
    status_ = RuntimeStatus::Ended;
    memory_ = nullptr;
    ledger_ = nullptr;
    clock_ = nullptr;
    events_ = nullptr;
    ledgerWritable_ = false;
}

std::size_t Runtime::estimatedMemoryBytes() const noexcept {
    std::size_t total = sizeof(*this);
    total += resolved_.capacity() * sizeof(ResolvedSymbol);
    total += snapshots_.capacity() * sizeof(SymbolSnapshot);
    total += achievementStates_.capacity() * sizeof(AchievementRuntimeState);
    total += sessionId_.capacity() + identity_.region.capacity() + identity_.applicationVersion.capacity() +
             identity_.updateVersion.capacity() + identity_.codeFingerprint.capacity();
    total += pack_.gameName.capacity() + pack_.profileVersion.capacity() + pack_.profileLicense.capacity() +
             pack_.provenance.capacity();
    total += pack_.builds.capacity() * sizeof(BuildDefinition);
    for (const BuildDefinition &build : pack_.builds)
        total += build.id.capacity() + build.region.capacity() + build.applicationVersion.capacity() +
                 build.updateVersion.capacity() + build.codeFingerprint.capacity();
    total += pack_.symbols.capacity() * sizeof(SymbolDefinition);
    for (const SymbolDefinition &symbol : pack_.symbols)
        total += symbol.name.capacity() + symbol.resolver.pointerOffsets.capacity() * sizeof(std::int32_t) +
                 symbol.resolver.pointerXorMasks.capacity() * sizeof(std::uint32_t) +
                 symbol.resolver.pattern.bytes.capacity() + symbol.resolver.pattern.mask.capacity() +
                 symbol.derivedBytecode.capacity();
    total += pack_.achievements.capacity() * sizeof(AchievementDefinition);
    for (std::size_t i = 0; i < pack_.achievements.size(); ++i) {
        const AchievementDefinition &achievement = pack_.achievements[i];
        total += achievement.id.capacity() + achievement.title.capacity() + achievement.description.capacity() +
                 achievement.author.capacity() + achievement.category.capacity() + achievement.tags.capacity() +
                 achievement.icon.capacity() + achievement.bytecode.capacity();
        total += achievement.prerequisites.capacity() * sizeof(std::string);
        for (const std::string &prerequisite : achievement.prerequisites) total += prerequisite.capacity();
        if (i < achievementStates_.size())
            total += achievementStates_[i].vm.slots.capacity() * sizeof(VmSlotState) +
                     achievementStates_[i].disableReason.capacity();
    }
    total += pack_.assets.capacity() * sizeof(AssetDefinition);
    for (const AssetDefinition &asset : pack_.assets)
        total += asset.name.capacity() + asset.encodedData.capacity();
    return total;
}

RuntimeSummary Runtime::summary() const noexcept {
    RuntimeSummary value;
    std::uint16_t scoredTotal = 0;
    for (std::size_t i = 0; i < pack_.achievements.size(); ++i) {
        const AchievementDefinition &achievement = pack_.achievements[i];
        value.pointsTotal += achievement.points;
        // Zero-point ledger/helper achievements are omitted from completion %.
        if (achievement.points == 0) continue;
        ++scoredTotal;
        const bool unlocked = i < achievementStates_.size() && achievementStates_[i].unlocked;
        if (unlocked) {
            ++value.achievementsUnlocked;
            value.pointsUnlocked += achievement.points;
        }
    }
    value.achievementsTotal = scoredTotal;
    if (value.achievementsTotal != 0) {
        value.completionPercent = static_cast<std::uint8_t>(
            (static_cast<std::uint32_t>(value.achievementsUnlocked) * 100U) /
            value.achievementsTotal);
    }
    return value;
}

} // namespace amun
