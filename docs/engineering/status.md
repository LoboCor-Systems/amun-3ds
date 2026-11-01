# Engineering status — 2026-09-02

Update 2026-09-10: the current candidate is plugin `dbf62712...` with MK7 coin pack
`e3ae5fa6...`, installed with a backup on the test SD card. Startup resolution recovery,
transient VM input handling, and precise plugin-memory exclusions are cross-built.
The exact 3152 CRC and coin value 30 were independently read from hardware. The pack
contains five coin goals; 26 additional goals are only a design. All four CTest suites
pass; Python: 81 passed, two Windows symlink cases skipped. The user reported Small
Savings and Pocket Change unlocked on the original 2DS; normal exit/relaunch
acceptance for this new pair remains pending. See the
[bundle record](../../dist/mk7-coin-fix-20260910/BUILD-RECORD.md).

The report below describes the 2026-09-02 predecessor. It has no Git commit/tag yet, so it is
not a releasable source revision. Multiple predecessor artifacts exposed borrowed-root
teardown, menu-input, existing-ledger/timed-shutdown, and null loader-event defects on
an original wedge-shaped Nintendo 2DS. The current corrected artifact passed the
two-title Mario Kart/Pilotwings regression on that console; emulator and other-console
columns remain unverified.

## Evidence matrix

`yes` means evidence was produced for this exact working tree; `no` means it was not.
Historical predecessor evidence is not promoted into the current artifact's columns.
Desktop-only products use `n/a` for the console cross-build column.

| Component | Implemented | Host tested | Cross-compiled | Emulator tested | Original 2DS | Old 3DS/XL | New 3DS / New 2DS XL |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Portable memory/value layer | yes | yes | yes | no | no | no | no |
| Pack parser + VM + runtime/read plan | yes | yes | yes | no | yes (address-free pack) | no | no |
| Portable journal ledger + trace + logging | yes | yes | not linked into 3GX | no | no | no | no |
| Console ledger + buffered platform log | yes | boundary only | yes | no | yes | no | no |
| Compiler/CLI/simulator | yes | yes | n/a | no | no | no | no |
| 3DS title/identity/memory/lifecycle/storage adapters | yes | boundary only | yes | no | no | no | no |
| Integrated plugin runtime, toast, status/self-test/menu | yes | surrounding boundaries | yes | no | yes | no | no |
| `AMUN.3gx` loader behavior | artifact format only | no | yes | no | yes | no | no |
| Studio editor/library/scanner/debugger/deployer | yes | yes | n/a | n/a | real GDB/MI connection exercised | no | no |
| Luma read-only client | yes | native RSP and GDB/MI fake-server tested | n/a | no | protocol primitives yes | no | no |
| Hub framing/pairing/events/backups | host server yes | yes | n/a | n/a | console client disabled | no | no |
| Address-free hardware self-test generator/runtime path | yes | yes | yes | no | yes | no | no |
| Deterministic release staging | yes | yes | n/a | n/a | no | no | no |

### Historical hardware evidence and disposition

On 2026-08-27, predecessor 3GX SHA-256
`e13bab596760e4b8ab594ec0acdecc0e1be1fbecd734b1d53a363f714fc8cc27`
loaded twice on an original wedge 2DS in Mario Kart 7 EUR, Title ID
`0004000000030700`. Both platform-only runs reached the CTRPF UI and passed the
monotonic-clock and scratch-ledger write/replay/remove checks with zero game reads.
Pause, resume, and stop events were logged. Both runs then crashed during clean menu
teardown because CTRPF double-destroyed a borrowed Tools-menu root.

This is useful loader/UI/storage/lifecycle bring-up evidence for the predecessor, but
the overall result is **failed**. The predecessor hash is **unsafe and retired**. The
ownership patch corrected that specific teardown ownership error.

