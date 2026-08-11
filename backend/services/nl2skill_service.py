"""Business logic for the ephemeral NL2Skill runtime."""

import asyncio
import json
import logging
import re
import threading
from collections.abc import AsyncIterator
from typing import Any

from nexent.core.agents.agent_model import AgentHistory, AgentRunInfo
from nexent.core.agents.run_agent import agent_run
from nexent.core.utils.observer import MessageObserver

from agents.create_agent_info import create_model_config_list
from agents.nl2skill_agent import create_nl2skill_agent_config
from consts.const import LANGUAGE, MODEL_CONFIG_MAPPING
from consts.model import HistoryItem, NL2SkillRunRequest
from database.model_management_db import get_model_by_model_id
from utils.config_utils import tenant_config_manager, get_model_name_from_config
from utils.content_classifier_utils import ContentClassifier
from utils.prompt_template_utils import get_skill_creation_simple_prompt_template

logger = logging.getLogger(__name__)

PARSABLE_MODEL_TYPES = frozenset(
    {
        "model_output",
        "model_output_thinking",
        "model_output_deep_thinking",
        "model_output_code",
        "model_thinking_output",
    }
)

SKILL_FILE_DIRECTIVE_PATTERN = re.compile(
    r'<(?:reference|use_script)\b[^>]*\bpath\s*=\s*(["\'])(.*?)\1[^>]*/\s*>',
    re.IGNORECASE,
)


def _normalize_relative_path(value: str) -> str | None:
    path = value.strip().replace("\\", "/")
    if not path or "\x00" in path or path.startswith("/"):
        return None
    if re.match(r"^[A-Za-z]:/", path):
        return None
    parts = path.split("/")
    if any(not part or part == ".." for part in parts):
        return None
    return "/".join(part for part in parts if part != ".")


def _extract_target_files(
    query: str,
    draft_snapshot: dict[str, Any] | None,
) -> list[str]:
    if not draft_snapshot or not isinstance(draft_snapshot.get("files"), list):
        return []

    available_paths = {
        normalized
        for file in draft_snapshot["files"]
        if isinstance(file, dict)
        and (normalized := _normalize_relative_path(str(file.get("path") or "")))
    }
    targets: list[str] = []
    for match in SKILL_FILE_DIRECTIVE_PATTERN.finditer(query):
        path = _normalize_relative_path(match.group(2))
        if path in available_paths and path not in targets:
            targets.append(path)
    return targets


def _convert_history(history: list[HistoryItem] | None) -> list[AgentHistory]:
    return [
        AgentHistory(role=item.role, content=item.content)
        for item in history or []
        if item.role in {"user", "assistant"}
    ]


def _assemble_draft_content(draft_snapshot: dict[str, Any]) -> str:
    content = str(draft_snapshot.get("content") or "")
    files = draft_snapshot.get("files")
    if not isinstance(files, list):
        return content

    parts: list[str] = []
    skill_content = content
    for file in files:
        if not isinstance(file, dict):
            continue
        path = str(file.get("path") or "").strip()
        file_content = str(file.get("content") or "")
        if path == "SKILL.md":
            skill_content = file_content
        elif path and file_content.strip():
            parts.append(f'<FILE path="{path}">\n{file_content}\n</FILE>')

    if not skill_content.strip() and not parts:
        return ""

    return "\n\n".join([f"<SKILL>\n{skill_content}\n</SKILL>", *parts])


