from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from inspect_project import inspect_project  # noqa: E402

IS_WINDOWS = os.name == "nt"


def write(root: Path, relative: str, content: str = "") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class InventoryTests(unittest.TestCase):
    def test_discovers_python_and_typescript_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "pyproject.toml", "[project]\n")
            write(root, "uv.lock", "")
            write(root, "package.json", "{}")
            write(root, "src/main.ts")
            write(root, "src/worker.py")

            report = inspect_project(root)
            paths = {item["path"] for item in report["manifests"]}

            self.assertEqual(paths, {"pyproject.toml", "uv.lock", "package.json"})
            self.assertEqual(report["source_file_counts"][".ts"], 1)
            self.assertEqual(report["source_file_counts"][".py"], 1)
            self.assertTrue(report["scan_complete"])

    def test_ignores_generated_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "package.json", "{}")
            write(root, "node_modules/fake/package.json", "{}")
            write(root, "target/Cargo.toml", "")

            report = inspect_project(root)

            self.assertEqual([item["path"] for item in report["manifests"]], ["package.json"])

    def test_marks_a_capped_scan_as_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "a.py")
            write(root, "b.py")

            report = inspect_project(root, max_files=1)

            self.assertEqual(report["files_scanned"], 1)
            self.assertTrue(report["scan_truncated"])
            self.assertFalse(report["scan_complete"])

    def test_output_is_byte_identical_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "z.py")
            write(root, "a.py")
            write(root, "Cargo.toml", "")
            write(root, "sub/requirements-dev.txt", "requests==2.31.0\n")

            first = json.dumps(inspect_project(root), sort_keys=True)
            second = json.dumps(inspect_project(root), sort_keys=True)

            self.assertEqual(first, second)

    def test_rejects_non_positive_file_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                inspect_project(Path(temp_dir), max_files=0)

    def test_does_not_follow_symlinked_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "actual/pyproject.toml", "")
            try:
                os.symlink(root / "actual", root / "alias", target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest("directory symlinks unavailable: {}".format(exc))

            report = inspect_project(root)

            self.assertEqual(
                [item["path"] for item in report["manifests"]], ["actual/pyproject.toml"]
            )

    def test_symlinked_files_are_not_counted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = write(root, "real.py", "")
            try:
                os.symlink(target, root / "link.py")
            except (OSError, NotImplementedError) as exc:
                self.skipTest("file symlinks unavailable: {}".format(exc))

            report = inspect_project(root)

            self.assertEqual(report["files_scanned"], 1)
            self.assertEqual(report["source_file_counts"].get(".py"), 1)

    def test_records_lockfile_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "package.json", "{}")
            write(root, "package-lock.json", "{}")

            report = inspect_project(root)
            by_path = {item["path"]: item for item in report["manifests"]}

            self.assertEqual(by_path["package-lock.json"]["authority"], "lockfile")
            self.assertTrue(by_path["package-lock.json"]["is_lockfile"])
            self.assertEqual(by_path["package.json"]["authority"], "manifest")
            self.assertFalse(by_path["package.json"]["is_lockfile"])

    def test_does_not_misclassify_a_file_named_description(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "docs/description", "not an R package")

            report = inspect_project(root)

            self.assertEqual(report["manifests"], [])

    def test_detects_runtime_version_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, ".python-version", "3.11.4\n")
            write(root, ".nvmrc", "20.11.0\n")

            report = inspect_project(root)
            values = {item["path"]: item["value"] for item in report["runtime_markers"]}

            self.assertEqual(values[".python-version"], "3.11.4")
            self.assertEqual(values[".nvmrc"], "20.11.0")

    def test_unreadable_directory_is_reported_not_swallowed(self) -> None:
        if IS_WINDOWS:
            self.skipTest("chmod does not restrict directory access on Windows")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "a.py")
            locked = root / "locked"
            locked.mkdir()
            write(locked, "b.py")
            os.chmod(locked, 0o000)
            try:
                report = inspect_project(root)
            finally:
                os.chmod(locked, 0o755)

            self.assertTrue(report["scan_errors"], "expected an unreadable path to be recorded")
            self.assertFalse(report["scan_complete"])

    def test_report_contains_the_documented_contract_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = inspect_project(Path(temp_dir))
            for key in (
                "tool",
                "tool_version",
                "schema_version",
                "root",
                "files_scanned",
                "scan_complete",
                "scan_errors",
                "manifests",
                "runtime_markers",
                "ecosystems",
                "source_file_counts",
                "resolution",
                "limitations",
            ):
                self.assertIn(key, report)

    def test_label_does_not_leak_the_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = inspect_project(Path(temp_dir), label=".")
            self.assertEqual(report["root"], ".")


