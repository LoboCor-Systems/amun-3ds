# Achievement sets

Every folder here with a `profile.json` is a set. CI validates and tests all of them.
How to write one: [docs/creating-achievements.md](../docs/creating-achievements.md).
How to contribute one: [CONTRIBUTING.md](../CONTRIBUTING.md). Trust levels are defined there.

| Set | Game / build | Goals | Level | Notes |
|---|---|---|---|---|
| [`mario-kart-7-eur`](mario-kart-7-eur/profile.json) | Mario Kart 7 EUR, build 3152 | 18 (5 coins, 13 cups; 190 pts) | **Community** | The demo set. Coin goals hardware-tested; cup table layout hardware-confirmed. Derived from the progression set by `scripts/make_mk7_stable_profile.py` |
| [`mario-kart-7-eur-progression`](mario-kart-7-eur-progression/RESEARCH.md) | Mario Kart 7 EUR, build 3152 | 31 scored + 64 hidden ledger entries (345 pts) | **Experimental** | Superset of the stable set plus race, ghost and Time Trial goals that still rely on unconfirmed live fields. Research notes included |
| [`mario-kart-7-eur-coins`](mario-kart-7-eur-coins/README.md) | Mario Kart 7 EUR, build 3152 | 5 (35 pts) | **Verified** (superseded) | The first accepted release; its five goals are included unchanged in the stable set |
| [`mario-kart-7-eur-rev2`](mario-kart-7-eur-rev2/README.md) | Mario Kart 7 EUR, build 2112 | 1 | Historical | Original one-goal probe and the [31-goal design](mario-kart-7-eur-rev2/SET-DESIGN.md) |
| [`synthetic`](synthetic/profile.json) | none (test fixture) | 14 | Example | Fully synthetic; exercises every condition feature. Start here when writing a set |
| [`hardware-self-test`](hardware-self-test/README.md) | any native title | generated | Tool | Address-free platform check for a new console/game |

Sets for other regions and games: see "Ways to contribute" in
[CONTRIBUTING.md](../CONTRIBUTING.md).

## Conventions

- Folder name: `<game>-<region>[-<variant>]`, lower-case, hyphen-separated.
- Each set has a `README.md` stating the exact build it targets and how it was verified.
- The `profile.license` and `profile.provenance` fields are required.
