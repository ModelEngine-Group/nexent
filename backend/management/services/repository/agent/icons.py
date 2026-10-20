# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import uuid
from typing import Dict

from database.agent_db import search_agent_info_by_agent_id
from database.agent_repository_db import get_agent_repository_by_agent_id
from management.services.agent.icon import read_icon_image, upload_icon_image


async def upload_agent_repository_icon_impl(
    agent_id: int, version_no: int, tenant_id: str, user_id: str, content: bytes
) -> Dict[str, str]:
    if version_no < 0:
        raise ValueError("version_no must be >= 0")
    agent_info = search_agent_info_by_agent_id(agent_id, tenant_id, version_no)
    if not agent_info:
        raise ValueError("Agent version not found")
    _validate_create_listing_permission(user_id=user_id, agent_info=agent_info)
    image_id = str(uuid.uuid4())
    content_type = upload_icon_image(
        content, _repository_icon_object_name(tenant_id, agent_id, version_no, image_id)
    )
    return {
        "icon_url": _repository_icon_url(agent_id, version_no, image_id),
        "content_type": content_type,
    }


def get_agent_repository_icon_impl(
    agent_id: int, version_no: int, image_id: str, tenant_id: str
) -> tuple[bytes, str]:
    listing = get_agent_repository_by_agent_id(
        agent_id, version_no, publisher_tenant_id=tenant_id
    )
    if not listing or listing.get("icon_url") != _repository_icon_url(
        agent_id, version_no, image_id
    ):
        raise FileNotFoundError("Repository icon not found")
    return read_icon_image(
        _repository_icon_object_name(tenant_id, agent_id, version_no, image_id)
    )


from management.services.repository.agent.common import (
    _repository_icon_object_name,
    _repository_icon_url,
    _repository_image_id,
    _validate_create_listing_permission,
)
