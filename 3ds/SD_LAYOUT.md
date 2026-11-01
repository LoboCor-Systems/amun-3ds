# AMUN SD layout

The package target stages this tree beneath `dist/sd-root/`:

```text
luma/
`-- plugins/
    `-- default.3gx
amun/
|-- config/
|   `-- self-test.flag.example
|-- ledger/
|   `-- <FULL-16-DIGIT-TITLE-ID>.amunledger
|-- logs/
|   `-- platform.log
`-- packs/
    `-- <FULL-16-DIGIT-TITLE-ID>/
        `-- game.amunpack
```

All paths used by the plugin are absolute CTRPF SD-archive paths beginning with
`/amun`. The framework changes the working directory of a fallback plugin to an
ActionReplay directory, so relative AMUN paths are prohibited.

`default.3gx` is Luma's fallback only. A `.3gx` inside
`/luma/plugins/<FULL-16-DIGIT-TITLE-ID>/` shadows it. The current Luma loader selects
only one plugin and per-title directory enumeration is not an AMUN extension mechanism.

The observer accepts only `00040000` native application/game titles and only when the
exact full-title pack path exists. It then parses the bounded pack, validates its
embedded full Title ID, constructs the installed version/region/live-text
fingerprint, and lets `amun::Runtime` require an exact build before any profile
address is read.

A missing pack remains inert unless the user explicitly renames the packaged
`/amun/config/self-test.flag.example` to `/amun/config/self-test.flag`. On an otherwise
eligible native title, that flag opens a platform-only menu and tests the monotonic
clock, configured menu-input delivery, and one temporary AMUN-owned ledger record. It
performs zero game-memory reads and no unlocks, removes its scratch ledger, and never
enables networking. Remove the flag when the platform check is complete.

Each title owns one byte-compatible `AMLG` journal. The CTRPF adapter flushes every
record before publishing it in memory, recovers a torn tail through temporary/backup
renames on the next load, and compacts automatically before the 512 KiB/4096-record
cap. Its deterministic snapshot keeps the complete latest unlock event, or the latest
effective progress event for a still-locked achievement, while discarding session and
superseded checkpoint history. If the retained state itself cannot fit, the adapter
fails closed rather than dropping an unlock. Do not manually delete a full ledger;
archive it for diagnosis.

The same package target maintains `dist/dev/` with matching `AMUN.3gx`, ELF, linker
map, `SHA256SUMS`, and `BUILD-STATUS.txt`. That status deliberately says cross-compiled
yes and hardware-tested no.

Do not copy a development `AMUN.3gx` into the tree merely because host tests pass.
Only the `make package` target may stage a cross-compiled result, and that result is
still **not hardware verified** until exercised on a console.
