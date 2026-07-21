from nexent.core.agents.agent_model import (
    BufferedStrategy,
    PriorityWeightedStrategy,
    TokenBudgetStrategy,
    TurnResourcesComponent,
)
from nexent.core.agents.turn_resources import (
    ResolvedTurnResource,
    TurnResourceInvocation,
)


def _invocation(content: str = "Follow this exact workflow.") -> TurnResourceInvocation:
    return TurnResourceInvocation(
        resources=[
            ResolvedTurnResource(
                resource_type="skill",
                resource_id="7",
                name="report-writer",
                description="Write structured reports",
                content=content,
            )
        ]
    )


def test_render_required_skill_instructions() -> None:
    rendered = _invocation().render_required_instructions("en")

    assert rendered is not None
    assert "Required resources for this turn" in rendered
    assert "report-writer" in rendered
    assert "Follow this exact workflow." in rendered
    assert "expire after this turn" in rendered


def test_empty_skill_content_requires_reading_guide() -> None:
    rendered = _invocation(content="").render_required_instructions("zh")

    assert rendered is not None
    assert "read_skill_md" in rendered
    assert "report-writer" in rendered


def test_required_component_survives_context_strategies() -> None:
    component = TurnResourcesComponent(
        invocation=_invocation(),
        language="en",
        token_estimate=500,
        metadata={"required": True, "relevance_score": 0.0},
    )

    token_selected = TokenBudgetStrategy().select_components(
        [component], token_budget=10, component_budgets={"turn_resources": 10}
    )
    priority_selected = PriorityWeightedStrategy(
        relevance_threshold=0.9
    ).select_components([component], token_budget=10, component_budgets={})
    buffered_selected = BufferedStrategy(buffer_size=0).select_components(
        [component], token_budget=10, component_budgets={}
    )

    assert token_selected == [component]
    assert priority_selected == [component]
    assert buffered_selected == [component]
    assert component.to_messages()[0]["content"][0]["text"].startswith(
        "# Required resources"
    )
