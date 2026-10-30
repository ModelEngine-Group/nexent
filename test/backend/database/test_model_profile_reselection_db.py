# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Re-selection may change source identity, never tenant, record or revision."""

from unittest.mock import MagicMock

import pytest
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from test.backend.database.model_outlet_helpers import database, profile, row, statement, update  # noqa: F401


@pytest.mark.parametrize("field,value", [("outlet_id", 13), ("tenant_id", "foreign"),
    ("model_type", "vlm"), ("config_revision", 2)])
def test_reselection_rejects_cross_record_scope_before_update(database, profile, field, value):
    db, _, errors = database
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = row(profile)
    data = profile.model_dump(mode="json")
    if field == "outlet_id":
        data[field] = data["connection"]["credential_ref"]["model_id"] = value
    elif field in {"tenant_id", "model_type"}:
        data["identity"][field] = value
    else:
        data[field] = value
    replacement = ResolvedModelProfile.model_validate(data)
    with pytest.raises(errors.ModelOutletValidationError):
        update(db, profile, session, replacement_base=replacement)
    assert session.execute.call_count == 1


def test_valid_reselection_updates_provider_and_request_id_in_same_revision(database, profile):
    db, _, _ = database
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = row(profile)
    session.execute.return_value.scalar_one_or_none.return_value = 2
    data = profile.model_dump(mode="json")
    data["identity"].update(provider_id="selected-provider", request_model_id="selected-model")
    selected = ResolvedModelProfile.model_validate(data)
    assert update(db, selected, session, replacement_base=selected) == 2
    parameters = statement(session, 1).params
    assert parameters["model_factory"] == "selected-provider"
    assert parameters["model_name"] == "selected-model" and parameters["config_revision"] == 2
