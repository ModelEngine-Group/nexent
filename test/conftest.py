"""
Global test configuration and common fixtures for all tests.

This file provides shared mocks and fixtures to reduce duplication across test files.
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Set up environment variables commonly needed for tests
os.environ.setdefault('MINIO_ENDPOINT', 'http://localhost:9000')
os.environ.setdefault('MINIO_ACCESS_KEY', 'minioadmin')
os.environ.setdefault('MINIO_SECRET_KEY', 'minioadmin')
os.environ.setdefault('MINIO_REGION', 'us-east-1')
os.environ.setdefault('MINIO_DEFAULT_BUCKET', 'test-bucket')
os.environ.setdefault('ELASTICSEARCH_HOST', 'http://localhost:9200')
os.environ.setdefault('ELASTICSEARCH_API_KEY', 'test-key')
os.environ.setdefault('ELASTICSEARCH_USERNAME', 'elastic')
os.environ.setdefault('ELASTICSEARCH_PASSWORD', 'test-password')
os.environ.setdefault('POSTGRES_HOST', 'localhost')
os.environ.setdefault('POSTGRES_USER', 'test_user')
os.environ.setdefault('POSTGRES_PASSWORD', 'test_password')
os.environ.setdefault('POSTGRES_DB', 'test_db')
os.environ.setdefault('POSTGRES_PORT', '5432')

# Set up Python path
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
backend_dir = project_root / "backend"

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Mock external libraries at module level before any imports
boto3_mock = MagicMock()
psycopg2_mock = MagicMock()
supabase_mock = MagicMock()

# Mock dotenv to prevent file access issues
dotenv_mock = MagicMock()
sys.modules['dotenv'] = dotenv_mock
sys.modules['dotenv.main'] = dotenv_mock.main = MagicMock()

sys.modules['boto3'] = boto3_mock
sys.modules['psycopg2'] = psycopg2_mock
sys.modules['supabase'] = supabase_mock

# Mock other common external dependencies
nexent_mock = MagicMock()
sys.modules['nexent'] = nexent_mock
sys.modules['nexent.core'] = nexent_mock.core = MagicMock()
sys.modules['nexent.core.models'] = nexent_mock.core.models = MagicMock()
sys.modules['nexent.core.models.openai_vlm'] = nexent_mock.core.models.openai_vlm = MagicMock()
sys.modules['nexent.core.models.openai_long_context_model'] = nexent_mock.core.models.openai_long_context_model = MagicMock()
sys.modules['nexent.memory'] = MagicMock()
sys.modules['nexent.memory.memory_service'] = MagicMock()
sys.modules['nexent.storage.storage_client_factory'] = MagicMock()
sys.modules['nexent.storage.minio_config'] = MagicMock()

# Mock nexent.core classes


class MockMessageObserver:
    def __init__(self, *args, **kwargs):
        pass


class MockOpenAIVLModel:
    def __init__(self, *args, **kwargs):
        pass

    def analyze_image(self, *args, **kwargs):
        return MagicMock(content="Mocked image analysis")


class MockOpenAILongContextModel:
    def __init__(self, *args, **kwargs):
        pass

    def analyze_long_text(self, *args, **kwargs):
        return (MagicMock(content="Mocked text analysis"), "0")


nexent_mock.core.MessageObserver = MockMessageObserver
nexent_mock.core.models.openai_vlm.OpenAIVLModel = MockOpenAIVLModel
nexent_mock.core.models.openai_long_context_model.OpenAILongContextModel = MockOpenAILongContextModel

# Mock services module
sys.modules['services'] = MagicMock()
sys.modules['services.invitation_service'] = MagicMock()
sys.modules['services.group_service'] = MagicMock()

# Note: database module is not mocked at sys.modules level to avoid import conflicts
# Individual components are mocked via patch decorators instead

# Common logger mock
logger_mock = MagicMock()


@pytest.fixture(scope="session", autouse=True)
def global_mocks():
    """
    Global mocks that are applied to all tests.

    This fixture runs once per test session and patches common external dependencies
    that should be mocked across all tests.
    """
    # Mock AWS/MinIO calls
    with patch('botocore.client.BaseClient._make_api_call', return_value={}):

        # Mock Elasticsearch
        with patch('elasticsearch.Elasticsearch', return_value=MagicMock()):

            # Mock storage factory and MinIO config validation
            storage_client_mock = MagicMock()
            minio_client_mock = MagicMock()
            minio_client_mock._ensure_bucket_exists = MagicMock()
            minio_client_mock.client = MagicMock()

            minio_config_mock = MagicMock()
            minio_config_mock.validate = MagicMock()

            with patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
                       return_value=storage_client_mock), \
                    patch('nexent.storage.minio_config.MinIOStorageConfig',
                          return_value=minio_config_mock), \
                    patch('backend.database.client.MinioClient',
                          return_value=minio_client_mock), \
                    patch('database.client.MinioClient', return_value=minio_client_mock), \
                    patch('backend.database.client.minio_client', minio_client_mock):

                yield {
                    'boto3': boto3_mock,
                    'psycopg2': psycopg2_mock,
                    'supabase': supabase_mock,
                    'storage_client': storage_client_mock,
                    'minio_client': minio_client_mock,
                    'minio_config': minio_config_mock,
                    'logger': logger_mock
                }


@pytest.fixture
def mock_logger():
    """Common logger mock for tests that need logging."""
    return logger_mock


@pytest.fixture
def mock_constants():
    """Mock constants object with common test values."""
    mock_const = MagicMock()
    mock_const.ES_HOST = "http://localhost:9200"
    mock_const.ES_API_KEY = "test-es-key"
    mock_const.ES_USERNAME = "elastic"
    mock_const.ES_PASSWORD = "test-password"
    return mock_const


@pytest.fixture
def mock_tenant_config_manager():
    """Mock tenant config manager for tests."""
    mock_manager = MagicMock()
    # Ensure certain methods/attributes don't exist to match real behavior
    del mock_manager._get_cache_key  # This method was removed
    del mock_manager.clear_cache  # This method was removed
    return mock_manager


@pytest.fixture
def mock_database_client():
    """Mock database client for tests."""
    mock_client = MagicMock()
    mock_client.MinioClient = MagicMock()
    mock_client.PostgresClient = MagicMock()
    mock_client.db_client = MagicMock()
    mock_client.get_db_session = MagicMock()
    mock_client.as_dict = MagicMock()
    mock_client.minio_client = MagicMock()
    mock_client.postgres_client = MagicMock()
    return mock_client


@pytest.fixture
def mock_model_configs():
    """Common mock model configurations for testing."""
    return {
        'llm_config': {
            "model_name": "gpt-4",
            "model_repo": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "test-llm-key"
        },
        'embedding_config': {
            "model_name": "text-embedding-ada-002",
            "model_repo": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "test-embed-key",
            "max_tokens": 1536
        }
    }
