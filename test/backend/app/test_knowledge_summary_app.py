import unittest
import json
import sys
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.responses import StreamingResponse

# Mock botocore client first to prevent any S3 connection attempts
with patch('botocore.client.BaseClient._make_api_call', return_value={}):
    # Mock MinioClient and database connections
    with patch('backend.database.client.MinioClient', MagicMock()):
        with patch('backend.database.client.db_client', MagicMock()):
            # Mock other imports needed by knowledge_summary_app.py
            with patch('nexent.vector_database.elasticsearch_core.ElasticSearchCore', MagicMock()) as mock_es_core:
                with patch('backend.services.elasticsearch_service.ElasticSearchService', MagicMock()) as mock_es_service:
                    with patch('backend.services.elasticsearch_service.get_es_core', MagicMock()) as mock_get_es_core:
                        with patch('backend.utils.auth_utils.get_current_user_id', MagicMock(return_value=('test_user_id', 'test_tenant_id'))) as mock_get_user_id:
                            with patch('backend.utils.auth_utils.get_current_user_info', MagicMock(return_value=('test_user_id', 'test_tenant_id', 'en'))) as mock_get_user_info:
                                # Now import the module after mocking dependencies
                                from fastapi.testclient import TestClient
                                from fastapi import FastAPI, Depends, Request
                                from backend.apps.knowledge_summary_app import router

# Create a FastAPI app and include the router for testing
app = FastAPI()
app.include_router(router)
client = TestClient(app)

