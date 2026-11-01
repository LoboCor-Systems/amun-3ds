# Physical hardware test procedure

## Current coin-preview check (2026-09-10)

New plugin `dbf62712...` and pack `e3ae5fa6...` are installed on the test SD card.
See [the exact bundle record](../dist/mk7-coin-fix-20260910/BUILD-RECORD.md).
This pair is cross-built and host-tested. The user reports Small Savings and Pocket
Change unlocked on hardware; normal exit/relaunch acceptance remains pending.
Luma's read-only debugger confirmed version v13.4, MK7 effective build 3152, text
CRC `2BE03E4B`, and coin value 30 at `0x1413C540`. Startup retries and unavailable-data
handling were fixed; only the five coin goals are executable.

Acceptance: load the saved coin total, observe Small Savings at 30; collect new
coins for Pocket Change; check both in the browser; exit normally; relaunch with no
duplicate unlock. Then review the new appended log and ledger. Preserve the ledger.

The following sections are historical evidence, not acceptance of the new hash.

Several predecessor artifacts have physical-console evidence. They successively exposed
borrowed-root teardown, root-menu input, existing-ledger/timed-thread shutdown, and a
missing CTRPF loader-event channel. The current event-guarded artifact needs focused
no-pack and exact-pack reruns on the original wedge-shaped Nintendo 2DS (Old-class
hardware) with current official Luma3DS.

Do not begin with a valuable save or an unbacked-up SD card. AMUN executes inside the
game process; a platform fault can close the game or reboot the console.

## Recorded hardware history

On 2026-08-27, predecessor `AMUN.3gx` SHA-256
`e13bab596760e4b8ab594ec0acdecc0e1be1fbecd734b1d53a363f714fc8cc27`
loaded twice on an original wedge 2DS in Mario Kart 7 EUR, full Title ID
`0004000000030700`. The Luma version was not recorded and must not be guessed. Both
platform-only self-test sessions reached the CTRPF UI and reported:

- monotonic clock: pass;
- scratch-ledger write, replay, and removal: pass;
- menu/UI input: pass;
- game-memory reads: 0; and
- lifecycle pause, resume, and stop events observed.

Both sessions then crashed during clean menu teardown. Symbolicated Luma dumps traced
the failure to CTRPF deleting a borrowed Tools-menu root and later destroying the same
object again during `PluginMenu` teardown. Therefore the run result is **failed**, no
acceptance row is promoted, and that predecessor hash is **retired and unsafe**.

The ownership-fixed replacement `AMUN.3gx`, SHA-256
`d6d72a9f6de19d2897696d3e75be890ce12bc119b37004ea0c145d8542184f09`,
was tested on 2026-08-30 on the same original wedge 2DS and Mario Kart 7 EUR,
full Title ID `0004000000030700`. The Luma version was still not recorded. Its third
appended `platform.log` session reported a passing monotonic clock, passing scratch-
ledger write/replay/removal, zero game-memory reads, and lifecycle pause, resume, and
stop. The title then closed normally. This is positive evidence that the borrowed-root
ownership repair fixed clean teardown; this artifact is **not unsafe**.

That run also found a UI acceptance failure: Down could not select the second
self-test information row, and B did not close the root overlay. The artifact is
therefore **superseded for usability**, not promoted to a Phase 2 pass.

The UI-fixed replacement, `AMUN.3gx` SHA-256
`d0dcd7a42704ab3dfe2cd1cf937c9cf9f0679664c261de52d56c4d203c188895`,
then passed Down/B/reopen behavior and two identity-discovery launches on the original
2DS. Mario Kart 7 EUR identity was stable at Title ID `0004000000030700`, effective
version `2112`, fingerprint `live-text-crc32-v1:004EC000:04F718AE`.

