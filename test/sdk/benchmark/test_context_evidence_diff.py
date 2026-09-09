import sys

import pytest

from sdk.benchmark.generic.tools import context_evidence_diff
from sdk.benchmark.generic.tools.context_evidence_diff import (
    compare_context_evidence,
    first_paired_differences,
)


def test_compare_context_evidence_labels_semantic_changes():
    left = {
        "purpose": "step",
        "stable_prefix_fingerprint": "system-a",
        "tools_fingerprint": "tools-a",
        "messages_fingerprint": "messages-a",
        "system_messages_fingerprint": "system-a",
        "history_messages_fingerprint": "messages-a",
        "message_roles": ["system", "user"],
        "history_message_roles": ["user"],
        "current_summary_fingerprint": None,
        "observation_truncated": False,
    }
    right = {
        **left,
        "tools_fingerprint": "tools-b",
        "messages_fingerprint": "messages-b",
        "history_messages_fingerprint": "messages-b",
        "current_summary_fingerprint": "summary-b",
        "observation_truncated": True,
    }

    assert compare_context_evidence(left, right) == [
        "tool_schema_order_diff",
        "history_message_diff",
        "summary_replacement_diff",
        "observation_truncation_diff",
    ]


def test_first_paired_differences_returns_only_first_step_per_item_and_pair():
    common = {
        "item_id": "item-1",
        "purpose": "step",
        "stable_prefix_fingerprint": "system",
        "tools_fingerprint": "tools",
        "messages_fingerprint": "same",
        "system_messages_fingerprint": "system",
        "history_messages_fingerprint": "same",
    }
    groups = {
        "A": [
            {**common, "step_number": 1},
            {**common, "step_number": 2, "history_messages_fingerprint": "a-step-2"},
        ],
        "B": [
            {**common, "step_number": 1},
            {**common, "step_number": 2, "history_messages_fingerprint": "b-step-2"},
        ],
        "C": [
            {**common, "step_number": 1},
            {**common, "step_number": 2, "history_messages_fingerprint": "b-step-2"},
        ],
    }

    assert first_paired_differences(groups) == [
        {
            "item_id": "item-1",
            "left_group": "A",
            "right_group": "B",
            "step_number": 2,
            "purpose": "step",
            "differences": ["history_message_diff"],
        },
        {
            "item_id": "item-1",
            "left_group": "A",
            "right_group": "C",
            "step_number": 2,
            "purpose": "step",
            "differences": ["history_message_diff"],
        },
    ]


def test_context_evidence_diff_cli_reads_named_groups(
    monkeypatch,
    tmp_path,
    capsys,
):
    left_path = tmp_path / "left.json"
    right_path = tmp_path / "right.json"
    left_path.write_text("[]", encoding="utf-8")
    right_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "context_evidence_diff.py",
            "--group",
            f"P={left_path}",
            "--group",
            f"C={right_path}",
        ],
    )

    context_evidence_diff.main()

    assert capsys.readouterr().out.strip() == "[]"


def test_parse_group_rejects_missing_name_or_path():
    with pytest.raises(Exception, match="NAME=PATH"):
        context_evidence_diff._parse_group("invalid")