On 2026-08-30, ownership-fixed 3GX SHA-256
`d6d72a9f6de19d2897696d3e75be890ce12bc119b37004ea0c145d8542184f09`
loaded on the same console class in Mario Kart 7 EUR, full Title ID
`0004000000030700`. Its platform log records monotonic-clock and scratch-ledger
write/replay/remove passes, zero game reads, and lifecycle pause/resume/stop. The tester
reported that the title closed cleanly. However, Down could not move between the two
information rows and B could not close the root overlay. Source review found that all
four information rows were explicitly unselectable and CTRPF's B-close policy retained
its false default. The `d6d72a9f...` hash is superseded for UI usability, but it is not
classified as unsafe. Its Luma version was not recorded.

UI-fixed `d0dcd7a4...` passed the Down/B/reopen controls and produced the stable exact
Mario Kart 7 identity twice. During the exact no-memory pack, AMUN detected the unlock
but its CTRPF adapter wrote only the second record header: APPEND moved the cursor from
zero to the real EOF during `Write`, so the adapter rejected the successful header and
short-circuited the payload. The ledger failure repeated every frame; delayed shutdown
then exposed CTRPF's global `ThreadEx` destructor freeing a possibly running thread.
Luma parsed the exit failure as a write to `0x0000000C` in `_free_r`. This artifact is
retired.

Storage/shutdown-fixed `dfec2647...` then passed the Mario Kart 7 exact-pack run:
the torn tail recovered, the unlock was durable before its toast, relaunch did not
duplicate it, and exit was clean. A no-pack Pilotwings Resort
(`0004000000031D00`) launch stayed visually inert but crashed on exit. Dump 6 reports a
read data abort at zero in `PLGLDR__FetchEvent`, called from `KeepThreadMain` after the
memory-change wait timed out. CTRPF's loader-event pointer was null for that title.
The hash is retired because AMUN is a global fallback plugin.

Current `d579addd...` retains the validated storage/thread changes, guards null
loader-event polls/replies, and passed exact-pack Mario Kart plus no-pack Pilotwings
normal-exit runs. `HARDWARE-TESTED=yes` is scoped to those current-artifact paths.
Read-only Luma research also established the first Mario Kart candidate symbol at
`0x1413C540` with an observed `u32` transition from zero to six. The compiled candidate
pack `925313e2...` did not unlock: one `2112` run failed the plugin memory-region check,
and the newest run identified a different `3152` / `2BE03E4B` build and correctly made
zero profile reads. Studio's direct Luma backend is now the research path for that build.

Host boundary tests do not call `svcQueryMemory`, CTRPF, Luma, GSP, or real SD archive
APIs. “Implemented” in a 3DS row is not shorthand for “loads on console.”

## Verification run

Environment:

```text
Windows x64
CMake 3.27.3
MSVC 19.41.34123.0 (Visual Studio 2022)
Python 3.13.5
configuration: Release unless noted
physical console for this host/cross run: not used
separate hardware evidence: original wedge 2DS used for the superseded d6d72a9f artifact
emulator: not used
devkitARM r68 / libctru 2.7.0 cross-link: completed with pinned patched dependencies
WSL GCC 13.3: fresh ASan+UBSan build
```

Commands and results:

