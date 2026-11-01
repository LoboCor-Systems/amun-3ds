#include "amun/3ds/clock.hpp"
#include "amun/3ds/game_identity.hpp"
#include "amun/3ds/lifecycle.hpp"
#include "amun/3ds/menu_policy.hpp"
#include "amun/3ds/memory_reader.hpp"
#include "amun/3ds/network_policy.hpp"
#include "amun/3ds/paths.hpp"
#include "amun/3ds/runtime_policy.hpp"
#include "amun/3ds/title_gate.hpp"
#include "amun/metal_tier.hpp"
#include "amun/pack.hpp"
#include "amun/runtime.hpp"
#include "amun/version.hpp"
#include "ctrpf_ledger.hpp"
#include "event_sink.hpp"
#include "pack_loader.hpp"
#include "sd_status_log.hpp"
#include "trophy_overlay.hpp"

#include <3ds.h>
#include <CTRPluginFramework.hpp>

#include <cstdio>
#include <algorithm>
#include <string>
#include <utility>
#include <vector>

namespace CTRPluginFramework {

namespace {

using amun::AchievementPack;
using amun::BuildMatch;
using amun::CheatStatus;
using amun::IntegrityMode;
using amun::Runtime;
using amun::RuntimeStatus;
using amun::threeds::CtrpfLedger;
using amun::threeds::IdentityResult;
using amun::threeds::LifecycleCoordinator;
using amun::threeds::LifecycleEvent;
using amun::threeds::LifecycleHooks;
using amun::threeds::PackProbe;
using amun::threeds::SdStatusLog;
using amun::threeds::ThreeDSClock;
using amun::threeds::ThreeDSEventSink;
using amun::threeds::ThreeDSMemoryReader;

LifecycleCoordinator *gLifecycle = nullptr;

class CtrpfPackProbe final : public PackProbe {
public:
    bool exists(const char *absolutePath) const noexcept override {
        return absolutePath != nullptr && File::Exists(absolutePath) == 1;
    }
};

struct FlushContext {
    SdStatusLog *statusLog{nullptr};
    CtrpfLedger *ledger{nullptr};
};

void appendLifecycleLine(void *context, const char *line) noexcept {
    auto *state = static_cast<FlushContext *>(context);
    if (state != nullptr && state->statusLog != nullptr) state->statusLog->appendLine(line);
}

void onPause(void *context) noexcept { appendLifecycleLine(context, "lifecycle: pause"); }
void onResume(void *context) noexcept { appendLifecycleLine(context, "lifecycle: resume"); }
void onStop(void *context) noexcept { appendLifecycleLine(context, "lifecycle: stop"); }
bool onFlush(void *context) noexcept {
    auto *state = static_cast<FlushContext *>(context);
    if (state == nullptr) return true;
    const bool ledgerOk = state->ledger == nullptr || state->ledger->flush();
    const bool logOk = state->statusLog == nullptr || !state->statusLog->isReady() ||
                       state->statusLog->flush();
    return ledgerOk && logOk;
}

void onProcessEvent(Process::Event event) {
    if (gLifecycle == nullptr) return;
    switch (event) {
    case Process::Event::EXIT: gLifecycle->handle(LifecycleEvent::Exit); break;
    case Process::Event::SLEEP_ENTER: gLifecycle->handle(LifecycleEvent::SleepEnter); break;
    case Process::Event::SLEEP_EXIT: gLifecycle->handle(LifecycleEvent::SleepExit); break;
    case Process::Event::HOME_ENTER: gLifecycle->handle(LifecycleEvent::HomeEnter); break;
    case Process::Event::HOME_EXIT: gLifecycle->handle(LifecycleEvent::HomeExit); break;
    case Process::Event::SWAP_ENTER: gLifecycle->handle(LifecycleEvent::SwapEnter); break;
    case Process::Event::SWAP_EXIT: gLifecycle->handle(LifecycleEvent::SwapExit); break;
    }
}

const char *runtimeStatusName(RuntimeStatus status) noexcept {
    switch (status) {
    case RuntimeStatus::Idle: return "idle";
    case RuntimeStatus::Ready: return "ready";
    case RuntimeStatus::Running: return "running";
    case RuntimeStatus::ExactBuildRequired: return "exact build required";
    case RuntimeStatus::UnsupportedGame: return "unsupported game";
    case RuntimeStatus::SymbolResolutionFailed: return "symbol resolution failed";
    case RuntimeStatus::LedgerFailure: return "ledger failure";
    case RuntimeStatus::PackInvalid: return "pack invalid";
    case RuntimeStatus::ProfileDisabled: return "profile disabled";
    case RuntimeStatus::Ended: return "ended";
    }
    return "unknown";
}

const char *buildMatchName(BuildMatch match) noexcept {
    switch (match) {
    case BuildMatch::ExactSupportedBuild: return "exact";
    case BuildMatch::CompatibleSupportedBuild: return "compatible";
    case BuildMatch::UnknownBuild: return "unknown";
    case BuildMatch::UnsupportedBuild: return "unsupported";
    }
    return "unknown";
}

class ObserverSession {
public:
    ObserverSession(std::uint64_t titleId, LifecycleCoordinator &lifecycle,
                    SdStatusLog &statusLog)
        : titleId_(titleId), lifecycle_(lifecycle), statusLog_(statusLog),
          eventSink_(&statusLog), ledger_(amun::threeds::ledgerPathForTitle(titleId)),
          runtime_(amun::threeds::old2dsRuntimeConfig()) {}

