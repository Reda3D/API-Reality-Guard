from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from validate_skill import (  # noqa: E402
    FrontmatterError,
    parse_frontmatter_fallback,
    split_frontmatter,
    validate,
)

try:
    import yaml  # noqa: F401

    HAVE_PYYAML = True
except ModuleNotFoundError:
    HAVE_PYYAML = False


def build_skill(root: Path, frontmatter: str, body: str = "# Body\n") -> Path:
    """Create a structurally complete skill package with the given frontmatter."""
    (root / "references").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "references" / "verification-protocol.md").write_text("# Protocol\n", encoding="utf-8")
    (root / "scripts" / "inspect_project.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "scripts" / "validate_skill.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "SKILL.md").write_text(
        "---\n" + frontmatter + "---\n\n" + body, encoding="utf-8"
    )
    return root


VALID_FRONTMATTER = (
    "name: api-reality-guard\n"
    "description: Verify API claims against the exact versions a project uses.\n"
)


class SplitTests(unittest.TestCase):
    def test_tolerates_crlf_and_bom(self) -> None:
        text = "\ufeff---\r\nname: x\r\n---\r\n\r\nbody\r\n"
        frontmatter, body = split_frontmatter(text)
        self.assertEqual(frontmatter, "name: x")
        self.assertIn("body", body)

    def test_rejects_missing_delimiter(self) -> None:
        with self.assertRaises(FrontmatterError):
            split_frontmatter("no frontmatter here")

    def test_rejects_unclosed_frontmatter(self) -> None:
        with self.assertRaises(FrontmatterError):
            split_frontmatter("---\nname: x\n")

    def test_delimiter_inside_a_value_does_not_truncate(self) -> None:
        text = "---\ndescription: a --- b\n---\n\nbody\n"
        frontmatter, _ = split_frontmatter(text)
        self.assertIn("a --- b", frontmatter)


class FallbackParserTests(unittest.TestCase):
    def test_reads_block_scalar(self) -> None:
        parsed = parse_frontmatter_fallback("description: >\n  one\n  two\n")
        self.assertEqual(parsed["description"], "one two")

    def test_reads_quoted_scalar(self) -> None:
        parsed = parse_frontmatter_fallback('description: "a: b"\n')
        self.assertEqual(parsed["description"], "a: b")

    def test_reads_plain_scalar(self) -> None:
        parsed = parse_frontmatter_fallback("name: api-reality-guard\n")
        self.assertEqual(parsed["name"], "api-reality-guard")

    def test_fails_closed_on_a_line_that_is_not_a_pair(self) -> None:
        with self.assertRaises(FrontmatterError):
            parse_frontmatter_fallback("name: x\nthis line is not a key value pair\n")

    def test_fails_closed_on_unterminated_quote(self) -> None:
        with self.assertRaises(FrontmatterError):
            parse_frontmatter_fallback('name: "unterminated\n')

    def test_rejects_duplicate_keys(self) -> None:
        with self.assertRaises(FrontmatterError):
            parse_frontmatter_fallback("name: a\nname: b\n")

    @unittest.skipUnless(HAVE_PYYAML, "PyYAML is not installed")
    def test_agrees_with_pyyaml_on_the_real_skill(self) -> None:
        from validate_skill import load_frontmatter

        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        frontmatter, _, parser = load_frontmatter(text)
        yaml_text, _ = split_frontmatter(text)
        fallback = parse_frontmatter_fallback(yaml_text)

        self.assertEqual(parser, "pyyaml")
        self.assertEqual(frontmatter["name"], fallback["name"])
        self.assertEqual(frontmatter["description"], fallback["description"])


