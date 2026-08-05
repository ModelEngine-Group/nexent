from types import SimpleNamespace

import pytest

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
        python_executable="python",
        dataset="gaia",
        run_name="comparison-formal-r01-b",
        group=group,
        runner_args=["--evaluators", "gaia_exact_match"],
        item_limit=2,
        experiment_time="2026-07-20T00:00:00+00:00",
    )

    assert command[0] == "python"
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
