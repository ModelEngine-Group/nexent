"""Verify coverage isolation, branch data, and comparison evidence."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from coverage_support import python_report
from run_cases import command_for
from run_d1_coverage import audit_behaviors, compare_python


class D1CoverageTests(unittest.TestCase):
    def test_only_d1_can_enable_coverage_and_legacy_scope_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            record = {"stage": "D1", "case_id": "UNIT-01", "execution": {"implementations": [
                {"framework": "pytest", "file": "test.py"}]}}
            env = {}
            commands, _ = command_for(record, repo, repo / "results", env, coverage=True)
            self.assertIn(f"--cov={repo / 'backend'}", commands[0])
            self.assertIn(f"--cov={repo / 'sdk'}", commands[0])
            self.assertIn("--cov-branch", commands[0])
            self.assertIn("--cov-context=test", commands[0])
            self.assertEqual(env["COVERAGE_FILE"], str(repo / "results/coverage/python/.coverage"))
            record["stage"] = "D2"
            with self.assertRaisesRegex(ValueError, "only for D1"):
                command_for(record, repo, repo / "results", {}, coverage=True)
            commands, _ = command_for(record, repo, repo / "results", {})
            self.assertFalse(any(arg.startswith("--cov") for arg in commands[0]))

    def test_python_merge_preserves_contexts_and_reports_separate_metrics(self):
        import coverage
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "backend").mkdir()
            (repo / "sdk").mkdir()
            module = repo / "backend/unit.py"
            module.write_text("def choose(value):\n    if value:\n        return 1\n    return 0\n", encoding="utf-8")
            data_files = []
            for suite, value in (("legacy", True), ("d1", False)):
                raw = repo / suite / "raw"
                raw.mkdir(parents=True)
                cov = coverage.Coverage(data_file=str(raw / ".coverage"), source=[str(repo / "backend"), str(repo / "sdk")],
                                        branch=True, config_file=False)
                cov.start()
                cov.switch_context(f"test/unit.py::test_{suite}|run")
                spec = importlib.util.spec_from_file_location(f"fixture_{suite}", module)
                loaded = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(loaded)
                self.assertEqual(loaded.choose(value), int(value))
                cov.stop()
                cov.save()
                data_files.append(raw / ".coverage")
                summary = python_report(repo, repo / suite / "python", [raw / ".coverage"])
                self.assertEqual(summary["scope"], ["backend", "sdk"])
                self.assertEqual(summary["lines"]["covered"], 3)
                self.assertEqual(summary["branches"]["total"], 2)
                self.assertEqual(summary["branches"]["covered"], 1)
            comparison = compare_python(repo, repo)
            self.assertEqual(comparison["legacy_only_lines"], 1)
            self.assertEqual(comparison["d1_only_lines"], 1)
            self.assertEqual(comparison["legacy_only_branches"], 1)
            self.assertTrue(comparison["comparable_inventory"])
            summary = python_report(repo, repo / "merged", data_files)
            self.assertEqual(summary["branches"]["percent"], 100)
            data = coverage.CoverageData(basename=str(repo / "merged/.coverage"))
            data.read()
            self.assertIn("test/unit.py::test_legacy|run", data.measured_contexts())
            self.assertIn("test/unit.py::test_d1|run", data.measured_contexts())

    def test_frontend_and_python_outputs_are_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            package = repo / "test-e2e/infra/automation/d1/frontend"
            binary = package / "node_modules/vitest/vitest.mjs"
            binary.parent.mkdir(parents=True)
            binary.touch()
            record = {"stage": "D1", "case_id": "COMP-01", "execution": {"implementations": [
                {"framework": "vitest", "file": "component.test.tsx"}]}}
            commands, _ = command_for(record, repo, repo / "results", {}, coverage=True)
            self.assertIn("--coverage", commands[0])
            self.assertIn(f"--coverage.reportsDirectory={repo / 'results/coverage/frontend'}", commands[0])
            self.assertFalse(any(arg.startswith("--cov=") for arg in commands[0]))

    def test_empty_source_inspection_data_is_not_mixed_with_branch_data(self):
        import coverage
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "backend").mkdir()
            (repo / "sdk").mkdir()
            module = repo / "backend/unit.py"
            module.write_text("def choose(value):\n    if value:\n        return 1\n    return 0\n", encoding="utf-8")
            valid = coverage.CoverageData(basename=str(repo / "valid"))
            valid.add_arcs({str(module): [(-1, 1), (1, -1)]})
            valid.write()
            empty = coverage.CoverageData(basename=str(repo / "empty"))
            empty.add_lines({str(module): []})
            empty.write()
            summary = python_report(repo, repo / "reports", [repo / "valid", repo / "empty"])
            self.assertEqual(summary["empty_data_files"], [str(repo / "empty")])
            invalid = coverage.CoverageData(basename=str(repo / "invalid"))
            invalid.add_lines({str(module): [1]})
            invalid.write()
            with self.assertRaisesRegex(ValueError, "Branch coverage is missing"):
                python_report(repo, repo / "invalid-reports", [repo / "valid", repo / "invalid"])

    def test_common_inventory_counts_unimported_example_as_uncovered(self):
        import coverage
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "backend").mkdir()
            (repo / "sdk/examples").mkdir(parents=True)
            source = repo / "backend/unit.py"
            source.write_text("value = 1\n", encoding="utf-8")
            example = repo / "sdk/examples/probe.py"
            example.write_text("value = 2\n", encoding="utf-8")
            raw = coverage.CoverageData(basename=str(repo / "raw"))
            raw.add_arcs({str(source): [(-1, 1), (1, -1)]})
            raw.write()
            summary = python_report(repo, repo / "reports", [repo / "raw"], inventory=[str(source), str(example)])
            self.assertEqual(summary["lines"], {"covered": 1, "total": 2, "percent": 50.0})

    def test_behavior_audit_resolves_legacy_root_and_real_d1_contexts(self):
        import coverage
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            source = repo / "backend/unit.py"
            source.parent.mkdir()
            source.write_text("def choose(value):\n    if value:\n        return 1\n    return 0\n", encoding="utf-8")
            legacy = repo / "test/backend/test_example.py"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("def test_boundary():\n    assert choose(True) == 1\n", encoding="utf-8")
            batch = repo / "batch"
            for suite, context, arcs in (
                ("legacy", "backend/test_example.py::test_boundary|run", [(2, 3), (3, -1)]),
                ("d1", "cases/UNIT-01/test.py::test_unit|run", [(2, 4), (4, -1)]),
            ):
                directory = batch / suite / "python"
                directory.mkdir(parents=True)
                raw = coverage.CoverageData(basename=str(directory / ".coverage"))
                raw.set_context(context)
                raw.add_arcs({str(source): arcs})
                raw.write()
            (batch / "legacy-job").mkdir()
            (batch / "legacy-job/junit.xml").write_text(
                '<testsuite><testcase name="test_boundary"/></testsuite>', encoding="utf-8")
            (batch / "plan.json").write_text(json.dumps({"tasks": [{"suite": "legacy",
                "file": "test/backend/test_example.py", "directory": "legacy-job"}]}), encoding="utf-8")
            case = repo / "test-e2e/cases/UNIT-01/case.yaml"
            case.parent.mkdir(parents=True)
            case.write_text('case:\n  title: Boundary\n  expected_results: [Returns zero]\n', encoding="utf-8")
            audit_behaviors(repo, batch, {"files": [{"file": "backend/unit.py", "legacy_only_lines": [3]}]},
                            [{"case_id": "UNIT-01"}])
            lead = json.loads((batch / "legacy-exclusive-behaviors.json").read_text(encoding="utf-8"))["review_leads"][0]
            self.assertEqual(lead["legacy_tests"][0]["test_id"], "test/backend/test_example.py::test_boundary")
            self.assertEqual(lead["legacy_tests"][0]["execution_outcome"], ["PASS"])
            self.assertEqual(lead["legacy_tests"][0]["assertions"], ["assert choose(True) == 1"])
            self.assertEqual(lead["related_formal_cases"][0]["case_id"], "UNIT-01")
            # A module imported during the test can execute only its def line.
            # That must not be presented as execution of this behavior.
            imported = coverage.CoverageData(basename=str(batch / "d1/python/.coverage"))
            imported.set_context("cases/UNIT-01/test.py::test_unit|run")
            imported.add_arcs({str(source): [(-1, 1), (1, -1)]})
            imported.write()
            audit_behaviors(repo, batch, {"files": [{"file": "backend/unit.py", "legacy_only_lines": [3]}]},
                            [{"case_id": "UNIT-01"}])
            lead = json.loads((batch / "legacy-exclusive-behaviors.json").read_text(encoding="utf-8"))["review_leads"][0]
            self.assertEqual(lead["related_formal_cases"], [])
