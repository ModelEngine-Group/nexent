# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Operations-only HTTP isolation covers every method without weakening other roles."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from permissions.operations_boundary import install_operations_boundary


@pytest.mark.parametrize(
    "roles,method,authorization,status",
    [
        (("OPS",), "GET", "Bearer owned", 403),
        (("OPS",), "POST", "owned", 403),
        (("OPS",), "PUT", "Bearer owned", 403),
        (("OPS",), "DELETE", "owned", 403),
        (("DEV", "OPS"), "POST", "owned", 200),
        (("ADMIN", "OPS"), "PUT", "Bearer owned", 200),
        (("SU",), "DELETE", "Bearer owned", 200),
    ],
)
def test_business_boundary(mocker, roles, method, authorization, status):
    mocker.patch(
        "permissions.operations_boundary.get_current_user_context",
        return_value=("actor", "a", roles),
    )
    app = FastAPI()
    install_operations_boundary(app)
    app.add_api_route("/business", lambda: {"ok": True}, methods=[method])
    with TestClient(app) as client:
        response = client.request(method, "/business", headers={"Authorization": authorization})
    assert response.status_code == status


@pytest.mark.parametrize(
    "path,method",
    [
        ("/ops/resources", "GET"),
        ("/user/current_user_info", "GET"),
        ("/user/logout", "POST"),
        ("/tenant_config/deployment_version", "GET"),
    ],
)
def test_allowed_paths_keep_endpoint_authorization(mocker, path, method):
    mocker.patch("permissions.operations_boundary.get_current_user_context", return_value=("actor", "a", ("OPS",)))
    app = FastAPI()
    install_operations_boundary(app)
    app.add_api_route(path, lambda: {"ok": True}, methods=[method])
    with TestClient(app) as client:
        assert client.request(method, path, headers={"Authorization": "Bearer owned"}).status_code == 200
