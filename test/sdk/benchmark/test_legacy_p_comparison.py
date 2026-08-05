import json
from pathlib import Path

import pytest

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
