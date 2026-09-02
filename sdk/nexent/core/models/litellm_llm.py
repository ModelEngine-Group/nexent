"""LiteLLM-backed LLM model for nexent.

Provides access to 100+ LLM providers (OpenAI, Anthropic, Google Gemini,
Azure, Bedrock, Ollama, etc.) through ``litellm.completion()`` as an SDK
dependency. Follows the same interface as ``OpenAIModel``.
"""

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from smolagents import Tool
from smolagents.models import ChatMessage, MessageRole

from ..utils.observer import MessageObserver, ProcessType

logger = logging.getLogger("litellm_llm")


class LiteLLMModel:
    """LLM model backed by LiteLLM SDK.

    Uses ``litellm.completion()`` directly, supporting any model identifier
    that LiteLLM recognizes (e.g. ``anthropic/claude-sonnet-4-20250514``,
    ``gemini/gemini-2.5-flash``, ``azure/gpt-4o``).

    See https://docs.litellm.ai/docs/providers for the full provider list.
    """

    def __init__(
        self,
        model_id: str,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        temperature: float = 0.2,
        top_p: float = 0.95,
        observer: MessageObserver = MessageObserver,
        display_name: Optional[str] = None,
        **kwargs: Any,
    ):
        self.model_id = model_id
        self.api_key = api_key
        self.api_base = api_base
        self.temperature = temperature
        self.top_p = top_p
        self.observer = observer
        self.display_name = display_name
        self.stop_event = threading.Event()
        self.last_input_token_count = 0
        self.last_output_token_count = 0

    def __call__(
        self,
        messages: List[Dict[str, Any]],
        stop_sequences: Optional[List[str]] = None,
        response_format: Optional[Dict[str, str]] = None,
        tools_to_call_from: Optional[List[Tool]] = None,
        **kwargs: Any,
    ) -> ChatMessage:
        try:
            import litellm
        except ImportError as e:
            raise ImportError(
                "litellm is required for LiteLLMModel. "
                "Install it with: pip install 'litellm>=1.80,<1.87'"
            ) from e

        # Normalize messages to dicts
        normalized: List[Dict[str, Any]] = []
        for msg in messages or []:
            if isinstance(msg, ChatMessage):
                normalized.append({
                    "role": msg.role.value if hasattr(msg.role, "value") else str(msg.role),
                    "content": msg.content,
                })
            elif isinstance(msg, dict):
                normalized.append(msg)
            else:
                raise TypeError("Messages must be ChatMessage or dict objects.")

        completion_kwargs: Dict[str, Any] = {
            "model": self.model_id,
            "messages": normalized,
            "temperature": self.temperature,
            "stream": True,
            "drop_params": True,
            "stream_options": {"include_usage": True},
        }

        if self.api_key:
            completion_kwargs["api_key"] = self.api_key
        if self.api_base:
            completion_kwargs["api_base"] = self.api_base
        if stop_sequences:
            completion_kwargs["stop"] = stop_sequences
        if response_format:
            completion_kwargs["response_format"] = response_format

        # Handle tool calling
        if tools_to_call_from:
            tool_definitions = []
            for tool in tools_to_call_from:
                if hasattr(tool, "to_openai_tool"):
                    tool_definitions.append(tool.to_openai_tool())
            if tool_definitions:
                completion_kwargs["tools"] = tool_definitions

        current_request = litellm.completion(**completion_kwargs)

        # Process streaming response
        chunk_list = []
        token_join = []
        role = None

        self.observer.current_mode = ProcessType.MODEL_OUTPUT_THINKING

        try:
            for chunk in current_request:
                if not hasattr(chunk, "choices") or not chunk.choices:
                    chunk_list.append(chunk)
                    continue

                delta = chunk.choices[0].delta
                new_token = getattr(delta, "content", None)
                reasoning_content = getattr(delta, "reasoning_content", None)

                if reasoning_content is not None:
                    self.observer.add_model_reasoning_content(reasoning_content)

                if new_token is not None:
                    self.observer.add_model_new_token(new_token)
                    token_join.append(new_token)
                    role = getattr(delta, "role", None) or role

                chunk_list.append(chunk)
                if self.stop_event.is_set():
                    raise RuntimeError("Model is interrupted by stop event")

            self.observer.flush_remaining_tokens()
            model_output = "".join(token_join)

            # Extract token usage from the last chunk
            input_tokens = 0
            output_tokens = 0
            if chunk_list and hasattr(chunk_list[-1], "usage") and chunk_list[-1].usage is not None:
                usage = chunk_list[-1].usage
                input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(usage, "completion_tokens", 0) or 0

            self.last_input_token_count = input_tokens
            self.last_output_token_count = output_tokens

            from openai.types.chat.chat_completion_message import ChatCompletionMessage

            message = ChatMessage.from_dict(
                ChatCompletionMessage(
                    role=role if role else "assistant",
                    content=model_output,
                ).model_dump(include={"role", "content", "tool_calls"})
            )

            from smolagents.monitoring import TokenUsage

            if input_tokens > 0 or output_tokens > 0:
                message.token_usage = TokenUsage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

            message.raw = current_request
            message.role = MessageRole.ASSISTANT
            return message

        except Exception as e:
            if "context_length_exceeded" in str(e):
                raise ValueError(f"Token limit exceeded: {str(e)}")
            raise

    async def check_connectivity(self) -> bool:
        """Test if the LLM provider connection works."""
        try:
            import litellm
            import asyncio

            kwargs: Dict[str, Any] = {
                "model": self.model_id,
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 5,
                "drop_params": True,
            }
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.api_base:
                kwargs["api_base"] = self.api_base

            await litellm.acompletion(**kwargs)
            return True
        except Exception as e:
            logger.error(f"LiteLLM connectivity check failed: {e}")
            return False
