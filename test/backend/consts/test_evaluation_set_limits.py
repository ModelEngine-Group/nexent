import os
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
VARIABLE = "MAX_EVALUATION_SET_FILE_SIZE_MB"


def _run_const_import(environment: dict[str, str]):
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import backend.consts.const as c; "
                "print(c.MAX_EVALUATION_SET_FILE_SIZE_MB, "
                "c.MAX_EVALUATION_SET_FILE_SIZE_BYTES)"
            ),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_evaluation_set_file_size_defaults_match_deployment_example():
    environment = os.environ.copy()
    environment.pop(VARIABLE, None)
    result = _run_const_import(environment)

    assert result.returncode == 0
    assert result.stdout.strip() == "20 20971520"
    example = (PROJECT_ROOT / "deploy" / "env" / ".env.example").read_text(
        encoding="utf-8"
    )
    assert f"{VARIABLE}=20" in example


def test_evaluation_set_file_size_accepts_positive_override():
    environment = os.environ.copy()
    environment[VARIABLE] = "7"
    result = _run_const_import(environment)

    assert result.returncode == 0
    assert result.stdout.strip() == "7 7340032"


@pytest.mark.parametrize("value", ["0", "-1", "not-a-number"])
def test_evaluation_set_file_size_rejects_invalid_override(value):
    environment = os.environ.copy()
    environment[VARIABLE] = value
    result = _run_const_import(environment)

    assert result.returncode != 0
    assert VARIABLE in result.stderr
