import logging
import logging
import queue
import threading

import yaml
from jinja2 import StrictUndefined, Template
from smolagents import OpenAIServerModel
from smolagents.agents import populate_template
from smolagents.utils import BASE_BUILTIN_MODULES

from consts.model import AgentInfoRequest
from database.agent_db import query_sub_agents, update_agent, \
    query_tools_by_ids
from services.agent_service import get_enable_tool_id_by_agent_id
from utils.config_utils import tenant_config_manager, get_model_name_from_config
from utils.auth_utils import get_current_user_info
from fastapi import Header, Request


# Configure logging
logger = logging.getLogger("prompt_service")


def call_llm_for_system_prompt(user_prompt: str, system_prompt: str, callback=None, tenant_id:str = None) -> str:
    """
    Call LLM to generate system prompt

    Args:
        user_prompt: description of the current task
        system_prompt: system prompt for the LLM

    Returns:
        str: Generated system prompt
    """
    llm_model_config = tenant_config_manager.get_model_config(key="LLM_ID", tenant_id=tenant_id)

    llm = OpenAIServerModel(
        model_id=get_model_name_from_config(llm_model_config) if llm_model_config else "",
        api_base=llm_model_config.get("base_url", ""),
        api_key=llm_model_config.get("api_key", ""),
        temperature=0.3,
        top_p=0.95
    )
    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}]
    try:
        completion_kwargs = llm._prepare_completion_kwargs(
            messages=messages,
            model=llm.model_id,
            temperature=0.3,
            top_p=0.95
        )
        current_request = llm.client.chat.completions.create(stream=True, **completion_kwargs)
        token_join = []
        for chunk in current_request:
            new_token = chunk.choices[0].delta.content
            if new_token is not None:
                token_join.append(new_token)
                current_text = "".join(token_join)
                if callback is not None:
                    callback(current_text)
        return "".join(token_join)
    except Exception as e:
        logger.error(f"Failed to generate prompt from LLM: {str(e)}")
        raise e


def get_prompt_template_path(is_manager: bool, language: str = 'zh') -> str:
    """
    Get the prompt template path based on the agent type and language
    
    Args:
        is_manager: Whether it is a manager mode
        language: Language code ('zh' or 'en')
        
    Returns:
        str: Prompt template file path
    """
    if language == 'en':
        if is_manager:
            return "backend/prompts/manager_system_prompt_template_en.yaml"
        else:
            return "backend/prompts/managed_system_prompt_template_en.yaml"
    else:  # Default to Chinese
        if is_manager:
            return "backend/prompts/manager_system_prompt_template.yaml"
        else:
            return "backend/prompts/managed_system_prompt_template.yaml"

def get_prompt_generate_config_path(language: str = 'zh') -> str:
    """
    Get the prompt generation configuration file path based on the language
    
    Args:
        language: Language code ('zh' or 'en')
        
    Returns:
        str: Prompt generation configuration file path
    """
    if language == 'en':
        return 'backend/prompts/utils/prompt_generate_en.yaml'
    else:  # Default to Chinese
        return 'backend/prompts/utils/prompt_generate.yaml'


def generate_and_save_system_prompt_impl(agent_id: int, task_description: str, authorization: str = Header(None), 
                                       request: Request = None):
    user_id, tenant_id, language = get_current_user_info(authorization, request)

    # Get description of tool and agent
    tool_info_list = get_enabled_tool_description_for_generate_prompt(
        tenant_id=tenant_id, agent_id=agent_id, user_id=user_id
    )
    sub_agent_info_list = get_enabled_sub_agent_description_for_generate_prompt(
        tenant_id=tenant_id, agent_id=agent_id, user_id=user_id
    )

    # 1. Real-time streaming push
    last_system_prompt = None
    for system_prompt in generate_system_prompt(sub_agent_info_list, task_description, tool_info_list, tenant_id, language):
        yield system_prompt
        last_system_prompt = system_prompt

    # 2. Update agent with the final result
    logger.info("Updating agent with business_description and prompt")
    agent_info = AgentInfoRequest(
        agent_id=agent_id,
        business_description=task_description,
        prompt=last_system_prompt
    )
    update_agent(
        agent_id=agent_id,
        agent_info=agent_info,
        tenant_id=tenant_id,
        user_id=user_id
    )
    logger.info("Prompt generation and agent update completed successfully")


