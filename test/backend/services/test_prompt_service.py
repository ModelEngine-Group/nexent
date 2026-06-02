import json
import importlib.machinery
import types
import unittest
import json
import sys
from unittest.mock import patch, MagicMock

# Mock nexent module hierarchy BEFORE any backend imports that depend on it
nexent_mock = MagicMock()
nexent_core_mock = MagicMock()
nexent_core_agents_mock = MagicMock()
nexent_storage_mock = MagicMock()
nexent_storage_storage_client_factory_mock = MagicMock()
nexent_storage_minio_config_mock = MagicMock()
nexent_vector_database_mock = MagicMock()
nexent_memory_mock = MagicMock()
nexent_monitor_mock = MagicMock()

sys.modules['nexent'] = nexent_mock
sys.modules['nexent.core'] = nexent_core_mock
sys.modules['nexent.core.agents'] = nexent_core_agents_mock
sys.modules['nexent.storage'] = nexent_storage_mock
sys.modules['nexent.storage.storage_client_factory'] = nexent_storage_storage_client_factory_mock
sys.modules['nexent.storage.minio_config'] = nexent_storage_minio_config_mock
sys.modules['nexent.vector_database'] = nexent_vector_database_mock
sys.modules['nexent.memory'] = nexent_memory_mock
sys.modules['nexent.monitor'] = nexent_monitor_mock

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

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
minio_client_mock._ensure_bucket_exists = MagicMock()
minio_client_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()
patch('database.client.MinioClient', return_value=minio_client_mock).start()
patch('backend.database.client.minio_client', minio_client_mock).start()
patch('nexent.vector_database.elasticsearch_core.ElasticSearchCore', return_value=MagicMock()).start()
patch('nexent.vector_database.elasticsearch_core.Elasticsearch', return_value=MagicMock()).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

from jinja2 import StrictUndefined

# Mock database submodules BEFORE importing prompt_service
sys.modules['database'] = MagicMock()
sys.modules['database.agent_db'] = MagicMock()
sys.modules['database.tool_db'] = MagicMock()
sys.modules['database.model_management_db'] = MagicMock()
sys.modules['database.knowledge_db'] = MagicMock()
sys.modules['database.client'] = MagicMock()
sys.modules['database.db_models'] = MagicMock()

# Mock utils
sys.modules['utils'] = MagicMock()
sys.modules['utils.llm_utils'] = MagicMock()
sys.modules['utils.prompt_template_utils'] = MagicMock()

# Mock services
sys.modules['services'] = MagicMock()
sys.modules['services.agent_service'] = MagicMock()
sys.modules['services.prompt_template_service'] = MagicMock()

