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


def test_runner_command_omits_item_limit_for_unbounded_formal_run(tmp_path):
    legacy, _ = _arms(tmp_path)

    command = build_runner_command(
        arm=legacy,
        dataset="gaia",
        run_name="comparison-formal-r01-l-legacy",
        runner_args=["--language", "en"],
        item_limit=None,
        experiment_time="2026-08-17T00:00:00+00:00",
    )

    assert "--item-limit" not in command


def test_validate_runner_args_accepts_uncontrolled_options():
    validate_runner_args(["--language", "en", "--evaluators", "exact_match"])


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


@pytest.mark.parametrize(
    ("results", "message"),
    [
        ({"L": {"one": True}}, "exactly L and P"),
        ({"L": {}, "P": {}}, "must be non-empty"),
        (
            {"L": {"one": True}, "P": {"two": True}},
            "dataset item IDs do not match",
        ),
    ],
)
def test_paired_outcomes_rejects_invalid_inputs(results, message):
    with pytest.raises(ValueError, match=message):
        paired_outcomes(results)


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


def _base_lp_cli(tmp_path):
    return [
        "runner",
        "--dataset",
        "gaia",
        "--run-prefix",
        "lp",
        "--legacy-root",
        str(tmp_path),
    ]


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--repeat", "0"],
        ["--smoke-items", "0"],
        ["--formal-items", "0"],
        ["--skip-smoke", "--smoke-only"],
        [
            "--candidate-soft-input-budget",
            "0",
            "--candidate-hard-input-budget",
            "20",
        ],
        [
            "--candidate-soft-input-budget",
            "20",
            "--candidate-hard-input-budget",
            "20",
        ],
        ["--candidate-context-window-tokens", "0"],
        ["--runner-args", "--dataset", "other"],
    ],
)
def test_parse_args_rejects_invalid_lp_configuration(monkeypatch, tmp_path, extra_args):
    from sdk.benchmark.generic.run_legacy_p_comparison import parse_args

    monkeypatch.setattr("sys.argv", [*_base_lp_cli(tmp_path), *extra_args])

    with pytest.raises(SystemExit):
        parse_args()


