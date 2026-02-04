import pytest
from unittest.mock import mock_open

from utils.prompt_template_utils import get_agent_prompt_template, get_prompt_generate_prompt_template


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


if __name__ == '__main__':
    pytest.main()