from backend.services.prompt_service import (
    generate_and_save_system_prompt_impl,
    gen_system_prompt_streamable,
    generate_system_prompt,
    join_info_for_generate_system_prompt,
    join_info_for_optimize_prompt_section,
    optimize_prompt_section_impl,
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
        self.assertEqual(template_vars["knowledge_base_names"], '"kb-a", "kb-b"')

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
            True,  # has_selected_resources
        )

    @patch('backend.services.prompt_service._regenerate_agent_display_name_with_llm')
    @patch('backend.services.prompt_service._regenerate_agent_name_with_llm')
    @patch('backend.services.prompt_service._check_agent_display_name_duplicate')
    @patch('backend.services.prompt_service._check_agent_name_duplicate')
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
        mock_check_name_dup,
        mock_check_display_dup,
        mock_regen_name,
        mock_regen_display,
    ):
        """Duplicate agent_var_name / agent_display_name should be regenerated via LLM helpers."""
        # Tool and sub-agent info do not matter for this test
        mock_query_tools.return_value = []
        mock_search_agent_info.return_value = {}
        mock_query_all_agents.return_value = [
            {"agent_id": 1, "name": "dup", "display_name": "Dup Display"}
        ]

        # Force duplicate detection
        mock_check_name_dup.return_value = True
        mock_check_display_dup.return_value = True

        # Regenerated values
        mock_regen_name.return_value = "regen_var"
        mock_regen_display.return_value = "Regen Display"

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

        mock_regen_name.assert_called_once()
        mock_regen_display.assert_called_once()

    @patch('backend.services.prompt_service._generate_unique_display_name_with_suffix')
    @patch('backend.services.prompt_service._generate_unique_agent_name_with_suffix')
    @patch('backend.services.prompt_service._regenerate_agent_display_name_with_llm')
    @patch('backend.services.prompt_service._regenerate_agent_name_with_llm')
    @patch('backend.services.prompt_service._check_agent_display_name_duplicate')
    @patch('backend.services.prompt_service._check_agent_name_duplicate')
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
        mock_check_name_dup,
        mock_check_display_dup,
        mock_regen_name,
        mock_regen_display,
        mock_generate_unique_name,
        mock_generate_unique_display,
    ):
        """When regeneration fails, duplicate names should fall back to suffix helpers."""
        mock_query_tools.return_value = []
        mock_search_agent_info.return_value = {}
        mock_query_all_agents.return_value = [
            {"agent_id": 1, "name": "dup", "display_name": "Dup Display"}
        ]

        mock_check_name_dup.return_value = True
        mock_check_display_dup.return_value = True

        # Force LLM regeneration failure
        mock_regen_name.side_effect = Exception("llm error")
        mock_regen_display.side_effect = Exception("llm error")

        mock_generate_unique_name.return_value = "uniq_var"
        mock_generate_unique_display.return_value = "Uniq Display"

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

        mock_generate_unique_name.assert_called_once()
        mock_generate_unique_display.assert_called_once()

    @patch('backend.services.prompt_service._check_agent_display_name_duplicate')
    @patch('backend.services.prompt_service._check_agent_name_duplicate')
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
        mock_check_name_dup,
        mock_check_display_dup,
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
        mock_check_name_dup.return_value = False
        mock_check_display_dup.return_value = False

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
        mock_check_name_dup.assert_called_once()
        mock_check_display_dup.assert_called_once()

    @patch('backend.services.prompt_service._check_agent_display_name_duplicate')
    @patch('backend.services.prompt_service._check_agent_name_duplicate')
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
        mock_check_name_dup,
        mock_check_display_dup,
    ):
        """Test agent_display_name path when is_complete is True and no duplicate (line 235)."""
        # Setup
        mock_query_tools.return_value = []
        mock_search_agent_info.return_value = {}
        mock_query_all_agents.return_value = []
        mock_check_name_dup.return_value = False
        mock_check_display_dup.return_value = False

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
        mock_check_display_dup.assert_called_once()

    @patch('backend.services.prompt_service._generate_unique_display_name_with_suffix')
    @patch('backend.services.prompt_service._regenerate_agent_display_name_with_llm')
    @patch('backend.services.prompt_service._check_agent_display_name_duplicate')
    @patch('backend.services.prompt_service._check_agent_name_duplicate')
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
        mock_check_name_dup,
        mock_check_display_dup,
        mock_regen_display,
        mock_generate_unique_display,
    ):
        """Test agent_display_name path when is_complete is True and duplicate exists, regenerates with LLM (line 235-250)."""
        # Setup
        mock_query_tools.return_value = []
        mock_search_agent_info.return_value = {}
        mock_query_all_agents.return_value = [{"display_name": "Test Agent", "agent_id": 999}]
        mock_check_name_dup.return_value = False
        mock_check_display_dup.return_value = True  # Duplicate exists
        mock_regen_display.return_value = "Regenerated Display Name"
        mock_generate_unique_display.return_value = "fallback_display_1"

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
        mock_check_display_dup.assert_called_once()
        mock_regen_display.assert_called_once()

    @patch('backend.services.prompt_service._generate_unique_display_name_with_suffix')
    @patch('backend.services.prompt_service._regenerate_agent_display_name_with_llm')
    @patch('backend.services.prompt_service._check_agent_display_name_duplicate')
    @patch('backend.services.prompt_service._check_agent_name_duplicate')
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
        mock_check_name_dup,
        mock_check_display_dup,
        mock_regen_display,
        mock_generate_unique_display,
    ):
        """Test agent_display_name path when is_complete is True, duplicate exists, LLM regeneration fails, uses fallback (line 235-250)."""
        # Setup
        mock_query_tools.return_value = []
        mock_search_agent_info.return_value = {}
        mock_query_all_agents.return_value = [{"display_name": "Test Agent", "agent_id": 999}]
        mock_check_name_dup.return_value = False
        mock_check_display_dup.return_value = True  # Duplicate exists
        mock_regen_display.side_effect = Exception("LLM failed")
        mock_generate_unique_display.return_value = "fallback_display_2"

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
        mock_check_display_dup.assert_called_once()
        mock_regen_display.assert_called_once()
        mock_generate_unique_display.assert_called_once()

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
        """Wrapper should fetch enabled tool IDs then query tool details."""
        from backend.services.prompt_service import get_enabled_tool_description_for_generate_prompt

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
        self.assertEqual(result, tools)

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

    @patch('backend.services.prompt_service._check_agent_display_name_duplicate')
    @patch('backend.services.prompt_service._check_agent_name_duplicate')
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
        mock_check_name_dup,
        mock_check_display_dup,
    ):
        """Test generate_and_save_system_prompt_impl raises exception when no content is generated (line 223)"""
        # Setup
        mock_query_tools.return_value = []
        mock_search_agent_info.return_value = {}
        mock_query_all_agents.return_value = []
        mock_check_name_dup.return_value = False
        mock_check_display_dup.return_value = False

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
        self.assertEqual(template_vars["knowledge_base_names"], '"redis", "kafka"')

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
        mock_get_knowledge_map.assert_called_once_with(["index-1", "index-2"])

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
        mock_get_knowledge_map.assert_called_once_with(["index-1", "index-2"])

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
        mock_get_knowledge_map.assert_called_once_with(["index-2"])

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
        self.assertEqual(render_args["knowledge_base_names"], '"kb1"')

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
                # has_selected_resources is passed positionally (10th arg), not as keyword
                call_args = mock_gen.call_args[0]
                self.assertIs(
                    call_args[9],
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
                # has_selected_resources is passed positionally (10th arg), not as keyword
                call_args = mock_gen.call_args[0]
                self.assertIs(
                    call_args[9],
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
                # has_selected_resources is passed positionally (10th arg), not as keyword
                call_args = mock_gen.call_args[0]
                self.assertIs(
                    call_args[9],
                    True,
                    "has_selected_resources should be True when sub-agents are present",
                )
