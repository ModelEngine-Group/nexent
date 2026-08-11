#!/usr/bin/env python3
"""Run paired ContextItems passthrough / adaptive-compaction benchmarks."""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


try:
    from .common.benchmark_paths import ARTIFACT_ROOT
except ImportError:
    from common.benchmark_paths import ARTIFACT_ROOT

GENERIC_DIR = Path(__file__).resolve().parent
REPO_ROOT = GENERIC_DIR.parents[2]
RUNNER = GENERIC_DIR / "run_benchmark.py"
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
    "--item-limit",
    "--experiment-time",
}


@dataclass(frozen=True)
class GroupSpec:
    key: str
    label: str
    runner_args: tuple[str, ...]


def comparison_groups(
    compression_threshold: int | None = None,
    *,
    soft_input_budget: int | None = None,
    hard_input_budget: int | None = None,
    budget_profile: str = "legacy_threshold",
) -> tuple[GroupSpec, ...]:
    """Return the two standard same-code comparison groups."""
    if soft_input_budget is not None and hard_input_budget is not None:
        budget_args = (
            "--soft-input-budget",
            str(soft_input_budget),
            "--hard-input-budget",
            str(hard_input_budget),
            "--budget-profile",
            budget_profile,
        )
        compact_args = budget_args
    else:
        threshold = compression_threshold or 10_000
        budget_args = (
            "--token-threshold",
            str(threshold),
            "--budget-profile",
            "legacy_threshold",
        )
        compact_args = budget_args
    return (
        GroupSpec(
            "P",
            "passthrough",
            ("--context-processing-mode", "passthrough", *budget_args),
        ),
        GroupSpec(
            "C",
            "adaptive-compact",
            (
                "--context-processing-mode",
                "adaptive_compact",
                *compact_args,
            ),
        ),
    )


def build_run_name(prefix: str, phase: str, repeat_index: int, group: GroupSpec) -> str:
    """Build a paired and collision-resistant run name."""
    return f"{prefix}-{phase}-r{repeat_index:02d}-{group.key.lower()}-{group.label}"


def build_runner_command(
    *,
    python_executable: str,
    dataset: str,
    run_name: str,
    group: GroupSpec,
    runner_args: list[str],
    item_limit: int | None,
    experiment_time: str,
) -> list[str]:
    """Build a child runner command while keeping experimental variables owned here."""
    command = [
        python_executable,
        str(RUNNER),
        "--dataset",
        dataset,
        "--run-name",
        run_name,
        "--experiment-time",
        experiment_time,
        *group.runner_args,
        *runner_args,
    ]
    if item_limit is not None:
        command.extend(["--item-limit", str(item_limit)])
    return command


def validate_runner_args(runner_args: list[str]) -> None:
    """Reject child arguments that could invalidate the standard comparison."""
    for argument in runner_args:
        option = argument.split("=", 1)[0]
        if option in CONTROLLED_RUNNER_ARGS:
            raise ValueError(f"{option} is controlled by the comparison runner")


def preflight(
    *,
    dataset_name: str,
    required_urls: list[str],
    planned_run_names: list[str],
) -> tuple[Any, list[str]]:
    """Validate Langfuse, dataset pairing, declared services, and run uniqueness."""
    from langfuse import Langfuse

    langfuse = Langfuse()
    if not langfuse.auth_check():
        raise RuntimeError("Langfuse authentication failed")
    dataset = langfuse.get_dataset(dataset_name)
    item_ids = [str(item.id) for item in dataset.items]
    if not item_ids:
        raise ValueError(f"Dataset '{dataset_name}' is empty")
    if len(item_ids) != len(set(item_ids)):
        raise ValueError(f"Dataset '{dataset_name}' contains duplicate item IDs")

    for value in required_urls:
        name, separator, url = value.partition("=")
        if not separator or not name or not url:
            raise ValueError("--required-url must use NAME=URL")
        response = requests.get(url, timeout=10)
        if response.status_code >= 500:
            raise RuntimeError(
                f"Required service '{name}' is unhealthy: HTTP {response.status_code}"
            )

    manifest_dir = ARTIFACT_ROOT / "manifests"
    from provenance.experiment_manifest import manifest_path

    collisions = [
        run_name
        for run_name in planned_run_names
        if manifest_path(manifest_dir, run_name).exists()
    ]
    if collisions:
        raise FileExistsError(
            "Refusing to overwrite existing local runs: " + ", ".join(collisions)
        )

    remote_collisions = []
    for run_name in planned_run_names:
        try:
            langfuse.get_dataset_run(dataset_name, run_name)
        except Exception as error:
            if getattr(error, "status_code", None) == 404:
                continue
            raise RuntimeError(
                f"Unable to verify whether Langfuse run '{run_name}' exists"
            ) from error
        remote_collisions.append(run_name)
    if remote_collisions:
        raise FileExistsError(
            "Refusing to reuse existing Langfuse runs: " + ", ".join(remote_collisions)
        )
    return langfuse, item_ids


