# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Edit previews return precise errors while keeping private values out of HTTP."""

from unittest.mock import AsyncMock

import pytest
from test.backend.app.test_model_managment_app import client  # noqa: F401


@pytest.mark.parametrize("kind,status", [("missing", 404), ("stale", 409), ("invalid", 400)])
def test_edit_preview_preserves_domain_error_and_hides_private_values(client, mocker, kind, status):
    from contracts.errors.exceptions import ModelOutletConflictError, ModelOutletValidationError
    from management.api.model import model_managment as module
    errors = {"missing": LookupError("controlled-private"), "stale": ModelOutletConflictError(),
              "invalid": ModelOutletValidationError("PARAMETER_VALUE_INVALID", "/temperature")}
    run = mocker.patch.object(module, "run_blocking", new=AsyncMock(side_effect=errors[kind]))
    response = client.post("/model/outlets/42/profile_previews", json={"expected_revision": 1})
    assert response.status_code == status and "controlled-private" not in response.text
    assert run.call_args.args[-3] == 42 and run.call_args.args[-2].expected_revision == 1
    assert run.call_args.args[-1] == "test_tenant"
    if kind == "invalid":
        assert response.json()["detail"] == {"code": "MODEL_OUTLET_INVALID",
            "details": {"category": "PARAMETER_VALUE_INVALID", "field": "/temperature"}}
