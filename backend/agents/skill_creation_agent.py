"""Skill creation agent module for interactive skill generation."""

import logging
import threading
from typing import List

from nexent.core.agents.agent_model import AgentConfig, AgentRunInfo, ModelConfig, ToolConfig
from nexent.core.agents.run_agent import agent_run_thread
from nexent.core.utils.observer import MessageObserver

logger = logging.getLogger("skill_creation_agent")


def create_skill_creation_agent_config(
    system_prompt: str,
    model_config_list: List[ModelConfig],
    local_skills_dir: str = ""
) -> AgentConfig:
    """
    Create agent config for skill creation with builtin tools.

    Args:
        system_prompt: Custom system prompt to replace smolagent defaults
        model_config_list: List of model configurations

    Returns:
        AgentConfig configured for skill creation
    """
    if not model_config_list:
        raise ValueError("model_config_list cannot be empty")

    first_model = model_config_list[0]

    builtin_tools = [
        ToolConfig(
            class_name="WriteSkillFileTool",
            name="write_skill_file",
            description="Write skill file content to disk",
            source="builtin",
            params={"local_skills_dir": local_skills_dir},
            metadata={},
            inputs="filename: str, content: str",
            output_type="bool"
        ),
        ToolConfig(
            class_name="ReadSkillMdTool",
            name="read_skill_md",
            description="Read skill markdown file content",
            source="builtin",
            params={"local_skills_dir": local_skills_dir},
            metadata={},
            inputs="file_path: str",
            output_type="str"
        )
    ]

    prompt_templates = {
        "system_prompt": system_prompt,
        "managed_agent": {
            "task": "{task}",
            "report": "## {name} Report\n\n{final_answer}"
        },
        "planning": {
            "initial_plan": "",
            "update_plan_pre_messages": "",
            "update_plan_post_messages": ""
        },
        "final_answer": {
            "pre_messages": "",
            "post_messages": ""
        }
    }

    return AgentConfig(
        name="__skill_creator__",
        description="Internal skill creator agent",
        prompt_templates=prompt_templates,
        tools=builtin_tools,
        max_steps=5,
        model_name=first_model.cite_name
    )


def run_skill_creation_agent(
    query: str,
    agent_config: AgentConfig,
    model_config_list: List[ModelConfig],
    observer: MessageObserver,
    stop_event: threading.Event,
) -> None:
    """
    Run the skill creator agent synchronously.

    Args:
        query: User query for the agent
        agent_config: Pre-configured agent config
        model_config_list: List of model configurations
        observer: Message observer for capturing agent output
        stop_event: Threading event for cancellation
    """
    agent_run_info = AgentRunInfo(
        query=query,
        model_config_list=model_config_list,
        observer=observer,
        agent_config=agent_config,
        stop_event=stop_event
    )

    agent_run_thread(agent_run_info)


def create_simple_skill_from_request(
    system_prompt: str,
    user_prompt: str,
    model_config_list: List[ModelConfig],
    observer: MessageObserver,
    stop_event: threading.Event,
    local_skills_dir: str = ""
) -> None:
    """
    Run skill creation agent to create a skill interactively.

    The agent will write the skill content to tmp.md in local_skills_dir.
    Frontend should read tmp.md after agent completes to get the skill content.

    Args:
        system_prompt: System prompt with skill creation instructions
        user_prompt: User's skill description request
        model_config_list: List of model configurations
        observer: Message observer for capturing agent output
        stop_event: Threading event for cancellation
        local_skills_dir: Path to local skills directory for file operations
    """
    agent_config = create_skill_creation_agent_config(
        system_prompt=system_prompt,
        model_config_list=model_config_list,
        local_skills_dir=local_skills_dir
    )

    thread_agent = threading.Thread(
        target=run_skill_creation_agent,
        args=(user_prompt, agent_config, model_config_list, observer, stop_event)
    )
    thread_agent.start()
    thread_agent.join()
