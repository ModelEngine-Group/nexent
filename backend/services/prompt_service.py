import json
import logging
import queue
import threading
from typing import Optional, List

from jinja2 import StrictUndefined, Template

from consts.const import LANGUAGE
from consts.error_code import ErrorCode
from consts.error_message import ErrorMessage
from consts.exceptions import AppException
from database.agent_db import search_agent_info_by_agent_id, query_all_agent_info_by_tenant_id, \
    query_sub_agents_id_list
from database.model_management_db import get_model_by_model_id
from database.knowledge_db import get_knowledge_name_map_by_index_names
from database.tool_db import query_tools_by_ids, query_tool_instances_by_id
from services.agent_service import (
    get_enable_tool_id_by_agent_id,
    _check_agent_name_duplicate,
    _check_agent_display_name_duplicate,
    _regenerate_agent_name_with_llm,
    _regenerate_agent_display_name_with_llm,
    _generate_unique_agent_name_with_suffix,
    _generate_unique_display_name_with_suffix
)
from services.prompt_template_service import resolve_prompt_generate_template
from utils.llm_utils import call_llm_for_system_prompt
from utils.prompt_template_utils import (
    get_prompt_generate_prompt_template,
    get_prompt_optimize_prompt_template,
)

# Configure logging
logger = logging.getLogger("prompt_service")

PROMPT_SECTION_TYPE_TITLES = {
    LANGUAGE["ZH"]: {
        "duty": "智能体角色",
        "constraint": "使用要求",
        "few_shots": "示例",
    },
    LANGUAGE["EN"]: {
        "duty": "Agent Role",
        "constraint": "Usage Requirements",
        "few_shots": "Few Shots",
    },
}


def gen_system_prompt_streamable(agent_id: int, model_id: int, task_description: str, user_id: str, tenant_id: str, language: str, prompt_template_id: Optional[int] = None, tool_ids: Optional[List[int]] = None, sub_agent_ids: Optional[List[int]] = None, knowledge_base_display_names: Optional[List[str]] = None, has_selected_resources: bool = True):
    try:
        for system_prompt in generate_and_save_system_prompt_impl(
            agent_id=agent_id,
            model_id=model_id,
            task_description=task_description,
            user_id=user_id,
            tenant_id=tenant_id,
            language=language,
            prompt_template_id=prompt_template_id,
            tool_ids=tool_ids,
            sub_agent_ids=sub_agent_ids,
            knowledge_base_display_names=knowledge_base_display_names,
            has_selected_resources=has_selected_resources,
        ):
            # SSE format, each message ends with \n\n
            yield f"data: {json.dumps({'success': True, 'data': system_prompt}, ensure_ascii=False)}\n\n"
    except Exception as e:
        # Catch model unavailable or other errors and return error through SSE
        logger.error(f"Error generating prompt: {e}")
        # Use original error code if it's an AppException, otherwise use default
        if isinstance(e, AppException):
            error_code = e.error_code
            error_message = e.message
        else:
            error_code = ErrorCode.MODEL_PROMPT_GENERATION_FAILED
            error_message = ErrorMessage.get_message(error_code)
        yield f"data: {json.dumps({'success': False, 'error': {'code': error_code.value, 'message': error_message}}, ensure_ascii=False)}\n\n"


