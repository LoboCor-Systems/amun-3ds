# AMUN 3DS project history

This is the development log that used to be the front of the README: dated hardware results,
retired artifact hashes and research notes, kept verbatim for traceability. For what AMUN is
and how to use it, read the [README](../README.md).

---

# AMUN 3DS

Research update (2026-09-24): the [20-goal MK7 progression candidate](../profiles/mario-kart-7-eur-progression/RESEARCH.md)
adds the two proven race-result goals to the cup/trophy candidate. It is **not the
full 31-goal set and is not deployed**. Eleven race and ghost goals still need
live fields. The accepted coin release below is unchanged.
[Portable Azahar setup and current testing blockers](MK7-EMULATOR-TESTING.md).

Installed release (2026-09-10): [Mario Kart 7 coin preview](../profiles/mario-kart-7-eur-coins/README.md)
and startup-recovery plugin are built and installed on the test SD card. The bundle
is `dist/mk7-coin-fix-20260910`, not the older `dist/sd-root` or release bundles.
Five coin achievements are implemented; the user confirmed Small Savings and Pocket
Change unlocked on the original 2DS and subsequently reported it working before
requesting the full set. Earlier hardware results below apply to earlier hashes.

<p align="center">
  <img src="assets/branding/amun-mark.png" alt="AMUN double-plume emblem" width="220">
</p>

AMUN — Achievement Monitoring Underlaying Network — is an offline-first,
observer-only achievement framework for native Nintendo 3DS software on real
Luma3DS-equipped consoles. The original wedge-shaped Nintendo 2DS is the minimum
hardware target; New-model speed, memory, controls, and services are not required by
the achievement design.

This repository contains a real portable runtime, deterministic profile compiler and
pack parser, journal ledger, replay/synthetic simulator, desktop Studio, optional LAN
Hub, and a current-Luma 3GX platform integration. An early plugin was loaded twice on
an original wedge 2DS, where its platform-only self-test reached the CTRPF UI and
passed its clock, scratch-ledger, zero-game-read, and lifecycle checks. Both runs then
crashed during menu teardown because CTRPF destroyed a borrowed root folder twice.
That predecessor SHA-256,
`e13bab596760e4b8ab594ec0acdecc0e1be1fbecd734b1d53a363f714fc8cc27`, is
**retired and unsafe; do not install it**.

The ownership-fixed SHA-256
`d6d72a9f6de19d2897696d3e75be890ce12bc119b37004ea0c145d8542184f09`
then loaded on the same 2DS in Mario Kart 7 EUR (`0004000000030700`). Its third
appended log session passed clock, scratch-ledger, zero-game-read, and
pause/resume/stop checks, and the user directly reported a clean title close. However,
D-Pad Down could not reach the second information row and B could not close the root
overlay. That build is **superseded for UI usability, not retired as unsafe**.

The UI-fixed `d0dcd7a42704ab3dfe2cd1cf937c9cf9f0679664c261de52d56c4d203c188895`
artifact then passed the corrected controls and two exact-identity discovery launches on
the same 2DS. Its first exact-pack run exposed two linked faults: the CTRPF ledger
adapter rejected its first append to an existing file after writing only the record
header, and the resulting warning storm exposed CTRPF freeing a still-running thread
during timed shutdown. No unlock or toast was published because durability failed; the
title then crashed on exit. That hash is **retired and must not be installed**.

The storage/shutdown-fixed `dfec2647d030f8b0fe2a997d38f815371eb9d17945d1fba0bda2f78e9dd5c226`
artifact subsequently passed the Mario Kart 7 exact-pack recovery, durable unlock,
toast, relaunch, and clean-exit run. A later no-pack launch of Pilotwings Resort
(`0004000000031D00`) correctly showed no AMUN UI, but crashed on exit. Dump 6
symbolicates to CTRPF `PLGLDR__FetchEvent` reading through a null loader-event pointer.
That globally unsafe hash is retired.