def test_arm_manifest_dir_uses_shared_artifact_root_for_current_repo(monkeypatch, tmp_path):
    monkeypatch.setattr(legacy_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(legacy_module, "ARTIFACT_ROOT", tmp_path / "artifacts")
    arm = legacy_module.ArmSpec("P", "passthrough", tmp_path, tmp_path / "python", ())

    assert arm.manifest_dir == tmp_path / "artifacts/manifests"


def test_validate_arm_paths_accepts_complete_arm(tmp_path):
    repo_root = tmp_path / "repo"
    runner = repo_root / "sdk/benchmark/generic/run_benchmark.py"
    runner.parent.mkdir(parents=True)
    runner.touch()
    python = repo_root / "python"
    python.touch()
    arm = legacy_module.ArmSpec("L", "legacy", repo_root, python, ())

    legacy_module.validate_arm_paths((arm,))


@pytest.mark.parametrize("missing", ["runner", "python"])
def test_validate_arm_paths_rejects_missing_executable(tmp_path, missing):
    repo_root = tmp_path / "repo"
    runner = repo_root / "sdk/benchmark/generic/run_benchmark.py"
    runner.parent.mkdir(parents=True)
    python = repo_root / "python"
    if missing != "runner":
        runner.touch()
    if missing != "python":
        python.touch()
    arm = legacy_module.ArmSpec("L", "legacy", repo_root, python, ())

    with pytest.raises(FileNotFoundError, match=missing.capitalize() if missing == "python" else "runner"):
        legacy_module.validate_arm_paths((arm,))


def test_validate_local_collisions_rejects_existing_manifest(tmp_path):
    legacy, candidate = _arms(tmp_path)
    legacy.manifest_dir.mkdir(parents=True)
    legacy_module.manifest_path(legacy.manifest_dir, "existing/run").touch()

    with pytest.raises(FileExistsError, match="existing arm manifests"):
        legacy_module.validate_local_collisions(
            (legacy, candidate),
            {"L": ["existing/run"], "P": ["new-run"]},
        )


def test_validate_local_collisions_accepts_new_run_names(tmp_path):
    legacy, candidate = _arms(tmp_path)

    legacy_module.validate_local_collisions(
        (legacy, candidate),
        {"L": ["legacy-new"], "P": ["candidate-new"]},
    )


def test_parse_args_accepts_complete_candidate_limits(monkeypatch, tmp_path):
    from sdk.benchmark.generic.run_legacy_p_comparison import parse_args

    monkeypatch.setattr(
        "sys.argv",
        [
            *_base_lp_cli(tmp_path),
            "--candidate-soft-input-budget",
            "10",
            "--candidate-hard-input-budget",
            "20",
            "--candidate-context-window-tokens",
            "30",
        ],
    )

    args = parse_args()

    assert args.candidate_soft_input_budget == 10
    assert args.candidate_hard_input_budget == 20
    assert args.candidate_context_window_tokens == 30


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


def _write_runtime_manifests(tmp_path, *, legacy_changes=None, candidate_changes=None):
    legacy, candidate = _arms(tmp_path)
    run_names = {"L": "legacy-run", "P": "candidate-run"}
    common = {field: None for field in legacy_module.EXECUTION_INVARIANT_FIELDS}
    common.update({field: None for field in legacy_module.ASSEMBLY_PARITY_FIELDS})
    manifests = {
        "L": {
            **common,
            "context_runtime": "legacy",
            "context_manager_enabled": False,
        },
        "P": {
            **common,
            "context_runtime": "context_items",
            "context_processing_mode": "passthrough",
        },
    }
    manifests["L"].update(legacy_changes or {})
    manifests["P"].update(candidate_changes or {})
    for arm in (legacy, candidate):
        arm.manifest_dir.mkdir(parents=True)
        legacy_module.manifest_path(
            arm.manifest_dir,
            run_names[arm.key],
        ).write_text(json.dumps(manifests[arm.key]), encoding="utf-8")
    return (legacy, candidate), run_names


def test_manifest_parity_rejects_execution_setting_drift(tmp_path):
    arms, run_names = _write_runtime_manifests(
        tmp_path,
        candidate_changes={"dataset_name": "other-dataset"},
    )

    with pytest.raises(RuntimeError, match="execution manifest parity"):
        validate_manifest_parity(arms, run_names)


@pytest.mark.parametrize(
    ("legacy_changes", "candidate_changes", "message"),
    [
        ({"context_runtime": "context_items"}, {}, "legacy context runtime"),
        ({"context_manager_enabled": True}, {}, "enabled ContextManager"),
        ({}, {"context_runtime": "legacy"}, "unified ContextItems runtime"),
        ({}, {"context_processing_mode": "adaptive_compact"}, "passthrough processing"),
    ],
)
def test_manifest_parity_rejects_invalid_arm_runtime(
    tmp_path,
    legacy_changes,
    candidate_changes,
    message,
):
    arms, run_names = _write_runtime_manifests(
        tmp_path,
        legacy_changes=legacy_changes,
        candidate_changes=candidate_changes,
    )

    with pytest.raises(RuntimeError, match=message):
        validate_manifest_parity(arms, run_names)


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
        skip_smoke=False,
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

    assert len(commands) == 4
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


def test_main_rejects_existing_lp_report(monkeypatch, tmp_path):
    legacy_root = tmp_path / "legacy"
    candidate_root = tmp_path / "candidate"
    args = SimpleNamespace(
        dataset="dataset",
        run_prefix="existing",
        legacy_root=legacy_root,
        candidate_root=candidate_root,
        legacy_python=legacy_root / "python",
        candidate_python=candidate_root / "python",
        candidate_soft_input_budget=None,
        candidate_hard_input_budget=None,
        candidate_context_window_tokens=None,
        candidate_budget_profile="synthetic_trigger",
        repeat=1,
        smoke_items=1,
        skip_smoke=True,
        smoke_only=False,
        formal_items=1,
    )
    monkeypatch.setattr(legacy_module, "parse_args", lambda: args)
    monkeypatch.setattr(legacy_module, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(legacy_module, "validate_arm_paths", lambda arms: None)
    report_path, _ = legacy_module.comparison_report_paths(args.run_prefix)
    report_path.parent.mkdir(parents=True)
    report_path.write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError, match="L/P reports"):
        legacy_module.main()


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
