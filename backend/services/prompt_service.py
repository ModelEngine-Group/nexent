import json
import logging
import queue
import threading
from typing import Optional, List

from jinja2 import StrictUndefined, Template

from consts.const import LANGUAGE
from consts.model import AgentInfoRequest
from database.agent_db import update_agent, search_agent_info_by_agent_id, query_all_agent_info_by_tenant_id, \
    query_sub_agents_id_list
from database.tool_db import query_tools_by_ids
from services.agent_service import (
    get_enable_tool_id_by_agent_id,
    _check_agent_name_duplicate,
    _check_agent_display_name_duplicate,
    _regenerate_agent_name_with_llm,
    _regenerate_agent_display_name_with_llm,
    _generate_unique_agent_name_with_suffix,
    _generate_unique_display_name_with_suffix
)
from utils.llm_utils import call_llm_for_system_prompt
from utils.prompt_template_utils import get_prompt_generate_prompt_template

# Configure logging
logger = logging.getLogger("prompt_service")


def gen_system_prompt_streamable(agent_id: int, model_id: int, task_description: str, user_id: str, tenant_id: str, language: str, tool_ids: Optional[List[int]] = None, sub_agent_ids: Optional[List[int]] = None):
    for system_prompt in generate_and_save_system_prompt_impl(
        agent_id=agent_id,
        model_id=model_id,
        task_description=task_description,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
        tool_ids=tool_ids,
        sub_agent_ids=sub_agent_ids
    ):
        # SSE format, each message ends with \n\n
        yield f"data: {json.dumps({'success': True, 'data': system_prompt}, ensure_ascii=False)}\n\n"


