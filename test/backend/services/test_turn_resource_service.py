from unittest.mock import patch

import pytest

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from consts.model import (
    TurnResourceInvocationRequest,
    TurnResourceReferenceRequest,
)
from services.turn_resource_service import resolve_turn_resources


def _request(resource_type: str = "skill", resource_id: str = "12"):
    return TurnResourceInvocationRequest(
        resources=[
            TurnResourceReferenceRequest(
                resource_type=resource_type,
                resource_id=resource_id,
                name="Untrusted client name",
            )
        ]
    )


def test_resolve_skill_uses_tenant_scoped_authoritative_data() -> None:
    with patch("services.turn_resource_service.SkillService") as service_class:
        service_class.return_value.get_skill_by_id.return_value = {
            "skill_id": 12,
            "name": "trusted-name",
            "description": "trusted-description",
            "content": "trusted-guide",
        }

        result = resolve_turn_resources(_request(), "tenant-a")

    service_class.assert_called_once_with(tenant_id="tenant-a")
    service_class.return_value.get_skill_by_id.assert_called_once_with(
        skill_id=12,
        tenant_id="tenant-a",
    )
    assert result is not None
    assert result.resources[0].name == "trusted-name"
    assert result.resources[0].content == "trusted-guide"


def test_resolve_skill_rejects_missing_tenant_resource() -> None:
    with patch("services.turn_resource_service.SkillService") as service_class:
        service_class.return_value.get_skill_by_id.return_value = None
        with pytest.raises(AppException) as exc_info:
            resolve_turn_resources(_request(), "tenant-b")

    assert exc_info.value.error_code == ErrorCode.COMMON_RESOURCE_NOT_FOUND


def test_resolve_rejects_reserved_resource_type_until_resolver_exists() -> None:
    with pytest.raises(AppException) as exc_info:
        resolve_turn_resources(_request("mcp", "server-a"), "tenant-a")

    assert exc_info.value.error_code == ErrorCode.COMMON_VALIDATION_ERROR


def test_resolve_deduplicates_same_resource() -> None:
    request = TurnResourceInvocationRequest(
        resources=[
            TurnResourceReferenceRequest(resource_type="skill", resource_id="12"),
            TurnResourceReferenceRequest(resource_type="skill", resource_id="12"),
        ]
    )
    with patch("services.turn_resource_service.SkillService") as service_class:
        service_class.return_value.get_skill_by_id.return_value = {
            "name": "skill-a",
            "description": "",
            "content": "guide",
        }
        result = resolve_turn_resources(request, "tenant-a")

    assert result is not None
    assert len(result.resources) == 1
    service_class.return_value.get_skill_by_id.assert_called_once()
