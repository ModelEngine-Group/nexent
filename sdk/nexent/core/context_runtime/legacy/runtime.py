"""Legacy context path: Jinja prompt plus the original AgentMemory assembly."""
from __future__ import annotations

from typing import Any, Sequence

from ..contracts import ContextEvidence, FinalContext


class LegacyContextRuntime:
    """Fallback path deliberately independent from ContextManager and W3."""

    context_manager = None

    def prepare_run(self, *, memory: Any, fallback_system_prompt: str) -> None:
        from smolagents.memory import SystemPromptStep

        memory.system_prompt = SystemPromptStep(system_prompt=fallback_system_prompt)

    def prepare_step(
        self,
        *,
        model: Any,
        memory: Any,
        current_run_start_idx: int,
        tools: Sequence[Any] | None = None,
    ) -> FinalContext:
        del model, current_run_start_idx
        messages = self._messages_from_memory(memory)
        return FinalContext(
            messages=messages,
            tools=list(tools or ()),
            evidence=ContextEvidence(dynamic_message_count=len(messages)),
        )

    def prepare_final_answer(
        self,
        *,
        model: Any,
        memory: Any,
        current_run_start_idx: int,
        task: str,
        final_answer_templates: dict,
        tools: Sequence[Any] | None = None,
    ) -> FinalContext:
        del model, current_run_start_idx
        from jinja2 import StrictUndefined, Template
        from smolagents.models import ChatMessage, MessageRole

        memory_messages = self._messages_from_memory(memory)
        final_answer = final_answer_templates["final_answer"]
        messages = [
            ChatMessage(
                role=MessageRole.SYSTEM,
                content=[{"type": "text", "text": final_answer["pre_messages"]}],
            )
        ]
        messages += memory_messages[1:]
        messages.append(
            ChatMessage(
                role=MessageRole.USER,
                content=[{
                    "type": "text",
                    "text": Template(
                        final_answer["post_messages"],
                        undefined=StrictUndefined,
                    ).render(task=task),
                }],
            )
        )
        return FinalContext(
            messages=messages,
            tools=list(tools or ()),
            evidence=ContextEvidence(dynamic_message_count=len(messages)),
        )

    def truncate_observation(self, memory_step: Any) -> None:
        del memory_step
        return None

    @staticmethod
    def _messages_from_memory(memory: Any) -> list[Any]:
        messages: list[Any] = []
        if memory.system_prompt:
            messages.extend(memory.system_prompt.to_messages())
        for step in memory.steps:
            messages.extend(step.to_messages())
        return messages

    def compression_stats(self) -> dict:
        return {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_hits": 0,
            "cache_types": [],
        }

    @property
    def chars_per_token(self) -> float:
        return 1.5

    @property
    def token_threshold(self) -> int | None:
        return None
