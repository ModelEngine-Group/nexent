import json
import logging
import queue
import sys
import threading
from typing import Optional, List

from jinja2 import StrictUndefined, Template

from nexent.core.tools.parallel_executor import ParallelExecutorTool

from consts.const import LANGUAGE, ENABLE_JIUWEN_SDK
from consts.tool_labels import PARALLEL_EXECUTOR_TOOL_NAME
from consts.error_code import ErrorCode
from consts.error_message import ErrorMessage
from consts.exceptions import AppException
from consts.model import AgentInfoRequest
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
    _generate_unique_display_name_with_suffix,
    update_agent,
)
from services.prompt_template_service import resolve_prompt_generate_template
from utils.llm_utils import call_llm_for_system_prompt
from utils.prompt_template_utils import (
    get_prompt_optimize_prompt_template,
    get_prompt_template,
)

from dataclasses import dataclass, field
from typing import Optional as Opt

from adapters.exception import JiuwenSDKError, NexentCapabilityError


def _get_jiuwen_adapter_class():
    """Import Jiuwen adapter only when optimization paths need it."""
    try:
        from adapters import JiuwenSDKAdapter
    except ModuleNotFoundError:
        return None
    return JiuwenSDKAdapter


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
        logger.debug(
            f"Using frontend-provided knowledge base display names: {knowledge_base_display_names}")
    else:
        knowledge_base_display_names = get_knowledge_base_display_names(
            tool_info_list=tool_info_list,
            agent_id=agent_id,
            tenant_id=tenant_id
        )
        logger.debug(
            f"Using database query for knowledge base display names: {knowledge_base_display_names}")

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
                     "agent_description": "", "greeting_message": "", "example_questions": ""}

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
                        logger.info(
                            f"Agent name '{agent_name}' already exists, regenerating with LLM")
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
                            logger.info(
                                f"Regenerated agent name: '{agent_name}'")
                            final_results["agent_var_name"] = agent_name
                        except Exception as e:
                            logger.error(
                                f"Failed to regenerate agent name with LLM: {str(e)}, using fallback")
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
                        logger.info(
                            f"Agent display_name '{agent_display_name}' already exists, regenerating with LLM")
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
                            logger.info(
                                f"Regenerated agent display_name: '{agent_display_name}'")
                            final_results["agent_display_name"] = agent_display_name
                        except Exception as e:
                            logger.error(
                                f"Failed to regenerate agent display_name with LLM: {str(e)}, using fallback")
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

    # 3. Generate greeting message and example questions
    try:
        greeting_template = get_prompt_template('greeting_generate', language)
        greeting_system_prompt = greeting_template.get("GREETING_SYSTEM_PROMPT", "")
        greeting_user_prompt_template = greeting_template.get("USER_PROMPT", "")

        greeting_user_prompt = Template(greeting_user_prompt_template, undefined=StrictUndefined).render({
            "display_name": final_results.get("agent_display_name", ""),
            "duty_description": final_results.get("duty", ""),
            "business_description": task_description,
            "few_shots": final_results.get("few_shots", ""),
        })

        greeting_result = call_llm_for_system_prompt(
            model_id=model_id,
            user_prompt=greeting_user_prompt,
            system_prompt=greeting_system_prompt,
            tenant_id=tenant_id,
        )

        parsed = None
        try:
            json_start = greeting_result.find("{")
            json_end = greeting_result.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                parsed = json.loads(greeting_result[json_start:json_end])
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse greeting JSON from LLM output: {greeting_result}")

        if parsed and "greeting_message" in parsed and "example_questions" in parsed:
            greeting_message = parsed["greeting_message"]
            example_questions = parsed["example_questions"]
            if isinstance(example_questions, list) and len(example_questions) > 6:
                example_questions = example_questions[:6]
        else:
            greeting_message = greeting_result.strip() if greeting_result else ""
            example_questions = []

        yield {
            "type": "greeting_message",
            "content": greeting_message,
            "is_complete": True
        }
        yield {
            "type": "example_questions",
            "content": json.dumps(example_questions, ensure_ascii=False),
            "is_complete": True
        }

        final_results["greeting_message"] = greeting_message
        final_results["example_questions"] = json.dumps(example_questions, ensure_ascii=False)

        # Update agent with greeting (skip in create mode)
        if agent_id != 0:
            update_agent(agent_id, AgentInfoRequest(
                agent_id=agent_id,
                greeting_message=greeting_message,
                example_questions=example_questions,
            ), user_id)
    except Exception as e:
        logger.warning(f"Greeting generation failed: {str(e)}, skipping greeting")

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
        section_title=section_title or _default_prompt_section_title(
            normalized_section_type, language),
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
    concurrency_limit = model_config.get(
        "concurrency_limit") if model_config else None

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
    logger.debug(
        f"Using database query for knowledge base display names: {resolved_names}")
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
                              has_selected_resources=True, concurrency_limit: Optional[int] = None):
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
    semaphore = threading.Semaphore(
        effective_limit) if effective_limit else None
    if semaphore:
        logger.info(
            f"Using concurrency limit of {effective_limit} for prompt generation (total tasks: {total_tasks})")
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
        logger.info(
            "Skipping constraint and few_shots generation: no tools or sub-agents selected")
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
        kb_names_str = ", ".join(
            f'"{name}"' for name in knowledge_base_display_names)
    else:
        kb_names_str = ""
    template_context["knowledge_base_names"] = kb_names_str

    # Generate content using template
    content = Template(
        prompt_for_generate["user_prompt"], undefined=StrictUndefined).render(template_context)
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
        kb_names_str = ", ".join(
            f'"{name}"' for name in knowledge_base_display_names)
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
    # If no tools are enabled, return early — nothing to parallelize.
    if not tool_id_list:
        return []
    tool_info_list = query_tools_by_ids(tool_id_list)

    # parallel_executor is always built from the SDK class — no DB query.
    seen_names = {t.get("name") for t in tool_info_list if t.get("name")}
    if PARALLEL_EXECUTOR_TOOL_NAME not in seen_names:
        tool_info_list.append({
            "name": ParallelExecutorTool.name,
            "description": ParallelExecutorTool.description,
            "description_zh": ParallelExecutorTool.description_zh,
            "inputs": json.dumps(ParallelExecutorTool.inputs, ensure_ascii=False),
            "output_type": ParallelExecutorTool.output_type,
            "params": [],
            "source": "local",
            "class_name": ParallelExecutorTool.__name__,
        })

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
    kb_tool_ids = [tool['tool_id'] for tool in tool_info_list if tool.get(
        'name') == 'knowledge_base_search']
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
                        logger.warning(
                            f"Failed to parse index_names JSON: {index_names}")
        except Exception as e:
            logger.warning(
                f"Failed to get tool instance for tool_id {kb_tool_id}: {e}")

    if not all_index_names:
        logger.debug(
            "No index_names configured for knowledge_base_search tool")
        return None

    # Remove duplicates while preserving order
    unique_index_names = list(dict.fromkeys(all_index_names))

    # Convert to display names
    knowledge_name_map = get_knowledge_name_map_by_index_names(
        unique_index_names)

    # Return list of display names (knowledge_name) for each configured index_name
    display_names = []
    for index_name in unique_index_names:
        display_name = knowledge_name_map.get(index_name, index_name)
        if display_name and display_name not in display_names:
            display_names.append(display_name)

    logger.debug(
        f"Converted index_names {unique_index_names} to display_names: {display_names}")
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


