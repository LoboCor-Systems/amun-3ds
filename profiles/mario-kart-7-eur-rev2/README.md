# Mario Kart 7 EUR Rev2 research profile

Historical one-achievement profile. The newer
[five-coin preview](../mario-kart-7-eur-coins/README.md) includes independently checked
3152 identity evidence and needs the startup-recovery plugin built on 2026-09-10.

This hardware-candidate profile is marked `live_unverified`. Its one symbol observes
the lifetime coin total on the exact original-2DS build identified by:

- Title ID: `0004000000030700`
- effective application version: `2112`
- fingerprint: `live-text-crc32-v1:004EC000:04F718AE`
- address/type: `0x1413C540`, little-endian `u32`
- observed transition: `0` before a single-player 50cc Grand Prix to `6` after it
- visible cross-check: Mario Kart Channel displayed a lifetime total of `6`

The layout was cross-referenced with the archived
[`CTRPF-AR-CHEAT-CODES` Mario Kart 7 EUR table](https://github.com/JourneyOver/CTRPF-AR-CHEAT-CODES/blob/master/Cheats/Mario%20Kart%207%20%28EUR%29/0004000000030700.txt).
The local observations used Luma GDB and AMUN's read-only native RSP fallback; neither
client implements a game-memory write operation.

Do not call the profile fully supported until the game and console have been restarted
and another save has been checked. The embedded scenarios test trigger semantics; the
physical observation above establishes the address only for the named build and save.

The first plugin-driven check did not unlock. Its log recorded a failed memory-region
resolution on one `2112` boot. A later boot reported effective version `3152` and
fingerprint `live-text-crc32-v1:004EC000:2BE03E4B`, which is intentionally outside this
exact build record. Research for `3152` therefore starts from new snapshots rather than
assuming the `2112` absolute address remains valid.
