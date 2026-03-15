import logging
from typing import List, Optional

from database.client import get_db_session
from database.db_models import PromptTemplate
from database.prompt_template_db import (
    list_prompt_templates,
    create_prompt_template,
    update_prompt_template,
    delete_prompt_template,
)

logger = logging.getLogger("prompt_template_service")


BUILTIN_TEMPLATES = [
    {
        "name": "通用结构",
        "description": "适用于多种场景的提示词结构，可以根据具体需求增删对应模块",
        "prompt_text": """# 角色：{#InputSlot placeholder="角色名称" mode="input"#}{#/InputSlot#}
{#InputSlot placeholder="角色概述和主要职责的一句话描述" mode="input"#}{#/InputSlot#}

## 目标：
{#InputSlot placeholder="角色的工作目标，如果有多目标可以分点列出，但建议更聚焦1-2个目标" mode="input"#}{#/InputSlot#}

## 技能：
1.  {#InputSlot placeholder="为了实现目标，角色需要具备的技能1" mode="input"#}{#/InputSlot#}
2. {#InputSlot placeholder="为了实现目标，角色需要具备的技能2" mode="input"#}{#/InputSlot#}
3. {#InputSlot placeholder="为了实现目标，角色需要具备的技能3" mode="input"#}{#/InputSlot#}

## 工作流：
1. {#InputSlot placeholder="描述角色工作流程的第一步" mode="input"#}{#/InputSlot#}
2. {#InputSlot placeholder="描述角色工作流程的第二步" mode="input"#}{#/InputSlot#}
3. {#InputSlot placeholder="描述角色工作流程的第三步" mode="input"#}{#/InputSlot#}

## 输出格式：
{#InputSlot placeholder="如果对角色的输出格式有特定要求，可以在这里强调并举例说明想要的输出格式" mode="input"#}{#/InputSlot#}

## 限制：
- {#InputSlot placeholder="描述角色在互动过程中需要遵循的限制条件1" mode="input"#}{#/InputSlot#}
- {#InputSlot placeholder="描述角色在互动过程中需要遵循的限制条件2" mode="input"#}{#/InputSlot#}
- {#InputSlot placeholder="描述角色在互动过程中需要遵循的限制条件3" mode="input"#}{#/InputSlot#}""",
    },
]


def ensure_builtin_templates(tenant_id: str, user_id: str) -> None:
    with get_db_session() as session:
        for template in BUILTIN_TEMPLATES:
            existing = session.query(PromptTemplate).filter(
                PromptTemplate.tenant_id == tenant_id,
                PromptTemplate.name == template["name"],
                PromptTemplate.is_builtin == True
            ).first()
            if existing:
                existing.description = template["description"]
                existing.prompt_text = template["prompt_text"]
                if existing.delete_flag == "Y":
                    existing.delete_flag = "N"
                existing.updated_by = user_id
                continue

            new_template = PromptTemplate(
                name=template["name"],
                description=template["description"],
                prompt_text=template["prompt_text"],
                is_builtin=True,
                tenant_id=tenant_id,
                created_by=user_id,
                updated_by=user_id,
                delete_flag="N",
            )
            session.add(new_template)


def list_templates(tenant_id: str, user_id: str, keyword: Optional[str] = None) -> List[dict]:
    ensure_builtin_templates(tenant_id, user_id)
    return list_prompt_templates(tenant_id, keyword)


def create_template(tenant_id: str, user_id: str, payload: dict) -> dict:
    return create_prompt_template(payload, tenant_id, user_id)


def update_template(tenant_id: str, user_id: str, template_id: int, payload: dict) -> dict:
    return update_prompt_template(template_id, payload, tenant_id, user_id)


def delete_template(tenant_id: str, user_id: str, template_id: int) -> None:
    delete_prompt_template(template_id, tenant_id, user_id)
