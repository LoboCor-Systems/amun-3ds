# Compiled `.amunpack` format 1.0/1.1

This document describes the little-endian binary contract shared by
`compiler/pack.py` and `core/src/pack.cpp`. The compact normative record summary is
also kept in [`formats/pack-format.md`](../formats/pack-format.md). Parsers must treat
every pack as untrusted even if it was produced locally.

All multibyte integers and `f32` values are little-endian. There is no host-pointer,
native-structure, or platform-alignment dependency.

## File header

The fixed 40-byte header is Python/C notation `<4sHHIIIHH16s>`:

| Offset | Type | Field | Rule |
|---:|---|---|---|
| 0 | `char[4]` | magic | ASCII `AMUN` |
| 4 | `u16` | major | `1` |
| 6 | `u16` | minor | `0` or `1`; reject unsupported minors |
| 8 | `u32` | total size | exactly the input byte length; at most 2 MiB |
| 12 | `u32` | payload CRC-32 | CRC-32 of every byte from `headerSize` to EOF |
| 16 | `u32` | flags | bit 0 means asset sections are present; other bits reserved |
| 20 | `u16` | section count | 1–16 |
| 22 | `u16` | header size | `40 + sectionCount * 16` |
| 24 | `u8[16]` | profile hash | first 16 bytes of SHA-256 over canonical source JSON |

The CRC protects the section payload, not the fixed header/directory. Release SHA-256
is the identity of the entire pack and should be retained separately. The truncated
profile hash is an event/provenance key, not a signature or authenticity proof.

## Section directory

Immediately after the header are `sectionCount` 16-byte `<IIII>` records:

```text
u32 sectionType
u32 absoluteFileOffset
u32 byteSize
u32 logicalRecordCount
```

Sections may occur in directory order but readers do not infer offsets from that
order. Every range must begin at or after `headerSize`, remain inside the declared
file, and not overlap another nonempty range. Duplicate types are rejected.

| Type | Name | Required | Count meaning |
|---:|---|:---:|---|
| 1 | manifest | yes | exactly 1 |
| 2 | builds | yes | build records |
| 3 | symbols | yes | symbol records |
| 4 | achievements | yes | achievement records |
| 5 | resolver payloads | yes | pointer/pattern payload count |
| 6 | bytecode | yes | derived plus achievement programs |
| 7 | strings | yes | deduplicated strings including empty string |
| 8 | assets | paired | asset records |
| 9 | asset data | paired | asset payload count |

Types 8 and 9 must either both be absent or both be present.

## Strings and offsets

The string section begins with NUL, so offset 0 is the empty string. Other strings are
deduplicated UTF-8 followed by NUL. A string offset is relative to the start of section
7, must reference a complete UTF-8 string, and must encounter NUL within 1024 bytes.
Embedded NUL is impossible.

Resolver, bytecode, and asset-data offsets in records are likewise relative to their
own section. Only section-directory offsets are absolute file offsets.

## Manifest record

One 28-byte `<QIIIII>` record:

| Field | Type |
|---|---|
| full Title ID | `u64` |
| game name string offset | `u32` |
| profile version string offset | `u32` |
| profile license string offset | `u32` |
| provenance string offset | `u32` |
| reserved, zero | `u32` |

The runtime checks this full Title ID again after the exact-title SD path gate.

## Build record

Each build is 24 bytes, `<IIIIIB3x>`:

| Field | Type |
|---|---|
| build ID, region, application version, update version, fingerprint offsets | five `u32` |
| flags | `u8`; bit 0 = compatible classification |
| padding | three zero bytes |

The fingerprint is a normalized explicit scheme string. Empty region/version fields
may be used deliberately, but the fingerprint is nonempty and must match exactly.

## Symbol record

Each symbol is 32 bytes, `<IBBBBIiIHBBIHH>`:

| Field | Type | Meaning |
|---|---|---|
| name offset | `u32` | nonempty unique symbol ID |
| value type | `u8` | enum below |
| poll class | `u8` | enum below |
| resolver kind | `u8` | enum below |
| flags | `u8` | pointer-only: bit 0 XOR masks, bit 1 refresh; requires 1.1 |
| address | `u32` | absolute/pointer base, otherwise zero |
| module offset | `i32` | module-relative/pointer base |
| resolver offset | `u32` | relative to section 5 |
| resolver size | `u16` | bounded payload length |
| pointer depth | `u8` | 1–8 in 1.0; 1–16 in 1.1; pointer chains only |
| bit index | `u8` | 0–7 for `bit` |
| derived offset | `u32` | relative to section 6 |
| derived size | `u16` | stateless verified program |
| value size | `u16` | 1–16 only for bytes/fixed string |

Value type enum: `0 bit`, `1 bool`, `2 u8`, `3 s8`, `4 u16`, `5 s16`,
`6 u32`, `7 s32`, `8 f32`, `9 bytes`, `10 fixed_string`.

Poll class enum: `0 fast`, `1 normal`, `2 slow`, `3 static`.

Resolver enum: `0 absolute`, `1 module_relative`, `2 pointer_chain`, `3 pattern`,
`4 derived`.

### Resolver payloads

