# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""HTTP identity, application ID and failure contracts for independent reviews."""

from unittest.mock import AsyncMock

import pytest
from contracts.errors.exceptions import ReviewConflictError, UnauthorizedError
from fastapi import FastAPI
from fastapi.testclient import TestClient
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
    operation = mocker.patch.object(reviews, "submit_repository_review", new_callable=AsyncMock)
    response = client.post("/reviews", json=body)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_REVIEW_REQUEST"
    operation.assert_not_called()


def test_decision_uses_application_id_without_revision(client, mocker):
    operation = mocker.patch.object(reviews, "decide_repository_review", return_value={"status": "approved"})
    response = client.post("/reviews/9007199254740993/decision", json={"decision": "approve"})
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
    detail = mocker.patch.object(reviews, "get_repository_review", return_value={"review_id": "9007199254740993"})
    assert client.get("/reviews/9007199254740993").status_code == 200
    assert detail.call_args.args[0] == 9007199254740993
    query = mocker.patch.object(reviews, "list_repository_reviews", return_value={"items": []})
    assert client.get("/reviews?resource_type=skill&status=approved").status_code == 200
    assert query.call_args.args[-1].resource_type == "skill"
    assert client.get("/reviews?status=not_shared").status_code == 400


def test_expired_identity_returns_401_without_service_lookup(mocker):
    mocker.patch.object(reviews, "get_current_user_context", side_effect=UnauthorizedError("expired"))
    app = FastAPI()
    app.include_router(reviews.router)
    operation = mocker.patch.object(reviews, "list_repository_reviews")
    response = TestClient(app).get("/reviews")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTHENTICATION_REQUIRED"
    operation.assert_not_called()


@pytest.mark.parametrize(
    "error,status,code",
    [
        (UnauthorizedError("denied"), 403, "REVIEW_FORBIDDEN"),
        (ReviewConflictError("pending"), 409, "PENDING_REVIEW_EXISTS"),
        (ValueError("invalid"), 400, "INVALID_REVIEW_REQUEST"),
    ],
)
def test_submission_maps_domain_failures(client, mocker, error, status, code):
    mocker.patch.object(reviews, "submit_repository_review", new_callable=AsyncMock, side_effect=error)
    response = client.post("/reviews", json={"resource_type": "skill", "source_resource_id": "3"})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


@pytest.mark.parametrize("kind", ["agent", "skill", "mcp"])
def test_legacy_detail_preserves_resource_and_repository_identity(client, mocker, kind):
    operation = mocker.patch(
        "management.services.repository.reviews.get_legacy_repository_review", return_value={"review_id": "123"}
    )
    response = client.get(f"/reviews/{kind}/9007199254740993")
    assert response.json() == {"review_id": "123"}
    operation.assert_called_once_with(kind, 9007199254740993, "user", "tenant", "ADMIN")


@pytest.mark.parametrize("decision,status", [("approve", "shared"), ("reject", "rejected")])
def test_legacy_decision_passes_authenticated_identity(client, mocker, decision, status):
    operation = mocker.patch(
        "management.services.repository.reviews.decide_legacy_review", return_value={"status": status}
    )
    response = client.post("/reviews/skill/42/decision", json={"decision": decision, "reason": "note"})
    assert response.json() == {"status": status}
    operation.assert_called_once_with("skill", 42, "user", "tenant", "ADMIN", status, "note")
