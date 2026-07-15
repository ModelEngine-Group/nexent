"""ContextProjector: converts ContextComponent instances into fine-grained ContextItem candidates."""

import uuid
from typing import Any, Dict, List

from ..agent_model import (
    ContextComponent,
    ExternalAgentsComponent,
    KnowledgeBaseComponent,
    ManagedAgentsComponent,
    MemoryComponent,
    SkillsComponent,
    SystemPromptComponent,
    ToolsComponent,
)
from .context_item import AuthorityTier, ContextItem, ContextItemType, RepresentationTier
from .item_handler_registry import ItemHandlerRegistry

_CHARS_PER_TOKEN = 1.5

_MINIMUM_FIDELITY_MAP: Dict[ContextItemType, RepresentationTier] = {
    ContextItemType.SYSTEM_PROMPT: RepresentationTier.FULL,
    ContextItemType.TOOL: RepresentationTier.STRUCTURED,
    ContextItemType.SKILL: RepresentationTier.STRUCTURED,
    ContextItemType.MEMORY: RepresentationTier.STRUCTURED,
    ContextItemType.KNOWLEDGE_BASE: RepresentationTier.COMPRESSED,
    ContextItemType.MANAGED_AGENT: RepresentationTier.STRUCTURED,
    ContextItemType.EXTERNAL_AGENT: RepresentationTier.STRUCTURED,
}


def _estimate_item_tokens(content: Any) -> int:
    return int(len(str(content)) / _CHARS_PER_TOKEN)


def _make_item_id(item_type: ContextItemType, suffix: str = "") -> str:
    tag = item_type.value
    if suffix:
        return f"{tag}:{suffix}"
    return f"{tag}:{uuid.uuid4().hex[:8]}"