class TestKnowledgeSummaryApp(unittest.TestCase):
    def setUp(self):
        """Setup test environment before each test"""
        # Sample test data
        self.index_name = "test_index"
        self.user_id = "test_user_id"
        self.tenant_id = "test_tenant_id"
        self.language = "en"
        self.summary_result = "This is a test summary for the knowledge base"
        self.auth_header = {"Authorization": "Bearer test_token"}

        # Reset mocks
        mock_get_user_id.reset_mock()
        mock_get_user_id.return_value = (self.user_id, self.tenant_id)

        mock_get_user_info.reset_mock()
        mock_get_user_info.return_value = (self.user_id, self.tenant_id, self.language)

        mock_es_service.reset_mock()
        self.mock_service_instance = MagicMock()
        mock_es_service.return_value = self.mock_service_instance

    @patch('backend.services.elasticsearch_service.get_es_core')
    async def test_auto_summary_success(self, mock_get_es_core_local):
        """Test successful auto summary generation"""
        # Setup mock responses
        mock_es_core_instance = MagicMock()
        mock_get_es_core_local.return_value = mock_es_core_instance

        # Configure service mock to return streaming response
        self.mock_service_instance.summary_index_name = AsyncMock()
        stream_response = StreamingResponse(
            content=iter(["data: {\"status\": \"success\", \"progress\": 100}\n\n"]),
            media_type="text/event-stream"
        )
        self.mock_service_instance.summary_index_name.return_value = stream_response

        # Execute test
        with patch('backend.apps.knowledge_summary_app.ElasticSearchService', return_value=self.mock_service_instance):
            with TestClient(app) as client:
                response = client.post(
                    f"/summary/{self.index_name}/auto_summary?batch_size=500",
                    headers=self.auth_header
                )

        # Verify service calls
        self.mock_service_instance.summary_index_name.assert_called_once()
        call_args = self.mock_service_instance.summary_index_name.call_args[1]
        self.assertEqual(call_args["index_name"], self.index_name)
        self.assertEqual(call_args["batch_size"], 500)
        self.assertEqual(call_args["user_id"], self.user_id)
        self.assertEqual(call_args["language"], self.language)

        # Verify auth calls
        mock_get_user_info.assert_called_once()
        self.assertIn(self.auth_header["Authorization"], mock_get_user_info.call_args[0])

    @patch('backend.services.elasticsearch_service.get_es_core')
    async def test_auto_summary_exception(self, mock_get_es_core_local):
        """Test auto summary generation with exception"""
        # Setup mock to raise exception
        mock_es_core_instance = MagicMock()
        mock_get_es_core_local.return_value = mock_es_core_instance

        # Configure service mock to raise exception
        with patch('backend.apps.knowledge_summary_app.ElasticSearchService', return_value=self.mock_service_instance):
            self.mock_service_instance.summary_index_name = AsyncMock(
                side_effect=Exception("Error generating summary")
            )

            # Execute test
            with TestClient(app) as client:
                response = client.post(
                    f"/summary/{self.index_name}/auto_summary",
                    headers=self.auth_header
                )

        # Assertions
        self.assertEqual(response.status_code, 500)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertIn("知识库摘要生成失败", response.text)
        self.assertIn("Error generating summary", response.text)

    def test_change_summary_success(self):
        """Test successful summary update"""
        # Setup request data
        request_data = {
            "summary_result": self.summary_result
        }

        # Configure service mock response
        expected_response = {
            "success": True,
            "index_name": self.index_name,
            "summary": self.summary_result
        }

        # Debug what's actually happening with get_current_user_id
        actual_user_id_call_args = []
        actual_change_summary_call_args = []

        def capture_user_id_args(*args, **kwargs):
            actual_user_id_call_args.append((args, kwargs))
            # Return a tuple to mimic the actual function's signature
            # The change_summary function does user_id = get_current_user_id(authorization)[0]
            return (self.user_id, self.tenant_id)

        # Directly patch the module function to ensure we're mocking the right one
        with patch('backend.apps.knowledge_summary_app.get_current_user_id', side_effect=capture_user_id_args):
            with patch('backend.apps.knowledge_summary_app.ElasticSearchService', return_value=self.mock_service_instance):
                # Capture change_summary call args
                original_change_summary = self.mock_service_instance.change_summary
                def capture_change_summary_args(*args, **kwargs):
                    actual_change_summary_call_args.append(kwargs)
                    return expected_response

                self.mock_service_instance.change_summary = capture_change_summary_args

                # Execute test
                with TestClient(app) as client:
                    response = client.post(
                        f"/summary/{self.index_name}/summary",
                        json=request_data,
                        headers=self.auth_header
                    )

        # Debug output
        print(f"User ID call args: {actual_user_id_call_args}")
        print(f"Change summary call args: {actual_change_summary_call_args}")

        # Assertions
        self.assertEqual(response.status_code, 200)
        response_json = response.json()
        self.assertEqual(response_json["success"], True)
        self.assertEqual(response_json["index_name"], self.index_name)
        self.assertEqual(response_json["summary"], self.summary_result)

        # Verify that the change_summary was called with the correct arguments
        self.assertTrue(actual_change_summary_call_args, "change_summary was not called")
        if actual_change_summary_call_args:
            call_args = actual_change_summary_call_args[0]
            self.assertEqual(call_args["index_name"], self.index_name)
            self.assertEqual(call_args["summary_result"], self.summary_result)
            self.assertEqual(call_args["user_id"], self.user_id)

    def test_change_summary_exception(self):
        """Test summary update with exception"""
        # Setup request data
        request_data = {
            "summary_result": self.summary_result
        }

        # Configure service mock to raise exception
        with patch('backend.apps.knowledge_summary_app.get_current_user_id', return_value=(self.user_id, self.tenant_id)):
            with patch('backend.apps.knowledge_summary_app.ElasticSearchService', return_value=self.mock_service_instance):
                self.mock_service_instance.change_summary.side_effect = Exception("Error updating summary")

                # Execute test
                with TestClient(app) as client:
                    response = client.post(
                        f"/summary/{self.index_name}/summary",
                        json=request_data,
                        headers=self.auth_header
                    )

        # Assertions
        self.assertEqual(response.status_code, 500)
        self.assertIn("知识库摘要更新失败", response.json()["detail"])
        self.assertIn("Error updating summary", response.json()["detail"])

    def test_get_summary_success(self):
        """Test successful summary retrieval"""
        # Configure service mock response
        expected_response = {
            "success": True,
            "index_name": self.index_name,
            "summary": self.summary_result
        }

        with patch('backend.apps.knowledge_summary_app.ElasticSearchService', return_value=self.mock_service_instance):
            self.mock_service_instance.get_summary.return_value = expected_response

            # Execute test
            with TestClient(app) as client:
                response = client.get(f"/summary/{self.index_name}/summary")

        # Assertions
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected_response)

        # Verify service calls
        self.mock_service_instance.get_summary.assert_called_once_with(
            index_name=self.index_name
        )

    def test_get_summary_exception(self):
        """Test summary retrieval with exception"""
        # Configure service mock to raise exception
        with patch('backend.apps.knowledge_summary_app.ElasticSearchService', return_value=self.mock_service_instance):
            self.mock_service_instance.get_summary.side_effect = Exception("Error getting summary")

            # Execute test
            with TestClient(app) as client:
                response = client.get(f"/summary/{self.index_name}/summary")

        # Assertions
        self.assertEqual(response.status_code, 500)
        self.assertIn("获取知识库摘要失败", response.json()["detail"])
        self.assertIn("Error getting summary", response.json()["detail"])

    def test_missing_auth_header(self):
        """Test endpoints that require auth when auth header is missing"""
        # Test auto_summary endpoint
        with patch('backend.apps.knowledge_summary_app.get_current_user_info', side_effect=Exception("Missing auth header")):
            with TestClient(app) as client:
                response = client.post(f"/summary/{self.index_name}/auto_summary")
                self.assertEqual(response.status_code, 500)
                self.assertIn("知识库摘要生成失败", response.text)
                self.assertIn("Missing auth header", response.text)

        # Test change_summary endpoint
        with patch('backend.apps.knowledge_summary_app.get_current_user_id', side_effect=Exception("Missing auth header")):
            with TestClient(app) as client:
                response = client.post(
                    f"/summary/{self.index_name}/summary",
                    json={"summary_result": self.summary_result}
                )
                self.assertEqual(response.status_code, 500)
                self.assertIn("知识库摘要更新失败", response.json()["detail"])
                self.assertIn("Missing auth header", response.json()["detail"])

    def test_different_language_setting(self):
        """Test auto_summary with different language settings"""
        languages = ["zh", "en", "fr", "es"]

        # Create a proper StreamingResponse for return value
        stream_content = iter(["data: {\"status\": \"success\", \"progress\": 100}\n\n"])
        stream_response = StreamingResponse(
            content=stream_content,
            media_type="text/event-stream"
        )

        for lang in languages:
            # Setup mock for different language
            with patch('backend.apps.knowledge_summary_app.get_current_user_info', return_value=(self.user_id, self.tenant_id, lang)):
                # Configure service mock with proper return value
                mock_summary = AsyncMock()
                mock_summary.return_value = stream_response

                with patch('backend.apps.knowledge_summary_app.ElasticSearchService') as mock_es_class:
                    # Create a new mock service instance for this iteration
                    mock_service = MagicMock()
                    mock_service.summary_index_name = mock_summary
                    mock_es_class.return_value = mock_service

                    # Execute test
                    with TestClient(app) as client:
                        response = client.post(
                            f"/summary/{self.index_name}/auto_summary",
                            headers=self.auth_header
                        )

                    # Verify language is passed correctly
                    mock_summary.assert_called_once()
                    call_args = mock_summary.call_args[1]
                    self.assertEqual(call_args["language"], lang)


if __name__ == "__main__":
    unittest.main()
