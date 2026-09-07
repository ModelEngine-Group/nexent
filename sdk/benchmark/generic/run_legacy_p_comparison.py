#!/usr/bin/env python3
"""Run a cross-worktree Legacy versus passthrough (P) benchmark."""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


try:
    from .common.benchmark_paths import ARTIFACT_ROOT
    from .run_context_manager_comparison import (
        _primary_evaluator,
        aggregate_provider_cache,
        aggregate_summary_cache,
        fetch_run_provider_cache,
        fetch_run_results,
        fetch_run_summary_cache,
        preflight,
    )
except ImportError:
    from common.benchmark_paths import ARTIFACT_ROOT
    from run_context_manager_comparison import (
        _primary_evaluator,
        aggregate_provider_cache,
        aggregate_summary_cache,
        fetch_run_provider_cache,
        fetch_run_results,
        fetch_run_summary_cache,
        preflight,
    )


GENERIC_DIR = Path(__file__).resolve().parent
REPO_ROOT = GENERIC_DIR.parents[2]
CONTROLLED_RUNNER_ARGS = {
    "--dataset",
    "--run-name",
    "--enable-context-manager",
    "--disable-context-manager",
    "--context-processing-mode",
    "--token-threshold",
    "--soft-input-budget",
    "--hard-input-budget",
    "--budget-profile",
    "--context-window-tokens",
    "--item-limit",
    "--experiment-time",
}
EXECUTION_INVARIANT_FIELDS = (
    "dataset_name",
    "dataset_version",
    "dataset_item_ids",
    "main_model",
    "model_endpoint",
    "model_factory",
    "temperature",
    "max_steps",
    "language",
    "max_concurrency",
    "evaluator_names",
)
ASSEMBLY_PARITY_FIELDS = (
    "benchmark_lifecycle_mode",
    "summary_model",
    "tool_count",
    "tool_schema_hash",
    "system_prompt_hash",
    "evaluator_version",
)


@dataclass(frozen=True)
class ArmSpec:
    key: str
    label: str
    repo_root: Path
    python_executable: Path
    runner_args: tuple[str, ...]

    @property
    def runner(self) -> Path:
        return self.repo_root / "sdk/benchmark/generic/run_benchmark.py"

    @property
    def manifest_dir(self) -> Path:
        if self.repo_root.resolve() == REPO_ROOT.resolve():
            return ARTIFACT_ROOT / "manifests"
        return self.repo_root / "sdk/benchmark/generic/artifacts/manifests"


def comparison_arms(
    *,
    legacy_root: Path,
    legacy_python: Path,
    candidate_root: Path,
    candidate_python: Path,
    candidate_policy_args: tuple[str, ...] = (),
) -> tuple[ArmSpec, ArmSpec]:
    """Return isolated cross-worktree Legacy and P arms."""
    return (
        ArmSpec(
            "L",
            "legacy",
            legacy_root.resolve(),
            Path(os.path.abspath(legacy_python)),
            ("--disable-context-manager",),
        ),
        ArmSpec(
            "P",
            "passthrough",
            candidate_root.resolve(),
            Path(os.path.abspath(candidate_python)),
            (
                "--context-processing-mode",
                "passthrough",
                *candidate_policy_args,
            ),
        ),
    )


def build_run_name(prefix: str, phase: str, repeat_index: int, arm: ArmSpec) -> str:
    """Build an immutable run name that identifies the cross-version arm."""
    return f"{prefix}-{phase}-r{repeat_index:02d}-{arm.key.lower()}-{arm.label}"


def build_runner_command(
    *,
    arm: ArmSpec,
    dataset: str,
    run_name: str,
    runner_args: list[str],
    item_limit: int | None,
    experiment_time: str,
) -> list[str]:
    """Build a runner command rooted in exactly one worktree and interpreter."""
    command = [
        str(arm.python_executable),
        str(arm.runner),
        "--dataset",
        dataset,
        "--run-name",
        run_name,
        "--experiment-time",
        experiment_time,
        *arm.runner_args,
        *runner_args,
    ]
    if item_limit is not None:
        command.extend(["--item-limit", str(item_limit)])
    return command


