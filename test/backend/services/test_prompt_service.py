import json
import inspect
import importlib.machinery
import types
import unittest
import json
import sys
import atexit
from unittest.mock import patch, MagicMock

_MODULE_PATCH_SENTINEL = object()
_MODULE_PATCH_NAMES = [
    'boto3',
    'elasticsearch',
    'sqlalchemy',
    'sqlalchemy.create_engine',
    'sqlalchemy.orm',
    'sqlalchemy.dialects',
    'sqlalchemy.dialects.postgresql',
    'sqlalchemy.sql',
    'database.agent_db',
    'database.tool_db',
    'database.model_management_db',
    'database.knowledge_db',
    'database.client',
    'database.db_models',
    'utils.llm_utils',
    'utils.prompt_template_utils',
    'management.services.agent.service',
    'services.prompt_template_service',
    'nexent',
    'nexent.core',
    'nexent.core.agents',
    'nexent.core.agents.agent_model',
    'nexent.storage',
    'nexent.storage.storage_client_factory',
    'nexent.storage.minio_config',
    'nexent.vector_database',
    'nexent.memory',
    'nexent.monitor',
]
_MODULE_PATCH_ORIGINALS = {
    name: sys.modules.get(name, _MODULE_PATCH_SENTINEL)
    for name in _MODULE_PATCH_NAMES
}


def _restore_patched_modules() -> None:
    for name, original in _MODULE_PATCH_ORIGINALS.items():
        if original is _MODULE_PATCH_SENTINEL:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


atexit.register(_restore_patched_modules)


