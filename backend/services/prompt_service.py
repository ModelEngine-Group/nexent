import json
import logging
import queue
import threading

from jinja2 import StrictUndefined, Template
from smolagents import OpenAIServerModel

from consts.const import LANGUAGE, MODEL_CONFIG_MAPPING, MESSAGE_ROLE, THINK_END_PATTERN, THINK_START_PATTERN
from consts.model import AgentInfoRequest
from database.agent_db import update_agent, query_sub_agents_id_list, search_agent_info_by_agent_id
from database.model_management_db import get_model_by_model_id
from database.tool_db import query_tools_by_ids
from services.agent_service import get_enable_tool_id_by_agent_id
from utils.config_utils import tenant_config_manager, get_model_name_from_config
from utils.prompt_template_utils import get_prompt_generate_prompt_template

# Configure logging
logger = logging.getLogger("prompt_service")


def _process_thinking_tokens(new_token: str, is_thinking: bool, token_join: list, callback=None) -> bool:
    """
    Process tokens to filter out thinking content between <think> and </think> tags

    Args:
        new_token: Current token from LLM stream
        is_thinking: Current thinking state
        token_join: List to accumulate non-thinking tokens
        callback: Callback function for streaming output

    Returns:
        bool: updated_is_thinking
    """
    # Handle thinking mode
    if is_thinking:
        return not (THINK_END_PATTERN in new_token)

    # Handle start of thinking
    if THINK_START_PATTERN in new_token:
        return True

    # Normal token processing
    token_join.append(new_token)
    if callback:
        callback("".join(token_join))

    return False


def call_llm_for_system_prompt(model_id: int, user_prompt: str, system_prompt: str, callback=None, tenant_id: str = None) -> str:
    """
    Call LLM to generate system prompt

    Args:
        model_id: select model for generate prompt
        user_prompt: description of the current task
        system_prompt: system prompt for the LLM
        callback: callback function
        tenant_id: tenant id

    Returns:
        str: Generated system prompt
    """

    llm_model_config = get_model_by_model_id(model_id=model_id, tenant_id=tenant_id)

    llm = OpenAIServerModel(
        model_id=get_model_name_from_config(
            llm_model_config) if llm_model_config else "",
        api_base=llm_model_config.get("base_url", ""),
        api_key=llm_model_config.get("api_key", ""),
        temperature=0.3,
        top_p=0.95
    )
    messages = [{"role": MESSAGE_ROLE["SYSTEM"], "content": system_prompt},
                {"role": MESSAGE_ROLE["USER"], "content": user_prompt}]
    try:
        completion_kwargs = llm._prepare_completion_kwargs(
            messages=messages,
            model=llm.model_id,
            temperature=0.3,
            top_p=0.95
        )
        current_request = llm.client.chat.completions.create(
            stream=True, **completion_kwargs)
        token_join = []
        is_thinking = False
        for chunk in current_request:
            new_token = chunk.choices[0].delta.content
            if new_token is not None:
                is_thinking = _process_thinking_tokens(
                    new_token, is_thinking, token_join, callback
                )
        return "".join(token_join)
    except Exception as e:
        logger.error(f"Failed to generate prompt from LLM: {str(e)}")
        raise e


def gen_system_prompt_streamable(agent_id: int, model_id: int, task_description: str, user_id: str, tenant_id: str, language: str):
    for system_prompt in generate_and_save_system_prompt_impl(
        agent_id=agent_id,
        model_id=model_id,
        task_description=task_description,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language
    ):
        # SSE format, each message ends with \n\n
        yield f"data: {json.dumps({'success': True, 'data': system_prompt}, ensure_ascii=False)}\n\n"


def generate_and_save_system_prompt_impl(agent_id: int,
                                         model_id: int,
                                         task_description: str,
                                         user_id: str,
                                         tenant_id: str,
                                         language: str):
    # Get description of tool and agent
    tool_info_list = get_enabled_tool_description_for_generate_prompt(
        tenant_id=tenant_id, agent_id=agent_id)
    sub_agent_info_list = get_enabled_sub_agent_description_for_generate_prompt(
        tenant_id=tenant_id, agent_id=agent_id)

    # 1. Real-time streaming push
    final_results = {"duty": "", "constraint": "", "few_shots": "", "agent_var_name": "", "agent_display_name": "",
                     "agent_description": ""}
    for result_data in generate_system_prompt(sub_agent_info_list, task_description, tool_info_list, tenant_id,
                                              model_id, language):
        # Update final results
        final_results[result_data["type"]] = result_data["content"]
        yield result_data

    # 2. Update agent with the final result
    logger.info("Updating agent with business_description and prompt segments")
    agent_info = AgentInfoRequest(
        agent_id=agent_id,
        business_description=task_description,
        duty_prompt=final_results["duty"],
        constraint_prompt=final_results["constraint"],
        few_shots_prompt=final_results["few_shots"],
        name=final_results["agent_var_name"],
        display_name=final_results["agent_display_name"],
        description=final_results["agent_description"]
    )
    update_agent(
        agent_id=agent_id,
        agent_info=agent_info,
        tenant_id=tenant_id,
        user_id=user_id
    )
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
                "content": latest[tag],
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
