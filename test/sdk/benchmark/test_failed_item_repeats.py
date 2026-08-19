import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from sdk.benchmark.generic import run_failed_item_repeats as repeat_module
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


def test_repeat_aggregate_rejects_mismatched_item_sets():
    with pytest.raises(ValueError, match="exact targeted item set"):
        aggregate_repeat_results(["a"], [{"b": True}])


def test_repeat_command_adds_item_filter_and_gaia_diagnostics():
    command = build_repeat_command(
        dataset_name="gaia",
        run_name="repeat-r01",
        item_ids=["b", "c"],
        primary_evaluator="gaia_exact_match",
        runner_args=["--temperature", "0"],
    )

    assert command[:2] == [
        sys.executable,
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


def test_main_repeats_baseline_failures_and_writes_stability_report(
    monkeypatch,
    tmp_path,
):
    langfuse = SimpleNamespace(auth_check=lambda: True)
    monkeypatch.setattr("langfuse.Langfuse", lambda: langfuse)
    monkeypatch.setattr(
        repeat_module,
        "baseline_failed_item_ids",
        lambda **kwargs: ["b", "c"],
    )
    monkeypatch.setattr(
        repeat_module,
        "_assert_no_collisions",
        lambda *args, **kwargs: None,
    )
    commands = []
    monkeypatch.setattr(
        repeat_module.subprocess,
        "run",
        lambda command, **kwargs: commands.append((command, kwargs)),
    )
    outcomes = iter(
        [
            {"b": True, "c": False},
            {"b": False, "c": True},
        ]
    )
    monkeypatch.setattr(
        repeat_module,
        "fetch_run_results",
        lambda *args, **kwargs: next(outcomes),
    )
    written = {}

    def fake_write_report(report, prefix):
        written["report"] = report
        written["prefix"] = prefix
        return tmp_path / "report.json", tmp_path / "report.md"

    monkeypatch.setattr(
        repeat_module,
        "write_report_exclusive",
        fake_write_report,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_failed_item_repeats.py",
            "--dataset",
            "gaia",
            "--baseline-run",
            "baseline",
            "--run-prefix",
            "repeat",
            "--repeat",
            "2",
            "--max-items",
            "2",
            "--runner-args",
            "--temperature",
            "0",
        ],
    )

    repeat_module.main()

    assert len(commands) == 2
    assert all(command[0][0] == sys.executable for command in commands)
    assert written["report"]["run_names"] == ["repeat-r01", "repeat-r02"]
    assert written["report"]["target_item_ids"] == ["b", "c"]
    assert written["report"]["aggregate"]["total_passes"] == 2
    assert written["prefix"] == "repeat"


def test_main_rejects_python_executable_override(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_failed_item_repeats.py",
            "--dataset",
            "gaia",
            "--baseline-run",
            "baseline",
            "--run-prefix",
            "repeat",
            "--python",
            "/tmp/untrusted-python",
        ],
    )

    with pytest.raises(SystemExit):
        repeat_module.main()


def test_runner_args_reject_controlled_options():
    with pytest.raises(ValueError, match="--dataset is controlled"):
        repeat_module._validate_runner_args(["--temperature", "0", "--dataset=other"])


def test_write_report_exclusive_creates_json_and_markdown(monkeypatch, tmp_path):
    monkeypatch.setattr(repeat_module, "ARTIFACT_ROOT", tmp_path)
    report = {
        "dataset": "gaia",
        "baseline_run": "baseline",
        "primary_evaluator": "gaia_exact_match",
        "run_names": ["repeat-r01"],
        "target_item_ids": ["b"],
        "aggregate": aggregate_repeat_results(["b"], [{"b": True}]),
    }

    json_path, markdown_path = repeat_module.write_report_exclusive(
        report,
        "repeat unsafe/name",
    )

    assert json_path.exists()
    assert markdown_path.exists()
    assert json_path.name == "repeat_unsafe_name.targeted-repeat.json"
    assert "| `b` | 1 | 1 | 100.0% | pass |" in markdown_path.read_text(
        encoding="utf-8"
    )


def test_baseline_failures_reject_missing_evaluator_scores(monkeypatch):
    run = SimpleNamespace(
        dataset_run_items=[
            SimpleNamespace(dataset_item_id="a", trace_id="trace-a"),
        ]
    )
    langfuse = SimpleNamespace(
        get_dataset=lambda name: SimpleNamespace(
            items=[SimpleNamespace(id="a")]
        ),
        get_trace=lambda trace_id: SimpleNamespace(scores=[]),
    )
    monkeypatch.setattr(
        repeat_module,
        "fetch_complete_dataset_run",
        lambda *args, **kwargs: run,
    )

    with pytest.raises(RuntimeError, match="missing evaluator"):
        baseline_failed_item_ids(
            langfuse=langfuse,
            dataset_name="dataset",
            run_name="baseline",
            evaluator_name="exact_match",
        )


def test_collision_check_rejects_local_and_remote_runs(monkeypatch, tmp_path):
    local_manifest = tmp_path / "existing.manifest.json"
    local_manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        repeat_module,
        "manifest_path",
        lambda output_dir, run_name: local_manifest,
    )

    with pytest.raises(FileExistsError, match="local run manifests"):
        repeat_module._assert_no_collisions(
            SimpleNamespace(),
            "dataset",
            ["run"],
        )

    missing_manifest = tmp_path / "missing.manifest.json"
    monkeypatch.setattr(
        repeat_module,
        "manifest_path",
        lambda output_dir, run_name: missing_manifest,
    )
    langfuse = SimpleNamespace(
        get_dataset_run=lambda dataset, run: SimpleNamespace(name=run)
    )
    with pytest.raises(FileExistsError, match="Langfuse runs"):
        repeat_module._assert_no_collisions(langfuse, "dataset", ["run"])


def test_collision_check_accepts_remote_not_found(monkeypatch, tmp_path):
    class NotFoundError(Exception):
        status_code = 404

    monkeypatch.setattr(
        repeat_module,
        "manifest_path",
        lambda output_dir, run_name: tmp_path / "missing.manifest.json",
    )
    langfuse = SimpleNamespace(
        get_dataset_run=lambda dataset, run: (_ for _ in ()).throw(NotFoundError())
    )

    repeat_module._assert_no_collisions(langfuse, "dataset", ["run"])
