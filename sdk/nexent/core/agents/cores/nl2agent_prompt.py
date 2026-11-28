# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Render the call protocol for the platform-owned NL2Agent workflow."""

from collections.abc import Iterable
from typing import Literal

from nexent.core.agents.context import ContextItemInput, ContextItemType
from nexent.core.prompts import load_prompt, render_prompt_text


NL2AGENT_PROMPT_ID = "system:nl2agent_prompt"


def nl2agent_protocol(
    items: Iterable[ContextItemInput], language: str, mode: Literal["native", "smolagents", "jiuwen"]
) -> ContextItemInput | None:
    creator = next((item for item in items if item.type == ContextItemType.SYSTEM
                    and item.id == NL2AGENT_PROMPT_ID and item.metadata.get("authority") == "platform"), None)
    names = creator.metadata.get("creator_tools") if creator is not None else None
    if not isinstance(names, dict):
        return None

    template = load_prompt("zh" if language == "zh" else "en", "core/nl2agent")
    if mode == "native":
        sections = (template["native"], render_prompt_text(template["native_examples"], names))
    else:
        sections = (template["text"], template[f"{mode}_final"], render_prompt_text(template["text_examples"], names))
    return ContextItemInput(
        id="system:nl2agent_protocol",
        type=ContextItemType.SYSTEM,
        content={"text": "\n\n".join(sections)},
        source=("core:nl2agent",),
        priority=100,
        metadata={"authority": "platform", "layout_order": 0},
    )
