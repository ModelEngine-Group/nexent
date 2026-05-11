import logging
from typing import Optional

from consts.const import DEFAULT_TENANT_ID, DEFAULT_USER_ID
from consts.const import LANGUAGE
from consts.exceptions import DuplicateError, NotFoundException, ValidationError
from consts.model import PromptTemplateRequest
from database.prompt_template_db import (
    create_prompt_template,
    delete_prompt_template,
    get_prompt_template_by_id,
    get_prompt_template_by_name,
    get_prompt_template_by_template_id,
    query_prompt_templates_by_user,
    upsert_prompt_template_by_id,
    update_prompt_template,
)
from utils.prompt_template_utils import (
    get_prompt_generate_prompt_template,
    merge_prompt_generate_templates,
    normalize_prompt_generate_template_content,
)

logger = logging.getLogger("prompt_template_service")

SYSTEM_PROMPT_TEMPLATE_ID = 0
SYSTEM_PROMPT_TEMPLATE_NAME = "system_default"
PROMPT_TEMPLATE_TYPE_AGENT_GENERATE = "agent_generate"
SYSTEM_PROMPT_TEMPLATE_DESCRIPTION = "System default prompt template"
SYSTEM_PROMPT_TEMPLATE_TENANT_ID = DEFAULT_TENANT_ID
SYSTEM_PROMPT_TEMPLATE_USER_ID = DEFAULT_USER_ID


def _normalize_prompt_template_entity(template: Optional[dict]) -> Optional[dict]:
    """Normalize prompt template entity content keys to lowercase."""
    if not template:
        return template

    normalized_template = dict(template)
    normalized_template["template_content_zh"] = normalize_prompt_generate_template_content(
        normalized_template.get("template_content_zh")
    )
    template_content_en = normalize_prompt_generate_template_content(
        normalized_template.get("template_content_en")
    )
    normalized_template["template_content_en"] = template_content_en or None
    return normalized_template


def build_system_default_prompt_template_payload() -> dict:
    """Build the canonical system default prompt template payload from YAML files."""
    system_template_zh = normalize_prompt_generate_template_content(
        get_prompt_generate_prompt_template(LANGUAGE["ZH"])
    )
    system_template_en = normalize_prompt_generate_template_content(
        get_prompt_generate_prompt_template(LANGUAGE["EN"])
    )
    return {
        "template_id": SYSTEM_PROMPT_TEMPLATE_ID,
        "template_name": SYSTEM_PROMPT_TEMPLATE_NAME,
        "description": SYSTEM_PROMPT_TEMPLATE_DESCRIPTION,
        "template_type": PROMPT_TEMPLATE_TYPE_AGENT_GENERATE,
        "tenant_id": SYSTEM_PROMPT_TEMPLATE_TENANT_ID,
        "user_id": SYSTEM_PROMPT_TEMPLATE_USER_ID,
        "template_content_zh": system_template_zh,
        "template_content_en": system_template_en,
        "created_by": SYSTEM_PROMPT_TEMPLATE_USER_ID,
        "updated_by": SYSTEM_PROMPT_TEMPLATE_USER_ID,
        "delete_flag": "N",
    }


def sync_system_default_prompt_template() -> dict:
    """Sync the YAML-backed system default prompt template into the database."""
    payload = build_system_default_prompt_template_payload()
    prompt_template = upsert_prompt_template_by_id(
        template_id=SYSTEM_PROMPT_TEMPLATE_ID,
        template_data=payload,
        user_id=SYSTEM_PROMPT_TEMPLATE_USER_ID,
    )
    prompt_template["is_system_default"] = True
    return _normalize_prompt_template_entity(prompt_template)


def get_system_default_prompt_template() -> dict:
    """Return the system default prompt generation template from the database."""
    prompt_template = get_prompt_template_by_template_id(
        template_id=SYSTEM_PROMPT_TEMPLATE_ID,
        template_type=PROMPT_TEMPLATE_TYPE_AGENT_GENERATE,
    )
    if not prompt_template:
        prompt_template = sync_system_default_prompt_template()
    else:
        prompt_template["is_system_default"] = True
    return _normalize_prompt_template_entity({
        **prompt_template,
        "is_system_default": True,
    })


def _normalize_template_request(request: PromptTemplateRequest) -> dict:
    """Normalize prompt template request payload."""
    template_name = (request.template_name or "").strip()
    if not template_name:
        raise ValidationError("template_name is required")

    if request.template_type != PROMPT_TEMPLATE_TYPE_AGENT_GENERATE:
        raise ValidationError("Unsupported template type")

    zh_content = normalize_prompt_generate_template_content(
        request.template_content_zh.model_dump()
    )
    if len(zh_content) == 0:
        raise ValidationError("template_content_zh is required")

    en_content = None
    if request.template_content_en is not None:
        en_content = normalize_prompt_generate_template_content(
            request.template_content_en.model_dump()
        )
        if len(en_content) == 0:
            en_content = None

    return {
        "template_name": template_name,
        "description": (request.description or "").strip() or None,
        "template_type": request.template_type,
        "template_content_zh": zh_content,
        "template_content_en": en_content,
    }


def list_prompt_templates_impl(tenant_id: str, user_id: str) -> list[dict]:
    """List all prompt templates for the current user."""
    system_default_template = sync_system_default_prompt_template()
    templates = query_prompt_templates_by_user(
        tenant_id=tenant_id,
        user_id=user_id,
        template_type=PROMPT_TEMPLATE_TYPE_AGENT_GENERATE,
    )
    return [system_default_template, *[
        _normalize_prompt_template_entity({
            **template,
            "is_system_default": False,
        })
        for template in templates
        if template.get("template_id") != SYSTEM_PROMPT_TEMPLATE_ID
    ]]


