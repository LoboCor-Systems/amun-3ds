# Building and packaging a release

AMUN has two deliberately different package classes:

1. **Host-tools**: CLI, Studio, Hub, examples, docs, no console plugin.
2. **Plugin-bearing, not hardware verified**: the same material plus a cross-compiled
   3GX and exact SD tree.

Only a recorded physical run can create a hardware-tested release claim. The packager
always writes `hardwareVerified: false` and never infers validation from a filename.

## Host evidence gate

From a clean checkout:

```sh
./scripts/test.sh
python3 amun.py profile validate profiles/synthetic
python3 amun.py profile test profiles/synthetic
python3 amun.py profile build profiles/synthetic -o build/synthetic-a.amunpack
python3 amun.py profile build profiles/synthetic -o build/synthetic-b.amunpack
cmp build/synthetic-a.amunpack build/synthetic-b.amunpack
python3 amun.py pack inspect build/synthetic-a.amunpack --disassemble
./scripts/benchmark.sh > build/host-benchmark.csv
```

Configure standalone fuzz smoke when it is not already built:

```sh
cmake -S . -B build/fuzz -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DAMUN_BUILD_TESTS=ON \
  -DAMUN_BUILD_TOOLS=OFF \
  -DAMUN_BUILD_3DS_PLATFORM_TESTS=OFF \
  -DAMUN_BUILD_FUZZERS=ON
cmake --build build/fuzz --parallel
ctest --test-dir build/fuzz --output-on-failure -R '^amun-fuzz-.*-smoke$'
python3 -B tests/fuzz/fuzz_python_parsers.py
```

## Cross-build gate

Use the exact legal inputs in [`3ds-toolchain.md`](3ds-toolchain.md). In a prepared
devkitPro environment:

```sh
./scripts/build-3ds.sh
```

That wrapper fetches exact Git revisions, verifies/applies the reviewed patches,
builds 3gxtool and CTRPluginFramework, links `AMUN.elf`, converts it, and requires the
eight-byte `3GX$0002` marker. Preserve:

```text
3ds/AMUN.elf
3ds/AMUN.map
3ds/AMUN.3gx
```

The loader-event-guarded 2026-09-02 working tree passed this cross-build gate with
devkitARM r68 and libctru 2.7.0. The matching candidate outputs are:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `AMUN.3gx` | 1,318,704 | `d579addd00deca524600cf6b058a7ed5d90b49dc2657df7bd24c431a82248571` |
| `AMUN.elf` | 4,579,912 | `c73f029094fe1411e31ba6a3091ce8edd073baafdb22f67b9c0063e01ff170c3` |
| `AMUN.map` | 5,097,541 | `60606d10f5e141cbe96ca01b570ed3498146db7142ea619dec248fdc2c2d99c5` |

That cross-build result was later followed by physical execution on the original 2DS.
ARM disassembly shows that all four information-row
`CanBeSelected` calls pass true and that `PatchProcess` enables `CloseMenuWithB` while
leaving its adjacent framework booleans false. It also verifies that the patched CTRPF
destructor cleans only a finished thread and never directly frees a possibly running
thread stack. It also shows the new null branch before `PLGLDR__FetchEvent`'s exclusive
read and both pointer checks in `PLGLDR__Reply`. Host tests cover the ledger failure
latch and dependency patch. The current hash passed no-pack Pilotwings and exact-pack
Mario Kart launch/normal-exit regression paths, so the scoped artifact status is
`HARDWARE-TESTED=yes`. A live memory-profile unlock remains a separate pending gate.

Storage/shutdown-fixed predecessor SHA-256
`dfec2647d030f8b0fe2a997d38f815371eb9d17945d1fba0bda2f78e9dd5c226`
passed Mario Kart 7 torn-ledger recovery, durable unlock/toast, relaunch, and normal
exit on the original 2DS. It later crashed on no-pack Pilotwings exit in null
`PLGLDR__FetchEvent`, so the global plugin is retired and must not be staged.

UI-fixed predecessor SHA-256
`d0dcd7a42704ab3dfe2cd1cf937c9cf9f0679664c261de52d56c4d203c188895`
passed menu controls and identity discovery on the original 2DS but failed the first
exact-pack append and crashed during delayed exit. It is retired and must not be staged.

Superseded ownership-fixed 3GX SHA-256
`d6d72a9f6de19d2897696d3e75be890ce12bc119b37004ea0c145d8542184f09`
loaded on 2026-08-30 on an original wedge 2DS in Mario Kart 7 EUR, full Title ID
`0004000000030700`. Its platform log records clock and scratch-ledger passes, zero game
reads, and pause/resume/stop; the tester reported a clean title close. Down could not
move between the information rows and B could not close the root overlay. This hash is
superseded for UI usability, but is not classified as unsafe. Its Luma version was not
recorded.

