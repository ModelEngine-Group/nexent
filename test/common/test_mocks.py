"""
Common test utilities for mocking external dependencies.

This module provides shared mocking utilities to avoid code duplication
across test files that need to mock database, storage, and external service dependencies.
"""

import sys
import types
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any
from unittest.mock import MagicMock

import pytest


def _ensure_path(path: Path) -> None:
    """Ensure the given path is in sys.path."""
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _create_module(name: str, **attrs: Any) -> types.ModuleType:
    """Create a module with the given attributes."""
    module = types.ModuleType(name)
    for attr_name, attr_value in attrs.items():
        setattr(module, attr_name, attr_value)
    sys.modules[name] = module
    return module


@lru_cache(maxsize=1)
def bootstrap_test_env() -> Dict[str, Any]:
    """
    Bootstrap the test environment with common mocks and path setup.

    This is cached and should be used for tests that need a persistent
    environment setup across the test session.
    """
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parents[1]
    backend_dir = project_root / "backend"

    _ensure_path(project_root)
    _ensure_path(backend_dir)

    mock_const = MagicMock()
    consts_module = _create_module("consts", const=mock_const)
    sys.modules["consts.const"] = mock_const

    boto3_mock = MagicMock()
    sys.modules.setdefault("boto3", boto3_mock)

    client_module = _create_module(
        "backend.database.client",
        MinioClient=MagicMock(),
        PostgresClient=MagicMock(),
        db_client=MagicMock(),
        get_db_session=MagicMock(),
        as_dict=MagicMock(),
        minio_client=MagicMock(),
        postgres_client=MagicMock(),
    )
    sys.modules["database.client"] = client_module
    if "database" not in sys.modules:
        _create_module("database")

    config_utils_module = _create_module(
        "utils.config_utils",
        tenant_config_manager=MagicMock(),
        get_model_name_from_config=MagicMock(return_value=""),
    )

    nexent_module = _create_module("nexent", MessageObserver=MagicMock())
    _create_module("nexent.core")
    _create_module("nexent.core.models", OpenAIVLModel=MagicMock())

    return {
        "mock_const": mock_const,
        "consts_module": consts_module,
        "client_module": client_module,
        "config_utils_module": config_utils_module,
        "nexent_module": nexent_module,
        "boto3_mock": boto3_mock,
        "project_root": project_root,
        "backend_dir": backend_dir,
    }


