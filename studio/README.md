# AMUN Studio

AMUN Studio is a dependency-free Python 3.11+ desktop tool for editing AMUN
source profiles, invoking the profile compiler, researching offline memory
dumps, and safely deploying a packaged SD-card tree.

Studio uses the AMUN double-plume emblem as its window icon and application header.
If a platform cannot load PNG window icons, Studio continues without the icon; the
brand asset is never a runtime dependency for profile authoring.

Launch it from the repository root:

```text
python -m studio
python -m studio path/to/profile.json
python -m studio path/to/project --cli "path/to/amun"
```

The Profile tab combines a raw JSON editor with symbol and achievement tables.
Table edits round-trip into the source JSON. Save operations validate JSON and
atomically replace the selected profile. The CLI is configurable under
**Tools → Configure CLI** and is called without a shell using these contracts:

```text
<configured command> profile validate <project-directory>
<configured command> profile build <project-directory>
```

The Local Library tab indexes `.amunpack` files beneath a configurable local
directory. Scans and metadata opens are read-only, do not follow symbolic
links, and display corrupt packs without executing them. Import and export are
explicit bounded file copies; traversal paths and implicit overwrites are
rejected. Studio does not contact an online profile service.

The Memory Scanner loads raw dumps at a user-supplied base address or persistent
`.amunsnap` files. Snapshots include size/base metadata and a SHA-256 checksum.
Supported little-endian values are `u8`, `s8`, `u16`, `s16`, `u32`, `s32`, and
`f32`; scans support unknown, exact, changed, unchanged, increased, decreased,
signed delta (`by`), inclusive range, and masked bit-change refinements.

The Live 3DS tab defaults to **Direct Luma RSP**. It connects to ports 4000-4002
without an external GDB executable or WSL, reads Luma's bounded process XML, and
shows the exact PIDs supplied by the console. If a profile is open, Studio highlights
the best process-name match but never auto-attaches to a guess. Attaching pauses the
selected process; use **Detach / resume** after sampling or saving a bounded snapshot.
The legacy external GDB/MI backend remains available explicitly.

The Deploy tab copies the contents of a packaged `sd-root` directory. It never
deletes files just because they are absent from that package. Replaced files are
backed up locally, new paths are recorded, and a transaction manifest permits
rollback. Rollback is conflict-aware: it stops before making changes if a
deployed target was edited afterward.

Run the headless tests with:

```text
python -m unittest discover -s studio/tests -v
```
