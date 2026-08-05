"""Compare content-free FinalContext evidence across paired benchmark groups."""
from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path
from typing import Any


DIFF_FIELDS = {
    "system_message_diff": ("system_messages_fingerprint",),
    "tool_schema_order_diff": ("tools_fingerprint",),
    "history_message_diff": ("history_messages_fingerprint", "history_message_roles"),
    "summary_replacement_diff": (
        "previous_summary_fingerprint",
        "current_summary_fingerprint",
        "previous_summary_fallback",
        "current_summary_fallback",
    ),
    "observation_truncation_diff": ("observation_truncated",),
    "final_answer_prompt_diff": ("final_answer_prompt_fingerprint",),
}


def compare_context_evidence(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    """Return semantic difference labels for two aligned model inputs."""
    differences = [
        label
        for label, fields in DIFF_FIELDS.items()
        if any(left.get(field) != right.get(field) for field in fields)
    ]
    if left.get("purpose") != right.get("purpose"):
        differences.append("purpose_diff")
    return differences


def first_paired_differences(
    groups: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Find the first differing model input for every paired item and group pair."""
    indexed = {
        group: {
            (str(row["item_id"]), int(row["step_number"]), str(row.get("purpose", "step"))): row
            for row in rows
        }
        for group, rows in groups.items()
    }
    reports: list[dict[str, Any]] = []
    for left_group, right_group in combinations(groups, 2):
        left_rows = indexed[left_group]
        right_rows = indexed[right_group]
        item_ids = sorted(
            {key[0] for key in left_rows} & {key[0] for key in right_rows}
        )
        for item_id in item_ids:
            keys = sorted(
                {
                    key for key in {*left_rows, *right_rows}
                    if key[0] == item_id
                },
                key=lambda key: (key[1], key[2]),
            )
            for key in keys:
                if key not in left_rows or key not in right_rows:
                    reports.append({
                        "item_id": item_id,
                        "left_group": left_group,
                        "right_group": right_group,
                        "step_number": key[1],
                        "purpose": key[2],
                        "differences": ["model_call_presence_diff"],
                    })
                    break
                differences = compare_context_evidence(left_rows[key], right_rows[key])
                if differences:
                    reports.append({
                        "item_id": item_id,
                        "left_group": left_group,
                        "right_group": right_group,
                        "step_number": key[1],
                        "purpose": key[2],
                        "differences": differences,
                    })
                    break
    return reports


def _parse_group(value: str) -> tuple[str, Path]:
    name, separator, path = value.partition("=")
    if not separator or not name or not path:
        raise argparse.ArgumentTypeError("group must use NAME=PATH")
    return name, Path(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--group",
        action="append",
        required=True,
        type=_parse_group,
        help="Evidence JSON file as NAME=PATH; repeat for A/B/C",
    )
    args = parser.parse_args()
    groups = {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in args.group
    }
    print(json.dumps(first_paired_differences(groups), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
