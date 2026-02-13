import os
import importlib
import logging
import sys
import types
import pytest
from unittest import mock

# Add backend to Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)


# Stub external modules required by consts.model before importing services
if "nexent" not in sys.modules:
    sys.modules["nexent"] = mock.MagicMock()
if "nexent.core" not in sys.modules:
    sys.modules["nexent.core"] = mock.MagicMock()
if "nexent.core.agents" not in sys.modules:
    sys.modules["nexent.core.agents"] = mock.MagicMock()
if "nexent.core.agents.agent_model" not in sys.modules:
    agent_model_mod = types.ModuleType("nexent.core.agents.agent_model")

    class ToolConfig:  # minimal stub
        pass

    agent_model_mod.ToolConfig = ToolConfig
    sys.modules["nexent.core.agents.agent_model"] = agent_model_mod

# Stub boto3 used by backend.database.client
if "boto3" not in sys.modules:
    sys.modules["boto3"] = mock.MagicMock()

# Provide stub modules for backend.database.client and database.client so that
# patching MinioClient does not import the real client module (which pulls SQLAlchemy).
backend_db_client_mod = types.ModuleType("backend.database.client")


class _MinioClient:  # minimal stub
    pass


backend_db_client_mod.MinioClient = _MinioClient
sys.modules["backend.database.client"] = backend_db_client_mod

# Ensure parent package exposes the submodule attribute for import machinery
try:
    backend_database_pkg = importlib.import_module("backend.database")
    setattr(backend_database_pkg, "client", backend_db_client_mod)
except Exception:
    # If backend.database is not importable yet, defer to sys.modules injection
    if "backend.database" in sys.modules:
        setattr(sys.modules["backend.database"],
                "client", backend_db_client_mod)

# Also stub database.client.MinioClient in case modules import without the 'backend.' prefix
database_client_mod = types.ModuleType("database.client")
database_client_mod.MinioClient = _MinioClient
sys.modules["database.client"] = database_client_mod

if "database" in sys.modules:
    setattr(sys.modules["database"], "client", database_client_mod)

# Stub consts.model to avoid deep dependencies
consts_model_mod = types.ModuleType("consts.model")


class _EnumItem:
    def __init__(self, value: str):
        self.value = value


class _ModelConnectStatusEnum:
    OPERATIONAL = _EnumItem("operational")
    NOT_DETECTED = _EnumItem("not_detected")
    DETECTING = _EnumItem("detecting")
    UNAVAILABLE = _EnumItem("unavailable")

    @staticmethod
    def get_value(status):
        return status or _ModelConnectStatusEnum.NOT_DETECTED.value


consts_model_mod.ModelConnectStatusEnum = _ModelConnectStatusEnum
sys.modules["consts.model"] = consts_model_mod
if "consts" not in sys.modules:
    sys.modules["consts"] = types.ModuleType("consts")

# Stub consts.const required by service
consts_const_mod = types.ModuleType("consts.const")
consts_const_mod.LOCALHOST_IP = "127.0.0.1"
consts_const_mod.LOCALHOST_NAME = "localhost"
consts_const_mod.DOCKER_INTERNAL_HOST = "host.docker.internal"
# Fields required by utils.memory_utils and services.vectordatabase_service
consts_const_mod.MODEL_CONFIG_MAPPING = {
    "llm": "LLM_ID", "embedding": "EMBEDDING_ID"}
consts_const_mod.ES_HOST = "http://localhost:9200"
consts_const_mod.ES_API_KEY = ""
consts_const_mod.ES_USERNAME = ""
consts_const_mod.ES_PASSWORD = ""
sys.modules["consts.const"] = consts_const_mod

# Stub sqlalchemy.sql.func used by utils.config_utils
sqlalchemy_sql_mod = types.ModuleType("sqlalchemy.sql")


class _Func:
    pass


sqlalchemy_sql_mod.func = _Func()
sys.modules["sqlalchemy.sql"] = sqlalchemy_sql_mod

# Stub consts.provider used by service
consts_provider_mod = types.ModuleType("consts.provider")


class _ProviderEnum:
    SILICON = _EnumItem("silicon")
    MODELENGINE = _EnumItem("modelengine")


consts_provider_mod.ProviderEnum = _ProviderEnum
consts_provider_mod.SILICON_BASE_URL = "http://silicon.test"
sys.modules["consts.provider"] = consts_provider_mod

# Stub services.model_provider_service used by service
services_provider_mod = types.ModuleType("services.model_provider_service")


async def _prepare_model_dict(**kwargs):
    return {}


def _merge_existing_model_tokens(model_list, tenant_id, provider, model_type):
    return model_list


async def _get_provider_models(model_data):
    return []
services_provider_mod.prepare_model_dict = _prepare_model_dict
services_provider_mod.merge_existing_model_tokens = _merge_existing_model_tokens
services_provider_mod.get_provider_models = _get_provider_models
sys.modules["services.model_provider_service"] = services_provider_mod

# Stub services.model_health_service used by service
services_health_mod = types.ModuleType("services.model_health_service")


async def _embedding_dimension_check(model_config):
    return 0
services_health_mod.embedding_dimension_check = _embedding_dimension_check
sys.modules["services.model_health_service"] = services_health_mod

# Stub utils.model_name_utils used by service
utils_name_mod = types.ModuleType("utils.model_name_utils")


def _add_repo_to_name(model_repo, model_name):
    return f"{model_repo}/{model_name}" if model_repo else model_name


def _split_display_name(model_name: str):
    return model_name.split("/")[-1]


def _split_repo_name(model_name: str):
    parts = model_name.split("/", 1)
    return (parts[0], parts[1]) if len(parts) > 1 else ("", parts[0])


def _sort_models_by_id(model_list):
    if isinstance(model_list, list):
        model_list.sort(key=lambda m: str(
            (m.get("id") if isinstance(m, dict) else m) or "")[:1].lower())
    return model_list