```powershell
cmake --build build-release --config Release --parallel
ctest --test-dir build-release -C Release --output-on-failure
# 3/3 CTest targets passed:
#   amun-core
#   amun-compiler-runtime-integration
#   amun-3ds-platform

./build-release/Release/amun-core-tests.exe
# 36/36 named portable-core cases passed

python -B -m unittest discover -v
# 81 tests discovered: 79 passed, including native Luma RSP process discovery,
# exact-PID attach/detach, 3DS menu, EOF-append, thread-patch, and null loader-event regressions;
# two symlink-fixture tests skipped because this Windows account lacks
# symlink-creation privilege; both pass under WSL/Linux

ctest --test-dir build-fuzz -C RelWithDebInfo --output-on-failure
# core plus four standalone fuzz-smoke targets passed, 5/5 CTest targets

python -B tests/fuzz/fuzz_python_parsers.py
# exit 0; 1,000 deterministic inputs each feed source-profile and AMNP boundaries

wsl.exe -d Ubuntu -u root -- bash -lc "cmake -S '/mnt/<path-to>/amun-3ds' -B /tmp/amun-sanitize-final -G Ninja -DCMAKE_BUILD_TYPE=Debug -DAMUN_BUILD_TESTS=ON -DAMUN_BUILD_TOOLS=ON -DAMUN_BUILD_3DS_PLATFORM_TESTS=ON -DAMUN_BUILD_FUZZERS=ON -DAMUN_ENABLE_SANITIZERS=ON && cmake --build /tmp/amun-sanitize-final --parallel"
wsl.exe -d Ubuntu -u root -- bash -lc "ASAN_OPTIONS=detect_leaks=0:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 ctest --test-dir /tmp/amun-sanitize-final --output-on-failure"
# 7/7 CTest targets passed in 41.69 s with ASan/UBSan halt-on-error
```

Each standalone C++ fuzz target runs 1,000 deterministic inputs up to 4096 bytes:
pack parser, VM verifier/evaluator, trace parser, and ledger parser. These are smoke
mutations, not a coverage-guided campaign. The AMNP network parser is covered by the
Python mutator and focused Hub tests.

The CTest integration target compiles a source profile, runs the C++ simulator through
an unlock, verifies ledger-before-toast durability, restarts, preserves the unlock,
and suppresses the duplicate.

## Determinism and packaging evidence

The current synthetic profile compiled to 3517 bytes with:

```text
pack SHA-256: 4fb012ab2f60716dfa6242f69a4616fda9ecea91661867d576d22c56b8500913
profile hash: 9ab4b06c9b3c86915ea9b3a1477d89c1
```

Two final-tree compilations were byte-for-byte identical. The release input was built
with:

```powershell
python -B amun.py profile build profiles/synthetic `
  -o build/release-final/synthetic-a.amunpack
python -B amun.py profile build profiles/synthetic `
  -o build/release-final/synthetic-b.amunpack
Get-FileHash build/release-final/synthetic-*.amunpack -Algorithm SHA256
```

Release tests exercise traversal rejection, programmatic validation bypasses,
replacement containment, escaping symlinks (on platforms that permit creating the
fixture), the 2 MiB pack limit, current 3GX header/range validation, manifest contents,
plugin/host status metadata, and byte-for-byte ZIP reproduction. Packaging writes both
top-level and plugin `hardwareVerified: false`; no packaging result is hardware
evidence.

## Host benchmark

One verified Windows x64 Release run, 2,000 iterations per size:

| Achievements | Load µs | Start µs | Estimated runtime bytes | Mean tick µs | p95 µs | Max µs | Mean reads | Mean instructions |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 154 | 129 | 7,399 | 16.731 | 22 | 58 | 1.000 | 40 |
| 50 | 262 | 53 | 30,879 | 79.479 | 104 | 189 | 1.000 | 200 |
| 100 | 392 | 38 | 64,693 | 352.838 | 470 | 879 | 1.000 | 400 |
| 250 | 1,988 | 168 | 149,143 | 548.753 | 1,057 | 2,357 | 1.000 | 1,000 |
| 500 | 1,611 | 112 | 319,653 | 774.659 | 1,262 | 1,659 | 1.000 | 2,000 |

The single read demonstrates dependency deduplication in this synthetic setup. The
estimated bytes cover portable runtime-owned dynamic structures, not CTRPF, plugin
code/data, renderer, allocator fragmentation, swap file, or the complete 5 MiB plugin
region. Desktop microseconds do not predict Old2DS ARM11 frame cost. No original-2DS
threshold has passed yet.

## Implemented vertical slice

On the host, the completed path is:

```text
source JSON + schema/semantic checks
→ deterministic little-endian pack
→ independent bounded C++ parse/bytecode verification
→ exact Title ID/build match
→ resolved synthetic/pointer/pattern/derived symbols
→ deduplicated polling
→ stateful VM evaluation under local/global budgets
→ progress or unlock journal append
→ event/toast sink
→ normal end/flush
→ restart/reload without duplicate unlock
```

