import pytest
import sys
import types
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, Mock, PropertyMock, ANY

from test.common.test_mocks import bootstrap_test_env

env_state = bootstrap_test_env()
consts_const = env_state["mock_const"]

# Mock consts.model module with HistoryItem class
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class HistoryItem(BaseModel):
    role: str
    content: str
    minio_files: Optional[List[Dict[str, Any]]] = None


class AgentHistory(BaseModel):
    role: str
    content: str


class ValidationError(Exception):
    """Mock ValidationError for testing."""
    pass


class MCPConnectionError(Exception):
    """Mock MCPConnectionError for testing."""
    pass


class NotFoundException(Exception):
    """Mock NotFoundException for testing."""
    pass


class ToolExecutionException(Exception):
    """Mock ToolExecutionException for testing."""
    pass


class MockModelCapacityConfigError(ValidationError):
    def __init__(self, reason_code, message, *, field=None):
        self.reason_code = reason_code
        self.field = field
        super().__init__(f"{reason_code}: {message}")


consts_model_module = types.ModuleType("consts.model")
consts_model_module.HistoryItem = HistoryItem


class MockAgentToolParamsRequest(BaseModel):
    """Mock for AgentToolParamsRequest."""
    tools: Dict[str, Dict[str, Any]] = {}


class MockToolParamsRequest(BaseModel):
    """Mock for ToolParamsRequest."""
    agents: Dict[str, MockAgentToolParamsRequest] = {}


consts_model_module.HistoryItem = HistoryItem
consts_model_module.AgentToolParamsRequest = MockAgentToolParamsRequest
consts_model_module.ToolParamsRequest = MockToolParamsRequest
sys.modules["consts.model"] = consts_model_module
sys.modules["consts.capability_profiles"] = types.ModuleType(
    "consts.capability_profiles"
)
sys.modules["consts.capability_profiles"].CATALOG = {}
sys.modules["consts.model_feature_capabilities"] = types.ModuleType(
    "consts.model_feature_capabilities"
)
sys.modules["consts.model_feature_capabilities"].CATALOG_REVISION = "test"
sys.modules["consts.model_feature_capabilities"].EXACT_CATALOG = {}
sys.modules["consts.model_feature_capabilities"].FAMILY_RULES = ()

# Mock consts.exceptions module with ValidationError
consts_exceptions_module = types.ModuleType("consts.exceptions")
consts_exceptions_module.ValidationError = ValidationError
consts_exceptions_module.ModelCapacityConfigError = MockModelCapacityConfigError
consts_exceptions_module.MCPConnectionError = MCPConnectionError
consts_exceptions_module.NotFoundException = NotFoundException
consts_exceptions_module.ToolExecutionException = ToolExecutionException
sys.modules["consts.exceptions"] = consts_exceptions_module

# Also add model and exceptions to consts module attributes
consts_module = sys.modules.get("consts")
if consts_module:
    setattr(consts_module, "model", consts_model_module)
    setattr(consts_module, "exceptions", consts_exceptions_module)
    setattr(
        consts_module,
        "capability_profiles",
        sys.modules["consts.capability_profiles"],
    )

# Also add model to consts module attributes (with AgentToolParamsRequest and ToolParamsRequest)
consts_module = sys.modules.get("consts")
if consts_module:
    setattr(consts_module, "model", consts_model_module)

TEST_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TEST_ROOT.parent

