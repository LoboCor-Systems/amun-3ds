# AMUN pack 1.0/1.1 implementation note

The Python compiler and C++ runtime share a little-endian, bounds-checked binary
contract. The fixed 40-byte header is `<4sHHIIIHH16s>` and is followed by
`<IIII>` directory records. Required section types are manifest (1), builds (2),
symbols (3), achievements (4), resolver payloads (5), bytecode (6), and a
NUL-prefixed/deduplicated string table (7). Asset records/data (8/9) occur only
as a pair. Directory offsets are absolute; offsets stored in records are relative
to their resolver, bytecode, string, or asset-data section.

The header checksum is CRC-32 over all bytes beginning at `header_size`. The
16-byte profile hash is the first half of SHA-256 over canonical UTF-8 source
JSON (`sort_keys`, no insignificant whitespace). Compilation is deterministic.

Build fingerprints are stored as canonical opaque strings; runtime matching is
exact string equality. Compiler-recognized forms are
`sha256:<lowercase digest>` and
`live-text-crc32-v1:<UPPERCASE size>:<UPPERCASE CRC>`. The latter is byte-for-byte
compatible with the 3DS identity adapter's `%08X` fields.

Records use these exact layouts:

```text
manifest     <QIIIII>                     28 bytes
build        <IIIIIB3x>                   24 bytes
symbol       <IBBBBIiIHBBIHH>             32 bytes
achievement  <IIIIIIIIHBBIIIHHI>          56 bytes
asset        <IBBBxHHIII>                 24 bytes
```

Achievement string offset eight points at comma-joined prerequisite IDs. Symbol
record byte 30 is `value_size`, required only for 1–16-byte `bytes` and
`fixed_string` values. Pattern payloads are `<IIiH2x>` followed by equal-length
pattern and significance-mask bytes. Every bytecode program is verified postfix
ending in `END`, with no jumps or loops. Derived programs are stateless and their
dependencies precede them in the symbol table.

Pack 1.1 adds pointer-chain options only. Symbol flags bit 0 appends
`pointerDepth - 1` u32 XOR masks after the i32 offsets; bit 1 refreshes the chain
at each scheduled sample. Other flags and flags on non-pointer resolvers are
invalid. Depth is bounded to 16 in 1.1, eight in 1.0. Extended flags in a 1.0
header are rejected. Legacy profiles still compile to 1.0 with unchanged bytes.