The cross-compiled 3DS integration links this portable runtime with CTRPF/libctru adapters, an
address-free self-test/status view, a bounded achievement browser, queued toasts,
full-title ledger paths, exact pack load, lifecycle pause/flush, and observer-only
memory reads. The current cross-link includes verified EOF append positioning, a
single-record write, a per-session ledger failure latch, safe timed-thread teardown,
and null-safe loader-event polling/replies. It must repeat both title paths on hardware.

## Current generated artifacts

Current build evidence in this workspace:

```text
build-release/Release/amun-core-tests.exe
build-release/Release/amun-sim.exe
build-release/Release/amun-bench.exe
build/release-final/synthetic-a.amunpack
3ds/AMUN.3gx
3ds/AMUN.elf
3ds/AMUN.map
```

The generated `dist/dev` copies are byte-identical to the three current artifacts;
the release ZIP remains unstaged until hardware acceptance advances.

Current loader-event-guarded cross-build outputs (2026-09-02):

```text
AMUN.3gx  1,318,704 bytes  d579addd00deca524600cf6b058a7ed5d90b49dc2657df7bd24c431a82248571
AMUN.elf  4,579,912 bytes  c73f029094fe1411e31ba6a3091ce8edd073baafdb22f67b9c0063e01ff170c3
AMUN.map  5,097,541 bytes  60606d10f5e141cbe96ca01b570ed3498146db7142ea619dec248fdc2c2d99c5
```

The verified current cross-build produced a `3GX$0002` plugin with SHA-256
`d579addd00deca524600cf6b058a7ed5d90b49dc2657df7bd24c431a82248571`.
`arm-none-eabi-size` reported text 1,005,024, data 9,924, and bss 17,460 bytes:
1,032,408 bytes (`0xFC0D8`) total. The AMUN compile/link completed without diagnostics.
ARM disassembly shows all four `CanBeSelected` calls passing `r1=1`; `PatchProcess`
stores packed word `0x100` at offset 16, enabling `CloseMenuWithB` while its adjacent
booleans remain false. It also shows a null branch before the event poll's `ldrex` and
both reply pointers checked before access. These are cross-build facts, not runtime input, memory, or
hardware measurements. Do not create
`dist/sd-root/luma/plugins/default.3gx` from a host binary; only the Makefile and
license-aware release packager may stage the verified result.

## Exact build and launch commands

Host, Linux/macOS:

```sh
./scripts/bootstrap-host.sh
./scripts/test.sh
./scripts/benchmark.sh
python3 -m studio profiles/synthetic
python3 -m hub --host 127.0.0.1 --data build/hub-data
```

Host, Windows PowerShell:

```powershell
./scripts/bootstrap-host.ps1
./scripts/test.ps1 -Configuration Release
./scripts/benchmark.ps1
python -m studio profiles/synthetic
```

Pinned 3DS environment:

```sh
./scripts/build-3ds.sh
./scripts/package-3ds.sh --replace
```

The manual CI cross job uses
`devkitpro/devkitarm@sha256:116afba8df8453961de2936ffab20dd441edf4d682856c1ec8b0e53d7ed0bbf5`.
Exact dependency commands and Luma GDB setup are in
[`../3ds-toolchain.md`](../3ds-toolchain.md).

## SD tree and first pack

The plugin-bearing base release stages the plugin, disabled self-test example, and
empty AMUN directories. An admitted achievement title additionally needs the exact
pack path; its ledger file is created at runtime:

```text
sd-root/luma/plugins/default.3gx
sd-root/amun/config/
sd-root/amun/ledger/
sd-root/amun/logs/
sd-root/amun/packs/<FULL-16-DIGIT-TITLE-ID>/game.amunpack
```

