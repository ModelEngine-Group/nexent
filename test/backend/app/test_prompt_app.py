import os
import sys
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend"))
sys.path.insert(0, backend_dir)

from apps.prompt_app import router


app = FastAPI()
app.include_router(router)
client = TestClient(app)


@patch("apps.prompt_app.get_current_user_info")
@patch("apps.prompt_app.PromptOptimizationService")
def test_optimize_prompt_section_api_success(mock_service_cls, mock_get_current_user_info):
    """Test /prompt/optimize returns optimized content with X-Prompt-Source header"""
    mock_get_current_user_info.return_value = ("user-1", "tenant-1", "en")

    mock_result = MagicMock()
    mock_result.optimized_content = "Optimized"
    mock_result.source = "nexent"
    mock_result.section_type = "duty"
    mock_result.section_title = "Agent Role"
    mock_result.original_content = "Original"

    mock_svc_instance = MagicMock()
    mock_svc_instance.optimize.return_value = mock_result
    mock_service_cls.return_value = mock_svc_instance

    response = client.post(
        "/prompt/optimize",
        json={
            "task_description": "Build an agent",
            "agent_id": 1,
            "model_id": 2,
            "section_type": "duty",
            "section_title": "Agent Role",
            "current_content": "Original",
            "feedback": "Make it clearer",
            "tool_ids": [10],
            "sub_agent_ids": [20],
            "knowledge_base_display_names": ["kb-a"],
        },
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Success"
    assert data["data"]["optimized_content"] == "Optimized"
    assert data["data"]["section_type"] == "duty"
    assert data["data"]["section_title"] == "Agent Role"
    assert data["data"]["original_content"] == "Original"
    mock_get_current_user_info.assert_called_once()
    mock_svc_instance.optimize.assert_called_once()


@patch("apps.prompt_app.get_current_user_info")
@patch("apps.prompt_app.PromptOptimizationService")
def test_optimize_prompt_section_api_with_mode(mock_service_cls, mock_get_current_user_info):
    """Test /prompt/optimize accepts mode/start_pos/end_pos parameters"""
    mock_get_current_user_info.return_value = ("user-1", "tenant-1", "zh")

    mock_result = MagicMock()
    mock_result.optimized_content = "Inserted content"
    mock_result.source = "jiuwen"
    mock_result.section_type = "duty"
    mock_result.section_title = "智能体角色"
    mock_result.original_content = "Old content"

    mock_svc_instance = MagicMock()
    mock_svc_instance.optimize.return_value = mock_result
    mock_service_cls.return_value = mock_svc_instance

    response = client.post(
        "/prompt/optimize",
        json={
            "task_description": "Test insert",
            "agent_id": 5,
            "model_id": 3,
            "section_type": "duty",
            "section_title": "智能体角色",
            "current_content": "Old content",
            "feedback": "Insert more detail",
            "mode": "insert",
            "start_pos": 10,
            "end_pos": 20,
        },
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert call_args[0][0].mode == "insert"
    assert call_args[0][0].start_pos == 10
    assert call_args[0][0].end_pos == 20


@patch("apps.prompt_app.get_current_user_info")
@patch("apps.prompt_app.PromptOptimizationService")
def test_optimize_prompt_section_api_nexent_capability_error(mock_service_cls, mock_get_current_user_info):
    """Test /prompt/optimize returns 400 when NexentCapabilityError is raised"""
    mock_get_current_user_info.return_value = ("user-1", "tenant-1", "en")

    from backend.adapters.exception import NexentCapabilityError
    mock_svc_instance = MagicMock()
    mock_svc_instance.optimize.side_effect = NexentCapabilityError(
        "nexent 原生模式只支持 general 模式，当前请求 mode=insert 不支持"
    )
    mock_service_cls.return_value = mock_svc_instance

    response = client.post(
        "/prompt/optimize",
        json={
            "task_description": "Build an agent",
            "agent_id": 1,
            "model_id": 2,
            "section_type": "duty",
            "section_title": "Agent Role",
            "current_content": "Original",
            "feedback": "Make it clearer",
            "mode": "insert",
        },
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 400
    data = response.json()
    assert "general" in data["message"]


@patch("apps.prompt_app.get_current_user_info")
@patch("apps.prompt_app.PromptOptimizationService")
def test_optimize_badcase_api_success(mock_service_cls, mock_get_current_user_info):
    """Test /prompt/optimize/badcase returns optimized content with X-Prompt-Source header"""
    mock_get_current_user_info.return_value = ("user-1", "tenant-1", "zh")

    mock_result = MagicMock()
    mock_result.optimized_content = "Fixed based on bad cases"
    mock_result.source = "jiuwen"
    mock_result.section_type = "duty"
    mock_result.section_title = "智能体角色"
    mock_result.original_content = "Old content"

    mock_svc_instance = MagicMock()
    mock_svc_instance.optimize_badcase.return_value = mock_result
    mock_service_cls.return_value = mock_svc_instance

    response = client.post(
        "/prompt/optimize/badcase",
        json={
            "agent_id": 1,
            "model_id": 2,
            "current_content": "Old content",
            "bad_cases": [
                {
                    "question": "用户问如何退款",
                    "answer": "请联系客服",
                    "label": "退款问题",
                    "reason": "没有给出具体操作步骤",
                }
            ],
            "section_type": "duty",
            "section_title": "智能体角色",
            "tool_ids": [10],
            "sub_agent_ids": [],
            "knowledge_base_display_names": [],
        },
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Success"
    assert data["data"]["optimized_content"] == "Fixed based on bad cases"
    mock_svc_instance.optimize_badcase.assert_called_once()


@patch("apps.prompt_app.get_current_user_info")
@patch("apps.prompt_app.PromptOptimizationService")
def test_optimize_badcase_api_nexent_capability_error(mock_service_cls, mock_get_current_user_info):
    """Test /prompt/optimize/badcase returns 400 when NexentCapabilityError is raised"""
    mock_get_current_user_info.return_value = ("user-1", "tenant-1", "zh")

    from backend.adapters.exception import NexentCapabilityError
    mock_svc_instance = MagicMock()
    mock_svc_instance.optimize_badcase.side_effect = NexentCapabilityError(
        "nexent 原生模式不支持 badcase 优化"
    )
    mock_service_cls.return_value = mock_svc_instance

    response = client.post(
        "/prompt/optimize/badcase",
        json={
            "agent_id": 1,
            "model_id": 2,
            "current_content": "Old content",
            "bad_cases": [
                {"question": "Q1", "answer": "A1"}
            ],
            "section_type": "duty",
            "section_title": "智能体角色",
        },
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 400
    data = response.json()
    assert "badcase" in data["message"]
