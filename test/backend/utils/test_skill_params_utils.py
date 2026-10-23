"""Unit tests for skill params helper functions."""

from backend.utils.skill_params_utils import split_string_inline_comment


def test_split_string_inline_comment_strips_display_and_comment():
    assert split_string_inline_comment("value  # tip ") == ("value", "tip")
    assert split_string_inline_comment("value #   ") == ("value", None)
