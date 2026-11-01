# ADR 0001: Official Luma 3GX platform baseline

- Status: Accepted for initial observer integration; scoped physical regression passed
- Date: 2026-08-25
- Last evidence update: 2026-09-02
- Hardware baseline: original Nintendo 2DS / Old3DS class
- Hardware verification: Current loader-event-guarded artifact passed exact-pack Mario Kart and no-pack Pilotwings normal-exit paths on original 2DS

## Context

AMUN must coexist with native CTR games on current official Luma3DS and fail closed
when no exact achievement profile is installed. The global plugin is injected into the
game process, so a bad memory access or slow lifecycle reply can crash or delay the
game itself.

Current upstream inspection established these relevant contracts:

- Official [Luma3DS v13.4](https://github.com/LumaTeam/Luma3DS/releases/tag/v13.4)
  contains the supported 3GX loader; no forked `boot.firm` is required.
- Luma searches a per-title directory and then
  [`/luma/plugins/default.3gx`](https://github.com/LumaTeam/Luma3DS/blob/v13.4/sysmodules/rosalina/source/plugin/file_loader.c).
  A per-title plugin shadows the fallback, and only one plugin is loaded.
- The current runtime header and event contract are defined by Luma's
  [`plgldr.h`](https://github.com/LumaTeam/Luma3DS/blob/v13.4/sysmodules/rosalina/include/plugin/plgldr.h).
- Old3DS-class systems normally swap the complete plugin region through
  `/luma/plugins/.swap` at HOME transitions. Swap failures can reboot the console.
  [Loader lifecycle](https://github.com/LumaTeam/Luma3DS/blob/v13.4/sysmodules/rosalina/source/plugin/plgloader.c),
  [memory implementation](https://github.com/LumaTeam/Luma3DS/blob/v13.4/sysmodules/rosalina/source/plugin/memoryblock.c)
- 3GX metadata supports 2, 5, and 10 MiB plugin regions, shared/private memory,
  loader-managed events, and optional swap avoidance. The format authority is
  Luma's [`3gx.h`](https://github.com/LumaTeam/Luma3DS/blob/v13.4/sysmodules/rosalina/include/plugin/3gx.h).

3gxtool and CTRPluginFramework are community dependencies rather than official Luma
or devkitPro SDKs. Their exact commits and compatibility patches are therefore part
of AMUN's build input, not assumed system packages.

The first physical bring-up exposed one such compatibility defect. Predecessor 3GX
SHA-256 `e13bab596760e4b8ab594ec0acdecc0e1be1fbecd734b1d53a363f714fc8cc27`
loaded twice on an original wedge 2DS with Mario Kart 7 EUR
(`0004000000030700`). Its CTRPF UI, clock, scratch-ledger write/replay/remove, zero
game reads, and lifecycle pause/resume/stop checks passed, but both sessions crashed
during menu teardown because an embedded borrowed root was destroyed twice. That
artifact is unsafe and retired; this ADR records the corrected ownership decision, not
a hardware pass for the replacement.

The ownership-fixed replacement, SHA-256
`d6d72a9f6de19d2897696d3e75be890ce12bc119b37004ea0c145d8542184f09`,
was then tested on 2026-08-30 on the same original wedge 2DS and Mario Kart 7 EUR
(`0004000000030700`); the Luma version remains unknown. Its third appended
`platform.log` session passed the monotonic-clock and scratch-ledger checks, performed
zero game-memory reads, and recorded pause, resume, and stop. The title closed cleanly,
which is hardware evidence for the ownership repair. The run was not a complete UI
pass: Down could not select the second information row, and B did not close the root
overlay. That artifact is superseded for usability, not classified as unsafe. The
  UI-fixed hash
  `d0dcd7a42704ab3dfe2cd1cf937c9cf9f0679664c261de52d56c4d203c188895`
  then passed those controls and two identity-discovery launches. Its first exact-pack
  run exposed the existing-file append-cursor fault and crashed during delayed CTRPF
  shutdown, so it is retired. The later ledger/shutdown-fixed 3GX, SHA-256
  `dfec2647d030f8b0fe2a997d38f815371eb9d17945d1fba0bda2f78e9dd5c226`,
  passed the Mario Kart exact-pack recovery/unlock/toast/relaunch/exit flow. It then
  crashed on no-pack Pilotwings exit because CTRPF polled a null loader-event pointer.
  That hash is retired. The current guarded 3GX has SHA-256
  `d579addd00deca524600cf6b058a7ed5d90b49dc2657df7bd24c431a82248571` and later passed
  both title paths on the original 2DS. Those scoped paths are `HARDWARE-TESTED=yes`;
  live profile-driven memory observation remains a separate pending check.

## Decision

### Loader and title scope

AMUN is installed as `/luma/plugins/default.3gx`. Its `.plgInfo` target list is global,
but the runtime accepts only:

1. a full nonzero Title ID whose high word is exactly `00040000`; and
2. an exact pack at `/amun/packs/<FULL-16-DIGIT-TITLE-ID>/game.amunpack`.

The complete 64-bit ID is formatted into the path. A low-title-ID collision cannot
admit a system application. System applications, applets, homebrew, TWL/DS, and
AGB/GBA modes remain inert. Pack parsing must independently verify its embedded full
Title ID, version, and executable fingerprint before any profile address is used.

AMUN performs no persistent SD write before this exact-title gate succeeds. On a
missing pack or excluded title it enables CTRPF lightweight OSD mode and uses
`Process::WaitForExit()`; it creates no AMUN log, ledger, menu, or scanner. The only
exception is an explicit `/amun/config/self-test.flag` on a native `00040000` title
with no pack. That opt-in path creates the platform log and a temporary AMUN-owned
scratch ledger, exercises clock/menu/input/storage, removes the scratch ledger, and
performs zero game-memory reads or unlocks. Packaging supplies only a disabled
`.example`, and excluded title classes can never enter the self-test.

After that gate, the console adapter reads at most 512 KiB through CTRPF `File`, calls
`PackParser::parse` on the bytes, and rejects an embedded title ID that differs from
the running full ID. It constructs the build identity before handing the pack to
`Runtime`. `Runtime::startSession` performs its build match before retaining the
memory reader or resolving symbols, so an unknown fingerprint/version causes zero
profile-address reads.

### Observer-only memory capability

The platform exports only `MemoryReader::read` and `isRangeReadable`; it exports no
game-memory write, patch, permission-change, search, or Action Replay API.

`ThreeDSMemoryReader` uses libctru's exact
[`svcQueryMemory(MemInfo*, PageInfo*, u32)`](https://github.com/devkitPro/libctru/blob/v2.7.0/libctru/include/3ds/svc.h)
contract for the current process. It:

- rejects address overflow, zero-sized returned regions, query failures, free,
  reserved, I/O, and non-readable mappings;
- re-queries every member mapping of a request;
- caps each `memcpy` at `base_addr + size`, returning `Partial` instead of crossing a
  hole or unreadable next mapping; and
- rejects the Luma runtime header/executable mapping and plugin heap identified by
  `FwkSettings::Header`, so untrusted packs cannot intentionally read AMUN state.

The check and copy are not atomic. A game can change bytes during a read, and an
unexpected concurrent unmap can still race the query. AMUN stops sampling on
lifecycle entry and treats snapshots as observational, not transactional.

CTRPF's `Process::CheckAddress`, `CheckRegion`, and `CopyMemory` are not used as the
safety boundary. In the pinned implementation their requested permission argument is
not enforced and a copy is not partitioned across all mappings.
[Implementation](https://gitlab.com/thepixellizeross/ctrpluginframework/-/blob/develop/Library/source/CTRPluginFramework/System/Process.cpp)

### Memory and original-2DS policy

The plugin metadata is fixed to:

```text
Compatibility: Console
MemorySize: 5MiB
EventsSelfManaged: false
SwapNotNeeded: false
UsePrivateMemory: false
```

Five MiB is chosen because stock CTRPF and the pack/runtime/menu/ledger allocations
must coexist. The console caps packs at 512 KiB, achievements at 300, symbols at 512,
decoded assets at 256 KiB total, the ledger at 512 KiB/4096 records, and the browser
at 128 entries. Those are rejection bounds, not evidence that peak use fits. Two MiB
is not accepted until a linked-size and runtime-allocation budget proves it safe. Ten
MiB is not accepted without Old2DS title-matrix testing.

Normal Luma-managed swap semantics are retained. Every AMUN worker must be a
libctru/CTRPF thread so Luma recognizes its TLS while swapping. This implementation
adds no worker: `PluginMenu::Run` invokes the runtime tick callback on CTRPF's plugin
main loop.

### Lifecycle

CTRPF's current
[`Process::SetProcessEventCallback`](https://gitlab.com/thepixellizeross/ctrpluginframework/-/blob/develop/Library/include/CTRPluginFramework/System/Process.hpp)
is the adapter for `EXIT`, sleep, HOME, and swap events. The portable coordinator:

- tracks sleep, HOME, and swap as independent nested suspension reasons;
- pauses work on the first entry and resumes only after the last reason clears;
- invokes an idempotent stop hook on exit; and
- invokes the registered flush hook before returning from every suspend/exit entry.

The callback must remain bounded because Luma waits for replies at synchronous
lifecycle boundaries. It first sets atomic stop/pause state and then invokes the
ledger/status flush hook. `CtrpfLedger::append` already flushes and closes each record,
so its lifecycle flush has no pending file payload. Runtime session-end is appended
after `PluginMenu::Run` returns. Networking is never performed there.

The original 2DS has a sleep switch rather than a folding lid; behavior is based on
events, never on physical-lid language or controls.

### UI and framework dependency

CTRPluginFramework is pinned at
`6671936663faaa900f7cfdeedf42bc8581560f4f`. AMUN disables its Action Replay and
search engine handlers, game-HID memory mode, SD sounds, and boot delay. Toasts use
the existing `OSD::Notify` API only after the exact-title gate. AMUN adds an eight-item
queue in front of CTRPF's own 50-item queue, emits at most one toast per 750 ms, hides
locked secret titles, and includes points. A verified `PluginMenu` callback ticks the
runtime every other synchronized frame while neither CTRPF nor the lifecycle adapter
reports a pause. Its status/self-test entries are selectable, callback-free
information rows; its achievement browser is bounded to 128 read-only folders and
exposes locked/unlocked, points, and progress, with `???` for locked secrets.

Status and self-test information rows are selectable for navigation but have no game
or menu callback, so A is an inert no-op. Marking them unselectable is prohibited:
CTRPF excludes such rows from cursor navigation, which made the two-row platform menu
impossible to inspect. AMUN also sets `FwkSettings::CloseMenuWithB` to true. At the
root, B closes the overlay without stopping the plugin or title; `L+Select` must reopen
it. Inside a folder, B retains CTRPF's normal parent-folder behavior. Hardware Phase 2
must exercise Down, root B, reopen, and a clean title exit in that order.

AMUN's CTRPF patch sets the initial menu chord to `L+Select`. The pinned framework's
**Tools > Settings > Change menu hotkeys** UI remains available and persists a user
override; AMUN does not guess at an independent input hook.

Stock CTRPF remains bootstrap debt. It initializes broad services, hooks game/GSP
behavior for its framework, reserves substantial memory, and creates its own
`/cheats` and `/Screenshots` directories before AMUN `main()` runs. Disabling its menu
tools does not turn it into a formally read-only library. A pinned, stripped CTRPF
fork or smaller native runtime is the likely production path after the current UI
retest and broader characterization, but is not substituted without real-console
validation.

### Filesystem

Every AMUN-owned CTRPF path begins with `/amun`; relative paths are prohibited because
a fallback plugin inherits CTRPF's ActionReplay working directory. The platform uses
CTRPF `File`/`Directory`, buffers its diagnostic log, and explicitly flushes it at
lifecycle boundaries rather than using `File::SYNC` on every write.

CTRPF's `/...` API and newlib paths are different namespaces. Core code using
`std::fstream` or `std::filesystem` must first call libctru v2.7.0's
`archiveMountSdmc()` and then use `sdmc:/amun/...`; it must later call
`archiveUnmount("sdmc")`. The plugin intentionally does not mount that devoptab. It
uses `PackParser::parse` on a bounded CTRPF file buffer and a `CtrpfLedger` adapter
that is byte-compatible with the core `AMLG`/`AMLE` journal format, including CRCs,
sequence numbers, duplicate/unlock/progress replay, and atomic valid-prefix recovery
through temporary/backup renames. Before the 512 KiB/4096-record cap, it automatically
compacts when at least 64 discardable records exist and the journal crosses 75 percent
of its byte or record budget; an imminent cap also forces an attempt. The snapshot
retains one complete latest unlock event or effective progress event per achievement,
orders by prior sequence/type/ID, and deterministically resequences from one. Unlocks
retain their UUID, build ID, timestamp, runtime version, profile hash, session ID, and
integrity mode. A fully flushed temporary file replaces the journal through a backup
rename; an interrupted transaction restores the original full journal on the next
load. It does not link the `std::filesystem`-based `JournalLedger` implementation.

The executable identity is deliberately named
`live-text-crc32-v1:<TEXT-SIZE-HEX>:<CRC32-HEX>`. It covers the complete bounded live
`.text` range returned by `Process::GetTextSize()` (maximum 32 MiB), using the safe
reader in 4 KiB chunks. It is not a pristine ExeFS hash: pinned CTRPF has installed
framework hooks before AMUN `main()`. Consequently fingerprints are valid only for
this pinned loader/framework path until an on-disk executable hash API is implemented.
The region is a CFGU code (`JPN`, `USA`, `EUR`, `AUS`, `CHN`, `KOR`, `TWN`), and
`applicationVersion` is decimal `Process::GetVersion()`—the maximum installed
base/update/game-card version. `updateVersion` is empty because CTRPF cannot expose
the two versions separately; pack build records must encode the same convention.

### Networking

Networking is compiled out and `socInit` is never called. `UsePrivateMemory` was
introduced to support socket/HTTP buffers, but title-specific crashes have been
reported with it enabled, while a normal SOC context may not work from the shared
plugin heap. [Luma feature PR](https://github.com/LumaTeam/Luma3DS/pull/2086),
[compatibility report](https://github.com/LumaTeam/Luma3DS/issues/2225)

AMUN will not trade universal offline observation for unverified networking. A later
network build requires a proven private SOC-buffer strategy, hard nonblocking
timeouts, lifecycle shutdown, and original-2DS hardware tests.

### Pinned format/tool patches

The dependency fetcher checks out exact commits and applies seven reviewed patches:

- CTRPF's copied `PluginHeader` is updated to Luma v13.4's 0x100-byte layout,
  including `waitForReplyTimeout` and the `config` offset assertion.
- CTRPF's two GCC 16 `unused-but-set-variable` diagnostics are fixed so its build can
  keep normal warnings without the upstream project's blanket `-Werror` failure.
- CTRPF's initial/fallback menu hotkey changes from bare `Select` to `L+Select` while
  preserving its existing user-configurable settings UI.
- CTRPF's internal `Menu` records whether its root folder is owned or borrowed. The
  Tools menu borrows its embedded root, preventing the root from being deleted by
  `Menu` and then destroyed a second time during `PluginMenu` teardown.
- CTRPF's `ThreadEx` destructor calls `threadFree` only for a completed thread. A timed
  join may leave the main thread running; global teardown leaves that allocation for
  process reclamation instead of freeing its live stack.
- CTRPF's loader-event poll returns `PLG_OK` when Luma supplies no event pointer, and
  its reply path checks both pointers. This prevents the Pilotwings no-pack exit's
  null exclusive read while leaving supported loader-event handling unchanged.
- 3gxtool gains the current `allowHomebrewLoad` bit and explicit
  `AllowHomebrewLoad` YAML key. AMUN sets it false; the patch prevents format drift
  and permits a future opt-in homebrew self-test artifact.

AMUN does not call CTRPF's stale runtime `PLGLDR__SetSwapSettings`; 3gxtool embeds the
standard swap payloads in the output.

## Consequences and unverified boundaries

- A per-title `.3gx` shadows AMUN's fallback. AMUN cannot compose with it.
- Luma injects the plugin before AMUN's user code can gate the title. Unsupported
  titles still pay CTRPF initialization cost even though AMUN itself stays inert.
- The observer parses the exact pack, fingerprints live `.text`, loads/replays or
  recovers the per-title ledger, starts `amun::Runtime`, ticks it through the safe
  reader and monotonic libctru clock, durably stores events, and exposes status,
  self-test, and a bounded achievement browser. The exact pinned dependency build is
  cross-linked and container-verified. Predecessors provide ownership, controls,
  identity, ledger, toast, and exact-title exit evidence, but current `d579addd...`
  has not been hardware validated.
- The main executable base check uses `0x00100000`, matching current Luma/CTRPF
  assumptions. Relocatable executable support is not claimed.
- Stock CTRPF modifies the process environment internally even though AMUN exposes no
  mutation operation.
- The live fingerprint may change if CTRPF's hook set changes, even when the game
  executable does not. Pack authors need the exact status-menu fingerprint from the
  pinned build; a pristine on-disk executable fingerprint remains pending.
- The ledger now compacts automatically and removes unbounded session/checkpoint
  history while retaining complete latest unlock and effective locked-progress
  records. If that finite retained snapshot itself exceeds 512 KiB (possible for
  unusually large accepted identifiers/metadata), it fails closed rather than dropping
  an unlock. CTRPF/FAT rename durability and compaction latency remain hardware-test
  items.
- Existing CTRPF journals are sought to and verified at the expected EOF before one
  combined record write. This avoids APPEND mode's zero cursor before its first write.
  A failed append latches persistence off for the rest of the session, preventing
  per-frame SD/log retry storms while preserving ledger-before-toast order.
- The achievement browser shows at most 128 of the accepted 300 definitions.
- The unsafe predecessor loaded with the 5 MiB allocation and logged
  pause/resume/stop plus scratch-ledger activity, but failed teardown. The later
  ownership-fixed artifact closed cleanly with the same lifecycle events, while its
  Down and root-B controls failed. This separates positive borrowed-root ownership
  evidence from acceptance of the current fixed build. The later `dfec2647...` passed
  the exact Mario Kart path but failed no-pack Pilotwings exit; dump 6 provides direct
  evidence for the new event-channel guard. `SwapNotNeeded:false`
  stress, repeated lifecycle timing, storage durability, and CTRPF priority `0x30`
  remain unverified on an original 2DS.
- A clean devkitARM r68/libctru 2.7.0/GCC 16.1.0 WSL build produced and verified the
  superseded ownership-fixed `d6d72a9...` `.elf`, linker map, and `3GX$0002`
  container with no compiler diagnostics. `arm-none-eabi-size` reported text
  1,004,144, data 9,924, bss 17,460, and total 1,031,528 bytes (`0xFBD68`). Those size
  figures describe that historical artifact, not the current fixed build, and are
  not a Citra or physical-hardware result.

These boundaries must stay visible until the physical test matrix records evidence
for them.
