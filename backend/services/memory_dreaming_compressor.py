"""Tenant-model semantic compressor for bounded Dreaming versions."""

from __future__ import annotations

import json
import re

from consts.const import MODEL_CONFIG_MAPPING
from nexent.core.models import OpenAIModel
from nexent.memory.dreaming import (
    DreamingCompressionOutput,
    DreamingCompressionRequest,
)
from nexent.monitor import (
    AgentRunMetadata,
    agent_monitoring_context,
    set_monitoring_operation,
)
from utils.config_utils import get_model_name_from_config, tenant_config_manager


class TenantDreamingCompressor:
    """Compress RAW memory with the tenant's configured default LLM."""

    def __init__(self, tenant_id: str, user_id: str):
        config = tenant_config_manager.get_model_config(
            key=MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id
        )
        if not config:
            raise RuntimeError("No tenant LLM is configured for Dreaming")
        self.tenant_id = tenant_id
        self.user_id = user_id
        context_tokens = int(
            config.get("max_input_tokens")
            or config.get("context_window_tokens")
            or 32_000
        )
        self.max_compression_input_chars = max(20_000, context_tokens * 3)
        self.model = OpenAIModel(
            model_id=get_model_name_from_config(config),
            api_base=config.get("base_url", ""),
            api_key=config.get("api_key", ""),
            temperature=0.1,
            top_p=0.9,
            model_factory=config.get("model_factory"),
            ssl_verify=config.get("ssl_verify", True),
            display_name=config.get("display_name") or None,
            timeout_seconds=config.get("timeout_seconds"),
            stream=False,
        )

    def __call__(
        self, request: DreamingCompressionRequest
    ) -> DreamingCompressionOutput:
        evidence_ids = sorted(
            {evidence_id for unit in request.units for evidence_id in unit.evidence_ids}
        )
        feedback = ", ".join(request.validation_feedback) or "none"
        numeric_agent_id = (
            int(request.agent_id)
            if request.agent_id and request.agent_id.isdigit()
            else None
        )
        metadata = AgentRunMetadata(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            agent_id=numeric_agent_id,
            extra_metadata={
                "dreaming_run_id": request.run_id,
                "dreaming_agent_id": request.agent_id,
                "dreaming_attempt": request.attempt,
            },
        )
        with agent_monitoring_context(metadata):
            input_limit = getattr(self, "max_compression_input_chars", 40_000)

            units = self._prepare_units_with_ids(request.units)

            if len(request.raw_content) > input_limit or len(units) > 12:
                return self._map_reduce_extract(
                    request, units, evidence_ids, feedback
                )

            spans = self._extract_spans(request.raw_content, units, feedback)

            facts, span_feedback = self._validate_spans(
                spans, request.raw_content, units
            )
            if span_feedback:
                raise ValueError(
                    f"Span validation failed: {span_feedback}"
                )

            facts.extend(self._required_literal_facts(units, len(facts)))
            unique_facts = self._deterministic_dedup(facts)
            self._require_source_coverage(unique_facts, units)

            output = self._format_facts(
                unique_facts, request.max_chars, evidence_ids
            )

            # Stage 3: Coverage validation
            all_fact_ids = [f["fact_id"] for f in unique_facts]
            covered_fact_ids = output.metadata.get(
                "covered_fact_ids",
                self._count_covered_facts(output.content, unique_facts),
            )
            output.metadata["covered_fact_ids"] = covered_fact_ids

            if len(all_fact_ids) > 0:
                coverage = len(covered_fact_ids) / len(all_fact_ids)
                if coverage < 0.95:
                    raise ValueError(
                        f"Fact coverage too low: {len(covered_fact_ids)}/{len(all_fact_ids)}={coverage:.2f}"
                    )

            return output

    def _map_reduce_extract(
        self,
        request: DreamingCompressionRequest,
        units: list[dict],
        evidence_ids: list[str],
        feedback: str,
    ) -> DreamingCompressionOutput:
        input_limit = getattr(self, "max_compression_input_chars", 40_000)
        unit_models = request.units
        chunks = self._chunk_units(
            unit_models,
            input_limit=max(10_000, input_limit // 2),
            max_units=12,
        )

        all_facts = []
        fact_counter = 0
        for chunk in chunks:
            chunk_units = [u for u in units if any(
                m.unit_id == u["unit_id"] for m in chunk
            )]
            chunk_raw = "\n".join(
                f"- {u['text'].strip()}" for u in chunk_units if u["text"].strip()
            )
            spans = self._extract_spans(chunk_raw, chunk_units, feedback)
            facts, span_fb = self._validate_spans(spans, chunk_raw, chunk_units)
            if span_fb:
                raise ValueError(f"Map chunk span validation failed: {span_fb}")
            for f in facts:
                f["fact_id"] = f"f{fact_counter:03d}"
                fact_counter += 1
            all_facts.extend(facts)

        all_facts.extend(
            self._required_literal_facts(units, fact_counter)
        )
        unique_facts = self._deterministic_dedup(all_facts)
        self._require_source_coverage(unique_facts, units)
        output = self._format_facts(unique_facts, request.max_chars, evidence_ids)

        all_fact_ids = [f["fact_id"] for f in unique_facts]
        covered_fact_ids = output.metadata.get(
            "covered_fact_ids",
            self._count_covered_facts(output.content, unique_facts),
        )
        output.metadata["covered_fact_ids"] = covered_fact_ids

        if len(all_fact_ids) > 0:
            coverage = len(covered_fact_ids) / len(all_fact_ids)
            if coverage < 0.95:
                raise ValueError(
                    f"Fact coverage too low: {len(covered_fact_ids)}/{len(all_fact_ids)}={coverage:.2f}"
                )

        return output

    @staticmethod
    def _chunk_units(
        units: list, *, input_limit: int, max_units: int = 12
    ) -> list[list]:
        chunks: list[list] = []
        current: list = []
        current_chars = 0
        for unit in units:
            unit_chars = len(unit.content) + 200
            if current and (
                current_chars + unit_chars > input_limit
                or len(current) >= max_units
            ):
                chunks.append(current)
                current = []
                current_chars = 0
            current.append(unit)
            current_chars += unit_chars
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _prepare_units_with_ids(
        units: list,
    ) -> list[dict]:
        """Pre-assign evidence IDs to each unit before LLM extraction."""
        prepared = []
        for unit in units:
            prepared.append({
                "unit_id": unit.unit_id,
                "text": unit.content,
                "evidence_ids": list(unit.evidence_ids),
            })
        return prepared

    @staticmethod
    def _extract_spans_prompt(raw_content: str, units: list[dict]) -> str:
        units_json = json.dumps(
            [
                {"unit_id": unit["unit_id"], "text": unit["text"]}
                for unit in units
            ],
            ensure_ascii=False,
        )
        return (
            "Select all atomic facts from the memory-unit JSON below.\n\n"
            "Rules:\n"
            "1. Select every fact, including labels, identifiers, and numbers; "
            "return one input unit_id and offsets indexing only that object's "
            "text string (exclude JSON syntax and unit_id).\n"
            "2. Do NOT generate or copy any text.\n"
            "3. Each fact must be a contiguous substring of its selected unit.\n"
            "4. Select the smallest complete atomic fact; split units that contain "
            "multiple facts into separate spans.\n"
            "5. Keep contradictory facts as separate spans.\n\n"
            f"Memory units JSON:\n{units_json}\n\n"
            "Return only a JSON array of objects with exactly these keys: "
            "unit_id, start, end. start and end are character offsets in the "
            "selected object's text value."
        )

    @staticmethod
    def _compression_prompt(raw_content: str, units: list[dict]) -> str:
        """Compatibility name for the approved information-extraction prompt."""
        return TenantDreamingCompressor._extract_spans_prompt(raw_content, units)

    def _extract_spans(
        self,
        raw_content: str,
        units: list[dict],
        feedback: str,
    ) -> list[dict]:
        """Call LLM to extract spans, parse JSON, return list of span dicts."""
        prompt = self._compression_prompt(raw_content, units)
        if feedback and feedback != "none":
            prompt += f"\n\nPrevious attempt feedback: {feedback}"
        set_monitoring_operation("dreaming_semantic_compression_extract")
        response = self.model.generate(
            [
                {
                    "role": "system",
                    "content": (
                        "You are an information extraction engine. "
                        "Your task is to select factual spans from RAW memory. "
                        "You do not summarize. You do not rewrite. You do not compress. "
                        "Return only unit-relative character offsets that exist exactly "
                        "in the selected source unit. "
                        "Output JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
        )
        raw = str(response.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
        return json.loads(raw)

    @staticmethod
    def _validate_spans(
        spans: list[dict],
        raw_content: str,
        units: list[dict],
    ) -> tuple[list[dict], list[str]]:
        """Validate spans and extract fact text. Returns (facts, feedback)."""
        feedback = []
        valid_facts = []
        unit_evidence_map = {u["unit_id"]: u["evidence_ids"] for u in units}
        unit_text_map = {u["unit_id"]: u["text"] for u in units}

        for i, span_obj in enumerate(spans):
            start = span_obj.get("start")
            end = span_obj.get("end")

            if start is None or end is None:
                feedback.append(f"span_{i}_missing_offsets")
                continue

            if not isinstance(start, int) or not isinstance(end, int):
                feedback.append(f"span_{i}_non_integer_offsets")
                continue

            unit_id = span_obj.get("unit_id")
            legacy_unit_ids = span_obj.get("unit_ids")
            if unit_id is None and isinstance(legacy_unit_ids, list):
                if len(legacy_unit_ids) == 1:
                    unit_id = legacy_unit_ids[0]
            if unit_id not in unit_text_map:
                feedback.append(f"span_{i}_invalid_unit:{unit_id}")
                continue
            unit_text = unit_text_map[unit_id]

            if end > len(unit_text):
                json_text_prefix = (
                    json.dumps(
                        {"unit_id": unit_id, "text": ""},
                        ensure_ascii=False,
                    )[:-2]
                )
                normalized_start = start - len(json_text_prefix)
                normalized_end = end - len(json_text_prefix)
                if (
                    normalized_start >= 0
                    and normalized_start < normalized_end <= len(unit_text)
                ):
                    start, end = normalized_start, normalized_end

            if start < 0 or end > len(unit_text):
                feedback.append(f"span_{i}_out_of_bounds:{start},{end}")
                continue

            if start >= end:
                feedback.append(f"span_{i}_invalid_range:{start}>={end}")
                continue

            fact_text = unit_text[start:end].strip()

            if not fact_text:
                feedback.append(f"span_{i}_empty_text:{start},{end}")
                continue

            unit_ids = [unit_id]
            evidence_ids = sorted(set(unit_evidence_map.get(unit_id, [])))

            valid_facts.append({
                "fact_id": f"f{i:03d}",
                "unit_ids": unit_ids,
                "span": {"start": start, "end": end},
                "text": fact_text,
                "evidence_ids": evidence_ids,
            })

        return valid_facts, feedback

    @staticmethod
    def _deterministic_dedup(facts: list[dict]) -> list[dict]:
        """Remove exact duplicates while preserving their source attribution."""
        by_text: dict[str, dict] = {}
        order: list[str] = []

        for fact_obj in facts:
            normalized = re.sub(r"\s+", " ", fact_obj["text"].strip())
            if normalized in by_text:
                retained = by_text[normalized]
                retained["unit_ids"] = sorted(
                    set(retained["unit_ids"]) | set(fact_obj["unit_ids"])
                )
                retained["evidence_ids"] = sorted(
                    set(retained["evidence_ids"]) | set(fact_obj["evidence_ids"])
                )
                continue
            by_text[normalized] = {
                **fact_obj,
                "unit_ids": sorted(set(fact_obj["unit_ids"])),
                "evidence_ids": sorted(set(fact_obj["evidence_ids"])),
            }
            order.append(normalized)

        return [by_text[text] for text in order]

    @staticmethod
    def _required_literal_facts(
        units: list[dict], start_index: int
    ) -> list[dict]:
        """Extract validation-critical literals from authoritative unit text."""
        patterns = (
            r"https?://[^\s)\]}>,]+",
            r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
            r"(?<![\w])[-+]?\d+(?:[.,]\d+)*(?:%|ms|s|MB|GB|TB|元|天|小时)?"
            r"(?![\w])",
            r"\b[A-Za-z]+\s+\d+\b",
        )
        facts = []
        fact_index = start_index
        for unit in units:
            matches = sorted(
                (
                    match.start(),
                    match.end(),
                    match.group(0),
                )
                for pattern in patterns
                for match in re.finditer(pattern, unit["text"])
            )
            for start, end, text in matches:
                facts.append({
                    "fact_id": f"f{fact_index:03d}",
                    "unit_ids": [unit["unit_id"]],
                    "span": {"start": start, "end": end},
                    "text": text,
                    "evidence_ids": sorted(set(unit["evidence_ids"])),
                })
                fact_index += 1
        return facts

    @staticmethod
    def _require_source_coverage(facts: list[dict], units: list[dict]) -> None:
        """Reject extraction that represents fewer than 95% of source units."""
        source_unit_ids = {unit["unit_id"] for unit in units}
        covered_unit_ids = {
            unit_id for fact in facts for unit_id in fact["unit_ids"]
        }
        if not source_unit_ids:
            return
        coverage = len(covered_unit_ids) / len(source_unit_ids)
        if coverage < 0.95:
            raise ValueError(
                "Source unit coverage too low: "
                f"{len(covered_unit_ids)}/{len(source_unit_ids)}={coverage:.2f}"
            )

    def _format_facts(
        self,
        facts: list[dict],
        max_chars: int,
        evidence_ids: list[str],
    ) -> DreamingCompressionOutput:
        """Format facts as bullet list. LLM only if over limit."""
        content = "\n".join(f"- {f['text']}" for f in facts)

        if len(content) <= max_chars:
            return DreamingCompressionOutput(
                content=content,
                evidence_ids=evidence_ids,
                metadata={
                    "all_fact_ids": [f["fact_id"] for f in facts],
                    "covered_fact_ids": [f["fact_id"] for f in facts],
                    "fact_to_units_map": {f["fact_id"]: f["unit_ids"] for f in facts},
                },
            )

        return self._lossless_formatting(facts, max_chars, evidence_ids)

    def _lossless_formatting(
        self,
        facts: list[dict],
        max_chars: int,
        evidence_ids: list[str],
    ) -> DreamingCompressionOutput:
        """LLM-based character-level shortening. No semantic changes."""
        facts_text = "\n".join(
            f"[{fact['fact_id']}] {fact['text']}" for fact in facts
        )
        prompt = (
            "You are a lossless formatter.\n\n"
            "Input contains validated facts.\n"
            "Your task: reduce character count while preserving every fact.\n\n"
            "Allowed:\n"
            "- Remove redundant whitespace\n"
            "- Shorten connective words (e.g., 'in order to' → 'to')\n"
            "- Change bullet formatting\n\n"
            "Forbidden:\n"
            "- Merge facts\n"
            "- Reorder facts if it changes meaning\n"
            "- Generalize facts\n"
            "- Remove examples\n"
            "- Remove identifiers\n"
            "- Combine facts\n\n"
            f"The following facts total {len(facts_text)} characters.\n"
            f"Format them to fit within {max_chars} characters.\n\n"
            f"Facts:\n{facts_text}\n\n"
            "Return strict JSON with one entry for every supplied fact_id:\n"
            '{"facts": [{"fact_id": "f001", "text": "shortened fact"}]}\n'
            "Each fact_id must appear exactly once. Never combine multiple fact_ids."
        )
        set_monitoring_operation("dreaming_semantic_compression_format")
        response = self.model.generate(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a lossless formatter. "
                        "You shorten text without changing meaning. "
                        "Output JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
        )
        raw = str(response.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
        payload = json.loads(raw)
        formatted_facts = payload.get("facts")
        if not isinstance(formatted_facts, list):
            raise ValueError("Lossless formatting response must contain a facts list")
        expected_ids = [fact["fact_id"] for fact in facts]
        returned_ids = [
            item.get("fact_id") for item in formatted_facts
            if isinstance(item, dict)
        ]
        if len(returned_ids) != len(set(returned_ids)):
            raise ValueError("Lossless formatting returned duplicate fact_ids")
        if set(returned_ids) != set(expected_ids):
            raise ValueError(
                "Lossless formatting fact_ids do not match the extracted facts"
            )
        text_by_id = {}
        for item in formatted_facts:
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Lossless formatting returned an empty fact")
            text_by_id[item["fact_id"]] = text.strip()
        content = "\n".join(f"- {text_by_id[fact_id]}" for fact_id in expected_ids)
        return DreamingCompressionOutput(
            content=content,
            evidence_ids=evidence_ids,
            metadata={
                "all_fact_ids": expected_ids,
                "covered_fact_ids": returned_ids,
                "fact_to_units_map": {f["fact_id"]: f["unit_ids"] for f in facts},
            },
        )

    @staticmethod
    def _count_covered_facts(
        output_content: str,
        facts: list[dict],
    ) -> list[str]:
        """Return fact_ids whose text appears in output_content."""
        covered = []
        for fact_obj in facts:
            if fact_obj["text"] in output_content:
                covered.append(fact_obj["fact_id"])
        return covered
