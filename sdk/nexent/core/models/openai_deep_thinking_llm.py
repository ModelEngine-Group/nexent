import logging
from typing import List, Optional, Dict, Any

from openai.types.chat.chat_completion_message import ChatCompletionMessage
from smolagents import Tool
from smolagents.models import ChatMessage

from .openai_llm import OpenAIModel
from ..utils.observer import ProcessType, Message

logger = logging.getLogger("openai_deep_thinking_llm")

class OpenAIDeepThinkingModel(OpenAIModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def process_token(self, new_token: str) -> str:
        if "<think>" in new_token:
            self.observer.in_think_block = True
            new_token = new_token.replace("<think>", "")
            
        if "</think>" in new_token:
            self.observer.in_think_block = False
            new_token = new_token.replace("</think>", "")
            
        return new_token

    def __call__(self, messages: List[Dict[str, Any]], stop_sequences: Optional[List[str]] = None,
            grammar: Optional[str] = None, tools_to_call_from: Optional[List[Tool]] = None, **kwargs) -> ChatMessage:
        try:
            completion_kwargs = self._prepare_completion_kwargs(messages=messages, stop_sequences=stop_sequences,
                grammar=grammar, tools_to_call_from=tools_to_call_from, model=self.model_id,
                custom_role_conversions=self.custom_role_conversions, convert_images_to_image_urls=True,
                temperature=self.temperature, top_p=self.top_p, **kwargs)

            current_request = self.client.chat.completions.create(stream=True, **completion_kwargs)
            chunk_list = []
            token_join = []
            role = None
            
            # Reset output mode and think block status
            self.observer.current_mode = ProcessType.MODEL_OUTPUT_THINKING
            self.observer.in_think_block = False
            
            for chunk in current_request:
                new_token = chunk.choices[0].delta.content
                if new_token is not None:
                    # Process think tags
                    new_token = self.process_token(new_token)
                    
                    # If in think block, process as deep thinking content
                    if self.observer.in_think_block and new_token:
                        self.observer.message_query.append(
                            Message(ProcessType.MODEL_OUTPUT_DEEP_THINKING, new_token).to_json()
                        )
                    else:
                        # Process token normally
                        self.observer.add_model_new_token(new_token)
                        if not self.observer.in_think_block:
                            token_join.append(new_token)
                    
                    role = chunk.choices[0].delta.role
                chunk_list.append(chunk)
                
                if self.stop_event.is_set():
                    raise RuntimeError("Model is interrupted by stop event")

            # Send end marker
            self.observer.flush_remaining_tokens()
            model_output = "".join(token_join)

            if chunk_list[-1].usage is not None:
                self.last_input_token_count = chunk_list[-1].usage.prompt_tokens
                self.last_output_token_count = chunk_list[-1].usage.total_tokens
            else:
                self.last_input_token_count = 0
                self.last_output_token_count = 0

            message = ChatMessage.from_dict(
                ChatCompletionMessage(role=role if role else "assistant",
                    content=model_output).model_dump(include={"role", "content", "tool_calls"}))

            message.raw = current_request
            return self.postprocess_message(message, tools_to_call_from)

        except Exception as e:
            if "context_length_exceeded" in str(e):
                raise ValueError(f"Token limit exceeded: {str(e)}")
            raise e
