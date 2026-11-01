# Mario Kart 7 EUR: coin preview

Five executable achievements, 35 AMUN points. This is an original local set, not an
official RetroAchievements set or account integration. The larger
[31-goal design](../mario-kart-7-eur-rev2/SET-DESIGN.md) is separate research work;
cup, race-result, and ghost achievements are **not included** in this pack.

| Achievement | Condition | Points |
|---|---|---:|
| Pocket Change | Lifetime coin total increases during play | 5 |
| Small Savings | Reach 25 lifetime coins | 5 |
| A Hundred Little Boosts | Reach 100 lifetime coins | 5 |
| The Kart Fund | Reach 500 lifetime coins | 10 |
| Four-Digit Garage | Reach 1,000 lifetime coins | 10 |

The four milestones recognize an existing total; Pocket Change needs a newly observed
increase. An initial value of 30 earns only Small Savings. Unchanged values and
decreases do not count as coin collection. Existing ledger IDs are retained, so
installing this pack does not re-award an already earned Pocket Change.

## Exact build evidence

Title ID: `0004000000030700`; EUR; symbol `save.total_coins` is little-endian `u32`
at `0x1413C540`, read once per second. Both build records require exact matching:

| Effective version | Live text fingerprint | Read-only observation |
|---|---|---|
| 2112 | `live-text-crc32-v1:004EC000:04F718AE` | 0 -> 6 after normal 50cc GP; Channel showed 6, 2026-09-02 |
| 3152 | `live-text-crc32-v1:004EC000:2BE03E4B` | 30, matching user-reported total; full text CRC rechecked 2026-09-10 |

The latest check used Luma v13.4 release `b3282131`, actual process name `MarioKar`,
PID 39, on the user's original wedge 2DS. The game was detached/resumed afterwards.
PID is session-specific and is not hard-coded in the pack. Executable bytes were
streamed for CRC calculation, not saved. This evidence does not establish address
stability after restarting or on another save; integrity remains `live_unverified`.

The old runtime never retried a failed startup resolution and permanently disabled
the trigger when a sample was unavailable. The replacement retries cheap resolvers
at bounded intervals and waits for real data without inventing a zero baseline.
The pack also admits the independently observed 3152 identity, previously rejected.

## Verification and installation

Ten embedded scenarios pass. The same compiled pack passes 20 native-runtime cases
(ten for each exact build) and 20 persistent-ledger replays without duplicate unlocks.
Runtime unit tests additionally cover late memory availability and missing history.
These tests are synthetic, not proof of a physical toast or successful console exit.

The matching plugin and pack are in `dist/mk7-coin-fix-20260910/sd-root`.
Install **both files together**. They were deployed with backup to the test SD card
on 2026-09-10; the ledger was verified unchanged. The user then reported both Small
Savings and Pocket Change unlocked on the original 2DS, then confirmed that it
works before requesting the full set. The follow-up live session read 67 coins
on 2026-09-11. Post-play ledger inspection remains separate evidence; no ledger
was erased or replaced. The profile's frozen build-time provenance predates this
user acceptance and has intentionally not been edited to manufacture a new pack.

For the console check, load Mario Kart Channel with the existing 30 coins and leave
the AMUN overlay closed briefly: Small Savings should unlock. Earn more coins through
normal play to unlock Pocket Change. Verify both in AMUN's achievement browser, exit
normally, and relaunch to check persistence without duplicate toasts. Do not erase
the ledger to repeat the test.

```powershell
python -B -m cli profile test profiles/mario-kart-7-eur-coins/profile.json
python -B -m cli profile build profiles/mario-kart-7-eur-coins/profile.json -o build/mk7-coins.amunpack
```