def validate_runner_args(runner_args: list[str]) -> None:
    """Reject arguments owned by the L/P comparison protocol."""
    for argument in runner_args:
        option = argument.split("=", 1)[0]
        if option in CONTROLLED_RUNNER_ARGS:
            raise ValueError(f"{option} is controlled by the L/P comparison runner")


def validate_arm_paths(arms: tuple[ArmSpec, ...]) -> None:
    """Fail before remote work if a worktree or interpreter is unresolved."""
    for arm in arms:
        if not arm.runner.is_file():
            raise FileNotFoundError(f"{arm.key} runner does not exist: {arm.runner}")
        if not arm.python_executable.is_file():
            raise FileNotFoundError(
                f"{arm.key} Python executable does not exist: {arm.python_executable}"
            )


def manifest_path(manifest_dir: Path, run_name: str) -> Path:
    """Resolve a manifest without importing revision-specific helper code."""
    safe_name = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in run_name
    )
    return manifest_dir / f"{safe_name}.manifest.json"


def validate_local_collisions(
    arms: tuple[ArmSpec, ...],
    planned_run_names: dict[str, list[str]],
) -> None:
    """Check manifest collisions in the worktree that owns each arm."""
    collisions = [
        str(path)
        for arm in arms
        for run_name in planned_run_names[arm.key]
        if (path := manifest_path(arm.manifest_dir, run_name)).exists()
    ]
    if collisions:
        raise FileExistsError(
            "Refusing to overwrite existing arm manifests: " + ", ".join(collisions)
        )


def paired_outcomes(group_results: dict[str, dict[str, bool]]) -> dict[str, Any]:
    """Build the paired Legacy/P outcome matrix for one repeat."""
    if set(group_results) != {"L", "P"}:
        raise ValueError("Legacy/P paired results require exactly L and P")
    item_ids = {key: set(results) for key, results in group_results.items()}
    if any(not ids for ids in item_ids.values()):
        raise ValueError("Legacy/P paired results must be non-empty")
    if item_ids["L"] != item_ids["P"]:
        mismatch = {
            "L_only": sorted(item_ids["L"] - item_ids["P"]),
            "P_only": sorted(item_ids["P"] - item_ids["L"]),
        }
        raise ValueError(
            "Legacy/P dataset item IDs do not match: "
            + json.dumps(mismatch, ensure_ascii=False, sort_keys=True)
        )

    matrix: dict[str, int] = {}
    items = []
    for item_id in sorted(item_ids["L"]):
        pattern = "".join(
            "P" if group_results[key][item_id] else "F"
            for key in ("L", "P")
        )
        matrix[pattern] = matrix.get(pattern, 0) + 1
        items.append(
            {
                "item_id": item_id,
                "legacy": pattern[0],
                "passthrough": pattern[1],
            }
        )
    return {
        "paired_item_count": len(items),
        "outcome_matrix": matrix,
        "items": items,
    }


