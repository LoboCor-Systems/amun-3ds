# Address-free hardware self-test profile

This generator creates a valid pack for one exact native 3DS application without
declaring any memory symbols or addresses. Once the exact build matches, its
bounded one-second monotonic-duration achievement exercises pack parsing, runtime
startup, VM state, durable ledger append, and toast delivery. It does not prove commercial-game address resolution
and has not been verified on physical hardware.

Use the two-stage flow because AMUN deliberately refuses to evaluate an unknown
build:

1. Record the full 16-digit Title ID, region, and effective decimal version shown
   by the AMUN overlay/log. Generate a probe profile without `--fingerprint`:

   ```text
   python profiles/hardware-self-test/generate.py --title-id 00040000XXXXXXXX --region EUR --application-version 0 -o self-test/profile.json
   python amun.py profile validate self-test
   python amun.py profile build self-test -o self-test/game.amunpack
   ```

2. Copy the probe pack to
   `/amun/packs/<FULL-16-DIGIT-TITLE-ID>/game.amunpack`. Its canonical SHA-256
   sentinel cannot equal the live-text scheme emitted on console, so the launch
   remains `UNKNOWN_BUILD` and performs zero profile-driven reads. Copy the exact
   `live-text-crc32-v1:SSSSSSSS:CCCCCCCC` fingerprint printed by that launch.

3. Regenerate with that exact fingerprint and rebuild:

   ```text
   python profiles/hardware-self-test/generate.py --title-id 00040000XXXXXXXX --region EUR --application-version 0 --fingerprint live-text-crc32-v1:SSSSSSSS:CCCCCCCC -o self-test/profile.json --force
   python amun.py profile test self-test
   python amun.py profile build self-test -o self-test/game.amunpack
   ```

4. Replace only that title's pack and launch it again. A successful exact match
   produces the `AMUN Hardware Self-Test` unlock/toast and the title ledger under
   `/amun/ledger/`. A second launch must not append a duplicate unlock.

Remove the self-test pack afterward. Never substitute another title's identity or
treat this address-free check as evidence that a real achievement profile is safe.