def get_prompt_template_detail_impl(template_id: int, tenant_id: str, user_id: str) -> dict:
    """Get prompt template detail."""
    if template_id == SYSTEM_PROMPT_TEMPLATE_ID:
        return get_system_default_prompt_template()

    template = get_prompt_template_by_id(
        template_id=template_id,
        tenant_id=tenant_id,
        user_id=user_id,
        template_type=PROMPT_TEMPLATE_TYPE_AGENT_GENERATE,
    )
    if not template:
        raise NotFoundException("Prompt template not found")

    template["is_system_default"] = False
    return _normalize_prompt_template_entity(template)


def create_prompt_template_impl(
    request: PromptTemplateRequest,
    tenant_id: str,
    user_id: str,
) -> dict:
    """Create a prompt template."""
    normalized_request = _normalize_template_request(request)
    existing_template = get_prompt_template_by_name(
        template_name=normalized_request["template_name"],
        tenant_id=tenant_id,
        user_id=user_id,
        template_type=PROMPT_TEMPLATE_TYPE_AGENT_GENERATE,
    )
    if existing_template:
        raise DuplicateError("Prompt template name already exists")

    created_template = create_prompt_template({
        **normalized_request,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "created_by": user_id,
        "updated_by": user_id,
    })
    created_template["is_system_default"] = False
    return _normalize_prompt_template_entity(created_template)


def update_prompt_template_impl(
    template_id: int,
    request: PromptTemplateRequest,
    tenant_id: str,
    user_id: str,
) -> dict:
    """Update a prompt template."""
    if template_id == SYSTEM_PROMPT_TEMPLATE_ID:
        raise ValidationError("System default prompt template cannot be updated")

    existing_template = get_prompt_template_by_id(
        template_id=template_id,
        tenant_id=tenant_id,
        user_id=user_id,
        template_type=PROMPT_TEMPLATE_TYPE_AGENT_GENERATE,
    )
    if not existing_template:
        raise NotFoundException("Prompt template not found")

    normalized_request = _normalize_template_request(request)
    duplicate_template = get_prompt_template_by_name(
        template_name=normalized_request["template_name"],
        tenant_id=tenant_id,
        user_id=user_id,
        template_type=PROMPT_TEMPLATE_TYPE_AGENT_GENERATE,
    )
    if duplicate_template and duplicate_template["template_id"] != template_id:
        raise DuplicateError("Prompt template name already exists")

    updated_template = update_prompt_template(
        template_id=template_id,
        template_data=normalized_request,
        user_id=user_id,
    )
    updated_template["is_system_default"] = False
    return _normalize_prompt_template_entity(updated_template)


def delete_prompt_template_impl(template_id: int, tenant_id: str, user_id: str) -> dict:
    """Delete a prompt template."""
    if template_id == SYSTEM_PROMPT_TEMPLATE_ID:
        raise ValidationError("System default prompt template cannot be deleted")

    existing_template = get_prompt_template_by_id(
        template_id=template_id,
        tenant_id=tenant_id,
        user_id=user_id,
        template_type=PROMPT_TEMPLATE_TYPE_AGENT_GENERATE,
    )
    if not existing_template:
        raise NotFoundException("Prompt template not found")

    deleted_count = delete_prompt_template(template_id=template_id, user_id=user_id)
    return {
        "template_id": template_id,
        "deleted": deleted_count > 0,
    }


def resolve_prompt_generate_template(
    tenant_id: str,
    user_id: str,
    language: str,
    prompt_template_id: Optional[int] = None,
) -> dict:
    """Resolve prompt generation template for the current user and language."""
    system_default_template = sync_system_default_prompt_template()
    system_template = (
        system_default_template.get("template_content_en")
        if language == LANGUAGE["EN"]
        else system_default_template.get("template_content_zh")
    )
    fallback_system_template = system_default_template.get("template_content_zh")

    if not prompt_template_id or prompt_template_id == SYSTEM_PROMPT_TEMPLATE_ID:
        return merge_prompt_generate_templates(system_template, fallback_system_template)

    prompt_template = get_prompt_template_by_id(
        template_id=prompt_template_id,
        tenant_id=tenant_id,
        user_id=user_id,
        template_type=PROMPT_TEMPLATE_TYPE_AGENT_GENERATE,
    )
    if not prompt_template:
        logger.warning(
            "Prompt template %s not found for tenant %s user %s, falling back to system default",
            prompt_template_id,
            tenant_id,
            user_id,
        )
        return merge_prompt_generate_templates(system_template, fallback_system_template)

    custom_language_template = (
        prompt_template.get("template_content_en")
        if language == LANGUAGE["EN"]
        else prompt_template.get("template_content_zh")
    )
    return merge_prompt_generate_templates(
        custom_language_template,
        prompt_template.get("template_content_zh"),
        system_template,
        fallback_system_template,
    )


def get_prompt_template_summary(
    template_id: Optional[int],
    tenant_id: str,
    user_id: str,
) -> tuple[Optional[int], Optional[str]]:
    """Resolve prompt template identity for saving on agent."""
    if template_id is None:
        return None, None

    if template_id == SYSTEM_PROMPT_TEMPLATE_ID:
        return SYSTEM_PROMPT_TEMPLATE_ID, SYSTEM_PROMPT_TEMPLATE_NAME

    prompt_template = get_prompt_template_by_id(
        template_id=template_id,
        tenant_id=tenant_id,
        user_id=user_id,
        template_type=PROMPT_TEMPLATE_TYPE_AGENT_GENERATE,
    )
    if not prompt_template:
        raise NotFoundException("Prompt template not found")

    return prompt_template["template_id"], prompt_template["template_name"]
