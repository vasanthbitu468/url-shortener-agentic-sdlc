"""Policy guardrails for security, compliance and change control.

Each rule inspects the run's change set and returns findings. Severity decides the effect:
    block     the review gate fails; the engine rolls back and sends work back for rework
    approval  allowed only with an explicit human approval at release
    warn      recorded in the audit log and the summary
Rules are plain functions so they are easy to read, test and extend.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from orchestrator.workspace import Workspace

BLOCK, APPROVAL, WARN = "block", "approval", "warn"

SECRET_PATTERNS = {
    "api key": re.compile(r"\b(sk|pk|rk)[-_](live|test|proj)?[-_]?[A-Za-z0-9]{16,}"),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "hard-coded credential": re.compile(
        r"""(?i)\b(password|passwd|secret|api_?key|token)\s*=\s*["'][^"'\s]{8,}["']"""
    ),
}
PII_PATTERNS = {
    "raw client IP stored": re.compile(
        r"(\.add\(|Column|mapped_column|\bip\s*=).*request\.client\.host"
        r"|request\.client\.host.*(Column|mapped_column|\.add\()"
    ),
}
PROTECTED_PATHS = (".github/", "orchestrator/", "scenarios/", ".env")
DEPENDENCY_FILES = ("pyproject.toml", "requirements.txt")
MAX_CHANGED_LINES = 800


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class ChangeSet:
    changed: dict[str, str]  # path -> added/modified/deleted
    added_lines: dict[str, list[str]]  # path -> lines added by the change
    diff_lines: int
    design: dict[str, Any]


def collect_changes(ws: Workspace, design: dict[str, Any] | None) -> ChangeSet:
    diff = ws.diff()
    added: dict[str, list[str]] = {}
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif current and line.startswith("+") and not line.startswith("+++"):
            added.setdefault(current, []).append(line[1:])
    diff_lines = sum(
        1 for line in diff.splitlines() if line[:1] in "+-" and line[:3] not in ("+++", "---")
    )
    return ChangeSet(ws.changed_files(), added, diff_lines, design or {})


# ---- rules ------------------------------------------------------------------------------


def no_secrets(cs: ChangeSet) -> list[Finding]:
    out = []
    for path, lines in cs.added_lines.items():
        for line in lines:
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(line):
                    out.append(Finding("security.no_secrets", BLOCK, f"possible {label}", path))
    return out


def no_pii(cs: ChangeSet) -> list[Finding]:
    out = []
    for path, lines in cs.added_lines.items():
        for line in lines:
            for label, pattern in PII_PATTERNS.items():
                if pattern.search(line):
                    out.append(Finding("compliance.no_pii", BLOCK, label, path))
    return out


def protected_paths(cs: ChangeSet) -> list[Finding]:
    return [
        Finding("change_control.protected_paths", BLOCK, "agents may not modify this path", p)
        for p in cs.changed
        if any(p == pp.rstrip("/") or p.startswith(pp) for pp in PROTECTED_PATHS)
    ]


def dependency_changes(cs: ChangeSet) -> list[Finding]:
    return [
        Finding("change_control.dependencies", APPROVAL, "dependency manifest changed", p)
        for p in cs.changed
        if p in DEPENDENCY_FILES
    ]


def diff_size(cs: ChangeSet) -> list[Finding]:
    if cs.diff_lines > MAX_CHANGED_LINES:
        return [
            Finding(
                "change_control.diff_size",
                BLOCK,
                f"{cs.diff_lines} changed lines exceeds limit of {MAX_CHANGED_LINES}",
            )
        ]
    return []


def api_change_declared(cs: ChangeSet) -> list[Finding]:
    contract_changed = "service/openapi.json" in cs.changed
    declared = bool(cs.design.get("api_changes"))
    if contract_changed and not declared:
        return [
            Finding(
                "change_control.api_contract",
                BLOCK,
                "public API changed but the approved design declared no API change",
                "service/openapi.json",
            )
        ]
    if declared and not contract_changed:
        return [
            Finding(
                "change_control.api_contract",
                WARN,
                "design declared an API change but service/openapi.json was not regenerated",
            )
        ]
    return []


def schema_change_declared(cs: ChangeSet) -> list[Finding]:
    touched = "service/db/models.py" in cs.changed
    if touched and not cs.design.get("data_model_changes"):
        return [
            Finding(
                "change_control.schema",
                BLOCK,
                "database models changed but the approved design declared no schema change",
                "service/db/models.py",
            )
        ]
    if touched:
        return [
            Finding(
                "change_control.schema", APPROVAL, "database schema change", "service/db/models.py"
            )
        ]
    return []


def tests_accompany_code(cs: ChangeSet) -> list[Finding]:
    code = [p for p in cs.changed if p.startswith("service/") and p.endswith(".py")]
    tests = [p for p in cs.changed if p.startswith("tests/")]
    if code and not tests:
        return [Finding("quality.tests_required", BLOCK, "code changed without test changes")]
    return []


RULES: list[Callable[[ChangeSet], list[Finding]]] = [
    no_secrets,
    no_pii,
    protected_paths,
    dependency_changes,
    diff_size,
    api_change_declared,
    schema_change_declared,
    tests_accompany_code,
]


def evaluate(cs: ChangeSet) -> list[Finding]:
    findings: list[Finding] = []
    for rule in RULES:
        findings.extend(rule(cs))
    return findings
