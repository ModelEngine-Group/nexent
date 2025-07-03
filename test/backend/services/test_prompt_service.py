import unittest
from unittest.mock import patch, MagicMock, mock_open, ANY
import queue

# Mock boto3 and minio client before importing the module under test
import sys
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Mock MinioClient class before importing the services
minio_client_mock = MagicMock()
with patch('backend.database.client.MinioClient', return_value=minio_client_mock):
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

    @patch('backend.services.prompt_service.OpenAIServerModel')
    @patch('backend.services.prompt_service.tenant_config_manager')
    @patch('backend.services.prompt_service.get_model_name_from_config')
    def test_call_llm_for_system_prompt(self, mock_get_model_name, mock_tenant_config, mock_openai):
        # Setup
        mock_model_config = {
            "base_url": "http://example.com",
            "api_key": "fake-key"
        }
        mock_tenant_config.get_model_config.return_value = mock_model_config
        mock_get_model_name.return_value = "gpt-4"
        
        mock_llm_instance = mock_openai.return_value
        
        # Mock the streaming response
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Generated prompt"
        
        # Set up the client.chat.completions.create mock
        mock_llm_instance.client = MagicMock()
        mock_llm_instance.client.chat.completions.create.return_value = [mock_chunk]
        mock_llm_instance._prepare_completion_kwargs.return_value = {}
        
        # Execute
        result = call_llm_for_system_prompt("user prompt", "system prompt")
        
        # Assert
        self.assertEqual(result, "Generated prompt")
        mock_openai.assert_called_once_with(
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
    def test_generate_and_save_system_prompt_impl(self, mock_update_agent, mock_get_user_info, 
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
        
        mock_generate_system_prompt.return_value = ["Generated prompt", "Final populated prompt"]
        
        # We need to use a generator since the function is a generator
        def mock_generator(*args, **kwargs):
            for prompt in mock_generate_system_prompt.return_value:
                yield prompt
        
        mock_generate_system_prompt.side_effect = mock_generator
        
        # Execute - test as a generator
        result_gen = generate_and_save_system_prompt_impl(123, "Test task", "fake-auth-token")
        result = list(result_gen)  # Convert generator to list for assertion
        
        # Assert
        self.assertEqual(result, mock_generate_system_prompt.return_value)
        mock_get_user_info.assert_called_once_with("fake-auth-token", None)
        mock_get_tool_desc.assert_called_once_with(tenant_id="tenant456", agent_id=123, user_id="user123")
        mock_get_agent_desc.assert_called_once_with(tenant_id="tenant456", agent_id=123, user_id="user123")
        
        mock_generate_system_prompt.assert_called_once_with(
            mock_get_agent_desc.return_value,
            "Test task",
            mock_get_tool_desc.return_value,
            "tenant456",
            "zh"
        )
        
        mock_update_agent.assert_called_once()
        agent_info = mock_update_agent.call_args[1]['agent_info']
        self.assertEqual(agent_info.agent_id, 123)
        self.assertEqual(agent_info.business_description, "Test task")
        self.assertEqual(agent_info.prompt, "Final populated prompt")
        # Verify call parameters
        mock_update_agent.assert_called_once_with(
            agent_id=123, 
            agent_info=ANY, 
            tenant_id="tenant456", 
            user_id="user123"
        )

    @patch('backend.services.prompt_service.generate_system_prompt')
    def test_generate_system_prompt(self, mock_generate_system_prompt):
        # Setup - create a simple generator function for the mock
        def mock_generator(*args, **kwargs):
            yield "Prompt 1"
            yield "Prompt 2" 
            yield "Final populated prompt"
            
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
        self.assertEqual(result, ["Prompt 1", "Prompt 2", "Final populated prompt"])
        mock_generate_system_prompt.assert_called_once_with(
            mock_sub_agents,
            mock_task_description,
            mock_tools,
            mock_tenant_id,
            mock_language
        )

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
    def test_get_enabled_tool_description_for_generate_prompt(self, mock_query_tools, mock_get_tool_ids):
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
    def test_get_enabled_sub_agent_description_for_generate_prompt(self, mock_query_sub_agents):
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
    def test_fine_tune_prompt(self, mock_yaml_load, mock_open_file, mock_call_llm):
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
        
    @patch('backend.services.prompt_service.OpenAIServerModel')
    @patch('backend.services.prompt_service.tenant_config_manager')
    @patch('backend.services.prompt_service.get_model_name_from_config')
    def test_call_llm_for_system_prompt_exception(self, mock_get_model_name, mock_tenant_config, mock_openai):
        # Setup
        mock_model_config = {
            "base_url": "http://example.com",
            "api_key": "fake-key"
        }
        mock_tenant_config.get_model_config.return_value = mock_model_config
        mock_get_model_name.return_value = "gpt-4"
        
        mock_llm_instance = mock_openai.return_value
        mock_llm_instance.client = MagicMock()
        mock_llm_instance.client.chat.completions.create.side_effect = Exception("LLM error")
        mock_llm_instance._prepare_completion_kwargs.return_value = {}
        
        # Execute and Assert
        with self.assertRaises(Exception) as context:
            call_llm_for_system_prompt("user prompt", "system prompt")
            
        self.assertTrue("LLM error" in str(context.exception))


if __name__ == '__main__':
    unittest.main()