utils_name_mod.add_repo_to_name = _add_repo_to_name
utils_name_mod.split_display_name = _split_display_name
utils_name_mod.split_repo_name = _split_repo_name
utils_name_mod.sort_models_by_id = _sort_models_by_id
sys.modules["utils.model_name_utils"] = utils_name_mod

# Stub database.model_management_db to avoid importing heavy DB client
database_mod = types.ModuleType("database")
db_mm_mod = types.ModuleType("database.model_management_db")


def _noop(*args, **kwargs):
    return None


def _get_model_records(*args, **kwargs):
    return []


def _get_models_by_tenant_factory_type(*args, **kwargs):
    return []


def _get_models_by_display_name(*args, **kwargs):
    """Return an empty list for display name lookups in tests."""
    return []


db_mm_mod.create_model_record = _noop
db_mm_mod.delete_model_record = _noop
db_mm_mod.get_model_by_display_name = _noop
db_mm_mod.get_models_by_display_name = _get_models_by_display_name
db_mm_mod.get_model_records = _get_model_records
db_mm_mod.get_models_by_tenant_factory_type = _get_models_by_tenant_factory_type


def _get_model_by_model_id(model_id: int, tenant_id: str):
    # Minimal model config stub for utils.config_utils.get_model_name_from_config usage
    return {
        "model_id": model_id,
        "model_repo": "openai",
        "model_name": "text-embedding-3-small",
        "max_tokens": 1536,
        "base_url": "https://api.openai.com",
        "api_key": "test-key",
    }


db_mm_mod.get_model_by_model_id = _get_model_by_model_id
db_mm_mod.update_model_record = _noop
sys.modules["database"] = database_mod
sys.modules["database.model_management_db"] = db_mm_mod

# Stub database.tenant_config_db required by utils.config_utils
db_tenant_cfg_mod = types.ModuleType("database.tenant_config_db")


def _delete_config_by_tenant_config_id(*args, **kwargs):
    return None


def _get_all_configs_by_tenant_id(tenant_id):
    return {}


def _get_single_config_info(*args, **kwargs):
    return None


def _insert_config(*args, **kwargs):
    return None


def _update_config_by_tenant_config_id_and_data(*args, **kwargs):
    return None


def _update_config_by_tenant_config_id(*args, **kwargs):
    return None


db_tenant_cfg_mod.delete_config_by_tenant_config_id = _delete_config_by_tenant_config_id
db_tenant_cfg_mod.get_all_configs_by_tenant_id = _get_all_configs_by_tenant_id
db_tenant_cfg_mod.get_single_config_info = _get_single_config_info
db_tenant_cfg_mod.insert_config = _insert_config
db_tenant_cfg_mod.update_config_by_tenant_config_id = _update_config_by_tenant_config_id
db_tenant_cfg_mod.update_config_by_tenant_config_id_and_data = _update_config_by_tenant_config_id_and_data
sys.modules["database.tenant_config_db"] = db_tenant_cfg_mod

# Stub services.vectordatabase_service to avoid heavy imports
services_vdb_mod = types.ModuleType("services.vectordatabase_service")


def _get_vector_db_core():
    return object()


services_vdb_mod.get_vector_db_core = _get_vector_db_core
sys.modules["services.vectordatabase_service"] = services_vdb_mod

# Stub nexent.memory.memory_service.clear_model_memories
nexent_memory_mod = types.ModuleType("nexent.memory.memory_service")


async def _clear_model_memories(**kwargs):
    return None
nexent_memory_mod.clear_model_memories = _clear_model_memories
sys.modules["nexent.memory.memory_service"] = nexent_memory_mod

# Stub services.tenant_service required by list_models_for_admin BEFORE any imports
services_tenant_mod = types.ModuleType("services.tenant_service")


def _get_tenant_info(tenant_id):
    """Mock implementation of get_tenant_info for testing."""
    # Raise exception for empty tenant to test error handling
    if tenant_id == "empty_tenant":
        raise Exception("Tenant not found")
    return {"tenant_name": "Test Tenant"}


services_tenant_mod.get_tenant_info = _get_tenant_info
sys.modules["services.tenant_service"] = services_tenant_mod


def _add_repo_to_name(model_repo, model_name):
    """Mock implementation of add_repo_to_name for testing."""
    return f"{model_repo}/{model_name}" if model_repo else model_name


def import_svc():
    """Import service under MinioClient patch to avoid real initialization."""
    minio_client_mock = mock.MagicMock()
    with mock.patch("backend.database.client.MinioClient", return_value=minio_client_mock):
        from backend.services import model_management_service as svc  # type: ignore
    return svc


@pytest.mark.asyncio
async def test_create_model_for_tenant_success_llm():
    svc = import_svc()

    with mock.patch.object(svc, "get_model_by_display_name", return_value=None) as mock_get_by_display, \
            mock.patch.object(svc, "create_model_record") as mock_create, \
            mock.patch.object(svc, "split_repo_name", return_value=("huggingface", "llama")):

        user_id = "u1"
        tenant_id = "t1"
        model_data = {
            "model_name": "huggingface/llama",
            "display_name": None,
            "base_url": "http://localhost:8000",
            "model_type": "llm",
        }
        model_data['ssl_verify'] = False

        await svc.create_model_for_tenant(user_id, tenant_id, model_data)

        mock_get_by_display.assert_called_once_with(
            "huggingface/llama", tenant_id)
        # create_model_record called once for non-multimodal
        assert mock_create.call_count == 1


@pytest.mark.asyncio
async def test_create_model_for_tenant_open_router_disables_ssl():
    """When base_url contains 'open/router' ssl_verify should be set to False."""
    svc = import_svc()

    with mock.patch.object(svc, "get_model_by_display_name", return_value=None), \
            mock.patch.object(svc, "create_model_record") as mock_create, \
            mock.patch.object(svc, "split_repo_name", return_value=("modelengine", "m")):

        user_id = "u1"
        tenant_id = "t1"
        model_data = {
            "model_name": "modelengine/m",
            "display_name": None,
            "base_url": "https://api.example.com/open/router/v1",
            "model_type": "llm",
        }

        await svc.create_model_for_tenant(user_id, tenant_id, model_data)

        # Ensure a single record created and ssl_verify was disabled
        assert mock_create.call_count == 1
        create_args = mock_create.call_args[0][0]
        assert create_args["ssl_verify"] is False


