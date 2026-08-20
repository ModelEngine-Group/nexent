from utils.text_length_utils import get_display_width, truncate_to_display_width


def test_display_width_counts_ascii_and_wide_characters():
    assert get_display_width("abc中！") == 7


def test_truncate_to_display_width_returns_short_values_unchanged():
    assert truncate_to_display_width("abc", 3) == "abc"


def test_truncate_to_display_width_preserves_character_boundaries_and_suffix():
    value = "中" * 501

    result = truncate_to_display_width(value, 1000, suffix="…")

    assert result == "中" * 499 + "…"
    assert get_display_width(result) <= 1000


def test_truncate_to_display_width_handles_ascii_prefix_with_suffix():
    result = truncate_to_display_width("a" * 10, 5, suffix="…")

    assert result == "a" * 4 + "…"
    assert get_display_width(result) == 5