Its first exact no-memory pack run detected `hardware_self_test`, but the first append
to the existing ledger wrote only the 24-byte `AMLE` unlock header. AMUN therefore
correctly suppressed the unlock publication and toast, then repeated the failed append
until exit. The supplied ledger was 235 bytes and ended immediately after that header.
The log ended at lifecycle stop without the shutdown marker. Official Luma parsing of
dump SHA-256
`4a66c03d11ce021ecf7e4bc54454a5d32f9f02331ab0127b153da56caeb8c07b`
reported a write to `0x0000000C` at `_free_r`, called from
`CTRPluginFramework::ThreadEx::~ThreadEx`. This hash is retired.

The EOF-append and safe-thread-destruction replacement, `AMUN.3gx` SHA-256
`dfec2647d030f8b0fe2a997d38f815371eb9d17945d1fba0bda2f78e9dd5c226`,
then passed the Mario Kart 7 exact-pack recovery run: the torn ledger recovered, the
unlock was durably recorded before its toast, the relaunch did not duplicate it, and
the title closed normally. A later no-pack Pilotwings Resort run, Title ID
`0004000000031D00`, correctly displayed no AMUN UI but crashed on exit. Official Luma
dump 6 (SHA-256
`308aa99fcad91e2195eae83ed537e0f4bafdf33e66bb9db73b0ca825f3014a4d`)
parsing reports a read data abort at `0x00000000`; the PC symbolicates to
`PLGLDR__FetchEvent`, called by `CTRPluginFramework::KeepThreadMain` after a timeout.
CTRPF had not obtained a loader-event pointer for that title but polled it anyway.
The hash is retired because a global fallback plugin must be safe on missing-pack titles.

The current null-event-guarded replacement built on 2026-09-02 has `AMUN.3gx`
SHA-256
`d579addd00deca524600cf6b058a7ed5d90b49dc2657df7bd24c431a82248571`.
ARM disassembly verifies a null branch before `PLGLDR__FetchEvent`'s exclusive read and
guards both pointers before replies. On the original wedge 2DS, the current hash passed
the exact-pack Mario Kart 7 path and closed normally. It then
passed the no-pack Pilotwings path: AMUN remained inert and the title closed normally.
For these scoped two-title paths, `HARDWARE-TESTED=yes`.

On 2026-09-02, a subsequent read-only Luma session attached to Mario Kart PID 41 and
recorded the writable process map. The exact EUR build remained Title ID
`0004000000030700`, effective version `2112`, fingerprint
`live-text-crc32-v1:004EC000:04F718AE`. Address `0x1413C540` read as little-endian
`u32` zero before a normal single-player 50cc Grand Prix, then read as six while Mario
Kart Channel displayed a lifetime coin total of six. The candidate profile passed
three embedded scenarios and compiled deterministically to 980-byte pack SHA-256
`925313e27eea46f32bf787853cafef19acffb3e03578d8f1402a1af1335da74f`, profile hash
`adcd691e572331f3a5c6e370fa432441`.

The subsequent physical run did not validate the candidate. One `2112` boot logged
`failed to resolve symbol save.total_coins`, so the plugin's memory adapter never
sampled it. The newest boot then reported effective version `3152` and fingerprint
`live-text-crc32-v1:004EC000:2BE03E4B`; exact matching correctly selected the unknown-
build path and performed zero profile reads. No `pocket_change` event was appended.
The `2112` address must not be reused for `3152` without a new read-only scan.

## Test record

Create one copy of this block per artifact/title/build:

```text
Date/time (UTC):
Tester:
Console model:
System version:
Luma version:
Plugin loader enabled:
AMUN Git revision:
Source archive/tree SHA-256 (required if uncommitted):
AMUN.3gx SHA-256:
AMUN.elf SHA-256:
Release ZIP SHA-256:
SHA256SUMS SHA-256:
Full Title ID:
Game name/region:
Application version:
Update version:
Pack SHA-256:
Pack profile hash:
SD make/model/filesystem/free space:
Prior per-title plugin present:
Wi-Fi state:
Result:
First failing step:
platform.log attached:
ledger attached:
Photos/video attached:
```