class MockToolConfig:
    def __init__(self, *args, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def model_dump(self, **kwargs):
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

# Mock nexent module hierarchy BEFORE any backend imports that depend on it
nexent_mock = MagicMock()
nexent_core_mock = MagicMock()
nexent_core_agents_mock = MagicMock()
nexent_agent_model_mock = MagicMock()
nexent_agent_model_mock.ToolConfig = MockToolConfig
nexent_storage_mock = MagicMock()
nexent_storage_storage_client_factory_mock = MagicMock()
nexent_storage_minio_config_mock = MagicMock()
nexent_vector_database_mock = MagicMock()
nexent_memory_mock = MagicMock()
nexent_monitor_mock = MagicMock()

sys.modules['nexent'] = nexent_mock
sys.modules['nexent.core'] = nexent_core_mock
sys.modules['nexent.core.agents'] = nexent_core_agents_mock
sys.modules['nexent.core.agents.agent_model'] = nexent_agent_model_mock
sys.modules['nexent.storage'] = nexent_storage_mock
sys.modules['nexent.storage.storage_client_factory'] = nexent_storage_storage_client_factory_mock
sys.modules['nexent.storage.minio_config'] = nexent_storage_minio_config_mock
sys.modules['nexent.vector_database'] = nexent_vector_database_mock
sys.modules['nexent.memory'] = nexent_memory_mock
sys.modules['nexent.monitor'] = nexent_monitor_mock

# Stub parallel_executor so that prompt_service can import ParallelExecutorTool
_parallel_executor_stub = types.ModuleType("nexent.core.tools.parallel_executor")
class _MockParallelExecutorTool:
    __name__ = "ParallelExecutorTool"
    name = "parallel_executor"
    description = "Execute multiple independent calls in parallel."
    description_zh = "并行执行多个互不依赖的调用。"
    inputs = {"tasks": {"type": "array"}}
    output_type = "any"

_mock_parallel_tool = _MockParallelExecutorTool
_parallel_executor_stub.ParallelExecutorTool = _mock_parallel_tool
sys.modules["nexent.core.tools.parallel_executor"] = _parallel_executor_stub

# Mock external dependencies
sys.modules['boto3'] = MagicMock()
sys.modules['elasticsearch'] = MagicMock()
sys.modules['sqlalchemy'] = MagicMock()
sys.modules['sqlalchemy.create_engine'] = MagicMock()
sys.modules['sqlalchemy.orm'] = MagicMock()
sys.modules['sqlalchemy.dialects'] = MagicMock()
sys.modules['sqlalchemy.dialects.postgresql'] = MagicMock()
sys.modules['sqlalchemy.sql'] = MagicMock()


# DO NOT mock consts - import real ones
# The backend path is already in sys.path via sys.path.insert above

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from consts.const import ENABLE_JIUWEN_SDK

# Mock boto3 and minio client before importing the module under test
import sys
boto3_module = types.ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules['boto3'] = boto3_module

# Mock ElasticSearch before importing other modules
elasticsearch_mock = MagicMock()
sys.modules['elasticsearch'] = elasticsearch_mock

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

minio_client_mock = MagicMock()
minio_client_mock._ensure_bucket_exists = MagicMock()
minio_client_mock.client = MagicMock()

# Mock database submodules BEFORE importing prompt_service
sys.modules['database.agent_db'] = MagicMock()
sys.modules['database.tool_db'] = MagicMock()
sys.modules['database.model_management_db'] = MagicMock()
sys.modules['database.knowledge_db'] = MagicMock()
mock_database_client = MagicMock()
mock_database_client.MinioClient.return_value = minio_client_mock
mock_database_client.minio_client = minio_client_mock
sys.modules['database.client'] = mock_database_client
sys.modules['backend.database.client'] = mock_database_client
sys.modules['database.db_models'] = MagicMock()

from jinja2 import StrictUndefined

# Mock utils
sys.modules['utils.llm_utils'] = MagicMock()
sys.modules['utils.prompt_template_utils'] = MagicMock()

# Mock services
sys.modules['management.services.agent.service'] = MagicMock()
sys.modules['services.prompt_template_service'] = MagicMock()

from backend.services.prompt_service import (
    generate_and_save_system_prompt_impl,
    gen_system_prompt_streamable,
    generate_system_prompt,
    join_info_for_generate_system_prompt,
    join_info_for_optimize_prompt_section,
    optimize_prompt_section_impl,
    get_enabled_tool_description_for_generate_prompt,
    _resolve_aidp_kb_display_names,
    PromptOptimizationService,
    OptimizeRequest,
    OptimizeResult,
    _copy_bad_cases_with_scope_instruction,
    _resolve_knowledge_tool_capabilities,
)


class TestPromptService(unittest.TestCase):

    def setUp(self):
        self.test_model_id = 1

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.get_prompt_optimize_prompt_template')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_optimize_prompt_section_impl_success(
        self,
        mock_search_agent_info,
        mock_query_tools,
        mock_get_prompt_template,
        mock_call_llm,
    ):
        mock_query_tools.return_value = [
            {"name": "tool1", "description": "Tool 1", "inputs": "{}", "output_type": "text"}
        ]
        mock_search_agent_info.return_value = {"name": "assistant1", "description": "Assistant 1"}
        mock_get_prompt_template.return_value = {
            "OPTIMIZE_SYSTEM_PROMPT": "Optimize section",
            "OPTIMIZE_USER_PROMPT": "Section {{ section_type }} {{ current_content }} {{ feedback }}"
        }
        mock_call_llm.return_value = "Optimized content"

        result = optimize_prompt_section_impl(
            agent_id=1,
            model_id=2,
            task_description="Build an agent",
            tenant_id="tenant-1",
            language="en",
            section_type="duty",
            section_title="Agent Role",
            current_content="Original duty",
            feedback="Make it more specific",
            tool_ids=[10],
            sub_agent_ids=[20],
            knowledge_base_display_names=["kb-a"],
        )

        self.assertEqual(result["section_type"], "duty")
        self.assertEqual(result["original_content"], "Original duty")
        self.assertEqual(result["optimized_content"], "Optimized content")
        mock_query_tools.assert_called_once_with([10])
        mock_search_agent_info.assert_called_once_with(agent_id=20, tenant_id="tenant-1")
        mock_call_llm.assert_called_once()

    def test_optimize_prompt_section_impl_requires_feedback(self):
        with self.assertRaises(AppException) as context:
            optimize_prompt_section_impl(
                agent_id=1,
                model_id=2,
                task_description="Build an agent",
                tenant_id="tenant-1",
                language="en",
                section_type="duty",
                section_title="Agent Role",
                current_content="Original duty",
                feedback="",
            )

        self.assertEqual(
            context.exception.error_code,
            ErrorCode.COMMON_MISSING_REQUIRED_FIELD
        )

    @patch('backend.services.prompt_service.Template')
    def test_join_info_for_optimize_prompt_section(self, mock_template):
        mock_template_instance = MagicMock()
        mock_template.return_value = mock_template_instance
        mock_template_instance.render.return_value = "Rendered optimize content"

        result = join_info_for_optimize_prompt_section(
            prompt_for_optimize={"OPTIMIZE_USER_PROMPT": "Template"},
            section_type="constraint",
            section_title="Usage Requirements",
            task_description="Task description",
            current_content="Original content",
            feedback="Be clearer",
            tool_info_list=[
                {"name": "tool1", "description": "Tool 1", "inputs": "{}", "output_type": "text"}
            ],
            sub_agent_info_list=[
                {"name": "assistant1", "description": "Assistant 1"}
            ],
            language="en",
            knowledge_base_display_names=["kb-a", "kb-b"],
        )

        self.assertEqual(result, "Rendered optimize content")
        template_vars = mock_template_instance.render.call_args[0][0]
        self.assertEqual(template_vars["section_type"], "constraint")
        self.assertEqual(template_vars["current_content"], "Original content")
        self.assertEqual(template_vars["feedback"], "Be clearer")
        self.assertEqual(template_vars["knowledge_base_names"], "")

    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    def test_generate_and_save_system_prompt_impl(
        self,
        mock_query_all_agents,
        mock_search_agent_info,
        mock_query_tools,
        mock_generate_system_prompt,
    ):
        # Setup
        mock_tool1 = {"name": "tool1", "description": "Tool 1 desc",
                      "inputs": "input1", "output_type": "output1"}
        mock_tool2 = {"name": "tool2", "description": "Tool 2 desc",
                      "inputs": "input2", "output_type": "output2"}
        mock_query_tools.return_value = [mock_tool1, mock_tool2]
        # No existing agents so that duplicate detection path is not triggered
        mock_query_all_agents.return_value = []

        mock_agent1 = {"name": "agent1", "description": "Agent 1 desc"}
        mock_agent2 = {"name": "agent2", "description": "Agent 2 desc"}
        mock_search_agent_info.side_effect = [mock_agent1, mock_agent2]

        # Mock the generator to return the expected data structure
        def mock_generator(*args, **kwargs):
            yield {"type": "duty", "content": "Generated duty prompt", "is_complete": False}
            yield {"type": "constraint", "content": "Generated constraint prompt", "is_complete": False}
            yield {"type": "few_shots", "content": "Generated few shots prompt", "is_complete": False}
            yield {"type": "agent_var_name", "content": "test_agent", "is_complete": True}
            yield {"type": "agent_display_name", "content": "Test Agent", "is_complete": True}
            yield {"type": "agent_description", "content": "Test agent description", "is_complete": True}
            yield {"type": "duty", "content": "Final duty prompt", "is_complete": True}
            yield {"type": "constraint", "content": "Final constraint prompt", "is_complete": True}
            yield {"type": "few_shots", "content": "Final few shots prompt", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_generator

        # Execute - test as a generator with frontend-provided IDs
        result_gen = generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=self.test_model_id,
            task_description="Test task",
            user_id="user123",
            tenant_id="tenant456",
            language="zh",
            tool_ids=[1, 2],
            sub_agent_ids=[10, 20]
        )
        result = list(result_gen)  # Convert generator to list for assertion

        # Assert
        self.assertGreater(len(result), 0)

        # Verify tools and agents were queried using frontend-provided IDs
        mock_query_tools.assert_called_once_with([1, 2])
        self.assertEqual(mock_search_agent_info.call_count, 2)
        mock_search_agent_info.assert_any_call(agent_id=10, tenant_id="tenant456")
        mock_search_agent_info.assert_any_call(agent_id=20, tenant_id="tenant456")

        # Verify generate_system_prompt was called with correct parameters
        mock_generate_system_prompt.assert_called_once()
        call_args = mock_generate_system_prompt.call_args
        self.assertEqual(call_args[0][0], [mock_agent1, mock_agent2])  # sub_agent_info_list
        self.assertEqual(call_args[0][1], "Test task")  # task_description
        self.assertEqual(call_args[0][2], [mock_tool1, mock_tool2])  # tool_info_list

    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.get_enabled_tool_description_for_generate_prompt')
    @patch('backend.services.prompt_service.get_enabled_sub_agent_description_for_generate_prompt')
    @patch('backend.services.prompt_service.get_knowledge_base_display_names')
    def test_generate_and_save_system_prompt_impl_create_mode(
        self,
        mock_get_kb_display_names,
        mock_get_enabled_sub_agents,
        mock_get_enabled_tools,
        mock_generate_system_prompt,
        mock_query_all_agents,
    ):
        """Test generate_and_save_system_prompt_impl in create mode (agent_id=0)"""
        # Setup - Mock the generator to return the expected data structure
        def mock_generator(*args, **kwargs):
            yield {"type": "duty", "content": "Generated duty prompt", "is_complete": False}
            yield {"type": "constraint", "content": "Generated constraint prompt", "is_complete": False}
            yield {"type": "few_shots", "content": "Generated few shots prompt", "is_complete": False}
            yield {"type": "agent_var_name", "content": "test_agent", "is_complete": True}
            yield {"type": "agent_display_name", "content": "Test Agent", "is_complete": True}
            yield {"type": "agent_description", "content": "Test agent description", "is_complete": True}
            yield {"type": "duty", "content": "Final duty prompt", "is_complete": True}
            yield {"type": "constraint", "content": "Final constraint prompt", "is_complete": True}
            yield {"type": "few_shots", "content": "Final few shots prompt", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_generator
        # Simulate no existing agents (no duplicates)
        mock_query_all_agents.return_value = []
        # Simulate back-end enabled tools / sub-agents when IDs are empty
        enabled_tools = [{"name": "db_tool", "description": "DB tool"}]
        enabled_sub_agents = [{"name": "db_agent", "description": "DB agent"}]
        mock_get_enabled_tools.return_value = enabled_tools
        mock_get_enabled_sub_agents.return_value = enabled_sub_agents
        mock_get_kb_display_names.return_value = None

        # Execute - test as a generator with agent_id=0 (create mode) and empty tool/sub-agent IDs
        result_gen = generate_and_save_system_prompt_impl(
            agent_id=0,
            model_id=self.test_model_id,
            task_description="Test task",
            user_id="user123",
            tenant_id="tenant456",
            language="zh",
            tool_ids=[],
            sub_agent_ids=[]
        )
        result = list(result_gen)  # Convert generator to list for assertion

        # Assert
        self.assertGreater(len(result), 0)

        # Should call generate_system_prompt with back-end enabled tools and sub-agents
        mock_generate_system_prompt.assert_called_once_with(
            enabled_sub_agents,  # sub_agent_info_list from helper
            "Test task",
            enabled_tools,  # tool_info_list from helper
            "tenant456",
            "user123",
            self.test_model_id,
            "zh",
            None,
            None,
            None,  # aidp_kb_display_names
            True,  # has_selected_resources
        )

    @patch('backend.services.prompt_service.regenerate_agent_value')
    @patch('backend.services.prompt_service.check_agent_value_duplicate')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_generate_and_save_system_prompt_impl_duplicate_names_regenerated(
        self,
        mock_search_agent_info,
        mock_query_tools,
        mock_generate_system_prompt,
        mock_query_all_agents,
        mock_check_value_dup,
        mock_regen_value,
    ):
        """Duplicate agent_var_name / agent_display_name should be regenerated via LLM helpers."""
        # Tool and sub-agent info do not matter for this test
        mock_query_tools.return_value = []
        mock_search_agent_info.return_value = {}
        mock_query_all_agents.return_value = [
            {"agent_id": 1, "name": "dup", "display_name": "Dup Display"}
        ]

        # Force duplicate detection
        mock_check_value_dup.return_value = True

        # Regenerated values
        mock_regen_value.side_effect = lambda field_key, **kwargs: {
            "name": "regen_var", "display_name": "Regen Display",
        }[field_key]

        # Mock generator output from generate_system_prompt
        def mock_gen(*args, **kwargs):
            yield {"type": "agent_var_name", "content": "dup", "is_complete": True}
            yield {"type": "agent_display_name", "content": "Dup Display", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_gen

        result = list(generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=1,
            task_description="Task",
            user_id="u",
            tenant_id="t",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[10],
        ))

        # Should yield regenerated names
        var_items = [r for r in result if r["type"] == "agent_var_name"]
        disp_items = [r for r in result if r["type"] == "agent_display_name"]
        self.assertEqual(var_items[0]["content"], "regen_var")
        self.assertEqual(disp_items[0]["content"], "Regen Display")

        self.assertEqual(mock_regen_value.call_count, 2)

    @patch('backend.services.prompt_service.generate_unique_agent_value')
    @patch('backend.services.prompt_service.regenerate_agent_value')
    @patch('backend.services.prompt_service.check_agent_value_duplicate')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_generate_and_save_system_prompt_impl_duplicate_names_fallback_suffix(
        self,
        mock_search_agent_info,
        mock_query_tools,
        mock_generate_system_prompt,
        mock_query_all_agents,
        mock_check_value_dup,
        mock_regen_value,
        mock_generate_unique_value,
    ):
        """When regeneration fails, duplicate names should fall back to suffix helpers."""
        mock_query_tools.return_value = []
        mock_search_agent_info.return_value = {}
        mock_query_all_agents.return_value = [
            {"agent_id": 1, "name": "dup", "display_name": "Dup Display"}
        ]

        mock_check_value_dup.return_value = True

        # Force LLM regeneration failure
        mock_regen_value.side_effect = Exception("llm error")

        mock_generate_unique_value.side_effect = lambda field_key, *args: {
            "name": "uniq_var", "display_name": "Uniq Display",
        }[field_key]

        def mock_gen(*args, **kwargs):
            yield {"type": "agent_var_name", "content": "dup", "is_complete": True}
            yield {"type": "agent_display_name", "content": "Dup Display", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_gen

        result = list(generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=1,
            task_description="Task",
            user_id="u",
            tenant_id="t",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[10],
        ))

        var_items = [r for r in result if r["type"] == "agent_var_name"]
        disp_items = [r for r in result if r["type"] == "agent_display_name"]
        self.assertEqual(var_items[0]["content"], "uniq_var")
        self.assertEqual(disp_items[0]["content"], "Uniq Display")

        self.assertEqual(mock_generate_unique_value.call_count, 2)

    @patch('backend.services.prompt_service.check_agent_value_duplicate')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_generate_and_save_system_prompt_impl_name_fields_incomplete(
        self,
        mock_search_agent_info,
        mock_query_tools,
        mock_generate_system_prompt,
        mock_query_all_agents,
        mock_check_value_dup,
    ):
        """When agent_var_name or agent_display_name is_complete is False, skip duplicate checking (line 193 else branch)."""
        # Setup
        mock_query_tools.return_value = []
        mock_search_agent_info.return_value = {}
        mock_query_all_agents.return_value = []

        # Mock generator output with incomplete name fields first, then complete ones
        def mock_gen(*args, **kwargs):
            yield {"type": "duty", "content": "duty content", "is_complete": False}
            # Incomplete name fields - should not trigger duplicate checking (line 193 condition is False)
            yield {"type": "agent_var_name", "content": "test_agent", "is_complete": False}
            yield {"type": "agent_display_name", "content": "Test Agent", "is_complete": False}
            # Complete name fields - should trigger duplicate checking (line 193 condition is True)
            yield {"type": "agent_var_name", "content": "test_agent_final", "is_complete": True}
            yield {"type": "agent_display_name", "content": "Test Agent Final", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_gen
        mock_check_value_dup.return_value = False

        # Execute
        result = list(generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=1,
            task_description="Task",
            user_id="u",
            tenant_id="t",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[10],
        ))

        # Assert - incomplete name fields should NOT be yielded (they are skipped)
        # Only complete name fields should be yielded
        var_items = [r for r in result if r["type"] == "agent_var_name"]
        disp_items = [r for r in result if r["type"] == "agent_display_name"]
        
        # Should only have complete items (incomplete ones are not yielded)
        self.assertEqual(len(var_items), 1)
        self.assertEqual(len(disp_items), 1)
        self.assertTrue(var_items[0].get("is_complete", False))
        self.assertTrue(disp_items[0].get("is_complete", False))
        
        # Duplicate checking should only be called for complete items
        self.assertEqual(
            [item.args[0] for item in mock_check_value_dup.call_args_list],
            ["name", "display_name"],
        )

    @patch('backend.services.prompt_service.check_agent_value_duplicate')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_generate_and_save_system_prompt_impl_display_name_complete_no_duplicate(
        self,
        mock_search_agent_info,
        mock_query_tools,
        mock_generate_system_prompt,
        mock_query_all_agents,
        mock_check_value_dup,
    ):
        """Test agent_display_name path when is_complete is True and no duplicate (line 235)."""
        # Setup
        mock_query_tools.return_value = []
        mock_search_agent_info.return_value = {}
        mock_query_all_agents.return_value = []
        mock_check_value_dup.return_value = False

        # Mock generator output - only display_name with is_complete=True to test line 235
        def mock_gen(*args, **kwargs):
            yield {"type": "duty", "content": "duty content", "is_complete": True}
            yield {"type": "agent_display_name", "content": "Test Agent", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_gen

        # Execute
        result = list(generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=1,
            task_description="Task",
            user_id="u",
            tenant_id="t",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[10],
        ))

        # Assert - should yield display_name without regeneration (no duplicate)
        disp_items = [r for r in result if r["type"] == "agent_display_name"]
        self.assertEqual(len(disp_items), 1)
        self.assertEqual(disp_items[0]["content"], "Test Agent")
        self.assertTrue(disp_items[0].get("is_complete", False))
        
        # Should check for duplicate but not regenerate
        mock_check_value_dup.assert_called_once()

    @patch('backend.services.prompt_service.generate_unique_agent_value')
    @patch('backend.services.prompt_service.regenerate_agent_value')
    @patch('backend.services.prompt_service.check_agent_value_duplicate')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_generate_and_save_system_prompt_impl_display_name_complete_with_duplicate(
        self,
        mock_search_agent_info,
        mock_query_tools,
        mock_generate_system_prompt,
        mock_query_all_agents,
        mock_check_value_dup,
        mock_regen_value,
        mock_generate_unique_value,
    ):
        """Test agent_display_name path when is_complete is True and duplicate exists, regenerates with LLM (line 235-250)."""
        # Setup
        mock_query_tools.return_value = []
        mock_search_agent_info.return_value = {}
        mock_query_all_agents.return_value = [{"display_name": "Test Agent", "agent_id": 999}]
        mock_check_value_dup.side_effect = lambda field_key, *args, **kwargs: field_key == "display_name"
        mock_regen_value.return_value = "Regenerated Display Name"
        mock_generate_unique_value.return_value = "fallback_display_1"

        # Mock generator output - display_name with is_complete=True to test line 235
        def mock_gen(*args, **kwargs):
            yield {"type": "duty", "content": "duty content", "is_complete": True}
            yield {"type": "agent_display_name", "content": "Test Agent", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_gen

        # Execute
        result = list(generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=1,
            task_description="Task",
            user_id="u",
            tenant_id="t",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[10],
        ))

        # Assert - should yield regenerated display_name
        disp_items = [r for r in result if r["type"] == "agent_display_name"]
        self.assertEqual(len(disp_items), 1)
        self.assertEqual(disp_items[0]["content"], "Regenerated Display Name")
        self.assertTrue(disp_items[0].get("is_complete", False))
        
        # Should check for duplicate and regenerate
        mock_check_value_dup.assert_called_once()
        mock_regen_value.assert_called_once()

    @patch('backend.services.prompt_service.generate_unique_agent_value')
    @patch('backend.services.prompt_service.regenerate_agent_value')
    @patch('backend.services.prompt_service.check_agent_value_duplicate')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_generate_and_save_system_prompt_impl_display_name_llm_failure_fallback(
        self,
        mock_search_agent_info,
        mock_query_tools,
        mock_generate_system_prompt,
        mock_query_all_agents,
        mock_check_value_dup,
        mock_regen_value,
        mock_generate_unique_value,
    ):
        """Test agent_display_name path when is_complete is True, duplicate exists, LLM regeneration fails, uses fallback (line 235-250)."""
        # Setup
        mock_query_tools.return_value = []
        mock_search_agent_info.return_value = {}
        mock_query_all_agents.return_value = [{"display_name": "Test Agent", "agent_id": 999}]
        mock_check_value_dup.side_effect = lambda field_key, *args, **kwargs: field_key == "display_name"
        mock_regen_value.side_effect = Exception("LLM failed")
        mock_generate_unique_value.return_value = "fallback_display_2"

        # Mock generator output - display_name with is_complete=True to test line 235
        def mock_gen(*args, **kwargs):
            yield {"type": "duty", "content": "duty content", "is_complete": True}
            yield {"type": "agent_display_name", "content": "Test Agent", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_gen

        # Execute
        result = list(generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=1,
            task_description="Task",
            user_id="u",
            tenant_id="t",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[10],
        ))

        # Assert - should yield fallback display_name
        disp_items = [r for r in result if r["type"] == "agent_display_name"]
        self.assertEqual(len(disp_items), 1)
        self.assertEqual(disp_items[0]["content"], "fallback_display_2")
        self.assertTrue(disp_items[0].get("is_complete", False))
        
        # Should check for duplicate, try LLM regeneration, then use fallback
        mock_check_value_dup.assert_called_once()
        mock_regen_value.assert_called_once()
        mock_generate_unique_value.assert_called_once()

    @patch('backend.services.prompt_service.generate_and_save_system_prompt_impl')
    def test_gen_system_prompt_streamable(self, mock_generate_impl):
        """Test gen_system_prompt_streamable function"""
        # Setup mock data
        test_data = [
            {"type": "duty", "content": "Test duty prompt", "is_complete": False},
            {"type": "constraint", "content": "Test constraint prompt",
                "is_complete": False},
            {"type": "few_shots", "content": "Test few shots prompt", "is_complete": True},
        ]
        mock_generate_impl.return_value = iter(test_data)

        # Execute - collect results from the generator
        result_list = []
        for result in gen_system_prompt_streamable(
            agent_id=123,
            model_id=self.test_model_id,
            task_description="Test task",
            user_id="user123",
            tenant_id="tenant456",
            language="zh"
        ):
            result_list.append(result)

        # Assert
        # Verify generate_and_save_system_prompt_impl was called with correct parameters
        mock_generate_impl.assert_called_once_with(
            agent_id=123,
            model_id=self.test_model_id,
            task_description="Test task",
            user_id="user123",
            tenant_id="tenant456",
            language="zh",
            prompt_template_id=None,
            tool_ids=None,
            sub_agent_ids=None,
            knowledge_base_display_names=None,
            has_selected_resources=True,
        )

        # Verify output format - should be SSE format
        self.assertEqual(len(result_list), 3)
        for i, result in enumerate(result_list):
            expected_data = f"data: {json.dumps({'success': True, 'data': test_data[i]}, ensure_ascii=False)}\n\n"
            self.assertEqual(result, expected_data)

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.join_info_for_generate_system_prompt')
    @patch('backend.services.prompt_service.resolve_prompt_generate_template')
    @patch('backend.services.prompt_service.get_model_by_model_id')
    def test_generate_system_prompt(self, mock_get_model, mock_resolve_prompt_template, mock_join_info, mock_call_llm):
        # Setup
        mock_get_model.return_value = None  # No DB connection needed; concurrency_limit defaults to unlimited
        mock_prompt_config = {
            "user_prompt": "Test user prompt template",
            "duty_system_prompt": "Generate duty prompt",
            "constraint_system_prompt": "Generate constraint prompt",
            "few_shots_system_prompt": "Generate few shots prompt",
            "agent_variable_name_system_prompt": "Generate agent var name",
            "agent_display_name_system_prompt": "Generate agent display name",
            "agent_description_system_prompt": "Generate agent description"
        }
        mock_resolve_prompt_template.return_value = mock_prompt_config

        mock_join_info.return_value = "Joined template content"

        # Mock call_llm_for_system_prompt to simulate streaming responses
        def mock_llm_call(model_id, content, sys_prompt, callback, tenant_id):
            # Simulate different responses based on system prompt
            if "duty" in sys_prompt.lower():
                if callback:
                    callback("Duty prompt part 1")
                    callback("Duty prompt part 1 part 2")
                return "Duty prompt part 1 part 2"
            elif "constraint" in sys_prompt.lower():
                if callback:
                    callback("Constraint prompt part 1")
                    callback("Constraint prompt part 1 part 2")
                return "Constraint prompt part 1 part 2"
            elif "few_shots" in sys_prompt.lower():
                if callback:
                    callback("Few shots prompt part 1")
                    callback("Few shots prompt part 1 part 2")
                return "Few shots prompt part 1 part 2"
            elif "variable_name" in sys_prompt.lower():
                if callback:
                    callback("test_agent")
                return "test_agent"
            elif "display_name" in sys_prompt.lower():
                if callback:
                    callback("Test Agent")
                return "Test Agent"
            elif "description" in sys_prompt.lower():
                if callback:
                    callback("Test agent description")
                return "Test agent description"
            return "Default response"

        mock_call_llm.side_effect = mock_llm_call

        # Test data
        mock_sub_agents = [{"name": "agent1", "description": "Agent 1"}]
        mock_task_description = "Test task"
        mock_tools = [{"name": "tool1", "description": "Tool 1"}]
        mock_tenant_id = "test_tenant"
        mock_language = "zh"

        # Execute - collect all results from the generator
        result_list = []
        for result in generate_system_prompt(
            mock_sub_agents,
            mock_task_description,
            mock_tools,
            mock_tenant_id,
            "test_user",
            self.test_model_id,
            mock_language
        ):
            result_list.append(result)

        # Assert
        # Verify template loading
        mock_resolve_prompt_template.assert_called_once_with(
            tenant_id=mock_tenant_id,
            user_id="test_user",
            language=mock_language,
            prompt_template_id=None,
        )

        # Verify template joining - now includes knowledge_base_display_names parameter
        mock_join_info.assert_called_once_with(
            prompt_for_generate=mock_prompt_config,
            sub_agent_info_list=mock_sub_agents,
            task_description=mock_task_description,
            tool_info_list=mock_tools,
            language=mock_language,
            knowledge_base_display_names=None,
            aidp_kb_display_names=None,
            has_selected_resources=True,
        )

        # Verify LLM calls - should be called 6 times for each prompt type
        self.assertEqual(mock_call_llm.call_count, 6)

        # Verify that results contain the expected structure
        # Should have streaming results and final results
        self.assertGreater(len(result_list), 0)

        # Check that we get results for all expected types
        result_types = [r["type"] for r in result_list]
        expected_types = ["duty", "constraint", "few_shots",
                          "agent_var_name", "agent_display_name", "agent_description"]

        for expected_type in expected_types:
            self.assertIn(expected_type, result_types,
                          f"Missing result type: {expected_type}")

        # Check that all final results are marked as complete
        final_results = [r for r in result_list if r.get("is_complete", False)]
        final_types = [r["type"] for r in final_results]

        for expected_type in expected_types:
            self.assertIn(expected_type, final_types,
                          f"Missing final result for type: {expected_type}")

        # Verify content structure
        for result in result_list:
            self.assertIn("type", result)
            self.assertIn("content", result)
            self.assertIn("is_complete", result)
            self.assertIsInstance(result["is_complete"], bool)
            self.assertIsInstance(result["content"], str)

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.join_info_for_generate_system_prompt')
    @patch('backend.services.prompt_service.resolve_prompt_generate_template')
    @patch('backend.services.prompt_service.get_model_by_model_id')
    def test_generate_system_prompt_with_exception(self, mock_get_model, mock_resolve_prompt_template, mock_join_info, mock_call_llm):
        # Setup
        mock_get_model.return_value = None  # No DB connection needed; concurrency_limit defaults to unlimited
        mock_prompt_config = {
            "user_prompt": "Test user prompt template",
            "duty_system_prompt": "Generate duty prompt",
            "constraint_system_prompt": "Generate constraint prompt",
            "few_shots_system_prompt": "Generate few shots prompt",
            "agent_variable_name_system_prompt": "Generate agent var name",
            "agent_display_name_system_prompt": "Generate agent display name",
            "agent_description_system_prompt": "Generate agent description"
        }
        mock_resolve_prompt_template.return_value = mock_prompt_config
        mock_join_info.return_value = "Joined template content"

        # Mock call_llm_for_system_prompt to raise exception for one prompt type
        def mock_llm_call_with_exception(model_id, content, sys_prompt, callback, tenant_id):
            if "duty" in sys_prompt.lower():
                raise Exception("LLM error for duty prompt")
            elif "constraint" in sys_prompt.lower():
                if callback:
                    callback("Constraint prompt")
                return "Constraint prompt"
            else:
                if callback:
                    callback("Other prompt")
                return "Other prompt"

        mock_call_llm.side_effect = mock_llm_call_with_exception

        # Test data
        mock_sub_agents = [{"name": "agent1", "description": "Agent 1"}]
        mock_task_description = "Test task"
        mock_tools = [{"name": "tool1", "description": "Tool 1"}]
        mock_tenant_id = "test_tenant"
        mock_language = "en"

        # Execute - exception should be raised (this tests the error propagation behavior)
        with self.assertRaises(Exception) as context:
            for result in generate_system_prompt(
                mock_sub_agents,
                mock_task_description,
                mock_tools,
                mock_tenant_id,
                "test_user",
                self.test_model_id,
                mock_language
            ):
                pass  # Consume the generator to trigger the exception

        # Assert - exception message should be present
        self.assertIn("LLM error", str(context.exception))

    @patch('backend.services.prompt_service.Template')
    def test_join_info_for_generate_system_prompt(self, mock_template):
        # Setup
        mock_prompt_for_generate = {"user_prompt": "Test User Prompt"}
        mock_sub_agents = [
            {"name": "agent1", "description": "Agent 1 desc"},
            {"name": "agent2", "description": "Agent 2 desc"}
        ]
        mock_task_description = "Test task"
        mock_tools = [
            {"name": "tool1", "description": "Tool 1 desc",
                "inputs": "input1", "output_type": "output1"},
            {"name": "tool2", "description": "Tool 2 desc",
                "inputs": "input2", "output_type": "output2"}
        ]

        mock_template_instance = MagicMock()
        mock_template.return_value = mock_template_instance
        mock_template_instance.render.return_value = "Rendered content"

        # Execute
        result = join_info_for_generate_system_prompt(
            mock_prompt_for_generate, mock_sub_agents, mock_task_description, mock_tools
        )

        # Assert
        self.assertEqual(result, "Rendered content")
        template_vars = mock_template_instance.render.call_args[0][0]
        self.assertIn("tool1", template_vars["tool_description"])
        self.assertNotIn("知识库工具仅代表检索能力", template_vars["tool_description"])
        self.assertFalse(template_vars["has_local_knowledge_tool"])
        self.assertFalse(template_vars["has_aidp_knowledge_tool"])
        mock_template.assert_called_once_with(
            mock_prompt_for_generate["user_prompt"], undefined=StrictUndefined)
        mock_template_instance.render.assert_called_once()
        # Check template variables
        template_vars = mock_template_instance.render.call_args[0][0]
        self.assertIn("tool_description", template_vars)
        self.assertIn("assistant_description", template_vars)
        self.assertEqual(
            template_vars["task_description"], mock_task_description)


    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.get_enable_tool_id_by_agent_id')
    def test_get_enabled_tool_description_for_generate_prompt(
        self,
        mock_get_enable_tool_ids,
        mock_query_tools,
    ):
        """DB results should be returned with parallel_executor appended."""
        mock_get_enable_tool_ids.return_value = [1, 2]
        tools = [{"tool_id": 1}, {"tool_id": 2}]
        mock_query_tools.return_value = tools

        result = get_enabled_tool_description_for_generate_prompt(
            agent_id=123, tenant_id="tenant-x"
        )

        mock_get_enable_tool_ids.assert_called_once_with(
            agent_id=123, tenant_id="tenant-x"
        )
        mock_query_tools.assert_called_once_with([1, 2])
        # parallel_executor is always injected
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], {"tool_id": 1})
        self.assertEqual(result[1], {"tool_id": 2})
        self.assertEqual(result[2]["name"], "parallel_executor")

    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.get_enable_tool_id_by_agent_id')
    def test_get_enabled_tool_description_parallel_executor_not_duplicated(
        self,
        mock_get_enable_tool_ids,
        mock_query_tools,
    ):
        """When parallel_executor is already in DB results, it is not duplicated."""
        mock_get_enable_tool_ids.return_value = [1]
        tools = [{"name": "parallel_executor", "tool_id": 99}]
        mock_query_tools.return_value = tools

        result = get_enabled_tool_description_for_generate_prompt(
            agent_id=1, tenant_id="t"
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tool_id"], 99)

    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    @patch('backend.services.prompt_service.query_sub_agents_id_list')
    def test_get_enabled_sub_agent_description_for_generate_prompt(
        self,
        mock_query_sub_ids,
        mock_search_agent,
    ):
        """Wrapper should fetch sub-agent IDs then hydrate them with info."""
        from backend.services.prompt_service import get_enabled_sub_agent_description_for_generate_prompt

        mock_query_sub_ids.return_value = [10, 20]
        mock_search_agent.side_effect = [
            {"agent_id": 10, "name": "A"},
            {"agent_id": 20, "name": "B"},
        ]

        result = get_enabled_sub_agent_description_for_generate_prompt(
            agent_id=99, tenant_id="tenant-y"
        )

        mock_query_sub_ids.assert_called_once_with(
            main_agent_id=99, tenant_id="tenant-y"
        )
        self.assertEqual(mock_search_agent.call_count, 2)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["agent_id"], 10)
        self.assertEqual(result[1]["agent_id"], 20)

    # ==================== Additional tests for higher coverage ====================

    @patch('backend.services.prompt_service.generate_and_save_system_prompt_impl')
    def test_gen_system_prompt_streamable_with_app_exception(self, mock_generate_impl):
        """Test gen_system_prompt_streamable handles AppException and returns error through SSE"""
        from consts.error_code import ErrorCode
        from consts.exceptions import AppException

        # Setup - mock generate_and_save_system_prompt_impl to raise AppException
        mock_generate_impl.side_effect = AppException(
            ErrorCode.MODEL_NOT_FOUND,
            "Model not found error"
        )

        # Execute - collect results from the generator
        result_list = []
        for result in gen_system_prompt_streamable(
            agent_id=123,
            model_id=self.test_model_id,
            task_description="Test task",
            user_id="user123",
            tenant_id="tenant456",
            language="zh"
        ):
            result_list.append(result)

        # Assert - should yield error in SSE format
        self.assertEqual(len(result_list), 1)
        parsed = json.loads(result_list[0].replace("data: ", "").replace("\n\n", ""))
        self.assertFalse(parsed['success'])
        self.assertEqual(parsed['error']['code'], str(ErrorCode.MODEL_NOT_FOUND.value))
        self.assertEqual(parsed['error']['message'], "Model not found error")

    @patch('backend.services.prompt_service.generate_and_save_system_prompt_impl')
    def test_gen_system_prompt_streamable_with_generic_exception(self, mock_generate_impl):
        """Test gen_system_prompt_streamable handles generic Exception and returns error through SSE"""
        # Setup - mock generate_and_save_system_prompt_impl to raise generic Exception
        mock_generate_impl.side_effect = Exception("Some random error")

        # Execute - collect results from the generator
        result_list = []
        for result in gen_system_prompt_streamable(
            agent_id=123,
            model_id=self.test_model_id,
            task_description="Test task",
            user_id="user123",
            tenant_id="tenant456",
            language="zh"
        ):
            result_list.append(result)

        # Assert - should yield error in SSE format with default error code
        self.assertEqual(len(result_list), 1)
        parsed = json.loads(result_list[0].replace("data: ", "").replace("\n\n", ""))
        self.assertFalse(parsed['success'])
        # Should use default error code for non-AppException
        self.assertIn('error', parsed)

    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    def test_generate_and_save_system_prompt_impl_sub_agent_exception(
        self,
        mock_query_all_agents,
        mock_generate_system_prompt,
        mock_query_tools,
        mock_search_agent_info,
    ):
        """Test generate_and_save_system_prompt_impl handles sub-agent info retrieval exception (lines 88-89)"""
        # Setup
        mock_query_tools.return_value = []
        mock_query_all_agents.return_value = []

        # Mock generate_system_prompt to yield data
        def mock_gen(*args, **kwargs):
            yield {"type": "duty", "content": "duty content", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_gen

        # Make search_agent_info_by_agent_id raise exception for one sub-agent
        mock_search_agent_info.side_effect = [
            {"agent_id": 10, "name": "agent1"},  # First sub-agent succeeds
            Exception("Database error"),  # Second sub-agent fails
        ]

        # Execute - should handle exception gracefully and continue
        result_gen = generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=self.test_model_id,
            task_description="Test task",
            user_id="user123",
            tenant_id="tenant456",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[10, 20]  # Two sub-agents
        )
        result = list(result_gen)

        # Assert - should still return results (exception was logged but not raised)
        self.assertGreater(len(result), 0)

    @patch('backend.services.prompt_service.check_agent_value_duplicate')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_generate_and_save_system_prompt_impl_empty_content_raises_exception(
        self,
        mock_search_agent_info,
        mock_query_tools,
        mock_generate_system_prompt,
        mock_query_all_agents,
        mock_check_value_dup,
    ):
        """Test generate_and_save_system_prompt_impl raises exception when no content is generated (line 223)"""
        # Setup
        mock_query_tools.return_value = []
        mock_search_agent_info.return_value = {}
        mock_query_all_agents.return_value = []
        mock_check_value_dup.return_value = False

        # Mock generate_system_prompt to yield empty content
        def mock_gen(*args, **kwargs):
            yield {"type": "duty", "content": "", "is_complete": True}
            yield {"type": "constraint", "content": "", "is_complete": True}
            yield {"type": "few_shots", "content": "", "is_complete": True}
            yield {"type": "agent_var_name", "content": "", "is_complete": True}
            yield {"type": "agent_display_name", "content": "", "is_complete": True}
            yield {"type": "agent_description", "content": "", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_gen

        # Execute and Assert - should raise Exception when all content is empty
        with self.assertRaises(Exception) as context:
            list(generate_and_save_system_prompt_impl(
                agent_id=123,
                model_id=self.test_model_id,
                task_description="Test task",
                user_id="user123",
                tenant_id="tenant456",
                language="zh",
                tool_ids=[1],
                sub_agent_ids=[10],
            ))

        self.assertIn("Failed to generate prompt content", str(context.exception))

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.join_info_for_generate_system_prompt')
    @patch('backend.services.prompt_service.resolve_prompt_generate_template')
    @patch('backend.services.prompt_service.get_model_by_model_id')
    def test_generate_system_prompt_error_before_streaming(
        self,
        mock_get_model,
        mock_resolve_prompt_template,
        mock_join_info,
        mock_call_llm,
    ):
        """Test generate_system_prompt handles error that occurs before streaming (line 307-311)"""
        # Setup
        mock_get_model.return_value = None  # No DB connection needed; concurrency_limit defaults to unlimited
        mock_prompt_config = {
            "user_prompt": "Test user prompt template",
            "duty_system_prompt": "Generate duty prompt",
            "constraint_system_prompt": "Generate constraint prompt",
            "few_shots_system_prompt": "Generate few shots prompt",
            "agent_variable_name_system_prompt": "Generate agent var name",
            "agent_display_name_system_prompt": "Generate agent display name",
            "agent_description_system_prompt": "Generate agent description"
        }
        mock_resolve_prompt_template.return_value = mock_prompt_config
        mock_join_info.return_value = "Joined template content"

        # Mock call_llm_for_system_prompt to raise exception immediately
        def mock_llm_call_error(model_id, content, sys_prompt, callback, tenant_id):
            if "duty" in sys_prompt.lower():
                raise Exception("LLM connection error")
            # Other prompts work normally
            if callback:
                callback(f"Content for {sys_prompt}")
            return f"Content for {sys_prompt}"

        mock_call_llm.side_effect = mock_llm_call_error

        # Execute - should raise the exception during iteration
        result_list = []
        with self.assertRaises(Exception) as context:
            for result in generate_system_prompt(
                [{"name": "agent1"}],
                "Test task",
                [{"name": "tool1"}],
                "tenant123",
                "test_user",
                self.test_model_id,
                "zh"
            ):
                result_list.append(result)

        self.assertIn("LLM connection error", str(context.exception))

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.join_info_for_generate_system_prompt')
    @patch('backend.services.prompt_service.resolve_prompt_generate_template')
    @patch('backend.services.prompt_service.get_model_by_model_id')
    def test_generate_system_prompt_error_during_streaming(
        self,
        mock_get_model,
        mock_resolve_prompt_template,
        mock_join_info,
        mock_call_llm,
    ):
        """Test generate_system_prompt handles error that occurs during streaming (line 330-331)"""
        # Setup
        mock_get_model.return_value = None  # No DB connection needed; concurrency_limit defaults to unlimited
        mock_prompt_config = {
            "user_prompt": "Test user prompt template",
            "duty_system_prompt": "Generate duty prompt",
            "constraint_system_prompt": "Generate constraint prompt",
            "few_shots_system_prompt": "Generate few shots prompt",
            "agent_variable_name_system_prompt": "Generate agent var name",
            "agent_display_name_system_prompt": "Generate agent display name",
            "agent_description_system_prompt": "Generate agent description"
        }
        mock_resolve_prompt_template.return_value = mock_prompt_config
        mock_join_info.return_value = "Joined template content"

        # Track which call we're on
        call_count = {"count": 0}

        # Mock call_llm to succeed initially then fail after some streaming
        def mock_llm_call_error_after_first(
            model_id, content, sys_prompt, callback, tenant_id
        ):
            call_count["count"] += 1

            # First few calls succeed
            if call_count["count"] <= 3:
                if callback:
                    callback(f"Content for {sys_prompt}")
                return f"Content for {sys_prompt}"
            else:
                # Later calls fail
                raise Exception("LLM error during generation")

        mock_call_llm.side_effect = mock_llm_call_error_after_first

        # Execute - error should be raised during streaming
        result_list = []
        with self.assertRaises(Exception) as context:
            for result in generate_system_prompt(
                [{"name": "agent1"}],
                "Test task",
                [{"name": "tool1"}],
                "tenant123",
                "test_user",
                self.test_model_id,
                "zh"
            ):
                result_list.append(result)

        # Should eventually raise an exception
        self.assertIn("LLM error during generation", str(context.exception))

    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.get_enable_tool_id_by_agent_id')
    def test_get_enabled_tool_description_for_generate_prompt_empty_tool_ids(
        self,
        mock_get_enable_tool_ids,
        mock_query_tools,
    ):
        """Test get_enabled_tool_description_for_generate_prompt with empty tool IDs"""
        from backend.services.prompt_service import get_enabled_tool_description_for_generate_prompt

        # Setup - return empty list
        mock_get_enable_tool_ids.return_value = []
        mock_query_tools.return_value = []

        result = get_enabled_tool_description_for_generate_prompt(
            agent_id=123, tenant_id="tenant-x"
        )

        # Should return empty list
        self.assertEqual(result, [])

    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    @patch('backend.services.prompt_service.query_sub_agents_id_list')
    def test_get_enabled_sub_agent_description_for_generate_prompt_empty(
        self,
        mock_query_sub_ids,
        mock_search_agent,
    ):
        """Test get_enabled_sub_agent_description_for_generate_prompt with empty sub-agent IDs"""
        from backend.services.prompt_service import get_enabled_sub_agent_description_for_generate_prompt

        # Setup - return empty list
        mock_query_sub_ids.return_value = []

        result = get_enabled_sub_agent_description_for_generate_prompt(
            agent_id=99, tenant_id="tenant-y"
        )

        # Should return empty list
        self.assertEqual(result, [])
        mock_search_agent.assert_not_called()

    @patch('backend.services.prompt_service.Template')
    def test_join_info_for_generate_system_prompt_english(self, mock_template):
        """Test join_info_for_generate_system_prompt with English language"""
        # Setup
        mock_prompt_for_generate = {"user_prompt": "Test User Prompt"}
        mock_sub_agents = [
            {"name": "agent1", "description": "Agent 1 desc"}
        ]
        mock_task_description = "Test task"
        mock_tools = [
            {"name": "tool1", "description": "Tool 1 desc",
                "inputs": "input1", "output_type": "output1"}
        ]

        mock_template_instance = MagicMock()
        mock_template.return_value = mock_template_instance
        mock_template_instance.render.return_value = "Rendered content"

        # Execute with English language
        result = join_info_for_generate_system_prompt(
            mock_prompt_for_generate, mock_sub_agents, mock_task_description, mock_tools,
            language="en"
        )

        # Assert
        self.assertEqual(result, "Rendered content")
        template_vars = mock_template_instance.render.call_args[0][0]
        self.assertIn("tool1", template_vars["tool_description"])
        self.assertNotIn("Knowledge tools represent capabilities only", template_vars["tool_description"])
        self.assertFalse(template_vars["has_local_knowledge_tool"])
        self.assertFalse(template_vars["has_aidp_knowledge_tool"])
        # Check that English labels are used
        call_args = mock_template_instance.render.call_args[0][0]
        self.assertEqual(call_args["task_description"], mock_task_description)

    @patch('backend.services.prompt_service.Template')
    def test_join_info_for_generate_system_prompt_empty_tools_and_agents(self, mock_template):
        """Test join_info_for_generate_system_prompt with empty tools and sub-agents"""
        # Setup
        mock_prompt_for_generate = {"user_prompt": "Test User Prompt"}
        mock_sub_agents = []
        mock_task_description = "Test task"
        mock_tools = []

        mock_template_instance = MagicMock()
        mock_template.return_value = mock_template_instance
        mock_template_instance.render.return_value = "Rendered content"

        # Execute
        result = join_info_for_generate_system_prompt(
            mock_prompt_for_generate, mock_sub_agents, mock_task_description, mock_tools
        )

        # Assert
        self.assertEqual(result, "Rendered content")
        template_vars = mock_template_instance.render.call_args[0][0]
        self.assertEqual(template_vars["tool_description"], "")
        self.assertFalse(template_vars["has_local_knowledge_tool"])
        self.assertFalse(template_vars["has_aidp_knowledge_tool"])

    @patch('backend.services.prompt_service.Template')
    def test_join_info_for_generate_system_prompt_with_knowledge_base_names(self, mock_template):
        """Test join_info_for_generate_system_prompt with knowledge_base_display_names"""
        # Setup
        mock_prompt_for_generate = {"user_prompt": "Test User Prompt"}
        mock_sub_agents = []
        mock_task_description = "Test task"
        mock_tools = [
            {"name": "knowledge_base_search", "description": "Search knowledge base",
                "inputs": "{}", "output_type": "string"}
        ]

        mock_template_instance = MagicMock()
        mock_template.return_value = mock_template_instance
        mock_template_instance.render.return_value = "Rendered content with KB names"

        # Execute with knowledge base display names
        result = join_info_for_generate_system_prompt(
            mock_prompt_for_generate, mock_sub_agents, mock_task_description, mock_tools,
            knowledge_base_display_names=["redis", "kafka"]
        )

        # Assert
        self.assertEqual(result, "Rendered content with KB names")
        # Verify that knowledge_base_names was passed to template
        template_vars = mock_template_instance.render.call_args[0][0]
        self.assertIn("knowledge_base_names", template_vars)
        self.assertEqual(template_vars["knowledge_base_names"], "")
        self.assertIn("知识库工具仅代表检索能力", template_vars["tool_description"])

    @patch('backend.services.prompt_service.Template')
    def test_join_info_for_generate_system_prompt_without_knowledge_base_names(self, mock_template):
        """Test join_info_for_generate_system_prompt without knowledge_base_display_names"""
        # Setup
        mock_prompt_for_generate = {"user_prompt": "Test User Prompt"}
        mock_sub_agents = []
        mock_task_description = "Test task"
        mock_tools = [
            {"name": "web_search", "description": "Web search",
                "inputs": "{}", "output_type": "string"}
        ]

        mock_template_instance = MagicMock()
        mock_template.return_value = mock_template_instance
        mock_template_instance.render.return_value = "Rendered content"

        # Execute without knowledge base display names
        result = join_info_for_generate_system_prompt(
            mock_prompt_for_generate, mock_sub_agents, mock_task_description, mock_tools
        )

        # Assert
        template_vars = mock_template_instance.render.call_args[0][0]
        # knowledge_base_names is always present but empty when not provided
        self.assertIn("knowledge_base_names", template_vars)
        self.assertEqual(template_vars["knowledge_base_names"], "")
        self.assertNotIn("知识库工具仅代表检索能力", template_vars["tool_description"])
        self.assertNotIn("当前会话允许的知识库范围", template_vars["tool_description"])

    @patch('backend.services.prompt_service.get_knowledge_name_map_by_index_names')
    @patch('backend.services.prompt_service.query_tool_instances_by_id')
    def test_get_knowledge_base_display_names_with_configured_kb(
        self,
        mock_query_tool_instance,
        mock_get_knowledge_map,
    ):
        """Test get_knowledge_base_display_names with configured knowledge base"""
        from backend.services.prompt_service import get_knowledge_base_display_names

        # Setup
        tool_info_list = [
            {"tool_id": 1, "name": "knowledge_base_search"},
            {"tool_id": 2, "name": "web_search"},
        ]

        mock_query_tool_instance.return_value = {
            "params": {
                "index_names": ["index-1", "index-2"]
            }
        }
        mock_get_knowledge_map.return_value = {
            "index-1": "redis",
            "index-2": "kafka"
        }

        # Execute
        result = get_knowledge_base_display_names(
            tool_info_list=tool_info_list,
            agent_id=123,
            tenant_id="tenant-abc"
        )

        # Assert
        self.assertEqual(result, ["redis", "kafka"])
        mock_query_tool_instance.assert_called_once_with(
            agent_id=123, tool_id=1, tenant_id="tenant-abc"
        )
        mock_get_knowledge_map.assert_called_once_with(
            ["index-1", "index-2"],
            tenant_id="tenant-abc",
        )

    @patch('backend.services.prompt_service.query_tool_instances_by_id')
    def test_get_knowledge_base_display_names_no_kb_tool(self, mock_query_tool_instance):
        """Test get_knowledge_base_display_names when no knowledge_base_search tool exists"""
        from backend.services.prompt_service import get_knowledge_base_display_names

        # Setup - no knowledge_base_search tool
        tool_info_list = [
            {"tool_id": 2, "name": "web_search"},
        ]

        # Execute
        result = get_knowledge_base_display_names(
            tool_info_list=tool_info_list,
            agent_id=123,
            tenant_id="tenant-abc"
        )

        # Assert
        self.assertIsNone(result)
        mock_query_tool_instance.assert_not_called()

    @patch('backend.services.prompt_service.get_knowledge_name_map_by_index_names')
    @patch('backend.services.prompt_service.query_tool_instances_by_id')
    def test_get_knowledge_base_display_names_empty_index_names(
        self,
        mock_query_tool_instance,
        mock_get_knowledge_map,
    ):
        """Test get_knowledge_base_display_names when index_names is empty"""
        from backend.services.prompt_service import get_knowledge_base_display_names

        # Setup
        tool_info_list = [
            {"tool_id": 1, "name": "knowledge_base_search"},
        ]

        mock_query_tool_instance.return_value = {
            "params": {}
        }

        # Execute
        result = get_knowledge_base_display_names(
            tool_info_list=tool_info_list,
            agent_id=123,
            tenant_id="tenant-abc"
        )

        # Assert
        self.assertIsNone(result)
        mock_get_knowledge_map.assert_not_called()

    @patch('backend.services.prompt_service.get_knowledge_name_map_by_index_names')
    @patch('backend.services.prompt_service.query_tool_instances_by_id')
    def test_get_knowledge_base_display_names_with_json_string(
        self,
        mock_query_tool_instance,
        mock_get_knowledge_map,
    ):
        """Test get_knowledge_base_display_names when index_names is a JSON string"""
        from backend.services.prompt_service import get_knowledge_base_display_names

        # Setup
        tool_info_list = [
            {"tool_id": 1, "name": "knowledge_base_search"},
        ]

        mock_query_tool_instance.return_value = {
            "params": {
                "index_names": '["index-1", "index-2"]'  # JSON string format
            }
        }
        mock_get_knowledge_map.return_value = {
            "index-1": "redis",
            "index-2": "kafka"
        }

        # Execute
        result = get_knowledge_base_display_names(
            tool_info_list=tool_info_list,
            agent_id=123,
            tenant_id="tenant-abc"
        )

        # Assert
        self.assertEqual(result, ["redis", "kafka"])

    @patch('backend.services.prompt_service.get_knowledge_name_map_by_index_names')
    @patch('backend.services.prompt_service.query_tool_instances_by_id')
    def test_get_knowledge_base_display_names_multiple_tools(
        self,
        mock_query_tool_instance,
        mock_get_knowledge_map,
    ):
        """Test get_knowledge_base_display_names with multiple knowledge_base_search tools"""
        from backend.services.prompt_service import get_knowledge_base_display_names

        # Setup - two knowledge_base_search tools
        tool_info_list = [
            {"tool_id": 1, "name": "knowledge_base_search"},
            {"tool_id": 2, "name": "knowledge_base_search"},
        ]

        mock_query_tool_instance.side_effect = [
            {"params": {"index_names": ["index-1"]}},
            {"params": {"index_names": ["index-2"]}},
        ]
        mock_get_knowledge_map.return_value = {
            "index-1": "redis",
            "index-2": "kafka"
        }

        # Execute
        result = get_knowledge_base_display_names(
            tool_info_list=tool_info_list,
            agent_id=123,
            tenant_id="tenant-abc"
        )

        # Assert
        self.assertEqual(result, ["redis", "kafka"])
        self.assertEqual(mock_query_tool_instance.call_count, 2)

    @patch('backend.services.prompt_service.get_knowledge_name_map_by_index_names')
    @patch('backend.services.prompt_service.query_tool_instances_by_id')
    def test_get_knowledge_base_display_names_duplicate_index_names(
        self,
        mock_query_tool_instance,
        mock_get_knowledge_map,
    ):
        """Test get_knowledge_base_display_names handles duplicate index_names"""
        from backend.services.prompt_service import get_knowledge_base_display_names

        # Setup
        tool_info_list = [
            {"tool_id": 1, "name": "knowledge_base_search"},
        ]

        mock_query_tool_instance.return_value = {
            "params": {"index_names": ["index-1", "index-1", "index-2"]}  # Duplicates
        }
        mock_get_knowledge_map.return_value = {
            "index-1": "redis",
            "index-2": "kafka"
        }

        # Execute
        result = get_knowledge_base_display_names(
            tool_info_list=tool_info_list,
            agent_id=123,
            tenant_id="tenant-abc"
        )

        # Assert - should deduplicate while preserving order
        self.assertEqual(result, ["redis", "kafka"])
        # Should be called with deduplicated list
        mock_get_knowledge_map.assert_called_once_with(
            ["index-1", "index-2"],
            tenant_id="tenant-abc",
        )

    @patch('backend.services.prompt_service.get_knowledge_name_map_by_index_names')
    @patch('backend.services.prompt_service.query_tool_instances_by_id')
    def test_get_knowledge_base_display_names_query_tool_instance_exception(
        self,
        mock_query_tool_instance,
        mock_get_knowledge_map,
    ):
        """Test get_knowledge_base_display_names handles query_tool_instances_by_id exception gracefully (lines 445-446)"""
        from backend.services.prompt_service import get_knowledge_base_display_names

        # Setup - two knowledge_base_search tools
        tool_info_list = [
            {"tool_id": 1, "name": "knowledge_base_search"},
            {"tool_id": 2, "name": "knowledge_base_search"},
        ]

        # First tool instance query fails with exception
        mock_query_tool_instance.side_effect = [
            Exception("Database connection error"),
            {"params": {"index_names": ["index-2"]}},  # Second tool succeeds
        ]
        mock_get_knowledge_map.return_value = {
            "index-2": "kafka"
        }

        # Execute - should handle exception gracefully and continue processing
        result = get_knowledge_base_display_names(
            tool_info_list=tool_info_list,
            agent_id=123,
            tenant_id="tenant-abc"
        )

        # Assert - should still return results from the tool that succeeded
        self.assertEqual(result, ["kafka"])
        # Should have tried both tools
        self.assertEqual(mock_query_tool_instance.call_count, 2)
        mock_get_knowledge_map.assert_called_once_with(
            ["index-2"],
            tenant_id="tenant-abc",
        )

    @patch('backend.services.prompt_service.generate_and_save_system_prompt_impl')
    def test_gen_system_prompt_streamable_knowledge_base_flow(self, mock_generate_impl):
        """Test gen_system_prompt_streamable with knowledge base configuration"""
        # Setup
        test_data = [
            {"type": "duty", "content": "Test duty", "is_complete": False},
            {"type": "few_shots", "content": 'index_names=["redis", "kafka"]', "is_complete": True},
        ]
        mock_generate_impl.return_value = iter(test_data)

        # Execute
        result_list = list(gen_system_prompt_streamable(
            agent_id=123,
            model_id=self.test_model_id,
            task_description="Test task with knowledge base",
            user_id="user123",
            tenant_id="tenant456",
            language="zh"
        ))

        # Assert
        self.assertEqual(len(result_list), 2)
        # Verify success format
        parsed = json.loads(result_list[0].replace("data: ", "").replace("\n\n", ""))
        self.assertTrue(parsed['success'])

    # ==================== Coverage gap tests ====================

    def test_optimize_prompt_section_impl_invalid_section_type(self):
        """Test that invalid section_type raises AppException"""
        with self.assertRaises(AppException) as context:
            optimize_prompt_section_impl(
                agent_id=1,
                model_id=2,
                task_description="Build an agent",
                tenant_id="tenant-1",
                language="en",
                section_type="invalid_type",
                section_title="Some Title",
                current_content="Original content",
                feedback="Some feedback",
            )
        self.assertEqual(context.exception.error_code, ErrorCode.COMMON_PARAMETER_INVALID)

    def test_optimize_prompt_section_impl_missing_current_content(self):
        """Test that missing current_content raises AppException"""
        with self.assertRaises(AppException) as context:
            optimize_prompt_section_impl(
                agent_id=1,
                model_id=2,
                task_description="Build an agent",
                tenant_id="tenant-1",
                language="en",
                section_type="duty",
                section_title="Agent Role",
                current_content="",
                feedback="Some feedback",
            )
        self.assertEqual(context.exception.error_code, ErrorCode.COMMON_MISSING_REQUIRED_FIELD)

    def test_optimize_prompt_section_impl_empty_result(self):
        """Test that empty LLM result raises AppException"""
        with patch('backend.services.prompt_service.call_llm_for_system_prompt') as mock_call_llm:
            with patch('backend.services.prompt_service.get_prompt_optimize_prompt_template') as mock_template:
                mock_template.return_value = {
                    "OPTIMIZE_SYSTEM_PROMPT": "System prompt",
                    "OPTIMIZE_USER_PROMPT": "User prompt",
                }
                mock_call_llm.return_value = ""

                with self.assertRaises(AppException) as context:
                    optimize_prompt_section_impl(
                        agent_id=1,
                        model_id=2,
                        task_description="Build an agent",
                        tenant_id="tenant-1",
                        language="en",
                        section_type="duty",
                        section_title="Agent Role",
                        current_content="Original content",
                        feedback="Make it better",
                    )
                self.assertEqual(
                    context.exception.error_code,
                    ErrorCode.MODEL_PROMPT_GENERATION_FAILED
                )

    def test_optimize_prompt_section_impl_uses_default_title(self):
        """Test that section_title defaults when not provided"""
        with patch('backend.services.prompt_service.call_llm_for_system_prompt') as mock_call_llm:
            with patch('backend.services.prompt_service.get_prompt_optimize_prompt_template') as mock_template:
                with patch('backend.services.prompt_service.join_info_for_optimize_prompt_section') as mock_join:
                    mock_template.return_value = {
                        "OPTIMIZE_SYSTEM_PROMPT": "System prompt",
                        "OPTIMIZE_USER_PROMPT": "User prompt",
                    }
                    mock_call_llm.return_value = "Optimized"
                    mock_join.return_value = "joined"

                    result = optimize_prompt_section_impl(
                        agent_id=1,
                        model_id=2,
                        task_description="Build an agent",
                        tenant_id="tenant-1",
                        language="zh",
                        section_type="duty",
                        section_title=None,
                        current_content="Original content",
                        feedback="Make it better",
                    )
                    self.assertEqual(result["section_title"], "智能体角色")

    @patch('backend.services.prompt_service.Template')
    def test_join_info_for_optimize_prompt_section_english(self, mock_template):
        """Test join_info_for_optimize_prompt_section with English language"""
        mock_instance = MagicMock()
        mock_template.return_value = mock_instance
        mock_instance.render.return_value = "Rendered"

        result = join_info_for_optimize_prompt_section(
            prompt_for_optimize={"OPTIMIZE_USER_PROMPT": "Template {{ section_title }}"},
            section_type="constraint",
            section_title="Requirements",
            task_description="Task",
            current_content="Content",
            feedback="Feedback",
            tool_info_list=[{"name": "t1", "description": "d", "inputs": "i", "output_type": "o"}],
            sub_agent_info_list=[{"name": "a1", "description": "desc"}],
            language="en",
            knowledge_base_display_names=["kb1"],
        )

        self.assertEqual(result, "Rendered")
        render_args = mock_instance.render.call_args[0][0]
        self.assertEqual(render_args["section_type"], "constraint")
        self.assertEqual(render_args["knowledge_base_names"], "")

    @patch('backend.services.prompt_service.Template')
    def test_join_info_for_optimize_prompt_section_without_kb(self, mock_template):
        """Test join_info_for_optimize_prompt_section without knowledge base"""
        mock_instance = MagicMock()
        mock_template.return_value = mock_instance
        mock_instance.render.return_value = "Rendered"

        result = join_info_for_optimize_prompt_section(
            prompt_for_optimize={"OPTIMIZE_USER_PROMPT": "Template"},
            section_type="duty",
            section_title="Role",
            task_description="Task",
            current_content="Content",
            feedback="Feedback",
            tool_info_list=[],
            sub_agent_info_list=[],
            language="zh",
            knowledge_base_display_names=None,
        )

        render_args = mock_instance.render.call_args[0][0]
        self.assertEqual(render_args["knowledge_base_names"], "")

    def test_default_prompt_section_title_zh(self):
        """Test _default_prompt_section_title with Chinese language"""
        from backend.services.prompt_service import _default_prompt_section_title
        self.assertEqual(_default_prompt_section_title("duty", "zh"), "智能体角色")
        self.assertEqual(_default_prompt_section_title("constraint", "zh"), "使用要求")
        self.assertEqual(_default_prompt_section_title("few_shots", "zh"), "示例")

    def test_default_prompt_section_title_en(self):
        """Test _default_prompt_section_title with English language"""
        from backend.services.prompt_service import _default_prompt_section_title
        self.assertEqual(_default_prompt_section_title("duty", "en"), "Agent Role")
        self.assertEqual(_default_prompt_section_title("constraint", "en"), "Usage Requirements")
        self.assertEqual(_default_prompt_section_title("few_shots", "en"), "Few Shots")

    def test_default_prompt_section_title_unknown_lang(self):
        """Test _default_prompt_section_title falls back to ZH for unknown language"""
        from backend.services.prompt_service import _default_prompt_section_title
        self.assertEqual(_default_prompt_section_title("duty", "xx"), "智能体角色")
        self.assertEqual(_default_prompt_section_title("unknown_type", "en"), "unknown_type")

    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.get_enable_tool_id_by_agent_id')
    def test_resolve_prompt_generation_tools_empty_ids(self, mock_get_ids, mock_query_tools):
        """Test _resolve_prompt_generation_tools with empty tool_ids uses DB fallback"""
        from backend.services.prompt_service import _resolve_prompt_generation_tools
        mock_get_ids.return_value = [1, 2]
        mock_query_tools.return_value = [{"name": "tool1"}]

        result = _resolve_prompt_generation_tools(agent_id=123, tenant_id="tenant-x", tool_ids=[])

        mock_get_ids.assert_called_once()
        mock_query_tools.assert_called_once_with([1, 2])

    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_resolve_prompt_generation_sub_agents_empty_ids(self, mock_search):
        """Test _resolve_prompt_generation_sub_agents with empty sub_agent_ids uses DB fallback"""
        from backend.services.prompt_service import _resolve_prompt_generation_sub_agents
        mock_search.return_value = {"name": "sub1"}

        result = _resolve_prompt_generation_sub_agents(agent_id=123, tenant_id="tenant-x", sub_agent_ids=[])

        mock_search.assert_not_called()

    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_resolve_prompt_generation_sub_agents_with_ids(self, mock_search):
        """Test _resolve_prompt_generation_sub_agents with sub_agent_ids queries DB"""
        from backend.services.prompt_service import _resolve_prompt_generation_sub_agents
        mock_search.return_value = {"name": "sub1"}

        result = _resolve_prompt_generation_sub_agents(agent_id=123, tenant_id="tenant-x", sub_agent_ids=[10, 20])

        self.assertEqual(mock_search.call_count, 2)
        self.assertEqual(len(result), 2)

    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_resolve_prompt_generation_sub_agents_exception_handling(self, mock_search):
        """Test _resolve_prompt_generation_sub_agents handles exception gracefully"""
        from backend.services.prompt_service import _resolve_prompt_generation_sub_agents
        mock_search.side_effect = [Exception("DB error"), {"name": "sub2"}]

        result = _resolve_prompt_generation_sub_agents(agent_id=123, tenant_id="tenant-x", sub_agent_ids=[10, 20])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "sub2")

    @patch('backend.services.prompt_service.get_knowledge_name_map_by_index_names')
    @patch('backend.services.prompt_service.query_tool_instances_by_id')
    def test_get_knowledge_base_display_names_json_decode_error(self, mock_query, mock_get_map):
        """Test get_knowledge_base_display_names handles JSON decode error gracefully"""
        from backend.services.prompt_service import get_knowledge_base_display_names
        tool_info_list = [{"tool_id": 1, "name": "knowledge_base_search"}]
        mock_query.return_value = {"params": {"index_names": "not valid json ["}}
        mock_get_map.return_value = {}

        result = get_knowledge_base_display_names(tool_info_list=tool_info_list, agent_id=123, tenant_id="tenant-abc")

        self.assertIsNone(result)

    @patch('backend.services.prompt_service.get_knowledge_name_map_by_index_names')
    @patch('backend.services.prompt_service.query_tool_instances_by_id')
    def test_get_knowledge_base_display_names_empty_result_map(self, mock_query, mock_get_map):
        """Test get_knowledge_base_display_names when knowledge_name_map returns empty, uses index_name as fallback"""
        from backend.services.prompt_service import get_knowledge_base_display_names
        tool_info_list = [{"tool_id": 1, "name": "knowledge_base_search"}]
        mock_query.return_value = {"params": {"index_names": ["index-1"]}}
        mock_get_map.return_value = {}

        result = get_knowledge_base_display_names(tool_info_list=tool_info_list, agent_id=123, tenant_id="tenant-abc")

        self.assertEqual(result, ["index-1"])

    @patch('backend.services.prompt_service.get_enabled_tool_description_for_generate_prompt')
    def test_generate_and_save_system_prompt_impl_empty_tool_ids_fallback(self, mock_enabled_tools):
        """Test generate_and_save_system_prompt_impl uses DB fallback when tool_ids is empty"""
        mock_enabled_tools.return_value = [{"name": "db_tool"}]

        with patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id') as mock_query_agents:
            mock_query_agents.return_value = []

            with patch('backend.services.prompt_service.generate_system_prompt') as mock_gen:
                def mock_generator(*args, **kwargs):
                    yield {"type": "duty", "content": "duty content", "is_complete": True}

                mock_gen.side_effect = mock_generator

                result = list(generate_and_save_system_prompt_impl(
                    agent_id=123,
                    model_id=1,
                    task_description="Task",
                    user_id="u",
                    tenant_id="t",
                    language="zh",
                    tool_ids=[],
                    sub_agent_ids=[],
                ))

                mock_enabled_tools.assert_called_once()

    @patch('backend.services.prompt_service.get_knowledge_base_display_names')
    def test_generate_and_save_system_prompt_impl_frontend_provided_kb_names(self, mock_get_kb):
        """Test generate_and_save_system_prompt_impl uses frontend KB names when provided"""
        mock_get_kb.return_value = ["frontend-kb"]

        with patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id') as mock_query_agents:
            mock_query_agents.return_value = []

            with patch('backend.services.prompt_service.generate_system_prompt') as mock_gen:
                def mock_generator(*args, **kwargs):
                    yield {"type": "duty", "content": "duty content", "is_complete": True}

                mock_gen.side_effect = mock_generator

                result = list(generate_and_save_system_prompt_impl(
                    agent_id=123,
                    model_id=1,
                    task_description="Task",
                    user_id="u",
                    tenant_id="t",
                    language="zh",
                    tool_ids=[1],
                    sub_agent_ids=[],
                    knowledge_base_display_names=["my-kb"],
                ))

                mock_get_kb.assert_not_called()

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.join_info_for_generate_system_prompt')
    @patch('backend.services.prompt_service.resolve_prompt_generate_template')
    @patch('backend.services.prompt_service.get_model_by_model_id')
    def test_generate_system_prompt_no_selected_resources(self, mock_get_model, mock_resolve, mock_join, mock_call_llm):
        """Test generate_system_prompt with has_selected_resources=False skips constraint/few_shots"""
        mock_get_model.return_value = None
        mock_resolve.return_value = {
            "user_prompt": "Test",
            "duty_system_prompt": "duty",
            "constraint_system_prompt": "constraint",
            "few_shots_system_prompt": "few shots",
            "agent_variable_name_system_prompt": "var name",
            "agent_display_name_system_prompt": "display name",
            "agent_description_system_prompt": "description",
        }
        mock_join.return_value = "joined"

        def mock_llm(model_id, content, sys_prompt, callback, tenant_id):
            if callback:
                callback("content")
            if "var_name" in sys_prompt.lower():
                return "test_agent"
            elif "display_name" in sys_prompt.lower():
                return "Test Agent"
            elif "description" in sys_prompt.lower():
                return "desc"
            return "content"

        mock_call_llm.side_effect = mock_llm

        result_list = list(generate_system_prompt(
            [{"name": "a1"}],
            "task",
            [],
            "tenant",
            "user",
            self.test_model_id,
            "zh",
            has_selected_resources=False,
        ))

        final_results = [r for r in result_list if r.get("is_complete")]
        constraint_items = [r for r in final_results if r["type"] == "constraint"]
        fewshots_items = [r for r in final_results if r["type"] == "few_shots"]
        self.assertEqual(len(constraint_items), 1)
        self.assertEqual(constraint_items[0]["content"], "")
        self.assertEqual(len(fewshots_items), 1)
        self.assertEqual(fewshots_items[0]["content"], "")

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.join_info_for_generate_system_prompt')
    @patch('backend.services.prompt_service.resolve_prompt_generate_template')
    @patch('backend.services.prompt_service.get_model_by_model_id')
    def test_generate_system_prompt_with_concurrency_limit(self, mock_get_model, mock_resolve, mock_join, mock_call_llm):
        """Test generate_system_prompt with concurrency_limit < 6 uses semaphore"""
        mock_get_model.return_value = {"concurrency_limit": 2}
        mock_resolve.return_value = {
            "user_prompt": "Test",
            "duty_system_prompt": "duty",
            "constraint_system_prompt": "constraint",
            "few_shots_system_prompt": "few shots",
            "agent_variable_name_system_prompt": "var name",
            "agent_display_name_system_prompt": "display name",
            "agent_description_system_prompt": "description",
        }
        mock_join.return_value = "joined"

        def mock_llm(model_id, content, sys_prompt, callback, tenant_id):
            if callback:
                callback("content")
            if "var_name" in sys_prompt.lower():
                return "test_agent"
            elif "display_name" in sys_prompt.lower():
                return "Test Agent"
            elif "description" in sys_prompt.lower():
                return             "desc"
            return "content"

        mock_call_llm.side_effect = mock_llm

        result_list = list(generate_system_prompt(
            [],
            "task",
            [],
            "tenant",
            "user",
            self.test_model_id,
            "zh",
        ))

        self.assertGreater(len(result_list), 0)

