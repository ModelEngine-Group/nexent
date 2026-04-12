from ...monitor import get_monitoring_manager
import logging
import threading
import asyncio
import time
from typing import List, Optional, Dict, Any

from openai.types.chat.chat_completion_message import ChatCompletionMessage
from smolagents import Tool
from smolagents.models import OpenAIServerModel, ChatMessage, MessageRole

from ..utils.observer import MessageObserver, ProcessType
from .message_utils import prepare_messages_for_completion

logger = logging.getLogger("openai_llm")

class OpenAIModel(OpenAIServerModel):
    def __init__(self, observer: MessageObserver = MessageObserver, temperature=0.2, top_p=0.95,
                 ssl_verify=True, model_factory: Optional[str] = None, *args, **kwargs):
        """
        Initialize OpenAI Model with observer and SSL verification option.

        Args:
            observer: MessageObserver instance for tracking model output
            temperature: Sampling temperature (default: 0.2)
            top_p: Top-p sampling parameter (default: 0.95)
            ssl_verify: Whether to verify SSL certificates (default: True).
                       Set to False for local services without SSL support.
            model_factory: Provider identifier (e.g., openai, modelengine)
            *args: Additional positional arguments for OpenAIServerModel
            **kwargs: Additional keyword arguments for OpenAIServerModel
        """
        self.observer = observer
        self.temperature = temperature
        self.top_p = top_p
        self.stop_event = threading.Event()
        self._monitoring = get_monitoring_manager()
        self.model_factory = (model_factory or "").lower()

        # Create http_client based on ssl_verify parameter
        if not ssl_verify:
            from openai import DefaultHttpxClient
            http_client = DefaultHttpxClient(verify=False)
            client_kwargs = kwargs.get('client_kwargs', {})
            client_kwargs['http_client'] = http_client
            kwargs['client_kwargs'] = client_kwargs

        super().__init__(*args, **kwargs)

    @get_monitoring_manager().monitor_llm_call("openai_chat", "chat_completion")
    def __call__(self, messages: List[Dict[str, Any]], stop_sequences: Optional[List[str]] = None,
                 response_format: dict[str, str] | None = None, tools_to_call_from: Optional[List[Tool]] = None, **kwargs, ) -> ChatMessage:
        # Get token tracker from decorator (if monitoring is available)
        token_tracker = kwargs.pop('_token_tracker', None)

        # Normalize incoming messages so we can accept plain dict payloads like
        # {"role": "user", "content": "..."} alongside ChatMessage instances.
        normalized_messages: List[ChatMessage] = []
        for msg in messages or []:
            if isinstance(msg, ChatMessage):
                normalized_messages.append(msg)
            elif isinstance(msg, dict):
                if "role" not in msg or "content" not in msg:
                    raise ValueError("Each message dict must include 'role' and 'content'.")
                normalized_messages.append(ChatMessage.from_dict({
                    "role": msg["role"],
                    "content": msg["content"],
                    "tool_calls": msg.get("tool_calls"),
                }))
            else:
                raise TypeError("Messages must be ChatMessage or dict objects.")

        # Prepare messages for completion according to provider requirements.
        messages_for_completion = prepare_messages_for_completion(normalized_messages, self.model_factory)

        # Add completion started event and model parameters
        if token_tracker:
            self._monitoring.add_span_event("completion_started")
            self._monitoring.set_span_attributes(
                model_id=self.model_id,
                temperature=self.temperature,
                top_p=self.top_p,
                message_count=len(messages_for_completion) if messages_for_completion else 0,
                **{f"llm.param.{k}": v for k, v in kwargs.items() if isinstance(v, (str, int, float, bool))}
            )

        completion_kwargs = self._prepare_completion_kwargs(
            messages=messages_for_completion, stop_sequences=stop_sequences,
            response_format=response_format, tools_to_call_from=tools_to_call_from, model=self.model_id,
            custom_role_conversions=self.custom_role_conversions, convert_images_to_image_urls=True,
            temperature=self.temperature, top_p=self.top_p, **kwargs,
        )

        current_request = self.client.chat.completions.create(
            stream=True, **completion_kwargs)
        chunk_list = []
        token_join = []
        role = None

        # Reset output mode
        self.observer.current_mode = ProcessType.MODEL_OUTPUT_THINKING

        # Track streaming metrics
        stream_start_time = time.time()
        first_token_received = False

        try:
            for chunk in current_request:
                new_token = chunk.choices[0].delta.content
                reasoning_content = getattr(
                    chunk.choices[0].delta, 'reasoning_content', None)

                # Handle reasoning_content if it exists and is not null
                if reasoning_content is not None:
                    self.observer.add_model_reasoning_content(
                        reasoning_content)
                    if token_tracker and not first_token_received:
                        token_tracker.record_first_token()
                        first_token_received = True

                if new_token is not None:
                    # Record first token timing
                    if token_tracker and not first_token_received:
                        token_tracker.record_first_token()
                        first_token_received = True

                    # Track each token
                    if token_tracker:
                        token_tracker.record_token(new_token)

                    self.observer.add_model_new_token(new_token)
                    token_join.append(new_token)
                    role = chunk.choices[0].delta.role

                chunk_list.append(chunk)
                if self.stop_event.is_set():
                    if token_tracker:
                        self._monitoring.add_span_event("model_stopped", {
                            "reason": "stop_event_set"})
                    raise RuntimeError(
                        "Model is interrupted by stop event")

            # Send end marker
            self.observer.flush_remaining_tokens()
            model_output = "".join(token_join)

            # Extract token usage
            input_tokens = 0
            output_tokens = 0
            if chunk_list and chunk_list[-1].usage is not None:
                usage = chunk_list[-1].usage
                input_tokens = usage.prompt_tokens
                output_tokens = usage.completion_tokens if hasattr(
                    usage, 'completion_tokens') else usage.total_tokens
                self.last_input_token_count = input_tokens
                self.last_output_token_count = output_tokens
            else:
                self.last_input_token_count = 0
                self.last_output_token_count = 0

            # Record completion metrics
            if token_tracker:
                token_tracker.record_completion(
                    input_tokens, output_tokens)

            if token_tracker:
                total_duration = time.time() - stream_start_time
                self._monitoring.add_span_event("completion_finished", {
                    "total_duration": total_duration,
                    "output_length": len(model_output),
                    "chunk_count": len(chunk_list)
                })

            message = ChatMessage.from_dict(
                ChatCompletionMessage(role=role if role else "assistant",  # If there is no explicit role, default to "assistant"
                                      content=model_output).model_dump(include={"role", "content", "tool_calls"}))

            message.raw = current_request
            message.role = MessageRole.ASSISTANT
            return message

        except Exception as e:
            if token_tracker:
                self._monitoring.add_span_event("error_occurred", {"error_type": type(
                    e).__name__, "error_message": str(e)})

            if "context_length_exceeded" in str(e):
                raise ValueError(f"Token limit exceeded: {str(e)}")
            raise e

    async def check_connectivity(self) -> bool:
        """
        Test if the connection to the remote OpenAI large model service is normal

        Returns:
            bool: True if the connection is successful, False if it fails
        """
        try:
            # Construct a simple test message
            test_message = [{"role": "user", "content": "Hello"}]

            # Directly send a short chat request to test the connection
            completion_kwargs = self._prepare_completion_kwargs(
                messages=test_message,
                model=self.model_id,
                max_tokens=5,
            )

            # Offload the blocking SDK call to a thread pool to avoid blocking the event loop
            await asyncio.to_thread(
                self.client.chat.completions.create,
                stream=False,
                **completion_kwargs,
            )

            # If no exception is raised, the connection is successful
            return True
        except Exception as e:
            logging.error(f"Connection test failed: {str(e)}")
            return False
