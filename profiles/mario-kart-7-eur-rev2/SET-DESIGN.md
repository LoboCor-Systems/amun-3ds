# Mario Kart 7: AMUN achievement set design

Drafted 2026-09-09. Proposed base set: **31 achievements, 345 points**.
This is an original AMUN set, inspired by other Mario Kart sets on
RetroAchievements. It is not an official RetroAchievements release or an account
integration. Titles and descriptions below were written for this project.

## Inspiration and scope

The [Mario Kart 64 set](https://retroachievements.org/game/10078) combines cup
progression, harder classes, race challenges, and time trials. That broad progression
shape fits Mario Kart 7 well. The
[Mario Kart DS set](https://retroachievements.org/game/12711) also makes unlocks and
new classes part of the journey. The
[Super Circuit set](https://retroachievements.org/game/533) groups some lower-class
cup goals while giving individual harder cups their own recognition. This design
uses those structural ideas without importing their achievement text or logic.

The proposed goals cover Mario Kart 7's eight cups and 32 courses, with gliding,
underwater driving, and coins providing its own identity. Nintendo describes those
features on its [Mario Kart 7 page](https://www.nintendo.com/en-gb/Games/Nintendo-3DS-games/Mario-Kart-7-274402.html).
The [Nintendo electronic manual](https://www.nintendo.com/eu/media/downloads/games_8/emanuals/nintendo_3ds_2/mario_kart_7/ElectronicManual_Nintendo3DS_MarioKart7_EN.pdf)
explains the ten-coin race limit, Grand Prix, and Time Trials.

All goals are intended for offline single-player play. The set has no online wins,
StreetPass requirements, real-world clock gates, rare item lottery, or requirement
to erase a save. Points are provisional until hardware playtesting establishes the
effort involved. A separate challenge expansion can cover expert ghosts on every
course after the base set is reliable.

## What can run now

Update 2026-09-10: the five coin goals now exist in
[`mario-kart-7-eur-coins`](../mario-kart-7-eur-coins/README.md), with exact 2112/3152
records and host/native replay tests. The 3152 text CRC and value 30 were independently
read on hardware. The matching rebuilt plugin/pack were installed on the SD card;
the user reported both Small Savings and Pocket Change unlocked, then confirmed it
works and requested the full set. A subsequent live session read 67 coins.

Update 2026-09-13: a separate [18-goal progression candidate](../mario-kart-7-eur-progression/RESEARCH.md)
implements five coin and 13 cup/trophy/star goals with refreshed encoded pointer
chains. It is research-only and not deployed. The installed five-goal pack is unchanged.

Update 2026-09-24: that candidate also contains `first_gp_win` and `win_with_ten`
(20 goals, 205 points). Finish place and race coins were read on the EUR 3152
console. The other 11 race and ghost goals are still unimplemented. Nothing
from this candidate is deployed.

At the time of the original design, only `save.total_coins` had a local memory candidate. The existing research record
identifies it as little-endian `u32` at `0x1413C540`, with an observed `0 -> 6`
transition on the original `2112` build. On 2026-09-09 the user reported that Studio
read `30`, matching the visible total on the currently running game. The current
build's exact identity and AMUN plugin unlock path were subsequently checked as
recorded above; a debugger read alone did not establish them.

The five coin achievements below are the only implementable subset using that one
symbol. Other goals require separate fields; see the newer candidate's research
record for its implementation and outstanding release gates.
No new address, guessed enum, executable trigger, or compatible build record is
introduced by this document. Keep unresearched entries out of `profile.json` and
the installed pack until their dependencies are validated.

## Achievement list

`C` means the existing coin candidate can express the goal after the current build
and plugin path are validated. `R` means additional memory research is required.
Points are AMUN points.

| ID | Title | Player-facing description | Points | State |
|---|---|---|---:|:---:|
| `pocket_change` | Pocket Change | Increase your lifetime coin total through normal play. | 5 | C |
| `coins_25` | Small Savings | Reach 25 lifetime coins. | 5 | C |
| `coins_100` | A Hundred Little Boosts | Reach 100 lifetime coins. | 5 | C |
| `coins_500` | The Kart Fund | Reach 500 lifetime coins. | 10 | C |
| `coins_1000` | Four-Digit Garage | Reach 1,000 lifetime coins. | 10 | C |
| `first_gp_win` | The Flag Finds You | Finish first in a single-player Grand Prix race. | 5 | R |
| `first_gp_gold` | Room on the Shelf | Earn a gold trophy in any single-player Grand Prix cup. | 5 | R |
| `gold_50_all` | Sunday Touring Club | Earn gold trophies in all eight 50cc cups. | 10 | R |
| `gold_100_all` | A Faster Kind of Sunday | Earn gold trophies in all eight 100cc cups. | 10 | R |
| `gold_150_mushroom` | Wings Before Lunch | Take the Mushroom Cup gold trophy at 150cc. | 10 | R |
| `gold_150_flower` | Bloom at Full Throttle | Take the Flower Cup gold trophy at 150cc. | 10 | R |
| `gold_150_star` | Above the Traffic | Take the Star Cup gold trophy at 150cc. | 10 | R |
| `gold_150_special` | Beyond the Guardrail | Take the Special Cup gold trophy at 150cc. | 10 | R |
| `gold_150_shell` | Familiar Roads, New Wings | Take the Shell Cup gold trophy at 150cc. | 10 | R |
| `gold_150_banana` | The Scenic Overtake | Take the Banana Cup gold trophy at 150cc. | 10 | R |
| `gold_150_leaf` | Old Corners, New Tricks | Take the Leaf Cup gold trophy at 150cc. | 10 | R |
| `gold_150_lightning` | A Spark Through History | Take the Lightning Cup gold trophy at 150cc. | 10 | R |
| `gold_mirror_all` | Read the Road Backwards | Earn gold trophies in all eight Mirror cups. | 25 | R |
| `star_150_all` | Eight Bright Signatures | Earn at least a one-star rank in all eight 150cc cups. | 25 | R |
| `win_with_ten` | Heavy Pockets, Light Foot | Win a single-player Grand Prix race with 10 coins at the finish. | 10 | R |
| `gp_sweep` | Leave No Flag Behind | Finish first in all four races of one 100cc or 150cc Grand Prix. | 10 | R |
| `last_lap_comeback` | The Last Lap Disagrees | Start the final lap in eighth place and win that single-player Grand Prix race. | 10 | R |
| `rainbow_no_rescue` | Keep Your Feet in Space | Win the 3DS Rainbow Road race in 150cc Grand Prix without a Lakitu rescue. | 10 | R |
| `ghost_normal_first` | Ahead of the Recording | Beat a normal staff ghost in Time Trials. | 5 | R |
| `ghost_normal_8` | Eight Empty Rearviews | Beat normal staff ghosts on eight different courses. | 10 | R |
| `ghost_normal_16` | Half the Map Behind You | Beat normal staff ghosts on 16 different courses. | 10 | R |
| `ghost_normal_32` | Every Road Remembered | Beat normal staff ghosts on all 32 courses. | 25 | R |
| `ghost_expert_first` | The Recording Fights Back | Beat an expert staff ghost in Time Trials. | 10 | R |
| `ghost_expert_8` | Eight Answers to the Experts | Beat expert staff ghosts on eight different courses. | 25 | R |
| `land_sea_air_win` | Three Ways to the Same Flag | Win a single-player Grand Prix race after driving underwater and gliding during that race. | 10 | R |
| `ghost_no_mushroom` | The Racing Line Pays | Beat a normal staff ghost in Time Trials without using a Mushroom. | 15 | R |

The five coin goals total 35 points. Progression goals total 160, race challenges
40, ghost milestones 85, and the last two challenges 25: 345 points overall.

## Required evidence and logical symbols

The following are proposed logical field names, not claims about the game's layout.
Array-like notation describes the needed facts; it does not introduce new AMUN
syntax. Resolve them to actual bounded scalar symbols or verified bitfields before
compilation.

| Group | Needed facts | Validation needed before implementation |
|---|---|---|
| Coin total | `save.total_coins`, valid save/initialization state | Correct visible total, natural increase, current build identity, plugin read success, restart stability. |
| Cup progression | Trophy and star rank for each cup/class; save initialized | Identify all cup/class cells and enum encodings using before/after trophies. Confirm fields survive menu changes and restart. Do not infer a star rank from race points. |
| Race results | Mode, local player, race identity, course, class, result validity, finishing position | Distinguish live play from demo, replay, menus, multiplayer, and an aborted race. Verify result values persist long enough for the chosen polling rate. |
| Race challenges | Race coins, lap/section, position at final-lap crossing, per-race rescue count, Grand Prix race index and four finishing results | Verify local-player indexing, reset points, lap/section semantics, and finished-versus-current position. Prefer durable race counters/results over brief animation flags. |
| Ghost goals | Course, valid completed Time Trial, staff ghost class, finish time, verified staff reference time, saved per-course results | Distinguish normal, expert, personal, and downloaded ghosts. An unlocked expert ghost is not proof that the expert ghost was beaten. Count distinct courses, not repeated wins. |
| MK7-specific challenges | Per-race gliding and underwater evidence; per-attempt Mushroom use | Prove fields reset per attempt and describe actual behavior, rather than equipped parts or a merely held item. |

The race-coin count is a separate fact from lifetime coins. A lifetime increase must
never be used to infer a race win, ten coins at the finish, a particular course, a
cup trophy, or a staff ghost victory.

## Unlock semantics

Coin milestones are save-progress goals. They should evaluate the current valid
total using AMUN's `set_progress` or `ge` condition, rather than requiring the player
to cross the threshold after installation. A total of 30 should make `coins_25`
eligible, but leave the 100, 500, and 1,000 goals locked. If several thresholds are
already met, each legitimately unlocks once and the existing toast queue presents
them. Previously earned cup trophies and saved Time Trial records should likewise
count when their validity and meaning can be established.

`pocket_change` keeps its existing stable ID and `increased` semantics. Its first
valid sample primes history; unchanged `30` is not an unlock. A later `30 -> 31`
qualifies. Loading at 30 is intentionally different from observing that increase.
Preserve the ledger across profile upgrades so the same achievement is not awarded
again.

Race challenges require a freshly observed attempt and a valid final result from
that same attempt. Entering a result screen after attachment must not fabricate a
race history. Use a verified race/attempt identity, mode gates, and explicit reset
conditions for restart, abort, menu exit, and the next race. Keep a failure remembered
until that attempt ends; resetting a stateful expression on a rescue alone could
accidentally let it re-arm mid-race. Reject observations with missing required
samples rather than joining events from different races.

For `last_lap_comeback`, initially restrict eligibility to ordinary three-lap
courses. Wuhu Loop, Maka Wuhu, and 3DS Rainbow Road need separately verified section
semantics before they can participate. Eighth place must be measured at the final-lap
crossing, and the finished position must be first.

`gp_sweep` needs all four first-place results from the same cup attempt. The final
gold trophy alone is insufficient. `rainbow_no_rescue` requires an observed start
and a trustworthy rescue counter/history through the final result. The two
MK7-specific goals require behavior during that one attempt; old latched flags must
not carry forward from earlier races.

Staff ghost comparisons use each course's verified in-game reference times. Do not
invent fixed stopwatch targets, compare display strings, count a tied time as a win,
or substitute expert-ghost availability for a victory. If the game does not store a
reliable persistent victory bitmap, additional AMUN per-course achievements or
another explicitly designed durable mechanism will be needed. Session-only hit
counters cannot implement the promised multi-session distinct-course milestones.

## Release order and acceptance checks

1. Validate the exact current game build and repair the plugin read/unlock path.
   Release only the five coin goals as a clearly labeled preview. Confirm that an
   existing total of 30 unlocks Small Savings, a subsequent increase unlocks Pocket
   Change, both survive restart, and normal exit stays stable.
2. Research saved cup trophies and star ranks. Implement progression with positive,
   wrong-class, wrong-cup, uninitialized-save, and restart cases.
3. Research race results and per-attempt state. Start with a basic first-place finish
   and ten coins at the finish, then implement longer challenges only when their
   reset and missed-sample behavior are established.
4. Research staff ghost timing and saved results. Add Time Trial goals with tests for
   normal versus expert, duplicate courses, tied/slower times, aborted trials, and
   existing valid records.
5. Playtest the complete set on the original 2DS. Review difficulty and points, then
   publish an exact supported-build record and complete pack identity.

For every executable addition, run profile validation, scenario tests, deterministic
pack builds, and the relevant runtime tests. Hardware acceptance needs a valid log,
the expected ledger event, the visible toast, and a clean exit. A design row, a host
scenario pass, or a Studio watch alone is not a supported console achievement.
