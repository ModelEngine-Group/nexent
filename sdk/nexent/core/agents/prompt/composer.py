"""Run-scoped Agent prompt rendering and context composition."""

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from jinja2 import Environment, StrictUndefined

from ...prompts import load_prompt
from ..context.models import ContextItemInput, ContextItemType
from .bundle import AgentPromptBundle, _thaw
from .knowledge import render_knowledge_base_summaries, render_knowledge_scope_resources


_RENDERER = Environment(undefined=StrictUndefined, autoescape=False)


@dataclass(frozen=True)
class HumanInteractionPrompts:
    """Localized HITL instructions supplied by the SDK fixed-prompt catalog."""

    instructions: str
    clarification_policy: str
    questions_description: str


class AgentPromptComposer:
    """Render all Agent prompt sections through one strict interface."""

    def __init__(self, bundle: AgentPromptBundle):
        self.bundle = bundle

    @classmethod
    def from_compatibility_templates(cls, templates: Mapping[str, Any]):
        """Adapt the smolagents stage-template shape at a single SDK boundary."""
        role = "manager" if "manager_agent" in templates else "managed"
        if f"{role}_agent" not in templates and "final_answer" in templates:
            templates = {
                **templates,
                f"{role}_agent": {"task": "{{task}}", "report": "{{final_answer}}"},
            }
        return cls(AgentPromptBundle._from_compatibility_mapping(
            role=role,
            template=templates,
        ))

    def render_system_section(self, section: str, **values: Any) -> str:
        source = self.bundle.system_sections[section]
        return _RENDERER.from_string(source).render(**values).strip()

    def render_delegated_task(self, *, name: str, task: str) -> str:
        source = self.bundle.template[f"{self.bundle.role}_agent"]["task"]
        return _RENDERER.from_string(source).render(name=name, task=task)

    def render_delegated_report(self, result: str, *, name: str = "") -> str:
        source = self.bundle.template[f"{self.bundle.role}_agent"]["report"]
        return _RENDERER.from_string(source).render(name=name, final_answer=result)

    def render_final_answer_post_message(self, task: str) -> str:
        source = self.bundle.template["final_answer"]["post_messages"]
        return _RENDERER.from_string(source).render(task=task)

    def render_final_answer_pre_message(self) -> str:
        return self.bundle.template["final_answer"]["pre_messages"]

    def render_execution_flow(
        self,
        *,
        enable_planning: bool = False,
    ) -> str:
        text = self.render_system_section("execution_flow")
        if enable_planning:
            text += "\n" + self.render_system_section("planning_guidance")
        return text

    def render_restricted_python_execution(self, authorized_imports: List[str]) -> str:
        imports = ", ".join(
            f"`{name}`" for name in sorted({
                name.strip() for name in authorized_imports
                if isinstance(name, str) and name.strip()
            })
        )
        return self.render_system_section("restricted_python_execution", authorized_imports=imports)

    def render_human_interaction(self, *, preserves_executor: bool) -> HumanInteractionPrompts:
        policy = load_prompt(self.bundle.language, "agent/human_interaction")
        clarification = policy["clarification_policy"]
        questions = policy["questions_description"]
        linear = policy["linear_execution_policy"]
        instructions = clarification if preserves_executor else f"{clarification}\n{linear}"
        return HumanInteractionPrompts(
            instructions=instructions,
            clarification_policy=clarification,
            questions_description=questions,
        )

    def compose_context_inputs(
        self,
        duty: Optional[str] = None,
        constraint: Optional[str] = None,
        few_shots: Optional[str] = None,
        language: str = "zh",
        is_manager: bool = True,
        enable_planning: bool = False,
        verification_enabled: bool = False,
        # Piecewise data sources
        tools: Optional[Dict[str, Any]] = None,
        skills: Optional[List[Dict[str, str]]] = None,
        worker_agents: Optional[Dict[str, Any]] = None,
        external_a2a_agents: Optional[Dict[str, Any]] = None,
        memory_list: Optional[List[Any]] = None,
        memory_search_query: Optional[str] = None,
        enable_memory_tool_policy: bool = False,
        enable_automation_tool_policy: bool = False,
        long_term_memory_items: Optional[List[dict[str, Any]]] = None,
        knowledge_base_summaries: Optional[List[dict[str, Any]]] = None,
        knowledge_base_no_indexes: bool = False,
        knowledge_scope: Optional[Mapping[str, Any]] = None,
        restricted_python_authorized_imports: Optional[List[str]] = None,
        include_tools: bool = True,
        include_skills: bool = True,
        include_memory: bool = True,
        include_knowledge_base: bool = True,
        include_worker_agents: bool = True,
        include_external_agents: bool = True,
        include_app_context: bool = True,
        sandbox_workspace_enabled: bool = False,
    ) -> List[ContextItemInput]:
        """Build an authorized, naturally granular SDK context input snapshot."""
        inputs: List[ContextItemInput] = []
        if self.bundle.role != ("manager" if is_manager else "managed") or self.bundle.language != language:
            raise ValueError("Agent prompt composer role or language does not match this run")
        composer = self

        def add_system(
            item_id: str,
            text: str,
            priority: int,
            layout_order: int,
            authority: str = "agent",
        ) -> None:
            if text:
                inputs.append(ContextItemInput(
                    id=f"system:{item_id}",
                    type=ContextItemType.SYSTEM,
                    content={"text": text},
                    source=(f"agent_prompt:{item_id}",),
                    priority=priority,
                    metadata={"authority": authority, "layout_order": layout_order},
                ))

        if include_app_context:
            add_system(
                "header",
                composer.render_system_section("outline_identity") + "\n" + composer.render_system_section("header"),
                100, 0, "platform",
            )

        if sandbox_workspace_enabled:
            add_system(
                "sandbox_workspace_guidance",
                composer.render_system_section("sandbox_workspace_guidance"),
                99, 32,
                "platform",
            )

        if enable_memory_tool_policy:
            policy = load_prompt(language, "agent/memory_tool_policy")["policy"]
            add_system("memory_tool_policy", policy, 90, 35, "platform")

        if enable_automation_tool_policy:
            policy = load_prompt(language, "agent/automation_tool_policy")["policy"]
            add_system("automation_tool_policy", policy, 95, 34, "platform")

        if knowledge_scope is not None:
            policy = load_prompt(language, "agent/knowledge_scope")["policy"]
            add_system("knowledge_scope_policy", policy, 98, 33, "platform")

        if include_memory and long_term_memory_items:
            memory_list = [*long_term_memory_items, *(memory_list or [])]

        if include_memory and memory_list:
            for index, memory in enumerate(memory_list):
                if not isinstance(memory, (dict, str)):
                    raise ValueError(f"invalid memory payload at index {index}")
                payload = memory if isinstance(memory, dict) else {"memory": memory, "memory_level": "user"}
                inputs.append(ContextItemInput(
                    id=f"memory:{index}", type=ContextItemType.MEMORY, content=payload,
                    source=(f"memory:{memory_search_query or 'run'}",), priority=90,
                    metadata={
                        "render_group": "memory",
                        "language": language,
                        "authority": "retrieved",
                        **(
                            {
                                "version_id": payload.get("version_id") or payload.get("dreaming_version_id"),
                                "memory_type": "long_term",
                                "scope": payload.get("scope") or payload.get("memory_level"),
                                "source": payload.get("source"),
                            }
                            if payload.get("version_id") is not None or payload.get("dreaming_version_id") is not None
                            else {}
                        ),
                    },
                ))

        if duty:
            duty_text = composer.render_system_section("duty", duty=duty)
            if not include_app_context:
                duty_text = composer.render_system_section("outline_identity") + "\n" + duty_text
            add_system("duty", duty_text, 80, 10)

        has_tools = bool(include_tools and tools)
        has_agents = bool(
            is_manager
            and (
                (include_worker_agents and worker_agents)
                or (include_external_agents and external_a2a_agents)
            )
        )
        has_skills = bool(include_skills and skills)
        has_resources = has_tools or has_skills or has_agents

        if include_skills and skills:
            for index, skill in enumerate(skills):
                name = str(skill.get("name", index))
                inputs.append(ContextItemInput(
                    id=f"skill:{name}", type=ContextItemType.SKILL, content=dict(skill),
                    source=(f"skill:{name}",), priority=40,
                    metadata={
                        "render_group": "skills", "language": language,
                        "usage_guidance": composer.render_system_section("skill_usage"),
                        "authority": "agent",
                    },
                ))

        add_system(
            "execution_flow",
            composer.render_system_section("outline_execution") + "\n"
            + composer.render_execution_flow(enable_planning=enable_planning),
            60, 20, "platform",
        )
        if is_manager:
            add_system("manager_orchestration", composer.bundle.template["manager_agent"]["orchestration"], 58, 22, "platform")
        if verification_enabled:
            add_system("self_verification_guidance", composer.render_system_section("self_verification_guidance"), 60, 24, "platform")
        add_system("final_answer_guidance", composer.render_system_section("final_answer_guidance"), 60, 25, "platform")
        if has_resources:
            add_system("available_resources_header", composer.render_system_section("available_resources_header"), 55, 50, "platform")

        if include_tools and tools:
            for name, tool in tools.items():
                tool_name = getattr(tool, "name", name) if not isinstance(tool, dict) else tool.get("name", name)
                if name == "create_scheduled_task_proposal" or tool_name == "create_scheduled_task_proposal":
                    continue
                payload = {
                    "name": name,
                    "description": getattr(tool, "description", None) if not isinstance(tool, dict) else tool.get("description", ""),
                    "description_zh": getattr(tool, "description_zh", None) if not isinstance(tool, dict) else tool.get("description_zh"),
                    "inputs": getattr(tool, "inputs", None) if not isinstance(tool, dict) else tool.get("inputs", ""),
                    "output_type": getattr(tool, "output_type", None) if not isinstance(tool, dict) else tool.get("output_type", ""),
                    "source": getattr(tool, "source", "local") if not isinstance(tool, dict) else tool.get("source", "local"),
                }
                inputs.append(ContextItemInput(
                    id=f"tool:{name}", type=ContextItemType.TOOL, content=payload,
                    source=(f"tool:{name}",), priority=50,
                    metadata={
                        "render_group": "tools", "language": language,
                        "is_manager": is_manager,
                        "authority": "agent",
                    },
                ))

        summaries = knowledge_base_summaries or []
        if include_knowledge_base and (summaries or knowledge_base_no_indexes):
            is_scoped_knowledge = knowledge_scope is not None
            guidance = composer.render_system_section(
                "knowledge_guidance_scoped" if is_scoped_knowledge else "knowledge_guidance_unscoped"
            ) + "\n"
            heading = load_prompt(language, "agent/context_sections")["retrieved_context"]["knowledge_summary_heading"]
            summary_text = (
                render_knowledge_base_summaries(summaries)
                if summaries else load_prompt(language, "agent/knowledge_scope")["resources"]["no_indexes"]
            )
            inputs.append(ContextItemInput(
                id="knowledge_base:summary", type=ContextItemType.KNOWLEDGE_BASE,
                content={"text": heading + "\n" + guidance + summary_text, "role": "system"},
                source=tuple(f"knowledge_base:{item['index_name']}" for item in summaries), priority=10,
                metadata={"authority": "retrieved"},
            ))

        if include_knowledge_base and knowledge_scope is not None:
            inputs.append(ContextItemInput(
                id="knowledge_scope:resources",
                type=ContextItemType.KNOWLEDGE_BASE,
                content={"text": render_knowledge_scope_resources(language, knowledge_scope), "role": "system"},
                source=("knowledge_scope:runtime",),
                priority=20,
                metadata={"authority": "retrieved"},
            ))

        if is_manager and include_worker_agents and worker_agents:
            for name, agent in worker_agents.items():
                payload = {
                    "name": name,
                    "description": getattr(agent, "description", None) if not isinstance(agent, dict) else agent.get("description", ""),
                    "tools": [getattr(tool, "name", "") for tool in getattr(agent, "tools", ())]
                    if not isinstance(agent, dict) else agent.get("tools", []),
                }
                inputs.append(ContextItemInput(
                    id=f"worker_agent:{name}", type=ContextItemType.WORKER_AGENT, content=payload,
                    source=(f"worker_agent:{name}",), priority=45,
                    metadata={
                        "render_group": "worker_agents", "language": language,
                        "authority": "agent",
                    },
                ))

        if is_manager and include_external_agents and external_a2a_agents:
            for agent_id, agent in external_a2a_agents.items():
                payload = {
                    "agent_id": str(getattr(agent, "agent_id", agent_id) if not isinstance(agent, dict) else agent.get("agent_id", agent_id)),
                    "name": getattr(agent, "name", "") if not isinstance(agent, dict) else agent.get("name", ""),
                    "description": getattr(agent, "description", "") if not isinstance(agent, dict) else agent.get("description", ""),
                    "url": getattr(agent, "url", "") if not isinstance(agent, dict) else agent.get("url", ""),
                }
                inputs.append(ContextItemInput(
                    id=f"external_agent:{payload['agent_id']}", type=ContextItemType.EXTERNAL_AGENT,
                    content=payload, source=(f"external_agent:{payload['agent_id']}",), priority=44,
                    metadata={
                        "render_group": "external_agents", "language": language,
                        "authority": "agent",
                    },
                ))
        if constraint:
            add_system(
                "constraint",
                composer.render_system_section("outline_constraints") + "\n"
                + composer.render_system_section("constraint", constraint=constraint),
                30, 30,
            )
        if not sandbox_workspace_enabled and restricted_python_authorized_imports is not None:
            add_system(
                "restricted_python_execution",
                composer.render_restricted_python_execution(restricted_python_authorized_imports),
                25, 32,
                "platform",
            )
        code_norms = composer.render_system_section("code_norms")
        if not constraint:
            code_norms = composer.render_system_section("outline_constraints") + "\n" + code_norms
        add_system("code_norms", code_norms, 20, 31, "platform")
        if few_shots:
            add_system("footer", composer.render_system_section("footer", few_shots=few_shots), 10, 40)
        return inputs

    def compatibility_templates(self) -> dict[str, Any]:
        """Provide mutable legacy SDK templates without mutating the bundle."""
        result = {key: _thaw(value) for key, value in self.bundle.template.items() if key != "system_sections"}
        result["planning"] = {
            "initial_plan": "", "update_plan_pre_messages": "", "update_plan_post_messages": "",
        }
        if self.bundle.role == "manager":
            result["managed_agent"] = {
                "task": result["manager_agent"]["task"],
                "report": result["manager_agent"]["report"],
            }
        result["system_prompt"] = ""
        return result
