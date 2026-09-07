"""Evaluator service — CRUD + LLM generation."""

import json
import logging
import re
from typing import Any, Optional

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from database.evaluator_db import (
    create_evaluator,
    delete_evaluator,
    delete_evaluator_version,
    get_evaluator,
    list_evaluator_versions,
    list_evaluators,
    publish_evaluator,
    restore_evaluator_version,
    update_evaluator,
)
from utils.agent_profile_utils import fetch_agent_profile, format_agent_profile_context
from utils.llm_utils import call_llm_for_system_prompt
from utils.prompt_template_utils import get_prompt_template


logger = logging.getLogger(__name__)

# ── Export / Import constants ───────────────────────────────────────

_EXPORT_VERSION = "1.0"
_EXPORT_TYPE = "nexent_evaluator_export"

# Fields that carry instance-specific identity — stripped on export, regenerated on import
_EXPORT_STRIP_FIELDS = {
    "evaluator_id",
    "tenant_id",
    "source",
    "status",
    "version_no",
    "version_group_id",
    "is_current",
    "created_by",
    "updated_by",
    "create_time",
    "update_time",
    "delete_flag",
    "name_en",
    "description_en",
}


def list_evaluators_impl(
    tenant_id: str,
    source: str | None = None,
    evaluator_type: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    return list_evaluators(
        tenant_id=tenant_id,
        source=source,
        evaluator_type=evaluator_type,
        status=status,
    )


def get_evaluator_impl(evaluator_id: int, tenant_id: str) -> dict[str, Any] | None:
    return get_evaluator(evaluator_id=evaluator_id, tenant_id=tenant_id)


def create_evaluator_impl(
    tenant_id: str,
    user_id: str,
    name: str,
    description: str,
    evaluator_type: str,
    prompt: str | None,
    code: str | None = None,
    score_range_min: float = 0.0,
    score_range_max: float = 1.0,
    pass_threshold: float = 0.5,
    input_fields: list[dict[str, Any]] | None = None,
    model_id: int | None = None,
) -> dict[str, Any]:
    if code:
        from services.agent_evaluation_service import validate_code_evaluator

        validate_code_evaluator(code)
    return create_evaluator(
        tenant_id=tenant_id,
        user_id=user_id,
        name=name,
        description=description,
        evaluator_type=evaluator_type,
        prompt=prompt,
        code=code,
        score_range_min=score_range_min,
        score_range_max=score_range_max,
        pass_threshold=pass_threshold,
        input_fields=input_fields or [],
        model_id=model_id,
    )


def update_evaluator_impl(
    evaluator_id: int,
    tenant_id: str,
    **kwargs,
) -> dict[str, Any] | None:
    if kwargs.get("code"):
        from services.agent_evaluation_service import validate_code_evaluator

        validate_code_evaluator(kwargs["code"])
    return update_evaluator(evaluator_id=evaluator_id, tenant_id=tenant_id, **kwargs)


def delete_evaluator_impl(evaluator_id: int, tenant_id: str) -> bool:
    return delete_evaluator(evaluator_id=evaluator_id, tenant_id=tenant_id)


def publish_evaluator_impl(
    evaluator_id: int,
    tenant_id: str,
    version_name: str | None = None,
    release_note: str | None = None,
) -> dict[str, Any] | None:
    return publish_evaluator(
        evaluator_id=evaluator_id,
        tenant_id=tenant_id,
        version_name=version_name,
        release_note=release_note,
    )


def list_evaluator_versions_impl(
    evaluator_id: int, tenant_id: str
) -> list[dict[str, Any]]:
    return list_evaluator_versions(evaluator_id=evaluator_id, tenant_id=tenant_id)


def restore_evaluator_version_impl(
    version_id: int, tenant_id: str
) -> dict[str, Any] | None:
    return restore_evaluator_version(version_id=version_id, tenant_id=tenant_id)


def delete_evaluator_version_impl(version_id: int, tenant_id: str) -> bool:
    return delete_evaluator_version(version_id=version_id, tenant_id=tenant_id)


def _build_evaluator_gen_prompt(
    description: str, agent_id: int | None, tenant_id: str
) -> str:
    """Build the user prompt for evaluator generation.

    When *agent_id* is provided and the agent profile is available, it is
    prepended so the LLM can generate a more targeted evaluator.
    """
    if not agent_id:
        return f"Generate an evaluator based on the following requirements:\n\n{description}"

    profile = fetch_agent_profile(agent_id, tenant_id)
    agent_profile = format_agent_profile_context(profile)
    if not agent_profile:
        return f"Generate an evaluator based on the following requirements:\n\n{description}"

    return (
        f"{agent_profile}\n\n"
        f"## Evaluation Request\n"
        f"Generate an evaluator for the above agent. Requirements:\n\n{description}"
    )


def _parse_llm_evaluator_response(response) -> dict[str, Any]:
    """Parse the LLM response into a dict, stripping markdown fences."""
    raw = response
    m = re.search(r"```(?:json)?\s*(\{.*?})\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    try:
        return json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.error("Failed to parse LLM response as JSON: %s", str(response)[:500])
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            "LLM returned invalid format, please retry",
        ) from exc


def _validate_evaluator_fields(data: dict[str, Any]) -> str:
    """Validate the parsed evaluator dict and return the evaluator type.

    Raises ``AppException`` when required fields are missing or invalid.
    """
    if "name" not in data:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR, "Missing required field: name"
        )

    eval_type = data.get("evaluator_type", "llm")
    if eval_type not in ("llm", "code"):
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            f"Unsupported evaluator type: {eval_type} (only llm / code supported)",
        )

    if eval_type == "llm" and not data.get("prompt"):
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR, "llm evaluator requires prompt"
        )
    if eval_type == "code" and not data.get("code"):
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR, "code evaluator requires code"
        )
    return eval_type


