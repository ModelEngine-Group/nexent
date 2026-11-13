# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Numbered branch title formatting and collision boundaries."""

import pytest

from management.db.conversation.branch_titles import build_branch_title


@pytest.mark.parametrize(("source", "expected"), [
    ("先看一下这个代码", "先看一下这个代码 (2)"),
    ("Trip planning", "Trip planning (2)"),
    ("Trip planning (2)", "Trip planning (3)"),
    ("Trip planning (9)", "Trip planning (10)"),
    ("Trip planning（分支）", "Trip planning (2)"),
    ("Trip planning (2)（分支）", "Trip planning (3)"),
    ("  Trip planning  ", "Trip planning (2)"),
    (None, "(2)"),
    ("", "(2)"),
])
def test_branch_title_formats_source(source, expected):
    assert build_branch_title(source) == expected


def test_branch_title_skips_occupied_names_without_changing_input():
    occupied = ["Trip planning", "Trip planning (2)", "Trip planning (3)", None]
    assert build_branch_title("Trip planning", occupied) == "Trip planning (4)"
    assert build_branch_title("Trip planning (2)", occupied) == "Trip planning (4)"
    assert occupied[1] == "Trip planning (2)"


def test_branch_title_caps_length_and_rechecks_when_number_gains_a_digit():
    source = "很" * 120
    occupied = [f'{source[:96]} ({number})' for number in range(2, 10)]
    occupied.append(f'{source[:95]} (10)')
    title = build_branch_title(source, occupied)
    assert title == f'{source[:95]} (11)'
    assert len(title) == 100


def test_branch_title_keeps_non_numeric_parentheses_and_handles_huge_numbers():
    assert build_branch_title("Report (draft)") == "Report (draft) (2)"
    assert len(build_branch_title("(" + "9" * 100 + ")")) <= 100
