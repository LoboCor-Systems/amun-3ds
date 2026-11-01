"""AMUN source-profile compiler and host-side format tooling."""

from .diagnostics import Diagnostic, DiagnosticReport
from .pack import CompiledPack, PackError, compile_profile, inspect_pack, write_pack
from .profile import LoadedProfile, load_profile, validate_profile

__all__ = [
    "CompiledPack",
    "Diagnostic",
    "DiagnosticReport",
    "LoadedProfile",
    "PackError",
    "compile_profile",
    "inspect_pack",
    "load_profile",
    "validate_profile",
    "write_pack",
]

__version__ = "0.1.0"