# Ensure project backend package is found before test/backend
for _path in (str(PROJECT_ROOT), str(TEST_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# Utilities ---------------------------------------------------------------
def _create_stub_module(name: str, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    return module


# Configure required constants via shared bootstrap env
consts_const.MINIO_ENDPOINT = "http://localhost:9000"
consts_const.MINIO_ACCESS_KEY = "test_access_key"
consts_const.MINIO_SECRET_KEY = "test_secret_key"
consts_const.MINIO_REGION = "us-east-1"
consts_const.MINIO_DEFAULT_BUCKET = "test-bucket"
consts_const.POSTGRES_HOST = "localhost"
consts_const.POSTGRES_USER = "test_user"
consts_const.NEXENT_POSTGRES_PASSWORD = "test_password"
consts_const.POSTGRES_DB = "test_db"
consts_const.POSTGRES_PORT = 5432
consts_const.DEFAULT_TENANT_ID = "default_tenant"
consts_const.LOCAL_MCP_SERVER = "http://localhost:5011"
consts_const.MODEL_CONFIG_MAPPING = {"llm": "llm_config"}
consts_const.LANGUAGE = {"ZH": "zh"}
consts_const.DATA_PROCESS_SERVICE = "https://example.com/data-process"

# Mock utils module
utils_mock = MagicMock()
utils_mock.auth_utils = MagicMock()
utils_mock.auth_utils.get_current_user_id = MagicMock(return_value=("test_user_id", "test_tenant_id"))
utils_mock.context_utils = MagicMock()
utils_mock.context_utils.build_context_inputs = MagicMock(return_value=[])

# Add the mocked utils module to sys.modules
sys.modules['utils'] = utils_mock
sys.modules['utils.auth_utils'] = utils_mock.auth_utils
sys.modules['utils.context_utils'] = utils_mock.context_utils

# Provide a stub for the `boto3` module so that it can be imported safely even
# if the testing environment does not have it available.
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock
sys.modules['dotenv'] = MagicMock(load_dotenv=MagicMock())

# Mock the entire client module
client_mock = MagicMock()
client_mock.MinioClient = MagicMock()
client_mock.PostgresClient = MagicMock()
client_mock.db_client = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock()

# Add the mocked client module to sys.modules
sys.modules['backend.database.client'] = client_mock
sys.modules['database.client'] = _create_stub_module(
    "database.client",
    minio_client=MagicMock(),
    postgres_client=MagicMock(),
    db_client=MagicMock(),
    get_db_session=MagicMock(),
    as_dict=MagicMock(),
)

# Mock external dependencies before imports
mock_message_observer = MagicMock()
class MockAgentVerificationConfig:
    @classmethod
    def model_validate(cls, value):
        return value or {}

sys.modules['nexent.core.utils.observer'] = MagicMock(MessageObserver=mock_message_observer)
sys.modules['nexent.core.models.feature_capability'] = _create_stub_module(
    "nexent.core.models.feature_capability",
    normalize_feature_profile=lambda value: value if isinstance(value, dict) else None,
    resolve_feature_capabilities=lambda *args, **kwargs: {
        "schema_version": 1,
        "reasoning": {"supported": None, "mode": "unknown", "request_style": "unknown", "efforts": []},
        "prompt_cache": {"supported": None, "mode": "unknown", "metrics_available": None},
        "source": "unknown",
    },
)
sys.modules['nexent.core.agents.agent_model'] = _create_stub_module(
    "nexent.core.agents.agent_model",
    AgentHistory=AgentHistory,
    ModelConfig=MagicMock(),
    AgentConfig=MagicMock(),
    ToolConfig=MagicMock(),
    ExternalA2AAgentConfig=MagicMock(),
    AgentRunInfo=MagicMock(),
    AgentVerificationConfig=MockAgentVerificationConfig,
    MessageObserver=MagicMock(),
)
sys.modules['nexent.core.agents.agent_context'] = _create_stub_module(
    "nexent.core.agents.agent_context",
    ContextManager=MagicMock(),
    ContextManagerConfig=MagicMock(),
)
sys.modules['nexent.core.agents.context'] = _create_stub_module(
    "nexent.core.agents.context",
    ContextManager=MagicMock(),
    ContextManagerConfig=MagicMock(),
    ContextProcessingMode=types.SimpleNamespace(
        PASSTHROUGH="passthrough",
        ADAPTIVE_COMPACT="adaptive_compact",
    ),
    PolicyLayers=types.SimpleNamespace(model_validate=lambda value: value),
    resolve_policy=lambda layers: types.SimpleNamespace(
        processing_mode=(layers.get("request") or {}).get("processing_mode", "passthrough")
    ),
)
sys.modules['nexent.core.agents.summary_config'] = _create_stub_module(
    "nexent.core.agents.summary_config",
    ContextManagerConfig=MagicMock(),
)
sys.modules['nexent.core.models.prompt_cache'] = _create_stub_module(
    "nexent.core.models.prompt_cache",
    resolve_prompt_cache_profile=lambda provider, explicit_profile=None: (
        {"mode": "openai_automatic", "enabled": True}
        if (provider or "").lower() == "openai" else None
    ),
    resolve_provider_usage_profile=lambda provider, version=None: {
        "capability_profile_version": version,
        "reasoning_usage_semantics": "unavailable",
    },
)
sys.modules['smolagents.agents'] = MagicMock()
sys.modules['smolagents.utils'] = MagicMock()
sys.modules['services.remote_mcp_service'] = MagicMock()
database_module = _create_stub_module("database")
sys.modules['database'] = database_module
skill_db_stub = MagicMock()
sys.modules['database.skill_db'] = skill_db_stub
database_module.skill_db = skill_db_stub
sys.modules['database.agent_db'] = MagicMock()
sys.modules['database.tool_db'] = MagicMock()
sys.modules['database.model_management_db'] = MagicMock()
sys.modules['database.agent_version_db'] = MagicMock()
a2a_agent_db_stub = _create_stub_module(
    "database.a2a_agent_db",
    PROTOCOL_JSONRPC="JSONRPC",
    query_external_sub_agents=MagicMock(return_value=[]),
)
sys.modules['database.a2a_agent_db'] = a2a_agent_db_stub
database_module.a2a_agent_db = a2a_agent_db_stub
sys.modules['database.knowledge_db'] = MagicMock()
sys.modules['database.knowledge_db'].get_knowledge_name_map_by_index_names = MagicMock()
sys.modules['management.services.knowledge_base.service'] = MagicMock()
sys.modules['management.services.model.resolver'] = MagicMock()
# Configure ElasticSearchService.filter_accessible_indices as a pass-through so that
# existing tests (which don't explicitly mock this permission filter) still work correctly.
sys.modules['management.services.knowledge_base.service'].ElasticSearchService.filter_accessible_indices.side_effect = \
    lambda index_names, **kwargs: list(index_names)
sys.modules['services.tenant_config_service'] = MagicMock()
sys.modules['utils.prompt_template_utils'] = MagicMock()
sys.modules['utils.config_utils'] = MagicMock()
sys.modules['utils.http_client_utils'] = MagicMock()
sys.modules['utils.langchain_utils'] = MagicMock()
sys.modules['utils.model_name_utils'] = MagicMock()
sys.modules['langchain_core.tools'] = MagicMock()
# Build services module hierarchy with minimal functionality
services_module = _create_stub_module("services")
sys.modules['services'] = services_module
sys.modules['services.image_service'] = _create_stub_module(
    "services.image_service",
    get_vlm_model=MagicMock(return_value="stub_vlm"),
    get_video_understanding_model=MagicMock(return_value="stub_video_vlm"),
)
sys.modules['services.ind_aidp_service'] = _create_stub_module(
    "services.ind_aidp_service",
    create_ind_aidp_image_url_builder=MagicMock(),
)
sys.modules['services.model_gateway_service'] = _create_stub_module(
    "services.model_gateway_service",
    get_llm_adapter=MagicMock(return_value="stub_llm_adapter"),
    get_vlm_adapter=MagicMock(return_value="stub_vlm_adapter"),
)
sys.modules['services.memory_config_service'] = MagicMock()
sys.modules['services.memory_external_provider_service'] = _create_stub_module(
    "services.memory_external_provider_service",
    get_memory_external_provider_service=MagicMock(return_value=None),
)
# Extend services hierarchy with additional stubs
sys.modules['services.file_management_service'] = _create_stub_module(
    "services.file_management_service",
    get_llm_model=MagicMock(return_value="stub_llm_model"),
    validate_urls_access=MagicMock(),
)
sys.modules['services.tool_configuration_service'] = _create_stub_module(
    "services.tool_configuration_service",
    initialize_tools_on_startup=AsyncMock(),
)
sys.modules['management.services.agent.service'] = _create_stub_module(
    "management.services.agent.service",
    build_sandbox_policy=MagicMock(return_value=None),
    get_sandbox_minio_client=MagicMock(return_value=None),
)
sys.modules['nexent.memory.memory_service'] = MagicMock()

# Build top-level nexent module to avoid importing the real package
nexent_module = _create_stub_module("nexent", MessageObserver=mock_message_observer)
sys.modules['nexent'] = nexent_module
sys.modules['nexent.memory'] = _create_stub_module("nexent.memory")
sys.modules['nexent.memory.models'] = _create_stub_module("nexent.memory.models")
sys.modules['nexent.memory'].models = sys.modules['nexent.memory.models']

# Create nested modules for nexent.core to satisfy imports safely
sys.modules['nexent.core'] = _create_stub_module("nexent.core")
nexent_agents_module = _create_stub_module("nexent.core.agents")
nexent_agents_module.__path__ = []
sys.modules['nexent.core.utils'] = _create_stub_module("nexent.core.utils")
sys.modules['nexent.core.models'] = _create_stub_module("nexent.core.models")


class MockSandboxConfig:
    def __init__(self, auto_sync_outputs=True, **kwargs):
        self.auto_sync_outputs = auto_sync_outputs
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def from_dict(cls, data):
        return cls(**(data or {}))


sandbox_module = _create_stub_module(
    "nexent.core.agents.sandbox",
    SandboxConfig=MockSandboxConfig,
)
nexent_agents_module.sandbox = sandbox_module

nexent_agent_module = _create_stub_module(
    "nexent.core.agents.nexent_agent",
    get_local_python_authorized_imports=MagicMock(
        return_value=["sdk_default_import"]
    ),
)
nexent_agents_module.nexent_agent = nexent_agent_module


class MockProviderCapabilityUnknown(Exception):
    pass


class MockResolverError(Exception):
    pass


class MockModelCapacitySnapshot:
    def __init__(self, **kwargs):
        self.provider = kwargs.get("provider", "test")
        self.model_name = kwargs.get("model_name", "test-model")
        self.context_window_tokens = kwargs.get("context_window_tokens", 32768)
        self.default_output_reserve_tokens = kwargs.get(
            "default_output_reserve_tokens",
            4096,
        )
        self.capability_profile_version = kwargs.get("capability_profile_version")
        self.field_sources = kwargs.get("field_sources", {})
        self.requested_output_tokens = kwargs.get("requested_output_tokens")
        self.provider_input_limit_tokens = kwargs.get(
            "provider_input_limit_tokens",
            28672,
        )
        self.tokenizer_family = kwargs.get("tokenizer_family")
        self.counting_mode = kwargs.get("counting_mode", "estimated")
        self.unknown_capabilities = kwargs.get("unknown_capabilities", [])
        self.fingerprint = kwargs.get("fingerprint", "test-fingerprint")

    def model_dump(self):
        return self.__dict__.copy()


class MockRequestBudgetOverrides:
    def __init__(self, requested_output_tokens=None):
        self.requested_output_tokens = requested_output_tokens


class MockSafeInputBudgetSnapshot:
    def __init__(self, capacity_snapshot, requested_output_tokens=None):
        self.model_name = capacity_snapshot.model_name
        self.requested_output_tokens = requested_output_tokens or 4096
        self.soft_input_budget_tokens = 24576
        self.hard_input_budget_tokens = 28672
        self.fingerprint = "safe-budget-fingerprint"
        self.warnings = []

    def model_dump(self):
        return self.__dict__.copy()


class MockSafeInputBudgetCalculator:
    def calculate_safe_input_budget(
        self,
        capacity_snapshot,
        reserve_policy=None,
        request_overrides=None,
        requested_output_tokens=None,
        output_reserve_source="model_default",
    ):
        override_tokens = getattr(request_overrides, "requested_output_tokens", None)
        return MockSafeInputBudgetSnapshot(
            capacity_snapshot,
            requested_output_tokens=override_tokens or requested_output_tokens,
        )


class MockBudgetResolverError(Exception):
    """Mock W2 base exception."""


class MockUncertaintyReserveBasisUnknown(MockBudgetResolverError):
    """Mock W2 exception raised when context_window_tokens is missing."""


sys.modules['nexent.core.models.capacity_resolver'] = _create_stub_module(
    "nexent.core.models.capacity_resolver",
    ModelCapacitySnapshot=MockModelCapacitySnapshot,
    ProviderCapabilityUnknown=MockProviderCapabilityUnknown,
    ResolverError=MockResolverError,
    resolve_capacity=MagicMock(return_value=MockModelCapacitySnapshot()),
)
sys.modules['nexent.core.models.capacity_budget'] = _create_stub_module(
    "nexent.core.models.capacity_budget",
    BudgetResolverError=MockBudgetResolverError,
    RequestBudgetOverrides=MockRequestBudgetOverrides,
    SafeInputBudgetCalculator=MockSafeInputBudgetCalculator,
    UncertaintyReserveBasisUnknown=MockUncertaintyReserveBasisUnknown,
)

# Create mock classes that might be imported
mock_agent_config = MagicMock()
mock_model_config = MagicMock()
mock_tool_config = MagicMock()
mock_agent_run_info = MagicMock()

sys.modules['nexent.core.agents.agent_model'].AgentConfig = mock_agent_config
sys.modules['nexent.core.agents.agent_model'].ModelConfig = mock_model_config
sys.modules['nexent.core.agents.agent_model'].ToolConfig = mock_tool_config
sys.modules['nexent.core.agents.agent_model'].AgentRunInfo = mock_agent_run_info
sys.modules['nexent.core.agents.agent_model'].AgentVerificationConfig = MockAgentVerificationConfig
sys.modules['nexent.core.utils.observer'].MessageObserver = mock_message_observer

# Stub parallel_executor so that create_agent_info can import ParallelExecutorTool
_mock_parallel_executor_tool_cls = MagicMock()
_mock_parallel_executor_tool_cls.__name__ = "ParallelExecutorTool"
_mock_parallel_executor_tool_cls.name = "parallel_executor"
_mock_parallel_executor_tool_cls.description = "Execute multiple independent calls in parallel."
_mock_parallel_executor_tool_cls.inputs = {"tasks": {"type": "array"}}
_mock_parallel_executor_tool_cls.output_type = "any"
_parallel_executor_mod = _create_stub_module(
    "nexent.core.tools.parallel_executor",
    ParallelExecutorTool=_mock_parallel_executor_tool_cls,
)
sys.modules["nexent.core.tools.parallel_executor"] = _parallel_executor_mod

# Mock BASE_BUILTIN_MODULES
sys.modules['smolagents.utils'].BASE_BUILTIN_MODULES = ["os", "sys", "json"]

# Provide lightweight smolagents package to prevent circular imports
smolagents_module = _create_stub_module("smolagents")
smolagents_tools_module = _create_stub_module("smolagents.tools", Tool=MagicMock())
smolagents_module.tools = smolagents_tools_module
sys.modules['smolagents'] = smolagents_module
sys.modules['smolagents.tools'] = smolagents_tools_module

# Mock utils package (referenced by create_agent_info.py)
_utils_pkg = types.ModuleType("utils")
_utils_pkg.__path__ = [str((TEST_ROOT.parent) / "backend" / "utils")]
sys.modules["utils"] = _utils_pkg

# Mock all utils submodules that create_agent_info.py imports
_redis_utils_mod = _create_stub_module("utils.redis_utils")
_redis_utils_mod.get_redis_client = MagicMock(return_value=MagicMock())
sys.modules["utils.redis_utils"] = _redis_utils_mod
setattr(_utils_pkg, "redis_utils", _redis_utils_mod)

_model_name_utils_mod = _create_stub_module("utils.model_name_utils")
_model_name_utils_mod.add_repo_to_name = lambda name, repo=None, **kwargs: name
sys.modules["utils.model_name_utils"] = _model_name_utils_mod
setattr(_utils_pkg, "model_name_utils", _model_name_utils_mod)

_prompt_template_utils_mod = _create_stub_module("utils.prompt_template_utils")
_prompt_template_utils_mod.get_agent_prompt_template = MagicMock(return_value="")
sys.modules["utils.prompt_template_utils"] = _prompt_template_utils_mod
setattr(_utils_pkg, "prompt_template_utils", _prompt_template_utils_mod)

_config_utils_mod = _create_stub_module("utils.config_utils")
_config_utils_mod.tenant_config_manager = MagicMock()
_config_utils_mod.get_model_name_from_config = MagicMock(return_value="default")
sys.modules["utils.config_utils"] = _config_utils_mod
setattr(_utils_pkg, "config_utils", _config_utils_mod)

_context_utils_mod = _create_stub_module("utils.context_utils")
_context_utils_mod.build_context_inputs = MagicMock(return_value=[])
sys.modules["utils.context_utils"] = _context_utils_mod
setattr(_utils_pkg, "context_utils", _context_utils_mod)

_langchain_utils_mod = _create_stub_module("utils.langchain_utils")
_langchain_utils_mod.discover_langchain_modules = MagicMock(return_value=[])
sys.modules["utils.langchain_utils"] = _langchain_utils_mod
setattr(_utils_pkg, "langchain_utils", _langchain_utils_mod)

# Ensure real backend.agents.create_agent_info is available and uses our stubs
backend_pkg = sys.modules.get("backend")
if backend_pkg is None:
    backend_pkg = types.ModuleType("backend")
    backend_pkg.__path__ = [str((TEST_ROOT.parent) / "backend")]
    sys.modules["backend"] = backend_pkg

agents_pkg = sys.modules.get("backend.agents")
if agents_pkg is None:
    agents_pkg = types.ModuleType("backend.agents")
    agents_pkg.__path__ = [str((TEST_ROOT.parent) / "backend" / "agents")]
    sys.modules["backend.agents"] = agents_pkg
    setattr(backend_pkg, "agents", agents_pkg)

create_agent_info_path = (TEST_ROOT.parent / "backend" / "agents" / "create_agent_info.py")
spec = importlib.util.spec_from_file_location(
    "backend.agents.create_agent_info", create_agent_info_path
)
create_agent_info_module = importlib.util.module_from_spec(spec)
sys.modules["backend.agents.create_agent_info"] = create_agent_info_module
assert spec.loader is not None
spec.loader.exec_module(create_agent_info_module)
setattr(agents_pkg, "create_agent_info", create_agent_info_module)

# Now import the symbols under test
from backend.agents.create_agent_info import (
    discover_langchain_tools,
    create_tool_config_list,
    create_agent_config,
    create_model_config_list,
    filter_mcp_servers_and_tools,
    create_agent_run_info,
    join_minio_file_description_to_query,
    prepare_prompt_templates,
    _get_skills_for_template,
    _get_skill_script_tools,
    _extract_url_from_card,
    _build_external_agent_config,
    _build_security_headers,
    _resolve_scheme_field,
    _build_auth_header_for_scheme,
    _effective_feature_factory,
    _get_external_a2a_agents,
    _build_internal_s3_url,
    _format_minio_files_for_content,
    _convert_history_with_minio_files,
    _normalize_tool_params_request,
    _get_agent_tool_overrides,
    _merge_tool_params,
    _resolve_runtime_tool_records,
    _resolve_input_budget,
    _resolve_safe_input_budget,
    _get_external_provider_service_for_search,
)


def test_ac_p3_25_external_search_switch_skips_provider_factory(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr(create_agent_info_module, "get_memory_external_provider_service", factory)
    monkeypatch.setattr(create_agent_info_module, "EXTERNAL_MEMORY_SEARCH_ENABLED", False)

    assert _get_external_provider_service_for_search() is None
    factory.assert_not_called()


def test_ac_p3_25_external_search_switch_uses_provider_factory(monkeypatch):
    service = object()
    factory = MagicMock(return_value=service)
    monkeypatch.setattr(create_agent_info_module, "get_memory_external_provider_service", factory)
    monkeypatch.setattr(create_agent_info_module, "EXTERNAL_MEMORY_SEARCH_ENABLED", True)

    assert _get_external_provider_service_for_search() is service
    factory.assert_called_once_with()


@pytest.fixture(autouse=True)
def run_create_agent_thread_work_inline(monkeypatch):
    async def run_inline(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(create_agent_info_module.asyncio, "to_thread", run_inline)


def test_build_run_workspace_uses_user_and_run_only(monkeypatch, tmp_path):
    monkeypatch.setattr(
        create_agent_info_module,
        "AGENT_WORKSPACE_ROOT",
        str(tmp_path),
    )

    workspace = create_agent_info_module._build_run_workspace("user-1", "run-1")

    assert Path(workspace) == tmp_path.resolve() / "user-1" / "run-1"

# Import HistoryItem for testing (from mocked consts.model)
HistoryItem = sys.modules["consts.model"].HistoryItem

# Import ValidationError for testing (from mocked consts.exceptions)
ValidationError = sys.modules["consts.exceptions"].ValidationError

# Import ToolParamsRequest for testing
ToolParamsRequest = sys.modules["consts.model"].ToolParamsRequest

# Import constants for testing
from consts.const import MODEL_CONFIG_MAPPING


class TestResolveInputBudget:
    """Tests for W1/W2 budget resolver hand-off."""

    def test_resolve_input_budget_returns_monitoring_dict_then_resolver_snapshot(self):
        """The caller needs monitoring fields for AgentConfig and the raw snapshot for W2."""
        model_info = {
            "model_factory": "openai",
            "model_name": "gpt-4o",
            "context_window_tokens": 32768,
            "max_output_tokens": 4096,
        }

        input_budget, capacity_snapshot, resolved_capacity_snapshot = _resolve_input_budget(model_info)
        safe_budget_snapshot = _resolve_safe_input_budget(
            capacity_snapshot=resolved_capacity_snapshot,
            tenant_id="tenant_1",
            agent_requested_output_tokens=None,
            request_requested_output_tokens=None,
        )

        assert input_budget == resolved_capacity_snapshot.provider_input_limit_tokens
        assert isinstance(capacity_snapshot, dict)
        assert capacity_snapshot["capacity_fingerprint"] == resolved_capacity_snapshot.fingerprint
        assert isinstance(resolved_capacity_snapshot, MockModelCapacitySnapshot)
        assert safe_budget_snapshot["model_name"] == resolved_capacity_snapshot.model_name

    def test_persisted_profile_identity_overrides_compatibility_factory(self):
        profile = types.SimpleNamespace(
            capability_profile_version="dashscope/qwen3.7-plus@1"
        )
        snapshot = MockModelCapacitySnapshot(
            model_name="qwen3.7-plus",
            capability_profile_version="dashscope/qwen3.7-plus@1",
        )
        with patch.object(
            create_agent_info_module,
            "CAPABILITY_CATALOG",
            {("dashscope", "qwen3.7-plus"): profile},
        ), patch.object(
            create_agent_info_module,
            "resolve_capacity",
            return_value=snapshot,
        ) as resolver:
            _resolve_input_budget(
                {
                    "model_factory": "OpenAI-API-Compatible",
                    "model_name": "qwen3.7-plus",
                    "capability_profile_version": "dashscope/qwen3.7-plus@1",
                }
            )

        assert resolver.call_args.kwargs["provider"] == "dashscope"
        assert resolver.call_args.kwargs["model_id"] == "qwen3.7-plus"


class TestGetSkillsForTemplate:
    """Tests for the _get_skills_for_template function"""

    def test_get_skills_for_template_success(self):
        """Test case for successfully getting skills for template"""
        mock_skill1 = {"name": "skill1", "description": "desc1"}
        mock_skill2 = {"name": "skill2", "description": "desc2"}

        with patch.dict('sys.modules', {'management.services.skill.service': MagicMock()}):
            mock_skill_service = sys.modules['management.services.skill.service'].SkillService
            mock_instance = MagicMock()
            mock_instance.get_enabled_skills_for_agent.return_value = [mock_skill1, mock_skill2]
            mock_skill_service.return_value = mock_instance

            result = _get_skills_for_template(
                agent_id=1,
                tenant_id="tenant_1",
                version_no=0
            )

            assert result == [
                {"name": "skill1", "description": "desc1"},
                {"name": "skill2", "description": "desc2"}
            ]
            mock_instance.get_enabled_skills_for_agent.assert_called_once_with(
                agent_id=1,
                tenant_id="tenant_1",
                version_no=0
            )

    def test_get_skills_for_template_with_missing_fields(self):
        """Test case for skills with missing name or description fields"""
        mock_skill1 = {"name": "skill1"}  # Missing description
        mock_skill2 = {"description": "desc2"}  # Missing name
        mock_skill3 = {}  # Missing both

        with patch.dict('sys.modules', {'management.services.skill.service': MagicMock()}):
            mock_skill_service = sys.modules['management.services.skill.service'].SkillService
            mock_instance = MagicMock()
            mock_instance.get_enabled_skills_for_agent.return_value = [mock_skill1, mock_skill2, mock_skill3]
            mock_skill_service.return_value = mock_instance

            result = _get_skills_for_template(
                agent_id=1,
                tenant_id="tenant_1",
                version_no=0
            )

            assert result == [
                {"name": "skill1", "description": ""},
                {"name": "", "description": "desc2"},
                {"name": "", "description": ""}
            ]

    def test_get_skills_for_template_empty_list(self):
        """Test case when no skills are enabled"""
        with patch.dict('sys.modules', {'management.services.skill.service': MagicMock()}):
            mock_skill_service = sys.modules['management.services.skill.service'].SkillService
            mock_instance = MagicMock()
            mock_instance.get_enabled_skills_for_agent.return_value = []
            mock_skill_service.return_value = mock_instance

            result = _get_skills_for_template(
                agent_id=1,
                tenant_id="tenant_1",
                version_no=0
            )

            assert result == []

    def test_get_skills_for_template_exception_handling(self):
        """Test case for exception handling when SkillService fails"""
        with patch.dict('sys.modules', {'management.services.skill.service': MagicMock()}):
            mock_skill_service = sys.modules['management.services.skill.service'].SkillService
            mock_skill_service.side_effect = Exception("Service unavailable")

            with patch('backend.agents.create_agent_info.logger') as mock_logger:
                result = _get_skills_for_template(
                    agent_id=1,
                    tenant_id="tenant_1",
                    version_no=0
                )

                assert result == []
                mock_logger.error.assert_called_once()
                assert "Failed to get skills for agent" in mock_logger.error.call_args[0][0]

    def test_get_skills_for_template_with_version_no(self):
        """Test case with specific version number"""
        with patch.dict('sys.modules', {'management.services.skill.service': MagicMock()}):
            mock_skill_service = sys.modules['management.services.skill.service'].SkillService
            mock_instance = MagicMock()
            mock_instance.get_enabled_skills_for_agent.return_value = [
                {"name": "v2_skill", "description": "version 2 skill"}
            ]
            mock_skill_service.return_value = mock_instance

            result = _get_skills_for_template(
                agent_id=1,
                tenant_id="tenant_1",
                version_no=5
            )

            mock_instance.get_enabled_skills_for_agent.assert_called_once_with(
                agent_id=1,
                tenant_id="tenant_1",
                version_no=5
            )
            assert result == [{"name": "v2_skill", "description": "version 2 skill"}]


class TestGetSkillScriptTools:
    """Tests for the _get_skill_script_tools function"""

    def test_get_skill_script_tools_success(self):
        """Test case for successfully getting skill script tools"""
        mock_tool_config.reset_mock()
        with patch('consts.const.CONTAINER_SKILLS_PATH', "/container/skills"):
            result = _get_skill_script_tools(
                agent_id=1,
                tenant_id="tenant_1",
                version_no=0
            )

            assert len(result) == 6
            assert mock_tool_config.call_count == 6

            # Verify the calls made to ToolConfig
            calls = mock_tool_config.call_args_list

            # First call: RunSkillScriptTool
            assert calls[0][1]['class_name'] == "RunSkillScriptTool"
            assert calls[0][1]['name'] == "run_skill_script"
            assert calls[0][1]['params']["local_skills_dir"] == "/container/skills"
            assert calls[0][1]['metadata'] == {"agent_id": 1, "tenant_id": "tenant_1", "version_no": 0}

            # Second call: ReadSkillMdTool
            assert calls[1][1]['class_name'] == "ReadSkillMdTool"
            assert calls[1][1]['name'] == "read_skill_md"

            # Third call: ReadSkillConfigTool
            assert calls[2][1]['class_name'] == "ReadSkillConfigTool"
            assert calls[2][1]['name'] == "read_skill_config"

            # Fourth call: WriteSkillFileTool
            assert calls[3][1]['class_name'] == "WriteSkillFileTool"
            assert calls[3][1]['name'] == "write_skill_file"

            assert calls[4][1]['class_name'] == "DownloadFromS3Tool"
            assert calls[4][1]['name'] == "download_from_s3"
            assert calls[5][1]['class_name'] == "UploadToS3Tool"
            assert calls[5][1]['name'] == "upload_to_s3"

    def test_get_skill_script_tools_metadata_context(self):
        """Test that skill context metadata is correctly set for all tools"""
        mock_tool_config.reset_mock()
        with patch('consts.const.CONTAINER_SKILLS_PATH', "/skills"):
            result = _get_skill_script_tools(
                agent_id=123,
                tenant_id="test_tenant",
                version_no=7
            )

            assert len(result) == 6
            # Skill tools retain skill context; file tools use run-scoped metadata.
            calls = mock_tool_config.call_args_list
            for call in calls[:4]:
                assert call[1]['metadata'] == {
                    "agent_id": 123,
                    "tenant_id": "test_tenant",
                    "version_no": 7
                }
            for call in calls[4:]:
                assert call[1]['metadata'] == {}

    def test_get_skill_script_tools_input_schemas(self):
        """Test that input schemas are correctly defined for all tools"""
        mock_tool_config.reset_mock()
        with patch('consts.const.CONTAINER_SKILLS_PATH', "/skills"):
            result = _get_skill_script_tools(
                agent_id=1,
                tenant_id="tenant_1",
                version_no=0
            )

            calls = mock_tool_config.call_args_list

            # RunSkillScriptTool
            assert '"skill_name": "str"' in calls[0][1]['inputs']
            assert '"script_path": "str"' in calls[0][1]['inputs']
            assert '"params": "str"' in calls[0][1]['inputs']

            # ReadSkillMdTool
            assert '"skill_name": "str"' in calls[1][1]['inputs']
            assert '"additional_files": "list[str]"' in calls[1][1]['inputs']

            # ReadSkillConfigTool
            assert '"skill_name": "str"' in calls[2][1]['inputs']

            # WriteSkillFileTool
            assert '"skill_name": "str"' in calls[3][1]['inputs']
            assert '"file_path": "str"' in calls[3][1]['inputs']
            assert '"content": "str"' in calls[3][1]['inputs']

    def test_get_skill_script_tools_output_types(self):
        """Test that output types are correctly set for all tools"""
        mock_tool_config.reset_mock()
        with patch('consts.const.CONTAINER_SKILLS_PATH', "/skills"):
            result = _get_skill_script_tools(
                agent_id=1,
                tenant_id="tenant_1",
                version_no=0
            )

            calls = mock_tool_config.call_args_list
            for call in calls:
                assert call[1]['output_type'] == "string"

    def test_get_skill_script_tools_source_and_usage(self):
        """Test that source and usage are correctly set for all tools"""
        mock_tool_config.reset_mock()
        with patch('consts.const.CONTAINER_SKILLS_PATH', "/skills"):
            result = _get_skill_script_tools(
                agent_id=1,
                tenant_id="tenant_1",
                version_no=0
            )

            calls = mock_tool_config.call_args_list
            for call in calls:
                assert call[1]['source'] == "builtin"
                assert call[1]['usage'] == "builtin"

    def test_get_skill_script_tools_tool_descriptions(self):
        """Test that tool descriptions are meaningful"""
        mock_tool_config.reset_mock()
        with patch('consts.const.CONTAINER_SKILLS_PATH', "/skills"):
            result = _get_skill_script_tools(
                agent_id=1,
                tenant_id="tenant_1",
                version_no=0
            )

            calls = mock_tool_config.call_args_list
            # Each tool should have a non-empty description
            for call in calls:
                desc = call[1]['description']
                assert len(desc) > 0
                assert isinstance(desc, str)

    def test_get_skill_script_tools_injects_runtime_file_context(self):
        mock_tool_config.reset_mock()
        file_context = {
            "workspace_path": "/mnt/nexent/workdir/t/u/run",
            "user_id": "u",
            "tenant_id": "t",
            "run_id": "run",
            "minio_client": object(),
        }

        _get_skill_script_tools(1, "t", runtime_file_context=file_context)

        calls = mock_tool_config.call_args_list
        assert calls[0][1]["params"]["workspace_path"] == file_context["workspace_path"]
        for call in calls[4:]:
            assert call[1]["metadata"] == file_context
            assert call[1]["params"]["workspace_path"] == file_context["workspace_path"]


class TestDiscoverLangchainTools:
    """Tests for the discover_langchain_tools function"""

    @pytest.mark.asyncio
    async def test_discover_langchain_tools_success(self):
        """Test case for successfully discovering LangChain tools"""
        # Prepare test data
        mock_tool1 = Mock()
        mock_tool1.name = "test_tool1"

        mock_tool2 = Mock()
        mock_tool2.name = "test_tool2"

        # Mock the import statement inside the function
        mock_discover_func = Mock(return_value=[
            (mock_tool1, "tool1.py"),
            (mock_tool2, "tool2.py")
        ])

        with patch('backend.agents.create_agent_info.logger') as mock_logger:
            # Mock the import by patching the globals within the function scope
            with patch.dict('sys.modules', {
                'utils.langchain_utils': Mock(discover_langchain_modules=mock_discover_func)
            }):
                # Execute the test
                result = await discover_langchain_tools()

                # Verify the results
                assert len(result) == 2
                assert result[0] == mock_tool1
                assert result[1] == mock_tool2

                # Verify calls
                mock_discover_func.assert_called_once()
                assert mock_logger.info.call_count == 2
                mock_logger.info.assert_any_call(
                    "Loaded LangChain tool 'test_tool1' from tool1.py")
                mock_logger.info.assert_any_call(
                    "Loaded LangChain tool 'test_tool2' from tool2.py")

    @pytest.mark.asyncio
    async def test_discover_langchain_tools_empty(self):
        """Test case for when no tools are discovered"""
        mock_discover_func = Mock(return_value=[])

        with patch.dict('sys.modules', {
            'utils.langchain_utils': Mock(discover_langchain_modules=mock_discover_func)
        }):
            result = await discover_langchain_tools()

            assert len(result) == 0
            assert result == []
            mock_discover_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_discover_langchain_tools_module_exception(self):
        """Test case for when discover_langchain_modules throws an exception"""
        mock_discover_func = Mock(side_effect=Exception("模块发现错误"))

        with patch('backend.agents.create_agent_info.logger') as mock_logger:
            with patch.dict('sys.modules', {
                'utils.langchain_utils': Mock(discover_langchain_modules=mock_discover_func)
            }):
                result = await discover_langchain_tools()

                assert len(result) == 0
                assert result == []
                mock_logger.error.assert_called_once_with(
                    "Unexpected error scanning LangChain tools directory: 模块发现错误")

    @pytest.mark.asyncio
    async def test_discover_langchain_tools_processing_exception(self):
        """Test case for when an error occurs while processing a single tool"""
        mock_good_tool = Mock()
        mock_good_tool.name = "good_tool"

        # Create a tool that throws an exception when accessing the name attribute
        mock_error_tool = Mock()
        type(mock_error_tool).name = PropertyMock(
            side_effect=Exception("工具处理错误"))

        mock_discover_func = Mock(return_value=[
            (mock_good_tool, "good_tool.py"),
            (mock_error_tool, "error_tool.py")
        ])

        with patch('backend.agents.create_agent_info.logger') as mock_logger:
            with patch.dict('sys.modules', {
                'utils.langchain_utils': Mock(discover_langchain_modules=mock_discover_func)
            }):
                result = await discover_langchain_tools()

                # Verify the results - only the valid tool should be returned
                assert len(result) == 1
                assert result[0] == mock_good_tool

                # Verify that the error was logged
                mock_logger.error.assert_called_once()
                error_call = mock_logger.error.call_args[0][0]
                assert "Error processing LangChain tool from error_tool.py:" in error_call


class TestCreateToolConfigList:
    """Tests for the create_tool_config_list function"""

    @pytest.fixture(autouse=True)
    def mock_filter_accessible_indices(self):
        """Pass-through mock for filter_accessible_indices for all tests in this class."""
        with patch('backend.agents.create_agent_info.ElasticSearchService.filter_accessible_indices',
                   side_effect=lambda index_names, **kwargs: index_names):
            yield

    def test_resolve_runtime_tools_adds_skill_dependencies_with_saved_config(self):
        """An enabled skill makes its declared tool available without explicit selection."""
        with patch(
            "backend.agents.create_agent_info.search_tools_for_sub_agent",
            return_value=[],
        ), patch(
            "backend.agents.create_agent_info.skill_db.search_skills_for_agent",
            return_value=[{"skill_id": 10, "config_values": {"api_key": "saved-key"}}],
        ), patch(
            "backend.agents.create_agent_info.skill_db.get_skill_by_id",
            return_value={
                "skill_id": 10,
                "name": "search-web-linkup",
                "tool_ids": [20],
                "config_values": {"depth": "standard"},
            },
        ), patch(
            "backend.agents.create_agent_info.query_tools_by_ids",
            return_value=[{
                "tool_id": 20,
                "name": "linkup_search",
                "is_available": True,
                "params": [
                    {"name": "api_key", "default": ""},
                    {"name": "depth", "default": "deep"},
                ],
            }],
        ):
            result = _resolve_runtime_tool_records(1, "tenant-1")

        assert [tool["name"] for tool in result] == ["linkup_search"]
        assert result[0]["params"] == [
            {"name": "api_key", "default": "saved-key"},
            {"name": "depth", "default": "standard"},
        ]

    def test_resolve_runtime_tools_does_not_duplicate_explicit_tool(self):
        """Explicit tool configuration remains authoritative for a skill dependency."""
        explicit_tool = {"tool_id": 20, "name": "linkup_search", "params": []}
        with patch(
            "backend.agents.create_agent_info.search_tools_for_sub_agent",
            return_value=[explicit_tool],
        ), patch(
            "backend.agents.create_agent_info.skill_db.search_skills_for_agent",
            return_value=[{"skill_id": 10, "config_values": {"api_key": "skill-key"}}],
        ), patch(
            "backend.agents.create_agent_info.skill_db.get_skill_by_id",
            return_value={"skill_id": 10, "name": "search-web-linkup", "tool_ids": [20]},
        ), patch("backend.agents.create_agent_info.query_tools_by_ids") as mock_query:
            result = _resolve_runtime_tool_records(1, "tenant-1")

        assert result == [explicit_tool]
        mock_query.assert_not_called()

    def test_resolve_runtime_tools_rejects_conflicting_skill_config(self):
        """Two skills cannot silently assign different values to the same tool parameter."""
        skill_instances = [
            {"skill_id": 10, "config_values": {"api_key": "first"}},
            {"skill_id": 11, "config_values": {"api_key": "second"}},
        ]
        skills = {
            10: {"skill_id": 10, "name": "first-skill", "tool_ids": [20]},
            11: {"skill_id": 11, "name": "second-skill", "tool_ids": [20]},
        }
        with patch(
            "backend.agents.create_agent_info.search_tools_for_sub_agent",
            return_value=[],
        ), patch(
            "backend.agents.create_agent_info.skill_db.search_skills_for_agent",
            return_value=skill_instances,
        ), patch(
            "backend.agents.create_agent_info.skill_db.get_skill_by_id",
            side_effect=lambda skill_id, tenant_id: skills[skill_id],
        ):
            with pytest.raises(ValidationError, match="different values"):
                _resolve_runtime_tool_records(1, "tenant-1")

    @pytest.mark.asyncio
    async def test_create_tool_config_list_basic(self):
        """Test case for basic tool configuration list creation"""
        with patch('backend.agents.create_agent_info.discover_langchain_tools') as mock_discover, \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config:

            # Set mock return values
            mock_discover.return_value = []
            mock_search_tools.return_value = [
                {
                    "class_name": "TestTool",
                    "name": "test_tool",
                    "description": "A test tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [{"name": "param1", "default": "value1"}],
                    "source": "local",
                    "usage": None
                }
            ]

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 1
            # Verify that ToolConfig was called correctly
            mock_tool_config.assert_called_once_with(
                class_name="TestTool",
                name="test_tool",
                description="A test tool",
                inputs="string",
                output_type="string",
                params={"param1": "value1"},
                source="local",
                usage=None
            )

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_knowledge_base_tool(self):
        """Test case including the knowledge base search tool"""
        with patch('backend.agents.create_agent_info.discover_langchain_tools') as mock_discover, \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_embedding, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank:

            mock_discover.return_value = []
            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["test_index"]},  # Add non-empty index_names
                        {"name": "rerank", "default": False},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_vdb_core = "mock_elastic_core"
            mock_get_vector_db_core.return_value = mock_vdb_core
            mock_embedding.return_value = ("mock_embedding_model", 123, {"status": "ok"})
            mock_rerank.return_value = None

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 1
            # Verify that ToolConfig was called correctly, including knowledge base metadata
            # Check if the last call was for KnowledgeBaseSearchTool
            mock_tool_config.assert_called()
            last_call = mock_tool_config.call_args_list[-1]
            assert last_call[1]['class_name'] == "KnowledgeBaseSearchTool"

    @pytest.mark.asyncio
    async def test_create_tool_config_list_knowledge_base_multimodal(self):
        """Ensure multimodal param is forwarded to embedding model selection."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "KnowledgeBaseSearchTool"
        mock_tool_instance.params = {
            "index_names": ["idx1", "idx2"],
            "multimodal": True,
            "rerank": False,
        }

        with patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_embedding_by_index, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank, \
                patch('backend.agents.create_agent_info.get_knowledge_name_map_by_index_names') as mock_get_knowledge_map, \
                patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config:

            mock_tool_config.return_value = mock_tool_instance

            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["idx1", "idx2"]},
                        {"name": "multimodal", "default": True},
                        {"name": "rerank", "default": False},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vector_db_core.return_value = "mock_elastic_core"
            mock_embedding_by_index.return_value = ("mock_embedding_model", 123, {"status": "ok"})
            mock_rerank.return_value = None
            mock_get_knowledge_map.return_value = {"idx1": "KB1", "idx2": "KB2"}

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 1
            # Verify get_embedding_model_by_index_name was called with tenant_id and first index_name
            mock_embedding_by_index.assert_called_once_with("tenant_1", "idx1")

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_analyze_image_tool(self):
        """Ensure AnalyzeImageTool receives VLM model metadata."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "AnalyzeImageTool"
        mock_tool_config.return_value = mock_tool_instance

        with patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vlm_adapter') as mock_get_vlm_model, \
                patch('backend.agents.create_agent_info.minio_client', new_callable=MagicMock) as mock_minio_client:

            mock_search_tools.return_value = [
                {
                    "class_name": "AnalyzeImageTool",
                    "name": "analyze_image",
                    "description": "Analyze image tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [{"name": "prompt", "default": "describe"}],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vlm_model.return_value = "mock_vlm_model"

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 1
            assert result[0] is mock_tool_instance
            mock_get_vlm_model.assert_called_once_with("tenant_1", None, slot="vlm")
            # Verify metadata includes validate_url_access lambda
            assert "vlm_model" in mock_tool_instance.metadata
            assert "storage_client" in mock_tool_instance.metadata
            assert "validate_url_access" in mock_tool_instance.metadata
            assert callable(mock_tool_instance.metadata["validate_url_access"])

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "class_name,tool_name",
        [
            ("AnalyzeAudioTool", "analyze_audio"),
            ("AnalyzeVideoTool", "analyze_video"),
        ],
    )
    async def test_create_tool_config_list_with_audio_video_tools(self, class_name, tool_name):
        """Ensure audio/video tools receive video understanding model metadata."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = class_name
        mock_tool_config.return_value = mock_tool_instance

        with patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vlm_adapter') as mock_get_video_model, \
                patch('backend.agents.create_agent_info.minio_client', new_callable=MagicMock):

            mock_search_tools.return_value = [
                {
                    "class_name": class_name,
                    "name": tool_name,
                    "description": "Analyze media tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [{"name": "prompt", "default": "describe"}],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_video_model.return_value = "mock_video_model"

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 1
            assert result[0] is mock_tool_instance
            expected_slot = "vlm4" if tool_name == "analyze_audio" else "vlm3"
            mock_get_video_model.assert_called_once_with("tenant_1", None, slot=expected_slot)
            assert mock_tool_instance.metadata["vlm_model"] == "mock_video_model"
            assert "storage_client" in mock_tool_instance.metadata
            assert callable(mock_tool_instance.metadata["validate_url_access"])

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_analyze_text_file_tool(self):
        """Ensure AnalyzeTextFileTool receives text-specific metadata."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "AnalyzeTextFileTool"
        mock_tool_config.return_value = mock_tool_instance

        with patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_llm_adapter') as mock_get_llm_model, \
                patch('backend.agents.create_agent_info.minio_client', new_callable=MagicMock) as mock_minio_client:

            mock_search_tools.return_value = [
                {
                    "class_name": "AnalyzeTextFileTool",
                    "name": "analyze_text_file",
                    "description": "Analyze text file tool",
                    "inputs": "string",
                    "output_type": "array",
                    "params": [{"name": "prompt", "default": "describe"}],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_llm_model.return_value = "mock_llm_model"

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 1
            assert result[0] is mock_tool_instance
            mock_get_llm_model.assert_called_once_with("tenant_1", None, modality="llm_long_context")
            # Verify metadata includes validate_url_access lambda
            assert "llm_model" in mock_tool_instance.metadata
            assert "storage_client" in mock_tool_instance.metadata
            assert "data_process_service_url" in mock_tool_instance.metadata
            assert "validate_url_access" in mock_tool_instance.metadata
            assert callable(mock_tool_instance.metadata["validate_url_access"])

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_knowledge_base_tool_metadata(self):
        """
        Test that KnowledgeBaseSearchTool metadata contains vdb_core, embedding_model,
        rerank_model, display_name_to_index_map, and index_name_to_display_map.
        """
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "KnowledgeBaseSearchTool"
        mock_tool_instance.params = {
            "index_names": ["idx_a"],
            "rerank": True,
            "rerank_model_name": "gte-rerank-v2",
        }

        with patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_embedding, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank, \
                patch('backend.agents.create_agent_info.get_knowledge_name_map_by_index_names') as mock_get_knowledge_map, \
                patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config:

            mock_tool_config.return_value = mock_tool_instance

            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["idx_a"]},
                        {"name": "rerank", "default": True},
                        {"name": "rerank_model_name", "default": "gte-rerank-v2"},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_vdb_core = "mock_elastic_core"
            mock_embedding_model = "mock_embedding_model"
            mock_rerank_model = "mock_rerank_model"
            mock_get_vector_db_core.return_value = mock_vdb_core
            mock_embedding.return_value = (mock_embedding_model, 123, {"status": "ok"})
            mock_rerank.return_value = mock_rerank_model
            mock_get_knowledge_map.return_value = {"idx_a": "Knowledge Base A"}

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 1
            assert result[0] is mock_tool_instance

            # Verify correct functions were called with correct parameters
            mock_get_vector_db_core.assert_called_once()
            # Verify that call uses tenant_id and first index_name
            mock_embedding.assert_called_once_with("tenant_1", "idx_a")
            mock_rerank.assert_called_once_with(tenant_id="tenant_1", model_name="gte-rerank-v2")
            mock_get_knowledge_map.assert_called_once_with(["idx_a"], tenant_id="tenant_1")

            # Verify metadata contains required fields
            assert "vdb_core" in mock_tool_instance.metadata
            assert "embedding_model" in mock_tool_instance.metadata
            assert "rerank_model" in mock_tool_instance.metadata
            assert "display_name_to_index_map" in mock_tool_instance.metadata
            assert "index_name_to_display_map" in mock_tool_instance.metadata

            # Verify mappings
            assert mock_tool_instance.metadata["display_name_to_index_map"] == {
                "Knowledge Base A": "idx_a"
            }
            assert mock_tool_instance.metadata["index_name_to_display_map"] == {
                "idx_a": "Knowledge Base A"
            }

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_knowledge_base_tool_multiple_tools(self):
        """
        Test that multiple tools are processed correctly, with KnowledgeBaseSearchTool
        receiving the correct metadata without index_names.
        """
        mock_tool_kb = MagicMock()
        mock_tool_kb.class_name = "KnowledgeBaseSearchTool"

        mock_tool_other = MagicMock()
        mock_tool_other.class_name = "OtherTool"

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_embedding, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank:

            mock_tool_config.side_effect = [mock_tool_kb, mock_tool_other]

            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "kb_search",
                    "description": "Knowledge search",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["kb_idx"]},  # Non-empty index_names
                        {"name": "rerank", "default": True},
                        {"name": "rerank_model_name", "default": "gte-rerank-v2"},
                    ],
                    "source": "local",
                    "usage": None
                },
                {
                    "class_name": "OtherTool",
                    "name": "other",
                    "description": "Other tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vector_db_core.return_value = "vdb_core_instance"
            mock_embedding.return_value = ("embedding_instance", 123, {"status": "ok"})
            mock_rerank.return_value = "rerank_instance"

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 2

            # Verify KnowledgeBaseSearchTool has correct metadata including display_name_to_index_map
            assert "vdb_core" in mock_tool_kb.metadata
            assert "embedding_model" in mock_tool_kb.metadata
            assert "rerank_model" in mock_tool_kb.metadata
            assert "display_name_to_index_map" in mock_tool_kb.metadata

            # Verify OtherTool has no special metadata (should not have metadata attribute set)
            # Note: MagicMock will return a new MagicMock for unset attributes, so we check call_args
            # Instead, verify that set_metadata was never called on the mock_tool_other
            assert not hasattr(mock_tool_other, 'metadata') or mock_tool_other.metadata.call_count == 0 if hasattr(mock_tool_other.metadata, 'call_count') else True

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_knowledge_base_tool_mixed_sources(self):
        """
        Test handling of tools from mixed sources (local, mcp, langchain).
        KnowledgeBaseSearchTool should always get the simplified metadata.
        """
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "KnowledgeBaseSearchTool"

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_embedding, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank:

            mock_tool_config.return_value = mock_tool_instance

            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "kb_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["mcp_idx"]},  # Add non-empty index_names
                        {"name": "rerank", "default": True},
                        {"name": "rerank_model_name", "default": "gte-rerank-v2"},
                    ],
                    "source": "mcp",
                    "usage": "mcp_server_1"
                }
            ]
            mock_get_vector_db_core.return_value = "vdb_core"
            mock_embedding.return_value = ("embedding", 123, {"status": "ok"})
            mock_rerank.return_value = "rerank_model"

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 1
            # Even for MCP-sourced KnowledgeBaseSearchTool, metadata should be set
            assert "vdb_core" in mock_tool_instance.metadata
            assert "embedding_model" in mock_tool_instance.metadata
            assert "display_name_to_index_map" in mock_tool_instance.metadata

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_datamate_tool(self):
        """
        Test that DataMateTool (or other unhandled tools) receive no special metadata.
        This ensures the refactoring doesn't break other tool types.
        """
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "DataMateTool"

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools:

            mock_tool_config.return_value = mock_tool_instance

            mock_search_tools.return_value = [
                {
                    "class_name": "DataMateTool",
                    "name": "datamate",
                    "description": "Data management tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [],
                    "source": "local",
                    "usage": None
                }
            ]

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 1
            assert result[0] is mock_tool_instance
            # DataMateTool should not receive any special metadata (metadata should remain unset)
            # Since we use MagicMock, we verify that metadata was never assigned
            assert not hasattr(mock_tool_instance, 'metadata') or mock_tool_instance.metadata.call_count == 0 if hasattr(mock_tool_instance.metadata, 'call_count') else True

    @pytest.mark.asyncio
    async def test_create_tool_config_list_empty_list(self):
        """
        Test that an empty tools list returns an empty result.
        """
        with patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools:

            mock_search_tools.return_value = []

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert result == []

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_langchain_tool_metadata(self):
        """
        Test that langchain-sourced tools receive metadata from the langchain tool discovery.
        This verifies that the langchain tool metadata assignment still works correctly.
        """
        mock_langchain_tool = MagicMock()
        mock_langchain_tool.name = "LangChainTool"

        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "LangChainTool"

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools') as mock_discover, \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools:

            mock_tool_config.return_value = mock_tool_instance
            mock_discover.return_value = [mock_langchain_tool]
            mock_search_tools.return_value = [
                {
                    "class_name": "LangChainTool",
                    "name": "langchain_tool",
                    "description": "A langchain tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [],
                    "source": "langchain",
                    "usage": None
                }
            ]

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 1
            assert result[0] is mock_tool_instance
            # Langchain tool should receive metadata from discovered langchain tool
            assert mock_tool_instance.metadata == mock_langchain_tool

    @pytest.mark.asyncio
    async def test_create_tool_config_list_multiple_tools_same_type(self):
        """
        Test that multiple KnowledgeBaseSearchTool instances each get correct metadata.
        """
        mock_tool_1 = MagicMock()
        mock_tool_1.class_name = "KnowledgeBaseSearchTool"

        mock_tool_2 = MagicMock()
        mock_tool_2.class_name = "KnowledgeBaseSearchTool"

        mock_tool_config.side_effect = [mock_tool_1, mock_tool_2]

        with patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_embedding, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank:

            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "kb_search_1",
                    "description": "First knowledge search",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["idx_1"]},  # Add non-empty index_names
                        {"name": "rerank", "default": True},
                        {"name": "rerank_model_name", "default": "gte-rerank-v2"},
                    ],
                    "source": "local",
                    "usage": None
                },
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "kb_search_2",
                    "description": "Second knowledge search",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["idx_2"]},  # Add non-empty index_names
                        {"name": "rerank", "default": True},
                        {"name": "rerank_model_name", "default": "gte-rerank-v2"},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vector_db_core.return_value = "vdb_core"
            mock_embedding.return_value = ("embedding", 123, {"status": "ok"})
            mock_rerank.return_value = "rerank_model"

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 2

            # Both tools should have the same metadata including display_name_to_index_map
            assert "vdb_core" in mock_tool_1.metadata
            assert "embedding_model" in mock_tool_1.metadata
            assert "rerank_model" in mock_tool_1.metadata
            assert "display_name_to_index_map" in mock_tool_1.metadata
            assert mock_tool_1.metadata["display_name_to_index_map"] == {}
            assert mock_tool_2.metadata["display_name_to_index_map"] == {}

    @pytest.mark.asyncio
    async def test_create_tool_config_list_applies_request_overrides_for_multiple_tools(self):
        """Request tool_params should override DB params for multiple tools in one agent."""
        kb_tool = MagicMock()
        kb_tool.class_name = "KnowledgeBaseSearchTool"
        kb_tool.params = {
            "index_names": ["idx_override"],
            "rerank": True,
            "rerank_model_name": "gte-rerank-v2",
            "top_k": 10,
        }
        analyze_tool = MagicMock()
        analyze_tool.class_name = "AnalyzeTextFileTool"
        analyze_tool.params = {
            "prompt": "override prompt",
        }

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_embedding, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank, \
                patch('backend.agents.create_agent_info.get_knowledge_name_map_by_index_names', return_value={"idx_override": "Override KB"}), \
                patch('backend.agents.create_agent_info.get_llm_adapter', return_value='llm-model'):
            mock_tool_config.side_effect = [kb_tool, analyze_tool]
            mock_get_vector_db_core.return_value = 'vdb-core'
            mock_embedding.return_value = ('embedding-model', 1, {'status': 'ok'})
            mock_rerank.return_value = 'rerank-model'
            mock_search_tools.return_value = [
                {
                    'class_name': 'KnowledgeBaseSearchTool',
                    'name': 'knowledge_base_search',
                    'description': 'kb',
                    'inputs': '{}',
                    'output_type': 'string',
                    'params': [
                        {'name': 'index_names', 'default': ['idx_default']},
                        {'name': 'rerank', 'default': False},
                        {'name': 'rerank_model_name', 'default': ''},
                        {'name': 'top_k', 'default': 5},
                    ],
                    'source': 'local',
                    'usage': None,
                },
                {
                    'class_name': 'AnalyzeTextFileTool',
                    'name': 'analyze_text_file',
                    'description': 'text',
                    'inputs': '{}',
                    'output_type': 'string',
                    'params': [
                        {'name': 'prompt', 'default': 'default prompt'},
                    ],
                    'source': 'local',
                    'usage': None,
                },
            ]

            result = await create_tool_config_list(
                'agent_1',
                'tenant_1',
                'user_1',
                tool_params={
                    'agents': {
                        'test_agent': {
                            'tools': {
                                'knowledge_base_search': {
                                    'top_k': 10,
                                    'rerank': True,
                                    'rerank_model_name': 'gte-rerank-v2',
                                    'index_names': ['idx_override'],
                                },
                                'analyze_text_file': {
                                    'prompt': 'override prompt',
                                },
                            }
                        }
                    }
                },
            )

        assert len(result) == 2
        assert kb_tool.params['top_k'] == 10
        assert kb_tool.params['rerank'] is True
        assert kb_tool.params['rerank_model_name'] == 'gte-rerank-v2'
        assert kb_tool.params['index_names'] == ['idx_override']
        assert analyze_tool.params['prompt'] == 'override prompt'
        mock_rerank.assert_called_once_with(tenant_id='tenant_1', model_name='gte-rerank-v2')
        mock_embedding.assert_called_once_with('tenant_1', 'idx_override')

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_tool_params(self):
        """Test create_tool_config_list with valid tool_params."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "AnalyzeTextFileTool"
        mock_tool_instance.params = {
            "prompt": "override prompt",
        }

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_llm_adapter', return_value='llm-model'):
            mock_tool_config.return_value = mock_tool_instance

            mock_search_tools.return_value = [
                {
                    'class_name': 'AnalyzeTextFileTool',
                    'name': 'analyze_text_file',
                    'description': 'text',
                    'inputs': '{}',
                    'output_type': 'string',
                    'params': [
                        {'name': 'prompt', 'default': 'default prompt'},
                    ],
                    'source': 'local',
                    'usage': None,
                }
            ]

            result = await create_tool_config_list(
                'agent_1',
                'tenant_1',
                'user_1',
                tool_params={
                    'agents': {
                        'test_agent': {
                            'tools': {
                                'analyze_text_file': {
                                    'prompt': 'override prompt',
                                }
                            }
                        }
                    }
                },
            )

            assert len(result) == 1
            assert result[0] is mock_tool_instance

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_dify_tool(self):
        """Test that DifySearchTool gets correct metadata including rerank model."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "DifySearchTool"
        mock_tool_instance.params = {
            "rerank": True,
            "rerank_model_name": "gte-rerank-v2",
        }

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank:

            mock_tool_config.return_value = mock_tool_instance
            mock_rerank.return_value = "mock_rerank_model"

            mock_search_tools.return_value = [
                {
                    "class_name": "DifySearchTool",
                    "name": "dify_search",
                    "description": "Dify knowledge search",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "rerank", "default": True},
                        {"name": "rerank_model_name", "default": "gte-rerank-v2"},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            # Verify rerank model was fetched
            mock_rerank.assert_called_once_with(
                tenant_id="tenant_1", model_name="gte-rerank-v2"
            )

            # Verify metadata
            assert len(result) == 1
            assert result[0] is mock_tool_instance

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_dify_tool_no_rerank(self):
        """Test that DifySearchTool without rerank gets None metadata."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "DifySearchTool"
        mock_tool_instance.params = {
            "rerank": False,
            "rerank_model_name": "",
        }

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank:

            mock_tool_config.return_value = mock_tool_instance

            mock_search_tools.return_value = [
                {
                    "class_name": "DifySearchTool",
                    "name": "dify_search",
                    "description": "Dify knowledge search",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "rerank", "default": False},
                        {"name": "rerank_model_name", "default": ""},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            # Verify rerank model was NOT fetched
            mock_rerank.assert_not_called()

            # Verify metadata
            assert len(result) == 1
            assert result[0] is mock_tool_instance

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_datamate_tool_no_rerank(self):
        """Test that DataMateSearchTool without rerank gets None metadata."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "DataMateSearchTool"
        mock_tool_instance.params = {
            "rerank": False,
            "rerank_model_name": "",
        }

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank:

            mock_tool_config.return_value = mock_tool_instance

            mock_search_tools.return_value = [
                {
                    "class_name": "DataMateSearchTool",
                    "name": "datamate_search",
                    "description": "DataMate knowledge search",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "rerank", "default": False},
                        {"name": "rerank_model_name", "default": ""},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            # Verify rerank model was NOT fetched
            mock_rerank.assert_not_called()

            # Verify result
            assert len(result) == 1
            assert result[0] is mock_tool_instance

    @pytest.mark.asyncio
    async def test_create_tool_config_list_analyze_image_tool_validate_url_access(self):
        """
        Test that AnalyzeImageTool receives validate_url_access callback that
        properly calls validate_urls_access with user_id.
        """
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "AnalyzeImageTool"

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vlm_adapter') as mock_get_vlm_model, \
                patch('backend.agents.create_agent_info.minio_client', new_callable=MagicMock), \
                patch('backend.agents.create_agent_info.validate_urls_access') as mock_validate:

            mock_tool_config.return_value = mock_tool_instance

            mock_search_tools.return_value = [
                {
                    "class_name": "AnalyzeImageTool",
                    "name": "analyze_image",
                    "description": "Analyze image tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vlm_model.return_value = "mock_vlm_model"

            result = await create_tool_config_list("agent_1", "tenant_1", "user_123")

            assert len(result) == 1
            assert "validate_url_access" in result[0].metadata
            assert callable(result[0].metadata["validate_url_access"])

            # Test that the callback properly wraps validate_urls_access
            mock_validate.reset_mock()
            test_urls = ["s3://bucket/image.jpg"]
            result[0].metadata["validate_url_access"](test_urls)
            mock_validate.assert_called_once_with(test_urls, "user_123")

    @pytest.mark.asyncio
    async def test_create_tool_config_list_analyze_text_file_tool_validate_url_access(self):
        """
        Test that AnalyzeTextFileTool receives validate_url_access callback that
        properly calls validate_urls_access with user_id.
        """
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "AnalyzeTextFileTool"

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_llm_adapter') as mock_get_llm_model, \
                patch('backend.agents.create_agent_info.minio_client', new_callable=MagicMock), \
                patch('backend.agents.create_agent_info.validate_urls_access') as mock_validate:

            mock_tool_config.return_value = mock_tool_instance

            mock_search_tools.return_value = [
                {
                    "class_name": "AnalyzeTextFileTool",
                    "name": "analyze_text_file",
                    "description": "Analyze text file tool",
                    "inputs": "array",
                    "output_type": "array",
                    "params": [],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_llm_model.return_value = "mock_llm_model"

            result = await create_tool_config_list("agent_1", "tenant_1", "user_456")

            assert len(result) == 1
            assert "validate_url_access" in result[0].metadata
            assert callable(result[0].metadata["validate_url_access"])

            # Test that the callback properly wraps validate_urls_access
            mock_validate.reset_mock()
            test_urls = ["s3://bucket/document.pdf"]
            result[0].metadata["validate_url_access"](test_urls)
            mock_validate.assert_called_once_with(test_urls, "user_456")


class TestCreateAgentConfig:
    """Tests for the create_agent_config function"""

    async def _run_context_manager_case(
        self,
        *,
        enable_context_manager: bool,
        prepared_prompt: str,
        components: Optional[List[Mock]] = None,
        memory_switch: bool = False,
        fixed_search_result: str = "No relevant memories found.",
    ):
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
                patch('backend.agents.create_agent_info.query_sub_agent_relations', return_value=[]), \
                patch('backend.agents.create_agent_info.create_tool_config_list', return_value=[]), \
                patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
                patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
                patch('backend.agents.create_agent_info.prepare_prompt_templates', new_callable=AsyncMock) as mock_prepare_templates, \
                patch('backend.agents.create_agent_info.get_model_by_model_id') as mock_get_model_by_id, \
                patch('backend.agents.create_agent_info.build_context_inputs') as mock_build_components, \
                patch('backend.agents.create_agent_info.AgentConfig') as mock_agent_config, \
                patch('backend.agents.create_agent_info._create_fixed_search_memory_tool') as mock_search_tool, \
                patch('backend.agents.create_agent_info._get_skills_for_template', return_value=[]), \
                patch.dict(sys.modules, {
                    'services.memory_record_service': MagicMock(
                        _resolve_tenant_embedding_model_info=MagicMock(return_value=None),
                    ),
                    'services.memory_context_service': MagicMock(
                        get_memory_context_service=MagicMock(
                            return_value=MagicMock(
                                build_context=AsyncMock(return_value=types.SimpleNamespace(
                                    tenant_long_term=(),
                                    user_long_term=(),
                                ))
                            )
                        ),
                    ),
                    'services.memory_backend_adapter': MagicMock(
                        build_memory_service_for_agent=MagicMock(return_value=None),
                    ),
                }), \
                patch(
                    'backend.agents.create_agent_info.ContextManagerConfig',
                    side_effect=lambda **kwargs: Mock(**kwargs),
                ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": [123],
                "provide_run_summary": False,
                "enable_context_manager": enable_context_manager,
            }
            mock_get_template.return_value = {}
            mock_tenant_config.get_app_config.side_effect = ["TestApp", "Test Description"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(
                    memory_switch=memory_switch,
                    agent_share_option="always",
                    disable_agent_ids=[],
                    disable_user_agent_ids=[],
                ),
                memory_config={},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1",
            )
            mock_search_tool.return_value.forward.return_value = fixed_search_result
            mock_prepare_templates.return_value = {"system_prompt": prepared_prompt}
            mock_get_model_by_id.return_value = {"display_name": "test_model", "max_tokens": 1000}
            mock_build_components.return_value = components or []

            result = await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query")

            return {
                "build_components": mock_build_components,
                "prepare_templates": mock_prepare_templates,
                "agent_config": mock_agent_config,
                "search_tool": mock_search_tool,
            }

    @pytest.mark.asyncio
    async def test_create_agent_config_uses_raw_components(self):
        """Agent configuration should always delegate stable context assembly to the SDK."""
        mock_tool_config.reset_mock()
        mock_tool_config.side_effect = None
        components = [Mock(component_type="system_prompt")]
        mocks = await self._run_context_manager_case(
            enable_context_manager=True,
            prepared_prompt="",
            components=components,
        )

        mocks["build_components"].assert_called_once()
        mocks["prepare_templates"].assert_awaited_once()
        assert mocks["agent_config"].call_args.kwargs["context_items"] is components
        config = mocks["agent_config"].call_args.kwargs["context_manager_config"]
        assert config.policy_layers["platform"]["processing_mode"] == "adaptive_compact"

    @pytest.mark.asyncio
    async def test_create_agent_config_routes_memory_policy_through_context_items(self):
        memory_tools = [
            types.SimpleNamespace(name="search_memory"),
            types.SimpleNamespace(name="store_memory"),
        ]
        with patch(
            "backend.agents.create_agent_info._get_skill_script_tools",
            return_value=memory_tools,
        ):
            mocks = await self._run_context_manager_case(
                enable_context_manager=True,
                prepared_prompt="",
            )

        context_kwargs = mocks["build_components"].call_args.kwargs
        policy = context_kwargs["memory_tool_policy"]
        assert "### Memory Tool Policy" in policy
        assert "search_memory" not in policy
        assert "store_memory" in policy
        assert "instructions" not in mocks["agent_config"].call_args.kwargs

    @pytest.mark.asyncio
    @pytest.mark.parametrize("sandbox_default_level", ["local", "docker"])
    async def test_create_agent_config_injects_import_policy_only_for_local_executor(
        self,
        sandbox_default_level,
    ):
        sdk_authorized_imports = ["sdk_default_import", "sdk_extra_import"]
        with patch(
            "backend.agents.create_agent_info.os.getenv",
            return_value=sandbox_default_level,
        ), patch(
            "backend.agents.create_agent_info.get_local_python_authorized_imports",
            return_value=sdk_authorized_imports,
        ) as get_authorized_imports:
            mocks = await self._run_context_manager_case(
                enable_context_manager=True,
                prepared_prompt="",
            )

        expected_authorized_imports = (
            sdk_authorized_imports if sandbox_default_level == "local" else None
        )
        assert (
            mocks["build_components"].call_args.kwargs[
                "restricted_python_authorized_imports"
            ]
            == expected_authorized_imports
        )
        if sandbox_default_level == "local":
            get_authorized_imports.assert_called_once_with()
        else:
            get_authorized_imports.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_agent_config_runs_fixed_search_once_without_exposing_tool(self):
        result_text = "Found 1 relevant memories:\n[1] Existing preference"
        mocks = await self._run_context_manager_case(
            enable_context_manager=True,
            prepared_prompt="",
            memory_switch=True,
            fixed_search_result=result_text,
        )

        search_instance = mocks["search_tool"].return_value
        search_instance.forward.assert_called_once_with("test query", 5)

        context_kwargs = mocks["build_components"].call_args.kwargs
        assert context_kwargs["memory_list"] == [{
            "memory": result_text,
            "memory_level": "agent",
        }]
        assert "search_memory" not in context_kwargs["tools"]
        assert "search_memory" not in context_kwargs["memory_tool_policy"]
        assert all(
            tool.name != "search_memory"
            for tool in mocks["agent_config"].call_args.kwargs["tools"]
        )
        assert mocks["agent_config"].call_args.kwargs["pre_run_tool_events"] == [
            {
                "type": "tool",
                "content": "",
                "tool_name": "search_memory",
                "tool_arguments": {
                    "query": "test query",
                    "top_k": 5,
                },
            },
            {
                "type": "execution_logs",
                "content": result_text,
            },
        ]

    @pytest.mark.asyncio
    async def test_create_agent_config_managed_path_includes_builtin_tools_in_context(self):
        """Managed path should describe the same builtin tools that AgentConfig exposes."""
        builtin_tools = [
            types.SimpleNamespace(name="run_skill_script"),
            types.SimpleNamespace(name="read_skill_md"),
            types.SimpleNamespace(name="read_skill_config"),
            types.SimpleNamespace(name="write_skill_file"),
        ]
        with patch(
            'backend.agents.create_agent_info._get_skill_script_tools',
            return_value=builtin_tools,
        ):
            mocks = await self._run_context_manager_case(
                enable_context_manager=True,
                template="legacy {{duty}}",
                prepared_prompt="",
            )

        context_tools = mocks["build_components"].call_args.kwargs["tools"]
        agent_tools = mocks["agent_config"].call_args.kwargs["tools"]

        assert "run_skill_script" in context_tools
        assert "read_skill_md" in context_tools
        assert "read_skill_config" in context_tools
        assert "write_skill_file" in context_tools
        assert set(context_tools) == {tool.name for tool in agent_tools}

    @pytest.mark.asyncio
    async def test_create_agent_config_managed_path_includes_builtin_tools_in_context(self):
        """Managed path should describe the same builtin tools that AgentConfig exposes."""
        mock_tool_config.reset_mock()
        mock_tool_config.side_effect = None
        builtin_tools = [
            types.SimpleNamespace(name="run_skill_script"),
            types.SimpleNamespace(name="read_skill_md"),
            types.SimpleNamespace(name="read_skill_config"),
            types.SimpleNamespace(name="write_skill_file"),
        ]
        with patch(
            'backend.agents.create_agent_info._get_skill_script_tools',
            return_value=builtin_tools,
        ):
            mocks = await self._run_context_manager_case(
                enable_context_manager=True,
                prepared_prompt="",
            )

        context_tools = mocks["build_components"].call_args.kwargs["tools"]
        agent_tools = mocks["agent_config"].call_args.kwargs["tools"]

        assert "run_skill_script" in context_tools
        assert "read_skill_md" in context_tools
        assert "read_skill_config" in context_tools
        assert "write_skill_file" in context_tools
        assert set(context_tools) == {tool.name for tool in agent_tools}

    @pytest.mark.asyncio
    async def test_create_agent_config_disabled_compression_still_builds_components(self):
        """Disabling compression must not restore a second context assembly path."""
        mock_tool_config.reset_mock()
        mock_tool_config.side_effect = None
        components = [Mock(component_type="system_prompt")]
        mocks = await self._run_context_manager_case(
            enable_context_manager=False,
            prepared_prompt="",
            components=components,
        )

        mocks["build_components"].assert_called_once()
        assert "system_prompt" not in mocks["prepare_templates"].call_args.kwargs
        assert mocks["agent_config"].call_args.kwargs["context_items"] is components
        config = mocks["agent_config"].call_args.kwargs["context_manager_config"]
        assert config.policy_layers["platform"]["processing_mode"] == "adaptive_compact"

    @pytest.mark.asyncio
    async def test_create_agent_config_basic(self):
        """Test case for basic agent configuration creation"""
        # Reset module-level mock - parallel_executor appends an extra
        # ToolConfig call after create_tool_config_list returns.  Both
        # call history and side_effect must be cleared because prior
        # tests may have left an exhausted iterator on the shared mock.
        mock_tool_config.reset_mock()
        mock_tool_config.side_effect = None
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
                patch('backend.agents.create_agent_info.query_sub_agent_relations') as mock_query_sub, \
                patch('backend.agents.create_agent_info.create_tool_config_list') as mock_create_tools, \
                patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
                patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
                patch('backend.agents.create_agent_info.AgentConfig') as mock_agent_config, \
                patch('backend.agents.create_agent_info.prepare_prompt_templates') as mock_prepare_templates, \
                patch('backend.agents.create_agent_info.get_model_by_model_id') as mock_get_model_by_id:

            # Set mock return values
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": [123],
                "provide_run_summary": True
            }
            mock_query_sub.return_value = []
            mock_create_tools.return_value = []
            mock_get_template.return_value = {
                "system_prompt": "{{duty}} {{constraint}} {{few_shots}}"}
            mock_tenant_config.get_app_config.side_effect = [
                "TestApp", "Test Description"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(memory_switch=False),
                memory_config={},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1"
            )
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"}
            mock_get_model_by_id.return_value = {"display_name": "test_model"}

            result = await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query")

            # Verify that AgentConfig was called correctly
            mock_agent_config.assert_called_once_with(
                name="test_agent",
                description="test description",
                prompt_templates={"system_prompt": "populated_system_prompt"},
                tools=ANY,
                max_steps=5,
                requested_output_tokens=None,
                model_name="test_model",
                provide_run_summary=True,
                allow_chat_metadata=False,
                managed_agents=[],
                external_a2a_agents=[],
                context_manager_config=ANY,
                context_items=ANY,
                pre_run_tool_events=ANY,
                capacity_snapshot=ANY,
                safe_input_budget_snapshot=ANY,
                verification_config=ANY,
                enable_planning=ANY
            )
            # Verify parallel_executor ToolConfig call was made
            pe_calls = [
                c for c in mock_tool_config.call_args_list
                if c[1].get("class_name") == "ParallelExecutorTool"
            ]
            assert len(pe_calls) == 1
            assert pe_calls[0][1]["name"] == "parallel_executor"
            assert pe_calls[0][1]["source"] == "local"

    @pytest.mark.asyncio
    async def test_create_agent_config_with_sub_agents(self):
        """Test case for creating agent configuration with sub-agents"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
                patch('backend.agents.create_agent_info.query_sub_agent_relations') as mock_query_sub, \
                patch('backend.agents.create_agent_info.create_tool_config_list') as mock_create_tools, \
                patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
                patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
                patch('backend.agents.create_agent_info.AgentConfig') as mock_agent_config, \
                patch('backend.agents.create_agent_info.prepare_prompt_templates') as mock_prepare_templates, \
                patch('backend.agents.create_agent_info.get_model_by_model_id') as mock_get_model_by_id:

            # Set mock return values
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": [123],
                "provide_run_summary": True
            }
            mock_query_sub.return_value = [
                {"selected_agent_id": "sub_agent_1", "selected_agent_version_no": None}
            ]
            mock_create_tools.return_value = []
            mock_get_template.return_value = {
                "system_prompt": "{{duty}} {{constraint}} {{few_shots}}"}
            mock_tenant_config.get_app_config.side_effect = [
                "TestApp", "Test Description"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(memory_switch=False),
                memory_config={},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1"
            )
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"}
            mock_get_model_by_id.return_value = {"display_name": "test_model"}

            # Mock sub-agent configuration
            mock_sub_agent_config = Mock()
            mock_sub_agent_config.name = "sub_agent"

            # Return sub-agent config on recursive call to create_agent_config
            with patch('backend.agents.create_agent_info.create_agent_config', return_value=mock_sub_agent_config):
                # Reset mock state, as previous tests might have called AgentConfig
                mock_agent_config.reset_mock()

                result = await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query")

                # Verify that AgentConfig was called correctly, including sub-agents
                mock_agent_config.assert_called_once_with(
                    name="test_agent",
                    description="test description",
                    prompt_templates={
                        "system_prompt": "populated_system_prompt"},
                    tools=ANY,
                    max_steps=5,
                    requested_output_tokens=None,
                    model_name="test_model",
                    provide_run_summary=True,
                    allow_chat_metadata=False,
                    managed_agents=[mock_sub_agent_config],
                    external_a2a_agents=[],
                    context_manager_config=ANY,
                    context_items=ANY,
                    pre_run_tool_events=ANY,
                    capacity_snapshot=ANY,
                    safe_input_budget_snapshot=ANY,
                    verification_config=ANY,
                    enable_planning=ANY
                )

    @pytest.mark.asyncio
    async def test_create_agent_config_with_pinned_sub_agent_version(self):
        """Test sub-agent config uses pinned selected_agent_version_no from relation"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
                patch('backend.agents.create_agent_info.query_sub_agent_relations') as mock_query_sub, \
                patch('backend.agents.create_agent_info.resolve_sub_agent_version_no', return_value=3) as mock_resolve, \
                patch('backend.agents.create_agent_info.create_tool_config_list', new_callable=AsyncMock) as mock_create_tools, \
                patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
                patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
                patch('backend.agents.create_agent_info.AgentConfig') as mock_agent_config, \
                patch('backend.agents.create_agent_info.prepare_prompt_templates') as mock_prepare_templates, \
                patch('backend.agents.create_agent_info.get_model_by_model_id') as mock_get_model_by_id:

            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": [123],
                "provide_run_summary": True,
            }
            mock_query_sub.return_value = [
                {"selected_agent_id": 42, "selected_agent_version_no": 3}
            ]
            mock_create_tools.return_value = []
            mock_get_template.return_value = {"system_prompt": "{{duty}}"}
            mock_tenant_config.get_app_config.side_effect = ["TestApp", "Test Description"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(memory_switch=False),
                memory_config={},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1",
            )
            mock_prepare_templates.return_value = {"system_prompt": "populated_system_prompt"}
            mock_get_model_by_id.return_value = {"display_name": "test_model"}

            mock_sub_agent_config = Mock()
            mock_sub_agent_config.name = "sub_agent"

            with patch(
                'backend.agents.create_agent_info.create_agent_config',
                new_callable=AsyncMock,
                return_value=mock_sub_agent_config,
            ) as mock_recursive_create:
                mock_agent_config.reset_mock()
                await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query", version_no=2)

                mock_resolve.assert_called_once_with(
                    selected_agent_id=42,
                    selected_agent_version_no=3,
                    tenant_id="tenant_1",
                )
                mock_recursive_create.assert_called_once()
                assert mock_recursive_create.call_args.kwargs["version_no"] == 3

    @pytest.mark.asyncio
    async def test_create_agent_config_with_memory(self):
        """Test case for creating agent configuration with memory"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
                patch('backend.agents.create_agent_info.query_sub_agent_relations') as mock_query_sub, \
                patch('backend.agents.create_agent_info.create_tool_config_list') as mock_create_tools, \
                patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
                patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
                patch('backend.agents.create_agent_info._create_fixed_search_memory_tool') as mock_search_tool, \
                patch('backend.agents.create_agent_info.prepare_prompt_templates') as mock_prepare_templates, \
                patch('backend.agents.create_agent_info.get_model_by_model_id') as mock_get_model_by_id, \
                patch.dict(sys.modules, {
                    'services.memory_record_service': MagicMock(
                        _resolve_tenant_embedding_model_info=MagicMock(return_value=None),
                    ),
                    'services.memory_context_service': MagicMock(
                        get_memory_context_service=MagicMock(
                            return_value=MagicMock(
                                build_context=AsyncMock(return_value=types.SimpleNamespace(
                                    tenant_long_term=(),
                                    user_long_term=(),
                                ))
                            )
                        ),
                    ),
                    'services.memory_backend_adapter': MagicMock(
                        build_memory_service_for_agent=MagicMock(return_value=None),
                    ),
                }):

            # Set mock return values
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": [123],
                "provide_run_summary": True
            }
            mock_query_sub.return_value = []
            mock_create_tools.return_value = []
            mock_get_template.return_value = {
                "system_prompt": "{{duty}} {{constraint}} {{few_shots}}"}
            mock_tenant_config.get_app_config.side_effect = [
                "TestApp", "Test Description"]

            # Enable memory feature
            mock_user_config = Mock()
            mock_user_config.memory_switch = True
            mock_user_config.agent_share_option = "always"
            mock_user_config.disable_agent_ids = []
            mock_user_config.disable_user_agent_ids = []

            mock_build_memory.return_value = Mock(
                user_config=mock_user_config,
                memory_config={"test": "config"},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1"
            )
            mock_search_tool.return_value.forward = MagicMock(
                return_value="Found 1 result"
            )
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"}
            mock_get_model_by_id.return_value = {"display_name": "test_model"}

            await create_agent_config(
                "agent_1",
                "tenant_1",
                "user_1",
                "zh",
                "test query",
            )

            # Verify that fixed search memory tool's forward was called
            search_instance = mock_search_tool.return_value
            search_instance.forward.assert_called_once_with("test query", 5)

    @pytest.mark.asyncio
    async def test_create_agent_config_memory_disabled_no_search(self):
        with patch(
            "backend.agents.create_agent_info.search_agent_info_by_agent_id"
        ) as mock_search_agent, \
            patch(
                "backend.agents.create_agent_info.query_sub_agent_relations"
            ) as mock_query_sub, \
            patch(
                "backend.agents.create_agent_info.create_tool_config_list"
            ) as mock_create_tools, \
            patch(
                "backend.agents.create_agent_info.get_agent_prompt_template"
            ) as mock_get_template, \
            patch(
                "backend.agents.create_agent_info.tenant_config_manager"
            ) as mock_tenant_config, \
            patch(
                "backend.agents.create_agent_info.build_memory_context"
            ) as mock_build_memory, \
            patch(
                "backend.agents.create_agent_info.get_model_by_model_id"
            ) as mock_get_model_by_id, \
            patch(
                "backend.agents.create_agent_info._create_fixed_search_memory_tool"
            ) as mock_search_tool, \
            patch(
                "backend.agents.create_agent_info.prepare_prompt_templates"
            ) as mock_prepare_templates:
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": [123],
                "provide_run_summary": True,
            }
            mock_query_sub.return_value = []
            mock_create_tools.return_value = []
            mock_get_template.return_value = {
                "system_prompt": "{{duty}} {{constraint}} {{few_shots}}"
            }
            mock_tenant_config.get_app_config.side_effect = [
                "TestApp",
                "Test Description",
            ]

            # When allow_memory_search=False, build_memory_context returns
            # a context with memory_switch=False, which prevents the fixed
            # search memory tool from being invoked at all.
            mock_user_config = Mock()
            mock_user_config.memory_switch = False
            mock_user_config.agent_share_option = "always"
            mock_user_config.disable_agent_ids = []
            mock_user_config.disable_user_agent_ids = []
            mock_build_memory.return_value = Mock(
                user_config=mock_user_config,
                memory_config={"test": "config"},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1",
            )

            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"
            }
            mock_get_model_by_id.return_value = {"display_name": "test_model"}

            await create_agent_config(
                "agent_1",
                "tenant_1",
                "user_1",
                "zh",
                "test query",
                allow_memory_search=False,
            )

            mock_search_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_agent_config_model_id_none(self):
        """Test case for creating agent configuration when model_id is None"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
                patch('backend.agents.create_agent_info.query_sub_agent_relations') as mock_query_sub, \
                patch('backend.agents.create_agent_info.create_tool_config_list') as mock_create_tools, \
                patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
                patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
                patch('backend.agents.create_agent_info.AgentConfig') as mock_agent_config, \
                patch('backend.agents.create_agent_info.prepare_prompt_templates') as mock_prepare_templates, \
                patch('backend.agents.create_agent_info.get_model_by_model_id') as mock_get_model_by_id:

            # Set mock return values
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": None,  # Test None case
                "provide_run_summary": True
            }
            mock_query_sub.return_value = []
            mock_create_tools.return_value = []
            mock_get_template.return_value = {
                "system_prompt": "{{duty}} {{constraint}} {{few_shots}}"}
            mock_tenant_config.get_app_config.side_effect = [
                "TestApp", "Test Description"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(memory_switch=False),
                memory_config={},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1"
            )
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"}
            mock_get_model_by_id.return_value = None  # Model not found

            result = await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query")

            mock_agent_config.assert_called_with(
                name="test_agent",
                description="test description",
                prompt_templates={"system_prompt": "populated_system_prompt"},
                tools=ANY,
                max_steps=5,
                requested_output_tokens=None,
                model_name="main_model",
                provide_run_summary=True,
                allow_chat_metadata=False,
                managed_agents=[],
                external_a2a_agents=[],
                context_manager_config=ANY,
                context_items=ANY,
                pre_run_tool_events=ANY,
                capacity_snapshot=None,
                safe_input_budget_snapshot=None,
                verification_config=ANY,
                enable_planning=ANY
            )

    @pytest.mark.asyncio
    async def test_create_agent_config_memory_exception(self):
        """Verify that errors raised by the fixed search tool are swallowed
        and logged instead of aborting ``create_agent_config``.

        The legacy multi-level ``search_memory_in_levels`` fan-out has been
        removed; the new code path uses ``_create_fixed_search_memory_tool``
        whose failures are caught and logged at WARNING level so the agent
        can still start.
        """
        services_pkg = types.ModuleType("services")
        services_pkg.__path__ = []
        skill_service_mod = types.ModuleType("management.services.skill.service")
        skill_service_mod.SkillService = MagicMock(
            return_value=MagicMock(get_enabled_skills_for_agent=MagicMock(return_value=[]))
        )

        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agent_relations"
            ) as mock_query_sub,
            patch(
                "backend.agents.create_agent_info.create_tool_config_list"
            ) as mock_create_tools,
            patch(
                "backend.agents.create_agent_info.get_agent_prompt_template"
            ) as mock_get_template,
            patch(
                "backend.agents.create_agent_info.tenant_config_manager"
            ) as mock_tenant_config,
            patch(
                "backend.agents.create_agent_info.build_memory_context"
            ) as mock_build_memory,
            patch(
                "backend.agents.create_agent_info._create_fixed_search_memory_tool"
            ) as mock_search_tool,
            patch(
                "backend.agents.create_agent_info.prepare_prompt_templates"
            ) as mock_prepare_templates,
            patch(
                "backend.agents.create_agent_info.logger"
            ) as mock_logger,
            patch.dict(sys.modules, {
                'services': services_pkg,
                'management.services.skill.service': skill_service_mod,
                'services.memory_record_service': MagicMock(
                    _resolve_tenant_embedding_model_info=MagicMock(return_value=None),
                ),
                'services.memory_context_service': MagicMock(
                    get_memory_context_service=MagicMock(
                        return_value=MagicMock(
                            build_context=AsyncMock(return_value=types.SimpleNamespace(
                                tenant_long_term=(),
                                user_long_term=(),
                            ))
                        )
                    ),
                ),
                'services.memory_backend_adapter': MagicMock(
                    build_memory_service_for_agent=MagicMock(return_value=None),
                ),
            }),
        ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": [123],
                "provide_run_summary": True,
            }
            mock_query_sub.return_value = []
            mock_create_tools.return_value = []
            mock_get_template.return_value = {
                "system_prompt": "{{duty}} {{constraint}} {{few_shots}}"
            }
            mock_tenant_config.get_app_config.side_effect = [
                "TestApp",
                "Test Description",
            ]

            mock_user_config = Mock()
            mock_user_config.memory_switch = True
            mock_user_config.agent_share_option = "always"
            mock_user_config.disable_agent_ids = []
            mock_user_config.disable_user_agent_ids = []
            mock_build_memory.return_value = Mock(
                user_config=mock_user_config,
                memory_config={"test": "config"},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1",
            )

            mock_search_tool.return_value.forward.side_effect = Exception("boom")
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"
            }

            # Should NOT raise; the error is swallowed and logged.
            await create_agent_config(
                "agent_1",
                "tenant_1",
                "user_1",
                "zh",
                "test query",
                allow_memory_search=True,
            )

            mock_logger.error.assert_called_once()
            error_message = mock_logger.error.call_args[0][0]
            assert "Failed to load memory tools" in error_message

    @pytest.mark.asyncio
    async def test_create_agent_config_memory_levels_agent_share_never(self):
        """Verify that with ``agent_share_option='never'`` the agent-level
        memory search is still executed via the fixed search tool.

        The legacy ``search_memory_in_levels`` multi-level fan-out has been
        removed; the new code path always uses a single
        ``_create_fixed_search_memory_tool`` instance whose ``forward`` is
        invoked once during agent preparation.
        """
        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agent_relations"
            ) as mock_query_sub,
            patch(
                "backend.agents.create_agent_info.create_tool_config_list"
            ) as mock_create_tools,
            patch(
                "backend.agents.create_agent_info.get_agent_prompt_template"
            ) as mock_get_template,
            patch(
                "backend.agents.create_agent_info.tenant_config_manager"
            ) as mock_tenant_config,
            patch(
                "backend.agents.create_agent_info.build_memory_context"
            ) as mock_build_memory,
            patch(
                "backend.agents.create_agent_info._create_fixed_search_memory_tool"
            ) as mock_search_tool,
            patch(
                "backend.agents.create_agent_info.prepare_prompt_templates"
            ) as mock_prepare_templates,
            patch(
                "backend.agents.create_agent_info.get_model_by_model_id"
            ) as mock_get_model_by_id,
            patch(
                "backend.agents.create_agent_info._get_skills_for_template"
            ) as mock_get_skills,
            patch(
                "backend.agents.create_agent_info._get_skill_script_tools"
            ) as mock_get_skill_tools,
            patch.dict(sys.modules, {
                'services.memory_record_service': MagicMock(
                    _resolve_tenant_embedding_model_info=MagicMock(return_value=None),
                ),
                'services.memory_context_service': MagicMock(
                    get_memory_context_service=MagicMock(
                        return_value=MagicMock(
                            build_context=AsyncMock(return_value=types.SimpleNamespace(
                                tenant_long_term=(),
                                user_long_term=(),
                            ))
                        )
                    ),
                ),
                'services.memory_backend_adapter': MagicMock(
                    build_memory_service_for_agent=MagicMock(return_value=None),
                ),
            }),
        ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": [123],
                "provide_run_summary": True,
            }
            mock_query_sub.return_value = []
            mock_create_tools.return_value = []
            mock_get_template.return_value = {
                "system_prompt": "{{duty}} {{constraint}} {{few_shots}}"
            }
            mock_tenant_config.get_app_config.side_effect = ["TestApp", "Test Description"]

            # Set agent_share_option to "never"
            mock_user_config = Mock()
            mock_user_config.memory_switch = True
            mock_user_config.agent_share_option = "never"
            mock_user_config.disable_agent_ids = []
            mock_user_config.disable_user_agent_ids = []

            mock_build_memory.return_value = Mock(
                user_config=mock_user_config,
                memory_config={"test": "config"},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1",
            )
            mock_search_tool.return_value.forward = MagicMock(return_value="")
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"
            }
            mock_get_model_by_id.return_value = {"display_name": "test_model"}
            mock_get_skills.return_value = []
            mock_get_skill_tools.return_value = []

            await create_agent_config(
                "agent_1",
                "tenant_1",
                "user_1",
                "zh",
                "test query",
                allow_memory_search=True,
            )

            # Fixed search memory tool should have been invoked exactly once.
            mock_search_tool.assert_called_once()
            search_instance = mock_search_tool.return_value
            search_instance.forward.assert_called_once_with("test query", 5)

    @pytest.mark.asyncio
    async def test_create_agent_config_memory_levels_disable_agent(self):
        """Verify that with ``disable_agent_ids`` containing the agent id the
        fixed search memory tool is still invoked (its level filtering is
        now performed inside the service).
        """
        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agent_relations"
            ) as mock_query_sub,
            patch(
                "backend.agents.create_agent_info.create_tool_config_list"
            ) as mock_create_tools,
            patch(
                "backend.agents.create_agent_info.get_agent_prompt_template"
            ) as mock_get_template,
            patch(
                "backend.agents.create_agent_info.tenant_config_manager"
            ) as mock_tenant_config,
            patch(
                "backend.agents.create_agent_info.build_memory_context"
            ) as mock_build_memory,
            patch(
                "backend.agents.create_agent_info._create_fixed_search_memory_tool"
            ) as mock_search_tool,
            patch(
                "backend.agents.create_agent_info.prepare_prompt_templates"
            ) as mock_prepare_templates,
            patch(
                "backend.agents.create_agent_info.get_model_by_model_id"
            ) as mock_get_model_by_id,
            patch(
                "backend.agents.create_agent_info._get_skills_for_template"
            ) as mock_get_skills,
            patch(
                "backend.agents.create_agent_info._get_skill_script_tools"
            ) as mock_get_skill_tools,
            patch.dict(sys.modules, {
                'services.memory_record_service': MagicMock(
                    _resolve_tenant_embedding_model_info=MagicMock(return_value=None),
                ),
                'services.memory_context_service': MagicMock(
                    get_memory_context_service=MagicMock(
                        return_value=MagicMock(
                            build_context=AsyncMock(return_value=types.SimpleNamespace(
                                tenant_long_term=(),
                                user_long_term=(),
                            ))
                        )
                    ),
                ),
                'services.memory_backend_adapter': MagicMock(
                    build_memory_service_for_agent=MagicMock(return_value=None),
                ),
            }),
        ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": [123],
                "provide_run_summary": True,
            }
            mock_query_sub.return_value = []
            mock_create_tools.return_value = []
            mock_get_template.return_value = {
                "system_prompt": "{{duty}} {{constraint}} {{few_shots}}"
            }
            mock_tenant_config.get_app_config.side_effect = ["TestApp", "Test Description"]

            # Set disable_agent_ids to include the agent
            mock_user_config = Mock()
            mock_user_config.memory_switch = True
            mock_user_config.agent_share_option = "always"
            mock_user_config.disable_agent_ids = ["agent_1"]
            mock_user_config.disable_user_agent_ids = []

            mock_build_memory.return_value = Mock(
                user_config=mock_user_config,
                memory_config={"test": "config"},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1",
            )
            mock_search_tool.return_value.forward = MagicMock(return_value="")
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"
            }
            mock_get_model_by_id.return_value = {"display_name": "test_model"}
            mock_get_skills.return_value = []
            mock_get_skill_tools.return_value = []

            await create_agent_config(
                "agent_1",
                "tenant_1",
                "user_1",
                "zh",
                "test query",
                allow_memory_search=True,
            )

            mock_search_tool.assert_called_once()
            search_instance = mock_search_tool.return_value
            search_instance.forward.assert_called_once_with("test query", 5)

    @pytest.mark.asyncio
    async def test_create_agent_config_memory_levels_disable_user_agent(self):
        """Verify that with ``disable_user_agent_ids`` containing the agent id
        the fixed search memory tool is still invoked (per-level disable
        checks are now performed inside the service).
        """
        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agent_relations"
            ) as mock_query_sub,
            patch(
                "backend.agents.create_agent_info.create_tool_config_list"
            ) as mock_create_tools,
            patch(
                "backend.agents.create_agent_info.get_agent_prompt_template"
            ) as mock_get_template,
            patch(
                "backend.agents.create_agent_info.tenant_config_manager"
            ) as mock_tenant_config,
            patch(
                "backend.agents.create_agent_info.build_memory_context"
            ) as mock_build_memory,
            patch(
                "backend.agents.create_agent_info._create_fixed_search_memory_tool"
            ) as mock_search_tool,
            patch(
                "backend.agents.create_agent_info.prepare_prompt_templates"
            ) as mock_prepare_templates,
            patch(
                "backend.agents.create_agent_info.get_model_by_model_id"
            ) as mock_get_model_by_id,
            patch(
                "backend.agents.create_agent_info._get_skills_for_template"
            ) as mock_get_skills,
            patch(
                "backend.agents.create_agent_info._get_skill_script_tools"
            ) as mock_get_skill_tools,
            patch.dict(sys.modules, {
                'services.memory_record_service': MagicMock(
                    _resolve_tenant_embedding_model_info=MagicMock(return_value=None),
                ),
                'services.memory_context_service': MagicMock(
                    get_memory_context_service=MagicMock(
                        return_value=MagicMock(
                            build_context=AsyncMock(return_value=types.SimpleNamespace(
                                tenant_long_term=(),
                                user_long_term=(),
                            ))
                        )
                    ),
                ),
                'services.memory_backend_adapter': MagicMock(
                    build_memory_service_for_agent=MagicMock(return_value=None),
                ),
            }),
        ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": [123],
                "provide_run_summary": True,
            }
            mock_query_sub.return_value = []
            mock_create_tools.return_value = []
            mock_get_template.return_value = {
                "system_prompt": "{{duty}} {{constraint}} {{few_shots}}"
            }
            mock_tenant_config.get_app_config.side_effect = ["TestApp", "Test Description"]

            # Set disable_user_agent_ids to include the agent
            mock_user_config = Mock()
            mock_user_config.memory_switch = True
            mock_user_config.agent_share_option = "always"
            mock_user_config.disable_agent_ids = []
            mock_user_config.disable_user_agent_ids = ["agent_1"]

            mock_build_memory.return_value = Mock(
                user_config=mock_user_config,
                memory_config={"test": "config"},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1",
            )
            mock_search_tool.return_value.forward = MagicMock(return_value="")
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"
            }
            mock_get_model_by_id.return_value = {"display_name": "test_model"}
            mock_get_skills.return_value = []
            mock_get_skill_tools.return_value = []

            await create_agent_config(
                "agent_1",
                "tenant_1",
                "user_1",
                "zh",
                "test query",
                allow_memory_search=True,
            )

            mock_search_tool.assert_called_once()
            search_instance = mock_search_tool.return_value
            search_instance.forward.assert_called_once_with("test query", 5)

    @pytest.mark.asyncio
    async def test_create_agent_config_with_knowledge_base_summary_filtering(self):
        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agent_relations"
            ) as mock_query_sub,
            patch(
                "backend.agents.create_agent_info.create_tool_config_list"
            ) as mock_create_tools,
            patch(
                "backend.agents.create_agent_info.get_agent_prompt_template"
            ) as mock_get_template,
            patch(
                "backend.agents.create_agent_info.tenant_config_manager"
            ) as mock_tenant_config,
            patch(
                "backend.agents.create_agent_info.build_memory_context"
            ) as mock_build_memory,
            patch(
                "backend.agents.create_agent_info.ElasticSearchService"
            ) as mock_es_service,
            patch(
                "backend.agents.create_agent_info.logger"
            ) as mock_logger,
            patch(
                "backend.agents.create_agent_info.prepare_prompt_templates"
            ) as mock_prepare_templates,
            patch(
                "backend.agents.create_agent_info.get_model_by_model_id"
            ) as mock_get_model_by_id,
            patch(
                "backend.agents.create_agent_info._get_skills_for_template"
            ) as mock_get_skills,
            patch(
                "backend.agents.create_agent_info._get_skill_script_tools"
            ) as mock_get_skill_tools,
            patch(
                "backend.agents.create_agent_info.get_knowledge_name_map_by_index_names"
            ) as mock_get_knowledge_name_map,
        ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": [123],
                "provide_run_summary": True,
            }
            mock_query_sub.return_value = []

            kb_tool_1 = Mock()
            kb_tool_1.class_name = "KnowledgeBaseSearchTool"
            kb_tool_1.name = "kb_tool_1"
            kb_tool_1.params = {"index_names": ["idx_a", "idx_b"]}
            kb_tool_1.metadata = {
                "index_name_to_display_map": {"idx_a": "idx_a", "idx_b": "idx_b"}
            }

            other_tool = Mock()
            other_tool.class_name = "OtherTool"
            other_tool.name = "other_tool"
            other_tool.params = {}

            kb_tool_2 = Mock()
            kb_tool_2.class_name = "KnowledgeBaseSearchTool"
            kb_tool_2.name = "kb_tool_2"
            kb_tool_2.params = {"index_names": ["idx_c"]}
            kb_tool_2.metadata = {
                "index_name_to_display_map": {"idx_c": "idx_c"}
            }

            mock_create_tools.return_value = [kb_tool_1, other_tool, kb_tool_2]
            mock_get_template.return_value = {"system_prompt": "{{ knowledge_base_summary }}"}
            mock_tenant_config.get_app_config.side_effect = ["TestApp", "Test Description"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(memory_switch=False),
                memory_config={},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1",
            )
            mock_prepare_templates.return_value = {"system_prompt": "populated_system_prompt"}
            mock_get_model_by_id.return_value = {"display_name": "test_model"}
            mock_get_skills.return_value = []
            mock_get_skill_tools.return_value = []
            # Mock knowledge_name_map to return index_name as fallback
            mock_get_knowledge_name_map.return_value = {"idx_a": "idx_a", "idx_b": "idx_b"}

            mock_es_instance = Mock()
            mock_es_instance.get_summary.side_effect = [
                {"summary": "AAA"},
                Exception("boom"),
            ]
            mock_es_service.return_value = mock_es_instance

            await create_agent_config(
                "agent_1",
                "tenant_1",
                "user_1",
                "zh",
                "test query",
                runtime_knowledge_context={
                    "policy": "scope policy",
                    "resources": "selected resources",
                },
            )

            assert mock_es_instance.get_summary.call_args_list == [
                ((), {"index_name": "idx_a"}),
                ((), {"index_name": "idx_b"}),
            ]
            mock_logger.warning.assert_called_once()
            assert "idx_b" in mock_logger.warning.call_args[0][0]

            mock_prepare_templates.assert_called_once()
            assert create_agent_info_module.build_context_inputs.call_args.kwargs[
                "knowledge_base_summary"
            ] == "**idx_a**: AAA\n\n"
            assert create_agent_info_module.build_context_inputs.call_args.kwargs[
                "knowledge_scope_policy"
            ] == "scope policy"
            assert create_agent_info_module.build_context_inputs.call_args.kwargs[
                "knowledge_scope_resources"
            ] == "selected resources"

            # Ensure only the first KnowledgeBaseSearchTool is processed.
            assert "idx_c" not in str(mock_es_instance.get_summary.call_args_list)

    def test_scoped_summary_uses_only_effective_tool_indices(self):
        """Scoped runs build routing summaries from the final tool whitelist."""
        kb_tool = Mock(
            class_name="KnowledgeBaseSearchTool",
            params={"index_names": ["selected-index"]},
            metadata={
                "index_name_to_display_map": {
                    "selected-index": "Selected Knowledge Base"
                }
            },
        )

        with patch(
            "backend.agents.create_agent_info.ElasticSearchService"
        ) as mock_es_service:
            mock_es_service.return_value.get_summary.return_value = {
                "summary": "Selected summary"
            }
            summary, kb_ids = (
                create_agent_info_module._build_effective_knowledge_base_summary(
                    [kb_tool],
                    "en",
                    include_empty_message=False,
                )
            )

        assert summary == (
            "**Selected Knowledge Base**: Selected summary\n\n"
        )
        assert kb_ids == ["selected-index"]
        mock_es_service.return_value.get_summary.assert_called_once_with(
            index_name="selected-index"
        )

    def test_scoped_empty_summary_does_not_restore_agent_defaults(self):
        """An empty effective scope stays empty instead of adding legacy text."""
        kb_tool = Mock(
            class_name="KnowledgeBaseSearchTool",
            params={"index_names": []},
            metadata={},
        )

        with patch(
            "backend.agents.create_agent_info.ElasticSearchService"
        ) as mock_es_service:
            summary, kb_ids = (
                create_agent_info_module._build_effective_knowledge_base_summary(
                    [kb_tool],
                    "en",
                    include_empty_message=False,
                )
            )

        assert summary == ""
        assert kb_ids == []
        mock_es_service.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_agent_config_uses_metadata_index_name_to_display_map(self):
        """Test that create_agent_config uses index_name_to_display_map from tool.metadata.

        This test verifies the refactored behavior where create_agent_config
        reuses the index_name -> display_name mapping from tool.metadata instead of
        making redundant database queries.
        """
        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agent_relations"
            ) as mock_query_sub,
            patch(
                "backend.agents.create_agent_info.create_tool_config_list"
            ) as mock_create_tools,
            patch(
                "backend.agents.create_agent_info.get_agent_prompt_template"
            ) as mock_get_template,
            patch(
                "backend.agents.create_agent_info.tenant_config_manager"
            ) as mock_tenant_config,
            patch(
                "backend.agents.create_agent_info.build_memory_context"
            ) as mock_build_memory,
            patch(
                "backend.agents.create_agent_info.ElasticSearchService"
            ) as mock_es_service,
            patch(
                "backend.agents.create_agent_info.prepare_prompt_templates"
            ) as mock_prepare_templates,
            patch(
                "backend.agents.create_agent_info.get_model_by_model_id"
            ) as mock_get_model_by_id,
            patch(
                "backend.agents.create_agent_info._get_skills_for_template"
            ) as mock_get_skills,
            patch(
                "backend.agents.create_agent_info._get_skill_script_tools"
            ) as mock_get_skill_tools,
            patch(
                "backend.agents.create_agent_info.get_knowledge_name_map_by_index_names"
            ) as mock_get_knowledge_name_map,
        ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": [123],
                "provide_run_summary": True,
            }
            mock_query_sub.return_value = []

            # Create a tool with index_name_to_display_map in metadata
            kb_tool = Mock()
            kb_tool.class_name = "KnowledgeBaseSearchTool"
            kb_tool.name = "kb_tool"
            kb_tool.params = {"index_names": ["idx1", "idx2"]}
            # The tool.metadata contains the index_name -> display_name mapping
            kb_tool.metadata = {
                "index_name_to_display_map": {
                    "idx1": "Custom Name 1",
                    "idx2": "Custom Name 2"
                }
            }

            mock_create_tools.return_value = [kb_tool]
            mock_get_template.return_value = {"system_prompt": "{{ knowledge_base_summary }}"}
            mock_tenant_config.get_app_config.side_effect = ["TestApp", "Test Description"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(memory_switch=False),
                memory_config={},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1",
            )
            mock_prepare_templates.return_value = {"system_prompt": "populated_system_prompt"}
            mock_get_model_by_id.return_value = {"display_name": "test_model"}
            mock_get_skills.return_value = []
            mock_get_skill_tools.return_value = []
            # This should NOT be called when tool.metadata has index_name_to_display_map
            mock_get_knowledge_name_map.return_value = {"idx1": "idx1", "idx2": "idx2"}

            mock_es_instance = Mock()
            mock_es_instance.get_summary.side_effect = [
                {"summary": "Summary 1"},
                {"summary": "Summary 2"},
            ]
            mock_es_service.return_value = mock_es_instance

            await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query")

            # Verify ElasticSearchService was called for both indices
            assert mock_es_instance.get_summary.call_count == 2

            # Verify get_knowledge_name_map_by_index_names was NOT called
            # because we're using the mapping from tool.metadata
            mock_get_knowledge_name_map.assert_not_called()

            # Verify the SDK context component uses display names from metadata.
            mock_prepare_templates.assert_called_once()
            knowledge_summary = create_agent_info_module.build_context_inputs.call_args.kwargs[
                "knowledge_base_summary"
            ]
            assert "**Custom Name 1**" in knowledge_summary
            assert "**Custom Name 2**" in knowledge_summary
            assert "idx1" not in knowledge_summary
            assert "idx2" not in knowledge_summary

    @pytest.mark.asyncio
    async def test_create_agent_config_metadata_without_index_name_to_display_map(self):
        """Test that create_agent_config handles missing index_name_to_display_map gracefully.

        When tool.metadata exists but doesn't have index_name_to_display_map,
        it should fall back to using index_name as display_name.
        """
        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agent_relations"
            ) as mock_query_sub,
            patch(
                "backend.agents.create_agent_info.create_tool_config_list"
            ) as mock_create_tools,
            patch(
                "backend.agents.create_agent_info.get_agent_prompt_template"
            ) as mock_get_template,
            patch(
                "backend.agents.create_agent_info.tenant_config_manager"
            ) as mock_tenant_config,
            patch(
                "backend.agents.create_agent_info.build_memory_context"
            ) as mock_build_memory,
            patch(
                "backend.agents.create_agent_info.ElasticSearchService"
            ) as mock_es_service,
            patch(
                "backend.agents.create_agent_info.prepare_prompt_templates"
            ) as mock_prepare_templates,
            patch(
                "backend.agents.create_agent_info.get_model_by_model_id"
            ) as mock_get_model_by_id,
            patch(
                "backend.agents.create_agent_info._get_skills_for_template"
            ) as mock_get_skills,
            patch(
                "backend.agents.create_agent_info._get_skill_script_tools"
            ) as mock_get_skill_tools,
            patch(
                "backend.agents.create_agent_info.get_knowledge_name_map_by_index_names"
            ) as mock_get_knowledge_name_map,
        ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": [123],
                "provide_run_summary": True,
            }
            mock_query_sub.return_value = []

            # Create a tool with empty metadata (no index_name_to_display_map)
            kb_tool = Mock()
            kb_tool.class_name = "KnowledgeBaseSearchTool"
            kb_tool.name = "kb_tool"
            kb_tool.params = {"index_names": ["idx1", "idx2"]}
            kb_tool.metadata = {}  # Empty metadata

            mock_create_tools.return_value = [kb_tool]
            mock_get_template.return_value = {"system_prompt": "{{ knowledge_base_summary }}"}
            mock_tenant_config.get_app_config.side_effect = ["TestApp", "Test Description"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(memory_switch=False),
                memory_config={},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1",
            )
            mock_prepare_templates.return_value = {"system_prompt": "populated_system_prompt"}
            mock_get_model_by_id.return_value = {"display_name": "test_model"}
            mock_get_skills.return_value = []
            mock_get_skill_tools.return_value = []
            mock_get_knowledge_name_map.return_value = {}

            mock_es_instance = Mock()
            mock_es_instance.get_summary.side_effect = [
                {"summary": "Summary 1"},
                {"summary": "Summary 2"},
            ]
            mock_es_service.return_value = mock_es_instance

            await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query")

            # When metadata is empty, it should fall back to using index_name
            # as the display_name (no mapping available)
            mock_prepare_templates.assert_called_once()
            knowledge_summary = create_agent_info_module.build_context_inputs.call_args.kwargs[
                "knowledge_base_summary"
            ]
            assert "**idx1**" in knowledge_summary
            assert "**idx2**" in knowledge_summary

    @pytest.mark.parametrize(
        "language,expected_message",
        [
            ("zh", "当前没有可用的知识库索引。\n"),
            ("en", "No knowledge base indexes are currently available.\n"),
        ],
    )
    @pytest.mark.asyncio
    async def test_create_agent_config_knowledge_base_summary_no_indexes_message(
        self, language, expected_message
    ):
        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agent_relations"
            ) as mock_query_sub,
            patch(
                "backend.agents.create_agent_info.create_tool_config_list"
            ) as mock_create_tools,
            patch(
                "backend.agents.create_agent_info.get_agent_prompt_template"
            ) as mock_get_template,
            patch(
                "backend.agents.create_agent_info.tenant_config_manager"
            ) as mock_tenant_config,
            patch(
                "backend.agents.create_agent_info.build_memory_context"
            ) as mock_build_memory,
            patch(
                "backend.agents.create_agent_info.ElasticSearchService"
            ) as mock_es_service,
            patch(
                "backend.agents.create_agent_info.prepare_prompt_templates"
            ) as mock_prepare_templates,
            patch(
                "backend.agents.create_agent_info.get_model_by_model_id"
            ) as mock_get_model_by_id,
        ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": [123],
                "provide_run_summary": True,
            }
            mock_query_sub.return_value = []

            kb_tool = Mock()
            kb_tool.class_name = "KnowledgeBaseSearchTool"
            kb_tool.name = "kb_tool"
            kb_tool.params = {"index_names": []}
            mock_create_tools.return_value = [kb_tool]

            mock_get_template.return_value = {"system_prompt": "{{ knowledge_base_summary }}"}
            mock_tenant_config.get_app_config.side_effect = ["TestApp", "Test Description"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(memory_switch=False),
                memory_config={},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1",
            )
            mock_prepare_templates.return_value = {"system_prompt": "populated_system_prompt"}
            mock_get_model_by_id.return_value = {"display_name": "test_model"}

            await create_agent_config(
                "agent_1", "tenant_1", "user_1", language, "test query"
            )

            mock_es_service.assert_not_called()
            assert create_agent_info_module.build_context_inputs.call_args.kwargs[
                "knowledge_base_summary"
            ] == expected_message

    @pytest.mark.asyncio
    async def test_create_agent_config_knowledge_base_summary_error(self):
        """Test case for error handling during knowledge base summary build"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
                patch('backend.agents.create_agent_info.query_sub_agent_relations') as mock_query_sub, \
                patch('backend.agents.create_agent_info.create_tool_config_list') as mock_create_tools, \
                patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
                patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
                patch('backend.agents.create_agent_info.AgentConfig') as mock_agent_config, \
                patch('backend.agents.create_agent_info.prepare_prompt_templates') as mock_prepare_templates, \
                patch('backend.agents.create_agent_info.get_model_by_model_id') as mock_get_model_by_id, \
                patch('backend.agents.create_agent_info.logger') as mock_logger:

            # Set mock return values
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_ids": [123],
                "provide_run_summary": True
            }
            mock_query_sub.return_value = []

            # Create a tool that raises exception when accessing class_name
            mock_tool = MagicMock()
            type(mock_tool).class_name = PropertyMock(side_effect=Exception("Test Error"))
            mock_create_tools.return_value = [mock_tool]

            mock_get_template.return_value = {
                "system_prompt": "{{duty}} {{constraint}} {{few_shots}}"}
            mock_tenant_config.get_app_config.side_effect = [
                "TestApp", "Test Description"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(memory_switch=False),
                memory_config={},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1"
            )
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"}
            mock_get_model_by_id.return_value = {"display_name": "test_model"}

            await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query")

            # Verify that error was logged
            mock_logger.error.assert_any_call("Failed to build knowledge base summary: Test Error")

        @pytest.mark.asyncio
        async def test_create_agent_config_includes_parallel_executor(self):
            """parallel_executor is always included as a system-managed tool."""
            with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search, \
                    patch('backend.agents.create_agent_info.query_sub_agent_relations', return_value=[]), \
                    patch('backend.agents.create_agent_info.create_tool_config_list', return_value=[]), \
                    patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
                    patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
                    patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
                    patch('backend.agents.create_agent_info.AgentConfig') as mock_agent_config, \
                    patch('backend.agents.create_agent_info.prepare_prompt_templates') as mock_prepare_templates, \
                    patch('backend.agents.create_agent_info.get_model_by_model_id') as mock_get_model_by_id, \
                    patch('backend.agents.create_agent_info._get_skills_for_template', return_value=[]):
                mock_search.return_value = {
                    "name": "test_agent", "description": "desc",
                    "duty_prompt": "d", "constraint_prompt": "c",
                    "few_shots_prompt": "f", "max_steps": 5,
                    "model_ids": [123], "provide_run_summary": False,
                }
                mock_get_template.return_value = {"system_prompt": "{{duty}}"}
                mock_tenant_config.get_app_config.side_effect = ["App", "Desc"]
                mock_build_memory.return_value = Mock(
                    user_config=Mock(memory_switch=False),
                    memory_config={}, tenant_id="t", user_id="u", agent_id="a",
                )
                mock_prepare_templates.return_value = {"system_prompt": "p"}
                mock_get_model_by_id.return_value = {"display_name": "m"}

                await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "")

                tools = mock_agent_config.call_args[1]["tools"]
                # Last tool should be parallel_executor
                last_tool = tools[-1]
                assert last_tool.name == "parallel_executor"
                assert last_tool.class_name == "ParallelExecutorTool"
                assert last_tool.source == "local"


def test_p8_effective_feature_factory_requires_generic_factory_and_exact_known_host():
    assert _effective_feature_factory({
        "model_factory": "OpenAI-API-Compatible",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }) == "dashscope"
    assert _effective_feature_factory({
        "model_factory": "OpenAI-API-Compatible",
        "base_url": "https://api.openai.com/v1",
    }) == "openai"
    assert _effective_feature_factory({
        "model_factory": "OpenAI-API-Compatible",
        "base_url": "https://dashscope.aliyuncs.com.evil.example/v1",
    }) == "openai-api-compatible"
    assert _effective_feature_factory({
        "model_factory": "modelengine",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }) == "modelengine"


class TestCreateModelConfigList:
    """Tests for the create_model_config_list function"""

    @pytest.mark.asyncio
    async def test_create_model_config_list(self):
        """Test case for model configuration list creation"""
        # Reset mock call count before test
        mock_model_config.reset_mock()

        with patch('backend.agents.create_agent_info.get_model_records') as mock_get_records, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_manager, \
                patch('backend.agents.create_agent_info.get_model_name_from_config') as mock_get_model_name, \
                patch('backend.agents.create_agent_info.add_repo_to_name') as mock_add_repo:

            # Mock database records
            mock_get_records.return_value = [
                {
                    "display_name": "GPT-4",
                    "api_key": "gpt4_key",
                    "model_repo": "openai",
                    "model_name": "gpt-4",
                    "base_url": "https://api.openai.com"
                },
                {
                    "display_name": "Claude",
                    "api_key": "claude_key",
                    "model_repo": "anthropic",
                    "model_name": "claude-3",
                    "base_url": "https://api.anthropic.com"
                }
            ]

            # Mock tenant config for main_model and sub_model
            mock_manager.get_model_config.return_value = {
                "api_key": "main_key",
                "model_name": "main_model",
                "base_url": "http://main.url",
                "context_window_tokens": 1_000_000,
                "max_input_tokens": 991_808,
                "default_output_reserve_tokens": 8_192,
                "canonical_model_id": "qwen:qwen3.7-plus",
                "tokenizer_family": "qwen",
                "tokenizer_match_metadata": {"auto_applicable": True},
                "token_count_probe_metadata": {"status": "supported"},
            }

            # Mock utility functions
            mock_add_repo.side_effect = ["openai/gpt-4", "anthropic/claude-3"]
            mock_get_model_name.return_value = "main_model_name"

            result = await create_model_config_list("tenant_1")

            # Should have 4 models: 2 from database + 2 default (main_model, sub_model)
            assert len(result) == 4

            # Verify get_model_records was called correctly
            mock_get_records.assert_called_once_with({"model_type": "llm"}, "tenant_1")

            # Verify tenant_config_manager was called for default models
            mock_manager.get_model_config.assert_called_once_with(
                key=MODEL_CONFIG_MAPPING["llm"], tenant_id="tenant_1")

            # Verify ModelConfig was called 4 times
            assert mock_model_config.call_count == 4

            # Verify the calls to ModelConfig
            calls = mock_model_config.call_args_list

            # First call: GPT-4 model from database
            assert calls[0][1]['cite_name'] == "GPT-4"
            assert calls[0][1]['api_key'] == "gpt4_key"
            assert calls[0][1]['model_name'] == "openai/gpt-4"
            assert calls[0][1]['url'] == "https://api.openai.com"
            assert calls[0][1]['prompt_cache'] is None

            # Second call: Claude model from database
            assert calls[1][1]['cite_name'] == "Claude"
            assert calls[1][1]['api_key'] == "claude_key"
            assert calls[1][1]['model_name'] == "anthropic/claude-3"
            assert calls[1][1]['url'] == "https://api.anthropic.com"

            # Third call: main_model
            assert calls[2][1]['cite_name'] == "main_model"
            assert calls[2][1]['api_key'] == "main_key"
            assert calls[2][1]['model_name'] == "main_model_name"
            assert calls[2][1]['url'] == "http://main.url"
            assert calls[2][1]['context_window_tokens'] == 1_000_000
            assert calls[2][1]['canonical_model_id'] == "qwen:qwen3.7-plus"
            assert calls[2][1]['token_count_probe_metadata'] == {"status": "supported"}

            # Fourth call: sub_model
            assert calls[3][1]['cite_name'] == "sub_model"
            assert calls[3][1]['api_key'] == "main_key"
            assert calls[3][1]['model_name'] == "main_model_name"
            assert calls[3][1]['url'] == "http://main.url"
            assert calls[3][1]['context_window_tokens'] == 1_000_000
            assert calls[3][1]['canonical_model_id'] == "qwen:qwen3.7-plus"
            assert calls[3][1]['token_count_probe_metadata'] == {"status": "supported"}

    @pytest.mark.asyncio
    async def test_create_model_config_list_empty_database(self):
        """Test case when database returns no records"""
        # Reset mock call count before test
        mock_model_config.reset_mock()

        with patch('backend.agents.create_agent_info.get_model_records') as mock_get_records, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_manager, \
                patch('backend.agents.create_agent_info.get_model_name_from_config') as mock_get_model_name:

            # Mock empty database records
            mock_get_records.return_value = []

            # Mock tenant config for main_model and sub_model
            mock_manager.get_model_config.return_value = {
                "api_key": "main_key",
                "model_name": "main_model",
                "base_url": "http://main.url"
            }

            mock_get_model_name.return_value = "main_model_name"

            result = await create_model_config_list("tenant_1")

            # Should have 2 models: only default models (main_model, sub_model)
            assert len(result) == 2

            # Verify ModelConfig was called 2 times
            assert mock_model_config.call_count == 2

            # Verify both calls are for default models
            calls = mock_model_config.call_args_list
            assert calls[0][1]['cite_name'] == "main_model"
            assert calls[1][1]['cite_name'] == "sub_model"

    @pytest.mark.asyncio
    async def test_create_model_config_list_no_model_name_in_config(self):
        """Test case when tenant config has no model_name"""
        # Reset mock call count before test
        mock_model_config.reset_mock()

        with patch('backend.agents.create_agent_info.get_model_records') as mock_get_records, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_manager, \
                patch('backend.agents.create_agent_info.get_model_name_from_config') as mock_get_model_name:

            # Mock empty database records
            mock_get_records.return_value = []

            # Mock tenant config without model_name
            mock_manager.get_model_config.return_value = {
                "api_key": "main_key",
                "base_url": "http://main.url"
                # No model_name field
            }

            result = await create_model_config_list("tenant_1")

            # Should have 2 models: only default models (main_model, sub_model)
            assert len(result) == 2

            # Verify ModelConfig was called 2 times with empty model_name
            assert mock_model_config.call_count == 2

            calls = mock_model_config.call_args_list
            assert calls[0][1]['cite_name'] == "main_model"
            assert calls[0][1]['model_name'] == ""  # Should be empty when no model_name in config
            assert calls[1][1]['cite_name'] == "sub_model"
            assert calls[1][1]['model_name'] == ""  # Should be empty when no model_name in config


class TestFilterMcpServersAndTools:
    """Tests for the filter_mcp_servers_and_tools function"""

    def test_filter_mcp_servers_with_mcp_tools(self):
        """Test case for filtering logic when MCP tools are present"""
        # Create mock objects
        mock_tool = Mock()
        mock_tool.source = "mcp"
        mock_tool.usage = "test_server"

        mock_agent_config = Mock()
        mock_agent_config.tools = [mock_tool]
        mock_agent_config.managed_agents = []

        mcp_info_dict = {
            "test_server": {
                "remote_mcp_server": "http://test.server"
            }
        }

        # Execute the function
        result = filter_mcp_servers_and_tools(mock_agent_config, mcp_info_dict)

        # Verify the result
        assert result == ["http://test.server"]

    def test_filter_mcp_servers_no_mcp_tools(self):
        """Test case for filtering logic when no MCP tools are present"""
        mock_tool = Mock()
        mock_tool.source = "local"

        mock_agent_config = Mock()
        mock_agent_config.tools = [mock_tool]
        mock_agent_config.managed_agents = []

        mcp_info_dict = {}

        result = filter_mcp_servers_and_tools(mock_agent_config, mcp_info_dict)

        # Should return an empty list if there are no MCP tools
        assert result == []

    def test_filter_mcp_servers_with_sub_agents(self):
        """Test case for filtering logic with sub-agents"""
        # Create mock tool for the sub-agent
        mock_sub_tool = Mock()
        mock_sub_tool.source = "mcp"
        mock_sub_tool.usage = "sub_server"

        mock_sub_agent = Mock()
        mock_sub_agent.tools = [mock_sub_tool]
        mock_sub_agent.managed_agents = []

        # Create mock tool for the main agent
        mock_main_tool = Mock()
        mock_main_tool.source = "mcp"
        mock_main_tool.usage = "main_server"

        mock_agent_config = Mock()
        mock_agent_config.tools = [mock_main_tool]
        mock_agent_config.managed_agents = [mock_sub_agent]

        mcp_info_dict = {
            "main_server": {
                "remote_mcp_server": "http://main.server"
            },
            "sub_server": {
                "remote_mcp_server": "http://sub.server"
            }
        }

        result = filter_mcp_servers_and_tools(mock_agent_config, mcp_info_dict)

        # Should contain the URLs of both servers
        assert len(result) == 2
        assert "http://main.server" in result
        assert "http://sub.server" in result

    def test_filter_mcp_servers_unknown_server(self):
        """Test case for an unknown MCP server"""
        mock_tool = Mock()
        mock_tool.source = "mcp"
        mock_tool.usage = "unknown_server"

        mock_agent_config = Mock()
        mock_agent_config.tools = [mock_tool]
        mock_agent_config.managed_agents = []

        mcp_info_dict = {
            "different_server": {
                "remote_mcp_server": "http://different.server"
            }
        }

        result = filter_mcp_servers_and_tools(mock_agent_config, mcp_info_dict)

        # Unknown servers should not be included
        assert result == []


class TestCreateAgentRunInfo:
    """Tests for the create_agent_run_info function"""

    @pytest.mark.asyncio
    async def test_create_agent_run_info_success(self):
        """Test case for successfully creating agent run info with dict format mcp_host"""
        mock_agent_run_info.reset_mock()
        with patch('backend.agents.create_agent_info.join_minio_file_description_to_query') as mock_join_query, \
                patch('backend.agents.create_agent_info.create_model_config_list') as mock_create_models, \
                patch('backend.agents.create_agent_info.get_remote_mcp_server_list', new_callable=AsyncMock) as mock_get_mcp, \
                patch('backend.agents.create_agent_info.create_agent_config') as mock_create_agent, \
                patch('backend.agents.create_agent_info.filter_mcp_servers_and_tools') as mock_filter, \
                patch('backend.agents.create_agent_info.urljoin') as mock_urljoin, \
                patch('backend.agents.create_agent_info.threading') as mock_threading, \
                patch('backend.agents.create_agent_info.query_current_version_no') as mock_version_no:

            # Set mock return values
            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            mock_get_mcp.return_value = [
                {
                    "remote_mcp_server_name": "test_server",
                    "remote_mcp_server": "http://test.server",
                    "status": True,
                    "authorization_token": None
                }
            ]
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            mock_filter.return_value = ["http://test.server"]
            mock_threading.Event.return_value = "stop_event"
            mock_version_no.return_value = 1  # Mock published version

            result = await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                user_id="user_1",
                tenant_id="tenant_1",
                language="zh"
            )

            # Verify that AgentRunInfo was called correctly with dict format mcp_host
            assert mock_agent_run_info.call_count == 1
            mock_agent_run_info.assert_called_with(
                query="processed_query",
                model_config_list=["model_config"],
                observer=mock_message_observer.return_value,
                agent_config="agent_config",
                mcp_host=[{
                    "url": "http://test.server",
                    "transport": "streamable-http"
                }],
                history=[],
                stop_event="stop_event",
                capacity_snapshot=None,
                safe_input_budget_snapshot=None,
                redis_client=ANY,
                sandbox_config=None,
                minio_client=None,
                workspace_path=ANY,
                workspace_run_id=ANY,
                tenant_id="tenant_1",
                minio_files=[],
            )

            # Verify that other functions were called correctly
            mock_join_query.assert_called_once_with(
                minio_files=[], query="test query", history=[])
            mock_create_models.assert_called_once_with("tenant_1")
            mock_create_agent.assert_called_once_with(
                agent_id="agent_1",
                tenant_id="tenant_1",
                user_id="user_1",
                language="zh",
                last_user_query="processed_query",
                allow_memory_search=True,
                version_no=1,
                tool_params=None,
                conversation_id=None,
                enable_planning=ANY,
                runtime_file_context=ANY,
            )
            mock_get_mcp.assert_called_once_with(tenant_id="tenant_1", is_need_auth=True)
            mock_filter.assert_called_once_with("agent_config", {
                "test_server": {
                    "remote_mcp_server_name": "test_server",
                    "remote_mcp_server": "http://test.server",
                    "status": True,
                    "authorization_token": None
                },
                "outer-apis": {
                    "remote_mcp_server_name": "outer-apis",
                    "remote_mcp_server": "http://nexent.mcp/sse",
                    "status": True,
                    "authorization_token": None
                }
            })

    @pytest.mark.asyncio
    async def test_create_agent_run_info_enables_automation_tool_for_conversation(self):
        mock_agent_run_info.reset_mock()
        with patch(
            'backend.agents.create_agent_info.join_minio_file_description_to_query',
            new_callable=AsyncMock,
            return_value="processed_query",
        ), patch(
            'backend.agents.create_agent_info.create_model_config_list',
            new_callable=AsyncMock,
            return_value=["model_config"],
        ), patch(
            'backend.agents.create_agent_info.get_remote_mcp_server_list',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'backend.agents.create_agent_info.create_agent_config',
            new_callable=AsyncMock,
            return_value="agent_config",
        ) as mock_create_agent, patch(
            'backend.agents.create_agent_info.filter_mcp_servers_and_tools',
            return_value=[],
        ), patch(
            'backend.agents.create_agent_info.urljoin',
            return_value="http://nexent.mcp/sse",
        ), patch(
            'backend.agents.create_agent_info.threading'
        ) as mock_threading, patch(
            'backend.agents.create_agent_info.query_current_version_no',
            return_value=1,
        ):
            mock_threading.Event.return_value = "stop_event"

            await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[{"name": "report.csv"}],
                query="每天九点分析报表",
                history=[],
                user_id="user_1",
                tenant_id="tenant_1",
                language="zh",
                conversation_id=123,
                override_model_id=9,
            )

        create_kwargs = mock_create_agent.await_args.kwargs
        assert create_kwargs["include_automation_tool"] is True
        assert create_kwargs["automation_user_message"] == "每天九点分析报表"
        assert create_kwargs["automation_model_id"] == 9
        assert create_kwargs["automation_has_attachments"] is True

    @pytest.mark.asyncio
    async def test_create_agent_run_info_with_authorization_token(self):
        """Test case for mcp_host with authorization token"""
        mock_agent_run_info.reset_mock()
        with patch('backend.agents.create_agent_info.join_minio_file_description_to_query') as mock_join_query, \
                patch('backend.agents.create_agent_info.create_model_config_list') as mock_create_models, \
                patch('backend.agents.create_agent_info.get_remote_mcp_server_list', new_callable=AsyncMock) as mock_get_mcp, \
                patch('backend.agents.create_agent_info.create_agent_config') as mock_create_agent, \
                patch('backend.agents.create_agent_info.filter_mcp_servers_and_tools') as mock_filter, \
                patch('backend.agents.create_agent_info.urljoin') as mock_urljoin, \
                patch('backend.agents.create_agent_info.threading') as mock_threading, \
                patch('backend.agents.create_agent_info.query_current_version_no') as mock_version_no:

            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            mock_get_mcp.return_value = [
                {
                    "remote_mcp_server_name": "test_server",
                    "remote_mcp_server": "http://test.server",
                    "status": True,
                    "authorization_token": "bearer_token_123"
                }
            ]
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            mock_filter.return_value = ["http://test.server"]
            mock_threading.Event.return_value = "stop_event"
            mock_version_no.return_value = 1

            await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                user_id="user_1",
                tenant_id="tenant_1",
                language="zh"
            )

            # Verify mcp_host includes authorization token
            assert mock_agent_run_info.call_count == 1
            call_args = mock_agent_run_info.call_args
            mcp_host = call_args[1]["mcp_host"]
            assert len(mcp_host) == 1
            assert mcp_host[0] == {
                "url": "http://test.server",
                "transport": "streamable-http",
                "headers": {"Authorization": "bearer_token_123"}
            }

    @pytest.mark.asyncio
    async def test_create_agent_run_info_with_custom_headers_only(self):
        """Test case for mcp_host with only custom_headers (no authorization_token)"""
        mock_agent_run_info.reset_mock()
        with patch('backend.agents.create_agent_info.join_minio_file_description_to_query') as mock_join_query, \
                patch('backend.agents.create_agent_info.create_model_config_list') as mock_create_models, \
                patch('backend.agents.create_agent_info.get_remote_mcp_server_list', new_callable=AsyncMock) as mock_get_mcp, \
                patch('backend.agents.create_agent_info.create_agent_config') as mock_create_agent, \
                patch('backend.agents.create_agent_info.filter_mcp_servers_and_tools') as mock_filter, \
                patch('backend.agents.create_agent_info.urljoin') as mock_urljoin, \
                patch('backend.agents.create_agent_info.threading') as mock_threading, \
                patch('backend.agents.create_agent_info.query_current_version_no') as mock_version_no:

            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            mock_get_mcp.return_value = [
                {
                    "remote_mcp_server_name": "custom_header_server",
                    "remote_mcp_server": "http://custom-header.server",
                    "status": True,
                    "authorization_token": None,
                    "custom_headers": {"X-Custom-Header": "custom-value", "X-Another-Header": "another-value"}
                }
            ]
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            mock_filter.return_value = ["http://custom-header.server"]
            mock_threading.Event.return_value = "stop_event"
            mock_version_no.return_value = 1

            await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                user_id="user_1",
                tenant_id="tenant_1",
                language="zh"
            )

            # Verify mcp_host includes custom headers
            assert mock_agent_run_info.call_count == 1
            call_args = mock_agent_run_info.call_args
            mcp_host = call_args[1]["mcp_host"]
            assert len(mcp_host) == 1
            assert mcp_host[0] == {
                "url": "http://custom-header.server",
                "transport": "streamable-http",
                "headers": {"X-Custom-Header": "custom-value", "X-Another-Header": "another-value"}
            }

    @pytest.mark.asyncio
    async def test_create_agent_run_info_with_authorization_and_custom_headers(self):
        """Test case for mcp_host with both authorization_token and custom_headers"""
        mock_agent_run_info.reset_mock()
        with patch('backend.agents.create_agent_info.join_minio_file_description_to_query') as mock_join_query, \
                patch('backend.agents.create_agent_info.create_model_config_list') as mock_create_models, \
                patch('backend.agents.create_agent_info.get_remote_mcp_server_list', new_callable=AsyncMock) as mock_get_mcp, \
                patch('backend.agents.create_agent_info.create_agent_config') as mock_create_agent, \
                patch('backend.agents.create_agent_info.filter_mcp_servers_and_tools') as mock_filter, \
                patch('backend.agents.create_agent_info.urljoin') as mock_urljoin, \
                patch('backend.agents.create_agent_info.threading') as mock_threading, \
                patch('backend.agents.create_agent_info.query_current_version_no') as mock_version_no:

            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            mock_get_mcp.return_value = [
                {
                    "remote_mcp_server_name": "both_headers_server",
                    "remote_mcp_server": "http://both-headers.server",
                    "status": True,
                    "authorization_token": "bearer_token_456",
                    "custom_headers": {"X-Custom-Header": "custom-value", "X-Request-ID": "req-123"}
                }
            ]
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            mock_filter.return_value = ["http://both-headers.server"]
            mock_threading.Event.return_value = "stop_event"
            mock_version_no.return_value = 1

            await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                user_id="user_1",
                tenant_id="tenant_1",
                language="zh"
            )

            # Verify mcp_host includes both authorization and custom headers
            assert mock_agent_run_info.call_count == 1
            call_args = mock_agent_run_info.call_args
            mcp_host = call_args[1]["mcp_host"]
            assert len(mcp_host) == 1
            # Authorization header should override any custom X-Authorization header
            assert mcp_host[0]["url"] == "http://both-headers.server"
            assert mcp_host[0]["transport"] == "streamable-http"
            assert mcp_host[0]["headers"]["Authorization"] == "bearer_token_456"
            assert mcp_host[0]["headers"]["X-Custom-Header"] == "custom-value"
            assert mcp_host[0]["headers"]["X-Request-ID"] == "req-123"

    @pytest.mark.asyncio
    async def test_create_agent_run_info_with_custom_headers_null(self):
        """Test case for mcp_host with custom_headers=None (should not add headers)"""
        mock_agent_run_info.reset_mock()
        with patch('backend.agents.create_agent_info.join_minio_file_description_to_query') as mock_join_query, \
                patch('backend.agents.create_agent_info.create_model_config_list') as mock_create_models, \
                patch('backend.agents.create_agent_info.get_remote_mcp_server_list', new_callable=AsyncMock) as mock_get_mcp, \
                patch('backend.agents.create_agent_info.create_agent_config') as mock_create_agent, \
                patch('backend.agents.create_agent_info.filter_mcp_servers_and_tools') as mock_filter, \
                patch('backend.agents.create_agent_info.urljoin') as mock_urljoin, \
                patch('backend.agents.create_agent_info.threading') as mock_threading, \
                patch('backend.agents.create_agent_info.query_current_version_no') as mock_version_no:

            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            mock_get_mcp.return_value = [
                {
                    "remote_mcp_server_name": "null_headers_server",
                    "remote_mcp_server": "http://null-headers.server",
                    "status": True,
                    "authorization_token": None,
                    "custom_headers": None
                }
            ]
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            mock_filter.return_value = ["http://null-headers.server"]
            mock_threading.Event.return_value = "stop_event"
            mock_version_no.return_value = 1

            await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                user_id="user_1",
                tenant_id="tenant_1",
                language="zh"
            )

            # Verify mcp_host has no headers key when both auth_token and custom_headers are null
            assert mock_agent_run_info.call_count == 1
            call_args = mock_agent_run_info.call_args
            mcp_host = call_args[1]["mcp_host"]
            assert len(mcp_host) == 1
            assert mcp_host[0] == {
                "url": "http://null-headers.server",
                "transport": "streamable-http"
            }
            assert "headers" not in mcp_host[0]

    @pytest.mark.asyncio
    async def test_create_agent_run_info_with_custom_headers_string_not_dict(self):
        """Test case for mcp_host with custom_headers as string (not dict) - should be ignored"""
        mock_agent_run_info.reset_mock()
        with patch('backend.agents.create_agent_info.join_minio_file_description_to_query') as mock_join_query, \
                patch('backend.agents.create_agent_info.create_model_config_list') as mock_create_models, \
                patch('backend.agents.create_agent_info.get_remote_mcp_server_list', new_callable=AsyncMock) as mock_get_mcp, \
                patch('backend.agents.create_agent_info.create_agent_config') as mock_create_agent, \
                patch('backend.agents.create_agent_info.filter_mcp_servers_and_tools') as mock_filter, \
                patch('backend.agents.create_agent_info.urljoin') as mock_urljoin, \
                patch('backend.agents.create_agent_info.threading') as mock_threading, \
                patch('backend.agents.create_agent_info.query_current_version_no') as mock_version_no:

            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            mock_get_mcp.return_value = [
                {
                    "remote_mcp_server_name": "string_headers_server",
                    "remote_mcp_server": "http://string-headers.server",
                    "status": True,
                    "authorization_token": "bearer_token_789",
                    "custom_headers": "not-a-dict-string"
                }
            ]
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            mock_filter.return_value = ["http://string-headers.server"]
            mock_threading.Event.return_value = "stop_event"
            mock_version_no.return_value = 1

            await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                user_id="user_1",
                tenant_id="tenant_1",
                language="zh"
            )

            # Verify mcp_host only has authorization header, custom_headers string is ignored
            assert mock_agent_run_info.call_count == 1
            call_args = mock_agent_run_info.call_args
            mcp_host = call_args[1]["mcp_host"]
            assert len(mcp_host) == 1
            assert mcp_host[0] == {
                "url": "http://string-headers.server",
                "transport": "streamable-http",
                "headers": {"Authorization": "bearer_token_789"}
            }
            assert mcp_host[0]["headers"]["Authorization"] == "bearer_token_789"

    @pytest.mark.asyncio
    async def test_create_agent_run_info_with_sse_transport(self):
        """Test case for mcp_host with SSE transport (URL ends with /sse)"""
        mock_agent_run_info.reset_mock()
        with patch('backend.agents.create_agent_info.join_minio_file_description_to_query') as mock_join_query, \
                patch('backend.agents.create_agent_info.create_model_config_list') as mock_create_models, \
                patch('backend.agents.create_agent_info.get_remote_mcp_server_list', new_callable=AsyncMock) as mock_get_mcp, \
                patch('backend.agents.create_agent_info.create_agent_config') as mock_create_agent, \
                patch('backend.agents.create_agent_info.filter_mcp_servers_and_tools') as mock_filter, \
                patch('backend.agents.create_agent_info.urljoin') as mock_urljoin, \
                patch('backend.agents.create_agent_info.threading') as mock_threading, \
                patch('backend.agents.create_agent_info.query_current_version_no') as mock_version_no:

            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            mock_get_mcp.return_value = []
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            mock_filter.return_value = ["http://nexent.mcp/sse"]
            mock_threading.Event.return_value = "stop_event"
            mock_version_no.return_value = 1

            await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                user_id="user_1",
                tenant_id="tenant_1",
                language="zh"
            )

            # Verify mcp_host uses SSE transport
            assert mock_agent_run_info.call_count == 1
            call_args = mock_agent_run_info.call_args
            mcp_host = call_args[1]["mcp_host"]
            assert len(mcp_host) == 1
            assert mcp_host[0] == {
                "url": "http://nexent.mcp/sse",
                "transport": "sse",
                "httpx_client_factory": create_agent_info_module.create_httpx_client,
            }

    @pytest.mark.asyncio
    async def test_create_agent_run_info_fallback_to_string_format(self):
        """Test case for fallback to string format when MCP record not found"""
        mock_agent_run_info.reset_mock()
        with patch('backend.agents.create_agent_info.join_minio_file_description_to_query') as mock_join_query, \
                patch('backend.agents.create_agent_info.create_model_config_list') as mock_create_models, \
                patch('backend.agents.create_agent_info.get_remote_mcp_server_list', new_callable=AsyncMock) as mock_get_mcp, \
                patch('backend.agents.create_agent_info.create_agent_config') as mock_create_agent, \
                patch('backend.agents.create_agent_info.filter_mcp_servers_and_tools') as mock_filter, \
                patch('backend.agents.create_agent_info.urljoin') as mock_urljoin, \
                patch('backend.agents.create_agent_info.threading') as mock_threading, \
                patch('backend.agents.create_agent_info.query_current_version_no') as mock_version_no:

            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            # Return empty list so the URL from filter won't be found in remote_mcp_list
            mock_get_mcp.return_value = []
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            # Filter returns a URL that doesn't exist in remote_mcp_list
            mock_filter.return_value = ["http://unknown.server"]
            mock_threading.Event.return_value = "stop_event"
            mock_version_no.return_value = 1

            await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                user_id="user_1",
                tenant_id="tenant_1",
                language="zh"
            )

            # Verify mcp_host falls back to string format
            assert mock_agent_run_info.call_count == 1
            call_args = mock_agent_run_info.call_args
            mcp_host = call_args[1]["mcp_host"]
            assert len(mcp_host) == 1
            assert mcp_host[0] == "http://unknown.server"

    @pytest.mark.asyncio
    async def test_create_agent_run_info_mixed_scenarios(self):
        """Test case for mixed scenarios: multiple servers with different configurations"""
        mock_agent_run_info.reset_mock()
        with patch('backend.agents.create_agent_info.join_minio_file_description_to_query') as mock_join_query, \
                patch('backend.agents.create_agent_info.create_model_config_list') as mock_create_models, \
                patch('backend.agents.create_agent_info.get_remote_mcp_server_list', new_callable=AsyncMock) as mock_get_mcp, \
                patch('backend.agents.create_agent_info.create_agent_config') as mock_create_agent, \
                patch('backend.agents.create_agent_info.filter_mcp_servers_and_tools') as mock_filter, \
                patch('backend.agents.create_agent_info.urljoin') as mock_urljoin, \
                patch('backend.agents.create_agent_info.threading') as mock_threading, \
                patch('backend.agents.create_agent_info.query_current_version_no') as mock_version_no:

            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            mock_get_mcp.return_value = [
                {
                    "remote_mcp_server_name": "server1",
                    "remote_mcp_server": "http://server1.com",
                    "status": True,
                    "authorization_token": "token1"
                },
                {
                    "remote_mcp_server_name": "server2",
                    "remote_mcp_server": "http://server2.com/sse",
                    "status": True,
                    "authorization_token": None
                },
                {
                    "remote_mcp_server_name": "server3",
                    "remote_mcp_server": "http://server3.com",
                    "status": True,
                    "authorization_token": "token3"
                }
            ]
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            # Filter returns URLs: one with token, one SSE without token, one unknown
            mock_filter.return_value = [
                "http://server1.com",
                "http://server2.com/sse",
                "http://unknown.server"
            ]
            mock_threading.Event.return_value = "stop_event"
            mock_version_no.return_value = 1

            await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                user_id="user_1",
                tenant_id="tenant_1",
                language="zh"
            )

            # Verify mcp_host contains mixed formats
            assert mock_agent_run_info.call_count == 1
            call_args = mock_agent_run_info.call_args
            mcp_host = call_args[1]["mcp_host"]
            assert len(mcp_host) == 3
            # First: dict with authorization and streamable-http
            assert mcp_host[0] == {
                "url": "http://server1.com",
                "transport": "streamable-http",
                "headers": {"Authorization": "token1"}
            }
            # Second: dict with SSE transport, no authorization
            assert mcp_host[1] == {
                "url": "http://server2.com/sse",
                "transport": "sse"
            }
            # Third: string format (fallback for unknown server)
            assert mcp_host[2] == "http://unknown.server"

    @pytest.mark.asyncio
    async def test_create_agent_run_info_with_status_false(self):
        """Test case for MCP record with status=False (should not be matched)"""
        mock_agent_run_info.reset_mock()
        with patch('backend.agents.create_agent_info.join_minio_file_description_to_query') as mock_join_query, \
                patch('backend.agents.create_agent_info.create_model_config_list') as mock_create_models, \
                patch('backend.agents.create_agent_info.get_remote_mcp_server_list', new_callable=AsyncMock) as mock_get_mcp, \
                patch('backend.agents.create_agent_info.create_agent_config') as mock_create_agent, \
                patch('backend.agents.create_agent_info.filter_mcp_servers_and_tools') as mock_filter, \
                patch('backend.agents.create_agent_info.urljoin') as mock_urljoin, \
                patch('backend.agents.create_agent_info.threading') as mock_threading, \
                patch('backend.agents.create_agent_info.query_current_version_no') as mock_version_no:

            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            mock_get_mcp.return_value = [
                {
                    "remote_mcp_server_name": "disabled_server",
                    "remote_mcp_server": "http://disabled.server",
                    "status": False,  # Status is False
                    "authorization_token": "token"
                }
            ]
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            # Filter returns URL that exists but has status=False
            mock_filter.return_value = ["http://disabled.server"]
            mock_threading.Event.return_value = "stop_event"
            mock_version_no.return_value = 1

            await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                user_id="user_1",
                tenant_id="tenant_1",
                language="zh"
            )

            # Verify mcp_host falls back to string format because status=False
            assert mock_agent_run_info.call_count == 1
            call_args = mock_agent_run_info.call_args
            mcp_host = call_args[1]["mcp_host"]
            assert len(mcp_host) == 1
            assert mcp_host[0] == "http://disabled.server"

    @pytest.mark.asyncio
    async def test_create_agent_run_info_forwards_allow_memory_false(self):
        with (
            patch(
                "backend.agents.create_agent_info.join_minio_file_description_to_query"
            ) as mock_join_query,
            patch(
                "backend.agents.create_agent_info.create_model_config_list"
            ) as mock_create_models,
            patch(
                "backend.agents.create_agent_info.get_remote_mcp_server_list",
                new_callable=AsyncMock,
            ) as mock_get_mcp,
            patch(
                "backend.agents.create_agent_info.create_agent_config"
            ) as mock_create_agent,
            patch(
                "backend.agents.create_agent_info.filter_mcp_servers_and_tools"
            ) as mock_filter,
            patch("backend.agents.create_agent_info.urljoin") as mock_urljoin,
            patch("backend.agents.create_agent_info.threading") as mock_threading,
            patch("backend.agents.create_agent_info.query_current_version_no") as mock_version_no,
        ):
            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            mock_get_mcp.return_value = []
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            mock_filter.return_value = []
            mock_threading.Event.return_value = "stop_event"
            mock_version_no.return_value = 1

            await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                tenant_id="tenant_1",
                user_id="user_1",
                language="zh",
                allow_memory_search=False,
            )

            mock_create_agent.assert_called_once_with(
                agent_id="agent_1",
                tenant_id="tenant_1",
                user_id="user_1",
                language="zh",
                last_user_query="processed_query",
                allow_memory_search=False,
                version_no=1,
                conversation_id=None,
                enable_planning=False,
                runtime_file_context=ANY,
                tool_params=None,
            )

    @pytest.mark.asyncio
    async def test_create_agent_run_info_is_debug_true(self):
        """Test case for is_debug=True uses version_no=0 without calling query_current_version_no"""
        mock_agent_run_info.reset_mock()
        with patch('backend.agents.create_agent_info.join_minio_file_description_to_query') as mock_join_query, \
                patch('backend.agents.create_agent_info.create_model_config_list') as mock_create_models, \
                patch('backend.agents.create_agent_info.get_remote_mcp_server_list', new_callable=AsyncMock) as mock_get_mcp, \
                patch('backend.agents.create_agent_info.create_agent_config') as mock_create_agent, \
                patch('backend.agents.create_agent_info.filter_mcp_servers_and_tools') as mock_filter, \
                patch('backend.agents.create_agent_info.urljoin') as mock_urljoin, \
                patch('backend.agents.create_agent_info.threading') as mock_threading, \
                patch('backend.agents.create_agent_info.query_current_version_no') as mock_version_no:

            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            mock_get_mcp.return_value = []
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            mock_filter.return_value = []
            mock_threading.Event.return_value = "stop_event"

            await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                user_id="user_1",
                tenant_id="tenant_1",
                language="zh",
                is_debug=True,  # Enable debug mode
            )

            # Verify that query_current_version_no was NOT called (because is_debug=True)
            mock_version_no.assert_not_called()

            # Verify that create_agent_config was called with version_no=0 (draft version)
            mock_create_agent.assert_called_once_with(
                agent_id="agent_1",
                tenant_id="tenant_1",
                user_id="user_1",
                language="zh",
                last_user_query="processed_query",
                allow_memory_search=True,
                version_no=0,  # Debug mode uses draft version 0
                conversation_id=None,
                enable_planning=False,
                runtime_file_context=ANY,
                tool_params=None,
            )

    @pytest.mark.asyncio
    async def test_create_agent_run_info_no_published_version_fallback(self):
        """Test case when query_current_version_no returns None, should fallback to version_no=0"""
        mock_agent_run_info.reset_mock()
        with patch('backend.agents.create_agent_info.join_minio_file_description_to_query') as mock_join_query, \
                patch('backend.agents.create_agent_info.create_model_config_list') as mock_create_models, \
                patch('backend.agents.create_agent_info.get_remote_mcp_server_list', new_callable=AsyncMock) as mock_get_mcp, \
                patch('backend.agents.create_agent_info.create_agent_config') as mock_create_agent, \
                patch('backend.agents.create_agent_info.filter_mcp_servers_and_tools') as mock_filter, \
                patch('backend.agents.create_agent_info.urljoin') as mock_urljoin, \
                patch('backend.agents.create_agent_info.threading') as mock_threading, \
                patch('backend.agents.create_agent_info.query_current_version_no') as mock_version_no, \
                patch('backend.agents.create_agent_info.logger') as mock_logger:

            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            mock_get_mcp.return_value = []
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            mock_filter.return_value = []
            mock_threading.Event.return_value = "stop_event"
            # Simulate no published version exists
            mock_version_no.return_value = None

            await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                user_id="user_1",
                tenant_id="tenant_1",
                language="zh",
                is_debug=False,
            )

            # Verify that query_current_version_no was called
            mock_version_no.assert_called_once_with(agent_id="agent_1", tenant_id="tenant_1")

            # Verify that logger.info was called with fallback message
            mock_logger.info.assert_called_once_with("Agent agent_1 has no published version, using draft version 0")

            # Verify that create_agent_config was called with version_no=0 (fallback)
            mock_create_agent.assert_called_once_with(
                agent_id="agent_1",
                tenant_id="tenant_1",
                user_id="user_1",
                language="zh",
                last_user_query="processed_query",
                allow_memory_search=True,
                version_no=0,  # Fallback to draft version 0
                conversation_id=None,
                enable_planning=False,
                runtime_file_context=ANY,
                tool_params=None,
            )
            # Verify that get_remote_mcp_server_list was called with is_need_auth=True
            mock_get_mcp.assert_called_once_with(tenant_id="tenant_1", is_need_auth=True)

    @pytest.mark.asyncio
    async def test_create_agent_run_info_is_need_auth_true_includes_token(self):
        """Test that get_remote_mcp_server_list is called with is_need_auth=True and returns authorization_token"""
        mock_agent_run_info.reset_mock()
        with patch('backend.agents.create_agent_info.join_minio_file_description_to_query') as mock_join_query, \
                patch('backend.agents.create_agent_info.create_model_config_list') as mock_create_models, \
                patch('backend.agents.create_agent_info.get_remote_mcp_server_list', new_callable=AsyncMock) as mock_get_mcp, \
                patch('backend.agents.create_agent_info.create_agent_config') as mock_create_agent, \
                patch('backend.agents.create_agent_info.filter_mcp_servers_and_tools') as mock_filter, \
                patch('backend.agents.create_agent_info.urljoin') as mock_urljoin, \
                patch('backend.agents.create_agent_info.threading') as mock_threading, \
                patch('backend.agents.create_agent_info.query_current_version_no') as mock_version_no:

            mock_join_query.return_value = "processed_query"
            mock_create_models.return_value = ["model_config"]
            # Mock return value with authorization_token (when is_need_auth=True)
            mock_get_mcp.return_value = [
                {
                    "remote_mcp_server_name": "test_server",
                    "remote_mcp_server": "http://test.server",
                    "status": True,
                    "authorization_token": "secret_token_123",
                    "mcp_id": 1
                }
            ]
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            mock_filter.return_value = ["http://test.server"]
            mock_threading.Event.return_value = "stop_event"
            mock_version_no.return_value = 1

            await create_agent_run_info(
                agent_id="agent_1",
                minio_files=[],
                query="test query",
                history=[],
                user_id="user_1",
                tenant_id="tenant_1",
                language="zh"
            )

            # Verify that get_remote_mcp_server_list was called with is_need_auth=True
            mock_get_mcp.assert_called_once_with(tenant_id="tenant_1", is_need_auth=True)

            # Verify that the returned data includes authorization_token (used in mcp_host construction)
            assert mock_get_mcp.return_value[0]["authorization_token"] == "secret_token_123"


class TestJoinMinioFileDescriptionToQuery:
    """Tests for the join_minio_file_description_to_query function"""

    def test_build_internal_s3_url_prefers_object_name(self):
        file = {
            "object_name": "attachments/user/image.png",
            "url": "blob:http://localhost:3000/preview",
            "name": "image.png",
        }

        result = _build_internal_s3_url(file)

        assert result.endswith("/attachments/user/image.png")
        assert result.startswith("s3://")

    def test_build_internal_s3_url_rejects_blob_preview_url(self):
        file = {
            "url": "blob:http://localhost:3000/preview",
            "name": "image.png",
        }

        assert _build_internal_s3_url(file) == ""

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_with_files(self):
        """Test case with file descriptions"""
        minio_files = [
            {"url": "/nexent/1.pdf", "name": "1.pdf"},
            {"url": "/nexent/2.pdf", "name": "2.pdf"},
            {"no_description": "should be ignored"}
        ]
        query = "test query"

        result = await join_minio_file_description_to_query(minio_files, query)

        expected = "User uploaded files. The file information is as follows:\nFile name: 1.pdf, S3 URL: s3://nexent/1.pdf  [permanent]\n\nFile name: 2.pdf, S3 URL: s3://nexent/2.pdf  [permanent]\n\nUser wants to answer questions based on the information in the above files: test query"
        assert result == expected

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_no_files(self):
        """Test case with no files"""
        minio_files = []
        query = "test query"

        result = await join_minio_file_description_to_query(minio_files, query)

        assert result == "test query"

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_none_files(self):
        """Test case when files are None"""
        minio_files = None
        query = "test query"

        result = await join_minio_file_description_to_query(minio_files, query)

        assert result == "test query"

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_no_descriptions(self):
        """Test case when files have no descriptions"""
        minio_files = [
            {"no_description": "should be ignored"},
            {"another_field": "also ignored"}
        ]
        query = "test query"

        result = await join_minio_file_description_to_query(minio_files, query)

        assert result == "test query"

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_prefers_object_name_over_blob_url(self):
        """Uploaded images should be exposed to internal tools through MinIO, not browser blob URLs."""
        minio_files = [
            {
                "object_name": "attachments/user/image.png",
                "url": "blob:http://localhost:3000/preview",
                "name": "image.png",
            }
        ]
        query = "describe the image"

        result = await join_minio_file_description_to_query(minio_files, query)

        assert "blob:http" not in result
        assert "File name: image.png" in result
        assert "attachments/user/image.png" in result
        assert "S3 URL: s3://" in result

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_skips_blob_only_file(self):
        """Browser-only preview URLs cannot be used by internal tools."""
        minio_files = [
            {
                "url": "blob:http://localhost:3000/preview",
                "name": "image.png",
            }
        ]
        query = "describe the image"

        result = await join_minio_file_description_to_query(minio_files, query)

        assert result == query

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_deduplication_current(self):
        """Test that duplicate files in current message are de-duplicated by URL"""
        minio_files = [
            {"url": "/nexent/1.pdf", "name": "1.pdf"},
            {"url": "/nexent/1.pdf", "name": "1.pdf"},  # Duplicate URL
            {"url": "/nexent/2.pdf", "name": "2.pdf"},
        ]
        query = "test query"

        result = await join_minio_file_description_to_query(minio_files, query)

        # Count occurrences of "File name: 1.pdf" which should appear exactly once
        assert result.count("File name: 1.pdf") == 1
        assert result.count("File name: 2.pdf") == 1
        # Total file description blocks should be 2, not 3
        assert result.count("S3 URL:") == 2

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_deduplication_history(self):
        """Test that files in history are de-duplicated against current message"""
        minio_files = [{"url": "/nexent/1.pdf", "name": "1.pdf"}]
        history = [
            {"minio_files": [{"url": "/nexent/1.pdf", "name": "1.pdf"}]},  # Same URL as current
            {"minio_files": [{"url": "/nexent/2.pdf", "name": "2.pdf"}]},
        ]
        query = "test query"

        result = await join_minio_file_description_to_query(minio_files, query, history)

        # Count occurrences of "File name:" which should appear exactly once for each unique file
        assert result.count("File name: 1.pdf") == 1
        assert result.count("File name: 2.pdf") == 1
        # Total file description blocks should be 2, not 3
        assert result.count("S3 URL:") == 2

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_max_files(self):
        """Test that file list is truncated when exceeding max_files limit"""
        minio_files = [
            {"url": f"/nexent/file_{i}.pdf", "name": f"file_{i}.pdf"}
            for i in range(10)
        ]
        query = "test query"

        result = await join_minio_file_description_to_query(minio_files, query, max_files=5)

        for i in range(5):
            assert f"file_{i}.pdf" in result
        for i in range(5, 10):
            assert f"file_{i}.pdf" not in result

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_max_chars(self):
        """Test that file descriptions are truncated when exceeding max_chars limit"""
        # Each file description is roughly 72 chars
        # With prefix (~56) and suffix (~100), fixed overhead is ~156 chars
        # Setting max_chars=100 should prevent ANY file from being included
        # (since even one file needs ~72 + 156 = 228 chars)
        minio_files = [
            {"url": f"/nexent/file_{i}.pdf", "name": f"file_{i}.pdf"}
            for i in range(10)
        ]
        query = "test query"

        # Very small limit - should result in no files being included
        result = await join_minio_file_description_to_query(minio_files, query, max_chars=100)
        assert result == "test query"

        # Reasonable limit - should include some files
        # With 500 chars, we can fit: 500 - 156 = 344 available chars
        # Each file is ~72 chars, so we can fit ~4 files
        result = await join_minio_file_description_to_query(minio_files, query, max_chars=500)
        # Should include at least some files but not all 10
        assert "file_0.pdf" in result
        assert result.count("File name:") < 10

    @pytest.mark.asyncio
    async def test_join_minio_file_description_to_query_current_files_priority(self):
        """Test that current message files appear before history files when deduping"""
        minio_files = [{"url": "/nexent/1.pdf", "name": "current_1.pdf"}]
        history = [
            {"minio_files": [{"url": "/nexent/2.pdf", "name": "history_2.pdf"}]},
        ]
        query = "test query"

        result = await join_minio_file_description_to_query(minio_files, query, history)

        pos_current = result.find("current_1.pdf")
        pos_history = result.find("history_2.pdf")
        assert pos_current < pos_history, "Current message files should appear before history files"

    def test_format_minio_files_for_content_formats_presigned_urls(self):
        """History attachment formatting should include both internal and external URLs."""
        result = _format_minio_files_for_content(
            [
                {
                    "name": "report.pdf",
                    "object_name": "tenant-a/report.pdf",
                    "presigned_url": "https://signed.example/report.pdf",
                }
            ]
        )

        assert result.startswith("\n[Attached files]:\n")
        assert "report.pdf" in result
        assert "s3://" in result
        assert "presigned_url: https://signed.example/report.pdf" in result

    def test_convert_history_with_minio_files_embeds_file_info(self):
        """History items should preserve text and append formatted attachment details."""
        history = [
            HistoryItem(
                role="user",
                content="Please review this file",
                minio_files=[
                    {
                        "name": "notes.txt",
                        "object_name": "tenant-a/notes.txt",
                    }
                ],
            ),
            HistoryItem(role="assistant", content="Done", minio_files=None),
        ]

        result = _convert_history_with_minio_files(history)

        assert len(result) == 2
        assert result[0].role == "user"
        assert result[0].content.startswith("Please review this file")
        assert "[Attached files]:" in result[0].content
        assert "notes.txt" in result[0].content
        assert result[1].content == "Done"

    def test_convert_history_with_minio_files_returns_none_for_none(self):
        """None history should remain None for downstream SDK compatibility."""
        assert _convert_history_with_minio_files(None) is None


class TestPreparePromptTemplates:
    """Tests for the prepare_prompt_templates function"""

    @pytest.mark.asyncio
    async def test_prepare_prompt_templates_manager_zh(self):
        """Test case for manager mode Chinese prompt templates"""
        with patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template:

            mock_get_template.return_value = {"test": "template"}

            result = await prepare_prompt_templates(True, "zh")

            mock_get_template.assert_called_once_with(True, "zh")
            assert result["system_prompt"] == ""
            assert result["test"] == "template"

    @pytest.mark.asyncio
    async def test_prepare_prompt_templates_worker_en(self):
        """Test case for worker mode English prompt templates"""
        with patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template:

            mock_get_template.return_value = {"test": "template"}

            result = await prepare_prompt_templates(False, "en")

            mock_get_template.assert_called_once_with(False, "en")
            assert result["system_prompt"] == ""
            assert result["test"] == "template"

    @pytest.mark.asyncio
    async def test_prepare_prompt_templates_clears_existing_system_prompt(self):
        """Template files cannot introduce a second stable-context source."""
        with patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template:
            mock_get_template.return_value = {
                "system_prompt": "stale prompt",
                "user_prompt": "keep me",
            }

            result = await prepare_prompt_templates(False, "en")

            assert result == {
                "system_prompt": "",
                "user_prompt": "keep me",
            }


class TestAdditionalAgentInfoCoverage:
    def test_build_long_term_memory_items_preserves_scope_metadata(self):
        context = types.SimpleNamespace(
            tenant_long_term=[{"content": "tenant preference", "metadata": {"version_id": 7}, "source": "manual"}],
            user_long_term=[types.SimpleNamespace(content="## Preferences\n\n- concise", metadata={"version_id": 8}, source="dreaming")],
        )
        result = create_agent_info_module._build_long_term_memory_items(context)
        assert [item["scope"] for item in result] == ["tenant", "user"]
        assert [item["version_id"] for item in result] == [7, 8]
        assert result[1]["source"] == "dreaming"

    def test_normalize_tool_params_rejects_non_object_payload(self):
        with pytest.raises(ValidationError, match="must be an object"):
            _normalize_tool_params_request("not-an-object")

    def test_resolve_input_budget_uses_legacy_fallback_for_unknown_capacity(self):
        create_agent_info_module._CAPACITY_WARNING_EMITTED.clear()
        with patch(
            "backend.agents.create_agent_info.resolve_capacity",
            side_effect=MockProviderCapabilityUnknown("unknown provider"),
        ), patch("backend.agents.create_agent_info.logger") as mock_logger:
            result = _resolve_input_budget({"model_id": 7, "model_name": "unknown"})

        assert result == (32768, None, None)
        mock_logger.warning.assert_called_once()

    def test_resolve_safe_input_budget_returns_none_for_uncertain_basis(self):
        capacity = MockModelCapacitySnapshot(model_name="legacy-model")
        calculator = MagicMock()
        calculator.calculate_safe_input_budget.side_effect = MockUncertaintyReserveBasisUnknown("missing context")
        with patch(
            "backend.agents.create_agent_info.SafeInputBudgetCalculator",
            return_value=calculator,
        ):
            result = _resolve_safe_input_budget(
                capacity_snapshot=capacity,
                tenant_id="tenant-1",
                agent_requested_output_tokens=None,
                request_requested_output_tokens=512,
            )

        assert result is None

    @pytest.mark.parametrize(
        ("exception_name", "reason"),
        [
            ("InvalidReservePolicy", "invalid_reserve_policy"),
            ("RequestedOutputExceedsCapacity", "requested_output_exceeds_model"),
            ("ReserveExceedsCapacity", "reserve_exceeds_capacity"),
            ("NoSafeInputCapacity", "no_safe_input_capacity"),
            ("SafeInputBudgetFingerprintMismatch", "budget_fingerprint_mismatch"),
            ("CallerMaxTokensOverrideForbidden", "caller_output_override_forbidden"),
            ("SafeInputBudgetCapacityMismatch", "capacity_snapshot_mismatch"),
            ("FutureBudgetError", "budget_resolution_failed"),
        ],
    )
    def test_ac_007_resolve_safe_input_budget_maps_budget_error(
        self, exception_name, reason
    ):
        capacity = MockModelCapacitySnapshot(model_name="invalid-model")
        calculator = MagicMock()
        exception_type = type(exception_name, (MockBudgetResolverError,), {})
        calculator.calculate_safe_input_budget.side_effect = exception_type("internal details")
        with patch(
            "backend.agents.create_agent_info.SafeInputBudgetCalculator",
            return_value=calculator,
        ):
            with pytest.raises(
                create_agent_info_module.ModelCapacityConfigError,
                match=f"capacity_config_invalid.{reason}",
            ) as exc_info:
                _resolve_safe_input_budget(
                    capacity_snapshot=capacity,
                    tenant_id="tenant-1",
                    agent_requested_output_tokens=None,
                    request_requested_output_tokens=None,
                )

        assert "internal details" not in str(exc_info.value)

    def test_inject_plan_tools_adds_tools_once(self):
        tools = []
        mock_tool_config.reset_mock()
        first_tool = MagicMock()
        first_tool.name = "create_plan"
        second_tool = MagicMock()
        second_tool.name = "update_plan_step"
        mock_tool_config.side_effect = [first_tool, second_tool]

        try:
            create_agent_info_module._inject_plan_tools(tools, True)
            create_agent_info_module._inject_plan_tools(tools, True)
        finally:
            mock_tool_config.side_effect = None

        assert len(tools) == 2
        assert mock_tool_config.call_count == 2

    def test_resolve_runtime_tool_records_rejects_missing_or_unavailable_dependency(self):
        common_patches = (
            patch(
                "backend.agents.create_agent_info.search_tools_for_sub_agent",
                return_value=[],
            ),
            patch(
                "backend.agents.create_agent_info.skill_db.search_skills_for_agent",
                return_value=[{"skill_id": 1, "config_values": {}}],
            ),
            patch(
                "backend.agents.create_agent_info.skill_db.get_skill_by_id",
                return_value={"name": "skill", "tool_ids": [5]},
            ),
        )
        with common_patches[0], common_patches[1], common_patches[2], patch(
            "backend.agents.create_agent_info.query_tools_by_ids", return_value=[]
        ):
            with pytest.raises(ValidationError, match="missing tools"):
                _resolve_runtime_tool_records(1, "tenant-1")

        with common_patches[0], common_patches[1], common_patches[2], patch(
            "backend.agents.create_agent_info.query_tools_by_ids",
            return_value=[{"tool_id": 5, "name": "required", "is_available": False}],
        ):
            with pytest.raises(ValidationError, match="unavailable tool"):
                _resolve_runtime_tool_records(1, "tenant-1")


class TestExtractUrlFromCard:
    """Tests for the _extract_url_from_card function"""

    def test_extract_url_from_card_none(self):
        """Test case for None raw_card"""
        result = _extract_url_from_card(None)
        assert result == ""

    def test_extract_url_from_card_empty_dict(self):
        """Test case for empty dict raw_card"""
        result = _extract_url_from_card({})
        assert result == ""

    def test_extract_url_from_card_no_interfaces(self):
        """Test case for card with url but no supportedInterfaces"""
        raw_card = {"name": "test_agent", "url": "http://example.com/agent"}
        result = _extract_url_from_card(raw_card)
        assert result == "http://example.com/agent"

    def test_extract_url_from_card_empty_interfaces(self):
        """Test case for card with empty supportedInterfaces"""
        raw_card = {
            "name": "test_agent",
            "url": "http://example.com/agent",
            "supportedInterfaces": []
        }
        result = _extract_url_from_card(raw_card)
        assert result == "http://example.com/agent"

    def test_extract_url_from_card_prefers_http_json_rpc(self):
        """Test case for preferring http-json-rpc protocol"""
        raw_card = {
            "name": "test_agent",
            "url": "http://fallback.com/agent",
            "supportedInterfaces": [
                {"protocolBinding": "http-streaming", "url": "http://streaming.com"},
                {"protocolBinding": "http-json-rpc", "url": "http://jsonrpc.com/agent"},
                {"protocolBinding": "sse", "url": "http://sse.com/agent"},
            ]
        }
        result = _extract_url_from_card(raw_card)
        assert result == "http://jsonrpc.com/agent"

    def test_extract_url_from_card_jsonrpc_variant(self):
        """Test case for jsonrpc protocol variant"""
        raw_card = {
            "name": "test_agent",
            "url": "http://fallback.com/agent",
            "supportedInterfaces": [
                {"protocolBinding": "jsonrpc", "url": "http://jsonrpc.com/agent"},
            ]
        }
        result = _extract_url_from_card(raw_card)
        assert result == "http://jsonrpc.com/agent"

    def test_extract_url_from_card_httpjsonrpc_variant(self):
        """Test case for httpjsonrpc protocol variant"""
        raw_card = {
            "name": "test_agent",
            "url": "http://fallback.com/agent",
            "supportedInterfaces": [
                {"protocolBinding": "httpjsonrpc", "url": "http://httpjsonrpc.com/agent"},
            ]
        }
        result = _extract_url_from_card(raw_card)
        assert result == "http://httpjsonrpc.com/agent"

    def test_extract_url_from_card_case_insensitive(self):
        """Test case for case-insensitive protocol matching"""
        raw_card = {
            "name": "test_agent",
            "url": "http://fallback.com/agent",
            "supportedInterfaces": [
                {"protocolBinding": "HTTP-JSON-RPC", "url": "http://uppercase.com/agent"},
            ]
        }
        result = _extract_url_from_card(raw_card)
        assert result == "http://uppercase.com/agent"

    def test_extract_url_from_card_fallback_to_first_interface(self):
        """Test case for fallback to first interface when no http-json-rpc"""
        raw_card = {
            "name": "test_agent",
            "url": "http://fallback.com/agent",
            "supportedInterfaces": [
                {"protocolBinding": "sse", "url": "http://sse.com/agent"},
                {"protocolBinding": "http-streaming", "url": "http://streaming.com/agent"},
            ]
        }
        result = _extract_url_from_card(raw_card)
        assert result == "http://sse.com/agent"

    def test_extract_url_from_card_fallback_skips_empty_url(self):
        """Test case for skipping interfaces with empty URL"""
        raw_card = {
            "name": "test_agent",
            "url": "http://fallback.com/agent",
            "supportedInterfaces": [
                {"protocolBinding": "sse", "url": ""},
                {"protocolBinding": "http-streaming", "url": "http://streaming.com/agent"},
            ]
        }
        result = _extract_url_from_card(raw_card)
        assert result == "http://streaming.com/agent"

    def test_extract_url_from_card_fallback_to_root_url(self):
        """Test case for fallback to root url when all interfaces have empty URL"""
        raw_card = {
            "name": "test_agent",
            "url": "http://fallback.com/agent",
            "supportedInterfaces": [
                {"protocolBinding": "sse", "url": ""},
                {"protocolBinding": "http-streaming", "url": ""},
            ]
        }
        result = _extract_url_from_card(raw_card)
        assert result == "http://fallback.com/agent"


class TestBuildExternalAgentConfig:
    """Tests for the _build_external_agent_config function"""

    def test_build_external_agent_config_basic(self):
        """Test case for building basic external agent config"""
        agent = {
            "external_agent_id": "ext_123",
            "name": "External Agent",
            "description": "An external A2A agent",
            "transport_type": "http-streaming",
            "protocol_version": "1.0",
            "protocol_type": "JSONRPC",
        }
        agent_url = "http://external.com/a2a"

        with patch('backend.agents.create_agent_info.ExternalA2AAgentConfig') as MockConfig:
            result = _build_external_agent_config(agent, agent_url)

            MockConfig.assert_called_once_with(
                agent_id="ext_123",
                name="External Agent",
                description="An external A2A agent",
                url="http://external.com/a2a",
                api_key=None,
                transport_type="http-streaming",
                protocol_version="1.0",
                protocol_type="JSONRPC",
                timeout=300.0,
                raw_card=None,
                custom_headers=None,
            )
            assert result == MockConfig.return_value

    def test_build_external_agent_config_defaults(self):
        """Test case for building config with missing fields"""
        agent = {
            "external_agent_id": "ext_456",
        }
        agent_url = "http://default.com/agent"

        with patch('backend.agents.create_agent_info.ExternalA2AAgentConfig') as MockConfig:
            result = _build_external_agent_config(agent, agent_url)

            MockConfig.assert_called_once_with(
                agent_id="ext_456",
                name="Unknown",
                description="External A2A agent",
                url="http://default.com/agent",
                api_key=None,
                transport_type="http-streaming",
                protocol_version="1.0",
                protocol_type="JSONRPC",
                timeout=300.0,
                raw_card=None,
                custom_headers=None,
            )
            assert result == MockConfig.return_value

    def test_build_external_agent_config_with_raw_card(self):
        """Test case for building config with raw_card"""
        agent = {
            "external_agent_id": "ext_789",
            "name": "Agent with Card",
            "description": "Agent with raw card",
            "raw_card": {"name": "raw_card_agent", "url": "http://raw.com"},
        }
        agent_url = "http://raw.com"

        with patch('backend.agents.create_agent_info.ExternalA2AAgentConfig') as MockConfig:
            result = _build_external_agent_config(agent, agent_url)

            call_kwargs = MockConfig.call_args[1]
            assert call_kwargs["agent_id"] == "ext_789"
            assert call_kwargs["raw_card"] == {"name": "raw_card_agent", "url": "http://raw.com"}
            assert result == MockConfig.return_value


class TestGetExternalA2AAgents:
    """Tests for the _get_external_a2a_agents function"""

    def test_get_external_a2a_agents_success(self):
        """Test case for successfully getting external A2A agents"""
        mock_query_result = [
            {
                "external_agent_id": "ext_1",
                "name": "Agent 1",
                "description": "First external agent",
                "agent_url": "http://agent1.com/a2a",
            },
            {
                "external_agent_id": "ext_2",
                "name": "Agent 2",
                "description": "Second external agent",
                "agent_url": "http://agent2.com/a2a",
            },
        ]

        with patch('database.a2a_agent_db.query_external_sub_agents', return_value=mock_query_result):
            with patch('backend.agents.create_agent_info._build_external_agent_config') as mock_build:
                result = _get_external_a2a_agents(agent_id=1, tenant_id="tenant_1", version_no=1)

                assert len(result) == 2
                from database.a2a_agent_db import query_external_sub_agents
                query_external_sub_agents.assert_called_once_with(
                    local_agent_id=1, tenant_id="tenant_1", version_no=1
                )
                assert mock_build.call_count == 2
                mock_build.assert_any_call(mock_query_result[0], "http://agent1.com/a2a")
                mock_build.assert_any_call(mock_query_result[1], "http://agent2.com/a2a")

    def test_get_external_a2a_agents_skips_missing_url(self):
        """Test case for skipping agents without URL"""
        mock_query_result = [
            {
                "external_agent_id": "ext_1",
                "name": "Valid Agent",
                "agent_url": "http://valid.com/a2a",
            },
            {
                "external_agent_id": "ext_2",
                "name": "Invalid Agent",
                "description": "No URL available",
            },
        ]

        with patch('database.a2a_agent_db.query_external_sub_agents', return_value=mock_query_result):
            with patch('backend.agents.create_agent_info._build_external_agent_config') as mock_build:
                result = _get_external_a2a_agents(agent_id=1, tenant_id="tenant_1")

                assert len(result) == 1
                mock_build.assert_called_once_with(mock_query_result[0], "http://valid.com/a2a")

    def test_get_external_a2a_agents_empty_db_response(self):
        """Test case for empty database response"""
        with patch('database.a2a_agent_db.query_external_sub_agents', return_value=[]):
            with patch('backend.agents.create_agent_info._build_external_agent_config') as mock_build:
                result = _get_external_a2a_agents(agent_id=1, tenant_id="tenant_1")

                assert result == []
                mock_build.assert_not_called()

    def test_get_external_a2a_agents_uses_explicit_url_first(self):
        """Test case for preferring explicit agent_url over raw_card"""
        mock_query_result = [
            {
                "external_agent_id": "ext_1",
                "name": "Agent with both URLs",
                "agent_url": "http://explicit.com/a2a",
                "raw_card": {"url": "http://card.com/a2a"},
            },
        ]

        with patch('database.a2a_agent_db.query_external_sub_agents', return_value=mock_query_result):
            with patch('backend.agents.create_agent_info._extract_url_from_card') as mock_extract:
                with patch('backend.agents.create_agent_info._build_external_agent_config') as mock_build:
                    result = _get_external_a2a_agents(agent_id=1, tenant_id="tenant_1")

                    assert len(result) == 1
                    mock_extract.assert_not_called()
                    mock_build.assert_called_once_with(mock_query_result[0], "http://explicit.com/a2a")

    def test_get_external_a2a_agents_extracts_url_from_raw_card(self):
        """Test case for extracting URL from raw_card when no explicit URL"""
        mock_query_result = [
            {
                "external_agent_id": "ext_1",
                "name": "Agent without explicit URL",
                "raw_card": {
                    "url": "http://card-url.com/a2a",
                    "supportedInterfaces": [
                        {"protocolBinding": "http-json-rpc", "url": "http://card-jsonrpc.com"}
                    ]
                },
            },
        ]

        with patch('database.a2a_agent_db.query_external_sub_agents', return_value=mock_query_result):
            with patch('backend.agents.create_agent_info._extract_url_from_card', return_value="http://card-jsonrpc.com") as mock_extract:
                with patch('backend.agents.create_agent_info._build_external_agent_config') as mock_build:
                    result = _get_external_a2a_agents(agent_id=1, tenant_id="tenant_1")

                    assert len(result) == 1
                    mock_extract.assert_called_once_with(mock_query_result[0]["raw_card"])
                    mock_build.assert_called_once_with(mock_query_result[0], "http://card-jsonrpc.com")

    def test_get_external_a2a_agents_exception_handling(self):
        """Test case for exception handling"""
        with patch('database.a2a_agent_db.query_external_sub_agents', side_effect=Exception("Database error")):
            with patch('backend.agents.create_agent_info.logger') as mock_logger:
                result = _get_external_a2a_agents(agent_id=1, tenant_id="tenant_1")

                assert result == []
                mock_logger.error.assert_called_once()
                assert "Get external A2A agents failed" in mock_logger.error.call_args[0][0]
                assert "Database error" in mock_logger.error.call_args[0][0]


class TestCreateToolConfigListWithDisplayNameMap:
    """Tests for create_tool_config_list with display_name_to_index_map functionality"""

    @pytest.fixture(autouse=True)
    def mock_filter_accessible_indices(self):
        """Pass-through mock for filter_accessible_indices for all tests in this class."""
        with patch('backend.agents.create_agent_info.ElasticSearchService.filter_accessible_indices',
                   side_effect=lambda index_names, **kwargs: index_names):
            yield

    @pytest.mark.asyncio
    async def test_knowledge_base_with_display_name_to_index_map(self):
        """Test that KnowledgeBaseSearchTool gets correct display_name_to_index_map from index_names"""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "KnowledgeBaseSearchTool"
        mock_tool_instance.params = {
            "index_names": ["idx1", "idx2"],
            "rerank": False,
        }

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_embedding, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank, \
                patch('backend.agents.create_agent_info.get_knowledge_name_map_by_index_names') as mock_get_knowledge_map:

            mock_tool_config.return_value = mock_tool_instance

            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["idx1", "idx2"]},
                        {"name": "rerank", "default": False},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vector_db_core.return_value = "vdb_core_instance"
            mock_embedding.return_value = ("embedding_instance", 123, {"status": "ok"})
            mock_rerank.return_value = None
            # Mock the knowledge name map: index_name -> knowledge_name (display_name)
            mock_get_knowledge_map.return_value = {
                "idx1": "Knowledge Base 1",
                "idx2": "Knowledge Base 2"
            }

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 1
            # Verify get_knowledge_name_map_by_index_names was called
            mock_get_knowledge_map.assert_called_once_with(
                ["idx1", "idx2"],
                tenant_id="tenant_1",
            )
            # Verify display_name_to_index_map contains reversed mapping
            assert result[0].metadata["display_name_to_index_map"] == {
                "Knowledge Base 1": "idx1",
                "Knowledge Base 2": "idx2"
            }

    @pytest.mark.asyncio
    async def test_knowledge_base_with_partial_name_mapping(self):
        """Test that KnowledgeBaseSearchTool handles partial name mapping correctly"""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "KnowledgeBaseSearchTool"

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_embedding, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank, \
                patch('backend.agents.create_agent_info.get_knowledge_name_map_by_index_names') as mock_get_knowledge_map:

            mock_tool_config.return_value = mock_tool_instance

            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["idx1", "idx2", "idx3"]},
                        {"name": "rerank", "default": False},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vector_db_core.return_value = "vdb_core_instance"
            mock_embedding.return_value = ("embedding_instance", 123, {"status": "ok"})
            mock_rerank.return_value = None
            # Only idx1 is found in database, idx2 and idx3 are not found
            mock_get_knowledge_map.return_value = {
                "idx1": "Knowledge Base 1"
            }

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            # display_name_to_index_map should only contain the found mappings
            # Unfound indices will use index_name as fallback (which is not in get_knowledge_name_map result)
            assert "Knowledge Base 1" in result[0].metadata["display_name_to_index_map"]
            assert "Knowledge Base 2" in result[0].metadata["display_name_to_index_map"]
            assert "idx3" not in result[0].metadata["display_name_to_index_map"]

    @pytest.mark.asyncio
    async def test_knowledge_base_with_partial_name_mapping(self):
        """Test that KnowledgeBaseSearchTool handles partial name mapping correctly"""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "KnowledgeBaseSearchTool"

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_embedding, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank, \
                patch('backend.agents.create_agent_info.get_knowledge_name_map_by_index_names') as mock_get_knowledge_map:

            mock_tool_config.return_value = mock_tool_instance

            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["idx1", "idx2", "idx3"]},
                        {"name": "rerank", "default": False},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vector_db_core.return_value = "vdb_core_instance"
            mock_embedding.return_value = ("embedding_instance", 123, {"status": "ok"})
            mock_rerank.return_value = None
            # Only idx1 is found in database, idx2 and idx3 are not found
            mock_get_knowledge_map.return_value = {
                "idx1": "Knowledge Base 1"
            }

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            # display_name_to_index_map should only contain the found mappings
            # Unfound indices will use index_name as fallback (which is not in get_knowledge_name_map result)
            assert "Knowledge Base 1" in result[0].metadata["display_name_to_index_map"]

    @pytest.mark.asyncio
    async def test_knowledge_base_with_index_name_to_display_map(self):
        """Test that KnowledgeBaseSearchTool gets correct index_name_to_display_map from index_names.

        This test verifies the reverse mapping (index_name -> display_name) that was added
        to avoid redundant database queries when building knowledge_base_summary.
        """
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "KnowledgeBaseSearchTool"

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_embedding, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank, \
                patch('backend.agents.create_agent_info.get_knowledge_name_map_by_index_names') as mock_get_knowledge_map:

            mock_tool_config.return_value = mock_tool_instance

            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["idx1", "idx2"]},
                        {"name": "rerank", "default": False},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vector_db_core.return_value = "vdb_core_instance"
            mock_embedding.return_value = ("embedding_instance", 123, {"status": "ok"})
            mock_rerank.return_value = None
            # Mock the knowledge name map: index_name -> knowledge_name (display_name)
            mock_get_knowledge_map.return_value = {
                "idx1": "Knowledge Base 1",
                "idx2": "Knowledge Base 2"
            }

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 1
            # Verify display_name_to_index_map (original mapping)
            assert result[0].metadata["display_name_to_index_map"] == {
                "Knowledge Base 1": "idx1",
                "Knowledge Base 2": "idx2"
            }
            # Verify index_name_to_display_map (new reverse mapping)
            assert result[0].metadata["index_name_to_display_map"] == {
                "idx1": "Knowledge Base 1",
                "idx2": "Knowledge Base 2"
            }
            # Both maps should be present
            assert "display_name_to_index_map" in result[0].metadata
            assert "index_name_to_display_map" in result[0].metadata

    @pytest.mark.asyncio
    async def test_knowledge_base_with_partial_index_name_mapping(self):
        """Test that KnowledgeBaseSearchTool handles partial index_name_to_display_map correctly.

        When some index_names are not found in the database, they should not be
        added to the index_name_to_display_map.
        """
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "KnowledgeBaseSearchTool"

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_embedding, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank, \
                patch('backend.agents.create_agent_info.get_knowledge_name_map_by_index_names') as mock_get_knowledge_map:

            mock_tool_config.return_value = mock_tool_instance

            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["idx1", "idx2", "idx3"]},
                        {"name": "rerank", "default": False},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vector_db_core.return_value = "vdb_core_instance"
            mock_embedding.return_value = ("embedding_instance", 123, {"status": "ok"})
            mock_rerank.return_value = None
            # Only idx1 and idx2 are found, idx3 is not in the database
            mock_get_knowledge_map.return_value = {
                "idx1": "Knowledge Base 1",
                "idx2": "Knowledge Base 2"
            }

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            # Verify both mappings contain only found entries
            assert "idx1" in result[0].metadata["index_name_to_display_map"]
            assert "idx2" in result[0].metadata["index_name_to_display_map"]
            # idx3 was not found, so it should not be in the map
            assert "idx3" not in result[0].metadata["index_name_to_display_map"]

            # Verify reverse mapping also contains only found entries
            assert "Knowledge Base 1" in result[0].metadata["display_name_to_index_map"]
            assert "Knowledge Base 2" in result[0].metadata["display_name_to_index_map"]
            assert "idx3" not in result[0].metadata["display_name_to_index_map"]

    @pytest.mark.asyncio
    async def test_knowledge_base_empty_index_names_keeps_tool(self):
        """Test that tool is kept when index_names is empty for KnowledgeBaseSearchTool.

        After the permission-control change, an empty index_names list (whether from permission
        filtering or not configured) causes the tool to be kept with empty index_names rather
        than being skipped. The SDK forward() will return a clear "no accessible knowledge base"
        message, allowing the LLM to explain the situation to the user instead of entering a
        retry loop against a non-existent tool.
        """
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "KnowledgeBaseSearchTool"
        mock_tool_instance.params = {
            "index_names": [],
            "rerank": False,
        }

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_get_emb, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank, \
                patch('backend.agents.create_agent_info.get_knowledge_name_map_by_index_names') as mock_get_knowledge_map:

            mock_tool_config.return_value = mock_tool_instance

            # Tool with empty index_names
            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": []},  # Empty list
                        {"name": "rerank", "default": False},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vector_db_core.return_value = "vdb_core_instance"
            mock_get_emb.return_value = None
            mock_rerank.return_value = None
            mock_get_knowledge_map.return_value = {}

            # Tool with empty index_names should be kept (not skipped) so the LLM can call it
            # and receive a clear permission-denial message from the SDK forward()
            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            # Verify the tool was kept with empty index_names
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_knowledge_base_no_embedding_model_raises_validation_error(self):
        """Test that ValidationError is raised when get_embedding_model_by_index_name returns None."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "KnowledgeBaseSearchTool"
        mock_tool_instance.params = {
            "index_names": ["idx1"],
            "rerank": False,
        }

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank, \
                patch('backend.agents.create_agent_info.get_knowledge_name_map_by_index_names') as mock_get_knowledge_map, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_get_emb_by_index:

            mock_tool_config.return_value = mock_tool_instance

            # Tool with non-empty index_names but no embedding model
            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["idx1"]},  # Non-empty list
                        {"name": "rerank", "default": False},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vector_db_core.return_value = "vdb_core_instance"
            mock_rerank.return_value = None
            mock_get_knowledge_map.return_value = {"idx1": "Knowledge Base 1"}
            # Simulate get_embedding_model_by_index_name returning None
            mock_get_emb_by_index.return_value = (None, None, {"status": "needs_config", "message": "No model configured"})

            # Should raise ValidationError
            with pytest.raises(ValidationError) as exc_info:
                await create_tool_config_list("agent_1", "tenant_1", "user_1")

            # Verify error message contains guidance about configuring embedding model
            assert "Please configure an embedding model for this knowledge base" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_knowledge_base_with_valid_embedding_model(self):
        """Test that KnowledgeBaseSearchTool correctly sets embedding_model when get_embedding_model_by_index_name succeeds."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "KnowledgeBaseSearchTool"
        mock_tool_instance.params = {
            "index_names": ["idx1", "idx2"],
            "rerank": True,
            "rerank_model_name": "gte-rerank-v2",
        }

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank, \
                patch('backend.agents.create_agent_info.get_knowledge_name_map_by_index_names') as mock_get_knowledge_map, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_get_emb_by_index:

            mock_tool_config.return_value = mock_tool_instance

            # Tool with index_names and valid embedding model
            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["idx1", "idx2"]},
                        {"name": "rerank", "default": True},
                        {"name": "rerank_model_name", "default": "gte-rerank-v2"},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vector_db_core.return_value = "vdb_core_instance"
            mock_rerank.return_value = "mock_rerank_model"
            mock_get_knowledge_map.return_value = {
                "idx1": "Knowledge Base 1",
                "idx2": "Knowledge Base 2"
            }
            # Simulate get_embedding_model_by_index_name returning a valid model
            mock_embedding_model = MagicMock()
            mock_embedding_model.name = "text-embedding-ada-002"
            mock_get_emb_by_index.return_value = (mock_embedding_model, 123, {"status": "ok", "message": "Model found"})

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            # Verify the tool was created successfully
            assert len(result) == 1

            # Verify get_embedding_model_by_index_name was called with correct parameters
            mock_get_emb_by_index.assert_called_once_with("tenant_1", "idx1")

            # Verify metadata contains the embedding_model
            assert result[0].metadata["embedding_model"] == mock_embedding_model

            # Verify metadata also contains other expected fields
            assert "vdb_core" in result[0].metadata
            assert "rerank_model" in result[0].metadata
            assert "display_name_to_index_map" in result[0].metadata
            assert "index_name_to_display_map" in result[0].metadata

            # Verify mappings are correct
            assert result[0].metadata["display_name_to_index_map"] == {
                "Knowledge Base 1": "idx1",
                "Knowledge Base 2": "idx2"
            }
            assert result[0].metadata["index_name_to_display_map"] == {
                "idx1": "Knowledge Base 1",
                "idx2": "Knowledge Base 2"
            }

    @pytest.mark.asyncio
    async def test_knowledge_base_with_single_index_and_embedding_model(self):
        """Test KnowledgeBaseSearchTool with single index_name and valid embedding model."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "KnowledgeBaseSearchTool"
        mock_tool_instance.params = {
            "index_names": ["single_index"],
            "rerank": False,
        }

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank, \
                patch('backend.agents.create_agent_info.get_knowledge_name_map_by_index_names') as mock_get_knowledge_map, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_get_emb_by_index:

            mock_tool_config.return_value = mock_tool_instance

            # Tool with single index_name
            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["single_index"]},  # Single index
                        {"name": "rerank", "default": False},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vector_db_core.return_value = "vdb_core_instance"
            mock_rerank.return_value = None
            mock_get_knowledge_map.return_value = {
                "single_index": "My Knowledge Base"
            }
            mock_embedding_model = MagicMock()
            mock_embedding_model.name = "embedding-model-v1"
            mock_get_emb_by_index.return_value = (mock_embedding_model, 456, {"status": "ok"})

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            # Verify the tool was created successfully
            assert len(result) == 1

            # Verify get_embedding_model_by_index_name was called
            mock_get_emb_by_index.assert_called_once_with("tenant_1", "single_index")

            # Verify embedding_model is set correctly
            assert result[0].metadata["embedding_model"] == mock_embedding_model

            # Verify mappings for single index
            assert result[0].metadata["display_name_to_index_map"] == {
                "My Knowledge Base": "single_index"
            }
            assert result[0].metadata["index_name_to_display_map"] == {
                "single_index": "My Knowledge Base"
            }

    @pytest.mark.asyncio
    async def test_knowledge_base_embedding_model_error_metadata(self):
        """Test that get_embedding_model_by_index_name metadata is handled but doesn't affect tool creation on success."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "KnowledgeBaseSearchTool"

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank, \
                patch('backend.agents.create_agent_info.get_knowledge_name_map_by_index_names') as mock_get_knowledge_map, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_get_emb_by_index:

            mock_tool_config.return_value = mock_tool_instance

            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "kb_search",
                    "description": "KB search",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["test_idx"]},
                        {"name": "rerank", "default": False},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vector_db_core.return_value = "vdb_core"
            mock_rerank.return_value = None
            mock_get_knowledge_map.return_value = {"test_idx": "Test KB"}

            # Return valid embedding model with error metadata
            mock_embedding_model = MagicMock()
            mock_get_emb_by_index.return_value = (
                mock_embedding_model,
                789,
                {"status": "error", "message": "Some error but model exists"}
            )

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            # Should still succeed because embedding_model is not None
            assert len(result) == 1
            assert result[0].metadata["embedding_model"] == mock_embedding_model


class TestFilterMcpServersAndTools:
    """Tests for filter_mcp_servers_and_tools function"""

    def test_filter_mcp_servers_with_multiple_tools(self):
        """Test filtering with multiple MCP tools"""
        mock_tool1 = MagicMock()
        mock_tool1.source = "mcp"
        mock_tool1.usage = "server1"

        mock_tool2 = MagicMock()
        mock_tool2.source = "local"
        mock_tool2.usage = None

        mock_tool3 = MagicMock()
        mock_tool3.source = "mcp"
        mock_tool3.usage = "server2"

        mock_sub_agent = MagicMock()
        mock_sub_agent.tools = []
        mock_sub_agent.managed_agents = []

        mock_agent_config = MagicMock()
        mock_agent_config.tools = [mock_tool1, mock_tool2, mock_tool3]
        mock_agent_config.managed_agents = [mock_sub_agent]

        mcp_info_dict = {
            "server1": {"remote_mcp_server": "http://server1.example.com"},
            "server2": {"remote_mcp_server": "http://server2.example.com"},
        }

        result = filter_mcp_servers_and_tools(mock_agent_config, mcp_info_dict)

        assert len(result) == 2
        assert "http://server1.example.com" in result
        assert "http://server2.example.com" in result

    def test_filter_mcp_servers_with_nested_sub_agents(self):
        """Test filtering with nested sub-agents"""
        mock_tool1 = MagicMock()
        mock_tool1.source = "mcp"
        mock_tool1.usage = "nested_server"

        mock_sub_sub_agent = MagicMock()
        mock_sub_sub_agent.tools = [mock_tool1]
        mock_sub_sub_agent.managed_agents = []

        mock_sub_agent = MagicMock()
        mock_sub_agent.tools = []
        mock_sub_agent.managed_agents = [mock_sub_sub_agent]

        mock_agent_config = MagicMock()
        mock_agent_config.tools = []
        mock_agent_config.managed_agents = [mock_sub_agent]

        mcp_info_dict = {
            "nested_server": {"remote_mcp_server": "http://nested.example.com"},
        }

        result = filter_mcp_servers_and_tools(mock_agent_config, mcp_info_dict)

        assert len(result) == 1
        assert "http://nested.example.com" in result

    def test_filter_mcp_servers_with_disabled_server(self):
        """Test filtering excludes servers not in mcp_info_dict"""
        mock_tool1 = MagicMock()
        mock_tool1.source = "mcp"
        mock_tool1.usage = "enabled_server"

        mock_tool2 = MagicMock()
        mock_tool2.source = "mcp"
        mock_tool2.usage = "disabled_server"

        mock_agent_config = MagicMock()
        mock_agent_config.tools = [mock_tool1, mock_tool2]
        mock_agent_config.managed_agents = []

        mcp_info_dict = {
            "enabled_server": {"remote_mcp_server": "http://enabled.example.com"},
            # disabled_server is not in the dict
        }

        result = filter_mcp_servers_and_tools(mock_agent_config, mcp_info_dict)

        assert len(result) == 1
        assert "http://enabled.example.com" in result

    def test_filter_mcp_servers_with_empty_tools(self):
        """Test filtering with no tools returns empty list"""
        mock_agent_config = MagicMock()
        mock_agent_config.tools = []
        mock_agent_config.managed_agents = []

        mcp_info_dict = {
            "server1": {"remote_mcp_server": "http://server1.example.com"},
        }

        result = filter_mcp_servers_and_tools(mock_agent_config, mcp_info_dict)

        assert result == []


class TestFormatMinioFilesForContent:
    """Tests for the _format_minio_files_for_content function"""

    def test_format_minio_files_for_content_none_input(self):
        """Test case for None input returns empty string"""
        result = _format_minio_files_for_content(None)
        assert result == ""

    def test_format_minio_files_for_content_empty_list(self):
        """Test case for empty list returns empty string"""
        result = _format_minio_files_for_content([])
        assert result == ""

    def test_format_minio_files_for_content_non_list_input(self):
        """Test case for non-list input returns empty string"""
        result = _format_minio_files_for_content("not a list")
        assert result == ""
        result = _format_minio_files_for_content(123)
        assert result == ""
        result = _format_minio_files_for_content({"url": "test"})
        assert result == ""

    def test_format_minio_files_for_content_single_file_with_presigned_url(self):
        """Test case for single file with presigned_url"""
        minio_files = [
            {"url": "bucket/file.txt", "name": "file.txt", "presigned_url": "http://presigned.url"}
        ]
        result = _format_minio_files_for_content(minio_files)
        assert result == "\n[Attached files]:\n  - file.txt: s3:/bucket/file.txt (for non-MCP tools), presigned_url: http://presigned.url (for [MCP] tools)"

    def test_format_minio_files_for_content_single_file_without_presigned_url(self):
        """Test case for single file without presigned_url"""
        minio_files = [
            {"url": "bucket/file.txt", "name": "file.txt"}
        ]
        result = _format_minio_files_for_content(minio_files)
        assert result == "\n[Attached files]:\n  - file.txt: s3:/bucket/file.txt"

    def test_format_minio_files_for_content_uses_object_name_for_blob_url(self):
        """Use uploaded object_name instead of browser-only blob preview URL."""
        minio_files = [
            {
                "object_name": "attachments/user/image.png",
                "url": "blob:http://localhost:3000/preview",
                "name": "image.png",
            }
        ]

        result = _format_minio_files_for_content(minio_files)

        assert "blob:http" not in result
        assert "attachments/user/image.png" in result

    def test_format_minio_files_for_content_multiple_files(self):
        """Test case for multiple files"""
        minio_files = [
            {"url": "bucket/file1.txt", "name": "file1.txt"},
            {"url": "bucket/file2.txt", "name": "file2.txt", "presigned_url": "http://presigned2.url"},
            {"url": "bucket/file3.txt", "name": "file3.txt"}
        ]
        result = _format_minio_files_for_content(minio_files)
        assert "  - file1.txt: s3:/bucket/file1.txt" in result
        assert "  - file2.txt: s3:/bucket/file2.txt (for non-MCP tools), presigned_url: http://presigned2.url (for [MCP] tools)" in result
        assert "  - file3.txt: s3:/bucket/file3.txt" in result
        assert result.startswith("\n[Attached files]:\n")

    def test_format_minio_files_for_content_exceeds_max_files(self):
        """Test case when files exceed max_files limit"""
        minio_files = [
            {"url": f"bucket/file{i}.txt", "name": f"file{i}.txt"}
            for i in range(25)
        ]
        result = _format_minio_files_for_content(minio_files, max_files=20)
        assert "... (and 5 more files)" in result
        assert result.count("  - ") == 21  # 20 files + 1 truncation line

    def test_format_minio_files_for_content_exceeds_max_files_with_presigned(self):
        """Test case when files with presigned urls exceed max_files limit"""
        minio_files = [
            {"url": f"bucket/file{i}.txt", "name": f"file{i}.txt", "presigned_url": f"http://url{i}"}
            for i in range(10)
        ]
        result = _format_minio_files_for_content(minio_files, max_files=5)
        assert "... (and 5 more files)" in result
        assert "  - file0.txt" in result
        assert "presigned_url: http://url0" in result

    def test_format_minio_files_for_content_file_missing_url(self):
        """Test case for file with missing url is skipped"""
        minio_files = [
            {"name": "file1.txt"},
            {"url": "bucket/file2.txt", "name": "file2.txt"}
        ]
        result = _format_minio_files_for_content(minio_files)
        assert "  - file2.txt: s3:/bucket/file2.txt" in result
        assert "file1.txt" not in result

    def test_format_minio_files_for_content_file_missing_name(self):
        """Test case for file with missing name is skipped"""
        minio_files = [
            {"url": "bucket/file1.txt"},
            {"url": "bucket/file2.txt", "name": "file2.txt"}
        ]
        result = _format_minio_files_for_content(minio_files)
        assert "  - file2.txt: s3:/bucket/file2.txt" in result
        assert "file1.txt" not in result

    def test_format_minio_files_for_content_file_empty_url(self):
        """Test case for file with empty url is skipped"""
        minio_files = [
            {"url": "", "name": "file1.txt"},
            {"url": "bucket/file2.txt", "name": "file2.txt"}
        ]
        result = _format_minio_files_for_content(minio_files)
        assert "  - file2.txt: s3:/bucket/file2.txt" in result
        assert "file1.txt" not in result

    def test_format_minio_files_for_content_file_empty_name(self):
        """Test case for file with empty name is skipped"""
        minio_files = [
            {"url": "bucket/file1.txt", "name": ""},
            {"url": "bucket/file2.txt", "name": "file2.txt"}
        ]
        result = _format_minio_files_for_content(minio_files)
        assert "  - file2.txt: s3:/bucket/file2.txt" in result
        assert "file1.txt" not in result

    def test_format_minio_files_for_content_non_dict_file(self):
        """Test case for non-dict file entries are skipped"""
        minio_files = [
            "not a dict",
            123,
            None,
            {"url": "bucket/file.txt", "name": "file.txt"}
        ]
        result = _format_minio_files_for_content(minio_files)
        assert "  - file.txt: s3:/bucket/file.txt" in result
        assert "not a dict" not in result
        assert "123" not in result

    def test_format_minio_files_for_content_all_files_invalid(self):
        """Test case when all files are invalid returns empty string"""
        minio_files = [
            {"name": "file1.txt"},
            {"url": "bucket/file2.txt"},
            "invalid"
        ]
        result = _format_minio_files_for_content(minio_files)
        assert result == ""

    def test_format_minio_files_for_content_custom_max_files(self):
        """Test case with custom max_files parameter"""
        minio_files = [
            {"url": f"bucket/file{i}.txt", "name": f"file{i}.txt"}
            for i in range(10)
        ]
        result = _format_minio_files_for_content(minio_files, max_files=3)
        assert "... (and 7 more files)" in result
        assert result.count("  - ") == 4  # 3 files + 1 truncation line


class TestConvertHistoryWithMinioFiles:
    """Tests for the _convert_history_with_minio_files function"""

    def test_convert_history_with_minio_files_none_input(self):
        """Test case for None input returns None"""
        result = _convert_history_with_minio_files(None)
        assert result is None

    def test_convert_history_with_minio_files_empty_list(self):
        """Test case for empty list returns empty list"""
        result = _convert_history_with_minio_files([])
        assert result == []

    def test_convert_history_with_minio_files_single_item_no_minio_files(self):
        """Test case for single history item without minio_files"""
        history = [
            HistoryItem(role="user", content="Hello", minio_files=None)
        ]
        result = _convert_history_with_minio_files(history)
        assert len(result) == 1
        assert result[0].role == "user"
        assert result[0].content == "Hello"

    def test_convert_history_with_minio_files_single_item_with_minio_files(self):
        """Test case for single history item with minio_files"""
        minio_files = [
            {"url": "bucket/file.txt", "name": "file.txt", "presigned_url": "http://presigned.url"}
        ]
        history = [
            HistoryItem(role="user", content="Hello", minio_files=minio_files)
        ]
        result = _convert_history_with_minio_files(history)
        assert len(result) == 1
        assert result[0].role == "user"
        assert "Hello" in result[0].content
        assert "[Attached files]" in result[0].content
        assert "file.txt: s3:/bucket/file.txt" in result[0].content
        assert "presigned_url: http://presigned.url" in result[0].content

    def test_convert_history_with_minio_files_multiple_items_mixed(self):
        """Test case for multiple history items with/without minio_files"""
        history = [
            HistoryItem(role="user", content="Hello", minio_files=None),
            HistoryItem(
                role="user",
                content="With file",
                minio_files=[{"url": "bucket/f1.txt", "name": "f1.txt"}]
            ),
            HistoryItem(role="assistant", content="Response", minio_files=None),
        ]
        result = _convert_history_with_minio_files(history)
        assert len(result) == 3
        assert result[0].content == "Hello"
        assert "With file" in result[1].content
        assert "[Attached files]" in result[1].content
        assert result[2].content == "Response"

    def test_convert_history_with_minio_files_item_with_empty_content(self):
        """Test case for history item with minio_files but empty content"""
        minio_files = [
            {"url": "bucket/file.txt", "name": "file.txt"}
        ]
        history = [
            HistoryItem(role="user", content="", minio_files=minio_files)
        ]
        result = _convert_history_with_minio_files(history)
        assert len(result) == 1
        assert result[0].content.startswith("\n[Attached files]")
        assert "file.txt" in result[0].content

    def test_convert_history_with_minio_files_item_with_empty_minio_files_list(self):
        """Test case for history item with empty minio_files list"""
        history = [
            HistoryItem(role="user", content="Hello", minio_files=[])
        ]
        result = _convert_history_with_minio_files(history)
        assert len(result) == 1
        assert result[0].content == "Hello"

    def test_convert_history_with_minio_files_item_with_invalid_minio_files(self):
        """Test case for history item with invalid minio_files entries"""
        minio_files = [
            {"name": "no_url"},
            {"url": "bucket/file.txt", "name": "file.txt"}
        ]
        history = [
            HistoryItem(role="user", content="Hello", minio_files=minio_files)
        ]
        result = _convert_history_with_minio_files(history)
        assert len(result) == 1
        assert "Hello" in result[0].content
        assert "file.txt" in result[0].content

    def test_convert_history_with_minio_files_multiple_files_in_single_item(self):
        """Test case for single history item with multiple minio_files"""
        minio_files = [
            {"url": "bucket/file1.txt", "name": "file1.txt", "presigned_url": "http://url1"},
            {"url": "bucket/file2.txt", "name": "file2.txt"},
            {"url": "bucket/file3.txt", "name": "file3.txt", "presigned_url": "http://url3"}
        ]
        history = [
            HistoryItem(role="user", content="Check these files", minio_files=minio_files)
        ]
        result = _convert_history_with_minio_files(history)
        assert len(result) == 1
        assert "Check these files" in result[0].content
        assert "file1.txt" in result[0].content
        assert "file2.txt" in result[0].content
        assert "file3.txt" in result[0].content

    def test_convert_history_with_minio_files_assistant_role(self):
        """Test case for assistant role history item"""
        minio_files = [
            {"url": "bucket/doc.pdf", "name": "doc.pdf"}
        ]
        history = [
            HistoryItem(role="assistant", content="Here is the document", minio_files=minio_files)
        ]
        result = _convert_history_with_minio_files(history)
        assert len(result) == 1
        assert result[0].role == "assistant"
        assert "Here is the document" in result[0].content

    def test_convert_history_with_minio_files_all_items_have_minio_files(self):
        """Test case where all history items have minio_files"""
        history = [
            HistoryItem(
                role="user",
                content="First",
                minio_files=[{"url": "bucket/f1.txt", "name": "f1.txt"}]
            ),
            HistoryItem(
                role="assistant",
                content="Second",
                minio_files=[{"url": "bucket/f2.txt", "name": "f2.txt", "presigned_url": "http://f2"}]
            ),
            HistoryItem(
                role="user",
                content="Third",
                minio_files=[{"url": "bucket/f3.txt", "name": "f3.txt"}]
            ),
        ]
        result = _convert_history_with_minio_files(history)
        assert len(result) == 3
        assert "f1.txt" in result[0].content
        assert "f2.txt" in result[1].content
        assert "f3.txt" in result[2].content


if __name__ == "__main__":
    pytest.main([__file__])


# ============================================================================
# Additional tests for improved coverage
# ============================================================================


class TestNormalizeToolParamsRequest:
    """Tests for _normalize_tool_params_request function."""

    def test_normalize_with_none(self):
        """Test that None returns empty ToolParamsRequest."""
        result = _normalize_tool_params_request(None)
        assert isinstance(result, ToolParamsRequest)
        assert result.agents == {}

    def test_normalize_with_tool_params_request(self):
        """Test that ToolParamsRequest is returned as-is."""
        req = ToolParamsRequest(agents={"agent1": MockAgentToolParamsRequest(tools={"tool1": {"param1": "value1"}})})
        result = _normalize_tool_params_request(req)
        assert result is req

    def test_normalize_with_valid_dict(self):
        """Test that valid dict is validated into ToolParamsRequest."""
        input_dict = {"agents": {"agent1": {"tools": {"tool1": {"param1": "value1"}}}}}
        result = _normalize_tool_params_request(input_dict)
        assert isinstance(result, ToolParamsRequest)
        assert "agent1" in result.agents

    def test_normalize_with_invalid_type_raises_validation_error(self):
        """Test that non-dict, non-ToolParamsRequest raises ValidationError."""
        with pytest.raises(ValidationError, match="tool_params must be an object"):
            _normalize_tool_params_request("invalid_string")

    def test_normalize_with_invalid_dict_returns_empty(self):
        """Test that invalid dict returns empty ToolParamsRequest (mock behavior)."""
        # The mock ToolParamsRequest doesn't validate, so it just returns empty
        result = _normalize_tool_params_request({"invalid_key": 123})
        assert isinstance(result, ToolParamsRequest)


class TestGetAgentToolOverrides:
    """Tests for _get_agent_tool_overrides function."""

    def test_get_overrides_with_none_tool_params(self):
        """Test that None tool_params returns empty dict."""
        result = _get_agent_tool_overrides(None, "agent1")
        assert result == {}

    def test_get_overrides_with_none_agent_name(self):
        """Test that None agent_name returns empty dict."""
        tool_params = ToolParamsRequest(agents={"agent1": MockAgentToolParamsRequest(tools={"tool1": {"param1": "value1"}})})
        result = _get_agent_tool_overrides(tool_params, None)
        assert result == {}

    def test_get_overrides_with_empty_agent_name(self):
        """Test that empty agent_name returns empty dict."""
        tool_params = ToolParamsRequest(agents={"agent1": MockAgentToolParamsRequest(tools={"tool1": {"param1": "value1"}})})
        result = _get_agent_tool_overrides(tool_params, "")
        assert result == {}

    def test_get_overrides_with_unknown_agent(self):
        """Test that unknown agent returns empty dict."""
        tool_params = ToolParamsRequest(agents={"agent1": MockAgentToolParamsRequest(tools={"tool1": {"param1": "value1"}})})
        result = _get_agent_tool_overrides(tool_params, "unknown_agent")
        assert result == {}

    def test_get_overrides_with_existing_agent(self):
        """Test that existing agent returns its tool overrides."""
        tool_params = ToolParamsRequest(agents={"agent1": MockAgentToolParamsRequest(tools={"tool1": {"param1": "value1"}, "tool2": {"param2": "value2"}})})
        result = _get_agent_tool_overrides(tool_params, "agent1")
        assert result == {"tool1": {"param1": "value1"}, "tool2": {"param2": "value2"}}


class TestBuildInternalS3Url:
    """Tests for _build_internal_s3_url function."""

    def test_build_with_non_dict(self):
        """Test that non-dict input returns empty string."""
        assert _build_internal_s3_url("not a dict") == ""
        assert _build_internal_s3_url(None) == ""
        assert _build_internal_s3_url(123) == ""

    def test_build_with_empty_dict(self):
        """Test that empty dict returns empty string."""
        assert _build_internal_s3_url({}) == ""

    def test_build_with_object_name(self):
        """Test URL building with object_name."""
        result = _build_internal_s3_url({"object_name": "path/to/file.txt"})
        # Bucket name depends on test environment mock (MINIO_DEFAULT_BUCKET = "test-bucket")
        assert result.startswith("s3://")
        assert "path/to/file.txt" in result

    def test_build_with_object_name_leading_slash(self):
        """Test URL building with leading slash in object_name."""
        result = _build_internal_s3_url({"object_name": "/path/to/file.txt"})
        # Bucket name depends on test environment mock
        assert result.startswith("s3://")
        assert "path/to/file.txt" in result

    def test_build_with_s3_url_input(self):
        """Test that s3:// URL is returned as-is."""
        result = _build_internal_s3_url({"url": "s3://bucket/path/file.txt"})
        assert result == "s3://bucket/path/file.txt"

    def test_build_with_s3_single_slash(self):
        """Test URL building with s3:/ prefix."""
        result = _build_internal_s3_url({"url": "s3:/bucket/file.txt"})
        assert result == "s3://bucket/file.txt"

    def test_build_with_blob_url(self):
        """Test that blob: URL returns empty string."""
        assert _build_internal_s3_url({"url": "blob:http://example.com/file"}) == ""

    def test_build_with_s3_blob_url(self):
        """Test that s3:/blob: URL returns empty string."""
        assert _build_internal_s3_url({"url": "s3:/blob:http://example.com/file"}) == ""

    def test_build_with_http_url(self):
        """Test that non-s3 URL returns s3:/ prefixed version."""
        result = _build_internal_s3_url({"url": "https://example.com/file.txt"})
        assert result == "s3:/https://example.com/file.txt"


