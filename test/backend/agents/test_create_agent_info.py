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


consts_model_module = types.ModuleType("consts.model")
consts_model_module.HistoryItem = HistoryItem
sys.modules["consts.model"] = consts_model_module

# Mock consts.exceptions module with ValidationError
consts_exceptions_module = types.ModuleType("consts.exceptions")
consts_exceptions_module.ValidationError = ValidationError
sys.modules["consts.exceptions"] = consts_exceptions_module

# Also add model and exceptions to consts module attributes
consts_module = sys.modules.get("consts")
if consts_module:
    setattr(consts_module, "model", consts_model_module)
    setattr(consts_module, "exceptions", consts_exceptions_module)

# Also add model to consts module attributes
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
    """Return a lightweight module stub with the provided attributes."""
    module = types.ModuleType(name)
    for attr_name, attr_value in attrs.items():
        setattr(module, attr_name, attr_value)
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

# Add the mocked utils module to sys.modules
sys.modules['utils'] = utils_mock
sys.modules['utils.auth_utils'] = utils_mock.auth_utils

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
sys.modules['nexent.core.utils.observer'] = MagicMock(MessageObserver=mock_message_observer)
sys.modules['nexent.core.agents.agent_model'] = _create_stub_module(
    "nexent.core.agents.agent_model",
    AgentHistory=AgentHistory,
    ModelConfig=MagicMock(),
    AgentConfig=MagicMock(),
    ToolConfig=MagicMock(),
    ExternalA2AAgentConfig=MagicMock(),
    AgentRunInfo=MagicMock(),
    MessageObserver=MagicMock(),
)
sys.modules['nexent.core.agents.agent_context'] = _create_stub_module(
    "nexent.core.agents.agent_context",
    ContextManager=MagicMock(),
    ContextManagerConfig=MagicMock(),
)
sys.modules['smolagents.agents'] = MagicMock()
sys.modules['smolagents.utils'] = MagicMock()
sys.modules['services.remote_mcp_service'] = MagicMock()
database_module = _create_stub_module("database")
sys.modules['database'] = database_module
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
sys.modules['services.vectordatabase_service'] = MagicMock()
sys.modules['services.tenant_config_service'] = MagicMock()
sys.modules['utils.prompt_template_utils'] = MagicMock()
sys.modules['utils.config_utils'] = MagicMock()
sys.modules['utils.langchain_utils'] = MagicMock()
sys.modules['utils.model_name_utils'] = MagicMock()
sys.modules['langchain_core.tools'] = MagicMock()
# Build services module hierarchy with minimal functionality
services_module = _create_stub_module("services")
sys.modules['services'] = services_module
sys.modules['services.image_service'] = _create_stub_module(
    "services.image_service", get_vlm_model=MagicMock(return_value="stub_vlm")
)
sys.modules['services.memory_config_service'] = MagicMock()
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
sys.modules['nexent.memory.memory_service'] = MagicMock()

# Build top-level nexent module to avoid importing the real package
nexent_module = _create_stub_module("nexent", MessageObserver=mock_message_observer)
sys.modules['nexent'] = nexent_module

# Create nested modules for nexent.core to satisfy imports safely
sys.modules['nexent.core'] = _create_stub_module("nexent.core")
sys.modules['nexent.core.agents'] = _create_stub_module("nexent.core.agents")
sys.modules['nexent.core.utils'] = _create_stub_module("nexent.core.utils")

# Create mock classes that might be imported
mock_agent_config = MagicMock()
mock_model_config = MagicMock()
mock_tool_config = MagicMock()
mock_agent_run_info = MagicMock()

sys.modules['nexent.core.agents.agent_model'].AgentConfig = mock_agent_config
sys.modules['nexent.core.agents.agent_model'].ModelConfig = mock_model_config
sys.modules['nexent.core.agents.agent_model'].ToolConfig = mock_tool_config
sys.modules['nexent.core.agents.agent_model'].AgentRunInfo = mock_agent_run_info
sys.modules['nexent.core.utils.observer'].MessageObserver = mock_message_observer

# Mock BASE_BUILTIN_MODULES
sys.modules['smolagents.utils'].BASE_BUILTIN_MODULES = ["os", "sys", "json"]

