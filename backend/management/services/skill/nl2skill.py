# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""NL2Skill draft normalization and public creation event projection."""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any

from contracts.errors.exceptions import sampling_configuration_error_payload
from management.services.skill.stream_parser import SkillStreamParser

logger = logging.getLogger(__name__)

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
            parts.append(f'<file path="{path}">\n{file_content}\n</file>')

    if not skill_content.strip() and not parts:
        return ""

    return "\n\n".join([f"<skill>\n{skill_content}\n</skill>", *parts])


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


def project_creation_events(
    events: AsyncIterator[str | dict[str, Any]], target_files: list[str],
) -> AsyncIterator[str]:
    """Project observer events into the public Skill creation protocol."""
    target_file_set = set(target_files)

    async def generate() -> AsyncIterator[str]:
        parser = SkillStreamParser()
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
            async with aclosing(events):
                async for raw_chunk in events:
                    try:
                        chunk = json.loads(raw_chunk) if isinstance(raw_chunk, str) else raw_chunk
                    except json.JSONDecodeError:
                        logger.warning("Ignoring malformed NL2Skill observer chunk")
                        continue
                    if not isinstance(chunk, dict):
                        continue
                    if chunk.get("type") == "agentos_execution_error":
                        yield serialize(json.loads(chunk["payload"]))
                        return
                    for event in parser.process(chunk):
                        if is_allowed_write(event):
                            yield serialize(event)

            for event in parser.flush():
                if is_allowed_write(event):
                    yield serialize(event)
            yield serialize({"type": "done", "content": ""})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("NL2Skill execution failed")
            yield serialize(
                sampling_configuration_error_payload(exc) or {
                    "type": "error",
                    "content": "NL2Skill execution failed.",
                }
            )

    return generate()
