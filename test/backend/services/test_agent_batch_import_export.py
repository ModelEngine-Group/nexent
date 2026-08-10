import sys
import io
import json
import zipfile
import base64
import types
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# =============================================================================
# STEP 1: Set up sys.modules mocks BEFORE any backend imports
# =============================================================================

email_validator_mock = types.ModuleType("email_validator")


class MockEmailNotValidError(ValueError):
    pass


def mock_validate_email(email, check_deliverability=False):
    local_part = email.split("@", 1)[0]
    return types.SimpleNamespace(normalized=email, local_part=local_part)

email_validator_mock.EmailNotValidError = MockEmailNotValidError
email_validator_mock.validate_email = mock_validate_email
sys.modules["email_validator"] = email_validator_mock

try:
    import pydantic.networks as pydantic_networks
    original_package_version = pydantic_networks.version
    pydantic_networks.version = (
        lambda package_name: "2.0.0"
        if package_name == "email-validator"
        else original_package_version(package_name)
    )
except Exception:
    pass


class MockToolConfig:
    def __init__(self, *args, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def model_dump(self, **kwargs):
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


nexent_agent_model_mock = MagicMock()
nexent_agent_model_mock.ToolConfig = MockToolConfig
sys.modules["nexent"] = MagicMock()
sys.modules["nexent.core"] = MagicMock()
sys.modules["nexent.core.agents"] = MagicMock()
sys.modules["nexent.core.agents.agent_model"] = nexent_agent_model_mock
sys.modules["nexent.core.agents.run_agent"] = MagicMock()

context_input_mock = types.ModuleType("nexent.core.agents.context_input")


class MockContextInput:
    def __init__(self, items=()):
        self.items = items


context_input_mock.ContextInput = MockContextInput
sys.modules["nexent.core.agents.context_input"] = context_input_mock

context_items_mock = types.ModuleType("nexent.core.agents.context")
context_items_mock.ContextItemInput = MagicMock()
sys.modules["nexent.core.agents.context"] = context_items_mock

sys.modules["nexent.core.models"] = MagicMock()
sys.modules["nexent.core.utils"] = MagicMock()


class MockProcessType:
    class MODEL_OUTPUT_CODE:
        value = "model_output_code"

    class MODEL_OUTPUT_THINKING:
        value = "model_output_thinking"

    class MODEL_OUTPUT_DEEP_THINKING:
        value = "model_output_deep_thinking"

    class STEP_COUNT:
        value = "step_count"

    class TOOL:
        value = "tool"

    class EXECUTION_LOGS:
        value = "execution_logs"

    class SKILL_ARTIFACT:
        value = "skill_artifact"


sys.modules["nexent.core.utils.observer"] = MagicMock()
sys.modules["nexent.core.utils.observer"].ProcessType = MockProcessType

rerank_module = MagicMock()
rerank_module.BaseRerank = type("BaseRerank", (), {})
rerank_module.OpenAICompatibleRerank = type("OpenAICompatibleRerank", (), {})
sys.modules["nexent.core.models.rerank_model"] = rerank_module

sys.modules["nexent.memory"] = MagicMock()
sys.modules["nexent.memory.memory_service"] = MagicMock()
sys.modules["nexent.storage"] = MagicMock()
sys.modules["nexent.storage.storage_client_factory"] = MagicMock()
sys.modules["nexent.storage.minio_config"] = MagicMock()
sys.modules["nexent.monitor"] = MagicMock()
sys.modules["nexent.monitor.monitoring"] = MagicMock()

sys.modules["boto3"] = MagicMock()
sys.modules["elasticsearch"] = MagicMock()
sys.modules["sqlalchemy"] = MagicMock()

sys.modules["database.agent_db"] = MagicMock()
sys.modules["database.tool_db"] = MagicMock()
sys.modules["database.remote_mcp_db"] = MagicMock()
sys.modules["database.agent_version_db"] = MagicMock()
sys.modules["database.group_db"] = MagicMock()
sys.modules["database.user_tenant_db"] = MagicMock()
sys.modules["database.model_management_db"] = MagicMock()
sys.modules["database.a2a_agent_db"] = MagicMock()
sys.modules["database.skill_db"] = MagicMock()
sys.modules["database.attachment_db"] = MagicMock()

_mock_db_client = MagicMock()
_mock_db_client.get_db_session = MagicMock()
_mock_db_client.as_dict = MagicMock()
_mock_db_client.MinioClient = MagicMock()
_mock_db_client.db_client = MagicMock()
sys.modules["database.client"] = _mock_db_client
sys.modules["backend.database.client"] = _mock_db_client

services_module = types.ModuleType("services")
services_module.__path__ = []
sys.modules["services"] = services_module

runtime_state_service_module = types.ModuleType("services.runtime_state_service")
runtime_state_service_mock = MagicMock()
runtime_state_service_mock.enabled = False
runtime_state_service_mock.is_cancelled_async = AsyncMock(return_value=False)
runtime_state_service_mock.get_run_state_async = AsyncMock(return_value={})
runtime_state_service_module.runtime_state_service = runtime_state_service_mock
sys.modules["services.runtime_state_service"] = runtime_state_service_module

conversation_management_service_mock = MagicMock()
memory_config_service_mock = MagicMock()
agent_version_service_mock = MagicMock()
skill_service_mock = MagicMock()
skill_service_mock.SkillService.return_value.list_skill_instances.return_value = []
prompt_template_service_mock = MagicMock()
prompt_template_service_mock.SYSTEM_PROMPT_TEMPLATE_ID = 0
prompt_template_service_mock.SYSTEM_PROMPT_TEMPLATE_NAME = "system_default"
prompt_template_service_mock.get_prompt_template_summary = MagicMock(return_value=(None, None))
prompt_template_service_mock.resolve_prompt_generate_template = MagicMock(return_value={})

sys.modules["services.conversation_management_service"] = conversation_management_service_mock
sys.modules["services.memory_config_service"] = memory_config_service_mock
sys.modules["services.agent_version_service"] = agent_version_service_mock
sys.modules["services.skill_service"] = skill_service_mock
sys.modules["services.prompt_template_service"] = prompt_template_service_mock
sys.modules["services.file_management_service"] = MagicMock()
sys.modules["services.streaming_channel"] = MagicMock()


class AsyncChannelMock:
    async def publish(self, *args, **kwargs):
        pass

    async def close(self, *args, **kwargs):
        pass


streaming_channel_manager_mock = MagicMock()
streaming_channel_manager_mock.get_or_create_channel = AsyncMock(return_value=AsyncChannelMock())
streaming_channel_manager_mock.remove_channel = AsyncMock(return_value=None)
streaming_channel_manager_mock.publish = AsyncMock(return_value=None)
streaming_channel_manager_mock.complete_channel = AsyncMock(return_value=None)
sys.modules["services.streaming_channel"].streaming_channel_manager = streaming_channel_manager_mock

setattr(services_module, "skill_service", sys.modules["services.skill_service"])

import importlib.util
from pathlib import Path

_asset_owner_path = Path(__file__).resolve().parents[3] / "backend" / "services" / "asset_owner_visibility.py"
_asset_owner_spec = importlib.util.spec_from_file_location(
    "services.asset_owner_visibility", _asset_owner_path
)
_asset_owner_mod = importlib.util.module_from_spec(_asset_owner_spec)
_asset_owner_spec.loader.exec_module(_asset_owner_mod)
sys.modules["services.asset_owner_visibility"] = _asset_owner_mod
setattr(services_module, "asset_owner_visibility", _asset_owner_mod)

sys.modules["agents"] = MagicMock()
sys.modules["agents.create_agent_info"] = MagicMock()
sys.modules["agents.agent_run_manager"] = MagicMock()
sys.modules["agents.preprocess_manager"] = MagicMock()

mock_create_agent_info = MagicMock()
mock_create_agent_info.create_tool_config_list = AsyncMock(return_value=[])
sys.modules["agents.create_agent_info"].create_agent_info = mock_create_agent_info

sys.modules["utils"] = MagicMock()
sys.modules["utils.auth_utils"] = MagicMock()
sys.modules["utils.thread_utils"] = MagicMock()
sys.modules["utils.context_utils"] = MagicMock()


def mock_convert_list_to_string(items):
    if not items:
        return ""
    return ",".join(str(item) for item in items)


sys.modules["utils.str_utils"] = MagicMock()
sys.modules["utils.str_utils"].convert_list_to_string = mock_convert_list_to_string
sys.modules["utils.str_utils"].convert_string_to_list = lambda s: s.split(",") if s else []
sys.modules["utils.config_utils"] = MagicMock()
sys.modules["utils.prompt_template_utils"] = MagicMock()
sys.modules["utils.llm_utils"] = MagicMock()
sys.modules["utils.monitoring"] = MagicMock()

# =============================================================================
# STEP 2: Create mock objects for database clients
# =============================================================================

mock_engine = MagicMock()
mock_session_maker = MagicMock()
mock_db_session = MagicMock()
mock_session_maker.return_value = mock_db_session

mock_postgres_client = MagicMock()
mock_postgres_client.session_maker = mock_session_maker

minio_client_mock = MagicMock()


def mock_get_db_session(db_session=None):
    session = mock_db_session if db_session is None else db_session
    from contextlib import contextmanager

    @contextmanager
    def _mock_context():
        yield session

    return _mock_context()


mock_backend_database_client = MagicMock()
mock_backend_database_client.PostgresClient = MagicMock(return_value=mock_postgres_client)
mock_backend_database_client.get_db_session = mock_get_db_session
mock_backend_database_client.MinioClient = MagicMock(return_value=minio_client_mock)
mock_backend_database_client.db_client = mock_postgres_client
sys.modules["backend.database.client"] = mock_backend_database_client

sys.modules["nexent.storage.storage_client_factory"].create_storage_client_from_config = MagicMock(return_value=MagicMock())

# =============================================================================
# STEP 3: Import backend modules after all mocks are in place
# =============================================================================

monitoring_manager_mock = MagicMock()


def pass_through_decorator(*args, **kwargs):
    def decorator(func):
        return func

    return decorator


monitoring_manager_mock.monitor_endpoint = pass_through_decorator
monitoring_manager_mock.monitor_llm_call = pass_through_decorator
monitoring_manager_mock.setup_fastapi_app = MagicMock(return_value=True)
monitoring_manager_mock.configure = MagicMock()
monitoring_manager_mock.add_span_event = MagicMock()
monitoring_manager_mock.set_span_attributes = MagicMock()

sys.modules["nexent.monitor"].get_monitoring_manager = lambda: monitoring_manager_mock
sys.modules["nexent.monitor"].monitoring_manager = monitoring_manager_mock
sys.modules["utils.monitoring"].monitoring_manager = monitoring_manager_mock
sys.modules["utils.monitoring"].setup_fastapi_app = MagicMock(return_value=True)

sys.modules["nexent.storage.minio_config"].MinIOStorageConfig = type(
    "MinIOStorageConfig", (), {"validate": lambda self: None}
)

import backend.services.agent_service as agent_service

from backend.services.agent_service import (
    export_agents_batch_impl,
    import_agents_batch_impl,
    _sanitize_agent_folder_name,
    _write_export_result_to_zip,
    _discover_agent_folders,
    _collect_skill_entries,
    _extract_agent_metadata,
    _build_import_failure_item,
    _import_single_agent_from_zip,
)

from consts.model import (
    ExportAndImportAgentInfo,
    ExportAndImportDataFormat,
    MCPInfo,
    SkillZipEntry,
)
from consts.exceptions import SkillDuplicateError


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def reset_mocks():
    yield


@pytest.fixture
def mock_authorization():
    return "Bearer test_token"


@pytest.fixture
def mock_user_info():
    return ("test_user_id", "test_tenant_id", "en")


@pytest.fixture
def sample_agent_payload():
    return {
        "agent_id": 1,
        "agent_info": {
            "1": {
                "agent_id": 1,
                "tenant_id": "test_tenant",
                "name": "test_agent",
                "display_name": "Test Agent",
                "description": "A test agent",
                "business_description": "",
                "author": "test_author",
                "max_steps": 10,
                "provide_run_summary": False,
                "enabled": True,
                "tools": [],
                "managed_agents": [],
            }
        },
        "mcp_info": [],
    }


@pytest.fixture
def sample_export_result():
    agent_json_bytes = json.dumps(
        {
            "agent_id": 1,
            "agent_info": {
                "1": {
                    "agent_id": 1,
                    "tenant_id": "test_tenant",
                    "name": "test_agent",
                    "display_name": "Test Agent",
                    "description": "A test agent",
                    "business_description": "",
                    "author": "test_author",
                    "max_steps": 10,
                    "provide_run_summary": False,
                    "enabled": True,
                    "tools": [],
                    "managed_agents": [],
                }
            },
            "mcp_info": [],
        }
    ).encode("utf-8")

    inner_buffer = io.BytesIO()
    with zipfile.ZipFile(inner_buffer, "w", zipfile.ZIP_DEFLATED) as inner_zf:
        inner_zf.writestr("agent.json", agent_json_bytes)
        inner_zf.writestr(
            "skills/test_skill.zip",
            b"fake_skill_zip_content",
        )

    return {
        "_zip": True,
        "data": inner_buffer.getvalue(),
        "filename": "agent_1_export.zip",
    }


# =============================================================================
# Tests for _sanitize_agent_folder_name
# =============================================================================


class TestSanitizeAgentFolderName:

    def test_normal_name(self):
        used = set()
        result = _sanitize_agent_folder_name("MyAgent", 1, used)
        assert result == "MyAgent"
        assert result in used

    def test_name_with_special_characters(self):
        used = set()
        result = _sanitize_agent_folder_name("My Agent!@#", 1, used)
        assert result == "My_Agent"
        assert result in used

    def test_empty_name_uses_default(self):
        used = set()
        result = _sanitize_agent_folder_name("", 42, used)
        assert result == "agent_42"
        assert result in used

    def test_none_name_uses_default(self):
        used = set()
        result = _sanitize_agent_folder_name(None, 42, used)
        assert result == "agent_42"
        assert result in used

    def test_duplicate_name_gets_suffix(self):
        used = set()
        _sanitize_agent_folder_name("MyAgent", 1, used)
        result = _sanitize_agent_folder_name("MyAgent", 2, used)
        assert result == "MyAgent_2"
        assert result in used

    def test_multiple_duplicates_get_incremental_suffix(self):
        used = set()
        _sanitize_agent_folder_name("MyAgent", 1, used)
        r2 = _sanitize_agent_folder_name("MyAgent", 2, used)
        r3 = _sanitize_agent_folder_name("MyAgent", 3, used)
        r4 = _sanitize_agent_folder_name("MyAgent", 4, used)
        assert r2 == "MyAgent_2"
        assert r3 == "MyAgent_3"
        assert r4 == "MyAgent_4"

    def test_name_with_only_special_chars(self):
        used = set()
        result = _sanitize_agent_folder_name("!@#$%", 1, used)
        assert result == "agent_1"
        assert result in used

    def test_unicode_name(self):
        used = set()
        result = _sanitize_agent_folder_name("我的智能体", 1, used)
        assert result == "agent_1"
        assert result in used

    def test_underscore_trimming(self):
        used = set()
        result = _sanitize_agent_folder_name("__MyAgent__", 1, used)
        assert result == "MyAgent"
        assert result in used


# =============================================================================
# Tests for _write_export_result_to_zip
# =============================================================================


class TestWriteExportResultToZip:

    def test_write_zip_result_with_skills(self, sample_export_result):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            _write_export_result_to_zip(zf, "agents/test_agent", sample_export_result)

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            assert "agents/test_agent/agent.json" in names
            assert "agents/test_agent/skills/test_skill.zip" in names

    def test_write_plain_dict_result(self):
        buffer = io.BytesIO()
        plain_result = {"key": "value", "name": "test"}
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            _write_export_result_to_zip(zf, "agents/plain_agent", plain_result)

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            assert "agents/plain_agent/agent.json" in names
            content = json.loads(zf.read("agents/plain_agent/agent.json").decode("utf-8"))
            assert content == plain_result

    def test_write_dict_without_zip_flag(self, sample_export_result):
        buffer = io.BytesIO()
        result_without_flag = {"key": "value", "name": "test"}
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            _write_export_result_to_zip(zf, "agents/no_zip", result_without_flag)

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            assert "agents/no_zip/agent.json" in names

    def test_write_zip_result_empty_inner_zip(self):
        buffer = io.BytesIO()
        inner_buffer = io.BytesIO()
        with zipfile.ZipFile(inner_buffer, "w") as inner_zf:
            inner_zf.writestr("agent.json", '{"agent_id": 1}')

        result = {"_zip": True, "data": inner_buffer.getvalue()}
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            _write_export_result_to_zip(zf, "agents/no_skills", result)

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            assert "agents/no_skills/agent.json" in names
            content = json.loads(zf.read("agents/no_skills/agent.json").decode("utf-8"))
            assert content == {"agent_id": 1}


# =============================================================================
# Tests for _discover_agent_folders
# =============================================================================


class TestDiscoverAgentFolders:

    def test_discover_from_manifest(self):
        manifest = {
            "version": "1.0",
            "exported_at": "",
            "agents": [
                {"folder": "agents/agent_one", "agent_id": 1},
                {"folder": "agents/agent_two", "agent_id": 2},
            ],
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("agents/agent_one/agent.json", "{}")
            zf.writestr("agents/agent_two/agent.json", "{}")

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            folders = _discover_agent_folders(zf, names)
            assert folders == ["agents/agent_one", "agents/agent_two"]

    def test_discover_fallback_to_scanning(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("agents/alpha/agent.json", "{}")
            zf.writestr("agents/beta/agent.json", "{}")

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            folders = _discover_agent_folders(zf, names)
            assert "agents/alpha" in folders
            assert "agents/beta" in folders

    def test_discover_skips_non_agent_files(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("agents/alpha/agent.json", "{}")
            zf.writestr("agents/alpha/skills/test.zip", b"test")
            zf.writestr("readme.txt", "some text")

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            folders = _discover_agent_folders(zf, names)
            assert folders == ["agents/alpha"]

    def test_discover_empty_zip(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps({"version": "1.0", "agents": []}))

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            folders = _discover_agent_folders(zf, names)
            assert folders == []

    def test_discover_manifest_parsing_error(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", "invalid json{{{")

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            with pytest.raises(ValueError, match="Failed to parse batch manifest"):
                _discover_agent_folders(zf, names)

    def test_discover_manifest_with_missing_folder_key(self):
        manifest = {
            "version": "1.0",
            "agents": [
                {"agent_id": 1},
                {"folder": "agents/valid"},
                "not_a_dict",
            ],
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest))

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            folders = _discover_agent_folders(zf, names)
            assert folders == ["agents/valid"]

    def test_discover_scanning_deduplicates_folders(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("agents/shared/agent.json", "{}")
            zf.writestr("agents/shared/skills/skill1.zip", b"test")
            zf.writestr("agents/shared/skills/skill2.zip", b"test")

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            folders = _discover_agent_folders(zf, names)
            assert folders == ["agents/shared"]


# =============================================================================
# Tests for _collect_skill_entries
# =============================================================================


class TestCollectSkillEntries:

    def test_collect_skills_from_folder(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("agents/test/agent.json", "{}")
            zf.writestr("agents/test/skills/skill_a.zip", b"skill_a_data")
            zf.writestr("agents/test/skills/skill_b.zip", b"skill_b_data")
            zf.writestr("agents/test/other_file.txt", "text")

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            entries = _collect_skill_entries(zf, names, "agents/test")
            assert len(entries) == 2
            assert entries[0].skill_name == "skill_a"
            assert entries[1].skill_name == "skill_b"
            assert isinstance(entries[0].skill_zip_base64, str)

    def test_collect_no_skills(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("agents/test/agent.json", "{}")

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            entries = _collect_skill_entries(zf, names, "agents/test")
            assert entries == []

    def test_collect_skills_empty_folder(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            pass

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            entries = _collect_skill_entries(zf, names, "agents/nonexistent")
            assert entries == []

    def test_collect_skill_name_parsing(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("agents/test/skills/my_skill.zip", b"data")

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            entries = _collect_skill_entries(zf, names, "agents/test")
            assert len(entries) == 1
            assert entries[0].skill_name == "my_skill"

    def test_collect_skill_base64_encoding(self):
        buffer = io.BytesIO()
        skill_content = b"test_skill_content"
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("agents/test/skills/enc.zip", skill_content)

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            entries = _collect_skill_entries(zf, names, "agents/test")
            decoded = base64.b64decode(entries[0].skill_zip_base64)
            assert decoded == skill_content


# =============================================================================
# Tests for _extract_agent_metadata
# =============================================================================


class TestExtractAgentMetadata:

    def test_extract_with_name_and_display_name(self, sample_agent_payload):
        agent_name, display_name = _extract_agent_metadata(sample_agent_payload, "agents/test")
        assert agent_name == "test_agent"
        assert display_name == "Test Agent"

    def test_extract_fallback_to_folder(self):
        payload = {"agent_id": 1, "agent_info": {}, "mcp_info": []}
        agent_name, display_name = _extract_agent_metadata(payload, "agents/my_folder")
        assert agent_name == "agents/my_folder"
        assert display_name == "agents/my_folder"

    def test_extract_display_name_fallback_to_name(self):
        payload = {
            "agent_id": 1,
            "agent_info": {
                "1": {
                    "name": "agent_name_only",
                }
            },
        }
        agent_name, display_name = _extract_agent_metadata(payload, "agents/test")
        assert agent_name == "agent_name_only"
        assert display_name == "agent_name_only"

    def test_extract_empty_agent_info(self):
        payload = {"agent_id": 1, "agent_info": {"1": {}}, "mcp_info": []}
        agent_name, display_name = _extract_agent_metadata(payload, "agents/fallback")
        assert agent_name == "agents/fallback"
        assert display_name == "agents/fallback"

    def test_extract_with_none_values(self):
        payload = {
            "agent_id": 1,
            "agent_info": {
                "1": {"name": None, "display_name": None}
            },
        }
        agent_name, display_name = _extract_agent_metadata(payload, "agents/fallback")
        assert agent_name == "agents/fallback"
        assert display_name == "agents/fallback"


# =============================================================================
# Tests for _build_import_failure_item
# =============================================================================


class TestBuildImportFailureItem:

    def test_build_failure_item_with_valid_json(self, sample_agent_payload):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "agents/test/agent.json",
                json.dumps(sample_agent_payload).encode("utf-8"),
            )

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            item = _build_import_failure_item(
                zf, "agents/test/agent.json", "agents/test", "Test error"
            )
            assert item["name"] == "test_agent"
            assert item["display_name"] == "Test Agent"
            assert item["success"] is False
            assert item["error"] == "Test error"

    def test_build_failure_item_with_invalid_json(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("agents/test/agent.json", "not valid json")

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            item = _build_import_failure_item(
                zf, "agents/test/agent.json", "agents/test", "Parse error"
            )
            assert item["name"] == "agents/test"
            assert item["display_name"] is None
            assert item["success"] is False
            assert item["error"] == "Parse error"

    def test_build_failure_item_missing_file(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            pass

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            item = _build_import_failure_item(
                zf, "agents/nonexistent/agent.json", "agents/nonexistent", "Missing"
            )
            assert item["name"] == "agents/nonexistent"
            assert item["display_name"] is None
            assert item["success"] is False
            assert item["error"] == "Missing"


# =============================================================================
# Tests for _import_single_agent_from_zip
# =============================================================================


class TestImportSingleAgentFromZip:

    @pytest.mark.asyncio
    async def test_import_with_skills_success(self, mock_authorization):
        payload = {
            "agent_id": 1,
            "agent_info": {
                "1": {
                    "agent_id": 1,
                    "tenant_id": "test_tenant",
                    "name": "test_agent",
                    "display_name": "Test Agent",
                    "description": "desc",
                    "business_description": "",
                    "author": "author",
                    "max_steps": 10,
                    "provide_run_summary": False,
                    "enabled": True,
                    "tools": [],
                    "managed_agents": [],
                }
            },
            "mcp_info": [],
        }

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "agents/test/agent.json",
                json.dumps(payload).encode("utf-8"),
            )
            zf.writestr("agents/test/skills/skill1.zip", b"skill_data")

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            mock_import = AsyncMock(return_value={"agent_id": 1})
            with patch(
                "backend.services.agent_service.import_agent_with_skills_impl",
                mock_import,
            ):
                item = await _import_single_agent_from_zip(
                    zf, names, "agents/test", mock_authorization
                )

            assert item["name"] == "test_agent"
            assert item["display_name"] == "Test Agent"
            assert item["success"] is True
            mock_import.assert_called_once()

    @pytest.mark.asyncio
    async def test_import_without_skills_success(self, mock_authorization):
        payload = {
            "agent_id": 2,
            "agent_info": {
                "2": {
                    "agent_id": 2,
                    "tenant_id": "test_tenant",
                    "name": "simple_agent",
                    "display_name": "Simple Agent",
                    "description": "desc",
                    "business_description": "",
                    "author": "author",
                    "max_steps": 5,
                    "provide_run_summary": False,
                    "enabled": True,
                    "tools": [],
                    "managed_agents": [],
                }
            },
            "mcp_info": [],
        }

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "agents/simple/agent.json",
                json.dumps(payload).encode("utf-8"),
            )

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            mock_import = AsyncMock(return_value={"agent_id": 2})
            with patch(
                "backend.services.agent_service.import_agent_impl",
                mock_import,
            ):
                item = await _import_single_agent_from_zip(
                    zf, names, "agents/simple", mock_authorization
                )

            assert item["name"] == "simple_agent"
            assert item["display_name"] == "Simple Agent"
            assert item["success"] is True
            mock_import.assert_called_once()

    @pytest.mark.asyncio
    async def test_import_missing_agent_json(self, mock_authorization):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("agents/test/some_other_file.txt", "content")

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            item = await _import_single_agent_from_zip(
                zf, names, "agents/test", mock_authorization
            )

            assert item["success"] is False
            assert "agent.json not found" in item["error"]
            assert item["name"] == "agents/test"

    @pytest.mark.asyncio
    async def test_import_with_invalid_payload(self, mock_authorization):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "agents/bad/agent.json",
                '{"invalid": "payload"}'.encode("utf-8"),
            )

        buffer.seek(0)
        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            with pytest.raises(Exception):
                await _import_single_agent_from_zip(
                    zf, names, "agents/bad", mock_authorization
                )


# =============================================================================
# Tests for export_agents_batch_impl
# =============================================================================


class TestExportAgentsBatchImpl:

    @pytest.mark.asyncio
    async def test_export_single_agent(self, mock_authorization, mock_user_info, sample_export_result):
        mock_export = AsyncMock(return_value=sample_export_result)
        with patch(
            "backend.services.agent_service.get_current_user_info",
            return_value=mock_user_info,
        ), patch(
            "backend.services.agent_service.search_agent_info_by_agent_id",
            return_value={
                "agent_id": 1,
                "name": "test_agent",
                "display_name": "Test Agent",
            },
        ), patch(
            "backend.services.agent_service.export_agent_with_skills_impl",
            mock_export,
        ):
            result = await export_agents_batch_impl([1], mock_authorization)

            assert result["_zip"] is True
            assert "data" in result
            assert result["filename"] == "agents_batch_export.zip"

            zip_bytes = result["data"]
            with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
                names = zf.namelist()
                assert "manifest.json" in names
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                assert len(manifest["agents"]) == 1
                assert manifest["agents"][0]["agent_id"] == 1

    @pytest.mark.asyncio
    async def test_export_multiple_agents(self, mock_authorization, mock_user_info, sample_export_result):
        mock_export = AsyncMock(return_value=sample_export_result)
        with patch(
            "backend.services.agent_service.get_current_user_info",
            return_value=mock_user_info,
        ), patch(
            "backend.services.agent_service.search_agent_info_by_agent_id",
            side_effect=[
                {"agent_id": 1, "name": "agent_one", "display_name": "Agent One"},
                {"agent_id": 2, "name": "agent_two", "display_name": "Agent Two"},
            ],
        ), patch(
            "backend.services.agent_service.export_agent_with_skills_impl",
            mock_export,
        ):
            result = await export_agents_batch_impl([1, 2], mock_authorization)

            zip_bytes = result["data"]
            with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                assert len(manifest["agents"]) == 2

    @pytest.mark.asyncio
    async def test_export_agent_not_found(self, mock_authorization, mock_user_info):
        with patch(
            "backend.services.agent_service.get_current_user_info",
            return_value=mock_user_info,
        ), patch(
            "backend.services.agent_service.search_agent_info_by_agent_id",
            return_value=None,
        ):
            result = await export_agents_batch_impl([999], mock_authorization)

            zip_bytes = result["data"]
            with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                assert len(manifest["agents"]) == 0

    @pytest.mark.asyncio
    async def test_export_empty_agent_list(self, mock_authorization, mock_user_info):
        with patch(
            "backend.services.agent_service.get_current_user_info",
            return_value=mock_user_info,
        ):
            result = await export_agents_batch_impl([], mock_authorization)

            assert result["_zip"] is True
            zip_bytes = result["data"]
            with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                assert len(manifest["agents"]) == 0

    @pytest.mark.asyncio
    async def test_export_with_special_characters_in_name(self, mock_authorization, mock_user_info, sample_export_result):
        mock_export = AsyncMock(return_value=sample_export_result)
        with patch(
            "backend.services.agent_service.get_current_user_info",
            return_value=mock_user_info,
        ), patch(
            "backend.services.agent_service.search_agent_info_by_agent_id",
            return_value={
                "agent_id": 1,
                "name": "My Agent!@#",
                "display_name": "Test",
            },
        ), patch(
            "backend.services.agent_service.export_agent_with_skills_impl",
            mock_export,
        ):
            result = await export_agents_batch_impl([1], mock_authorization)

            zip_bytes = result["data"]
            with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                folder = manifest["agents"][0]["folder"]
                assert "My_Agent" in folder

    @pytest.mark.asyncio
    async def test_export_with_duplicate_names(self, mock_authorization, mock_user_info, sample_export_result):
        mock_export = AsyncMock(return_value=sample_export_result)
        with patch(
            "backend.services.agent_service.get_current_user_info",
            return_value=mock_user_info,
        ), patch(
            "backend.services.agent_service.search_agent_info_by_agent_id",
            side_effect=[
                {"agent_id": 1, "name": "same_name", "display_name": "First"},
                {"agent_id": 2, "name": "same_name", "display_name": "Second"},
            ],
        ), patch(
            "backend.services.agent_service.export_agent_with_skills_impl",
            mock_export,
        ):
            result = await export_agents_batch_impl([1, 2], mock_authorization)

            zip_bytes = result["data"]
            with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                folders = [a["folder"] for a in manifest["agents"]]
                assert len(folders) == 2
                assert folders[0] != folders[1]


# =============================================================================
# Tests for import_agents_batch_impl
# =============================================================================


class TestImportAgentsBatchImpl:

    def _create_batch_zip(self, agents_data, include_manifest=True):
        buffer = io.BytesIO()
        manifest_agents = []

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, (folder_name, payload) in enumerate(agents_data.items()):
                folder = f"agents/{folder_name}"
                json_payload = {k: v for k, v in payload.items() if k != "_skills"}
                zf.writestr(
                    f"{folder}/agent.json",
                    json.dumps(json_payload).encode("utf-8"),
                )
                if payload.get("_skills"):
                    for skill_name, skill_data in payload["_skills"].items():
                        zf.writestr(
                            f"{folder}/skills/{skill_name}.zip",
                            skill_data,
                        )
                manifest_agents.append({
                    "folder": folder,
                    "agent_id": payload["agent_id"],
                    "name": payload["agent_info"][str(payload["agent_id"])]["name"],
                    "display_name": payload["agent_info"][str(payload["agent_id"])].get("display_name"),
                })

            if include_manifest:
                manifest = {
                    "version": "1.0",
                    "exported_at": "",
                    "agents": manifest_agents,
                }
                zf.writestr("manifest.json", json.dumps(manifest))

        return buffer.getvalue()

    @pytest.mark.asyncio
    async def test_import_single_agent_success(self, mock_authorization):
        agents_data = {
            "test_agent": {
                "agent_id": 1,
                "agent_info": {
                    "1": {
                        "agent_id": 1,
                        "tenant_id": "test_tenant",
                        "name": "test_agent",
                        "display_name": "Test Agent",
                        "description": "desc",
                        "business_description": "",
                        "author": "author",
                        "max_steps": 10,
                        "provide_run_summary": False,
                        "enabled": True,
                        "tools": [],
                        "managed_agents": [],
                    }
                },
                "mcp_info": [],
            }
        }

        zip_bytes = self._create_batch_zip(agents_data)

        mock_import = AsyncMock(return_value={"agent_id": 1})
        with patch(
            "backend.services.agent_service.import_agent_impl",
            mock_import,
        ):
            result = await import_agents_batch_impl(zip_bytes, mock_authorization)

            assert result["total"] == 1
            assert result["success_count"] == 1
            assert result["failed_count"] == 0
            assert len(result["items"]) == 1
            assert result["items"][0]["success"] is True

    @pytest.mark.asyncio
    async def test_import_multiple_agents_success(self, mock_authorization):
        agents_data = {
            "agent_one": {
                "agent_id": 1,
                "agent_info": {
                    "1": {
                        "agent_id": 1,
                        "tenant_id": "test_tenant",
                        "name": "agent_one",
                        "display_name": "Agent One",
                        "description": "desc",
                        "business_description": "",
                        "author": "author",
                        "max_steps": 10,
                        "provide_run_summary": False,
                        "enabled": True,
                        "tools": [],
                        "managed_agents": [],
                    }
                },
                "mcp_info": [],
            },
            "agent_two": {
                "agent_id": 2,
                "agent_info": {
                    "2": {
                        "agent_id": 2,
                        "tenant_id": "test_tenant",
                        "name": "agent_two",
                        "display_name": "Agent Two",
                        "description": "desc",
                        "business_description": "",
                        "author": "author",
                        "max_steps": 5,
                        "provide_run_summary": False,
                        "enabled": True,
                        "tools": [],
                        "managed_agents": [],
                    }
                },
                "mcp_info": [],
            },
        }

        zip_bytes = self._create_batch_zip(agents_data)

        mock_import = AsyncMock(return_value={"agent_id": 1})
        with patch(
            "backend.services.agent_service.import_agent_impl",
            mock_import,
        ):
            result = await import_agents_batch_impl(zip_bytes, mock_authorization)

            assert result["total"] == 2
            assert result["success_count"] == 2
            assert result["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_import_with_skills(self, mock_authorization):
        skill_data = b"fake_skill_zip_data"
        agents_data = {
            "agent_with_skill": {
                "agent_id": 1,
                "agent_info": {
                    "1": {
                        "agent_id": 1,
                        "tenant_id": "test_tenant",
                        "name": "agent_with_skill",
                        "display_name": "Agent With Skill",
                        "description": "desc",
                        "business_description": "",
                        "author": "author",
                        "max_steps": 10,
                        "provide_run_summary": False,
                        "enabled": True,
                        "tools": [],
                        "managed_agents": [],
                    }
                },
                "mcp_info": [],
                "_skills": {"my_skill": skill_data},
            }
        }

        zip_bytes = self._create_batch_zip(agents_data)

        mock_import = AsyncMock(return_value={"agent_id": 1})
        with patch(
            "backend.services.agent_service.import_agent_with_skills_impl",
            mock_import,
        ):
            result = await import_agents_batch_impl(zip_bytes, mock_authorization)

            assert result["total"] == 1
            assert result["success_count"] == 1
            mock_import.assert_called_once()

    @pytest.mark.asyncio
    async def test_import_invalid_zip_file(self, mock_authorization):
        with pytest.raises(ValueError, match="Invalid batch export ZIP file"):
            await import_agents_batch_impl(b"not a zip file", mock_authorization)

    @pytest.mark.asyncio
    async def test_import_with_skill_duplicate_error(self, mock_authorization):
        agents_data = {
            "agent_with_skill": {
                "agent_id": 1,
                "agent_info": {
                    "1": {
                        "agent_id": 1,
                        "tenant_id": "test_tenant",
                        "name": "agent_with_skill",
                        "display_name": "Agent With Skill",
                        "description": "desc",
                        "business_description": "",
                        "author": "author",
                        "max_steps": 10,
                        "provide_run_summary": False,
                        "enabled": True,
                        "tools": [],
                        "managed_agents": [],
                    }
                },
                "mcp_info": [],
                "_skills": {"dup_skill": b"skill_data"},
            }
        }

        zip_bytes = self._create_batch_zip(agents_data)

        mock_import = AsyncMock(
            side_effect=SkillDuplicateError(["dup_skill"])
        )
        with patch(
            "backend.services.agent_service.import_agent_with_skills_impl",
            mock_import,
        ):
            result = await import_agents_batch_impl(zip_bytes, mock_authorization)

            assert result["total"] == 1
            assert result["success_count"] == 0
            assert result["failed_count"] == 1
            assert result["items"][0]["success"] is False
            assert "Skill name conflict" in result["items"][0]["error"]

    @pytest.mark.asyncio
    async def test_import_with_general_exception(self, mock_authorization):
        agents_data = {
            "failing_agent": {
                "agent_id": 1,
                "agent_info": {
                    "1": {
                        "agent_id": 1,
                        "tenant_id": "test_tenant",
                        "name": "failing_agent",
                        "display_name": "Failing Agent",
                        "description": "desc",
                        "business_description": "",
                        "author": "author",
                        "max_steps": 10,
                        "provide_run_summary": False,
                        "enabled": True,
                        "tools": [],
                        "managed_agents": [],
                    }
                },
                "mcp_info": [],
            }
        }

        zip_bytes = self._create_batch_zip(agents_data)

        mock_import = AsyncMock(side_effect=Exception("Import failed"))
        with patch(
            "backend.services.agent_service.import_agent_impl",
            mock_import,
        ):
            result = await import_agents_batch_impl(zip_bytes, mock_authorization)

            assert result["total"] == 1
            assert result["success_count"] == 0
            assert result["failed_count"] == 1
            assert result["items"][0]["success"] is False
            assert result["items"][0]["error"] == "Import failed"

    @pytest.mark.asyncio
    async def test_import_partial_success(self, mock_authorization):
        agents_data = {
            "good_agent": {
                "agent_id": 1,
                "agent_info": {
                    "1": {
                        "agent_id": 1,
                        "tenant_id": "test_tenant",
                        "name": "good_agent",
                        "display_name": "Good Agent",
                        "description": "desc",
                        "business_description": "",
                        "author": "author",
                        "max_steps": 10,
                        "provide_run_summary": False,
                        "enabled": True,
                        "tools": [],
                        "managed_agents": [],
                    }
                },
                "mcp_info": [],
            },
            "bad_agent": {
                "agent_id": 2,
                "agent_info": {
                    "2": {
                        "agent_id": 2,
                        "tenant_id": "test_tenant",
                        "name": "bad_agent",
                        "display_name": "Bad Agent",
                        "description": "desc",
                        "business_description": "",
                        "author": "author",
                        "max_steps": 5,
                        "provide_run_summary": False,
                        "enabled": True,
                        "tools": [],
                        "managed_agents": [],
                    }
                },
                "mcp_info": [],
            },
        }

        zip_bytes = self._create_batch_zip(agents_data)

        mock_import = AsyncMock(
            side_effect=[
                {"agent_id": 1},
                Exception("Import failed for agent 2"),
            ]
        )
        with patch(
            "backend.services.agent_service.import_agent_impl",
            mock_import,
        ):
            result = await import_agents_batch_impl(zip_bytes, mock_authorization)

            assert result["total"] == 2
            assert result["success_count"] == 1
            assert result["failed_count"] == 1

    @pytest.mark.asyncio
    async def test_import_empty_batch(self, mock_authorization):
        agents_data = {}
        zip_bytes = self._create_batch_zip(agents_data)

        result = await import_agents_batch_impl(zip_bytes, mock_authorization)

        assert result["total"] == 0
        assert result["success_count"] == 0
        assert result["failed_count"] == 0
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_import_fallback_to_folder_scanning(self, mock_authorization):
        agents_data = {
            "test_agent": {
                "agent_id": 1,
                "agent_info": {
                    "1": {
                        "agent_id": 1,
                        "tenant_id": "test_tenant",
                        "name": "test_agent",
                        "display_name": "Test Agent",
                        "description": "desc",
                        "business_description": "",
                        "author": "author",
                        "max_steps": 10,
                        "provide_run_summary": False,
                        "enabled": True,
                        "tools": [],
                        "managed_agents": [],
                    }
                },
                "mcp_info": [],
            }
        }

        zip_bytes = self._create_batch_zip(agents_data, include_manifest=False)

        mock_import = AsyncMock(return_value={"agent_id": 1})
        with patch(
            "backend.services.agent_service.import_agent_impl",
            mock_import,
        ):
            result = await import_agents_batch_impl(zip_bytes, mock_authorization)

            assert result["total"] == 1
            assert result["success_count"] == 1

    @pytest.mark.asyncio
    async def test_import_agent_with_missing_agent_json(self, mock_authorization):
        buffer = io.BytesIO()
        manifest = {
            "version": "1.0",
            "exported_at": "",
            "agents": [
                {
                    "folder": "agents/test_agent",
                    "agent_id": 1,
                    "name": "test_agent",
                    "display_name": "Test Agent",
                }
            ],
        }
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("agents/test_agent/some_other_file.txt", "content")

        zip_bytes = buffer.getvalue()

        result = await import_agents_batch_impl(zip_bytes, mock_authorization)

        assert result["total"] == 1
        assert result["success_count"] == 0
        assert result["failed_count"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["success"] is False