"""Configurable subprocess hooks for the AMUN command-line compiler."""

from __future__ import annotations

from dataclasses import dataclass, field
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
from typing import Iterable, Sequence


class CliError(RuntimeError):
    """Raised when the configured AMUN CLI cannot be executed."""


def parse_command(command: str) -> tuple[str, ...]:
    command = command.strip()
    if not command:
        raise CliError("CLI command cannot be empty")
    if os.name != "nt":
        return tuple(shlex.split(command))

    argc = ctypes.c_int()
    command_line_to_argv = ctypes.windll.shell32.CommandLineToArgvW
    command_line_to_argv.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
    command_line_to_argv.restype = ctypes.POINTER(wintypes.LPWSTR)
    pointer = command_line_to_argv(command, ctypes.byref(argc))
    if not pointer:
        raise CliError("Windows could not parse the CLI command")
    try:
        return tuple(pointer[index] for index in range(argc.value))
    finally:
        ctypes.windll.kernel32.LocalFree(pointer)


def format_command(command: Sequence[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(list(command))
    return shlex.join(command)


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class CliResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass
class CliHooks:
    """Invoke the implementation CLI without shell interpolation."""

    command: tuple[str, ...] = ("amun",)
    timeout_seconds: float = 120.0

    @classmethod
    def from_text(cls, command: str, timeout_seconds: float = 120.0) -> "CliHooks":
        return cls(parse_command(command), timeout_seconds)

    def run(
        self,
        arguments: Iterable[str],
        *,
        cwd: str | os.PathLike[str] | None = None,
    ) -> CliResult:
        full_command = self.command + tuple(str(item) for item in arguments)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                full_command,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                shell=False,
                check=False,
            )
        except FileNotFoundError as error:
            raise CliError(f"CLI executable was not found: {self.command[0]}") from error
        except subprocess.TimeoutExpired as error:
            raise CliError(
                f"CLI timed out after {self.timeout_seconds:g} seconds: {format_command(full_command)}"
            ) from error
        except OSError as error:
            raise CliError(f"Cannot run CLI: {error}") from error
        return CliResult(
            command=full_command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            elapsed_seconds=time.monotonic() - started,
        )

    def validate(self, project: str | os.PathLike[str]) -> CliResult:
        project_path = Path(project).expanduser().resolve()
        return self.run(("profile", "validate", str(project_path)), cwd=project_path.parent)

    def build(
        self,
        project: str | os.PathLike[str],
        output: str | os.PathLike[str] | None = None,
    ) -> CliResult:
        project_path = Path(project).expanduser().resolve()
        arguments: list[str] = ["profile", "build", str(project_path)]
        if output is not None:
            arguments.extend(("--output", str(Path(output).expanduser().resolve())))
        return self.run(arguments, cwd=project_path.parent)


@dataclass
class StudioSettings:
    cli_command: tuple[str, ...] = ("amun",)
    cli_timeout_seconds: float = 120.0
    backup_directory: Path = field(
        default_factory=lambda: Path.home() / ".amun" / "studio-backups"
    )
    library_directory: Path = field(
        default_factory=lambda: Path.home() / ".amun" / "library"
    )

    @classmethod
    def default_path(cls) -> Path:
        return Path.home() / ".amun" / "studio.json"

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "StudioSettings":
        settings_path = Path(path) if path is not None else cls.default_path()
        if not settings_path.exists():
            return cls()
        try:
            value = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("settings root is not an object")
            command = value.get("cliCommand", ["amun"])
            if isinstance(command, str):
                command_tuple = parse_command(command)
            elif isinstance(command, list) and command and all(isinstance(item, str) for item in command):
                command_tuple = tuple(command)
            else:
                raise ValueError("cliCommand must be a non-empty string array")
            timeout = float(value.get("cliTimeoutSeconds", 120.0))
            if timeout <= 0:
                raise ValueError("cliTimeoutSeconds must be positive")
            backup = Path(value.get("backupDirectory", Path.home() / ".amun" / "studio-backups"))
            library = Path(value.get("libraryDirectory", Path.home() / ".amun" / "library"))
            return cls(command_tuple, timeout, backup.expanduser(), library.expanduser())
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise CliError(f"Cannot load Studio settings from {settings_path}: {error}") from error

    def save(self, path: str | os.PathLike[str] | None = None) -> Path:
        settings_path = Path(path) if path is not None else self.default_path()
        _atomic_json(
            settings_path,
            {
                "version": 1,
                "cliCommand": list(self.cli_command),
                "cliTimeoutSeconds": self.cli_timeout_seconds,
                "backupDirectory": str(self.backup_directory),
                "libraryDirectory": str(self.library_directory),
            },
        )
        return settings_path

    def hooks(self) -> CliHooks:
        return CliHooks(self.cli_command, self.cli_timeout_seconds)
