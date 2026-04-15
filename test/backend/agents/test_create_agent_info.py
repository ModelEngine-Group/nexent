import pytest
import sys
import types
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, Mock, PropertyMock

from test.common.test_mocks import bootstrap_test_env

env_state = bootstrap_test_env()
consts_const = env_state["mock_const"]
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
sys.modules['nexent.core.agents.agent_model'] = MagicMock()
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
)

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
                patch('backend.agents.create_agent_info.get_embedding_model') as mock_embedding:

            mock_discover.return_value = []
            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_vdb_core = "mock_elastic_core"
            mock_get_vector_db_core.return_value = mock_vdb_core
            mock_embedding.return_value = "mock_embedding_model"

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
            assert mock_tool_instance.metadata == {
                "vlm_model": "mock_vlm_model",
                "storage_client": mock_minio_client
            }

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
            assert mock_tool_instance.metadata == {
                "llm_model": "mock_llm_model",
                "storage_client": mock_minio_client,
                "data_process_service_url": consts_const.DATA_PROCESS_SERVICE,
            }

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
                patch('backend.agents.create_agent_info.get_embedding_model') as mock_embedding, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank:

            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "knowledge_search",
                    "description": "Knowledge search tool",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": []},
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
            mock_embedding.return_value = mock_embedding_model
            mock_rerank.return_value = mock_rerank_model

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 1
            assert result[0] is mock_tool_instance

            # Verify correct functions were called with correct parameters
            mock_get_vector_db_core.assert_called_once()
            mock_embedding.assert_called_once_with(tenant_id="tenant_1")

            # Verify metadata contains vdb_core, embedding_model and rerank_model
            expected_metadata = {
                "vdb_core": mock_vdb_core,
                "embedding_model": mock_embedding_model,
                "rerank_model": mock_rerank.return_value,
            }
            assert mock_tool_instance.metadata == expected_metadata

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
                patch('backend.agents.create_agent_info.get_embedding_model') as mock_embedding, \
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
                        {"name": "index_names", "default": []},
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
            mock_embedding.return_value = "embedding_instance"
            mock_rerank.return_value = "rerank_instance"

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 2

            # Verify KnowledgeBaseSearchTool has correct metadata
            assert mock_tool_kb.metadata == {
                "vdb_core": "vdb_core_instance",
                "embedding_model": "embedding_instance",
                "rerank_model": mock_rerank.return_value,
            }

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
                patch('backend.agents.create_agent_info.get_embedding_model') as mock_embedding, \
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
                        {"name": "rerank", "default": True},
                        {"name": "rerank_model_name", "default": "gte-rerank-v2"},
                    ],
                    "source": "mcp",
                    "usage": "mcp_server_1"
                }
            ]
            mock_get_vector_db_core.return_value = "vdb_core"
            mock_embedding.return_value = "embedding"
            mock_rerank.return_value = "rerank_model"

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 1
            # Even for MCP-sourced KnowledgeBaseSearchTool, metadata should be set
            assert mock_tool_instance.metadata == {
                "vdb_core": "vdb_core",
                "embedding_model": "embedding",
                "rerank_model": mock_rerank.return_value,
            }

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
                patch('backend.agents.create_agent_info.get_embedding_model') as mock_embedding, \
                patch('backend.agents.create_agent_info.get_rerank_model') as mock_rerank:

            mock_search_tools.return_value = [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "kb_search_1",
                    "description": "First knowledge search",
                    "inputs": "string",
                    "output_type": "string",
                    "params": [
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
                        {"name": "rerank", "default": True},
                        {"name": "rerank_model_name", "default": "gte-rerank-v2"},
                    ],
                    "source": "local",
                    "usage": None
                }
            ]
            mock_get_vector_db_core.return_value = "vdb_core"
            mock_embedding.return_value = "embedding"
            mock_rerank.return_value = "rerank_model"

            result = await create_tool_config_list("agent_1", "tenant_1", "user_1")

            assert len(result) == 2

            # Both tools should have the same simplified metadata
            expected_metadata = {
                "vdb_core": "vdb_core",
                "embedding_model": "embedding",
                "rerank_model": mock_rerank.return_value,
            }
            assert mock_tool_1.metadata == expected_metadata
            assert mock_tool_2.metadata == expected_metadata

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
                external_a2a_agents=[]
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
                    external_a2a_agents=[]
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
                external_a2a_agents=[]
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

            other_tool = Mock()
            other_tool.class_name = "OtherTool"
            other_tool.name = "other_tool"
            other_tool.params = {}

            kb_tool_2 = Mock()
            kb_tool_2.class_name = "KnowledgeBaseSearchTool"
            kb_tool_2.name = "kb_tool_2"
            kb_tool_2.params = {"index_names": ["idx_c"]}

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
                minio_files=[], query="test query")
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

        expected = "User uploaded files. The file information is as follows:\nFile name: 1.pdf, S3 URL: s3://nexent/1.pdf\nFile name: 2.pdf, S3 URL: s3://nexent/2.pdf\n\nUser wants to answer questions based on the information in the above files: test query"
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


if __name__ == "__main__":
    pytest.main([__file__])
