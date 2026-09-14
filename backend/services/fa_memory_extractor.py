"""FA-based memory extraction module for extracting and storing memory items from final answers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from nexent.memory.models import MemoryLayer, MemoryType

logger = logging.getLogger("fa_memory_extractor")

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "fa_memory_extraction_en.yaml"


@dataclass
class ExtractionResult:
    items: list[dict] = field(default_factory=list)
    reason: str = ""


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
        with _PROMPT_PATH.open(encoding="utf-8") as stream:
            prompt = yaml.safe_load(stream)
        return prompt

    def _build_messages(self, final_answer: str, user_query: str = "") -> list[dict]:
        prompt = self._load_prompt()
        user_content = prompt["user"].format(
            final_answer=final_answer,
            user_query=user_query,
        )
        return [
            {"role": "system", "content": prompt["system"]},
            {"role": "user", "content": user_content},
        ]

    @staticmethod
    def _parse_items(raw: str) -> list[str]:
        if "<no-memory/>" in raw:
            return []
        matches = re.findall(r"<memory-item>(.*?)</memory-item>", raw, re.DOTALL)
        return [m.strip() for m in matches if m.strip()]

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

        parsed = self._parse_items(raw)
        if not parsed:
            return ExtractionResult(items=[], reason="no_items")

        stored = await self._store_items(parsed)
        return ExtractionResult(items=stored, reason="ok")
