"""Offline resume tests: completed work is reused only with matching identity and cleanup."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import suite
import suite_resume
from suite_runtime import config_fingerprint, save


RECORDS = [
    {"case_id": "A-001", "stage": "D1", "status": "active", "execution": {"test": True}},
    {"case_id": "A-002", "stage": "D2", "status": "active", "execution": {"test": True}},
]
SOURCE_FINGERPRINT = {"head": "same", "test_assets_sha256": "assets",
                      "tracked_product_diff_sha256": "product", "untracked_product_sha256": "untracked"}
SETTINGS = {"hooks": {}, "case_timeout_seconds": 20}


def interrupted_batch(home: Path) -> Path:
    source = home / "runs/repository-daily/original"
    source.mkdir(parents=True)
    save(source / "provenance.json", {**SOURCE_FINGERPRINT, "config_sha256": config_fingerprint(home),
                                      "batch_mode": "run", "full_static_assets": False,
                                      "required_static_assets": []})
    save(source / "plan.json", {"cases": RECORDS})
    save(source / "pipeline.json", SETTINGS)
    save(source / "summary.json", {"status": "INCOMPLETE", "execution_complete": False,
                                   "error": "Interrupted", "counts": {"PASS": 1, "NOT_EXECUTED": 1}})
    save(source / "status.json", {"status": "INCOMPLETE", "stages": {"D0": "COMPLETE"}})
    save(source / "cases/A-001/receipt.json", {"case_id": "A-001", "stage": "D1",
                                              "result": "PASS", "cleanup_exit_code": 0})
    (source / "results.journal.jsonl").write_text(
        json.dumps({"case_id": "A-001", "stage": "D1", "result": "PASS", "evidence": []}) + "\n",
        encoding="utf-8")
    return source


class ResumeTests(unittest.TestCase):
    def test_resume_cli_previews_without_starting_cases(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            repo, home = base / "repo", base / "home"
            repo.mkdir()
            home.mkdir()
            source = home / "runs/repository-daily/original"
            preview = {"source": source, "records": RECORDS, "rows": [{"case_id": "A-001"}]}
            with patch.object(suite, "repository_root", return_value=repo), \
                    patch.object(suite, "config", return_value=SETTINGS), \
                    patch.object(suite, "inspect", return_value=([], {"cases": RECORDS})), \
                    patch.object(suite, "prepare_resume", return_value=preview), \
                    patch.object(suite, "execute") as execute:
                self.assertEqual(suite.main(["resume", "--test-home", str(home),
                                             "--batch-dir", str(source)]), 0)
                execute.assert_not_called()

    def test_graceful_interruption_produces_a_resumable_incomplete_batch(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)

            def interrupt_after_first(command, cwd, env, log, timeout):
                if "--batch-dir" not in command:
                    return 0
                case_id = command[command.index("--case") + 1]
                if case_id == "A-002":
                    raise KeyboardInterrupt
                batch = Path(command[command.index("--batch-dir") + 1])
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text("completed\n", encoding="utf-8")
                save(batch / "cases" / case_id / "receipt.json", {
                    "case_id": case_id, "stage": "D1", "result": "PASS", "cleanup_exit_code": 0})
                return 0

            with patch.object(suite, "machine_environment", return_value=dict(os.environ)), \
                    patch.object(suite, "fingerprint", return_value=SOURCE_FINGERPRINT), \
                    patch.object(suite, "static_requirements", return_value=set()), \
                    patch.object(suite, "static_inventory", return_value=[]), \
                    patch.object(suite, "logged", side_effect=interrupt_after_first):
                self.assertEqual(suite.execute(home, home, RECORDS, SETTINGS), 1)
            source = next((home / "runs/repository-daily").iterdir())
            summary = json.loads((source / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["counts"], {"PASS": 1, "NOT_EXECUTED": 1})
            self.assertFalse(summary["execution_complete"])
            with patch.object(suite_resume, "fingerprint", return_value=SOURCE_FINGERPRINT):
                resume = suite_resume.prepare_resume(home, home, source, SETTINGS, RECORDS)
            self.assertEqual([row["case_id"] for row in resume["rows"]], ["A-001"])

    def test_resume_reuses_clean_prefix_and_executes_only_remainder(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            source = interrupted_batch(home)
            with patch.object(suite_resume, "fingerprint", return_value=SOURCE_FINGERPRINT):
                resume = suite_resume.prepare_resume(home, home, source, SETTINGS, RECORDS)
            executed = []

            def command_result(command, cwd, env, log, timeout):
                if "--batch-dir" in command:
                    case_id = command[command.index("--case") + 1]
                    executed.append(case_id)
                    batch = Path(command[command.index("--batch-dir") + 1])
                    save(batch / "cases" / case_id / "receipt.json", {
                        "case_id": case_id, "stage": "D2", "result": "PASS", "cleanup_exit_code": 0})
                return 0

            with patch.object(suite, "machine_environment", return_value=dict(os.environ)), \
                    patch.object(suite, "fingerprint", return_value=SOURCE_FINGERPRINT), \
                    patch.object(suite, "static_requirements", return_value=set()), \
                    patch.object(suite, "static_inventory", return_value=[]), \
                    patch.object(suite, "logged", side_effect=command_result):
                self.assertEqual(suite.execute(home, home, RECORDS, SETTINGS, resume=resume), 0)
            self.assertEqual(executed, ["A-002"])
            marker = json.loads((source / "resume-child.json").read_text(encoding="utf-8"))
            child = Path(marker["child"])
            summary = json.loads((child / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["counts"], {"PASS": 2})
            self.assertTrue(summary["execution_complete"])
            with patch.object(suite_resume, "fingerprint", return_value=SOURCE_FINGERPRINT):
                with self.assertRaisesRegex(ValueError, "resume child"):
                    suite_resume.prepare_resume(home, home, source, SETTINGS, RECORDS)

    def test_resume_rejects_source_or_config_drift(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            source = interrupted_batch(home)
            with patch.object(suite_resume, "fingerprint", return_value={**SOURCE_FINGERPRINT, "head": "changed"}):
                with self.assertRaisesRegex(ValueError, "HEAD"):
                    suite_resume.prepare_resume(home, home, source, SETTINGS, RECORDS)
            config = home / "config"
            config.mkdir()
            (config / "daily.env").write_text("NEW=value\n", encoding="utf-8")
            with patch.object(suite_resume, "fingerprint", return_value=SOURCE_FINGERPRINT):
                with self.assertRaisesRegex(ValueError, "config differs"):
                    suite_resume.prepare_resume(home, home, source, SETTINGS, RECORDS)

    def test_resume_refuses_uncertain_cleanup_and_unrecorded_work(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            source = interrupted_batch(home)
            save(source / "cases/A-001/receipt.json", {"case_id": "A-001", "stage": "D1",
                                                      "result": "PASS", "cleanup_exit_code": 1})
            with patch.object(suite_resume, "fingerprint", return_value=SOURCE_FINGERPRINT):
                with self.assertRaisesRegex(ValueError, "clean receipt"):
                    suite_resume.prepare_resume(home, home, source, SETTINGS, RECORDS)
            save(source / "cases/A-001/receipt.json", {"case_id": "A-001", "stage": "D1",
                                                      "result": "PASS", "cleanup_exit_code": 0})
            (source / "cases/A-002").mkdir()
            with patch.object(suite_resume, "fingerprint", return_value=SOURCE_FINGERPRINT):
                with self.assertRaisesRegex(ValueError, "unrecorded Case"):
                    suite_resume.prepare_resume(home, home, source, SETTINGS, RECORDS)


if __name__ == "__main__":
    unittest.main()