def generate_and_save_system_prompt_impl(agent_id: int,
                                         model_id: int,
                                         task_description: str,
                                         user_id: str,
                                         tenant_id: str,
                                         language: str,
                                         prompt_template_id: Optional[int] = None,
                                         tool_ids: Optional[List[int]] = None,
                                         sub_agent_ids: Optional[List[int]] = None,
                                         knowledge_base_display_names: Optional[List[str]] = None,
                                         has_selected_resources: bool = True):
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

    # Get knowledge base display names for few-shot examples
    # Priority: frontend-provided > database query
    if knowledge_base_display_names:
        logger.debug(f"Using frontend-provided knowledge base display names: {knowledge_base_display_names}")
    else:
        knowledge_base_display_names = get_knowledge_base_display_names(
            tool_info_list=tool_info_list,
            agent_id=agent_id,
            tenant_id=tenant_id
        )
        logger.debug(f"Using database query for knowledge base display names: {knowledge_base_display_names}")

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

    # Re-evaluate has_selected_resources based on the actual resolved lists.
    # The frontend value indicates user intent, but after resolving tool_ids/sub_agent_ids
    # the actual lists are the source of truth. If both lists are empty, constraint and
    # few_shots sections have no meaningful content to generate, so we force False.
    has_selected_resources = bool(tool_info_list or sub_agent_info_list)
    logger.info(
        "Resolved resource availability: tools=%d, sub_agents=%d, has_selected_resources=%s",
        len(tool_info_list),
        len(sub_agent_info_list),
        has_selected_resources,
    )

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
    for result_data in generate_system_prompt(
        sub_agent_info_list,
        task_description,
        tool_info_list,
        tenant_id,
        user_id,
        model_id,
        language,
        prompt_template_id,
        knowledge_base_display_names,
            has_selected_resources
    ):
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
                                exclude_agent_id=agent_id,
                                prompt_template_id=prompt_template_id,
                                user_id=user_id,
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
                                exclude_agent_id=agent_id,
                                prompt_template_id=prompt_template_id,
                                user_id=user_id,
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

    # Check if any content was generated - if all fields are empty, model likely failed
    all_fields = ["duty", "constraint", "few_shots",
                  "agent_var_name", "agent_display_name", "agent_description"]
    has_content = any(final_results.get(field, "").strip()
                      for field in all_fields)
    if not has_content:
        raise Exception("Failed to generate prompt content.")

def optimize_prompt_section_impl(
    agent_id: int,
    model_id: int,
    task_description: str,
    tenant_id: str,
    language: str,
    section_type: str,
    section_title: str,
    current_content: str,
    feedback: str,
    tool_ids: Optional[List[int]] = None,
    sub_agent_ids: Optional[List[int]] = None,
    knowledge_base_display_names: Optional[List[str]] = None,
) -> dict:
    normalized_section_type = (section_type or "").strip()
    if normalized_section_type not in {"duty", "constraint", "few_shots"}:
        raise AppException(
            ErrorCode.COMMON_PARAMETER_INVALID,
            "Unsupported prompt section type."
        )

    if not (current_content or "").strip():
        raise AppException(
            ErrorCode.COMMON_MISSING_REQUIRED_FIELD,
            "Current section content is required."
        )

    if not (feedback or "").strip():
        raise AppException(
            ErrorCode.COMMON_MISSING_REQUIRED_FIELD,
            "Optimization feedback is required."
        )

    tool_info_list = _resolve_prompt_generation_tools(
        agent_id=agent_id,
        tenant_id=tenant_id,
        tool_ids=tool_ids,
    )
    knowledge_base_display_names = _resolve_knowledge_base_display_names(
        agent_id=agent_id,
        tenant_id=tenant_id,
        tool_info_list=tool_info_list,
        knowledge_base_display_names=knowledge_base_display_names,
    )
    sub_agent_info_list = _resolve_prompt_generation_sub_agents(
        agent_id=agent_id,
        tenant_id=tenant_id,
        sub_agent_ids=sub_agent_ids,
    )

    prompt_template = get_prompt_optimize_prompt_template(language)
    prompt_context = join_info_for_optimize_prompt_section(
        prompt_for_optimize=prompt_template,
        section_type=normalized_section_type,
        section_title=section_title or _default_prompt_section_title(normalized_section_type, language),
        task_description=task_description,
        current_content=current_content,
        feedback=feedback,
        tool_info_list=tool_info_list,
        sub_agent_info_list=sub_agent_info_list,
        language=language,
        knowledge_base_display_names=knowledge_base_display_names,
    )

    optimized_content = call_llm_for_system_prompt(
        model_id=model_id,
        user_prompt=prompt_context,
        system_prompt=prompt_template["OPTIMIZE_SYSTEM_PROMPT"],
        tenant_id=tenant_id,
    ).strip()

    if not optimized_content:
        raise AppException(ErrorCode.MODEL_PROMPT_GENERATION_FAILED)

    return {
        "section_type": normalized_section_type,
        "section_title": section_title or _default_prompt_section_title(normalized_section_type, language),
        "original_content": current_content,
        "optimized_content": optimized_content,
    }