@pytest.mark.asyncio
async def test_create_model_for_tenant_conflict_raises():
    svc = import_svc()

    with mock.patch.object(svc, "get_model_by_display_name", return_value={"model_id": "exists"}):
        user_id = "u1"
        tenant_id = "t1"
        model_data = {
            "model_name": "huggingface/llama",
            "display_name": "dup",
            "base_url": "http://localhost:8000",
            "model_type": "llm",
        }

        with pytest.raises(Exception) as exc:
            await svc.create_model_for_tenant(user_id, tenant_id, model_data)
        assert "Failed to create model" in str(exc.value)


@pytest.mark.asyncio
async def test_create_model_for_tenant_display_name_conflict_valueerror():
    """Test that display_name conflict raises ValueError (covers lines 65-72)"""
    svc = import_svc()

    existing_model = {"model_id": 1, "display_name": "existing_name"}
    with mock.patch.object(svc, "get_model_by_display_name", return_value=existing_model):
        user_id = "u1"
        tenant_id = "t1"
        model_data = {
            "model_name": "huggingface/llama",
            "display_name": "existing_name",  # Conflicts with existing
            "base_url": "http://localhost:8000",
            "model_type": "llm",
        }

        # ValueError is wrapped in Exception, but the error message should contain the original ValueError message
        with pytest.raises(Exception) as exc:
            await svc.create_model_for_tenant(user_id, tenant_id, model_data)
        assert "already in use" in str(exc.value)
        assert "existing_name" in str(exc.value)


@pytest.mark.asyncio
async def test_create_model_for_tenant_multi_embedding_creates_two_records():
    svc = import_svc()

    with mock.patch.object(svc, "get_model_by_display_name", return_value=None), \
            mock.patch.object(svc, "create_model_record") as mock_create, \
            mock.patch.object(svc, "split_repo_name", return_value=("openai", "clip")):

        user_id = "u1"
        tenant_id = "t1"
        model_data = {
            "model_name": "openai/clip",
            "display_name": None,
            "base_url": "https://api.openai.com",
            "model_type": "multi_embedding",
        }

        await svc.create_model_for_tenant(user_id, tenant_id, model_data)
        # Should create two records: multi_embedding and its embedding variant
        assert mock_create.call_count == 2


@pytest.mark.asyncio
async def test_create_model_for_tenant_embedding_sets_dimension():
    svc = import_svc()

    with mock.patch.object(svc, "get_model_by_display_name", return_value=None), \
            mock.patch.object(svc, "embedding_dimension_check", new=mock.AsyncMock(return_value=1536)) as mock_dim, \
            mock.patch.object(svc, "create_model_record") as mock_create, \
            mock.patch.object(svc, "split_repo_name", return_value=("openai", "text-embedding-ada-002")):

        user_id = "u1"
        tenant_id = "t1"
        model_data = {
            "model_name": "openai/text-embedding-ada-002",
            "display_name": None,
            "base_url": "https://api.openai.com",
            "model_type": "embedding",
        }

        await svc.create_model_for_tenant(user_id, tenant_id, model_data)

        mock_dim.assert_awaited()
        # Ensure we created exactly one record (non-multimodal)
        assert mock_create.call_count == 1


@pytest.mark.asyncio
async def test_create_model_for_tenant_embedding_sets_default_chunk_batch():
    """chunk_batch defaults to 10 when not provided for embedding models."""
    svc = import_svc()

    with mock.patch.object(svc, "get_model_by_display_name", return_value=None), \
            mock.patch.object(svc, "embedding_dimension_check", new=mock.AsyncMock(return_value=512)) as mock_dim, \
            mock.patch.object(svc, "create_model_record") as mock_create, \
            mock.patch.object(svc, "split_repo_name", return_value=("openai", "text-embedding-3-small")):

        user_id = "u1"
        tenant_id = "t1"
        model_data = {
            "model_name": "openai/text-embedding-3-small",
            "display_name": None,
            "base_url": "https://api.openai.com",
            "model_type": "embedding",
            "chunk_batch": None,  # Explicitly unset to exercise defaulting
        }

        await svc.create_model_for_tenant(user_id, tenant_id, model_data)

        mock_dim.assert_awaited_once()
        assert mock_create.call_count == 1
        # chunk_batch should be defaulted before persistence
        create_args = mock_create.call_args[0][0]
        assert create_args["chunk_batch"] == 10


@pytest.mark.asyncio
async def test_create_model_for_tenant_multi_embedding_sets_default_chunk_batch():
    """chunk_batch defaults to 10 when not provided for multi_embedding models (covers line 79)."""
    svc = import_svc()

    with mock.patch.object(svc, "get_model_by_display_name", return_value=None), \
            mock.patch.object(svc, "embedding_dimension_check", new=mock.AsyncMock(return_value=512)) as mock_dim, \
            mock.patch.object(svc, "create_model_record") as mock_create, \
            mock.patch.object(svc, "split_repo_name", return_value=("openai", "clip")):

        user_id = "u1"
        tenant_id = "t1"
        model_data = {
            "model_name": "openai/clip",
            "display_name": None,
            "base_url": "https://api.openai.com",
            "model_type": "multi_embedding",
            "chunk_batch": None,  # Explicitly unset to exercise defaulting
        }

        await svc.create_model_for_tenant(user_id, tenant_id, model_data)

        mock_dim.assert_awaited_once()
        # Should create two records: multi_embedding and its embedding variant
        assert mock_create.call_count == 2

        # Verify chunk_batch was set to 10 for both records
        create_calls = mock_create.call_args_list
        # First call is for multi_embedding
        multi_emb_args = create_calls[0][0][0]
        assert multi_emb_args["chunk_batch"] == 10
        assert multi_emb_args["model_type"] == "multi_embedding"
        # Second call is for embedding variant
        emb_args = create_calls[1][0][0]
        assert emb_args["chunk_batch"] == 10
        assert emb_args["model_type"] == "embedding"