    CtrpfLedger &ledger() noexcept { return ledger_; }

    void initialize(const char *packPath) {
        auto loaded = amun::threeds::loadPackFromSd(
            packPath, amun::threeds::old2dsPackLimits());
        packBytes_ = loaded.bytes;
        if (!loaded.ok) {
            detail_ = "pack: " + loaded.detail;
            logDetail();
            return;
        }
        packParsed_ = true;
        AchievementPack pack = std::move(loaded.pack);
        if (pack.titleId != titleId_) {
            detail_ = "pack title ID does not equal the running full title ID";
            logDetail();
            return;
        }
        packTitleMatched_ = true;

        identityResult_ = amun::threeds::buildGameIdentity(titleId_, memory_);
        if (!identityResult_.ok) {
            detail_ = "identity: " + identityResult_.detail;
            logDetail();
            return;
        }
        identityReady_ = true;

        std::string runtimeError;
        if (!runtime_.loadPack(std::move(pack), &runtimeError)) {
            detail_ = "runtime rejected pack: " + runtimeError;
            logDetail();
            return;
        }
        runtimePackReady_ = true;

        const BuildMatch preflight = amun::matchBuild(runtime_.pack(), identityResult_.identity);
        buildMatch_ = preflight;
        if (preflight == BuildMatch::UnknownBuild || preflight == BuildMatch::UnsupportedBuild) {
            // startSession repeats this gate before assigning MemoryReader or
            // resolving symbols: unknown builds therefore perform zero profile reads.
            (void)runtime_.startSession(identityResult_.identity, memory_, ledger_, clock_, eventSink_);
            detail_ = preflight == BuildMatch::UnknownBuild
                ? "unknown fingerprint/version: zero profile reads"
                : "pack does not support this title identity";
            logDetail();
            return;
        }

        const amun::LedgerLoadResult ledgerLoad = ledger_.load();
        if (!ledgerLoad) {
            detail_ = "ledger load failed: " + ledgerLoad.detail;
            logDetail();
            return;
        }
        ledgerReady_ = true;
        recoveredLedgerTail_ = ledgerLoad.truncatedTail;
        const RuntimeStatus started = runtime_.startSession(
            identityResult_.identity, memory_, ledger_, clock_, eventSink_);
        if (started != RuntimeStatus::Running) {
            detail_ = std::string("runtime start: ") + runtimeStatusName(started);
            logDetail();
            return;
        }
        detail_ = "observer running; game memory is read-only";
        logDetail();
        amun::threeds::installTrophyOverlay();
        (void)OSD::Notify("AMUN observer running");
    }

    void attachStatusEntries(MenuEntry *runtimeEntry, MenuEntry *selfTestEntry) noexcept {
        runtimeEntry_ = runtimeEntry;
        selfTestEntry_ = selfTestEntry;
        refreshMenu(true);
    }

