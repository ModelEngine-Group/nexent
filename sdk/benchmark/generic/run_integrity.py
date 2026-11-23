#!/usr/bin/env python3
"""Post-run integrity checking for benchmark experiments.

Verifies that a completed benchmark run is complete and consistent by checking
linked traces, evaluator scores, trace outputs, and optional manifest parity.

Callable as a library function or as a CLI tool::

    # Library
    from run_integrity import check_run_integrity
    report = check_run_integrity(
        langfuse=lf,
        dataset_name="gsm8k-n10",
        run_name="gsm8k-agent7",
        expected_item_ids=["id1", "id2"],
        evaluator_names=["exact_match"],
    )
    print(report.summary())

    # CLI
    python run_integrity.py \\
        --dataset gsm8k-n10 \\
        --run-name gsm8k-agent7 \\
        --evaluators exact_match
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


try:
    from .run_context_manager_comparison import fetch_complete_dataset_run
except ImportError:
    from run_context_manager_comparison import fetch_complete_dataset_run


REQUIRED_OUTPUT_FIELDS = frozenset({
    "agent_config",
    "compression",
    "model_config",
    "provider_cache",
    "system_prompt",
})


@dataclass(frozen=True)
class IntegrityReport:
    """Immutable summary of a benchmark run's completeness and consistency."""

    run_name: str
    dataset_name: str
    run_complete: bool
    expected_item_count: int
    linked_trace_count: int
    unique_item_count: int
    missing_item_ids: list[str] = field(default_factory=list)
    duplicate_item_ids: list[str] = field(default_factory=list)
    missing_scores: dict[str, list[str]] = field(default_factory=dict)
    empty_outputs: list[str] = field(default_factory=list)
    trace_errors: list[str] = field(default_factory=list)
    config_mismatches: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the report."""
        return {
            "run_name": self.run_name,
            "dataset_name": self.dataset_name,
            "run_complete": self.run_complete,
            "expected_item_count": self.expected_item_count,
            "linked_trace_count": self.linked_trace_count,
            "unique_item_count": self.unique_item_count,
            "missing_item_ids": list(self.missing_item_ids),
            "duplicate_item_ids": list(self.duplicate_item_ids),
            "missing_scores": {
                key: list(value) for key, value in self.missing_scores.items()
            },
            "empty_outputs": list(self.empty_outputs),
            "trace_errors": list(self.trace_errors),
            "config_mismatches": list(self.config_mismatches),
        }

    def summary(self) -> str:
        """Return a human-readable integrity summary."""
        status = "COMPLETE" if self.run_complete else "INCOMPLETE"
        lines = [
            f"Integrity report for run '{self.run_name}' "
            f"(dataset: {self.dataset_name})",
            f"  Status: {status}",
            f"  Expected items: {self.expected_item_count}",
            f"  Linked traces: {self.linked_trace_count}",
            f"  Unique items: {self.unique_item_count}",
            f"  Missing items: {len(self.missing_item_ids)}",
            f"  Duplicate items: {len(self.duplicate_item_ids)}",
            f"  Missing scores: {len(self.missing_scores)}",
            f"  Empty outputs: {len(self.empty_outputs)}",
            f"  Trace errors: {len(self.trace_errors)}",
            f"  Config mismatches: {len(self.config_mismatches)}",
        ]
        if self.missing_item_ids:
            lines.append(
                f"  Missing item IDs: {', '.join(self.missing_item_ids)}"
            )
        if self.duplicate_item_ids:
            lines.append(
                f"  Duplicate item IDs: {', '.join(self.duplicate_item_ids)}"
            )
        if self.missing_scores:
            lines.append("  Missing scores:")
            for item_id, names in sorted(self.missing_scores.items()):
                lines.append(f"    {item_id}: {', '.join(names)}")
        if self.empty_outputs:
            lines.append(
                f"  Empty outputs: {', '.join(self.empty_outputs)}"
            )
        if self.trace_errors:
            lines.append(
                f"  Trace errors: {', '.join(self.trace_errors)}"
            )
        if self.config_mismatches:
            lines.append("  Config mismatches:")
            for mismatch in self.config_mismatches:
                lines.append(f"    {mismatch}")
        return "\n".join(lines)


def _parse_trace_output(raw_output: Any) -> dict[str, Any]:
    """Coerce a trace output into a dict, handling JSON strings and None."""
    if raw_output is None:
        return {}
    if isinstance(raw_output, dict):
        return raw_output
    if isinstance(raw_output, str):
        try:
            parsed = json.loads(raw_output)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def check_run_integrity(
    *,
    langfuse: Any,
    dataset_name: str,
    run_name: str,
    expected_item_ids: list[str],
    evaluator_names: list[str],
    manifest: dict[str, Any] | None = None,
) -> IntegrityReport:
    """Verify a completed benchmark run is complete and consistent.

    Checks linked trace counts, evaluator score coverage, trace output
    completeness, and optional manifest parity.

    Args:
        langfuse: Connected Langfuse client instance.
        dataset_name: Name of the Langfuse dataset.
        run_name: Name of the dataset run to verify.
        expected_item_ids: Dataset item IDs that should be present.
        evaluator_names: Evaluator score names expected on each trace.
        manifest: Optional resolved experiment manifest dict for parity checks.

    Returns:
        An IntegrityReport describing the run's completeness.
    """
    expected_set = set(expected_item_ids)

    # Fetch the run, falling back to a single read if eventual consistency
    # retries are exhausted.
    run = None
    try:
        run = fetch_complete_dataset_run(
            langfuse,
            dataset_name,
            run_name,
            expected_item_ids=expected_item_ids,
        )
    except (TimeoutError, Exception):
        try:
            run = langfuse.get_dataset_run(dataset_name, run_name)
        except Exception:
            run = None

    if run is None:
        return IntegrityReport(
            run_name=run_name,
            dataset_name=dataset_name,
            run_complete=False,
            expected_item_count=len(expected_item_ids),
            linked_trace_count=0,
            unique_item_count=0,
            missing_item_ids=sorted(expected_set),
        )

    run_items = run.dataset_run_items or []
    linked_trace_count = len(run_items)

    # Collect item IDs and detect duplicates.
    item_id_list = [str(ri.dataset_item_id) for ri in run_items]
    item_id_counts = Counter(item_id_list)
    linked_set = set(item_id_list)
    unique_item_count = len(linked_set)

    missing_item_ids = sorted(expected_set - linked_set)
    duplicate_item_ids = sorted(
        item_id for item_id, count in item_id_counts.items() if count > 1
    )

    # Inspect each trace for score coverage, output completeness, and errors.
    missing_scores: dict[str, list[str]] = {}
    empty_outputs: list[str] = []
    trace_errors: list[str] = []
    actual_score_names: set[str] = set()

    for run_item in run_items:
        item_id = str(run_item.dataset_item_id)
        trace = langfuse.get_trace(run_item.trace_id)

        # Score coverage.
        trace_score_names = {
            s.name for s in (trace.scores or []) if s.name is not None
        }
        actual_score_names.update(trace_score_names)
        missing_for_item = sorted(set(evaluator_names) - trace_score_names)
        if missing_for_item:
            missing_scores[item_id] = missing_for_item

        # Output completeness.
        output = _parse_trace_output(trace.output)
        if not output:
            empty_outputs.append(item_id)
            continue
        missing_fields = sorted(REQUIRED_OUTPUT_FIELDS - output.keys())
        if missing_fields:
            empty_outputs.append(item_id)

        # Trace errors.
        errors = output.get("errors")
        if isinstance(errors, list) and errors:
            trace_errors.append(item_id)

    empty_outputs.sort()
    trace_errors.sort()

    # Optional manifest parity checks.
    config_mismatches: list[str] = []
    if manifest is not None:
        manifest_item_ids = manifest.get("dataset_item_ids")
        if manifest_item_ids is not None:
            manifest_set = set(str(i) for i in manifest_item_ids)
            manifest_only = sorted(manifest_set - linked_set)
            linked_only = sorted(linked_set - manifest_set)
            if manifest_only:
                config_mismatches.append(
                    f"manifest dataset_item_ids not in run: "
                    f"{', '.join(manifest_only)}"
                )
            if linked_only:
                config_mismatches.append(
                    f"run items not in manifest dataset_item_ids: "
                    f"{', '.join(linked_only)}"
                )

        manifest_evaluators = manifest.get("evaluator_names")
        if manifest_evaluators is not None:
            manifest_eval_set = set(str(e) for e in manifest_evaluators)
            missing_from_traces = sorted(manifest_eval_set - actual_score_names)
            if missing_from_traces:
                config_mismatches.append(
                    f"manifest evaluator_names not found in trace scores: "
                    f"{', '.join(missing_from_traces)}"
                )

    run_complete = (
        not missing_item_ids
        and not duplicate_item_ids
        and not missing_scores
        and not empty_outputs
        and not trace_errors
        and not config_mismatches
    )

    return IntegrityReport(
        run_name=run_name,
        dataset_name=dataset_name,
        run_complete=run_complete,
        expected_item_count=len(expected_item_ids),
        linked_trace_count=linked_trace_count,
        unique_item_count=unique_item_count,
        missing_item_ids=missing_item_ids,
        duplicate_item_ids=duplicate_item_ids,
        missing_scores=missing_scores,
        empty_outputs=empty_outputs,
        trace_errors=trace_errors,
        config_mismatches=config_mismatches,
    )


def _parse_cli_args() -> argparse.Namespace:
    """Parse command-line arguments for standalone integrity checking."""
    parser = argparse.ArgumentParser(
        description="Verify a completed benchmark run is complete and consistent.",
    )
    parser.add_argument("--dataset", required=True, help="Langfuse dataset name")
    parser.add_argument("--run-name", required=True, help="Dataset run name")
    parser.add_argument(
        "--evaluators",
        required=True,
        nargs="+",
        help="Evaluator score names expected on each trace",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to a manifest JSON file for parity checks",
    )
    return parser.parse_args()


def main() -> None:
    """Run integrity checking from the command line."""
    from dotenv import load_dotenv

    load_dotenv()
    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")

    args = _parse_cli_args()

    from langfuse import Langfuse

    langfuse = Langfuse()
    if not langfuse.auth_check():
        print("ERROR: Langfuse authentication failed", file=sys.stderr)
        sys.exit(2)

    # Resolve expected item IDs from the dataset.
    dataset = langfuse.get_dataset(args.dataset)
    expected_item_ids = [str(item.id) for item in dataset.items]
    if not expected_item_ids:
        print(f"ERROR: Dataset '{args.dataset}' is empty", file=sys.stderr)
        sys.exit(2)

    manifest = None
    if args.manifest is not None:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    report = check_run_integrity(
        langfuse=langfuse,
        dataset_name=args.dataset,
        run_name=args.run_name,
        expected_item_ids=expected_item_ids,
        evaluator_names=args.evaluators,
        manifest=manifest,
    )
    print(report.summary())
    sys.exit(0 if report.run_complete else 1)


if __name__ == "__main__":
    main()
