# Contributing

## Setup

No dependency is required to work on this repository.

```bash
git clone https://github.com/Reda3D/api-reality-guard.git
cd api-reality-guard
python -m unittest discover -s tests -v
python scripts/validate_skill.py .
```

Optionally, for the stricter validation path:

```bash
pip install pyyaml
python scripts/validate_skill.py . --json   # frontmatter_parser must be "pyyaml"
```

## Before opening a pull request

```bash
python -m unittest discover -s tests -v
python scripts/validate_skill.py .
python scripts/inspect_project.py . --json > /dev/null
```

All three run in CI on Linux, macOS and Windows across Python 3.9, 3.11 and 3.13,
with and without PyYAML.

## What a good change looks like

- **One concern per pull request.** A new lockfile format and a documentation
  rewrite do not belong in the same diff.
- **A test that fails without the change.** For a new format, that means a fixture
  that reproduces the resolution.
- **A labelled confidence.** Any new extraction is either `exact` (real parser) or
  `best_effort` (line scanner). Never present a scan as authoritative.
- **No new runtime dependency.** `json` and `tomllib` are the budget. If you need
  more, explain why in the pull request.

## Adding a lockfile format

1. Write a parser in `scripts/inspect_project.py` returning records built by
   `_record()`. Set `authority` and `confidence` honestly.
2. Register the filename in `MARKERS` and add it to `SUPPORTED_FORMATS`.
3. Dispatch it in `_resolve_packages`.
4. Add a test in `tests/test_inspect_project.py` covering both a hit and a miss.
5. Add the format to the README support list.

A parser that raises must not abort the scan: catch, record in
`resolution_errors`, and continue. A malformed lockfile in one directory is not a
reason to lose the rest of the report.

## Changing `SKILL.md`

- `name` must stay lowercase kebab-case and equal the directory name.
- `description` must stay within 1–1024 characters and state **what** the skill
  does and **when** to use it.
- No angle brackets in frontmatter values. The validator rejects them, because
  some hosts render the description as markup.
- Every relative link must resolve inside the package.
- Adding a rule is cheap; adding a *procedure step* is not. Six gates is already
  a lot for an agent to hold. Justify any new one.

## Security-sensitive changes

Extra scrutiny applies to:

- `scripts/inspect_project.py` — the only code that touches project files.
- `scripts/validate_skill.py` — the gate that decides a package is compliant.
- Any change that widens what is read, or where it is read from.

If a change makes the tool read something it did not read before, expect the pull
request to be rejected unless it is discussed in an issue first.

## Style

- Python 3.9 compatible. No `match`, no `X | Y` in runtime type positions.
- Standard library only in `scripts/`. Tests may use `unittest` and nothing else.
- `%`-formatting for messages that must stay identical across Python versions.
- Comments explain *why*. A comment restating the code is removed in review.

## Commit messages

Imperative mood, one line, then a body when the reasoning is not obvious:

```
Report declared ranges as declared, never as versions

A requirements line such as "requests>=2.31,<3" was being emitted with
authority "resolved" because the parser treated any parsed line as a
resolution. A range is a request. Reporting it as a fact is the exact error
this skill exists to prevent.
```

## Reporting bugs

Include the version, the platform, and the smallest fixture that reproduces the
problem. If the fixture contains anything proprietary, reduce it first — the
formats are small enough that a synthetic reproduction is usually a few lines.
