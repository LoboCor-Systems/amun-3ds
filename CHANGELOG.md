# Changelog

## Unreleased (0.2.0-preview candidate)

### Added
- Mario Kart 7 EUR **stable** set (18 goals, 190 points), generated from the experimental
  progression set; the progression set (31 goals plus 64 hidden ledger entries) is now the
  experimental set.
- Trophy badge: a scored unlock draws its metal tier's trophy in the top-right corner of the
  top screen for the duration of the toast.
- Console `perf:` log lines (average and worst tick time, reads per tick) every 100 ticks.
- User README, safety guide, contributing guide, code of conduct, security policy, issue and PR
  templates, and a set index.

### Fixed
- Packs with achievements that have more than 16 prerequisites (the Mario Kart 7 ghost
  milestones) were rejected by the console build, so no achievements loaded. The limit is 32.
- Large sets made Mario Kart 7 barely playable on an original 2DS: the observer now ticks at
  most every 100 ms with duty-cycle back-off, polls normal-class values every 250 ms, refreshes
  the achievement list only when the menu opens, and rate-limits performance warnings.
  Mario Kart 7 now plays normally on an original 2DS.

### Known issues
- Hardware-tested on one original 2DS only; Old 3DS/XL and New 3DS/2DS XL are untested.
- Race, ghost and Time Trial goals are experimental and some depend on unconfirmed live fields.