def generate_system_prompt(sub_agent_info_list, task_description, tool_info_list, tenant_id: str, user_id: str, model_id: int, language: str = LANGUAGE["ZH"], prompt_template_id: Optional[int] = None, knowledge_base_display_names: Optional[List[str]] = None, has_selected_resources: bool = True):
    """Main function for generating system prompts"""
    prompt_for_generate = resolve_prompt_generate_template(
        tenant_id=tenant_id,
        user_id=user_id,
        language=language,
        prompt_template_id=prompt_template_id,
    )

    # Prepare content for generating system prompts
    content = join_info_for_generate_system_prompt(
        prompt_for_generate=prompt_for_generate,
        sub_agent_info_list=sub_agent_info_list,
        task_description=task_description,
        tool_info_list=tool_info_list,
        language=language,
        knowledge_base_display_names=knowledge_base_display_names,
        has_selected_resources=has_selected_resources,
    )

    # Initialize state
    produce_queue = queue.Queue()
    latest = {"duty": "", "constraint": "", "few_shots": "",
              "agent_var_name": "", "agent_display_name": "", "agent_description": ""}
    stop_flags = {"duty": False, "constraint": False, "few_shots": False,
                  "agent_var_name": False, "agent_display_name": False, "agent_description": False}

    # Get model concurrency limit to control the number of concurrent LLM calls
    # If None or >= 6, no limit (all 6 calls run concurrently)
    # If < 6, use semaphore to limit concurrent calls
    model_config = get_model_by_model_id(model_id, tenant_id)
    concurrency_limit = model_config.get("concurrency_limit") if model_config else None

    # Start all generation threads with concurrency control
    threads, error_holder = _start_generation_threads(
        content, prompt_for_generate, produce_queue, latest, stop_flags, tenant_id, model_id,
        has_selected_resources,
        concurrency_limit=concurrency_limit
    )

    # Stream results
    yield from _stream_results(produce_queue, latest, stop_flags, threads, error_holder)


def _resolve_prompt_generation_tools(
    agent_id: int,
    tenant_id: str,
    tool_ids: Optional[List[int]] = None,
) -> List[dict]:
    if tool_ids and len(tool_ids) > 0:
        logger.debug(f"Using frontend-provided tool IDs: {tool_ids}")
        return query_tools_by_ids(tool_ids)

    logger.debug("No tools selected (empty tool_ids list)")
    return get_enabled_tool_description_for_generate_prompt(
        tenant_id=tenant_id, agent_id=agent_id
    )


def _resolve_knowledge_base_display_names(
    agent_id: int,
    tenant_id: str,
    tool_info_list: List[dict],
    knowledge_base_display_names: Optional[List[str]] = None,
) -> Optional[List[str]]:
    if knowledge_base_display_names:
        logger.debug(
            f"Using frontend-provided knowledge base display names: {knowledge_base_display_names}"
        )
        return knowledge_base_display_names

    resolved_names = get_knowledge_base_display_names(
        tool_info_list=tool_info_list,
        agent_id=agent_id,
        tenant_id=tenant_id
    )
    logger.debug(f"Using database query for knowledge base display names: {resolved_names}")
    return resolved_names


def _resolve_prompt_generation_sub_agents(
    agent_id: int,
    tenant_id: str,
    sub_agent_ids: Optional[List[int]] = None,
) -> List[dict]:
    if sub_agent_ids and len(sub_agent_ids) > 0:
        sub_agent_info_list = []
        for sub_agent_id in sub_agent_ids:
            try:
                sub_agent_info = search_agent_info_by_agent_id(
                    agent_id=sub_agent_id, tenant_id=tenant_id)
                sub_agent_info_list.append(sub_agent_info)
            except Exception as exc:
                logger.warning(
                    f"Failed to get sub-agent info for agent_id {sub_agent_id}: {str(exc)}"
                )
        logger.debug(f"Using frontend-provided sub-agent IDs: {sub_agent_ids}")
        return sub_agent_info_list

    logger.debug("No sub-agents selected (empty sub_agent_ids list)")
    return get_enabled_sub_agent_description_for_generate_prompt(
        tenant_id=tenant_id, agent_id=agent_id
    )

