import pytest
from backend.utils.str_utils import remove_think_blocks


class TestStrUtils:
    """Test str_utils module functions"""

    def setup_method(self):
        """Setup before each test method"""
        self.remove_think_blocks = remove_think_blocks

    def test_remove_think_blocks_no_tags(self):
        """Text without any think tags remains unchanged"""
        text = "This is a normal text without any think tags."
        result = self.remove_think_blocks(text)
        assert result == text

    def test_remove_think_blocks_with_opening_tag_only(self):
        """Only opening tag: no closing tag -> no removal"""
        text = "This text has <think>some thinking content"
        result = self.remove_think_blocks(text)
        assert result == text  # unchanged

    def test_remove_think_blocks_with_closing_tag_only(self):
        """Only closing tag: no opening tag -> no removal"""
        text = ""
        result = self.remove_think_blocks(text)
        assert result == text  # unchanged

    def test_remove_think_blocks_with_both_tags(self):
        """Both tags present: remove the whole block including inner content"""
        text = "This text has <think>some thinking content</think> in it."
        result = self.remove_think_blocks(text)
        assert result == " in it."

    def test_remove_think_blocks_multiple_tags(self):
        """Multiple blocks should all be removed"""
        text = "<think>First thought</think> Normal text <think>Second thought</think>"
        result = self.remove_think_blocks(text)
        assert result == ""

    def test_remove_think_blocks_empty_string(self):
        """Empty string"""
        text = ""
        result = self.remove_think_blocks(text)
        assert result == ""

    def test_remove_think_blocks_only_tags(self):
        """Only tags with empty content"""
        text = "<think></think>"
        result = self.remove_think_blocks(text)
        assert result == ""

    def test_remove_think_blocks_partial_tags(self):
        """Partial/misspelled tags should not be touched"""
        text = "Text with <thin>partial tag</thin>"
        result = self.remove_think_blocks(text)
        assert result == text  # Should not be modified

    def test_remove_think_blocks_case_insensitive(self):
        """Uppercase/lowercase tags should be removed (case-insensitive)"""
        text = "Text with <THINK>uppercase</THINK> tags"
        result = self.remove_think_blocks(text)
        assert result == " tags"


if __name__ == "__main__":
    pytest.main()
