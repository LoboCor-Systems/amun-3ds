# Source profile format (schema 1)

The normative machine-readable contract is
[`profiles/schema/profile.schema.json`](../profiles/schema/profile.schema.json).
`compiler/profile.py` adds semantic checks that JSON Schema alone cannot express,
including unique IDs, exact fingerprint schemes, dependency cycles, resolver bounds,
referenced assets, and deterministic derived-symbol order.

Profiles are UTF-8 JSON. The root may be a specific file or a directory containing
`profile.json`, `game.json`, or `amun.json`. If none of those exists, a directory is
accepted only when it contains exactly one root JSON file.

## Root object

| Field | Required | Contract |
|---|---:|---|
| `schema` | yes | integer `1` |
| `profile` | yes | authorship, version, license, provenance, integrity |
| `game` | yes | native-3DS identity and one or more supported builds |
| `symbols` | yes | identifier-keyed object, at most 1024 entries |
| `achievements` | yes | 1–500 achievement objects |
| `assets` | no | identifier-keyed object, at most 128 entries |
| `tests` | no | deterministic host scenarios |

Unknown properties are rejected at the root and in normal typed objects. Identifiers
start with an ASCII letter and contain at most 128 characters from letters, digits,
`.`, `_`, and `-`. Strings contain no NUL and occupy at most 1024 UTF-8 bytes.

## Profile metadata

```json
"profile": {
  "version": "1.2.0",
  "license": "CC-BY-4.0",
  "authors": ["Author name"],
  "provenance": "Original logic; addresses established from documented local tests.",
  "integrity": "live_unverified"
}
```

`version`, `license`, `authors`, and `provenance` are required. Integrity is one of:

- `live`: developer mode off and cheat state reliably inactive;
- `live_unverified`: normal observation where cheat state is active or unknown;
- `developer`: scanning, live watches, reloads, or research;
- `imported`: locally imported provenance;
- `save_scan`: explicitly offline save/state inspection.

The runtime must never silently promote unknown cheat state to `live`.

## Game and build identity

```json
"game": {
  "platform": "3ds",
  "titleId": "000400001234ABCD",
  "name": "Example Game",
  "builds": [{
    "id": "eur-v1-update2",
    "region": "EUR",
    "applicationVersion": "1.0.0",
    "updateVersion": "2.0.0",
    "codeFingerprint": "live-text-crc32-v1:00123000:89ABCDEF",
    "compatible": false
  }]
}
```

`titleId` is exactly 16 hexadecimal digits. Supported fingerprint strings are:

```text
sha256:<64 hexadecimal digits>
live-text-crc32-v1:<8-digit text size>:<8-digit CRC-32>
```

The compiler normalizes SHA-256 hex to lowercase and the live-text size/CRC fields to
uppercase. Bare hashes and invented schemes are rejected. Use exactly the scheme and
value emitted by the runtime identity tool used for physical testing. The current
console adapter computes bounded live `.text` CRC identity; SHA-256 is reserved for a
tool/path that actually computes it.

A runtime match requires the full Title ID, nonempty exact fingerprint, and every
nonempty region/version field. `compatible: true` labels a deliberately compatible
record after it matches; it is **not** permission to try a mismatched fingerprint or
revision. Unknown builds perform no profile reads.

## Symbols

```json
"player.hp": {
  "type": "u16",
  "poll": "fast",
  "resolver": {"kind": "module_relative", "offset": "0x00014230"}
}
```

Types are little-endian `bit`, `bool`, `u8`, `s8`, `u16`, `s16`, `u32`, `s32`,
`f32`, `bytes`, and `fixed_string`. `bytes` and `fixed_string` require `size` from
1 through 16; other types forbid it. `bit` accepts `bitIndex` 0–7. Polling is `fast`,
`normal` (default), `slow`, or `static`.

Addresses and offsets accept JSON integers or decimal/`0x` strings. Address arithmetic
is bounded to the 32-bit 3DS address space.

### Absolute

```json
{"kind": "absolute", "address": "0x08123456"}
```

The complete value range must be readable at session initialization.

### Module relative

```json
{"kind": "module_relative", "offset": "0x14230"}
```

The signed offset is added to the runtime's verified main-module base.

### Pointer chain

```json
{
  "kind": "pointer_chain",
  "moduleOffset": "0x1234",
  "offsets": [0, 32, 8]
}
```

Use exactly one base, either `address` or `moduleOffset`, and 1–8 signed offsets. For
each offset the runtime adds it; after every offset except the final one, it reads a
little-endian 32-bit pointer. Each add, dereference, null pointer, and final value range
is checked. The final offset selects the value field and is not dereferenced.

