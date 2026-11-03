# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Build the ephemeral NL2Skill agent configuration."""

from nexent.core.agents.agent_model import AgentConfig
from nexent.core.agents.context import ContextItemInput, ContextItemType

NL2SKILL_NAME = "nl2skill_main"


def create_nl2skill_agent_config(
    system_prompt: str,
    model_name: str,
    system_ref=None,
) -> AgentConfig:
    """Create one request-scoped skill creator without persistent state."""

    if not system_prompt.strip():
        raise ValueError("Skill creation system prompt must not be empty")

    return AgentConfig(
        agent_id=system_ref.agent_id if system_ref else None,
        version_no=0 if system_ref else None,
        runtime_ref=f"agent:{system_ref.agent_id}:v0" if system_ref else None,
        origin="SYSTEM",
        name=NL2SKILL_NAME,
        display_name="技能创建助手",
        description="Ephemeral natural-language skill builder",
        # A non-empty mapping disables CodeAgent's default English templates.
        # Keep the rendered prompt in context_items to preserve literal Jinja syntax.
        prompt_templates={
            "system_prompt": "",
            "planning": {
                "initial_plan": "",
                "update_plan_pre_messages": "",
                "update_plan_post_messages": "",
            },
            "managed_agent": {"task": "", "report": ""},
            "final_answer": {"pre_messages": "", "post_messages": "{{task}}"},
        },
        tools=[],
        max_steps=5,
        model_name=model_name,
        output_protocol="final_envelope",
        provide_run_summary=False,
        context_items=[
            ContextItemInput(
                id="system:nl2skill_prompt",
                type=ContextItemType.SYSTEM,
                content={"text": system_prompt},
                source=("prompt:nl2skill",),
                priority=100,
                metadata={"authority": "platform", "layout_order": -1},
            )
        ],
        enable_planning=False,
    )
