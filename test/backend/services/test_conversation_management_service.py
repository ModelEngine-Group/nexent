import sys
import types
from unittest.mock import patch

# Mock storage client factory and MinIO config before any imports that would initialize MinIO
from unittest.mock import MagicMock
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()

# Mock boto3 before any imports
boto3_mock = types.SimpleNamespace()
sys.modules['boto3'] = boto3_mock

def _stub_nexent_openai_model():
    # Provide a simple OpenAIModel stub for import-time safety
    mod = types.ModuleType("nexent.core.models")
    class Stub:
        def __init__(self, *a, **k):
            self.generated = None
        def generate(self, messages):
            # record messages for assertion and return object with content
            self.generated = messages
            return types.SimpleNamespace(content="The Title")
    mod.OpenAIModel = Stub
    sys.modules["nexent.core.models"] = mod

_stub_nexent_openai_model()

# Stub jinja2 to avoid importing the dependency during tests
jinja2_mod = types.ModuleType("jinja2")
class StrictUndefined:
    pass
class Template:
    def __init__(self, text, undefined=None):
        self.text = text
    def render(self, ctx):
        # very small render: replace {{content}} occurrence
        return self.text.replace("{{content}}", ctx.get("content", ""))
jinja2_mod.StrictUndefined = StrictUndefined
jinja2_mod.Template = Template
sys.modules["jinja2"] = jinja2_mod
# Stub nexent.core.agents.agent_model to satisfy imports in consts.model
agent_model_mod = types.ModuleType("nexent.core.agents.agent_model")
agent_model_mod.ToolConfig = object
sys.modules["nexent.core.agents"] = types.ModuleType("nexent.core.agents")
sys.modules["nexent.core.agents.agent_model"] = agent_model_mod
# Stub nexent.core.utils.observer ProcessType and MessageObserver used by conversation service
observer_mod = types.ModuleType("nexent.core.utils.observer")
observer_mod.MessageObserver = lambda *a, **k: types.SimpleNamespace(add_model_new_token=lambda t: None, add_model_reasoning_content=lambda r: None, flush_remaining_tokens=lambda: None)
observer_mod.ProcessType = types.SimpleNamespace(MODEL_OUTPUT_CODE=types.SimpleNamespace(value="model_output_code"), MODEL_OUTPUT_THINKING=types.SimpleNamespace(value="model_output_thinking"))
sys.modules["nexent.core.utils.observer"] = observer_mod

# Stub nexent.core.models.embedding_model to avoid import errors
embedding_mod = types.ModuleType("nexent.core.models.embedding_model")
embedding_mod.BaseEmbedding = object
embedding_mod.OpenAICompatibleEmbedding = object
embedding_mod.JinaEmbedding = object
sys.modules["nexent.core.models.embedding_model"] = embedding_mod
#
# Stub consts.model to avoid pydantic/email-validator heavy imports during tests.
consts_model_mod = types.ModuleType("consts.model")
class AgentRequest:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
class ConversationResponse:
    def __init__(self, code=0, message="", data=None):
        self.code = code
        self.message = message
        self.data = data
class MessageUnit:
    def __init__(self, type="", content=""):
        self.type = type
        self.content = content
class MessageRequest:
    def __init__(self, conversation_id=None, message_idx=None, role=None, message=None, minio_files=None):
        self.conversation_id = conversation_id
        self.message_idx = message_idx
        self.role = role
        self.message = message
        self.minio_files = minio_files
    def model_dump(self):
        return {
            "conversation_id": self.conversation_id,
            "message_idx": self.message_idx,
            "role": self.role,
            "message": [m.__dict__ if hasattr(m, "__dict__") else m for m in (self.message or [])],
            "minio_files": self.minio_files,
        }

consts_model_mod.AgentRequest = AgentRequest
consts_model_mod.ConversationResponse = ConversationResponse
consts_model_mod.MessageUnit = MessageUnit
consts_model_mod.MessageRequest = MessageRequest
sys.modules["consts.model"] = consts_model_mod
# Also ensure backend.consts.model resolves to our stub for tests that import via backend.consts.model
sys.modules["backend.consts.model"] = consts_model_mod