    void attachAchievementBrowser(MenuFolder *browser) {
        achievementBrowser_ = browser;
        achievementFolders_.clear();
        if (browser == nullptr || !runtimePackReady_) return;
        constexpr std::size_t kBrowserEntryLimit = 128U;
        const auto &achievements = runtime_.pack().achievements;
        const std::size_t shown = std::min(achievements.size(), kBrowserEntryLimit);
        achievementFolders_.reserve(shown);
        for (std::size_t i = 0; i < shown; ++i) {
            auto *folder = new MenuFolder("Achievement");
            browser->Append(folder);
            achievementFolders_.push_back(folder);
        }
        char note[160]{};
        std::snprintf(note, sizeof(note), "Read-only achievement browser. Showing %lu of %lu entries.",
                      static_cast<unsigned long>(shown),
                      static_cast<unsigned long>(achievements.size()));
        browser->Note() = note;
        refreshAchievementBrowser();
    }

    void tick() noexcept {
        if (lifecycle_.isStopping()) return;
        const amun::Milliseconds now = clock_.monotonicMs();
        const bool tickDue = nextTickAt_ == 0U || now < lastTickAt_ || now >= nextTickAt_;
        if (tickDue && !lifecycle_.isPaused() && !Process::IsPaused() &&
            runtime_.status() == RuntimeStatus::Running) {
            const amun::TickMetrics metrics = runtime_.tick();
            totalReads_ += metrics.reads;
            totalReadBytes_ += metrics.bytesRead;
            totalFailures_ += metrics.failures;
            lastTickMicros_ = metrics.elapsedMicroseconds;
            lastTickAt_ = now;
            nextTickAt_ = now + amun::threeds::nextTickDelayMs(metrics.elapsedMicroseconds);
            recordTickPerformance(metrics);
        }
        eventSink_.pump(now);
        // The menu text is rebuilt only when the menu opens (onMenuOpening); rewriting every
        // achievement entry on a timer starved the game on an original 2DS.
    }

    // CTRPF OnOpening hook: the game is paused while the menu is open, so refresh here.
    void onMenuOpening() noexcept { refreshMenu(true); }

    void shutdown() noexcept {
        runtime_.endSession();
        (void)ledger_.flush();
        statusLog_.appendLine("shutdown: runtime ended; storage flush completed");
        (void)statusLog_.flush();
    }

private:
    // One "perf:" line per kPerfWindowTicks ticks so the next hardware run shows real timings.
    void recordTickPerformance(const amun::TickMetrics &metrics) noexcept {
        perfElapsedTotal_ += metrics.elapsedMicroseconds;
        perfElapsedMax_ = std::max(perfElapsedMax_, metrics.elapsedMicroseconds);
        perfReads_ += metrics.reads;
        if (++perfTicks_ < kPerfWindowTicks) return;
        char line[160]{};
        std::snprintf(line, sizeof(line),
                      "perf: ticks=%lu avg=%lluus max=%lluus reads/tick=%lu",
                      static_cast<unsigned long>(perfTicks_),
                      static_cast<unsigned long long>(perfElapsedTotal_ / perfTicks_),
                      static_cast<unsigned long long>(perfElapsedMax_),
                      static_cast<unsigned long>(perfReads_ / perfTicks_));
        statusLog_.appendLine(line);
        perfTicks_ = 0U;
        perfElapsedTotal_ = 0U;
        perfElapsedMax_ = 0U;
        perfReads_ = 0U;
    }

    void logDetail() noexcept {
        statusLog_.appendLine(detail_.c_str());
        if (identityReady_) {
            const std::string line = "identity: region=" + identityResult_.identity.region +
                " effective-version=" + identityResult_.identity.applicationVersion +
                " fingerprint=" + identityResult_.identity.codeFingerprint;
            statusLog_.appendLine(line.c_str());
        }
        (void)statusLog_.flush();
    }

