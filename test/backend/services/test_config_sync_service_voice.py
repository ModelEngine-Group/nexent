"""
Unit tests for config_sync_service STT model config saving.
These tests cover the STT specific fields in save_config_impl.
"""
import importlib
import sys
import types
import importlib
from unittest.mock import patch, MagicMock

import pytest

# Patch boto3 and other dependencies before importing anything from backend
boto3_module = types.ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules['boto3'] = boto3_module

# Apply critical patches before importing any modules
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
minio_client_mock._ensure_bucket_exists = MagicMock()
minio_client_mock.client = MagicMock()
minio_config_mock = MagicMock()
minio_config_mock.validate = MagicMock()

if 'consts.const' in sys.modules and not hasattr(sys.modules['consts.const'], 'APP_DESCRIPTION'):
    sys.modules.pop('consts.const', None)
if 'consts' in sys.modules and not hasattr(sys.modules['consts'], '__path__'):
    sys.modules.pop('consts', None)

database_client_module = types.ModuleType('database.client')
database_client_module.MinioClient = MagicMock()
database_client_module.minio_client = minio_client_mock
database_client_module.as_dict = MagicMock(side_effect=lambda value: value)
database_client_module.db_client = MagicMock()
database_client_module.db_client.clean_string_values = MagicMock(side_effect=lambda value: value)
database_client_module.get_db_session = MagicMock()
sys.modules['database.client'] = database_client_module
database_package = sys.modules.get('database') or importlib.import_module('database')
setattr(database_package, 'client', database_client_module)
database_model_management_module = types.ModuleType('database.model_management_db')
database_model_management_module.get_model_by_model_id = MagicMock()
database_model_management_module.get_model_id_by_display_name = MagicMock()
database_model_management_module.get_model_records = MagicMock(return_value=[])
sys.modules['database.model_management_db'] = database_model_management_module
setattr(database_package, 'model_management_db', database_model_management_module)
backend_database_client_module = sys.modules.get('backend.database.client')
if backend_database_client_module is not None and not hasattr(backend_database_client_module, 'minio_client'):
    backend_database_client_module.minio_client = minio_client_mock

patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
      return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig',
      return_value=minio_config_mock).start()
patch('backend.database.client.MinioClient',
      return_value=minio_client_mock).start()
patch('database.client.MinioClient', return_value=minio_client_mock).start()
patch('backend.database.client.minio_client', minio_client_mock, create=True).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

# Import backend modules after all patches are applied
with patch('backend.database.client.MinioClient', return_value=minio_client_mock), \
        patch('nexent.storage.minio_config.MinIOStorageConfig', return_value=minio_config_mock):
    from backend.services.config_sync_service import (
        save_config_impl,
        build_model_config,
    )


@pytest.fixture
def service_mocks():
    """Create mocks for service layer dependencies."""
    with patch('backend.services.config_sync_service.tenant_config_manager') as mock_tenant_config_manager, \
            patch('backend.services.config_sync_service.get_env_key') as mock_get_env_key, \
            patch('backend.services.config_sync_service.safe_value') as mock_safe_value, \
            patch('backend.services.config_sync_service.get_model_records') as mock_get_model_records, \
            patch('backend.services.config_sync_service.get_model_id_by_display_name') as mock_get_model_id, \
            patch('backend.services.config_sync_service.get_model_name_from_config') as mock_get_model_name, \
            patch('backend.services.config_sync_service.logger') as mock_logger:

        mock_get_model_records.return_value = []
        yield {
            'tenant_config_manager': mock_tenant_config_manager,
            'get_env_key': mock_get_env_key,
            'safe_value': mock_safe_value,
            'get_model_records': mock_get_model_records,
            'get_model_id': mock_get_model_id,
            'get_model_name': mock_get_model_name,
            'logger': mock_logger
        }


class TestSaveConfigSTTModel:
    """Tests for save_config_impl with STT model configuration."""

    @pytest.mark.asyncio
    async def test_save_config_impl_with_stt_model(self, service_mocks):
        """Test saving configuration with STT model."""
        config = MagicMock()
        config_dict = {
            "app": {
                "name": "Test App"
            },
            "models": {
                "stt": {
                    "displayName": "STT Model",
                    "modelFactory": "volc",
                    "modelAppid": "stt_appid_123",
                    "accessToken": "stt_token_456"
                }
            }
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        service_mocks['tenant_config_manager'].load_config.return_value = {}
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()
        service_mocks['safe_value'].side_effect = lambda value: str(value) if value is not None else ""
        service_mocks['get_model_id'].return_value = "stt-model-id"

        result = await save_config_impl(config, tenant_id, user_id)

        assert result is None
        # Verify STT specific fields are saved
        service_mocks['tenant_config_manager'].set_single_config.assert_any_call(
            user_id, tenant_id, "STT_MODEL_FACTORY", "volc"
        )
        service_mocks['tenant_config_manager'].set_single_config.assert_any_call(
            user_id, tenant_id, "STT_MODEL_APPID", "stt_appid_123"
        )
        service_mocks['tenant_config_manager'].set_single_config.assert_any_call(
            user_id, tenant_id, "STT_ACCESS_TOKEN", "stt_token_456"
        )

    @pytest.mark.asyncio
    async def test_save_config_impl_stt_partial_fields(self, service_mocks):
        """Test saving configuration with STT model and partial fields."""
        config = MagicMock()
        config_dict = {
            "app": {
                "name": "Test App"
            },
            "models": {
                "stt": {
                    "displayName": "STT Model",
                    "modelFactory": "volc",
                    "modelAppid": "stt_appid_123"
                    # accessToken is missing
                }
            }
        }
        config.model_dump.return_value = config_dict

        tenant_id = "test_tenant_id"
        user_id = "test_user_id"

        service_mocks['tenant_config_manager'].load_config.return_value = {}
        service_mocks['get_env_key'].side_effect = lambda key: key.upper()
        service_mocks['safe_value'].side_effect = lambda value: str(value) if value is not None else ""
        service_mocks['get_model_id'].return_value = "stt-model-id"

        result = await save_config_impl(config, tenant_id, user_id)

        assert result is None
        # Verify only provided STT fields are saved
        service_mocks['tenant_config_manager'].set_single_config.assert_any_call(
            user_id, tenant_id, "STT_MODEL_FACTORY", "volc"
        )
        service_mocks['tenant_config_manager'].set_single_config.assert_any_call(
            user_id, tenant_id, "STT_MODEL_APPID", "stt_appid_123"
        )
        # accessToken should not be saved


class TestBuildModelConfigSTT:
    """Tests for build_model_config with STT model types."""

    def test_build_model_config_stt(self, service_mocks):
        """Test build_model_config with STT model."""
        model_config = {
            "display_name": "STT Model",
            "api_key": "test-key",
            "base_url": "https://stt.example.com",
            "model_type": "stt",
            "model_factory": "volc",
            "model_appid": "stt_appid",
            "access_token": "stt_token"
        }

        service_mocks['get_model_name'].return_value = "stt-model"

        result = build_model_config(model_config)

        assert result["modelFactory"] == "volc"
        assert result["modelAppid"] == "stt_appid"
        assert result["accessToken"] == "stt_token"

    def test_build_model_config_stt_empty_fields(self, service_mocks):
        """Test build_model_config with STT model and empty voice fields."""
        model_config = {
            "display_name": "STT Model",
            "model_type": "stt"
        }

        service_mocks['get_model_name'].return_value = "stt-model"

        result = build_model_config(model_config)

        assert result["modelFactory"] == ""
        assert result["modelAppid"] == ""
        assert result["accessToken"] == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
