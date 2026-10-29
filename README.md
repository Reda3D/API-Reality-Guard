# API Reality Guard

An Agent Skill that stops AI-generated code from being built on APIs that do not
exist, parameters that were invented, or documentation for a version the project
does not use.

Built for Claude Code and any host that implements the
[agentskills.io](https://agentskills.io) format.

---

## The problem it targets

AI coding assistants produce code that looks right and fails at import. The failure
is rarely a syntax error; it is a method that never existed, a keyword argument from
a different major version, or a package name that was hallucinated whole.

The skill does not try to detect this with another model. It imposes a procedure:
establish which version the project resolves, find evidence that applies to *that*
version, and label every claim with what was actually checked.

## What is in the box

| Path | Purpose |
|---|---|
| `SKILL.md` | The procedure: six gates, ten non-negotiable rules, evidence labels |
| `references/verification-protocol.md` | Evidence ranking, version resolution, per-ecosystem sources, failure modes |
| `references/audit-2026-10-29.md` | The defect audit that produced version 1.0.0 |
| `scripts/inspect_project.py` | Read-only inventory, plus optional version resolution |
| `scripts/validate_skill.py` | Standards conformance check for this package |
| `tests/` | 58 tests: inventory, resolution, conformance, CLI contracts |
| `VALIDATION_REPORT.md` | What was actually run, with results |

## Install

### Claude Code (Windows)

```powershell
Copy-Item -Recurse .\api-reality-guard "$env:USERPROFILE\.claude\skills\api-reality-guard"
```

### Claude Code (macOS / Linux)

```bash
cp -r api-reality-guard ~/.claude/skills/api-reality-guard
```

### Any other host

Copy the whole directory into the location your host documents for skills. The
package is self-contained: `SKILL.md`, `references/`, `scripts/`, `tests/`.

Restart the host or start a new session, then invoke the skill by name on a real
task.

## Use

Ask for a version-sensitive change and name the skill:

> Use api-reality-guard to add retries to our Stripe client.

The agent should then resolve the installed version, cite evidence per claim, and
label anything it could not verify.

### The helpers, standalone

```bash
# Inventory: filenames only. No file contents, no network, no code execution.
python scripts/inspect_project.py . --json

# Inventory plus version resolution. Reads allowlisted manifests and lockfiles only.
python scripts/inspect_project.py . --package requests --package flask --json

# Validate this package against the standard.
python scripts/validate_skill.py .
```

`inspect_project.py` exit codes: `0` complete, `1` incomplete (truncated scan or
unreadable paths), `2` usage or I/O error.

## Declared versus resolved

This is the distinction the skill exists to protect, and the reason the inventory
grew a resolution mode.

```json
{
  "package": "pyyaml",
  "version": null,
  "constraint": "PyYAML>=6.0,<7.0",
  "authority": "declared",
  "confidence": "declared",
  "source_path": "pyproject.toml"
}
```

That is a *request*, not a fact. If a lockfile had been present, the same package
would appear with `"authority": "resolved"` and a concrete version. An agent that
reads only the constraint and then cites documentation for the latest release has
verified nothing.

Confidence levels:

| Level | Meaning |
|---|---|
| `exact` | Parsed by a real parser (JSON, or TOML via `tomllib` on Python 3.11+) from a lockfile |
| `best_effort` | Extracted by a line scanner. A lead, to confirm with native tooling |
| `declared` | A range from a manifest. Not a version |

## Supported formats

`package-lock.json`, `package.json`, `yarn.lock`, `pnpm-lock.yaml`,
`requirements*.txt`, `Pipfile.lock`, `poetry.lock`, `uv.lock`, `pyproject.toml`,
`Cargo.lock`, `Cargo.toml`, `go.mod`, `composer.json`, `composer.lock`,
`Gemfile.lock`, `pubspec.lock`.

Anything else is reported as unsupported rather than silently ignored: the report
lists the supported set in every run.

## What this skill does not do

- It does not prove an API behaves correctly for your data. It proves the contract
  you are coding against exists.
- It does not run your project, install anything, or reach the network from its
  bundled scripts.
- It does not replace tests. It tells you which tests are worth writing.
- It does not guarantee that an agent follows the procedure. It makes deviation
  visible: every claim is supposed to carry a label, and a missing label is itself
  a finding.

## Security model

The bundled scripts are the part that runs on your machine, so their boundaries are
stated rather than implied.

- **Inventory mode reads filenames only.** No file contents are opened.
- **Resolution mode reads allowlisted metadata files only** — the manifest and
  lockfile names in the registry. Never source code.
- **Symlinks are never followed**, for directories or for files.
- **Reads are bounded**: 2 MiB per metadata file by default, 4 KiB for runtime
  markers, 200 000 lines per text format.
- **No network access, no subprocess, no `eval`.** Standard library only.
- **Unreadable paths are reported, never swallowed.** A directory that cannot be
  listed makes the scan `INCOMPLETE`; it does not quietly vanish from a report that
  claims to be complete.
- **The absolute project path is not emitted** unless you passed one explicitly.

`validate_skill.py` uses PyYAML when it is installed and a narrow, fail-closed
reader otherwise. It never falls back to regular-expression parsing of YAML: that
technique is what silently truncates multi-line descriptions, and it is the reason
version 1.0.0 of this package exists.

## Requirements

- Python 3.9 or newer.
- No third-party dependency. PyYAML is optional and only makes validation stricter.
- `tomllib` is used automatically on Python 3.11+; older versions fall back to a
  labelled best-effort scan of TOML lockfiles.

## Verification status

The package is tested locally on Windows and in CI on Linux, macOS and Windows
across Python 3.9, 3.11 and 3.13. It has **not** been installed into a live Claude
Code or ChatGPT workspace by the author, so host discovery and auto-invocation are
unverified. See `VALIDATION_REPORT.md` for the exact scope of every claim.

## License

MIT. See `LICENSE.txt`.