Pack 1.1 extends the limit to 16 offsets and adds optional `xorMasks` (one u32
mask per dereference) and `refresh: true` (resolve again at each scheduled poll).
Masks decode pointers before null/range validation. A missing or relocated
object invalidates samples and clears dependent state; address reuse still needs
explicit race/attempt reset conditions. These features require an updated plugin.

### Pattern

```json
{
  "kind": "pattern",
  "scanStart": "0x00100000",
  "scanSize": "0x00040000",
  "resultOffset": 12,
  "pattern": "E3 A0 ?? ?? E5 9F 00 04"
}
```

Patterns contain 1–128 space-separated bytes. `?`, `??`, and `**` are wildcards.
The bounded scan runs at initialization, not every tick, and must find exactly one
match; zero or multiple matches disable the symbol. `resultOffset` is a signed offset
from the match.

### Derived

```json
{
  "kind": "derived",
  "expression": {
    "op": "divide",
    "left": {
      "op": "multiply",
      "left": {"symbol": "player.hp"},
      "right": 100
    },
    "right": {"symbol": "player.max_hp"}
  }
}
```

Derived expressions are stateless bytecode using constants, symbol current/previous/
initial values, `add`, `subtract`, `multiply`, `divide`, `bit_and`, and `bit_or`.
Aliases `+`, `-`, `*`, and `/` are accepted. Dependencies are topologically ordered;
self references and cycles are rejected. There are no calls, variables, jumps, loops,
or native code. Division by zero and non-finite arithmetic fail the evaluation.

## Achievements

| Field | Required | Notes |
|---|---:|---|
| `id` | yes | stable unique identifier |
| `title`, `description` | yes | hidden by UI before a secret unlock |
| `points` | yes | integer 0–10000 |
| `trigger` | yes | one condition object or Boolean |
| `icon`, `author`, `category` | no | free metadata; icon references an asset name |
| `secret`, `missable` | no | default false; packed as metadata flags |
| `tags` | no | string or string array |
| `prerequisites` | no | unique achievement IDs; cycles rejected |
| `prerequisiteMinCount` | no | 0 (default) = all prerequisites required; otherwise minimum number that must be unlocked |
| `imported` | no | importer provenance retained for review |

Categories and tags are community-defined strings, not a closed enum. Achievement IDs
must remain stable across profile releases because the ledger uses them as durable
keys. Prerequisites affect eligibility; they are not textual dependencies.
An achievement whose entire trigger is literal `true` is rejected as an unconditional
unlock; the address-free hardware self-test uses a bounded duration over `true`.

Triggers are documented in [`condition-language.md`](condition-language.md). The
compiler verifies no more than 32 source nesting levels, stack depth 64, 256 state
slots, 2048 instructions per program, and 256 KiB total bytecode section.

## Assets

```json
"icon.boss": {
  "kind": "icon",
  "format": "rgb565",
  "compression": "byte_rle",
  "width": 32,
  "height": 32,
  "file": "assets/boss.rgb565"
}
```

Kinds are `icon` and `sound`. Formats are `rgb565`, `rgba5551`, and `pcm_u8`;
compression is `none` or `byte_rle`. Provide exactly one of a project-relative regular
`file` or inline `data` (hex bytes or a byte array). The resolved path may not escape
the project, and the selected file itself may not be a symlink. Icons require width/height 1–64 and exactly two decoded bytes
per pixel.

Each decoded asset is at most 32 KiB; all decoded assets at most 512 KiB; stored asset
data at most 256 KiB. These are parser ceilings, not recommended Old2DS budgets.

## Embedded scenarios

```json
"tests": [{
  "name": "boss transition",
  "frames": [
    {"timeMs": 0, "values": {"boss.hp": 20}},
    {"timeMs": 100, "values": {"boss.hp": 0}}
  ],
  "expectUnlocked": ["first_boss"],
  "expectLocked": ["no_damage"],
  "expectProgress": {"collector": 3}
}]
```

Frames retain unspecified symbol values from the preceding frame. `timeMs` is
monotonic scenario time. Every stateful rule should have an explicit initialization
frame plus positive and negative scenarios. Run them with:

```sh
python3 amun.py profile test path/to/project
python3 amun.py sim run path/to/project --json
```

## Determinism and provenance

Compilation canonicalizes the complete JSON object with sorted keys and no
insignificant whitespace, then stores the first 16 bytes of its SHA-256 as the profile
hash. Symbol dependencies, assets, strings, and sections use deterministic ordering.
Asset file contents are build inputs even though the canonical profile hash describes
the source JSON; retain the final pack SHA-256 as the complete binary identity.
