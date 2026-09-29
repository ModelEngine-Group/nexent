"""Regression checks for case-local result classification and platform-safe bindings."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import run_cases  # noqa: E402
from test_asset_lib import implementation_hash  # noqa: E402


class RunnerOutcomeTests(unittest.TestCase):
    def test_implementation_hash_ignores_checkout_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "test.py"
            binding = [{"file": "test.py", "selector": "CASE-001"}]
            script.write_bytes(b"first\nsecond\n")
            lf_hash = implementation_hash(root, binding)
            script.write_bytes(b"first\r\nsecond\r\n")
            self.assertEqual(implementation_hash(root, binding), lf_hash)

    def test_pytest_skip_is_blocked_even_with_zero_process_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "test-home"
            code = (
                "import os; from pathlib import Path; "
                "Path(os.environ['RESULT_DIR'], 'junit.xml').write_text("
                "'<testsuite><testcase name=\"case\"><skipped message=\"missing asset\"/>'"
                "'</testcase></testsuite>')"
            )
            record = {"case_id": "AGT-001", "stage": "D3", "execution": {
                "implementations": [{"framework": "pytest"}]}}
            with patch.object(run_cases, "command_for", return_value=([[sys.executable, "-c", code]], root)):
                case_id, status, result_dir = run_cases.run_one(record, root, home, {})
            self.assertEqual(case_id, "AGT-001")
            self.assertEqual(status, "BLOCKED")
            saved = json.loads((result_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["exit_code"], 0)
            self.assertEqual(saved["status"], "BLOCKED")
            self.assertEqual(saved["test_summary"]["skipped"], 1)

    def test_playwright_uses_case_file_with_unanchored_title_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            case_dir = repo / "test-e2e/cases/PW-AUTH-01"
            case_dir.mkdir(parents=True)
            (case_dir / "case.yaml").write_text(yaml.safe_dump({"case": {
                "case_id": "PW-AUTH-01", "priority": "P0", "title": "Login",
                "preconditions": [], "steps": [], "expected_results": [],
            }}), encoding="utf-8")
            (case_dir / "test.spec.ts").write_text('test("PW-AUTH-01", () => {});', encoding="utf-8")
            cli = repo / "test-e2e/infra/automation/d4/node_modules/playwright/cli.js"
            cli.parent.mkdir(parents=True)
            cli.touch()
            record = {"case_id": "PW-AUTH-01", "execution": {"implementations": [{
                "framework": "playwright", "file": "test-e2e/cases/PW-AUTH-01/test.spec.ts",
                "selector": "PW-AUTH-01",
            }]}}
            with patch.object(run_cases.shutil, "which", return_value="/usr/bin/node"):
                commands, _ = run_cases.command_for(record, repo, repo / "results", {})
            command = commands[1]
            self.assertEqual(command[command.index("--grep") + 1], "PW-AUTH-01")


if __name__ == "__main__":
    unittest.main()
