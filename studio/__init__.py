"""AMUN Studio desktop authoring and offline memory research tools.

The package deliberately depends only on Python's standard library.  The GUI
is available through ``python -m studio``; the data-model modules are usable in
headless tests and scripts.
"""

from .cli import CliHooks, CliResult, StudioSettings
from .deployment import DeploymentTransaction, SdCandidate, SdDeployer, detect_sd_cards
from .library import (
    InvalidPack,
    LibraryConflict,
    LibraryEntry,
    LibraryError,
    PackBuild,
    PackSummary,
    ProfileLibrary,
)
from .project import ProfileProject, ProjectError
from .scanner import MemorySnapshot, ScanError, ScanResult, SnapshotScanner, VALUE_TYPES

__all__ = [
    "CliHooks",
    "CliResult",
    "DeploymentTransaction",
    "InvalidPack",
    "LibraryConflict",
    "LibraryEntry",
    "LibraryError",
    "MemorySnapshot",
    "PackBuild",
    "PackSummary",
    "ProfileProject",
    "ProfileLibrary",
    "ProjectError",
    "ScanError",
    "ScanResult",
    "SdCandidate",
    "SdDeployer",
    "SnapshotScanner",
    "StudioSettings",
    "VALUE_TYPES",
    "detect_sd_cards",
]

__version__ = "0.1.0"
