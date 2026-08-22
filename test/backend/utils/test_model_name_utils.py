import pytest
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from backend.utils.model_name_utils import split_repo_name, add_repo_to_name, split_display_name, sort_models_by_id

class TestModelNameUtils:
    """Test cases for model_name_utils.py"""

    def test_split_repo_name(self):
        """Test the split_repo_name function"""
        assert split_repo_name("THUDM/chatglm3-6b") == ("THUDM", "chatglm3-6b")
        assert split_repo_name("Pro/THUDM/GLM-4.1V-9B-Thinking") == ("Pro/THUDM", "GLM-4.1V-9B-Thinking")
        assert split_repo_name("chatglm3-6b") == ("", "chatglm3-6b")
        assert split_repo_name("") == ("", "")

    def test_add_repo_to_name(self, caplog):
        """Test the add_repo_to_name function"""
        assert add_repo_to_name("THUDM", "chatglm3-6b") == "THUDM/chatglm3-6b"
        assert add_repo_to_name("", "chatglm3-6b") == "chatglm3-6b"
        # Test case where model_name already contains a slash, should return model_name
        with caplog.at_level('WARNING'):
            result = add_repo_to_name("THUDM", "THUDM/chatglm3-6b")
            assert result == "THUDM/chatglm3-6b"
            assert "already contains repository information" in caplog.text

    def test_split_display_name(self):
        """Test the split_display_name function"""
        assert split_display_name("chatglm3-6b") == "chatglm3-6b"
        assert split_display_name("THUDM/chatglm3-6b") == "chatglm3-6b"
        assert split_display_name("Pro/THUDM/GLM-4.1V-9B-Thinking") == "Pro/GLM-4.1V-9B-Thinking"
        assert split_display_name("Pro/moonshotai/Kimi-K2-Instruct") == "Pro/Kimi-K2-Instruct"
        assert split_display_name("Pro/Qwen/Qwen2-7B-Instruct") == "Pro/Qwen2-7B-Instruct"
        assert split_display_name("A/B/C/D") == "A/D"
        assert split_display_name("") == ""

    def test_sort_models_by_id(self):
        """Test the sort_models_by_id function"""
        # Test case 1: Normal list of dictionaries with id field
        models = [
            {"id": "chatglm3-6b", "name": "ChatGLM3-6B"},
            {"id": "qwen2-7b", "name": "Qwen2-7B"},
            {"id": "baichuan2-7b", "name": "Baichuan2-7B"},
            {"id": "llama2-7b", "name": "Llama2-7B"}
        ]
        sorted_models = sort_models_by_id(models)
        expected_order = ["baichuan2-7b", "chatglm3-6b", "llama2-7b", "qwen2-7b"]
        actual_order = [model["id"] for model in sorted_models]
        assert actual_order == expected_order

        # Test case 2: List with mixed case IDs
        models_mixed_case = [
            {"id": "ChatGLM3-6B", "name": "ChatGLM3-6B"},
            {"id": "qwen2-7b", "name": "Qwen2-7B"},
            {"id": "Baichuan2-7B", "name": "Baichuan2-7B"},
            {"id": "llama2-7b", "name": "Llama2-7B"}
        ]
        sorted_mixed = sort_models_by_id(models_mixed_case)
        expected_mixed_order = ["Baichuan2-7B", "ChatGLM3-6B", "llama2-7b", "qwen2-7b"]
        actual_mixed_order = [model["id"] for model in sorted_mixed]
        assert actual_mixed_order == expected_mixed_order

        # Test case 3: List with empty or None IDs
        models_with_empty = [
            {"id": "", "name": "Empty Model"},
            {"id": "chatglm3-6b", "name": "ChatGLM3-6B"},
            {"id": None, "name": "None Model"},
            {"id": "qwen2-7b", "name": "Qwen2-7B"}
        ]
        sorted_empty = sort_models_by_id(models_with_empty)
        # Empty and None IDs should be sorted first (empty string)
        expected_empty_order = ["", None, "chatglm3-6b", "qwen2-7b"]
        actual_empty_order = [model["id"] for model in sorted_empty]
        assert actual_empty_order == expected_empty_order

        # Test case 4: Empty list
        empty_list = []
        sorted_empty_list = sort_models_by_id(empty_list)
        assert sorted_empty_list == []

        # Test case 5: Non-list input (should return as-is)
        non_list = "not a list"
        result = sort_models_by_id(non_list)
        assert result == non_list

        # Test case 6: List with non-dict items
        mixed_list = [
            {"id": "chatglm3-6b", "name": "ChatGLM3-6B"},
            "string_item",
            {"id": "qwen2-7b", "name": "Qwen2-7B"},
            123
        ]
        sorted_mixed = sort_models_by_id(mixed_list)
        # Should handle non-dict items gracefully
        assert len(sorted_mixed) == 4
