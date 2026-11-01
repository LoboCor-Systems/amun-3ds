"""Transactional deployment of an AMUN SD-root tree.

Only files represented by the selected source tree are created or replaced.
Backups and the transaction manifest live outside the SD card, so deployment
does not add bookkeeping files to unrelated SD locations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from typing import Iterable


class DeploymentError(RuntimeError):
    """Raised when deployment or rollback cannot be completed safely."""


class DeploymentConflict(DeploymentError):
    """Raised when rollback would overwrite a post-deployment user change."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_relative(text: str) -> Path:
    path = Path(text)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise DeploymentError(f"Unsafe transaction path: {text!r}")
    return path


def _copy_atomic(source: Path, destination: Path, expected_hash: str | None = None) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w+b", dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp", delete=False
    )
    temporary = Path(handle.name)
    digest = hashlib.sha256()
    try:
        with source.open("rb") as input_handle, handle:
            for chunk in iter(lambda: input_handle.read(1 << 20), b""):
                handle.write(chunk)
                digest.update(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        actual_hash = digest.hexdigest()
        if expected_hash is not None and actual_hash != expected_hash:
            raise DeploymentError(f"Source changed while it was being copied: {source}")
        os.replace(temporary, destination)
        return actual_hash
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class SdCandidate:
    root: Path
    score: int
    reasons: tuple[str, ...]

    @property
    def likely(self) -> bool:
        return self.score >= 20


def _windows_volumes() -> Iterable[tuple[Path, bool]]:
    kernel32 = ctypes.windll.kernel32
    mask = kernel32.GetLogicalDrives()
    for index in range(26):
        if not mask & (1 << index):
            continue
        root = Path(f"{chr(ord('A') + index)}:\\")
        drive_type = kernel32.GetDriveTypeW(str(root))
        # DRIVE_REMOVABLE=2. Some USB SD readers report DRIVE_FIXED=3.
        if drive_type in (2, 3):
            yield root, drive_type == 2


def _posix_volumes() -> Iterable[tuple[Path, bool]]:
    roots = (Path("/media"), Path("/run/media"), Path("/Volumes"))
    seen: set[Path] = set()
    for parent in roots:
        if not parent.is_dir():
            continue
        for candidate in parent.glob("*/*") if parent == Path("/run/media") else parent.glob("*"):
            if candidate.is_dir() and candidate not in seen:
                seen.add(candidate)
                yield candidate, True


def detect_sd_cards(
    search_roots: Iterable[str | os.PathLike[str]] | None = None,
) -> list[SdCandidate]:
    """Find likely 3DS SD roots without writing to any candidate."""

    explicit = search_roots is not None
    if search_roots is not None:
        volumes = [(Path(item).expanduser(), False) for item in search_roots]
    elif os.name == "nt":
        volumes = list(_windows_volumes())
    else:
        volumes = list(_posix_volumes())

    output: list[SdCandidate] = []
    seen: set[Path] = set()
    for raw_root, removable in volumes:
        try:
            root = raw_root.resolve()
        except OSError:
            continue
        if root in seen or not root.is_dir():
            continue
        seen.add(root)
        score = 10 if removable else 0
        reasons: list[str] = ["removable volume"] if removable else []
        markers = (
            ("luma", 35, "Luma directory"),
            ("Nintendo 3DS", 30, "Nintendo 3DS data"),
            ("boot.firm", 25, "boot.firm"),
            ("amun", 15, "existing AMUN directory"),
        )
        for relative, points, description in markers:
            if (root / relative).exists():
                score += points
                reasons.append(description)
        if explicit or removable or score:
            output.append(SdCandidate(root, score, tuple(reasons or ("manually supplied",))))
    return sorted(output, key=lambda item: (-item.score, str(item.root).lower()))


@dataclass
class DeploymentEntry:
    path: str
    action: str
    source_sha256: str
    before_sha256: str | None = None
    backup_path: str | None = None
    applied: bool = False


@dataclass
class DeploymentTransaction:
    identifier: str
    created_at: str
    source_root: str
    sd_root: str
    backup_root: str
    status: str
    entries: list[DeploymentEntry] = field(default_factory=list)
    created_directories: list[str] = field(default_factory=list)

    @property
    def directory(self) -> Path:
        return Path(self.backup_root) / self.identifier

    @property
    def manifest_path(self) -> Path:
        return self.directory / "transaction.json"

    def to_dict(self) -> dict[str, object]:
        return {
            "version": 1,
            "identifier": self.identifier,
            "createdAt": self.created_at,
            "sourceRoot": self.source_root,
            "sdRoot": self.sd_root,
            "backupRoot": self.backup_root,
            "status": self.status,
            "createdDirectories": list(self.created_directories),
            "entries": [asdict(entry) for entry in self.entries],
        }

    def save(self) -> None:
        _atomic_json(self.manifest_path, self.to_dict())

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "DeploymentTransaction":
        selected = Path(path).expanduser().resolve()
        manifest = selected / "transaction.json" if selected.is_dir() else selected
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise DeploymentError(f"Cannot load transaction {manifest}: {error}") from error
        if not isinstance(value, dict) or value.get("version") != 1:
            raise DeploymentError("Unsupported deployment transaction")
        try:
            entries_value = value["entries"]
            if not isinstance(entries_value, list):
                raise TypeError("entries is not an array")
            entries = [
                DeploymentEntry(
                    path=str(item["path"]),
                    action=str(item["action"]),
                    source_sha256=str(item["source_sha256"]),
                    before_sha256=(str(item["before_sha256"]) if item.get("before_sha256") else None),
                    backup_path=(str(item["backup_path"]) if item.get("backup_path") else None),
                    applied=bool(item.get("applied", False)),
                )
                for item in entries_value
                if isinstance(item, dict)
            ]
            transaction = cls(
                identifier=str(value["identifier"]),
                created_at=str(value["createdAt"]),
                source_root=str(value["sourceRoot"]),
                sd_root=str(value["sdRoot"]),
                backup_root=str(value["backupRoot"]),
                status=str(value["status"]),
                entries=entries,
                created_directories=[str(item) for item in value.get("createdDirectories", [])],
            )
        except (KeyError, TypeError) as error:
            raise DeploymentError(f"Malformed transaction manifest: {error}") from error
        if transaction.manifest_path.resolve() != manifest.resolve():
            raise DeploymentError("Transaction location does not match its manifest")
        for entry in transaction.entries:
            _safe_relative(entry.path)
            if entry.backup_path:
                _safe_relative(entry.backup_path)
        return transaction


class SdDeployer:
    def __init__(self, backup_root: str | os.PathLike[str]) -> None:
        self.backup_root = Path(backup_root).expanduser().resolve()

    def deploy(
        self,
        source_root: str | os.PathLike[str],
        sd_root: str | os.PathLike[str],
    ) -> DeploymentTransaction:
        source = Path(source_root).expanduser().resolve()
        target = Path(sd_root).expanduser().resolve()
        if not source.is_dir():
            raise DeploymentError(f"SD source tree is not a directory: {source}")
        if not target.is_dir():
            raise DeploymentError(f"SD destination is not a directory: {target}")
        if source == target or _is_within(source, target) or _is_within(target, source):
            raise DeploymentError("Source tree and SD root must not contain one another")
        if _is_within(self.backup_root, target):
            raise DeploymentError("Backup directory must be outside the SD root")

        files: list[tuple[Path, Path, str]] = []
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise DeploymentError(f"Deployment source contains a symbolic link: {path}")
            if path.is_dir():
                continue
            if not path.is_file():
                raise DeploymentError(f"Deployment source contains a special file: {path}")
            relative = path.relative_to(source)
            destination = target / relative
            resolved_destination = destination.resolve(strict=False)
            if not _is_within(resolved_destination, target):
                raise DeploymentError(f"Destination escapes SD root: {relative}")
            if destination.is_symlink():
                raise DeploymentError(f"Refusing to replace destination symlink: {destination}")
            if destination.exists() and not destination.is_file():
                raise DeploymentError(f"Destination is not a regular file: {destination}")
            files.append((path, relative, _sha256(path)))
        if not files:
            raise DeploymentError("Deployment source tree contains no files")

        identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:10]
        transaction = DeploymentTransaction(
            identifier=identifier,
            created_at=_utc_now(),
            source_root=str(source),
            sd_root=str(target),
            backup_root=str(self.backup_root),
            status="preparing",
        )
        transaction.directory.mkdir(parents=True, exist_ok=False)

        created_directories: set[Path] = set()
        try:
            for source_file, relative, source_hash in files:
                destination = target / relative
                if destination.exists():
                    before_hash = _sha256(destination)
                    if before_hash == source_hash:
                        transaction.entries.append(
                            DeploymentEntry(relative.as_posix(), "unchanged", source_hash, before_hash)
                        )
                        continue
                    backup_relative = Path("files") / relative
                    backup = transaction.directory / backup_relative
                    _copy_atomic(destination, backup, before_hash)
                    transaction.entries.append(
                        DeploymentEntry(
                            relative.as_posix(),
                            "replace",
                            source_hash,
                            before_hash,
                            backup_relative.as_posix(),
                        )
                    )
                else:
                    parent = destination.parent
                    while parent != target and not parent.exists():
                        created_directories.add(parent.relative_to(target))
                        parent = parent.parent
                    transaction.entries.append(
                        DeploymentEntry(relative.as_posix(), "create", source_hash)
                    )

            transaction.created_directories = [
                path.as_posix() for path in sorted(created_directories, key=lambda item: len(item.parts))
            ]
            transaction.status = "prepared"
            transaction.save()

            source_by_relative = {relative.as_posix(): source_file for source_file, relative, _ in files}
            for entry in transaction.entries:
                if entry.action == "unchanged":
                    continue
                relative = _safe_relative(entry.path)
                destination = target / relative
                entry.applied = True
                transaction.status = "applying"
                transaction.save()
                _copy_atomic(source_by_relative[entry.path], destination, entry.source_sha256)
            transaction.status = "complete"
            transaction.save()
            return transaction
        except BaseException as error:
            transaction.status = "failed"
            try:
                transaction.save()
                self.rollback(transaction, force=True)
            except BaseException as rollback_error:
                raise DeploymentError(
                    f"Deployment failed ({error}); automatic rollback also failed ({rollback_error}). "
                    f"Transaction: {transaction.manifest_path}"
                ) from error
            if isinstance(error, DeploymentError):
                raise
            raise DeploymentError(f"Deployment failed and was rolled back: {error}") from error

    def rollback(
        self,
        transaction: DeploymentTransaction | str | os.PathLike[str],
        *,
        force: bool = False,
    ) -> DeploymentTransaction:
        current = (
            transaction
            if isinstance(transaction, DeploymentTransaction)
            else DeploymentTransaction.load(transaction)
        )
        target = Path(current.sd_root).resolve()
        if not target.is_dir():
            raise DeploymentError(f"Recorded SD root is unavailable: {target}")
        if current.status == "rolled_back":
            return current

        applied = [entry for entry in current.entries if entry.applied and entry.action != "unchanged"]
        # Validate every path and conflict before changing anything.
        for entry in applied:
            relative = _safe_relative(entry.path)
            destination = target / relative
            if not _is_within(destination.resolve(strict=False), target):
                raise DeploymentError(f"Recorded path escapes SD root: {entry.path}")
            if destination.is_symlink() or (destination.exists() and not destination.is_file()):
                raise DeploymentConflict(f"Destination type changed after deployment: {destination}")
            if not force:
                if not destination.exists():
                    if entry.action == "replace":
                        raise DeploymentConflict(f"Replaced file was removed after deployment: {destination}")
                elif _sha256(destination) != entry.source_sha256:
                    raise DeploymentConflict(f"File changed after deployment: {destination}")
            if entry.action == "replace":
                if not entry.backup_path or not entry.before_sha256:
                    raise DeploymentError(f"Replacement has no valid backup: {entry.path}")
                backup = current.directory / _safe_relative(entry.backup_path)
                if not backup.is_file() or _sha256(backup) != entry.before_sha256:
                    raise DeploymentError(f"Backup is missing or corrupt: {backup}")

        current.status = "rolling_back"
        current.save()
        for entry in reversed(applied):
            destination = target / _safe_relative(entry.path)
            if entry.action == "replace":
                backup = current.directory / _safe_relative(entry.backup_path or "")
                _copy_atomic(backup, destination, entry.before_sha256)
            elif entry.action == "create":
                if destination.exists():
                    destination.unlink()
            entry.applied = False
            current.save()

        for text in sorted(current.created_directories, key=lambda item: len(Path(item).parts), reverse=True):
            directory = target / _safe_relative(text)
            if _is_within(directory.resolve(strict=False), target):
                try:
                    directory.rmdir()
                except OSError:
                    pass
        current.status = "rolled_back"
        current.save()
        return current

    def recent_transactions(self, limit: int = 20) -> list[DeploymentTransaction]:
        if limit < 0:
            raise DeploymentError("Transaction limit cannot be negative")
        if not self.backup_root.is_dir():
            return []
        transactions: list[DeploymentTransaction] = []
        for directory in sorted(self.backup_root.iterdir(), reverse=True):
            if not directory.is_dir() or not (directory / "transaction.json").is_file():
                continue
            try:
                transactions.append(DeploymentTransaction.load(directory))
            except DeploymentError:
                continue
            if len(transactions) >= limit:
                break
        return transactions