def generate_and_save_system_prompt_impl(agent_id: int,
                                         model_id: int,
                                         task_description: str,
                                         user_id: str,
                                         tenant_id: str,
                                         language: str,
                                         tool_ids: Optional[List[int]] = None,
                                         sub_agent_ids: Optional[List[int]] = None):
    # Get description of tool and agent from frontend-provided IDs
    # Frontend always provides tool_ids and sub_agent_ids (could be empty arrays)

    # Handle tool IDs
    if tool_ids and len(tool_ids) > 0:
        tool_info_list = query_tools_by_ids(tool_ids)
        logger.debug(f"Using frontend-provided tool IDs: {tool_ids}")
    else:
        logger.debug("No tools selected (empty tool_ids list)")
        # If no tool IDs provided, get enabled tools from database
        tool_info_list = get_enabled_tool_description_for_generate_prompt(
            tenant_id=tenant_id, agent_id=agent_id)

    # Handle sub-agent IDs
    if sub_agent_ids and len(sub_agent_ids) > 0:
        sub_agent_info_list = []
        for sub_agent_id in sub_agent_ids:
            try:
                sub_agent_info = search_agent_info_by_agent_id(
                    agent_id=sub_agent_id, tenant_id=tenant_id)
                sub_agent_info_list.append(sub_agent_info)
            except Exception as e:
                logger.warning(
                    f"Failed to get sub-agent info for agent_id {sub_agent_id}: {str(e)}")
        logger.debug(f"Using frontend-provided sub-agent IDs: {sub_agent_ids}")
    else:
        logger.debug("No sub-agents selected (empty sub_agent_ids list)")
        # If no sub-agent IDs provided, get enabled sub-agents from database
        sub_agent_info_list = get_enabled_sub_agent_description_for_generate_prompt(
            tenant_id=tenant_id, agent_id=agent_id)

    # 1. Real-time streaming push
    final_results = {"duty": "", "constraint": "", "few_shots": "", "agent_var_name": "", "agent_display_name": "",
                     "agent_description": ""}

    # Get all existing agent names and display names for duplicate checking (only if not in create mode)
    all_agents = query_all_agent_info_by_tenant_id(tenant_id)
    existing_names = [
        agent.get("name")
        for agent in all_agents
        if agent.get("name") and agent.get("agent_id") != agent_id
    ]
    existing_display_names = [
        agent.get("display_name")
        for agent in all_agents
        if agent.get("display_name") and agent.get("agent_id") != agent_id
    ]

    # Collect results and yield non-name fields immediately, but hold name fields for duplicate checking
    for result_data in generate_system_prompt(sub_agent_info_list, task_description, tool_info_list, tenant_id,
                                              model_id, language):
        result_type = result_data["type"]
        final_results[result_type] = result_data["content"]

        # Yield non-name fields immediately
        if result_type not in ["agent_var_name", "agent_display_name"]:
            yield result_data
        else:
            # If name field is complete, check for duplicates and regenerate if needed before yielding
            if result_data.get("is_complete", False):
                if result_type == "agent_var_name":
                    agent_name = final_results["agent_var_name"]
                    # Check and regenerate name if duplicate
                    if _check_agent_name_duplicate(
                        agent_name,
                        tenant_id=tenant_id,
                        exclude_agent_id=agent_id,
                        agents_cache=all_agents
                    ):
                        logger.info(f"Agent name '{agent_name}' already exists, regenerating with LLM")
                        try:
                            agent_name = _regenerate_agent_name_with_llm(
                                original_name=agent_name,
                                existing_names=existing_names,
                                task_description=task_description,
                                model_id=model_id,
                                tenant_id=tenant_id,
                                language=language,
                                agents_cache=all_agents,
                                exclude_agent_id=agent_id
                            )
                            logger.info(f"Regenerated agent name: '{agent_name}'")
                            final_results["agent_var_name"] = agent_name
                        except Exception as e:
                            logger.error(f"Failed to regenerate agent name with LLM: {str(e)}, using fallback")
                            # Fallback: add suffix
                            agent_name = _generate_unique_agent_name_with_suffix(
                                agent_name,
                                tenant_id=tenant_id,
                                agents_cache=all_agents,
                                exclude_agent_id=agent_id
                            )
                            final_results["agent_var_name"] = agent_name

                    # Yield the (possibly regenerated) name
                    yield {
                        "type": "agent_var_name",
                        "content": final_results["agent_var_name"],
                        "is_complete": True
                    }

                elif result_type == "agent_display_name":
                    agent_display_name = final_results["agent_display_name"]
                    # Check and regenerate display_name if duplicate
                    if _check_agent_display_name_duplicate(
                        agent_display_name,
                        tenant_id=tenant_id,
                        exclude_agent_id=agent_id,
                        agents_cache=all_agents
                    ):
                        logger.info(f"Agent display_name '{agent_display_name}' already exists, regenerating with LLM")
                        try:
                            agent_display_name = _regenerate_agent_display_name_with_llm(
                                original_display_name=agent_display_name,
                                existing_display_names=existing_display_names,
                                task_description=task_description,
                                model_id=model_id,
                                tenant_id=tenant_id,
                                language=language,
                                agents_cache=all_agents,
                                exclude_agent_id=agent_id
                            )
                            logger.info(f"Regenerated agent display_name: '{agent_display_name}'")
                            final_results["agent_display_name"] = agent_display_name
                        except Exception as e:
                            logger.error(f"Failed to regenerate agent display_name with LLM: {str(e)}, using fallback")
                            # Fallback: add suffix
                            agent_display_name = _generate_unique_display_name_with_suffix(
                                agent_display_name,
                                tenant_id=tenant_id,
                                agents_cache=all_agents,
                                exclude_agent_id=agent_id
                            )
                            final_results["agent_display_name"] = agent_display_name

                    # Yield the (possibly regenerated) display_name
                    yield {
                        "type": "agent_display_name",
                        "content": final_results["agent_display_name"],
                        "is_complete": True
                    }

    # 2. Update agent with the final result (skip in create mode)
    if agent_id == 0:
        logger.info("Skipping agent update in create mode (agent_id=0)")
    else:
        logger.info(
            "Updating agent with business_description and prompt segments")
        logger.info("Prompt generation and agent update completed successfully")


def generate_system_prompt(sub_agent_info_list, task_description, tool_info_list, tenant_id: str, model_id: int, language: str = LANGUAGE["ZH"]):
    """Main function for generating system prompts"""
    prompt_for_generate = get_prompt_generate_prompt_template(language)

    # Prepare content for generating system prompts
    content = join_info_for_generate_system_prompt(
        prompt_for_generate=prompt_for_generate,
        sub_agent_info_list=sub_agent_info_list,
        task_description=task_description,
        tool_info_list=tool_info_list,
        language=language
    )

    # Initialize state
    produce_queue = queue.Queue()
    latest = {"duty": "", "constraint": "", "few_shots": "",
              "agent_var_name": "", "agent_display_name": "", "agent_description": ""}
    stop_flags = {"duty": False, "constraint": False, "few_shots": False,
                  "agent_var_name": False, "agent_display_name": False, "agent_description": False}

    # Start all generation threads
    threads = _start_generation_threads(
        content, prompt_for_generate, produce_queue, latest, stop_flags, tenant_id, model_id)

    # Stream results
    yield from _stream_results(produce_queue, latest, stop_flags, threads)