def generate_system_prompt(sub_agent_info_list, task_description, tool_info_list, tenant_id: str, language: str = 'zh'):
    prompt_config_path = get_prompt_generate_config_path(language)
    with open(prompt_config_path, "r", encoding="utf-8") as f:
        prompt_for_generate = yaml.safe_load(f)

    # Get app information from environment variables
    default_app_description = 'Nexent 是一个开源智能体SDK和平台' if language == 'zh' else 'Nexent is an open-source agent SDK and platform'
    app_name = tenant_config_manager.get_app_config('APP_NAME', tenant_id=tenant_id) or "Nexent"
    app_description = tenant_config_manager.get_app_config('APP_DESCRIPTION', tenant_id=tenant_id) or default_app_description

    # Add app information to the template variables
    content = join_info_for_generate_system_prompt(prompt_for_generate, sub_agent_info_list, task_description,
                                                   tool_info_list)

    def get_prompt_template():
        template_path = get_prompt_template_path(is_manager=len(sub_agent_info_list) > 0, language=language)
        with open(template_path, "r", encoding="utf-8") as file:
            return yaml.safe_load(file)

    def make_callback(tag):
        def callback_fn(current_text):
            latest[tag] = current_text
            # Notify main thread that new content is available
            produce_queue.put(tag)
        return callback_fn

    def run_and_flag(tag, sys_prompt):
        try:
            call_llm_for_system_prompt(content, sys_prompt, make_callback(tag), tenant_id)
        except Exception as e:
            logger.error(f"Error in {tag} generation: {e}")
        finally:
            stop_flags[tag] = True

    produce_queue = queue.Queue()
    latest = {"duty": "", "constraint": "", "few_shots": ""}
    stop_flags = {"duty": False, "constraint": False, "few_shots": False}
    prompt_template = get_prompt_template()

    threads = []
    logger.info(f"Generating system prompt")
    for tag, sys_prompt in [
        ("duty", prompt_for_generate["DUTY_SYSTEM_PROMPT"]),
        ("constraint", prompt_for_generate["CONSTRAINT_SYSTEM_PROMPT"]),
        ("few_shots", prompt_for_generate["FEW_SHOTS_SYSTEM_PROMPT"])
    ]:
        t = threading.Thread(target=run_and_flag, args=(tag, sys_prompt))
        t.start()
        threads.append(t)

    last_formatted = None
    while not all(stop_flags.values()):
        try:
            produce_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        formatted = populate_template(
            prompt_template["system_prompt"],
            variables={
                "duty": latest["duty"],
                "constraint": latest["constraint"],
                "few_shots": latest["few_shots"],
                "tools": {tool.get("name"): tool for tool in tool_info_list},
                "managed_agents": {sub_agent.get("name"): sub_agent for sub_agent in sub_agent_info_list},
                "authorized_imports": str(BASE_BUILTIN_MODULES),
                "APP_NAME": app_name,
                "APP_DESCRIPTION": app_description
            },
        )
        if formatted != last_formatted:
            yield formatted
            last_formatted = formatted

    for t in threads:
        t.join(timeout=5)


def join_info_for_generate_system_prompt(prompt_for_generate, sub_agent_info_list, task_description, tool_info_list,
                                         app_name=None, app_description=None):
    tool_description = "\n".join(
        [f"- {tool['name']}: {tool['description']} \n 接受输入: {tool['inputs']}\n 返回输出类型: {tool['output_type']}"
         for tool in tool_info_list])
    agent_description = "\n".join(
        [f"- {sub_agent_info['name']}: {sub_agent_info['description']}" for sub_agent_info in sub_agent_info_list])
    # Generate content using template
    compiled_template = Template(prompt_for_generate["USER_PROMPT"], undefined=StrictUndefined)
    content = compiled_template.render({
        "tool_description": tool_description,
        "agent_description": agent_description,
        "task_description": task_description,
        "APP_NAME": app_name,
        "APP_DESCRIPTION": app_description
    })
    return content


def get_enabled_tool_description_for_generate_prompt(agent_id: int, tenant_id: str, user_id: str = None):
    # Get tool information
    logger.info("Fetching tool instances")
    tool_id_list = get_enable_tool_id_by_agent_id(agent_id=agent_id, tenant_id=tenant_id, user_id=user_id)
    tool_info_list = query_tools_by_ids(tool_id_list)
    return tool_info_list


def get_enabled_sub_agent_description_for_generate_prompt(agent_id: int, tenant_id: str, user_id: str = None):
    logger.info("Fetching sub-agents information")
    sub_agent_raw_info_list = query_sub_agents(main_agent_id=agent_id, tenant_id=tenant_id, user_id=user_id)
    logger.info(f"Found {len(sub_agent_raw_info_list)} sub-agents")

    sub_agent_info_list = []
    for sub_agent_raw_info in sub_agent_raw_info_list:
        if not sub_agent_raw_info["enabled"]:
            continue
        sub_agent_info_list.append(sub_agent_raw_info)
    return sub_agent_info_list


def fine_tune_prompt(system_prompt: str, command: str, tenant_id: str, language: str = 'zh'):
    logger.info("Starting prompt fine-tuning")

    try:
        fine_tune_config_path = 'backend/prompts/utils/prompt_fine_tune_en.yaml' if language == 'en' else 'backend/prompts/utils/prompt_fine_tune.yaml'
        
        with open(fine_tune_config_path, "r", encoding="utf-8") as f:
            prompt_for_fine_tune = yaml.safe_load(f)

        compiled_template = Template(prompt_for_fine_tune["FINE_TUNE_USER_PROMPT"], undefined=StrictUndefined)
        content = compiled_template.render({
            "prompt": system_prompt,
            "command": command
        })

        logger.info("Calling LLM for prompt fine-tuning")
        regenerate_prompt = call_llm_for_system_prompt(
            user_prompt=content,
            system_prompt=prompt_for_fine_tune["FINE_TUNE_SYSTEM_PROMPT"],
            tenant_id=tenant_id
        )
        logger.info("Successfully completed prompt fine-tuning")
        return regenerate_prompt

    except Exception as e:
        logger.error(f"Error in prompt fine-tuning process: {str(e)}")
        raise e
