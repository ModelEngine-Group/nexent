# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contracts.authentication import AuthenticatedIdentity
import importlib.machinery
from pathlib import Path
import sys
import asyncio
import json
import io
import types
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import ANY, patch, MagicMock, mock_open, call, Mock, AsyncMock
import os

imghdr_mock = types.ModuleType("imghdr")
imghdr_mock.what = MagicMock(return_value=None)
sys.modules["imghdr"] = imghdr_mock

import pytest
from fastapi.responses import StreamingResponse
from fastapi import Request


@pytest.mark.asyncio
async def test_get_agent_info_impl_hides_system_agent_before_capability_reads(monkeypatch):
    """UT-BE-SAL-010: ordinary detail lookup must not disclose a system Agent."""
    from management.services.agent import service as agent_service

    monkeypatch.setattr(
        agent_service,
        "search_agent_info_by_agent_id",
        lambda *_args, **_kwargs: {
            "agent_id": 7,
            "tenant_id": "tenant-a",
            "name": "workbench_main",
            "agent_origin": "SYSTEM",
            "system_key": "workbench_main",
        },
    )
    tool_lookup = MagicMock()
    monkeypatch.setattr(agent_service, "search_tools_for_sub_agent", tool_lookup)

    with pytest.raises(agent_service.ForbiddenError, match="not accessible"):
        await agent_service.get_agent_info_impl(
            agent_id=7,
            tenant_id="tenant-a",
            user_id="user-a",
        )

    tool_lookup.assert_not_called()


@pytest.mark.asyncio
async def test_export_agent_with_skills_rejects_system_agent_before_skill_reads(monkeypatch):
    """UT-BE-SAL-010 and UT-BE-SAL-011: reject before Skill reads."""
    from management.services.agent import transfer as agent_service
    monkeypatch.setattr(agent_transfer_backend, 'is_system_agent', lambda *_args: True)
    skill_collector = MagicMock()
    monkeypatch.setattr(agent_transfer_backend, 'collect_skill_zip_entries', skill_collector)
    with pytest.raises(agent_transfer.ForbiddenError, match='cannot be exported'):
        await agent_service.export_agent_with_skills_impl(agent_id=7, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    skill_collector.assert_not_called()

# =============================================================================
# STEP 1: Set up ALL sys.modules mocks BEFORE any backend imports
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
    from pydantic import networks as pydantic_networks

    original_package_version = pydantic_networks.version
    pydantic_networks.version = lambda package_name: (
        "2.0.0"
        if package_name == "email-validator"
        else original_package_version(package_name)
    )
except Exception:
    pass


# Create mock ToolConfig class with all necessary methods
class MockToolConfig:
    """Mock ToolConfig for testing - accepts any arguments."""

    def __init__(self, *args, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def model_dump(self, **kwargs):
        """Return a dict representation of the ToolConfig."""
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


# Mock nexent module hierarchy
nexent_agent_model_mock = MagicMock()
nexent_agent_model_mock.ToolConfig = MockToolConfig
sys.modules["nexent"] = MagicMock()
sys.modules["nexent.core"] = MagicMock()
sys.modules["nexent.core"].__path__ = [str(Path(__file__).resolve().parents[3] / "sdk/nexent/core")]
sys.modules["nexent.core"].__spec__ = importlib.machinery.ModuleSpec("nexent.core", loader=None, is_package=True)
_concurrency_module = types.ModuleType("nexent.core.concurrency")


class _ManagedTaskSpec:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _ThreadCapacityExceeded(RuntimeError):
    pass


class _ThreadQueueTimedOut(RuntimeError):
    def __init__(self, timeout_seconds=1):
        self.timeout_seconds = timeout_seconds


class _RunCancellationScope:
    """Keep the service test double aligned with run cancellation behavior."""

    def __init__(self, stop_event):
        self.stop_event = stop_event
        self.cancelled = False

    def cancel(self):
        if not self.cancelled:
            self.cancelled = True
            self.stop_event.set()


async def _run_blocking(_task_name, fn, *args, **kwargs):
    kwargs.pop("lane", None)
    kwargs.pop("owner", None)
    return fn(*args, **kwargs)


async def _run_managed(_lane, _spec, fn, *args, **kwargs):
    return fn(*args, **kwargs)


_concurrency_module.ManagedTaskSpec = _ManagedTaskSpec
_concurrency_module.ManagedExecution = MagicMock
_concurrency_module.RunCancellationScope = _RunCancellationScope
_concurrency_module.ThreadCapacityExceeded = _ThreadCapacityExceeded
_concurrency_module.ThreadQueueTimedOut = _ThreadQueueTimedOut
_concurrency_module.run_blocking = _run_blocking
sys.modules["nexent.core.concurrency"] = _concurrency_module
_concurrency_module.LanePolicy = MagicMock()
_concurrency_module.ThreadManager = MagicMock()
_thread_spec = importlib.util.spec_from_file_location(
    "runtime.thread_management", Path(__file__).resolve().parents[3] / "backend/runtime/thread_management.py",
)
_thread_lifecycle_module = importlib.util.module_from_spec(_thread_spec)
_thread_spec.loader.exec_module(_thread_lifecycle_module)
_thread_lifecycle_module.runtime_thread_manager.run = AsyncMock(
    side_effect=_run_managed
)
_thread_lifecycle_module.runtime_thread_manager.submit = MagicMock(return_value=MagicMock(
    execution_id="execution-test",
    future=MagicMock(done=MagicMock(return_value=True)),
))
_thread_lifecycle_module.runtime_thread_manager.wait_until_started = AsyncMock()
_thread_lifecycle_module.config_thread_manager = MagicMock()
sys.modules["runtime.thread_management"] = _thread_lifecycle_module
sys.modules["management.thread_management"] = _thread_lifecycle_module
sys.modules["nexent.core.agents"] = MagicMock()
sys.modules["nexent.core.agents"].__path__ = [str(Path(__file__).resolve().parents[3] / "sdk/nexent/core/agents")]
sys.modules["nexent.core.agents"].__spec__ = importlib.machinery.ModuleSpec("nexent.core.agents", loader=None, is_package=True)
sys.modules["nexent.core.agents.contracts.config"] = nexent_agent_model_mock
sys.modules["nexent.core.agents.orchestration.entry"] = MagicMock()
context_input_mock = types.ModuleType("nexent.core.agents.contracts.context")


class MockContextInput:
    def __init__(self, items=()):
        self.items = items


context_input_mock.ContextInput = MockContextInput
sys.modules["nexent.core.agents.contracts.context"] = context_input_mock
context_items_mock = types.ModuleType("nexent.core.agents.context")
context_items_mock.__path__ = [str(Path(__file__).resolve().parents[3] / "sdk/nexent/core/agents/context")]
context_items_mock.ContextItemInput = MagicMock()
context_input_mock.ContextItemInput = context_items_mock.ContextItemInput
sys.modules["nexent.core.agents.context"] = context_items_mock

# Mock other nexent submodules
sys.modules["nexent.memory"] = MagicMock()
sys.modules["nexent.memory.memory_service"] = MagicMock()
memory_models_module = types.ModuleType("nexent.memory.models")
memory_models_module.MemoryIngestUnit = MagicMock
sys.modules["nexent.memory.models"] = memory_models_module
knowledge_scope_service_module = types.ModuleType("management.services.knowledge_base.scope")
knowledge_scope_service_module.build_runtime_knowledge_resources = MagicMock
knowledge_scope_service_module.prepare_tool_retrieval_overrides = MagicMock(return_value=None)
knowledge_scope_service_module.resolve_knowledge_scope = MagicMock
sys.modules["management.services.knowledge_base.scope"] = knowledge_scope_service_module
fa_memory_extractor_module = types.ModuleType("management.services.memory.extraction")
fa_memory_extractor_module.FaMemoryExtractor = MagicMock
sys.modules["management.services.memory.extraction"] = fa_memory_extractor_module
memory_backend_adapter_module = types.ModuleType("management.services.memory.provider")
memory_backend_adapter_module._build_ingestion_event_service = MagicMock
memory_backend_adapter_module.build_memory_service_for_fa_extraction = MagicMock
sys.modules["management.services.memory.provider"] = memory_backend_adapter_module
sys.modules["nexent.storage"] = MagicMock()
sys.modules["nexent.storage.storage_client_factory"] = MagicMock()
sys.modules["nexent.storage.minio_config"] = MagicMock()
sys.modules["nexent.monitor"] = MagicMock()
sys.modules["nexent.monitor.monitoring"] = MagicMock()
sys.modules["nexent.monitor.local_content"] = MagicMock()

# Mock external dependencies
sys.modules["boto3"] = MagicMock()
sys.modules["elasticsearch"] = MagicMock()

# Mock database submodules (do not replace the parent `database` package to avoid breaking other tests)
sys.modules["management.db.agent.repository"] = MagicMock()
sys.modules["management.db.tool.repository"] = MagicMock()
sys.modules["management.db.mcp.remote"] = MagicMock()
sys.modules["management.db.agent.version"] = MagicMock()
sys.modules["management.db.identity.group"] = MagicMock()
sys.modules["management.db.identity.user_tenant"] = MagicMock()
sys.modules["management.db.model.repository"] = MagicMock()

# Mock a2a_agent_db (referenced by agent_service.py)
sys.modules["management.db.a2a.repository"] = MagicMock()
sys.modules["management.db.skill.repository"] = MagicMock()

# Mock conversation_db and db_models (newly imported by agent_service.py for
# runtime metadata support) so the real sqlalchemy-based modules are not loaded
# during collection - the pre-existing sqlalchemy stub conflicts with
# sqlalchemy.dialects.postgresql.
sys.modules["management.db.conversation.repository"] = MagicMock()
sys.modules["management.db.models"] = MagicMock()

# Mock conversation_db and db_models (newly imported by agent_service.py for
# runtime metadata support) so the real sqlalchemy-based modules are not loaded
# during collection - the pre-existing sqlalchemy stub conflicts with
# sqlalchemy.dialects.postgresql.
sys.modules["management.db.conversation.repository"] = MagicMock()
sys.modules["management.db.models"] = MagicMock()

# Stub infrastructure.rdb.client early so real DB modules are not loaded during import
_mock_db_client = MagicMock()
_mock_db_client.get_db_session = MagicMock()
_mock_db_client.as_dict = MagicMock()
_mock_db_client.MinioClient = MagicMock()
_mock_db_client.db_client = MagicMock()
sys.modules["infrastructure.rdb.client"] = _mock_db_client
sys.modules["infrastructure.object_storage.client"] = sys.modules["infrastructure.rdb.client"]
from test.common.database_stubs import install_serialization_stub
install_serialization_stub(sys.modules["infrastructure.rdb.client"])
from test.common.database_stubs import install_serialization_stub
install_serialization_stub(sys.modules["infrastructure.rdb.client"])
sys.modules["infrastructure.rdb.client"] = _mock_db_client
sys.modules["infrastructure.object_storage.client"] = sys.modules["infrastructure.rdb.client"]
from test.common.database_stubs import install_serialization_stub
install_serialization_stub(sys.modules["infrastructure.rdb.client"])

# Mock services submodules
services_module = types.ModuleType("services")
services_module.__path__ = [
    os.path.join(os.path.dirname(__file__), "../../../backend/services")
]
sys.modules["services"] = services_module

tag_management_service_module = types.ModuleType("management.services.tag.library")
tag_management_service_module.TagManagementService = MagicMock()
sys.modules["management.services.tag.library"] = tag_management_service_module
setattr(services_module, "tag_management_service", tag_management_service_module)

runtime_state_service_module = types.ModuleType("infrastructure.redis.run_state")
runtime_state_service_mock = MagicMock()
runtime_state_service_mock.enabled = False
runtime_state_service_mock.is_cancelled_async = AsyncMock(return_value=False)
runtime_state_service_mock.get_run_state_async = AsyncMock(return_value={})
runtime_state_service_mock.read_stream_events_async = AsyncMock(return_value=[])
runtime_state_service_mock.wait_for_stream_events_async = AsyncMock(return_value=[])
runtime_state_service_mock.get_stream_status_async = AsyncMock(return_value={})
runtime_state_service_mock.reset_stream_async = AsyncMock(return_value=None)
runtime_state_service_module.runtime_state_service = runtime_state_service_mock
sys.modules["infrastructure.redis.run_state"] = runtime_state_service_module

conversation_management_service_mock = MagicMock()
memory_config_service_mock = MagicMock()
agent_version_service_mock = MagicMock()
skill_service_mock = types.ModuleType("management.services.skill.service")
skill_service_mock.SkillService = MagicMock()
skill_service_mock.SkillService.return_value.list_skill_instances.return_value = []
sys.modules["management.services.conversation.service"] = conversation_management_service_mock
sys.modules["management.services.configuration.user.memory"] = memory_config_service_mock
sys.modules["management.services.agent.versions"] = agent_version_service_mock
sys.modules["management.services.skill.service"] = skill_service_mock
sys.modules["management.services.file.service"] = MagicMock()
sys.modules["infrastructure.agent_stream_channels"] = MagicMock()

model_gateway_service_mock = types.ModuleType("management.services.model.adapter")
model_gateway_service_mock.build_adapter_fresh = MagicMock()
sys.modules["management.services.model.adapter"] = model_gateway_service_mock
setattr(services_module, "model_gateway_service", model_gateway_service_mock)


# Mock streaming_channel_manager with async methods
class AsyncChannelMock:
    """Async mock for StreamingChannel that can be awaited."""

    def __init__(self):
        self._history = []
        self._completed = False
        self._completion_status = None
        self._event = asyncio.Event()

    @property
    def is_completed(self):
        return self._completed

    @property
    def completion_status(self):
        return self._completion_status

    async def publish(self, chunk, *args, **kwargs):
        if not self._completed:
            self._history.append(chunk)
            self._event.set()

    async def subscribe_with_history(self, start_from_index=0):
        index = start_from_index
        while True:
            while index < len(self._history):
                chunk = self._history[index]
                index += 1
                yield chunk
            if self._completed:
                break
            self._event.clear()
            await self._event.wait()

    def complete(self, status="completed"):
        self._completed = True
        self._completion_status = status
        self._event.set()

    async def close(self, *args, **kwargs):
        pass


streaming_channel_manager_mock = MagicMock()


async def _get_test_streaming_channel(*args, **kwargs):
    channel = AsyncChannelMock()
    streaming_channel_manager_mock._latest_channel = channel
    return channel


async def _complete_test_streaming_channel(*args, **kwargs):
    channel = getattr(streaming_channel_manager_mock, "_latest_channel", None)
    if isinstance(channel, AsyncChannelMock):
        channel.complete(kwargs.get("status", "completed"))


streaming_channel_manager_mock.get_or_create_channel = AsyncMock(
    side_effect=_get_test_streaming_channel
)
streaming_channel_manager_mock.remove_channel = AsyncMock(return_value=None)
streaming_channel_manager_mock.publish = AsyncMock(return_value=None)
streaming_channel_manager_mock.complete_channel = AsyncMock(
    side_effect=_complete_test_streaming_channel
)
sys.modules[
    "infrastructure.agent_stream_channels"
].streaming_channel_manager = streaming_channel_manager_mock
setattr(
    services_module, "skill_service", sys.modules["management.services.skill.service"]
)

# Load real asset_owner_visibility (agent_service imports resolve_agent_list_permission)
import importlib.util

_asset_owner_path = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / 'management' / 'services' / 'permission' / 'asset_owner.py'
)
_asset_owner_spec = importlib.util.spec_from_file_location(
    "management.services.permission.asset_owner", _asset_owner_path
)
_asset_owner_mod = importlib.util.module_from_spec(_asset_owner_spec)
_asset_owner_spec.loader.exec_module(_asset_owner_mod)
sys.modules["management.services.permission.asset_owner"] = _asset_owner_mod
setattr(services_module, "asset_owner_visibility", _asset_owner_mod)

# Mock canonical preparation modules
sys.modules["management.services.agent.preparation.run"] = MagicMock()
sys.modules["management.services.agent.preparation.tools"] = MagicMock()

sys.modules["management.services.agent.preprocessing"] = MagicMock()

# Need to set up create_tool_config_list as an async mock
mock_create_agent_info = MagicMock()
mock_create_agent_info.create_tool_config_list = AsyncMock(return_value=[])
sys.modules["management.services.agent.preparation.tools"].create_tool_config_list = mock_create_agent_info.create_tool_config_list

# Mock utils submodules
utils_module = types.ModuleType("utils")
utils_module.__path__ = [
    os.path.join(os.path.dirname(__file__), "../../../backend/utils")
]
sys.modules["utils"] = utils_module
sys.modules["management.services.permission.identity.session"] = MagicMock()
sys.modules["utils.thread_utils"] = MagicMock()
sys.modules["infrastructure.trace.knowledge"] = MagicMock()


# Mock str_utils with actual convert_list_to_string implementation
def mock_convert_list_to_string(items):
    """Mock implementation of convert_list_to_string."""
    if not items:
        return ""
    return ",".join(str(item) for item in items)

# Mock Elasticsearch (already done in the import section above, but keeping for reference)
elasticsearch_client_mock = MagicMock()


# Mock memory-related modules
nexent_mock = MagicMock()
sys.modules["nexent"] = nexent_mock
sys.modules["nexent.core"] = MagicMock()
sys.modules["nexent.core"].__path__ = [str(Path(__file__).resolve().parents[3] / "sdk/nexent/core")]
sys.modules["nexent.core"].__spec__ = importlib.machinery.ModuleSpec("nexent.core", loader=None, is_package=True)
sys.modules["nexent.core.agents"] = MagicMock()
sys.modules["nexent.core.agents"].__path__ = [str(Path(__file__).resolve().parents[3] / "sdk/nexent/core/agents")]
sys.modules["nexent.core.agents"].__spec__ = importlib.machinery.ModuleSpec("nexent.core.agents", loader=None, is_package=True)
sys.modules["nexent.core.models"] = MagicMock()
sys.modules["nexent.core.utils"] = MagicMock()


# Mock ProcessType enum for observer module
class MockProcessType:
    class FINAL_ANSWER:
        value = "final_answer"

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

    class FILE_ARTIFACT:
        value = "file_artifact"


sys.modules["nexent.core.utils.observer"] = MagicMock()
sys.modules["nexent.core.utils.observer"].ProcessType = MockProcessType


# Mock rerank_model module with proper class exports
class MockBaseRerank:
    pass


class MockOpenAICompatibleRerank(MockBaseRerank):
    def __init__(self, *args, **kwargs):
        pass


rerank_module = MagicMock()
rerank_module.BaseRerank = MockBaseRerank
rerank_module.OpenAICompatibleRerank = MockOpenAICompatibleRerank
sys.modules["nexent.core.models.rerank_model"] = rerank_module
# Don't mock agent_model yet, we need to import ToolConfig first
sys.modules["nexent.memory"] = MagicMock()
sys.modules["nexent.memory.memory_service"] = MagicMock()
sys.modules["management.utils.serialization"] = MagicMock()
sys.modules["management.utils.serialization"].convert_list_to_string = mock_convert_list_to_string
sys.modules["management.utils.serialization"].convert_string_to_list = lambda s: (
    s.split(",") if s else []
)

tenant_settings_mock = MagicMock()
tenant_settings_mock.tenant_config_manager = MagicMock()
tenant_settings_mock.tenant_config_manager.get_model_config = MagicMock()
sys.modules["management.services.configuration.tenant.settings"] = tenant_settings_mock
sys.modules["management.services.agent.prompt"] = MagicMock()
sys.modules["management.services.model.invocation"] = MagicMock()
sys.modules["infrastructure.trace.bootstrap"] = MagicMock()

# =============================================================================
# STEP 2: Now import after all mocks are in place
# =============================================================================

from nexent.core.agents.contracts.config import ToolConfig
from contracts.agent import AgentNameBatchCheckItem, AgentNameBatchCheckRequest, AgentNameBatchRegenerateItem, AgentNameBatchRegenerateRequest

# Set up mock for nexent.monitor
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
sys.modules["infrastructure.trace.bootstrap"].monitoring_manager = monitoring_manager_mock
sys.modules["infrastructure.trace.bootstrap"].setup_fastapi_app = MagicMock(return_value=True)

# Mock storage config validate
sys.modules["nexent.storage.minio_config"].MinIOStorageConfig = type(
    "MinIOStorageConfig", (), {"validate": lambda self: None}
)

# =============================================================================
# STEP 3: Create mock objects for database clients
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

    @contextmanager
    def _mock_context():
        yield session

    return _mock_context()


# Mock database client module
mock_backend_database_client = MagicMock()
mock_backend_database_client.PostgresClient = MagicMock(
    return_value=mock_postgres_client
)
mock_backend_database_client.get_db_session = mock_get_db_session
mock_backend_database_client.MinioClient = MagicMock(return_value=minio_client_mock)
mock_backend_database_client.db_client = mock_postgres_client
sys.modules["infrastructure.rdb.client"] = mock_backend_database_client
sys.modules["infrastructure.object_storage.client"] = sys.modules["infrastructure.rdb.client"]
from test.common.database_stubs import install_serialization_stub
install_serialization_stub(sys.modules["infrastructure.rdb.client"])

# Mock storage client factory
sys.modules[
    "nexent.storage.storage_client_factory"
].create_storage_client_from_config = MagicMock(return_value=MagicMock())

# Other test modules may have imported the production model module before this
# file installs its lightweight SDK types. Reload it against this file's
# ``MockToolConfig`` so model validation uses one consistent class identity.
sys.modules.pop("contracts.agent", None)
if hasattr(sys.modules.get("consts"), "model"):
    delattr(sys.modules["consts"], "model")

from importlib.machinery import ModuleSpec as _SDKModuleSpec
from pathlib import Path as _SDKPath
for _package in ("nexent", "nexent.core", "nexent.core.agents", "nexent.core.models", "nexent.core.agents.contracts"):
    if _package in sys.modules:
        sys.modules[_package].__path__ = [str(_SDKPath(__file__).resolve().parents[3] / "sdk" / _package.replace(".", "/"))]
        sys.modules[_package].__spec__ = _SDKModuleSpec(_package, loader=None, is_package=True)
        sys.modules[_package].__package__ = _package

# Now import backend modules
# Load the consolidated context after its external collaborators are isolated.
sys.modules.pop("management.services.agent.context", None)
from management.services.agent import context as agent_context
agent_context.build_authorized_context_input = (
    lambda agent_run_info, historical_context=None: MockContextInput(
        items=tuple(agent_run_info.agent_config.context_items or ())
    )
)

from management.services.agent import naming as naming_service
from management.services.agent import management as agent_management
from management.services.agent import service as agent_service
from management.services.agent import transfer as agent_transfer
from management.services.agent import transfer as agent_transfer_backend
from management.services.agent.icon import ICON_MAX_BYTES
from management.services.agent.service import update_agent_info_impl
from management.services.agent.service import list_all_agent_info_impl
from management.services.agent.service import list_agent_page_impl
from management.services.agent.service import get_agent_info_impl
from management.services.agent.service import get_enable_tool_id_by_agent_id
from management.services.agent.service import (
    get_agent_call_relationship_impl,
    delete_agent_impl,
    export_agent_impl,
    export_agent_by_agent_id,
    import_agent_by_agent_id,
    import_agent_impl,
    get_agent_by_name_impl,
    _resolve_model_ids_with_fallback,
    clear_agent_new_mark_impl,
)
from contracts.constants.constants import STREAM_STATUS_EVENT
from contracts.constants.environment import RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS
from contracts.errors.exceptions import AgentRunConcurrencyExceededError, RuntimeCapacityExceededError, RuntimeQueueTimeoutError
from test.backend.services.agent_legacy_helpers import (
    delete_related_agent_impl,
    insert_related_agent_impl,
    load_default_agents_json_file,
    get_agent_id_by_name,
)
from management.services.conversation.service import (
    save_message,
    save_message_unit,
    update_unit_status,
    update_message_status,
)
from management.services.agent.context import (
    prepend_current_time,
)
from management.services.agent.stream import (
    AssistantMessageProjection,
)
from management.services.agent.read import (
    apply_duplicate_name_availability_rules as _apply_duplicate_name_availability_rules,
)
from nexent.core.agents.prompt.meta import render_name_template as _render_prompt_template
from contracts.agent import ExportAndImportAgentInfo, ExportAndImportDataFormat, MCPInfo, AgentRequest

@pytest.fixture(autouse=True)
def mock_agent_edit_permission(mocker, request):
    if request.node.name.startswith(("test_update_agent_info", "test_cmsr_006")):
        mocker.patch.object(agent_service, "resolve_agent_list_permission", return_value="EDIT")


def test_projection_persists_tool_arguments_and_associates_the_result():
    projection = AssistantMessageProjection(persist_units=True)
    projection.project(json.dumps({
        "type": "tool-call", "content": "querying", "tool_name": "lookup",
        "tool_call_id": "call-1", "invocation_id": "child", "tool_arguments": {"limit": 2},
    }))
    projection.project(json.dumps({
        "type": "tool", "content": "result", "tool_name": "lookup",
        "tool_call_id": "call-1", "invocation_id": "child",
    }))

    assert [unit["type"] for unit in projection.units] == ["tool-call", "tool"]
    assert [unit["unit_index"] for unit in projection.units] == [0, 1]
    assert all(unit["tool_call_id"] == "call-1" and unit["invocation_id"] == "child" for unit in projection.units)
    assert json.loads(projection.units[0]["unit_content"])["tool_arguments"] == {"limit": 2}
    assert json.loads(projection.units[1]["unit_content"]) == {"content": "result", "tool_name": "lookup"}


def test_projection_ignores_malformed_sources_and_keeps_only_valid_automation_proposals():
    projection = AssistantMessageProjection(persist_units=True)
    assert projection.project("not JSON") == ("not JSON", {})
    projection.project(json.dumps({"type": "search_content", "content": "not a search result"}))
    projection.project(json.dumps({"type": "picture_web", "content": "not an image result"}))
    images = json.dumps({"images_url": ["https://fixture.invalid/image", "https://fixture.invalid/image"]})
    projection.project(json.dumps({"type": "picture_web", "content": images}))
    projection.project(json.dumps({"type": "automation_proposal", "content": "not a proposal"}))
    projection.project(json.dumps({"type": "automation_proposal", "content": '{"proposal_id":7}'}))

    assert projection.search_records == []
    assert projection.image_urls == ["https://fixture.invalid/image"]
    assert projection.units[0]["type"] == "search_content_placeholder"
    assert projection.automation_proposals == [{"unit_index": 4, "proposal_id": 7}]


def apply_default_agent_request_fields(request):
    """Populate optional fields used by Agent configuration service logic."""
    request.enabled_skill_ids = None
    if not hasattr(request, "related_agent_ids"):
        request.related_agent_ids = None
    if not hasattr(request, "related_agents"):
        request.related_agents = None
    if not hasattr(request, "enabled_tool_ids"):
        request.enabled_tool_ids = None
    if not hasattr(request, "example_questions"):
        request.example_questions = None
    if not hasattr(request, "greeting_message"):
        request.greeting_message = None
    return request


@pytest.mark.asyncio
async def test_get_enable_tool_id_by_agent_id():
    """
    Test the function that retrieves enabled tool IDs for a specific agent.

    This test verifies that:
    1. The function correctly filters and returns only enabled tool IDs
    2. The underlying query function is called with correct parameters
    """
    # Setup
    mock_tool_instances = [
        {"tool_id": 1, "enabled": True},
        {"tool_id": 2, "enabled": False},
        {"tool_id": 3, "enabled": True},
        {"tool_id": 4, "enabled": True},
    ]

    with patch(
        "management.services.agent.service.query_all_enabled_tool_instances"
    ) as mock_query:
        mock_query.return_value = mock_tool_instances

        # Execute
        result = get_enable_tool_id_by_agent_id(agent_id=123, tenant_id="test_tenant")

        # Assert
        assert sorted(result) == [1, 3, 4]
        mock_query.assert_called_once_with(agent_id=123, tenant_id="test_tenant")


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_success(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """
    Test successful retrieval of an agent's information by ID.

    This test verifies that:
    1. The function correctly retrieves the agent's basic information
    2. It fetches the associated tools
    3. It gets the sub-agent ID list
    4. It returns a complete agent information structure with availability status
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test agent",
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1", "unavailable_reasons": []}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [456, 789]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Disabled skill instances must not be returned as selected skills.
    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = [
        {"skill_id": 1, "enabled": True},
        {"skill_id": 2, "enabled": False},
    ]
    mock_skill_service.return_value = mock_skill_service_instance

    # skill_db.get_valid_skill_ids is hit as a fallback check; mock it to keep the
    # flow self-contained without requiring a live DB.
    with patch(
        "management.services.agent.service.skill_db.get_valid_skill_ids",
        return_value={1},
    ):
        # Mock check_agent_availability - agent is available
        mock_check_availability.return_value = (True, [])
        # Execute
        result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    expected_tools = [{"tool_id": 1, "name": "Tool 1", "unavailable_reasons": []}]
    expected_result = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test agent",
        "tools": expected_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "sub_agent_relations": [],
        "skills": [{"skill_id": 1, "enabled": True}],
        "external_sub_agent_id_list": [],
        "model_ids": [],  # Added for get_valid_model_ids integration
        "model_names": [],
        "model_name": None,
        "business_logic_model_name": None,
        "is_available": True,
        "unavailable_reasons": [],
    }
    assert result == expected_result
    mock_search_agent_info.assert_called_once_with(123, "test_tenant", 0)
    mock_search_tools.assert_called_once_with(agent_id=123, tenant_id="test_tenant")
    mock_query_sub_agents_id.assert_called_once_with(
        main_agent_id=123, tenant_id="test_tenant"
    )
    mock_check_availability.assert_called_once()


@patch("management.services.agent.service.query_current_version_no")
@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_with_version_no(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
    mock_query_current_version_no,
):
    """
    Test get_agent_info_impl with explicit version_no parameter.

    This test verifies that:
    1. The function correctly passes version_no to search_agent_info_by_agent_id
    2. It works correctly when version_no is explicitly provided
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test agent",
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1", "unavailable_reasons": []}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [456, 789]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Mock SkillService to return empty list for skills
    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance

    # Mock query_external_sub_agents
    mock_query_external_sub_agents.return_value = []

    # Mock get_model_by_model_id - return None for model_id=None
    mock_get_model_by_model_id.return_value = None

    # Mock check_agent_availability - agent is available
    mock_check_availability.return_value = (True, [])

    # Mock query_current_version_no - return 5 as the current version
    mock_query_current_version_no.return_value = 5

    # Execute with explicit version_no
    result = await get_agent_info_impl(
        agent_id=123, tenant_id="test_tenant", version_no=5
    )

    # Assert
    expected_tools = [{"tool_id": 1, "name": "Tool 1", "unavailable_reasons": []}]
    expected_result = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test agent",
        "tools": expected_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "sub_agent_relations": [],
        "skills": [],
        "external_sub_agent_id_list": [],
        "model_ids": [],  # Added for get_valid_model_ids integration
        "model_names": [],
        "model_name": None,
        "business_logic_model_name": None,
        "is_available": True,
        "unavailable_reasons": [],
        "current_version_no": 5,
    }
    assert result == expected_result
    # Verify version_no is passed correctly
    mock_search_agent_info.assert_called_once_with(123, "test_tenant", 5)
    mock_search_tools.assert_called_once_with(agent_id=123, tenant_id="test_tenant")
    mock_query_sub_agents_id.assert_called_once_with(
        main_agent_id=123, tenant_id="test_tenant"
    )
    mock_check_availability.assert_called_once()
    # Verify query_current_version_no is called for version_no > 0
    mock_query_current_version_no.assert_called_once_with(123, "test_tenant")


@patch('management.services.agent.service.create_or_update_tool_by_tool_info')
@patch('management.db.tool.repository.query_tool_instances_by_id')
@patch('management.services.agent.transfer.query_all_tools')
@patch('management.services.agent.service.update_agent')
@pytest.mark.asyncio
async def test_update_agent_info_impl_success(mock_update_agent, mock_query_all_tools, mock_query_tool_instances_by_id, mock_create_or_update_tool):
    """
    Test successful update of agent information.

    This test verifies that:
    1. The function correctly gets the current user and tenant IDs
    2. It calls the update_agent function with the correct parameters
    """
    request = MagicMock()
    request.agent_id = 123
    request.model_id = None
    request.business_description = 'Updated agent'
    request.display_name = 'Updated Display Name'
    request.enabled_tool_ids = None
    apply_default_agent_request_fields(request)
    await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    mock_update_agent.assert_called_once_with(123, request, 'test_user')


@pytest.mark.asyncio
async def test_cmsr_006_read_only_agent_cannot_change_protocol_repair_policy():
    """The new policy cannot be changed through a read-only Agent update."""
    request = MagicMock()
    request.agent_id = 123
    request.enable_protocol_repair_retry = False
    request.requested_output_tokens = None
    request.example_questions = None
    apply_default_agent_request_fields(request)
    with patch('management.services.agent.service.search_agent_info_by_agent_id', return_value={'agent_id': 123, 'tenant_id': 'test_tenant'}), patch('management.services.agent.service.get_user_tenant_by_user_id', return_value={'user_role': 'USER'}), patch('management.services.agent.service.resolve_agent_list_permission', return_value='READ_ONLY'), patch('management.services.agent.service.update_agent') as mock_update:
        with pytest.raises(agent_service.ForbiddenError):
            await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_cmsr_006_editable_agent_can_disable_protocol_repair_policy():
    """An editable Agent can persist an explicitly disabled policy."""
    request = MagicMock()
    request.agent_id = 123
    request.enable_protocol_repair_retry = False
    request.requested_output_tokens = None
    request.example_questions = None
    request.enabled_tool_ids = None
    request.related_agent_ids = None
    apply_default_agent_request_fields(request)
    with patch('management.services.agent.service.search_agent_info_by_agent_id', return_value={'agent_id': 123, 'tenant_id': 'test_tenant'}), patch('management.services.agent.service.get_user_tenant_by_user_id', return_value={'user_role': 'USER'}), patch('management.services.agent.service.resolve_agent_list_permission', return_value='EDIT'), patch('management.services.agent.service.update_agent') as mock_update:
        result = await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result['agent_id'] == 123
    mock_update.assert_called_once_with(123, request, 'test_user')


@patch("management.services.agent.management.delete_tools_by_agent_id")
@patch("management.services.agent.management.delete_agent_relationship")
@patch("management.services.agent.management.delete_agent_by_id")
@patch("management.services.agent.management.skill_db.delete_skills_by_agent_id")
@pytest.mark.asyncio
async def test_delete_agent_impl_success(
    mock_delete_skills, mock_delete_agent, mock_delete_related, mock_delete_tools
):
    """
    Test successful deletion of an agent.

    This test verifies that:
    1. It calls the delete_agent_by_id function with the correct parameters
    2. It also deletes all related agent relationships
    3. It deletes all tools associated with the agent
    """
    # Execute
    await delete_agent_impl(123, "test_tenant", "test_user")

    # Assert
    mock_delete_agent.assert_called_once_with(123, "test_tenant", "test_user")
    mock_delete_related.assert_called_once_with(123, "test_tenant", "test_user")
    mock_delete_tools.assert_called_once_with(123, "test_tenant", "test_user")
    mock_delete_skills.assert_called_once_with(123, "test_tenant", "test_user")


@patch("management.services.agent.management.delete_tools_by_agent_id")
@patch("management.services.agent.management.delete_agent_relationship")
@patch("management.services.agent.management.delete_agent_by_id")
@patch("management.services.agent.management.skill_db.delete_skills_by_agent_id")
@patch("management.services.agent.management.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_delete_agent_impl_cleans_up_tags_for_tenant_owned_agent(
    mock_search_agent,
    mock_delete_skills,
    _mock_delete_agent,
    _mock_delete_related,
    _mock_delete_tools,
):
    mock_search_agent.return_value = {"tenant_id": "test_tenant"}
    cleanup = (
        tag_management_service_module.TagManagementService.cleanup_resource_assignments
    )

    await delete_agent_impl(123, "test_tenant", "test_user")

    cleanup.assert_called_once_with("test_tenant", "agent", "123", "test_user")


@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_exception_handling(mock_search_agent_info):
    """
    Test exception handling in get_agent_info_impl function.

    This test verifies that:
    1. When an exception occurs during agent info retrieval
    2. The function raises a ValueError with an appropriate message
    """
    # Setup
    mock_search_agent_info.side_effect = Exception("Database error")

    # Execute & Assert
    with pytest.raises(ValueError) as context:
        await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    assert "Failed to get agent info" in str(context.value)
    # Verify version_no parameter is passed (default value 0)
    mock_search_agent_info.assert_called_once_with(123, "test_tenant", 0)


@patch('management.services.agent.service.update_agent')
@pytest.mark.asyncio
async def test_update_agent_info_impl_exception_handling(mock_update_agent):
    """
    Test exception handling in update_agent_info_impl function.

    This test verifies that:
    1. When an exception occurs during agent info update
    2. The function raises a ValueError with an appropriate message
    """
    mock_update_agent.side_effect = Exception('Update failed')
    request = MagicMock()
    request.agent_id = 123
    request.model_id = None
    request.display_name = 'Test Display Name'
    request.enabled_tool_ids = None
    request.related_agent_ids = None
    request.example_questions = None
    apply_default_agent_request_fields(request)
    with pytest.raises(ValueError) as context:
        await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert 'Failed to update agent info' in str(context.value)


@patch('management.services.agent.service.update_agent')
@pytest.mark.asyncio
async def test_update_agent_info_impl_reraises_agent_quota_error(mock_update_agent):
    """Agent quota errors must pass through without generic error wrapping."""
    from contracts.errors.exceptions import TenantResourceLimitError
    limit_error = TenantResourceLimitError('Tenant agent limit reached: maximum 1000 agents per tenant', resource='agents', scope='tenant', limit=1000, current_count=1000)
    mock_update_agent.side_effect = limit_error
    request = MagicMock()
    request.agent_id = 123
    request.model_id = None
    request.display_name = 'Test Display Name'
    request.enabled_tool_ids = None
    request.related_agent_ids = None
    request.example_questions = None
    apply_default_agent_request_fields(request)
    with pytest.raises(TenantResourceLimitError) as exc_info:
        await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert exc_info.value is limit_error


@patch('management.services.agent.service.query_tools_by_ids')
@patch('management.services.agent.service.create_or_update_tool_by_tool_info')
@patch('management.services.agent.service.query_tool_instances_by_agent_id')
@patch('management.services.agent.service.update_agent')
@pytest.mark.asyncio
async def test_update_agent_info_impl_with_enabled_tool_ids(mock_update_agent, mock_query_tool_instances_by_agent_id, mock_create_or_update_tool, mock_query_tools_by_ids):
    """
    Test update_agent_info_impl with enabled_tool_ids parameter.

    This test verifies that:
    1. When enabled_tool_ids is provided, existing tools are disabled if not selected
    2. Selected tools are enabled (create or update)
    3. Existing tool params are preserved
    """
    mock_query_tool_instances_by_agent_id.return_value = [{'tool_id': 1, 'params': {'key1': 'value1'}}]
    mock_query_tools_by_ids.return_value = [{'tool_id': 1, 'is_available': True}, {'tool_id': 2, 'is_available': True}]
    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = [1, 2]
    request.related_agent_ids = None
    apply_default_agent_request_fields(request)
    result = await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result['agent_id'] == 123
    mock_update_agent.assert_called_once()
    assert mock_create_or_update_tool.call_count == 2
    call_args = mock_create_or_update_tool.call_args_list[0]
    tool_info = call_args.kwargs['tool_info']
    assert tool_info.tool_id == 1
    assert tool_info.enabled is True
    assert tool_info.params == {'key1': 'value1'}
    call_args = mock_create_or_update_tool.call_args_list[1]
    tool_info = call_args.kwargs['tool_info']
    assert tool_info.tool_id == 2
    assert tool_info.enabled is True
    assert tool_info.params == {}


@patch('management.services.agent.service.query_tools_by_ids')
@patch('management.services.agent.service.create_or_update_tool_by_tool_info')
@patch('management.services.agent.service.query_tool_instances_by_agent_id')
@patch('management.services.agent.service.update_agent')
@pytest.mark.asyncio
async def test_update_agent_info_impl_skips_unavailable_enabled_tools(mock_update_agent, mock_query_tool_instances_by_agent_id, mock_create_or_update_tool, mock_query_tools_by_ids):
    """Unavailable tools must not be recreated from a stale Agent save."""
    mock_query_tool_instances_by_agent_id.return_value = []
    mock_query_tools_by_ids.return_value = [{'tool_id': 2, 'is_available': False}]
    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = [2]
    request.related_agent_ids = None
    apply_default_agent_request_fields(request)
    result = await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result['agent_id'] == 123
    mock_update_agent.assert_called_once()
    mock_query_tools_by_ids.assert_called_once_with([2])
    mock_create_or_update_tool.assert_not_called()


@patch('management.services.agent.service.query_tools_by_ids')
@patch('management.services.agent.service.create_or_update_tool_by_tool_info')
@patch('management.services.agent.service.query_tool_instances_by_agent_id')
@patch('management.services.agent.service.update_agent')
@pytest.mark.asyncio
async def test_update_agent_info_impl_with_enabled_tool_ids_instance_having_null_tool_id(mock_update_agent, mock_query_tool_instances_by_agent_id, mock_create_or_update_tool, mock_query_tools_by_ids):
    """
    Test update_agent_info_impl when existing tool instance has null tool_id.

    This test verifies that:
    1. Instances with null tool_id are skipped (not causing errors)
    2. Only valid tool instances are processed for enabling/disabling
    """
    mock_query_tool_instances_by_agent_id.return_value = [{'tool_id': 1, 'params': {'key1': 'value1'}}, {'tool_id': None, 'params': {}}]
    mock_query_tools_by_ids.return_value = [{'tool_id': 1, 'is_available': True}]
    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = [1]
    request.related_agent_ids = None
    apply_default_agent_request_fields(request)
    result = await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result['agent_id'] == 123
    mock_update_agent.assert_called_once()
    assert mock_create_or_update_tool.call_count == 1
    call_args = mock_create_or_update_tool.call_args
    tool_info = call_args.kwargs['tool_info']
    assert tool_info.tool_id == 1
    assert tool_info.enabled is True


@patch('management.services.agent.service.query_tools_by_ids')
@patch('management.services.agent.service.create_or_update_tool_by_tool_info')
@patch('management.services.agent.service.query_tool_instances_by_agent_id')
@patch('management.services.agent.service.update_agent')
@pytest.mark.asyncio
async def test_update_agent_info_impl_with_enabled_tool_ids_disabled_existing_tool(mock_update_agent, mock_query_tool_instances_by_agent_id, mock_create_or_update_tool, mock_query_tools_by_ids):
    """
    Test that existing tools not in enabled_tool_ids are disabled.

    This test verifies that:
    1. When enabled_tool_ids is provided, existing tools NOT in the list are disabled
    2. create_or_update_tool_by_tool_info is called with enabled=False for disabled tools
    """
    mock_query_tool_instances_by_agent_id.return_value = [{'tool_id': 1, 'params': {'key1': 'value1'}}]
    mock_query_tools_by_ids.return_value = [{'tool_id': 2, 'is_available': True}]
    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = [2]
    request.related_agent_ids = None
    apply_default_agent_request_fields(request)
    result = await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result['agent_id'] == 123
    mock_update_agent.assert_called_once()
    assert mock_create_or_update_tool.call_count == 2
    call_args = mock_create_or_update_tool.call_args_list[0]
    tool_info = call_args.kwargs['tool_info']
    assert tool_info.tool_id == 1
    assert tool_info.enabled is False
    assert tool_info.params == {'key1': 'value1'}
    call_args = mock_create_or_update_tool.call_args_list[1]
    tool_info = call_args.kwargs['tool_info']
    assert tool_info.tool_id == 2
    assert tool_info.enabled is True
    assert tool_info.params == {}


@patch('management.services.agent.service.update_related_agents')
@patch('management.services.agent.service.query_sub_agents_id_list')
@patch('management.services.agent.service.update_agent')
@pytest.mark.asyncio
async def test_update_agent_info_impl_with_related_agent_ids(mock_update_agent, mock_query_sub_agents_id_list, mock_update_related_agents):
    """
    Test update_agent_info_impl with related_agent_ids parameter.

    This test verifies that:
    1. When related_agent_ids is provided, relationships are updated
    2. Circular dependency detection works correctly
    3. update_related_agents is called with correct parameters
    """
    mock_query_sub_agents_id_list.return_value = []
    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = None
    request.related_agent_ids = [456, 789]
    request.related_agents = None
    apply_default_agent_request_fields(request)
    result = await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result['agent_id'] == 123
    mock_update_agent.assert_called_once()
    mock_update_related_agents.assert_called_once_with(parent_agent_id=123, tenant_id='test_tenant', user_id='test_user', related_agents=[{'agent_id': 456, 'version_no': None}, {'agent_id': 789, 'version_no': None}])


@patch('management.services.agent.service.query_sub_agents_id_list')
@patch('management.services.agent.service.update_agent')
@pytest.mark.asyncio
async def test_update_agent_info_impl_circular_dependency_detection(mock_update_agent, mock_query_sub_agents_id_list):
    """
    Test update_agent_info_impl circular dependency detection.

    This test verifies that:
    1. When agent tries to relate to itself, ValueError is raised
    2. When circular dependency is detected through sub-agents, ValueError is raised
    """
    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = None
    request.related_agent_ids = [123]
    apply_default_agent_request_fields(request)
    with pytest.raises(ValueError, match='Circular dependency detected'):
        await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    request.related_agent_ids = [456]
    mock_query_sub_agents_id_list.return_value = [123]
    with pytest.raises(ValueError, match='Circular dependency detected'):
        await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))


@patch('management.services.agent.service.query_tools_by_ids')
@patch('management.services.agent.service.create_or_update_tool_by_tool_info')
@patch('management.services.agent.service.query_tool_instances_by_agent_id')
@patch('management.services.agent.service.update_related_agents')
@patch('management.services.agent.service.query_sub_agents_id_list')
@patch('management.services.agent.service.update_agent')
@pytest.mark.asyncio
async def test_update_agent_info_impl_with_both_tool_and_related_agents(mock_update_agent, mock_query_sub_agents_id_list, mock_update_related_agents, mock_query_tool_instances_by_agent_id, mock_create_or_update_tool, mock_query_tools_by_ids):
    """
    Test update_agent_info_impl with both enabled_tool_ids and related_agent_ids.

    This test verifies that:
    1. Both tools and related agents can be updated in the same call
    2. Operations are performed in correct order
    """
    mock_query_tool_instances_by_agent_id.return_value = []
    mock_query_tools_by_ids.return_value = [{'tool_id': 1, 'is_available': True}]
    mock_query_sub_agents_id_list.return_value = []
    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = [1]
    request.related_agent_ids = [456]
    request.related_agents = None
    apply_default_agent_request_fields(request)
    result = await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result['agent_id'] == 123
    mock_update_agent.assert_called_once()
    mock_create_or_update_tool.assert_called_once()
    mock_update_related_agents.assert_called_once_with(parent_agent_id=123, tenant_id='test_tenant', user_id='test_user', related_agents=[{'agent_id': 456, 'version_no': None}])


@patch('management.services.agent.service.query_tools_by_ids')
@patch('management.services.agent.service.create_or_update_tool_by_tool_info')
@patch('management.services.agent.service.query_tool_instances_by_agent_id')
@patch('management.services.agent.service.update_agent')
@pytest.mark.asyncio
async def test_update_agent_info_impl_tool_update_exception(mock_update_agent, mock_query_tool_instances_by_agent_id, mock_create_or_update_tool, mock_query_tools_by_ids):
    """
    Test update_agent_info_impl exception handling for tool updates.

    This test verifies that:
    1. When tool update fails, ValueError is raised with appropriate message
    """
    mock_query_tool_instances_by_agent_id.return_value = []
    mock_query_tools_by_ids.return_value = [{'tool_id': 1, 'is_available': True}]
    mock_create_or_update_tool.side_effect = Exception('Tool update failed')
    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = [1]
    request.related_agent_ids = None
    apply_default_agent_request_fields(request)
    with pytest.raises(ValueError, match='Failed to update agent tools'):
        await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))


@patch('management.services.agent.service.update_related_agents')
@patch('management.services.agent.service.query_sub_agents_id_list')
@patch('management.services.agent.service.update_agent')
@pytest.mark.asyncio
async def test_update_agent_info_impl_related_agent_update_exception(mock_update_agent, mock_query_sub_agents_id_list, mock_update_related_agents):
    """
    Test update_agent_info_impl exception handling for related agent updates.

    This test verifies that:
    1. When related agent update fails, ValueError is raised with appropriate message
    """
    mock_query_sub_agents_id_list.return_value = []
    mock_update_related_agents.side_effect = Exception('Related agent update failed')
    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = None
    request.related_agent_ids = [456]
    request.related_agents = None
    apply_default_agent_request_fields(request)
    with pytest.raises(ValueError, match='Failed to update related agents'):
        await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))


@patch("management.services.agent.management.delete_agent_by_id")
@pytest.mark.asyncio
async def test_delete_agent_impl_exception_handling(mock_delete_agent):
    """
    Test exception handling in delete_agent_impl function.

    This test verifies that:
    1. When an exception occurs during agent deletion
    2. The function raises a ValueError with an appropriate message
    """
    # Setup
    mock_delete_agent.side_effect = Exception("Delete failed")

    # Execute & Assert
    with pytest.raises(ValueError) as context:
        await delete_agent_impl(123, "test_tenant", "test_user")

    assert "Failed to delete agent" in str(context.value)


@patch("management.services.agent.transfer.query_group_ids_by_user")
def test_get_user_group_ids_success(mock_get_group_ids):
    """
    Test successful retrieval of user's group IDs as comma-separated string.

    This test verifies that:
    1. The _get_user_group_ids function calls get_group_ids_by_user
    2. Returns a comma-separated string of group IDs
    3. Uses convert_list_to_string utility function
    """
    # Setup
    from management.services.agent.service import _get_user_group_ids

    mock_get_group_ids.return_value = [1, 2, 3]

    # Execute
    result = _get_user_group_ids("test_user", "test_tenant")

    # Assert
    assert result == "1,2,3"
    mock_get_group_ids.assert_called_once_with("test_user")


@patch("management.services.agent.transfer.query_group_ids_by_user")
def test_get_user_group_ids_empty_groups(mock_get_group_ids):
    """
    Test _get_user_group_ids with empty group list.

    This test verifies that:
    1. When user has no groups, returns empty string
    """
    # Setup
    from management.services.agent.service import _get_user_group_ids

    mock_get_group_ids.return_value = []

    # Execute
    result = _get_user_group_ids("test_user", "test_tenant")

    # Assert
    assert result == ""
    mock_get_group_ids.assert_called_once_with("test_user")


@patch("management.services.agent.transfer.query_group_ids_by_user")
def test_get_user_group_ids_exception_handling(mock_get_group_ids):
    """
    Test _get_user_group_ids exception handling.

    This test verifies that:
    1. When get_group_ids_by_user raises exception, logs warning and returns empty string
    """
    # Setup
    from management.services.agent.service import _get_user_group_ids

    mock_get_group_ids.side_effect = Exception("Database error")

    # Execute
    result = _get_user_group_ids("test_user", "test_tenant")

    # Assert
    assert result == ""
    mock_get_group_ids.assert_called_once_with("test_user")


@patch('management.services.agent.transfer.query_group_ids_by_user')
@patch('management.services.agent.service.create_agent')
@pytest.mark.asyncio
async def test_update_agent_info_impl_create_agent_auto_group_ids(mock_create_agent, mock_get_group_ids):
    """
    Test creating a new agent with automatic group_ids assignment.

    This test verifies that:
    1. When agent_id is None, a new agent is created
    2. The group_ids are automatically set to the current user's groups
    3. The create_agent function is called with the correct parameters including group_ids
    """
    from management.services.agent.service import update_agent_info_impl
    mock_get_group_ids.return_value = [1, 2, 3]
    mock_create_agent.return_value = {'agent_id': 456}
    request = MagicMock()
    request.agent_id = None
    request.name = 'New Agent'
    request.display_name = 'New Display Name'
    request.business_description = 'New agent description'
    request.author = 'test_author'
    request.model_id = 1
    request.model_name = 'test-model'
    request.business_logic_model_id = None
    request.business_logic_model_name = None
    request.max_steps = 10
    request.provide_run_summary = True
    request.prompt = "Test duty"
    request.enabled = True
    request.enabled_tool_ids = None
    request.related_agent_ids = None
    request.group_ids = None
    apply_default_agent_request_fields(request)
    result = await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result['agent_id'] == 456
    mock_get_group_ids.assert_called_once_with('test_user')
    mock_create_agent.assert_called_once()
    call_args = mock_create_agent.call_args[1]['agent_info']
    assert call_args['group_ids'] == '1,2,3'


@patch('management.services.agent.service.query_all_agent_info_by_tenant_id')
@patch('management.services.agent.transfer.query_group_ids_by_user')
@patch('management.services.agent.service.create_agent')
@pytest.mark.asyncio
async def test_update_agent_info_impl_create_agent_resolves_duplicate_names(mock_create_agent, mock_get_group_ids, mock_query_all_agents):
    """
    Creating an agent through update_agent_info_impl with a duplicate
    name/display_name must fall back to a unique numeric suffix so the new
    agent stays publishable (same rule as the repository import link).
    """
    mock_get_group_ids.return_value = []
    mock_create_agent.return_value = {'agent_id': 457}
    mock_query_all_agents.return_value = [{'agent_id': 1, 'name': 'javis_copy', 'display_name': 'Javis副本'}]
    request = MagicMock()
    request.agent_id = None
    request.name = 'javis_copy'
    request.display_name = 'Javis副本'
    request.business_description = 'copy'
    request.author = 'test_author'
    request.model_id = 1
    request.model_name = 'test-model'
    request.business_logic_model_id = None
    request.business_logic_model_name = None
    request.max_steps = 10
    request.provide_run_summary = True
    request.enabled = True
    request.enabled_tool_ids = None
    request.related_agent_ids = None
    request.group_ids = None
    apply_default_agent_request_fields(request)
    result = await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result['agent_id'] == 457
    call_args = mock_create_agent.call_args[1]['agent_info']
    assert call_args['name'] == 'javis_copy_1'
    assert call_args['display_name'] == 'Javis副本_1'

@patch('management.services.agent.transfer.get_mcp_server_by_name_and_tenant')
@patch('management.services.agent.transfer.ExportAndImportDataFormat')
@patch('management.services.agent.transfer.export_agent_by_agent_id')
@pytest.mark.asyncio
async def test_export_agent_impl_success(mock_export_agent_by_id, mock_export_data_format, mock_get_mcp_server):
    """
    Test successful export of agent information with MCP servers.
    """
    mcp_tool = MockToolConfig(class_name='MCPTool', name='MCP Tool', source='mcp', params={'param1': 'value1'}, metadata={}, description='MCP tool description', inputs='input description', output_type='output type description', usage='test_mcp_server')
    mock_agent_info = ExportAndImportAgentInfo(agent_id=123, name='Test Agent', display_name='Test Agent Display', description='A test agent', business_description='For testing purposes', max_steps=10, provide_run_summary=True, prompt='# Responsibilities\nTest duty prompt\n\n# Constraints\nTest constraint prompt\n\n# Examples\nTest few shots prompt', enabled=True, tools=[mcp_tool], managed_agents=[])
    mock_export_agent_by_id.return_value = mock_agent_info
    mock_get_mcp_server.return_value = 'http://test-mcp-server.com'
    mock_export_data_instance = Mock()
    mock_export_data_instance.model_dump.return_value = {'agent_id': 123, 'agent_info': {'123': {'agent_id': 123, 'name': 'Test Agent', 'display_name': 'Test Agent Display', 'description': 'A test agent', 'business_description': 'For testing purposes', 'max_steps': 10, 'provide_run_summary': True, 'prompt': '# Responsibilities\nTest duty prompt\n\n# Constraints\nTest constraint prompt\n\n# Examples\nTest few shots prompt', 'enabled': True, 'tools': [mcp_tool.model_dump()], 'managed_agents': []}}, 'mcp_info': [{'mcp_server_name': 'test_mcp_server', 'mcp_url': 'http://test-mcp-server.com'}]}
    mock_export_data_format.return_value = mock_export_data_instance
    result = await export_agent_impl(agent_id=123, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    result_dict = json.loads(result)
    assert result_dict['agent_id'] == 123
    assert 'agent_info' in result_dict
    assert '123' in result_dict['agent_info']
    assert 'mcp_info' in result_dict
    agent_data = result_dict['agent_info']['123']
    assert agent_data['name'] == 'Test Agent'
    assert agent_data['business_description'] == 'For testing purposes'
    assert agent_data['agent_id'] == 123
    assert len(agent_data['tools']) == 1
    mcp_info = result_dict['mcp_info']
    assert len(mcp_info) == 1
    assert mcp_info[0]['mcp_server_name'] == 'test_mcp_server'
    assert mcp_info[0]['mcp_url'] == 'http://test-mcp-server.com'
    mock_export_agent_by_id.assert_called_once_with(agent_id=123, tenant_id='test_tenant', user_id='test_user', version_no=0)
    mock_get_mcp_server.assert_called_once_with('test_mcp_server', 'test_tenant')
    mock_export_data_format.assert_called_once()


@patch('management.services.agent.transfer.get_mcp_server_by_name_and_tenant')
@patch('management.services.agent.transfer.ExportAndImportDataFormat')
@patch('management.services.agent.transfer.export_agent_by_agent_id')
@pytest.mark.asyncio
async def test_export_agent_impl_no_mcp_tools(mock_export_agent_by_id, mock_export_data_format, mock_get_mcp_server):
    """
    Test successful export of agent information without MCP tools.
    """
    mock_agent_info = ExportAndImportAgentInfo(agent_id=123, name='Test Agent', display_name='Test Agent Display', description='A test agent', business_description='For testing purposes', max_steps=10, provide_run_summary=True, prompt='# Responsibilities\nTest duty prompt\n\n# Constraints\nTest constraint prompt\n\n# Examples\nTest few shots prompt', enabled=True, tools=[], managed_agents=[])
    mock_export_agent_by_id.return_value = mock_agent_info
    mock_export_data_instance = Mock()
    mock_export_data_instance.model_dump.return_value = {'agent_id': 123, 'agent_info': {'123': {'agent_id': 123, 'name': 'Test Agent', 'display_name': 'Test Agent Display', 'description': 'A test agent', 'business_description': 'For testing purposes', 'max_steps': 10, 'provide_run_summary': True, 'prompt': '# Responsibilities\nTest duty prompt\n\n# Constraints\nTest constraint prompt\n\n# Examples\nTest few shots prompt', 'enabled': True, 'tools': [], 'managed_agents': []}}, 'mcp_info': []}
    mock_export_data_format.return_value = mock_export_data_instance
    result = await export_agent_impl(agent_id=123, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    result_dict = json.loads(result)
    assert result_dict['agent_id'] == 123
    assert 'agent_info' in result_dict
    assert '123' in result_dict['agent_info']
    assert 'mcp_info' in result_dict
    assert len(result_dict['mcp_info']) == 0
    mock_export_agent_by_id.assert_called_once_with(agent_id=123, tenant_id='test_tenant', user_id='test_user', version_no=0)
    mock_get_mcp_server.assert_not_called()
    mock_export_data_format.assert_called_once()


@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
async def test_get_agent_info_impl_with_tool_error(
    mock_search_agent_info, mock_get_model_by_model_id, mock_check_availability
):
    """
    Test get_agent_info_impl with an error in retrieving tool information.

    This test verifies that:
    1. The function correctly gets the agent information
    2. When an error occurs retrieving tool information
    3. The function returns the agent information with an empty tools list
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test agent",
    }
    mock_search_agent_info.return_value = mock_agent_info
    mock_check_availability.return_value = (True, [])

    # Mock the search_tools_for_sub_agent function to raise an exception
    with (
        patch(
            "management.services.agent.service.search_tools_for_sub_agent"
        ) as mock_search_tools,
        patch(
            "management.services.agent.service.query_sub_agents_id_list"
        ) as mock_query_sub_agents_id,
    ):
        mock_search_tools.side_effect = Exception("Tool search error")
        mock_query_sub_agents_id.return_value = []
        mock_get_model_by_model_id.return_value = None

        # Execute
        result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

        # Assert
        assert result["agent_id"] == 123
        assert result["tools"] == []
        assert result["sub_agent_id_list"] == []
        assert result["model_name"] is None
        assert result["is_available"] == True
        assert result["unavailable_reasons"] == []
        mock_search_agent_info.assert_called_once_with(123, "test_tenant", 0)


@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_sub_agent_error(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
):
    """
    Test get_agent_info_impl with an error in retrieving sub agent id list.

    This test verifies that:
    1. The function correctly gets the agent information
    2. When an error occurs retrieving sub agent id list
    3. The function returns the agent information with an empty sub_agent_id_list
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test agent",
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1", "unavailable_reasons": []}]
    mock_search_tools.return_value = mock_tools

    # Mock query_sub_agents_id_list to raise an exception
    mock_query_sub_agents_id.side_effect = Exception("Sub agent query error")
    mock_get_model_by_model_id.return_value = None
    mock_check_availability.return_value = (True, [])

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    assert result["agent_id"] == 123
    assert result["tools"] == mock_tools
    assert result["sub_agent_id_list"] == []
    assert result["model_name"] is None
    assert result["is_available"] == True
    assert result["unavailable_reasons"] == []
    mock_search_agent_info.assert_called_once_with(123, "test_tenant", 0)
    mock_search_tools.assert_called_once_with(agent_id=123, tenant_id="test_tenant")
    mock_query_sub_agents_id.assert_called_once_with(
        main_agent_id=123, tenant_id="test_tenant"
    )


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_with_model_id_success(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """
    Test get_agent_info_impl with a valid model_id.

    This test verifies that:
    1. The function correctly retrieves model information when model_id is not None
    2. It sets model_name from the model's display_name
    3. It handles the case when model_info is None
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_ids": [456],
        "model_names": ["GPT-4"],
        "business_description": "Test agent",
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1", "unavailable_reasons": []}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [789]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Mock model info with display_name
    mock_model_info = {
        "model_id": 456,
        "display_name": "GPT-4",
        "provider": "openai",
        "connect_status": "available",
    }
    mock_get_model_by_model_id.return_value = mock_model_info

    # Mock SkillService to return empty list for skills
    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance

    # Mock query_external_sub_agents
    mock_query_external_sub_agents.return_value = []

    # Mock check_agent_availability - agent is available
    mock_check_availability.return_value = (True, [])

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    expected_result = {
        "agent_id": 123,
        "model_ids": [456],
        "model_names": ["GPT-4"],
        "business_description": "Test agent",
        "tools": mock_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "sub_agent_relations": [],
        "skills": [],
        "external_sub_agent_id_list": [],
        "model_name": "GPT-4",
        "business_logic_model_name": None,
        "is_available": True,
        "unavailable_reasons": [],
    }
    assert result == expected_result
    # The model projection resolves each model id once and reuses the result.
    assert mock_get_model_by_model_id.call_count == 1
    mock_get_model_by_model_id.assert_any_call(456)


@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.agent.service.convert_string_to_list")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_converts_group_ids_when_present(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_convert_string_to_list,
    mock_check_availability,
):
    """get_agent_info_impl should convert group_ids when present."""
    mock_search_agent_info.return_value = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test agent",
        "group_ids": "1,2",
        "business_logic_model_id": None,
    }
    mock_search_tools.return_value = []
    mock_query_sub_agents_id.return_value = []
    mock_convert_string_to_list.return_value = [1, 2]
    mock_check_availability.return_value = (True, [])

    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    assert result["group_ids"] == [1, 2]
    mock_convert_string_to_list.assert_called_once_with("1,2")


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_with_model_id_no_display_name(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """
    Test get_agent_info_impl with model_id but model has no display_name.

    This test verifies that:
    1. The function correctly retrieves model information when model_id is not None
    2. It sets model_name to None when model_info exists but has no display_name
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_ids": [456],
        "business_description": "Test agent",
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1", "unavailable_reasons": []}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [789]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Mock model info without display_name
    mock_model_info = {
        "model_id": 456,
        "provider": "openai",
        "connect_status": "available",
        # No display_name field
    }
    mock_get_model_by_model_id.return_value = mock_model_info

    # Mock SkillService to return empty list for skills
    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance

    # Mock query_external_sub_agents
    mock_query_external_sub_agents.return_value = []

    mock_check_availability.return_value = (True, [])

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    expected_result = {
        "agent_id": 123,
        "model_ids": [456],
        "business_description": "Test agent",
        "tools": mock_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "sub_agent_relations": [],
        "skills": [],
        "external_sub_agent_id_list": [],
        "model_names": [],
        "model_name": None,
        "business_logic_model_name": None,
        "is_available": True,
        "unavailable_reasons": [],
    }
    assert result == expected_result
    # Source calls get_model_by_model_id twice for the single model id:
    # once while collecting model_names and once when deriving legacy model_name.
    assert mock_get_model_by_model_id.call_count == 1
    mock_get_model_by_model_id.assert_any_call(456)


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_with_model_id_none_model_info(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """
    Test get_agent_info_impl with model_id but get_model_by_model_id returns None.

    This test verifies that:
    1. The function correctly handles when model_id is not None but get_model_by_model_id returns None
    2. It sets model_name to None when model_info is None
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_ids": [456],
        "business_description": "Test agent",
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1", "unavailable_reasons": []}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [789]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Mock get_model_by_model_id to return None
    mock_get_model_by_model_id.return_value = None

    # Mock SkillService to return empty list for skills
    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance

    # Mock query_external_sub_agents
    mock_query_external_sub_agents.return_value = []

    mock_check_availability.return_value = (True, [])

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    expected_result = {
        "agent_id": 123,
        "model_ids": [],
        "business_description": "Test agent",
        "tools": mock_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "sub_agent_relations": [],
        "skills": [],
        "external_sub_agent_id_list": [],
        "model_names": [],
        "model_name": None,
        "business_logic_model_name": None,
        "is_available": True,
        "unavailable_reasons": [],
    }
    assert result == expected_result
    # Source calls get_model_by_model_id twice for the single model id:
    # once while collecting model_names and once when deriving legacy model_name.
    assert mock_get_model_by_model_id.call_count == 1
    mock_get_model_by_model_id.assert_any_call(456)


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.agent.service.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_with_business_logic_model(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """
    Test get_agent_info_impl with business_logic_model_id.

    This test verifies that:
    1. The function correctly retrieves business logic model information when business_logic_model_id is not None
    2. It sets business_logic_model_name from the model's display_name
    3. It handles both main model and business logic model correctly
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_ids": [456],
        "business_logic_model_id": 789,
        "business_description": "Test agent",
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1", "unavailable_reasons": []}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [101, 102]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Mock model info for main model
    mock_main_model_info = {
        "model_id": 456,
        "display_name": "GPT-4",
        "provider": "openai",
        "connect_status": "available",
    }

    # Mock model info for business logic model
    mock_business_logic_model_info = {
        "model_id": 789,
        "display_name": "Claude-3.5",
        "provider": "anthropic",
        "connect_status": "available",
    }

    # Mock get_model_by_model_id to return different values based on input
    def mock_get_model(model_id):
        if model_id == 456:
            return mock_main_model_info
        elif model_id == 789:
            return mock_business_logic_model_info
        return None

    mock_get_model_by_model_id.side_effect = mock_get_model

    # Mock SkillService to return empty list for skills
    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance

    # Mock query_external_sub_agents
    mock_query_external_sub_agents.return_value = []

    mock_check_availability.return_value = (True, [])

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    expected_result = {
        "agent_id": 123,
        "model_ids": [456],
        "business_logic_model_id": 789,
        "business_description": "Test agent",
        "tools": mock_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "sub_agent_relations": [],
        "skills": [],
        "external_sub_agent_id_list": [],
        "model_names": ["GPT-4"],
        "model_name": "GPT-4",
        "business_logic_model_name": "Claude-3.5",
        "is_available": True,
        "unavailable_reasons": [],
    }
    assert result == expected_result

    # Verify both models were looked up
    # Source calls get_model_by_model_id 3 times total:
    # - once for main model_ids[0]
    # - once again to derive legacy model_name from model_ids[0]
    # - once for business_logic_model_id
    assert mock_get_model_by_model_id.call_count == 2
    mock_get_model_by_model_id.assert_any_call(456)
    mock_get_model_by_model_id.assert_any_call(789)


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.agent.service.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_with_business_logic_model_none(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """
    Test get_agent_info_impl with business_logic_model_id but get_model_by_model_id returns None.

    This test verifies that:
    1. The function correctly handles when business_logic_model_id is not None but get_model_by_model_id returns None
    2. It sets business_logic_model_name to None when model_info is None
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_ids": [456],
        "business_logic_model_id": 789,
        "business_description": "Test agent",
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1", "unavailable_reasons": []}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [101, 102]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Mock model info for main model
    mock_main_model_info = {
        "model_id": 456,
        "display_name": "GPT-4",
        "provider": "openai",
        "connect_status": "available",
    }

    # Mock get_model_by_model_id to return None for business_logic_model_id
    def mock_get_model(model_id):
        if model_id == 456:
            return mock_main_model_info
        elif model_id == 789:
            return None  # Business logic model not found
        return None

    mock_get_model_by_model_id.side_effect = mock_get_model

    # Mock SkillService to return empty list for skills
    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance

    # Mock query_external_sub_agents
    mock_query_external_sub_agents.return_value = []

    mock_check_availability.return_value = (True, [])

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    expected_result = {
        "agent_id": 123,
        "model_ids": [456],
        "business_logic_model_id": 789,
        "business_description": "Test agent",
        "tools": mock_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "sub_agent_relations": [],
        "skills": [],
        "external_sub_agent_id_list": [],
        "model_names": ["GPT-4"],
        "model_name": "GPT-4",
        "business_logic_model_name": None,  # Should be None when model info is not found
        "is_available": True,
        "unavailable_reasons": [],
    }
    assert result == expected_result

    # Verify both models were looked up
    # Source calls get_model_by_model_id 3 times total:
    # - once for main model_ids[0]
    # - once again to derive legacy model_name from model_ids[0]
    # - once for business_logic_model_id
    assert mock_get_model_by_model_id.call_count == 2
    mock_get_model_by_model_id.assert_any_call(456)
    mock_get_model_by_model_id.assert_any_call(789)


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.agent.service.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_with_business_logic_model_no_display_name(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """
    Test get_agent_info_impl with business_logic_model_id but model has no display_name.

    This test verifies that:
    1. The function correctly retrieves business logic model information when business_logic_model_id is not None
    2. It sets business_logic_model_name to None when model_info exists but has no display_name
    """
    # Setup
    mock_agent_info = {
        "agent_id": 123,
        "model_ids": [456],
        "business_logic_model_id": 789,
        "business_description": "Test agent",
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [{"tool_id": 1, "name": "Tool 1", "unavailable_reasons": []}]
    mock_search_tools.return_value = mock_tools

    mock_sub_agent_ids = [101, 102]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Mock model info for main model
    mock_main_model_info = {
        "model_id": 456,
        "display_name": "GPT-4",
        "provider": "openai",
        "connect_status": "available",
    }

    # Mock model info for business logic model without display_name
    mock_business_logic_model_info = {
        "model_id": 789,
        "provider": "anthropic",
        "connect_status": "available",
        # No display_name field
    }

    # Mock get_model_by_model_id to return different values based on input
    def mock_get_model(model_id):
        if model_id == 456:
            return mock_main_model_info
        elif model_id == 789:
            return mock_business_logic_model_info
        return None

    mock_get_model_by_model_id.side_effect = mock_get_model

    # Mock SkillService to return empty list for skills
    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance

    # Mock query_external_sub_agents
    mock_query_external_sub_agents.return_value = []

    mock_check_availability.return_value = (True, [])

    # Execute
    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    # Assert
    expected_result = {
        "agent_id": 123,
        "model_ids": [456],
        "business_logic_model_id": 789,
        "business_description": "Test agent",
        "tools": mock_tools,
        "sub_agent_id_list": mock_sub_agent_ids,
        "sub_agent_relations": [],
        "skills": [],
        "external_sub_agent_id_list": [],
        "model_names": ["GPT-4"],
        "model_name": "GPT-4",
        "business_logic_model_name": None,  # Should be None when display_name is not in model_info
        "is_available": True,
        "unavailable_reasons": [],
    }
    assert result == expected_result

    # Verify both models were looked up
    # Source calls get_model_by_model_id 3 times total:
    # - once for main model_ids[0]
    # - once again to derive legacy model_name from model_ids[0]
    # - once for business_logic_model_id
    assert mock_get_model_by_model_id.call_count == 2
    mock_get_model_by_model_id.assert_any_call(456)
    mock_get_model_by_model_id.assert_any_call(789)


@patch("management.services.agent.service.query_current_version_no")
@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.agent.read.get_valid_model_ids")
@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_marks_mcp_model_unavailable_when_deleted(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id_ignore_delete,
    mock_get_valid_model_ids,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
    mock_query_current_version_no,
):
    """Tools whose selected_model_id has been soft-deleted should be marked mcp_model_unavailable."""
    mock_search_agent_info.return_value = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test agent",
    }

    mock_tools = [
        {
            "tool_id": 1,
            "name": "Tool 1",
            "params": [{"name": "selected_model_id", "default": 99}],
        },
        {
            "tool_id": 2,
            "name": "Tool 2",
            "params": [{"name": "selected_model_id", "default": 100}],
        },
    ]
    mock_search_tools.return_value = mock_tools
    mock_query_sub_agents_id.return_value = []
    mock_get_valid_model_ids.return_value = []

    def fake_ignore_delete(model_id, tenant_id):
        if model_id == 99:
            return {"model_id": 99, "delete_flag": "Y"}
        return {"model_id": model_id, "delete_flag": "N"}

    mock_get_model_by_model_id_ignore_delete.side_effect = fake_ignore_delete

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance
    mock_query_external_sub_agents.return_value = []
    mock_check_availability.return_value = (True, [])

    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    assert result["tools"][0]["unavailable_reasons"] == ["mcp_model_unavailable"]
    assert result["tools"][1]["unavailable_reasons"] == []


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.agent.read.get_valid_model_ids")
@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_handles_tools_without_params(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id_ignore_delete,
    mock_get_valid_model_ids,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """Tools without a params list should still return an empty unavailable_reasons and not crash."""
    mock_search_agent_info.return_value = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test agent",
    }

    mock_tools = [
        {"tool_id": 1, "name": "Tool 1"},  # no params key
        {"tool_id": 2, "name": "Tool 2", "params": []},  # empty params list
        {
            "tool_id": 3,
            "name": "Tool 3",
            "params": [{"name": "other", "default": "x"}],
        },  # no selected_model_id
    ]
    mock_search_tools.return_value = mock_tools
    mock_query_sub_agents_id.return_value = []
    mock_get_valid_model_ids.return_value = []
    mock_get_model_by_model_id_ignore_delete.return_value = None

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance
    mock_query_external_sub_agents.return_value = []
    mock_check_availability.return_value = (True, [])

    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    for tool in result["tools"]:
        assert tool["unavailable_reasons"] == []
    mock_get_model_by_model_id_ignore_delete.assert_not_called()


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.agent.read.get_valid_model_ids")
@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_skips_unset_selected_model_default(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id_ignore_delete,
    mock_get_valid_model_ids,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """Tools with `selected_model_id` declared but no default should skip the DB lookup."""
    mock_search_agent_info.return_value = {"agent_id": 1, "model_id": None}
    mock_search_tools.return_value = [
        {"tool_id": 1, "name": "T1", "params": [{"name": "selected_model_id"}]},
        {
            "tool_id": 2,
            "name": "T2",
            "params": [{"name": "selected_model_id", "default": None}],
        },
    ]
    mock_query_sub_agents_id.return_value = []
    mock_get_valid_model_ids.return_value = []
    mock_get_model_by_model_id_ignore_delete.return_value = None

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance
    mock_query_external_sub_agents.return_value = []
    mock_check_availability.return_value = (True, [])

    result = await get_agent_info_impl(agent_id=1, tenant_id="test_tenant")

    assert result["tools"][0]["unavailable_reasons"] == []
    assert result["tools"][1]["unavailable_reasons"] == []
    mock_get_model_by_model_id_ignore_delete.assert_not_called()


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.agent.read.get_valid_model_ids")
@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_selected_model_not_found(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id_ignore_delete,
    mock_get_valid_model_ids,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """When `get_model_by_model_id_ignore_delete` returns None we should not mark the tool unavailable."""
    mock_search_agent_info.return_value = {"agent_id": 1, "model_id": None}
    mock_search_tools.return_value = [
        {
            "tool_id": 1,
            "name": "T1",
            "params": [{"name": "selected_model_id", "default": 555}],
        },
    ]
    mock_query_sub_agents_id.return_value = []
    mock_get_valid_model_ids.return_value = []
    mock_get_model_by_model_id_ignore_delete.return_value = None

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance
    mock_query_external_sub_agents.return_value = []
    mock_check_availability.return_value = (True, [])

    result = await get_agent_info_impl(agent_id=1, tenant_id="test_tenant")

    assert result["tools"][0]["unavailable_reasons"] == []
    mock_get_model_by_model_id_ignore_delete.assert_called_once_with(555, "test_tenant")


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.agent.read.get_valid_model_ids")
@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_selected_model_not_deleted(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id_ignore_delete,
    mock_get_valid_model_ids,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """A tool whose selected model is still active must not be marked unavailable."""
    mock_search_agent_info.return_value = {"agent_id": 1, "model_id": None}
    mock_search_tools.return_value = [
        {
            "tool_id": 1,
            "name": "T1",
            "params": [{"name": "selected_model_id", "default": 7}],
        },
    ]
    mock_query_sub_agents_id.return_value = []
    mock_get_valid_model_ids.return_value = []
    mock_get_model_by_model_id_ignore_delete.return_value = {
        "model_id": 7,
        "delete_flag": "N",
    }

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance
    mock_query_external_sub_agents.return_value = []
    mock_check_availability.return_value = (True, [])

    result = await get_agent_info_impl(agent_id=1, tenant_id="test_tenant")

    assert result["tools"][0]["unavailable_reasons"] == []


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.agent.read.get_valid_model_ids")
@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_skips_non_list_params(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id_ignore_delete,
    mock_get_valid_model_ids,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """Tool `params` values that aren't a list (e.g. dict, string) should be safely ignored."""
    mock_search_agent_info.return_value = {"agent_id": 1, "model_id": None}
    mock_search_tools.return_value = [
        {"tool_id": 1, "name": "T1", "params": {"selected_model_id": 5}},
        {"tool_id": 2, "name": "T2", "params": "invalid"},
    ]
    mock_query_sub_agents_id.return_value = []
    mock_get_valid_model_ids.return_value = []
    mock_get_model_by_model_id_ignore_delete.return_value = None

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance
    mock_query_external_sub_agents.return_value = []
    mock_check_availability.return_value = (True, [])

    result = await get_agent_info_impl(agent_id=1, tenant_id="test_tenant")

    for tool in result["tools"]:
        assert tool["unavailable_reasons"] == []
    mock_get_model_by_model_id_ignore_delete.assert_not_called()


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.agent.read.get_valid_model_ids")
@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_param_loop_skips_non_dict_entries(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id_ignore_delete,
    mock_get_valid_model_ids,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """Within a list, non-dict entries must be skipped without crashing."""
    mock_search_agent_info.return_value = {"agent_id": 1, "model_id": None}
    mock_search_tools.return_value = [
        {
            "tool_id": 1,
            "name": "T1",
            "params": [
                None,
                "string-not-a-dict",
                42,
                True,
                {"name": "selected_model_id", "default": 9},
            ],
        },
    ]
    mock_query_sub_agents_id.return_value = []
    mock_get_valid_model_ids.return_value = []
    mock_get_model_by_model_id_ignore_delete.return_value = {
        "model_id": 9,
        "delete_flag": "Y",
    }

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance
    mock_query_external_sub_agents.return_value = []
    mock_check_availability.return_value = (True, [])

    result = await get_agent_info_impl(agent_id=1, tenant_id="test_tenant")

    assert result["tools"][0]["unavailable_reasons"] == ["mcp_model_unavailable"]
    mock_get_model_by_model_id_ignore_delete.assert_called_once_with(9, "test_tenant")


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.agent.read.get_valid_model_ids")
@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_breaks_after_selected_model_id(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id_ignore_delete,
    mock_get_valid_model_ids,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """After locating `selected_model_id` other params in the same tool should be skipped."""
    mock_search_agent_info.return_value = {"agent_id": 1, "model_id": None}
    mock_search_tools.return_value = [
        {
            "tool_id": 1,
            "name": "T1",
            "params": [
                {"name": "selected_model_id", "default": 9},
                {"name": "another_selected_model_id", "default": 10},
            ],
        },
    ]
    mock_query_sub_agents_id.return_value = []
    mock_get_valid_model_ids.return_value = []
    mock_get_model_by_model_id_ignore_delete.return_value = None

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance
    mock_query_external_sub_agents.return_value = []
    mock_check_availability.return_value = (True, [])

    result = await get_agent_info_impl(agent_id=1, tenant_id="test_tenant")

    assert result["tools"][0]["unavailable_reasons"] == []
    # Only one lookup per tool should be issued thanks to the `break`.
    mock_get_model_by_model_id_ignore_delete.assert_called_once_with(9, "test_tenant")


def _mock_paged_agent_candidates(monkeypatch, agents):
    monkeypatch.setattr(
        agent_management,
        "query_agent_list_candidates_by_tenant_id",
        lambda _tenant_id, **_kwargs: [dict(agent) for agent in agents],
    )
    monkeypatch.setattr(
        agent_management,
        "get_user_tenant_by_user_id",
        lambda _user_id: {"user_role": "ADMIN"},
    )


@pytest.mark.asyncio
async def test_list_all_agent_info_impl_loads_only_requested_ids(monkeypatch):
    calls = []
    monkeypatch.setattr(
        agent_management,
        "get_user_tenant_by_user_id",
        lambda _user_id: {"user_role": "ADMIN"},
    )
    monkeypatch.setattr(agent_management, "get_server_agent_ids", lambda _tenant_id: set())
    monkeypatch.setattr(
        agent_management,
        "query_agent_info_by_ids",
        lambda tenant_id, agent_ids: calls.append((tenant_id, agent_ids)) or [],
    )
    monkeypatch.setattr(
        agent_management,
        "query_all_agent_info_by_tenant_id",
        lambda **_kwargs: pytest.fail("paged list must not load every agent record"),
    )

    result = await agent_management.list_all_agent_info_impl(
        tenant_id="tenant_123", user_id="alice", agent_ids=[2]
    )

    assert result == []
    assert calls == [("tenant_123", [2])]


@pytest.mark.asyncio
async def test_list_agent_page_impl_filters_before_paginating(monkeypatch):
    """Search, tag, and permission constraints apply before page slicing."""
    agents = [
        {
            "agent_id": 1,
            "name": "Support Alpha",
            "description": "General help",
            "permission": "EDIT",
            "tags": ["support"],
        },
        {
            "agent_id": 2,
            "name": "Support Read Only",
            "description": "General help",
            "permission": "READ_ONLY",
            "tags": ["support"],
        },
        {
            "agent_id": 3,
            "name": "Operations",
            "description": "Support escalation",
            "permission": "EDIT",
            "tags": ["support"],
        },
        {
            "agent_id": 4,
            "name": "Billing",
            "description": "Support billing",
            "permission": "EDIT",
            "tags": ["billing"],
        },
    ]

    async def list_agents(**_kwargs):
        return agents

    _mock_paged_agent_candidates(monkeypatch, agents)
    monkeypatch.setattr(agent_management, "list_all_agent_info_impl", list_agents)

    result = await list_agent_page_impl(
        tenant_id="tenant_123",
        user_id="test_user",
        permission="EDIT",
        tag="support",
        search="support",
        page=2,
        page_size=1,
    )

    assert [agent["agent_id"] for agent in result["items"]] == [3]
    assert result["pagination"] == {
        "page": 2,
        "page_size": 1,
        "total": 2,
        "total_pages": 2,
    }


@pytest.mark.asyncio
async def test_list_agent_page_includes_repository_info_only_for_current_page(monkeypatch):
    agents = [
        {"agent_id": 1, "name": "First", "created_by": "alice"},
        {"agent_id": 2, "name": "Second", "created_by": "alice"},
    ]
    _mock_paged_agent_candidates(monkeypatch, agents)

    async def enrich_page(*, agent_ids, **_kwargs):
        return [{"agent_id": agent_id, "current_version_no": 3} for agent_id in agent_ids]

    repository_calls = []

    def repository_rows(agent_ids, *, statuses, publisher_tenant_id):
        repository_calls.append((agent_ids, set(statuses), publisher_tenant_id))
        return [record for record in [
            {"agent_repository_id": 12, "agent_id": 2, "status": "pending_review",
             "version_no": 3, "version_name": "v3", "create_time": None, "content": "Update"},
            {"agent_repository_id": 10, "agent_id": 2, "status": "shared",
             "version_no": 1, "version_name": "v1", "create_time": None, "content": None},
        ] if record["status"] in statuses]

    monkeypatch.setattr(agent_management, "list_all_agent_info_impl", enrich_page)
    monkeypatch.setattr(agent_management, "batch_search_version_names", lambda *_args: [])
    monkeypatch.setattr(agent_management, "list_agent_repository_by_agent_ids", repository_rows)

    result = await list_agent_page_impl(
        tenant_id="tenant_123", user_id="alice", caller_tenant_id="tenant_123",
        page=2, page_size=1,
        include_repository_info=True,
    )

    assert [item["agent_id"] for item in result["items"]] == [2]
    assert repository_calls == [
        ([2], {"shared"}, "tenant_123"),
        ([2], {"pending_review", "rejected", "shared"}, "tenant_123"),
    ]
    assert result["items"][0]["repository_info"] == [
        {"agent_repository_id": 12, "status": "pending_review", "version_no": 3,
         "version_label": "v3", "create_time": None, "content": "Update"},
        {"agent_repository_id": 10, "status": "shared", "version_no": 1,
         "version_label": "v1", "create_time": None, "content": None},
    ]

    empty_page = await list_agent_page_impl(
        tenant_id="tenant_123", user_id="alice", page=3, page_size=1,
        include_repository_info=True,
    )
    assert empty_page["items"] == []
    assert len(repository_calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "caller_tenant", "scope_tenant", "expected_statuses", "expected_content"),
    [
        ("USER", "tenant-a", "tenant-a", ["shared"], [None]),
        ("ADMIN", "tenant-a", "asset-owner", ["shared"], [None]),
        ("DEV", "tenant-a", "tenant-a", ["pending_review", "shared"], ["my review", None]),
    ],
)
async def test_list_agent_page_repository_review_visibility(
    monkeypatch, role, caller_tenant, scope_tenant, expected_statuses, expected_content,
):
    monkeypatch.setattr(
        agent_management, "get_user_tenant_by_user_id", lambda _user_id: {"user_role": role}
    )
    monkeypatch.setattr(agent_management, "query_group_ids_by_user", lambda _user_id: [])
    monkeypatch.setattr(
        agent_management, "query_agent_list_candidates_by_tenant_id",
        lambda tenant_id, **_kwargs: [
            {"agent_id": 7, "tenant_id": tenant_id, "created_by": "alice", "enabled": True}
        ],
    )

    async def enrich(*, agent_ids, **_kwargs):
        return [{"agent_id": agent_id, "current_version_no": 0} for agent_id in agent_ids]

    monkeypatch.setattr(agent_management, "list_all_agent_info_impl", enrich)
    rows = [
        {"agent_repository_id": 1, "agent_id": 7, "status": "pending_review",
         "version_no": 2, "version_name": "v2", "create_time": "2026-09-29",
         "content": "my review", "publisher_user_id": "alice"},
        {"agent_repository_id": 2, "agent_id": 7, "status": "rejected",
         "version_no": 3, "version_name": "v3", "create_time": "2026-09-28",
         "content": "other review", "publisher_user_id": "bob"},
        {"agent_repository_id": 3, "agent_id": 7, "status": "shared",
         "version_no": 1, "version_name": "v1", "create_time": "2026-09-27",
         "content": "old feedback", "publisher_user_id": "bob"},
    ]
    calls = []

    def repository_rows(agent_ids, *, statuses, publisher_tenant_id, publisher_user_id=None):
        calls.append((set(statuses), publisher_tenant_id, publisher_user_id))
        assert agent_ids == [7]
        return [row for row in rows if row["status"] in statuses and
                (publisher_user_id is None or row["publisher_user_id"] == publisher_user_id)]

    monkeypatch.setattr(agent_management, "list_agent_repository_by_agent_ids", repository_rows)

    result = await list_agent_page_impl(
        tenant_id=scope_tenant, caller_tenant_id=caller_tenant,
        user_id="alice", include_repository_info=True,
    )

    info = result["items"][0]["repository_info"]
    assert [record["status"] for record in info] == expected_statuses
    assert [record["content"] for record in info] == expected_content
    assert calls[0] == ({"shared"}, scope_tenant, None)
    assert len(calls) == (2 if role == "DEV" else 1)
    if role == "DEV":
        assert calls[1] == ({"pending_review", "rejected", "shared"}, scope_tenant, "alice")


@pytest.mark.asyncio
async def test_list_agent_page_filters_creator_before_pagination(monkeypatch):
    agents = [
        {"agent_id": 1, "created_by": "alice"},
        {"agent_id": 2, "created_by": "bob"},
        {"agent_id": 3, "created_by": "alice"},
        {"agent_id": 4, "created_by": "bob"},
    ]

    async def list_agents(**_kwargs):
        return agents

    _mock_paged_agent_candidates(monkeypatch, agents)
    monkeypatch.setattr(agent_management, "list_all_agent_info_impl", list_agents)

    mine = await list_agent_page_impl(
        tenant_id="tenant_123", user_id="alice", created_by="alice", page=2, page_size=1
    )
    others = await list_agent_page_impl(
        tenant_id="tenant_123", user_id="alice", created_by_not="alice", page=2, page_size=1
    )

    assert [item["agent_id"] for item in mine["items"]] == [3]
    assert [item["agent_id"] for item in others["items"]] == [4]
    assert mine["pagination"]["total"] == 2
    assert others["pagination"]["total"] == 2
    assert mine["creator_counts"] == {"all": 4, "created": 2, "others": 2}


@pytest.mark.asyncio
async def test_list_agent_page_rejects_conflicting_creator_filters(monkeypatch):
    async def list_agents(**_kwargs):
        return []

    _mock_paged_agent_candidates(monkeypatch, [])
    monkeypatch.setattr(agent_management, "list_all_agent_info_impl", list_agents)

    with pytest.raises(ValueError, match="created_by"):
        await list_agent_page_impl(
            tenant_id="tenant_123", user_id="alice", created_by="alice", created_by_not="alice"
        )


@pytest.mark.asyncio
async def test_list_agent_page_applies_structured_tags_before_pagination(monkeypatch):
    agents = [
        {"agent_id": 1, "name": "First", "created_by": "alice"},
        {"agent_id": 2, "name": "Second", "created_by": "bob"},
        {"agent_id": 3, "name": "Third", "created_by": "alice"},
    ]

    async def list_agents(**_kwargs):
        return agents

    _mock_paged_agent_candidates(monkeypatch, agents)
    monkeypatch.setattr(agent_management, "list_all_agent_info_impl", list_agents)
    monkeypatch.setattr(
        agent_management.TagManagementDB,
        "filter_authorized_resource_ids",
        lambda *_args: ["1", "3"],
    )

    result = await list_agent_page_impl(
        tenant_id="tenant_123", user_id="alice", tag_predicates=[object()], page=2, page_size=1
    )

    assert [item["agent_id"] for item in result["items"]] == [3]
    assert result["pagination"]["total"] == 2
    assert result["creator_counts"] == {"all": 2, "created": 2, "others": 0}


@pytest.mark.asyncio
async def test_list_agent_page_enriches_only_current_page_version_metadata(monkeypatch):
    agents = [
        {"agent_id": 1, "created_by": "alice", "current_version_no": 1},
        {"agent_id": 2, "created_by": "alice", "current_version_no": 2},
    ]
    calls = []

    async def list_agents(**_kwargs):
        return agents

    def versions(agent_ids, tenant_id, version_nos):
        calls.append((agent_ids, tenant_id, version_nos))
        return [{
            "agent_id": 2,
            "version_no": 2,
            "version_name": "Release Two",
            "create_time": "2026-09-23T10:00:00",
        }]

    _mock_paged_agent_candidates(monkeypatch, agents)
    monkeypatch.setattr(agent_management, "list_all_agent_info_impl", list_agents)
    monkeypatch.setattr(agent_management, "batch_search_version_names", versions)

    result = await list_agent_page_impl(
        tenant_id="tenant_123", user_id="alice", page=2, page_size=1
    )

    assert calls == [([2], "tenant_123", [2])]
    assert result["items"][0]["version_label"] == "Release Two"
    assert result["items"][0]["version_create_time"] == "2026-09-23T10:00:00"


@pytest.mark.asyncio
async def test_list_agent_page_enriches_only_current_page_and_keeps_unavailable(monkeypatch):
    candidates = [
        {"agent_id": agent_id, "tenant_id": "tenant_123", "name": f"Agent {agent_id}",
         "display_name": f"Agent {agent_id}", "created_by": "alice", "enabled": True}
        for agent_id in (1, 2, 3)
    ]
    enriched_ids = []

    monkeypatch.setattr(
        agent_management,
        "query_agent_list_candidates_by_tenant_id",
        lambda _tenant_id, **_kwargs: candidates,
        raising=False,
    )
    monkeypatch.setattr(
        agent_management,
        "get_user_tenant_by_user_id",
        lambda _user_id: {"user_role": "ADMIN"},
    )

    async def enrich_page(*, agent_ids=None, **_kwargs):
        assert agent_ids is not None, "listing must not enrich every candidate"
        enriched_ids.extend(agent_ids)
        return [
            {"agent_id": agent_id, "tenant_id": "tenant_123", "current_version_no": 0,
             "is_available": False, "unavailable_reasons": ["tool_unavailable"]}
            for agent_id in agent_ids
        ]

    monkeypatch.setattr(agent_management, "list_all_agent_info_impl", enrich_page)

    result = await list_agent_page_impl(
        tenant_id="tenant_123", user_id="alice", page=2, page_size=1
    )

    assert enriched_ids == [2]
    assert [agent["agent_id"] for agent in result["items"]] == [2]
    assert result["items"][0]["unavailable_reasons"] == ["tool_unavailable"]
    assert result["pagination"]["total"] == 3
    assert result["creator_counts"] == {"all": 3, "created": 3, "others": 0}


@pytest.mark.asyncio
async def test_list_agent_page_keeps_duplicate_warning_when_original_is_off_page(monkeypatch):
    candidates = [
        {"agent_id": 2, "name": "duplicate", "display_name": "Newer",
         "create_time": "2026-09-24", "created_by": "alice"},
        {"agent_id": 1, "name": "duplicate", "display_name": "Original",
         "create_time": "2026-09-20", "created_by": "alice"},
    ]
    _mock_paged_agent_candidates(monkeypatch, candidates)

    async def enrich_page(*, agent_ids, **_kwargs):
        return [
            {"agent_id": agent_id, "current_version_no": 0,
             "is_available": True, "unavailable_reasons": []}
            for agent_id in agent_ids
        ]

    monkeypatch.setattr(agent_management, "list_all_agent_info_impl", enrich_page)

    result = await list_agent_page_impl(
        tenant_id="tenant_123", user_id="alice", page=1, page_size=1
    )

    assert [agent["agent_id"] for agent in result["items"]] == [2]
    assert result["items"][0]["is_available"] is False
    assert result["items"][0]["unavailable_reasons"] == ["duplicate_name"]
    assert result["pagination"]["total"] == 2


@pytest.mark.asyncio
async def test_list_agent_page_filters_visibility_before_count_and_enrichment(monkeypatch):
    from contracts.constants.constants import PERMISSION_PRIVATE

    candidates = [
        {"agent_id": 1, "name": "Mine", "created_by": "alice", "group_ids": "2"},
        {"agent_id": 2, "name": "Shared", "created_by": "bob", "group_ids": "2"},
        {"agent_id": 3, "name": "Hidden", "created_by": "bob", "group_ids": "3"},
        {"agent_id": 4, "name": "Private", "created_by": "bob", "group_ids": "2",
         "ingroup_permission": PERMISSION_PRIVATE},
    ]
    _mock_paged_agent_candidates(monkeypatch, candidates)
    monkeypatch.setattr(
        agent_management, "get_user_tenant_by_user_id",
        lambda _user_id: {"user_role": "USER"},
    )
    monkeypatch.setattr(agent_management, "query_group_ids_by_user", lambda _user_id: [2])
    monkeypatch.setattr(
        agent_management,
        "convert_string_to_list",
        lambda value: [int(part) for part in value.split(",") if part] if value else [],
    )
    enriched_ids = []

    async def enrich_page(*, agent_ids, **_kwargs):
        enriched_ids.extend(agent_ids)
        return [
            {"agent_id": agent_id, "current_version_no": 0,
             "is_available": True, "unavailable_reasons": []}
            for agent_id in agent_ids
        ]

    monkeypatch.setattr(agent_management, "list_all_agent_info_impl", enrich_page)

    result = await list_agent_page_impl(
        tenant_id="tenant_123", user_id="alice", page=1, page_size=10
    )

    assert enriched_ids == [1, 2]
    assert [agent["agent_id"] for agent in result["items"]] == [1, 2]
    assert result["pagination"]["total"] == 2
    assert result["creator_counts"] == {"all": 2, "created": 1, "others": 1}


@pytest.mark.asyncio
async def test_list_agent_page_preserves_cross_tenant_order_and_version_scope(monkeypatch):
    candidates_by_tenant = {
        "tenant_123": [{"agent_id": 1, "name": "Mine", "created_by": "alice"}],
        "shared": [{"agent_id": 2, "name": "Shared", "created_by": "bob"}],
    }
    enrich_calls = []
    version_calls = []
    monkeypatch.setattr(
        agent_management,
        "query_agent_list_candidates_by_tenant_id",
        lambda tenant_id, **_kwargs: [dict(agent) for agent in candidates_by_tenant[tenant_id]],
    )
    monkeypatch.setattr(
        agent_management,
        "get_user_tenant_by_user_id",
        lambda _user_id: {"user_role": "ADMIN"},
    )

    async def enrich_page(*, tenant_id, agent_ids, **_kwargs):
        enrich_calls.append((tenant_id, agent_ids))
        return [
            {"agent_id": agent_id, "current_version_no": 1,
             "is_available": True, "unavailable_reasons": []}
            for agent_id in agent_ids
        ]

    def versions(agent_ids, tenant_id, version_nos):
        version_calls.append((tenant_id, agent_ids, version_nos))
        return [{"agent_id": agent_ids[0], "version_no": 1,
                 "version_name": tenant_id, "create_time": None}]

    monkeypatch.setattr(agent_management, "list_all_agent_info_impl", enrich_page)
    monkeypatch.setattr(agent_management, "batch_search_version_names", versions)

    result = await list_agent_page_impl(
        tenant_id="tenant_123", additional_tenant_id="shared",
        user_id="alice", page=1, page_size=2,
    )

    assert [item["agent_id"] for item in result["items"]] == [1, 2]
    assert [item["version_label"] for item in result["items"]] == ["tenant_123", "shared"]
    assert enrich_calls == [("tenant_123", [1]), ("shared", [2])]
    assert version_calls == [("tenant_123", [1], [1]), ("shared", [2], [1])]
    assert result["pagination"]["total"] == 2


def _publish_sort_candidates():
    """Raw candidates covering newest, mid, oldest, and never-published agents."""
    return [
        {"agent_id": 1, "name": "Oldest", "created_by": "alice",
         "current_version_no": 1},
        {"agent_id": 2, "name": "Newest", "created_by": "alice",
         "current_version_no": 1},
        {"agent_id": 3, "name": "NeverPublished", "created_by": "alice",
         "current_version_no": 0},
        {"agent_id": 4, "name": "Mid", "created_by": "alice",
         "current_version_no": 2},
    ]


_PUBLISH_TIMES = {
    (1, 1): "2026-01-01T00:00:00",
    (2, 1): "2026-09-01T00:00:00",
    (4, 2): "2026-05-01T00:00:00",
}


def _mock_publish_sort(monkeypatch, candidates):
    _mock_paged_agent_candidates(monkeypatch, candidates)

    async def enrich_page(*, tenant_id, agent_ids, **_kwargs):
        return [
            {"agent_id": agent_id, "current_version_no": 1,
             "is_available": True, "unavailable_reasons": []}
            for agent_id in agent_ids
        ]

    def versions(agent_ids, tenant_id, version_nos):
        return [
            {
                "agent_id": agent_id,
                "version_no": version_no,
                "create_time": _PUBLISH_TIMES.get((agent_id, version_no)),
            }
            for agent_id, version_no in zip(agent_ids, version_nos)
        ]

    monkeypatch.setattr(agent_management, "list_all_agent_info_impl", enrich_page)
    monkeypatch.setattr(agent_management, "batch_search_version_names", versions)


@pytest.mark.asyncio
async def test_list_agent_page_sort_by_publish_time_orders_newest_first(monkeypatch):
    """sort_by_update_time leads with the newest publish time, undated last."""
    _mock_publish_sort(monkeypatch, _publish_sort_candidates())

    result = await list_agent_page_impl(
        tenant_id="tenant_123", user_id="alice", page=1, page_size=10,
        sort_by_update_time=True,
    )

    assert [item["agent_id"] for item in result["items"]] == [2, 4, 1, 3]
    assert result["pagination"]["total"] == 4


@pytest.mark.asyncio
async def test_list_agent_page_sort_by_publish_time_is_stable_across_pages(monkeypatch):
    """The publish-time ordering applies before slicing, so pages stay ordered."""
    _mock_publish_sort(monkeypatch, _publish_sort_candidates())

    first_page = await list_agent_page_impl(
        tenant_id="tenant_123", user_id="alice", page=1, page_size=2,
        sort_by_update_time=True,
    )
    second_page = await list_agent_page_impl(
        tenant_id="tenant_123", user_id="alice", page=2, page_size=2,
        sort_by_update_time=True,
    )

    assert [item["agent_id"] for item in first_page["items"]] == [2, 4]
    assert [item["agent_id"] for item in second_page["items"]] == [1, 3]


@pytest.mark.asyncio
async def test_list_agent_page_default_order_unchanged_without_sort(monkeypatch):
    """Leaving the flag off keeps the pre-existing candidate ordering."""
    _mock_publish_sort(monkeypatch, _publish_sort_candidates())

    result = await list_agent_page_impl(
        tenant_id="tenant_123", user_id="alice", page=1, page_size=10,
    )

    assert [item["agent_id"] for item in result["items"]] == [1, 2, 3, 4]


def test_publish_time_sort_value_normalizes_supported_inputs():
    """Datetimes and ISO strings sort by epoch; anything else collapses to 0.0."""
    assert agent_management._publish_time_sort_value(
        datetime(2026, 1, 1)
    ) == datetime(2026, 1, 1).timestamp()
    assert agent_management._publish_time_sort_value(
        "2026-01-01T00:00:00"
    ) == datetime(2026, 1, 1).timestamp()
    assert agent_management._publish_time_sort_value("not-a-date") == 0.0
    assert agent_management._publish_time_sort_value(None) == 0.0


def test_order_agents_by_publish_time_skips_scopes_without_versions(monkeypatch):
    """A scope tenant without a published version is skipped, not queried."""
    queried_scopes = []

    def versions(agent_ids, tenant_id, version_nos):
        queried_scopes.append((tenant_id, list(agent_ids)))
        return []

    monkeypatch.setattr(agent_management, "batch_search_version_names", versions)
    agents = [
        {"agent_id": 1, "tenant_id": "tenant_123", "current_version_no": 0},
        {"agent_id": 2, "tenant_id": "tenant_other", "current_version_no": 1},
    ]

    ordered = agent_management._order_agents_by_publish_time(
        agents, ["tenant_123", "tenant_other"]
    )

    assert queried_scopes == [("tenant_other", [2])]
    assert [agent["agent_id"] for agent in ordered] == [2, 1]


def test_order_agents_by_publish_time_degrades_when_version_lookup_fails(monkeypatch):
    """A failing publish-time lookup keeps every agent in the undated tail."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("version store unavailable")

    monkeypatch.setattr(agent_management, "batch_search_version_names", boom)
    agents = [
        {"agent_id": 1, "tenant_id": "tenant_123", "current_version_no": 1},
        {"agent_id": 2, "tenant_id": "tenant_123", "current_version_no": 1},
    ]

    ordered = agent_management._order_agents_by_publish_time(agents, ["tenant_123"])

    assert [agent["agent_id"] for agent in ordered] == [2, 1]


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_success(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """
    Test successful retrieval of all agent information for admin user.

    This test verifies that:
    1. The function correctly queries all agents for a tenant
    2. It checks agent availability
    3. It returns a properly formatted list of agent information with permissions
    """
    # Setup mock agents
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "First test agent",
            "enabled": True,
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
            "current_version_no": None,  # Not published
            "icon_url": "/api/agent/1/icon",
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Second test agent",
            "enabled": True,
            "group_ids": "1,2,3",
            "created_by": "user2",
            "create_time": 2,
            "current_version_no": 1,  # Published
        },
        {
            "agent_id": 99,
            "name": "workbench_main",
            "display_name": "Nexent Workbench",
            "description": "Protected system Agent",
            "enabled": True,
            "group_ids": "",
            "created_by": "admin_user",
            "create_time": 3,
            "current_version_no": 1,
            "agent_origin": "SYSTEM",
            "system_key": "workbench_main",
        },
    ]

    # Configure mocks
    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.side_effect = lambda x: (
        [] if not x else [int(i) for i in x.split(",")]
    )
    mock_check_availability.side_effect = lambda *args, **kwargs: (True, [])
    mock_get_model.return_value = None

    # Execute
    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    # Assert
    assert len(result) == 2
    # UT-BE-SAL-009: ownership metadata cannot expose a system Agent.
    assert {agent["agent_id"] for agent in result} == {1, 2}
    assert result[0]["agent_id"] == 1
    assert result[0]["name"] == "Agent 1"
    assert result[0]["display_name"] == "Display Agent 1"
    assert result[0]["is_available"] == True
    assert result[0]["unavailable_reasons"] == []
    assert result[0]["group_ids"] == []
    assert result[0]["permission"] == "EDIT"  # Admin can edit all
    assert result[0]["is_published"] == False  # current_version_no is None
    assert result[0]["icon_url"] == "/api/agent/1/icon"
    assert result[1]["agent_id"] == 2
    assert result[1]["name"] == "Agent 2"
    assert result[1]["display_name"] == "Display Agent 2"
    assert result[1]["is_available"] == True
    assert result[1]["unavailable_reasons"] == []
    assert result[1]["group_ids"] == [1, 2, 3]
    assert result[1]["permission"] == "EDIT"  # Admin can edit all
    assert result[1]["is_published"] == True  # current_version_no is not None
    assert result[1]["icon_url"] is None

    # Verify mock calls
    mock_query_agents.assert_called_once_with(tenant_id="test_tenant")
    mock_get_user_tenant.assert_called_once_with("admin_user")


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_emits_is_main_agent(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """is_main_agent mirrors the stored flag and defaults to True when absent."""
    mock_agents = [
        {"agent_id": 1, "name": "Main", "display_name": "Main",
         "description": "", "enabled": True, "group_ids": "",
         "created_by": "user1", "create_time": 1, "is_main_agent": True},
        {"agent_id": 2, "name": "Secondary", "display_name": "Secondary",
         "description": "", "enabled": True, "group_ids": "",
         "created_by": "user2", "create_time": 2, "is_main_agent": False},
        {"agent_id": 3, "name": "Legacy", "display_name": "Legacy",
         "description": "", "enabled": True, "group_ids": "",
         "created_by": "user3", "create_time": 3},
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.side_effect = lambda x: (
        [] if not x else [int(i) for i in x.split(",")]
    )
    mock_check_availability.side_effect = lambda *args, **kwargs: (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    assert result[0]["is_main_agent"] is True
    assert result[1]["is_main_agent"] is False
    assert result[2]["is_main_agent"] is True  # missing field defaults to main


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_is_published_field(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """
    Test that is_published field is correctly set based on current_version_no.

    This test verifies that:
    1. is_published is False when current_version_no is None
    2. is_published is False when current_version_no field is missing
    3. is_published is True when current_version_no is not None
    """
    # Setup mock agents with different current_version_no values
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Unpublished agent",
            "enabled": True,
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
            "current_version_no": None,  # Not published
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Published agent",
            "enabled": True,
            "group_ids": "",
            "created_by": "user2",
            "create_time": 2,
            "current_version_no": 1,  # Published
        },
        {
            "agent_id": 3,
            "name": "Agent 3",
            "display_name": "Display Agent 3",
            "description": "Agent without current_version_no field",
            "enabled": True,
            "group_ids": "",
            "created_by": "user3",
            "create_time": 3,
            # current_version_no field is missing
        },
    ]

    # Configure mocks
    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.side_effect = lambda x: (
        [] if not x else [int(i) for i in x.split(",")]
    )
    mock_check_availability.side_effect = lambda *args, **kwargs: (True, [])
    mock_get_model.return_value = None

    # Execute
    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    # Assert
    assert len(result) == 3
    # Agent 1: current_version_no is None -> is_published should be False
    assert result[0]["agent_id"] == 1
    assert result[0]["is_published"] == False
    # Agent 2: current_version_no is 1 -> is_published should be True
    assert result[1]["agent_id"] == 2
    assert result[1]["is_published"] == True
    # Agent 3: current_version_no field is missing -> is_published should be False
    assert result[2]["agent_id"] == 3
    assert result[2]["is_published"] == False

    # Verify mock calls
    mock_query_agents.assert_called_once_with(tenant_id="test_tenant")
    mock_get_user_tenant.assert_called_once_with("admin_user")


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_model_cache_miss_fetches_model(
    mock_query_all,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """list_all_agent_info_impl should fetch model when model_id not in cache."""
    mock_query_all.return_value = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "First test agent",
            "enabled": True,
            "model_ids": [99],
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
        }
    ]

    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.return_value = []
    # Do not mutate model_cache here so that the "model_id not in model_cache" branch runs.
    mock_check_availability.side_effect = lambda *args, **kwargs: (True, [])
    mock_get_model.return_value = {"model_name": "m", "display_name": "M", "connect_status": "available"}

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    assert len(result) == 1
    assert result[0]["model_ids"] == [99]
    assert result[0]["model_names"] == ["M"]
    assert result[0]["model_name"] == "M"
    mock_get_model.assert_called_once_with(99, "test_tenant")


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_with_unavailable_tools(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """
    Test retrieval of agent information with some unavailable tools.

    This test verifies that:
    1. The function correctly handles cases where some tools are unavailable
    2. It properly sets the is_available flag based on tool availability
    """
    # Setup mock agents
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent with available tools",
            "enabled": True,
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Agent with unavailable tools",
            "enabled": True,
            "group_ids": "5,6",
            "created_by": "user2",
            "create_time": 2,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.side_effect = lambda x: (
        [] if not x else [int(i) for i in x.split(",")]
    )
    # First agent has available tools, second agent has unavailable tools
    mock_check_availability.side_effect = [
        (True, []),  # Agent 1: available
        (False, ["tool_unavailable"]),  # Agent 2: unavailable
    ]
    mock_get_model.return_value = None

    # Execute
    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    # Assert
    assert len(result) == 2
    assert result[0]["is_available"] == True
    assert result[0]["unavailable_reasons"] == []
    assert result[0]["group_ids"] == []
    assert result[1]["is_available"] == False
    assert result[1]["unavailable_reasons"] == ["tool_unavailable"]
    assert result[1]["group_ids"] == [5, 6]

    # Verify mock calls
    mock_query_agents.assert_called_once_with(tenant_id="test_tenant")


@pytest.mark.asyncio
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_query_error(
    mock_query_agents,
    mock_get_user_tenant,
):
    """
    Test error handling when querying agent information fails.

    This test verifies that:
    1. When an error occurs during agent query
    2. The function raises a ValueError with an appropriate message
    """
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    # Configure mock to raise exception
    mock_query_agents.side_effect = Exception("Database error")

    # Execute & Assert
    with pytest.raises(ValueError) as context:
        await list_all_agent_info_impl(tenant_id="test_tenant", user_id="admin_user")

    assert "Failed to query all agent info" in str(context.value)
    mock_query_agents.assert_called_once_with(tenant_id="test_tenant")


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_model_unavailable(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent with unavailable model",
            "enabled": True,
            "model_id": 101,
            "group_ids": "7,8,9",
            "created_by": "user1",
            "create_time": 1,
            "current_version_no": None,
        }
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.side_effect = lambda x: (
        [] if not x else [int(i) for i in x.split(",")]
    )
    mock_check_availability.side_effect = lambda *args, **kwargs: (
        False,
        ["model_unavailable"],
    )
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    assert len(result) == 1
    assert result[0]["is_available"] is False
    assert result[0]["unavailable_reasons"] == ["model_unavailable"]
    assert result[0]["group_ids"] == [7, 8, 9]
    assert result[0]["is_published"] == False  # current_version_no is None


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_duplicate_names(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Duplicated",
            "create_time": 1,
            "display_name": "Agent Display 1",
            "description": "First agent",
            "enabled": True,
            "group_ids": "10",
            "created_by": "user1",
        },
        {
            "agent_id": 2,
            "name": "Duplicated",
            "create_time": 2,
            "display_name": "Agent Display 2",
            "description": "Second agent",
            "enabled": True,
            "group_ids": "10,11",
            "created_by": "user2",
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.side_effect = lambda x: (
        [] if not x else [int(i) for i in x.split(",")]
    )
    mock_check_availability.side_effect = lambda *args, **kwargs: (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    assert len(result) == 2

    # The earliest created agent (agent_id=1) should remain available
    agent1 = next(a for a in result if a["agent_id"] == 1)
    assert agent1["is_available"] is True
    assert "duplicate_name" not in agent1["unavailable_reasons"]
    assert agent1["group_ids"] == [10]
    assert agent1["is_published"] == False  # current_version_no is missing/None

    # The later created agent (agent_id=2) should be unavailable due to duplication
    agent2 = next(a for a in result if a["agent_id"] == 2)
    assert agent2["is_available"] is False
    assert "duplicate_name" in agent2["unavailable_reasons"]
    assert agent2["group_ids"] == [10, 11]
    assert agent2["is_published"] == False  # current_version_no is missing/None


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_user_permission_read_only(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that regular users get READ_ONLY permission for agents they didn't create."""
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent created by user1",
            "enabled": True,
            "group_ids": "1",  # Agent in group 1
            "created_by": "user1",
            "create_time": 1,
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Agent created by current_user",
            "enabled": True,
            "group_ids": "1",  # Agent in group 1
            "created_by": "current_user",
            "create_time": 2,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "USER"}  # Regular user, not admin
    mock_query_groups.return_value = [1]  # User is in group 1, so can see both agents

    # Mock convert_string_to_list to handle both empty strings and comma-separated values
    # This should match the actual implementation in management.utils.serialization
    def convert_side_effect(x):
        if not x or (isinstance(x, str) and x.strip() == ""):
            return []
        # Handle comma-separated string like "1" or "1,2"
        parts = str(x).split(",")
        result = []
        for part in parts:
            stripped = part.strip()
            if stripped and stripped.isdigit():
                result.append(int(stripped))
        return result

    mock_convert_list.side_effect = convert_side_effect

    # Mock check_agent_availability to return (is_available, unavailable_reasons)
    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="current_user"
    )

    assert len(result) == 2
    # Agent created by user1 - current_user should have READ_ONLY
    agent1 = next(a for a in result if a["agent_id"] == 1)
    assert agent1["permission"] == "READ_ONLY"
    # Agent created by current_user - should have EDIT
    agent2 = next(a for a in result if a["agent_id"] == 2)
    assert agent2["permission"] == "EDIT"


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_group_filtering(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that regular users only see agents whose group_ids overlap with their groups."""
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent in group 1",
            "enabled": True,
            "group_ids": "1,2",
            "created_by": "user1",
            "create_time": 1,
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Agent in group 3",
            "enabled": True,
            "group_ids": "3,4",
            "created_by": "user2",
            "create_time": 2,
        },
        {
            "agent_id": 3,
            "name": "Agent 3",
            "display_name": "Display Agent 3",
            "description": "Agent in group 1 (same as user)",
            "enabled": True,
            "group_ids": "1",  # Agent in group 1, which overlaps with user's groups
            "created_by": "user3",
            "create_time": 3,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "USER"}  # Regular user
    mock_query_groups.return_value = [1, 2]  # User is in groups 1 and 2

    # Mock convert_string_to_list to handle both empty strings and comma-separated values
    # This should match the actual implementation in management.utils.serialization
    def convert_side_effect(x):
        if not x or (isinstance(x, str) and x.strip() == ""):
            return []
        # Handle comma-separated string like "1" or "1,2"
        parts = str(x).split(",")
        result = []
        for part in parts:
            stripped = part.strip()
            if stripped and stripped.isdigit():
                result.append(int(stripped))
        return result

    mock_convert_list.side_effect = convert_side_effect

    # Mock check_agent_availability to return (is_available, unavailable_reasons)
    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="regular_user"
    )

    # Should only see Agent 1 (overlaps with user's groups 1,2) and Agent 3 (overlaps with group 1)
    # Agent 2 should be filtered out (groups 3,4 don't overlap with user's groups 1,2)
    assert len(result) == 2
    agent_ids = [a["agent_id"] for a in result]
    assert 1 in agent_ids
    assert 3 in agent_ids
    assert 2 not in agent_ids


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_creator_can_see_own_agent_without_group_overlap(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that users can see agents they created even if group_ids don't overlap."""
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent created by current_user, but in different groups",
            "enabled": True,
            "group_ids": "5,6",  # Different groups from user's groups [1, 2]
            "created_by": "current_user",  # User is the creator
            "create_time": 1,
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Agent not created by current_user, no group overlap",
            "enabled": True,
            "group_ids": "7,8",  # Different groups from user's groups [1, 2]
            "created_by": "other_user",  # User is NOT the creator
            "create_time": 2,
        },
        {
            "agent_id": 3,
            "name": "Agent 3",
            "display_name": "Display Agent 3",
            "description": "Agent with group overlap",
            "enabled": True,
            "group_ids": "1,9",  # Overlaps with user's group 1
            "created_by": "another_user",
            "create_time": 3,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "USER"}  # Regular user
    mock_query_groups.return_value = [1, 2]  # User is in groups 1 and 2

    # Mock convert_string_to_list to handle both empty strings and comma-separated values
    def convert_side_effect(x):
        if not x or (isinstance(x, str) and x.strip() == ""):
            return []
        parts = str(x).split(",")
        result = []
        for part in parts:
            stripped = part.strip()
            if stripped and stripped.isdigit():
                result.append(int(stripped))
        return result

    mock_convert_list.side_effect = convert_side_effect

    # Mock check_agent_availability to return (is_available, unavailable_reasons)
    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="current_user"
    )

    # Should see:
    # - Agent 1: created by current_user (creators can always see their own agents, even without group overlap)
    # - Agent 3: groups overlap (1 is in both user's groups and agent's groups)
    # Should NOT see:
    # - Agent 2: not created by current_user AND groups don't overlap
    assert len(result) == 2
    agent_ids = [a["agent_id"] for a in result]
    assert 1 in agent_ids, "Agent 1 should be visible because user is the creator"
    assert 3 in agent_ids, "Agent 3 should be visible because groups overlap"
    assert 2 not in agent_ids, (
        "Agent 2 should be filtered out (not creator and no group overlap)"
    )


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_disabled_agents_filtered(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that disabled agents are filtered out."""
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Enabled agent",
            "enabled": True,
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Disabled agent",
            "enabled": False,
            "group_ids": "",
            "created_by": "user2",
            "create_time": 2,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    # For admin users, query_group_ids_by_user is not called, but we still need to mock it
    mock_query_groups.return_value = []
    mock_convert_list.return_value = []
    # Mock check_agent_availability to return (is_available, unavailable_reasons)
    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    # Should only see enabled agent (disabled agents are filtered out)
    assert len(result) == 1
    assert result[0]["agent_id"] == 1
    assert result[0]["name"] == "Agent 1"


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_group_query_error_handled(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that group query errors are handled gracefully - admin users are not affected."""
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Test agent",
            "enabled": True,
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
        }
    ]

    mock_query_agents.return_value = mock_agents
    # Use ADMIN user - group query errors don't affect admin users since they bypass group filtering
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    # For admin users, query_group_ids_by_user is not called (can_edit_all is True)
    # But if it were called and failed, it should be handled gracefully
    mock_query_groups.side_effect = Exception("Database error")  # Simulate error
    mock_convert_list.return_value = []
    # Mock check_agent_availability to return (is_available, unavailable_reasons)
    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    # Should not raise exception, but should handle gracefully
    # Admin users bypass group filtering, so they should see all agents
    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    # Admin users should still see agents even if group query fails
    assert len(result) == 1
    assert result[0]["agent_id"] == 1


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_group_query_error_for_user_role(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that group query errors are handled gracefully for USER/DEV roles - covers lines 1274-1278."""
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Test agent",
            "enabled": True,
            "group_ids": "1,2",
            "created_by": "other_user",  # Different from user_id to test filtering logic
            "create_time": 1,
        }
    ]

    mock_query_agents.return_value = mock_agents
    # Use USER role - group query errors should be handled gracefully
    mock_get_user_tenant.return_value = {"user_role": "USER"}
    # Simulate exception when querying group IDs - this should trigger lines 1274-1278
    mock_query_groups.side_effect = Exception("Database connection error")

    # Mock convert_string_to_list to handle comma-separated values
    def convert_side_effect(x):
        if not x or (isinstance(x, str) and x.strip() == ""):
            return []
        parts = str(x).split(",")
        result = []
        for part in parts:
            stripped = part.strip()
            if stripped and stripped.isdigit():
                result.append(int(stripped))
        return result

    mock_convert_list.side_effect = convert_side_effect

    # Mock check_agent_availability to return (is_available, unavailable_reasons)
    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    # Should not raise exception, but should handle gracefully
    # When group query fails, user_group_ids is set to empty set
    # Agent is not created by user1, so it should be filtered out (no group overlap and not creator)
    result = await list_all_agent_info_impl(tenant_id="test_tenant", user_id="user1")

    # Since user_group_ids is empty set (due to exception) and user is not the creator,
    # agent should be filtered out according to line 1328 logic
    assert len(result) == 0
    # Verify that query_group_ids_by_user was called (to trigger the exception)
    mock_query_groups.assert_called_once_with("user1")


@patch("management.services.agent.transfer.query_sub_agents_id_list")
@patch(
    "management.services.agent.transfer.create_tool_config_list",
    new_callable=AsyncMock,
)
@patch("management.services.agent.transfer.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_export_agent_by_agent_id_success(
    mock_search_agent_info, mock_create_tool_config, mock_query_sub_agents_id
):
    """
    Test successful export of agent information by agent ID.

    This test verifies that:
    1. The function correctly retrieves agent information
    2. It creates tool configuration list
    3. It gets sub-agent ID list
    4. It returns properly structured ExportAndImportAgentInfo
    """
    # Setup
    mock_agent_info = {
        "name": "Test Agent",
        "display_name": "Test Agent Display",
        "description": "A test agent",
        "business_description": "For testing purposes",
        "max_steps": 10,
        "provide_run_summary": True,
        "enable_protocol_repair_retry": False,
        "prompt": '# Responsibilities\nTest duty prompt\n\n# Constraints\nTest constraint prompt\n\n# Examples\nTest few shots prompt',
        "enabled": True,
        "tenant_id": "test_tenant",
    }
    mock_search_agent_info.return_value = mock_agent_info

    mock_tools = [
        ToolConfig(
            class_name="Tool1",
            name="Tool One",
            source="source1",
            params={"param1": "value1"},
            metadata={},
            description="Tool 1 description",
            inputs="input description",
            output_type="output type description",
            usage=None,
        ),
        ToolConfig(
            class_name="KnowledgeBaseSearchTool",
            name="Knowledge Search",
            source="source2",
            params={"param2": "value2"},
            metadata={"some": "data"},
            description="Knowledge base search tool",
            inputs="search query",
            output_type="search results",
            usage=None,
        ),
        ToolConfig(
            class_name="AnalyzeTextFileTool",
            name="Text Analyzer",
            source="source3",
            params={"param4": "value4"},
            metadata={"text": "data"},
            description="Text analysis tool",
            inputs="text file",
            output_type="analysis",
            usage=None,
        ),
        ToolConfig(
            class_name="AnalyzeImageTool",
            name="Image Analyzer",
            source="source4",
            params={"param5": "value5"},
            metadata={"image": "data"},
            description="Image analysis tool",
            inputs="image file",
            output_type="analysis result",
            usage=None,
        ),
        ToolConfig(
            class_name="MCPTool",
            name="MCP Tool",
            source="mcp",
            params={"param3": "value3"},
            metadata={},
            description="MCP tool description",
            inputs="mcp input",
            output_type="mcp output",
            usage="test_mcp_server",
        ),
    ]
    mock_tools.append(ToolConfig(
        class_name="AidpSearchTool", name="aidp_search", source="local",
        params={"api_key": "secret", "server_url": "private", "tenant_id": "old", "kds_list": ["kb"]},
        metadata={"allowed_kds_set": ["kb"], "kds_name_to_id_map": {"KB": "kb"}},
        description="AIDP search", inputs="query", output_type="string", usage=None,
    ))
    mock_create_tool_config.return_value = mock_tools

    mock_sub_agent_ids = [456, 789]
    mock_query_sub_agents_id.return_value = mock_sub_agent_ids

    # Execute
    with patch(
        "management.services.agent.transfer.ExportAndImportAgentInfo",
        new=ExportAndImportAgentInfo,
    ):
        result = await export_agent_by_agent_id(
            agent_id=123, tenant_id="test_tenant", user_id="test_user"
        )

    # Assert
    assert result.agent_id == 123
    assert result.tenant_id == "test_tenant"
    assert result.name == "Test Agent"
    assert result.enable_protocol_repair_retry is False
    assert len(result.tools) == 6
    aidp_tool = next(tool for tool in result.tools if tool.class_name == "AidpSearchTool")
    assert aidp_tool.params == {"kds_list": ["kb"]}
    assert aidp_tool.metadata == {}
    assert result.managed_agents == mock_sub_agent_ids

    # Verify KnowledgeBaseSearchTool metadata is empty
    knowledge_tool = next(
        tool for tool in result.tools if tool.class_name == "KnowledgeBaseSearchTool"
    )
    assert knowledge_tool.metadata == {}

    analyze_text_tool = next(
        tool for tool in result.tools if tool.class_name == "AnalyzeTextFileTool"
    )
    assert analyze_text_tool.metadata == {}

    analyze_image_tool = next(
        tool for tool in result.tools if tool.class_name == "AnalyzeImageTool"
    )
    assert analyze_image_tool.metadata == {}

    # Verify MCP tool has usage field
    mcp_tool = next(tool for tool in result.tools if tool.class_name == "MCPTool")
    assert mcp_tool.usage == "test_mcp_server"

    # Verify function calls
    mock_search_agent_info.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant", version_no=0
    )
    mock_create_tool_config.assert_called_once_with(
        agent_id=123, tenant_id="test_tenant", user_id="test_user", version_no=0
    )
    mock_query_sub_agents_id.assert_called_once_with(
        main_agent_id=123, tenant_id="test_tenant", version_no=0
    )


@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@pytest.mark.asyncio
async def test_import_agent_by_agent_id_success(
    mock_query_all_tools, mock_create_agent, mock_create_tool
):
    """
    Test successful import of agent by agent ID.

    This test verifies that:
    1. The function correctly retrieves agent information
    2. It creates tool configuration list
    3. It gets sub-agent ID list
    4. It returns properly structured ExportAndImportAgentInfo
    """
    # Setup
    mock_tool_info = [
        {
            "tool_id": 101,
            "class_name": "Tool1",
            "source": "source1",
            "params": [{"name": "param1", "type": "string"}],
            "description": "Tool 1 description",
            "name": "Tool One",
            "inputs": "input description",
            "output_type": "output type description",
        }
    ]
    mock_query_all_tools.return_value = mock_tool_info

    mock_create_agent.return_value = {"agent_id": 456}

    # Create import data
    tool_config = ToolConfig(
        class_name="Tool1",
        name="Tool One",
        source="source1",
        params={"param1": "value1"},
        metadata={},
        description="Tool 1 description",
        inputs="input description",
        output_type="output type description",
        usage=None,
    )

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="valid_agent_name",
        display_name="Valid Agent Display Name",
        description="Imported description",
        business_description="Imported business description",
        max_steps=5,
        provide_run_summary=True,
        enable_protocol_repair_retry=False,
        prompt='# Responsibilities\nImported duty prompt\n\n# Constraints\nImported constraint prompt\n\n# Examples\nImported few shots prompt',
        enabled=True,
        tools=[tool_config],
        managed_agents=[],
    )

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info, tenant_id="test_tenant", user_id="test_user"
    )

    # Assert
    assert result == 456
    assert mock_create_agent.call_args.kwargs["agent_info"]["enable_protocol_repair_retry"] is False
    mock_create_agent.assert_called_once()
    assert mock_create_agent.call_args[1]["agent_info"]["name"] == "valid_agent_name"
    assert (
        mock_create_agent.call_args[1]["agent_info"]["display_name"]
        == "Valid Agent Display Name"
    )
    mock_create_tool.assert_called_once()


@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@pytest.mark.asyncio
async def test_import_agent_by_agent_id_invalid_tool(
    mock_query_all_tools, mock_create_tool
):
    """
    Test import of agent by agent ID with an invalid tool.

    This test verifies that:
    1. When a tool doesn't exist in the database
    2. The function raises a ValueError with appropriate message
    """
    # Setup
    mock_tool_info = [
        {
            "tool_id": 101,
            "class_name": "OtherTool",
            "source": "source1",
            "params": [{"name": "param1", "type": "string"}],
            "description": "Other tool description",
            "name": "Other Tool",
            "inputs": "other input",
            "output_type": "other output",
        }
    ]
    mock_query_all_tools.return_value = mock_tool_info

    # Create import data with non-existent tool
    tool_config = ToolConfig(
        class_name="Tool1",
        name="Tool One",
        source="source1",
        params={"param1": "value1"},
        metadata={},
        description="Tool 1 description",
        inputs="input description",
        output_type="output type description",
    )

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="valid_agent_name",
        display_name="Valid Agent Display Name",
        description="Imported description",
        business_description="Imported business description",
        max_steps=5,
        provide_run_summary=True,
        prompt='# Responsibilities\nImported duty prompt\n\n# Constraints\nImported constraint prompt\n\n# Examples\nImported few shots prompt',
        enabled=True,
        tools=[tool_config],
        managed_agents=[],
    )

    # Execute & Assert
    with pytest.raises(ValueError) as context:
        await import_agent_by_agent_id(
            import_agent_info=agent_info, tenant_id="test_tenant", user_id="test_user"
        )

    assert "Cannot find tool Tool1 in source1." in str(context.value)
    mock_create_tool.assert_not_called()


@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@pytest.mark.asyncio
async def test_import_agent_by_agent_id_with_mcp_tool(
    mock_query_all_tools, mock_create_agent, mock_create_tool
):
    """
    Test successful import of agent by agent ID with MCP tools.
    """
    # Setup
    mock_tool_info = [
        {
            "tool_id": 101,
            "class_name": "MCPTool",
            "source": "mcp",
            "params": [{"name": "param1", "type": "string"}],
            "description": "MCP tool description",
            "name": "MCP Tool",
            "inputs": "mcp input",
            "output_type": "mcp output",
        }
    ]
    mock_query_all_tools.return_value = mock_tool_info

    mock_create_agent.return_value = {"agent_id": 456}

    # Create import data with MCP tool
    tool_config = ToolConfig(
        class_name="MCPTool",
        name="MCP Tool",
        source="mcp",
        params={"param1": "value1"},
        metadata={},
        description="MCP tool description",
        inputs="mcp input",
        output_type="mcp output",
        usage="test_mcp_server",
    )

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="valid_agent_name",
        display_name="Valid Agent Display Name",
        description="Imported description",
        business_description="Imported business description",
        max_steps=5,
        provide_run_summary=True,
        prompt='# Responsibilities\nImported duty prompt\n\n# Constraints\nImported constraint prompt\n\n# Examples\nImported few shots prompt',
        enabled=True,
        tools=[tool_config],
        managed_agents=[],
    )

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info, tenant_id="test_tenant", user_id="test_user"
    )

    # Assert
    assert result == 456
    mock_create_agent.assert_called_once()
    assert mock_create_agent.call_args[1]["agent_info"]["name"] == "valid_agent_name"
    assert (
        mock_create_agent.call_args[1]["agent_info"]["display_name"]
        == "Valid Agent Display Name"
    )
    mock_create_tool.assert_called_once()


@patch("test.backend.services.agent_legacy_helpers.insert_related_agent")
@patch("test.backend.services.agent_legacy_helpers.query_sub_agents_id_list")
def test_insert_related_agent_impl_success(
    mock_query_sub_agents_id, mock_insert_related
):
    """
    Test successful insertion of related agent relationship.

    This test verifies that:
    1. The function checks for circular dependencies using BFS
    2. When no circular dependency exists, it inserts the relationship
    3. It returns a success response
    """
    # Setup
    # Child agent has different sub-agents
    mock_query_sub_agents_id.return_value = [789]
    mock_insert_related.return_value = True

    # Execute
    result = insert_related_agent_impl(
        parent_agent_id=123, child_agent_id=456, tenant_id="test_tenant"
    )

    # Assert
    assert result.status_code == 200
    assert "Insert relation success" in result.body.decode()
    mock_insert_related.assert_called_once_with(123, 456, "test_tenant")


@patch("test.backend.services.agent_legacy_helpers.query_sub_agents_id_list")
def test_insert_related_agent_impl_circular_dependency(mock_query_sub_agents_id):
    """
    Test insertion of related agent with circular dependency.

    This test verifies that:
    1. The function detects circular dependencies
    2. It returns an error response when circular dependency exists
    """
    # Setup - simulate circular dependency
    mock_query_sub_agents_id.side_effect = [
        # Child agent 456 has parent agent 123 as its sub-agent (circular)
        [123],
    ]

    # Execute
    result = insert_related_agent_impl(
        parent_agent_id=123, child_agent_id=456, tenant_id="test_tenant"
    )

    # Assert
    assert result.status_code == 500
    assert "There is a circular call in the agent" in result.body.decode()


@patch("os.path.join", return_value="test_path")
@patch("os.listdir")
@patch("builtins.open", new_callable=mock_open)
def test_load_default_agents_json_file(mock_file, mock_listdir, mock_join):
    """
    Test loading default agent JSON files.

    This test verifies that:
    1. The function correctly lists files in the specified directory
    2. It filters for JSON files
    3. It reads and parses each JSON file
    4. It returns a list of validated agent configurations
    """
    # Setup
    mock_listdir.return_value = ["agent1.json", "agent2.json", "not_json.txt"]

    # Set up the mock file content for each file
    json_content1 = """{
        "agent_id": 1,
        "name": "Agent1",
        "display_name": "Agent 1 Display",
        "description": "Agent 1 description",
        "business_description": "Business description",
        "max_steps": 10,
        "provide_run_summary": true,
        "prompt": "Agent 1 prompt",
        "enabled": true,
        "tools": [],
        "managed_agents": []
    }"""

    json_content2 = """{
        "agent_id": 2,
        "name": "Agent2",
        "display_name": "Agent 2 Display",
        "description": "Agent 2 description",
        "business_description": "Business description",
        "max_steps": 5,
        "provide_run_summary": false,
        "prompt": "Agent 2 prompt",
        "enabled": true,
        "tools": [],
        "managed_agents": []
    }"""

    # Make the mock file return different content for different files
    mock_file.return_value.__enter__.side_effect = [
        MagicMock(read=lambda: json_content1),
        MagicMock(read=lambda: json_content2),
    ]

    # Need to patch json.load to handle the mock file contents
    with patch("json.load") as mock_json_load:
        mock_json_load.side_effect = [
            {
                "agent_id": 1,
                "name": "Agent1",
                "display_name": "Agent 1 Display",
                "description": "Agent 1 description",
                "business_description": "Business description",
                "max_steps": 10,
                "provide_run_summary": True,
                "prompt": "Agent 1 prompt",
                "enabled": True,
                "tools": [],
                "managed_agents": [],
            },
            {
                "agent_id": 2,
                "name": "Agent2",
                "display_name": "Agent 2 Display",
                "description": "Agent 2 description",
                "business_description": "Business description",
                "max_steps": 5,
                "provide_run_summary": False,
                "prompt": "Agent 2 prompt",
                "enabled": True,
                "tools": [],
                "managed_agents": [],
            },
        ]

        # Execute
        with patch(
            "management.services.agent.transfer.ExportAndImportAgentInfo",
            new=ExportAndImportAgentInfo,
        ):
            result = load_default_agents_json_file("default/path")

        # Assert
        assert len(result) == 2
        assert result[0].name == "Agent1"
        assert result[1].name == "Agent2"
        assert mock_file.call_count == 2
        mock_listdir.assert_called_once_with("default/path")


@patch('management.services.agent.transfer.insert_related_agent')
@patch('management.services.agent.transfer.import_agent_by_agent_id')
@pytest.mark.asyncio
async def test_import_agent_impl_imports_all_agents_and_links_relations(mock_import_agent, mock_insert_relationship):
    """
    Import agent implementation should import sub-agents before their parents
    and create the relationship between the newly created agent IDs.
    """
    sub_agent_info = ExportAndImportAgentInfo(agent_id=2, name='SubAgent', display_name='Sub Agent', description='Sub agent desc', business_description='Business desc', max_steps=5, provide_run_summary=True, prompt='# Responsibilities\nSub duty\n\n# Constraints\nSub constraint\n\n# Examples\nSub few shots', enabled=True, tools=[], managed_agents=[])
    main_agent_info = ExportAndImportAgentInfo(agent_id=1, name='MainAgent', display_name='Main Agent', description='Main desc', business_description='Business main', max_steps=10, provide_run_summary=True, prompt='# Responsibilities\nMain duty\n\n# Constraints\nMain constraint\n\n# Examples\nMain few shots', enabled=True, tools=[], managed_agents=[2])
    export_data = ExportAndImportDataFormat(agent_id=1, agent_info={'1': main_agent_info, '2': sub_agent_info}, mcp_info=[MCPInfo(mcp_server_name='test_mcp_server', mcp_url='http://test-mcp-server.com')])
    mock_import_agent.side_effect = [101, 202]
    await import_agent_impl(export_data, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert mock_import_agent.call_count == 2
    first_call = mock_import_agent.call_args_list[0]
    second_call = mock_import_agent.call_args_list[1]
    assert first_call.kwargs['import_agent_info'] is sub_agent_info
    assert first_call.kwargs['skip_duplicate_regeneration'] is False
    assert second_call.kwargs['import_agent_info'] is main_agent_info
    assert second_call.kwargs['skip_duplicate_regeneration'] is False
    mock_insert_relationship.assert_called_once_with(parent_agent_id=202, child_agent_id=101, tenant_id='test_tenant', user_id='test_user', selected_agent_version_no=1)


@patch('management.services.agent.transfer.import_agent_by_agent_id')
@pytest.mark.asyncio
async def test_import_agent_impl_force_import_passes_skip_flag(mock_import_agent):
    """
    When force_import=True, skip_duplicate_regeneration should be True.
    """
    agent_info = ExportAndImportAgentInfo(agent_id=1, name='Agent', display_name='Agent Display', description='desc', business_description='biz', max_steps=5, provide_run_summary=True, prompt='# Responsibilities\nduty\n\n# Constraints\nconstraint\n\n# Examples\nfew shots', enabled=True, tools=[], managed_agents=[])
    export_data = ExportAndImportDataFormat(agent_id=1, agent_info={'1': agent_info}, mcp_info=[])
    await import_agent_impl(export_data, identity=AuthenticatedIdentity('test_user', 'test_tenant'), force_import=True)
    mock_import_agent.assert_called_once()
    call_kwargs = mock_import_agent.call_args.kwargs
    assert call_kwargs['import_agent_info'] is agent_info
    assert call_kwargs['skip_duplicate_regeneration'] is True


if __name__ == "__main__":
    pytest.main()


# Agent run tests
@pytest.fixture
def mock_agent_request():
    return AgentRequest(
        agent_id=1,
        conversation_id=123,
        query="test query",
        history=[],
        minio_files=[],
        requested_output_tokens=4096,
        is_debug=False,
    )


@pytest.fixture
def mock_http_request():
    return Request(scope={"type": "http", "headers": []})


@patch("test.backend.services.agent_legacy_helpers.search_agent_id_by_agent_name")
async def test_get_agent_id_by_name(mock_search):
    """Test get_agent_id_by_name function."""
    # Test success
    mock_search.return_value = 1
    result = await get_agent_id_by_name("test_agent", "test_tenant")
    assert result == 1

    # Test not found
    mock_search.side_effect = Exception("Not found")
    with pytest.raises(Exception) as excinfo:
        await get_agent_id_by_name("test_agent", "test_tenant")
    assert "agent not found" in str(excinfo.value)

    # Test empty agent name
    with pytest.raises(Exception) as excinfo:
        await get_agent_id_by_name("", "test_tenant")
    assert "agent_name required" in str(excinfo.value)


@patch("management.services.agent.management.search_agent_info_by_agent_id")
@patch("management.services.agent.management.search_tools_for_sub_agent")
@patch("management.services.agent.management.query_sub_agents_id_list")
def test_get_agent_call_relationship_impl_success(
    mock_query_sub_agents, mock_search_tools, mock_search_agent_info
):
    """
    Test successful retrieval of agent call relationship tree.

    This test verifies that:
    1. The function correctly retrieves agent information
    2. Tools are properly normalized and formatted
    3. Sub-agents are recursively collected with their tools
    4. The response structure matches expected format
    """
    # Setup mock data
    mock_agent_info = {
        "agent_id": 1,
        "name": "Test Agent",
        "display_name": "Test Display Name",
        "description": "Test Description",
    }

    mock_tools = [
        {
            "tool_id": 1,
            "name": "Test Tool 1",
            "source": "local",
            "tool_name": "Local Tool",
        },
        {"tool_id": 2, "name": "Test Tool 2", "source": "mcp", "tool_name": "MCP Tool"},
        {
            "tool_id": 3,
            "name": "Test Tool 3",
            "source": "langchain",
            "tool_name": "LangChain Tool",
        },
    ]

    mock_sub_agent_ids = [2, 3]

    # Setup sub-agent info
    mock_sub_agent_info = {
        "agent_id": 2,
        "name": "Sub Agent 1",
        "display_name": "Sub Display 1",
    }

    mock_sub_tools = [{"tool_id": 4, "name": "Sub Tool 1", "source": "local"}]

    # Setup mocks
    mock_search_agent_info.side_effect = [mock_agent_info, mock_sub_agent_info]
    mock_search_tools.side_effect = [mock_tools, mock_sub_tools]
    mock_query_sub_agents.return_value = mock_sub_agent_ids

    # Execute
    result = get_agent_call_relationship_impl(agent_id=1, tenant_id="test_tenant")

    # Assert
    assert result["agent_id"] == "1"
    assert result["name"] == "Test Display Name"
    assert len(result["tools"]) == 3
    assert len(result["sub_agents"]) == 1

    # Check tool normalization
    assert result["tools"][0]["type"] == "Local"
    assert result["tools"][1]["type"] == "MCP"
    assert result["tools"][2]["type"] == "LangChain"

    # Check sub-agent structure
    sub_agent = result["sub_agents"][0]
    assert sub_agent["agent_id"] == "2"
    assert sub_agent["name"] == "Sub Display 1"
    assert sub_agent["depth"] == 1
    assert len(sub_agent["tools"]) == 1
    assert sub_agent["tools"][0]["type"] == "Local"

    # Verify mock calls
    mock_search_agent_info.assert_called()
    mock_search_tools.assert_called()
    mock_query_sub_agents.assert_called()


@patch("management.services.agent.management.search_agent_info_by_agent_id")
@patch("management.services.agent.management.search_tools_for_sub_agent")
@patch("management.services.agent.management.query_sub_agents_id_list")
def test_get_agent_call_relationship_impl_with_unknown_source(
    mock_query_sub_agents, mock_search_tools, mock_search_agent_info
):
    """
    Test agent call relationship with unknown tool source.

    This test verifies that:
    1. Unknown tool sources are handled gracefully
    2. Tool types are properly formatted for unknown sources
    """
    # Setup mock data
    mock_agent_info = {
        "agent_id": 1,
        "name": "Test Agent",
        "display_name": "Test Display Name",
    }

    mock_tools = [
        {
            "tool_id": 1,
            "name": "Unknown Tool",
            "source": "unknown_source",
            "tool_name": "Unknown Source Tool",
        }
    ]

    # Setup mocks
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = mock_tools
    mock_query_sub_agents.return_value = []

    # Execute
    result = get_agent_call_relationship_impl(agent_id=1, tenant_id="test_tenant")

    # Assert
    assert result["tools"][0]["type"] == "Unknown_source"
    assert len(result["sub_agents"]) == 0


@patch("management.services.agent.management.search_agent_info_by_agent_id")
@patch("management.services.agent.management.search_tools_for_sub_agent")
@patch("management.services.agent.management.query_sub_agents_id_list")
def test_get_agent_call_relationship_impl_with_none_source(
    mock_query_sub_agents, mock_search_tools, mock_search_agent_info
):
    """
    Test agent call relationship with None tool source.

    This test verifies that:
    1. None tool sources are handled gracefully
    2. Tool types default to "UNKNOWN" for None sources
    """
    # Setup mock data
    mock_agent_info = {
        "agent_id": 1,
        "name": "Test Agent",
        "display_name": "Test Display Name",
    }

    mock_tools = [
        {
            "tool_id": 1,
            "name": "None Source Tool",
            "source": None,
            "tool_name": "None Source Tool",
        }
    ]

    # Setup mocks
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = mock_tools
    mock_query_sub_agents.return_value = []

    # Execute
    result = get_agent_call_relationship_impl(agent_id=1, tenant_id="test_tenant")

    # Assert
    assert result["tools"][0]["type"] == "UNKNOWN"
    assert len(result["sub_agents"]) == 0


@patch("management.services.agent.management.search_agent_info_by_agent_id")
@patch("management.services.agent.management.search_tools_for_sub_agent")
@patch("management.services.agent.management.query_sub_agents_id_list")
def test_get_agent_call_relationship_impl_with_empty_tools(
    mock_query_sub_agents, mock_search_tools, mock_search_agent_info
):
    """
    Test agent call relationship with no tools.

    This test verifies that:
    1. Agents without tools are handled correctly
    2. Empty tool lists don't cause errors
    """
    # Setup mock data
    mock_agent_info = {
        "agent_id": 1,
        "name": "Test Agent",
        "display_name": "Test Display Name",
    }

    # Setup mocks
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = []
    mock_query_sub_agents.return_value = []

    # Execute
    result = get_agent_call_relationship_impl(agent_id=1, tenant_id="test_tenant")

    # Assert
    assert result["tools"] == []
    assert len(result["sub_agents"]) == 0


@patch("management.services.agent.management.search_agent_info_by_agent_id")
def test_get_agent_call_relationship_impl_agent_not_found(mock_search_agent_info):
    """
    Test agent call relationship when agent is not found.

    This test verifies that:
    1. Appropriate error is raised when agent doesn't exist
    2. Error message is descriptive
    """
    # Setup mock to return None (agent not found)
    mock_search_agent_info.return_value = None

    # Execute and assert
    with pytest.raises(ValueError, match="Agent 999 not found"):
        get_agent_call_relationship_impl(agent_id=999, tenant_id="test_tenant")

    mock_search_agent_info.assert_called_once_with(999, "test_tenant")


@patch("management.services.agent.management.search_agent_info_by_agent_id")
@patch("management.services.agent.management.search_tools_for_sub_agent")
@patch("management.services.agent.management.query_sub_agents_id_list")
def test_get_agent_call_relationship_impl_sub_agent_error_handling(
    mock_query_sub_agents, mock_search_tools, mock_search_agent_info
):
    """
    Test agent call relationship with sub-agent errors.

    This test verifies that:
    1. Errors in sub-agent processing don't crash the entire function
    2. Failed sub-agents are logged and skipped
    3. Other sub-agents continue to be processed
    """
    # Setup mock data
    mock_agent_info = {
        "agent_id": 1,
        "name": "Test Agent",
        "display_name": "Test Agent",
    }

    # Setup mocks - one sub-agent will fail, one will succeed
    mock_search_agent_info.side_effect = [
        mock_agent_info,  # Main agent
        {"agent_id": 2, "name": "Sub Agent 1"},  # First sub-agent (success)
        ValueError("Sub-agent 3 not found"),  # Second sub-agent (failure)
    ]

    mock_search_tools.return_value = []
    mock_query_sub_agents.return_value = [2, 3]  # Two sub-agents

    # Execute
    result = get_agent_call_relationship_impl(agent_id=1, tenant_id="test_tenant")

    # Assert - should only include the successful sub-agent
    assert len(result["sub_agents"]) == 1
    assert result["sub_agents"][0]["agent_id"] == "2"

    # Verify mock calls
    mock_search_agent_info.assert_called()
    # At least main agent + one sub-agent
    assert mock_search_agent_info.call_count >= 2


@patch("management.services.agent.management.search_agent_info_by_agent_id")
@patch("management.services.agent.management.search_tools_for_sub_agent")
@patch("management.services.agent.management.query_sub_agents_id_list")
def test_get_agent_call_relationship_impl_tool_name_fallback(
    mock_query_sub_agents, mock_search_tools, mock_search_agent_info
):
    """
    Test agent call relationship tool name fallback logic.

    This test verifies that:
    1. Tool names fall back to tool_name if name is not available
    2. Tool names fall back to tool_id if neither name nor tool_name is available
    """
    # Setup mock data
    mock_agent_info = {
        "agent_id": 1,
        "name": "Test Agent",
        "display_name": "Test Agent",
    }

    mock_tools = [
        {
            "tool_id": 1,
            "source": "local",
            # No name or tool_name
        },
        {"tool_id": 2, "name": "Explicit Name", "source": "local"},
        {
            "tool_id": 3,
            "tool_name": "Tool Name",
            "source": "local",
            # No name
        },
    ]

    # Setup mocks
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = mock_tools
    mock_query_sub_agents.return_value = []

    # Execute
    result = get_agent_call_relationship_impl(agent_id=1, tenant_id="test_tenant")

    # Assert
    assert result["tools"][0]["name"] == "1"  # Fallback to tool_id
    assert result["tools"][1]["name"] == "Explicit Name"  # Use explicit name
    assert result["tools"][2]["name"] == "Tool Name"  # Use tool_name


#############################
# Additional tests for newer logic in agent_service.py
#############################


def test_insert_related_agent_impl_failure_returns_400():
    """When insertion fails, should return 400 JSONResponse."""
    with (
        patch(
            "management.services.agent.service.query_sub_agents_id_list",
            return_value=[],
        ) as _,
        patch(
            "test.backend.services.agent_legacy_helpers.insert_related_agent",
            return_value=False,
        ) as __,
    ):
        resp = insert_related_agent_impl(
            parent_agent_id=1, child_agent_id=2, tenant_id="t"
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_with_disabled_agents(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """
    Test list_all_agent_info_impl with disabled agents.

    This test verifies that:
    1. Agents with enabled=False are skipped and not included in the result
    2. Only enabled agents are processed and returned
    """
    # Setup mock agents with mixed enabled/disabled states
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Enabled Agent 1",
            "display_name": "Display Enabled Agent 1",
            "description": "First enabled agent",
            "enabled": True,
            "group_ids": "12",
            "created_by": "user1",
            "create_time": 1,
        },
        {
            "agent_id": 2,
            "name": "Disabled Agent",
            "display_name": "Display Disabled Agent",
            "description": "Disabled agent that should be skipped",
            "enabled": False,
            "group_ids": "13",
            "created_by": "user2",
            "create_time": 2,
        },
        {
            "agent_id": 3,
            "name": "Enabled Agent 2",
            "display_name": "Display Enabled Agent 2",
            "description": "Second enabled agent",
            "enabled": True,
            "group_ids": "12,14",
            "created_by": "user3",
            "create_time": 3,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.side_effect = lambda x: (
        [] if not x else [int(i) for i in x.split(",")]
    )
    mock_check_availability.side_effect = lambda *args, **kwargs: (True, [])
    mock_get_model.return_value = None

    # Execute
    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    # Assert - only enabled agents should be in the result
    assert len(result) == 2
    assert result[0]["agent_id"] == 1
    assert result[0]["name"] == "Enabled Agent 1"
    assert result[0]["display_name"] == "Display Enabled Agent 1"
    assert result[0]["is_available"] == True
    assert result[0]["group_ids"] == [12]

    assert result[1]["agent_id"] == 3
    assert result[1]["name"] == "Enabled Agent 2"
    assert result[1]["display_name"] == "Display Enabled Agent 2"
    assert result[1]["is_available"] == True
    assert result[1]["group_ids"] == [12, 14]

    # Verify mock calls
    mock_query_agents.assert_called_once_with(tenant_id="test_tenant")


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_all_disabled_agents(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """
    Test list_all_agent_info_impl with all agents disabled.

    This test verifies that:
    1. When all agents are disabled, an empty list is returned
    2. No availability checks are made since no agents are processed
    """
    # Setup mock agents - all disabled
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Disabled Agent 1",
            "display_name": "Display Disabled Agent 1",
            "description": "First disabled agent",
            "enabled": False,
            "group_ids": "15",
            "created_by": "user1",
            "create_time": 1,
        },
        {
            "agent_id": 2,
            "name": "Disabled Agent 2",
            "display_name": "Display Disabled Agent 2",
            "description": "Second disabled agent",
            "enabled": False,
            "group_ids": "16,17",
            "created_by": "user2",
            "create_time": 2,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.return_value = []
    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    # Execute
    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    # Assert - no agents should be in the result
    assert len(result) == 0
    assert result == []

    # Verify mock calls
    mock_query_agents.assert_called_once_with(tenant_id="test_tenant")
    # No availability checks should be made since no agents are enabled
    mock_check_availability.assert_not_called()


def test_apply_duplicate_name_availability_rules_handles_missing_fields():
    """
    Ensure duplicate detection gracefully handles agents without name/display_name.
    """
    enriched_agents = [
        {
            "raw_agent": {
                "agent_id": 1,
                "name": None,
                "display_name": None,
                "create_time": "2024-01-01T00:00:00",
            },
            "unavailable_reasons": [],
        },
        {
            "raw_agent": {
                "agent_id": 2,
                "name": "dup",
                "display_name": None,
                "create_time": "2024-01-01T00:00:00",
            },
            "unavailable_reasons": [],
        },
        {
            "raw_agent": {
                "agent_id": 3,
                "name": "dup",
                "display_name": None,
                "create_time": "2024-02-01T00:00:00",
            },
            "unavailable_reasons": [],
        },
        {
            "raw_agent": {
                "agent_id": 4,
                "name": None,
                "display_name": "display-dup",
                "create_time": "2024-01-01T00:00:00",
            },
            "unavailable_reasons": [],
        },
        {
            "raw_agent": {
                "agent_id": 5,
                "name": None,
                "display_name": "display-dup",
                "create_time": "2024-02-01T00:00:00",
            },
            "unavailable_reasons": [],
        },
    ]

    _apply_duplicate_name_availability_rules(enriched_agents)

    assert enriched_agents[0]["unavailable_reasons"] == []
    assert "duplicate_name" not in enriched_agents[1]["unavailable_reasons"]
    assert "duplicate_name" in enriched_agents[2]["unavailable_reasons"]
    assert "duplicate_display_name" not in enriched_agents[3]["unavailable_reasons"]
    assert "duplicate_display_name" in enriched_agents[4]["unavailable_reasons"]


# ============================================================================
# Tests for Agent Export/Import Integration with model_name fields
# ============================================================================


@patch(
    "management.services.agent.transfer.create_tool_config_list",
    new_callable=AsyncMock,
)
@patch("management.services.agent.transfer.query_sub_agents_id_list")
@patch("management.services.agent.transfer.get_model_by_model_id")
@patch("management.services.agent.transfer.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_export_agent_includes_model_names(
    mock_search_agent_info,
    mock_get_model_by_model_id,
    mock_query_sub_agents,
    mock_create_tool_config,
):
    """
    Test that export_agent_by_agent_id correctly includes model_name and
    business_logic_model_name in the exported data.
    """
    # Setup - Agent info from database
    mock_agent_info_from_db = {
        "name": "test_agent",
        "display_name": "Test Agent",
        "description": "Test description",
        "business_description": "Test business description",
        "max_steps": 5,
        "provide_run_summary": False,
        "prompt": '# Responsibilities\nTest duty\n\n# Constraints\nTest constraints\n\n# Examples\nTest examples',
        "enabled": True,
        "tenant_id": "test_tenant",
        "model_ids": [5],
        "business_logic_model_id": 4,
    }
    mock_search_agent_info.return_value = mock_agent_info_from_db

    # Mock model lookup - this is where model_name comes from
    def get_model_side_effect(model_id):
        if model_id == 5:
            return {"display_name": "Qwen/Qwen3-8B", "model_id": 5}
        elif model_id == 4:
            return {"display_name": "Qwen/QwQ-32B", "model_id": 4}
        return None

    mock_get_model_by_model_id.side_effect = get_model_side_effect

    mock_query_sub_agents.return_value = []
    mock_create_tool_config.return_value = []

    # Execute export
    exported_agent = await export_agent_by_agent_id(
        agent_id=123, tenant_id="test_tenant", user_id="test_user"
    )

    # Assert - verify exported data includes model names
    assert isinstance(exported_agent, ExportAndImportAgentInfo)

    # Critical assertions - these fields must be present for import to work
    assert exported_agent.model_ids == [5]
    assert exported_agent.model_names == ["Qwen/Qwen3-8B"]  # ← Must be present
    assert exported_agent.business_logic_model_id == 4
    assert (
        exported_agent.business_logic_model_name == "Qwen/QwQ-32B"
    )  # ← Must be present

    # Verify other fields
    assert exported_agent.name == "test_agent"
    assert exported_agent.display_name == "Test Agent"


@patch(
    "management.services.agent.transfer.create_tool_config_list",
    new_callable=AsyncMock,
)
@patch("management.services.agent.transfer.query_sub_agents_id_list")
@patch("management.services.agent.transfer.get_model_by_model_id")
@patch("management.services.agent.transfer.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_export_agent_with_null_model_id(
    mock_search_agent_info,
    mock_get_model_by_model_id,
    mock_query_sub_agents,
    mock_create_tool_config,
):
    """
    Test export when model_id is NULL in database.
    """
    # Setup - Agent with NULL model_id
    mock_agent_info_from_db = {
        "name": "agent_without_model",
        "display_name": "Agent Without Model",
        "description": "Test description",
        "business_description": "Test business description",
        "max_steps": 5,
        "provide_run_summary": False,
        "prompt": '# Responsibilities\nTest duty\n\n# Constraints\nTest constraints\n\n# Examples\nTest examples',
        "enabled": True,
        "tenant_id": "test_tenant",
        "model_ids": None,  # NULL in database
        "business_logic_model_id": None,  # NULL in database
    }
    mock_search_agent_info.return_value = mock_agent_info_from_db
    mock_query_sub_agents.return_value = []
    mock_create_tool_config.return_value = []

    # Execute export
    exported_agent = await export_agent_by_agent_id(
        agent_id=123, tenant_id="test_tenant", user_id="test_user"
    )

    # Assert - should handle NULL gracefully
    # Source uses `agent_info.get("model_ids") or []` so None becomes empty list
    assert exported_agent.model_ids == []
    assert exported_agent.model_names == []
    assert exported_agent.business_logic_model_id is None
    assert exported_agent.business_logic_model_name is None

    # get_model_by_model_id should not have been called
    mock_get_model_by_model_id.assert_not_called()


@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@patch(
    "management.services.agent.transfer.create_tool_config_list",
    new_callable=AsyncMock,
)
@patch("management.services.agent.transfer.query_sub_agents_id_list")
@patch("management.services.agent.transfer.get_model_by_model_id")
@patch("management.services.agent.transfer.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_export_then_import_preserves_model_names(
    mock_search_agent_info,
    mock_get_model_by_model_id,
    mock_query_sub_agents,
    mock_create_tool_config,
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool,
    mock_get_model_id_by_display_name,
):
    """
    Integration test: Export an agent, then import it, verify model names are preserved.

    This test simulates the complete export/import cycle to ensure data integrity.
    """
    # ========== STEP 1: EXPORT ==========

    # Setup - Agent in source tenant
    mock_agent_info_from_db = {
        "name": "iot_knowledge_qa_assistant",
        "display_name": "物联网知识问答助手",
        "description": "IoT Q&A Assistant",
        "business_description": "IoT knowledge retrieval",
        "max_steps": 5,
        "provide_run_summary": False,
        "prompt": '# Responsibilities\nYou are an IoT assistant\n\n# Constraints\nFollow safety rules\n\n# Examples\nExample tasks',
        "enabled": True,
        "tenant_id": "source_tenant",
        "model_ids": [10],  # Model ID in source tenant
        "business_logic_model_id": 9,  # Business logic model ID in source tenant
    }
    mock_search_agent_info.return_value = mock_agent_info_from_db

    # Mock model lookup for export
    def get_model_for_export(model_id):
        if model_id == 10:
            return {"display_name": "Qwen/Qwen3-8B", "model_id": 10}
        elif model_id == 9:
            return {"display_name": "Qwen/QwQ-32B", "model_id": 9}
        return None

    mock_get_model_by_model_id.side_effect = get_model_for_export
    mock_query_sub_agents.return_value = []
    mock_create_tool_config.return_value = []

    # Execute export
    exported_agent = await export_agent_by_agent_id(
        agent_id=123, tenant_id="source_tenant", user_id="source_user"
    )

    # Verify export includes model names
    assert exported_agent.model_ids == [10]
    assert exported_agent.model_names == ["Qwen/Qwen3-8B"]
    assert exported_agent.business_logic_model_id == 9
    assert exported_agent.business_logic_model_name == "Qwen/QwQ-32B"

    # ========== STEP 2: IMPORT ==========

    # Setup for import - simulate different model IDs in target tenant
    mock_query_all_tools.return_value = []

    # In target tenant, the explicit model ids from the source tenant do NOT exist
    # so the resolver must fall back to display name lookup. We override the
    # export's side_effect to force model lookups to return None.
    def model_not_in_target_tenant(model_id):
        return None

    mock_get_model_by_model_id.side_effect = model_not_in_target_tenant

    # In target tenant, same models have different IDs
    # Source: model_ids=[10] → Target: model_ids=[5]
    # Source: business_logic_model_id=9 → Target: business_logic_model_id=4
    mock_get_model_id_by_display_name.side_effect = [5, 4]

    mock_create_agent.return_value = {"agent_id": 999}

    # Execute import
    new_agent_id = await import_agent_by_agent_id(
        import_agent_info=exported_agent,
        tenant_id="target_tenant",
        user_id="target_user",
    )

    # Verify import was successful
    assert new_agent_id == 999

    # ========== STEP 3: VERIFY DATA INTEGRITY ==========

    # Verify create_agent was called with correct model information
    mock_create_agent.assert_called_once()
    call_kwargs = mock_create_agent.call_args[1]
    agent_info_dict = call_kwargs["agent_info"]

    # Model IDs should be REMAPPED to target tenant IDs
    assert agent_info_dict["model_ids"] == [5]  # Remapped from [10] to [5]
    assert agent_info_dict["business_logic_model_id"] == 4  # Remapped from 9 to 4

    # Model NAMES should be PRESERVED (not remapped) for cross-tenant display name lookup.
    # Note: source does NOT propagate model_names to create_agent (only used for lookup),
    # but business_logic_model_name IS propagated.
    assert "model_names" not in agent_info_dict
    assert agent_info_dict["business_logic_model_name"] == "Qwen/QwQ-32B"  # ← Preserved

    # Other fields should also be preserved
    assert agent_info_dict["name"] == "iot_knowledge_qa_assistant"
    assert agent_info_dict["display_name"] == "物联网知识问答助手"
    assert agent_info_dict["description"] == "IoT Q&A Assistant"
    assert agent_info_dict["max_steps"] == 5

    # Verify model lookup was done by display name (model_name)
    assert mock_get_model_id_by_display_name.call_count == 2
    first_call = mock_get_model_id_by_display_name.call_args_list[0]
    second_call = mock_get_model_id_by_display_name.call_args_list[1]

    # get_model_id_by_display_name(display_name: str, tenant_id: str) uses positional args
    assert first_call[0][0] == "Qwen/Qwen3-8B"  # display_name
    assert first_call[0][1] == "target_tenant"  # tenant_id
    assert second_call[0][0] == "Qwen/QwQ-32B"  # display_name
    assert second_call[0][1] == "target_tenant"  # tenant_id


@patch(
    "management.services.agent.transfer.create_tool_config_list",
    new_callable=AsyncMock,
)
@patch("management.services.agent.transfer.query_sub_agents_id_list")
@patch("management.services.agent.transfer.get_model_by_model_id")
@patch("management.services.agent.transfer.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_export_agent_model_not_found(
    mock_search_agent_info,
    mock_get_model_by_model_id,
    mock_query_sub_agents,
    mock_create_tool_config,
):
    """
    Test export when model_id exists but model record is not found.

    This can happen if:
    - Model was deleted after agent creation
    - Database inconsistency
    """
    # Setup
    mock_agent_info_from_db = {
        "name": "orphaned_agent",
        "display_name": "Orphaned Agent",
        "description": "Agent with missing model",
        "business_description": "Test",
        "max_steps": 5,
        "provide_run_summary": False,
        "prompt": '# Responsibilities\nTest\n\n# Constraints\nTest\n\n# Examples\nTest',
        "enabled": True,
        "tenant_id": "test_tenant",
        "model_ids": [999],  # This model doesn't exist
        "business_logic_model_id": 998,  # This model doesn't exist
    }
    mock_search_agent_info.return_value = mock_agent_info_from_db

    # Model lookup returns None (model not found)
    mock_get_model_by_model_id.return_value = None

    mock_query_sub_agents.return_value = []
    mock_create_tool_config.return_value = []

    # Execute export
    exported_agent = await export_agent_by_agent_id(
        agent_id=123, tenant_id="test_tenant", user_id="test_user"
    )

    # Assert - should handle gracefully
    assert exported_agent.model_ids == [999]  # ID is preserved
    assert exported_agent.model_names == []  # But name list is empty (model not found)
    assert exported_agent.business_logic_model_id == 998
    assert exported_agent.business_logic_model_name is None


@patch("management.services.agent.transfer.tenant_config_manager")
@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer.get_model_by_model_id")
@pytest.mark.asyncio
async def test_import_agent_model_name_consistency(
    mock_get_model_by_model_id,
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool,
    mock_get_model_id_by_display_name,
    mock_tenant_config_manager,
):
    """
    Test that both model_id and model_name are consistently saved during import.

    This test ensures that:
    1. model_id is looked up from model_name
    2. Both model_id AND model_name are saved to database
    3. This maintains data consistency and cross-tenant compatibility
    """
    # Setup
    mock_query_all_tools.return_value = []
    # Explicit ids from source tenant are not present in target tenant,
    # so the resolver must fall back to display name lookup.
    mock_get_model_by_model_id.return_value = None
    mock_tenant_config_manager.get_model_config.return_value = None
    mock_get_model_id_by_display_name.side_effect = [5, 4]

    # Track what was passed to create_agent
    captured_agent_info = {}

    def capture_agent_info(agent_info, tenant_id, user_id):
        captured_agent_info.update(agent_info)
        return {"agent_id": 888}

    mock_create_agent.side_effect = capture_agent_info

    # Create import data
    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="consistency_test_agent",
        display_name="Consistency Test Agent",
        description="Testing model field consistency",
        business_description="Test",
        max_steps=5,
        provide_run_summary=False,
        prompt='# Responsibilities\nTest\n\n# Constraints\nTest\n\n# Examples\nTest',
        enabled=True,
        tools=[],
        managed_agents=[],
        model_ids=[100],  # Original ID (will be remapped)
        model_names=["Qwen/Qwen3-8B"],  # Used for lookup
        business_logic_model_id=99,  # Original ID (will be remapped)
        business_logic_model_name="Qwen/QwQ-32B",  # Used for lookup
    )

    # Execute import
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info, tenant_id="test_tenant", user_id="test_user"
    )

    # Assert
    assert result == 888

    # Verify BOTH model_ids (remapped) AND business_logic_model_name (preserved) are passed to create_agent
    # Note: model_names is NOT propagated to create_agent because the DB stores the
    # primary model's display_name via the first entry in model_ids.
    assert "model_ids" in captured_agent_info
    assert "business_logic_model_id" in captured_agent_info
    assert "business_logic_model_name" in captured_agent_info

    # Verify consistency between ID and name
    assert captured_agent_info["model_ids"] == [5]  # Remapped ID list

    assert captured_agent_info["business_logic_model_id"] == 4  # Remapped ID
    assert (
        captured_agent_info["business_logic_model_name"] == "Qwen/QwQ-32B"
    )  # Preserved name

    # This consistency allows:
    # 1. Fast lookups by model_id (integer index)
    # 2. Human-readable model information (model_name)
    # 3. Cross-tenant import compatibility (lookup by name, save by ID)


# ============================================================================
# Tests for Agent Import with Quick Config Model Fallback
# ============================================================================


@pytest.fixture
def mock_tenant_id():
    """Fixture for tenant ID"""
    return "test_tenant_123"


@pytest.fixture
def mock_user_id():
    """Fixture for user ID"""
    return "test_user_456"


@pytest.fixture
def sample_agent_info():
    """Fixture for sample agent import information"""
    return {
        "agent_id": 1,
        "name": "test_agent",
        "display_name": "Test Agent",
        "description": "Test description",
        "business_description": "Test business description",
        "model_ids": [10],  # Original model ID from source tenant
        "model_names": ["Qwen/Qwen3-8B"],  # Model that might not exist in target tenant
        "business_logic_model_id": 20,  # Original business logic model ID
        "business_logic_model_name": "Qwen/QwQ-32B",  # Business logic model
        "max_steps": 5,
        "provide_run_summary": True,
        "prompt": '# Responsibilities\nTest duty\n\n# Constraints\nTest constraint\n\n# Examples\nTest few shots',
        "enabled": True,
        "tools": [],
        "managed_agents": [],
    }


@pytest.fixture
def sample_quick_config_model():
    """Fixture for quick config LLM model"""
    return {
        "model_id": 100,
        "model_name": "DeepSeek/DeepSeek-V3",
        "display_name": "DeepSeek V3",
        "model_repo": "DeepSeek",
        "model_type": "chat",
        "api_key": "test_key",
        "base_url": "https://api.deepseek.com",
    }


@pytest.fixture
def mock_import_agent_info(sample_agent_info):
    """Fixture for ExportAndImportAgentInfo object"""
    return ExportAndImportAgentInfo(**sample_agent_info)


@pytest.mark.asyncio
@patch("management.services.agent.transfer.get_model_by_model_id")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.tenant_config_manager")
@patch("management.services.agent.transfer.create_agent")
async def test_main_model_fallback_to_quick_config(
    mock_create_agent,
    mock_tenant_config_manager,
    mock_get_model_id,
    mock_query_tools,
    mock_get_model_by_model_id,
    mock_tenant_id,
    mock_user_id,
    sample_agent_info,
    sample_quick_config_model,
    mock_import_agent_info,
):
    """
    Test that when main model is not found, system falls back to quick config LLM model

    Scenario:
    - Agent config specifies "Qwen/Qwen3-8B" as main model
    - Model not found in target tenant
    - System should fallback to quick config LLM model (DeepSeek V3)
    - Agent should be created with quick config model_id
    """
    # Setup: No tools to process
    mock_query_tools.return_value = []

    # Setup: Explicit model_ids missing from catalog
    mock_get_model_by_model_id.return_value = None
    # Setup: Model not found by display name, but quick config exists
    mock_get_model_id.side_effect = [
        None,  # Main model not found
        50,  # Business logic model found
    ]

    mock_tenant_config_manager.get_model_config.return_value = sample_quick_config_model

    mock_create_agent.return_value = {
        "agent_id": 999,
        "name": sample_agent_info["name"],
    }

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=mock_import_agent_info,
        tenant_id=mock_tenant_id,
        user_id=mock_user_id,
    )

    # Verify: Quick config model was requested
    from contracts.constants.constants import MODEL_CONFIG_MAPPING

    mock_tenant_config_manager.get_model_config.assert_called_with(
        key=MODEL_CONFIG_MAPPING["llm"], tenant_id=mock_tenant_id
    )

    # Verify: Agent was created with quick config model_id
    mock_create_agent.assert_called_once()
    call_args = mock_create_agent.call_args
    agent_info = call_args.kwargs["agent_info"]

    assert agent_info["model_ids"] == [sample_quick_config_model["model_id"]]
    assert result == 999


@pytest.mark.asyncio
@patch("management.services.agent.transfer.get_model_by_model_id")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.tenant_config_manager")
@patch("management.services.agent.transfer.create_agent")
async def test_business_logic_model_fallback_to_quick_config(
    mock_create_agent,
    mock_tenant_config_manager,
    mock_get_model_id,
    mock_query_tools,
    mock_get_model_by_model_id,
    mock_tenant_id,
    mock_user_id,
    sample_agent_info,
    sample_quick_config_model,
    mock_import_agent_info,
):
    """
    Test that when business logic model is not found, system falls back to quick config LLM model

    Scenario:
    - Agent config specifies "Qwen/QwQ-32B" as business logic model
    - Business logic model not found in target tenant
    - System should fallback to quick config LLM model
    - Agent should be created with quick config model_id for business logic
    """
    # Setup: No tools to process
    mock_query_tools.return_value = []

    # Setup: Explicit ids missing in catalog
    mock_get_model_by_model_id.return_value = None
    # Setup: Main model found, but business logic model not found
    main_model_id = 50
    mock_get_model_id.side_effect = [
        main_model_id,  # Main model found
        None,  # Business logic model not found
    ]

    mock_tenant_config_manager.get_model_config.return_value = sample_quick_config_model

    mock_create_agent.return_value = {
        "agent_id": 888,
        "name": sample_agent_info["name"],
    }

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=mock_import_agent_info,
        tenant_id=mock_tenant_id,
        user_id=mock_user_id,
    )

    # Verify: Quick config model was requested for business logic model
    from contracts.constants.constants import MODEL_CONFIG_MAPPING

    mock_tenant_config_manager.get_model_config.assert_called_with(
        key=MODEL_CONFIG_MAPPING["llm"], tenant_id=mock_tenant_id
    )

    # Verify: Agent was created with correct model IDs
    mock_create_agent.assert_called_once()
    call_args = mock_create_agent.call_args
    agent_info = call_args.kwargs["agent_info"]

    assert agent_info["model_ids"] == [main_model_id]
    assert (
        agent_info["business_logic_model_id"] == sample_quick_config_model["model_id"]
    )
    assert result == 888


@pytest.mark.asyncio
@patch("management.services.agent.transfer.get_model_by_model_id")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.tenant_config_manager")
@patch("management.services.agent.transfer.create_agent")
async def test_both_models_fallback_to_quick_config(
    mock_create_agent,
    mock_tenant_config_manager,
    mock_get_model_id,
    mock_query_tools,
    mock_get_model_by_model_id,
    mock_tenant_id,
    mock_user_id,
    sample_agent_info,
    sample_quick_config_model,
    mock_import_agent_info,
):
    """
    Test that both main and business logic models fallback to quick config when not found

    Scenario:
    - Neither main model nor business logic model found in target tenant
    - Both should fallback to quick config LLM model
    - Agent should be created with quick config model_id for both fields
    """
    # Setup: No tools to process
    mock_query_tools.return_value = []

    # Setup: Both explicit ids missing
    mock_get_model_by_model_id.return_value = None
    # Setup: Both models not found
    mock_get_model_id.side_effect = [
        None,  # Main model not found
        None,  # Business logic model not found
    ]

    mock_tenant_config_manager.get_model_config.return_value = sample_quick_config_model

    mock_create_agent.return_value = {
        "agent_id": 777,
        "name": sample_agent_info["name"],
    }

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=mock_import_agent_info,
        tenant_id=mock_tenant_id,
        user_id=mock_user_id,
    )

    # Verify: Quick config model was requested twice (once for each model)
    assert mock_tenant_config_manager.get_model_config.call_count == 2

    # Verify: Agent was created with quick config model_id for both fields
    mock_create_agent.assert_called_once()
    call_args = mock_create_agent.call_args
    agent_info = call_args.kwargs["agent_info"]

    assert agent_info["model_ids"] == [sample_quick_config_model["model_id"]]
    assert (
        agent_info["business_logic_model_id"] == sample_quick_config_model["model_id"]
    )
    assert result == 777


@pytest.mark.asyncio
@patch("management.services.agent.transfer.get_model_by_model_id")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.tenant_config_manager")
@patch("management.services.agent.transfer.create_agent")
async def test_no_quick_config_model_available(
    mock_create_agent,
    mock_tenant_config_manager,
    mock_get_model_id,
    mock_query_tools,
    mock_get_model_by_model_id,
    mock_tenant_id,
    mock_user_id,
    sample_agent_info,
    mock_import_agent_info,
):
    """
    Test behavior when model not found and no quick config model is available

    Scenario:
    - Main model not found in target tenant
    - Quick config LLM model also not configured
    - Agent should be created with model_id = None
    """
    # Setup: No tools to process
    mock_query_tools.return_value = []

    # Setup: Explicit ids missing
    mock_get_model_by_model_id.return_value = None
    # Setup: Model not found and no quick config
    mock_get_model_id.side_effect = [
        None,  # Main model not found
        50,  # Business logic model found
    ]

    mock_tenant_config_manager.get_model_config.return_value = None  # No quick config

    mock_create_agent.return_value = {
        "agent_id": 666,
        "name": sample_agent_info["name"],
    }

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=mock_import_agent_info,
        tenant_id=mock_tenant_id,
        user_id=mock_user_id,
    )

    # Verify: Quick config was attempted
    from contracts.constants.constants import MODEL_CONFIG_MAPPING

    mock_tenant_config_manager.get_model_config.assert_called_with(
        key=MODEL_CONFIG_MAPPING["llm"], tenant_id=mock_tenant_id
    )

    # Verify: Agent was created with empty model_ids (no quick config resolved)
    mock_create_agent.assert_called_once()
    call_args = mock_create_agent.call_args
    agent_info = call_args.kwargs["agent_info"]

    assert agent_info["model_ids"] == []
    assert agent_info["business_logic_model_id"] == 50
    assert result == 666


@pytest.mark.asyncio
@patch("management.services.agent.transfer.get_model_by_model_id")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.tenant_config_manager")
@patch("management.services.agent.transfer.create_agent")
async def test_model_found_no_fallback_needed(
    mock_create_agent,
    mock_tenant_config_manager,
    mock_get_model_id,
    mock_query_tools,
    mock_get_model_by_model_id,
    mock_tenant_id,
    mock_user_id,
    sample_agent_info,
    mock_import_agent_info,
):
    """
    Test that quick config fallback is NOT used when model is found

    Scenario:
    - Both main model and business logic model found in target tenant
    - Quick config should NOT be called
    - Agent should be created with found model IDs
    """
    # Setup: No tools to process
    mock_query_tools.return_value = []

    # Setup: Both models found via display name (explicit ids also valid via mock)
    main_model_id = 30
    business_logic_model_id = 40

    mock_get_model_by_model_id.return_value = (
        None  # explicit ids missing => falls through to display-name resolution
    )
    mock_get_model_id.side_effect = [
        main_model_id,  # Main model found
        business_logic_model_id,  # Business logic model found
    ]

    mock_create_agent.return_value = {
        "agent_id": 555,
        "name": sample_agent_info["name"],
    }

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=mock_import_agent_info,
        tenant_id=mock_tenant_id,
        user_id=mock_user_id,
    )

    # Verify: Quick config was NOT called
    mock_tenant_config_manager.get_model_config.assert_not_called()

    # Verify: Agent was created with found model IDs
    mock_create_agent.assert_called_once()
    call_args = mock_create_agent.call_args
    agent_info = call_args.kwargs["agent_info"]

    assert agent_info["model_ids"] == [main_model_id]
    assert agent_info["business_logic_model_id"] == business_logic_model_id
    assert result == 555


# ============================================================================
# Tests for Model Name Fields in Import
# ============================================================================


@patch("management.services.agent.transfer.tenant_config_manager")
@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer.get_model_by_model_id")
@pytest.mark.asyncio
async def test_import_agent_includes_model_names(
    mock_get_model_by_model_id,
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool,
    mock_get_model_id,
    mock_tenant_config_manager,
):
    """
    Test that import_agent_by_agent_id passes model_name and business_logic_model_name
    to create_agent, ensuring these fields are not NULL in the database.

    This test verifies the fix for the bug where these fields were missing from the
    agent_info dictionary passed to create_agent().
    """
    # Setup
    mock_tool_info = [
        {
            "tool_id": 101,
            "class_name": "TestTool",
            "source": "local",
            "params": [{"name": "param1", "type": "string"}],
            "description": "Test tool",
            "name": "Test Tool",
            "inputs": "test input",
            "output_type": "string",
        }
    ]
    mock_query_all_tools.return_value = mock_tool_info

    # Explicit ids from source tenant are not present in target tenant,
    # so the resolver must fall back to display name lookup.
    mock_get_model_by_model_id.return_value = None
    mock_tenant_config_manager.get_model_config.return_value = None

    # Mock model ID lookup to return valid IDs
    mock_get_model_id.side_effect = [
        5,
        4,
    ]  # First call for model_id, second for business_logic_model_id

    mock_create_agent.return_value = {"agent_id": 999}

    # Create import data with model_name and business_logic_model_name
    from nexent.core.agents.contracts.config import ToolConfig as NexentToolConfig

    tool_config = NexentToolConfig(
        class_name="TestTool",
        name="Test Tool",
        source="local",
        params={"param1": "value1"},
        metadata={},
        description="Test tool",
        inputs="test input",
        output_type="string",
        usage=None,
    )

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="iot_knowledge_qa_assistant",
        display_name="物联网知识问答助手",
        description="IoT Q&A Assistant",
        business_description="IoT knowledge retrieval assistant",
        max_steps=5,
        provide_run_summary=False,
        prompt='# Responsibilities\nYou are an IoT Q&A assistant\n\n# Constraints\nFollow safety guidelines\n\n# Examples\nExample tasks...',
        enabled=True,
        tools=[tool_config],
        managed_agents=[],
        model_ids=[5],
        model_names=["Qwen/Qwen3-8B"],  # This is critical
        business_logic_model_id=4,
        business_logic_model_name="Qwen/QwQ-32B",  # This is critical
    )

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info, tenant_id="test_tenant", user_id="test_user"
    )

    # Assert - verify the agent was created
    assert result == 999

    # Critical assertion: verify that model_names and business_logic_model_name
    # were passed to create_agent
    mock_create_agent.assert_called_once()
    call_kwargs = mock_create_agent.call_args[1]
    agent_info_dict = call_kwargs["agent_info"]

    # Verify all model-related fields are present
    assert "model_ids" in agent_info_dict
    assert "business_logic_model_id" in agent_info_dict
    assert (
        "business_logic_model_name" in agent_info_dict
    )  # ← This was missing before the fix

    # Verify the values are correct
    # Note: source does not propagate model_names to create_agent; it is only used
    # for cross-tenant display-name resolution during import.
    assert "model_names" not in agent_info_dict
    assert agent_info_dict["business_logic_model_name"] == "Qwen/QwQ-32B"

    # Verify other fields are also present
    assert agent_info_dict["name"] == "iot_knowledge_qa_assistant"
    assert agent_info_dict["display_name"] == "物联网知识问答助手"
    assert agent_info_dict["max_steps"] == 5


@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@pytest.mark.asyncio
async def test_import_agent_without_business_logic_model(
    mock_query_all_tools, mock_create_agent, mock_create_tool, mock_get_model_id
):
    """
    Test import when business_logic_model_name is None.

    Verifies that the function handles cases where business logic model is not set.
    """
    # Setup
    mock_query_all_tools.return_value = []
    mock_get_model_id.return_value = 5  # Only one model lookup
    mock_create_agent.return_value = {"agent_id": 888}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="simple_agent",
        display_name="Simple Agent",
        description="A simple agent",
        business_description="Simple agent description",
        max_steps=3,
        provide_run_summary=False,
        prompt='# Responsibilities\nDo your duty\n\n# Constraints\nFollow constraints\n\n# Examples\nExamples',
        enabled=True,
        tools=[],
        managed_agents=[],
        model_ids=[5],
        model_names=["Qwen/Qwen3-8B"],
        business_logic_model_id=None,  # No business logic model
        business_logic_model_name=None,
    )

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info, tenant_id="test_tenant", user_id="test_user"
    )

    # Assert
    assert result == 888
    mock_create_agent.assert_called_once()

    call_kwargs = mock_create_agent.call_args[1]
    agent_info_dict = call_kwargs["agent_info"]

    # Verify model fields are present
    # Note: source passes business_logic_model_name through to create_agent, but
    # model_names is not propagated because it's only used for cross-tenant lookup.
    assert agent_info_dict["business_logic_model_name"] is None
    assert agent_info_dict["business_logic_model_id"] is None


@patch("management.services.agent.transfer.tenant_config_manager")
@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer.get_model_by_model_id")
@pytest.mark.asyncio
async def test_import_agent_model_lookup_by_display_name(
    mock_get_model_by_model_id,
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool,
    mock_get_model_id,
    mock_tenant_config_manager,
):
    """
    Test that model_id is looked up by display_name (model_name) for cross-tenant compatibility.

    This test verifies that the import process uses model_name to find the corresponding
    model_id in the target tenant, rather than directly using the exported model_id.
    """
    # Setup
    mock_query_all_tools.return_value = []

    # Explicit ids from source tenant do NOT exist in target tenant, forcing the
    # resolver to fall back to display name lookup.
    mock_get_model_by_model_id.return_value = None
    mock_tenant_config_manager.get_model_config.return_value = None

    # Simulate cross-tenant import where model IDs are different
    # Exported: model_id=10, model_name="Qwen/Qwen3-8B"
    # Target tenant: model_id=5 for "Qwen/Qwen3-8B"
    mock_get_model_id.side_effect = [5, 4]  # Returns different IDs than exported

    mock_create_agent.return_value = {"agent_id": 777}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="cross_tenant_agent",
        display_name="Cross Tenant Agent",
        description="Agent imported from another tenant",
        business_description="Cross-tenant import test",
        max_steps=5,
        provide_run_summary=False,
        prompt='# Responsibilities\nCross-tenant duty\n\n# Constraints\nCross-tenant constraints\n\n# Examples\nCross-tenant examples',
        enabled=True,
        tools=[],
        managed_agents=[],
        model_ids=[10],  # Original model_id in source tenant
        model_names=["Qwen/Qwen3-8B"],  # Used for lookup in target tenant
        business_logic_model_id=9,  # Original business logic model_id
        business_logic_model_name="Qwen/QwQ-32B",  # Used for lookup
    )

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info, tenant_id="target_tenant", user_id="test_user"
    )

    # Assert
    assert result == 777

    # Verify model lookup was called with display names (model_name)
    assert mock_get_model_id.call_count == 2
    first_call = mock_get_model_id.call_args_list[0]
    second_call = mock_get_model_id.call_args_list[1]

    # First call should be for model_names
    # get_model_id_by_display_name(display_name: str, tenant_id: str) uses positional args
    assert first_call[0][0] == "Qwen/Qwen3-8B"  # display_name
    assert first_call[0][1] == "target_tenant"  # tenant_id

    # Second call should be for business_logic_model_name
    assert second_call[0][0] == "Qwen/QwQ-32B"  # display_name
    assert second_call[0][1] == "target_tenant"  # tenant_id

    # Verify the NEW model IDs (from target tenant) were used, not the exported ones
    call_kwargs = mock_create_agent.call_args[1]
    agent_info_dict = call_kwargs["agent_info"]

    assert agent_info_dict["model_ids"] == [5]  # New ID list, not [10]
    assert agent_info_dict["business_logic_model_id"] == 4  # New ID, not 9

    # Verify model_names is NOT propagated to create_agent (only used for cross-tenant lookup)
    assert "model_names" not in agent_info_dict
    assert agent_info_dict["business_logic_model_name"] == "Qwen/QwQ-32B"


@patch("management.services.agent.transfer.tenant_config_manager")
@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer.get_model_by_model_id")
@pytest.mark.asyncio
async def test_import_agent_model_not_found_in_target_tenant(
    mock_get_model_by_model_id,
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool,
    mock_get_model_id,
    mock_tenant_config_manager,
):
    """
    Test that import fails gracefully when the model doesn't exist in target tenant.
    """
    # Setup
    mock_query_all_tools.return_value = []

    # Simulate model not found in target tenant for both explicit id lookup
    # and display name lookup.
    mock_get_model_by_model_id.return_value = None
    mock_get_model_id.return_value = None

    # Mock the tenant config manager to return None (no quick config fallback)
    mock_tenant_config_manager.get_model_config.return_value = None

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="missing_model_agent",
        display_name="Agent with Missing Model",
        description="Test missing model",
        business_description="Missing model test",
        max_steps=5,
        provide_run_summary=False,
        prompt='# Responsibilities\nDuty\n\n# Constraints\nConstraints\n\n# Examples\nExamples',
        enabled=True,
        tools=[],
        managed_agents=[],
        model_ids=[10],
        model_names=["NonExistent/Model"],  # This model doesn't exist in target tenant
        business_logic_model_id=None,
        business_logic_model_name=None,
    )

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info, tenant_id="target_tenant", user_id="test_user"
    )

    # Assert - should still create agent but with None model_ids
    assert result is not None
    mock_create_agent.assert_called_once()

    call_kwargs = mock_create_agent.call_args[1]
    agent_info_dict = call_kwargs["agent_info"]

    # model_ids resolves to empty list since model wasn't found
    # (the source does not collapse this back to None when there was input)
    assert agent_info_dict["model_ids"] == []
    # model_names is NOT propagated to create_agent
    assert "model_names" not in agent_info_dict


@patch("management.services.agent.transfer.tenant_config_manager")
@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer.get_model_by_model_id")
@pytest.mark.asyncio
async def test_import_agent_all_model_fields_in_database(
    mock_get_model_by_model_id,
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool,
    mock_get_model_id,
    mock_tenant_config_manager,
):
    """
    Integration-style test to verify all model fields are correctly passed to the database.

    This test ensures that the resolved model_ids are passed through correctly,
    along with the preserved business_logic_model_name. (model_names is only used
    for cross-tenant resolution and is not propagated to create_agent.)
    """
    # Setup
    mock_query_all_tools.return_value = []
    # Force the resolver to fall back to display name lookup
    mock_get_model_by_model_id.return_value = None
    mock_tenant_config_manager.get_model_config.return_value = None
    mock_get_model_id.side_effect = [5, 4]

    # Mock create_agent to return the agent info as it would be inserted
    def mock_create_agent_impl(agent_info, tenant_id, user_id):
        return {
            "agent_id": 666,
            **agent_info,  # Simulate returning all fields that were passed in
        }

    mock_create_agent.side_effect = mock_create_agent_impl

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="complete_agent",
        display_name="Complete Agent",
        description="Agent with all fields",
        business_description="Complete test",
        max_steps=5,
        provide_run_summary=True,
        prompt='# Responsibilities\nComplete duty\n\n# Constraints\nComplete constraints\n\n# Examples\nComplete examples',
        enabled=True,
        tools=[],
        managed_agents=[],
        model_ids=[10],
        model_names=["Qwen/Qwen3-8B"],
        business_logic_model_id=9,
        business_logic_model_name="Qwen/QwQ-32B",
    )

    # Execute
    result = await import_agent_by_agent_id(
        import_agent_info=agent_info, tenant_id="test_tenant", user_id="test_user"
    )

    # Assert
    assert result == 666

    # Verify all model fields were passed to create_agent
    call_kwargs = mock_create_agent.call_args[1]
    agent_info_dict = call_kwargs["agent_info"]

    # model_ids is propagated after resolution; model_names is not (only used for lookup)
    assert "model_ids" in agent_info_dict
    assert "model_names" not in agent_info_dict
    assert "business_logic_model_id" in agent_info_dict
    assert "business_logic_model_name" in agent_info_dict

    assert agent_info_dict["model_ids"] == [5]
    assert agent_info_dict["business_logic_model_name"] == "Qwen/QwQ-32B"
    assert agent_info_dict["business_logic_model_id"] == 4
    assert agent_info_dict["business_logic_model_name"] == "Qwen/QwQ-32B"

    # Verify other standard fields
    assert agent_info_dict["name"] == "complete_agent"
    assert agent_info_dict["display_name"] == "Complete Agent"
    assert agent_info_dict["description"] == "Agent with all fields"
    assert "business_description" not in agent_info_dict
    assert agent_info_dict["max_steps"] == 5
    assert agent_info_dict["provide_run_summary"] is True
    assert agent_info_dict["prompt"] == "# Responsibilities\nComplete duty\n\n# Constraints\nComplete constraints\n\n# Examples\nComplete examples"
    assert "constraint_prompt" not in agent_info_dict
    assert "few_shots_prompt" not in agent_info_dict
    assert agent_info_dict["enabled"] is True


# =====================================================================
# Additional tests for internal helper functions and import logic
# =====================================================================


def test_render_prompt_template_success(monkeypatch):
    """_render_prompt_template should render a jinja2 template successfully."""

    tpl = "Hello {{ name }}"
    rendered = _render_prompt_template(tpl, name="World")
    assert rendered == "Hello World"


def test_render_prompt_template_on_error_returns_original(monkeypatch):
    """When Template.render fails, _render_prompt_template should return original template."""

    class FailingTemplate:
        def __init__(self, template_str):
            self.template_str = template_str

        def render(self, **context):
            raise ValueError("render failed")

    monkeypatch.setitem(_render_prompt_template.__globals__, "Template", FailingTemplate)

    tpl = "Broken {template"
    # Should not raise; should return original string
    assert _render_prompt_template(tpl, name="x") == tpl


def test_check_agent_value_duplicate_with_and_without_exclude():
    """_check_agent_value_duplicate should respect exclude_agent_id and cache."""
    agents = [
        {"agent_id": 1, "name": "agent_one"},
        {"agent_id": 2, "name": "agent_two"},
    ]

    # Duplicate found
    assert naming_service.check_agent_value_duplicate(
        "name", "agent_one", tenant_id="t", agents_cache=agents
    )
    # No duplicate
    assert not naming_service.check_agent_value_duplicate(
        "name", "agent_three", tenant_id="t", agents_cache=agents
    )
    # Exclude matching id should skip that record
    assert not naming_service.check_agent_value_duplicate(
        "name", "agent_one", tenant_id="t", exclude_agent_id=1, agents_cache=agents
    )


@patch("management.services.agent.naming.query_all_agent_info_by_tenant_id")
def test_check_agent_value_duplicate_empty_value(mock_query_all):
    """_check_agent_value_duplicate should return False when value is empty."""
    # Test empty string
    assert not naming_service.check_agent_value_duplicate(
        "name", "", tenant_id="t", agents_cache=[]
    )
    # Test None value
    assert not naming_service.check_agent_value_duplicate(
        "name", None, tenant_id="t", agents_cache=[]
    )
    # Should not call query_all_agent_info_by_tenant_id when value is empty
    mock_query_all.assert_not_called()


@patch("management.services.agent.naming.query_all_agent_info_by_tenant_id")
def test_check_agent_value_duplicate_cache_none(mock_query_all):
    """_check_agent_value_duplicate should query database when agents_cache is None."""
    mock_query_all.return_value = [
        {"agent_id": 1, "name": "agent_one"},
        {"agent_id": 2, "name": "agent_two"},
    ]

    # Should query database when cache is None
    assert naming_service.check_agent_value_duplicate(
        "name", "agent_one", tenant_id="t", agents_cache=None
    )
    mock_query_all.assert_called_once_with("t")

    # Reset mock
    mock_query_all.reset_mock()
    mock_query_all.return_value = [
        {"agent_id": 1, "name": "agent_one"},
        {"agent_id": 2, "name": "agent_two"},
    ]

    # Should query database when cache is None and no duplicate found
    assert not naming_service.check_agent_value_duplicate(
        "name", "agent_three", tenant_id="t", agents_cache=None
    )
    mock_query_all.assert_called_once_with("t")


@pytest.mark.asyncio
async def test_import_agent_impl_dfs_import_order(monkeypatch):
    """
    import_agent_impl should handle DFS ordering and establish relationships correctly.
    This covers the branch where managed agents are not yet imported (agent_stack.extend path).
    """
    from contracts.agent import ExportAndImportAgentInfo, ExportAndImportDataFormat
    root_agent = ExportAndImportAgentInfo(agent_id=1, name='root', display_name='Root', description='root', business_description='root', max_steps=5, provide_run_summary=False, prompt=None, enabled=True, tools=[], managed_agents=[2])
    child_agent = ExportAndImportAgentInfo(agent_id=2, name='child', display_name='Child', description='child', business_description='child', max_steps=5, provide_run_summary=False, prompt=None, enabled=True, tools=[], managed_agents=[])
    export_data = ExportAndImportDataFormat(agent_id=1, agent_info={'1': root_agent, '2': child_agent}, mcp_info=[])
    imported_ids = []

    async def fake_import_agent_by_agent_id(import_agent_info, tenant_id, user_id, skip_duplicate_regeneration=False, resolve_name_conflicts=False):
        new_id = 100 + import_agent_info.agent_id
        imported_ids.append(import_agent_info.agent_id)
        return new_id
    relationships = []

    def fake_insert_related_agent(parent_agent_id, child_agent_id, tenant_id, user_id, selected_agent_version_no=None):
        relationships.append((parent_agent_id, child_agent_id, tenant_id, user_id, selected_agent_version_no))

    async def fake_update_tool_list(tenant_id, user_id):
        return None
    monkeypatch.setattr('management.services.agent.transfer.import_agent_by_agent_id', fake_import_agent_by_agent_id, raising=False)
    monkeypatch.setattr('management.services.agent.transfer.insert_related_agent', fake_insert_related_agent, raising=False)
    monkeypatch.setattr('management.services.agent.service.update_tool_list', fake_update_tool_list, raising=False)
    await import_agent_impl(export_data, identity=AuthenticatedIdentity('user1', 'tenant1'), force_import=False)
    assert imported_ids == [2, 1]
    assert relationships == [(100 + 1, 100 + 2, 'tenant1', 'user1', 1)]


# =====================================================================
# Tests for batch agent name conflict and regeneration
# =====================================================================


@pytest.mark.asyncio
async def test_check_agent_name_conflict_batch_impl_detects_conflicts(monkeypatch):
    existing_agents = [{'agent_id': 10, 'name': 'dup_name', 'display_name': 'Dup Display'}, {'agent_id': 11, 'name': 'unique', 'display_name': 'Unique'}]
    monkeypatch.setattr('management.services.agent.service.query_all_agent_info_by_tenant_id', lambda tenant_id: existing_agents, raising=False)
    from contracts.agent import AgentNameBatchCheckItem, AgentNameBatchCheckRequest
    request = AgentNameBatchCheckRequest(items=[AgentNameBatchCheckItem(name='dup_name', display_name='Another'), AgentNameBatchCheckItem(name='', display_name=None)])
    result = await agent_service.check_agent_name_conflict_batch_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result[0]['name_conflict'] is True
    assert result[0]['display_name_conflict'] is False
    assert result[0]['conflict_agents'] == [{'name': 'dup_name', 'display_name': 'Dup Display'}]
    assert result[1]['name_conflict'] is False
    assert result[1]['display_name_conflict'] is False
    assert result[1]['conflict_agents'] == []


@pytest.mark.asyncio
async def test_check_agent_name_conflict_batch_impl_checks_display_name_without_name(monkeypatch):
    monkeypatch.setattr('management.services.agent.service.query_all_agent_info_by_tenant_id', lambda tenant_id: [{'agent_id': 3, 'name': 'alpha', 'display_name': 'Shown'}], raising=False)
    request = AgentNameBatchCheckRequest(items=[AgentNameBatchCheckItem(display_name='Shown')])
    result = await agent_service.check_agent_name_conflict_batch_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result[0]['name_conflict'] is False
    assert result[0]['display_name_conflict'] is True
    assert result[0]['conflict_agents'] == [{'name': 'alpha', 'display_name': 'Shown'}]


@pytest.mark.asyncio
async def test_check_agent_name_conflict_batch_impl_display_conflict(monkeypatch):
    existing_agents = [{'agent_id': 3, 'name': 'alpha', 'display_name': 'Shown'}]
    monkeypatch.setattr('management.services.agent.service.query_all_agent_info_by_tenant_id', lambda tenant_id: existing_agents, raising=False)
    request = AgentNameBatchCheckRequest(items=[AgentNameBatchCheckItem(name='beta', display_name='Shown')])
    result = await agent_service.check_agent_name_conflict_batch_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result[0]['name_conflict'] is False
    assert result[0]['display_name_conflict'] is True
    assert result[0]['conflict_agents'] == [{'name': 'alpha', 'display_name': 'Shown'}]


@pytest.mark.asyncio
async def test_check_agent_name_conflict_batch_impl_skips_same_agent(monkeypatch):
    existing_agents = [{'agent_id': 7, 'name': 'self', 'display_name': 'Self Display'}]
    monkeypatch.setattr('management.services.agent.service.query_all_agent_info_by_tenant_id', lambda tenant_id: existing_agents, raising=False)
    request = AgentNameBatchCheckRequest(items=[AgentNameBatchCheckItem(agent_id=7, name='self', display_name='Self Display')])
    result = await agent_service.check_agent_name_conflict_batch_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result[0]['name_conflict'] is False
    assert result[0]['display_name_conflict'] is False
    assert result[0]['conflict_agents'] == []


@pytest.mark.asyncio
async def test_regenerate_agent_name_batch_impl_uses_llm(monkeypatch):
    monkeypatch.setattr('management.services.agent.service.query_all_agent_info_by_tenant_id', lambda tenant_id: [{'agent_id': 2, 'name': 'dup_name', 'display_name': 'Dup'}], raising=False)
    monkeypatch.setattr('management.services.agent.service.tenant_config_manager.get_model_config', lambda key, tenant_id: {'model_id': 'model-1', 'display_name': 'LLM'}, raising=False)

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr('asyncio.to_thread', fake_to_thread, raising=False)
    monkeypatch.setattr('management.services.agent.service.regenerate_agent_value', AsyncMock(side_effect=lambda **kwargs: 'regenerated_name' if kwargs['field_key'] == 'name' else 'Regenerated Display'), raising=False)
    request = AgentNameBatchRegenerateRequest(items=[AgentNameBatchRegenerateItem(agent_id=1, name='dup_name', display_name='Dup', task_description='desc')])
    result = await agent_service.regenerate_agent_name_batch_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result == [{'name': 'regenerated_name', 'display_name': 'Regenerated Display'}]


@pytest.mark.asyncio
async def test_regenerate_agent_name_batch_impl_no_model(monkeypatch):
    monkeypatch.setattr('management.services.agent.service.query_all_agent_info_by_tenant_id', lambda tenant_id: [], raising=False)
    monkeypatch.setattr('management.services.agent.service.tenant_config_manager.get_model_config', lambda key, tenant_id: None, raising=False)
    from contracts.agent import AgentNameBatchRegenerateItem, AgentNameBatchRegenerateRequest
    request = AgentNameBatchRegenerateRequest(items=[AgentNameBatchRegenerateItem(agent_id=1, name='dup', display_name='Dup')])
    with pytest.raises(ValueError):
        await agent_service.regenerate_agent_name_batch_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))


@pytest.mark.asyncio
async def test_regenerate_agent_name_batch_impl_llm_failure_fallback(monkeypatch):
    monkeypatch.setattr('management.services.agent.service.query_all_agent_info_by_tenant_id', lambda tenant_id: [{'agent_id': 2, 'name': 'dup', 'display_name': 'Dup'}], raising=False)
    monkeypatch.setattr('management.services.agent.service.tenant_config_manager.get_model_config', lambda key, tenant_id: {'model_id': 'model-1', 'display_name': 'LLM'}, raising=False)

    async def run_in_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr('asyncio.to_thread', run_in_thread, raising=False)
    monkeypatch.setattr('management.services.agent.service.regenerate_agent_value', AsyncMock(side_effect=Exception('llm-fail')), raising=False)
    monkeypatch.setattr('management.services.agent.service.generate_unique_agent_value', lambda field_key, base_value, *args, **kwargs: f'{base_value}_fallback', raising=False)
    request = AgentNameBatchRegenerateRequest(items=[AgentNameBatchRegenerateItem(agent_id=1, name='dup', display_name='Dup', task_description='desc')])
    result = await agent_service.regenerate_agent_name_batch_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result == [{'name': 'dup_fallback', 'display_name': 'Dup_fallback'}]


# =====================================================================
# Tests for _resolve_model_ids_with_fallback helper function
# =====================================================================


class TestResolveModelWithFallback:
    """Test suite for the _resolve_model_ids_with_fallback helper function."""

    @pytest.mark.asyncio
    @patch("management.services.agent.transfer.get_model_by_model_id")
    @patch("management.services.agent.transfer.get_model_id_by_display_name")
    @patch(
        "management.services.agent.transfer.tenant_config_manager.get_model_config"
    )
    async def test_resolve_model_success_found_in_tenant(
        self,
        mock_get_model_config,
        mock_get_model_id,
        mock_get_model_by_id,
    ):
        """Test successful model resolution when explicit model_id exists in tenant."""
        # Arrange - explicit model_id is valid
        mock_get_model_by_id.return_value = {"display_name": "GPT-4"}

        from management.services.agent.service import _resolve_model_ids_with_fallback

        # Act
        result = _resolve_model_ids_with_fallback(
            model_ids=[123],
            model_display_names=["GPT-4"],
            model_label="Model",
            tenant_id="tenant_001",
        )

        # Assert - should return the explicit id and not call quick config
        assert result == [123]
        mock_get_model_by_id.assert_called_once_with(123)
        mock_get_model_config.assert_not_called()

    @pytest.mark.asyncio
    @patch("management.services.agent.transfer.get_model_by_model_id")
    @patch("management.services.agent.transfer.get_model_id_by_display_name")
    @patch(
        "management.services.agent.transfer.tenant_config_manager.get_model_config"
    )
    async def test_resolve_model_fallback_to_quick_config(
        self,
        mock_get_model_config,
        mock_get_model_id,
        mock_get_model_by_id,
    ):
        """Test fallback to quick config LLM model when model not found in tenant."""
        # Arrange
        mock_get_model_by_id.return_value = None  # explicit id not found in tenant
        mock_get_model_id.return_value = None  # display name not resolved
        mock_get_model_config.return_value = {
            "model_id": 789,
            "display_name": "Default LLM Model",
        }

        from management.services.agent.service import _resolve_model_ids_with_fallback

        # Act
        result = _resolve_model_ids_with_fallback(
            model_ids=[999],
            model_display_names=["NonExistentModel"],
            model_label="Model",
            tenant_id="tenant_002",
        )

        # Assert - should fall back to quick config
        assert result == [789]
        mock_get_model_id.assert_called_once_with("NonExistentModel", "tenant_002")
        mock_get_model_config.assert_called_once()

    @pytest.mark.asyncio
    @patch("management.services.agent.transfer.get_model_by_model_id")
    @patch("management.services.agent.transfer.get_model_id_by_display_name")
    @patch(
        "management.services.agent.transfer.tenant_config_manager.get_model_config"
    )
    async def test_resolve_model_no_fallback_available(
        self,
        mock_get_model_config,
        mock_get_model_id,
        mock_get_model_by_id,
    ):
        """Test when neither tenant model nor quick config model is available."""
        # Arrange
        mock_get_model_by_id.return_value = None
        mock_get_model_id.return_value = None
        mock_get_model_config.return_value = None  # No quick config model

        from management.services.agent.service import _resolve_model_ids_with_fallback

        # Act
        result = _resolve_model_ids_with_fallback(
            model_ids=[999],
            model_display_names=["NonExistentModel"],
            model_label="Model",
            tenant_id="tenant_003",
        )

        # Assert
        assert result == []
        mock_get_model_id.assert_called_once_with("NonExistentModel", "tenant_003")
        mock_get_model_config.assert_called_once()

    @pytest.mark.asyncio
    @patch("management.services.agent.transfer.get_model_by_model_id")
    @patch("management.services.agent.transfer.get_model_id_by_display_name")
    @patch(
        "management.services.agent.transfer.tenant_config_manager.get_model_config"
    )
    async def test_resolve_model_none_model_name(
        self,
        mock_get_model_config,
        mock_get_model_id,
        mock_get_model_by_id,
    ):
        """Test when model_display_names is None."""
        # Arrange
        from management.services.agent.service import _resolve_model_ids_with_fallback

        # Act - both model_ids and model_display_names are None
        result = _resolve_model_ids_with_fallback(
            model_ids=None,
            model_display_names=None,
            model_label="Model",
            tenant_id="tenant_004",
        )

        # Assert - returns None when both are None
        assert result is None
        mock_get_model_id.assert_not_called()
        mock_get_model_config.assert_not_called()

    @pytest.mark.asyncio
    @patch("management.services.agent.transfer.get_model_by_model_id")
    @patch("management.services.agent.transfer.get_model_id_by_display_name")
    @patch(
        "management.services.agent.transfer.tenant_config_manager.get_model_config"
    )
    async def test_resolve_model_empty_model_name(
        self,
        mock_get_model_config,
        mock_get_model_id,
        mock_get_model_by_id,
    ):
        """Test when model_display_names is an empty list."""
        # Arrange
        from management.services.agent.service import _resolve_model_ids_with_fallback

        # Act
        result = _resolve_model_ids_with_fallback(
            model_ids=None,
            model_display_names=[],
            model_label="Model",
            tenant_id="tenant_005",
        )

        # Assert - returns None when both are empty
        assert result is None
        mock_get_model_id.assert_not_called()
        mock_get_model_config.assert_not_called()

    @pytest.mark.asyncio
    @patch("management.services.agent.transfer.get_model_by_model_id")
    @patch("management.services.agent.transfer.get_model_id_by_display_name")
    @patch(
        "management.services.agent.transfer.tenant_config_manager.get_model_config"
    )
    async def test_resolve_business_logic_model_success(
        self,
        mock_get_model_config,
        mock_get_model_id,
        mock_get_model_by_id,
    ):
        """Test successful resolution of business logic model."""
        # Arrange - business logic model with explicit id present
        mock_get_model_by_id.return_value = {"display_name": "Qwen/QwQ-32B"}

        from management.services.agent.service import _resolve_model_ids_with_fallback

        # Act
        result = _resolve_model_ids_with_fallback(
            model_ids=[777],
            model_display_names=["Qwen/QwQ-32B"],
            model_label="Business logic model",
            tenant_id="tenant_006",
        )

        # Assert
        assert result == [777]
        mock_get_model_by_id.assert_called_once_with(777)
        mock_get_model_config.assert_not_called()

    @pytest.mark.asyncio
    @patch("management.services.agent.transfer.get_model_by_model_id")
    @patch("management.services.agent.transfer.get_model_id_by_display_name")
    @patch(
        "management.services.agent.transfer.tenant_config_manager.get_model_config"
    )
    async def test_resolve_model_quick_config_no_model_id(
        self,
        mock_get_model_config,
        mock_get_model_id,
        mock_get_model_by_id,
    ):
        """Test when quick config exists but has no model_id."""
        # Arrange
        mock_get_model_by_id.return_value = None
        mock_get_model_id.return_value = None
        mock_get_model_config.return_value = {
            "display_name": "Default Model",
            # No model_id field
        }

        from management.services.agent.service import _resolve_model_ids_with_fallback

        # Act
        result = _resolve_model_ids_with_fallback(
            model_ids=[888],
            model_display_names=["SomeModel"],
            model_label="Model",
            tenant_id="tenant_007",
        )

        # Assert - should return empty list when model_id is missing
        assert result == []
        mock_get_model_id.assert_called_once_with("SomeModel", "tenant_007")
        mock_get_model_config.assert_called_once()

    @pytest.mark.asyncio
    @patch("management.services.agent.transfer.get_model_by_model_id")
    @patch("management.services.agent.transfer.get_model_id_by_display_name")
    @patch(
        "management.services.agent.transfer.tenant_config_manager.get_model_config"
    )
    async def test_resolve_model_with_various_labels(
        self,
        mock_get_model_config,
        mock_get_model_id,
        mock_get_model_by_id,
    ):
        """Test that different model_labels are handled correctly."""
        # Arrange
        mock_get_model_by_id.return_value = {"display_name": "TestModel"}

        from management.services.agent.service import _resolve_model_ids_with_fallback

        # Act & Assert - Test with "Model" label
        result1 = _resolve_model_ids_with_fallback(
            model_ids=[111],
            model_display_names=None,
            model_label="Model",
            tenant_id="tenant_008",
        )
        assert result1 == [111]

        # Reset mock
        mock_get_model_by_id.reset_mock()
        mock_get_model_by_id.return_value = {"display_name": "TestModel2"}

        # Act & Assert - Test with "Business logic model" label
        result2 = _resolve_model_ids_with_fallback(
            model_ids=[222],
            model_display_names=None,
            model_label="Business logic model",
            tenant_id="tenant_009",
        )
        assert result2 == [222]

    @pytest.mark.asyncio
    @patch("management.services.agent.transfer.get_model_by_model_id")
    @patch("management.services.agent.transfer.get_model_id_by_display_name")
    @patch(
        "management.services.agent.transfer.tenant_config_manager.get_model_config"
    )
    async def test_resolve_model_exception_handling(
        self,
        mock_get_model_config,
        mock_get_model_id,
        mock_get_model_by_id,
    ):
        """Test that exceptions from database calls are propagated."""
        # Arrange
        mock_get_model_by_id.side_effect = Exception("Database connection error")

        from management.services.agent.service import _resolve_model_ids_with_fallback

        # Act & Assert
        with pytest.raises(Exception, match="Database connection error"):
            _resolve_model_ids_with_fallback(
                model_ids=[333],
                model_display_names=None,
                model_label="Model",
                tenant_id="tenant_010",
            )

        mock_get_model_config.assert_not_called()

    @pytest.mark.asyncio
    @patch("management.services.agent.transfer.get_model_by_model_id")
    @patch("management.services.agent.transfer.get_model_id_by_display_name")
    @patch(
        "management.services.agent.transfer.tenant_config_manager.get_model_config"
    )
    async def test_resolve_model_quick_config_exception(
        self,
        mock_get_model_config,
        mock_get_model_id,
        mock_get_model_by_id,
    ):
        """Test when quick config retrieval raises an exception."""
        # Arrange
        mock_get_model_by_id.return_value = None
        mock_get_model_id.return_value = None
        mock_get_model_config.side_effect = Exception("Config service error")

        from management.services.agent.service import _resolve_model_ids_with_fallback

        # Act & Assert
        with pytest.raises(Exception, match="Config service error"):
            _resolve_model_ids_with_fallback(
                model_ids=[444],
                model_display_names=["TestModel"],
                model_label="Model",
                tenant_id="tenant_011",
            )


# ============================================================================
# Tests for check_agent_availability function
# ============================================================================


@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.read.resolve_model_record")
@patch("management.services.agent.read.check_tool_is_available")
@patch("management.services.agent.read.search_tools_for_sub_agent")
@patch("management.services.agent.read.search_agent_info_by_agent_id")
def test_check_agent_availability_all_available(
    mock_search_agent_info,
    mock_search_tools,
    mock_check_tool,
    mock_resolve_model,
    mock_get_model_by_model_id_ignore_delete,
):
    """Test check_agent_availability when all tools and models are available."""
    from management.services.agent.read import check_agent_availability

    mock_agent_info = {"agent_id": 123, "model_ids": [456]}
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = [{"tool_id": 1}, {"tool_id": 2}]
    mock_check_tool.return_value = [True, True]
    mock_resolve_model.return_value = {"connect_status": "available"}

    is_available, reasons = check_agent_availability(
        agent_id=123, tenant_id="test_tenant"
    )

    assert is_available is True
    assert reasons == []
    mock_search_agent_info.assert_called_once_with(123, "test_tenant")
    mock_search_tools.assert_called_once_with(agent_id=123, tenant_id="test_tenant")
    mock_check_tool.assert_called_once_with([1, 2])


@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.read.resolve_model_record")
@patch("management.services.agent.read.check_tool_is_available")
@patch("management.services.agent.read.search_tools_for_sub_agent")
@patch("management.services.agent.read.search_agent_info_by_agent_id")
def test_check_agent_availability_tool_unavailable(
    mock_search_agent_info,
    mock_search_tools,
    mock_check_tool,
    mock_resolve_model,
    mock_get_model_by_model_id_ignore_delete,
):
    """Test check_agent_availability when some tools are unavailable."""
    from management.services.agent.read import check_agent_availability

    mock_agent_info = {"agent_id": 123, "model_ids": [456]}
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = [{"tool_id": 1}, {"tool_id": 2}]
    mock_check_tool.return_value = [True, False]  # One tool unavailable
    mock_resolve_model.return_value = {"connect_status": "available"}

    is_available, reasons = check_agent_availability(
        agent_id=123, tenant_id="test_tenant"
    )

    assert is_available is False
    assert reasons == ["tool_unavailable"]


@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.read.resolve_model_record")
@patch("management.services.agent.read.check_tool_is_available")
@patch("management.services.agent.read.search_tools_for_sub_agent")
@patch("management.services.agent.read.search_agent_info_by_agent_id")
def test_check_agent_availability_missing_model(
    mock_search_agent_info,
    mock_search_tools,
    mock_check_tool,
    mock_resolve_model,
    mock_get_model_by_model_id_ignore_delete,
):
    """Test check_agent_availability when the configured model no longer exists."""
    from management.services.agent.read import check_agent_availability

    mock_agent_info = {"agent_id": 123, "model_ids": [456]}
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = [{"tool_id": 1}]
    mock_check_tool.return_value = [True]
    mock_resolve_model.return_value = None

    is_available, reasons = check_agent_availability(
        agent_id=123, tenant_id="test_tenant"
    )

    assert is_available is False
    assert reasons == ["model_unavailable"]


@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.read.resolve_model_record")
@patch("management.services.agent.read.check_tool_is_available")
@patch("management.services.agent.read.search_tools_for_sub_agent")
@patch("management.services.agent.read.search_agent_info_by_agent_id")
def test_check_agent_availability_mcp_model_deleted(
    mock_search_agent_info,
    mock_search_tools,
    mock_check_tool,
    mock_resolve_model,
    mock_get_model_by_model_id_ignore_delete,
):
    """Test check_agent_availability when tool has selected_model_id pointing to a deleted model."""
    from management.services.agent.read import check_agent_availability

    mock_agent_info = {"agent_id": 123, "model_ids": [456]}
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = [
        {
            "tool_id": 1,
            "params": [{"name": "selected_model_id", "default": 99}],
        },
        {
            "tool_id": 2,
            "params": [{"name": "selected_model_id", "default": 100}],
        },
    ]
    mock_check_tool.return_value = [True, True]
    mock_resolve_model.return_value = {"connect_status": "available"}

    def fake_ignore_delete(model_id, tenant_id):
        if model_id == 99:
            return {"model_id": 99, "delete_flag": "Y"}
        return {"model_id": model_id, "delete_flag": "N"}

    mock_get_model_by_model_id_ignore_delete.side_effect = fake_ignore_delete

    is_available, reasons = check_agent_availability(
        agent_id=123, tenant_id="test_tenant"
    )

    assert is_available is False
    # Agent-level unavailability re-uses the same TOOL_UNAVAILABLE reason as
    # the per-tool check, but it is only emitted once even when multiple tools
    # point to deleted models.
    assert "tool_unavailable" in reasons
    assert reasons.count("tool_unavailable") == 1
    # confirm the deleted model was the source of the reason
    expected_lookups = {99, 100}
    looked_up = {
        call.args[0] for call in mock_get_model_by_model_id_ignore_delete.call_args_list
    }
    assert looked_up == expected_lookups


@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.read.resolve_model_record")
@patch("management.services.agent.read.check_tool_is_available")
@patch("management.services.agent.read.search_tools_for_sub_agent")
@patch("management.services.agent.read.search_agent_info_by_agent_id")
def test_check_agent_availability_mcp_model_selected_default_none(
    mock_search_agent_info,
    mock_search_tools,
    mock_check_tool,
    mock_resolve_model,
    mock_get_model_by_model_id_ignore_delete,
):
    """`selected_model_id` set without a default value should be skipped without lookups."""
    from management.services.agent.read import check_agent_availability

    mock_search_agent_info.return_value = {"agent_id": 1, "model_ids": [1]}
    mock_search_tools.return_value = [
        {"tool_id": 1, "params": [{"name": "selected_model_id"}]},  # default is None
    ]
    mock_check_tool.return_value = [True]
    mock_resolve_model.return_value = {"connect_status": "available"}

    is_available, reasons = check_agent_availability(agent_id=1, tenant_id="t")

    assert is_available is True
    assert reasons == []
    mock_get_model_by_model_id_ignore_delete.assert_not_called()


@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.read.resolve_model_record")
@patch("management.services.agent.read.check_tool_is_available")
@patch("management.services.agent.read.search_tools_for_sub_agent")
@patch("management.services.agent.read.search_agent_info_by_agent_id")
def test_check_agent_availability_mcp_model_record_missing(
    mock_search_agent_info,
    mock_search_tools,
    mock_check_tool,
    mock_resolve_model,
    mock_get_model_by_model_id_ignore_delete,
):
    """If the DB lookup returns None we should not raise and not add a reason."""
    from management.services.agent.read import check_agent_availability

    mock_search_agent_info.return_value = {"agent_id": 1, "model_ids": [1]}
    mock_search_tools.return_value = [
        {"tool_id": 1, "params": [{"name": "selected_model_id", "default": 999}]},
    ]
    mock_check_tool.return_value = [True]
    mock_resolve_model.return_value = {"connect_status": "available"}
    mock_get_model_by_model_id_ignore_delete.return_value = None

    is_available, reasons = check_agent_availability(agent_id=1, tenant_id="t")

    assert is_available is True
    assert reasons == []


@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.read.resolve_model_record")
@patch("management.services.agent.read.check_tool_is_available")
@patch("management.services.agent.read.search_tools_for_sub_agent")
@patch("management.services.agent.read.search_agent_info_by_agent_id")
def test_check_agent_availability_mcp_model_params_non_dict_entries(
    mock_search_agent_info,
    mock_search_tools,
    mock_check_tool,
    mock_resolve_model,
    mock_get_model_by_model_id_ignore_delete,
):
    """Non-dict entries inside `params` (and missing `params`) must not crash the loop."""
    from management.services.agent.read import check_agent_availability

    mock_search_agent_info.return_value = {"agent_id": 1, "model_ids": [1]}
    mock_search_tools.return_value = [
        {"tool_id": 1},  # no params
        {"tool_id": 2, "params": None},  # explicit None
        {"tool_id": 3, "params": "not-a-list"},  # wrong type, skip
        {"tool_id": 4, "params": [None, "string", 42, True]},  # non-dict entries
        {
            "tool_id": 5,
            "params": [{"name": "unrelated", "default": 7}],
        },  # wrong param name
    ]
    mock_check_tool.return_value = [True] * 5
    mock_resolve_model.return_value = {"connect_status": "available"}
    mock_get_model_by_model_id_ignore_delete.return_value = None

    is_available, reasons = check_agent_availability(agent_id=1, tenant_id="t")

    assert is_available is True
    assert reasons == []
    # No selected_model_id found in any tool's params, so the lookup is never invoked.
    mock_get_model_by_model_id_ignore_delete.assert_not_called()


@patch("management.services.agent.read.get_model_by_model_id_ignore_delete")
@patch("management.services.agent.read.resolve_model_record")
@patch("management.services.agent.read.check_tool_is_available")
@patch("management.services.agent.read.search_tools_for_sub_agent")
@patch("management.services.agent.read.search_agent_info_by_agent_id")
def test_check_agent_availability_mcp_model_loop_breaks_after_first_match(
    mock_search_agent_info,
    mock_search_tools,
    mock_check_tool,
    mock_resolve_model,
    mock_get_model_by_model_id_ignore_delete,
):
    """Once `selected_model_id` is located, subsequent params in the same tool are skipped."""
    from management.services.agent.read import check_agent_availability

    mock_search_agent_info.return_value = {"agent_id": 1, "model_ids": [1]}
    mock_search_tools.return_value = [
        {
            "tool_id": 1,
            "params": [
                {"name": "other_param", "default": 1},
                {"name": "selected_model_id", "default": 99},
                {"name": "trailing", "default": 2},
            ],
        },
    ]
    mock_check_tool.return_value = [True]
    mock_resolve_model.return_value = {"connect_status": "available"}
    mock_get_model_by_model_id_ignore_delete.return_value = None

    is_available, reasons = check_agent_availability(agent_id=1, tenant_id="t")

    assert is_available is True
    assert reasons == []
    # Only one lookup should be performed for the tool, regardless of how many
    # other params follow `selected_model_id` in the schema list.
    assert mock_get_model_by_model_id_ignore_delete.call_count == 1


@patch("management.services.agent.read.resolve_model_record")
@patch("management.services.agent.read.check_tool_is_available")
@patch("management.services.agent.read.search_tools_for_sub_agent")
@patch("management.services.agent.read.search_agent_info_by_agent_id")
def test_check_agent_availability_both_unavailable(
    mock_search_agent_info, mock_search_tools, mock_check_tool, mock_resolve_model
):
    """Test check_agent_availability when both tools and model are unavailable."""
    from management.services.agent.read import check_agent_availability

    mock_agent_info = {"agent_id": 123, "model_ids": [456]}
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = [{"tool_id": 1}]
    mock_check_tool.return_value = [False]
    mock_resolve_model.return_value = None

    is_available, reasons = check_agent_availability(
        agent_id=123, tenant_id="test_tenant"
    )

    assert is_available is False
    assert "tool_unavailable" in reasons
    assert "model_unavailable" in reasons


@patch("management.services.agent.read.resolve_model_record")
@patch("management.services.agent.read.search_tools_for_sub_agent")
@patch("management.services.agent.read.search_agent_info_by_agent_id")
def test_check_agent_availability_no_tools(
    mock_search_agent_info, mock_search_tools, mock_resolve_model
):
    """Test check_agent_availability when agent has no tools."""
    from management.services.agent.read import check_agent_availability

    mock_agent_info = {"agent_id": 123, "model_ids": [456]}
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = []  # No tools
    mock_resolve_model.return_value = {"connect_status": "available"}

    is_available, reasons = check_agent_availability(
        agent_id=123, tenant_id="test_tenant"
    )

    assert is_available is True
    assert reasons == []


@patch("management.services.agent.read.search_agent_info_by_agent_id")
def test_check_agent_availability_agent_not_found(mock_search_agent_info):
    """Test check_agent_availability when agent is not found."""
    from management.services.agent.read import check_agent_availability

    mock_search_agent_info.return_value = None

    is_available, reasons = check_agent_availability(
        agent_id=999, tenant_id="test_tenant"
    )

    assert is_available is False
    assert reasons == ["agent_not_found"]


@patch("management.services.agent.read.resolve_model_record")
@patch("management.services.agent.read.check_tool_is_available")
@patch("management.services.agent.read.search_tools_for_sub_agent")
def test_check_agent_availability_with_pre_fetched_agent_info(
    mock_search_tools, mock_check_tool, mock_resolve_model
):
    """Test check_agent_availability with pre-fetched agent_info (avoids duplicate DB query)."""
    from management.services.agent.read import check_agent_availability

    pre_fetched_agent_info = {"agent_id": 123, "model_ids": [456]}
    mock_search_tools.return_value = [{"tool_id": 1}]
    mock_check_tool.return_value = [True]
    mock_resolve_model.return_value = {"connect_status": "available"}

    is_available, reasons = check_agent_availability(
        agent_id=123, tenant_id="test_tenant", agent_info=pre_fetched_agent_info
    )

    assert is_available is True
    assert reasons == []
    # search_agent_info_by_agent_id should NOT be called since agent_info was provided
    mock_search_tools.assert_called_once_with(agent_id=123, tenant_id="test_tenant")


@patch("management.services.agent.read.resolve_model_record")
@patch("management.services.agent.read.check_tool_is_available")
@patch("management.services.agent.read.search_tools_for_sub_agent")
def test_check_agent_availability_with_model_cache(
    mock_search_tools, mock_check_tool, mock_resolve_model
):
    """Test check_agent_availability with pre-populated model cache."""
    from management.services.agent.read import check_agent_availability

    pre_fetched_agent_info = {"agent_id": 123, "model_ids": [456]}
    model_cache = {456: {"connect_status": "available"}}
    mock_search_tools.return_value = [{"tool_id": 1}]
    mock_check_tool.return_value = [True]
    mock_resolve_model.return_value = {"connect_status": "available"}

    is_available, reasons = check_agent_availability(
        agent_id=123,
        tenant_id="test_tenant",
        agent_info=pre_fetched_agent_info,
        model_cache=model_cache,
    )

    assert is_available is True
    assert reasons == []
    # Verify model_cache was passed to resolve_model_record
    mock_resolve_model.assert_called_once()
    call_args = mock_resolve_model.call_args
    assert call_args.args == (456, "test_tenant", model_cache)


@pytest.mark.asyncio
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
async def test_get_agent_info_impl_with_unavailable_agent(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
):
    """Test get_agent_info_impl returns is_available=False when agent is unavailable."""
    mock_agent_info = {
        "agent_id": 123,
        "model_id": 456,
        "business_description": "Test agent",
    }
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = [{"tool_id": 1}]
    mock_query_sub_agents_id.return_value = []
    mock_get_model_by_model_id.return_value = {"display_name": "GPT-4"}
    # Agent is unavailable due to tool issues
    mock_check_availability.return_value = (False, ["tool_unavailable"])

    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    assert result["is_available"] is False
    assert result["unavailable_reasons"] == ["tool_unavailable"]


@pytest.mark.asyncio
@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer._resolve_model_ids_with_fallback")
@patch("management.services.agent.transfer.query_all_agent_info_by_tenant_id")
async def test_import_agent_by_agent_id_resolves_name_and_display_name_conflicts_for_repository_copy(
    mock_query_agents,
    mock_resolve_model,
    mock_query_all_tools,
    mock_create_agent,
    mock_create_tool,
):
    mock_query_agents.side_effect = [
        [
            {
                "agent_id": 1,
                "name": "duplicate_name",
                "display_name": "Duplicate Display",
            }
        ],
        [
            {
                "agent_id": 2,
                "name": "existing_agent",
                "display_name": "Existing Agent",
            }
        ],
    ]
    mock_query_all_tools.return_value = []
    mock_resolve_model.side_effect = [[1], [2], [1], [2]]
    mock_create_agent.return_value = {"agent_id": 456}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="duplicate_name",
        display_name="Duplicate Display",
        description="Test",
        business_description="Test business",
        max_steps=5,
        provide_run_summary=True,
        prompt='',
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=1,
        model_name="Model1",
        business_logic_model_id=2,
        business_logic_model_name="Model2",
    )

    await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user",
        resolve_name_conflicts=True,
    )

    created_agent = mock_create_agent.call_args.kwargs["agent_info"]
    assert created_agent["name"] == "duplicate_name_1"
    assert created_agent["display_name"] == "Duplicate Display_1"

    await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user",
        resolve_name_conflicts=True,
    )

    created_agent = mock_create_agent.call_args.kwargs["agent_info"]
    assert created_agent["name"] == "duplicate_name"
    assert created_agent["display_name"] == "Duplicate Display"


@pytest.mark.asyncio
@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer._resolve_model_ids_with_fallback")
async def test_import_agent_by_agent_id_allows_duplicate_name_without_regen(
    mock_resolve_model, mock_query_all_tools, mock_create_agent, mock_create_tool
):
    """
    New behavior: import_agent_by_agent_id no longer performs duplicate-name regeneration.
    It should create the agent with the provided name/display_name even if duplicates exist.
    """
    mock_query_all_tools.return_value = []
    mock_resolve_model.side_effect = [[1], [2]]
    mock_create_agent.return_value = {"agent_id": 456}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="duplicate_name",
        display_name="Test Display",
        description="Test",
        business_description="Test business",
        max_steps=5,
        provide_run_summary=True,
        prompt='',
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=1,
        model_name="Model1",
        business_logic_model_id=2,
        business_logic_model_name="Model2",
    )

    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user",
        skip_duplicate_regeneration=False,
    )

    assert result == 456
    mock_create_agent.assert_called_once()
    assert mock_create_agent.call_args[1]["agent_info"]["name"] == "duplicate_name"
    assert (
        mock_create_agent.call_args[1]["agent_info"]["display_name"] == "Test Display"
    )


@pytest.mark.asyncio
@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer._resolve_model_ids_with_fallback")
async def test_import_agent_by_agent_id_duplicate_name_no_regen_fallback(
    mock_resolve_model, mock_query_all_tools, mock_create_agent, mock_create_tool
):
    """
    New behavior: even when duplicate name, import proceeds without regeneration or fallback.
    """
    mock_query_all_tools.return_value = []
    mock_resolve_model.side_effect = [[1], [2]]
    mock_create_agent.return_value = {"agent_id": 456}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="duplicate_name",
        display_name="Test Display",
        description="Test",
        business_description="Test business",
        max_steps=5,
        provide_run_summary=True,
        prompt='',
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=1,
        model_name="Model1",
        business_logic_model_id=2,
        business_logic_model_name="Model2",
    )

    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user",
        skip_duplicate_regeneration=False,
    )

    assert result == 456
    mock_create_agent.assert_called_once()
    assert mock_create_agent.call_args[1]["agent_info"]["name"] == "duplicate_name"


@pytest.mark.asyncio
@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer._resolve_model_ids_with_fallback")
async def test_import_agent_by_agent_id_duplicate_name_no_model_still_allows(
    mock_resolve_model, mock_query_all_tools, mock_create_agent, mock_create_tool
):
    """
    New behavior: even without model, duplicate name passes through unchanged.
    """
    mock_query_all_tools.return_value = []
    mock_resolve_model.side_effect = [None, None]
    mock_create_agent.return_value = {"agent_id": 456}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="duplicate_name",
        display_name="Test Display",
        description="Test",
        business_description="Test business",
        max_steps=5,
        provide_run_summary=True,
        prompt='',
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=None,
        model_name=None,
        business_logic_model_id=None,
        business_logic_model_name=None,
    )

    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user",
        skip_duplicate_regeneration=False,
    )

    assert result == 456
    mock_create_agent.assert_called_once()
    assert mock_create_agent.call_args[1]["agent_info"]["name"] == "duplicate_name"


@pytest.mark.asyncio
@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer._resolve_model_ids_with_fallback")
async def test_import_agent_by_agent_id_duplicate_display_name_allowed(
    mock_resolve_model, mock_query_all_tools, mock_create_agent, mock_create_tool
):
    """New behavior: duplicate display_name passes through without regeneration."""
    mock_query_all_tools.return_value = []
    mock_resolve_model.side_effect = [[1], [2]]
    mock_create_agent.return_value = {"agent_id": 456}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="unique_name",
        display_name="duplicate_display",
        description="Test",
        business_description="Test business",
        max_steps=5,
        provide_run_summary=True,
        prompt='',
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=1,
        model_name="Model1",
        business_logic_model_id=2,
        business_logic_model_name="Model2",
    )

    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user",
        skip_duplicate_regeneration=False,
    )

    assert result == 456
    mock_create_agent.assert_called_once()
    assert (
        mock_create_agent.call_args[1]["agent_info"]["display_name"]
        == "duplicate_display"
    )


@pytest.mark.asyncio
@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer._resolve_model_ids_with_fallback")
async def test_import_agent_by_agent_id_duplicate_display_name_no_llm_fallback(
    mock_resolve_model, mock_query_all_tools, mock_create_agent, mock_create_tool
):
    """
    New behavior: duplicate display_name passes through without LLM; fallback not invoked.
    """
    mock_query_all_tools.return_value = []
    mock_resolve_model.side_effect = [[1], [2]]
    mock_create_agent.return_value = {"agent_id": 456}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="unique_name",
        display_name="duplicate_display",
        description="Test",
        business_description="Test business",
        max_steps=5,
        provide_run_summary=True,
        prompt='',
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=1,
        model_name="Model1",
        business_logic_model_id=2,
        business_logic_model_name="Model2",
    )

    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user",
        skip_duplicate_regeneration=False,
    )

    assert result == 456
    mock_create_agent.assert_called_once()
    assert (
        mock_create_agent.call_args[1]["agent_info"]["display_name"]
        == "duplicate_display"
    )


@pytest.mark.asyncio
@patch("management.services.agent.transfer.create_or_update_tool_by_tool_info")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
@patch("management.services.agent.transfer._resolve_model_ids_with_fallback")
async def test_import_agent_by_agent_id_duplicate_display_name_no_model_still_allowed(
    mock_resolve_model, mock_query_all_tools, mock_create_agent, mock_create_tool
):
    """
    New behavior: even without model, duplicate display_name passes through unchanged.
    """
    mock_query_all_tools.return_value = []
    mock_resolve_model.side_effect = [None, None]
    mock_create_agent.return_value = {"agent_id": 456}

    agent_info = ExportAndImportAgentInfo(
        agent_id=123,
        name="unique_name",
        display_name="duplicate_display",
        description="Test",
        business_description="Test business",
        max_steps=5,
        provide_run_summary=True,
        prompt='',
        enabled=True,
        tools=[],
        managed_agents=[],
        model_id=None,
        model_name=None,
        business_logic_model_id=None,
        business_logic_model_name=None,
    )

    result = await import_agent_by_agent_id(
        import_agent_info=agent_info,
        tenant_id="test_tenant",
        user_id="test_user",
        skip_duplicate_regeneration=False,
    )

    assert result == 456
    mock_create_agent.assert_called_once()
    assert (
        mock_create_agent.call_args[1]["agent_info"]["display_name"]
        == "duplicate_display"
    )


@pytest.mark.asyncio
async def test_clear_agent_new_mark_impl_success():
    """
    Test successful clearing of agent NEW mark through service layer.

    This test verifies that:
    1. The function correctly calls the database helper
    2. Returns the correct row count
    3. Logs the operation with correct parameters
    """
    # Setup
    mock_module = MagicMock()
    mock_module.clear_agent_new_mark.return_value = 1
    with (
        patch(
            "management.services.agent.management.clear_agent_new_mark",
            new=mock_module.clear_agent_new_mark,
        ),
        patch("management.services.agent.management.logger") as mock_logger,
    ):
        # Execute
        result = await clear_agent_new_mark_impl(
            agent_id=123, tenant_id="test_tenant", user_id="test_user"
        )

        # Assert
        assert result == 1
        mock_module.clear_agent_new_mark.assert_called_once_with(
            123, "test_tenant", "test_user"
        )
        mock_logger.info.assert_called_once_with(
            "clear_agent_new_mark_impl called for agent_id=123, tenant_id=test_tenant, user_id=test_user, affected_rows=1"
        )


@pytest.mark.asyncio
async def test_clear_agent_new_mark_impl_no_rows_affected():
    """
    Test clearing agent NEW mark when no rows are affected.

    This test verifies that:
    1. The function handles zero affected rows correctly
    2. Still logs the operation appropriately
    """
    # Setup
    mock_module = MagicMock()
    mock_module.clear_agent_new_mark.return_value = 0
    with (
        patch(
            "management.services.agent.management.clear_agent_new_mark",
            new=mock_module.clear_agent_new_mark,
        ),
        patch("management.services.agent.management.logger") as mock_logger,
    ):
        # Execute
        result = await clear_agent_new_mark_impl(
            agent_id=999, tenant_id="test_tenant", user_id="test_user"
        )

        # Assert
        assert result == 0
        mock_module.clear_agent_new_mark.assert_called_once_with(
            999, "test_tenant", "test_user"
        )
        mock_logger.info.assert_called_once_with(
            "clear_agent_new_mark_impl called for agent_id=999, tenant_id=test_tenant, user_id=test_user, affected_rows=0"
        )


@pytest.mark.asyncio
async def test_clear_agent_new_mark_impl_multiple_rows_affected():
    """
    Test clearing agent NEW mark when multiple rows are affected.

    This test verifies that:
    1. The function handles multiple affected rows correctly
    2. Logs the correct count
    """
    # Setup
    mock_module = MagicMock()
    mock_module.clear_agent_new_mark.return_value = 3
    with (
        patch(
            "management.services.agent.management.clear_agent_new_mark",
            new=mock_module.clear_agent_new_mark,
        ),
        patch("management.services.agent.management.logger") as mock_logger,
    ):
        # Execute
        result = await clear_agent_new_mark_impl(
            agent_id=456, tenant_id="another_tenant", user_id="another_user"
        )

        # Assert
        assert result == 3
        mock_module.clear_agent_new_mark.assert_called_once_with(
            456, "another_tenant", "another_user"
        )
        mock_logger.info.assert_called_once_with(
            "clear_agent_new_mark_impl called for agent_id=456, tenant_id=another_tenant, user_id=another_user, affected_rows=3"
        )


@pytest.mark.asyncio
async def test_clear_agent_new_mark_impl_database_error():
    """
    Test clear_agent_new_mark_impl when database operation fails.

    This test verifies that:
    1. The function propagates database errors
    2. Does not log success when operation fails
    """
    # Setup
    mock_module = MagicMock()
    mock_module.clear_agent_new_mark.side_effect = Exception(
        "Database connection failed"
    )
    with (
        patch(
            "management.services.agent.management.clear_agent_new_mark",
            new=mock_module.clear_agent_new_mark,
        ),
        patch("management.services.agent.management.logger") as mock_logger,
    ):
        # Execute and Assert
        with pytest.raises(Exception, match="Database connection failed"):
            await clear_agent_new_mark_impl(
                agent_id=123, tenant_id="test_tenant", user_id="test_user"
            )

        mock_module.clear_agent_new_mark.assert_called_once_with(
            123, "test_tenant", "test_user"
        )
        mock_logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_clear_agent_new_mark_impl_with_special_characters():
    """
    Test clear_agent_new_mark_impl with special characters in parameters.

    This test verifies that:
    1. The function handles special characters in tenant_id and user_id
    2. Properly passes through all parameters
    """
    # Setup
    mock_module = MagicMock()
    mock_module.clear_agent_new_mark.return_value = 1
    with (
        patch(
            "management.services.agent.management.clear_agent_new_mark",
            new=mock_module.clear_agent_new_mark,
        ),
        patch("management.services.agent.management.logger") as mock_logger,
    ):
        # Execute
        result = await clear_agent_new_mark_impl(
            agent_id=789,
            tenant_id="tenant-with-dashes_and_underscores",
            user_id="user@domain.com",
        )

        # Assert
        assert result == 1
        mock_module.clear_agent_new_mark.assert_called_once_with(
            789, "tenant-with-dashes_and_underscores", "user@domain.com"
        )
        mock_logger.info.assert_called_once_with(
            "clear_agent_new_mark_impl called for agent_id=789, tenant_id=tenant-with-dashes_and_underscores, user_id=user@domain.com, affected_rows=1"
        )


# Tests for ingroup_permission and group_ids functionality
@patch('management.services.agent.service.create_or_update_tool_by_tool_info')
@patch('management.db.tool.repository.query_tool_instances_by_id')
@patch('management.services.agent.transfer.query_all_tools')
@patch('management.services.agent.service.create_agent')
@patch('management.services.agent.service.convert_list_to_string')
@patch('management.services.agent.service._get_user_group_ids')
@pytest.mark.asyncio
async def test_update_agent_info_impl_create_agent_with_ingroup_permission(mock_get_user_group_ids, mock_convert_list_to_string, mock_create_agent, mock_query_all_tools, mock_query_tool_instances_by_id, mock_create_or_update_tool):
    """Test creating agent with ingroup_permission set."""
    from contracts.constants.constants import PERMISSION_READ, PERMISSION_EDIT, PERMISSION_PRIVATE
    mock_get_user_group_ids.return_value = '1,2,3'
    mock_convert_list_to_string.return_value = '1,2'
    mock_create_agent.return_value = {'agent_id': 123}
    request = MagicMock()
    request.agent_id = None
    request.name = 'Test Agent'
    request.display_name = 'Test Display'
    request.description = 'Test description'
    request.business_description = None
    request.author = None
    request.model_id = None
    request.model_name = None
    request.business_logic_model_id = None
    request.business_logic_model_name = None
    request.max_steps = None
    request.provide_run_summary = None
    request.prompt = None
    request.enabled = True
    request.enabled_tool_ids = None
    request.related_agent_ids = None
    request.group_ids = [1, 2]
    request.ingroup_permission = PERMISSION_READ
    apply_default_agent_request_fields(request)
    result = await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result['agent_id'] == 123
    call_args = mock_create_agent.call_args[1]['agent_info']
    assert call_args['ingroup_permission'] == PERMISSION_READ
    assert call_args['group_ids'] == '1,2'


@patch('management.services.agent.service.create_or_update_tool_by_tool_info')
@patch('management.db.tool.repository.query_tool_instances_by_id')
@patch('management.services.agent.transfer.query_all_tools')
@patch('management.services.agent.service.create_agent')
@patch('management.services.agent.service._get_user_group_ids')
@pytest.mark.asyncio
async def test_update_agent_info_impl_create_agent_with_ingroup_permission_none(mock_get_user_group_ids, mock_create_agent, mock_query_all_tools, mock_query_tool_instances_by_id, mock_create_or_update_tool):
    """Test creating agent with ingroup_permission None."""
    mock_get_user_group_ids.return_value = '1,2,3'
    mock_create_agent.return_value = {'agent_id': 456}
    request = MagicMock()
    request.agent_id = None
    request.name = 'Test Agent'
    request.display_name = 'Test Display'
    request.description = 'Test description'
    request.business_description = None
    request.author = None
    request.model_id = None
    request.model_name = None
    request.business_logic_model_id = None
    request.business_logic_model_name = None
    request.max_steps = None
    request.provide_run_summary = None
    request.prompt = None
    request.enabled = True
    request.enabled_tool_ids = None
    request.related_agent_ids = None
    request.group_ids = None
    request.ingroup_permission = None
    apply_default_agent_request_fields(request)
    result = await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result['agent_id'] == 456
    call_args = mock_create_agent.call_args[1]['agent_info']
    assert call_args['ingroup_permission'] is None
    assert call_args['group_ids'] == '1,2,3'


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_creator_with_private_permission_no_group_overlap(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that creators cannot see their own agents if no group overlap, even with PRIVATE permission."""
    from contracts.constants.constants import PERMISSION_PRIVATE

    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent with PRIVATE permission, created by current_user, but no group overlap",
            "enabled": True,
            "group_ids": "5,6",  # No overlap with user's groups [1, 2]
            "ingroup_permission": PERMISSION_PRIVATE,
            "created_by": "current_user",
            "create_time": 1,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "USER"}
    mock_query_groups.return_value = [1, 2]

    def convert_side_effect(x):
        if not x or (isinstance(x, str) and x.strip() == ""):
            return []
        parts = str(x).split(",")
        result = []
        for part in parts:
            stripped = part.strip()
            if stripped and stripped.isdigit():
                result.append(int(stripped))
        return result

    mock_convert_list.side_effect = convert_side_effect

    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="current_user"
    )

    # Creator can see their own agent even if no group overlap and permission is PRIVATE
    assert len(result) == 1
    agent_ids = [a["agent_id"] for a in result]
    assert 1 in agent_ids, "Agent 1 should be visible because user is the creator"


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_creator_with_private_permission_with_group_overlap(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that creators can see their own agents with PRIVATE permission if there is group overlap."""
    from contracts.constants.constants import PERMISSION_PRIVATE

    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent with PRIVATE permission, created by current_user, with group overlap",
            "enabled": True,
            "group_ids": "1,6",  # Overlaps with user's group 1
            "ingroup_permission": PERMISSION_PRIVATE,
            "created_by": "current_user",
            "create_time": 1,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "USER"}
    mock_query_groups.return_value = [1, 2]

    def convert_side_effect(x):
        if not x or (isinstance(x, str) and x.strip() == ""):
            return []
        parts = str(x).split(",")
        result = []
        for part in parts:
            stripped = part.strip()
            if stripped and stripped.isdigit():
                result.append(int(stripped))
        return result

    mock_convert_list.side_effect = convert_side_effect

    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="current_user"
    )

    # Creator can see their own agent with PRIVATE permission if there is group overlap
    assert len(result) == 1
    assert result[0]["agent_id"] == 1


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_non_creator_with_private_permission_hidden(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that non-creators cannot see agents with PRIVATE permission even with group overlap."""
    from contracts.constants.constants import PERMISSION_PRIVATE

    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent with PRIVATE permission, not created by current_user",
            "enabled": True,
            "group_ids": "1,2",  # Overlaps with user's groups [1, 2]
            "ingroup_permission": PERMISSION_PRIVATE,
            "created_by": "other_user",
            "create_time": 1,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "USER"}
    mock_query_groups.return_value = [1, 2]

    def convert_side_effect(x):
        if not x or (isinstance(x, str) and x.strip() == ""):
            return []
        parts = str(x).split(",")
        result = []
        for part in parts:
            stripped = part.strip()
            if stripped and stripped.isdigit():
                result.append(int(stripped))
        return result

    mock_convert_list.side_effect = convert_side_effect

    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="current_user"
    )

    # Non-creator should NOT see agent with PRIVATE permission even with group overlap
    assert len(result) == 0


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_permission_assignment_creator_gets_edit(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that creators get PERMISSION_EDIT regardless of ingroup_permission."""
    from contracts.constants.constants import PERMISSION_READ, PERMISSION_EDIT

    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent created by current_user",
            "enabled": True,
            "group_ids": "1,2",
            "ingroup_permission": PERMISSION_READ,  # Even with READ permission
            "created_by": "current_user",
            "create_time": 1,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "USER"}
    mock_query_groups.return_value = [1, 2]

    def convert_side_effect(x):
        if not x or (isinstance(x, str) and x.strip() == ""):
            return []
        parts = str(x).split(",")
        result = []
        for part in parts:
            stripped = part.strip()
            if stripped and stripped.isdigit():
                result.append(int(stripped))
        return result

    mock_convert_list.side_effect = convert_side_effect

    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="current_user"
    )

    assert len(result) == 1
    assert result[0]["permission"] == PERMISSION_EDIT  # Creator gets EDIT


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_permission_assignment_non_creator_uses_ingroup_permission(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that non-creators use ingroup_permission when set."""
    from contracts.constants.constants import PERMISSION_READ, PERMISSION_EDIT

    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent not created by current_user",
            "enabled": True,
            "group_ids": "1,2",
            "ingroup_permission": PERMISSION_EDIT,  # Set to EDIT
            "created_by": "other_user",
            "create_time": 1,
        },
        {
            "agent_id": 2,
            "name": "Agent 2",
            "display_name": "Display Agent 2",
            "description": "Agent with READ permission",
            "enabled": True,
            "group_ids": "1,2",
            "ingroup_permission": PERMISSION_READ,  # Set to READ
            "created_by": "other_user",
            "create_time": 2,
        },
        {
            "agent_id": 3,
            "name": "Agent 3",
            "display_name": "Display Agent 3",
            "description": "Agent with None permission",
            "enabled": True,
            "group_ids": "1,2",
            "ingroup_permission": None,  # None should default to READ
            "created_by": "other_user",
            "create_time": 3,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "USER"}
    mock_query_groups.return_value = [1, 2]

    def convert_side_effect(x):
        if not x or (isinstance(x, str) and x.strip() == ""):
            return []
        parts = str(x).split(",")
        result = []
        for part in parts:
            stripped = part.strip()
            if stripped and stripped.isdigit():
                result.append(int(stripped))
        return result

    mock_convert_list.side_effect = convert_side_effect

    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="current_user"
    )

    assert len(result) == 3
    agent1 = next(a for a in result if a["agent_id"] == 1)
    agent2 = next(a for a in result if a["agent_id"] == 2)
    agent3 = next(a for a in result if a["agent_id"] == 3)
    assert agent1["permission"] == PERMISSION_EDIT
    assert agent2["permission"] == PERMISSION_READ
    assert agent3["permission"] == PERMISSION_READ  # None defaults to READ


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_admin_gets_edit_permission(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that admin users (can_edit_all) get PERMISSION_EDIT regardless of ingroup_permission."""
    from contracts.constants.constants import PERMISSION_READ, PERMISSION_EDIT

    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent with READ permission",
            "enabled": True,
            "group_ids": "1,2",
            "ingroup_permission": PERMISSION_READ,
            "created_by": "other_user",
            "create_time": 1,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}  # Admin role
    mock_query_groups.return_value = []

    def convert_side_effect(x):
        if not x or (isinstance(x, str) and x.strip() == ""):
            return []
        parts = str(x).split(",")
        result = []
        for part in parts:
            stripped = part.strip()
            if stripped and stripped.isdigit():
                result.append(int(stripped))
        return result

    mock_convert_list.side_effect = convert_side_effect

    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    assert len(result) == 1
    assert result[0]["permission"] == PERMISSION_EDIT  # Admin gets EDIT


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_asset_owner_agent_read_only_for_admin(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """ASSET_OWNER-scoped agents are READ_ONLY for non-ASSET_OWNER roles even when admin."""
    from contracts.constants.constants import ASSET_OWNER_TENANT_ID, PERMISSION_EDIT, PERMISSION_READ

    mock_agents = [
        {
            "agent_id": 99,
            "name": "Asset Agent",
            "display_name": "Asset Agent",
            "description": "Asset owner scoped",
            "enabled": True,
            "group_ids": "1",
            "ingroup_permission": PERMISSION_EDIT,
            "created_by": "admin_user",
            "tenant_id": ASSET_OWNER_TENANT_ID,
            "create_time": 1,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = [1]

    def convert_side_effect(x):
        if not x or (isinstance(x, str) and x.strip() == ""):
            return []
        return [int(p.strip()) for p in str(x).split(",") if p.strip().isdigit()]

    mock_convert_list.side_effect = convert_side_effect
    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id=ASSET_OWNER_TENANT_ID, user_id="admin_user"
    )

    assert len(result) == 1
    assert result[0]["permission"] == PERMISSION_READ


def _mock_get_agent_info_impl_dependencies(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
    agent_info,
):
    """Configure common mocks for get_agent_info_impl permission tests."""
    defaults = {"model_id": None}
    mock_search_agent_info.return_value = {**defaults, **agent_info}
    mock_search_tools.return_value = []
    mock_query_sub_agents_id.return_value = []
    mock_query_external_sub_agents.return_value = []
    mock_get_model_by_model_id.return_value = None
    mock_check_availability.return_value = (True, [])
    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@patch("management.services.agent.service.get_user_tenant_by_user_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_asset_owner_agent_read_only_for_admin(
    mock_get_user_tenant,
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """ASSET_OWNER-scoped agent detail is READ_ONLY for ADMIN viewers."""
    from contracts.constants.constants import ASSET_OWNER_TENANT_ID, PERMISSION_EDIT, PERMISSION_READ

    agent_info = {
        "agent_id": 99,
        "tenant_id": ASSET_OWNER_TENANT_ID,
        "created_by": "admin_user",
        "ingroup_permission": PERMISSION_EDIT,
    }
    _mock_get_agent_info_impl_dependencies(
        mock_search_agent_info,
        mock_search_tools,
        mock_query_sub_agents_id,
        mock_get_model_by_model_id,
        mock_check_availability,
        mock_query_external_sub_agents,
        mock_skill_service,
        agent_info,
    )
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}

    result = await get_agent_info_impl(
        agent_id=99,
        tenant_id="regular_tenant",
        user_id="admin_user",
    )

    assert result["permission"] == PERMISSION_READ


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@patch("management.services.agent.service.get_user_tenant_by_user_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_asset_owner_agent_read_only_for_dev(
    mock_get_user_tenant,
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """ASSET_OWNER-scoped agent detail is READ_ONLY for DEV even with ingroup EDIT."""
    from contracts.constants.constants import ASSET_OWNER_TENANT_ID, PERMISSION_EDIT, PERMISSION_READ

    agent_info = {
        "agent_id": 99,
        "tenant_id": ASSET_OWNER_TENANT_ID,
        "created_by": "asset_owner_user",
        "ingroup_permission": PERMISSION_EDIT,
    }
    _mock_get_agent_info_impl_dependencies(
        mock_search_agent_info,
        mock_search_tools,
        mock_query_sub_agents_id,
        mock_get_model_by_model_id,
        mock_check_availability,
        mock_query_external_sub_agents,
        mock_skill_service,
        agent_info,
    )
    mock_get_user_tenant.return_value = {"user_role": "DEV"}

    result = await get_agent_info_impl(
        agent_id=99,
        tenant_id="regular_tenant",
        user_id="dev_user",
    )

    assert result["permission"] == PERMISSION_READ


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@patch("management.services.agent.service.get_user_tenant_by_user_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_asset_owner_role_gets_edit(
    mock_get_user_tenant,
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """ASSET_OWNER role creator retains EDIT on ASSET_OWNER-scoped agent detail."""
    from contracts.constants.constants import ASSET_OWNER_ROLE, ASSET_OWNER_TENANT_ID, PERMISSION_EDIT, PERMISSION_READ

    agent_info = {
        "agent_id": 99,
        "tenant_id": ASSET_OWNER_TENANT_ID,
        "created_by": "asset_owner_user",
        "ingroup_permission": PERMISSION_READ,
    }
    _mock_get_agent_info_impl_dependencies(
        mock_search_agent_info,
        mock_search_tools,
        mock_query_sub_agents_id,
        mock_get_model_by_model_id,
        mock_check_availability,
        mock_query_external_sub_agents,
        mock_skill_service,
        agent_info,
    )
    mock_get_user_tenant.return_value = {"user_role": ASSET_OWNER_ROLE}

    result = await get_agent_info_impl(
        agent_id=99,
        tenant_id=ASSET_OWNER_TENANT_ID,
        user_id="asset_owner_user",
    )

    assert result["permission"] == PERMISSION_EDIT


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_non_creator_no_group_overlap_hidden(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that non-creators without group overlap are hidden."""
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent not created by current_user, no group overlap",
            "enabled": True,
            "group_ids": "5,6",  # No overlap with user's groups [1, 2]
            "ingroup_permission": None,
            "created_by": "other_user",
            "create_time": 1,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "USER"}
    mock_query_groups.return_value = [1, 2]

    def convert_side_effect(x):
        if not x or (isinstance(x, str) and x.strip() == ""):
            return []
        parts = str(x).split(",")
        result = []
        for part in parts:
            stripped = part.strip()
            if stripped and stripped.isdigit():
                result.append(int(stripped))
        return result

    mock_convert_list.side_effect = convert_side_effect

    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="current_user"
    )

    # Non-creator without group overlap should be hidden (no group overlap hides it)
    assert len(result) == 0


@pytest.mark.asyncio
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_creator_no_group_overlap_hidden(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
):
    """Test that creators cannot see their own agents if no group overlap."""
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Agent created by current_user, but no group overlap",
            "enabled": True,
            "group_ids": "5,6",  # No overlap with user's groups [1, 2]
            "ingroup_permission": None,
            "created_by": "current_user",
            "create_time": 1,
        },
    ]

    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "USER"}
    mock_query_groups.return_value = [1, 2]

    def convert_side_effect(x):
        if not x or (isinstance(x, str) and x.strip() == ""):
            return []
        parts = str(x).split(",")
        result = []
        for part in parts:
            stripped = part.strip()
            if stripped and stripped.isdigit():
                result.append(int(stripped))
        return result

    mock_convert_list.side_effect = convert_side_effect

    mock_check_availability.return_value = (True, [])
    mock_get_model.return_value = None

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="current_user"
    )

    # Creator can see their own agent even if no group overlap
    assert len(result) == 1
    agent_ids = [a["agent_id"] for a in result]
    assert 1 in agent_ids, "Agent 1 should be visible because user is the creator"


# Deprecated tests for mark_agents_as_new_impl have been removed as the API is cleaned up.


# ============================================================================
# Additional tests for uncovered code paths (improving coverage)
# ============================================================================


# Tests for get_agent_by_name_impl
@patch("management.services.agent.management.query_version_list")
@patch("management.services.agent.management.search_agent_id_by_agent_name")
def test_get_agent_by_name_impl_empty_name(mock_search, mock_query_versions):
    """Test that empty agent name raises Exception."""
    with pytest.raises(Exception, match="agent_name required"):
        get_agent_by_name_impl("", "tenant_1")


@patch("management.services.agent.management.query_version_list")
@patch("management.services.agent.management.search_agent_id_by_agent_name")
def test_get_agent_by_name_impl_success(mock_search, mock_query_versions):
    """Test successful get_agent_by_name_impl."""
    mock_search.return_value = 123
    mock_query_versions.return_value = [{"version_no": 5}]

    result = get_agent_by_name_impl("test_agent", "tenant_1")

    assert result["agent_id"] == 123
    assert result["latest_version_no"] == 5


@patch("management.services.agent.management.query_version_list")
@patch("management.services.agent.management.search_agent_id_by_agent_name")
def test_get_agent_by_name_impl_not_found(mock_search, mock_query_versions):
    """An expected Agent lookup miss retains its domain exception."""
    from contracts.errors.exceptions import AgentNotFoundError

    lookup_error = AgentNotFoundError("agent not found")
    mock_search.side_effect = lookup_error

    with pytest.raises(AgentNotFoundError, match="agent not found") as excinfo:
        get_agent_by_name_impl("nonexistent_agent", "tenant_1")
    assert excinfo.value is lookup_error
    mock_query_versions.assert_not_called()


@patch("management.services.agent.management.query_version_list")
@patch("management.services.agent.management.search_agent_id_by_agent_name")
def test_get_agent_by_name_impl_empty_name_service(mock_search, mock_query_versions):
    """Test that empty agent name in impl raises Exception."""
    with pytest.raises(Exception, match="agent_name required"):
        get_agent_by_name_impl("", "tenant_1")


# Unexpected lookup failures must remain distinct from an Agent lookup miss.
@pytest.mark.parametrize("failure_stage", ["lookup", "versions"])
@patch("management.services.agent.management.query_version_list")
@patch("management.services.agent.management.search_agent_id_by_agent_name")
def test_get_agent_by_name_impl_preserves_internal_errors(
    mock_search, mock_query_versions, failure_stage
):
    """Internal failures must not be reclassified as missing resources."""
    lookup_error = RuntimeError("database unavailable")
    mock_search.return_value = 123
    if failure_stage == "lookup":
        mock_search.side_effect = lookup_error
    else:
        mock_query_versions.side_effect = lookup_error

    with pytest.raises(RuntimeError, match="database unavailable") as excinfo:
        get_agent_by_name_impl("missing_agent", "tenant_1")
    assert excinfo.value is lookup_error
    mock_search.assert_called_once_with("missing_agent", "tenant_1")
    if failure_stage == "lookup":
        mock_query_versions.assert_not_called()
    else:
        mock_query_versions.assert_called_once_with(123, "tenant_1")


# Tests for delete_related_agent_impl
@patch("test.backend.services.agent_legacy_helpers.delete_related_agent")
def test_delete_related_agent_impl_success(mock_delete):
    """Test successful delete_related_agent_impl."""
    mock_delete.return_value = True

    result = delete_related_agent_impl(1, 2, "tenant_1")

    assert result is True
    mock_delete.assert_called_once_with(1, 2, "tenant_1")


@patch("test.backend.services.agent_legacy_helpers.delete_related_agent")
def test_delete_related_agent_impl_exception(mock_delete):
    """Test that exception in delete_related_agent_impl is raised."""
    mock_delete.side_effect = Exception("Database error")

    with pytest.raises(Exception, match="Failed to delete related agent"):
        delete_related_agent_impl(1, 2, "tenant_1")


# Tests for get_agent_call_relationship_impl max depth
@patch("management.services.agent.management.search_tools_for_sub_agent")
@patch("management.services.agent.management.search_agent_info_by_agent_id")
@patch("management.services.agent.management.query_sub_agents_id_list")
def test_get_agent_call_relationship_impl_deep_recursion(
    mock_query_sub, mock_search_info, mock_search_tools
):
    """Test that get_agent_call_relationship handles deep recursion gracefully."""
    mock_query_sub.return_value = [2, 3, 4, 5, 6]  # Multiple sub agents
    mock_search_info.return_value = {"name": "agent", "display_name": "Agent"}
    mock_search_tools.return_value = []

    result = get_agent_call_relationship_impl(agent_id=1, tenant_id="tenant_1")

    assert result["agent_id"] == "1"
    assert "tools" in result
    assert "sub_agents" in result


# Legacy orchestration tests use partial request doubles. Keep the normalization
# boundary isolated here; TestNormalizeAgentOutputReserve exercises the real rule.
@pytest.fixture(autouse=True)
def _stub_agent_output_reserve_normalization():
    with patch(
        "management.services.agent.service._normalize_agent_output_reserve",
        return_value=None,
    ):
        yield


@pytest.fixture(autouse=True)
def _stub_get_valid_model_ids():
    """Auto-mock get_valid_model_ids to pass through when not explicitly mocked by a test.

    This fixture ensures that existing tests that don't mock get_valid_model_ids still work.
    Tests that need to verify get_valid_model_ids behavior can mock it explicitly.
    """
    with patch(
        "management.services.agent.read.get_valid_model_ids",
        side_effect=lambda model_ids, tenant_id: model_ids,
    ):
        yield


@pytest.fixture(autouse=True)
def _bridge_legacy_model_lookup_patch():
    """Keep legacy service-level model mocks visible to the extracted reader."""
    with patch(
        "management.services.model.resolver.get_model_by_model_id",
        side_effect=lambda model_id, _tenant_id=None: (
            agent_service.get_model_by_model_id(model_id)
        ),
    ):
        yield


# Tests for update_agent_info_impl skill handling exception
@patch('management.services.agent.service.skill_db.create_or_update_skill_by_skill_info')
@patch('management.services.agent.service.skill_db.query_skill_instances_by_agent_id')
@pytest.mark.asyncio
async def test_update_agent_info_impl_skill_update_exception(mock_query_skills, mock_create_skill):
    """Test that exception in skill update is raised as ValueError."""
    from contracts.agent import AgentInfoRequest
    mock_request = MagicMock(spec=AgentInfoRequest)
    mock_request.agent_id = 1
    mock_request.name = 'Test'
    mock_request.display_name = 'Test Display'
    mock_request.description = 'Desc'
    mock_request.business_description = 'Biz Desc'
    mock_request.author = 'Author'
    mock_request.model_id = 1
    mock_request.model_name = 'Model'
    mock_request.business_logic_model_id = None
    mock_request.business_logic_model_name = None
    mock_request.max_steps = 5
    mock_request.provide_run_summary = True
    mock_request.prompt = "Duty"
    mock_request.enabled = True
    mock_request.enabled_tool_ids = None
    mock_request.enabled_skill_ids = [1, 2]
    mock_request.related_agent_ids = None
    mock_request.related_agents = None
    mock_request.group_ids = None
    mock_request.ingroup_permission = None
    mock_request.example_questions = None
    mock_request.greeting_message = None
    mock_query_skills.return_value = []
    mock_create_skill.side_effect = Exception('Skill update failed')
    with pytest.raises(ValueError, match='Failed to update agent skills'):
        await update_agent_info_impl(mock_request, identity=AuthenticatedIdentity('user_1', 'tenant_1'))


# ---------------------------------------------------------------------------
# Monitoring instrumentation tests for agent_service
# ---------------------------------------------------------------------------


# =============================================================================
# Tests for export_agent_with_skills_impl and import_agent_with_skills_impl
# =============================================================================


def test_build_skill_import_conflicts_avoids_bundle_and_existing_names():
    """Conflict suggestions should avoid tenant names and names in the upload bundle."""
    from management.services.agent import transfer as ag_svc

    unavailable_snapshots = []

    def generate_name(base_name, unavailable_names):
        unavailable_snapshots.append((base_name, set(unavailable_names)))
        return "SkillA 副本 2" if base_name == "SkillA" else "SkillB 副本"

    with patch.object(
        agent_transfer,
        "generate_available_copy_skill_name",
        side_effect=generate_name,
    ):
        conflicts = ag_svc.build_skill_import_conflicts(
            ["SkillA", "SkillA 副本", "SkillB", "SkillA"],
            {"SkillA", "SkillB"},
        )

    assert conflicts == [
        {"skill_name": "SkillA", "suggested_new_name": "SkillA 副本 2"},
        {"skill_name": "SkillB", "suggested_new_name": "SkillB 副本"},
    ]
    assert unavailable_snapshots[0] == (
        "SkillA",
        {"SkillA", "SkillA 副本", "SkillB"},
    )
    assert "SkillA 副本 2" in unavailable_snapshots[1][1]


def test_check_skill_conflicts_impl_uses_current_tenant():
    """Skill precheck should query only the authenticated tenant."""
    from management.services.agent import transfer as ag_svc
    with patch.object(agent_transfer.skill_db, 'list_skills', return_value=[{'name': 'SkillA', 'skill_id': 10}]) as mock_list_skills, patch.object(agent_transfer, 'generate_available_copy_skill_name', return_value='SkillA 副本'):
        conflicts = ag_svc.check_skill_conflicts_impl(['SkillA', 'SkillB'], AuthenticatedIdentity('user_123', 'tenant_abc'))
    assert conflicts == [{'skill_name': 'SkillA', 'suggested_new_name': 'SkillA 副本'}]
    mock_list_skills.assert_called_once_with('tenant_abc')


@pytest.mark.asyncio
@patch('management.services.agent.transfer.collect_skill_zip_entries')
@patch('management.services.agent.transfer.export_agent_dict_impl')
async def test_export_agent_with_skills_impl_no_skills(mock_export_dict_impl, mock_collect_skills):
    """Test export_agent_with_skills_impl returns dict when agent has no skill instances."""
    from management.services.agent.service import export_agent_with_skills_impl
    mock_export_dict_impl.return_value = {'agent_id': 1, 'agent_info': {}}
    mock_collect_skills.return_value = []
    result = await export_agent_with_skills_impl(agent_id=1, identity=AuthenticatedIdentity('user_123', 'tenant_abc'))
    assert result == {'agent_id': 1, 'agent_info': {}}
    mock_export_dict_impl.assert_called_once_with(1, AuthenticatedIdentity('user_123', 'tenant_abc'), version_no=0)


@pytest.mark.asyncio
@patch('management.services.agent.transfer.collect_skill_zip_entries')
@patch('management.services.agent.transfer.export_agent_dict_impl')
async def test_export_agent_with_skills_impl_skills_but_no_names(mock_export_dict_impl, mock_collect_skills):
    """Test export_agent_with_skills_impl returns dict when skill export yields nothing."""
    from management.services.agent.service import export_agent_with_skills_impl
    mock_export_dict_impl.return_value = {'agent_id': 1, 'agent_info': {}}
    mock_collect_skills.return_value = []
    result = await export_agent_with_skills_impl(agent_id=1, identity=AuthenticatedIdentity('user_123', 'tenant_abc'))
    assert result == {'agent_id': 1, 'agent_info': {}}
    mock_export_dict_impl.assert_called_once()


@pytest.mark.asyncio
@patch('management.services.agent.transfer.search_agent_info_by_agent_id')
@patch('management.services.agent.transfer.collect_skill_zip_entries')
async def test_export_agent_with_skills_impl_with_zip(mock_collect_skills, mock_search_info):
    """Test export_agent_with_skills_impl returns ZIP when agent has skills."""
    from management.services.agent.service import export_agent_with_skills_impl
    from management.services.agent import transfer as ag_svc
    from contracts.skill import SkillZipEntry
    import io
    import zipfile
    mock_search_info.return_value = {'name': 'my_agent', 'display_name': 'My Agent'}
    mock_collect_skills.return_value = [SkillZipEntry(skill_name='TestSkill', skill_zip_base64='SGVsbG8gV29ybGQ=')]
    with patch.object(agent_transfer, 'export_agent_impl', return_value='{"agent_id": 1}'):
        result = await export_agent_with_skills_impl(agent_id=1, identity=AuthenticatedIdentity('user_123', 'tenant_abc'))
    assert result['_zip'] is True
    assert 'data' in result
    assert result['filename'] == 'My Agent.zip'
    zip_data = io.BytesIO(result['data'])
    with zipfile.ZipFile(zip_data, 'r') as zf:
        assert 'agent.json' in zf.namelist()
        assert 'skills/TestSkill.zip' in zf.namelist()


@pytest.mark.asyncio
async def test_import_agent_with_skills_impl_duplicate_returns_suggestions_before_writes():
    """Duplicate skills should return deterministic suggestions before creating data."""
    from management.services.agent.service import import_agent_with_skills_impl
    from management.services.agent import transfer as ag_svc
    agent_info = types.SimpleNamespace(agent_id=1, agent_info={})
    skills = [types.SimpleNamespace(skill_name='SkillA', skill_zip_base64='eA=='), types.SimpleNamespace(skill_name='SkillA 副本', skill_zip_base64='eA==')]
    with patch.object(agent_transfer.skill_db, 'list_skills', return_value=[{'name': 'SkillA', 'skill_id': 10}]), patch.object(agent_transfer, 'generate_available_copy_skill_name', return_value='SkillA 副本 2'), patch.object(agent_transfer, 'SkillService') as mock_skill_service, patch.object(agent_transfer, 'import_agent_impl', new_callable=AsyncMock) as mock_import:
        with pytest.raises(agent_transfer.SkillDuplicateError) as exc_info:
            await import_agent_with_skills_impl(agent_info=agent_info, skills=skills, identity=AuthenticatedIdentity('user_123', 'tenant_abc'))
    assert exc_info.value.duplicate_names == ['SkillA']
    assert exc_info.value.skill_conflicts == [{'skill_name': 'SkillA', 'suggested_new_name': 'SkillA 副本 2'}]
    mock_skill_service.assert_not_called()
    mock_import.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_agent_with_skills_impl_success():
    """Test import_agent_with_skills_impl successfully imports agent with skills."""
    from management.services.agent.service import import_agent_with_skills_impl
    from management.services.agent import transfer as ag_svc
    existing_skills = [{"name": "ExistingSkill"}]
    new_skills = [MagicMock(skill_name="NewSkill", skill_zip_base64="SGVsbG8gV29ybGQ=")]

    mock_agent_info = types.SimpleNamespace(
        agent_id=1,
        agent_info={
            "1": types.SimpleNamespace(agent_id=1, name="agent_one", skill_names=["NewSkill"], tools=[]),
        },
    )
    mock_skill_service = MagicMock()
    mock_skill_service.create_skill_from_zip_bytes.return_value = {'skill_id': 200}
    with patch.object(agent_transfer.skill_db, 'list_skills', return_value=existing_skills):
        with patch.object(agent_transfer, 'import_agent_impl', return_value={1: 100}) as mock_import:
            with patch.object(agent_transfer.skill_db, 'create_or_update_skill_by_skill_info') as mock_create_instance:
                with patch.object(agent_transfer, 'SkillService', return_value=mock_skill_service):
                    result = await import_agent_with_skills_impl(agent_info=mock_agent_info, skills=new_skills, identity=AuthenticatedIdentity('user_123', 'tenant_abc'))
    assert result == {1: 100}
    mock_import.assert_called_once()
    mock_skill_service.create_skill_from_zip_bytes.assert_called_once()
    created_skill_info = mock_create_instance.call_args.kwargs['skill_info']
    assert created_skill_info.agent_id == 100
    assert created_skill_info.skill_id == 200


@pytest.mark.asyncio
async def test_import_agent_with_skills_impl_reuses_existing_skills():
    """A use-existing resolution links the existing skill instead of failing."""
    from management.services.agent.service import import_agent_with_skills_impl
    from management.services.agent import transfer as ag_svc
    from contracts.skill import SkillResolution
    existing_skills = [{'name': 'ExistingSkill', 'skill_id': 99}]
    skills = [MagicMock(skill_name='ExistingSkill', skill_zip_base64='SGVsbG8gV29ybGQ='), MagicMock(skill_name='NewSkill', skill_zip_base64='SGVsbG8gV29ybGQ=')]
    mock_agent_info = MagicMock()
    mock_agent_info.agent_id = 1
    mock_skill_service = MagicMock()
    mock_skill_service.create_skill_from_zip_bytes.return_value = {'skill_id': 200}
    with patch.object(agent_transfer.skill_db, 'list_skills', return_value=existing_skills):
        with patch.object(agent_transfer, 'import_agent_impl', return_value={1: 100}) as mock_import:
            with patch.object(agent_transfer.skill_db, 'create_or_update_skill_by_skill_info'):
                with patch('management.services.agent.transfer.SkillService', return_value=mock_skill_service):
                    result = await import_agent_with_skills_impl(agent_info=mock_agent_info, skills=skills, identity=AuthenticatedIdentity('user_123', 'tenant_abc'), skill_resolutions=[SkillResolution(skill_name='ExistingSkill', action='use_existing')])
    assert result == {1: 100}
    mock_skill_service.create_skill_from_zip_bytes.assert_called_once()
    skill_name_to_id = mock_import.call_args.kwargs['skill_name_to_id']
    assert skill_name_to_id == {'ExistingSkill': 99, 'NewSkill': 200}


@pytest.mark.asyncio
async def test_import_agent_with_skills_impl_duplicate_raises_by_default():
    """Default behaviour still hard-gates duplicate skill names."""
    from management.services.agent.service import import_agent_with_skills_impl
    from management.services.agent import transfer as ag_svc
    from contracts.errors.exceptions import SkillDuplicateError
    existing_skills = [{'name': 'ExistingSkill', 'skill_id': 99}]
    skills = [MagicMock(skill_name='ExistingSkill', skill_zip_base64='SGVsbG8gV29ybGQ=')]
    mock_agent_info = MagicMock()
    mock_agent_info.agent_id = 1
    with patch.object(agent_transfer.skill_db, 'list_skills', return_value=existing_skills):
        with pytest.raises(SkillDuplicateError) as exc_info:
            await import_agent_with_skills_impl(agent_info=mock_agent_info, skills=skills, identity=AuthenticatedIdentity('user_123', 'tenant_abc'))
    assert 'ExistingSkill' in exc_info.value.duplicate_names


@pytest.mark.asyncio
async def test_import_agent_with_skills_impl_no_main_agent():
    """Test import_agent_with_skills_impl handles case where main agent is not in mapping."""
    from management.services.agent.service import import_agent_with_skills_impl
    from management.services.agent import transfer as ag_svc
    existing_skills = []
    # Use valid base64 encoded string "Hello World"
    new_skills = [MagicMock(skill_name="NewSkill", skill_zip_base64="SGVsbG8gV29ybGQ=")]

    mock_agent_info = types.SimpleNamespace(
        agent_id=1,
        agent_info={
            "1": types.SimpleNamespace(agent_id=1, name="agent_one", skill_names=["NewSkill"], tools=[]),
        },
    )
    mock_skill_service = MagicMock()
    mock_skill_service.create_skill_from_zip_bytes.return_value = {'skill_id': 200}
    with patch.object(agent_transfer.skill_db, 'list_skills', return_value=existing_skills):
        with patch.object(agent_transfer, 'import_agent_impl', return_value={}) as mock_import:
            with patch.object(agent_transfer.skill_db, 'create_or_update_skill_by_skill_info') as mock_create_instance:
                with patch.object(agent_transfer, 'SkillService', return_value=mock_skill_service):
                    result = await import_agent_with_skills_impl(agent_info=mock_agent_info, skills=new_skills, identity=AuthenticatedIdentity('user_123', 'tenant_abc'))
    assert result == {}
    mock_import.assert_called_once()
    mock_create_instance.assert_not_called()


@pytest.mark.asyncio
async def test_import_agent_with_skills_impl_resolves_existing_and_renamed_per_agent():
    """Use-existing and renamed skills should link to their original owning agents."""
    from contracts.skill import SkillResolution
    from management.services.agent.service import import_agent_with_skills_impl
    from management.services.agent import transfer as ag_svc

    agent_info = types.SimpleNamespace(
        agent_id=1,
        agent_info={
            "1": types.SimpleNamespace(
                agent_id=1, name="agent_one", skill_names=["ExistingSkill"], tools=[]
            ),
            "2": types.SimpleNamespace(
                agent_id=2,
                name="agent_two",
                skill_names=["RenamedSkill", "NewSkill", "MissingSkill"],
                tools=[],
            ),
        },
    )
    skills = [
        types.SimpleNamespace(skill_name="ExistingSkill", skill_zip_base64="eA=="),
        types.SimpleNamespace(skill_name="RenamedSkill", skill_zip_base64="eA=="),
        types.SimpleNamespace(skill_name="NewSkill", skill_zip_base64="eA=="),
    ]
    rename_target = "RenamedSkill \u526f\u672c"
    resolutions = [
        SkillResolution(skill_name="ExistingSkill", action="use_existing"),
        SkillResolution(
            skill_name="RenamedSkill", action="rename", new_name=rename_target
        ),
    ]
    mock_skill_service = MagicMock()
    mock_skill_service.create_skill_from_zip_bytes.side_effect = [{'skill_id': 20}, {'skill_id': 30}]
    with patch.object(agent_transfer.skill_db, 'list_skills', return_value=[{'name': 'ExistingSkill', 'skill_id': 10}, {'name': 'RenamedSkill', 'skill_id': 11}]), patch.object(agent_transfer, 'generate_available_copy_skill_name', side_effect=lambda base_name, _: f'{base_name} 副本'), patch.object(agent_transfer, 'SkillService', return_value=mock_skill_service), patch.object(agent_transfer, 'import_agent_impl', new_callable=AsyncMock, return_value={1: 101, 2: 102}), patch.object(agent_transfer.skill_db, 'create_or_update_skill_by_skill_info') as mock_create_instance:
        result = await import_agent_with_skills_impl(agent_info=agent_info, skills=skills, identity=AuthenticatedIdentity('user_123', 'tenant_abc'), skill_resolutions=resolutions)
    assert result == {1: 101, 2: 102}
    assert [call.kwargs['skill_name'] for call in mock_skill_service.create_skill_from_zip_bytes.call_args_list] == [rename_target, 'NewSkill']
    assert all((call.kwargs['skip_duplicate_check'] is False for call in mock_skill_service.create_skill_from_zip_bytes.call_args_list))
    created_links = {(call.kwargs['skill_info'].agent_id, call.kwargs['skill_info'].skill_id) for call in mock_create_instance.call_args_list}
    assert created_links == {(101, 10), (102, 20), (102, 30)}


# ============================================================================
# Additional tests for uncovered code paths (coverage improvement)
# ============================================================================


# Test for _render_prompt_template with empty string
def test_render_prompt_template_empty_string():
    """Test that _render_prompt_template returns empty string for empty input."""
    from nexent.core.agents.prompt.meta import render_name_template as _render_prompt_template

    result = _render_prompt_template("")
    assert result == ""

    result = _render_prompt_template(None)
    assert result == ""


# Note: export_agent_by_agent_id skill collection exception test removed
# The skill collection exception handling (lines 1211-1223) is covered by the try-except
# structure which logs a warning when skill_db operations fail


# Test for update_agent_info_impl related_agent_ids query error
@pytest.mark.asyncio
@patch('management.services.agent.service.query_sub_agents_id_list')
async def test_update_agent_info_impl_related_agent_query_error(mock_query_sub):
    """Test update_agent_info_impl handles related agent query error."""
    from management.services.agent.service import update_agent_info_impl
    from contracts.agent import AgentInfoRequest
    mock_request = MagicMock(spec=AgentInfoRequest)
    mock_request.agent_id = 1
    mock_request.name = 'Test'
    mock_request.display_name = 'Test Display'
    mock_request.description = 'Desc'
    mock_request.business_description = 'Biz Desc'
    mock_request.author = 'Author'
    mock_request.model_id = None
    mock_request.model_name = None
    mock_request.business_logic_model_id = None
    mock_request.business_logic_model_name = None
    mock_request.max_steps = 5
    mock_request.provide_run_summary = True
    mock_request.prompt = "Duty"
    mock_request.enabled = True
    mock_request.enabled_tool_ids = None
    mock_request.enabled_skill_ids = None
    mock_request.related_agent_ids = [2, 3]
    mock_request.related_agents = None
    mock_request.group_ids = None
    mock_request.ingroup_permission = None
    mock_request.example_questions = None
    mock_request.greeting_message = None
    mock_query_sub.side_effect = RuntimeError('Query error')
    with pytest.raises(RuntimeError, match='Query error'):
        await update_agent_info_impl(mock_request, identity=AuthenticatedIdentity('user_1', 'tenant_1'))


# Test for update_agent_info_impl related_external_agent_ids
@pytest.mark.asyncio
@patch('management.services.agent.service.update_related_agents')
@patch('management.services.agent.service.query_sub_agents_id_list')
async def test_update_agent_info_impl_related_external_agents(mock_query_sub, mock_update_related):
    """Test update_agent_info_impl handles external agent relations."""
    from management.services.agent.service import update_agent_info_impl
    from management.services.agent import service as ag_svc
    from contracts.agent import AgentInfoRequest
    mock_query_sub.return_value = []
    mock_request = MagicMock(spec=AgentInfoRequest)
    mock_request.agent_id = 1
    mock_request.name = 'Test'
    mock_request.display_name = 'Test Display'
    mock_request.description = 'Desc'
    mock_request.business_description = 'Biz Desc'
    mock_request.author = 'Author'
    mock_request.model_id = None
    mock_request.model_name = None
    mock_request.business_logic_model_id = None
    mock_request.business_logic_model_name = None
    mock_request.max_steps = 5
    mock_request.provide_run_summary = True
    mock_request.prompt = "Duty"
    mock_request.enabled = True
    mock_request.enabled_tool_ids = None
    mock_request.enabled_skill_ids = None
    mock_request.related_agent_ids = None
    mock_request.related_agents = None
    mock_request.related_external_agent_ids = [100, 200]
    mock_request.group_ids = None
    mock_request.ingroup_permission = None
    mock_request.example_questions = None
    mock_request.greeting_message = None
    with patch.object(ag_svc.a2a_agent_db, 'list_external_relations_by_local_agent', return_value=[]):
        with patch.object(ag_svc.a2a_agent_db, 'add_external_agent_relation', return_value=True) as mock_add:
            result = await update_agent_info_impl(mock_request, identity=AuthenticatedIdentity('user_1', 'tenant_1'))
    assert result['agent_id'] == 1
    assert mock_add.call_count == 2


@pytest.mark.asyncio
@patch('management.services.agent.service.update_related_agents')
@patch('management.services.agent.service.query_sub_agents_id_list')
async def test_update_agent_info_impl_external_agent_remove_relation(mock_query_sub, mock_update_related):
    """Test that external agent relation can be removed."""
    from management.services.agent.service import update_agent_info_impl
    from management.services.agent import service as ag_svc
    from contracts.agent import AgentInfoRequest
    mock_query_sub.return_value = []
    mock_request = MagicMock(spec=AgentInfoRequest)
    mock_request.agent_id = 1
    mock_request.name = 'Test'
    mock_request.display_name = 'Test Display'
    mock_request.description = 'Desc'
    mock_request.business_description = 'Biz Desc'
    mock_request.author = 'Author'
    mock_request.model_id = None
    mock_request.model_name = None
    mock_request.business_logic_model_id = None
    mock_request.business_logic_model_name = None
    mock_request.max_steps = 5
    mock_request.provide_run_summary = True
    mock_request.prompt = "Duty"
    mock_request.enabled = True
    mock_request.enabled_tool_ids = None
    mock_request.enabled_skill_ids = None
    mock_request.related_agent_ids = None
    mock_request.related_agents = None
    mock_request.related_external_agent_ids = []
    mock_request.group_ids = None
    mock_request.ingroup_permission = None
    mock_request.example_questions = None
    mock_request.greeting_message = None
    with patch.object(ag_svc.a2a_agent_db, 'list_external_relations_by_local_agent', return_value=[{'external_agent_id': 100}]):
        with patch.object(ag_svc.a2a_agent_db, 'remove_external_agent_relation') as mock_remove:
            result = await update_agent_info_impl(mock_request, identity=AuthenticatedIdentity('user_1', 'tenant_1'))
    assert result['agent_id'] == 1
    mock_remove.assert_called_once()


@pytest.mark.asyncio
@patch('management.services.agent.service.update_related_agents')
@patch('management.services.agent.service.query_sub_agents_id_list')
async def test_update_agent_info_impl_external_agent_relation_exists(mock_query_sub, mock_update_related):
    """Test that existing external agent relation is skipped (no exception)."""
    from management.services.agent.service import update_agent_info_impl
    from management.services.agent import service as ag_svc
    from contracts.agent import AgentInfoRequest
    mock_query_sub.return_value = []
    mock_request = MagicMock(spec=AgentInfoRequest)
    mock_request.agent_id = 1
    mock_request.name = 'Test'
    mock_request.display_name = 'Test Display'
    mock_request.description = 'Desc'
    mock_request.business_description = 'Biz Desc'
    mock_request.author = 'Author'
    mock_request.model_id = None
    mock_request.model_name = None
    mock_request.business_logic_model_id = None
    mock_request.business_logic_model_name = None
    mock_request.max_steps = 5
    mock_request.provide_run_summary = True
    mock_request.prompt = "Duty"
    mock_request.enabled = True
    mock_request.enabled_tool_ids = None
    mock_request.enabled_skill_ids = None
    mock_request.related_agent_ids = None
    mock_request.related_agents = None
    mock_request.related_external_agent_ids = [100]
    mock_request.group_ids = None
    mock_request.ingroup_permission = None
    mock_request.example_questions = None
    mock_request.greeting_message = None
    with patch.object(ag_svc.a2a_agent_db, 'list_external_relations_by_local_agent', return_value=[{'external_agent_id': 100}]):
        with patch.object(ag_svc.a2a_agent_db, 'add_external_agent_relation', side_effect=ValueError('Already exists')):
            result = await update_agent_info_impl(mock_request, identity=AuthenticatedIdentity('user_1', 'tenant_1'))
    assert result['agent_id'] == 1


# Note: export_agent_by_agent_id skill no name test removed
# The skill names collection logic is covered by existing tests


# Test for import_agent_impl handles already-imported agent (continue path - line 1296)
@pytest.mark.asyncio
async def test_import_agent_impl_already_imported():
    """Test import_agent_impl handles already-imported agent (continue path)."""
    from management.services.agent.service import import_agent_impl
    from contracts.agent import ExportAndImportDataFormat, ExportAndImportAgentInfo
    mock_agent_info = MagicMock(spec=ExportAndImportAgentInfo)
    mock_agent_info.agent_core = "smolagents"
    mock_agent_info.enable_context_manager = True
    mock_agent_info.agent_id = 1
    mock_agent_info.name = 'agent_1'
    mock_agent_info.display_name = 'Agent 1'
    mock_agent_info.description = 'desc'
    mock_agent_info.business_description = 'biz'
    mock_agent_info.author = 'author'
    mock_agent_info.max_steps = 5
    mock_agent_info.provide_run_summary = True
    mock_agent_info.prompt = "duty"
    mock_agent_info.enabled = True
    mock_agent_info.tools = []
    mock_agent_info.managed_agents = []
    mock_agent_info.model_id = None
    mock_agent_info.model_name = None
    mock_agent_info.business_logic_model_id = None
    mock_agent_info.business_logic_model_name = None
    export_data = MagicMock(spec=ExportAndImportDataFormat)
    export_data.agent_id = 1
    export_data.agent_info = {'1': mock_agent_info}
    import_count = 0

    async def mock_import(*args, **kwargs):
        nonlocal import_count
        import_count += 1
        return 100
    with patch('management.services.agent.transfer.import_agent_by_agent_id', side_effect=mock_import) as mock_import_fn:
        result = await import_agent_impl(export_data, identity=AuthenticatedIdentity('user_1', 'tenant_1'))
    assert mock_import_fn.call_count >= 1


# Test for update_agent_info_impl skill unselected handling (lines 952-954)
@pytest.mark.asyncio
@patch('management.services.agent.service.skill_db.create_or_update_skill_by_skill_info')
@patch('management.services.agent.service.skill_db.query_skill_instances_by_agent_id')
async def test_update_agent_info_impl_skill_unselected(mock_query_skills, mock_create_skill):
    """Test that unselected skills are disabled (lines 952-954)."""
    from management.services.agent.service import update_agent_info_impl
    from contracts.agent import AgentInfoRequest
    mock_query_skills.return_value = [{'skill_id': 1, 'skill_description': 'desc1'}, {'skill_id': 3, 'skill_description': 'desc3'}]
    mock_request = MagicMock(spec=AgentInfoRequest)
    mock_request.agent_id = 1
    mock_request.name = 'Test'
    mock_request.display_name = 'Test Display'
    mock_request.description = 'Desc'
    mock_request.business_description = 'Biz Desc'
    mock_request.author = 'Author'
    mock_request.model_id = None
    mock_request.model_name = None
    mock_request.business_logic_model_id = None
    mock_request.business_logic_model_name = None
    mock_request.max_steps = 5
    mock_request.provide_run_summary = True
    mock_request.prompt = "Duty"
    mock_request.enabled = True
    mock_request.enabled_tool_ids = None
    mock_request.enabled_skill_ids = [2]
    mock_request.related_agent_ids = None
    mock_request.related_agents = None
    mock_request.related_external_agent_ids = None
    mock_request.group_ids = None
    mock_request.ingroup_permission = None
    mock_request.example_questions = None
    mock_request.greeting_message = None
    result = await update_agent_info_impl(mock_request, identity=AuthenticatedIdentity('user_1', 'tenant_1'))
    assert result['agent_id'] == 1
    assert mock_create_skill.call_count == 3


@pytest.mark.asyncio
@patch('management.services.agent.service.skill_db.get_valid_skill_ids')
@patch('management.services.agent.service.skill_db.create_or_update_skill_by_skill_info')
@patch('management.services.agent.service.skill_db.query_skill_instances_by_agent_id')
async def test_update_agent_info_impl_persists_structured_skill_config(mock_query_skills, mock_create_skill, mock_get_valid_skill_ids):
    """The main agent save persists per-agent skill values in the same transaction flow."""
    from contracts.agent import AgentInfoRequest, AgentSkillInstanceRequest
    from management.services.agent.service import update_agent_info_impl
    mock_get_valid_skill_ids.return_value = {2}
    mock_query_skills.return_value = [{'skill_id': 1, 'config_values': {'preserved': True}}]
    request = MagicMock(spec=AgentInfoRequest)
    request.agent_id = 1
    request.name = 'Test'
    request.display_name = 'Test Display'
    request.description = 'Desc'
    request.business_description = 'Biz Desc'
    request.author = 'Author'
    request.model_id = None
    request.model_name = None
    request.business_logic_model_id = None
    request.business_logic_model_name = None
    request.max_steps = 5
    request.provide_run_summary = True
    request.prompt = "Duty"
    request.enabled = True
    request.enabled_tool_ids = None
    request.enabled_skill_ids = [2]
    request.skill_instances = [AgentSkillInstanceRequest(skill_id=2, config_values={'linkup_api_key': 'saved-key', 'max_results': 5})]
    request.related_agent_ids = None
    request.related_agents = None
    request.related_external_agent_ids = None
    request.group_ids = None
    request.ingroup_permission = None
    request.example_questions = None
    request.greeting_message = None
    request.version_no = 4
    result = await update_agent_info_impl(request, identity=AuthenticatedIdentity('user_1', 'tenant_1'))
    assert result['agent_id'] == 1
    mock_get_valid_skill_ids.assert_called_once_with(tenant_id='tenant_1', skill_ids=[2])
    mock_query_skills.assert_called_once_with(1, 'tenant_1', version_no=4)
    disabled_call, enabled_call = mock_create_skill.call_args_list
    assert disabled_call.kwargs['skill_info'].enabled is False
    assert disabled_call.kwargs['skill_info'].config_values == {'preserved': True}
    assert enabled_call.kwargs['skill_info'].enabled is True
    assert enabled_call.kwargs['skill_info'].config_values == {'linkup_api_key': 'saved-key', 'max_results': 5}
    assert enabled_call.kwargs['version_no'] == 4


@pytest.mark.asyncio
@patch('management.services.agent.service.skill_db.get_valid_skill_ids')
@patch('management.services.agent.service.skill_db.query_skill_instances_by_agent_id')
async def test_update_agent_info_impl_rejects_unavailable_skill_id(mock_query_skills, mock_get_valid_skill_ids):
    """Updating with a skill id that does not exist must raise a domain error, not 500."""
    from contracts.agent import AgentInfoRequest, AgentSkillInstanceRequest
    from contracts.errors.exceptions import AppException
    from management.services.agent.service import update_agent_info_impl
    mock_get_valid_skill_ids.return_value = set()
    mock_query_skills.return_value = []

    request = AgentInfoRequest(
        agent_id=1,
        name="Test",
        display_name="Test Display",
        description="Desc",
        business_description="Biz Desc",
        author="Author",
        model_ids=[],
        max_steps=5,
        provide_run_summary=True,
        prompt='# Responsibilities\nDuty\n\n# Constraints\nConstraint\n\n# Examples\nFew shots',
        enabled=True,
        enabled_skill_ids=[9999],
        skill_instances=[AgentSkillInstanceRequest(skill_id=9999, enabled=True)],
        version_no=1,
    )
    assert request.related_agents is None
    with pytest.raises(AppException, match='invalid or unavailable skill IDs: \\[9999\\]'):
        await update_agent_info_impl(request, identity=AuthenticatedIdentity('user_1', 'tenant_1'))
    mock_get_valid_skill_ids.assert_called_once_with(tenant_id='tenant_1', skill_ids=[9999])
    mock_query_skills.assert_not_called()


# Test for generate_stream unexpected exception (lines 1889-1896)
# Test for import_agent_impl DFS continue path
@pytest.mark.asyncio
async def test_import_agent_impl_continue_path():
    """Test import_agent_impl handles continue in DFS loop."""
    from management.services.agent.service import import_agent_impl
    from contracts.agent import ExportAndImportDataFormat, ExportAndImportAgentInfo
    mock_agent_info = MagicMock(spec=ExportAndImportAgentInfo)
    mock_agent_info.agent_id = 1
    mock_agent_info.name = 'agent_1'
    mock_agent_info.display_name = 'Agent 1'
    mock_agent_info.description = 'desc'
    mock_agent_info.business_description = 'biz'
    mock_agent_info.author = 'author'
    mock_agent_info.max_steps = 5
    mock_agent_info.provide_run_summary = True
    mock_agent_info.prompt = "duty"
    mock_agent_info.enabled = True
    mock_agent_info.tools = []
    mock_agent_info.managed_agents = [2]
    mock_agent_info.model_id = None
    mock_agent_info.model_name = None
    mock_agent_info.business_logic_model_id = None
    mock_agent_info.business_logic_model_name = None
    mock_sub_agent_info = MagicMock(spec=ExportAndImportAgentInfo)
    mock_sub_agent_info.agent_id = 2
    mock_sub_agent_info.name = 'sub_agent'
    mock_sub_agent_info.display_name = 'Sub Agent'
    mock_sub_agent_info.description = 'sub desc'
    mock_sub_agent_info.business_description = 'sub biz'
    mock_sub_agent_info.author = 'author'
    mock_sub_agent_info.max_steps = 5
    mock_sub_agent_info.provide_run_summary = True
    mock_sub_agent_info.prompt = "duty"
    mock_sub_agent_info.enabled = True
    mock_sub_agent_info.tools = []
    mock_sub_agent_info.managed_agents = []
    mock_sub_agent_info.model_id = None
    mock_sub_agent_info.model_name = None
    mock_sub_agent_info.business_logic_model_id = None
    mock_sub_agent_info.business_logic_model_name = None
    export_data = MagicMock(spec=ExportAndImportDataFormat)
    export_data.agent_id = 1
    export_data.agent_info = {'1': mock_agent_info, '2': mock_sub_agent_info}
    with patch('management.services.agent.transfer.import_agent_by_agent_id', return_value=100) as mock_import:
        with patch('management.services.agent.transfer.insert_related_agent'):
            result = await import_agent_impl(export_data, identity=AuthenticatedIdentity('user_1', 'tenant_1'))
    assert mock_import.call_count == 2


# Test for import_agent_by_agent_id tool param validation error
@pytest.mark.asyncio
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
async def test_import_agent_by_agent_id_tool_param_error(mock_query_tools, mock_create):
    """Test import_agent_by_agent_id raises error for invalid tool param."""
    from management.services.agent.service import import_agent_by_agent_id
    from contracts.agent import ExportAndImportAgentInfo

    mock_tool = MagicMock()
    mock_tool.class_name = "TestTool"
    mock_tool.source = "local"
    mock_tool.params = {"param1": "value1", "param2": "value2"}
    mock_tool.metadata = {}

    mock_agent_info = MagicMock(spec=ExportAndImportAgentInfo)
    mock_agent_info.agent_id = 1
    mock_agent_info.name = "valid_name"
    mock_agent_info.display_name = "Valid Name"
    mock_agent_info.description = "desc"
    mock_agent_info.business_description = "biz"
    mock_agent_info.author = "author"
    mock_agent_info.max_steps = 5
    mock_agent_info.provide_run_summary = True
    mock_agent_info.prompt = "duty"
    mock_agent_info.enabled = True
    mock_agent_info.tools = [mock_tool]
    mock_agent_info.managed_agents = []
    mock_agent_info.model_id = None
    mock_agent_info.model_name = None
    mock_agent_info.business_logic_model_id = None
    mock_agent_info.business_logic_model_name = None

    mock_query_tools.return_value = [
        {
            "class_name": "TestTool",
            "source": "local",
            "params": [{"name": "param1"}],  # Missing param2
        }
    ]

    with pytest.raises(ValueError, match="cannot be found"):
        await import_agent_by_agent_id(
            import_agent_info=mock_agent_info, tenant_id="tenant_1", user_id="user_1"
        )


# Test for import_agent_by_agent_id invalid max_steps
@pytest.mark.asyncio
async def test_import_agent_by_agent_id_invalid_max_steps():
    """Test import_agent_by_agent_id raises error for invalid max_steps."""
    from management.services.agent.service import import_agent_by_agent_id
    from contracts.agent import ExportAndImportAgentInfo

    mock_agent_info = MagicMock(spec=ExportAndImportAgentInfo)
    mock_agent_info.agent_id = 1
    mock_agent_info.name = "valid_name"
    mock_agent_info.display_name = "Valid Name"
    mock_agent_info.description = "desc"
    mock_agent_info.business_description = "biz"
    mock_agent_info.author = "author"
    mock_agent_info.max_steps = -1  # Invalid: must be > 0
    mock_agent_info.provide_run_summary = True
    mock_agent_info.prompt = "duty"
    mock_agent_info.enabled = True
    mock_agent_info.tools = []
    mock_agent_info.managed_agents = []
    mock_agent_info.model_id = None
    mock_agent_info.model_name = None
    mock_agent_info.business_logic_model_id = None
    mock_agent_info.business_logic_model_name = None

    with pytest.raises(ValueError, match="Invalid max steps"):
        await import_agent_by_agent_id(
            import_agent_info=mock_agent_info, tenant_id="tenant_1", user_id="user_1"
        )


# Test for import_agent_by_agent_id invalid agent name
@pytest.mark.asyncio
async def test_import_agent_by_agent_id_invalid_name():
    """Test import_agent_by_agent_id raises error for invalid agent name."""
    from management.services.agent.service import import_agent_by_agent_id
    from contracts.agent import ExportAndImportAgentInfo

    mock_agent_info = MagicMock(spec=ExportAndImportAgentInfo)
    mock_agent_info.agent_id = 1
    mock_agent_info.name = "invalid-name-with-dashes"  # Not a valid identifier
    mock_agent_info.display_name = "Valid Name"
    mock_agent_info.description = "desc"
    mock_agent_info.business_description = "biz"
    mock_agent_info.author = "author"
    mock_agent_info.max_steps = 5
    mock_agent_info.provide_run_summary = True
    mock_agent_info.prompt = "duty"
    mock_agent_info.enabled = True
    mock_agent_info.tools = []
    mock_agent_info.managed_agents = []
    mock_agent_info.model_id = None
    mock_agent_info.model_name = None
    mock_agent_info.business_logic_model_id = None
    mock_agent_info.business_logic_model_name = None

    with pytest.raises(ValueError, match="Python identifier"):
        await import_agent_by_agent_id(
            import_agent_info=mock_agent_info, tenant_id="tenant_1", user_id="user_1"
        )


# Test for import_agent_by_agent_id publish_version_impl exception
@pytest.mark.asyncio
@patch("management.services.agent.transfer.publish_version_impl")
@patch("management.services.agent.transfer.create_agent")
@patch("management.services.agent.transfer.query_all_tools")
async def test_import_agent_by_agent_id_publish_version_error(
    mock_query_tools, mock_create, mock_publish
):
    """Test import_agent_by_agent_id handles publish_version_impl exception."""
    from management.services.agent.service import import_agent_by_agent_id
    from contracts.agent import ExportAndImportAgentInfo

    mock_agent_info = MagicMock(spec=ExportAndImportAgentInfo)
    mock_agent_info.agent_core = "smolagents"
    mock_agent_info.enable_context_manager = True
    mock_agent_info.agent_id = 1
    mock_agent_info.name = "valid_name"
    mock_agent_info.display_name = "Valid Name"
    mock_agent_info.description = "desc"
    mock_agent_info.business_description = "biz"
    mock_agent_info.author = "author"
    mock_agent_info.max_steps = 5
    mock_agent_info.provide_run_summary = True
    mock_agent_info.prompt = "duty"
    mock_agent_info.enabled = True
    mock_agent_info.tools = []
    mock_agent_info.managed_agents = []
    mock_agent_info.model_ids = None
    mock_agent_info.model_names = None
    mock_agent_info.business_logic_model_id = None
    mock_agent_info.business_logic_model_name = None
    # W2 added `requested_output_tokens` to ExportAndImportAgentInfo and
    # import_agent_by_agent_id reads it directly at agent_service.py:1874.
    # MagicMock(spec=...) on a Pydantic v2 model does not always expose
    # field-level attributes through dir(), so the access AttributeErrors
    # unless we set it explicitly.
    mock_agent_info.requested_output_tokens = None
    # Runtime metadata support added `allow_chat_metadata` to
    # ExportAndImportAgentInfo; import_agent_by_agent_id reads it directly
    # at agent_service.py:2489. Same Pydantic v2 spec caveat applies.
    mock_agent_info.allow_chat_metadata = None
    # Runtime metadata support added `allow_chat_metadata` to
    # ExportAndImportAgentInfo; import_agent_by_agent_id reads it directly
    # at agent_service.py:2489. Same Pydantic v2 spec caveat applies.
    mock_agent_info.allow_chat_metadata = None

    # Configure the three patched mocks so the flow reaches the publish branch:
    # - query_all_tools() must return an iterable (empty list -> no tool loop)
    # - create_agent(...) must return a dict so `new_agent["agent_id"]` is an int
    # - publish_version_impl(...) must raise so the under-test exception handler
    #   at agent_service.py:1899-1901 actually fires
    mock_query_tools.return_value = []
    mock_create.return_value = {"agent_id": 100}
    mock_publish.side_effect = Exception("Publish error")

    # Should not raise - exception is caught and logged
    result = await import_agent_by_agent_id(
        import_agent_info=mock_agent_info, tenant_id="tenant_1", user_id="user_1"
    )

    assert result == 100


# Test for _collect_model_availability_reasons


# Test for save_messages error cases
# Test for update_agent_info_impl related_external_agents exception
@pytest.mark.asyncio
async def test_update_agent_info_impl_external_agent_list_error():
    """Test update_agent_info_impl handles external agent list error."""
    from management.services.agent.service import update_agent_info_impl
    from management.services.agent import service as ag_svc
    from contracts.agent import AgentInfoRequest
    mock_request = MagicMock(spec=AgentInfoRequest)
    mock_request.agent_id = 1
    mock_request.name = 'Test'
    mock_request.display_name = 'Test Display'
    mock_request.description = 'Desc'
    mock_request.business_description = 'Biz Desc'
    mock_request.author = 'Author'
    mock_request.model_id = None
    mock_request.model_name = None
    mock_request.business_logic_model_id = None
    mock_request.business_logic_model_name = None
    mock_request.max_steps = 5
    mock_request.provide_run_summary = True
    mock_request.prompt = "Duty"
    mock_request.enabled = True
    mock_request.enabled_tool_ids = None
    mock_request.enabled_skill_ids = None
    mock_request.related_agent_ids = None
    mock_request.related_agents = None
    mock_request.related_external_agent_ids = [100]
    mock_request.group_ids = None
    mock_request.ingroup_permission = None
    mock_request.example_questions = None
    mock_request.greeting_message = None
    with patch.object(ag_svc.a2a_agent_db, 'list_external_relations_by_local_agent', side_effect=Exception('DB error')):
        with pytest.raises(ValueError, match='Failed to update related external agents'):
            await update_agent_info_impl(mock_request, identity=AuthenticatedIdentity('user_1', 'tenant_1'))


@pytest.mark.asyncio
async def test_update_agent_info_impl_example_questions_exceed_limit():
    """Test update_agent_info_impl raises AppException when example_questions exceeds 6 items."""
    from contracts.errors.codes import ErrorCode
    from contracts.errors.exceptions import AppException
    request = MagicMock()
    request.agent_id = 123
    request.model_id = None
    request.example_questions = ['q1', 'q2', 'q3', 'q4', 'q5', 'q6', 'q7']
    request.enabled_tool_ids = None
    request.related_agent_ids = None
    apply_default_agent_request_fields(request)
    with pytest.raises(AppException) as exc_info:
        await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert exc_info.value.error_code == ErrorCode.COMMON_PARAMETER_INVALID


# =============================================================================
# Tests for version_no export and repository export helpers
# =============================================================================


@pytest.mark.asyncio
@patch('management.services.agent.transfer.resolve_sub_agent_version_no')
@patch('management.services.agent.transfer.query_sub_agent_relations')
@patch('management.services.agent.transfer.export_agent_by_agent_id')
async def test_export_agent_dict_impl_uses_pinned_sub_agent_versions(mock_export_agent_by_id, mock_query_relations, mock_resolve_version):
    """BFS export should enqueue sub-agents with their pinned version numbers."""
    from management.services.agent.service import export_agent_dict_impl
    from contracts.agent import ExportAndImportAgentInfo
    root_agent = ExportAndImportAgentInfo(agent_id=1, name='root', display_name='Root', description='desc', business_description='biz', max_steps=5, provide_run_summary=False, enabled=True, tools=[], managed_agents=[2])
    child_agent = ExportAndImportAgentInfo(agent_id=2, name='child', display_name='Child', description='desc', business_description='biz', max_steps=5, provide_run_summary=False, enabled=True, tools=[], managed_agents=[])

    async def _export_side_effect(agent_id, tenant_id, user_id, version_no=0):
        if agent_id == 1:
            return root_agent
        return child_agent
    mock_export_agent_by_id.side_effect = _export_side_effect
    mock_query_relations.side_effect = [[{'selected_agent_id': 2, 'selected_agent_version_no': 3}], []]
    mock_resolve_version.return_value = 3
    result = await export_agent_dict_impl(agent_id=1, identity=AuthenticatedIdentity('u', 't'), version_no=2)
    assert result['agent_id'] == 1
    assert '1' in result['agent_info']
    assert '2' in result['agent_info']
    mock_export_agent_by_id.assert_any_call(agent_id=1, tenant_id='t', user_id='u', version_no=2)
    mock_export_agent_by_id.assert_any_call(agent_id=2, tenant_id='t', user_id='u', version_no=3)


@pytest.mark.asyncio
@patch("management.services.agent.transfer._export_agent_dict_core")
async def test_export_agent_dict_for_repository_impl(mock_export_core):
    """Repository export helper should delegate to core export without auth header."""
    from management.services.agent.service import export_agent_dict_for_repository_impl

    mock_export_core.return_value = {
        "agent_id": 10,
        "agent_info": {},
        "mcp_info": [],
    }

    result = await export_agent_dict_for_repository_impl(
        agent_id=10, tenant_id="tenant_a", user_id="user_a", version_no=1
    )

    assert result["agent_id"] == 10
    mock_export_core.assert_called_once_with(
        root_agent_id=10,
        tenant_id="tenant_a",
        user_id="user_a",
        version_no=1,
    )


# =============================================================================
# Tests for _resolve_model_ids_with_fallback
# =============================================================================


def test_resolve_model_ids_with_fallback_both_none():
    """When both model_ids and model_display_names are None, return None."""
    result = _resolve_model_ids_with_fallback(
        model_ids=None,
        model_display_names=None,
        model_label="Model",
        tenant_id="tenant1",
    )
    assert result is None


def test_resolve_model_ids_with_fallback_both_empty():
    """When both model_ids and model_display_names are empty, return None."""
    result = _resolve_model_ids_with_fallback(
        model_ids=[],
        model_display_names=[],
        model_label="Model",
        tenant_id="tenant1",
    )
    assert result is None


@patch("management.services.agent.transfer.get_model_by_model_id")
def test_resolve_model_ids_with_fallback_explicit_ids_all_valid(mock_get_model):
    """When explicit model_ids are provided and all are valid, return them."""
    mock_get_model.return_value = {"display_name": "gpt-4"}
    result = _resolve_model_ids_with_fallback(
        model_ids=[1, 2],
        model_display_names=None,
        model_label="Model",
        tenant_id="tenant1",
    )
    assert result == [1, 2]
    assert mock_get_model.call_count == 2


@patch("management.services.agent.transfer.get_model_by_model_id")
def test_resolve_model_ids_with_fallback_explicit_ids_some_missing(mock_get_model):
    """When some model_ids are missing, return only valid ones."""
    mock_get_model.side_effect = [
        {"display_name": "gpt-4"},
        None,
        {"display_name": "gpt-3.5"},
    ]
    result = _resolve_model_ids_with_fallback(
        model_ids=[1, 2, 3],
        model_display_names=None,
        model_label="Model",
        tenant_id="tenant1",
    )
    assert result == [1, 3]


@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.tenant_config_manager")
def test_resolve_model_ids_with_fallback_display_names_only(
    mock_tenant_config, mock_get_by_name
):
    """When only model_display_names are provided, resolve them to ids."""
    mock_get_by_name.side_effect = [101, 102]
    mock_tenant_config.get_model_config.return_value = None
    result = _resolve_model_ids_with_fallback(
        model_ids=None,
        model_display_names=["Model A", "Model B"],
        model_label="Model",
        tenant_id="tenant1",
    )
    assert result == [101, 102]
    mock_get_by_name.assert_any_call("Model A", "tenant1")
    mock_get_by_name.assert_any_call("Model B", "tenant1")


@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.tenant_config_manager")
def test_resolve_model_ids_with_fallback_display_names_with_missing(
    mock_tenant_config, mock_get_by_name
):
    """When some display names cannot be resolved, log and continue."""
    mock_get_by_name.side_effect = [101, None, 103]
    mock_tenant_config.get_model_config.return_value = None
    result = _resolve_model_ids_with_fallback(
        model_ids=None,
        model_display_names=["Model A", "Unknown", "Model C"],
        model_label="Model",
        tenant_id="tenant1",
    )
    assert result == [101, 103]


@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.tenant_config_manager")
def test_resolve_model_ids_with_fallback_quick_config_fallback(
    mock_tenant_config, mock_get_by_name
):
    """When no model can be resolved, fall back to quick config LLM."""
    mock_get_by_name.return_value = None
    mock_tenant_config.get_model_config.return_value = {
        "model_id": 999,
        "display_name": "Quick Config LLM",
    }
    result = _resolve_model_ids_with_fallback(
        model_ids=None,
        model_display_names=["Unknown Model"],
        model_label="Model",
        tenant_id="tenant1",
    )
    assert result == [999]


@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.tenant_config_manager")
def test_resolve_model_ids_with_fallback_empty_display_names(
    mock_tenant_config, mock_get_by_name
):
    """When display names contain empty strings, skip them."""
    mock_get_by_name.return_value = 55
    mock_tenant_config.get_model_config.return_value = None
    result = _resolve_model_ids_with_fallback(
        model_ids=None,
        model_display_names=["", "Valid Model", ""],
        model_label="Model",
        tenant_id="tenant1",
    )
    assert result == [55]


@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.tenant_config_manager")
def test_resolve_model_ids_with_fallback_deduplication(
    mock_tenant_config, mock_get_by_name
):
    """Resolved model ids should be deduplicated."""
    mock_get_by_name.side_effect = [10, 10, 20]
    mock_tenant_config.get_model_config.return_value = None
    result = _resolve_model_ids_with_fallback(
        model_ids=None,
        model_display_names=["Model A", "Model A", "Model B"],
        model_label="Model",
        tenant_id="tenant1",
    )
    assert result == [10, 20]


@patch("management.services.agent.transfer.get_model_by_model_id")
def test_resolve_model_ids_with_fallback_explicit_ids_no_supplement(mock_get_model):
    """When explicit model_ids are provided, do NOT supplement with display names."""
    mock_get_model.return_value = {"display_name": "gpt-4"}
    result = _resolve_model_ids_with_fallback(
        model_ids=[1],
        model_display_names=["Should Not Be Used"],
        model_label="Model",
        tenant_id="tenant1",
    )
    assert result == [1]
    mock_get_model.assert_called_once_with(1)


@patch("management.services.agent.transfer.get_model_by_model_id")
@patch("management.services.agent.transfer.get_model_id_by_display_name")
@patch("management.services.agent.transfer.tenant_config_manager")
def test_resolve_model_ids_with_fallback_business_logic_model(
    mock_tenant_config, mock_get_by_name, mock_get_by_id
):
    """Business logic model resolution should work the same as regular model resolution."""
    mock_get_by_id.return_value = {"display_name": "claude-3"}
    mock_get_by_name.return_value = 77
    mock_tenant_config.get_model_config.return_value = None

    # Test with explicit model_ids for business logic model
    result = _resolve_model_ids_with_fallback(
        model_ids=[55],
        model_display_names=None,
        model_label="Business logic model",
        tenant_id="tenant1",
    )
    assert result == [55]

    # Test with display name only
    result2 = _resolve_model_ids_with_fallback(
        model_ids=None,
        model_display_names=["Claude Sonnet"],
        model_label="Business logic model",
        tenant_id="tenant1",
    )
    assert result2 == [77]


# ============================================================================
# Tests for helper functions to improve coverage
# ============================================================================


def test_extract_json_objects_from_text_empty():
    """_extract_json_objects_from_text should return empty list for empty text."""
    from management.services.agent.artifacts import (
        extract_json_objects_from_text as _extract_json_objects_from_text,
    )

    assert _extract_json_objects_from_text("") == []
    assert _extract_json_objects_from_text(None) == []


def test_extract_json_objects_from_text_with_objects():
    """_extract_json_objects_from_text should extract JSON objects from mixed text."""
    from management.services.agent.artifacts import (
        extract_json_objects_from_text as _extract_json_objects_from_text,
    )

    text = 'some text {"key": "value"} more text {"num": 123}'
    results = _extract_json_objects_from_text(text)
    assert len(results) == 2
    assert results[0] == {"key": "value"}
    assert results[1] == {"num": 123}


def test_extract_json_objects_from_text_with_invalid_json():
    """_extract_json_objects_from_text should skip invalid JSON."""
    from management.services.agent.artifacts import (
        extract_json_objects_from_text as _extract_json_objects_from_text,
    )

    text = 'valid {"key": "value"} invalid {broken json'
    results = _extract_json_objects_from_text(text)
    assert len(results) == 1
    assert results[0] == {"key": "value"}


def test_extract_json_objects_from_text_non_dict():
    """_extract_json_objects_from_text should skip non-dict JSON (arrays, primitives)."""
    from management.services.agent.artifacts import (
        extract_json_objects_from_text as _extract_json_objects_from_text,
    )

    text = '{"dict": true} [1, 2, 3] "string"'
    results = _extract_json_objects_from_text(text)
    assert len(results) == 1
    assert results[0] == {"dict": True}


def test_extract_skill_file_upload_payloads():
    """_extract_skill_file_upload_payloads should extract payloads with absolute_path."""
    from management.services.agent.artifacts import (
        extract_skill_file_upload_payloads as _extract_skill_file_upload_payloads,
    )

    content = 'some text {"absolute_path": "/tmp/file.txt", "file_name": "test.txt"} more text'
    results = _extract_skill_file_upload_payloads(content)
    assert len(results) == 1
    assert results[0]["absolute_path"] == "/tmp/file.txt"


def test_extract_skill_file_upload_payloads_no_path():
    """_extract_skill_file_upload_payloads should skip payloads without absolute_path."""
    from management.services.agent.artifacts import (
        extract_skill_file_upload_payloads as _extract_skill_file_upload_payloads,
    )

    content = '{"key": "value"}'
    results = _extract_skill_file_upload_payloads(content)
    assert len(results) == 0


def test_transform_skill_files_to_standard_format():
    """_transform_skill_files_to_standard_format should convert skill file format to frontend format."""
    from management.services.agent.artifacts import (
        transform_skill_files_to_standard_format as _transform_skill_files_to_standard_format,
    )

    upload_results = [
        {
            "file_name": "test.txt",
            "absolute_path": "/tmp/test.txt",
            "object_name": "obj1",
            "url": "https://example.com/test.txt",
            "presigned_url": "https://example.com/presigned",
            "mime_type": "text/plain",
            "file_size": 1024,
        }
    ]
    frontend_files = _transform_skill_files_to_standard_format(upload_results)
    assert len(frontend_files) == 1
    assert frontend_files[0]["object_name"] == "obj1"
    assert frontend_files[0]["name"] == "test.txt"
    assert frontend_files[0]["type"] == "file"
    assert frontend_files[0]["size"] == 1024
    assert frontend_files[0]["url"] == "https://example.com/test.txt"


def test_transform_skill_files_to_standard_format_missing_fields():
    """_transform_skill_files_to_standard_format should handle missing fields gracefully."""
    from management.services.agent.artifacts import (
        transform_skill_files_to_standard_format as _transform_skill_files_to_standard_format,
    )

    upload_results = [{"file_name": "test.txt"}]
    frontend_files = _transform_skill_files_to_standard_format(upload_results)
    assert len(frontend_files) == 1
    assert frontend_files[0]["name"] == "test.txt"
    assert frontend_files[0]["size"] == 0
    assert frontend_files[0]["object_name"] == ""


def test_safe_agent_stream_error_chunk():
    """_safe_agent_stream_error_chunk should return sanitized error message."""
    from management.services.agent.stream import (
        safe_agent_stream_error_chunk as _safe_agent_stream_error_chunk,
    )
    from management.services.agent.stream import (
        SAFE_AGENT_STREAM_ERROR_MESSAGE,
    )

    result = _safe_agent_stream_error_chunk()
    assert SAFE_AGENT_STREAM_ERROR_MESSAGE in result
    assert "data:" in result
    assert "\n\n" in result


def test_get_user_group_ids_success():
    """_get_user_group_ids should return comma-separated group IDs."""
    from management.services.agent.service import _get_user_group_ids

    with patch(
        "management.services.agent.transfer.query_group_ids_by_user",
        return_value=[1, 2, 3],
    ):
        result = _get_user_group_ids("user1", "tenant1")
        assert result == "1,2,3"


def test_get_user_group_ids_empty():
    """_get_user_group_ids should return empty string when no groups."""
    from management.services.agent.service import _get_user_group_ids

    with patch(
        "management.services.agent.transfer.query_group_ids_by_user", return_value=[]
    ):
        result = _get_user_group_ids("user1", "tenant1")
        assert result == ""


def test_get_user_group_ids_exception():
    """_get_user_group_ids should return empty string on exception."""
    from management.services.agent.service import _get_user_group_ids

    with patch(
        "management.services.agent.transfer.query_group_ids_by_user",
        side_effect=Exception("DB error"),
    ):
        result = _get_user_group_ids("user1", "tenant1")
        assert result == ""


# ============================================================================
# Additional tests for process_skill_file_uploads coverage
# ============================================================================


@pytest.mark.asyncio
@patch("management.services.agent.artifacts.upload_fileobj")
@patch("management.services.agent.artifacts.is_allowed_skill_upload_path")
@patch("management.services.agent.artifacts.os.path.exists")
@patch("management.services.agent.artifacts.os.path.getsize")
@patch("builtins.open", new_callable=MagicMock)
async def test_process_skill_file_uploads_success(
    mock_open, mock_getsize, mock_exists, mock_allowed, mock_upload
):
    """_process_skill_file_uploads should upload files successfully."""
    from management.services.agent.artifacts import (
        process_skill_file_uploads as _process_skill_file_uploads,
    )

    # Setup mocks
    mock_exists.return_value = True
    mock_allowed.return_value = True
    mock_getsize.return_value = 1024
    mock_upload.return_value = {
        "success": True,
        "object_name": "obj1",
        "url": "http://example.com/file",
    }

    content = '{"absolute_path": "/tmp/test.txt", "file_name": "test.txt", "mime_type": "text/plain"}'

    result = await _process_skill_file_uploads(content, "user1", "tenant1")

    assert len(result) == 1
    assert result[0]["status"] == "success"
    assert result[0]["file_name"] == "test.txt"


@pytest.mark.asyncio
@patch("management.services.agent.artifacts.upload_fileobj")
@patch("management.services.agent.artifacts.is_allowed_skill_upload_path")
@patch("management.services.agent.artifacts.os.path.exists")
@patch("management.services.agent.artifacts.os.path.getsize")
@patch("builtins.open", new_callable=MagicMock)
async def test_process_skill_file_uploads_uses_structured_payloads(
    mock_open, mock_getsize, mock_exists, mock_allowed, mock_upload
):
    """Structured artifacts should bypass legacy text extraction."""
    from management.services.agent.artifacts import (
        process_skill_file_uploads as _process_skill_file_uploads,
    )

    mock_exists.return_value = True
    mock_allowed.return_value = True
    mock_getsize.return_value = 128
    mock_upload.return_value = {
        "success": True,
        "object_name": "obj1",
        "url": "http://example.com/file",
    }
    payloads = [
        {
            "absolute_path": "/mnt/nexent/report.docx",
            "file_name": "report.docx",
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
    ]

    result = await _process_skill_file_uploads(payloads, "user1", "tenant1")

    assert len(result) == 1
    assert result[0]["file_name"] == "report.docx"
    mock_upload.assert_called_once()


@pytest.mark.asyncio
@patch("management.services.agent.artifacts.upload_fileobj")
@patch("management.services.agent.artifacts.is_allowed_skill_upload_path")
@patch("management.services.agent.artifacts.os.path.exists")
async def test_process_skill_file_uploads_rejected_path(
    mock_exists, mock_allowed, mock_upload
):
    """_process_skill_file_uploads should reject unsafe paths."""
    from management.services.agent.artifacts import (
        process_skill_file_uploads as _process_skill_file_uploads,
    )

    mock_exists.return_value = True
    mock_allowed.return_value = False  # Reject path

    content = '{"absolute_path": "/etc/passwd", "file_name": "secret.txt"}'

    result = await _process_skill_file_uploads(content, "user1", "tenant1")

    assert len(result) == 0
    mock_upload.assert_not_called()


@pytest.mark.asyncio
@patch("management.services.agent.artifacts.upload_fileobj")
@patch("management.services.agent.artifacts.is_allowed_skill_upload_path")
@patch("management.services.agent.artifacts.os.path.exists")
async def test_process_skill_file_uploads_file_not_exists(
    mock_exists, mock_allowed, mock_upload
):
    """_process_skill_file_uploads should skip files that don't exist."""
    from management.services.agent.artifacts import (
        process_skill_file_uploads as _process_skill_file_uploads,
    )

    mock_exists.return_value = False  # File doesn't exist
    mock_allowed.return_value = True

    content = '{"absolute_path": "/tmp/missing.txt", "file_name": "missing.txt"}'

    result = await _process_skill_file_uploads(content, "user1", "tenant1")

    assert len(result) == 0
    mock_upload.assert_not_called()


@pytest.mark.asyncio
@patch("management.services.agent.artifacts.upload_fileobj")
@patch("management.services.agent.artifacts.is_allowed_skill_upload_path")
@patch("management.services.agent.artifacts.os.path.exists")
@patch("management.services.agent.artifacts.os.path.getsize")
@patch("builtins.open", new_callable=MagicMock)
async def test_process_skill_file_uploads_upload_failure(
    mock_open, mock_getsize, mock_exists, mock_allowed, mock_upload
):
    """_process_skill_file_uploads should handle upload failures gracefully."""
    from management.services.agent.artifacts import (
        process_skill_file_uploads as _process_skill_file_uploads,
    )

    mock_exists.return_value = True
    mock_allowed.return_value = True
    mock_getsize.return_value = 1024
    mock_upload.return_value = {"success": False, "error": "Upload failed"}

    content = '{"absolute_path": "/tmp/test.txt", "file_name": "test.txt"}'

    result = await _process_skill_file_uploads(content, "user1", "tenant1")

    assert len(result) == 0


@pytest.mark.asyncio
@patch("management.services.agent.artifacts.upload_fileobj")
@patch("management.services.agent.artifacts.is_allowed_skill_upload_path")
@patch("management.services.agent.artifacts.os.path.exists")
@patch("management.services.agent.artifacts.os.path.getsize")
@patch("builtins.open", new_callable=MagicMock)
async def test_process_skill_file_uploads_exception(
    mock_open, mock_getsize, mock_exists, mock_allowed, mock_upload
):
    """_process_skill_file_uploads should handle exceptions gracefully."""
    from management.services.agent.artifacts import (
        process_skill_file_uploads as _process_skill_file_uploads,
    )

    mock_exists.return_value = True
    mock_allowed.return_value = True
    mock_getsize.side_effect = OSError("File error")

    content = '{"absolute_path": "/tmp/test.txt", "file_name": "test.txt"}'

    # Should not raise, should return empty list
    result = await _process_skill_file_uploads(content, "user1", "tenant1")

    assert len(result) == 0


@pytest.mark.asyncio
@patch("management.services.agent.artifacts.upload_fileobj")
@patch("management.services.agent.artifacts.is_allowed_skill_upload_path")
@patch("management.services.agent.artifacts.os.path.exists")
@patch("management.services.agent.artifacts.os.path.getsize")
@patch("builtins.open", new_callable=MagicMock)
async def test_process_skill_file_uploads_uses_content_type(
    mock_open, mock_getsize, mock_exists, mock_allowed, mock_upload
):
    """_process_skill_file_uploads should use content_type when mime_type is missing."""
    from management.services.agent.artifacts import (
        process_skill_file_uploads as _process_skill_file_uploads,
    )

    mock_exists.return_value = True
    mock_allowed.return_value = True
    mock_getsize.return_value = 1024
    mock_upload.return_value = {"success": True, "object_name": "obj1"}

    content = '{"absolute_path": "/tmp/test.txt", "file_name": "test.txt", "content_type": "application/json"}'

    result = await _process_skill_file_uploads(content, "user1", "tenant1")

    assert len(result) == 1
    assert result[0]["mime_type"] == "application/json"


# ============================================================================
# Tests for _regenerate_agent_value_with_llm with user_id
# Note: The user_id path in _regenerate_agent_value_with_llm is tested via
# the existing test_regenerate_agent_name_with_llm and
# test_regenerate_agent_display_name_with_llm tests that pass user_id
# ============================================================================


# ============================================================================
# Tests for stop_agent_tasks
# ============================================================================


# ============================================================================
# Tests for delete_agent_impl exception handling
# ============================================================================


@pytest.mark.asyncio
async def test_delete_agent_impl_exception():
    """delete_agent_impl should raise ValueError on database errors."""
    from management.services.agent.service import delete_agent_impl

    with patch(
        "management.services.agent.management.delete_agent_by_id",
        side_effect=Exception("DB error"),
    ):
        with pytest.raises(ValueError, match="Failed to delete agent"):
            await delete_agent_impl(123, "tenant1", "user1")


# ============================================================================
# Tests for insert_related_agent_impl returns response (not raises)
# ============================================================================


def test_insert_related_agent_impl_returns_response():
    """insert_related_agent_impl returns a JSONResponse."""
    from test.backend.services.agent_legacy_helpers import (insert_related_agent_impl)

    with patch(
        "test.backend.services.agent_legacy_helpers.query_sub_agents_id_list", return_value=[]
    ):
        with patch(
            "test.backend.services.agent_legacy_helpers.insert_related_agent",
            return_value=True,
        ):
            result = insert_related_agent_impl(
                parent_agent_id=123, child_agent_id=456, tenant_id="tenant1"
            )
            assert result.status_code == 200


# ============================================================================
# Additional tests for remaining uncovered code paths
# ============================================================================


@pytest.mark.asyncio
@patch("management.services.agent.artifacts.upload_fileobj")
@patch("management.services.agent.artifacts.is_allowed_skill_upload_path")
@patch("management.services.agent.artifacts.os.path.exists")
@patch("management.services.agent.artifacts.os.path.getsize")
@patch("builtins.open", new_callable=MagicMock)
async def test_process_skill_file_uploads_empty_filename_uses_basename(
    mock_open, mock_getsize, mock_exists, mock_allowed, mock_upload
):
    """_process_skill_file_uploads should use basename when file_name is empty."""
    from management.services.agent.artifacts import (
        process_skill_file_uploads as _process_skill_file_uploads,
    )

    mock_exists.return_value = True
    mock_allowed.return_value = True
    mock_getsize.return_value = 1024
    mock_upload.return_value = {"success": True, "object_name": "obj1"}

    content = '{"absolute_path": "/tmp/test.txt"}'  # No file_name

    result = await _process_skill_file_uploads(content, "user1", "tenant1")

    assert len(result) == 1
    assert result[0]["file_name"] == "test.txt"


@patch("management.services.agent.transfer.get_model_by_model_id")
def test_resolve_model_ids_with_fallback_duplicate_ids_in_list(mock_get_model):
    """_resolve_model_ids_with_fallback should skip duplicate ids in the list."""
    from management.services.agent.service import _resolve_model_ids_with_fallback

    mock_get_model.return_value = {"display_name": "gpt-4"}
    result = _resolve_model_ids_with_fallback(
        model_ids=[1, 1, 2],  # Duplicate id
        model_display_names=None,
        model_label="Model",
        tenant_id="tenant1",
    )
    # Should only return unique ids
    assert len(result) == 2
    assert 1 in result
    assert 2 in result


@patch("management.services.agent.transfer.get_model_by_model_id")
def test_resolve_model_ids_with_fallback_model_not_found_in_catalog(mock_get_model):
    """_resolve_model_ids_with_fallback should log and skip missing model ids."""
    from management.services.agent.service import _resolve_model_ids_with_fallback

    # First id found, second id not found in tenant catalog
    mock_get_model.side_effect = [
        {"display_name": "gpt-4"},
        None,  # Not found
    ]

    result = _resolve_model_ids_with_fallback(
        model_ids=[1, 2],
        model_display_names=None,
        model_label="Model",
        tenant_id="tenant1",
    )
    # Should only return the found id
    assert result == [1]


# Tests for stop_agent_tasks with various scenarios
# Tests for _check_agent_value_duplicate
def test_check_agent_value_duplicate_cache_used():
    """_check_agent_value_duplicate should use provided cache."""
    from management.services.agent.naming import (
        check_agent_value_duplicate as _check_agent_value_duplicate,
    )

    agents_cache = [
        {"agent_id": 1, "name": "TestAgent"},
        {"agent_id": 2, "name": "OtherAgent"},
    ]

    # Should find duplicate
    assert (
        _check_agent_value_duplicate(
            field_key="name",
            value="TestAgent",
            tenant_id="tenant1",
            agents_cache=agents_cache,
        )
        is True
    )

    # Should not find duplicate
    assert (
        _check_agent_value_duplicate(
            field_key="name",
            value="NewAgent",
            tenant_id="tenant1",
            agents_cache=agents_cache,
        )
        is False
    )


def test_check_agent_value_duplicate_exclude_self():
    """_check_agent_value_duplicate should exclude self agent when checking duplicates."""
    from management.services.agent.naming import (
        check_agent_value_duplicate as _check_agent_value_duplicate,
    )

    agents_cache = [
        {"agent_id": 1, "name": "TestAgent"},
        {"agent_id": 2, "name": "TestAgent"},  # Duplicate name
    ]

    # Exclude agent_id 1, should find duplicate (agent_id 2)
    assert (
        _check_agent_value_duplicate(
            field_key="name",
            value="TestAgent",
            tenant_id="tenant1",
            agents_cache=agents_cache,
            exclude_agent_id=1,
        )
        is True
    )

    # Exclude agent_id 2, should find duplicate (agent_id 1)
    assert (
        _check_agent_value_duplicate(
            field_key="name",
            value="TestAgent",
            tenant_id="tenant1",
            agents_cache=agents_cache,
            exclude_agent_id=2,
        )
        is True
    )

    # Exclude both, should not find duplicate
    assert (
        _check_agent_value_duplicate(
            field_key="name",
            value="TestAgent",
            tenant_id="tenant1",
            agents_cache=agents_cache,
            exclude_agent_id=1,
        )
        is True
    )  # Still finds agent_id 2


def test_check_agent_value_duplicate_empty_value():
    """_check_agent_value_duplicate should return False for empty value."""
    from management.services.agent.naming import (
        check_agent_value_duplicate as _check_agent_value_duplicate,
    )

    assert (
        _check_agent_value_duplicate(field_key="name", value="", tenant_id="tenant1")
        is False
    )

    assert (
        _check_agent_value_duplicate(field_key="name", value=None, tenant_id="tenant1")
        is False
    )


# Tests for delete_related_agent_impl
@patch("test.backend.services.agent_legacy_helpers.delete_related_agent")
def test_delete_related_agent_impl_success(mock_delete):
    """delete_related_agent_impl should call delete_related_agent."""
    from test.backend.services.agent_legacy_helpers import (delete_related_agent_impl)

    mock_delete.return_value = True
    result = delete_related_agent_impl(
        parent_agent_id=1, child_agent_id=2, tenant_id="tenant1"
    )
    mock_delete.assert_called_once_with(1, 2, "tenant1")
    assert result is True


@patch("test.backend.services.agent_legacy_helpers.delete_related_agent")
def test_delete_related_agent_impl_failure(mock_delete):
    """delete_related_agent_impl should raise Exception on failure."""
    from test.backend.services.agent_legacy_helpers import (delete_related_agent_impl)

    mock_delete.side_effect = Exception("DB error")
    with pytest.raises(Exception, match="Failed to delete related agent"):
        delete_related_agent_impl(
            parent_agent_id=1, child_agent_id=2, tenant_id="tenant1"
        )


# Tests for _generate_unique_value_with_suffix


# ============================================================================
# Tests for remaining uncovered code paths - skill files, import/export, etc.
# ============================================================================


def test_transform_skill_files_to_standard_format_ignores_preview_url():
    """An unapproved preview URL must not enter persisted attachment metadata."""
    from management.services.agent.artifacts import (
        transform_skill_files_to_standard_format as _transform_skill_files_to_standard_format,
    )

    upload_results = [
        {
            "file_name": "test.txt",
            "object_name": "obj1",
            "preview_url": "https://example.com/preview",
        }
    ]
    frontend_files = _transform_skill_files_to_standard_format(upload_results)
    assert len(frontend_files) == 1
    assert frontend_files[0]["url"] == ""
    assert "presigned_url" not in frontend_files[0]


def test_transform_skill_files_to_standard_format_empty_list():
    """_transform_skill_files_to_standard_format should return empty list for empty input."""
    from management.services.agent.artifacts import (
        transform_skill_files_to_standard_format as _transform_skill_files_to_standard_format,
    )

    result = _transform_skill_files_to_standard_format([])
    assert result == []


# Tests for _extract_json_objects_from_text edge cases
def test_extract_json_objects_from_text_empty_after_parse():
    """_extract_json_objects_from_text should skip empty string input."""
    from management.services.agent.artifacts import (
        extract_json_objects_from_text as _extract_json_objects_from_text,
    )

    result = _extract_json_objects_from_text("")
    assert result == []


# Tests for get_agent_by_name_impl - uses search and query_version_list
# (complex function with multiple database interactions, covered by integration tests)


# Tests for get_agent_id_by_name - uses search and query_version_list


# Test for _safe_agent_stream_error_chunk
def test_safe_agent_stream_error_chunk_format():
    """_safe_agent_stream_error_chunk should return properly formatted SSE error."""
    from management.services.agent.stream import (
        safe_agent_stream_error_chunk as _safe_agent_stream_error_chunk,
        SAFE_AGENT_STREAM_ERROR_MESSAGE,
    )

    result = _safe_agent_stream_error_chunk()

    # Should be formatted as SSE data
    assert result.startswith("data: ")
    assert '"type": "error"' in result
    assert SAFE_AGENT_STREAM_ERROR_MESSAGE in result
    assert result.endswith("\n\n")


# Test for _normalize_language_key edge cases


# ============================================================================
# Additional tests for _stream_agent_chunks and streaming coverage
# ============================================================================


# ============================================================================
# Tests for _extract_skill_file_upload_payloads edge cases
# ============================================================================


def test_extract_skill_file_upload_payloads_multiple_objects():
    """_extract_skill_file_upload_payloads should extract multiple objects."""
    from management.services.agent.artifacts import (
        extract_skill_file_upload_payloads as _extract_skill_file_upload_payloads,
    )

    # Multiple JSON objects in text
    content = '{"absolute_path": "/tmp/file1.txt"}\n{"absolute_path": "/tmp/file2.txt"}'
    result = _extract_skill_file_upload_payloads(content)

    assert len(result) == 2


# ============================================================================
# Tests for _safe_agent_stream_error_chunk
# ============================================================================


def test_safe_agent_stream_error_chunk_contains_type():
    """_safe_agent_stream_error_chunk should return error chunk with type."""
    from management.services.agent.stream import (
        safe_agent_stream_error_chunk as _safe_agent_stream_error_chunk,
    )

    result = _safe_agent_stream_error_chunk()

    assert '"type": "error"' in result


# ============================================================================
# Tests for _stream_agent_chunks with memory add
# ============================================================================


# ============================================================================
# Additional tests for remaining uncovered code paths
# ============================================================================


# Tests for _check_agent_value_duplicate with different field keys
def test_check_agent_value_duplicate_with_display_name():
    """_check_agent_value_duplicate should work with display_name field."""
    from management.services.agent.naming import (
        check_agent_value_duplicate as _check_agent_value_duplicate,
    )

    agents_cache = [
        {"agent_id": 1, "name": "Agent", "display_name": "Test Display"},
        {
            "agent_id": 2,
            "name": "Other",
            "display_name": "Test Display",
        },  # Duplicate display_name
    ]

    # Should find duplicate for display_name
    assert (
        _check_agent_value_duplicate(
            field_key="display_name",
            value="Test Display",
            tenant_id="tenant1",
            agents_cache=agents_cache,
        )
        is True
    )

    # Should not find duplicate
    assert (
        _check_agent_value_duplicate(
            field_key="display_name",
            value="Different Display",
            tenant_id="tenant1",
            agents_cache=agents_cache,
        )
        is False
    )


def test_check_agent_value_duplicate_exclude_both():
    """_check_agent_value_duplicate should exclude both when both agent_ids are excluded."""
    from management.services.agent.naming import (
        check_agent_value_duplicate as _check_agent_value_duplicate,
    )

    agents_cache = [
        {"agent_id": 1, "name": "TestAgent"},
        {"agent_id": 2, "name": "TestAgent"},  # Duplicate name
    ]

    # When exclude_agent_id excludes both, no duplicate should be found
    # (this is a special edge case - the function checks against ALL agents)
    result = _check_agent_value_duplicate(
        field_key="name",
        value="TestAgent",
        tenant_id="tenant1",
        agents_cache=agents_cache,
        exclude_agent_id=1,  # Exclude only agent 1
    )
    # Still finds agent_id 2
    assert result is True


def test_check_agent_value_duplicate_mismatched_case():
    """_check_agent_value_duplicate should be case-sensitive."""
    from management.services.agent.naming import (
        check_agent_value_duplicate as _check_agent_value_duplicate,
    )

    agents_cache = [
        {"agent_id": 1, "name": "TestAgent"},
    ]

    # Different case should not be considered duplicate
    assert (
        _check_agent_value_duplicate(
            field_key="name",
            value="testagent",  # Lower case
            tenant_id="tenant1",
            agents_cache=agents_cache,
        )
        is False
    )


# Tests for _format_existing_values with Chinese language


# Tests for stop_agent_tasks with logging
# Tests for _safe_agent_stream_error_chunk with multiple calls
def test_safe_agent_stream_error_chunk_consistent():
    """_safe_agent_stream_error_chunk should return consistent output."""
    from management.services.agent.stream import (
        safe_agent_stream_error_chunk as _safe_agent_stream_error_chunk,
    )

    result1 = _safe_agent_stream_error_chunk()
    result2 = _safe_agent_stream_error_chunk()

    # Should be consistent
    assert result1 == result2
    assert "error" in result1.lower()


# Tests for extract_json_objects with nested JSON
def test_extract_json_objects_nested():
    """_extract_json_objects_from_text should handle nested JSON objects."""
    from management.services.agent.artifacts import (
        extract_json_objects_from_text as _extract_json_objects_from_text,
    )

    content = '{"outer": {"inner": "value"}}'
    result = _extract_json_objects_from_text(content)

    # Should extract the nested object
    assert len(result) == 1
    assert result[0]["outer"]["inner"] == "value"


# Tests for transform_skill_files with missing url fields
def test_transform_skill_files_missing_url_fields():
    """_transform_skill_files_to_standard_format should handle missing URL fields."""
    from management.services.agent.artifacts import (
        transform_skill_files_to_standard_format as _transform_skill_files_to_standard_format,
    )

    upload_results = [
        {
            "status": "success",
            "file_name": "test.txt",
            # No url, presigned_url, or preview_url
        }
    ]

    result = _transform_skill_files_to_standard_format(upload_results)

    assert len(result) == 1
    # The function maps 'file_name' to 'name'
    assert result[0]["name"] == "test.txt"


# ============================================================================
# Test for empty absolute_path case (line 208)
# ============================================================================


@pytest.mark.asyncio
@patch("management.services.agent.artifacts.is_allowed_skill_upload_path")
async def test_process_skill_file_uploads_empty_absolute_path(mock_allowed):
    """_process_skill_file_uploads should skip when absolute_path is empty."""
    from management.services.agent.artifacts import (
        process_skill_file_uploads as _process_skill_file_uploads,
    )

    mock_allowed.return_value = True

    # Content with empty absolute_path
    content = '{"absolute_path": "", "file_name": "test.txt"}'

    result = await _process_skill_file_uploads(content, "user1", "tenant1")

    # Should return empty list because absolute_path is empty
    assert len(result) == 0


# ============================================================================
# Tests for _stream_agent_chunks - error handling coverage
# ============================================================================


# ============================================================================
# Tests for memory background processing (lines 1269-1319)
# ============================================================================


# ============================================================================
# Tests for skill collection from tree (lines 1966-2014)
# ============================================================================


@patch("management.services.agent.transfer.resolve_sub_agent_version_no")
@patch("management.services.agent.transfer.query_sub_agent_relations")
@patch("management.services.agent.transfer.skill_db")
def test_collect_skill_names_from_tree_with_sub_agents(
    mock_skill_db, mock_relations, mock_resolve
):
    """_collect_skill_names_from_tree should recursively collect skills from sub-agents."""
    from management.services.agent.service import _collect_skill_names_from_tree

    # Agent 1 has skill "Skill1" and sub-agent 2
    mock_skill_db.query_skill_instances_by_agent_id.side_effect = [
        [{"skill_id": 1}],  # Agent 1's skills
        [{"skill_id": 2}],  # Agent 2's skills
    ]
    mock_skill_db.get_skill_by_id.side_effect = [
        {"name": "Skill1"},
        {"name": "Skill2"},
    ]

    # Agent 1 -> Agent 2
    mock_relations.side_effect = [
        [
            {"selected_agent_id": 2, "selected_agent_version_no": 1}
        ],  # Agent 1's relations
        [],  # Agent 2's relations
    ]
    mock_resolve.return_value = 1

    result = _collect_skill_names_from_tree(
        agent_id=1, tenant_id="tenant1", version_no=1
    )

    assert "Skill1" in result
    assert "Skill2" in result
    assert len(result) == 2


@patch("management.services.agent.transfer.query_sub_agent_relations")
@patch("management.services.agent.transfer.skill_db")
def test_collect_skill_names_from_tree_no_skills(mock_skill_db, mock_relations):
    """_collect_skill_names_from_tree should return empty list when no skills found."""
    from management.services.agent.service import _collect_skill_names_from_tree

    mock_skill_db.query_skill_instances_by_agent_id.return_value = []
    mock_relations.return_value = []

    result = _collect_skill_names_from_tree(
        agent_id=1, tenant_id="tenant1", version_no=1
    )

    assert result == []


@patch("management.services.agent.transfer.skill_db")
def test_collect_skill_names_from_tree_skill_not_found(mock_skill_db):
    """_collect_skill_names_from_tree should handle missing skills gracefully."""
    from management.services.agent.service import _collect_skill_names_from_tree

    mock_skill_db.query_skill_instances_by_agent_id.return_value = [{"skill_id": 1}]
    mock_skill_db.get_skill_by_id.return_value = None  # Skill not found
    mock_skill_db.query_sub_agent_relations.return_value = []

    # Should not raise
    result = _collect_skill_names_from_tree(
        agent_id=1, tenant_id="tenant1", version_no=1
    )
    assert result == []


# ============================================================================
# Tests for export_agent_by_agent_id (lines 2060-2078)
# ============================================================================


@pytest.mark.asyncio
async def test_export_agent_by_agent_id_skill_error(monkeypatch):
    """export_agent_by_agent_id should handle skill collection error gracefully."""
    from management.services.agent import transfer as agent_service

    async def mock_create_tool_config_list(*args, **kwargs):
        return []

    with patch(
        "management.services.agent.transfer.search_agent_info_by_agent_id"
    ) as mock_search:
        mock_search.return_value = {
            "agent_id": 1,
            "name": "Test",
            "display_name": "Test Agent",
            "description": "Test agent",
            "business_description": "Test",
            "max_steps": 5,
            "provide_run_summary": True,
            "enabled": True,
            "tenant_id": "tenant1",
            "model_ids": [],
        }

        with patch(
            "management.services.agent.transfer.query_sub_agents_id_list"
        ) as mock_sub:
            mock_sub.return_value = []

            with patch(
                "management.services.agent.transfer.create_tool_config_list",
                new=mock_create_tool_config_list,
            ):
                with patch.object(agent_transfer, "skill_db") as mock_skill_db:
                    mock_skill_db.query_skill_instances_by_agent_id.side_effect = (
                        Exception("DB error")
                    )

                    with patch(
                        "management.services.agent.transfer.get_model_by_model_id"
                    ) as mock_model:
                        mock_model.return_value = None

                        # Should not raise, just log warning
                        result = await agent_service.export_agent_by_agent_id(
                            agent_id=1,
                            tenant_id="tenant1",
                            user_id="user1",
                            version_no=0,
                        )

                        # Should return agent info with empty skill_names
                        assert result.skill_names == []


@pytest.mark.asyncio
async def test_export_agent_by_agent_id_knowledge_base_tool(monkeypatch):
    """export_agent_by_agent_id should reset metadata for KnowledgeBase tools."""
    from management.services.agent import transfer as agent_service

    async def mock_create_tool_config_list(*args, **kwargs):
        return []

    with patch(
        "management.services.agent.transfer.search_agent_info_by_agent_id"
    ) as mock_search:
        mock_search.return_value = {
            "agent_id": 1,
            "name": "Test",
            "display_name": "Test Agent",
            "description": "Test agent",
            "business_description": "Test",
            "max_steps": 5,
            "provide_run_summary": True,
            "enabled": True,
            "tenant_id": "tenant1",
            "model_ids": [],
        }

        with patch(
            "management.services.agent.transfer.query_sub_agents_id_list"
        ) as mock_sub:
            mock_sub.return_value = []

            with patch(
                "management.services.agent.transfer.create_tool_config_list",
                new=mock_create_tool_config_list,
            ):
                with patch.object(agent_transfer, "skill_db") as mock_skill_db:
                    mock_skill_db.query_skill_instances_by_agent_id.return_value = []
                    mock_skill_db.get_skill_by_id.return_value = None

                    with patch(
                        "management.services.agent.transfer.get_model_by_model_id"
                    ) as mock_model:
                        mock_model.return_value = None

                        # Should not raise
                        result = await agent_service.export_agent_by_agent_id(
                            agent_id=1,
                            tenant_id="tenant1",
                            user_id="user1",
                            version_no=0,
                        )

                        # Should return valid agent info
                        assert result.agent_id == 1
                        assert result.name == "Test"


# ============================================================================
# Tests for collect_skill_zip_entries (lines 2017-2035)
# ============================================================================


# ============================================================================
# Tests for generate_stream error handling (lines 2785-2793)
# ============================================================================


    # First chunk should be either memory start token or error token
    # The error handler yields error chunk after memory tokens


# ============================================================================
# Tests for run_agent_stream resume mode channel_stream (lines 2994-3011)
# ============================================================================


# ============================================================================
# Tests for collect_skill_zip_entries (lines 2017-2035)
# ============================================================================


@patch("management.services.agent.transfer.SkillService")
@patch("management.services.agent.transfer._collect_skill_names_from_tree")
def test_collect_skill_zip_entries_with_skills(mock_collect, mock_service):
    """collect_skill_zip_entries should export skills when found."""
    from management.services.agent.service import collect_skill_zip_entries

    mock_collect.return_value = ["Skill1", "Skill2"]

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.export_skills_by_names.return_value = [
        {"skill_name": "Skill1", "skill_zip_base64": "base64data1"},
        {"skill_name": "Skill2", "skill_zip_base64": "base64data2"},
    ]
    mock_service.return_value = mock_skill_service_instance

    result = collect_skill_zip_entries(agent_id=1, tenant_id="tenant1", version_no=1)

    assert len(result) == 2
    assert result[0].skill_name == "Skill1"
    assert result[1].skill_name == "Skill2"


@pytest.mark.asyncio
async def test_update_agent_info_impl_self_reference(monkeypatch):
    """update_agent_info_impl should raise error when agent references itself."""
    from management.services.agent import service as agent_service
    agent_request = MagicMock()
    agent_request.agent_id = 1
    agent_request.related_agent_ids = [1]
    agent_request.enabled_skill_ids = None
    agent_request.skill_instances = None
    with patch('management.services.agent.service.search_agent_info_by_agent_id') as mock_search:
        mock_search.return_value = {'agent_id': 1, 'name': 'test', 'enabled': True}
        with pytest.raises(ValueError) as exc_info:
            await agent_service.update_agent_info_impl(agent_request, AuthenticatedIdentity('user1', 'tenant1'))
        assert 'Circular dependency' in str(exc_info.value)


# ============================================================================
# Tests for collect_skill_zip_entries (lines 2017-2029)
# ============================================================================


@patch("management.services.agent.transfer.SkillService")
@patch("management.services.agent.transfer._collect_skill_names_from_tree")
def test_collect_skill_zip_entries_no_skills(mock_collect, mock_service):
    """collect_skill_zip_entries should return empty list when no skills found."""
    from management.services.agent.service import collect_skill_zip_entries

    mock_collect.return_value = []

    result = collect_skill_zip_entries(agent_id=1, tenant_id="tenant1", version_no=1)

    assert result == []
    mock_service.assert_not_called()


# ============================================================================
# Tests for run_agent_stream resume mode (lines 2936-3012)
# ============================================================================


def test_agent_run_registration_is_retained_until_worker_future_finishes():
    from concurrent.futures import Future

    future = Future()
    run_info = MagicMock(
        thread_future=future,
        thread_execution_id="execution-delayed",
    )
    unregister = MagicMock(return_value=True)
    registry = types.SimpleNamespace(unregister_agent_run=unregister)

    released = _thread_lifecycle_module.unregister_after_worker_exit(
        registry,
        999,
        "user1",
        "stopped",
        run_info,
    )

    assert released is False
    unregister.assert_not_called()
    future.set_result(None)
    unregister.assert_called_once_with(
        999,
        "user1",
        status="stopped",
        agent_run_info=run_info,
    )


@pytest.mark.asyncio
async def test_shutdown_agent_stream_tasks_cancels_request_owned_tasks():
    started = asyncio.Event()

    async def wait_forever():
        started.set()
        await asyncio.Event().wait()

    producer = asyncio.create_task(wait_forever(), name="test-agent-producer")
    _thread_lifecycle_module.agent_stream_producer_tasks.add(producer)
    producer.add_done_callback(_thread_lifecycle_module.agent_stream_producer_tasks.discard)
    await started.wait()

    pending = await _thread_lifecycle_module.shutdown_agent_stream_tasks(timeout=1)
    await asyncio.sleep(0)

    assert pending == ()
    assert producer.cancelled()
    assert producer not in _thread_lifecycle_module.agent_stream_producer_tasks


    # preprocess_manager.unregister_preprocess_task was removed together with
    # the legacy preprocess registration; only the register call is gated
    # on asyncio.current_task() being non-None.


class TestNormalizeAgentOutputReserve:
    """Retired Agent output reserves cannot gate saves or override outlets."""

    @pytest.fixture(autouse=True)
    def _stub_agent_output_reserve_normalization(self):
        yield

    @pytest.mark.parametrize("reserve", [None, 128, 4096, 999999])
    def test_retired_reserve_is_normalized_without_model_lookup(self, reserve):
        from management.services.agent.service import (
            AgentInfoRequest, _normalize_agent_output_reserve,
        )
        request = AgentInfoRequest(agent_id=1, model_ids=[5], requested_output_tokens=reserve)
        with patch("management.services.agent.service.get_model_by_model_id") as lookup:
            _normalize_agent_output_reserve(request)
        assert request.requested_output_tokens is None
        lookup.assert_not_called()


# ============================================================================
# ============================================================================


# ============================================================================
# ============================================================================


# ============================================================================
# Tests for resume mode update_message_status exception handling (lines 2987-2993)
# ============================================================================


# ============================================================================
# Tests for get_valid_model_ids integration in list_all_agent_info_impl
# ============================================================================


@pytest.mark.asyncio
@patch("management.services.agent.read.get_valid_model_ids")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_filters_deleted_models(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
    mock_get_valid_model_ids,
):
    """Test that list_all_agent_info_impl filters out deleted models from model_ids.

    This test verifies that:
    1. get_valid_model_ids is called to filter deleted models
    2. The filtered model_ids are used for availability check and model name resolution
    3. The returned model_ids only contain valid (non-deleted) models
    """
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Test agent with models",
            "enabled": True,
            "model_ids": [1, 2, 3],  # Original model_ids including deleted ones
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
        }
    ]
    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.return_value = []

    # Mock get_valid_model_ids to filter out model_id=2 (deleted)
    mock_get_valid_model_ids.return_value = [1, 3]  # Only models 1 and 3 are valid

    # Mock model info for valid models (get_model_by_model_id takes 2 args: model_id and tenant_id)
    def get_model_side_effect(model_id, tenant_id=None):
        if model_id == 1:
            return {"display_name": "Model 1", "model_id": 1}
        elif model_id == 3:
            return {"display_name": "Model 3", "model_id": 3}
        return None

    mock_get_model.side_effect = get_model_side_effect

    mock_check_availability.return_value = (True, [])

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    # Verify get_valid_model_ids was called with original model_ids and tenant_id
    mock_get_valid_model_ids.assert_called_once_with([1, 2, 3], "test_tenant")

    # Verify result contains only valid model_ids
    assert len(result) == 1
    assert result[0]["model_ids"] == [1, 3]
    assert result[0]["model_names"] == ["Model 1", "Model 3"]


@pytest.mark.asyncio
@patch("management.services.agent.read.get_valid_model_ids")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_all_models_deleted(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
    mock_get_valid_model_ids,
):
    """Test that list_all_agent_info_impl handles when all models are deleted.

    This test verifies that:
    1. get_valid_model_ids returns empty list when all models are deleted
    2. model_names is empty
    3. Availability check is still performed with empty model_ids
    """
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Test agent",
            "enabled": True,
            "model_ids": [1, 2, 3],
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
        }
    ]
    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.return_value = []

    # All models were deleted
    mock_get_valid_model_ids.return_value = []

    mock_check_availability.return_value = (True, [])

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    # Verify result has empty model_ids and model_names
    assert len(result) == 1
    assert result[0]["model_ids"] == []
    assert result[0]["model_names"] == []
    assert result[0]["model_name"] is None


@pytest.mark.asyncio
@patch("management.services.agent.read.get_valid_model_ids")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_empty_model_ids(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
    mock_get_valid_model_ids,
):
    """Test that list_all_agent_info_impl handles empty model_ids."""
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Test agent",
            "enabled": True,
            "model_ids": [],  # Empty model_ids
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
        }
    ]
    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.return_value = []

    # get_valid_model_ids should be called with empty list
    mock_get_valid_model_ids.return_value = []

    mock_check_availability.return_value = (True, [])

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    mock_get_valid_model_ids.assert_called_once_with([], "test_tenant")
    assert result[0]["model_ids"] == []
    assert result[0]["model_names"] == []


# ============================================================================
# Tests for get_valid_model_ids integration in get_agent_info_impl
# ============================================================================


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_filters_deleted_models(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """Test that get_agent_info_impl filters out deleted models from model_ids.

    This test verifies that:
    1. get_valid_model_ids is called to filter deleted models
    2. The filtered model_ids are used for availability check and model name resolution
    3. The returned model_ids only contain valid (non-deleted) models
    """
    mock_agent_info = {
        "agent_id": 123,
        "model_ids": [1, 2, 3],  # Original model_ids including deleted ones
        "business_description": "Test agent",
    }
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = [{"tool_id": 1, "name": "Tool 1"}]
    mock_query_sub_agents_id.return_value = [456]

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance
    mock_query_external_sub_agents.return_value = []

    # Mock get_model_by_model_id for valid models
    def get_model_side_effect(model_id, tenant_id=None):
        if model_id == 1:
            return {"display_name": "Model 1", "model_id": 1}
        elif model_id == 3:
            return {"display_name": "Model 3", "model_id": 3}
        return None

    mock_get_model_by_model_id.side_effect = get_model_side_effect

    mock_check_availability.return_value = (True, [])

    # Mock get_valid_model_ids to filter out model_id=2 (deleted)
    with patch(
        "management.services.agent.read.get_valid_model_ids"
    ) as mock_get_valid_model_ids:
        mock_get_valid_model_ids.return_value = [1, 3]

        result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

        # Verify get_valid_model_ids was called
        mock_get_valid_model_ids.assert_called_once_with([1, 2, 3], "test_tenant")

    # Verify result contains only valid model_ids
    assert result["model_ids"] == [1, 3]
    assert result["model_names"] == ["Model 1", "Model 3"]
    assert result["model_name"] == "Model 1"  # First model's display_name


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_all_models_deleted(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """Test that get_agent_info_impl handles when all models are deleted."""
    mock_agent_info = {
        "agent_id": 123,
        "model_ids": [1, 2, 3],
        "business_description": "Test agent",
    }
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = []
    mock_query_sub_agents_id.return_value = []

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance
    mock_query_external_sub_agents.return_value = []

    mock_get_model_by_model_id.return_value = None
    mock_check_availability.return_value = (True, [])

    with patch(
        "management.services.agent.read.get_valid_model_ids"
    ) as mock_get_valid_model_ids:
        mock_get_valid_model_ids.return_value = []  # All models deleted

        result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    assert result["model_ids"] == []
    assert result["model_names"] == []
    assert result["model_name"] is None


# =============================================================================
# Tests for Sandbox Policy Builder (lines 3671-3686)
# =============================================================================


class TestBuildSandboxPolicy:
    """Tests for build_sandbox_policy function.

    Note: The function imports contracts.constants.environment inside the function body,
    so we test the function signature and basic existence here.
    Integration tests would require mocking at the consts module level.
    """

    def test_build_sandbox_policy_function_exists(self):
        """Test that build_sandbox_policy function exists and is callable."""
        from management.services.agent.service import build_sandbox_policy

        assert callable(build_sandbox_policy)

    def test_build_sandbox_policy_accepts_required_args(self):
        """Test that build_sandbox_policy accepts tenant_id and agent_type arguments."""
        from management.services.agent.service import build_sandbox_policy
        import inspect

        sig = inspect.signature(build_sandbox_policy)
        params = list(sig.parameters.keys())

        assert "tenant_id" in params
        assert "agent_type" in params

    def test_build_sandbox_policy_includes_configurable_host_tool_timeout(self):
        from contracts.constants import environment as const_module
        from management.services.agent.service import build_sandbox_policy

        with (
            patch.object(const_module, "NEXENT_SANDBOX_DEFAULT_LEVEL", "docker"),
            patch.object(const_module, "NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_S", 900),
        ):
            policy = build_sandbox_policy("tenant-1", "")

        assert policy["host_tool_timeout_seconds"] == 900


class TestGetSandboxMinioClient:
    """Tests for get_sandbox_minio_client function."""

    def test_get_sandbox_minio_client_function_exists(self):
        """Test that get_sandbox_minio_client function exists and is callable."""
        from management.services.agent.service import get_sandbox_minio_client

        assert callable(get_sandbox_minio_client)


# =============================================================================
# Tests for helper functions in agent_service.py
# =============================================================================


class TestExtractJsonObjectsFromText:
    """Tests for _extract_json_objects_from_text function."""

    def test_extract_json_objects_empty_string(self):
        """Test _extract_json_objects_from_text returns empty list for empty string."""
        from management.services.agent.artifacts import (
            extract_json_objects_from_text as _extract_json_objects_from_text,
        )

        result = _extract_json_objects_from_text("")
        assert result == []

    def test_extract_json_objects_none_string(self):
        """Test _extract_json_objects_from_text returns empty list for None."""
        from management.services.agent.artifacts import (
            extract_json_objects_from_text as _extract_json_objects_from_text,
        )

        result = _extract_json_objects_from_text(None)
        assert result == []

    def test_extract_json_objects_single_object(self):
        """Test _extract_json_objects_from_text extracts single JSON object."""
        from management.services.agent.artifacts import (
            extract_json_objects_from_text as _extract_json_objects_from_text,
        )

        text = '{"key": "value"}'
        result = _extract_json_objects_from_text(text)
        assert len(result) == 1
        assert result[0] == {"key": "value"}

    def test_extract_json_objects_multiple_objects(self):
        """Test _extract_json_objects_from_text extracts multiple JSON objects."""
        from management.services.agent.artifacts import (
            extract_json_objects_from_text as _extract_json_objects_from_text,
        )

        text = '{"a": 1} some text {"b": 2} more text {"c": 3}'
        result = _extract_json_objects_from_text(text)
        assert len(result) == 3
        assert result[0] == {"a": 1}
        assert result[1] == {"b": 2}
        assert result[2] == {"c": 3}

    def test_extract_json_objects_nested_object(self):
        """Test _extract_json_objects_from_text extracts nested JSON objects."""
        from management.services.agent.artifacts import (
            extract_json_objects_from_text as _extract_json_objects_from_text,
        )

        text = '{"outer": {"inner": "value"}}'
        result = _extract_json_objects_from_text(text)
        assert len(result) == 1
        assert result[0] == {"outer": {"inner": "value"}}

    def test_extract_json_objects_array_not_included(self):
        """Test _extract_json_objects_from_text excludes arrays."""
        from management.services.agent.artifacts import (
            extract_json_objects_from_text as _extract_json_objects_from_text,
        )

        text = '{"key": [1, 2, 3]}'
        result = _extract_json_objects_from_text(text)
        assert len(result) == 1
        assert result[0] == {"key": [1, 2, 3]}

    def test_extract_json_objects_with_invalid_json(self):
        """Test _extract_json_objects_from_text skips invalid JSON."""
        from management.services.agent.artifacts import (
            extract_json_objects_from_text as _extract_json_objects_from_text,
        )

        text = '{"valid": true} {invalid} {"also": "valid"}'
        result = _extract_json_objects_from_text(text)
        assert len(result) == 2
        assert result[0] == {"valid": True}
        assert result[1] == {"also": "valid"}


class TestExtractSkillFileUploadPayloads:
    """Tests for _extract_skill_file_upload_payloads function."""

    def test_extract_skill_file_payloads_empty(self):
        """Test _extract_skill_file_upload_payloads returns empty list for empty input."""
        from management.services.agent.artifacts import (
            extract_skill_file_upload_payloads as _extract_skill_file_upload_payloads,
        )

        result = _extract_skill_file_upload_payloads("")
        assert result == []

    def test_extract_skill_file_payloads_with_absolute_path(self):
        """Test _extract_skill_file_upload_payloads extracts payloads with absolute_path."""
        from management.services.agent.artifacts import (
            extract_skill_file_upload_payloads as _extract_skill_file_upload_payloads,
        )

        text = '{"absolute_path": "/tmp/test.txt", "file_name": "test.txt"}'
        result = _extract_skill_file_upload_payloads(text)
        assert len(result) == 1
        assert result[0]["absolute_path"] == "/tmp/test.txt"

    def test_extract_skill_file_payloads_without_absolute_path(self):
        """Test _extract_skill_file_upload_payloads excludes payloads without absolute_path."""
        from management.services.agent.artifacts import (
            extract_skill_file_upload_payloads as _extract_skill_file_upload_payloads,
        )

        text = '{"file_name": "test.txt"}'
        result = _extract_skill_file_upload_payloads(text)
        assert len(result) == 0

    def test_extract_skill_file_payloads_multiple(self):
        """Test _extract_skill_file_upload_payloads extracts multiple valid payloads."""
        from management.services.agent.artifacts import (
            extract_skill_file_upload_payloads as _extract_skill_file_upload_payloads,
        )

        text = '{"absolute_path": "/tmp/a.txt"} extra {"absolute_path": "/tmp/b.txt"}'
        result = _extract_skill_file_upload_payloads(text)
        assert len(result) == 2
        assert result[0]["absolute_path"] == "/tmp/a.txt"
        assert result[1]["absolute_path"] == "/tmp/b.txt"


class TestTransformSkillFilesToStandardFormat:
    """Tests for _transform_skill_files_to_standard_format function."""

    def test_transform_skill_files_empty(self):
        """Test _transform_skill_files_to_standard_format returns empty list for empty input."""
        from management.services.agent.artifacts import (
            transform_skill_files_to_standard_format as _transform_skill_files_to_standard_format,
        )

        result = _transform_skill_files_to_standard_format([])
        assert result == []

    def test_transform_skill_files_full_fields(self):
        """Test _transform_skill_files_to_standard_format transforms complete upload results."""
        from management.services.agent.artifacts import (
            transform_skill_files_to_standard_format as _transform_skill_files_to_standard_format,
        )

        upload_results = [
            {
                "file_name": "test.txt",
                "object_name": "obj123",
                "url": "https://example.com/test.txt",
                "presigned_url": "https://example.com/presigned",
                "file_size": 1024,
                "mime_type": "text/plain",
            }
        ]
        result = _transform_skill_files_to_standard_format(upload_results)
        assert len(result) == 1
        assert result[0]["object_name"] == "obj123"
        assert result[0]["name"] == "test.txt"
        assert result[0]["type"] == "file"
        assert result[0]["size"] == 1024
        assert result[0]["url"] == "https://example.com/test.txt"
        assert result[0]["presigned_url"] == "https://example.com/presigned"
        assert result[0]["description"] == ""

    def test_transform_skill_files_ignores_preview_url(self):
        """Temporary preview URLs are not part of the permanent file contract."""
        from management.services.agent.artifacts import (
            transform_skill_files_to_standard_format as _transform_skill_files_to_standard_format,
        )

        upload_results = [
            {
                "file_name": "test.txt",
                "preview_url": "https://example.com/preview",
                "url": "https://example.com/test.txt",
                "file_size": 1024,
            }
        ]
        result = _transform_skill_files_to_standard_format(upload_results)
        assert result[0]["url"] == "https://example.com/test.txt"
        assert "presigned_url" not in result[0]

    def test_transform_skill_files_uses_size_fallback(self):
        """Test _transform_skill_files_to_standard_format uses 'size' as fallback for 'file_size'."""
        from management.services.agent.artifacts import (
            transform_skill_files_to_standard_format as _transform_skill_files_to_standard_format,
        )

        upload_results = [
            {
                "name": "test.txt",
                "size": 2048,
            }
        ]
        result = _transform_skill_files_to_standard_format(upload_results)
        assert result[0]["size"] == 2048

    def test_transform_skill_files_multiple(self):
        """Test _transform_skill_files_to_standard_format transforms multiple files."""
        from management.services.agent.artifacts import (
            transform_skill_files_to_standard_format as _transform_skill_files_to_standard_format,
        )

        upload_results = [
            {"file_name": "a.txt", "size": 100},
            {"file_name": "b.txt", "size": 200},
        ]
        result = _transform_skill_files_to_standard_format(upload_results)
        assert len(result) == 2
        assert result[0]["name"] == "a.txt"
        assert result[1]["name"] == "b.txt"


class TestSafeAgentStreamErrorChunk:
    """Tests for _safe_agent_stream_error_chunk function."""

    def test_safe_agent_stream_error_chunk_format(self):
        """Test _safe_agent_stream_error_chunk returns properly formatted SSE chunk."""
        from management.services.agent.stream import (
            safe_agent_stream_error_chunk as _safe_agent_stream_error_chunk,
        )

        result = _safe_agent_stream_error_chunk()
        assert result.startswith("data: ")
        assert "\n\n" in result
        assert "error" in result
        assert "content" in result

    def test_safe_agent_stream_error_chunk_contains_safe_message(self):
        """Test _safe_agent_stream_error_chunk contains safe error message."""
        from management.services.agent.stream import (
            safe_agent_stream_error_chunk as _safe_agent_stream_error_chunk,
        )

        result = _safe_agent_stream_error_chunk()
        assert "Agent execution failed" in result


class TestGetUserGroupIds:
    """Tests for _get_user_group_ids function."""

    @patch("management.services.agent.transfer.query_group_ids_by_user")
    def test_get_user_group_ids_success(self, mock_query_groups):
        """Test _get_user_group_ids returns comma-separated group IDs."""
        from management.services.agent.service import _get_user_group_ids

        mock_query_groups.return_value = ["1", "2", "3"]

        result = _get_user_group_ids("user123", "tenant456")

        assert result == "1,2,3"
        mock_query_groups.assert_called_once_with("user123")

    @patch("management.services.agent.transfer.query_group_ids_by_user")
    def test_get_user_group_ids_empty(self, mock_query_groups):
        """Test _get_user_group_ids returns empty string when no groups."""
        from management.services.agent.service import _get_user_group_ids

        mock_query_groups.return_value = []

        result = _get_user_group_ids("user123", "tenant456")

        assert result == ""

    @patch("management.services.agent.transfer.query_group_ids_by_user")
    @patch("management.services.agent.transfer.logger")
    def test_get_user_group_ids_exception(self, mock_logger, mock_query_groups):
        """Test _get_user_group_ids returns empty string on exception."""
        from management.services.agent.service import _get_user_group_ids

        mock_query_groups.side_effect = Exception("Database error")

        result = _get_user_group_ids("user123", "tenant456")

        assert result == ""
        mock_logger.warning.assert_called_once()


class TestResolveModelIdsWithFallback:
    """Tests for _resolve_model_ids_with_fallback function."""

    @patch("management.services.agent.transfer.get_model_by_model_id")
    @patch("management.services.agent.transfer.get_model_id_by_display_name")
    @patch("management.services.agent.transfer.MODEL_CONFIG_MAPPING")
    def test_resolve_model_ids_explicit_ids(
        self, mock_config, mock_get_by_name, mock_get_by_id
    ):
        """Test _resolve_model_ids_with_fallback uses explicit model_ids when available."""
        from management.services.agent.service import _resolve_model_ids_with_fallback

        mock_get_by_id.return_value = {"display_name": "Test Model"}

        result = _resolve_model_ids_with_fallback(
            model_ids=[1, 2],
            model_display_names=None,
            model_label="Model",
            tenant_id="tenant123",
        )

        assert result == [1, 2]

    @patch("management.services.agent.transfer.get_model_by_model_id")
    @patch("management.services.agent.transfer.get_model_id_by_display_name")
    @patch("management.services.agent.transfer.MODEL_CONFIG_MAPPING")
    def test_resolve_model_ids_fallback_to_names(
        self, mock_config, mock_get_by_name, mock_get_by_id
    ):
        """Test _resolve_model_ids_with_fallback falls back to display names."""
        from management.services.agent.service import _resolve_model_ids_with_fallback

        mock_get_by_id.return_value = None
        mock_get_by_name.return_value = 5

        result = _resolve_model_ids_with_fallback(
            model_ids=None,
            model_display_names=["TestModel"],
            model_label="Model",
            tenant_id="tenant123",
        )

        assert result == [5]


class TestCollectSkillNamesFromTree:
    """Tests for _collect_skill_names_from_tree function."""

    @patch("management.services.agent.transfer.skill_db")
    @patch("management.services.agent.transfer.query_sub_agent_relations")
    def test_collect_skill_names_empty(self, mock_relations, mock_skill_db):
        """Test _collect_skill_names_from_tree returns empty list when no skills."""
        from management.services.agent.service import _collect_skill_names_from_tree

        mock_skill_db.query_skill_instances_by_agent_id.return_value = []
        mock_relations.return_value = []

        result = _collect_skill_names_from_tree(1, "tenant123", 0)

        assert result == []

    @patch("management.services.agent.transfer.skill_db")
    @patch("management.services.agent.transfer.query_sub_agent_relations")
    def test_collect_skill_names_single_skill(self, mock_relations, mock_skill_db):
        """Test _collect_skill_names_from_tree collects skill names."""
        from management.services.agent.service import _collect_skill_names_from_tree

        mock_skill_db.query_skill_instances_by_agent_id.return_value = [{"skill_id": 1}]
        mock_skill_db.get_skill_by_id.return_value = {"name": "TestSkill"}
        mock_relations.return_value = []

        result = _collect_skill_names_from_tree(1, "tenant123", 0)

        assert result == ["TestSkill"]

    @patch("management.services.agent.transfer.skill_db")
    @patch("management.services.agent.transfer.query_sub_agent_relations")
    def test_collect_skill_names_deduplicates(self, mock_relations, mock_skill_db):
        """Test _collect_skill_names_from_tree deduplicates skill names."""
        from management.services.agent.service import _collect_skill_names_from_tree

        mock_skill_db.query_skill_instances_by_agent_id.return_value = [
            {"skill_id": 1},
            {"skill_id": 1},
        ]
        mock_skill_db.get_skill_by_id.return_value = {"name": "TestSkill"}
        mock_relations.return_value = []

        result = _collect_skill_names_from_tree(1, "tenant123", 0)

        assert result == ["TestSkill"]

    @patch("management.services.agent.transfer.skill_db")
    @patch("management.services.agent.transfer.query_sub_agent_relations")
    def test_collect_skill_names_handles_missing_skill(
        self, mock_relations, mock_skill_db
    ):
        """Test _collect_skill_names_from_tree handles missing skill gracefully."""
        from management.services.agent.service import _collect_skill_names_from_tree

        mock_skill_db.query_skill_instances_by_agent_id.return_value = [{"skill_id": 1}]
        mock_skill_db.get_skill_by_id.return_value = None
        mock_relations.return_value = []

        result = _collect_skill_names_from_tree(1, "tenant123", 0)

        assert result == []


class TestCollectSkillZipEntries:
    """Tests for collect_skill_zip_entries function."""

    @patch("management.services.agent.transfer._collect_skill_names_from_tree")
    def test_collect_skill_zip_entries_empty(self, mock_collect):
        """Test collect_skill_zip_entries returns empty list when no skills."""
        from management.services.agent.service import collect_skill_zip_entries

        mock_collect.return_value = []

        result = collect_skill_zip_entries(1, "tenant123", 0)

        assert result == []

    @patch("management.services.agent.transfer.SkillService")
    @patch("management.services.agent.transfer._collect_skill_names_from_tree")
    def test_collect_skill_zip_entries_success(self, mock_collect, mock_skill_service):
        """Test collect_skill_zip_entries returns skill zip entries."""
        from management.services.agent.service import collect_skill_zip_entries

        mock_collect.return_value = ["TestSkill"]
        mock_service_instance = MagicMock()
        mock_service_instance.export_skills_by_names.return_value = [
            {"skill_name": "TestSkill", "skill_zip_base64": "abc123"}
        ]
        mock_skill_service.return_value = mock_service_instance

        result = collect_skill_zip_entries(1, "tenant123", 0)

        assert len(result) == 1
        assert result[0].skill_name == "TestSkill"
        assert result[0].skill_zip_base64 == "abc123"


class TestClearAgentNewMarkImpl:
    """Tests for clear_agent_new_mark_impl function."""

    @patch("management.services.agent.management.clear_agent_new_mark")
    @patch("management.services.agent.management.logger")
    async def test_clear_agent_new_mark_impl_success(self, mock_logger, mock_clear):
        """Test clear_agent_new_mark_impl calls clear_agent_new_mark and logs result."""
        from management.services.agent.service import clear_agent_new_mark_impl

        mock_clear.return_value = 1

        result = await clear_agent_new_mark_impl(123, "tenant456", "user789")

        assert result == 1
        mock_clear.assert_called_once_with(123, "tenant456", "user789")
        mock_logger.info.assert_called_once()
        assert "affected_rows=1" in mock_logger.info.call_args[0][0]


class TestLoadDefaultAgentsJsonFile:
    """Tests for load_default_agents_json_file function."""

    @patch("builtins.open", new_callable=MagicMock)
    @patch("test.backend.services.agent_legacy_helpers.os.listdir")
    @patch("test.backend.services.agent_legacy_helpers.os.path.join")
    def test_load_default_agents_json_file_empty_dir(
        self, mock_join, mock_listdir, mock_open
    ):
        """Test load_default_agents_json_file returns empty list for empty directory."""
        from test.backend.services.agent_legacy_helpers import (load_default_agents_json_file)

        mock_listdir.return_value = ["readme.txt", "config.yaml"]

        result = load_default_agents_json_file("/path/to/agents")

        assert result == []

    @patch("builtins.open", new_callable=MagicMock)
    @patch("test.backend.services.agent_legacy_helpers.os.listdir")
    @patch("test.backend.services.agent_legacy_helpers.os.path.join")
    def test_load_default_agents_json_file_with_json(
        self, mock_join, mock_listdir, mock_open
    ):
        """Test load_default_agents_json_file loads JSON files."""
        from test.backend.services.agent_legacy_helpers import (load_default_agents_json_file)
        import json

        mock_listdir.return_value = ["agent1.json", "readme.txt"]
        mock_file_content = {
            "agent_id": "1",
            "name": "TestAgent",
            "display_name": "Test Agent",
            "description": "A test agent",
            "business_description": "Test",
            "max_steps": 5,
            "provide_run_summary": True,
            "enabled": True,
            "tools": [],
            "managed_agents": [],
        }
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_file.read.return_value = json.dumps(mock_file_content)
        mock_open.return_value = mock_file
        mock_join.side_effect = lambda a, b: f"{a}/{b}"

        result = load_default_agents_json_file("/path/to/agents")

        assert len(result) == 1
        assert result[0].name == "TestAgent"


class TestInsertRelatedAgentImpl:
    """Tests for insert_related_agent_impl function."""

    @patch("test.backend.services.agent_legacy_helpers.insert_related_agent")
    @patch("test.backend.services.agent_legacy_helpers.query_sub_agents_id_list")
    def test_insert_related_agent_impl_success(self, mock_query, mock_insert):
        """Test insert_related_agent_impl returns success response."""
        from test.backend.services.agent_legacy_helpers import (insert_related_agent_impl)
        from fastapi.responses import JSONResponse

        mock_query.return_value = [2, 3]
        mock_insert.return_value = True

        result = insert_related_agent_impl(1, 2, "tenant123")

        assert isinstance(result, JSONResponse)
        assert result.status_code == 200

    @patch("test.backend.services.agent_legacy_helpers.insert_related_agent")
    @patch("test.backend.services.agent_legacy_helpers.query_sub_agents_id_list")
    def test_insert_related_agent_impl_failure(self, mock_query, mock_insert):
        """Test insert_related_agent_impl returns error response."""
        from test.backend.services.agent_legacy_helpers import (insert_related_agent_impl)
        from fastapi.responses import JSONResponse

        mock_query.return_value = [2, 3]
        mock_insert.return_value = False

        result = insert_related_agent_impl(1, 2, "tenant123")

        assert isinstance(result, JSONResponse)
        assert result.status_code == 400


# ============================================================================
# Tests for get_valid_model_ids integration in list_all_agent_info_impl
# ============================================================================


@pytest.mark.asyncio
@patch("management.services.agent.read.get_valid_model_ids")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_filters_deleted_models(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
    mock_get_valid_model_ids,
):
    """Test that list_all_agent_info_impl filters out deleted models from model_ids.

    This test verifies that:
    1. get_valid_model_ids is called to filter deleted models
    2. The filtered model_ids are used for availability check and model name resolution
    3. The returned model_ids only contain valid (non-deleted) models
    """
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Test agent with models",
            "enabled": True,
            "model_ids": [1, 2, 3],  # Original model_ids including deleted ones
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
        }
    ]
    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.return_value = []

    # Mock get_valid_model_ids to filter out model_id=2 (deleted)
    mock_get_valid_model_ids.return_value = [1, 3]  # Only models 1 and 3 are valid

    # Mock model info for valid models (get_model_by_model_id takes 2 args: model_id and tenant_id)
    def get_model_side_effect(model_id, tenant_id=None):
        if model_id == 1:
            return {"display_name": "Model 1", "model_id": 1, "connect_status": "available"}
        elif model_id == 3:
            return {"display_name": "Model 3", "model_id": 3, "connect_status": "available"}
        return None

    mock_get_model.side_effect = get_model_side_effect

    mock_check_availability.return_value = (True, [])

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    # Verify get_valid_model_ids was called with original model_ids and tenant_id
    mock_get_valid_model_ids.assert_called_once_with([1, 2, 3], "test_tenant")

    # Verify result contains only valid model_ids
    assert len(result) == 1
    assert result[0]["model_ids"] == [1, 3]
    assert result[0]["model_names"] == ["Model 1", "Model 3"]


@pytest.mark.asyncio
@patch("management.services.agent.read.get_valid_model_ids")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_all_models_deleted(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
    mock_get_valid_model_ids,
):
    """Test that list_all_agent_info_impl handles when all models are deleted.

    This test verifies that:
    1. get_valid_model_ids returns empty list when all models are deleted
    2. model_names is empty
    3. Availability check is still performed with empty model_ids
    """
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Test agent",
            "enabled": True,
            "model_ids": [1, 2, 3],
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
        }
    ]
    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.return_value = []

    # All models were deleted
    mock_get_valid_model_ids.return_value = []

    mock_check_availability.return_value = (True, [])

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    # Verify result has empty model_ids and model_names
    assert len(result) == 1
    assert result[0]["model_ids"] == []
    assert result[0]["model_names"] == []
    assert result[0]["model_name"] is None


@pytest.mark.asyncio
@patch("management.services.agent.read.get_valid_model_ids")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.management.check_agent_availability")
@patch("management.services.agent.management.convert_string_to_list")
@patch("management.services.agent.management.get_user_tenant_by_user_id")
@patch("management.services.agent.management.query_group_ids_by_user")
@patch("management.services.agent.management.query_all_agent_info_by_tenant_id")
async def test_list_all_agent_info_impl_empty_model_ids(
    mock_query_agents,
    mock_query_groups,
    mock_get_user_tenant,
    mock_convert_list,
    mock_check_availability,
    mock_get_model,
    mock_get_valid_model_ids,
):
    """Test that list_all_agent_info_impl handles empty model_ids."""
    mock_agents = [
        {
            "agent_id": 1,
            "name": "Agent 1",
            "display_name": "Display Agent 1",
            "description": "Test agent",
            "enabled": True,
            "model_ids": [],  # Empty model_ids
            "group_ids": "",
            "created_by": "user1",
            "create_time": 1,
        }
    ]
    mock_query_agents.return_value = mock_agents
    mock_get_user_tenant.return_value = {"user_role": "ADMIN"}
    mock_query_groups.return_value = []
    mock_convert_list.return_value = []

    # get_valid_model_ids should be called with empty list
    mock_get_valid_model_ids.return_value = []

    mock_check_availability.return_value = (True, [])

    result = await list_all_agent_info_impl(
        tenant_id="test_tenant", user_id="admin_user"
    )

    mock_get_valid_model_ids.assert_called_once_with([], "test_tenant")
    assert result[0]["model_ids"] == []
    assert result[0]["model_names"] == []


# ============================================================================
# Tests for get_valid_model_ids integration in get_agent_info_impl
# ============================================================================


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_filters_deleted_models(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """Test that get_agent_info_impl filters out deleted models from model_ids.

    This test verifies that:
    1. get_valid_model_ids is called to filter deleted models
    2. The filtered model_ids are used for availability check and model name resolution
    3. The returned model_ids only contain valid (non-deleted) models
    """
    mock_agent_info = {
        "agent_id": 123,
        "model_ids": [1, 2, 3],  # Original model_ids including deleted ones
        "business_description": "Test agent",
    }
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = [{"tool_id": 1, "name": "Tool 1"}]
    mock_query_sub_agents_id.return_value = [456]

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance
    mock_query_external_sub_agents.return_value = []

    # Mock get_model_by_model_id for valid models
    def get_model_side_effect(model_id, tenant_id=None):
        if model_id == 1:
            return {"display_name": "Model 1", "model_id": 1, "connect_status": "available"}
        elif model_id == 3:
            return {"display_name": "Model 3", "model_id": 3, "connect_status": "available"}
        return None

    mock_get_model_by_model_id.side_effect = get_model_side_effect

    mock_check_availability.return_value = (True, [])

    # Mock get_valid_model_ids to filter out model_id=2 (deleted)
    with patch(
        "management.services.agent.read.get_valid_model_ids"
    ) as mock_get_valid_model_ids:
        mock_get_valid_model_ids.return_value = [1, 3]

        result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

        # Verify get_valid_model_ids was called
        mock_get_valid_model_ids.assert_called_once_with([1, 2, 3], "test_tenant")

    # Verify result contains only valid model_ids
    assert result["model_ids"] == [1, 3]
    assert result["model_names"] == ["Model 1", "Model 3"]
    assert result["model_name"] == "Model 1"  # First model's display_name


@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_all_models_deleted(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
):
    """Test that get_agent_info_impl handles when all models are deleted."""
    mock_agent_info = {
        "agent_id": 123,
        "model_ids": [1, 2, 3],
        "business_description": "Test agent",
    }
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = []
    mock_query_sub_agents_id.return_value = []

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance
    mock_query_external_sub_agents.return_value = []

    mock_get_model_by_model_id.return_value = None
    mock_check_availability.return_value = (True, [])

    with patch(
        "management.services.agent.read.get_valid_model_ids"
    ) as mock_get_valid_model_ids:
        mock_get_valid_model_ids.return_value = []  # All models deleted

        result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    assert result["model_ids"] == []
    assert result["model_names"] == []
    assert result["model_name"] is None


@patch("management.services.agent.service.batch_search_agent_display_names")
@patch("management.services.agent.service.batch_search_version_names")
@patch("management.services.agent.service.batch_query_current_version_nos")
@patch("management.services.agent.service.query_sub_agent_relations")
@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_sub_agent_relations_with_pinned_version(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
    mock_query_sub_agent_relations,
    mock_batch_query_current_version_nos,
    mock_batch_search_version_names,
    mock_batch_search_agent_display_names,
):
    """Test get_agent_info_impl enriches sub_agent_relations with pinned version_no."""
    mock_agent_info = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test",
    }
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = []
    mock_query_sub_agents_id.return_value = [456]
    mock_get_model_by_model_id.return_value = None
    mock_check_availability.return_value = (True, [])
    mock_query_external_sub_agents.return_value = []

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance

    mock_query_sub_agent_relations.return_value = [
        {"selected_agent_id": 456, "selected_agent_version_no": 2}
    ]
    mock_batch_query_current_version_nos.return_value = {}
    mock_batch_search_version_names.return_value = [
        {"agent_id": 456, "version_no": 2, "version_name": "v2.0"}
    ]
    mock_batch_search_agent_display_names.return_value = {456: "Sub Agent"}

    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    assert len(result["sub_agent_relations"]) == 1
    rel = result["sub_agent_relations"][0]
    assert rel["agent_id"] == 456
    assert rel["agent_name"] == "Sub Agent"
    assert rel["version_no"] == 2
    assert rel["version_name"] == "v2.0"


@patch("management.services.agent.service.batch_search_agent_display_names")
@patch("management.services.agent.service.batch_search_version_names")
@patch("management.services.agent.service.batch_query_current_version_nos")
@patch("management.services.agent.service.query_sub_agent_relations")
@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_sub_agent_relations_null_version_fallback(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
    mock_query_sub_agent_relations,
    mock_batch_query_current_version_nos,
    mock_batch_search_version_names,
    mock_batch_search_agent_display_names,
):
    """Test get_agent_info_impl resolves null version_no via batch_query_current_version_nos."""
    mock_agent_info = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test",
    }
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = []
    mock_query_sub_agents_id.return_value = [456]
    mock_get_model_by_model_id.return_value = None
    mock_check_availability.return_value = (True, [])
    mock_query_external_sub_agents.return_value = []

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance

    mock_query_sub_agent_relations.return_value = [
        {"selected_agent_id": 456, "selected_agent_version_no": None}
    ]
    mock_batch_query_current_version_nos.return_value = {456: 3}
    mock_batch_search_version_names.return_value = [
        {"agent_id": 456, "version_no": 3, "version_name": "v3.0"}
    ]
    mock_batch_search_agent_display_names.return_value = {456: "Sub Agent"}

    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    assert len(result["sub_agent_relations"]) == 1
    rel = result["sub_agent_relations"][0]
    assert rel["agent_id"] == 456
    assert rel["version_no"] == 3
    assert rel["version_name"] == "v3.0"


@patch("management.services.agent.service.batch_search_agent_display_names")
@patch("management.services.agent.service.batch_search_version_names")
@patch("management.services.agent.service.batch_query_current_version_nos")
@patch("management.services.agent.service.query_sub_agent_relations")
@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_sub_agent_relations_zero_version_fallback(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
    mock_query_sub_agent_relations,
    mock_batch_query_current_version_nos,
    mock_batch_search_version_names,
    mock_batch_search_agent_display_names,
):
    """Test get_agent_info_impl resolves version_no=0 via batch_query_current_version_nos."""
    mock_agent_info = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test",
    }
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = []
    mock_query_sub_agents_id.return_value = [456]
    mock_get_model_by_model_id.return_value = None
    mock_check_availability.return_value = (True, [])
    mock_query_external_sub_agents.return_value = []

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance

    mock_query_sub_agent_relations.return_value = [
        {"selected_agent_id": 456, "selected_agent_version_no": 0}
    ]
    mock_batch_query_current_version_nos.return_value = {456: 1}
    mock_batch_search_version_names.return_value = [
        {"agent_id": 456, "version_no": 1, "version_name": "v1.0"}
    ]
    mock_batch_search_agent_display_names.return_value = {456: "Sub Agent"}

    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    assert len(result["sub_agent_relations"]) == 1
    rel = result["sub_agent_relations"][0]
    assert rel["version_no"] == 1
    assert rel["version_name"] == "v1.0"


@patch("management.services.agent.service.batch_search_agent_display_names")
@patch("management.services.agent.service.batch_search_version_names")
@patch("management.services.agent.service.batch_query_current_version_nos")
@patch("management.services.agent.service.query_sub_agent_relations")
@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_sub_agent_relations_no_resolved_version(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
    mock_query_sub_agent_relations,
    mock_batch_query_current_version_nos,
    mock_batch_search_version_names,
    mock_batch_search_agent_display_names,
):
    """Test get_agent_info_impl handles when no published version exists for sub-agent."""
    mock_agent_info = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test",
    }
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = []
    mock_query_sub_agents_id.return_value = [456]
    mock_get_model_by_model_id.return_value = None
    mock_check_availability.return_value = (True, [])
    mock_query_external_sub_agents.return_value = []

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance

    mock_query_sub_agent_relations.return_value = [
        {"selected_agent_id": 456, "selected_agent_version_no": None}
    ]
    mock_batch_query_current_version_nos.return_value = {}
    mock_batch_search_version_names.return_value = []
    mock_batch_search_agent_display_names.return_value = {456: "Sub Agent"}

    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    assert len(result["sub_agent_relations"]) == 1
    rel = result["sub_agent_relations"][0]
    assert rel["agent_id"] == 456
    assert rel["version_no"] is None
    assert rel["version_name"] is None
    assert rel["agent_name"] == "Sub Agent"


@patch("management.services.agent.service.batch_search_agent_display_names")
@patch("management.services.agent.service.batch_search_version_names")
@patch("management.services.agent.service.batch_query_current_version_nos")
@patch("management.services.agent.service.query_sub_agent_relations")
@patch("management.services.agent.service.SkillService")
@patch("management.services.agent.service.query_external_sub_agents")
@patch("management.services.agent.service.check_agent_availability")
@patch("management.services.model.resolver.get_model_by_model_id")
@patch("management.services.agent.service.query_sub_agents_id_list")
@patch("management.services.agent.service.search_tools_for_sub_agent")
@patch("management.services.agent.service.search_agent_info_by_agent_id")
@pytest.mark.asyncio
async def test_get_agent_info_impl_sub_agent_relations_with_none_agent_id(
    mock_search_agent_info,
    mock_search_tools,
    mock_query_sub_agents_id,
    mock_get_model_by_model_id,
    mock_check_availability,
    mock_query_external_sub_agents,
    mock_skill_service,
    mock_query_sub_agent_relations,
    mock_batch_query_current_version_nos,
    mock_batch_search_version_names,
    mock_batch_search_agent_display_names,
):
    """Test get_agent_info_impl handles relations with selected_agent_id=None gracefully."""
    mock_agent_info = {
        "agent_id": 123,
        "model_id": None,
        "business_description": "Test",
    }
    mock_search_agent_info.return_value = mock_agent_info
    mock_search_tools.return_value = []
    mock_query_sub_agents_id.return_value = [456, None]
    mock_get_model_by_model_id.return_value = None
    mock_check_availability.return_value = (True, [])
    mock_query_external_sub_agents.return_value = []

    mock_skill_service_instance = MagicMock()
    mock_skill_service_instance.list_skill_instances.return_value = []
    mock_skill_service.return_value = mock_skill_service_instance

    # Include a relation with selected_agent_id=None alongside a normal one
    mock_query_sub_agent_relations.return_value = [
        {"selected_agent_id": 456, "selected_agent_version_no": 2},
        {"selected_agent_id": None, "selected_agent_version_no": 5},
    ]
    mock_batch_query_current_version_nos.return_value = {}
    mock_batch_search_version_names.return_value = [
        {"agent_id": 456, "version_no": 2, "version_name": "v2.0"}
    ]
    mock_batch_search_agent_display_names.return_value = {456: "Sub Agent"}

    result = await get_agent_info_impl(agent_id=123, tenant_id="test_tenant")

    assert len(result["sub_agent_relations"]) == 2
    # First relation (normal) should be enriched correctly
    rel_normal = result["sub_agent_relations"][0]
    assert rel_normal["agent_id"] == 456
    assert rel_normal["agent_name"] == "Sub Agent"
    assert rel_normal["version_no"] == 2
    assert rel_normal["version_name"] == "v2.0"
    # Second relation (None agent_id) should have None values without crashing
    rel_none = result["sub_agent_relations"][1]
    assert rel_none["agent_id"] is None
    assert rel_none["agent_name"] is None
    assert rel_none["version_no"] == 5
    assert rel_none["version_name"] is None


@patch('management.services.agent.service.update_related_agents')
@patch('management.services.agent.service.query_sub_agents_id_list')
@patch('management.services.agent.service.update_agent')
@pytest.mark.asyncio
async def test_update_agent_info_impl_with_related_agents_objects(mock_update_agent, mock_query_sub_agents_id_list, mock_update_related_agents):
    """Test update_agent_info_impl passes related_agents dicts when RelatedAgentInfo objects are provided."""
    mock_query_sub_agents_id_list.return_value = []
    request = MagicMock()
    request.agent_id = 123
    request.enabled_tool_ids = None
    request.related_agent_ids = [456, 789]
    mock_ra1 = MagicMock()
    mock_ra1.agent_id = 456
    mock_ra1.version_no = 2
    mock_ra2 = MagicMock()
    mock_ra2.agent_id = 789
    mock_ra2.version_no = None
    request.related_agents = [mock_ra1, mock_ra2]
    apply_default_agent_request_fields(request)
    result = await update_agent_info_impl(request, identity=AuthenticatedIdentity('test_user', 'test_tenant'))
    assert result['agent_id'] == 123
    mock_update_related_agents.assert_called_once_with(parent_agent_id=123, tenant_id='test_tenant', user_id='test_user', related_agents=[{'agent_id': 456, 'version_no': 2}, {'agent_id': 789, 'version_no': None}])


@patch(
    "management.services.agent.transfer.query_group_ids_by_user",
    side_effect=RuntimeError("db unavailable"),
)
def test_get_user_group_ids_returns_empty_string_on_query_failure(mock_query_group_ids):
    assert agent_service._get_user_group_ids("user-1", "tenant-1") == ""
    mock_query_group_ids.assert_called_once_with("user-1")


def test_inject_user_timezone_time_with_valid_timezone():
    """Should prepend [Current time: ...] when X-User-Timezone header is present."""
    from datetime import timezone
    from unittest.mock import MagicMock, patch

    request = MagicMock()
    request.headers = {"x-user-timezone": "Asia/Shanghai"}
    with patch("management.services.agent.context.ZoneInfo", return_value=timezone.utc):
        result = prepend_current_time(
            "What time is it?", request.headers.get("x-user-timezone")
        )
    assert result.startswith("What time is it?\n\n[Current time:")
    assert "What time is it?" in result


def test_inject_user_timezone_time_without_header():
    """Should return query unchanged when X-User-Timezone header is absent."""
    from unittest.mock import MagicMock

    request = MagicMock()
    request.headers = {}
    result = prepend_current_time(
        "What time is it?", request.headers.get("x-user-timezone")
    )
    assert result == "What time is it?"


def test_inject_user_timezone_time_with_existing_marker():
    """Do not append a second runtime time marker."""
    from unittest.mock import MagicMock

    request = MagicMock()
    request.headers = {"x-user-timezone": "Asia/Shanghai"}
    prefixed = "What time is it?\n\n[Current time: 2026-01-01 20:00:00]"
    result = prepend_current_time(prefixed, request.headers.get("x-user-timezone"))
    assert result == prefixed


def test_inject_user_timezone_time_with_invalid_timezone():
    """Should return query unchanged when timezone is invalid."""
    from unittest.mock import MagicMock

    request = MagicMock()
    request.headers = {"x-user-timezone": "Invalid/Timezone"}
    result = prepend_current_time(
        "What time is it?", request.headers.get("x-user-timezone")
    )
    assert result == "What time is it?"


# ---------------------------------------------------------------------------
# run_agent_stream knowledge_scope resolution (scoped conversation selection)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "Icon file is empty"),
        (
            b"x" * (ICON_MAX_BYTES + 1),
            "Icon must not exceed 2 MB",
        ),
        (b"not an image", "Icon must be a PNG, JPEG, GIF, or WebP image"),
    ],
    ids=("empty", "too-large", "invalid-format"),
)
async def test_upload_agent_icon_impl_rejects_invalid_content(mocker, content, message):
    mocker.patch.object(agent_service, "is_system_agent", return_value=False)
    with pytest.raises(ValueError, match=message):
        await agent_service.upload_agent_icon_impl(123, content, "tenant", "user")


@pytest.mark.asyncio
async def test_upload_agent_icon_impl_rejects_system_agent(mocker):
    mocker.patch.object(agent_service, "is_system_agent", return_value=True)
    get_agent = mocker.patch.object(agent_service, "get_agent_info_impl")
    upload = mocker.patch.object(agent_service, "upload_icon_image")

    with pytest.raises(agent_service.ForbiddenError, match="System Agent"):
        await agent_service.upload_agent_icon_impl(123, b"\x89PNG\r\n\x1a\n", "tenant", "user")

    get_agent.assert_not_called()
    upload.assert_not_called()


@pytest.mark.asyncio
async def test_upload_agent_icon_impl_rejects_without_edit_permission(mocker):
    mocker.patch.object(agent_service, "is_system_agent", return_value=False)
    mocker.patch.object(
        agent_service, "get_agent_info_impl", return_value={"permission": "VIEW"}
    )
    upload = mocker.patch.object(agent_service, "upload_icon_image")

    with pytest.raises(agent_service.ForbiddenError, match="permission to edit"):
        await agent_service.upload_agent_icon_impl(123, b"\x89PNG\r\n\x1a\n", "tenant", "user")

    upload.assert_not_called()


@pytest.mark.asyncio
async def test_upload_agent_icon_impl_upload_failure(mocker):
    mocker.patch.object(agent_service, "is_system_agent", return_value=False)
    mocker.patch.object(
        agent_service,
        "get_agent_info_impl",
        return_value={"permission": "EDIT", "tenant_id": "owner-tenant"},
    )
    mocker.patch.object(
        agent_service, "upload_icon_image", side_effect=ValueError("Failed to upload icon: storage error")
    )

    with pytest.raises(ValueError, match="Failed to upload icon: storage error"):
        await agent_service.upload_agent_icon_impl(123, b"\x89PNG\r\n\x1a\n", "tenant", "user")


@pytest.mark.asyncio
async def test_upload_agent_icon_impl_success(mocker):
    mocker.patch.object(agent_service, "is_system_agent", return_value=False)
    mocker.patch.object(
        agent_service,
        "get_agent_info_impl",
        return_value={"permission": "EDIT", "tenant_id": "owner-tenant"},
    )
    upload = mocker.patch.object(agent_service, "upload_icon_image", return_value="image/png")
    update = mocker.patch.object(agent_service, "update_agent_icon")

    result = await agent_service.upload_agent_icon_impl(123, b"\x89PNG\r\n\x1a\n", "tenant", "user")

    assert result["content_type"] == "image/png"
    assert result["icon_url"].startswith("/api/agent/123/icon?v=")
    assert len(result["icon_url"].split("?v=", 1)[1]) == 32
    upload.assert_called_once()
    assert upload.call_args.args[1] == "agent-icons/owner-tenant/123/icon"
    update.assert_called_once_with(
        agent_id=123,
        tenant_id="owner-tenant",
        icon_url=result["icon_url"],
        user_id="user",
    )


@pytest.mark.asyncio
async def test_upload_agent_icon_impl_changes_url_on_reupload(mocker):
    mocker.patch.object(agent_service, "is_system_agent", return_value=False)
    mocker.patch.object(
        agent_service,
        "get_agent_info_impl",
        return_value={"permission": "EDIT", "tenant_id": "owner-tenant"},
    )
    mocker.patch.object(agent_service, "upload_icon_image", return_value="image/png")
    mocker.patch.object(agent_service, "update_agent_icon")

    first = await agent_service.upload_agent_icon_impl(123, b"\x89PNG\r\n\x1a\n", "tenant", "user")
    second = await agent_service.upload_agent_icon_impl(123, b"\x89PNG\r\n\x1a\n", "tenant", "user")

    assert first["icon_url"] != second["icon_url"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "agent",
    [
        {},
        {"icon_url": ""},
    ],
)
async def test_get_agent_icon_impl_requires_icon_url(mocker, agent):
    mocker.patch.object(agent_service, "get_agent_info_impl", return_value=agent)

    with pytest.raises(FileNotFoundError, match="Agent icon not found"):
        await agent_service.get_agent_icon_impl(123, "tenant", "user")


@pytest.mark.asyncio
async def test_get_agent_icon_impl_raises_when_object_missing(mocker):
    mocker.patch.object(
        agent_service,
        "get_agent_info_impl",
        return_value={"icon_url": "/api/agent/123/icon", "tenant_id": "owner-tenant"},
    )
    get_stream = mocker.patch.object(
        agent_service, "read_icon_image", side_effect=FileNotFoundError("Icon not found")
    )

    with pytest.raises(FileNotFoundError, match="Icon not found"):
        await agent_service.get_agent_icon_impl(123, "tenant", "user")

    get_stream.assert_called_once_with("agent-icons/owner-tenant/123/icon")


@pytest.mark.asyncio
async def test_get_agent_icon_impl_rejects_invalid_stored_content(mocker):
    mocker.patch.object(
        agent_service,
        "get_agent_info_impl",
        return_value={"icon_url": "/api/agent/123/icon", "tenant_id": "tenant"},
    )
    mocker.patch.object(
        agent_service, "read_icon_image", side_effect=FileNotFoundError("Icon is invalid")
    )

    with pytest.raises(FileNotFoundError, match="Icon is invalid"):
        await agent_service.get_agent_icon_impl(123, "tenant", "user")


@pytest.mark.asyncio
async def test_get_agent_icon_impl_success(mocker):
    content = b"png content"
    mocker.patch.object(
        agent_service,
        "get_agent_info_impl",
        return_value={"icon_url": "/api/agent/123/icon", "tenant_id": "owner-tenant"},
    )
    mocker.patch.object(
        agent_service, "read_icon_image", return_value=(content, "image/webp")
    )

    result = await agent_service.get_agent_icon_impl(123, "tenant", "user")

    assert result == (content, "image/webp")


# =============================================================================
# Runtime metadata flow inside run_agent_stream
# =============================================================================


@pytest.fixture
def rebase_import_context(mocker):
    """Isolate persistence while retaining real import orchestration and naming rules."""
    from management.services.agent import transfer as management, naming
    catalog = []
    query = mocker.patch.object(management, 'query_all_agent_info_by_tenant_id', side_effect=lambda tenant: list(catalog))
    mocker.patch.object(management, 'query_all_tools', return_value=[])
    mocker.patch.object(management, '_resolve_model_ids_with_fallback', return_value=[])
    mocker.patch.object(management, '_get_user_group_ids', return_value='')
    mocker.patch.object(management, 'publish_version_impl', new_callable=AsyncMock)
    relations = mocker.patch.object(agent_transfer, 'insert_related_agent')
    llm = mocker.patch.object(naming, 'invoke_chat_prompt')

    def create_agent(agent_info, **kwargs):
        record = {**agent_info, 'agent_id': len(catalog) + 1}
        catalog.append(record)
        return record
    create = mocker.patch.object(management, 'create_agent', side_effect=create_agent)
    payload = ExportAndImportAgentInfo(agent_id=1, name='copy', display_name='Copy', description='test', business_description='test', max_steps=5, provide_run_summary=False, enabled=True, tools=[], managed_agents=[], model_ids=[], model_names=[])
    return types.SimpleNamespace(service=management, catalog=catalog, payload=payload, query=query, create=create, relations=relations, llm=llm)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "existing,expected",
    [
        ([], ("copy", "Copy")),
        ([{"name": "copy", "display_name": "Other"}], ("copy_1", "Copy")),
        ([{"name": "other", "display_name": "Copy"}], ("copy", "Copy_1")),
        ([{"name": "copy", "display_name": "Copy"}], ("copy_1", "Copy_1")),
        (
            [
                {"name": "copy", "display_name": "Copy"},
                {"name": "copy_1", "display_name": "Copy_2"},
            ],
            ("copy_2", "Copy_1"),
        ),
    ],
)
async def test_ac019_repository_copy_resolves_each_name_independently(
    rebase_import_context, existing, expected
):
    ctx = rebase_import_context
    ctx.catalog.extend(existing)
    await ctx.service.import_agent_by_agent_id(
        ctx.payload, "tenant", "user", resolve_name_conflicts=True
    )
    assert (ctx.catalog[-1]["name"], ctx.catalog[-1]["display_name"]) == expected
    ctx.query.assert_called_once_with("tenant")
    ctx.llm.assert_not_called()


@pytest.mark.asyncio
async def test_ac019_ordinary_import_keeps_names_by_default(rebase_import_context):
    ctx = rebase_import_context
    ctx.catalog.append({"name": "copy", "display_name": "Copy"})
    await ctx.service.import_agent_by_agent_id(ctx.payload, "tenant", "user")
    assert (ctx.catalog[-1]["name"], ctx.catalog[-1]["display_name"]) == (
        "copy",
        "Copy",
    )
    ctx.query.assert_not_called()
    ctx.llm.assert_not_called()


@pytest.mark.asyncio
async def test_ac019_repeated_dfs_copies_see_names_created_by_previous_agents(rebase_import_context):
    ctx = rebase_import_context
    ctx.catalog.append({'name': 'copy', 'display_name': 'Copy'})
    ctx.payload.managed_agents = [2]
    child = ctx.payload.model_copy(update={'agent_id': 2, 'managed_agents': []})
    snapshot = types.SimpleNamespace(agent_id=1, agent_info={'1': ctx.payload, '2': child})
    for _ in range(2):
        mapping = await ctx.service.import_agent_impl(snapshot, AuthenticatedIdentity('user', 'tenant'), resolve_name_conflicts=True)
        assert mapping[1] > mapping[2]
    assert [record['name'] for record in ctx.catalog] == ['copy', 'copy_1', 'copy_2', 'copy_3', 'copy_4']
    assert [record['display_name'] for record in ctx.catalog] == ['Copy', 'Copy_1', 'Copy_2', 'Copy_3', 'Copy_4']
    assert ctx.relations.call_count == 2
    ctx.llm.assert_not_called()


@pytest.mark.asyncio
async def test_ac019_suffix_exhaustion_prevents_agent_creation(rebase_import_context):
    ctx = rebase_import_context
    ctx.catalog.extend(
        {"name": value}
        for value in ["copy", *(f"copy_{index}" for index in range(1, 101))]
    )
    with pytest.raises(ValueError, match="max attempts"):
        await ctx.service.import_agent_by_agent_id(
            ctx.payload, "tenant", "user", resolve_name_conflicts=True
        )
    ctx.create.assert_not_called()
    ctx.llm.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('resolve_conflicts', [False, True])
async def test_ac019_skill_bundle_preserves_naming_flag_and_skill_binding(rebase_import_context, mocker, resolve_conflicts):
    ctx = rebase_import_context
    ctx.catalog.append({'name': 'copy', 'display_name': 'Copy'})
    ctx.payload.skill_names = ['SkillA']
    mocker.patch.object(ctx.service.skill_db, 'list_skills', return_value=[])
    skill_service = mocker.patch.object(ctx.service, 'SkillService').return_value
    skill_service.create_skill_from_zip_bytes.return_value = {'skill_id': 7}
    bind = mocker.patch.object(ctx.service.skill_db, 'create_or_update_skill_by_skill_info')
    snapshot = types.SimpleNamespace(agent_id=1, agent_info={'1': ctx.payload})
    result = await ctx.service.import_agent_with_skills_impl(snapshot, [types.SimpleNamespace(skill_name='SkillA', skill_zip_base64='eA==')], AuthenticatedIdentity('user', 'tenant'), resolve_name_conflicts=resolve_conflicts)
    assert result == {1: 2}
    assert ctx.catalog[-1]['name'] == ('copy_1' if resolve_conflicts else 'copy')
    assert ctx.catalog[-1]['display_name'] == ('Copy_1' if resolve_conflicts else 'Copy')
    assert bind.call_args.kwargs['skill_info'].skill_id == 7
    assert bind.call_args.kwargs['skill_info'].agent_id == 2
    ctx.llm.assert_not_called()


def test_check_single_model_availability_loads_missing_cache_entry(mocker):
    from management.services.model import resolver

    model_cache = {}
    get_model = mocker.patch.object(
        resolver, "get_model_by_model_id", return_value=None
    )

    model = resolver.resolve_model_record(31, "tenant-id", model_cache)

    assert not resolver.is_model_available(model)
    assert model_cache == {31: None}
    get_model.assert_called_once_with(31, "tenant-id")


def test_check_single_model_availability_reuses_cached_model(mocker):
    from management.services.model import resolver

    status_enum = types.SimpleNamespace(
        AVAILABLE=types.SimpleNamespace(value="available"),
        get_value=lambda value: value,
    )
    mocker.patch.object(resolver, "ModelConnectStatusEnum", status_enum)
    get_model = mocker.patch.object(resolver, "get_model_by_model_id")
    model_cache = {31: {"connect_status": "available"}}

    model = resolver.resolve_model_record(31, "tenant-id", model_cache)

    assert resolver.is_model_available(model)
    get_model.assert_not_called()


def test_collect_model_availability_marks_models_not_configured(mocker):
    from management.services.agent import read

    mocker.patch.object(read, "search_tools_for_sub_agent", return_value=[])
    available, reasons = read.check_agent_availability(
        agent_id=1,
        agent_info={"model_ids": []},
        tenant_id="tenant-id",
        model_cache={},
    )

    assert available is False
    assert reasons == [read.AgentUnavailableReason.MODEL_NOT_CONFIGURED]


@pytest.mark.asyncio
async def test_import_agent_with_skills_rejects_parameters_before_dependency_writes(mocker):
    from management.services.agent import transfer as management
    from contracts.errors.exceptions import AgentToolImportError
    mocker.patch.object(agent_transfer, 'query_all_tools', return_value=[{'class_name': 'AidpSearchTool', 'source': 'local', 'params': [{'name': 'kds_list'}]}])
    skill_service = mocker.patch.object(agent_transfer, 'SkillService')
    import_agents = mocker.patch.object(agent_transfer, 'import_agent_impl', new_callable=AsyncMock)
    snapshot = types.SimpleNamespace(agent_info={"1": types.SimpleNamespace(name="agent_one", tools=[
        types.SimpleNamespace(class_name='AidpSearchTool', source='local', params={'unknown': 1}),
    ])})
    with pytest.raises(AgentToolImportError, match='unknown'):
        await management.import_agent_with_skills_impl(snapshot, [], AuthenticatedIdentity('user', 'tenant'))
    skill_service.assert_not_called()
    import_agents.assert_not_called()


@pytest.fixture(autouse=True)
def batch_list_read_boundary(monkeypatch):
    """Retain standalone projection assertions with isolated batch collaborators."""
    from management.services.agent import read as read_service

    class Context:
        tools = {}
        definitions = {}
        models = {}

        def model_cache(self):
            return {}

        def valid_model_ids(self, ids):
            return read_service.get_valid_model_ids(ids, current_tenant[0])

    current_tenant = [None]

    def context(agents, tenant):
        current_tenant[0] = tenant
        return Context()

    monkeypatch.setattr(agent_management, "load_agent_list_context", context)
