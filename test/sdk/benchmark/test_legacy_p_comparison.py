import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sdk.benchmark.generic import run_legacy_p_comparison as legacy_module
from sdk.benchmark.generic.run_legacy_p_comparison import (
    build_run_name,
    build_runner_command,
    comparison_arms,
    paired_outcomes,
    validate_manifest_parity,
    validate_runner_args,
)


def _arms(tmp_path: Path):
    legacy = tmp_path / "legacy"
    candidate = tmp_path / "candidate"
    return comparison_arms(
        legacy_root=legacy,
        legacy_python=legacy / "python",
        candidate_root=candidate,
        candidate_python=candidate / "python",
    )


def test_comparison_arms_use_separate_roots_and_policies(tmp_path):
    legacy, candidate = _arms(tmp_path)

    assert legacy.runner_args == ("--disable-context-manager",)
    assert candidate.runner_args == (
        "--context-processing-mode",
        "passthrough",
    )
    assert legacy.runner != candidate.runner


def test_candidate_only_budget_is_not_forwarded_to_legacy(tmp_path):
    legacy_root = tmp_path / "legacy"
    candidate_root = tmp_path / "candidate"
    legacy, candidate = comparison_arms(
        legacy_root=legacy_root,
        legacy_python=legacy_root / "python",
        candidate_root=candidate_root,
        candidate_python=candidate_root / "python",
        candidate_policy_args=(
            "--soft-input-budget",
            "10000",
            "--hard-input-budget",
            "900000",
        ),
    )

    assert "--soft-input-budget" not in legacy.runner_args
    assert candidate.runner_args[-4:] == (
        "--soft-input-budget",
        "10000",
        "--hard-input-budget",
        "900000",
    )


def test_comparison_arms_preserve_virtualenv_python_symlink(tmp_path):
    real_python = tmp_path / "python3.11"
    real_python.touch()
    legacy_root = tmp_path / "legacy"
    legacy_python = legacy_root / "backend/.venv/bin/python"
    legacy_python.parent.mkdir(parents=True)
    legacy_python.symlink_to(real_python)

    legacy, _ = comparison_arms(
        legacy_root=legacy_root,
        legacy_python=legacy_python,
        candidate_root=tmp_path / "candidate",
        candidate_python=tmp_path / "candidate/backend/.venv/bin/python",
    )

    assert legacy.python_executable == legacy_python.absolute()


def test_runner_command_uses_arm_owned_python_runner_and_cwd(tmp_path):
    legacy, _ = _arms(tmp_path)

    command = build_runner_command(
        arm=legacy,
        dataset="gaia",
        run_name="comparison-smoke-r01-l-legacy",
        runner_args=["--evaluators", "gaia_exact_match"],
        item_limit=1,
        experiment_time="2026-07-24T00:00:00+00:00",
    )

    assert command[0] == str(legacy.python_executable)
    assert command[1] == str(legacy.runner)
    assert "--disable-context-manager" in command
    assert command[-2:] == ["--item-limit", "1"]


@pytest.mark.parametrize(
    "argument",
    [
        "--dataset",
        "--run-name=value",
        "--disable-context-manager",
        "--context-processing-mode=passthrough",
        "--token-threshold",
        "--item-limit=2",
    ],
)
def test_validate_runner_args_rejects_owned_variables(argument):
    with pytest.raises(ValueError, match="controlled"):
        validate_runner_args([argument])


def test_paired_outcomes_uses_legacy_then_passthrough_order():
    result = paired_outcomes(
        {
            "L": {"one": True, "two": False},
            "P": {"one": False, "two": True},
        }
    )

    assert result["outcome_matrix"] == {"PF": 1, "FP": 1}
    assert result["items"][0] == {
        "item_id": "one",
        "legacy": "P",
        "passthrough": "F",
    }


def test_build_run_name_is_separate_from_pc_names(tmp_path):
    legacy, _ = _arms(tmp_path)

    assert (
        build_run_name("gaia-lp", "formal", 3, legacy)
        == "gaia-lp-formal-r03-l-legacy"
    )


