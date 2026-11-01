# Example profile layout

The executable example is [`../synthetic/profile.json`](../synthetic/profile.json).
It intentionally uses only invented addresses and an invented executable hash.
Copy that project when starting a profile, then replace every identity, resolver,
asset, and test trace with evidence from the exact game build being supported.

The compiler accepts a profile JSON file directly or a directory containing
`profile.json`, `game.json`, or `amun.json`:

```text
python amun.py profile validate profiles/synthetic
python amun.py profile test profiles/synthetic
python amun.py profile build profiles/synthetic
```

For the address-free two-stage console check, use the generator documented in
[`../hardware-self-test/README.md`](../hardware-self-test/README.md). It produces
only valid source profiles and requires the exact identity printed by the 3DS
adapter before creating the matching self-test pack.