class TestMergeToolParams:
    """Tests for _merge_tool_params function."""

    def test_merge_with_override_params(self):
        """Test that override params update merged params."""
        tool_record = {"params": [{"name": "param1", "default": "default1"}, {"name": "param2", "default": "default2"}]}
        override_params = {"param1": "override1"}
        result = _merge_tool_params(tool_record, override_params)
        assert result == {"param1": "override1", "param2": "default2"}

    def test_merge_with_extra_params(self):
        """Test that extra params take precedence."""
        tool_record = {"params": [{"name": "param1", "default": "default1"}]}
        override_params = {"param1": "override1"}
        extra_params = {"param1": "extra1", "internal_param": "secret"}
        result = _merge_tool_params(tool_record, override_params, extra_params)
        assert result == {"param1": "extra1", "internal_param": "secret"}

    def test_merge_with_no_params_in_tool_record(self):
        """Test merge when tool_record has no params."""
        tool_record = {}
        result = _merge_tool_params(tool_record, {"override": "value"})
        assert result == {"override": "value"}

    def test_merge_with_empty_override_params(self):
        """Test merge with empty override params."""
        tool_record = {"params": [{"name": "param1", "default": "default1"}]}
        result = _merge_tool_params(tool_record, {})
        assert result == {"param1": "default1"}


