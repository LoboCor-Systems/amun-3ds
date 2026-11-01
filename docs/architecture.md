# AMUN architecture

AMUN is an offline-first achievement observer for native Nintendo 3DS-mode software. The
original Nintendo 2DS is the reference performance class. The portable core contains no
Nintendo SDK code and never dereferences game addresses directly.

## Runtime data flow

```text
source profile JSON
  -> host validator/compiler
  -> bounded, checksummed .amunpack
  -> exact title/build match
  -> one-time address resolution
  -> deduplicated polling plan
  -> current/previous/initial symbol cache
  -> verified loop-free VM
  -> append durable ledger event
  -> toast/event sink
  -> optional nonblocking Hub queue
```

Durable local storage precedes notification and networking. A failed ledger append leaves the
achievement eligible for a later retry; it does not produce a toast claiming a durable unlock.

## Products

- `amun_core` is conservative C++17 shared by host tools and the console adapter. It owns pack
  parsing, resolvers, symbol history, the condition VM, sessions, progress, ledger framing,
  tracing, and achievement state.
- `AMUN.3gx` is the thin Luma/CTRPF adapter. It supplies safe current-process reads, title/build
  identity, monotonic time, absolute SD paths, lifecycle callbacks, and UI events.
- `amun` is the source validator, deterministic compiler, pack inspector, trace/dump tooling,
  simulator front end, and optional local RA-style importer.
- AMUN Studio is a Windows-first Tkinter application for project editing, offline snapshots,
  iterative memory filtering, compilation, and transactional SD deployment.
- AMUN Hub is optional. It accepts paired LAN events and backups; gameplay never depends on it.

## Trust boundaries

Profiles, packs, traces, ledgers, assets, and network frames are untrusted. Their parsers enforce
file sizes, section bounds, counts, string lengths, VM stack and instruction budgets, pointer
depth, signature size, asset expansion, and CRCs before use.

`MemoryReader` is the only game-memory boundary. The console implementation queries current
memory mappings and verifies that an entire requested span is readable before copying it. AMUN
does not expose a game-memory write operation. Source profiles contain declarative operations;
there is no native-code or general-script payload.

## Build identity

The full 64-bit title ID gates pack discovery. A build entry must also match its region,
application/update version metadata, and executable fingerprint. A recognized title with an
unknown fingerprint enters `UNKNOWN_BUILD` and performs no profile-driven reads. Compatibility
entries are explicit; AMUN never guesses that addresses from another revision are safe.

## Failure containment

- An unsupported title leaves the universal plugin inert.
- One unresolved/failing symbol disables dependent evaluation rather than reading an unchecked
  address. Repeated read failures disable that symbol and emit a bounded warning.
- Invalid bytecode is rejected at pack load. A runtime achievement-budget failure disables the
  profile; no unbounded loop or arbitrary jump exists in the VM.
- A malformed final ledger record is ignored. The next append truncates only the invalid tail.
- Network, sound, custom icons, Studio, and Hub are optional subsystems.

## Explicit non-goals

AMUN v1 does not target TWL/DS mode, DSiWare in TWL mode, AGB/GBA mode, `open_agb_firm`, Wii, or
emulator-only execution. It does not grant items, patch gameplay, provide cheats, scrape an
achievement service, or claim cryptographic proof against the console owner.

