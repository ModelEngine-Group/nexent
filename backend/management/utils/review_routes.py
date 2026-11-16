# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Keep review validation errors stable at the HTTP routing boundary."""

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute


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