def generate_evaluator_by_llm_impl(
    description: str,
    tenant_id: str,
    model_id: int,
    agent_id: int | None = None,
    language: str = "zh",
) -> dict[str, Any]:
    """Generate evaluator config via LLM from a natural language description.

    If agent_id is provided, the agent's full profile (name, description,
    duty/constraint prompts, tools, skills, sub-agents) is included so the
    LLM can generate a more targeted evaluator.
    """
    logger.info(
        "Generating evaluator from description: %s (agent_id=%s)",
        description[:100],
        agent_id,
    )

    template = get_prompt_template("evaluation_generate_evaluator", language)
    user_prompt = _build_evaluator_gen_prompt(description, agent_id, tenant_id)

    try:
        response = call_llm_for_system_prompt(
            model_id=model_id,
            user_prompt=user_prompt,
            system_prompt=template["SYSTEM_PROMPT"],
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.exception("LLM call failed for evaluator generation")
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR, "Evaluator generation failed"
        ) from exc

    data = _parse_llm_evaluator_response(response)
    eval_type = _validate_evaluator_fields(data)

    return {
        "name": data.get("name", ""),
        "description": data.get("description", ""),
        "evaluator_type": eval_type,
        "prompt": data.get("prompt") if eval_type == "llm" else None,
        "code": data.get("code") if eval_type == "code" else None,
        "score_range_min": data.get("score_range_min", 0.0),
        "score_range_max": data.get("score_range_max", 1.0),
        "pass_threshold": data.get("pass_threshold", 0.5),
        "input_fields": data.get(
            "input_fields",
            [
                {"name": "query", "type": "string", "required": True},
                {"name": "expected", "type": "string", "required": True},
                {"name": "actual", "type": "string", "required": True},
            ],
        ),
    }