def test_smoke_only_is_an_independent_lp_option(monkeypatch, tmp_path):
    from sdk.benchmark.generic.run_legacy_p_comparison import parse_args

    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--dataset",
            "gaia",
            "--run-prefix",
            "lp-smoke",
            "--legacy-root",
            str(tmp_path),
            "--smoke-only",
        ],
    )

    args = parse_args()

    assert args.smoke_only is True


def test_parse_args_rejects_partial_candidate_budget(monkeypatch, tmp_path):
    from sdk.benchmark.generic.run_legacy_p_comparison import parse_args

    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--dataset",
            "gaia",
            "--run-prefix",
            "lp",
            "--legacy-root",
            str(tmp_path),
            "--candidate-soft-input-budget",
            "10000",
        ],
    )

    with pytest.raises(SystemExit):
        parse_args()


def test_manifest_parity_allows_revision_and_runtime_differences(tmp_path):
    legacy, candidate = _arms(tmp_path)
    common = {
        "dataset_name": "gaia",
        "dataset_version": "v1",
        "dataset_item_ids": ["one"],
        "benchmark_lifecycle_mode": "isolated-item",
        "main_model": "model",
        "summary_model": "model",
        "model_endpoint": "https://example.test/v1",
        "model_factory": "openai",
        "temperature": 0.1,
        "max_steps": 10,
        "language": "en",
        "max_concurrency": 1,
        "tool_count": 2,
        "tool_schema_hash": "tools",
        "system_prompt_hash": "prompt",
        "evaluator_names": ["exact_match"],
        "evaluator_version": "code_commit",
    }
    manifests = {
        "L": {
            **common,
            "code_commit": "legacy",
            "context_runtime": "legacy",
            "context_manager_enabled": False,
        },
        "P": {
            **common,
            "code_commit": "candidate",
            "source_tree_hash": "candidate-tree",
            "context_runtime": "context_items",
            "context_processing_mode": "passthrough",
        },
    }
    run_names = {"L": "legacy-run", "P": "candidate-run"}
    for arm in (legacy, candidate):
        arm.manifest_dir.mkdir(parents=True)
        path = arm.manifest_dir / f"{run_names[arm.key]}.manifest.json"
        path.write_text(json.dumps(manifests[arm.key]), encoding="utf-8")

    result = validate_manifest_parity((legacy, candidate), run_names)

    assert result["status"] == "passed"
    assert result["intentional_differences"]["L"]["code_commit"] == "legacy"
    assert result["intentional_differences"]["P"]["code_commit"] == "candidate"


def test_manifest_parity_rejects_prompt_drift(tmp_path):
    legacy, candidate = _arms(tmp_path)
    run_names = {"L": "legacy-run", "P": "candidate-run"}
    base = {
        field: None
        for field in (
            "dataset_name",
            "dataset_version",
            "dataset_item_ids",
            "benchmark_lifecycle_mode",
            "main_model",
            "summary_model",
            "model_endpoint",
            "model_factory",
            "temperature",
            "max_steps",
            "language",
            "max_concurrency",
            "tool_count",
            "tool_schema_hash",
            "evaluator_names",
            "evaluator_version",
        )
    }
    for arm, prompt_hash in ((legacy, "old"), (candidate, "new")):
        arm.manifest_dir.mkdir(parents=True)
        path = arm.manifest_dir / f"{run_names[arm.key]}.manifest.json"
        path.write_text(
            json.dumps({**base, "system_prompt_hash": prompt_hash}),
            encoding="utf-8",
        )

    with pytest.raises(RuntimeError, match="system_prompt_hash"):
        validate_manifest_parity(
            (legacy, candidate),
            run_names,
            require_assembly_parity=True,
        )


