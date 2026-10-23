# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Benchmark entrypoints expose the same single business prompt contract."""

import logging
import sys
from pathlib import Path

import pytest
import yaml

from sdk.benchmark import agent_runner
from sdk.benchmark.generic import run_benchmark
from sdk.benchmark.generic.integrations.langfuse import webhook_server
from sdk.benchmark.generic.runtime.task_adapter import make_nexent_task


@pytest.fixture(params=[
    {"constraint_prompt": "Legacy rule"},
    {"few_shots_prompt": "Legacy example"},
    {"unknown_prompt": "Unsupported prompt"},
    {"duty_prompt": "Retired field"},
    {"constraint_prompt": "Rule", "few_shots_prompt": "Example"},
    {"constraint_prompt": ""},
    {"few_shots_prompt": None},
], ids=["constraint", "examples", "unknown", "duty", "both-legacy", "empty-legacy", "null-legacy"])
def unsupported_prompt_config(request, tmp_path):
    config_path = tmp_path / "agent.yaml"
    config_path.write_text(
        yaml.safe_dump({"prompts": {"prompt": "Complete prompt", **request.param}}),
        encoding="utf-8",
    )
    return config_path


def test_benchmark_cli_rejects_unsupported_config_prompts_before_execution(
    mocker, unsupported_prompt_config,
):
    langfuse = mocker.patch("langfuse.Langfuse")
    run_experiment = mocker.patch.object(run_benchmark, "run_experiment")
    mocker.patch.object(sys, "argv", [
        "run_benchmark.py", "--dataset", "synthetic",
        "--agent-config", str(unsupported_prompt_config),
        "--prompt", "CLI override cannot bypass validation",
    ])

    with pytest.raises(ValueError) as error:
        run_benchmark.main()

    assert str(error.value) == (
        "Agent prompts only supports prompt; migrate legacy configuration first"
    )
    langfuse.assert_not_called()
    run_experiment.assert_not_called()


def test_webhook_rejects_unsupported_config_prompts_before_execution(
    mocker, caplog, unsupported_prompt_config,
):
    import evaluators
    from runtime import task_adapter as runtime_task_adapter

    langfuse = mocker.patch("langfuse.Langfuse").return_value
    mocker.patch.object(evaluators, "resolve_evaluators", return_value=[])
    make_task = mocker.patch.object(runtime_task_adapter, "make_nexent_task")

    with caplog.at_level(logging.ERROR, logger="benchmark-webhook"):
        webhook_server.run_experiment_task(
            "synthetic", [], 5, "invalid-prompts", 0.0, "en",
            str(unsupported_prompt_config),
        )

    assert caplog.messages == ["Experiment 'invalid-prompts' FAILED"]
    langfuse.get_dataset.assert_not_called()
    langfuse.trace.assert_not_called()
    make_task.assert_not_called()


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
        assert set(config["prompts"]) == {"prompt"}, name
        assert config["prompts"]["prompt"].strip(), name


def test_benchmark_cli_rejects_retired_prompt_flag(mocker):
    run = mocker.patch.object(run_benchmark, "run_experiment")
    mocker.patch.object(sys, "argv", ["run_benchmark.py", "--dataset", "synthetic", "--duty-prompt", "Legacy"])
    with pytest.raises(SystemExit) as error:
        run_benchmark.main()
    assert error.value.code == 2
    run.assert_not_called()
