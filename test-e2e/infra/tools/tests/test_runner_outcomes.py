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
    def playwright_run(self, root: Path, outcome: str, *, audit_code: int = 0,
                       browser_code: int = 1, duplicate: bool = False) -> tuple[dict, list[int]]:
        home = root / "test-home"
        directory = home / "runs/case"
        directory.mkdir(parents=True)
        (directory / "checkpoints").mkdir()
        evidence_dir = directory / "d4/PW-TEST-01"
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "status.json").write_text(json.dumps({
            "case_id": "PW-TEST-01", "status": outcome}), encoding="utf-8")
        (evidence_dir / "assertions.json").write_text(json.dumps({
            "cleanup": {"status": "PASS"}}), encoding="utf-8")
        row = {"case_id": "PW-TEST-01", "stage": "D4", "result": outcome,
               "failure_reason": "step failed; credential-fixture", "evidence": ["d4/PW-TEST-01/trace.zip"]}
        (directory / "checkpoints/results.jsonl").write_text(
            (json.dumps(row) + "\n") * (2 if duplicate else 1), encoding="utf-8")
        record = {"case_id": "PW-TEST-01", "stage": "D4", "execution": {
            "implementations": [{"framework": "playwright"}]}}
        attempted = []

        def process(command, **kwargs):
            number = int(command[0])
            attempted.append(number)
            return type("Result", (), {"returncode": {1: 0, 2: browser_code, 3: audit_code}[number]})()

        with patch.object(run_cases, "command_for", return_value=([["1"], ["2"], ["3"]], root)), \
                patch.object(run_cases.subprocess, "run", side_effect=process):
            run_cases.run_one(record, root, home, {"MODEL_API_KEY": "credential-fixture"}, result_dir=directory)
        return json.loads((directory / "status.json").read_text(encoding="utf-8")), attempted

    def test_failed_playwright_still_audits_and_preserves_terminal_classification(self) -> None:
        for outcome in ("FAIL", "TIMEOUT", "AUTOMATION_ERROR", "BLOCKED_BY_DEPENDENCY"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temporary:
                saved, attempted = self.playwright_run(Path(temporary), outcome)
                self.assertEqual(attempted, [1, 2, 3])
                self.assertEqual(saved["status"], outcome)
                self.assertEqual(saved["exit_code"], 1)
                self.assertIn("step failed", saved["reason"])
                self.assertNotIn("credential-fixture", saved["reason"])
                self.assertEqual(saved["evidence"], ["d4/PW-TEST-01/trace.zip"])

    def test_invalid_d4_audit_cannot_be_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            saved, _ = self.playwright_run(Path(temporary), "PASS", audit_code=1, browser_code=0)
            self.assertEqual(saved["status"], "AUTOMATION_ERROR")

    def test_duplicate_d4_terminal_record_cannot_be_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            saved, _ = self.playwright_run(Path(temporary), "PASS", duplicate=True, browser_code=0)
            self.assertEqual(saved["status"], "AUTOMATION_ERROR")

    def test_d4_pass_with_failed_process_cannot_be_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            saved, _ = self.playwright_run(Path(temporary), "PASS")
            self.assertEqual(saved["status"], "AUTOMATION_ERROR")

    def test_implementation_hash_ignores_checkout_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "test.py"
            binding = [{"file": "test.py", "selector": "CASE-001"}]
            script.write_bytes(b"first\nsecond\n")
            lf_hash = implementation_hash(root, binding)
            script.write_bytes(b"first\r\nsecond\r\n")
            self.assertEqual(implementation_hash(root, binding), lf_hash)

    def test_node_spec_and_tap_reporters_preserve_pass_fail_and_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "step-1.log"
            for prefix in ("#", "ℹ"):
                with self.subTest(prefix=prefix):
                    log.write_text(f"{prefix} tests 4\n{prefix} pass 4\n{prefix} fail 0\n", encoding="utf-8")
                    self.assertEqual(run_cases.tap_outcome(log)[0], "PASS")
                    log.write_text(f"{prefix} tests 4\n{prefix} pass 3\n{prefix} fail 1\n", encoding="utf-8")
                    self.assertEqual(run_cases.tap_outcome(log)[0], "FAIL")
                    log.write_text(f"{prefix} tests 4\n{prefix} pass 3\n{prefix} cancelled 1\n", encoding="utf-8")
                    self.assertEqual(run_cases.tap_outcome(log)[0], "BLOCKED")

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
            self.assertEqual(command[command.index("--config") + 2], "PW-AUTH-01/test.spec.ts")
            self.assertEqual(command[command.index("--grep") + 1], "PW-AUTH-01")


if __name__ == "__main__":
    unittest.main()
