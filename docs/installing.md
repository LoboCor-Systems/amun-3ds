# Installing AMUN on a 3DS-family console

This procedure is for native 3DS-mode games on a console that already has
boot9strap and current official Luma3DS. It does not add support for DS/TWL mode,
DSiWare running in TWL mode, GBA/AGB mode, or `open_agb_firm`.

## Before copying anything

You need:

- a 3DS-family console with current official Luma3DS and accessible SD card;
- the Luma plugin loader enabled;
- a release whose `release.json` says `plugin-present-not-hardware-verified` (or a
  later status backed by an actual hardware report);
- an `.amunpack` built for the game's **full Title ID and exact installed build**.

The pinned toolchain produced the current loader-event-guarded, format-verified
`AMUN.3gx` on 2026-09-02, but that artifact remains **not hardware tested**. Its
SHA-256 is
`d579addd00deca524600cf6b058a7ed5d90b49dc2657df7bd24c431a82248571`.
Install only the canonical plugin-bearing package with its manifest and matching debug
artifacts. A package with `NO-3GX.txt` is a host-tools package and cannot be installed
on the console. Do not rename an ELF, test executable, or arbitrary file to
`AMUN.3gx`.

Ownership-fixed SHA-256
`d6d72a9f6de19d2897696d3e75be890ce12bc119b37004ea0c145d8542184f09`
loaded and closed cleanly on the original wedge 2DS, but D-Pad Down could not reach
the second information row and B could not close the root overlay. It is superseded.
It is not classified as unsafe, but should not be installed
for further acceptance testing.

Never install predecessor SHA-256
`e13bab596760e4b8ab594ec0acdecc0e1be1fbecd734b1d53a363f714fc8cc27`.
It loaded on an original 2DS, but crashed twice during CTRPF menu teardown and is
**unsafe and retired**.

Also remove UI-fixed predecessor SHA-256
`d0dcd7a42704ab3dfe2cd1cf937c9cf9f0679664c261de52d56c4d203c188895`.
It passed menu controls and identity discovery, but its first exact-pack append left a
torn ledger tail and its delayed exit reached an unsafe CTRPF thread destructor.

Also remove storage/shutdown-fixed predecessor SHA-256
`dfec2647d030f8b0fe2a997d38f815371eb9d17945d1fba0bda2f78e9dd5c226`.
It passed the Mario Kart 7 exact-pack recovery/unlock/toast/exit flow, but the global
plugin later crashed on a no-pack Pilotwings exit because CTRPF polled a null
loader-event pointer. Only the current guarded hash should be used for the retest.

Verify the archive hash supplied by the build and then verify its internal manifest:

```sh
sha256sum AMUN-3DS-v0.1.0.zip
cd AMUN-3DS-v0.1.0
sha256sum -c SHA256SUMS
```

PowerShell equivalent for an individual file:

```powershell
Get-FileHash .\AMUN-3DS-v0.1.0.zip -Algorithm SHA256
```

`AMUN.3gx` must begin with the eight ASCII bytes `3GX$0002`. The release packager
checks that marker plus the pinned-format header and bounded executable/metadata
ranges, but structural checks do not prove the plugin is safe or hardware-tested.

## SD card tree

Back up any files that will be replaced. Copy the **contents** of `sd-root/` to the
root of the SD card, preserving this layout:

```text
SD:/
├── luma/
│   └── plugins/
│       └── default.3gx
└── amun/
    ├── config/
    │   └── self-test.flag.example
    ├── ledger/
    │   └── <FULL-16-DIGIT-TITLE-ID>.amunledger
    ├── logs/
    └── packs/
        └── <FULL-16-DIGIT-TITLE-ID>/
            └── game.amunpack
```

For Title ID `000400001234ABCD`, the exact pack path is:

```text
SD:/amun/packs/000400001234ABCD/game.amunpack
```

Use uppercase, zero-padded, 16-digit hexadecimal Title IDs. Do not shorten the ID to
its low 32 bits. AMUN's global title gate admits only normal native applications with
the `00040000` high word and only when the exact pack path exists. The pack parser and
runtime then independently require the embedded full Title ID and build identity.

Luma checks a per-title plugin before `/luma/plugins/default.3gx`. If this directory
exists for the game:

```text
SD:/luma/plugins/<FULL-16-DIGIT-TITLE-ID>/
```

its plugin shadows AMUN's fallback. Current Luma loads one 3GX, not a chain. Move the
conflicting per-title plugin out of the directory after backing it up; AMUN cannot
merge with it.

## Enable and launch

1. Insert the SD card and boot normally.
2. Open Rosalina (normally `L` + D-Pad Down + `Select`).
3. Enable **Plugin Loader**.
4. Exit Rosalina and launch the supported native 3DS game.
5. Open the plugin menu with the pinned build's initial `L` + `Select` chord. CTRPF's
   **Tools > Settings > Change menu hotkeys** can persist a replacement. Inspect
   **Runtime status** and **Platform self-test** before playing.

