import json
import sys
from types import SimpleNamespace

import pytest

from sdk.benchmark.generic import run_context_manager_comparison as comparison_module
from sdk.benchmark.generic.run_context_manager_comparison import (
    GroupSpec,
    aggregate_provider_cache,
    aggregate_summary_cache,
    build_run_name,
    build_runner_command,
    comparison_groups,
    fetch_complete_dataset_run,
    fetch_run_results,
    paired_outcomes,
    parse_args,
    validate_manifest_parity,
    validate_runner_args,
)


def test_comparison_groups_isolate_processing_policy():
    groups = comparison_groups(10_000)

    assert [group.key for group in groups] == ["P", "C"]
    assert groups[0].runner_args == (
        "--context-processing-mode",
        "passthrough",
        "--token-threshold",
        "10000",
        "--budget-profile",
        "legacy_threshold",
    )
    assert groups[1].runner_args[-1] == "legacy_threshold"


def test_comparison_groups_share_explicit_budgets_and_profile():
    groups = comparison_groups(
        soft_input_budget=10_000,
        hard_input_budget=18_404,
        budget_profile="synthetic_trigger",
    )

    for group in groups:
        assert group.runner_args[-6:] == (
            "--soft-input-budget",
            "10000",
            "--hard-input-budget",
            "18404",
            "--budget-profile",
            "synthetic_trigger",
        )
    assert groups[0].runner_args[1] == "passthrough"
    assert groups[1].runner_args[1] == "adaptive_compact"


def test_runner_command_contains_owned_group_configuration():
    group = GroupSpec("P", "passthrough", ("--context-processing-mode", "passthrough"))

    command = build_runner_command(
        dataset="gaia",
        run_name="comparison-formal-r01-b",
        group=group,
        runner_args=["--evaluators", "gaia_exact_match"],
        item_limit=2,
        experiment_time="2026-07-20T00:00:00+00:00",
    )

    assert command[0] == sys.executable
    assert command[1].endswith("run_benchmark.py")
    assert command.count("--dataset") == 1
    assert command.count("--run-name") == 1
    assert command[-2:] == ["--item-limit", "2"]
    assert "--experiment-time" in command


@pytest.mark.parametrize(
    "argument",
    [
        "--dataset",
        "--run-name=value",
        "--token-threshold",
        "--soft-input-budget",
        "--hard-input-budget=18404",
        "--budget-profile",
        "--item-limit=2",
    ],
)
def test_validate_runner_args_rejects_comparison_variables(argument):
    with pytest.raises(ValueError):
        validate_runner_args([argument])


def test_paired_outcomes_requires_identical_item_ids():
    with pytest.raises(ValueError, match="dataset item IDs do not match"):
        paired_outcomes(
            {
                "P": {"one": True, "two": True, "missing": False},
                "C": {"one": False, "two": False},
            }
        )


def test_paired_outcomes_builds_matrix_for_identical_item_ids():
    result = paired_outcomes(
        {
            "P": {"one": True, "two": True},
            "C": {"one": False, "two": False},
        }
    )

    assert result["paired_item_count"] == 2
    assert result["outcome_matrix"] == {"PF": 2}


