# Safe 3DS memory research

Memory research belongs in developer mode. It marks the session non-live and should begin with a
homebrew/synthetic target before a commercial game. AMUN's normal runtime remains read-only.

## Known-value search

Capture a bounded snapshot while the visible value is known, select the correct little-endian
type, and scan for the value. Change it naturally in the game and filter again. Repeat with both
increases and decreases, then include an unchanged step. A candidate that survives one change is
not yet a stable symbol.

Signedness and width matter. The byte sequence for `0x1234` as a 3DS `u16` is `34 12`; a displayed
counter might be `u8`, `u16`, `u32`, a float, fixed-point, packed BCD, or derived from another
value. Search aligned and unaligned candidates deliberately rather than assuming host alignment.

## Unknown-value search

When no number is visible, start from an unknown snapshot and filter `changed`, `unchanged`,
`increased`, `decreased`, or exact delta after controlled actions. Unknown scans can produce
millions of candidates; Studio applies a candidate bound, so narrow the address region/type first.
Bit-changed filtering is useful for Boolean flags and packed completion fields.

## Stability

Restart the title and console, load another save, enter/leave the relevant scene, and repeat on the
same region/update. Heap addresses often move. If the value moves, find a stable pointer chain or a
module-relative root. AMUN caps pointer depth at eight and validates every dereference; prefer a
shorter chain.

Code/data-relative addresses are offsets from the actual executable layout, not from an assumed
desktop dump. Pattern signatures are initialization-time fallbacks. Choose distinctive bytes,
wildcard relocations/addresses, cap the scan range, and require exactly one match. An ambiguous or
missing signature disables the symbol.

## Structures and bitfields

Nearby candidates may be fields of one runtime structure. Change one property at a time and record
snapshots. A value such as `flags & 0x08` should become a bounded derived symbol rather than a
general script. Distinguish runtime state from serialized save state: achievements normally
observe the live representation, which may be cached, transformed, or absent outside a scene.

## Revisions and evidence

Never reuse an address merely because the title ID matches. Region, base/update version, and the
executable fingerprint are part of the profile build. Record the source/provenance, author,
research notes, exact build, test saves, negative cases, and a watched-symbol trace. Replay that
trace in CI, then test a fresh session on physical original-2DS hardware.

Do not publish copyrighted memory dumps, game assets, save data, keys, or third-party achievement
text/art without permission.