# ── Jiuwen SDK 集成 ───────────────────────────────────────────────────────────


@dataclass
class OptimizeRequest:
    """优化请求的统一数据结构"""
    agent_id: int
    model_id: int
    task_description: str
    section_type: str
    section_title: str
    current_content: str
    feedback: str
    mode: str = "general"
    start_pos: Opt[int] = None
    end_pos: Opt[int] = None
    tool_ids: Opt[list[int]] = None
    sub_agent_ids: Opt[list[int]] = None
    knowledge_base_display_names: Opt[list[str]] = None


@dataclass
class OptimizeResult:
    """优化结果的统一数据结构"""
    optimized_content: str
    source: str
    section_type: str = ""
    section_title: str = ""
    original_content: str = ""


class PromptOptimizationService:
    """提示词优化服务 — 统一入口，模式二选一"""

    def optimize_from_debug(self, agent_id: int, feedback: str, selected, history=None) -> OptimizeResult:
        """基于调试对话自动优化整个 system prompt（完整模板）。

        Args:
            selected: OptimizeFromDebugSelected (pydantic model) or any object with user_question/assistant_answer.
            history: Optional[List[HistoryItem]]
        """
        if not (feedback or "").strip():
            raise AppException(
                ErrorCode.COMMON_MISSING_REQUIRED_FIELD,
                "Optimization feedback is required.",
            )

        if not self.is_jiuwen_mode_available():
            raise NexentCapabilityError(
                "Auto optimize from debug requires Jiuwen SDK to be enabled."
            )

        agent_info = search_agent_info_by_agent_id(
            agent_id=agent_id, tenant_id=self.tenant_id, version_no=0)

        duty = (agent_info.get("duty_prompt") or "").strip()
        constraint = (agent_info.get("constraint_prompt") or "").strip()
        few_shots = (agent_info.get("few_shots_prompt") or "").strip()

        original_full_prompt = "\n\n".join(
            [
                "# Duty\n" + duty,
                "# Constraint\n" + constraint,
                "# FewShots\n" + few_shots,
            ]
        ).strip()

        if not original_full_prompt:
            raise AppException(
                ErrorCode.COMMON_MISSING_REQUIRED_FIELD,
                "Agent system prompt is empty.",
            )

        user_question = getattr(selected, "user_question", None) or (
            selected.get("user_question") if isinstance(selected, dict) else "")
        assistant_answer = getattr(selected, "assistant_answer", None) or (
            selected.get("assistant_answer") if isinstance(selected, dict) else "")

        bad_case_obj = type("_BadCase", (), {})
        bc = bad_case_obj()
        bc.question = user_question or ""
        bc.answer = assistant_answer or ""
        bc.label = ""
        bc.reason = feedback

        adapter_cls = _get_jiuwen_adapter_class()
        if adapter_cls is None:
            raise JiuwenSDKError("Jiuwen SDK adapter is unavailable")

        adapter = adapter_cls(
            model_id=self.model_id, tenant_id=self.tenant_id)

        optimized_full_prompt = adapter.optimize_badcase(
            prompt=original_full_prompt,
            bad_cases=[bc],
            language=self.language,
        )

        return OptimizeResult(
            optimized_content=optimized_full_prompt,
            source="jiuwen",
            section_type="full_prompt",
            section_title="system_prompt",
            original_content=original_full_prompt,
        )

    def __init__(self, model_id: int, tenant_id: str, language: str):
        self.model_id = model_id
        self.tenant_id = tenant_id
        self.language = language

    def is_jiuwen_mode_available(self) -> bool:
        """判断 Jiuwen SDK 模式是否可用"""
        if not ENABLE_JIUWEN_SDK:
            return False

        return _get_jiuwen_adapter_class() is not None

    def optimize(self, request: OptimizeRequest) -> OptimizeResult:
        """统一优化入口 — 优先 Jiuwen SDK，失败则降级 nexent 原生"""
        if self.is_jiuwen_mode_available():
            logger.info(
                f"[prompt-optimize] mode={request.mode}, using Jiuwen SDK")
            try:
                return self._optimize_with_jiuwen(request)
            except JiuwenSDKError as e:
                logger.warning(f"Jiuwen SDK 模式失败，降级到 nexent 原生: {e}")
                return self._optimize_with_nexent(request)
        else:
            return self._optimize_with_nexent(request)

    def _optimize_with_jiuwen(self, request: OptimizeRequest) -> OptimizeResult:
        """Jiuwen SDK 模式"""
        logger.info(
            f"[jiuwen-optimize] mode={request.mode}, start_pos={request.start_pos}, "
            f"end_pos={request.end_pos}, prompt_len={len(request.current_content)}, "
            f"feedback_len={len(request.feedback)}"
        )
        adapter_cls = _get_jiuwen_adapter_class()
        if adapter_cls is None:
            raise JiuwenSDKError("Jiuwen SDK adapter is unavailable")

        adapter = adapter_cls(
            model_id=self.model_id,
            tenant_id=self.tenant_id,
        )
        result = adapter.optimize(
            prompt=request.current_content,
            feedback=request.feedback,
            mode=request.mode,
            start_pos=request.start_pos,
            end_pos=request.end_pos,
            language=self.language,
        )

        # Jiuwen insert/select mode returns a fragment by design.
        # We reassemble the full prompt here so frontend always receives full optimized content.
        if request.mode == "insert":
            if request.start_pos is None or not isinstance(request.start_pos, int):
                raise JiuwenSDKError("insert mode requires start_pos")
            if request.start_pos < 0 or request.start_pos > len(request.current_content):
                raise JiuwenSDKError("insert mode start_pos out of bounds")
            optimized_full = (
                request.current_content[: request.start_pos]
                + result
                + request.current_content[request.start_pos:]
            )
        elif request.mode == "select":
            if request.start_pos is None or request.end_pos is None:
                raise JiuwenSDKError(
                    "select mode requires start_pos and end_pos")
            if not isinstance(request.start_pos, int) or not isinstance(request.end_pos, int):
                raise JiuwenSDKError(
                    "select mode start_pos/end_pos must be int")
            if request.start_pos < 0 or request.end_pos < 0 or request.start_pos >= request.end_pos:
                raise JiuwenSDKError("select mode start_pos/end_pos invalid")
            if request.end_pos > len(request.current_content):
                raise JiuwenSDKError("select mode end_pos out of bounds")
            optimized_full = (
                request.current_content[: request.start_pos]
                + result
                + request.current_content[request.end_pos:]
            )
        else:
            optimized_full = result

        return OptimizeResult(
            optimized_content=optimized_full,
            source="jiuwen",
            section_type=request.section_type,
            section_title=request.section_title,
            original_content=request.current_content,
        )

    def _optimize_with_nexent(self, request: OptimizeRequest) -> OptimizeResult:
        """nexent 原生模式 — 只支持 general 模式"""
        if request.mode != "general":
            raise NexentCapabilityError(
                f"nexent 原生模式只支持 general 模式，"
                f"当前请求 mode={request.mode} 不支持，请启用 Jiuwen SDK"
            )

        result = optimize_prompt_section_impl(
            agent_id=request.agent_id,
            model_id=self.model_id,
            task_description=request.task_description,
            tenant_id=self.tenant_id,
            language=self.language,
            section_type=request.section_type,
            section_title=request.section_title,
            current_content=request.current_content,
            feedback=request.feedback,
            tool_ids=request.tool_ids,
            sub_agent_ids=request.sub_agent_ids,
            knowledge_base_display_names=request.knowledge_base_display_names,
        )
        return OptimizeResult(
            optimized_content=result["optimized_content"],
            source="nexent",
            section_type=result["section_type"],
            section_title=result["section_title"],
            original_content=result["original_content"],
        )

    def optimize_badcase(
        self,
        current_content: str,
        bad_cases: list,
        agent_id: int,
        section_type: str,
        section_title: str,
        tool_ids: Opt[list[int]] = None,
        sub_agent_ids: Opt[list[int]] = None,
        knowledge_base_display_names: Opt[list[str]] = None,
    ) -> OptimizeResult:
        """坏案例优化入口 — 优先 Jiuwen SDK，失败则降级"""
        if self.is_jiuwen_mode_available():
            logger.info("[prompt-badcase] using Jiuwen SDK")
            try:
                return self._optimize_badcase_with_jiuwen(
                    current_content, bad_cases, section_type, section_title
                )
            except JiuwenSDKError as e:
                logger.warning(f"Jiuwen SDK badcase 模式失败，降级到 nexent 原生: {e}")
                return self._optimize_badcase_with_nexent(
                    current_content, bad_cases, agent_id, section_type, section_title,
                    tool_ids, sub_agent_ids, knowledge_base_display_names,
                )
        else:
            return self._optimize_badcase_with_nexent(
                current_content, bad_cases, agent_id, section_type, section_title,
                tool_ids, sub_agent_ids, knowledge_base_display_names,
            )

    def _optimize_badcase_with_jiuwen(
        self, current_content: str, bad_cases: list, section_type: str, section_title: str
    ) -> OptimizeResult:
        """Jiuwen SDK 坏案例优化"""
        adapter_cls = _get_jiuwen_adapter_class()
        if adapter_cls is None:
            raise JiuwenSDKError("Jiuwen SDK adapter is unavailable")

        adapter = adapter_cls(
            model_id=self.model_id,
            tenant_id=self.tenant_id,
        )
        result = adapter.optimize_badcase(
            prompt=current_content,
            bad_cases=bad_cases,
            language=self.language,
        )
        return OptimizeResult(
            optimized_content=result,
            source="jiuwen",
            section_type=section_type,
            section_title=section_title,
            original_content=current_content,
        )

    def _optimize_badcase_with_nexent(
        self,
        current_content: str,
        bad_cases: list,
        agent_id: int,
        section_type: str,
        section_title: str,
        tool_ids: Opt[list[int]] = None,
        sub_agent_ids: Opt[list[int]] = None,
        knowledge_base_display_names: Opt[list[str]] = None,
    ) -> OptimizeResult:
        """nexent 原生模式不支持坏案例优化"""
        raise NexentCapabilityError(
            "nexent 原生模式不支持 badcase 优化，请启用 Jiuwen SDK"
        )
