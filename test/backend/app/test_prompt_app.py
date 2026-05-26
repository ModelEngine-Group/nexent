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
@patch("apps.prompt_app.optimize_prompt_section_impl")
def test_optimize_prompt_section_api_success(
    mock_optimize_prompt_section,
    mock_get_current_user_info,
):
    mock_get_current_user_info.return_value = ("user-1", "tenant-1", "en")
    mock_optimize_prompt_section.return_value = {
        "section_type": "duty",
        "section_title": "Agent Role",
        "original_content": "Original",
        "optimized_content": "Optimized",
    }

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
    assert response.json()["message"] == "Prompt section optimized successfully"
    assert response.json()["data"]["optimized_content"] == "Optimized"
    mock_get_current_user_info.assert_called_once()
    mock_optimize_prompt_section.assert_called_once_with(
        agent_id=1,
        model_id=2,
        task_description="Build an agent",
        tenant_id="tenant-1",
        language="en",
        section_type="duty",
        section_title="Agent Role",
        current_content="Original",
        feedback="Make it clearer",
        tool_ids=[10],
        sub_agent_ids=[20],
        knowledge_base_display_names=["kb-a"],
    )
