# Creating achievements

An AMUN project is a human-readable JSON source profile plus optional small assets and
embedded deterministic scenarios. The compiler validates it and emits one bounded
`.amunpack`; the console never evaluates source JSON.

Start with the fully synthetic project in `profiles/synthetic/`. It contains no
commercial-game address or asset and exercises exact comparisons, byte strings,
derived values, edge detection, reset, progress, prerequisites, secrets, and sequence.

```sh
python3 amun.py profile validate profiles/synthetic
python3 amun.py profile test profiles/synthetic
python3 amun.py profile build profiles/synthetic -o build/synthetic.amunpack
python3 amun.py pack inspect build/synthetic.amunpack --disassemble
```

## First real-game workflow

1. Make a project directory and copy the synthetic profile as a structural example.
2. Record the full 16-digit Title ID, region, application/update versions, and the
   executable fingerprint reported by the same hardware/runtime build that will load
   the pack.
3. Launch the game without developer cheats or patches that change its executable.
4. Connect Studio's direct Luma RSP backend, or capture bounded read-only dumps by
   another legal method. Studio obtains exact PIDs from Luma and intentionally exposes
   no memory-write command; external GDB/MI remains an optional fallback.
5. Search for a value you can observe in the game.
6. Change that state through normal gameplay and filter candidates.
7. Repeat with increased, decreased, changed, and unchanged steps as appropriate.
8. Restart the game and console, use another save, and retest the candidate.
9. Prefer a stable module-relative root or short validated pointer chain over a heap
   address that happened to work once.
10. Use an initialization-time signature only when its bounded region has exactly one
    match on every declared build.
11. Name the symbol by meaning (`player.hp`), choose its exact little-endian type, and
    select the slowest polling class that preserves correctness.
12. Add one achievement with clear metadata, provenance, and a declarative trigger.
13. Use Studio's condition debugger to inspect bytecode, operands, edge state, counters,
    and progress on controlled frames.
14. Record or construct a trace/scenario containing a positive case, negative case,
    initialization frame, and restart-sensitive state.
15. Add `expectUnlocked`, `expectLocked`, and `expectProgress` assertions.
16. Run validation and every embedded scenario.
17. Compile twice and compare hashes to catch accidental nondeterminism.
18. Inspect the pack and retain its SHA-256 beside the source revision.
19. Deploy it as `/amun/packs/<FULL-TITLE-ID>/game.amunpack` without modifying unrelated
    SD files.
20. Run the staged physical checklist on an original wedge 2DS before calling the
    profile supported.

See [`memory-research.md`](memory-research.md) for the scanning discipline and
[`hardware-test.md`](hardware-test.md) for the physical evidence form.

## Minimal source

This is structural only. The address and fingerprint are deliberately non-real and
must not be copied into a game profile.

```json
{
  "schema": 1,
  "profile": {
    "version": "0.1.0",
    "license": "CC0-1.0",
    "authors": ["Example author"],
    "provenance": "Original achievement text; symbol established from documented local tests.",
    "integrity": "live_unverified"
  },
  "game": {
    "platform": "3ds",
    "titleId": "0004000000000000",
    "name": "Example Game",
    "builds": [{
      "id": "example-eur-v1",
      "region": "EUR",
      "applicationVersion": "1.0.0",
      "updateVersion": "0",
      "codeFingerprint": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
      "compatible": false
    }]
  },
  "symbols": {
    "boss.hp": {
      "type": "u16",
      "poll": "fast",
      "resolver": {"kind": "absolute", "address": "0x08000000"}
    }
  },
  "achievements": [{
    "id": "first_boss",
    "title": "An Old Score",
    "description": "Defeat the first boss.",
    "points": 5,
    "author": "Example author",
    "category": "combat",
    "secret": false,
    "missable": false,
    "prerequisites": [],
    "trigger": {
      "op": "falling",
      "condition": {"op": "gt", "symbol": "boss.hp", "value": 0}
    }
  }],
  "tests": []
}
```

The example trigger demonstrates syntax, not a recommended boss rule: a robust rule
usually also establishes encounter identity, player survival, and initialization
behavior. Edge conditions prime on their first evaluation, so loading a save where the
boss is already at zero cannot generate a synthetic transition.

## Design a low-cost read plan

Symbols are sampled once per due polling class and shared by all dependent
achievements. Choose deliberately:

| Poll class | Use |
|---|---|
| `fast` | Brief transitions that normal polling could miss |
| `normal` | Ordinary health, counters, encounter state |
| `slow` | Stable menus, chapter, inventory totals |
| `static` | Values expected not to move after session resolution |

Rates are selected by runtime performance mode; a profile does not encode a guessed
frame rate. Avoid making every symbol fast. Derived symbols are evaluated after their
dependencies and do not trigger another game-memory read.

## Conditions and state

Use simple comparisons for persistent facts and an event operation for transitions.
For example:

```json
{
  "op": "reset_if",
  "condition": {
    "op": "rising",
    "condition": {
      "all": [
        {"op": "eq", "symbol": "boss.hp", "value": 0},
        {"op": "gt", "symbol": "player.hp", "value": 0}
      ]
    }
  },
  "reset": {"op": "increased", "symbol": "healing.used"}
}
```

Always include an initialization frame in tests. Previous/initial values, rising and
falling edges, hit counts, sequences, duration, cooldown, latch, pause, and reset all
have session state. Timed conditions use injected monotonic time, not the editable wall
clock. Full syntax and priming behavior are in
[`condition-language.md`](condition-language.md).

## Progress, prerequisites, and secrets

Measured progress is a trigger, not a disk write on every poll:

```json
{"op": "set_progress", "symbol": "collectibles.count", "target": 50}
```

The runtime clamps progress to `0..target`, persists meaningful increases, and unlocks
at the target. Prerequisites refer to earlier achievement IDs and are cycle-checked.
Before a secret unlock, UI should expose neither its real title/description nor ID;
after unlock the normal metadata is available. Completion percentage is based on
achievement count, while points are reported separately.

## Assets and rights

V1 assets are deliberately small and bounded: RGB565/RGBA5551 icons and unsigned
8-bit PCM sound data, optionally byte-RLE encoded. Keep decoded-size cost in the
Old2DS budget. Do not copy art or audio from a game, guide, website, or another
achievement service unless its license permits redistribution. Record the source and
license in profile provenance.

## Review checklist

- Exact build identity, not only Title ID.
- Every symbol survives restart, another save, and negative cases.
- Pointer/signature failure disables the symbol rather than trying a nearby address.
- Conditions have an initialization frame and cannot unlock from uninitialized history.
- Achievement IDs and prerequisites are stable; metadata and assets are licensed.
- Embedded tests cover unlock, non-unlock, progress, and relevant reset/pause paths.
- The pack builds deterministically and passes independent inspection.
- Fast polling is justified and benchmarked.
- Physical testing uses an original wedge 2DS and records Luma/game/update details.