The current `3GX$0002` artifact adds null-safe loader-event polling/replies and was
cross-compiled on 2026-09-02 as SHA-256
`d579addd00deca524600cf6b058a7ed5d90b49dc2657df7bd24c431a82248571`.
It subsequently passed the two-title regression on the same original 2DS: Mario Kart
7 loaded its exact address-free pack and closed normally, while no-pack Pilotwings
remained inert and also closed normally. `HARDWARE-TESTED=yes` applies to those scoped
paths; the first profile-driven `svcQueryMemory` unlock remains pending.

## Status

Status vocabulary is literal: **implemented** means code exists, **host tested** means
an automated desktop test exercised it, **cross-compiled** means the ARM/3GX toolchain
produced an artifact, and **hardware tested** requires a recorded physical-console run.

| Feature | Status | Evidence / boundary |
|---|---|---|
| 3GX build path | Implemented; cross-compiled; format verified | Pinned legal toolchain produced ELF/MAP/3GX and passed the `3GX$0002` check |
| 3GX loads | Hardware tested on current artifact | Current hash passed exact-pack Mario Kart and no-pack Pilotwings launch/normal-exit flows |
| Original 2DS | Current artifact hardware tested for the two-title regression | Exact-pack and missing-pack paths passed; first live memory-profile unlock is staged next |
| Old 3DS / Old 3DS XL | Not hardware tested | Same conservative Old-class baseline |
| New 3DS / New 2DS XL | Not hardware tested | No essential New-model-only path |
| Pack compiler / parser | Implemented; host tested; runtime cross-compiled | Deterministic compiler plus independent Python/C++ bounded parsers |
| Exact build identity | Implemented; host tested; predecessor hardware observed | Mario Kart 7 EUR produced stable `live-text-crc32-v1:004EC000:04F718AE` identity twice |
| Memory monitoring | Implemented; host boundary tested; cross-compiled | Read-only Luma research observed Mario Kart lifetime coins `0 -> 6`; profile-driven `svcQueryMemory` run is pending |
| Achievement VM | Implemented; host tested; cross-compiled | Loop-free verified bytecode, stateful conditions, hard budgets |
| Persistent ledger | Implemented; host tested; predecessor hardware observed | Mario Kart recovered the torn tail, durably appended the unlock, and preserved it on relaunch; current binary retains that code plus the event guard |
| Toast / status menu | Implemented; predecessor hardware observed | Mario Kart displayed the ledger-gated unlock toast; current binary needs the two-title regression rerun |
| Missing-pack title gate | Implemented; host and current-artifact hardware tested | Pilotwings stayed inert and closed normally with the null-event guard |
| Studio | Implemented; host tested | Profile editing, local pack library, dump/snapshot scanner, deployment, direct read-only Luma RSP plus optional external GDB/MI |
| Condition debugger | Implemented; host tested | Compile/disassemble/evaluate path with state explanations |
| Live debugging | Read-only protocol hardware exercised | Studio obtains exact PIDs from Luma's process XML without WSL/GDB; the native RSP flow is fake-server tested and its read/attach/detach primitives were hardware exercised |
| Hub / networking | Hub host tested; console disabled | Stable console build intentionally has networking compiled out |
| Wii, TWL/DS, AGB/GBA modes | Out of scope | AMUN v1 targets native 3DS-mode applications only |

The detailed, command-backed snapshot is maintained in
[`docs/engineering/status.md`](engineering/status.md).

The Amun-inspired emblem is decorative project identity, not a claim of historical
reconstruction or affiliation. Its palette and usage rules are in
[`docs/brand.md`](brand.md).

## Host quick start

Requirements are Python 3.11+, CMake 3.20+, and a C++17 compiler. The Python tools
use only the standard library.

Linux/macOS:

```sh
./scripts/bootstrap-host.sh
./scripts/test.sh
python3 amun.py profile validate profiles/synthetic
python3 amun.py profile test profiles/synthetic
python3 amun.py profile build profiles/synthetic -o build/synthetic.amunpack
python3 amun.py pack inspect build/synthetic.amunpack --disassemble
python3 -m studio profiles/synthetic
```

Windows PowerShell with Visual Studio 2022:

```powershell
./scripts/bootstrap-host.ps1
./scripts/test.ps1
python amun.py profile validate profiles/synthetic
python amun.py profile test profiles/synthetic
python -m studio profiles/synthetic
```

Every CLI command has `--help`; start with `python amun.py --help`.

