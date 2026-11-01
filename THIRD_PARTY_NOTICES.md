# Third-party notices

AMUN itself is distributed under the repository [MIT license](LICENSE). A console
plugin build uses legal open homebrew tooling; it contains no Nintendo SDK, keys,
firmware, game data, or other proprietary Nintendo material.

The pinned 3DS build inputs are:

| Dependency | Pin | Role | License handling |
|---|---|---|---|
| Luma3DS | v13.4 | 3GX loader ABI/format authority; not redistributed | GPL-3.0 upstream |
| devkitARM | r68 | ARM cross-compiler; not redistributed | upstream component licenses |
| libctru | 2.7.0 | open 3DS userspace library; linked by the plugin | exact zlib-style notice in [LICENSES/libctru-LICENSE.txt](LICENSES/libctru-LICENSE.txt) |
| CTRPluginFramework | `6671936663faaa900f7cfdeedf42bc8581560f4f` | statically linked plugin framework | custom Pixellizer license in [LICENSES/CTRPluginFramework-LICENSE.txt](LICENSES/CTRPluginFramework-LICENSE.txt) |
| 3gxtool | `57e3160ab72d8533a2f0601efdc8a149b4825ea5` | converts the ELF to 3GX; not linked | MIT notice in [LICENSES/3gxtool-LICENSE.txt](LICENSES/3gxtool-LICENSE.txt) |
| devkitPro container | `devkitpro/devkitarm:20260610` at `sha256:116afba8df8453961de2936ffab20dd441edf4d682856c1ec8b0e53d7ed0bbf5` | reproducible cross-build environment; not redistributed | image/component licenses upstream |

AMUN carries reviewed compatibility patches in `cmake/3ds/patches/`. The release
packager includes those patches and the exact CTRPluginFramework license whenever a
3GX is staged. The dependency fetcher retains upstream Git history and license files.
CTRPluginFramework's terms include a fee/source condition for access to binaries and
require covered source copies, modifications, and distributions to retain that same
license. The conservative release practice is to distribute AMUN's plugin without an
access fee, retain the exact license, and keep the pinned patched source and patch set
available. This is an operational summary, not legal advice; read the exact included
license before redistributing a binary or dependency source.

Achievement packs are separate authored works. Their source profile must declare a
license and provenance. Do not import or distribute third-party achievement text,
art, audio, dumps, saves, or game assets without permission.