def _write_comparison_manifest(
    manifest_dir,
    run_name,
    *,
    mode,
    policy,
    model_name="model-a",
):
    manifest = {
        "context_processing_mode": mode,
        "context_runtime": "context_items",
        "context_manager": {"hard_input_budget_tokens": 20_000},
        "context_policy_fingerprint": f"policy-{mode}",
        "parity_snapshot_hash": f"snapshot-{mode}",
        "parity_snapshot": {
            "snapshot_schema_version": 2,
            "prompt": {"component_hashes": {"duty": "same"}},
            "context_items": [],
            "resources": {},
            "tools": {"schemas": []},
            "model": {"model_name": model_name},
            "capacity": {"context_window_tokens": 32_000},
            "policy": policy,
            "runtime_flags": {"max_steps": 15},
        },
    }
    (manifest_dir / f"{run_name}.manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


def _comparison_policy(mode, soft_input_budget=10_000):
    return {
        "effective_processing_mode": mode,
        "policy_layers": {"platform": {"processing_mode": mode}},
        "soft_input_budget_tokens": soft_input_budget,
    }


def test_validate_manifest_parity_allows_processing_mode_snapshot_difference(
    tmp_path,
    monkeypatch,
):
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    monkeypatch.setattr(comparison_module, "ARTIFACT_ROOT", tmp_path)
    _write_comparison_manifest(
        manifest_dir,
        "run-p",
        mode="passthrough",
        policy=_comparison_policy("passthrough"),
    )
    _write_comparison_manifest(
        manifest_dir,
        "run-c",
        mode="adaptive_compact",
        policy=_comparison_policy("adaptive_compact"),
    )

    result = validate_manifest_parity({"P": "run-p", "C": "run-c"})

    assert result["status"] == "passed"
    assert "parity_snapshot_except_processing_mode" in result["checked_fields"]


def test_validate_manifest_parity_rejects_non_processing_mode_snapshot_difference(
    tmp_path,
    monkeypatch,
):
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    monkeypatch.setattr(comparison_module, "ARTIFACT_ROOT", tmp_path)
    _write_comparison_manifest(
        manifest_dir,
        "run-p",
        mode="passthrough",
        policy=_comparison_policy("passthrough"),
    )
    _write_comparison_manifest(
        manifest_dir,
        "run-c",
        mode="adaptive_compact",
        policy=_comparison_policy("adaptive_compact"),
        model_name="model-b",
    )

    with pytest.raises(RuntimeError, match="parity_snapshot_except_processing_mode"):
        validate_manifest_parity({"P": "run-p", "C": "run-c"})


def test_validate_manifest_parity_rejects_other_policy_difference(
    tmp_path,
    monkeypatch,
):
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    monkeypatch.setattr(comparison_module, "ARTIFACT_ROOT", tmp_path)
    _write_comparison_manifest(
        manifest_dir,
        "run-p",
        mode="passthrough",
        policy=_comparison_policy("passthrough"),
    )
    _write_comparison_manifest(
        manifest_dir,
        "run-c",
        mode="adaptive_compact",
        policy=_comparison_policy("adaptive_compact", soft_input_budget=11_000),
    )

    with pytest.raises(RuntimeError, match="parity_snapshot_except_processing_mode"):
        validate_manifest_parity({"P": "run-p", "C": "run-c"})


def test_fetch_run_results_waits_for_complete_dataset_run(mocker, monkeypatch):
    incomplete_run = SimpleNamespace(dataset_run_items=[
        SimpleNamespace(dataset_item_id="one", trace_id="trace-one"),
    ])
    complete_run = SimpleNamespace(dataset_run_items=[
        SimpleNamespace(dataset_item_id="one", trace_id="trace-one"),
        SimpleNamespace(dataset_item_id="two", trace_id="trace-two"),
    ])
    langfuse = SimpleNamespace()
    mocker.patch.object(langfuse, "get_dataset_run", create=True)
    mocker.patch.object(langfuse, "get_trace", create=True)
    langfuse.get_dataset_run.side_effect = [incomplete_run, complete_run]
    langfuse.get_trace.side_effect = [
        SimpleNamespace(scores=[SimpleNamespace(name="exact_match", value=1.0)]),
        SimpleNamespace(scores=[SimpleNamespace(name="exact_match", value=0.0)]),
    ]
    monkeypatch.setattr("sdk.benchmark.generic.run_context_manager_comparison.time.sleep", lambda _: None)

    result = fetch_run_results(
        langfuse,
        "dataset",
        "run",
        "exact_match",
        expected_item_ids=["one", "two"],
        attempts=2,
    )

    assert result == {"one": True, "two": False}
    assert langfuse.get_dataset_run.call_count == 2


def test_fetch_complete_dataset_run_reports_persistent_missing_items(mocker, monkeypatch):
    incomplete_run = SimpleNamespace(dataset_run_items=[
        SimpleNamespace(dataset_item_id="one"),
    ])
    langfuse = SimpleNamespace()
    mocker.patch.object(langfuse, "get_dataset_run", create=True)
    mocker.patch.object(langfuse, "get_trace", create=True)
    langfuse.get_dataset_run.return_value = incomplete_run
    monkeypatch.setattr("sdk.benchmark.generic.run_context_manager_comparison.time.sleep", lambda _: None)

    with pytest.raises(TimeoutError, match=r'"missing": \["two"\]'):
        fetch_complete_dataset_run(
            langfuse,
            "dataset",
            "run",
            expected_item_ids=["one", "two"],
            attempts=2,
        )


def test_build_run_name_is_paired_and_explicit():
    group = comparison_groups(10_000)[1]

    assert (
        build_run_name("gaia-cm", "formal", 3, group)
        == "gaia-cm-formal-r03-c-adaptive-compact"
    )


def test_parse_args_accepts_explicit_synthetic_trigger_budget(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--dataset",
            "gaia",
            "--run-prefix",
            "run",
            "--soft-input-budget",
            "10000",
            "--hard-input-budget",
            "18404",
            "--budget-profile",
            "synthetic_trigger",
        ],
    )

    args = parse_args()

    assert args.soft_input_budget == 10_000
    assert args.hard_input_budget == 18_404
    assert args.compression_threshold is None


