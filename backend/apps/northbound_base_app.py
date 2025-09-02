from http import HTTPStatus
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .northbound_app import router as northbound_router
from consts.exceptions import LimitExceededError, UnauthorizedError, SignatureValidationError

logger = logging.getLogger("northbound_base_app")


northbound_app = FastAPI(
    title="Nexent Northbound API",
    description="Northbound APIs for partners",
    version="1.0.0",
    root_path="/api"
)

northbound_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


northbound_app.include_router(northbound_router)


@northbound_app.exception_handler(HTTPException)
async def northbound_http_exception_handler(request, exc):
    logger.error(f"Northbound HTTPException: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": exc.detail},
    )


@northbound_app.exception_handler(Exception)
async def northbound_generic_exception_handler(request, exc):
    logger.error(f"Northbound Generic Exception: {exc}")
    return JSONResponse(
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        content={"message": "Internal server error, please try again later."},
    )