    void refreshMenu(bool force) noexcept {
        if (runtimeEntry_ == nullptr || selfTestEntry_ == nullptr) return;
        const amun::Milliseconds now = clock_.monotonicMs();
        if (!force && lastMenuRefresh_ != 0U && now >= lastMenuRefresh_ &&
            now - lastMenuRefresh_ < 1000U) return;
        lastMenuRefresh_ = now;

        const amun::RuntimeSummary summary = runtime_.summary();
        const std::string metals = metalTallyLine();
        char runtimeNote[512]{};
        std::snprintf(runtimeNote, sizeof(runtimeNote),
                      "Status: %s\nBuild: %s\nUnlocked: %u/%u (%u%%), points %lu/%lu\n%s"
                      "Reads: %lu (%lu bytes), failures: %lu\nLast tick: %llu us\n%s",
                      runtimeStatusName(runtime_.status()), buildMatchName(buildMatch_),
                      static_cast<unsigned>(summary.achievementsUnlocked),
                      static_cast<unsigned>(summary.achievementsTotal),
                      static_cast<unsigned>(summary.completionPercent),
                      static_cast<unsigned long>(summary.pointsUnlocked),
                      static_cast<unsigned long>(summary.pointsTotal), metals.c_str(),
                      static_cast<unsigned long>(totalReads_),
                      static_cast<unsigned long>(totalReadBytes_),
                      static_cast<unsigned long>(totalFailures_),
                      static_cast<unsigned long long>(lastTickMicros_), detail_.c_str());
        runtimeEntry_->Note() = runtimeNote;
        runtimeEntry_->RefreshNote();

        char selfTest[512]{};
        const std::string fingerprint = identityReady_ ? identityResult_.identity.codeFingerprint : "unavailable";
        std::snprintf(selfTest, sizeof(selfTest),
                      "Observer-only platform self-test\nFull TID: %016llX\n"
                      "Pack: %s (%lu bytes), TID gate: %s\nIdentity: %s\n"
                      "Ledger: %s%s\nMemory guard: svcQueryMemory + bounded copies\n"
                      "Networking: compiled out\nAMUN game-memory writes: none\nFingerprint: %s",
                      static_cast<unsigned long long>(titleId_), packParsed_ ? "parsed" : "failed",
                      static_cast<unsigned long>(packBytes_), packTitleMatched_ ? "pass" : "fail",
                      identityReady_ ? "pass" : "fail", ledgerReady_ ? "loaded" : "not opened",
                      recoveredLedgerTail_ ? " (torn tail recovered)" : "", fingerprint.c_str());
        selfTestEntry_->Note() = selfTest;
        selfTestEntry_->RefreshNote();
        refreshAchievementBrowser();
    }

    // "Metals: Bronze 3/6, Silver 10/20\n" for ranked tiers present in the pack;
    // empty when the pack has no scored achievements. See docs/metal-tiers.md.
    std::string metalTallyLine() const {
        amun::MetalTierTally tally;
        const auto &achievements = runtime_.pack().achievements;
        const auto &states = runtime_.achievementStates();
        for (std::size_t i = 0; i < achievements.size(); ++i)
            tally.add(achievements[i].points, i < states.size() && states[i].unlocked);
        std::string line;
        for (const amun::MetalTierBand &band : amun::kMetalTierBands) {
            const auto index = static_cast<std::size_t>(band.tier);
            if (tally.total[index] == 0U) continue;
            char item[32]{};
            std::snprintf(item, sizeof(item), "%s%s %u/%u", line.empty() ? "Metals: " : ", ",
                          band.name, static_cast<unsigned>(tally.unlocked[index]),
                          static_cast<unsigned>(tally.total[index]));
            line += item;
        }
        if (!line.empty()) line += '\n';
        return line;
    }

    // Coloured "[Silver] " menu tag in the tier body colour; unranked gets none.
    static std::string metalMenuTag(std::uint16_t points) {
        const amun::MetalTierBand *band = amun::metalTierBand(amun::metalTierFor(points));
        if (band == nullptr) return {};
        return std::string(Color(band->mid.r, band->mid.g, band->mid.b)) + "[" + band->name + "] " +
               ResetColor();
    }