def fetch_run_results(
    langfuse: Any,
    dataset_name: str,
    run_name: str,
    evaluator_name: str,
    expected_item_ids: list[str] | None = None,
    attempts: int = 10,
) -> dict[str, bool]:
    """Fetch per-item results after run-item links and evaluator scores settle."""
    run = fetch_complete_dataset_run(
        langfuse,
        dataset_name,
        run_name,
        expected_item_ids=expected_item_ids,
        attempts=attempts,
    )

    missing_scores: list[str] = []
    for attempt in range(attempts):
        results: dict[str, bool] = {}
        missing_scores = []
        for run_item in run.dataset_run_items:
            item_id = str(run_item.dataset_item_id)
            trace = langfuse.get_trace(run_item.trace_id)
            score = next(
                (
                    candidate
                    for candidate in (trace.scores or [])
                    if candidate.name == evaluator_name
                    and candidate.value is not None
                ),
                None,
            )
            if score is None:
                missing_scores.append(item_id)
                continue
            results[item_id] = float(score.value) >= 1.0

        if not missing_scores:
            return results
        if attempt < attempts - 1:
            time.sleep(1.0)

    raise TimeoutError(
        f"Langfuse dataset run '{run_name}' did not expose evaluator score "
        f"'{evaluator_name}' for all items after {attempts} attempts: "
        + json.dumps(
            {"missing_scores": sorted(missing_scores)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def fetch_run_provider_cache(
    langfuse: Any,
    dataset_name: str,
    run_name: str,
    expected_item_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch provider-reported prefix-cache metrics from benchmark trace outputs."""
    run = fetch_complete_dataset_run(
        langfuse,
        dataset_name,
        run_name,
        expected_item_ids=expected_item_ids,
    )
    results = {}
    for run_item in run.dataset_run_items:
        trace = langfuse.get_trace(run_item.trace_id)
        output = trace.output
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except (TypeError, ValueError, json.JSONDecodeError):
                output = {}
        provider_cache = (
            output.get("provider_cache", {})
            if isinstance(output, dict)
            else {}
        )
        results[str(run_item.dataset_item_id)] = provider_cache
    return results


def fetch_run_summary_cache(
    langfuse: Any,
    dataset_name: str,
    run_name: str,
    expected_item_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch ContextManager summary-cache metrics separately from provider cache."""
    run = fetch_complete_dataset_run(
        langfuse,
        dataset_name,
        run_name,
        expected_item_ids=expected_item_ids,
    )
    results = {}
    for run_item in run.dataset_run_items:
        trace = langfuse.get_trace(run_item.trace_id)
        output = trace.output
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except (TypeError, ValueError, json.JSONDecodeError):
                output = {}
        compression = output.get("compression", {}) if isinstance(output, dict) else {}
        results[str(run_item.dataset_item_id)] = {
            "summary_cache_hits": compression.get("summary_cache_hits", 0) or 0,
            "summary_cache_types": compression.get("summary_cache_types", []) or [],
        }
    return results


def fetch_run_budget_evidence(
    langfuse: Any,
    dataset_name: str,
    run_name: str,
    expected_item_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch per-item budget/overflow evidence from trace outputs."""
    run = fetch_complete_dataset_run(
        langfuse,
        dataset_name,
        run_name,
        expected_item_ids=expected_item_ids,
    )
    results = {}
    for run_item in run.dataset_run_items:
        trace = langfuse.get_trace(run_item.trace_id)
        output = trace.output
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except (TypeError, ValueError, json.JSONDecodeError):
                output = {}
        budget = output.get("budget_evidence", {}) if isinstance(output, dict) else {}
        results[str(run_item.dataset_item_id)] = budget
    return results


def fetch_complete_dataset_run(
    langfuse: Any,
    dataset_name: str,
    run_name: str,
    *,
    expected_item_ids: list[str] | None,
    attempts: int = 30,
    retry_delay: float = 1.0,
) -> Any:
    """Wait for Langfuse's eventually consistent dataset-run links to settle."""
    expected = set(expected_item_ids or [])
    last_seen: set[str] = set()
    for attempt in range(attempts):
        try:
            run = langfuse.get_dataset_run(dataset_name, run_name)
        except Exception:
            if attempt == attempts - 1:
                raise
        else:
            last_seen = {
                str(run_item.dataset_item_id)
                for run_item in run.dataset_run_items
            }
            if not expected or last_seen == expected:
                return run
        if attempt < attempts - 1:
            time.sleep(retry_delay)

    missing = sorted(expected - last_seen)
    unexpected = sorted(last_seen - expected)
    raise TimeoutError(
        f"Langfuse dataset run '{run_name}' did not expose the complete item set "
        f"after {attempts} attempts: "
        + json.dumps(
            {"missing": missing, "unexpected": unexpected},
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def aggregate_summary_cache(
    item_metrics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate ContextManager-local summary reuse."""
    cache_types = sorted({
        cache_type
        for metric in item_metrics.values()
        for cache_type in metric.get("summary_cache_types", [])
    })
    return {
        "summary_cache_hits": sum(
            metric.get("summary_cache_hits", 0) or 0
            for metric in item_metrics.values()
        ),
        "summary_cache_types": cache_types,
    }


def aggregate_provider_cache(
    item_metrics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate only calls for which provider cache metrics were explicit."""
    available_calls = sum(
        metric.get("available_calls", 0) or 0
        for metric in item_metrics.values()
        if metric.get("status") == "available"
    )
    hit_calls = sum(
        metric.get("hit_calls", 0) or 0
        for metric in item_metrics.values()
        if metric.get("status") == "available"
    )
    cached_tokens = sum(
        metric.get("provider_cached_tokens", 0) or 0
        for metric in item_metrics.values()
        if metric.get("status") == "available"
    )
    provider_input_tokens = sum(
        metric.get("provider_input_tokens", 0) or 0
        for metric in item_metrics.values()
        if metric.get("status") == "available"
    )
    statuses = sorted({
        metric.get("status", "unsupported")
        for metric in item_metrics.values()
    })
    if available_calls:
        status = "available"
    elif "unavailable" in statuses:
        status = "unavailable"
    else:
        status = "unsupported"
    return {
        "status": status,
        "item_count": len(item_metrics),
        "available_calls": available_calls,
        "hit_calls": hit_calls,
        "provider_prefix_hit_rate": (
            round(hit_calls / available_calls, 4)
            if available_calls
            else None
        ),
        "provider_cached_tokens": cached_tokens,
        "provider_input_tokens": provider_input_tokens,
        "provider_cached_input_ratio": (
            round(cached_tokens / provider_input_tokens, 4)
            if provider_input_tokens
            else None
        ),
    }


def aggregate_budget_evidence(
    item_metrics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate budget/overflow evidence across items."""
    total_items = len(item_metrics)
    over_soft = sum(1 for m in item_metrics.values() if m.get("over_soft_budget"))
    over_hard = sum(1 for m in item_metrics.values() if m.get("over_hard_budget"))
    compression_triggered = sum(1 for m in item_metrics.values() if m.get("compression_triggered"))
    peak_tokens_list = [m.get("peak_context_tokens", 0) for m in item_metrics.values()]
    return {
        "total_items": total_items,
        "over_soft_budget_count": over_soft,
        "over_hard_budget_count": over_hard,
        "compression_triggered_count": compression_triggered,
        "overflow_avoidance_rate": (
            round(1 - over_hard / total_items, 4) if total_items else None
        ),
        "max_peak_context_tokens": max(peak_tokens_list) if peak_tokens_list else 0,
        "avg_peak_context_tokens": (
            round(sum(peak_tokens_list) / len(peak_tokens_list))
            if peak_tokens_list
            else 0
        ),
    }


def paired_outcomes(group_results: dict[str, dict[str, bool]]) -> dict[str, Any]:
    """Build the paired P/C outcome matrix for one repeat."""
    item_ids = {
        key: set(results)
        for key, results in group_results.items()
    }
    if not item_ids or any(not ids for ids in item_ids.values()):
        raise ValueError("P/C paired results must all be non-empty")
    reference_key = next(iter(item_ids))
    reference_ids = item_ids[reference_key]
    mismatches = {
        key: {
            "missing": sorted(reference_ids - ids),
            "unexpected": sorted(ids - reference_ids),
        }
        for key, ids in item_ids.items()
        if ids != reference_ids
    }
    if mismatches:
        raise ValueError(
            "P/C dataset item IDs do not match: "
            + json.dumps(mismatches, ensure_ascii=False, sort_keys=True)
        )

    matrix: dict[str, int] = {}
    items = []
    for item_id in sorted(reference_ids):
        pattern = "".join("P" if group_results[key][item_id] else "F" for key in ("P", "C"))
        matrix[pattern] = matrix.get(pattern, 0) + 1
        items.append({"item_id": item_id, "P": pattern[0], "C": pattern[1]})
    return {
        "paired_item_count": len(reference_ids),
        "outcome_matrix": matrix,
        "items": items,
    }


def _normalize_snapshot_processing_mode(snapshot: Any) -> Any:
    """Replace only the P/C processing-mode variable before comparison."""
    normalized = json.loads(json.dumps(snapshot))
    if not isinstance(normalized, dict):
        return normalized
    policy = normalized.get("policy")
    if not isinstance(policy, dict):
        return normalized
    if "effective_processing_mode" in policy:
        policy["effective_processing_mode"] = "<processing_mode>"
    policy_layers = policy.get("policy_layers")
    if not isinstance(policy_layers, dict):
        return normalized
    platform_policy = policy_layers.get("platform")
    if isinstance(platform_policy, dict) and "processing_mode" in platform_policy:
        platform_policy["processing_mode"] = "<processing_mode>"
    return normalized


def validate_manifest_parity(run_names: dict[str, str]) -> dict[str, Any]:
    """Ensure settings other than the P/C processing mode are identical."""
    try:
        from .provenance.experiment_manifest import manifest_path
    except ImportError:
        from provenance.experiment_manifest import manifest_path

    manifest_dir = ARTIFACT_ROOT / "manifests"
    manifests = {
        key: json.loads(
            manifest_path(manifest_dir, run_name).read_text(encoding="utf-8")
        )
        for key, run_name in run_names.items()
    }
    invariant_fields = (
        "dataset_name",
        "dataset_version",
        "dataset_item_ids",
        "source_tree_hash",
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
        "system_prompt_hash",
        "budget_profile",
        "evaluator_names",
        "evaluator_version",
    )
    mismatches = {
        field: {key: manifest.get(field) for key, manifest in manifests.items()}
        for field in invariant_fields
        if len({json.dumps(manifest.get(field), sort_keys=True) for manifest in manifests.values()}) > 1
    }
    normalized_snapshots = {
        key: _normalize_snapshot_processing_mode(manifest.get("parity_snapshot") or {})
        for key, manifest in manifests.items()
    }
    serialized_snapshots = {
        json.dumps(snapshot, sort_keys=True)
        for snapshot in normalized_snapshots.values()
    }
    if len(serialized_snapshots) > 1:
        mismatches["parity_snapshot_except_processing_mode"] = {
            key: manifest.get("parity_snapshot_hash")
            for key, manifest in manifests.items()
        }
    if mismatches:
        raise RuntimeError(
            "P/C resolved manifest parity failed: "
            + ", ".join(sorted(mismatches))
        )
    commit_values = {
        key: manifest.get("code_commit") for key, manifest in manifests.items()
    }
    if len(set(commit_values.values())) > 1:
        tree_values = {
            key: manifest.get("source_tree_hash") for key, manifest in manifests.items()
        }
        if len(set(tree_values.values())) == 1:
            print(
                "WARNING: code_commit differs across groups but source_tree_hash "
                f"is identical ({tree_values.get('P', '')[:12]}...); "
                f"commits: {commit_values}",
                file=sys.stderr,
            )
    modes = {key: manifest.get("context_processing_mode") for key, manifest in manifests.items()}
    if modes != {"P": "passthrough", "C": "adaptive_compact"}:
        raise RuntimeError(f"P/C processing modes are invalid: {modes}")
    for key, manifest in manifests.items():
        if manifest.get("context_runtime") != "context_items":
            raise RuntimeError(f"{key} did not use the unified ContextItems runtime")
        config = manifest.get("context_manager") or {}
        if not config.get("hard_input_budget_tokens"):
            raise RuntimeError(f"{key} manifest is missing a resolved hard input budget")
        if not manifest.get("context_policy_fingerprint"):
            raise RuntimeError(f"{key} manifest is missing a context policy fingerprint")
    return {
        "status": "passed",
        "checked_fields": [*invariant_fields, "parity_snapshot_except_processing_mode"],
        "target_fields": [
            "context_processing_mode",
            "adaptive_compaction_enabled",
            "context_policy_fingerprint",
        ],
        "context_evidence_contract": [
            "processing_mode",
            "policy_fingerprint",
            "hard_budget",
            "over_hard_budget",
            "raw_token_estimate",
            "final_token_estimate",
        ],
    }


def write_report_exclusive(report: dict[str, Any], prefix: str) -> tuple[Path, Path]:
    """Write immutable JSON and Markdown comparison summaries."""
    json_path, markdown_path = comparison_report_paths(prefix)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    lines = [
        f"# ContextManager comparison: {prefix}",
        "",
        "P vs C measures adaptive compaction on the same ContextItems runtime.",
        "",
        f"- Budget profile: `{report['budget_profile']}`",
        f"- Soft input budget: `{report['thresholds'].get('soft_input_budget')}`",
        f"- Hard input budget: `{report['thresholds'].get('hard_input_budget')}`",
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
    lines.extend([
        "",
        "## Provider prefix cache",
        "",
        "| Phase | Repeat | Group | Status | Available calls | Hit calls | Hit rate | Cached tokens | Cached input ratio |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|",
    ])
    for result in report["results"]:
        for group in ("P", "C"):
            cache = result["provider_cache"][group]
            hit_rate = cache["provider_prefix_hit_rate"]
            cached_ratio = cache["provider_cached_input_ratio"]
            lines.append(
                f"| {result['phase']} | {result['repeat_index']} | {group} "
                f"| {cache['status']} | {cache['available_calls']} "
                f"| {cache['hit_calls']} "
                f"| {f'{hit_rate:.2%}' if hit_rate is not None else 'N/A'} "
                f"| {cache['provider_cached_tokens']} "
                f"| {f'{cached_ratio:.2%}' if cached_ratio is not None else 'N/A'} |"
            )
    lines.extend([
        "",
        "## ContextManager summary cache",
        "",
        "| Phase | Repeat | Group | Hits | Types |",
        "|---|---:|---|---:|---|",
    ])
    for result in report["results"]:
        for group in ("P", "C"):
            cache = result["summary_cache"][group]
            lines.append(
                f"| {result['phase']} | {result['repeat_index']} | {group} "
                f"| {cache['summary_cache_hits']} "
                f"| {', '.join(cache['summary_cache_types']) or 'none'} |"
            )
    lines.extend([
        "",
        "## Budget & overflow",
        "",
        "| Phase | Repeat | Group | Items | Over soft | Over hard | Compression triggered | Avoidance rate | Max peak ctx |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ])
    for result in report["results"]:
        for group in ("P", "C"):
            budget = result["budget_evidence"][group]
            avoidance = budget["overflow_avoidance_rate"]
            lines.append(
                f"| {result['phase']} | {result['repeat_index']} | {group} "
                f"| {budget['total_items']} "
                f"| {budget['over_soft_budget_count']} "
                f"| {budget['over_hard_budget_count']} "
                f"| {budget['compression_triggered_count']} "
                f"| {f'{avoidance:.2%}' if avoidance is not None else 'N/A'} "
                f"| {budget['max_peak_context_tokens']} |"
            )
    with markdown_path.open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return json_path, markdown_path


def comparison_report_paths(prefix: str) -> tuple[Path, Path]:
    """Return immutable report paths for a comparison prefix."""
    output_dir = ARTIFACT_ROOT / "comparisons"
    safe_prefix = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in prefix
    )
    json_path = output_dir / f"{safe_prefix}.comparison.json"
    markdown_path = output_dir / f"{safe_prefix}.comparison.md"
    return json_path, markdown_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--run-prefix", required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--smoke-items", type=int, default=1)
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--formal-items", type=int)
    parser.add_argument(
        "--compression-threshold",
        type=int,
        help="Legacy shorthand that derives hard budget as threshold * 1.1",
    )
    parser.add_argument("--soft-input-budget", type=int)
    parser.add_argument("--hard-input-budget", type=int)
    parser.add_argument(
        "--budget-profile",
        choices=("legacy_threshold", "synthetic_trigger", "synthetic_stress"),
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--required-url", action="append", default=[])
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--runner-args",
        nargs=argparse.REMAINDER,
        default=[],
        help="Arguments forwarded unchanged to run_benchmark.py",
    )
    args = parser.parse_args()
    for name in (
        "repeat",
        "smoke_items",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be greater than 0")
    if args.formal_items is not None and args.formal_items <= 0:
        parser.error("--formal-items must be greater than 0")
    explicit_budgets = (
        args.soft_input_budget is not None,
        args.hard_input_budget is not None,
    )
    if any(explicit_budgets) and not all(explicit_budgets):
        parser.error(
            "--soft-input-budget and --hard-input-budget must be provided together"
        )
    if all(explicit_budgets):
        if args.compression_threshold is not None:
            parser.error(
                "--compression-threshold cannot be combined with explicit soft/hard budgets"
            )
        if args.soft_input_budget <= 0 or args.hard_input_budget <= 0:
            parser.error("soft/hard input budgets must be greater than 0")
        if args.soft_input_budget >= args.hard_input_budget:
            parser.error("--soft-input-budget must be less than --hard-input-budget")
        if args.budget_profile not in {"synthetic_trigger", "synthetic_stress"}:
            parser.error(
                "explicit soft/hard budgets require --budget-profile "
                "synthetic_trigger or synthetic_stress"
            )
    else:
        args.compression_threshold = args.compression_threshold or 10_000
        args.budget_profile = args.budget_profile or "legacy_threshold"
        if args.compression_threshold <= 0:
            parser.error("--compression-threshold must be greater than 0")
        if args.budget_profile != "legacy_threshold":
            parser.error(
                "synthetic budget profiles require explicit soft/hard budgets"
            )
    try:
        validate_runner_args(args.runner_args)
    except ValueError as error:
        parser.error(str(error))
    return args


def main() -> None:
    load_dotenv()
    load_dotenv(REPO_ROOT / ".env")
    args = parse_args()
    groups = comparison_groups(
        args.compression_threshold,
        soft_input_budget=args.soft_input_budget,
        hard_input_budget=args.hard_input_budget,
        budget_profile=args.budget_profile,
    )
    phases = []
    if not args.skip_smoke:
        phases.append(("smoke", 1, args.smoke_items))
    phases.extend(("formal", index, args.formal_items) for index in range(1, args.repeat + 1))
    report_collisions = [
        path
        for path in comparison_report_paths(args.run_prefix)
        if path.exists()
    ]
    if report_collisions:
        raise FileExistsError(
            "Refusing to overwrite comparison reports: "
            + ", ".join(str(path) for path in report_collisions)
        )

    planned = [
        build_run_name(args.run_prefix, phase, repeat_index, group)
        for phase, repeat_index, _ in phases
        for group in groups
    ]
    langfuse, dataset_item_ids = preflight(
        dataset_name=args.dataset,
        required_urls=args.required_url,
        planned_run_names=planned,
    )
    print(
        f"Preflight passed: dataset={args.dataset}, items={len(dataset_item_ids)}, "
        f"planned_runs={len(planned)}"
    )

    report = {
        "comparison_schema_version": 2,
        "run_prefix": args.run_prefix,
        "dataset_name": args.dataset,
        "dataset_item_ids": dataset_item_ids,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "budget_profile": args.budget_profile,
        "thresholds": {
            "compression_threshold": args.compression_threshold,
            "soft_input_budget": args.soft_input_budget,
            "hard_input_budget": args.hard_input_budget,
        },
        "evaluator_name": _primary_evaluator(args.runner_args),
        "results": [],
    }
    experiment_time = report["created_at"]
    rng = random.Random(args.seed)
    for phase, repeat_index, item_limit in phases:
        ordered_groups = list(groups)
        rng.shuffle(ordered_groups)
        run_names = {}
        for group in ordered_groups:
            run_name = build_run_name(args.run_prefix, phase, repeat_index, group)
            run_names[group.key] = run_name
            command = build_runner_command(
                python_executable=args.python,
                dataset=args.dataset,
                run_name=run_name,
                group=group,
                runner_args=args.runner_args,
                item_limit=item_limit,
                experiment_time=experiment_time,
            )
            print(f"Running {group.key} ({group.label}): {run_name}")
            subprocess.run(command, cwd=REPO_ROOT, check=True)

        group_results = {
            key: fetch_run_results(
                langfuse,
                args.dataset,
                run_name,
                report["evaluator_name"],
                expected_item_ids=dataset_item_ids[:item_limit],
            )
            for key, run_name in run_names.items()
        }
        provider_cache = {
            key: aggregate_provider_cache(
                fetch_run_provider_cache(
                    langfuse,
                    args.dataset,
                    run_name,
                    expected_item_ids=dataset_item_ids[:item_limit],
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
                    expected_item_ids=dataset_item_ids[:item_limit],
                )
            )
            for key, run_name in run_names.items()
        }
        budget_evidence = {
            key: aggregate_budget_evidence(
                fetch_run_budget_evidence(
                    langfuse,
                    args.dataset,
                    run_name,
                    expected_item_ids=dataset_item_ids[:item_limit],
                )
            )
            for key, run_name in run_names.items()
        }

        try:
            from .run_integrity import check_run_integrity
        except ImportError:
            from run_integrity import check_run_integrity

        integrity: dict[str, Any] = {}
        evaluator_names = _all_evaluators(args.runner_args)
        for key, run_name in run_names.items():
            manifest_data = None
            try:
                from provenance.experiment_manifest import manifest_path as _mp

                _manifest_dir = ARTIFACT_ROOT / "manifests"
                _mpath = _mp(_manifest_dir, run_name)
                if _mpath.exists():
                    manifest_data = json.loads(
                        _mpath.read_text(encoding="utf-8")
                    )
            except Exception:
                pass
            integrity_report = check_run_integrity(
                langfuse=langfuse,
                dataset_name=args.dataset,
                run_name=run_name,
                expected_item_ids=dataset_item_ids[:item_limit],
                evaluator_names=evaluator_names,
                manifest=manifest_data,
            )
            integrity[key] = integrity_report.to_dict()
            if not integrity_report.run_complete:
                print(
                    f"WARNING: integrity check INCOMPLETE for "
                    f"{key} ({run_name})"
                )
                print(integrity_report.summary())

        report["results"].append(
            {
                "phase": phase,
                "repeat_index": repeat_index,
                "run_names": run_names,
                "execution_order": [group.key for group in ordered_groups],
                "manifest_parity": validate_manifest_parity(run_names),
                "paired": paired_outcomes(group_results),
                "provider_cache": provider_cache,
                "summary_cache": summary_cache,
                "budget_evidence": budget_evidence,
                "integrity": integrity,
            }
        )

    json_path, markdown_path = write_report_exclusive(report, args.run_prefix)
    print(f"Comparison complete: {json_path}")
    print(f"Paired summary: {markdown_path}")


def _primary_evaluator(runner_args: list[str]) -> str:
    if "--evaluators" not in runner_args:
        return "exact_match"
    index = runner_args.index("--evaluators") + 1
    if index >= len(runner_args) or runner_args[index].startswith("--"):
        raise ValueError("--evaluators requires at least one evaluator")
    return runner_args[index]


def _all_evaluators(runner_args: list[str]) -> list[str]:
    """Extract all evaluator names from runner arguments."""
    if "--evaluators" not in runner_args:
        return ["exact_match"]
    index = runner_args.index("--evaluators") + 1
    evaluators: list[str] = []
    while index < len(runner_args) and not runner_args[index].startswith("--"):
        evaluators.append(runner_args[index])
        index += 1
    if not evaluators:
        raise ValueError("--evaluators requires at least one evaluator")
    return evaluators


if __name__ == "__main__":
    main()
