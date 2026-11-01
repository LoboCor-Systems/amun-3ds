"""Profile project loading, editing, and atomic persistence."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable


class ProjectError(ValueError):
    """Raised when a Studio project cannot be opened or represented safely."""


PREFERRED_PROFILE_NAMES = ("profile.json", "game.json", "amun.json")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _parse_document(raw_text: str, source: str = "profile") -> dict[str, Any]:
    try:
        value = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise ProjectError(
            f"Invalid JSON in {source} at line {error.lineno}, column "
            f"{error.colno}: {error.msg}"
        ) from error
    if not isinstance(value, dict):
        raise ProjectError(f"{source} must contain one top-level JSON object")
    return value


def _select_profile_file(directory: Path) -> Path:
    for name in PREFERRED_PROFILE_NAMES:
        candidate = directory / name
        if candidate.is_file():
            return candidate

    root_json = sorted(path for path in directory.glob("*.json") if path.is_file())
    if len(root_json) == 1:
        return root_json[0]
    if not root_json:
        raise ProjectError(
            f"No profile JSON found in {directory}. Expected one of: "
            + ", ".join(PREFERRED_PROFILE_NAMES)
        )
    names = ", ".join(path.name for path in root_json)
    raise ProjectError(
        f"Project directory has multiple JSON files ({names}); open the profile file directly"
    )


@dataclass
class ProfileProject:
    """A source profile and its containing project directory."""

    root: Path
    profile_path: Path
    document: dict[str, Any]
    raw_text: str
    dirty: bool = False

    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> "ProfileProject":
        selected = Path(path).expanduser().resolve()
        if selected.is_dir():
            profile_path = _select_profile_file(selected)
            root = selected
        elif selected.is_file():
            profile_path = selected
            root = selected.parent
        else:
            raise ProjectError(f"Project path does not exist: {selected}")

        try:
            raw_text = profile_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            raise ProjectError(f"Cannot read {profile_path}: {error}") from error
        document = _parse_document(raw_text, str(profile_path))
        return cls(root=root, profile_path=profile_path, document=document, raw_text=raw_text)

    @classmethod
    def create(
        cls,
        directory: str | os.PathLike[str],
        filename: str = "profile.json",
    ) -> "ProfileProject":
        root = Path(directory).expanduser().resolve()
        if Path(filename).name != filename or not filename.lower().endswith(".json"):
            raise ProjectError("Profile filename must be a plain .json filename")
        document: dict[str, Any] = {
            "schema": 1,
            "game": {
                "platform": "3ds",
                "titleId": "0004000000000000",
                "name": "New AMUN profile",
                "builds": [],
            },
            "symbols": {},
            "achievements": [],
        }
        raw_text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        return cls(root=root, profile_path=root / filename, document=document, raw_text=raw_text, dirty=True)

    def apply_raw(self, raw_text: str) -> None:
        self.document = _parse_document(raw_text, str(self.profile_path))
        self.raw_text = raw_text
        self.dirty = True

    def formatted_json(self) -> str:
        return json.dumps(self.document, indent=2, ensure_ascii=False) + "\n"

    def reformat(self) -> str:
        self.raw_text = self.formatted_json()
        self.dirty = True
        return self.raw_text

    def save(self, raw_text: str | None = None) -> Path:
        if raw_text is not None:
            self.apply_raw(raw_text)
        elif not isinstance(self.document, dict):
            raise ProjectError("Profile document must be a JSON object")
        text = self.raw_text
        if text and not text.endswith("\n"):
            text += "\n"
        try:
            _atomic_write_text(self.profile_path, text)
        except OSError as error:
            raise ProjectError(f"Cannot save {self.profile_path}: {error}") from error
        self.raw_text = text
        self.dirty = False
        return self.profile_path

    def save_as(self, path: str | os.PathLike[str], raw_text: str | None = None) -> Path:
        destination = Path(path).expanduser().resolve()
        if destination.suffix.lower() != ".json":
            raise ProjectError("Profile destination must use a .json extension")
        self.root = destination.parent
        self.profile_path = destination
        return self.save(raw_text)

    def symbols(self) -> list[tuple[str, dict[str, Any]]]:
        symbols = self.document.get("symbols", {})
        rows: list[tuple[str, dict[str, Any]]] = []
        if isinstance(symbols, dict):
            for identifier, definition in symbols.items():
                rows.append((str(identifier), definition if isinstance(definition, dict) else {"value": definition}))
        elif isinstance(symbols, list):
            for index, definition in enumerate(symbols):
                if isinstance(definition, dict):
                    identifier = str(definition.get("id", definition.get("name", f"symbol_{index}")))
                    rows.append((identifier, definition))
        return rows

    def achievements(self) -> list[dict[str, Any]]:
        achievements = self.document.get("achievements", [])
        return [item for item in achievements if isinstance(item, dict)] if isinstance(achievements, list) else []

    def replace_symbol(self, identifier: str, definition: dict[str, Any], old_identifier: str | None = None) -> None:
        if not identifier.strip():
            raise ProjectError("Symbol identifier cannot be empty")
        symbols = self.document.setdefault("symbols", {})
        if not isinstance(symbols, dict):
            raise ProjectError("Table editing requires 'symbols' to be a JSON object")
        if old_identifier and old_identifier != identifier:
            symbols.pop(old_identifier, None)
        symbols[identifier] = definition
        self.raw_text = self.formatted_json()
        self.dirty = True

    def remove_symbol(self, identifier: str) -> bool:
        symbols = self.document.get("symbols")
        if not isinstance(symbols, dict) or identifier not in symbols:
            return False
        del symbols[identifier]
        self.raw_text = self.formatted_json()
        self.dirty = True
        return True

    def replace_achievement(self, definition: dict[str, Any], index: int | None = None) -> int:
        achievements = self.document.setdefault("achievements", [])
        if not isinstance(achievements, list):
            raise ProjectError("Table editing requires 'achievements' to be a JSON array")
        if index is None:
            achievements.append(definition)
            result = len(achievements) - 1
        elif 0 <= index < len(achievements):
            achievements[index] = definition
            result = index
        else:
            raise ProjectError(f"Achievement index is out of range: {index}")
        self.raw_text = self.formatted_json()
        self.dirty = True
        return result

    def remove_achievement(self, index: int) -> bool:
        achievements = self.document.get("achievements")
        if not isinstance(achievements, list) or not (0 <= index < len(achievements)):
            return False
        del achievements[index]
        self.raw_text = self.formatted_json()
        self.dirty = True
        return True


def resolver_summary(definition: dict[str, Any]) -> str:
    resolver = definition.get("resolver", {})
    if not isinstance(resolver, dict):
        return ""
    kind = str(resolver.get("kind", ""))
    address = resolver.get("address", resolver.get("offset", ""))
    return f"{kind}: {address}" if address != "" else kind


def iter_profile_files(project_root: Path) -> Iterable[Path]:
    """Yield source JSON files for callers that want a broader project view."""

    yield from sorted(path for path in project_root.rglob("*.json") if path.is_file())