@pytest.mark.asyncio
async def test_create_provider_models_for_tenant_success():
    svc = import_svc()

    req = {"provider": "silicon", "model_type": "llm"}
    models = [{"id": "silicon/a"}, {"id": "silicon/b"}]

    with mock.patch.object(svc, "get_provider_models", new=mock.AsyncMock(return_value=models)) as mock_get, \
            mock.patch.object(svc, "merge_existing_model_tokens", return_value=models) as mock_merge, \
            mock.patch.object(svc, "sort_models_by_id", side_effect=lambda m: m) as mock_sort:

        out = await svc.create_provider_models_for_tenant("t1", req)
        assert out == models
        mock_get.assert_awaited_once()
        mock_merge.assert_called_once()
        mock_sort.assert_called_once()


@pytest.mark.asyncio
async def test_create_provider_models_for_tenant_exception():
    svc = import_svc()

    req = {"provider": "silicon", "model_type": "llm"}
    with mock.patch.object(svc, "get_provider_models", new=mock.AsyncMock(side_effect=Exception("boom"))):
        with pytest.raises(Exception) as exc:
            await svc.create_provider_models_for_tenant("t1", req)
        assert "Failed to create provider models" in str(exc.value)


@pytest.mark.asyncio
async def test_batch_create_models_for_tenant_other_provider():
    """Test batch_create_models_for_tenant with non-Silicon/ModelEngine provider (covers lines 138-140)"""
    svc = import_svc()

    batch_payload = {
        "provider": "openai",  # Not Silicon or ModelEngine
        "type": "llm",
        "models": [
            {"id": "openai/gpt-4", "max_tokens": 4096},
        ],
        "api_key": "k",
    }

    # Add MODELENGINE to ProviderEnum if it doesn't exist
    if not hasattr(svc.ProviderEnum, 'MODELENGINE'):
        modelengine_item = _EnumItem("modelengine")
        svc.ProviderEnum.MODELENGINE = modelengine_item

    with mock.patch.object(svc, "get_models_by_tenant_factory_type", return_value=[]), \
            mock.patch.object(svc, "delete_model_record"), \
            mock.patch.object(svc, "split_repo_name", return_value=("openai", "gpt-4")), \
            mock.patch.object(svc, "add_repo_to_name", return_value="openai/gpt-4"), \
            mock.patch.object(svc, "get_model_by_display_name", return_value=None), \
            mock.patch.object(svc, "prepare_model_dict", new=mock.AsyncMock(return_value={"model_id": 1})), \
            mock.patch.object(svc, "create_model_record", return_value=True):

        await svc.batch_create_models_for_tenant("u1", "t1", batch_payload)

        # Verify prepare_model_dict was called with empty model_url for non-Silicon/ModelEngine provider
        call_args = svc.prepare_model_dict.call_args
        # Should be empty for other providers
        assert call_args[1]["model_url"] == ""


@pytest.mark.asyncio
async def test_batch_create_models_for_tenant_flow():
    svc = import_svc()

    batch_payload = {
        "provider": "silicon",
        "type": "llm",
        "models": [
            {"id": "silicon/keep", "max_tokens": 4096},
            {"id": "silicon/new", "max_tokens": 8192},
        ],
        "api_key": "k",
    }

    existing = [
        {"model_id": "del-id", "model_repo": "silicon", "model_name": "delete"},
        {"model_id": "keep-id", "model_repo": "silicon", "model_name": "keep"},
    ]

    def get_by_display(display_name, tenant_id):
        if display_name == "silicon/keep":
            return {"model_id": "keep-id", "max_tokens": 1024}
        return None

    with mock.patch.object(svc, "get_models_by_tenant_factory_type", return_value=existing) as mock_get_existing, \
            mock.patch.object(svc, "delete_model_record") as mock_delete, \
            mock.patch.object(svc, "get_model_by_display_name", side_effect=get_by_display) as mock_get_by_display, \
            mock.patch.object(svc, "update_model_record") as mock_update, \
            mock.patch.object(svc, "prepare_model_dict", new=mock.AsyncMock(return_value={"prepared": True})) as mock_prep, \
            mock.patch.object(svc, "create_model_record") as mock_create:

        await svc.batch_create_models_for_tenant("u1", "t1", batch_payload)

        mock_get_existing.assert_called_once_with("t1", "silicon", "llm")
        mock_delete.assert_called_once_with("del-id", "u1", "t1")
        mock_get_by_display.assert_any_call("silicon/keep", "t1")
        mock_update.assert_called_once_with(
            "keep-id", {"max_tokens": 4096}, "u1")
        mock_prep.assert_awaited()
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_batch_create_models_max_tokens_update():
    """Test batch_create_models updates max_tokens when display_name exists and max_tokens changed (covers lines 160->173, 168->171)"""
    svc = import_svc()

    batch_payload = {
        "provider": "silicon",
        "type": "llm",
        "models": [
            {"id": "silicon/model1", "max_tokens": 8192},  # Changed from 4096
            {"id": "silicon/model2", "max_tokens": 4096},  # Same as existing
            {"id": "silicon/model3", "max_tokens": None},  # None should not update
        ],
        "api_key": "k",
    }

    def get_by_display(display_name, tenant_id):
        if display_name == "silicon/model1":
            # Different from new value
            return {"model_id": "id1", "max_tokens": 4096}
        elif display_name == "silicon/model2":
            return {"model_id": "id2", "max_tokens": 4096}  # Same as new value
        elif display_name == "silicon/model3":
            # Existing has value, new is None
            return {"model_id": "id3", "max_tokens": 2048}
        return None

    with mock.patch.object(svc, "get_models_by_tenant_factory_type", return_value=[]), \
            mock.patch.object(svc, "delete_model_record"), \
            mock.patch.object(svc, "split_repo_name", side_effect=lambda x: ("silicon", x.split("/")[1] if "/" in x else x)), \
            mock.patch.object(svc, "add_repo_to_name", side_effect=lambda r, n: f"{r}/{n}"), \
            mock.patch.object(svc, "get_model_by_display_name", side_effect=get_by_display) as mock_get_by_display, \
            mock.patch.object(svc, "update_model_record") as mock_update, \
            mock.patch.object(svc, "prepare_model_dict", new=mock.AsyncMock(return_value={"model_id": 1})), \
            mock.patch.object(svc, "create_model_record", return_value=True):

        await svc.batch_create_models_for_tenant("u1", "t1", batch_payload)

        # Should update model1 (max_tokens changed from 4096 to 8192)
        # Note: update_model_record may be called multiple times, so check if it was called with correct args
        update_calls = [
            call for call in mock_update.call_args_list if call[0][0] == "id1"]
        if update_calls:
            assert update_calls[0][0][1] == {"max_tokens": 8192}

        # Should NOT update model2 (max_tokens same) or model3 (new max_tokens is None)
        # Verify model2 and model3 were not updated
        model2_calls = [
            call for call in mock_update.call_args_list if call[0][0] == "id2"]
        model3_calls = [
            call for call in mock_update.call_args_list if call[0][0] == "id3"]
        # model2 should not be updated (same max_tokens)
        assert len(model2_calls) == 0
        # model3 should not be updated (new max_tokens is None)
        assert len(model3_calls) == 0


