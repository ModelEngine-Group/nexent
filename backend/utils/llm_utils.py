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
    Handles cases where providers only send a closing tag or mix reasoning_content.
    """
    # Check for end tag first, as it might appear in the same token as start tag
    if THINK_END_PATTERN in new_token:
        # If we were never in think mode, treat everything accumulated so far as reasoning and clear it
        if not is_thinking:
            token_join.clear()
            if callback:
                callback("")  # clear any previously streamed reasoning content

        # Exit thinking mode and only keep content after </think>
        _, _, after_end = new_token.partition(THINK_END_PATTERN)
        is_thinking = False
        new_token = after_end
        # Continue processing the remaining content in this token

    # Check for start tag (after processing end tag, in case both are in the same token)
    if THINK_START_PATTERN in new_token:
        # Drop any content before <think> and switch to thinking mode
        _, _, after_start = new_token.partition(THINK_START_PATTERN)
        new_token = after_start
        is_thinking = True

    if is_thinking:
        # Still inside thinking content; ignore until we exit
        return True

    if new_token:
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
        api_base=llm_model_config.get("base_url", "") if llm_model_config else "",
        api_key=llm_model_config.get("api_key", "") if llm_model_config else "",
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
        reasoning_content_seen = False
        content_tokens_seen = 0
        for chunk in current_request:
            delta = chunk.choices[0].delta
            reasoning_content = getattr(delta, "reasoning_content", None)
            new_token = delta.content

            # Note: reasoning_content is separate metadata and doesn't affect content filtering
            # We only filter content based on <think> tags in delta.content
            if reasoning_content:
                reasoning_content_seen = True
                logger.debug("Received reasoning_content (metadata only, not filtering content)")

            # Process content token if it exists
            if new_token is not None:
                content_tokens_seen += 1
                is_thinking = _process_thinking_tokens(
                    new_token,
                    is_thinking,
                    token_join,
                    callback,
                )
        
        result = "".join(token_join)
        if not result and content_tokens_seen > 0:
            logger.warning(
                "Generated prompt is empty but %d content tokens were processed. "
                "This suggests all content was filtered out.",
                content_tokens_seen
            )
        
        return result
    except Exception as exc:
        logger.error("Failed to generate prompt from LLM: %s", str(exc))
        raise


__all__ = ["call_llm_for_system_prompt", "_process_thinking_tokens"]