Never change a row from pending to pass without the artifact hashes and observable
result. A successful New3DS run does not satisfy the original-2DS row.

## Phase 0: desktop gate

Before touching the SD card:

```sh
./scripts/test.sh
python3 amun.py profile validate profiles/synthetic
python3 amun.py profile test profiles/synthetic
python3 amun.py profile build profiles/synthetic -o build/synthetic-a.amunpack
python3 amun.py profile build profiles/synthetic -o build/synthetic-b.amunpack
cmp build/synthetic-a.amunpack build/synthetic-b.amunpack
python3 amun.py pack inspect build/synthetic-a.amunpack --disassemble
SOURCE_DATE_EPOCH=946684800 ./scripts/package-3ds.sh --replace
(cd dist/release/AMUN-3DS-v0.1.0 && sha256sum -c SHA256SUMS)

cmake -S . -B build/hardware-fuzz -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DAMUN_BUILD_TESTS=ON -DAMUN_BUILD_TOOLS=OFF \
  -DAMUN_BUILD_3DS_PLATFORM_TESTS=OFF -DAMUN_BUILD_FUZZERS=ON
cmake --build build/hardware-fuzz --parallel
ctest --test-dir build/hardware-fuzz --output-on-failure \
  -R '^amun-fuzz-.*-smoke$'
python3 -B tests/fuzz/fuzz_python_parsers.py
```

On Windows, use `scripts/test.ps1`, `Compare-Object` or matching
`Get-FileHash` output for the two packs, and `scripts/package-3ds.ps1 -Replace`.

Require all of these:

- host unit/integration-style tests pass;
- standalone fuzz smoke passes;
- the exact profile scenarios pass;
- two compilations of the source pack have identical SHA-256;
- `AMUN.3gx` begins with `3GX$0002`;
- `SHA256SUMS` validates after extraction;
- `release.json` says `plugin-present-not-hardware-verified`, with both top-level
  and plugin `hardwareVerified` values set to false.

Record the host benchmark CSV. It is comparison data, not an Old2DS measurement.

## Phase 1: recoverable SD setup

1. Power the console off completely.
2. Image or back up the SD card, at minimum `/luma/plugins/` and `/amun/`.
3. Check for `/luma/plugins/<FULL-TITLE-ID>/`; move any conflicting plugin to the
   backup. A per-title plugin shadows `default.3gx`.
4. Copy the release `sd-root` contents.
5. Keep a second SD copy without AMUN so recovery does not depend on a crashing boot.
6. Boot, open Rosalina, confirm Luma version, and enable **Plugin Loader**.

AMUN is an application plugin, not `boot.firm`; removing its `default.3gx` with power
off must restore the previous title behavior.

### Phase 1A: missing-pack inert-title regression

Before enabling the self-test flag, leave Pilotwings Resort
(`0004000000031D00`) without `/amun/packs/0004000000031D00/game.amunpack`. Launch it,
play briefly, use HOME once, resume, and close it normally. AMUN must display no menu,
toast, or status UI, create no per-title AMUN log or ledger, and create no exception
dump. This specifically retests dump 6's absent CTRPF loader-event channel. Stop if it
fails; do not continue to an exact-pack test with that artifact.

## Phase 2: explicit platform-only self-test with zero game reads

Use the current fixed artifact identified above. If the 3GX hash is
`e13bab596760e4b8ab594ec0acdecc0e1be1fbecd734b1d53a363f714fc8cc27`,
remove it without launching: that predecessor is retired and unsafe. The
`d6d72a9f6de19d2897696d3e75be890ce12bc119b37004ea0c145d8542184f09`
artifact is clean-teardown evidence but is also superseded because it cannot complete
the required UI sequence. A Phase 2 pass requires both working UI controls and a
normal close with no exception dump, not merely passing values while the menu is open.
Also remove retired
`d0dcd7a42704ab3dfe2cd1cf937c9cf9f0679664c261de52d56c4d203c188895`;
it fails the exact existing-ledger path even though its platform controls worked.
Also remove retired `dfec2647d030f8b0fe2a997d38f815371eb9d17945d1fba0bda2f78e9dd5c226`;
it passed the Mario Kart exact-pack path but crashes on Pilotwings' no-pack exit.

