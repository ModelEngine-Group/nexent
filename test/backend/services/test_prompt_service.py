import json
import unittest
from unittest.mock import patch, MagicMock

# Mock boto3 and minio client before importing the module under test
import sys
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

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

from backend.services.prompt_service import (
    generate_and_save_system_prompt_impl,
    gen_system_prompt_streamable,
    generate_system_prompt,
    join_info_for_generate_system_prompt
)


class TestPromptService(unittest.TestCase):

    def setUp(self):
        # Reset all mocks before each test
        minio_client_mock.reset_mock()
        self.test_model_id = 1

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

    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.query_all_agent_info_by_tenant_id')
    @patch('backend.services.prompt_service.get_enabled_sub_agent_description_for_generate_prompt')
    @patch('backend.services.prompt_service.get_enabled_tool_description_for_generate_prompt')
    def test_generate_and_save_system_prompt_impl_create_mode(
        self,
        mock_get_enabled_tools,
        mock_get_enabled_sub_agents,
        mock_query_all_agents,
        mock_generate_system_prompt,
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
            self.test_model_id,
            "zh"
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
            tool_ids=None,
            sub_agent_ids=None,
        )

        # Verify output format - should be SSE format
        self.assertEqual(len(result_list), 3)
        for i, result in enumerate(result_list):
            expected_data = f"data: {json.dumps({'success': True, 'data': test_data[i]}, ensure_ascii=False)}\n\n"
            self.assertEqual(result, expected_data)

    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.join_info_for_generate_system_prompt')
    @patch('backend.services.prompt_service.get_prompt_generate_prompt_template')
    def test_generate_system_prompt(self, mock_get_prompt_template, mock_join_info, mock_call_llm):
        # Setup
        mock_prompt_config = {
            "USER_PROMPT": "Test user prompt template",
            "DUTY_SYSTEM_PROMPT": "Generate duty prompt",
            "CONSTRAINT_SYSTEM_PROMPT": "Generate constraint prompt",
            "FEW_SHOTS_SYSTEM_PROMPT": "Generate few shots prompt",
            "AGENT_VARIABLE_NAME_SYSTEM_PROMPT": "Generate agent var name",
            "AGENT_DISPLAY_NAME_SYSTEM_PROMPT": "Generate agent display name",
            "AGENT_DESCRIPTION_SYSTEM_PROMPT": "Generate agent description"
        }
        mock_get_prompt_template.return_value = mock_prompt_config

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
            self.test_model_id,
            mock_language
        ):
            result_list.append(result)

        # Assert
        # Verify template loading
        mock_get_prompt_template.assert_called_once_with(mock_language)

        # Verify template joining
        mock_join_info.assert_called_once_with(
            prompt_for_generate=mock_prompt_config,
            sub_agent_info_list=mock_sub_agents,
            task_description=mock_task_description,
            tool_info_list=mock_tools,
            language=mock_language
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
    @patch('backend.services.prompt_service.get_prompt_generate_prompt_template')
    def test_generate_system_prompt_with_exception(self, mock_get_prompt_template, mock_join_info, mock_call_llm):
        # Setup
        mock_prompt_config = {
            "USER_PROMPT": "Test user prompt template",
            "DUTY_SYSTEM_PROMPT": "Generate duty prompt",
            "CONSTRAINT_SYSTEM_PROMPT": "Generate constraint prompt",
            "FEW_SHOTS_SYSTEM_PROMPT": "Generate few shots prompt",
            "AGENT_VARIABLE_NAME_SYSTEM_PROMPT": "Generate agent var name",
            "AGENT_DISPLAY_NAME_SYSTEM_PROMPT": "Generate agent display name",
            "AGENT_DESCRIPTION_SYSTEM_PROMPT": "Generate agent description"
        }
        mock_get_prompt_template.return_value = mock_prompt_config
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

        # Execute - should handle exceptions gracefully
        result_list = []
        for result in generate_system_prompt(
            mock_sub_agents,
            mock_task_description,
            mock_tools,
            mock_tenant_id,
            self.test_model_id,
            mock_language
        ):
            result_list.append(result)

        # Assert - should still return results for other prompt types
        self.assertGreater(len(result_list), 0)

        # Constraint should work fine
        constraint_results = [
            r for r in result_list if r["type"] == "constraint"]
        self.assertGreater(len(constraint_results), 0)

        # Verify that duty result exists but might be empty due to exception handling
        duty_results = [r for r in result_list if r["type"] == "duty"]

        # Should still have duty result entry with empty content
        self.assertGreater(len(duty_results), 0)

    @patch('backend.services.prompt_service.Template')
    def test_join_info_for_generate_system_prompt(self, mock_template):
        # Setup
        mock_prompt_for_generate = {"USER_PROMPT": "Test User Prompt"}
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
            mock_prompt_for_generate["USER_PROMPT"], undefined=StrictUndefined)
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


