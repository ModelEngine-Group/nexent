# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unified review HTTP boundary; legacy repository routes remain available."""

from typing import Annotated

from contracts.errors.exceptions import ReviewConflictError, UnauthorizedError
from contracts.review import (
    ResourceType,
    ReviewDecisionRequest,
    ReviewListQuery,
    ReviewSubmissionRequest,
)
from fastapi import APIRouter, Header, HTTPException, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from gateway.authentication.auth import get_current_user_context
from management.services.repository.reviews import (
    decide_repository_review,
    get_repository_review,
    list_repository_reviews,
    submit_repository_review,
)
from pydantic import ValidationError


class ReviewRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                return await original(request)
            except RequestValidationError as exc:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "INVALID_REVIEW_REQUEST",
                        "message": "Invalid review request",
                    },
                ) from exc

        return handler


router = APIRouter(prefix="/reviews", route_class=ReviewRoute)
ReviewId = Annotated[int, Path(ge=1, le=9223372036854775807)]


def identity(authorization):
    try:
        return get_current_user_context(authorization)
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTHENTICATION_REQUIRED",
                "message": "Authentication required",
            },
        ) from exc


def invoke(operation, *args):
    try:
        return operation(*args)
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=403, detail={"code": "REVIEW_FORBIDDEN", "message": str(exc)}
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "REVIEW_NOT_FOUND", "message": "Review record not found"},
        ) from exc
    except ReviewConflictError as exc:
        raise HTTPException(
            status_code=409, detail={"code": str(exc), "message": str(exc)}
        ) from exc


@router.get("")
def list_reviews_api(request: Request, authorization: str | None = Header(None)):
    user_id, tenant_id, role = identity(authorization)
    try:
        query = ReviewListQuery.model_validate(dict(request.query_params))
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REVIEW_REQUEST",
                "message": "Invalid review query",
            },
        ) from exc
    return invoke(list_repository_reviews, user_id, tenant_id, role, query)


@router.post("")
async def submit_review_api(
    payload: ReviewSubmissionRequest, authorization: str | None = Header(None)
):
    user_id, tenant_id, role = identity(authorization)
    try:
        return await submit_repository_review(user_id, tenant_id, role, payload)
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=403, detail={"code": "REVIEW_FORBIDDEN", "message": str(exc)}
        ) from exc
    except ReviewConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "PENDING_REVIEW_EXISTS", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_REVIEW_REQUEST", "message": str(exc)},
        ) from exc


@router.get("/{review_id}")
def get_review_api(review_id: ReviewId, authorization: str | None = Header(None)):
    user_id, tenant_id, role = identity(authorization)
    return invoke(get_repository_review, review_id, user_id, tenant_id, role)


@router.post("/{review_id}/decision")
def decide_review_api(
    review_id: ReviewId,
    payload: ReviewDecisionRequest,
    authorization: str | None = Header(None),
):
    user_id, tenant_id, role = identity(authorization)
    return invoke(
        decide_repository_review, review_id, user_id, tenant_id, role, payload
    )


@router.post("/{resource_type}/{repository_id}/decision")
def legacy_decide_review_api(
    resource_type: ResourceType,
    repository_id: ReviewId,
    payload: ReviewDecisionRequest,
    authorization: str | None = Header(None),
):
    from management.services.repository.reviews import decide_legacy_review

    user_id, tenant_id, role = identity(authorization)
    return invoke(
        decide_legacy_review,
        resource_type,
        repository_id,
        user_id,
        tenant_id,
        role,
        "shared" if payload.decision == "approve" else "rejected",
        payload.reason,
    )


@router.get("/{resource_type}/{repository_id}")
def legacy_get_review_api(
    resource_type: ResourceType,
    repository_id: ReviewId,
    authorization: str | None = Header(None),
):
    from management.services.repository.reviews import get_legacy_repository_review

    user_id, tenant_id, role = identity(authorization)
    return invoke(
        get_legacy_repository_review,
        resource_type,
        repository_id,
        user_id,
        tenant_id,
        role,
    )