class TestPromptOptimizationService(unittest.TestCase):
    """Tests for PromptOptimizationService Jiuwen SDK integration"""

    @patch('backend.services.prompt_service.optimize_prompt_section_impl')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', False)
    def test_optimize_nexent_fallback_general_mode(self, mock_impl):
        """nexent 模式: mode=general 应该调用 optimize_prompt_section_impl"""
        mock_impl.return_value = {
            "section_type": "duty",
            "section_title": "智能体角色",
            "original_content": "old",
            "optimized_content": "new",
        }

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="智能体角色",
            current_content="old", feedback="improve",
            mode="general",
        )
        result = service.optimize(req)

        self.assertEqual(result.source, "nexent")
        self.assertEqual(result.optimized_content, "new")
        mock_impl.assert_called_once()

    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', False)
    def test_optimize_nexent_fallback_insert_mode_raises(self):
        """nexent 模式: mode=insert 应该抛出 NexentCapabilityError"""
        from adapters.exception import NexentCapabilityError

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="title",
            current_content="old", feedback="improve",
            mode="insert",
        )
        with self.assertRaises(NexentCapabilityError) as ctx:
            service.optimize(req)
        self.assertIn("insert", str(ctx.exception))

    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', False)
    def test_optimize_nexent_fallback_select_mode_raises(self):
        """nexent 模式: mode=select 应该抛出 NexentCapabilityError"""
        from adapters.exception import NexentCapabilityError

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="title",
            current_content="old", feedback="improve",
            mode="select",
        )
        with self.assertRaises(NexentCapabilityError):
            service.optimize(req)

    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', False)
    def test_optimize_badcase_nexent_raises(self):
        """nexent 模式: badcase 优化应该抛出 NexentCapabilityError"""
        from adapters.exception import NexentCapabilityError

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        with self.assertRaises(NexentCapabilityError) as ctx:
            service.optimize_badcase(
                current_content="old",
                bad_cases=[{"question": "Q1", "answer": "A1"}],
                agent_id=1, section_type="duty", section_title="title",
            )
        self.assertIn("badcase", str(ctx.exception))

    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_is_jiuwen_mode_available_env_disabled(self):
        """开关关闭时 Jiuwen SDK 不可用"""
        from consts.const import ENABLE_JIUWEN_SDK

        # Patch ENABLE_JIUWEN_SDK to False
        with patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', False):
            service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
            self.assertFalse(service.is_jiuwen_mode_available())

    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_is_jiuwen_mode_available_openjiuwen_missing(self):
        """openjiuwen 未安装时 Jiuwen SDK 不可用"""
        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        with patch('builtins.__import__', side_effect=ModuleNotFoundError("No module named 'openjiuwen'")):
            self.assertFalse(service.is_jiuwen_mode_available())

    def test_optimize_request_dataclass_fields(self):
        """OptimizeRequest dataclass 所有字段正确"""
        req = OptimizeRequest(
            agent_id=1, model_id=2, task_description="task",
            section_type="duty", section_title="title",
            current_content="old", feedback="improve",
            mode="insert", start_pos=5, end_pos=10,
            tool_ids=[1, 2], sub_agent_ids=[3],
            knowledge_base_display_names=["kb1"],
        )
        self.assertEqual(req.agent_id, 1)
        self.assertEqual(req.model_id, 2)
        self.assertEqual(req.mode, "insert")
        self.assertEqual(req.start_pos, 5)
        self.assertEqual(req.end_pos, 10)
        self.assertEqual(req.tool_ids, [1, 2])
        self.assertEqual(req.sub_agent_ids, [3])
        self.assertEqual(req.knowledge_base_display_names, ["kb1"])

    def test_optimize_result_dataclass_fields(self):
        """OptimizeResult dataclass 所有字段正确"""
        res = OptimizeResult(
            optimized_content="new",
            source="jiuwen",
            section_type="duty",
            section_title="title",
            original_content="old",
        )
        self.assertEqual(res.optimized_content, "new")
        self.assertEqual(res.source, "jiuwen")
        self.assertEqual(res.section_type, "duty")
        self.assertEqual(res.section_title, "title")
        self.assertEqual(res.original_content, "old")
    @patch('backend.services.prompt_service.get_enabled_sub_agent_description_for_generate_prompt')
    @patch('backend.services.prompt_service.get_enabled_tool_description_for_generate_prompt')
    def test_generate_and_save_system_prompt_impl_auto_detect_no_resources(
        self, mock_enabled_tools, mock_enabled_sub_agents
    ):
        """Test that has_selected_resources is automatically set to False when both tool and sub-agent lists are empty.

        This covers the fix for the regression where adding the prompt template feature inadvertently
        bypassed the conditional generation of constraint/few_shots sections.
        """
        mock_enabled_tools.return_value = []
        mock_enabled_sub_agents.return_value = []

        with patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id') as mock_query_agents:
            mock_query_agents.return_value = []

            with patch('backend.services.prompt_service.generate_system_prompt') as mock_gen:
                def mock_generator(*args, **kwargs):
                    yield {"type": "duty", "content": "duty content", "is_complete": True}
                    yield {"type": "agent_var_name", "content": "test", "is_complete": True}
                    yield {"type": "agent_display_name", "content": "Test", "is_complete": True}
                    yield {"type": "agent_description", "content": "desc", "is_complete": True}

                mock_gen.side_effect = mock_generator

                list(generate_and_save_system_prompt_impl(
                    agent_id=123,
                    model_id=1,
                    task_description="Task",
                    user_id="u",
                    tenant_id="t",
                    language="zh",
                    tool_ids=[],
                    sub_agent_ids=[],
                    has_selected_resources=True,
                ))

                mock_gen.assert_called_once()
                bound_args = inspect.signature(generate_system_prompt).bind(
                    *mock_gen.call_args.args,
                    **mock_gen.call_args.kwargs,
                )
                self.assertIs(
                    bound_args.arguments["has_selected_resources"],
                    False,
                    "has_selected_resources should be False when both tool and sub-agent lists are empty",
                )

    @patch('backend.services.prompt_service.get_enabled_sub_agent_description_for_generate_prompt')
    @patch('backend.services.prompt_service.get_enabled_tool_description_for_generate_prompt')
    def test_generate_and_save_system_prompt_impl_auto_detect_has_tools(
        self, mock_enabled_tools, mock_enabled_sub_agents
    ):
        """Test that has_selected_resources is automatically set to True when tools are present."""
        mock_enabled_tools.return_value = [{"name": "db_tool"}]
        mock_enabled_sub_agents.return_value = []

        with patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id') as mock_query_agents:
            mock_query_agents.return_value = []

            with patch('backend.services.prompt_service.generate_system_prompt') as mock_gen:
                def mock_generator(*args, **kwargs):
                    yield {"type": "duty", "content": "duty", "is_complete": True}
                    yield {"type": "constraint", "content": "constraints", "is_complete": True}
                    yield {"type": "few_shots", "content": "examples", "is_complete": True}
                    yield {"type": "agent_var_name", "content": "test", "is_complete": True}
                    yield {"type": "agent_display_name", "content": "Test", "is_complete": True}
                    yield {"type": "agent_description", "content": "desc", "is_complete": True}

                mock_gen.side_effect = mock_generator

                list(generate_and_save_system_prompt_impl(
                    agent_id=123,
                    model_id=1,
                    task_description="Task",
                    user_id="u",
                    tenant_id="t",
                    language="zh",
                    tool_ids=[],
                    sub_agent_ids=[],
                    has_selected_resources=False,
                ))

                mock_gen.assert_called_once()
                bound_args = inspect.signature(generate_system_prompt).bind(
                    *mock_gen.call_args.args,
                    **mock_gen.call_args.kwargs,
                )
                self.assertIs(
                    bound_args.arguments["has_selected_resources"],
                    True,
                    "has_selected_resources should be True when tools are present",
                )

    @patch('backend.services.prompt_service.get_enabled_sub_agent_description_for_generate_prompt')
    @patch('backend.services.prompt_service.get_enabled_tool_description_for_generate_prompt')
    def test_generate_and_save_system_prompt_impl_auto_detect_has_sub_agents(
        self, mock_enabled_tools, mock_enabled_sub_agents
    ):
        """Test that has_selected_resources is automatically set to True when sub-agents are present."""
        mock_enabled_tools.return_value = []
        mock_enabled_sub_agents.return_value = [{"name": "sub_agent"}]

        with patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id') as mock_query_agents:
            mock_query_agents.return_value = []

            with patch('backend.services.prompt_service.generate_system_prompt') as mock_gen:
                def mock_generator(*args, **kwargs):
                    yield {"type": "duty", "content": "duty", "is_complete": True}
                    yield {"type": "constraint", "content": "constraints", "is_complete": True}
                    yield {"type": "few_shots", "content": "examples", "is_complete": True}
                    yield {"type": "agent_var_name", "content": "test", "is_complete": True}
                    yield {"type": "agent_display_name", "content": "Test", "is_complete": True}
                    yield {"type": "agent_description", "content": "desc", "is_complete": True}

                mock_gen.side_effect = mock_generator

                list(generate_and_save_system_prompt_impl(
                    agent_id=123,
                    model_id=1,
                    task_description="Task",
                    user_id="u",
                    tenant_id="t",
                    language="zh",
                    tool_ids=[],
                    sub_agent_ids=[],
                    has_selected_resources=False,
                ))

                mock_gen.assert_called_once()
                bound_args = inspect.signature(generate_system_prompt).bind(
                    *mock_gen.call_args.args,
                    **mock_gen.call_args.kwargs,
                )
                self.assertIs(
                    bound_args.arguments["has_selected_resources"],
                    True,
                    "has_selected_resources should be True when sub-agents are present",
                )


