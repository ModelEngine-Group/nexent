# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Role arrays reject invalid identities and preserve explicit array authority."""

import pytest

from contracts.roles import has_any_role, invitation_roles, normalize_roles, primary_role, roles_from_record


@pytest.mark.parametrize("values", [[], [None], [""], ["SPEED"], ["DEV", "UNKNOWN"], ["SU", "OPS"]])
def test_invalid_role_arrays_are_rejected(values):
    with pytest.raises(ValueError):
        normalize_roles(values)
    assert not has_any_role(values, {"SU", "DEV", "SPEED"})


def test_normalization_and_compatibility_value():
    assert normalize_roles([" ops ", "dev", "OPS"]) == ("DEV", "OPS")
    assert primary_role(["DEV", "OPS"], "OPS") == "OPS"
    assert roles_from_record({"roles": ["OPS"], "user_role": "SU"}) == ("OPS",)
    assert roles_from_record({"roles": [], "user_role": "SU"}) == ()
    assert roles_from_record({"user_roles": ["OPS"], "roles": ["SU"], "user_role": "SU"}) == ("OPS",)
    assert roles_from_record({"user_roles": [], "user_role": "SU"}) == ()
    assert roles_from_record({"user_role": "DEV"}) == ("DEV",)


def test_invitation_arrays_do_not_fall_back_to_a_more_privileged_type():
    assert invitation_roles({"roles": ["OPS"], "code_type": "ADMIN_INVITE"}) == ("OPS",)
    assert invitation_roles({"code_type": "DEV_INVITE"}) == ("DEV",)
    with pytest.raises(ValueError):
        invitation_roles({"code_type": "TENANT_INVITE"})


def test_ordinary_assignment_rejects_special_identities():
    with pytest.raises(ValueError):
        normalize_roles(["SU"], ordinary_only=True)
    assert has_any_role(["DEV", "OPS"], {"OPS"})
