"""Verify exception-only reports preserve complete local execution evidence."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from suite_runtime import finalize, render_report, report_metrics


class SuiteReportTests(unittest.TestCase):
    def test_exception_only_details_and_full_checkpoints(self):
        statuses = ["PASS", "FAIL", "BLOCKED", "AUTOMATION_ERROR", "RETIRED", "SKIPPED_BY_POLICY",
                    "CLEANUP_FAILED", "BLOCKED_BY_DEPENDENCY", "EXECUTION_FAILED", "TIMEOUT"]
        rows = [{"case_id": f"C-{i}", "stage": "D4", "result": status,
                 "title": f"title-{i}", "reason": "expected | observed\nnext"}
                for i, status in enumerate(statuses)]
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            summary = finalize(directory, rows, rows)
            report = (directory / "report.md").read_text(encoding="utf-8")
            self.assertIn("**10.00%** (1 / 10)", report)
            self.assertIn("**12.50%** (1 / 8)", report)
            self.assertIn("| D4 | 10 | 1 | 7 | 2 | 10.00% |", report)
            for i in [0, 4, 5]:
                self.assertNotIn(f"| C-{i} |", report)
            for i in [1, 2, 3, 6, 7, 8, 9]:
                self.assertIn(f"| C-{i} |", report)
            self.assertIn("expected \\| observed<br>next", report)
            checkpoint = (directory / "checkpoints/results.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(checkpoint), 10)
            self.assertEqual(json.loads(checkpoint[0])["result"], "PASS")
            before = (directory / "summary.json").read_bytes()
            render_report(directory, rows, rows, summary)
            self.assertEqual((directory / "summary.json").read_bytes(), before)

    def test_missing_case_remains_in_denominator_and_details(self):
        plan = [{"case_id": "A", "stage": "D1"}, {"case_id": "B", "stage": "D2"}]
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            finalize(directory, plan, [{"case_id": "A", "stage": "D1", "result": "PASS"}], "Interrupted")
            report = (directory / "report.md").read_text(encoding="utf-8")
            self.assertIn("**50.00%** (1 / 2)", report)
            self.assertIn("| B | D2 |", report)
            self.assertIn("NOT_EXECUTED", report)

    def test_zero_cases_and_all_excluded_have_no_false_pass_rate(self):
        self.assertIsNone(report_metrics([], [])['overall_pass_rate'])
        row = {"case_id": "R", "stage": "D4", "result": "RETIRED"}
        self.assertIsNone(report_metrics([row], [row])['applicable_pass_rate'])

    def test_duplicates_and_unexpected_results_do_not_inflate_rate(self):
        row = {"case_id": "A", "stage": "D1", "result": "PASS"}
        other = {"case_id": "OTHER", "stage": "D1", "result": "PASS"}
        self.assertEqual(report_metrics([row], [row, row, other])["passed"], 0)

    def test_all_pass_report_has_no_case_details(self):
        row = {"case_id": "A", "stage": "D1", "result": "PASS"}
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            finalize(directory, [row], [row])
            report = (directory / "report.md").read_text(encoding="utf-8")
            self.assertIn("**100.00%**", report)
            self.assertIn("No non-passing cases.", report)
            self.assertNotIn("| A |", report)

    def test_details_are_grouped_by_stage_with_explicit_empty_stage(self):
        rows = [{"case_id": "A", "stage": "D1", "result": "PASS"},
                {"case_id": "B", "stage": "D2", "result": "FAIL"},
                {"case_id": "C", "stage": "D4", "result": "BLOCKED"}]
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            finalize(directory, rows, rows)
            report = (directory / "report.md").read_text(encoding="utf-8")
            self.assertIn("### D1 — 0 not passed\n\nNo non-passing cases in this stage.", report)
            d2 = report.split("### D2 — 1 not passed", 1)[1].split("### D4", 1)[0]
            d4 = report.split("### D4 — 1 not passed", 1)[1]
            self.assertIn("| B | D2 |", d2)
            self.assertNotIn("| C |", d2)
            self.assertIn("| C | D4 |", d4)
            self.assertNotIn("| B |", d4)


if __name__ == "__main__":
    unittest.main()
