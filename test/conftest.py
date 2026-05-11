"""
Global test configuration for third-party component environment variables.

This file sets up environment variables for external services used in tests.
"""
import os
import sys
from unittest.mock import MagicMock

# Stub out mem0 modules before anything else imports them.
# The sdk imports mem0 at module level, so stubs must be registered first.
_mem0_stubs = {
    "mem0": MagicMock(),
    "mem0.memory": MagicMock(),
    "mem0.memory.main": MagicMock(),
    "mem0.embeddings": MagicMock(),
    "mem0.embeddings.base": MagicMock(),
    "mem0.configs": MagicMock(),
    "mem0.configs.embeddings": MagicMock(),
    "mem0.configs.embeddings.base": MagicMock(),
}
for _mod_name in _mem0_stubs:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = _mem0_stubs[_mod_name]

# Add backend and sdk directories to sys.path so that modules can be imported
# as `from backend.xxx import ...` and `from sdk.xxx import ...`
_test_root = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.abspath(os.path.join(_test_root, "..", "backend"))
_sdk_dir = os.path.abspath(os.path.join(_test_root, "..", "sdk"))

if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
if _sdk_dir not in sys.path:
    sys.path.insert(0, _sdk_dir)

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
