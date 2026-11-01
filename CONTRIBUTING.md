# Contributing to AMUN 3DS

Thanks for helping. AMUN is the engine and the toolbox; the Mario Kart 7 sets are the worked
examples. The goal is for other people to write sets for other games, and to port existing
sets to other regions and versions.

## Ways to contribute

1. **Test and report.** Run a set on your console and file a *Compatibility report* (console
   model, Luma version, game region/version, `platform.log`). This is the most valuable thing
   anyone with a different console can do.
2. **Port a set to another region or version.** Mario Kart 7 USA and JPN need their own
   fingerprints and addresses. Addresses from one build must never be copied to another
   without validating them on that build.
3. **Write a new set** for a game you own (see below).
4. **Improve tools, docs and the plugin.** Bug fixes and tests always welcome.

## Setting up

```sh
./scripts/bootstrap-host.sh      # or scripts\bootstrap-host.ps1 on Windows
./scripts/test.sh                # C++ and Python tests
```

Requirements: Python 3.11+, CMake 3.20+, a C++17 compiler. Building the console plugin
needs the pinned devkitARM toolchain described in [docs/3ds-toolchain.md](docs/3ds-toolchain.md);
you do not need it to write a set.

## Writing a set

1. Copy `profiles/synthetic/` as a structure example and read
   [docs/creating-achievements.md](docs/creating-achievements.md).
2. Find the values you need with Studio's read-only Luma connection
   (`python -m studio <your-profile-dir>`).
3. Keep embedded scenarios in the profile; they are the tests.
4. Validate, test and build:

   ```sh
   python amun.py profile validate profiles/<your-set>
   python amun.py profile test profiles/<your-set>
   python amun.py profile build profiles/<your-set> -o build/<your-set>.amunpack
   ```

5. Put it at `profiles/<game>-<region>[-<name>]/` with a `profile.json` and a `README.md`
   (what it covers, the exact game build, how you verified it).

### Rules for sets

- **License and provenance are required** in the profile. Accepted licenses: CC0, CC-BY,
  MIT. You must have the right to contribute everything in the set.
- **No copied material.** No text, art or audio from other achievement sets (including
  RetroAchievements), from games, wikis or guides. Write your own titles and descriptions.
- **No game data.** Do not commit dumps, saves, keys, firmware or ROMs.
- **Observe only.** A set describes conditions on memory values. AMUN never writes game memory
  and neither may anything in a set or its tooling.
- Use the game's name only to identify it; do not use publisher logos or art.
- Pin the **exact build** (region, version, code fingerprint). Do not claim support for builds
  you have not checked.

### Trust levels

Each set in the [set index](profiles/README.md) carries one of these:

| Level | Meaning |
|---|---|
| **Experimental** | Host-tested scenarios only, or only partly confirmed on hardware |
| **Community** | At least one hardware report for the exact build |
| **Verified** | Hardware report with a ledger excerpt and fingerprint, every goal confirmed to unlock |

Put your evidence in the pull request. A maintainer sets the level when merging.

## Pull requests

- Keep each PR focused. Describe what changed and how you tested it.
- Code changes need tests; the C++ and Python suites must pass.
- Sets must pass `profile validate` and `profile test`; CI checks every profile under
  `profiles/`.
- If you change a profile that has a derived profile (for example the stable Mario Kart 7 set),
  regenerate it and commit the result; a test fails if it is stale.
- Do not include anything that bypasses a console's protections or helps obtain games.

By contributing, you agree that your code is released under the repository's
[MIT license](LICENSE) and that a set you contribute is released under the license declared
in its profile.

## Conduct

Be kind and assume good faith. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