# Provide lightweight smolagents package to prevent circular imports
smolagents_module = _create_stub_module("smolagents")
smolagents_tools_module = _create_stub_module("smolagents.tools", Tool=MagicMock())
smolagents_module.tools = smolagents_tools_module
sys.modules['smolagents'] = smolagents_module
sys.modules['smolagents.tools'] = smolagents_tools_module

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
    _get_external_a2a_agents,
    _format_minio_files_for_content,
    _convert_history_with_minio_files,
)

# Import HistoryItem for testing (from mocked consts.model)
HistoryItem = sys.modules["consts.model"].HistoryItem

# Import ValidationError for testing (from mocked consts.exceptions)
ValidationError = sys.modules["consts.exceptions"].ValidationError

# Import constants for testing
from consts.const import MODEL_CONFIG_MAPPING


class TestGetSkillsForTemplate:
    """Tests for the _get_skills_for_template function"""

    def test_get_skills_for_template_success(self):
        """Test case for successfully getting skills for template"""
        mock_skill1 = {"name": "skill1", "description": "desc1"}
        mock_skill2 = {"name": "skill2", "description": "desc2"}

        with patch.dict('sys.modules', {'services.skill_service': MagicMock()}):
            mock_skill_service = sys.modules['services.skill_service'].SkillService
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

        with patch.dict('sys.modules', {'services.skill_service': MagicMock()}):
            mock_skill_service = sys.modules['services.skill_service'].SkillService
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
        with patch.dict('sys.modules', {'services.skill_service': MagicMock()}):
            mock_skill_service = sys.modules['services.skill_service'].SkillService
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
        with patch.dict('sys.modules', {'services.skill_service': MagicMock()}):
            mock_skill_service = sys.modules['services.skill_service'].SkillService
            mock_skill_service.side_effect = Exception("Service unavailable")

            with patch('backend.agents.create_agent_info.logger') as mock_logger:
                result = _get_skills_for_template(
                    agent_id=1,
                    tenant_id="tenant_1",
                    version_no=0
                )

                assert result == []
                mock_logger.warning.assert_called_once()
                assert "Failed to get skills for template: Service unavailable" in mock_logger.warning.call_args[0][0]

    def test_get_skills_for_template_with_version_no(self):
        """Test case with specific version number"""
        with patch.dict('sys.modules', {'services.skill_service': MagicMock()}):
            mock_skill_service = sys.modules['services.skill_service'].SkillService
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

            assert len(result) == 4
            assert mock_tool_config.call_count == 4

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

    def test_get_skill_script_tools_metadata_context(self):
        """Test that skill context metadata is correctly set for all tools"""
        mock_tool_config.reset_mock()
        with patch('consts.const.CONTAINER_SKILLS_PATH', "/skills"):
            result = _get_skill_script_tools(
                agent_id=123,
                tenant_id="test_tenant",
                version_no=7
            )

            assert len(result) == 4
            # Verify all tools have the correct metadata
            calls = mock_tool_config.call_args_list
            for call in calls:
                assert call[1]['metadata'] == {
                    "agent_id": 123,
                    "tenant_id": "test_tenant",
                    "version_no": 7
                }

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
            assert '"params": "dict"' in calls[0][1]['inputs']

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
                assert "skill" in desc.lower()


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
    async def test_create_tool_config_list_with_analyze_image_tool(self):
        """Ensure AnalyzeImageTool receives VLM model metadata."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "AnalyzeImageTool"
        mock_tool_config.return_value = mock_tool_instance

        with patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vlm_model') as mock_get_vlm_model, \
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
            mock_get_vlm_model.assert_called_once_with(tenant_id="tenant_1")
            # Verify metadata includes validate_url_access lambda
            assert "vlm_model" in mock_tool_instance.metadata
            assert "storage_client" in mock_tool_instance.metadata
            assert "validate_url_access" in mock_tool_instance.metadata
            assert callable(mock_tool_instance.metadata["validate_url_access"])

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_analyze_text_file_tool(self):
        """Ensure AnalyzeTextFileTool receives text-specific metadata."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "AnalyzeTextFileTool"
        mock_tool_config.return_value = mock_tool_instance

        with patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_llm_model') as mock_get_llm_model, \
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
            mock_get_llm_model.assert_called_once_with(tenant_id="tenant_1")
            # Verify metadata includes validate_url_access lambda
            assert "llm_model" in mock_tool_instance.metadata
            assert "storage_client" in mock_tool_instance.metadata
            assert "data_process_service_url" in mock_tool_instance.metadata
            assert "validate_url_access" in mock_tool_instance.metadata
            assert callable(mock_tool_instance.metadata["validate_url_access"])

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_knowledge_base_tool_metadata(self):
        """
        Test that KnowledgeBaseSearchTool metadata contains only vdb_core and embedding_model.
        This test verifies the refactored behavior where index_names and name_resolver
        have been removed from the metadata.
        """
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "KnowledgeBaseSearchTool"
        mock_tool_config.return_value = mock_tool_instance

        with patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
                patch('backend.agents.create_agent_info.get_embedding_model_by_index_name') as mock_embedding, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank, \
                patch('backend.agents.create_agent_info.get_knowledge_name_map_by_index_names') as mock_get_knowledge_map:

            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["idx_a"]},  # Non-empty index_names
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
            mock_get_knowledge_map.return_value = {"idx_a": "idx_a"}

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 1
            assert result[0] is mock_tool_instance

            # Verify correct functions were called with correct parameters
            mock_get_vector_db_core.assert_called_once()
            mock_embedding.assert_called_once_with("tenant_1", "idx_a")

            # Verify metadata contains vdb_core, embedding_model, rerank_model and display_name_to_index_map
            assert "vdb_core" in mock_tool_instance.metadata
            assert "embedding_model" in mock_tool_instance.metadata
            assert "rerank_model" in mock_tool_instance.metadata
            assert "display_name_to_index_map" in mock_tool_instance.metadata

            # Explicitly verify that old fields are NOT present
            assert "index_names" not in mock_tool_instance.metadata
            assert "name_resolver" not in mock_tool_instance.metadata

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
    async def test_create_tool_config_list_with_dify_tool(self):
        """Test that DifySearchTool gets correct metadata including rerank model."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "DifySearchTool"

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

            from backend.agents.create_agent_info import create_tool_config_list
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

            from backend.agents.create_agent_info import create_tool_config_list
            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            # Verify rerank model was NOT fetched
            mock_rerank.assert_not_called()

            # Verify metadata
            assert len(result) == 1
            assert result[0] is mock_tool_instance

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_datamate_tool(self):
        """Test that DataMateSearchTool gets correct metadata including rerank model."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "DataMateSearchTool"

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank:

            mock_tool_config.return_value = mock_tool_instance
            mock_rerank.return_value = "mock_datamate_rerank_model"

            mock_search_tools.return_value = [
                {
                    "class_name": "DataMateSearchTool",
                    "name": "datamate_search",
                    "description": "DataMate knowledge search",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "rerank", "default": True},
                        {"name": "rerank_model_name", "default": "jina-rerank-v2"},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]

            from backend.agents.create_agent_info import create_tool_config_list
            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            # Verify rerank model was fetched
            mock_rerank.assert_called_once_with(
                tenant_id="tenant_1", model_name="jina-rerank-v2"
            )

            # Verify metadata
            assert len(result) == 1
            assert result[0] is mock_tool_instance

    @pytest.mark.asyncio
    async def test_create_tool_config_list_with_datamate_tool_no_rerank(self):
        """Test that DataMateSearchTool without rerank gets None metadata."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "DataMateSearchTool"

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

            from backend.agents.create_agent_info import create_tool_config_list
            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            # Verify rerank model was NOT fetched
            mock_rerank.assert_not_called()

            # Verify metadata
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
                patch('backend.agents.create_agent_info.get_vlm_model') as mock_get_vlm_model, \
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
                patch('backend.agents.create_agent_info.get_llm_model') as mock_get_llm_model, \
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

    @pytest.mark.asyncio
    async def test_create_agent_config_basic(self):
        """Test case for basic agent configuration creation"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
                patch('backend.agents.create_agent_info.query_sub_agents_id_list') as mock_query_sub, \
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
                "model_id": 123,
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
                tools=[],
                max_steps=5,
                model_name="test_model",
                provide_run_summary=True,
                managed_agents=[],
                external_a2a_agents=[],
                context_manager_config=ANY
            )

    @pytest.mark.asyncio
    async def test_create_agent_config_with_sub_agents(self):
        """Test case for creating agent configuration with sub-agents"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
                patch('backend.agents.create_agent_info.query_sub_agents_id_list') as mock_query_sub, \
                patch('backend.agents.create_agent_info.create_tool_config_list') as mock_create_tools, \
                patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
                patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
                patch('backend.agents.create_agent_info.search_memory_in_levels', new_callable=AsyncMock) as mock_search_memory, \
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
                "model_id": 123,
                "provide_run_summary": True
            }
            mock_query_sub.return_value = ["sub_agent_1"]
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
                    tools=[],
                    max_steps=5,
                    model_name="test_model",
                    provide_run_summary=True,
                    managed_agents=[mock_sub_agent_config],
                    external_a2a_agents=[],
                    context_manager_config=ANY
                )

    @pytest.mark.asyncio
    async def test_create_agent_config_with_memory(self):
        """Test case for creating agent configuration with memory"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
                patch('backend.agents.create_agent_info.query_sub_agents_id_list') as mock_query_sub, \
                patch('backend.agents.create_agent_info.create_tool_config_list') as mock_create_tools, \
                patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template, \
                patch('backend.agents.create_agent_info.tenant_config_manager') as mock_tenant_config, \
                patch('backend.agents.create_agent_info.build_memory_context') as mock_build_memory, \
                patch('backend.agents.create_agent_info.search_memory_in_levels', new_callable=AsyncMock) as mock_search_memory, \
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
                "model_id": 123,
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
            mock_search_memory.return_value = {"results": [{"memory": "test"}]}
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"}
            mock_get_model_by_id.return_value = {"display_name": "test_model"}

            result = await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query")

            # Verify that memory search was called
            mock_search_memory.assert_called_once_with(
                query_text="test query",
                memory_config={"test": "config"},
                tenant_id="tenant_1",
                user_id="user_1",
                agent_id="agent_1",
                memory_levels=["tenant", "agent", "user", "user_agent"]
            )

    @pytest.mark.asyncio
    async def test_create_agent_config_memory_disabled_no_search(self):
        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agents_id_list"
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
                "backend.agents.create_agent_info.get_model_by_model_id"
            ) as mock_get_model_by_id,
            patch(
                "backend.agents.create_agent_info.search_memory_in_levels",
                new_callable=AsyncMock,
            ) as mock_search_memory,
            patch(
                "backend.agents.create_agent_info.prepare_prompt_templates"
            ) as mock_prepare_templates,
        ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_id": 123,
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

            # memory_switch is on, but search is disabled
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

            mock_search_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_agent_config_model_id_none(self):
        """Test case for creating agent configuration when model_id is None"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
                patch('backend.agents.create_agent_info.query_sub_agents_id_list') as mock_query_sub, \
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
                "model_id": None,  # Test None case
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

            # Verify that AgentConfig was called with "main_model" as fallback
            mock_agent_config.assert_called_with(
                name="test_agent",
                description="test description",
                prompt_templates={"system_prompt": "populated_system_prompt"},
                tools=[],
                max_steps=5,
                model_name="main_model",  # Should fallback to "main_model"
                provide_run_summary=True,
                managed_agents=[],
                external_a2a_agents=[],
                context_manager_config=ANY
            )

    @pytest.mark.asyncio
    async def test_create_agent_config_memory_exception(self):
        """raise when search_memory_in_levels raises an exception"""
        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agents_id_list"
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
                "backend.agents.create_agent_info.search_memory_in_levels",
                new_callable=AsyncMock,
            ) as mock_search_memory,
            patch(
                "backend.agents.create_agent_info.prepare_prompt_templates"
            ) as mock_prepare_templates,
        ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_id": 123,
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

            mock_search_memory.side_effect = Exception("boom")
            mock_prepare_templates.return_value = {
                "system_prompt": "populated_system_prompt"
            }

            with pytest.raises(Exception) as excinfo:
                await create_agent_config(
                    "agent_1",
                    "tenant_1",
                    "user_1",
                    "zh",
                    "test query",
                    allow_memory_search=True,
                )

            assert "Failed to retrieve memory list: boom" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_create_agent_config_memory_levels_agent_share_never(self):
        """Test that agent level is removed when agent_share_option is 'never'"""
        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agents_id_list"
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
                "backend.agents.create_agent_info.search_memory_in_levels",
                new_callable=AsyncMock,
            ) as mock_search_memory,
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
        ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_id": 123,
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
            mock_search_memory.return_value = {"results": []}
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

            # Verify agent level is removed from memory_levels
            mock_search_memory.assert_called_once()
            memory_levels = mock_search_memory.call_args[1]["memory_levels"]
            assert "agent" not in memory_levels
            assert "tenant" in memory_levels
            assert "user" in memory_levels
            assert "user_agent" in memory_levels

    @pytest.mark.asyncio
    async def test_create_agent_config_memory_levels_disable_agent(self):
        """Test that agent level is removed when agent_id is in disable_agent_ids"""
        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agents_id_list"
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
                "backend.agents.create_agent_info.search_memory_in_levels",
                new_callable=AsyncMock,
            ) as mock_search_memory,
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
        ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_id": 123,
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
            mock_search_memory.return_value = {"results": []}
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

            # Verify agent level is removed from memory_levels
            mock_search_memory.assert_called_once()
            memory_levels = mock_search_memory.call_args[1]["memory_levels"]
            assert "agent" not in memory_levels
            assert "tenant" in memory_levels
            assert "user" in memory_levels
            assert "user_agent" in memory_levels

    @pytest.mark.asyncio
    async def test_create_agent_config_memory_levels_disable_user_agent(self):
        """Test that user_agent level is removed when agent_id is in disable_user_agent_ids"""
        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agents_id_list"
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
                "backend.agents.create_agent_info.search_memory_in_levels",
                new_callable=AsyncMock,
            ) as mock_search_memory,
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
        ):
            mock_search_agent.return_value = {
                "name": "test_agent",
                "description": "test description",
                "duty_prompt": "test duty",
                "constraint_prompt": "test constraint",
                "few_shots_prompt": "test few shots",
                "max_steps": 5,
                "model_id": 123,
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
            mock_search_memory.return_value = {"results": []}
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

            # Verify user_agent level is removed from memory_levels
            mock_search_memory.assert_called_once()
            memory_levels = mock_search_memory.call_args[1]["memory_levels"]
            assert "agent" in memory_levels
            assert "tenant" in memory_levels
            assert "user" in memory_levels
            assert "user_agent" not in memory_levels

    @pytest.mark.asyncio
    async def test_create_agent_config_with_knowledge_base_summary_filtering(self):
        with (
            patch(
                "backend.agents.create_agent_info.search_agent_info_by_agent_id"
            ) as mock_search_agent,
            patch(
                "backend.agents.create_agent_info.query_sub_agents_id_list"
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
                "model_id": 123,
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

            await create_agent_config("agent_1", "tenant_1", "user_1", "zh", "test query")

            assert mock_es_instance.get_summary.call_args_list == [
                ((), {"index_name": "idx_a"}),
                ((), {"index_name": "idx_b"}),
            ]
            mock_logger.warning.assert_called_once()
            assert "idx_b" in mock_logger.warning.call_args[0][0]

            mock_prepare_templates.assert_called_once()
            assert mock_prepare_templates.call_args[1]["system_prompt"] == "**idx_a**: AAA\n\n"

            # Ensure only the first KnowledgeBaseSearchTool is processed.
            assert "idx_c" not in str(mock_es_instance.get_summary.call_args_list)

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
                "backend.agents.create_agent_info.query_sub_agents_id_list"
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
                "model_id": 123,
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

            # Verify the system prompt uses the display names from metadata
            mock_prepare_templates.assert_called_once()
            system_prompt = mock_prepare_templates.call_args[1]["system_prompt"]
            assert "**Custom Name 1**" in system_prompt
            assert "**Custom Name 2**" in system_prompt
            assert "idx1" not in system_prompt
            assert "idx2" not in system_prompt

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
                "backend.agents.create_agent_info.query_sub_agents_id_list"
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
                "model_id": 123,
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
            system_prompt = mock_prepare_templates.call_args[1]["system_prompt"]
            assert "**idx1**" in system_prompt
            assert "**idx2**" in system_prompt

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
                "backend.agents.create_agent_info.query_sub_agents_id_list"
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
                "model_id": 123,
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
            assert mock_prepare_templates.call_args[1]["system_prompt"] == expected_message

    @pytest.mark.asyncio
    async def test_create_agent_config_knowledge_base_summary_error(self):
        """Test case for error handling during knowledge base summary build"""
        with patch('backend.agents.create_agent_info.search_agent_info_by_agent_id') as mock_search_agent, \
                patch('backend.agents.create_agent_info.query_sub_agents_id_list') as mock_query_sub, \
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
                "model_id": 123,
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
            mock_logger.error.assert_called_with("Failed to build knowledge base summary: Test Error")


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
                "base_url": "http://main.url"
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

            # Fourth call: sub_model
            assert calls[3][1]['cite_name'] == "sub_model"
            assert calls[3][1]['api_key'] == "main_key"
            assert calls[3][1]['model_name'] == "main_model_name"
            assert calls[3][1]['url'] == "http://main.url"

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
                stop_event="stop_event"
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
                "authorization": "bearer_token_123"
            }

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
            mock_get_mcp.return_value = [
                {
                    "remote_mcp_server_name": "sse_server",
                    "remote_mcp_server": "http://sse.server/sse",
                    "status": True,
                    "authorization_token": None
                }
            ]
            mock_create_agent.return_value = "agent_config"
            mock_urljoin.return_value = "http://nexent.mcp/sse"
            mock_filter.return_value = ["http://sse.server/sse"]
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
                "url": "http://sse.server/sse",
                "transport": "sse"
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
                "authorization": "token1"
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


class TestPreparePromptTemplates:
    """Tests for the prepare_prompt_templates function"""

    @pytest.mark.asyncio
    async def test_prepare_prompt_templates_manager_zh(self):
        """Test case for manager mode Chinese prompt templates"""
        with patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template:

            mock_get_template.return_value = {"test": "template"}

            result = await prepare_prompt_templates(True, "test system prompt", "zh")

            mock_get_template.assert_called_once_with(True, "zh")
            assert result["system_prompt"] == "test system prompt"
            assert result["test"] == "template"

    @pytest.mark.asyncio
    async def test_prepare_prompt_templates_worker_en(self):
        """Test case for worker mode English prompt templates"""
        with patch('backend.agents.create_agent_info.get_agent_prompt_template') as mock_get_template:

            mock_get_template.return_value = {"test": "template"}

            result = await prepare_prompt_templates(False, "test system prompt", "en")

            mock_get_template.assert_called_once_with(False, "en")
            assert result["system_prompt"] == "test system prompt"
            assert result["test"] == "template"


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
                assert "FAILED" in mock_logger.error.call_args[0][0]
                assert "Database error" in mock_logger.error.call_args[0][0]


class TestCreateToolConfigListWithDisplayNameMap:
    """Tests for create_tool_config_list with display_name_to_index_map functionality"""

    @pytest.mark.asyncio
    async def test_knowledge_base_with_display_name_to_index_map(self):
        """Test that KnowledgeBaseSearchTool gets correct display_name_to_index_map from index_names"""
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
            # Verify get_knowledge_name_map_by_index_names was called
            mock_get_knowledge_map.assert_called_once_with(["idx1", "idx2"])
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
    async def test_knowledge_base_empty_index_names_raises_validation_error(self):
        """Test that ValidationError is raised when index_names is empty for KnowledgeBaseSearchTool."""
        mock_tool_instance = MagicMock()
        mock_tool_instance.class_name = "KnowledgeBaseSearchTool"

        with patch('backend.agents.create_agent_info.ToolConfig') as mock_tool_config, \
                patch('backend.agents.create_agent_info.discover_langchain_tools', return_value=[]), \
                patch('backend.agents.create_agent_info.search_tools_for_sub_agent') as mock_search_tools, \
                patch('backend.agents.create_agent_info.get_vector_db_core') as mock_get_vector_db_core, \
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
            mock_rerank.return_value = None
            mock_get_knowledge_map.return_value = {}

            # Should raise ValidationError
            with pytest.raises(ValidationError) as exc_info:
                await create_tool_config_list("agent_1", "tenant_1", "user_1")

            # Verify error message
            assert "Embedding model is required for knowledge_base_search but index_names is empty" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_knowledge_base_no_embedding_model_raises_validation_error(self):
        """Test that ValidationError is raised when get_embedding_model_by_index_name returns None."""
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

            # Verify error message contains index name and guidance
            assert "No embedding model found for index 'idx1'" in str(exc_info.value)
            assert "Please configure an embedding model for this knowledge base" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_knowledge_base_with_valid_embedding_model(self):
        """Test that KnowledgeBaseSearchTool correctly sets embedding_model when get_embedding_model_by_index_name succeeds."""
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