def test_parse_args_rejects_partial_explicit_budget(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--dataset",
            "gaia",
            "--run-prefix",
            "run",
            "--soft-input-budget",
            "10000",
            "--budget-profile",
            "synthetic_trigger",
        ],
    )

    with pytest.raises(SystemExit):
        parse_args()


def test_parse_args_rejects_python_executable_override(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--dataset",
            "gaia",
            "--run-prefix",
            "run",
            "--python",
            "/tmp/untrusted-python",
        ],
    )

    with pytest.raises(SystemExit):
        parse_args()


def test_provider_cache_aggregate_uses_only_explicit_provider_metrics():
    result = aggregate_provider_cache({
        "one": {
            "status": "available",
            "available_calls": 2,
            "hit_calls": 1,
            "provider_cached_tokens": 40,
            "provider_input_tokens": 100,
        },
        "two": {
            "status": "unsupported",
            "available_calls": 0,
            "hit_calls": 0,
            "provider_cached_tokens": 0,
            "provider_input_tokens": 0,
        },
    })

    assert result["status"] == "available"
    assert result["provider_prefix_hit_rate"] == 0.5
    assert result["provider_cached_input_ratio"] == 0.4


def test_provider_cache_aggregate_preserves_unavailable_status():
    result = aggregate_provider_cache({
        "one": {"status": "unsupported"},
        "two": {"status": "unavailable"},
    })

    assert result["status"] == "unavailable"
    assert result["provider_prefix_hit_rate"] is None
    assert result["provider_cached_input_ratio"] is None


def test_summary_cache_aggregate_remains_separate():
    result = aggregate_summary_cache({
        "one": {
            "summary_cache_hits": 2,
            "summary_cache_types": ["previous_summary"],
        },
        "two": {
            "summary_cache_hits": 1,
            "summary_cache_types": ["current_summary", "previous_summary"],
        },
    })

    assert result == {
        "summary_cache_hits": 3,
        "summary_cache_types": ["current_summary", "previous_summary"],
    }

def test_fetch_run_results_waits_for_delayed_evaluator_score(mocker, monkeypatch):
    langfuse = SimpleNamespace()
    mocker.patch.object(langfuse, "get_dataset_run", create=True)
    mocker.patch.object(langfuse, "get_trace", create=True)
    langfuse.get_dataset_run.return_value = SimpleNamespace(
        dataset_run_items=[
            SimpleNamespace(dataset_item_id="one", trace_id="trace-one"),
        ]
    )
    langfuse.get_trace.side_effect = [
        SimpleNamespace(scores=[]),
        SimpleNamespace(
            scores=[SimpleNamespace(name="exact_match", value=1.0)]
        ),
    ]
    sleep = mocker.patch(
        "sdk.benchmark.generic.run_context_manager_comparison.time.sleep"
    )

    result = fetch_run_results(
        langfuse,
        "dataset",
        "run",
        "exact_match",
        expected_item_ids=["one"],
        attempts=2,
    )

    assert result == {"one": True}
    assert langfuse.get_trace.call_count == 2
    sleep.assert_called_once_with(1.0)


