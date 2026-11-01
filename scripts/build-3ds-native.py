"""Direct native devkitARM build, preserving 3ds/Makefile flags and spaced paths.

Requires an already installed devkitARM SDK and the pinned/patched CTRPF library.
Does not install tools, alter WSL, clean directories, or deploy to an SD card.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--devkitpro", type=Path, required=True)
    parser.add_argument("--ctrpf", type=Path, required=True, help="Patched CTRPF Library directory")
    parser.add_argument("--threegxtool", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("build/3ds-native"))
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    sdk, ctrpf, output = args.devkitpro.resolve(), args.ctrpf.resolve(), args.output.resolve()
    suffix = ".exe" if (sdk / "devkitARM/bin/arm-none-eabi-g++.exe").is_file() else ""
    compiler = sdk / f"devkitARM/bin/arm-none-eabi-g++{suffix}"
    archiver = sdk / f"devkitARM/bin/arm-none-eabi-gcc-ar{suffix}"
    for required in (compiler, archiver, ctrpf / "lib/libctrpf.a", sdk / "libctru/lib/libctru.a", args.threegxtool):
        if not required.is_file():
            parser.error(f"Missing build input: {required}")
    subprocess.run(["cmake", f"-DAMUN_CTRPF_SOURCE={ctrpf.parent}", "-P",
                    str(repo / "cmake/3ds/verify_patched_ctrpf.cmake")], check=True)
    output.mkdir(parents=True, exist_ok=True)
    arch = ["-march=armv6k", "-mtune=mpcore", "-mfloat-abi=hard", "-mtp=soft"]
    flags = arch + ["-Os", "-g", "-mword-relocations", "-fomit-frame-pointer",
        "-ffunction-sections", "-fdata-sections", "-fno-strict-aliasing",
        "-Wall", "-Wextra", "-Wpedantic", "-Wconversion", "-Wshadow", "-D__3DS__",
        "-DAMUN_3DS_NETWORKING=0", "-std=gnu++20", "-fno-rtti", "-fno-exceptions",
        "-fno-threadsafe-statics", '-DAMUN_VERSION="0.1.0"']
    for directory in (repo / "3ds/include", repo / "3ds/runtime", repo / "3ds/storage", repo / "core/include", output):
        flags.extend(["-I", str(directory)])
    for directory in (ctrpf / "include", sdk / "libctru/include"):
        flags.extend(["-isystem", str(directory)])
    core = [repo / f"core/src/{name}.cpp" for name in ("crc32", "memory", "pack", "runtime", "vm")]
    platform = sorted(p for folder in ("plugin", "memory", "identity", "runtime", "storage")
                      for p in (repo / "3ds" / folder).glob("*.cpp"))

    def compile_one(source: Path) -> Path:
        obj = output / ("_".join(source.relative_to(repo).with_suffix("").parts) + ".o")
        print(f"Compiling {source.relative_to(repo)}", flush=True)
        subprocess.run([str(compiler), *flags, "-c", str(source), "-o", str(obj)], check=True)
        return obj

    with ThreadPoolExecutor(max_workers=4) as pool:
        objects = list(pool.map(compile_one, core + platform))
    library = output / "libamun_core.a"
    subprocess.run([str(archiver), "rcs", str(library), *map(str, objects[:len(core)])], check=True)
    elf, pack, mapfile = (output / f"AMUN.{ext}" for ext in ("elf", "3gx", "map"))
    subprocess.run([str(compiler), "-T", str(repo / "3ds/3gx.ld"), *arch, "-g", "-Os",
        f"-Wl,--gc-sections,--strip-discarded,-Map,{mapfile}",
        *map(str, objects[len(core):]), "-L", str(output), "-L", str(ctrpf / "lib"),
        "-L", str(sdk / "libctru/lib"), "-lamun_core", "-lctrpf", "-lctru", "-lm",
        "-o", str(elf)], check=True)
    subprocess.run([str(args.threegxtool.resolve()), "--silent", str(elf),
                    str(repo / "3ds/AMUN.plgInfo"), str(pack)], check=True)
    subprocess.run(["cmake", f"-DAMUN_3GX={pack}", "-P", str(repo / "cmake/3ds/verify_3gx.cmake")], check=True)
    for artifact in (elf, pack, mapfile):
        print(f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact} ({artifact.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