def setup_common_mocks():
    """
    Setup common mocks for external dependencies used across multiple test files.

    This includes mocks for:
    - Database modules (database, database.db_models, etc.)
    - Storage modules (nexent.storage, boto3)
    - External libraries (sqlalchemy, psycopg2, jinja2)
    - Configuration modules (consts)

    Returns:
        Dict containing the main mock objects for use in tests
    """
    # Mock consts module with proper MODEL_CONFIG_MAPPING
    consts_mock = MagicMock()
    consts_mock.const = MagicMock()

    # Set up MODEL_CONFIG_MAPPING as a proper dict, not a MagicMock
    consts_mock.const.MODEL_CONFIG_MAPPING = {
        "llm": "LLM_ID",
        "embedding": "EMBEDDING_ID",
        "multiEmbedding": "MULTI_EMBEDDING_ID",
        "rerank": "RERANK_ID",
        "vlm": "VLM_ID",
        "stt": "STT_ID",
        "tts": "TTS_ID"
    }

    sys.modules['consts'] = consts_mock
    sys.modules['consts.const'] = consts_mock.const

    # Mock boto3
    boto3_mock = MagicMock()
    sys.modules['boto3'] = boto3_mock

    # Mock nexent modules
    nexent_mock = MagicMock()
    nexent_core_mock = MagicMock()
    nexent_core_models_mock = MagicMock()
    nexent_storage_mock = MagicMock()
    nexent_storage_factory_mock = MagicMock()
    storage_client_mock = MagicMock()

    # Configure storage factory mock
    nexent_storage_factory_mock.create_storage_client_from_config = MagicMock(
        return_value=storage_client_mock)
    nexent_storage_factory_mock.MinIOStorageConfig = MagicMock()
    nexent_storage_mock.storage_client_factory = nexent_storage_factory_mock

    # Set up nexent module hierarchy
    nexent_core_mock.models = nexent_core_models_mock
    nexent_mock.core = nexent_core_mock
    nexent_mock.storage = nexent_storage_mock

    # Register nexent modules
    sys.modules['nexent'] = nexent_mock
    sys.modules['nexent.core'] = nexent_core_mock
    sys.modules['nexent.core.models'] = nexent_core_models_mock
    sys.modules['nexent.core.models.openai_long_context_model'] = MagicMock()
    sys.modules['nexent.core.models.openai_vlm'] = MagicMock()
    sys.modules['nexent.storage'] = nexent_storage_mock
    sys.modules['nexent.storage.storage_client_factory'] = nexent_storage_factory_mock

    # Mock database modules
    db_mock = MagicMock()
    db_models_mock = MagicMock()
    db_models_mock.TableBase = MagicMock()
    db_model_management_mock = MagicMock()
    db_tenant_config_mock = MagicMock()

    sys.modules['database'] = db_mock
    sys.modules['database.db_models'] = db_models_mock
    sys.modules['database.model_management_db'] = db_model_management_mock
    sys.modules['database.tenant_config_db'] = db_tenant_config_mock
    sys.modules['backend.database.db_models'] = db_models_mock

    # Mock sqlalchemy with submodules
    sqlalchemy_mock = MagicMock()
    sqlalchemy_sql_mock = MagicMock()
    sqlalchemy_orm_mock = MagicMock()
    sqlalchemy_orm_class_mapper_mock = MagicMock()
    sqlalchemy_orm_sessionmaker_mock = MagicMock()

    sqlalchemy_mock.sql = sqlalchemy_sql_mock
    sqlalchemy_orm_mock.class_mapper = sqlalchemy_orm_class_mapper_mock
    sqlalchemy_orm_mock.sessionmaker = sqlalchemy_orm_sessionmaker_mock

    sys.modules['sqlalchemy'] = sqlalchemy_mock
    sys.modules['sqlalchemy.sql'] = sqlalchemy_sql_mock
    sys.modules['sqlalchemy.orm'] = sqlalchemy_orm_mock
    sys.modules['sqlalchemy.orm.class_mapper'] = sqlalchemy_orm_class_mapper_mock
    sys.modules['sqlalchemy.orm.sessionmaker'] = sqlalchemy_orm_sessionmaker_mock

    # Mock psycopg2
    sys.modules['psycopg2'] = MagicMock()
    sys.modules['psycopg2.extensions'] = MagicMock()

    # Mock jinja2
    sys.modules['jinja2'] = MagicMock()

    return {
        'consts_mock': consts_mock,
        'boto3_mock': boto3_mock,
        'nexent_mock': nexent_mock,
        'storage_client_mock': storage_client_mock,
        'db_mock': db_mock,
        'sqlalchemy_mock': sqlalchemy_mock,
    }


def patch_minio_client_initialization():
    """
    Context manager to patch MinIO client initialization during import.

    This should be used with 'with' statement before importing modules
    that initialize MinIO clients at module level.
    """
    from unittest.mock import patch
    from contextlib import contextmanager

    @contextmanager
    def _patch_minio():
        with patch('nexent.storage.storage_client_factory.create_storage_client_from_config'), \
                patch('nexent.storage.storage_client_factory.MinIOStorageConfig'):
            yield

    return _patch_minio()


# Global fixtures for common test constants
@pytest.fixture(scope="session")
def mock_constants():
    """
    Global fixture providing mock constants for Elasticsearch configuration.

    This fixture provides the standard mock values used across multiple test files
    and aligns with the environment variables set in conftest.py.
    """
    mock_const = MagicMock()
    mock_const.ES_HOST = "http://localhost:9200"
    mock_const.ES_API_KEY = "test-es-key"
    mock_const.ES_USERNAME = "elastic"
    mock_const.ES_PASSWORD = "test-password"
    return mock_const