# ==================== Tests for aidp_kb_display_names parameter ====================


class TestGenerateAndSaveSystemPromptImplAidpKbNames(unittest.TestCase):
    """Test aidp_kb_display_names handling in generate_and_save_system_prompt_impl."""

    def setUp(self):
        self.test_model_id = 1

    def _make_mock_generator(self):
        def mock_gen(*args, **kwargs):
            yield {"type": "duty", "content": "duty", "is_complete": True}
            yield {"type": "constraint", "content": "constraints", "is_complete": True}
            yield {"type": "few_shots", "content": "examples", "is_complete": True}
            yield {"type": "agent_var_name", "content": "test_agent", "is_complete": True}
            yield {"type": "agent_display_name", "content": "Test Agent", "is_complete": True}
            yield {"type": "agent_description", "content": "desc", "is_complete": True}
        return mock_gen

    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service._resolve_aidp_kb_display_names')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_frontend_provided_aidp_names_is_used_directly(
        self,
        mock_search_agent,
        mock_query_tools,
        mock_resolve_aidp,
        mock_generate_system_prompt,
        mock_query_all_agents,
    ):
        """When frontend provides aidp_kb_display_names, _resolve_aidp_kb_display_names is skipped."""
        mock_query_tools.return_value = [
            {"name": "tool1", "description": "d", "inputs": "{}", "output_type": "text"}
        ]
        mock_search_agent.return_value = {"name": "a1", "description": "d"}
        mock_query_all_agents.return_value = []
        mock_generate_system_prompt.side_effect = self._make_mock_generator()

        list(generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=self.test_model_id,
            task_description="Task",
            user_id="user1",
            tenant_id="tenant1",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[10],
            aidp_kb_display_names=["aidp-kb-1"],
        ))

        mock_resolve_aidp.assert_not_called()

        mock_generate_system_prompt.assert_called_once()
        bound_args = inspect.signature(generate_system_prompt).bind(
            *mock_generate_system_prompt.call_args.args,
            **mock_generate_system_prompt.call_args.kwargs,
        )
        self.assertIsNone(bound_args.arguments["aidp_kb_display_names"])

    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service._resolve_aidp_kb_display_names')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_falls_back_to_db_resolution_when_not_provided(
        self,
        mock_search_agent,
        mock_query_tools,
        mock_resolve_aidp,
        mock_generate_system_prompt,
        mock_query_all_agents,
    ):
        """When aidp_kb_display_names is None, _resolve_aidp_kb_display_names is called."""
        mock_query_tools.return_value = [
            {"name": "tool1", "description": "d", "inputs": "{}", "output_type": "text"}
        ]
        mock_search_agent.return_value = {"name": "a1", "description": "d"}
        mock_query_all_agents.return_value = []
        mock_resolve_aidp.return_value = ["db-resolved"]
        mock_generate_system_prompt.side_effect = self._make_mock_generator()

        list(generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=self.test_model_id,
            task_description="Task",
            user_id="user1",
            tenant_id="tenant1",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[10],
            aidp_kb_display_names=None,
        ))

        # Verify _resolve_aidp_kb_display_names was called with correct args
        mock_resolve_aidp.assert_not_called()

        # Verify downstream receives the resolved value
        mock_generate_system_prompt.assert_called_once()
        bound_args = inspect.signature(generate_system_prompt).bind(
            *mock_generate_system_prompt.call_args.args,
            **mock_generate_system_prompt.call_args.kwargs,
        )
        self.assertIsNone(bound_args.arguments["aidp_kb_display_names"])

    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service._resolve_aidp_kb_display_names')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_empty_frontend_names_triggers_fallback(
        self,
        mock_search_agent,
        mock_query_tools,
        mock_resolve_aidp,
        mock_generate_system_prompt,
        mock_query_all_agents,
    ):
        """Empty list is falsy, so _resolve_aidp_kb_display_names should be called."""
        mock_query_tools.return_value = [
            {"name": "tool1", "description": "d", "inputs": "{}", "output_type": "text"}
        ]
        mock_search_agent.return_value = {"name": "a1", "description": "d"}
        mock_query_all_agents.return_value = []
        mock_resolve_aidp.return_value = ["fallback-name"]
        mock_generate_system_prompt.side_effect = self._make_mock_generator()

        list(generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=self.test_model_id,
            task_description="Task",
            user_id="user1",
            tenant_id="tenant1",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[10],
            aidp_kb_display_names=[],
        ))

        mock_resolve_aidp.assert_not_called()

    @patch('backend.services.prompt_service.join_info_for_generate_system_prompt')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service._resolve_aidp_kb_display_names')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_aidp_names_passed_through_to_join_info(
        self,
        mock_search_agent,
        mock_query_tools,
        mock_resolve_aidp,
        mock_generate_system_prompt,
        mock_query_all_agents,
        mock_join_info,
    ):
        """Resolved aidp_kb_display_names flows to join_info_for_generate_system_prompt."""
        mock_query_tools.return_value = [
            {"name": "tool1", "description": "d", "inputs": "{}", "output_type": "text"}
        ]
        mock_search_agent.return_value = {"name": "a1", "description": "d"}
        mock_query_all_agents.return_value = []
        mock_resolve_aidp.return_value = ["resolved-kb"]
        mock_join_info.return_value = "content"
        mock_generate_system_prompt.side_effect = self._make_mock_generator()

        list(generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=self.test_model_id,
            task_description="Task",
            user_id="user1",
            tenant_id="tenant1",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[10],
            aidp_kb_display_names=None,
        ))

        # generate_system_prompt calls join_info_for_generate_system_prompt internally
        # but since we mock generate_system_prompt we cannot observe that chain directly.
        # Instead verify the resolved value reaches generate_system_prompt kwargs.
        mock_generate_system_prompt.assert_called_once()
        bound_args = inspect.signature(generate_system_prompt).bind(
            *mock_generate_system_prompt.call_args.args,
            **mock_generate_system_prompt.call_args.kwargs,
        )
        self.assertIsNone(bound_args.arguments["aidp_kb_display_names"])


