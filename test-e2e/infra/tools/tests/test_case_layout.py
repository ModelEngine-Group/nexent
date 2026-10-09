"""Static tests for the case-centric execution adapter."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml


TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[2]
sys.path.insert(0, str(TOOLS))

from generate_feature_links import expected_pages  # noqa: E402
from run_cases import d4_plan  # noqa: E402
from validate_execution import inspect  # noqa: E402
sys.path.insert(0, str(REPO / "test-e2e/infra/automation/d4"))
from control import enrich_contract  # noqa: E402


class CaseLayoutTests(unittest.TestCase):
    def test_case_registry_and_feature_navigation(self) -> None:
        issues, registry = inspect(REPO)
        self.assertEqual(issues, [])
        defined = {path.parent.name for path in (REPO / "test-e2e/cases").glob("*/case.yaml")}
        registered = [record["case_id"] for record in registry["cases"]]
        self.assertTrue(defined)
        self.assertEqual(set(registered), defined)
        self.assertEqual(len(registered), len(defined))
        features = {path.parent.name for path in (REPO / "test-e2e/features").glob("*/feature.yaml")}
        self.assertEqual({path.parent.name for path in expected_pages(REPO)}, features)

    def test_d4_queue_uses_case_local_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result_dir = Path(temporary)
            plan = d4_plan(REPO / "test-e2e/cases/PW-AGENT-01/case.yaml", result_dir)
            results = result_dir / "checkpoints/results.jsonl"
            results.parent.mkdir()
            queue = result_dir / "agent-input/d4-queue.json"
            control = REPO / "test-e2e/infra/automation/d4/control.py"
            completed = subprocess.run(
                [sys.executable, str(control), "prepare", "--plan", str(plan),
                 "--results", str(results), "--result-dir", str(result_dir), "--output", str(queue)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            item = json.loads(queue.read_text(encoding="utf-8"))["items"][0]
            self.assertEqual(item["id"], "PW-AGENT-01")
            case = yaml.safe_load((REPO / "test-e2e/cases/PW-AGENT-01/case.yaml").read_text(encoding="utf-8"))["case"]
            self.assertEqual(len(item["step_items"]), len(case["steps"]))
            self.assertEqual(len(item["assertion_items"]), len(case["expected_results"]))

    def test_every_active_d4_contract_can_be_enriched(self) -> None:
        issues, registry = inspect(REPO)
        self.assertEqual(issues, [])
        active = [record for record in registry["cases"]
                  if record["stage"] == "D4" and record["status"] == "active"]
        self.assertTrue(active)
        with tempfile.TemporaryDirectory() as temporary:
            for record in active:
                case_id = record["case_id"]
                directory = Path(temporary) / case_id
                directory.mkdir()
                plan = d4_plan(REPO / "test-e2e/cases" / case_id / "case.yaml", directory)
                item = json.loads(plan.read_text(encoding="utf-8"))["items"][0]
                contract = enrich_contract(item)
                case = yaml.safe_load((REPO / "test-e2e/cases" / case_id / "case.yaml").read_text(encoding="utf-8"))["case"]
                self.assertEqual(len(contract["precondition_items"]), len(case["preconditions"]), case_id)
                self.assertEqual(len(contract["step_items"]), len(case["steps"]), case_id)
                self.assertEqual(len(contract["assertion_items"]), len(case["expected_results"]), case_id)


if __name__ == "__main__":
    unittest.main()
