from http import HTTPStatus

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from consts.model import ModelResponse, ModelConnectStatusEnum
from services.me_model_management_service import get_me_models_impl
from services.model_health_service import check_me_model_connectivity, check_me_connectivity_impl

router = APIRouter(prefix="/me")


@router.get("/model/list")
async def get_me_models(
        type: str = Query(
            default="", description="Model type: embed/chat/rerank"),
        timeout: int = Query(
            default=2, description="Request timeout in seconds")
):
    try:
        filtered_result = await get_me_models_impl(timeout, type)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "code": HTTPStatus.OK,
                "message": "Successfully retrieved",
                "data": filtered_result
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "code": HTTPStatus.INTERNAL_SERVER_ERROR,
                "message": f"Failed to get model list: {str(e)}",
                "data": None
            }
        )


@router.get("/healthcheck")
async def check_me_connectivity(timeout: int = Query(default=2, description="Timeout in seconds")):
    try:
        message, code, status_data = await check_me_connectivity_impl(timeout)
        if code == HTTPStatus.OK:
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    "code": HTTPStatus.OK,
                    "message": message,
                    "data": status_data
                }
            )
        else:
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    "code": code,
                    "message": message,
                    "data": status_data
                }
            )
    except Exception as e:
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "code": HTTPStatus.INTERNAL_SERVER_ERROR,
                "message": f"Connection failed: {str(e)}",
                "data": {
                    "status": "Disconnected",
                    "desc": f"Connection failed: {str(e)}",
                    "connect_status": ModelConnectStatusEnum.UNAVAILABLE.value
                }
            }
        )


@router.get("/model/healthcheck", response_model=ModelResponse)
async def check_me_model_healthcheck(
        model_name: str = Query(..., description="Model name to check")
):
    return await check_me_model_connectivity(model_name)
