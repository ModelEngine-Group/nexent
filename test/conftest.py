"""
Global test configuration for third-party component environment variables.

This file sets up environment variables for external services used in tests.
"""
import sys
from unittest.mock import MagicMock
import os


# Mock mem0 before any imports to avoid import errors
mem0_mock = MagicMock()
sys.modules['mem0'] = mem0_mock
sys.modules['mem0.memory'] = MagicMock()
sys.modules['mem0.memory.main'] = MagicMock()
sys.modules['mem0.embeddings'] = MagicMock()
sys.modules['mem0.embeddings.base'] = MagicMock()
sys.modules['mem0.embeddings.base'].EmbeddingBase = MagicMock
sys.modules['mem0.configs'] = MagicMock()
sys.modules['mem0.configs.embeddings'] = MagicMock()
sys.modules['mem0.configs.embeddings.base'] = MagicMock()
sys.modules['mem0.configs.embeddings.base'].BaseEmbedderConfig = MagicMock

# Mock nexent.core.models.embedding_model if it causes issues
sys.modules['nexent'] = MagicMock()
sys.modules['nexent.core'] = MagicMock()
sys.modules['nexent.core.models'] = MagicMock()
sys.modules['nexent.core.models.embedding_model'] = MagicMock()

# Mock boto3 for storage
sys.modules['boto3'] = MagicMock()
sys.modules['botocore'] = MagicMock()
sys.modules['botocore.client'] = MagicMock()
sys.modules['botocore.exceptions'] = MagicMock()
sys.modules['botocore.config'] = MagicMock()

# Note: smolagents is installed in the environment, no need to mock it


# MinIO Configuration
os.environ.setdefault('MINIO_ENDPOINT', 'http://localhost:9000')
os.environ.setdefault('MINIO_ACCESS_KEY', 'minioadmin')
os.environ.setdefault('MINIO_SECRET_KEY', 'minioadmin')
os.environ.setdefault('MINIO_REGION', 'us-east-1')
os.environ.setdefault('MINIO_DEFAULT_BUCKET', 'test-bucket')

# Elasticsearch Configuration
os.environ.setdefault('ELASTICSEARCH_HOST', 'http://localhost:9200')
os.environ.setdefault('ELASTICSEARCH_API_KEY', 'test-es-key')
os.environ.setdefault('ELASTIC_PASSWORD', 'test-password')

# PostgresSQL Configuration
os.environ.setdefault('POSTGRES_HOST', 'localhost')
os.environ.setdefault('POSTGRES_USER', 'test_user')
os.environ.setdefault('POSTGRES_PASSWORD', 'test_password')
os.environ.setdefault('POSTGRES_DB', 'test_db')
os.environ.setdefault('POSTGRES_PORT', '5432')
