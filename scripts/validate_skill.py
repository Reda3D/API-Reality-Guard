#!/usr/bin/env python3
"""Validate an Agent Skills package against the agentskills.io standard.

Design rule: **never guess a frontmatter value.** The previous version of this
script parsed YAML with regular expressions. That is the failure mode that once
shipped 604 truncated descriptions out of 817 in a public skill collection: a
regex reads `description: >` as the single character ">" and reports success.

This version parses with PyYAML when it is importable. When it is not, it falls
back to a deliberately narrow reader that understands plain, quoted and block
scalars and **fails closed** on anything else. A validator that cannot read a
file must say so, not approve it.

Standard library only, with PyYAML as an optional accelerator. Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

TOOL_VERSION = "1.0.0"

NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

#: The agentskills.io standard forbids reserved vendor words in a skill name.
RESERVED_NAME_WORDS = ("anthropic", "claude")

#: Keys the standard recognises. Extra keys are permitted and reported.
STANDARD_KEYS = ("name", "description", "license", "compatibility", "metadata", "allowed-tools")

NAME_MAX = 64
DESCRIPTION_MIN = 1
DESCRIPTION_MAX = 1024

REQUIRED_FILES = (
    "references/verification-protocol.md",
    "scripts/inspect_project.py",
    "scripts/validate_skill.py",
)


class FrontmatterError(ValueError):
    """Raised when frontmatter is missing, unclosed, or not safely parseable."""


# --------------------------------------------------------------------------
# Frontmatter reading
# --------------------------------------------------------------------------


def split_frontmatter(text: str) -> Tuple[str, str]:
    """Return (frontmatter_yaml, body).

    Tolerates a UTF-8 BOM and CRLF line endings. Delimiters must be a line
    containing only ``---``, which is stricter and safer than splitting the
    whole document on the first two occurrences of the string.
    """
    if text.startswith("\ufeff"):
        text = text[1:]

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError("file must start with a '---' frontmatter delimiter")

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1:])

    raise FrontmatterError("frontmatter is not closed by a second '---' line")


def _find_closing_quote(value: str, quote: str) -> Optional[int]:
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and quote == '"':
            index += 2
            continue
        if char == quote:
            if quote == "'" and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            return index
        index += 1
    return None


def parse_frontmatter_fallback(yaml_text: str) -> Dict[str, Any]:
    """Narrow, fail-closed reader for the subset used by SKILL.md frontmatter.

    Supports top-level ``key: value`` with plain, single-quoted, double-quoted,
    literal (``|``) and folded (``>``) scalars. Nested mappings are recorded as
    opaque (``None``) because their inner values cannot be checked here; that
    limitation is reported rather than hidden.
    """
    result: Dict[str, Any] = {}
    lines = yaml_text.splitlines()
    index = 0

    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue

        if line[0] in " \t":
            raise FrontmatterError(
                "unexpected indentation at line {}; the fallback reader cannot "
                "safely interpret this document".format(index + 1)
            )
        if ":" not in line:
            raise FrontmatterError(
                "line {} is not a 'key: value' pair".format(index + 1)
            )

        key, _, raw_value = line.partition(":")
        key = key.strip()
        value = raw_value.strip()
        if not key:
            raise FrontmatterError("empty key at line {}".format(index + 1))
        if key in result:
            raise FrontmatterError("duplicate key {!r} in frontmatter".format(key))

        if value in ("|", ">", "|-", ">-", "|+", ">+"):
            block: List[str] = []
            index += 1
            while index < len(lines) and (not lines[index].strip() or lines[index][0] in " \t"):
                block.append(lines[index].strip())
                index += 1
            result[key] = " ".join(part for part in block if part).strip()
            continue

        if value[:1] in ("'", '"'):
            quote = value[0]
            buffer = value[1:]
            closing = _find_closing_quote(buffer, quote)
            while closing is None:
                index += 1
                if index >= len(lines):
                    raise FrontmatterError(
                        "unterminated quoted value for key {!r}".format(key)
                    )
                buffer += "\n" + lines[index].strip()
                closing = _find_closing_quote(buffer, quote)
            result[key] = buffer[:closing]
            index += 1
            continue

        if not value:
            # Nested mapping or list: consume the indented block, keep it opaque.
            index += 1
            while index < len(lines) and (
                not lines[index].strip() or lines[index][0] in " \t" or lines[index].startswith("-")
            ):
                index += 1
            result[key] = None
            continue

        parts = [value]
        index += 1
        while index < len(lines) and lines[index].strip() and lines[index][0] in " \t":
            parts.append(lines[index].strip())
            index += 1
        result[key] = " ".join(parts)

    return result


def load_frontmatter(text: str) -> Tuple[Dict[str, Any], str, str]:
    """Return (frontmatter, body, parser_name)."""
    yaml_text, body = split_frontmatter(text)

    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return parse_frontmatter_fallback(yaml_text), body, "fallback"

    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise FrontmatterError("invalid YAML in frontmatter: {}".format(exc)) from exc

    if data is None:
        raise FrontmatterError("frontmatter is empty")
    if not isinstance(data, dict):
        raise FrontmatterError("frontmatter must be a mapping of keys to values")
    return data, body, "pyyaml"


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _iter_strings(value: Any, path: str = "") -> List[Tuple[str, str]]:
    found: List[Tuple[str, str]] = []
    if isinstance(value, str):
        found.append((path, value))
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(_iter_strings(item, "{}.{}".format(path, key) if path else str(key)))
    elif isinstance(value, list):
        for position, item in enumerate(value):
            found.extend(_iter_strings(item, "{}[{}]".format(path, position)))
    return found


def validate(skill_root: Path) -> Tuple[List[str], List[str], str]:
    """Validate a skill package.

    Returns (errors, warnings, parser_name). Empty errors means compliant.
    """
    skill_root = Path(skill_root).resolve()
    errors: List[str] = []
    warnings: List[str] = []
    parser_name = "n/a"

    skill_file = skill_root / "SKILL.md"
    if not skill_file.is_file():
        return ["missing SKILL.md at {}".format(skill_file)], warnings, parser_name

    try:
        text = skill_file.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return ["SKILL.md is not valid UTF-8: {}".format(exc)], warnings, parser_name

    try:
        frontmatter, body, parser_name = load_frontmatter(text)
    except FrontmatterError as exc:
        return ["frontmatter error: {}".format(exc)], warnings, parser_name

    if parser_name == "fallback":
        warnings.append(
            "PyYAML is not installed: frontmatter was read by the narrow fallback "
            "reader. Nested values were not checked. Install pyyaml for the "
            "authoritative result."
        )

    # -- required fields ---------------------------------------------------
    for required in ("name", "description"):
        if required not in frontmatter:
            errors.append("missing required frontmatter field: {}".format(required))

    # -- name --------------------------------------------------------------
    name = frontmatter.get("name")
    if isinstance(name, str) and name:
        if not NAME_PATTERN.fullmatch(name):
            errors.append(
                "name {!r} is not lowercase kebab-case".format(name)
            )
        if not (1 <= len(name) <= NAME_MAX):
            errors.append("name length {} is outside 1..{}".format(len(name), NAME_MAX))
        if name != skill_root.name and name.lower() != skill_root.name.lower():
            # A case-only difference is accepted. GitHub preserves the casing of
            # a repository name, so cloning API-Reality-Guard produces a
            # directory that differs from the skill name only by case. The
            # identity of a skill is its name; case is a hosting artifact. A
            # genuinely different name is still an error.
            errors.append(
                "name {!r} does not match the directory name {!r}".format(name, skill_root.name)
            )
        for reserved in RESERVED_NAME_WORDS:
            if reserved in name.lower():
                errors.append("name contains the reserved word {!r}".format(reserved))
    elif "name" in frontmatter:
        errors.append("name must be a non-empty string")

    # -- description -------------------------------------------------------
    description = frontmatter.get("description")
    if isinstance(description, str):
        if not (DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX):
            errors.append(
                "description length {} is outside {}..{}".format(
                    len(description), DESCRIPTION_MIN, DESCRIPTION_MAX
                )
            )
    elif "description" in frontmatter:
        errors.append(
            "description must be a single string, got {}".format(type(description).__name__)
        )

    # -- injection surface -------------------------------------------------
    # Angle brackets in frontmatter are an injection risk on hosts that render
    # the description as markup. Checked on parsed values, so YAML indicators
    # such as ">-" are never mistaken for content.
    for key, value in _iter_strings(frontmatter):
        if "<" in value or ">" in value:
            errors.append(
                "frontmatter value for {!r} contains angle brackets".format(key)
            )

    # -- body --------------------------------------------------------------
    if not body.strip():
        errors.append("SKILL.md instruction body must not be empty")

    # -- links -------------------------------------------------------------
    for match in MARKDOWN_LINK_PATTERN.finditer(body):
        target = match.group(1).strip()
        if target.startswith(("https://", "http://", "#", "mailto:")):
            continue
        candidate = (skill_root / target.split("#", 1)[0]).resolve()
        try:
            candidate.relative_to(skill_root)
        except ValueError:
            errors.append("relative link escapes the skill directory: {}".format(target))
            continue
        if not candidate.is_file():
            errors.append("broken relative link: {}".format(target))

    # -- structure ---------------------------------------------------------
    for required_file in REQUIRED_FILES:
        if not (skill_root / required_file).is_file():
            errors.append("missing required support file: {}".format(required_file))

    skill_files = [path for path in skill_root.rglob("SKILL.md") if path.is_file()]
    if len(skill_files) != 1:
        errors.append(
            "expected exactly one SKILL.md in the package, found {}".format(len(skill_files))
        )

    # -- symlink containment ----------------------------------------------
    for path in skill_root.rglob("*"):
        if path.is_symlink():
            resolved = path.resolve()
            try:
                resolved.relative_to(skill_root)
            except ValueError:
                errors.append(
                    "symlink escapes the skill directory: {}".format(
                        path.relative_to(skill_root).as_posix()
                    )
                )

    # -- scripts compile ---------------------------------------------------
    for script in sorted((skill_root / "scripts").glob("*.py")):
        try:
            compile(script.read_text(encoding="utf-8"), str(script), "exec")
        except SyntaxError as exc:
            errors.append("{} does not compile: {}".format(script.name, exc))
        except UnicodeDecodeError:
            errors.append("{} is not valid UTF-8".format(script.name))

    # -- non-standard keys (informational) ---------------------------------
    extra = sorted(key for key in frontmatter if key not in STANDARD_KEYS)
    if extra:
        warnings.append(
            "non-standard top-level keys present (permitted by the standard): {}".format(
                ", ".join(extra)
            )
        )

    return errors, warnings, parser_name


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate an Agent Skills package against the agentskills.io standard."
    )
    parser.add_argument("path", nargs="?", default=".", help="Skill directory (default: current)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    skill_root = Path(args.path).resolve()
    if not skill_root.is_dir():
        print("error: {} is not a directory".format(args.path), file=sys.stderr)
        return 2

    errors, warnings, parser_name = validate(skill_root)
    ok = not errors

    if args.json:
        print(
            json.dumps(
                {
                    "tool": "api-reality-guard",
                    "tool_version": TOOL_VERSION,
                    "skill": skill_root.name,
                    "compliant": ok,
                    "frontmatter_parser": parser_name,
                    "errors": errors,
                    "warnings": warnings,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        for warning in warnings:
            print("WARN: " + warning)
        for error in errors:
            print("FAIL: " + error, file=sys.stderr)
        if ok:
            print("PASS: {!r} is compliant with the agentskills.io standard.".format(skill_root.name))
            print("PASS: name matches the directory name and is lowercase kebab-case.")
            print("PASS: description length is within 1..{}.".format(DESCRIPTION_MAX))
            print("PASS: no angle-bracket content in frontmatter.")
            print("PASS: relative links resolve inside the skill directory.")
            print("PASS: required support files are present and compile.")
            print("NOTE: frontmatter parsed with {}.".format(parser_name))
        else:
            print(
                "Skill validation failed with {} issue(s).".format(len(errors)),
                file=sys.stderr,
            )

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
