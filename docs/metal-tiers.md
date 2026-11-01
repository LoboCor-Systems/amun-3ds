# Metal tiers (platform chrome)

AMUN shows every scored achievement with one of seven metal tiers, for **every**
game. The tier comes from the achievement's `points` when it is displayed. It is
Hub/Studio/plugin presentation only:

- **No pack or profile format change.** Nothing new is stored in `.amunpack`, the
  source schema, or the ledger. Existing packs get tiers automatically.
- **Profiles do not choose a metal.** Authors pick `points` the way they already do,
  and the band table below decides the metal. Changing a set's metals means changing
  its points, which is a normal profile release.
- **Custom `icon` assets still work.** A per-achievement icon replaces the trophy
  picture. The metal remains as the frame, ribbon, or label colour (see *UI use*).

Status: implemented in the plugin, Studio, CLI, and Hub (see *Where metals show*).
Plugin changes are cross-compile checked only; they are not hardware-tested yet.

## Bands

Ranges are inclusive and cover the whole `points` domain (0–10000).

| Rank | Metal | Points | Typical meaning |
|---:|---|---|---|
| — | *(none)* | 0 | ledger/helper/tracking entries; excluded from completion % already |
| 1 | Copper | 1–4 | trivial or tutorial steps |
| 2 | Bronze | 5–9 | normal progress (the Studio default for a new achievement is 5) |
| 3 | Silver | 10–14 | a real challenge or a full objective |
| 4 | Electrum | 15–24 | hard challenge |
| 5 | Gold | 25–49 | mastery or a major milestone |
| 6 | Platinum | 50–99 | rare, set-defining feats |
| 7 | Rhodium | 100–10000 | exceptional; use only a few per set, if any |

Reference implementation (any language):

```text
tier(points):
    0          -> none
    1..4       -> copper
    5..9       -> bronze
    10..14     -> silver
    15..24     -> electrum
    25..49     -> gold
    50..99     -> platinum
    100..10000 -> rhodium
```

### Code

There is one table per language. The tests make sure the copies agree:

| File | Role |
|---|---|
| `compiler/metal_tiers.py` | **Canonical.** `MetalTier`, `BANDS` (lower bounds), `PALETTE` (highlight/mid/shadow/ink), `metal_tier(points)`, `tier_counts`, `points_label` |
| `core/include/amun/metal_tier.hpp` | Header-only C++ copy for the plugin/core: `metalTierFor`, `metalTierName`, `metalTierBand`, `MetalTierTally` |
| `hub/metal_tiers.py` | Dependency-free band copy, because Hub ships without `compiler/` |
| `tests/python/test_metal_tiers.py` | Checks that the copies agree, plus palette contrast/distinctness and asset shape |
| `tests/unit/test_metal_tier.cpp` | C++ band, name, and tally tests |

**To retune**, edit `BANDS`/`PALETTE` in `compiler/metal_tiers.py` and make the same
edit to the rows in `metal_tier.hpp` (and to `hub/metal_tiers.py` for cut-offs). Then
run `python scripts/make_metal_tiers.py` to redraw the art and run the tests.

### Why these cut-offs

- **The lower edges sit on the values authors already use:** 5, 10, 15, 25, 50, 100.
  This is the 1/2/3/4/5/10/25/50/100 scale common in community achievement sets.
  A round value is always the *first* point of its band, so "10 points" always means
  silver and never depends on which side of a boundary it falls.
- **0 is not copper.** In the runtime summary, zero-point entries are ledger or helper
  achievements and are excluded from completion %. The MK7 progression research set
  has 64 of them. They get no metal and should stay out of player-facing tier counts.
- **Gold is reachable, and platinum/rhodium stay rare.** Bands get wider as points go up.
  This keeps the top two metals for deliberate, high-value designs, and no current set
  reaches them by accident.

### Current sets under this table

| Set | Copper | Bronze | Silver | Electrum | Gold | Platinum | Rhodium | Unranked (0) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MK7 EUR progression (research, 345 pts) | 0 | 6 | 20 | 1 | 4 | 0 | 0 | 64 |
| MK7 EUR coins (live, 35 pts) | 0 | 3 | 2 | 0 | 0 | 0 | 0 | 0 |
| Synthetic test profile (56 pts) | 8 | 5 | 1 | 0 | 0 | 0 | 0 | 0 |

MK7's 25-point ghost milestones show as gold. For a platinum or rhodium headline goal,
a future profile release would raise that goal to 50+ or 100+ points. That is optional
and separate from this design.

## UI use

All surfaces work out the tier from `points`. None of them need a pack read beyond
what they already do.

| Surface | Use |
|---|---|
| Achievement list rows (Hub, Studio table, plugin menu) | 16–24 px trophy or a metal swatch next to the points; sort/filter by tier |
| Achievement detail (plugin note, Hub page) | full 64 px trophy; `Points: 10 (Silver)` |
| Unlock toast (plugin `ThreeDSEventSink`) | add the metal name to the prefix, e.g. `Achievement unlocked (+10, Silver): …`; a small trophy only if the overlay can draw one within budget |
| Progress/summary | per-metal unlocked/total counts beside the existing points and %, e.g. `Gold 2/4` |
| Locked state | the same art drawn desaturated/dimmed at render time; no extra assets |
| Secret, not yet unlocked | show the metal (the toast already shows its points); title/description/ID stay hidden as today |
| Custom per-goal `icon` | draw the custom icon and use the tier colour for its frame or label |

