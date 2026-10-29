# Changelog

All notable changes to this package are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-10-29

First release after a full audit of the 0.1.0 package. The audit is published in
[`references/audit-2026-10-29.md`](references/audit-2026-10-29.md); the summary is
below.

### Fixed

- **`validate_skill.py` parsed YAML with regular expressions.** A folded
  description (`description: >`) was read as the single character `>`, so the length
  check measured the wrong value. A `SKILL.md` with a 2058-character description was
  approved against a 1024-character limit. Frontmatter is now parsed with PyYAML
  when available, and otherwise by a narrow reader that **fails closed** on anything
  it cannot classify.
- **`---` inside a frontmatter value truncated the document**, because the file was
  split on the first two occurrences of the substring. Delimiters are now matched as
  lines.
- **`os.walk` swallowed `PermissionError`**, so an unreadable directory silently
  disappeared while the report claimed `COMPLETE`. Unreadable paths are now collected
  in `scan_errors` and force `scan_complete: false`.
- A file named `description` was classified as an R package manifest.
- FIFOs and sockets were counted in `files_scanned`.
- The absolute project path was embedded in the report even when the caller passed a
  relative one.

### Added

- **Version resolution** (`--package NAME`, repeatable). Reads allowlisted manifests
  and lockfiles only — never source files — and reports `authority`
  (`resolved`/`declared`), `confidence` (`exact`/`best_effort`/`declared`), source
  path and line. Sixteen formats. This closes the gap between the skill's rule 2
  ("distinguish declared from resolved") and the tooling behind it.
- **`runtime_markers`** — `.python-version`, `.nvmrc`, `.node-version`,
  `.ruby-version`, `.tool-versions`, `rust-toolchain.toml`, `global.json` and
  friends. The runtime version is half of every compatibility question.
- **`authority` and `is_lockfile`** on every manifest record, so a consumer no
  longer has to substring-match English prose.
- **agentskills.io conformance checks** in `validate_skill.py`: angle brackets in
  frontmatter, reserved words in the name, non-standard key reporting, script
  compilation, symlink containment.
- **`--json` on the validator**, for machine consumption.
- **CI** on Linux, macOS and Windows across Python 3.9, 3.11 and 3.13, including a
  job that fails if regular-expression frontmatter parsing is reintroduced.
- 52 additional tests (58 total), covering exit-code contracts, malformed lockfiles,
  oversized metadata, PEP 503 name normalisation and the folded-description
  regression.

### Changed

- **BREAKING:** `schema_version` is now `2`. New top-level fields: `tool`,
  `tool_version`, `scan_complete`, `scan_errors`, `runtime_markers`, `resolution`,
  `resolution_errors`, `resolution_supported_formats`, `toml_parser_available`.
  `manifests[].kind` keeps its human-readable value; `authority` and `is_lockfile`
  are new.
- **BREAKING:** `inspect_project.py` exit codes are now a documented contract —
  `0` complete, `1` incomplete, `2` error.
- `SKILL.md` restructured into six explicit gates (0–5) with a stop condition at
  gate 4, so "I could not verify this" is a named outcome rather than a failure to
  finish.
- `SKILL.md` now states what the skill does **not** do, in its own section.

### Not changed

The ten non-negotiable rules, the evidence hierarchy and the refusal to invent
evidence are the product. They were preserved.

## [0.1.0] — 2026-10-29

Initial package: `SKILL.md` workflow, verification protocol, read-only filename
inventory, structural validator, six tests.

[1.0.0]: https://github.com/Reda3D/api-reality-guard/releases/tag/v1.0.0