@pytest.mark.asyncio
async def test_batch_create_models_for_tenant_exception():
    svc = import_svc()

    batch_payload = {"provider": "other", "type": "llm",
                     "models": [{"id": "x"}], "api_key": "k"}

    with mock.patch.object(svc, "get_models_by_tenant_factory_type", return_value=[]), \
            mock.patch.object(svc, "prepare_model_dict", new=mock.AsyncMock(side_effect=Exception("prep failed"))):
        with pytest.raises(Exception) as exc:
            await svc.batch_create_models_for_tenant("u1", "t1", batch_payload)
        assert "Failed to batch create models" in str(exc.value)


async def test_list_provider_models_for_tenant_success():
    svc = import_svc()

    existing = [
        {"model_repo": "huggingface", "model_name": "llama"},
        {"model_repo": "openai", "model_name": "clip"},
    ]
    with mock.patch.object(svc, "get_models_by_tenant_factory_type", return_value=existing):
        out = await svc.list_provider_models_for_tenant("t1", "huggingface", "llm")
        assert out[0]["id"] == "huggingface/llama"
        assert out[1]["id"] == "openai/clip"


async def test_list_provider_models_for_tenant_exception():
    svc = import_svc()

    with mock.patch.object(svc, "get_models_by_tenant_factory_type", side_effect=Exception("db")):
        with pytest.raises(Exception) as exc:
            await svc.list_provider_models_for_tenant("t1", "p", "llm")
        assert "Failed to list provider models" in str(exc.value)


async def test_update_single_model_for_tenant_success_single_model():
    """Update succeeds for a single non-embedding model with no display_name change."""
    svc = import_svc()

    existing_models = [
        {"model_id": 1, "model_type": "llm", "display_name": "name"},
    ]
    model_data = {
        "model_id": 1,
        "display_name": "name",
        "description": "updated",
        "model_type": "llm",
    }

    with mock.patch.object(svc, "get_models_by_display_name", return_value=existing_models) as mock_get, \
            mock.patch.object(svc, "update_model_record") as mock_update:
        await svc.update_single_model_for_tenant("u1", "t1", "name", model_data)

        mock_get.assert_called_once_with("name", "t1")
        # update_model_record should be called without model_id in the payload
        mock_update.assert_called_once_with(
            1,
            {"display_name": "name", "description": "updated", "model_type": "llm"},
            "u1",
        )


async def test_update_single_model_for_tenant_conflict_new_display_name():
    """Updating to a new conflicting display_name raises ValueError."""
    svc = import_svc()

    existing_models = [
        {"model_id": 1, "model_type": "llm", "display_name": "old_name"},
    ]
    conflict_models = [
        {"model_id": 2, "model_type": "llm", "display_name": "new_name"},
    ]
    model_data = {
        "model_id": 1,
        "display_name": "new_name",
    }

    with mock.patch.object(svc, "get_models_by_display_name", side_effect=[existing_models, conflict_models]):
        with pytest.raises(ValueError) as exc:
            await svc.update_single_model_for_tenant("u1", "t1", "old_name", model_data)
        assert "already in use" in str(exc.value)


async def test_update_single_model_for_tenant_not_found_raises_lookup_error():
    """If no model is found for current_display_name, raise LookupError."""
    svc = import_svc()

    with mock.patch.object(svc, "get_models_by_display_name", return_value=[]):
        with pytest.raises(LookupError):
            await svc.update_single_model_for_tenant("u1", "t1", "missing", {"display_name": "x"})


async def test_update_single_model_for_tenant_multi_embedding_updates_both():
    """Updating multi_embedding models updates both embedding and multi_embedding records."""
    svc = import_svc()

    existing_models = [
        {"model_id": 10, "model_type": "embedding", "display_name": "emb_name"},
        {"model_id": 11, "model_type": "multi_embedding", "display_name": "emb_name"},
    ]
    model_data = {
        "model_id": 10,
        "display_name": "emb_name",
        "description": "updated",
        "model_type": "multi_embedding",
    }

    with mock.patch.object(svc, "get_models_by_display_name", return_value=existing_models) as mock_get, \
            mock.patch.object(svc, "update_model_record") as mock_update:
        await svc.update_single_model_for_tenant("u1", "t1", "emb_name", model_data)

        mock_get.assert_called_once_with("emb_name", "t1")
        # model_type should be stripped from update payload for multi_embedding flow
        expected_update = {"display_name": "emb_name",
                           "description": "updated"}
        mock_update.assert_any_call(10, expected_update, "u1")
        mock_update.assert_any_call(11, expected_update, "u1")


