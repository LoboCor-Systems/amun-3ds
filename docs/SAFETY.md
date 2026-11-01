# Safety, risk and recovery

AMUN is preview software for modified consoles. Read this before you install it.

## Online play and bans

- Running custom firmware and plugins on a console can lead Nintendo to restrict that
  console's access to its online services. We cannot tell you where the line is, and AMUN
  has **never been tested online**.
- AMUN is observer-only: it reads game memory, never writes it, and has no networking in the
  console build. That reduces, but does not remove, the fact that a plugin is loaded.
- **Recommendation: play offline** (switch the console's wireless off) while
  AMUN is installed, and do not use it in online or ranked modes.
- You use AMUN at your own risk. The MIT license provides no warranty.

## What AMUN touches on your SD card

| Path | Purpose |
|---|---|
| `/luma/plugins/default.3gx` | The plugin. Luma loads **one** default plugin per game, so this replaces any other default plugin (for example a cheat plugin). A plugin in `/luma/plugins/<TitleID>/` takes priority for that game |
| `/amun/packs/<TitleID>/game.amunpack` | The achievement set for one exact game |
| `/amun/ledger/<TitleID>.amunledger` | **Your unlocks.** Append-only journal |
| `/amun/logs/platform.log` | Diagnostic log; safe to delete |
| `/amun/config/` | Optional flags (a disabled self-test example) |

AMUN never edits game saves, the game's files, or Luma's configuration.

## Back up your progress

Copy the `/amun/ledger/` folder somewhere safe now and then. Do not delete a ledger by hand;
it is the only record of your unlocks. If the ledger ever becomes full or damaged, copy it
aside and report it instead of removing it.

## If a game crashes or runs slowly

1. Delete `/luma/plugins/default.3gx` (or rename it) to run the game without AMUN. Restore a
   previous plugin if you had one.
2. Send the maintainers `/amun/logs/platform.log` with your console model, Luma version, and
   the game's region and version. Lines starting `perf:` show how long AMUN's checks took.
3. If you installed the experimental set, try the stable set first: on a PC benchmark it does
   under a third of the memory reads and about a sixth of the achievement evaluations.

## What AMUN will not do

- It does not work on games without a matching set, or on a different build of a supported
  game: the pack is bound to the exact title and executable fingerprint, and AMUN stays inert
  otherwise.
- It does not help you obtain games or hack a console, and the project hosts no game data,
  keys or firmware. Use legally owned copies.

## Reporting a security problem

Do not open a public issue. Follow [SECURITY.md](../SECURITY.md).