class ResolutionTests(unittest.TestCase):
    def test_resolves_from_package_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(
                root,
                "package-lock.json",
                json.dumps(
                    {
                        "lockfileVersion": 3,
                        "packages": {
                            "": {"name": "app"},
                            "node_modules/lodash": {"version": "4.17.21"},
                            "node_modules/a/node_modules/lodash": {"version": "4.17.20"},
                        },
                    }
                ),
            )

            report = inspect_project(root, packages=["lodash"])
            records = report["resolution"]

            self.assertEqual(len(records), 2)
            self.assertTrue(all(r["authority"] == "resolved" for r in records))
            self.assertTrue(all(r["confidence"] == "exact" for r in records))
            self.assertEqual({r["version"] for r in records}, {"4.17.21", "4.17.20"})

    def test_declared_range_is_not_reported_as_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "package.json", json.dumps({"dependencies": {"lodash": "^4.17.0"}}))

            records = inspect_project(root, packages=["lodash"])["resolution"]

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["authority"], "declared")
            self.assertIsNone(records[0]["version"])
            self.assertEqual(records[0]["constraint"], "^4.17.0")

    def test_resolves_pinned_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "requirements.txt", "Flask==3.0.0\nrequests>=2.0\n")

            records = inspect_project(root, packages=["flask", "requests"])["resolution"]
            by_name = {record["package"]: record for record in records}

            self.assertEqual(by_name["flask"]["version"], "3.0.0")
            self.assertEqual(by_name["flask"]["authority"], "resolved")
            self.assertIsNone(by_name["requests"]["version"])
            self.assertEqual(by_name["requests"]["authority"], "declared")

    def test_python_name_normalisation_matches_pep503(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "requirements.txt", "zope.interface==6.0\n")

            records = inspect_project(root, packages=["zope-interface"])["resolution"]

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["version"], "6.0")

    def test_resolves_go_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(
                root,
                "go.mod",
                "module example.com/app\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n)\n",
            )

            records = inspect_project(root, packages=["github.com/gin-gonic/gin"])["resolution"]

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["version"], "1.9.1")

    def test_resolves_poetry_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(
                root,
                "poetry.lock",
                '[[package]]\nname = "requests"\nversion = "2.31.0"\n\n'
                '[[package]]\nname = "flask"\nversion = "3.0.1"\n',
            )

            records = inspect_project(root, packages=["requests"])["resolution"]

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["version"], "2.31.0")
            self.assertIn(records[0]["confidence"], {"exact", "best_effort"})

    def test_unknown_package_returns_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "requirements.txt", "flask==3.0.0\n")

            self.assertEqual(inspect_project(root, packages=["does-not-exist"])["resolution"], [])

    def test_no_reads_without_a_package_argument(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "requirements.txt", "flask==3.0.0\n")

            report = inspect_project(root)

            self.assertEqual(report["resolution"], [])
            self.assertEqual(report["resolution_errors"], [])

    def test_oversized_metadata_file_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "requirements.txt", "flask==3.0.0\n" + "# pad\n" * 5000)

            report = inspect_project(root, packages=["flask"], max_metadata_bytes=64)

            self.assertEqual(report["resolution"], [])

    def test_malformed_lockfile_does_not_abort_the_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "package-lock.json", "{ this is not json")
            write(root, "requirements.txt", "flask==3.0.0\n")

            report = inspect_project(root, packages=["flask"])

            self.assertEqual(len(report["resolution"]), 1)
            self.assertEqual(report["resolution"][0]["version"], "3.0.0")


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "inspect_project.py")] + list(args),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_json_output_is_valid_and_complete(self) -> None:
        result = self.run_cli(str(SKILL_ROOT), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], 2)
        self.assertTrue(payload["scan_complete"])

    def test_exit_code_one_when_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write(root, "a.py")
            write(root, "b.py")
            result = self.run_cli(root, "--max-files", "1", "--json")
            self.assertEqual(result.returncode, 1)
            self.assertFalse(json.loads(result.stdout)["scan_complete"])

    def test_exit_code_two_on_missing_directory(self) -> None:
        result = self.run_cli("definitely-not-a-directory")
        self.assertEqual(result.returncode, 2)
        self.assertIn("error:", result.stderr)

    def test_exit_code_two_on_invalid_limit(self) -> None:
        result = self.run_cli(".", "--max-files", "0")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
