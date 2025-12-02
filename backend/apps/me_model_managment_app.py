import logging
from http import HTTPStatus

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse

from consts.exceptions import MEConnectionException, TimeoutException
from services.me_model_management_service import check_me_variable_set, check_me_connectivity

router = APIRouter(prefix="/me")


@router.get("/healthcheck")
async def check_me_health(timeout: int = Query(default=30, description="Timeout in seconds")):
    """
    Health check for ModelEngine platform by actually calling the API.
    Returns connectivity status based on actual API response.
    """
    try:
        # First check if environment variables are configured
        if not await check_me_variable_set():
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    "connectivity": False,
                    "message": "ModelEngine platform environment variables not configured. Healthcheck skipped.",
                }
            )
        
        # Then check actual connectivity
        await check_me_connectivity(timeout)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "connectivity": True,
                "message": "ModelEngine platform connected successfully.",
            }
        )
    except MEConnectionException as e:
        logging.error(f"ModelEngine healthcheck failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail=f"ModelEngine connection failed: {str(e)}")
    except TimeoutException as e:
        logging.error(f"ModelEngine healthcheck timeout: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.REQUEST_TIMEOUT, detail="ModelEngine connection timeout.")
    except Exception as e:
        logging.error(f"ModelEngine healthcheck failed with unknown error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"ModelEngine healthcheck failed: {str(e)}")
