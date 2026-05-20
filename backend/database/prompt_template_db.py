import logging
from typing import Optional

from sqlalchemy import select, update

from database.client import as_dict, filter_property, get_db_session
from database.db_models import PromptTemplate

logger = logging.getLogger("prompt_template_db")


def create_prompt_template(template_data: dict) -> dict:
    """Create a prompt template."""
    with get_db_session() as session:
        prompt_template = PromptTemplate(
            **filter_property(template_data, PromptTemplate)
        )
        prompt_template.delete_flag = "N"
        session.add(prompt_template)
        session.flush()
        return as_dict(prompt_template)


def upsert_prompt_template_by_id(template_id: int, template_data: dict, user_id: str) -> dict:
    """Create or update a prompt template with a fixed template ID."""
    with get_db_session() as session:
        prompt_template = session.query(PromptTemplate).filter(
            PromptTemplate.template_id == template_id,
        ).first()

        filtered_data = filter_property(template_data, PromptTemplate)
        if prompt_template:
            for key, value in filtered_data.items():
                setattr(prompt_template, key, value)
            prompt_template.updated_by = user_id
        else:
            prompt_template = PromptTemplate(**filtered_data)
            prompt_template.template_id = template_id
            prompt_template.delete_flag = filtered_data.get("delete_flag", "N")
            session.add(prompt_template)

        session.flush()
        return as_dict(prompt_template)


def update_prompt_template(template_id: int, template_data: dict, user_id: str) -> dict:
    """Update a prompt template."""
    with get_db_session() as session:
        prompt_template = session.query(PromptTemplate).filter(
            PromptTemplate.template_id == template_id,
            PromptTemplate.delete_flag == "N",
        ).first()

        if not prompt_template:
            raise ValueError("prompt template not found")

        for key, value in filter_property(template_data, PromptTemplate).items():
            if value is None:
                continue
            setattr(prompt_template, key, value)

        prompt_template.updated_by = user_id
        session.flush()
        return as_dict(prompt_template)


def delete_prompt_template(template_id: int, user_id: str) -> int:
    """Soft-delete a prompt template."""
    with get_db_session() as session:
        result = session.execute(
            update(PromptTemplate)
            .where(
                PromptTemplate.template_id == template_id,
                PromptTemplate.delete_flag == "N",
            )
            .values(delete_flag="Y", updated_by=user_id)
        )
        return result.rowcount


def query_prompt_templates_by_user(
    tenant_id: str,
    user_id: str,
    template_type: str = "agent_generate",
) -> list[dict]:
    """Query prompt templates by tenant and user."""
    with get_db_session() as session:
        templates = session.query(PromptTemplate).filter(
            PromptTemplate.tenant_id == tenant_id,
            PromptTemplate.user_id == user_id,
            PromptTemplate.template_type == template_type,
            PromptTemplate.delete_flag == "N",
        ).order_by(PromptTemplate.update_time.desc(), PromptTemplate.template_id.desc()).all()
        return [as_dict(template) for template in templates]


def get_prompt_template_by_id(
    template_id: int,
    tenant_id: str,
    user_id: str,
    template_type: str = "agent_generate",
) -> Optional[dict]:
    """Get a prompt template by ID."""
    with get_db_session() as session:
        template = session.query(PromptTemplate).filter(
            PromptTemplate.template_id == template_id,
            PromptTemplate.tenant_id == tenant_id,
            PromptTemplate.user_id == user_id,
            PromptTemplate.template_type == template_type,
            PromptTemplate.delete_flag == "N",
        ).first()
        return as_dict(template) if template else None


def get_prompt_template_by_name(
    template_name: str,
    tenant_id: str,
    user_id: str,
    template_type: str = "agent_generate",
) -> Optional[dict]:
    """Get a prompt template by name."""
    with get_db_session() as session:
        template = session.query(PromptTemplate).filter(
            PromptTemplate.template_name == template_name,
            PromptTemplate.tenant_id == tenant_id,
            PromptTemplate.user_id == user_id,
            PromptTemplate.template_type == template_type,
            PromptTemplate.delete_flag == "N",
        ).first()
        return as_dict(template) if template else None


def get_prompt_template_by_template_id(
    template_id: int,
    template_type: str = "agent_generate",
    include_deleted: bool = False,
) -> Optional[dict]:
    """Get a prompt template by template ID regardless of owner."""
    with get_db_session() as session:
        query = session.query(PromptTemplate).filter(
            PromptTemplate.template_id == template_id,
            PromptTemplate.template_type == template_type,
        )
        if not include_deleted:
            query = query.filter(PromptTemplate.delete_flag == "N")
        template = query.first()
        return as_dict(template) if template else None


def query_prompt_template_names(
    tenant_id: str,
    user_id: str,
    template_type: str = "agent_generate",
) -> set[str]:
    """Query all active prompt template names for the current user."""
    with get_db_session() as session:
        rows = session.execute(
            select(PromptTemplate.template_name).where(
                PromptTemplate.tenant_id == tenant_id,
                PromptTemplate.user_id == user_id,
                PromptTemplate.template_type == template_type,
                PromptTemplate.delete_flag == "N",
            )
        ).all()
        return {row[0] for row in rows if row and row[0]}
