# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""HTTP identity, application ID and failure contracts for independent reviews."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts.errors.exceptions import ReviewConflictError, UnauthorizedError
from management.api.repository import reviews


@pytest.fixture
def client(mocker):
    mocker.patch.object(reviews, "identity", return_value=("user", "tenant", "ADMIN"))
    app = FastAPI()
    app.include_router(reviews.router)
    return TestClient(app)


def test_submission_does_not_require_repository_id(client, mocker):
    operation = mocker.patch.object(
        reviews,
        "submit_repository_review",
        new_callable=AsyncMock,
        return_value={"review_id": "41", "repository_id": None},
    )
    response = client.post(
        "/reviews",
        json={"resource_type": "agent", "source_resource_id": "2", "version_no": 0},
    )
    assert response.status_code == 200
    assert response.json() == {"review_id": "41", "repository_id": None}
    assert operation.await_args.args[:3] == ("user", "tenant", "ADMIN")


@pytest.mark.parametrize(
    "body",
    [
        {"resource_type": "agent", "source_resource_id": "0"},
        {"resource_type": "agent", "source_resource_id": "2", "tenant_id": "other"},
        {"resource_type": "agent", "source_resource_id": "2147483648"},
    ],
)
def test_invalid_submission_is_rejected_before_service(client, mocker, body):
    operation = mocker.patch.object(
        reviews, "submit_repository_review", new_callable=AsyncMock
    )
    response = client.post("/reviews", json=body)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_REVIEW_REQUEST"
    operation.assert_not_called()


def test_decision_uses_application_id_without_revision(client, mocker):
    operation = mocker.patch.object(
        reviews, "decide_repository_review", return_value={"status": "approved"}
    )
    response = client.post(
        "/reviews/9007199254740993/decision", json={"decision": "approve"}
    )
    assert response.status_code == 200
    assert operation.call_args.args[:4] == (9007199254740993, "user", "tenant", "ADMIN")


@pytest.mark.parametrize(
    "error,status,code",
    [
        (LookupError("hidden"), 404, "REVIEW_NOT_FOUND"),
        (UnauthorizedError("forbidden"), 403, "REVIEW_FORBIDDEN"),
        (
            ReviewConflictError("REVIEW_ALREADY_PROCESSED"),
            409,
            "REVIEW_ALREADY_PROCESSED",
        ),
    ],
)
def test_decision_error_mapping(client, mocker, error, status, code):
    mocker.patch.object(reviews, "decide_repository_review", side_effect=error)
    response = client.post("/reviews/41/decision", json={"decision": "reject"})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


def test_bigint_detail_and_approved_filter(client, mocker):
    detail = mocker.patch.object(
        reviews, "get_repository_review", return_value={"review_id": "9007199254740993"}
    )
    assert client.get("/reviews/9007199254740993").status_code == 200
    assert detail.call_args.args[0] == 9007199254740993
    query = mocker.patch.object(
        reviews, "list_repository_reviews", return_value={"items": []}
    )
    assert client.get("/reviews?resource_type=skill&status=approved").status_code == 200
    assert query.call_args.args[-1].resource_type == "skill"
    assert client.get("/reviews?status=not_shared").status_code == 400