## Console installation layout

Only install a release that actually contains a cross-compiled `AMUN.3gx`. A
host-tools-only archive contains `NO-3GX.txt` and cannot be installed as a plugin.
The release `sd-root` is copied to the root of the SD card without deleting unrelated
files. The base plugin bundle contains `default.3gx`, the disabled self-test example,
and empty AMUN data directories; a compiled pack is added at the path below, and the
ledger file appears only after an admitted title runs:

```text
/luma/plugins/default.3gx
/amun/config/self-test.flag.example
/amun/ledger/<FULL-16-DIGIT-TITLE-ID>.amunledger
/amun/logs/
/amun/packs/<FULL-16-DIGIT-TITLE-ID>/game.amunpack
```

Title IDs are uppercase, zero-padded, and always 16 hexadecimal digits. A per-title
plugin under `/luma/plugins/<TITLE-ID>/` shadows Luma's `default.3gx`; current Luma
loads one plugin, so AMUN cannot compose with another plugin for that title. The pack
must then match the full Title ID and exact build fingerprint before AMUN reads any
profile address.

See [`docs/installing.md`](installing.md) for player installation and
[`docs/3ds-toolchain.md`](3ds-toolchain.md) for the legal cross-build.

## Pinned 3DS baseline

- official Luma3DS v13.4 and its built-in 3GX loader;
- devkitARM r68 and libctru 2.7.0 (`3ds-dev`);
- `devkitpro/devkitarm:20260610`, resolved to OCI digest
  `sha256:116afba8df8453961de2936ffab20dd441edf4d682856c1ec8b0e53d7ed0bbf5`,
  for the optional container build;
- 3gxtool `57e3160ab72d8533a2f0601efdc8a149b4825ea5`;
- CTRPluginFramework `6671936663faaa900f7cfdeedf42bc8581560f4f`.

The exact compatibility patches and rationale are recorded in
[`docs/adr/0001-3gx-platform.md`](adr/0001-3gx-platform.md). Do not silently
substitute other commits when producing a release.

## Repository map

| Path | Purpose |
|---|---|
| `core/` | Portable C++17 runtime, VM, parser, ledger, trace, logging |
| `compiler/`, `cli/`, `amun.py` | Source validation, deterministic compilation, simulation, dump and trace tools |
| `3ds/` | CTRPF/libctru platform adapters and plugin entry point |
| `studio/` | Dependency-free Tk authoring/research app with a filesystem-backed local pack library |
| `hub/` | Optional bounded LAN pairing/event/backup server |
| `profiles/` | JSON Schema, synthetic profile, examples |
| `tests/` | Unit, integration-style vertical slice, fuzz harnesses, benchmark |
| `docs/` | Formats, workflows, decisions, installation, physical test plan |

Start authoring with [`docs/creating-achievements.md`](creating-achievements.md),
then read the [source profile](profile-format.md),
[condition language](condition-language.md), and
[compiled pack](pack-format.md) contracts.

## Release packaging

Host-tools bundle:

```sh
python3 scripts/package-release.py --version 0.1.0 --replace
```

Plugin-bearing bundle (fails if the file is absent, its pinned-format 3GX header or
executable ranges are invalid, or the reviewed CTRPluginFramework license is
unavailable):

```sh
./scripts/package-3ds.sh --replace
```

The packager fixes timestamps using `SOURCE_DATE_EPOCH`, sorts every input, writes
`release.json` and `SHA256SUMS`, and creates a deterministic ZIP. Packaging always
records hardware verification as false; only the hardware report can change that.
The complete evidence and licensing gate is in
[`docs/releasing.md`](releasing.md).

## Safety and scope

AMUN normally reads game memory and writes only its own SD files. Source profiles are
declarative and cannot contain native code, jumps, loops, or game-memory writes.
Developer scanning is read-only and marks provenance as developer/unverified. Do not
use AMUN to distribute copyrighted games, keys, firmware, dumps, saves, or unlicensed
third-party assets. Achievement packs are not a compatibility promise until their
exact revision has been replay-tested and tested on physical hardware.

AMUN is MIT licensed. Console binaries also carry applicable upstream notices; see
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).