# Stub database.client to avoid import-time DB helpers
db_client_stub = types.ModuleType("database.client")
db_client_stub.as_dict = lambda obj: {}

# Minimal dummy db_client with clean_string_values and session_maker to satisfy imports.
db_client_stub.db_client = types.SimpleNamespace(
    clean_string_values=lambda d: d,
    session_maker=lambda: None
)

# Provide a simple context manager compatible get_db_session used with `with get_db_session() as session:`
class _DummySessionCM:
    def __enter__(self):
        # Return a minimal session-like object with methods used in tests (execute, scalars, commit/rollback/close)
        return types.SimpleNamespace(
            execute=lambda *a, **k: types.SimpleNamespace(rowcount=0),
            scalars=lambda *a, **k: types.SimpleNamespace(all=lambda: []),
            commit=lambda: None,
            rollback=lambda: None,
            close=lambda: None,
        )

    def __exit__(self, exc_type, exc, tb):
        return False

db_client_stub.get_db_session = lambda *a, **k: _DummySessionCM()
sys.modules["database.client"] = db_client_stub

# Stub utils.prompt_template_utils to avoid requiring PyYAML
prompt_mod = types.ModuleType("utils.prompt_template_utils")
prompt_mod.get_generate_title_prompt_template = lambda language="zh": {"USER_PROMPT":"{{question}}", "SYSTEM_PROMPT":"SYS"}
sys.modules["utils.prompt_template_utils"] = prompt_mod


from backend.consts.model import MessageRequest, AgentRequest, MessageUnit
import unittest
import json
import asyncio
import os
from datetime import datetime
from unittest.mock import patch, MagicMock

# Environment variables are now configured in conftest.py

with patch('backend.database.client.MinioClient', return_value=minio_client_mock):
    from backend.services.conversation_management_service import (
        save_message,
        save_conversation_user,
        save_conversation_assistant,
        call_llm_for_title,
        update_conversation_title,
        create_new_conversation,
        get_conversation_list_service,
        rename_conversation_service,
        delete_conversation_service,
        get_conversation_history_service,
        get_sources_service,
        generate_conversation_title_service,
        update_message_opinion_service,
        get_message_id_by_index_impl
    )