def validate_manifest_parity(
    arms: tuple[ArmSpec, ...],
    run_names: dict[str, str],
    *,
    require_assembly_parity: bool = False,
) -> dict[str, Any]:
    """Validate comparable settings while allowing intentional revision differences."""
    manifests = {
        arm.key: json.loads(
            manifest_path(arm.manifest_dir, run_names[arm.key]).read_text(
                encoding="utf-8"
            )
        )
        for arm in arms
    }
    execution_mismatches = {
        field: {key: manifest.get(field) for key, manifest in manifests.items()}
        for field in EXECUTION_INVARIANT_FIELDS
        if len(
            {
                json.dumps(manifest.get(field), sort_keys=True)
                for manifest in manifests.values()
            }
        )
        > 1
    }
    if execution_mismatches:
        raise RuntimeError(
            "Legacy/P execution manifest parity failed: "
            + ", ".join(sorted(execution_mismatches))
        )
    assembly_mismatches = {
        field: {key: manifest.get(field) for key, manifest in manifests.items()}
        for field in ASSEMBLY_PARITY_FIELDS
        if len(
            {
                json.dumps(manifest.get(field), sort_keys=True)
                for manifest in manifests.values()
            }
        )
        > 1
    }
    if require_assembly_parity and assembly_mismatches:
        raise RuntimeError(
            "Legacy/P assembly manifest parity failed: "
            + ", ".join(sorted(assembly_mismatches))
        )

    legacy = manifests["L"]
    candidate = manifests["P"]
    if legacy.get("context_runtime") != "legacy":
        raise RuntimeError("L arm did not resolve the legacy context runtime")
    if legacy.get("context_manager_enabled") is not False:
        raise RuntimeError("L arm unexpectedly enabled ContextManager")
    if candidate.get("context_runtime") != "context_items":
        raise RuntimeError("P arm did not resolve the unified ContextItems runtime")
    if candidate.get("context_processing_mode") != "passthrough":
        raise RuntimeError("P arm did not resolve passthrough processing")

    return {
        "status": (
            "passed_with_revision_differences"
            if assembly_mismatches
            else "passed"
        ),
        "causal_scope": (
            "end_to_end_revision"
            if assembly_mismatches
            else "context_runtime_candidate"
        ),
        "checked_execution_fields": list(EXECUTION_INVARIANT_FIELDS),
        "assembly_fields": list(ASSEMBLY_PARITY_FIELDS),
        "assembly_mismatches": assembly_mismatches,
        "intentional_differences": {
            key: {
                "code_commit": manifest.get("code_commit"),
                "source_tree_hash": manifest.get("source_tree_hash"),
                "context_runtime": manifest.get("context_runtime"),
                "context_processing_mode": manifest.get("context_processing_mode"),
                "context_policy_fingerprint": manifest.get(
                    "context_policy_fingerprint"
                ),
            }
            for key, manifest in manifests.items()
        },
    }


def comparison_report_paths(prefix: str) -> tuple[Path, Path]:
    """Keep L/P reports separate from existing P/C comparison artifacts."""
    output_dir = ARTIFACT_ROOT / "legacy_p_comparisons"
    safe_prefix = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in prefix
    )
    return (
        output_dir / f"{safe_prefix}.legacy-p.json",
        output_dir / f"{safe_prefix}.legacy-p.md",
    )


