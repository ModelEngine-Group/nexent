import os
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

# Dynamically determine the backend path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)

# Mock external dependencies before importing the modules that use them
# Stub nexent.core.agents.agent_model.ToolConfig to satisfy type imports in consts.model
agent_model_stub = types.ModuleType("agent_model")


class ToolConfig:  # minimal stub for type reference
    pass


agent_model_stub.ToolConfig = ToolConfig

# Ensure module hierarchy exists in sys.modules
sys.modules['nexent'] = types.ModuleType('nexent')
sys.modules['nexent.core'] = types.ModuleType('nexent.core')
sys.modules['nexent.core.agents'] = types.ModuleType('nexent.core.agents')
sys.modules['nexent.core.agents.agent_model'] = agent_model_stub
sys.modules['database.client'] = pytest.importorskip("unittest.mock").MagicMock()
sys.modules['database.agent_db'] = pytest.importorskip("unittest.mock").MagicMock()
sys.modules['agents.create_agent_info'] = pytest.importorskip("unittest.mock").MagicMock()
sys.modules['nexent.core.agents.run_agent'] = pytest.importorskip("unittest.mock").MagicMock()
sys.modules['supabase'] = pytest.importorskip("unittest.mock").MagicMock()
sys.modules['utils.auth_utils'] = pytest.importorskip(
    "unittest.mock").MagicMock()
sys.modules['utils.config_utils'] = pytest.importorskip(
    "unittest.mock").MagicMock()
sys.modules['utils.thread_utils'] = pytest.importorskip(
    "unittest.mock").MagicMock()
sys.modules['agents.agent_run_manager'] = pytest.importorskip(
    "unittest.mock").MagicMock()
sys.modules['services.agent_service'] = pytest.importorskip(
    "unittest.mock").MagicMock()
sys.modules['services.conversation_management_service'] = pytest.importorskip(
    "unittest.mock").MagicMock()
sys.modules['services.memory_config_service'] = pytest.importorskip(
    "unittest.mock").MagicMock()

from apps.agent_app import router

# Create FastAPI app for testing
app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture
def mock_auth_header():
    return {"Authorization": "Bearer test_token"}


@pytest.fixture
def mock_conversation_id():
    return 123


@pytest.mark.asyncio
async def test_agent_run_api(mocker, mock_auth_header):
    """Test agent_run_api endpoint."""
    mock_run_agent_stream = mocker.patch(
        "apps.agent_app.run_agent_stream", new_callable=mocker.AsyncMock)

    # Mock the streaming response
    async def mock_stream():
        yield b"data: chunk1\n\n"
        yield b"data: chunk2\n\n"

    mock_run_agent_stream.return_value = StreamingResponse(
        mock_stream(), media_type="text/event-stream")

    response = client.post(
        "/agent/run",
        json={
            "agent_id": 1,
            "conversation_id": 123,
            "query": "test query",
            "history": [],
            "minio_files": [],
            "is_debug": False,
        },
        headers=mock_auth_header
    )

    assert response.status_code == 200
    mock_run_agent_stream.assert_called_once()
    assert "text/event-stream" in response.headers["content-type"]

    # Check streamed content
    content = response.content.decode()
    assert "data: chunk1" in content
    assert "data: chunk2" in content


def test_agent_stop_api_success(mocker, mock_conversation_id):
    """Test agent_stop_api success case."""
    mock_stop_tasks = mocker.patch("apps.agent_app.stop_agent_tasks")
    mock_stop_tasks.return_value = {"status": "success"}

    response = client.get(f"/agent/stop/{mock_conversation_id}")

    assert response.status_code == 200
    mock_stop_tasks.assert_called_once_with(mock_conversation_id)
    assert response.json()["status"] == "success"


def test_agent_stop_api_not_found(mocker, mock_conversation_id):
    """Test agent_stop_api not found case."""
    mock_stop_tasks = mocker.patch("apps.agent_app.stop_agent_tasks")
    mock_stop_tasks.return_value = {"status": "error"}  # Simulate not found

    response = client.get(f"/agent/stop/{mock_conversation_id}")

    # The app should raise HTTPException for non-success status
    assert response.status_code == 400
    mock_stop_tasks.assert_called_once_with(mock_conversation_id)
    assert "no running agent or preprocess tasks found" in response.json()[
        "detail"]


