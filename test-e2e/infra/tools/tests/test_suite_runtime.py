# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
        samples = [
            ("D4", {}, 1800, 660),
            ("D4", {}, 400, 460),
            ("D4", {"timeout_seconds": 900}, 1800, 960),
            ("D5", {"timeout_seconds": 4800}, 1800, 4800),
        ]
        for stage, execution, default, expected in samples:
            with self.subTest(stage=stage, execution=execution, default=default), tempfile.TemporaryDirectory() as root:
                home = Path(root)
                case_id = f"SYNTHETIC-{stage}-TIMEOUT"
                records = [{"case_id": case_id, "stage": stage, "status": "active",
                            "execution": {"test": True, **execution}}]
                observed = []

                def command_result(command, cwd, env, log, timeout):
                    if "--batch-dir" in command:
                        observed.append(timeout)
                        batch = Path(command[command.index("--batch-dir") + 1])
                        save(batch / "cases" / case_id / "receipt.json", {
                            "case_id": case_id, "stage": stage, "result": "PASS", "cleanup_exit_code": 0})
                    return 0

                with patch.object(suite, "machine_environment", return_value=dict(os.environ)), \
                        patch.object(suite, "fingerprint", return_value={"head": "test"}), \
                        patch.object(suite, "static_requirements", return_value=set()), \
                        patch.object(suite, "static_inventory", return_value=[]), \
                        patch.object(suite, "logged", side_effect=command_result):
                    self.assertEqual(suite.execute(home, home, records,
                                                   {"hooks": {}, "case_timeout_seconds": default}), 0)
                self.assertEqual(observed, [expected])

    def test_tfp_controller_cleans_registered_case_assets_after_worker_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            directory = home / "runs/repository-daily/test-tfp"
            case_id = "TFP-D3-001"
            case_dir = directory / "cases" / case_id
            records = [{"case_id": case_id, "stage": "D3", "status": "active", "execution": {"test": True}}]

            def execute(command, cwd, env, log, timeout):
                if "--case" in command:
                    self.assertEqual(env["NEXENT_CASE_DEPLOYMENT_PROFILE"], "tfp")
                    save(case_dir / "runtime/resolved-assets.yaml", {"assets": {}})
                    return 124
                if "shared.asset_cleanup" in command:
                    self.assertEqual(env["RESULT_DIR"], str(case_dir))
                    self.assertIn("--force", command)
                    (case_dir / "runtime/cleanup-results.jsonl").write_text('{"result":"DELETED"}\n', encoding="utf-8")
                return 0

            with (patch.object(suite, "machine_environment", return_value={}),
                  patch.object(suite, "fingerprint", return_value={"head": "test"}),
                  patch.object(suite, "static_requirements", return_value=set()),
                  patch.object(suite, "static_inventory", return_value=[]),
                  patch.object(suite, "runtime_blocks", return_value={}),
                  patch.object(suite, "logged", side_effect=execute)):
                settings = {"hooks": {}, "case_timeout_seconds": 20, "command_timeout_seconds": 120}
                self.assertEqual(suite._execute(home, home, records, settings, directory=directory, deployment_profile="tfp"), 1)
            self.assertTrue((case_dir / "runtime/cleanup-results.jsonl").is_file())
            summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["counts"], {"TIMEOUT": 1})

    def test_notification_refuses_nonterminal(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            save(directory / "summary.json", {"status": "RUNNING", "execution_complete": False})
            with patch.object(suite_notify, "logged") as send:
                self.assertEqual(suite_notify.send_report(directory, {}), "NOT_TERMINAL")
                send.assert_not_called()

    def test_case_failures_and_fault_marker_do_not_stop_independent_cases(self):
        for outcome, fault in (("FAIL", False), ("TIMEOUT", False), ("CLEANUP_FAILED", False), ("PASS", True)):
            with self.subTest(outcome=outcome, fault=fault), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                records = [{"case_id": case_id, "stage": "D5", "status": "active", "execution": {"test": True}}
                           for case_id in ("FIRST", "INDEPENDENT")]
                calls = []

                def execute(command, cwd, env, log, timeout):
                    if "--case" in command:
                        case_id = command[command.index("--case") + 1]
                        batch = Path(command[command.index("--batch-dir") + 1])
                        calls.append(case_id)
                        save(batch / "cases" / case_id / "receipt.json", {
                            "case_id": case_id, "stage": "D5", "result": outcome if case_id == "FIRST" else "PASS"})
                        if fault:
                            save(home / "state/deployment-guard/pending.json", {"status": "PENDING"})
                    return 0

                with patch.object(suite, "machine_environment", return_value=dict(os.environ)), \
                        patch.object(suite, "fingerprint", return_value={"head": "test"}), \
                        patch.object(suite, "static_requirements", return_value=set()), \
                        patch.object(suite, "static_inventory", return_value=[]), \
                        patch.object(suite, "logged", side_effect=execute):
                    self.assertEqual(suite.execute(home, home, records, {"hooks": {}, "case_timeout_seconds": 20}),
                                     int(outcome != "PASS"))
                batch = next((home / "runs/repository-daily").iterdir())
                summary = json.loads((batch / "summary.json").read_text())
                self.assertEqual(calls, ["FIRST", "INDEPENDENT"])
                self.assertTrue(summary["execution_complete"])
                self.assertEqual(summary["counts"].get(outcome), 2 if outcome == "PASS" else 1)
                if fault:
                    self.assertTrue((home / "state/deployment-guard/pending.json").exists())

    def test_notification_deduplicates_uncertain_delivery(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            save(directory / "summary.json", {"status": "FAILED", "d6_complete": True, "execution_complete": True})
            with patch.object(suite_notify, "logged", return_value=124) as send:
                env = {"LARK_CLI": "test-cli", "FEISHU_REPORT_CHAT_ID": "test-chat"}
                self.assertEqual(suite_notify.send_report(directory, env), "UNKNOWN")
                self.assertEqual(suite_notify.send_report(directory, env), "UNKNOWN")
                self.assertEqual(send.call_count, 1)

    def test_notification_sends_once_after_complete_report(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            save(directory / "summary.json", {"status": "PASSED", "d6_complete": True, "execution_complete": True})
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
                receipt = json.loads((directory / "receipt.json").read_text())
                self.assertEqual(receipt["result"], "BLOCKED")
                self.assertEqual(receipt["blocked_phase"], "CASE_PREPARATION")

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

            def run(record, repo, home, env, *, result_dir, enforce_timeout):
                self.assertFalse(enforce_timeout)
                self.assertGreater(int(env["D4_CASE_TIMEOUT_MS"]), 0)
                self.assertLessEqual(int(env["D4_CASE_TIMEOUT_MS"]), 600_000)
                events.append("test")
                self.assertEqual(env["NEXENT_D4_CHAT_AGENT"], "owned-agent")
                self.assertEqual(result_dir, directory)
                return 0, "PASS", directory

            with patch.object(suite, "machine_environment", return_value={}), \
                 patch.object(suite, "controlled_services", side_effect=controlled), \
                 patch.object(suite, "logged", side_effect=command), \
                 patch.object(suite, "run_one", side_effect=run):
                self.assertEqual(suite.worker(Path(root), Path(root), record, directory,
                                             {"command_timeout_seconds": 10, "case_timeout_seconds": 1800}), 0)
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

            def run(record, repo, home, env, *, result_dir, enforce_timeout):
                self.assertFalse(enforce_timeout)
                save(result_dir / "status.json", {"reason": "STEP-02: configured element not found",
                     "evidence": ["d4/PW-TEST-01/trace.zip"], "cleanup_failed": True})
                save(result_dir / "runtime/resolved-assets.yaml", {})
                return "PW-TEST-01", "AUTOMATION_ERROR", result_dir

            with patch.object(suite, "machine_environment", return_value={}), \
                    patch.object(suite, "run_one", side_effect=run), \
                    patch.object(suite, "logged", return_value=0):
                self.assertEqual(suite.worker(Path(root), Path(root), record, directory,
                                               {"command_timeout_seconds": 10, "case_timeout_seconds": 1800}), 1)
            receipt = json.loads((directory / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["result"], "CLEANUP_FAILED")
            self.assertEqual(receipt["test_result"], "AUTOMATION_ERROR")
            self.assertEqual(receipt["cleanup_exit_code"], 1)
            self.assertIn("STEP-02", receipt["reason"])
            self.assertEqual(receipt["test_evidence"], ["d4/PW-TEST-01/trace.zip"])

    def test_existing_fault_marker_does_not_stop_batch_or_erase_cleanup_failures(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            records = [{"case_id": name, "stage": "D5", "status": "active", "execution": {"test": True}}
                       for name in ("SEC-002", "SEC-003")]
            started = []
            fault = home / "state/deployment-guard/pending.json"
            save(fault, {"status": "PENDING", "evidence": "previous-batch"})
            original = fault.read_bytes()

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
            self.assertEqual(started, ["SEC-002", "SEC-003"])
            self.assertEqual(summary["counts"], {"CLEANUP_FAILED": 2})
            self.assertTrue(summary["execution_complete"])
            self.assertEqual(fault.read_bytes(), original)
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

    def test_missing_static_asset_blocks_its_case_without_interrupting_the_batch(self):
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
            summary = json.loads((batch / "summary.json").read_text())
            self.assertEqual(summary["counts"], {"BLOCKED": 1})
            self.assertTrue(summary["execution_complete"])
            self.assertEqual(json.loads((batch / "d0/static-assets.json").read_text())["assets"][0]["destination"], "MISSING")
            diagnostic = json.loads((batch / "cases/A-001/block-diagnostic.json").read_text())
            self.assertEqual(diagnostic["phase"], "STATIC_ASSET_PREFLIGHT")
            self.assertFalse(diagnostic["worker_started"])
            self.assertIn("AUD-001", diagnostic["reason"])
            self.assertIn("d0/static-assets.json", diagnostic["related_records"])

    def test_blocked_case_receipts_reach_the_same_batch_journal(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            directory = home / "batch"
            records = [
                {"case_id": "P-001", "stage": "D3", "status": "blocked", "automation": "automated", "execution": None},
                {"case_id": "P-002", "stage": "D3", "status": "active", "automation": "manual", "execution": None},
                {"case_id": "P-003", "stage": "D3", "status": "active", "execution": {"test": True}},
                {"case_id": "P-004", "stage": "D3", "status": "retired", "execution": None},
            ]
            definition = home / "test-e2e/cases/P-001/case.yaml"
            definition.parent.mkdir(parents=True)
            definition.write_text("case:\n  source:\n    blocked_reason: Missing fixture with demo-secret\n")
            notifications = []

            def command_result(command, cwd, env, log, timeout):
                if "--case" in command:
                    self.assertEqual(command[command.index("--case") + 1], "P-003")
                    case_dir = directory / "cases/P-003"
                    save(case_dir / "runtime/preparation-failure.json", {"result": "BLOCKED_BY_DEPENDENCY"})
                    save(case_dir / "receipt.json", {"case_id": "P-003", "stage": "D3",
                         "result": "BLOCKED_BY_DEPENDENCY", "reason": "Dependency unavailable",
                         "blocked_phase": "CASE_PREPARATION"})
                    return 1
                return 0

            def on_result(row):
                if row["result"] in suite.BLOCKED_RESULTS:
                    receipt = f"cases/{row['case_id']}/block-diagnostic.json"
                    self.assertIn(receipt, row["evidence"])
                    notifications.append(json.loads((directory / receipt).read_text()))

            with patch.object(suite, "machine_environment", return_value={"DEMO_TOKEN": "demo-secret"}), \
                 patch.object(suite, "fingerprint", return_value={"head": "test"}), \
                 patch.object(suite, "static_requirements", return_value=set()), \
                 patch.object(suite, "static_inventory", return_value=[]), \
                 patch.object(suite, "logged", side_effect=command_result):
                self.assertEqual(suite._execute(home, home, records, {"case_timeout_seconds": 10},
                                               directory=directory, on_result=on_result), 1)
            planned, manual, preparation = notifications
            self.assertEqual(planned["phase"], "CASE_PLAN")
            self.assertEqual(planned["related_records"], ["plan.json"])
            self.assertIn("Missing fixture with [REDACTED]", planned["reason"])
            self.assertFalse(planned["worker_started"])
            self.assertIn("Manual case", manual["reason"])
            self.assertEqual(preparation["phase"], "CASE_PREPARATION")
            self.assertTrue(preparation["worker_started"])
            self.assertIn("cases/P-003/runtime/preparation-failure.json", preparation["related_records"])
            self.assertFalse((directory / "cases/P-004").exists())
            journal = [json.loads(row) for row in (directory / "results.journal.jsonl").read_text().splitlines()]
            self.assertEqual([row["result"] for row in journal],
                             ["BLOCKED", "BLOCKED", "BLOCKED_BY_DEPENDENCY", "RETIRED"])


if __name__ == "__main__":
    unittest.main()
