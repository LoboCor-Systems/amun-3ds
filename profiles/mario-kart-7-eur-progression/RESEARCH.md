# EUR cup progression candidate — do not deploy yet

31 scored candidate achievements, 345 points (plus 64 secret 0-pt ledger bits):
the five accepted coin goals, 13 cup/trophy/star progression goals, two race-result
goals (`first_gp_win`, `win_with_ten`), `gp_sweep`, `last_lap_comeback`,
`rainbow_no_rescue`, `land_sea_air_win`, and the Time Trial ghost set from the
[31-goal design](../mario-kart-7-eur-rev2/SET-DESIGN.md): firsts plus count milestones
`ghost_normal_8` / `16` / `32` and `ghost_expert_8`, plus `ghost_no_mushroom`,
backed by durable per-course ledger bits. This is the completed 31-achievement
research set. It is not installed on the SD card. The working coin-only release
remains unchanged.

## Evidence and uncertainties

Read-only captures on the original 2DS on 2026-09-11 found:

- Static RootSystem at `0x006789B8`; rootScene pointer at +0x10.
- SystemEngine encoded pointer at rootScene+0x208, XOR `0x75F1B26B`;
  its adjacent existence byte at +0x20C was 1.
- SaveDataManager at SystemEngine+0x28; **embedded save at manager+0xC0**.
  A shadow save pointer at manager+0xB0 led to the matching second copy.
- Lifetime coins at save+0x4C28: both copies read 67.
- 32 candidate trophy bytes at save+0x70C: first byte `0x3B`, other 31 zero,
  identical in both save copies. Captures during the menu and attract demo agreed.

The new pointer path replaces a heap address with a bounded, refreshed chain. It
uses pack 1.1; older plugins reject it rather than interpreting it incorrectly.
Cup triggers require an existing SystemEngine, matching main/shadow cell, completed
bit, gold trophy, and valid reserved/rank bits. Saved progress can count immediately.
Every existing coin achievement ID is preserved.

References (layout facts only; no external game-writing helpers are executed):