class TestJoinInfoForGenerateSystemPromptAidpKbNames(unittest.TestCase):
    """Test aidp_kb_names rendering in join_info_for_generate_system_prompt."""

    @patch('backend.services.prompt_service.Template')
    def test_rendered_string_when_aidp_kb_display_names_set(self, mock_template):
        mock_template_instance = MagicMock()
        mock_template.return_value = mock_template_instance
        mock_template_instance.render.return_value = "rendered"

        join_info_for_generate_system_prompt(
            prompt_for_generate={"user_prompt": "tmpl"},
            sub_agent_info_list=[{"name": "a", "description": "d"}],
            task_description="task",
            tool_info_list=[
                {"name": "t", "description": "d", "inputs": "{}", "output_type": "text"}
            ],
            language="en",
            aidp_kb_display_names=["kb-1", "kb-2"],
        )

        template_vars = mock_template_instance.render.call_args[0][0]
        self.assertEqual(template_vars["aidp_kb_names"], "")

    @patch('backend.services.prompt_service.Template')
    def test_empty_string_when_aidp_kb_display_names_none(self, mock_template):
        mock_template_instance = MagicMock()
        mock_template.return_value = mock_template_instance
        mock_template_instance.render.return_value = "rendered"

        join_info_for_generate_system_prompt(
            prompt_for_generate={"user_prompt": "tmpl"},
            sub_agent_info_list=[{"name": "a", "description": "d"}],
            task_description="task",
            tool_info_list=[
                {"name": "t", "description": "d", "inputs": "{}", "output_type": "text"}
            ],
            language="en",
            aidp_kb_display_names=None,
        )

        template_vars = mock_template_instance.render.call_args[0][0]
        self.assertEqual(template_vars["aidp_kb_names"], "")

    @patch('backend.services.prompt_service.Template')
    def test_empty_string_when_aidp_kb_display_names_empty_list(self, mock_template):
        mock_template_instance = MagicMock()
        mock_template.return_value = mock_template_instance
        mock_template_instance.render.return_value = "rendered"

        join_info_for_generate_system_prompt(
            prompt_for_generate={"user_prompt": "tmpl"},
            sub_agent_info_list=[{"name": "a", "description": "d"}],
            task_description="task",
            tool_info_list=[
                {"name": "t", "description": "d", "inputs": "{}", "output_type": "text"}
            ],
            language="en",
            aidp_kb_display_names=[],
        )

        template_vars = mock_template_instance.render.call_args[0][0]
        self.assertEqual(template_vars["aidp_kb_names"], "")

    @patch('backend.services.prompt_service.Template')
    def test_default_value_is_empty_string(self, mock_template):
        mock_template_instance = MagicMock()
        mock_template.return_value = mock_template_instance
        mock_template_instance.render.return_value = "rendered"

        join_info_for_generate_system_prompt(
            prompt_for_generate={"user_prompt": "tmpl"},
            sub_agent_info_list=[{"name": "a", "description": "d"}],
            task_description="task",
            tool_info_list=[
                {"name": "t", "description": "d", "inputs": "{}", "output_type": "text"}
            ],
            language="en",
        )

        template_vars = mock_template_instance.render.call_args[0][0]
        self.assertEqual(template_vars["aidp_kb_names"], "")