Copy the contents of `sd-root` to the powered-off console's SD root, enable Plugin
Loader in Rosalina, and launch only the exact supported native build. Use
[`../installing.md`](../installing.md) for rollback and
[`../hardware-test.md`](../hardware-test.md) for the address-free two-stage probe.

## Studio and a real 2DS connection

Launch Studio with `python -m studio`. In the Live 3DS view, use the default direct
Luma RSP backend on a normal context (ports 4000-4002). This avoids the external
GDB/WSL launch path, reads exact PIDs from Luma's `osdata/processes` XML, and highlights
the best profile-name match without auto-attaching. Attach only after verifying the
visible process name, capture bounded read ranges/watch values, then detach to resume
the title. The backend exposes no game-memory write. External GDB/MI remains an
explicit fallback, and only one debugger client should own a context.

Raw GDB equivalent:

```gdb
target extended-remote <3DS-IP>:4000
info os processes
attach <pid>
monitor getmemregions
add-symbol-file 3ds/AMUN.elf 0x07000100
```

The break-on-start context uses Luma's separate port/flow; follow
`3ds-toolchain.md` rather than treating it as `extended-remote`.

## Known limitations and open evidence

- The current `d579addd...` 3GX/ELF/MAP were produced, format-checked, loaded by Luma,
  and passed the scoped Mario Kart exact-pack/Pilotwings no-pack regression.
- Unsafe `e13bab59...` demonstrated loading and several platform checks but crashed in
  teardown. Superseded `d6d72a9f...` demonstrated the same checks and a user-reported
  clean title close, but its Down navigation and B-close policy failed. Retired
  `d0dcd7a4...` passed those controls/identity, then failed exact-ledger append and exit.
  `dfec2647...` passed the Mario Kart exact-pack durability/toast/exit path but failed
  no-pack Pilotwings exit. The current two-title pass validates the loader-event guard.
- Live profile-driven `svcQueryMemory`, swap stress, and sleep-switch timing remain
  unobserved. Both title-close paths for the current binary passed.
- Stock pinned CTRPF reserves substantial memory and initializes broader framework
  behavior; the 5 MiB region remains an unverified Old2DS choice.
- The live fingerprint is a bounded text-size/CRC identity, not a pristine signed
  ExeFS hash. It must be captured and matched exactly per revision.
- The current clock adapter does not explicitly subtract suspended time; timed
  behavior across HOME/sleep is an open hardware/correctness result.
- Console networking is disabled. Hub pairing sends its six-digit code on the same
  unauthenticated channel and is not strong authentication.
- Per-title 3GX files shadow `default.3gx`; Luma loads one plugin.
- A profile can be host-replay correct and still be wrong for a region/update/save.
- Studio's native RSP and optional GDB/MI live clients are read-only and fake-server
  tested; the protocol attach/read/detach path has physical-console evidence, while the
  new in-Studio process-discovery UI still needs its first physical rerun.
- Portable trace construction/replay and Studio snapshot capture are implemented;
  the stable 3GX does not yet record live sessions into `.amuntrace` files.
- No Wii, TWL/DS, DSiWare-in-TWL, AGB/GBA, or `open_agb_firm` runtime exists.

## Next physical test

Phase 2 controls, both Phase 3 identity probes, and Phase 4 storage/toast behavior
passed on predecessors. Start with the new Phase 1A missing-pack regression, then
repeat Phase 4 in
[`../hardware-test.md`](../hardware-test.md) on the original 2DS:

```text
verify current SHA-256 and load the AMUN fallback plugin
→ launch no-pack Pilotwings, use HOME, exit, and require no UI/dump
→ leave the Mario Kart exact pack and current ledger in place
→ run one-second VM condition
→ preserve the existing unlock without a duplicate toast
→ close without a new exception dump and require the shutdown marker
→ relaunch and confirm the same persistent unlock
```

Only then proceed to a researched live symbol and 10/50/100-achievement scaling. Until
that full memory-transition chain passes on the original 2DS, AMUN has not reached its
first release acceptance criterion.