class TestConversationManagementService(unittest.TestCase):
    def setUp(self):
        """
        Set up test data and reset all mocks before each test.
        """
        self.tenant_id = "test_tenant_id"
        self.user_id = "test_user_id"

        # Reset all mocks before each test
        minio_client_mock.reset_mock()

    @patch('backend.services.conversation_management_service.create_conversation_message')
    @patch('backend.services.conversation_management_service.create_source_image')
    def test_save_message_picture_web_invalid_json(self, mock_create_image, mock_create_msg):
        mock_create_msg.return_value = 1
        message_request = MessageRequest(
            conversation_id=456,
            message_idx=99,
            role="assistant",
            message=[MessageUnit(type="picture_web", content="not a valid json")],
            minio_files=[]
        )
        result = save_message(
            message_request, user_id=self.user_id, tenant_id=self.tenant_id)
        self.assertEqual(result.code, 0)
        mock_create_image.assert_not_called()

    def test_get_sources_service_no_id(self):
        """Should return error when both conversation_id and message_id are None."""
        result = get_sources_service(None, None, user_id=self.user_id)
        self.assertEqual(result['code'], 400)
        self.assertEqual(result['message'], "Must provide conversation_id or message_id parameter")

    @patch('backend.services.conversation_management_service.create_conversation_message')
    @patch('backend.services.conversation_management_service.create_source_search')
    @patch('backend.services.conversation_management_service.create_source_image')
    @patch('backend.services.conversation_management_service.create_message_units')
    def test_save_message_with_string_content(self, mock_create_message_units, mock_create_source_image,
                                              mock_create_source_search, mock_create_conversation_message):
        # Setup
        mock_create_conversation_message.return_value = 123  # message_id

        # Create message request with string content
        message_request = MessageRequest(
            conversation_id=456,
            message_idx=1,
            role="user",
            message=[MessageUnit(
                type="string", content="Hello, this is a test message")],
            minio_files=[]
        )

        # Execute
        result = save_message(
            message_request, user_id=self.user_id, tenant_id=self.tenant_id)

        # Assert
        self.assertEqual(result.code, 0)
        self.assertEqual(result.message, "success")
        self.assertTrue(result.data)

        # Check if create_conversation_message was called with correct params
        mock_create_conversation_message.assert_called_once()
        call_args = mock_create_conversation_message.call_args[0][0]
        self.assertEqual(call_args['conversation_id'], 456)
        self.assertEqual(call_args['message_idx'], 1)
        self.assertEqual(call_args['role'], "user")
        self.assertEqual(call_args['content'], "Hello, this is a test message")

        # Check that other methods were not called
        mock_create_message_units.assert_not_called()
        mock_create_source_image.assert_not_called()
        mock_create_source_search.assert_not_called()

    @patch('backend.services.conversation_management_service.create_conversation_message')
    @patch('backend.services.conversation_management_service.create_source_search')
    @patch('backend.services.conversation_management_service.create_message_units')
    def test_save_message_with_search_content(self, mock_create_message_units, mock_create_source_search,
                                              mock_create_conversation_message):
        # Setup
        mock_create_conversation_message.return_value = 123  # message_id

        # Create message with search content
        search_content = json.dumps([{
            "source_type": "web",
            "title": "Test Result",
            "url": "https://example.com",
            "text": "Example search result",
            "score": "0.95",
            "score_details": {"accuracy": "0.9", "semantic": "0.8"},
            "published_date": "2023-01-15",
            "cite_index": 1,
            "search_type": "web_search",
            "tool_sign": "web_search"
        }])

        message_request = MessageRequest(
            conversation_id=456,
            message_idx=2,
            role="assistant",
            message=[
                MessageUnit(type="string",
                            content="Here are the search results"),
                MessageUnit(type="search_content", content=search_content)
            ],
            minio_files=[]
        )

        # Execute
        result = save_message(
            message_request, user_id=self.user_id, tenant_id=self.tenant_id)

        # Assert
        self.assertEqual(result.code, 0)
        self.assertTrue(result.data)

        # Check correct message was created
        mock_create_conversation_message.assert_called_once()
        call_args = mock_create_conversation_message.call_args[0][0]
        self.assertEqual(call_args['content'], "Here are the search results")

        # Check search content was saved
        mock_create_source_search.assert_called_once()
        search_data = mock_create_source_search.call_args[0][0]
        self.assertEqual(search_data['message_id'], 123)
        self.assertEqual(search_data['conversation_id'], 456)
        self.assertEqual(search_data['source_type'], "web")
        self.assertEqual(search_data['score_overall'], 0.95)

        # Check message units were created with placeholder
        mock_create_message_units.assert_called_once()
        units = mock_create_message_units.call_args[0][0]
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]['type'], 'search_content_placeholder')

    @patch('backend.services.conversation_management_service.create_conversation_message')
    @patch('backend.services.conversation_management_service.create_source_image')
    @patch('backend.services.conversation_management_service.create_message_units')
    def test_save_message_with_picture_web(self, mock_create_message_units, mock_create_source_image, mock_create_conversation_message):
        """Ensure picture_web units trigger create_source_image and not message_units creation."""
        # Setup
        mock_create_conversation_message.return_value = 789  # message_id

        images_payload = json.dumps({
            "images_url": [
                "https://example.com/img1.jpg",
                "https://example.com/img2.jpg"
            ]
        })

        message_request = MessageRequest(
            conversation_id=456,
            message_idx=3,
            role="assistant",
            message=[
                MessageUnit(type="string", content="Here are some images"),
                MessageUnit(type="picture_web", content=images_payload)
            ],
            minio_files=[]
        )

        # Execute
        result = save_message(
            message_request, user_id=self.user_id, tenant_id=self.tenant_id)

        # Assert base result
        self.assertEqual(result.code, 0)
        self.assertTrue(result.data)

        # create_conversation_message called once
        mock_create_conversation_message.assert_called_once()
        # create_source_image called twice for two images
        self.assertEqual(mock_create_source_image.call_count, 2)
        calls = mock_create_source_image.call_args_list
        called_urls = [call.args[0]['image_url'] for call in calls]
        self.assertIn("https://example.com/img1.jpg", called_urls)
        self.assertIn("https://example.com/img2.jpg", called_urls)
        # ensure conversation_id and message_id in payload
        for call in calls:
            payload = call.args[0]
            self.assertEqual(payload['conversation_id'], 456)
            self.assertEqual(payload['message_id'], 789)

        # create_message_units should not be called for picture_web
        mock_create_message_units.assert_not_called()

    @patch('backend.services.conversation_management_service.save_message')
    def test_save_conversation_user(self, mock_save_message):
        # Setup
        agent_request = AgentRequest(
            conversation_id=123,
            query="What is machine learning?",
            minio_files=[],
            history=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"}
            ]
        )

        # Execute
        save_conversation_user(agent_request, self.user_id, self.tenant_id)

        # Assert
        mock_save_message.assert_called_once()
        request_arg = mock_save_message.call_args[0][0]
        self.assertEqual(request_arg.conversation_id, 123)
        # Based on 1 user message in history
        self.assertEqual(request_arg.message_idx, 2)
        self.assertEqual(request_arg.role, "user")
        self.assertEqual(request_arg.message[0].type, "string")
        self.assertEqual(
            request_arg.message[0].content, "What is machine learning?")

    @patch('backend.services.conversation_management_service.save_message')
    def test_save_conversation_assistant(self, mock_save_message):
        # Setup
        agent_request = AgentRequest(
            conversation_id=123,
            query="What is machine learning?",
            minio_files=[],
            history=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"}
            ]
        )

        messages = [
            json.dumps({"type": "model_output_thinking",
                       "content": "Machine learning is "}),
            json.dumps({"type": "model_output_thinking",
                       "content": "a field of AI"})
        ]

        # Execute
        save_conversation_assistant(
            agent_request, messages, self.user_id, self.tenant_id)

        # Assert
        mock_save_message.assert_called_once()
        request_arg = mock_save_message.call_args[0][0]
        self.assertEqual(request_arg.conversation_id, 123)
        # Based on 1 user message in history + current
        self.assertEqual(request_arg.message_idx, 3)
        self.assertEqual(request_arg.role, "assistant")
        # Check that consecutive model_output_thinking messages were merged
        self.assertEqual(len(request_arg.message), 1)
        first_unit = request_arg.message[0]
        unit_type = getattr(first_unit, "type", None) or (first_unit.get("type") if isinstance(first_unit, dict) else None)
        self.assertEqual(unit_type, "model_output_thinking")
        first_unit = request_arg.message[0]
        unit_content = getattr(first_unit, "content", None) or (first_unit.get("content") if isinstance(first_unit, dict) else None)
        self.assertEqual(unit_content, "Machine learning is a field of AI")

    @patch('backend.services.conversation_management_service.OpenAIModel')
    @patch('backend.services.conversation_management_service.get_generate_title_prompt_template')
    @patch('backend.services.conversation_management_service.tenant_config_manager.get_model_config')
    def test_call_llm_for_title(self, mock_get_model_config, mock_get_prompt_template, mock_openai):
        # Setup
        mock_get_model_config.return_value = {
            "model_name": "gpt-4",
            "model_repo": "openai",
            "base_url": "http://example.com",
            "api_key": "fake-key"
        }

        mock_prompt_template = {
            "SYSTEM_PROMPT": "Generate a short title",
            "USER_PROMPT": "Generate a title for: {{question}}"
        }
        mock_get_prompt_template.return_value = mock_prompt_template

        mock_llm_instance = mock_openai.return_value
        mock_response = MagicMock()
        mock_response.content = "AI Discussion"
        mock_llm_instance.generate.return_value = mock_response

        # Execute
        result = call_llm_for_title(
            "What is AI? AI stands for Artificial Intelligence.", tenant_id=self.tenant_id)

        # Assert
        self.assertEqual(result, "AI Discussion")
        mock_openai.assert_called_once()
        mock_llm_instance.generate.assert_called_once()
        mock_get_prompt_template.assert_called_once_with(language='zh')

    @patch('backend.services.conversation_management_service.rename_conversation')
    def test_update_conversation_title(self, mock_rename_conversation):
        # Setup
        mock_rename_conversation.return_value = True

        # Execute
        result = update_conversation_title(123, "New Title", self.user_id)

        # Assert
        self.assertTrue(result)
        mock_rename_conversation.assert_called_once_with(
            123, "New Title", self.user_id)

    @patch('backend.services.conversation_management_service.create_conversation')
    def test_create_new_conversation(self, mock_create_conversation):
        # Setup
        mock_create_conversation.return_value = {
            "conversation_id": 123, "title": "New Chat", "create_time": "2023-04-01"}

        # Execute
        result = create_new_conversation("New Chat", self.user_id)

        # Assert
        self.assertEqual(result["conversation_id"], 123)
        self.assertEqual(result["title"], "New Chat")
        mock_create_conversation.assert_called_once_with(
            "New Chat", self.user_id)

    @patch('backend.services.conversation_management_service.get_conversation_list')
    def test_get_conversation_list_service(self, mock_get_conversation_list):
        # Setup
        mock_conversations = [
            {"conversation_id": 1, "title": "Chat 1", "create_time": "2023-04-01"},
            {"conversation_id": 2, "title": "Chat 2", "create_time": "2023-04-02"}
        ]
        mock_get_conversation_list.return_value = mock_conversations

        # Execute
        result = get_conversation_list_service(self.user_id)

        # Assert
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["conversation_id"], 1)
        self.assertEqual(result[1]["title"], "Chat 2")
        mock_get_conversation_list.assert_called_once_with(self.user_id)

    @patch('backend.services.conversation_management_service.rename_conversation')
    def test_rename_conversation_service(self, mock_rename_conversation):
        # Setup
        mock_rename_conversation.return_value = True

        # Execute
        rename_conversation_service(123, "Updated Title", self.user_id)

        # Assert
        mock_rename_conversation.assert_called_once_with(
            123, "Updated Title", self.user_id)

    @patch('backend.services.conversation_management_service.delete_conversation')
    def test_delete_conversation_service(self, mock_delete_conversation):
        # Setup
        mock_delete_conversation.return_value = True

        # Execute
        delete_conversation_service(123, self.user_id)

        # Assert
        mock_delete_conversation.assert_called_once_with(123, self.user_id)

    @patch('backend.services.conversation_management_service.get_conversation_history')
    def test_get_conversation_history_service(self, mock_get_conversation_history):
        # Setup
        mock_history = {
            "conversation_id": 123,
            "create_time": "2023-04-01",
            "message_records": [
                {
                    "message_id": 1,
                    "role": "user",
                    "message_content": "What is AI?",
                    "minio_files": [],
                    "units": []
                },
                {
                    "message_id": 2,
                    "role": "assistant",
                    "message_content": "AI stands for Artificial Intelligence.",
                    "units": [],
                    "opinion_flag": None
                }
            ],
            "search_records": [],
            "image_records": []
        }
        mock_get_conversation_history.return_value = mock_history

        # Execute
        result = get_conversation_history_service(123, self.user_id)

        # Assert
        self.assertEqual(len(result), 1)  # Result is wrapped in a list
        self.assertEqual(result[0]["conversation_id"],
                         "123")  # Converted to string
        self.assertEqual(len(result[0]["message"]), 2)
        # Check message structure
        user_message = result[0]["message"][0]
        self.assertEqual(user_message["role"], "user")
        self.assertEqual(user_message["message"], "What is AI?")

        assistant_message = result[0]["message"][1]
        self.assertEqual(assistant_message["role"], "assistant")
        # Contains final_answer unit
        self.assertEqual(len(assistant_message["message"]), 1)
        self.assertEqual(
            assistant_message["message"][0]["type"], "final_answer")
        self.assertEqual(
            assistant_message["message"][0]["content"], "AI stands for Artificial Intelligence.")

    @patch('backend.services.conversation_management_service.get_conversation')
    @patch('backend.services.conversation_management_service.get_source_searches_by_message')
    @patch('backend.services.conversation_management_service.get_source_images_by_message')
    def test_get_sources_service_by_message(self, mock_get_images, mock_get_searches, mock_get_conversation):
        # Setup
        mock_get_conversation.return_value = {
            "conversation_id": 123, "title": "Test Chat"}

        mock_searches = [
            {
                "message_id": 2,
                "source_title": "AI Definition",
                "source_content": "AI stands for Artificial Intelligence",
                "source_type": "web",
                "source_location": "https://example.com/ai",
                "published_date": datetime(2023, 1, 15),
                "score_overall": 0.95,
                "score_accuracy": 0.9,
                "score_semantic": 0.8,
                "cite_index": 1,
                "search_type": "web_search",
                "tool_sign": "web_search"
            }
        ]
        mock_get_searches.return_value = mock_searches

        mock_images = [
            {"message_id": 2, "image_url": "https://example.com/image.jpg"}
        ]
        mock_get_images.return_value = mock_images

        # Execute
        result = get_sources_service(None, 2, user_id=self.user_id)

        # Assert
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["message"], "success")
        # Check searches
        self.assertEqual(len(result["data"]["searches"]), 1)
        search = result["data"]["searches"][0]
        self.assertEqual(search["title"], "AI Definition")
        self.assertEqual(search["url"], "https://example.com/ai")
        self.assertEqual(search["published_date"], "2023-01-15")
        self.assertEqual(search["score"], 0.95)
        self.assertEqual(search["score_details"]["accuracy"], 0.9)
        # Check images
        self.assertEqual(len(result["data"]["images"]), 1)
        self.assertEqual(result["data"]["images"][0],
                         "https://example.com/image.jpg")

    @patch('backend.services.conversation_management_service.update_message_opinion')
    def test_update_message_opinion_service(self, mock_update_opinion):
        # Setup
        mock_update_opinion.return_value = True

        # Execute
        update_message_opinion_service(123, "Y")

        # Assert
        mock_update_opinion.assert_called_once_with(123, "Y")

    @patch('backend.services.conversation_management_service.update_message_opinion')
    def test_update_message_opinion_service_failure(self, mock_update_opinion):
        """Ensure service raises exception when DB update fails (returns False)."""
        # Setup failure
        mock_update_opinion.return_value = False

        # Execute & Assert
        with self.assertRaises(Exception) as context:
            update_message_opinion_service(123, "Y")
        self.assertIn("Message does not exist", str(context.exception))
        mock_update_opinion.assert_called_once_with(123, "Y")

    @patch('backend.services.conversation_management_service.get_message_id_by_index')
    def test_get_message_id_by_index_impl_success(self, mock_get_message):
        """Should return message_id when found."""
        mock_get_message.return_value = 999
        import asyncio
        result = asyncio.run(get_message_id_by_index_impl(123, 2))
        self.assertEqual(result, 999)
        mock_get_message.assert_called_once_with(123, 2)

    @patch('backend.services.conversation_management_service.get_message_id_by_index')
    def test_get_message_id_by_index_impl_not_found(self, mock_get_message):
        """Should raise Exception when message_id not found."""
        mock_get_message.return_value = None
        import asyncio
        with self.assertRaises(Exception) as ctx:
            asyncio.run(get_message_id_by_index_impl(123, 2))
        self.assertIn("Message not found", str(ctx.exception))
        mock_get_message.assert_called_once_with(123, 2)

    # Tests for generate_conversation_title_service
    @patch('backend.services.conversation_management_service.call_llm_for_title')
    @patch('backend.services.conversation_management_service.update_conversation_title')
    def test_generate_conversation_title_service(self, mock_update_title, mock_call_llm):
        """Test generate_conversation_title_service generates title from question."""
        # Setup
        mock_call_llm.return_value = "Python Tips"
        mock_update_title.return_value = True

        # Execute
        import asyncio
        result = asyncio.run(generate_conversation_title_service(
            123, "How to use Python effectively?", self.user_id, self.tenant_id, "en"))

        # Assert
        self.assertEqual(result, "Python Tips")
        mock_call_llm.assert_called_once_with(
            "How to use Python effectively?", self.tenant_id, "en")
        mock_update_title.assert_called_once_with(
            123, "Python Tips", self.user_id)


if __name__ == '__main__':
    unittest.main()
