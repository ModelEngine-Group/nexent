"""Prompt template service layer."""

import logging
from typing import Any, Dict, List, Optional

import yaml

from consts.const import LANGUAGE
from consts.error_code import ErrorCode
from consts.exceptions import AppException
from database import prompt_template_db
from utils.prompt_template_utils import get_prompt_generate_prompt_template_text

logger = logging.getLogger(__name__)


DEFAULT_PROMPT_TEMPLATE_NAME = "prompt_generate"
REQUIRED_PROMPT_GENERATE_KEYS = [
    "DUTY_SYSTEM_PROMPT",
    "CONSTRAINT_SYSTEM_PROMPT",
    "FEW_SHOTS_SYSTEM_PROMPT",
    "AGENT_VARIABLE_NAME_SYSTEM_PROMPT",
    "AGENT_DISPLAY_NAME_SYSTEM_PROMPT",
    "AGENT_DESCRIPTION_SYSTEM_PROMPT",
    "USER_PROMPT",
    "AGENT_NAME_REGENERATE_SYSTEM_PROMPT",
    "AGENT_NAME_REGENERATE_USER_PROMPT",
    "AGENT_DISPLAY_NAME_REGENERATE_SYSTEM_PROMPT",
    "AGENT_DISPLAY_NAME_REGENERATE_USER_PROMPT",
]


def _normalize_language(language: str) -> str:
    normalized = (language or "").lower()
    if normalized.startswith(LANGUAGE["ZH"]):
        return LANGUAGE["ZH"]
    return LANGUAGE["EN"]


def _parse_and_validate_yaml_content(content: str, language: str) -> Dict[str, Any]:
    if not content or not content.strip():
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            f"模板{language}内容不能为空"
        )
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            f"模板{language} YAML 格式无效: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            f"模板{language}必须是 YAML 对象"
        )
    missing_keys = [key for key in REQUIRED_PROMPT_GENERATE_KEYS if key not in parsed]
    if missing_keys:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            f"模板缺少字段: {', '.join(missing_keys)}"
        )
    return parsed


def _normalize_template_contents(template_data: Dict[str, Any]) -> tuple[str, str]:
    content_zh = (template_data.get("content_zh") or "").strip()
    content_en = (template_data.get("content_en") or "").strip()
    if not content_en:
        content_en = content_zh

    _parse_and_validate_yaml_content(content_zh, LANGUAGE["ZH"])
    _parse_and_validate_yaml_content(content_en, LANGUAGE["EN"])
    return content_zh, content_en


def ensure_default_prompt_templates(tenant_id: str, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    templates = prompt_template_db.list_prompt_templates(tenant_id)
    if templates:
        return templates

    default_template = {
        "tenant_id": tenant_id,
        "template_name": DEFAULT_PROMPT_TEMPLATE_NAME,
        "description": "Default prompt generation template",
        "template_type": "prompt_generate",
        "content_zh": get_prompt_generate_prompt_template_text(LANGUAGE["ZH"]),
        "content_en": get_prompt_generate_prompt_template_text(LANGUAGE["EN"]),
        "source": "builtin",
        "created_by": user_id,
        "updated_by": user_id,
    }
    prompt_template_db.create_prompt_template(default_template)
    return prompt_template_db.list_prompt_templates(tenant_id)


def list_prompt_templates(tenant_id: str, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    return ensure_default_prompt_templates(tenant_id, user_id=user_id)


def create_prompt_template(template_data: Dict[str, Any], tenant_id: str, user_id: str) -> Dict[str, Any]:
    content_zh, content_en = _normalize_template_contents(template_data)
    payload = {
        "tenant_id": tenant_id,
        "template_name": template_data["name"].strip(),
        "description": template_data.get("description", "").strip(),
        "template_type": template_data.get("template_type", "prompt_generate"),
        "content_zh": content_zh,
        "content_en": content_en,
        "source": template_data.get("source", "custom"),
        "created_by": user_id,
        "updated_by": user_id,
    }
    return prompt_template_db.create_prompt_template(payload)


def update_prompt_template(
    template_id: int,
    template_data: Dict[str, Any],
    tenant_id: str,
    user_id: str
) -> Dict[str, Any]:
    existing_template = prompt_template_db.get_prompt_template_by_id(template_id, tenant_id)
    if not existing_template:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "模板不存在")
    if existing_template.get("source") == "builtin":
        raise AppException(ErrorCode.COMMON_FORBIDDEN, "内置模板不可编辑")

    update_payload: Dict[str, Any] = {"updated_by": user_id}
    if "name" in template_data:
        update_payload["template_name"] = template_data["name"].strip()
    if "description" in template_data:
        update_payload["description"] = (template_data.get("description") or "").strip()
    if "content_zh" in template_data or "content_en" in template_data:
        merged_template_data = {
            "content_zh": template_data.get("content_zh", existing_template.get("content_zh", "")),
            "content_en": template_data.get("content_en", existing_template.get("content_en", "")),
        }
        content_zh, content_en = _normalize_template_contents(merged_template_data)
        update_payload["content_zh"] = content_zh
        update_payload["content_en"] = content_en
    if "source" in template_data:
        update_payload["source"] = template_data["source"]
    return prompt_template_db.update_prompt_template(template_id, tenant_id, update_payload)


def delete_prompt_template(template_id: int, tenant_id: str, user_id: str) -> bool:
    existing_template = prompt_template_db.get_prompt_template_by_id(template_id, tenant_id)
    if not existing_template:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "模板不存在")
    if existing_template.get("source") == "builtin":
        raise AppException(ErrorCode.COMMON_FORBIDDEN, "内置模板不可删除")
    return prompt_template_db.delete_prompt_template(template_id, tenant_id, updated_by=user_id)


def get_prompt_template_payload(
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
    template_id: Optional[int] = None,
) -> Dict[str, Any]:
    language = _normalize_language(language)
    templates = ensure_default_prompt_templates(tenant_id)

    selected_template: Optional[Dict[str, Any]] = None
    if template_id is not None:
        selected_template = prompt_template_db.get_prompt_template_by_id(template_id, tenant_id)
        if not selected_template:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, f"模板不存在: {template_id}")
    elif templates:
        selected_template = templates[0]

    if not selected_template:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "没有可用模板")

    raw_content = selected_template["content_zh"] if language == LANGUAGE["ZH"] else (
        selected_template.get("content_en") or selected_template["content_zh"]
    )
    parsed = _parse_and_validate_yaml_content(raw_content, language)

    return {
        "template_id": selected_template["template_id"],
        "name": selected_template["name"],
        "description": selected_template.get("description", ""),
        "source": selected_template.get("source", "custom"),
        "content": parsed,
        "raw_content": raw_content,
    }