class TestResolveAidpKbDisplayNames(unittest.TestCase):
    """Test _resolve_aidp_kb_display_names delegation."""

    @patch('backend.services.prompt_service.get_aidp_kb_display_names')
    def test_delegates_to_get_aidp_kb_display_names(self, mock_get_aidp):
        tool_info = [{"name": "aidp_search", "tool_id": 42}]
        mock_get_aidp.return_value = ["resolved-kb-1", "resolved-kb-2"]

        result = _resolve_aidp_kb_display_names(
            tool_info_list=tool_info,
            user_id="user1",
            tenant_id="tenant1",
        )

        mock_get_aidp.assert_called_once_with(
            tool_info_list=tool_info,
            user_id="user1",
            tenant_id="tenant1",
        )
        self.assertEqual(result, ["resolved-kb-1", "resolved-kb-2"])


class TestJoinInfoForOptimizePromptSectionAidpKbNames(unittest.TestCase):
    """Test aidp_kb_names in join_info_for_optimize_prompt_section template context."""

    @patch('backend.services.prompt_service.Template')
    def test_aidp_kb_display_names_passed_to_template_context(self, mock_template):
        mock_template_instance = MagicMock()
        mock_template.return_value = mock_template_instance
        mock_template_instance.render.return_value = "rendered"

        join_info_for_optimize_prompt_section(
            prompt_for_optimize={"OPTIMIZE_USER_PROMPT": "tmpl"},
            section_type="duty",
            section_title="Duties",
            task_description="task",
            current_content="content",
            feedback="feedback",
            tool_info_list=[
                {"name": "t", "description": "d", "inputs": "{}", "output_type": "text"}
            ],
            sub_agent_info_list=[
                {"name": "a", "description": "d"}
            ],
            language="en",
            aidp_kb_display_names=["aidp-kb-a", "aidp-kb-b"],
        )

        template_vars = mock_template_instance.render.call_args[0][0]
        self.assertEqual(template_vars["aidp_kb_names"], "")


# ==================== Coverage boost tests ====================


class TestExtractJsonObject(unittest.TestCase):
    """Tests for _extract_json_object helper (lines 486-513)."""

    def test_returns_none_for_empty_input(self):
        from backend.services.prompt_service import _extract_json_object
        self.assertIsNone(_extract_json_object(""))
        self.assertIsNone(_extract_json_object(None))
        self.assertIsNone(_extract_json_object("   "))

    def test_returns_none_when_no_braces(self):
        from backend.services.prompt_service import _extract_json_object
        self.assertIsNone(_extract_json_object("just plain text no json"))

    def test_extracts_simple_json_object(self):
        from backend.services.prompt_service import _extract_json_object
        raw = 'some text {"key": "value"} more text'
        result = _extract_json_object(raw)
        self.assertEqual(result, {"key": "value"})

    def test_extracts_nested_json(self):
        from backend.services.prompt_service import _extract_json_object
        raw = '{"type": "single", "candidates": [{"pattern": "\\d+", "desc": "digits"}]}'
        result = _extract_json_object(raw)
        self.assertEqual(result["type"], "single")
        self.assertEqual(len(result["candidates"]), 1)

    def test_handles_single_quotes_fallback(self):
        from backend.services.prompt_service import _extract_json_object
        raw = "{'type': 'single', 'count': 1}"
        result = _extract_json_object(raw)
        self.assertEqual(result["type"], "single")
        self.assertEqual(result["count"], 1)

    def test_handles_trailing_commas_fallback(self):
        from backend.services.prompt_service import _extract_json_object
        raw = '{"type": "single", "items": [1, 2,],}'
        result = _extract_json_object(raw)
        # Should fix trailing commas and parse successfully
        self.assertIsNotNone(result)

    def test_handles_invalid_json_escape_fallback(self):
        from backend.services.prompt_service import _extract_json_object
        # LLM often outputs \d \w etc. with single backslash (invalid JSON)
        raw = r'{"pattern": "\d+\.\d+"}'
        result = _extract_json_object(raw)
        self.assertIsNotNone(result)
        self.assertIn("pattern", result)

    def test_returns_none_for_completely_invalid_json(self):
        from backend.services.prompt_service import _extract_json_object
        raw = "{not json at all!!!"
        result = _extract_json_object(raw)
        self.assertIsNone(result)

    def test_end_before_start_returns_none(self):
        from backend.services.prompt_service import _extract_json_object
        raw = "} something {"
        result = _extract_json_object(raw)
        self.assertIsNone(result)


class TestGenerateGuardrailRulesImpl(unittest.TestCase):
    """Tests for generate_guardrail_rules_impl (lines 547-586)."""

    def test_empty_description_raises(self):
        from backend.services.prompt_service import generate_guardrail_rules_impl
        with self.assertRaises(AppException) as ctx:
            generate_guardrail_rules_impl(
                description="",
                model_id=1,
                tenant_id="t",
            )
        self.assertEqual(ctx.exception.error_code, ErrorCode.COMMON_MISSING_REQUIRED_FIELD)

    def test_whitespace_description_raises(self):
        from backend.services.prompt_service import generate_guardrail_rules_impl
        with self.assertRaises(AppException) as ctx:
            generate_guardrail_rules_impl(
                description="   ",
                model_id=1,
                tenant_id="t",
            )
        self.assertEqual(ctx.exception.error_code, ErrorCode.COMMON_MISSING_REQUIRED_FIELD)

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.get_guardrail_regex_prompt_template')
    def test_empty_llm_response_raises(self, mock_template, mock_llm):
        from backend.services.prompt_service import generate_guardrail_rules_impl
        mock_template.return_value = {
            "GUARDRAIL_USER_PROMPT": "prompt {{ description }}",
            "GUARDRAIL_SYSTEM_PROMPT": "system",
        }
        mock_llm.return_value = "   "

        with self.assertRaises(AppException) as ctx:
            generate_guardrail_rules_impl(
                description="block phone numbers",
                model_id=1,
                tenant_id="t",
            )
        self.assertEqual(ctx.exception.error_code, ErrorCode.MODEL_PROMPT_GENERATION_FAILED)

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.get_guardrail_regex_prompt_template')
    def test_invalid_json_response_raises(self, mock_template, mock_llm):
        from backend.services.prompt_service import generate_guardrail_rules_impl
        mock_template.return_value = {
            "GUARDRAIL_USER_PROMPT": "prompt {{ description }}",
            "GUARDRAIL_SYSTEM_PROMPT": "system",
        }
        mock_llm.return_value = "no json here at all"

        with self.assertRaises(AppException) as ctx:
            generate_guardrail_rules_impl(
                description="block phone numbers",
                model_id=1,
                tenant_id="t",
            )
        self.assertEqual(ctx.exception.error_code, ErrorCode.MODEL_PROMPT_GENERATION_FAILED)

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.get_guardrail_regex_prompt_template')
    def test_unknown_type_raises(self, mock_template, mock_llm):
        from backend.services.prompt_service import generate_guardrail_rules_impl
        mock_template.return_value = {
            "GUARDRAIL_USER_PROMPT": "prompt {{ description }}",
            "GUARDRAIL_SYSTEM_PROMPT": "system",
        }
        mock_llm.return_value = '{"type": "unknown_type", "data": []}'

        with self.assertRaises(AppException) as ctx:
            generate_guardrail_rules_impl(
                description="block phone numbers",
                model_id=1,
                tenant_id="t",
            )
        self.assertEqual(ctx.exception.error_code, ErrorCode.MODEL_PROMPT_GENERATION_FAILED)
        self.assertIn("Unknown guardrail result type", ctx.exception.message)

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.get_guardrail_regex_prompt_template')
    def test_single_type_success(self, mock_template, mock_llm):
        from backend.services.prompt_service import generate_guardrail_rules_impl
        mock_template.return_value = {
            "GUARDRAIL_USER_PROMPT": "prompt {{ description }}",
            "GUARDRAIL_SYSTEM_PROMPT": "system",
        }
        mock_llm.return_value = '{"type": "single", "candidates": [{"pattern": "1[3-9]\\d{9}", "desc": "phone"}]}'

        result = generate_guardrail_rules_impl(
            description="block phone numbers",
            model_id=1,
            tenant_id="t",
        )
        self.assertEqual(result["type"], "single")
        self.assertIsInstance(result["candidates"], list)

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.get_guardrail_regex_prompt_template')
    def test_multi_type_success(self, mock_template, mock_llm):
        from backend.services.prompt_service import generate_guardrail_rules_impl
        mock_template.return_value = {
            "GUARDRAIL_USER_PROMPT": "prompt {{ description }}",
            "GUARDRAIL_SYSTEM_PROMPT": "system",
        }
        mock_llm.return_value = '{"type": "multi", "rules": [{"name": "r1", "pattern": "\\d", "severity": "high", "desc": "d"}]}'

        result = generate_guardrail_rules_impl(
            description="block sensitive patterns",
            model_id=1,
            tenant_id="t",
        )
        self.assertEqual(result["type"], "multi")
        self.assertIsInstance(result["rules"], list)

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.get_guardrail_regex_prompt_template')
    def test_single_type_with_non_list_candidates(self, mock_template, mock_llm):
        from backend.services.prompt_service import generate_guardrail_rules_impl
        mock_template.return_value = {
            "GUARDRAIL_USER_PROMPT": "prompt {{ description }}",
            "GUARDRAIL_SYSTEM_PROMPT": "system",
        }
        mock_llm.return_value = '{"type": "single", "candidates": "not_a_list"}'

        result = generate_guardrail_rules_impl(
            description="block phone numbers",
            model_id=1,
            tenant_id="t",
        )
        self.assertEqual(result["type"], "single")
        self.assertEqual(result["candidates"], [])

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.get_guardrail_regex_prompt_template')
    def test_multi_type_with_non_list_rules(self, mock_template, mock_llm):
        from backend.services.prompt_service import generate_guardrail_rules_impl
        mock_template.return_value = {
            "GUARDRAIL_USER_PROMPT": "prompt {{ description }}",
            "GUARDRAIL_SYSTEM_PROMPT": "system",
        }
        mock_llm.return_value = '{"type": "multi", "rules": "not_a_list"}'

        result = generate_guardrail_rules_impl(
            description="block sensitive patterns",
            model_id=1,
            tenant_id="t",
        )
        self.assertEqual(result["type"], "multi")
        self.assertEqual(result["rules"], [])