def _start_generation_threads(content, prompt_for_generate, produce_queue, latest, stop_flags, tenant_id, model_id,
                                has_selected_resources = True, concurrency_limit: Optional[int] = None):
    """Start all prompt generation threads with optional concurrency control."""
    # Shared error tracking across threads
    error_holder = {"error": None}

    # Total number of generation tasks
    total_tasks = 6

    # Determine effective concurrency limit
    # None means unlimited, 0 or negative means unlimited
    if concurrency_limit is None or concurrency_limit <= 0 or concurrency_limit >= total_tasks:
        effective_limit = None
    else:
        effective_limit = concurrency_limit

    # Use semaphore if concurrency is limited
    semaphore = threading.Semaphore(effective_limit) if effective_limit else None
    if semaphore:
        logger.info(f"Using concurrency limit of {effective_limit} for prompt generation (total tasks: {total_tasks})")
    else:
        logger.info("Using unlimited concurrency for prompt generation")

    def make_callback(tag):
        def callback_fn(current_text):
            latest[tag] = current_text
            produce_queue.put(tag)
        return callback_fn

    def run_and_flag(tag, sys_prompt):
        try:
            # Acquire semaphore before starting (if limited)
            if semaphore:
                semaphore.acquire()
            try:
                call_llm_for_system_prompt(
                    model_id, content, sys_prompt, make_callback(tag), tenant_id)
            finally:
                # Always release semaphore after completion
                if semaphore:
                    semaphore.release()
        except Exception as e:
            logger.error(f"Error in {tag} generation: {e}")
            error_holder["error"] = e
        finally:
            stop_flags[tag] = True

    threads = []
    logger.info("Generating system prompt")

    # Base sections always generated
    prompt_configs = [
        ("duty", prompt_for_generate["duty_system_prompt"]),
        ("agent_var_name",
         prompt_for_generate["agent_variable_name_system_prompt"]),
        ("agent_display_name",
         prompt_for_generate["agent_display_name_system_prompt"]),
        ("agent_description",
         prompt_for_generate["agent_description_system_prompt"])
    ]

    # Constraint and few_shots sections are only generated when tools or sub-agents are selected
    if has_selected_resources:
        prompt_configs.extend([
            ("constraint", prompt_for_generate["constraint_system_prompt"]),
            ("few_shots", prompt_for_generate["few_shots_system_prompt"]),
        ])
    else:
        logger.info("Skipping constraint and few_shots generation: no tools or sub-agents selected")
        # Mark these sections as already complete with empty content
        stop_flags["constraint"] = True
        stop_flags["few_shots"] = True
        latest["constraint"] = ""
        latest["few_shots"] = ""

    for tag, sys_prompt in prompt_configs:
        thread = threading.Thread(target=run_and_flag, args=(tag, sys_prompt))
        thread.start()
        threads.append(thread)

    return threads, error_holder


def _stream_results(produce_queue, latest, stop_flags, threads, error_holder):
    """Stream prompt generation results"""

    # Real-time streaming output for the first three sections
    last_results = {"duty": "", "constraint": "", "few_shots": "",
                    "agent_var_name": "", "agent_display_name": "", "agent_description": ""}

    while not all(stop_flags.values()):
        # Check if error occurred in any thread - raise immediately
        if error_holder.get("error"):
            # Wait for threads to finish
            for thread in threads:
                thread.join(timeout=5)
            raise error_holder["error"]

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

    # Check if error occurred before final output
    if error_holder.get("error"):
        raise error_holder["error"]

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


def join_info_for_generate_system_prompt(prompt_for_generate, sub_agent_info_list, task_description, tool_info_list, language: str = LANGUAGE["ZH"], knowledge_base_display_names: Optional[List[str]] = None, has_selected_resources: bool = True):
    input_label = "Inputs" if language == 'en' else "接受输入"
    output_label = "Output type" if language == 'en' else "返回输出类型"

    tool_description = "\n".join(
        [f"- {tool['name']}: {tool['description']} \n {input_label}: {tool['inputs']}\n {output_label}: {tool['output_type']}"
         for tool in tool_info_list])
    assistant_description = "\n".join(
        [f"- {sub_agent_info['name']}: {sub_agent_info['description']}" for sub_agent_info in sub_agent_info_list])

    # Build template context
    template_context = {
        "task_description": task_description,
        "tool_description": tool_description,
        "assistant_description": assistant_description,
        # Always include knowledge_base_names to avoid StrictUndefined errors in template.
        # An empty string is falsy, so the {% if knowledge_base_names %} block will be skipped.
        "knowledge_base_names": "",
        # Flag indicating whether tools or sub-agents are selected;
        # templates use this to suppress boilerplate in constraint/few_shots sections
        "has_selected_resources": has_selected_resources,
    }

    # Always add knowledge_base_names to context (empty string when not available).
    # This is necessary because Jinja2 StrictUndefined raises an error for any
    # undefined variable, even inside an {% if %} block.
    if knowledge_base_display_names:
        kb_names_str = ", ".join(f'"{name}"' for name in knowledge_base_display_names)
    else:
        kb_names_str = ""
    template_context["knowledge_base_names"] = kb_names_str

    # Generate content using template
    content = Template(prompt_for_generate["user_prompt"], undefined=StrictUndefined).render(template_context)
    return content


