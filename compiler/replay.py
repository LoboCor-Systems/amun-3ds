"""Safe launcher for the authoritative C++ trace replay simulator."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from typing import Mapping


class ReplayError(ValueError):
    pass


def _executable_from(value: str | os.PathLike[str]) -> Path | None:
    text = os.fspath(value)
    has_directory = Path(text).parent != Path(".") or Path(text).is_absolute()
    if not has_directory:
        found = shutil.which(text)
        return Path(found).resolve() if found else None
    candidate = Path(text).expanduser().resolve()
    return candidate if candidate.is_file() else None


def locate_simulator(
    explicit: str | os.PathLike[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Locate ``amun-sim`` without interpreting a command through a shell."""

    if explicit is not None:
        selected = _executable_from(explicit)
        if selected is None:
            raise ReplayError(f"AMUN simulator does not exist or is not on PATH: {explicit}")
        return selected

    variables = os.environ if environment is None else environment
    configured = variables.get("AMUN_SIMULATOR")
    if configured:
        selected = _executable_from(configured)
        if selected is None:
            raise ReplayError(
                f"AMUN_SIMULATOR does not name an existing executable: {configured}"
            )
        return selected

    on_path = _executable_from("amun-sim")
    if on_path is not None:
        return on_path

    repository = Path(__file__).resolve().parents[1]
    candidates: list[Path] = []
    for preset in ("host-debug", "host-release", "host-relwithdebinfo"):
        root = repository / "build" / preset
        candidates.extend(
            (
                root / "amun-sim",
                root / "amun-sim.exe",
                root / "Debug" / "amun-sim.exe",
                root / "Release" / "amun-sim.exe",
                root / "RelWithDebInfo" / "amun-sim.exe",
            )
        )
    candidates.extend(
        (
            repository / "build" / "amun-sim",
            repository / "build" / "amun-sim.exe",
            repository / "build" / "Debug" / "amun-sim.exe",
            repository / "build" / "Release" / "amun-sim.exe",
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ReplayError(
        "could not locate amun-sim; pass --simulator, set AMUN_SIMULATOR, "
        "or build the host-debug/host-release CMake preset"
    )


def replay_trace(
    trace: str | os.PathLike[str],
    pack: str | os.PathLike[str],
    *,
    ledger: str | os.PathLike[str] | None = None,
    simulator: str | os.PathLike[str] | None = None,
) -> int:
    """Run the C++ simulator and return its exit status, forwarding its I/O."""

    trace_path = Path(trace).expanduser().resolve()
    pack_path = Path(pack).expanduser().resolve()
    if not trace_path.is_file():
        raise ReplayError(f"trace does not exist or is not a file: {trace_path}")
    if not pack_path.is_file():
        raise ReplayError(f"pack does not exist or is not a file: {pack_path}")
    executable = locate_simulator(simulator)
    command = [
        str(executable),
        "--pack",
        str(pack_path),
        "--trace",
        str(trace_path),
    ]
    if ledger is not None:
        ledger_path = Path(ledger).expanduser().resolve()
        if ledger_path.exists() and not ledger_path.is_file():
            raise ReplayError(f"ledger path is not a file: {ledger_path}")
        command.extend(("--ledger", str(ledger_path)))
    try:
        completed = subprocess.run(command, check=False, shell=False)
    except OSError as error:
        raise ReplayError(f"could not start AMUN simulator {executable}: {error}") from error
    return int(completed.returncode)