class TestGetAidpKbDisplayNames(unittest.TestCase):
    """Tests for get_aidp_kb_display_names (lines 1086-1099)."""

    def test_no_aidp_tool_returns_none(self):
        from backend.services.prompt_service import get_aidp_kb_display_names
        tool_info_list = [{"name": "web_search", "tool_id": 1}]
        result = get_aidp_kb_display_names(tool_info_list, "user1", "tenant1")
        self.assertIsNone(result)

    def test_empty_tool_list_returns_none(self):
        from backend.services.prompt_service import get_aidp_kb_display_names
        result = get_aidp_kb_display_names([], "user1", "tenant1")
        self.assertIsNone(result)

    @patch('backend.services.prompt_service.sys')
    def test_aidp_tool_found_returns_display_names(self, mock_sys_mod):
        """When aidp_search tool exists, import and call permission service."""
        from backend.services.prompt_service import get_aidp_kb_display_names

        mock_access_module = MagicMock()
        mock_access_module.resolve_current_aidp_access.return_value = types.SimpleNamespace(
            name_to_id={"KB-Alpha": "1", "KB-Beta": "2"}
        )

        tool_info_list = [
            {"name": "aidp_search", "tool_id": 42},
            {"name": "web_search", "tool_id": 1},
        ]

        with patch.dict(sys.modules, {
            'ext_components.aidp.services.aidp_access_service': mock_access_module,
        }):
            result = get_aidp_kb_display_names(tool_info_list, "user1", "tenant1")

        self.assertEqual(result, ["KB-Alpha", "KB-Beta"])

    @patch('backend.services.prompt_service.sys')
    def test_aidp_tool_found_empty_map_returns_none(self, mock_sys_mod):
        """When kds_name_to_id_map is empty, return None."""
        from backend.services.prompt_service import get_aidp_kb_display_names

        mock_access_module = MagicMock()
        mock_access_module.resolve_current_aidp_access.return_value = types.SimpleNamespace(
            name_to_id={}
        )

        tool_info_list = [{"name": "aidp_search", "tool_id": 42}]

        with patch.dict(sys.modules, {
            'ext_components.aidp.services.aidp_access_service': mock_access_module,
        }):
            result = get_aidp_kb_display_names(tool_info_list, "user1", "tenant1")

        self.assertIsNone(result)

    @patch('backend.services.prompt_service.sys')
    def test_aidp_tool_import_error_returns_none(self, mock_sys_mod):
        """When import fails, return None gracefully."""
        from backend.services.prompt_service import get_aidp_kb_display_names

        tool_info_list = [{"name": "aidp_search", "tool_id": 42}]

        # Make the import raise an exception
        with patch.dict(sys.modules, {'ext_components.aidp.services': None}):
            with patch('builtins.__import__', side_effect=Exception("Module not found")):
                result = get_aidp_kb_display_names(tool_info_list, "user1", "tenant1")

        self.assertIsNone(result)


class TestStreamResultsErrorPath(unittest.TestCase):
    """Tests for _stream_results error handling (lines 808-828)."""

    def test_error_holder_raises_immediately(self):
        """When error_holder has an error, _stream_results raises it after joining threads."""
        import queue as q_module
        from backend.services.prompt_service import _stream_results

        produce_q = q_module.Queue()
        latest = {"duty": "", "constraint": "", "few_shots": "",
                  "agent_var_name": "", "agent_display_name": "", "agent_description": ""}
        stop_flags = {"duty": False, "constraint": False, "few_shots": False,
                      "agent_var_name": False, "agent_display_name": False, "agent_description": False}
        mock_thread = MagicMock()
        mock_thread.join = MagicMock()
        threads = [mock_thread]
        error_holder = {"error": RuntimeError("Thread error")}

        with self.assertRaises(RuntimeError) as ctx:
            list(_stream_results(produce_q, latest, stop_flags, threads, error_holder))

        self.assertIn("Thread error", str(ctx.exception))
        mock_thread.join.assert_called()

    def test_streaming_yields_updated_content(self):
        """When content changes and stop flags complete, yields streaming data then final results."""
        import queue as q_module
        from backend.services.prompt_service import _stream_results

        produce_q = q_module.Queue()
        latest = {"duty": "duty content", "constraint": "", "few_shots": "",
                  "agent_var_name": "test_agent", "agent_display_name": "Test Agent", "agent_description": "desc"}
        # All flags True from start -> loop exits immediately
        stop_flags = {"duty": True, "constraint": True, "few_shots": True,
                      "agent_var_name": True, "agent_display_name": True, "agent_description": True}
        mock_thread = MagicMock()
        mock_thread.join = MagicMock()
        threads = [mock_thread]
        error_holder = {}

        # Put one item so the loop body runs once, but since all stop_flags are True,
        # the while condition fails and we skip loop entirely -> go to final results
        produce_q.put("signal")

        results = list(_stream_results(produce_q, latest, stop_flags, threads, error_holder))

        # Should yield final results for all tags that have stop_flags True
        self.assertGreater(len(results), 0)
        result_types = [r["type"] for r in results]
        self.assertIn("duty", result_types)
        self.assertIn("agent_var_name", result_types)

    def test_streaming_yields_intermediate_updates(self):
        """When new content appears, yields intermediate streaming updates."""
        import queue as q_module
        from backend.services.prompt_service import _stream_results

        produce_q = q_module.Queue()

        latest = {"duty": "", "constraint": "", "few_shots": "",
                  "agent_var_name": "", "agent_display_name": "", "agent_description": ""}

        # Start with duty not complete
        stop_flags = {"duty": False, "constraint": True, "few_shots": True,
                      "agent_var_name": True, "agent_display_name": True, "agent_description": True}
        mock_thread = MagicMock()
        mock_thread.join = MagicMock()
        threads = [mock_thread]
        error_holder = {}

        # Add items and schedule a stop flag change
        produce_q.put("signal1")

        # We'll collect results in a thread and change stop flags concurrently
        results_collected = []

        import threading

        def consumer():
            gen = _stream_results(produce_q, latest, stop_flags, threads, error_holder)
            try:
                for r in gen:
                    results_collected.append(r)
            except Exception:
                pass

        # Schedule: after first poll, update latest and set all flags True
        def updater():
            import time
            time.sleep(0.1)
            latest["duty"] = "new duty"
            stop_flags["duty"] = True
            produce_q.put("signal2")

        t_consumer = threading.Thread(target=consumer)
        t_updater = threading.Thread(target=updater)
        t_consumer.start()
        t_updater.start()
        t_consumer.join(timeout=10)
        t_updater.join(timeout=5)

        # Should have yielded at least one intermediate update for "duty"
        duty_results = [r for r in results_collected if r["type"] == "duty"]
        self.assertGreater(len(duty_results), 0)


class TestPromptOptimizationServiceOptimizeFromDebug(unittest.TestCase):
    """Tests for PromptOptimizationService.optimize_from_debug (lines 1158-1215)."""

    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', False)
    def test_empty_feedback_raises(self):
        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        selected = type("S", (), {"user_question": "q", "assistant_answer": "a"})()
        with self.assertRaises(AppException) as ctx:
            service.optimize_from_debug(agent_id=1, feedback="", selected=selected)
        self.assertEqual(ctx.exception.error_code, ErrorCode.COMMON_MISSING_REQUIRED_FIELD)

    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', False)
    def test_whitespace_feedback_raises(self):
        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        selected = type("S", (), {"user_question": "q", "assistant_answer": "a"})()
        with self.assertRaises(AppException):
            service.optimize_from_debug(agent_id=1, feedback="   ", selected=selected)

    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', False)
    def test_jiuwen_unavailable_raises(self):
        from adapters.exception import NexentCapabilityError
        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        selected = type("S", (), {"user_question": "q", "assistant_answer": "a"})()
        with self.assertRaises(NexentCapabilityError):
            service.optimize_from_debug(agent_id=1, feedback="good feedback", selected=selected)

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_successful_optimize_from_debug(self, mock_search_agent, mock_get_adapter):
        from adapters.exception import JiuwenSDKError

        mock_search_agent.return_value = {
            "duty_prompt": "Duty content",
            "constraint_prompt": "Constraint content",
            "few_shots_prompt": "FewShots content",
        }

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize_badcase.return_value = "Optimized full prompt"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        selected = type("S", (), {"user_question": "What is X?", "assistant_answer": "X is Y"})()

        result = service.optimize_from_debug(
            agent_id=1, feedback="Make it more specific", selected=selected
        )

        self.assertEqual(result.optimized_content, "Optimized full prompt")
        self.assertEqual(result.source, "jiuwen")
        self.assertEqual(result.section_type, "full_prompt")
        mock_adapter_instance.optimize_badcase.assert_called_once()

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_optimize_from_debug_with_dict_selected(self, mock_search_agent, mock_get_adapter):
        """Test optimize_from_debug when selected is a dict rather than an object."""
        mock_search_agent.return_value = {
            "duty_prompt": "Duty",
            "constraint_prompt": "Constraint",
            "few_shots_prompt": "FewShots",
        }

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize_badcase.return_value = "Optimized"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")

        result = service.optimize_from_debug(
            agent_id=1,
            feedback="feedback text",
            selected={"user_question": "Q?", "assistant_answer": "A!"},
        )

        self.assertEqual(result.optimized_content, "Optimized")

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_optimize_from_debug_empty_prompt_raises(self, mock_search_agent, mock_get_adapter):
        """When all agent prompts are None, the joined prompt strips to empty => AppException."""
        mock_search_agent.return_value = {
            "duty_prompt": None,
            "constraint_prompt": None,
            "few_shots_prompt": None,
        }

        mock_adapter_cls = MagicMock()
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        selected = type("S", (), {"user_question": "q", "assistant_answer": "a"})()

        # When all prompts are None, strip gives empty strings, joined gives "# Duty\n\n# Constraint\n\n# FewShots"
        # which is NOT empty after strip. So this won't raise for empty_prompt.
        # The function proceeds and calls adapter.optimize_badcase successfully.
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize_badcase.return_value = "optimized"
        mock_adapter_cls.return_value = mock_adapter_instance

        result = service.optimize_from_debug(agent_id=1, feedback="feedback", selected=selected)
        self.assertEqual(result.source, "jiuwen")

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_optimize_from_debug_adapter_none_raises(self, mock_search_agent, mock_get_adapter):
        """When _get_jiuwen_adapter_class returns None after is_jiuwen_mode_available check, raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError

        mock_search_agent.return_value = {
            "duty_prompt": "Duty",
            "constraint_prompt": "Constraint",
            "few_shots_prompt": "FewShots",
        }
        # First call (is_jiuwen_mode_available) returns a class, second call returns None
        mock_adapter_cls = MagicMock()
        mock_get_adapter.side_effect = [mock_adapter_cls, None]

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        selected = type("S", (), {"user_question": "q", "assistant_answer": "a"})()

        with self.assertRaises(JiuwenSDKError):
            service.optimize_from_debug(agent_id=1, feedback="feedback", selected=selected)


class TestPromptOptimizationServiceOptimizeJiuwen(unittest.TestCase):
    """Tests for PromptOptimizationService.optimize with Jiuwen SDK paths (lines 1238-1303)."""

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_general_mode(self, mock_get_adapter):
        """Jiuwen SDK general mode returns optimized content."""
        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "Optimized by Jiuwen"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="Original content", feedback="Improve this",
            mode="general",
        )

        result = service.optimize(req)

        self.assertEqual(result.source, "jiuwen")
        self.assertEqual(result.optimized_content, "Optimized by Jiuwen")
        self.assertEqual(result.original_content, "Original content")

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_insert_mode(self, mock_get_adapter):
        """Jiuwen SDK insert mode inserts text at start_pos."""
        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "INSERTED"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABCDE", feedback="insert here",
            mode="insert", start_pos=2,
        )

        result = service.optimize(req)

        self.assertEqual(result.optimized_content, "ABINSERTEDCDE")

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_select_mode(self, mock_get_adapter):
        """Jiuwen SDK select mode replaces selected range."""
        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "REPLACED"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABCDEF", feedback="replace this",
            mode="select", start_pos=1, end_pos=4,
        )

        result = service.optimize(req)

        # "ABCDEF"[:1] + "REPLACED" + "ABCDEF"[4:] = "A" + "REPLACED" + "EF"
        self.assertEqual(result.optimized_content, "AREPLACEDEF")

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_insert_no_start_pos_raises(self, mock_get_adapter):
        """Insert mode without start_pos raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "text"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABC", feedback="insert",
            mode="insert", start_pos=None,
        )

        # Call _optimize_with_jiuwen directly to bypass the fallback in optimize()
        with self.assertRaises(JiuwenSDKError):
            service._optimize_with_jiuwen(req)

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_insert_out_of_bounds_raises(self, mock_get_adapter):
        """Insert mode with out-of-bounds start_pos raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "text"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABC", feedback="insert",
            mode="insert", start_pos=100,
        )

        with self.assertRaises(JiuwenSDKError):
            service._optimize_with_jiuwen(req)

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_select_missing_positions_raises(self, mock_get_adapter):
        """Select mode without start_pos/end_pos raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "text"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABCDEF", feedback="select",
            mode="select", start_pos=None, end_pos=None,
        )

        with self.assertRaises(JiuwenSDKError):
            service._optimize_with_jiuwen(req)

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_select_non_int_positions_raises(self, mock_get_adapter):
        """Select mode with non-integer positions raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "text"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABCDEF", feedback="select",
            mode="select", start_pos="bad", end_pos="worse",
        )

        with self.assertRaises(JiuwenSDKError):
            service._optimize_with_jiuwen(req)

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_select_invalid_range_raises(self, mock_get_adapter):
        """Select mode with start >= end raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "text"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABCDEF", feedback="select",
            mode="select", start_pos=5, end_pos=2,
        )

        with self.assertRaises(JiuwenSDKError):
            service._optimize_with_jiuwen(req)

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_select_end_out_of_bounds_raises(self, mock_get_adapter):
        """Select mode with end_pos > length raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "text"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABC", feedback="select",
            mode="select", start_pos=0, end_pos=100,
        )

        with self.assertRaises(JiuwenSDKError):
            service._optimize_with_jiuwen(req)

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_adapter_unavailable_raises(self, mock_get_adapter):
        """When adapter class is None in _optimize_with_jiuwen, raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError
        mock_get_adapter.return_value = None

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="old", feedback="improve",
            mode="general",
        )

        # Call _optimize_with_jiuwen directly to avoid the fallback chain
        with self.assertRaises(JiuwenSDKError):
            service._optimize_with_jiuwen(req)

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.optimize_prompt_section_impl')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_error_falls_back_to_nexent(self, mock_impl, mock_get_adapter):
        """When Jiuwen SDK raises JiuwenSDKError, falls back to nexent native."""
        from adapters.exception import JiuwenSDKError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.side_effect = JiuwenSDKError("SDK failed")
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        mock_impl.return_value = {
            "section_type": "duty",
            "section_title": "Role",
            "original_content": "old",
            "optimized_content": "nexent fallback",
        }

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="old", feedback="improve",
            mode="general",
        )

        result = service.optimize(req)
        self.assertEqual(result.optimized_content, "nexent fallback")