def _start_generation_threads(content, prompt_for_generate, produce_queue, latest, stop_flags, tenant_id, model_id):
    """Start all prompt generation threads"""
    def make_callback(tag):
        def callback_fn(current_text):
            latest[tag] = current_text
            produce_queue.put(tag)
        return callback_fn

    def run_and_flag(tag, sys_prompt):
        try:
            call_llm_for_system_prompt(
                model_id, content, sys_prompt, make_callback(tag), tenant_id)
        except Exception as e:
            logger.error(f"Error in {tag} generation: {e}")
        finally:
            stop_flags[tag] = True

    threads = []
    logger.info("Generating system prompt")

    prompt_configs = [
        ("duty", prompt_for_generate["DUTY_SYSTEM_PROMPT"]),
        ("constraint", prompt_for_generate["CONSTRAINT_SYSTEM_PROMPT"]),
        ("few_shots", prompt_for_generate["FEW_SHOTS_SYSTEM_PROMPT"]),
        ("agent_var_name",
         prompt_for_generate["AGENT_VARIABLE_NAME_SYSTEM_PROMPT"]),
        ("agent_display_name",
         prompt_for_generate["AGENT_DISPLAY_NAME_SYSTEM_PROMPT"]),
        ("agent_description",
         prompt_for_generate["AGENT_DESCRIPTION_SYSTEM_PROMPT"])
    ]

    for tag, sys_prompt in prompt_configs:
        thread = threading.Thread(target=run_and_flag, args=(tag, sys_prompt))
        thread.start()
        threads.append(thread)

    return threads


def _stream_results(produce_queue, latest, stop_flags, threads):
    """Stream prompt generation results"""

    # Real-time streaming output for the first three sections
    last_results = {"duty": "", "constraint": "", "few_shots": "",
                    "agent_var_name": "", "agent_display_name": "", "agent_description": ""}

    while not all(stop_flags.values()):
        try:
            produce_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        # Check if there is new content (only stream the first three sections)
        for tag in ["duty", "constraint", "few_shots"]:
            if latest[tag] != last_results[tag]:
                result_data = {
                    "type": tag,
                    "content": latest[tag],
                    "is_complete": stop_flags[tag]
                }
                yield result_data
                last_results[tag] = latest[tag]

    # Wait for all threads to complete
    for thread in threads:
        thread.join(timeout=5)

    # Output final results
    all_tags = ["duty", "constraint", "few_shots",
                "agent_var_name", "agent_display_name", "agent_description"]
    for tag in all_tags:
        if stop_flags[tag]:
            # Clean up content for specific tags
            if tag in {'agent_var_name', 'agent_display_name', 'agent_description'}:
                latest[tag] = latest[tag].strip().replace('\n', '')

            result_data = {
                "type": tag,
                "content": latest[tag].strip(),
                "is_complete": True
            }
            yield result_data
            last_results[tag] = latest[tag]


def join_info_for_generate_system_prompt(prompt_for_generate, sub_agent_info_list, task_description, tool_info_list, language: str = LANGUAGE["ZH"]):
    input_label = "Inputs" if language == 'en' else "接受输入"
    output_label = "Output type" if language == 'en' else "返回输出类型"

    tool_description = "\n".join(
        [f"- {tool['name']}: {tool['description']} \n {input_label}: {tool['inputs']}\n {output_label}: {tool['output_type']}"
         for tool in tool_info_list])
    assistant_description = "\n".join(
        [f"- {sub_agent_info['name']}: {sub_agent_info['description']}" for sub_agent_info in sub_agent_info_list])
    # Generate content using template
    content = Template(prompt_for_generate["USER_PROMPT"], undefined=StrictUndefined).render({
        "task_description": task_description,
        "tool_description": tool_description,
        "assistant_description": assistant_description
    })
    return content


def get_enabled_tool_description_for_generate_prompt(agent_id: int, tenant_id: str):
    # Get tool information
    logger.info("Fetching tool instances")
    tool_id_list = get_enable_tool_id_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id)
    tool_info_list = query_tools_by_ids(tool_id_list)
    return tool_info_list


def get_enabled_sub_agent_description_for_generate_prompt(agent_id: int, tenant_id: str):
    logger.info("Fetching sub-agents information")

    sub_agent_id_list = query_sub_agents_id_list(
        main_agent_id=agent_id, tenant_id=tenant_id)

    sub_agent_info_list = []
    for sub_agent_id in sub_agent_id_list:
        sub_agent_info = search_agent_info_by_agent_id(
            agent_id=sub_agent_id, tenant_id=tenant_id)

        sub_agent_info_list.append(sub_agent_info)
    return sub_agent_info_list