def test_search_agent_info_api_success(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=mocker.AsyncMock)
    mock_get_user_id.return_value = ("user_id", "tenant_id")
    mock_get_agent_info.return_value = {"agent_id": 123, "name": "Test Agent"}

    # Test the endpoint
    response = client.post(
        "/agent/search_info",
        json=123,  # agent_id as body parameter
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_get_agent_info.assert_called_once_with(123, "tenant_id")
    assert response.json()["agent_id"] == 123


def test_search_agent_info_api_exception(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=mocker.AsyncMock)
    mock_get_user_id.return_value = ("user_id", "tenant_id")
    mock_get_agent_info.side_effect = Exception("Test error")

    # Test the endpoint
    response = client.post(
        "/agent/search_info",
        json=123,
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    assert "Agent search info error" in response.json()["detail"]


def test_get_creating_sub_agent_info_api_success(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_get_creating_agent = mocker.patch(
        "apps.agent_app.get_creating_sub_agent_info_impl", new_callable=mocker.AsyncMock)
    mock_get_creating_agent.return_value = {"agent_id": 456}

    # Test the endpoint - this is a GET request
    response = client.get(
        "/agent/get_creating_sub_agent_id",
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_get_creating_agent.assert_called_once_with(
        mock_auth_header["Authorization"])
    assert response.json()["agent_id"] == 456


def test_get_creating_sub_agent_info_api_exception(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_get_creating_agent = mocker.patch(
        "apps.agent_app.get_creating_sub_agent_info_impl", new_callable=mocker.AsyncMock)
    mock_get_creating_agent.side_effect = Exception("Test error")

    # Test the endpoint - this is a GET request
    response = client.get(
        "/agent/get_creating_sub_agent_id",
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    assert "Agent create error" in response.json()["detail"]


def test_update_agent_info_api_success(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_update_agent = mocker.patch(
        "apps.agent_app.update_agent_info_impl", new_callable=mocker.AsyncMock)
    mock_update_agent.return_value = None

    # Test the endpoint
    response = client.post(
        "/agent/update",
        json={"agent_id": 123, "name": "Updated Agent",
              "display_name": "Updated Display Name"},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_update_agent.assert_called_once()
    assert response.json() == {}


def test_update_agent_info_api_exception(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_update_agent = mocker.patch(
        "apps.agent_app.update_agent_info_impl", new_callable=mocker.AsyncMock)
    mock_update_agent.side_effect = Exception("Test error")

    # Test the endpoint
    response = client.post(
        "/agent/update",
        json={"agent_id": 123, "name": "Updated Agent",
              "display_name": "Updated Display Name"},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    assert "Agent update error" in response.json()["detail"]


def test_delete_agent_api_success(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_delete_agent = mocker.patch(
        "apps.agent_app.delete_agent_impl", new_callable=mocker.AsyncMock)
    mock_delete_agent.return_value = None

    # Test the endpoint
    response = client.request(
        "DELETE",
        "/agent",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_delete_agent.assert_called_once_with(
        123, mock_auth_header["Authorization"])
    assert response.json() == {}


def test_delete_agent_api_exception(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_delete_agent = mocker.patch(
        "apps.agent_app.delete_agent_impl", new_callable=mocker.AsyncMock)
    mock_delete_agent.side_effect = Exception("Test error")

    # Test the endpoint
    response = client.request(
        "DELETE",
        "/agent",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    assert "Agent delete error" in response.json()["detail"]


@pytest.mark.asyncio
async def test_export_agent_api_success(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_export_agent = mocker.patch(
        "apps.agent_app.export_agent_impl", new_callable=mocker.AsyncMock)
    mock_export_agent.return_value = '{"agent_id": 123, "name": "Test Agent"}'

    # Test the endpoint
    response = client.post(
        "/agent/export",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_export_agent.assert_called_once_with(
        123, mock_auth_header["Authorization"])
    assert response.json()["code"] == 0
    assert response.json()["message"] == "success"


@pytest.mark.asyncio
async def test_export_agent_api_exception(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_export_agent = mocker.patch(
        "apps.agent_app.export_agent_impl", new_callable=mocker.AsyncMock)
    mock_export_agent.side_effect = Exception("Test error")

    # Test the endpoint
    response = client.post(
        "/agent/export",
        json={"agent_id": 123},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    assert "Agent export error" in response.json()["detail"]


def test_import_agent_api_success(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_import_agent = mocker.patch(
        "apps.agent_app.import_agent_impl", new_callable=mocker.AsyncMock)
    mock_import_agent.return_value = None

    # Test the endpoint - following the ExportAndImportDataFormat structure
    response = client.post(
        "/agent/import",
        json={
            "agent_info": {
                "agent_id": 123,
                "agent_info": {
                    "test_agent": {
                        "agent_id": 123,
                        "name": "Imported Agent",
                        "description": "Test description",
                        "business_description": "Test business",
                        "model_name": "gpt-4",
                        "max_steps": 10,
                        "provide_run_summary": True,
                        "duty_prompt": "Test duty prompt",
                        "constraint_prompt": "Test constraint prompt",
                        "few_shots_prompt": "Test few shots prompt",
                        "enabled": True,
                        "tools": [],
                        "managed_agents": []
                    }
                },
                "mcp_info": []
            }
        },
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_import_agent.assert_called_once()
    args, kwargs = mock_import_agent.call_args
    # The function signature is import_agent_impl(request.agent_info, authorization)
    assert args[1] == mock_auth_header["Authorization"]
    assert response.json() == {}


def test_import_agent_api_exception(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_import_agent = mocker.patch(
        "apps.agent_app.import_agent_impl", new_callable=mocker.AsyncMock)
    mock_import_agent.side_effect = Exception("Test error")

    # Test the endpoint - following the ExportAndImportDataFormat structure
    response = client.post(
        "/agent/import",
        json={
            "agent_info": {
                "agent_id": 123,
                "agent_info": {
                    "test_agent": {
                        "agent_id": 123,
                        "name": "Imported Agent",
                        "description": "Test description",
                        "business_description": "Test business",
                        "model_name": "gpt-4",
                        "max_steps": 10,
                        "provide_run_summary": True,
                        "duty_prompt": "Test duty prompt",
                        "constraint_prompt": "Test constraint prompt",
                        "few_shots_prompt": "Test few shots prompt",
                        "enabled": True,
                        "tools": [],
                        "managed_agents": []
                    }
                },
                "mcp_info": []
            }
        },
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    assert "Agent import error" in response.json()["detail"]


def test_list_all_agent_info_api_success(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "apps.agent_app.list_all_agent_info_impl", new_callable=mocker.AsyncMock)
    # Mock return values
    mock_get_user_info.return_value = ("test_user", "test_tenant", "en")
    mock_list_all_agent.return_value = [
        {"agent_id": 1, "name": "Agent 1", "display_name": "Display Agent 1"},
        {"agent_id": 2, "name": "Agent 2", "display_name": "Display Agent 2"}
    ]

    # Test the endpoint
    response = client.get(
        "/agent/list",
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_get_user_info.assert_called_once()
    mock_list_all_agent.assert_called_once_with(tenant_id="test_tenant")
    assert len(response.json()) == 2
    assert response.json()[0]["agent_id"] == 1
    assert response.json()[0]["display_name"] == "Display Agent 1"
    assert response.json()[1]["name"] == "Agent 2"
    assert response.json()[1]["display_name"] == "Display Agent 2"


def test_list_all_agent_info_api_exception(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_get_user_info = mocker.patch("apps.agent_app.get_current_user_info")
    mock_list_all_agent = mocker.patch(
        "apps.agent_app.list_all_agent_info_impl", new_callable=mocker.AsyncMock)
    # Mock return values and exception
    mock_get_user_info.return_value = ("test_user", "test_tenant", "en")
    mock_list_all_agent.side_effect = Exception("Test error")

    # Test the endpoint
    response = client.get(
        "/agent/list",
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    mock_get_user_info.assert_called_once()
    mock_list_all_agent.assert_called_once_with(tenant_id="test_tenant")
    assert "Agent list error" in response.json()["detail"]


def test_related_agent_api_success(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_insert_related_agent = mocker.patch(
        "apps.agent_app.insert_related_agent_impl")

    mock_get_user_id.return_value = ("user_id", "tenant_id")
    mock_insert_related_agent.return_value = {"status": "success"}

    # Test the endpoint
    response = client.post(
        "/agent/related_agent",
        json={
            "parent_agent_id": 123,
            "child_agent_id": 456
        },
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_insert_related_agent.assert_called_once_with(
        parent_agent_id=123,
        child_agent_id=456,
        tenant_id="tenant_id"
    )
    assert response.json()["status"] == "success"


def test_related_agent_api_exception(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_insert_related_agent = mocker.patch(
        "apps.agent_app.insert_related_agent_impl")

    mock_get_user_id.return_value = ("user_id", "tenant_id")
    mock_insert_related_agent.side_effect = Exception("Test error")

    # Test the endpoint
    response = client.post(
        "/agent/related_agent",
        json={
            "parent_agent_id": 123,
            "child_agent_id": 456
        },
        headers=mock_auth_header
    )

    # The exception handling returns a JSONResponse with status 400
    assert response.status_code == 500
    assert response.json()["message"] == "Failed to insert relation"
    assert response.json()["status"] == "error"


def test_delete_related_agent_api_success(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_delete_related_agent = mocker.patch(
        "apps.agent_app.delete_related_agent_impl")

    mock_get_user_id.return_value = ("user_id", "tenant_id")
    mock_delete_related_agent.return_value = {"status": "success"}

    # Test the endpoint
    response = client.post(
        "/agent/delete_related_agent",
        json={
            "parent_agent_id": 123,
            "child_agent_id": 456
        },
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_delete_related_agent.assert_called_once_with(123, 456, "tenant_id")
    assert response.json()["status"] == "success"


def test_delete_related_agent_api_exception(mocker, mock_auth_header):
    # Setup mocks using pytest-mock
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_delete_related_agent = mocker.patch(
        "apps.agent_app.delete_related_agent_impl")

    mock_get_user_id.return_value = ("user_id", "tenant_id")
    mock_delete_related_agent.side_effect = Exception("Test error")

    # Test the endpoint
    response = client.post(
        "/agent/delete_related_agent",
        json={
            "parent_agent_id": 123,
            "child_agent_id": 456
        },
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 500
    assert "Agent related info error" in response.json()["detail"]


@pytest.mark.asyncio
async def test_export_agent_api_detailed(mocker, mock_auth_header):
    """Detailed testing of export_agent_api function, including ConversationResponse construction"""
    # Setup mocks using pytest-mock
    mock_export_agent = mocker.patch(
        "apps.agent_app.export_agent_impl", new_callable=mocker.AsyncMock)

    # Setup mocks - return complex JSON data
    agent_data = {
        "agent_id": 456,
        "name": "Complex Agent",
        "description": "Detailed testing",
        "tools": [{"id": 1, "name": "tool1"}, {"id": 2, "name": "tool2"}],
        "managed_agents": [789, 101],
        "other_fields": "some values"
    }
    mock_export_agent.return_value = agent_data

    # Test with complex data
    response = client.post(
        "/agent/export",
        json={"agent_id": 456},
        headers=mock_auth_header
    )

    # Assertions
    assert response.status_code == 200
    mock_export_agent.assert_called_once_with(
        456, mock_auth_header["Authorization"])

    # Verify correct construction of ConversationResponse
    response_data = response.json()
    assert response_data["code"] == 0
    assert response_data["message"] == "success"
    assert response_data["data"] == agent_data


@pytest.mark.asyncio
async def test_export_agent_api_empty_response(mocker, mock_auth_header):
    """Test export_agent_api handling empty response"""
    # Setup mocks using pytest-mock
    mock_export_agent = mocker.patch(
        "apps.agent_app.export_agent_impl", new_callable=mocker.AsyncMock)

    # Setup mock to return empty data
    mock_export_agent.return_value = {}

    # Send request
    response = client.post(
        "/agent/export",
        json={"agent_id": 789},
        headers=mock_auth_header
    )

    # Verify
    assert response.status_code == 200
    mock_export_agent.assert_called_once_with(
        789, mock_auth_header["Authorization"])

    # Verify empty data can also be correctly wrapped in ConversationResponse
    response_data = response.json()
    assert response_data["code"] == 0
    assert response_data["message"] == "success"
    assert response_data["data"] == {}


def _alias_services_for_tests():
    """
    兼容路由里使用的 'services.agent_service' 动态导入路径。
    将 backend.services.* 映射为 services.* 以便 mocker.patch 能找到。
    """
    import sys
    try:
        import backend.services as b_services
        import backend.services.agent_service as b_agent_service
        # 父包与子模块都映射一份
        sys.modules['services'] = b_services
        sys.modules['services.agent_service'] = b_agent_service
    except Exception:
        # 如果你的工程本来就能直接 import services.*，这里兜底不做处理
        pass


def test_get_agent_call_relationship_api_success(mocker, mock_auth_header):
    # patch 鉴权
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_user_id.return_value = ("user_id_x", "tenant_abc")

    # 现在改 patch 这里：指向 apps.agent_app 命名空间的顶层符号
    mock_impl = mocker.patch("apps.agent_app.get_agent_call_relationship_impl")
    mock_impl.return_value = {
        "agent_id": 1,
        "tree": {"tools": [], "sub_agents": []}
    }

    resp = client.get("/agent/call_relationship/1", headers=mock_auth_header)

    assert resp.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_impl.assert_called_once_with(1, "tenant_abc")
    data = resp.json()
    assert data["agent_id"] == 1
    assert "tree" in data and "tools" in data["tree"] and "sub_agents" in data["tree"]


def test_get_agent_call_relationship_api_exception(mocker, mock_auth_header):
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_user_id.return_value = ("user_id_x", "tenant_abc")

    # 同样改这里
    mock_impl = mocker.patch("apps.agent_app.get_agent_call_relationship_impl")
    mock_impl.side_effect = Exception("boom")

    resp = client.get("/agent/call_relationship/999", headers=mock_auth_header)

    assert resp.status_code == 500
    assert "Failed to get agent call relationship" in resp.json()["detail"]
