# Mario Kart 7 (EUR): stable set

The demo set for AMUN: 18 achievements worth 190 points, covering lifetime coins and
Grand Prix cup trophies and stars. License: CC0.

| Target | Value |
|---|---|
| Game | Mario Kart 7, EUR, Title ID `0004000000030700` |
| Build | effective application version `3152`, fingerprint `live-text-crc32-v1:004EC000:2BE03E4B` |
| Other regions/builds | Not supported. AMUN stays inert; see CONTRIBUTING to port the set |

## Goals

- **Coins (5):** Pocket Change, Small Savings, A Hundred Little Boosts, The Kart Fund, Four-Digit Garage.
- **Cups (13):** your first gold, all cups gold at 50cc and 100cc, each of the eight cups gold at
  150cc, all mirror cups gold, and at least one star in every 150cc cup.

## Evidence

- Coin goals: unlocked on an original 2DS (see the [coin set notes](../mario-kart-7-eur-coins/README.md)).
- Cup table layout (cup-major `[cup*4+class]` ordering and the gold/star bitfield) was confirmed
  on the same console on 2026-09-22 with a 50cc Mushroom gold and a 50cc Shell gold with
  three stars. Not every cup goal has been unlocked on hardware yet; reports welcome.

## How it is made

This profile is generated, not hand-edited:

```sh
python scripts/make_mk7_stable_profile.py   # subset of the experimental progression profile
python amun.py profile test profiles/mario-kart-7-eur
python amun.py profile build profiles/mario-kart-7-eur -o build/mk7-eur-stable.amunpack
```

It uses the same IDs, triggers and symbols as the
[experimental set](../mario-kart-7-eur-progression/RESEARCH.md), without the race, ghost and Time
Trial goals, so it reads only save data (slowly) and is much cheaper to run on an original 2DS.