    void refreshAchievementBrowser() noexcept {
        if (achievementBrowser_ == nullptr || achievementFolders_.empty()) return;
        const auto &achievements = runtime_.pack().achievements;
        const auto &states = runtime_.achievementStates();
        const std::size_t count = std::min(achievementFolders_.size(), achievements.size());
        for (std::size_t i = 0; i < count; ++i) {
            const auto &achievement = achievements[i];
            const bool hasState = i < states.size();
            const bool unlocked = hasState && states[i].unlocked;
            const std::uint32_t progress = hasState ? states[i].progress : 0U;
            const std::string visibleTitle = achievement.secret && !unlocked
                ? "???"
                : achievement.title;
            achievementFolders_[i]->Name() = (unlocked ? "[Unlocked] " : "[Locked] ") +
                                             metalMenuTag(achievement.points) + visibleTitle;
            const char *metal = amun::metalTierName(amun::metalTierFor(achievement.points));
            char pointsText[32]{};
            if (metal[0] != '\0')
                std::snprintf(pointsText, sizeof(pointsText), "%u (%s)",
                              static_cast<unsigned>(achievement.points), metal);
            else
                std::snprintf(pointsText, sizeof(pointsText), "%u",
                              static_cast<unsigned>(achievement.points));

            char note[512]{};
            const char *description = achievement.secret && !unlocked
                ? "Locked secret achievement."
                : achievement.description.c_str();
            if (achievement.progressTarget != 0U) {
                std::snprintf(note, sizeof(note), "%s\nPoints: %s\nProgress: %lu/%lu\nID: %s",
                              description, pointsText,
                              static_cast<unsigned long>(progress),
                              static_cast<unsigned long>(achievement.progressTarget),
                              achievement.secret && !unlocked ? "hidden" : achievement.id.c_str());
            } else {
                std::snprintf(note, sizeof(note), "%s\nPoints: %s\nID: %s",
                              description, pointsText,
                              achievement.secret && !unlocked ? "hidden" : achievement.id.c_str());
            }
            achievementFolders_[i]->Note() = note;
        }
    }

