# Validation Report — API Reality Guard 1.0.0

**Date:** 2026-10-29
**Package version:** 1.0.0
**Scope of this document:** what was executed, on which platform, with which
result. Every claim below corresponds to a command that can be re-run.

---

## 1. Summary

| Check | Result | Where |
|---|---|---|
| Unit tests, no third-party dependency | PASS — 58 tests, 4 skipped | Windows, Python 3.13 |
| Unit tests, with PyYAML | PASS — 58 tests, 3 skipped | Windows, Python 3.13 |
| agentskills.io conformance, fallback parser | PASS | Windows |
| agentskills.io conformance, PyYAML parser | PASS, `compliant: true` | Windows |
| Inventory JSON contract | PASS | Windows |
| Determinism (byte-identical output) | PASS | Windows |
| Declared vs resolved distinction | PASS | Windows |
| Over-long folded description rejected | PASS — exit 1 | Windows |
| No regex frontmatter parsing | PASS — grep finds nothing | Windows |
| README demo reproducibility | PASS — fixture resolves as documented | Windows |
| Continuous integration | PASS — 13/13 jobs | GitHub Actions, 2026-10-29 |

The skips are environmental, not failures:

- 1 skip is the PyYAML-versus-fallback agreement test, which only runs when PyYAML
  is importable.
- 3 skips on Windows are POSIX-only behaviours: directory permissions
  (`chmod 000`) and symlink creation without Developer Mode.

---

## 2. Commands executed

From the package root:

```bash
python -m unittest discover -s tests -v
python scripts/validate_skill.py .
python scripts/validate_skill.py . --json
python scripts/inspect_project.py . --json
python scripts/inspect_project.py ../mcp-driftguard --package pyyaml --json
```

With PyYAML installed, the first four were repeated using an interpreter that has
`pyyaml` available, to exercise the authoritative frontmatter path.

### Test suite

```
Ran 58 tests in 14.687s

OK (skipped=4)
```

```
Ran 58 tests in 13.728s

OK (skipped=3)
```

Coverage by area:

| Area | Tests | What is asserted |
|---|---|---|
| Inventory | 12 | Marker discovery, ignored directories, truncation, symlinks, runtime markers, lockfile authority, unreadable paths, contract keys, path privacy |
| Version resolution | 10 | package-lock, pinned and unpinned requirements, PEP 503 normalisation, go.mod, poetry.lock, unknown package, oversized metadata, malformed lockfile, no reads without `--package` |
| Frontmatter | 8 | CRLF and BOM tolerance, delimiter inside a value, block/plain/quoted scalars, fail-closed behaviour, duplicate keys, PyYAML agreement |
| Conformance | 15 | Name rules, reserved words, angle brackets, description bounds, broken and escaping links, missing files, duplicate SKILL.md, script compilation, invalid YAML |
| CLI contracts | 8 | Exit codes 0/1/2 for both scripts, JSON output parseability |

### Conformance

```
PASS: 'api-reality-guard' is compliant with the agentskills.io standard.
PASS: name matches the directory name and is lowercase kebab-case.
PASS: description length is within 1..1024.
PASS: no angle-bracket content in frontmatter.
PASS: relative links resolve inside the skill directory.
PASS: required support files are present and compile.
NOTE: frontmatter parsed with fallback.
```

With PyYAML: `compliant: True`, `frontmatter_parser: pyyaml`, `errors: []`.

The description measures 309 characters against a 1024 limit. The `version` key is
reported as a non-standard but permitted top-level key, which is the intended
behaviour rather than a failure.

### Declared versus resolved

A fixture project with both a manifest and a lockfile for the same dependency:

```
flask      3.0.0    resolved   exact        requirements.txt
lodash     4.17.21  resolved   exact        package-lock.json
lodash     None     declared   declared     package.json
requests   None     declared   declared     requirements.txt
```

The same package appears twice, once as a request and once as a fact. That is the
distinction the skill's rule 2 demands, and the reason this mode exists.

### Real project

```
$ python scripts/inspect_project.py ../mcp-driftguard --package pyyaml --json
"package": "pyyaml", "version": null, "constraint": "PyYAML>=6.0,<7.0",
"authority": "declared", "confidence": "declared", "source_path": "pyproject.toml"
```

A range, reported as a range, with no lockfile invented to fill the gap.

### Regression guard

A `SKILL.md` whose description is 2000 characters in a folded block:

```
FAIL: description length 2000 is outside 1..1024
Skill validation failed with 1 issue(s).
exit=1
```

Version 0.1.0 returned `PASS` and exit `0` on the same file.

---

## 3. What is **not** verified

Stated explicitly, because a validation report that lists only successes is a
marketing document.

1. **No host installation was performed.** The package has not been copied into a
   live Claude Code or ChatGPT workspace by the author. Skill discovery,
   auto-invocation, and how a given host renders the `SKILL.md` body remain
   unverified.
2. **No real third-party API was verified.** The protocol was exercised on
   synthetic fixtures. Whether an agent follows it on a real integration is a
   behavioural question that requires an evaluation set, not a unit test.
3. **CI ran after the local measurements.** The first pipeline was green on
   Linux, macOS and Windows across Python 3.9, 3.11 and 3.13, including the
   authoritative PyYAML job, the regression guards and the resolution fixture.
   The numbers in section 2 remain the local Windows figures, not CI figures.
4. **Python 3.9 and 3.11 were not exercised locally.** Only 3.13 was available on
   this machine. CI covers 3.9 and 3.11 on all three platforms; that is the
   evidence for those versions, not a local measurement.
5. **`best_effort` parsers are best effort.** `yarn.lock`, `pnpm-lock.yaml`,
   `Gemfile.lock`, `pubspec.lock` and TOML lockfiles on Python below 3.11 are read by
   line scanners. They are labelled, and the skill instructs the agent to confirm
   them with native tooling.
6. **Sixteen formats are supported, not all formats.** Anything else is reported as
   unsupported rather than silently ignored.
7. **The name is not reserved.** `api-reality-guard` was not checked against
   trademark or package registries.

---

## 4. Changes since 0.1.0

Full detail in [`references/audit-2026-10-29.md`](references/audit-2026-10-29.md)
and [`CHANGELOG.md`](CHANGELOG.md). The three that matter:

1. **The validator no longer parses YAML with regular expressions.** It was
   approving a 2058-character description against a 1024-character limit.
2. **Unreadable directories no longer produce a false `COMPLETE`.** They are
   reported and force `scan_complete: false`.
3. **The tool can now distinguish a declared range from a resolved version**, which
   is the question the skill's own rule 2 asks and which 0.1.0 could not answer.

---

## 5. How to reproduce

```bash
python -m unittest discover -s tests -v
python scripts/validate_skill.py . --json
python scripts/inspect_project.py . --json
```

To exercise the authoritative YAML path:

```bash
pip install pyyaml
python scripts/validate_skill.py . --json   # frontmatter_parser must be "pyyaml"
```

To reproduce the defect that motivated 1.0.0, restore `validate_skill.py` from
version 0.1.0, write a `SKILL.md` with a 2000-character folded description, and run
it. It will report `PASS`.