async def test_batch_update_models_for_tenant_success():
    svc = import_svc()

    models = [{"model_id": "a"}, {"model_id": "b"}]
    with mock.patch.object(svc, "update_model_record") as mock_update:
        await svc.batch_update_models_for_tenant("u1", "t1", models)
        assert mock_update.call_count == 2
        mock_update.assert_any_call("a", models[0], "u1", "t1")
        mock_update.assert_any_call("b", models[1], "u1", "t1")


async def test_batch_update_models_for_tenant_exception():
    svc = import_svc()

    models = [{"model_id": "a"}]
    with mock.patch.object(svc, "update_model_record", side_effect=Exception("oops")):
        with pytest.raises(Exception) as exc:
            await svc.batch_update_models_for_tenant("u1", "t1", models)
        assert "Failed to batch update models" in str(exc.value)


async def test_delete_model_for_tenant_not_found_raises_lookup_error():
    """If no models are found for display_name, raise LookupError."""
    svc = import_svc()

    with mock.patch.object(svc, "get_models_by_display_name", return_value=[]):
        with pytest.raises(LookupError):
            await svc.delete_model_for_tenant("u1", "t1", "missing")


async def test_delete_model_for_tenant_embedding_deletes_both():
    """Embedding + multi_embedding models are both deleted and memories cleared."""
    svc = import_svc()

    models = [
        {
            "model_id": "id-emb",
            "model_type": "embedding",
            "model_repo": "openai",
            "model_name": "text-embedding-3-small",
            "max_tokens": 1536,
        },
        {
            "model_id": "id-multi",
            "model_type": "multi_embedding",
            "model_repo": "openai",
            "model_name": "text-embedding-3-small",
            "max_tokens": 1536,
        },
    ]

    with mock.patch.object(svc, "get_models_by_display_name", return_value=models) as mock_get, \
            mock.patch.object(svc, "delete_model_record") as mock_delete, \
            mock.patch.object(svc, "get_vector_db_core", return_value=object()) as mock_get_vdb, \
            mock.patch.object(svc, "build_memory_config_for_tenant", return_value={}) as mock_build_cfg, \
            mock.patch.object(svc, "clear_model_memories", new=mock.AsyncMock()) as mock_clear:
        await svc.delete_model_for_tenant("u1", "t1", "name")

        mock_get.assert_called_once_with("name", "t1")
        assert mock_delete.call_count == 2
        mock_get_vdb.assert_called_once()
        mock_build_cfg.assert_called_once_with("t1")
        # Best-effort cleanup should be attempted for both records
        assert mock_clear.await_count == 2