def test_fetch_run_results_times_out_instead_of_marking_missing_score_failed(
    mocker,
    monkeypatch,
):
    langfuse = SimpleNamespace()
    mocker.patch.object(langfuse, "get_dataset_run", create=True)
    mocker.patch.object(langfuse, "get_trace", create=True)
    langfuse.get_dataset_run.return_value = SimpleNamespace(
        dataset_run_items=[
            SimpleNamespace(dataset_item_id="one", trace_id="trace-one"),
        ]
    )
    langfuse.get_trace.return_value = SimpleNamespace(scores=[])
    monkeypatch.setattr(
        "sdk.benchmark.generic.run_context_manager_comparison.time.sleep",
        lambda _: None,
    )

    with pytest.raises(TimeoutError, match=r'"missing_scores": \["one"\]'):
        fetch_run_results(
            langfuse,
            "dataset",
            "run",
            "exact_match",
            expected_item_ids=["one"],
            attempts=2,
        )


def test_fetch_run_results_preserves_visible_failing_score(mocker):
    langfuse = SimpleNamespace()
    mocker.patch.object(langfuse, "get_dataset_run", create=True)
    mocker.patch.object(langfuse, "get_trace", create=True)
    langfuse.get_dataset_run.return_value = SimpleNamespace(
        dataset_run_items=[
            SimpleNamespace(dataset_item_id="one", trace_id="trace-one"),
        ]
    )
    langfuse.get_trace.return_value = SimpleNamespace(
        scores=[SimpleNamespace(name="exact_match", value=0.0)]
    )

    result = fetch_run_results(
        langfuse,
        "dataset",
        "run",
        "exact_match",
        expected_item_ids=["one"],
        attempts=1,
    )

    assert result == {"one": False}


def test_main_runs_both_groups_and_writes_paired_report(
    monkeypatch,
    tmp_path,
):
    from sdk.benchmark.generic import run_integrity

    args = SimpleNamespace(
        dataset="dataset",
        run_prefix="pc-test",
        repeat=1,
        smoke_items=1,
        skip_smoke=True,
        formal_items=1,
        compression_threshold=None,
        soft_input_budget=100,
        hard_input_budget=200,
        budget_profile="synthetic_trigger",
        seed=0,
        required_url=[],
        runner_args=["--evaluators", "exact_match", "f1"],
    )
    monkeypatch.setattr(comparison_module, "parse_args", lambda: args)
    monkeypatch.setattr(comparison_module, "ARTIFACT_ROOT", tmp_path)
    langfuse = object()
    monkeypatch.setattr(
        comparison_module,
        "preflight",
        lambda **kwargs: (langfuse, ["item-1"]),
    )
    commands = []
    monkeypatch.setattr(
        comparison_module.subprocess,
        "run",
        lambda command, **kwargs: commands.append((command, kwargs)),
    )
    monkeypatch.setattr(
        comparison_module,
        "fetch_run_results",
        lambda langfuse, dataset, run_name, evaluator, **kwargs: {
            "item-1": run_name.endswith("-p-passthrough")
        },
    )
    provider_cache = {
        "status": "available",
        "available_calls": 1,
        "hit_calls": 1,
        "provider_prefix_hit_rate": 1.0,
        "provider_cached_tokens": 10,
        "provider_input_tokens": 20,
        "provider_cached_input_ratio": 0.5,
        "metrics_sources": ["usage"],
    }
    summary_cache = {"summary_cache_hits": 0, "summary_cache_types": []}
    budget_evidence = {
        "total_items": 1,
        "over_soft_budget_count": 0,
        "over_hard_budget_count": 0,
        "compression_triggered_count": 0,
        "overflow_avoidance_rate": None,
        "max_peak_context_tokens": 50,
    }
    monkeypatch.setattr(
        comparison_module,
        "fetch_run_provider_cache",
        lambda *args, **kwargs: [{}],
    )
    monkeypatch.setattr(
        comparison_module,
        "aggregate_provider_cache",
        lambda items: provider_cache,
    )
    monkeypatch.setattr(
        comparison_module,
        "fetch_run_summary_cache",
        lambda *args, **kwargs: [{}],
    )
    monkeypatch.setattr(
        comparison_module,
        "aggregate_summary_cache",
        lambda items: summary_cache,
    )
    monkeypatch.setattr(
        comparison_module,
        "fetch_run_budget_evidence",
        lambda *args, **kwargs: [{}],
    )
    monkeypatch.setattr(
        comparison_module,
        "aggregate_budget_evidence",
        lambda items: budget_evidence,
    )
    monkeypatch.setattr(
        comparison_module,
        "validate_manifest_parity",
        lambda run_names: {"status": "matched"},
    )
    integrity_report = SimpleNamespace(
        run_complete=True,
        to_dict=lambda: {"status": "complete"},
        summary=lambda: "complete",
    )
    monkeypatch.setattr(
        run_integrity,
        "check_run_integrity",
        lambda **kwargs: integrity_report,
    )
    written = {}

    def fake_write_report(report, prefix):
        written["report"] = report
        written["prefix"] = prefix
        return tmp_path / "report.json", tmp_path / "report.md"

    monkeypatch.setattr(
        comparison_module,
        "write_report_exclusive",
        fake_write_report,
    )

    comparison_module.main()

    assert len(commands) == 2
    processing_modes = {
        command[0][command[0].index("--context-processing-mode") + 1]
        for command in commands
    }
    assert processing_modes == {"passthrough", "adaptive_compact"}
    result = written["report"]["results"][0]
    assert result["phase"] == "formal"
    assert result["paired"]["outcome_matrix"] == {"PF": 1}
    assert result["integrity"] == {
        "P": {"status": "complete"},
        "C": {"status": "complete"},
    }
    assert written["prefix"] == "pc-test"