The release stages `/amun/config/self-test.flag.example`. With the console powered
off, ensure the chosen native title has no exact-title pack and rename the example to:

```text
/amun/config/self-test.flag
```

Launch one normal native application whose Title ID begins `00040000`. This explicit
global opt-in admits only a missing-pack native title and runs a separate platform
path. Exercise the **AMUN platform self-test** in this exact order:

1. Open the root overlay with `L+Select`.
2. With **Platform checks** selected, verify its note reports the full native Title ID
   class gate as pass, monotonic clock as pass, temporary AMUN-owned ledger
   write/replay/removal as pass, zero game-memory reads, zero achievement unlocks, and
   networking compiled out.
3. Press Down and confirm that the selected row changes to **Menu input check**, whose
   note reports delivery rather than pending.
4. Press B at the root and confirm that it closes only the AMUN overlay.
5. Press `L+Select` again and confirm that the overlay reopens.
6. Close the title normally and confirm that no exception dump is created.

Inspect `platform.log` for the same results and the pause/resume/stop lifecycle. Confirm
`/amun/ledger/platform-self-test.tmp` was removed. Power off and remove
`self-test.flag` immediately; leaving it installed opts every native missing-pack title
into the test UI. This phase does not parse an achievement pack, fingerprint the game,
or exercise a toast.

## Phase 3: identity-discovery pack with zero profile reads

The repository includes an address-free two-stage generator at
`profiles/hardware-self-test/generate.py`. It deliberately uses no symbol or
profile-defined memory address.

Phase 2 reveals the native title's full ID. For the first probe, use the title's known
region and `0` as a temporary application version if the effective version is not yet
known. Those two fields cannot admit the build because the generated fingerprint is a
deliberately nonmatching sentinel. Generate the probe without a fingerprint:

```sh
python3 profiles/hardware-self-test/generate.py \
  --title-id 000400001234ABCD \
  --region EUR \
  --application-version 0 \
  -o self-test/profile.json
python3 amun.py profile validate self-test
python3 amun.py profile build self-test -o self-test/game.amunpack
```

The generator uses a syntactically valid SHA-256 sentinel that cannot equal the
console adapter's `live-text-crc32-v1` scheme. Remove `self-test.flag`, place the probe
at `/amun/packs/<TITLE-ID>/game.amunpack`, and launch. It must produce an unknown-build
status and zero profile reads. Open the AMUN menu and record:

- full Title ID;
- parsed pack byte count and Title ID gate result;
- identity result and exact fingerprint string;
- runtime status/build match;
- total reads (must remain zero);
- memory guard statement and networking-disabled statement;
- `platform.log` identity line, including the adapter's actual region and effective
  decimal application version.

If the first probe used a guessed region or version, regenerate it with the exact
logged values but still omit `--fingerprint`. Relaunch and require the same stable
fingerprint, unknown-build result, and zero profile reads. This second discovery launch
prevents a guessed version from leaking into the exact self-test pack.

The adapter reads the bounded executable text to compute identity; it does not use any
profile-defined address during this phase. If the title crashes, remove `default.3gx`
before another launch and report this phase as failed.

## Phase 4: no-memory pack/ledger/toast self-test

Regenerate with the exact emitted fingerprint; do not hand-edit its scheme, size, or
CRC:

