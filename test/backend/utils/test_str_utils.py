import pytest
from backend.utils.str_utils import remove_think_blocks, convert_list_to_string


class TestStrUtils:
    """Test str_utils module functions"""

    def test_remove_think_blocks_no_tags(self):
        """Text without any think tags remains unchanged"""
        text = "This is a normal text without any think tags."
        result = remove_think_blocks(text)
        assert result == text

    def test_remove_think_blocks_with_opening_tag_only(self):
        """Only opening tag: no closing tag -> no removal"""
        text = "This text has <think>some thinking content"
        result = remove_think_blocks(text)
        assert result == text  # unchanged

    def test_remove_think_blocks_with_closing_tag_only(self):
        """Only closing tag: no opening tag -> no removal"""
        text = ""
        result = remove_think_blocks(text)
        assert result == text  # unchanged

    def test_remove_think_blocks_with_both_tags(self):
        """Both tags present: remove the whole block including inner content"""
        text = "This text has <think>some thinking content</think> in it."
        result = remove_think_blocks(text)
        assert result == " in it."

    def test_remove_think_blocks_multiple_tags(self):
        """Multiple blocks should all be removed"""
        text = "<think>First thought</think> Normal text <think>Second thought</think>"
        result = remove_think_blocks(text)
        assert result == ""

    def test_remove_think_blocks_empty_string(self):
        """Empty string"""
        text = ""
        result = remove_think_blocks(text)
        assert result == ""

    def test_remove_think_blocks_only_tags(self):
        """Only tags with empty content"""
        text = "<think></think>"
        result = remove_think_blocks(text)
        assert result == ""

    def test_remove_think_blocks_partial_tags(self):
        """Partial/misspelled tags should not be touched"""
        text = "Text with <thin>partial tag</thin>"
        result = remove_think_blocks(text)
        assert result == text  # Should not be modified

    def test_remove_think_blocks_case_insensitive(self):
        """Uppercase/lowercase tags should be removed (case-insensitive)"""
        text = "Text with <THINK>uppercase</THINK> tags"
        result = remove_think_blocks(text)
        assert result == " tags"

    def test_convert_list_to_string_none_input(self):
        """None input should return empty string"""
        result = convert_list_to_string(None)
        assert result == ""

    def test_convert_list_to_string_empty_list(self):
        """Empty list should return empty string"""
        result = convert_list_to_string([])
        assert result == ""

    def test_convert_list_to_string_single_item(self):
        """Single item list should return single item as string"""
        result = convert_list_to_string([42])
        assert result == "42"

    def test_convert_list_to_string_multiple_items(self):
        """Multiple items should be joined with commas"""
        result = convert_list_to_string([1, 2, 3])
        assert result == "1,2,3"

    def test_convert_list_to_string_mixed_types(self):
        """List with mixed integer types should work correctly"""
        result = convert_list_to_string([1, 2, 3, 10])
        assert result == "1,2,3,10"

    def test_convert_list_to_string_zero_and_negative(self):
        """Zero and negative numbers should be handled correctly"""
        result = convert_list_to_string([0, -1, 5])
        assert result == "0,-1,5"


if __name__ == "__main__":
    pytest.main()