On the current fixed build, verify the root-overlay controls explicitly:

1. With the first information row highlighted, press D-Pad Down once. The cursor must
   move to the second information row; in explicit self-test mode that row is
   **Menu input check**.
2. Press B once while at the root. The overlay must close and the title must continue
   without an exception screen.
3. Press `L` + `Select` again. The overlay must reopen and remain navigable; press B
   again to close it.

If Down cannot reach the second row, B does not close the root overlay, or the chord
does not reopen it, stop the acceptance run and retain `platform.log`.

AMUN should remain inert for excluded titles and native titles with no exact pack.
For an admitted title, a successful session parses the pack, checks the live identity,
loads the ledger, and only then starts memory observation. Unknown revisions must show
an unsupported/exact-build message and perform zero profile reads.

For the first loader bring-up with no pack, rename
`/amun/config/self-test.flag.example` to `/amun/config/self-test.flag`, launch one
native `00040000` title, inspect the platform checks, then remove the flag. This
explicit mode performs zero game-memory reads and zero unlocks, tests clock/menu input
and a temporary AMUN-owned ledger, and removes that scratch ledger. Afterward use the
address-free two-stage generator documented in
[`profiles/hardware-self-test/README.md`](../profiles/hardware-self-test/README.md).
It discovers the exact live fingerprint first, then exercises VM/ledger/toast without
declaring a game-memory symbol.

For the current UI-fix retest, complete the Down/B/reopen sequence above, then close
the title normally after the platform checks and require a clean return with no Luma
exception dump. Repeat once before moving to the identity-discovery pack; an on-screen
pass followed by unusable controls or a teardown crash is a failed test.

Unlock durability order is local ledger first, then toast, then any optional external
work. The stable console configuration has networking compiled out, so Wi-Fi and Hub
are not required.

## Installing a pack you built

Validate and compile it on the desktop:

```sh
python3 amun.py profile validate path/to/project
python3 amun.py profile test path/to/project
python3 amun.py profile build path/to/project -o game.amunpack
python3 amun.py pack inspect game.amunpack
```

Copy that file to the exact title directory shown above. The compiler's source build
record must use the identity emitted by the hardware build; a Title ID match alone is
never enough. Keep the source profile, compiler version, pack SHA-256, and research
evidence with the release.

## Logs, ledgers, and failure handling

- Platform diagnostics: `SD:/amun/logs/platform.log`
- Durable per-title ledger: `SD:/amun/ledger/<TITLE-ID>.amunledger`
- Packs: `SD:/amun/packs/<TITLE-ID>/game.amunpack`

Copy a suspect ledger and log off the SD card before changing them. A truncated final
ledger frame should be recovered at the last valid CRC boundary. A corrupt header,
invalid pack, instruction-budget failure, unresolved symbol, or unsupported build
should disable observation and leave the game running whenever the platform permits.
That behavior still needs physical fault-injection evidence.

## Updating, rollback, and removal

Before updating, copy these files somewhere safe:

```text
/luma/plugins/default.3gx
/amun/ledger/
/amun/config/
```

Replace `default.3gx` and packs only while the console is powered off. Preserve the
ledger unless release notes explicitly describe a migration. To roll back, restore
the backed-up plugin and pack together; a pack/runtime version mismatch must fail
closed.

To remove AMUN, power off and remove `/luma/plugins/default.3gx` only if it is AMUN's
file. The `/amun/ledger/` directory contains unlock history; retain it if you might
reinstall. Disable Plugin Loader only if no other title relies on it.

## If the game fails to start

1. Power off, remove AMUN's `default.3gx`, and confirm the game starts without it.
2. Confirm no per-title plugin is shadowing the fallback.
3. Confirm the plugin came from a successful pinned cross-build and passed the 3GX
   magic check.
   If its SHA-256 is retired `e13bab596760e4b8ab594ec0acdecc0e1be1fbecd734b1d53a363f714fc8cc27`
   or `d0dcd7a42704ab3dfe2cd1cf937c9cf9f0679664c261de52d56c4d203c188895`,
   remove it immediately. If it is the superseded
   `d6d72a9f6de19d2897696d3e75be890ce12bc119b37004ea0c145d8542184f09`,
   or retired `dfec2647d030f8b0fe2a997d38f815371eb9d17945d1fba0bda2f78e9dd5c226`,
   replace it with the current fixed build.
4. Reinstall without a pack. The title gate should remain inert.
5. Reinstall the exact pack and collect `platform.log` plus the console/model,
   Luma version, full Title ID, game/update version, and test step.
6. Follow [`hardware-test.md`](hardware-test.md) and stop at the first failing phase.

Never repeatedly relaunch a crashing in-process plugin without first removing it from
the SD card. The next required acceptance run is the current fixed hash on an
original wedge 2DS, because that is AMUN's baseline rather than a later optimization
target.
