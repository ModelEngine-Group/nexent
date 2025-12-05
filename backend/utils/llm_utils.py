import logging
from typing import Callable, List, Optional

from consts.const import MESSAGE_ROLE, THINK_END_PATTERN, THINK_START_PATTERN
from database.model_management_db import get_model_by_model_id
from nexent.core.utils.observer import MessageObserver
from nexent.core.models import OpenAIModel
from utils.config_utils import get_model_name_from_config

logger = logging.getLogger("llm_utils")


def _process_thinking_tokens(
    new_token: str,
    is_thinking: bool,
    token_join: List[str],
    callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Process tokens to filter out thinking content between <think> and </think> tags.
    """
    if is_thinking:
        return THINK_END_PATTERN not in new_token

    if THINK_START_PATTERN in new_token:
        return True

    token_join.append(new_token)
    if callback:
        callback("".join(token_join))

    return False


def call_llm_for_system_prompt(
    model_id: int,
    user_prompt: str,
    system_prompt: str,
    callback: Optional[Callable[[str], None]] = None,
    tenant_id: Optional[str] = None,
) -> str:
    """
    Call the LLM to generate a system prompt with optional streaming callbacks.
    """
    llm_model_config = get_model_by_model_id(model_id=model_id, tenant_id=tenant_id)

    llm = OpenAIModel(
        model_id=get_model_name_from_config(llm_model_config) if llm_model_config else "",
        api_base=llm_model_config.get("base_url", ""),
        api_key=llm_model_config.get("api_key", ""),
        temperature=0.3,
        top_p=0.95,
    )
    messages = [
        {"role": MESSAGE_ROLE["SYSTEM"], "content": system_prompt},
        {"role": MESSAGE_ROLE["USER"], "content": user_prompt},
    ]
    try:
        completion_kwargs = llm._prepare_completion_kwargs(
            messages=messages,
            model=llm.model_id,
            temperature=0.3,
            top_p=0.95,
        )
        current_request = llm.client.chat.completions.create(stream=True, **completion_kwargs)
        token_join: List[str] = []
        is_thinking = False
        for chunk in current_request:
            new_token = chunk.choices[0].delta.content
            if new_token is not None:
                is_thinking = _process_thinking_tokens(
                    new_token,
                    is_thinking,
                    token_join,
                    callback,
                )
        return "".join(token_join)
    except Exception as exc:
        logger.error("Failed to generate prompt from LLM: %s", str(exc))
        raise


__all__ = ["call_llm_for_system_prompt", "_process_thinking_tokens"]

