# Security policy

AMUN runs inside a game process on a modified console and parses files from an SD card, so
bugs in the pack and ledger parsers or the plugin can matter.

## Reporting

Please **do not open a public issue** for a vulnerability. Use the repository's private
vulnerability reporting (GitHub: *Security* > *Report a vulnerability*). Include the plugin or
tool version, a description, and a proof-of-concept file if you have one (for example a
malformed `.amunpack`).

You can expect an acknowledgement and a fix or a mitigation plan as quickly as a hobby project
allows. Please give us time to ship a fix before disclosing publicly.

## Scope

In scope: the pack and ledger parsers, the achievement VM, the plugin's SD-card and memory
access, the release packaging, and Studio/Hub handling of untrusted files.

Out of scope: ways to hack a console, issues in Luma3DS or CTRPluginFramework themselves
(report those upstream), and the safety of running custom firmware online (see
[docs/SAFETY.md](docs/SAFETY.md)).

## Design stance

Packs are bounded and verified before use; the console never evaluates source JSON; AMUN does
not write game memory; the console build has networking compiled out. A report that breaks one
of those properties is treated as high severity.
