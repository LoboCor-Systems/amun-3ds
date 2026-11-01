# Original Nintendo 2DS compatibility

The wedge-shaped original Nintendo 2DS is AMUN's minimum-spec reference device. A
retired predecessor reached the platform-only self-test on this model but failed clean
teardown twice. Its ownership-fixed replacement passed the platform checks and closed
cleanly, but failed root-menu Down/B usability. A later UI-fixed artifact passed those
controls and exact identity, then failed its first existing-ledger unlock append and
delayed exit. Its storage/shutdown-fixed successor passed the Mario Kart 7 exact-pack
unlock/toast/exit path, but a no-pack Pilotwings run exposed a null CTRPF loader-event
channel on exit. The newly guarded artifact has not been run there, so the checklist
below remains **not hardware verified** for the current build.

## Feature classes

| Class | Features |
|---|---|
| ALL MODELS | Exact build match, pack parsing, memory observation, condition evaluation, local ledger, toast/menu, offline play, trace capture, compatibility/balanced modes |
| NEW-MODEL ENHANCED | Optional higher developer scan rate, larger authoring captures, richer animation after measurement |
| NEW-MODEL ONLY | None required for achievements; no current v1 feature is intentionally New-only |

AMUN assumes neither 804 MHz mode, L2 cache, extra cores/FCRAM, stereoscopic 3D, C-Stick, nor
ZL/ZR. Both logical screens exist on a 2DS; the user interface must not depend on stereoscopic
separation or on physically closing a lid. The 2DS sleep switch and HOME lifecycle must be tested
as their own facilities.

## Runtime budgets

The initial 3GX reservation is 5 MiB because current CTRPF itself reserves substantial runtime
space and the current Luma swap path is built around 2/5/10 MiB choices. These are design caps,
not measured hardware results:

| Item | Hard/default bound | Normal profile target |
|---|---:|---:|
| Whole `.amunpack` | 2 MiB | <= 512 KiB |
| Symbols | 1,024 | <= 256 |
| Achievements | 500 | <= 100 |
| VM stack per achievement | 64 values | <= 16 |
| VM state slots per achievement | 256 | <= 32 |
| VM instructions per achievement | 2,048 | <= 256 |
| VM instructions per tick | 100,000 | <= 10,000 |
| Pointer depth | 8 | <= 4 |
| Signature | 128 bytes | <= 32 bytes |
| Decoded asset | 32 KiB | 8 KiB icon |
| Buffered log | 16 KiB | production INFO/WARN |

Balanced polling defaults are FAST 17 ms, NORMAL 100 ms, SLOW 1,000 ms, and STATIC once. These
are configurable and must be adjusted from hardware measurements. Compatibility mode raises the
FAST floor to 33 ms and NORMAL to 150 ms. The VM stack is fixed storage during ticks; symbol reads
are deduplicated before achievements evaluate.

## Physical acceptance checklist

Record console model, Luma version, AMUN commit/artifact hash, game/homebrew title, pack hash, and
SD card for every run.

- [ ] Official Luma plugin loader enables and `default.3gx` loads.
- [ ] Unsupported titles launch normally and AMUN stays inert.
- [ ] Full title ID, model class, installed version, and `.text` fingerprint display correctly.
- [ ] Missing, truncated, wrong-version, oversized, and bad-CRC packs do not crash the title.
- [ ] Safe absolute, module-relative, pointer-chain, and signature reads work.
- [ ] Unknown executable fingerprint causes zero profile memory reads.
- [ ] 10, 50, and 100 active achievements run; 250/500 are benchmark-only stress cases.
- [ ] Average, p95, and maximum tick; read count; instruction count; and memory footprint are captured.
- [ ] Toast and menu render on the selected logical screen without persistent game-input capture.
- [ ] D-Pad Down reaches the second information row, B closes the root overlay, and the configured chord reopens it.
- [ ] Secret masking, measured progress, points, and count-based completion are correct.
- [ ] Unlock is in the ledger before toast; close/relaunch preserves it with no duplicate.
- [ ] Truncated ledger tail recovers; unavailable/read-only/removed SD fails safely.
- [ ] HOME enter/exit, sleep switch, shutdown, and Luma swap callbacks flush/stop within deadline.
- [ ] Wi-Fi disabled and Hub absent have no gameplay effect.
- [ ] Developer networking build is tested separately; stable observer build does not initialize SOC.
- [ ] No New3DS service, input, CPU, cache, extra core, or extended-memory dependency is observed.

## Current evidence

The portable core is host-tested. On 2026-08-27, predecessor 3GX SHA-256
`e13bab596760e4b8ab594ec0acdecc0e1be1fbecd734b1d53a363f714fc8cc27`
loaded twice on an original wedge 2DS with Mario Kart 7 EUR
(`0004000000030700`). The CTRPF self-test UI, clock, scratch-ledger
write/replay/remove, zero game reads, and pause/resume/stop callbacks were observed,
but both sessions crashed during CTRPF menu teardown. That hash is **unsafe and
retired**, and none of the acceptance boxes above may be checked from those runs.

Ownership-fixed SHA-256
`d6d72a9f6de19d2897696d3e75be890ce12bc119b37004ea0c145d8542184f09`
loaded on the same original wedge 2DS in Mario Kart 7 EUR
(`0004000000030700`) on 2026-08-30. A third appended platform-log session recorded
clock pass, scratch-ledger write/replay/remove pass, zero game reads, and ordered
pause/resume/stop callbacks. The user directly reported a clean title close, providing
the teardown result that the pre-destruction log marker cannot prove by itself.
However, D-Pad Down could not reach the second information row and B could not close
the root overlay. This hash is **superseded for UI usability, not unsafe**.

UI-fixed SHA-256
`d0dcd7a42704ab3dfe2cd1cf937c9cf9f0679664c261de52d56c4d203c188895`
subsequently passed the Down/B controls and two identity-discovery runs on the same
console. Its exact-pack run detected the no-memory achievement but failed the first
existing-ledger append, correctly emitted no toast, and crashed during exit after the
repeated failures delayed CTRPF shutdown. It is retired.

EOF-append and safe-thread-destruction SHA-256
`dfec2647d030f8b0fe2a997d38f815371eb9d17945d1fba0bda2f78e9dd5c226`
then recovered the Mario Kart 7 torn ledger, durably unlocked and toasted once,
preserved the unlock on relaunch, and closed cleanly. In Pilotwings Resort
(`0004000000031D00`), the same global plugin correctly presented no UI because no
exact pack existed, but crashed on exit. Official dump parsing reports a read data
abort at address zero in CTRPF `PLGLDR__FetchEvent`; its loader-event pointer was null.
That hash is retired because an unsupported game must never crash.

The current null-event-guarded build, cross-compiled on 2026-09-02, has SHA-256
`d579addd00deca524600cf6b058a7ed5d90b49dc2657df7bd24c431a82248571`.
It treats a missing event channel as idle and makes replies no-ops. It passed both the
Mario Kart exact-pack case and Pilotwings no-pack normal-exit case on the original 2DS;
`HARDWARE-TESTED=yes` is scoped to those paths. Host timing remains regression evidence
only, and the first live memory-profile unlock remains pending.
