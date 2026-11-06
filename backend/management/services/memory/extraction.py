# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""FA-based memory extraction module for extracting and storing memory items from final answers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from nexent.core.agents.prompt.memory import compose_memory_prompt, load_memory_template
from nexent.core.concurrency import ManagedTaskSpec
from nexent.memory.models import MemoryLayer, MemoryType
from nexent.monitor import set_monitoring_operation

from management.services.memory.extraction_scope import parse_grounded_items

logger = logging.getLogger("fa_memory_extractor")

@dataclass
class ExtractionResult:
    items: list[dict] = field(default_factory=list)
    reason: str = ""


class MemoryExtractionModelClient:
    """Use the monitored model wrapper through the runtime's managed lane."""

    def __init__(self, model, thread_manager):
        self.model = model
        self.thread_manager = thread_manager

    async def chat(self, messages):
        set_monitoring_operation("memory_extraction")
        result = await self.thread_manager.run(
            "model-tool-io",
            ManagedTaskSpec(task_name="memory-extractor-model-generate", owner="memory.extraction"),
            self.model,
            messages,
        )
        content = getattr(result, "content", result)
        return content if isinstance(content, str) else str(content)


class FaMemoryExtractor:
    MAX_INPUT_CHARS = 8000

    def __init__(
        self,
        *,
        tenant_id: str,
        user_id: str,
        agent_id: str,
        conversation_id: str,
        language: str = "en",
        memory_service=None,
        model_client=None,
    ):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.agent_id = agent_id
        self.conversation_id = conversation_id
        self.language = language
        self.memory_service = memory_service
        self.model_client = model_client

    def _load_prompt(self) -> dict:
        return load_memory_template("memory_extraction")

    def _build_messages(self, final_answer: str, user_query: str = "") -> list[dict]:
        prompt = compose_memory_prompt(
            "memory_extraction",
            {"final_answer": final_answer, "user_query": user_query},
        )
        return [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ]

    @staticmethod
    def _parse_items(raw: str, user_query: str = "", final_answer: str = "") -> list[str]:
        return parse_grounded_items(raw, user_query, final_answer)

    async def _store_items(self, items: list[str]) -> list[dict]:
        results: list[dict] = []
        for item in items:
            try:
                result = await self.memory_service.store_memory(
                    content=item,
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                    agent_id=self.agent_id,
                    conversation_id=self.conversation_id,
                    layer=MemoryLayer.AGENT,
                    memory_type=MemoryType.SHORT_TERM,
                )
                results.append({
                    "content": item,
                    "memory_id": result.memory_id,
                    "event": result.event,
                })
            except Exception:
                logger.warning("Failed to store memory item: %s", item, exc_info=True)
        return results

    async def extract_and_store(
        self,
        final_answer_text: str,
        user_query: str = "",
    ) -> ExtractionResult:
        if not final_answer_text or not final_answer_text.strip():
            return ExtractionResult(items=[], reason="empty_final_answer")

        if not self.model_client:
            return ExtractionResult(items=[], reason="no_llm_configured")

        truncated = final_answer_text[: self.MAX_INPUT_CHARS]
        messages = self._build_messages(truncated, user_query=user_query)

        try:
            raw = await self.model_client.chat(messages)
        except Exception:
            logger.error("LLM call failed during memory extraction", exc_info=True)
            return ExtractionResult(items=[], reason="llm_error")

        parsed = self._parse_items(raw, user_query, truncated)
        if not parsed:
            return ExtractionResult(items=[], reason="no_items")

        stored = await self._store_items(parsed)
        return ExtractionResult(items=stored, reason="ok")
