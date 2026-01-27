"""
Global test configuration for third-party component environment variables.

This file sets up environment variables for external services used in tests.
"""
import os


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
