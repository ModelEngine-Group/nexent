from pathlib import Path
from types import SimpleNamespace

import pytest

from sdk.benchmark.generic.run_failed_item_repeats import (
    aggregate_repeat_results,
    baseline_failed_item_ids,
    build_repeat_command,
)


class _Langfuse:
    def get_dataset(self, _name):
        return SimpleNamespace(items=[
            SimpleNamespace(id="a"),
            SimpleNamespace(id="b"),
            SimpleNamespace(id="c"),
        ])

    def get_trace(self, trace_id):
        values = {
            "ta": [SimpleNamespace(name="gaia_exact_match", value=1)],
            "tb": [SimpleNamespace(name="gaia_exact_match", value=0)],
            "tc": [SimpleNamespace(name="gaia_exact_match", value=0)],
        }
        return SimpleNamespace(scores=values[trace_id])


def test_baseline_failures_preserve_dataset_order(monkeypatch):
    run = SimpleNamespace(dataset_run_items=[
        SimpleNamespace(dataset_item_id="c", trace_id="tc"),
        SimpleNamespace(dataset_item_id="a", trace_id="ta"),
        SimpleNamespace(dataset_item_id="b", trace_id="tb"),
    ])
    monkeypatch.setattr(
        "sdk.benchmark.generic.run_failed_item_repeats.fetch_complete_dataset_run",
        lambda *args, **kwargs: run,
    )

    assert baseline_failed_item_ids(
        langfuse=_Langfuse(),
        dataset_name="gaia",
        run_name="baseline",
        evaluator_name="gaia_exact_match",
    ) == ["b", "c"]


def test_repeat_aggregate_exposes_per_item_stability():
    result = aggregate_repeat_results(
        ["b", "c"],
        [
            {"b": True, "c": False},
            {"b": False, "c": False},
            {"b": True, "c": True},
        ],
    )

    assert result["total_passes"] == 3
    assert result["items"][0]["pass_rate"] == pytest.approx(2 / 3, abs=0.0001)
    assert result["items"][1]["outcomes"] == ["fail", "fail", "pass"]


def test_repeat_command_adds_item_filter_and_gaia_diagnostics():
    command = build_repeat_command(
        python_executable=Path("/venv/python"),
        dataset_name="gaia",
        run_name="repeat-r01",
        item_ids=["b", "c"],
        primary_evaluator="gaia_exact_match",
        runner_args=["--temperature", "0"],
    )

    assert command[:2] == [
        "/venv/python",
        str(
            Path(__file__).resolve().parents[3]
            / "sdk/benchmark/generic/run_benchmark.py"
        ),
    ]
    assert command.count("--item-id") == 2
    assert command[command.index("--evaluators") + 1:command.index("--item-id")] == [
        "gaia_exact_match",
        "gaia_final_answer",
    ]
