import unittest
from unittest.mock import patch, MagicMock, mock_open, ANY
import queue

# Mock boto3 and minio client before importing the module under test
import sys
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Mock ElasticSearch before importing other modules
elasticsearch_mock = MagicMock()
sys.modules['elasticsearch'] = elasticsearch_mock

# Mock MinioClient class before importing the services
minio_client_mock = MagicMock()
with patch('backend.database.client.MinioClient', return_value=minio_client_mock):
    with patch('nexent.vector_database.elasticsearch_core.ElasticSearchCore', return_value=MagicMock()):
        with patch('nexent.vector_database.elasticsearch_core.Elasticsearch', return_value=MagicMock()):
            from jinja2 import StrictUndefined

            from backend.services.prompt_service import (
                call_llm_for_system_prompt,
                generate_and_save_system_prompt_impl,
                get_enabled_tool_description_for_generate_prompt,
                get_enabled_sub_agent_description_for_generate_prompt,
                fine_tune_prompt,
                generate_system_prompt,
                join_info_for_generate_system_prompt
            )
            from backend.consts.model import AgentInfoRequest


class TestPromptService(unittest.TestCase):
    
    def setUp(self):
        # Reset all mocks before each test
        minio_client_mock.reset_mock()

    @patch('backend.services.prompt_service.OpenAIModel')
    @patch('backend.services.prompt_service.tenant_config_manager')
    @patch('backend.services.prompt_service.get_model_name_from_config')
    @patch('backend.services.prompt_service.get_model_factory_type')
    def test_call_llm_for_system_prompt(self, mock_get_model_factory_type, mock_get_model_name, mock_tenant_config, mock_openai):
        # Setup
        mock_model_config = {
            "base_url": "http://example.com",
            "api_key": "fake-key"
        }
        mock_tenant_config.get_model_config.return_value = mock_model_config
        mock_get_model_name.return_value = "gpt-4"
        mock_get_model_factory_type.return_value = "openai"  # Use OpenAI model, not restful
        
        # Mock the LLM instance and its response
        mock_llm_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Generated prompt"
        mock_llm_instance.return_value = mock_response
        mock_openai.return_value = mock_llm_instance
        
        # Execute
        result = call_llm_for_system_prompt("user prompt", "system prompt")
        
        # Assert
        self.assertEqual(result, "Generated prompt")
        mock_openai.assert_called_once_with(
            observer=ANY,  # Using ANY because observer is complex to mock
            model_id="gpt-4",
            api_base="http://example.com",
            api_key="fake-key",
            temperature=0.3,
            top_p=0.95
        )
        
    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('backend.services.prompt_service.get_enabled_sub_agent_description_for_generate_prompt')
    @patch('backend.services.prompt_service.get_enabled_tool_description_for_generate_prompt')
    @patch('backend.services.prompt_service.get_current_user_info')
    @patch('backend.services.prompt_service.update_agent')
    @patch('nexent.vector_database.elasticsearch_core.ElasticSearchCore')
    @patch('elasticsearch.Elasticsearch')
    def test_generate_and_save_system_prompt_impl(self, mock_elasticsearch, mock_es_core, mock_update_agent, mock_get_user_info, 
                                         mock_get_tool_desc, mock_get_agent_desc, 
                                         mock_generate_system_prompt):
        # Setup
        mock_get_user_info.return_value = ("user123", "tenant456", "zh")
        
        mock_tool1 = {"name": "tool1", "description": "Tool 1 desc", "inputs": "input1", "output_type": "output1"}
        mock_tool2 = {"name": "tool2", "description": "Tool 2 desc", "inputs": "input2", "output_type": "output2"}
        mock_get_tool_desc.return_value = [mock_tool1, mock_tool2]
        
        mock_agent1 = {"name": "agent1", "description": "Agent 1 desc", "enabled": True}
        mock_agent2 = {"name": "agent2", "description": "Agent 2 desc", "enabled": True}
        mock_get_agent_desc.return_value = [mock_agent1, mock_agent2]
        
        # Mock the generator to return the expected data structure
        def mock_generator(*args, **kwargs):
            yield {"type": "duty", "content": "Generated duty prompt", "is_complete": False}
            yield {"type": "constraint", "content": "Generated constraint prompt", "is_complete": False}
            yield {"type": "few_shots", "content": "Generated few shots prompt", "is_complete": False}
            yield {"type": "duty", "content": "Final duty prompt", "is_complete": True}
            yield {"type": "constraint", "content": "Final constraint prompt", "is_complete": True}
            yield {"type": "few_shots", "content": "Final few shots prompt", "is_complete": True}
        
        mock_generate_system_prompt.side_effect = mock_generator
        
        # Execute - test as a generator
        result_gen = generate_and_save_system_prompt_impl(123, "Test task", "fake-auth-token")
        result = list(result_gen)  # Convert generator to list for assertion
        
        # Assert
        expected_results = [
            {"type": "duty", "content": "Generated duty prompt", "is_complete": False},
            {"type": "constraint", "content": "Generated constraint prompt", "is_complete": False},
            {"type": "few_shots", "content": "Generated few shots prompt", "is_complete": False},
            {"type": "duty", "content": "Final duty prompt", "is_complete": True},
            {"type": "constraint", "content": "Final constraint prompt", "is_complete": True},
            {"type": "few_shots", "content": "Final few shots prompt", "is_complete": True}
        ]
        self.assertEqual(result, expected_results)
        
        mock_get_user_info.assert_called_once_with("fake-auth-token", None)
        mock_get_tool_desc.assert_called_once_with(agent_id=123, tenant_id="tenant456", user_id="user123")
        mock_get_agent_desc.assert_called_once_with(agent_id=123, tenant_id="tenant456", user_id="user123")
        
        mock_generate_system_prompt.assert_called_once_with(
            mock_get_agent_desc.return_value,
            "Test task",
            mock_get_tool_desc.return_value,
            "tenant456",
            "zh"
        )
        
        # Verify update_agent was called with the correct parameters
        mock_update_agent.assert_called_once()
        call_args = mock_update_agent.call_args
        self.assertEqual(call_args[1]['agent_id'], 123)
        self.assertEqual(call_args[1]['tenant_id'], "tenant456")
        self.assertEqual(call_args[1]['user_id'], "user123")
        
        # Verify the agent_info object has the correct structure
        agent_info = call_args[1]['agent_info']
        self.assertEqual(agent_info.agent_id, 123)
        self.assertEqual(agent_info.business_description, "Test task")
        self.assertEqual(agent_info.duty_prompt, "Final duty prompt")
        self.assertEqual(agent_info.constraint_prompt, "Final constraint prompt")
        self.assertEqual(agent_info.few_shots_prompt, "Final few shots prompt")

    @patch('backend.services.prompt_service.generate_system_prompt')
    @patch('nexent.vector_database.elasticsearch_core.ElasticSearchCore')
    @patch('elasticsearch.Elasticsearch')
    def test_generate_system_prompt(self, mock_elasticsearch, mock_es_core, mock_generate_system_prompt):
        # Setup - create a generator function that returns the expected data structure
        def mock_generator(*args, **kwargs):
            yield {"type": "duty", "content": "Duty prompt", "is_complete": False}
            yield {"type": "constraint", "content": "Constraint prompt", "is_complete": False}
            yield {"type": "few_shots", "content": "Few shots prompt", "is_complete": False}
            yield {"type": "duty", "content": "Final duty prompt", "is_complete": True}
            yield {"type": "constraint", "content": "Final constraint prompt", "is_complete": True}
            yield {"type": "few_shots", "content": "Final few shots prompt", "is_complete": True}
            
        mock_generate_system_prompt.side_effect = mock_generator
        
        # Test data
        mock_sub_agents = [{"name": "agent1", "description": "Agent 1"}]
        mock_task_description = "Test task"
        mock_tools = [{"name": "tool1", "description": "Tool 1"}]
        mock_tenant_id = "test_tenant"
        mock_language = "en"
        
        # Execute
        from backend.services.prompt_service import generate_system_prompt as original_generate
        result = list(original_generate(
            mock_sub_agents,
            mock_task_description,
            mock_tools,
            mock_tenant_id,
            mock_language
        ))
        
        # Assert
        expected_results = [
            {"type": "duty", "content": "Duty prompt", "is_complete": False},
            {"type": "constraint", "content": "Constraint prompt", "is_complete": False},
            {"type": "few_shots", "content": "Few shots prompt", "is_complete": False},
            {"type": "duty", "content": "Final duty prompt", "is_complete": True},
            {"type": "constraint", "content": "Final constraint prompt", "is_complete": True},
            {"type": "few_shots", "content": "Final few shots prompt", "is_complete": True}
        ]
        self.assertEqual(result, expected_results)
        mock_generate_system_prompt.assert_called_once_with(
            mock_sub_agents,
            mock_task_description,
            mock_tools,
            mock_tenant_id,
            mock_language
        )

    @patch('backend.services.prompt_service.Template')
    @patch('nexent.vector_database.elasticsearch_core.ElasticSearchCore')
    @patch('elasticsearch.Elasticsearch')
    def test_join_info_for_generate_system_prompt(self, mock_elasticsearch, mock_es_core, mock_template):
        # Setup
        mock_prompt_for_generate = {"USER_PROMPT": "Test User Prompt"}
        mock_sub_agents = [
            {"name": "agent1", "description": "Agent 1 desc"},
            {"name": "agent2", "description": "Agent 2 desc"}
        ]
        mock_task_description = "Test task"
        mock_tools = [
            {"name": "tool1", "description": "Tool 1 desc", "inputs": "input1", "output_type": "output1"},
            {"name": "tool2", "description": "Tool 2 desc", "inputs": "input2", "output_type": "output2"}
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
        mock_template.assert_called_once_with(mock_prompt_for_generate["USER_PROMPT"], undefined=StrictUndefined)
        mock_template_instance.render.assert_called_once()
        # Check template variables
        template_vars = mock_template_instance.render.call_args[0][0]
        self.assertTrue("tool_description" in template_vars)
        self.assertTrue("agent_description" in template_vars)
        self.assertEqual(template_vars["task_description"], mock_task_description)
        
    @patch('backend.services.prompt_service.get_enable_tool_id_by_agent_id')
    @patch('backend.services.prompt_service.query_tools_by_ids')
    @patch('nexent.vector_database.elasticsearch_core.ElasticSearchCore')
    @patch('elasticsearch.Elasticsearch')
    def test_get_enabled_tool_description_for_generate_prompt(self, mock_elasticsearch, mock_es_core, mock_query_tools, mock_get_tool_ids):
        # Setup
        mock_get_tool_ids.return_value = [1, 2, 3]
        mock_tools = [{"id": 1, "name": "tool1"}, {"id": 2, "name": "tool2"}, {"id": 3, "name": "tool3"}]
        mock_query_tools.return_value = mock_tools
        
        # Execute
        result = get_enabled_tool_description_for_generate_prompt(
            agent_id=123, 
            tenant_id="tenant456", 
            user_id="user123"
        )
        
        # Assert
        self.assertEqual(result, mock_tools)
        mock_get_tool_ids.assert_called_once_with(agent_id=123, tenant_id="tenant456", user_id="user123")
        mock_query_tools.assert_called_once_with([1, 2, 3])
        
    @patch('backend.services.prompt_service.query_sub_agents')
    @patch('nexent.vector_database.elasticsearch_core.ElasticSearchCore')
    @patch('elasticsearch.Elasticsearch')
    def test_get_enabled_sub_agent_description_for_generate_prompt(self, mock_elasticsearch, mock_es_core, mock_query_sub_agents):
        # Setup
        mock_agents = [
            {"id": 1, "name": "agent1", "enabled": True},
            {"id": 2, "name": "agent2", "enabled": False},  # This one should be filtered out
            {"id": 3, "name": "agent3", "enabled": True}
        ]
        mock_query_sub_agents.return_value = mock_agents
        
        # Execute
        result = get_enabled_sub_agent_description_for_generate_prompt(
            agent_id=123, 
            tenant_id="tenant456", 
            user_id="user123"
        )
        
        # Assert
        expected_result = [
            {"id": 1, "name": "agent1", "enabled": True},
            {"id": 3, "name": "agent3", "enabled": True}
        ]
        self.assertEqual(result, expected_result)
        mock_query_sub_agents.assert_called_once_with(main_agent_id=123, tenant_id="tenant456", user_id="user123")
        
    @patch('backend.services.prompt_service.call_llm_for_system_prompt')
    @patch('backend.services.prompt_service.open', new_callable=mock_open, read_data="""
FINE_TUNE_USER_PROMPT: "Test Fine Tune User Prompt {{prompt}} {{command}}"
FINE_TUNE_SYSTEM_PROMPT: "Fine Tune System Prompt"
""")
    @patch('backend.services.prompt_service.yaml.safe_load')
    @patch('nexent.vector_database.elasticsearch_core.ElasticSearchCore')
    @patch('elasticsearch.Elasticsearch')
    def test_fine_tune_prompt(self, mock_elasticsearch, mock_es_core, mock_yaml_load, mock_open_file, mock_call_llm):
        # Setup
        mock_yaml_data = {
            "FINE_TUNE_USER_PROMPT": "Test Fine Tune User Prompt {{prompt}} {{command}}",
            "FINE_TUNE_SYSTEM_PROMPT": "Fine Tune System Prompt"
        }
        mock_yaml_load.return_value = mock_yaml_data
        mock_call_llm.return_value = "Fine-tuned prompt result"
        
        # Execute
        result = fine_tune_prompt("Original prompt", "Command", tenant_id="test_tenant")
        
        # Assert
        self.assertEqual(result, "Fine-tuned prompt result")
        mock_call_llm.assert_called_once_with(
            user_prompt=ANY,  # Using ANY because the Template.render() result is complex to reproduce
            system_prompt="Fine Tune System Prompt",
            tenant_id="test_tenant"
        )

    @patch('backend.services.prompt_service.OpenAIModel')
    @patch('backend.services.prompt_service.tenant_config_manager')
    @patch('backend.services.prompt_service.get_model_name_from_config')
    @patch('backend.services.prompt_service.get_model_factory_type')
    def test_call_llm_for_system_prompt_exception(self, mock_get_model_factory_type, mock_get_model_name, mock_tenant_config, mock_openai):
        # Setup
        mock_model_config = {
            "base_url": "http://example.com",
            "api_key": "fake-key"
        }
        mock_tenant_config.get_model_config.return_value = mock_model_config
        mock_get_model_name.return_value = "gpt-4"
        mock_get_model_factory_type.return_value = "openai"
        
        # Mock the LLM instance to raise an exception
        mock_llm_instance = MagicMock()
        mock_llm_instance.side_effect = Exception("LLM error")
        mock_openai.return_value = mock_llm_instance
        
        # Execute and Assert
        with self.assertRaises(Exception) as context:
            call_llm_for_system_prompt("user prompt", "system prompt")
            
        self.assertTrue("LLM error" in str(context.exception))


if __name__ == '__main__':
    unittest.main()