### Where metals show (implemented)

| Surface | What it shows |
|---|---|
| Plugin unlock toast (`3ds/runtime/event_sink.cpp`) | `Achievement unlocked (+10, Silver): <title>`. The toast is tinted with the tier highlight text on the tier ink background. Zero-point unlocks keep the CTRPF default white-on-black and get no metal |
| Plugin achievement browser (`3ds/plugin/main.cpp`) | Folder name `[Unlocked] [Silver] <title>`, with the tag in the tier body colour. Note line `Points: 10 (Silver)`. Secret entries still show the metal |
| Plugin runtime entry | `Unlocked: 12/31 (38%), points 120/345` plus `Metals: Bronze 3/6, Silver 8/20, …` (unlocked/total per tier present) |
| Studio achievement table (`studio/app.py`) | 16 px trophy in the first column, a `Metal` column, and a `Metals: … · N unranked` line under the table |
| CLI `amun pack inspect` | `Metals: Bronze 6, Silver 20, Electrum 1, Gold 4 (64 unranked)` |
| Hub (`hub/server.py`) | An `UNLOCK` whose payload carries integer `points` gets a derived `"metal"` key **beside** the payload in `events.jsonl` (the payload stays verbatim). Hub also prints `Unlock from <device>: <id> (+10, Silver)` |

Not drawn yet: there is no trophy *bitmap* on the console. CTRPF menus and `OSD::Notify`
are text only, so the plugin uses tier colour and name. Drawing the 16 px art over a
toast would need a custom `OSD::Run` callback and a hardware budget check (see *Assets*).

Accessibility: the colour is never the only signal. Each trophy has 1–7 rank pips
on its plinth, and text surfaces also print the metal name.

## Assets

Source art lives in `assets/branding/metal-tiers/`:

```
copper.png bronze.png silver.png electrum.png gold.png platinum.png rhodium.png
```

- 64×64 RGBA PNG. The trophy is original artwork with an Obsidian `#090B0D` outline,
  a Deep lapis `#0A2F78` plinth, and Papyrus `#F3E8CB` rank pips (palette from
  [`brand.md`](brand.md)). It reads on both Midnight and Papyrus backgrounds.
- Alpha is strictly 0 or 255, so `rgba5551` keeps the silhouette exactly. Use
  `rgba5551` for these. `rgb565` has no transparency and would need a fixed
  background colour baked in first.
- Platinum carries one four-point glint and rhodium carries two, as an extra visual step.

### Colours

The trophies use a five-stop left-lit gradient: mid-high, highlight, mid, shadow, then
a bounce-light lift on the far edge so they read as polished metal. Each metal sits in
its own hue family, so neighbouring metals never look alike at 16 px:

| Metal | Hue family | Mid (swatch) | Toast text / ink |
|---|---|---|---|
| Copper | red-orange | `#D66A3C` | `#FFBA96` on `#48180A` |
| Bronze | olive-brown | `#A87638` | `#ECC480` on `#38240E` |
| Silver | neutral grey (no tint) | `#B2B4B8` | `#F6F6F6` on `#303134` |
| Electrum | pale green-gold | `#C4C068` | `#F8F6B8` on `#3C3C14` |
| Gold | saturated yellow-gold | `#F0B428` | `#FFEA88` on `#543400` |
| Platinum | cool ice blue | `#96C0EC` | `#ECF8FF` on `#12284C` |
| Rhodium | bright chrome, violet depth | `#DED4F8` | `#FFFFFF` on `#221244` |

Silver and platinum used to be nearly the same grey. Silver is now strictly neutral,
and platinum is clearly blue with a glint. The tests enforce a minimum mid-colour
distance between neighbours and between silver and platinum/rhodium. They also
require toast text contrast of at least 7:1.

### Small sizes

`scripts/make_metal_tiers.py` also writes `studio/assets/metal-tiers/<metal>-16.png`
and `-24.png`. These use the same trophy shape with heavier handles and outline, and
no rank pips, because the pips do not survive at 16 px. Studio bundles these once.
- Regenerate them all with `python scripts/make_metal_tiers.py` (Pillow, deterministic).
  Pass `--preview sheet.png` to write a contact sheet on both brand backgrounds.

This is platform chrome, so the plugin/Hub should bundle these images once. They are
not game-pack assets: do not copy them into every profile's `assets` (128-asset and
512 KiB decoded budgets). A decoded 64×64 icon is 8 KiB, and all seven are 56 KiB.

### Conversion to rgb565/rgba5551

The repository has **no PNG → rgb565/rgba5551 converter yet**, and metal tiers do not need one: nothing draws them on the console, and Studio uses the PNGs directly. A converter only matters once the plugin draws trophy bitmaps. `compiler/pack.py` only
checks that a raw file has `width × height × 2` decoded bytes. The pixel bit layout and
byte order are not documented anywhere yet, and nothing renders icons today. Before
adding a converter, pin the layout in `pack-format.md`. The suggested layout matches the
3DS GPU: little-endian `u16`, `rgb565` = R[15:11] G[10:5] B[4:0], `rgba5551` =
R[15:11] G[10:6] B[5:1] A[0].