def _strip_instance_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Remove instance-specific fields from an evaluator dict for export."""
    return {k: v for k, v in row.items() if k not in _EXPORT_STRIP_FIELDS}


def export_evaluators_impl(tenant_id: str, evaluator_ids: list[int]) -> dict:
    """Export one or more custom evaluators as a portable JSON-serializable dict.

    Only custom evaluators belonging to *tenant_id* are exported.
    The result is suitable for ``import_evaluators_impl``.
    """
    from datetime import datetime, timezone

    exported = []
    for eid in evaluator_ids:
        row = get_evaluator_impl(evaluator_id=eid, tenant_id=tenant_id)
        if not row:
            raise AppException(
                ErrorCode.COMMON_RESOURCE_NOT_FOUND, f"Evaluator {eid} not found"
            )
        if row.get("source") != "custom":
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR,
                f"Evaluator {eid} is builtin and cannot be exported",
            )
        exported.append(_strip_instance_fields(row))

    return {
        "version": _EXPORT_VERSION,
        "type": _EXPORT_TYPE,
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "evaluators": exported,
    }


def _validate_evaluator_item(
    item: Any, idx: int
) -> tuple[Optional[str], Optional[str], Optional[float], Optional[float], Optional[float], Optional[dict]]:
    """Validate one evaluator entry from the import payload.

    Returns ``(name, etype, lo, hi, th, error)``.  When validation fails,
    ``error`` is a dict describing the problem and the other fields are
    ``None``.  When validation passes, ``error`` is ``None``.
    """
    if not isinstance(item, dict):
        return None, None, None, None, None, {
            "index": idx, "reason": "evaluator entry must be an object",
        }

    name = (item.get("name") or "").strip()
    etype = item.get("evaluator_type") or "llm"

    if not name:
        return None, None, None, None, None, {
            "index": idx, "reason": "name is required",
        }
    if etype not in ("llm", "code"):
        return None, None, None, None, None, {
            "index": idx, "name": name,
            "reason": f"unsupported evaluator_type: {etype}",
        }
    if etype == "llm" and not item.get("prompt"):
        return None, None, None, None, None, {
            "index": idx, "name": name,
            "reason": "llm evaluator requires prompt",
        }
    if etype == "code" and not item.get("code"):
        return None, None, None, None, None, {
            "index": idx, "name": name,
            "reason": "code evaluator requires code",
        }

    lo = float(item.get("score_range_min", 0.0))
    hi = float(item.get("score_range_max", 1.0))
    th = float(item.get("pass_threshold", 0.5))
    if lo >= hi:
        return None, None, None, None, None, {
            "index": idx, "name": name,
            "reason": f"score_range_min({lo}) >= score_range_max({hi})",
        }
    if th <= lo or th >= hi:
        return None, None, None, None, None, {
            "index": idx, "name": name,
            "reason": f"pass_threshold({th}) not in ({lo}, {hi})",
        }

    return name, etype, lo, hi, th, None


def import_evaluators_impl(
    tenant_id: str,
    user_id: str,
    export_data: dict[str, Any],
) -> dict[str, Any]:
    """Import evaluators from a previously exported JSON payload.

    Returns ``{imported: int, skipped: int, errors: [{evaluator, reason}]}``.
    """
    if not isinstance(export_data, dict):
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            "Invalid export file: top-level must be an object",
        )

    version = export_data.get("version")
    etype = export_data.get("type")
    if version != _EXPORT_VERSION or etype != _EXPORT_TYPE:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            f"Unsupported export (version={version}, type={etype})",
        )

    evaluators = export_data.get("evaluators")
    if not isinstance(evaluators, list) or not evaluators:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR, "Export file contains no evaluators"
        )

    # Gather existing evaluators for name-based dedup
    existing = list_evaluators_impl(tenant_id=tenant_id)
    existing_keys = {
        (e["name"], e.get("evaluator_type", "llm"))
        for e in existing
        if e.get("source") == "custom"
    }

    imported = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    for idx, item in enumerate(evaluators):
        name, etype, lo, hi, th, error = _validate_evaluator_item(item, idx)
        if error is not None:
            errors.append(error)
            continue

        # ── Dedup ───────────────────────────────────────────────────
        if (name, etype) in existing_keys:
            skipped += 1
            logger.info(
                "Import skipped — duplicate evaluator: name=%s type=%s", name, etype
            )
            continue

        # ── Create ──────────────────────────────────────────────────
        created, create_error = _try_create_evaluator(
            tenant_id, user_id, item, name, etype, lo, hi, th, existing_keys, idx,
        )
        if created:
            imported += 1
        elif create_error:
            errors.append(create_error)

    return {"imported": imported, "skipped": skipped, "errors": errors}


def _try_create_evaluator(
    tenant_id: str,
    user_id: str,
    item: dict[str, Any],
    name: str,
    etype: str,
    lo: float,
    hi: float,
    th: float,
    existing_keys: set,
    idx: int,
) -> tuple[bool, Optional[dict]]:
    """Attempt to create one evaluator from import data.

    Returns ``(created, error)``.  On success, ``created`` is ``True`` and
    the (name, type) pair is added to ``existing_keys``.  On failure,
    ``error`` is a dict for the import error report.
    """
    try:
        created = create_evaluator_impl(
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            description=item.get("description") or "",
            evaluator_type=etype,
            prompt=item.get("prompt"),
            code=item.get("code"),
            score_range_min=lo,
            score_range_max=hi,
            pass_threshold=th,
            input_fields=item.get("input_fields") or [],
            model_id=item.get("model_id"),
        )
        if created:
            existing_keys.add((name, etype))
        return created, None
    except Exception as exc:
        logger.warning(
            "Import failed for evaluator '%s': %s", name, exc, exc_info=True
        )
        return False, {"index": idx, "name": name, "reason": "Invalid evaluator data"}
