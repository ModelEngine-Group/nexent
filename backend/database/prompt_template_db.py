"""Prompt template database operations."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from database.client import as_dict, db_client, get_db_session
from database.db_models import PromptTemplateInfo

logger = logging.getLogger(__name__)


def ensure_prompt_template_table() -> None:
    """Create the prompt template table if it does not exist."""
    PromptTemplateInfo.__table__.create(bind=db_client.engine, checkfirst=True)


def _to_dict(template: PromptTemplateInfo) -> Dict[str, Any]:
    result = as_dict(template)
    result["name"] = result.pop("template_name", "")
    return result


def list_prompt_templates(tenant_id: str, template_type: str = "prompt_generate") -> List[Dict[str, Any]]:
    ensure_prompt_template_table()
    with get_db_session() as session:
        templates = session.query(PromptTemplateInfo).filter(
            PromptTemplateInfo.tenant_id == tenant_id,
            PromptTemplateInfo.template_type == template_type,
            PromptTemplateInfo.delete_flag != "Y"
        ).order_by(PromptTemplateInfo.template_id.asc()).all()
        return [_to_dict(item) for item in templates]


def get_prompt_template_by_id(
    template_id: int,
    tenant_id: str,
    template_type: str = "prompt_generate"
) -> Optional[Dict[str, Any]]:
    ensure_prompt_template_table()
    with get_db_session() as session:
        template = session.query(PromptTemplateInfo).filter(
            PromptTemplateInfo.template_id == template_id,
            PromptTemplateInfo.tenant_id == tenant_id,
            PromptTemplateInfo.template_type == template_type,
            PromptTemplateInfo.delete_flag != "Y"
        ).first()
        return _to_dict(template) if template else None


def get_prompt_template_by_name(
    template_name: str,
    tenant_id: str,
    template_type: str = "prompt_generate"
) -> Optional[Dict[str, Any]]:
    ensure_prompt_template_table()
    with get_db_session() as session:
        template = session.query(PromptTemplateInfo).filter(
            PromptTemplateInfo.template_name == template_name,
            PromptTemplateInfo.tenant_id == tenant_id,
            PromptTemplateInfo.template_type == template_type,
            PromptTemplateInfo.delete_flag != "Y"
        ).first()
        return _to_dict(template) if template else None


def create_prompt_template(template_data: Dict[str, Any]) -> Dict[str, Any]:
    ensure_prompt_template_table()
    with get_db_session() as session:
        exists = session.query(PromptTemplateInfo).filter(
            PromptTemplateInfo.tenant_id == template_data["tenant_id"],
            PromptTemplateInfo.template_name == template_data["template_name"],
            PromptTemplateInfo.template_type == template_data.get("template_type", "prompt_generate"),
            PromptTemplateInfo.delete_flag != "Y"
        ).first()
        if exists:
            raise ValueError(f"Prompt template already exists: {template_data['template_name']}")

        now = datetime.now()
        template = PromptTemplateInfo(
            tenant_id=template_data["tenant_id"],
            template_name=template_data["template_name"],
            description=template_data.get("description", ""),
            template_type=template_data.get("template_type", "prompt_generate"),
            content_zh=template_data["content_zh"],
            content_en=template_data["content_en"],
            source=template_data.get("source", "custom"),
            created_by=template_data.get("created_by"),
            updated_by=template_data.get("updated_by"),
            create_time=now,
            update_time=now,
        )
        session.add(template)
        session.flush()
        return _to_dict(template)


def update_prompt_template(
    template_id: int,
    tenant_id: str,
    template_data: Dict[str, Any]
) -> Dict[str, Any]:
    ensure_prompt_template_table()
    with get_db_session() as session:
        template = session.query(PromptTemplateInfo).filter(
            PromptTemplateInfo.template_id == template_id,
            PromptTemplateInfo.tenant_id == tenant_id,
            PromptTemplateInfo.delete_flag != "Y"
        ).first()
        if not template:
            raise ValueError(f"Prompt template not found: {template_id}")

        next_name = template_data.get("template_name", template.template_name)
        duplicate = session.query(PromptTemplateInfo).filter(
            PromptTemplateInfo.tenant_id == tenant_id,
            PromptTemplateInfo.template_name == next_name,
            PromptTemplateInfo.template_type == template.template_type,
            PromptTemplateInfo.template_id != template_id,
            PromptTemplateInfo.delete_flag != "Y"
        ).first()
        if duplicate:
            raise ValueError(f"Prompt template already exists: {next_name}")

        if "template_name" in template_data:
            template.template_name = template_data["template_name"]
        if "description" in template_data:
            template.description = template_data["description"]
        if "content_zh" in template_data:
            template.content_zh = template_data["content_zh"]
        if "content_en" in template_data:
            template.content_en = template_data["content_en"]
        if "source" in template_data:
            template.source = template_data["source"]
        if "updated_by" in template_data:
            template.updated_by = template_data["updated_by"]
        template.update_time = datetime.now()

        session.flush()
        return _to_dict(template)


def delete_prompt_template(template_id: int, tenant_id: str, updated_by: Optional[str] = None) -> bool:
    ensure_prompt_template_table()
    with get_db_session() as session:
        template = session.query(PromptTemplateInfo).filter(
            PromptTemplateInfo.template_id == template_id,
            PromptTemplateInfo.tenant_id == tenant_id,
            PromptTemplateInfo.delete_flag != "Y"
        ).first()
        if not template:
            return False

        template.delete_flag = "Y"
        template.update_time = datetime.now()
        if updated_by:
            template.updated_by = updated_by
        session.flush()
        return True
