"""
Unit tests for attachment_utils.py
Tests the convert_image_to_text and convert_long_text_to_text functions
"""


import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from io import BytesIO

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..')))

# Patch environment variables before any imports that might use them
os.environ.setdefault('MINIO_ENDPOINT', 'http://localhost:9000')
os.environ.setdefault('MINIO_ACCESS_KEY', 'minioadmin')
os.environ.setdefault('MINIO_SECRET_KEY', 'minioadmin')
os.environ.setdefault('MINIO_REGION', 'us-east-1')
os.environ.setdefault('MINIO_DEFAULT_BUCKET', 'test-bucket')

# Mock external dependencies
sys.modules['boto3'] = MagicMock()
sys.modules['botocore'] = MagicMock()
sys.modules['botocore.client'] = MagicMock()
sys.modules['botocore.exceptions'] = MagicMock()
sys.modules['nexent'] = MagicMock()
sys.modules['nexent.core'] = MagicMock()
sys.modules['nexent.core.models'] = MagicMock()
sys.modules['nexent.core.models.openai_vlm'] = MagicMock()
sys.modules['nexent.core.models.openai_long_context_model'] = MagicMock()

# Mock MessageObserver
class MockMessageObserver:
    def __init__(self, *args, **kwargs):
        pass

sys.modules['nexent.core'].MessageObserver = MockMessageObserver

# Mock OpenAIVLModel
class MockOpenAIVLModel:
    def __init__(self, *args, **kwargs):
        pass

    def analyze_image(self, *args, **kwargs):
        return MagicMock(content="Mocked image analysis")

sys.modules['nexent.core.models.openai_vlm'].OpenAIVLModel = MockOpenAIVLModel

# Mock OpenAILongContextModel
class MockOpenAILongContextModel:
    def __init__(self, *args, **kwargs):
        pass

    def analyze_long_text(self, *args, **kwargs):
        return (MagicMock(content="Mocked text analysis"), "0")

sys.modules['nexent.core.models.openai_long_context_model'].OpenAILongContextModel = MockOpenAILongContextModel

sys.modules['utils'] = MagicMock()
sys.modules['utils.config_utils'] = MagicMock()
sys.modules['utils.prompt_template_utils'] = MagicMock()

# Mock consts module before any imports that might use it
# This is critical because backend.database.client imports from consts.const
# Create a simple object to hold const values instead of MagicMock to ensure dictionary access works
class ConstModule:
    MINIO_ENDPOINT = os.environ.get('MINIO_ENDPOINT', 'http://localhost:9000')
    MINIO_ACCESS_KEY = os.environ.get('MINIO_ACCESS_KEY', 'minioadmin')
    MINIO_SECRET_KEY = os.environ.get('MINIO_SECRET_KEY', 'minioadmin')
    MINIO_REGION = os.environ.get('MINIO_REGION', 'us-east-1')
    MINIO_DEFAULT_BUCKET = os.environ.get('MINIO_DEFAULT_BUCKET', 'test-bucket')
    POSTGRES_HOST = "localhost"
    POSTGRES_USER = "test_user"
    NEXENT_POSTGRES_PASSWORD = "test_password"
    POSTGRES_DB = "test_db"
    POSTGRES_PORT = 5432
    # MODEL_CONFIG_MAPPING and LANGUAGE for attachment_utils
    MODEL_CONFIG_MAPPING = {
        "llm": "LLM_ID",
        "embedding": "EMBEDDING_ID",
        "multiEmbedding": "MULTI_EMBEDDING_ID",
        "rerank": "RERANK_ID",
        "vlm": "VLM_ID",
        "stt": "STT_ID",
        "tts": "TTS_ID"
    }
    LANGUAGE = {
        "ZH": "zh",
        "EN": "en"
    }

consts_mock = MagicMock()
consts_mock.const = ConstModule()
sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = ConstModule()

# Mock database modules
sys.modules['database'] = MagicMock()
sys.modules['database.client'] = MagicMock()
sys.modules['database.model_management_db'] = MagicMock()