def _normalize_draft_snapshot(
    draft_snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not draft_snapshot:
        return None
    return {
        "name": str(draft_snapshot.get("name") or ""),
        "description": str(draft_snapshot.get("description") or ""),
        "tags": draft_snapshot.get("tags")
        if isinstance(draft_snapshot.get("tags"), list)
        else [],
        "content": _assemble_draft_content(draft_snapshot),
    }


def _resolve_model_for_nl2skill(
    tenant_id: str,
    model_id: int | None,
    model_config_list: list,
) -> tuple[str, str, dict]:
    """Resolve the model configuration for NL2Skill.

    Args:
        tenant_id: Current tenant ID
        model_id: Optional model ID override from request
        model_config_list: Full model config list for the tenant

    Returns:
        Tuple of (cite_name, model_name, model_config) for the resolved model

    Raises:
        ValueError: When no valid model is found
    """
    if model_id is not None:
        # Use the explicitly requested model
        model_info = get_model_by_model_id(model_id, tenant_id)
        if model_info:
            return (
                model_info["display_name"],
                model_info["display_name"],
                model_info,
            )
        raise ValueError(f"Requested model_id {model_id} not found for tenant")

    # Use the tenant-configured LLM model (MODEL_CONFIG_MAPPING["llm"])
    llm_key = MODEL_CONFIG_MAPPING["llm"]
    llm_config = tenant_config_manager.get_model_config(
        key=llm_key, tenant_id=tenant_id
    )
    if llm_config:
        # Check if there's a matching model in model_config_list with cite_name "main_model"
        for config in model_config_list:
            if config.cite_name == "main_model":
                return ("main_model", config.model_name, llm_config)
        # Fallback: construct from config
        model_name = get_model_name_from_config(llm_config) if llm_config.get(
            "model_name") else ""
        if model_name:
            return ("main_model", model_name, llm_config)

    # Final fallback: use first model in list
    if model_config_list:
        first = model_config_list[0]
        return (first.cite_name, first.model_name, {})

    raise ValueError("No LLM model configured for tenant")


async def build_nl2skill_run_info(
    request: NL2SkillRunRequest,
    tenant_id: str,
    language: str,
) -> AgentRunInfo:
    """Build all request-scoped objects for one NL2Skill turn."""

    template_language = LANGUAGE["EN"] if language == LANGUAGE["EN"] else LANGUAGE["ZH"]
    target_files = _extract_target_files(request.query, request.draft_snapshot)
    draft_snapshot = _normalize_draft_snapshot(request.draft_snapshot)
    template = get_skill_creation_simple_prompt_template(
        language=template_language,
        existing_skill=draft_snapshot,
        complexity=request.complexity,
        user_request=request.query,
        target_files=target_files,
    )
    model_config_list = await create_model_config_list(tenant_id)
    if not model_config_list:
        raise ValueError("No LLM model configured for tenant")

    # Resolve model: use request.model_id if provided, otherwise use tenant-configured model
    cite_name, model_name, model_info = _resolve_model_for_nl2skill(
        tenant_id=tenant_id,
        model_id=request.model_id,
        model_config_list=model_config_list,
    )

    return AgentRunInfo(
        query=template.get("user_prompt") or request.query,
        model_config_list=model_config_list,
        observer=MessageObserver(lang=template_language),
        agent_config=create_nl2skill_agent_config(
            system_prompt=template.get("system_prompt", ""),
            model_name=model_name,
        ),
        history=_convert_history(request.history),
        stop_event=threading.Event(),
        enable_planning=False,
        sandbox_config=None,
        redis_client=None,
    )


def _decorate_event(
    event: dict[str, Any],
    sequence: int,
) -> dict[str, Any]:
    event = {**event, "sequence": sequence}
    event_type = event.get("type")
    if event_type == "skill_body":
        event["block_id"] = "skill:SKILL.md"
    elif event_type == "file_content":
        event["block_id"] = f"file:{event.get('path', '')}"
    elif event_type == "summary":
        event["block_id"] = "summary"
    return event


async def create_nl2skill_stream(
    request: NL2SkillRunRequest,
    tenant_id: str,
    language: str,
) -> AsyncIterator[str]:
    """Create the SSE payload stream for one ephemeral NL2Skill turn."""

    run_info = await build_nl2skill_run_info(request, tenant_id, language)
    target_files = _extract_target_files(request.query, request.draft_snapshot)
    target_file_set = set(target_files)

    async def generate() -> AsyncIterator[str]:
        classifier = ContentClassifier()
        sequence = 0

        def serialize(event: dict[str, Any]) -> str:
            nonlocal sequence
            sequence += 1
            payload = _decorate_event(event, sequence)
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        def is_allowed_write(event: dict[str, Any]) -> bool:
            if not target_file_set:
                return True
            if event.get("type") == "skill_body":
                return "SKILL.md" in target_file_set
            if event.get("type") == "file_content":
                return event.get("path") in target_file_set
            return True

        try:
            if target_files:
                yield serialize(
                    {
                        "type": "target_files",
                        "content": json.dumps(target_files, ensure_ascii=False),
                        "paths": target_files,
                    }
                )
            async for raw_chunk in agent_run(run_info):
                try:
                    chunk = json.loads(raw_chunk) if isinstance(raw_chunk, str) else raw_chunk
                except json.JSONDecodeError:
                    logger.warning("Ignoring malformed NL2Skill observer chunk")
                    continue
                if not isinstance(chunk, dict):
                    continue

                chunk_type = str(chunk.get("type") or "")
                content = str(chunk.get("content") or "")
                if chunk_type in PARSABLE_MODEL_TYPES:
                    for event in classifier.classify(content, origin_type=chunk_type):
                        if is_allowed_write(event):
                            yield serialize(event)
                    continue

                if chunk_type == "final_answer" and classifier.saw_control_tag:
                    continue

                if chunk_type == "final_answer" and "<" in content:
                    for event in classifier.classify(content, origin_type=chunk_type):
                        if is_allowed_write(event):
                            yield serialize(event)
                    continue

                yield serialize(chunk)

            for event in classifier.flush():
                if is_allowed_write(event):
                    yield serialize(event)
            yield serialize({"type": "done", "content": ""})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("NL2Skill execution failed")
            yield serialize(
                {
                    "type": "error",
                    "content": "NL2Skill execution failed.",
                }
            )
        finally:
            run_info.stop_event.set()

    return generate()