def test_fetch_trace_metrics_handles_dict_json_and_invalid_outputs(monkeypatch):
    run = SimpleNamespace(
        dataset_run_items=[
            SimpleNamespace(dataset_item_id="one", trace_id="trace-one"),
            SimpleNamespace(dataset_item_id="two", trace_id="trace-two"),
            SimpleNamespace(dataset_item_id="three", trace_id="trace-three"),
        ]
    )
    outputs = {
        "trace-one": {
            "provider_cache": {"status": "available", "available_calls": 1},
            "compression": {
                "summary_cache_hits": 2,
                "summary_cache_types": ["history"],
            },
            "budget_evidence": {
                "over_soft_budget": True,
                "over_hard_budget": False,
                "compression_triggered": True,
                "peak_context_tokens": 100,
            },
        },
        "trace-two": json.dumps(
            {
                "provider_cache": {"status": "unsupported"},
                "compression": {},
                "budget_evidence": {
                    "over_hard_budget": True,
                    "peak_context_tokens": 200,
                },
            }
        ),
        "trace-three": "not-json",
    }
    langfuse = SimpleNamespace(
        get_trace=lambda trace_id: SimpleNamespace(output=outputs[trace_id])
    )
    monkeypatch.setattr(
        comparison_module,
        "fetch_complete_dataset_run",
        lambda *args, **kwargs: run,
    )

    provider = comparison_module.fetch_run_provider_cache(
        langfuse,
        "dataset",
        "run",
    )
    summary = comparison_module.fetch_run_summary_cache(
        langfuse,
        "dataset",
        "run",
    )
    budget = comparison_module.fetch_run_budget_evidence(
        langfuse,
        "dataset",
        "run",
    )

    assert provider["one"]["status"] == "available"
    assert provider["three"] == {}
    assert summary["one"] == {
        "summary_cache_hits": 2,
        "summary_cache_types": ["history"],
    }
    assert summary["three"] == {
        "summary_cache_hits": 0,
        "summary_cache_types": [],
    }
    aggregate = comparison_module.aggregate_budget_evidence(budget)
    assert aggregate == {
        "total_items": 3,
        "over_soft_budget_count": 1,
        "over_hard_budget_count": 1,
        "compression_triggered_count": 1,
        "overflow_avoidance_rate": pytest.approx(2 / 3, abs=0.0001),
        "max_peak_context_tokens": 200,
        "avg_peak_context_tokens": 100,
    }