```sh
python3 profiles/hardware-self-test/generate.py \
  --title-id 000400001234ABCD \
  --region EUR \
  --application-version 0 \
  --fingerprint live-text-crc32-v1:SSSSSSSS:CCCCCCCC \
  -o self-test/profile.json --force
python3 amun.py profile test self-test
python3 amun.py profile build self-test -o self-test/game.amunpack
python3 amun.py pack inspect self-test/game.amunpack
```

Deploy only the rebuilt pack. Its bounded duration-over-true condition waits one
monotonic second, avoiding an unconditional instant-unlock profile. On launch:

1. **Runtime status** must become running with an exact build.
2. **Platform self-test** must show pack parsed, full-TID gate pass, identity pass,
   ledger loaded, `svcQueryMemory + bounded copies`, networking compiled out, and no
   AMUN game-memory writes.
3. The `hardware_self_test` achievement must append to the ledger before its
   toast is shown.
4. **Achievements** must show it unlocked without revealing any game-derived state.
5. Close the game normally and confirm `platform.log` records storage flush.
6. Copy and hash the ledger, relaunch, and confirm no duplicate toast/event while the
   achievement remains unlocked.

For the Mario Kart 7 regression rerun, first copy the supplied ledger somewhere safe,
then leave the current ledger and exact pack in place. Replace only `default.3gx` with
current hash `d579addd...`; do not delete the ledger. The exact pack
SHA-256 is
`bb51f71f1a23c60364104bca74f8d3ea9ebe92c21e8543e6d4321d99beffdeef`.
If retesting from the original 235-byte torn ledger, the status note must report
`torn tail recovered`, `hardware_self_test` must toast exactly once, and the ledger must
grow with a complete CRC-valid unlock record. If retaining the already-recovered
ledger, the first launch must preserve the unlock without another toast. In both cases,
normal close must append the shutdown marker without creating an exception dump.

This separates loader, identity, pack, VM, ledger, menu, and toast failures from a
commercial-game symbol error. It does **not** test `ThreeDSMemoryReader` against a
profile address or prove achievement correctness for that game.

## Phase 5: original-2DS lifecycle

Run on the wedge 2DS using its physical sleep switch; do not describe it as closing a
lid.

| Action | Expected result | Pass / evidence |
|---|---|---|
| Enter HOME, wait 30 s, resume | game and AMUN resume; no duplicate unlock | |
| Repeat HOME 10 times | no hang/reboot; ledger remains valid | |
| Engage sleep switch, wait 60 s, resume | runtime resumes; record duration behavior. The current clock adapter has no explicit suspended-time subtraction, so this is an open correctness result | |
| Disengage/engage sleep repeatedly | nested lifecycle state resumes only after all reasons clear | |
| Close software from HOME | bounded flush; next load recovers ledger | |
| Power off only after normal close | no torn record | |

Current Luma-managed Old-class swap behavior and the 5 MiB plugin allocation are the
highest-risk platform boundaries. Record any `/luma/plugins/.swap` symptom or reboot.
Do not set `SwapNotNeeded` or private memory merely to make a test pass.

## Phase 6: fault injection

Perform mutations only with the console powered off and retain the known-good files.
Never hot-remove the SD card from a powered console.

| Case | Safe setup | Expected behavior | Result |
|---|---|---|---|
| Missing pack | move exact pack aside | AMUN gate inert; game runs | |
| Unknown build | use discovery fingerprint | unsupported/exact-build status; zero profile reads | |
| Truncated pack | truncate a copy | parser rejects; observer disabled; game remains usable | |
| Bad pack CRC | flip one payload byte | checksum rejection | |
| Unsupported pack version | alter a copy, recompute nothing | rejection | |
| Missing AMUN directories | rename `/amun` backup | no crash; diagnostic if admitted path exists | |
| Torn ledger tail | append partial bytes to a copy | valid prefix recovered and reported | |
| Corrupt ledger header | alter a copy | ledger disabled/reported; no fabricated unlock | |
| Wi-Fi disabled | normal stable build | no effect; networking is compiled out | |
| Hub absent | normal stable build | no effect | |
| Per-title plugin exists | restore conflict temporarily | documented shadowing; AMUN does not load | |

