from nexent.core.agents.context import ContextItemInput, ContextItemType
from sdk.benchmark.generic.runtime.task_adapter import render_precompact_system_prompt


def test_render_precompact_system_prompt_includes_grouped_tool_descriptions():
    items = [
        ContextItemInput(
            id="system:available_resources_header",
            type=ContextItemType.SYSTEM,
            content={"text": "### Available Resources"},
            priority=55,
        ),
        ContextItemInput(
            id="tool:search",
            type=ContextItemType.TOOL,
            content={
                "name": "search",
                "description": "Search public information.",
                "inputs": '{"query": {"type": "string"}}',
                "output_type": "string",
                "source": "local",
            },
            priority=50,
            metadata={
                "render_group": "tools",
                "language": "en",
                "is_manager": False,
            },
        ),
    ]

    rendered = render_precompact_system_prompt(items)

    assert "### Available Resources" in rendered
    assert "search" in rendered
    assert "Search public information." in rendered
    assert "query" in rendered