def test_preflight_validates_service_dataset_and_remote_run_uniqueness(
    monkeypatch,
    tmp_path,
):
    from sdk.benchmark.generic import provenance
    from sdk.benchmark.generic.provenance import experiment_manifest

    monkeypatch.setitem(sys.modules, "provenance", provenance)
    monkeypatch.setitem(
        sys.modules,
        "provenance.experiment_manifest",
        experiment_manifest,
    )

    class NotFoundError(Exception):
        status_code = 404

    langfuse = SimpleNamespace(
        auth_check=lambda: True,
        get_dataset=lambda name: SimpleNamespace(
            items=[SimpleNamespace(id="one"), SimpleNamespace(id="two")]
        ),
        get_dataset_run=lambda dataset, run: (_ for _ in ()).throw(NotFoundError()),
    )
    monkeypatch.setattr("langfuse.Langfuse", lambda: langfuse)
    monkeypatch.setattr(comparison_module, "ARTIFACT_ROOT", tmp_path)
    requested = []
    monkeypatch.setattr(
        comparison_module.requests,
        "get",
        lambda url, timeout: requested.append((url, timeout))
        or SimpleNamespace(status_code=200),
    )

    result, item_ids = comparison_module.preflight(
        dataset_name="dataset",
        required_urls=["langfuse=http://localhost:3100"],
        planned_run_names=["run-one", "run-two"],
    )

    assert result is langfuse
    assert item_ids == ["one", "two"]
    assert requested == [("http://localhost:3100", 10)]


@pytest.mark.parametrize(
    ("required_urls", "status_code", "expected_error"),
    [
        (["invalid"], 200, ValueError),
        (["service=http://localhost"], 503, RuntimeError),
    ],
)
def test_preflight_rejects_invalid_or_unhealthy_required_service(
    monkeypatch,
    tmp_path,
    required_urls,
    status_code,
    expected_error,
):
    langfuse = SimpleNamespace(
        auth_check=lambda: True,
        get_dataset=lambda name: SimpleNamespace(items=[SimpleNamespace(id="one")]),
    )
    monkeypatch.setattr("langfuse.Langfuse", lambda: langfuse)
    monkeypatch.setattr(comparison_module, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        comparison_module.requests,
        "get",
        lambda url, timeout: SimpleNamespace(status_code=status_code),
    )

    with pytest.raises(expected_error):
        comparison_module.preflight(
            dataset_name="dataset",
            required_urls=required_urls,
            planned_run_names=[],
        )


def test_write_report_exclusive_renders_cache_and_budget_sections(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(comparison_module, "ARTIFACT_ROOT", tmp_path)
    provider_cache = {
        "status": "available",
        "available_calls": 2,
        "hit_calls": 1,
        "provider_prefix_hit_rate": 0.5,
        "provider_cached_tokens": 20,
        "provider_cached_input_ratio": 0.25,
    }
    summary_cache = {
        "summary_cache_hits": 1,
        "summary_cache_types": ["history"],
    }
    budget_evidence = {
        "total_items": 1,
        "over_soft_budget_count": 1,
        "over_hard_budget_count": 0,
        "compression_triggered_count": 1,
        "overflow_avoidance_rate": 1.0,
        "max_peak_context_tokens": 100,
    }
    report = {
        "budget_profile": "synthetic_trigger",
        "thresholds": {
            "soft_input_budget": 100,
            "hard_input_budget": 200,
        },
        "results": [
            {
                "phase": "formal",
                "repeat_index": 1,
                "paired": {
                    "paired_item_count": 1,
                    "outcome_matrix": {"PC": 1},
                },
                "provider_cache": {
                    "P": provider_cache,
                    "C": provider_cache,
                },
                "summary_cache": {
                    "P": summary_cache,
                    "C": summary_cache,
                },
                "budget_evidence": {
                    "P": budget_evidence,
                    "C": budget_evidence,
                },
            }
        ],
    }

    json_path, markdown_path = comparison_module.write_report_exclusive(
        report,
        "pc unsafe/name",
    )

    assert json_path.name == "pc_unsafe_name.comparison.json"
    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "## Provider prefix cache" in markdown
    assert "## ContextManager summary cache" in markdown
    assert "## Budget & overflow" in markdown
    assert "50.00%" in markdown
    assert "100.00%" in markdown
