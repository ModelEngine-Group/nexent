# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Contracts for the Python UT execution tool, independent of product services."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest


RUNNER_PATH = Path(__file__).resolve().parents[2] / "run_all_test.py"


@pytest.fixture(scope="module")
def runner():
    spec = importlib.util.spec_from_file_location("unit_test_execution_tool", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("budget", "file_count", "expected"),
    [
        ("4", 12, 4),
        ("20", 3, 3),
        ("0", 12, 1),
        ("-2", 12, 1),
        ("off", 12, 1),
        ("invalid", 12, 1),
        ("auto", 12, 1),
    ],
)
def test_environment_budget_without_cpu_detection(runner, monkeypatch, budget, file_count, expected):
    if budget is None:
        monkeypatch.delenv("NEXENT_PYTEST_WORKERS", raising=False)
    else:
        monkeypatch.setenv("NEXENT_PYTEST_WORKERS", budget)

    def unexpected_detection():
        raise AssertionError("Worker selection must not inspect the host CPU count")

    with monkeypatch.context() as context:
        context.setattr(runner.os, "cpu_count", unexpected_detection)
        assert runner._worker_count(file_count) == expected


@pytest.mark.parametrize(
    ("budget", "cpu_count", "file_count", "expected"),
    [(None, 8, 12, 8), ("", 8, 12, 8), ("  ", 8, 12, 8),
     (None, 8, 3, 3), (None, None, 12, 1), (None, 0, 12, 1)],
)
def test_missing_budget_uses_cpu_count(runner, monkeypatch, budget, cpu_count, file_count, expected):
    if budget is None:
        monkeypatch.delenv("NEXENT_PYTEST_WORKERS", raising=False)
    else:
        monkeypatch.setenv("NEXENT_PYTEST_WORKERS", budget)
    with monkeypatch.context() as context:
        context.setattr(runner.os, "cpu_count", lambda: cpu_count)
        assert runner._worker_count(file_count) == expected


@pytest.mark.parametrize(
    ("output", "exit_code", "expected"),
    [
        ("2 passed, 3 skipped in 0.10s", 0, {"total": 5, "passed": 2, "failed": 0, "skipped": 3}),
        ("3 skipped in 0.10s", 0, {"total": 3, "passed": 0, "failed": 0, "skipped": 3}),
        ("1 error in 0.10s", 2, {"total": 1, "passed": 0, "failed": 1, "skipped": 0}),
        ("2 failed, 1 error, 3 skipped in 0.10s", 1,
         {"total": 6, "passed": 0, "failed": 3, "skipped": 3}),
        ("", 124, {"total": 1, "passed": 0, "failed": 1, "skipped": 0}),
    ],
)
def test_result_counts_include_skipped_and_errors(runner, output, exit_code, expected):
    assert runner._parse_test_counts({"stdout": output, "returncode": exit_code}) == expected


def test_skipped_file_is_not_described_as_execution_failure(runner, caplog):
    runner._print_file_result({"file": "test/optional.py", "stdout": "3 skipped in 0.10s", "returncode": 0})
    assert "SKIP | 3 skipped in 0.10s" in caplog.text
    assert "execution failed" not in caplog.text


def test_summary_separates_skipped_from_executed_tests(runner, caplog):
    runner._print_test_summary([
        {"file": "test/first.py", "stdout": "2 passed in 0.10s", "returncode": 0},
        {"file": "test/failed.py", "stdout": "1 failed in 0.10s", "returncode": 1},
        {"file": "test/optional.py", "stdout": "3 skipped in 0.10s", "returncode": 0},
    ])
    assert "SKIPPED - test/optional.py" in caplog.text
    assert "Total Tests: 6" in caplog.text
    assert "Skipped: 3" in caplog.text
    assert "Pass Rate: 66.7%" in caplog.text


def test_invalid_coverage_data_remains_a_failure(runner, tmp_path, caplog):
    (tmp_path / ".coverage").write_text("invalid coverage database")
    assert runner._report_coverage(tmp_path) is False
    assert "Coverage report failed" in caplog.text
    assert not (tmp_path / "coverage.xml").exists()


@pytest.mark.parametrize(("budget", "include_failure"), [(None, False), ("2", False), ("2", True)])
def test_real_process_isolation_reports_and_failure_exit(tmp_path, budget, include_failure):
    project = tmp_path / "fixture-project"
    tests = project / "test" / "backend"
    tests.mkdir(parents=True)
    for package in ("backend", "sdk"):
        (project / package).mkdir()
        (project / package / "__init__.py").write_text("")
    (project / "backend" / "feature.py").write_text(
        "def choose(enabled):\n    if enabled:\n        return 'on'\n    return 'off'\n"
    )
    shutil.copyfile(RUNNER_PATH, project / "test" / "run_all_test.py")
    for name, enabled, expected in (("first", True, "on"), ("second", False, "off")):
        (tests / f"test_{name}.py").write_text(
            "import builtins\nfrom backend.feature import choose\n"
            f"def test_{name}():\n"
            "    assert not getattr(builtins, '_ut_process_marker', False)\n"
            "    builtins._ut_process_marker = True\n"
            f"    assert choose({enabled!r}) == {expected!r}\n"
        )
    (tests / "test_optional.py").write_text(
        "import pytest\n@pytest.mark.skip(reason='optional integration')\n"
        "def test_optional():\n    assert False\n"
    )
    if include_failure:
        (tests / "test_failure.py").write_text("def test_failure():\n    assert False, 'intentional failure'\n")

    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith("COVERAGE_") and key not in {
            "NEXENT_PYTEST_WORKERS", "NEXENT_PYTEST_TARGETS", "PYTHONPATH", "PYTEST_ADDOPTS",
        }
    }
    if budget is not None:
        env["NEXENT_PYTEST_WORKERS"] = budget
    env["NEXENT_PYTEST_FILE_TIMEOUT"] = "60"
    (project / "tmp").mkdir()
    env["TMPDIR"] = str(project / "tmp")
    result = subprocess.run(
        [sys.executable, str(project / "test" / "run_all_test.py")],
        cwd=project, env=env, text=True, capture_output=True, timeout=90,
    )
    output = result.stdout + result.stderr
    assert result.returncode == (1 if include_failure else 0), output
    expected_workers = int(budget) if budget else max(1, min(os.cpu_count() or 1, 3))
    assert f"Running with {expected_workers} file worker(s)" in output
    assert "Passed: 2" in output
    assert f"Failed: {int(include_failure)}" in output
    assert "Skipped: 1" in output
    assert "SKIP | 1 skipped" in output
    assert "Total Coverage:" in output
    assert not (project / "test" / "coverage_html").exists()
    assert (project / "test" / ".coverage").exists()
    xml = ET.parse(project / "test" / "coverage.xml").getroot()
    assert int(xml.attrib["branches-valid"]) == 2
    assert int(xml.attrib["branches-covered"]) == 2