def join_info_for_optimize_prompt_section(
    prompt_for_optimize,
    section_type: str,
    section_title: str,
    task_description: str,
    current_content: str,
    feedback: str,
    tool_info_list,
    sub_agent_info_list,
    language: str = LANGUAGE["ZH"],
    knowledge_base_display_names: Optional[List[str]] = None,
):
    input_label = "Inputs" if language == LANGUAGE["EN"] else "接受输入"
    output_label = "Output type" if language == LANGUAGE["EN"] else "返回输出类型"

    tool_description = "\n".join(
        [f"- {tool['name']}: {tool['description']} \n {input_label}: {tool['inputs']}\n {output_label}: {tool['output_type']}"
         for tool in tool_info_list]
    )
    assistant_description = "\n".join(
        [f"- {sub_agent_info['name']}: {sub_agent_info['description']}" for sub_agent_info in sub_agent_info_list]
    )

    if knowledge_base_display_names:
        kb_names_str = ", ".join(f'"{name}"' for name in knowledge_base_display_names)
    else:
        kb_names_str = ""

    template_context = {
        "section_type": section_type,
        "section_title": section_title,
        "task_description": task_description,
        "current_content": current_content,
        "feedback": feedback,
        "tool_description": tool_description,
        "assistant_description": assistant_description,
        "knowledge_base_names": kb_names_str,
    }

    return Template(
        prompt_for_optimize["OPTIMIZE_USER_PROMPT"],
        undefined=StrictUndefined
    ).render(template_context)


def _default_prompt_section_title(section_type: str, language: str) -> str:
    localized_titles = PROMPT_SECTION_TYPE_TITLES.get(
        language,
        PROMPT_SECTION_TYPE_TITLES[LANGUAGE["ZH"]]
    )
    return localized_titles.get(section_type, section_type)


def get_enabled_tool_description_for_generate_prompt(agent_id: int, tenant_id: str):
    # Get tool information
    logger.info("Fetching tool instances")
    tool_id_list = get_enable_tool_id_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id)
    tool_info_list = query_tools_by_ids(tool_id_list)
    return tool_info_list


def get_knowledge_base_display_names(tool_info_list: List[dict], agent_id: int, tenant_id: str) -> Optional[List[str]]:
    """
    Extract knowledge base display names from tool configurations.
    This is used to ensure few-shot examples use actual configured knowledge base names.

    Args:
        tool_info_list: List of tool info dictionaries
        agent_id: Agent ID for querying tool instances
        tenant_id: Tenant ID for database queries

    Returns:
        List of knowledge base display names if knowledge_base_search tool is configured, None otherwise
    """
    # Check if knowledge_base_search tool is in the list
    kb_tool_ids = [tool['tool_id'] for tool in tool_info_list if tool.get('name') == 'knowledge_base_search']
    if not kb_tool_ids:
        logger.debug("No knowledge_base_search tool found in tool list")
        return None

    # Get the index_names from ToolInstance for knowledge_base_search tool
    all_index_names = []
    for kb_tool_id in kb_tool_ids:
        try:
            tool_instance = query_tool_instances_by_id(
                agent_id=agent_id,
                tool_id=kb_tool_id,
                tenant_id=tenant_id
            )
            if tool_instance and tool_instance.get('params', {}).get('index_names'):
                index_names = tool_instance['params']['index_names']
                if isinstance(index_names, list):
                    all_index_names.extend(index_names)
                elif isinstance(index_names, str):
                    # Handle JSON string format
                    try:
                        all_index_names.extend(json.loads(index_names))
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse index_names JSON: {index_names}")
        except Exception as e:
            logger.warning(f"Failed to get tool instance for tool_id {kb_tool_id}: {e}")

    if not all_index_names:
        logger.debug("No index_names configured for knowledge_base_search tool")
        return None

    # Remove duplicates while preserving order
    unique_index_names = list(dict.fromkeys(all_index_names))

    # Convert to display names
    knowledge_name_map = get_knowledge_name_map_by_index_names(unique_index_names)

    # Return list of display names (knowledge_name) for each configured index_name
    display_names = []
    for index_name in unique_index_names:
        display_name = knowledge_name_map.get(index_name, index_name)
        if display_name and display_name not in display_names:
            display_names.append(display_name)

    logger.debug(f"Converted index_names {unique_index_names} to display_names: {display_names}")
    return display_names if display_names else None


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