After every case restore the known-good pack/ledger and verify its hash.

## Phase 7: real memory and scaling acceptance

This phase requires a separately researched exact-build profile with at least one safe,
stable live symbol and negative tests. Do not use the no-memory self-test as evidence.

| Check | 10 achievements | 50 achievements | 100 achievements |
|---|---:|---:|---:|
| Pack loads | | | |
| Symbol resolves after cold restart | | | |
| Deduplicated reads match expected plan | | | |
| Correct transition unlocks once | | | |
| Negative path remains locked | | | |
| Toast renders without visible corruption | | | |
| Average tick (µs) | | | |
| p95 tick (µs) | | | |
| maximum tick (µs) | | | |
| pack load (ms) | | | |
| symbol resolution (ms) | | | |
| ledger append (ms) | | | |
| plugin/runtime memory (bytes) | | | |

Also measure toast rendering cost separately and repeat with notifications disabled if
possible. Optimization decisions use the original-2DS figures even when a New3DS is
faster.

## Model matrix

| Artifact / check | Original 2DS | Old 3DS/XL | New 3DS/XL | New 2DS XL |
|---|---|---|---|---|
| Retired `e13bab596760e4b8ab594ec0acdecc0e1be1fbecd734b1d53a363f714fc8cc27`: loader + platform-only self-test | **failed**: checks passed twice, then teardown crashed twice | not run | not run | not run |
| Superseded `d6d72a9f6de19d2897696d3e75be890ce12bc119b37004ea0c145d8542184f09`: loader + platform-only self-test | **partial**: third appended session passed clock, scratch ledger, zero reads, lifecycle, and clean title close; Down navigation and root-B close failed | not run | not run | not run |
| Retired `d0dcd7a42704ab3dfe2cd1cf937c9cf9f0679664c261de52d56c4d203c188895`: UI-fixed loader + exact no-memory pack | **failed**: controls and identity passed; first existing-ledger unlock append tore after its header, no toast was published, and delayed exit crashed | not run | not run | not run |
| Retired `dfec2647d030f8b0fe2a997d38f815371eb9d17945d1fba0bda2f78e9dd5c226`: EOF append + safe thread teardown | **mixed/retired**: Mario Kart exact-pack recovery/unlock/toast/relaunch/exit passed; Pilotwings no-pack exit crashed in null `PLGLDR__FetchEvent` | not run | not run | not run |
| Current `d579addd00deca524600cf6b058a7ed5d90b49dc2657df7bd24c431a82248571`: null-safe loader events | **pass**: exact-pack Mario Kart and no-pack Pilotwings both closed normally | pending | pending | pending |
| address-free runtime/ledger/toast self-test | **pass** on current artifact | pending | pending | pending |
| Mario Kart `pocket_change` live-memory candidate pack `925313e2...` | staged; physical unlock pending | pending | pending | pending |
| 10 live achievements | pending | pending | pending | pending |
| 50 live achievements | pending | pending | pending | pending |
| 100 live achievements | pending | pending | pending | pending |
| HOME/sleep/exit | pending | pending | pending | pending |
| corrupt pack/ledger recovery | pending | pending | pending | pending |

## Acceptance decision

The first release criterion passes only when the same original-2DS artifact demonstrates:

```text
exact native title/build admitted
→ live game-memory transition observed
→ correct achievement appended durably
→ toast displayed
→ normal game close/flush
→ later launch preserves unlock
→ no duplicate unlock
```

Cross-compilation, Citra, host replay, a no-memory constant trigger, or New3DS-only
testing cannot substitute for that chain. Add the signed-off evidence and hashes to
[`engineering/status.md`](engineering/status.md) only after the physical run.