Predecessor 3GX SHA-256
`e13bab596760e4b8ab594ec0acdecc0e1be1fbecd734b1d53a363f714fc8cc27`
did load twice on an original wedge 2DS, but both self-test sessions crashed during
CTRPF menu teardown. It is **unsafe and retired** and must never be staged or
distributed as a release artifact.

Record the container OCI digest or installed devkitARM/libctru versions, dependency
commits, patch hashes, AMUN Git revision, and hashes of all three outputs. A successful
cross-link changes status to cross-compiled only.

## Deterministic staging

Host-tools package:

```sh
SOURCE_DATE_EPOCH=946684800 \
python3 scripts/package-release.py --version 0.1.0 --replace
```

Plugin package:

```sh
SOURCE_DATE_EPOCH=946684800 ./scripts/package-3ds.sh --replace
```

PowerShell equivalents are `scripts/package-release.ps1` and
`scripts/package-3ds.ps1`. To place exact-title packs into the SD tree, repeat:

```text
--pack FULL_16_DIGIT_TITLE_ID=path/to/game.amunpack
```

The packager rejects packs over the runtime's 2 MiB hard limit before reading them,
then independently checks pack magic/version/size/directory/CRC and requires the
embedded Title ID to equal the destination. For a 3GX input it validates the current
magic, complete pinned-format header, metadata/target/symbol bounds, loader flags, and
contiguous executable ranges. It additionally requires AMUN's target-free Console,
5 MiB, loader-managed swap, shared-memory, no-homebrew policy and rejects
`--require-3gx` without a plugin. A
plugin-bearing package also requires the reviewed exact CTRPluginFramework license.

Output:

```text
dist/release/
├── AMUN-3DS-v0.1.0.zip
└── AMUN-3DS-v0.1.0/
    ├── AMUN.3gx                  # only when supplied
    ├── debug/AMUN.elf            # plugin package debug symbols
    ├── debug/AMUN.map            # matching linker map
    ├── NO-3GX.txt                # host-tools bundle instead
    ├── amun-cli/
    ├── amun-studio/
    ├── amun-hub/
    ├── example-profiles/
    ├── dependency-patches/
    ├── docs/
    ├── LICENSES/
    ├── sd-root/
    ├── release.json
    └── SHA256SUMS
```

Inputs are copied in sorted order; generated text uses LF; staged timestamps and ZIP
entries use `SOURCE_DATE_EPOCH`; the archive root is versioned. `SHA256SUMS` covers
every staged file other than itself. Existing output is never replaced unless
`--replace` is explicit, and replacement targets only the version-derived leaf and ZIP.
The version is restricted to a 1-64 character filename-safe token, resolved replacement
targets must remain direct children of the selected output directory, and source-tree
symlinks are rejected. The automated suite checks traversal strings, programmatic
validation bypasses, escaping stage symlinks, sibling preservation, manifest contents,
and byte-for-byte ZIP reproduction.

Prove repeatability by packaging twice from unchanged inputs and comparing ZIP hashes.
Pack file assets are external build inputs, so compare the final pack hash as well as
the source profile hash.

## Licensing gate

AMUN is MIT. The current plugin statically links pinned CTRPluginFramework, whose
custom license is reproduced exactly at
`LICENSES/CTRPluginFramework-LICENSE.txt`. The packager refuses a different text when
a plugin is present. Reviewed dependency patches and fetch/build scripts are included
so the modified source input is identifiable. Its terms include a fee/source condition
for binary access and same-license retention for covered source; distribute the plugin
without an access fee and keep the pinned patched source available unless qualified
legal review establishes another compliant release process. 3gxtool is a build tool
rather than a linked component; its MIT notice is retained. The exact libctru 2.7.0
license section is staged for the linked library as well.

Read [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) before redistribution. Do
not package Nintendo SDK files, keys, firmware, games, saves, dumps, or unlicensed pack
assets.

## CI artifact labels

Regular CI uploads host evidence and the host-tools package. The 3DS container job is
manual/optional because it fetches and builds substantial pinned dependencies. It uses
the devkitPro image by OCI digest and labels its upload:

```text
CROSS-COMPILED: yes
HARDWARE-TESTED: no
```

After cross-build, run [`hardware-test.md`](hardware-test.md). Keep the resulting
report, log, ledger, hashes, and photos/video with the release. Do not edit status rows
from pending to pass based on second-hand or emulator-only evidence.