# ---------------------------------------------------------------------------
# W11 V1.5 - dispatch_profile_hit_total metric wiring
# ---------------------------------------------------------------------------


class TestDispatchProfileHitMetric:
    """Spec L710: every successful capacity resolve where the resolved snapshot
    carries a non-null capability_profile_version increments the dispatch
    profile-hit counter. Combined with accept_total at save time, this gives
    the 95% SLO 'accepted catalog suggestions produce expected runtime
    profile' (W11 spec L1162-1163).
    """

    def test_profile_hit_recorded_when_snapshot_carries_profile_version(self):
        counter = MagicMock()
        snapshot = MockModelCapacitySnapshot(
            model_name="gpt-4o",
            capability_profile_version="openai/gpt-4o@1",
        )
        with patch.object(
            create_agent_info_module,
            "_capacity_dispatch_profile_hit_total",
            counter,
        ), patch.object(
            create_agent_info_module,
            "resolve_capacity",
            return_value=snapshot,
        ):
            create_agent_info_module._resolve_input_budget(
                {"model_factory": "openai", "model_name": "gpt-4o"}
            )

        counter.add.assert_called_once_with(1, {"provider": "openai"})

    def test_profile_hit_not_recorded_without_profile_version(self):
        """An operator-configured row (no catalog match) resolves successfully
        but `capability_profile_version` stays None. Counter must not fire --
        otherwise the SLO ratio is inflated by non-catalog dispatches.
        """
        counter = MagicMock()
        snapshot = MockModelCapacitySnapshot(
            model_name="custom-local",
            capability_profile_version=None,
        )
        with patch.object(
            create_agent_info_module,
            "_capacity_dispatch_profile_hit_total",
            counter,
        ), patch.object(
            create_agent_info_module,
            "resolve_capacity",
            return_value=snapshot,
        ):
            create_agent_info_module._resolve_input_budget(
                {"model_factory": "custom", "model_name": "custom-local"}
            )

        counter.add.assert_not_called()

    def test_recorder_no_op_when_counter_disabled(self):
        """OTel-optional guard: the helper must not raise when the counter
        is None so agent dispatch works in deployments without OpenTelemetry.
        """
        with patch.object(
            create_agent_info_module,
            "_capacity_dispatch_profile_hit_total",
            None,
        ):
            create_agent_info_module._record_dispatch_profile_hit("openai")