# Mock db_models module before any imports that might trigger backend.database.client
# This is critical because backend.database.client imports database.db_models
db_models_mock = MagicMock()
db_models_mock.TableBase = MagicMock()
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

# Mock nexent.storage modules before any imports that might trigger backend.database.client
# This is critical because backend.database.client imports from nexent.storage.storage_client_factory
nexent_mock = MagicMock()
nexent_storage_mock = MagicMock()
nexent_storage_factory_mock = MagicMock()
nexent_storage_factory_mock.create_storage_client_from_config = MagicMock()
nexent_storage_factory_mock.MinIOStorageConfig = MagicMock()
nexent_storage_mock.storage_client_factory = nexent_storage_factory_mock
nexent_storage_mock.minio_config = MagicMock()
nexent_storage_mock.minio_config.MinIOStorageConfig = MagicMock()
nexent_mock.storage = nexent_storage_mock
sys.modules['nexent'] = nexent_mock
sys.modules['nexent.storage'] = nexent_storage_mock
sys.modules['nexent.storage.storage_client_factory'] = nexent_storage_factory_mock
sys.modules['nexent.storage.minio_config'] = nexent_storage_mock.minio_config

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
minio_client_mock._ensure_bucket_exists = MagicMock()
minio_client_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()
patch('database.client.MinioClient', return_value=minio_client_mock).start()
patch('backend.database.client.minio_client', minio_client_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Import the functions to test
from backend.utils.attachment_utils import (
    convert_image_to_text,
    convert_long_text_to_text
)

class TestConvertImageToText:
    """Test cases for convert_image_to_text function"""

    @patch('backend.utils.attachment_utils.tenant_config_manager')
    @patch('backend.utils.attachment_utils.get_model_name_from_config')
    @patch('backend.utils.attachment_utils.get_analyze_file_prompt_template')
    @patch('backend.utils.attachment_utils.OpenAIVLModel')
    def test_convert_image_to_text_success(self, mock_vlm_model, mock_get_prompts, mock_get_model_name, mock_config_manager):
        """Test successful image to text conversion"""
        # Setup mocks
        mock_config = {"base_url": "http://test.com", "api_key": "test_key"}
        mock_config_manager.get_model_config.return_value = mock_config
        mock_get_model_name.return_value = "gpt-4-vision"
        mock_get_prompts.return_value = {
            'image_analysis': {
                'system_prompt': 'Analyze this image: {{query}}'
            }
        }

        mock_model_instance = MagicMock()
        mock_model_instance.analyze_image.return_value = MagicMock(
            content="Image description")
        mock_vlm_model.return_value = mock_model_instance

        # Execute
        result = convert_image_to_text(
            "What's in this image?", "test.jpg", "tenant123")

        # Assertions
        assert result == "Image description"
        mock_config_manager.get_model_config.assert_called_once_with(
            key="VLM_ID", tenant_id="tenant123")
        mock_vlm_model.assert_called_once()
        mock_model_instance.analyze_image.assert_called_once()

    @patch('backend.utils.attachment_utils.tenant_config_manager')
    def test_convert_image_to_text_no_config(self, mock_config_manager):
        """Test image conversion with no model configuration"""
        # Setup mocks
        mock_config_manager.get_model_config.return_value = None

        # Execute and assert exception
        with pytest.raises(Exception):
            convert_image_to_text("What's in this image?",
                                  "test.jpg", "tenant123")

    @patch('backend.utils.attachment_utils.tenant_config_manager')
    @patch('backend.utils.attachment_utils.get_model_name_from_config')
    @patch('backend.utils.attachment_utils.get_analyze_file_prompt_template')
    @patch('backend.utils.attachment_utils.OpenAIVLModel')
    def test_convert_image_to_text_binary_input(self, mock_vlm_model, mock_get_prompts, mock_get_model_name, mock_config_manager):
        """Test image conversion with binary input"""
        # Setup mocks
        mock_config = {"base_url": "http://test.com", "api_key": "test_key"}
        mock_config_manager.get_model_config.return_value = mock_config
        mock_get_model_name.return_value = "gpt-4-vision"
        mock_get_prompts.return_value = {
            'image_analysis': {
                'system_prompt': 'Analyze this image: {{query}}'
            }
        }

        mock_model_instance = MagicMock()
        mock_model_instance.analyze_image.return_value = MagicMock(
            content="Binary image description")
        mock_vlm_model.return_value = mock_model_instance

        # Execute with binary input
        binary_data = BytesIO(b"fake image data")
        result = convert_image_to_text(
            "What's in this image?", binary_data, "tenant123")

        # Assertions
        assert result == "Binary image description"
        mock_model_instance.analyze_image.assert_called_once()


class TestConvertLongTextToText:
    """Test cases for convert_long_text_to_text function"""

    @patch('backend.utils.attachment_utils.tenant_config_manager')
    @patch('backend.utils.attachment_utils.get_model_name_from_config')
    @patch('backend.utils.attachment_utils.get_analyze_file_prompt_template')
    @patch('backend.utils.attachment_utils.OpenAILongContextModel')
    def test_convert_long_text_to_text_success(self, mock_long_context_model, mock_get_prompts, mock_get_model_name, mock_config_manager):
        """Test successful long text to text conversion"""
        # Setup mocks
        mock_config = {"base_url": "http://test.com",
                       "api_key": "test_key", "max_tokens": 4000}
        mock_config_manager.get_model_config.return_value = mock_config
        mock_get_model_name.return_value = "gpt-4"
        mock_get_prompts.return_value = {
            'long_text_analysis': {
                'system_prompt': 'Analyze this text: {{query}}',
                'user_prompt': 'Please summarize'
            }
        }

        mock_model_instance = MagicMock()
        mock_model_instance.analyze_long_text.return_value = (
            MagicMock(content="Summarized text"), "0")
        mock_long_context_model.return_value = mock_model_instance

        # Execute
        result, truncation = convert_long_text_to_text(
            "Summarize this", "Long text content", "tenant123")

        # Assertions
        assert result == "Summarized text"
        assert truncation == "0"
        mock_config_manager.get_model_config.assert_called_once_with(
            key="LLM_ID", tenant_id="tenant123")
        mock_long_context_model.assert_called_once()
        mock_model_instance.analyze_long_text.assert_called_once()

    @patch('backend.utils.attachment_utils.tenant_config_manager')
    @patch('backend.utils.attachment_utils.get_model_name_from_config')
    @patch('backend.utils.attachment_utils.get_analyze_file_prompt_template')
    @patch('backend.utils.attachment_utils.OpenAILongContextModel')
    def test_convert_long_text_to_text_with_truncation(self, mock_long_context_model, mock_get_prompts, mock_get_model_name, mock_config_manager):
        """Test long text conversion with truncation"""
        # Setup mocks
        mock_config = {"base_url": "http://test.com",
                       "api_key": "test_key", "max_tokens": 4000}
        mock_config_manager.get_model_config.return_value = mock_config
        mock_get_model_name.return_value = "gpt-4"
        mock_get_prompts.return_value = {
            'long_text_analysis': {
                'system_prompt': 'Analyze this text: {{query}}',
                'user_prompt': 'Please summarize'
            }
        }

        mock_model_instance = MagicMock()
        mock_model_instance.analyze_long_text.return_value = (
            MagicMock(content="Truncated summary"), "50")
        mock_long_context_model.return_value = mock_model_instance

        # Execute
        result, truncation = convert_long_text_to_text(
            "Summarize this", "Very long text content", "tenant123")

        # Assertions
        assert result == "Truncated summary"
        assert truncation == "50"

    @patch('backend.utils.attachment_utils.tenant_config_manager')
    def test_convert_long_text_to_text_no_config(self, mock_config_manager):
        """Test long text conversion with no model configuration"""
        # Setup mocks
        mock_config_manager.get_model_config.return_value = None

        # Execute and assert exception
        with pytest.raises(Exception):
            convert_long_text_to_text(
                "Summarize this", "Long text content", "tenant123")

    @patch('backend.utils.attachment_utils.tenant_config_manager')
    @patch('backend.utils.attachment_utils.get_model_name_from_config')
    @patch('backend.utils.attachment_utils.get_analyze_file_prompt_template')
    @patch('backend.utils.attachment_utils.OpenAILongContextModel')
    def test_convert_long_text_to_text_different_language(self, mock_long_context_model, mock_get_prompts, mock_get_model_name, mock_config_manager):
        """Test long text conversion with different language"""
        # Setup mocks
        mock_config = {"base_url": "http://test.com",
                       "api_key": "test_key", "max_tokens": 4000}
        mock_config_manager.get_model_config.return_value = mock_config
        mock_get_model_name.return_value = "gpt-4"
        mock_get_prompts.return_value = {
            'long_text_analysis': {
                'system_prompt': 'Analyze this text: {{query}}',
                'user_prompt': 'Please summarize'
            }
        }

        mock_model_instance = MagicMock()
        mock_model_instance.analyze_long_text.return_value = (
            MagicMock(content="English summary"), "0")
        mock_long_context_model.return_value = mock_model_instance

        # Execute with English language
        result, truncation = convert_long_text_to_text(
            "Summarize this", "Long text content", "tenant123", "en")

        # Assertions
        assert result == "English summary"
        assert truncation == "0"
        mock_get_prompts.assert_called_once_with("en")


class TestErrorHandling:
    """Test cases for error handling scenarios"""

    @patch('backend.utils.attachment_utils.tenant_config_manager')
    @patch('backend.utils.attachment_utils.get_model_name_from_config')
    @patch('backend.utils.attachment_utils.get_analyze_file_prompt_template')
    @patch('backend.utils.attachment_utils.OpenAIVLModel')
    def test_convert_image_to_text_model_exception(self, mock_vlm_model, mock_get_prompts, mock_get_model_name, mock_config_manager):
        """Test image conversion with model exception"""
        # Setup mocks
        mock_config = {"base_url": "http://test.com", "api_key": "test_key"}
        mock_config_manager.get_model_config.return_value = mock_config
        mock_get_model_name.return_value = "gpt-4-vision"
        mock_get_prompts.return_value = {
            'image_analysis': {
                'system_prompt': 'Analyze this image: {{query}}'
            }
        }

        mock_model_instance = MagicMock()
        mock_model_instance.analyze_image.side_effect = Exception(
            "Model error")
        mock_vlm_model.return_value = mock_model_instance

        # Execute and assert exception
        with pytest.raises(Exception) as exc_info:
            convert_image_to_text("What's in this image?",
                                  "test.jpg", "tenant123")

        assert "Model error" in str(exc_info.value)

    @patch('backend.utils.attachment_utils.tenant_config_manager')
    @patch('backend.utils.attachment_utils.get_model_name_from_config')
    @patch('backend.utils.attachment_utils.get_analyze_file_prompt_template')
    @patch('backend.utils.attachment_utils.OpenAILongContextModel')
    def test_convert_long_text_to_text_model_exception(self, mock_long_context_model, mock_get_prompts, mock_get_model_name, mock_config_manager):
        """Test long text conversion with model exception"""
        # Setup mocks
        mock_config = {"base_url": "http://test.com",
                       "api_key": "test_key", "max_tokens": 4000}
        mock_config_manager.get_model_config.return_value = mock_config
        mock_get_model_name.return_value = "gpt-4"
        mock_get_prompts.return_value = {
            'long_text_analysis': {
                'system_prompt': 'Analyze this text: {{query}}',
                'user_prompt': 'Please summarize'
            }
        }

        mock_model_instance = MagicMock()
        mock_model_instance.analyze_long_text.side_effect = Exception(
            "Model error")
        mock_long_context_model.return_value = mock_model_instance

        # Execute and assert exception
        with pytest.raises(Exception) as exc_info:
            convert_long_text_to_text(
                "Summarize this", "Long text content", "tenant123")

        assert "Model error" in str(exc_info.value)
