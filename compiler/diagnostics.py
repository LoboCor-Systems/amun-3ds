"""Structured, stable diagnostics shared by validation and compilation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable


@dataclass(frozen=True, order=True)
class Diagnostic:
    severity: str
    code: str
    path: str
    message: str
    hint: str = ""

    def __post_init__(self) -> None:
        if self.severity not in {"error", "warning", "info"}:
            raise ValueError(f"invalid diagnostic severity: {self.severity}")

    def to_dict(self) -> dict[str, str]:
        value = {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }
        if self.hint:
            value["hint"] = self.hint
        return value

    def format(self) -> str:
        location = f" {self.path}" if self.path else ""
        line = f"{self.severity}: {self.code}{location}: {self.message}"
        return f"{line}\n  hint: {self.hint}" if self.hint else line


class DiagnosticReport:
    def __init__(self, diagnostics: Iterable[Diagnostic] = ()) -> None:
        self.diagnostics = list(diagnostics)

    def add(
        self,
        severity: str,
        code: str,
        path: str,
        message: str,
        hint: str = "",
    ) -> None:
        self.diagnostics.append(Diagnostic(severity, code, path, message, hint))

    def error(self, code: str, path: str, message: str, hint: str = "") -> None:
        self.add("error", code, path, message, hint)

    def warning(self, code: str, path: str, message: str, hint: str = "") -> None:
        self.add("warning", code, path, message, hint)

    def info(self, code: str, path: str, message: str, hint: str = "") -> None:
        self.add("info", code, path, message, hint)

    def extend(self, other: "DiagnosticReport" | Iterable[Diagnostic]) -> None:
        self.diagnostics.extend(other.diagnostics if isinstance(other, DiagnosticReport) else other)

    @property
    def errors(self) -> list[Diagnostic]:
        return [item for item in self.diagnostics if item.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [item for item in self.diagnostics if item.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "errorCount": len(self.errors),
            "warningCount": len(self.warnings),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def format(self) -> str:
        if not self.diagnostics:
            return "validation passed with no diagnostics"
        body = "\n".join(item.format() for item in self.diagnostics)
        summary = f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)"
        return f"{body}\n{summary}"


class CompilationFailed(ValueError):
    def __init__(self, report: DiagnosticReport) -> None:
        self.report = report
        super().__init__(report.format())