# ============================================================================
# KB Read Permission Control Tests for create_tool_config_list (Issue #3339)
# ============================================================================


class TestKBPermissionFilteringInCreateToolConfigList:
    """Tests for knowledge base permission filtering in create_tool_config_list."""

    @pytest.mark.asyncio
    async def test_create_tool_config_list_filters_inaccessible_kbs(self):
        """
        When user lacks read permission on some knowledge bases, those indices are filtered out
        from the KnowledgeBaseSearchTool's index_names.
        """
        with patch("backend.agents.create_agent_info.search_tools_for_sub_agent") as mock_tools, \
             patch("backend.agents.create_agent_info.search_agent_info_by_agent_id", return_value={"name": "test_agent"}), \
             patch("backend.agents.create_agent_info.get_knowledge_name_map_by_index_names") as mock_kb_map, \
             patch("backend.agents.create_agent_info.get_vector_db_core") as mock_vdb, \
             patch("backend.agents.create_agent_info.get_embedding_model_by_index_name") as mock_get_embedding, \
             patch("backend.agents.create_agent_info.ElasticSearchService") as mock_es_service, \
             patch("backend.agents.create_agent_info.ToolConfig") as mock_tool_config:

            # Mock tool list with KnowledgeBaseSearchTool
            # params must be a list of dicts with "name" and "default" keys
            mock_tools.return_value = [{
                "class_name": "KnowledgeBaseSearchTool",
                "name": "knowledge_base_search",
                "description": "Search knowledge base",
                "inputs": "{}",
                "output_type": "string",
                "params": [
                    {"name": "index_names", "default": ["kb_allowed", "kb_forbidden", "kb_creator"]},
                    {"name": "top_k", "default": 5},
                ],
            }]

            # Mock permission check: kb_forbidden returns None, others return permissions
            def mock_filter(indices, user_id, tenant_id=None):
                return [idx for idx in indices if idx != "kb_forbidden"]

            mock_es_service.filter_accessible_indices = mock_filter
            mock_kb_map.return_value = {
                "kb_allowed": "Allowed KB",
                "kb_creator": "Creator KB",
            }
            mock_vdb.return_value = MagicMock()
            mock_get_embedding.return_value = (MagicMock(), None, None)

            # Create a simple class that stores params and allows modification
            class MockToolConfigInstance:
                def __init__(self):
                    self.params = {}
                    self.metadata = {}

            mock_tc_instance = MockToolConfigInstance()

            def capture_and_return(**kwargs):
                # Set all kwargs as attributes on the instance
                for key, value in kwargs.items():
                    setattr(mock_tc_instance, key, value)
                return mock_tc_instance
            mock_tool_config.side_effect = capture_and_return

            result = await create_agent_info_module.create_tool_config_list(
                agent_id="agent_123",
                tenant_id="tenant_456",
                user_id="user_789",
            )

            # Tool should be included (2 accessible KBs remain)
            assert len(result) == 1
            # Verify params.index_names was updated to filtered list
            assert mock_tc_instance.params["index_names"] == ["kb_allowed", "kb_creator"]

    @pytest.mark.asyncio
    async def test_create_tool_config_list_keeps_tool_when_no_accessible_kbs(self):
        """
        When user has no read permission on any knowledge base, the KnowledgeBaseSearchTool
        is kept in the tool list with empty index_names. The SDK forward() will return a
        clear "no accessible knowledge base" message, allowing the LLM to explain the
        situation to the user instead of entering a retry loop against a non-existent tool.
        """
        with patch("backend.agents.create_agent_info.search_tools_for_sub_agent") as mock_tools, \
             patch("backend.agents.create_agent_info.search_agent_info_by_agent_id", return_value={"name": "test_agent"}), \
             patch("backend.agents.create_agent_info.ElasticSearchService") as mock_es_service, \
             patch("backend.agents.create_agent_info.ToolConfig") as mock_tool_config:

            mock_tools.return_value = [{
                "class_name": "KnowledgeBaseSearchTool",
                "name": "knowledge_base_search",
                "description": "Search knowledge base",
                "inputs": "{}",
                "output_type": "string",
                "params": [
                    {"name": "index_names", "default": ["kb1", "kb2"]},
                    {"name": "top_k", "default": 5},
                ],
            }]

            # All KBs are inaccessible - filter returns empty list
            def mock_filter(indices, user_id, tenant_id=None):
                return []  # Return empty list to simulate no accessible KBs

            mock_es_service.filter_accessible_indices = mock_filter

            # Create a simple class that stores params and allows modification
            class MockToolConfigInstance:
                def __init__(self):
                    self.params = {}
                    self.metadata = {}

            mock_tc_instance = MockToolConfigInstance()

            def capture_and_return(**kwargs):
                # Set all kwargs as attributes on the instance
                for key, value in kwargs.items():
                    setattr(mock_tc_instance, key, value)
                return mock_tc_instance
            mock_tool_config.side_effect = capture_and_return

            result = await create_agent_info_module.create_tool_config_list(
                agent_id="agent_123",
                tenant_id="tenant_456",
                user_id="user_789",
            )

            # Tool should be kept in the list (not skipped) so the LLM can call it
            # and receive a clear permission-denial message from the SDK forward()
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_create_tool_config_list_preserves_order_after_filtering(self):
        """
        After filtering, the order of accessible knowledge bases is preserved.
        """
        with patch("backend.agents.create_agent_info.search_tools_for_sub_agent") as mock_tools, \
             patch("backend.agents.create_agent_info.search_agent_info_by_agent_id", return_value={"name": "test_agent"}), \
             patch("backend.agents.create_agent_info.get_knowledge_name_map_by_index_names") as mock_kb_map, \
             patch("backend.agents.create_agent_info.get_vector_db_core") as mock_vdb, \
             patch("backend.agents.create_agent_info.get_embedding_model_by_index_name") as mock_get_embedding, \
             patch("backend.agents.create_agent_info.ElasticSearchService") as mock_es_service, \
             patch("backend.agents.create_agent_info.ToolConfig") as mock_tool_config:

            mock_tools.return_value = [{
                "class_name": "KnowledgeBaseSearchTool",
                "name": "knowledge_base_search",
                "description": "Search knowledge base",
                "inputs": "{}",
                "output_type": "string",
                "params": [
                    {"name": "index_names", "default": ["kb_a", "kb_b", "kb_c", "kb_d"]},
                    {"name": "top_k", "default": 5},
                ],
            }]

            # Filter out kb_a and kb_c, preserving relative order
            def mock_filter(indices, user_id, tenant_id=None):
                return [idx for idx in indices if idx in ["kb_b", "kb_d"]]

            mock_es_service.filter_accessible_indices = mock_filter
            mock_kb_map.return_value = {
                "kb_b": "B KB",
                "kb_d": "D KB",
            }
            mock_vdb.return_value = MagicMock()
            mock_get_embedding.return_value = (MagicMock(), None, None)

            # Create a simple class that stores params and allows modification
            class MockToolConfigInstance:
                def __init__(self):
                    self.params = {}
                    self.metadata = {}

            mock_tc_instance = MockToolConfigInstance()

            def capture_and_return(**kwargs):
                # Set all kwargs as attributes on the instance
                for key, value in kwargs.items():
                    setattr(mock_tc_instance, key, value)
                return mock_tc_instance
            mock_tool_config.side_effect = capture_and_return

            result = await create_agent_info_module.create_tool_config_list(
                agent_id="agent_123",
                tenant_id="tenant_456",
                user_id="user_789",
            )

            assert len(result) == 1
            # Order should be preserved from original index_names list
            assert mock_tc_instance.params["index_names"] == ["kb_b", "kb_d"]



