import logging
from typing import List, Optional

from sqlalchemy import or_

from database.client import get_db_session, as_dict, filter_property
from database.db_models import PromptTemplate

logger = logging.getLogger("prompt_template_db")


def list_prompt_templates(tenant_id: str, keyword: Optional[str] = None) -> List[dict]:
    with get_db_session() as session:
        query = session.query(PromptTemplate).filter(
            PromptTemplate.tenant_id == tenant_id,
            PromptTemplate.delete_flag != "Y"
        )
        if keyword:
            like_keyword = f"%{keyword}%"
            query = query.filter(
                or_(
                    PromptTemplate.name.ilike(like_keyword),
                    PromptTemplate.description.ilike(like_keyword),
                    PromptTemplate.prompt_text.ilike(like_keyword),
                )
            )
        templates = query.order_by(PromptTemplate.update_time.desc()).all()
        return [as_dict(t) for t in templates]


def get_prompt_template_by_id(template_id: int, tenant_id: str) -> Optional[dict]:
    with get_db_session() as session:
        template = session.query(PromptTemplate).filter(
            PromptTemplate.template_id == template_id,
            PromptTemplate.tenant_id == tenant_id,
            PromptTemplate.delete_flag != "Y"
        ).first()
        return as_dict(template) if template else None


def create_prompt_template(
    template_info: dict,
    tenant_id: str,
    user_id: str
) -> dict:
    info_with_metadata = dict(template_info)
    info_with_metadata.update({
        "tenant_id": tenant_id,
        "created_by": user_id,
        "updated_by": user_id,
    })
    with get_db_session() as session:
        new_template = PromptTemplate(
            **filter_property(info_with_metadata, PromptTemplate)
        )
        new_template.delete_flag = "N"
        session.add(new_template)
        session.flush()
        return as_dict(new_template)


def update_prompt_template(
    template_id: int,
    template_info: dict,
    tenant_id: str,
    user_id: str
) -> dict:
    with get_db_session() as session:
        template = session.query(PromptTemplate).filter(
            PromptTemplate.template_id == template_id,
            PromptTemplate.tenant_id == tenant_id,
            PromptTemplate.delete_flag != "Y"
        ).first()
        if not template:
            raise ValueError("prompt template not found")

        for key, value in filter_property(template_info, PromptTemplate).items():
            if value is None:
                continue
            setattr(template, key, value)
        template.updated_by = user_id
        session.flush()
        return as_dict(template)


def delete_prompt_template(
    template_id: int,
    tenant_id: str,
    user_id: str
) -> None:
    with get_db_session() as session:
        template = session.query(PromptTemplate).filter(
            PromptTemplate.template_id == template_id,
            PromptTemplate.tenant_id == tenant_id,
            PromptTemplate.delete_flag != "Y"
        ).first()
        if not template:
            raise ValueError("prompt template not found")
        template.delete_flag = "Y"
        template.updated_by = user_id
