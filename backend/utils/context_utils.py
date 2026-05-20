"""Context component building utilities for system prompt assembly.

Provides build_context_components() to convert agent configuration data
into ContextComponent instances for use with ContextManager.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from nexent.core.agents.agent_model import (
        ContextComponent,
        ToolsComponent,
        SkillsComponent,
        MemoryComponent,
        KnowledgeBaseComponent,
        ManagedAgentsComponent,
        ExternalAgentsComponent,
        SystemPromptComponent,
        ToolConfig,
        AgentConfig,
        ExternalA2AAgentConfig,
    )


def _format_tools_description(tools: Dict[str, Any]) -> str:
    """Format tool descriptions for system prompt injection."""
    if not tools:
        return ""
    
    lines = ["Available tools:"]
    for name, tool in tools.items():
        desc = tool.description if hasattr(tool, 'description') else tool.get('description', '')
        inputs = tool.inputs if hasattr(tool, 'inputs') else tool.get('inputs', '')
        output_type = tool.output_type if hasattr(tool, 'output_type') else tool.get('output_type', '')
        lines.append(f"- {name}: {desc}")
        if inputs:
            lines.append(f"  Inputs: {inputs}")
        if output_type:
            lines.append(f"  Output: {output_type}")
    
    return "\n".join(lines)


def _format_skills_description(skills: List[Dict[str, str]]) -> str:
    """Format skill descriptions for system prompt injection."""
    if not skills:
        return ""
    
    lines = ["Available skills:"]
    for skill in skills:
        name = skill.get('name', '')
        desc = skill.get('description', '')
        lines.append(f"- {name}: {desc}")
    
    return "\n".join(lines)


def _format_memory_context(memory_list: List[Any]) -> str:
    """Format memory search results for system prompt injection."""
    if not memory_list:
        return ""
    
    lines = ["Relevant memories from previous conversations:"]
    for mem in memory_list:
        if isinstance(mem, dict):
            content = mem.get('memory', '') or mem.get('content', '')
            if content:
                lines.append(f"- {content}")
        elif isinstance(mem, str):
            lines.append(f"- {mem}")
    
    return "\n".join(lines)


def _format_managed_agents_description(managed_agents: Dict[str, Any]) -> str:
    """Format managed sub-agent descriptions for system prompt injection."""
    if not managed_agents:
        return ""
    
    lines = ["Available sub-agents you can delegate tasks to:"]
    for name, agent in managed_agents.items():
        desc = agent.description if hasattr(agent, 'description') else agent.get('description', '')
        lines.append(f"- {name}: {desc}")
    
    return "\n".join(lines)


def _format_external_agents_description(external_a2a_agents: Dict[str, Any]) -> str:
    """Format external A2A agent descriptions for system prompt injection."""
    if not external_a2a_agents:
        return ""
    
    lines = ["Available external agents you can call:"]
    for agent_id, agent in external_a2a_agents.items():
        name = agent.name if hasattr(agent, 'name') else agent.get('name', '')
        desc = agent.description if hasattr(agent, 'description') else agent.get('description', '')
        lines.append(f"- {name} (ID: {agent_id}): {desc}")
    
    return "\n".join(lines)


def _format_app_context(app_name: str, app_description: str, user_id: str, time_str: str) -> str:
    """Format application context for system prompt injection."""
    lines = [
        f"Application: {app_name}",
        f"Description: {app_description}",
        f"Current user: {user_id}",
        f"Current time: {time_str}",
    ]
    return "\n".join(lines)


def build_tools_component(
    tools: Dict[str, Any],
    priority: int = 20,
) -> "ToolsComponent":
    """Build ToolsComponent from tool configurations.
    
    Args:
        tools: Dict of tool name -> ToolConfig or tool dict
        priority: Component priority for selection
        
    Returns:
        ToolsComponent instance
    """
    from nexent.core.agents.agent_model import ToolsComponent
    
    tool_list = []
    for name, tool in tools.items():
        tool_dict = {
            "name": name,
            "description": getattr(tool, 'description', '') or tool.get('description', ''),
            "inputs": getattr(tool, 'inputs', '') or tool.get('inputs', ''),
            "output_type": getattr(tool, 'output_type', '') or tool.get('output_type', ''),
        }
        tool_list.append(tool_dict)
    
    formatted_desc = _format_tools_description(tools)
    return ToolsComponent(
        tools=tool_list,
        formatted_description=formatted_desc,
        priority=priority,
    )


def build_skills_component(
    skills: List[Dict[str, str]],
    priority: int = 15,
) -> "SkillsComponent":
    """Build SkillsComponent from skill configurations.
    
    Args:
        skills: List of skill dicts with name and description
        priority: Component priority for selection
        
    Returns:
        SkillsComponent instance
    """
    from nexent.core.agents.agent_model import SkillsComponent
    
    formatted_desc = _format_skills_description(skills)
    return SkillsComponent(
        skills=skills,
        formatted_description=formatted_desc,
        priority=priority,
    )


def build_memory_component(
    memory_list: List[Any],
    search_query: Optional[str] = None,
    priority: int = 12,
) -> "MemoryComponent":
    """Build MemoryComponent from memory search results.
    
    Args:
        memory_list: List of memory search results
        search_query: Query used to search memory
        priority: Component priority for selection
        
    Returns:
        MemoryComponent instance
    """
    from nexent.core.agents.agent_model import MemoryComponent
    
    memories = []
    for mem in memory_list:
        if isinstance(mem, dict):
            memories.append({
                "content": mem.get('memory', '') or mem.get('content', ''),
                "memory_type": mem.get('memory_type', 'user'),
                "metadata": mem.get('metadata', {}),
            })
        elif isinstance(mem, str):
            memories.append({
                "content": mem,
                "memory_type": "user",
                "metadata": {},
            })
    
    formatted_content = _format_memory_context(memory_list)
    return MemoryComponent(
        memories=memories,
        formatted_content=formatted_content,
        search_query=search_query,
        priority=priority,
    )


def build_knowledge_base_component(
    knowledge_base_summary: str,
    kb_ids: Optional[List[str]] = None,
    priority: int = 10,
) -> "KnowledgeBaseComponent":
    """Build KnowledgeBaseComponent from knowledge base summary.
    
    Args:
        knowledge_base_summary: Summary text from knowledge bases
        kb_ids: List of knowledge base IDs used
        priority: Component priority for selection
        
    Returns:
        KnowledgeBaseComponent instance
    """
    from nexent.core.agents.agent_model import KnowledgeBaseComponent
    
    return KnowledgeBaseComponent(
        summary=knowledge_base_summary,
        kb_ids=kb_ids or [],
        priority=priority,
    )


def build_managed_agents_component(
    managed_agents: Dict[str, Any],
    priority: int = 8,
) -> "ManagedAgentsComponent":
    """Build ManagedAgentsComponent from managed sub-agent configurations.
    
    Args:
        managed_agents: Dict of agent name -> AgentConfig
        priority: Component priority for selection
        
    Returns:
        ManagedAgentsComponent instance
    """
    from nexent.core.agents.agent_model import ManagedAgentsComponent
    
    agent_list = []
    for name, agent in managed_agents.items():
        agent_dict = {
            "name": name,
            "description": getattr(agent, 'description', '') or agent.get('description', ''),
            "tools": [],
        }
        if hasattr(agent, 'tools'):
            agent_dict["tools"] = [t.name for t in agent.tools if hasattr(t, 'name')]
        agent_list.append(agent_dict)
    
    formatted_desc = _format_managed_agents_description(managed_agents)
    return ManagedAgentsComponent(
        agents=agent_list,
        formatted_description=formatted_desc,
        priority=priority,
    )


def build_external_agents_component(
    external_a2a_agents: Dict[str, Any],
    priority: int = 7,
) -> "ExternalAgentsComponent":
    """Build ExternalAgentsComponent from external A2A agent configurations.
    
    Args:
        external_a2a_agents: Dict of agent_id -> ExternalA2AAgentConfig
        priority: Component priority for selection
        
    Returns:
        ExternalAgentsComponent instance
    """
    from nexent.core.agents.agent_model import ExternalAgentsComponent
    
    agent_list = []
    for agent_id, agent in external_a2a_agents.items():
        agent_dict = {
            "agent_id": str(agent_id),
            "name": getattr(agent, 'name', '') or agent.get('name', ''),
            "description": getattr(agent, 'description', '') or agent.get('description', ''),
            "url": getattr(agent, 'url', '') or agent.get('url', ''),
        }
        agent_list.append(agent_dict)
    
    formatted_desc = _format_external_agents_description(external_a2a_agents)
    return ExternalAgentsComponent(
        agents=agent_list,
        formatted_description=formatted_desc,
        priority=priority,
    )


def build_system_prompt_component(
    content: str,
    template_name: Optional[str] = None,
    priority: int = 100,
) -> "SystemPromptComponent":
    """Build SystemPromptComponent with rendered content.
    
    Args:
        content: Rendered system prompt content
        template_name: Source template name for reference
        priority: Component priority (highest by default)
        
    Returns:
        SystemPromptComponent instance
    """
    from nexent.core.agents.agent_model import SystemPromptComponent
    
    return SystemPromptComponent(
        content=content,
        template_name=template_name,
        priority=priority,
    )


def build_context_components(
    tools: Optional[Dict[str, Any]] = None,
    skills: Optional[List[Dict[str, str]]] = None,
    managed_agents: Optional[Dict[str, Any]] = None,
    external_a2a_agents: Optional[Dict[str, Any]] = None,
    memory_list: Optional[List[Any]] = None,
    memory_search_query: Optional[str] = None,
    knowledge_base_summary: Optional[str] = None,
    kb_ids: Optional[List[str]] = None,
    app_name: Optional[str] = None,
    app_description: Optional[str] = None,
    user_id: Optional[str] = None,
    include_tools: bool = True,
    include_skills: bool = True,
    include_memory: bool = True,
    include_knowledge_base: bool = True,
    include_managed_agents: bool = True,
    include_external_agents: bool = True,
    include_app_context: bool = True,
) -> List["ContextComponent"]:
    """Build list of ContextComponents from agent configuration data.
    
    This function converts the raw data used in Jinja2 template rendering
    into ContextComponent instances that can be registered with ContextManager.
    
    Args:
        tools: Dict of tool name -> ToolConfig
        skills: List of skill dicts with name and description
        managed_agents: Dict of agent name -> AgentConfig
        external_a2a_agents: Dict of agent_id -> ExternalA2AAgentConfig
        memory_list: List of memory search results
        memory_search_query: Query used to search memory
        knowledge_base_summary: Summary text from knowledge bases
        kb_ids: List of knowledge base IDs
        app_name: Application name
        app_description: Application description
        user_id: Current user ID
        include_tools: Whether to include tools component
        include_skills: Whether to include skills component
        include_memory: Whether to include memory component
        include_knowledge_base: Whether to include KB component
        include_managed_agents: Whether to include managed agents component
        include_external_agents: Whether to include external agents component
        include_app_context: Whether to include app context
        
    Returns:
        List of ContextComponent instances ready for ContextManager
    """
    components: List = []
    
    if include_tools and tools:
        components.append(build_tools_component(tools))
    
    if include_skills and skills:
        components.append(build_skills_component(skills))
    
    if include_memory and memory_list:
        components.append(build_memory_component(memory_list, memory_search_query))
    
    if include_knowledge_base and knowledge_base_summary:
        components.append(build_knowledge_base_component(knowledge_base_summary, kb_ids))
    
    if include_managed_agents and managed_agents:
        components.append(build_managed_agents_component(managed_agents))
    
    if include_external_agents and external_a2a_agents:
        components.append(build_external_agents_component(external_a2a_agents))
    
    return components


def build_app_context_string(
    app_name: str,
    app_description: str,
    user_id: str,
) -> str:
    """Build app context string for template injection.
    
    Args:
        app_name: Application name
        app_description: Application description  
        user_id: Current user ID
        
    Returns:
        Formatted app context string
    """
    time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return _format_app_context(app_name, app_description, user_id, time_str)