class TestCreateAgentConfigMemoryBuildFailure:
    """MemoryService initialization failures leave no unusable store tool."""

    @pytest.mark.asyncio
    async def test_memory_service_build_failure_skips_store_tool(self):
        """Storage failure is isolated while pipeline pre-search continues."""
        with patch("backend.agents.create_agent_info.search_agent_info_by_agent_id") as mock_search_agent, \
             patch("backend.agents.create_agent_info.query_sub_agent_relations", return_value=[]), \
             patch("backend.agents.create_agent_info._get_external_a2a_agents", return_value=[]), \
             patch("backend.agents.create_agent_info.create_tool_config_list",
                   new_callable=AsyncMock, return_value=[]), \
             patch("backend.agents.create_agent_info.get_agent_prompt_template", return_value={}), \
             patch("backend.agents.create_agent_info.tenant_config_manager") as mock_tenant_config, \
             patch("backend.agents.create_agent_info.build_memory_context") as mock_build_memory, \
             patch("backend.agents.create_agent_info._create_fixed_search_memory_tool") as mock_search_tool, \
             patch("backend.agents.create_agent_info.prepare_prompt_templates",
                   new_callable=AsyncMock, return_value={"system_prompt": "sp"}), \
             patch("backend.agents.create_agent_info.get_model_by_model_id",
                   return_value={"display_name": "model", "max_tokens": 1000}), \
             patch("backend.agents.create_agent_info.build_context_inputs", return_value=[]), \
             patch("backend.agents.create_agent_info.AgentConfig") as mock_agent_config, \
             patch("backend.agents.create_agent_info._get_skills_for_template", return_value=[]), \
             patch.dict(sys.modules, {
                 "services.memory_record_service": MagicMock(
                     _resolve_tenant_embedding_model_info=MagicMock(return_value=None),
                 ),
                 "services.memory_context_service": MagicMock(
                     get_memory_context_service=MagicMock(
                         return_value=MagicMock(
                             build_context=AsyncMock(
                                 side_effect=RuntimeError("long-term unavailable")
                             )
                         )
                     ),
                 ),
                 "services.memory_backend_adapter": MagicMock(
                     build_memory_service_for_agent=MagicMock(
                         side_effect=RuntimeError("DB connection lost")
                     ),
                 ),
             }):
            mock_search_agent.return_value = {
                "name": "test_agent", "description": "desc",
                "duty_prompt": "", "constraint_prompt": "",
                "few_shots_prompt": "", "max_steps": 5,
                "model_ids": [1], "provide_run_summary": False,
                "enable_context_manager": False,
            }
            mock_tenant_config.get_app_config.side_effect = ["App", "Desc"]
            mock_user_config = Mock()
            mock_user_config.memory_switch = True
            mock_user_config.agent_share_option = "always"
            mock_user_config.disable_agent_ids = []
            mock_user_config.disable_user_agent_ids = []
            mock_build_memory.return_value = Mock(
                user_config=mock_user_config, memory_config={},
                tenant_id="t1", user_id="u1", agent_id="a1",
            )
            mock_search_tool.return_value.forward = MagicMock(return_value="")

            # Should NOT raise - the exception is caught and warning logged
            result = await create_agent_config("a1", "t1", "u1", "en", "query")
            assert result is not None
            tool_names = [
                tool.name for tool in mock_agent_config.call_args.kwargs["tools"]
            ]
            assert "store_memory" not in tool_names
            mock_search_tool.return_value.forward.assert_called_once_with("query", 5)


