"""Tenant-model Markdown summarizer for Dreaming user memory."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml
from consts.const import MODEL_CONFIG_MAPPING
from nexent.core.models import OpenAIModel
from nexent.memory.dreaming import (
    DreamingSummarizationOutput,
    DreamingSummarizationRequest,
)
from nexent.monitor import (
    AgentRunMetadata,
    agent_monitoring_context,
    set_monitoring_operation,
)
from utils.config_utils import get_model_name_from_config, tenant_config_manager

logger = logging.getLogger(__name__)

DREAMING_SUMMARIZATION_MAX_WORKERS = 3
_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "dreaming_user_memory_en.yaml"


def _load_prompt() -> dict:
    with _PROMPT_PATH.open(encoding="utf-8") as stream:
        prompt = yaml.safe_load(stream)
    if not isinstance(prompt, dict) or not prompt.get("system") or not prompt.get("user"):
        raise RuntimeError("Dreaming summary prompt is invalid")
    return prompt


def _parse_summary_envelope(value: object) -> str:
    """Extract one anchored, non-nested summary envelope."""
    raw = str(value or "")
    opening, closing = "<summary>", "</summary>"
    if raw.count(opening) != 1 or raw.count(closing) != 1:
        raise ValueError("summary envelope must occur exactly once")
    if not raw.startswith(opening) or not raw.endswith(closing):
        raise ValueError("content outside summary envelope")
    body = raw[len(opening) : -len(closing)]
    if opening in body or closing in body:
        raise ValueError("nested summary envelope")
    if not body.strip():
        raise ValueError("summary is empty")
    return body.strip()


class TenantDreamingSummarizer:
    """Summarize prior Markdown and promoted evidence with the tenant default LLM."""

    def __init__(self, tenant_id: str, user_id: str):
        config = tenant_config_manager.get_model_config(key=MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id)
        if not config:
            raise RuntimeError("No tenant LLM is configured for Dreaming")
        self.tenant_id = tenant_id
        self.user_id = user_id
        context_tokens = int(config.get("max_input_tokens") or config.get("context_window_tokens") or 32_000)
        self.max_summarization_input_chars = max(20_000, context_tokens * 3)
        self.prompt = _load_prompt()
        self.model = OpenAIModel(
            model_id=get_model_name_from_config(config), api_base=config.get("base_url", ""),
            api_key=config.get("api_key", ""), temperature=0.1, top_p=0.9,
            model_factory=config.get("model_factory"), ssl_verify=config.get("ssl_verify", True),
            display_name=config.get("display_name") or None, timeout_seconds=config.get("timeout_seconds"),
            stream=False,
        )

    def __call__(self, request: DreamingSummarizationRequest) -> DreamingSummarizationOutput:
        metadata = AgentRunMetadata(
            tenant_id=self.tenant_id, user_id=self.user_id,
            agent_id=int(request.agent_id) if request.agent_id and request.agent_id.isdigit() else None,
            extra_metadata={"dreaming_run_id": request.run_id, "dreaming_attempt": request.attempt},
        )
        started = time.monotonic()
        with agent_monitoring_context(metadata):
            source = self._source_markdown(request)
            if len(source) <= self.max_summarization_input_chars:
                markdown = self._generate(source, request, operation="dreaming_summarization")
                return DreamingSummarizationOutput(
                    markdown=markdown,
                    metadata={"mode": "single", "input_chars": len(source), "duration_ms": int((time.monotonic() - started) * 1000)},
                )

            chunks = self._chunk_units(request, self.max_summarization_input_chars)
            summaries: list[str | None] = [None] * len(chunks)
            with ThreadPoolExecutor(max_workers=DREAMING_SUMMARIZATION_MAX_WORKERS) as executor:
                futures = {
                    executor.submit(self._generate, chunk, request, "dreaming_summarization_map", index): index
                    for index, chunk in enumerate(chunks)
                }
                for future in as_completed(futures):
                    index = futures[future]
                    summaries[index] = future.result()
            reduce_source = "\n\n".join(f"## Map Summary {i + 1}\n\n{value}" for i, value in enumerate(summaries))
            markdown = self._generate(reduce_source, request, operation="dreaming_summarization_reduce")
            return DreamingSummarizationOutput(
                markdown=markdown,
                metadata={"mode": "map_reduce", "input_chars": len(source), "chunk_count": len(chunks),
                          "duration_ms": int((time.monotonic() - started) * 1000)},
            )

    @staticmethod
    def _source_markdown(request: DreamingSummarizationRequest) -> str:
        prior = request.prior_markdown.strip() or "(none)"
        return (
            f"## Current Active User Memory\n\nSource: {request.prior_source}\n\n{prior}\n\n"
            f"## Newly Promoted Evidence\n\n{request.new_evidence_markdown.strip()}"
        )

    @staticmethod
    def _chunk_units(request: DreamingSummarizationRequest, limit: int) -> list[str]:
        blocks = []
        if request.prior_markdown.strip():
            blocks.append(f"## Current Active User Memory\n\nSource: {request.prior_source}\n\n{request.prior_markdown.strip()}")
        blocks.extend(f"### Evidence {unit.unit_id}\n\n{unit.content.strip()}" for unit in request.units if unit.is_new)
        if len(blocks) <= DREAMING_SUMMARIZATION_MAX_WORKERS:
            return blocks
        chunks: list[str] = []
        current = ""
        remaining_chars = sum(len(block) for block in blocks)
        for index, block in enumerate(blocks):
            candidate = f"{current}\n\n{block}".strip()
            remaining_slots = DREAMING_SUMMARIZATION_MAX_WORKERS - len(chunks)
            remaining_blocks = len(blocks) - index
            target = max(limit, (remaining_chars + remaining_slots - 1) // remaining_slots)
            if current and remaining_slots > 1 and len(candidate) > target and remaining_blocks >= remaining_slots:
                chunks.append(current)
                current = block
            else:
                current = candidate
            remaining_chars -= len(block)
        if current:
            chunks.append(current)
        return chunks

    def _generate(self, source: str, request: DreamingSummarizationRequest, operation: str, chunk_index: int | None = None) -> str:
        set_monitoring_operation(operation)
        user_prompt = self.prompt["user"].format(
            task_mode={
                "dreaming_summarization": "single",
                "dreaming_summarization_map": "map",
                "dreaming_summarization_reduce": "reduce",
            }[operation],
            max_chars=request.max_chars, attempt=request.attempt,
            validation_feedback=", ".join(request.validation_feedback) or "none", source=source,
        )
        response = self.model.generate([
            {"role": "system", "content": self.prompt["system"]},
            {"role": "user", "content": user_prompt},
        ])
        result = _parse_summary_envelope(response.content)
        logger.info("Dreaming summary operation=%s chunk=%s input_chars=%d output_chars=%d", operation, chunk_index, len(source), len(result))
        return result


# Temporary import compatibility for callers outside the feature branch.
TenantDreamingCompressor = TenantDreamingSummarizer
