# Isolated Mario Kart 7 emulator research

## Installed tool

Portable [Azahar 2126.1.1](https://github.com/azahar-emu/azahar/releases/tag/2126.1.1),
official Windows MSYS2 ZIP, downloaded 2026-09-12. Azahar continues Citra and combines
the PabloMK7 and Lime3DS forks. No system-wide installer or file associations used.

Archive SHA-256 (matched the official release asset digest):
`75565a43a7b182ccf14d85a6c99cb09f40861f8f7920c80fad90fb944b232a85`.

Executable, relative to this repository:
`build/emulators/azahar-2126.1.1/azahar-windows-msys2-2126.1.1/azahar.exe`.
The adjacent `user/` directory selects portable storage. The official
`src/common/file_util.cpp` and `src/common/common_paths.h` at this release confirm
this behavior. Existing AppData emulator saves and the 2DS SD card are untouched.

## Supplied game and region boundary

The research used a decrypted CIA made from the maintainer's own US cartridge
(Title ID `0004000000030800`, title version 2112). This is **not** the console's EUR
title `0004000000030700`, effective version 3152. An emulator address or text
fingerprint must never be silently added to the console profile as a compatible build.

Azahar rejects encrypted CIA imports (`InstallStatus::ErrorEncrypted` in
`src/core/hle/service/am/am.cpp` at 2126.1.1), so the copy was decrypted on the console
first (see "Preparing a decrypted copy" below). No game-memory writes were performed by
research tools. No keys, ROMs, saves, or decrypted game content are committed.

## Successful decrypted import and boot (2026-09-14)

All three TMD content encryption flags of the decrypted copy are clear and the main
content has `NCCH` magic and the NCCH no-crypto flag. The research copy lives in the
ignored `build/emulator-games/` directory.

The official `--install` command imported it into the portable emulator's virtual
SD. All three installed content hashes match the decrypted TMD:

| Content | Bytes | SHA-256 |
| --- | ---: | --- |
| `00000000.app` | 637,521,920 | `0e5febb41711059a5ddee05f680134e77b3dc12945c01326b6a3ebdc4371d407` |
| `00000005.app` | 1,085,440 | `d872e38b9a17f2fe32fe86518cb207dc6a12b504335d4a32b3abf021a86b958f` |
| `00000006.app` | 26,509,312 | `6fae89f2be53d512bd5d8f275098bbf4fa0902a5d091fbeeed32312e1b5ebd46` |

The Windows CLI reports import completion in a modal dialog. Once installation
and hashes were verified, the background installer was terminated; it was not a
running game. The subsequent background game boot logged title
`0004000000030800`, OpenGL on the GTX 1650, and DSP/audio initialization. The game
created its own separate `system0.dat` and `system1.dat` (20,692 bytes each).
The boot log is preserved locally at `build/research/mk7-usa-20260914-boot.log`.
This establishes that game code executed; it is **not visual confirmation of a
race, an achievement unlock, or a graceful exit test**. The background boot test
was terminated after an unanswered close confirmation, then the game was launched
on the user's interactive desktop for visual confirmation.

The user subsequently confirmed the game screen was visible. Later, Azahar was
no longer running. Computer Use reopened the existing emulator and eventually
listed its window, but both the first capture and the fresh-window recovery failed:

`SetIsBorderRequired failed: Interfaz no compatible (0x80004002)`.

No game inputs were sent. Window enumeration working is not proof that screenshot
capture works. The root cause is not established; a new chat may refresh the
connection but is not a proven fix. The user requests agent-driven testing, not
another manual cup run.

### Further Computer Use recovery, September 14–15

The test SD card was subsequently confirmed mounted, and the local decrypted CIA
was present. The same screenshot error remained; inserting the physical SD did
not resolve it. Text-only accessibility capture does work and lists the installed
US Mario Kart 7 title. However, an indexed game-list click failed with
`coordinate input geometry is unavailable`.

On September 15 the existing emulator was reopened through Computer Use. Keyboard
Ctrl+O successfully opened its native Load File dialog. Other navigation attempts
did not reliably change the reported focus. A test `f` filter character was
removed with BackSpace, restoring the game list. Setting the Qt filter's value
failed with `read UIA value read-only state: La propiedad solicitada no estaba en
CacheRequest (0x80070057)`. Setting the native filename field after observing it
failed with `element 227 is not available in cached app state for azahar.exe`.
No successful game-file submission or game screenshot resulted. Azahar's own
screenshot function remains an unproven alternative, not a working workaround.
The Load File dialog may still be open; inspect current state before any action.
These attempts did not write the SD, modify a game save, or validate achievements.

Old3DS mode is selected in this isolated instance. Debug logging is flushed
immediately; automatic emulator updates and Discord presence are disabled for the
pinned research setup. Both RPC and GDB remain off: their upstream listeners bind
all interfaces, so do not describe them as loopback-only or enable them silently.

To reopen the installed game without re-importing it:

```powershell
powershell -NoProfile -File scripts/start-mk7-emulator.ps1
```

All six AMUN CTest suites passed again on September 14. These are native/synthetic
tests, not emulator achievement validation. The 18-goal candidate remains
undeployed and the full 31-goal set is unfinished. The physical SD plugin and pack
still match the accepted coin-fix release. Its log records both `pocket_change`
and `coins_25`; its ledger SHA-256 is
`6861f36c983b58c349a5cf9a1ce66a913c35632f30a04c301f37b6afcffe128a`.

## Read-only save baseline

`build/research/mk7-usa-20260914-before-cup/system0.dat` and `system1.dat`
are identical preserved emulator baselines, with SHA-256
`381f5242fb0162cee1747a960d58c3d9c01973181641c5a3f4eabebb88a03767`.
Both have `SSDC` magic, format version 5, valid CRC-32 `82078D8E`, zero lifetime
coins and 32 zero candidate cup bytes. No completed cup has been captured.

`scripts/mk7_save_research.py` provides `inspect` and `compare` commands. It reads
bounded files twice, checks size/magic/version/CRC, and reports raw changes with
both cup-major and class-major hypotheses. It never edits a save; optional JSON
reports refuse to overwrite existing files. Seven synthetic unit tests pass:

```powershell
python -B -m unittest tests.python.test_mk7_save_research -q
python -B scripts/mk7_save_research.py inspect build/research/mk7-usa-20260914-before-cup/system0.dat
```

These checks establish file integrity and tooling behavior, not trophy semantics.

## Preparing a decrypted copy

Dump and decrypt **your own** cartridge or eShop title as described in the
[community guide](https://3ds.hacks.guide/dumping-titles-and-game-cartridges.html#encrypting-decrypting-a-cia-file).
Do not obtain game files from anywhere else.

## Test plan

1. Use the user's properly dumped/decrypted game, or their own console's supported
   transfer setup. Do not obtain keys or game files from third-party ROM sites.
2. Keep the emulator save separate. Identify the actual loaded process, region,
   update, and text fingerprint before collecting addresses.
3. Validate trophies and star encoding against the visible cup screen, then capture
   one natural cup update. Check cup-major versus class-major ordering explicitly.
4. Capture race start, pause, finish, quit/retry, next race, menu and attract demo.
   Distinguish local play from AI/demo and check fresh-attempt/reset behavior.
5. Capture normal and expert staff ghost headers and legitimate player records.
   Count distinct courses durably; ties and unlocking an expert are not victories.
6. Replay captured **data-only** traces through the native AMUN VM. An emulator pass
   is not evidence of Luma plugin loading, Old2DS memory safety, toast rendering,
   SD durability, or HOME/sleep/exit behavior; those still need the real console.

The bundled emulator scripting API has read and write operations. Research must
use bounded reads only; do not execute its doctest, which writes game memory.
