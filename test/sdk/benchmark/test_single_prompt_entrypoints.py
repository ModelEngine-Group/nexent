# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Benchmark entrypoints expose the same single business prompt contract."""

from pathlib import Path
import sys

import pytest
import yaml

from sdk.benchmark import agent_runner
from sdk.benchmark.generic import run_benchmark
from sdk.benchmark.generic.runtime.task_adapter import make_nexent_task


@pytest.mark.parametrize("field", ["constraint_prompt", "few_shots_prompt"])
def test_benchmark_factories_reject_removed_fields(field):
    with pytest.raises(TypeError, match=field):
        agent_runner.build_agent_run_info(query="question", history=[], **{field: "Legacy"})
    with pytest.raises(TypeError, match=field):
        make_nexent_task(**{field: "Legacy"})


@pytest.mark.parametrize("flag", ["--constraint-prompt", "--few-shots-prompt"])
def test_benchmark_cli_rejects_removed_flags(monkeypatch, capsys, flag):
    monkeypatch.setattr(sys, "argv", ["run_benchmark.py", "--dataset", "synthetic", flag, "Legacy"])
    with pytest.raises(SystemExit) as caught:
        run_benchmark.main()
    assert caught.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_shipped_benchmark_configs_contain_one_complete_prompt():
    root = Path(__file__).resolve().parents[3] / "sdk/benchmark/generic/configs"
    for name in ("agent_example.yaml", "agent_7_test.yaml", "gaia_solver.yaml", "gsm8k_solver_assistant.yaml"):
        config = yaml.safe_load((root / name).read_text(encoding="utf-8"))
        assert set(config["prompts"]) == {"duty_prompt"}, name
        assert config["prompts"]["duty_prompt"].strip(), name