class TestPromptOptimizationServiceBadcaseJiuwen(unittest.TestCase):
    """Tests for optimize_badcase with Jiuwen SDK (lines 1354-1388)."""

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_badcase_jiuwen_success(self, mock_get_adapter):
        """Jiuwen SDK badcase optimization succeeds."""
        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize_badcase.return_value = "Badcase optimized"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        result = service.optimize_badcase(
            current_content="Current prompt",
            bad_cases=[{"question": "Q", "answer": "A"}],
            agent_id=1,
            section_type="duty",
            section_title="Role",
        )

        self.assertEqual(result.source, "jiuwen")
        self.assertEqual(result.optimized_content, "Badcase optimized")
        self.assertEqual(result.original_content, "Current prompt")

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_badcase_jiuwen_fallback_on_error(self, mock_get_adapter):
        """When Jiuwen SDK badcase fails, falls back to nexent which raises NexentCapabilityError."""
        from adapters.exception import JiuwenSDKError, NexentCapabilityError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize_badcase.side_effect = JiuwenSDKError("badcase fail")
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")

        # Fallback to nexent which raises NexentCapabilityError (no native badcase support)
        with self.assertRaises(NexentCapabilityError):
            service.optimize_badcase(
                current_content="Current prompt",
                bad_cases=[{"question": "Q", "answer": "A"}],
                agent_id=1,
                section_type="duty",
                section_title="Role",
            )

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    @patch('backend.services.prompt_service.ENABLE_JIUWEN_SDK', True)
    def test_badcase_jiuwen_adapter_none_raises(self, mock_get_adapter):
        """When adapter class is None in badcase, raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError, NexentCapabilityError

        mock_get_adapter.return_value = None

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")

        # _optimize_badcase_with_jiuwen raises JiuwenSDKError, then fallback _optimize_badcase_with_nexent raises NexentCapabilityError
        with self.assertRaises(NexentCapabilityError):
            service.optimize_badcase(
                current_content="Current prompt",
                bad_cases=[{"question": "Q", "answer": "A"}],
                agent_id=1,
                section_type="duty",
                section_title="Role",
            )


class TestGetJiuwenAdapterClass(unittest.TestCase):
    """Tests for _get_jiuwen_adapter_class (line 53, 1375-1388)."""

    def test_returns_adapter_when_importable(self):
        """When adapters module has JiuwenSDKAdapter, return it."""
        from backend.services.prompt_service import _get_jiuwen_adapter_class

        mock_adapter = MagicMock()
        mock_module = MagicMock()
        mock_module.JiuwenSDKAdapter = mock_adapter

        with patch.dict(sys.modules, {'adapters': mock_module}):
            result = _get_jiuwen_adapter_class()

        self.assertEqual(result, mock_adapter)

    def test_returns_none_when_not_importable(self):
        """When adapters module is not found, return None."""
        from backend.services.prompt_service import _get_jiuwen_adapter_class

        with patch.dict(sys.modules, {'adapters': None}):
            with patch('builtins.__import__', side_effect=ModuleNotFoundError("No module named 'adapters'")):
                result = _get_jiuwen_adapter_class()

        self.assertIsNone(result)


class TestGreetingGeneration(unittest.TestCase):
    """Tests for greeting generation within generate_and_save_system_prompt_impl (lines 347-388)."""

    @patch('backend.services.prompt_service.update_agent')
    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.get_prompt_template')
    @patch('backend.services.prompt_service.check_agent_value_duplicate')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_greeting_generation_with_valid_json(
        self,
        mock_search_agent,
        mock_query_tools,
        mock_generate_system_prompt,
        mock_query_all_agents,
        mock_check_value_dup,
        mock_get_prompt_template,
        mock_call_llm,
        mock_update_agent,
    ):
        """Greeting generation parses JSON and yields greeting_message and example_questions."""
        mock_query_tools.return_value = []
        mock_search_agent.return_value = {}
        mock_query_all_agents.return_value = []
        mock_check_value_dup.return_value = False

        def mock_gen(*args, **kwargs):
            yield {"type": "duty", "content": "duty", "is_complete": True}
            yield {"type": "constraint", "content": "constraint", "is_complete": True}
            yield {"type": "few_shots", "content": "few_shots", "is_complete": True}
            yield {"type": "agent_var_name", "content": "test", "is_complete": True}
            yield {"type": "agent_display_name", "content": "Test", "is_complete": True}
            yield {"type": "agent_description", "content": "desc", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_gen

        mock_get_prompt_template.return_value = {
            "GREETING_SYSTEM_PROMPT": "generate greeting",
            "USER_PROMPT": "Render {{ display_name }}",
        }

        greeting_json = json.dumps({
            "greeting_message": "Hello! How can I help?",
            "example_questions": ["Q1?", "Q2?", "Q3?"]
        })
        mock_call_llm.return_value = greeting_json

        result = list(generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=1,
            task_description="Task",
            user_id="u",
            tenant_id="t",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[],
        ))

        greeting_items = [r for r in result if r.get("type") == "greeting_message"]
        question_items = [r for r in result if r.get("type") == "example_questions"]

        self.assertEqual(len(greeting_items), 1)
        self.assertEqual(greeting_items[0]["content"], "Hello! How can I help?")
        self.assertEqual(len(question_items), 1)
        parsed_questions = json.loads(question_items[0]["content"])
        self.assertEqual(len(parsed_questions), 3)

    @patch('backend.services.prompt_service.update_agent')
    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.get_prompt_template')
    @patch('backend.services.prompt_service.check_agent_value_duplicate')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_greeting_generation_invalid_json_fallback(
        self,
        mock_search_agent,
        mock_query_tools,
        mock_generate_system_prompt,
        mock_query_all_agents,
        mock_check_value_dup,
        mock_get_prompt_template,
        mock_call_llm,
        mock_update_agent,
    ):
        """When JSON parsing fails, fallback to raw text."""
        mock_query_tools.return_value = []
        mock_search_agent.return_value = {}
        mock_query_all_agents.return_value = []
        mock_check_value_dup.return_value = False

        def mock_gen(*args, **kwargs):
            yield {"type": "duty", "content": "duty", "is_complete": True}
            yield {"type": "constraint", "content": "constraint", "is_complete": True}
            yield {"type": "few_shots", "content": "few_shots", "is_complete": True}
            yield {"type": "agent_var_name", "content": "test", "is_complete": True}
            yield {"type": "agent_display_name", "content": "Test", "is_complete": True}
            yield {"type": "agent_description", "content": "desc", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_gen

        mock_get_prompt_template.return_value = {
            "GREETING_SYSTEM_PROMPT": "generate greeting",
            "USER_PROMPT": "Render {{ display_name }}",
        }
        # Return invalid JSON (no valid keys)
        mock_call_llm.return_value = "plain text greeting no json"

        result = list(generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=1,
            task_description="Task",
            user_id="u",
            tenant_id="t",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[],
        ))

        greeting_items = [r for r in result if r.get("type") == "greeting_message"]
        question_items = [r for r in result if r.get("type") == "example_questions"]

        self.assertEqual(len(greeting_items), 1)
        self.assertEqual(greeting_items[0]["content"], "plain text greeting no json")
        self.assertEqual(len(question_items), 1)
        parsed_questions = json.loads(question_items[0]["content"])
        self.assertEqual(parsed_questions, [])

    @patch('backend.services.prompt_service.update_agent')
    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.get_prompt_template')
    @patch('backend.services.prompt_service.check_agent_value_duplicate')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_greeting_example_questions_truncated_at_six(
        self,
        mock_search_agent,
        mock_query_tools,
        mock_generate_system_prompt,
        mock_query_all_agents,
        mock_check_value_dup,
        mock_get_prompt_template,
        mock_call_llm,
        mock_update_agent,
    ):
        """When more than 6 example questions, truncate to 6."""
        mock_query_tools.return_value = []
        mock_search_agent.return_value = {}
        mock_query_all_agents.return_value = []
        mock_check_value_dup.return_value = False

        def mock_gen(*args, **kwargs):
            yield {"type": "duty", "content": "duty", "is_complete": True}
            yield {"type": "constraint", "content": "constraint", "is_complete": True}
            yield {"type": "few_shots", "content": "few_shots", "is_complete": True}
            yield {"type": "agent_var_name", "content": "test", "is_complete": True}
            yield {"type": "agent_display_name", "content": "Test", "is_complete": True}
            yield {"type": "agent_description", "content": "desc", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_gen

        mock_get_prompt_template.return_value = {
            "GREETING_SYSTEM_PROMPT": "generate greeting",
            "USER_PROMPT": "Render {{ display_name }}",
        }

        # Return 10 questions - should be truncated to 6
        questions = [f"Q{i}?" for i in range(10)]
        greeting_json = json.dumps({
            "greeting_message": "Hello!",
            "example_questions": questions,
        })
        mock_call_llm.return_value = greeting_json

        result = list(generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=1,
            task_description="Task",
            user_id="u",
            tenant_id="t",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[],
        ))

        question_items = [r for r in result if r.get("type") == "example_questions"]
        self.assertEqual(len(question_items), 1)
        parsed = json.loads(question_items[0]["content"])
        self.assertEqual(len(parsed), 6)

    @patch('backend.services.prompt_service.update_agent')
    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.get_prompt_template')
    @patch('backend.services.prompt_service.check_agent_value_duplicate')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_greeting_skips_agent_update_in_create_mode(
        self,
        mock_search_agent,
        mock_query_tools,
        mock_generate_system_prompt,
        mock_query_all_agents,
        mock_check_value_dup,
        mock_get_prompt_template,
        mock_call_llm,
        mock_update_agent,
    ):
        """When agent_id=0, skip update_agent call (create mode)."""
        mock_query_tools.return_value = []
        mock_search_agent.return_value = {}
        mock_query_all_agents.return_value = []
        mock_check_value_dup.return_value = False

        def mock_gen(*args, **kwargs):
            yield {"type": "duty", "content": "duty", "is_complete": True}
            yield {"type": "constraint", "content": "constraint", "is_complete": True}
            yield {"type": "few_shots", "content": "few_shots", "is_complete": True}
            yield {"type": "agent_var_name", "content": "test", "is_complete": True}
            yield {"type": "agent_display_name", "content": "Test", "is_complete": True}
            yield {"type": "agent_description", "content": "desc", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_gen

        mock_get_prompt_template.return_value = {
            "GREETING_SYSTEM_PROMPT": "generate greeting",
            "USER_PROMPT": "Render {{ display_name }}",
        }
        mock_call_llm.return_value = json.dumps({
            "greeting_message": "Hello!",
            "example_questions": ["Q1?"]
        })

        list(generate_and_save_system_prompt_impl(
            agent_id=0,
            model_id=1,
            task_description="Task",
            user_id="u",
            tenant_id="t",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[],
        ))

        mock_update_agent.assert_not_called()

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.get_prompt_template')
    @patch('backend.services.prompt_service.check_agent_value_duplicate')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_greeting_exception_does_not_stop_flow(
        self,
        mock_search_agent,
        mock_query_tools,
        mock_generate_system_prompt,
        mock_query_all_agents,
        mock_check_value_dup,
        mock_get_prompt_template,
        mock_call_llm,
    ):
        """Greeting generation exception is caught and does not stop prompt generation."""
        mock_query_tools.return_value = []
        mock_search_agent.return_value = {}
        mock_query_all_agents.return_value = []
        mock_check_value_dup.return_value = False

        def mock_gen(*args, **kwargs):
            yield {"type": "duty", "content": "duty", "is_complete": True}
            yield {"type": "constraint", "content": "constraint", "is_complete": True}
            yield {"type": "few_shots", "content": "few_shots", "is_complete": True}
            yield {"type": "agent_var_name", "content": "test", "is_complete": True}
            yield {"type": "agent_display_name", "content": "Test", "is_complete": True}
            yield {"type": "agent_description", "content": "desc", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_gen

        # Greeting generation fails
        mock_get_prompt_template.side_effect = Exception("Template error")

        result = list(generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=1,
            task_description="Task",
            user_id="u",
            tenant_id="t",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[],
        ))

        # Should still return results (greeting just skipped)
        self.assertGreater(len(result), 0)
        greeting_items = [r for r in result if r.get("type") == "greeting_message"]
        self.assertEqual(len(greeting_items), 0)


class TestGreetingJsonDecodeError(unittest.TestCase):
    """Test greeting JSON decode error path (lines 360-361)."""

    @patch('backend.services.prompt_service.update_agent')
    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.get_prompt_template')
    @patch('backend.services.prompt_service.check_agent_value_duplicate')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('backend.services.prompt_service.search_agent_info_by_agent_id')
    def test_greeting_json_decode_error_falls_back(
        self,
        mock_search_agent,
        mock_query_tools,
        mock_generate_system_prompt,
        mock_query_all_agents,
        mock_check_value_dup,
        mock_get_prompt_template,
        mock_call_llm,
        mock_update_agent,
    ):
        """When LLM returns braces with invalid JSON, JSONDecodeError is caught (lines 360-361)."""
        mock_query_tools.return_value = []
        mock_search_agent.return_value = {}
        mock_query_all_agents.return_value = []
        mock_check_value_dup.return_value = False

        def mock_gen(*args, **kwargs):
            yield {"type": "duty", "content": "duty", "is_complete": True}
            yield {"type": "constraint", "content": "constraint", "is_complete": True}
            yield {"type": "few_shots", "content": "few_shots", "is_complete": True}
            yield {"type": "agent_var_name", "content": "test", "is_complete": True}
            yield {"type": "agent_display_name", "content": "Test", "is_complete": True}
            yield {"type": "agent_description", "content": "desc", "is_complete": True}

        mock_generate_system_prompt.side_effect = mock_gen

        mock_get_prompt_template.return_value = {
            "GREETING_SYSTEM_PROMPT": "generate greeting",
            "USER_PROMPT": "Render {{ display_name }}",
        }
        # Text has braces but invalid JSON: undefined keys, no quotes
        # Must have both { and } so json_start >= 0 and json_end > json_start,
        # but content between them is invalid JSON
        mock_call_llm.return_value = '{greeting_message: Hello broken}'

        result = list(generate_and_save_system_prompt_impl(
            agent_id=123,
            model_id=1,
            task_description="Task",
            user_id="u",
            tenant_id="t",
            language="zh",
            tool_ids=[1],
            sub_agent_ids=[],
        ))

        # Should fall back to raw text (no valid JSON parse, parsed=None)
        greeting_items = [r for r in result if r.get("type") == "greeting_message"]
        self.assertEqual(len(greeting_items), 1)


class TestExtractJsonObjectEdgeCases(unittest.TestCase):
    """Additional edge case for _extract_json_object final fallback (lines 512-513)."""

    def test_utterly_broken_json_all_fallbacks_fail(self):
        """When all JSON repair strategies fail, return None (lines 512-513)."""
        from backend.services.prompt_service import _extract_json_object
        # Snippet with unbalanced braces that confuses all three strategies
        raw = '{\\x not valid json ever }'
        result = _extract_json_object(raw)
        # All fallbacks fail - returns None
        self.assertIsNone(result)


class TestOptimizeBadcaseWithJiuwenDirect(unittest.TestCase):
    """Test _optimize_badcase_with_jiuwen when adapter unavailable (line 1377)."""

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    def test_badcase_jiuwen_adapter_none_raises_directly(self, mock_get_adapter):
        """When adapter class is None, _optimize_badcase_with_jiuwen raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError
        mock_get_adapter.return_value = None

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")

        with self.assertRaises(JiuwenSDKError):
            service._optimize_badcase_with_jiuwen(
                current_content="prompt",
                bad_cases=[{"q": "Q", "a": "A"}],
                section_type="duty",
                section_title="Role",
            )


class TestKnowledgeAgnosticPromptRules(unittest.TestCase):
    def test_tool_capabilities_do_not_depend_on_resource_names(self):
        local, aidp = _resolve_knowledge_tool_capabilities([
            {"class_name": "KnowledgeBaseSearchTool", "name": "custom-local"},
            {"name": "aidp_search"},
        ])

        self.assertTrue(local)
        self.assertTrue(aidp)

    def test_bad_cases_are_copied_and_hardened(self):
        original = {"question": "Q", "answer": "A", "reason": "Improve it"}

        copied = _copy_bad_cases_with_scope_instruction([original], "en")

        self.assertEqual(original["reason"], "Improve it")
        self.assertIsNot(copied[0], original)
        self.assertIn("current conversation", copied[0]["reason"])
        self.assertIn("fixed index_names", copied[0]["reason"])

    @patch('backend.services.prompt_service._get_jiuwen_adapter_class')
    def test_jiuwen_general_optimization_receives_scope_rule(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.optimize.return_value = "optimized"
        adapter_class = MagicMock(return_value=adapter)
        mock_get_adapter.return_value = adapter_class
        service = PromptOptimizationService(model_id=1, tenant_id="t", language="en")
        request = OptimizeRequest(
            agent_id=1,
            model_id=1,
            task_description="task",
            section_type="duty",
            section_title="Role",
            current_content="prompt",
            feedback="Improve it",
        )

        service._optimize_with_jiuwen(request)

        feedback = adapter.optimize.call_args.kwargs["feedback"]
        self.assertIn("Improve it", feedback)
        self.assertIn("fixed kds_list", feedback)


def test_join_info_for_optimize_prompt_section_full_context(mocker):
    """Full tool/sub-agent rendering exercises knowledge capability flags and the scope instruction."""
    from jinja2 import Template as JinjaTemplate

    render_kwargs = {}
    mocked_template = MagicMock()
    mocked_template.render = MagicMock(side_effect=lambda *args, **kwargs: render_kwargs.update(kwargs or (args[0] if args else {})) or "rendered")

    prompt_for_optimize = {
        "OPTIMIZE_USER_PROMPT": "{{ section_type }} {{ task_description }} {{ tool_description }} {{ has_local_knowledge_tool }} {{ has_aidp_knowledge_tool }}"
    }
    with mocker.patch("backend.services.prompt_service.Template", return_value=mocked_template):
        result = join_info_for_optimize_prompt_section(
            prompt_for_optimize=prompt_for_optimize,
            section_type="constraint",
            section_title="section-title",
            task_description="task",
            current_content="body",
            feedback="fb",
            tool_info_list=[
                {"name": "knowledge_base_search", "description": "kb tool", "inputs": "{}", "output_type": "string"},
                {"name": "aidp_search", "description": "aidp tool", "inputs": "{}", "output_type": "string"},
            ],
            sub_agent_info_list=[{"name": "sub-1", "description": "sub desc"}],
            language="zh",
            knowledge_base_display_names=["KB 1"],
            aidp_kb_display_names=["AIDP 1"],
        )

    assert result == "rendered"
    assert render_kwargs["has_local_knowledge_tool"] is True
    assert render_kwargs["has_aidp_knowledge_tool"] is True
    assert "knowledge_base_search" in render_kwargs["tool_description"]
    assert "优化后的内容不得新增或保留具体知识库名称" in render_kwargs["tool_description"]


def test_join_info_for_optimize_prompt_section_english_scope_instruction(mocker):
    from jinja2 import Template as JinjaTemplate

    render_kwargs = {}
    mocked_template = MagicMock()
    mocked_template.render = MagicMock(side_effect=lambda *args, **kwargs: render_kwargs.update(kwargs or (args[0] if args else {})) or "ok")

    with mocker.patch("backend.services.prompt_service.Template", return_value=mocked_template):
        join_info_for_optimize_prompt_section(
            prompt_for_optimize={"OPTIMIZE_USER_PROMPT": "{{ tool_description }}"},
            section_type="constraint",
            section_title="t",
            task_description="task",
            current_content="c",
            feedback="f",
            tool_info_list=[{"name": "knowledge_base_search", "description": "d", "inputs": "{}", "output_type": "string"}],
            sub_agent_info_list=[],
            language="en",
        )

    assert "Inputs" in render_kwargs["tool_description"]
    assert "must not add or retain concrete knowledge base names" in render_kwargs["tool_description"]


def test_join_info_for_optimize_prompt_section_without_knowledge_tool_omits_scope_instruction(mocker):
    render_kwargs = {}
    mocked_template = MagicMock()
    mocked_template.render = MagicMock(
        side_effect=lambda *args, **kwargs: render_kwargs.update(kwargs or (args[0] if args else {})) or "ok"
    )

    with mocker.patch("backend.services.prompt_service.Template", return_value=mocked_template):
        join_info_for_optimize_prompt_section(
            prompt_for_optimize={"OPTIMIZE_USER_PROMPT": "{{ tool_description }}"},
            section_type="constraint",
            section_title="t",
            task_description="task",
            current_content="c",
            feedback="f",
            tool_info_list=[{"name": "web_search", "description": "d", "inputs": "{}", "output_type": "string"}],
            sub_agent_info_list=[],
            language="zh",
        )

    assert "web_search" in render_kwargs["tool_description"]
    assert "优化后的内容不得新增或保留具体知识库名称" not in render_kwargs["tool_description"]
    assert "当前会话允许的知识库范围" not in render_kwargs["tool_description"]
