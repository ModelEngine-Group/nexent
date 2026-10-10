"""Offline orchestration tests. Never deploy, notify, or contact product services."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import suite
import suite_notify
from suite_runtime import BatchLock, config_fingerprint, finalize, logged, save


class SuiteTests(unittest.TestCase):
    def test_missing_result_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            plan = [{"case_id": "A-001", "stage": "D1"}, {"case_id": "A-002", "stage": "D2"}]
            result = finalize(directory, plan, [{"case_id": "A-001", "stage": "D1", "result": "PASS"}], "Interrupted")
            self.assertFalse(result["execution_complete"])
            self.assertEqual(result["counts"], {"PASS": 1, "NOT_EXECUTED": 1})
            self.assertTrue((directory / "report.md").is_file())

    def test_blocked_is_failure_but_execution_can_be_complete(self):
        with tempfile.TemporaryDirectory() as root:
            row = {"case_id": "A-001", "stage": "D2", "result": "BLOCKED"}
            result = finalize(Path(root), [row], [row])
            self.assertEqual(result["status"], "FAILED")
            self.assertTrue(result["execution_complete"])

    def test_duplicate_records_invalidate_summary(self):
        with tempfile.TemporaryDirectory() as root:
            row = {"case_id": "A-001", "stage": "D1", "result": "PASS"}
            self.assertEqual(finalize(Path(root), [row], [row, row])["status"], "INCOMPLETE")

    def test_process_timeout(self):
        with tempfile.TemporaryDirectory() as root:
            code = logged([sys.executable, "-c", "import time; time.sleep(20)"], Path(root), dict(os.environ), Path(root) / "log", 0.2)
            self.assertEqual(code, 124)

    def test_lock_exclusion(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "daily.lock"
            with BatchLock(path):
                with self.assertRaisesRegex(RuntimeError, "another daily run"):
                    with BatchLock(path):
                        pass
            with BatchLock(path):
                pass

    def test_refreshed_anchor_registry_does_not_change_operator_config_identity(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            config = home / "config"
            config.mkdir()
            (config / "pipeline.yaml").write_text("schema_version: 1\n", encoding="utf-8")
            anchor = config / "anchor-assets.yaml"
            anchor.write_text("tenant_a_id: old\n", encoding="utf-8")
            original = config_fingerprint(home)

            anchor.write_text("tenant_a_id: refreshed\n", encoding="utf-8")
            self.assertEqual(config_fingerprint(home), original)

            (config / "pipeline.yaml").write_text("schema_version: 2\n", encoding="utf-8")
            self.assertNotEqual(config_fingerprint(home), original)

    def test_batch_continues_after_case_refreshes_anchor_registry(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            config = home / "config"
            config.mkdir()
            anchor = config / "anchor-assets.yaml"
            anchor.write_text("tenant_a_id: old\n", encoding="utf-8")
            records = [
                {"case_id": "A-001", "stage": "D2", "status": "active", "execution": {"test": True}},
                {"case_id": "A-002", "stage": "D2", "status": "active", "execution": {"test": True}},
            ]

            def command_result(command, cwd, env, log, timeout):
                if "--batch-dir" in command:
                    batch = Path(command[command.index("--batch-dir") + 1])
                    case_id = command[command.index("--case") + 1]
                    if case_id == "A-001":
                        anchor.write_text("tenant_a_id: refreshed\n", encoding="utf-8")
                    save(batch / "cases" / case_id / "receipt.json", {
                        "case_id": case_id, "stage": "D2", "result": "PASS", "cleanup_exit_code": 0})
                return 0

            with patch.object(suite, "machine_environment", return_value=dict(os.environ)), \
                    patch.object(suite, "fingerprint", return_value={"head": "test"}), \
                    patch.object(suite, "static_requirements", return_value=set()), \
                    patch.object(suite, "static_inventory", return_value=[]), \
                    patch.object(suite, "logged", side_effect=command_result):
                self.assertEqual(suite.execute(home, home, records, {"hooks": {}, "case_timeout_seconds": 20}), 0)
            batch = next((home / "runs/repository-daily").iterdir())
            summary = json.loads((batch / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["counts"], {"PASS": 2})
            self.assertTrue(summary["execution_complete"])

    def test_case_local_timeout_overrides_machine_default(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            records = [{"case_id": "SYNTHETIC-D5-TIMEOUT", "stage": "D5", "status": "active",
                        "execution": {"test": True, "timeout_seconds": 4800}}]
            observed = []

            def command_result(command, cwd, env, log, timeout):
                if "--batch-dir" in command:
                    observed.append(timeout)
                    batch = Path(command[command.index("--batch-dir") + 1])
                    save(batch / "cases/SYNTHETIC-D5-TIMEOUT/receipt.json", {
                        "case_id": "SYNTHETIC-D5-TIMEOUT", "stage": "D5", "result": "PASS", "cleanup_exit_code": 0})
                return 0

            with patch.object(suite, "machine_environment", return_value=dict(os.environ)), \
                    patch.object(suite, "fingerprint", return_value={"head": "test"}), \
                    patch.object(suite, "static_requirements", return_value=set()), \
                    patch.object(suite, "static_inventory", return_value=[]), \
                    patch.object(suite, "logged", side_effect=command_result):
                self.assertEqual(suite.execute(home, home, records,
                                               {"hooks": {}, "case_timeout_seconds": 1800}), 0)
            self.assertEqual(observed, [4800])

    def test_notification_refuses_incomplete(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            save(directory / "summary.json", {"d6_complete": True, "execution_complete": False})
            with patch.object(suite_notify, "logged") as send:
                self.assertEqual(suite_notify.send_report(directory, {}), "INCOMPLETE_NOT_SENT")
                send.assert_not_called()

    def test_notification_deduplicates_uncertain_delivery(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            save(directory / "summary.json", {"d6_complete": True, "execution_complete": True})
            with patch.object(suite_notify, "logged", return_value=124) as send:
                env = {"LARK_CLI": "test-cli", "FEISHU_REPORT_CHAT_ID": "test-chat"}
                self.assertEqual(suite_notify.send_report(directory, env), "UNKNOWN")
                self.assertEqual(suite_notify.send_report(directory, env), "UNKNOWN")
                self.assertEqual(send.call_count, 1)

    def test_notification_sends_once_after_complete_report(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            save(directory / "summary.json", {"d6_complete": True, "execution_complete": True})
            with patch.object(suite_notify, "logged", return_value=0) as send:
                env = {"LARK_CLI": "test-cli", "FEISHU_REPORT_CHAT_ID": "test-chat"}
                self.assertEqual(suite_notify.send_report(directory, env), "SENT")
                self.assertEqual(suite_notify.send_report(directory, env), "SENT")
                send.assert_called_once()

    def test_change_selection_uses_existing_delta_schema(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root)
            change = repo / "test-e2e/changes/bugs/B-001.yaml"
            change.parent.mkdir(parents=True)
            change.write_text("change:\n  change_id: B-001\n  affected_cases:\n    modified: [A-002]\n", encoding="utf-8")
            args = argparse.Namespace(case=None, feature=None, stage=None, change="B-001")
            records = [{"case_id": "A-001", "stage": "D1"}, {"case_id": "A-002", "stage": "D2"}]
            with patch.object(suite, "inspect", return_value=([], {"cases": records})):
                self.assertEqual([row["case_id"] for row in suite.selection(repo, args)], ["A-002"])

    def test_missing_preparation_is_blocked_before_product_access(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "run"
            record = {"case_id": "A-001", "stage": "D3", "execution": {"implementation_hash": "sha256:" + "a" * 64}}
            with patch.object(suite, "machine_environment", return_value={}), patch.object(suite, "run_one") as run:
                suite.worker(Path(root), Path(root), record, directory, {})
                run.assert_not_called()
                self.assertEqual(json.loads((directory / "receipt.json").read_text())["result"], "BLOCKED")

    def test_preparation_needs_no_hash_approval(self):
        for implementation_hash in ("sha256:" + "a" * 64, "sha256:" + "b" * 64):
            with self.subTest(implementation_hash=implementation_hash), tempfile.TemporaryDirectory() as root:
                directory = Path(root) / "run"
                record = {"case_id": "A-001", "stage": "D3", "execution": {
                    "implementation_hash": implementation_hash, "preparation": {"families": []}}}
                with patch.object(suite, "machine_environment", return_value={}), \
                     patch.object(suite, "run_one", return_value=(0, "PASS", directory)) as run:
                    self.assertEqual(suite.worker(Path(root), Path(root), record, directory, {}), 0)
                    run.assert_called_once()
                    self.assertEqual(json.loads((directory / "receipt.json").read_text())["result"], "PASS")

    def test_preparation_schema_accepts_declaration_but_rejects_unknown_factory(self):
        from jsonschema import Draft202012Validator
        schema_path = Path(__file__).resolve().parents[2] / "schemas/preparation.schema.json"
        validator = Draft202012Validator(json.loads(schema_path.read_text()))
        self.assertEqual(list(validator.iter_errors({"families": [], "anchors": True})), [])
        self.assertTrue(list(validator.iter_errors({"families": ["invented_factory"]})))

    def test_preparation_test_cleanup_order_and_case_local_output(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "run"
            record = {"case_id": "A-001", "stage": "D4", "execution": {"preparation": {
                "families": ["basic_agent"], "anchors": True, "special_assets": True,
                "d4_groups": ["chat"]}}}
            events = []

            @contextmanager
            def controlled(*args):
                events.append("services-start")
                try:
                    yield
                finally:
                    events.append("services-stop")

            def command(command, cwd, env, log, timeout, **kwargs):
                events.append(log.stem)
                registry = directory / "runtime/resolved-assets.yaml"
                registry.parent.mkdir(parents=True, exist_ok=True)
                registry.touch()
                if "--group" in command:
                    output = Path(command[command.index("--output") + 1])
                    self.assertEqual(output.parent, directory / "runtime")
                    output.write_text("export NEXENT_D4_CHAT_AGENT='owned-agent'\n")
                return 0

            def run(record, repo, home, env, *, result_dir):
                events.append("test")
                self.assertEqual(env["NEXENT_D4_CHAT_AGENT"], "owned-agent")
                self.assertEqual(result_dir, directory)
                return 0, "PASS", directory

            with patch.object(suite, "machine_environment", return_value={}), \
                 patch.object(suite, "controlled_services", side_effect=controlled), \
                 patch.object(suite, "logged", side_effect=command), \
                 patch.object(suite, "run_one", side_effect=run):
                self.assertEqual(suite.worker(Path(root), Path(root), record, directory,
                                             {"command_timeout_seconds": 10}), 0)
            self.assertEqual(events, ["services-start", "prepare-anchors", "prepare-basic_agent",
                                      "prepare-special", "prepare-d4", "test", "cleanup", "services-stop"])

    def test_failed_preparation_still_cleans_registered_assets(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "run"
            record = {"case_id": "A-001", "stage": "D3", "execution": {
                "preparation": {"families": ["basic_agent"]}}}
            commands = []

            def command(command, cwd, env, log, timeout, **kwargs):
                commands.append(log.stem)
                registry = directory / "runtime/resolved-assets.yaml"
                registry.parent.mkdir(parents=True, exist_ok=True)
                registry.touch()
                return 0 if log.stem == "cleanup" else 124

            with patch.object(suite, "machine_environment", return_value={}), \
                 patch.object(suite, "logged", side_effect=command), patch.object(suite, "run_one") as run:
                self.assertEqual(suite.worker(Path(root), Path(root), record, directory,
                                             {"command_timeout_seconds": 10}), 1)
                run.assert_not_called()
            self.assertEqual(commands, ["prepare-basic_agent", "cleanup"])
            receipt = json.loads((directory / "receipt.json").read_text())
            self.assertEqual(receipt["result"], "TIMEOUT")
            self.assertEqual(receipt["cleanup_exit_code"], 0)

    def test_worker_preserves_journey_reason_and_separate_cleanup_failure(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "run"
            record = {"case_id": "PW-TEST-01", "stage": "D4", "execution": {
                "preparation": {"families": []}}}

            def run(record, repo, home, env, *, result_dir):
                save(result_dir / "status.json", {"reason": "STEP-02: configured element not found",
                     "evidence": ["d4/PW-TEST-01/trace.zip"], "cleanup_failed": True})
                save(result_dir / "runtime/resolved-assets.yaml", {})
                return "PW-TEST-01", "AUTOMATION_ERROR", result_dir

            with patch.object(suite, "machine_environment", return_value={}), \
                    patch.object(suite, "run_one", side_effect=run), \
                    patch.object(suite, "logged", return_value=0):
                self.assertEqual(suite.worker(Path(root), Path(root), record, directory,
                                               {"command_timeout_seconds": 10}), 1)
            receipt = json.loads((directory / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["result"], "CLEANUP_FAILED")
            self.assertEqual(receipt["test_result"], "AUTOMATION_ERROR")
            self.assertEqual(receipt["cleanup_exit_code"], 1)
            self.assertIn("STEP-02", receipt["reason"])
            self.assertEqual(receipt["test_evidence"], ["d4/PW-TEST-01/trace.zip"])

    def test_d5_cleanup_failure_stops_remaining_cases_and_finalizes_incomplete(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            records = [{"case_id": name, "stage": "D5", "status": "active", "execution": {"test": True}}
                       for name in ("SEC-002", "SEC-003")]
            started = []

            def command_result(command, cwd, env, log, timeout):
                if "--batch-dir" in command:
                    batch = Path(command[command.index("--batch-dir") + 1])
                    case_id = command[command.index("--case") + 1]
                    started.append(case_id)
                    save(batch / "cases" / case_id / "receipt.json", {
                        "case_id": case_id, "stage": "D5", "result": "CLEANUP_FAILED",
                        "test_result": "PASS", "cleanup_exit_code": 1})
                    return 1
                return 0

            with patch.object(suite, "machine_environment", return_value=dict(os.environ)), \
                    patch.object(suite, "fingerprint", return_value={"head": "test"}), \
                    patch.object(suite, "static_requirements", return_value=set()), \
                    patch.object(suite, "static_inventory", return_value=[]), \
                    patch.object(suite, "logged", side_effect=command_result):
                self.assertEqual(suite.execute(home, home, records, {"hooks": {}, "case_timeout_seconds": 20}), 1)
            summary = json.loads(next((home / "runs/repository-daily").iterdir()).joinpath("summary.json").read_text())
            self.assertEqual(started, ["SEC-002"])
            self.assertEqual(summary["counts"], {"CLEANUP_FAILED": 1, "NOT_EXECUTED": 1})
            self.assertFalse(summary["execution_complete"])
            self.assertTrue(summary["d6_complete"])

    def test_batch_continues_after_case_failure(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            records = [{"case_id": "A-001", "stage": "D1", "status": "active", "execution": {"test": True}},
                       {"case_id": "A-002", "stage": "D2", "status": "active", "execution": {"test": True}}]
            def command_result(command, cwd, env, log, timeout):
                if "--batch-dir" in command:
                    batch = Path(command[command.index("--batch-dir") + 1])
                    case_id = command[command.index("--case") + 1]
                    save(batch / "cases" / case_id / "receipt.json", {
                        "case_id": case_id, "stage": "D1" if case_id == "A-001" else "D2",
                        "result": "FAIL" if case_id == "A-001" else "PASS"})
                    return 1 if case_id == "A-001" else 0
                return 0
            with patch.object(suite, "machine_environment", return_value=dict(os.environ)), \
                 patch.object(suite, "fingerprint", return_value={"head": "test"}), \
                 patch.object(suite, "static_requirements", return_value=set()), \
                 patch.object(suite, "static_inventory", return_value=[]), \
                 patch.object(suite, "logged", side_effect=command_result):
                self.assertEqual(suite.execute(home, home, records, {"hooks": {}, "case_timeout_seconds": 20}), 1)
            batch = next((home / "runs/repository-daily").iterdir())
            summary = json.loads((batch / "summary.json").read_text())
            self.assertEqual(summary["counts"], {"FAIL": 1, "PASS": 1})
            self.assertTrue(summary["execution_complete"])

    def test_d0_missing_static_asset_prevents_case_worker(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            records = [{"case_id": "A-001", "stage": "D3", "status": "active", "execution": {"test": True}}]
            with patch.object(suite, "machine_environment", return_value=dict(os.environ)), \
                 patch.object(suite, "fingerprint", return_value={"head": "test"}), \
                 patch.object(suite, "static_requirements", return_value={"AUD-001"}), \
                 patch.object(suite, "static_inventory", return_value=[{
                     "asset_id": "AUD-001", "path": "audio/sample.pcm", "destination": "MISSING"}]), \
                 patch.object(suite, "logged", return_value=0) as command:
                self.assertEqual(suite.execute(home, home, records, {"hooks": {}}), 1)
                self.assertEqual(command.call_count, 1)  # Formal validator only.
            batch = next((home / "runs/repository-daily").iterdir())
            self.assertEqual(json.loads((batch / "summary.json").read_text())["counts"], {"NOT_EXECUTED": 1})
            self.assertEqual(json.loads((batch / "d0/static-assets.json").read_text())["assets"][0]["destination"], "MISSING")


if __name__ == "__main__":
    unittest.main()