def write_report_exclusive(report: dict[str, Any], prefix: str) -> tuple[Path, Path]:
    """Write immutable cross-version JSON and Markdown reports."""
    json_path, markdown_path = comparison_report_paths(prefix)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    lines = [
        f"# Legacy vs P comparison: {prefix}",
        "",
        "This is a cross-revision regression comparison. It does not by itself "
        "isolate ContextManager as the only causal difference.",
        "",
        "| Phase | Repeat | Paired | PP | PF | FP | FF |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for result in report["results"]:
        matrix = result["paired"]["outcome_matrix"]
        lines.append(
            f"| {result['phase']} | {result['repeat_index']} "
            f"| {result['paired']['paired_item_count']} "
            f"| {matrix.get('PP', 0)} | {matrix.get('PF', 0)} "
            f"| {matrix.get('FP', 0)} | {matrix.get('FF', 0)} |"
        )
    lines.extend(
        [
            "",
            "`PF` means Legacy passed and P failed; `FP` means P passed and Legacy failed.",
            "",
            "## Provider prefix cache",
            "",
            "| Phase | Repeat | Arm | Status | Available calls | Hit calls | Hit rate | Cached tokens |",
            "|---|---:|---|---|---:|---:|---:|---:|",
        ]
    )
    for result in report["results"]:
        for key in ("L", "P"):
            cache = result["provider_cache"][key]
            hit_rate = cache["provider_prefix_hit_rate"]
            lines.append(
                f"| {result['phase']} | {result['repeat_index']} | {key} "
                f"| {cache['status']} | {cache['available_calls']} "
                f"| {cache['hit_calls']} "
                f"| {f'{hit_rate:.2%}' if hit_rate is not None else 'N/A'} "
                f"| {cache['provider_cached_tokens']} |"
            )
    with markdown_path.open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return json_path, markdown_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--run-prefix", required=True)
    parser.add_argument("--legacy-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--legacy-python", type=Path)
    parser.add_argument("--candidate-python", type=Path)
    parser.add_argument("--candidate-soft-input-budget", type=int)
    parser.add_argument("--candidate-hard-input-budget", type=int)
    parser.add_argument("--candidate-context-window-tokens", type=int)
    parser.add_argument(
        "--candidate-budget-profile",
        choices=(
            "legacy_threshold",
            "production_like",
            "synthetic_trigger",
            "synthetic_stress",
        ),
        default="synthetic_trigger",
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--smoke-items", type=int, default=1)
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument(
        "--smoke-only",
        action="store_true",
        help="Run only the smoke phase and omit formal repeats",
    )
    parser.add_argument("--formal-items", type=int)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--required-url", action="append", default=[])
    parser.add_argument(
        "--require-assembly-parity",
        action="store_true",
        help="Fail if prompt/tool/lifecycle hashes differ across revisions",
    )
    parser.add_argument(
        "--runner-args",
        nargs=argparse.REMAINDER,
        default=[],
        help="Arguments forwarded unchanged to both run_benchmark.py versions",
    )
    args = parser.parse_args()
    args.legacy_root = args.legacy_root.resolve()
    args.candidate_root = args.candidate_root.resolve()
    args.legacy_python = (
        args.legacy_python
        or args.legacy_root / "backend/.venv/bin/python"
    )
    args.legacy_python = Path(os.path.abspath(args.legacy_python))
    args.candidate_python = (
        args.candidate_python
        or args.candidate_root / "backend/.venv/bin/python"
    )
    args.candidate_python = Path(os.path.abspath(args.candidate_python))
    if args.repeat <= 0 or args.smoke_items <= 0:
        parser.error("--repeat and --smoke-items must be greater than 0")
    if args.formal_items is not None and args.formal_items <= 0:
        parser.error("--formal-items must be greater than 0")
    if args.skip_smoke and args.smoke_only:
        parser.error("--skip-smoke and --smoke-only cannot be combined")
    candidate_budgets = (
        args.candidate_soft_input_budget,
        args.candidate_hard_input_budget,
    )
    if any(value is not None for value in candidate_budgets) and not all(
        value is not None for value in candidate_budgets
    ):
        parser.error(
            "--candidate-soft-input-budget and --candidate-hard-input-budget "
            "must be provided together"
        )
    if all(value is not None for value in candidate_budgets):
        if args.candidate_soft_input_budget <= 0:
            parser.error("--candidate-soft-input-budget must be greater than 0")
        if args.candidate_hard_input_budget <= args.candidate_soft_input_budget:
            parser.error(
                "--candidate-hard-input-budget must exceed the candidate soft budget"
            )
    if (
        args.candidate_context_window_tokens is not None
        and args.candidate_context_window_tokens <= 0
    ):
        parser.error("--candidate-context-window-tokens must be greater than 0")
    try:
        validate_runner_args(args.runner_args)
    except ValueError as error:
        parser.error(str(error))
    return args


def main() -> None:
    load_dotenv()
    load_dotenv(REPO_ROOT / ".env")
    args = parse_args()
    candidate_policy_args: list[str] = []
    if args.candidate_soft_input_budget is not None:
        candidate_policy_args.extend(
            [
                "--soft-input-budget",
                str(args.candidate_soft_input_budget),
                "--hard-input-budget",
                str(args.candidate_hard_input_budget),
                "--budget-profile",
                args.candidate_budget_profile,
            ]
        )
    if args.candidate_context_window_tokens is not None:
        candidate_policy_args.extend(
            [
                "--context-window-tokens",
                str(args.candidate_context_window_tokens),
            ]
        )
    arms = comparison_arms(
        legacy_root=args.legacy_root,
        legacy_python=args.legacy_python,
        candidate_root=args.candidate_root,
        candidate_python=args.candidate_python,
        candidate_policy_args=tuple(candidate_policy_args),
    )
    validate_arm_paths(arms)

    phases = []
    if not args.skip_smoke:
        phases.append(("smoke", 1, args.smoke_items))
    if not args.smoke_only:
        phases.extend(
            ("formal", index, args.formal_items)
            for index in range(1, args.repeat + 1)
        )
    report_paths = comparison_report_paths(args.run_prefix)
    if any(path.exists() for path in report_paths):
        raise FileExistsError(
            "Refusing to overwrite L/P reports: "
            + ", ".join(str(path) for path in report_paths if path.exists())
        )

    planned_by_arm = {
        arm.key: [
            build_run_name(args.run_prefix, phase, repeat_index, arm)
            for phase, repeat_index, _ in phases
        ]
        for arm in arms
    }
    validate_local_collisions(arms, planned_by_arm)
    all_planned = [
        run_name
        for arm in arms
        for run_name in planned_by_arm[arm.key]
    ]
    langfuse, dataset_item_ids = preflight(
        dataset_name=args.dataset,
        required_urls=args.required_url,
        planned_run_names=all_planned,
    )

    created_at = datetime.now(timezone.utc).isoformat()
    report = {
        "comparison_schema_version": 1,
        "comparison_type": "cross_revision_legacy_vs_passthrough",
        "run_prefix": args.run_prefix,
        "dataset_name": args.dataset,
        "dataset_item_ids": dataset_item_ids,
        "created_at": created_at,
        "evaluator_name": _primary_evaluator(args.runner_args),
        "arms": {
            arm.key: {
                "label": arm.label,
                "repo_root": str(arm.repo_root),
                "python_executable": str(arm.python_executable),
            }
            for arm in arms
        },
        "results": [],
    }
    rng = random.Random(args.seed)
    for phase, repeat_index, item_limit in phases:
        ordered_arms = list(arms)
        rng.shuffle(ordered_arms)
        run_names = {}
        for arm in ordered_arms:
            run_name = build_run_name(
                args.run_prefix,
                phase,
                repeat_index,
                arm,
            )
            run_names[arm.key] = run_name
            command = build_runner_command(
                arm=arm,
                dataset=args.dataset,
                run_name=run_name,
                runner_args=args.runner_args,
                item_limit=item_limit,
                experiment_time=created_at,
            )
            print(f"Running {arm.key} ({arm.label}): {run_name}")
            subprocess.run(command, cwd=arm.repo_root, check=True)

        expected_ids = dataset_item_ids[:item_limit]
        group_results = {
            key: fetch_run_results(
                langfuse,
                args.dataset,
                run_name,
                report["evaluator_name"],
                expected_item_ids=expected_ids,
            )
            for key, run_name in run_names.items()
        }
        provider_cache = {
            key: aggregate_provider_cache(
                fetch_run_provider_cache(
                    langfuse,
                    args.dataset,
                    run_name,
                    expected_item_ids=expected_ids,
                )
            )
            for key, run_name in run_names.items()
        }
        summary_cache = {
            key: aggregate_summary_cache(
                fetch_run_summary_cache(
                    langfuse,
                    args.dataset,
                    run_name,
                    expected_item_ids=expected_ids,
                )
            )
            for key, run_name in run_names.items()
        }
        report["results"].append(
            {
                "phase": phase,
                "repeat_index": repeat_index,
                "run_names": run_names,
                "execution_order": [arm.key for arm in ordered_arms],
                "manifest_parity": validate_manifest_parity(
                    arms,
                    run_names,
                    require_assembly_parity=args.require_assembly_parity,
                ),
                "paired": paired_outcomes(group_results),
                "provider_cache": provider_cache,
                "summary_cache": summary_cache,
            }
        )

    json_path, markdown_path = write_report_exclusive(report, args.run_prefix)
    print(f"Legacy/P comparison complete: {json_path}")
    print(f"Paired summary: {markdown_path}")


if __name__ == "__main__":
    main()
