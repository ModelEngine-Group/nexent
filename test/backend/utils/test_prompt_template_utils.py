import pytest
from unittest.mock import mock_open

from utils.prompt_template_utils import (
    get_agent_prompt_template,
    get_prompt_generate_prompt_template,
    get_generate_title_prompt_template,
    get_document_summary_prompt_template,
    get_cluster_summary_reduce_prompt_template,
    get_skill_creation_simple_prompt_template,
    get_prompt_template,
)


class TestPromptTemplateUtils:
    """Test cases for prompt_template_utils module"""

    def test_get_agent_prompt_template_manager_zh(self, mocker):
        """Test get_agent_prompt_template for manager mode in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"test": "data"}'))

        mock_yaml_load.return_value = {"test": "data"}
        result = get_agent_prompt_template(is_manager=True, language='zh')

        # Verify the function was called with correct parameters
        # The actual path will be an absolute path, so we check that it contains the expected relative path
        call_args = mock_file.call_args[0]
        assert 'backend/prompts/manager_system_prompt_template_zh.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"test": "data"}

    def test_get_agent_prompt_template_manager_en(self, mocker):
        """Test get_agent_prompt_template for manager mode in English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"test": "data"}'))

        mock_yaml_load.return_value = {"test": "data"}
        result = get_agent_prompt_template(is_manager=True, language='en')

        # Verify the function was called with correct parameters
        # The actual path will be an absolute path, so we check that it ends with the expected relative path
        call_args = mock_file.call_args[0]
        assert 'backend/prompts/manager_system_prompt_template_en.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"test": "data"}

    def test_get_agent_prompt_template_managed_zh(self, mocker):
        """Test get_agent_prompt_template for managed mode in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"test": "data"}'))

        mock_yaml_load.return_value = {"test": "data"}
        result = get_agent_prompt_template(is_manager=False, language='zh')

        # Verify the function was called with correct parameters
        # The actual path will be an absolute path, so we check that it ends with the expected relative path
        call_args = mock_file.call_args[0]
        assert 'backend/prompts/managed_system_prompt_template_zh.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"test": "data"}

    def test_get_agent_prompt_template_managed_en(self, mocker):
        """Test get_agent_prompt_template for managed mode in English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"test": "data"}'))

        mock_yaml_load.return_value = {"test": "data"}
        result = get_agent_prompt_template(is_manager=False, language='en')

        # Verify the function was called with correct parameters
        # The actual path will be an absolute path, so we check that it ends with the expected relative path
        call_args = mock_file.call_args[0]
        assert 'backend/prompts/managed_system_prompt_template_en.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"test": "data"}

    def test_get_prompt_generate_prompt_template_zh(self, mocker):
        """Test get_prompt_generate_prompt_template for Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"test": "data"}'))

        mock_yaml_load.return_value = {"test": "data"}
        result = get_prompt_generate_prompt_template(language='zh')

        # Verify the function was called with correct parameters
        # The actual path will be an absolute path, so we check that it ends with the expected relative path
        call_args = mock_file.call_args[0]
        assert 'backend/prompts/utils/prompt_generate_zh.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"test": "data"}

    def test_get_prompt_generate_prompt_template_en(self, mocker):
        """Test get_prompt_generate_prompt_template for English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"test": "data"}'))

        mock_yaml_load.return_value = {"test": "data"}
        result = get_prompt_generate_prompt_template(language='en')

        # Verify the function was called with correct parameters
        # The actual path will be an absolute path, so we check that it ends with the expected relative path
        call_args = mock_file.call_args[0]
        assert 'backend/prompts/utils/prompt_generate_en.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"test": "data"}

    def test_get_prompt_generate_prompt_template_default_language(self, mocker):
        """Test get_prompt_generate_prompt_template with default language (should be Chinese)"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"test": "data"}'))

        mock_yaml_load.return_value = {"test": "data"}
        result = get_prompt_generate_prompt_template()

        # Verify the function was called with correct parameters
        # The actual path will be an absolute path, so we check that it ends with the expected relative path
        call_args = mock_file.call_args[0]
        assert 'backend/prompts/utils/prompt_generate_zh.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"test": "data"}


class TestGetPromptTemplate:
    """Test cases for get_prompt_template function"""

    def test_get_prompt_template_unsupported_type(self, mocker):
        """Test get_prompt_template with unsupported template type raises ValueError"""
        with pytest.raises(ValueError) as excinfo:
            get_prompt_template(template_type='unsupported_type', language='zh')

        assert "Unsupported template type" in str(excinfo.value)

    def test_get_prompt_template_file_not_found(self, mocker):
        """Test get_prompt_template raises FileNotFoundError when file is missing"""
        mocker.patch('builtins.open', side_effect=FileNotFoundError("File not found"))

        with pytest.raises(FileNotFoundError):
            get_prompt_template(template_type='prompt_generate', language='zh')

    def test_get_prompt_template_prompt_generate_zh(self, mocker):
        """Test get_prompt_template for prompt_generate in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system: "test"'))

        mock_yaml_load.return_value = {"system": "test"}
        result = get_prompt_template(template_type='prompt_generate', language='zh')

        call_args = mock_file.call_args[0]
        assert 'utils/prompt_generate_zh.yaml' in call_args[0].replace('\\', '/')
        mock_yaml_load.assert_called_once()
        assert result == {"system": "test"}

    def test_get_prompt_template_prompt_generate_en(self, mocker):
        """Test get_prompt_template for prompt_generate in English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system: "test"'))

        mock_yaml_load.return_value = {"system": "test"}
        result = get_prompt_template(template_type='prompt_generate', language='en')

        call_args = mock_file.call_args[0]
        assert 'utils/prompt_generate_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"system": "test"}

    def test_get_prompt_template_agent_manager_zh(self, mocker):
        """Test get_prompt_template for agent with is_manager=True in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system: "manager"'))

        mock_yaml_load.return_value = {"system": "manager"}
        result = get_prompt_template(template_type='agent', language='zh', is_manager=True)

        call_args = mock_file.call_args[0]
        assert 'manager_system_prompt_template_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"system": "manager"}

    def test_get_prompt_template_agent_managed_zh(self, mocker):
        """Test get_prompt_template for agent with is_manager=False in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system: "managed"'))

        mock_yaml_load.return_value = {"system": "managed"}
        result = get_prompt_template(template_type='agent', language='zh', is_manager=False)

        call_args = mock_file.call_args[0]
        assert 'managed_system_prompt_template_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"system": "managed"}

    def test_get_prompt_template_generate_title_zh(self, mocker):
        """Test get_prompt_template for generate_title in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='title: "test"'))

        mock_yaml_load.return_value = {"title": "test"}
        result = get_prompt_template(template_type='generate_title', language='zh')

        call_args = mock_file.call_args[0]
        assert 'utils/generate_title_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"title": "test"}

    def test_get_prompt_template_generate_title_en(self, mocker):
        """Test get_prompt_template for generate_title in English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='title: "test"'))

        mock_yaml_load.return_value = {"title": "test"}
        result = get_prompt_template(template_type='generate_title', language='en')

        call_args = mock_file.call_args[0]
        assert 'utils/generate_title_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"title": "test"}

    def test_get_prompt_template_document_summary_zh(self, mocker):
        """Test get_prompt_template for document_summary in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='summary: "test"'))

        mock_yaml_load.return_value = {"summary": "test"}
        result = get_prompt_template(template_type='document_summary', language='zh')

        call_args = mock_file.call_args[0]
        assert 'document_summary_agent_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"summary": "test"}

    def test_get_prompt_template_document_summary_en(self, mocker):
        """Test get_prompt_template for document_summary in English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='summary: "test"'))

        mock_yaml_load.return_value = {"summary": "test"}
        result = get_prompt_template(template_type='document_summary', language='en')

        call_args = mock_file.call_args[0]
        assert 'document_summary_agent_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"summary": "test"}

    def test_get_prompt_template_cluster_summary_reduce_zh(self, mocker):
        """Test get_prompt_template for cluster_summary_reduce in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='reduce: "test"'))

        mock_yaml_load.return_value = {"reduce": "test"}
        result = get_prompt_template(template_type='cluster_summary_reduce', language='zh')

        call_args = mock_file.call_args[0]
        assert 'cluster_summary_reduce_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"reduce": "test"}

    def test_get_prompt_template_cluster_summary_reduce_en(self, mocker):
        """Test get_prompt_template for cluster_summary_reduce in English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='reduce: "test"'))

        mock_yaml_load.return_value = {"reduce": "test"}
        result = get_prompt_template(template_type='cluster_summary_reduce', language='en')

        call_args = mock_file.call_args[0]
        assert 'cluster_summary_reduce_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"reduce": "test"}


class TestWrapperFunctions:
    """Test cases for wrapper functions"""

    def test_get_generate_title_prompt_template_zh(self, mocker):
        """Test get_generate_title_prompt_template for Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"title": "test"}'))

        mock_yaml_load.return_value = {"title": "test"}
        result = get_generate_title_prompt_template(language='zh')

        call_args = mock_file.call_args[0]
        assert 'utils/generate_title_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"title": "test"}

    def test_get_generate_title_prompt_template_en(self, mocker):
        """Test get_generate_title_prompt_template for English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"title": "test"}'))

        mock_yaml_load.return_value = {"title": "test"}
        result = get_generate_title_prompt_template(language='en')

        call_args = mock_file.call_args[0]
        assert 'utils/generate_title_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"title": "test"}

    def test_get_generate_title_prompt_template_default(self, mocker):
        """Test get_generate_title_prompt_template with default language"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"title": "test"}'))

        mock_yaml_load.return_value = {"title": "test"}
        result = get_generate_title_prompt_template()

        call_args = mock_file.call_args[0]
        assert 'utils/generate_title_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"title": "test"}

    def test_get_document_summary_prompt_template_zh(self, mocker):
        """Test get_document_summary_prompt_template for Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"summary": "test"}'))

        mock_yaml_load.return_value = {"summary": "test"}
        result = get_document_summary_prompt_template(language='zh')

        call_args = mock_file.call_args[0]
        assert 'document_summary_agent_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"summary": "test"}

    def test_get_document_summary_prompt_template_en(self, mocker):
        """Test get_document_summary_prompt_template for English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"summary": "test"}'))

        mock_yaml_load.return_value = {"summary": "test"}
        result = get_document_summary_prompt_template(language='en')

        call_args = mock_file.call_args[0]
        assert 'document_summary_agent_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"summary": "test"}

    def test_get_document_summary_prompt_template_default(self, mocker):
        """Test get_document_summary_prompt_template with default language"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"summary": "test"}'))

        mock_yaml_load.return_value = {"summary": "test"}
        result = get_document_summary_prompt_template()

        call_args = mock_file.call_args[0]
        assert 'document_summary_agent_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"summary": "test"}

    def test_get_cluster_summary_reduce_prompt_template_zh(self, mocker):
        """Test get_cluster_summary_reduce_prompt_template for Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"reduce": "test"}'))

        mock_yaml_load.return_value = {"reduce": "test"}
        result = get_cluster_summary_reduce_prompt_template(language='zh')

        call_args = mock_file.call_args[0]
        assert 'cluster_summary_reduce_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"reduce": "test"}

    def test_get_cluster_summary_reduce_prompt_template_en(self, mocker):
        """Test get_cluster_summary_reduce_prompt_template for English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"reduce": "test"}'))

        mock_yaml_load.return_value = {"reduce": "test"}
        result = get_cluster_summary_reduce_prompt_template(language='en')

        call_args = mock_file.call_args[0]
        assert 'cluster_summary_reduce_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"reduce": "test"}

    def test_get_cluster_summary_reduce_prompt_template_default(self, mocker):
        """Test get_cluster_summary_reduce_prompt_template with default language"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"reduce": "test"}'))

        mock_yaml_load.return_value = {"reduce": "test"}
        result = get_cluster_summary_reduce_prompt_template()

        call_args = mock_file.call_args[0]
        assert 'cluster_summary_reduce_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"reduce": "test"}