class ContextProjector:
    """Projects ContextComponent instances into fine-grained ContextItem candidates."""

    def project(self, components: List[ContextComponent]) -> List[ContextItem]:
        """Convert a list of ContextComponent into ContextItem list.

        Each component type maps to one or more ContextItem instances with
        appropriate authority tiers and minimum fidelity constraints.
        After creation, each item is validated against the ItemHandlerRegistry.
        """
        items: List[ContextItem] = []
        for component in components:
            items.extend(self._project_component(component))

        for item in items:
            ItemHandlerRegistry.get(item.item_type)

        return items

    def _project_component(self, component: ContextComponent) -> List[ContextItem]:
        if isinstance(component, SystemPromptComponent):
            return self._project_system_prompt(component)
        if isinstance(component, ToolsComponent):
            return self._project_tools(component)
        if isinstance(component, SkillsComponent):
            return self._project_skills(component)
        if isinstance(component, MemoryComponent):
            return self._project_memory(component)
        if isinstance(component, KnowledgeBaseComponent):
            return self._project_knowledge_base(component)
        if isinstance(component, ManagedAgentsComponent):
            return self._project_managed_agents(component)
        if isinstance(component, ExternalAgentsComponent):
            return self._project_external_agents(component)
        return []

    def _project_system_prompt(self, component: SystemPromptComponent) -> List[ContextItem]:
        return [
            ContextItem(
                item_id=_make_item_id(ContextItemType.SYSTEM_PROMPT, component.template_name or ""),
                item_type=ContextItemType.SYSTEM_PROMPT,
                source_refs=[component.template_name] if component.template_name else [],
                authority_tier=AuthorityTier.PLATFORM,
                minimum_fidelity=_MINIMUM_FIDELITY_MAP[ContextItemType.SYSTEM_PROMPT],
                current_representation=RepresentationTier.FULL,
                content=component.content,
                token_estimate=component.token_estimate or component.estimate_tokens(),
                metadata={
                    "template_name": component.template_name,
                    "_source_component": component,
                    **component.metadata,
                },
            )
        ]

    def _project_tools(self, component: ToolsComponent) -> List[ContextItem]:
        items: List[ContextItem] = []
        for tool in component.tools:
            tool_name = tool.get("name", "unknown")
            items.append(
                ContextItem(
                    item_id=_make_item_id(ContextItemType.TOOL, tool_name),
                    item_type=ContextItemType.TOOL,
                    source_refs=[tool_name],
                    authority_tier=AuthorityTier.PLATFORM,
                    minimum_fidelity=_MINIMUM_FIDELITY_MAP[ContextItemType.TOOL],
                    current_representation=RepresentationTier.FULL,
                    content=tool,
                    token_estimate=_estimate_item_tokens(tool),
                    metadata={
                        "priority": component.priority,
                        "_source_component": component,
                        **component.metadata,
                    },
                )
            )
        return items

    def _project_skills(self, component: SkillsComponent) -> List[ContextItem]:
        items: List[ContextItem] = []
        for skill in component.skills:
            skill_name = skill.get("name", "unknown")
            items.append(
                ContextItem(
                    item_id=_make_item_id(ContextItemType.SKILL, skill_name),
                    item_type=ContextItemType.SKILL,
                    source_refs=[skill_name],
                    authority_tier=AuthorityTier.PLATFORM,
                    minimum_fidelity=_MINIMUM_FIDELITY_MAP[ContextItemType.SKILL],
                    current_representation=RepresentationTier.FULL,
                    content=skill,
                    token_estimate=_estimate_item_tokens(skill),
                    metadata={
                        "priority": component.priority,
                        "_source_component": component,
                        **component.metadata,
                    },
                )
            )
        return items

    def _project_memory(self, component: MemoryComponent) -> List[ContextItem]:
        items: List[ContextItem] = []
        for idx, memory in enumerate(component.memories):
            memory_content = memory.get("content", "")
            memory_type = memory.get("memory_type", "user")
            items.append(
                ContextItem(
                    item_id=_make_item_id(ContextItemType.MEMORY, f"{memory_type}:{idx}"),
                    item_type=ContextItemType.MEMORY,
                    source_refs=[f"mem0:{memory_type}"],
                    authority_tier=AuthorityTier.RETRIEVED_MEMORY,
                    minimum_fidelity=_MINIMUM_FIDELITY_MAP[ContextItemType.MEMORY],
                    current_representation=RepresentationTier.FULL,
                    content=memory,
                    token_estimate=_estimate_item_tokens(memory_content),
                    metadata={
                        "memory_type": memory_type,
                        "search_query": component.search_query,
                        "_source_component": component,
                        **memory.get("metadata", {}),
                        **component.metadata,
                    },
                )
            )
        return items

    def _project_knowledge_base(self, component: KnowledgeBaseComponent) -> List[ContextItem]:
        return [
            ContextItem(
                item_id=_make_item_id(
                    ContextItemType.KNOWLEDGE_BASE, ":".join(component.kb_ids)
                ),
                item_type=ContextItemType.KNOWLEDGE_BASE,
                source_refs=component.kb_ids,
                authority_tier=AuthorityTier.RETRIEVED_MEMORY,
                minimum_fidelity=_MINIMUM_FIDELITY_MAP[ContextItemType.KNOWLEDGE_BASE],
                current_representation=RepresentationTier.FULL,
                content=component.summary,
                token_estimate=component.token_estimate or component.estimate_tokens(),
                metadata={
                    "kb_ids": component.kb_ids,
                    "_source_component": component,
                    **component.metadata,
                },
            )
        ]

    def _project_managed_agents(self, component: ManagedAgentsComponent) -> List[ContextItem]:
        items: List[ContextItem] = []
        for agent in component.agents:
            agent_name = agent.get("name", "unknown")
            items.append(
                ContextItem(
                    item_id=_make_item_id(ContextItemType.MANAGED_AGENT, agent_name),
                    item_type=ContextItemType.MANAGED_AGENT,
                    source_refs=[agent_name],
                    authority_tier=AuthorityTier.PLATFORM,
                    minimum_fidelity=_MINIMUM_FIDELITY_MAP[ContextItemType.MANAGED_AGENT],
                    current_representation=RepresentationTier.FULL,
                    content=agent,
                    token_estimate=_estimate_item_tokens(agent),
                    metadata={
                        "priority": component.priority,
                        "_source_component": component,
                        **component.metadata,
                    },
                )
            )
        return items

    def _project_external_agents(self, component: ExternalAgentsComponent) -> List[ContextItem]:
        items: List[ContextItem] = []
        for agent in component.agents:
            agent_name = agent.get("name", "unknown")
            agent_id = agent.get("agent_id", "")
            items.append(
                ContextItem(
                    item_id=_make_item_id(ContextItemType.EXTERNAL_AGENT, agent_id or agent_name),
                    item_type=ContextItemType.EXTERNAL_AGENT,
                    source_refs=[agent_id or agent_name],
                    authority_tier=AuthorityTier.PLATFORM,
                    minimum_fidelity=_MINIMUM_FIDELITY_MAP[ContextItemType.EXTERNAL_AGENT],
                    current_representation=RepresentationTier.FULL,
                    content=agent,
                    token_estimate=_estimate_item_tokens(agent),
                    metadata={
                        "priority": component.priority,
                        "_source_component": component,
                        **component.metadata,
                    },
                )
            )
        return items
