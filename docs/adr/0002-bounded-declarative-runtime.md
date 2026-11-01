# ADR 0002: Bounded declarative runtime and ledger-first unlocks

- Status: Accepted and implemented in the portable core
- Date: 2026-08-25
- Hardware baseline: original Nintendo 2DS / Old3DS class
- Physical verification: pending

## Context

AMUN runs in the same process as a native game. A malformed community pack, invalid
address, allocation spike, unbounded rule, or synchronous SD/network path can damage
the player experience more severely than an ordinary desktop tool failure. Source JSON
is useful for authors but is expensive and too permissive as an in-game format.

Achievement correctness also spans restarts. A toast shown before durable state is not
an unlock; a network acknowledgement is not a local source of truth.

## Decision

### Portable injected core

The C++17 runtime accepts an `AchievementPack`, `GameIdentity`, `MemoryReader`,
`Ledger`, `Clock`, and `EventSink`. It has no direct 3DS API and never dereferences a
profile address. Desktop synthetic/replay readers and the console reader implement the
same read-only boundary. No game-memory writer interface exists in the runtime or pack.

### Compile source before gameplay

Human JSON is validated and compiled on the desktop into versioned little-endian
`.amunpack` sections. The compiler canonicalizes source, orders derived dependencies,
deduplicates strings, and emits compact postfix programs. The runtime performs a
second independent parse and bytecode verification; it never trusts compiler-declared
stack/budget values without checking them.

The VM has no jumps, loops, native calls, or arbitrary data access. Program size,
instruction count, stack, state slots, source nesting, symbol/achievement/asset counts,
pointer depth, signature length, and decoded assets are bounded. A global tick budget
disables a profile that is collectively too expensive.

### Fail closed on identity and resolution

The full 64-bit Title ID and explicit fingerprint scheme must match a declared build.
An unknown fingerprint causes zero profile reads. Address addition, every pointer
dereference, complete value span, and signature cardinality are validated. A repeatedly
failing symbol/achievement is disabled with a warning rather than retried without a
bound.

### One read plan

Symbols are resolved once and cached. Each due symbol is sampled at most once per tick
for all dependent achievements. Static/slow/normal/fast polling separates correctness
needs. Derived symbols consume cached values and are topologically evaluated without a
game-memory read. The VM uses a fixed stack during each evaluation.

### Ledger before presentation

For a new unlock, runtime order is:

```text
verified condition
→ append CRC-framed event to local ledger
→ mark runtime state unlocked
→ enqueue toast/event sink
→ optional external synchronization later
```

If ledger append fails, no success toast is emitted. Event UUIDs and achievement IDs
provide duplicate suppression. The journal recovers a torn final frame at the last
valid CRC boundary and compaction replaces it atomically on supported storage adapters.
Progress checkpoints are throttled; session/timed logic uses an injected monotonic
clock while wall time is provenance only.

### Offline stable path

Hub is not a gameplay dependency. Console networking is compiled out until its memory,
timeout, lifecycle, and original-2DS behavior are demonstrated. Lifecycle callbacks
pause sampling first and bound storage flush work; they never perform networking.

## Consequences

- Profiles cannot express arbitrary scripts or writes. New logic requires a reviewed,
  bounded opcode and verifier/runtime/compiler tests.
- Exact build onboarding costs more research but prevents silent address reuse.
- Parser ceilings are security limits, not recommended content budgets; profiles still
  need original-2DS performance evidence.
- Pattern scanning allocates/works at initialization and is unsuitable as a per-frame
  fallback.
- CRC/profile hashes provide integrity diagnostics, not signatures or anti-cheat proof.
- The host vertical slice can validate detection, durability, restart, and duplicate
  behavior, but only physical hardware can validate 3GX injection, memory mapping,
  renderer hooks, Luma swap, SD timing, and title compatibility.
