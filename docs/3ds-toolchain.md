# Reproducible 3DS / 3GX toolchain

This document describes the pinned build inputs for the conservative AMUN bootstrap.
The verification record below covers the current ledger, shutdown, and null-safe
loader-event cross-link and 3GX container build. Earlier artifacts supplied useful console evidence,
but neither that evidence nor a successful cross-build constitutes a hardware-tested
release for the current artifact.

## Versions and provenance

| Input | Pinned reference |
|---|---|
| Official Luma3DS loader contract | v13.4 |
| devkitARM | release 68 |
| libctru | v2.7.0 |
| Official devkitPro container | `devkitpro/devkitarm:20260610` |
| Container OCI index digest | `sha256:116afba8df8453961de2936ffab20dd441edf4d682856c1ec8b0e53d7ed0bbf5` |
| CTRPluginFramework | `6671936663faaa900f7cfdeedf42bc8581560f4f` |
| 3gxtool | `57e3160ab72d8533a2f0601efdc8a149b4825ea5` |

The source pins live in `cmake/3ds/Dependencies.cmake`. CTRPF and 3gxtool are
ThePixellizerOSS community projects, not official devkitPro or Luma SDK components.

Primary references:

- [Luma3DS v13.4](https://github.com/LumaTeam/Luma3DS/releases/tag/v13.4)
- [Luma build and GDB instructions](https://github.com/LumaTeam/Luma3DS/blob/v13.4/README.md)
- [devkitPro Getting Started](https://devkitpro.org/wiki/Getting_Started)
- [libctru v2.7.0](https://github.com/devkitPro/libctru/releases/tag/v2.7.0)
- [CTRPluginFramework](https://gitlab.com/thepixellizeross/ctrpluginframework)
- [3gxtool](https://gitlab.com/thepixellizeross/3gxtool)

## Supported setup

The reproducible route is the immutable container reference:

```text
devkitpro/devkitarm@sha256:116afba8df8453961de2936ffab20dd441edf4d682856c1ec8b0e53d7ed0bbf5
```

For an amd64 build host, make the platform explicit:

```sh
docker run --rm -it --platform linux/amd64 \
  -v "$PWD:/work" -w /work \
  devkitpro/devkitarm@sha256:116afba8df8453961de2936ffab20dd441edf4d682856c1ec8b0e53d7ed0bbf5 \
  bash
```

For a native devkitPro installation, use its supported pacman environment and install
the 3DS group:

```sh
sudo dkp-pacman -S 3ds-dev --needed
```

The recorded current build on 2026-09-02 used the official devkitPro pacman environment
in WSL Ubuntu (`devkitARM r68`, `libctru 2.7.0`, GCC 16.1.0):

```sh
source /etc/profile.d/devkit-env.sh
```

Keep the actual GNU Make source and dependency paths free of whitespace. GNU Make and
devkitARM's `3ds_rules` split this repository's Windows path (`AMUN 3DS`) when it is
used directly through DrvFs. The verified WSL run copied the source to a fresh ext4
directory and kept dependencies under `/tmp`; this is a build-system path limitation,
not a source-code workaround.

On Windows, run the commands below from the devkitPro/MSYS2 shell so `DEVKITARM`,
`DEVKITPRO`, GNU Make, the ARM tools, and a GNU-compatible host compiler are visible.
The stock 3gxtool source is not an MSVC project. AMUN now applies
`3gxtool-msvc-layout.patch` for scoped packed layouts, compile-time ABI size checks,
and conditional GNU linker flags, allowing the pinned tool to build with MSVC too.

### Native Windows fallback (2026-09-10)

`scripts/build-3ds-native.py` invokes an existing native devkitARM toolchain directly,
using the flags and source list from `3ds/Makefile`. It handles repository paths with
spaces and requires a prebuilt pinned/patched CTRPF `Library` directory:

```powershell
python -B scripts/build-3ds-native.py --devkitpro build/native-toolchain/opt/devkitpro --ctrpf PATH/TO/ctrpluginframework/Library --threegxtool build/3gxtool-native/Release/3gxtool.exe
```

This route built the current coin-preview artifact without changing the stuck WSL
service. Exact package/library hashes and verification are in
[`dist/mk7-coin-fix-20260910/BUILD-RECORD.md`](../dist/mk7-coin-fix-20260910/BUILD-RECORD.md).

Do not install the moving `libctrpf` package and assume it matches AMUN. The build
below creates the library from the pinned, patched checkout.

## Host boundary tests

These tests need no Nintendo or devkitPro tooling:

```sh
cmake -S 3ds -B build-3ds-platform-host -DAMUN_3DS_BUILD_HOST_TESTS=ON
cmake --build build-3ds-platform-host --config Debug
ctest --test-dir build-3ds-platform-host -C Debug --output-on-failure
```

They validate full-title gating, address overflow, bounded adjacent-region copying,
partial failures, nested suspend/resume, stop idempotence, and the compile-time network
off policy. The extracted ledger-snapshot tests also validate deterministic
resequencing, latest effective progress retention, unlock-over-progress retention, and
duplicate unlock protection. They do not validate CTRPF rename durability,
`svcQueryMemory`, Luma, or hardware timing.

The Python host suite additionally guards the two CTRPF UI policies implicated by the
2026-08-30 console run: all four information rows must remain cursor-selectable, and
the root-menu B-close setting must remain enabled. These are source-policy regression
checks; physical input delivery still requires a console run.

## Fetch and patch exact community dependencies

From the repository root, inside the container or devkitPro shell:

```sh
cmake -DAMUN_DEPS_DIR="$PWD/build/3ds-deps" \
  -P cmake/3ds/fetch_pinned_dependencies.cmake
```

The fetcher:

1. clones both repositories with their submodules;
2. checks out detached exact commits;
3. refuses an existing non-Git destination or incompatible dirty checkout;
4. applies the reviewed patches in `cmake/3ds/patches/`; and
5. recognizes an already-applied patch on a repeat run.

The 3gxtool patch is required for the `AllowHomebrewLoad` key in `AMUN.plgInfo`.
Current unpatched 3gxtool silently ignores that key; false still happens to be the
zero-bit default, but AMUN treats the patched format definition as part of its build.
The CTRPF ownership patch marks embedded menu roots as borrowed so `Menu` does not
delete an object that `PluginMenu` later destroys again. It fixes the double teardown
observed in the retired predecessor build.
The CTRPF thread-destruction patch prevents a timed-out join from being followed by a
raw `free` of the still-running thread's combined control-block/stack allocation during
global teardown. Completed threads use libctru's `threadFree` path instead.
The CTRPF loader-event patch treats a null `plgldrEvent` pointer as an idle poll and
returns without touching either pointer when a reply channel is unavailable. This
closes the Pilotwings no-pack exit fault captured in dump 6.

## Build 3gxtool and CTRPF

```sh
cmake -DAMUN_DEPS_DIR="$PWD/build/3ds-deps" -DAMUN_BUILD_JOBS=4 \
  -P cmake/3ds/build_pinned_dependencies.cmake
```

Expected dependency outputs are:

```text
build/3ds-deps/
├── 3gxtool/
├── 3gxtool-build/
│   └── 3gxtool[.exe]
└── ctrpluginframework/
    └── Library/
        ├── include/
        └── lib/libctrpf.a
```

Multi-configuration host generators may place `3gxtool.exe` in
`3gxtool-build/Release/`; the Makefile detects all three layouts. An unusual layout can
be supplied explicitly as `THREEGXTOOL=/absolute/path/to/3gxtool`.

## Cross-build the bootstrap

```sh
make -C 3ds AMUN_DEPS_DIR="$PWD/build/3ds-deps"
```

The authoritative console build uses devkitARM's `3ds_rules`, ARMv6K/MPcore
hard-float flags, C++20 to match pinned CTRPF, `-fno-rtti`, `-fno-exceptions`, AMUN's
`3gx.ld`, and:

```text
3gxtool --silent AMUN.elf AMUN.plgInfo AMUN.3gx
```

It preserves the ELF/DWARF symbol artifact and asks 3gxtool to retain its symbol
table. The post-build CMake check requires the first eight bytes to be exactly
`3GX$0002` (`33 47 58 24 30 30 30 32`).

The Makefile builds `lib/libamun_core.a` from the console-required portable sources
(`crc32.cpp`, `memory.cpp`, `pack.cpp`, `runtime.cpp`, and `vm.cpp`) and links it as
`-lamun_core`. The CTRPF-backed ledger deliberately replaces the
`std::filesystem`-based core ledger on console. `decodeAsset` has a bounded
no-exception path; with exceptions disabled an allocation failure cannot be converted
to a parser error and follows the platform allocator's fatal behavior. The explicit
pack/asset/count caps are therefore part of the Old3DS risk boundary, not an OOM
recovery guarantee.

Expected outputs, only after a successful cross-build, are:

```text
3ds/AMUN.elf
3ds/AMUN.map
3ds/AMUN.3gx
```

This target links the portable runtime vertical slice plus the 3DS pack, identity,
clock, safe-memory, CTRPF-ledger, lifecycle, toast, status, self-test, and bounded
achievement-browser adapters. It must not be described as the AMUN v1 acceptance
artifact until the physical hardware matrix passes.

## Stage the SD tree

After a successful cross-build:

```sh
make -C 3ds package AMUN_DEPS_DIR="$PWD/build/3ds-deps"
```

This stages `dist/sd-root/luma/plugins/default.3gx` and the absolute AMUN directories
documented in `3ds/SD_LAYOUT.md`. It also maintains `dist/dev/AMUN.3gx`, the matching
ELF/map, `SHA256SUMS`, and a build-status file that says `CROSS-COMPILED=yes` and
`HARDWARE-TESTED=no`. It does not copy to a mounted SD card automatically.

The package includes `/amun/config/self-test.flag.example`, never an enabled flag.
For a pack-independent platform check on a native `00040000` title, rename it to the
exact `/amun/config/self-test.flag` path and leave that title's pack absent. AMUN then
tests its monotonic clock, menu-input delivery, and one temporary AMUN-owned ledger
record; it performs zero game-memory reads, produces no unlocks, removes the scratch
ledger, and keeps networking compiled out. Remove the flag after testing. Without the
flag, a missing pack remains inert.

On the SD card, a pack for Title ID `000400001234ABCD` belongs at:

```text
/amun/packs/000400001234ABCD/game.amunpack
```

AMUN's CTRPF storage code uses `/amun/...`. The pack is read into a bounded buffer and
passed to `PackParser::parse`; the console ledger uses CTRPF `File` directly. Portable
core code using newlib streams would need to mount libctru's devoptab with
`archiveMountSdmc()` and use `sdmc:/amun/...`; CTRPF does not perform that mount for it.

Pack build identities for this integration use these exact strings:

```text
region: JPN | USA | EUR | AUS | CHN | KOR | TWN
applicationVersion: decimal Process::GetVersion() effective installed version
updateVersion: empty
codeFingerprint: live-text-crc32-v1:<8-hex-text-size>:<8-hex-crc32>
```

The fingerprint covers live `.text` after the pinned CTRPF bootstrap hooks. Read it
from the in-game self-test/status view; it is not a pristine ExeFS hash and will need
regeneration if the pinned framework hook set changes.

CTRPluginFramework's pinned source has a custom Pixellizer license. Binary access may
not be fee-restricted unless corresponding source is supplied alongside, and source
copies/modifications must retain its license text. Preserve
[`LICENSE.txt`](https://gitlab.com/thepixellizeross/ctrpluginframework/-/blob/6671936663faaa900f7cfdeedf42bc8581560f4f/LICENSE.txt)
with any distribution that includes the statically linked framework. 3gxtool is an
MIT-licensed build tool; its notice is embedded in its pinned
[`README.md`](https://gitlab.com/thepixellizeross/3gxtool/-/blob/57e3160ab72d8533a2f0601efdc8a149b4825ea5/README.md#license).

Enable the loader in Rosalina (`L+Down+Select` by default, then **Plugin Loader**) and
remember that any per-title `.3gx` shadows `default.3gx`.

The pinned CTRPF patch changes AMUN's initial menu chord to `L+Select`. CTRPF exposes
the verified **Tools > Settings > Change menu hotkeys** UI and persists a user's
replacement chord; AMUN does not maintain a second hotkey configuration parser.

## Debug symbols and Luma GDB

Enable the debugger in Rosalina and connect using a normal context:

AMUN Studio's default **Direct Luma RSP** backend needs no GDB installation or WSL.
It obtains the exact process list from Luma on ports 4000-4002, highlights a likely
profile-name match for confirmation, and provides an explicit detach/resume action.
Choose the external GDB/MI backend only when full GDB behavior is needed.

```gdb
target extended-remote <3DS-IP>:4000
info os processes
attach <pid>
monitor getmemregions
add-symbol-file 3ds/AMUN.elf 0x07000100
```

Ports 4000-4002 are normal contexts. Break-on-start uses port 4003 after **Force-debug
next application at launch** and does not use `extended-remote`. The game and plugin
share one process.

## Verification status

On 2026-09-02, the exact pinned sources plus the reviewed ownership, input, storage,
thread, and loader-event fixes were rebuilt from a fresh space-free source tree with the
official WSL devkitPro environment. The commands that performed the build and format
checks were:

```sh
source /etc/profile.d/devkit-env.sh
export AMUN_DEPS_DIR="$PWD/build/3ds-deps"
./scripts/build-3ds.sh
cmake -DAMUN_3GX="$PWD/3ds/AMUN.3gx" -P cmake/3ds/verify_3gx.cmake
```

The AMUN compile/link completed without diagnostics. `arm-none-eabi-size` reported
`text=1005024`, `data=9924`, `bss=17460`, total `1032408` bytes (`0xFC0D8`). The
matching build artifacts were:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `3ds/AMUN.3gx` | 1,318,704 | `d579addd00deca524600cf6b058a7ed5d90b49dc2657df7bd24c431a82248571` |
| `3ds/AMUN.elf` | 4,579,912 | `c73f029094fe1411e31ba6a3091ce8edd073baafdb22f67b9c0063e01ff170c3` |
| `3ds/AMUN.map` | 5,097,541 | `60606d10f5e141cbe96ca01b570ed3498146db7142ea619dec248fdc2c2d99c5` |

The verifier accepted the first eight bytes as `3GX$0002`; the target count and unsafe
loader-policy bits are zero. ARM disassembly confirms that each of the four
`CanBeSelected` calls passes `r1=1`. It also shows `PatchProcess` storing packed word
`0x100` at offset 16, enabling `CloseMenuWithB` while the adjacent framework booleans
remain false. The current `ThreadEx` destructor branches to `threadFree` only when the
thread's `finished` byte is nonzero; it no longer directly calls `std::free` on a
possibly live stack allocation. `PLGLDR__FetchEvent` now compares its event pointer
with zero and branches around the exclusive read; `PLGLDR__Reply` checks both event
pointers before either exclusive access. Current status:

- Portable boundary code: implemented; all three host CTest targets passed. The full
  Python suite contains 81 tests: 79 passed, including native Luma RSP process
  discovery, exact-PID attach/detach, UI, EOF-append, thread-patch, and loader-event-guard
  policy checks, and two unrelated Windows symlink-fixture tests skipped for lack of
  symlink-creation privilege.
- Upstream patch applicability: checked against both exact source commits.
- Runtime/platform vertical slice: implemented, source/API audited against the pinned
  CTRPF/libctru headers, and cross-linked with the exact pinned dependencies.
- devkitARM/libctru cross-link and 3gxtool container generation: passed in the WSL
  environment described above. The ELF is ARMv6K/VFPv2 EABI hard-float.
- Citra: not tested and not a declared compatibility target.
- Current loader-event-guarded artifact
  `d579addd00deca524600cf6b058a7ed5d90b49dc2657df7bd24c431a82248571`:
  passed exact-pack Mario Kart and no-pack Pilotwings launch/normal-exit paths on the
  Original 2DS; those scoped paths are `HARDWARE-TESTED=yes`. Old3DS and New3DS remain
  untested, and the live memory-profile unlock is pending.
- Retired storage/shutdown-fixed artifact
  `dfec2647d030f8b0fe2a997d38f815371eb9d17945d1fba0bda2f78e9dd5c226`
  passed Mario Kart 7 torn-tail recovery, durable unlock-before-toast, relaunch, and
  normal exit. It then crashed on no-pack Pilotwings exit. Dump 6 reports FAR zero and
  symbolicates the PC/LR to `PLGLDR__FetchEvent`/`KeepThreadMain`; CTRPF polled a null
  loader-event pointer after the memory-change wait timed out. The global plugin makes
  that title-safety failure grounds for retirement.
- Retired UI-fixed artifact
  `d0dcd7a42704ab3dfe2cd1cf937c9cf9f0679664c261de52d56c4d203c188895`
  passed root-menu Down/B input and produced the same exact Mario Kart 7 EUR identity
  twice. Its exact-pack run wrote an unlock header but no payload because AMUN compared
  CTRPF's pre-append zero cursor with the post-append EOF cursor. Repeated failed
  retries delayed the main thread beyond CTRPF's timed join; Luma dump
  `4a66c03d11ce021ecf7e4bc54454a5d32f9f02331ab0127b153da56caeb8c07b`
  then faulted in `_free_r` from `ThreadEx::~ThreadEx`. That artifact is retired.
- Superseded ownership-fixed artifact
  `d6d72a9f6de19d2897696d3e75be890ce12bc119b37004ea0c145d8542184f09`
  loaded on 2026-08-30 on an original wedge 2DS with Mario Kart 7 EUR, full Title ID
  `0004000000030700`. Its log records clock and scratch-ledger passes, zero game reads,
  and lifecycle pause/resume/stop; the tester reported a clean title close. Down could
  not move between the information rows and B could not close the root overlay, so the
  artifact is superseded for UI usability. It is not classified as unsafe. The Luma
  version was not recorded.
- Retired predecessor 3GX
  `e13bab596760e4b8ab594ec0acdecc0e1be1fbecd734b1d53a363f714fc8cc27`
  loaded twice on an original wedge 2DS with Mario Kart 7 EUR
  (`0004000000030700`). Clock, scratch-ledger write/replay/remove, zero game reads,
  CTRPF UI, and lifecycle pause/resume/stop passed, but both sessions crashed during
  clean CTRPF menu teardown. That hash is unsafe and must not be installed.

The predecessor runs established loader, ownership, control, identity, storage, toast,
and exact-title exit facts. The current `d579addd...` two-title rerun additionally
validated the missing-event guard. Acceptable live-profile frame cost and broader game
compatibility remain unverified.
