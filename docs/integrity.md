# Integrity and provenance

AMUN runs on a console whose owner controls the firmware. It provides useful provenance, not an
absolute anti-cheat claim.

Unlock events record an event UUID, achievement ID, exact build ID, wall-clock timestamp, runtime
version, profile hash, session ID, progress, and integrity mode. Timed conditions use the injected
monotonic clock; changing the wall clock can alter the displayed unlock date but cannot complete a
duration challenge.

Modes are:

- `LIVE`: live observation with developer mode off and a reliably inactive cheat facility.
- `LIVE_UNVERIFIED`: live observation when cheat state is active or unknown. This is the safe
  default because reliable detection is not guaranteed across frameworks/titles.
- `DEVELOPER`: watch/scanner/reload/trace research session.
- `IMPORTED`: provenance imported from user-supplied local data.
- `SAVE_SCAN`: a declared offline save/state inspection rather than a live event.

AMUN never silently promotes `UNKNOWN` cheat status to inactive. Developer mode never emits normal
verified-live provenance. The profile hash and CRCs detect accidental/malicious file alteration;
they do not prove that the console, runtime binary, clock, or source profile was trustworthy.

The optional Hub uses a six-digit LAN pairing ceremony followed by a random device token. Frames
are versioned, length-bounded, CRC-protected, and duplicate-addressed. This prevents accidents and
basic unauthorized reconnects; it is not transport encryption and does not resist a local network
attacker observing the pairing exchange. Keep Hub on a trusted LAN.