- [mk7re/MK7-Memory](https://github.com/mk7re/MK7-Memory), MIT, commit
  `b531a9aaf6aca01c1bcd7600d8fdd626d1fc6b75`.
- [mk7re/MK7-Emu-Scripts](https://github.com/mk7re/MK7-Emu-Scripts), commit
  `e4f81c4df118f74c0c2cc2b31a2c646c687f0726`, RootSystem and encoded engine lookup.
- [MK7 Plugin Deluxe source](https://github.com/SFC-hacker/Mario-Kart-7-Plugin-Deluxe/blob/master/plugin/Sources/cheats.cpp):
  relative offsets for coin/table and the documented all-gold-three-star byte `0x3D`.

**Do not blindly use the upstream template:** its SaveDataManager offsets were
eight bytes early on this build, and its GrandPrixData bit accessors contradict the
`0x3D` reference. This candidate interprets bit 0 as complete, bits 1-3 as rank
(4/5/6 = one/two/three stars), and bits 4-5 as trophy (3 = gold). Cup-major
`[cup * 4 + class]` ordering and that bitfield decode are now **hardware-confirmed**
for EUR 3152 (2026-09-22): visible 50cc Mushroom gold/two stars at index 0 (`0x3B`)
and a natural 50cc Shell gold/three stars write at index 16 (`0x3D`). Remaining
release gates are race/ghost live fields, a non-1st place race sample, and an
explicit deploy decision -- not cup-table layout.

The attract demo had live-looking race objects but playMode 3 and ruleMode 6.
It must never qualify as a player's race. September 27-28 Time Trial captures pin
ghost class, player finish time, and place. Staff reference times for course 4 and
sketch achievements `ghost_normal_first` / `ghost_expert_first` are now in this
candidate (research-only; `compatible` remains false). See the staff table and
sketch section below, and
[emulator setup and its separate US-build boundary](../../docs/MK7-EMULATOR-TESTING.md).

## Repeatable checks

```powershell
python -B -m cli profile test profiles/mario-kart-7-eur-progression/profile.json
python -B -m unittest tests.python.test_mk7_progression tests.python.test_pointer_resolvers
python -B -m cli profile build profiles/mario-kart-7-eur-progression/profile.json -o build/mk7-progression-research.amunpack
```

Synthetic tests cover every cup/class cell, seven-versus-eight cups, star ranks,
silver/bronze, incomplete/invalid bytes, uninitialized engine, disagreement between
save copies, all original coin scenarios, and native pack/VM/ledger replay. These
validate the implementation, not the provisional mapping's correctness on hardware.

2026-09-13 verification: 66 native candidate scenarios and 66 persistent-ledger
replays pass. Six CTest suites pass; 85 Python tests finish (83 pass, two Windows
symlink-permission skips). The new 3DS plugin also cross-compiles and its 3GX
container validates. Neither candidate file has been deployed.

Local build identities (do not confuse with the installed coin-fix pair):

- `build/mk7-progression-research.amunpack`: 48,974 bytes,
  SHA-256 `3a87e5eaa1f011178d6b52dbc6b917aa0928bba93bb2dbdf9d7afbc42b0b0616`
  (after `last_lap_comeback`; still not deployed).
- `build/3ds-native/AMUN.3gx`: 1,320,804 bytes,
  SHA-256 `fd41debd0fa0c9dae98b2220f37293df9b3044c792189df76d5650f9a590c23b`.

Hardware research could not resume on 2026-09-13: the console's debugger connection
timed out on a bounded connection attempt. No process was attached.

September 14: the test SD card is mounted. Its plugin/pack still match the
accepted coin-fix release, and its log confirms both first coin unlocks. The
decrypted US CIA (from the maintainer's own cartridge) was imported into the isolated emulator,
and booted far enough to initialize audio/graphics and create fresh game saves.
See the emulator document for hashes and the remaining visual/gameplay checks.
No new cup mapping was validated, no candidate was deployed, and the SD was only
read. All six CTest suites passed again.

September 20: direct Luma research resumed successfully on the real 2DS. The
client selected the named `MarioKar` process (PID 39 in this session), captured
23 bounded reads, and detached successfully. Local evidence:
`build/research/mk7-20260920-baseline.json` (20:56:41 UTC). Main/shadow save copies
still agree: 67 lifetime coins, first cup candidate byte `0x3B`, the remaining
31 zero. Menu fields report single-player Grand Prix/50cc; no live RaceDirector
exists in this menu state. This recaptures the baseline, not a new cup result or
independent confirmation of trophy/star encoding. Visible Mushroom Cup confirmation
and a paused fresh 50cc Shell Cup race are the next requested observations.

At the next checkpoint the user reported **two stars and a yellow trophy** for
50cc Mushroom Cup, corroborating gold/two-star interpretation of the observed
first byte `0x3B`. This alone does not prove all bitfields or table ordering.
`build/research/mk7-20260920-shell50-start-paused.json` (21:05:27 UTC) then captured
40 bounded reads and detached successfully. Shell cup byte is 4, race index 0 of
4, course 26, single-player GP, race type 2, engine 0, race state 2. Pad flags are
`01 00 01` (started, no gyro, paused). Vehicle 0 is the master, not a ghost;
KartInfo has player ID 0, zero coins, zero goal flags, displayed-lap candidate 1.
The separate LapRankChecker lap value is -1 at this stationary start checkpoint;
do not equate these two lap representations without further observations.
Main/shadow totals remain 67 and the cup table is unchanged. A first-race result
with user-reported finishing place and finish-line coin count is the next gate.

September 22: Luma research resumed over the local network (Luma v13.4).
`MarioKar` was PID 39. Read-only captures (always detached afterward):

- `build/research/mk7-20260922-233714-live.json` — menu baseline; 77 lifetime
  coins; cup table still index 0 = `0x3B`, others zero; no live RaceDirector.
- `build/research/mk7-20260922-233903-shell50-start-paused.json` — paused at
  start of 50cc Shell Cup race 1; course 26; playMode 0 / ruleMode 0 / type 2 /
  engine 0; raceState 2; 40 bounded reads.
- `build/research/mk7-20260922-234300-shell50-race1-1st-9coins.json` — results
  screen after user-reported **1st place, 9 finish-line coins**. KartInfo race
  coins 0→9; lifetime coins 77→86 (+9); raceState 2→3; cup table unchanged.
- `build/research/mk7-20260922-235548-shell50-gold-3star.json` — after full cup;
  user reported **gold trophy and three stars**. Lifetime coins 104. Cup table
  index 0 remains `0x3B`; **index 16 is now `0x3D`** (Shell = cup 4, 50cc =
  class 0 → `4*4+0`). Main and shadow copies agree.

Cup-table ordering and trophy/star bitfields for these two cells are accepted
for the progression candidate.

September 24: the same EUR 3152 fingerprint was read again over the local network.
A paused 100cc Mushroom Cup race (Toad Circuit, course 4) matched a reported
3rd place, lap 1, and 4 race coins. The results screen then matched 2nd place
and 7 race coins: `race.place` at mode+0x1FD was 3, then 2, and lifetime coins
moved 104→111 in both save copies. The same byte was 1 on the earlier 1st-place
results. The September 20 capture
`build/research/mk7-20260920-shell50-race1-first-ten.json` is a finished 50cc
Shell Cup race with place 1 and 10 race coins, and lifetime coins 67→77.
`first_gp_win` and `win_with_ten` are now in this candidate. They arm only after
a live racing state and clear if the race goes away, so a results screen that is
already up does not count. They are not deployed.

September 27-28: Time Trial live fields were probed on the same EUR 3152 console
(read-only Luma captures; always detached afterward). Ghost sketches were added
afterward from that evidence; nothing was deployed.

**Ghost class flag (Normal vs Expert).** Confirmed by toggling the class without
racing. The byte at `menu.raceInfo+0x030` is mirrored at `mode.header+0x050`:
**0 = Normal, 1 = Expert**. September 28 pair:

- `build/research/mk7-eur-tt-start-20260928-231257.json` — Expert (=1), paused
  Time Trial start (Toad Circuit / course 4).
- `build/research/mk7-eur-tt-start-20260928-231616.json` — Normal (=0), same
  start state after toggling back.

The same flip appears in the September 27 pair
`build/research/mk7-20260927-004106-tt-start-paused.json` (Normal) versus
`build/research/mk7-eur-tt-start-20260927-010715.json` (Expert). Across the
September 28 toggle pair, `save.records` is identical — this flag is not a PB
write.

**Player finish time.** KartInfo / CTime encoding on the results path, not plain
centiseconds in `save.records`. Observed layout is `(seconds<<16)|minutes` in
one u32 plus the next u32 as milliseconds, matching the project's CTime
min/sec/ms reading of the same fields. On Toad Circuit Normal, the player beat
**1:33.594** against Katie's staff ghost **1:35.135** (results evidence includes
`build/research/mk7-20260927-004324-tt-results.json`).

**Place.** `mode+0x1FD` is the finishing place for player 0. The same byte already
drives the race-result goals (`first_gp_win`, `win_with_ten`); Time Trial
results use it as well.

**Staff reference.** Staff ghost times are **not** reliable from the ghost unit's
kartInfo on the results screen. Treat published / observed tables (see below) as
the reference until a live RomFS/DAT pin is confirmed.

## Staff times table (research)

Canonical fill-in file: [`staff-times.json`](staff-times.json). **32/32** race courses filled
(Normal + Expert). Course IDs are `RaceSys::ECourseID`
([mk3ds identifiers](https://mk3ds.com/?title=List_of_Identifiers)); **course 4 = Toad Circuit**.

**Sources.** Primary: Super Mario Wiki per-course Staff ghosts boxes. Cross-check:
[IGN Unlockables](https://www.ign.com/wikis/mario-kart-7/unlockables) (correct Music Park Expert
`2:07.511` not IGN `2:07.551`; Coconut Mall Normal `2:30.117` not IGN `2:30.177`;
Kalimari Desert Expert `1:47.707` not IGN `1:48.707`). No in-tree RomFS/DAT staff dump.
Toad Circuit Normal/Expert match hardware pins `1:35.135` / `1:26.632`.

**Pack wiring.** Format 1.1 still has no course-indexed constant section. Sketches
`ghost_normal_first` / `ghost_expert_first` now use an `any` of 32 `(race.course == id &&
player_ctime_total_ms < staffTotalMs)` branches so goals can use the full table. Count
milestones (`ghost_normal_8` / `16` / `32`, `ghost_expert_8`) now count durable per-course ledger bits (`ghost_n_cXX` / `ghost_e_cXX`) via `prerequisiteMinCount`.

| Course ID | Course | Normal | Expert | totalMs N/E |
|---:|---|---|---|---|
| 0 | Mario Circuit | 2:25.001 | 2:10.018 | 145001 / 130018 |
| 1 | Rock Rock Mountain | 2:35.105 | 2:19.149 | 155105 / 139149 |
| 2 | Cheep Cheep Lagoon | 1:53.758 | 1:42.011 | 113758 / 102011 |
| 3 | Daisy Hills | 2:06.351 | 1:51.111 | 126351 / 111111 |
| 4 | Toad Circuit | 1:35.135 | 1:26.632 | 95135 / 86632 |
| 5 | Shy Guy Bazaar | 2:31.167 | 2:14.714 | 151167 / 134714 |
| 6 | Neo Bowser City | 2:11.032 | 1:58.996 | 131032 / 118996 |
| 7 | DK Jungle | 2:24.040 | 2:10.777 | 144040 / 130777 |
| 8 | Wuhu Loop | 1:44.287 | 1:32.854 | 104287 / 92854 |
| 9 | Maka Wuhu | 1:50.607 | 1:39.361 | 110607 / 99361 |
| 10 | Rosalina's Ice World | 2:25.784 | 2:13.091 | 145784 / 133091 |
| 11 | Bowser's Castle | 2:34.815 | 2:15.244 | 154815 / 135244 |
| 12 | Piranha Plant Slide | 2:20.186 | 2:06.540 | 140186 / 126540 |
| 13 | Rainbow Road | 2:10.090 | 1:52.077 | 130090 / 112077 |
| 14 | Wario Shipyard | 2:26.268 | 2:12.313 | 146268 / 132313 |
| 15 | Music Park | 2:19.336 | 2:07.511 | 139336 / 127511 |
| 16 | Wii Coconut Mall | 2:30.117 | 2:14.167 | 150117 / 134167 |
| 17 | Wii Koopa Cape | 2:49.046 | 2:28.585 | 169046 / 148585 |
| 18 | Wii Maple Treeway | 2:53.560 | 2:34.877 | 173560 / 154877 |
| 19 | Wii Mushroom Gorge | 2:02.292 | 1:50.526 | 122292 / 110526 |
| 20 | DS Luigi's Mansion | 2:09.982 | 1:58.539 | 129982 / 118539 |
| 21 | DS Airship Fortress | 2:23.323 | 2:07.704 | 143323 / 127704 |
| 22 | DS DK Pass | 2:35.045 | 2:16.534 | 155045 / 136534 |
| 23 | DS Waluigi Pinball | 2:44.372 | 2:27.574 | 164372 / 147574 |
| 24 | GCN Dino Dino Jungle | 2:29.837 | 2:14.430 | 149837 / 134430 |
| 25 | GCN Daisy Cruiser | 1:49.564 | 1:43.341 | 109564 / 103341 |
| 26 | N64 Luigi Raceway | 2:04.317 | 1:52.206 | 124317 / 112206 |
| 27 | N64 Kalimari Desert | 2:01.932 | 1:47.707 | 121932 / 107707 |
| 28 | N64 Koopa Troopa Beach | 1:54.274 | 1:42.909 | 114274 / 102909 |
| 29 | GBA Bowser Castle 1 | 1:31.030 | 1:22.221 | 91030 / 82221 |
| 30 | SNES Mario Circuit 2 | 1:28.106 | 1:17.777 | 88106 / 77777 |
| 31 | SNES Rainbow Road | 1:34.459 | 1:21.994 | 94459 / 81994 |

## Ghost goals (firsts + count milestones)

SET-DESIGN firsts: 5 pts / 10 pts. Count milestones: 10 / 10 / 25 / 25. Titles and
descriptions match the design doc. All are tagged `research-candidate`; build stays
`compatible: false`.

| ID | Points | Class gate / bits | Staff compare |
|---|---:|---|---|
| `ghost_normal_first` | 5 | `race.ghost_class == 0` | `any` course+staff Normal totalMs |
| `ghost_expert_first` | 10 | `race.ghost_class == 1` | `any` course+staff Expert totalMs |
| `ghost_n_c00`..`31` | 0 (secret) | Normal class + that course | single-course staff Normal totalMs |
| `ghost_e_c00`..`31` | 0 (secret) | Expert class + that course | single-course staff Expert totalMs |
| `ghost_normal_8` | 10 | `prerequisiteMinCount` 8 of `ghost_n_c*` | durable bit count |
| `ghost_normal_16` | 10 | `prerequisiteMinCount` 16 of `ghost_n_c*` | durable bit count |
| `ghost_normal_32` | 25 | `prerequisiteMinCount` 32 of `ghost_n_c*` | durable bit count |
| `ghost_expert_8` | 25 | `prerequisiteMinCount` 8 of `ghost_e_c*` | durable bit count |
| `ghost_no_mushroom` | 15 | Normal class + Kinoko3 stock still 3 | same Normal staff `any` |

**How compare works**

1. Gate Time Trial: `race.rule_mode == 1`, single-player `play_mode == 0`, `type == 2`,
   engine present; same latch/`rising` race-state pattern as `first_gp_win`
   (arm on live `race.state == 2`, unlock on rising `race.state == 3`).
2. Require `race.place == 1` (`mode+0x1FD`).
3. Require `race.ghost_class` Normal(0) or Expert(1) via `mode+0x94`
   (`mode.header+0x050` / `menu.raceInfo+0x030`).
4. Require `race.course` match a staff row (`mode+0x1C4`); compare against that course's staff `totalMs`.
5. Player CTime from KartInfo: `+0x60` minutes u16, `+0x62` seconds u16, `+0x64` ms u32.
   Derived `race.player_ctime_total_ms = min*60000 + sec*1000 + ms`.
6. Beat iff `player_ctime_total_ms < staff totalMs` for that class on the current course
   (firsts: `any` of 32 course branches; ledger bits: single course). Ties do not count (SET-DESIGN).

## Durable ghost beat ledger + count milestones

RESEARCH has no hardware-confirmed save-memory staff-ghost victory bitmap
(`RankingSaveData` / `PlayerFlagSaveData` remain undocumented on mk3ds). Count
milestones therefore use an AMUN-side durable ledger:

- Secret 0-pt bits `ghost_n_c00`..`ghost_n_c31` and `ghost_e_c00`..`ghost_e_c31`
  unlock with the same TT compare as the firsts (ruleMode 1, place 1, class, course,
  `player_ctime_total_ms` < staff `totalMs`). Each unlock is a durable ledger event
  recording courseId+class.
- Count milestones `ghost_normal_8` (10), `ghost_normal_16` (10), `ghost_normal_32` (25),
  `ghost_expert_8` (25) list those 32 bits as prerequisites with `prerequisiteMinCount`
  8/16/32/8 and trigger on `save.ready == 1` (progress-style; existing bits count on load).
- Zero-point ledger bits are omitted from completion percentage.
- Build stays `compatible: false`. No SD deploy.


## ghost_no_mushroom (research)

SET-DESIGN: **15 pts**, title **The Racing Line Pays**, description "Beat a normal
staff ghost in Time Trials without using a Mushroom." Tagged `research-candidate`.
`compatible` stays false. Not deployed.

**Hardware (2026-10-02, EUR 3152, Toad Circuit Normal TT results).** Player KartItem
is element 0 of the ItemDirector PtrArray. Item kind at KartItem+0x38 and stock
amount at KartItem+0x3C are u32s. Kinoko3 is item id **7**. Unused triple mushrooms
stay at stock **3**. Two uses left stock **1** (ghost unit, element 1, read stock 2
on that same screen — do not use it). `m_equip_items_used` at KartItem+0x48 was **0**
on results in both the unused and the two-use captures, so it does not stick.

**Chain** (same RootSystem / scene / CharacterEngine XOR as the other race symbols):

1. `0x006789B8` +0x04 scene manager, +0x04 scene, +0x1E4 CharacterEngine XOR `0x75F1B26B`
2. directors at CharacterEngine+0x1C
3. ItemDirector at directors+0x38
4. sead PtrArray object starts at ItemDirector+0xC0 (count) / +0xC4 (capacity).
   The **data pointer is +0xC8**, not +0xC0. The 2-kart results capture had count 2.
5. Element 0 is player0 KartItem. Kind +0x38, stock +0x3C.

Profile symbols: `race.player_item_kind`, `race.player_item_stock` (`refresh: true`).

**Unlock** uses the same Normal staff-beat gate as `ghost_normal_first` (TT
`ruleMode == 1`, single-player, type 2, class 0, latch on `race.state == 2`, rising
`race.state == 3`, place 1, `player_ctime_total_ms` < that course's Normal staff
`totalMs`) and also requires kind == 7 and stock == 3 on that results edge. Ties
still do not count. Using any mushroom drops the stock below 3 and blocks only this
goal; `ghost_normal_first` can still unlock.

**Pointer fragility**

- Heap chain through ItemDirector. A menu or a missing race leaves the symbols
  unavailable; that must not count.
- +0xC0 is the array count, not a KartItem pointer. Wiring that slot would read `2`.
- Player is index 0 only for the observed TT order (player, then staff ghost). A
  different array order would score the wrong kart. The ghost's stock is not the
  player's.
- Two independent walks (kind and stock) must agree on the same results tick.
- This is remaining stock, not a press counter. A mushroom that was used and then
  restocked to 3 before results would false-pass; that was not observed. TT is
  assumed to start on Kinoko3 x3. A different starting item with amount 3 does not
  match kind 7.
- Do not substitute `m_equip_items_used` (+0x48); it read 0 after confirmed uses.


## gp_sweep (research)

SET-DESIGN: **10 pts**, title **Leave No Flag Behind**, description "Finish first in all four races of one 100cc or 150cc Grand Prix." Tagged `research-candidate`. `compatible` stays false. Not deployed. The gold/star trophy byte is not a sweep.

**Hardware (2026-10-03, EUR 3152, Banana Cup 100cc).** Engine class is the fifth u32 of the race-info block, `mode+0x1D4` (`race.engine`). This attempt stayed **1**. 0 is 50cc and 3 is Mirror on earlier captures; 2 is 150cc. `menu.gp+0x00` cup id stayed **5** (Banana). `menu.gp+0x50` race index went **0, 1, 2, 3**. Place stayed `mode+0x1FD == 1` on each results screen (`raceState` 3). `menu.gp+0xF8` stayed `0x29` and never received the four places. Do not use it.

**Chains**

- `race.engine`: same RootSystem / scene / CharacterEngine path as `race.type`, final offset `mode+0x1D4`.
- `race.gp_cup` / `race.gp_index`: `0x006789B8+0x10` root scene, sequence engine at `+0x214` XOR `0x75F1B26B` (kind 4), then menu `+0xC0` and gp `+0x620`. Cup is `+0x00` (chain field `0x6E0`); index is `+0x50` (chain field `0x730`). Both u32.

**Unlock** is one achievement, not four durable bits. Durable unlocks cannot be cleared when the cup changes, and a partial sweep must not carry into the next attempt. The trigger is a `sequence` of four results legs (index 0 then 1 then 2 then 3). Each leg requires single-player GP (`play_mode` 0, `rule_mode` 0, `type` 2), `engine_ready`, engine 1 or 2, `race.state == 3`, and `race.place == 1`. The sequence edge-triggers each leg, so a results screen that is already up does not count until a live race is seen.

**Reset** (clears the in-progress latch, not an already unlocked `gp_sweep`) when any of these is true:

- `race.gp_cup` changes
- `race.gp_index` decreases (same cup restarted; a later index must not inherit earlier legs)
- `race.engine` is neither 1 nor 2, including while that value is being sampled between races
- a race finishes (`race.state == 3`) with `race.place != 1`

A 50cc or Mirror gold does not count. Finishing outside first clears the attempt. After a cleared race 1, a later four-first restart of that same cup can still unlock.


## last_lap_comeback (research)

SET-DESIGN: **10 pts**, title **The Last Lap Disagrees**, description "Start the final lap in eighth place and win that single-player Grand Prix race." Ordinary three-lap courses only. Wuhu Loop, Maka Wuhu, and 3DS Rainbow Road stay out until their section laps are verified. Tagged `research-candidate`. `compatible` stays false. Not deployed.

**Hardware (2026-10-03, EUR 3152, Toad Circuit, raceState 2 then 3).** `lap.player0+0x1C` is a u32 lap index: **2** on the final lap (3 of 3) and **3** once results are up. `kartInfo+0x58` is a u16, current lap in the low byte and lap count in the high byte: lap 1 read `0x0301`, the final lap and the results screen read `0x0303`. Live place is `mode+0x1FD` (`race.place`): **8** at the final-lap pause, **1** on the comeback results. The same pause in 1st read place **1**. `lap.player0+0x24` was 8 while 8th, 0 while 1st, and still 8 on the later results screen. It is not a frozen crossing place. Do not use it.

**Chains**

- `race.lap_index`: same mode object as `race.place`, then `mode+0x504` (lap), `lap+0x2C` (player 0), field `+0x1C`. u32.
- `race.lap_shown`: same KartInfo object as `race.coins`, field `+0x58`. u16 `0x0303` means shown lap 3 of 3.

**Unlock** is one in-progress sequence, same style as `gp_sweep`. Leg 1 is a single-player Grand Prix (`play_mode` 0, `rule_mode` 0, `type` 2, any engine class) on a course other than 8, 9, or 13, `race.state == 2`, `race.place == 8`, on the rising edge of "the lap just became final" (`lap_index == 2` and/or `lap_shown == 0x0303`). That edge is the sample. Being 8th later in the same final lap does not count, because the edge already fired. Leg 2 is `race.state == 3` and `race.place == 1` on that same attempt. A results screen that is already up does not count.

**Reset** (clears the in-progress latch, not an already unlocked `last_lap_comeback`) when a new race starts:

- `race.engine_ready == 0` or `race.state == 0`
- `play_mode`, `rule_mode`, or `type` leaves single-player Grand Prix
- `race.course` or `race.gp_index` changes
- `race.lap_index` decreases

Finishing outside first does not unlock and does not by itself clear a sample; the next race does. 50cc and Mirror are allowed. A gold trophy is not a comeback.

## rainbow_no_rescue (research)

SET-DESIGN: **10 pts**, title **Keep Your Feet in Space**, description "Win 3DS Rainbow Road in a 150cc single-player Grand Prix without a single Lakitu rescue." Tagged `research-candidate`. `compatible` stays false. Not deployed.

**Source.** `RaceSys::LogRecorder` at `raceDirector+0x1C0`. `m_logs` is `sead::Buffer<u32>[EValueType::MAX]` at offset 0. Each entry is 8 bytes, **u32 size then pointer** (not pointer then size). `EValueType::RESPAWN` is index 18, so the entry is `log+0x90` (size) / `log+0x94` (pointer). The tally is the u32 at that pointer.

**Hardware (2026-10-05, EUR 3152, 3DS Rainbow Road, 150cc GP).**

- Start line (`build/research/mk7-eur-rainbow-start-20261005-zerochk.json`): course 13, engine 2, playMode 0, ruleMode 0, type 2, raceState 2. RESPAWN size **1**, value **0**. UNDERWATER (14) 0, FLYING (16) 0.
- Results after exactly one Lakitu fall (`build/research/mk7-eur-rainbow-finish-1fall-20261005.json`): raceState 3, place 1 (`mode+0x1FD` and `lap.player0+0x20`). RESPAWN size **1**, value **1**. UNDERWATER 0, FLYING 1037 (likely frames airborne/gliding; not wired yet).
- Earlier Toad and Rainbow runs: the tally restarts each race (two earlier rescues were not carried into the next race).
- The capture scripts store only the log header. The values above are live reads taken right after each capture, with detach after.

**Chains**

- `race.respawn_log_size`: same RootSystem / scene / CharacterEngine path as `race.place`, through `directors+0x1C` race director, `+0x1C0` log, field `+0x90`. u32.
- `race.respawn_count`: same path to `log`, then `+0x94` pointer, value `+0x00`. u32.

**Unlock** is one in-progress attempt, same style as `first_gp_win`. The trigger needs single-player GP (`play_mode` 0, `rule_mode` 0, `type` 2), `engine_ready`, `race.course == 13`, and `race.engine == 2`. A latch is set on a live race frame (`race.state == 2`) on course 13 at 150cc with a readable log (`respawn_log_size != 0`) and `respawn_count == 0`. Then a rising edge of `race.state == 3`, `race.place == 1`, and `respawn_count == 0` unlocks. A rescue does not reset the attempt by itself. It just blocks the finish edge, because the count cannot fall back to 0 inside that race. A results screen that is already up does not count.

**Reset** (clears the in-progress latch, not an already unlocked goal) when a new race starts: `engine_ready == 0` or `race.state == 0`, leaving single-player GP, or a change to `race.course` or `race.gp_index`. Nothing carries across races. 100cc, 50cc, Mirror, and SNES Rainbow Road (31) do not count.

## land_sea_air_win (research)

SET-DESIGN: **10 pts**, title **Three Ways to the Same Flag**, description "Win a single-player Grand Prix race after driving underwater and gliding during that race." Tagged `research-candidate`. Any course / engine class. `compatible` stays false. Not deployed.

**Source.** Same `RaceSys::LogRecorder` at `raceDirector+0x1C0` as `rainbow_no_rescue`. Each `m_logs` entry is 8 bytes, **u32 size then pointer**. `EValueType::UNDERWATER` is index 14 (`log+0x70` / `+0x74`); `EValueType::FLYING` is index 16 (`log+0x80` / `+0x84`). The u32 at each pointer is a **frame total** for that behavior in the current race (not an event counter). Treat `> 0` as evidence the player went underwater / glided.

**Hardware (2026-10-05/06, EUR 3152).**

- Piranha Plant Slide start (`build/research/mk7-eur-landseaair-start-20261005.json`): course 12, 100cc GP, raceState 2. UNDERWATER **0**, FLYING **0**.
- Same race results (`build/research/mk7-eur-landseaair-finish-20261005.json`): raceState 3, place **1**. UNDERWATER **2032**, FLYING **518**.
- Toad Circuit no-glider control (`build/research/mk7-eur-toad-noglide-finish-20261006.json`): jumps allowed, no glider pads. FLYING stayed **0** at results, so FLYING is glide-related frame time, not general airtime.

**Chains**

- `race.underwater_log_size` / `race.underwater_count`: RootSystem path through race director `+0x1C0` log, fields `+0x70` (size) and `+0x74` then `+0x00` (count). u32.
- `race.flying_log_size` / `race.flying_count`: same path, fields `+0x80` / `+0x84` then `+0x00`. u32.

**Unlock** is one in-progress attempt, same style as `first_gp_win` / `rainbow_no_rescue`. Single-player GP (`play_mode` 0, `rule_mode` 0, `type` 2) and `engine_ready`. Two independent mid-race latches fire when `race.state == 2` and each count is readable (`*_log_size != 0`) and `> 0`. A rising edge of `race.state == 3` with `race.place == 1` while both latches are held unlocks. A brief zero mid-race after arming does not clear a latch. A results screen that is already up does not count.

**Reset** (clears in-progress latches, not an already unlocked goal) when a new race starts: `engine_ready == 0` or `race.state == 0`, leaving single-player GP, or a change to `race.course` or `race.gp_index`. Nothing carries across races. Demo / Time Trial do not count.

## Gaps still open

- ~~Staff times for courses other than Toad Circuit (4).~~ Filled in `staff-times.json` (32/32).
- ~~Count milestones `ghost_normal_8` / `16` / `32` and `ghost_expert_8`.~~ Wired to
  durable per-course ledger bits (no save bitmap confirmed yet).
- RomFS/DAT or other stable live staff-time pin (ghost-unit kartInfo on results is not).
- Optional: confirm whether MK7 `systemX.dat` stores a staff-beat bitmap that could
  replace the AMUN ledger bits later.
- ~~`ghost_no_mushroom`~~ Wired (research-only) from remaining Kinoko3 stock on
  results. See the section above. Not a live `m_equip_items_used` counter.
- ~~`last_lap_comeback`~~ Wired (research-only) as a final-lap place sample.
  See the section above. `lap.player0+0x24` is not the latch.
- ~~`rainbow_no_rescue`~~ Wired (research-only) from the LogRecorder RESPAWN tally.
  See the section above.
- ~~`land_sea_air_win`~~ Wired (research-only) from LogRecorder UNDERWATER / FLYING
  frame totals. See the section above.
- ~~`gp_sweep`~~ Wired (research-only) as a four-race latch. See the section below.
- Keep `compatible` false; do not deploy over the live coin pack.

The installed five-goal coin pack is unchanged. No candidate was written to the SD
card during these captures.
