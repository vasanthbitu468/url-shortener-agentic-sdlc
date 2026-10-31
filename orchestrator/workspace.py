"""Sandboxed workspace for agents.

Agents never edit the real repository. Each run copies the relevant parts of the repo into
``baseline/`` (read-only reference) and ``workspace/`` (what agents change). Edits are
validated against the stage's allowed paths, checkpoints make rollback cheap, and the final
deliverable is a git-applicable patch of workspace vs baseline.
"""

from __future__ import annotations

import difflib
import os
import py_compile
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from orchestrator.models import PolicyViolation

# What gets copied from the repo into a run.
INCLUDE = ("service", "tests", "scripts", "docs", "pyproject.toml", "README.md")
IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache", "*.db", ".coverage", "*.egg-info"
)


@dataclass(frozen=True)
class Edit:
    path: str
    action: str  # "create" | "replace" | "delete"
    content: str = ""
    find: str = ""
    replace: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> Edit:
        return cls(
            path=raw["path"],
            action=raw.get("action", "create"),
            content=raw.get("content", ""),
            find=raw.get("find", ""),
            replace=raw.get("replace", ""),
        )


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _safe_relpath(path: str) -> PurePosixPath:
    p = PurePosixPath(path.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise PolicyViolation(f"path escapes the workspace: {path!r}")
    return p


def _in_scope(rel: PurePosixPath, allowed: tuple[str, ...]) -> bool:
    s = str(rel)
    return any(s == a.rstrip("/") or s.startswith(a.rstrip("/") + "/") for a in allowed)


class Workspace:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.baseline = run_dir / "baseline"
        self.root = run_dir / "workspace"
        self.checkpoints = run_dir / "checkpoints"

    # ---- lifecycle ----------------------------------------------------------------------

    def create_from(self, repo_root: Path) -> None:
        for target in (self.baseline, self.root):
            target.mkdir(parents=True, exist_ok=True)
            for name in INCLUDE:
                src = repo_root / name
                if src.is_dir():
                    shutil.copytree(src, target / name, ignore=IGNORE, dirs_exist_ok=True)
                elif src.is_file():
                    shutil.copy2(src, target / name)

    def checkpoint(self, label: str) -> str:
        dest = self.checkpoints / label
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(self.root, dest, ignore=IGNORE)
        return label

    def restore(self, label: str, scopes: tuple[str, ...] | None = None) -> None:
        """Roll the workspace (or only ``scopes`` within it) back to a checkpoint."""
        snap = self.checkpoints / label
        if not snap.exists():
            raise FileNotFoundError(f"checkpoint {label!r} not found")
        targets = scopes or tuple(p.name for p in self.root.iterdir()) + tuple(
            p.name for p in snap.iterdir()
        )
        for scope in sorted(set(targets)):
            live, saved = self.root / scope, snap / scope
            if live.is_dir():
                shutil.rmtree(live)
            elif live.exists():
                live.unlink()
            if saved.is_dir():
                shutil.copytree(saved, live)
            elif saved.exists():
                live.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(saved, live)

    # ---- edits --------------------------------------------------------------------------

    def apply(self, edits: list[Edit], allowed: tuple[str, ...]) -> list[str]:
        """Apply edits atomically (all or nothing). Returns the changed paths."""
        planned: dict[Path, str | None] = {}
        for e in edits:
            rel = _safe_relpath(e.path)
            if not _in_scope(rel, allowed):
                raise PolicyViolation(
                    f"edit to {e.path!r} is outside this stage's allowed paths {list(allowed)}"
                )
            target = self.root / rel
            if e.action == "create":
                planned[target] = e.content
            elif e.action == "delete":
                planned[target] = None
            elif e.action == "replace":
                current = planned.get(target)
                if current is None:
                    if not target.exists():
                        raise ValueError(f"cannot edit missing file {e.path!r}")
                    current = target.read_text(encoding="utf-8")
                count = current.count(e.find)
                if not e.find or count != 1:
                    raise ValueError(
                        f"edit to {e.path!r}: text to replace must match exactly once "
                        f"(found {count} times)"
                    )
                planned[target] = current.replace(e.find, e.replace)
            else:
                raise ValueError(f"unknown edit action {e.action!r}")

        for target, content in planned.items():
            if content is None:
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8", newline="\n")
        return sorted(str(t.relative_to(self.root).as_posix()) for t in planned)

    def compile_check(self, paths: list[str]) -> list[str]:
        errors = []
        for p in paths:
            f = self.root / p
            if f.suffix == ".py" and f.exists():
                try:
                    py_compile.compile(str(f), doraise=True)
                except py_compile.PyCompileError as exc:
                    errors.append(f"{p}: {exc.msg.strip()}")
        return errors

    def read(self, path: str) -> str:
        return (self.root / _safe_relpath(path)).read_text(encoding="utf-8")

    def list_files(self, under: str = "") -> list[str]:
        base = self.root / under if under else self.root
        return sorted(
            p.relative_to(self.root).as_posix()
            for p in base.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )

    # ---- tools --------------------------------------------------------------------------

    def run(self, args: list[str], timeout: float = 600) -> CommandResult:
        """Run a command inside the workspace with the workspace first on the import path."""
        env = {**os.environ, "PYTHONPATH": str(self.root), "PYTHONDONTWRITEBYTECODE": "1"}
        env.pop("APP_DATABASE_URL", None)
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argument lists, no shell
                args,
                cwd=self.root,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(124, f"timed out after {timeout}s")
        return CommandResult(proc.returncode, (proc.stdout + proc.stderr)[-6000:])

    def python(self, *args: str, timeout: float = 600) -> CommandResult:
        return self.run([sys.executable, *args], timeout=timeout)

    # ---- diff ---------------------------------------------------------------------------

    def changed_files(self) -> dict[str, str]:
        """path -> 'added' | 'modified' | 'deleted'"""
        before = {p: self.baseline / p for p in self._files(self.baseline)}
        after = {p: self.root / p for p in self._files(self.root)}
        changes: dict[str, str] = {}
        for p in sorted(set(before) | set(after)):
            if p not in before:
                changes[p] = "added"
            elif p not in after:
                changes[p] = "deleted"
            elif before[p].read_bytes() != after[p].read_bytes():
                changes[p] = "modified"
        return changes

    def diff(self) -> str:
        """Unified diff of workspace vs baseline, applicable with ``git apply``."""
        chunks: list[str] = []
        for path, kind in self.changed_files().items():
            old = [] if kind == "added" else self._lines(self.baseline / path)
            new = [] if kind == "deleted" else self._lines(self.root / path)
            header = [f"diff --git a/{path} b/{path}\n"]
            if kind == "added":
                header.append("new file mode 100644\n")
            elif kind == "deleted":
                header.append("deleted file mode 100644\n")
            body = difflib.unified_diff(
                old,
                new,
                fromfile="/dev/null" if kind == "added" else f"a/{path}",
                tofile="/dev/null" if kind == "deleted" else f"b/{path}",
            )
            chunks.extend(header)
            for line in body:
                chunks.append(
                    line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                )
        return "".join(chunks)

    @staticmethod
    def _files(root: Path) -> list[str]:
        if not root.exists():
            return []
        return [
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        ]

    @staticmethod
    def _lines(path: Path) -> list[str]:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
