import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
SDK_SOURCE_ROOT = PROJECT_ROOT / "sdk"
if str(SDK_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_SOURCE_ROOT))


def test_nl2agent_apply_local_resources_rejects_invalid_draft_agent_id(monkeypatch):
    for module_name in list(sys.modules):
        if (
            module_name == "nexent"
            or module_name.startswith("nexent.core")
            or module_name == "smolagents"
            or module_name.startswith("smolagents.")
        ):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    from nexent.core.tools.nl2agent.apply_local_resources_tool import (
        get_apply_local_resources_tool,
        nl2agent_apply_local_resources,
    )

    get_apply_local_resources_tool(
        agent_id=0,
        draft_agent_id=0,
        user_id="user_1",
        tenant_id="tenant_1",
        model_id=7,
        language="en",
    )

    raw_result = nl2agent_apply_local_resources(tool_ids="[42]", skill_ids="[]")

    assert json.loads(raw_result) == {
        "error": "NL2AGENT draft agent_id not set in context."
    }