def test_main_runs_legacy_and_candidate_arms_and_writes_report(
    monkeypatch,
    tmp_path,
):
    legacy_root = tmp_path / "legacy"
    candidate_root = tmp_path / "candidate"
    args = SimpleNamespace(
        dataset="dataset",
        run_prefix="lp-test",
        legacy_root=legacy_root,
        candidate_root=candidate_root,
        legacy_python=legacy_root / "python",
        candidate_python=candidate_root / "python",
        candidate_soft_input_budget=100,
        candidate_hard_input_budget=200,
        candidate_context_window_tokens=300,
        candidate_budget_profile="synthetic_trigger",
        repeat=1,
        smoke_items=1,
        skip_smoke=True,
        smoke_only=False,
        formal_items=1,
        seed=0,
        required_url=[],
        require_assembly_parity=True,
        runner_args=["--evaluators", "exact_match"],
    )
    monkeypatch.setattr(legacy_module, "parse_args", lambda: args)
    monkeypatch.setattr(legacy_module, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(legacy_module, "validate_arm_paths", lambda arms: None)
    monkeypatch.setattr(
        legacy_module,
        "validate_local_collisions",
        lambda *args, **kwargs: None,
    )
    langfuse = object()
    monkeypatch.setattr(
        legacy_module,
        "preflight",
        lambda **kwargs: (langfuse, ["item-1"]),
    )
    commands = []
    monkeypatch.setattr(
        legacy_module.subprocess,
        "run",
        lambda command, **kwargs: commands.append((command, kwargs)),
    )
    monkeypatch.setattr(
        legacy_module,
        "fetch_run_results",
        lambda langfuse, dataset, run_name, evaluator, **kwargs: {
            "item-1": "-l-legacy" in run_name
        },
    )
    provider_cache = {
        "status": "unsupported",
        "available_calls": 0,
        "hit_calls": 0,
        "provider_prefix_hit_rate": None,
        "provider_cached_tokens": 0,
    }
    summary_cache = {"summary_cache_hits": 0, "summary_cache_types": []}
    monkeypatch.setattr(
        legacy_module,
        "fetch_run_provider_cache",
        lambda *args, **kwargs: [{}],
    )
    monkeypatch.setattr(
        legacy_module,
        "aggregate_provider_cache",
        lambda items: provider_cache,
    )
    monkeypatch.setattr(
        legacy_module,
        "fetch_run_summary_cache",
        lambda *args, **kwargs: [{}],
    )
    monkeypatch.setattr(
        legacy_module,
        "aggregate_summary_cache",
        lambda items: summary_cache,
    )
    monkeypatch.setattr(
        legacy_module,
        "validate_manifest_parity",
        lambda *args, **kwargs: {"status": "matched"},
    )
    written = {}

    def fake_write_report(report, prefix):
        written["report"] = report
        written["prefix"] = prefix
        return tmp_path / "report.json", tmp_path / "report.md"

    monkeypatch.setattr(
        legacy_module,
        "write_report_exclusive",
        fake_write_report,
    )

    legacy_module.main()

    assert len(commands) == 2
    assert {call[1]["cwd"] for call in commands} == {legacy_root, candidate_root}
    candidate_command = next(
        command for command, kwargs in commands if kwargs["cwd"] == candidate_root
    )
    assert "--soft-input-budget" in candidate_command
    legacy_command = next(
        command for command, kwargs in commands if kwargs["cwd"] == legacy_root
    )
    assert "--soft-input-budget" not in legacy_command
    result = written["report"]["results"][0]
    assert result["paired"]["outcome_matrix"] == {"PF": 1}
    assert result["manifest_parity"] == {"status": "matched"}
    assert written["prefix"] == "lp-test"


def test_write_report_exclusive_renders_cross_revision_summary(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(legacy_module, "ARTIFACT_ROOT", tmp_path)
    provider_cache = {
        "status": "available",
        "available_calls": 2,
        "hit_calls": 1,
        "provider_prefix_hit_rate": 0.5,
        "provider_cached_tokens": 20,
    }
    report = {
        "results": [
            {
                "phase": "formal",
                "repeat_index": 1,
                "paired": {
                    "paired_item_count": 1,
                    "outcome_matrix": {"PF": 1},
                },
                "provider_cache": {
                    "L": provider_cache,
                    "P": provider_cache,
                },
            }
        ]
    }

    json_path, markdown_path = legacy_module.write_report_exclusive(
        report,
        "lp unsafe/name",
    )

    assert json_path.name == "lp_unsafe_name.legacy-p.json"
    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "cross-revision regression comparison" in markdown
    assert "| formal | 1 | 1 | 0 | 1 | 0 | 0 |" in markdown
    assert "50.00%" in markdown
