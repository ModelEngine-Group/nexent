#!/usr/bin/env python3
"""Repeat only failed items from a completed Langfuse benchmark run."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


try:
    from .common.benchmark_paths import ARTIFACT_ROOT
    from .provenance.experiment_manifest import manifest_path
    from .run_context_manager_comparison import (
        fetch_complete_dataset_run,
        fetch_run_results,
    )
except ImportError:
    from common.benchmark_paths import ARTIFACT_ROOT
    from provenance.experiment_manifest import manifest_path
    from run_context_manager_comparison import (
        fetch_complete_dataset_run,
        fetch_run_results,
    )


GENERIC_DIR = Path(__file__).resolve().parent
REPO_ROOT = GENERIC_DIR.parents[2]
CONTROLLED_RUNNER_ARGS = {
    "--dataset",
    "--run-name",
    "--item-id",
    "--item-limit",
    "--evaluators",
}


def baseline_failed_item_ids(
    *,
    langfuse: Any,
    dataset_name: str,
    run_name: str,
    evaluator_name: str,
) -> list[str]:
    """Return failed IDs in dataset order and reject missing baseline scores."""
    dataset = langfuse.get_dataset(dataset_name)
    dataset_order = [str(item.id) for item in dataset.items]
    run = fetch_complete_dataset_run(
        langfuse,
        dataset_name,
        run_name,
        expected_item_ids=None,
    )
    score_by_item: dict[str, float] = {}
    missing_scores: list[str] = []
    for run_item in run.dataset_run_items:
        item_id = str(run_item.dataset_item_id)
        trace = langfuse.get_trace(run_item.trace_id)
        score = next(
            (
                candidate
                for candidate in (trace.scores or [])
                if candidate.name == evaluator_name
            ),
            None,
        )
        if score is None:
            missing_scores.append(item_id)
            continue
        score_by_item[item_id] = float(score.value)
    if missing_scores:
        raise RuntimeError(
            f"Baseline run '{run_name}' is missing evaluator "
            f"'{evaluator_name}' for: {', '.join(sorted(missing_scores))}"
        )
    if not score_by_item:
        raise RuntimeError(
            f"Baseline run '{run_name}' has no '{evaluator_name}' scores"
        )
    ordered = [item_id for item_id in dataset_order if item_id in score_by_item]
    return [item_id for item_id in ordered if score_by_item[item_id] < 1.0]


def build_repeat_command(
    *,
    python_executable: Path,
    dataset_name: str,
    run_name: str,
    item_ids: list[str],
    primary_evaluator: str,
    runner_args: list[str],
) -> list[str]:
    """Build one isolated run containing only baseline failures."""
    command = [
        str(python_executable),
        str(GENERIC_DIR / "run_benchmark.py"),
        "--dataset",
        dataset_name,
        "--run-name",
        run_name,
        "--evaluators",
        primary_evaluator,
    ]
    if primary_evaluator == "gaia_exact_match":
        command.append("gaia_final_answer")
    for item_id in item_ids:
        command.extend(["--item-id", item_id])
    command.extend(runner_args)
    return command


def aggregate_repeat_results(
    item_ids: list[str],
    repeat_results: list[dict[str, bool]],
) -> dict[str, Any]:
    """Aggregate repeat stability without hiding per-item variance."""
    if any(set(result) != set(item_ids) for result in repeat_results):
        raise ValueError("Repeat results do not contain the exact targeted item set")
    repeat_count = len(repeat_results)
    items = []
    for item_id in item_ids:
        pass_count = sum(result[item_id] for result in repeat_results)
        items.append({
            "item_id": item_id,
            "pass_count": pass_count,
            "attempt_count": repeat_count,
            "pass_rate": round(pass_count / repeat_count, 4) if repeat_count else None,
            "outcomes": [
                "pass" if result[item_id] else "fail"
                for result in repeat_results
            ],
        })
    return {
        "target_item_count": len(item_ids),
        "repeat_count": repeat_count,
        "total_passes": sum(item["pass_count"] for item in items),
        "total_attempts": len(item_ids) * repeat_count,
        "items": items,
    }


def write_report_exclusive(report: dict[str, Any], prefix: str) -> tuple[Path, Path]:
    """Write immutable JSON and Markdown targeted-repeat reports."""
    output_dir = ARTIFACT_ROOT / "targeted_repeats"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_prefix = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in prefix
    )
    json_path = output_dir / f"{safe_prefix}.targeted-repeat.json"
    markdown_path = output_dir / f"{safe_prefix}.targeted-repeat.md"
    with json_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    lines = [
        f"# Failed-item repeats: {prefix}",
        "",
        f"- Baseline run: `{report['baseline_run']}`",
        f"- Evaluator: `{report['primary_evaluator']}`",
        f"- Targeted failures: `{report['aggregate']['target_item_count']}`",
        f"- Repeats: `{report['aggregate']['repeat_count']}`",
        "",
        "| Item ID | Passes | Attempts | Pass rate | Outcomes |",
        "|---|---:|---:|---:|---|",
    ]
    for item in report["aggregate"]["items"]:
        lines.append(
            f"| `{item['item_id']}` | {item['pass_count']} "
            f"| {item['attempt_count']} | {item['pass_rate']:.1%} "
            f"| {', '.join(item['outcomes'])} |"
        )
    with markdown_path.open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return json_path, markdown_path


def _validate_runner_args(runner_args: list[str]) -> None:
    for argument in runner_args:
        option = argument.split("=", 1)[0]
        if option in CONTROLLED_RUNNER_ARGS:
            raise ValueError(
                f"{option} is controlled by the failed-item repeat runner"
            )


def _assert_no_collisions(langfuse, dataset_name: str, run_names: list[str]) -> None:
    local = [
        run_name
        for run_name in run_names
        if manifest_path(ARTIFACT_ROOT / "manifests", run_name).exists()
    ]
    if local:
        raise FileExistsError(
            "Refusing to overwrite local run manifests: " + ", ".join(local)
        )
    remote = []
    for run_name in run_names:
        try:
            langfuse.get_dataset_run(dataset_name, run_name)
        except Exception as error:
            if getattr(error, "status_code", None) == 404:
                continue
            raise
        remote.append(run_name)
    if remote:
        raise FileExistsError(
            "Refusing to reuse Langfuse runs: " + ", ".join(remote)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--baseline-run", required=True)
    parser.add_argument("--run-prefix", required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--primary-evaluator", default="gaia_exact_match")
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python executable for run_benchmark.py",
    )
    parser.add_argument(
        "--runner-args",
        nargs=argparse.REMAINDER,
        default=[],
        help="Arguments forwarded to run_benchmark.py",
    )
    args = parser.parse_args()
    if args.repeat <= 0:
        parser.error("--repeat must be greater than 0")
    if args.max_items is not None and args.max_items <= 0:
        parser.error("--max-items must be greater than 0")
    _validate_runner_args(args.runner_args)

    load_dotenv()
    load_dotenv(REPO_ROOT / ".env")
    from langfuse import Langfuse

    langfuse = Langfuse()
    if not langfuse.auth_check():
        raise RuntimeError("Langfuse authentication failed")
    item_ids = baseline_failed_item_ids(
        langfuse=langfuse,
        dataset_name=args.dataset,
        run_name=args.baseline_run,
        evaluator_name=args.primary_evaluator,
    )
    if args.max_items is not None:
        item_ids = item_ids[:args.max_items]
    if not item_ids:
        print("Baseline has no failed items; no repeat runs are needed.")
        return

    run_names = [
        f"{args.run_prefix}-r{index:02d}"
        for index in range(1, args.repeat + 1)
    ]
    _assert_no_collisions(langfuse, args.dataset, run_names)
    repeat_results = []
    for run_name in run_names:
        command = build_repeat_command(
            python_executable=args.python,
            dataset_name=args.dataset,
            run_name=run_name,
            item_ids=item_ids,
            primary_evaluator=args.primary_evaluator,
            runner_args=args.runner_args,
        )
        print(f"Running targeted repeat: {run_name} ({len(item_ids)} items)")
        subprocess.run(command, cwd=REPO_ROOT, check=True)
        repeat_results.append(
            fetch_run_results(
                langfuse,
                args.dataset,
                run_name,
                args.primary_evaluator,
                expected_item_ids=item_ids,
            )
        )

    report = {
        "schema_version": 1,
        "dataset": args.dataset,
        "baseline_run": args.baseline_run,
        "primary_evaluator": args.primary_evaluator,
        "run_names": run_names,
        "target_item_ids": item_ids,
        "aggregate": aggregate_repeat_results(item_ids, repeat_results),
    }
    json_path, markdown_path = write_report_exclusive(report, args.run_prefix)
    print(f"Targeted repeat report: {json_path}")
    print(f"Targeted repeat summary: {markdown_path}")


if __name__ == "__main__":
    main()
