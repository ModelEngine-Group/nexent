"""
Comprehensive unit tests for prompt_template_utils module in SDK.

Tests cover:
- get_prompt_template function with different template types
- Language support (zh, en)
- Error handling (unsupported template type, file not found)
- Path construction and file reading
- YAML parsing
"""

import pytest
import yaml
import os
from unittest.mock import patch, mock_open, MagicMock

# Import target module
from sdk.nexent.core.utils.prompt_template_utils import get_prompt_template


class TestGetPromptTemplate:
    """Test cases for get_prompt_template function"""

    @patch('builtins.open', new_callable=mock_open, read_data='system_prompt: "Test prompt"\nuser_prompt: "User prompt"')
    @patch('yaml.safe_load')
    def test_get_prompt_template_analyze_image_zh(self, mock_yaml_load, mock_file):
        """Test get_prompt_template for analyze_image template in Chinese"""
        mock_yaml_load.return_value = {"system_prompt": "Test prompt", "user_prompt": "User prompt"}

        result = get_prompt_template(template_type='analyze_image', language='zh')

        # Verify file was opened with correct path
        call_args = mock_file.call_args[0]
        assert 'prompts/analyze_image_zh.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'

        # Verify YAML was loaded
        mock_yaml_load.assert_called_once()

        # Verify result
        assert result == {"system_prompt": "Test prompt", "user_prompt": "User prompt"}

    @patch('builtins.open', new_callable=mock_open, read_data='system_prompt: "Test prompt"\nuser_prompt: "User prompt"')
    @patch('yaml.safe_load')
    def test_get_prompt_template_analyze_image_en(self, mock_yaml_load, mock_file):
        """Test get_prompt_template for analyze_image template in English"""
        mock_yaml_load.return_value = {"system_prompt": "Test prompt", "user_prompt": "User prompt"}

        result = get_prompt_template(template_type='analyze_image', language='en')

        # Verify file was opened with correct path
        call_args = mock_file.call_args[0]
        assert 'prompts/analyze_image_en.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'

        # Verify YAML was loaded
        mock_yaml_load.assert_called_once()

        # Verify result
        assert result == {"system_prompt": "Test prompt", "user_prompt": "User prompt"}

    @patch('builtins.open', new_callable=mock_open, read_data='system_prompt: "Test prompt"')
    @patch('yaml.safe_load')
    @patch('sdk.nexent.core.utils.prompt_template_utils.LANGUAGE', {'ZH': 'zh', 'EN': 'en'})
    def test_get_prompt_template_default_language_zh(self, mock_yaml_load, mock_file):
        """Test get_prompt_template with default language (should be Chinese)"""
        mock_yaml_load.return_value = {"system_prompt": "Test prompt"}

        # Test with default (should use LANGUAGE["ZH"] which is 'zh')
        result = get_prompt_template(template_type='analyze_image')

        # Verify file path contains Chinese template
        call_args = mock_file.call_args[0]
        assert 'prompts/analyze_image_zh.yaml' in call_args[0].replace('\\', '/')

        mock_yaml_load.assert_called_once()
        assert result == {"system_prompt": "Test prompt"}

    def test_get_prompt_template_unsupported_type(self):
        """Test get_prompt_template with unsupported template type"""
        with pytest.raises(ValueError) as excinfo:
            get_prompt_template(template_type='unsupported_type', language='zh')

        assert "Unsupported template type" in str(excinfo.value)
        assert "unsupported_type" in str(excinfo.value)

    @patch('builtins.open', new_callable=mock_open, read_data='system_prompt: "Test prompt"')
    @patch('yaml.safe_load')
    def test_get_prompt_template_with_kwargs(self, mock_yaml_load, mock_file):
        """Test get_prompt_template with additional kwargs (should be logged but not used)"""
        mock_yaml_load.return_value = {"system_prompt": "Test prompt"}

        with patch('sdk.nexent.core.utils.prompt_template_utils.logger') as mock_logger:
            result = get_prompt_template(template_type='analyze_image', language='en', extra_param='value')

            # Verify kwargs were logged
            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            assert any("extra_param" in str(call) or "kwargs" in str(call) for call in log_calls)

            # Verify function still works
            assert result == {"system_prompt": "Test prompt"}

    @patch('builtins.open', side_effect=FileNotFoundError("File not found"))
    def test_get_prompt_template_file_not_found(self, mock_file):
        """Test get_prompt_template when template file is not found"""
        with pytest.raises(FileNotFoundError) as excinfo:
            get_prompt_template(template_type='analyze_image', language='zh')

        assert "File not found" in str(excinfo.value)

    @patch('builtins.open', new_callable=mock_open, read_data='invalid: yaml: content: [')
    @patch('yaml.safe_load', side_effect=yaml.YAMLError("YAML parse error"))
    def test_get_prompt_template_yaml_error(self, mock_yaml_load, mock_file):
        """Test get_prompt_template when YAML parsing fails"""
        with pytest.raises(yaml.YAMLError) as excinfo:
            get_prompt_template(template_type='analyze_image', language='zh')

        assert "YAML parse error" in str(excinfo.value)

    @patch('builtins.open', new_callable=mock_open, read_data='system_prompt: "Test prompt"')
    @patch('yaml.safe_load')
    @patch('sdk.nexent.core.utils.prompt_template_utils.logger')
    def test_get_prompt_template_logging(self, mock_logger, mock_yaml_load, mock_file):
        """Test that get_prompt_template logs correctly"""
        mock_yaml_load.return_value = {"system_prompt": "Test prompt"}

        get_prompt_template(template_type='analyze_image', language='en')

        # Verify logger was called
        mock_logger.info.assert_called_once()
        log_call = str(mock_logger.info.call_args)
        assert "analyze_image" in log_call
        assert "en" in log_call

    @patch('builtins.open', new_callable=mock_open, read_data='system_prompt: "Test prompt"')
    @patch('yaml.safe_load')
    def test_get_prompt_template_path_construction(self, mock_yaml_load, mock_file):
        """Test that path is constructed correctly"""
        mock_yaml_load.return_value = {"system_prompt": "Test prompt"}

        get_prompt_template(template_type='analyze_image', language='en')

        # Verify path construction
        call_args = mock_file.call_args[0]
        file_path = call_args[0]

        # Path should be absolute
        assert os.path.isabs(file_path) or file_path.startswith('/')

        # Path should contain the expected template file
        assert 'analyze_image_en.yaml' in file_path

    @patch('builtins.open', new_callable=mock_open, read_data='system_prompt: "Test prompt"\nuser_prompt: "User prompt"\nother_field: "Other"')
    @patch('yaml.safe_load')
    def test_get_prompt_template_complex_yaml(self, mock_yaml_load, mock_file):
        """Test get_prompt_template with complex YAML structure"""
        complex_yaml = {
            "system_prompt": "Test prompt",
            "user_prompt": "User prompt",
            "other_field": "Other",
            "nested": {
                "field": "value"
            }
        }
        mock_yaml_load.return_value = complex_yaml

        result = get_prompt_template(template_type='analyze_image', language='en')

        assert result == complex_yaml
        assert "nested" in result
        assert result["nested"]["field"] == "value"

    @patch('builtins.open', new_callable=mock_open, read_data='')
    @patch('yaml.safe_load', return_value=None)
    def test_get_prompt_template_empty_file(self, mock_yaml_load, mock_file):
        """Test get_prompt_template with empty YAML file"""
        result = get_prompt_template(template_type='analyze_image', language='zh')

        assert result is None
        mock_yaml_load.assert_called_once()

    @patch('builtins.open', new_callable=mock_open, read_data='system_prompt: "Test prompt"')
    @patch('yaml.safe_load')
    def test_get_prompt_template_encoding_utf8(self, mock_yaml_load, mock_file):
        """Test that file is opened with UTF-8 encoding"""
        mock_yaml_load.return_value = {"system_prompt": "Test prompt"}

        get_prompt_template(template_type='analyze_image', language='zh')

        # Verify encoding parameter
        call_kwargs = mock_file.call_args[1]
        assert call_kwargs['encoding'] == 'utf-8'

    @patch('builtins.open', new_callable=mock_open, read_data='system_prompt: "Test prompt"')
    @patch('yaml.safe_load')
    def test_get_prompt_template_path_resolution(self, mock_yaml_load, mock_file):
        """Test that path resolution works correctly"""
        mock_yaml_load.return_value = {"system_prompt": "Test prompt"}

        get_prompt_template(template_type='analyze_image', language='en')

        # Verify file was opened (path resolution happened)
        assert mock_file.called
        call_args = mock_file.call_args[0]
        # Path should be absolute or contain the expected template file
        assert 'analyze_image_en.yaml' in call_args[0]