- Absolute and module-relative symbols have no resolver payload.
- Pointer chains store `pointerDepth` signed little-endian `i32` offsets.
  Pack 1.0 permits at most eight; 1.1 permits at most sixteen. With flag bit 0,
  append exactly `pointerDepth - 1` little-endian u32 XOR masks, applied after
  each dereference. The last offset addresses the value and is not dereferenced.
  Flag bit 1 re-resolves the chain at each scheduled poll. Missing/relocated
  objects invalidate samples and break dependent state/history. Unknown flags,
  flags on another resolver kind, and extended options in 1.0 are rejected.
- A pattern payload starts with `<IIiH2x>`: scan start, scan size, result offset,
  pattern length, two zero padding bytes. It is followed by `length` pattern bytes and
  `length` significance bytes (`0` wildcard, nonzero significant).
- Derived symbols point to their stateless expression program in section 6 and have no
  resolver-section payload.

Derived dependencies are ordered before consumers. A parser re-verifies the bytecode
and rejects state slots in a derived program.

## Achievement record

Each achievement is 56 bytes, `<IIIIIIIIHBBIIIHHI>`:

| Field | Type |
|---|---|
| ID, title, description, author, category, tags, icon, prerequisites offsets | eight `u32` |
| points | `u16` |
| metadata flags | `u8`: bit 0 secret, bit 1 missable |
| reserved / prerequisiteMinCount | `u8`; 0 = all prerequisites required, else minimum unlock count among listed prerequisites |
| progress target | `u32`, zero for non-measured |
| bytecode offset | `u32`, relative to section 6 |
| bytecode size | `u32` |
| declared maximum stack | `u16` |
| declared state slots | `u16` |
| instruction budget | `u32` |

Tags and prerequisites are comma-joined source IDs in their string entries. Source
validation forbids prerequisite cycles and commas in identifiers. The independent VM
verifier must agree with the declared stack, state-slot, and instruction values.

## Asset record

When present, each asset is 24 bytes, `<IBBBxHHIII>`:

| Field | Type |
|---|---|
| name offset | `u32` |
| kind | `u8`: 1 icon, 2 sound |
| format | `u8`: 1 RGB565, 2 RGBA5551, 3 PCM u8 |
| compression | `u8`: 0 none, 1 byte RLE |
| padding | one byte |
| width, height | two `u16` |
| data offset | `u32`, relative to section 9 |
| stored size | `u32` |
| decoded size | `u32` |

Byte RLE consists of `(u8 count, u8 value)` pairs. Count zero, odd stored length,
decoded overrun, or final decoded-size mismatch is invalid. Each decoded asset is at
most 32 KiB, total decoded data 512 KiB, and stored asset data 256 KiB.

## VM bytecode

Programs are postfix stack bytecode with no branch, jump, or loop opcode. Operands:

| Opcode | Byte | Operand |
|---|---:|---|
| `LOAD_CURRENT`, `LOAD_PREVIOUS`, `LOAD_INITIAL` | `01`–`03` | `u16 symbol` |
| `CONST_I64` | `04` | `i64` |
| `CONST_F32` | `05` | `f32` |
| `CONST_BYTES` | `06` | `u8 length`, then 1–16 bytes |
| `EQ NE LT LE GT GE` | `10`–`15` | none |
| `BETWEEN BIT_SET BIT_CLEAR MASKED_EQUALS` | `16`–`19` | none |
| `ADD SUBTRACT MULTIPLY DIVIDE BIT_AND BIT_OR` | `1A`–`1F` | none |
| `CHANGED UNCHANGED INCREASED DECREASED` | `20`–`23` | `u16 symbol` |
| `INCREASED_BY DECREASED_BY` | `24`–`25` | `u16 symbol`, `i64 amount` |
| `ALL ANY` | `30`–`31` | `u8 child count` |
| `NOT` | `32` | none |
| `RISING FALLING LATCH` | `40`, `41`, `44` | `u16 state slot` |
| `HIT_COUNT CONSECUTIVE` | `42`–`43` | `u16 slot`, `u16 target` |
| `DURATION COOLDOWN` | `45`–`46` | `u16 slot`, `u32 milliseconds` |
| `SEQUENCE` | `47` | `u16 slot`, `u8 stage count` |
| `RESET_IF PAUSE_IF` | `48`–`49` | none |
| `SET_PROGRESS` | `4A` | `u32 target` |
| `END` | `FF` | none; exactly one final stack value |

Verification walks the entire program linearly, bounds every operand and symbol/slot,
proves stack effects, permits at most 64 stack entries and 256 state slots, and
requires `END` to be the final instruction. The per-achievement ceiling is 2048
instructions; the runtime also applies a global per-tick budget and disables the
profile if it is exceeded.

## Parser rejection checklist

A safe reader rejects, before runtime use: short/oversized files, wrong magic or
version, total-size mismatch, CRC mismatch, malformed/overlapping directories,
missing sections, bad record counts, invalid or unterminated UTF-8 strings, unknown
record enums, out-of-range resolver and bytecode slices, pointer depth over the version limit, signature
over 128 bytes, invalid bytecode accounting, achievement/symbol/asset limits, malformed
RLE, and asset decoded-size overflow.

Inspect a candidate with the independent host parser:

```sh
python3 amun.py pack inspect game.amunpack --disassemble
```

Inspection is necessary but not sufficient: console admission still requires the
running full Title ID and exact live build identity.