class ValidationTests(unittest.TestCase):
    def test_the_shipped_package_is_compliant(self) -> None:
        errors, _, _ = validate(SKILL_ROOT)
        self.assertEqual(errors, [])

    def test_detects_name_directory_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(
                Path(temp_dir) / "wrong-name",
                "name: api-reality-guard\ndescription: Valid description.\n",
            )
            errors, _, _ = validate(root)
            self.assertTrue(any("does not match the directory name" in e for e in errors))

    def test_accepts_a_case_only_directory_difference(self) -> None:
        """Cloning a repo named API-Reality-Guard yields a mixed-case directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(
                Path(temp_dir) / "API-Reality-Guard",
                "name: api-reality-guard\ndescription: Valid description.\n",
            )
            errors, _, _ = validate(root)
            self.assertEqual(errors, [])

    def test_detects_non_kebab_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(
                Path(temp_dir) / "api_reality_guard",
                "name: api_reality_guard\ndescription: Valid description.\n",
            )
            errors, _, _ = validate(root)
            self.assertTrue(any("kebab-case" in e for e in errors))

    def test_detects_reserved_word_in_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(
                Path(temp_dir) / "claude-helper",
                "name: claude-helper\ndescription: Valid description.\n",
            )
            errors, _, _ = validate(root)
            self.assertTrue(any("reserved word" in e for e in errors))

    def test_detects_angle_brackets_in_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(
                Path(temp_dir) / "api-reality-guard",
                "name: api-reality-guard\ndescription: Use when input is <script>alert(1)</script>.\n",
            )
            errors, _, _ = validate(root)
            self.assertTrue(any("angle brackets" in e for e in errors))

    def test_rejects_overlong_folded_description(self) -> None:
        """Regression: the previous regex read this as the single character '>'."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(
                Path(temp_dir) / "api-reality-guard",
                "name: api-reality-guard\ndescription: >\n  " + "A" * 2000 + "\n",
            )
            errors, _, _ = validate(root)
            self.assertTrue(
                any("description length" in e for e in errors),
                "a 2000-character description must be rejected, got: {}".format(errors),
            )

    def test_rejects_overlong_plain_description(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(
                Path(temp_dir) / "api-reality-guard",
                "name: api-reality-guard\ndescription: " + "A" * 1500 + "\n",
            )
            errors, _, _ = validate(root)
            self.assertTrue(any("description length" in e for e in errors))

    def test_rejects_missing_description(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(Path(temp_dir) / "api-reality-guard", "name: api-reality-guard\n")
            errors, _, _ = validate(root)
            self.assertTrue(any("missing required" in e for e in errors))

    def test_rejects_empty_body(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(Path(temp_dir) / "api-reality-guard", VALID_FRONTMATTER, body="\n")
            errors, _, _ = validate(root)
            self.assertTrue(any("body must not be empty" in e for e in errors))

    def test_detects_broken_relative_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(
                Path(temp_dir) / "api-reality-guard",
                VALID_FRONTMATTER,
                body="See [protocol](references/missing.md).\n",
            )
            errors, _, _ = validate(root)
            self.assertTrue(any("broken relative link" in e for e in errors))

    def test_detects_link_escaping_the_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(
                Path(temp_dir) / "api-reality-guard",
                VALID_FRONTMATTER,
                body="See [outside](../../etc/passwd).\n",
            )
            errors, _, _ = validate(root)
            self.assertTrue(any("escapes the skill directory" in e for e in errors))

    def test_detects_missing_support_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(Path(temp_dir) / "api-reality-guard", VALID_FRONTMATTER)
            (root / "references" / "verification-protocol.md").unlink()
            errors, _, _ = validate(root)
            self.assertTrue(any("missing required support file" in e for e in errors))

    def test_detects_duplicate_skill_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(Path(temp_dir) / "api-reality-guard", VALID_FRONTMATTER)
            (root / "nested").mkdir()
            (root / "nested" / "SKILL.md").write_text("---\nname: nested\n---\n", encoding="utf-8")
            errors, _, _ = validate(root)
            self.assertTrue(any("exactly one SKILL.md" in e for e in errors))

    def test_detects_script_that_does_not_compile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(Path(temp_dir) / "api-reality-guard", VALID_FRONTMATTER)
            (root / "scripts" / "inspect_project.py").write_text("def broken(:\n", encoding="utf-8")
            errors, _, _ = validate(root)
            self.assertTrue(any("does not compile" in e for e in errors))

    def test_fails_closed_on_invalid_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(
                Path(temp_dir) / "api-reality-guard",
                "name: api-reality-guard\nthis line is not a key value pair\n",
            )
            errors, _, _ = validate(root)
            self.assertTrue(
                any(error.startswith("frontmatter error") for error in errors),
                "expected a hard frontmatter error, got: {}".format(errors),
            )

    def test_reports_non_standard_keys_as_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = build_skill(
                Path(temp_dir) / "api-reality-guard",
                VALID_FRONTMATTER + "version: 1.0.0\n",
            )
            errors, warnings, _ = validate(root)
            self.assertEqual(errors, [])
            self.assertTrue(any("non-standard" in w for w in warnings))

    def test_rejects_missing_skill_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            errors, _, _ = validate(Path(temp_dir))
            self.assertTrue(any("missing SKILL.md" in e for e in errors))


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "validate_skill.py")] + list(args),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_exit_zero_on_the_real_package(self) -> None:
        result = self.run_cli(str(SKILL_ROOT))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_json_output_is_parseable(self) -> None:
        import json

        result = self.run_cli(str(SKILL_ROOT), "--json")
        payload = json.loads(result.stdout)
        self.assertTrue(payload["compliant"])
        self.assertIn(payload["frontmatter_parser"], {"pyyaml", "fallback"})

    def test_exit_two_on_missing_directory(self) -> None:
        result = self.run_cli("definitely-not-a-directory")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