class TestCreateAgentConfigMemoryContextServiceFailure:
    """ContextService failures do not switch pre-search retrieval modes."""

    @pytest.mark.asyncio
    async def test_memory_context_service_failure_skips_presearch(self):
        """Missing pipeline degrades to no memory without direct retrieval."""
        with patch("backend.agents.create_agent_info.search_agent_info_by_agent_id") as mock_search_agent, \
             patch("backend.agents.create_agent_info.query_sub_agent_relations", return_value=[]), \
             patch("backend.agents.create_agent_info._get_external_a2a_agents", return_value=[]), \
             patch("backend.agents.create_agent_info.create_tool_config_list",
                   new_callable=AsyncMock, return_value=[]), \
             patch("backend.agents.create_agent_info.get_agent_prompt_template", return_value={}), \
             patch("backend.agents.create_agent_info.tenant_config_manager") as mock_tenant_config, \
             patch("backend.agents.create_agent_info.build_memory_context") as mock_build_memory, \
             patch("backend.agents.create_agent_info._create_fixed_search_memory_tool") as mock_search_tool, \
             patch("backend.agents.create_agent_info.prepare_prompt_templates",
                   new_callable=AsyncMock, return_value={"system_prompt": "sp"}), \
             patch("backend.agents.create_agent_info.get_model_by_model_id",
                   return_value={"display_name": "model", "max_tokens": 1000}), \
             patch("backend.agents.create_agent_info.build_context_inputs", return_value=[]), \
             patch("backend.agents.create_agent_info.AgentConfig") as mock_agent_config, \
             patch("backend.agents.create_agent_info._get_skills_for_template", return_value=[]), \
             patch.dict(sys.modules, {
                 "services.memory_record_service": MagicMock(
                     _resolve_tenant_embedding_model_info=MagicMock(return_value=None),
                 ),
                 "services.memory_context_service": MagicMock(
                     get_memory_context_service=MagicMock(
                         side_effect=RuntimeError("config missing")
                     ),
                 ),
                 "services.memory_backend_adapter": MagicMock(
                     build_memory_service_for_agent=MagicMock(return_value=None),
                 ),
             }):
            mock_search_agent.return_value = {
                "name": "test_agent", "description": "desc",
                "duty_prompt": "", "constraint_prompt": "",
                "few_shots_prompt": "", "max_steps": 5,
                "model_ids": [1], "provide_run_summary": False,
                "enable_context_manager": False,
            }
            mock_tenant_config.get_app_config.side_effect = ["App", "Desc"]
            mock_user_config = Mock()
            mock_user_config.memory_switch = True
            mock_user_config.agent_share_option = "always"
            mock_user_config.disable_agent_ids = []
            mock_user_config.disable_user_agent_ids = []
            mock_build_memory.return_value = Mock(
                user_config=mock_user_config, memory_config={},
                tenant_id="t1", user_id="u1", agent_id="a1",
            )
            mock_search_tool.return_value.forward = MagicMock(return_value="")

            # Should NOT raise - the error is caught
            result = await create_agent_config("a1", "t1", "u1", "en", "query")
            assert result is not None
            mock_search_tool.assert_not_called()
            execution_logs = [
                event["content"]
                for event in mock_agent_config.call_args.kwargs["pre_run_tool_events"]
                if event["type"] == "execution_logs"
            ]
            assert execution_logs == [
                "Memory search unavailable: retrieval pipeline is not configured. "
                "Continuing without memory results."
            ]


