#!/usr/bin/env python3
"""Read-only project inventory and dependency-version resolver for API Reality Guard.

Two modes, deliberately separated:

* **Inventory (default).** Walks the tree, records filenames only. No file
  contents are opened, no project code is executed, no network is used.
* **Resolution (``--package``).** Additionally reads *allowlisted metadata
  files only* (manifests and lockfiles) to report the declared range and the
  resolved version of a named dependency. Source files are still never read.

The second mode exists because "which version is actually installed?" is the
central question of the skill, and a filename-only inventory cannot answer it.
The read is bounded, allowlisted, symlink-refusing, and labelled with its
confidence so a best-effort extraction is never presented as authoritative.

Standard library only. Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

TOOL_NAME = "api-reality-guard"
TOOL_VERSION = "1.0.0"
SCHEMA_VERSION = 2

DEFAULT_MAX_FILES = 20_000
DEFAULT_MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_RUNTIME_MARKER_BYTES = 4096
MAX_TEXT_LINES = 200_000

try:  # Python 3.11+
    import tomllib as _toml  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - exercised on 3.9/3.10 only
    _toml = None

IGNORED_DIRECTORIES = frozenset(
    {
        ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
        "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
        ".idea", ".vscode", "target", "dist", "build", "out", "coverage",
        ".next", ".nuxt", ".turbo", "vendor", "site-packages", ".eggs",
        ".gradle", ".cargo", "Pods", "DerivedData",
    }
)

#: filename -> (ecosystem, kind, authority)
#: ``authority`` is the field the skill's rule 2 depends on: a lockfile records
#: what was resolved, a manifest records only what was requested.
MARKERS: Dict[str, Tuple[str, str, str]] = {
    "pyproject.toml": ("Python", "Project metadata and dependencies", "manifest"),
    "setup.py": ("Python", "Build and package metadata", "manifest"),
    "setup.cfg": ("Python", "Project configuration", "manifest"),
    "pipfile": ("Python", "Dependency manifest", "manifest"),
    "pipfile.lock": ("Python", "Dependency lockfile", "lockfile"),
    "poetry.lock": ("Python", "Dependency lockfile", "lockfile"),
    "uv.lock": ("Python", "Dependency lockfile", "lockfile"),
    "pylock.toml": ("Python", "Dependency lockfile", "lockfile"),
    "environment.yml": ("Python / Conda", "Environment manifest", "manifest"),
    "conda.yaml": ("Python / Conda", "Environment manifest", "manifest"),
    "package.json": ("JavaScript / TypeScript", "Package manifest", "manifest"),
    "package-lock.json": ("JavaScript / TypeScript", "Dependency lockfile", "lockfile"),
    "npm-shrinkwrap.json": ("JavaScript / TypeScript", "Dependency lockfile", "lockfile"),
    "pnpm-lock.yaml": ("JavaScript / TypeScript", "Dependency lockfile", "lockfile"),
    "yarn.lock": ("JavaScript / TypeScript", "Dependency lockfile", "lockfile"),
    "bun.lock": ("JavaScript / TypeScript", "Dependency lockfile", "lockfile"),
    "bun.lockb": ("JavaScript / TypeScript", "Dependency lockfile", "lockfile"),
    "tsconfig.json": ("JavaScript / TypeScript", "Compiler configuration", "tooling"),
    "cargo.toml": ("Rust", "Package manifest", "manifest"),
    "cargo.lock": ("Rust", "Dependency lockfile", "lockfile"),
    "go.mod": ("Go", "Module manifest", "manifest"),
    "go.sum": ("Go", "Dependency checksums", "lockfile"),
    "go.work": ("Go", "Workspace manifest", "manifest"),
    "go.work.sum": ("Go", "Workspace checksums", "lockfile"),
    "pom.xml": ("Java / Kotlin", "Maven project manifest", "manifest"),
    "build.gradle": ("Java / Kotlin", "Gradle build file", "manifest"),
    "build.gradle.kts": ("Java / Kotlin", "Gradle Kotlin build file", "manifest"),
    "settings.gradle": ("Java / Kotlin", "Gradle settings", "tooling"),
    "settings.gradle.kts": ("Java / Kotlin", "Gradle Kotlin settings", "tooling"),
    "gradle.lockfile": ("Java / Kotlin", "Dependency lockfile", "lockfile"),
    "directory.packages.props": (".NET", "Central package versions", "manifest"),
    "packages.lock.json": (".NET", "Dependency lockfile", "lockfile"),
    "global.json": (".NET", "SDK selection file", "tooling"),
    "nuget.config": (".NET", "Package source configuration", "tooling"),
    "composer.json": ("PHP", "Package manifest", "manifest"),
    "composer.lock": ("PHP", "Dependency lockfile", "lockfile"),
    "gemfile": ("Ruby", "Dependency manifest", "manifest"),
    "gemfile.lock": ("Ruby", "Dependency lockfile", "lockfile"),
    "package.swift": ("Swift", "Package manifest", "manifest"),
    "package.resolved": ("Swift", "Dependency resolution file", "lockfile"),
    "pubspec.yaml": ("Dart / Flutter", "Package manifest", "manifest"),
    "pubspec.lock": ("Dart / Flutter", "Dependency lockfile", "lockfile"),
    "mix.exs": ("Elixir", "Project manifest", "manifest"),
    "mix.lock": ("Elixir", "Dependency lockfile", "lockfile"),
    "renv.lock": ("R", "Dependency lockfile", "lockfile"),
    "build.sbt": ("Scala", "SBT build file", "manifest"),
    "docker-compose.yml": ("Docker", "Compose configuration", "tooling"),
    "docker-compose.yaml": ("Docker", "Compose configuration", "tooling"),
    "compose.yml": ("Docker", "Compose configuration", "tooling"),
    "compose.yaml": ("Docker", "Compose configuration", "tooling"),
    "makefile": ("Build tooling", "Make build file", "tooling"),
}

#: Files whose *content* is a runtime version declaration. These answer half of
#: every compatibility question and were missing from the original inventory.
RUNTIME_MARKERS: Dict[str, str] = {
    ".python-version": "Python runtime version",
    ".nvmrc": "Node runtime version",
    ".node-version": "Node runtime version",
    ".ruby-version": "Ruby runtime version",
    ".go-version": "Go runtime version",
    ".tool-versions": "asdf tool versions",
    ".sdkmanrc": "SDKMAN tool versions",
    "rust-toolchain.toml": "Rust toolchain channel",
    "rust-toolchain": "Rust toolchain channel",
    "mise.toml": "mise tool versions",
    ".mise.toml": "mise tool versions",
}

SOURCE_EXTENSIONS = frozenset(
    {
        ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
        ".vue", ".svelte", ".rs", ".go", ".java", ".kt", ".kts", ".cs",
        ".fs", ".php", ".rb", ".swift", ".dart", ".c", ".h", ".cc",
        ".cpp", ".hpp", ".hh", ".sql", ".sh", ".ps1", ".ex", ".exs",
        ".scala", ".sc", ".r", ".R", ".html", ".css", ".scss", ".less",
    }
)

LIMITATIONS = [
    "Inventory mode reads filenames only; resolution mode additionally reads allowlisted manifests and lockfiles, never source files.",
    "Neither mode proves API signatures or runtime behavior. A version is not a contract.",
    "Best-effort extractions are labelled; treat them as a lead to confirm with the ecosystem's own tooling.",
    "Generated, cache, build and vendor directories are skipped, so a result may omit files inside them.",
    "If scan_complete is false, the inventory is incomplete: rerun with a higher --max-files or fix the reported unreadable paths.",
]


# --------------------------------------------------------------------------
# Filesystem helpers
# --------------------------------------------------------------------------


def _is_regular_file(path: Path) -> bool:
    """True only for regular files, without following symlinks."""
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode)


def _read_metadata(path: Path, limit: int) -> Tuple[Optional[str], Optional[str]]:
    """Read a metadata file safely.

    Returns ``(text, None)`` on success and ``(None, reason)`` on refusal.
    Refusals are reported, never silently skipped: a missing file must not look
    like a file that was checked and found empty.
    """
    if path.is_symlink():
        return None, "symlink"
    if not _is_regular_file(path):
        return None, "not a regular file"
    try:
        size = os.lstat(path).st_size
    except OSError as exc:
        return None, "stat failed: {}".format(exc.strerror or exc)
    if size > limit:
        return None, "exceeds {} bytes".format(limit)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit + 1), None
    except OSError as exc:
        return None, "read failed: {}".format(exc.strerror or exc)


def _first_version_token(text: str) -> Optional[str]:
    match = re.search(r"\d+(?:\.\d+)*", text)
    return match.group(0) if match else None


def classify_marker(filename: str) -> Optional[Tuple[str, str, str]]:
    """Return (ecosystem, kind, authority) for a recognised project marker."""
    lower_name = filename.lower()

    if lower_name in MARKERS:
        return MARKERS[lower_name]
    if lower_name.startswith("requirements") and lower_name.endswith(".txt"):
        return ("Python", "Requirements file", "manifest")
    if lower_name.startswith("dockerfile"):
        return ("Docker", "Container build file", "tooling")
    if lower_name.endswith((".csproj", ".fsproj", ".vbproj")):
        return (".NET", "Project file", "manifest")
    if lower_name.endswith((".sln", ".slnx")):
        return (".NET", "Solution file", "tooling")
    if lower_name.endswith((".xcworkspace", ".xcodeproj")):
        return ("Apple platform", "IDE project marker", "tooling")
    return None


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------


def _walk(
    root: Path, max_files: int
) -> Tuple[List[Tuple[str, str]], int, bool, List[Dict[str, str]]]:
    """Walk the tree, collecting (relative_path, filename) and any errors."""
    entries: List[Tuple[str, str]] = []
    errors: List[Dict[str, str]] = []
    files_scanned = 0
    truncated = False

    def on_error(exc: OSError) -> None:
        # os.walk swallows these by default, which would let the report claim
        # completeness while having skipped an entire subtree.
        location = getattr(exc, "filename", None) or "<unknown>"
        try:
            relative = Path(location).relative_to(root).as_posix()
        except (ValueError, TypeError):
            relative = str(location)
        errors.append({"path": relative, "reason": exc.strerror or str(exc)})

    for current_dir, dirnames, filenames in os.walk(
        root, topdown=True, followlinks=False, onerror=on_error
    ):
        current_path = Path(current_dir)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name.lower() not in IGNORED_DIRECTORIES
            and not (current_path / name).is_symlink()
        )

        for filename in sorted(filenames):
            full_path = current_path / filename
            if full_path.is_symlink() or not _is_regular_file(full_path):
                continue
            if files_scanned >= max_files:
                truncated = True
                break
            files_scanned += 1
            entries.append((full_path.relative_to(root).as_posix(), filename))

        if truncated:
            break

    return entries, files_scanned, truncated, errors


def inspect_project(
    root: Path,
    max_files: int = DEFAULT_MAX_FILES,
    label: Optional[str] = None,
    packages: Sequence[str] = (),
    max_metadata_bytes: int = DEFAULT_MAX_METADATA_BYTES,
) -> Dict[str, Any]:
    """Return a deterministic, read-only inventory of the project tree."""
    if max_files < 1:
        raise ValueError("max_files must be at least 1")
    if max_metadata_bytes < 1:
        raise ValueError("max_metadata_bytes must be at least 1")

    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("root must be a directory")

    entries, files_scanned, truncated, scan_errors = _walk(root, max_files)

    markers: List[Dict[str, Any]] = []
    runtime_markers: List[Dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    metadata_paths: List[Tuple[str, str]] = []

    for relative_path, filename in entries:
        marker = classify_marker(filename)
        if marker is not None:
            ecosystem, kind, authority = marker
            markers.append(
                {
                    "path": relative_path,
                    "ecosystem": ecosystem,
                    "kind": kind,
                    "authority": authority,
                    "is_lockfile": authority == "lockfile",
                }
            )
            metadata_paths.append((relative_path, filename))

        runtime_kind = RUNTIME_MARKERS.get(filename.lower())
        if runtime_kind is not None:
            text, error = _read_metadata(root / relative_path, MAX_RUNTIME_MARKER_BYTES)
            runtime_markers.append(
                {
                    "path": relative_path,
                    "kind": runtime_kind,
                    "value": _first_version_token(text) if text else None,
                    "raw_first_line": (text.splitlines()[0].strip()[:160] if text and text.splitlines() else None),
                    "error": error,
                }
            )

        suffix = Path(filename).suffix
        if suffix and suffix.lower() in SOURCE_EXTENSIONS:
            source_counts[suffix.lower()] += 1

    markers.sort(key=lambda item: (item["path"].lower(), item["ecosystem"].lower()))
    runtime_markers.sort(key=lambda item: item["path"].lower())

    ecosystem_markers: Dict[str, List[str]] = defaultdict(list)
    for marker in markers:
        ecosystem_markers[marker["ecosystem"]].append(marker["path"])

    ecosystems = [
        {"name": name, "marker_paths": sorted(paths)}
        for name, paths in sorted(ecosystem_markers.items(), key=lambda item: item[0].lower())
    ]

    resolution: List[Dict[str, Any]] = []
    resolution_errors: List[Dict[str, str]] = []
    if packages:
        resolution, resolution_errors = _resolve_packages(
            root, metadata_paths, packages, max_metadata_bytes
        )

    return {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "root": label if label is not None else str(root),
        "files_scanned": files_scanned,
        "max_files": max_files,
        "scan_truncated": truncated,
        "scan_complete": not truncated and not scan_errors,
        "scan_errors": sorted(scan_errors, key=lambda item: item["path"]),
        "ignored_directories": sorted(IGNORED_DIRECTORIES),
        "manifests": markers,
        "runtime_markers": runtime_markers,
        "ecosystems": ecosystems,
        "source_file_counts": dict(sorted(source_counts.items())),
        "resolution": resolution,
        "resolution_errors": sorted(resolution_errors, key=lambda item: item["path"]),
        "resolution_supported_formats": sorted(SUPPORTED_FORMATS),
        "toml_parser_available": _toml is not None,
        "limitations": LIMITATIONS,
    }


# --------------------------------------------------------------------------
# Version resolution
# --------------------------------------------------------------------------

SUPPORTED_FORMATS = frozenset(
    {
        "package-lock.json", "package.json", "yarn.lock", "pnpm-lock.yaml",
        "requirements.txt", "Pipfile.lock", "poetry.lock", "uv.lock",
        "pyproject.toml", "Cargo.lock", "Cargo.toml", "go.mod",
        "composer.json", "composer.lock", "Gemfile.lock", "pubspec.lock",
    }
)

_PEP503 = re.compile(r"[-_.]+")


def _norm(name: str, ecosystem: str) -> str:
    lowered = name.strip().lower()
    if ecosystem.startswith("Python"):
        return _PEP503.sub("-", lowered)
    return lowered


def _record(
    package: str,
    version: Optional[str],
    constraint: Optional[str],
    source_path: str,
    source_format: str,
    authority: str,
    confidence: str,
    line: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "package": package,
        "version": version,
        "constraint": constraint,
        "source_path": source_path,
        "source_format": source_format,
        "authority": authority,
        "confidence": confidence,
        "line": line,
    }


def _wanted(candidate: str, targets: Sequence[str], ecosystem: str) -> Optional[str]:
    normalized = _norm(candidate, ecosystem)
    for target in targets:
        if normalized == _norm(target, ecosystem):
            return target
        if ecosystem == "Go" and normalized.endswith("/" + _norm(target, "Go")):
            return target
    return None


def _parse_requirements(text: str, path: str, targets: Sequence[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    pattern = re.compile(
        r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(==|>=|<=|~=|!=|>|<)?\s*([^\s;#]*)"
    )
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith(("#", "-")):
            continue
        match = pattern.match(line)
        if not match:
            continue
        matched_target = _wanted(match.group(1), targets, "Python")
        if matched_target is None:
            continue
        operator = match.group(3) or ""
        version = match.group(4) or ""
        exact = operator == "==" and version
        out.append(
            _record(
                matched_target,
                version if exact else None,
                None if exact else (operator + version if operator else None),
                path,
                "requirements",
                "resolved" if exact else "declared",
                "exact" if exact else "declared",
                number,
            )
        )
    return out


def _parse_json_format(
    text: str, path: str, targets: Sequence[str], fmt: str
) -> List[Dict[str, Any]]:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []

    out: List[Dict[str, Any]] = []

    if fmt == "package-lock":
        packages = data.get("packages")
        if isinstance(packages, dict):
            for key, meta in packages.items():
                if not isinstance(meta, dict):
                    continue
                marker = "node_modules/"
                if marker not in key:
                    continue
                name = key.rsplit(marker, 1)[1]
                matched = _wanted(name, targets, "JavaScript / TypeScript")
                if matched is None:
                    continue
                out.append(
                    _record(matched, str(meta.get("version") or "") or None, None,
                            path, fmt, "resolved", "exact")
                )
        dependencies = data.get("dependencies")
        if isinstance(dependencies, dict):
            for name, meta in dependencies.items():
                if not isinstance(meta, dict):
                    continue
                matched = _wanted(name, targets, "JavaScript / TypeScript")
                if matched is None:
                    continue
                out.append(
                    _record(matched, str(meta.get("version") or "") or None, None,
                            path, fmt, "resolved", "exact")
                )

    elif fmt == "package-json":
        for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            block = data.get(section)
            if not isinstance(block, dict):
                continue
            for name, constraint in block.items():
                matched = _wanted(name, targets, "JavaScript / TypeScript")
                if matched is None:
                    continue
                out.append(
                    _record(matched, None, str(constraint), path, fmt, "declared", "declared")
                )

    elif fmt == "pipfile-lock":
        for section in ("default", "develop"):
            block = data.get(section)
            if not isinstance(block, dict):
                continue
            for name, meta in block.items():
                matched = _wanted(name, targets, "Python")
                if matched is None:
                    continue
                raw = meta.get("version") if isinstance(meta, dict) else None
                version = raw[2:] if isinstance(raw, str) and raw.startswith("==") else None
                out.append(
                    _record(matched, version, None, path, fmt,
                            "resolved" if version else "declared",
                            "exact" if version else "best_effort")
                )

    elif fmt == "composer-lock":
        for section in ("packages", "packages-dev"):
            block = data.get(section)
            if not isinstance(block, list):
                continue
            for meta in block:
                if not isinstance(meta, dict):
                    continue
                matched = _wanted(str(meta.get("name") or ""), targets, "PHP")
                if matched is None:
                    continue
                out.append(
                    _record(matched, str(meta.get("version") or "") or None, None,
                            path, fmt, "resolved", "exact")
                )

    elif fmt == "composer-json":
        for section in ("require", "require-dev"):
            block = data.get(section)
            if not isinstance(block, dict):
                continue
            for name, constraint in block.items():
                matched = _wanted(name, targets, "PHP")
                if matched is None:
                    continue
                out.append(
                    _record(matched, None, str(constraint), path, fmt, "declared", "declared")
                )

    return out


def _parse_toml_format(
    text: str, path: str, targets: Sequence[str], fmt: str
) -> List[Dict[str, Any]]:
    if _toml is None:
        return _scan_toml_package_blocks(text, path, targets, fmt)

    try:
        data = _toml.loads(text)
    except Exception:  # tomllib raises several types; any failure means fall back
        return _scan_toml_package_blocks(text, path, targets, fmt)

    out: List[Dict[str, Any]] = []

    if fmt in ("poetry-lock", "uv-lock", "cargo-lock"):
        packages = data.get("package")
        if isinstance(packages, list):
            for meta in packages:
                if not isinstance(meta, dict):
                    continue
                ecosystem = "Rust" if fmt == "cargo-lock" else "Python"
                matched = _wanted(str(meta.get("name") or ""), targets, ecosystem)
                if matched is None:
                    continue
                out.append(
                    _record(matched, str(meta.get("version") or "") or None, None,
                            path, fmt, "resolved", "exact")
                )

    elif fmt == "pyproject":
        project = data.get("project")
        if isinstance(project, dict):
            for spec in project.get("dependencies") or []:
                if not isinstance(spec, str):
                    continue
                name = re.split(r"[<>=!~\[;\s]", spec, maxsplit=1)[0]
                matched = _wanted(name, targets, "Python")
                if matched is None:
                    continue
                out.append(_record(matched, None, spec, path, fmt, "declared", "declared"))
        poetry = (data.get("tool") or {}).get("poetry") or {}
        block = poetry.get("dependencies") if isinstance(poetry, dict) else None
        if isinstance(block, dict):
            for name, constraint in block.items():
                matched = _wanted(name, targets, "Python")
                if matched is None:
                    continue
                out.append(
                    _record(matched, None, json.dumps(constraint), path, fmt,
                            "declared", "declared")
                )

    elif fmt == "cargo-toml":
        for section in ("dependencies", "dev-dependencies", "build-dependencies"):
            block = data.get(section)
            if not isinstance(block, dict):
                continue
            for name, constraint in block.items():
                matched = _wanted(name, targets, "Rust")
                if matched is None:
                    continue
                out.append(
                    _record(matched, None, json.dumps(constraint), path, fmt,
                            "declared", "declared")
                )

    return out


def _scan_toml_package_blocks(
    text: str, path: str, targets: Sequence[str], fmt: str
) -> List[Dict[str, Any]]:
    """Line-based fallback for ``[[package]]`` blocks when tomllib is absent.

    Labelled ``best_effort`` on purpose: a hand-rolled reader of a structured
    format is a lead, not an authority.
    """
    ecosystem = "Rust" if fmt == "cargo-lock" else "Python"
    out: List[Dict[str, Any]] = []
    current_name: Optional[str] = None
    current_line = 0

    for number, line in enumerate(text.splitlines()[:MAX_TEXT_LINES], start=1):
        stripped = line.strip()
        if stripped == "[[package]]":
            current_name = None
            continue
        match = re.match(r'^name\s*=\s*"([^"]+)"', stripped)
        if match:
            current_name = match.group(1)
            current_line = number
            continue
        match = re.match(r'^version\s*=\s*"([^"]+)"', stripped)
        if match and current_name:
            matched = _wanted(current_name, targets, ecosystem)
            if matched is not None:
                out.append(
                    _record(matched, match.group(1), None, path, fmt, "resolved", "best_effort")
                )
            current_name = None
    return out


def _parse_go_mod(text: str, path: str, targets: Sequence[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    in_block = False
    for number, line in enumerate(text.splitlines()[:MAX_TEXT_LINES], start=1):
        stripped = line.strip()
        if stripped.startswith("require ("):
            in_block = True
            continue
        if in_block and stripped == ")":
            in_block = False
            continue
        candidate = None
        if in_block:
            candidate = stripped
        elif stripped.startswith("require "):
            candidate = stripped[len("require "):].strip()
        if not candidate:
            continue
        parts = candidate.split()
        if len(parts) < 2:
            continue
        matched = _wanted(parts[0], targets, "Go")
        if matched is None:
            continue
        out.append(
            _record(matched, parts[1].lstrip("v"), None, path, "go.mod", "resolved", "exact", number)
        )
    return out


def _parse_yarn_lock(text: str, path: str, targets: Sequence[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    current: List[str] = []
    for line in text.splitlines()[:MAX_TEXT_LINES]:
        if line and not line.startswith((" ", "\t", "#")):
            current = [spec.strip().strip('"') for spec in line.rstrip(":").split(",")]
            continue
        stripped = line.strip()
        if not stripped.startswith("version"):
            continue
        value = stripped.split(None, 1)[1].strip().strip('"') if " " in stripped else ""
        for spec in current:
            name = spec.split("@")[0] if not spec.startswith("@") else "@" + spec[1:].split("@")[0]
            matched = _wanted(name, targets, "JavaScript / TypeScript")
            if matched is None:
                continue
            out.append(
                _record(matched, value or None, None, path, "yarn.lock", "resolved", "best_effort")
            )
        current = []
    return out


def _parse_pnpm_lock(text: str, path: str, targets: Sequence[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    pattern = re.compile(r"^\s+'?/?((?:@[^/@\s]+/)?[^@\s:']+)@([^:'\s]+)'?:?\s*$")
    for line in text.splitlines()[:MAX_TEXT_LINES]:
        match = pattern.match(line)
        if not match:
            continue
        matched = _wanted(match.group(1), targets, "JavaScript / TypeScript")
        if matched is None:
            continue
        out.append(
            _record(matched, match.group(2), None, path, "pnpm-lock.yaml", "resolved", "best_effort")
        )
    return out


def _parse_gemfile_lock(text: str, path: str, targets: Sequence[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    pattern = re.compile(r"^ {4}([A-Za-z0-9_.-]+) \(([^)]+)\)")
    for number, line in enumerate(text.splitlines()[:MAX_TEXT_LINES], start=1):
        match = pattern.match(line)
        if not match:
            continue
        matched = _wanted(match.group(1), targets, "Ruby")
        if matched is None:
            continue
        out.append(
            _record(matched, match.group(2), None, path, "Gemfile.lock", "resolved", "best_effort", number)
        )
    return out


def _parse_pubspec_lock(text: str, path: str, targets: Sequence[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    current: Optional[str] = None
    for line in text.splitlines()[:MAX_TEXT_LINES]:
        match = re.match(r"^ {2}([A-Za-z0-9_]+):\s*$", line)
        if match:
            current = match.group(1)
            continue
        match = re.match(r'^ {4}version:\s*"?([^"\s]+)"?', line)
        if match and current:
            matched = _wanted(current, targets, "Dart / Flutter")
            if matched is not None:
                out.append(
                    _record(matched, match.group(1), None, path, "pubspec.lock",
                            "resolved", "best_effort")
                )
            current = None
    return out


def _resolve_packages(
    root: Path,
    metadata_paths: Sequence[Tuple[str, str]],
    packages: Sequence[str],
    max_metadata_bytes: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Extract declared and resolved versions for the requested packages."""
    records: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for relative_path, filename in metadata_paths:
        lower_name = filename.lower()
        text, error = _read_metadata(root / relative_path, max_metadata_bytes)
        if text is None:
            if error and error != "exceeds {} bytes".format(max_metadata_bytes):
                errors.append({"path": relative_path, "reason": error or "unreadable"})
            continue

        try:
            if lower_name.startswith("requirements") and lower_name.endswith(".txt"):
                records.extend(_parse_requirements(text, relative_path, packages))
            elif lower_name == "package-lock.json" or lower_name == "npm-shrinkwrap.json":
                records.extend(_parse_json_format(text, relative_path, packages, "package-lock"))
            elif lower_name == "package.json":
                records.extend(_parse_json_format(text, relative_path, packages, "package-json"))
            elif lower_name == "pipfile.lock":
                records.extend(_parse_json_format(text, relative_path, packages, "pipfile-lock"))
            elif lower_name == "composer.lock":
                records.extend(_parse_json_format(text, relative_path, packages, "composer-lock"))
            elif lower_name == "composer.json":
                records.extend(_parse_json_format(text, relative_path, packages, "composer-json"))
            elif lower_name == "poetry.lock":
                records.extend(_parse_toml_format(text, relative_path, packages, "poetry-lock"))
            elif lower_name == "uv.lock":
                records.extend(_parse_toml_format(text, relative_path, packages, "uv-lock"))
            elif lower_name == "cargo.lock":
                records.extend(_parse_toml_format(text, relative_path, packages, "cargo-lock"))
            elif lower_name == "pyproject.toml":
                records.extend(_parse_toml_format(text, relative_path, packages, "pyproject"))
            elif lower_name == "cargo.toml":
                records.extend(_parse_toml_format(text, relative_path, packages, "cargo-toml"))
            elif lower_name == "go.mod":
                records.extend(_parse_go_mod(text, relative_path, packages))
            elif lower_name == "yarn.lock":
                records.extend(_parse_yarn_lock(text, relative_path, packages))
            elif lower_name == "pnpm-lock.yaml":
                records.extend(_parse_pnpm_lock(text, relative_path, packages))
            elif lower_name == "gemfile.lock":
                records.extend(_parse_gemfile_lock(text, relative_path, packages))
            elif lower_name == "pubspec.lock":
                records.extend(_parse_pubspec_lock(text, relative_path, packages))
        except Exception as exc:  # never let one odd file abort the scan
            errors.append({"path": relative_path, "reason": "parser error: {}".format(exc)})

    order = {"exact": 0, "best_effort": 1, "declared": 2}
    records.sort(
        key=lambda item: (
            item["package"].lower(),
            order.get(item["confidence"], 9),
            item["source_path"].lower(),
            item["line"] or 0,
        )
    )
    return records, errors


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def render_text(report: Dict[str, Any]) -> str:
    status = "COMPLETE" if report["scan_complete"] else "INCOMPLETE"
    lines = [
        "API REALITY GUARD — READ-ONLY PROJECT INVENTORY",
        "=" * 48,
        "Root: " + report["root"],
        "Files examined: {} / {}".format(report["files_scanned"], report["max_files"]),
        "Scan status: " + status,
    ]

    if report["scan_errors"]:
        lines.append("")
        lines.append("Unreadable paths:")
        for error in report["scan_errors"]:
            lines.append("- {} — {}".format(error["path"], error["reason"]))

    lines.extend(["", "Project markers:"])
    if report["manifests"]:
        for marker in report["manifests"]:
            lines.append(
                "- [{}] {} — {} ({})".format(
                    marker["ecosystem"], marker["path"], marker["kind"], marker["authority"]
                )
            )
    else:
        lines.append("- No recognised project markers found.")

    lines.extend(["", "Runtime version markers:"])
    if report["runtime_markers"]:
        for marker in report["runtime_markers"]:
            lines.append(
                "- {} — {} = {}".format(marker["path"], marker["kind"], marker["value"] or "unreadable")
            )
    else:
        lines.append("- None found. The runtime version is unresolved from the filesystem.")

    lines.extend(["", "Source file counts:"])
    if report["source_file_counts"]:
        for suffix, count in report["source_file_counts"].items():
            lines.append("- {}: {}".format(suffix, count))
    else:
        lines.append("- No recognised source extensions found.")

    if report["resolution"]:
        lines.extend(["", "Requested package resolution:"])
        for record in report["resolution"]:
            version = record["version"] or record["constraint"] or "unknown"
            lines.append(
                "- {} = {} [{} / {}] {}".format(
                    record["package"], version, record["authority"],
                    record["confidence"], record["source_path"]
                )
            )
        if report["resolution_errors"]:
            for error in report["resolution_errors"]:
                lines.append("- unreadable: {} — {}".format(error["path"], error["reason"]))

    lines.extend(["", "Limitations:"])
    lines.extend("- " + limitation for limitation in report["limitations"])
    return "\n".join(lines)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inventory project markers without reading source code. Passing --package "
            "additionally reads allowlisted manifests and lockfiles to resolve versions."
        )
    )
    parser.add_argument("root", nargs="?", default=".", help="Project directory (default: current)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES,
                        help="Maximum regular files to inspect (default: %(default)s)")
    parser.add_argument("--package", action="append", default=[], metavar="NAME",
                        help="Resolve versions for NAME (repeatable). Enables metadata reads.")
    parser.add_argument("--max-metadata-bytes", type=int, default=DEFAULT_MAX_METADATA_BYTES,
                        help="Maximum bytes read from any single metadata file (default: %(default)s)")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    if args.max_files < 1:
        print("error: --max-files must be at least 1", file=sys.stderr)
        return 2
    if args.max_metadata_bytes < 1:
        print("error: --max-metadata-bytes must be at least 1", file=sys.stderr)
        return 2

    try:
        report = inspect_project(
            Path(args.root),
            max_files=args.max_files,
            label=args.root,
            packages=args.package,
            max_metadata_bytes=args.max_metadata_bytes,
        )
    except (OSError, ValueError) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=False))
    else:
        print(render_text(report))

    # 0 = complete, 1 = incomplete (truncated or unreadable paths), 2 = error.
    return 0 if report["scan_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