class TestSkillCreationSimplePromptTemplate:
    """Test cases for get_skill_creation_simple_prompt_template function"""

    def test_get_skill_creation_simple_prompt_template_zh(self, mocker):
        """Test get_skill_creation_simple_prompt_template for Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system_prompt: "sys"\nuser_prompt: "user"'))

        mock_yaml_load.return_value = {"system_prompt": "sys", "user_prompt": "user"}
        result = get_skill_creation_simple_prompt_template(language='zh')

        call_args = mock_file.call_args[0]
        assert 'skill_creation_simple_zh.yaml' in call_args[0].replace('\\', '/')
        mock_yaml_load.assert_called_once()
        assert result == {"system_prompt": "sys", "user_prompt": "user"}

    def test_get_skill_creation_simple_prompt_template_en(self, mocker):
        """Test get_skill_creation_simple_prompt_template for English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system_prompt: "sys"\nuser_prompt: "user"'))

        mock_yaml_load.return_value = {"system_prompt": "sys", "user_prompt": "user"}
        result = get_skill_creation_simple_prompt_template(language='en')

        call_args = mock_file.call_args[0]
        assert 'skill_creation_simple_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"system_prompt": "sys", "user_prompt": "user"}

    def test_get_skill_creation_simple_prompt_template_default(self, mocker):
        """Test get_skill_creation_simple_prompt_template with default language"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system_prompt: "sys"\nuser_prompt: "user"'))

        mock_yaml_load.return_value = {"system_prompt": "sys", "user_prompt": "user"}
        result = get_skill_creation_simple_prompt_template()

        call_args = mock_file.call_args[0]
        assert 'skill_creation_simple_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"system_prompt": "sys", "user_prompt": "user"}

    def test_get_skill_creation_simple_prompt_template_fallback(self, mocker):
        """Test get_skill_creation_simple_prompt_template falls back to Chinese for unknown language"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system_prompt: "sys"\nuser_prompt: "user"'))

        mock_yaml_load.return_value = {"system_prompt": "sys", "user_prompt": "user"}
        result = get_skill_creation_simple_prompt_template(language='unknown')

        call_args = mock_file.call_args[0]
        assert 'skill_creation_simple_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"system_prompt": "sys", "user_prompt": "user"}

    def test_get_skill_creation_simple_prompt_template_missing_keys(self, mocker):
        """Test get_skill_creation_simple_prompt_template handles missing keys in YAML"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='other: "data"'))

        mock_yaml_load.return_value = {"other": "data"}
        result = get_skill_creation_simple_prompt_template(language='zh')

        # Missing keys should default to empty strings
        assert result == {"system_prompt": "", "user_prompt": ""}

    def test_get_skill_creation_simple_prompt_template_file_not_found(self, mocker):
        """Test get_skill_creation_simple_prompt_template raises FileNotFoundError when file is missing"""
        mocker.patch('builtins.open', side_effect=FileNotFoundError("File not found"))

        with pytest.raises(FileNotFoundError):
            get_skill_creation_simple_prompt_template(language='zh')