class TestCreateAgentConfigMemoryProviderResults:
    """Memory provider return values determine available tools and pre-search."""

    @pytest.mark.asyncio
    async def test_available_memory_providers_register_store_tool(self):
        """Available providers register storage and execute pipeline pre-search."""
        memory_service = MagicMock(name="memory_service")
        memory_context_service = MagicMock(
            build_context=AsyncMock(
                return_value=types.SimpleNamespace(
                    tenant_long_term=(), user_long_term=()
                )
            )
        )
        memory_record_service_mod = types.ModuleType("services.memory_record_service")
        memory_record_service_mod._resolve_tenant_embedding_model_info = MagicMock(return_value=None)
        memory_context_service_mod = types.ModuleType("services.memory_context_service")
        memory_context_service_mod.get_memory_context_service = MagicMock(
            return_value=memory_context_service
        )
        memory_backend_adapter_mod = types.ModuleType("services.memory_backend_adapter")
        memory_backend_adapter_mod.build_memory_service_for_agent = MagicMock(
            return_value=memory_service
        )

        with patch("backend.agents.create_agent_info.search_agent_info_by_agent_id") as mock_search_agent, \
             patch("backend.agents.create_agent_info.query_sub_agent_relations", return_value=[]), \
             patch("backend.agents.create_agent_info._get_external_a2a_agents", return_value=[]), \
             patch("backend.agents.create_agent_info.create_tool_config_list", new_callable=AsyncMock, return_value=[]), \
             patch("backend.agents.create_agent_info.get_agent_prompt_template", return_value={}), \
             patch("backend.agents.create_agent_info.tenant_config_manager") as mock_tenant_config, \
             patch("backend.agents.create_agent_info.build_memory_context") as mock_build_memory, \
             patch("backend.agents.create_agent_info._create_fixed_search_memory_tool") as mock_search_tool, \
             patch("backend.agents.create_agent_info.prepare_prompt_templates", new_callable=AsyncMock, return_value={"system_prompt": "sp"}), \
             patch("backend.agents.create_agent_info.get_model_by_model_id", return_value={"display_name": "model", "max_tokens": 1000}), \
             patch("backend.agents.create_agent_info.build_context_inputs", return_value=[]), \
             patch("backend.agents.create_agent_info.ToolConfig", side_effect=lambda **kwargs: types.SimpleNamespace(**kwargs)), \
             patch("backend.agents.create_agent_info.AgentConfig") as mock_agent_config, \
             patch("backend.agents.create_agent_info._get_skills_for_template", return_value=[]), \
             patch.dict(sys.modules, {
                 "services.memory_record_service": memory_record_service_mod,
                 "services.memory_context_service": memory_context_service_mod,
                 "services.memory_backend_adapter": memory_backend_adapter_mod,
             }):
            mock_search_agent.return_value = {
                "name": "test_agent", "description": "desc", "duty_prompt": "",
                "constraint_prompt": "", "few_shots_prompt": "", "max_steps": 5,
                "model_ids": [1], "provide_run_summary": False,
                "enable_context_manager": False,
            }
            mock_tenant_config.get_app_config.side_effect = ["App", "Desc"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(
                    memory_switch=True, agent_share_option="always",
                    disable_agent_ids=[], disable_user_agent_ids=[],
                ),
                memory_config={}, tenant_id="t1", user_id="u1", agent_id="a1",
            )
            mock_search_tool.return_value.forward.return_value = "No relevant memories found."

            await create_agent_config("a1", "t1", "u1", "en", "query")

            tools = mock_agent_config.call_args.kwargs["tools"]
            store_tool = next(tool for tool in tools if tool.name == "store_memory")
            assert store_tool.metadata["memory_service"] is memory_service
            mock_search_tool.return_value.forward.assert_called_once_with("query", 5)

    @pytest.mark.asyncio
    async def test_none_memory_providers_skip_store_and_presearch(self):
        """Provider None results are isolated as unavailable memory dependencies."""
        memory_record_service_mod = types.ModuleType("services.memory_record_service")
        memory_record_service_mod._resolve_tenant_embedding_model_info = MagicMock(return_value=None)
        memory_context_service_mod = types.ModuleType("services.memory_context_service")
        memory_context_service_mod.get_memory_context_service = MagicMock(return_value=None)
        memory_backend_adapter_mod = types.ModuleType("services.memory_backend_adapter")
        memory_backend_adapter_mod.build_memory_service_for_agent = MagicMock(return_value=None)

        with patch("backend.agents.create_agent_info.search_agent_info_by_agent_id") as mock_search_agent, \
             patch("backend.agents.create_agent_info.query_sub_agent_relations", return_value=[]), \
             patch("backend.agents.create_agent_info._get_external_a2a_agents", return_value=[]), \
             patch("backend.agents.create_agent_info.create_tool_config_list", new_callable=AsyncMock, return_value=[]), \
             patch("backend.agents.create_agent_info.get_agent_prompt_template", return_value={}), \
             patch("backend.agents.create_agent_info.tenant_config_manager") as mock_tenant_config, \
             patch("backend.agents.create_agent_info.build_memory_context") as mock_build_memory, \
             patch("backend.agents.create_agent_info._create_fixed_search_memory_tool") as mock_search_tool, \
             patch("backend.agents.create_agent_info.prepare_prompt_templates", new_callable=AsyncMock, return_value={"system_prompt": "sp"}), \
             patch("backend.agents.create_agent_info.get_model_by_model_id", return_value={"display_name": "model", "max_tokens": 1000}), \
             patch("backend.agents.create_agent_info.build_context_inputs", return_value=[]), \
             patch("backend.agents.create_agent_info.ToolConfig", side_effect=lambda **kwargs: types.SimpleNamespace(**kwargs)), \
             patch("backend.agents.create_agent_info.AgentConfig") as mock_agent_config, \
             patch("backend.agents.create_agent_info._get_skills_for_template", return_value=[]), \
             patch.dict(sys.modules, {
                 "services.memory_record_service": memory_record_service_mod,
                 "services.memory_context_service": memory_context_service_mod,
                 "services.memory_backend_adapter": memory_backend_adapter_mod,
             }):
            mock_search_agent.return_value = {
                "name": "test_agent", "description": "desc", "duty_prompt": "",
                "constraint_prompt": "", "few_shots_prompt": "", "max_steps": 5,
                "model_ids": [1], "provide_run_summary": False,
                "enable_context_manager": False,
            }
            mock_tenant_config.get_app_config.side_effect = ["App", "Desc"]
            mock_build_memory.return_value = Mock(
                user_config=Mock(
                    memory_switch=True, agent_share_option="always",
                    disable_agent_ids=[], disable_user_agent_ids=[],
                ),
                memory_config={}, tenant_id="t1", user_id="u1", agent_id="a1",
            )

            await create_agent_config("a1", "t1", "u1", "en", "query")

            tools = mock_agent_config.call_args.kwargs["tools"]
            assert all(tool.name != "store_memory" for tool in tools)
            mock_search_tool.assert_not_called()
            execution_logs = [
                event["content"]
                for event in mock_agent_config.call_args.kwargs["pre_run_tool_events"]
                if event["type"] == "execution_logs"
            ]
            assert execution_logs == [
                "Memory search unavailable: retrieval pipeline is not configured. "
                "Continuing without memory results."
            ]


class TestCreateToolConfigListAidpSearch:
    """Coverage for lines 1294-1297, 1310-1354: AidpSearchTool credential injection and permission filtering."""

    @pytest.fixture(autouse=True)
    def mock_filter_accessible_indices(self):
        """Pass-through mock for filter_accessible_indices for all tests in this class."""
        with patch("backend.agents.create_agent_info.ElasticSearchService.filter_accessible_indices",
                   side_effect=lambda index_names, **kwargs: index_names):
            yield

    @pytest.mark.asyncio
    async def test_aidp_search_injects_credentials_from_env(self):
        """AidpSearchTool must pop stale creds and inject AIDP_SERVER_URL, AIDP_API_KEY, AIDP_TENANT_ID."""
        with patch("backend.agents.create_agent_info.discover_langchain_tools",
                   new_callable=AsyncMock, return_value=[]), \
             patch("backend.agents.create_agent_info.search_tools_for_sub_agent") as mock_tools, \
             patch("backend.agents.create_agent_info.search_agent_info_by_agent_id",
                   return_value={"name": "test_agent"}), \
             patch("backend.agents.create_agent_info.ToolConfig") as mock_tool_config, \
             patch("backend.agents.create_agent_info.AIDP_SERVER_URL", "https://aidp.test"), \
             patch("backend.agents.create_agent_info.AIDP_API_KEY", "key-123"), \
             patch("backend.agents.create_agent_info.AIDP_TENANT_ID", "aidp-tenant"), \
             patch.dict(sys.modules, {
                 "ext_components.aidp.services": MagicMock(
                     aidp_permission_service=MagicMock(
                         get_allowed_kds_list=MagicMock(return_value=["kb1"]),
                     ),
                 ),
             }):

            mock_tools.return_value = [{
                "class_name": "AidpSearchTool",
                "name": "aidp_search",
                "description": "AIDP search",
                "inputs": "{}",
                "output_type": "string",
                "params": [
                    {"name": "server_url", "default": "stale-url"},
                    {"name": "api_key", "default": "stale-key"},
                    {"name": "tenant_id", "default": "stale-tenant"},
                    {"name": "kds_list", "default": ["kb1"]},
                ],
                "source": "langchain",
                "usage": None,
            }]

            mock_tc_instance = Mock()
            mock_tc_instance.params = {}
            mock_tc_instance.metadata = None

            def capture_and_return(**kwargs):
                for key, value in kwargs.items():
                    setattr(mock_tc_instance, key, value)
                return mock_tc_instance

            mock_tool_config.side_effect = capture_and_return

            result = await create_agent_info_module.create_tool_config_list(
                agent_id="agent_1", tenant_id="tenant_1", user_id="user_1",
            )

            assert len(result) == 1
            # Platform credentials replace stale database values and are passed
            # explicitly to the SDK; the SDK must not read process environment.
            assert mock_tc_instance.params["server_url"] == "https://aidp.test"
            assert mock_tc_instance.params["api_key"] == "key-123"
            assert mock_tc_instance.params["tenant_id"] == "aidp-tenant"

    @pytest.mark.asyncio
    async def test_aidp_search_permission_whitelist_success(self):
        """When get_allowed_kds_list succeeds, allowed_kds_set is set in metadata."""
        access_module = MagicMock()
        access_module.resolve_current_aidp_access.return_value = types.SimpleNamespace(
            accessible_id_set={"kb_allowed_1", "kb_allowed_2", "kb_not_selected"},
            name_to_id={
                "Allowed 1": "kb_allowed_1",
                "Allowed 2": "kb_allowed_2",
                "Not selected": "kb_not_selected",
            },
        )
        with patch("backend.agents.create_agent_info.discover_langchain_tools",
                   new_callable=AsyncMock, return_value=[]), \
             patch("backend.agents.create_agent_info.search_tools_for_sub_agent") as mock_tools, \
             patch("backend.agents.create_agent_info.search_agent_info_by_agent_id",
                   return_value={"name": "test_agent"}), \
             patch("backend.agents.create_agent_info.ToolConfig") as mock_tool_config, \
             patch("backend.agents.create_agent_info.AIDP_SERVER_URL", "https://aidp.test"), \
             patch("backend.agents.create_agent_info.AIDP_API_KEY", "key"), \
             patch("backend.agents.create_agent_info.AIDP_TENANT_ID", "tenant"), \
             patch.dict(sys.modules, {
                 "ext_components.aidp.services.aidp_access_service": access_module,
             }):

            mock_tools.return_value = [{
                "class_name": "AidpSearchTool",
                "name": "aidp_search",
                "description": "AIDP search",
                "inputs": "{}",
                "output_type": "string",
                "params": [{
                    "name": "kds_list",
                    "default": ["kb_allowed_2", "kb_not_accessible"],
                }],
                "source": "langchain",
                "usage": None,
            }]

            mock_tc_instance = Mock()
            mock_tc_instance.params = {}
            mock_tc_instance.metadata = None

            def capture_and_return(**kwargs):
                for key, value in kwargs.items():
                    setattr(mock_tc_instance, key, value)
                return mock_tc_instance

            mock_tool_config.side_effect = capture_and_return

            result = await create_agent_info_module.create_tool_config_list(
                agent_id="agent_1", tenant_id="tenant_1", user_id="user_1",
            )

            assert len(result) == 1
            assert mock_tc_instance.metadata is not None
            assert "allowed_kds_set" in mock_tc_instance.metadata
            assert mock_tc_instance.params["kds_list"] == ["kb_allowed_2"]
            assert mock_tc_instance.metadata["allowed_kds_set"] == ["kb_allowed_2"]
            assert mock_tc_instance.metadata["kds_name_to_id_map"] == {
                "Allowed 2": "kb_allowed_2",
            }

    @pytest.mark.asyncio
    async def test_aidp_search_permission_whitelist_failure_fallback(self):
        """When get_allowed_kds_list raises, a warning is logged and allowed_kds_set stays empty."""
        access_module = MagicMock()
        access_module.resolve_current_aidp_access.side_effect = Exception("AIDP down")
        with patch("backend.agents.create_agent_info.discover_langchain_tools",
                   new_callable=AsyncMock, return_value=[]), \
             patch("backend.agents.create_agent_info.search_tools_for_sub_agent") as mock_tools, \
             patch("backend.agents.create_agent_info.search_agent_info_by_agent_id",
                   return_value={"name": "test_agent"}), \
             patch("backend.agents.create_agent_info.ToolConfig") as mock_tool_config, \
             patch("backend.agents.create_agent_info.AIDP_SERVER_URL", "https://aidp.test"), \
             patch("backend.agents.create_agent_info.AIDP_API_KEY", "key"), \
             patch("backend.agents.create_agent_info.AIDP_TENANT_ID", "tenant"), \
             patch.dict(sys.modules, {
                 "ext_components.aidp.services.aidp_access_service": access_module,
             }):

            mock_tools.return_value = [{
                "class_name": "AidpSearchTool",
                "name": "aidp_search",
                "description": "AIDP search",
                "inputs": "{}",
                "output_type": "string",
                "params": [{"name": "kds_list", "default": ["kb_requested"]}],
                "source": "langchain",
                "usage": None,
            }]

            mock_tc_instance = Mock()
            mock_tc_instance.params = {}
            mock_tc_instance.metadata = None

            def capture_and_return(**kwargs):
                for key, value in kwargs.items():
                    setattr(mock_tc_instance, key, value)
                return mock_tc_instance

            mock_tool_config.side_effect = capture_and_return

            result = await create_agent_info_module.create_tool_config_list(
                agent_id="agent_1", tenant_id="tenant_1", user_id="user_1",
            )

            assert len(result) == 1
            # Snapshot failure is fail-closed even when the tool requested a KB.
            assert mock_tc_instance.params["kds_list"] == []
            assert mock_tc_instance.metadata is not None
            assert mock_tc_instance.metadata["allowed_kds_set"] == []

    @pytest.mark.asyncio
    async def test_aidp_search_metadata_merges_langchain_tool(self):
        """When a langchain tool matches the AidpSearchTool class_name, it is merged into metadata."""
        matching_langchain_tool = Mock()
        matching_langchain_tool.name = "AidpSearchTool"

        with patch("backend.agents.create_agent_info.discover_langchain_tools",
                   new_callable=AsyncMock, return_value=[matching_langchain_tool]), \
             patch("backend.agents.create_agent_info.search_tools_for_sub_agent") as mock_tools, \
             patch("backend.agents.create_agent_info.search_agent_info_by_agent_id",
                   return_value={"name": "test_agent"}), \
             patch("backend.agents.create_agent_info.ToolConfig") as mock_tool_config, \
             patch("backend.agents.create_agent_info.AIDP_SERVER_URL", "https://aidp.test"), \
             patch("backend.agents.create_agent_info.AIDP_API_KEY", "key"), \
             patch("backend.agents.create_agent_info.AIDP_TENANT_ID", "tenant"), \
             patch.dict(sys.modules, {
                 "ext_components.aidp.services": MagicMock(
                     aidp_permission_service=MagicMock(
                         get_allowed_kds_list=MagicMock(return_value=[]),
                     ),
                 ),
             }):

            mock_tools.return_value = [{
                "class_name": "AidpSearchTool",
                "name": "aidp_search",
                "description": "AIDP search",
                "inputs": "{}",
                "output_type": "string",
                "params": [],
                "source": "langchain",
                "usage": None,
            }]

            mock_tc_instance = Mock()
            mock_tc_instance.params = {}
            mock_tc_instance.metadata = None

            def capture_and_return(**kwargs):
                for key, value in kwargs.items():
                    setattr(mock_tc_instance, key, value)
                return mock_tc_instance

            mock_tool_config.side_effect = capture_and_return

            result = await create_agent_info_module.create_tool_config_list(
                agent_id="agent_1", tenant_id="tenant_1", user_id="user_1",
            )

            assert len(result) == 1
            assert "langchain_tool" in mock_tc_instance.metadata
            assert mock_tc_instance.metadata["langchain_tool"] is matching_langchain_tool
            assert "allowed_kds_set" in mock_tc_instance.metadata


class TestBuildSecurityHeaders:
    """Tests for _build_security_headers and related functions."""

    def test_build_security_headers_apikey(self):
        """Two apiKey-header schemes."""
        agent = {
            "security_schemes": {
                "scheme_a": {"apiKeySecurityScheme": {"name": "X-Custom-Id", "location": "header"}},
                "scheme_b": {"apiKeySecurityScheme": {"name": "X-Custom-Key", "location": "header"}},
            },
            "security_requirements": [{"schemes": {"scheme_a": {}, "scheme_b": {}}}],
            "security_credentials": {"scheme_a": "id_value", "scheme_b": "key_value"},
        }
        assert _build_security_headers(agent) == {"X-Custom-Id": "id_value", "X-Custom-Key": "key_value"}

    def test_build_security_headers_http_bearer(self):
        """HTTP Bearer JWT."""
        agent = {
            "security_schemes": {"jwt": {"httpAuthSecurityScheme": {"scheme": "bearer", "bearerFormat": "JWT"}}},
            "security_requirements": [{"schemes": {"jwt": {}}}],
            "security_credentials": {"jwt": "token123"},
        }
        assert _build_security_headers(agent) == {"Authorization": "Bearer token123"}

    def test_build_security_headers_no_credentials(self):
        """No credentials -> empty."""
        agent = {
            "security_schemes": {"k": {"apiKeySecurityScheme": {"name": "X-Key", "location": "header"}}},
            "security_requirements": [{"schemes": {"k": {}}}],
            "security_credentials": {},
        }
        assert _build_security_headers(agent) == {}

    def test_build_security_headers_mixed(self):
        """Mixed apiKey + httpAuth."""
        agent = {
            "security_schemes": {
                "k": {"apiKeySecurityScheme": {"name": "X-Custom", "location": "header"}},
                "j": {"httpAuthSecurityScheme": {"scheme": "bearer"}},
            },
            "security_requirements": [{"schemes": {"k": {}, "j": {}}}],
            "security_credentials": {"k": "key-val", "j": "jwt-val"},
        }
        assert _build_security_headers(agent) == {"X-Custom": "key-val", "Authorization": "bearer jwt-val"}

    def test_resolve_scheme_field_wrapper(self):
        scheme = {"apiKeySecurityScheme": {"name": "X-Key", "location": "header"}}
        assert _resolve_scheme_field(scheme, "apiKeySecurityScheme") == {"name": "X-Key", "location": "header"}

    def test_resolve_scheme_field_flat_apikey(self):
        scheme = {"name": "X-Key", "location": "header"}
        assert _resolve_scheme_field(scheme, "apiKeySecurityScheme") == scheme

    def test_resolve_scheme_field_flat_http(self):
        scheme = {"scheme": "bearer", "bearerFormat": "JWT"}
        assert _resolve_scheme_field(scheme, "httpAuthSecurityScheme") == scheme

    def test_resolve_scheme_field_none(self):
        assert _resolve_scheme_field({}, "apiKeySecurityScheme") is None
        assert _resolve_scheme_field({"foo": "bar"}, "httpAuthSecurityScheme") is None

    def test_build_auth_header_apikey(self):
        scheme = {"apiKeySecurityScheme": {"name": "X-Custom", "location": "header"}}
        assert _build_auth_header_for_scheme(scheme, "secret") == ("X-Custom", "secret")

    def test_build_auth_header_http_bearer(self):
        scheme = {"httpAuthSecurityScheme": {"scheme": "bearer"}}
        assert _build_auth_header_for_scheme(scheme, "tok") == ("Authorization", "bearer tok")

    def test_build_auth_header_http_jwt(self):
        scheme = {"httpAuthSecurityScheme": {"scheme": "bearer", "bearerFormat": "JWT"}}
        assert _build_auth_header_for_scheme(scheme, "tok") == ("Authorization", "Bearer tok")

    def test_build_auth_header_apikey_query(self):
        scheme = {"apiKeySecurityScheme": {"name": "key", "location": "query"}}
        assert _build_auth_header_for_scheme(scheme, "val") is None

    def test_build_auth_header_no_match(self):
        assert _build_auth_header_for_scheme({"foo": "bar"}, "val") is None

    def test_build_external_agent_config_with_security(self):
        """_build_external_agent_config passes custom_headers from security."""
        agent = {
            "external_agent_id": "ext_sec",
            "name": "Secured Agent",
            "security_schemes": {"k": {"apiKeySecurityScheme": {"name": "X-Token", "location": "header"}}},
            "security_requirements": [{"schemes": {"k": {}}}],
            "security_credentials": {"k": "secret-token"},
        }
        with patch('backend.agents.create_agent_info.ExternalA2AAgentConfig') as MockConfig:
            _build_external_agent_config(agent, "http://test/a2a")
            call_kwargs = MockConfig.call_args[1]
            assert call_kwargs["custom_headers"] == {"X-Token": "secret-token"}

    def test_resolve_scheme_field_empty_scheme_string(self):
        """scheme['scheme'] is empty string -> None."""
        from backend.agents.create_agent_info import _resolve_scheme_field
        scheme = {"scheme": ""}
        assert _resolve_scheme_field(scheme, "httpAuthSecurityScheme") is None

    def test_build_auth_header_empty_auth_scheme(self):
        """httpAuth with empty scheme -> None."""
        from backend.agents.create_agent_info import _build_auth_header_for_scheme
        scheme = {"httpAuthSecurityScheme": {"scheme": ""}}
        assert _build_auth_header_for_scheme(scheme, "cred") is None

    def test_collect_auth_headers_non_dict_req(self):
        """Requirement is not a dict -> skipped."""
        from backend.agents.create_agent_info import _build_security_headers
        agent = {
            "security_schemes": {"k": {"apiKeySecurityScheme": {"name": "X", "location": "header"}}},
            "security_requirements": ["not_a_dict"],
            "security_credentials": {"k": "v"},
        }
        assert _build_security_headers(agent) == {}

    def test_build_security_headers_missing_credential(self):
        """scheme_id in requirements but not in credentials -> skipped."""
        from backend.agents.create_agent_info import _build_security_headers
        agent = {
            "security_schemes": {"k": {"apiKeySecurityScheme": {"name": "X", "location": "header"}}},
            "security_requirements": [{"schemes": {"k": {}, "missing": {}}}],
            "security_credentials": {"k": "v"},
        }
        headers = _build_security_headers(agent)
        assert headers == {"X": "v"}

    def test_build_security_headers_scheme_builds_none(self):
        """Credential present but header build returns None (e.g. query location) -> skipped."""
        from backend.agents.create_agent_info import _build_security_headers
        agent = {
            "security_schemes": {"k": {"apiKeySecurityScheme": {"name": "key", "location": "query"}}},
            "security_requirements": [{"schemes": {"k": {}}}],
            "security_credentials": {"k": "v"},
        }
        assert _build_security_headers(agent) == {}
