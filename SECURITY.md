# Security policy

## Supported versions

| Version | Supported |
|---|---|
| `1.0.x` | Yes |
| `0.1.x` | No — superseded, see [`references/audit-2026-10-29.md`](references/audit-2026-10-29.md) |

## Reporting a vulnerability

Please do **not** open a public issue for a security problem.

Use GitHub's private vulnerability reporting on this repository
(*Security* → *Report a vulnerability*). If that is unavailable, open a minimal
issue asking for a private channel, and include no details.

Please include:

- The version (`SKILL.md` frontmatter, or `scripts/inspect_project.py --json`
  field `tool_version`) and the platform.
- A minimal reproduction: the fixture project or `SKILL.md` that triggers it.
- What you expected versus what happened.
- The impact you believe it has.

## What counts

Anything that breaks one of the guarantees in the README's security model is in
scope. Concretely:

| Guarantee | Example violation |
|---|---|
| Source code is never read | Any mode opens a `.py`, `.ts`, `.go` file and reads its content |
| Only allowlisted metadata is read | A path outside the marker registry is opened |
| Symlinks are never followed | A symlinked directory or file is traversed |
| Reads are bounded | A small file causes unbounded memory or time |
| No network access | Any outbound request from a bundled script |
| No execution | A subprocess, `eval`, or import of project code |
| Completeness is honest | `scan_complete: true` while a path was skipped |
| Declared is never reported as resolved | A range appears with `authority: resolved` |
| Validation fails closed | A `SKILL.md` that cannot be parsed is reported as compliant |
| Reports are inert | A tool name or description produces active markup |

## What is out of scope

- An agent choosing not to follow the procedure. The skill makes omission
  visible; it cannot compel compliance.
- False positives from the description heuristics. Report them as normal issues.
- Findings that require an already-compromised machine.
- Formats outside the documented support list. Those are reported as unsupported
  by design.

## Response

Acknowledgement within 72 hours. A fix or a documented decision within 30 days for
confirmed issues. Credit in the changelog unless you ask otherwise.

## For users

- Pin the repository to a commit SHA or a release tag in automated pipelines.
- Read [`VALIDATION_REPORT.md`](VALIDATION_REPORT.md) before relying on a
  guarantee; it states what was actually exercised.
- Treat the `SKILL.md` procedure as part of your review process, not as a
  replacement for it.