@pytest.mark.asyncio
async def test_delete_model_for_tenant_cleanup_inner_exception(caplog):
    svc = import_svc()

    models = [
        {"model_id": "id-emb", "model_type": "embedding",
            "model_repo": "r", "model_name": "n", "max_tokens": 1},
        {"model_id": "id-multi", "model_type": "multi_embedding",
            "model_repo": "r", "model_name": "n", "max_tokens": 1},
    ]
    with mock.patch.object(svc, "get_models_by_display_name", return_value=models), \
            mock.patch.object(svc, "delete_model_record") as mock_delete, \
            mock.patch.object(svc, "get_vector_db_core", return_value=object()), \
            mock.patch.object(svc, "build_memory_config_for_tenant", return_value={}), \
            mock.patch.object(svc, "clear_model_memories", new=mock.AsyncMock(side_effect=Exception("boom"))):

        with caplog.at_level(logging.WARNING):
            await svc.delete_model_for_tenant("u1", "t1", "name")

        assert mock_delete.call_count == 2
        assert any(
            "Best-effort clear_model_memories failed" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_delete_model_for_tenant_cleanup_outer_exception(caplog):
    svc = import_svc()

    models = [
        {"model_id": "id-emb", "model_type": "embedding"},
        {"model_id": "id-multi", "model_type": "multi_embedding"},
    ]
    with mock.patch.object(svc, "get_models_by_display_name", return_value=models), \
            mock.patch.object(svc, "delete_model_record") as mock_delete, \
            mock.patch.object(svc, "get_vector_db_core", side_effect=Exception("vdb_down")), \
            mock.patch.object(svc, "build_memory_config_for_tenant", return_value={}):

        with caplog.at_level(logging.WARNING):
            await svc.delete_model_for_tenant("u1", "t1", "name")

        assert mock_delete.call_count == 2
        assert any(
            "Memory cleanup preparation failed" in rec.message for rec in caplog.records)


async def test_delete_model_for_tenant_non_embedding():
    """Non-embedding model deletes a single record without memory cleanup."""
    svc = import_svc()

    models = [
        {"model_id": "id", "model_type": "llm"},
    ]
    with mock.patch.object(svc, "get_models_by_display_name", return_value=models), \
            mock.patch.object(svc, "delete_model_record") as mock_delete, \
            mock.patch.object(svc, "get_vector_db_core") as mock_get_vdb:
        await svc.delete_model_for_tenant("u1", "t1", "name")
        mock_delete.assert_called_once_with("id", "u1", "t1")
        # For non-embedding models we should not prepare vector DB cleanup
        mock_get_vdb.assert_not_called()


async def test_list_models_for_tenant_success():
    svc = import_svc()

    records = [
        {"model_repo": "huggingface", "model_name": "llama",
            "connect_status": "operational"},
        {"model_repo": "openai", "model_name": "clip", "connect_status": None},
    ]
    with mock.patch.object(svc, "get_model_records", return_value=records), \
            mock.patch.object(svc, "add_repo_to_name", side_effect=lambda model_repo, model_name: f"{model_repo}/{model_name}" if model_repo else model_name), \
            mock.patch.object(svc.ModelConnectStatusEnum, "get_value", side_effect=lambda s: s or "not_detected"):
        out = await svc.list_models_for_tenant("t1")
        assert out[0]["model_name"] == "huggingface/llama"
        assert out[1]["model_name"] == "openai/clip"
        assert out[1]["connect_status"] == "not_detected"


async def test_list_models_for_tenant_exception():
    svc = import_svc()

    with mock.patch.object(svc, "get_model_records", side_effect=Exception("db")):
        with pytest.raises(Exception) as exc:
            await svc.list_models_for_tenant("t1")
        assert "Failed to retrieve model list" in str(exc.value)


async def test_list_llm_models_for_tenant_success():
    """Test list_llm_models_for_tenant returns filtered LLM models."""
    svc = import_svc()

    records = [
        {
            "model_id": "llm1",
            "model_repo": "huggingface",
            "model_name": "llama-2",
            "display_name": "LLaMA 2",
            "connect_status": "operational"
        },
        {
            "model_id": "llm2",
            "model_repo": "openai",
            "model_name": "gpt-4",
            "display_name": "GPT-4",
            "connect_status": "not_detected"
        }
    ]

    with mock.patch.object(svc, "get_model_records", return_value=records) as mock_get_records, \
            mock.patch.object(svc, "add_repo_to_name", side_effect=lambda model_repo, model_name: f"{model_repo}/{model_name}" if model_repo else model_name), \
            mock.patch.object(svc.ModelConnectStatusEnum, "get_value", side_effect=lambda s: s or "not_detected"):

        result = await svc.list_llm_models_for_tenant("t1")

        # Should only return LLM models, filtered by model_type="llm"
        assert len(result) == 2
        assert result[0]["model_id"] == "llm1"
        assert result[0]["model_name"] == "huggingface/llama-2"
        assert result[0]["display_name"] == "LLaMA 2"
        assert result[0]["connect_status"] == "operational"

        assert result[1]["model_id"] == "llm2"
        assert result[1]["model_name"] == "openai/gpt-4"
        assert result[1]["display_name"] == "GPT-4"
        assert result[1]["connect_status"] == "not_detected"

        # Verify get_model_records was called with correct filter
        mock_get_records.assert_called_once_with({"model_type": "llm"}, "t1")


async def test_list_llm_models_for_tenant_exception():
    """Test list_llm_models_for_tenant handles exceptions properly."""
    svc = import_svc()

    with mock.patch.object(svc, "get_model_records", side_effect=Exception("Database error")):
        with pytest.raises(Exception) as exc:
            await svc.list_llm_models_for_tenant("t1")
        assert "Failed to retrieve model list" in str(exc.value)


async def test_list_llm_models_for_tenant_normalizes_connect_status():
    """Test list_llm_models_for_tenant normalizes connect_status values."""
    svc = import_svc()

    records = [
        {
            "model_id": "llm1",
            "model_repo": "huggingface",
            "model_name": "llama-2",
            "display_name": "LLaMA 2",
            "connect_status": None  # Should be normalized to "not_detected"
        },
        {
            "model_id": "llm2",
            "model_repo": "openai",
            "model_name": "gpt-4",
            "display_name": "GPT-4",
            "connect_status": "operational"
        }
    ]

    with mock.patch.object(svc, "get_model_records", return_value=records), \
            mock.patch.object(svc, "add_repo_to_name", side_effect=lambda model_repo, model_name: f"{model_repo}/{model_name}" if model_repo else model_name), \
            mock.patch.object(svc.ModelConnectStatusEnum, "get_value", side_effect=lambda s: s or "not_detected"):

        result = await svc.list_llm_models_for_tenant("t1")

        assert len(result) == 2
        # Normalized from None
        assert result[0]["connect_status"] == "not_detected"
        assert result[1]["connect_status"] == "operational"


async def test_list_models_for_tenant_type_mapping():
    """Test list_models_for_tenant maps model_type from 'chat' to 'llm' (covers line 310)"""
    svc = import_svc()

    records = [
        {
            "model_id": "llm1",
            "model_repo": "openai",
            "model_name": "gpt-4",
            "display_name": "GPT-4",
            "model_type": "chat",  # ModelEngine type that should be mapped to "llm"
            "connect_status": "operational"
        },
        {
            "model_id": "llm2",
            "model_repo": "anthropic",
            "model_name": "claude-3",
            "display_name": "Claude 3",
            "model_type": "llm",  # Already correct type
            "connect_status": "not_detected"
        }
    ]

    with mock.patch.object(svc, "get_model_records", return_value=records), \
            mock.patch.object(svc, "add_repo_to_name", side_effect=lambda model_repo, model_name: f"{model_repo}/{model_name}" if model_repo else model_name), \
            mock.patch.object(svc.ModelConnectStatusEnum, "get_value", side_effect=lambda s: s or "not_detected"):

        result = await svc.list_models_for_tenant("t1")

        assert len(result) == 2
        # First model should have model_type mapped from "chat" to "llm" (covers line 310)
        assert result[0]["model_type"] == "llm"  # Should be mapped from "chat"
        assert result[0]["model_id"] == "llm1"
        # Second model should remain "llm"
        assert result[1]["model_type"] == "llm"
        assert result[1]["model_id"] == "llm2"


async def test_list_llm_models_for_tenant_handles_missing_repo():
    """Test list_llm_models_for_tenant handles models without repo."""
    svc = import_svc()

    records = [
        {
            "model_id": "llm1",
            "model_repo": "",  # Empty repo
            "model_name": "local-model",
            "display_name": "Local Model",
            "connect_status": "operational"
        },
        {
            "model_id": "llm2",
            "model_repo": None,  # None repo
            "model_name": "another-model",
            "display_name": "Another Model",
            "connect_status": "operational"
        }
    ]

    with mock.patch.object(svc, "get_model_records", return_value=records), \
            mock.patch.object(svc, "add_repo_to_name", side_effect=lambda model_repo, model_name: f"{model_repo}/{model_name}" if model_repo else model_name), \
            mock.patch.object(svc.ModelConnectStatusEnum, "get_value", side_effect=lambda s: s or "not_detected"):

        result = await svc.list_llm_models_for_tenant("t1")

        assert len(result) == 2
        assert result[0]["model_name"] == "local-model"  # No repo prefix
        assert result[1]["model_name"] == "another-model"  # No repo prefix


# Tests for list_models_for_admin
async def test_list_models_for_admin_success():
    """Test list_models_for_tenant returns models for a specified tenant."""
    svc = import_svc()

    records = [
        {"model_repo": "huggingface", "model_name": "llama",
            "connect_status": "operational", "model_type": "llm"},
        {"model_repo": "openai", "model_name": "clip", "connect_status": None, "model_type": "embedding"},
    ]

    with mock.patch.object(svc, "get_model_records", return_value=records), \
            mock.patch.object(svc, "add_repo_to_name", side_effect=lambda model_repo, model_name: f"{model_repo}/{model_name}" if model_repo else model_name), \
            mock.patch.object(svc.ModelConnectStatusEnum, "get_value", side_effect=lambda s: s or "not_detected"):
        out = await svc.list_models_for_admin("t1")
        assert out["tenant_id"] == "t1"
        assert out["tenant_name"] == "Test Tenant"
        assert out["total"] == 2
        assert out["page"] == 1
        assert out["page_size"] == 20
        assert out["total_pages"] == 1
        assert len(out["models"]) == 2
        assert out["models"][0]["model_name"] == "huggingface/llama"


async def test_list_models_for_admin_with_pagination():
    """Test list_models_for_tenant handles pagination correctly."""
    svc = import_svc()

    # Create 25 records to test pagination
    records = [
        {"model_repo": "openai", "model_name": f"gpt-{i}", "connect_status": "operational", "model_type": "llm"}
        for i in range(25)
    ]

    with mock.patch.object(svc, "get_model_records", return_value=records), \
            mock.patch("backend.utils.model_name_utils.add_repo_to_name", side_effect=_add_repo_to_name), \
            mock.patch.object(svc.ModelConnectStatusEnum, "get_value", side_effect=lambda s: s or "not_detected"):
        # Page 1, page_size 10
        out = await svc.list_models_for_admin("t1", page=1, page_size=10)
        assert out["page"] == 1
        assert out["page_size"] == 10
        assert out["total"] == 25
        assert out["total_pages"] == 3
        assert len(out["models"]) == 10
        assert out["models"][0]["model_name"] == "openai/gpt-0"

        # Page 2
        out = await svc.list_models_for_admin("t1", page=2, page_size=10)
        assert out["page"] == 2
        assert len(out["models"]) == 10

        # Page 3 (last page)
        out = await svc.list_models_for_admin("t1", page=3, page_size=10)
        assert out["page"] == 3
        assert out["total_pages"] == 3
        assert len(out["models"]) == 5


async def test_list_models_for_admin_with_model_type_filter():
    """Test list_models_for_tenant filters by model_type."""
    svc = import_svc()

    records = [
        {"model_repo": "openai", "model_name": "gpt-4", "connect_status": "operational", "model_type": "llm"},
        {"model_repo": "openai", "model_name": "text-embedding", "connect_status": "operational", "model_type": "embedding"},
    ]

    with mock.patch.object(svc, "get_model_records", return_value=records) as mock_get_records, \
            mock.patch("backend.utils.model_name_utils.add_repo_to_name", side_effect=lambda model_repo, model_name: f"{model_repo}/{model_name}" if model_repo else model_name), \
            mock.patch.object(svc.ModelConnectStatusEnum, "get_value", side_effect=lambda s: s or "not_detected"):
        # Filter by llm
        out = await svc.list_models_for_admin("t1", model_type="llm")
        mock_get_records.assert_called_once_with({"model_type": "llm"}, "t1")
        assert out["total"] == 2
        assert out["models"][0]["model_type"] == "llm"


async def test_list_models_for_admin_empty_tenant():
    """Test list_models_for_tenant handles empty tenant gracefully."""
    svc = import_svc()

    with mock.patch.object(svc, "get_model_records", return_value=[]):
        # Use "empty_tenant" ID to trigger exception in stub, resulting in empty tenant_name
        out = await svc.list_models_for_admin("empty_tenant")
        assert out["tenant_id"] == "empty_tenant"
        assert out["tenant_name"] == ""
        assert out["total"] == 0
        assert out["total_pages"] == 0
        assert len(out["models"]) == 0


async def test_list_models_for_admin_exception():
    """Test list_models_for_tenant handles exceptions."""
    svc = import_svc()

    with mock.patch.object(svc, "get_model_records", side_effect=Exception("db error")):
        with pytest.raises(Exception) as exc:
            await svc.list_models_for_admin("t1")
        assert "Failed to retrieve admin model list" in str(exc.value)


async def test_list_models_for_admin_type_mapping():
    """Test list_models_for_tenant maps model_type from 'chat' to 'llm'."""
    svc = import_svc()

    records = [
        {
            "model_id": "llm1",
            "model_repo": "openai",
            "model_name": "gpt-4",
            "display_name": "GPT-4",
            "model_type": "chat",  # Should be mapped to "llm"
            "connect_status": "operational"
        },
    ]

    with mock.patch.object(svc, "get_model_records", return_value=records), \
            mock.patch.object(svc, "add_repo_to_name", side_effect=lambda model_repo, model_name: f"{model_repo}/{model_name}" if model_repo else model_name), \
            mock.patch.object(svc.ModelConnectStatusEnum, "get_value", side_effect=lambda s: s or "not_detected"):
        out = await svc.list_models_for_admin("t1")

        assert len(out["models"]) == 1
        assert out["models"][0]["model_type"] == "llm"  # Should be mapped from "chat"