    std::uint64_t titleId_{0U};
    LifecycleCoordinator &lifecycle_;
    SdStatusLog &statusLog_;
    ThreeDSMemoryReader memory_;
    ThreeDSClock clock_;
    ThreeDSEventSink eventSink_;
    CtrpfLedger ledger_;
    Runtime runtime_;
    IdentityResult identityResult_;
    BuildMatch buildMatch_{BuildMatch::UnsupportedBuild};
    std::string detail_{"initializing"};
    std::size_t packBytes_{0U};
    bool packParsed_{false};
    bool packTitleMatched_{false};
    bool identityReady_{false};
    bool ledgerReady_{false};
    bool recoveredLedgerTail_{false};
    bool runtimePackReady_{false};
    std::uint32_t totalReads_{0U};
    std::uint32_t totalReadBytes_{0U};
    std::uint32_t totalFailures_{0U};
    static constexpr std::uint32_t kPerfWindowTicks = 100U;
    amun::Milliseconds lastTickAt_{0U};
    amun::Milliseconds nextTickAt_{0U};
    std::uint32_t perfTicks_{0U};
    std::uint64_t perfElapsedTotal_{0U};
    std::uint64_t perfElapsedMax_{0U};
    std::uint64_t perfReads_{0U};
    std::uint64_t lastTickMicros_{0U};
    amun::Milliseconds lastMenuRefresh_{0U};
    MenuEntry *runtimeEntry_{nullptr};
    MenuEntry *selfTestEntry_{nullptr};
    MenuFolder *achievementBrowser_{nullptr};
    std::vector<MenuFolder *> achievementFolders_;
};

ObserverSession *gObserver = nullptr;
void observerFrame() {
    if (gObserver != nullptr) gObserver->tick();
}
bool observerMenuOpening() {
    if (gObserver != nullptr) gObserver->onMenuOpening();
    return true; // allow the menu to open
}

MenuEntry *gSelfTestInputEntry = nullptr;
void selfTestMenuOpened() {
    if (gSelfTestInputEntry == nullptr) return;
    gSelfTestInputEntry->Note() =
        "PASS: CTRPF delivered the menu-open input event.\n"
        "The default chord is L+SELECT and is configurable under Tools > Settings.";
    gSelfTestInputEntry->RefreshNote();
}

void runOptInPlatformSelfTest(std::uint64_t titleId, LifecycleCoordinator &lifecycle,
                              SdStatusLog &statusLog, FlushContext &flushContext) {
    ThreeDSClock clock;
    const amun::Milliseconds before = clock.monotonicMs();
    svcSleepThread(1'000'000LL);
    const amun::Milliseconds after = clock.monotonicMs();
    const bool clockPassed = after > before;

    const char *scratchPath = amun::threeds::kSelfTestScratchLedgerPath;
    bool scratchReady = true;
    if (File::Exists(scratchPath) == 1 && File::Remove(scratchPath) != File::SUCCESS)
        scratchReady = false;

    CtrpfLedger scratch(scratchPath, 16U * 1024U, 64U * 1024U);
    flushContext.ledger = &scratch;
    bool ledgerPassed = false;
    if (scratchReady && scratch.load()) {
        amun::LedgerEvent event;
        event.type = amun::LedgerEventType::SessionStarted;
        event.wallClockUnixMs = clock.wallClockUnixMs();
        event.integrity = IntegrityMode::Developer;
        char identifier[96]{};
        std::snprintf(identifier, sizeof(identifier), "platform-self-test-%016llX-%llu",
                      static_cast<unsigned long long>(titleId),
                      static_cast<unsigned long long>(clock.monotonicMs()));
        event.eventId = identifier;
        event.runtimeVersion = amun::kRuntimeVersion;
        event.sessionId = identifier;
        event.detail = "AMUN-owned scratch ledger self-test";
        if (scratch.append(std::move(event)) == amun::LedgerStatus::Ok) {
            CtrpfLedger replay(scratchPath, 16U * 1024U, 64U * 1024U);
            const amun::LedgerLoadResult verified = replay.load();
            ledgerPassed = verified && verified.records == 1U &&
                           File::Remove(scratchPath) == File::SUCCESS;
        }
    }

    char logLine[192]{};
    std::snprintf(logLine, sizeof(logLine),
                  "self-test: tid=%016llX clock=%s scratch-ledger=%s game-reads=0",
                  static_cast<unsigned long long>(titleId), clockPassed ? "pass" : "fail",
                  ledgerPassed ? "pass" : "fail");
    statusLog.appendLine(logLine);
    (void)statusLog.flush();

    PluginMenu menu("AMUN platform self-test", 0U, 1U, 0U,
                    "Explicit opt-in platform test. No game memory is read.");
    menu.ShowWelcomeMessage(false);
    menu.SetHexEditorState(false);
    menu.SynchronizeWithFrame(true);
    menu.UpdateEveryOtherFrame(true);

    char resultNote[384]{};
    std::snprintf(resultNote, sizeof(resultNote),
                  "Full TID class gate: PASS (%016llX)\nMonotonic clock: %s\n"
                  "Scratch ledger write/replay/remove: %s\nGame-memory reads: 0\n"
                  "Achievement unlocks: 0\nNetworking: compiled out",
                  static_cast<unsigned long long>(titleId), clockPassed ? "PASS" : "FAIL",
                  ledgerPassed ? "PASS" : "FAIL");
    auto *resultEntry = new MenuEntry("Platform checks", resultNote);
    auto *inputEntry = new MenuEntry(
        "Menu input check",
        "PENDING: open this menu with its configured chord. The note updates on delivery.");
    resultEntry->CanBeSelected(amun::threeds::kInformationRowsSelectable);
    inputEntry->CanBeSelected(amun::threeds::kInformationRowsSelectable);
    menu.Append(resultEntry);
    menu.Append(inputEntry);
    gSelfTestInputEntry = inputEntry;
    menu.OnFirstOpening = selfTestMenuOpened;
    (void)menu.Run();
    gSelfTestInputEntry = nullptr;
    flushContext.ledger = nullptr;
    statusLog.appendLine("self-test: menu stopped");
    (void)statusLog.flush();
    (void)lifecycle; // Process events stop PluginMenu::Run; no sampling callback exists.
}

} // namespace

void PatchProcess(FwkSettings &settings) {
    settings.ThreadPriority = 0x30U;
    settings.AllowActionReplay = false;
    settings.AllowSearchEngine = false;
    settings.WaitTimeToBoot = Milliseconds(0);
    settings.CachedDrawMode = false;
    settings.CloseMenuWithB = amun::threeds::kCloseMenuWithB;
    settings.UseGameHidMemory = false;
    settings.AreN3DSButtonsAvailable = false;
    settings.TryLoadSDSounds = false;
}

int main() {
    static_assert(!amun::threeds::kNetworkingCompiledIn,
                  "SOC networking must remain compiled out");

    SdStatusLog statusLog;
    FlushContext flushContext{&statusLog, nullptr};
    LifecycleHooks hooks{&flushContext, onPause, onResume, onStop, onFlush};
    LifecycleCoordinator lifecycle(hooks);
    gLifecycle = &lifecycle;
    Process::SetProcessEventCallback(onProcessEvent);

    const std::uint64_t titleId = Process::GetTitleID();
    CtrpfPackProbe probe;
    const auto gate = amun::threeds::evaluateTitleGate(titleId, probe);
    const bool selfTestRequested =
        gate.decision == amun::threeds::TitleGateDecision::PackMissing &&
        File::Exists(amun::threeds::kSelfTestFlagPath) == 1;

    OSD::LightweightMode = !(gate.canObserve() || selfTestRequested);
    if (!gate.canObserve() && !selfTestRequested) {
        Process::WaitForExit();
        Process::SetProcessEventCallback(nullptr);
        gLifecycle = nullptr;
        return 0;
    }

    if (!statusLog.initialize()) {
        (void)OSD::Notify("AMUN: SD initialization failed; observer disabled");
        Process::WaitForExit();
        Process::SetProcessEventCallback(nullptr);
        gLifecycle = nullptr;
        return 0;
    }
    char bootLine[192]{};
    std::snprintf(bootLine, sizeof(bootLine), "boot: tid=%016llX pack=%s",
                  static_cast<unsigned long long>(titleId), gate.packPath.data());
    statusLog.appendLine(bootLine);

    if (selfTestRequested) {
        statusLog.appendLine("boot: explicit platform self-test flag accepted; no pack/game reads");
        runOptInPlatformSelfTest(titleId, lifecycle, statusLog, flushContext);
        Process::SetProcessEventCallback(nullptr);
        gLifecycle = nullptr;
        statusLog.close();
        return 0;
    }

    ObserverSession observer(titleId, lifecycle, statusLog);
    flushContext.ledger = &observer.ledger();
    observer.initialize(gate.packPath.data());

    PluginMenu menu("AMUN", 0U, 1U, 0U,
                    "Read-only, local achievement observer. Networking is disabled.");
    menu.ShowWelcomeMessage(false);
    menu.SetHexEditorState(false);
    menu.SynchronizeWithFrame(true);
    menu.UpdateEveryOtherFrame(true);

    auto *runtimeEntry = new MenuEntry("Runtime status");
    auto *selfTestEntry = new MenuEntry("Platform self-test");
    auto *achievementBrowser = new MenuFolder("Achievements");
    runtimeEntry->CanBeSelected(amun::threeds::kInformationRowsSelectable);
    selfTestEntry->CanBeSelected(amun::threeds::kInformationRowsSelectable);
    menu.Append(runtimeEntry);
    menu.Append(selfTestEntry);
    menu.Append(achievementBrowser);
    observer.attachStatusEntries(runtimeEntry, selfTestEntry);
    observer.attachAchievementBrowser(achievementBrowser);
    gObserver = &observer;
    menu.Callback(observerFrame);
    menu.OnOpening = observerMenuOpening;
    (void)menu.Run();
    gObserver = nullptr;

    observer.shutdown();
    flushContext.ledger = nullptr;
    Process::SetProcessEventCallback(nullptr);
    gLifecycle = nullptr;
    statusLog.close();
    return 0;
}

} // namespace CTRPluginFramework
