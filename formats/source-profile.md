# Source profile v1

[`profiles/schema/profile.schema.json`](../profiles/schema/profile.schema.json)
is the machine-readable source contract. Semantic validation additionally checks
unique IDs, prerequisite and derived-symbol cycles, exact scheme-qualified build
fingerprints, VM limits, resolver bounds, referenced icons, asset decode limits,
and local asset paths.

Use `sha256:<64 hex digits>` for an offline SHA-256 identity, or the exact
`live-text-crc32-v1:<8 hex text-size>:<8 hex CRC-32>` string reported by the 3DS
identity adapter. Compilation canonicalizes SHA-256 digits to lowercase and the
live-text size/CRC fields to uppercase, matching the adapter's `%08X` format.
Legacy bare 64-hex strings are rejected because they do not identify the
measurement method.

Source logic is declarative. It supports comparisons, inclusive ranges,
bit tests, current/previous/initial symbol values, change/delta tests, ALL/ANY/NOT,
rising/falling edges, counters, consecutive ticks, latches, durations, cooldowns,
sequences, reset/pause gates, and measured progress. Derived values allow bounded
arithmetic (`add`, `subtract`, `multiply`, `divide`) and bitwise (`bit_and`,
`bit_or`) expressions only. There is no native code, jump, or loop construct.

Pointer chains accept 1-16 signed offsets. Each offset except the last is added
then dereferenced as a little-endian u32. Optional `xorMasks` supplies exactly
one u32 mask per dereference, applied before checking the decoded pointer.
`refresh: true` resolves the chain at every scheduled sample. Missing objects
invalidate data without permanently disabling the symbol; relocation exposes an
invalid sample and clears history/dependent achievement state. Use explicit
attempt/reset gates too: an allocator may reuse an address.

Masks, refresh, or depth above eight require pack 1.1. The compiler still emits
byte-compatible 1.0 packs when none of these features is used. Install a 1.1-capable
plugin with a 1.1 pack; older plugins reject the newer minor version safely.
